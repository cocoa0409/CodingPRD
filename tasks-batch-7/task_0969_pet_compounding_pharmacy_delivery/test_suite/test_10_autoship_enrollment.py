"""Auto-ship schedules, wellness enrollment lifecycle, and pet-death cascades."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId,
    create_owner, create_pet, create_wellness_plan, create_lot, create_bench,
    create_compound_order, create_enrollment_for_pet, create_schedule_for_rx,
    fetch_enrollment, fetch_schedule, fetch_prescription,
    setup_verified_scenario, order_to_dispensed, list_orders_for_prescription,
    TEST_USERS, make_owner_headers,
)


def test_autoship_run_fires_only_when_due(api):
    """PRD §3.8: "The auto-ship run fires every schedule whose `next_run_date`
    falls on or before the current clock date while `ACTIVE`"
    PRD §3.8: "each due schedule creates a refill compound order under exactly the
    same rules as a manual refill creation — including the deceased-pet,
    refills-remaining, and refill-timing gates — and on success advances
    `next_run_date` by `interval_days`, resets `consecutive_failures`, and records
    `last_fired_at`"
    A run at 2026-05-19 (next_run 2026-05-20) creates nothing; a run at 2026-05-20
    creates the refill (fill_number 2) and advances next_run_date to 2026-06-09.

    Design: Corner/cross_cutting_complexity_layers/autoship_run_fires_only_when_due
    """
    scn = setup_verified_scenario(pet_weight_kg=6, quantity=10, days_supply=20,
                                  refills_authorized=2)
    create_lot(scn["drug"]["id"], received_qty=100)
    bench = create_bench()
    order_to_dispensed(scn["rx"]["id"], bench["id"])
    schedule = create_schedule_for_rx(scn["rx"]["id"], scn["owner"]["id"],
                                      interval_days=20, next_run_date="2026-05-20")
    admin = TEST_USERS["pharmacy_admin_headers"]
    get_success_data(api_client.set_clock("2026-05-19T00:00:00Z", admin))
    get_success_data(api_client.run_auto_ship(admin))
    assert len(list_orders_for_prescription(scn["rx"]["id"])) == 1, (
        "run before next_run_date must create nothing")
    get_success_data(api_client.set_clock("2026-05-20T00:00:00Z", admin))
    get_success_data(api_client.run_auto_ship(admin))
    orders = list_orders_for_prescription(scn["rx"]["id"])
    assert len(orders) == 2
    refill = [o for o in orders if o["is_refill"]]
    assert len(refill) == 1 and refill[0]["fill_number"] == 2
    sch = fetch_schedule(schedule["id"], scn["owner"]["id"])
    assert sch["next_run_date"] == "2026-06-09", (
        f"next_run_date expected 2026-06-09, got {sch['next_run_date']}")
    assert sch["last_fired_at"] is not None
    assert sch["consecutive_failures"] == 0


def test_autoship_supersede_with_fresh_version(api):
    """PRD §3.8: "The new schedule supersedes any existing `ACTIVE` schedule on the
    same prescription, which moves to `CANCELLED`; the prescription's `version`
    increments."

    Design: Corner/cross_cutting_complexity_layers/autoship_supersede_with_fresh_version
    """
    scn = setup_verified_scenario(pet_weight_kg=6, quantity=5, days_supply=5,
                                  refills_authorized=3)
    sch1 = create_schedule_for_rx(scn["rx"]["id"], scn["owner"]["id"],
                                  interval_days=10, next_run_date="2026-06-01")
    sch2 = create_schedule_for_rx(scn["rx"]["id"], scn["owner"]["id"],
                                  interval_days=7, next_run_date="2026-05-15")
    assert fetch_schedule(sch1["id"], scn["owner"]["id"])["status"] == "CANCELLED"
    sch2_after = fetch_schedule(sch2["id"], scn["owner"]["id"])
    assert sch2_after["status"] == "ACTIVE"
    assert sch2_after["interval_days"] == 7


def test_autoship_resume_after_cancel_invalid(api):
    """PRD §3.8: "The owner may pause an `ACTIVE` schedule, resume a `PAUSED` one,
    or cancel either"
    PRD §2.9: "the generic from-state check rejects transitions invoked on a
    resource not in a permitted source state — and any further transition on a
    terminal-state resource — with `ERR_INVALID_STATE`"
    A CANCELLED schedule is terminal: resume fails.

    Design: Corner/state_machines/autoship_resume_after_cancel_invalid
    """
    scn = setup_verified_scenario(pet_weight_kg=6, quantity=10, days_supply=10,
                                  refills_authorized=3)
    schedule = create_schedule_for_rx(scn["rx"]["id"], scn["owner"]["id"],
                                      interval_days=10, next_run_date="2026-06-01")
    get_success_data(api_client.cancel_auto_ship(schedule["id"],
                                                 make_owner_headers(scn["owner"]["id"])))
    res = api_client.resume_auto_ship(schedule["id"], make_owner_headers(scn["owner"]["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert fetch_schedule(schedule["id"], scn["owner"]["id"])["status"] == "CANCELLED"


def test_enrollment_suspend_resume_cycle(api):
    """PRD §3.6: "The owner (or an admin) may suspend an `ACTIVE` enrollment,
    resume a `SUSPENDED` one, or cancel either"
    The ACTIVE -> SUSPENDED -> ACTIVE cycle works and credits are preserved.

    Design: Corner/state_machines/enrollment_suspend_resume_cycle
    """
    owner = create_owner()
    pet = create_pet(owner["id"], species="CAT", weight_kg=4)
    plan = create_wellness_plan(name="PlanS7", monthly_fee_cents=2000,
                                included_refill_credits=5, credit_value_cents=2000,
                                discount_pct=0, covers_controlled=False)
    enrollment = create_enrollment_for_pet(pet["id"], plan["id"], owner["id"])
    headers = make_owner_headers(owner["id"])
    get_success_data(api_client.suspend_enrollment(enrollment["id"], headers))
    resumed = get_success_data(api_client.resume_enrollment(enrollment["id"], headers))
    assert resumed["status"] == "ACTIVE"
    assert resumed["credits_remaining"] == 5


def test_enrollment_supersede_cancels_prior(api):
    """PRD §3.6: "The new enrollment supersedes that pet's existing `ACTIVE` or
    `SUSPENDED` enrollment, which moves to `CANCELLED`; the new enrollment's
    `credits_remaining` initializes to the plan's `included_refill_credits`"

    Design: Corner/state_machines/enrollment_supersede_cancels_prior
    """
    owner = create_owner()
    pet = create_pet(owner["id"], species="DOG", weight_kg=6)
    plan_a = create_wellness_plan(name="PlanS9a", monthly_fee_cents=2000,
                                  included_refill_credits=3, credit_value_cents=1500,
                                  discount_pct=0, covers_controlled=False)
    plan_b = create_wellness_plan(name="PlanS9b", monthly_fee_cents=4000,
                                  included_refill_credits=6, credit_value_cents=1500,
                                  discount_pct=0.1, covers_controlled=False)
    enr1 = create_enrollment_for_pet(pet["id"], plan_a["id"], owner["id"])
    enr2 = create_enrollment_for_pet(pet["id"], plan_b["id"], owner["id"])
    assert fetch_enrollment(enr1["id"], owner["id"])["status"] == "CANCELLED"
    enr2_after = fetch_enrollment(enr2["id"], owner["id"])
    assert enr2_after["status"] == "ACTIVE"
    assert enr2_after["credits_remaining"] == 6


def test_pet_deceased_cascades_and_blocks_refill(api):
    """PRD §3.1: "the system cancels every auto-ship schedule in `ACTIVE` or
    `PAUSED` status on that pet's prescriptions"
    PRD §3.4: "The pet must be `ALIVE`, otherwise `ERR_PET_DECEASED`."

    Design: Corner/state_machines/pet_deceased_cascades_and_blocks_refill
    """
    scn = setup_verified_scenario(pet_weight_kg=6, quantity=10, days_supply=10,
                                  refills_authorized=1)
    schedule = create_schedule_for_rx(scn["rx"]["id"], scn["owner"]["id"],
                                      interval_days=10, next_run_date="2026-06-01")
    get_success_data(api_client.update_pet(scn["pet"]["id"], {"status": "DECEASED"},
                                           make_owner_headers(scn["owner"]["id"])))
    assert fetch_schedule(schedule["id"], scn["owner"]["id"])["status"] == "CANCELLED"
    res = api_client.create_compound_order(
        scn["rx"]["id"],
        {"is_refill": True,
         "expected_prescription_version": fetch_prescription(scn["rx"]["id"])["version"]},
        TEST_USERS["pharmacy_tech_headers"])
    validate_error(res, ApiErrorId.ERR_PET_DECEASED)


def test_occ_autoship_stale_version_rejected(api):
    """PRD §2.7: "Creating an auto-ship schedule requires
    `expected_prescription_version` for the same reason — a new schedule
    legitimately supersedes the existing `ACTIVE` one for that prescription — and a
    mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_autoship_stale_version_rejected
    """
    scn = setup_verified_scenario(pet_weight_kg=4, pet_species="CAT", quantity=5,
                                  days_supply=5, refills_authorized=2)
    headers = make_owner_headers(scn["owner"]["id"])
    first = api_client.create_auto_ship_schedule(
        {"prescription_id": scn["rx"]["id"], "interval_days": 10,
         "next_run_date": "2026-06-01",
         "expected_prescription_version": scn["rx_version"]}, headers)
    sch1 = validate_success(first, 201)
    stale = api_client.create_auto_ship_schedule(
        {"prescription_id": scn["rx"]["id"], "interval_days": 20,
         "next_run_date": "2026-06-11",
         "expected_prescription_version": scn["rx_version"]}, headers)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    data, meta = validate_paginated(api_client.list_auto_ship_schedules(
        headers, params={"prescription_id": scn["rx"]["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == sch1["id"]


def test_occ_enrollment_stale_version_rejected(api):
    """PRD §2.7: "Creating a wellness enrollment requires `expected_owner_version`;
    a new enrollment for a pet legitimately supersedes that pet's existing
    enrollment, so a stale owner view is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_enrollment_stale_version_rejected
    """
    owner = create_owner()
    pet1 = create_pet(owner["id"], name="One", species="DOG", weight_kg=6)
    pet2 = create_pet(owner["id"], name="Two", species="CAT", weight_kg=4)
    plan = create_wellness_plan(name="PlanL4", monthly_fee_cents=2000,
                                included_refill_credits=3, credit_value_cents=1500,
                                discount_pct=0, covers_controlled=False)
    headers = make_owner_headers(owner["id"])
    first = api_client.create_enrollment(
        {"pet_id": pet1["id"], "plan_id": plan["id"],
         "expected_owner_version": owner["version"]}, headers)
    validate_success(first, 201)
    stale = api_client.create_enrollment(
        {"pet_id": pet2["id"], "plan_id": plan["id"],
         "expected_owner_version": owner["version"]}, headers)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    data, meta = validate_paginated(api_client.list_enrollments(
        headers, params={"owner_id": owner["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["pet_id"] == pet1["id"]
