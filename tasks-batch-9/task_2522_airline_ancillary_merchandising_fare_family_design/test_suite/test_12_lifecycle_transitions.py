"""Lifecycle transitions across the retailing entities.

The fare family walks DRAFT -> IN_REVIEW -> PUBLISHED -> SUSPENDED/RETIRED, the
booking walks HELD -> TICKETED/CANCELLED, the offer walks PRESENTED -> one of its
four terminal states, and a flight is born in PRESALE with normal operations.
Every test here builds its own world, drives one transition, and holds the system
to the exact side effects the contract promises for that transition - including
the refusals that a terminal or wrong-from-state must produce.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    MERCHANDISING_ANALYST,
    OPERATIONS_CONTROLLER,
    PRICING_APPROVER,
    PRICING_APPROVER_USER_ID,
    REVENUE_ACCOUNTANT,
    assert_entry_amounts,
    assert_immutable_common_fields,
    assert_money_field,
    assert_recognized_net_matches_ledger,
    assert_segment_counts,
    factories,
    find_entries,
    find_one_entry,
    make_channel_partner_headers,
)


def assert_ladder_winner(response, winning_error_id: str, losing_error_id: str) -> dict:
    """The first failure on the fixed check order decides the answer.

    ``losing_error_id`` names the condition that also holds on the request but
    sits later in the order, so it must never be the one reported.
    """
    reported = (response.json().get("data") or {}).get("error_id")
    assert reported != losing_error_id, (
        f"{losing_error_id} was reported, but {winning_error_id} is checked earlier "
        "and must decide the response"
    )
    return validate_error(response, winning_error_id)


def eco_family_payload(code: str, name: str, **overrides):
    """An ECONOMY family: base fare 12000 cents, change fee 7500, tier 4."""
    return factories.fare_family_payload(
        **{
            "code": code,
            "name": name,
            "cabin_class": "ECONOMY",
            "base_fare_cents": 12000,
            "bundle_price_cents": 14000,
            "refundability": "NON_REFUNDABLE",
            "change_fee_cents": 7500,
            "boarding_priority_tier": 4,
            **overrides,
        }
    )


# ---------------------------------------------------------------------------
# The fare family design lifecycle
# ---------------------------------------------------------------------------
def test_submit_draft_family_moves_to_in_review_and_recomputes_valuation(api, scenario):
    """PRD §3.2: "Submission for review is the analyst's hand-off, and it is the
    transition `DRAFT` → `IN_REVIEW`."
    PRD §3.2: "When all four hold, the submission recomputes the override-basis
    valuation into `unbundled_value_cents`, `a_la_carte_total_cents`,
    `bundle_discount_bp` and `included_attribute_count`, rebuilds
    `fee_fingerprint`, and increments the family's `version`."
    PRD §3.1: "Its `bundle_discount_bp` — the basis points a passenger saves by
    buying the bundle instead of every component separately — is 0 when
    `unbundled_value_cents` is 0; otherwise it is `a_la_carte_total_cents` minus
    `bundle_price_cents`, multiplied by 10,000, divided by
    `a_la_carte_total_cents`, and rounded half up."

    Design: Corner/state_machines/submit_draft_family_moves_to_in_review_and_recomputes_valuation
    """
    bag = scenario.create_product(factories.checked_bag_product_payload())
    boarding = scenario.create_product(factories.priority_boarding_product_payload())
    family = scenario.create_family(
        eco_family_payload("ECO_TWO", "Economy Two", bundle_price_cents=15000)
    )
    scenario.add_attribute(
        family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1
    )
    scenario.add_attribute(
        family["id"], boarding["id"], inclusion="INCLUDED", included_quantity=1
    )

    submitted = validate_success(
        api.submit_fare_family(family["id"], {}, MERCHANDISING_ANALYST)
    )

    assert submitted["status"] == "IN_REVIEW", (
        f"submit drives DRAFT to IN_REVIEW but status is {submitted['status']!r}"
    )
    # ECONOMY carries no cabin uplift, so each attribute values at its own unit
    # price: 3500 for the bag plus 1250 for priority boarding.
    assert_money_field(submitted, "unbundled_value_cents", 4750)
    assert_money_field(submitted, "a_la_carte_total_cents", 16750)
    # (16750 - 15000) * 10000 / 16750 = 1044.78 basis points, rounded half up.
    assert submitted["bundle_discount_bp"] == 1045, (
        "bundle_discount_bp should be 1045 basis points but is "
        f"{submitted['bundle_discount_bp']}"
    )
    assert submitted["included_attribute_count"] == 2, (
        "both attributes are ACTIVE and INCLUDED, so included_attribute_count is 2 "
        f"but is {submitted['included_attribute_count']}"
    )
    assert (
        submitted["fee_fingerprint"]
        == "ECO_TWO|1|BAG_CHECKED_1:INCLUDED:1:3500;PRIORITY_BOARDING:INCLUDED:1:1250"
    ), f"fee_fingerprint is {submitted['fee_fingerprint']!r}"
    assert submitted["revision_no"] == 1, (
        "a submission does not bump revision_no, only a rejection does; got "
        f"{submitted['revision_no']}"
    )
    assert submitted.get("reviewer_user_id") is None, (
        "reviewer_user_id stays null until a decision is recorded but is "
        f"{submitted.get('reviewer_user_id')!r}"
    )
    # Create, then one mutation per attribute attachment, then this submit.
    assert submitted["version"] == 4, (
        f"version should be 4 after create, two attachments and the submit, "
        f"but is {submitted['version']}"
    )


def test_submit_without_active_attributes_is_refused_before_the_bundle_floor_check(
    api, scenario
):
    """PRD §3.2: "The family must have at least one attribute whose
    `attribute_state` is `ACTIVE`, or the request is refused with
    `ERR_FAMILY_HAS_NO_ATTRIBUTES`."
    PRD §3.2: "Four conditions gate it, evaluated in the order §2.7 fixes."
    PRD §2.8: "A family with no `ACTIVE` attributes therefore fingerprints as its
    `code`, a vertical bar, its `revision_no` and a trailing vertical bar with
    nothing after it."

    Design: Corner/state_machines/submit_family_with_zero_active_attributes_returns_family_has_no_attributes
    """
    family = scenario.create_family(
        eco_family_payload("ECO_BARE", "Economy Bare", bundle_price_cents=14000)
    )

    # With no attributes the a-la-carte total is the bare base fare of 12000, so
    # the 14000 bundle price also breaches the discount floor - but the missing
    # attribute set is checked first.
    response = api.submit_fare_family(family["id"], {}, MERCHANDISING_ANALYST)
    assert_ladder_winner(
        response,
        ApiErrorId.FAMILY_HAS_NO_ATTRIBUTES,
        ApiErrorId.BUNDLE_DISCOUNT_FLOOR_BREACH,
    )

    unchanged = validate_success(api.get_fare_family(family["id"], MERCHANDISING_ANALYST))
    assert unchanged["status"] == "DRAFT", (
        f"the refused submit must leave the family in DRAFT, got {unchanged['status']!r}"
    )
    assert unchanged["version"] == 1, (
        f"a refused submit is not a mutation, so version stays 1 but is {unchanged['version']}"
    )
    assert unchanged["fee_fingerprint"] == "ECO_BARE|1|", (
        "an attribute-free family fingerprints as code|revision_no| but is "
        f"{unchanged['fee_fingerprint']!r}"
    )


def test_approve_promotes_pending_publication_to_in_parity(api, scenario):
    """PRD §3.2: "Every publication of the family whose `parity_state` is
    `PENDING` is promoted to `IN_PARITY`, pinning `published_fee_fingerprint`
    from the family's `fee_fingerprint` and `published_family_version` from the
    family's `version` **as of the end of this transition** — that is, after the
    version bump this transition performs, not before it."
    PRD §3.2: "The family's `reviewer_user_id` is set to the deciding approver's
    `X-User-ID`."
    PRD §2.8: "it reads `BREACHED` when the channel's `parity_required` is true
    and at least one of that channel's publications is `OUT_OF_PARITY`, and
    `COMPLIANT` otherwise."

    Design: Corner/state_machines/approve_review_decision_promotes_pending_publication_to_in_parity
    """
    bag = scenario.create_product(factories.checked_bag_product_payload())
    family = scenario.create_family(eco_family_payload("ECO_PUB", "Economy Pub"))
    scenario.add_attribute(
        family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1
    )
    channel = scenario.create_channel(factories.direct_web_channel_payload())

    # Publish the draft's content to the channel: it must wait in PENDING until
    # the pricing review lands.
    draft = scenario.get_family(family["id"])
    publication = scenario.publish_to_channel(
        family["id"], channel["id"], draft["version"]
    )
    assert publication["parity_state"] == "PENDING", (
        "a publication of a family that is not yet PUBLISHED waits in PENDING, got "
        f"{publication['parity_state']!r}"
    )
    scenario.submit_family(family["id"])

    approved = validate_success(
        api.review_fare_family(
            family["id"], factories.review_decision_payload("APPROVE"), PRICING_APPROVER
        )
    )

    assert approved["status"] == "PUBLISHED", (
        f"an approval publishes the family but status is {approved['status']!r}"
    )
    assert approved["reviewer_user_id"] == PRICING_APPROVER_USER_ID, (
        "reviewer_user_id is stamped from the deciding approver but is "
        f"{approved['reviewer_user_id']!r}"
    )
    assert approved["revision_no"] == 1, (
        f"an approval does not touch revision_no, got {approved['revision_no']}"
    )
    # Create, attribute attachment, publication creation, submit, this approval.
    assert approved["version"] == 5, (
        f"version should be 5 at the end of the approval but is {approved['version']}"
    )
    assert approved["publication_count"] == 1, (
        "publication_count counts the PENDING, IN_PARITY and OUT_OF_PARITY "
        f"publications of the family, expected 1 but got {approved['publication_count']}"
    )

    promoted = scenario.get_publication(publication["id"])
    assert promoted["parity_state"] == "IN_PARITY", (
        f"the PENDING publication must be promoted, got {promoted['parity_state']!r}"
    )
    assert promoted.get("drift_reason") is None, (
        "a publication that never lost parity carries no drift_reason but has "
        f"{promoted.get('drift_reason')!r}"
    )
    assert promoted["published_family_version"] == 5, (
        "published_family_version pins the family version as of the end of the "
        f"approval, expected 5 but got {promoted['published_family_version']}"
    )
    assert (
        promoted["published_fee_fingerprint"]
        == "ECO_PUB|1|BAG_CHECKED_1:INCLUDED:1:3500"
    ), f"published_fee_fingerprint is {promoted['published_fee_fingerprint']!r}"

    compliant = scenario.get_channel(channel["id"])
    assert compliant["content_parity_status"] == "COMPLIANT", (
        "no publication of this channel is OUT_OF_PARITY, so the channel is "
        f"COMPLIANT but reads {compliant['content_parity_status']!r}"
    )
    assert compliant["parity_breach_count"] == 0, (
        "parity was never lost, so parity_breach_count stays 0 but is "
        f"{compliant['parity_breach_count']}"
    )


def test_status_change_from_draft_to_suspended_is_refused(api, scenario):
    """PRD §3.2: "Once published, a family is moved between the three
    post-publication states by an approver supplying a `target_status` and a
    `reason`. Four moves are legal and no others; any other pair is refused with
    `ERR_FAMILY_STATE_INVALID`."
    PRD §2.7 item 8: "For a status change, the family's current `status` must be
    one from which the requested `target_status` is reachable: `PUBLISHED`
    reaches `SUSPENDED` or `RETIRED`, and `SUSPENDED` reaches `PUBLISHED` or
    `RETIRED`. Every other pair is rejected."

    Design: Corner/state_machines/status_change_from_draft_to_suspended_returns_family_state_invalid
    """
    bag = scenario.create_product(factories.checked_bag_product_payload())
    family = scenario.create_family(eco_family_payload("ECO_DRAFT", "Economy Draft"))
    scenario.add_attribute(
        family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1
    )

    # Taking a family off sale only makes sense once it is on sale; a draft has
    # never been sold, so DRAFT is not a from-state for SUSPENDED.
    response = api.change_fare_family_status(
        family["id"],
        factories.status_change_payload("SUSPENDED", reason="Pull it from the shelf"),
        PRICING_APPROVER,
    )
    validate_error(response, ApiErrorId.FAMILY_STATE_INVALID)

    unchanged = scenario.get_family(family["id"])
    assert unchanged["status"] == "DRAFT", (
        f"the refused move must leave the family in DRAFT, got {unchanged['status']!r}"
    )
    # Create plus the one attribute attachment; the refused move is not a mutation.
    assert unchanged["version"] == 2, (
        f"version should still be 2 after the refusal but is {unchanged['version']}"
    )


def test_retired_family_cannot_be_submitted_again(api, scenario):
    """PRD §3.2: "`RETIRED` is terminal."
    PRD §2.7 item 8: "the family's `status` is the from-state the requested
    action declares: `DRAFT` to submit for review, `IN_REVIEW` to record a review
    decision, `DRAFT` to reposition the family on the upsell ladder, `DRAFT` to
    attach a new attribute, and `DRAFT` or `PUBLISHED` to reprice or withdraw an
    existing attribute."
    PRD §3.2: "All four moves increment the family's `version`."

    Design: Corner/state_machines/retired_family_rejects_submit_from_terminal_state
    """
    bag = scenario.create_product(factories.checked_bag_product_payload())
    family = scenario.create_family(eco_family_payload("ECO_GONE", "Economy Gone"))
    scenario.add_attribute(
        family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1
    )
    scenario.publish_family(family["id"])

    # No booking was ever opened on this family, so it retires cleanly.
    retired = scenario.change_family_status(
        family["id"], "RETIRED", reason="Withdrawn from the market"
    )
    assert retired["status"] == "RETIRED", (
        f"the family should be RETIRED but is {retired['status']!r}"
    )
    # Create, attribute attachment, submit, approval, retirement.
    assert retired["version"] == 5, (
        f"version should be 5 after the retirement but is {retired['version']}"
    )

    response = api.submit_fare_family(family["id"], {}, MERCHANDISING_ANALYST)
    validate_error(response, ApiErrorId.FAMILY_STATE_INVALID)

    still_retired = scenario.get_family(family["id"])
    assert still_retired["status"] == "RETIRED", (
        "a retired family stays retired; nothing resurrects it, but status is "
        f"{still_retired['status']!r}"
    )
    assert still_retired["version"] == 5, (
        f"the refused submit is not a mutation, so version stays 5 but is "
        f"{still_retired['version']}"
    )


def test_second_submit_of_an_in_review_family_is_refused(api, scenario):
    """PRD §3.2: "The family must currently be in `DRAFT`, or the request is
    refused with `ERR_FAMILY_STATE_INVALID`."
    PRD §3.1: "its `reviewer_user_id` null because no decision has yet been
    recorded"

    Design: Corner/state_machines/second_submit_of_in_review_family_returns_family_state_invalid
    """
    bag = scenario.create_product(factories.checked_bag_product_payload())
    family = scenario.create_family(eco_family_payload("ECO_TWICE", "Economy Twice"))
    scenario.add_attribute(
        family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1
    )
    first = scenario.submit_family(family["id"])
    assert first["status"] == "IN_REVIEW", (
        f"the first submit must land in IN_REVIEW, got {first['status']!r}"
    )
    # Create, attribute attachment, first submit.
    assert first["version"] == 3, (
        f"version should be 3 after the first submit but is {first['version']}"
    )

    # A family already on the approver's desk cannot be handed over a second time.
    response = api.submit_fare_family(family["id"], {}, MERCHANDISING_ANALYST)
    validate_error(response, ApiErrorId.FAMILY_STATE_INVALID)

    unchanged = scenario.get_family(family["id"])
    assert unchanged["status"] == "IN_REVIEW", (
        f"the family must still be IN_REVIEW, got {unchanged['status']!r}"
    )
    assert unchanged["version"] == 3, (
        f"the refused second submit is not a mutation, so version stays 3 but is "
        f"{unchanged['version']}"
    )
    assert unchanged.get("reviewer_user_id") is None, (
        "no decision has been recorded, so reviewer_user_id stays null but is "
        f"{unchanged.get('reviewer_user_id')!r}"
    )


# ---------------------------------------------------------------------------
# The flight's two state dimensions
# ---------------------------------------------------------------------------
def test_new_flight_starts_in_presale_and_normal_with_zero_counters(api, scenario):
    """PRD §3.3: "A new flight starts with `sales_phase` `PRESALE`, `irops_state`
    `NORMAL`, `booked_load_factor_pct` at 0, `demand_index_bp` at 0,
    `demand_tier` `LOW`, and both `active_waiver_count` and
    `ticketed_booking_count` at 0."
    PRD §3.3: "`demand_tier` — `HIGH` when `booked_load_factor_pct` is at least
    80, `MID` when it is at least 60 but below 80, and `LOW` otherwise"

    Design: Corner/state_machines/new_flight_starts_in_presale_and_normal_with_zero_counters
    """
    created = validate_success(
        api.create_flight(
            factories.flight_payload(
                flight_no="AA4410",
                origin="JFK",
                destination="LAX",
                scheduled_departure_utc="2026-09-15T14:00:00Z",
                cabin_seat_total=180,
            ),
            OPERATIONS_CONTROLLER,
        ),
        201,
    )

    assert created["sales_phase"] == "PRESALE", (
        f"a brand new flight opens in PRESALE but reads {created['sales_phase']!r}"
    )
    assert created["irops_state"] == "NORMAL", (
        f"operations start normal but irops_state is {created['irops_state']!r}"
    )
    assert created["booked_load_factor_pct"] == 0, (
        "no seat is booked yet, so booked_load_factor_pct is 0 but is "
        f"{created['booked_load_factor_pct']}"
    )
    assert created["demand_index_bp"] == 0, (
        f"demand_index_bp starts at 0 but is {created['demand_index_bp']}"
    )
    assert created["demand_tier"] == "LOW", (
        "a load factor of 0 falls below every higher band, so demand_tier is LOW "
        f"but is {created['demand_tier']!r}"
    )
    assert created["active_waiver_count"] == 0, (
        f"active_waiver_count starts at 0 but is {created['active_waiver_count']}"
    )
    assert created["ticketed_booking_count"] == 0, (
        f"ticketed_booking_count starts at 0 but is {created['ticketed_booking_count']}"
    )
    assert created["version"] == 1, (
        f"a freshly created flight is at version 1 but is at {created['version']}"
    )

    # The same opening position must be what a later reader sees.
    fetched = validate_success(api.get_flight(created["id"], OPERATIONS_CONTROLLER))
    assert fetched["sales_phase"] == "PRESALE", (
        f"the stored flight must also read PRESALE, got {fetched['sales_phase']!r}"
    )
    assert fetched["irops_state"] == "NORMAL", (
        f"the stored flight must also read NORMAL, got {fetched['irops_state']!r}"
    )
    assert fetched["demand_tier"] == "LOW", (
        f"the stored flight must also read LOW, got {fetched['demand_tier']!r}"
    )


# ---------------------------------------------------------------------------
# The booking sales lifecycle
# ---------------------------------------------------------------------------
def test_second_cancel_of_a_cancelled_booking_is_refused(api, scenario):
    """PRD §3.8: "Cancelling takes a `cancel_reason` and is legal from three
    states — `HELD`, `TICKETED` and `CHANGE_PENDING` — with `CANCELLED`
    terminal."
    PRD §2.7 item 9: "the booking's `booking_status` is a legal from-state for
    the action: `HELD` for issuing a disclosure and for ticketing; `HELD` for
    acknowledging a disclosure; `TICKETED` for opening a change; `CHANGE_PENDING`
    for settling a change; `HELD`, `TICKETED` or `CHANGE_PENDING` for cancelling
    and for assigning a seat"

    Design: Corner/state_machines/cancel_of_already_cancelled_booking_returns_booking_state_invalid
    """
    flight = scenario.create_flight()
    family = scenario.create_family(eco_family_payload("ECO_CXL", "Economy Cancel"))
    channel = scenario.create_channel(factories.direct_web_channel_payload())
    booking = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="CXL001"
    )

    cancelled = scenario.cancel(booking["id"], channel["id"], "Passenger changed plans")
    assert cancelled["booking_status"] == "CANCELLED", (
        f"the first cancellation must land in CANCELLED, got {cancelled['booking_status']!r}"
    )
    assert cancelled["version"] == 2, (
        f"the hold plus the cancellation put the booking at version 2, not "
        f"{cancelled['version']}"
    )

    # CANCELLED is terminal: there is nothing left to cancel.
    response = api.cancel_booking(
        booking["id"],
        factories.cancel_payload("Duplicate cancellation request"),
        make_channel_partner_headers(channel["id"]),
    )
    validate_error(response, ApiErrorId.BOOKING_STATE_INVALID)

    unchanged = scenario.get_booking(booking["id"], channel["id"])
    assert unchanged["booking_status"] == "CANCELLED", (
        f"the booking must stay CANCELLED, got {unchanged['booking_status']!r}"
    )
    assert unchanged["version"] == 2, (
        f"the refused second cancellation is not a mutation, so version stays 2 "
        f"but is {unchanged['version']}"
    )


def test_declining_an_offer_posts_no_revenue_while_accepting_posts_a_sale(api, scenario):
    """PRD §3.6: "Its side effect is deceptively small but functionally
    important: the offer's `updated_at` is set to the logical clock, and that
    timestamp anchors a thirty-minute cool-off during which the same product
    cannot be re-offered on the same booking. The offer's `version` increments.
    No revenue moves."
    PRD §3.6: "On success, `accepted_price_cents` is frozen from
    `offered_price_cents`; one `SALE` revenue entry is posted whose `category` is
    the product's `category`, whose `gross_cents` is the accepted price, whose
    tax and reporting metadata are snapshotted from the product, and whose
    `source_ref` is `offer:` followed by the offer's id"
    PRD §3.9: "`ancillary_gross_cents` is the signed sum of `gross_cents` over
    the booking's revenue entries whose `entry_type` is `SALE`, `REFUND`,
    `WAIVER_CREDIT` or `WAIVER_REVERSAL`."

    Design: Corner/state_machines/decline_branch_posts_no_revenue_while_accept_branch_posts_a_sale
    """
    bag = scenario.create_product(factories.checked_bag_product_payload())
    boarding = scenario.create_product(factories.priority_boarding_product_payload())
    flight = scenario.create_flight()
    # A load factor of exactly 50 and a flat demand index leave the elastic score
    # at par, so each product is offered at its own list price.
    scenario.post_demand(flight["id"], 50, 0)
    family = scenario.create_family(
        eco_family_payload("ECO_SESS", "Economy Session", bundle_price_cents=12000)
    )
    scenario.add_attribute(
        family["id"], bag["id"], inclusion="CHARGEABLE", included_quantity=0
    )
    scenario.add_attribute(
        family["id"], boarding["id"], inclusion="CHARGEABLE", included_quantity=0
    )
    channel = scenario.create_channel(factories.direct_web_channel_payload())
    booking = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="SESS01"
    )

    session = scenario.open_offer_session(booking["id"], channel["id"], "BOOKING")
    assert session["candidate_count"] == 2, (
        "both chargeable products are eligible, so candidate_count is 2 but is "
        f"{session['candidate_count']}"
    )
    assert len(session["presented_offer_ids"]) == 2, (
        f"two offers should be presented but got {len(session['presented_offer_ids'])}"
    )

    bag_offer = scenario.offers_for_booking(
        booking["id"], channel["id"], ancillary_product_id=bag["id"]
    )[0]
    boarding_offer = scenario.offers_for_booking(
        booking["id"], channel["id"], ancillary_product_id=boarding["id"]
    )[0]
    assert_money_field(bag_offer, "offered_price_cents", 3500)
    assert_money_field(boarding_offer, "offered_price_cents", 1250)

    declined = scenario.decline_offer(bag_offer["id"], channel["id"])
    assert declined["offer_status"] == "DECLINED", (
        f"the declined offer must read DECLINED, got {declined['offer_status']!r}"
    )
    assert declined.get("accepted_price_cents") is None, (
        "a declined offer never freezes a price but carries "
        f"{declined.get('accepted_price_cents')!r}"
    )
    assert declined["version"] == 2, (
        f"the decline increments the offer's version to 2, not {declined['version']}"
    )

    # The decline moved no money, so the ledger is still empty at this point.
    _, meta_after_decline = validate_paginated(
        api.list_booking_revenue_entries(booking["id"], REVENUE_ACCOUNTANT)
    )
    assert meta_after_decline["total_count"] == 0, (
        "declining an offer posts nothing to the ledger, but total_count is "
        f"{meta_after_decline['total_count']}"
    )

    live = scenario.get_booking(booking["id"], channel["id"])
    accepted = scenario.accept_offer(
        boarding_offer["id"], channel["id"], live["version"]
    )
    assert accepted["offer_status"] == "ACCEPTED", (
        f"the accepted offer must read ACCEPTED, got {accepted['offer_status']!r}"
    )
    assert_money_field(accepted, "accepted_price_cents", 1250)
    assert accepted["version"] == 2, (
        f"the acceptance increments the offer's version to 2, not {accepted['version']}"
    )

    entries, meta = validate_paginated(
        api.list_booking_revenue_entries(booking["id"], REVENUE_ACCOUNTANT)
    )
    assert meta["total_count"] == 1, (
        "only the accepted offer posts revenue, so the ledger holds one row but "
        f"total_count is {meta['total_count']}"
    )
    sale = find_one_entry(entries, entry_type="SALE", category="BOARDING")
    # Priority boarding is a taxable service: 1250 * 400 / 10000 = 50 cents of tax.
    assert_entry_amounts(sale, 1250, 50, 1200)
    assert sale["source_ref"] == f"offer:{boarding_offer['id']}", (
        f"source_ref should trace back to the offer but is {sale['source_ref']!r}"
    )
    assert sale["product_sku"] == "PRIORITY_BOARDING", (
        f"product_sku should be PRIORITY_BOARDING but is {sale['product_sku']!r}"
    )
    assert sale["tax_treatment"] == "TAXABLE_SERVICE", (
        f"tax_treatment is snapshotted from the product: {sale['tax_treatment']!r}"
    )
    assert sale["revenue_class"] == "NON_AIR", (
        f"revenue_class is snapshotted from the product: {sale['revenue_class']!r}"
    )
    assert sale["revenue_account_code"] == "4400", (
        f"revenue_account_code is snapshotted from the product: "
        f"{sale['revenue_account_code']!r}"
    )
    assert_immutable_common_fields(sale)
    assert find_entries(entries, product_sku="BAG_CHECKED_1") == [], (
        "the declined bag must not appear anywhere in the ledger"
    )

    settled = scenario.get_booking(booking["id"], channel["id"])
    assert_money_field(settled, "ancillary_gross_cents", 1250)
    assert_money_field(settled, "recognized_ancillary_net_cents", 1200)
    assert_recognized_net_matches_ledger(settled, entries)
    assert settled.get("fare_component_cents") is None, (
        "the booking is not ticketed, so the fare component is still unpinned but "
        f"reads {settled.get('fare_component_cents')!r}"
    )
    assert_money_field(settled, "commission_cents", 0)
    assert_money_field(settled, "incentive_credit_cents", 0)
    assert_money_field(settled, "channel_settlement_total_cents", 0)


def test_cancelling_a_held_booking_releases_the_seat_and_supersedes_the_offer(
    api, scenario
):
    """PRD §3.8: "Every path releases every seat assignment of the booking that is
    still `HELD` or `CONFIRMED`, stamping `released_reason` `BOOKING_CANCELLED`;
    moves every offer on the booking still `PRESENTED` to `SUPERSEDED`; and
    reverses refundable ancillary revenue by posting, for every `SALE` entry of
    the booking whose product's `refundable` flag is true, one mirroring `REFUND`
    entry"
    PRD §3.7: "Releasing from `HELD` decreases the segment's `held_seats` by one
    and increases its `available_seats` by one, and posts and reverses
    **nothing**, because a held seat was never sold."
    PRD §3.7: "A release cascaded from a booking cancellation stamps
    `BOOKING_CANCELLED`."

    Design: Corner/state_machines/booking_cancel_cascades_seat_release_and_offer_supersede
    """
    bag = scenario.create_product(factories.checked_bag_product_payload())
    seat_product = scenario.create_product(factories.standard_seat_product_payload())
    flight = scenario.create_flight()
    family = scenario.create_family(
        eco_family_payload("ECO_CASC", "Economy Cascade", bundle_price_cents=12000)
    )
    channel = scenario.create_channel(factories.direct_web_channel_payload())
    # Rows 16 to 18 crossed with three letters is a nine-seat rectangle; a row
    # start of 16 draws no row-band premium and demand is still at its floor, so
    # the seat prices at its base price of 2000 cents.
    segment = scenario.create_segment(flight["id"], seat_product["id"])
    assert_segment_counts(
        segment, total_seats=9, held_seats=0, sold_seats=0, available_seats=9
    )
    assert_money_field(segment, "effective_price_cents", 2000)

    booking = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="CASC01"
    )
    assignment = scenario.assign_seat(
        booking["id"], channel["id"], segment["id"], 16, "A"
    )
    assert assignment["assignment_state"] == "HELD", (
        "a seat taken on a held booking is itself only held, but reads "
        f"{assignment['assignment_state']!r}"
    )
    assert assignment.get("released_reason") is None, (
        "released_reason stays null while the seat is held but is "
        f"{assignment.get('released_reason')!r}"
    )
    assert_money_field(assignment, "price_charged_cents", 2000)
    assert_segment_counts(
        scenario.get_segment(segment["id"]),
        total_seats=9,
        held_seats=1,
        sold_seats=0,
        available_seats=8,
    )

    session = scenario.open_offer_session(
        booking["id"], channel["id"], "BOOKING", requested_product_ids=[bag["id"]]
    )
    assert session["candidate_count"] == 1, (
        "the session was narrowed to the checked bag alone, so candidate_count is "
        f"1 but is {session['candidate_count']}"
    )
    offer_id = session["presented_offer_ids"][0]

    cancelled = scenario.cancel(booking["id"], channel["id"], "Passenger no longer flying")
    assert cancelled["booking_status"] == "CANCELLED", (
        f"the booking must reach CANCELLED, got {cancelled['booking_status']!r}"
    )

    released = validate_success(
        api.get_seat_assignment(
            assignment["id"], make_channel_partner_headers(channel["id"])
        )
    )
    assert released["assignment_state"] == "RELEASED", (
        "the cancellation must give the seat back, but the assignment reads "
        f"{released['assignment_state']!r}"
    )
    assert released["released_reason"] == "BOOKING_CANCELLED", (
        "a seat given back by a cancellation is stamped BOOKING_CANCELLED, not "
        f"{released['released_reason']!r}"
    )
    assert_money_field(released, "price_charged_cents", 2000)

    # The held seat returns to the pool without ever having been sold.
    assert_segment_counts(
        scenario.get_segment(segment["id"]),
        total_seats=9,
        held_seats=0,
        sold_seats=0,
        available_seats=9,
    )

    superseded = validate_success(
        api.get_ancillary_offer(offer_id, make_channel_partner_headers(channel["id"]))
    )
    assert superseded["offer_status"] == "SUPERSEDED", (
        "an offer on a cancelled booking is superseded, not expired: the content "
        f"moved out from under it, but it reads {superseded['offer_status']!r}"
    )
    assert superseded.get("accepted_price_cents") is None, (
        "a superseded offer was never accepted but carries "
        f"{superseded.get('accepted_price_cents')!r}"
    )

    # Nothing was ever sold on this booking, so nothing is reversed.
    entries, meta = validate_paginated(
        api.list_booking_revenue_entries(booking["id"], REVENUE_ACCOUNTANT)
    )
    assert meta["total_count"] == 0, (
        "a held seat and a presented offer moved no money, so the cancellation has "
        f"nothing to reverse, but the ledger holds {meta['total_count']} rows"
    )
    assert entries == [], f"the ledger should be empty but holds {entries}"
    assert_money_field(cancelled, "ancillary_gross_cents", 0)
