"""Composite setup helpers.

Every test runs against an empty database, so each helper builds its
preconditions from scratch using only endpoints the PRD declares. Setup calls
use the lenient `get_success_data` validator so a broken precondition surfaces
as a clear "Setup step failed" rather than a confusing assertion later.

Canonical economics used throughout (matching PRD calculations):
  entry duty_paid 82500 over line_quantity 100 -> per-unit eligible 825
  direct line qty 40 -> round_half_up(0.99 * 825 * 40) = 32670
  settled invoice fee on 32670 @ 2500 bps -> 8168
  accrued fee on approved 32670 -> fee(round_half_up(32670 * 0.8)) = 6534
"""
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_audit_case_payload,
    create_binding_ruling_payload,
    create_claim_line_payload,
    create_claim_payload,
    create_classification_payload,
    create_client_b_payload,
    create_client_payload,
    create_export_shipment_payload,
    create_import_entry_payload,
    create_tariff_measure_payload,
)
from .test_users import (
    ANALYST_USER,
    BROKER_USER,
    TEST_USERS,
    make_analyst_headers,
    make_broker_headers,
)

ADMIN = TEST_USERS["firm_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
BROKER = TEST_USERS["broker_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# ---------------------------------------------------------------------------
# Tier 0 — primitive steps
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """Set the logical clock (FirmAdmin only, PRD 2.8)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def onboard_client(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_client(create_client_payload(**overrides), ADMIN))


def onboard_client_b(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_client(create_client_b_payload(**overrides), ADMIN))


def add_classification(client_id: str, **overrides) -> Dict[str, Any]:
    """Create a classification in DRAFT as the analyst."""
    return get_success_data(
        api_client.create_classification(
            create_classification_payload(client_id, **overrides),
            make_analyst_headers(),
        )
    )


def submit_classification(classification_id: str, user_id: str = ANALYST_USER) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_classification(classification_id, make_analyst_headers(user_id))
    )


def certify_classification(classification_id: str, user_id: str = BROKER_USER) -> Dict[str, Any]:
    return get_success_data(
        api_client.review_classification(
            classification_id, {"decision": "CERTIFY"}, make_broker_headers(user_id)
        )
    )


def add_certified_classification(client_id: str, **overrides) -> Dict[str, Any]:
    """Create -> submit -> certify. Returns the CERTIFIED classification."""
    cls = add_classification(client_id, **overrides)
    submit_classification(cls["id"])
    return certify_classification(cls["id"])


def add_import_entry(client_id: str, classification_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_import_entry(
            create_import_entry_payload(client_id, classification_id, **overrides),
            make_analyst_headers(),
        )
    )


def add_export_shipment(client_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_export_shipment(
            create_export_shipment_payload(client_id, **overrides),
            make_analyst_headers(),
        )
    )


def add_claim(client_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_claim(
            create_claim_payload(client_id, **overrides),
            make_analyst_headers(),
        )
    )


def add_claim_line(
    claim_id: str, import_entry_id: str, export_shipment_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.add_claim_line(
            claim_id,
            create_claim_line_payload(import_entry_id, export_shipment_id, **overrides),
            make_analyst_headers(),
        )
    )


def file_claim(claim_id: str, user_id: str = BROKER_USER) -> Dict[str, Any]:
    return get_success_data(api_client.file_claim(claim_id, make_broker_headers(user_id)))


def approve_claim(claim_id: str, approved_duty_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api_client.review_claim(
            claim_id, {"outcome": "APPROVED", "approved_duty_cents": approved_duty_cents},
            make_broker_headers(),
        )
    )


def record_payment(claim_id: str, paid_duty_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_payment(claim_id, {"paid_duty_cents": paid_duty_cents}, ADMIN)
    )


def get_invoice_for_claim(claim_id: str) -> Dict[str, Any]:
    data = get_success_data(api_client.list_invoices(ADMIN, params={"claim_id": claim_id}))
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one invoice for claim {claim_id}, got {data}"
    )
    return data[0]


def get_records_for_claim(claim_id: str) -> List[Dict[str, Any]]:
    data = get_success_data(api_client.list_records(COMPLIANCE, params={"claim_id": claim_id}))
    assert isinstance(data, list), "records list must be an array"
    return data


# ---------------------------------------------------------------------------
# Tier 2 — entity hierarchy: client + certified classification + entry/export
# ---------------------------------------------------------------------------


def setup_trade_scenario(
    client_overrides: Optional[Dict] = None,
    classification_overrides: Optional[Dict] = None,
    entry_overrides: Optional[Dict] = None,
    export_overrides: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Client (ACTIVE) + CERTIFIED classification + one import entry + one
    export shipment. Returns a ctx dict with client/classification/entry/export."""
    client = onboard_client(**(client_overrides or {}))
    cls = add_certified_classification(client["id"], **(classification_overrides or {}))
    entry = add_import_entry(client["id"], cls["id"], **(entry_overrides or {}))
    export = add_export_shipment(client["id"], **(export_overrides or {}))
    return {"client": client, "classification": cls, "entry": entry, "export": export}


def setup_two_entry_scenario() -> Dict[str, Any]:
    """Client + CERTIFIED classification + two identical entries (E100/E200)
    + two exports. Used by tests needing parallel twin claims."""
    client = onboard_client()
    cls = add_certified_classification(client["id"])
    entry_a = add_import_entry(client["id"], cls["id"], entry_number="E100")
    entry_b = add_import_entry(client["id"], cls["id"], entry_number="E200")
    export_a = add_export_shipment(client["id"], export_date="2026-04-01T00:00:00Z")
    export_b = add_export_shipment(client["id"], export_date="2026-04-02T00:00:00Z")
    return {
        "client": client,
        "classification": cls,
        "entry_a": entry_a,
        "entry_b": entry_b,
        "export_a": export_a,
        "export_b": export_b,
    }


# ---------------------------------------------------------------------------
# Tier 3 — claim lifecycle shortcuts
# ---------------------------------------------------------------------------


def setup_draft_claim_with_line(
    matched_quantity: int = 40,
    claim_overrides: Optional[Dict] = None,
    **scenario_kwargs,
) -> Dict[str, Any]:
    """Trade scenario + DRAFT claim with one ACTIVE line. Returns ctx with
    claim and line added."""
    ctx = setup_trade_scenario(**scenario_kwargs)
    claim = add_claim(ctx["client"]["id"], **(claim_overrides or {}))
    line = add_claim_line(
        claim["id"], ctx["entry"]["id"], ctx["export"]["id"],
        matched_quantity=matched_quantity,
    )
    ctx.update({"claim": claim, "line": line})
    return ctx


def setup_filed_claim(matched_quantity: int = 40, **scenario_kwargs) -> Dict[str, Any]:
    """DRAFT claim with one line, then FILED by the broker. claimed frozen."""
    ctx = setup_draft_claim_with_line(matched_quantity=matched_quantity, **scenario_kwargs)
    ctx["claim"] = file_claim(ctx["claim"]["id"])
    return ctx


def setup_approved_claim(
    matched_quantity: int = 40, approved_duty_cents: int = 32670, **scenario_kwargs
) -> Dict[str, Any]:
    ctx = setup_filed_claim(matched_quantity=matched_quantity, **scenario_kwargs)
    ctx["claim"] = approve_claim(ctx["claim"]["id"], approved_duty_cents)
    return ctx


def setup_paid_claim(
    matched_quantity: int = 40, approved_duty_cents: int = 32670, **scenario_kwargs
) -> Dict[str, Any]:
    """Full lifecycle through PAID; invoice auto-created; records get
    retention_until = paid_at + 3 years."""
    ctx = setup_approved_claim(
        matched_quantity=matched_quantity,
        approved_duty_cents=approved_duty_cents,
        **scenario_kwargs,
    )
    ctx["claim"] = record_payment(ctx["claim"]["id"], approved_duty_cents)
    ctx["invoice"] = get_invoice_for_claim(ctx["claim"]["id"])
    return ctx


def setup_two_paid_claims() -> Dict[str, Any]:
    """Two fully-processed claims (32670 each, disjoint periods, separate
    entries/exports), producing two ISSUED invoices of fee_cents 8168."""
    ctx = setup_two_entry_scenario()
    client = ctx["client"]

    claim_a = add_claim(
        client["id"], period_start="2026-01-01T00:00:00Z", period_end="2026-03-31T00:00:00Z"
    )
    add_claim_line(claim_a["id"], ctx["entry_a"]["id"], ctx["export_a"]["id"], matched_quantity=40)
    file_claim(claim_a["id"])
    approve_claim(claim_a["id"], 32670)
    record_payment(claim_a["id"], 32670)

    claim_b = add_claim(
        client["id"], period_start="2026-04-01T00:00:00Z", period_end="2026-06-30T00:00:00Z"
    )
    add_claim_line(claim_b["id"], ctx["entry_b"]["id"], ctx["export_b"]["id"], matched_quantity=40)
    file_claim(claim_b["id"])
    approve_claim(claim_b["id"], 32670)
    record_payment(claim_b["id"], 32670)

    ctx.update({
        "claim_a": claim_a,
        "claim_b": claim_b,
        "invoice_a": get_invoice_for_claim(claim_a["id"]),
        "invoice_b": get_invoice_for_claim(claim_b["id"]),
    })
    return ctx


# ---------------------------------------------------------------------------
# Audit helpers
# ---------------------------------------------------------------------------


def add_audit_case(client_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_audit_case(create_audit_case_payload(client_id, **overrides), ADMIN)
    )


def advance_audit(audit_id: str, action: str, **extra) -> Dict[str, Any]:
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(api_client.advance_audit(audit_id, payload, COMPLIANCE))


def setup_audit_in_evidence(client_id: str, **overrides) -> Dict[str, Any]:
    """Audit OPENED -> EVIDENCE_GATHERING."""
    case = add_audit_case(client_id, **overrides)
    return advance_audit(case["id"], "START_EVIDENCE")


def setup_audit_response_filed(client_id: str, **overrides) -> Dict[str, Any]:
    """Audit OPENED -> EVIDENCE_GATHERING -> RESPONSE_FILED."""
    case = setup_audit_in_evidence(client_id, **overrides)
    return advance_audit(case["id"], "FILE_RESPONSE")


# ---------------------------------------------------------------------------
# Measure helpers
# ---------------------------------------------------------------------------


def add_measure(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_tariff_measure(create_tariff_measure_payload(**overrides), ADMIN)
    )
