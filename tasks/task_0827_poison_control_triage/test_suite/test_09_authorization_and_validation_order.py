"""Authorization gates and validation ordering: role-precedence over state, the
toxicologist finalize gate, the no-protocol finalize failure, RBAC denials, and
sub-resource existence.

Translations of Difficulty rule `priority_pair_validation_conflict` and Corner
`validations` / `rbac` / `errors`.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    add_exposure,
    create_assessment,
    create_facility_consult_payload,
    make_specialist_headers,
    make_toxicologist_headers,
    open_case,
    seed_facility,
    seed_protocol,
    seed_specialist,
    seed_substance,
    setup_moderate_finalized_assessment,
    setup_severe_completed_assessment,
    triage,
    validate_error,
    validate_success,
)

_SURVEILLANCE = TEST_USERS["surveillance_officer_headers"]


def test_unauthorized_finalize_beats_state_check(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."
    PRD §2.10: "Authentication of the headers comes first (`ERR_UNAUTHENTICATED`),
    then role authorization (`ERR_UNAUTHORIZED`), then existence of path-referenced
    resources ... then whether the target entity is in a state that permits the
    requested transition (`ERR_INVALID_STATE`, HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/finalize_auth_beats_state_returns_unauthorized
    """
    ctx = setup_moderate_finalized_assessment(api)
    resp = api.finalize_risk_assessment(ctx["ra"]["id"], _SURVEILLANCE)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_unauthorized_finalize_leaves_assessment_finalized(api):
    """PRD §3.4: "Finalizing an assessment advances it from `COMPLETED` to
    `FINALIZED` and refreshes the case's `risk_tier` mirror."

    Design: Difficulty/priority_pair_validation_conflict/finalize_auth_beats_state_returns_unauthorized
    """
    ctx = setup_moderate_finalized_assessment(api)
    api.finalize_risk_assessment(ctx["ra"]["id"], _SURVEILLANCE)
    ra = validate_success(api.get_risk_assessment(ctx["ra"]["id"],
                                                  make_specialist_headers(ctx["spi"]["id"])))
    assert ra["status"] == "FINALIZED"


def test_finalize_with_no_matching_protocol_rejected(api):
    """PRD §3.4: "Finally, if `protocol_id` is still null at finalize because no
    protocol matched the tier, finalization is refused with `ERR_NO_PROTOCOL`
    (HTTP 409)."

    Design: Corner/validations/no_protocol_for_tier_at_finalize
    """
    ctx = setup_severe_completed_assessment(api)  # SEVERE tier, no SEVERE protocol seeded
    resp = api.finalize_risk_assessment(ctx["ra"]["id"],
                                        make_toxicologist_headers(ctx["tox"]["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_PROTOCOL)


def test_specialist_cannot_open_facility_consult(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/specialist_cannot_open_facility_consult
    """
    facility = seed_facility(api)
    spi = seed_specialist(api)
    case = open_case(api, spi["id"])
    resp = api.create_facility_consult(
        create_facility_consult_payload(case["id"], facility["id"], 60),
        make_specialist_headers(spi["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_specialist_finalize_severe_requires_toxicologist(api):
    """PRD §3.4: "if the selected protocol's `requires_toxicologist` is true (the
    `SEVERE` and `CRITICAL` tiers), the acting role must be `Toxicologist`; a
    non-toxicologist attempt is rejected with `ERR_TOXICOLOGIST_REQUIRED`
    (HTTP 403), while the `MINIMAL` and `MODERATE` tiers admit either a `Specialist`
    or a `Toxicologist`."

    Design: Corner/rbac/specialist_finalize_severe_requires_toxicologist
    """
    substance = seed_substance(api)
    seed_protocol(api, risk_tier="SEVERE", management_setting="ED",
                  followup_count=0, followup_interval_hours=24, requires_toxicologist=True)
    spi = seed_specialist(api)
    case = open_case(api, spi["id"], patient_weight_kg=20, chief_complaint="large ingestion")
    add_exposure(api, case["id"], spi["id"], substance["id"],
                 dose_range_low_mg=3000, dose_range_high_mg=3000)
    triaged = triage(api, case["id"], spi["id"])
    ra = create_assessment(api, case["id"], spi["id"], triaged["version"])
    resp = api.finalize_risk_assessment(ra["id"], make_specialist_headers(spi["id"]))
    validate_error(resp, ApiErrorId.ERR_TOXICOLOGIST_REQUIRED)


def test_surveillance_officer_cannot_triage(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/surveillance_officer_cannot_triage
    """
    substance = seed_substance(api)
    spi = seed_specialist(api)
    case = open_case(api, spi["id"])
    add_exposure(api, case["id"], spi["id"], substance["id"])
    resp = api.triage_case(case["id"], _SURVEILLANCE)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_finalize_nonexistent_assessment_returns_resource_not_found(api):
    """PRD §2.8: "When a sub-resource id in the path — an exposure, risk assessment,
    disposition, follow-up call, facility consult, or NPDS report — does not
    resolve, the request fails with `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/resource_not_found_bad_risk_assessment
    """
    tox = seed_specialist(api, full_name="Tara Tox", credential="TOXICOLOGIST")
    resp = api.finalize_risk_assessment(NON_EXISTENT_UUID, make_toxicologist_headers(tox["id"]))
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)
