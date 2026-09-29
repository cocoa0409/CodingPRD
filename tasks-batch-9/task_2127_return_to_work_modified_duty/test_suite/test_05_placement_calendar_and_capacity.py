"""The calendar and capacity ladder that guards placement creation, and the
normative order in which competing rejections fire."""
from test_helpers import (
    ApiErrorId,
    create_placement_payload,
    fixtures,
    validate_error,
    validate_success,
)


def test_a_successor_window_overlapping_the_incumbent_by_one_day_is_refused(api):
    """PRD §3.4: "At priority 26, a worker may not be double-booked: treating each placement window as **half-open**, running from `start_date` up to but not including `end_date`, the proposed window must not intersect the window of any other placement of the same worker whose `placement_status` is `PROPOSED`, `ADJUSTER_PENDING`, `ACTIVE`, `PROGRESSION_HOLD` or `SUSPENDED`."
    PRD §3.4: "A collision answers `ERR_PLACEMENT_WINDOW_OVERLAP` with HTTP 409, and the rule applies to both creation routes and to extension."

    Design: Difficulty/resource_temporal_overlap/employee_half_open_window_allows_adjacency_rejects_one_day_overlap
    """
    ctx = fixtures.setup_proposed_placement()
    version = fixtures.current_restriction_set_version(ctx["restriction_set_id"])

    resp = api.create_placement(
        create_placement_payload(
            ctx["restriction_set_id"], ctx["job_id"], version,
            start_date="2026-08-27", end_date="2026-09-15",
        ),
        fixtures.COORD,
    )

    validate_error(resp, ApiErrorId.ERR_PLACEMENT_WINDOW_OVERLAP, 409)
    incumbent = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))
    assert incumbent["placement_status"] == "PROPOSED"


def test_a_successor_starting_on_the_incumbents_end_date_is_admitted(api):
    """PRD §3.4: "Adjacency is explicitly legal here — a window beginning exactly on another's `end_date` does not collide, and a zero-day gap between two of a worker's assignments is fine."

    Design: Difficulty/resource_temporal_overlap/employee_half_open_window_allows_adjacency_rejects_one_day_overlap
    """
    ctx = fixtures.setup_proposed_placement()
    version = fixtures.current_restriction_set_version(ctx["restriction_set_id"])

    data = validate_success(
        api.create_placement(
            create_placement_payload(
                ctx["restriction_set_id"], ctx["job_id"], version,
                start_date="2026-08-28", end_date="2026-09-15",
            ),
            fixtures.COORD,
        ),
        201,
    )

    assert data["start_date"] == "2026-08-28"
    assert data["placement_status"] == "PROPOSED"


def test_a_successor_starting_one_day_after_the_occupant_breaches_the_changeover_buffer(api):
    """PRD §3.4: "At priority 27, the same job may not be handed from one occupant to the next without a changeover gap: treating each placement window on that job as the **closed** interval from `start_date` through `end_date` inclusive, a proposed window is rejected whenever the number of days from an existing occupant's `end_date` to the proposed `start_date` is at least zero and no more than the one-day changeover buffer, counting only occupants whose `placement_status` is `ADJUSTER_PENDING`, `ACTIVE` or `PROGRESSION_HOLD`."

    Design: Difficulty/resource_temporal_overlap/job_closed_interval_changeover_buffer_rejects_next_day_start
    """
    ctx = fixtures.setup_routed_placement()
    version = fixtures.current_restriction_set_version(ctx["restriction_set_id"])

    resp = api.create_placement(
        create_placement_payload(
            ctx["restriction_set_id"], ctx["job_id"], version,
            start_date="2026-08-29", end_date="2026-09-15",
        ),
        fixtures.COORD,
    )

    validate_error(resp, ApiErrorId.ERR_JOB_CHANGEOVER_BUFFER, 409)
    occupant = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))
    assert occupant["placement_status"] == "ADJUSTER_PENDING"


def test_a_successor_starting_two_days_after_the_occupant_is_admitted(api):
    """PRD §3.4: "Unlike the worker rule, both endpoints are inclusive here and a zero-day gap is forbidden; the earliest legal successor start is two days after the outgoing occupant's `end_date`."
    PRD §3.4: "A violation answers `ERR_JOB_CHANGEOVER_BUFFER` with HTTP 409, and this rule guards both creation routes."

    Design: Difficulty/resource_temporal_overlap/job_closed_interval_changeover_buffer_rejects_next_day_start
    """
    ctx = fixtures.setup_routed_placement()
    version = fixtures.current_restriction_set_version(ctx["restriction_set_id"])

    data = validate_success(
        api.create_placement(
            create_placement_payload(
                ctx["restriction_set_id"], ctx["job_id"], version,
                start_date="2026-08-30", end_date="2026-09-15",
            ),
            fixtures.COORD,
        ),
        201,
    )

    assert data["start_date"] == "2026-08-30"
    assert data["placement_status"] == "PROPOSED"


def test_a_second_worker_cannot_take_the_only_seat_on_an_occupied_day(api):
    """PRD §3.4: "At priority 29, for every calendar day inside the proposed closed window from `start_date` through `end_date`, the count of placements already on that job whose `placement_status` is `ADJUSTER_PENDING`, `ACTIVE` or `PROGRESSION_HOLD` and whose own window covers that day, plus one for the incoming placement, must not exceed the job's `seat_capacity`. Exceeding it on even a single day answers `ERR_JOB_SEAT_UNAVAILABLE` with HTTP 409."

    Design: Corner/validations/job_seat_capacity_exceeded_by_second_worker_is_rejected
    """
    ctx = fixtures.setup_routed_placement(job_overrides={"seat_capacity": 1})
    second = fixtures.add_second_worker(ctx)

    resp = api.create_placement(
        create_placement_payload(
            second["restriction_set_id"], ctx["job_id"], second["restriction_set_version"],
            start_date="2026-08-10", end_date="2026-08-20",
        ),
        fixtures.COORD,
    )

    validate_error(resp, ApiErrorId.ERR_JOB_SEAT_UNAVAILABLE, 409)
    job = validate_success(api.get_transitional_job(ctx["job_id"], fixtures.COORD))
    assert job["filled_seats"] == 1, "the incumbent still holds the single seat"


def test_a_window_beyond_the_restrictions_validity_is_refused(api):
    """PRD §3.4: "At priority 25, the placement window must sit entirely inside the restriction window: `start_date` must be on or after the set's `effective_from` and `end_date` must be on or before the set's `valid_through`, or the request answers `ERR_PLACEMENT_OUTSIDE_RESTRICTION_WINDOW` with HTTP 422; this rule also guards extension."

    Design: Corner/errors/placement_window_outside_restriction_validity_is_refused
    """
    ctx = fixtures.setup_active_restriction_set()

    resp = api.create_placement(
        create_placement_payload(
            ctx["restriction_set_id"], ctx["job_id"], ctx["restriction_set_version"],
            start_date="2026-12-01", end_date="2026-12-20",
        ),
        fixtures.COORD,
    )

    validate_error(resp, ApiErrorId.ERR_PLACEMENT_OUTSIDE_RESTRICTION_WINDOW, 422)


def test_a_restricted_posture_bars_brand_new_transitional_work(api):
    """PRD §3.1: "A `FROZEN` posture bars placement creation by either route, adjuster routing, activation, extension and resumption, each answering `ERR_CLAIM_POSTURE_FROZEN`; a `RESTRICTED` posture additionally bars only the two operations that mint brand-new transitional work — explicit placement creation and selector-driven matching — answering `ERR_CLAIM_POSTURE_RESTRICTED`."
    PRD §3.1: "Otherwise it lands on `RESTRICTED` when some placement of the claim is in `ACTIVE`, `PROGRESSION_HOLD` or `SUSPENDED` while its `compliance_status` is `WATCH` or `NONCOMPLIANT`"

    Design: Corner/validations/restricted_claim_posture_blocks_a_new_placement
    """
    ctx = fixtures.setup_active_placement()
    fixtures.drive_placement_to_watch(ctx)
    version = fixtures.current_restriction_set_version(ctx["restriction_set_id"])

    resp = api.create_placement(
        create_placement_payload(
            ctx["restriction_set_id"], ctx["job_id"], version,
            start_date="2026-09-01", end_date="2026-09-20",
        ),
        fixtures.COORD,
    )

    validate_error(resp, ApiErrorId.ERR_CLAIM_POSTURE_RESTRICTED, 409)
    claim = validate_success(api.get_claim(ctx["claim_id"], fixtures.COORD))
    assert claim["rtw_posture"] == "RESTRICTED"


def test_a_closed_claim_refuses_new_transitional_work(api):
    """PRD §3.1: "Because placement creation demands `RTW_ELIGIBLE` at priority 11, a claim left at `OPEN`, moved to `SUSPENDED`, or `CLOSED` will refuse new transitional work with `ERR_CLAIM_NOT_RTW_ELIGIBLE`."
    PRD §3.1: "the caller supplies a `claim_status_directive` of `RTW_ELIGIBLE`, `SUSPENDED` or `CLOSED`, which is written straight onto `claim_status`"

    Design: Corner/validations/closed_claim_blocks_placement_creation
    """
    ctx = fixtures.setup_active_restriction_set()
    fixtures.authorize_claim(ctx["claim_id"], claim_status_directive="CLOSED")

    resp = api.create_placement(
        create_placement_payload(
            ctx["restriction_set_id"], ctx["job_id"], ctx["restriction_set_version"]
        ),
        fixtures.COORD,
    )

    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_RTW_ELIGIBLE, 409)
    claim = validate_success(api.get_claim(ctx["claim_id"], fixtures.COORD))
    assert claim["claim_status"] == "CLOSED"
    restriction_set = validate_success(
        api.get_restriction_set(ctx["restriction_set_id"], fixtures.COORD)
    )
    assert restriction_set["status"] == "ACTIVE", "the restriction set is untouched"


def test_an_inactive_restriction_set_outranks_a_frozen_posture(api):
    """PRD §2.6: "After the generic state screen come the domain state screens, in this order: the referenced restriction set must be `ACTIVE` (priority 10, `ERR_RESTRICTION_SET_NOT_ACTIVE`); the owning claim must be `RTW_ELIGIBLE` (priority 11, `ERR_CLAIM_NOT_RTW_ELIGIBLE`)"
    PRD §2.6: "Then the claim-posture gates: not `FROZEN` (priority 15, `ERR_CLAIM_POSTURE_FROZEN`) and, on the two endpoints that create brand-new transitional work, not `RESTRICTED` either (priority 16, `ERR_CLAIM_POSTURE_RESTRICTED`)."
    PRD §2.6: "Because a single request can violate several rules at once, the order in which checks run is normative: an implementation that reports a *different but also true* failure is wrong."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_inactive_restriction_set_wins_over_frozen_posture
    """
    ctx = fixtures.setup_active_placement()
    fixtures.convene_panel(ctx, trigger_reason="COMPLIANCE_CRITICAL", quorum_required=3)
    second = fixtures.file_restriction_set(ctx, max_lift_lbs=8)
    verified = fixtures.walk_restriction_set_to_verified(ctx, second["id"])

    resp = api.create_placement(
        create_placement_payload(
            second["id"], ctx["job_id"], verified["version"],
            start_date="2026-09-01", end_date="2026-09-20",
        ),
        fixtures.COORD,
    )

    validate_error(resp, ApiErrorId.ERR_RESTRICTION_SET_NOT_ACTIVE, 409)


def test_the_frozen_posture_and_the_verified_set_both_survive_that_rejection(api):
    """PRD §3.1: "The posture lands on `FROZEN` when the claim's `claim_status` is `SUSPENDED`, or when any case-review panel attached to any of the claim's placements sits in `OPEN` or `VOTING`."
    PRD §2.6: "the referenced restriction set must be `ACTIVE` (priority 10, `ERR_RESTRICTION_SET_NOT_ACTIVE`)"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_inactive_restriction_set_wins_over_frozen_posture
    """
    ctx = fixtures.setup_active_placement()
    fixtures.convene_panel(ctx, trigger_reason="COMPLIANCE_CRITICAL", quorum_required=3)
    second = fixtures.file_restriction_set(ctx, max_lift_lbs=8)
    verified = fixtures.walk_restriction_set_to_verified(ctx, second["id"])
    api.create_placement(
        create_placement_payload(
            second["id"], ctx["job_id"], verified["version"],
            start_date="2026-09-01", end_date="2026-09-20",
        ),
        fixtures.COORD,
    )

    claim = validate_success(api.get_claim(ctx["claim_id"], fixtures.COORD))
    assert claim["rtw_posture"] == "FROZEN", (
        "the open panel really does hold the claim at FROZEN, so both rules were violated"
    )
    unchanged = validate_success(api.get_restriction_set(second["id"], fixtures.COORD))
    assert unchanged["status"] == "VERIFIED"


def test_a_restriction_violation_outranks_a_worker_window_overlap(api):
    """PRD §3.4: "At priority 19 the hard restriction limits are enforced on explicit creation and again whenever an assignment is extended: `demand_lift_lbs` must not exceed `max_lift_lbs`, `demand_standing_minutes` must not exceed `max_continuous_standing_minutes`, `demand_hours_per_day` must not exceed `max_hours_per_day`, and `demand_keyboard_minutes_per_hour` must not exceed `keyboard_minutes_per_hour`"
    PRD §3.4: "a job whose `requires_overhead_reach` is true is only acceptable when `overhead_reach_allowed` is true, and a job whose `requires_driving` is true is only acceptable when `driving_allowed` is true; and the requested `scheduled_hours_per_day` must not exceed `max_hours_per_day`. Any breach answers `ERR_RESTRICTION_VIOLATION` with HTTP 422."
    PRD §2.6: "Because a single request can violate several rules at once, the order in which checks run is normative: an implementation that reports a *different but also true* failure is wrong."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_restriction_violation_wins_over_window_overlap
    """
    ctx = fixtures.setup_proposed_placement()
    heavy_job = fixtures.create_transitional_job(
        ctx["supervisor_id"], title="Pallet Stager", seat_capacity=1, demand_lift_lbs=25,
    )
    version = fixtures.current_restriction_set_version(ctx["restriction_set_id"])

    resp = api.create_placement(
        create_placement_payload(
            ctx["restriction_set_id"], heavy_job["id"], version,
            start_date="2026-08-10", end_date="2026-08-20",
        ),
        fixtures.COORD,
    )

    validate_error(resp, ApiErrorId.ERR_RESTRICTION_VIOLATION, 422)


def test_the_incumbent_window_is_untouched_by_the_rejected_creation(api):
    """PRD §3.4: "At priority 26, a worker may not be double-booked: treating each placement window as **half-open**, running from `start_date` up to but not including `end_date`, the proposed window must not intersect the window of any other placement of the same worker whose `placement_status` is `PROPOSED`, `ADJUSTER_PENDING`, `ACTIVE`, `PROGRESSION_HOLD` or `SUSPENDED`."
    PRD §3.4: "a job whose `requires_overhead_reach` is true is only acceptable when `overhead_reach_allowed` is true, and a job whose `requires_driving` is true is only acceptable when `driving_allowed` is true; and the requested `scheduled_hours_per_day` must not exceed `max_hours_per_day`. Any breach answers `ERR_RESTRICTION_VIOLATION` with HTTP 422."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_restriction_violation_wins_over_window_overlap
    """
    ctx = fixtures.setup_proposed_placement()
    heavy_job = fixtures.create_transitional_job(
        ctx["supervisor_id"], title="Pallet Stager", seat_capacity=1, demand_lift_lbs=25,
    )
    version = fixtures.current_restriction_set_version(ctx["restriction_set_id"])
    api.create_placement(
        create_placement_payload(
            ctx["restriction_set_id"], heavy_job["id"], version,
            start_date="2026-08-10", end_date="2026-08-20",
        ),
        fixtures.COORD,
    )

    incumbent = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))
    assert incumbent["placement_status"] == "PROPOSED", (
        "the incumbent 2026-08-03..2026-08-28 window that the request also collided with "
        "is left exactly as it was"
    )
    assert incumbent["start_date"] == "2026-08-03"
    assert incumbent["end_date"] == "2026-08-28"
