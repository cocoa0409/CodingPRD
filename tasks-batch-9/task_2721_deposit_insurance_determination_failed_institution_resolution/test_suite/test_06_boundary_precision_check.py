"""Comparisons that must be exact at the boundary itself.

The insured position is capped by the standard maximum with a "smaller of" rule, so
a depositor holding exactly the maximum is fully insured and only the depositor one
cent above it owes anything; the award compares a bid's evaluated cost against the
liquidation baseline strictly, so a bid that merely ties the baseline is not
least-costly and cannot win.
"""
from test_helpers import constants as C
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_account_dimensions,
    assert_certificate,
    assert_determination_amounts,
    assert_fields_equal,
    assert_page,
    total_count,
)
from test_helpers.test_users import CLAIMS_CERTIFIER

# Three positions one cent apart across the standard maximum of 25000000 cents.
BELOW_CAP_CENTS = 24999999
AT_CAP_CENTS = 25000000
ABOVE_CAP_CENTS = 25000001
BOUNDARY_BOOKED_TOTAL_CENTS = BELOW_CAP_CENTS + AT_CAP_CENTS + ABOVE_CAP_CENTS


def _certificate_count(client, depositor_record_id):
    return total_count(
        client.list_certificates(
            CLAIMS_CERTIFIER, params={"depositor_record_id": depositor_record_id}
        )
    )


def _boundary_estate(client):
    """Three depositors of 24999999, 25000000 and 25000001 cents, each certified.

    Every account is a single-ownership account of one depositor, so each pooled
    bucket is exactly that account's balance against one standard maximum.
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="34576",
        legal_name="Clearwater Boundary Bank",
        charter_state="ID",
    )
    institution_id = institution["id"]

    people = {}
    for name, balance, account_number, opened_at in (
        ("below", BELOW_CAP_CENTS, "I-0001", "2024-03-01T00:00:00Z"),
        ("at", AT_CAP_CENTS, "J-0001", "2024-03-02T00:00:00Z"),
        ("above", ABOVE_CAP_CENTS, "K-0001", "2024-03-03T00:00:00Z"),
    ):
        depositor = X.new_depositor(client, institution_id, legal_name=f"Depositor {name}")
        account = X.new_account(
            client,
            institution_id,
            depositor["id"],
            account_number=account_number,
            ownership_category="SINGLE",
            balance_cents=balance,
            accrued_interest_cents=0,
            opened_at=opened_at,
        )
        people[name] = {"depositor": depositor, "account": account, "balance": balance}

    X.make_resolution_ready(client, institution_id, BOUNDARY_BOOKED_TOTAL_CENTS)
    X.close_charter(client, institution_id)

    for person in people.values():
        person["determination"] = X.certified_determination(
            client, person["depositor"]["id"]
        )
    people["institution_id"] = institution_id
    return people


def test_a_position_exactly_at_the_standard_maximum_is_fully_insured(client):
    """At exactly 25000000 cents the depositor owes nothing uninsured and behaves like
    the depositor one cent below: no hold, no receivership certificate, and a fully
    insured notice.

    PRD: "When the determination's `uninsured_amount_cents` is exactly zero, the third and fourth levels are skipped entirely — no account is touched, every `hold_status` stays `NONE`, and no receivership certificate is created at all — while the fifth level still runs, sending the notice with `notice_template_code` `FULLY_INSURED` instead."

    Design: Difficulty/boundary_precision_check/smdia_cap_boundary_below_at_and_above_on_certify
    """
    estate = _boundary_estate(client)

    for key, balance in (("below", BELOW_CAP_CENTS), ("at", AT_CAP_CENTS)):
        person = estate[key]
        assert_determination_amounts(person["determination"], balance, 0, balance)
        assert_account_dimensions(
            X.get_account(client, person["account"]["id"]),
            "DETERMINED",
            "NONE",
            "PENDING",
            held_amount_cents=0,
            attributed_amount_cents=balance,
        )
        assert _certificate_count(client, person["depositor"]["id"]) == 0
        assert_fields_equal(
            X.get_depositor(client, person["depositor"]["id"]),
            {
                "notice_status": "SENT",
                "notice_template_code": "FULLY_INSURED",
                "certified_insured_cents": balance,
                "certified_uninsured_cents": 0,
            },
        )

    # Equality is fully insured, so the two positions differ only in their amounts.
    assert estate["at"]["determination"]["insured_amount_cents"] == C.SMDIA_CENTS
    assert estate["at"]["determination"]["uninsured_amount_cents"] == 0


def test_one_cent_above_the_standard_maximum_owes_exactly_one_cent(client):
    """At 25000001 cents the insured figure stops at the maximum and the single extra
    cent is held and certificated, which is the only claim on the whole estate.

    PRD: "`insured_amount_cents` is the sum over buckets of the smaller of that bucket's attributed amount and its limit; `uninsured_amount_cents` is the sum over buckets of the amount by which the attributed amount exceeds the limit, counting zero for any bucket that is at or below its limit"

    Design: Difficulty/boundary_precision_check/smdia_cap_boundary_below_at_and_above_on_certify
    """
    estate = _boundary_estate(client)
    above = estate["above"]

    assert_determination_amounts(above["determination"], C.SMDIA_CENTS, 1, ABOVE_CAP_CENTS)
    assert_account_dimensions(
        X.get_account(client, above["account"]["id"]),
        "DETERMINED",
        "HELD",
        "PENDING",
        held_amount_cents=1,
        attributed_amount_cents=ABOVE_CAP_CENTS,
    )
    assert_fields_equal(
        X.get_depositor(client, above["depositor"]["id"]),
        {"notice_status": "SENT", "notice_template_code": "PARTIALLY_UNINSURED"},
    )

    certificates, _ = assert_page(
        client.list_certificates(
            CLAIMS_CERTIFIER,
            params={"depositor_record_id": above["depositor"]["id"]},
        ),
        expected_total=1,
    )
    assert_certificate(certificates[0], "ISSUED", 1, cumulative_dividends_cents=0)

    institution = X.get_institution(client, estate["institution_id"])
    assert_fields_equal(
        institution,
        {
            "aggregate_insured_cents": BELOW_CAP_CENTS + AT_CAP_CENTS + C.SMDIA_CENTS,
            "aggregate_certificate_face_cents": 1,
            "uninsured_claim_count": 1,
            "total_deposit_balance_cents": BOUNDARY_BOOKED_TOTAL_CENTS,
        },
    )
    assert X.insurance_summary(client, estate["institution_id"])["conservation_delta_cents"] == 0


# ---------------------------------------------------------------------------
# The award: a bid that ties the liquidation baseline is not least-costly
# ---------------------------------------------------------------------------
EQUALITY_BOOK_ASSET_CENTS = 10000000
EQUALITY_RECOVERY_CENTS = 10000000
JONAS_BALANCE_CENTS = 25000000

# 25000000 deposit base, less the 9000000 asset bid value, less the 850000 premium,
# with no retained pool: 15150000 — the same figure as the payoff baseline
# 25000000 + 150000 - 10000000.
TIE_PREMIUM_BPS = 340
TIE_DEPOSIT_PREMIUM_CENTS = 850000
TIE_ASSET_BID_VALUE_CENTS = 9000000
TIE_EVALUATED_COST_CENTS = 15150000
EQUALITY_BASELINE_CENTS = 15150000


def _tied_bid_estate(client):
    """A certified, fully insured estate whose only bid prices exactly at the baseline."""
    estate = X.single_account_estate(
        client,
        JONAS_BALANCE_CENTS,
        account_number="N-0001",
        cert_number="34577",
        legal_name="Bitterroot Equality Bank",
        charter_state="MT",
        book_asset_value_cents=EQUALITY_BOOK_ASSET_CENTS,
        estimated_liquidation_recovery_cents=EQUALITY_RECOVERY_CENTS,
        depositor_name="Jonas Weber",
    )
    institution_id = estate["institution"]["id"]
    estate["branch"] = X.new_branch_reopening(
        client,
        institution_id,
        branch_code="BR-09",
        reopen_window_start="2026-08-06T09:00:00Z",
        reopen_window_end="2026-08-06T17:00:00Z",
        staffing_headcount=8,
    )
    estate["determination"] = X.certified_determination(client, estate["depositor"]["id"])

    X.open_marketing(client, institution_id)
    bidder = X.new_qualified_bidder(
        client,
        legal_name="Glacier Peak Bank",
        cert_number="54001",
        tier1_capital_ratio_bps=1550,
        camels_composite=2,
    )
    estate["bid"] = X.new_bid(
        client,
        institution_id,
        bidder["id"],
        structure="WHOLE_BANK_PA",
        deposit_premium_bps=TIE_PREMIUM_BPS,
        asset_discount_bps=1000,
        loss_share_pct_bps=0,
        asset_retention_pool_cents=0,
        data_room_window_start="2026-09-03T09:00:00Z",
        data_room_window_end="2026-09-03T12:00:00Z",
    )
    X.evaluate_least_cost(client, institution_id, "EXPECTED_LOSS_SHARE")
    estate["institution"] = X.get_institution(client, institution_id)
    estate["bid"] = X.get_bid(client, estate["bid"]["id"])
    return estate


def test_a_bid_whose_cost_equals_the_baseline_wins_nothing(client):
    """A conforming bid evaluated at exactly the 15150000-cent liquidation baseline is
    not least-costly, so the award falls through to the payoff branch instead of
    naming it the winner.

    PRD: "A bid is eligible to win only if it is at `CONFORMING` **and** its `evaluated_cost_cents` is strictly less than the institution's `liquidation_baseline_cents`; a bid whose evaluated cost exactly equals the baseline is not least-costly and is not eligible."

    Design: Difficulty/boundary_precision_check/award_rejects_bid_whose_cost_equals_liquidation_baseline
    """
    estate = _tied_bid_estate(client)
    institution_id = estate["institution"]["id"]

    assert_fields_equal(
        estate["institution"],
        {
            "least_cost_status": "EVALUATED",
            "conforming_bid_count": 1,
            "liquidation_baseline_cents": EQUALITY_BASELINE_CENTS,
        },
    )
    assert_fields_equal(
        estate["bid"],
        {
            "status": "CONFORMING",
            "assumed_deposit_base_cents": JONAS_BALANCE_CENTS,
            "pre_fee_cost_cents": TIE_EVALUATED_COST_CENTS,
            "loss_share_fee_cents": 0,
            "expected_loss_share_reimbursement_cents": 0,
            "evaluated_cost_cents": TIE_EVALUATED_COST_CENTS,
        },
    )
    assert estate["bid"]["evaluated_cost_cents"] == EQUALITY_BASELINE_CENTS

    awarded = X.award_least_cost(client, institution_id)
    assert_fields_equal(
        awarded,
        {
            "least_cost_status": "FAILED_ALL_BIDS",
            "resolution_method": "DEPOSIT_PAYOFF",
            "status": "RESOLUTION_COMPLETE",
        },
    )
    assert awarded["least_cost_status"] != "AWARDED"
    assert awarded["resolution_method"] != "WHOLE_BANK_PA"

    settled_bid = X.get_bid(client, estate["bid"]["id"])
    assert_fields_equal(
        settled_bid,
        {"status": "REJECTED", "evaluated_cost_cents": TIE_EVALUATED_COST_CENTS},
    )
    assert settled_bid["status"] != "WINNER"


def test_the_payoff_branch_pays_the_account_out_and_still_readies_the_branch(client):
    """Because no bid was eligible, the certified hold-free account is paid out rather
    than transferred, while the planned branch reopening still becomes ready.

    PRD: "Eligible accounts — again those at `insurance_status` `DETERMINED` with `hold_status` `NONE` or `RELEASED` — move `transition_status` `PENDING` → `PAID_OUT` instead of `TRANSFERRED`, because their deposits are being paid out rather than assumed by an acquirer. And the branch cascade still fires, moving every `PLANNED` reopening to `READY`."

    Design: Difficulty/boundary_precision_check/award_rejects_bid_whose_cost_equals_liquidation_baseline
    """
    estate = _tied_bid_estate(client)

    X.award_least_cost(client, estate["institution"]["id"])

    account = X.get_account(client, estate["account"]["id"])
    assert_account_dimensions(
        account, "DETERMINED", "NONE", "PAID_OUT", held_amount_cents=0
    )
    assert account["transition_status"] != "TRANSFERRED"

    branch = X.get_branch_reopening(client, estate["branch"]["id"])
    assert_fields_equal(branch, {"status": "READY", "reschedule_count": 0})
