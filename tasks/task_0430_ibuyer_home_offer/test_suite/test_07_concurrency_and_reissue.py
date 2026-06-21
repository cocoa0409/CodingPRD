"""Re-issuing offers: optimistic concurrency on Property.version, supersession of
the prior active offer, the single-active-offer invariant, and re-issuability gating.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    make_seller_headers,
    set_clock,
    create_seller,
    create_property,
    issue_offer,
    setup_property_under_offer,
    reissue_offer,
    get_property_version,
    accept_offer,
)

_ANALYST = TEST_USERS["pricing_analyst_headers"]
_ADMIN = TEST_USERS["operations_admin_headers"]


def test_reissue_supersedes_prior_and_keeps_single_active_offer(api):
    """PRD §3.2: "When a re-issue succeeds, the prior active offer moves to
    `SUPERSEDED` (with no payout effect — a superseded offer simply ceases to be
    acceptable), a new offer is created in `ISSUED`, the property's `active_offer_id`
    is repointed to the new offer, and the property's `version` increments by 1."

    Design: Difficulty/compensating_invariant/reissue_supersede_conserves_single_active_offer_count
    """
    seller, prop, offer1 = setup_property_under_offer()
    prop_v = get_property_version(prop["id"])
    offer2 = reissue_offer(prop["id"], prop_v)

    offer1_after = validate_success(api.get_offer(offer1["id"], _ANALYST))
    assert offer1_after["status"] == "SUPERSEDED", offer1_after["status"]
    assert offer2["status"] == "ISSUED", offer2["status"]
    prop_after = validate_success(api.get_property(prop["id"], _ANALYST))
    assert prop_after["active_offer_id"] == offer2["id"], prop_after["active_offer_id"]


def test_reissue_conserves_single_issued_offer_count(api):
    """PRD §3.2: "Re-issuing an offer for a property already `UNDER_OFFER` keeps the
    property in `UNDER_OFFER` but replaces the offer."
    PRD §3.2: "the prior active offer moves to `SUPERSEDED` (with no payout effect —
    a superseded offer simply ceases to be acceptable), a new offer is created in
    `ISSUED`"

    Design: Difficulty/compensating_invariant/reissue_supersede_conserves_single_active_offer_count
    """
    seller, prop, offer1 = setup_property_under_offer()
    prop_v = get_property_version(prop["id"])
    reissue_offer(prop["id"], prop_v)
    offers = validate_success(api.list_property_offers(prop["id"], _ANALYST))
    issued = [o for o in offers if o["status"] == "ISSUED"]
    assert len(issued) == 1, [o["status"] for o in offers]


def test_reissue_with_stale_version_rejected_412(api):
    """PRD §2.8: "If that value does not equal the property's current `version` —
    because some other writer has advanced the property since the client last read it
    — the re-issue is rejected with `ERR_STALE_VERSION` (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/occ_stale_property_version_rejected_412
    """
    seller, prop, offer1 = setup_property_under_offer()
    prop_v = get_property_version(prop["id"])
    # First re-issue with the correct version succeeds and bumps Property.version.
    reissue_offer(prop["id"], prop_v)
    # Second re-issue carrying the now-stale pre-bump version is rejected.
    validate_error(
        api.issue_offer(
            prop["id"], {"service_fee_pct": 0.05, "expected_property_version": prop_v}, _ANALYST
        ),
        ApiErrorId.ERR_STALE_VERSION,
    )


def test_property_version_increments_on_reissue(api):
    """PRD §3.2: "the property's `active_offer_id` is repointed to the new offer, and
    the property's `version` increments by 1."

    Design: Corner/cross_cutting_complexity_layers/property_version_increments_on_reissue
    """
    seller, prop, offer1 = setup_property_under_offer()
    prop_v = get_property_version(prop["id"])
    reissue_offer(prop["id"], prop_v)
    after = validate_success(api.get_property(prop["id"], _ANALYST))
    assert after["version"] == prop_v + 1, (after["version"], prop_v)


def test_reissue_after_accept_not_reissuable(api):
    """PRD §3.2: "A re-issue is permitted only when the property's currently active
    offer is in one of `ISSUED`, `EXPIRED`, or `DECLINED` status; if the active offer
    is `ACCEPTED` or `SUPERSEDED` it cannot be superseded again and the request is
    rejected with `ERR_OFFER_NOT_REISSUABLE`."

    Design: Corner/validations/reissue_not_reissuable_after_accept_returns_error
    """
    seller, prop, offer1 = setup_property_under_offer()
    accept_offer(offer1["id"], seller["id"])
    prop_v = get_property_version(prop["id"])
    validate_error(
        api.issue_offer(
            prop["id"], {"service_fee_pct": 0.05, "expected_property_version": prop_v}, _ANALYST
        ),
        ApiErrorId.ERR_OFFER_NOT_REISSUABLE,
    )


def test_list_property_offers_returns_current_and_superseded(api):
    """PRD §4 (GET /properties/{id}/offers): "List all offers issued for a property
    (current and superseded)."
    PRD §3.2: "the prior active offer moves to `SUPERSEDED` (with no payout effect —
    a superseded offer simply ceases to be acceptable), a new offer is created in
    `ISSUED`"

    Design: Corner/endpoints/list_offers_for_property_returns_current_and_superseded
    """
    seller, prop, offer1 = setup_property_under_offer()
    prop_v = get_property_version(prop["id"])
    reissue_offer(prop["id"], prop_v)
    offers = validate_success(api.list_property_offers(prop["id"], _ANALYST))
    assert isinstance(offers, list) and len(offers) == 2, offers
    statuses = sorted(o["status"] for o in offers)
    assert statuses == ["ISSUED", "SUPERSEDED"], statuses
