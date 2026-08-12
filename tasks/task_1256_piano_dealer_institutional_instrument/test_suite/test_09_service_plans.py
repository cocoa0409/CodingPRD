"""Service plan credits, technician capacity, and loyalty pricing (PRD §3.7)."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    setup_installed_order, create_service_plan, get_service_plan, create_technician,
    book_visit, complete_visit, create_service_visit_payload,
    assert_plan_credit_invariant,
    TEST_USERS,
)

COORDINATOR = TEST_USERS["service_coordinator_headers"]


def _exhausted_basic_plan(api):
    """INSTALLED order with a BASIC plan whose two visits are both COMPLETED."""
    customer, instrument, order = setup_installed_order(
        serial_number="SN-Z-1", job_window=("2026-05-03T09:00:00Z", "2026-05-03T11:00:00Z"))
    plan = create_service_plan(order["id"], "BASIC")
    technician = create_technician(full_name="Ted Tuner", certification_level="STANDARD")
    v1 = book_visit(plan["id"], technician["id"], "2026-06-01T09:00:00Z", "2026-06-01T10:00:00Z")
    complete_visit(v1["id"])
    v2 = book_visit(plan["id"], technician["id"], "2026-06-01T11:00:00Z", "2026-06-01T12:00:00Z")
    complete_visit(v2["id"])
    return plan, technician


def test_zero_credit_booking_rejected(api):
    """PRD §3.7: "Booking requires the plan to be `ACTIVE` — otherwise
    `ERR_PLAN_NOT_ACTIVE` — and requires `visits_available` greater than zero, else
    `ERR_PLAN_EXHAUSTED`."
    PRD §3.7: "On every plan mutation the system re-evaluates exhaustion: when
    `visits_used` has reached `visits_total` with nothing left booked, the plan moves itself
    from `ACTIVE` to `EXHAUSTED`."
    (A BASIC plan with both visits consumed has visits_available exactly 0; the next booking
    must fail — 0 is rejected, not treated as one remaining. The plan is by then EXHAUSTED,
    so either the exhausted-plan rejection or the not-active rejection is PRD-conformant.)

    Design: Difficulty/boundary_precision_check/service_plan_zero_credit_booking_rejected
    """
    plan, technician = _exhausted_basic_plan(api)
    res = api.create_service_visit(
        create_service_visit_payload(plan["id"], technician["id"],
                                     "2026-06-01T14:00:00Z", "2026-06-01T15:00:00Z"),
        COORDINATOR)
    validate_error_is_one_of(res, ["ERR_PLAN_EXHAUSTED", "ERR_PLAN_NOT_ACTIVE"])
    after = get_service_plan(plan["id"])
    assert after["visits_used"] == 2
    assert after["visits_booked"] == 0
    assert after["visits_available"] == 0


def test_plan_auto_exhausts_when_all_visits_used(api):
    """PRD §3.7: "On every plan mutation the system re-evaluates exhaustion: when
    `visits_used` has reached `visits_total` with nothing left booked, the plan moves itself
    from `ACTIVE` to `EXHAUSTED`."
    PRD §3.7: "The plan's `price_cents` and `visits_total` come from the tier: `BASIC` costs
    30,000 cents and carries 2 visits, `STANDARD` costs 55,000 cents with 4 visits, and
    `PREMIUM` costs 85,000 cents with 6 visits."

    Design: Difficulty/boundary_precision_check/service_plan_zero_credit_booking_rejected
    """
    plan, _ = _exhausted_basic_plan(api)
    after = get_service_plan(plan["id"])
    assert after["visits_total"] == 2
    assert after["status"] == "EXHAUSTED", "visits_used == visits_total with nothing booked"
    assert_plan_credit_invariant(after)


def _standard_plan_with_technician(api, serial="SN-V-1"):
    customer, instrument, order = setup_installed_order(
        serial_number=serial, job_window=("2026-05-05T09:00:00Z", "2026-05-05T11:00:00Z"))
    plan = create_service_plan(order["id"], "STANDARD")
    technician = create_technician(full_name="Uma Upright", certification_level="STANDARD")
    return plan, technician


def test_visit_booking_holds_one_credit(api):
    """PRD §3.7: "A successfully booked visit starts in `BOOKED` and holds one plan credit:
    `visits_booked` increases by one."
    PRD §3.7: "The bookkeeping invariant never breaks: used plus booked plus available
    always equals `visits_total`."

    Design: Difficulty/compensating_invariant/visit_book_then_cancel_conserves_plan_credits
    """
    plan, technician = _standard_plan_with_technician(api)
    visit = book_visit(plan["id"], technician["id"],
                       "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z")
    assert visit["status"] == "BOOKED"
    after = get_service_plan(plan["id"])
    assert after["visits_used"] == 0
    assert after["visits_booked"] == 1
    assert after["visits_available"] == 3
    assert_plan_credit_invariant(after)


def test_visit_cancel_releases_held_credit(api):
    """PRD §3.7: "Cancelling a visit likewise requires `BOOKED`, moves the visit to
    `CANCELLED`, and hands the credit back — `visits_booked` decreases by one while
    `visits_used` is untouched."
    PRD §3.7: "The bookkeeping invariant never breaks: used plus booked plus available
    always equals `visits_total`."

    Design: Difficulty/compensating_invariant/visit_book_then_cancel_conserves_plan_credits
    """
    plan, technician = _standard_plan_with_technician(api)
    visit = book_visit(plan["id"], technician["id"],
                       "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z")
    cancelled = validate_success(api.cancel_service_visit(visit["id"], COORDINATOR), 200)
    assert cancelled["status"] == "CANCELLED"
    after = get_service_plan(plan["id"])
    assert after["visits_used"] == 0, "cancel leaves visits_used untouched"
    assert after["visits_booked"] == 0
    assert after["visits_available"] == 4, "compensating release returns the credit"
    assert after["status"] == "ACTIVE"
    assert_plan_credit_invariant(after)


def test_plan_suspend_blocks_booking_then_resume(api):
    """PRD §3.7: "Booking requires the plan to be `ACTIVE` — otherwise
    `ERR_PLAN_NOT_ACTIVE` — and requires `visits_available` greater than zero, else
    `ERR_PLAN_EXHAUSTED`."
    PRD §3.7: "A coordinator may suspend an `ACTIVE` plan (`ACTIVE` → `SUSPENDED`) and
    resume a suspended one (`SUSPENDED` → `ACTIVE`); each requires the matching source
    state, else `ERR_PLAN_NOT_ACTIVE`."

    Design: Corner/state_machines/plan_suspend_blocks_booking_then_resume
    """
    customer, instrument, order = setup_installed_order(
        serial_number="SN-SP-1", job_window=("2026-05-06T09:00:00Z", "2026-05-06T11:00:00Z"))
    plan = create_service_plan(order["id"], "STANDARD")
    technician = create_technician(full_name="Tammy Tech", certification_level="STANDARD")
    validate_success(api.suspend_service_plan(plan["id"], COORDINATOR), 200)

    res = api.create_service_visit(
        create_service_visit_payload(plan["id"], technician["id"],
                                     "2026-06-11T09:00:00Z", "2026-06-11T10:00:00Z"),
        COORDINATOR)
    validate_error(res, "ERR_PLAN_NOT_ACTIVE")

    validate_success(api.resume_service_plan(plan["id"], COORDINATOR), 200)
    visit = book_visit(plan["id"], technician["id"],
                       "2026-06-11T09:00:00Z", "2026-06-11T10:00:00Z")
    assert visit["status"] == "BOOKED"
    assert get_service_plan(plan["id"])["visits_booked"] == 1


def test_technician_shared_endpoint_conflicts(api):
    """PRD §3.7: "Their windows follow closed-interval semantics, so two `BOOKED` visits for
    the same technician conflict whenever their intervals touch, shared endpoints included
    (`ERR_TECHNICIAN_WINDOW_CONFLICT`)."
    (Existing 09:00-10:00; a successor starting at 10:00 shares the endpoint.)

    Design: Difficulty/resource_temporal_overlap/technician_closed_interval_shared_endpoint_conflicts
    """
    customer, instrument, order = setup_installed_order(
        serial_number="SN-CL-1", job_window=("2026-05-04T09:00:00Z", "2026-05-04T11:00:00Z"))
    plan = create_service_plan(order["id"], "STANDARD")
    technician = create_technician(full_name="Tim Tuner", certification_level="MASTER")
    book_visit(plan["id"], technician["id"], "2026-06-03T09:00:00Z", "2026-06-03T10:00:00Z")

    res = api.create_service_visit(
        create_service_visit_payload(plan["id"], technician["id"],
                                     "2026-06-03T10:00:00Z", "2026-06-03T11:00:00Z"),
        COORDINATOR)
    validate_error(res, "ERR_TECHNICIAN_WINDOW_CONFLICT")


def test_technician_successor_after_shared_endpoint_succeeds(api):
    """PRD §3.7: "Their windows follow closed-interval semantics, so two `BOOKED` visits for
    the same technician conflict whenever their intervals touch, shared endpoints included
    (`ERR_TECHNICIAN_WINDOW_CONFLICT`)."
    PRD §3.7: "A successfully booked visit starts in `BOOKED` and holds one plan credit:
    `visits_booked` increases by one."
    (A 10:00:01 start does not touch the 09:00-10:00 interval.)

    Design: Difficulty/resource_temporal_overlap/technician_closed_interval_shared_endpoint_conflicts
    """
    customer, instrument, order = setup_installed_order(
        serial_number="SN-CL-1", job_window=("2026-05-04T09:00:00Z", "2026-05-04T11:00:00Z"))
    plan = create_service_plan(order["id"], "STANDARD")
    technician = create_technician(full_name="Tim Tuner", certification_level="MASTER")
    book_visit(plan["id"], technician["id"], "2026-06-03T09:00:00Z", "2026-06-03T10:00:00Z")

    visit = validate_success(api.create_service_visit(
        create_service_visit_payload(plan["id"], technician["id"],
                                     "2026-06-03T10:00:01Z", "2026-06-03T11:00:00Z"),
        COORDINATOR), 201)
    assert visit["status"] == "BOOKED"
    assert get_service_plan(plan["id"])["visits_booked"] == 2


def test_technician_day_capacity_fifth_visit_rejected(api):
    """PRD §3.7: "And no technician may hold more than four `BOOKED` visits on the same UTC
    calendar day (`ERR_TECHNICIAN_DAY_CAPACITY_REACHED`)."
    (Four non-overlapping visits on 2026-06-12 are admitted; the fifth fails even though the
    PREMIUM plan still has credits.)

    Design: Corner/validations/technician_day_capacity_fifth_visit_rejected
    """
    customer, instrument, order = setup_installed_order(
        serial_number="SN-DC-1", job_window=("2026-05-08T09:00:00Z", "2026-05-08T11:00:00Z"))
    plan = create_service_plan(order["id"], "PREMIUM")
    technician = create_technician(full_name="Max Booked", certification_level="MASTER")
    for start, end in [("08:00", "09:00"), ("09:01", "10:00"),
                       ("10:01", "11:00"), ("11:01", "12:00")]:
        book_visit(plan["id"], technician["id"],
                   f"2026-06-12T{start}:00Z", f"2026-06-12T{end}:00Z")

    res = api.create_service_visit(
        create_service_visit_payload(plan["id"], technician["id"],
                                     "2026-06-12T12:01:00Z", "2026-06-12T13:00:00Z"),
        COORDINATOR)
    validate_error(res, "ERR_TECHNICIAN_DAY_CAPACITY_REACHED")
    assert get_service_plan(plan["id"])["visits_booked"] == 4, (
        "rejected booking must not consume a credit")


def test_service_plan_loyalty_discount_on_second_plan(api):
    """PRD §3.7: "Loyalty is rewarded: when the same customer already holds any other plan
    in `EXHAUSTED` or `CANCELLED`, the new plan's price is the tier price reduced by ten
    percent, rounded half-up to whole cents."
    PRD §3.7: "The plan's `price_cents` and `visits_total` come from the tier: `BASIC` costs
    30,000 cents and carries 2 visits, `STANDARD` costs 55,000 cents with 4 visits, and
    `PREMIUM` costs 85,000 cents with 6 visits."
    (First BASIC 30000 full price; second STANDARD round(55000 * 0.90) == 49500.)

    Design: Corner/calculations/service_plan_loyalty_discount_on_second_plan
    """
    customer, instrument, order = setup_installed_order(
        serial_number="SN-LY-1", job_window=("2026-05-07T09:00:00Z", "2026-05-07T11:00:00Z"))
    first = create_service_plan(order["id"], "BASIC")
    assert first["price_cents"] == 30_000, "no loyalty on the first plan"
    validate_success(api.cancel_service_plan(first["id"], COORDINATOR), 200)

    second = create_service_plan(order["id"], "STANDARD")
    assert second["price_cents"] == 49_500, (
        f"prior CANCELLED plan earns 10% loyalty, got {second['price_cents']}")
