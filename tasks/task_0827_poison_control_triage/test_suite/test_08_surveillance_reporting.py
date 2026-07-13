"""NPDS surveillance reporting: the medical-outcome derivation, the active-
assessment precondition, and the aggregate_case_count compensating invariant.

Translations of Difficulty rule `compensating_invariant` and Corner
`calculations` / `validations`.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_exposure,
    create_npds_report_payload,
    make_specialist_headers,
    open_case,
    seed_specialist,
    seed_substance,
    setup_npds_submitted,
    setup_triaged_completed_assessment,
    triage,
    validate_error,
    validate_success,
)

_SURVEILLANCE = TEST_USERS["surveillance_officer_headers"]


def test_aggregate_case_count_returns_to_zero_after_retract(api):
    """PRD §3.8: "A `SurveillanceOfficer` (or a `Toxicologist`) may retract a
    submitted report, moving its `report_status` from `SUBMITTED` to `RETRACTED`
    and decrementing the credited substance's `aggregate_case_count` by one as a
    compensating adjustment."

    Design: Difficulty/compensating_invariant/substance_surveillance_count_invariant
    """
    ctx = setup_npds_submitted(api)
    api.retract_npds_report(ctx["report"]["id"], _SURVEILLANCE)
    substance = validate_success(api.get_substance(ctx["substance"]["id"], _SURVEILLANCE))
    assert substance["aggregate_case_count"] == 0


def test_retract_moves_report_to_retracted(api):
    """PRD §3.8: "A `SurveillanceOfficer` (or a `Toxicologist`) may retract a
    submitted report, moving its `report_status` from `SUBMITTED` to `RETRACTED`
    and decrementing the credited substance's `aggregate_case_count` by one as a
    compensating adjustment."

    Design: Difficulty/compensating_invariant/substance_surveillance_count_invariant
    """
    ctx = setup_npds_submitted(api)
    report = validate_success(api.retract_npds_report(ctx["report"]["id"], _SURVEILLANCE))
    assert report["report_status"] == "RETRACTED"


def test_npds_medical_outcome_from_additive_score(api):
    """PRD §3.8: "On submission, the report derives its `medical_outcome` from the
    active assessment's `aggregate_score_additive`: the outcome is `MINOR` when the
    additive score is below 0.5, `MODERATE` when it is at least 0.5 but below 1.5,
    and `MAJOR` when it is 1.5 or greater."

    Design: Corner/calculations/npds_medical_outcome_from_additive
    """
    ctx = setup_triaged_completed_assessment(api, dose_low=1500, dose_high=1500, weight=20)
    report = validate_success(api.create_npds_report(
        create_npds_report_payload(ctx["case"]["id"], ctx["substance"]["id"]),
        _SURVEILLANCE), 201)
    assert report["medical_outcome"] == "MODERATE"


def test_npds_without_active_assessment_rejected(api):
    """PRD §3.8: "The case must have an active, non-superseded risk assessment; a
    submission for a case without one is rejected with `ERR_NO_ACTIVE_ASSESSMENT`
    (HTTP 409)."

    Design: Corner/validations/npds_without_active_assessment_rejected
    """
    substance = seed_substance(api)
    spi = seed_specialist(api)
    case = open_case(api, spi["id"])
    add_exposure(api, case["id"], spi["id"], substance["id"])
    triage(api, case["id"], spi["id"])
    resp = api.create_npds_report(
        create_npds_report_payload(case["id"], substance["id"]), _SURVEILLANCE)
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_ASSESSMENT)
