"""Corner queue - section state_machines, part A: initial states and early transitions."""
from test_helpers import (
    CONTROL_DOMAIN_ORDER,
    ApiErrorId,
    add_control_rows,
    assert_instant_equals,
    corridor,
    licensed_respondent,
    new_jurisdiction,
    new_respondent,
    open_questionnaire,
    read_respondent,
    respondent_version,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANALYST, make_respondent_headers


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def _prospect():
    _de()
    return new_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )


def _verified():
    _de()
    return licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )


def test_initial_state_information_request_created_in_draft(api):
    """The service-level clock starts at dispatch, not at creation, so a fresh request has
    no dispatch stamp, no due instant and no service level at all.

    Design: Corner/state_machines/initial_state_information_request_created_in_draft
    """
    rid = _verified()["id"]

    created = validate_success(
        api.create_information_request(
            rid, {"request_topic": "OWNERSHIP_EVIDENCE", "severity": "HIGH"}, ANALYST
        ),
        expected_status=201,
    )

    assert created["state"] == "DRAFT"
    assert created["dispatched_at"] is None
    assert created["due_at"] is None
    assert created["sla_hours"] is None
    assert created["escalation_level"] == 0
    assert created["insufficiency_rounds"] == 0
    assert created["reminder_count"] == 0


def test_initial_state_monitoring_profile_created_in_provisional(api):
    """A create computes nothing and calibrates nothing: the profile lands in PROVISIONAL
    with its supplied tolerance and no recalibration reason.

    Design: Corner/state_machines/initial_state_monitoring_profile_created_in_provisional
    """
    respondent = _verified()
    rid = respondent["id"]

    created = validate_success(
        api.create_monitoring_profile(
            rid,
            {
                "effective_from": "2026-07-01T00:00:00Z",
                "effective_to": "2026-12-31T23:59:59Z",
                "expected_corridors": [corridor("DE", 400000.00, 80)],
                "expected_respondent_version": respondent_version(rid),
                "tolerance_pct": 0.15,
            },
            ANALYST,
        ),
        expected_status=201,
    )

    assert created["calibration_state"] == "PROVISIONAL"
    assert created["recalibration_reason"] is None
    assert created["tolerance_pct"] == 0.15
    assert created["calibrated_at"] is None


def test_valid_transition_licensing_verification_moves_prospect_to_dd_in_progress(api):
    """An eligible licence pair opens due diligence: the lifecycle advances and the licence
    stamp is written, but the payment posture is a separate dimension and stays BLOCKED.

    Design: Corner/state_machines/valid_transition_licensing_verification_moves_prospect_to_dd_in_progress
    """
    rid = _prospect()["id"]

    updated = validate_success(
        api.verify_licensing(
            rid,
            {"license_status": "ACTIVE", "regulator_standing": "GOOD_STANDING",
             "regulator_name": "BaFin"},
            ANALYST,
        )
    )

    assert updated["dd_state"] == "DD_IN_PROGRESS"
    assert updated["license_status"] == "ACTIVE"
    assert_instant_equals(updated["license_verified_at"], "2026-08-01T00:00:00Z")
    assert updated["payment_posture"] == "BLOCKED"
    assert updated["version"] == 2


def test_precondition_licensing_verification_with_suspended_license_rejected(api):
    """SUSPENDED is a legal enum member but not an onboarding-eligible one, so the refusal
    is the domain error at priority 22 and the lifecycle does not move.

    Design: Corner/state_machines/precondition_licensing_verification_with_suspended_license_rejected
    """
    rid = _prospect()["id"]

    response = api.verify_licensing(
        rid,
        {"license_status": "SUSPENDED", "regulator_standing": "UNDER_ENFORCEMENT",
         "regulator_name": "BaFin"},
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_LICENSE_NOT_IN_GOOD_STANDING)

    assert read_respondent(rid)["dd_state"] == "PROSPECT"


def test_valid_transition_questionnaire_draft_to_submitted_with_all_eight_domains(api):
    """Submission is the respondent's own act and needs every one of the eight domains on
    file; it stamps the submission instant and leaves the clarification budget untouched.

    Design: Corner/state_machines/valid_transition_questionnaire_draft_to_submitted_with_all_eight_domains
    """
    respondent = _verified()
    rid = respondent["id"]
    questionnaire = open_questionnaire(rid)
    add_control_rows(questionnaire["id"], rid, {d: 4 for d in CONTROL_DOMAIN_ORDER})

    submitted = validate_success(
        api.submit_questionnaire(questionnaire["id"], {}, make_respondent_headers(rid))
    )

    assert submitted["state"] == "SUBMITTED"
    assert_instant_equals(submitted["submitted_at"], "2026-08-01T00:00:00Z")
    assert submitted["clarification_rounds"] == 0
