"""Disposition workflow: the finalized-assessment precondition, the home-management
safety gate, the facility-pairing rule, and validation-order precedence.

Translations of Difficulty rules `priority_pair_validation_conflict` /
`cross_entity_state_dependency` and Corner `validations`.
"""
from test_helpers import (
    ApiErrorId,
    add_exposure,
    create_assessment,
    create_disposition_payload,
    finalize,
    make_specialist_headers,
    open_case,
    seed_protocol,
    seed_specialist,
    seed_substance,
    setup_moderate_completed_with_protocol,
    setup_moderate_finalized_assessment,
    setup_severe_completed_assessment,
    triage,
    validate_error,
    validate_success,
)


def test_home_disposition_on_completed_severe_returns_invalid_state(api):
    """PRD §3.5: "A **disposition** records the care-setting decision and must
    reference a `risk_assessment_id` that is `FINALIZED`."
    PRD §2.10: "then whether the target entity is in a state that permits the
    requested transition (`ERR_INVALID_STATE`, HTTP 409). Only after all of those
    pass are the operation-specific business rules evaluated."

    Design: Difficulty/priority_pair_validation_conflict/disposition_state_beats_safety_returns_invalid_state
    """
    ctx = setup_severe_completed_assessment(api)
    resp = api.create_disposition(
        ctx["case"]["id"],
        create_disposition_payload(ctx["ra"]["id"], "HOME_MANAGEMENT"),
        make_specialist_headers(ctx["spi"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_rejected_disposition_leaves_case_triaged(api):
    """PRD §3.5: "A home-management disposition drives the case from `TRIAGED` to
    `MONITORING` (or from `RETRIAGE` back to `MONITORING` when a fresh `FINALIZED`
    assessment of tier `MINIMAL` or `MODERATE` exists)."

    Design: Difficulty/priority_pair_validation_conflict/disposition_state_beats_safety_returns_invalid_state
    """
    ctx = setup_severe_completed_assessment(api)
    headers = make_specialist_headers(ctx["spi"]["id"])
    api.create_disposition(ctx["case"]["id"],
                           create_disposition_payload(ctx["ra"]["id"], "HOME_MANAGEMENT"),
                           headers)
    case = validate_success(api.get_case(ctx["case"]["id"], headers))
    assert case["status"] == "TRIAGED"


def test_disposition_on_completed_assessment_rejected(api):
    """PRD §3.5: "A **disposition** records the care-setting decision and must
    reference a `risk_assessment_id` that is `FINALIZED`."

    Design: Difficulty/cross_entity_state_dependency/disposition_requires_finalized_assessment
    """
    ctx = setup_moderate_completed_with_protocol(api)
    resp = api.create_disposition(
        ctx["case"]["id"],
        create_disposition_payload(ctx["ra"]["id"], "HOME_MANAGEMENT"),
        make_specialist_headers(ctx["spi"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_disposition_succeeds_after_finalize_drives_monitoring(api):
    """PRD §3.5: "A home-management disposition drives the case from `TRIAGED` to
    `MONITORING` (or from `RETRIAGE` back to `MONITORING` when a fresh `FINALIZED`
    assessment of tier `MINIMAL` or `MODERATE` exists)."

    Design: Difficulty/cross_entity_state_dependency/disposition_requires_finalized_assessment
    """
    ctx = setup_moderate_completed_with_protocol(api)
    headers = make_specialist_headers(ctx["spi"]["id"])
    finalize(api, ctx["ra"]["id"], ctx["spi"]["id"], role="Specialist")
    disp = validate_success(
        api.create_disposition(ctx["case"]["id"],
                               create_disposition_payload(ctx["ra"]["id"], "HOME_MANAGEMENT"),
                               headers), 201)
    assert disp["status"] == "ACTIVE"
    case = validate_success(api.get_case(ctx["case"]["id"], headers))
    assert case["status"] == "MONITORING"


def test_ed_referral_without_facility_rejected(api):
    """PRD §3.5: "The facility-pairing rule then requires that `ED_REFERRAL` supply
    a `facility_id` naming the referral target while `HOME_MANAGEMENT` leave
    `facility_id` null; violating this pairing is rejected with
    `ERR_DISPOSITION_FACILITY_MISMATCH` (HTTP 422)."

    Design: Corner/validations/ed_referral_without_facility_rejected
    """
    ctx = setup_moderate_finalized_assessment(api)
    resp = api.create_disposition(
        ctx["case"]["id"],
        create_disposition_payload(ctx["ra"]["id"], "ED_REFERRAL"),
        make_specialist_headers(ctx["spi"]["id"]))
    validate_error(resp, ApiErrorId.ERR_DISPOSITION_FACILITY_MISMATCH)


def test_unsafe_home_disposition_on_severe_case_rejected(api):
    """PRD §3.5: "The safety gate allows a home-management decision only when the
    referenced assessment's `risk_tier` is `MINIMAL` or `MODERATE`; a
    home-management disposition on a `SEVERE` or `CRITICAL` case is rejected with
    `ERR_UNSAFE_DISPOSITION` (HTTP 422)."

    Design: Corner/validations/unsafe_home_disposition_on_severe_rejected
    """
    substance = seed_substance(api)
    seed_protocol(api, risk_tier="SEVERE", management_setting="ED",
                  followup_count=0, followup_interval_hours=24, requires_toxicologist=True)
    spi = seed_specialist(api)
    tox = seed_specialist(api, full_name="Tara Tox", credential="TOXICOLOGIST")
    case = open_case(api, spi["id"], patient_weight_kg=20, chief_complaint="large ingestion")
    add_exposure(api, case["id"], spi["id"], substance["id"],
                 dose_range_low_mg=3000, dose_range_high_mg=3000)
    triaged = triage(api, case["id"], spi["id"])
    ra = create_assessment(api, case["id"], spi["id"], triaged["version"])
    finalize(api, ra["id"], tox["id"], role="Toxicologist")
    resp = api.create_disposition(
        case["id"], create_disposition_payload(ra["id"], "HOME_MANAGEMENT"),
        make_specialist_headers(spi["id"]))
    validate_error(resp, ApiErrorId.ERR_UNSAFE_DISPOSITION)
