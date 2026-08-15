"""Composite setup helpers.

Every helper builds its preconditions from scratch via PRD-declared endpoints
(the harness restarts the server before each test, so the DB starts empty).
All setup calls go through get_success_data() so setup failures surface as
clear 'Setup failed' errors, not confusing assertion failures.

Identity threading: all roles are opaque (X-User-ID is an operator id, never
compared to entity ids). SoD compares operator ids against recorded *_by_id
fields, so helpers that drive multi-operator flows thread explicit operator
ids via make_*_headers(user_id).
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_branch_payload,
    create_customer_payload,
    create_cash_transaction_payload,
    create_instrument_sale_payload,
    create_exemption_designation_payload,
    create_structuring_alert_payload,
    create_examination_case_payload,
    create_finding_payload,
)
from .test_users import (
    make_admin_headers,
    make_manager_headers,
    make_teller_headers,
    make_analyst_headers,
    make_officer_headers,
    make_examiner_headers,
)


# ---------------------------------------------------------------------------
# Tier 1: state progression + basic seed
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the logical clock as SystemAdmin."""
    resp = api_client.set_clock(to_iso8601, headers=make_admin_headers())
    return get_success_data(resp)


def create_branch(**overrides) -> dict:
    resp = api_client.create_branch(create_branch_payload(**overrides), headers=make_admin_headers())
    return get_success_data(resp)


def create_customer(**overrides) -> dict:
    resp = api_client.create_customer(create_customer_payload(**overrides), headers=make_manager_headers())
    return get_success_data(resp)


def setup_branch_and_customer(
    clock: str = "2026-08-01T09:00:00Z",
    customer_overrides: Optional[dict] = None,
    branch_overrides: Optional[dict] = None,
):
    """Clock set + branch ACTIVE + customer ACTIVE. Returns (branch, customer)."""
    set_clock(clock)
    branch = create_branch(**(branch_overrides or {}))
    customer = create_customer(**(customer_overrides or {}))
    return branch, customer


def post_cash_txn(
    customer_id: str,
    branch_id: str,
    *,
    direction: str = "CASH_IN",
    amount_cents: int = 100_000,
    occurred_at: str = "2026-08-01T08:00:00Z",
    teller_id: str = "teller-1",
    **extra,
) -> dict:
    payload = create_cash_transaction_payload(
        customer_id, branch_id,
        direction=direction, amount_cents=amount_cents, occurred_at=occurred_at,
        **extra,
    )
    resp = api_client.create_cash_transaction(payload, headers=make_teller_headers(teller_id))
    return get_success_data(resp)


def post_instrument_sale(
    customer_id: str,
    branch_id: str,
    *,
    instrument_type: str = "CASHIERS_CHECK",
    amount_cents: int = 100_000,
    occurred_at: str = "2026-08-01T08:00:00Z",
    teller_id: str = "teller-1",
    **extra,
) -> dict:
    payload = create_instrument_sale_payload(
        customer_id, branch_id,
        instrument_type=instrument_type, amount_cents=amount_cents,
        occurred_at=occurred_at, **extra,
    )
    resp = api_client.create_instrument_sale(payload, headers=make_teller_headers(teller_id))
    return get_success_data(resp)


def list_ctrs_for_customer(customer_id: str, *, status: Optional[str] = None) -> tuple:
    """Returns (data_list, meta)."""
    params = {"customer_id": customer_id}
    if status:
        params["status"] = status
    resp = api_client.list_ctrs(headers=make_officer_headers(), params=params)
    body = resp.json()
    return body["data"], body["meta"]


def get_single_ctr_for_customer(customer_id: str) -> dict:
    data, _meta = list_ctrs_for_customer(customer_id)
    assert len(data) == 1, f"Expected exactly one CTR for customer {customer_id}, got {len(data)}"
    return data[0]


def get_aggregation_for(customer_id: str, business_date: str) -> dict:
    resp = api_client.list_daily_aggregations(
        headers=make_officer_headers(),
        params={"customer_id": customer_id, "business_date": business_date},
    )
    body = resp.json()
    assert len(body["data"]) == 1, (
        f"Expected one aggregation for ({customer_id}, {business_date}), got {len(body['data'])}"
    )
    return body["data"][0]


# ---------------------------------------------------------------------------
# Tier 3: CTR lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_ctr_in_draft(
    customer_id: str,
    branch_id: str,
    *,
    amount_cents: int = 1_100_000,
    occurred_at: str = "2026-08-01T08:00:00Z",
    direction: str = "CASH_IN",
) -> dict:
    """Post one over-threshold transaction; auto-created DRAFT CTR returned."""
    post_cash_txn(
        customer_id, branch_id,
        direction=direction, amount_cents=amount_cents, occurred_at=occurred_at,
    )
    return get_single_ctr_for_customer(customer_id)


def create_validated_ctr(
    customer_id: str,
    branch_id: str,
    *,
    analyst_id: str = "analyst-x",
    **txn_kwargs,
) -> dict:
    """DRAFT CTR -> VALIDATED. Returns validated CTR."""
    ctr = create_ctr_in_draft(customer_id, branch_id, **txn_kwargs)
    resp = api_client.validate_ctr(ctr["id"], headers=make_analyst_headers(analyst_id))
    return get_success_data(resp)


def create_filed_ctr(
    customer_id: str,
    branch_id: str,
    *,
    filing_channel: str = "EFILE",
    analyst_id: str = "analyst-x",
    filer_id: str = "officer-y",
    **txn_kwargs,
) -> dict:
    """DRAFT -> VALIDATED -> FILED. Returns filed CTR."""
    ctr = create_validated_ctr(customer_id, branch_id, analyst_id=analyst_id, **txn_kwargs)
    resp = api_client.file_ctr(
        ctr["id"], {"filing_channel": filing_channel}, headers=make_officer_headers(filer_id),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: Exemption lifecycle shortcuts
# ---------------------------------------------------------------------------

def request_exemption(
    customer_id: str,
    *,
    phase: str,
    requester_id: str = "officer-a",
    **extra,
) -> dict:
    payload = create_exemption_designation_payload(phase=phase, **extra)
    resp = api_client.create_exemption_designation(
        customer_id, payload, headers=make_officer_headers(requester_id),
    )
    return get_success_data(resp)


def approve_exemption(designation_id: str, *, approver_id: str = "officer-b") -> dict:
    resp = api_client.approve_exemption(designation_id, headers=make_officer_headers(approver_id))
    return get_success_data(resp)


def create_active_phase_i_exemption(
    customer_id: str,
    *,
    requester_id: str = "officer-a",
    approver_id: str = "officer-b",
    **extra,
) -> dict:
    ex = request_exemption(customer_id, phase="PHASE_I", requester_id=requester_id, **extra)
    return approve_exemption(ex["id"], approver_id=approver_id)


# ---------------------------------------------------------------------------
# Tier 3: Structuring alert lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_manual_alert(customer_id: str, *, creator_id: str = "officer-z", **extra) -> dict:
    payload = create_structuring_alert_payload(customer_id, **extra)
    resp = api_client.create_structuring_alert(payload, headers=make_officer_headers(creator_id))
    return get_success_data(resp)


def alert_in_status(
    customer_id: str,
    target: str,
    *,
    creator_id: str = "officer-z",
    analyst_id: str = "analyst-x",
    disposition_note: str = "disposition",
    **alert_kwargs,
) -> dict:
    """Walk a manual alert to UNDER_REVIEW / DISMISSED / REFERRED."""
    alert = create_manual_alert(customer_id, creator_id=creator_id, **alert_kwargs)
    if target == "OPEN":
        return alert
    get_success_data(api_client.begin_review_alert(alert["id"], headers=make_analyst_headers(analyst_id)))
    if target == "UNDER_REVIEW":
        return get_success_data(api_client.get_structuring_alert(alert["id"], headers=make_officer_headers()))
    if target == "DISMISSED":
        return get_success_data(api_client.dismiss_alert(
            alert["id"], {"disposition_note": disposition_note},
            headers=make_officer_headers(creator_id),
        ))
    if target == "REFERRED":
        return get_success_data(api_client.refer_alert(
            alert["id"], {"referral_note": disposition_note},
            headers=make_officer_headers(creator_id),
        ))
    raise ValueError(f"unsupported target {target}")


# ---------------------------------------------------------------------------
# Tier 3: Examination case lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_exam_case(**overrides) -> dict:
    resp = api_client.create_examination_case(
        create_examination_case_payload(**overrides), headers=make_examiner_headers(),
    )
    return get_success_data(resp)


def exam_case_in_status(target: str, *, findings: int = 0, finding_target=None) -> dict:
    """Create a case and walk it to FIELDWORK or FINDINGS_ISSUED.

    If findings > 0, finding_target must be (target_type, target_id).
    Returns dict with keys: case, findings (list).
    """
    case = create_exam_case()
    if target == "OPEN" and findings == 0:
        return {"case": case, "findings": []}
    get_success_data(api_client.begin_fieldwork(case["id"], headers=make_examiner_headers()))
    created = []
    if findings:
        assert finding_target is not None, "finding_target required"
        ttype, tid = finding_target
        for _ in range(findings):
            payload = create_finding_payload(ttype, tid)
            created.append(get_success_data(
                api_client.create_finding(case["id"], payload, headers=make_examiner_headers()),
            ))
    if target == "FIELDWORK":
        case_now = get_success_data(api_client.get_examination_case(case["id"], headers=make_examiner_headers()))
        return {"case": case_now, "findings": created}
    if target == "FINDINGS_ISSUED":
        case_now = get_success_data(api_client.issue_findings(case["id"], headers=make_examiner_headers()))
        return {"case": case_now, "findings": created}
    raise ValueError(f"unsupported target {target}")
