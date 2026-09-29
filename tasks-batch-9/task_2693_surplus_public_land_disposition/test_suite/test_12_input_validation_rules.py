"""Refusals that turn on state elsewhere rather than on the shape of the payload.

Each request here is individually well-formed: a timely-looking response, a valid
category claim, a bid clearing both fiscal floors, a deed restriction inside its
count bound, a notice round of two registered-looking recipients. Every one is
refused on a fact held by a different row, and nothing is written either way.
"""

from test_helpers import ApiErrorId, factories as f, fixtures as fx
from test_helpers import get_success_data, validate_error, validate_paginated, validate_success
from test_helpers.test_users import make_agency_representative_headers


def _noticed_declaration(api, recipient, apn, resolution_number, window_days=60):
    """A declaration adopted and noticed on one recipient at the default clock."""
    ctx = {}
    ctx["agency"] = fx.make_agency(api)
    ctx["recipient"] = recipient
    ctx["parcel"] = fx.make_parcel(api, ctx["agency"]["id"], apn=apn)
    ctx["declaration"] = fx.make_adopted_declaration(
        api, ctx["parcel"]["id"], resolution_number=resolution_number
    )
    ctx["notices"] = fx.issue_notices(
        api, ctx["declaration"]["id"], [recipient["id"]], window_days
    )
    ctx["notice"] = ctx["notices"][0]
    return ctx


def _offers_under(api, declaration_id):
    """Every preference offer opened under one declaration."""
    return validate_paginated(
        api.list_preference_offers(
            fx.OFFICER_HEADERS, {"declaration_id": declaration_id, "limit": 100}
        )
    )


def test_01_a_response_one_day_past_the_notices_own_deadline_is_refused(api):
    """Standing and a matching claim do not rescue a response filed too late.

    "Responding is the recipient agency's own act, permitted only while the notice
    is `ISSUED` — a notice already answered or expired is
    `ERR_INVALID_NOTICE_STATE` (HTTP 409) — and only while the clock stands at or
    before that notice's own `response_deadline_at`; a response one instant later
    is `ERR_NOTICE_RESPONSE_LATE` (HTTP 409), while a response exactly on the
    deadline instant is timely."

    Design: Corner/validations/notice_response_after_deadline_is_rejected
    """
    housing = fx.make_preference_agency(api)
    ctx = _noticed_declaration(api, housing, "APN-2693-141", "RES-2026-241", 60)
    assert ctx["notice"]["response_deadline_at"] == "2026-09-30T00:00:00.000Z", (
        "60 days after 2026-08-01 is 2026-09-30, got "
        f"{ctx['notice']['response_deadline_at']!r}"
    )

    fx.set_clock(api, "2026-10-01T00:00:00Z")
    response = api.respond_to_notice(
        ctx["notice"]["id"],
        f.express_interest_payload(
            "AFFORDABLE_HOUSING",
            intended_use="62-unit affordable rental development",
        ),
        make_agency_representative_headers(housing["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOTICE_RESPONSE_LATE.value, 409)

    notice = get_success_data(api.get_notice(ctx["notice"]["id"], fx.OFFICER_HEADERS))
    assert notice["status"] == "ISSUED", (
        f"the notice is left outstanding, got {notice['status']!r}"
    )
    assert notice["responded_at"] is None, (
        f"with no response instant stamped, got {notice['responded_at']!r}"
    )
    assert notice["response_type"] is None, (
        f"and no response type recorded, got {notice['response_type']!r}"
    )

    _, meta = _offers_under(api, ctx["declaration"]["id"])
    assert meta["total_count"] == 0, (
        "a late expression of interest opens no negotiation even from a genuine "
        f"preference entity, got {meta['total_count']}"
    )
    declaration = get_success_data(
        api.get_declaration(ctx["declaration"]["id"], fx.OFFICER_HEADERS)
    )
    assert declaration["preference_offer_count"] == 0, (
        f"so the parent counts none, got {declaration['preference_offer_count']}"
    )
    assert declaration["status"] == "NOTICED", (
        f"and the round is still running, got {declaration['status']!r}"
    )


def test_02_a_non_preference_recipient_may_decline_but_may_not_claim_a_right(api):
    """The same notice inside the same window answers one way and not the other.

    "Declining is the simpler branch and imposes no standing requirement of its
    own: `responded_at` is stamped from the clock, `response_type` is recorded as
    `DECLINE`, the notice moves `ISSUED → DECLINED`, and no preference offer is
    created. Expressing interest is only open to an agency that actually holds a
    statutory preference right: if the recipient's `is_preference_entity` is false
    the response is refused with `ERR_NOT_PREFERENCE_ENTITY` (HTTP 422)."

    Design: Corner/validations/express_interest_from_non_preference_agency_is_rejected
    """
    district = fx.make_transit_agency(api)
    assert district["is_preference_entity"] is False, (
        "the neighbouring district holds no statutory preference, got "
        f"{district['is_preference_entity']!r}"
    )
    ctx = _noticed_declaration(api, district, "APN-2693-142", "RES-2026-242", 60)
    headers = make_agency_representative_headers(district["id"])

    claimed = api.respond_to_notice(
        ctx["notice"]["id"],
        f.express_interest_payload("PARK_OPEN_SPACE", intended_use="Bus layover yard"),
        headers,
    )
    validate_error(claimed, ApiErrorId.ERR_NOT_PREFERENCE_ENTITY.value, 422)

    still_open = get_success_data(
        api.get_notice(ctx["notice"]["id"], fx.OFFICER_HEADERS)
    )
    assert still_open["status"] == "ISSUED", (
        "the refusal leaves the notice answerable, got "
        f"{still_open['status']!r}"
    )

    declined = validate_success(
        api.respond_to_notice(ctx["notice"]["id"], f.decline_response_payload(), headers),
        200,
    )
    assert declined["status"] == "DECLINED", (
        "the very same recipient may decline the same notice, got "
        f"{declined['status']!r}"
    )
    assert declined["responded_at"] == "2026-08-01T00:00:00.000Z", (
        f"stamped from the clock, got {declined['responded_at']!r}"
    )

    _, meta = _offers_under(api, ctx["declaration"]["id"])
    assert meta["total_count"] == 0, (
        f"and neither branch opened a negotiation, got {meta['total_count']}"
    )
    declaration = get_success_data(
        api.get_declaration(ctx["declaration"]["id"], fx.OFFICER_HEADERS)
    )
    assert declaration["preference_offer_count"] == 0, (
        f"the parent counts no offer, got {declaration['preference_offer_count']}"
    )
    assert declaration["unresolved_preference_count"] == 0, (
        f"and nothing unresolved, got {declaration['unresolved_preference_count']}"
    )


def test_03_a_debarred_bidder_is_refused_even_with_a_faultless_tender(api):
    """The bid clears both fiscal floors and dies on the bidder's own standing.

    "The bidder's `debarment_status` must be `CLEAR`, or `ERR_BIDDER_DEBARRED`
    (HTTP 422)."

    Design: Corner/validations/bid_from_debarred_bidder_is_rejected
    """
    ctx = fx.build_valued_parcel(
        api, apn="APN-2693-143", appraised_value_cents=100000000
    )
    ctx = fx.build_published_offering(api, ctx)
    assert ctx["offering"]["minimum_price_cents"] == 100000000, (
        "with no cured item to deduct the minimum is the appraised value, got "
        f"{ctx['offering']['minimum_price_cents']}"
    )
    assert ctx["offering"]["required_deposit_cents"] == 5000000, (
        "and five hundredths of it is exactly the 5,000,000 floor, got "
        f"{ctx['offering']['required_deposit_cents']}"
    )

    bidder = fx.make_funded_bidder(api, 10000000)
    debarred = fx.debar_bidder(api, bidder["id"])
    assert debarred["debarment_status"] == "DEBARRED", (
        f"the bidder is out, got {debarred['debarment_status']!r}"
    )

    response = api.submit_bid(
        ctx["offering"]["id"],
        f.bid_payload(amount_cents=108000000, deposit_amount_cents=5000000),
        fx.make_bidder_headers(bidder["id"]),
    )
    validate_error(response, ApiErrorId.ERR_BIDDER_DEBARRED.value, 422)

    reread = get_success_data(api.get_bidder(bidder["id"], fx.FINANCE_HEADERS))
    assert reread["available_funds_cents"] == 10000000, (
        "the refused tender moves no money off the spendable side, got "
        f"{reread['available_funds_cents']}"
    )
    assert reread["escrow_held_cents"] == 0, (
        f"and puts nothing into escrow, got {reread['escrow_held_cents']}"
    )

    _, meta = validate_paginated(
        api.list_bids(
            fx.OFFICER_HEADERS, {"offering_id": ctx["offering"]["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 0, (
        f"and files no bid on the offering, got {meta['total_count']}"
    )


def test_04_a_deed_with_fewer_clauses_than_reserved_easements_is_refused(api):
    """One clause is well-formed on its own and still short of the two burdens kept.

    "Then the deed must carry every burden the agency chose to keep: the number of
    entries in `deed_restrictions` must be at least the number of title curative
    items on the parcel whose `status` is `RESERVED_AS_EASEMENT`, and a deed with
    fewer clauses than reserved easements is refused with
    `ERR_EASEMENT_RESERVATION_MISSING` (HTTP 422)."

    Design: Corner/validations/create_conveyance_with_fewer_deed_restrictions_than_reserved_easements_is_rejected
    """
    agency = fx.make_agency(api)
    parcel = fx.make_parcel(api, agency["id"], apn="APN-2693-144")
    storm = fx.open_title_item(
        api,
        parcel["id"],
        item_type="MISSING_ACCESS_EASEMENT",
        description="No recorded access easement for the rear storm line",
        cure_cost_estimate_cents=5000000,
    )
    feeder = fx.open_title_item(
        api,
        parcel["id"],
        item_type="MISSING_ACCESS_EASEMENT",
        description="No recorded easement for the overhead feeder crossing",
        cure_cost_estimate_cents=3000000,
    )
    fx.reserve_title_item_as_easement(
        api,
        storm["id"],
        easement_purpose="Storm drain access reserved to the City",
        easement_area_sqft=1800.0,
    )
    fx.reserve_title_item_as_easement(
        api,
        feeder["id"],
        easement_purpose="Overhead electrical feeder reserved to the City",
        easement_area_sqft=900.0,
    )
    appraiser = fx.make_appraiser(api)
    fx.make_accepted_appraisal(
        api, parcel["id"], appraiser["id"], appraised_value_cents=100000000
    )
    ctx = fx.build_awarded_offering(
        api,
        {"agency": agency, "parcel": parcel, "appraiser": appraiser},
        bid_amount_cents=108000000,
    )
    assert ctx["offering"]["minimum_price_cents"] == 100000000, (
        "the two reserved easements deduct nothing from the minimum, got "
        f"{ctx['offering']['minimum_price_cents']}"
    )

    response = api.create_conveyance(
        ctx["offering"]["id"],
        f.conveyance_payload(
            deed_restrictions=["Industrial use only for 30 years"],
            reverter_condition=(
                "Reverts if the industrial use ceases for 24 consecutive months"
            ),
        ),
        fx.OFFICER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_EASEMENT_RESERVATION_MISSING.value, 422)

    _, easement_meta = validate_paginated(
        api.list_parcel_title_items(
            parcel["id"], fx.OFFICER_HEADERS, {"status": "RESERVED_AS_EASEMENT"}
        )
    )
    assert easement_meta["total_count"] == 2, (
        f"two burdens are still reserved on the parcel, got {easement_meta['total_count']}"
    )

    _, conveyance_meta = validate_paginated(
        api.list_conveyances(
            fx.OFFICER_HEADERS, {"offering_id": ctx["offering"]["id"], "limit": 100}
        )
    )
    assert conveyance_meta["total_count"] == 0, (
        f"and no conveyance file was opened, got {conveyance_meta['total_count']}"
    )

    offering = get_success_data(
        api.get_offering(ctx["offering"]["id"], fx.OFFICER_HEADERS)
    )
    assert offering["status"] == "AWARDED", (
        f"the award stands, got {offering['status']!r}"
    )
    assert offering["winning_bid_amount_cents"] == 108000000, (
        f"at the winning amount, got {offering['winning_bid_amount_cents']}"
    )
    bid = get_success_data(api.get_bid(ctx["bid"]["id"], fx.OFFICER_HEADERS))
    assert bid["qualification_status"] == "WINNING", (
        f"the winner is still the winner, got {bid['qualification_status']!r}"
    )
    assert bid["deposit_status"] == "HELD", (
        "and its deposit is still held rather than applied, got "
        f"{bid['deposit_status']!r}"
    )


def test_05_one_lapsed_recipient_defeats_the_whole_notice_round(api):
    """The registered co-recipient is not served either; the round is atomic.

    "Every recipient must be in good standing on the registry at the moment of
    service: if any one of them has `notice_registry_status` `LAPSED`, the whole
    round is refused with `ERR_NOTICE_REGISTRY_LAPSED` (HTTP 422) and no notice is
    created."

    Design: Corner/validations/issue_notices_to_lapsed_registry_agency_is_rejected
    """
    custodian = fx.make_agency(api)
    housing = fx.make_preference_agency(api)
    district = fx.make_transit_agency(api)
    lapsed = fx.lapse_agency_registry(api, district["id"])
    assert lapsed["notice_registry_status"] == "LAPSED", (
        "the district's registry standing has lapsed, got "
        f"{lapsed['notice_registry_status']!r}"
    )
    assert housing["notice_registry_status"] == "REGISTERED", (
        "while the housing authority remains in good standing, got "
        f"{housing['notice_registry_status']!r}"
    )

    parcel = fx.make_parcel(api, custodian["id"], apn="APN-2693-145")
    declaration = fx.make_adopted_declaration(
        api, parcel["id"], resolution_number="RES-2026-245"
    )

    response = api.issue_notices(
        declaration["id"],
        f.issue_notices_payload([housing["id"], district["id"]], 60),
        fx.OFFICER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_NOTICE_REGISTRY_LAPSED.value, 422)

    _, notice_meta = validate_paginated(
        api.list_notices(
            fx.OFFICER_HEADERS, {"declaration_id": declaration["id"], "limit": 100}
        )
    )
    assert notice_meta["total_count"] == 0, (
        "the recipient in good standing was not served either, got "
        f"{notice_meta['total_count']}"
    )

    reread = get_success_data(api.get_declaration(declaration["id"], fx.OFFICER_HEADERS))
    assert reread["status"] == "ADOPTED", (
        f"the declaration has not moved on, got {reread['status']!r}"
    )
    for field in (
        "notice_issued_at",
        "notice_response_window_days",
        "notice_response_deadline_at",
    ):
        assert reread.get(field) is None, (
            f"and {field} is still empty, got {reread.get(field)!r}"
        )

    _, agency_meta = validate_paginated(
        api.list_agencies(
            fx.ADMIN_HEADERS, {"notice_registry_status": "LAPSED", "limit": 100}
        )
    )
    assert agency_meta["total_count"] == 1, (
        "exactly one agency stands lapsed on the registry, got "
        f"{agency_meta['total_count']}"
    )
