"""Validation-precedence conflicts: when one request violates two ranked checks
at once, the lower-numbered check is the one the caller is told about, and the
refused request leaves no trace behind.
"""

from test_helpers import (
    ApiErrorId,
    create_certified_vendor,
    create_order_payload,
    make_care_agent_headers,
    make_merchandise_manager_headers,
    make_platform_admin_headers,
    order_line_input,
    refresh_item,
    refresh_vendor,
    reset_clock,
    setup_vendor_with_active_offer,
    validate_error,
    validate_paginated,
    get_success_data,
)


def _offer_with_three_orderable_units(api, suffix, now_at):
    """An ACTIVE vendor whose single ACTIVE offer carries a fresh feed of 8 on
    hand against a 5 unit safety buffer, so 3 units are orderable."""
    state = setup_vendor_with_active_offer(
        api,
        suffix=suffix,
        on_hand_units=8,
        feed_at="2026-08-03T09:00:00Z",
        now_at=now_at,
    )
    return state


def test_suppressed_offer_outranks_insufficient_availability_on_order_placement(api):
    """PRD §2.6: "Checks are evaluated strictly in the sequence below, lowest number first, and the first failure short-circuits the request."

    One line asks for 10 units of an offer that is both SUPPRESSED (rank 21) and
    short of availability (rank 38, since a suppressed offer exposes 0 available).
    The caller must see the orderability failure, never the availability one.

    Design: Difficulty/priority_pair_validation_conflict/item_not_orderable_state_check_outranks_insufficient_availability_check
    """
    state = _offer_with_three_orderable_units(
        api, suffix="PPA", now_at="2026-08-03T09:30:00Z"
    )
    item_id = state["item_id"]

    orderable = refresh_item(api, item_id)
    assert orderable["status"] == "ACTIVE"
    assert orderable["available_units"] == 3, (
        "8 on hand less a 5 unit safety buffer leaves 3 orderable units"
    )

    get_success_data(
        api.suppress_item(item_id, make_merchandise_manager_headers("mm-suppress-ppa"))
    )
    suppressed = refresh_item(api, item_id)
    assert suppressed["status"] == "SUPPRESSED"
    assert suppressed["suppression_reason"] == "MANUAL"
    assert suppressed["available_units"] == 0
    assert suppressed["inventory_is_stale"] is False, (
        "a 30 minute old feed against a 180 minute limit is still fresh, so the "
        "freshness check cannot pre-empt the pair under test"
    )

    response = api.create_order(
        create_order_payload("ORD-PPA-CONFLICT", [order_line_input(item_id, 10)]),
        make_care_agent_headers("care-ppa"),
    )
    validate_error(response, ApiErrorId.ERR_ITEM_NOT_ORDERABLE.value)


def test_insufficient_availability_surfaces_alone_when_the_offer_stays_active(api):
    """PRD §3.5: "And the requested `quantity` must be at most the offer's `available_units`: a request for exactly `available_units` units is accepted, and one unit more is refused with `ERR_INSUFFICIENT_AVAILABILITY`."

    The same over-large quantity against the same offer, left ACTIVE this time,
    isolates the lower-ranked availability failure.

    Design: Difficulty/priority_pair_validation_conflict/item_not_orderable_state_check_outranks_insufficient_availability_check
    """
    state = _offer_with_three_orderable_units(
        api, suffix="PPB", now_at="2026-08-03T09:30:00Z"
    )
    item_id = state["item_id"]

    item = refresh_item(api, item_id)
    assert item["status"] == "ACTIVE"
    assert item["available_units"] == 3
    assert item["inventory_is_stale"] is False

    care = make_care_agent_headers("care-ppb")
    response = api.create_order(
        create_order_payload("ORD-PPB-OVER", [order_line_input(item_id, 10)]),
        care,
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_AVAILABILITY.value)

    exact = api.create_order(
        create_order_payload("ORD-PPB-EXACT", [order_line_input(item_id, 3)]),
        care,
    )
    assert exact.status_code == 201, (
        "a request for exactly available_units must be accepted: "
        f"got {exact.status_code} {exact.text}"
    )


def test_refused_order_against_suppressed_offer_reserves_nothing(api):
    """PRD §2.6: "No row is mutated when a request fails."

    The short-circuited placement must not reserve units, must not advance the
    offer's version and must not leave an order line behind.

    Design: Difficulty/priority_pair_validation_conflict/item_not_orderable_state_check_outranks_insufficient_availability_check
    """
    state = _offer_with_three_orderable_units(
        api, suffix="PPC", now_at="2026-08-03T09:30:00Z"
    )
    item_id = state["item_id"]
    get_success_data(
        api.suppress_item(item_id, make_merchandise_manager_headers("mm-suppress-ppc"))
    )
    before = refresh_item(api, item_id)

    response = api.create_order(
        create_order_payload("ORD-PPC-CONFLICT", [order_line_input(item_id, 10)]),
        make_care_agent_headers("care-ppc"),
    )
    validate_error(response, ApiErrorId.ERR_ITEM_NOT_ORDERABLE.value)

    after = refresh_item(api, item_id)
    assert after["reserved_units"] == 0
    assert after["lifetime_reserved_units"] == 0
    assert after["version"] == before["version"], (
        "a failed placement may not bump the offer's version"
    )

    admin = make_platform_admin_headers("admin-ppc")
    lines, meta = validate_paginated(
        api.list_order_lines(admin, params={"item_id": item_id})
    )
    assert lines == []
    assert meta["total_count"] == 0


def test_segregation_of_duties_outranks_missing_serviceability_coverage(api):
    """PRD §2.11: "At the identity level, the check goes further: the `X-User-ID` presented when a vendor is activated must differ from the value stored in that vendor's `certified_by_user_id`, and an attempt to do both with the same operator identity is refused with `ERR_SEGREGATION_OF_DUTIES`."

    The activating operator id is the certifier's (rank 27) and the vendor also
    has no live coverage row at all (rank 29). The duty-separation guard answers.

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_check_outranks_missing_serviceability_coverage_check
    """
    reset_clock(api)
    vendor = create_certified_vendor(api, suffix="SODA", rules=[])
    assert vendor["onboarding_status"] == "CERTIFIED"
    assert vendor["certified_by_user_id"] == "ops-cert-SODA"

    admin = make_platform_admin_headers("admin-soda")
    rules, meta = validate_paginated(
        api.list_serviceability_rules(vendor["id"], admin)
    )
    assert rules == [], "the vendor must reach activation with zero coverage rows"
    assert meta["total_count"] == 0

    response = api.activate_vendor(
        vendor["id"], make_merchandise_manager_headers("ops-cert-SODA")
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_missing_serviceability_coverage_surfaces_alone_under_a_distinct_activator(api):
    """PRD §2.6: "The vendor has at least one serviceability rule with `status` `ACTIVE`; for offer activation that rule must additionally match the offer's `ship_method`."

    With the duty-separation condition satisfied by a different operator id, the
    lower-ranked coverage requirement is what refuses the go-live.

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_check_outranks_missing_serviceability_coverage_check
    """
    reset_clock(api)
    vendor = create_certified_vendor(api, suffix="SODB", rules=[])
    assert vendor["certified_by_user_id"] == "ops-cert-SODB"

    response = api.activate_vendor(
        vendor["id"], make_merchandise_manager_headers("mm-activator-SODB")
    )
    validate_error(response, ApiErrorId.ERR_NO_SERVICEABILITY_COVERAGE.value)


def test_refused_activation_leaves_the_vendor_untouched_in_certified(api):
    """PRD §2.6: "No row is mutated when a request fails."

    The duty-separation refusal must not stamp `activated_by_user_id`, must not
    move the vendor off `CERTIFIED` and must not advance its version.

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_check_outranks_missing_serviceability_coverage_check
    """
    reset_clock(api)
    vendor = create_certified_vendor(api, suffix="SODC", rules=[])
    before = refresh_vendor(api, vendor["id"])

    response = api.activate_vendor(
        vendor["id"], make_merchandise_manager_headers("ops-cert-SODC")
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    after = refresh_vendor(api, vendor["id"])
    assert after["onboarding_status"] == "CERTIFIED"
    assert after["certified_by_user_id"] == "ops-cert-SODC"
    assert after["activated_by_user_id"] is None
    assert after["version"] == before["version"], (
        "a refused activation may not bump the vendor's version"
    )
