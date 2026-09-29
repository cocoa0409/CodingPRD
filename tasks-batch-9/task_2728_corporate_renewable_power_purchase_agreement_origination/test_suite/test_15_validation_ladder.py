"""The validation ladder: one request, several broken rules, exactly one answer.

Most of these tests fire a request that violates two or three rules at once and
pin the single error the priority order says must come back; the last one walks
the two fiscal rungs of the execute gate in order.  The recurring shape is that
clearing the reported violation exposes the next one, so the very same request
answers differently each time without any earlier fact changing.
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
from test_helpers.constants import UNKNOWN_UUIDS  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    CREDIT_OFFICER,
    DEAL_COMMITTEE,
    ORIGINATOR,
    make_offtaker_rep_headers,
)

# ---------------------------------------------------------------------------
# Three buyers, each landing in a different qualification outcome.
# ---------------------------------------------------------------------------

#: BBB / 3.0 turns / TCFD_ONLY with a science-based target but no RE100 and no
#: near-term year: 72.60 credit, 50.00 sustainability, so CONDITIONAL is the
#: best decision available to it.
MIDMARKET = {
    "legal_name": "Midmarket Bottling Co",
    "credit_rating": "BBB",
    "rating_agency": "SP",
    "reported_ebitda_usd": 40000000.00,
    "net_debt_to_ebitda": 3.0,
    "disclosure_framework": "TCFD_ONLY",
    "has_science_based_target": True,
    "re100_member": False,
}
MIDMARKET_SCORE = 72.60
MIDMARKET_SUSTAINABILITY = 50.00
#: min(10,000,000.00 STANDARD cap, 40,000,000.00 * 2%).
MIDMARKET_THRESHOLD_USD = 800000.00
#: ceil((1,395,030.00 - 800,000.00) / 250,000.00) = ceil(2.38012) = 3.
MIDMARKET_REQUIREMENT_USD = 750000.00

CONDITION_TEXT = "parent guarantee delivered before notice to proceed"

#: B / 6.0 turns / NONE: 0.55 * 38 + 0.30 * 40 + 0.15 * 30 = 37.40, DECLINED.
DISTRESSED = {
    "legal_name": "Distressed Retail Group",
    "credit_rating": "B",
    "rating_agency": "SP",
    "reported_ebitda_usd": 30000000.00,
    "net_debt_to_ebitda": 6.0,
    "disclosure_framework": "NONE",
}
DISTRESSED_SCORE = 37.40

#: The same BBB / 3.0 balance sheet as Midmarket, but full disclosure and a
#: 2030 target lift it to 75.60 credit and exactly 70.00 sustainability — the
#: QUALIFY gate, met on the nose.
CASCADIA = {
    "legal_name": "Cascadia Foods Co",
    "credit_rating": "BBB",
    "rating_agency": "SP",
    "reported_ebitda_usd": 40000000.00,
    "net_debt_to_ebitda": 3.0,
    "disclosure_framework": "CDP_AND_TCFD",
    "has_science_based_target": True,
    "re100_member": False,
    "scope2_target_year": 2030,
    "registry_account_id": "WREGIS-ACC-00812",
}
CASCADIA_SCORE = 75.60
CASCADIA_SUSTAINABILITY = 70.00

CONTRACTED_MW = 25.000
CONTRACT_PRICE = 22.75
EXPECTED_ANNUAL_MWH = 61320.00
#: 61,320.00 * 22.75.
EXPOSURE_USD = 1395030.00
PROJECT_CAPACITY_MW = 100.000


def test_01_an_unknown_deal_beats_the_state_gate_which_beats_qualification(api):
    """One execute request breaks three rules at once and answers only with the
    highest: a 404 for an identifier that does not resolve, and on a real deal a
    409 from the state gate rather than the 422 the buyer's standing also earns.

    "Path existence: every identifier appearing in the request path must resolve
    to a live row, and the identifiers are resolved strictly left to right — the
    outer segment first."

    "Because the state gate sits at priority 8, executing a `DRAFT` deal whose
    anchor buyer is also still `UNDER_REVIEW` returns `ERR_INVALID_STATE_TRANSITION`
    (409), not `ERR_OFFTAKER_NOT_QUALIFIED` (422)."

    "The same action is also the revision loop: a buyer sitting at `CONDITIONAL`
    after a conditional decision re-submits along `CONDITIONAL → UNDER_REVIEW`
    once it has remediated its conditions, and on that path the `conditions`
    array is cleared to empty **before** the scores are recomputed."

    Design: Corner/validations/deal_not_found_precedes_state_gate_which_precedes_offtaker_qualification
    """
    buyer = fx.create_conditional_offtaker(api, conditions=[CONDITION_TEXT],
                                           anchor=False, **MIDMARKET)
    assert buyer["qualification_status"] == "CONDITIONAL", buyer
    assert buyer["conditions"] == [CONDITION_TEXT], buyer
    asserts.assert_score(buyer["credit_score"], MIDMARKET_SCORE, "credit_score")
    assert buyer["credit_tier"] == "STANDARD", buyer

    node = fx.create_node(api)
    project = fx.create_project(api, node["id"],
                                cod_target_date="2029-06-01T00:00:00Z")
    deal = fx.create_deal(api, project["id"], buyer["id"], node["id"],
                          product_type="VIRTUAL_CFD", term_years=12)

    # The revision loop puts the buyer back under review and empties the
    # remediation list, so the deal now has an unqualified anchor.
    reviewed = fx.submit_offtaker(api, buyer["id"])
    assert reviewed["qualification_status"] == "UNDER_REVIEW", reviewed
    assert reviewed["conditions"] == [], reviewed
    asserts.assert_score(reviewed["credit_score"], MIDMARKET_SCORE,
                         "credit_score")

    # An identifier that resolves to nothing is answered at priority 4, even
    # though this request has no signable deal and no qualified buyer either.
    missing = api.execute_deal(UNKNOWN_UUIDS["spare"], DEAL_COMMITTEE)
    validate_error(missing, ApiErrorId.ERR_DEAL_NOT_FOUND.value, 404)
    asserts.assert_error_envelope(missing)

    before = fx.read_deal(api, deal["id"])
    assert before["status"] == "DRAFT", before
    assert before["credit_status"] == "NOT_SUBMITTED", before

    refused = api.execute_deal(deal["id"], DEAL_COMMITTEE)
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)
    body = asserts.assert_error_envelope(refused)
    assert body["error_id"] not in (
        ApiErrorId.ERR_OFFTAKER_NOT_QUALIFIED.value,
        ApiErrorId.ERR_ALLOCATION_INCOMPLETE.value), (
        "both of those are equally true of this request, and both sit below the "
        "state gate")

    after = fx.read_deal(api, deal["id"])
    assert after["status"] == "DRAFT", after
    assert after["version"] == before["version"], after
    assert after["effective_at"] is None, after
    buyer_after = fx.read_offtaker(api, buyer["id"])
    assert buyer_after["version"] == reviewed["version"], buyer_after


# ---------------------------------------------------------------------------
# Allocation uniqueness is scoped by status, not by the pair of identifiers.
# ---------------------------------------------------------------------------

FIRST_SLICE_MW = 15.000
BLOCKED_SLICE_MW = 5.000
SECOND_SLICE_MW = 20.000
SECOND_SHARE_PCT = 80.0000


def test_02_a_withdrawn_slice_stops_blocking_but_survives_as_history(api):
    """The same buyer is refused a second live slice, then granted one the moment
    the first is withdrawn — and the withdrawn row is still listed afterwards.

    "If that buyer already holds a slice on this deal whose `status` is
    `PROPOSED` or `CONFIRMED`, the proposal is refused with
    `ERR_DUPLICATE_ALLOCATION`; a `WITHDRAWN` slice does not block a fresh
    proposal."

    "`WITHDRAW` is the exact compensating action, and it is legal from either
    live state."

    "Its `allocation_share_pct` is one hundred multiplied by `allocated_mw`
    divided by the deal's `contracted_mw`, rounded half up to four decimal
    places."

    Design: Corner/validations/duplicate_allocation_blocks_a_live_share_but_not_a_withdrawn_one
    """
    chain = fx.chain_a(api, deal_overrides={"product_type": "AGGREGATED",
                                            "term_years": 12})
    deal_id = chain["deal"]["id"]
    buyer_id = chain["buyer"]["id"]
    fx.table_round(api, deal_id)

    first = fx.propose_allocation(api, deal_id, buyer_id, FIRST_SLICE_MW)
    assert first["status"] == "PROPOSED", first
    blocked_token = fx.deal_version(api, deal_id)

    duplicate = api.create_allocation(
        deal_id,
        f.allocation_payload(buyer_id, BLOCKED_SLICE_MW, blocked_token),
        ORIGINATOR)
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_ALLOCATION.value, 409)
    asserts.assert_error_envelope(duplicate)
    assert fx.deal_version(api, deal_id) == blocked_token, (
        "a refused proposal moves no version")

    withdrawn = fx.withdraw_allocation(api, first["id"], buyer_id)
    assert withdrawn["status"] == "WITHDRAWN", withdrawn
    assert withdrawn["confirmed_at"] is None, withdrawn

    second = fx.propose_allocation(api, deal_id, buyer_id, SECOND_SLICE_MW)
    assert second["status"] == "PROPOSED", second
    asserts.assert_mw(second["allocated_mw"], SECOND_SLICE_MW, "allocated_mw")
    asserts.assert_share_pct(second["allocation_share_pct"], SECOND_SHARE_PCT)

    # The withdrawn row is history, not a deletion.
    rows, meta = fx.list_all(api.list_allocations(deal_id, ORIGINATOR))
    assert meta["total_count"] == 2, meta
    assert sorted(asserts.ids_of(rows)) == sorted([first["id"], second["id"]]), \
        rows
    history = asserts.row_by_id(rows, first["id"])
    assert history["status"] == "WITHDRAWN", history
    asserts.assert_mw(history["allocated_mw"], FIRST_SLICE_MW, "allocated_mw")

    # Nothing was ever confirmed, so the deal's confirmed ledger never moved.
    deal = fx.read_deal(api, deal_id)
    asserts.assert_mw(deal["confirmed_allocated_mw"], 0.000,
                      "confirmed_allocated_mw")
    asserts.assert_mw(deal["unallocated_mw"], CONTRACTED_MW - SECOND_SLICE_MW,
                      "unallocated_mw")


# ---------------------------------------------------------------------------
# Structuring admits {QUALIFIED, CONDITIONAL} and nothing else.
# ---------------------------------------------------------------------------


def test_03_the_identical_deal_payload_turns_on_the_anchor_buyers_standing(api):
    """A rejected buyer cannot be structured at all while a conditional one can,
    on byte-identical commercial terms — and the refusal reserves no capacity.

    "The anchor buyer's `qualification_status` must be `QUALIFIED` or
    `CONDITIONAL`, or the request is refused with `ERR_OFFTAKER_NOT_QUALIFIED`."

    "`REJECT` moves the buyer `UNDER_REVIEW → REJECTED`, which is terminal,
    stamps `decision_by_user_id`, and cascades: every deal anchored by this buyer
    whose `status` is `DRAFT`, `TERM_SHEET_ISSUED` or `UNDER_NEGOTIATION` has its
    `credit_status` set to `DECLINED` and its `version` incremented by one."

    "Creation also prices the deal, projects its volume, snapshots the buyer's
    unsecured limit into `unsecured_credit_limit_usd` and
    `collateral_threshold_usd`, and sizes `exposure_usd` and
    `credit_support_required_usd`."

    Design: Corner/validations/deal_create_refuses_a_rejected_buyer_and_admits_a_conditional_one
    """
    node = fx.create_node(api)
    rejected = fx.create_rejected_offtaker(api, **DISTRESSED)
    asserts.assert_score(rejected["credit_score"], DISTRESSED_SCORE,
                         "credit_score")
    assert rejected["credit_tier"] == "DECLINED", rejected
    assert rejected["qualification_status"] == "REJECTED", rejected

    conditional = fx.create_conditional_offtaker(api, conditions=[CONDITION_TEXT],
                                                 anchor=False, **MIDMARKET)
    assert conditional["qualification_status"] == "CONDITIONAL", conditional
    assert conditional["conditions"] == [CONDITION_TEXT], conditional
    asserts.assert_score(conditional["sustainability_score"],
                         MIDMARKET_SUSTAINABILITY, "sustainability_score")

    project = fx.create_project(api, node["id"],
                                cod_target_date="2029-06-01T00:00:00Z")

    def structure_for(anchor_id):
        """The same 25.000 MW VIRTUAL_CFD, anchored by a different buyer."""
        return f.deal_payload(project["id"], anchor_id, node["id"],
                              product_type="VIRTUAL_CFD",
                              contracted_mw=CONTRACTED_MW, term_years=12)

    refused = api.create_deal(structure_for(rejected["id"]), ORIGINATOR)
    validate_error(refused, ApiErrorId.ERR_OFFTAKER_NOT_QUALIFIED.value, 422)
    asserts.assert_error_envelope(refused)

    _, meta = fx.list_all(api.list_deals(
        ORIGINATOR, params={"anchor_offtaker_id": rejected["id"]}))
    assert meta["total_count"] == 0, meta

    # A refused creation reserves nothing on the parent project.
    ledger = fx.read_project(api, project["id"])
    asserts.assert_mw(ledger["contracted_mw"], 0.000, "contracted_mw")
    asserts.assert_mw(ledger["available_mw"], PROJECT_CAPACITY_MW,
                      "available_mw")

    admitted = get_success_data(
        api.create_deal(structure_for(conditional["id"]), ORIGINATOR), 201)
    assert admitted["status"] == "DRAFT", admitted
    assert admitted["credit_status"] == "NOT_SUBMITTED", admitted
    asserts.assert_money(admitted["contract_price_usd_per_mwh"], CONTRACT_PRICE,
                         "contract_price_usd_per_mwh")
    asserts.assert_mwh(admitted["expected_annual_mwh"], EXPECTED_ANNUAL_MWH,
                       "expected_annual_mwh", places=2)
    asserts.assert_money(admitted["exposure_usd"], EXPOSURE_USD, "exposure_usd")
    asserts.assert_money(admitted["collateral_threshold_usd"],
                         MIDMARKET_THRESHOLD_USD, "collateral_threshold_usd")
    asserts.assert_money(admitted["credit_support_required_usd"],
                         MIDMARKET_REQUIREMENT_USD, "credit_support_required_usd")
    asserts.assert_whole_increment(admitted["credit_support_required_usd"])

    # "`contracted_mw` is always the sum of `contracted_mw` over the project's
    # deals whose `status` is `EXECUTED` or `EFFECTIVE`" — the admitted deal is
    # still `DRAFT`, so the recomputed ledger books nothing for it either.
    reserved = fx.read_project(api, project["id"])
    asserts.assert_mw(reserved["contracted_mw"], 0.000, "contracted_mw")
    asserts.assert_mw(reserved["available_mw"], PROJECT_CAPACITY_MW,
                      "available_mw")


# ---------------------------------------------------------------------------
# Lateness is decided at answer time, and the comparison is inclusive.
# ---------------------------------------------------------------------------

ROUND_DEADLINE = "2026-08-15T00:00:00Z"
FIVE_DAYS_LATE = "2026-08-20T00:00:00Z"


def test_04_a_lapsed_round_is_refused_as_expired_not_as_a_bad_transition(api):
    """Answering exactly at the deadline second is legal, five days later is
    `ERR_ROUND_EXPIRED`, and the lapsed round is still stored `OPEN` when it is
    refused — nothing swept it on the way past.

    "The round must be `OPEN` and the logical clock must be at or before its
    `response_deadline`; answering a lapsed round is refused with
    `ERR_ROUND_EXPIRED`, and a lapsed round must be expired and re-issued rather
    than answered late."

    "An `ACCEPT` moves the round `OPEN → ACCEPTED` with `responded_at` set to the
    logical clock and `responded_by_user_id` set to the answering buyer, and
    drives the deal `TERM_SHEET_ISSUED → TERMS_AGREED`."

    Design: Corner/validations/round_answered_after_its_deadline_is_expired_not_accepted
    """
    chain = fx.chain_a(api)
    buyer_id = chain["buyer"]["id"]
    lapsing_deal = chain["deal"]["id"]
    lapsing = fx.table_round(api, lapsing_deal,
                             response_deadline=ROUND_DEADLINE)

    # A second agreement on the same project, whose round is answered on the
    # deadline itself rather than after it.
    on_time_deal = fx.create_deal(api, chain["project"]["id"], buyer_id,
                                  chain["node"]["id"])["id"]
    on_time = fx.table_round(api, on_time_deal,
                             response_deadline=ROUND_DEADLINE)

    fx.set_clock(api, ROUND_DEADLINE)
    accepted = fx.respond_accept(api, on_time["id"], buyer_id)
    assert accepted["status"] == "ACCEPTED", accepted
    asserts.assert_instant_equals(accepted["responded_at"], ROUND_DEADLINE,
                                  "responded_at")
    assert fx.read_deal(api, on_time_deal)["status"] == "TERMS_AGREED", (
        "at or before the deadline is inclusive, so this answer lands")

    fx.set_clock(api, FIVE_DAYS_LATE)
    rounds, _ = fx.list_all(api.list_rounds(lapsing_deal, ORIGINATOR))
    stale = asserts.row_by_id(rounds, lapsing["id"])
    assert stale["status"] == "OPEN", stale
    asserts.assert_instant_equals(stale["response_deadline"], ROUND_DEADLINE,
                                  "response_deadline")

    late = api.respond_to_round(lapsing["id"],
                                f.round_response_payload("ACCEPT"),
                                make_offtaker_rep_headers(buyer_id))
    validate_error(late, ApiErrorId.ERR_ROUND_EXPIRED.value, 409)
    body = asserts.assert_error_envelope(late)
    assert body["error_id"] != ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, (
        "the round is genuinely still OPEN, so this is not a state-gate failure")

    # The refusal changed nothing at all: not the round, not the deal.
    rounds, _ = fx.list_all(api.list_rounds(lapsing_deal, ORIGINATOR))
    unmoved = asserts.row_by_id(rounds, lapsing["id"])
    assert unmoved["status"] == "OPEN", unmoved
    assert unmoved["responded_at"] is None, unmoved
    assert unmoved["responded_by_user_id"] is None, unmoved
    assert unmoved["version"] == stale["version"], unmoved

    deal = fx.read_deal(api, lapsing_deal)
    assert deal["status"] == "TERM_SHEET_ISSUED", deal
    assert deal["round_count"] == 1, deal


# ---------------------------------------------------------------------------
# The tenor rule is conditioned on instrument_type, and its boundary is walked
# from both sides.
# ---------------------------------------------------------------------------

CASH_FACE_USD = 100000.00
SHORT_LETTER_FACE_USD = 100000.00
LONG_LETTER_FACE_USD = 200000.00

#: Thirty days of tenor from the logical clock.
SHORT_EXPIRY = "2026-08-31T00:00:00Z"
#: Exactly MIN_TENOR_DAYS whole days from the logical clock.
BOUNDARY_EXPIRY = "2027-08-01T00:00:00Z"
#: 364 whole days: one day short of the boundary.
ONE_DAY_SHORT_EXPIRY = "2027-07-31T00:00:00Z"

PRIME_ISSUER = {"issuer_name": "First Prime Bank", "issuer_rating": "AAA"}
POSTED_TOTAL_USD = 300000.00


def test_05_the_tenor_rule_binds_paper_and_exempts_cash_outright(api):
    """The identical thirty-day window is fine for cash and fatal for a letter,
    365 whole days passes and 364 does not — and none of the three refusals is
    about the issuer, whose `AAA` rating always had a haircut row.

    "Tenor is tested only after eligibility: a letter of credit or a parent
    guarantee must have at least 365 whole days from the logical clock to its
    `expiry_date`, or the post is refused with `ERR_INSTRUMENT_TENOR_TOO_SHORT`;
    cash collateral is exempt from the tenor rule entirely."

    "A `LETTER_OF_CREDIT` requires an `issuer_name` and an `issuer_rating` among
    `AAA`, `AA`, `A`, `BBB` and `BB`; an unrated issuer or one rated `B`, `CCC` or
    `NR` has no haircut row and is refused with `ERR_INELIGIBLE_ISSUER`."

    "A successful post moves the instrument `PROPOSED → POSTED`, stamps
    `posted_at` with the logical clock, and recomputes the deal's
    `posted_credit_support_usd` as the sum of `eligible_credit_usd` over that
    deal's `POSTED` instruments."

    Design: Corner/validations/instrument_tenor_rule_binds_letters_and_guarantees_but_exempts_cash
    """
    # Posting requires the credit dimension to be open, so the deal is carried
    # to APPROVED; its requirement is 0.00, which keeps coverage out of the way.
    chain = fx.negotiated_chain(api)
    deal_id = chain["deal"]["id"]
    assert chain["deal"]["credit_status"] == "APPROVED", chain["deal"]
    asserts.assert_money(chain["deal"]["credit_support_required_usd"], 0.00,
                         "credit_support_required_usd")

    cash = fx.register_cash(api, deal_id, CASH_FACE_USD,
                            expiry_date=SHORT_EXPIRY)
    short_letter = fx.register_letter_of_credit(
        api, deal_id, SHORT_LETTER_FACE_USD, expiry_date=SHORT_EXPIRY,
        **PRIME_ISSUER)
    boundary_letter = fx.register_letter_of_credit(
        api, deal_id, LONG_LETTER_FACE_USD, expiry_date=BOUNDARY_EXPIRY,
        **PRIME_ISSUER)
    one_day_short = fx.register_letter_of_credit(
        api, deal_id, LONG_LETTER_FACE_USD, expiry_date=ONE_DAY_SHORT_EXPIRY,
        **PRIME_ISSUER)

    # Cash in hand needs no remaining tenor.
    posted_cash = fx.post_instrument(api, deal_id, cash["id"])
    assert posted_cash["status"] == "POSTED", posted_cash
    asserts.assert_money(posted_cash["haircut_pct"], 0.00, "haircut_pct")
    asserts.assert_money(posted_cash["eligible_credit_usd"], CASH_FACE_USD,
                         "eligible_credit_usd")
    asserts.assert_instant_equals(posted_cash["posted_at"], fx.INITIAL_CLOCK,
                                  "posted_at")

    token = fx.deal_version(api, deal_id)
    refused = api.post_credit_support(
        short_letter["id"], f.post_credit_support_payload(token),
        CREDIT_OFFICER)
    validate_error(refused,
                   ApiErrorId.ERR_INSTRUMENT_TENOR_TOO_SHORT.value, 422)
    body = asserts.assert_error_envelope(refused)
    assert body["error_id"] != ApiErrorId.ERR_INELIGIBLE_ISSUER.value, (
        "an AAA issuer has a haircut row, so eligibility was satisfied and the "
        "tenor limb is unambiguously the failing one")

    stack, _ = fx.list_all(api.list_credit_support(deal_id, CREDIT_OFFICER))
    untouched = asserts.row_by_id(stack, short_letter["id"])
    assert untouched["status"] == "PROPOSED", untouched
    asserts.assert_all_null(untouched, ["eligible_credit_usd", "haircut_pct",
                                        "posted_at", "closed_at"])
    assert fx.deal_version(api, deal_id) == token, (
        "a refused post leaves the deal's concurrency token where it was")

    boundary = fx.post_instrument(api, deal_id, boundary_letter["id"])
    assert boundary["status"] == "POSTED", boundary
    asserts.assert_money(boundary["haircut_pct"], 0.00, "haircut_pct")
    asserts.assert_money(boundary["eligible_credit_usd"], LONG_LETTER_FACE_USD,
                         "eligible_credit_usd")

    token = fx.deal_version(api, deal_id)
    just_short = api.post_credit_support(
        one_day_short["id"], f.post_credit_support_payload(token),
        CREDIT_OFFICER)
    validate_error(just_short,
                   ApiErrorId.ERR_INSTRUMENT_TENOR_TOO_SHORT.value, 422)

    deal = fx.read_deal(api, deal_id)
    asserts.assert_money(deal["posted_credit_support_usd"], POSTED_TOTAL_USD,
                         "posted_credit_support_usd")
    asserts.assert_money(deal["credit_support_required_usd"], 0.00,
                         "credit_support_required_usd")
    assert deal["credit_status"] == "APPROVED", deal


# ---------------------------------------------------------------------------
# The aggregate is only tested at CONFIRM, and only over CONFIRMED rows.
# ---------------------------------------------------------------------------

AGGREGATE_SLICE_MW = 15.000
FIRST_AGGREGATE_SHARE_PCT = 60.0000
REPLACEMENT_SLICE_MW = 10.000
REPLACEMENT_SHARE_PCT = 40.0000


def test_06_two_valid_shares_are_collectively_too_large_only_at_confirm(api):
    """Two 15.000 MW proposals sit side by side without complaint against a
    25.000 MW deal; the second confirmation is refused by arithmetic over a row
    its buyer does not own, and a 10.000 MW replacement lands exactly on the total.

    "It also carries an aggregate check that no individual proposal could catch:
    if confirming would push the sum of `allocated_mw` over the deal's `CONFIRMED`
    slices above `contracted_mw`, the request is refused with
    `ERR_ALLOCATION_EXCEEDS_CONTRACTED_MW`."

    "Equality is allowed, and confirming exactly to the contracted total drives
    `unallocated_mw` to 0.000."

    "`confirmed_allocated_mw` is always the sum of `allocated_mw` over the deal's
    `CONFIRMED` slices."

    Design: Corner/validations/two_individually_valid_shares_are_collectively_over_contracted_mw
    """
    chain = fx.chain_a(api, deal_overrides={"product_type": "AGGREGATED",
                                            "contracted_mw": CONTRACTED_MW,
                                            "term_years": 12,
                                            "settlement_frequency": "MONTHLY"})
    deal_id = chain["deal"]["id"]
    buyer_a = chain["buyer"]["id"]
    second = fx.create_qualified_offtaker(api, anchor=False, **CASCADIA)
    asserts.assert_score(second["credit_score"], CASCADIA_SCORE, "credit_score")
    asserts.assert_score(second["sustainability_score"],
                         CASCADIA_SUSTAINABILITY, "sustainability_score")
    assert second["credit_tier"] == "STANDARD", second
    buyer_b = second["id"]
    fx.table_round(api, deal_id)

    # 15.000 + 15.000 = 30.000 against 25.000 contracted, and both are accepted.
    slice_a = fx.propose_allocation(api, deal_id, buyer_a, AGGREGATE_SLICE_MW,
                                    joint_and_several=True)
    slice_b = fx.propose_allocation(api, deal_id, buyer_b, AGGREGATE_SLICE_MW,
                                    joint_and_several=True)
    assert slice_a["status"] == "PROPOSED", slice_a
    assert slice_b["status"] == "PROPOSED", slice_b
    asserts.assert_mw(fx.read_deal(api, deal_id)["confirmed_allocated_mw"],
                      0.000, "confirmed_allocated_mw")

    confirmed_a = fx.confirm_allocation(api, slice_a["id"], buyer_a)
    assert confirmed_a["status"] == "CONFIRMED", confirmed_a
    asserts.assert_share_pct(confirmed_a["allocation_share_pct"],
                             FIRST_AGGREGATE_SHARE_PCT)
    midway = fx.read_deal(api, deal_id)
    asserts.assert_mw(midway["confirmed_allocated_mw"], AGGREGATE_SLICE_MW,
                      "confirmed_allocated_mw")

    over = api.decide_allocation(slice_b["id"],
                                 f.allocation_decision_payload("CONFIRM"),
                                 make_offtaker_rep_headers(buyer_b))
    validate_error(over,
                   ApiErrorId.ERR_ALLOCATION_EXCEEDS_CONTRACTED_MW.value, 422)
    asserts.assert_error_envelope(over)

    rows, _ = fx.list_all(api.list_allocations(deal_id, ORIGINATOR))
    still_proposed = asserts.row_by_id(rows, slice_b["id"])
    assert still_proposed["status"] == "PROPOSED", still_proposed
    assert still_proposed["confirmed_at"] is None, still_proposed
    after_refusal = fx.read_deal(api, deal_id)
    asserts.assert_mw(after_refusal["confirmed_allocated_mw"],
                      AGGREGATE_SLICE_MW, "confirmed_allocated_mw")
    assert after_refusal["version"] == midway["version"], after_refusal

    withdrawn = fx.withdraw_allocation(api, slice_b["id"], buyer_b)
    assert withdrawn["status"] == "WITHDRAWN", withdrawn

    replacement = fx.propose_allocation(api, deal_id, buyer_b,
                                        REPLACEMENT_SLICE_MW,
                                        joint_and_several=True)
    asserts.assert_share_pct(replacement["allocation_share_pct"],
                             REPLACEMENT_SHARE_PCT)
    confirmed_b = fx.confirm_allocation(api, replacement["id"], buyer_b)
    assert confirmed_b["status"] == "CONFIRMED", confirmed_b

    # 15.000 + 10.000 == 25.000 exactly, and equality is allowed.
    full = fx.read_deal(api, deal_id)
    asserts.assert_mw(full["confirmed_allocated_mw"], CONTRACTED_MW,
                      "confirmed_allocated_mw")
    asserts.assert_mw(full["unallocated_mw"], 0.000, "unallocated_mw")

    rows, meta = fx.list_all(api.list_allocations(deal_id, ORIGINATOR))
    assert meta["total_count"] == 3, meta
    assert sorted(row["status"] for row in rows) == \
        ["CONFIRMED", "CONFIRMED", "WITHDRAWN"], rows


# ---------------------------------------------------------------------------
# The two fiscal rungs of the execute gate, cleared in priority order.
# ---------------------------------------------------------------------------

PARTIAL_MW = 15.000
REMAINDER_MW = 10.000

#: PRIME on 60,000,000.00 of EBITDA: min(25,000,000.00, 3,000,000.00).
INITIAL_THRESHOLD_USD = 3000000.00
#: The restatement keeps the tier and shrinks the limb that binds:
#: min(25,000,000.00, 20,000,000.00 * 5%).
RESTATED_EBITDA_USD = 20000000.00
RESTATED_THRESHOLD_USD = 1000000.00
#: ceil((1,395,030.00 - 1,000,000.00) / 250,000.00) = ceil(1.58012) = 2.
RESTATED_REQUIREMENT_USD = 500000.00
ANCHOR_SCORE = 83.70

CASH_COVER_USD = 500000.00
#: Well clear of the 365-day tenor rule.
LONG_EXPIRY = "2031-08-01T00:00:00Z"

EXECUTED_CP_COUNT = 3
NO_CONDITION_CLEARED_PCT = 0.00


def test_07_signing_reports_allocation_completeness_before_coverage(api):
    """A same-band restatement leaves an `APPROVED` deal under-collateralised, and
    the resulting execute attempt reports only the allocation rung; filling the
    capacity exposes the coverage rung, and posting exactly the requirement signs.

    "When a single request violates several rules at once, exactly one error is
    returned, and which one is fully determined."

    "If the tier stays inside the band it was already in, `qualification_status`
    does not move — but the deal-side consequences still fire. Every
    non-terminated deal anchored by this buyer re-snapshots
    `unsecured_credit_limit_usd` and `collateral_threshold_usd` from the buyer and
    re-sizes `credit_support_required_usd`. Crucially, `credit_status` is
    deliberately **not** re-opened on this path. A deal can therefore sit at
    `APPROVED` carrying a freshly enlarged requirement, and the discrepancy is
    caught later, at signing, by `ERR_CREDIT_SUPPORT_SHORTFALL`."

    "`confirmed_allocated_mw` must equal `contracted_mw` exactly, or the answer is
    `ERR_ALLOCATION_INCOMPLETE`; a single-buyer deal satisfies this with one
    confirmed slice equal to the contracted total."

    "`posted_credit_support_usd` must be at least `credit_support_required_usd`,
    or the answer is `ERR_CREDIT_SUPPORT_SHORTFALL` — equality passes, and a
    requirement of 0.00 passes with nothing posted at all."

    "Execution then sets `cp_total_count` to the number of rows included and
    computes `cp_completion_pct`, which is one hundred multiplied by the count of
    the deal's conditions whose `status` is `SATISFIED` or `WAIVED`, divided by
    `cp_total_count`, rounded half up to two decimal places; both `FAILED` and
    `PENDING` count as not cleared."

    Design: Corner/validations/execute_ladder_allocation_incomplete_then_support_shortfall_then_signed
    """
    chain = fx.negotiated_chain(
        api, allocated_mw=PARTIAL_MW,
        deal_overrides={"product_type": "AGGREGATED", "term_years": 12,
                        "settlement_frequency": "MONTHLY"})
    deal_id = chain["deal"]["id"]
    anchor_id = chain["buyer"]["id"]
    approved = chain["deal"]
    assert approved["status"] == "TERMS_AGREED", approved
    assert approved["credit_status"] == "APPROVED", approved
    asserts.assert_money(approved["collateral_threshold_usd"],
                         INITIAL_THRESHOLD_USD, "collateral_threshold_usd")
    asserts.assert_money(approved["credit_support_required_usd"], 0.00,
                         "credit_support_required_usd")
    asserts.assert_money(approved["exposure_usd"], EXPOSURE_USD, "exposure_usd")
    asserts.assert_mw(approved["confirmed_allocated_mw"], PARTIAL_MW,
                      "confirmed_allocated_mw")

    second = fx.create_qualified_offtaker(api, anchor=False, **CASCADIA)

    # A restatement inside the same tier band: nothing about the buyer's
    # standing moves, but the EBITDA limb of its limit collapses.
    restated = get_success_data(api.change_offtaker_rating(
        anchor_id,
        f.rating_change_payload("A", reported_ebitda_usd=RESTATED_EBITDA_USD),
        CREDIT_OFFICER), 200)
    asserts.assert_score(restated["credit_score"], ANCHOR_SCORE, "credit_score")
    assert restated["credit_tier"] == "PRIME", restated
    assert restated["qualification_status"] == "QUALIFIED", restated
    asserts.assert_money(restated["unsecured_credit_limit_usd"],
                         RESTATED_THRESHOLD_USD, "unsecured_credit_limit_usd")

    resized = fx.read_deal(api, deal_id)
    asserts.assert_money(resized["collateral_threshold_usd"],
                         RESTATED_THRESHOLD_USD, "collateral_threshold_usd")
    asserts.assert_money(resized["credit_support_required_usd"],
                         RESTATED_REQUIREMENT_USD, "credit_support_required_usd")
    asserts.assert_money(resized["posted_credit_support_usd"], 0.00,
                         "posted_credit_support_usd")
    assert resized["credit_status"] == "APPROVED", resized

    # Two rules are broken at once; only the lower priority number answers.
    incomplete = api.execute_deal(deal_id, DEAL_COMMITTEE)
    validate_error(incomplete, ApiErrorId.ERR_ALLOCATION_INCOMPLETE.value, 422)
    asserts.assert_error_envelope(incomplete)

    fx.confirmed_allocation(api, deal_id, second["id"], REMAINDER_MW,
                            joint_and_several=True)
    filled = fx.read_deal(api, deal_id)
    asserts.assert_mw(filled["confirmed_allocated_mw"], CONTRACTED_MW,
                      "confirmed_allocated_mw")

    # The second rung is only visible once the first is cleared.
    shortfall = api.execute_deal(deal_id, DEAL_COMMITTEE)
    validate_error(shortfall, ApiErrorId.ERR_CREDIT_SUPPORT_SHORTFALL.value, 422)

    unmoved = fx.read_deal(api, deal_id)
    assert unmoved["status"] == "TERMS_AGREED", unmoved
    assert unmoved["effective_at"] is None, unmoved
    assert unmoved["cp_total_count"] == 0, unmoved
    assert fx.conditions_of(api, deal_id) == [], (
        "neither refusal built any part of the condition-precedent set")

    posted = fx.post_cash(api, deal_id, CASH_COVER_USD, expiry_date=LONG_EXPIRY)
    asserts.assert_money(posted["haircut_pct"], 0.00, "haircut_pct")
    asserts.assert_money(posted["eligible_credit_usd"], CASH_COVER_USD,
                         "eligible_credit_usd")
    covered = fx.read_deal(api, deal_id)
    asserts.assert_money(covered["posted_credit_support_usd"],
                         RESTATED_REQUIREMENT_USD, "posted_credit_support_usd")

    executed = fx.execute_deal(api, deal_id)
    assert executed["status"] == "EXECUTED", executed
    assert executed["effective_at"] is None, executed
    assert executed["cp_total_count"] == EXECUTED_CP_COUNT, executed
    asserts.assert_score(executed["cp_completion_pct"],
                         NO_CONDITION_CLEARED_PCT, "cp_completion_pct")

    conditions = fx.conditions_of(api, deal_id)
    assert len(conditions) == EXECUTED_CP_COUNT, conditions
    assert sorted(row["cp_type"] for row in conditions) == \
        ["INTERCONNECTION", "NOTICE_TO_PROCEED", "PERMITTING"], conditions
    for cp_type, deadline, waivable in (
            ("PERMITTING", fx.CP_PERMITTING_DEADLINE, False),
            ("INTERCONNECTION", fx.CP_INTERCONNECTION_DEADLINE, False),
            ("NOTICE_TO_PROCEED", fx.CP_NOTICE_TO_PROCEED_DEADLINE, True)):
        row = asserts.row_by(conditions, "cp_type", cp_type)
        assert row["status"] == "PENDING", row
        assert row["is_waivable"] is waivable, row
        asserts.assert_instant_equals(row["deadline_date"], deadline,
                                      f"{cp_type} deadline_date")

    # The anchor already holds a registry account, so that row never appears.
    assert chain["buyer"]["registry_account_id"] is not None, chain["buyer"]
    assert [row for row in conditions
            if row["cp_type"] == "REGISTRY_ACCOUNT"] == [], conditions
