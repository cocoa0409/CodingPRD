"""The authorization layers, each proved distinct by a contrasting call.

Every test here fires the same request twice against the same path, changing only
the principal, so the refused layer is isolated from every other reason the call
could fail. Where the path names a fabricated id, the contrast call reaches the
existence layer and answers 404 — which is what proves the first refusal came
from authorization rather than from the missing row.
"""

from test_helpers import ApiErrorId, UserRole, factories as f, fixtures as fx
from test_helpers import (
    NON_EXISTENT_UUID,
    get_success_data,
    headers_without_user_id,
    validate_error,
    validate_paginated,
    validate_success,
)


def _two_housing_authorities_noticed(api):
    """Two preference agencies in the same category, both served the same round."""
    ctx = {}
    ctx["custodian"] = fx.make_agency(api)
    ctx["agency_a"] = fx.make_preference_agency(api, "AFFORDABLE_HOUSING")
    ctx["agency_b"] = fx.make_preference_agency(
        api,
        "AFFORDABLE_HOUSING",
        name="Northside Housing Commission",
        contact_email="clerk@northsidehousing.gov",
    )
    ctx["parcel"] = fx.make_parcel(api, ctx["custodian"]["id"], apn="APN-2693-171")
    ctx["declaration"] = fx.make_adopted_declaration(
        api, ctx["parcel"]["id"], resolution_number="RES-2026-271"
    )
    fx.issue_notices(
        api,
        ctx["declaration"]["id"],
        [ctx["agency_a"]["id"], ctx["agency_b"]["id"]],
        60,
    )
    ctx["notice_a"] = fx.notice_for_recipient(
        api, ctx["declaration"]["id"], ctx["agency_a"]["id"]
    )
    return ctx


def _ordered_engagement_and_a_rival_appraiser(api):
    """One appraisal engaged to the first of two equally licensed appraisers."""
    ctx = {}
    ctx["agency"] = fx.make_agency(api)
    ctx["parcel"] = fx.make_parcel(api, ctx["agency"]["id"], apn="APN-2693-172")
    ctx["engaged"] = fx.make_appraiser(api, license_number="AG-44272")
    ctx["rival"] = fx.make_appraiser(
        api, name="Marcus Vane MAI", license_number="AG-44273"
    )
    ctx["appraisal"] = fx.order_appraisal(
        api, ctx["parcel"]["id"], ctx["engaged"]["id"]
    )
    return ctx


def _challenge_against_a_declaration_adopted_by_the_same_clerk(api):
    """A submitted challenge whose parent resolution clerk-adopt-1 moved."""
    ctx = {}
    ctx["custodian"] = fx.make_agency(api)
    ctx["challenger"] = fx.make_transit_agency(api)
    ctx["parcel"] = fx.make_parcel(api, ctx["custodian"]["id"], apn="APN-2693-173")
    ctx["appraiser"] = fx.make_appraiser(api, license_number="AG-44274")
    ctx["appraisal"] = fx.make_reported_appraisal(
        api, ctx["parcel"]["id"], ctx["appraiser"]["id"], 100000000
    )
    ctx["declaration"] = fx.make_adopted_declaration(
        api, ctx["parcel"]["id"], resolution_number="RES-2026-274"
    )
    fx.issue_notices(api, ctx["declaration"]["id"], [ctx["challenger"]["id"]], 60)
    ctx["challenge"] = fx.file_challenge(
        api,
        ctx["appraisal"]["id"],
        ctx["challenger"]["id"],
        asserted_value_cents=95000000,
        deposit_paid_cents=1000000,
        grounds="Two of the four comparables are outside the industrial submarket",
    )
    return ctx


def test_01_a_bid_carrying_no_user_id_header_never_reaches_any_later_layer(api):
    """The role header alone is not an identity, and 401 precedes the 404.

    "If `X-User-Role` is absent or does not name one of the eight declared roles,
    or if `X-User-ID` is absent or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)." "Presence of both headers is checked before
    anything else about the request — the role header first, then the user id
    header."

    Design: Corner/rbac/bid_missing_x_user_id_header_returns_unauthenticated
    """
    bidder = fx.make_bidder(api)
    tender = f.bid_payload(amount_cents=108000000, deposit_amount_cents=5000000)

    headerless = api.submit_bid(
        NON_EXISTENT_UUID,
        tender,
        headers_without_user_id(UserRole.BIDDER.value),
    )
    validate_error(headerless, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    identified = api.submit_bid(
        NON_EXISTENT_UUID, tender, fx.make_bidder_headers(bidder["id"])
    )
    validate_error(identified, ApiErrorId.ERR_OFFERING_NOT_FOUND.value, 404)

    reread = get_success_data(api.get_bidder(bidder["id"], fx.FINANCE_HEADERS))
    assert reread["available_funds_cents"] == 0, (
        "neither attempt moved money, got " f"{reread['available_funds_cents']}"
    )
    assert reread["escrow_held_cents"] == 0, (
        f"nor took a deposit, got {reread['escrow_held_cents']}"
    )
    _, meta = validate_paginated(api.list_bids(fx.OFFICER_HEADERS, {"limit": 100}))
    assert meta["total_count"] == 0, (
        f"and no bid was written at all, got {meta['total_count']}"
    )


def test_02_a_bidder_publishing_an_offering_is_refused_before_the_row_is_looked_up(api):
    """The same fabricated id answers 403 to one role and 404 to another.

    "Once the headers are accepted, the acting role must appear on the list of
    roles the addressed endpoint declares; if it does not, the request is rejected
    with `ERR_UNAUTHORIZED` (HTTP 403)." "Authorization follows: the endpoint's role
    list, then entity-backed identity resolution, then resource ownership, then the
    engaged-appraiser check, then segregation of duties."

    Design: Corner/rbac/bidder_cannot_publish_offering_returns_unauthorized
    """
    bidder = fx.make_bidder(api)

    forbidden = api.publish_offering(
        NON_EXISTENT_UUID, fx.make_bidder_headers(bidder["id"])
    )
    validate_error(forbidden, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    missing = api.publish_offering(NON_EXISTENT_UUID, fx.OFFICER_HEADERS)
    validate_error(missing, ApiErrorId.ERR_OFFERING_NOT_FOUND.value, 404)

    _, meta = validate_paginated(api.list_offerings(fx.OFFICER_HEADERS, {"limit": 100}))
    assert meta["total_count"] == 0, (
        "the store holds no offering, so the 403 cannot have come from the "
        f"missing row, got {meta['total_count']}"
    )


def test_03_an_agency_id_presented_as_a_bidder_principal_is_not_resolvable(api):
    """A real id of the wrong entity is a 403, not a 401 and not a 404.

    "When `X-User-Role` is `Bidder`, `X-User-ID` is the `id` of the acting
    `Bidder`; ownership checks compare a bid's bidder reference to `X-User-ID`."
    "For all three, an `X-User-ID` that resolves to no row of the backing entity is
    rejected with `ERR_IDENTITY_NOT_RESOLVABLE` (HTTP 403). This resolution check
    runs after the role-permission check and before any ownership comparison."

    Design: Corner/rbac/entity_backed_bidder_id_not_resolvable_returns_forbidden
    """
    agency = fx.make_agency(api)
    bidder = fx.make_bidder(api)
    tender = f.bid_payload(amount_cents=108000000, deposit_amount_cents=5000000)

    impostor = api.submit_bid(
        NON_EXISTENT_UUID, tender, fx.make_bidder_headers(agency["id"])
    )
    validate_error(impostor, ApiErrorId.ERR_IDENTITY_NOT_RESOLVABLE.value, 403)

    genuine = api.submit_bid(
        NON_EXISTENT_UUID, tender, fx.make_bidder_headers(bidder["id"])
    )
    validate_error(genuine, ApiErrorId.ERR_OFFERING_NOT_FOUND.value, 404)

    _, meta = validate_paginated(api.list_bids(fx.OFFICER_HEADERS, {"limit": 100}))
    assert meta["total_count"] == 0, (
        f"neither attempt wrote a bid, got {meta['total_count']}"
    )


def test_04_one_housing_authority_may_not_answer_the_other_s_notice(api):
    """Same role, same grant, same category — and still confined to its own notice.

    "Ownership is enforced in three places. Responding to a statutory notice
    requires `X-User-ID` to equal the notice's `recipient_agency_id`; tendering a
    negotiation round as the preference entity requires `X-User-ID` to equal the
    offer's `offeror_agency_id`; withdrawing a bid requires `X-User-ID` to equal the
    bid's `bidder_id`. A mismatch in any of the three is `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403)."

    Design: Corner/rbac/agency_representative_cannot_respond_to_another_agencys_notice
    """
    ctx = _two_housing_authorities_noticed(api)
    notice_a = ctx["notice_a"]
    assert notice_a["recipient_agency_id"] == ctx["agency_a"]["id"], (
        "the notice under test was served on the first authority, got "
        f"{notice_a['recipient_agency_id']!r}"
    )

    intruder = api.respond_to_notice(
        notice_a["id"],
        f.express_interest_payload(
            "AFFORDABLE_HOUSING",
            intended_use="48-unit affordable rental development",
        ),
        fx.make_agency_representative_headers(ctx["agency_b"]["id"]),
    )
    validate_error(intruder, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    untouched = get_success_data(api.get_notice(notice_a["id"], fx.OFFICER_HEADERS))
    assert untouched["status"] == "ISSUED", (
        f"the notice is still awaiting its own recipient, got {untouched['status']!r}"
    )
    _, none_yet = validate_paginated(
        api.list_preference_offers(
            fx.OFFICER_HEADERS,
            {"declaration_id": ctx["declaration"]["id"], "limit": 100},
        )
    )
    assert none_yet["total_count"] == 0, (
        f"and no negotiation was opened, got {none_yet['total_count']}"
    )

    owner = validate_success(
        api.respond_to_notice(
            notice_a["id"],
            f.express_interest_payload(
                "AFFORDABLE_HOUSING",
                intended_use="62-unit affordable rental development",
            ),
            fx.make_agency_representative_headers(ctx["agency_a"]["id"]),
        ),
        200,
    )
    assert owner["status"] == "INTEREST_EXPRESSED", (
        "the recipient's own answer is accepted, got " f"{owner['status']!r}"
    )
    assert owner["intended_use"] == "62-unit affordable rental development", (
        f"with its stated use recorded, got {owner['intended_use']!r}"
    )

    rows, meta = validate_paginated(
        api.list_preference_offers(
            fx.OFFICER_HEADERS,
            {"declaration_id": ctx["declaration"]["id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one negotiation is opened, got {meta['total_count']}"
    )
    assert rows[0]["offeror_agency_id"] == ctx["agency_a"]["id"], (
        "for the agency that actually answered, got "
        f"{rows[0]['offeror_agency_id']!r}"
    )
    declaration = get_success_data(
        api.get_declaration(ctx["declaration"]["id"], fx.OFFICER_HEADERS)
    )
    assert declaration["preference_offer_count"] == 1, (
        f"and the parent counts one offer, got {declaration['preference_offer_count']}"
    )


def test_05_an_unengaged_appraiser_may_not_deliver_the_report(api):
    """The grant is per engagement, and the refusal has its own distinct code.

    "Delivering an appraisal report has its own, distinct code: only the engaged
    appraiser may report, and an acting `Appraiser` whose `X-User-ID` differs from
    the appraisal's `appraiser_id` is refused with `ERR_NOT_ENGAGED_APPRAISER`
    (HTTP 403)."

    Design: Corner/rbac/appraiser_cannot_report_on_an_engagement_of_another_appraiser
    """
    ctx = _ordered_engagement_and_a_rival_appraiser(api)

    intruder = api.report_appraisal(
        ctx["appraisal"]["id"],
        f.appraisal_report_payload(
            61000000,
            narrative="Drive-by opinion prepared without the engagement.",
        ),
        fx.make_appraiser_headers(ctx["rival"]["id"]),
    )
    validate_error(intruder, ApiErrorId.ERR_NOT_ENGAGED_APPRAISER.value, 403)

    untouched = get_success_data(
        api.get_appraisal(ctx["appraisal"]["id"], fx.OFFICER_HEADERS)
    )
    assert untouched["status"] == "ORDERED", (
        f"the engagement is still awaiting its report, got {untouched['status']!r}"
    )
    assert untouched["appraised_value_cents"] is None, (
        "with no value recorded, got " f"{untouched['appraised_value_cents']!r}"
    )
    assert untouched["reported_at"] is None, (
        f"nothing stamped, got {untouched['reported_at']!r}"
    )
    assert untouched["expires_on"] is None, (
        "and no validity window opened, got " f"{untouched['expires_on']!r}"
    )

    delivered = validate_success(
        api.report_appraisal(
            ctx["appraisal"]["id"],
            f.appraisal_report_payload(100000000),
            fx.make_appraiser_headers(ctx["engaged"]["id"]),
        ),
        200,
    )
    assert delivered["status"] == "REPORTED", (
        "the engaged appraiser's report is accepted, got "
        f"{delivered['status']!r}"
    )
    assert delivered["appraised_value_cents"] == 100000000, (
        f"at the value it names, got {delivered['appraised_value_cents']}"
    )
    assert delivered["expires_on"] == "2027-08-01T00:00:00.000Z", (
        "opening a validity window one year from the effective date, got "
        f"{delivered['expires_on']!r}"
    )

    rival = get_success_data(api.get_appraiser(ctx["rival"]["id"], fx.OFFICER_HEADERS))
    assert rival["active_engagement_count"] == 0, (
        "and the refused appraiser holds no engagement at all, got "
        f"{rival['active_engagement_count']}"
    )


def test_06_the_clerk_who_adopted_the_resolution_may_not_rule_on_the_challenge(api):
    """The bar is on the operator identity, so a second clerk in the same role rules.

    "The `BoardClerk` who determines an appraisal challenge must not be the same
    `X-User-ID` recorded in `adopted_by_user_id` on the declaration covering that
    appraisal's parcel — the same person may not both adopt the surplus resolution
    and rule on a challenge to the valuation that resolution depends on." "Either
    violation is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), evaluated with
    the other authorization checks and therefore before any state or business rule
    on the same request."

    Design: Corner/rbac/same_clerk_cannot_adopt_declaration_and_determine_its_appraisal_challenge
    """
    ctx = _challenge_against_a_declaration_adopted_by_the_same_clerk(api)
    assert ctx["declaration"]["adopted_by_user_id"] == "clerk-adopt-1", (
        "the resolution was moved by the adopting clerk, got "
        f"{ctx['declaration']['adopted_by_user_id']!r}"
    )

    same_hand = api.determine_challenge(
        ctx["challenge"]["id"],
        f.sustain_determination_payload(95000000),
        fx.CLERK_ADOPT_HEADERS,
    )
    validate_error(same_hand, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    held = get_success_data(
        api.get_challenge(ctx["challenge"]["id"], fx.OFFICER_HEADERS)
    )
    assert held["status"] == "SUBMITTED", (
        f"the challenge is undetermined, got {held['status']!r}"
    )
    assert held["determined_by_user_id"] is None, (
        "with nobody recorded as having ruled, got "
        f"{held['determined_by_user_id']!r}"
    )
    parent = get_success_data(
        api.get_appraisal(ctx["appraisal"]["id"], fx.OFFICER_HEADERS)
    )
    assert parent["status"] == "CHALLENGED", (
        f"the appraisal is still out on challenge, got {parent['status']!r}"
    )
    assert parent["appraised_value_cents"] == 100000000, (
        "at the value the report named, got " f"{parent['appraised_value_cents']}"
    )

    other_hand = validate_success(
        api.determine_challenge(
            ctx["challenge"]["id"],
            f.sustain_determination_payload(95000000),
            fx.CLERK_DETERMINE_HEADERS,
        ),
        200,
    )
    assert other_hand["status"] == "SUSTAINED", (
        "a different clerk in the identical role rules on it, got "
        f"{other_hand['status']!r}"
    )
    assert other_hand["determined_by_user_id"] == "clerk-determine-1", (
        "and is recorded as the deciding hand, got "
        f"{other_hand['determined_by_user_id']!r}"
    )
    assert other_hand["deposit_refunded_cents"] == 1000000, (
        "a sustained challenge returns the whole deposit, got "
        f"{other_hand['deposit_refunded_cents']}"
    )
    assert other_hand["deposit_forfeited_cents"] == 0, (
        f"forfeiting nothing, got {other_hand['deposit_forfeited_cents']}"
    )

    revised = get_success_data(
        api.get_appraisal(ctx["appraisal"]["id"], fx.OFFICER_HEADERS)
    )
    assert revised["status"] == "REPORTED", (
        "the appraisal returns to the reported side, got " f"{revised['status']!r}"
    )
    assert revised["appraised_value_cents"] == 95000000, (
        "carrying the revised value, got " f"{revised['appraised_value_cents']}"
    )
    assert revised["challenge_count"] == 1, (
        f"and one challenge stands on its record, got {revised['challenge_count']}"
    )
