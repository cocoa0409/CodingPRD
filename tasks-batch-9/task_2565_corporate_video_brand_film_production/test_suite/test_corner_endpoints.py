"""What a single call does, and what a single read shows for it.

Four endpoints are exercised for their own declared behaviour: the sign-off that
snapshots a baseline and commits every planned line at once, the line-creation call
whose result depends entirely on how far its project has travelled, the reservation
whose parent link is resolved before anything is priced, and the venue that reads
back exactly as it was filed with its two scheduling columns still empty.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import (
    BUDGET_LINE_COMMITTED,
    BUDGET_LINE_PLANNED,
    CATEGORY_CREW,
    CATEGORY_EQUIPMENT,
    CATEGORY_POST,
    COORDINATOR,
    LINE_PRODUCER,
    LOCATION_SCOUTED,
    NON_EXISTENT_UUID,
    PROJECT_IN_PRODUCTION,
    RESERVATION_RESERVED,
    ApiErrorId,
    add_budget_line,
    add_deliverable,
    approve_budget,
    assert_budget_line,
    assert_common_fields,
    assert_empty_listing,
    assert_ledgers,
    assert_project_state,
    assert_reservation,
    assert_total_count,
    assert_version_bumped,
    assert_version_is,
    equipment_reservation_payload,
    lock_scope,
    ok_row,
    open_project,
    read_project,
    register_location,
    reserve_equipment,
    schedule_shoot_day,
)


def _project_with_one_olv_deliverable(api, client_name, campaign_title, brief, ceiling_cents):
    """A `DRAFT` project with the one deliverable a later scope lock will demand."""
    project = open_project(
        api,
        client_name=client_name,
        campaign_title=campaign_title,
        creative_brief_summary=brief,
        channel_scope=["OLV"],
        usage_term_months=12,
        budget_ceiling_cents=ceiling_cents,
    )
    add_deliverable(
        api,
        project["id"],
        title=f"{campaign_title} 60",
        channel="OLV",
        aspect_ratio="16:9",
        target_duration_seconds=60,
        caption_requirement="NONE",
        usage_rights_months=12,
        air_date="2026-12-01T00:00:00Z",
    )
    return project


def _line_by_id(api, project_id, line_id, **params):
    """One budget line, read back through the only listing that exposes it."""
    rows, _meta = validate_paginated(
        api.list_project_budget_lines(project_id, headers=LINE_PRODUCER, **params)
    )
    matches = [row for row in rows if row["id"] == line_id]
    assert matches, f"budget line {line_id} is missing from the listing"
    return matches[0]


def test_approving_the_budget_snapshots_the_baseline_and_commits_every_planned_line(api):
    """One call moves the status, flips both lines, snapshots the baseline and bumps the row.

    PRD §3.2: "The request carries `approved_budget_cents`; the value the server stores in
    `approved_budget_cents` is the project's `provisional_cost_cents` evaluated at the
    instant of approval, which becomes the baseline against which variance is measured
    from then on."

    PRD §3.2: "Sign-off then cascades down: every budget line of the project still in
    `PLANNED` — each one under a project that is `SCOPED` at that moment — transitions
    `PLANNED → COMMITTED`."

    PRD §3.2: "Caused by that line cascade, `committed_cost_cents` is recomputed and now
    includes those lines, and `budget_variance_cents` is recomputed, which necessarily
    reads 0 at this instant because the baseline was just snapshotted from the same
    provisional figure."

    Design: Corner/endpoints/approve_budget_snapshots_the_number_and_commits_every_planned_line
    """
    project = _project_with_one_olv_deliverable(
        api,
        "Thorne Instruments",
        "Green Light",
        "Brand film awaiting client budget approval.",
        3000000,
    )
    crew_line = add_budget_line(
        api,
        project["id"],
        category=CATEGORY_CREW,
        description="Core unit",
        quantity=1,
        unit_rate_cents=1200000,
        markup_pct=0,
    )
    post_line = add_budget_line(
        api,
        project["id"],
        category=CATEGORY_POST,
        description="Edit and finish",
        quantity=1,
        unit_rate_cents=800000,
        markup_pct=0,
    )
    lock_scope(api, project["id"])
    before = read_project(api, project["id"])

    approved = approve_budget(api, project["id"], 2000000)

    assert_project_state(approved, status=PROJECT_IN_PRODUCTION)
    assert approved["approved_budget_cents"] == 2000000, approved["approved_budget_cents"]
    assert_ledgers(
        approved,
        provisional_cents=2000000,
        committed_cents=2000000,
        approved_cents=2000000,
        variance_cents=0,
    )
    assert_version_bumped(before, approved)
    assert_budget_line(
        _line_by_id(api, project["id"], crew_line["id"]),
        extended_cents=1200000,
        status=BUDGET_LINE_COMMITTED,
    )
    assert_budget_line(
        _line_by_id(api, project["id"], post_line["id"]),
        extended_cents=800000,
        status=BUDGET_LINE_COMMITTED,
    )
    assert_total_count(
        api.list_project_budget_lines(
            project["id"], headers=LINE_PRODUCER, status=BUDGET_LINE_COMMITTED
        ),
        2,
    )


def test_a_budget_line_auto_commits_only_once_the_budget_has_been_approved(api):
    """The same payload is born `PLANNED` before sign-off and `COMMITTED` after it.

    PRD §3.2: "A line created while the project is `DRAFT` or `SCOPED` starts at `status`
    `PLANNED` and joins the provisional figure only."

    PRD §3.2: "A line created while the project is `IN_PRODUCTION` or `IN_POST` is
    auto-committed in the very same request: it is written directly as `COMMITTED`, and
    the project's `committed_cost_cents` increases by that line's `extended_cents`
    immediately, alongside the provisional increase."

    PRD §2.8: "The allowance depends on where the project stands: while the project's
    `status` is `DRAFT` or `SCOPED` the allowance equals `budget_ceiling_cents` exactly,
    with no tolerance; once the budget has been approved — that is, for `IN_PRODUCTION`,
    `IN_POST` and any later status — the allowance is `budget_ceiling_cents` multiplied by
    1.05, rounded half up to whole cents, so the production may run five percent hot
    against its contracted ceiling."

    Design: Corner/endpoints/budget_line_auto_commits_only_while_the_project_is_in_production
    """
    project = _project_with_one_olv_deliverable(
        api,
        "Rossiter Dairy",
        "Two Timings",
        "Brand film with lines added on both sides of approval.",
        3000000,
    )

    drafted_line = add_budget_line(
        api,
        project["id"],
        category=CATEGORY_CREW,
        description="Core unit booked in draft",
        quantity=1,
        unit_rate_cents=2000000,
        markup_pct=0,
    )
    assert_budget_line(
        drafted_line, extended_cents=2000000, status=BUDGET_LINE_PLANNED, category=CATEGORY_CREW
    )
    assert_ledgers(
        read_project(api, project["id"]), provisional_cents=2000000, committed_cents=0
    )

    lock_scope(api, project["id"])
    approve_budget(api, project["id"], 2000000)

    production_line = add_budget_line(
        api,
        project["id"],
        category=CATEGORY_POST,
        description="Colour grade added in production",
        quantity=1,
        unit_rate_cents=500000,
        markup_pct=0,
    )

    assert_budget_line(
        production_line,
        extended_cents=500000,
        status=BUDGET_LINE_COMMITTED,
        category=CATEGORY_POST,
    )
    assert_budget_line(
        _line_by_id(api, project["id"], drafted_line["id"]), status=BUDGET_LINE_COMMITTED
    )
    assert_ledgers(
        read_project(api, project["id"]),
        provisional_cents=2500000,
        committed_cents=2500000,
        approved_cents=2000000,
        variance_cents=500000,
    )


def test_a_reservation_resolves_its_shoot_day_before_it_prices_anything(api):
    """An unknown day is a 404 before any money is computed; the real day gets the row.

    PRD §2.12: "Priorities 6 through 15: **Existence** of every referenced row, in this
    order of identifier families — project (priority 6), deliverable (7), cut (8), change
    order (9), shoot day (10), location (11), crew member (12), crew booking (13),
    compliance certificate (14), talent engagement (15) — each reporting the 404 code
    listed in §2.11."

    PRD §3.6: "`rental_days` is the span from pickup to return in hours divided by 24 and
    rounded up to a whole day, with a floor of one day, so any partial day bills as a full
    day and a same-morning pickup and return still bills one."

    Design: Corner/endpoints/equipment_reservation_links_a_shoot_day_that_must_already_exist
    """
    project = _project_with_one_olv_deliverable(
        api,
        "Ferro Cycles",
        "Chainline",
        "Brand film with a single rental package.",
        50000000,
    )
    add_budget_line(
        api,
        project["id"],
        category=CATEGORY_EQUIPMENT,
        description="Camera package",
        quantity=1,
        unit_rate_cents=200000,
        markup_pct=0,
    )
    lock_scope(api, project["id"])
    location = register_location(
        api,
        name="Ferro Workshop",
        address="18 Spoke Street, Portland",
        stage_count=1,
        daily_fee_cents=90000,
        insurance_minimum_cents=50000000,
        permit_authority="Portland Film Office",
    )
    day = schedule_shoot_day(
        api,
        project["id"],
        location["id"],
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )

    orphan = api.create_equipment_reservation(
        equipment_reservation_payload(
            NON_EXISTENT_UUID,
            vendor_name="Rose City Camera",
            kit_label="A camera",
            unit_count=1,
            daily_rate_cents=30000,
            pickup_at="2026-09-09T06:00:00Z",
            return_at="2026-09-11T16:00:00Z",
        ),
        headers=COORDINATOR,
    )

    validate_error(orphan, ApiErrorId.ERR_SHOOT_DAY_NOT_FOUND)
    assert_empty_listing(
        api.list_shoot_day_equipment_reservations(day["id"], headers=COORDINATOR)
    )

    reservation = reserve_equipment(
        api,
        day["id"],
        vendor_name="Rose City Camera",
        kit_label="A camera",
        unit_count=1,
        daily_rate_cents=30000,
        pickup_at="2026-09-09T06:00:00Z",
        return_at="2026-09-11T16:00:00Z",
    )

    assert reservation["shoot_day_id"] == day["id"], reservation["shoot_day_id"]
    assert_reservation(
        reservation, rental_days=3, total_cost_cents=90000, status=RESERVATION_RESERVED
    )
    rows = assert_total_count(
        api.list_shoot_day_equipment_reservations(day["id"], headers=COORDINATOR), 1
    )
    assert rows[0]["id"] == reservation["id"], rows[0]["id"]
    assert_ledgers(
        read_project(api, project["id"]), provisional_cents=290000, committed_cents=90000
    )


def test_a_freshly_registered_venue_reads_back_with_its_scheduling_columns_empty(api):
    """Every filed field survives the round trip, and nothing is scheduled there yet.

    PRD §3.4: "A location carries a `name` and an `address` as they will appear on permits
    and call sheets (non-blank; up to 120 and 200 characters respectively), a `stage_count`
    of independently bookable stages or areas (an integer from 1 to 12), a
    `daily_fee_cents` per shoot day (at least 0), an `insurance_minimum_cents` naming the
    minimum general-liability coverage the venue demands before any shoot day there may be
    confirmed (at least 0), and the `permit_authority` — the jurisdiction that issues film
    permits for that address (non-blank, up to 120 characters)."

    PRD §3.4: "A fresh location reports `scouting_status` `SCOUTED` and
    `scheduled_shoot_day_count` 0."

    Design: Corner/endpoints/location_create_then_read_returns_the_same_row_with_zeroed_scheduling
    """
    created = register_location(
        api,
        name="Cadwell Glasshouse",
        address="7 Nursery Lane, Ithaca",
        stage_count=2,
        daily_fee_cents=125000,
        insurance_minimum_cents=200000000,
        permit_authority="Ithaca Film Office",
    )

    read_back = ok_row(api.get_location(created["id"], headers=LINE_PRODUCER))

    assert read_back["id"] == created["id"], read_back["id"]
    assert read_back["name"] == "Cadwell Glasshouse", read_back["name"]
    assert read_back["address"] == "7 Nursery Lane, Ithaca", read_back["address"]
    assert read_back["stage_count"] == 2, read_back["stage_count"]
    assert read_back["daily_fee_cents"] == 125000, read_back["daily_fee_cents"]
    assert read_back["insurance_minimum_cents"] == 200000000, read_back["insurance_minimum_cents"]
    assert read_back["permit_authority"] == "Ithaca Film Office", read_back["permit_authority"]
    assert read_back["scheduled_shoot_day_count"] == 0, read_back["scheduled_shoot_day_count"]
    assert read_back["scouting_status"] == LOCATION_SCOUTED, read_back["scouting_status"]
    assert_common_fields(read_back)
    assert_version_is(read_back, 1)
