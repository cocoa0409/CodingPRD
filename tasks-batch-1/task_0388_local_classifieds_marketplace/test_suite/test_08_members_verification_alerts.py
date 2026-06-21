"""Member registration & verification, category immutability, flag enum
validation, and saved-search alert fan-out.

Translates the remaining Corner entity / calculation / cross-cutting rows not
covered by the lifecycle, offer, meetup, cascade, and auth test files.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    make_seller_headers, make_buyer_headers, make_member_headers,
    TEST_USERS, fixtures as fx,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Member registration defaults
# ---------------------------------------------------------------------------
class TestMemberRegistration:
    def test_role_kind_defaults_to_both(self, api):
        """PRD §3.1: "role_kind, when given, must be one of SELLER, BUYER, or
        BOTH, defaulting to BOTH. On registration the member's status begins
        ACTIVE, phone_verified begins false, verification_code is null, the derived
        trust_score is initialized to the base reputation value of 50"

        Design: Corner/entities/member_role_kind_defaults_to_both
        """
        data = validate_success(api.create_member(
            {"email": "m-default@x.com", "display_name": "M"}, headers=ANON),
            expected_status=201)
        assert data["role_kind"] == "BOTH"
        assert data["status"] == "ACTIVE"
        assert data["trust_score"] == 50


# ---------------------------------------------------------------------------
# Phone verification (Corner: calculations)
# ---------------------------------------------------------------------------
class TestVerification:
    def test_verification_bonus_applied_on_confirm(self, api):
        """PRD §3.1: "add a verification bonus of 20 if and only if the member's
        phone_verified is true, and 0 otherwise"
        PRD §3.1: "On a match, phone_verified is set to true, the stored
        verification_code is cleared, the member's version increments by 1, and the
        trust_score is recomputed immediately."

        Design: Corner/calculations/trust_score_verification_bonus_applied
        """
        member = fx.create_member(role_kind="BOTH", display_name="M")
        req = get_success_data(api.request_verification(member["id"],
                                                        headers=make_member_headers(member["id"])))
        code = req["verification_code"]
        confirmed = validate_success(api.confirm_verification(
            member["id"], {"verification_code": code},
            headers=make_member_headers(member["id"])))
        assert confirmed["phone_verified"] is True
        assert confirmed["trust_score"] == 70

    def test_verification_code_mismatch_rejected(self, api):
        """PRD §3.1: "Confirming verification submits a verification_code; if the
        submitted code does not match the member's minted verification_code, the
        request fails with ERR_VERIFICATION_CODE_MISMATCH (HTTP 422)."

        Design: Corner/calculations/verification_code_mismatch_rejected
        """
        member = fx.create_member(role_kind="BOTH", display_name="M")
        get_success_data(api.request_verification(member["id"],
                                                  headers=make_member_headers(member["id"])))
        validate_error(api.confirm_verification(
            member["id"], {"verification_code": "DEFINITELY-WRONG"},
            headers=make_member_headers(member["id"])),
            ApiErrorId.ERR_VERIFICATION_CODE_MISMATCH.value)
        fetched = validate_success(api.get_member(member["id"],
                                                  headers=make_member_headers(member["id"])))
        assert fetched["phone_verified"] is False


# ---------------------------------------------------------------------------
# Category immutability
# ---------------------------------------------------------------------------
class TestCategoryImmutability:
    def test_category_carries_no_version_field(self, api):
        """PRD §2.4: "Four entities are lightweight records that carry only an id
        and a created_at, with no updated_at and no version field: Category,
        Message, SafeTradeSpot, and Alert are immutable once written."

        Design: Corner/entities/category_immutable_no_version_field
        """
        fx.create_category(slug="furniture", name="Furniture")
        data, _ = validate_paginated(api.list_categories(headers=ANON))
        assert len(data) >= 1
        cat = next(c for c in data if c["slug"] == "furniture")
        assert "version" not in cat, "Category is immutable and exposes no version"
        assert "updated_at" not in cat


# ---------------------------------------------------------------------------
# Flag enum validation
# ---------------------------------------------------------------------------
class TestFlagValidation:
    def test_invalid_reason_enum_rejected(self, api):
        """PRD §3.7: "a reason of SPAM, PROHIBITED, SCAM, MISCATEGORIZED, or
        OTHER."
        PRD §2.8: "(8) basic request well-formedness (ERR_INVALID_REQUEST)."

        Design: Corner/entities/create_flag_invalid_reason_enum_rejected
        """
        base = fx.setup_published_listing(ask_price_cents=10000,
                                          min_acceptable_price_cents=5000)
        listing_id = base["listing"]["id"]
        reporter = fx.create_member(role_kind="BUYER", display_name="R")
        validate_error(api.create_flag(
            {"reporter_id": reporter["id"], "target_type": "LISTING",
             "target_listing_id": listing_id, "reason": "NONSENSE"},
            headers=make_member_headers(reporter["id"])),
            ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Saved-search alert fan-out (Corner: cross_cutting_complexity_layers)
# ---------------------------------------------------------------------------
class TestAlertFanout:
    def test_alert_fanout_increments_matching_saved_search(self, api):
        """PRD §3.8: "For every saved search whose category_slug equals the newly
        published listing's category_slug, and whose keyword is either null or a
        case-insensitive substring of the listing's title, and whose
        max_price_cents is either 0 or greater than or equal to the listing's
        ask_price_cents, the system creates one Alert and increments that saved
        search's alert_count by 1."

        Design: Corner/cross_cutting_complexity_layers/saved_search_alert_fanout_on_publish
        """
        fx.create_category(slug="furniture", name="Furniture")
        seller = fx.create_member(role_kind="SELLER", display_name="S")
        buyer = fx.create_member(role_kind="BUYER", display_name="B")
        ss_match = get_success_data(api.create_saved_search(
            {"owner_id": buyer["id"], "category_slug": "furniture",
             "keyword": "desk", "max_price_cents": 12000},
            headers=make_member_headers(buyer["id"])))
        ss_nomatch = get_success_data(api.create_saved_search(
            {"owner_id": buyer["id"], "category_slug": "furniture",
             "keyword": "sofa", "max_price_cents": 12000},
            headers=make_member_headers(buyer["id"])))
        listing = fx.create_listing(seller["id"], title="Oak Desk",
                                    ask_price_cents=10000,
                                    min_acceptable_price_cents=5000)
        fx.publish_listing(listing["id"], seller["id"])
        matched = validate_success(api.get_saved_search(ss_match["id"],
                                                        headers=make_member_headers(buyer["id"])))
        assert matched["alert_count"] == 1
        unmatched = validate_success(api.get_saved_search(ss_nomatch["id"],
                                                          headers=make_member_headers(buyer["id"])))
        assert unmatched["alert_count"] == 0, "keyword 'sofa' does not match 'Oak Desk'"
        alerts, _ = validate_paginated(api.list_saved_search_alerts(
            ss_match["id"], headers=make_member_headers(buyer["id"])))
        assert len(alerts) == 1
        assert alerts[0]["listing_id"] == listing["id"]
