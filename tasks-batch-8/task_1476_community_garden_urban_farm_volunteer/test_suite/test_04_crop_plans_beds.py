"""Crop-plan approval gates (capacity, occupancy buffer, rotation, bed state),
the reject/resubmit cycle, and the bed rest period (PRD §3.4, §3.3)."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    assert_bed,
    assert_crop_plan,
    create_crop_plan_payload,
    make_admin_headers,
    make_bed,
    make_coordinator_headers,
    make_season,
    make_volunteer,
    make_volunteer_headers,
    setup_season_harvesting,
    setup_season_open,
    validate_error,
    validate_success,
)


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_crop_plan_reject_resubmit_approve_cycle(api):
    """PRD §3.4: "A `GardenAdmin` or `Coordinator` rejects a `PROPOSED` plan with
    a non-empty `rejection_reason` (an empty reason fails with
    `ERR_INVALID_REQUEST`), which is recorded on the plan. A `REJECTED` plan may
    be resubmitted to `PROPOSED` by staff or by the proposing volunteer (ownership
    applies, otherwise `ERR_OWNERSHIP_VIOLATION`); resubmission clears
    `rejection_reason` to null and may apply updated `requested_sq_ft`,
    `planned_start_date`, `planned_end_date`, `crop_type`, or `plant_family`
    supplied with the request."
    PRD §3.4: "Approving writes the allocation: the bed's `allocated_sq_ft` rises
    by the plan's `requested_sq_ft`".

    Design: Difficulty/non_linear_state_machine/crop_plan_reject_resubmit_cycle
    """
    admin = make_admin_headers()
    coordinator = make_volunteer()
    coordinator_headers = make_coordinator_headers(coordinator["id"])
    season, bed = setup_season_open()
    proposer = make_volunteer()
    plan = validate_success(
        api.create_crop_plan(
            create_crop_plan_payload(
                season_id=season["id"],
                bed_id=bed["id"],
                proposer_volunteer_id=proposer["id"],
                requested_sq_ft=60,
            ),
            make_volunteer_headers(proposer["id"]),
        ),
        expected_status=201,
    )
    assert plan["status"] == "PROPOSED"

    rejected = validate_success(
        api.transition_crop_plan(
            plan["id"],
            {"to_state": "REJECTED", "rejection_reason": "bed too sunny for this crop"},
            coordinator_headers,
        )
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "bed too sunny for this crop"
    bed_now = validate_success(api.get_bed(bed["id"], admin))
    assert bed_now["allocated_sq_ft"] == 0, "rejection carries no allocation side effect"

    resubmitted = validate_success(
        api.transition_crop_plan(
            plan["id"],
            {"to_state": "PROPOSED", "requested_sq_ft": 50},
            make_volunteer_headers(proposer["id"]),
        )
    )
    assert resubmitted["status"] == "PROPOSED"
    assert resubmitted["rejection_reason"] is None, "resubmission clears the reason"
    assert resubmitted["requested_sq_ft"] == 50, "updated fields apply on resubmit"

    approved = validate_success(
        api.transition_crop_plan(plan["id"], {"to_state": "APPROVED"}, coordinator_headers)
    )
    assert approved["status"] == "APPROVED"
    bed_now = validate_success(api.get_bed(bed["id"], admin))
    assert bed_now["allocated_sq_ft"] == 50, "only the resubmitted size is debited"


def test_crop_plan_approve_blocked_by_bed_state(api):
    """PRD §3.4: "the bed is in `FALLOW` or `RESERVED` (otherwise
    `ERR_BED_NOT_AVAILABLE`)".

    Design: Difficulty/cross_entity_state_dependency/crop_plan_approve_blocked_by_bed_state
    """
    admin = make_admin_headers()
    season, bed = setup_season_open()
    proposer = make_volunteer()
    # Bed FALLOW -> RESERVED (a season sits in OPEN_ENROLLMENT).
    validate_success(api.transition_bed(bed["id"], {"to_state": "RESERVED"}, admin))
    plan_a = validate_success(
        api.create_crop_plan(
            create_crop_plan_payload(
                season_id=season["id"],
                bed_id=bed["id"],
                proposer_volunteer_id=proposer["id"],
                requested_sq_ft=10,
            ),
            admin,
        ),
        expected_status=201,
    )
    validate_success(api.transition_crop_plan(plan_a["id"], {"to_state": "APPROVED"}, admin))
    validate_success(api.transition_bed(bed["id"], {"to_state": "PLANTED"}, admin))

    plan_b = validate_success(
        api.create_crop_plan(
            create_crop_plan_payload(
                season_id=season["id"],
                bed_id=bed["id"],
                proposer_volunteer_id=proposer["id"],
                crop_type="Beans",
                plant_family="Fabaceae",
                requested_sq_ft=10,
                planned_start_date="2026-10-01",
                planned_end_date="2026-10-15",
            ),
            admin,
        ),
        expected_status=201,
    )
    err = validate_error(
        api.transition_crop_plan(plan_b["id"], {"to_state": "APPROVED"}, admin),
        ApiErrorId.ERR_BED_NOT_AVAILABLE,
    )
    assert err["error_id"] == "ERR_BED_NOT_AVAILABLE", (
        "bed PLANTED is outside {FALLOW, RESERVED} even though capacity, rotation, "
        "and window all pass"
    )


def test_bed_area_exact_fit_allowed_one_over_rejected(api):
    """PRD §3.4: "the area fits — the bed's `allocated_sq_ft`, being the sum of
    `requested_sq_ft` over the bed's plans in `APPROVED`, `PLANTED`, or
    `HARVESTING`, plus the candidate's `requested_sq_ft`, must not exceed the
    bed's `size_sq_ft`, with an exact fit allowed and one square foot over failing
    with `ERR_BED_CAPACITY_EXCEEDED`".

    Design: Difficulty/boundary_precision_check/bed_area_exact_fit_allowed_one_over_rejected
    """
    admin = make_admin_headers()
    season, bed = setup_season_open()
    proposer = make_volunteer()

    def propose(sq_ft, family, crop, start, end):
        return validate_success(
            api.create_crop_plan(
                create_crop_plan_payload(
                    season_id=season["id"],
                    bed_id=bed["id"],
                    proposer_volunteer_id=proposer["id"],
                    crop_type=crop,
                    plant_family=family,
                    requested_sq_ft=sq_ft,
                    planned_start_date=start,
                    planned_end_date=end,
                ),
                admin,
            ),
            expected_status=201,
        )

    plan_a = propose(60, "Solanaceae", "Tomato", "2026-08-01", "2026-09-01")
    validate_success(api.transition_crop_plan(plan_a["id"], {"to_state": "APPROVED"}, admin))
    plan_b = propose(40, "Fabaceae", "Beans", "2026-09-20", "2026-10-01")
    plan_c = propose(1, "Brassicaceae", "Kale", "2026-10-16", "2026-10-26")

    approved_b = validate_success(
        api.transition_crop_plan(plan_b["id"], {"to_state": "APPROVED"}, admin)
    )
    assert approved_b["status"] == "APPROVED", "60 + 40 == 100: exact fit allowed"
    bed_now = validate_success(api.get_bed(bed["id"], admin))
    assert bed_now["allocated_sq_ft"] == 100

    err = validate_error(
        api.transition_crop_plan(plan_c["id"], {"to_state": "APPROVED"}, admin),
        ApiErrorId.ERR_BED_CAPACITY_EXCEEDED,
    )
    assert err["error_id"] == "ERR_BED_CAPACITY_EXCEEDED", "100 + 1 > 100 fails"


def test_bed_occupancy_requires_fourteen_day_buffer(api):
    """PRD §3.4: "the occupancy windows clear — two plans on the same bed, both in
    `APPROVED`, `PLANTED`, or `HARVESTING`, conflict unless one plan's
    `planned_end_date` plus a mandatory 14-day cover-crop buffer falls strictly
    before the other's `planned_start_date`, in either order, and adjacency is
    forbidden so a plan starting exactly fourteen days after another's end still
    conflicts, failing with `ERR_BED_OCCUPANCY_OVERLAP`".

    Design: Difficulty/resource_temporal_overlap/bed_occupancy_requires_fourteen_day_buffer
    """
    admin = make_admin_headers()
    season, bed = setup_season_open(bed=make_bed(size_sq_ft=200))
    proposer = make_volunteer()

    def propose(family, crop, start, end):
        return validate_success(
            api.create_crop_plan(
                create_crop_plan_payload(
                    season_id=season["id"],
                    bed_id=bed["id"],
                    proposer_volunteer_id=proposer["id"],
                    crop_type=crop,
                    plant_family=family,
                    requested_sq_ft=10,
                    planned_start_date=start,
                    planned_end_date=end,
                ),
                admin,
            ),
            expected_status=201,
        )

    plan_a = propose("Solanaceae", "Tomato", "2026-08-01", "2026-09-01")
    validate_success(api.transition_crop_plan(plan_a["id"], {"to_state": "APPROVED"}, admin))
    plan_b = propose("Fabaceae", "Beans", "2026-09-16", "2026-10-01")
    plan_c = propose("Brassicaceae", "Kale", "2026-09-15", "2026-09-20")
    plan_d = propose("Cucurbitaceae", "Squash", "2026-07-01", "2026-07-17")

    approved_b = validate_success(
        api.transition_crop_plan(plan_b["id"], {"to_state": "APPROVED"}, admin)
    )
    assert approved_b["status"] == "APPROVED", "A.end 09-01 + 14d = 09-15 < 09-16"

    err = validate_error(
        api.transition_crop_plan(plan_c["id"], {"to_state": "APPROVED"}, admin),
        ApiErrorId.ERR_BED_OCCUPANCY_OVERLAP,
    )
    assert err["error_id"] == "ERR_BED_OCCUPANCY_OVERLAP", (
        "starting exactly on A.end + 14d (09-15) still conflicts: strict <"
    )

    approved_d = validate_success(
        api.transition_crop_plan(plan_d["id"], {"to_state": "APPROVED"}, admin)
    )
    assert approved_d["status"] == "APPROVED", (
        "D.end 07-17 + 14d = 07-31 < A.start 08-01: before-side buffer satisfied"
    )


def test_bed_rest_period_enforced_after_harvest_close(api):
    """PRD §3.4: "`HARVEST_OPEN → POST_HARVEST` requires zero crop plans on the
    bed in `APPROVED`, `PLANTED`, or `HARVESTING`, otherwise
    `ERR_CROP_PLANS_UNRESOLVED`; the transition stamps `last_harvest_closed_at`
    with the current logical clock."
    PRD §3.4: "`POST_HARVEST → FALLOW` enforces the cover-crop rest: the clock
    must have reached `last_harvest_closed_at` plus 14 days, otherwise
    `ERR_BED_REST_PERIOD_ACTIVE`."

    Design: Corner/state_machines/bed_rest_period_enforced_after_harvest_close
    """
    admin = make_admin_headers()
    ctx = setup_season_harvesting()
    bed, plan = ctx["bed"], ctx["plan"]
    validate_success(api.set_clock({"to_iso8601": "2026-09-15T12:00:00Z"}, admin))

    err = validate_error(
        api.transition_bed(bed["id"], {"to_state": "POST_HARVEST"}, admin),
        ApiErrorId.ERR_CROP_PLANS_UNRESOLVED,
    )
    assert err["error_id"] == "ERR_CROP_PLANS_UNRESOLVED", "plan still HARVESTING"

    completed = validate_success(
        api.transition_crop_plan(plan["id"], {"to_state": "COMPLETE"}, admin)
    )
    assert completed["status"] == "COMPLETE"

    closed = validate_success(
        api.transition_bed(bed["id"], {"to_state": "POST_HARVEST"}, admin)
    )
    assert closed["status"] == "POST_HARVEST"
    assert_bed(closed)
    assert _parse_iso(closed["last_harvest_closed_at"]) == _parse_iso(
        "2026-09-15T12:00:00Z"
    ), "stamped with the current logical clock"

    err = validate_error(
        api.transition_bed(bed["id"], {"to_state": "FALLOW"}, admin),
        ApiErrorId.ERR_BED_REST_PERIOD_ACTIVE,
    )
    assert err["error_id"] == "ERR_BED_REST_PERIOD_ACTIVE", "same instant"

    validate_success(api.set_clock({"to_iso8601": "2026-09-28T12:00:00Z"}, admin))
    err = validate_error(
        api.transition_bed(bed["id"], {"to_state": "FALLOW"}, admin),
        ApiErrorId.ERR_BED_REST_PERIOD_ACTIVE,
    )
    assert err["error_id"] == "ERR_BED_REST_PERIOD_ACTIVE", "13 days < 14"

    validate_success(api.set_clock({"to_iso8601": "2026-09-30T12:00:00Z"}, admin))
    fallow = validate_success(api.transition_bed(bed["id"], {"to_state": "FALLOW"}, admin))
    assert fallow["status"] == "FALLOW", "at +15 days the rest period has passed"
    assert fallow["last_plant_family"] == "Solanaceae", (
        "rotation anchor written when the plan completed"
    )


def test_crop_rotation_violation_after_cycle_and_new_season(api):
    """PRD §3.4: "The rotation anchor, `last_plant_family`, is the `plant_family`
    of the most recent crop plan on the bed to reach `COMPLETE`, and it is null
    until the first plan completes".
    PRD §3.4: "the rotation check passes — the candidate's `plant_family` must
    differ from the bed's `last_plant_family`, otherwise
    `ERR_CROP_ROTATION_VIOLATION`".

    Design: Corner/state_machines/crop_rotation_violation_after_cycle_and_new_season
    """
    admin = make_admin_headers()
    ctx = setup_season_harvesting()
    season1, bed, plan_a, proposer = (
        ctx["season"],
        ctx["bed"],
        ctx["plan"],
        ctx["proposer"],
    )

    # Finish season 1: complete the plan, rest the bed, reconcile, close.
    validate_success(api.transition_crop_plan(plan_a["id"], {"to_state": "COMPLETE"}, admin))
    validate_success(api.transition_bed(bed["id"], {"to_state": "POST_HARVEST"}, admin))
    validate_success(api.set_clock({"to_iso8601": "2026-10-20T00:00:00Z"}, admin))
    fallow = validate_success(api.transition_bed(bed["id"], {"to_state": "FALLOW"}, admin))
    assert fallow["status"] == "FALLOW"
    validate_success(
        api.transition_season(season1["id"], {"to_state": "RECONCILIATION"}, admin)
    )
    closed = validate_success(
        api.transition_season(season1["id"], {"to_state": "CLOSED"}, admin)
    )
    assert closed["status"] == "CLOSED"

    # A new season on the same bed: the rotation anchor persists.
    season2 = make_season(
        name="2027 Spring",
        signup_opens_at="2027-01-01T00:00:00Z",
        signup_closes_at="2027-02-01T00:00:00Z",
        season_starts_at="2027-02-15T00:00:00Z",
        season_ends_at="2027-06-30T00:00:00Z",
        water_budget_gallons=800,
    )
    validate_success(
        api.transition_season(season2["id"], {"to_state": "OPEN_ENROLLMENT"}, admin)
    )

    def propose_season2(family, crop):
        return validate_success(
            api.create_crop_plan(
                create_crop_plan_payload(
                    season_id=season2["id"],
                    bed_id=bed["id"],
                    proposer_volunteer_id=proposer["id"],
                    crop_type=crop,
                    plant_family=family,
                    requested_sq_ft=40,
                    planned_start_date="2027-03-01",
                    planned_end_date="2027-04-01",
                ),
                admin,
            ),
            expected_status=201,
        )

    plan_b = propose_season2("Solanaceae", "Pepper")
    plan_c = propose_season2("Fabaceae", "Beans")

    err = validate_error(
        api.transition_crop_plan(plan_b["id"], {"to_state": "APPROVED"}, admin),
        ApiErrorId.ERR_CROP_ROTATION_VIOLATION,
    )
    assert err["error_id"] == "ERR_CROP_ROTATION_VIOLATION", (
        "Solanaceae matches the bed's rotation anchor from season 1"
    )

    approved_c = validate_success(
        api.transition_crop_plan(plan_c["id"], {"to_state": "APPROVED"}, admin)
    )
    assert_crop_plan(approved_c)
    assert approved_c["status"] == "APPROVED", "Fabaceae rotates cleanly"


def test_crop_plan_bare_resubmit_then_approve(api):
    """PRD §3.4: "A `REJECTED` plan may be resubmitted to `PROPOSED` by staff or
    by the proposing volunteer (ownership applies, otherwise
    `ERR_OWNERSHIP_VIOLATION`); resubmission clears `rejection_reason` to null and
    may apply updated `requested_sq_ft`, `planned_start_date`, `planned_end_date`,
    `crop_type`, or `plant_family` supplied with the request."
    PRD §3.4: "Approving writes the allocation: the bed's `allocated_sq_ft` rises
    by the plan's `requested_sq_ft`".

    Design: Difficulty/non_linear_state_machine/crop_plan_reject_resubmit_cycle
    """
    admin = make_admin_headers()
    season, bed = setup_season_open()
    proposer = make_volunteer()
    plan = validate_success(
        api.create_crop_plan(
            create_crop_plan_payload(
                season_id=season["id"],
                bed_id=bed["id"],
                proposer_volunteer_id=proposer["id"],
                requested_sq_ft=60,
            ),
            admin,
        ),
        expected_status=201,
    )

    rejected = validate_success(
        api.transition_crop_plan(
            plan["id"],
            {"to_state": "REJECTED", "rejection_reason": "window too tight"},
            admin,
        )
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "window too tight"

    # A resubmission with no updated fields keeps the original shape.
    resubmitted = validate_success(
        api.transition_crop_plan(plan["id"], {"to_state": "PROPOSED"}, admin)
    )
    assert resubmitted["status"] == "PROPOSED"
    assert resubmitted["rejection_reason"] is None
    assert resubmitted["requested_sq_ft"] == 60, "no updates supplied: size unchanged"

    approved = validate_success(
        api.transition_crop_plan(plan["id"], {"to_state": "APPROVED"}, admin)
    )
    assert approved["status"] == "APPROVED"
    bed_now = validate_success(api.get_bed(bed["id"], admin))
    assert bed_now["allocated_sq_ft"] == 60


def test_crop_plan_blocked_on_out_of_service_bed(api):
    """PRD §3.4: "Creation is gated: the season must be in `OPEN_ENROLLMENT` or
    `PLANTING` (otherwise `ERR_SEASON_NOT_ACCEPTING`), the bed must not be
    `OUT_OF_SERVICE` (otherwise `ERR_BED_NOT_AVAILABLE`), and a `Volunteer` or
    `GroupLeader` caller may propose only as themselves — the
    `proposer_volunteer_id` must equal their identity, otherwise
    `ERR_OWNERSHIP_VIOLATION`."
    PRD §3.4: "From any state other than `OUT_OF_SERVICE`, a `GardenAdmin` may
    take the bed to `OUT_OF_SERVICE` (from `FALLOW`, `RESERVED`, `PLANTED`,
    `GROWING`, `HARVEST_OPEN`, or `POST_HARVEST`); the cascade moves crop plans on
    the bed in `PROPOSED` or `APPROVED` to `WITHDRAWN`, freeing their allocated
    area."

    Design: Difficulty/cross_entity_state_dependency/crop_plan_approve_blocked_by_bed_state
    """
    admin = make_admin_headers()
    season, bed = setup_season_open()
    proposer = make_volunteer()
    plan = validate_success(
        api.create_crop_plan(
            create_crop_plan_payload(
                season_id=season["id"],
                bed_id=bed["id"],
                proposer_volunteer_id=proposer["id"],
                requested_sq_ft=10,
            ),
            admin,
        ),
        expected_status=201,
    )

    oos = validate_success(
        api.transition_bed(bed["id"], {"to_state": "OUT_OF_SERVICE"}, admin)
    )
    assert oos["status"] == "OUT_OF_SERVICE"
    plan_now = validate_success(api.get_crop_plan(plan["id"], admin))
    assert plan_now["status"] == "WITHDRAWN", "the bed cascade withdraws proposed plans"

    err = validate_error(
        api.create_crop_plan(
            create_crop_plan_payload(
                season_id=season["id"],
                bed_id=bed["id"],
                proposer_volunteer_id=proposer["id"],
                requested_sq_ft=10,
            ),
            admin,
        ),
        ApiErrorId.ERR_BED_NOT_AVAILABLE,
    )
    assert err["error_id"] == "ERR_BED_NOT_AVAILABLE", (
        "an OUT_OF_SERVICE bed accepts no new plans"
    )


def test_bed_area_single_plan_exact_fit(api):
    """PRD §3.4: "the area fits — the bed's `allocated_sq_ft`, being the sum of
    `requested_sq_ft` over the bed's plans in `APPROVED`, `PLANTED`, or
    `HARVESTING`, plus the candidate's `requested_sq_ft`, must not exceed the
    bed's `size_sq_ft`, with an exact fit allowed and one square foot over failing
    with `ERR_BED_CAPACITY_EXCEEDED`".

    Design: Difficulty/boundary_precision_check/bed_area_exact_fit_allowed_one_over_rejected
    """
    admin = make_admin_headers()
    season, bed = setup_season_open()
    proposer = make_volunteer()
    plan_a = validate_success(
        api.create_crop_plan(
            create_crop_plan_payload(
                season_id=season["id"],
                bed_id=bed["id"],
                proposer_volunteer_id=proposer["id"],
                requested_sq_ft=100,
            ),
            admin,
        ),
        expected_status=201,
    )
    approved = validate_success(
        api.transition_crop_plan(plan_a["id"], {"to_state": "APPROVED"}, admin)
    )
    assert approved["status"] == "APPROVED", "a single plan may fill the bed exactly"
    bed_now = validate_success(api.get_bed(bed["id"], admin))
    assert bed_now["allocated_sq_ft"] == 100

    plan_b = validate_success(
        api.create_crop_plan(
            create_crop_plan_payload(
                season_id=season["id"],
                bed_id=bed["id"],
                proposer_volunteer_id=proposer["id"],
                crop_type="Beans",
                plant_family="Fabaceae",
                requested_sq_ft=1,
                planned_start_date="2026-10-16",
                planned_end_date="2026-10-26",
            ),
            admin,
        ),
        expected_status=201,
    )
    err = validate_error(
        api.transition_crop_plan(plan_b["id"], {"to_state": "APPROVED"}, admin),
        ApiErrorId.ERR_BED_CAPACITY_EXCEEDED,
    )
    assert err["error_id"] == "ERR_BED_CAPACITY_EXCEEDED", "one square foot over fails"


def test_bed_occupancy_reverse_and_enclosing_conflicts(api):
    """PRD §3.4: "the occupancy windows clear — two plans on the same bed, both in
    `APPROVED`, `PLANTED`, or `HARVESTING`, conflict unless one plan's
    `planned_end_date` plus a mandatory 14-day cover-crop buffer falls strictly
    before the other's `planned_start_date`, in either order, and adjacency is
    forbidden so a plan starting exactly fourteen days after another's end still
    conflicts, failing with `ERR_BED_OCCUPANCY_OVERLAP`".

    Design: Difficulty/resource_temporal_overlap/bed_occupancy_requires_fourteen_day_buffer
    """
    admin = make_admin_headers()
    season, bed = setup_season_open(bed=make_bed(size_sq_ft=200))
    proposer = make_volunteer()

    def propose(family, crop, start, end):
        return validate_success(
            api.create_crop_plan(
                create_crop_plan_payload(
                    season_id=season["id"],
                    bed_id=bed["id"],
                    proposer_volunteer_id=proposer["id"],
                    crop_type=crop,
                    plant_family=family,
                    requested_sq_ft=10,
                    planned_start_date=start,
                    planned_end_date=end,
                ),
                admin,
            ),
            expected_status=201,
        )

    plan_a = propose("Solanaceae", "Tomato", "2026-08-01", "2026-09-01")
    validate_success(api.transition_crop_plan(plan_a["id"], {"to_state": "APPROVED"}, admin))

    # Enclosed entirely inside A's window: neither ordering separates them.
    plan_g = propose("Fabaceae", "Beans", "2026-08-15", "2026-08-20")
    err = validate_error(
        api.transition_crop_plan(plan_g["id"], {"to_state": "APPROVED"}, admin),
        ApiErrorId.ERR_BED_OCCUPANCY_OVERLAP,
    )
    assert err["error_id"] == "ERR_BED_OCCUPANCY_OVERLAP"

    # Before-side exact buffer edge: H.end 07-18 + 14d == A.start 08-01, and the
    # rule demands strictly-before, so this still conflicts.
    plan_h = propose("Brassicaceae", "Kale", "2026-07-04", "2026-07-18")
    err = validate_error(
        api.transition_crop_plan(plan_h["id"], {"to_state": "APPROVED"}, admin),
        ApiErrorId.ERR_BED_OCCUPANCY_OVERLAP,
    )
    assert err["error_id"] == "ERR_BED_OCCUPANCY_OVERLAP"
