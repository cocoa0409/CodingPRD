"""Conservation of lead mass in kilograms and of core-deposit liability in cents."""

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers.assertions import assert_close
from test_helpers.factories import core_transition_payload
from test_helpers.fixtures import World

from prd_bench_local_runner.testing import validate_error


def test_shipping_two_lead_units_moves_mass_out_of_inventory_and_closes_at_zero(
    shipped_unit_world: World,
):
    """Each shipment moves 300.000 kg from on-hand inventory into the field.

    "`lead_inventory_kg` decreases and `lead_in_field_kg` increases by `declared_lead_kg`, keeping
    the lead mass variance at exactly 0.000". Two units off a 10000.000 kg opening inventory
    therefore read 9400.000 on hand and 600.000 in the field with nothing recycled yet.

    Design: Difficulty/compensating_invariant/invariant_l1_lead_mass_balance_closes_through_shipment_and_core_return
    """
    world = shipped_unit_world

    assert_close(world.unit_a["declared_lead_kg"], 300.000, "declared_lead_kg", 3)
    assert world.unit_a["core_status"] == C.CORE_DEPOSIT_HELD
    assert world.unit_b["core_status"] == C.CORE_DEPOSIT_HELD

    balance = world.read_mass_balance()
    assert_close(balance["lead_inventory_kg"], 9400.000, "lead_inventory_kg", 3)
    assert_close(balance["lead_in_field_kg"], 600.000, "lead_in_field_kg", 3)
    assert_close(balance["lead_recycled_kg"], 0.000, "lead_recycled_kg", 3)
    assert_close(balance["lead_mass_variance_kg"], 0.000, "lead_mass_variance_kg", 3)


def test_a_weighing_two_percent_over_the_manifest_is_received_but_more_is_refused(
    shipped_unit_world: World,
):
    """The reconciliation tolerance on a 300.000 kg manifest is exactly plus or minus 6.000 kg.

    "A variance of exactly 2.00 percent is **accepted**; only a larger one is refused, with
    `ERR_CORE_MASS_VARIANCE_EXCEEDED`." So 307.000 kg is turned away while 306.000 kg weighs in,
    and the refused attempt leaves `received_lead_kg` null.

    Design: Difficulty/compensating_invariant/invariant_l1_lead_mass_balance_closes_through_shipment_and_core_return
    """
    world = shipped_unit_world
    unit_a = world.unit_a["id"]
    world.open_core_return(unit_a, "CM-0001")
    world.core_transition(unit_a, C.CORE_ACTION_SHIP)

    validate_error(
        world.api.transition_core_return(
            unit_a,
            core_transition_payload(C.CORE_ACTION_RECEIVE, 307.000),
            world.warranty,
        ),
        E.ERR_CORE_MASS_VARIANCE_EXCEEDED,
    )
    refused = world.read_unit(unit_a)
    assert refused["received_lead_kg"] is None
    assert refused["core_status"] == C.CORE_IN_TRANSIT

    accepted = world.core_transition(unit_a, C.CORE_ACTION_RECEIVE, 306.000)
    assert_close(accepted["received_lead_kg"], 306.000, "received_lead_kg", 3)
    assert accepted["core_status"] == C.CORE_RECEIVED


def test_mass_moves_once_at_receipt_and_the_weighing_account_is_kept_separately(
    shipped_unit_world: World,
):
    """The two opposite weighing errors cancel in a second, independent account.

    "the mass itself moves partitions: `declared_lead_kg` leaves `lead_in_field_kg` and enters
    `lead_recycled_kg` in the same write, so the lead mass variance stays at exactly 0.000. The
    deposit is deliberately **not** settled at receipt." A later RECYCLE moves no mass a second
    time, so both cores end up recycled at 600.000 kg while the plus 6.000 and minus 6.000
    weighings net to 0.000 in `core_lead_variance_kg`.

    Design: Difficulty/compensating_invariant/invariant_l1_lead_mass_balance_closes_through_shipment_and_core_return
    """
    world = shipped_unit_world
    unit_a = world.unit_a["id"]
    unit_b = world.unit_b["id"]

    world.open_core_return(unit_a, "CM-0001")
    world.core_transition(unit_a, C.CORE_ACTION_SHIP)
    world.core_transition(unit_a, C.CORE_ACTION_RECEIVE, 306.000)

    mid = world.read_mass_balance()
    assert_close(mid["lead_in_field_kg"], 300.000, "lead_in_field_kg", 3)
    assert_close(mid["lead_recycled_kg"], 300.000, "lead_recycled_kg", 3)
    assert_close(mid["core_lead_variance_kg"], 6.000, "core_lead_variance_kg", 3)

    recycled = world.core_transition(unit_a, C.CORE_ACTION_RECYCLE)
    assert recycled["core_status"] == C.CORE_RECYCLED

    world.open_core_return(unit_b, "CM-0002")
    world.core_transition(unit_b, C.CORE_ACTION_SHIP)
    received_b = world.core_transition(unit_b, C.CORE_ACTION_RECEIVE, 294.000)
    assert received_b["core_status"] == C.CORE_RECEIVED

    final = world.read_mass_balance()
    assert_close(final["lead_inventory_kg"], 9400.000, "lead_inventory_kg", 3)
    assert_close(final["lead_in_field_kg"], 0.000, "lead_in_field_kg", 3)
    assert_close(final["lead_recycled_kg"], 600.000, "lead_recycled_kg", 3)
    assert_close(final["lead_mass_variance_kg"], 0.000, "lead_mass_variance_kg", 3)
    assert_close(final["core_lead_variance_kg"], 0.000, "core_lead_variance_kg", 3)


def test_the_refund_route_closes_exactly_one_deposit_and_receipt_closes_none(
    shipped_unit_world: World,
):
    """Two lead-acid shipments open 25000 cents of liability that only RECYCLE refunds.

    "`core_deposit_liability_cents` increases by the standard core deposit of 12500 cents **for
    lead-acid units only**." Receipt issues nothing, and then "`core_credit_issued_cents` is set to
    the 12500-cent deposit and the plant's `core_deposit_liability_cents` is reduced by the same
    amount, so the liability opened at shipment closes exactly."

    Design: Difficulty/compensating_invariant/invariant_c1_core_deposit_liability_closes_by_refund_or_by_forfeit
    """
    world = shipped_unit_world
    unit_a = world.unit_a["id"]

    opening = world.read_mass_balance()
    assert opening["core_deposit_liability_cents"] == 25000

    world.open_core_return(unit_a, "CM-0101")
    world.core_transition(unit_a, C.CORE_ACTION_SHIP)
    received = world.core_transition(unit_a, C.CORE_ACTION_RECEIVE, 300.000)
    assert received["core_credit_issued_cents"] == 0
    assert world.read_mass_balance()["core_deposit_liability_cents"] == 25000

    recycled = world.core_transition(unit_a, C.CORE_ACTION_RECYCLE)
    assert recycled["core_status"] == C.CORE_RECYCLED
    assert recycled["core_credit_issued_cents"] == 12500
    assert world.read_mass_balance()["core_deposit_liability_cents"] == 12500


def test_the_forfeit_route_closes_the_last_deposit_without_ever_issuing_a_credit(
    shipped_unit_world: World,
):
    """REJECT discharges the liability to zero while the cash account stops at 12500.

    "`core_credit_issued_cents` stays 0 and `core_deposit_liability_cents` is still reduced by
    12500, because the liability is discharged either way", and because "any action from the wrong
    state is `ERR_CORE_STATE_INVALID`, and `RECYCLED` and `REJECTED` are both terminal" a forfeited
    deposit can never be refunded afterwards.

    Design: Difficulty/compensating_invariant/invariant_c1_core_deposit_liability_closes_by_refund_or_by_forfeit
    """
    world = shipped_unit_world
    unit_a = world.unit_a["id"]
    unit_b = world.unit_b["id"]

    world.open_core_return(unit_a, "CM-0101")
    world.core_transition(unit_a, C.CORE_ACTION_SHIP)
    world.core_transition(unit_a, C.CORE_ACTION_RECEIVE, 300.000)
    credited = world.core_transition(unit_a, C.CORE_ACTION_RECYCLE)

    world.open_core_return(unit_b, "CM-0102")
    world.core_transition(unit_b, C.CORE_ACTION_SHIP)
    rejected = world.core_transition(unit_b, C.CORE_ACTION_REJECT)
    assert rejected["core_status"] == C.CORE_REJECTED
    assert rejected["core_credit_issued_cents"] == 0

    validate_error(
        world.api.transition_core_return(
            unit_b, core_transition_payload(C.CORE_ACTION_RECYCLE), world.warranty
        ),
        E.ERR_CORE_STATE_INVALID,
    )
    assert world.read_unit(unit_b)["core_credit_issued_cents"] == 0

    closing = world.read_mass_balance()
    assert closing["core_deposit_liability_cents"] == 0
    assert (
        credited["core_credit_issued_cents"] + rejected["core_credit_issued_cents"]
    ) == 12500
    assert_close(closing["lead_in_field_kg"], 0.000, "lead_in_field_kg", 3)
    assert_close(closing["lead_recycled_kg"], 600.000, "lead_recycled_kg", 3)
    assert_close(closing["lead_mass_variance_kg"], 0.000, "lead_mass_variance_kg", 3)
