"""Corner queue - section state_machines, part F: restriction cascades and profile terminals."""
from test_helpers import (
    ApiErrorId,
    add_nested,
    adjudicate_nested,
    calibrate,
    committee_decision,
    corridor,
    dispatch_request,
    licensed_respondent,
    new_jurisdiction,
    open_profile,
    raise_request,
    read_nested,
    read_profile,
    read_request,
    read_respondent,
    restrict,
    setup_approved_respondent,
    setup_pending_committee,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, OFFICER


def _three_jurisdictions():
    new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )
    new_jurisdiction(
        jurisdiction_code="FR", name="France", basel_aml_index=5.0, corridor_risk_weight=1.2
    )
    new_jurisdiction(
        jurisdiction_code="IT", name="Italy", basel_aml_index=4.5, corridor_risk_weight=1.1
    )


def _approved_nesting_respondent():
    bundle = setup_approved_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
        nested_activity_permitted=True,
    )
    return bundle["respondent"]["id"]


def test_conditional_cascade_restriction_suspends_only_confirmed_nested_rows(api):
    """The suspension cascade is state-conditional, not blanket: the confirmed edge is
    frozen while the merely disclosed one is untouched, and the two weights still sum.

    Design: Corner/state_machines/conditional_cascade_restriction_suspends_only_confirmed_nested_rows
    """
    _three_jurisdictions()
    rid = _approved_nesting_respondent()
    fr = add_nested(
        rid, "FR", downstream_institution_name="Petit Banque SA",
        discovery_source="QUESTIONNAIRE",
    )
    it = add_nested(
        rid, "IT", downstream_institution_name="Banca Piccola SpA",
        discovery_source="QUESTIONNAIRE",
    )
    adjudicate_nested(fr["id"], "CONFIRM")

    validate_success(
        api.restrict_respondent(
            rid,
            {"action": "RESTRICT", "restriction_reason": "OFFICER_ACTION",
             "payment_posture": "BLOCKED"},
            OFFICER,
        )
    )

    respondent = read_respondent(rid)
    assert respondent["dd_state"] == "RESTRICTED"
    assert respondent["restriction_reason"] == "OFFICER_ACTION"
    assert respondent["payment_posture"] == "BLOCKED"
    assert read_nested(fr["id"])["state"] == "SUSPENDED"
    assert read_nested(it["id"])["state"] == "DISCLOSED"
    assert respondent["nested_exposure_units"] == 4


def test_cyclic_restriction_lift_restores_suspended_nested_and_screen_only_posture(api):
    """The lift closes the approved-restricted-approved cycle: the reason is cleared, the
    frozen edge returns to confirmed, and the posture lands on the narrower opening.

    Design: Corner/state_machines/cyclic_restriction_lift_restores_suspended_nested_and_screen_only_posture
    """
    _three_jurisdictions()
    rid = _approved_nesting_respondent()
    fr = add_nested(
        rid, "FR", downstream_institution_name="Petit Banque SA",
        discovery_source="QUESTIONNAIRE",
    )
    adjudicate_nested(fr["id"], "CONFIRM")
    restrict(rid, "OFFICER_ACTION", payment_posture="BLOCKED")
    assert read_nested(fr["id"])["state"] == "SUSPENDED"

    validate_success(api.restrict_respondent(rid, {"action": "LIFT"}, OFFICER))

    respondent = read_respondent(rid)
    assert respondent["dd_state"] == "APPROVED"
    assert respondent["restriction_reason"] is None
    assert respondent["payment_posture"] == "SCREEN_ONLY"
    assert read_nested(fr["id"])["state"] == "CONFIRMED"
    assert respondent["nested_exposure_units"] == 3


def test_cascade_down_decline_terminates_nested_and_abandons_information_requests(api):
    """One decline fans out to two child collections at once, zeroing the exposure rollup
    and the escalation rollup while the posture never leaves its blocked start.

    Design: Corner/state_machines/cascade_down_decline_terminates_nested_and_abandons_information_requests
    """
    _three_jurisdictions()
    bundle = setup_pending_committee(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
        nested_activity_permitted=True,
    )
    rid = bundle["respondent"]["id"]
    nested = add_nested(
        rid, "FR", downstream_institution_name="Petit Banque SA",
        discovery_source="QUESTIONNAIRE",
    )
    request = raise_request(rid, request_topic="CONTROL_REMEDIATION", severity="MEDIUM")
    dispatch_request(request["id"])
    assert read_request(request["id"])["state"] == "SENT"

    committee_decision(rid, "DECLINE", decision_note="Risk appetite")

    respondent = read_respondent(rid)
    assert respondent["dd_state"] == "DECLINED"
    assert respondent["payment_posture"] == "BLOCKED"
    assert read_nested(nested["id"])["state"] == "TERMINATED"
    assert read_request(request["id"])["state"] == "ABANDONED"
    assert respondent["nested_exposure_units"] == 0
    assert respondent["disclosed_nested_count"] == 0
    assert respondent["escalation_units"] == 0


def _superseded_profile():
    new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    profile = open_profile(respondent["id"], [corridor("DE", 400000.00, 80)])
    calibrate(profile["id"], action="SUPERSEDE")
    return profile


def test_invalid_transition_calibrate_a_superseded_profile_rejected(api):
    """Supersession is terminal, so the thresholds of a retired profile can never be brought
    back into force by a later calibration.

    Design: Corner/state_machines/invalid_transition_calibrate_a_superseded_profile_rejected
    """
    profile = _superseded_profile()

    response = api.calibrate_profile(profile["id"], {"action": "CALIBRATE"}, ANALYST)
    validate_error(response, ApiErrorId.ERR_INVALID_MONITORING_PROFILE_STATE)

    assert read_profile(profile["id"])["calibration_state"] == "SUPERSEDED"


def test_observation_against_superseded_profile_rejected(api):
    """Activity cannot be posted into a retired profile, and the refusal carries the
    dedicated supersession error rather than the generic state error.

    Design: Corner/state_machines/observation_against_superseded_profile_rejected
    """
    profile = _superseded_profile()

    response = api.create_observation(
        profile["id"],
        {"period_month": "2026-07", "corridor_jurisdiction_code": "DE",
         "aggregate_usd": 100000.00, "txn_count": 20},
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_MONITORING_PROFILE_SUPERSEDED)

    _rows, meta = validate_paginated(
        api.list_activity_observations(ANALYST, params={"monitoring_profile_id": profile["id"]})
    )
    assert meta["total_count"] == 0
