"""Endpoint contracts: live views, join arms, legacy onboarding and completion."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    ASSET_HEADERS,
    OFFICIAL_HEADERS,
    PERMIT_HEADERS,
    PLANNER_HEADERS,
    SCHEDULER_HEADERS,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_budget_partition,
    assert_capacity_fields,
    assert_cost_breakdown,
)
from test_helpers.factories import legacy_placement_payload, permit_decision_payload
from test_helpers.fixtures import (
    build_campus,
    build_request_context,
    certify_study,
    create_school,
    create_site,
    create_study,
    create_unit,
    submit_study,
)

CLOCK = "2027-03-01T00:00:00Z"
NORTHSIDE = {"name": "Northside Middle", "site_acreage": 10.0,
             "electrical_spare_capacity_kw": 40, "sewer_spare_connections": 1}


def test_taking_a_room_out_of_service_moves_the_live_view_but_not_the_frozen_study(api):
    """PRD §3.1: "A `DistrictAdmin` may later revise a room's `status` or its `area_sqft`;
    such a revision increments the room's `version`, and — importantly — never
    retroactively rewrites the capacity already frozen onto a submitted study. Only
    `IN_SERVICE` rooms count toward program capacity; a room in
    `OUT_OF_SERVICE_RENOVATION` or `DECOMMISSIONED` contributes nothing." PRD §3.2: the
    breakdown view "recomputes both variants live against the campus's current rooms and
    set-asides ... Because this view recomputes rather than reads, it will disagree with an
    already-submitted study whose figures were frozen before a room was renovated — and
    that disagreement is the intended signal." PRD §3.2 on the seat rule: "take the room's
    `area_sqft`, divide it by the policy's `min_area_sqft_per_seat`, take the quotient
    downward to a whole number, and then take the smaller of that figure and the policy's
    `max_class_size`".

    Design: Corner/endpoints/room_patch_changes_live_capacity_but_not_a_frozen_study
    """
    ctx = build_campus(api, clock=CLOCK, school_overrides=NORTHSIDE, budget_cents=None)
    room_one_id, room_two_id = ctx["room_ids"]

    study = create_study(api, ctx["school_id"], ctx["policy_id"])
    submit_study(api, study["id"])

    renovated = validate_success(
        api.patch_room(room_two_id, {"status": "OUT_OF_SERVICE_RENOVATION"},
                       ADMIN_HEADERS)
    )
    assert renovated["status"] == "OUT_OF_SERVICE_RENOVATION"
    assert renovated["area_sqft"] == 900
    assert renovated["version"] == 2

    breakdown = validate_success(
        api.get_capacity_breakdown(study["id"], PLANNER_HEADERS)
    )
    assert breakdown["program_capacity_seats"] == 28
    assert breakdown["utilization_pct"] == 214.3
    assert breakdown["seat_deficit"] == 34
    assert breakdown["required_portable_count"] == 2

    frozen = validate_success(api.get_capacity_study(study["id"], PLANNER_HEADERS))
    assert_capacity_fields(frozen, program_capacity_seats=56, utilization_pct=107.1,
                           seat_deficit=7, required_portable_count=1)

    resized = validate_success(
        api.patch_room(room_one_id, {"area_sqft": 750}, ADMIN_HEADERS)
    )
    assert resized["area_sqft"] == 750
    assert resized["version"] == 2

    after_resize = validate_success(
        api.get_capacity_breakdown(study["id"], PLANNER_HEADERS)
    )
    assert after_resize["program_capacity_seats"] == 25
    assert after_resize["utilization_pct"] == 240.0

    _, meta = validate_paginated(
        api.list_rooms(ADMIN_HEADERS, {"school_id": ctx["school_id"],
                                       "status": "OUT_OF_SERVICE_RENOVATION"})
    )
    assert meta["total_count"] == 1


def test_one_denied_permit_rejects_the_request_and_hands_the_unit_back(api):
    """PRD §3.7: "A decision of `DENIED` moves the permit `SUBMITTED → DENIED` and takes
    the request down the other join arm, whose side effects are wholly disjoint from the
    approval arm's. The request moves `PERMIT_PENDING → REJECTED` with `rejection_reason`
    recorded as `PERMIT_DENIED`; the reserved unit returns `RESERVED → IN_STORAGE`; no
    budget encumbrance is created at all; and the pad's `occupied_by_unit_id` remains
    null. Sibling permits of a denied request keep whatever status they already hold — they
    are not cancelled or rewritten — and no further decision on any of them is accepted,
    because the owning request is no longer `PERMIT_PENDING`." PRD §3.7 names that refusal:
    "a decision attempted while the request has moved on is rejected with
    `ERR_PERMIT_REQUEST_NOT_PENDING`." PRD §3.7 on the filing: "The required set is always
    `DSA_STRUCTURAL`, `FIRE_MARSHAL` and `ELECTRICAL`".

    Design: Corner/endpoints/permit_denial_rejects_the_request_and_releases_the_unit
    """
    ctx = build_request_context(
        api, stage="permit_pending", clock=CLOCK, school_overrides=NORTHSIDE,
        unit_overrides={"asset_tag": "PU-D101"},
    )

    denied = validate_success(
        api.decide_permit(ctx["permit_ids"]["DSA_STRUCTURAL"],
                          permit_decision_payload("DENIED"), OFFICIAL_HEADERS)
    )
    assert denied["status"] == "DENIED"
    assert denied["approved_on"] is None

    request = validate_success(api.get_placement_request(ctx["request_id"],
                                                        PLANNER_HEADERS))
    assert request["status"] == "REJECTED"
    assert request["encumbered_cost_cents"] == 0
    assert request["rejection_reason"] == "PERMIT_DENIED"

    unit = validate_success(api.get_portable_unit(ctx["unit_id"], ASSET_HEADERS))
    assert unit["allocation_status"] == "IN_STORAGE"
    assert unit["condition_status"] == "SERVICEABLE"
    assert unit["current_school_id"] is None

    assert validate_success(
        api.get_placement_site(ctx["site_id"], PLANNER_HEADERS)
    )["occupied_by_unit_id"] is None

    assert_budget_partition(
        validate_success(api.get_capital_budget(ctx["budget_id"], PLANNER_HEADERS)),
        authorized_cents=500_000_000, encumbered_cents=0, expended_cents=0,
        uncommitted_cents=500_000_000,
    )

    _, meta = validate_paginated(
        api.list_permits(PERMIT_HEADERS, {"placement_request_id": ctx["request_id"],
                                          "status": "SUBMITTED"})
    )
    assert meta["total_count"] == 2

    revival = api.decide_permit(ctx["permit_ids"]["FIRE_MARSHAL"],
                               permit_decision_payload("APPROVED"), OFFICIAL_HEADERS)
    validate_error(revival, ApiErrorId.PERMIT_REQUEST_NOT_PENDING, expected_status=409)


def test_a_campus_hosting_nothing_still_reports_and_still_counts_in_the_rollup(api):
    """PRD §3.9: "The campus's permanent seats are that study's `program_capacity_seats`,
    reported as `permanent_seats`, and its portable seats are its current
    `hosted_portable_seats`. `portable_seat_share_pct` is the hosted portable seats
    multiplied by 100, divided by the sum of the permanent seats and the hosted portable
    seats, rounded half up to one decimal place ... otherwise it is `NONE`. A narrative to
    the board is required exactly when the flag is `LONG_TERM_RELIANCE`, reported as
    `narrative_required`. The per-campus report returns the campus's `school_id` and
    `certified_study_id` alongside those figures and the campus's
    `consecutive_reliance_years`." "a campus with no certified study cannot be reported on
    and the request fails with `ERR_NO_CERTIFIED_STUDY`." "Qualifying campuses are those
    whose `certified_study_id` is not null, counted as `qualifying_school_count` ... Finally,
    `long_term_reliance_school_count` counts the qualifying campuses whose flag is
    `LONG_TERM_RELIANCE`".

    Design: Corner/endpoints/reliance_report_is_computed_live_from_the_latest_certified_study
    """
    ctx = build_campus(api, clock=CLOCK, school_overrides=NORTHSIDE, budget_cents=None)
    other = create_school(api, name="Eastvale Middle", site_acreage=10.0)

    study = create_study(api, ctx["school_id"], ctx["policy_id"])
    submit_study(api, study["id"])
    certify_study(api, study["id"])

    report = validate_success(
        api.get_reliance_report(ctx["school_id"], PLANNER_HEADERS)
    )
    assert report["school_id"] == ctx["school_id"]
    assert report["certified_study_id"] == study["id"]
    assert report["permanent_seats"] == 56
    assert report["hosted_portable_seats"] == 0
    assert report["portable_seat_share_pct"] == 0.0
    assert report["consecutive_reliance_years"] == 0
    assert report["reliance_flag"] == "NONE"
    assert report["narrative_required"] is False

    summary = validate_success(api.get_reliance_summary(PLANNER_HEADERS))
    assert summary["qualifying_school_count"] == 1
    assert summary["district_average_portable_share_pct"] == 0.0
    assert summary["long_term_reliance_school_count"] == 0

    validate_error(api.get_reliance_report(other["id"], PLANNER_HEADERS),
                   ApiErrorId.NO_CERTIFIED_STUDY, expected_status=409)


def test_recording_a_legacy_placement_links_unit_pad_and_campus_at_once(api):
    """PRD §3.9: "An `AssetManager` or `DistrictAdmin` records an existing placement by
    supplying the `school_id` of the hosting campus, the `placement_site_id` of the pad the
    unit stands on, and `installed_on`, the date the unit went in. The unit must be
    `IN_STORAGE`, its `condition_status` must not be `UNSAFE`, and the named pad must belong
    to the supplied campus and have a null `occupied_by_unit_id`; a pad belonging elsewhere
    is rejected with `ERR_SITE_SCHOOL_MISMATCH` and an occupied pad with
    `ERR_SITE_OCCUPIED`. On success the unit jumps `IN_STORAGE → INSTALLED`, its
    `current_school_id` is set, the pad's `occupied_by_unit_id` is set,
    `lifetime_relocation_count` is incremented by 1, the unit's `rated_seats` are added to
    the campus's `hosted_portable_seats`, and the campus's `reliance_flag` is recomputed."
    "The campus's `reliance_flag` is `LONG_TERM_RELIANCE` when that share reaches 15.0
    percent or more". PRD §3.1: a new unit "opens `accumulated_relocation_cost_cents` at
    0", and "a `SINGLE_24x40` seats 24".

    Design: Corner/endpoints/legacy_placement_links_unit_pad_and_campus_in_one_write
    """
    ctx = build_campus(api, clock=CLOCK, school_overrides=NORTHSIDE, budget_cents=None)
    other = create_school(api, name="Eastvale Middle", site_acreage=10.0)
    site = create_site(api, ctx["school_id"], pad_code="PAD-A")
    other_site = create_site(api, other["id"], pad_code="PAD-E")

    unit = create_unit(api, asset_tag="PU-L101", in_service_year=2016)
    spare = create_unit(api, asset_tag="PU-L102", in_service_year=2016)

    study = create_study(api, ctx["school_id"], ctx["policy_id"])
    submit_study(api, study["id"])
    certify_study(api, study["id"])

    placed = validate_success(
        api.record_existing_placement(
            unit["id"],
            legacy_placement_payload(ctx["school_id"], site["id"],
                                     installed_on="2024-08-01"),
            ASSET_HEADERS,
        )
    )
    assert placed["allocation_status"] == "INSTALLED"
    assert placed["current_school_id"] == ctx["school_id"]
    assert placed["lifetime_relocation_count"] == 1
    assert placed["accumulated_relocation_cost_cents"] == 0

    assert validate_success(
        api.get_placement_site(site["id"], PLANNER_HEADERS)
    )["occupied_by_unit_id"] == unit["id"]

    school = validate_success(api.get_school(ctx["school_id"], PLANNER_HEADERS))
    assert school["hosted_portable_seats"] == 24
    assert school["reliance_flag"] == "LONG_TERM_RELIANCE"

    report = validate_success(
        api.get_reliance_report(ctx["school_id"], PLANNER_HEADERS)
    )
    assert report["portable_seat_share_pct"] == 30.0
    assert report["narrative_required"] is True

    straddling = api.record_existing_placement(
        spare["id"],
        legacy_placement_payload(ctx["school_id"], other_site["id"],
                                 installed_on="2024-08-01"),
        ASSET_HEADERS,
    )
    validate_error(straddling, ApiErrorId.SITE_SCHOOL_MISMATCH, expected_status=422)

    taken = api.record_existing_placement(
        spare["id"],
        legacy_placement_payload(ctx["school_id"], site["id"],
                                 installed_on="2024-08-01"),
        ASSET_HEADERS,
    )
    validate_error(taken, ApiErrorId.SITE_OCCUPIED, expected_status=409)


def test_a_ramp_less_unit_cannot_close_its_window_and_nothing_downstream_moves(api):
    """PRD §3.8: "Completing the work moves the schedule `IN_PROGRESS → COMPLETED` and
    carries the accessibility and code-compliance gate for the relocated unit: the unit's
    `ada_ramp_installed` must be true and the pad's `ada_path_of_travel_compliant` must be
    true, and a failure here is reported as `ERR_ADA_NONCOMPLIANT`." PRD §2.6 rule 19: "The
    referenced unit's `ada_ramp_installed` is true and the referenced pad's
    `ada_path_of_travel_compliant` is true — `ERR_ADA_NONCOMPLIANT`, 422, on `POST
    /facilities/installation-schedules/{id}/complete`." PRD §3.8 on the cascade that must
    therefore not run: "The owning request moves `SCHEDULED → INSTALLED`, which moves the
    request's `encumbered_cost_cents` out of the appropriation's `encumbered_cents` and
    into its `expended_cents` and recomputes `uncommitted_cents`. The unit moves `SCHEDULED
    → INSTALLED`, has its `current_school_id` set to the request's `school_id`, has its
    `lifetime_relocation_count` incremented by 1". PRD §3.6: site work adds "3,150,000
    cents when either the unit's `ada_ramp_installed` is false or the pad's
    `ada_path_of_travel_compliant` is false", and the permit set grows by "one more when
    either the unit lacks a compliant ramp or the pad path is non-compliant".

    Design: Corner/endpoints/installation_completion_is_gated_on_accessibility_compliance
    """
    ctx = build_request_context(
        api, stage="in_progress", clock=CLOCK, school_overrides=NORTHSIDE,
        unit_overrides={"asset_tag": "PU-N101", "ada_ramp_installed": False},
    )

    blocked = api.complete_schedule(ctx["schedule_id"], {}, SCHEDULER_HEADERS)
    validate_error(blocked, ApiErrorId.ADA_NONCOMPLIANT, expected_status=422)

    assert validate_success(
        api.get_installation_schedule(ctx["schedule_id"], SCHEDULER_HEADERS)
    )["status"] == "IN_PROGRESS"

    unit = validate_success(api.get_portable_unit(ctx["unit_id"], ASSET_HEADERS))
    assert unit["allocation_status"] == "SCHEDULED"
    assert unit["current_school_id"] is None
    assert unit["lifetime_relocation_count"] == 0

    school = validate_success(api.get_school(ctx["school_id"], PLANNER_HEADERS))
    assert school["hosted_portable_seats"] == 0
    assert school["reliance_flag"] == "NONE"

    assert_budget_partition(
        validate_success(api.get_capital_budget(ctx["budget_id"], PLANNER_HEADERS)),
        authorized_cents=500_000_000, encumbered_cents=11_504_640, expended_cents=0,
        uncommitted_cents=488_495_360,
    )

    model = validate_success(api.get_cost_model(ctx["request_id"], PLANNER_HEADERS))
    assert_cost_breakdown(model, {
        "site_work_cents": 3_150_000,
        "permit_fee_cents": 840_000,
        "direct_cost_cents": 10_272_000,
        "contingency_cents": 1_232_640,
        "estimated_relocation_cost_cents": 11_504_640,
    })
