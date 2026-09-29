"""Which refusal wins when one request breaks two rules, and where the edges lie.

A tender made at the closing instant is also far below the minimum price, and an
engagement that runs past the licence also overloads the appraiser: in both
cases the earlier check in the declared order is the one the caller is told
about. The other half of the file pins two boundary instants to the cent and to
the second.
"""

from test_helpers import ApiErrorId, factories as f, fixtures as fx
from test_helpers import get_success_data, validate_error
from test_helpers.test_users import make_bidder_headers


def _live_offering_at_the_closing_instant(api):
    """A published competitive sale whose window has just run out.

    The parcel is appraised at 100,000,000 against a cured lien of 250,000, so
    the frozen minimum is 99,750,000. One clear bidder has been credited with
    10,000,000 and has never tendered anything. The clock stands exactly on the
    closing instant, which the half-open window no longer contains.
    """
    ctx = fx.build_valued_parcel(
        api,
        appraised_value_cents=100000000,
        book_value_cents=70000000,
        cured_lien_actual_cents=250000,
        lien_estimate_cents=250000,
    )
    ctx = fx.build_published_offering(
        api, ctx, bid_open_at="2026-08-01T00:00:00Z", bid_close_at="2026-12-31T00:00:00Z"
    )
    ctx["bidder"] = fx.make_funded_bidder(api, 10000000)
    fx.set_clock(api, ctx["bid_close_at"])
    return ctx


def _late_and_underpriced_tender(api, ctx):
    """Tender 50,000,000 after the window has shut, breaking two rules at once."""
    return api.submit_bid(
        ctx["offering"]["id"],
        f.bid_payload(
            amount_cents=50000000,
            deposit_amount_cents=ctx["offering"]["required_deposit_cents"],
        ),
        make_bidder_headers(ctx["bidder"]["id"]),
    )


def _loaded_appraiser_with_a_lapsing_licence(api):
    """An appraiser holding two in-flight engagements and a licence that ends soon.

    The two orders sit on the non-overlapping closed intervals
    [2026-08-02, 2026-08-20] and [2026-08-25, 2026-08-31], both of which the
    licence covers, so both were admissible and both are still `ORDERED`. The
    licence expires on 2026-09-01 and the clock has not moved from the default.
    """
    ctx = {}
    ctx["agency"] = fx.make_agency(api)
    ctx["parcel"] = fx.make_parcel(
        api,
        ctx["agency"]["id"],
        apn="APN-2693-010",
        address="5 Foundry Row",
        acreage=0.9,
        zoning_code="I-1",
        book_value_cents=40000000,
    )
    ctx["appraiser"] = fx.make_appraiser(
        api,
        name="Orrin Vasquez MAI",
        license_expires_on="2026-09-01T00:00:00Z",
    )
    ctx["first"] = fx.order_appraisal(
        api,
        ctx["parcel"]["id"],
        ctx["appraiser"]["id"],
        method="SALES_COMPARISON",
        engagement_start_on="2026-08-02T00:00:00Z",
        engagement_end_on="2026-08-20T00:00:00Z",
    )
    ctx["second"] = fx.order_appraisal(
        api,
        ctx["parcel"]["id"],
        ctx["appraiser"]["id"],
        method="COST",
        engagement_start_on="2026-08-25T00:00:00Z",
        engagement_end_on="2026-08-31T00:00:00Z",
    )
    ctx["version_before_trigger"] = fx.parcel_version(api, ctx["parcel"]["id"])
    return ctx


def _overlapping_order_past_the_licence(api, ctx):
    """Order over [2026-08-20, 2026-09-05]: past the licence and over the limit."""
    return api.create_appraisal(
        f.appraisal_order_payload(
            ctx["parcel"]["id"],
            ctx["appraiser"]["id"],
            ctx["version_before_trigger"],
            method="INCOME",
            engagement_start_on="2026-08-20T00:00:00Z",
            engagement_end_on="2026-09-05T00:00:00Z",
        ),
        fx.OFFICER_HEADERS,
    )


def test_01_a_tender_at_the_closing_instant_is_refused_on_the_window_not_the_price(api):
    """Both rules are broken and the temporal refusal is the one that is reported.

    "The window must be live, meaning the clock stands at or after `bid_open_at`
    and strictly before `bid_close_at` — a bid at the opening instant is in time,
    a bid at the closing instant is too late — and a bid outside the live window
    is `ERR_BIDDING_CLOSED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/bidding_closed_temporal_outranks_bid_below_minimum_fiscal
    """
    ctx = _live_offering_at_the_closing_instant(api)
    assert ctx["offering"]["minimum_price_cents"] == 99750000, (
        "the tender of 50,000,000 must also break the price rule, and the frozen "
        f"minimum is 99,750,000, got {ctx['offering']['minimum_price_cents']}"
    )

    response = _late_and_underpriced_tender(api, ctx)
    error = validate_error(response, ApiErrorId.ERR_BIDDING_CLOSED.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_BID_BELOW_MINIMUM.value, (
        "the price check runs after the window check, so it must not be the "
        f"refusal the caller is given, got {error['error_id']!r}"
    )


def test_02_the_refused_tender_writes_no_bid_and_moves_no_money(api):
    """A refusal on the window leaves the bid table and the cash ledger alone.

    "On success the bid is created with `qualification_status` `SUBMITTED` and
    `deposit_status` `HELD`, with `submitted_at` stamped from the logical clock,
    `award_rank` and `disqualification_reason` empty. The deposit moves out of
    spendable cash and into escrow in one transfer: the bidder's
    `available_funds_cents` falls by `deposit_amount_cents` and
    `escrow_held_cents` rises by exactly the same amount, while
    `lifetime_deposits_cents` is untouched — that counter records funding credits
    from treasury, never internal movements."

    Design: Difficulty/priority_pair_validation_conflict/bidding_closed_temporal_outranks_bid_below_minimum_fiscal
    """
    ctx = _live_offering_at_the_closing_instant(api)
    _late_and_underpriced_tender(api, ctx)

    bids = fx.bids_for_offering(api, ctx["offering"]["id"])
    assert bids == [], f"the refused tender must leave no bid behind, got {bids!r}"

    bidder = get_success_data(api.get_bidder(ctx["bidder"]["id"], fx.FINANCE_HEADERS))
    assert bidder["available_funds_cents"] == 10000000, (
        "the whole credited amount is still spendable, got "
        f"{bidder['available_funds_cents']}"
    )
    assert bidder["escrow_held_cents"] == 0, (
        f"nothing moved into escrow, got {bidder['escrow_held_cents']}"
    )
    assert bidder["lifetime_deposits_cents"] == 10000000, (
        "and the funding counter records the one treasury credit only, got "
        f"{bidder['lifetime_deposits_cents']}"
    )


def test_03_the_offering_itself_is_untouched_by_the_late_tender(api):
    """The offering stays open until somebody closes it, and counts no bid.

    "The offering starts with `qualified_bid_count` zero, `rescind_count` zero,
    and `winning_bid_amount_cents`, `awarded_at`, `awarded_by_user_id` and
    `cancellation_reason` all empty." "The offering's `qualified_bid_count` is
    then recomputed, and the offering moves `OPEN → EVALUATION` when at least one
    bid qualifies."

    Design: Difficulty/priority_pair_validation_conflict/bidding_closed_temporal_outranks_bid_below_minimum_fiscal
    """
    ctx = _live_offering_at_the_closing_instant(api)
    _late_and_underpriced_tender(api, ctx)

    offering = get_success_data(
        api.get_offering(ctx["offering"]["id"], fx.OFFICER_HEADERS)
    )
    assert offering["status"] == "OPEN", (
        "the clock running past the close instant does not by itself move the "
        f"offering, got {offering['status']!r}"
    )
    assert offering["qualified_bid_count"] == 0, (
        f"and no bid has been counted, got {offering['qualified_bid_count']}"
    )


def test_04_a_lapsing_licence_outranks_the_concurrent_engagement_limit(api):
    """The order breaks the licence rule and the capacity rule, and the licence wins.

    "The engagement is refused with `ERR_APPRAISER_LICENSE_EXPIRED` (HTTP 422)
    when the appraiser's `license_status` is `EXPIRED`, and equally when
    `license_expires_on` is not strictly later than `engagement_end_on` — a
    licence that lapses mid-engagement is no licence at all for this purpose."

    Design: Difficulty/priority_pair_validation_conflict/appraiser_license_safety_outranks_capacity_constraint
    """
    ctx = _loaded_appraiser_with_a_lapsing_licence(api)
    appraiser = get_success_data(
        api.get_appraiser(ctx["appraiser"]["id"], fx.OFFICER_HEADERS)
    )
    assert appraiser["active_engagement_count"] == 2, (
        "two in-flight engagements are needed for the capacity rule to be broken "
        f"as well, got {appraiser['active_engagement_count']}"
    )

    response = _overlapping_order_past_the_licence(api, ctx)
    error = validate_error(response, ApiErrorId.ERR_APPRAISER_LICENSE_EXPIRED.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_APPRAISER_CAPACITY_EXCEEDED.value, (
        "the capacity count is taken after the licence has been checked, so it "
        f"must not be the refusal the caller is given, got {error['error_id']!r}"
    )


def test_05_the_refused_order_leaves_both_engagements_and_the_licence_alone(api):
    """No third engagement is written and the licence is still good for its term.

    "On success the appraisal is created in `ORDERED`, the parcel's `version`
    rises by 1, and the appraiser's `active_engagement_count` is recomputed."
    "The derived `license_status` reads `ACTIVE` while the logical clock is
    strictly before `license_expires_on` and `EXPIRED` at that instant or after
    it, and the appraiser list can be filtered on it."

    Design: Difficulty/priority_pair_validation_conflict/appraiser_license_safety_outranks_capacity_constraint
    """
    ctx = _loaded_appraiser_with_a_lapsing_licence(api)
    _overlapping_order_past_the_licence(api, ctx)

    rows = get_success_data(
        api.list_appraisals(
            fx.OFFICER_HEADERS,
            {"appraiser_id": ctx["appraiser"]["id"], "limit": 100},
        )
    )
    assert len(rows) == 2, (
        "the refused order must not have created a third engagement, got "
        f"{len(rows)}"
    )
    assert {row["id"] for row in rows} == {ctx["first"]["id"], ctx["second"]["id"]}, (
        "the two surviving rows must be the two that were lawfully ordered"
    )
    for row in rows:
        assert row["status"] == "ORDERED", (
            "both engagements are still in flight, which is why the capacity "
            f"rule was broken at all, got {row['status']!r}"
        )

    appraiser = get_success_data(
        api.get_appraiser(ctx["appraiser"]["id"], fx.OFFICER_HEADERS)
    )
    assert appraiser["license_status"] == "ACTIVE", (
        "the refusal came from measuring the licence against the engagement end "
        f"date, not from flipping the licence status, got {appraiser['license_status']!r}"
    )
    assert appraiser["license_expires_on"] == "2026-09-01T00:00:00Z", (
        "and the recorded expiry is untouched, got "
        f"{appraiser['license_expires_on']!r}"
    )


def test_06_the_refused_order_consumes_no_concurrency_token(api):
    """The parcel version the caller held is still spendable after the refusal.

    "Note that the successful create itself advances `Parcel.version`, so the
    token a client just spent is stale for every other holder of the same token."

    Design: Difficulty/priority_pair_validation_conflict/appraiser_license_safety_outranks_capacity_constraint
    """
    ctx = _loaded_appraiser_with_a_lapsing_licence(api)
    _overlapping_order_past_the_licence(api, ctx)

    parcel = get_success_data(api.get_parcel(ctx["parcel"]["id"], fx.OFFICER_HEADERS))
    assert parcel["version"] == ctx["version_before_trigger"], (
        "a rejected create advances nothing, so the token is still current: "
        f"{parcel['version']} against {ctx['version_before_trigger']}"
    )

    accepted = api.create_appraisal(
        f.appraisal_order_payload(
            ctx["parcel"]["id"],
            ctx["appraiser"]["id"],
            ctx["version_before_trigger"],
            method="INCOME",
            engagement_start_on="2026-08-21T00:00:00Z",
            engagement_end_on="2026-08-24T00:00:00Z",
        ),
        fx.OFFICER_HEADERS,
    )
    ordered = get_success_data(accepted)
    assert ordered["status"] == "ORDERED", (
        "the very same token opens an engagement the licence covers and that "
        f"overlaps neither existing interval, got {ordered['status']!r}"
    )


def _breach_noticed_on_a_recorded_deed(api):
    """A recorded deed with an outstanding breach and a thirty-day cure period.

    The sale closed at 108,000,000 with a single cured lien of 250,000, so the
    frozen net of 105,000,001 was distributed to the one designated fund when the
    deed was recorded on 2026-12-31. The breach was noticed on 2027-01-15, which
    fixes the cure deadline at 2027-02-14T00:00:00Z.
    """
    ctx = fx.build_valued_parcel(
        api,
        appraised_value_cents=100000000,
        book_value_cents=70000000,
        cured_lien_actual_cents=250000,
        lien_estimate_cents=250000,
    )
    return fx.build_violation_noticed_conveyance(
        api,
        ctx,
        noticed_at="2027-01-15T00:00:00Z",
        reverter_cure_period_days=30,
    )


def _offering_with_two_funded_bidders(api):
    """A live competitive sale and two clear bidders each credited with 10,000,000.

    The parcel is appraised at 100,000,000 against a cured lien of 250,000, so
    the frozen minimum of 99,750,000 puts a twentieth of the price below the
    statutory deposit floor.
    """
    ctx = fx.build_valued_parcel(
        api,
        appraised_value_cents=100000000,
        book_value_cents=70000000,
        cured_lien_actual_cents=250000,
        lien_estimate_cents=250000,
    )
    ctx = fx.build_published_offering(api, ctx)
    ctx["short_bidder"] = fx.make_funded_bidder(
        api, 10000000, legal_name="SHORT-BID LLC", contact_email="short@bids.example"
    )
    ctx["exact_bidder"] = fx.make_funded_bidder(
        api, 10000000, legal_name="EXACT-BID LLC", contact_email="exact@bids.example"
    )
    return ctx


def _tender(api, ctx, bidder_key, deposit_amount_cents):
    """Tender a bid at the minimum-clearing amount with the stated deposit."""
    return api.submit_bid(
        ctx["offering"]["id"],
        f.bid_payload(
            amount_cents=108000000, deposit_amount_cents=deposit_amount_cents
        ),
        make_bidder_headers(ctx[bidder_key]["id"]),
    )


def test_07_enforcing_the_reverter_on_the_deadline_instant_is_refused(api):
    """The grantee still holds the right to cure at the deadline instant itself.

    "It requires `compliance_status` to be `VIOLATION_NOTICED` — anything else is
    `ERR_INVALID_CONVEYANCE_STATE` — and it requires the clock to stand strictly
    after `cure_deadline_at`." "On the deadline instant itself the grantee still
    holds the right to cure, so enforcement at exactly `cure_deadline_at` is
    refused with `ERR_CURE_PERIOD_NOT_EXPIRED` (HTTP 409); this is the one
    deadline in the system whose boundary instant favours the party being timed
    rather than the party doing the timing, and it is the exact complement of the
    cure test above, so at no instant are both operations available and at no
    instant are both refused."

    Design: Difficulty/boundary_precision_check/revert_requires_clock_strictly_after_cure_deadline_instant
    """
    ctx = _breach_noticed_on_a_recorded_deed(api)
    assert ctx["conveyance"]["cure_deadline_at"] == "2027-02-14T00:00:00.000Z", (
        "the notice of 2027-01-15 plus the frozen thirty-day cure period lands on "
        f"2027-02-14T00:00:00Z, got {ctx['conveyance']['cure_deadline_at']!r}"
    )

    fx.set_clock(api, "2027-02-14T00:00:00Z")
    response = api.revert_conveyance(ctx["conveyance"]["id"], fx.COMPLIANCE_HEADERS)
    validate_error(response, ApiErrorId.ERR_CURE_PERIOD_NOT_EXPIRED.value, 409)

    conveyance = get_success_data(
        api.get_conveyance(ctx["conveyance"]["id"], fx.OFFICER_HEADERS)
    )
    assert conveyance["compliance_status"] == "VIOLATION_NOTICED", (
        "the breach is still outstanding and curable, got "
        f"{conveyance['compliance_status']!r}"
    )
    assert conveyance["recording_status"] == "RECORDED", (
        f"and the deed still stands, got {conveyance['recording_status']!r}"
    )
    fund = get_success_data(api.get_fund(ctx["funds"][0]["id"], fx.FINANCE_HEADERS))
    assert fund["balance_cents"] == 105000001, (
        "no allocation row has been reversed, so the fund still holds the whole "
        f"distribution, got {fund['balance_cents']}"
    )


def test_08_enforcing_the_reverter_one_second_later_unwinds_the_transaction(api):
    """A single second past the deadline both dimensions of the deed move at once.

    "The conveyance moves `compliance_status` `VIOLATION_NOTICED → REVERTED` and,
    on the other dimension, `recording_status` `RECORDED → RESCINDED`, with
    `reverted_at` stamped from the logical clock; this is the only operation that
    drives both dimensions of a conveyance at once."

    Design: Difficulty/boundary_precision_check/revert_requires_clock_strictly_after_cure_deadline_instant
    """
    ctx = _breach_noticed_on_a_recorded_deed(api)
    fx.set_clock(api, "2027-02-14T00:00:01Z")

    conveyance = fx.revert_conveyance(api, ctx["conveyance"]["id"])
    assert conveyance["compliance_status"] == "REVERTED", (
        "one second past the deadline the reverter is enforceable, got "
        f"{conveyance['compliance_status']!r}"
    )
    assert conveyance["recording_status"] == "RESCINDED", (
        "and the recording dimension moves in the same operation, got "
        f"{conveyance['recording_status']!r}"
    )
    assert conveyance["reverted_at"] == "2027-02-14T00:00:01.000Z", (
        "stamped from the logical clock as it stood, got "
        f"{conveyance['reverted_at']!r}"
    )

    parcel = get_success_data(api.get_parcel(ctx["parcel"]["id"], fx.OFFICER_HEADERS))
    assert parcel["ownership_status"] == "REVERTED_TO_AGENCY", (
        "the land comes back to the agency, got " f"{parcel['ownership_status']!r}"
    )


def test_09_a_deposit_one_cent_short_of_the_requirement_is_refused(api):
    """4,999,999 against a requirement of 5,000,000 buys nothing at all.

    "Then `deposit_amount_cents` must be at least the offering's frozen
    `required_deposit_cents`, with exact equality sufficient and one cent short
    refused as `ERR_DEPOSIT_INSUFFICIENT` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/bid_deposit_exact_equality_passes_one_cent_short_fails
    """
    ctx = _offering_with_two_funded_bidders(api)
    assert ctx["offering"]["required_deposit_cents"] == 5000000, (
        "a twentieth of the frozen 99,750,000 is 4,987,500, which falls below the "
        "floor, so the requirement is the flat 5,000,000 cents, got "
        f"{ctx['offering']['required_deposit_cents']}"
    )

    response = _tender(api, ctx, "short_bidder", 4999999)
    validate_error(response, ApiErrorId.ERR_DEPOSIT_INSUFFICIENT.value, 422)

    bids = fx.bids_for_offering(api, ctx["offering"]["id"])
    assert bids == [], (
        f"the one-cent shortfall must leave no bid behind, got {bids!r}"
    )
    bidder = get_success_data(
        api.get_bidder(ctx["short_bidder"]["id"], fx.FINANCE_HEADERS)
    )
    assert bidder["available_funds_cents"] == 10000000, (
        "and must move nothing out of spendable cash, got "
        f"{bidder['available_funds_cents']}"
    )
    assert bidder["escrow_held_cents"] == 0, (
        f"nor into escrow, got {bidder['escrow_held_cents']}"
    )


def test_10_a_deposit_exactly_equal_to_the_requirement_is_sufficient(api):
    """5,000,000 exactly is accepted and the transfer into escrow is exact.

    "On success the bid is created with `qualification_status` `SUBMITTED` and
    `deposit_status` `HELD`, with `submitted_at` stamped from the logical clock,
    `award_rank` and `disqualification_reason` empty. The deposit moves out of
    spendable cash and into escrow in one transfer: the bidder's
    `available_funds_cents` falls by `deposit_amount_cents` and
    `escrow_held_cents` rises by exactly the same amount, while
    `lifetime_deposits_cents` is untouched — that counter records funding credits
    from treasury, never internal movements."

    Design: Difficulty/boundary_precision_check/bid_deposit_exact_equality_passes_one_cent_short_fails
    """
    ctx = _offering_with_two_funded_bidders(api)
    _tender(api, ctx, "short_bidder", 4999999)

    accepted = get_success_data(_tender(api, ctx, "exact_bidder", 5000000))
    assert accepted["deposit_amount_cents"] == 5000000, (
        "the tendered deposit is recorded as offered, got "
        f"{accepted['deposit_amount_cents']}"
    )
    assert accepted["qualification_status"] == "SUBMITTED", (
        f"the bid opens on the submitted status, got {accepted['qualification_status']!r}"
    )
    assert accepted["deposit_status"] == "HELD", (
        f"with its deposit held, got {accepted['deposit_status']!r}"
    )

    bidder = get_success_data(
        api.get_bidder(ctx["exact_bidder"]["id"], fx.FINANCE_HEADERS)
    )
    assert bidder["available_funds_cents"] == 5000000, (
        "10,000,000 credited less the 5,000,000 deposit leaves 5,000,000 "
        f"spendable, got {bidder['available_funds_cents']}"
    )
    assert bidder["escrow_held_cents"] == 5000000, (
        "and exactly the deposit sits in escrow, got "
        f"{bidder['escrow_held_cents']}"
    )

    bids = fx.bids_for_offering(api, ctx["offering"]["id"])
    assert len(bids) == 1, (
        "only the exact tender was admitted, so the offering carries one bid, got "
        f"{len(bids)}"
    )
    assert bids[0]["id"] == accepted["id"], (
        "and that bid is the one the exact tender created"
    )
