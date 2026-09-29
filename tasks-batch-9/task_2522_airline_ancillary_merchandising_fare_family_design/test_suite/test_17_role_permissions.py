"""Who may do what, and who may only see part of it.

The checks here walk one role's exclusive chain end to end, then push the other
roles at the same doors: the catalog and the review gate, the revenue ledger, the
review decision on a family the caller designed, and a peer channel's booking.
Each refusal names the identifier the contract answers with, and each is paired
with the same call succeeding for the role or identity that owns it.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    DISTRIBUTION_MANAGER,
    MERCHANDISING_ANALYST,
    MERCHANDISING_ANALYST_USER_ID,
    OPERATIONS_CONTROLLER,
    PRICING_APPROVER,
    PRICING_APPROVER_USER_ID,
    REVENUE_ACCOUNTANT,
    ROLE_PRICING_APPROVER,
    assert_entry_amounts,
    assert_field_values,
    assert_fingerprint,
    factories,
    make_channel_partner_headers,
    make_headers,
)


def test_merchandising_analyst_performs_its_exclusive_catalog_chain(api):
    """PRD §2.1: "`MerchandisingAnalyst` — builds the ancillary catalog and designs
    fare families and their bundled attributes. Exclusively creates catalog
    products, creates fare families, repositions or renames a draft family,
    attaches attributes to a family, reprices or withdraws an attribute, and
    submits a family for pricing review."
    PRD §3.1: "`effective_unit_cents`, which is `override_price_cents` when that is
    not null and otherwise the referenced product's `list_price_cents`."
    PRD §3.1: "Its `a_la_carte_total_cents` is `base_fare_cents` plus
    `unbundled_value_cents`. ... Its `bundle_discount_bp` ... is
    `a_la_carte_total_cents` minus `bundle_price_cents`, multiplied by 10,000,
    divided by `a_la_carte_total_cents`, and rounded half up."
    PRD §3.2: "Submission for review is the analyst's hand-off, and it is the
    transition `DRAFT` → `IN_REVIEW`."

    Design: Corner/rbac/merchandising_analyst_performs_every_one_of_its_exclusive_catalog_operations
    """
    # 1. Author the catalog product.
    product = validate_success(
        api.create_ancillary_product(
            factories.checked_bag_product_payload(), MERCHANDISING_ANALYST
        ),
        201,
    )

    # 2. Design the family.
    family = validate_success(
        api.create_fare_family(
            factories.fare_family_payload(code="ECO_RBAC", name="Economy RBAC"),
            MERCHANDISING_ANALYST,
        ),
        201,
    )

    # 3. Rename the draft.
    renamed = validate_success(
        api.update_fare_family(
            family["id"], {"name": "Economy RBAC Renamed"}, MERCHANDISING_ANALYST
        )
    )
    assert_field_values(renamed, name="Economy RBAC Renamed")

    # 4. Bundle the product into it.
    attribute = validate_success(
        api.add_family_attribute(
            family["id"],
            factories.family_attribute_payload(
                product["id"], inclusion="INCLUDED", included_quantity=1
            ),
            MERCHANDISING_ANALYST,
        ),
        201,
    )

    # 5. Reprice the bundled attribute below the catalog list price.
    repriced = validate_success(
        api.update_family_attribute(
            attribute["id"],
            {"override_price_cents": 3000, "waiver_eligible": True},
            MERCHANDISING_ANALYST,
        )
    )
    assert_field_values(
        repriced,
        override_price_cents=3000,
        effective_unit_cents=3000,
        attr_value_cents=3000,
        waiver_eligible=True,
    )

    # 6. Hand the design off for pricing review.
    submitted = validate_success(
        api.submit_fare_family(family["id"], {}, MERCHANDISING_ANALYST)
    )
    assert_field_values(submitted, status="IN_REVIEW")

    settled = validate_success(api.get_fare_family(family["id"], MERCHANDISING_ANALYST))
    assert_field_values(
        settled,
        name="Economy RBAC Renamed",
        status="IN_REVIEW",
        design_owner_user_id=MERCHANDISING_ANALYST_USER_ID,
        reviewer_user_id=None,
        revision_no=1,
        unbundled_value_cents=3000,
        a_la_carte_total_cents=15000,
        bundle_discount_bp=667,
        included_attribute_count=1,
        version=5,
    )
    assert_fingerprint(
        settled, "fee_fingerprint", "ECO_RBAC|1|BAG_CHECKED_1:INCLUDED:1:3000"
    )


def test_other_roles_cannot_touch_the_catalog_or_the_review_gate(api, scenario):
    """PRD §2.1: "If the supplied role is not one of the six roles below, or is a
    recognised role that is not authorised for the endpoint being called, the
    request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.1: "`PricingApprover` — ... Exclusively records review decisions and
    performs family status changes."
    PRD §2.1: "`OperationsController` — ... Exclusively creates flights, advances a
    flight's retailing phase, publishes a demand snapshot, creates seat-map
    segments, declares irregular-operations waivers, and rescinds them."
    PRD §2.7: "`ERR_ROLE_NOT_PERMITTED` (403) — the supplied role is one of the six
    declared roles and that role is authorised for the endpoint being called.
    Applies to every endpoint." — evaluated at step 2, ahead of
    `ERR_SEGREGATION_OF_DUTIES` at step 7 and `ERR_FAMILY_STATE_INVALID` at step 8.

    Design: Corner/rbac/other_roles_cannot_touch_the_catalog_or_the_review_gate
    """
    family = scenario.create_family(
        factories.fare_family_payload(code="ECO_RBAC", name="Economy RBAC")
    )
    channel = scenario.create_channel(factories.direct_web_channel_payload())

    # A selling channel may not author the merchandise it sells.
    validate_error(
        api.create_fare_family(
            factories.fare_family_payload(
                code="CP_TRY", name="Channel partner attempt"
            ),
            make_channel_partner_headers(channel["id"]),
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )

    # The operational side of the house is closed to the analyst.
    validate_error(
        api.create_flight(
            factories.flight_payload(
                flight_no="AC570", origin="SFO", destination="JFK"
            ),
            MERCHANDISING_ANALYST,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )

    # The analyst cannot sign off its own draft, and the reason given is the role -
    # not the family's state, and not the designer-versus-reviewer comparison.
    review_error = validate_error(
        api.review_fare_family(
            family["id"],
            factories.review_decision_payload("APPROVE"),
            MERCHANDISING_ANALYST,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    assert review_error["error_id"] not in (
        ApiErrorId.FAMILY_STATE_INVALID,
        ApiErrorId.SEGREGATION_OF_DUTIES,
    ), (
        "the review gate must refuse an analyst for its role before it looks at the "
        f"family's state or its ownership: {review_error}"
    )

    # Nothing the three refused calls asked for exists.
    families, families_meta = validate_paginated(
        api.list_fare_families(MERCHANDISING_ANALYST)
    )
    assert families_meta["total_count"] == 1, (
        f"only the analyst-authored family may exist: {families_meta}"
    )
    assert [f["code"] for f in families] == ["ECO_RBAC"], (
        f"the refused authoring attempt left a family behind: {families}"
    )
    assert_field_values(families[0], status="DRAFT", version=1)

    flights, flights_meta = validate_paginated(api.list_flights(OPERATIONS_CONTROLLER))
    assert flights == [], f"the refused flight was created anyway: {flights}"
    assert flights_meta["total_count"] == 0, (
        f"no flight may exist after the refusal: {flights_meta}"
    )


def test_only_the_revenue_accountant_may_read_the_ancillary_ledger(
    api, scenario, clock_at_nine
):
    """PRD §2.1: "`RevenueAccountant` — reads the append-only ancillary revenue
    ledger and its tax treatment. This is the **only** role permitted to read
    revenue entries, in any of the three ways the ledger is exposed."
    PRD §3.9: "Ledger reads belong to the `RevenueAccountant` alone; no other role,
    including the `ChannelPartner` who generated the entries, may read them."
    PRD §3.6: "On success, `accepted_price_cents` is frozen from
    `offered_price_cents`; one `SALE` revenue entry is posted whose `category` is
    the product's `category`, whose `gross_cents` is the accepted price, whose tax
    and reporting metadata are snapshotted from the product, and whose `source_ref`
    is `offer:` followed by the offer's id."
    PRD §2.11: "Tax is derived per entry from the entry's `tax_treatment`, at a rate
    of 750 basis points for `TAXABLE_TRANSPORT`, 400 basis points for
    `TAXABLE_SERVICE` and nothing at all for `EXEMPT`."

    Design: Corner/rbac/revenue_accountant_is_the_only_role_that_may_read_the_ancillary_ledger
    """
    bag = scenario.create_product(factories.checked_bag_product_payload())
    family = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_BARE", name="Economy Bare", bundle_price_cents=12000
        )
    )
    channel = scenario.create_channel(factories.direct_web_channel_payload())
    flight = scenario.create_flight(flight_no="AC571", origin="SFO", destination="JFK")
    scenario.post_demand(flight["id"], 50, 0)
    booking = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="LEDG01"
    )

    # A neutral bag offer at list price, accepted by the selling channel.
    session = scenario.open_offer_session(
        booking["id"], channel["id"], "BOOKING", [bag["id"]]
    )
    offer_id = session["presented_offer_ids"][0]
    held = scenario.get_booking(booking["id"], channel["id"])
    accepted = scenario.accept_offer(offer_id, channel["id"], held["version"])
    assert_field_values(accepted, offer_status="ACCEPTED", accepted_price_cents=3500)

    # The channel that generated the money may not read the rows it generated.
    validate_error(
        api.list_booking_revenue_entries(
            booking["id"], make_channel_partner_headers(channel["id"])
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.list_revenue_entries(DISTRIBUTION_MANAGER, {"booking_id": booking["id"]}),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )

    # The accountant sees the single sale, tax split at the service rate.
    entries, entries_meta = validate_paginated(
        api.list_booking_revenue_entries(booking["id"], REVENUE_ACCOUNTANT)
    )
    assert entries_meta["total_count"] == 1, (
        f"one accepted offer posts exactly one ledger row: {entries_meta}"
    )
    entry = entries[0]
    assert_field_values(
        entry,
        entry_type="SALE",
        category="BAGGAGE",
        product_sku="BAG_CHECKED_1",
        tax_treatment="TAXABLE_SERVICE",
        revenue_class="NON_AIR",
        revenue_account_code="4100",
        source_ref=f"offer:{offer_id}",
    )
    assert_entry_amounts(entry, gross_cents=3500, tax_cents=140, net_cents=3360)

    # Only the rows are walled off: the partner still reads its own money totals.
    own_view = scenario.get_booking(booking["id"], channel["id"])
    assert_field_values(
        own_view, ancillary_gross_cents=3500, recognized_ancillary_net_cents=3360
    )


def test_the_analyst_who_designed_a_family_may_not_review_it(api, scenario):
    """PRD §2.1: "A `PricingApprover` may never review a family it designed."
    PRD §2.7: "`ERR_SEGREGATION_OF_DUTIES` (403) — the acting `PricingApprover`'s
    `X-User-ID` differs from the target family's `design_owner_user_id`. The analyst
    who designed a family may never record its review decision. This guards the
    review-decision operation only."
    PRD §3.2: "the approver's `X-User-ID` must differ from the family's
    `design_owner_user_id`, or the request is refused with
    `ERR_SEGREGATION_OF_DUTIES`. ... the check is a straight comparison of the two
    user identifiers."
    PRD §3.2: "An **approval** drives `IN_REVIEW` → `PUBLISHED` ... The family's
    `reviewer_user_id` is set to the deciding approver's `X-User-ID`."

    Design: Corner/rbac/the_analyst_who_designed_a_family_may_not_review_it
    """
    bag = scenario.create_product(factories.checked_bag_product_payload())
    family = scenario.create_family(
        factories.fare_family_payload(code="ECO_SOD", name="Economy Segregation")
    )
    scenario.add_attribute(
        family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1
    )
    submitted = scenario.submit_family(family["id"])
    assert_field_values(
        submitted,
        status="IN_REVIEW",
        design_owner_user_id=MERCHANDISING_ANALYST_USER_ID,
        reviewer_user_id=None,
    )
    version_in_review = submitted["version"]

    # The designer's own identity, presented in the approver's capacity, is refused.
    validate_error(
        api.review_fare_family(
            family["id"],
            factories.review_decision_payload(
                "APPROVE", review_note="self approval attempt"
            ),
            make_headers(ROLE_PRICING_APPROVER, MERCHANDISING_ANALYST_USER_ID),
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
    )
    still_in_review = scenario.get_family(family["id"])
    assert_field_values(
        still_in_review,
        status="IN_REVIEW",
        reviewer_user_id=None,
        version=version_in_review,
    )

    # An independent approver, at the very same endpoint, is accepted.
    approved = validate_success(
        api.review_fare_family(
            family["id"],
            factories.review_decision_payload(
                "APPROVE", review_note="independent approval"
            ),
            PRICING_APPROVER,
        )
    )
    assert_field_values(
        approved,
        status="PUBLISHED",
        reviewer_user_id=PRICING_APPROVER_USER_ID,
        design_owner_user_id=MERCHANDISING_ANALYST_USER_ID,
        version=version_in_review + 1,
    )


def test_channel_partner_list_reads_filter_while_single_reads_are_refused(api, scenario):
    """PRD §2.1: "Single-resource reads of a booking, an ancillary offer or a seat
    assignment belonging to another channel are *refused* with
    `ERR_CHANNEL_SCOPE_VIOLATION`. The corresponding list reads behave differently:
    they silently filter the result set down to the acting partner's own channel
    rather than raising an error. Both behaviours are deliberate and both are tested."
    PRD §2.1: "a `ChannelPartner` may only act on a `Booking` whose
    `distribution_channel_id` equals its own `X-User-ID`."
    PRD §2.1: "Every role may read every resource except the revenue ledger."

    Design: Corner/rbac/channel_partner_list_reads_are_filtered_while_single_row_reads_are_refused
    """
    family = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_BARE", name="Economy Bare", bundle_price_cents=12000
        )
    )
    channel_one = scenario.create_channel(
        factories.distribution_channel_payload(
            channel_code="OTA_ONE", channel_type="OTA", commission_bp=900, markup_bp=500
        )
    )
    channel_two = scenario.create_channel(
        factories.distribution_channel_payload(
            channel_code="OTA_TWO", channel_type="OTA", commission_bp=700, markup_bp=300
        )
    )
    flight = scenario.create_flight(flight_no="AC572", origin="SFO", destination="JFK")
    mine = scenario.create_booking(
        flight["id"], family["id"], channel_one["id"], record_locator="MINE01"
    )
    theirs = scenario.create_booking(
        flight["id"], family["id"], channel_two["id"], record_locator="THEIR1"
    )

    # The collection read quietly narrows to the caller's own sales.
    own_rows, own_meta = validate_paginated(
        api.list_bookings(make_channel_partner_headers(channel_one["id"]))
    )
    assert own_meta["total_count"] == 1, (
        f"a partner's booking list must show only its own channel: {own_meta}"
    )
    assert [row["id"] for row in own_rows] == [mine["id"]], (
        f"the filtered list returned a peer's booking: {own_rows}"
    )
    assert_field_values(own_rows[0], record_locator="MINE01")

    # The by-id read of the same peer row is an outright refusal, not a filter.
    validate_error(
        api.get_booking(theirs["id"], make_channel_partner_headers(channel_one["id"])),
        ApiErrorId.CHANNEL_SCOPE_VIOLATION,
    )

    # A write against the peer's booking is refused the same way, and changes nothing.
    validate_error(
        api.cancel_booking(
            theirs["id"],
            factories.cancel_payload("Poaching attempt"),
            make_channel_partner_headers(channel_one["id"]),
        ),
        ApiErrorId.CHANNEL_SCOPE_VIOLATION,
    )
    untouched = scenario.get_booking(theirs["id"], channel_two["id"])
    assert_field_values(untouched, booking_status="HELD", version=theirs["version"])

    # An internal role is not channel-scoped and sees both sides of the market.
    all_rows, all_meta = validate_paginated(api.list_bookings(REVENUE_ACCOUNTANT))
    assert all_meta["total_count"] == 2, (
        f"an internal role reads every booking, not one channel's: {all_meta}"
    )
    assert {row["id"] for row in all_rows} == {mine["id"], theirs["id"]}, (
        f"the unscoped list is missing a booking: {all_rows}"
    )
