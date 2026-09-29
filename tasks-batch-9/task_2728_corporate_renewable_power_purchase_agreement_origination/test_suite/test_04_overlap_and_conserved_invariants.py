"""Two scarce slots that may not be double-booked, and two quantities that may
not be created or destroyed.

Risk-claim windows collide on closed intervals but only within one event type;
metered hours occupy one slot each inside a half-open period.  Money moves
between the posted, released and drawn buckets of a deal's collateral stack
without changing their total, and whole megawatt-hours of environmental
attributes move between three nested buckets under the same discipline.
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
    DEAL_COMMITTEE_ID,
    ORIGINATOR,
    REGISTRY_AGENT,
    SETTLEMENT_ANALYST,
    make_offtaker_rep_headers,
)

# ---------------------------------------------------------------------------
# Instance: a risk claim's window is the scarce resource, closed at both ends
# and partitioned by event type.
# ---------------------------------------------------------------------------

#: The claim already on the books, filed over eleven days of July 2027.
OPEN_CLAIM_WINDOW = ("2027-07-10T00:00:00Z", "2027-07-20T00:00:00Z")

#: A window whose start is exactly the open claim's end.
ABUTS_AFTER = ("2027-07-20T00:00:00Z", "2027-07-28T00:00:00Z")

#: A window whose end is exactly the open claim's start.
ABUTS_BEFORE = ("2027-07-02T00:00:00Z", "2027-07-10T00:00:00Z")

#: One day clear of the open claim's end: the first window that fits.
CLEAR_OF_THE_CLAIM = ("2027-07-21T00:00:00Z", "2027-07-28T00:00:00Z")

#: Wholly inside the open claim's window, and therefore only filable under a
#: different event type.
INSIDE_THE_CLAIM = ("2027-07-12T00:00:00Z", "2027-07-18T00:00:00Z")


def _effective_deal_with_one_open_claim(api):
    """An `EFFECTIVE` deal on an operational project carrying one `CLAIMED` row.

    The project is already `OPERATIONAL` and the anchor buyer already holds a
    registry account, so execution produces the empty condition template and the
    deal is `EFFECTIVE` in the same request — the state a claim requires.
    """
    chain = fx.chain_c(api, project_overrides={
        "name": "Kramer Junction Solar II",
        "cod_target_date": "2026-07-01T00:00:00Z"})
    chain["claim"] = fx.file_risk_event(api, chain["deal"]["id"], "CURTAILMENT",
                                        *OPEN_CLAIM_WINDOW)
    return chain


def _claims_on(api, deal_id, params=None):
    rows, _ = fx.list_all(api.list_risk_events(deal_id, ORIGINATOR, params))
    return rows


def test_01_a_claim_beginning_where_another_ends_collides_with_it(api):
    """Both touching windows are refused while a one-day gap is accepted.

    "Collision here is **closed-interval**: the window runs from `window_start`
    through `window_end` inclusive of both ends, so touching endpoints do collide
    and a claim starting at exactly the instant another ends is rejected."

    Design: Difficulty/resource_temporal_overlap/risk_event_closed_window_touching_endpoints_collide_per_event_type
    """
    chain = _effective_deal_with_one_open_claim(api)
    deal_id = chain["deal"]["id"]
    baseline = chain["claim"]

    # A window opening at the exact instant the live claim closes.
    refused_after = api.create_risk_event(
        deal_id, f.risk_event_payload("CURTAILMENT", *ABUTS_AFTER), ORIGINATOR)
    validate_error(refused_after, ApiErrorId.ERR_RISK_WINDOW_OVERLAP.value, 409)
    asserts.assert_error_envelope(refused_after)

    # And the mirror image: a window closing at the instant the claim opens.
    refused_before = api.create_risk_event(
        deal_id, f.risk_event_payload("CURTAILMENT", *ABUTS_BEFORE), ORIGINATOR)
    validate_error(refused_before, ApiErrorId.ERR_RISK_WINDOW_OVERLAP.value, 409)

    # One day clear of the closed end, the same event type is admitted.
    admitted = fx.file_risk_event(api, deal_id, "CURTAILMENT",
                                  *CLEAR_OF_THE_CLAIM)
    assert admitted["status"] == "CLAIMED", admitted
    assert admitted["event_type"] == "CURTAILMENT", admitted
    asserts.assert_instant_equals(admitted["window_start"],
                                  CLEAR_OF_THE_CLAIM[0], "window_start")
    asserts.assert_instant_equals(admitted["window_end"],
                                  CLEAR_OF_THE_CLAIM[1], "window_end")
    asserts.assert_all_null(admitted, ["allocation_outcome",
                                       "price_adjustment_usd_per_mwh",
                                       "duration_days", "reviewed_by_user_id",
                                       "reviewed_at"])
    assert admitted["excused_hours"] == 0, admitted

    # Neither refusal disturbed the claim that owns the contested window.
    rows = _claims_on(api, deal_id)
    assert len(rows) == 2, rows
    still_open = asserts.row_by_id(rows, baseline["id"])
    assert still_open["status"] == "CLAIMED", still_open
    assert still_open["version"] == baseline["version"], still_open
    asserts.assert_instant_equals(still_open["window_end"],
                                  OPEN_CLAIM_WINDOW[1], "window_end")


def test_02_the_slot_is_per_event_type_and_a_rejection_hands_it_back(api):
    """A force-majeure claim fits inside a live curtailment window, and refiling
    the very same force-majeure window succeeds once the first is `REJECTED`.

    "It must then not collide with any existing claim of the same deal carrying
    the same `event_type` whose `status` is `CLAIMED` or `ACCEPTED`, or the claim
    is refused with `ERR_RISK_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/risk_event_closed_window_touching_endpoints_collide_per_event_type
    """
    chain = _effective_deal_with_one_open_claim(api)
    deal_id = chain["deal"]["id"]
    buyer_headers = make_offtaker_rep_headers(chain["buyer"]["id"])

    # The buyer files force majeure over days the developer's curtailment claim
    # already covers: a different event type is a different resource.
    force_majeure = fx.file_risk_event(api, deal_id, "FORCE_MAJEURE",
                                       *INSIDE_THE_CLAIM,
                                       headers=buyer_headers,
                                       claimed_by="OFFTAKER")
    assert force_majeure["status"] == "CLAIMED", force_majeure
    assert force_majeure["claimed_by"] == "OFFTAKER", force_majeure

    # A second force-majeure claim over the same days is refused while the first
    # is live, which is what makes the release below meaningful.
    collides = api.create_risk_event(
        deal_id,
        f.risk_event_payload("FORCE_MAJEURE", *INSIDE_THE_CLAIM), ORIGINATOR)
    validate_error(collides, ApiErrorId.ERR_RISK_WINDOW_OVERLAP.value, 409)

    reviewed = fx.review_risk_event(api, force_majeure["id"], "REJECT")
    assert reviewed["status"] == "REJECTED", reviewed
    asserts.assert_all_null(reviewed, ["allocation_outcome",
                                       "price_adjustment_usd_per_mwh"])
    assert reviewed["excused_hours"] == 0, reviewed
    assert reviewed["reviewed_by_user_id"] == DEAL_COMMITTEE_ID, reviewed
    asserts.assert_instant_equals(reviewed["reviewed_at"], fx.INITIAL_CLOCK,
                                  "reviewed_at")

    # The rejected claim no longer holds its window, so the identical window is
    # filable again.
    refiled = fx.file_risk_event(api, deal_id, "FORCE_MAJEURE",
                                 *INSIDE_THE_CLAIM)
    assert refiled["status"] == "CLAIMED", refiled
    assert refiled["id"] != force_majeure["id"], refiled

    rows = _claims_on(api, deal_id)
    assert len(rows) == 3, rows
    assert asserts.row_by_id(rows, chain["claim"]["id"])["status"] == "CLAIMED"
    by_type = [row for row in rows if row["event_type"] == "FORCE_MAJEURE"]
    assert sorted(row["status"] for row in by_type) == ["CLAIMED", "REJECTED"]


# ---------------------------------------------------------------------------
# Instance: a metered hour is a one-hour slot inside a half-open period, so the
# duplicate test and the in-window test answer different questions.
# ---------------------------------------------------------------------------

FIRST_PERIOD = ("2027-07-01T00:00:00Z", "2027-08-01T00:00:00Z")

#: The next period opens at the exact instant the first one closes, which the
#: half-open period convention accepts.
SECOND_PERIOD = ("2027-08-01T00:00:00Z", "2027-09-01T00:00:00Z")

#: The first two hours of July, adjacent but distinct slots.
FIRST_HOUR = "2027-07-01T00:00:00Z"
SECOND_HOUR = "2027-07-01T01:00:00Z"

#: Exactly the first period's exclusive end.
BOUNDARY_HOUR = "2027-08-01T00:00:00Z"

#: Inside the window but not on the hour.
HALF_PAST_HOUR = "2027-07-01T00:30:00Z"

OPEN_PERIOD_MONEY_FIELDS = [
    "weighted_avg_index_usd_per_mwh",
    "energy_settlement_usd",
    "basis_adjustment_usd",
    "net_settlement_usd",
    "seller_pays_usd",
    "buyer_pays_usd",
    "mintable_attributes_mwh",
    "calculated_at",
]


def _deal_with_two_abutting_periods(api):
    """An `EFFECTIVE` deal carrying July and August 2027 as two `OPEN` periods.

    "Overlap here uses **half-open** semantics on the range from `period_start`
    up to but not including `period_end`, so a period beginning at exactly the
    instant a previous one ends is accepted — deliberately the opposite
    convention from the one that governs risk claims."
    """
    chain = fx.chain_c(api, project_overrides={
        "name": "Kramer Junction Solar II",
        "cod_target_date": "2026-07-01T00:00:00Z"})
    deal_id = chain["deal"]["id"]
    chain["july"] = fx.open_period(api, deal_id, *FIRST_PERIOD)
    chain["august"] = fx.open_period(api, deal_id, *SECOND_PERIOD)
    return chain


def _post_hour(api, period_id, hour_start, metered_mwh,
               node_price_usd_per_mwh=30.00, hub_price_usd_per_mwh=35.00,
               token=None):
    """Attempt one interval post, returning the raw response."""
    if token is None:
        token = fx.period_version(api, period_id)
    return api.create_meter_interval(
        period_id,
        f.meter_interval_payload(hour_start, metered_mwh,
                                 node_price_usd_per_mwh, hub_price_usd_per_mwh,
                                 token), SETTLEMENT_ANALYST)


def test_03_an_adjacent_hour_is_a_new_slot_but_the_same_hour_is_not(api):
    """Midnight and one o'clock both load; midnight a second time is refused and
    overwrites nothing.

    "Only after that in-window test does the duplicate test run: an hour already
    loaded into this period is refused with `ERR_DUPLICATE_METER_HOUR`, so a
    duplicate hour that is also out of range returns the out-of-range error
    instead."

    Design: Difficulty/resource_temporal_overlap/meter_interval_hour_slot_duplicate_versus_abutting_hour_and_period_boundary
    """
    chain = _deal_with_two_abutting_periods(api)
    period_id = chain["july"]["id"]

    midnight = get_success_data(_post_hour(api, period_id, FIRST_HOUR, 10.0000,
                                           30.00, 35.00), 201)
    assert midnight["settlement_period_id"] == period_id, midnight
    asserts.assert_mwh(midnight["metered_mwh"], 10.0000, "metered_mwh")
    asserts.assert_all_null(midnight, ["expected_mwh", "delivered_mwh"])
    asserts.assert_mwh(midnight["deemed_mwh"], 0.0000, "deemed_mwh")
    assert midnight["curtailment_flag"] == "NONE", midnight

    one_oclock = get_success_data(_post_hour(api, period_id, SECOND_HOUR,
                                             12.0000, 31.00, 36.00), 201)
    assert one_oclock["id"] != midnight["id"], one_oclock
    asserts.assert_mwh(one_oclock["metered_mwh"], 12.0000, "metered_mwh")

    loaded = fx.read_period(api, period_id)
    assert loaded["interval_count"] == 2, loaded
    token = loaded["version"]

    # The same slot again, carrying a different volume and a current token.
    duplicate = _post_hour(api, period_id, FIRST_HOUR, 9.5000, 30.00, 35.00,
                           token=token)
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_METER_HOUR.value, 409)
    asserts.assert_error_envelope(duplicate)

    # No upsert: the stored hour keeps its original volume, the count is
    # unchanged, and the concurrency token the refused post carried is still
    # the live one.
    hours = fx.intervals_of(api, period_id)
    assert len(hours) == 2, hours
    asserts.assert_mwh(asserts.row_by_id(hours, midnight["id"])["metered_mwh"],
                       10.0000, "metered_mwh")
    after = fx.read_period(api, period_id)
    assert after["interval_count"] == 2, after
    assert after["version"] == token, after
    assert after["status"] == "OPEN", after


def test_04_the_period_end_instant_belongs_to_the_next_period_not_this_one(api):
    """The instant that closes July is refused for July and accepted for August,
    and a half-past instant is refused outright.

    "The `hour_start` must land exactly on the hour and must lie inside the
    period's half-open window — an `hour_start` equal to `period_end` is outside
    the period — or the request is refused with `ERR_HOUR_OUTSIDE_PERIOD`."

    Design: Difficulty/resource_temporal_overlap/meter_interval_hour_slot_duplicate_versus_abutting_hour_and_period_boundary
    """
    chain = _deal_with_two_abutting_periods(api)
    july_id = chain["july"]["id"]
    august_id = chain["august"]["id"]
    july_token = chain["july"]["version"]

    outside = _post_hour(api, july_id, BOUNDARY_HOUR, 11.0000, token=july_token)
    validate_error(outside, ApiErrorId.ERR_HOUR_OUTSIDE_PERIOD.value, 422)
    asserts.assert_error_envelope(outside)

    off_the_hour = _post_hour(api, july_id, HALF_PAST_HOUR, 11.0000,
                              token=july_token)
    validate_error(off_the_hour, ApiErrorId.ERR_HOUR_OUTSIDE_PERIOD.value, 422)

    # The very instant July refused is August's inclusive first hour.
    admitted = get_success_data(_post_hour(api, august_id, BOUNDARY_HOUR,
                                           11.0000), 201)
    assert admitted["settlement_period_id"] == august_id, admitted
    asserts.assert_instant_equals(admitted["hour_start"], BOUNDARY_HOUR,
                                  "hour_start")

    july = fx.read_period(api, july_id)
    assert july["interval_count"] == 0, july
    assert july["version"] == july_token, july
    assert july["status"] == "OPEN", july
    asserts.assert_all_null(july, OPEN_PERIOD_MONEY_FIELDS)

    august = fx.read_period(api, august_id)
    assert august["interval_count"] == 1, august
    assert august["status"] == "OPEN", august
    asserts.assert_all_null(august, OPEN_PERIOD_MONEY_FIELDS)


# ---------------------------------------------------------------------------
# Instance: money in the collateral stack.  Post and release are inverse
# operations over three disjoint buckets whose total never moves.
# ---------------------------------------------------------------------------

#: A fifty-megawatt CFD whose exposure comfortably clears the buyer's unsecured
#: appetite: escalated base 43.35, price tier MID, contract price 44.10, one
#: year of volume 122,640.00 MWh and exposure 5,408,424.00 against a 3,000,000.00
#: threshold, so the requirement is ten increments of 250,000.00.
STACK_TERMS = dict(
    product_type="VIRTUAL_CFD",
    contracted_mw=50.000,
    first_delivery_year=2027,
    base_fixed_price_usd_per_mwh=42.50,
    escalation_pct_per_year=2.0,
    shape_product="AS_GENERATED",
    basis_responsibility="SHARED",
)

STACK_ROUND = dict(
    proposed_fixed_price_usd_per_mwh=42.50,
    proposed_escalation_pct_per_year=2.0,
    proposed_shape_product="AS_GENERATED",
    proposed_basis_responsibility="SHARED",
)

CONTRACT_PRICE = 44.10
EXPECTED_ANNUAL_MWH = 122640.00
EXPOSURE_USD = 5408424.00
UNSECURED_LIMIT_USD = 3000000.00
REQUIREMENT_USD = 2500000.00

CASH_ONE_FACE = 1500000.00
LC_FACE = 2000000.00
LC_ELIGIBLE = 1800000.00
CASH_TWO_FACE = 1000000.00
UNPOSTED_FACE = 750000.00
POSTED_TOTAL = 4300000.00


def _approved_deal_with_a_posted_stack(api):
    """A `TERMS_AGREED` deal with credit `APPROVED` over three posted instruments.

    A fourth instrument is registered and deliberately left `PROPOSED`, so the
    test can show that an unposted face contributes to none of the three buckets.
    """
    chain = fx.origination_chain(api, deal_overrides=dict(STACK_TERMS))
    deal_id = chain["deal"]["id"]
    buyer_id = chain["buyer"]["id"]

    term_sheet = fx.table_round(api, deal_id, **STACK_ROUND)
    fx.confirmed_allocation(api, deal_id, buyer_id, 50.000)
    fx.respond_accept(api, term_sheet["id"], buyer_id)

    chain["cash_one"] = fx.register_cash(
        api, deal_id, CASH_ONE_FACE, expiry_date="2028-12-31T00:00:00Z")
    chain["letter"] = fx.register_letter_of_credit(
        api, deal_id, LC_FACE, issuer_name="Cascade Trust Bank NA",
        issuer_rating="BBB", expiry_date="2027-12-31T00:00:00Z")
    chain["cash_two"] = fx.register_cash(
        api, deal_id, CASH_TWO_FACE, expiry_date="2028-12-31T00:00:00Z")
    chain["unposted"] = fx.register_cash(
        api, deal_id, UNPOSTED_FACE, expiry_date="2028-12-31T00:00:00Z")

    fx.submit_credit(api, deal_id)
    for key in ("cash_one", "letter", "cash_two"):
        chain[key] = fx.post_instrument(api, deal_id, chain[key]["id"])
    chain["deal"] = fx.decide_credit(api, deal_id, "APPROVE")
    return chain


def _stack_of(api, deal_id):
    rows, _ = fx.list_all(api.list_credit_support(deal_id, CREDIT_OFFICER))
    return rows


def _assert_buckets_conserve(deal, total, label):
    """posted + released + drawn is the invariant, whatever the split."""
    moved = (deal["posted_credit_support_usd"]
             + deal["released_credit_support_usd"]
             + deal["drawn_credit_support_usd"])
    asserts.assert_money(moved, total, f"{label}: posted + released + drawn")


def test_05_releasing_an_instrument_moves_its_value_without_destroying_any(api):
    """The posted bucket falls by exactly what the released bucket gains, and the
    released instrument keeps its own valuation.

    "A permitted release moves the instrument `POSTED → RELEASED`, stamps
    `closed_at`, and recomputes both `posted_credit_support_usd` and
    `released_credit_support_usd`, so that posted plus released plus drawn is
    conserved across the deal's whole stack."

    Design: Difficulty/compensating_invariant/credit_support_usd_conserved_across_post_and_release
    """
    chain = _approved_deal_with_a_posted_stack(api)
    deal_id = chain["deal"]["id"]
    before = chain["deal"]

    asserts.assert_money(before["contract_price_usd_per_mwh"], CONTRACT_PRICE,
                         "contract_price_usd_per_mwh")
    asserts.assert_money(before["expected_annual_mwh"], EXPECTED_ANNUAL_MWH,
                         "expected_annual_mwh")
    asserts.assert_money(before["exposure_usd"], EXPOSURE_USD, "exposure_usd")
    asserts.assert_money(before["collateral_threshold_usd"],
                         UNSECURED_LIMIT_USD, "collateral_threshold_usd")
    asserts.assert_money(before["credit_support_required_usd"], REQUIREMENT_USD,
                         "credit_support_required_usd")
    asserts.assert_money(before["posted_credit_support_usd"], POSTED_TOTAL,
                         "posted_credit_support_usd")
    asserts.assert_money(before["released_credit_support_usd"], 0.00,
                         "released_credit_support_usd")
    asserts.assert_money(before["drawn_credit_support_usd"], 0.00,
                         "drawn_credit_support_usd")
    assert before["credit_status"] == "APPROVED", before
    _assert_buckets_conserve(before, POSTED_TOTAL, "before")

    # Each posted instrument carries its own immutable valuation.
    asserts.assert_money(chain["cash_one"]["eligible_credit_usd"],
                         CASH_ONE_FACE, "cash eligible_credit_usd")
    asserts.assert_money(chain["cash_one"]["haircut_pct"], 0.00, "cash haircut")
    asserts.assert_money(chain["letter"]["eligible_credit_usd"], LC_ELIGIBLE,
                         "letter eligible_credit_usd")
    asserts.assert_money(chain["letter"]["haircut_pct"], 10.00, "BBB haircut")
    asserts.assert_money(chain["cash_two"]["eligible_credit_usd"],
                         CASH_TWO_FACE, "cash two eligible_credit_usd")

    # The unposted instrument is in none of the buckets: 1.5M + 1.8M + 1.0M is
    # the whole posted figure, and its own 750,000.00 face is nowhere.
    unposted = asserts.row_by_id(_stack_of(api, deal_id),
                                 chain["unposted"]["id"])
    assert unposted["status"] == "PROPOSED", unposted
    asserts.assert_all_null(unposted, ["haircut_pct", "eligible_credit_usd",
                                       "posted_at", "closed_at"])
    asserts.assert_money(unposted["face_amount_usd"], UNPOSTED_FACE,
                         "face_amount_usd")

    released = fx.release_instrument(api, chain["cash_two"]["id"])
    assert released["status"] == "RELEASED", released
    asserts.assert_instant_equals(released["closed_at"], fx.INITIAL_CLOCK,
                                  "closed_at")
    asserts.assert_version_advanced_by(chain["cash_two"]["version"],
                                       released["version"], 1,
                                       "instrument version")
    # The valuation survives the release untouched.
    asserts.assert_money(released["eligible_credit_usd"], CASH_TWO_FACE,
                         "eligible_credit_usd after release")

    after = fx.read_deal(api, deal_id)
    asserts.assert_money(after["posted_credit_support_usd"],
                         POSTED_TOTAL - CASH_TWO_FACE,
                         "posted_credit_support_usd")
    asserts.assert_money(after["released_credit_support_usd"], CASH_TWO_FACE,
                         "released_credit_support_usd")
    asserts.assert_money(after["drawn_credit_support_usd"], 0.00,
                         "drawn_credit_support_usd")
    _assert_buckets_conserve(after, POSTED_TOTAL, "after the release")
    asserts.assert_version_advanced_by(before["version"], after["version"], 1,
                                       "deal version")


def test_06_a_release_that_would_break_coverage_moves_nothing_at_all(api):
    """With the requirement still 2,500,000.00, releasing the letter of credit is
    refused and every bucket stays exactly where the first release left it.

    "When the deal's `credit_status` is `APPROVED`, a release that would drop
    `posted_credit_support_usd` below `credit_support_required_usd` is refused
    with `ERR_RELEASE_BREACHES_COVERAGE` — the coverage invariant is enforced on
    the reverse action, not only on the forward one."

    Design: Difficulty/compensating_invariant/credit_support_usd_conserved_across_post_and_release
    """
    chain = _approved_deal_with_a_posted_stack(api)
    deal_id = chain["deal"]["id"]

    # The permitted release first: 4.3M less 1.0M still covers 2.5M.
    fx.release_instrument(api, chain["cash_two"]["id"])
    poised = fx.read_deal(api, deal_id)
    asserts.assert_money(poised["posted_credit_support_usd"],
                         POSTED_TOTAL - CASH_TWO_FACE,
                         "posted_credit_support_usd")

    # Releasing 1,800,000.00 more would leave 1,500,000.00 against 2,500,000.00.
    refused = api.release_credit_support(chain["letter"]["id"], CREDIT_OFFICER)
    validate_error(refused, ApiErrorId.ERR_RELEASE_BREACHES_COVERAGE.value, 422)
    asserts.assert_error_envelope(refused)

    letter = asserts.row_by_id(_stack_of(api, deal_id), chain["letter"]["id"])
    assert letter["status"] == "POSTED", letter
    assert letter["closed_at"] is None, letter
    asserts.assert_money(letter["eligible_credit_usd"], LC_ELIGIBLE,
                         "eligible_credit_usd")
    assert letter["version"] == chain["letter"]["version"], letter

    after = fx.read_deal(api, deal_id)
    asserts.assert_money(after["posted_credit_support_usd"],
                         POSTED_TOTAL - CASH_TWO_FACE,
                         "posted_credit_support_usd")
    asserts.assert_money(after["released_credit_support_usd"], CASH_TWO_FACE,
                         "released_credit_support_usd")
    asserts.assert_money(after["drawn_credit_support_usd"], 0.00,
                         "drawn_credit_support_usd")
    _assert_buckets_conserve(after, POSTED_TOTAL, "after the refusal")
    assert after["version"] == poised["version"], after

    # Neither dimension of the deal moved.
    assert after["credit_status"] == "APPROVED", after
    assert after["status"] == "TERMS_AGREED", after


# ---------------------------------------------------------------------------
# Instance: whole megawatt-hours of environmental attributes, held in three
# NESTED buckets and compensated by transfer / cancel-transfer.
# ---------------------------------------------------------------------------

ATTRIBUTE_PERIOD = ("2027-07-01T00:00:00Z", "2027-08-01T00:00:00Z")

#: Three uncurtailed hours summing to 20.4500 MWh, so the mintable floor is 20.
ATTRIBUTE_HOURS = [
    {"hour_start": "2027-07-01T00:00:00Z", "metered_mwh": 7.0000,
     "node_price_usd_per_mwh": 30.00, "hub_price_usd_per_mwh": 30.00},
    {"hour_start": "2027-07-01T01:00:00Z", "metered_mwh": 7.0000,
     "node_price_usd_per_mwh": 30.00, "hub_price_usd_per_mwh": 30.00},
    {"hour_start": "2027-07-01T02:00:00Z", "metered_mwh": 6.4500,
     "node_price_usd_per_mwh": 30.00, "hub_price_usd_per_mwh": 30.00},
]

TOTAL_METERED_MWH = 20.4500
MINTABLE_MWH = 20
FIRST_BATCH_MWH = 12
SECOND_BATCH_MWH = 8
VINTAGE_MONTH = "2027-07"
FIRST_SERIAL_RANGE = "WREGIS-2027-07-000001-000012"
SECOND_SERIAL_RANGE = "WREGIS-2027-07-000101-000112"


def _period_minted_to_its_ceiling(api):
    """A calculated July period whose two batches draw the whole 20 MWh ceiling."""
    chain = fx.calculated_period_chain(
        api, hours=ATTRIBUTE_HOURS, period_start=ATTRIBUTE_PERIOD[0],
        period_end=ATTRIBUTE_PERIOD[1],
        project_overrides={"name": "Kramer Junction Solar II",
                           "cod_target_date": "2026-07-01T00:00:00Z"})
    period_id = chain["period"]["id"]
    chain["batch_one"] = fx.mint_batch(api, period_id, FIRST_BATCH_MWH)
    chain["batch_two"] = fx.mint_batch(api, period_id, SECOND_BATCH_MWH)
    return chain


def _batches_of(api, deal_id, params=None):
    rows, _ = fx.list_all(
        api.list_deal_attribute_batches(deal_id, REGISTRY_AGENT, params))
    return rows


def test_07_two_batches_exhaust_the_ceiling_and_no_further_mwh_can_be_conjured(api):
    """Twelve plus eight is the whole floor of 20.4500 metered megawatt-hours, so
    a further single certificate is refused.

    "The requested `quantity_mwh` may not exceed the period's
    `mintable_attributes_mwh` less whatever earlier batches have already minted
    from that same period, or the request is refused with
    `ERR_ATTRIBUTE_QUANTITY_EXCEEDS_MINTABLE`; because deemed generation is
    excluded from the mintable count, a period whose delivered volume was largely
    deemed mints far fewer certificates than its settlement dollars would
    suggest."

    Design: Difficulty/compensating_invariant/attribute_mwh_conserved_across_transfer_and_cancel_transfer
    """
    chain = _period_minted_to_its_ceiling(api)
    deal_id = chain["deal"]["id"]
    period_id = chain["period"]["id"]

    period = fx.read_period(api, period_id)
    asserts.assert_mwh(period["total_metered_mwh"], TOTAL_METERED_MWH,
                       "total_metered_mwh")
    asserts.assert_mwh(period["total_deemed_mwh"], 0.0000, "total_deemed_mwh")
    assert period["mintable_attributes_mwh"] == MINTABLE_MWH, period

    first = chain["batch_one"]
    assert first["status"] == "MINTED", first
    assert first["vintage_month"] == VINTAGE_MONTH, first
    assert first["claim_substantiation_status"] == "UNSUBSTANTIATED", first
    assert first["allocation_breakdown"] == [], first
    assert first["quantity_mwh"] == FIRST_BATCH_MWH, first
    asserts.assert_all_null(first, ["registry_serial_range",
                                    "transferred_to_offtaker_id", "claim_year",
                                    "transferred_at", "retired_at"])

    before = fx.read_deal(api, deal_id)
    assert before["attributes_minted_mwh"] == MINTABLE_MWH, before
    assert before["attributes_transferred_mwh"] == 0, before
    assert before["attributes_retired_mwh"] == 0, before

    # Not one more megawatt-hour: the remaining headroom is exactly zero.
    refused = api.mint_attributes(period_id, f.mint_attributes_payload(1),
                                  REGISTRY_AGENT)
    validate_error(refused,
                   ApiErrorId.ERR_ATTRIBUTE_QUANTITY_EXCEEDS_MINTABLE.value, 422)
    asserts.assert_error_envelope(refused)

    after = fx.read_deal(api, deal_id)
    assert after["attributes_minted_mwh"] == MINTABLE_MWH, after
    assert after["version"] == before["version"], after
    assert len(_batches_of(api, deal_id)) == 2, _batches_of(api, deal_id)


def test_08_cancelling_a_transfer_restores_the_bucket_it_filled(api):
    """Transfer, cancel, re-transfer and retire shuffle one batch through three
    nested buckets while the minted total stays at twenty throughout.

    "The deal's `attributes_transferred_mwh` decreases by `quantity_mwh`,
    returning to its pre-transfer value, while `attributes_minted_mwh` is left
    untouched — the pair must conserve attribute megawatt-hours across the
    minted, transferred and retired buckets."

    Design: Difficulty/compensating_invariant/attribute_mwh_conserved_across_transfer_and_cancel_transfer
    """
    chain = _period_minted_to_its_ceiling(api)
    deal_id = chain["deal"]["id"]
    buyer_id = chain["buyer"]["id"]
    batch_id = chain["batch_one"]["id"]

    transferred = fx.transfer_batch(api, batch_id, buyer_id,
                                    registry_serial_range=FIRST_SERIAL_RANGE)
    assert transferred["status"] == "TRANSFERRED", transferred
    assert transferred["transferred_to_offtaker_id"] == buyer_id, transferred
    assert transferred["registry_serial_range"] == FIRST_SERIAL_RANGE, transferred
    asserts.assert_instant_equals(transferred["transferred_at"],
                                  fx.INITIAL_CLOCK, "transferred_at")
    asserts.assert_breakdown_rows(transferred["allocation_breakdown"],
                                  [(buyer_id, FIRST_BATCH_MWH)])

    conveyed = fx.read_deal(api, deal_id)
    assert conveyed["attributes_minted_mwh"] == MINTABLE_MWH, conveyed
    assert conveyed["attributes_transferred_mwh"] == FIRST_BATCH_MWH, conveyed
    assert conveyed["attributes_retired_mwh"] == 0, conveyed

    cancelled = fx.cancel_batch_transfer(api, batch_id)
    assert cancelled["status"] == "MINTED", cancelled
    asserts.assert_all_null(cancelled, ["transferred_to_offtaker_id",
                                        "registry_serial_range",
                                        "transferred_at"])
    assert cancelled["allocation_breakdown"] == [], cancelled

    restored = fx.read_deal(api, deal_id)
    assert restored["attributes_transferred_mwh"] == 0, restored
    assert restored["attributes_minted_mwh"] == MINTABLE_MWH, restored

    # A re-transfer may carry a different serial range from the registry.
    again = fx.transfer_batch(api, batch_id, buyer_id,
                              registry_serial_range=SECOND_SERIAL_RANGE)
    assert again["registry_serial_range"] == SECOND_SERIAL_RANGE, again
    reconveyed = fx.read_deal(api, deal_id)
    assert reconveyed["attributes_transferred_mwh"] == FIRST_BATCH_MWH

    retired = fx.retire_batch(api, batch_id, 2027)
    assert retired["status"] == "RETIRED", retired
    assert retired["claim_year"] == 2027, retired
    assert retired["claim_substantiation_status"] == "SUBSTANTIATED", retired
    asserts.assert_instant_equals(retired["retired_at"], fx.INITIAL_CLOCK,
                                  "retired_at")

    # The buckets are nested: a retired batch still counts as transferred and as
    # minted, so the twenty never changed.
    final = fx.read_deal(api, deal_id)
    assert final["attributes_minted_mwh"] == MINTABLE_MWH, final
    assert final["attributes_transferred_mwh"] == FIRST_BATCH_MWH, final
    assert final["attributes_retired_mwh"] == FIRST_BATCH_MWH, final

    buyer = fx.read_offtaker(api, buyer_id)
    assert buyer["claimed_attributes_mwh"] == FIRST_BATCH_MWH, buyer

    untouched = asserts.row_by_id(_batches_of(api, deal_id),
                                  chain["batch_two"]["id"])
    assert untouched["status"] == "MINTED", untouched
    assert untouched["claim_substantiation_status"] == "UNSUBSTANTIATED"
