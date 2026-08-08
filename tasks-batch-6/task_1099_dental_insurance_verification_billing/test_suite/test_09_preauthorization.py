"""Pre-authorization revision loop and terminal-state guard.

Corner: preauth_submitted_pended_resubmit_cycle, decision_on_approved_preauth_invalid_state.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_biller_headers,
)
from test_helpers import fixtures as fx


def _draft_crown_preauth(api):
    """A DRAFT pre-auth (crown line billed 130000) for a verified coverage.
    Returns preauth_id."""
    patient = fx.new_patient(api)
    plan = fx.new_plan(api, annual_maximum_cents=150000, major_coinsurance_pct=50,
                       deductible_cents=5000)
    fx.new_procedure(api, cdt_code="D2740", description="Crown", category="MAJOR",
                     ucr_fee_cents=120000)
    cov = fx.new_coverage(api, patient["id"], plan["id"])
    fx.new_verification(api, cov)
    pa = get_success_data(api.create_preauthorization(
        {"patient_id": patient["id"], "coverage_id": cov["id"],
         "procedures": [{"cdt_code": "D2740", "billed_fee_cents": 130000}]},
        make_biller_headers()))
    return pa["id"]


def test_preauth_submitted_pended_resubmit_cycle(api):
    """PRD §3.3: "A pended pre-authorization forms a revision loop: after the
    biller adds the missing documentation, resubmitting moves it back from
    `PENDED` to `SUBMITTED` ... An `APPROVED` outcome moves the pre-authorization
    to the terminal `APPROVED` state and sets `approved_amount_cents` equal to the
    current `estimated_benefit_cents`."

    Design: Corner/state_machines/preauth_submitted_pended_resubmit_cycle
    """
    pa_id = _draft_crown_preauth(api)
    fx.get_success_data(api.submit_preauthorization(pa_id, make_biller_headers()))
    fx.get_success_data(api.decide_preauthorization(pa_id, "PENDED", make_biller_headers()))
    resub = validate_success(api.submit_preauthorization(pa_id, make_biller_headers()), 200)
    assert resub["status"] == "SUBMITTED", f"expected SUBMITTED, got {resub['status']}"
    approved = validate_success(
        api.decide_preauthorization(pa_id, "APPROVED", make_biller_headers()), 200)
    assert approved["status"] == "APPROVED", f"expected APPROVED, got {approved['status']}"
    assert approved["approved_amount_cents"] == 57500, \
        f"expected 57500, got {approved['approved_amount_cents']}"


def test_decision_on_approved_preauth_invalid_state(api):
    """PRD §3.3: "Deciding a pre-authorization that is not currently `SUBMITTED`,
    or submitting from a state other than `DRAFT` or `PENDED`, is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/decision_on_approved_preauth_invalid_state
    """
    pa_id = _draft_crown_preauth(api)
    fx.get_success_data(api.submit_preauthorization(pa_id, make_biller_headers()))
    fx.get_success_data(api.decide_preauthorization(pa_id, "APPROVED", make_biller_headers()))
    resp = api.decide_preauthorization(pa_id, "DENIED", make_biller_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
