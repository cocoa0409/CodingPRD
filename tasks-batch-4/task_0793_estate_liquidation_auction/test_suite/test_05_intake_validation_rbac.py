"""Estate/lot intake state gating, structural validation, existence, listing,
and RBAC denials.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    operator_headers, anonymous_headers, make_buyer_headers,
    create_estate_payload, create_lot_payload, create_photo_payload,
    new_estate, new_draft_lot_with_photo, new_verified_buyer, new_registered_buyer,
    attach_photo, new_lot,
    setup_live_estate_with_draft_lot,
)

OP = operator_headers()
ANON = anonymous_headers()


# ==========================================================================
# A lot's DRAFT -> CATALOGED depends on the owning estate being CATALOGING
# ==========================================================================
class TestLotCatalogRequiresEstateCataloging:
    def test_catalog_draft_lot_when_estate_live_rejected(self, api):
        """PRD §3.1: "Any lot- or photo-creation, cataloging, or listing action
        attempted when the estate is not in CATALOGING is rejected with
        ERR_ESTATE_NOT_CATALOGING (409)."

        Design: Difficulty/cross_entity_state_dependency/lot_catalog_requires_estate_cataloging
        """
        s = setup_live_estate_with_draft_lot(api)  # estate LIVE, L2 still DRAFT
        resp = api.update_lot(s["l2"]["id"], {"status": "CATALOGED"}, OP)
        validate_error(resp, ApiErrorId.ERR_ESTATE_NOT_CATALOGING.value)
        lot = validate_success(api.get_lot(s["l2"]["id"], OP))
        assert lot["status"] == "DRAFT"

    def test_catalog_draft_lot_when_estate_cataloging_succeeds(self, api):
        """PRD §3.1: "Moving a lot from DRAFT to CATALOGED requires that the
        owning estate still be in CATALOGING and that the lot already have at
        least one photo (its photo_count is 1 or more); otherwise the transition
        is refused."

        Design: Difficulty/cross_entity_state_dependency/lot_catalog_requires_estate_cataloging
        """
        estate = new_estate(api)  # CATALOGING
        lot = new_draft_lot_with_photo(api, estate["id"], starting_bid_cents=5000)
        updated = validate_success(api.update_lot(lot["id"], {"status": "CATALOGED"}, OP))
        assert updated["status"] == "CATALOGED"


# ==========================================================================
# Structural body validation (ERR_VALIDATION)
# ==========================================================================
def test_estate_create_missing_seller_name_rejected(api):
    """PRD §2.10: "(3) structural body validation — required fields present,
    correct types, valid enum members, and pagination bounds — ERR_VALIDATION
    (400)".

    Design: Corner/entities/estate_create_missing_required_field
    """
    payload = {
        "seller_email": "x@e.com",
        "auction_starts_at": "2026-03-02T10:00:00Z",
        "auction_ends_at": "2026-03-20T10:00:00Z",
    }
    resp = api.create_estate(payload, OP)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_lot_create_invalid_condition_grade_rejected(api):
    """PRD §3.1: "a condition_grade that must be one of A, B, C, or D". PRD
    §2.10: "(3) structural body validation — required fields present, correct
    types, valid enum members, and pagination bounds — ERR_VALIDATION (400)".

    Design: Corner/entities/lot_create_invalid_condition_grade
    """
    estate = new_estate(api)
    resp = api.create_lot(create_lot_payload(estate["id"], condition_grade="Z"), OP)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_list_lots_invalid_limit_rejected(api):
    """PRD §2.3: "A limit outside the range of 1 through 100, or a negative
    offset, is a validation failure (ERR_VALIDATION, HTTP 400)."

    Design: Corner/validations/list_lots_invalid_limit
    """
    estate = new_estate(api)
    resp = api.list_estate_lots(estate["id"], OP, params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ==========================================================================
# Existence (ERR_NOT_FOUND)
# ==========================================================================
def test_get_unknown_estate_not_found(api):
    """PRD §2.9: "the first identifier that does not resolve to an existing
    resource causes the request to be rejected with ERR_NOT_FOUND (HTTP 404)
    before any later reference or business rule is evaluated."

    Design: Corner/entities/estate_get_not_found
    """
    resp = api.get_estate(NON_EXISTENT_UUID, OP)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ==========================================================================
# System-defaulted fields on estate creation
# ==========================================================================
def test_estate_create_defaults_system_fields(api):
    """PRD §3.1: "A freshly created estate begins in CATALOGING status with its
    extended_count at 0 and every money field — provisional_gross_cents,
    gross_sales_cents, commission_cents, seller_payout_cents — and its lot_count
    at 0."

    Design: Corner/entities/estate_create_system_fields_defaulted
    """
    estate = validate_success(
        api.create_estate(create_estate_payload(seller_name="Sys"), OP), 201)
    assert estate["status"] == "CATALOGING"
    assert estate["extended_count"] == 0
    assert estate["lot_count"] == 0
    assert estate["provisional_gross_cents"] == 0
    assert estate["gross_sales_cents"] == 0
    assert estate["commission_cents"] == 0
    assert estate["seller_payout_cents"] == 0


# ==========================================================================
# State-machine gating on estate lifecycle
# ==========================================================================
def test_settle_before_close_rejected(api):
    """PRD §3.7: "settlement requires the estate to currently be CLOSED, and a
    settle attempt from any other status is rejected with ERR_ESTATE_NOT_CLOSED
    (409)."

    Design: Corner/state_machines/estate_settle_before_close_rejected
    """
    estate = new_estate(api)  # CATALOGING
    resp = api.settle_estate(estate["id"], OP)
    validate_error(resp, ApiErrorId.ERR_ESTATE_NOT_CLOSED.value)


def test_withdraw_draft_lot_rejected(api):
    """PRD §3.1: "An illegal lot status change — one that is not a legal
    transition from the lot's current state — is rejected with ERR_INVALID_STATE
    (409)." PRD §3.9: "a withdraw is only legal from PASSED."

    Design: Corner/state_machines/lot_withdraw_requires_passed
    """
    estate = new_estate(api)
    lot = new_lot(api, estate["id"])  # DRAFT
    resp = api.update_lot(lot["id"], {"status": "WITHDRAWN"}, OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    lot_after = validate_success(api.get_lot(lot["id"], OP))
    assert lot_after["status"] == "DRAFT"


# ==========================================================================
# Reverse-reachability: a lot's photos and its photo_count
# ==========================================================================
def test_lot_photos_reverse_list(api):
    """PRD §2.9: "Sub-resource paths list the children owned by a parent — an
    estate's lots, an estate's pickup windows, a lot's photos, an order's payment
    ledger." PRD §3.1: "Attaching a photo increments the lot's photo_count."

    Design: Corner/endpoints/lot_photos_reverse_list
    """
    estate = new_estate(api)
    lot = new_lot(api, estate["id"])
    attach_photo(api, lot["id"], image_url="http://img/1.jpg", is_primary=True)
    attach_photo(api, lot["id"], image_url="http://img/2.jpg")
    data, meta = validate_paginated(api.list_lot_photos(lot["id"], OP))
    assert len(data) == 2
    lot_after = validate_success(api.get_lot(lot["id"], OP))
    assert lot_after["photo_count"] == 2


# ==========================================================================
# RBAC denials
# ==========================================================================
def test_buyer_cannot_create_estate(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/buyer_cannot_create_estate
    """
    buyer = new_verified_buyer(api, "B1", "b1@x.com")
    resp = api.create_estate(create_estate_payload(), make_buyer_headers(buyer["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_anonymous_cannot_verify_buyer(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/anonymous_cannot_verify_buyer
    """
    buyer = new_registered_buyer(api, "B1", "b1@x.com")
    resp = api.verify_buyer(buyer["id"], ANON)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
