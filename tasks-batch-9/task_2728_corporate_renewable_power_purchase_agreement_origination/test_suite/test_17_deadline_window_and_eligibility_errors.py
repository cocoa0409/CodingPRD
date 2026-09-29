"""Deadlines, windows, vested rights and membership tables.

Six refusal paths that each depend on something other than the payload in front
of them: a price that would go non-positive, a logical clock that has passed a
deadline, a termination right whose predicate is false, a window that intersects
a sibling, a recipient with no confirmed slice, and an issuer that has no row in
the haircut table.  Every one of them is checked against the state the request
would have produced, and each is paired with the neighbouring request that
succeeds.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (  # noqa: E402
    get_success_data,
    validate_error,
)

from test_helpers import assertions as asserts  # noqa: E402
from test_helpers import factories as f  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402
from test_helpers.api_errors import ApiErrorId  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    CREDIT_OFFICER,
    DEAL_COMMITTEE,
    ORIGINATOR,
    REGISTRY_AGENT,
    SETTLEMENT_ANALYST,
)

# ---------------------------------------------------------------------------
# A change-in-law adjustment may be negative, but not to death.
# ---------------------------------------------------------------------------

#: 8.00 escalated base plus 0.75 of shared basis adder.
LAW_CONTRACT_PRICE = 8.75

#: 25.000 MW of SOLAR: 25 * 0.28 * 8,760.
LAW_EXPECTED_MWH = 61320.00

#: 61,320.00 * 8.75.
LAW_EXPOSURE_USD = 536550.00

#: 8.75 - 8.75 is 0.00, which is not strictly positive.
FATAL_ADJUSTMENT = -8.75

#: 8.75 - 8.74 is 0.01, which is.
SURVIVABLE_ADJUSTMENT = -8.74
SURVIVED_PRICE = 0.01

#: 61,320.00 * 0.01.
SURVIVED_EXPOSURE_USD = 613.20

#: 2026-08-01 through 2026-08-02, counted inclusively of both endpoints.
LAW_WINDOW_DAYS = 2


def test_01_a_change_in_law_adjustment_may_not_zero_the_contract_price(api):
    """An omitted adjustment and one that lands the price on exactly 0.00 are both
    refused, while one cent of survival is accepted and re-sizes the exposure.

    "`ACCEPT` requires an `allocation_outcome` of `SELLER_BEARS`, `BUYER_BEARS` or
    `SHARED`, and when the `event_type` is `CHANGE_IN_LAW` it additionally requires
    a `price_adjustment_usd_per_mwh` between negative 10.00 and positive 10.00
    inclusive, at most two decimals; a change-in-law acceptance that omits the
    adjustment, or one whose adjustment would drive the deal's
    `contract_price_usd_per_mwh` to zero or below, is refused with
    `ERR_PRICE_ADJUSTMENT_INVALID` — the adjustment may be negative but the
    resulting price must remain strictly positive."

    "Hop one stores the `allocation_outcome` and, where supplied, the
    `price_adjustment_usd_per_mwh`, stamps `reviewed_by_user_id` and `reviewed_at`,
    and sizes the claim: `duration_days` is the whole days from `window_start` to
    `window_end` counted inclusively of both endpoints — that is, the truncated
    count of 86400-second periods between them, plus one — and `excused_hours` is
    the number of metered hours belonging to any settlement period of this deal
    whose `hour_start` falls at or after `window_start` and at or before
    `window_end`, the window being closed on both ends so an hour starting exactly
    at `window_end` is excused."

    "Hop two fires only on the `CHANGE_IN_LAW` path: the deal's
    `contract_price_usd_per_mwh` becomes its prior value plus
    `price_adjustment_usd_per_mwh`, rounded half up to two decimal places, after
    which `exposure_usd` and `credit_support_required_usd` are re-sized by the
    three-step requirement calculation."

    Design: Corner/errors/change_in_law_acceptance_needs_an_adjustment_that_keeps_the_price_positive
    """
    chain = fx.executed_chain_with_conditions(
        api, deal_overrides={"base_fixed_price_usd_per_mwh": 8.00})
    deal_id = chain["deal"]["id"]
    asserts.assert_money(chain["deal"]["contract_price_usd_per_mwh"],
                         LAW_CONTRACT_PRICE, "contract_price_usd_per_mwh")
    asserts.assert_money(chain["deal"]["exposure_usd"], LAW_EXPOSURE_USD,
                         "exposure_usd")
    assert chain["deal"]["credit_status"] == "APPROVED", chain["deal"]

    window_end = fx.iso_plus(fx.INITIAL_CLOCK, days=1)
    claim = fx.file_risk_event(api, deal_id, "CHANGE_IN_LAW", fx.INITIAL_CLOCK,
                              window_end)
    assert claim["status"] == "CLAIMED", claim
    asserts.assert_all_null(claim, ["allocation_outcome", "duration_days",
                                    "price_adjustment_usd_per_mwh",
                                    "reviewed_at", "reviewed_by_user_id"])

    before = fx.read_deal(api, deal_id)

    # An outcome alone is not enough on the change-in-law path.
    omitted = api.review_risk_event(
        claim["id"], f.risk_review_payload("ACCEPT", "SHARED"), DEAL_COMMITTEE)
    validate_error(omitted, ApiErrorId.ERR_PRICE_ADJUSTMENT_INVALID.value, 422)

    # In range, at most two decimals, and fatal: 8.75 - 8.75 is 0.00.
    fatal = api.review_risk_event(
        claim["id"],
        f.risk_review_payload("ACCEPT", "SHARED", FATAL_ADJUSTMENT),
        DEAL_COMMITTEE)
    validate_error(fatal, ApiErrorId.ERR_PRICE_ADJUSTMENT_INVALID.value, 422)

    rows, _ = fx.list_all(api.list_risk_events(deal_id, ORIGINATOR))
    untouched = asserts.row_by_id(rows, claim["id"])
    assert untouched["status"] == "CLAIMED", untouched
    assert untouched["version"] == claim["version"], untouched
    asserts.assert_all_null(untouched, ["allocation_outcome",
                                        "price_adjustment_usd_per_mwh"])
    held = fx.read_deal(api, deal_id)
    asserts.assert_money(held["contract_price_usd_per_mwh"], LAW_CONTRACT_PRICE,
                         "contract_price_usd_per_mwh")
    assert held["version"] == before["version"], held

    accepted = fx.review_risk_event(api, claim["id"], "ACCEPT", "SHARED",
                                    SURVIVABLE_ADJUSTMENT)
    assert accepted["status"] == "ACCEPTED", accepted
    asserts.assert_money(accepted["price_adjustment_usd_per_mwh"],
                         SURVIVABLE_ADJUSTMENT, "price_adjustment_usd_per_mwh")
    assert accepted["duration_days"] == LAW_WINDOW_DAYS, accepted
    assert accepted["excused_hours"] == 0, accepted
    asserts.assert_instant_equals(accepted["reviewed_at"], fx.INITIAL_CLOCK,
                                  "reviewed_at")

    adjusted = fx.read_deal(api, deal_id)
    asserts.assert_money(adjusted["contract_price_usd_per_mwh"], SURVIVED_PRICE,
                         "contract_price_usd_per_mwh")
    asserts.assert_mwh(adjusted["expected_annual_mwh"], LAW_EXPECTED_MWH,
                       "expected_annual_mwh", places=2)
    asserts.assert_money(adjusted["exposure_usd"], SURVIVED_EXPOSURE_USD,
                         "exposure_usd")
    asserts.assert_money(adjusted["credit_support_required_usd"], 0.00,
                         "credit_support_required_usd")
    asserts.assert_version_advanced_by(before["version"], adjusted["version"], 1,
                                       "deal version")

    # Hop three has nothing to catch: the requirement fell rather than rose.
    assert adjusted["credit_status"] == "APPROVED", adjusted
    assert adjusted["support_cure_deadline"] is None, adjusted


# ---------------------------------------------------------------------------
# Two deadlines guard one condition, and the clock decides which branch is left.
# ---------------------------------------------------------------------------

#: Three days past the PERMITTING deadline of 2027-04-28, and eight months
#: inside the INTERCONNECTION deadline of 2028-01-23.
CLOCK_PAST_PERMITTING = "2027-05-01T00:00:00Z"

#: Past the 15-day cure window that the failure opened.
CLOCK_PAST_THE_CURE = "2027-06-01T00:00:00Z"

CURE_WINDOW_DAYS = 15

#: One of three conditions cleared: the half-up rounding of 33.333…
ONE_OF_THREE_PCT = 33.33


def test_02_an_expired_condition_may_only_be_failed_and_the_cure_expires_too(api):
    """Satisfying after the deadline is refused, its live sibling satisfies in the
    same breath, failing the expired row is still legal, and re-curing after the
    cure window closes is refused by the same code.

    "`SATISFY` moves the condition `PENDING → SATISFIED`; it requires that the
    deal's `status` is `EXECUTED`, that the logical clock is at or before the
    condition's `deadline_date` — satisfying after the deadline is refused with
    `ERR_CP_DEADLINE_PASSED`, and an expired condition can then only be failed or
    waived — and that the request supplies `evidence_ref`, which is stored along
    with `resolved_at` at the logical clock and `resolved_by_user_id` from the
    acting operator."

    "`FAIL` moves the condition `PENDING → FAILED` and is legal while the deal's
    `status` is `EXECUTED` or `TERMINATED`."

    "It stamps `resolved_at` at the logical clock and `resolved_by_user_id` from the
    acting operator, sets `cure_deadline` to 15 days after the logical clock, and
    vests the `CP_FAILURE` termination right on the deal."

    "`RECURE` is the cure loop that makes this machine non-linear: it moves the
    condition `FAILED → PENDING`, requires that the deal's `status` is `EXECUTED`
    and that the logical clock is at or before the condition's `cure_deadline` —
    otherwise `ERR_CP_DEADLINE_PASSED` — clears both `cure_deadline` and
    `resolved_at` back to null, and pushes `deadline_date` out to 15 days after the
    logical clock."

    Design: Corner/errors/condition_precedent_resolution_after_its_deadline_or_cure_window_is_refused
    """
    chain = fx.executed_chain_with_conditions(api)
    deal_id = chain["deal"]["id"]
    assert chain["deal"]["status"] == "EXECUTED", chain["deal"]
    assert chain["deal"]["cp_total_count"] == 3, chain["deal"]
    asserts.assert_score(chain["deal"]["cp_completion_pct"], 0.00,
                         "cp_completion_pct")

    permitting = fx.condition_by_type(api, deal_id, "PERMITTING")
    interconnection = fx.condition_by_type(api, deal_id, "INTERCONNECTION")
    asserts.assert_date_equals(permitting["deadline_date"],
                               fx.date_of(fx.CP_PERMITTING_DEADLINE),
                               "PERMITTING deadline_date")
    asserts.assert_date_equals(interconnection["deadline_date"],
                               fx.date_of(fx.CP_INTERCONNECTION_DEADLINE),
                               "INTERCONNECTION deadline_date")
    assert permitting["is_waivable"] is False, permitting

    fx.set_clock(api, CLOCK_PAST_PERMITTING)
    late = api.resolve_condition_precedent(
        permitting["id"],
        f.cp_resolution_payload("SATISFY", evidence_ref="EV-LATE-0001"),
        ORIGINATOR)
    validate_error(late, ApiErrorId.ERR_CP_DEADLINE_PASSED.value, 409)
    expired = fx.condition_by_type(api, deal_id, "PERMITTING")
    assert expired["status"] == "PENDING", expired
    assert expired["version"] == permitting["version"], expired
    asserts.assert_all_null(expired, ["resolved_at", "resolved_by_user_id",
                                      "evidence_ref", "cure_deadline"])

    # The sibling whose deadline has not passed resolves normally.
    satisfied = fx.satisfy_condition(api, interconnection["id"],
                                     evidence_ref="EV-ICA-0001")
    assert satisfied["status"] == "SATISFIED", satisfied
    asserts.assert_instant_equals(satisfied["resolved_at"],
                                  CLOCK_PAST_PERMITTING, "resolved_at")
    assert satisfied["evidence_ref"] == "EV-ICA-0001", satisfied
    part_cleared = fx.read_deal(api, deal_id)
    asserts.assert_score(part_cleared["cp_completion_pct"], ONE_OF_THREE_PCT,
                         "cp_completion_pct")
    assert part_cleared["status"] == "EXECUTED", part_cleared

    # An expired condition can still be failed, which opens the cure window.
    failed = fx.fail_condition(api, permitting["id"])
    assert failed["status"] == "FAILED", failed
    asserts.assert_instant_equals(failed["resolved_at"], CLOCK_PAST_PERMITTING,
                                  "resolved_at")
    asserts.assert_date_equals(
        failed["cure_deadline"],
        fx.date_of(fx.iso_plus(CLOCK_PAST_PERMITTING, days=CURE_WINDOW_DAYS)),
        "cure_deadline")
    after_failure = fx.read_deal(api, deal_id)
    asserts.assert_score(after_failure["cp_completion_pct"], ONE_OF_THREE_PCT,
                         "cp_completion_pct")

    # The cure window is a second deadline answering with the same code.
    fx.set_clock(api, CLOCK_PAST_THE_CURE)
    late_cure = api.resolve_condition_precedent(
        permitting["id"], f.cp_resolution_payload("RECURE"), ORIGINATOR)
    validate_error(late_cure, ApiErrorId.ERR_CP_DEADLINE_PASSED.value, 409)
    frozen = fx.condition_by_type(api, deal_id, "PERMITTING")
    assert frozen["status"] == "FAILED", frozen
    assert frozen["version"] == failed["version"], frozen
    asserts.assert_date_equals(
        frozen["cure_deadline"],
        fx.date_of(fx.iso_plus(CLOCK_PAST_PERMITTING, days=CURE_WINDOW_DAYS)),
        "cure_deadline")
    unmoved = fx.read_deal(api, deal_id)
    assert unmoved["version"] == after_failure["version"], unmoved
    asserts.assert_score(unmoved["cp_completion_pct"], ONE_OF_THREE_PCT,
                         "cp_completion_pct")


# ---------------------------------------------------------------------------
# Five reasons, five predicates, and none of them free.
# ---------------------------------------------------------------------------

#: A day after the deal's `commercial_operation_deadline` of 2029-12-31.
CLOCK_PAST_COD = "2030-01-01T00:00:00Z"

CASH_FACE_USD = 500000.00
PROJECT_CAPACITY_MW = 100.000
CONTRACTED_MW = 25.000

#: Every reason the enum carries, in the order the PRD predicates them.
ALL_TERMINATION_REASONS = [
    "CP_FAILURE",
    "BUYER_DEFAULT",
    "SELLER_DEFAULT",
    "COD_DEADLINE_MISSED",
    "EXTENDED_FORCE_MAJEURE",
]


def test_03_an_unvested_termination_right_is_refused_for_every_reason(api):
    """On a freshly executed deal not one of the five reasons is vested; once the
    clock passes the commercial operation deadline `COD_DEADLINE_MISSED` vests and
    the three-branch cascade fires.

    "Termination is a `DealCommittee` act citing a single `termination_reason`, and
    there is no unconditional right to walk away — all five reasons are predicated,
    so a request citing a reason whose predicate is false is always refused with
    `ERR_TERMINATION_RIGHT_NOT_VESTED`."

    "`CP_FAILURE` is vested when some condition of the deal has `status` `FAILED`
    and either its `cure_deadline` is null or that `cure_deadline` falls before the
    logical clock."

    "`BUYER_DEFAULT` is vested when the deal's `credit_status` is
    `SUPPORT_SHORTFALL` and its `support_cure_deadline` falls before the logical
    clock."

    "`SELLER_DEFAULT` is vested when the logical clock has passed the deal's
    `commercial_operation_deadline` and the parent project's `status` is still
    anything other than `OPERATIONAL`."

    "`COD_DEADLINE_MISSED` is vested when the logical clock has passed
    `commercial_operation_deadline` and the deal's own `status` is anything other
    than `EFFECTIVE`."

    "`EXTENDED_FORCE_MAJEURE` is vested when some risk claim on the deal has
    `status` `ACCEPTED`, `event_type` `FORCE_MAJEURE` and a `duration_days` of at
    least 180."

    "The first branch fails the outstanding conditions: every condition of the deal
    whose `status` is `PENDING` moves `PENDING → FAILED` with `resolved_at` set to
    the logical clock and `cure_deadline` left null, and then `cp_completion_pct` is
    recomputed over the new statuses."

    "The second branch resolves the collateral: every instrument whose `status` is
    `POSTED` moves `POSTED → DRAWN` when the `termination_reason` is `BUYER_DEFAULT`
    and `POSTED → RELEASED` for every other reason, with `closed_at` stamped in both
    cases, and then `posted_credit_support_usd`, `released_credit_support_usd` and
    `drawn_credit_support_usd` are all recomputed."

    Design: Corner/errors/every_termination_reason_is_conditional_so_an_unvested_right_is_refused
    """
    chain = fx.negotiated_chain(api)
    deal_id = chain["deal"]["id"]
    instrument = fx.post_cash(api, deal_id, CASH_FACE_USD)
    assert instrument["status"] == "POSTED", instrument
    executed = fx.execute_deal(api, deal_id)
    assert executed["status"] == "EXECUTED", executed
    assert executed["credit_status"] == "APPROVED", executed
    asserts.assert_money(executed["posted_credit_support_usd"], CASH_FACE_USD,
                         "posted_credit_support_usd")

    # Nothing has failed, nothing is short, the deadline has not passed and no
    # force majeure has been accepted.
    for reason in ALL_TERMINATION_REASONS:
        refused = api.terminate_deal(deal_id, f.termination_payload(reason),
                                     DEAL_COMMITTEE)
        validate_error(refused,
                       ApiErrorId.ERR_TERMINATION_RIGHT_NOT_VESTED.value, 422)

    intact = fx.read_deal(api, deal_id)
    assert intact["status"] == "EXECUTED", intact
    assert intact["version"] == executed["version"], intact
    asserts.assert_all_null(intact, ["terminated_at", "termination_reason"])

    # One day past the outside date the fourth predicate turns true.
    fx.set_clock(api, CLOCK_PAST_COD)
    terminated = fx.terminate_deal(api, deal_id, "COD_DEADLINE_MISSED")
    assert terminated["status"] == "TERMINATED", terminated
    assert terminated["termination_reason"] == "COD_DEADLINE_MISSED", terminated
    asserts.assert_instant_equals(terminated["terminated_at"], CLOCK_PAST_COD,
                                  "terminated_at")
    asserts.assert_version_advanced_by(intact["version"],
                                       terminated["version"], 1,
                                       "deal version")

    # Branch one: the outstanding conditions fail with no cure window at all.
    conditions = fx.conditions_of(api, deal_id)
    assert len(conditions) == 3, conditions
    for condition in conditions:
        assert condition["status"] == "FAILED", condition
        asserts.assert_instant_equals(condition["resolved_at"], CLOCK_PAST_COD,
                                      "resolved_at")
        assert condition["cure_deadline"] is None, condition
    asserts.assert_score(terminated["cp_completion_pct"], 0.00,
                         "cp_completion_pct")

    # Branch two: the reason is not BUYER_DEFAULT, so the cash is released.
    instruments, _ = fx.list_all(api.list_credit_support(deal_id, CREDIT_OFFICER))
    released = asserts.row_by_id(instruments, instrument["id"])
    assert released["status"] == "RELEASED", released
    asserts.assert_instant_equals(released["closed_at"], CLOCK_PAST_COD,
                                  "closed_at")
    asserts.assert_money(terminated["posted_credit_support_usd"], 0.00,
                         "posted_credit_support_usd")
    asserts.assert_money(terminated["released_credit_support_usd"],
                         CASH_FACE_USD, "released_credit_support_usd")
    asserts.assert_money(terminated["drawn_credit_support_usd"], 0.00,
                         "drawn_credit_support_usd")

    # The slice is untouched — only the TERMS_AGREED path withdraws slices — and
    # the project's ledger no longer counts the deal.
    slices, _ = fx.list_all(api.list_allocations(deal_id, ORIGINATOR))
    assert [row["status"] for row in slices] == ["CONFIRMED"], slices
    asserts.assert_mw(terminated["confirmed_allocated_mw"], CONTRACTED_MW,
                      "confirmed_allocated_mw")
    ledger = fx.read_project(api, chain["project"]["id"])
    asserts.assert_mw(ledger["contracted_mw"], 0.000, "contracted_mw")
    asserts.assert_mw(ledger["available_mw"], PROJECT_CAPACITY_MW,
                      "available_mw")


# ---------------------------------------------------------------------------
# Half-open windows abut freely and intersect never.
# ---------------------------------------------------------------------------

AUGUST_START = "2026-08-01T00:00:00Z"
AUGUST_END = "2026-09-01T00:00:00Z"
SEPTEMBER_END = "2026-10-01T00:00:00Z"
JULY_START = "2026-07-01T00:00:00Z"

#: Four ways to intersect one window: straddling its end, sitting strictly
#: inside it, straddling its start, and swallowing it whole.
INTERSECTING_WINDOWS = [
    ("2026-08-15T00:00:00Z", "2026-09-15T00:00:00Z"),
    ("2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z"),
    ("2026-07-15T00:00:00Z", "2026-08-15T00:00:00Z"),
    ("2026-07-01T00:00:00Z", "2026-10-01T00:00:00Z"),
]

#: A window that ends where it begins, and one that ends before it begins.
MALFORMED_WINDOWS = [
    ("2026-10-01T00:00:00Z", "2026-10-01T00:00:00Z"),
    ("2026-11-01T00:00:00Z", "2026-10-15T00:00:00Z"),
]


def test_04_settlement_windows_may_touch_but_never_intersect_or_invert(api):
    """Four different intersections with one August window are all refused, the two
    windows that merely touch its endpoints are both accepted, and a window that is
    not strictly increasing is refused by a different code entirely.

    "The deal's `status` must be `EFFECTIVE`; `period_end` must fall strictly after
    `period_start` or the request is refused with `ERR_INVALID_WINDOW`; and the new
    window must not intersect any existing period of the same deal, or the request
    is refused with `ERR_SETTLEMENT_PERIOD_OVERLAP`."

    "Overlap here uses **half-open** semantics on the range from `period_start` up
    to but not including `period_end`, so a period beginning at exactly the instant
    a previous one ends is accepted — deliberately the opposite convention from the
    one that governs risk claims."

    "On creation the period's `netting_method` is computed as a snapshot of the
    deal's `settlement_frequency` and never changes afterwards; since a deal is
    created with one `settlement_frequency` and no operation amends it, comparing
    the two netting variants requires two deals."

    Design: Corner/errors/settlement_periods_abut_freely_but_may_not_intersect_or_invert
    """
    chain = fx.chain_c(api)
    deal_id = chain["deal"]["id"]
    assert chain["deal"]["status"] == "EFFECTIVE", chain["deal"]

    august = fx.open_period(api, deal_id, AUGUST_START, AUGUST_END)
    assert august["status"] == "OPEN", august
    assert august["netting_method"] == "HOURLY", august
    assert august["interval_count"] == 0, august

    for period_start, period_end in INTERSECTING_WINDOWS:
        collision = api.create_settlement_period(
            deal_id, f.settlement_period_payload(period_start, period_end),
            SETTLEMENT_ANALYST)
        validate_error(collision,
                       ApiErrorId.ERR_SETTLEMENT_PERIOD_OVERLAP.value, 409)

    # Touching endpoints are not intersections under half-open semantics.
    september = fx.open_period(api, deal_id, AUGUST_END, SEPTEMBER_END)
    assert september["netting_method"] == "HOURLY", september
    july = fx.open_period(api, deal_id, JULY_START, AUGUST_START)
    assert july["status"] == "OPEN", july

    for period_start, period_end in MALFORMED_WINDOWS:
        malformed = api.create_settlement_period(
            deal_id, f.settlement_period_payload(period_start, period_end),
            SETTLEMENT_ANALYST)
        validate_error(malformed, ApiErrorId.ERR_INVALID_WINDOW.value, 422)

    rows, meta = fx.list_all(api.list_settlement_periods(deal_id,
                                                         SETTLEMENT_ANALYST))
    assert meta["total_count"] == 3, meta
    assert sorted(asserts.ids_of(rows)) == sorted(
        asserts.ids_of([july, august, september])), rows
    for row in rows:
        assert row["netting_method"] == "HOURLY", row


# ---------------------------------------------------------------------------
# Conveyance guards a confirmed slice, then a registry account, then the year.
# ---------------------------------------------------------------------------

#: 40 for the science-based target, 20 for a 2030 target, 10 for reporting under
#: a framework: exactly the 70.00 the QUALIFY gate demands, and no registry
#: account at all.
CASCADIA_INPUTS = {
    "legal_name": "Cascadia Foods Co",
    "credit_rating": "BBB",
    "reported_ebitda_usd": 40000000.00,
    "net_debt_to_ebitda": 3.0,
    "has_science_based_target": True,
    "scope2_target_year": 2030,
}

OUTSIDER_ACCOUNT = "WREGIS-ACC-00918"

ANCHOR_MW = 15.000
CASCADIA_MW = 10.000

CONVEYANCE_CLOCK = "2027-08-01T00:00:00Z"
VINTAGE_PERIOD_START = "2027-07-01T00:00:00Z"
VINTAGE_PERIOD_END = "2027-08-01T00:00:00Z"
VINTAGE_MONTH = "2027-07"

#: One uncurtailed hour of 30.0000 MWh, truncated to whole certificates.
METERED_MWH = 30.0000
BATCH_MWH = 30

#: 30 * 15/25 and 30 * 10/25 — both exact, so no remainder is handed out.
ANCHOR_SHARE_MWH = 18
CASCADIA_SHARE_MWH = 12

VINTAGE_YEAR = 2027
CLAIM_YEAR = 2028
OUT_OF_WINDOW_YEARS = [2026, 2029]


def test_05_conveyance_guards_the_slice_then_the_account_then_the_claim_year(api):
    """A buyer with no slice, a buyer with a slice but no registry account and a
    reporting year outside the two-year window are each refused in turn, while the
    anchor takes the whole batch and the split is recorded per confirmed slice.

    "The named recipient must hold a slice on this batch's deal whose `status` is
    `CONFIRMED`, or the transfer is refused with `ERR_NO_CONFIRMED_ALLOCATION` —
    aggregated deals convey attributes only to buyers whose allocation was
    confirmed."

    "That recipient must also have a non-null `registry_account_id`, or the transfer
    is refused with `ERR_REGISTRY_ACCOUNT_MISSING`, because a claim without a
    receiving account and a registry serial cannot be substantiated at all."

    "The batch's `vintage_month` is computed as the calendar year and month of the
    source period's `period_start`, written in four-digit-year-hyphen-two-digit-month
    form."

    "The payload supplies the `claim_year`, the reporting year the buyer will claim
    the certificates against, which must be no earlier than the batch's vintage year
    and no later than one year after it; a `claim_year` outside that two-year window
    is refused with `ERR_CLAIM_YEAR_OUT_OF_WINDOW`."

    "It increases the deal's `attributes_retired_mwh` by `quantity_mwh` and
    increases the recipient buyer's `claimed_attributes_mwh` by the same amount,
    incrementing that buyer's `version` by one; `claimed_attributes_mwh` is the
    running total of environmental attribute megawatt-hours retired in that buyer's
    name across every deal it participates in."

    Design: Corner/errors/attribute_conveyance_guards_allocation_then_registry_then_claim_year
    """
    node = fx.create_node(api)
    anchor = fx.create_qualified_offtaker(api)
    cascadia = fx.create_qualified_offtaker(api, anchor=False, **CASCADIA_INPUTS)
    outsider = fx.create_qualified_offtaker(api, legal_name="Puget Logistics LLC",
                                            registry_account_id=OUTSIDER_ACCOUNT)
    assert cascadia["registry_account_id"] is None, cascadia
    assert anchor["registry_account_id"] is not None, anchor

    project = fx.create_operational_project(api, node["id"])
    deal = fx.create_deal(api, project["id"], anchor["id"], node["id"],
                          product_type="AGGREGATED")
    deal_id = deal["id"]
    negotiation = fx.table_round(
        api, deal_id,
        proposed_fixed_price_usd_per_mwh=deal["base_fixed_price_usd_per_mwh"],
        proposed_escalation_pct_per_year=deal["escalation_pct_per_year"],
        proposed_shape_product=deal["shape_product"],
        proposed_basis_responsibility=deal["basis_responsibility"])
    fx.confirmed_allocation(api, deal_id, anchor["id"], ANCHOR_MW)
    fx.confirmed_allocation(api, deal_id, cascadia["id"], CASCADIA_MW)
    fx.respond_accept(api, negotiation["id"], anchor["id"])
    fx.submit_credit(api, deal_id)
    fx.decide_credit(api, deal_id, "APPROVE")
    effective = fx.execute_deal(api, deal_id)
    assert effective["status"] == "EFFECTIVE", effective

    fx.set_clock(api, CONVEYANCE_CLOCK)
    period = fx.open_period(api, deal_id, VINTAGE_PERIOD_START,
                            VINTAGE_PERIOD_END)
    fx.post_interval(api, period["id"], VINTAGE_PERIOD_START, METERED_MWH)
    calculated = fx.calculate_period(api, period["id"])
    assert calculated["mintable_attributes_mwh"] == BATCH_MWH, calculated

    batch = fx.mint_batch(api, period["id"], BATCH_MWH)
    assert batch["status"] == "MINTED", batch
    assert batch["vintage_month"] == VINTAGE_MONTH, batch
    assert batch["allocation_breakdown"] == [], batch

    # A qualified buyer that holds no slice on this deal.
    no_slice = api.transfer_attribute_batch(
        batch["id"], f.transfer_payload(outsider["id"]), REGISTRY_AGENT)
    validate_error(no_slice, ApiErrorId.ERR_NO_CONFIRMED_ALLOCATION.value, 422)

    # A confirmed slice holder with nowhere to receive the certificates.
    no_account = api.transfer_attribute_batch(
        batch["id"], f.transfer_payload(cascadia["id"]), REGISTRY_AGENT)
    validate_error(no_account,
                   ApiErrorId.ERR_REGISTRY_ACCOUNT_MISSING.value, 422)

    transferred = fx.transfer_batch(api, batch["id"], anchor["id"])
    assert transferred["status"] == "TRANSFERRED", transferred
    assert transferred["transferred_to_offtaker_id"] == anchor["id"], transferred
    asserts.assert_instant_equals(transferred["transferred_at"],
                                  CONVEYANCE_CLOCK, "transferred_at")
    asserts.assert_breakdown_rows(transferred["allocation_breakdown"],
                                  [(anchor["id"], ANCHOR_SHARE_MWH),
                                   (cascadia["id"], CASCADIA_SHARE_MWH)])

    for claim_year in OUT_OF_WINDOW_YEARS:
        refused = api.retire_attribute_batch(
            batch["id"], f.retire_payload(claim_year), REGISTRY_AGENT)
        validate_error(refused,
                       ApiErrorId.ERR_CLAIM_YEAR_OUT_OF_WINDOW.value, 422)
    held = get_success_data(api.get_deal(deal_id, ORIGINATOR), 200)
    assert held["attributes_retired_mwh"] == 0, held

    retired = fx.retire_batch(api, batch["id"], CLAIM_YEAR)
    assert retired["status"] == "RETIRED", retired
    assert retired["claim_year"] == CLAIM_YEAR, retired
    assert retired["claim_substantiation_status"] == "SUBSTANTIATED", retired
    asserts.assert_instant_equals(retired["retired_at"], CONVEYANCE_CLOCK,
                                  "retired_at")

    # The whole batch is claimed in the recipient's name, not split by slice.
    claimed = fx.read_offtaker(api, anchor["id"])
    assert claimed["claimed_attributes_mwh"] == BATCH_MWH, claimed
    unclaimed = fx.read_offtaker(api, cascadia["id"])
    assert unclaimed["claimed_attributes_mwh"] == 0, unclaimed
    conveyed = fx.read_deal(api, deal_id)
    assert conveyed["attributes_minted_mwh"] == BATCH_MWH, conveyed
    assert conveyed["attributes_transferred_mwh"] == BATCH_MWH, conveyed
    assert conveyed["attributes_retired_mwh"] == BATCH_MWH, conveyed


# ---------------------------------------------------------------------------
# Eligibility is a table-membership test, and it answers before the tenor rule.
# ---------------------------------------------------------------------------

#: Fourteen days of tenor from the logical clock: far short of 365 whole days.
SHORT_EXPIRY = "2026-08-15T00:00:00Z"
LONG_EXPIRY = "2031-12-31T00:00:00Z"

#: BBB / FITCH / 4.0 / NONE scores 62.10, so the guarantor's tier is STANDARD
#: and the only limb of the guarantee test that can fail is the identity one.
UNRELATED_GUARANTOR = {
    "legal_name": "Unrelated Holdings Ltd",
    "credit_rating": "BBB",
    "rating_agency": "FITCH",
    "reported_ebitda_usd": 20000000.00,
    "net_debt_to_ebitda": 4.0,
    "disclosure_framework": "NONE",
}
GUARANTOR_TIER = "STANDARD"

INELIGIBLE_FACE_USD = 1000000.00
CASH_FACE_SHORT_TENOR_USD = 500000.00
BBB_FACE_USD = 1000000.00
BBB_HAIRCUT_PCT = 10.00
BBB_ELIGIBLE_USD = 900000.00
TOTAL_POSTED_USD = 1400000.00


def test_06_an_issuer_with_no_haircut_row_is_refused_before_the_tenor_test(api):
    """A `CCC` letter that is also far too short answers on eligibility rather than
    tenor, an unrelated guarantor is equally ineligible, an identically short cash
    deposit posts anyway, and the `BBB` letter carries its ten percent discount.

    "The instrument must be `PROPOSED`, and the deal's `credit_status` must be
    `SUBMITTED`, `APPROVED`, `SUPPORT_SHORTFALL` or `DECLINED`."

    "A `LETTER_OF_CREDIT` requires an `issuer_name` and an `issuer_rating` among
    `AAA`, `AA`, `A`, `BBB` and `BB`; an unrated issuer or one rated `B`, `CCC` or
    `NR` has no haircut row and is refused with `ERR_INELIGIBLE_ISSUER`."

    "A `PARENT_GUARANTEE` requires a `guarantor_offtaker_id` that is present, equal
    to the anchor buyer's own `parent_guarantor_offtaker_id`, and belonging to a
    guarantor whose `credit_tier` is not `DECLINED`; any of those failing is also
    `ERR_INELIGIBLE_ISSUER`."

    "`CASH_COLLATERAL` consults neither issuer nor guarantor fields."

    "Tenor is tested only after eligibility: a letter of credit or a parent guarantee
    must have at least 365 whole days from the logical clock to its `expiry_date`, or
    the post is refused with `ERR_INSTRUMENT_TENOR_TOO_SHORT`; cash collateral is
    exempt from the tenor rule entirely."

    "A letter of credit is discounted by the issuing bank's rating: 0.00 for `AAA`,
    `AA` and `A`, 10.00 for `BBB` and 35.00 for `BB`."

    "A successful post moves the instrument `PROPOSED → POSTED`, stamps `posted_at`
    with the logical clock, and recomputes the deal's `posted_credit_support_usd` as
    the sum of `eligible_credit_usd` over that deal's `POSTED` instruments."

    Design: Corner/errors/issuer_eligibility_is_a_haircut_table_membership_test_decided_before_tenor
    """
    guarantor = fx.create_submitted_offtaker(api, anchor=False,
                                             **UNRELATED_GUARANTOR)
    assert guarantor["credit_tier"] == GUARANTOR_TIER, guarantor

    chain = fx.negotiated_chain(api)
    deal_id = chain["deal"]["id"]
    assert chain["deal"]["credit_status"] == "APPROVED", chain["deal"]
    assert chain["buyer"]["parent_guarantor_offtaker_id"] is None, chain["buyer"]

    ineligible_letter = fx.register_letter_of_credit(
        api, deal_id, INELIGIBLE_FACE_USD, issuer_name="Marginal Credit Bank",
        issuer_rating="CCC", expiry_date=SHORT_EXPIRY)
    short_but_rated = fx.register_letter_of_credit(
        api, deal_id, INELIGIBLE_FACE_USD, issuer_name="First Pacific Bank",
        issuer_rating="A", expiry_date=SHORT_EXPIRY)
    unrelated_guarantee = fx.register_parent_guarantee(
        api, deal_id, INELIGIBLE_FACE_USD, guarantor["id"],
        expiry_date=LONG_EXPIRY)

    # Both letters carry the same fourteen days of tenor, and only the rated one
    # is answered by the tenor rule: eligibility is decided first.
    refused_issuer = api.post_credit_support(
        ineligible_letter["id"],
        f.post_credit_support_payload(fx.deal_version(api, deal_id)),
        CREDIT_OFFICER)
    validate_error(refused_issuer, ApiErrorId.ERR_INELIGIBLE_ISSUER.value, 422)

    refused_tenor = api.post_credit_support(
        short_but_rated["id"],
        f.post_credit_support_payload(fx.deal_version(api, deal_id)),
        CREDIT_OFFICER)
    validate_error(refused_tenor,
                   ApiErrorId.ERR_INSTRUMENT_TENOR_TOO_SHORT.value, 422)

    # A guarantor the anchor buyer never named, however creditworthy.
    refused_guarantor = api.post_credit_support(
        unrelated_guarantee["id"],
        f.post_credit_support_payload(fx.deal_version(api, deal_id)),
        CREDIT_OFFICER)
    validate_error(refused_guarantor, ApiErrorId.ERR_INELIGIBLE_ISSUER.value,
                   422)

    stack, _ = fx.list_all(api.list_credit_support(deal_id, CREDIT_OFFICER))
    for instrument_id in (ineligible_letter["id"], short_but_rated["id"],
                          unrelated_guarantee["id"]):
        held = asserts.row_by_id(stack, instrument_id)
        assert held["status"] == "PROPOSED", held
        asserts.assert_all_null(held, ["haircut_pct", "eligible_credit_usd",
                                       "posted_at", "closed_at"])
    at_rest = fx.read_deal(api, deal_id)
    asserts.assert_money(at_rest["posted_credit_support_usd"], 0.00,
                         "posted_credit_support_usd")

    # Cash consults neither table and is exempt from the tenor rule, so the very
    # same fourteen days of tenor posts without complaint.
    cash = fx.register_cash(api, deal_id, CASH_FACE_SHORT_TENOR_USD,
                            expiry_date=SHORT_EXPIRY)
    posted_cash = fx.post_instrument(api, deal_id, cash["id"])
    assert posted_cash["status"] == "POSTED", posted_cash
    asserts.assert_money(posted_cash["haircut_pct"], 0.00, "haircut_pct")
    asserts.assert_money(posted_cash["eligible_credit_usd"],
                         CASH_FACE_SHORT_TENOR_USD, "eligible_credit_usd")
    asserts.assert_instant_equals(posted_cash["posted_at"], fx.INITIAL_CLOCK,
                                  "posted_at")

    # A rated issuer with a row in the table and tenor to spare.
    bbb_letter = fx.register_letter_of_credit(
        api, deal_id, BBB_FACE_USD, issuer_name="Second Federal Bank",
        issuer_rating="BBB", expiry_date=LONG_EXPIRY)
    posted_letter = fx.post_instrument(api, deal_id, bbb_letter["id"])
    assert posted_letter["status"] == "POSTED", posted_letter
    asserts.assert_money(posted_letter["haircut_pct"], BBB_HAIRCUT_PCT,
                         "haircut_pct")
    asserts.assert_money(posted_letter["eligible_credit_usd"],
                         BBB_ELIGIBLE_USD, "eligible_credit_usd")

    covered = fx.read_deal(api, deal_id)
    asserts.assert_money(covered["posted_credit_support_usd"], TOTAL_POSTED_USD,
                         "posted_credit_support_usd")
    assert covered["credit_status"] == "APPROVED", covered
    assert covered["status"] == "TERMS_AGREED", covered
