"""
Two calculations that each run in two variants over identical inputs.

A redemption line releases revenue twice: provisionally at allocation, reserved
at each consumed lot's own frozen breakage rate, and finally at fulfilment,
reserved at the programme's single current rate. And a settlement statement bills
the same measured legs differently depending on whether its agreement settles
gross or net.
"""

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_fields,
    assert_immutable_common_fields,
    assert_lot_split,
    assert_ok,
    assert_page,
    assert_statement_net,
)
from test_helpers.constants import (
    BASIS_GROSS,
    BASIS_NET,
    CLOCK_EPOCH,
    COHORT_C2_ADJUSTMENT_BP,
    COHORT_C2_ENROLLMENT_END,
    COHORT_C2_ENROLLMENT_START,
    COHORT_C2_OBSERVED_RATE_BP,
    COHORT_C2_SAMPLE_SIZE,
    DEFAULT_MIN_INVOICE_CENTS,
    DEFAULT_SEEDED_BREAKAGE_RATE_BP,
    ENTRY_TYPE_ALLOCATION,
    LOT_PARTIALLY_REDEEMED,
    REDEMPTION_ALLOCATED,
    REDEMPTION_FULFILLED,
    REDEMPTION_TYPE_PARTNER,
    STATEMENT_DRAFT,
    TIER_GOLD,
    TIER_SILVER,
)
from test_helpers.test_users import (
    ACCOUNTANT_HEADERS,
    CONTROLLER_HEADERS,
    PROGRAM_ADMIN_HEADERS,
)

# ─── The cohort-weighted world both redemption variants measure against ──────
# Cohort one observes 8200 bp with no adjustment; cohort two observes 400 bp with
# an adjustment of -300 bp, so its raw adjusted rate of 100 bp is lifted to the
# 200 bp floor before the weighting.
GOLD_BASE_POINTS = 4000
SILVER_BASE_POINTS = 250
SILVER_PROMO_MULTIPLIER_BP = 10300

# (8200 * 5000 + 200 * 266) / 5266 == 7795.898..., rounded half up.
MEASURED_REDEMPTION_RATE_BP = 7796
INSTALLED_BREAKAGE_RATE_BP = 2204

# ─── The one redemption line, released twice ─────────────────────────────────
REDEEMED_POINTS = 3000
LINE_GROSS_CENTS = 3600
# 3600 - round_half_up(3600 * 2500 / 10000) == 3600 - 900
PROVISIONAL_RELEASE_CENTS = 2700
# 3600 - round_half_up(3600 * 2204 / 10000) == 3600 - 793
FINAL_RELEASE_CENTS = 2807
REMEASUREMENT_DELTA_CENTS = 107
GOLD_LOT_REMAINING_POINTS = 2000

# ─── The two byte-identical partner agreements ───────────────────────────────
PARTNER_ISSUANCE_CAP = 200000
PARTNER_BASE_POINTS = 80000
PARTNER_ISSUED_POINTS = 80000
PARTNER_REDEEMED_POINTS = 3000
# 80000 * 900 / 1000 and 3000 * 1100 / 1000
ISSUANCE_RECEIVABLE_CENTS = 72000
REDEMPTION_PAYABLE_CENTS = 3300
GROSS_NET_DUE_CENTS = 72000
NET_NET_DUE_CENTS = 68700
BASIS_DELTA_CENTS = 3300
# Period end 2026-09-01T00:00:00Z advanced by 30 whole days.
STATEMENT_DUE_DATE = "2026-10-01T00:00:00Z"


def _cohort_weighted_world(api):
    """
    An ACTIVE programme with two enrolment vintages, a GOLD holder of a
    5000-point lot and a SILVER holder of a 266-point lot, all inside one OPEN
    period.
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api)
    fixtures.new_state_expiry_rule(api, program["id"])
    first_cohort = fixtures.new_cohort(api, program["id"])
    second_cohort = fixtures.new_cohort(
        api,
        program["id"],
        enrollment_start_date=COHORT_C2_ENROLLMENT_START,
        enrollment_end_date=COHORT_C2_ENROLLMENT_END,
        observed_redemption_rate_bp=COHORT_C2_OBSERVED_RATE_BP,
        sample_size=COHORT_C2_SAMPLE_SIZE,
        program_change_adjustment_bp=COHORT_C2_ADJUSTMENT_BP,
    )
    program = fixtures.activate(api, program["id"])
    gold_member = fixtures.new_member(
        api, program["id"], first_cohort["id"], tier=TIER_GOLD
    )
    silver_member = fixtures.new_member(
        api, program["id"], second_cohort["id"], tier=TIER_SILVER
    )
    period = fixtures.new_period(api, program["id"])
    gold_lot = fixtures.issue_lot(
        api, gold_member["id"], period["id"], base_points=GOLD_BASE_POINTS
    )
    silver_lot = fixtures.issue_lot(
        api,
        silver_member["id"],
        period["id"],
        base_points=SILVER_BASE_POINTS,
        promo_multiplier_bp=SILVER_PROMO_MULTIPLIER_BP,
    )
    return {
        "program": program,
        "gold_member": gold_member,
        "silver_member": silver_member,
        "period": period,
        "gold_lot": gold_lot,
        "silver_lot": silver_lot,
    }


def _world_with_installed_rate(api):
    """
    The same world, with an approved estimate that has already overwritten the
    programme's live breakage rate, so the lots' frozen 2500 bp and the
    programme's 2204 bp disagree.
    """
    world = _cohort_weighted_world(api)
    world["estimate"] = fixtures.approved_estimate(
        api, world["program"]["id"], world["period"]["id"]
    )
    return world


def _partner_pair_world(api):
    """
    Two partner agreements carrying identical rate cards, windows and activity
    and differing only in whether netting is enabled.
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api, per_issuance_point_cap=PARTNER_ISSUANCE_CAP)
    fixtures.new_state_expiry_rule(api, program["id"])
    cohort = fixtures.new_cohort(api, program["id"])
    program = fixtures.activate(api, program["id"])
    period = fixtures.new_period(api, program["id"])

    pair = {"program": program, "period": period}
    for label, netting in (("gross", False), ("net", True)):
        member = fixtures.new_member(api, program["id"], cohort["id"])
        agreement = fixtures.new_agreement(
            api, program["id"], net_settlement_enabled=netting
        )
        fixtures.issue_lot(
            api,
            member["id"],
            period["id"],
            base_points=PARTNER_BASE_POINTS,
            partner_agreement_id=agreement["id"],
        )
        fixtures.allocated_redemption(
            api,
            member["id"],
            period["id"],
            PARTNER_REDEEMED_POINTS,
            partner_agreement_id=agreement["id"],
            redemption_type=REDEMPTION_TYPE_PARTNER,
        )
        pair[f"{label}_member"] = member
        pair[f"{label}_agreement"] = agreement
    return pair


def test_provisional_release_reserves_at_each_lots_own_frozen_rate(api):
    """
    Allocation is the first of the two release variants. The consumed lot pinned
    2500 basis points at issuance and an approved estimate has since installed
    2204 on the programme, yet the allocation deducts the lot's own snapshot:
    3600 cents of line gross less a 900-cent reserve leaves 2700, while the
    final leg is still untouched at 0. The period books the provisional release
    into its redemption column alone.

    "It also records `provisional_release_cents` for the line: the line's gross less the reserve on that line, where the reserve is the line gross multiplied by **that lot's own** `breakage_rate_bp_at_issue`, divided by 10000, rounded half up."
    "Because the rate used is each lot's own frozen snapshot, a redemption spanning lots issued under different breakage rates blends several rates within one event."
    "The event's `provisional_release_cents` is added to the period's `redemption_recognized_cents`."
    "`breakage_rate_bp_at_issue` takes the programme's `current_breakage_rate_bp` as it stands at this instant."

    Design: Difficulty/dual_variant_calc/dual_variant_redemption_provisional_vs_final_release
    """
    world = _world_with_installed_rate(api)
    assert_fields(
        world["estimate"],
        estimated_redemption_rate_bp=MEASURED_REDEMPTION_RATE_BP,
        breakage_rate_bp=INSTALLED_BREAKAGE_RATE_BP,
    )
    program = assert_ok(api.get_program(world["program"]["id"], CONTROLLER_HEADERS))
    assert_fields(program, current_breakage_rate_bp=INSTALLED_BREAKAGE_RATE_BP)

    event = fixtures.allocated_redemption(
        api, world["gold_member"]["id"], world["period"]["id"], REDEEMED_POINTS
    )
    assert_fields(
        event,
        state=REDEMPTION_ALLOCATED,
        provisional_release_cents=PROVISIONAL_RELEASE_CENTS,
        final_release_cents=0,
        remeasurement_delta_cents=0,
        partner_cost_cents=0,
    )

    period = assert_ok(api.get_period(world["period"]["id"], CONTROLLER_HEADERS))
    assert_fields(
        period,
        redemption_recognized_cents=PROVISIONAL_RELEASE_CENTS,
        remeasurement_delta_cents=0,
    )

    lot = assert_ok(api.get_point_lot(world["gold_lot"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        lot,
        points_remaining=GOLD_LOT_REMAINING_POINTS,
        lifecycle_state=LOT_PARTIALLY_REDEEMED,
        breakage_rate_bp_at_issue=DEFAULT_SEEDED_BREAKAGE_RATE_BP,
    )


def test_final_release_reserves_at_the_single_current_programme_rate(api):
    """
    Fulfilment is the second variant over the very same line. It ignores the
    lot's 2500 basis point snapshot and deducts one reserve at the programme's
    current 2204, so the identical 3600 cents of line gross releases 2807 rather
    than 2700 and the re-measurement delta is exactly +107. The provisional leg
    is never overwritten, and the period carries the two legs in two separate
    columns.

    "For every `ALLOCATION` row of the event, `final_release_cents` is written as the row's `line_gross_ssp_cents` less the reserve on that line computed at the **single** current programme rate — the line gross multiplied by the programme's `current_breakage_rate_bp`, divided by 10000, rounded half up — ignoring the per-lot snapshots entirely."
    "The event's `final_release_cents` is the sum of those per-line finals, each rounded before being added, and the event's `remeasurement_delta_cents` is `final_release_cents` less `provisional_release_cents`."
    "That delta is added to the period's `remeasurement_delta_cents`, separately from the provisional release already booked."

    Design: Difficulty/dual_variant_calc/dual_variant_redemption_provisional_vs_final_release
    """
    world = _world_with_installed_rate(api)
    event = fixtures.allocated_redemption(
        api, world["gold_member"]["id"], world["period"]["id"], REDEEMED_POINTS
    )
    fulfilled = assert_ok(
        api.fulfill_redemption(event["id"], None, ACCOUNTANT_HEADERS)
    )
    assert_fields(
        fulfilled,
        state=REDEMPTION_FULFILLED,
        provisional_release_cents=PROVISIONAL_RELEASE_CENTS,
        final_release_cents=FINAL_RELEASE_CENTS,
        remeasurement_delta_cents=REMEASUREMENT_DELTA_CENTS,
    )
    assert (
        fulfilled["final_release_cents"] - fulfilled["provisional_release_cents"]
        == REMEASUREMENT_DELTA_CENTS
    ), "The delta must be the final release less the provisional release"

    period = assert_ok(api.get_period(world["period"]["id"], CONTROLLER_HEADERS))
    assert_fields(
        period,
        redemption_recognized_cents=PROVISIONAL_RELEASE_CENTS,
        remeasurement_delta_cents=REMEASUREMENT_DELTA_CENTS,
    )


def test_one_journal_row_carries_both_release_variants(api):
    """
    The two variants meet on one append-only journal row: the single line drawn
    from the 5000-point lot records 3600 cents of gross, 2700 provisionally and
    2807 finally, so both measurements of the same consumption are auditable side
    by side. Fulfilment re-measures money only — the lot's balance is exactly
    where allocation left it.

    "The row records `points_allocated`, the positive count drawn from that lot, and `line_gross_ssp_cents`, being `points_allocated` multiplied by that lot's `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up."
    "No lot balance moves at fulfilment."
    "A lot that was `OUTSTANDING` and gives up a positive count strictly fewer than its `points_remaining` moves `OUTSTANDING → PARTIALLY_REDEEMED`, with `points_remaining` decremented by the amount drawn, one `ALLOCATION` row appended, and the lot's `version` incremented by 1."

    Design: Difficulty/dual_variant_calc/dual_variant_redemption_provisional_vs_final_release
    """
    world = _world_with_installed_rate(api)
    event = fixtures.allocated_redemption(
        api, world["gold_member"]["id"], world["period"]["id"], REDEEMED_POINTS
    )
    after_allocation = assert_ok(
        api.get_point_lot(world["gold_lot"]["id"], ACCOUNTANT_HEADERS)
    )
    assert_ok(api.fulfill_redemption(event["id"], None, ACCOUNTANT_HEADERS))

    rows = assert_page(
        api.list_redemption_allocations(event["id"], ACCOUNTANT_HEADERS),
        total_count=1,
    )
    assert_immutable_common_fields(rows[0])
    assert_fields(
        rows[0],
        entry_type=ENTRY_TYPE_ALLOCATION,
        allocation_seq=1,
        point_lot_id=world["gold_lot"]["id"],
        points_allocated=REDEEMED_POINTS,
        line_gross_ssp_cents=LINE_GROSS_CENTS,
        provisional_release_cents=PROVISIONAL_RELEASE_CENTS,
        final_release_cents=FINAL_RELEASE_CENTS,
    )

    after_fulfilment = assert_ok(
        api.get_point_lot(world["gold_lot"]["id"], ACCOUNTANT_HEADERS)
    )
    assert_fields(
        after_fulfilment,
        points_remaining=after_allocation["points_remaining"],
        lifecycle_state=LOT_PARTIALLY_REDEEMED,
    )
    assert_fields(after_fulfilment, points_remaining=GOLD_LOT_REMAINING_POINTS)
    assert_lot_split(after_fulfilment)


def test_gross_basis_bills_the_receivable_without_offsetting_the_payable(api):
    """
    The gross variant of the settlement calculation. The agreement has netting
    disabled, so the statement measures the 3300-cent redemption payable and
    reports it, but the billable candidate is the 72000-cent issuance receivable
    plus a zero carry-forward and nothing else: 72000 is due. The statement is
    born a draft and books nothing onto the agreement until it is issued.

    "What happens next depends on `settlement_basis`, which is computed at creation from the agreement: `NET` when `net_settlement_enabled` is true, `GROSS` when it is false."
    "Under `GROSS`, the billable candidate is `issuance_receivable_cents` plus `carried_forward_cents`."
    "The redemption payable is still measured and reported on the statement, but it is **not** offset here — it settles on the partner's own invoice outside this ledger."
    "Otherwise `net_due_cents` takes the candidate and `deferred_below_minimum_cents` is 0."
    "A new statement is born in `state` `DRAFT`, with `dispute_count` at 0 and `issued_at`, `paid_at`, `dispute_reason`, `resolution_note` and `write_off_reason` all null."

    Design: Difficulty/dual_variant_calc/dual_variant_partner_settlement_gross_vs_net
    """
    pair = _partner_pair_world(api)
    statement = fixtures.draft_statement(
        api, pair["gross_agreement"]["id"], pair["period"]["id"]
    )
    assert_fields(
        statement,
        settlement_basis=BASIS_GROSS,
        state=STATEMENT_DRAFT,
        partner_issued_points=PARTNER_ISSUED_POINTS,
        partner_redeemed_points=PARTNER_REDEEMED_POINTS,
        issuance_receivable_cents=ISSUANCE_RECEIVABLE_CENTS,
        redemption_payable_cents=REDEMPTION_PAYABLE_CENTS,
        carried_forward_cents=0,
        net_due_cents=GROSS_NET_DUE_CENTS,
        deferred_below_minimum_cents=0,
    )
    assert_statement_net(statement)

    agreement = assert_ok(
        api.get_agreement(pair["gross_agreement"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert_fields(
        agreement,
        outstanding_settlement_cents=0,
        deferred_below_minimum_cents=0,
        min_invoice_cents=DEFAULT_MIN_INVOICE_CENTS,
        net_settlement_enabled=False,
    )


def test_net_basis_offsets_the_measured_payable_inside_the_statement(api):
    """
    The net variant over byte-identical activity. Netting is enabled on this
    agreement, so the same 72000-cent receivable is reduced by the same
    3300-cent payable before the minimum-invoice threshold is applied, and 68700
    is due rather than 72000. The candidate still clears the 5000-cent minimum,
    so nothing is deferred.

    "Under `NET`, the billable candidate is `issuance_receivable_cents` less `redemption_payable_cents` plus `carried_forward_cents`."
    "The payable is offset inside the statement, and the candidate may come out negative, in which case it necessarily falls below the minimum invoice and is deferred rather than billed."
    "The minimum-invoice threshold is applied to the candidate **after** the carry-forward has been added, never to the current period's legs alone — applying it earlier would strand the carry-forward forever."

    Design: Difficulty/dual_variant_calc/dual_variant_partner_settlement_gross_vs_net
    """
    pair = _partner_pair_world(api)
    statement = fixtures.draft_statement(
        api, pair["net_agreement"]["id"], pair["period"]["id"]
    )
    assert_fields(
        statement,
        settlement_basis=BASIS_NET,
        state=STATEMENT_DRAFT,
        partner_issued_points=PARTNER_ISSUED_POINTS,
        partner_redeemed_points=PARTNER_REDEEMED_POINTS,
        issuance_receivable_cents=ISSUANCE_RECEIVABLE_CENTS,
        redemption_payable_cents=REDEMPTION_PAYABLE_CENTS,
        carried_forward_cents=0,
        net_due_cents=NET_NET_DUE_CENTS,
        deferred_below_minimum_cents=0,
    )
    assert_statement_net(statement)

    agreement = assert_ok(
        api.get_agreement(pair["net_agreement"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert_fields(
        agreement, outstanding_settlement_cents=0, net_settlement_enabled=True
    )


def test_identical_legs_diverge_only_by_the_settlement_basis(api):
    """
    The two variants placed side by side. Both agreements carry the same rate
    card, the same window and the same activity — 80000 partner-issued points and
    one allocated 3000-point partner redemption — so both statements measure
    identical legs and identical due dates, and the whole difference between them
    is the 3300-cent payable the net basis offsets and the gross basis does not.

    "`partner_issued_points` is the sum of `points_issued` over the matching lots, with every `lifecycle_state` included — issuance is billable the moment it happens, and a later redemption, expiry or escheatment does not un-bill it."
    "`partner_redeemed_points` is the sum of `points_requested` over the matching redemption events whose `state` is `ALLOCATED` or `FULFILLED`; events still merely `REQUESTED`, and events that were `REVERSED`, contribute nothing."
    "From those two counts, `issuance_receivable_cents` is `partner_issued_points` multiplied by the agreement's `issuance_rate_millicents_per_point`, divided by 1000, rounded half up, and `redemption_payable_cents` is `partner_redeemed_points` multiplied by the agreement's `redemption_rate_millicents_per_point`, divided by 1000, rounded half up."
    "`due_date` is the period's `end_at` advanced by the agreement's `settlement_lag_days` whole days."

    Design: Difficulty/dual_variant_calc/dual_variant_partner_settlement_gross_vs_net
    """
    pair = _partner_pair_world(api)
    gross_statement = fixtures.draft_statement(
        api, pair["gross_agreement"]["id"], pair["period"]["id"]
    )
    net_statement = fixtures.draft_statement(
        api, pair["net_agreement"]["id"], pair["period"]["id"]
    )

    for statement in (gross_statement, net_statement):
        assert_fields(
            statement,
            partner_issued_points=PARTNER_ISSUED_POINTS,
            partner_redeemed_points=PARTNER_REDEEMED_POINTS,
            issuance_receivable_cents=ISSUANCE_RECEIVABLE_CENTS,
            redemption_payable_cents=REDEMPTION_PAYABLE_CENTS,
            carried_forward_cents=0,
            deferred_below_minimum_cents=0,
            due_date=STATEMENT_DUE_DATE,
        )

    assert_fields(gross_statement, net_due_cents=GROSS_NET_DUE_CENTS)
    assert_fields(net_statement, net_due_cents=NET_NET_DUE_CENTS)
    assert (
        gross_statement["net_due_cents"] - net_statement["net_due_cents"]
        == BASIS_DELTA_CENTS
    ), "The two bases must differ by exactly the measured redemption payable"
    assert gross_statement["settlement_basis"] != net_statement["settlement_basis"], (
        "The two statements must be measured on different bases"
    )
