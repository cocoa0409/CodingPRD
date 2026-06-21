"""Validation ordering, priority-pair conflicts, cross-entity state guards, and
temporal-overlap (unit double-booking + buffered truck windows).

Covers difficulty rules priority_pair_validation_conflict,
cross_entity_state_dependency, resource_temporal_overlap, plus the corner
validations instances.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_yard, create_reservation, setup_out_of_service_unit,
    setup_dispatched_delivery, setup_returned_pending_inspection,
    pull_unit_out_of_service, set_clock, TEST_USERS,
)

YM = TEST_USERS["yard_manager_headers"]
AGENT = TEST_USERS["rental_agent_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


def _reservation_body(account_id, item_id, unit_id=None, **kw):
    body = {
        "contractor_account_id": account_id,
        "catalog_item_id": item_id,
        "fulfillment_method": "PICKUP",
        "rental_start_date": "2026-06-01",
        "rental_end_date": "2026-06-10",
        "damage_waiver_opted": False,
    }
    if unit_id is not None:
        body["equipment_unit_id"] = unit_id
    body.update(kw)
    return body


# ─── priority_pair_validation_conflict ───────────────────────────

def test_unit_not_available_beats_credit_limit(api):
    """PRD §3.4: "Next comes unit availability: the chosen EquipmentUnit must not
    be OUT_OF_SERVICE, since a unit pulled for maintenance cannot accept new
    bookings; a violation is ERR_UNIT_NOT_AVAILABLE (HTTP 409). ... Finally the
    credit projection described below, rejected with ERR_CREDIT_LIMIT_EXCEEDED
    (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/unit_not_available_beats_credit_limit_on_reservation
    """
    ctx = setup_out_of_service_unit(account_overrides={"credit_limit_cents": 1})
    res = api.create_reservation(
        _reservation_body(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                          rental_end_date="2026-06-03"),
        AGENT)
    validate_error(res, "ERR_UNIT_NOT_AVAILABLE")


def test_credit_limit_loser_fires_alone_when_unit_available(api):
    """PRD §3.4: "Finally the credit projection described below, rejected with
    ERR_CREDIT_LIMIT_EXCEEDED (HTTP 422)."
    PRD §3.4: "The server computes a would-be balance as the account's current
    outstanding_balance_cents plus the rate card's deposit_cents plus the
    reservation's estimated_total_cents, and rejects the reservation when that
    projected balance would exceed the account's credit_limit_cents".

    Design: Difficulty/priority_pair_validation_conflict/unit_not_available_beats_credit_limit_on_reservation
    """
    # Same too-low credit limit, but the unit is AVAILABLE: the higher-priority
    # unit-state check no longer fires, so the credit projection (the loser) does.
    ctx = setup_yard(account_overrides={"credit_limit_cents": 1})
    res = api.create_reservation(
        _reservation_body(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                          rental_end_date="2026-06-03"),
        AGENT)
    validate_error(res, "ERR_CREDIT_LIMIT_EXCEEDED")


def test_double_booked_beats_account_suspended(api):
    """PRD §3.4: "Then the temporal-overlap check: no other active reservation or
    agreement on the same EquipmentUnit may overlap the requested inclusive
    [rental_start_date, rental_end_date] interval ... a true overlap is rejected
    with ERR_UNIT_DOUBLE_BOOKED (HTTP 409). ... Then account standing: the
    ContractorAccount must be ACTIVE, with a SUSPENDED account rejected by
    ERR_ACCOUNT_SUSPENDED (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/double_booked_beats_account_suspended_on_reservation
    """
    ctx = setup_yard()
    create_reservation(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                       rental_start_date="2026-06-01", rental_end_date="2026-06-10")
    acct2 = validate_success(api.create_contractor_account(
        {"company_name": "Beta", "credit_limit_cents": 1_000_000}, YM), 201)
    validate_success(api.suspend_account(acct2["id"], YM), 200)
    res = api.create_reservation(
        _reservation_body(acct2["id"], ctx["item"]["id"], ctx["unit"]["id"],
                          rental_start_date="2026-06-05", rental_end_date="2026-06-08"),
        AGENT)
    validate_error(res, "ERR_UNIT_DOUBLE_BOOKED")


def test_account_suspended_loser_fires_alone_when_no_overlap(api):
    """PRD §3.4: "Then account standing: the ContractorAccount must be ACTIVE,
    with a SUSPENDED account rejected by ERR_ACCOUNT_SUSPENDED (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/double_booked_beats_account_suspended_on_reservation
    """
    # Same SUSPENDED account, but no overlapping booking on the unit: the
    # higher-priority double-booking check no longer fires, so the suspended-account
    # check (the loser) surfaces.
    ctx = setup_yard()
    acct2 = validate_success(api.create_contractor_account(
        {"company_name": "Beta", "credit_limit_cents": 1_000_000}, YM), 201)
    validate_success(api.suspend_account(acct2["id"], YM), 200)
    res = api.create_reservation(
        _reservation_body(acct2["id"], ctx["item"]["id"], ctx["unit"]["id"],
                          rental_start_date="2026-06-05", rental_end_date="2026-06-08"),
        AGENT)
    validate_error(res, "ERR_ACCOUNT_SUSPENDED")


# ─── cross_entity_state_dependency ───────────────────────────────

def test_reservation_blocked_when_account_suspended(api):
    """PRD §3.4: "Then account standing: the ContractorAccount must be ACTIVE,
    with a SUSPENDED account rejected by ERR_ACCOUNT_SUSPENDED (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/reservation_blocked_when_contractor_account_suspended
    """
    ctx = setup_yard()
    validate_success(api.suspend_account(ctx["account"]["id"], YM), 200)
    res = api.create_reservation(
        _reservation_body(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"]),
        AGENT)
    validate_error(res, "ERR_ACCOUNT_SUSPENDED")
    unit = validate_success(api.get_equipment_unit(ctx["unit"]["id"], YM), 200)
    assert unit["availability_state"] == "AVAILABLE"


def test_reservation_allowed_when_account_active(api):
    """PRD §3.4: "Then account standing: the ContractorAccount must be ACTIVE,
    with a SUSPENDED account rejected by ERR_ACCOUNT_SUSPENDED (HTTP 409)."
    PRD §3.4: "On confirmation the reservation enters the CONFIRMED state".

    Design: Difficulty/cross_entity_state_dependency/reservation_blocked_when_contractor_account_suspended
    """
    # Complement: the referenced account is ACTIVE, so the cross-entity status
    # guard passes and the reservation reaches CONFIRMED.
    ctx = setup_yard()
    res = api.create_reservation(
        _reservation_body(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"]),
        AGENT)
    reservation = validate_success(res, 201)
    assert reservation["reservation_state"] == "CONFIRMED"


def test_inspection_blocked_unless_agreement_returned_pending(api):
    """PRD §3.6: "an Inspector records a ReturnInspection against the agreement's
    rental_agreement_id, which must be in RETURNED_PENDING_INSPECTION".
    PRD §2.10: "a second dispatch, pickup, cancel, return, or inspection on a
    resource whose state has already advanced is rejected by the state precondition".

    Design: Difficulty/cross_entity_state_dependency/inspection_blocked_unless_agreement_returned_pending
    """
    from test_helpers import setup_picked_up_agreement
    ctx = setup_picked_up_agreement(reservation_overrides={
        "rental_start_date": "2026-06-01", "rental_end_date": "2026-06-10"})
    # Agreement is still ON_RENT (not yet returned).
    res = api.create_return_inspection({
        "rental_agreement_id": ctx["agreement"]["id"],
        "return_fuel_level_liters": 40,
        "cleanliness": "CLEAN",
        "damage_assessed_cents": 0,
    }, INSPECTOR)
    validate_error(res, "ERR_INVALID_STATE")


def test_inspection_allowed_when_agreement_returned_pending(api):
    """PRD §3.6: "an Inspector records a ReturnInspection against the agreement's
    rental_agreement_id, which must be in RETURNED_PENDING_INSPECTION".
    PRD §3.6: "When the inspection yields no net damage, the agreement moves
    RETURNED_PENDING_INSPECTION → CLOSED."

    Design: Difficulty/cross_entity_state_dependency/inspection_blocked_unless_agreement_returned_pending
    """
    # Complement: the agreement IS in RETURNED_PENDING_INSPECTION, so the inspection
    # is accepted and closes the agreement.
    ctx = setup_returned_pending_inspection(reservation_overrides={
        "rental_start_date": "2026-06-01", "rental_end_date": "2026-06-10"})
    res = api.create_return_inspection({
        "rental_agreement_id": ctx["agreement"]["id"],
        "return_fuel_level_liters": 40,
        "cleanliness": "CLEAN",
        "damage_assessed_cents": 0,
    }, INSPECTOR)
    validate_success(res, 201)
    ag = validate_success(
        api.get_rental_agreement(ctx["agreement"]["id"], YM), 200)
    assert ag["agreement_state"] == "CLOSED"


# ─── resource_temporal_overlap ───────────────────────────────────

def test_unit_overlap_inside_closed_interval_rejected(api):
    """PRD §3.4: "no other active reservation or agreement on the same
    EquipmentUnit may overlap the requested inclusive
    [rental_start_date, rental_end_date] interval; this is a closed-interval test
    in which adjacency is not overlap, so one booking ending on the very day
    another begins is allowed, and a true overlap is rejected with
    ERR_UNIT_DOUBLE_BOOKED (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/equipment_unit_overlap_closed_interval_adjacency_allowed
    """
    ctx = setup_yard()
    create_reservation(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                       rental_start_date="2026-06-01", rental_end_date="2026-06-10")
    res = api.create_reservation(
        _reservation_body(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                          rental_start_date="2026-06-09", rental_end_date="2026-06-15"),
        AGENT)
    validate_error(res, "ERR_UNIT_DOUBLE_BOOKED")


def test_unit_adjacency_at_interval_boundary_allowed(api):
    """PRD §3.4: "this is a closed-interval test in which adjacency is not overlap,
    so one booking ending on the very day another begins is allowed".

    Design: Difficulty/resource_temporal_overlap/equipment_unit_overlap_closed_interval_adjacency_allowed
    """
    ctx = setup_yard()
    create_reservation(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                       rental_start_date="2026-06-01", rental_end_date="2026-06-10")
    res = api.create_reservation(
        _reservation_body(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                          rental_start_date="2026-06-10", rental_end_date="2026-06-15"),
        AGENT)
    # Second booking starts exactly on the first's end day => adjacency, allowed.
    second = validate_success(res, 201)
    assert second["reservation_state"] == "CONFIRMED"


def test_truck_buffered_window_overlap_rejected(api):
    """PRD §3.5: "The window is checked against the truck's existing commitments
    using half-open interval semantics expanded by the truck's buffer_minutes on
    each side: the requested [delivery_window_start, delivery_window_end) interval,
    padded by buffer_minutes before and after, must not collide with any other
    assigned window on the same truck — adjacency within the buffer counts as a
    collision. A collision is rejected with ERR_TRUCK_DOUBLE_BOOKED (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/delivery_truck_overlap_buffered_half_open_interval
    """
    ctx = setup_dispatched_delivery(buffer_minutes=60)
    # Second window starts 30 min after the first ends (10:00 -> 10:30) within 60-min buffer.
    res = api.dispatch_reservation(ctx["reservation_b"]["id"], {
        "delivery_truck_id": ctx["truck"]["id"],
        "delivery_window_start": "2026-06-01T10:30:00.000Z",
        "delivery_window_end": "2026-06-01T11:30:00.000Z",
    }, AGENT)
    validate_error(res, "ERR_TRUCK_DOUBLE_BOOKED")


def test_truck_window_clear_of_buffer_allowed(api):
    """PRD §3.5: "the requested [delivery_window_start, delivery_window_end)
    interval, padded by buffer_minutes before and after, must not collide with any
    other assigned window on the same truck — adjacency within the buffer counts as
    a collision."

    Design: Difficulty/resource_temporal_overlap/delivery_truck_overlap_buffered_half_open_interval
    """
    ctx = setup_dispatched_delivery(buffer_minutes=60)
    # Second window starts 70 min after the first ends (10:00 -> 11:10), clear of the 60-min buffer.
    res = api.dispatch_reservation(ctx["reservation_b"]["id"], {
        "delivery_truck_id": ctx["truck"]["id"],
        "delivery_window_start": "2026-06-01T11:10:00.000Z",
        "delivery_window_end": "2026-06-01T12:10:00.000Z",
    }, AGENT)
    dispatched = validate_success(res, 200)
    assert dispatched["reservation_state"] == "ON_RENT"


# ─── corner: validations ─────────────────────────────────────────

def test_end_before_start_returns_invalid_request(api):
    """PRD §3.4: "Then it validates the body shape — required fields present and
    well-typed, valid enum members, the end date on or after the start date,
    amounts non-negative — rejecting a violation with ERR_INVALID_REQUEST."

    Design: Corner/validations/end_before_start_returns_invalid_request
    """
    ctx = setup_yard()
    res = api.create_reservation(
        _reservation_body(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                          rental_start_date="2026-06-10", rental_end_date="2026-06-01"),
        AGENT)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_nonexistent_account_returns_not_found_before_business(api):
    """PRD §2.5: "the server validates existence left to right in the order the
    identifiers appear and rejects the first missing reference with ERR_NOT_FOUND
    (HTTP 404)."
    PRD §3.4: "First, after authentication and authorization, the server confirms
    every referenced resource exists, rejecting the first missing one with
    ERR_NOT_FOUND."

    Design: Corner/validations/existence_before_state_nonexistent_account_on_reservation
    """
    ctx = setup_yard()
    res = api.create_reservation({
        "contractor_account_id": "00000000-0000-4000-8000-000000000000",
        "catalog_item_id": ctx["item"]["id"],
        "equipment_unit_id": ctx["unit"]["id"],
        "fulfillment_method": "PICKUP",
        "rental_start_date": "2026-06-01",
        "rental_end_date": "2026-06-10",
        "damage_waiver_opted": False,
    }, AGENT)
    validate_error(res, "ERR_NOT_FOUND")


def test_payment_not_negative_returns_422(api):
    """PRD §3.3: "A payment whose amount_cents is not strictly below 0 is rejected
    with ERR_PAYMENT_NOT_NEGATIVE (HTTP 422), after which the account's
    outstanding_balance_cents is recomputed."

    Design: Corner/validations/payment_not_negative_returns_422
    """
    acct = validate_success(api.create_contractor_account(
        {"company_name": "Acme", "credit_limit_cents": 1_000_000}, YM), 201)
    res = api.create_payment(acct["id"], {"amount_cents": 5000}, YM)
    validate_error(res, "ERR_PAYMENT_NOT_NEGATIVE")


def test_pagination_limit_zero_returns_400(api):
    """PRD §2.3: "A request whose limit is below 1, whose limit exceeds 100, or
    whose offset is below 0 is rejected with ERR_VALIDATION_LIMIT (HTTP 400)."

    Design: Corner/validations/pagination_limit_out_of_bounds_returns_400
    """
    res = api.list_rate_cards(YM, params={"limit": 0})
    validate_error(res, "ERR_VALIDATION_LIMIT")
