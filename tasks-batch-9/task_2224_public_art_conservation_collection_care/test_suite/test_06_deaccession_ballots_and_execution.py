"""Balloting a deaccession case and executing it.

An all-abstention quorum leaves the decision denominator empty, the execution
gate refuses on an immature statutory notice before it notices a missing
disposition target, and a successful execution runs four cascade hops that empty
the site, terminate the work's live records and refund two funding pools' worth
of money.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_deaccession_case
from test_helpers.factories import deaccession_case_payload
from test_helpers.test_users import (
    COMMISSION_MEMBER_USER_IDS,
    TEST_USERS,
    make_commission_member_headers,
)


def _case_ready_to_execute(api):
    """A waived work carrying an approved treatment, a booked visit and a case."""
    state = fixtures.setup_approved_proposal(
        api, artist={"moral_rights_waiver_on_file": True}
    )
    assert state["artwork"]["moral_rights_status"] == "WAIVED"
    assert fixtures.read_pool(api, state["pool"]["id"])["available_cents"] == 19_827_500

    protocol = fixtures.create_protocol(api)
    visit = fixtures.schedule_visit(
        api,
        state["artwork"]["id"],
        protocol["id"],
        window_start="2026-09-25T08:00:00Z",
        window_end="2026-09-26T17:00:00Z",
    )
    visit_allocation = fixtures.reserve_allocation(
        api,
        state["pool"]["id"],
        purpose="MAINTENANCE",
        amount_cents=250_000,
        visit_id=visit["id"],
    )
    assert fixtures.read_pool(api, state["pool"]["id"])["available_cents"] == 19_577_500

    case = fixtures.setup_case_approved(api, state["artwork"]["id"])
    assert case["status"] == "APPROVED"
    state["protocol"] = protocol
    state["visit"] = visit
    state["visit_allocation"] = visit_allocation
    state["case"] = case
    return state


def test_execution_empties_the_site_and_closes_the_case(api):
    """PRD §3.8: "Execution is the manager's final act, carries an optional
    `execution_note` and moves the case `APPROVED → EXECUTED`, stamping `executed_at`
    from the logical clock."
    PRD §3.8: "Hop 1: the work's `custody_status` becomes `DESTROYED` when the
    disposition is `DESTRUCTION` and `DEACCESSIONED` for `SALE`, `TRANSFER` or
    `RETURN_TO_ARTIST`, moving from `ON_VIEW` or from `IN_STORAGE` in either case;
    where the work was `ON_VIEW`, its site's `installed_units_used` falls by the
    work's `footprint_units`, and where it was already `IN_STORAGE` no site adjustment
    is needed because none was being consumed."

    Design: Difficulty/transitive_cascade/deaccession_execute_withdraws_proposal_aborts_visit_and_refunds_two_allocations
    """
    state = _case_ready_to_execute(api)

    executed = validate_success(
        api.execute_deaccession_case(
            state["case"]["id"],
            {"execution_note": "transferred to the state museum"},
            TEST_USERS["manager_headers"],
        )
    )
    assert executed["status"] == "EXECUTED"
    assert executed["decision_ratio"] == 1.0
    assert executed["executed_at"] is not None
    assert_deaccession_case(executed)

    work = fixtures.read_artwork(api, state["artwork"]["id"])
    assert work["custody_status"] == "DEACCESSIONED"
    assert fixtures.read_site(api, state["site"]["id"])["installed_units_used"] == 0


def test_execution_withdraws_the_treatment_and_aborts_the_visit(api):
    """PRD §3.8: "Hop 2: the work's non-terminal treatment proposals are withdrawn,
    its `SCHEDULED` maintenance visits are aborted, its `PENDING` artist consultations
    lapse, and its open moral-rights notices other than the consumed one are voided,
    all as detailed in §3.3, §3.5 and §3.6."
    PRD §3.5: "When a deaccession execution makes the work's custody terminal, Cascade
    B hop 2 moves every proposal on that work sitting in `DRAFT`, `SUBMITTED`,
    `REVISION_REQUESTED` or `APPROVED` to `WITHDRAWN` with `withdraw_reason` set to
    `ARTWORK_DEACCESSIONED`."
    PRD §3.3: "Cascade A hop 3 aborts it with `abort_reason` of
    `SUPERSEDED_BY_TREATMENT` when a survey flags the work for treatment; Cascade B
    hop 2 aborts it with `abort_reason` of `ARTWORK_DEACCESSIONED` when the work
    leaves the collection."
    PRD §3.5: "They differ in exactly one respect: the `APPROVED → WITHDRAWN` branch
    also decreases the engaged conservator's `active_engagement_count` by one, because
    that engagement had already been counted, whereas the `DRAFT → WITHDRAWN`,
    `SUBMITTED → WITHDRAWN` and `REVISION_REQUESTED → WITHDRAWN` branches leave the
    count untouched."

    Design: Difficulty/transitive_cascade/deaccession_execute_withdraws_proposal_aborts_visit_and_refunds_two_allocations
    """
    state = _case_ready_to_execute(api)
    assert (
        fixtures.read_conservator(api, state["conservator"]["id"])[
            "active_engagement_count"
        ]
        == 1
    )

    validate_success(
        api.execute_deaccession_case(
            state["case"]["id"], {}, TEST_USERS["manager_headers"]
        )
    )

    proposal = fixtures.read_proposal(api, state["proposal"]["id"])
    assert proposal["status"] == "WITHDRAWN"
    assert proposal["withdraw_reason"] == "ARTWORK_DEACCESSIONED"

    visit = fixtures.read_visit(api, state["visit"]["id"])
    assert visit["status"] == "ABORTED"
    assert visit["abort_reason"] == "ARTWORK_DEACCESSIONED"

    assert (
        fixtures.read_conservator(api, state["conservator"]["id"])[
            "active_engagement_count"
        ]
        == 0
    )


def test_execution_refunds_both_allocations_with_their_own_reasons(api):
    """PRD §3.8: "Hop 3: the funding allocations held by those withdrawn proposals and
    aborted visits, in `RESERVED` or `COMMITTED`, are released."
    PRD §3.8: "Hop 4: each affected pool's `available_cents` rises by the released
    `amount_cents`."
    PRD §3.5: "All four branches behave alike in one respect: every `RESERVED` or
    `COMMITTED` allocation attached to any of them is released with `release_reason` of
    `PROPOSAL_WITHDRAWN` in hop 3, and each affected pool's `available_cents` rises in
    hop 4."
    PRD §3.3: "In both cases the abort is followed immediately by the release of any
    `RESERVED` or `COMMITTED` allocation attached to the visit, carrying
    `release_reason` of `VISIT_ABORTED`."

    Design: Difficulty/transitive_cascade/deaccession_execute_withdraws_proposal_aborts_visit_and_refunds_two_allocations
    """
    state = _case_ready_to_execute(api)

    validate_success(
        api.execute_deaccession_case(
            state["case"]["id"], {}, TEST_USERS["manager_headers"]
        )
    )

    treatment_allocation = fixtures.read_allocation(api, state["allocation"]["id"])
    assert treatment_allocation["status"] == "RELEASED"
    assert treatment_allocation["release_reason"] == "PROPOSAL_WITHDRAWN"

    visit_allocation = fixtures.read_allocation(api, state["visit_allocation"]["id"])
    assert visit_allocation["status"] == "RELEASED"
    assert visit_allocation["release_reason"] == "VISIT_ABORTED"

    # 700000 and 250000 both come back, restoring the whole authorised draw.
    assert fixtures.read_pool(api, state["pool"]["id"])["available_cents"] == 20_527_500


def _approved_case_with_an_immature_notice(api):
    """A living artist's work, a case with no target, and a notice still ripening."""
    register = fixtures.setup_register(api)
    assert register["artwork"]["moral_rights_status"] == "ACTIVE"
    notice = fixtures.setup_acknowledged_notice(
        api,
        register["artwork"]["id"],
        register["artist"]["id"],
        action_type="REMOVAL",
    )
    assert notice["status"] == "ACKNOWLEDGED"
    assert notice["earliest_action_at"].startswith("2026-10-30T00:00:00")

    payload = deaccession_case_payload(register["artwork"]["id"])
    payload.pop("disposition_target_ref")
    case = validate_success(
        api.create_deaccession_case(payload, TEST_USERS["manager_headers"]), 201
    )
    assert case["disposition"] == "TRANSFER"
    assert case["disposition_target_ref"] is None

    case = validate_success(
        api.advance_deaccession_case(case["id"], {}, TEST_USERS["manager_headers"])
    )
    fixtures.set_clock(api, case["public_comment_closes_at"])
    validate_success(
        api.advance_deaccession_case(case["id"], {}, TEST_USERS["manager_headers"])
    )
    case = fixtures.cast_ballots(api, case["id"], ["APPROVE"] * 5)
    assert case["status"] == "APPROVED"
    return register, notice, case


def test_an_immature_notice_is_reported_before_the_missing_transfer_target(api):
    """PRD §3.6: "The matching notice's `earliest_action_at` must be at or before the
    logical clock; a notice that has not yet matured yields
    `ERR_MORAL_RIGHTS_WAIT_ACTIVE`, and the action is permitted at the
    `earliest_action_at` instant exactly."
    PRD §2.8: "Maturity of that notice's waiting period —
    `ERR_MORAL_RIGHTS_WAIT_ACTIVE`."
    PRD §2.8: "A disposition target being named where one is required —
    `ERR_DISPOSITION_TARGET_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/moral_rights_wait_outranks_missing_disposition_target
    """
    register, notice, case = _approved_case_with_an_immature_notice(api)

    # The clock stands at the close of the comment period, 2026-09-15, six weeks
    # short of the notice's maturity, and the transfer has no named recipient.
    refused = api.execute_deaccession_case(
        case["id"], {"execution_note": "transfer now"}, TEST_USERS["manager_headers"]
    )
    body = validate_error(refused, ApiErrorId.ERR_MORAL_RIGHTS_WAIT_ACTIVE.value)
    assert body["error_id"] != ApiErrorId.ERR_DISPOSITION_TARGET_REQUIRED.value

    after = fixtures.read_case(api, case["id"])
    assert after["status"] == "APPROVED"
    assert after["executed_at"] is None
    assert fixtures.read_artwork(api, register["artwork"]["id"])["custody_status"] == "ON_VIEW"
    assert fixtures.read_notice(api, notice["id"])["status"] == "ACKNOWLEDGED"


def test_once_the_notice_matures_the_missing_target_surfaces(api):
    """PRD §3.8: "Where the work's `moral_rights_status` is `ACTIVE`, a matured notice
    on that work whose `action_type` is `REMOVAL` or `DESTRUCTION` must exist in
    `ACKNOWLEDGED` or `WAIT_ELAPSED` with an `earliest_action_at` at or before the
    logical clock, subject to the two failures in §3.6."
    PRD §3.8: "A `SALE` or `TRANSFER` disposition requires a non-null
    `disposition_target_ref`, failing which the request draws
    `ERR_DISPOSITION_TARGET_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/moral_rights_wait_outranks_missing_disposition_target
    """
    register, notice, case = _approved_case_with_an_immature_notice(api)
    fixtures.set_clock(api, "2026-10-30T00:00:00Z")

    # The waiting period is spent at this exact instant, so the earlier check now
    # passes and the referential failure it had been masking is finally returned.
    refused = api.execute_deaccession_case(
        case["id"], {}, TEST_USERS["manager_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_DISPOSITION_TARGET_REQUIRED.value)

    assert fixtures.read_case(api, case["id"])["status"] == "APPROVED"
    assert fixtures.read_notice(api, notice["id"])["status"] == "ACKNOWLEDGED"
    assert fixtures.read_artwork(api, register["artwork"]["id"])["custody_status"] == "ON_VIEW"


def _case_with_four_abstentions(api):
    """A case one ballot short of quorum, with nothing decisive cast yet."""
    register = fixtures.setup_register(
        api, artist={"moral_rights_waiver_on_file": True}
    )
    case = fixtures.setup_case_at_board_review(api, register["artwork"]["id"])
    assert case["status"] == "BOARD_REVIEW"
    case = fixtures.cast_ballots(api, case["id"], ["ABSTAIN"] * 4)
    assert case["status"] == "BOARD_REVIEW"
    assert case["abstain_count"] == 4
    assert case["decision_ratio"] is None
    return register, case


def test_a_quorum_of_pure_abstentions_denies_the_case_at_a_ratio_of_zero(api):
    """PRD §3.8: "Quorum is reached when the count of ballots that are not recusals —
    that is, `approve_count` plus `deny_count` plus `abstain_count` — is at least 5;
    recusals are excluded from quorum entirely."
    PRD §3.8: "At quorum, `decision_ratio` is the `approve_count` divided by the sum of
    `approve_count` and `deny_count`, and is defined as exactly 0 in the degenerate
    case where that denominator is zero because every quorum ballot was an
    abstention."
    PRD §3.8: "A ratio of 0.60 or above moves the case `BOARD_REVIEW → APPROVED`; a
    ratio below 0.60 — including that all-abstention case — moves it `BOARD_REVIEW →
    DENIED`."

    Design: Difficulty/boundary_precision_check/quorum_of_all_abstain_ballots_leaves_an_empty_decision_denominator
    """
    register, case = _case_with_four_abstentions(api)

    tallied = validate_success(
        api.cast_deaccession_ballot(
            case["id"],
            {"ballot": "ABSTAIN", "ballot_note": "no view either way"},
            make_commission_member_headers(COMMISSION_MEMBER_USER_IDS[4]),
        )
    )
    assert tallied["abstain_count"] == 5
    assert tallied["approve_count"] == 0
    assert tallied["deny_count"] == 0
    assert tallied["decision_ratio"] == 0
    assert tallied["status"] == "DENIED"
    assert len(tallied["vote_records"]) == 5

    # The empty denominator decides the case rather than failing the request, and
    # the work stays exactly where it was.
    assert fixtures.read_artwork(api, register["artwork"]["id"])["custody_status"] == "ON_VIEW"


def test_a_single_decisive_ballot_fills_the_denominator_and_approves(api):
    """PRD §3.8: "Either way the `decision_ratio` is pinned at the value that produced
    the decision."
    PRD §3.8: "Each ballot triggers an automatic tally."

    Design: Difficulty/boundary_precision_check/quorum_of_all_abstain_ballots_leaves_an_empty_decision_denominator
    """
    register, case = _case_with_four_abstentions(api)

    # The same five-ballot quorum, but one ballot is decisive: the denominator is
    # one rather than zero, so the ratio is 1.0 instead of the degenerate 0.
    tallied = validate_success(
        api.cast_deaccession_ballot(
            case["id"],
            {"ballot": "APPROVE"},
            make_commission_member_headers(COMMISSION_MEMBER_USER_IDS[4]),
        )
    )
    assert tallied["abstain_count"] == 4
    assert tallied["approve_count"] == 1
    assert tallied["deny_count"] == 0
    assert tallied["decision_ratio"] == 1.0
    assert tallied["status"] == "APPROVED"
    assert fixtures.read_artwork(api, register["artwork"]["id"])["custody_status"] == "ON_VIEW"
