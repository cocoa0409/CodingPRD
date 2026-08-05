"""Preventive care: the periodicity schedule, punctuality and the missed sweep."""

from test_helpers import (
    TEST_USERS,
    assert_date_equals,
    assert_well_visit,
    complete_well_visit,
    enroll,
    set_clock,
    setup_active_membership,
    setup_household,
    setup_practice,
    service_lines_for_membership,
    validate_paginated,
    validate_success,
    well_visit_for,
    well_visits_for,
)

ADMIN = TEST_USERS["admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


def _child_born_april_with_active_membership():
    return setup_active_membership(
        clock="2026-05-24T09:00:00Z",
        household_name="Quiroga",
        child_first_name="Sol",
        date_of_birth="2026-04-01",
        start_date="2026-05-24",
    )


def _child_born_april_pending_membership():
    practice = setup_practice(clock="2026-05-24T09:00:00Z")
    household = setup_household(
        household_name="Petrov", child_first_name="Mira", date_of_birth="2026-04-01"
    )
    membership = enroll(
        household["child"]["id"],
        practice["plan"]["id"],
        practice["physician"]["id"],
        "2026-05-24",
        household["family"]["id"],
    )
    return {**practice, **household, "membership": membership}


def test_completion_on_either_window_boundary_is_on_schedule(api):
    """PRD §3.5: "A `completed_date` on or after the open date and on or before the
    `window_close_date` is `ON_SCHEDULE`."
    PRD §3.5: "For a child born 2026-04-01 the `M2` milestone opens 2026-05-24 and closes
    2026-06-15, so a completion on 2026-05-23 is `EARLY`, one on 2026-05-24 is
    `ON_SCHEDULE`, one on 2026-06-15 is still `ON_SCHEDULE`, and one on 2026-06-16 is
    `DELAYED`."

    Design: Difficulty/boundary_precision_check/well_visit_punctuality_at_both_window_boundaries
    """
    scenario = _child_born_april_with_active_membership()
    membership, doc = scenario["membership"], scenario["physician"]

    m2 = well_visit_for(membership["id"], "M2")
    assert_well_visit(m2)
    assert_date_equals(m2["window_open_date"], "2026-05-24", "M2.window_open_date")
    assert_date_equals(m2["window_close_date"], "2026-06-15", "M2.window_close_date")

    completed_m2 = complete_well_visit(m2["id"], doc["id"], "2026-05-24")
    assert completed_m2["punctuality"] == "ON_SCHEDULE", "the open date belongs to the middle band"
    assert completed_m2["status"] == "COMPLETED"

    set_clock("2026-08-15T09:00:00Z")

    m4 = well_visit_for(membership["id"], "M4")
    assert_date_equals(m4["window_open_date"], "2026-07-24", "M4.window_open_date")
    assert_date_equals(m4["window_close_date"], "2026-08-15", "M4.window_close_date")

    completed_m4 = complete_well_visit(m4["id"], doc["id"], "2026-08-15")
    assert completed_m4["punctuality"] == "ON_SCHEDULE", "the close date belongs to the middle band"
    assert completed_m4["status"] == "COMPLETED"


def test_completion_one_day_outside_either_edge_is_early_or_delayed(api):
    """PRD §3.5: "A `completed_date` strictly before the `window_open_date` is `EARLY`."
    PRD §3.5: "A `completed_date` strictly after the close date is `DELAYED`."
    PRD §3.5: "On success the visit records its `completed_date`, classifies
    `punctuality`, and produces a service line: `service_code` `WELL_VISIT`, route
    `COVERED_BY_MEMBERSHIP`, `billed_amount_cents` 22 000, `membership_covered_cents`
    22 000, `patient_responsibility_cents` 0, carrying the `well_visit_id` of the visit
    and created directly in status `SETTLED`."

    Design: Difficulty/boundary_precision_check/well_visit_punctuality_at_both_window_boundaries
    """
    scenario = _child_born_april_with_active_membership()
    membership, doc = scenario["membership"], scenario["physician"]

    complete_well_visit(well_visit_for(membership["id"], "M2")["id"], doc["id"], "2026-05-24")

    set_clock("2026-08-15T09:00:00Z")
    complete_well_visit(well_visit_for(membership["id"], "M4")["id"], doc["id"], "2026-08-15")

    set_clock("2026-09-22T09:00:00Z")
    m6 = well_visit_for(membership["id"], "M6")
    assert_date_equals(m6["window_open_date"], "2026-09-23", "M6.window_open_date")
    assert_date_equals(m6["window_close_date"], "2026-10-15", "M6.window_close_date")
    completed_m6 = complete_well_visit(m6["id"], doc["id"], "2026-09-22")
    assert completed_m6["punctuality"] == "EARLY"
    assert completed_m6["status"] == "COMPLETED"

    set_clock("2027-01-20T09:00:00Z")
    m9 = well_visit_for(membership["id"], "M9")
    assert_date_equals(m9["window_open_date"], "2026-12-16", "M9.window_open_date")
    assert_date_equals(m9["window_close_date"], "2027-01-15", "M9.window_close_date")
    completed_m9 = complete_well_visit(m9["id"], doc["id"], "2027-01-20")
    assert completed_m9["punctuality"] == "DELAYED"
    assert completed_m9["status"] == "COMPLETED"

    lines = service_lines_for_membership(membership["id"])
    well_visit_lines = [line for line in lines if line["service_code"] == "WELL_VISIT"]
    assert len(well_visit_lines) == 4
    for line in well_visit_lines:
        assert line["billed_amount_cents"] == 22000
        assert line["route"] == "COVERED_BY_MEMBERSHIP"
        assert line["status"] == "SETTLED"


def test_well_visit_generation_skips_milestones_whose_window_already_closed(api):
    """PRD §3.5: "A well-visit row is generated only when that `window_close_date` is on
    or after the membership's `start_date` — the test is inclusive, so a milestone whose
    window closes exactly on the start date **is** generated. Milestones whose window
    closed strictly before the start date are never generated at all, which is why a
    child enrolled at four months of age carries no `NEWBORN` and no `M1` row."
    PRD §3.5: "Each generated row records the `membership_id` that produced it, the
    `child_id` denormalised from that membership, its `milestone_code`, the three
    computed dates, a null `scheduled_date`, a null `completed_date`, a null
    `punctuality`, and status `DUE`."

    Design: Corner/calculations/corner_well_visit_generation_skips_milestones_already_closed
    """
    practice = setup_practice(clock="2026-05-24T09:00:00Z")
    household = setup_household(
        household_name="Cordero", child_first_name="Tico", date_of_birth="2026-04-01"
    )
    membership = enroll(
        household["child"]["id"],
        practice["plan"]["id"],
        practice["physician"]["id"],
        "2026-05-24",
        household["family"]["id"],
    )

    visits = well_visits_for(membership["id"])
    assert len(visits) == 9
    codes = [v["milestone_code"] for v in visits]
    assert set(codes) == {"M2", "M4", "M6", "M9", "M12", "M24", "M36", "M48", "M60"}
    assert "NEWBORN" not in codes and "M1" not in codes

    first = visits[0]
    assert first["milestone_code"] == "M2"
    assert_date_equals(first["window_open_date"], "2026-05-24", "M2.window_open_date")
    assert_date_equals(first["window_close_date"], "2026-06-15", "M2.window_close_date")
    assert_date_equals(first["target_date"], "2026-06-01", "M2.target_date")
    assert first["status"] == "DUE"

    by_child, meta = validate_paginated(
        api.list_well_visits(COORDINATOR, params={"child_id": household["child"]["id"]})
    )
    assert meta["total_count"] == 9
    assert {row["id"] for row in by_child} == {row["id"] for row in visits}


def test_scheduling_a_due_visit_records_the_date_without_completing_it(api):
    """PRD §3.5: "A `CareCoordinator` or `PracticeAdmin` books a due visit by supplying a
    `scheduled_date`, moving it `DUE → SCHEDULED`. Booking requires the owning membership
    to be in `PENDING_ACTIVATION` or `ACTIVE` — notably a not-yet-activated membership may
    still book, because families schedule their newborn visit before the first invoice
    clears — and requires the `scheduled_date` not to be earlier than today."

    Design: Corner/state_machines/corner_schedule_well_visit_moves_due_to_scheduled
    """
    scenario = _child_born_april_pending_membership()
    membership = scenario["membership"]
    assert membership["status"] == "PENDING_ACTIVATION"

    m2 = well_visit_for(membership["id"], "M2")
    scheduled = validate_success(
        api.schedule_well_visit(m2["id"], {"scheduled_date": "2026-06-10"}, COORDINATOR)
    )

    assert scheduled["status"] == "SCHEDULED"
    assert_date_equals(scheduled["scheduled_date"], "2026-06-10", "WellVisit.scheduled_date")
    assert scheduled["completed_date"] is None
    assert scheduled["punctuality"] is None
    assert_date_equals(scheduled["target_date"], "2026-06-01", "M2.target_date")
    assert_date_equals(scheduled["window_open_date"], "2026-05-24", "M2.window_open_date")
    assert_date_equals(scheduled["window_close_date"], "2026-06-15", "M2.window_close_date")

    _, meta = validate_paginated(
        api.list_well_visits(
            COORDINATOR, params={"membership_id": membership["id"], "status": "DUE"}
        )
    )
    assert meta["total_count"] == 8


def test_due_visit_is_swept_to_missed_only_past_the_thirty_day_tail(api):
    """PRD §3.5: "Whenever the logical clock moves, every well visit in `DUE` or
    `SCHEDULED` whose `window_close_date` plus thirty days falls strictly before the new
    current date is swept to `MISSED`."
    PRD §3.5: "That thirty-day tail is deliberate: inside it a late completion is still
    recordable and is classified `DELAYED`."

    Design: Corner/state_machines/corner_well_visit_swept_to_missed_only_after_close_plus_grace
    """
    scenario = _child_born_april_pending_membership()
    membership = scenario["membership"]

    m2 = well_visit_for(membership["id"], "M2")
    assert_date_equals(m2["window_close_date"], "2026-06-15", "M2.window_close_date")

    set_clock("2026-07-15T00:00:00Z")
    at_grace = validate_success(api.get_well_visit(m2["id"], COORDINATOR))
    assert at_grace["status"] == "DUE", "close + 30 is not strictly before today"

    set_clock("2026-07-16T00:00:00Z")
    past_grace = validate_success(api.get_well_visit(m2["id"], COORDINATOR))
    assert past_grace["status"] == "MISSED"
    assert past_grace["completed_date"] is None
    assert past_grace["punctuality"] is None

    m4 = well_visit_for(membership["id"], "M4")
    assert m4["status"] == "DUE", "the M4 window closes 2026-08-15 and is untouched"
