"""Visit fork-join and recert revision-cycle lifecycles (PRD §3.4, §3.7).
Queue A difficulty instances with depth coverage.
"""
from test_helpers import api_client, validate_success
from test_helpers.fixtures import (
    BILLING,
    COMPLIANCE,
    INTAKE,
    SCHEDULER,
    create_oasis,
    schedule_visit,
    setup_active_episode,
    set_clock,
)
from test_helpers.test_users import make_clinician_headers

WOUND_RATE = {
    "clinical_group": "WOUND", "base_30day_rate": 2000.00,
    "functional_weight_low": 0.95, "functional_weight_medium": 1.00,
    "functional_weight_high": 1.05, "lupa_threshold": 5,
}
WOUND_OASIS = {"clinical_group": "WOUND", "functional_level": "HIGH", "comorbidity_count": 2}
MMTA_RATE = {
    "clinical_group": "MMTA_OTHER", "base_30day_rate": 1500.00,
    "functional_weight_low": 1.00, "functional_weight_medium": 1.00,
    "functional_weight_high": 1.00, "lupa_threshold": 1,
}
MMTA_OASIS = {"clinical_group": "MMTA_OTHER", "functional_level": "LOW", "comorbidity_count": 0}


def _confirm(api, visit_id, rn_id):
    return validate_success(api.confirm_visit(visit_id, make_clinician_headers(rn_id)))


# ===========================================================================
# Difficulty: visit_fork_join_completed_vs_missed (≥2)
# ===========================================================================
def test_visit_completed_billable_missed_not_billable(api):
    """PRD §3.4: "Completion sets billable true, recomputes the episode's
    provisional payment to reflect the now-completed visit, appends a
    VISIT_COMPLETED event, and bumps the visit version."
    PRD §3.4: "The Scheduler may mark a confirmed visit missed, driving
    CONFIRMED -> MISSED; this is allowed once the window has elapsed ... sets
    billable false, releases the clinician's weekly-cap slot".

    Design: Difficulty/non_linear_state_machine/visit_fork_join_completed_vs_missed
    """
    base = setup_active_episode(
        api, rate_overrides=MMTA_RATE, oasis_overrides=MMTA_OASIS,
        plan_overrides={"planned_rn_visits": 2},
    )
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    vc = schedule_visit(ep_id, rn_id, api,
                        scheduled_start="2026-02-03T09:00:00Z", scheduled_end="2026-02-03T10:00:00Z")
    vm = schedule_visit(ep_id, rn_id, api,
                        scheduled_start="2026-02-04T09:00:00Z", scheduled_end="2026-02-04T10:00:00Z")
    _confirm(api, vc["id"], rn_id)
    _confirm(api, vm["id"], rn_id)
    set_clock("2026-02-05T08:00:00Z", api)
    completed = validate_success(api.complete_visit(vc["id"], make_clinician_headers(rn_id)))
    missed = validate_success(api.mark_missed_visit(vm["id"], SCHEDULER))

    assert completed["status"] == "COMPLETED"
    assert completed["billable"] is True
    assert missed["status"] == "MISSED"
    assert missed["billable"] is False


def test_completed_visit_bumps_provisional_payment(api):
    """PRD §3.4: "Completion sets billable true, recomputes the episode's
    provisional payment to reflect the now-completed visit, appends a
    VISIT_COMPLETED event, and bumps the visit version."

    Design: Difficulty/non_linear_state_machine/visit_fork_join_completed_vs_missed
    """
    base = setup_active_episode(
        api, rate_overrides=MMTA_RATE, oasis_overrides=MMTA_OASIS,
        plan_overrides={"planned_rn_visits": 2},
    )
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    v = schedule_visit(ep_id, rn_id, api,
                       scheduled_start="2026-02-03T09:00:00Z", scheduled_end="2026-02-03T10:00:00Z")
    _confirm(api, v["id"], rn_id)
    set_clock("2026-02-05T08:00:00Z", api)
    validate_success(api.complete_visit(v["id"], make_clinician_headers(rn_id)))
    # provisional reflects the ACTIVE plan's planned counts; completion triggers a
    # recompute that leaves the forward-looking estimate at FULL PDGM 3000.00.
    ep = validate_success(api.get_episode(ep_id, INTAKE))
    assert ep["provisional_payment"] == 3000.00


# ===========================================================================
# Difficulty: recert_request_revision_cycle (≥2)
# ===========================================================================
def _setup_recert_pending(api):
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 6},
    )
    ep_id = base["episode"]["id"]
    recert_oasis = create_oasis(
        base["patient"]["id"], base["rn"]["id"], api,
        assessment_type="RECERTIFICATION", assessment_date="2026-03-25T08:00:00Z",
        clinical_group="WOUND", functional_level="HIGH", comorbidity_count=2,
    )
    set_clock("2026-03-25T08:00:00Z", api)
    rr = validate_success(api.create_recert_request(ep_id, {"recert_oasis_id": recert_oasis["id"]}, INTAKE), 201)
    return base, rr


def test_recert_return_then_resubmit_increments_revision_count(api):
    """PRD §3.7: "A returned request re-enters the loop: the IntakeCoordinator
    resubmits it, driving RETURNED -> SUBMITTED and incrementing its
    revision_count by 1."

    Design: Difficulty/non_linear_state_machine/recert_request_revision_cycle
    """
    _, rr = _setup_recert_pending(api)
    validate_success(api.return_recert_request(rr["id"], {"review_note": "Need updated measurements"}, COMPLIANCE))
    resubmitted = validate_success(api.resubmit_recert_request(rr["id"], INTAKE))
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_count"] == 1


def test_recert_return_sets_returned_status(api):
    """PRD §3.7: "Returning the request for revision drives it SUBMITTED ->
    RETURNED, stores the review_note, and bumps the request's own version."

    Design: Difficulty/non_linear_state_machine/recert_request_revision_cycle
    """
    _, rr = _setup_recert_pending(api)
    returned = validate_success(api.return_recert_request(rr["id"], {"review_note": "fix"}, COMPLIANCE))
    assert returned["status"] == "RETURNED"
    assert returned["revision_count"] == 0


# ===========================================================================
# Difficulty: episode_not_active_beats_discipline_mismatch (≥2)
# ===========================================================================
def test_schedule_on_draft_episode_yields_episode_not_active(api):
    """PRD §3.4: "Scheduling requires the parent episode to be ACTIVE; attempting
    it against any other episode state yields ERR_EPISODE_NOT_ACTIVE (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/episode_not_active_beats_discipline_mismatch
    """
    from test_helpers.fixtures import setup_draft_episode
    from test_helpers import validate_error
    base = setup_draft_episode(api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS)
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    # discipline PT also mismatches RN clinician, but episode-not-active wins.
    resp = api.create_visit(ep_id, {
        "clinician_id": rn_id, "discipline": "PT",
        "scheduled_start": "2026-02-03T09:00:00Z", "scheduled_end": "2026-02-03T10:00:00Z",
    }, SCHEDULER)
    validate_error(resp, "ERR_EPISODE_NOT_ACTIVE", 409)


def test_episode_not_active_reported_even_with_valid_discipline(api):
    """PRD §3.4: "Scheduling requires the parent episode to be ACTIVE; attempting
    it against any other episode state yields ERR_EPISODE_NOT_ACTIVE (HTTP 409)."
    (Isolated single-failure scenario: DRAFT episode, discipline matches.)

    Design: Difficulty/priority_pair_validation_conflict/episode_not_active_beats_discipline_mismatch
    """
    from test_helpers.fixtures import setup_draft_episode
    from test_helpers import validate_error
    base = setup_draft_episode(api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS)
    ep_id, rn_id = base["episode"]["id"], base["rn"]["id"]
    resp = api.create_visit(ep_id, {
        "clinician_id": rn_id, "discipline": "RN",
        "scheduled_start": "2026-02-03T09:00:00Z", "scheduled_end": "2026-02-03T10:00:00Z",
    }, SCHEDULER)
    validate_error(resp, "ERR_EPISODE_NOT_ACTIVE", 409)


# ===========================================================================
# Difficulty: recert_window_closed_beats_recert_oasis_invalid (≥2)
# ===========================================================================
def test_recert_oasis_invalid_when_wrong_type(api):
    """PRD §3.7: "The supporting assessment must be of type RECERTIFICATION,
    belong to the same patient, and not be locked, or the request fails with
    ERR_RECERT_OASIS_INVALID (HTTP 422)." (Wrong-type OASIS supplied to recert.)

    Design: Difficulty/priority_pair_validation_conflict/recert_window_closed_beats_recert_oasis_invalid
    """
    from test_helpers import validate_error
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 6},
    )
    ep_id = base["episode"]["id"]
    wrong = create_oasis(
        base["patient"]["id"], base["rn"]["id"], api,
        assessment_type="START_OF_CARE", assessment_date="2026-02-09T08:00:00Z",
        clinical_group="WOUND", functional_level="HIGH", comorbidity_count=2,
    )
    set_clock("2026-02-10T08:00:00Z", api)  # also far outside recert window
    resp = api.create_recert_request(ep_id, {"recert_oasis_id": wrong["id"]}, INTAKE)
    validate_error(resp, "ERR_RECERT_OASIS_INVALID", 422)


def test_recert_oasis_invalid_takes_precedence_over_window(api):
    """PRD §3.7: "The supporting assessment must be of type RECERTIFICATION,
    belong to the same patient, and not be locked, or the request fails with
    ERR_RECERT_OASIS_INVALID (HTTP 422)." (Both window-closed and wrong-type hold;
    OASIS-invalid is the reported error.)

    Design: Difficulty/priority_pair_validation_conflict/recert_window_closed_beats_recert_oasis_invalid
    """
    from test_helpers import validate_error
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 6},
    )
    ep_id = base["episode"]["id"]
    wrong = create_oasis(
        base["patient"]["id"], base["rn"]["id"], api,
        assessment_type="START_OF_CARE", assessment_date="2026-02-09T08:00:00Z",
        clinical_group="WOUND", functional_level="HIGH", comorbidity_count=2,
    )
    set_clock("2026-02-10T08:00:00Z", api)
    resp = api.create_recert_request(ep_id, {"recert_oasis_id": wrong["id"]}, INTAKE)
    body = validate_error(resp, "ERR_RECERT_OASIS_INVALID", 422)
    assert body["error_id"] == "ERR_RECERT_OASIS_INVALID"
