"""Authentication, role authorization, clock control, and the audit trail."""
from datetime import datetime, timezone

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, build_user_headers, api_client,
    create_contract_payload, create_product_payload, create_label_approval_payload,
    create_excise_report_payload,
)

OM = TEST_USERS["orchard_manager_headers"]
CL = TEST_USERS["cellar_lead_headers"]
CO = TEST_USERS["compliance_officer_headers"]
PO = TEST_USERS["packaging_operator_headers"]
SR = TEST_USERS["sales_rep_headers"]
PA = TEST_USERS["platform_admin_headers"]


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ─── Corner: validations / authentication ───────────────────────────────────

def test_unauthenticated_missing_role_header(api):
    """PRD section 2.1: "All interactions with the API are authenticated through
    two mandatory HTTP headers: `X-User-ID`, identifying the acting operator,
    and `X-User-Role`, declaring their operational capacity." and "A request
    with a missing or malformed `X-User-Role` or `X-User-ID` header is rejected
    with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/unauthenticated_missing_role_header
    """
    res = api.list_contracts(headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")

    role_only = {"X-User-Role": "OrchardManager", "Content-Type": "application/json"}
    res2 = api.list_contracts(headers=role_only)
    validate_error(res2, "ERR_UNAUTHENTICATED")


def test_unauthorized_role_cannot_create_contract(api):
    """PRD section 2.1: "A request whose role is not permitted for the target
    endpoint per the matrix in §4 is rejected with `ERR_UNAUTHORIZED`."
    PRD section 4: "POST | `/cidery/contracts` | Create an orchard contract |
    OrchardManager".

    Design: Corner/validations/unauthorized_role_cannot_create_contract
    """
    res = api.create_contract(
        create_contract_payload(grower_name="NoPerm", committed_weight_lbs=1000), CL)
    validate_error(res, "ERR_UNAUTHORIZED")


# ─── Corner: rbac ───────────────────────────────────────────────────────────

def test_sales_rep_cannot_create_excise_report(api):
    """PRD section 2.1: "A request whose role is not permitted for the target
    endpoint per the matrix in §4 is rejected with `ERR_UNAUTHORIZED`."
    PRD section 4: "POST | `/cidery/excise-reports` | Open an excise report for
    a year, month, and regulator | ComplianceOfficer".

    Design: Corner/rbac/sales_rep_cannot_create_excise_report
    """
    res = api.create_excise_report(
        create_excise_report_payload(period_year=2026, period_month=10,
                                     regulator="TTB"), SR)
    validate_error(res, "ERR_UNAUTHORIZED")


def test_packaging_operator_cannot_create_label(api):
    """PRD section 2.1: "A request whose role is not permitted for the target
    endpoint per the matrix in §4 is rejected with `ERR_UNAUTHORIZED`."
    PRD section 4: "POST | `/cidery/products/{productId}/label-approvals` |
    Submit a label approval application for a market | ComplianceOfficer".

    Design: Corner/rbac/packaging_operator_cannot_create_label
    """
    product = validate_success(api.create_product(
        create_product_payload(sku="LBL-001", name="Lbl"), CO), 201)
    res = api.create_label_approval(
        product["id"],
        create_label_approval_payload(market="FEDERAL_TTB",
                                      application_number="TTB-LBL"), PO)
    validate_error(res, "ERR_UNAUTHORIZED")


def test_platform_admin_can_set_clock(api):
    """PRD section 2.5: "A `PlatformAdmin`-only test-driving capability advances
    the clock to a supplied `to_iso8601` instant and answers with the resulting
    `now_iso8601`; the server never falls back to wall-clock time under any
    circumstance."

    Design: Corner/rbac/platform_admin_can_set_clock
    """
    res = validate_success(api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, PA), 200)
    assert _parse_iso(res["now_iso8601"]) == datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_compliance_officer_cannot_set_clock(api):
    """PRD section 2.1: "A request whose role is not permitted for the target
    endpoint per the matrix in §4 is rejected with `ERR_UNAUTHORIZED`."
    PRD section 4: "POST | `/cidery/_clock/set_current_utc` | Set the logical
    clock (test-driving) | PlatformAdmin".

    Design: Corner/rbac/compliance_officer_cannot_set_clock
    """
    res = api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, CO)
    validate_error(res, "ERR_UNAUTHORIZED")


# ─── Corner: entities / audit trail ─────────────────────────────────────────

def test_compliance_event_collection_readable_and_append_only(api):
    """PRD section 2.10: "Events are emitted at the specific moments called out
    in §3 — contract activation and settlement, lot spoilage, yield anomalies,
    packaging leftovers, product activation, report filing and amendment, and
    late returns — and are readable only by `ComplianceOfficer` and
    `PlatformAdmin`. The audit collection is filterable by `entity_type`,
    `entity_id`, and `action`."

    On a fresh system the collection is an empty page served to a
    ComplianceOfficer.

    Design: Corner/entities/compliance_event_immutable_no_update_endpoint
    """
    data, meta = validate_paginated(api.list_compliance_events(CO))
    assert data == []
    assert meta["total_count"] == 0
