"""The declaration, the environmental document and the offering as state machines.

A declaration opens in draft and the board's acts are each recorded once and once
only. An environmental document's terminal state accepts nothing further, while
its recirculation loop returns it to circulation on a fresh window. Closing
bidding early is refused, and abandoning the declaration unwinds the whole market.
"""

from test_helpers import ApiErrorId, factories as f, fixtures as fx
from test_helpers import get_success_data, validate_error, validate_paginated, validate_success


def _drafted_declaration(api):
    """One custodian agency, one parcel it holds, and a declaration in draft."""
    ctx = {}
    ctx["agency"] = fx.make_agency(api)
    ctx["parcel"] = fx.make_parcel(api, ctx["agency"]["id"])
    ctx["declaration"] = fx.make_declaration(api, ctx["parcel"]["id"])
    return ctx


def _live_competitive_sale_with_one_bid(api):
    """A published competitive sale with one submitted bid, still inside its window.

    The clock never leaves the default instant, so the window running to
    2026-12-31 is still live and the field cannot yet be graded.
    """
    ctx = fx.build_valued_parcel(
        api,
        appraised_value_cents=100000000,
        book_value_cents=70000000,
        cured_lien_actual_cents=250000,
        lien_estimate_cents=250000,
    )
    ctx = fx.build_published_offering(api, ctx)
    ctx["bidder"] = fx.make_funded_bidder(api, 10000000)
    ctx["bid"] = fx.submit_bid(
        api,
        ctx["offering"]["id"],
        ctx["bidder"]["id"],
        amount_cents=108000000,
        deposit_amount_cents=ctx["offering"]["required_deposit_cents"],
    )
    return ctx


def test_01_a_new_declaration_opens_in_draft_with_every_counter_at_zero(api):
    """The create does not skip ahead to adoption even for the office that adopts.

    "The new declaration is created in `DRAFT` with `reoffer_count`,
    `preference_offer_count` and `unresolved_preference_count` all zero and every
    system field empty."

    Design: Corner/state_machines/new_declaration_starts_in_draft_status
    """
    agency = fx.make_agency(api)
    parcel = fx.make_parcel(api, agency["id"], apn="APN-2693-111")

    response = api.create_declaration(
        f.declaration_payload(parcel["id"]), fx.OFFICER_HEADERS
    )
    declaration = validate_success(response, 201)

    assert declaration["status"] == "DRAFT", (
        f"a declaration opens in draft, got {declaration['status']!r}"
    )
    assert declaration["reoffer_count"] == 0, (
        f"with no re-offer cycle taken, got {declaration['reoffer_count']}"
    )
    assert declaration["preference_offer_count"] == 0, (
        f"no preference offer against it, got {declaration['preference_offer_count']}"
    )
    assert declaration["unresolved_preference_count"] == 0, (
        "and nothing unresolved, got "
        f"{declaration['unresolved_preference_count']}"
    )
    for field in (
        "resolution_number",
        "adopted_by_user_id",
        "adopted_at",
        "notice_issued_at",
        "authorized_disposition_type",
        "reoffer_eligible_at",
    ):
        assert declaration.get(field) is None, (
            f"the system field {field} starts empty, got {declaration.get(field)!r}"
        )

    rows, meta = validate_paginated(
        api.list_declarations(fx.OFFICER_HEADERS, {"status": "DRAFT"})
    )
    assert meta["total_count"] == 1, (
        f"and it is findable by status, got {meta['total_count']}"
    )
    assert rows[0]["id"] == declaration["id"], "and the row found is the new draft"


def test_02_adoption_stamps_the_resolution_the_clerk_and_the_clock_together(api):
    """The board's act writes three fields at once, not merely a status flip.

    "The clerk supplies the `resolution_number` under which the board acted; the
    service stores it, writes the acting `X-User-ID` into `adopted_by_user_id`,
    stamps `adopted_at` from the logical clock, moves the declaration `DRAFT →
    ADOPTED`, and increments its `version` by 1."

    Design: Corner/state_machines/adopt_declaration_from_draft_reaches_adopted
    """
    ctx = _drafted_declaration(api)

    response = api.adopt_declaration(
        ctx["declaration"]["id"],
        f.adopt_payload(resolution_number="RES-2026-211"),
        fx.CLERK_ADOPT_HEADERS,
    )
    adopted = validate_success(response, 200)

    assert adopted["status"] == "ADOPTED", (
        f"the resolution carries the declaration forward, got {adopted['status']!r}"
    )
    assert adopted["resolution_number"] == "RES-2026-211", (
        f"the resolution number is stored, got {adopted['resolution_number']!r}"
    )
    assert adopted["adopted_by_user_id"] == "clerk-adopt-1", (
        "the acting clerk's identity is captured, got "
        f"{adopted['adopted_by_user_id']!r}"
    )
    assert adopted["adopted_at"] == "2026-08-01T00:00:00.000Z", (
        "and the instant is read from the logical clock, got "
        f"{adopted['adopted_at']!r}"
    )
    assert adopted["version"] == ctx["declaration"]["version"] + 1, (
        f"with the row version raised by one, got {adopted['version']}"
    )
    assert adopted["notice_issued_at"] is None, (
        "adoption does not serve the notice round, got "
        f"{adopted['notice_issued_at']!r}"
    )


def test_03_adopting_a_second_time_is_refused_and_preserves_the_first_record(api):
    """The first adoption is the record of the board's act and is not overwritten.

    "Any operation addressed at a declaration whose current `status` is not a
    from-state of the requested transition is refused with
    `ERR_INVALID_DECLARATION_STATE` (HTTP 409); this single code guards adoption,
    notice issuance, preference-window closure, disposition authorization,
    re-offering, withdrawal, opening an environmental review, creating an offering,
    appending a negotiation round and concluding a negotiation."

    Design: Corner/state_machines/adopt_declaration_twice_is_rejected
    """
    ctx = _drafted_declaration(api)
    fx.adopt_declaration(
        api, ctx["declaration"]["id"], resolution_number="RES-2026-212"
    )

    response = api.adopt_declaration(
        ctx["declaration"]["id"],
        f.adopt_payload(resolution_number="RES-2026-999"),
        fx.CLERK_AUTHORIZE_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_DECLARATION_STATE.value, 409)

    stored = get_success_data(
        api.get_declaration(ctx["declaration"]["id"], fx.OFFICER_HEADERS)
    )
    assert stored["resolution_number"] == "RES-2026-212", (
        "the second caller's resolution number is not written, got "
        f"{stored['resolution_number']!r}"
    )
    assert stored["adopted_by_user_id"] == "clerk-adopt-1", (
        "nor is the second caller's identity, got "
        f"{stored['adopted_by_user_id']!r}"
    )
    assert stored["status"] == "ADOPTED", (
        f"and the declaration is where it was, got {stored['status']!r}"
    )


def test_04_certifying_an_exempt_review_that_is_already_certified_is_refused(api):
    """The document's only terminal state accepts nothing further, not even a re-stamp.

    "A new review is created with `circulation_round` 1, `status` `CIRCULATING`,
    `certified_at` empty and `recirculation_reason` empty — except for an `EXEMPT`
    determination, which needs no public circulation at all and is created directly
    in `CERTIFIED` with `certified_at` stamped from the clock; for an `EXEMPT` review
    the supplied interval is ignored entirely, is not length-checked, and may be
    omitted." "A review that is not `CIRCULATING`, or one whose circulation has not
    yet run out, is refused with `ERR_INVALID_ENV_REVIEW_STATE` (HTTP 409)."

    Design: Corner/state_machines/certify_environmental_review_already_certified_is_rejected
    """
    ctx = _drafted_declaration(api)
    fx.adopt_declaration(
        api, ctx["declaration"]["id"], resolution_number="RES-2026-214"
    )
    review = fx.make_exempt_review(api, ctx["declaration"]["id"])
    assert review["status"] == "CERTIFIED", (
        f"an exempt determination arrives certified, got {review['status']!r}"
    )
    assert review["certified_at"] == "2026-08-01T00:00:00.000Z", (
        f"stamped from the clock, got {review['certified_at']!r}"
    )

    response = api.certify_environmental_review(review["id"], fx.OFFICER_HEADERS)
    validate_error(response, ApiErrorId.ERR_INVALID_ENV_REVIEW_STATE.value, 409)

    stored = get_success_data(
        api.get_environmental_review(review["id"], fx.OFFICER_HEADERS)
    )
    assert stored["certified_at"] == "2026-08-01T00:00:00.000Z", (
        f"the certification instant is not re-stamped, got {stored['certified_at']!r}"
    )
    assert stored["circulation_round"] == 1, (
        f"and the round counter is untouched, got {stored['circulation_round']}"
    )

    _, meta = validate_paginated(
        api.list_environmental_reviews(ctx["declaration"]["id"], fx.OFFICER_HEADERS)
    )
    assert meta["total_count"] == 1, (
        f"the refusal creates no second review, got {meta['total_count']}"
    )


def test_05_recirculation_returns_the_document_to_circulation_on_the_new_window(api):
    """The loop passes through the required state and comes straight back out.

    "A recirculation is a single operation that passes through
    `RECIRCULATION_REQUIRED` and returns immediately to `CIRCULATING` on the new
    window, so the review a client reads afterwards is `CIRCULATING` again;
    `circulation_round` rises by 1, both circulation dates are replaced by the
    supplied values, and `recirculation_reason` is stored. `certified_at` remains
    empty, since nothing has been certified yet."

    Design: Corner/state_machines/environmental_review_recirculation_increments_circulation_round
    """
    ctx = _drafted_declaration(api)
    fx.adopt_declaration(
        api, ctx["declaration"]["id"], resolution_number="RES-2026-215"
    )
    review = fx.make_circulating_review(
        api,
        ctx["declaration"]["id"],
        determination_class="NEGATIVE_DECLARATION",
        circulation_start_on="2026-09-01T00:00:00Z",
        circulation_end_on="2026-10-01T00:00:00Z",
    )
    assert review["status"] == "CIRCULATING", (
        f"the document goes out for comment, got {review['status']!r}"
    )
    assert review["circulation_round"] == 1, (
        f"on its first round, got {review['circulation_round']}"
    )

    reason = "Traffic study revised after the initial circulation closed"
    response = api.recirculate_environmental_review(
        review["id"],
        f.recirculate_payload(
            "2026-10-31T00:00:00Z",
            "2026-12-01T00:00:00Z",
            recirculation_reason=reason,
        ),
        fx.OFFICER_HEADERS,
    )
    recirculated = validate_success(response, 200)

    assert recirculated["status"] == "CIRCULATING", (
        "the review a client reads afterwards is circulating again, got "
        f"{recirculated['status']!r}"
    )
    assert recirculated["circulation_round"] == 2, (
        f"on its second round, got {recirculated['circulation_round']}"
    )
    assert recirculated["circulation_start_on"] == "2026-10-31T00:00:00Z", (
        "the start date is replaced, and 30 days after 2026-10-01 is the earliest "
        f"legal start, got {recirculated['circulation_start_on']!r}"
    )
    assert recirculated["circulation_end_on"] == "2026-12-01T00:00:00Z", (
        f"the end date is replaced too, got {recirculated['circulation_end_on']!r}"
    )
    assert recirculated["recirculation_reason"] == reason, (
        f"and the reason is stored, got {recirculated['recirculation_reason']!r}"
    )
    assert recirculated["certified_at"] is None, (
        f"nothing has been certified, got {recirculated['certified_at']!r}"
    )

    _, meta = validate_paginated(
        api.list_environmental_reviews(ctx["declaration"]["id"], fx.OFFICER_HEADERS)
    )
    assert meta["total_count"] == 1, (
        "recirculation mutates the standing review rather than filing a second, got "
        f"{meta['total_count']}"
    )


def test_06_closing_bidding_while_the_window_is_still_live_is_refused(api):
    """No bid is graded and no deposit moves when the window has not run out.

    "It is the officer's act, it requires the offering to be `OPEN` and of type
    `COMPETITIVE_SALE` — anything else is `ERR_INVALID_OFFERING_STATE` — and it
    requires the window to have actually run out, meaning the clock stands at or
    after `bid_close_at`; closing while bidding is still live is refused with
    `ERR_BIDDING_STILL_OPEN` (HTTP 409)."

    Design: Corner/state_machines/close_bidding_before_bid_close_at_is_rejected
    """
    ctx = _live_competitive_sale_with_one_bid(api)
    deposit = ctx["offering"]["required_deposit_cents"]

    response = api.close_bidding(ctx["offering"]["id"], fx.OFFICER_HEADERS)
    validate_error(response, ApiErrorId.ERR_BIDDING_STILL_OPEN.value, 409)

    offering = get_success_data(
        api.get_offering(ctx["offering"]["id"], fx.OFFICER_HEADERS)
    )
    assert offering["status"] == "OPEN", (
        f"the offering is still taking bids, got {offering['status']!r}"
    )
    assert offering["qualified_bid_count"] == 0, (
        f"and nothing has been graded, got {offering['qualified_bid_count']}"
    )

    bid = get_success_data(api.get_bid(ctx["bid"]["id"], fx.OFFICER_HEADERS))
    assert bid["qualification_status"] == "SUBMITTED", (
        f"the bid is ungraded, got {bid['qualification_status']!r}"
    )
    assert bid["deposit_status"] == "HELD", (
        f"and its deposit is still held, got {bid['deposit_status']!r}"
    )

    bidder = get_success_data(api.get_bidder(ctx["bidder"]["id"], fx.FINANCE_HEADERS))
    assert bidder["escrow_held_cents"] == deposit, (
        f"no deposit moved, got {bidder['escrow_held_cents']}"
    )
    assert bidder["available_funds_cents"] == 10000000 - deposit, (
        f"on either side of the ledger, got {bidder['available_funds_cents']}"
    )


def test_07_withdrawing_the_declaration_cancels_the_offering_and_frees_the_escrow(api):
    """One abandonment fires all three links and leaves no money in escrow.

    "From `OFFERING_AUTHORIZED` the withdrawal also unwinds the market in three
    linked steps: every offering on this declaration whose `status` is `DRAFT`,
    `OPEN` or `EVALUATION` moves to `CANCELLED`; every live bid on those offerings —
    meaning every bid whose `qualification_status` is `SUBMITTED`, `QUALIFIED`,
    `WINNING` or `BACKUP` — moves to `WITHDRAWN`; and every one of those bids whose
    `deposit_status` is `HELD` moves to `RELEASED`, with `escrow_held_cents` falling
    and `available_funds_cents` rising by that bid's `deposit_amount_cents` on the
    bidder concerned."

    Design: Corner/state_machines/withdraw_declaration_cancels_live_offering_and_releases_deposits
    """
    ctx = _live_competitive_sale_with_one_bid(api)
    reason = "Council rescinded the surplus finding after a school-siting study"

    response = api.withdraw_declaration(
        ctx["declaration"]["id"],
        f.withdraw_declaration_payload(withdrawn_reason=reason),
        fx.CLERK_AUTHORIZE_HEADERS,
    )
    withdrawn = validate_success(response, 200)
    assert withdrawn["status"] == "WITHDRAWN", (
        f"the declaration is abandoned, got {withdrawn['status']!r}"
    )
    assert withdrawn["withdrawn_reason"] == reason, (
        f"with the reason recorded, got {withdrawn['withdrawn_reason']!r}"
    )

    offering = get_success_data(
        api.get_offering(ctx["offering"]["id"], fx.OFFICER_HEADERS)
    )
    assert offering["status"] == "CANCELLED", (
        f"the live offering is cancelled with it, got {offering['status']!r}"
    )
    assert offering["cancellation_reason"] == reason, (
        "and the reason the offering died is legible on the offering itself, got "
        f"{offering['cancellation_reason']!r}"
    )

    bid = get_success_data(api.get_bid(ctx["bid"]["id"], fx.OFFICER_HEADERS))
    assert bid["qualification_status"] == "WITHDRAWN", (
        f"the live bid is withdrawn, got {bid['qualification_status']!r}"
    )
    assert bid["deposit_status"] == "RELEASED", (
        f"and its deposit released, got {bid['deposit_status']!r}"
    )

    bidder = get_success_data(api.get_bidder(ctx["bidder"]["id"], fx.FINANCE_HEADERS))
    assert bidder["escrow_held_cents"] == 0, (
        "a withdrawal never leaves a bidder's money in escrow, got "
        f"{bidder['escrow_held_cents']}"
    )
    assert bidder["available_funds_cents"] == 10000000, (
        f"the whole credit is spendable again, got {bidder['available_funds_cents']}"
    )
    assert bidder["lifetime_deposits_cents"] == 10000000, (
        "and the release was a transfer, not a new credit, got "
        f"{bidder['lifetime_deposits_cents']}"
    )

    parcel = get_success_data(api.get_parcel(ctx["parcel"]["id"], fx.OFFICER_HEADERS))
    assert parcel["ownership_status"] == "AGENCY_OWNED", (
        "and the agency still holds the land, got "
        f"{parcel['ownership_status']!r}"
    )
