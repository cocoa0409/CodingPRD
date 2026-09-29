"""Running the assignment: daily hours, interruption, the duration ledger,
extension caps and closure."""
from test_helpers import (
    ApiErrorId,
    assert_placement_dimensions_independent,
    assert_seat_ledger,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_logging_more_hours_than_the_active_restriction_allows_is_refused(api):
    """PRD §3.6: "At priority 22, the `hours_worked` figure may not exceed the `max_hours_per_day` published by the claim's *currently* `ACTIVE` restriction set — not the set pinned on the placement at creation — and an excess answers `ERR_HOURS_EXCEED_RESTRICTION` with HTTP 422."

    Design: Corner/validations/hours_log_above_restriction_maximum_is_rejected
    """
    ctx = fixtures.setup_active_placement()

    resp = api.log_placement_hours(
        ctx["placement_id"], {"work_date": "2026-08-03", "hours_worked": 7},
        ctx["supervisor_headers"],
    )

    validate_error(resp, ApiErrorId.ERR_HOURS_EXCEED_RESTRICTION, 422)
    placement = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))
    assert placement["logged_hours"] == [], "nothing is written when the figure is refused"


def test_a_supervisor_may_not_log_hours_on_someone_elses_placement(api):
    """PRD §2.1: "When `X-User-Role` is `Supervisor`, `X-User-ID` is the `id` of the acting `Supervisor`; ownership checks compare it to the addressed placement's `supervisor_id`, to the addressed training record's `supervisor_id`, or to the supervisor id named in the URL path."
    PRD §2.1: "Any mismatch on one of these three roles is refused with `ERR_NOT_RESOURCE_OWNER` and HTTP 403."

    Design: Corner/validations/supervisor_cannot_log_hours_on_another_supervisors_placement
    """
    ctx = fixtures.setup_active_placement()
    other = fixtures.add_second_supervisor()

    resp = api.log_placement_hours(
        ctx["placement_id"], {"work_date": "2026-08-03", "hours_worked": 4},
        fixtures.make_supervisor_headers(other["id"]),
    )

    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)
    placement = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))
    assert placement["logged_hours"] == []


def test_a_monitoring_finding_moves_only_the_compliance_dimension(api):
    """PRD §2.9: "A placement can be `ACTIVE` and `NONCOMPLIANT` at the same time; a compliance movement never by itself changes `placement_status`, and a lifecycle movement never by itself changes `compliance_status`."
    PRD §3.8: "From `COMPLIANT`, a finding of `MINOR` or `MAJOR` moves the placement `COMPLIANT → WATCH`, while a finding of `CRITICAL` moves it straight `COMPLIANT → NONCOMPLIANT`."

    Design: Difficulty/non_linear_state_machine/placement_parallel_status_and_compliance_dimensions_move_independently
    """
    ctx = fixtures.setup_active_placement()

    fixtures.file_compliance_audit(
        ctx, observed_on="2026-08-01", finding_severity="MINOR", finding_code="DOCUMENTATION"
    )

    placement = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))
    assert_placement_dimensions_independent(placement, "ACTIVE", "WATCH")


def test_the_suspend_resume_cycle_leaves_the_compliance_dimension_untouched(api):
    """PRD §2.9: "`placement_status` is the lifecycle dimension, moving through `PROPOSED`, `ADJUSTER_PENDING`, `ACTIVE`, `PROGRESSION_HOLD`, `SUSPENDED`, and terminating in `COMPLETED`, `TERMINATED_EARLY` or `DECLINED`. `compliance_status` is the monitoring dimension, cycling among `COMPLIANT`, `WATCH`, `NONCOMPLIANT` and `REMEDIATED` purely under the influence of monitoring observations and supervisor-suspension cascades."
    PRD §3.6: "Resuming clears `suspension_reason`, raises the job's `filled_seats` by 1, and raises the placement's `version` by 1. The `ACTIVE → SUSPENDED → ACTIVE` cycle may run repeatedly."

    Design: Difficulty/non_linear_state_machine/placement_parallel_status_and_compliance_dimensions_move_independently
    """
    ctx = fixtures.setup_active_placement()
    fixtures.file_compliance_audit(
        ctx, observed_on="2026-08-01", finding_severity="MINOR", finding_code="DOCUMENTATION"
    )

    suspended = validate_success(
        api.suspend_placement(
            ctx["placement_id"], {"suspension_reason": "OPERATIONAL"}, fixtures.COORD
        )
    )
    resumed = validate_success(api.resume_placement(ctx["placement_id"], fixtures.COORD))

    assert_placement_dimensions_independent(suspended, "SUSPENDED", "WATCH")
    assert_placement_dimensions_independent(resumed, "ACTIVE", "WATCH")
    assert resumed["suspension_reason"] is None


def test_suspending_an_active_assignment_releases_its_seat(api):
    """PRD §3.6: "A coordinator or nurse may pause a live assignment, moving it `ACTIVE → SUSPENDED` and supplying a `suspension_reason` of `RESTRICTION_CONFLICT`, `MEDICAL_HOLD` or `OPERATIONAL`. Suspension lowers the job's `filled_seats` by 1, recomputes the claim's `cumulative_transitional_days` and `rtw_posture`, and raises the placement's `version` by 1."

    Design: Corner/state_machines/placement_suspend_syncs_job_seat_ledger
    """
    ctx = fixtures.setup_active_placement()
    before = validate_success(api.get_transitional_job(ctx["job_id"], fixtures.COORD))
    assert_seat_ledger(before, 1)

    data = validate_success(
        api.suspend_placement(
            ctx["placement_id"], {"suspension_reason": "MEDICAL_HOLD"}, fixtures.COORD
        )
    )

    assert data["placement_status"] == "SUSPENDED"
    assert data["suspension_reason"] == "MEDICAL_HOLD"
    after = validate_success(api.get_transitional_job(ctx["job_id"], fixtures.COORD))
    assert_seat_ledger(after, 0)
    assert data["restriction_set_id"] == ctx["restriction_set_id"], (
        "the placement keeps its restriction pointer while paused"
    )


def test_filled_seats_tracks_the_status_predicate_across_suspend_and_resume(api):
    """PRD §3.3: "thereafter `filled_seats` counts the placements on that job whose `placement_status` is `ADJUSTER_PENDING`, `ACTIVE` or `PROGRESSION_HOLD`, and is recomputed before any read of the job."
    PRD §3.6: "Resuming clears `suspension_reason`, raises the job's `filled_seats` by 1, and raises the placement's `version` by 1."

    Design: Corner/cross_cutting_layers/filled_seats_is_recomputed_after_suspend_and_resume
    """
    ctx = fixtures.setup_active_placement()

    validate_success(
        api.suspend_placement(
            ctx["placement_id"], {"suspension_reason": "OPERATIONAL"}, fixtures.COORD
        )
    )
    paused_job = validate_success(api.get_transitional_job(ctx["job_id"], fixtures.COORD))
    resumed = validate_success(api.resume_placement(ctx["placement_id"], fixtures.COORD))
    retaken_job = validate_success(api.get_transitional_job(ctx["job_id"], fixtures.COORD))

    assert_seat_ledger(paused_job, 0)
    assert resumed["placement_status"] == "ACTIVE"
    assert resumed["suspension_reason"] is None
    assert_seat_ledger(retaken_job, 1)


def test_completing_the_same_assignment_twice_is_refused(api):
    """PRD §3.6: "A coordinator closes a successful assignment, moving it `ACTIVE → COMPLETED`. Closure sets `ended_on` to the logical clock's calendar date, lowers the job's `filled_seats` by 1, moves every live directive of the placement to `SUPERSEDED`, recomputes `benefit_continuation_status` to `LAPSED`, recomputes the claim's `cumulative_transitional_days` and `rtw_posture`, and raises the placement's `version` by 1."
    PRD §3.6: "All three of `COMPLETED`, `TERMINATED_EARLY` and `DECLINED` are terminal: any further lifecycle request against such a placement answers `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/placement_complete_twice_second_call_returns_already_terminal
    """
    ctx = fixtures.setup_active_placement()
    fixtures.set_clock("2026-08-10T00:00:00Z")

    first = validate_success(api.complete_placement(ctx["placement_id"], fixtures.COORD))
    second = api.complete_placement(ctx["placement_id"], fixtures.COORD)

    assert first["placement_status"] == "COMPLETED"
    assert first["ended_on"] == "2026-08-10"
    assert first["benefit_continuation_status"] == "LAPSED"
    validate_error(second, ApiErrorId.ERR_ALREADY_TERMINAL, 409)
    job = validate_success(api.get_transitional_job(ctx["job_id"], fixtures.COORD))
    assert_seat_ledger(job, 0)


def test_terminating_a_live_assignment_lands_on_terminated_early(api):
    """PRD §3.6: "When the placement is `ACTIVE`, `PROGRESSION_HOLD` or `SUSPENDED`, it lands on `TERMINATED_EARLY` — that is, `ACTIVE → TERMINATED_EARLY`, `PROGRESSION_HOLD → TERMINATED_EARLY` or `SUSPENDED → TERMINATED_EARLY`: `ended_on` is set to the clock's calendar date, the job's `filled_seats` is lowered by 1 when the placement was holding a seat — that is, when it was `ADJUSTER_PENDING`, `ACTIVE` or `PROGRESSION_HOLD` — every live directive moves to `SUPERSEDED`, `benefit_continuation_status` becomes `LAPSED`, the claim's `cumulative_transitional_days` and `rtw_posture` are recomputed, and `version` rises by 1."

    Design: Corner/state_machines/terminate_branches_to_terminated_early_from_active
    """
    ctx = fixtures.setup_active_placement()
    fixtures.set_clock("2026-08-10T00:00:00Z")

    data = validate_success(
        api.terminate_placement(
            ctx["placement_id"], {"reason": "Worker medically withdrawn"}, fixtures.COORD
        )
    )

    assert data["placement_status"] == "TERMINATED_EARLY"
    assert data["placement_status"] != "DECLINED", "the from-state decides the branch"
    assert data["ended_on"] == "2026-08-10"
    assert data["benefit_continuation_status"] == "LAPSED"
    directives, _ = validate_paginated(
        api.list_placement_directives(ctx["placement_id"], fixtures.COORD)
    )
    assert directives[0]["directive_status"] == "SUPERSEDED"
    job = validate_success(api.get_transitional_job(ctx["job_id"], fixtures.COORD))
    assert_seat_ledger(job, 0)


def test_the_claim_posture_flips_to_restricted_at_exactly_ninety_days(api):
    """PRD §3.6: "The placement's `cumulative_days` is zero when `activated_on` is null or the effective through-date is undefined; otherwise it is the number of days from `activated_on` to the earlier of the effective through-date and the placement's `end_date`, counting both endpoints inclusively — that is, the day count plus one — and floored at zero."
    PRD §3.1: "or when the claim's `cumulative_transitional_days` has reached 90 days or more"

    Design: Corner/calculations/claim_posture_flips_to_restricted_at_exactly_ninety_cumulative_days
    """
    ctx = fixtures.setup_active_placement(placement_overrides={"end_date": "2026-11-30"})

    fixtures.set_clock("2026-10-30T00:00:00Z")
    at_89 = validate_success(api.get_claim(ctx["claim_id"], fixtures.COORD))
    fixtures.set_clock("2026-10-31T00:00:00Z")
    at_90 = validate_success(api.get_claim(ctx["claim_id"], fixtures.COORD))

    assert at_89["cumulative_transitional_days"] == 89
    assert at_89["rtw_posture"] == "OPEN"
    assert at_90["cumulative_transitional_days"] == 90
    assert at_90["rtw_posture"] == "RESTRICTED", "the soft-cap term reads 90 days or more"


def test_an_extension_projecting_eighty_nine_days_is_admitted(api):
    """PRD §3.6: "The projected cumulative duration is worked out as the claim's current `cumulative_transitional_days`, minus this placement's present `cumulative_days`, plus the inclusive day count from this placement's `start_date` through the proposed `new_end_date` floored at zero."
    PRD §3.6: "At priority 37, the projection must stay strictly below the soft cap of 90 days **unless** the placement has a case-review panel sitting in `DECIDED_CONTINUE`; failing both answers `ERR_DURATION_SOFT_CAP_REQUIRES_CASE_REVIEW` with HTTP 409."

    Design: Difficulty/boundary_precision_check/duration_soft_cap_admits_89_days_and_blocks_exactly_90
    """
    ctx = fixtures.setup_active_placement()

    data = validate_success(
        api.extend_placement(
            ctx["placement_id"],
            {"new_end_date": "2026-10-30", "reason": "Taper continues"},
            fixtures.COORD,
        )
    )

    assert data["end_date"] == "2026-10-30", (
        "2026-08-03 through 2026-10-30 inclusive projects exactly 89 days"
    )


def test_an_extension_projecting_exactly_ninety_days_is_refused(api):
    """PRD §3.6: "At priority 37, the projection must stay strictly below the soft cap of 90 days **unless** the placement has a case-review panel sitting in `DECIDED_CONTINUE`; failing both answers `ERR_DURATION_SOFT_CAP_REQUIRES_CASE_REVIEW` with HTTP 409."
    PRD §3.6: "A successful extension writes the new `end_date`, recomputes `cumulative_days`, the claim's `cumulative_transitional_days` and `rtw_posture`, and raises the placement's `version` by 1."

    Design: Difficulty/boundary_precision_check/duration_soft_cap_admits_89_days_and_blocks_exactly_90
    """
    ctx = fixtures.setup_active_placement()
    fixtures.get_success_data(
        api.extend_placement(
            ctx["placement_id"],
            {"new_end_date": "2026-10-30", "reason": "Taper continues"},
            fixtures.COORD,
        )
    )

    resp = api.extend_placement(
        ctx["placement_id"],
        {"new_end_date": "2026-10-31", "reason": "One more day"},
        fixtures.COORD,
    )

    validate_error(resp, ApiErrorId.ERR_DURATION_SOFT_CAP_REQUIRES_CASE_REVIEW, 409)
    placement = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))
    assert placement["end_date"] == "2026-10-30", "the refused extension writes nothing"


def test_an_extension_reaching_the_hard_cap_is_refused(api):
    """PRD §3.6: "At priority 36, the projection must stay strictly below the hard cap of 180 days; reaching 180 or beyond answers `ERR_DURATION_HARD_CAP` with HTTP 422 and there is no override."

    Design: Corner/validations/extend_past_the_hard_cap_is_rejected
    """
    ctx = fixtures.setup_active_placement(
        restriction_overrides={"valid_through": "2027-06-30"}
    )

    resp = api.extend_placement(
        ctx["placement_id"],
        {"new_end_date": "2027-02-15", "reason": "Long taper"},
        fixtures.COORD,
    )

    validate_error(resp, ApiErrorId.ERR_DURATION_HARD_CAP, 422)
    placement = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))
    assert placement["end_date"] == "2026-08-28"


def test_the_restriction_window_rejection_outranks_the_duration_hard_cap(api):
    """PRD §3.4: "At priority 25, the placement window must sit entirely inside the restriction window: `start_date` must be on or after the set's `effective_from` and `end_date` must be on or before the set's `valid_through`, or the request answers `ERR_PLACEMENT_OUTSIDE_RESTRICTION_WINDOW` with HTTP 422; this rule also guards extension."
    PRD §3.6: "At priority 36, the projection must stay strictly below the hard cap of 180 days; reaching 180 or beyond answers `ERR_DURATION_HARD_CAP` with HTTP 422 and there is no override."
    PRD §2.6: "Because a single request can violate several rules at once, the order in which checks run is normative: an implementation that reports a *different but also true* failure is wrong."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_restriction_window_wins_over_duration_hard_cap
    """
    ctx = fixtures.setup_active_placement()

    resp = api.extend_placement(
        ctx["placement_id"],
        {"new_end_date": "2027-02-15", "reason": "Provider expects a long taper"},
        fixtures.COORD,
    )

    validate_error(resp, ApiErrorId.ERR_PLACEMENT_OUTSIDE_RESTRICTION_WINDOW, 422)


def test_the_doubly_illegal_extension_writes_nothing(api):
    """PRD §3.6: "Extension is also re-screened against the hard restriction limits of priority 19, the restriction-window containment of priority 25, the worker-level overlap rule of priority 26, the claim's posture at priority 15, and the directive ceiling of priority 40."
    PRD §3.6: "A successful extension writes the new `end_date`, recomputes `cumulative_days`, the claim's `cumulative_transitional_days` and `rtw_posture`, and raises the placement's `version` by 1."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_restriction_window_wins_over_duration_hard_cap
    """
    ctx = fixtures.setup_active_placement()

    api.extend_placement(
        ctx["placement_id"],
        {"new_end_date": "2027-02-15", "reason": "Provider expects a long taper"},
        fixtures.COORD,
    )

    placement = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))
    assert placement["end_date"] == "2026-08-28", (
        "the extension that left the 2026-11-30 restriction window and projected 197 "
        "cumulative days changed nothing"
    )
    assert placement["placement_status"] == "ACTIVE"
