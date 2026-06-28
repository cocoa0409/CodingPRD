"""Validation-priority conflicts, cross-entity state dependencies (permit gates,
warranty-gated retests), crew/closing-deadline temporal conflicts, and the
job-cancel deposit-refund net-zero conservation invariant.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_installed_job, setup_scheduled_job, setup_quoted_job,
    setup_cleared_job_with_warranty,
    set_clock, get_property, pay, issue_permit, create_crew,
    create_radon_test_payload, retrieve_short_term_payload, schedule_payload,
    create_payment_payload, cancel_warranty_payload,
    make_inspector_headers, make_crew_lead_headers, make_client_contact_headers,
    DESIGNER, COMPLIANCE, TEST_USERS, ApiErrorId,
)


def test_retrieve_on_retrieved_test_hits_state_not_window(api):
    """PRD §2.5: "Validation proceeds in a fixed priority order, and the first
    failing check determines the response."
    PRD §2.5: "Fifth, the target resource must be in a state from which the
    requested transition is legal, otherwise `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_beats_placement_window_safety
    """
    from test_helpers import create_inspector, create_property
    inspector = create_inspector()
    insp = make_inspector_headers(inspector["id"])
    prop = create_property()
    test = get_success_data(api.create_radon_test(
        create_radon_test_payload(prop["id"], inspector["id"],
                                  test_kind="SHORT_TERM_48HR", purpose="INITIAL",
                                  placement_window_hours=48),
        insp))
    set_clock("2026-04-03T00:00:00Z")  # window exactly met
    validate_success(api.retrieve_radon_test(
        test["id"], retrieve_short_term_payload(3.0), insp), 200)
    # Second retrieve: test is now RETRIEVED → state check fires first.
    res = api.retrieve_radon_test(test["id"], retrieve_short_term_payload(3.0), insp)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_state_rejected_retrieve_leaves_test_in_retrieved(api):
    """PRD §3.2: "Retrieval is the inspector's act of collecting the device and
    supplying its data, moving the test from `PLACED` to `RETRIEVED`."
    PRD §2.5: "the target resource must be in a state from which the requested
    transition is legal, otherwise `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_beats_placement_window_safety
    """
    from test_helpers import create_inspector, create_property
    inspector = create_inspector()
    insp = make_inspector_headers(inspector["id"])
    prop = create_property()
    test = get_success_data(api.create_radon_test(
        create_radon_test_payload(prop["id"], inspector["id"],
                                  test_kind="SHORT_TERM_48HR", purpose="INITIAL",
                                  placement_window_hours=48),
        insp))
    set_clock("2026-04-03T00:00:00Z")
    validate_success(api.retrieve_radon_test(
        test["id"], retrieve_short_term_payload(3.0), insp), 200)
    validate_error(
        api.retrieve_radon_test(test["id"], retrieve_short_term_payload(3.0), insp),
        ApiErrorId.ERR_INVALID_STATE.value)
    # The rejected second retrieve did not corrupt the RETRIEVED state.
    fetched = validate_success(api.get_radon_test(test["id"], insp), 200)
    assert fetched["status"] == "RETRIEVED"


def test_complete_install_without_permit_hits_permit_not_balance(api):
    """PRD §3.5: "the job must have a `permit_id` pointing at a permit whose
    status is `ISSUED`, else `ERR_PERMIT_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_safety_beats_fiscal_on_complete_install
    """
    # SCHEDULED with deposit only (no balance), no permit issued.
    _, _, _, job, crew = setup_scheduled_job(
        foundation_type="SLAB", floor_area_sqft=1400, pay_balance=False,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    crew_headers = make_crew_lead_headers(crew["id"])
    res = api.complete_install(job["id"], crew_headers)
    validate_error(res, ApiErrorId.ERR_PERMIT_REQUIRED.value)


def test_complete_install_permit_block_leaves_job_scheduled(api):
    """PRD §3.5: "the job must have a `permit_id` pointing at a permit whose
    status is `ISSUED`, else `ERR_PERMIT_REQUIRED`."
    PRD §3.5: "Completing the install, performed by a `CrewLead`, moves the job
    from `SCHEDULED` to `INSTALLED`."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_safety_beats_fiscal_on_complete_install
    """
    _, _, _, job, crew = setup_scheduled_job(
        foundation_type="SLAB", floor_area_sqft=1400, pay_balance=False,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    crew_headers = make_crew_lead_headers(crew["id"])
    validate_error(api.complete_install(job["id"], crew_headers),
                   ApiErrorId.ERR_PERMIT_REQUIRED.value)
    # The blocked install left the job in SCHEDULED (not INSTALLED).
    fetched = validate_success(api.get_mitigation_job(job["id"], DESIGNER), 200)
    assert fetched["status"] == "SCHEDULED"


def test_install_blocked_after_permit_revoked(api):
    """PRD §3.5: "Revocation clears the job's `permit_id`, so the job once again
    lacks a permit and its install is blocked."
    PRD §3.5: "the job must have a `permit_id` pointing at a permit whose status
    is `ISSUED`, else `ERR_PERMIT_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/cesd_install_requires_issued_permit
    """
    _, _, _, job, crew = setup_scheduled_job(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    permit = issue_permit(job["id"])
    validate_success(api.revoke_permit(permit["id"], COMPLIANCE), 200)
    crew_headers = make_crew_lead_headers(crew["id"])
    res = api.complete_install(job["id"], crew_headers)
    validate_error(res, ApiErrorId.ERR_PERMIT_REQUIRED.value)


def test_permit_revoke_clears_job_permit_id(api):
    """PRD §3.5: "A `ComplianceOfficer` or `PlatformAdmin` may revoke an `ISSUED`
    permit, moving it to `REVOKED`."
    PRD §3.5: "Revocation clears the job's `permit_id`, so the job once again
    lacks a permit and its install is blocked."

    Design: Difficulty/cross_entity_state_dependency/cesd_install_requires_issued_permit
    """
    _, _, _, job, crew = setup_scheduled_job(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    permit = issue_permit(job["id"])
    job_with_permit = validate_success(api.get_mitigation_job(job["id"], DESIGNER), 200)
    assert job_with_permit["permit_id"] == permit["id"]
    revoked = validate_success(api.revoke_permit(permit["id"], COMPLIANCE), 200)
    assert revoked["status"] == "REVOKED"
    job_after = validate_success(api.get_mitigation_job(job["id"], DESIGNER), 200)
    assert job_after["permit_id"] is None


def test_fire_due_on_ended_schedule_after_warranty_cancel(api):
    """PRD §3.7: "When the parent warranty leaves `ACTIVE` — whether through
    expiry or cancellation — the schedule is cascaded to `ENDED`, which is
    terminal."
    PRD §2.5: "the target resource must be in a state from which the requested
    transition is legal, otherwise `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/cesd_retest_fire_requires_active_warranty
    """
    _, prop, _, warranty, schedule, _ = setup_cleared_job_with_warranty(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    client = make_client_contact_headers(prop["id"])
    fresh = validate_success(api.get_warranty(warranty["id"], client), 200)
    validate_success(api.cancel_warranty(
        warranty["id"], cancel_warranty_payload(fresh["version"]), client), 200)
    set_clock("2028-04-03T00:00:00Z")
    res = api.fire_due(schedule["id"], COMPLIANCE)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_warranty_cancel_cascades_schedule_to_ended(api):
    """PRD §3.6: "the retest schedule is cascaded to `ENDED`, and the warranty
    `version` increments."
    PRD §3.7: "When the parent warranty leaves `ACTIVE` — whether through expiry
    or cancellation — the schedule is cascaded to `ENDED`, which is terminal."

    Design: Difficulty/cross_entity_state_dependency/cesd_retest_fire_requires_active_warranty
    """
    _, prop, _, warranty, schedule, _ = setup_cleared_job_with_warranty(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    client = make_client_contact_headers(prop["id"])
    fresh = validate_success(api.get_warranty(warranty["id"], client), 200)
    validate_success(api.cancel_warranty(
        warranty["id"], cancel_warranty_payload(fresh["version"]), client), 200)
    # The warranty leaving ACTIVE cascaded the schedule to the terminal ENDED.
    sched_after = validate_success(
        api.get_retest_schedule(schedule["id"], COMPLIANCE), 200)
    assert sched_after["status"] == "ENDED"


def test_crew_window_half_open_overlap_rejected(api):
    """PRD §3.5: "the new window must not overlap an existing `SCHEDULED` job's
    window for that same crew, where adjacency on a half-open interval (one
    window ending exactly as another begins) is allowed; a violation is rejected
    with `ERR_CREW_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/rto_crew_window_half_open_overlap
    """
    crew = create_crew(max_jobs_per_day=2)
    # First job J1 SCHEDULED [08:00,12:00) on the shared crew.
    setup_scheduled_job(foundation_type="SLAB", floor_area_sqft=1400,
                        crew=crew, pay_balance=False,
                        install_start_utc="2026-04-03T08:00:00Z",
                        install_end_utc="2026-04-03T12:00:00Z",
                        job_overrides={"num_suction_points": 1,
                                       "has_sump_pump": False, "is_rush": False})
    # Second job J2 QUOTED + deposit, ready to schedule against the same crew.
    _, prop2, _, job2 = setup_quoted_job(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    pay(job2["id"], "DEPOSIT", job2["deposit_required_cents"])
    prop2_now = get_property(prop2["id"])
    # [11:00,15:00) overlaps [08:00,12:00).
    res = api.schedule_job(
        job2["id"],
        schedule_payload(crew["id"], "2026-04-03T11:00:00Z",
                         "2026-04-03T15:00:00Z", prop2_now["version"]),
        DESIGNER)
    validate_error(res, ApiErrorId.ERR_CREW_WINDOW_CONFLICT.value)


def test_crew_window_adjacent_at_boundary_allowed(api):
    """PRD §3.5: "the new window must not overlap an existing `SCHEDULED` job's
    window for that same crew, where adjacency on a half-open interval (one
    window ending exactly as another begins) is allowed; a violation is rejected
    with `ERR_CREW_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/rto_crew_window_half_open_overlap
    """
    crew = create_crew(max_jobs_per_day=2)
    setup_scheduled_job(foundation_type="SLAB", floor_area_sqft=1400,
                        crew=crew, pay_balance=False,
                        install_start_utc="2026-04-03T08:00:00Z",
                        install_end_utc="2026-04-03T12:00:00Z",
                        job_overrides={"num_suction_points": 1,
                                       "has_sump_pump": False, "is_rush": False})
    _, prop2, _, job2 = setup_quoted_job(
        foundation_type="SLAB", floor_area_sqft=1400,
        job_overrides={"num_suction_points": 1, "has_sump_pump": False,
                       "is_rush": False})
    pay(job2["id"], "DEPOSIT", job2["deposit_required_cents"])
    prop2_now = get_property(prop2["id"])
    # [12:00,16:00) begins exactly as [08:00,12:00) ends → adjacency allowed.
    scheduled = validate_success(api.schedule_job(
        job2["id"],
        schedule_payload(crew["id"], "2026-04-03T12:00:00Z",
                         "2026-04-03T16:00:00Z", prop2_now["version"]),
        DESIGNER), 200)
    assert scheduled["status"] == "SCHEDULED"


def test_rush_install_window_past_closing_deadline_rejected(api):
    """PRD §3.5: "When the job is a rush job, the window must not run past the
    property's closing deadline — `install_end_utc` must be at or before
    `closing_deadline_utc` — else `ERR_RUSH_DEADLINE_MISSED`."

    Design: Difficulty/resource_temporal_overlap/rto_rush_window_against_closing_deadline
    """
    crew = create_crew(max_jobs_per_day=2)
    _, prop, _, job = setup_quoted_job(
        foundation_type="BASEMENT", floor_area_sqft=2200,
        is_real_estate_transaction=True,
        closing_deadline_utc="2026-04-10T00:00:00Z",
        job_overrides={"num_suction_points": 3, "has_sump_pump": True,
                       "is_rush": True})
    pay(job["id"], "DEPOSIT", job["deposit_required_cents"])
    prop_now = get_property(prop["id"])
    # install_end 2026-04-12 is after the 2026-04-10 closing deadline.
    res = api.schedule_job(
        job["id"],
        schedule_payload(crew["id"], "2026-04-12T08:00:00Z",
                         "2026-04-12T12:00:00Z", prop_now["version"]),
        DESIGNER)
    validate_error(res, ApiErrorId.ERR_RUSH_DEADLINE_MISSED.value)


def test_rush_install_window_within_closing_deadline_allowed(api):
    """PRD §3.5: "When the job is a rush job, the window must not run past the
    property's closing deadline — `install_end_utc` must be at or before
    `closing_deadline_utc` — else `ERR_RUSH_DEADLINE_MISSED`."

    Design: Difficulty/resource_temporal_overlap/rto_rush_window_against_closing_deadline
    """
    crew = create_crew(max_jobs_per_day=2)
    _, prop, _, job = setup_quoted_job(
        foundation_type="BASEMENT", floor_area_sqft=2200,
        is_real_estate_transaction=True,
        closing_deadline_utc="2026-04-10T00:00:00Z",
        job_overrides={"num_suction_points": 3, "has_sump_pump": True,
                       "is_rush": True})
    pay(job["id"], "DEPOSIT", job["deposit_required_cents"])
    prop_now = get_property(prop["id"])
    # install_end 2026-04-09 is before the 2026-04-10 closing deadline → allowed.
    scheduled = validate_success(api.schedule_job(
        job["id"],
        schedule_payload(crew["id"], "2026-04-09T08:00:00Z",
                         "2026-04-09T12:00:00Z", prop_now["version"]),
        DESIGNER), 200)
    assert scheduled["status"] == "SCHEDULED"


def test_cancel_quoted_job_refunds_deposit_status_cancelled(api):
    """PRD §3.5: "If the job had already collected a deposit — `deposit_paid_cents`
    greater than zero — the cancellation appends a `REFUND` ledger entry for the
    negative of `deposit_paid_cents` and resets `deposit_paid_cents` to zero, so
    the total recorded cash on the job returns to zero."

    Design: Difficulty/compensating_invariant/ci_job_cancel_deposit_refund_nets_to_zero_cash
    """
    _, _, _, job = setup_quoted_job(
        foundation_type="BASEMENT", floor_area_sqft=2200,
        is_real_estate_transaction=True,
        closing_deadline_utc="2026-05-01T00:00:00Z",
        job_overrides={"num_suction_points": 3, "has_sump_pump": True,
                       "is_rush": True})
    pay(job["id"], "DEPOSIT", 123165)
    cancelled = validate_success(api.cancel_job(job["id"], DESIGNER), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["deposit_paid_cents"] == 0


def test_cancel_quoted_job_net_recorded_cash_returns_to_zero(api):
    """PRD §3.5: "the cancellation appends a `REFUND` ledger entry for the
    negative of `deposit_paid_cents` and resets `deposit_paid_cents` to zero, so
    the total recorded cash on the job returns to zero."

    Design: Difficulty/compensating_invariant/ci_job_cancel_deposit_refund_nets_to_zero_cash
    """
    _, _, _, job = setup_quoted_job(
        foundation_type="BASEMENT", floor_area_sqft=2200,
        is_real_estate_transaction=True,
        closing_deadline_utc="2026-05-01T00:00:00Z",
        job_overrides={"num_suction_points": 3, "has_sump_pump": True,
                       "is_rush": True})
    pay(job["id"], "DEPOSIT", 123165)
    validate_success(api.cancel_job(job["id"], DESIGNER), 200)
    client = TEST_USERS["client_contact_headers"]
    records = api.list_payment_records(
        client, params={"mitigation_job_id": job["id"]}).json()["data"]
    net = sum(r["amount_cents"] for r in records)
    assert net == 0, f"net recorded cash should be 0, got {net}"
