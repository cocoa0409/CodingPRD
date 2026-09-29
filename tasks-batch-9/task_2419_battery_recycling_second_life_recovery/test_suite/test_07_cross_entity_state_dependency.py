"""Transitions gated on the state of a row other than the one being changed."""
from test_helpers import (
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_PROCESS


# --------------------------------------------------------------------------
# Charging reads the shipment's custody state, not the module's queue alone
# --------------------------------------------------------------------------

def _lot_awaiting_an_unreleased_shipment(api):
    """A running campaign with an open lot and a recovery-queued module whose
    shipment is packaged and manifest-closed but not yet released."""
    ctx = fx.bootstrap_network(api)
    fx.advance_intake(ctx, stop_after="manifest_closed")
    fx.advance_processing(ctx, stop_after="lot")
    return ctx


def test_charge_is_refused_while_the_contributing_shipment_is_only_packaged(api):
    """A recovery-queued module cannot be charged until custody of its shipment has
    been released.

    PRD §3.7: "every named module's shipment must have `custody_state` `RELEASED`,
    otherwise `ERR_INTAKE_NOT_RELEASED`"

    Design: Difficulty/cross_entity_state_dependency/charge_requires_intake_released_not_merely_packaged
    """
    ctx = _lot_awaiting_an_unreleased_shipment(api)
    module_ids = [module["id"] for module in ctx["modules"]]

    response = api.charge_lot(
        ctx["lot"]["id"],
        f.charge_lot_payload(module_ids, ctx["lot"]["version"]),
        fx.OPERATOR,
    )
    validate_error(response, "ERR_INTAKE_NOT_RELEASED", 422)

    lot = fx.read_lot(api, ctx["lot"]["id"])
    assert lot["status"] == "OPEN"
    assert float(lot["charged_mass_kg"]) == 0.0

    module = validate_success(api.get_module(module_ids[0], fx.OPERATOR))
    assert module["status"] == "RECOVERY_QUEUE"
    assert module["lot_id"] is None


def test_charge_succeeds_once_custody_of_the_shipment_is_released(api):
    """Releasing the shipment is the only change needed for the identical charge to
    move mass into the recovery ledger.

    PRD §3.7: "A successful charge moves the lot `OPEN → CHARGED` and moves every
    named module `RECOVERY_QUEUE → CHARGED` with its `lot_id` set to that lot."

    Design: Difficulty/cross_entity_state_dependency/charge_requires_intake_released_not_merely_packaged
    """
    ctx = _lot_awaiting_an_unreleased_shipment(api)
    module_ids = [module["id"] for module in ctx["modules"]]

    released = fx.release(api, ctx["intake"]["id"])
    assert released["custody_state"] == "RELEASED"

    lot = fx.charge_lot(api, ctx["lot"]["id"], module_ids)
    assert lot["status"] == "CHARGED"
    assert float(lot["charged_mass_kg"]) == 100.000

    module = validate_success(api.get_module(module_ids[0], fx.OPERATOR))
    assert module["status"] == "CHARGED"
    assert module["lot_id"] == lot["id"]

    intake = fx.read_intake(api, ctx["intake"]["id"])
    assert float(intake["assigned_mass_kg"]) == 100.0
    assert float(intake["unassigned_mass_kg"]) == 0.0


# --------------------------------------------------------------------------
# Charging reads the campaign's state, not the lot's alone
# --------------------------------------------------------------------------

def _open_lot_under_a_scheduled_campaign(api):
    """An open lot on a campaign that has been scheduled but never started."""
    ctx = fx.bootstrap_network(api)
    fx.advance_intake(ctx, stop_after="released")
    ctx["line"] = fx.create_line(api, ctx["facility"]["id"])
    ctx["campaign"] = fx.create_campaign(api, ctx["line"]["id"])
    ctx["decisions"] = [fx.triage_module(api, m["id"]) for m in ctx["modules"]]
    fx.move_clock(api, CLOCK_PROCESS)
    ctx["lot"] = fx.open_lot(api, ctx["campaign"]["id"])
    return ctx


def test_charge_is_refused_while_the_campaign_is_only_scheduled(api):
    """A lot may be opened under a scheduled campaign, but charging it requires the
    campaign to be running.

    PRD §3.7: "the campaign's `status` must be `RUNNING`, otherwise
    `ERR_CAMPAIGN_NOT_RUNNING`"

    Design: Difficulty/cross_entity_state_dependency/charge_requires_campaign_running_not_scheduled
    """
    ctx = _open_lot_under_a_scheduled_campaign(api)
    assert ctx["campaign"]["status"] == "SCHEDULED"

    response = api.charge_lot(
        ctx["lot"]["id"],
        f.charge_lot_payload([m["id"] for m in ctx["modules"]], ctx["lot"]["version"]),
        fx.OPERATOR,
    )
    validate_error(response, "ERR_CAMPAIGN_NOT_RUNNING", 409)

    lot = fx.read_lot(api, ctx["lot"]["id"])
    assert lot["status"] == "OPEN"
    assert float(lot["charged_mass_kg"]) == 0.0


def test_charge_succeeds_once_the_campaign_is_started(api):
    """Starting the campaign is the only change needed for the identical charge to be
    accepted and to raise the campaign's committed input.

    PRD §3.6: "`committed_input_kg` is maintained by the system as the sum of
    `charged_mass_kg` over the campaign's lots whose `status` is `OPEN`, `CHARGED` or
    `FINALIZED`, rounded half up to three decimals."

    Design: Difficulty/cross_entity_state_dependency/charge_requires_campaign_running_not_scheduled
    """
    ctx = _open_lot_under_a_scheduled_campaign(api)

    started = fx.start_campaign(api, ctx["campaign"]["id"])
    assert started["status"] == "RUNNING"

    lot = fx.charge_lot(api, ctx["lot"]["id"], [m["id"] for m in ctx["modules"]])
    assert lot["status"] == "CHARGED"
    assert float(lot["charged_mass_kg"]) == 100.000

    campaign = validate_success(api.get_campaign(ctx["campaign"]["id"], fx.OPERATOR))
    assert float(campaign["committed_input_kg"]) == 100.000


# --------------------------------------------------------------------------
# Release reads the counterparty's credit hold
# --------------------------------------------------------------------------

def _second_shipment_behind_a_credit_hold(api):
    return fx.credit_hold_world(
        api,
        second_intake_stop_after="manifest_closed",
        second_intake={"soc_pct": 14.0},
    )


def test_release_is_refused_while_the_counterparty_is_on_credit_hold(api):
    """A packaged, manifest-closed shipment cannot be released while the recycler is
    already over the counterparty's credit limit.

    PRD §3.5: "The counterparty's `credit_hold` must be false, otherwise
    `ERR_SUPPLIER_CREDIT_HOLD`."

    Design: Difficulty/cross_entity_state_dependency/release_blocked_while_supplier_credit_hold_true
    """
    ctx = _second_shipment_behind_a_credit_hold(api)
    assert ctx["supplier"]["credit_hold"] is True

    second_id = ctx["second"]["intake"]["id"]
    response = api.release_intake(second_id, fx.OPERATOR)
    validate_error(response, "ERR_SUPPLIER_CREDIT_HOLD", 402)

    intake = fx.read_intake(api, second_id)
    assert intake["custody_state"] == "PACKAGED"
    assert intake["compliance_state"] == "MANIFEST_CLOSED"
    assert intake["released_at"] is None


def test_voiding_the_posted_settlement_clears_the_hold_and_unblocks_release(api):
    """Voiding the posted settlement returns the payable balance, drops the credit
    hold and lets the waiting shipment release.

    PRD §3.9: "The supplier's `payable_balance_cents` decreases by
    `posted_amount_cents` and `posted_amount_cents` resets to 0, which restores the
    supplier obligation invariant of §2.10 precisely."

    Design: Difficulty/cross_entity_state_dependency/release_blocked_while_supplier_credit_hold_true
    """
    ctx = _second_shipment_behind_a_credit_hold(api)

    voided = fx.void_settlement(
        api, ctx["settlement"]["id"], "Umpire assay pending; reverse the posting"
    )
    assert voided["state"] == "VOIDED"
    assert voided["posted_amount_cents"] == 0

    supplier = fx.read_supplier(api, ctx["supplier"]["id"])
    assert supplier["payable_balance_cents"] == 0
    assert supplier["credit_hold"] is False

    released = validate_success(
        api.release_intake(ctx["second"]["intake"]["id"], fx.OPERATOR)
    )
    assert released["custody_state"] == "RELEASED"
    assert released["released_at"] == "2026-08-20T00:00:00.000Z"
