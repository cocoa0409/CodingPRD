"""Auth & RBAC: headers, role membership, party existence/kind, scope."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    build_user_headers,
    create_fair_payload,
    create_agreement_payload,
    create_sale_payload,
    create_booking_payload,
    make_school,
    make_publisher,
    make_author,
    make_fair,
    make_fair_open,
    make_confirmed_booking,
    make_school_coordinator_headers,
    make_publisher_rep_headers,
    make_author_rep_headers,
    TEST_USERS,
)

ORG = TEST_USERS["organizer_headers"]
CASHIER = TEST_USERS["cashier_headers"]
LINESTAFF = TEST_USERS["linestaff_headers"]


class TestHeaderAndRole:
    def test_list_fairs_missing_headers_returns_400(self, api):
        """PRD §2.1: "Every request carries two identity headers: `X-User-ID`
        and `X-User-Role`. If either header is missing or empty, the request is
        rejected with `ERR_MISSING_HEADERS` (HTTP 400)."

        Design: Corner/validations/list_fairs_missing_headers_returns_400
        """
        resp = api.list_fairs(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_HEADERS, expected_status=400)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the request is
        rejected with `ERR_MISSING_HEADERS` (HTTP 400)."

        Design: Corner/validations/list_fairs_missing_headers_returns_400
        """
        resp = api.list_fairs(headers={"X-User-Role": "Organizer"})
        validate_error(resp, ApiErrorId.ERR_MISSING_HEADERS, expected_status=400)

    def test_cashier_cannot_cancel_fair(self, api):
        """PRD §2.1: "If the named role is not in the endpoint's authorized role
        list, the request is rejected with `ERR_ROLE_FORBIDDEN` (HTTP 403)."
        PRD §4 (routing summary row for POST /fairs/{id}/cancel): "Cancel the
        fair with the deep cascade of §3.1 | Organizer"

        Design: Corner/rbac/cashier_cannot_cancel_fair
        """
        school = make_school()
        fair = make_fair(school["id"])
        resp = api.cancel_fair(fair["id"], CASHIER, {"reason": "cashier attempt"})
        validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN)
        after = validate_success(api.get_fair(fair["id"], ORG))
        assert after["status"] == "DRAFT"

    def test_linestaff_cannot_tender_sale(self, api):
        """PRD §2.1: "If the named role is not in the endpoint's authorized role
        list, the request is rejected with `ERR_ROLE_FORBIDDEN` (HTTP 403)."
        PRD §4 (routing summary row for POST /sales/{id}/tender): "`DRAFT` →
        `TENDERED`; state checks before fiscal checks | Cashier"

        Design: Corner/rbac/linestaff_cannot_tender_sale
        """
        school = make_school()
        pub = make_publisher()
        fair, agr, lines = make_fair_open(school["id"], pub["id"])
        line = lines[0]
        sale = validate_success(api.create_sale(
            create_sale_payload(fair_id=fair["id"],
                                lines=[{"stock_line_id": line["id"], "qty": 1}]),
            CASHIER,
        ), expected_status=201)
        resp = api.tender_sale(sale["id"], {"tendered_amount_cents": 1000}, LINESTAFF)
        validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN)
        after = validate_success(api.get_sale(sale["id"], ORG))
        assert after["status"] == "DRAFT"

    def test_author_rep_cannot_book_travel(self, api):
        """PRD §2.1: "If the named role is not in the endpoint's authorized role
        list, the request is rejected with `ERR_ROLE_FORBIDDEN` (HTTP 403)."
        PRD §4 (routing summary row for POST /author-bookings/{id}/book-travel):
        "`CONFIRMED` → `TRAVEL_BOOKED`; records actual travel spend | Organizer"

        Design: Corner/rbac/author_rep_cannot_book_travel
        """
        school = make_school()
        author = make_author()
        fair = make_fair(school["id"])
        booking = make_confirmed_booking(fair["id"], author["id"])
        resp = api.book_travel(
            booking["id"], {"travel_actual_cents": 1500},
            make_author_rep_headers(author["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN)
        after = validate_success(api.get_booking(booking["id"], ORG))
        assert after["status"] == "CONFIRMED"


class TestEntityBackedIdentity:
    def test_party_not_found_for_entity_backed_role(self, api):
        """PRD §2.1: "If the referenced `Party` does not exist, the request
        fails with `ERR_PARTY_NOT_FOUND` (HTTP 404)"

        Design: Corner/errors/party_not_found_for_entity_backed_role
        """
        resp = api.get_party(
            NON_EXISTENT_UUID,
            make_publisher_rep_headers(NON_EXISTENT_UUID),
        )
        validate_error(resp, ApiErrorId.ERR_PARTY_NOT_FOUND)

    def test_role_party_kind_mismatch_rejected(self, api):
        """PRD §2.1: "if the party exists but its `kind` does not match the
        role, the request fails with `ERR_ROLE_PARTY_KIND_MISMATCH` (HTTP 403)"

        Design: Corner/validations/role_party_kind_mismatch_rejected
        """
        school = make_school()
        pub = make_publisher()
        fair = make_fair(school["id"])
        agr = validate_success(api.create_agreement(
            create_agreement_payload(fair_id=fair["id"], publisher_party_id=pub["id"]),
            ORG,
        ), expected_status=201)
        # PublisherRep role but the X-User-ID is a SCHOOL party
        resp = api.accept_agreement(agr["id"], make_publisher_rep_headers(school["id"]))
        validate_error(resp, ApiErrorId.ERR_ROLE_PARTY_KIND_MISMATCH)

    def test_publisher_scope_mismatch_on_accept(self, api):
        """PRD §2.1: "if the party simply is not the party scoped to the
        resource, the request fails with `ERR_PARTY_SCOPE_MISMATCH` (HTTP 403)."
        PRD §2.10: "agreement counter, accept, and decline on the publisher side
        are scoped to the agreement's `publisher_party_id`"

        Design: Corner/validations/publisher_scope_mismatch_on_accept
        """
        school = make_school()
        pub1 = make_publisher(name="Maple Press", email="rep@maple.example")
        pub2 = make_publisher(name="Birch Books", email="rep@birch.example")
        fair = make_fair(school["id"])
        agr = validate_success(api.create_agreement(
            create_agreement_payload(fair_id=fair["id"], publisher_party_id=pub1["id"]),
            ORG,
        ), expected_status=201)
        resp = api.accept_agreement(agr["id"], make_publisher_rep_headers(pub2["id"]))
        validate_error(resp, ApiErrorId.ERR_PARTY_SCOPE_MISMATCH)
        after = validate_success(api.get_agreement(agr["id"], ORG))
        assert after["status"] == "PROPOSED"

    def test_wrong_school_cannot_confirm_venue_slot(self, api):
        """PRD §2.10: "venue-slot confirmation is scoped to the fair's school
        ... In every case a wrong-party actor is refused with
        `ERR_PARTY_SCOPE_MISMATCH` (HTTP 403)."

        Design: Corner/validations/publisher_scope_mismatch_on_accept
        """
        school_a = make_school(name="Ridgeview Elementary", email="pta@ridgeview.example")
        school_b = make_school(name="Cedar School", email="office@cedar.example")
        fair = make_fair(school_a["id"])
        from test_helpers import create_venue_slot_payload
        slot = validate_success(api.create_venue_slot(
            create_venue_slot_payload(fair_id=fair["id"]), ORG,
        ), expected_status=201)
        resp = api.confirm_venue_slot(slot["id"], make_school_coordinator_headers(school_b["id"]))
        validate_error(resp, ApiErrorId.ERR_PARTY_SCOPE_MISMATCH)
