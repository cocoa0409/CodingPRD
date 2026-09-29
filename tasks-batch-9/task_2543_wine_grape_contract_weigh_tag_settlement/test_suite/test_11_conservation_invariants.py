"""One over-delivered harvest, read twice as a conservation problem: first in tons,
where four slices and three ledger buckets must account for every pound delivered, and
then in cents, where three independently rounded percentages must still sum to the exact
net payable."""
from test_helpers import (
    capture_gross,
    capture_tare,
    close_settlement,
    dispute_grading,
    list_installments,
    list_settlement_lines,
    move_clock,
    read_appointment,
    read_contract,
    read_grower,
    read_weigh_tag,
    record_grading,
    setup_harvest_ready,
    setup_scheduled_appointment,
    single_installment_plan,
)

SETUP_AT = "2026-08-20T08:00:00Z"
TARGET_PICK_AT = "2026-08-25T14:00:00Z"
SETTLEMENT_CLOSED_AT = "2026-08-28T09:00:00Z"
DISPUTE_AT = "2026-08-26T09:00:00Z"

# Three slots on one lane, and the inbound pass each truck makes inside its own window.
SLOTS = (
    ("2026-08-25T14:00:00Z", "2026-08-25T16:00:00Z", 22.000),
    ("2026-08-25T17:00:00Z", "2026-08-25T19:00:00Z", 18.000),
    ("2026-08-25T20:00:00Z", "2026-08-25T22:00:00Z", 25.000),
)
GROSS_PASSES = (
    ("2026-08-25T14:30:00Z", 61240),
    ("2026-08-25T17:30:00Z", 53000),
    ("2026-08-25T20:30:00Z", 67000),
)
# tare pounds and lab Brix per load; the net tons are 22.000, 18.000 and 25.000.
LOADS = ((17240, 28.0), (17000, 21.5), (17000, 21.5))


def _pad_with_the_third_truck_on_the_scale(installment_plan=None) -> dict:
    """A 40.000-ton contract whose three trucks have *all* weighed in before any of
    them is tared, so no slot can still be cancelled by a cap cascade.

    The first two loads are tared and graded — filling the soft cap exactly — and the
    third is tared and left ungraded on the scale.
    """
    move_clock(SETUP_AT)
    ctx = setup_harvest_ready(
        contract_overrides={
            "contract_basis": "TONNAGE",
            "base_price_per_ton_cents": 450000,
            "committed_tons": 40.000,
            "over_delivery_policy": "ACCEPT_AT_SPOT",
            "spot_price_pct": 70.0,
            "over_delivery_tolerance_pct": 10.0,
            "provisional_payment_pct": 60.0,
            "lien_holdback_pct": 5.0,
            "settlement_basis": "LOAD_BY_LOAD",
            "installment_plan": installment_plan or single_installment_plan(),
        },
        lane_overrides={
            "lane_code": "L1",
            "daily_capacity_tons": 80.000,
            "turnaround_buffer_minutes": 30,
            "max_load_tons": 40.0,
        },
        estimated_tons=65.000,
        target_pick_at=TARGET_PICK_AT,
        block_overrides={"acres": 35.000},
    )
    for window_start, window_end, planned_tons in SLOTS:
        setup_scheduled_appointment(ctx, window_start, window_end, planned_tons=planned_tons)

    tags = []
    for index, (arrival_at, gross_weight_lbs) in enumerate(GROSS_PASSES):
        move_clock(arrival_at)
        tags.append(
            capture_gross(ctx["appointments"][index]["id"], ctx["block"]["id"], gross_weight_lbs)
        )
    ctx["tags"] = tags

    for index, (tare_weight_lbs, brix) in enumerate(LOADS):
        capture_tare(tags[index]["id"], tare_weight_lbs)
        if index < 2:
            record_grading(
                tags[index]["id"], brix=brix, ta_gl=6.5, ph=3.60 if index == 0 else 3.30,
                rot_pct=1.0, mog_pct=0.5,
            )
    return ctx


def _grade_the_over_delivery(ctx: dict) -> dict:
    """Grade the third load, which arrives with the soft cap already full."""
    return record_grading(
        ctx["tags"][2]["id"], brix=21.5, ta_gl=6.5, ph=3.30, rot_pct=1.0, mog_pct=0.5
    )


def _slices(tag: dict) -> tuple:
    return (
        float(tag["contract_slice_tons"]),
        float(tag["over_slice_tons"]),
        float(tag["over_rejected_tons"]),
        float(tag["excess_rejected_tons"]),
    )


# --- Conservation in TONS ---------------------------------------------------------


def test_the_over_delivered_loads_four_slices_sum_to_its_net_tonnage():
    """25.000 tons meet a full soft cap and a 4.000-ton tolerance band: nothing goes to
    the contract bucket, 4.000 to the band, and the 21.000-ton remainder is refused —
    and the four slices still add up to the load exactly.

    PRD: "The four slices always sum to exactly `net_tons`, each to 3 decimals rounded
    half up."

    Design: Difficulty/compensating_invariant/tonnage_conservation_across_over_delivery_and_dispute
    """
    ctx = _pad_with_the_third_truck_on_the_scale()
    _grade_the_over_delivery(ctx)

    tag = read_weigh_tag(ctx["tags"][2]["id"])
    assert tag["disposition"] == "PARTIALLY_ACCEPTED"
    assert _slices(tag) == (0.000, 4.000, 0.000, 21.000)
    assert sum(_slices(tag)) == float(tag["net_tons"]) == 25.000


def test_the_two_earlier_loads_conserve_their_tonnage_too():
    """Both loads fitted inside the soft cap, so each puts its whole net weight in the
    first bucket and nothing anywhere else.

    PRD: "Bucket one, contract tonnage, takes `contract_slice_tons` as the lesser of
    `net_tons` and the remaining soft capacity; the remainder of the load is what is left
    of `net_tons` after that slice."

    Design: Difficulty/compensating_invariant/tonnage_conservation_across_over_delivery_and_dispute
    """
    ctx = _pad_with_the_third_truck_on_the_scale()
    _grade_the_over_delivery(ctx)

    first = read_weigh_tag(ctx["tags"][0]["id"])
    second = read_weigh_tag(ctx["tags"][1]["id"])
    assert _slices(first) == (22.000, 0.000, 0.000, 0.000)
    assert _slices(second) == (18.000, 0.000, 0.000, 0.000)
    assert sum(_slices(first)) == float(first["net_tons"]) == 22.000
    assert sum(_slices(second)) == float(second["net_tons"]) == 18.000


def test_the_contract_ledger_accounts_for_every_delivered_ton():
    """The three ledger buckets — contract, over-delivery and rejected — sum to the
    65.000 tons that crossed the scale, and the hard cap is now reached.

    PRD: "`HARD_CAP_REACHED` once `delivered_contract_tons` plus `delivered_over_tons`
    reaches or exceeds `hard_cap_tons`."

    Design: Difficulty/compensating_invariant/tonnage_conservation_across_over_delivery_and_dispute
    """
    ctx = _pad_with_the_third_truck_on_the_scale()
    _grade_the_over_delivery(ctx)

    contract = read_contract(ctx["contract"]["id"])
    delivered = float(contract["delivered_contract_tons"])
    over = float(contract["delivered_over_tons"])
    rejected = float(contract["rejected_tons"])
    assert (delivered, over, rejected) == (40.000, 4.000, 21.000)
    assert delivered + over + rejected == 65.000
    assert contract["tonnage_status"] == "HARD_CAP_REACHED"


def test_only_the_band_slice_is_priced_and_it_is_priced_at_spot():
    """The refused 21.000 tons buy no settlement line at all; the 4.000-ton band slice
    gets one, struck off the spot base with the penalty still applied.

    PRD: "the base is `base_price_per_ton_cents` multiplied by `spot_price_pct` divided by
    100 and rounded half up to whole cents when `over_delivery_policy` is `ACCEPT_AT_SPOT`"

    Design: Difficulty/compensating_invariant/tonnage_conservation_across_over_delivery_and_dispute
    """
    ctx = _pad_with_the_third_truck_on_the_scale()
    _grade_the_over_delivery(ctx)

    lines = list_settlement_lines(weigh_tag_id=ctx["tags"][2]["id"])
    assert len(lines) == 1
    assert lines[0]["bucket"] == "OVER_DELIVERY"
    assert float(lines[0]["tons"]) == 4.000
    assert lines[0]["price_per_ton_cents"] == 308700
    assert lines[0]["gross_amount_cents"] == 1234800


def test_the_provisional_money_is_the_sum_of_the_three_provisional_lines():
    """60 percent of each line's gross, summed across the two contract lines and the
    single band line.

    PRD: "the third the sum of `provisional_amount_cents` over its `PROVISIONAL` lines."

    Design: Difficulty/compensating_invariant/tonnage_conservation_across_over_delivery_and_dispute
    """
    ctx = _pad_with_the_third_truck_on_the_scale()
    _grade_the_over_delivery(ctx)

    contract = read_contract(ctx["contract"]["id"])
    assert contract["provisional_settlement_cents"] == 11918880
    assert 6415200 + 4762800 + 740880 == contract["provisional_settlement_cents"]


def test_the_dispute_returns_the_ledger_to_exactly_the_soft_cap():
    """Contesting the over-delivered load unwinds it completely: its four slices go back
    to zero, its line is voided, and no residue of the 21.000 refused tons is left in the
    contract's rejected figure.

    PRD: "The tag's `contract_slice_tons`, `over_slice_tons`, `over_rejected_tons` and
    `excess_rejected_tons` all reset to 0.000, `active_adjustment_pct` is cleared, and the
    disposition moves to `DISPUTED`, where it waits for a re-grade."

    Design: Difficulty/compensating_invariant/tonnage_conservation_across_over_delivery_and_dispute
    """
    ctx = _pad_with_the_third_truck_on_the_scale()
    _grade_the_over_delivery(ctx)
    move_clock(DISPUTE_AT)
    dispute_grading(
        ctx["tags"][2]["id"], ctx["grower"]["id"], reason="grower contests the over-cap rejection"
    )

    tag = read_weigh_tag(ctx["tags"][2]["id"])
    assert tag["disposition"] == "DISPUTED"
    assert _slices(tag) == (0.000, 0.000, 0.000, 0.000)

    lines = list_settlement_lines(weigh_tag_id=tag["id"])
    assert len(lines) == 1
    assert lines[0]["status"] == "VOID"

    contract = read_contract(ctx["contract"]["id"])
    delivered = float(contract["delivered_contract_tons"])
    over = float(contract["delivered_over_tons"])
    rejected = float(contract["rejected_tons"])
    assert (delivered, over, rejected) == (40.000, 0.000, 0.000)
    assert delivered + over + rejected == 40.000


def test_the_dispute_leaves_the_first_two_loads_holding_the_cap():
    """Voiding one line returns capacity but does not reopen the contract: the two
    surviving loads still fill the soft cap, and only their money remains provisional.

    PRD: "In either case, consumption counts only lines whose status is `PROVISIONAL` or
    `FINAL` — voided lines are excluded, which is exactly what returns capacity to a
    contract after a dispute."

    Design: Difficulty/compensating_invariant/tonnage_conservation_across_over_delivery_and_dispute
    """
    ctx = _pad_with_the_third_truck_on_the_scale()
    _grade_the_over_delivery(ctx)
    move_clock(DISPUTE_AT)
    dispute_grading(ctx["tags"][2]["id"], ctx["grower"]["id"], reason="over-cap rejection contested")

    contract = read_contract(ctx["contract"]["id"])
    assert contract["tonnage_status"] == "CAP_REACHED"
    assert contract["provisional_settlement_cents"] == 11178000


def test_an_already_arrived_slot_is_never_cancelled_by_the_cap_cascade():
    """The third truck weighed in before the cap was reached, so the cascade that
    suspends the call could not touch its slot; the slot closed normally instead.

    PRD: "If the posture leaves `OPEN`, every pick call of the contract in `ISSUED` or
    `ACKNOWLEDGED` is suspended to `SUSPENDED_CAP`, the `SCHEDULED` appointments of those
    suspended calls are cancelled, and each affected lane's `committed_tons` and
    `scheduled_appointment_count` are recomputed."

    Design: Difficulty/compensating_invariant/tonnage_conservation_across_over_delivery_and_dispute
    """
    ctx = _pad_with_the_third_truck_on_the_scale()
    _grade_the_over_delivery(ctx)
    move_clock(DISPUTE_AT)
    dispute_grading(ctx["tags"][2]["id"], ctx["grower"]["id"], reason="over-cap rejection contested")

    appointment = read_appointment(ctx["appointments"][2]["id"])
    assert appointment["status"] == "CLOSED"
    assert appointment["status"] != "CANCELLED"


# --- Conservation in CENTS -------------------------------------------------------


def _settled_with_three_installments() -> dict:
    """The same three loads, split across a 45.5 / 27.25 / 27.25 payment plan and
    closed, with no dispute anywhere."""
    ctx = _pad_with_the_third_truck_on_the_scale(
        installment_plan=[
            {"installment_no": 1, "pct_of_settlement": 45.5, "due_offset_days": 30, "lien_protected": True},
            {"installment_no": 2, "pct_of_settlement": 27.25, "due_offset_days": 60, "lien_protected": True},
            {"installment_no": 3, "pct_of_settlement": 27.25, "due_offset_days": 90, "lien_protected": False},
        ]
    )
    _grade_the_over_delivery(ctx)
    move_clock(SETTLEMENT_CLOSED_AT)
    ctx["contract"] = close_settlement(ctx["contract"]["id"])
    ctx["installments"] = sorted(
        list_installments(contract_id=ctx["contract"]["id"]), key=lambda row: row["installment_no"]
    )
    return ctx


def test_the_settled_gross_is_each_line_at_the_price_it_was_struck_at():
    """Under load-by-load settlement nothing is re-priced, so the total is simply the
    three lines added up.

    PRD: "Under `LOAD_BY_LOAD`, every line keeps the price it was struck at: each line's
    `final_amount_cents` becomes its own `gross_amount_cents`, and the settlement total is
    the sum of those amounts."

    Design: Difficulty/compensating_invariant/money_conservation_in_installment_waterfall_residual
    """
    ctx = _settled_with_three_installments()

    assert ctx["contract"]["final_settlement_cents"] == 19864800
    assert 10692000 + 7938000 + 1234800 == 19864800


def test_the_credit_and_the_holdback_are_both_keyed_on_the_pre_credit_total():
    """A gross above 15,000,000 cents earns the top 1.5 percent tier, the holdback takes
    5 percent of the same figure, and the net payable is the sequential result.

    PRD: "Step five computes `net_payable_cents` as the settlement total plus
    `prompt_pay_credit_cents` less `lien_holdback_cents`."

    Design: Difficulty/compensating_invariant/money_conservation_in_installment_waterfall_residual
    """
    ctx = _settled_with_three_installments()
    contract = ctx["contract"]

    assert contract["prompt_pay_credit_cents"] == 297972
    assert contract["lien_holdback_cents"] == 993240
    assert contract["net_payable_cents"] == 19169532
    assert 19864800 + 297972 - 993240 == 19169532


def test_each_percentage_rounds_independently_against_the_net_payable():
    """45.5 percent and 27.25 percent of 19169532 cents are each rounded on their own,
    and each installment's due date is its own offset from the close.

    PRD: "Each receives a `planned_amount_cents` of `net_payable_cents` multiplied by its
    own `pct_of_settlement` divided by 100, rounded half up to whole cents, and a `due_at`
    of `settlement_closed_at` plus its own `due_offset_days` days."

    Design: Difficulty/compensating_invariant/money_conservation_in_installment_waterfall_residual
    """
    ctx = _settled_with_three_installments()
    first, second, third = ctx["installments"]

    assert first["planned_amount_cents"] == 8722137
    assert second["planned_amount_cents"] == 5223697
    assert first["due_at"] == "2026-09-27T09:00:00Z"
    assert second["due_at"] == "2026-10-27T09:00:00Z"
    assert third["due_at"] == "2026-11-26T09:00:00Z"


def test_the_residual_cent_is_absorbed_by_the_highest_installment():
    """The three independent roundings lose a cent; the last installment is one cent
    above its own rounded share so the schedule closes on the net payable exactly.

    PRD: "the residual — `net_payable_cents` less the sum of the planned amounts — is
    absorbed in full by the installment with the **highest** `installment_no`, added to
    its `planned_amount_cents`"

    Design: Difficulty/compensating_invariant/money_conservation_in_installment_waterfall_residual
    """
    ctx = _settled_with_three_installments()
    first, second, third = ctx["installments"]

    assert third["planned_amount_cents"] == 5223698
    assert third["planned_amount_cents"] == second["planned_amount_cents"] + 1
    planned = [row["planned_amount_cents"] for row in ctx["installments"]]
    assert sum(planned) == 19169532
    assert sum(planned) != 19169531
    assert first["planned_amount_cents"] == 8722137


def test_the_schedule_is_live_and_every_line_is_final():
    """Closing the vintage moves all three installments off the settlement waiting room
    and finalises the money behind them.

    PRD: "The close also stamps `settlement_closed_at` from the logical clock, flips every
    `PROVISIONAL` line to `FINAL`, transitions every installment `PENDING_SETTLEMENT →
    SCHEDULED`, recomputes the producer's `outstanding_lien_balance_cents`"

    Design: Difficulty/compensating_invariant/money_conservation_in_installment_waterfall_residual
    """
    ctx = _settled_with_three_installments()

    assert ctx["contract"]["settlement_closed_at"] == SETTLEMENT_CLOSED_AT
    for row in ctx["installments"]:
        assert row["status"] == "SCHEDULED"
        assert row["paid_amount_cents"] == 0

    lines = list_settlement_lines(contract_id=ctx["contract"]["id"])
    assert len(lines) == 3
    for line in lines:
        assert line["status"] == "FINAL"
        assert line["final_amount_cents"] == line["gross_amount_cents"]


def test_the_statutory_lien_covers_only_the_protected_installments():
    """Two of the three installments are lien-protected, so the producer-wide balance is
    their planned amounts and not the whole net payable.

    PRD: "which is the sum, over every installment of every contract of that producer
    whose `lien_protected` flag is true and whose status is `SCHEDULED`, `PARTIALLY_PAID`
    or `DELINQUENT`, of `planned_amount_cents` less `paid_amount_cents`."

    Design: Difficulty/compensating_invariant/money_conservation_in_installment_waterfall_residual
    """
    ctx = _settled_with_three_installments()

    grower = read_grower(ctx["grower"]["id"])
    assert grower["outstanding_lien_balance_cents"] == 13945834
    assert 8722137 + 5223697 == 13945834
