"""Cascades that travel several levels from a single request.

Certification reaches from the determination through the depositor's accounts into
their holds, a new receivership certificate and a queued notice; the award reaches
from the winning bid through the losing bids into the accounts and the branch
plan.  Every level is applied inside the same request, so a read taken straight
afterwards observes all of them.
"""
from test_helpers import constants as C
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_account_dimensions,
    assert_certificate,
    assert_fields_equal,
    assert_instant,
)


def _farid_estate(client):
    return X.pooled_estate(
        client,
        cert_number="34571",
        legal_name="Willapa Coast Bank",
        depositor_name="Farid Haddad",
    )


# ---------------------------------------------------------------------------
# Certification: determination, accounts, holds, certificate, notice
# ---------------------------------------------------------------------------
def test_certify_cascade_places_holds_summing_to_the_uninsured_amount(client):
    """One certification determines both accounts and restrains 2758622 plus 1241379
    cents, which is exactly the 4000001 uninsured.

    PRD: "**Third**, because those accounts are now determined and the determination shows an `uninsured_amount_cents` greater than zero, the uninsured hold allocation described below writes each account's `held_amount_cents` and flips `hold_status` from `NONE` to `HELD` on every account whose allocated hold is greater than zero; an account allocated exactly zero cents stays at `hold_status` `NONE` with `held_amount_cents` zero."

    Design: Difficulty/transitive_cascade/certify_cascade_five_levels_determination_to_notice
    """
    estate = _farid_estate(client)
    certified = X.certified_determination(client, estate["depositor"]["id"])

    assert certified["status"] == "CERTIFIED"
    assert_instant(certified["certified_at"], C.SETUP_CLOCK)

    account_a = X.get_account(client, estate["account_a"]["id"])
    account_b = X.get_account(client, estate["account_b"]["id"])
    assert_account_dimensions(
        account_a,
        "DETERMINED",
        "HELD",
        "PENDING",
        held_amount_cents=C.HOLD_ACCOUNT_A_CENTS,
    )
    assert_account_dimensions(
        account_b,
        "DETERMINED",
        "HELD",
        "PENDING",
        held_amount_cents=C.HOLD_ACCOUNT_B_CENTS,
    )
    assert (
        account_a["held_amount_cents"] + account_b["held_amount_cents"]
        == certified["uninsured_amount_cents"]
    )

    certificate = X.certificate_for(client, certified["id"])
    assert_certificate(
        certificate,
        "ISSUED",
        C.CERT_FACE_LARGE_CENTS,
        cumulative_dividends_cents=0,
        last_dividend_amount_cents=0,
        last_dividend_round=0,
    )
    assert_instant(certificate["issued_at"], C.SETUP_CLOCK)


def test_certify_cascade_queues_the_partially_uninsured_notice(client):
    """Because a certificate was issued, the depositor's notice goes out under the
    `PARTIALLY_UNINSURED` template, and both conservation deltas stay at zero.

    PRD: "**Fifth**, because the certificate was issued, the depositor record's `notice_status` flips `PENDING` → `SENT` with `notice_template_code` `PARTIALLY_UNINSURED` and `notice_sent_at` stamped from the logical clock."

    Design: Difficulty/transitive_cascade/certify_cascade_five_levels_determination_to_notice
    """
    estate = _farid_estate(client)
    X.certified_determination(client, estate["depositor"]["id"])

    depositor = X.get_depositor(client, estate["depositor"]["id"])
    assert_fields_equal(
        depositor,
        {
            "notice_status": "SENT",
            "notice_template_code": "PARTIALLY_UNINSURED",
            "certified_insured_cents": C.POOLED_INSURED_CENTS,
            "certified_uninsured_cents": C.POOLED_UNINSURED_CENTS,
        },
    )
    assert_instant(depositor["notice_sent_at"], C.SETUP_CLOCK)
    assert depositor["acknowledged_at"] is None

    summary = X.insurance_summary(client, estate["institution"]["id"])
    assert_fields_equal(
        summary,
        {
            "conservation_delta_cents": 0,
            "aggregate_insured_cents": C.POOLED_INSURED_CENTS,
            "aggregate_certificate_face_cents": C.CERT_FACE_LARGE_CENTS,
            "uninsured_claim_count": 1,
            "held_amount_total_cents": C.POOLED_UNINSURED_CENTS,
        },
    )


# ---------------------------------------------------------------------------
# The award: winner, losing bid, accounts, branch plan
# ---------------------------------------------------------------------------
# Insured share 25000000 * 10000 / 29000001 truncated downward, the subrogated
# recovery 18000000 * 8620 / 10000, and the resulting baseline.
INSURED_SHARE_BPS = 8620
SUBROGATED_RECOVERY_CENTS = 15516000
LIQUIDATION_BASELINE_CENTS = 9634000

BID_A_EVALUATED_CENTS = 5630001
BID_C_EVALUATED_CENTS = 7397153

BRANCH_WINDOW_START = "2026-08-05T09:00:00Z"
BRANCH_WINDOW_END = "2026-08-05T17:00:00Z"


def _evaluated_gita_book(client):
    """A certified, hold-free estate carrying two conforming bids and one branch plan.

    Both of Gita's accounts are `DETERMINED` with their holds `RELEASED`, so both are
    eligible for the transition cascade; the branch reopening sits at `PLANNED`.
    """
    estate = X.certified_pooled_estate(
        client,
        cert_number="34572",
        legal_name="Deschutes Valley Bank",
        charter_state="OR",
        depositor_name="Gita Raman",
    )
    institution_id = estate["institution"]["id"]
    X.acknowledge_notice(client, estate["depositor"]["id"])
    X.release_hold(client, estate["account_a"]["id"])
    X.release_hold(client, estate["account_b"]["id"])

    estate["branch"] = X.new_branch_reopening(
        client,
        institution_id,
        branch_code="BR-01",
        reopen_window_start=BRANCH_WINDOW_START,
        reopen_window_end=BRANCH_WINDOW_END,
        staffing_headcount=12,
    )

    X.open_marketing(client, institution_id)
    bidder_a = X.new_qualified_bidder(
        client,
        legal_name="Columbia River National",
        cert_number="52001",
        tier1_capital_ratio_bps=1600,
        camels_composite=1,
    )
    bidder_c = X.new_qualified_bidder(
        client,
        legal_name="Cascade Union Bank",
        cert_number="52002",
        tier1_capital_ratio_bps=1400,
        camels_composite=2,
    )
    estate["bid_a"] = X.new_bid(
        client,
        institution_id,
        bidder_a["id"],
        structure="WHOLE_BANK_PA",
        deposit_premium_bps=300,
        asset_discount_bps=1000,
        loss_share_pct_bps=0,
        asset_retention_pool_cents=0,
        data_room_window_start="2026-09-01T09:00:00Z",
        data_room_window_end="2026-09-01T12:00:00Z",
    )
    estate["bid_c"] = X.new_bid(
        client,
        institution_id,
        bidder_c["id"],
        structure="LOSS_SHARE_PA",
        deposit_premium_bps=1379,
        asset_discount_bps=1000,
        loss_share_pct_bps=6000,
        asset_retention_pool_cents=2000000,
        data_room_window_start="2026-09-02T09:00:00Z",
        data_room_window_end="2026-09-02T12:00:00Z",
    )
    X.evaluate_least_cost(client, institution_id, "EXPECTED_LOSS_SHARE")
    estate["institution"] = X.get_institution(client, institution_id)
    return estate


def test_liquidation_baseline_credits_the_subrogated_recovery_at_the_insured_share(client):
    """Evaluating the least-cost test prices the payoff alternative at 9634000 cents:
    the 25000000 certified insured total plus one depositor's administrative cost,
    less the 18000000 estimated recovery taken at the 8620 bps insured share.

    PRD: "Take the institution's `aggregate_insured_cents`, multiply by 10000, divide by its `total_deposit_balance_cents` and truncate downward to obtain the insured share in basis points"

    Design: Difficulty/transitive_cascade/award_cascade_four_levels_bid_to_branch_ready
    """
    estate = _evaluated_gita_book(client)

    institution = estate["institution"]
    assert_fields_equal(
        institution,
        {
            "least_cost_status": "EVALUATED",
            "conforming_bid_count": 2,
            "liquidation_baseline_cents": LIQUIDATION_BASELINE_CENTS,
            "aggregate_insured_cents": C.POOLED_INSURED_CENTS,
            "total_deposit_balance_cents": C.POOLED_ATTRIBUTED_CENTS,
            "depositor_record_count": 1,
        },
    )
    assert (
        institution["aggregate_insured_cents"]
        + C.ADMIN_COST_PER_DEPOSITOR_CENTS * institution["depositor_record_count"]
        - SUBROGATED_RECOVERY_CENTS
        == LIQUIDATION_BASELINE_CENTS
    )
    assert C.POOLED_INSURED_CENTS * C.BPS_WHOLE // C.POOLED_ATTRIBUTED_CENTS == INSURED_SHARE_BPS

    # Nothing has been awarded yet, so the branch plan is untouched.
    branch = X.get_branch_reopening(client, estate["branch"]["id"])
    assert_fields_equal(branch, {"status": "PLANNED", "reschedule_count": 0})
    assert branch["reopened_at"] is None


def test_award_cascade_rejects_the_loser_transfers_accounts_and_readies_the_branch(client):
    """Awarding the cheaper 5630001-cent whole-bank bid rejects the 7397153-cent
    loss-share bid, transfers both hold-free determined accounts, and turns the
    planned branch reopening ready.

    PRD: "**Third**, because `resolution_method` is now pinned to a purchase-and-assumption structure, every deposit account of the institution whose `insurance_status` is `DETERMINED` and whose `hold_status` is either `NONE` or `RELEASED` moves `transition_status` `PENDING` → `TRANSFERRED`"

    Design: Difficulty/transitive_cascade/award_cascade_four_levels_bid_to_branch_ready
    """
    estate = _evaluated_gita_book(client)
    institution_id = estate["institution"]["id"]

    awarded = X.award_least_cost(client, institution_id)

    assert_fields_equal(
        awarded,
        {
            "least_cost_status": "AWARDED",
            "resolution_method": "WHOLE_BANK_PA",
            "status": "RESOLUTION_COMPLETE",
        },
    )

    bid_a = X.get_bid(client, estate["bid_a"]["id"])
    bid_c = X.get_bid(client, estate["bid_c"]["id"])
    assert_fields_equal(
        bid_a, {"status": "WINNER", "evaluated_cost_cents": BID_A_EVALUATED_CENTS}
    )
    assert bid_a["evaluated_cost_cents"] < LIQUIDATION_BASELINE_CENTS
    # The loser is rejected because a winner now exists, not because it was screened out.
    assert_fields_equal(
        bid_c, {"status": "REJECTED", "evaluated_cost_cents": BID_C_EVALUATED_CENTS}
    )
    assert bid_c["evaluated_cost_cents"] < LIQUIDATION_BASELINE_CENTS

    for account_id in (estate["account_a"]["id"], estate["account_b"]["id"]):
        assert_account_dimensions(
            X.get_account(client, account_id), "DETERMINED", "RELEASED", "TRANSFERRED"
        )

    branch = X.get_branch_reopening(client, estate["branch"]["id"])
    assert_fields_equal(branch, {"status": "READY", "reschedule_count": 0})
    assert branch["reopened_at"] is None
