"""The declared machines: initial states, legal hops, refusals and cascades.

Four machines are opened and read at rest; the project machine is then walked
end to end and probed for skips; two declared terminal states are pushed at from
both sides; a confirmation is replayed; and the three big fan-outs — the round
sweep that fires as a side effect of tabling, the rating downgrade that rewrites
money on the deal, and the three-branch termination cascade — are pinned hop by
hop.  Every refusal is checked for having written nothing.
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
    CREDIT_OFFICER_ID,
    ORIGINATOR,
    ORIGINATOR_ID,
    make_credit_officer_headers,
    make_offtaker_rep_headers,
)

#: The five figures that "are all null - no scoring runs at creation".
COMPUTED_CREDIT_FIELDS = [
    "credit_score",
    "credit_score_variant",
    "credit_tier",
    "sustainability_score",
    "unsecured_credit_limit_usd",
]

PROJECT_CAPACITY_MW = 100.000
CONTRACTED_MW = 25.000

#: The fully sustainable anchor buyer's derived figures, which appear only once
#: it has been submitted for review.
ANCHOR_SCORE = 83.70

#: A buyer with no sustainability posture at all: BBB / FITCH / 4.0 / NONE
#: scores 62.10 STANDARD with sustainability 0.00, so it cannot qualify.
BARE_MINIMUM = {
    "legal_name": "Bare Minimum Industrials LLC",
    "credit_rating": "BBB",
    "rating_agency": "FITCH",
    "reported_ebitda_usd": 20000000.00,
    "net_debt_to_ebitda": 4.0,
    "disclosure_framework": "NONE",
}
BARE_SCORE = 62.10
BARE_SUSTAINABILITY = 0.00


def test_01_four_machines_each_open_in_their_declared_initial_state(api):
    """A buyer opens in `DRAFT` with no score at all, a project in
    `PRE_DEVELOPMENT` with its whole nameplate free, and a deal in `DRAFT` on the
    commercial dimension and `NOT_SUBMITTED` on the credit dimension.

    "On creation `qualification_status` is `DRAFT`, `conditions` is the empty
    array, `claimed_attributes_mwh` is 0, `watchlist_since` is null,
    `decision_by_user_id` is null, and `credit_score`, `credit_score_variant`,
    `credit_tier`, `sustainability_score` and `unsecured_credit_limit_usd` are all
    null — no scoring runs at creation."

    "On creation, `contracted_mw` is 0 and `available_mw` equals `capacity_mw`;
    `last_milestone_at` is null and `created_by_user_id` is stamped from the
    acting operator's identifier."

    "`status` is `DRAFT` and `credit_status` is `NOT_SUBMITTED`; `round_count` is
    0; `confirmed_allocated_mw` is 0 and `unallocated_mw` equals `contracted_mw`;
    `cp_total_count` is 0"

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_state
    """
    node = fx.create_node(api)

    buyer = get_success_data(
        api.create_offtaker(f.anchor_offtaker_payload(), ORIGINATOR), 201)
    assert buyer["qualification_status"] == "DRAFT", buyer
    assert buyer["conditions"] == [], buyer
    asserts.assert_all_null(buyer, COMPUTED_CREDIT_FIELDS
                            + ["watchlist_since", "decision_by_user_id"])
    assert buyer["created_by_user_id"] == ORIGINATOR_ID, buyer
    asserts.assert_common_fields(buyer, expected_version=1)

    project = get_success_data(
        api.create_project(f.project_payload(node["id"]), ORIGINATOR), 201)
    assert project["status"] == "PRE_DEVELOPMENT", project
    asserts.assert_mw(project["contracted_mw"], 0.000, "contracted_mw")
    asserts.assert_mw(project["available_mw"], PROJECT_CAPACITY_MW,
                      "available_mw")
    assert project["last_milestone_at"] is None, project
    asserts.assert_common_fields(project, expected_version=1)

    # Scoring is not qualification: submitting for review populates the five
    # figures without carrying the buyer past UNDER_REVIEW.
    reviewed = fx.submit_offtaker(api, buyer["id"])
    assert reviewed["qualification_status"] == "UNDER_REVIEW", reviewed
    asserts.assert_score(reviewed["credit_score"], ANCHOR_SCORE, "credit_score")
    assert reviewed["credit_tier"] == "PRIME", reviewed

    # The deal's two dimensions are initialised separately in the same row.
    qualified = fx.decide_offtaker(api, buyer["id"], "QUALIFY")
    assert qualified["qualification_status"] == "QUALIFIED", qualified
    deal = fx.create_deal(api, project["id"], buyer["id"], node["id"])
    assert deal["status"] == "DRAFT", deal
    assert deal["credit_status"] == "NOT_SUBMITTED", deal
    assert deal["round_count"] == 0, deal
    assert deal["cp_total_count"] == 0, deal
    asserts.assert_mw(deal["confirmed_allocated_mw"], 0.000,
                      "confirmed_allocated_mw")
    asserts.assert_mw(deal["unallocated_mw"], CONTRACTED_MW, "unallocated_mw")
    asserts.assert_common_fields(deal, expected_version=1)


#: Moved once before the walk so `last_milestone_at` is provably read from the
#: logical clock rather than from wall time.
WALK_CLOCK = "2026-09-15T00:00:00Z"


def test_02_the_project_machine_is_walked_hop_by_hop_to_its_terminal_state(api):
    """Four advances land the four declared states — the notice-to-proceed
    request word lands `NTP_ISSUED` — and every hop stamps the same frozen clock
    while the capacity ledger stays exactly where it started.

    "The milestone must be the single legal successor of the project's current
    `status`: `PRE_DEVELOPMENT` becomes `PERMITTED`, `PERMITTED` becomes
    `INTERCONNECTION_APPROVED`, `INTERCONNECTION_APPROVED` becomes `NTP_ISSUED`
    when the milestone `NOTICE_TO_PROCEED` is named, and `NTP_ISSUED` becomes
    `OPERATIONAL`, which is terminal."

    "Each advance sets `last_milestone_at` to the logical clock and increments the
    project's `version` by one."

    Design: Corner/state_machines/project_advances_through_four_milestones_to_operational
    """
    node = fx.create_node(api)
    project = fx.create_project(api, node["id"])
    fx.set_clock(api, WALK_CLOCK)

    expected_version = project["version"]
    for milestone, evidence_ref in fx.MILESTONE_CHAIN:
        advanced = fx.advance_milestone(api, project["id"], milestone,
                                        evidence_ref)
        expected_version += 1
        assert advanced["status"] == fx.MILESTONE_TARGET_STATUS[milestone], (
            f"milestone {milestone} must land in "
            f"{fx.MILESTONE_TARGET_STATUS[milestone]}, got {advanced['status']}")
        asserts.assert_instant_equals(advanced["last_milestone_at"], WALK_CLOCK,
                                      "last_milestone_at")
        assert advanced["version"] == expected_version, advanced

    final = fx.read_project(api, project["id"])
    assert final["status"] == "OPERATIONAL", final
    asserts.assert_version_advanced_by(project["version"], final["version"], 4,
                                       "project version")

    # Milestones are not contracts: nothing about the ledger moved.
    asserts.assert_mw(final["contracted_mw"], 0.000, "contracted_mw")
    asserts.assert_mw(final["available_mw"], PROJECT_CAPACITY_MW,
                      "available_mw")


def test_03_skipping_a_milestone_is_a_state_refusal_not_a_fast_forward(api):
    """Two of the three forward jumps out of `PRE_DEVELOPMENT` are refused as
    state transitions rather than as bad enum members, write nothing, and leave
    the one legal successor working.

    "Requesting any other jump is refused by the state gate with
    `ERR_INVALID_STATE_TRANSITION`."

    "The state gate — `ERR_INVALID_STATE_TRANSITION`. This check owns one
    question and only one: does the subject entity's own current state, on the
    dimension being moved, have a declared transition for the requested action?"

    Design: Corner/state_machines/project_milestone_skip_returns_invalid_state_transition
    """
    node = fx.create_node(api)
    project = fx.create_project(api, node["id"])
    project_id = project["id"]

    jumped = api.advance_project_milestone(
        project_id,
        f.advance_milestone_payload("OPERATIONAL", "COD-JUMPED-THE-QUEUE"),
        ORIGINATOR)
    validate_error(jumped, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)
    asserts.assert_error_envelope(jumped)

    skipped_permit = api.advance_project_milestone(
        project_id,
        f.advance_milestone_payload("INTERCONNECTION_APPROVED",
                                    "LGIA-SKIPPED-PERMIT"),
        ORIGINATOR)
    validate_error(skipped_permit,
                   ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    # A refused transition writes nothing at all.
    refused = fx.read_project(api, project_id)
    assert refused["status"] == "PRE_DEVELOPMENT", refused
    assert refused["last_milestone_at"] is None, refused
    assert refused["version"] == project["version"], refused

    # The endpoint itself was never broken.
    permitted = fx.advance_milestone(api, project_id, "PERMITTED",
                                     "CUP-2026-0442")
    assert permitted["status"] == "PERMITTED", permitted
    asserts.assert_instant_equals(permitted["last_milestone_at"],
                                  fx.INITIAL_CLOCK, "last_milestone_at")
    asserts.assert_version_advanced_by(project["version"],
                                       permitted["version"], 1,
                                       "project version")


def test_04_two_declared_terminal_states_absorb_every_further_trigger(api):
    """A rejected buyer cannot be re-submitted or re-decided, and an operational
    project cannot advance a fifth time; all three attempts are 409s and not 200
    no-ops.

    "`REJECT` moves the buyer `UNDER_REVIEW → REJECTED`, which is terminal, stamps
    `decision_by_user_id`, and cascades: every deal anchored by this buyer whose
    `status` is `DRAFT`, `TERM_SHEET_ISSUED` or `UNDER_NEGOTIATION` has its
    `credit_status` set to `DECLINED` and its `version` incremented by one."

    "The milestone must be the single legal successor of the project's current
    `status`: `PRE_DEVELOPMENT` becomes `PERMITTED`, `PERMITTED` becomes
    `INTERCONNECTION_APPROVED`, `INTERCONNECTION_APPROVED` becomes `NTP_ISSUED`
    when the milestone `NOTICE_TO_PROCEED` is named, and `NTP_ISSUED` becomes
    `OPERATIONAL`, which is terminal."

    Design: Corner/state_machines/terminal_states_reject_every_further_trigger
    """
    buyer = fx.create_rejected_offtaker(api, anchor=False, **BARE_MINIMUM)
    buyer_id = buyer["id"]
    assert buyer["qualification_status"] == "REJECTED", buyer
    asserts.assert_score(buyer["credit_score"], BARE_SCORE, "credit_score")
    assert buyer["credit_tier"] == "STANDARD", buyer
    asserts.assert_score(buyer["sustainability_score"], BARE_SUSTAINABILITY,
                         "sustainability_score")

    # REJECTED has no outbound edge, unlike CONDITIONAL which does.
    resubmitted = api.submit_offtaker_qualification(buyer_id, ORIGINATOR)
    validate_error(resubmitted, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
                   409)
    asserts.assert_error_envelope(resubmitted)

    redecided = api.decide_offtaker_qualification(
        buyer_id, f.qualification_decision_payload("QUALIFY"), CREDIT_OFFICER)
    validate_error(redecided, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    locked = fx.read_offtaker(api, buyer_id)
    assert locked["qualification_status"] == "REJECTED", locked
    assert locked["version"] == buyer["version"], locked

    node = fx.create_node(api)
    project = fx.create_operational_project(api, node["id"])
    assert project["status"] == "OPERATIONAL", project

    fifth_advance = api.advance_project_milestone(
        project["id"], f.advance_milestone_payload("OPERATIONAL", "COD-AGAIN"),
        ORIGINATOR)
    validate_error(fifth_advance, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
                   409)

    unmoved = fx.read_project(api, project["id"])
    assert unmoved["status"] == "OPERATIONAL", unmoved
    assert unmoved["version"] == project["version"], unmoved


def test_05_a_replayed_confirmation_is_refused_and_does_not_double_count(api):
    """The second `CONFIRM` on the same slice is a 409 rather than an idempotent
    200, so the megawatts are not counted twice, while `WITHDRAW` from
    `CONFIRMED` is a declared edge and works.

    "A `CONFIRM` moves the slice `PROPOSED → CONFIRMED`, requires that the deal's
    `status` is `TERM_SHEET_ISSUED`, `UNDER_NEGOTIATION` or `TERMS_AGREED` and
    that the referenced buyer's `qualification_status` is `QUALIFIED` or
    `CONDITIONAL`, and stamps `confirmed_at` with the logical clock."

    "`WITHDRAW` is the exact compensating action, and it is legal from either live
    state."

    "`confirmed_allocated_mw` is always the sum of `allocated_mw` over the deal's
    `CONFIRMED` slices."

    Design: Corner/state_machines/allocation_confirm_twice_second_attempt_rejected
    """
    chain = fx.chain_a(api)
    deal_id = chain["deal"]["id"]
    buyer_id = chain["buyer"]["id"]
    fx.table_round(api, deal_id)
    slice_row = fx.propose_allocation(api, deal_id, buyer_id, CONTRACTED_MW)

    confirmed = fx.confirm_allocation(api, slice_row["id"], buyer_id)
    assert confirmed["status"] == "CONFIRMED", confirmed
    asserts.assert_instant_equals(confirmed["confirmed_at"], fx.INITIAL_CLOCK,
                                  "confirmed_at")
    subscribed = fx.read_deal(api, deal_id)
    asserts.assert_mw(subscribed["confirmed_allocated_mw"], CONTRACTED_MW,
                      "confirmed_allocated_mw")
    asserts.assert_mw(subscribed["unallocated_mw"], 0.000, "unallocated_mw")

    replayed = api.decide_allocation(
        slice_row["id"], f.allocation_decision_payload("CONFIRM"),
        make_offtaker_rep_headers(buyer_id))
    validate_error(replayed, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)
    asserts.assert_error_envelope(replayed)

    # The recompute did not run twice: 25.000, never 50.000.
    rows, _ = fx.list_all(api.list_allocations(deal_id, ORIGINATOR))
    still_confirmed = asserts.row_by_id(rows, slice_row["id"])
    assert still_confirmed["version"] == confirmed["version"], still_confirmed
    unchanged = fx.read_deal(api, deal_id)
    asserts.assert_mw(unchanged["confirmed_allocated_mw"], CONTRACTED_MW,
                      "confirmed_allocated_mw")
    assert unchanged["version"] == subscribed["version"], unchanged

    withdrawn = fx.withdraw_allocation(api, slice_row["id"], buyer_id)
    assert withdrawn["status"] == "WITHDRAWN", withdrawn
    released = fx.read_deal(api, deal_id)
    asserts.assert_mw(released["confirmed_allocated_mw"], 0.000,
                      "confirmed_allocated_mw")
    asserts.assert_mw(released["unallocated_mw"], CONTRACTED_MW,
                      "unallocated_mw")


def test_06_the_right_role_with_the_wrong_identity_is_a_403_about_duties(api):
    """The operator who created the deal cannot decide its credit, and the
    operator who created a buyer cannot decide its qualification, even wearing a
    perfectly valid `CreditOfficer` header.

    "Four named checks compare `X-User-ID` against an identifier the system
    recorded at an earlier step, and any of them failing returns
    `ERR_SEGREGATION_OF_DUTIES` at HTTP 403."

    "First, the operator recorded as an `Offtaker`'s `created_by_user_id` may not
    render that same buyer's qualification decision."

    "The credit decision itself belongs to a `CreditOfficer` who is not the
    operator recorded as the deal's `created_by_user_id`."

    Design: Corner/state_machines/credit_decision_by_the_deal_creator_returns_segregation_of_duties
    """
    chain = fx.chain_a(api)
    deal_id = chain["deal"]["id"]
    buyer_id = chain["buyer"]["id"]
    other_buyer = fx.create_submitted_offtaker(api, anchor=False,
                                               **BARE_MINIMUM)
    term_sheet = fx.table_round(api, deal_id)
    fx.respond_accept(api, term_sheet["id"], buyer_id)
    submitted = fx.submit_credit(api, deal_id)
    assert submitted["status"] == "TERMS_AGREED", submitted
    assert submitted["credit_status"] == "SUBMITTED", submitted

    # The role header is correct and only the identity is wrong.
    wearing_the_wrong_hat = make_credit_officer_headers(ORIGINATOR_ID)
    self_approved = api.decide_deal_credit(
        deal_id, f.credit_decision_payload("APPROVE"), wearing_the_wrong_hat)
    validate_error(self_approved, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
                   403)
    asserts.assert_error_envelope(self_approved)

    blocked = fx.read_deal(api, deal_id)
    assert blocked["credit_status"] == "SUBMITTED", blocked
    assert blocked["credit_approved_by_user_id"] is None, blocked
    assert blocked["version"] == submitted["version"], blocked

    self_decided = api.decide_offtaker_qualification(
        other_buyer["id"], f.qualification_decision_payload("REJECT"),
        wearing_the_wrong_hat)
    validate_error(self_decided, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    undecided = fx.read_offtaker(api, other_buyer["id"])
    assert undecided["qualification_status"] == "UNDER_REVIEW", undecided
    assert undecided["decision_by_user_id"] is None, undecided
    assert undecided["version"] == other_buyer["version"], undecided

    # A different identity holding the same role is admitted.
    approved = fx.decide_credit(api, deal_id, "APPROVE")
    assert approved["credit_status"] == "APPROVED", approved
    assert approved["credit_approved_by_user_id"] == CREDIT_OFFICER_ID, approved
    assert approved["status"] == "TERMS_AGREED", approved


# ---------------------------------------------------------------------------
# The OPEN -> EXPIRED edge has no endpoint of its own: it fires as a side
# effect of tabling the next developer round.
# ---------------------------------------------------------------------------

ROUND_1_DEADLINE = "2026-08-10T00:00:00Z"

#: The successor round's deadline is computed, not supplied: fourteen days after
#: the logical clock.
ROUND_2_DEADLINE = fx.iso_plus(fx.INITIAL_CLOCK, days=14)

#: Past round 2's deadline, with round 2 still OPEN.
SWEEP_CLOCK = "2026-08-20T00:00:00Z"

ROUND_3_DEADLINE = "2026-09-15T00:00:00Z"


def test_07_tabling_the_next_round_expires_the_lapsed_one_and_spares_the_rest(api):
    """Round 3 is numbered from `round_count` rather than from the number of open
    rounds, expires the lapsed round 2, and leaves the already-countered round 1
    exactly as it was.

    "Tabling a developer round from `UNDER_NEGOTIATION` returns the deal
    `UNDER_NEGOTIATION → TERM_SHEET_ISSUED` — this alternation is the redline
    loop, and it is why the commercial dimension is cyclic rather than linear."

    "That path also sweeps whatever is still outstanding: any round of this deal
    whose `status` is `OPEN` and whose `response_deadline` has already fallen
    before the logical clock moves `OPEN → EXPIRED`, leaving `responded_at` and
    `responded_by_user_id` null; any round whose `status` is `OPEN` and whose
    `response_deadline` is at or after the logical clock moves `OPEN → COUNTERED`
    with `responded_by_user_id` set to the tabling operator."

    "The new round is created with `round_number` equal to the deal's
    `round_count` plus one, `status` `OPEN`, `responded_at` null and
    `responded_by_user_id` null; the deal's `round_count` then increments and its
    `version` increments by one."

    Design: Corner/state_machines/new_developer_round_expires_the_still_open_prior_round
    """
    chain = fx.chain_a(api)
    deal_id = chain["deal"]["id"]
    buyer_id = chain["buyer"]["id"]

    round_one = fx.table_round(api, deal_id,
                               response_deadline=ROUND_1_DEADLINE)
    assert round_one["round_number"] == 1, round_one
    round_two = fx.respond_counter(api, round_one["id"], buyer_id,
                                   counter_fixed_price_usd_per_mwh=20.00,
                                   counter_basis_responsibility="SELLER")

    before_rows, _ = fx.list_all(api.list_rounds(deal_id, ORIGINATOR))
    countered = asserts.row_by_id(before_rows, round_one["id"])
    assert countered["status"] == "COUNTERED", countered
    assert countered["round_number"] == 1, countered
    still_open = asserts.row_by_id(before_rows, round_two["id"])
    assert still_open["status"] == "OPEN", still_open
    assert still_open["round_number"] == 2, still_open
    assert still_open["proposed_by"] == "OFFTAKER", still_open
    asserts.assert_instant_equals(still_open["response_deadline"],
                                  ROUND_2_DEADLINE, "response_deadline")
    negotiating = fx.read_deal(api, deal_id)
    assert negotiating["status"] == "UNDER_NEGOTIATION", negotiating
    assert negotiating["round_count"] == 2, negotiating

    fx.set_clock(api, SWEEP_CLOCK)
    round_three = fx.table_round(api, deal_id,
                                 response_deadline=ROUND_3_DEADLINE,
                                 proposed_fixed_price_usd_per_mwh=21.50,
                                 proposed_escalation_pct_per_year=1.0)
    assert round_three["round_number"] == 3, round_three
    assert round_three["status"] == "OPEN", round_three
    assert round_three["proposed_by"] == "DEVELOPER", round_three
    asserts.assert_all_null(round_three, ["responded_at",
                                          "responded_by_user_id"])

    after_rows, meta = fx.list_all(api.list_rounds(deal_id, ORIGINATOR))
    assert meta["total_count"] == 3, meta
    expired = asserts.row_by_id(after_rows, round_two["id"])
    assert expired["status"] == "EXPIRED", expired
    asserts.assert_all_null(expired, ["responded_at", "responded_by_user_id"])
    asserts.assert_version_advanced_by(still_open["version"],
                                       expired["version"], 1, "round version")

    # A terminal round is not re-expired by the sweep.
    untouched = asserts.row_by_id(after_rows, round_one["id"])
    assert untouched["status"] == "COUNTERED", untouched
    assert untouched["version"] == countered["version"], untouched

    reissued = fx.read_deal(api, deal_id)
    assert reissued["status"] == "TERM_SHEET_ISSUED", reissued
    assert reissued["round_count"] == 3, reissued

    open_rows, open_meta = fx.list_all(
        api.list_rounds(deal_id, ORIGINATOR, params={"status": "OPEN"}))
    asserts.assert_page_meta(open_meta, total_count=1, limit=10, offset=0,
                             has_more=False)
    assert open_rows[0]["id"] == round_three["id"], open_rows


# ---------------------------------------------------------------------------
# One write to the buyer rewrites money on the deal.
# ---------------------------------------------------------------------------

QUALIFIED_SCORE = 83.70
QUALIFIED_LIMIT_USD = 3000000.00
DOWNGRADED_SCORE = 60.25
DOWNGRADED_LIMIT_USD = 300000.00
SUSTAINABILITY_SCORE = 100.00
CONTRACT_PRICE = 22.75
EXPOSURE_USD = 1395030.00
SHORTFALL_REQUIREMENT_USD = 1250000.00
SUPPORT_CURE_DEADLINE = fx.iso_plus(fx.INITIAL_CLOCK, days=10)


def test_08_a_downgrade_watchlists_the_buyer_and_shortfalls_its_deal(api):
    """`A` to `BB` with leverage doubling collapses the unsecured line, which
    turns a deal that needed no collateral into one that needs 1,250,000.00 and
    arms a cure deadline, without repricing the contract.

    "A drop out of `QUALIFIED` into a recomputed `credit_tier` of `SUBPRIME` or
    `DECLINED` moves the buyer `QUALIFIED → WATCHLIST` and fires a four-hop
    cascade."

    "Hop three, caused by hop two's larger requirement, takes each of those deals
    whose `credit_status` is `APPROVED` and whose `posted_credit_support_usd` now
    falls below the recomputed `credit_support_required_usd`, moves it `APPROVED →
    SUPPORT_SHORTFALL` and sets `support_cure_deadline` to ten days after the
    logical clock."

    "Third, otherwise, the residual is `exposure_usd` less
    `collateral_threshold_usd`, that residual is divided by the collateral
    increment of 250,000.00 USD and the quotient is rounded **up** to the next
    whole number of increments — a ceiling, never a half-up round — and
    `credit_support_required_usd` is that whole count of increments multiplied by
    250,000.00."

    Design: Corner/state_machines/rating_change_downgrade_watchlists_buyer_and_shortfalls_the_deal
    """
    chain = fx.chain_b(api)
    deal_id = chain["deal"]["id"]
    buyer_id = chain["buyer"]["id"]

    before_buyer = fx.read_offtaker(api, buyer_id)
    assert before_buyer["qualification_status"] == "QUALIFIED", before_buyer
    assert before_buyer["credit_tier"] == "PRIME", before_buyer
    asserts.assert_score(before_buyer["credit_score"], QUALIFIED_SCORE,
                         "credit_score")
    asserts.assert_money(before_buyer["unsecured_credit_limit_usd"],
                         QUALIFIED_LIMIT_USD, "unsecured_credit_limit_usd")
    assert before_buyer["watchlist_since"] is None, before_buyer

    before_deal = fx.read_deal(api, deal_id)
    assert before_deal["credit_status"] == "APPROVED", before_deal
    asserts.assert_money(before_deal["exposure_usd"], EXPOSURE_USD,
                         "exposure_usd")
    asserts.assert_money(before_deal["credit_support_required_usd"], 0.00,
                         "credit_support_required_usd")
    assert before_deal["support_cure_deadline"] is None, before_deal

    downgraded = get_success_data(api.change_offtaker_rating(
        buyer_id, f.rating_change_payload("BB", net_debt_to_ebitda=5.0),
        CREDIT_OFFICER), 200)
    asserts.assert_score(downgraded["credit_score"], DOWNGRADED_SCORE,
                         "credit_score")
    assert downgraded["credit_tier"] == "SUBPRIME", downgraded
    assert downgraded["credit_score_variant"] == "STANDALONE", downgraded
    asserts.assert_money(downgraded["unsecured_credit_limit_usd"],
                         DOWNGRADED_LIMIT_USD, "unsecured_credit_limit_usd")
    assert downgraded["qualification_status"] == "WATCHLIST", downgraded
    asserts.assert_instant_equals(downgraded["watchlist_since"],
                                  fx.INITIAL_CLOCK, "watchlist_since")

    # The sustainability chain is untouched by a credit downgrade.
    asserts.assert_score(downgraded["sustainability_score"],
                         SUSTAINABILITY_SCORE, "sustainability_score")

    after_deal = fx.read_deal(api, deal_id)
    asserts.assert_money(after_deal["unsecured_credit_limit_usd"],
                         DOWNGRADED_LIMIT_USD, "unsecured_credit_limit_usd")
    asserts.assert_money(after_deal["collateral_threshold_usd"],
                         DOWNGRADED_LIMIT_USD, "collateral_threshold_usd")
    asserts.assert_money(after_deal["credit_support_required_usd"],
                         SHORTFALL_REQUIREMENT_USD,
                         "credit_support_required_usd")
    assert after_deal["credit_status"] == "SUPPORT_SHORTFALL", after_deal
    asserts.assert_instant_equals(after_deal["support_cure_deadline"],
                                  SUPPORT_CURE_DEADLINE,
                                  "support_cure_deadline")

    # A credit downgrade does not reprice the contract.
    assert after_deal["status"] == "TERMS_AGREED", after_deal
    asserts.assert_money(after_deal["contract_price_usd_per_mwh"],
                         CONTRACT_PRICE, "contract_price_usd_per_mwh")
    assert after_deal["version"] > before_deal["version"], after_deal


# ---------------------------------------------------------------------------
# One terminate call fans out down three child collections at once.
# ---------------------------------------------------------------------------

DEVELOPMENT_SECURITY_USD = 500000.00

#: Past the failed condition's fifteen-day cure window, so the CP_FAILURE right
#: is vested.
TERMINATION_CLOCK = "2026-09-01T00:00:00Z"


def test_09_terminating_an_executed_deal_fails_the_cps_and_releases_collateral(api):
    """The two still-pending conditions fail with a null cure deadline, the posted
    cash is released rather than drawn because the reason is not `BUYER_DEFAULT`,
    the project gets its megawatts back, and the condition that vested the right
    is not re-resolved.

    "From `EXECUTED` the deal moves `EXECUTED → TERMINATED` and a three-branch
    cascade fires off that stamp. The first branch fails the outstanding
    conditions: every condition of the deal whose `status` is `PENDING` moves
    `PENDING → FAILED` with `resolved_at` set to the logical clock and
    `cure_deadline` left null, and then `cp_completion_pct` is recomputed over the
    new statuses. The second branch resolves the collateral: every instrument
    whose `status` is `POSTED` moves `POSTED → DRAWN` when the
    `termination_reason` is `BUYER_DEFAULT` and `POSTED → RELEASED` for every
    other reason, with `closed_at` stamped in both cases, and then
    `posted_credit_support_usd`, `released_credit_support_usd` and
    `drawn_credit_support_usd` are all recomputed."

    "`CP_FAILURE` is vested when some condition of the deal has `status` `FAILED`
    and either its `cure_deadline` is null or that `cure_deadline` falls before the
    logical clock."

    "Every termination path also recomputes the project's `contracted_mw` and
    `available_mw` and increments the deal's `version` by one, along with the
    `version` of every row the cascade touched."

    Design: Corner/state_machines/deal_termination_from_executed_cascades_cps_and_releases_security
    """
    chain = fx.chain_b(api)
    deal_id = chain["deal"]["id"]
    instrument = fx.post_cash(api, deal_id, DEVELOPMENT_SECURITY_USD,
                              purpose="DEVELOPMENT_SECURITY",
                              expiry_date="2031-12-31T00:00:00Z")
    assert instrument["status"] == "POSTED", instrument

    executed = fx.execute_deal(api, deal_id)
    assert executed["status"] == "EXECUTED", executed
    assert executed["cp_total_count"] == 3, executed
    asserts.assert_score(executed["cp_completion_pct"], 0.00,
                         "cp_completion_pct")
    asserts.assert_money(executed["posted_credit_support_usd"],
                         DEVELOPMENT_SECURITY_USD, "posted_credit_support_usd")
    asserts.assert_money(executed["released_credit_support_usd"], 0.00,
                         "released_credit_support_usd")

    permitting = fx.condition_by_type(api, deal_id, "PERMITTING")
    failed = fx.fail_condition(api, permitting["id"])
    assert failed["status"] == "FAILED", failed
    asserts.assert_instant_equals(failed["cure_deadline"], fx.CP_CURE_DEADLINE,
                                  "cure_deadline")
    assert failed["resolved_by_user_id"] == ORIGINATOR_ID, failed

    fx.set_clock(api, TERMINATION_CLOCK)
    terminated = fx.terminate_deal(api, deal_id, "CP_FAILURE")
    assert terminated["status"] == "TERMINATED", terminated
    asserts.assert_instant_equals(terminated["terminated_at"],
                                  TERMINATION_CLOCK, "terminated_at")
    assert terminated["termination_reason"] == "CP_FAILURE", terminated
    asserts.assert_score(terminated["cp_completion_pct"], 0.00,
                         "cp_completion_pct")

    # The 500,000.00 moved bucket to bucket without changing the total.
    asserts.assert_money(terminated["posted_credit_support_usd"], 0.00,
                         "posted_credit_support_usd")
    asserts.assert_money(terminated["released_credit_support_usd"],
                         DEVELOPMENT_SECURITY_USD,
                         "released_credit_support_usd")
    asserts.assert_money(terminated["drawn_credit_support_usd"], 0.00,
                         "drawn_credit_support_usd")

    rows = fx.conditions_of(api, deal_id)
    assert len(rows) == 3, rows
    for row in rows:
        assert row["status"] == "FAILED", row
    for cp_type in ("INTERCONNECTION", "NOTICE_TO_PROCEED"):
        swept = asserts.row_by(rows, "cp_type", cp_type)
        asserts.assert_instant_equals(swept["resolved_at"], TERMINATION_CLOCK,
                                      "resolved_at")
        assert swept["cure_deadline"] is None, swept

    # The cascade did not re-resolve the condition that vested the right.
    vesting = asserts.row_by(rows, "cp_type", "PERMITTING")
    assert vesting["resolved_by_user_id"] == ORIGINATOR_ID, vesting
    asserts.assert_instant_equals(vesting["cure_deadline"], fx.CP_CURE_DEADLINE,
                                  "cure_deadline")
    asserts.assert_instant_equals(vesting["resolved_at"], fx.INITIAL_CLOCK,
                                  "resolved_at")

    stack, _ = fx.list_all(api.list_credit_support(deal_id, CREDIT_OFFICER))
    released = asserts.row_by_id(stack, instrument["id"])
    assert released["status"] == "RELEASED", released
    asserts.assert_instant_equals(released["closed_at"], TERMINATION_CLOCK,
                                  "closed_at")

    # The 25.000 MW reservation was handed back.
    project = fx.read_project(api, chain["project"]["id"])
    asserts.assert_mw(project["contracted_mw"], 0.000, "contracted_mw")
    asserts.assert_mw(project["available_mw"], PROJECT_CAPACITY_MW,
                     "available_mw")

    # The allocation-withdrawal sweep is declared only on the TERMS_AGREED path.
    slices, _ = fx.list_all(api.list_allocations(deal_id, ORIGINATOR))
    assert asserts.row_by_id(slices, chain["allocation"]["id"])["status"] \
        == "CONFIRMED"
