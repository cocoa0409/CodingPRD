"""The two delivery-fee variants, the billing freeze and settlement."""

import pytest

from test_helpers import (
    ADMIN,
    WAREHOUSE,
    WAREHOUSE_RELEASER_ID,
    ApiErrorId,
    allocate,
    create_truck,
    donation_item_payload,
    fee_settlement_payload,
    get_run,
    get_stop,
    list_waitlist,
    prepare_offer_for_intake,
    release_quarantine,
    run_intake,
    set_clock,
    settle_fee,
    setup_allocated_voucher,
    setup_delivered_voucher,
    setup_issued_voucher,
    supply_stock,
    validate_error,
    validate_paginated,
    validate_success,
    voucher_line_payload,
)
from test_helpers.assertions import assert_voucher_money_identity


def _delivered_out_of_a_northern_run():
    """A CENTRAL household's BED quoted provisionally, then invoiced out of a
    NORTH run."""
    set_clock("2026-08-04T09:00:00Z")
    return setup_delivered_voucher(
        lines=[voucher_line_payload("BED", 1, "B")],
        offer_items=[donation_item_payload("BED", "B", False, 30.0)],
        run_county="NORTH", truck_label="BOX-1",
        agency_name="Riverbend Family Services",
    )


def _capped_fee_scenario():
    """A large SOUTH household whose upholstered donation quarantines, is
    released and then prices out above the fee cap."""
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_issued_voucher(
        lines=[voucher_line_payload("SOFA", 1, "C"),
               voucher_line_payload("BED", 1, "C")],
        categories=["SOFA", "BED"], urgency="EMERGENCY",
        agency_county="SOUTH", quota=5, household_size=6,
        client_county="SOUTH", has_infant=True, agency_name="Southgate Aid",
    )
    truck = create_truck(label="BOX-2", capacity_cubic_feet=600,
                         home_county="SOUTH", crew_minimum=1)
    supply = supply_stock(
        truck["id"],
        [donation_item_payload("SOFA", "B", True, 120.0),
         donation_item_payload("BED", "B", False, 90.0),
         donation_item_payload("DRESSER", "C", False, 10.0)],
        grades=["B", "B", "C"],
        pickup_county="SOUTH", donor_name="Marcus Hill", donor_phone="555-0111",
    )
    set_clock("2026-08-18T09:00:00Z")
    released = release_quarantine(supply["offer"]["id"], WAREHOUSE_RELEASER_ID)
    allocated = allocate(scenario["voucher"]["id"], scenario["voucher"]["version"])
    scenario.update({"truck": truck, "supply": supply, "released": released,
                     "allocated": allocated})
    return scenario


def _waived_voucher_awaiting_a_second_bed():
    """A two-BED voucher half filled, waived, and then topped up once a second
    BED reaches the floor."""
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_allocated_voucher(
        lines=[voucher_line_payload("BED", 2, "B")],
        offer_items=[donation_item_payload("BED", "B", False, 30.0)],
        truck_label="BOX-4", agency_name="Eastport Family Trust",
    )
    scenario["waitlist_entry"] = list_waitlist(
        client_id=scenario["client"]["id"], status="WAITING"
    )[0]
    scenario["waived"] = settle_fee(scenario["voucher"]["id"], "WAIVE")

    second = prepare_offer_for_intake(
        scenario["truck"]["id"],
        [donation_item_payload("BED", "B", False, 30.0)],
        donor_name="Omar Haddad", donor_phone="555-0155",
        window_start="2026-08-04T13:00:00Z", window_end="2026-08-04T15:00:00Z",
    )
    run_intake(second["offer"]["id"], second["items"])
    scenario["second_offer"] = second
    return scenario


# ─── Difficulty: provisional county versus final county ────────────────

def test_provisional_quote_prices_the_households_own_county(api):
    """PRD §3.9: "The first differing input is the service county. The
    provisional quote uses the household's own `county` — where the family
    lives, which is what the case manager was quoted. The final invoice uses the
    `county` of the delivery run that actually served the stop — where the truck
    actually drove."
    PRD §3.9: "From that basis the gross fee is assembled in a strict order.
    First, a base amount is taken from the service county: 4000 cents for
    `NORTH`, 3000 cents for `CENTRAL`, and 5000 cents for `SOUTH`."
    PRD §3.9: "The **provisional** variant runs on every allocation round and on
    every operational-cycle promotion that touches the voucher, and writes
    `fee_basis` `PROVISIONAL`."

    Design: Difficulty/dual_variant_calc/fee_provisional_client_county_vs_final_run_county
    """
    scenario = _delivered_out_of_a_northern_run()
    quote = scenario["allocated"]

    assert quote["gross_fee_cents"] == 5700, (
        "CENTRAL 3000 plus one bulk increment of 1200 plus the 1500 lift surcharge"
    )
    assert quote["subsidy_cents"] == 3990, "a four-person household is 70 percent subsidised"
    assert quote["client_due_cents"] == 1710
    assert quote["fee_basis"] == "PROVISIONAL"
    assert_voucher_money_identity(quote)


def test_final_invoice_reprices_on_the_county_the_truck_actually_served(api):
    """PRD §3.9: "Identical stock delivered out of a differently-countied run
    therefore produces a different `gross_fee_cents`, `subsidy_cents` and
    `client_due_cents` than the quote did."
    PRD §3.9: "The second differing input is the stock filter. The stock basis
    is always the set of inventory units whose `reserved_for_voucher_line_id`
    points at a line of *this* voucher; the provisional variant counts those
    whose `status` is `RESERVED` or `STAGED`, while the final variant counts
    only those whose `status` is `DELIVERED`."
    PRD §3.8: "The voucher moves `SCHEDULED → DELIVERED`, which recomputes its
    money fields with the final fee variant and sets `fee_basis` to `FINAL`. The
    household's `lifetime_vouchers_delivered` rises by 1. The owning referral
    moves `APPROVED → FULFILLED`."

    Design: Difficulty/dual_variant_calc/fee_provisional_client_county_vs_final_run_county
    """
    scenario = _delivered_out_of_a_northern_run()

    voucher_now = validate_success(api.get_voucher(scenario["voucher"]["id"], ADMIN))
    assert voucher_now["gross_fee_cents"] == 6700, (
        "NORTH 4000 plus one bulk increment of 1200 plus the 1500 lift surcharge"
    )
    assert voucher_now["subsidy_cents"] == 4690
    assert voucher_now["client_due_cents"] == 2010
    assert voucher_now["fee_basis"] == "FINAL"
    assert voucher_now["status"] == "DELIVERED"
    assert voucher_now["fee_status"] == "PENDING", "the billing axis has not moved"
    assert_voucher_money_identity(voucher_now)

    referral_now = validate_success(api.get_referral(scenario["referral"]["id"], ADMIN))
    assert referral_now["status"] == "FULFILLED"

    household = validate_success(api.get_client(scenario["client"]["id"], ADMIN))
    assert household["lifetime_vouchers_delivered"] == 1

    assert get_run(scenario["run"]["id"])["status"] == "COMPLETED"
    stop_now = get_stop(scenario["run"]["id"], scenario["stop"]["id"])
    assert stop_now["chargeback_cents"] == 0, "a successful delivery bills nothing"


# ─── Difficulty: the fee cap and the subsidy clamp ─────────────────────

def test_gross_fee_is_capped_and_the_infant_bonus_clamps_the_subsidy(api):
    """PRD §3.9: "Third, a lift surcharge of 1500 cents is added when the basis
    contains at least one unit whose `category` is `BED` or `SOFA`, and nothing
    otherwise. Fourth, the sum of those three components is capped:
    `gross_fee_cents` is the lesser of that sum and 9000 cents."
    PRD §3.9: "It starts from the household's size tier: 0.50 for a
    `household_size` of 2 or fewer, 0.70 for a `household_size` of 3 or 4, and
    0.90 for a `household_size` of 5 or more. If the household's `has_infant` is
    true, 0.10 is added, with the result capped at 1.00."
    PRD §3.9: "Money is then settled with exactly one rounding step:
    `subsidy_cents` is `gross_fee_cents` multiplied by that percentage, rounded
    half up to whole cents, and `client_due_cents` is `gross_fee_cents` minus
    `subsidy_cents`, never re-rounded."

    Design: Difficulty/combinatorial_formula/fee_cap_then_subsidy_clamp_nested_min_max
    """
    scenario = _capped_fee_scenario()
    money = scenario["allocated"]

    assert money["gross_fee_cents"] == 9000, (
        "SOUTH 5000 plus five bulk increments of 1200 plus the 1500 lift surcharge "
        "is 12500, which the cap trims to 9000"
    )
    assert money["subsidy_cents"] == 9000, (
        "0.90 for six people plus the 0.10 infant bonus clamps at 1.00"
    )
    assert money["client_due_cents"] == 0
    assert money["fee_basis"] == "PROVISIONAL"
    assert money["status"] == "ALLOCATED"
    assert money["fill_ratio"] == pytest.approx(1.0, abs=0.0005)
    assert_voucher_money_identity(money)


def test_upholstered_donation_quarantines_then_releases_before_allocation(api):
    """PRD §3.4: "Step one takes a pre-decision snapshot over *all* submitted
    pieces of the offer: `declared_soft_ratio` is the number of pieces whose
    `soft_surface` is true divided by the total number of pieces, rounded half
    up to three decimal places."
    PRD §3.5: "The offer's `quarantine_started_at` is set to the current
    instant, and `quarantine_release_due_at` is set to that instant plus 21 days
    when a live pest fired anywhere on the offer, or plus 14 days when the risk
    came only from upholstery."
    PRD §3.5: "Release moves the offer `QUARANTINED → RELEASED` and moves every
    inventory unit sourced from that offer still sitting in `QUARANTINED` to
    `AVAILABLE`, restamping each unit's `available_since` to the release instant
    and bumping each unit's `version` along with the offer's."

    Design: Difficulty/combinatorial_formula/fee_cap_then_subsidy_clamp_nested_min_max
    """
    scenario = _capped_fee_scenario()
    offer = scenario["supply"]["offer"]

    assert offer["declared_soft_ratio"] == pytest.approx(0.333, abs=0.0005), (
        "one of three submitted pieces is upholstered"
    )
    assert offer["accepted_item_count"] == 3, "the soft ratio is below the reject floor"
    assert offer["quarantine_release_due_at"] == "2026-08-18T09:00:00.000Z"
    assert scenario["released"]["status"] == "RELEASED"

    dressers, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "AVAILABLE",
                                             "category": "DRESSER", "limit": 100})
    )
    assert len(dressers) == 1, "the dresser was never requested and stays on the floor"


# ─── Difficulty: the two voucher axes and the billing freeze ───────────

def test_a_partially_allocated_voucher_can_be_waived_on_the_billing_axis(api):
    """PRD §3.9: "Waiving requires `fee_status` `PENDING` and requires the
    voucher's fulfilment `status` not to be `CANCELLED`; it moves `PENDING →
    WAIVED`, sets `subsidy_cents` equal to `gross_fee_cents`, sets
    `client_due_cents` to 0, and bumps the voucher's `version`."
    PRD §3.3: "The two advance on different triggers and, apart from one
    deliberate coupling described in §3.9, do not read each other."

    Design: Difficulty/non_linear_state_machine/voucher_fulfilment_and_billing_axes_advance_independently
    """
    scenario = _waived_voucher_awaiting_a_second_bed()

    assert scenario["allocated"]["status"] == "PARTIALLY_ALLOCATED"
    assert scenario["allocated"]["fill_ratio"] == pytest.approx(0.5, abs=0.0005)
    assert scenario["allocated"]["gross_fee_cents"] == 5700

    waived = scenario["waived"]
    assert waived["fee_status"] == "WAIVED"
    assert waived["subsidy_cents"] == 5700, "the waiver hands the whole gross fee back"
    assert waived["client_due_cents"] == 0
    assert waived["status"] == "PARTIALLY_ALLOCATED", (
        "the fulfilment axis is untouched by a billing move"
    )


def test_billing_freeze_keeps_the_money_fields_across_a_top_up_round(api):
    """PRD §3.9: "**The billing freeze.** `gross_fee_cents`, `subsidy_cents`,
    `client_due_cents` and `fee_basis` are written only while the voucher's
    `fee_status` is still `PENDING`. Once the billing axis has left `PENDING` —
    to `WAIVED`, `INVOICED`, `PAID` or `WRITTEN_OFF` — those four fields are
    frozen: later allocation rounds, waitlist promotions and even the final
    variant still perform all of their state changes, but they must not
    overwrite the four money fields."
    PRD §3.6: "A top-up round against an already partly filled voucher that
    completes it moves it `PARTIALLY_ALLOCATED → ALLOCATED`, reserves the
    selected units, moves the matching waitlist entries to `PROMOTED`, and
    recomputes the provisional money fields."

    Design: Difficulty/non_linear_state_machine/voucher_fulfilment_and_billing_axes_advance_independently
    """
    scenario = _waived_voucher_awaiting_a_second_bed()

    topped_up = allocate(scenario["voucher"]["id"], scenario["waived"]["version"])

    assert topped_up["status"] == "ALLOCATED", "the fulfilment axis completes"
    assert topped_up["fee_status"] == "WAIVED", "the billing axis is unchanged"
    assert topped_up["fill_ratio"] == pytest.approx(1.0, abs=0.0005)
    assert topped_up["gross_fee_cents"] == 5700, (
        "the second bed does not reprice a frozen voucher"
    )
    assert topped_up["subsidy_cents"] == 5700
    assert topped_up["client_due_cents"] == 0

    entry_now = validate_success(
        api.get_waitlist_entry(scenario["waitlist_entry"]["id"], ADMIN)
    )
    assert entry_now["status"] == "PROMOTED"
    assert entry_now["quantity_unmet"] == 0


# ─── Corner: the lift surcharge, and the settlement edges ──────────────

def test_fee_omits_the_lift_surcharge_when_no_bed_or_sofa_is_allocated(api):
    """PRD §3.9: "Third, a lift surcharge of 1500 cents is added when the basis
    contains at least one unit whose `category` is `BED` or `SOFA`, and nothing
    otherwise."
    PRD §3.9: "It starts from the household's size tier: 0.50 for a
    `household_size` of 2 or fewer, 0.70 for a `household_size` of 3 or 4, and
    0.90 for a `household_size` of 5 or more."

    Design: Corner/calculations/corner_fee_omits_lift_surcharge_when_no_bed_or_sofa_allocated
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_allocated_voucher(
        lines=[voucher_line_payload("DRESSER", 1, "B")],
        offer_items=[donation_item_payload("DRESSER", "B", False, 20.0)],
        truck_label="BOX-33", household_size=1, agency_name="Dunmore Assistance",
    )
    money = scenario["allocated"]

    assert money["gross_fee_cents"] == 4200, (
        "CENTRAL 3000 plus one bulk increment of 1200 and no lift surcharge"
    )
    assert money["subsidy_cents"] == 2100, "a one-person household is 50 percent subsidised"
    assert money["client_due_cents"] == 2100
    assert money["fee_basis"] == "PROVISIONAL"
    assert money["status"] == "ALLOCATED"
    assert_voucher_money_identity(money)


def test_invoicing_a_voucher_that_was_never_delivered_is_refused(api):
    """PRD §3.9: "Invoicing is the single fee edge that reads the fulfilment
    axis: it requires `fee_status` `PENDING` *and* requires the voucher's
    `status` to be `DELIVERED`, so that the final fee variant has already run,
    and it moves `PENDING → INVOICED` and bumps `version`."
    PRD §3.9: "Any settlement action with no outgoing edge from the voucher's
    current `fee_status` — including an invoice attempt while the voucher is not
    `DELIVERED` — is rejected with `ERR_FEE_STATE_INVALID`."

    Design: Corner/validations/corner_fee_invoice_before_delivery_rejected
    """
    scenario = setup_issued_voucher(
        lines=[voucher_line_payload("BED", 1, "B")],
        agency_name="Mossvale Family Line",
    )

    response = api.settle_voucher_fee(
        scenario["voucher"]["id"], fee_settlement_payload("INVOICE"), ADMIN
    )
    validate_error(response, ApiErrorId.ERR_FEE_STATE_INVALID.value, 409)

    voucher_now = validate_success(api.get_voucher(scenario["voucher"]["id"], ADMIN))
    assert voucher_now["fee_status"] == "PENDING"
    assert voucher_now["status"] == "ISSUED"


def test_payment_must_match_the_client_due_exactly_before_it_settles(api):
    """PRD §3.9: "Recording a payment requires `fee_status` `INVOICED` and
    requires the supplied `amount_cents` to equal `client_due_cents` exactly,
    otherwise `ERR_FEE_AMOUNT_MISMATCH`; it moves `INVOICED → PAID`, writes the
    supplied amount into `amount_paid_cents`, and bumps `version`."
    PRD §3.9: "Invoicing is the single fee edge that reads the fulfilment axis:
    it requires `fee_status` `PENDING` *and* requires the voucher's `status` to
    be `DELIVERED`, so that the final fee variant has already run, and it moves
    `PENDING → INVOICED` and bumps `version`."

    Design: Corner/validations/corner_record_payment_amount_mismatch_then_exact_amount_settles
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_delivered_voucher(
        lines=[voucher_line_payload("BED", 1, "B")],
        offer_items=[donation_item_payload("BED", "B", False, 30.0)],
        run_county="CENTRAL", truck_label="BOX-46",
        agency_name="Pembroke Household Trust",
    )
    invoiced = settle_fee(scenario["voucher"]["id"], "INVOICE")
    assert invoiced["fee_status"] == "INVOICED"
    assert invoiced["client_due_cents"] == 1710

    mismatch = api.settle_voucher_fee(
        scenario["voucher"]["id"],
        fee_settlement_payload("RECORD_PAYMENT", 1000), ADMIN,
    )
    validate_error(mismatch, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH.value, 422)

    paid = validate_success(
        api.settle_voucher_fee(
            scenario["voucher"]["id"],
            fee_settlement_payload("RECORD_PAYMENT", 1710), ADMIN,
        )
    )
    assert paid["fee_status"] == "PAID"
    assert paid["amount_paid_cents"] == 1710
    assert paid["status"] == "DELIVERED"
    assert paid["fee_basis"] == "FINAL"

    referral_now = validate_success(api.get_referral(scenario["referral"]["id"], ADMIN))
    assert referral_now["status"] == "FULFILLED"
