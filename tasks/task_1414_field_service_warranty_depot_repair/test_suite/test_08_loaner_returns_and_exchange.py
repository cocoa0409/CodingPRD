"""Loaner returns: damage cap, late fees, forfeit, and advance-exchange rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    authorize_rma,
    create_loaner_unit,
    create_reservation,
    create_draft_rma,
    diagnose_rma,
    forfeit_reservation,
    get_customer,
    get_loaner_unit,
    get_reservation,
    inspect_loaner,
    loaner_reservation_payload,
    planned_part_line,
    receive_rma,
    return_reservation,
    set_clock,
    setup_authorized_loaner_with_reservation,
    setup_catalog,
    setup_shipped_loaner_rma,
    ship_reservation,
    triage_rma,
    validate_error,
    validate_success,
)


def test_damaged_return_closes_reservation_with_capped_fee(api):
    """PRD §3.7: "A return in OK condition closes the reservation as
    `CLOSED_RETURNED`; a return reported as damaged closes it as
    `CLOSED_DAMAGED` and pins a `damage_fee_cents` equal to the lesser of the
    `damage_assessment_cents` and the unit's `deposit_value_cents`."

    Design: Difficulty/transitive_cascade/damaged_loaner_return_cascade
    """
    ctx = setup_authorized_loaner_with_reservation()
    ship_reservation(ctx["res"]["id"])
    returned = return_reservation(ctx["res"]["id"], condition="DAMAGED",
                                  damage_assessment_cents=30000)
    assert returned["status"] == "CLOSED_DAMAGED"
    # min(30000 assessment, 40000 deposit) = 30000
    assert returned["damage_fee_cents"] == 30000, (
        f"damage fee must be min(30000, 40000) = 30000, got "
        f"{returned['damage_fee_cents']}")
    # due_date was never set (repaired unit not shipped) -> fee zero
    assert returned["late_fee_cents"] == 0


def test_damaged_return_cascades_unit_to_inspection_then_retired(api):
    """PRD §3.7: "Either way the accrued `late_fee_cents` is finalized per the
    rule below, `returned_at` is pinned, the unit moves from `SHIPPED_OUT` to
    `INSPECTION`, and the customer's deposit exposure is released."
    PRD §3.7: "A `FAIL` moves the unit to `RETIRED`, ending its pool life."

    Design: Difficulty/transitive_cascade/damaged_loaner_return_cascade
    """
    ctx = setup_authorized_loaner_with_reservation()
    ship_reservation(ctx["res"]["id"])
    return_reservation(ctx["res"]["id"], condition="DAMAGED",
                       damage_assessment_cents=30000)
    assert get_loaner_unit(ctx["lu"]["id"])["status"] == "INSPECTION", (
        "the return must move the unit from SHIPPED_OUT to INSPECTION")
    assert get_customer(ctx["customer"]["id"])["deposit_exposure_cents"] == 0, (
        "the return must release the deposit exposure")

    inspected = inspect_loaner(ctx["lu"]["id"], "FAIL")
    assert inspected["status"] == "RETIRED", (
        f"inspect FAIL must retire the unit, got {inspected['status']}")


def test_damage_fee_capped_at_deposit(api):
    """PRD §3.7: "a return reported as damaged closes it as `CLOSED_DAMAGED` and
    pins a `damage_fee_cents` equal to the lesser of the
    `damage_assessment_cents` and the unit's `deposit_value_cents`."

    Design: Corner/calculations/damage_fee_capped_at_deposit
    """
    ctx = setup_authorized_loaner_with_reservation()
    ship_reservation(ctx["res"]["id"])
    returned = return_reservation(ctx["res"]["id"], condition="DAMAGED",
                                  damage_assessment_cents=99999)
    # min(99999, 40000) = 40000: the fee is capped at the deposit value
    assert returned["damage_fee_cents"] == 40000, (
        f"damage fee must be capped at the 40000 deposit, got "
        f"{returned['damage_fee_cents']}")
    assert returned["status"] == "CLOSED_DAMAGED"


def test_late_fee_zero_on_due_date(api):
    """PRD §3.7: "When the repaired (or replacement) unit ships, every
    `LOANER`-mode reservation of the RMA still in `SHIPPED` receives a
    `due_date`: the ship date plus the model's `loaner_grace_days`."
    PRD §3.7: "The fee is zero while `due_date` is unset, and zero when the
    as-of date is on or before the `due_date` — a loaner returned on its due
    date owes nothing."

    Design: Corner/calculations/late_fee_zero_on_due_date
    """
    ctx = setup_shipped_loaner_rma(loaner_grace_days=10)
    # shipped at 2026-08-01, grace 10 -> due 2026-08-11
    res_after = get_reservation(ctx["res"]["id"])
    assert res_after["due_date"][:10] == "2026-08-11", (
        f"due_date must be ship date + 10 grace days = 2026-08-11, got "
        f"{res_after['due_date']}")

    set_clock("2026-08-11T00:00:00Z")
    returned = return_reservation(ctx["res"]["id"], condition="OK")
    assert returned["late_fee_cents"] == 0, (
        f"return on the due date owes nothing, got {returned['late_fee_cents']}")
    assert returned["status"] == "CLOSED_RETURNED"


def test_forfeit_charges_deposit_plus_late_fees(api):
    """PRD §3.7: "A customer who simply keeps the loaner triggers forfeiture by
    an `IntakeAgent` or `DepotManager`: the reservation closes as
    `CLOSED_FORFEITED`, its `forfeit_charge_cents` is set to the unit's
    `deposit_value_cents` plus the accrued `late_fee_cents`, the unit moves from
    `SHIPPED_OUT` to `RETIRED`, and the deposit exposure is released."
    PRD §3.7: "Past the due date, the days late are the calendar days strictly
    after the `due_date` up to and including the as-of date, and the fee is the
    days late multiplied by 2500 cents, capped at the unit's
    `deposit_value_cents`."

    Design: Corner/calculations/forfeit_charges_deposit_plus_late_fees
    """
    ctx = setup_shipped_loaner_rma(loaner_grace_days=10)
    # due 2026-08-11; at 2026-08-13 the days late are 08-12 and 08-13 -> 2 days
    set_clock("2026-08-13T00:00:00Z")
    forfeited = forfeit_reservation(ctx["res"]["id"])
    assert forfeited["late_fee_cents"] == 5000, (
        f"2 days late at 2500/day must be 5000, got {forfeited['late_fee_cents']}")
    assert forfeited["forfeit_charge_cents"] == 45000, (
        f"forfeit charge must be 40000 deposit + 5000 fees = 45000, got "
        f"{forfeited['forfeit_charge_cents']}")
    assert forfeited["status"] == "CLOSED_FORFEITED"
    assert get_loaner_unit(ctx["lu"]["id"])["status"] == "RETIRED"
    assert get_customer(ctx["customer"]["id"])["deposit_exposure_cents"] == 0


def _setup_advance_exchange_rma(ship_exchange=False):
    """ADVANCE_EXCHANGE RMA diagnosed BER -> REPLACEMENT_PENDING, with an
    exchange reservation RESERVED (optionally shipped)."""
    ctx = setup_catalog()
    ctx["lu"] = create_loaner_unit(ctx["model"]["id"])
    ctx["rma"] = create_draft_rma(ctx["customer"]["id"], ctx["unit"]["id"],
                                  service_option="ADVANCE_EXCHANGE")
    ctx["rma"] = authorize_rma(ctx["rma"]["id"])
    ctx["res"] = create_reservation(ctx["rma"]["id"], ctx["lu"]["id"])
    ctx["rma"] = receive_rma(ctx["rma"]["id"], ctx["unit"]["serial_number"])
    ctx["rma"] = triage_rma(ctx["rma"]["id"], ctx["fc"]["id"])
    ctx["rma"] = diagnose_rma(ctx["rma"]["id"], labor_minutes_est=30,
                              repairability="BER", planned_parts=[])
    assert ctx["rma"]["status"] == "REPLACEMENT_PENDING"
    if ship_exchange:
        ctx["res"] = ship_reservation(ctx["res"]["id"])
    return ctx


def test_advance_exchange_ship_requires_fulfilled_exchange(api):
    """PRD §3.8: "From `REPLACEMENT_PENDING`, a replacement unit ships, which is
    guarded twice: the unit's model must not be under containment, otherwise the
    ship is rejected with `ERR_MODEL_CONTAINMENT`, and when the RMA's
    `service_option` is `ADVANCE_EXCHANGE` an advance-exchange reservation for
    the RMA must already be in `SHIPPED` — promising a customer an exchange that
    never left the depot fails with `ERR_EXCHANGE_NOT_FULFILLED`."

    Design: Corner/validations/advance_exchange_ship_requires_fulfilled_exchange
    """
    ctx = _setup_advance_exchange_rma(ship_exchange=False)
    assert ctx["res"]["mode"] == "ADVANCE_EXCHANGE", (
        "the reservation mode must be copied from the RMA's service_option")

    blocked = api.ship_rma(ctx["rma"]["id"],
                           {"carrier": "UPS", "tracking_number": "1Z"},
                           TEST_USERS["depot_technician_headers"])
    validate_error(blocked, ApiErrorId.ERR_EXCHANGE_NOT_FULFILLED)
    assert blocked.status_code == 409

    ship_reservation(ctx["res"]["id"])
    shipped = validate_success(api.ship_rma(
        ctx["rma"]["id"], {"carrier": "UPS", "tracking_number": "1Z"},
        TEST_USERS["depot_technician_headers"]), 200)
    assert shipped["status"] == "SHIPPED"
    assert shipped["return_reason"] == "REPLACED"


def test_return_of_advance_exchange_reservation_rejected(api):
    """PRD §3.7: "Return logistics depend on condition. Receiving a loaner back
    takes a `condition` and an optional `damage_assessment_cents`; return is a
    `LOANER`-mode workflow, and attempting it on an `ADVANCE_EXCHANGE`
    reservation is rejected with `ERR_INVALID_RESERVATION_STATE`."

    Design: Corner/validations/return_of_advance_exchange_reservation_rejected
    """
    ctx = _setup_advance_exchange_rma(ship_exchange=True)
    res = api.return_loaner_reservation(ctx["res"]["id"], {"condition": "OK"},
                                        TEST_USERS["intake_agent_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_RESERVATION_STATE)
    assert res.status_code == 409
    assert get_reservation(ctx["res"]["id"])["status"] == "SHIPPED", (
        "the rejected return must leave the reservation SHIPPED")
