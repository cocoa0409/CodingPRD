"""Product request value-analysis pipeline: quorum, SoD, endorsements, cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    endorse_request,
    get_success_data,
    make_officer_headers,
    make_product_request,
    make_supply_item,
    make_surgeon,
    make_surgeon_headers,
    open_review,
    setup_request_quorum_met,
    setup_request_under_review,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
ANY = TEST_USERS["any_headers"]


class TestEndorsements:
    def test_endorse_twice_same_officer_rejected(self):
        """PRD §3.7: "each endorsement appends the acting officer's id to
        `endorser_ids`, increments `endorsements_count` (which always equals
        the number of distinct endorsers), and is rejected with
        `ERR_DUPLICATE_ENDORSEMENT` when the officer has already endorsed."

        Design: Corner/validations/endorse_twice_same_officer_rejected
        """
        surgeon = make_surgeon(full_name="Dr. Endo", specialty="CARD")
        req = setup_request_under_review(surgeon, reviewing_officer="officer-1")
        endorse_request(req["id"], "officer-1")
        resp = api_client.endorse_product_request(
            req["id"], make_officer_headers("officer-1")
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENDORSEMENT)
        after = get_success_data(api_client.get_product_request(req["id"], ANY))
        assert after["endorsements_count"] == 1

    def test_endorse_submitted_request_rejected(self):
        """PRD §3.7: "A `ValueAnalysisOfficer` opens review on a `SUBMITTED`
        request — any other state draws `ERR_REQUEST_NOT_UNDER_REVIEW`" and
        endorsement applies "While under review"

        Design: Corner/errors/endorse_submitted_request_rejected
        """
        surgeon = make_surgeon(full_name="Dr. Sub", specialty="CARD")
        req = make_product_request(surgeon)
        resp = api_client.endorse_product_request(
            req["id"], make_officer_headers("officer-1")
        )
        validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_UNDER_REVIEW)
        after = get_success_data(api_client.get_product_request(req["id"], ANY))
        assert after["endorsements_count"] == 0


class TestApproval:
    def test_approve_below_quorum_rejected(self):
        """PRD §3.7: "The request must be `UNDER_REVIEW`
        (`ERR_REQUEST_NOT_UNDER_REVIEW`), its `endorsements_count` must be at
        least 2 (`ERR_QUORUM_NOT_MET`)"

        Design: Corner/validations/approve_below_quorum_rejected
        """
        surgeon = make_surgeon(full_name="Dr. Quo", specialty="CARD")
        req = setup_request_under_review(surgeon, reviewing_officer="officer-1")
        endorse_request(req["id"], "officer-1")
        resp = api_client.approve_product_request(
            req["id"], make_officer_headers("officer-2")
        )
        validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET)
        after = get_success_data(api_client.get_product_request(req["id"], ANY))
        assert after["status"] == "UNDER_REVIEW"

    def test_reviewer_cannot_approve_own_review(self):
        """PRD §3.7: "the approving officer's `X-User-ID` must differ from
        `reviewing_officer_id` — the officer who opened review may never
        approve it, an attempt drawing `ERR_SOD_REVIEWER_CANNOT_APPROVE` (HTTP
        403)"

        Design: Corner/validations/reviewer_cannot_approve_own_review
        """
        surgeon = make_surgeon(full_name="Dr. Sod", specialty="CARD")
        req = setup_request_quorum_met(surgeon, reviewing_officer="officer-1")
        resp = api_client.approve_product_request(
            req["id"], make_officer_headers("officer-1")
        )
        validate_error(resp, ApiErrorId.ERR_SOD_REVIEWER_CANNOT_APPROVE)
        after = get_success_data(api_client.get_product_request(req["id"], ANY))
        assert after["status"] == "UNDER_REVIEW"

    def test_approve_blocked_when_requester_deactivated(self):
        """PRD §3.7: "the requesting surgeon must still be `ACTIVE`
        (`ERR_REQUESTER_INACTIVE`)"
        PRD §3.1: "approval of that surgeon's pending product request fails
        with `ERR_REQUESTER_INACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/approve_blocked_when_requester_deactivated
        """
        surgeon = make_surgeon(full_name="Dr. Req", specialty="CARD")
        req = setup_request_quorum_met(
            surgeon, reviewing_officer="officer-1",
            proposed_sku="VALVE-INTRO-1",
        )
        get_success_data(api_client.deactivate_surgeon(surgeon["id"], ANALYST))
        resp = api_client.approve_product_request(
            req["id"], make_officer_headers("officer-2")
        )
        validate_error(resp, ApiErrorId.ERR_REQUESTER_INACTIVE)

    def test_approve_blocked_leaves_no_item(self):
        """PRD §2.7: "a failed request applies zero side effects, no matter how
        far into the pipeline it traveled."
        PRD §3.7: "Approval creates the new supply item in `ACTIVE` status with
        zero `on_hand_quantity`, built from the proposed fields"

        Design: Difficulty/cross_entity_state_dependency/approve_blocked_when_requester_deactivated
        """
        from test_helpers import validate_paginated
        surgeon = make_surgeon(full_name="Dr. Req2", specialty="CARD")
        req = setup_request_quorum_met(
            surgeon, reviewing_officer="officer-1",
            proposed_sku="VALVE-INTRO-9",
        )
        get_success_data(api_client.deactivate_surgeon(surgeon["id"], ANALYST))
        resp = api_client.approve_product_request(
            req["id"], make_officer_headers("officer-2")
        )
        validate_error(resp, ApiErrorId.ERR_REQUESTER_INACTIVE)
        after = get_success_data(api_client.get_product_request(req["id"], ANY))
        assert after["status"] == "UNDER_REVIEW"
        assert after["created_item_id"] is None
        items, meta = validate_paginated(
            api_client.list_supply_items(ANY, params={})
        )
        assert all(it["sku"] != "VALVE-INTRO-9" for it in items)


class TestRejection:
    def test_reject_terminal_request_rejected(self):
        """PRD §3.7: "Rejection, from `UNDER_REVIEW` only, stores the supplied
        `rejection_reason` and moves the request to `REJECTED`. Both `APPROVED`
        and `REJECTED` are terminal."
        PRD §3.7: "any other state draws `ERR_REQUEST_NOT_UNDER_REVIEW`"

        Design: Corner/errors/reject_terminal_request_rejected
        """
        surgeon = make_surgeon(full_name="Dr. Rej", specialty="CARD")
        req = setup_request_under_review(surgeon, reviewing_officer="officer-1")
        get_success_data(api_client.reject_product_request(
            req["id"], {"rejection_reason": "no clinical evidence"},
            make_officer_headers("officer-2"),
        ))
        resp = api_client.reject_product_request(
            req["id"], {"rejection_reason": "again"},
            make_officer_headers("officer-2"),
        )
        validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_UNDER_REVIEW)
        after = get_success_data(api_client.get_product_request(req["id"], ANY))
        assert after["rejection_reason"] == "no clinical evidence"


class TestApprovalCascade:
    def test_line_add_with_discontinued_item_rejected(self):
        """PRD §3.7: "When `replaces_item_id` was set, that item transitions
        `ACTIVE → DISCONTINUED` in the same commit, which is what blocks it
        from new card lines and future publishes (§3.1)."
        PRD §3.1: "from that moment, new card lines naming the item are
        rejected with `ERR_ITEM_NOT_ACTIVE`"

        Design: Corner/validations/line_add_with_discontinued_item_rejected
        """
        surgeon = make_surgeon(full_name="Dr. Disc")
        suture = make_supply_item(sku="SUTURE-KIT", name="Suture kit",
                                  unit_cost_cents=1000, substitute_group="SUTURE",
                                  initial_on_hand=50)
        req = setup_request_quorum_met(
            surgeon, reviewing_officer="officer-1",
            proposed_item_name="Barbed suture kit",
            proposed_sku="SUTURE-BARB",
            estimated_unit_cost_cents=1200,
            rationale="knotless closure saves time",
            replaces_item_id=suture["id"],
            substitute_group="SUTURE",
        )
        approved = validate_success(api_client.approve_product_request(
            req["id"], make_officer_headers("officer-2")
        ))
        assert approved["status"] == "APPROVED"
        item_after = get_success_data(api_client.get_supply_item(suture["id"], ANY))
        assert item_after["status"] == "DISCONTINUED"

        card = api_client.create_preference_card(
            {"surgeon_id": surgeon["id"], "procedure_name": "TKA"}, ANALYST
        )
        card_data = get_success_data(card)
        resp = api_client.create_preference_card_line(
            {"card_id": card_data["id"], "supply_item_id": suture["id"],
             "quantity": 1, "designation": "OPEN"},
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_ACTIVE)
