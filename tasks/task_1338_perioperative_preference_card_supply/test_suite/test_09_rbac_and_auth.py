"""RBAC gates, auth-header handling, and entity-backed ownership."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_success_data,
    make_case,
    make_published_card,
    make_supply_item,
    make_surgeon,
    make_surgeon_headers,
    publish_card,
    release_pick_list,
    setup_completed_case,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
CART = TEST_USERS["cart_tech_headers"]
ANY = TEST_USERS["any_headers"]


def _glove():
    return make_supply_item(sku="GLOVE-PR", name="Gloves pair",
                            unit_cost_cents=250, substitute_group="GLOVES",
                            initial_on_hand=100)


class TestAuthContext:
    def test_request_missing_auth_headers_returns_error_envelope(self):
        """PRD §2.1: "A request missing either header, or carrying a role name
        the system does not recognize, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
        PRD §2.7: "**Authentication context**: ... present and the role
        recognized" is priority 1, ahead of existence (priority 4).
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/errors/request_missing_auth_headers_returns_error_envelope
        """
        resp = api_client.get_surgeon(
            "11111111-1111-1111-1111-111111111111", headers={}
        )
        err = validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        assert "message" in err and len(err["message"]) > 0
        body = resp.json()
        assert body["response_type"] == "error"


class TestRoleGates:
    def test_surgeon_cannot_publish_card(self):
        """PRD §2.1: "Once authenticated, the caller's role is checked against
        the endpoint's authorization policy; a caller whose role is not
        permitted — or who fails an entity-backed ownership check — is rejected
        with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §3.2: "Publishing is the act that makes a `DRAFT` card operative,
        moving it `DRAFT → ACTIVE`. The analyst's publish request must carry
        `expected_card_version` matching the card's current `version`"

        Design: Corner/rbac/surgeon_cannot_publish_card
        """
        surgeon = make_surgeon(full_name="Dr. Rbac")
        glove = _glove()
        # Build a DRAFT card with one line, unpublished.
        from test_helpers import make_draft_card, add_card_line
        draft = make_draft_card(surgeon["id"], "TKA")
        add_card_line(draft["id"], glove["id"], quantity=1, designation="OPEN",
                      pick_sequence=1)
        card_now = get_success_data(api_client.get_preference_card(draft["id"], ANY))
        resp = api_client.publish_preference_card(
            draft["id"], {"expected_card_version": card_now["version"]},
            make_surgeon_headers(surgeon["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        after = get_success_data(api_client.get_preference_card(draft["id"], ANY))
        assert after["status"] == "DRAFT"

    def test_cart_technician_cannot_capture_charge(self):
        """PRD §2.1: "a caller whose role is not permitted ... is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §2.7: "**Authorization**: the caller's role is permitted on the
        endpoint" is priority 2, ahead of existence (priority 4 — "Existence:
        path identifiers resolve").
        PRD §4: capture is authorized for `MaterialsManager` only.

        Design: Corner/rbac/cart_technician_cannot_capture_charge
        """
        resp = api_client.capture_consignment_charge(
            "33333333-3333-3333-3333-333333333333", CART
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_value_officer_cannot_create_supply_item(self):
        """PRD §2.1: "Once authenticated, the caller's role is checked against
        the endpoint's authorization policy; a caller whose role is not
        permitted — or who fails an entity-backed ownership check — is rejected
        with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §3.1: "The supply catalog is likewise owned by the
        `SupplyChainAnalyst`."

        Design: Corner/rbac/value_officer_cannot_create_supply_item
        """
        from test_helpers import make_officer_headers
        resp = api_client.create_supply_item(
            {"sku": "X-1", "name": "Thing", "unit_cost_cents": 100},
            make_officer_headers("officer-9"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_non_owning_surgeon_cannot_dispute_audit(self):
        """PRD §3.6: "only the surgeon who owns the audited card may do so:
        the caller's `X-User-ID` must equal the audited card's `surgeon_id`, or
        the dispute is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/rbac/non_owning_surgeon_cannot_dispute_audit
        """
        s_a = make_surgeon(full_name="Dr. A", specialty="ORTHO")
        s_b = make_surgeon(full_name="Dr. B", specialty="CARD")
        glove = _glove()
        ctx = setup_completed_case(
            s_a, [glove],
            [{"item_index": 0, "quantity": 1, "designation": "OPEN"}],
            usage_by_index={0: 1},
            procedure_name="TKA",
            scheduled_start="2026-09-05T08:00:00Z",
            expected_duration_min=60,
            room="OR-1",
        )
        audit = ctx["audit"]
        resp = api_client.dispute_card_audit(
            audit["id"], {"comment": "not my card"},
            make_surgeon_headers(s_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        after = get_success_data(api_client.get_card_audit(audit["id"], ANY))
        assert after["status"] == "GENERATED"

    def test_get_endpoints_readable_by_any_role(self):
        """PRD §2.1: "A seventh designation, `Any`, denotes that every
        authenticated role may call the read endpoints: all GET operations are
        authorized for `Any`."

        Design: Corner/rbac/get_endpoints_readable_by_any_role
        """
        surgeon = make_surgeon(full_name="Dr. Read")
        glove = _glove()
        card = make_published_card(
            surgeon["id"], "TKA",
            [{"supply_item_id": glove["id"], "quantity": 1}],
        )
        case = make_case(surgeon["id"], card["id"])
        got_card = validate_success(api_client.get_preference_card(card["id"], ANY))
        got_case = validate_success(api_client.get_case(case["id"], ANY))
        assert got_card["id"] == card["id"]
        assert got_case["id"] == case["id"]
