"""Deemed generation, the mintable floor, claim sizing and the attribute split.

Four filters sit under the settlement arithmetic and each one is a separate
question.  An hour earns a make-whole only when a flag and an `ACCEPTED` claim
coincide; a certificate is earned only by metered electrons, floored rather than
rounded; a claim is sized from stored timestamps rather than insertion order;
and the attribute split's basis counts confirmed slices only.  Every figure
below is fixed to four decimals or two, because the fourth decimal is exactly
where a truncation and a half-up round part company.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import assertions as asserts  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    DEAL_COMMITTEE_ID,
    ORIGINATOR,
    SETTLEMENT_ANALYST,
)

# ---------------------------------------------------------------------------
# A wind deal whose hourly expectation lands on a fifth decimal of 6.
# ---------------------------------------------------------------------------

SEPTEMBER = ("2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")

#: 100 MW of wind, already generating, so the deal executes into an empty
#: condition template.
WIND_PROJECT = {
    "name": "Goat Mountain Wind",
    "technology": "WIND",
    "cod_target_date": "2026-06-01T00:00:00Z",
    "p50_annual_mwh": 367920.00,
}

#: 33.333 * 0.42 = 13.99986, whose fourth decimal is decided by a 6.
AWKWARD_MW = 33.333
WIND_DEAL = {
    "product_type": "VIRTUAL_CFD",
    "contracted_mw": AWKWARD_MW,
    "term_years": 12,
    "base_fixed_price_usd_per_mwh": 22.00,
    "basis_responsibility": "BUYER",
}

#: AS_GENERATED at `LOW` adds nothing and a buyer-borne basis adds nothing, so
#: the contract price is the unescalated base itself.
CONTRACT_PRICE = 22.00

#: 33.333 * 0.42 * 8,760 = 122,638.7736.
WIND_ANNUAL_MWH = 122638.77
WIND_EXPOSURE_USD = 2698052.94

EXPECTED_HOURLY_MWH = 13.9999
METERED_MWH = 10.0000

NODE_PRICE = 30.00

#: Published at the hub for the same hour, and irrelevant at a `NODE`.
HUB_PRICE = 41.00

NET_SETTLEMENT_USD = 80.00
MINTABLE_MWH = 10


def test_01_the_hourly_expectation_is_rounded_half_up_at_the_fourth_decimal(api):
    """13.99986 becomes 13.9999 rather than 13.9998 or 14.00, and the hub price
    published for the very same hour never enters the money.

    "For each hour, the contract-shape expectation `expected_mwh` is the deal's
    `contracted_mw` multiplied by the parent project's technology capacity factor —
    0.28 for `SOLAR`, 0.42 for `WIND`, 0.35 for `STORAGE_HYBRID` — rounded half up
    to four decimal places."

    "The hourly index is the `hub_price_usd_per_mwh` when the deal's settlement
    point has `settlement_point_type` `HUB`, and the `node_price_usd_per_mwh` when
    it has `settlement_point_type` `NODE`."

    "When the deal's settlement point has `settlement_point_type` `NODE`,
    `basis_adjustment_usd` is 0.00, because the contract already settles at the node
    and there is no differential to allocate."

    Design: Corner/calculations/deemed_expected_mwh_rounds_half_up_at_the_fourth_decimal
    """
    chain = fx.effective_chain_with_period(
        api, period_start=SEPTEMBER[0], period_end=SEPTEMBER[1],
        project_overrides=dict(WIND_PROJECT), deal_overrides=dict(WIND_DEAL))
    deal = chain["deal"]
    period_id = chain["period"]["id"]

    assert deal["status"] == "EFFECTIVE", deal
    assert deal["cp_total_count"] == 0, deal
    asserts.assert_score(deal["cp_completion_pct"], 100.00, "cp_completion_pct")
    asserts.assert_money(deal["contract_price_usd_per_mwh"], CONTRACT_PRICE,
                         "contract_price_usd_per_mwh")
    asserts.assert_mwh(deal["expected_annual_mwh"], WIND_ANNUAL_MWH,
                       "expected_annual_mwh", places=2)
    asserts.assert_money(deal["exposure_usd"], WIND_EXPOSURE_USD,
                         "exposure_usd")

    interval = fx.post_interval(api, period_id, "2026-09-15T13:00:00Z",
                               METERED_MWH,
                               node_price_usd_per_mwh=NODE_PRICE,
                               hub_price_usd_per_mwh=HUB_PRICE)
    assert interval["curtailment_flag"] == "NONE", interval
    asserts.assert_all_null(interval, ["expected_mwh", "delivered_mwh"])
    asserts.assert_mwh(interval["deemed_mwh"], 0.0000, "deemed_mwh")

    period = fx.calculate_period(api, period_id)
    assert period["status"] == "CALCULATED", period

    priced = fx.intervals_of(api, period_id)
    assert len(priced) == 1, priced
    asserts.assert_mwh(priced[0]["expected_mwh"], EXPECTED_HOURLY_MWH,
                       "expected_mwh")
    asserts.assert_mwh(priced[0]["deemed_mwh"], 0.0000, "deemed_mwh")
    asserts.assert_mwh(priced[0]["delivered_mwh"], METERED_MWH,
                       "delivered_mwh")

    asserts.assert_mwh(period["total_metered_mwh"], METERED_MWH,
                       "total_metered_mwh")
    asserts.assert_mwh(period["total_deemed_mwh"], 0.0000, "total_deemed_mwh")
    asserts.assert_mwh(period["total_delivered_mwh"], METERED_MWH,
                       "total_delivered_mwh")
    assert period["mintable_attributes_mwh"] == MINTABLE_MWH, period

    # The node is the index and the hub price is scenery.
    asserts.assert_mwh(period["weighted_avg_index_usd_per_mwh"], NODE_PRICE,
                       "weighted_avg_index_usd_per_mwh")
    asserts.assert_money(period["energy_settlement_usd"], NET_SETTLEMENT_USD,
                         "energy_settlement_usd")
    asserts.assert_money(period["basis_adjustment_usd"], 0.00,
                         "basis_adjustment_usd")
    asserts.assert_money(period["net_settlement_usd"], NET_SETTLEMENT_USD,
                         "net_settlement_usd")
    asserts.assert_money(period["seller_pays_usd"], NET_SETTLEMENT_USD,
                         "seller_pays_usd")
    asserts.assert_money(period["buyer_pays_usd"], 0.00, "buyer_pays_usd")
    asserts.assert_instant_equals(period["calculated_at"], fx.INITIAL_CLOCK,
                                  "calculated_at")


# ---------------------------------------------------------------------------
# Four hours, each failing a different limb of the deemed input-set filter.
# ---------------------------------------------------------------------------

#: The default 100 MW solar project, already `OPERATIONAL`.
OPERATING_SOLAR = {"cod_target_date": "2026-06-01T00:00:00Z"}

SOLAR_DEAL = {
    "product_type": "VIRTUAL_CFD",
    "contracted_mw": 25.000,
    "term_years": 12,
    "base_fixed_price_usd_per_mwh": 22.00,
    "basis_responsibility": "BUYER",
}

#: 25.000 * 0.28, exact at four decimals and identical for every hour.
SOLAR_HOURLY_MWH = 7.0000

#: Curtailed, and inside the accepted buyer-borne window.
COVERED_HOUR = "2026-09-01T14:00:00Z"
COVERED_METERED_MWH = 3.0000
COVERED_DEEMED_MWH = 4.0000

#: Inside the same accepted window, but never curtailed.
UNFLAGGED_HOUR = "2026-09-01T15:00:00Z"
UNFLAGGED_METERED_MWH = 6.0000

#: Curtailed, but outside every accepted window.
UNCOVERED_HOUR = "2026-09-02T14:00:00Z"
UNCOVERED_METERED_MWH = 3.0000

#: Curtailed, and inside a window that has been filed but not reviewed.
UNREVIEWED_HOUR = "2026-09-03T14:00:00Z"
UNREVIEWED_METERED_MWH = 2.0000

#: Closed on both ends, and disjoint from each other by more than a day.
ACCEPTED_WINDOW = ("2026-09-01T00:00:00Z", "2026-09-01T23:00:00Z")
CLAIMED_WINDOW = ("2026-09-03T00:00:00Z", "2026-09-03T23:00:00Z")

FILTERED_METERED_MWH = 14.0000
FILTERED_DEEMED_MWH = 4.0000
FILTERED_DELIVERED_MWH = 18.0000

#: 18.0000 * (30.00 - 22.00).
FILTERED_NET_USD = 144.00


def test_02_a_flag_and_an_accepted_claim_must_coincide_to_earn_deemed_volume(api):
    """Only the hour that satisfies both limbs is grossed up: coverage without a
    flag, a flag without coverage and a flag over a merely `CLAIMED` window all
    earn 0.0000.

    "An hour earns deemed volume only when two things hold together: its
    `curtailment_flag` is something other than `NONE`, and there exists a risk claim
    on this deal whose `status` is `ACCEPTED`, whose `event_type` is `CURTAILMENT`,
    and whose window contains `hour_start` inclusive of both endpoints."

    "`deemed_mwh` is then the shortfall — `expected_mwh` less `metered_mwh`, floored
    at zero so a curtailed hour that out-produced its expectation yields 0.0000
    rather than a negative — multiplied by that share, rounded half up to four
    decimal places."

    "An hour that fails either condition has `deemed_mwh` of 0.0000."

    "`delivered_mwh` is `metered_mwh` plus `deemed_mwh`, rounded half up to four
    decimal places, and it is the quantity the settlement legs multiply."

    Design: Corner/calculations/deemed_generation_input_set_excludes_uncovered_hours_and_unaccepted_claims
    """
    chain = fx.effective_chain_with_period(
        api, period_start=SEPTEMBER[0], period_end=SEPTEMBER[1],
        project_overrides=dict(OPERATING_SOLAR), deal_overrides=dict(SOLAR_DEAL))
    deal_id = chain["deal"]["id"]
    period_id = chain["period"]["id"]

    fx.post_interval(api, period_id, COVERED_HOUR, COVERED_METERED_MWH,
                    curtailment_flag="ECONOMIC")
    fx.post_interval(api, period_id, UNFLAGGED_HOUR, UNFLAGGED_METERED_MWH,
                    curtailment_flag="NONE")
    fx.post_interval(api, period_id, UNCOVERED_HOUR, UNCOVERED_METERED_MWH,
                    curtailment_flag="ECONOMIC")
    fx.post_interval(api, period_id, UNREVIEWED_HOUR, UNREVIEWED_METERED_MWH,
                    curtailment_flag="GRID_EMERGENCY")

    # 23:00 on 1 September against 00:00 on 3 September: no closed-interval
    # collision, so both claims are accepted onto the deal.
    covering = fx.file_risk_event(api, deal_id, "CURTAILMENT", *ACCEPTED_WINDOW)
    unreviewed = fx.file_risk_event(api, deal_id, "CURTAILMENT",
                                    *CLAIMED_WINDOW)
    covering = fx.review_risk_event(api, covering["id"], "ACCEPT",
                                    "BUYER_BEARS")
    assert covering["status"] == "ACCEPTED", covering
    assert covering["duration_days"] == 1, covering
    assert covering["excused_hours"] == 2, covering
    assert unreviewed["status"] == "CLAIMED", unreviewed
    asserts.assert_all_null(unreviewed, ["duration_days", "allocation_outcome",
                                         "reviewed_at",
                                         "reviewed_by_user_id"])
    assert unreviewed["excused_hours"] == 0, unreviewed

    period = fx.calculate_period(api, period_id)
    hours = {row["hour_start"]: row for row in fx.intervals_of(api, period_id)}
    assert len(hours) == 4, hours
    by_hour = {}
    for stamp, row in hours.items():
        asserts.assert_mwh(row["expected_mwh"], SOLAR_HOURLY_MWH,
                           f"expected_mwh at {stamp}")
        by_hour[stamp[:19]] = row

    covered = by_hour[COVERED_HOUR[:19]]
    asserts.assert_mwh(covered["deemed_mwh"], COVERED_DEEMED_MWH, "deemed_mwh")
    asserts.assert_mwh(covered["delivered_mwh"], SOLAR_HOURLY_MWH,
                       "delivered_mwh")

    for label, hour, metered in (
            ("coverage without a flag", UNFLAGGED_HOUR, UNFLAGGED_METERED_MWH),
            ("a flag without coverage", UNCOVERED_HOUR, UNCOVERED_METERED_MWH),
            ("a flag over an unreviewed claim", UNREVIEWED_HOUR,
             UNREVIEWED_METERED_MWH)):
        row = by_hour[hour[:19]]
        asserts.assert_mwh(row["deemed_mwh"], 0.0000, f"deemed_mwh: {label}")
        asserts.assert_mwh(row["delivered_mwh"], metered,
                           f"delivered_mwh: {label}")

    asserts.assert_mwh(period["total_metered_mwh"], FILTERED_METERED_MWH,
                       "total_metered_mwh")
    asserts.assert_mwh(period["total_deemed_mwh"], FILTERED_DEEMED_MWH,
                       "total_deemed_mwh")
    asserts.assert_mwh(period["total_delivered_mwh"], FILTERED_DELIVERED_MWH,
                       "total_delivered_mwh")

    # The single deemed block reaches the money even though it will never reach
    # the registry.
    asserts.assert_money(period["net_settlement_usd"], FILTERED_NET_USD,
                         "net_settlement_usd")
    asserts.assert_money(period["seller_pays_usd"], FILTERED_NET_USD,
                         "seller_pays_usd")


# ---------------------------------------------------------------------------
# Certificates follow metered electrons; money follows delivered volume.
# ---------------------------------------------------------------------------

#: Curtailed and covered, so it is grossed up from 3.0000 to 7.0000.
MINT_COVERED_HOUR = "2026-09-10T13:00:00Z"
MINT_COVERED_WINDOW = ("2026-09-10T00:00:00Z", "2026-09-10T23:00:00Z")

#: Uncurtailed, and the source of the half megawatt-hour that the floor eats.
MINT_PLAIN_HOUR = "2026-09-11T13:00:00Z"
MINT_PLAIN_METERED_MWH = 5.5000

MINT_METERED_MWH = 8.5000
MINT_DEEMED_MWH = 4.0000
MINT_DELIVERED_MWH = 12.5000

#: floor(8.5000): not 9 (a half-up round), not 12 (the floor of delivered
#: volume) and not 13 (a round of delivered volume).
MINTABLE_FROM_METERED = 8

#: 12.5000 * (30.00 - 22.00).
MINT_NET_USD = 100.00

VINTAGE_MONTH = "2026-09"


def test_03_only_metered_volume_earns_certificates_and_the_floor_truncates(api):
    """8.5000 metered plus 4.0000 deemed settles on 12.5000 delivered and mints
    exactly 8, so the gap between the money and the registry is permanent.

    "Finally, `mintable_attributes_mwh` is `total_metered_mwh` truncated to a whole
    number — a floor, never a half-up round — and `total_deemed_mwh` is deliberately
    excluded from that input, because deemed generation is a financial make-whole and
    minting a certificate against it would leave the buyer's claim unsubstantiated."

    "It arrives with `status` `MINTED`, `claim_substantiation_status`
    `UNSUBSTANTIATED`, `allocation_breakdown` the empty array, and
    `registry_serial_range`, `transferred_to_offtaker_id`, `claim_year`,
    `transferred_at` and `retired_at` all null."

    "The batch's `vintage_month` is computed as the calendar year and month of the
    source period's `period_start`, written in four-digit-year-hyphen-two-digit-month
    form."

    Design: Corner/calculations/mintable_attributes_floors_metered_volume_and_ignores_deemed
    """
    chain = fx.effective_chain_with_period(
        api, period_start=SEPTEMBER[0], period_end=SEPTEMBER[1],
        project_overrides=dict(OPERATING_SOLAR), deal_overrides=dict(SOLAR_DEAL))
    deal_id = chain["deal"]["id"]
    period_id = chain["period"]["id"]

    covered = fx.post_interval(api, period_id, MINT_COVERED_HOUR,
                              COVERED_METERED_MWH,
                              curtailment_flag="ECONOMIC")
    plain = fx.post_interval(api, period_id, MINT_PLAIN_HOUR,
                            MINT_PLAIN_METERED_MWH)
    assert plain["curtailment_flag"] == "NONE", plain
    fx.accepted_curtailment_claim(api, deal_id, *MINT_COVERED_WINDOW)

    period = fx.calculate_period(api, period_id)
    asserts.assert_mwh(period["total_metered_mwh"], MINT_METERED_MWH,
                       "total_metered_mwh")
    asserts.assert_mwh(period["total_deemed_mwh"], MINT_DEEMED_MWH,
                       "total_deemed_mwh")
    asserts.assert_mwh(period["total_delivered_mwh"], MINT_DELIVERED_MWH,
                       "total_delivered_mwh")
    assert period["mintable_attributes_mwh"] == MINTABLE_FROM_METERED, period
    asserts.assert_money(period["net_settlement_usd"], MINT_NET_USD,
                         "net_settlement_usd")

    hours = {row["hour_start"][:19]: row
             for row in fx.intervals_of(api, period_id, SETTLEMENT_ANALYST)}
    asserts.assert_mwh(hours[MINT_COVERED_HOUR[:19]]["deemed_mwh"],
                       MINT_DEEMED_MWH, "deemed_mwh")
    asserts.assert_mwh(hours[MINT_PLAIN_HOUR[:19]]["deemed_mwh"], 0.0000,
                       "deemed_mwh")
    assert covered["id"] in asserts.ids_of(list(hours.values())), hours

    batch = fx.mint_batch(api, period_id, MINTABLE_FROM_METERED)
    assert batch["quantity_mwh"] == MINTABLE_FROM_METERED, batch
    assert batch["status"] == "MINTED", batch
    assert batch["claim_substantiation_status"] == "UNSUBSTANTIATED", batch
    assert batch["allocation_breakdown"] == [], batch
    assert batch["vintage_month"] == VINTAGE_MONTH, batch
    assert batch["registry"] == "WREGIS", batch
    asserts.assert_all_null(batch, ["registry_serial_range",
                                    "transferred_to_offtaker_id", "claim_year",
                                    "transferred_at", "retired_at"])

    # The 4.0000 MWh that reached the money never reaches the registry.
    deal = fx.read_deal(api, deal_id)
    assert deal["attributes_minted_mwh"] == MINTABLE_FROM_METERED, deal
    assert deal["attributes_transferred_mwh"] == 0, deal
    asserts.assert_mwh(period["total_delivered_mwh"], MINT_DELIVERED_MWH,
                       "total_delivered_mwh")


# ---------------------------------------------------------------------------
# A claim is sized from the stored timestamps, not from insertion order.
# ---------------------------------------------------------------------------

#: Posted first and excused last: one hour past `window_end`.
LATE_HOUR = "2026-09-06T00:00:00Z"

#: Posted second, and sitting exactly on `window_end`.
EDGE_HOUR = "2026-09-05T23:00:00Z"

#: Posted last, and sitting exactly on `window_start`.
EARLY_HOUR = "2026-09-01T00:00:00Z"

#: Closed on both ends and spanning 4 days 23 hours = 428,400 seconds.
FORCE_MAJEURE_WINDOW = (EARLY_HOUR, EDGE_HOUR)

#: floor(428400 / 86400) + 1 = floor(4.9583) + 1: not 4 and not 6.
DURATION_DAYS = 5

#: The hour at `window_start` and the hour at `window_end`; the hour one hour
#: past `window_end` is outside.
EXCUSED_HOURS = 2

PERIOD_NULL_AT_REST = [
    "weighted_avg_index_usd_per_mwh",
    "energy_settlement_usd",
    "basis_adjustment_usd",
    "net_settlement_usd",
    "seller_pays_usd",
    "buyer_pays_usd",
    "mintable_attributes_mwh",
    "calculated_at",
    "invoiced_at",
    "dispute_reason",
]


def test_04_sizing_a_claim_reads_stored_hours_and_the_closed_window(api):
    """Three hours posted newest first are sized as if they had arrived in order,
    the hour on `window_end` is excused and the hour after it is not, and no money
    moves.

    "Hop one stores the `allocation_outcome` and, where supplied, the
    `price_adjustment_usd_per_mwh`, stamps `reviewed_by_user_id` and `reviewed_at`,
    and sizes the claim: `duration_days` is the whole days from `window_start` to
    `window_end` counted inclusively of both endpoints — that is, the truncated count
    of 86400-second periods between them, plus one — and `excused_hours` is the
    number of metered hours belonging to any settlement period of this deal whose
    `hour_start` falls at or after `window_start` and at or before `window_end`, the
    window being closed on both ends so an hour starting exactly at `window_end` is
    excused."

    "Hop two fires only on the `CHANGE_IN_LAW` path: the deal's
    `contract_price_usd_per_mwh` becomes its prior value plus
    `price_adjustment_usd_per_mwh`, rounded half up to two decimal places, after which
    `exposure_usd` and `credit_support_required_usd` are re-sized by the three-step
    requirement calculation."

    "The hours of a period are listable in `hour_start` order, filterable by
    `curtailment_flag`."

    Design: Corner/calculations/risk_event_duration_and_excused_hours_are_order_independent
    """
    chain = fx.effective_chain_with_period(
        api, period_start=SEPTEMBER[0], period_end=SEPTEMBER[1],
        project_overrides=dict(OPERATING_SOLAR), deal_overrides=dict(SOLAR_DEAL))
    deal_id = chain["deal"]["id"]
    period_id = chain["period"]["id"]

    late = fx.post_interval(api, period_id, LATE_HOUR, 4.0000)
    edge = fx.post_interval(api, period_id, EDGE_HOUR, 2.0000)
    early = fx.post_interval(api, period_id, EARLY_HOUR, 1.0000)

    # Listed in `hour_start` order, which is the reverse of the posting order.
    listed = fx.intervals_of(api, period_id, SETTLEMENT_ANALYST)
    assert asserts.ids_of(listed) == [early["id"], edge["id"], late["id"]], \
        listed

    claim = fx.file_risk_event(api, deal_id, "FORCE_MAJEURE",
                               *FORCE_MAJEURE_WINDOW)
    assert claim["status"] == "CLAIMED", claim
    assert claim["duration_days"] is None, claim
    assert claim["excused_hours"] == 0, claim

    sized = fx.review_risk_event(api, claim["id"], "ACCEPT", "SELLER_BEARS")
    assert sized["status"] == "ACCEPTED", sized
    assert sized["allocation_outcome"] == "SELLER_BEARS", sized
    assert sized["reviewed_by_user_id"] == DEAL_COMMITTEE_ID, sized
    asserts.assert_instant_equals(sized["reviewed_at"], fx.INITIAL_CLOCK,
                                  "reviewed_at")
    assert sized["duration_days"] == DURATION_DAYS, sized
    assert sized["excused_hours"] == EXCUSED_HOURS, sized

    # The repricing hop belongs to `CHANGE_IN_LAW` alone.
    assert sized["price_adjustment_usd_per_mwh"] is None, sized
    deal = fx.read_deal(api, deal_id)
    asserts.assert_money(deal["contract_price_usd_per_mwh"], CONTRACT_PRICE,
                         "contract_price_usd_per_mwh")
    assert deal["credit_status"] == "APPROVED", deal
    assert deal["support_cure_deadline"] is None, deal

    # Sizing a claim never settles a period.
    period = fx.read_period(api, period_id)
    assert period["status"] == "OPEN", period
    assert period["interval_count"] == 3, period
    asserts.assert_all_null(period, PERIOD_NULL_AT_REST)
    asserts.assert_mwh(period["total_metered_mwh"], 0.0000,
                       "total_metered_mwh")
    asserts.assert_mwh(period["total_deemed_mwh"], 0.0000, "total_deemed_mwh")
    asserts.assert_mwh(period["total_delivered_mwh"], 0.0000,
                       "total_delivered_mwh")


# ---------------------------------------------------------------------------
# The largest-remainder basis counts confirmed slices only.
# ---------------------------------------------------------------------------

AGGREGATED_DEAL = {
    "product_type": "AGGREGATED",
    "contracted_mw": 25.000,
    "term_years": 12,
    "base_fixed_price_usd_per_mwh": 22.00,
    "basis_responsibility": "BUYER",
}

CONFIRMED_SLICE_MW = 25.000
CONFIRMED_SHARE_PCT = 100.0000

#: Proposed and never agreed to: 100 * 10.000 / 25.000.
PROPOSED_SLICE_MW = 10.000
PROPOSED_SHARE_PCT = 40.0000

AGGREGATED_HOUR = "2026-09-12T13:00:00Z"
AGGREGATED_METERED_MWH = 8.5000
BATCH_MWH = 8
SERIAL_RANGE = "WREGIS-2026-09-000001-000008"


def test_05_the_attribute_split_ignores_a_slice_nobody_confirmed(api):
    """The whole batch goes to the one buyer that confirmed, and the 6/2 split an
    unfiltered basis of 35.000 would produce — which also sums to 8 — never
    appears.

    "The basis is the sum of `allocated_mw` over the deal's slices whose `status` is
    `CONFIRMED` only; `PROPOSED` and `WITHDRAWN` slices are excluded from the basis
    entirely."

    "`allocation_breakdown` is emitted in that same sort order, as objects each
    carrying an `offtaker_id` and a `quantity_mwh`, and the parts sum to the batch's
    `quantity_mwh` exactly."

    "A successful transfer moves the batch `MINTED → TRANSFERRED`, stores the
    recipient and the serial range, stamps `transferred_at` with the logical clock,
    populates `allocation_breakdown`, increases the deal's `attributes_transferred_mwh`
    by `quantity_mwh`, and increments both the batch's `version` and the deal's
    `version` by one."

    Design: Corner/calculations/attribute_allocation_basis_counts_confirmed_allocations_only
    """
    chain = fx.negotiated_chain(
        api, project_status="OPERATIONAL",
        project_overrides=dict(OPERATING_SOLAR),
        deal_overrides=dict(AGGREGATED_DEAL))
    deal_id = chain["deal"]["id"]
    confirmed_buyer = chain["buyer"]["id"]

    other_buyer = fx.create_qualified_offtaker(
        api, legal_name="Cascadia Foods Inc",
        registry_account_id="WREGIS-ACC-00902")
    unconfirmed = fx.propose_allocation(api, deal_id, other_buyer["id"],
                                        PROPOSED_SLICE_MW)

    rows = fx.list_all(api.list_allocations(deal_id, ORIGINATOR))[0]
    assert len(rows) == 2, rows
    confirmed_row = asserts.row_by(rows, "offtaker_id", confirmed_buyer)
    assert confirmed_row["status"] == "CONFIRMED", confirmed_row
    asserts.assert_mw(confirmed_row["allocated_mw"], CONFIRMED_SLICE_MW,
                      "allocated_mw")
    asserts.assert_share_pct(confirmed_row["allocation_share_pct"],
                             CONFIRMED_SHARE_PCT)
    assert unconfirmed["status"] == "PROPOSED", unconfirmed
    asserts.assert_share_pct(unconfirmed["allocation_share_pct"],
                             PROPOSED_SHARE_PCT)

    # The proposed slice never entered the confirmed pool, so signing is legal.
    signed = fx.execute_deal(api, deal_id)
    assert signed["status"] == "EFFECTIVE", signed
    asserts.assert_mw(signed["confirmed_allocated_mw"], CONFIRMED_SLICE_MW,
                      "confirmed_allocated_mw")

    period = fx.open_period(api, deal_id, *SEPTEMBER)
    fx.post_interval(api, period["id"], AGGREGATED_HOUR,
                    AGGREGATED_METERED_MWH)
    calculated = fx.calculate_period(api, period["id"])
    assert calculated["mintable_attributes_mwh"] == BATCH_MWH, calculated

    batch = fx.mint_batch(api, period["id"], BATCH_MWH)
    conveyed = fx.transfer_batch(api, batch["id"], confirmed_buyer,
                                 registry_serial_range=SERIAL_RANGE)
    assert conveyed["status"] == "TRANSFERRED", conveyed
    assert conveyed["transferred_to_offtaker_id"] == confirmed_buyer, conveyed
    assert conveyed["registry_serial_range"] == SERIAL_RANGE, conveyed
    asserts.assert_instant_equals(conveyed["transferred_at"], fx.INITIAL_CLOCK,
                                  "transferred_at")

    breakdown = conveyed["allocation_breakdown"]
    assert len(breakdown) == 1, breakdown
    assert breakdown[0]["offtaker_id"] == confirmed_buyer, breakdown
    assert breakdown[0]["quantity_mwh"] == BATCH_MWH, breakdown
    assert sum(part["quantity_mwh"] for part in breakdown) == BATCH_MWH, \
        breakdown

    # The 6/2 pair an unfiltered basis of 35.000 would produce is absent.
    assert other_buyer["id"] not in [part["offtaker_id"] for part in breakdown], \
        breakdown

    deal = fx.read_deal(api, deal_id)
    assert deal["attributes_minted_mwh"] == BATCH_MWH, deal
    assert deal["attributes_transferred_mwh"] == BATCH_MWH, deal
    assert deal["attributes_retired_mwh"] == 0, deal
    assert fx.read_offtaker(api, other_buyer["id"])["claimed_attributes_mwh"] \
        == 0, "a buyer that never confirmed claims nothing"
