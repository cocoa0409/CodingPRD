"""Which error wins when one request breaks two rules at once.

Both operations below carry a pinned guard order, so a request that violates two
guards simultaneously must answer with the earlier one and nothing else.  Each
pair is checked twice: once with both guards broken, and once with only the later
guard broken, which proves the shadowed rule is genuinely enforced rather than
missing.
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_BIDDER_NOT_QUALIFIED,
    ERR_BID_WINDOW_CLOSED,
    ERR_DETERMINATION_NOT_UNDER_REVIEW,
    ERR_SEGREGATION_OF_DUTIES_VIOLATION,
)
from test_helpers.assertions import assert_fields_equal, total_count
from test_helpers.test_users import (
    CLAIMS_AGENT,
    RESOLUTION_ANALYST,
    make_bidder_headers,
    make_claims_certifier_headers,
)

# The one operator who both prepares and tries to certify.
DUAL_ACTOR_USER_ID = "dual-actor-77"


def _prepared_by_the_dual_actor(client):
    """Hana's determination left at `PREPARED`, prepared by the dual-acting operator.

    Certifying it now breaks two guards at once: the determination is not at
    `UNDER_REVIEW`, and the acting operator is the one who prepared it.
    """
    estate = X.single_account_estate(
        client,
        C.ACCOUNT_A_BALANCE_CENTS,
        account_number="H-0001",
        cert_number="34573",
        legal_name="Skagit Mutual Bank",
        depositor_name="Hana Ito",
    )
    determination = X.open_determination(client, estate["depositor"]["id"])
    prepared = X.prepare(client, determination["id"], user_id=DUAL_ACTOR_USER_ID)
    assert_fields_equal(
        prepared, {"status": "PREPARED", "prepared_by_user_id": DUAL_ACTOR_USER_ID}
    )
    estate["determination"] = prepared
    return estate


def test_certify_answers_the_state_guard_and_shadows_segregation_of_duties(client):
    """Certifying a determination that is still `PREPARED`, by the very operator who
    prepared it, is refused for its state and not for the four-eyes breach.

    PRD: "The determination must be at `UNDER_REVIEW`, else `ERR_DETERMINATION_NOT_UNDER_REVIEW`. The depositor's institution must be at `CLOSED_IN_RECEIVERSHIP`, else `ERR_INSTITUTION_NOT_CLOSED`. The acting `X-User-ID` must differ from the recorded `prepared_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

    Design: Difficulty/priority_pair_validation_conflict/certify_state_error_outranks_segregation_of_duties
    """
    estate = _prepared_by_the_dual_actor(client)
    determination = estate["determination"]

    response = client.certify_determination(
        determination["id"], make_claims_certifier_headers(DUAL_ACTOR_USER_ID)
    )
    validate_error(response, ERR_DETERMINATION_NOT_UNDER_REVIEW, 409)
    assert response.json()["data"]["error_id"] != ERR_SEGREGATION_OF_DUTIES_VIOLATION
    assert response.status_code != 403

    # A refused certification writes nothing at all.
    unchanged = X.get_determination(client, determination["id"])
    assert_fields_equal(
        unchanged,
        {
            "status": "PREPARED",
            "version": determination["version"],
            "certified_by_user_id": None,
            "certified_at": None,
        },
    )
    assert (
        total_count(
            client.list_certificates(
                CLAIMS_AGENT, params={"depositor_record_id": estate["depositor"]["id"]}
            )
        )
        == 0
    )


def test_segregation_of_duties_is_enforced_once_the_state_guard_passes(client):
    """With the same determination moved to `UNDER_REVIEW`, the same operator's
    certification is refused for the four-eyes breach alone.

    PRD: "a certification whose `X-User-ID` equals the `prepared_by_user_id` recorded on the determination is refused with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` and HTTP 403, even though the caller holds the correct `ClaimsCertifier` role"

    Design: Difficulty/priority_pair_validation_conflict/certify_state_error_outranks_segregation_of_duties
    """
    estate = _prepared_by_the_dual_actor(client)
    determination_id = estate["determination"]["id"]

    under_review = X.submit_review(client, determination_id, user_id=DUAL_ACTOR_USER_ID)
    assert under_review["status"] == "UNDER_REVIEW"

    validate_error(
        client.certify_determination(
            determination_id, make_claims_certifier_headers(DUAL_ACTOR_USER_ID)
        ),
        ERR_SEGREGATION_OF_DUTIES_VIOLATION,
        403,
    )

    unchanged = X.get_determination(client, determination_id)
    assert_fields_equal(
        unchanged,
        {
            "status": "UNDER_REVIEW",
            "version": under_review["version"],
            "certified_by_user_id": None,
        },
    )
    assert (
        total_count(
            client.list_certificates(
                CLAIMS_AGENT, params={"depositor_record_id": estate["depositor"]["id"]}
            )
        )
        == 0
    )


# ---------------------------------------------------------------------------
# Bid submission: the closed deadline outranks the unqualified bidder
# ---------------------------------------------------------------------------
EXPIRED_DEADLINE = "2026-08-10T00:00:00Z"
OPEN_DEADLINE = "2026-09-30T00:00:00Z"
CLOCK_AFTER_THE_FIRST_DEADLINE = "2026-08-11T00:00:00Z"


def _two_estates_and_an_unqualified_bidder(client):
    """Two marketed estates, one past its bid deadline and one not, plus a `PENDING` bidder.

    The clock is advanced past the first estate's deadline only, so a bid on that
    estate breaks the deadline guard and the qualification guard together, while a
    bid on the second breaks the qualification guard alone.
    """
    X.open_at_setup_clock(client)
    expired = X.deposit_free_closed_institution(
        client, cert_number="34574", legal_name="Palouse Heritage Bank"
    )
    X.open_marketing(client, expired["id"], EXPIRED_DEADLINE)
    still_open = X.deposit_free_closed_institution(
        client, cert_number="34575", legal_name="Wallowa Union Bank", charter_state="OR"
    )
    X.open_marketing(client, still_open["id"], OPEN_DEADLINE)

    bidder = X.new_bidder(
        client,
        legal_name="Skyline Partners Bank",
        cert_number="53001",
        tier1_capital_ratio_bps=1500,
        camels_composite=2,
    )
    assert bidder["qualification_status"] == "PENDING"

    X.advance_clock(client, CLOCK_AFTER_THE_FIRST_DEADLINE)
    return {"expired": expired, "still_open": still_open, "bidder": bidder}


def _attempt_bid(client, institution_id, bidder_id, window_day):
    payload = F.bid_payload(
        institution_id,
        bidder_id,
        structure="WHOLE_BANK_PA",
        deposit_premium_bps=300,
        asset_discount_bps=1000,
        data_room_window_start=f"2026-08-{window_day}T09:00:00Z",
        data_room_window_end=f"2026-08-{window_day}T12:00:00Z",
    )
    return client.create_bid(payload, make_bidder_headers(bidder_id))


def test_a_late_bid_answers_the_closed_deadline_and_shadows_the_qualification_guard(client):
    """A bid filed after the deadline by a bidder who was never qualified is refused for
    the closed window, and the qualification code is not the one returned even though
    both share HTTP 422.

    PRD: "The logical clock must be at or before the institution's `bid_deadline_at`, else `ERR_BID_WINDOW_CLOSED`. The claimed data-room interval must clear the separation rule below, else `ERR_DATA_ROOM_WINDOW_CONFLICT`. And the referenced bidder must be at `qualification_status` `QUALIFIED`, so a `PENDING` or `DISQUALIFIED` acquirer is refused with `ERR_BIDDER_NOT_QUALIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/bid_deadline_temporal_error_outranks_bidder_qualification
    """
    world = _two_estates_and_an_unqualified_bidder(client)
    institution_id = world["expired"]["id"]
    bidder_id = world["bidder"]["id"]

    response = _attempt_bid(client, institution_id, bidder_id, "20")
    validate_error(response, ERR_BID_WINDOW_CLOSED, 422)
    assert response.json()["data"]["error_id"] != ERR_BIDDER_NOT_QUALIFIED

    # No bid row was created for the refused submission.
    assert (
        total_count(
            client.list_bids(RESOLUTION_ANALYST, params={"institution_id": institution_id})
        )
        == 0
    )
    bidder = X.get_bidder(client, bidder_id)
    assert_fields_equal(
        bidder, {"qualification_status": "PENDING", "disqualification_reason": None}
    )


def test_an_unqualified_bidder_is_refused_while_the_deadline_is_still_open(client):
    """On the estate whose deadline has not passed, the same bidder's submission is
    refused for its qualification status, which proves that guard is live.

    PRD: "the referenced bidder must be at `qualification_status` `QUALIFIED`, so a `PENDING` or `DISQUALIFIED` acquirer is refused with `ERR_BIDDER_NOT_QUALIFIED`"

    Design: Difficulty/priority_pair_validation_conflict/bid_deadline_temporal_error_outranks_bidder_qualification
    """
    world = _two_estates_and_an_unqualified_bidder(client)
    institution_id = world["still_open"]["id"]
    bidder_id = world["bidder"]["id"]

    response = _attempt_bid(client, institution_id, bidder_id, "21")
    validate_error(response, ERR_BIDDER_NOT_QUALIFIED, 422)

    assert (
        total_count(
            client.list_bids(RESOLUTION_ANALYST, params={"institution_id": institution_id})
        )
        == 0
    )
    bidder = X.get_bidder(client, bidder_id)
    assert_fields_equal(
        bidder, {"qualification_status": "PENDING", "disqualification_reason": None}
    )
