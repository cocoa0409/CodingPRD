"""Validation corners, second half: terminal-state gates, pinned guard orders and
the fiscal guards that run last.

Every case here drives one refusal that the PRD fixes by name and then checks the
refusal left no trace — the bid keeps the version its withdrawal gave it, the
determination stays where the certifier found it, the round stays `DECLARED`, the
disposition counters stay at zero — and, where the specification offers a repair,
takes the same call again to show the guard was the only thing standing in the way.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_BID_NOT_WITHDRAWABLE,
    ERR_BRANCH_NOT_READY,
    ERR_BRANCH_NOT_RESCHEDULABLE,
    ERR_CERTIFICATE_ALREADY_PAID,
    ERR_DISPOSITION_EXPENSE_EXCEEDS_PROCEEDS,
    ERR_DISTRIBUTION_NOT_DECLARED,
    ERR_DISTRIBUTION_NOT_SETTLED,
    ERR_INSUFFICIENT_RECEIVERSHIP_CASH,
    ERR_LEAST_COST_TEST_NOT_EVALUATED,
    ERR_LEAST_COST_TEST_NOT_OPEN,
    ERR_NOT_LATEST_DIVIDEND_ROUND,
    ERR_HOLD_NOT_PLACED,
    ERR_OUTSIDE_REOPEN_WINDOW,
    ERR_OWNERSHIP_SHARES_UNBALANCED,
    ERR_PROVISIONAL_VARIANT_NOT_CERTIFIABLE,
    ERR_RECEIVERSHIP_NOT_TERMINABLE,
)
from test_helpers.assertions import (
    assert_account_dimensions,
    assert_certificate,
    assert_determination_amounts,
    assert_fields_equal,
    assert_instant,
    assert_institution_aggregates,
    assert_page,
    assert_summary,
    total_count,
)
from test_helpers.test_users import (
    CLAIMS_AGENT,
    CLAIMS_CERTIFIER,
    CLOSING_MANAGER,
    RECEIVERSHIP_TRUSTEE,
    RESOLUTION_ANALYST,
    make_bidder_headers,
    make_claims_agent_headers,
    make_claims_certifier_headers,
)

# The window every bid in this file claims in the physical data room.
_DATA_ROOM_START = "2026-08-06T09:00:00Z"
_DATA_ROOM_END = "2026-08-06T10:00:00Z"
_BID_DEADLINE = "2026-08-12T00:00:00Z"


def _resolution_ready_estate(client, balance_cents, **institution_kwargs):
    """A registered institution standardized up to `RESOLUTION_READY`, charter open."""
    X.open_at_setup_clock(client)
    institution = X.new_institution(client, **institution_kwargs)
    depositor = X.new_depositor(client, institution["id"])
    account = X.new_account(
        client,
        institution["id"],
        depositor["id"],
        account_number="WT-0001",
        balance_cents=balance_cents,
    )
    X.make_resolution_ready(client, institution["id"], balance_cents)
    return {
        "institution": X.get_institution(client, institution["id"]),
        "depositor": depositor,
        "account": account,
    }


def test_bid_withdraw_twice_rejected(client):
    """A bidder may pull its own bid out of the book exactly once; the second attempt on
    an already withdrawn bid is refused and the bid keeps the version its withdrawal
    gave it.

    PRD: "A bidder may withdraw its own bid while it is still at `SUBMITTED`... Withdrawal of a bid that has already been screened or awarded is refused with `ERR_BID_NOT_WITHDRAWABLE`"

    Design: Corner/validations/bid_withdraw_twice_rejected
    """
    estate = _resolution_ready_estate(
        client,
        4000000,
        cert_number="61053",
        legal_name="Withdraw Twice Bank",
        charter_state="WY",
        book_asset_value_cents=5000000,
        estimated_liquidation_recovery_cents=2000000,
    )
    institution_id = estate["institution"]["id"]
    X.open_marketing(client, institution_id, _BID_DEADLINE)
    bidder = X.new_qualified_bidder(
        client,
        legal_name="Tenor Acquirer",
        cert_number="62008",
        tier1_capital_ratio_bps=1900,
        camels_composite=2,
    )
    bid = X.new_bid(
        client,
        institution_id,
        bidder["id"],
        structure="WHOLE_BANK_PA",
        deposit_premium_bps=150,
        asset_discount_bps=1200,
        data_room_window_start=_DATA_ROOM_START,
        data_room_window_end=_DATA_ROOM_END,
    )
    assert_fields_equal(bid, {"status": "SUBMITTED", "version": 1})

    withdrawn = X.withdraw_bid(client, bid["id"], bidder["id"])
    assert_fields_equal(withdrawn, {"status": "WITHDRAWN", "version": 2})

    # `WITHDRAWN` is terminal, so the bid is no longer at `SUBMITTED`.
    validate_error(
        client.withdraw_bid(bid["id"], make_bidder_headers(bidder["id"])),
        ERR_BID_NOT_WITHDRAWABLE,
    )
    assert_fields_equal(
        X.get_bid(client, bid["id"]), {"status": "WITHDRAWN", "version": 2}
    )


def test_least_cost_award_before_evaluate_and_second_evaluate_rejected(client):
    """The least-cost test is order-locked in both directions: an award before any
    evaluation is refused, and once the evaluation has pinned its variant a second
    evaluation cannot re-score the same estate under a different one.

    PRD: "**Evaluation** requires the institution to be at `status` `CLOSED_IN_RECEIVERSHIP`, its `franchise_marketing_status` to be either `OPEN` or `CLOSED`, and its `least_cost_status` to be `NOT_STARTED`; any other combination is refused with `ERR_LEAST_COST_TEST_NOT_OPEN`."

    Design: Corner/validations/least_cost_award_before_evaluate_and_second_evaluate_rejected
    """
    estate = X.single_account_estate(
        client,
        20000000,
        account_number="OL-0001",
        cert_number="61054",
        legal_name="Order Locked Bank",
        charter_state="SD",
        book_asset_value_cents=12000000,
        estimated_liquidation_recovery_cents=6000000,
        depositor_name="Ulla Bergen",
    )
    institution_id = estate["institution"]["id"]
    X.open_marketing(client, institution_id, _BID_DEADLINE)
    bidder = X.new_qualified_bidder(
        client,
        legal_name="Umbra Acquirer",
        cert_number="62009",
        tier1_capital_ratio_bps=2000,
        camels_composite=1,
    )
    bid = X.new_bid(
        client,
        institution_id,
        bidder["id"],
        structure="WHOLE_BANK_PA",
        deposit_premium_bps=200,
        asset_discount_bps=1500,
        asset_retention_pool_cents=0,
        data_room_window_start=_DATA_ROOM_START,
        data_room_window_end=_DATA_ROOM_END,
    )

    # The award cannot run while `least_cost_status` is still `NOT_STARTED`.
    validate_error(
        client.award_least_cost_test(institution_id, RESOLUTION_ANALYST),
        ERR_LEAST_COST_TEST_NOT_EVALUATED,
    )

    X.evaluate_least_cost(client, institution_id, "EXPECTED_LOSS_SHARE")
    # No certified determination exists, so the insured share is 0 and the baseline
    # is one depositor's administrative cost alone.
    assert_institution_aggregates(
        X.get_institution(client, institution_id),
        least_cost_status="EVALUATED",
        least_cost_test_variant="EXPECTED_LOSS_SHARE",
        liquidation_baseline_cents=150000,
        conforming_bid_count=1,
    )

    # `EVALUATED` is no longer `NOT_STARTED`, so the variant cannot be swapped.
    validate_error(
        client.evaluate_least_cost_test(
            institution_id, F.evaluate_payload("RETENTION_ADJUSTED"), RESOLUTION_ANALYST
        ),
        ERR_LEAST_COST_TEST_NOT_OPEN,
    )
    assert_institution_aggregates(
        X.get_institution(client, institution_id),
        least_cost_status="EVALUATED",
        least_cost_test_variant="EXPECTED_LOSS_SHARE",
    )

    X.award_least_cost(client, institution_id)
    assert_institution_aggregates(
        X.get_institution(client, institution_id),
        least_cost_status="FAILED_ALL_BIDS",
        resolution_method="DEPOSIT_PAYOFF",
        status="RESOLUTION_COMPLETE",
    )
    # 9400000 does not beat the 150000 baseline, so the conforming bid is rejected.
    assert_fields_equal(
        X.get_bid(client, bid["id"]),
        {
            "status": "REJECTED",
            "evaluated_cost_cents": 9400000,
            "pre_fee_cost_cents": 9400000,
            "assumed_deposit_base_cents": 20000000,
        },
    )


def test_branch_reopen_before_the_award_cascade_rejected(client):
    """A branch cannot open its doors on a plan that the award has never promoted:
    reopening a freshly planned branch is refused even with the logical clock sitting
    squarely inside the declared window, and the plan is left untouched.

    PRD: "Reopening the branch for customer transition requires three things: the reopening must be at `status` `READY`, else `ERR_BRANCH_NOT_READY`"

    Design: Corner/validations/branch_reopen_before_the_award_cascade_rejected
    """
    estate = X.single_account_estate(
        client,
        4000000,
        account_number="BG-0001",
        cert_number="61055",
        legal_name="Branch Gate Bank",
        charter_state="ND",
        book_asset_value_cents=5000000,
        estimated_liquidation_recovery_cents=2000000,
        depositor_name="Vera Lindqvist",
    )
    assert estate["institution"]["least_cost_status"] == "NOT_STARTED", estate[
        "institution"
    ]
    branch = X.new_branch_reopening(
        client,
        estate["institution"]["id"],
        branch_code="BR-MAIN",
        reopen_window_start="2026-08-05T09:00:00Z",
        reopen_window_end="2026-08-05T10:00:00Z",
        staffing_headcount=6,
    )
    assert_fields_equal(branch, {"status": "PLANNED", "reschedule_count": 0})

    # Inside the window, but `READY` is conferred only by the award cascade.
    X.advance_clock(client, "2026-08-05T09:30:00Z")
    validate_error(
        client.reopen_branch(branch["id"], CLOSING_MANAGER), ERR_BRANCH_NOT_READY
    )

    unchanged = X.get_branch_reopening(client, branch["id"])
    assert_fields_equal(
        unchanged,
        {
            "status": "PLANNED",
            "reopened_at": None,
            "reschedule_count": 0,
            "version": 1,
        },
    )


def test_reopen_at_exact_window_end_rejected_and_reopened_branch_cannot_reschedule(
    client,
):
    """The reopening window is half-open, so a branch whose window has just ended cannot
    reopen at that instant; and once a branch has reopened it drops out of the
    reschedulable set, while a branch still merely ready can still be moved.

    PRD: "the logical clock must fall inside the half-open window, at or after `reopen_window_start` and strictly before `reopen_window_end`, else `ERR_OUTSIDE_REOPEN_WINDOW`"

    Design: Corner/validations/reopen_at_exact_window_end_rejected_and_reopened_branch_cannot_reschedule
    """
    estate = X.single_account_estate(
        client,
        10000000,
        account_number="HW-0001",
        cert_number="61056",
        legal_name="Half Open Window Bank",
        charter_state="AK",
        book_asset_value_cents=6000000,
        estimated_liquidation_recovery_cents=4000000,
        depositor_name="Wen Zhao",
    )
    institution_id = estate["institution"]["id"]
    # A fully insured depositor: 10000000 sits under one standard maximum.
    determination = X.certified_determination(client, estate["depositor"]["id"])
    assert_determination_amounts(determination, 10000000, 0, 10000000)

    east = X.new_branch_reopening(
        client,
        institution_id,
        branch_code="BR-EAST",
        reopen_window_start="2026-08-05T09:00:00Z",
        reopen_window_end="2026-08-05T10:00:00Z",
        staffing_headcount=5,
    )
    west = X.new_branch_reopening(
        client,
        institution_id,
        branch_code="BR-WEST",
        reopen_window_start="2026-08-05T12:00:00Z",
        reopen_window_end="2026-08-05T13:00:00Z",
        staffing_headcount=4,
    )

    # No bid was ever submitted, so the award takes the deposit-payoff branch and its
    # fourth level promotes both planned branches to `READY`.
    X.open_marketing(client, institution_id, _BID_DEADLINE)
    X.evaluate_least_cost(client, institution_id, "EXPECTED_LOSS_SHARE")
    X.award_least_cost(client, institution_id)
    assert_institution_aggregates(
        X.get_institution(client, institution_id),
        conforming_bid_count=0,
        least_cost_status="FAILED_ALL_BIDS",
        resolution_method="DEPOSIT_PAYOFF",
        liquidation_baseline_cents=6150000,
    )
    assert X.get_branch_reopening(client, east["id"])["status"] == "READY"
    assert X.get_branch_reopening(client, west["id"])["status"] == "READY"

    X.advance_clock(client, "2026-08-05T09:30:00Z")
    reopened = validate_success(client.reopen_branch(east["id"], CLOSING_MANAGER), 200)
    assert reopened["status"] == "REOPENED", reopened
    assert_instant(reopened["reopened_at"], "2026-08-05T09:30:00Z")

    # The clock now equals BR-WEST's `reopen_window_end`, which the window excludes.
    X.advance_clock(client, "2026-08-05T13:00:00Z")
    validate_error(
        client.reopen_branch(west["id"], CLOSING_MANAGER), ERR_OUTSIDE_REOPEN_WINDOW
    )
    assert X.get_branch_reopening(client, west["id"])["status"] == "READY"

    # `REOPENED` is terminal, so the reopened branch can no longer be moved.
    validate_error(
        client.reschedule_branch_reopening(
            east["id"],
            F.reschedule_payload("2026-08-06T09:00:00Z", "2026-08-06T10:00:00Z"),
            CLOSING_MANAGER,
        ),
        ERR_BRANCH_NOT_RESCHEDULABLE,
    )
    assert X.get_branch_reopening(client, east["id"])["status"] == "REOPENED"

    # A `READY` branch is still reschedulable and cycles back to `PLANNED`.
    moved = validate_success(
        client.reschedule_branch_reopening(
            west["id"],
            F.reschedule_payload("2026-08-05T13:30:00Z", "2026-08-05T14:30:00Z"),
            CLOSING_MANAGER,
        ),
        200,
    )
    assert_fields_equal(moved, {"status": "PLANNED", "reschedule_count": 1})
    assert_instant(moved["reopen_window_start"], "2026-08-05T13:30:00Z")

    # The payoff branch of the award cascade is what made both branches ready.
    assert_account_dimensions(
        X.get_account(client, estate["account"]["id"]),
        "DETERMINED",
        "NONE",
        "PAID_OUT",
        held_amount_cents=0,
    )


def test_provisional_variant_determination_cannot_be_certified(client):
    """The provisional per-account read may be prepared and reviewed but never certified;
    the only way forward is a send-back and a re-prepare under the statutory aggregate
    method, which lifts the revision round before the certification lands.

    PRD: "certification of a determination whose `method_variant` is `PER_ACCOUNT_PROVISIONAL` is refused with `ERR_PROVISIONAL_VARIANT_NOT_CERTIFIABLE`"

    Design: Corner/validations/provisional_variant_determination_cannot_be_certified
    """
    estate = X.single_account_estate(
        client,
        10000000,
        account_number="PV-0001",
        cert_number="61057",
        legal_name="Provisional Variant Bank",
        charter_state="VT",
        book_asset_value_cents=6000000,
        estimated_liquidation_recovery_cents=2000000,
        depositor_name="Xan Petrov",
    )
    agent = make_claims_agent_headers("U-AGENT-P")
    certifier = make_claims_certifier_headers("U-CERT-P")
    determination = X.open_determination(
        client, estate["depositor"]["id"], headers=agent
    )
    X.prepare(client, determination["id"], "PER_ACCOUNT_PROVISIONAL", user_id="U-AGENT-P")
    X.submit_review(client, determination["id"], user_id="U-AGENT-P")

    # The certifier differs from the preparer, so only the variant stands in the way.
    validate_error(
        client.certify_determination(determination["id"], certifier),
        ERR_PROVISIONAL_VARIANT_NOT_CERTIFIABLE,
    )
    refused = X.get_determination(client, determination["id"])
    assert_fields_equal(
        refused,
        {
            "status": "UNDER_REVIEW",
            "method_variant": "PER_ACCOUNT_PROVISIONAL",
            "certified_by_user_id": None,
        },
    )

    sent_back = X.request_revision(
        client,
        determination["id"],
        revision_reason="re-run under the statutory aggregate method",
        user_id="U-CERT-P",
    )
    assert_fields_equal(sent_back, {"status": "REVISION_REQUESTED", "revision_round": 1})

    reprepared = X.prepare(
        client, determination["id"], "AGGREGATE_BY_CATEGORY", user_id="U-AGENT-P"
    )
    assert reprepared["status"] == "PREPARED", reprepared
    assert reprepared["method_variant"] == "AGGREGATE_BY_CATEGORY", reprepared
    assert_determination_amounts(reprepared, 10000000, 0, 10000000)

    X.submit_review(client, determination["id"], user_id="U-AGENT-P")
    certified = X.certify(client, determination["id"], user_id="U-CERT-P")
    assert_fields_equal(
        certified, {"status": "CERTIFIED", "certified_by_user_id": "U-CERT-P"}
    )
    assert_instant(certified["certified_at"], C.SETUP_CLOCK)


def test_prepare_rejected_when_joint_co_owner_shares_do_not_sum_to_ten_thousand(client):
    """A joint account whose co-owner shares fall short of the whole cannot be run through
    the insurance analysis, even though each individual share is inside its declared
    range; supplying the missing share makes the identical preparation succeed.

    PRD: "every joint account contributing to this depositor must carry co-owner interests whose `designated_share_bps` sum to exactly 10000, else `ERR_OWNERSHIP_SHARES_UNBALANCED`"

    Design: Corner/validations/prepare_rejected_when_joint_co_owner_shares_do_not_sum_to_ten_thousand
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61058",
        legal_name="Unbalanced Shares Bank",
        charter_state="NH",
        book_asset_value_cents=6000000,
        estimated_liquidation_recovery_cents=2000000,
    )
    yara = X.new_depositor(
        client, institution["id"], tin_hash="TIN-US-1", legal_name="Yara Bello"
    )
    zeno = X.new_depositor(
        client, institution["id"], tin_hash="TIN-US-2", legal_name="Zeno Castelli"
    )
    aiko = X.new_depositor(
        client, institution["id"], tin_hash="TIN-US-3", legal_name="Aiko Tanaka"
    )
    account = X.new_account(
        client,
        institution["id"],
        yara["id"],
        account_number="JN-0001",
        ownership_category="JOINT",
        balance_cents=8000000,
    )
    X.new_interest(client, account["id"], yara["id"], "CO_OWNER", 4000)
    X.new_interest(client, account["id"], zeno["id"], "CO_OWNER", 5000)
    X.make_resolution_ready(client, institution["id"], 8000000)
    X.close_charter(client, institution["id"])

    agent = make_claims_agent_headers("U-AGENT-Q")
    determination = X.open_determination(client, yara["id"], headers=agent)

    # 4000 + 5000 is 9000 bps, so the co-owner set does not account for the account.
    validate_error(
        client.prepare_determination(
            determination["id"], F.prepare_payload("AGGREGATE_BY_CATEGORY"), agent
        ),
        ERR_OWNERSHIP_SHARES_UNBALANCED,
    )
    untouched = X.get_determination(client, determination["id"])
    assert_fields_equal(
        untouched,
        {
            "status": "DRAFT",
            "prepared_by_user_id": None,
            "attributed_total_cents": 0,
        },
    )

    added = X.new_interest(client, account["id"], aiko["id"], "CO_OWNER", 1000)
    assert added["designated_share_bps"] == 1000, added

    prepared = X.prepare(
        client, determination["id"], "AGGREGATE_BY_CATEGORY", user_id="U-AGENT-Q"
    )
    assert prepared["status"] == "PREPARED", prepared
    # Yara's joint share is 8000000 * 4000 / 10000 rounded half up.
    assert_determination_amounts(prepared, 3200000, 0, 3200000)


def test_release_hold_rejected_when_no_hold_was_ever_placed(client):
    """A fully insured depositor's certification never restrains a cent, so there is no
    hold to release on that depositor's account — and the missing hold is what the
    release reports, ahead of the acknowledgement the depositor also never gave.

    PRD: "A `ClaimsCertifier` releases the hold on a single account, and two guards apply in order: the account's `hold_status` must be `HELD`, else `ERR_HOLD_NOT_PLACED`"

    Design: Corner/validations/release_hold_rejected_when_no_hold_was_ever_placed
    """
    estate = X.single_account_estate(
        client,
        10000000,
        account_number="NH-0001",
        cert_number="61059",
        legal_name="No Hold Bank",
        charter_state="ME",
        book_asset_value_cents=6000000,
        estimated_liquidation_recovery_cents=2000000,
        depositor_name="Bruno Alves",
    )
    determination = X.certified_determination(client, estate["depositor"]["id"])
    assert_determination_amounts(determination, 10000000, 0, 10000000)

    validate_error(
        client.release_hold(estate["account"]["id"], CLAIMS_CERTIFIER),
        ERR_HOLD_NOT_PLACED,
    )

    assert_account_dimensions(
        X.get_account(client, estate["account"]["id"]),
        "DETERMINED",
        "NONE",
        "PENDING",
        held_amount_cents=0,
    )
    # The notice still went out, under the fully insured template, unacknowledged.
    assert_fields_equal(
        X.get_depositor(client, estate["depositor"]["id"]),
        {"notice_status": "SENT", "notice_template_code": "FULLY_INSURED"},
    )
    # The conditional cascade skipped the certificate level entirely.
    assert (
        total_count(
            client.list_certificates(
                CLAIMS_CERTIFIER,
                params={"depositor_record_id": estate["depositor"]["id"]},
            )
        )
        == 0
    )


def _partially_uninsured_estate_with_cash(
    client, gross_proceeds_cents, account_number, depositor_name, **institution_kwargs
):
    """A certified 30000000 single-ownership depositor plus receivership cash.

    One standard maximum leaves 5000000 cents uninsured, so the certification issues
    one certificate of face 5000000 and holds the whole remainder on the account.
    """
    estate = X.single_account_estate(
        client,
        30000000,
        account_number=account_number,
        depositor_name=depositor_name,
        **institution_kwargs,
    )
    estate["determination"] = X.certified_determination(client, estate["depositor"]["id"])
    assert_determination_amounts(estate["determination"], 25000000, 5000000, 30000000)
    estate["certificate"] = X.certificate_for(client, estate["determination"]["id"])
    assert_certificate(estate["certificate"], "ISSUED", 5000000, 0)
    X.post_proceeds(
        client,
        estate["institution"]["id"],
        gross_proceeds_cents=gross_proceeds_cents,
        disposition_expense_cents=0,
    )
    return estate


def test_supersede_rejected_after_the_certificate_has_taken_a_dividend(client):
    """A certified position stays revisable only while nothing has been paid on the claim it
    produced: once a dividend has landed on the receivership certificate, opening a
    replacement determination is refused and nothing about the old position moves.

    PRD: "if that certificate's `cumulative_dividends_cents` is greater than zero, the opening is refused with `ERR_CERTIFICATE_ALREADY_PAID`, because money has already moved against the claim and the position can no longer be quietly rewritten."

    Design: Corner/validations/supersede_rejected_after_the_certificate_has_taken_a_dividend
    """
    estate = _partially_uninsured_estate_with_cash(
        client,
        10000000,
        "PC-0001",
        "Celia Duarte",
        cert_number="61060",
        legal_name="Paid Certificate Bank",
        charter_state="RI",
        book_asset_value_cents=40000000,
        estimated_liquidation_recovery_cents=15000000,
    )
    institution_id = estate["institution"]["id"]
    depositor_id = estate["depositor"]["id"]

    # 5000000 of face at 2000 bps pays 1000000 cents against 10000000 of cash.
    X.settled_round(client, institution_id, "GENERAL_UNSECURED", 2000)
    assert_certificate(
        X.get_certificate(client, estate["certificate"]["id"]),
        "PARTIALLY_PAID",
        5000000,
        1000000,
    )

    observed_version = X.depositor_version(client, depositor_id)
    validate_error(
        client.create_determination(
            F.determination_payload(
                depositor_id,
                observed_version,
                revision_reason="late trust documentation surfaced",
            ),
            CLAIMS_AGENT,
        ),
        ERR_CERTIFICATE_ALREADY_PAID,
    )

    # No supersession took place, so the refused opening left the OCC token valid.
    assert_fields_equal(
        X.get_determination(client, estate["determination"]["id"]),
        {"status": "CERTIFIED", "revision_round": 0},
    )
    assert X.depositor_version(client, depositor_id) == observed_version
    rows, _ = assert_page(
        client.list_certificates(
            CLAIMS_AGENT, params={"depositor_record_id": depositor_id}
        ),
        expected_total=1,
    )
    assert_certificate(rows[0], "PARTIALLY_PAID", 5000000, 1000000)


def test_dividend_settle_twice_and_void_of_a_declared_round_rejected(client):
    """Settlement and voiding guard opposite ends of the same two-step round: an already
    settled round cannot be settled again and must not pay the claim twice, and a round
    that has only been declared has nothing to reverse.

    PRD: "The round must be at `status` `DECLARED`, else `ERR_DISTRIBUTION_NOT_DECLARED`... Only a settled round may be voided — otherwise `ERR_DISTRIBUTION_NOT_SETTLED`"

    Design: Corner/validations/dividend_settle_twice_and_void_of_a_declared_round_rejected
    """
    estate = _partially_uninsured_estate_with_cash(
        client,
        10000000,
        "RG-0001",
        "Dara Okonjo",
        cert_number="61061",
        legal_name="Round Gate Bank",
        charter_state="DE",
        book_asset_value_cents=40000000,
        estimated_liquidation_recovery_cents=15000000,
    )
    institution_id = estate["institution"]["id"]
    round_one = X.declare_dividend(client, institution_id, "GENERAL_UNSECURED", 2000)

    settled = X.settle_dividend(client, round_one["id"])
    assert_fields_equal(
        settled,
        {"status": "SETTLED", "total_distributed_cents": 1000000, "certificate_count": 1},
    )

    validate_error(
        client.settle_dividend(round_one["id"], RECEIVERSHIP_TRUSTEE),
        ERR_DISTRIBUTION_NOT_DECLARED,
    )
    assert_institution_aggregates(
        X.get_institution(client, institution_id),
        receivership_cash_cents=9000000,
        dividend_round_count=1,
    )

    round_two = X.declare_dividend(client, institution_id, "GENERAL_UNSECURED", 1000)
    assert_fields_equal(round_two, {"status": "DECLARED", "distribution_round": 2})

    # Nothing has been paid out of round two yet, so there is nothing to reverse.
    validate_error(
        client.void_dividend(round_two["id"], RECEIVERSHIP_TRUSTEE),
        ERR_DISTRIBUTION_NOT_SETTLED,
    )

    # The refused second settlement paid the certificate nothing extra.
    rows, _ = assert_page(
        client.list_certificates(
            RECEIVERSHIP_TRUSTEE,
            params={"depositor_record_id": estate["depositor"]["id"]},
        ),
        expected_total=1,
    )
    assert_certificate(rows[0], "PARTIALLY_PAID", 5000000, 1000000)


def test_void_of_an_earlier_settled_round_rejected(client):
    """Reversal is last-in-first-out: with two rounds settled, only the latest may be
    voided, and voiding it hands back exactly the cents that round paid while the
    earlier payment survives on the claim.

    PRD: "only the round bearing the highest `distribution_round` among the institution's settled rounds, so an attempt on an earlier round is refused with `ERR_NOT_LATEST_DIVIDEND_ROUND`"

    Design: Corner/validations/void_of_an_earlier_settled_round_rejected
    """
    estate = _partially_uninsured_estate_with_cash(
        client,
        10000000,
        "LR-0001",
        "Elif Demir",
        cert_number="61062",
        legal_name="Lifo Reversal Bank",
        charter_state="MD",
        book_asset_value_cents=40000000,
        estimated_liquidation_recovery_cents=15000000,
    )
    institution_id = estate["institution"]["id"]
    round_one = X.settled_round(client, institution_id, "GENERAL_UNSECURED", 2000)
    round_two = X.settled_round(client, institution_id, "GENERAL_UNSECURED", 2000)
    assert_certificate(
        X.get_certificate(client, estate["certificate"]["id"]),
        "PARTIALLY_PAID",
        5000000,
        2000000,
        1000000,
        2,
    )

    validate_error(
        client.void_dividend(round_one["id"], RECEIVERSHIP_TRUSTEE),
        ERR_NOT_LATEST_DIVIDEND_ROUND,
    )

    voided = X.void_dividend(client, round_two["id"])
    # The distributed figure is retained for audit rather than zeroed.
    assert_fields_equal(
        voided, {"status": "VOIDED", "total_distributed_cents": 1000000}
    )

    # Each certificate remembers only its most recent payment, so the reversal is exact.
    rows, _ = assert_page(
        client.list_certificates(
            RECEIVERSHIP_TRUSTEE,
            params={"depositor_record_id": estate["depositor"]["id"]},
        ),
        expected_total=1,
    )
    assert_certificate(rows[0], "PARTIALLY_PAID", 5000000, 1000000, 0, 0)

    assert_summary(
        X.insurance_summary(client, institution_id),
        receivership_cash_cents=9000000,
        dividends_paid_cents=1000000,
        cash_conservation_delta_cents=0,
    )


def test_settle_rejected_one_cent_short_then_accepted_at_exactly_available_cash(client):
    """A dividend round may spend every cent the estate holds but not one more: a payout
    a single cent above available cash is refused and leaves the round declared, while
    the same payout against exactly that much cash settles and drains the estate.

    PRD: "a total exceeding available cash is refused with `ERR_INSUFFICIENT_RECEIVERSHIP_CASH` and HTTP 402, and a total exactly equal to available cash is allowed"

    Design: Corner/validations/settle_rejected_one_cent_short_then_accepted_at_exactly_available_cash
    """
    estate = _partially_uninsured_estate_with_cash(
        client,
        999999,
        "OC-0001",
        "Efe Aydin",
        cert_number="61063",
        legal_name="One Cent Short Bank",
        charter_state="CT",
        book_asset_value_cents=40000000,
        estimated_liquidation_recovery_cents=15000000,
    )
    institution_id = estate["institution"]["id"]
    # 5000000 of face at 2000 bps wants 1000000 cents against 999999 on hand.
    declared = X.declare_dividend(client, institution_id, "GENERAL_UNSECURED", 2000)

    validate_error(
        client.settle_dividend(declared["id"], RECEIVERSHIP_TRUSTEE),
        ERR_INSUFFICIENT_RECEIVERSHIP_CASH,
    )
    assert_fields_equal(
        X.get_dividend(client, declared["id"]),
        {"status": "DECLARED", "total_distributed_cents": 0, "settled_at": None},
    )

    # One more cent of proceeds makes the payout exactly equal to available cash.
    X.post_proceeds(
        client, institution_id, gross_proceeds_cents=1, disposition_expense_cents=0
    )
    assert_institution_aggregates(
        X.get_institution(client, institution_id), receivership_cash_cents=1000000
    )

    settled = X.settle_dividend(client, declared["id"])
    assert_fields_equal(
        settled,
        {"status": "SETTLED", "total_distributed_cents": 1000000, "certificate_count": 1},
    )
    assert_summary(
        X.insurance_summary(client, institution_id),
        receivership_cash_cents=0,
        dividends_paid_cents=1000000,
        gross_disposition_proceeds_cents=1000000,
        cash_conservation_delta_cents=0,
    )


def test_disposition_expense_above_gross_proceeds_rejected(client):
    """A single asset-pool disposition may break even but never lose money on the books:
    an expense above the gross proceeds of the same posting is refused and books nothing,
    while an expense exactly equal to the proceeds is accepted.

    PRD: "a posting whose `disposition_expense_cents` is greater than its `gross_proceeds_cents` is refused with `ERR_DISPOSITION_EXPENSE_EXCEEDS_PROCEEDS`"

    Design: Corner/validations/disposition_expense_above_gross_proceeds_rejected
    """
    estate = X.single_account_estate(
        client,
        4000000,
        account_number="BE-0001",
        cert_number="61064",
        legal_name="Break Even Bank",
        charter_state="WV",
        book_asset_value_cents=5000000,
        estimated_liquidation_recovery_cents=2000000,
        depositor_name="Faye Nakamura",
    )
    institution_id = estate["institution"]["id"]

    validate_error(
        client.post_receivership_proceeds(
            institution_id,
            F.proceeds_payload(
                asset_pool_code="POOL-BE-A",
                gross_proceeds_cents=1000000,
                disposition_expense_cents=1000001,
            ),
            RECEIVERSHIP_TRUSTEE,
        ),
        ERR_DISPOSITION_EXPENSE_EXCEEDS_PROCEEDS,
    )
    # The rejected posting left no trace on any of the three running totals.
    assert_summary(
        X.insurance_summary(client, institution_id),
        gross_disposition_proceeds_cents=0,
        disposition_expense_total_cents=0,
        receivership_cash_cents=0,
    )

    X.post_proceeds(
        client,
        institution_id,
        asset_pool_code="POOL-BE-B",
        gross_proceeds_cents=1000000,
        disposition_expense_cents=1000000,
    )
    assert_summary(
        X.insurance_summary(client, institution_id),
        gross_disposition_proceeds_cents=1000000,
        disposition_expense_total_cents=1000000,
        receivership_cash_cents=0,
        cash_conservation_delta_cents=0,
    )


def test_terminate_receivership_rejected_while_a_declared_round_remains(client):
    """Reaching a completed resolution is not enough to close the estate: an unsettled
    declared dividend round blocks termination, and only once that round has paid the
    insurer's subrogated claim does the receivership reach its terminal state.

    PRD: "The institution must be at `status` `RESOLUTION_COMPLETE`, no dividend round for the institution may still be sitting at `DECLARED`, and no deposit account of the institution may still be at `hold_status` `HELD`; any of these unmet yields `ERR_RECEIVERSHIP_NOT_TERMINABLE`."

    Design: Corner/validations/terminate_receivership_rejected_while_a_declared_round_remains
    """
    estate = X.single_account_estate(
        client,
        20000000,
        account_number="TG-0001",
        cert_number="61065",
        legal_name="Terminal Gate Bank",
        charter_state="HI",
        book_asset_value_cents=12000000,
        estimated_liquidation_recovery_cents=6000000,
        depositor_name="Fumiko Sato",
    )
    institution_id = estate["institution"]["id"]
    # Fully insured, so no hold survives to block the termination later.
    determination = X.certified_determination(client, estate["depositor"]["id"])
    assert_determination_amounts(determination, 20000000, 0, 20000000)

    X.open_marketing(client, institution_id, _BID_DEADLINE)
    bidder = X.new_qualified_bidder(
        client,
        legal_name="Vireo Acquirer",
        cert_number="62010",
        tier1_capital_ratio_bps=2100,
        camels_composite=1,
    )
    bid = X.new_bid(
        client,
        institution_id,
        bidder["id"],
        structure="WHOLE_BANK_PA",
        deposit_premium_bps=200,
        asset_discount_bps=1500,
        asset_retention_pool_cents=0,
        data_room_window_start=_DATA_ROOM_START,
        data_room_window_end=_DATA_ROOM_END,
    )
    X.evaluate_least_cost(client, institution_id, "EXPECTED_LOSS_SHARE")
    X.award_least_cost(client, institution_id)
    # 9400000 beats the 14150000 baseline, so the franchise is sold.
    assert_fields_equal(
        X.get_bid(client, bid["id"]),
        {"status": "WINNER", "evaluated_cost_cents": 9400000},
    )
    assert_account_dimensions(
        X.get_account(client, estate["account"]["id"]),
        "DETERMINED",
        "NONE",
        "TRANSFERRED",
    )

    X.post_proceeds(
        client, institution_id, gross_proceeds_cents=3000000, disposition_expense_cents=0
    )
    declared = X.declare_dividend(client, institution_id, "INSURED_SUBROGATION", 1000)

    validate_error(
        client.terminate_receivership(institution_id, RECEIVERSHIP_TRUSTEE),
        ERR_RECEIVERSHIP_NOT_TERMINABLE,
    )
    assert X.get_institution(client, institution_id)["status"] == "RESOLUTION_COMPLETE"

    # The subrogation round pays the insurance fund, touching no certificate.
    settled = X.settle_dividend(client, declared["id"])
    assert_fields_equal(
        settled,
        {"status": "SETTLED", "total_distributed_cents": 2000000, "certificate_count": 0},
    )

    terminated = validate_success(
        client.terminate_receivership(institution_id, RECEIVERSHIP_TRUSTEE), 200
    )
    assert_fields_equal(
        terminated,
        {
            "status": "RECEIVERSHIP_TERMINATED",
            "least_cost_status": "AWARDED",
            "resolution_method": "WHOLE_BANK_PA",
        },
    )
    assert_summary(
        X.insurance_summary(client, institution_id),
        receivership_cash_cents=1000000,
        dividends_paid_cents=2000000,
        cash_conservation_delta_cents=0,
    )
