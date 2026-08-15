"""Validation-cascade ordering, RBAC exclusivity, subcontractor scoping and
feedback visibility, body-FK integrity, and payload-shape discipline."""
from test_helpers import (
    DRAFTER_ID,
    LEAD,
    REVIEWER,
    ApiErrorId,
    advance_clock,
    close_bidding,
    create_bid_package,
    create_bid_package_payload,
    make_lead_estimator_headers,
    make_subcontractor_headers,
    register_subcontractor,
    setup_awarded_package,
    setup_published_with_bidders,
    submit_bid,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)

GHOST_A = "00000000-0000-0000-0000-0000000000aa"
GHOST_B = "00000000-0000-0000-0000-0000000000bb"
GHOST_C = "00000000-0000-0000-0000-0000000000cc"


class TestAuthenticationContext:

    def test_missing_auth_headers_returns_400(self):
        """PRD §2.1: "Every request carries two mandatory headers: `X-User-ID`
        identifies the acting user, and `X-User-Role` names the capacity in
        which they act. The declared roles, spelled exactly as the API expects
        them, are `LeadEstimator`, `ChiefEstimator`, `PrequalReviewer`,
        `Subcontractor`, and `Anonymous`. A request missing either header, or
        naming a role outside this set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        resp = api_client.create_bid_package(
            create_bid_package_payload(name="No Auth Package"), headers=None)
        validate_error(resp,
                       ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestValidationCascadeOrdering:

    def test_role_check_precedes_existence(self):
        """PRD §2.8: "Every request passes through a fixed validation cascade,
        and the order is observable. Authentication context comes first
        (missing or malformed headers, then role authorization — priorities 1
        and 2). Existence checks come next (priority 3): resource identifiers
        in the path are validated left to right, then body-referenced foreign
        keys in input order, each miss producing the corresponding 404 — ..."
        PRD §2.1: "A request whose role is declared but not on the endpoint's
        authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/validations/role_check_precedes_existence_returns_403
        """
        sub = register_subcontractor(legal_name="RoleFirst LLC")
        # Publish is LeadEstimator-only; the id does not even exist.
        resp = api_client.publish_bid_package(
            GHOST_A, make_subcontractor_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_ownership_check_precedes_state_check(self):
        """PRD §2.8: "Ownership scoping for `Subcontractor` callers follows
        (priority 4, `ERR_FORBIDDEN_OWNERSHIP`). Then state gates (priority
        5): the target resource must be in a from-state permitted for the
        trigger, rejected with the machine-specific `ERR_PACKAGE_INVALID_STATE`,
        `ERR_INVITATION_INVALID_STATE`, `ERR_APPLICATION_INVALID_STATE`,
        `ERR_BID_INVALID_STATE`, or the generic `ERR_INVALID_RESOURCE_STATE`;
        ..."
        PRD §2.1: "Ownership checks on any resource that references a
        subcontractor — an `Invitation`, a `Bid`, an `AddendumAcknowledgment`,
        a `BidderFeedback` reached through its bid, or a `PrequalApplication`
        at create, resubmit, or read time — compare the resource's
        `subcontractor_id` foreign key against `X-User-ID`. A mismatch is
        rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

        Design: Corner/validations/ownership_check_precedes_state_check
        """
        ctx = setup_published_with_bidders(n=2, name="Ownership Package")
        pkg = ctx["package"]
        sub_a = ctx["bidders"][0]["subcontractor"]
        sub_b = ctx["bidders"][1]["subcontractor"]
        bid_b = submit_bid(pkg["id"], sub_b["id"], 1_000_000)
        # B's bid reaches a terminal state.
        api_client.withdraw_bid(bid_b["id"],
                                make_subcontractor_headers(sub_b["id"]))

        # A (not the owner) revises B's WITHDRAWN bid: ownership beats state.
        resp = api_client.create_bid_revision(
            bid_b["id"], {"new_base_bid_cents": 900_000,
                          "expected_bid_version": bid_b["version"]},
            make_subcontractor_headers(sub_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)


class TestBodyForeignKeyIntegrity:

    def test_body_fk_existence_in_input_order(self):
        """PRD §2.8: "Existence checks come next (priority 3): resource
        identifiers in the path are validated left to right, then
        body-referenced foreign keys in input order, each miss producing the
        corresponding 404 — `ERR_BID_PACKAGE_NOT_FOUND`,
        `ERR_SUBCONTRACTOR_NOT_FOUND`, `ERR_PREQUAL_APPLICATION_NOT_FOUND`,
        `ERR_INVITATION_NOT_FOUND`, `ERR_ADDENDUM_NOT_FOUND`,
        `ERR_BID_NOT_FOUND`, or the generic `ERR_RESOURCE_NOT_FOUND` for
        leveling adjustments, interviews, recommendations, feedbacks, and
        acknowledgments."

        Design: Corner/entities/fk_body_reference_integrity
        """
        sub = register_subcontractor(legal_name="FK LLC")
        pkg = create_bid_package(name="Real Package")

        resp = api_client.create_invitation(
            {"bid_package_id": GHOST_A, "subcontractor_id": sub["id"]}, LEAD)
        validate_error(resp, ApiErrorId.ERR_BID_PACKAGE_NOT_FOUND)

        resp = api_client.create_invitation(
            {"bid_package_id": pkg["id"], "subcontractor_id": GHOST_B}, LEAD)
        validate_error(resp, ApiErrorId.ERR_SUBCONTRACTOR_NOT_FOUND)

        resp = api_client.create_bid(
            {"bid_package_id": GHOST_A, "base_bid_cents": 1_000_000,
             "bond_amount_cents": 50_000},
            make_subcontractor_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_BID_PACKAGE_NOT_FOUND)

        resp = api_client.create_award_recommendation(
            {"bid_package_id": GHOST_A, "recommended_bid_id": GHOST_C,
             "rationale": "ghost",
             "expected_bid_package_version": pkg["version"]},
            make_lead_estimator_headers(DRAFTER_ID))
        validate_error(resp, ApiErrorId.ERR_BID_PACKAGE_NOT_FOUND)


class TestPayloadShapeDiscipline:

    def test_invalid_enum_readonly_and_exactly_one_of_rejected(self):
        """PRD §2.9: "Request bodies must contain exactly the fields the
        endpoint accepts. Required fields must be present; enum fields must
        carry a declared member; numeric ranges must be honored — ..."
        PRD §2.9: "On leveling adjustments, exactly one of `amount_cents` or
        `pct_of_base` must be supplied — supplying both or neither breaks the
        exactly-one-of rule."
        PRD §2.9: "Computed, system-managed, or read-only fields supplied by
        the client (for example `status`, `version`, `resolved_amount_cents`,
        `self_reported_score`, `submitted_bid_count`) are rejected. Every
        violation of this discipline is `ERR_INVALID_REQUEST` (HTTP 400),
        sequenced per §2.8."

        Design: Corner/entities/enum_and_readonly_and_exactly_one_payload_rejection
        """
        ctx = setup_published_with_bidders(n=1, name="Enum Package")
        pkg = ctx["package"]
        sub = ctx["bidders"][0]["subcontractor"]
        inv = ctx["bidders"][0]["invitation"]
        bid = submit_bid(pkg["id"], sub["id"], 1_000_000)
        advance_clock("2026-08-10T15:00:00Z")
        close_bidding(pkg["id"])

        # Invalid enum member on the invitation respond intent.
        resp = api_client.respond_invitation(
            inv["id"], {"intent": "MAYBE"},
            make_subcontractor_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        # Client smuggles a computed field.
        resp = api_client.create_leveling_adjustment(
            {"bid_id": bid["id"],
             "description": "client smuggles computed field",
             "treatment": "GC_ALLOWANCE", "amount_cents": 1_000,
             "resolved_amount_cents": 1}, LEAD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        # Both amount kinds supplied: exactly-one-of broken.
        resp = api_client.create_leveling_adjustment(
            {"bid_id": bid["id"], "description": "both amount kinds",
             "treatment": "GC_ALLOWANCE", "amount_cents": 1_000,
             "pct_of_base": 0.05}, LEAD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestRoleExclusivity:

    def test_subcontractor_cannot_create_package(self):
        """PRD §2.1: "A `Subcontractor` acts only on its own rows: responding
        to invitations, accessing the plan room, acknowledging addenda, and
        submitting, revising, or withdrawing its own bids."
        PRD §2.1: "A request whose role is declared but not on the endpoint's
        authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/subcontractor_cannot_create_package
        """
        sub = register_subcontractor(legal_name="Nope LLC")
        resp = api_client.create_bid_package(
            create_bid_package_payload(name="Sub Package"),
            make_subcontractor_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_lead_estimator_cannot_decide_recommendation(self):
        """PRD §2.1: "The `ChiefEstimator` holds award authority alone,
        deciding submitted recommendations, and — by segregation of duties —
        must never be the drafter of the recommendation being decided."
        PRD §2.1: "A request whose role is declared but not on the endpoint's
        authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/lead_estimator_cannot_decide_recommendation
        """
        # Role check precedes even the existence lookup on the path id.
        resp = api_client.decide_award_recommendation(
            GHOST_A, {"decision": "APPROVED"},
            make_lead_estimator_headers(DRAFTER_ID))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_prequal_reviewer_cannot_issue_addendum(self):
        """PRD §2.1: "The `PrequalReviewer` verifies subcontractor financials
        and decides prequalification applications."
        PRD §2.1: "A request whose role is declared but not on the endpoint's
        authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/prequal_reviewer_cannot_issue_addendum
        """
        resp = api_client.create_addendum(
            {"bid_package_id": GHOST_A, "summary": "reviewer attempt"},
            REVIEWER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestSubcontractorScopingAndFeedbackVisibility:

    def test_list_scoping_and_draft_feedback_hidden_until_sent(self):
        """PRD §2.1: "All estimator-side roles (`LeadEstimator`,
        `ChiefEstimator`, `PrequalReviewer`) may set the logical clock and read
        any resource; a `Subcontractor` reading list endpoints sees only its
        own rows."
        PRD §3.10: "Visibility is deliberately asymmetric: estimator roles see
        all feedback rows, while a `Subcontractor` sees only `SENT` rows on its
        own bids — a `DRAFT` feedback is never visible to a subcontractor, and
        a subcontractor touching another firm's feedback through its bid's
        `subcontractor_id` is `ERR_FORBIDDEN_OWNERSHIP`."

        Design: Corner/rbac/subcontractor_scoping_and_feedback_visibility
        """
        ctx = setup_awarded_package((1_000_000, 900_000), recommend_index=1,
                                    name="Scope Package")
        bid_x = ctx["bids"][0]  # loser (feedback DRAFT auto-created)
        bid_y = ctx["bids"][1]  # winner, leveled 900_000
        sub_x = ctx["bidders"][0]["subcontractor"]
        headers_x = make_subcontractor_headers(sub_x["id"])

        rows, meta = validate_paginated(api_client.list_bids(headers_x))
        assert len(rows) == 1 and rows[0]["id"] == bid_x["id"], \
            "a subcontractor's bid list contains only its own rows"

        rows, _ = validate_paginated(
            api_client.list_bidder_feedbacks(bid_x["id"], headers_x))
        assert rows == [], "DRAFT feedback is never visible to the subcontractor"

        staff_rows, _ = validate_paginated(
            api_client.list_bidder_feedbacks(bid_x["id"], LEAD))
        assert len(staff_rows) == 1 and staff_rows[0]["status"] == "DRAFT"

        fb_id = staff_rows[0]["id"]
        resp = api_client.send_bidder_feedback(
            fb_id, {"notes": "Appreciate the bid; winner came in 100000 lower "
                             "leveled"}, LEAD)
        assert validate_success(resp)["status"] == "SENT"

        rows, _ = validate_paginated(
            api_client.list_bidder_feedbacks(bid_x["id"], headers_x))
        assert len(rows) == 1
        assert rows[0]["status"] == "SENT"
        assert rows[0]["notes"].startswith("Appreciate the bid")
        assert rows[0]["winning_leveled_amount_cents"] == 900_000
