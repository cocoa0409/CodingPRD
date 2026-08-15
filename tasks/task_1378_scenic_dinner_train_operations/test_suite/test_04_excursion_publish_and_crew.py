"""Excursion creation surge rules, publish readiness gates, boarding date gate,
crew/stock assignment rules, and publish OCC (PRD §2.6, §2.8, §3.3, §3.4)."""
import pytest

from test_helpers import (
    AGENT,
    CREW,
    SCHED,
    assign_car,
    assign_crew,
    create_active_agreement,
    create_car_assignment_payload,
    create_crew_assignment_payload,
    create_draft_excursion,
    create_excursion_payload,
    create_open_slot,
    publish_excursion,
    roster_crew_member,
    roster_stock,
    set_clock,
    setup_draft_excursion,
    setup_published_excursion,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import FIRST_CLASS_SPEC, LOCO_SPEC, COACH_SPEC


def test_holiday_surge_below_minimum_rejected(api, scheduler_headers):
    """PRD §2.6: "A `REGULAR` excursion must carry a `surge_multiplier_bp` of exactly
    10000; a `HOLIDAY` excursion must carry a value between 12000 and 20000 inclusive.
    Anything else is rejected with `ERR_SURGE_MULTIPLIER_INVALID` (HTTP 422)."

    Design: Corner/validations/holiday_surge_below_minimum_rejected
    """
    agreement = create_active_agreement()
    slot = create_open_slot(agreement["id"])
    res = api.create_excursion(
        create_excursion_payload(slot["id"], title="Cheap Holiday", event_type="HOLIDAY",
                                 surge_multiplier_bp=11999),
        scheduler_headers)
    validate_error(res, ApiErrorId.ERR_SURGE_MULTIPLIER_INVALID.value, expected_status=422)


def test_regular_surge_must_equal_base(api, scheduler_headers):
    """PRD §2.6: "A `REGULAR` excursion must carry a `surge_multiplier_bp` of exactly
    10000; a `HOLIDAY` excursion must carry a value between 12000 and 20000 inclusive.
    Anything else is rejected with `ERR_SURGE_MULTIPLIER_INVALID` (HTTP 422)."

    Design: Corner/validations/regular_surge_must_equal_base
    """
    agreement = create_active_agreement()
    slot = create_open_slot(agreement["id"])
    res = api.create_excursion(
        create_excursion_payload(slot["id"], title="Sneaky Surge", event_type="REGULAR",
                                 surge_multiplier_bp=10001),
        scheduler_headers)
    validate_error(res, ApiErrorId.ERR_SURGE_MULTIPLIER_INVALID.value, expected_status=422)


def test_publish_without_locomotive_fails_consist(api, scheduler_headers):
    """PRD §3.4: "The consist must contain at least one assignment with `class_code`
    `LOCO` and at least one passenger-carrying car — `COACH`, `FIRST_CLASS`, or `DINING`
    — otherwise `ERR_CONSIST_INCOMPLETE`."

    Design: Corner/state_machines/publish_without_locomotive_fails_consist
    """
    # Passenger car present, full non-dining crew, but no LOCO in the consist.
    scenario = setup_draft_excursion(car_specs=[COACH_SPEC])
    excursion = scenario["excursion"]
    current = validate_success(api.get_excursion(excursion["id"], scheduler_headers), 200)

    res = api.excursion_event(excursion["id"],
                              {"event_type": "PUBLISH",
                               "expected_excursion_version": current["version"]},
                              scheduler_headers)
    validate_error(res, ApiErrorId.ERR_CONSIST_INCOMPLETE.value, expected_status=409)
    after = validate_success(api.get_excursion(excursion["id"], scheduler_headers), 200)
    assert after["status"] == "DRAFT"


def test_publish_without_crew_fails_coverage(api, scheduler_headers):
    """PRD §3.4: "Crew coverage must be satisfied by members currently `ASSIGNED`: at
    least one `ENGINEER`, at least one `CONDUCTOR`, and at least one `CAR_HOST`, and when
    the consist includes dining cars, at least one `CHEF` plus at least two `SERVER`s per
    dining car — a consist with two dining cars needs four servers. All thresholds are
    inclusive; falling one short fails coverage with `ERR_CREW_COVERAGE_INCOMPLETE`."

    Design: Corner/state_machines/publish_without_crew_fails_coverage
    """
    # Valid LOCO + COACH consist but zero crew assignments.
    scenario = setup_draft_excursion(with_crew=False)
    excursion = scenario["excursion"]
    current = validate_success(api.get_excursion(excursion["id"], scheduler_headers), 200)

    res = api.excursion_event(excursion["id"],
                              {"event_type": "PUBLISH",
                               "expected_excursion_version": current["version"]},
                              scheduler_headers)
    validate_error(res, ApiErrorId.ERR_CREW_COVERAGE_INCOMPLETE.value, expected_status=409)
    after = validate_success(api.get_excursion(excursion["id"], scheduler_headers), 200)
    assert after["status"] == "DRAFT"


def test_begin_boarding_from_draft_rejected(api, scheduler_headers):
    """PRD §3.4: "A `Scheduler` issues the begin-boarding event, and the excursion moves
    `PUBLISHED → BOARDING` only when the logical clock's date equals the excursion's
    `service_date` — any other day is `ERR_NOT_SERVICE_DATE` — and only while crew
    coverage still holds, otherwise `ERR_CREW_COVERAGE_INCOMPLETE` again."
    PRD §2.9: "the target entity is in a legal from-state for the requested event —
    events on terminal entities, out-of-order boarding or operation, consist edits on a
    non-`DRAFT` excursion, starting a work order on a unit that is not `AVAILABLE`,
    checking in while the excursion is not `BOARDING`, and creating an excursion on a
    slot that is not `OPEN` all fail here with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/begin_boarding_from_draft_rejected
    """
    scenario = setup_draft_excursion()
    excursion = scenario["excursion"]
    assert excursion["status"] == "DRAFT"

    res = api.excursion_event(excursion["id"], {"event_type": "BEGIN_BOARDING"}, scheduler_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    after = validate_success(api.get_excursion(excursion["id"], scheduler_headers), 200)
    assert after["status"] == "DRAFT"


def test_begin_boarding_on_wrong_date_rejected(api, scheduler_headers):
    """PRD §3.4: "A `Scheduler` issues the begin-boarding event, and the excursion moves
    `PUBLISHED → BOARDING` only when the logical clock's date equals the excursion's
    `service_date` — any other day is `ERR_NOT_SERVICE_DATE`".

    Design: Corner/validations/begin_boarding_on_wrong_date_rejected
    """
    scenario = setup_published_excursion()
    excursion = scenario["excursion"]
    set_clock("2026-10-14T08:00:00Z")

    res = api.excursion_event(excursion["id"], {"event_type": "BEGIN_BOARDING"}, scheduler_headers)
    validate_error(res, ApiErrorId.ERR_NOT_SERVICE_DATE.value, expected_status=409)
    after = validate_success(api.get_excursion(excursion["id"], scheduler_headers), 200)
    assert after["status"] == "PUBLISHED", "rejected boarding leaves the excursion PUBLISHED"


def test_duplicate_stock_assignment_rejected(api, scheduler_headers):
    """PRD §3.3: "must not already appear in this excursion's consist
    (`ERR_STOCK_ALREADY_ASSIGNED`)".

    Design: Corner/validations/duplicate_stock_assignment_rejected
    """
    scenario = setup_draft_excursion(with_crew=False)
    excursion = scenario["excursion"]
    coach = scenario["cars"]["COACH-1"]["stock"]

    res = api.create_car_assignment(
        create_car_assignment_payload(excursion["id"], coach["id"], "COACH", 3),
        scheduler_headers)
    validate_error(res, ApiErrorId.ERR_STOCK_ALREADY_ASSIGNED.value, expected_status=409)


def test_position_role_mismatch_rejected(api, crew_manager_headers):
    """PRD §3.3: "The assignment's `position` must equal the member's `role`, else
    `ERR_POSITION_ROLE_MISMATCH`."

    Design: Corner/validations/position_role_mismatch_rejected
    """
    scenario = setup_draft_excursion(car_specs=[], with_crew=False)
    chef = roster_crew_member("Chef Ana", "CHEF")

    res = api.create_crew_assignment(
        create_crew_assignment_payload(scenario["excursion"]["id"], chef["id"], "SERVER"),
        crew_manager_headers)
    validate_error(res, ApiErrorId.ERR_POSITION_ROLE_MISMATCH.value, expected_status=422)


def test_certification_expired_before_service_date_rejected(api, crew_manager_headers):
    """PRD §3.3: "For `ENGINEER` and `CONDUCTOR` positions, the member's
    `cert_expires_on` must fall on or after the excursion's `service_date`, else
    `ERR_CERTIFICATION_EXPIRED`."

    Design: Corner/validations/certification_expired_before_service_date_rejected
    """
    scenario = setup_draft_excursion(car_specs=[], with_crew=False)  # service 2026-10-15
    engineer = roster_crew_member("Old Cert", "ENGINEER", False, "2026-09-01")

    res = api.create_crew_assignment(
        create_crew_assignment_payload(scenario["excursion"]["id"], engineer["id"], "ENGINEER"),
        crew_manager_headers)
    validate_error(res, ApiErrorId.ERR_CERTIFICATION_EXPIRED.value, expected_status=422)


def test_engineer_without_cert_rejected(api, crew_manager_headers):
    """PRD §3.3: "Engineers and conductors are certificate-holders: creating one without
    `cert_expires_on` is `ERR_CERTIFICATION_REQUIRED`, while for the other four roles the
    field must be null, again on pain of `ERR_VALIDATION`."

    Design: Corner/validations/engineer_without_cert_rejected
    """
    res = api.create_crew_member(
        {"name": "No Cert Ned", "role": "ENGINEER", "is_volunteer": False},
        crew_manager_headers)
    validate_error(res, ApiErrorId.ERR_CERTIFICATION_REQUIRED.value, expected_status=422)

    ok = api.create_crew_member(
        {"name": "Svr One", "role": "SERVER", "is_volunteer": False},
        crew_manager_headers)
    member = validate_success(ok, 201)
    assert member["status"] == "ACTIVE", "SERVER without a cert rosters fine"


def test_crew_double_booking_same_date_rejected(api, crew_manager_headers):
    """PRD §3.3: "One person cannot be in two places at once: a member already
    `ASSIGNED` to another excursion sharing the same `service_date` triggers
    `ERR_CREW_DATE_CONFLICT`."

    Design: Corner/validations/crew_double_booking_same_date_rejected
    """
    agreement = create_active_agreement()
    slot1 = create_open_slot(agreement["id"], start_minute=600, end_minute=780)
    slot2 = create_open_slot(agreement["id"], start_minute=780, end_minute=900)
    ex1 = create_draft_excursion(slot1["id"], title="Run 1")
    ex2 = create_draft_excursion(slot2["id"], title="Run 2")
    engineer = roster_crew_member("Ed Eng", "ENGINEER", False, "2027-06-01")
    assign_crew(ex1["id"], engineer["id"], "ENGINEER")

    # Same service_date, disjoint slot minutes: still a conflict.
    res = api.create_crew_assignment(
        create_crew_assignment_payload(ex2["id"], engineer["id"], "ENGINEER"),
        crew_manager_headers)
    validate_error(res, ApiErrorId.ERR_CREW_DATE_CONFLICT.value, expected_status=409)


def test_occ_publish_stale_excursion_version(api, scheduler_headers):
    """PRD §2.8: "A publish request must carry `expected_excursion_version`, the
    `version` of the excursion the client last observed. Because every consist edit and
    every crew assignment or release increments the excursion's `version`, a client whose
    view predates any such change holds a stale number; if `expected_excursion_version`
    does not equal the excursion's current `version`, the publish is rejected with
    `ERR_STALE_VERSION` and the client must re-read the excursion and re-publish what it
    actually reviewed."

    Design: Corner/cross_cutting_layers/occ_publish_stale_excursion_version
    """
    scenario = setup_draft_excursion(car_specs=[LOCO_SPEC, COACH_SPEC, FIRST_CLASS_SPEC][0:2])
    excursion = scenario["excursion"]
    observed = validate_success(api.get_excursion(excursion["id"], scheduler_headers), 200)
    stale_version = observed["version"]

    # A consist edit after the client's read advances Excursion.version.
    fc = roster_stock("FC-1", "FIRST_CLASS_CAR", 20, 0)
    assign_car(excursion["id"], fc["id"], "FIRST_CLASS", 3)

    res = api.excursion_event(excursion["id"],
                              {"event_type": "PUBLISH",
                               "expected_excursion_version": stale_version},
                              scheduler_headers)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)

    fresh = validate_success(api.get_excursion(excursion["id"], scheduler_headers), 200)
    res = api.excursion_event(excursion["id"],
                              {"event_type": "PUBLISH",
                               "expected_excursion_version": fresh["version"]},
                              scheduler_headers)
    published = validate_success(res, 200)
    assert published["status"] == "PUBLISHED", "fresh publish succeeds"
