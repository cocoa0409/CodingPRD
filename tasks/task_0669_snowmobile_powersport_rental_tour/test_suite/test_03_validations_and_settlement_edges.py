"""Remaining validation error triggers, fuel/no-show calculation edges, the OCC
happy-path and stale-version rejection, FK reverse-reachability, and immediate
cascade visibility. Corner sections: validations, calculations, errors,
cross_cutting_complexity_layers, consistency_model."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, TEST_USERS,
    create_trail, create_unit, create_guide, create_departure,
    register_member, register_signed_member, train_member,
    create_reservation, create_and_confirm_reservation, confirm_reservation,
    assign_guide, lock_departure, set_clock,
    setup_checked_out_reservation, setup_confirmed_reservation,
    read_member, read_reservation, read_departure,
    make_member_headers,
    assert_settlement,
)

DISPATCH = TEST_USERS["dispatch_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ===================================================================
# validations
# ===================================================================

def test_confirm_underage_rider_returns_rider_underage(api):
    """PRD §3.5: "The age gate requires the member's age, computed at the departure's
    `starts_at` instant, to be at least the minimum riding age of 16 years; a younger
    rider is rejected with `ERR_RIDER_UNDERAGE`."

    Design: Corner/validations/confirm_underage_rider_returns_rider_underage
    """
    trail = create_trail(name="AgeT", required_class="TRAIL", max_riders=10)
    unit = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    dep = create_departure(trail["id"], starts_at="2027-02-19T09:00:00Z",
                           ends_at="2027-02-19T12:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    # Born 2012-01-01 -> age 15 at departure start; guardian-signed waiver so waiver gate passes.
    member = register_member(date_of_birth="2012-01-01")
    get_success_data(api.sign_waiver(member["id"], {"guardian_ack": True}, make_member_headers(member["id"])))
    res = create_reservation(member, dep["id"], unit["id"])
    resp = api.confirm_reservation(res["id"], {"expected_tour_departure_version": dep["version"]},
                                   make_member_headers(member["id"]))
    validate_error(resp, "ERR_RIDER_UNDERAGE", expected_status=409)


def test_confirm_unit_class_below_trail_returns_unit_class_too_low(api):
    """PRD §3.5: "The class gate requires the unit's `unit_class` rank to be at least the
    trail's `required_class` rank — the sled must be capable of the route — and a sled
    that ranks below the trail is rejected with `ERR_UNIT_CLASS_TOO_LOW`."

    Design: Corner/validations/confirm_unit_class_below_trail_returns_unit_class_too_low
    """
    trail = create_trail(name="HighT", required_class="MOUNTAIN", max_riders=8)
    unit = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    dep = create_departure(trail["id"], starts_at="2027-02-21T09:00:00Z",
                           ends_at="2027-02-21T15:00:00Z", required_guide_class="MOUNTAIN", capacity_riders=8)
    member = register_signed_member()
    # ADVANCED training so the training gate (which fires before the class gate) does not pre-empt.
    train_member(member["id"], "BASIC")
    train_member(member["id"], "ADVANCED")
    res = create_reservation(member, dep["id"], unit["id"])
    resp = api.confirm_reservation(res["id"], {"expected_tour_departure_version": dep["version"]},
                                   make_member_headers(member["id"]))
    validate_error(resp, "ERR_UNIT_CLASS_TOO_LOW", expected_status=409)


def test_assign_guide_class_too_low_returns_guide_class_too_low(api):
    """PRD §3.3: "this is allowed only when the guide's `max_class` rank is at least the
    departure's `required_guide_class` rank, failing which the assignment is rejected with
    `ERR_GUIDE_CLASS_TOO_LOW`."

    Design: Corner/validations/assign_guide_class_too_low_returns_guide_class_too_low
    """
    trail = create_trail(name="GcT", required_class="MOUNTAIN", max_riders=8)
    guide = create_guide(max_class="TRAIL")
    dep = create_departure(trail["id"], starts_at="2027-02-23T09:00:00Z",
                           ends_at="2027-02-23T15:00:00Z", required_guide_class="MOUNTAIN", capacity_riders=8)
    resp = api.assign_guide(dep["id"], {"guide_id": guide["id"]}, DISPATCH)
    validate_error(resp, "ERR_GUIDE_CLASS_TOO_LOW", expected_status=409)
    assert read_departure(dep["id"])["guide_count"] == 0


def test_lock_without_guides_returns_guide_ratio_unmet(api):
    """PRD §3.3: "the departure must already carry at least one confirmed rider, and its
    `guide_count` must meet or exceed the required-guide count derived from the ratio
    above; a lock that has too few guides for its riders, or that has no riders at all, is
    rejected with `ERR_GUIDE_RATIO_UNMET`."

    Design: Corner/validations/lock_without_guides_returns_guide_ratio_unmet
    """
    trail = create_trail(name="RatT", required_class="TRAIL", max_riders=10)
    unit = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    dep = create_departure(trail["id"], starts_at="2027-02-25T09:00:00Z",
                           ends_at="2027-02-25T12:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    member = register_signed_member()
    create_and_confirm_reservation(member, dep["id"], unit["id"], expected_version=dep["version"])
    resp = api.lock_departure(dep["id"], DISPATCH)  # rider_count 1, guide_count 0
    validate_error(resp, "ERR_GUIDE_RATIO_UNMET", expected_status=409)
    assert read_departure(dep["id"])["status"] == "SCHEDULED"


def test_assign_guide_double_booked_returns_guide_double_booked(api):
    """PRD §3.3: "A guide also may not be assigned to a departure whose window overlaps a
    departure they are already actively assigned to: if the guide has any other active
    assignment whose departure window, taken as the half-open interval from `starts_at` up
    to but not including `ends_at`, overlaps this departure's window, the assignment is
    rejected with `ERR_GUIDE_DOUBLE_BOOKED`."

    Design: Corner/validations/assign_guide_double_booked_returns_guide_double_booked
    """
    trail = create_trail(name="GdbT", required_class="TRAIL", max_riders=10)
    guide = create_guide(max_class="TRAIL")
    d1 = create_departure(trail["id"], starts_at="2027-02-27T09:00:00Z",
                          ends_at="2027-02-27T17:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    d2 = create_departure(trail["id"], starts_at="2027-02-27T12:00:00Z",
                          ends_at="2027-02-27T20:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    assign_guide(d1["id"], guide["id"])
    resp = api.assign_guide(d2["id"], {"guide_id": guide["id"]}, DISPATCH)
    validate_error(resp, "ERR_GUIDE_DOUBLE_BOOKED", expected_status=409)
    assert read_departure(d2["id"])["guide_count"] == 0


def test_return_without_fuel_fraction_returns_fuel_required(api):
    """PRD §3.9: "A return missing a valid `fuel_return_fraction` in the range from 0 to 1
    is rejected with `ERR_FUEL_FRACTION_REQUIRED`."

    Design: Corner/validations/return_without_fuel_fraction_returns_fuel_required
    """
    bundle = setup_checked_out_reservation(
        trail_overrides={"name": "NfT", "required_class": "TRAIL", "max_riders": 10},
        unit_overrides={"unit_class": "TRAIL", "daily_rate_cents": 5000,
                        "deposit_cents": 25000, "tank_capacity_liters": 30},
        departure_overrides={"starts_at": "2027-03-01T09:00:00Z", "ends_at": "2027-03-01T12:00:00Z",
                             "required_guide_class": "TRAIL", "capacity_riders": 10},
        depart_clock="2027-03-01T09:30:00Z")
    resp = api.return_reservation(bundle["reservation"]["id"], {}, DISPATCH)
    validate_error(resp, "ERR_FUEL_FRACTION_REQUIRED", expected_status=422)


# ===================================================================
# calculations
# ===================================================================

def test_fuel_charge_zero_at_ok_fraction_boundary(api):
    """PRD §3.9: "there is no charge when the returned fuel fraction is at or above the
    full-tank threshold of 0.95, so a shortfall is billed only when `fuel_return_fraction`
    is strictly below 0.95."

    Design: Corner/calculations/fuel_charge_at_ok_fraction_boundary_zero
    """
    bundle = setup_checked_out_reservation(
        trail_overrides={"name": "FuelT", "required_class": "TRAIL", "max_riders": 10},
        unit_overrides={"unit_class": "TRAIL", "daily_rate_cents": 5000,
                        "deposit_cents": 25000, "tank_capacity_liters": 40},
        departure_overrides={"starts_at": "2027-02-15T09:00:00Z", "ends_at": "2027-02-15T17:00:00Z",
                             "required_guide_class": "TRAIL", "capacity_riders": 10},
        depart_clock="2027-02-15T09:30:00Z")
    set_clock("2027-02-15T16:50:00Z")  # before ends_at -> not late
    settle = validate_success(
        api.return_reservation(bundle["reservation"]["id"], {"fuel_return_fraction": 0.95}, DISPATCH), 200)
    assert settle["fuel_charge_cents"] == 0  # exactly at threshold -> free
    assert settle["late_charge_cents"] == 0


def test_no_show_charges_fixed_fee_refunds_deposit(api):
    """PRD §3.9: "A `Settlement` is created in which the `rental_charge_cents` is a flat
    no-show fee of 5000 cents ... The no-show fee does not consume the deposit: the
    `deposit_applied_cents` is zero, the full held deposit is returned as `refund_cents`,
    and the `net_charge_cents` equals the 5000-cent fee."

    Design: Corner/calculations/no_show_charges_fixed_fee_refunds_deposit
    """
    trail = create_trail(name="NsT", required_class="TRAIL", max_riders=10)
    unit = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    guide = create_guide(max_class="TRAIL")
    dep = create_departure(trail["id"], starts_at="2027-02-17T09:00:00Z",
                           ends_at="2027-02-17T12:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    member = register_signed_member()
    confirmed = create_and_confirm_reservation(member, dep["id"], unit["id"], expected_version=dep["version"])
    res_id = confirmed["id"]
    assign_guide(dep["id"], guide["id"])
    lock_departure(dep["id"])
    settle = validate_success(api.no_show_reservation(res_id, DISPATCH), 200)
    assert_settlement(settle)
    assert settle["rental_charge_cents"] == 5000
    assert settle["deposit_applied_cents"] == 0
    assert settle["refund_cents"] == 25000
    assert settle["net_charge_cents"] == 5000
    assert read_reservation(res_id)["reservation_status"] == "NO_SHOW"
    assert read_departure(dep["id"])["rider_count"] == 0


# ===================================================================
# errors (OCC stale version)
# ===================================================================

def test_confirm_stale_departure_version_returns_stale_version(api):
    """PRD §2.6: "If another writer has advanced the departure's version since the client
    last read it — most commonly because a different rider has already confirmed onto the
    same departure ... — then the client's view of the remaining capacity is stale and the
    confirm is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/confirm_stale_departure_version_returns_stale_version
    """
    trail = create_trail(name="OccT", required_class="TRAIL", max_riders=10)
    unit_b = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    unit_a = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    dep = create_departure(trail["id"], starts_at="2027-03-07T09:00:00Z",
                           ends_at="2027-03-07T12:00:00Z", required_guide_class="TRAIL", capacity_riders=5)
    dep_ver0 = dep["version"]
    mem_b = register_signed_member()
    res_b = create_reservation(mem_b, dep["id"], unit_b["id"])
    mem_a = register_signed_member()
    res_a = create_reservation(mem_a, dep["id"], unit_a["id"])
    # B confirms first -> departure version advances past dep_ver0.
    confirm_reservation(res_b["id"], mem_b["id"], dep_ver0)
    # A confirms carrying the stale pre-advance version.
    resp = api.confirm_reservation(res_a["id"], {"expected_tour_departure_version": dep_ver0},
                                   make_member_headers(mem_a["id"]))
    validate_error(resp, "ERR_STALE_VERSION", expected_status=412)
    assert read_reservation(res_a["id"])["reservation_status"] == "PENDING"


# ===================================================================
# cross_cutting_complexity_layers
# ===================================================================

def test_confirm_increments_departure_version_occ_happy_path(api):
    """PRD §3.4: "the departure's `rider_count` is incremented by one and its `version` is
    incremented by one".
    PRD §2.4: "The `version` is an integer that begins at 1 on creation and increments by
    one on every mutation".

    Design: Corner/cross_cutting_complexity_layers/confirm_increments_departure_version_occ_happy_path
    """
    trail = create_trail(name="VerT", required_class="TRAIL", max_riders=10)
    unit = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    dep = create_departure(trail["id"], starts_at="2027-03-11T09:00:00Z",
                           ends_at="2027-03-11T12:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    assert dep["version"] == 1
    member = register_signed_member()
    confirmed = create_and_confirm_reservation(member, dep["id"], unit["id"], expected_version=dep["version"])
    assert confirmed["reservation_status"] == "CONFIRMED"
    dep_after = read_departure(dep["id"])
    assert dep_after["version"] == 2
    assert dep_after["rider_count"] == 1


def test_fk_reverse_reachability_trail_closures_list(api):
    """PRD §3.7: "Every such posting records a `ClosureEvent` capturing the `trail_id`,
    the `new_condition`, the `reason`, and a `cancelled_departure_count`."
    PRD §2.10: "with reverse-reachability list endpoints hanging off a parent identifier".

    Design: Corner/cross_cutting_complexity_layers/fk_reverse_reachability_trail_closures_list
    """
    trail = create_trail(name="FkT", required_class="TRAIL", max_riders=10)
    get_success_data(api.post_closure(trail["id"], {"new_condition": "CAUTION", "reason": "fog"}, DISPATCH))
    data, meta = validate_paginated(api.list_trail_closures(trail["id"], DISPATCH))
    assert meta["total_count"] == 1
    assert data[0]["new_condition"] == "CAUTION"


# ===================================================================
# consistency_model
# ===================================================================

def test_immediate_cascade_visible_in_same_request_and_followup(api):
    """PRD §2.5: "The system holds itself to immediate, atomic consistency: when one
    operation triggers a cascade, every downstream effect resolves before the triggering
    request returns."
    PRD §3.6: "every reservation on it that is `PENDING` or `CONFIRMED` is moved to
    `CANCELLED` ... and — if that reservation's `settlement_status` is `HELD` — the
    deposit is fully refunded by moving its billing state from `HELD` to `REFUNDED`".

    Design: Corner/consistency_model/immediate_cascade_visible_in_same_request_response
    """
    bundle = setup_confirmed_reservation(
        trail_overrides={"name": "ImmT", "required_class": "TRAIL", "max_riders": 10},
        unit_overrides={"unit_class": "TRAIL", "daily_rate_cents": 5000,
                        "deposit_cents": 25000, "tank_capacity_liters": 30},
        departure_overrides={"starts_at": "2027-03-13T09:00:00Z", "ends_at": "2027-03-13T12:00:00Z",
                             "required_guide_class": "TRAIL", "capacity_riders": 10},
        member_overrides=None)
    cancelled = validate_success(api.cancel_departure(bundle["departure"]["id"], DISPATCH), 200)
    assert cancelled["status"] == "CANCELLED"  # already terminal in the same response
    res_after = read_reservation(bundle["reservation"]["id"])
    assert res_after["reservation_status"] == "CANCELLED"
    assert res_after["settlement_status"] == "REFUNDED"
    assert read_member(bundle["member"]["id"])["deposit_hold_cents"] == 0
