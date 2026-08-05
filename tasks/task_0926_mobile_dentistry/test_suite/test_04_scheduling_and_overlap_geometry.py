"""Visit scheduling: the two double-booking geometries, licence matching and terminal states."""

from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    assert_site_visit,
    build_portable_unit,
    build_program_period,
    build_site,
    build_site_visit,
    build_staff,
    make_program_admin_headers,
    make_site_coordinator_headers,
    set_clock,
    setup_program_site_and_staff,
    setup_visit_in_progress,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_program_admin_headers()


def _unit_overlap_fixture():
    """One SCHEDULED visit 09:00–15:00 on PU-01, plus a second dentist so only the unit rule can fire."""
    set_clock("2026-05-11T08:00:00Z")
    period = build_program_period()
    site = build_site()
    coord = make_site_coordinator_headers(site["id"])
    dentist1 = build_staff("Ada Reyes", "DENTIST", "D-1001", "SELF")
    dentist2 = build_staff("Cy Nolan", "DENTIST", "D-1002", "SELF")
    unit = build_portable_unit()
    build_site_visit(
        site["id"], period["id"], unit["id"], dentist1["id"], coord,
        onsite_dentist_staff_id=dentist1["id"],
        scheduled_start_at="2026-05-11T09:00:00Z", scheduled_end_at="2026-05-11T15:00:00Z",
        chair_count=2,
    )
    return period, site, coord, dentist2, unit


def _second_visit_payload(period, site, unit, dentist, start, end):
    return {
        "site_id": site["id"],
        "program_period_id": period["id"],
        "portable_unit_id": unit["id"],
        "lead_staff_id": dentist["id"],
        "onsite_dentist_staff_id": dentist["id"],
        "scheduled_start_at": start,
        "scheduled_end_at": end,
        "chair_count": 1,
    }


def test_unit_transport_buffer_collides_at_eighty_nine_minutes(api):
    """PRD §3.4: "A collision exists when the new visit's `scheduled_start_at` is strictly
    earlier than the other visit's `scheduled_end_at` plus 90 minutes, **and** the other
    visit's `scheduled_start_at` is strictly earlier than the new visit's `scheduled_end_at`
    plus 90 minutes."
    PRD §3.4: "Anything less does collide, and is refused with `ERR_UNIT_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/portable_unit_transport_buffer_exactly_ninety_minutes_clears_eighty_nine_collides
    """
    period, site, coord, dentist2, unit = _unit_overlap_fixture()
    resp = api.create_site_visit(
        _second_visit_payload(period, site, unit, dentist2,
                              "2026-05-11T16:29:00Z", "2026-05-11T18:00:00Z"),
        coord,
    )
    validate_error(resp, ApiErrorId.ERR_UNIT_DOUBLE_BOOKED.value, 409)

    rows, _ = validate_paginated(api.list_site_visits(ADMIN, params={"portable_unit_id": unit["id"]}))
    assert len(rows) == 1, f"The colliding visit must not be created, got {len(rows)} rows"


def test_unit_transport_buffer_clears_at_exactly_ninety_minutes(api):
    """PRD §3.4: "Both comparisons are strict, so a new visit starting exactly 90 minutes
    after another ends on the same unit does **not** collide — the van has exactly enough time
    to drive."
    PRD §3.4: "Take the scheduled duration in whole minutes — the difference between
    `scheduled_end_at` and `scheduled_start_at` — multiply it by `chair_count`, multiply that
    by a utilisation cap of 0.85, and take the floor to a whole number of minutes; the result
    is `capacity_chair_minutes`."

    Design: Difficulty/resource_temporal_overlap/portable_unit_transport_buffer_exactly_ninety_minutes_clears_eighty_nine_collides
    """
    period, site, coord, dentist2, unit = _unit_overlap_fixture()
    resp = api.create_site_visit(
        _second_visit_payload(period, site, unit, dentist2,
                              "2026-05-11T16:30:00Z", "2026-05-11T18:00:00Z"),
        coord,
    )
    visit2 = validate_success(resp, 201)
    assert_site_visit(visit2)
    assert visit2["status"] == "SCHEDULED"
    assert_same_instant(visit2["scheduled_start_at"], "2026-05-11T16:30:00Z", "scheduled_start_at")
    assert visit2["capacity_chair_minutes"] == 76, (
        f"90 minutes x 1 chair x 0.85 floored is 76, got {visit2['capacity_chair_minutes']}"
    )

    rows, _ = validate_paginated(api.list_site_visits(ADMIN, params={"portable_unit_id": unit["id"]}))
    assert len(rows) == 2, f"Expected both visits on the unit, got {len(rows)}"


def _staff_overlap_fixture():
    """One SCHEDULED visit 09:00–15:00 on PU-01 led by the only dentist, plus a spare unit."""
    set_clock("2026-05-11T08:00:00Z")
    period = build_program_period()
    site = build_site()
    coord = make_site_coordinator_headers(site["id"])
    dentist = build_staff("Ada Reyes", "DENTIST", "D-1001", "SELF")
    unit1 = build_portable_unit(unit_code="PU-01")
    unit2 = build_portable_unit(unit_code="PU-02")
    build_site_visit(
        site["id"], period["id"], unit1["id"], dentist["id"], coord,
        onsite_dentist_staff_id=dentist["id"],
        scheduled_start_at="2026-05-11T09:00:00Z", scheduled_end_at="2026-05-11T15:00:00Z",
        chair_count=2,
    )
    return period, site, coord, dentist, unit2


def test_staff_intervals_are_closed_so_touching_endpoints_collide(api):
    """PRD §3.4: "A collision exists when the new visit's `scheduled_start_at` is less than or
    equal to the other visit's `scheduled_end_at`, **and** the other visit's
    `scheduled_start_at` is less than or equal to the new visit's `scheduled_end_at`."
    PRD §3.4: "Because the comparisons are non-strict, a new visit beginning at the exact
    instant another one ends **does** collide — a clinician cannot be in two places at the
    same moment even for an instant."

    Design: Difficulty/resource_temporal_overlap/staff_closed_interval_touching_endpoints_collide_one_minute_later_does_not
    """
    period, site, coord, dentist, unit2 = _staff_overlap_fixture()
    resp = api.create_site_visit(
        _second_visit_payload(period, site, unit2, dentist,
                              "2026-05-11T15:00:00Z", "2026-05-11T17:00:00Z"),
        coord,
    )
    validate_error(resp, ApiErrorId.ERR_STAFF_DOUBLE_BOOKED.value, 409)

    rows, _ = validate_paginated(api.list_site_visits(ADMIN, params={"lead_staff_id": dentist["id"]}))
    assert len(rows) == 1, f"The colliding visit must not be created, got {len(rows)} rows"


def test_staff_intervals_clear_one_minute_after_the_previous_visit_ends(api):
    """PRD §3.4: "The rule considers the union of `lead_staff_id`, `onsite_dentist_staff_id`
    and `remote_dentist_staff_id` on both visits, ignoring nulls, and fires when any staff
    member appears on both. The refusal is `ERR_STAFF_DOUBLE_BOOKED`."
    PRD §3.4: "Take the scheduled duration in whole minutes — the difference between
    `scheduled_end_at` and `scheduled_start_at` — multiply it by `chair_count`, multiply that
    by a utilisation cap of 0.85, and take the floor to a whole number of minutes; the result
    is `capacity_chair_minutes`."

    Design: Difficulty/resource_temporal_overlap/staff_closed_interval_touching_endpoints_collide_one_minute_later_does_not
    """
    period, site, coord, dentist, unit2 = _staff_overlap_fixture()
    resp = api.create_site_visit(
        _second_visit_payload(period, site, unit2, dentist,
                              "2026-05-11T15:01:00Z", "2026-05-11T17:00:00Z"),
        coord,
    )
    visit2 = validate_success(resp, 201)
    assert_same_instant(visit2["scheduled_start_at"], "2026-05-11T15:01:00Z", "scheduled_start_at")
    assert visit2["capacity_chair_minutes"] == 101, (
        f"119 minutes x 1 chair x 0.85 floored is 101, got {visit2['capacity_chair_minutes']}"
    )

    rows, _ = validate_paginated(api.list_site_visits(ADMIN, params={"lead_staff_id": dentist["id"]}))
    assert len(rows) == 2, f"Expected both visits for the clinician, got {len(rows)}"


def test_scheduling_without_an_end_instant_is_a_validation_failure(api):
    """PRD §2.6: "Every field the endpoint requires is present, and every field present
    carries the declared JSON type."
    PRD §3.4: "Scheduling one names the `site_id`, the `program_period_id` the visit rolls up
    into, the `portable_unit_id` being taken, the `lead_staff_id` leading it, and a window
    from `scheduled_start_at` to a strictly later `scheduled_end_at`."

    Design: Corner/entities/site_visit_create_missing_required_field_returns_validation
    """
    set_clock("2026-05-11T09:00:00Z")
    period = build_program_period()
    site = build_site()
    coord = make_site_coordinator_headers(site["id"])
    dentist = build_staff("Ada Reyes", "DENTIST", "D-1001", "SELF")
    unit = build_portable_unit()

    resp = api.create_site_visit(
        {
            "site_id": site["id"],
            "program_period_id": period["id"],
            "portable_unit_id": unit["id"],
            "lead_staff_id": dentist["id"],
            "scheduled_start_at": "2026-05-11T09:00:00Z",
        },
        coord,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 400)

    rows, _ = validate_paginated(api.list_site_visits(ADMIN, params={"site_id": site["id"]}))
    assert rows == [], "A refused schedule must leave no SiteVisit row behind"


def test_out_of_state_lead_clinician_cannot_be_scheduled(api):
    """PRD §2.6: "Every staff member the request relies on — the same set enumerated for rung
    18 — has a `license_state` equal to the `state_code` of the site the visit is at. A
    clinician licensed in one state cannot work a van parked in another."

    Design: Corner/validations/scheduling_a_visit_with_an_out_of_state_lead_clinician_is_refused
    """
    set_clock("2026-05-11T09:00:00Z")
    period = build_program_period()
    site = build_site(state_code="CA")
    coord = make_site_coordinator_headers(site["id"])
    dentist_nv = build_staff("Ada Reyes", "DENTIST", "D-1001", "SELF", license_state="NV")
    unit = build_portable_unit()

    resp = api.create_site_visit(
        {
            "site_id": site["id"],
            "program_period_id": period["id"],
            "portable_unit_id": unit["id"],
            "lead_staff_id": dentist_nv["id"],
            "onsite_dentist_staff_id": dentist_nv["id"],
            "scheduled_start_at": "2026-05-11T09:00:00Z",
            "scheduled_end_at": "2026-05-11T15:00:00Z",
            "chair_count": 2,
        },
        coord,
    )
    validate_error(resp, ApiErrorId.ERR_LICENSE_STATE_MISMATCH.value, 422)

    assert validate_success(api.get_staff_member(dentist_nv["id"], ADMIN))["credential_status"] == "ACTIVE"
    rows, _ = validate_paginated(api.list_site_visits(ADMIN, params={"site_id": site["id"]}))
    assert rows == [], "A refused schedule must leave no SiteVisit row behind"


def test_a_completed_visit_cannot_be_cancelled(api):
    """PRD §3.4: "Both `COMPLETED` and `CANCELLED` are terminal."
    PRD §2.6: "The target row must currently be in a state from which the requested transition
    is declared."
    PRD §3.4: "Completion stamps `completed_at`, returns the unit from `IN_SERVICE` to
    `AVAILABLE`, moves every encounter on the visit whose `clinical_status` is `EXAMINED` or
    `TREATED` to `CLOSED`, and moves every encounter still in `REGISTERED` to `NO_SHOW`."

    Design: Corner/state_machines/cancelling_a_completed_site_visit_returns_invalid_state
    """
    stack = setup_program_site_and_staff(clock="2026-05-11T09:00:00Z")
    setup_visit_in_progress(stack)
    validate_success(api.complete_site_visit(stack.visit_id, stack.dentist_headers))

    resp = api.cancel_site_visit(stack.visit_id, {"cancel_reason": "OPERATOR_ERROR"}, stack.coord_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

    visit = validate_success(api.get_site_visit(stack.visit_id, ADMIN))
    assert visit["status"] == "COMPLETED"
    assert visit["cancelled_at"] is None
    assert validate_success(api.get_portable_unit(stack.unit_id, ADMIN))["status"] == "AVAILABLE"
