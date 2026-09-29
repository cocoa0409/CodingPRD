"""Declared transitions, initial states, self-loops and terminal lockdown."""
from test_helpers import (
    assert_permit_allotment,
    assert_processing_campaign,
    assert_recovery_lot,
    assert_triage_decision,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_INTAKE


def _received_shipment(api, **network):
    """The clock at the intake instant and one freshly booked NMC622 shipment."""
    ctx = fx.bootstrap_network(api, **network)
    ctx["intake"] = fx.book_intake(api, ctx["supplier"]["id"], ctx["facility"]["id"])
    return ctx


def _settlement_count(api, intake_id):
    _, meta = validate_paginated(
        api.list_settlements(fx.ACCOUNTANT, params={"intake_id": intake_id})
    )
    return meta["total_count"]


def _scheduled_campaign_on_a_hundred_kg_line(api):
    """A line rated at one hundred kilogrammes an hour carrying a single scheduled
    campaign over the first day of August."""
    ctx = fx.bootstrap_network(api, quotes=None)
    ctx["line"] = fx.create_line(api, ctx["facility"]["id"], throughput_kg_per_hour=100.0)
    ctx["campaign"] = fx.create_campaign(
        api,
        ctx["line"]["id"],
        window_start="2026-08-01T00:00:00.000Z",
        window_end="2026-08-02T00:00:00.000Z",
        planned_input_kg=1000.0,
    )
    return ctx


# --------------------------------------------------------------------------
# The custody dimension walks forward one declared step at a time
# --------------------------------------------------------------------------

def test_identify_discharge_and_package_each_advance_custody_one_step(api):
    """Three custody triggers move the physical dimension forward one state each,
    stamping their own field and lifting the version every time.

    PRD §3.2: "Recording the confirmed chemistry supplies `identified_chemistry` as one
    of the same four values and advances `custody_state` from `RECEIVED` to
    `IDENTIFIED`, incrementing the shipment's `version` by 1 and refreshing its
    `updated_at`."

    Design: Corner/state_machines/identify_discharge_package_walks_the_custody_dimension_forward
    """
    ctx = _received_shipment(api, quotes=None)
    intake_id = ctx["intake"]["id"]
    assert ctx["intake"]["version"] == 1

    identified = fx.identify_chemistry(api, intake_id, "NMC622")
    assert identified["custody_state"] == "IDENTIFIED"
    assert identified["identified_chemistry"] == "NMC622"
    assert identified["version"] == 2

    discharged = fx.discharge(api, intake_id, soc_pct=12.0)
    assert discharged["custody_state"] == "DISCHARGED"
    assert float(discharged["soc_pct"]) == 12.0
    assert discharged["version"] == 3

    packaged = fx.package(api, intake_id, packaging_type="UN4G-STEEL-DRUM")
    assert packaged["custody_state"] == "PACKAGED"
    assert packaged["packaging_type"] == "UN4G-STEEL-DRUM"
    assert packaged["version"] == 4

    assert packaged["compliance_state"] == "MANIFEST_DRAFT", (
        "the paperwork dimension never moved"
    )
    assert packaged["released_at"] is None
    assert _settlement_count(api, intake_id) == 0


def test_packaging_above_the_state_of_charge_limit_waits_for_a_second_reading(api):
    """A pack read at forty-five percent charge cannot be packaged, and the repeatable
    discharge step brings it down to the inclusive ceiling.

    PRD §3.2: "Packaging is refused with `ERR_SOC_ABOVE_PACKAGING_LIMIT` whenever
    `soc_pct` is still null or is greater than 30.0 percent; a reading of exactly 30.0
    passes."

    Design: Corner/state_machines/package_above_soc_limit_rejected_then_accepted_after_second_discharge
    """
    ctx = _received_shipment(api, quotes=None)
    intake_id = ctx["intake"]["id"]
    fx.identify_chemistry(api, intake_id, "NMC622")

    hot = fx.discharge(api, intake_id, soc_pct=45.0)
    assert float(hot["soc_pct"]) == 45.0
    assert hot["version"] == 3

    refused = api.package_intake(
        intake_id, f.package_payload("UN4G-STEEL-DRUM"), fx.OPERATOR
    )
    validate_error(refused, "ERR_SOC_ABOVE_PACKAGING_LIMIT", 422)
    intake = fx.read_intake(api, intake_id)
    assert intake["custody_state"] == "DISCHARGED"
    assert intake["packaging_type"] is None
    assert intake["version"] == 3

    remeasured = fx.discharge(api, intake_id, soc_pct=30.0)
    assert float(remeasured["soc_pct"]) == 30.0
    assert remeasured["custody_state"] == "DISCHARGED", "a repeat discharge is a self-loop"
    assert remeasured["version"] == 4

    packaged = fx.package(api, intake_id, packaging_type="UN4G-STEEL-DRUM")
    assert packaged["custody_state"] == "PACKAGED"
    assert packaged["version"] == 5


def test_replaying_identify_is_refused_while_replaying_discharge_is_accepted(api):
    """The same trigger sent twice has opposite outcomes in one dimension: identify is
    one-shot, discharge is the single declared repeat.

    PRD §3.2: "**Discharge is the only repeatable custody step.** A shipment already in
    `DISCHARGED` accepts a further measurement, staying in `DISCHARGED` while
    overwriting `soc_pct` with the new reading and incrementing `version` by 1 again"

    Design: Corner/state_machines/second_identify_chemistry_is_rejected_while_a_second_discharge_is_a_self_loop
    """
    ctx = _received_shipment(api, quotes=None)
    intake_id = ctx["intake"]["id"]
    identified = fx.identify_chemistry(api, intake_id, "NMC622")

    replay = api.identify_chemistry(
        intake_id, f.identify_chemistry_payload("LFP"), fx.CLERK
    )
    validate_error(replay, "ERR_INVALID_CUSTODY_STATE", 409)

    intake = fx.read_intake(api, intake_id)
    assert intake["identified_chemistry"] == "NMC622", (
        "the refused replay did not overwrite the confirmed chemistry"
    )
    assert intake["version"] == identified["version"]

    first = fx.discharge(api, intake_id, soc_pct=18.0)
    assert float(first["soc_pct"]) == 18.0
    assert first["version"] == 3

    second = fx.discharge(api, intake_id, soc_pct=9.0)
    assert float(second["soc_pct"]) == 9.0
    assert second["custody_state"] == "DISCHARGED"
    assert second["version"] == 4


def test_custody_triggers_undeclared_from_the_current_state_are_all_refused(api):
    """Four triggers requested from states that do not declare them are refused with
    one shared code, and none of them consumes a version.

    PRD §3.2: "Any custody step requested from a state for which it is not declared —
    packaging a shipment that is still `RECEIVED`, identifying one that is already
    `IDENTIFIED` — is refused with `ERR_INVALID_CUSTODY_STATE`."

    Design: Corner/state_machines/custody_triggers_from_a_state_that_does_not_declare_them_are_rejected
    """
    ctx = _received_shipment(api, quotes=None)
    intake_id = ctx["intake"]["id"]

    validate_error(
        api.discharge_intake(intake_id, f.discharge_payload(12.0), fx.OPERATOR),
        "ERR_INVALID_CUSTODY_STATE",
        409,
    )
    assert fx.read_intake(api, intake_id)["soc_pct"] is None
    validate_error(
        api.package_intake(intake_id, f.package_payload("UN4G-STEEL-DRUM"), fx.OPERATOR),
        "ERR_INVALID_CUSTODY_STATE",
        409,
    )

    identified = fx.identify_chemistry(api, intake_id, "NMC622")
    assert identified["version"] == 2, "the two refused calls did not consume a version"

    validate_error(
        api.package_intake(intake_id, f.package_payload("UN4G-STEEL-DRUM"), fx.OPERATOR),
        "ERR_INVALID_CUSTODY_STATE",
        409,
    )
    validate_error(
        api.release_intake(intake_id, fx.OPERATOR), "ERR_INVALID_CUSTODY_STATE", 409
    )

    intake = fx.read_intake(api, intake_id)
    assert intake["custody_state"] == "IDENTIFIED"
    assert intake["version"] == 2


def test_release_from_a_packaged_shipment_needs_the_manifest_closed(api):
    """Release is guarded by the other dimension, so a packaged shipment whose
    paperwork is still a draft is refused and no settlement is cut.

    PRD §3.5: "Its `compliance_state` must be `MANIFEST_CLOSED` — this is the one
    cross-dimension guard in the custody machine, and violating it yields
    `ERR_INVALID_COMPLIANCE_STATE`."

    Design: Corner/state_machines/release_before_manifest_closed_returns_invalid_compliance_state
    """
    ctx = fx.bootstrap_network(api)
    packaged = fx.advance_intake(ctx, stop_after="package", modules=())
    intake_id = packaged["intake"]["id"]

    intake = fx.read_intake(api, intake_id)
    assert intake["custody_state"] == "PACKAGED"
    assert intake["compliance_state"] == "MANIFEST_DRAFT"
    version_before = intake["version"]

    validate_error(
        api.release_intake(intake_id, fx.OPERATOR), "ERR_INVALID_COMPLIANCE_STATE", 409
    )

    intake = fx.read_intake(api, intake_id)
    assert intake["custody_state"] == "PACKAGED"
    assert intake["released_at"] is None
    assert intake["version"] == version_before
    assert _settlement_count(api, intake_id) == 0, "the settlement cascade never fired"
    assert fx.read_supplier(api, ctx["supplier"]["id"])["payable_balance_cents"] == 0


# --------------------------------------------------------------------------
# Initial states
# --------------------------------------------------------------------------

def test_freshly_created_rows_land_on_their_declared_initial_states(api):
    """A shipment, a module, a campaign, a lot and a permit allotment each start on the
    state their own machine declares, with every state-dependent field still empty.

    PRD §3.2: "Its `custody_state` — the physical dimension — starts at `RECEIVED` and
    may take the values `RECEIVED`, `IDENTIFIED`, `DISCHARGED`, `PACKAGED`, `RELEASED`
    and `QUARANTINED`, with `RELEASED` terminal. Its `compliance_state` — the paperwork
    dimension — starts at `MANIFEST_DRAFT`"

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    fx.move_clock(api, CLOCK_INTAKE)
    facility = fx.create_facility(api)
    supplier = fx.create_supplier(api)
    line = fx.create_line(api, facility["id"], throughput_kg_per_hour=100.0)

    intake = fx.book_intake(api, supplier["id"], facility["id"])
    assert intake["custody_state"] == "RECEIVED"
    assert intake["compliance_state"] == "MANIFEST_DRAFT"
    assert intake["version"] == 1

    fx.identify_chemistry(api, intake["id"], "NMC622")
    module = fx.add_module(api, intake["id"], "M-1")
    assert module["status"] == "PENDING_TRIAGE"
    assert module["lot_id"] is None
    assert module["second_life_score"] is None
    assert module["grade"] is None

    campaign = fx.create_campaign(
        api,
        line["id"],
        window_start="2026-08-01T00:00:00.000Z",
        window_end="2026-08-02T00:00:00.000Z",
        planned_input_kg=1000.0,
    )
    assert_processing_campaign(campaign)
    assert campaign["status"] == "SCHEDULED"
    assert float(campaign["committed_input_kg"]) == 0.0
    assert campaign["cancel_reason"] is None

    lot = fx.open_lot(api, campaign["id"], lot_code="LOT-1")
    assert_recovery_lot(lot)
    assert lot["status"] == "OPEN"
    assert float(lot["charged_mass_kg"]) == 0.0
    assert lot["mass_balance_pct"] is None
    assert lot["finalized_at"] is None
    assert lot["void_reason"] is None

    allotment = fx.create_allotment(api, facility["id"])
    assert_permit_allotment(allotment)
    assert allotment["status"] == "ACTIVE"
    assert float(allotment["consumed_kg"]) == 0.0
    assert allotment["suspend_reason"] is None


# --------------------------------------------------------------------------
# Terminal states and cancellation side effects
# --------------------------------------------------------------------------

def test_a_cancelled_campaign_refuses_both_start_and_a_second_cancel(api):
    """Cancellation is terminal, so neither trigger is declared from it and the reason
    recorded by the first call is never overwritten.

    PRD §3.6: "Cancellation is the alternative exit from `SCHEDULED`. It carries a
    `cancel_reason`, requires `status` to be `SCHEDULED`, and additionally requires
    that no lot of the campaign has `status` `CHARGED` or `FINALIZED`; both failures
    report `ERR_CAMPAIGN_NOT_SCHEDULED`."

    Design: Corner/state_machines/cancelled_campaign_refuses_start_and_a_second_cancel
    """
    ctx = _scheduled_campaign_on_a_hundred_kg_line(api)
    campaign_id = ctx["campaign"]["id"]

    cancelled = validate_success(
        api.cancel_campaign(
            campaign_id, f.cancel_campaign_payload("FEEDSTOCK_SHORTFALL"), fx.OPERATOR
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "FEEDSTOCK_SHORTFALL"
    assert cancelled["version"] == 2

    validate_error(
        api.start_campaign(campaign_id, fx.OPERATOR), "ERR_CAMPAIGN_NOT_SCHEDULED", 409
    )
    validate_error(
        api.cancel_campaign(
            campaign_id, f.cancel_campaign_payload("SECOND_ATTEMPT"), fx.OPERATOR
        ),
        "ERR_CAMPAIGN_NOT_SCHEDULED",
        409,
    )

    final = validate_success(api.get_campaign(campaign_id, fx.OPERATOR))
    assert final["status"] == "CANCELLED"
    assert final["cancel_reason"] == "FEEDSTOCK_SHORTFALL"
    assert final["version"] == 2


def test_cancelling_a_campaign_voids_its_open_lots_and_frees_the_line_window(api):
    """One cancel fires two side effects at once: both open lots are voided with the
    cancellation reason, and the released window is bookable again.

    PRD §3.6: "On success the campaign moves `SCHEDULED → CANCELLED`, the
    `cancel_reason` is recorded, every lot of the campaign still in `OPEN` becomes
    `VOIDED` with its `void_reason` set to `CAMPAIGN_CANCELLED`, the line's occupation
    window is released so a later campaign may reuse it, and the `version` of the
    campaign and of every voided lot increments by 1."

    Design: Corner/state_machines/campaign_cancel_voids_open_lots_and_frees_the_line_window
    """
    ctx = _scheduled_campaign_on_a_hundred_kg_line(api)
    campaign_id = ctx["campaign"]["id"]
    lots = [fx.open_lot(api, campaign_id, lot_code=code) for code in ("LOT-1", "LOT-2")]

    cancelled = validate_success(
        api.cancel_campaign(
            campaign_id, f.cancel_campaign_payload("FEEDSTOCK_SHORTFALL"), fx.OPERATOR
        )
    )
    assert cancelled["status"] == "CANCELLED"

    voided, meta = validate_paginated(
        api.list_lots(fx.OPERATOR, params={"campaign_id": campaign_id, "status": "VOIDED"})
    )
    assert meta["total_count"] == 2
    assert voided[0]["void_reason"] == "CAMPAIGN_CANCELLED"
    for lot in lots:
        stored = fx.read_lot(api, lot["id"])
        assert stored["status"] == "VOIDED"
        assert stored["void_reason"] == "CAMPAIGN_CANCELLED"
        assert float(stored["charged_mass_kg"]) == 0.0
        assert stored["version"] == 2

    rebooked = fx.create_campaign(
        api,
        ctx["line"]["id"],
        window_start="2026-08-01T00:00:00.000Z",
        window_end="2026-08-02T00:00:00.000Z",
        planned_input_kg=1000.0,
    )
    assert rebooked["status"] == "SCHEDULED"
    assert rebooked["id"] != campaign_id


def test_a_shipped_module_refuses_both_a_second_ship_and_a_second_triage(api):
    """A grade-A module routed to the refurbishment queue ships once, and from that
    terminal state both write paths are closed.

    PRD §3.4: "It requires the module's `status` to be `REFURB_QUEUE` or
    `SECOND_LIFE_QUEUE` — anything else is refused with `ERR_MODULE_NOT_SHIPPABLE` —
    and it requires the module's shipment to have `custody_state` `RELEASED`, failing
    with `ERR_INTAKE_NOT_RELEASED` otherwise. On success the module moves to `SHIPPED`,
    which together with `CONSUMED` is a terminal module state, and its `version`
    increments by 1."

    Design: Corner/state_machines/shipped_module_refuses_a_second_ship_and_a_second_triage
    """
    ctx = fx.bootstrap_network(api)
    walked = fx.advance_intake(
        ctx,
        stop_after="released",
        modules=(
            {
                "serial_code": "M-1",
                "min_cell_capacity_pct": 88.0,
                "mean_cell_capacity_pct": 92.0,
                "cycle_count": 400,
            },
        ),
    )
    assert fx.read_intake(api, walked["intake"]["id"])["custody_state"] == "RELEASED"
    module_id = walked["modules"][0]["id"]

    decision = fx.triage_module(api, module_id, scoring_variant="FLEET_AVERAGE")
    assert_triage_decision(decision)
    assert float(decision["score"]) == 86.80
    assert decision["grade"] == "A"
    assert decision["derived_disposition"] == "REFURBISH"
    assert decision["disposition"] == "REFURBISH"
    assert decision["status"] == "ACTIVE"

    queued = validate_success(api.get_module(module_id, fx.OPERATOR))
    assert queued["status"] == "REFURB_QUEUE"
    assert float(queued["second_life_score"]) == 86.80
    assert queued["grade"] == "A"

    shipped = validate_success(
        api.ship_module(module_id, f.ship_module_payload("Second Wind Storage"), fx.OPERATOR)
    )
    assert shipped["status"] == "SHIPPED"
    assert shipped["shipped_to"] == "Second Wind Storage"

    validate_error(
        api.ship_module(module_id, f.ship_module_payload("Second Wind Storage"), fx.OPERATOR),
        "ERR_MODULE_NOT_SHIPPABLE",
        409,
    )
    assert validate_success(api.get_module(module_id, fx.OPERATOR))["version"] == shipped[
        "version"
    ]

    validate_error(
        api.create_triage_decision(
            module_id, f.create_triage_decision_payload("CONSERVATIVE"), fx.ENGINEER
        ),
        "ERR_MODULE_NOT_TRIAGEABLE",
        409,
    )
    _, meta = validate_paginated(api.list_triage_decisions(module_id, fx.ENGINEER))
    assert meta["total_count"] == 1


# --------------------------------------------------------------------------
# The permit allotment leaves ACTIVE two different ways
# --------------------------------------------------------------------------

def _allotment_and_lot(api, *, clock=CLOCK_INTAKE, window=None):
    ctx = fx.bootstrap_network(api, clock=clock, quotes=None)
    ctx["line"] = fx.create_line(api, ctx["facility"]["id"], throughput_kg_per_hour=100.0)
    start, end = window or ("2026-08-01T00:00:00.000Z", "2026-08-02T00:00:00.000Z")
    ctx["campaign"] = fx.create_campaign(
        api, ctx["line"]["id"], window_start=start, window_end=end, planned_input_kg=1000.0
    )
    ctx["lot"] = fx.open_lot(api, ctx["campaign"]["id"], lot_code="LOT-1")
    ctx["allotment"] = fx.create_allotment(api, ctx["facility"]["id"])
    return ctx


def test_lazy_expiry_flips_the_allotment_and_still_rejects_the_booking(api):
    """Moving the clock past the permit's last covered instant expires the allotment at
    the start of the next booking, which is then refused.

    PRD §3.8: "At the very start of a discharge-event booking, the server evaluates the
    target allotment: if its `status` is `ACTIVE` and the current clock position is
    strictly later than its `valid_to`, the allotment moves `ACTIVE → EXPIRED` and
    its `version` increments by 1, and the triggering booking is then rejected with
    `ERR_PERMIT_NOT_ACTIVE`."

    Design: Corner/state_machines/permit_lazy_expiry_moves_the_allotment_to_expired_and_rejects_the_event
    """
    ctx = _allotment_and_lot(api)
    allotment_id = ctx["allotment"]["id"]
    assert ctx["allotment"]["version"] == 1
    assert ctx["allotment"]["status"] == "ACTIVE"

    fx.move_clock(api, "2026-09-01T00:00:00.000Z")
    refused = api.create_discharge_event(
        ctx["lot"]["id"],
        f.create_discharge_event_payload(
            allotment_id, "2026-08-20T10:00:00.000Z", 10.0, analyte="NICKEL_DISSOLVED"
        ),
        fx.SUBMITTER,
    )
    validate_error(refused, "ERR_PERMIT_NOT_ACTIVE", 422)

    allotment = fx.read_allotment(api, allotment_id)
    assert allotment["status"] == "EXPIRED"
    assert allotment["version"] == 2, (
        "the lazy transition commits even though the triggering request failed"
    )
    assert float(allotment["consumed_kg"]) == 0.0

    _, meta = validate_paginated(
        api.list_discharge_events(fx.SUBMITTER, params={"allotment_id": allotment_id})
    )
    assert meta["total_count"] == 0


def test_a_suspended_allotment_blocks_a_booking_inside_its_window(api):
    """A regulator suspension is a manual stop that keeps the unspent allowance yet
    refuses the booking with the same code as expiry.

    PRD §3.8: "Suspending an allotment after a regulator finding carries a
    `suspend_reason`, requires `status` to be `ACTIVE`, moves it
    `ACTIVE → SUSPENDED` and increments its `version` by 1."

    Design: Corner/state_machines/suspended_allotment_blocks_a_discharge_event
    """
    ctx = _allotment_and_lot(
        api,
        clock="2026-08-20T00:00:00.000Z",
        window=("2026-09-01T00:00:00.000Z", "2026-09-02T00:00:00.000Z"),
    )
    allotment_id = ctx["allotment"]["id"]

    suspended = validate_success(
        api.suspend_permit_allotment(
            allotment_id,
            f.suspend_permit_payload("OUTFALL_SAMPLING_EXCEEDANCE"),
            fx.SUBMITTER,
        )
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspend_reason"] == "OUTFALL_SAMPLING_EXCEEDANCE"
    assert suspended["version"] == 2

    refused = api.create_discharge_event(
        ctx["lot"]["id"],
        f.create_discharge_event_payload(
            allotment_id, "2026-08-20T10:00:00.000Z", 10.0, analyte="NICKEL_DISSOLVED"
        ),
        fx.SUBMITTER,
    )
    validate_error(refused, "ERR_PERMIT_NOT_ACTIVE", 422)

    allotment = fx.read_allotment(api, allotment_id)
    assert float(allotment["consumed_kg"]) == 0.0
    assert allotment["status"] == "SUSPENDED", (
        "the clock sits inside the validity interval, so this is not expiry"
    )

    _, meta = validate_paginated(
        api.list_discharge_events(fx.SUBMITTER, params={"lot_id": ctx["lot"]["id"]})
    )
    assert meta["total_count"] == 0
