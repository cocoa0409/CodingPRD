"""Offer lifecycle: acceptance cascade, expiry window, withdrawal, and the
Property branching off UNDER_OFFER.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_seller_headers,
    set_clock,
    create_seller,
    create_property,
    issue_offer,
    setup_property_under_offer,
    accept_offer,
)

_ANALYST = TEST_USERS["pricing_analyst_headers"]
_ADMIN = TEST_USERS["operations_admin_headers"]


def test_accept_offer_spawns_transaction_and_assessment(api):
    """PRD §3.3: "A successful acceptance moves the offer `ISSUED → ACCEPTED` and the
    property `UNDER_OFFER → IN_TRANSACTION`, and it spawns two children: a home
    `Assessment` in `DRAFT` status bound to the accepted offer, and a `Transaction`
    in `PENDING_ASSESSMENT` status."

    Design: Difficulty/transitive_cascade/accept_cascade_depth2_offer_property_spawn_transaction
    """
    seller, prop, offer = setup_property_under_offer()
    txn = validate_success(
        api.accept_offer(offer["id"], {}, make_seller_headers(seller["id"]))
    )
    assert txn["status"] == "PENDING_ASSESSMENT", txn["status"]

    offer_after = validate_success(api.get_offer(offer["id"], _ANALYST))
    assert offer_after["status"] == "ACCEPTED", offer_after["status"]
    prop_after = validate_success(api.get_property(prop["id"], _ANALYST))
    assert prop_after["status"] == "IN_TRANSACTION", prop_after["status"]


def test_accept_offer_creates_draft_assessment(api):
    """PRD §3.3: "it spawns two children: a home `Assessment` in `DRAFT` status bound
    to the accepted offer, and a `Transaction` in `PENDING_ASSESSMENT` status."
    PRD §3.4: "Acceptance creates an `Assessment` in `DRAFT` status, linked to the
    accepted offer through `offer_id`."

    Design: Difficulty/transitive_cascade/accept_cascade_depth2_offer_property_spawn_transaction
    """
    seller, prop, offer = setup_property_under_offer()
    accept_offer(offer["id"], seller["id"])
    assessments = validate_success(api.get_offer_assessment(offer["id"], _ADMIN))
    assert isinstance(assessments, list) and len(assessments) == 1
    assert assessments[0]["status"] == "DRAFT", assessments[0]["status"]
    assert assessments[0]["offer_id"] == offer["id"]


def test_accept_at_exactly_expires_at_rejected(api):
    """PRD §3.3: "When the owning `Seller` accepts an offer, the offer must still be
    in `ISSUED` status and the clock must be strictly before `expires_at`; an accept
    attempted at or after `expires_at` is rejected with `ERR_OFFER_EXPIRED`."

    Design: Difficulty/resource_temporal_overlap/offer_validity_window_expiry_half_open
    """
    set_clock("2026-03-01T00:00:00Z")
    seller = create_seller()
    prop = create_property(seller["id"])
    offer = issue_offer(prop["id"])
    # issued_at 2026-03-01, expires_at = +5 days = 2026-03-06T00:00:00Z (PRD §3.2).
    assert offer["expires_at"].startswith("2026-03-06T00:00:00"), offer["expires_at"]
    set_clock("2026-03-06T00:00:00Z")
    validate_error(
        api.accept_offer(offer["id"], {}, make_seller_headers(seller["id"])),
        ApiErrorId.ERR_OFFER_EXPIRED,
    )


def test_accept_just_before_expiry_succeeds(api):
    """PRD §3.3: "the clock must be strictly before `expires_at`; an accept attempted
    at or after `expires_at` is rejected with `ERR_OFFER_EXPIRED`."

    Design: Difficulty/resource_temporal_overlap/offer_validity_window_expiry_half_open
    """
    set_clock("2026-03-01T00:00:00Z")
    seller = create_seller()
    prop = create_property(seller["id"])
    offer = issue_offer(prop["id"])
    # One second before expires_at (2026-03-06T00:00:00Z) is still acceptable.
    set_clock("2026-03-05T23:59:59Z")
    txn = validate_success(
        api.accept_offer(offer["id"], {}, make_seller_headers(seller["id"]))
    )
    assert txn["status"] == "PENDING_ASSESSMENT", txn["status"]


def test_clock_default_makes_offer_unexpired_before_any_set(api):
    """PRD §2.7: "On server startup the clock reads exactly `2026-01-01T00:00:00Z`,
    and until it is explicitly advanced it never falls back to real time."
    PRD §3.2: "The offer records its `issued_at` as the current logical-clock instant
    and sets `expires_at` to five days after `issued_at`."

    Design: Corner/cross_cutting_complexity_layers/clock_default_makes_offer_unexpired_before_any_set
    """
    # Do NOT set the clock: it reads the startup default 2026-01-01T00:00:00Z.
    seller = create_seller()
    prop = create_property(seller["id"])
    offer = issue_offer(prop["id"])
    txn = validate_success(
        api.accept_offer(offer["id"], {}, make_seller_headers(seller["id"]))
    )
    offer_after = validate_success(api.get_offer(offer["id"], _ANALYST))
    assert offer_after["status"] == "ACCEPTED", offer_after["status"]
    assert txn["status"] == "PENDING_ASSESSMENT", txn["status"]


def test_withdraw_property_branch_to_withdrawn(api):
    """PRD §3.3: "A successful withdrawal moves the active offer to `DECLINED`, clears
    `active_offer_id` to null, and moves the property to the terminal `WITHDRAWN`
    status."

    Design: Difficulty/non_linear_state_machine/property_branches_under_offer_to_in_transaction_or_withdrawn
    """
    seller, prop, offer = setup_property_under_offer()
    result = validate_success(
        api.withdraw_property(prop["id"], {}, make_seller_headers(seller["id"]))
    )
    assert result["status"] == "WITHDRAWN", result["status"]
    assert result["active_offer_id"] is None
    offer_after = validate_success(api.get_offer(offer["id"], _ANALYST))
    assert offer_after["status"] == "DECLINED", offer_after["status"]


def test_withdraw_property_offer_declined_and_pointer_cleared(api):
    """PRD §3.3: "Separately, the seller may withdraw the whole property from offer
    while it is `UNDER_OFFER`."
    PRD §3.3: "A successful withdrawal moves the active offer to `DECLINED`, clears
    `active_offer_id` to null, and moves the property to the terminal `WITHDRAWN`
    status."

    Design: Difficulty/non_linear_state_machine/property_branches_under_offer_to_in_transaction_or_withdrawn
    """
    seller, prop, offer = setup_property_under_offer()
    validate_success(
        api.withdraw_property(prop["id"], {}, make_seller_headers(seller["id"]))
    )
    prop_after = validate_success(api.get_property(prop["id"], _ANALYST))
    assert prop_after["active_offer_id"] is None
    assert prop_after["status"] == "WITHDRAWN"
    offer_after = validate_success(api.get_offer(offer["id"], _ANALYST))
    assert offer_after["status"] == "DECLINED"


def test_accept_after_withdraw_rejected_invalid_state(api):
    """PRD §3.3: "the offer being accepted must be the property's current
    `active_offer_id` while the property is `UNDER_OFFER`."
    PRD §3.7: "A close attempted on a transaction that is not in `INSPECTION`, like
    any other transition attempted from an invalid state, is rejected with
    `ERR_INVALID_STATE`"

    Design: Difficulty/cross_entity_state_dependency/offer_accept_depends_on_property_under_offer_offer_vs_property
    """
    seller, prop, offer = setup_property_under_offer()
    validate_success(
        api.withdraw_property(prop["id"], {}, make_seller_headers(seller["id"]))
    )
    # Property is now WITHDRAWN and the offer DECLINED — accept is no longer valid.
    validate_error(
        api.accept_offer(offer["id"], {}, make_seller_headers(seller["id"])),
        ApiErrorId.ERR_INVALID_STATE,
    )


def test_accept_requires_property_under_offer_precondition(api):
    """PRD §3.3: "the offer being accepted must be the property's current
    `active_offer_id` while the property is `UNDER_OFFER`."
    PRD §3.3: "A successful withdrawal moves the active offer to `DECLINED`, clears
    `active_offer_id` to null, and moves the property to the terminal `WITHDRAWN`
    status."

    Design: Difficulty/cross_entity_state_dependency/offer_accept_depends_on_property_under_offer_offer_vs_property
    """
    seller, prop, offer = setup_property_under_offer()
    validate_success(
        api.withdraw_property(prop["id"], {}, make_seller_headers(seller["id"]))
    )
    # Confirm the Property left UNDER_OFFER (the precondition the accept depends on).
    prop_after = validate_success(api.get_property(prop["id"], _ANALYST))
    assert prop_after["status"] == "WITHDRAWN", prop_after["status"]
    assert prop_after["active_offer_id"] is None
    validate_error(
        api.accept_offer(offer["id"], {}, make_seller_headers(seller["id"])),
        ApiErrorId.ERR_INVALID_STATE,
    )
