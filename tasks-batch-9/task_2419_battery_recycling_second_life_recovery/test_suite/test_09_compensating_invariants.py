"""Forward actions and their compensations, checked against the named invariants."""
from test_helpers import (
    assert_credit_hold_consistent,
    assert_intake_mass_conservation,
    assert_permit_allowance_invariant,
    assert_supplier_obligation_invariant,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_PROCESS, FOUR_METAL_QUOTES


def _settlements_of(api, supplier_id):
    data, _ = validate_paginated(
        api.list_settlements(fx.ACCOUNTANT, params={"supplier_id": supplier_id})
    )
    return data


# --------------------------------------------------------------------------
# Posting a settlement and voiding it: the supplier obligation invariant
# --------------------------------------------------------------------------

def _unposted_settlement_over_the_credit_limit(api):
    """A finalized shipment whose FINAL settlement will breach the counterparty's
    credit limit the moment it posts, plus a second shipment still in RECEIVED."""
    ctx = fx.bootstrap_network(api, supplier={"credit_limit_cents": 20_000})
    first = fx.advance_intake(ctx, stop_after="released")
    second = fx.advance_intake(
        ctx,
        stop_after="intake",
        intake={"gross_mass_kg": 60.0, "packaging_tare_kg": 10.0, "declared_ni_pct": 11.0},
        modules=(),
    )
    ctx["modules"] = first["modules"]
    fx.advance_processing(ctx, stop_after="finalized")
    ctx["first"] = first
    ctx["second"] = second
    return ctx


def test_posting_loads_the_payable_balance_and_quarantines_the_waiting_shipment(api):
    """Posting freezes the net payable onto the settlement, raises the counterparty's
    obligation past its limit and sweeps its RECEIVED shipment into quarantine.

    PRD §3.9: "The first link freezes `posted_amount_cents` at the current
    `net_payable_cents` — from this point on, the payable ledger is driven by the
    frozen figure, not by the live calculation."

    Design: Difficulty/compensating_invariant/settlement_post_then_void_restores_supplier_obligation_invariant
    """
    ctx = _unposted_settlement_over_the_credit_limit(api)

    supplier = fx.read_supplier(api, ctx["supplier"]["id"])
    assert supplier["payable_balance_cents"] == 0
    assert supplier["credit_hold"] is False
    assert ctx["settlement"]["net_payable_cents"] == 30723
    assert ctx["settlement"]["posted_amount_cents"] == 0

    posted = fx.post_settlement(api, ctx["settlement"]["id"])
    assert posted["state"] == "POSTED"
    assert posted["posted_amount_cents"] == 30723

    supplier = fx.read_supplier(api, ctx["supplier"]["id"])
    assert supplier["payable_balance_cents"] == 30723
    assert supplier["credit_hold"] is True
    assert_credit_hold_consistent(supplier)
    assert_supplier_obligation_invariant(supplier, _settlements_of(api, supplier["id"]))

    second = fx.read_intake(api, ctx["second"]["intake"]["id"])
    assert second["custody_state"] == "QUARANTINED"
    assert second["hold_reason"] == "SUPPLIER_CREDIT_HOLD"


def test_voiding_the_posting_restores_the_supplier_obligation_invariant(api):
    """The void takes the frozen amount back out of the payable ledger, releases the
    quarantine it caused and leaves the priced figure on the record.

    PRD §3.9: "The supplier's `payable_balance_cents` decreases by
    `posted_amount_cents` and `posted_amount_cents` resets to 0, which restores the
    supplier obligation invariant of §2.10 precisely."

    Design: Difficulty/compensating_invariant/settlement_post_then_void_restores_supplier_obligation_invariant
    """
    ctx = _unposted_settlement_over_the_credit_limit(api)
    fx.post_settlement(api, ctx["settlement"]["id"])

    voided = fx.void_settlement(
        api, ctx["settlement"]["id"], "Booked against the wrong purchase order"
    )
    assert voided["state"] == "VOIDED"
    assert voided["posted_amount_cents"] == 0
    assert voided["net_payable_cents"] == 30723, (
        "voiding reverses the ledger entry, not the pricing arithmetic"
    )

    supplier = fx.read_supplier(api, ctx["supplier"]["id"])
    assert supplier["payable_balance_cents"] == 0
    assert supplier["paid_to_date_cents"] == 0
    assert supplier["credit_hold"] is False
    assert_supplier_obligation_invariant(supplier, _settlements_of(api, supplier["id"]))

    second = fx.read_intake(api, ctx["second"]["intake"]["id"])
    assert second["custody_state"] == "RECEIVED"
    assert second["hold_reason"] is None

    first = fx.read_intake(api, ctx["first"]["intake"]["id"])
    assert first["custody_state"] == "RELEASED", (
        "only shipments quarantined by the credit hold are released back to RECEIVED"
    )


def test_a_voided_settlement_cannot_be_voided_a_second_time(api):
    """The compensation is not repeatable, so the payable balance cannot be credited
    twice for one posting.

    PRD §3.9: "It carries a `void_reason`, requires the settlement's `state` to be
    `POSTED` — otherwise `ERR_SETTLEMENT_NOT_POSTED` — and moves it
    `POSTED → VOIDED`, which is terminal."

    Design: Difficulty/compensating_invariant/settlement_post_then_void_restores_supplier_obligation_invariant
    """
    ctx = _unposted_settlement_over_the_credit_limit(api)
    fx.post_settlement(api, ctx["settlement"]["id"])
    fx.void_settlement(
        api, ctx["settlement"]["id"], "Booked against the wrong purchase order"
    )

    response = api.void_settlement(
        ctx["settlement"]["id"],
        f.void_settlement_payload("Duplicate reversal raised by the ledger clerk"),
        fx.ACCOUNTANT,
    )
    validate_error(response, "ERR_SETTLEMENT_NOT_POSTED", 409)

    supplier = fx.read_supplier(api, ctx["supplier"]["id"])
    assert supplier["payable_balance_cents"] == 0
    assert_supplier_obligation_invariant(supplier, _settlements_of(api, supplier["id"]))


# --------------------------------------------------------------------------
# Charging a lot and voiding it: the shipment mass conservation invariant
# --------------------------------------------------------------------------

def _two_lots_and_an_eight_hundred_kilogramme_shipment(api):
    """A running campaign with two open lots and one released shipment whose two
    four-hundred-kilogramme modules are both waiting in the recovery queue."""
    ctx = fx.build_world(
        api,
        stop_after="lot",
        network={
            "quotes": FOUR_METAL_QUOTES,
            "supplier": {"credit_limit_cents": 200_000},
        },
        intake={
            "intake": {
                "gross_mass_kg": 850.0,
                "packaging_tare_kg": 50.0,
                "declared_ni_pct": 12.0,
                "declared_co_pct": 4.0,
                "declared_li_pct": 2.5,
                "declared_cu_pct": 8.0,
            },
            "modules": fx.TWO_LARGE_MODULES,
        },
    )
    ctx["spare_lot"] = fx.open_lot(api, ctx["campaign"]["id"], lot_code="L-2")
    return ctx


def test_voiding_a_charged_lot_gives_back_every_module_and_its_mass(api):
    """The void unwinds the charge completely: both modules return to the recovery
    queue, the shipment's assigned and unassigned split swings back and the campaign
    plan is freed.

    PRD §3.7: "Voiding a `CHARGED` lot does all of that and unwinds the charge as
    well: every module whose `lot_id` is this lot and whose `status` is `CHARGED`
    reverts to `RECOVERY_QUEUE` with its `lot_id` reset to null"

    Design: Difficulty/compensating_invariant/lot_charge_then_void_restores_intake_mass_conservation_invariant
    """
    ctx = _two_lots_and_an_eight_hundred_kilogramme_shipment(api)
    module_ids = [module["id"] for module in ctx["modules"]]

    intake = fx.read_intake(api, ctx["intake"]["id"])
    assert float(intake["module_mass_total_kg"]) == 800.0
    assert float(intake["unassigned_mass_kg"]) == 800.0
    assert_intake_mass_conservation(intake)

    lot = fx.charge_lot(api, ctx["lot"]["id"], module_ids)
    assert float(lot["charged_mass_kg"]) == 800.000
    intake = fx.read_intake(api, ctx["intake"]["id"])
    assert float(intake["assigned_mass_kg"]) == 800.0
    assert float(intake["unassigned_mass_kg"]) == 0.0

    voided = validate_success(
        api.void_lot(
            ctx["lot"]["id"],
            f.void_lot_payload("Reactor contamination found before leaching"),
            fx.OPERATOR,
        )
    )
    assert voided["status"] == "VOIDED"
    assert float(voided["charged_mass_kg"]) == 0.0
    assert voided["void_reason"] == "Reactor contamination found before leaching"

    for module_id in module_ids:
        module = validate_success(api.get_module(module_id, fx.OPERATOR))
        assert module["status"] == "RECOVERY_QUEUE"
        assert module["lot_id"] is None

    intake = fx.read_intake(api, ctx["intake"]["id"])
    assert float(intake["assigned_mass_kg"]) == 0.0
    assert float(intake["unassigned_mass_kg"]) == 800.0
    assert float(intake["module_mass_total_kg"]) == 800.0
    assert_intake_mass_conservation(intake)

    campaign = validate_success(api.get_campaign(ctx["campaign"]["id"], fx.OPERATOR))
    assert float(campaign["committed_input_kg"]) == 0.000


def test_a_voided_lot_refuses_a_second_charge_while_a_fresh_lot_accepts_it(api):
    """The voided lot is terminal, yet the released mass re-charges into another lot
    with no drift.

    PRD §3.7: "the lot's `status` must be `OPEN`, otherwise `ERR_LOT_NOT_OPEN`"

    Design: Difficulty/compensating_invariant/lot_charge_then_void_restores_intake_mass_conservation_invariant
    """
    ctx = _two_lots_and_an_eight_hundred_kilogramme_shipment(api)
    module_ids = [module["id"] for module in ctx["modules"]]
    fx.charge_lot(api, ctx["lot"]["id"], module_ids)
    validate_success(
        api.void_lot(
            ctx["lot"]["id"],
            f.void_lot_payload("Reactor contamination found before leaching"),
            fx.OPERATOR,
        )
    )

    voided_lot = fx.read_lot(api, ctx["lot"]["id"])
    response = api.charge_lot(
        ctx["lot"]["id"],
        f.charge_lot_payload(module_ids, voided_lot["version"]),
        fx.OPERATOR,
    )
    validate_error(response, "ERR_LOT_NOT_OPEN", 409)

    fresh = fx.charge_lot(api, ctx["spare_lot"]["id"], module_ids)
    assert fresh["status"] == "CHARGED"
    assert float(fresh["charged_mass_kg"]) == 800.000

    intake = fx.read_intake(api, ctx["intake"]["id"])
    assert float(intake["assigned_mass_kg"]) == 800.0
    assert float(intake["unassigned_mass_kg"]) == 0.0
    assert_intake_mass_conservation(intake)

    campaign = validate_success(api.get_campaign(ctx["campaign"]["id"], fx.OPERATOR))
    assert float(campaign["committed_input_kg"]) == 800.000


# --------------------------------------------------------------------------
# Booking a discharge event and voiding it: the permit allowance invariant
# --------------------------------------------------------------------------

def _capped_allotment_with_a_lot(api):
    """An open lot and an active water allotment capped at five hundred kilogrammes
    a day, with nothing consumed yet."""
    ctx = fx.bootstrap_network(api, clock=CLOCK_PROCESS, quotes=None)
    ctx["line"] = fx.create_line(api, ctx["facility"]["id"])
    ctx["campaign"] = fx.create_campaign(
        api,
        ctx["line"]["id"],
        window_start="2026-08-25T00:00:00.000Z",
        window_end="2026-09-30T00:00:00.000Z",
    )
    ctx["lot"] = fx.open_lot(api, ctx["campaign"]["id"])
    ctx["allotment"] = fx.create_allotment(api, ctx["facility"]["id"])
    assert float(ctx["allotment"]["consumed_kg"]) == 0.0
    return ctx


def test_voiding_a_discharge_event_returns_the_daily_allowance_exactly(api):
    """The refused mass becomes bookable again for the very same day once the first
    event is voided, because the bucket re-reads the POSTED rows.

    PRD §3.8: "It carries a `void_reason`, requires the event's `status` to be
    `POSTED` — otherwise `ERR_DISCHARGE_EVENT_NOT_POSTED` — moves the event
    `POSTED → VOIDED`, subtracts its `mass_kg` from the allotment's `consumed_kg`, and
    increments both the event's `version` and the allotment's `version` by 1."

    Design: Difficulty/compensating_invariant/discharge_event_then_void_restores_permit_allowance_invariant
    """
    ctx = _capped_allotment_with_a_lot(api)
    allotment_id = ctx["allotment"]["id"]

    first = fx.book_discharge_event(
        api, ctx["lot"]["id"], allotment_id, "2026-08-20T06:00:00.000Z", 500.0
    )
    assert first["status"] == "POSTED"

    refused = api.create_discharge_event(
        ctx["lot"]["id"],
        f.create_discharge_event_payload(allotment_id, "2026-08-20T09:00:00.000Z", 500.0),
        fx.SUBMITTER,
    )
    validate_error(refused, "ERR_DISCHARGE_DAILY_CAP_EXCEEDED", 422)

    voided = validate_success(
        api.void_discharge_event(
            first["id"], f.void_discharge_event_payload("Sampled from the wrong sump"), fx.SUBMITTER
        )
    )
    assert voided["status"] == "VOIDED"

    allotment = fx.read_allotment(api, allotment_id)
    assert float(allotment["consumed_kg"]) == 0.0
    assert allotment["status"] == "ACTIVE"

    retried = fx.book_discharge_event(
        api, ctx["lot"]["id"], allotment_id, "2026-08-20T09:00:00.000Z", 500.0
    )
    assert retried["status"] == "POSTED"

    allotment = fx.read_allotment(api, allotment_id)
    assert float(allotment["consumed_kg"]) == 500.0
    events, _ = validate_paginated(
        api.list_discharge_events(fx.SUBMITTER, params={"allotment_id": allotment_id})
    )
    assert_permit_allowance_invariant(allotment, events)


def test_a_voided_discharge_event_cannot_be_voided_twice(api):
    """A second void of the same event would credit the allowance twice, so it is
    refused and the voided row survives as an audit trail.

    PRD §3.8: "`consumed_kg` is maintained as the sum of `mass_kg` over that
    allotment's discharge events whose `status` is `POSTED`, rounded half up to three
    decimals."

    Design: Difficulty/compensating_invariant/discharge_event_then_void_restores_permit_allowance_invariant
    """
    ctx = _capped_allotment_with_a_lot(api)
    allotment_id = ctx["allotment"]["id"]
    first = fx.book_discharge_event(
        api, ctx["lot"]["id"], allotment_id, "2026-08-20T06:00:00.000Z", 500.0
    )
    validate_success(
        api.void_discharge_event(
            first["id"], f.void_discharge_event_payload("Sampled from the wrong sump"), fx.SUBMITTER
        )
    )
    fx.book_discharge_event(
        api, ctx["lot"]["id"], allotment_id, "2026-08-20T09:00:00.000Z", 500.0
    )

    response = api.void_discharge_event(
        first["id"],
        f.void_discharge_event_payload("Duplicate reversal raised by the environmental clerk"),
        fx.SUBMITTER,
    )
    validate_error(response, "ERR_DISCHARGE_EVENT_NOT_POSTED", 409)

    allotment = fx.read_allotment(api, allotment_id)
    assert float(allotment["consumed_kg"]) == 500.0
    events, _ = validate_paginated(
        api.list_discharge_events(fx.SUBMITTER, params={"allotment_id": allotment_id})
    )
    assert_permit_allowance_invariant(allotment, events)
    assert sorted(event["status"] for event in events) == ["POSTED", "VOIDED"]
