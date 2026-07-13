"""Case lifecycle transitions: the retriage cycle, empty-set triage boundary,
invalid re-transitions, and the optimistic-concurrency guard on assessment create.

Translations of Difficulty rules `non_linear_state_machine` /
`boundary_precision_check` and Corner `state_machines` / `cross_cutting_complexity_layers`.
"""
from test_helpers import (
    ApiErrorId,
    add_exposure,
    create_risk_assessment_payload,
    make_specialist_headers,
    open_case,
    seed_specialist,
    seed_substance,
    setup_moderate_finalized_assessment,
    setup_monitoring_case,
    setup_triaged_completed_assessment,
    triage,
    validate_error,
    validate_success,
)


def test_add_exposure_to_monitoring_case_triggers_retriage(api):
    """PRD §3.3: "Adding an exposure to a case that is already in `MONITORING` is a
    clinically significant event: it drives the case from `MONITORING` to
    `RETRIAGE`."

    Design: Difficulty/non_linear_state_machine/case_branch_and_retriage_cycle
    """
    ctx = setup_monitoring_case(api)
    add_exposure(api, ctx["case"]["id"], ctx["spi"]["id"], ctx["substance"]["id"],
                 dose_range_low_mg=400, dose_range_high_mg=600)
    case = validate_success(api.get_case(ctx["case"]["id"],
                                         make_specialist_headers(ctx["spi"]["id"])))
    assert case["status"] == "RETRIAGE"


def test_retriage_supersedes_active_assessment_and_disposition(api):
    """PRD §3.3: "As part of that transition, the case's active risk assessment
    moves from `COMPLETED` or `FINALIZED` to `SUPERSEDED`, and its active
    disposition moves from `ACTIVE` to `SUPERSEDED`, so the case must be re-assessed
    and re-dispositioned before it can settle again."

    Design: Difficulty/non_linear_state_machine/case_branch_and_retriage_cycle
    """
    ctx = setup_monitoring_case(api)
    headers = make_specialist_headers(ctx["spi"]["id"])
    add_exposure(api, ctx["case"]["id"], ctx["spi"]["id"], ctx["substance"]["id"],
                 dose_range_low_mg=400, dose_range_high_mg=600)
    ra = validate_success(api.get_risk_assessment(ctx["ra"]["id"], headers))
    disp = validate_success(api.get_disposition(ctx["disposition"]["id"], headers))
    assert ra["status"] == "SUPERSEDED"
    assert disp["status"] == "SUPERSEDED"


def test_triage_empty_exposure_set_rejected(api):
    """PRD §3.4: "Triage is refused with `ERR_NO_EXPOSURES` (HTTP 422) if the case
    has no exposures, and it requires that every exposure be `identified`."

    Design: Difficulty/boundary_precision_check/triage_empty_exposure_set_rejected
    """
    spi = seed_specialist(api)
    case = open_case(api, spi["id"], chief_complaint="unknown ingestion")
    resp = api.triage_case(case["id"], make_specialist_headers(spi["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_EXPOSURES)


def test_triage_empty_exposure_set_leaves_case_in_intake(api):
    """PRD §3.4: "Once at least one exposure is on the case, a `Specialist` triages
    it, advancing the case from `INTAKE` to `TRIAGED`."

    Design: Difficulty/boundary_precision_check/triage_empty_exposure_set_rejected
    """
    spi = seed_specialist(api)
    headers = make_specialist_headers(spi["id"])
    case = open_case(api, spi["id"], chief_complaint="unknown ingestion")
    api.triage_case(case["id"], headers)
    refreshed = validate_success(api.get_case(case["id"], headers))
    assert refreshed["status"] == "INTAKE"


def test_triage_already_triaged_case_rejected(api):
    """PRD §3.4: "Once at least one exposure is on the case, a `Specialist` triages
    it, advancing the case from `INTAKE` to `TRIAGED`."
    PRD §2.10: "then whether the target entity is in a state that permits the
    requested transition (`ERR_INVALID_STATE`, HTTP 409)."

    Design: Corner/state_machines/triage_from_already_triaged_returns_invalid_state
    """
    substance = seed_substance(api)
    spi = seed_specialist(api)
    case = open_case(api, spi["id"])
    add_exposure(api, case["id"], spi["id"], substance["id"])
    triage(api, case["id"], spi["id"])
    resp = api.triage_case(case["id"], make_specialist_headers(spi["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_finalize_already_finalized_assessment_rejected(api):
    """PRD §3.4: "Finalization is permitted only when the assessment is in
    `COMPLETED`; otherwise `ERR_INVALID_STATE` applies."

    Design: Corner/state_machines/finalize_twice_second_returns_invalid_state
    """
    ctx = setup_moderate_finalized_assessment(api)
    resp = api.finalize_risk_assessment(ctx["ra"]["id"],
                                        make_specialist_headers(ctx["spi"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_stale_case_version_on_second_assessment_rejected(api):
    """PRD §2.7: "If another writer has advanced the case's `version` since then —
    by creating a superseding assessment or adding an exposure — the client's view
    is stale, and the create is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412),
    preventing the client from overwriting an assessment it has not observed."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_case_version_on_second_assessment
    """
    ctx = setup_triaged_completed_assessment(api)
    stale_version = ctx["case_version_at_triage"]
    resp = api.create_risk_assessment(
        ctx["case"]["id"],
        create_risk_assessment_payload(stale_version),
        make_specialist_headers(ctx["spi"]["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION)
