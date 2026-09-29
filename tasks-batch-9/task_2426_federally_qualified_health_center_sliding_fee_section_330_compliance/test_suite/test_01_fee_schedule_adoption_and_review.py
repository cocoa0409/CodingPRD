"""Adopting a sliding fee schedule: period exclusivity, supersession, review clock."""

from test_helpers import (
    ApiErrorId,
    OFFICER,
    TWO_BAND_LADDER,
    adopt_fee_schedule_payload,
    advance_clock,
    annual_review_payload,
    api_client,
    make_board_chair_headers,
    refresh_fee_schedule,
    refresh_health_center,
    same_instant,
    seed_poverty_guidelines,
    setup_baseline_service,
    setup_baseline_site,
    setup_board_seat,
    setup_boot_fs,
    setup_draft_fee_schedule,
    setup_grantee,
    validate_error,
    validate_success,
)


def _adopt(fee_schedule_id, expected_version, chair_id):
    return api_client.adopt_fee_schedule(
        fee_schedule_id,
        adopt_fee_schedule_payload(expected_version),
        make_board_chair_headers(chair_id),
    )


def _three_candidate_drafts(ctx):
    """A later adjacent period, an overlapping inner period, and an equal start."""
    later = setup_draft_fee_schedule(
        ctx["health_center_id"],
        effective_start="2027-01-01T00:00:00Z",
        effective_end="2028-01-01T00:00:00Z",
        ladder=TWO_BAND_LADDER,
    )["fee_schedule"]
    inner = setup_draft_fee_schedule(
        ctx["health_center_id"],
        effective_start="2026-06-01T00:00:00Z",
        effective_end="2026-12-01T00:00:00Z",
        ladder=TWO_BAND_LADDER,
    )["fee_schedule"]
    same_start = setup_draft_fee_schedule(
        ctx["health_center_id"],
        effective_start="2026-01-01T00:00:00Z",
        effective_end="2027-01-01T00:00:00Z",
        ladder=TWO_BAND_LADDER,
    )["fee_schedule"]
    return later, inner, same_start


def test_adjacent_period_is_adopted_and_an_equal_start_supersedes_the_incumbent():
    """Adjacency is permitted and an equal effective_start supersedes.

    PRD 3.3: "Any other overlap is rejected with `ERR_FEE_SCHEDULE_PERIOD_OVERLAP`,
    while adjacency — an existing schedule whose `effective_end` equals the new
    schedule's `effective_start` — is always permitted." PRD 3.3 also states: "Any
    adopted schedule of the same grantee sharing this schedule's `effective_start`
    moves `ADOPTED → SUPERSEDED` and has its `superseded_by_fee_schedule_id`
    pointed at the newly adopted schedule."

    Design: Difficulty/resource_temporal_overlap/fee_schedule_periods_half_open_overlap_adjacency_and_equal_start_supersede
    """
    ctx = setup_boot_fs()
    incumbent_id = ctx["fee_schedule_id"]
    later, _inner, same_start = _three_candidate_drafts(ctx)

    version_before_later = refresh_health_center(
        ctx["health_center_id"], ctx["chair_headers"]
    )["version"]
    adopted_later = validate_success(
        _adopt(later["id"], version_before_later, ctx["chair_id"])
    )
    assert adopted_later["status"] == "ADOPTED", (
        "an adjacent period whose effective_start equals the incumbent's "
        f"effective_end is always permitted, got {adopted_later['status']}"
    )

    version_before_same_start = refresh_health_center(
        ctx["health_center_id"], ctx["chair_headers"]
    )["version"]
    assert version_before_same_start == version_before_later + 1, (
        "a successful adoption increments the grantee's version by one, so the "
        f"next observed version must be {version_before_later + 1}"
    )

    adopted_same_start = validate_success(
        _adopt(same_start["id"], version_before_same_start, ctx["chair_id"])
    )
    assert adopted_same_start["status"] == "ADOPTED"
    assert adopted_same_start["superseded_by_fee_schedule_id"] is None, (
        "the newly adopted schedule is not itself superseded"
    )

    incumbent = refresh_fee_schedule(incumbent_id)
    assert incumbent["status"] == "SUPERSEDED", (
        "the schedule sharing the new schedule's effective_start moves "
        f"ADOPTED to SUPERSEDED, got {incumbent['status']}"
    )
    assert incumbent["superseded_by_fee_schedule_id"] == same_start["id"], (
        "superseded_by_fee_schedule_id points at the newly adopted schedule"
    )


def test_overlapping_inner_period_is_rejected_and_stays_draft():
    """A period that overlaps without sharing a start is a conflict, not a supersession.

    PRD 3.3: "No other adopted schedule of the same grantee may overlap this one's
    half-open period — with one carefully chosen exception: if an existing adopted
    schedule has an `effective_start` exactly equal to this one's, it is
    *superseded* rather than treated as a conflict, which is how a board replaces
    a schedule it has already voted on."

    Design: Difficulty/resource_temporal_overlap/fee_schedule_periods_half_open_overlap_adjacency_and_equal_start_supersede
    """
    ctx = setup_boot_fs()
    _later, inner, _same_start = _three_candidate_drafts(ctx)

    observed_version = refresh_health_center(
        ctx["health_center_id"], ctx["chair_headers"]
    )["version"]
    validate_error(
        _adopt(inner["id"], observed_version, ctx["chair_id"]),
        ApiErrorId.ERR_FEE_SCHEDULE_PERIOD_OVERLAP.value,
    )

    rejected = refresh_fee_schedule(inner["id"])
    assert rejected["status"] == "DRAFT", (
        f"a rejected adoption leaves the schedule in DRAFT, got {rejected['status']}"
    )
    assert rejected["adopted_at"] is None
    assert (
        refresh_health_center(ctx["health_center_id"])["version"] == observed_version
    ), "a rejected adoption does not move the grantee's version"


def test_period_overlap_is_reported_ahead_of_a_nominal_fee_above_the_cap():
    """Rung 24 outranks rung 41 on a single adoption request.

    PRD 2.12: "When more than one rule would reject a request, the rule with the
    **lowest priority number wins** and its error is the one returned." Rung 24
    reads: "Fee-schedule period exclusivity holds, on fee-schedule adoption —
    otherwise `ERR_FEE_SCHEDULE_PERIOD_OVERLAP` (409)."

    Design: Difficulty/priority_pair_validation_conflict/fee_schedule_period_overlap_beats_nominal_fee_above_cap
    """
    ctx = setup_boot_fs()
    over_cap_and_overlapping = setup_draft_fee_schedule(
        ctx["health_center_id"],
        effective_start="2026-06-01T00:00:00Z",
        effective_end="2026-12-01T00:00:00Z",
        nominal_fee_cents=3000,
        ladder=TWO_BAND_LADDER,
    )["fee_schedule"]
    assert (
        over_cap_and_overlapping["nominal_fee_cents"]
        > ctx["health_center"]["nominal_fee_cap_cents"]
    ), "the draft must also breach the grantee's nominal fee cap"

    observed_version = refresh_health_center(
        ctx["health_center_id"], ctx["chair_headers"]
    )["version"]
    validate_error(
        _adopt(over_cap_and_overlapping["id"], observed_version, ctx["chair_id"]),
        ApiErrorId.ERR_FEE_SCHEDULE_PERIOD_OVERLAP.value,
    )


def test_nominal_fee_above_cap_and_overlap_leave_both_schedules_untouched():
    """The doubly-invalid adoption mutates neither schedule nor grantee version.

    PRD 3.3: "The schedule's `nominal_fee_cents` must not exceed the grantee's
    `nominal_fee_cap_cents`, or adoption is rejected with
    `ERR_NOMINAL_FEE_ABOVE_CAP`."

    Design: Difficulty/priority_pair_validation_conflict/fee_schedule_period_overlap_beats_nominal_fee_above_cap
    """
    ctx = setup_boot_fs()
    over_cap_and_overlapping = setup_draft_fee_schedule(
        ctx["health_center_id"],
        effective_start="2026-06-01T00:00:00Z",
        effective_end="2026-12-01T00:00:00Z",
        nominal_fee_cents=3000,
        ladder=TWO_BAND_LADDER,
    )["fee_schedule"]

    observed_version = refresh_health_center(
        ctx["health_center_id"], ctx["chair_headers"]
    )["version"]
    validate_error(
        _adopt(over_cap_and_overlapping["id"], observed_version, ctx["chair_id"]),
        ApiErrorId.ERR_FEE_SCHEDULE_PERIOD_OVERLAP.value,
    )

    assert refresh_fee_schedule(over_cap_and_overlapping["id"])["status"] == "DRAFT"
    incumbent = refresh_fee_schedule(ctx["fee_schedule_id"])
    assert incumbent["status"] == "ADOPTED", (
        "the incumbent is neither superseded nor otherwise disturbed"
    )
    assert incumbent["superseded_by_fee_schedule_id"] is None
    assert (
        refresh_health_center(ctx["health_center_id"])["version"] == observed_version
    )


def _grantee_with_two_year_schedule():
    """A grantee whose only adopted schedule runs [2026-01-01, 2028-01-01)."""
    seed_poverty_guidelines()
    advance_clock("2026-01-01T00:00:00Z")
    health_center = setup_grantee(
        legal_name="Calendar Creek Health", grant_number="H80CS00429"
    )
    setup_baseline_site(
        health_center["id"], site_name="Creek Clinic", address_line="3 Creek Ln"
    )
    setup_baseline_service(health_center["id"])
    chair = setup_board_seat(
        health_center["id"],
        expertise_category="COMMUNITY",
        term_start="2026-01-01T00:00:00Z",
        term_end="2029-12-31T00:00:00Z",
    )
    draft = setup_draft_fee_schedule(
        health_center["id"],
        fpg_year=2026,
        effective_start="2026-01-01T00:00:00Z",
        effective_end="2028-01-01T00:00:00Z",
        ladder=TWO_BAND_LADDER,
    )["fee_schedule"]
    observed = refresh_health_center(
        health_center["id"], make_board_chair_headers(chair["id"])
    )
    adopted = validate_success(_adopt(draft["id"], observed["version"], chair["id"]))
    return {"health_center": health_center, "chair": chair, "fee_schedule": adopted}


def test_adoption_is_the_first_annual_review_and_365_elapsed_days_still_reads_current():
    """The review clock starts at adoption and 365 whole days is not yet due.

    PRD 3.3: "A successful adoption moves the schedule `DRAFT → ADOPTED` and stamps
    `adopted_at` and `last_reviewed_at` with the logical clock, records the
    adopting chair's identifier in `adopted_by_user_id`, and sets
    `reviewed_against_guideline_year` to the schedule's own `fpg_year` — adoption
    *is* the first annual review." PRD 3.3 also fixes the boundary: "The day
    boundary is strict — 365 elapsed days is still `CURRENT`, and 366 is
    `REVIEW_DUE`."

    Design: Difficulty/boundary_precision_check/annual_review_elapsed_days_365_current_366_review_due
    """
    setup = _grantee_with_two_year_schedule()
    adopted = setup["fee_schedule"]
    assert adopted["status"] == "ADOPTED"
    assert same_instant(adopted["last_reviewed_at"]) == "2026-01-01T00:00:00Z", (
        "last_reviewed_at is stamped with the logical clock at adoption"
    )
    assert adopted["reviewed_against_guideline_year"] == 2026, (
        "adoption sets reviewed_against_guideline_year to the schedule's own fpg_year"
    )
    assert adopted["review_status"] == "CURRENT"

    advance_clock("2027-01-01T00:00:00Z")
    at_365_days = refresh_fee_schedule(adopted["id"])
    assert at_365_days["review_status"] == "CURRENT", (
        "365 elapsed days is still CURRENT, got "
        f"{at_365_days['review_status']}"
    )
    assert at_365_days["review_status"] != "OUT_OF_DATE", (
        "the schedule's fpg_year still equals the latest published guideline year"
    )


def test_366_elapsed_days_moves_the_schedule_to_review_due_on_a_plain_read():
    """One day past the boundary the same read reports REVIEW_DUE.

    PRD 3.3: "Otherwise, if elapsed days is greater than 365, `review_status` is
    `REVIEW_DUE`." PRD 3.3 adds that "This posture is recomputed on adoption, on
    annual review, during the compliance sweep, and on every read of a schedule,
    so publishing a new guideline year is visible in a schedule's `review_status`
    without any write against the schedule itself."

    Design: Difficulty/boundary_precision_check/annual_review_elapsed_days_365_current_366_review_due
    """
    setup = _grantee_with_two_year_schedule()
    adopted = setup["fee_schedule"]

    advance_clock("2027-01-02T00:00:00Z")
    at_366_days = refresh_fee_schedule(adopted["id"])
    assert at_366_days["review_status"] == "REVIEW_DUE", (
        "366 elapsed days is REVIEW_DUE, got " f"{at_366_days['review_status']}"
    )
    assert at_366_days["reviewed_against_guideline_year"] == 2026
    assert at_366_days["status"] == "ADOPTED", (
        "the period still contains the clock, so the schedule has not expired"
    )

    reviewed = validate_success(
        api_client.annual_review_fee_schedule(
            adopted["id"],
            annual_review_payload(2026),
            OFFICER,
        )
    )
    assert same_instant(reviewed["last_reviewed_at"]) == "2027-01-02T00:00:00Z", (
        "the review stamps last_reviewed_at with the logical clock"
    )
    assert reviewed["review_status"] == "CURRENT", (
        "resetting the clock returns the schedule to CURRENT"
    )
