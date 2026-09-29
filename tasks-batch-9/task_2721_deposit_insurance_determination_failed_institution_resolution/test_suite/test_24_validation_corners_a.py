"""Validation corners of the Deposit Insurance Resolution API, first group.

Every test here pins one declared validation rule: the monotone logical clock, the
declared integer ranges of the request-shape stage, the conditionally required
brokered pair, the eligibility floors that gate a bidder qualification, the
scoping of each uniqueness constraint, and the pinned order in which caller
identity, referential integrity and lifecycle guards fire on one request.  Each
test builds its own rows against an empty database whose logical clock reads the
instant the service started at, and a rejected write is checked to have left the
target row exactly as it was.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_BIDDER_INELIGIBLE,
    ERR_BIDDER_MISMATCH,
    ERR_BID_INSTITUTION_INELIGIBLE,
    ERR_CLOCK_MONOTONICITY,
    ERR_DEPOSITOR_MISMATCH,
    ERR_DUPLICATE_IDENTIFIER,
    ERR_INVALID_REQUEST,
    ERR_MARKETING_ACTION_INVALID,
    ERR_MARKETING_NOT_OPEN,
    ERR_NOTICE_NOT_SENT,
)
from test_helpers.assertions import (
    assert_fields_equal,
    assert_instant,
    assert_page,
)
from test_helpers.test_users import (
    CLAIMS_AGENT,
    CLOSING_MANAGER,
    RESOLUTION_ANALYST,
    make_bidder_headers,
    make_depositor_headers,
)


def _assert_empty_page(response):
    """A list response reporting no matching resource at all."""
    _, meta = assert_page(response, expected_total=0)
    assert meta["has_more"] is False, meta


def _resolution_ready_with_one_account(
    client, cert_number, legal_name, charter_state, balance_cents, account_number, tin_hash
):
    """An institution standardized to `RESOLUTION_READY` over one single-ownership account.

    A package of one record with none malformed clears the score floor outright, and
    reporting exactly the booked total puts the variance at zero, so both gates pass.
    """
    institution = X.new_institution(
        client,
        cert_number=cert_number,
        legal_name=legal_name,
        charter_state=charter_state,
        book_asset_value_cents=5000000,
        estimated_liquidation_recovery_cents=2000000,
    )
    depositor = X.new_depositor(
        client,
        institution["id"],
        tin_hash=tin_hash,
        legal_name="Rosa Iglesias",
        depositor_type="NATURAL_PERSON",
        contact_email="rosa@example.com",
    )
    X.new_account(
        client,
        institution["id"],
        depositor["id"],
        account_number=account_number,
        ownership_category="SINGLE",
        balance_cents=balance_cents,
        accrued_interest_cents=0,
        opened_at="2024-04-01T00:00:00Z",
    )
    submission = X.file_readiness(
        client,
        institution["id"],
        record_count=1,
        malformed_record_count=0,
        reported_deposit_total_cents=balance_cents,
    )
    X.standardize(client, submission["id"])
    return X.get_institution(client, institution["id"])


def test_clock_cannot_move_backwards_and_equal_reset_is_accepted(client):
    """The logical clock refuses a backward jump but accepts being re-set to the
    instant it already holds, and the refused call leaves the clock where it was.

    PRD: "The clock is strictly monotonic: a request whose `to_iso8601` is earlier than the current logical clock is rejected with `ERR_CLOCK_MONOTONICITY`, while a request that sets the clock to exactly its current value is accepted and leaves it unchanged."

    Design: Corner/validations/clock_cannot_move_backwards_and_equal_reset_is_accepted
    """
    X.advance_clock(client, "2026-08-03T09:00:00Z")

    backwards = client.set_clock("2026-08-02T09:00:00Z", CLOSING_MANAGER)
    validate_error(backwards, ERR_CLOCK_MONOTONICITY, 422)
    assert backwards.json()["response_type"] == "error", backwards.text

    equal = validate_success(client.set_clock("2026-08-03T09:00:00Z", CLOSING_MANAGER), 200)
    assert_instant(equal["current_utc"], "2026-08-03T09:00:00Z")


def test_malformed_record_count_above_record_count_rejected(client):
    """A readiness package flagging more malformed records than it delivers fails the
    request-shape stage, so no submission row is filed and the institution is untouched.

    PRD: "`malformed_record_count` at least 0 and no greater than `record_count`"

    Design: Corner/validations/malformed_record_count_above_record_count_rejected
    """
    X.advance_clock(client, C.SETUP_CLOCK)
    institution = X.new_institution(
        client,
        cert_number="61041",
        legal_name="Malformed Count Bank",
        charter_state="OH",
        book_asset_value_cents=5000000,
        estimated_liquidation_recovery_cents=2000000,
    )

    validate_error(
        client.create_readiness_submission(
            institution["id"],
            F.readiness_submission_payload(
                record_count=3, malformed_record_count=4, reported_deposit_total_cents=1000
            ),
            CLOSING_MANAGER,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    after = X.get_institution(client, institution["id"])
    assert_fields_equal(after, {"status": "PRE_FAILURE_MONITORING", "version": 1})
    _assert_empty_page(
        client.list_readiness_submissions(institution["id"], CLOSING_MANAGER)
    )


def test_broker_fields_rejected_on_single_account_and_required_together_on_pass_through(
    client,
):
    """The brokered pair is forbidden on a single-ownership account and accepted on a
    brokered pass-through one, so the same two keys flip on `ownership_category` alone.

    PRD: "`broker_name` and `recordkeeping_status` must both be present exactly when `ownership_category` is `BROKERED_PASS_THROUGH`, and must both be absent otherwise."

    Design: Corner/validations/broker_fields_rejected_on_single_account_and_required_together_on_pass_through
    """
    X.advance_clock(client, C.SETUP_CLOCK)
    institution = X.new_institution(
        client,
        cert_number="61042",
        legal_name="Conditional Broker Bank",
        charter_state="CO",
        book_asset_value_cents=9000000,
        estimated_liquidation_recovery_cents=4000000,
    )
    person = X.new_depositor(
        client,
        institution["id"],
        tin_hash="TIN-CB-1",
        legal_name="Jonas Ekwueme",
        depositor_type="NATURAL_PERSON",
        contact_email="jonas@example.com",
    )
    broker = X.new_depositor(
        client,
        institution["id"],
        tin_hash="TIN-CB-2",
        legal_name="Keystone Brokerage",
        depositor_type="BROKER",
        contact_email="ops@keystone.example.com",
    )

    validate_error(
        client.create_deposit_account(
            F.deposit_account_payload(
                institution["id"],
                person["id"],
                account_number="CB-0001",
                ownership_category="SINGLE",
                balance_cents=1000000,
                accrued_interest_cents=0,
                opened_at="2024-05-01T00:00:00Z",
                broker_name="Keystone Brokerage",
                recordkeeping_status="COMPLETE",
            ),
            CLAIMS_AGENT,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    account = X.new_account(
        client,
        institution["id"],
        broker["id"],
        account_number="CB-0002",
        ownership_category="BROKERED_PASS_THROUGH",
        balance_cents=1000000,
        accrued_interest_cents=0,
        opened_at="2024-05-01T00:00:00Z",
        broker_name="Keystone Brokerage",
        recordkeeping_status="COMPLETE",
    )
    assert_fields_equal(
        account,
        {
            "ownership_category": "BROKERED_PASS_THROUGH",
            "broker_name": "Keystone Brokerage",
            "recordkeeping_status": "COMPLETE",
            "insurance_status": "PENDING",
        },
    )

    assert_page(
        client.list_deposit_accounts(
            CLAIMS_AGENT, params={"institution_id": institution["id"]}
        ),
        expected_total=1,
    )


def test_designated_share_bps_outside_one_to_ten_thousand_rejected(client):
    """An ownership interest claiming a zero share or more than the whole account is
    rejected at the request-shape stage, leaving the account with no interests at all.

    PRD: "The declared ranges are: `designated_share_bps` from 1 to 10000"

    Design: Corner/validations/designated_share_bps_outside_one_to_ten_thousand_rejected
    """
    X.advance_clock(client, C.SETUP_CLOCK)
    institution = X.new_institution(
        client,
        cert_number="61043",
        legal_name="Share Range Bank",
        charter_state="KS",
        book_asset_value_cents=3000000,
        estimated_liquidation_recovery_cents=1000000,
    )
    depositor = X.new_depositor(
        client,
        institution["id"],
        tin_hash="TIN-SR-1",
        legal_name="Lidia Moreno",
        depositor_type="NATURAL_PERSON",
        contact_email="lidia@example.com",
    )
    account = X.new_account(
        client,
        institution["id"],
        depositor["id"],
        account_number="JT-0001",
        ownership_category="JOINT",
        balance_cents=2000000,
        accrued_interest_cents=0,
        opened_at="2024-06-01T00:00:00Z",
    )

    for share_bps in (10001, 0):
        validate_error(
            client.create_ownership_interest(
                account["id"],
                F.ownership_interest_payload(depositor["id"], "CO_OWNER", share_bps),
                CLAIMS_AGENT,
            ),
            ERR_INVALID_REQUEST,
            400,
        )

    _assert_empty_page(
        client.list_account_ownership_interests(account["id"], CLAIMS_AGENT)
    )
    assert_fields_equal(X.get_account(client, account["id"]), {"version": 1})


def test_bidder_camels_composite_outside_one_to_five_rejected(client):
    """A CAMELS composite outside the declared one-to-five range never reaches the
    bidder register, while a composite of three is a legal value that opens as pending.

    PRD: "`camels_composite` from 1 to 5"

    Design: Corner/validations/bidder_camels_composite_outside_one_to_five_rejected
    """
    X.advance_clock(client, C.SETUP_CLOCK)

    validate_error(
        client.create_bidder(
            F.bidder_payload(
                legal_name="Out Of Range Acquirer",
                cert_number="62001",
                tier1_capital_ratio_bps=1500,
                camels_composite=6,
            ),
            RESOLUTION_ANALYST,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    bidder = X.new_bidder(
        client,
        legal_name="Weak Camels Acquirer",
        cert_number="62002",
        tier1_capital_ratio_bps=1500,
        camels_composite=3,
    )
    assert_fields_equal(
        bidder, {"camels_composite": 3, "qualification_status": "PENDING"}
    )

    assert_page(client.list_bidders(RESOLUTION_ANALYST), expected_total=1)


def test_qualify_below_capital_floor_or_above_camels_ceiling_rejected(client):
    """Both eligibility floors gate only a qualify decision: an under-capitalized or
    weakly rated acquirer cannot be qualified, yet may still be disqualified.

    PRD: "A `QUALIFY` decision requires the bidder's `tier1_capital_ratio_bps` to be at least 1000 — a tier-1 leverage ratio of at least ten percent — and its `camels_composite` to be no worse than 2; a bidder failing either floor cannot be qualified and the decision is refused with `ERR_BIDDER_INELIGIBLE`."

    Design: Corner/validations/qualify_below_capital_floor_or_above_camels_ceiling_rejected
    """
    X.advance_clock(client, C.SETUP_CLOCK)
    thin = X.new_bidder(
        client,
        legal_name="Thin Capital Acquirer",
        cert_number="62003",
        tier1_capital_ratio_bps=900,
        camels_composite=1,
    )
    weak = X.new_bidder(
        client,
        legal_name="Weak Rating Acquirer",
        cert_number="62004",
        tier1_capital_ratio_bps=1500,
        camels_composite=3,
    )

    for bidder_id in (thin["id"], weak["id"]):
        validate_error(
            client.decide_qualification(
                bidder_id, F.qualification_payload("QUALIFY"), RESOLUTION_ANALYST
            ),
            ERR_BIDDER_INELIGIBLE,
            422,
        )

    refused = X.get_bidder(client, thin["id"])
    assert_fields_equal(refused, {"qualification_status": "PENDING", "version": 1})
    assert refused["qualified_at"] is None, refused["qualified_at"]

    disqualified = X.qualify_bidder(client, weak["id"], decision="DISQUALIFY")
    assert_fields_equal(
        disqualified,
        {"qualification_status": "DISQUALIFIED", "disqualification_reason": "MANUAL"},
    )


def test_duplicate_institution_cert_number_rejected_while_bidder_reuse_is_allowed(client):
    """A certificate number already on file may not be registered a second time as an
    institution, yet the same number is free for an acquiring institution to carry.

    PRD: "A second institution presenting a `cert_number` already on file is refused with `ERR_DUPLICATE_IDENTIFIER`."

    Design: Corner/validations/duplicate_institution_cert_number_rejected_while_bidder_reuse_is_allowed
    """
    X.advance_clock(client, C.SETUP_CLOCK)
    X.new_institution(
        client,
        cert_number="61044",
        legal_name="Duplicate Cert Bank",
        charter_state="AZ",
        book_asset_value_cents=7000000,
        estimated_liquidation_recovery_cents=3000000,
    )

    validate_error(
        client.create_institution(
            F.institution_payload(
                cert_number="61044",
                legal_name="Duplicate Cert Bank Two",
                charter_state="AZ",
                book_asset_value_cents=8000000,
                estimated_liquidation_recovery_cents=3500000,
            ),
            CLOSING_MANAGER,
        ),
        ERR_DUPLICATE_IDENTIFIER,
        409,
    )

    bidder = X.new_bidder(
        client,
        legal_name="Same Number Acquirer",
        cert_number="61044",
        tier1_capital_ratio_bps=1600,
        camels_composite=1,
    )
    assert_fields_equal(
        bidder, {"cert_number": "61044", "qualification_status": "PENDING"}
    )

    assert_page(
        client.list_institutions(CLOSING_MANAGER, params={"charter_state": "AZ"}),
        expected_total=1,
    )


def test_duplicate_account_number_rejected_within_institution_only(client):
    """An account number may not repeat inside one institution's deposit file but is
    perfectly free at another failed institution, and the refused load moves no total.

    PRD: "a repeated `account_number` within the institution is refused with `ERR_DUPLICATE_IDENTIFIER`"

    Design: Corner/validations/duplicate_account_number_rejected_within_institution_only
    """
    X.advance_clock(client, C.SETUP_CLOCK)
    first = X.new_institution(
        client,
        cert_number="61045",
        legal_name="Scoped Account Bank A",
        charter_state="NV",
        book_asset_value_cents=6000000,
        estimated_liquidation_recovery_cents=2500000,
    )
    second = X.new_institution(
        client,
        cert_number="61046",
        legal_name="Scoped Account Bank B",
        charter_state="NV",
        book_asset_value_cents=6000000,
        estimated_liquidation_recovery_cents=2500000,
    )
    mira = X.new_depositor(
        client,
        first["id"],
        tin_hash="TIN-DA-1",
        legal_name="Mira Solano",
        depositor_type="NATURAL_PERSON",
        contact_email="mira@example.com",
    )
    noor = X.new_depositor(
        client,
        second["id"],
        tin_hash="TIN-DA-2",
        legal_name="Noor Haddad",
        depositor_type="NATURAL_PERSON",
        contact_email="noor@example.com",
    )
    X.new_account(
        client,
        first["id"],
        mira["id"],
        account_number="AC-0001",
        ownership_category="SINGLE",
        balance_cents=1000000,
        accrued_interest_cents=0,
        opened_at="2024-02-01T00:00:00Z",
    )

    validate_error(
        client.create_deposit_account(
            F.deposit_account_payload(
                first["id"],
                mira["id"],
                account_number="AC-0001",
                ownership_category="RETIREMENT",
                balance_cents=2000000,
                accrued_interest_cents=0,
                opened_at="2024-02-02T00:00:00Z",
            ),
            CLAIMS_AGENT,
        ),
        ERR_DUPLICATE_IDENTIFIER,
        409,
    )

    elsewhere = X.new_account(
        client,
        second["id"],
        noor["id"],
        account_number="AC-0001",
        ownership_category="SINGLE",
        balance_cents=3000000,
        accrued_interest_cents=0,
        opened_at="2024-02-03T00:00:00Z",
    )
    assert_fields_equal(elsewhere, {"account_number": "AC-0001"})

    assert_fields_equal(
        X.get_institution(client, first["id"]), {"total_deposit_balance_cents": 1000000}
    )


def test_duplicate_tin_hash_rejected_within_institution_only(client):
    """The same taxpayer hash may appear once per institution, so a repeat inside one
    estate is refused while the identical hash at another estate is registered.

    PRD: "A repeated `tin_hash` within the same institution is refused with `ERR_DUPLICATE_IDENTIFIER`; the same hash at a different institution is perfectly acceptable."

    Design: Corner/validations/duplicate_tin_hash_rejected_within_institution_only
    """
    X.advance_clock(client, C.SETUP_CLOCK)
    first = X.new_institution(
        client,
        cert_number="61047",
        legal_name="Shared Tin Bank A",
        charter_state="OR",
        book_asset_value_cents=4000000,
        estimated_liquidation_recovery_cents=1500000,
    )
    second = X.new_institution(
        client,
        cert_number="61048",
        legal_name="Shared Tin Bank B",
        charter_state="OR",
        book_asset_value_cents=4000000,
        estimated_liquidation_recovery_cents=1500000,
    )
    X.new_depositor(
        client,
        first["id"],
        tin_hash="TIN-SHARED",
        legal_name="Omar Reyes",
        depositor_type="NATURAL_PERSON",
        contact_email="omar@example.com",
    )

    validate_error(
        client.create_depositor_record(
            first["id"],
            F.depositor_record_payload(
                tin_hash="TIN-SHARED",
                legal_name="Omar Reyes Duplicate",
                depositor_type="NATURAL_PERSON",
                contact_email="omar2@example.com",
            ),
            CLAIMS_AGENT,
        ),
        ERR_DUPLICATE_IDENTIFIER,
        409,
    )

    elsewhere = X.new_depositor(
        client,
        second["id"],
        tin_hash="TIN-SHARED",
        legal_name="Omar Reyes",
        depositor_type="NATURAL_PERSON",
        contact_email="omar@example.com",
    )
    assert_fields_equal(
        elsewhere, {"tin_hash": "TIN-SHARED", "notice_status": "PENDING"}
    )

    assert_fields_equal(
        X.get_institution(client, first["id"]), {"depositor_record_count": 1}
    )
    assert_fields_equal(
        X.get_institution(client, second["id"]), {"depositor_record_count": 1}
    )


def test_depositor_cannot_acknowledge_another_depositors_notice(client):
    """Caller identity is checked before the notice-state gate, so acting on somebody
    else's record is an identity refusal even though that record's notice is unsent too.

    PRD: "a depositor may acknowledge only the notice on its own record, and a mismatch between `X-User-ID` and the depositor record named in the path is rejected with `ERR_DEPOSITOR_MISMATCH`."

    Design: Corner/validations/depositor_cannot_acknowledge_another_depositors_notice
    """
    X.advance_clock(client, C.SETUP_CLOCK)
    institution = X.new_institution(
        client,
        cert_number="61049",
        legal_name="Notice Identity Bank",
        charter_state="NM",
        book_asset_value_cents=3000000,
        estimated_liquidation_recovery_cents=1200000,
    )
    priya = X.new_depositor(
        client,
        institution["id"],
        tin_hash="TIN-NI-1",
        legal_name="Priya Nandan",
        depositor_type="NATURAL_PERSON",
        contact_email="priya@example.com",
    )
    quentin = X.new_depositor(
        client,
        institution["id"],
        tin_hash="TIN-NI-2",
        legal_name="Quentin Blake",
        depositor_type="NATURAL_PERSON",
        contact_email="quentin@example.com",
    )
    acting_as_priya = make_depositor_headers(priya["id"])

    validate_error(
        client.acknowledge_notice(quentin["id"], acting_as_priya),
        ERR_DEPOSITOR_MISMATCH,
        403,
    )
    validate_error(
        client.acknowledge_notice(priya["id"], acting_as_priya),
        ERR_NOTICE_NOT_SENT,
        409,
    )

    untouched = X.get_depositor(client, quentin["id"])
    assert_fields_equal(untouched, {"notice_status": "PENDING", "version": 1})
    assert untouched["acknowledged_at"] is None, untouched["acknowledged_at"]


def test_bidder_cannot_submit_a_bid_for_another_bidder_or_an_ineligible_institution(
    client,
):
    """Bidding in another acquirer's name is an identity refusal, and once the identity
    matches the still-monitored institution is refused as an ineligible franchise.

    PRD: "The acting `X-User-ID` must equal the `bidder_id` in the payload, else `ERR_BIDDER_MISMATCH`. The institution must be at `status` `RESOLUTION_READY` or `CLOSED_IN_RECEIVERSHIP`, else `ERR_BID_INSTITUTION_INELIGIBLE`."

    Design: Corner/validations/bidder_cannot_submit_a_bid_for_another_bidder_or_an_ineligible_institution
    """
    X.advance_clock(client, C.SETUP_CLOCK)
    institution = X.new_institution(
        client,
        cert_number="61050",
        legal_name="Ineligible Franchise Bank",
        charter_state="UT",
        book_asset_value_cents=11000000,
        estimated_liquidation_recovery_cents=5000000,
    )
    alpha = X.new_qualified_bidder(
        client,
        legal_name="Alpha Acquirer",
        cert_number="62005",
        tier1_capital_ratio_bps=1700,
        camels_composite=1,
    )
    beta = X.new_qualified_bidder(
        client,
        legal_name="Beta Acquirer",
        cert_number="62006",
        tier1_capital_ratio_bps=1800,
        camels_composite=2,
    )
    acting_as_alpha = make_bidder_headers(alpha["id"])
    window = {
        "data_room_window_start": "2026-08-05T09:00:00Z",
        "data_room_window_end": "2026-08-05T10:00:00Z",
    }

    validate_error(
        client.create_bid(
            F.bid_payload(
                institution["id"],
                beta["id"],
                structure="WHOLE_BANK_PA",
                deposit_premium_bps=100,
                asset_discount_bps=1000,
                **window,
            ),
            acting_as_alpha,
        ),
        ERR_BIDDER_MISMATCH,
        403,
    )
    validate_error(
        client.create_bid(
            F.bid_payload(
                institution["id"],
                alpha["id"],
                structure="WHOLE_BANK_PA",
                deposit_premium_bps=100,
                asset_discount_bps=1000,
                **window,
            ),
            acting_as_alpha,
        ),
        ERR_BID_INSTITUTION_INELIGIBLE,
        422,
    )

    _assert_empty_page(
        client.list_bids(RESOLUTION_ANALYST, params={"institution_id": institution["id"]})
    )


def test_bid_rejected_before_franchise_marketing_opens(client):
    """A resolution-ready franchise that has never been marketed refuses a bid, and the
    identical submission is accepted the moment the marketing window is opened.

    PRD: "The institution's `franchise_marketing_status` must be `OPEN`, else `ERR_MARKETING_NOT_OPEN`."

    Design: Corner/validations/bid_rejected_before_franchise_marketing_opens
    """
    X.advance_clock(client, C.SETUP_CLOCK)
    institution = _resolution_ready_with_one_account(
        client,
        cert_number="61051",
        legal_name="Marketing Gate Bank",
        charter_state="ID",
        balance_cents=4000000,
        account_number="MG-0001",
        tin_hash="TIN-MG-1",
    )
    assert_fields_equal(
        institution,
        {
            "status": "RESOLUTION_READY",
            "franchise_marketing_status": "NOT_STARTED",
            "total_deposit_balance_cents": 4000000,
        },
    )
    bidder = X.new_qualified_bidder(
        client,
        legal_name="Rialto Acquirer",
        cert_number="62007",
        tier1_capital_ratio_bps=1800,
        camels_composite=1,
    )
    acting_as_bidder = make_bidder_headers(bidder["id"])

    def submission():
        return F.bid_payload(
            institution["id"],
            bidder["id"],
            structure="WHOLE_BANK_PA",
            deposit_premium_bps=150,
            asset_discount_bps=1200,
            data_room_window_start="2026-08-06T09:00:00Z",
            data_room_window_end="2026-08-06T10:00:00Z",
        )

    validate_error(
        client.create_bid(submission(), acting_as_bidder), ERR_MARKETING_NOT_OPEN, 409
    )

    opened = validate_success(
        client.franchise_marketing(
            institution["id"],
            F.marketing_payload("OPEN", bid_deadline_at="2026-08-10T00:00:00Z"),
            RESOLUTION_ANALYST,
        ),
        200,
    )
    assert_fields_equal(opened, {"franchise_marketing_status": "OPEN"})
    assert_instant(opened["bid_deadline_at"], "2026-08-10T00:00:00Z")

    bid = validate_success(client.create_bid(submission(), acting_as_bidder), 201)
    assert_fields_equal(
        bid,
        {
            "status": "SUBMITTED",
            "assumed_deposit_base_cents": 4000000,
            "loss_share_pct_bps": 0,
            "asset_retention_pool_cents": 0,
        },
    )
    assert bid["evaluated_cost_cents"] is None, bid["evaluated_cost_cents"]


def test_franchise_marketing_close_before_open_and_second_open_rejected(client):
    """The one marketing capability is direction-specific: closing a franchise that was
    never opened and re-opening an open one are both refused, and the deadline survives.

    PRD: "Either action taken out of turn — opening an already-open or already-closed franchise, or closing one that was never opened — is refused with `ERR_MARKETING_ACTION_INVALID`."

    Design: Corner/validations/franchise_marketing_close_before_open_and_second_open_rejected
    """
    X.advance_clock(client, C.SETUP_CLOCK)
    institution = _resolution_ready_with_one_account(
        client,
        cert_number="61052",
        legal_name="Marketing Direction Bank",
        charter_state="MT",
        balance_cents=4000000,
        account_number="MD-0001",
        tin_hash="TIN-MD-1",
    )
    assert_fields_equal(institution, {"franchise_marketing_status": "NOT_STARTED"})

    validate_error(
        client.franchise_marketing(
            institution["id"],
            F.marketing_payload("CLOSE", bid_deadline_at=None),
            RESOLUTION_ANALYST,
        ),
        ERR_MARKETING_ACTION_INVALID,
        409,
    )

    opened = validate_success(
        client.franchise_marketing(
            institution["id"],
            F.marketing_payload("OPEN", bid_deadline_at="2026-08-11T00:00:00Z"),
            RESOLUTION_ANALYST,
        ),
        200,
    )
    assert_fields_equal(opened, {"franchise_marketing_status": "OPEN"})
    assert_instant(opened["bid_deadline_at"], "2026-08-11T00:00:00Z")

    validate_error(
        client.franchise_marketing(
            institution["id"],
            F.marketing_payload("OPEN", bid_deadline_at="2026-08-12T00:00:00Z"),
            RESOLUTION_ANALYST,
        ),
        ERR_MARKETING_ACTION_INVALID,
        409,
    )

    closed = validate_success(
        client.franchise_marketing(
            institution["id"],
            F.marketing_payload("CLOSE", bid_deadline_at=None),
            RESOLUTION_ANALYST,
        ),
        200,
    )
    assert_fields_equal(closed, {"franchise_marketing_status": "CLOSED"})
    assert_instant(closed["bid_deadline_at"], "2026-08-11T00:00:00Z")
