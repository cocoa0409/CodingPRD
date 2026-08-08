"""Contract signature lifecycle, the projected-margin execution gate, and OCC revision."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_clinician_headers,
    revise_contract_payload,
)
from test_helpers.fixtures import provision, get_assignment_data

RECRUITER = TEST_USERS["recruiter_headers"]


def _contract(api, asg_id):
    data, _ = validate_paginated(api.list_assignment_contracts(asg_id, RECRUITER))
    return data[0]


def test_contract_cannot_jump_from_draft_to_fully_executed(api):
    """PRD §3.3: "Any signature move that is not an outgoing edge of the current state
    is rejected with ERR_INVALID_TRANSITION."
    PRD §3.3: "Fully executing a contract is a Clinician action out of
    SENT_FOR_SIGNATURE and is gated by the margin floor."

    Design: Corner/state_machines/corner_contract_cannot_jump_from_draft_to_fully_executed
    """
    ctx = provision(api)  # contract still DRAFT
    resp = api.transition_contract(ctx.con_id, {"to": "FULLY_EXECUTED"}, make_clinician_headers(ctx.clin_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION.value)
    con = _contract(api, ctx.asg_id)
    assert con["status"] == "DRAFT" and con["clinician_signed_at"] is None
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["staffing_status"] == "DRAFT"


def test_contract_execution_rejected_when_projected_margin_below_floor(api):
    """PRD §2.9: "At contract execution the projected whole-term margin passes only when
    the projected margin in cents multiplied by 100 is at least the projected gross bill
    in cents multiplied by 22; otherwise execution is rejected with ERR_MARGIN_BELOW_FLOOR."
    PRD §3.3: "If it is below, execution is rejected with ERR_MARGIN_BELOW_FLOOR (HTTP 422)."

    Design: Corner/validations/corner_contract_execution_rejected_when_projected_margin_below_floor
    """
    ctx = provision(api, assignment_overrides={"bill_rate_cents_per_hour": 12500},
                     contract_stage="sent")
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["projected_gross_bill_cents"] == 5850000
    assert asg["projected_pay_cost_cents"] == 4967716
    assert asg["projected_margin_cents"] == 882284
    assert asg["projected_margin_pct"] == 0.1508
    resp = api.transition_contract(ctx.con_id, {"to": "FULLY_EXECUTED"}, make_clinician_headers(ctx.clin_id))
    validate_error(resp, ApiErrorId.ERR_MARGIN_BELOW_FLOOR.value)
    assert _contract(api, ctx.asg_id)["status"] == "SENT_FOR_SIGNATURE"
    assert get_assignment_data(api, ctx.asg_id)["staffing_status"] == "DRAFT"


def test_contract_revise_recomputes_assignment_projection(api):
    """PRD §3.3: "A successful revision replaces those four terms, increments
    revision_count by 1, and increments the contract's version. It then recomputes the
    assignment's term_weeks, end_date, guaranteed_hours_total, and
    guaranteed_hours_remaining, and re-derives the forward-looking projection onto the
    assignment's projected_* fields."

    Design: Corner/cross_cutting_complexity_layers/corner_contract_revise_recomputes_projection_and_rejects_stale_version
    """
    ctx = provision(api)
    con = _contract(api, ctx.asg_id)
    v0 = con["version"]
    resp = api.revise_contract(ctx.con_id, revise_contract_payload(
        v0, term_weeks=13, weekly_guaranteed_hours=40,
        base_pay_rate_cents_per_hour=5400, bill_rate_cents_per_hour=15000), RECRUITER)
    data = validate_success(resp, 200)
    assert data["status"] == "DRAFT" and data["revision_count"] == 1
    assert data["weekly_guaranteed_hours"] == 40 and data["base_pay_rate_cents_per_hour"] == 5400
    assert data["bill_rate_cents_per_hour"] == 15000 and data["version"] == v0 + 1
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["guaranteed_hours_total"] == 520 and asg["guaranteed_hours_remaining"] == 520
    assert asg["guaranteed_hours_consumed"] == 0 and asg["guaranteed_hours_waived"] == 0
    assert asg["end_date"] == "2026-09-05"
    assert asg["projected_gross_bill_cents"] == 7800000
    assert asg["projected_pay_cost_cents"] == 5411380
    assert asg["projected_margin_cents"] == 2388620
    assert asg["projected_margin_pct"] == 0.3062


def test_contract_revise_rejects_stale_version(api):
    """PRD §2.6: "if expected_contract_version does not equal the contract's current
    version, the request is rejected with ERR_STALE_CONTRACT_VERSION (HTTP 412),
    preventing a caller from overwriting rate terms it never observed."

    Design: Corner/cross_cutting_complexity_layers/corner_contract_revise_recomputes_projection_and_rejects_stale_version
    """
    ctx = provision(api)
    con = _contract(api, ctx.asg_id)
    v0 = con["version"]
    validate_success(api.revise_contract(ctx.con_id, revise_contract_payload(
        v0, term_weeks=13, weekly_guaranteed_hours=40,
        base_pay_rate_cents_per_hour=5400, bill_rate_cents_per_hour=15000), RECRUITER), 200)
    resp = api.revise_contract(ctx.con_id, revise_contract_payload(
        v0, term_weeks=13, weekly_guaranteed_hours=36,
        base_pay_rate_cents_per_hour=5200, bill_rate_cents_per_hour=14000), RECRUITER)
    validate_error(resp, ApiErrorId.ERR_STALE_CONTRACT_VERSION.value)
    con_after = _contract(api, ctx.asg_id)
    assert con_after["revision_count"] == 1 and con_after["bill_rate_cents_per_hour"] == 15000
