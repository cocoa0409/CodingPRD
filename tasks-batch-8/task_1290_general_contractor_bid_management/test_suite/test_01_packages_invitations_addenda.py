"""Bid-package stand-up, defaults and pagination, the invitation lifecycle,
addendum issuance cascades, and the acknowledgment ledger."""
import pytest

from test_helpers import (
    ANON,
    LEAD,
    ApiErrorId,
    acknowledge_addendum,
    advance_clock,
    assert_addendum,
    assert_addendum_acknowledgment,
    assert_bid_package,
    assert_invitation,
    assert_timestamp_equals,
    close_bidding,
    create_bid_package,
    create_bid_package_payload,
    create_subcontractor_payload,
    get_bid,
    get_package,
    invite,
    issue_addendum,
    make_subcontractor_headers,
    publish_package,
    register_subcontractor,
    respond_bidding,
    respond_invitation,
    setup_bidder,
    submit_bid,
    submit_prequal_application,
    approve_application,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)

GHOST_A = "00000000-0000-0000-0000-0000000000aa"
GHOST_B = "00000000-0000-0000-0000-0000000000bb"


class TestBidPackageCreationDefaultsAndPagination:

    def test_bid_package_defaults_and_explicit_bond_pct(self):
        """PRD §3.1: "A bid event begins when a `LeadEstimator` creates a
        **bid package** with a `name` (a working title such as "Structural
        Steel — Tower A"), a `trade_code` label, the `bid_due_at` deadline,
        and optionally the `bid_bond_required_pct` — the fraction of the base
        bid that the submitted bond must cover, defaulting to 0.05 when omitted
        and always constrained to greater than 0 and at most 0.20."
        PRD §3.1: "The package is born in `DRAFT` status with
        `issued_addendum_count` and `submitted_bid_count` both at 0 and
        `compliant_bid_count`, `apparent_low_bid_id`, and `leveled_low_bid_id`
        all null until the first tabulation."

        Design: Corner/entities/bid_package_creation_defaults_and_pagination
        """
        resp = api_client.create_bid_package(
            create_bid_package_payload(name="Pkg One"), LEAD)
        pkg1 = validate_success(resp, expected_status=201)
        assert_bid_package(pkg1)
        assert pkg1["bid_bond_required_pct"] == pytest.approx(0.05), \
            "omitted bid_bond_required_pct must default to 0.05"
        assert pkg1["status"] == "DRAFT"
        assert pkg1["issued_addendum_count"] == 0
        assert pkg1["submitted_bid_count"] == 0

        resp = api_client.create_bid_package(
            create_bid_package_payload(name="Pkg Two",
                                       bid_due_at="2026-08-12T14:00:00Z",
                                       bid_bond_required_pct=0.10), LEAD)
        pkg2 = validate_success(resp, expected_status=201)
        assert pkg2["bid_bond_required_pct"] == pytest.approx(0.10), \
            "explicit bid_bond_required_pct must be honored"

        resp = api_client.list_bid_packages(LEAD, params={"limit": 1,
                                                          "offset": 0})
        rows, meta = validate_paginated(resp)
        assert len(rows) == 1, f"limit=1 must cap the page, got {len(rows)}"
        assert meta["total_count"] == 2
        assert meta["has_more"] is True, "1 of 2 rows returned: has_more true"


class TestResourceNotFoundFamily:

    def test_single_resource_gets_with_ghost_ids_return_domain_404s(self):
        """PRD §2.8: "Existence checks come next (priority 3): resource
        identifiers in the path are validated left to right, then
        body-referenced foreign keys in input order, each miss producing the
        corresponding 404 — `ERR_BID_PACKAGE_NOT_FOUND`,
        `ERR_SUBCONTRACTOR_NOT_FOUND`, `ERR_PREQUAL_APPLICATION_NOT_FOUND`,
        `ERR_INVITATION_NOT_FOUND`, `ERR_ADDENDUM_NOT_FOUND`,
        `ERR_BID_NOT_FOUND`, or the generic `ERR_RESOURCE_NOT_FOUND` for
        leveling adjustments, interviews, recommendations, feedbacks, and
        acknowledgments."

        Design: Corner/entities/resource_not_found_family_returns_404
        """
        cases = [
            (api_client.get_bid_package(GHOST_A, LEAD),
             ApiErrorId.ERR_BID_PACKAGE_NOT_FOUND),
            (api_client.get_subcontractor(GHOST_A, LEAD),
             ApiErrorId.ERR_SUBCONTRACTOR_NOT_FOUND),
            (api_client.get_prequal_application(GHOST_A, LEAD),
             ApiErrorId.ERR_PREQUAL_APPLICATION_NOT_FOUND),
            (api_client.get_invitation(GHOST_A, LEAD),
             ApiErrorId.ERR_INVITATION_NOT_FOUND),
            (api_client.get_addendum(GHOST_A, LEAD),
             ApiErrorId.ERR_ADDENDUM_NOT_FOUND),
            (api_client.get_bid(GHOST_A, LEAD), ApiErrorId.ERR_BID_NOT_FOUND),
            (api_client.get_award_recommendation(GHOST_A, LEAD),
             ApiErrorId.ERR_RESOURCE_NOT_FOUND),
        ]
        for resp, err_id in cases:
            validate_error(resp, err_id)


class TestSubcontractorRegistration:

    def test_missing_license_and_duplicate_license_rejected(self):
        """PRD §2.9: "Request bodies must contain exactly the fields the
        endpoint accepts. Required fields must be present; ... Every violation
        of this discipline is `ERR_INVALID_REQUEST` (HTTP 400), sequenced per
        §2.8."
        PRD §3.2: "The license number is unique across all subcontractors; a
        registration that reuses one is rejected with
        `ERR_DUPLICATE_LICENSE_NUMBER` (HTTP 409)."

        Design: Corner/entities/subcontractor_required_fields_and_duplicate_license
        """
        register_subcontractor(legal_name="First LLC",
                               license_number="LIC-D-001")

        resp = api_client.create_subcontractor(
            {"legal_name": "No License LLC", "contact_email": "nl@x.com"}, ANON)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        resp = api_client.create_subcontractor(
            create_subcontractor_payload(legal_name="Copycat LLC",
                                         contact_email="cc@x.com",
                                         license_number="LIC-D-001"), ANON)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LICENSE_NUMBER)


class TestPublishRequiresInvitationExistence:

    def test_publish_with_zero_invitations_rejected(self):
        """PRD §3.1: "Two preconditions guard the publish, and the
        existence/state ordering of §2.8 applies: at least one invitation must
        exist for the package (otherwise `ERR_NO_INVITED_BIDDERS`, HTTP 422),
        and the logical now must be strictly before `bid_due_at` (otherwise
        `ERR_BID_DEADLINE_PASSED`)."

        Design: Difficulty/cross_entity_state_dependency/publish_requires_invitation_existence
        """
        pkg = create_bid_package(name="Empty Invite Package")
        resp = api_client.publish_bid_package(pkg["id"], LEAD)
        validate_error(resp, ApiErrorId.ERR_NO_INVITED_BIDDERS)
        after = get_package(pkg["id"])
        assert after["status"] == "DRAFT", \
            f"rejected publish must leave the package DRAFT, got {after['status']}"

    def test_publish_succeeds_once_invitation_exists(self):
        """PRD §3.1: "A `LeadEstimator` publishes the package, moving it `DRAFT
        → PUBLISHED`, which makes invitations live and opens the plan room."
        PRD §3.1: "Two preconditions guard the publish, and the
        existence/state ordering of §2.8 applies: at least one invitation must
        exist for the package (otherwise `ERR_NO_INVITED_BIDDERS`, HTTP 422),
        and the logical now must be strictly before `bid_due_at` (otherwise
        `ERR_BID_DEADLINE_PASSED`)."

        Design: Difficulty/cross_entity_state_dependency/publish_requires_invitation_existence
        """
        pkg = create_bid_package(name="Invited Package")
        sub = register_subcontractor(legal_name="Invitee LLC")
        invite(pkg["id"], sub["id"])
        resp = api_client.publish_bid_package(pkg["id"], LEAD)
        published = validate_success(resp, expected_status=200)
        assert_bid_package(published)
        assert published["status"] == "PUBLISHED"


class TestInvitationLifecycle:

    def test_invitation_starts_sent_and_repeat_bidding_rejected(self):
        """PRD §3.1: "Each invitation starts in `SENT` status."
        PRD §3.3: "Every response stamps `responded_at` with the logical now."
        PRD §3.3: "An `intent` that matches no permitted transition from the
        invitation's current status is rejected with
        `ERR_INVITATION_INVALID_STATE`."

        Design: Corner/state_machines/invitation_initial_state_and_repeat_bidding_rejected
        """
        pkg = create_bid_package(name="Invite Package")
        sub = register_subcontractor(legal_name="Invited LLC")
        inv = invite(pkg["id"], sub["id"])
        assert inv["status"] == "SENT", "invitations are born SENT"

        resp = api_client.respond_invitation(
            inv["id"], {"intent": "BIDDING"}, make_subcontractor_headers(sub["id"]))
        bidding = validate_success(resp, expected_status=200)
        assert_invitation(bidding)
        assert bidding["status"] == "BIDDING"
        assert bidding.get("responded_at"), "responded_at must be stamped"

        resp = api_client.respond_invitation(
            inv["id"], {"intent": "BIDDING"}, make_subcontractor_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_INVITATION_INVALID_STATE)

    def test_reconsider_after_close_rejected(self):
        """PRD §3.3: "The transitions are `SENT → BIDDING`, `SENT → DECLINED`,
        `BIDDING → DECLINED`, and — the reconsider path — `DECLINED → BIDDING`,
        which is permitted only while the package remains `PUBLISHED`
        (otherwise `ERR_PACKAGE_NOT_ACCEPTING_BIDS`, HTTP 409)."

        Design: Corner/state_machines/invitation_reconsider_when_closed_returns_409
        """
        pkg = create_bid_package(name="Closed Package")
        sub = register_subcontractor(legal_name="Late LLC")
        inv = invite(pkg["id"], sub["id"])
        respond_invitation(inv["id"], sub["id"], "DECLINED")
        publish_package(pkg["id"])
        advance_clock("2026-08-10T15:00:00Z")
        close_bidding(pkg["id"])

        resp = api_client.respond_invitation(
            inv["id"], {"intent": "BIDDING"}, make_subcontractor_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_PACKAGE_NOT_ACCEPTING_BIDS)
        current = api_client.get_invitation(inv["id"], LEAD)
        assert validate_success(current)["status"] == "DECLINED"


class TestPlanRoomTelemetry:

    def test_plan_room_access_tracking_and_declined_block(self):
        """PRD §3.3: "Each successful plan-room access by the invited
        subcontractor sets `first_plan_room_access_at` exactly once (the first
        time only) and increments `plan_room_access_count` by 1."
        PRD §3.3: "Access requires the package to be `PUBLISHED` (otherwise
        `ERR_PACKAGE_NOT_ACCEPTING_BIDS`) and the invitation to be in `SENT` or
        `BIDDING`; accessing on a `DECLINED` invitation is rejected with
        `ERR_INVITATION_DECLINED` (HTTP 409)."

        Design: Corner/endpoints/plan_room_access_tracking_and_declined_block
        """
        pkg = create_bid_package(name="Room Package")
        sub = register_subcontractor(legal_name="Room LLC")
        inv = invite(pkg["id"], sub["id"])
        headers = make_subcontractor_headers(sub["id"])

        # While the package is still DRAFT the plan room is closed.
        resp = api_client.plan_room_access(inv["id"], headers)
        validate_error(resp, ApiErrorId.ERR_PACKAGE_NOT_ACCEPTING_BIDS)

        publish_package(pkg["id"])
        resp = api_client.plan_room_access(inv["id"], headers)
        first = validate_success(resp, expected_status=200)
        assert first["plan_room_access_count"] == 1
        assert first.get("first_plan_room_access_at"), \
            "first access must stamp first_plan_room_access_at"

        resp = api_client.plan_room_access(inv["id"], headers)
        second = validate_success(resp, expected_status=200)
        assert second["plan_room_access_count"] == 2
        assert_timestamp_equals(second["first_plan_room_access_at"],
                                first["first_plan_room_access_at"])

        respond_invitation(inv["id"], sub["id"], "DECLINED")
        resp = api_client.plan_room_access(inv["id"], headers)
        validate_error(resp, ApiErrorId.ERR_INVITATION_DECLINED)
        current = validate_success(api_client.get_invitation(inv["id"], LEAD))
        assert current["plan_room_access_count"] == 2, \
            "a blocked access must not increment the counter"


class TestAddendumIssuance:

    def test_addendum_sequential_numbering_per_package(self):
        """PRD §3.5: "The addendum's `number` is assigned per package as one
        more than the highest existing number for that package, starting at 1;
        `issued_at` is stamped at creation and the row is immutable afterward."
        PRD §3.5: "Issuance cascades immediately: for every invitation on
        the package in `SENT` or `BIDDING` status, a `PENDING` **addendum
        acknowledgment** is created; each affected subcontractor's `SUBMITTED`
        bids on the package have `addendum_ack_complete` recomputed (to false,
        since a `PENDING` row now exists); and the package's
        `issued_addendum_count` increments by 1."

        Design: Corner/endpoints/addendum_sequential_numbering
        """
        sub = register_subcontractor(legal_name="Seq LLC")
        pkg1 = create_bid_package(name="Seq P1")
        pkg2 = create_bid_package(name="Seq P2", trade_code="033000",
                                  bid_due_at="2026-08-11T14:00:00Z")
        invite(pkg1["id"], sub["id"])
        invite(pkg2["id"], sub["id"])
        publish_package(pkg1["id"])
        publish_package(pkg2["id"])

        a1 = issue_addendum(pkg1["id"], "P1 Addendum 1")
        a2 = issue_addendum(pkg1["id"], "P1 Addendum 2")
        a3 = issue_addendum(pkg2["id"], "P2 Addendum 1")
        for row in (a1, a2, a3):
            assert_addendum(row)
        assert a1["number"] == 1 and a2["number"] == 2, \
            "addenda on one package number 1, 2, ... in issue order"
        assert a3["number"] == 1, "a different package starts its own sequence"
        assert get_package(pkg1["id"])["issued_addendum_count"] == 2
        assert get_package(pkg2["id"])["issued_addendum_count"] == 1

    def test_addendum_issue_creates_pending_acks_excluding_declined(self):
        """PRD §3.5: "Issuance cascades immediately: for every invitation on
        the package in `SENT` or `BIDDING` status, a `PENDING` **addendum
        acknowledgment** is created; each affected subcontractor's `SUBMITTED`
        bids on the package have `addendum_ack_complete` recomputed (to false,
        since a `PENDING` row now exists); and the package's
        `issued_addendum_count` increments by 1."

        Design: Difficulty/transitive_cascade/addendum_issue_two_level_cascade
        """
        pkg = create_bid_package(name="Addendum Package")
        sub_x = register_subcontractor(legal_name="X Add LLC")
        sub_y = register_subcontractor(legal_name="Y Add LLC")
        sub_z = register_subcontractor(legal_name="Z Add LLC")
        inv_x = invite(pkg["id"], sub_x["id"])
        inv_y = invite(pkg["id"], sub_y["id"])
        inv_z = invite(pkg["id"], sub_z["id"])
        respond_bidding(inv_x["id"], sub_x["id"])
        inv_z = respond_invitation(inv_z["id"], sub_z["id"], "DECLINED")
        publish_package(pkg["id"])
        # X needs an approved prequalification to hold a SUBMITTED bid.
        app_x = submit_prequal_application(sub_x["id"])
        approve_application(app_x["id"])
        bid_x = submit_bid(pkg["id"], sub_x["id"], 1_000_000)

        add1 = issue_addendum(pkg["id"], "Addendum 1: revised anchor bolt plan")

        assert add1["number"] == 1
        assert get_package(pkg["id"])["issued_addendum_count"] == 1
        resp = api_client.list_addendum_acknowledgments(add1["id"], LEAD)
        rows, meta = validate_paginated(resp)
        assert len(rows) == 2, \
            f"one PENDING ack per SENT/BIDDING invitee (X and Y), got {len(rows)}"
        assert all(r["status"] == "PENDING" for r in rows)
        owed = {r["subcontractor_id"] for r in rows}
        assert owed == {sub_x["id"], sub_y["id"]}, \
            f"DECLINED invitee must receive no acknowledgment, got {owed}"
        assert inv_y["status"] == "SENT"  # fixture sanity: Y never responded
        assert inv_z["status"] == "DECLINED"
        # X's SUBMITTED bid picked up the flag recompute as the cascade's
        # second link; the dedicated companion test asserts it from scratch.
        assert bid_x["status"] == "SUBMITTED"

    def test_addendum_issue_recomputes_bid_ack_flag(self):
        """PRD §3.5: "Issuance cascades immediately: for every invitation on
        the package in `SENT` or `BIDDING` status, a `PENDING` **addendum
        acknowledgment** is created; each affected subcontractor's `SUBMITTED`
        bids on the package have `addendum_ack_complete` recomputed (to false,
        since a `PENDING` row now exists); and the package's
        `issued_addendum_count` increments by 1."
        PRD §3.5: "The `addendum_ack_complete` flag on a bid is defined
        precisely: it is true if and only if no `PENDING` acknowledgment exists
        for the pairing of that bid's package and that bid's subcontractor."

        Design: Difficulty/transitive_cascade/addendum_issue_two_level_cascade
        """
        pkg = create_bid_package(name="Addendum Flag Package")
        ctx = setup_bidder(pkg["id"])
        sub_x = ctx["subcontractor"]
        publish_package(pkg["id"])
        bid_x = submit_bid(pkg["id"], sub_x["id"], 1_000_000)
        assert get_bid(bid_x["id"])["addendum_ack_complete"] is True, \
            "before any addendum the ack flag is true"

        issue_addendum(pkg["id"], "Addendum 1")
        bid_after = get_bid(bid_x["id"])
        assert bid_after["addendum_ack_complete"] is False, \
            "a new PENDING acknowledgment must flip the bid's flag to false"


class TestAcknowledgmentLedger:

    def test_decline_waives_acks_and_reconsider_recreates(self):
        """PRD §3.3: "Declining has a cleanup cascade: when an invitation moves
        from `BIDDING` to `DECLINED`, every still-`PENDING` addendum
        acknowledgment owed by that subcontractor on the package's addenda is
        moved to `WAIVED` with its `waived_reason` recorded as \"bidder
        declined\", and `addendum_ack_complete` is recomputed on the affected
        `SUBMITTED` bids."
        PRD §3.3: "Reconsidering has the mirror cascade: when an invitation
        moves from `DECLINED` back to `BIDDING`, the system creates a fresh
        `PENDING` acknowledgment for each addendum of the package that lacks
        one in `PENDING` or `ACKNOWLEDGED` for this subcontractor — earlier
        `WAIVED` rows are retained as audit history, not resurrected."

        Design: Corner/state_machines/invitation_decline_waives_acks_reconsider_recreates
        """
        pkg = create_bid_package(name="Waffle Package")
        sub = register_subcontractor(legal_name="Waffle LLC")
        inv = invite(pkg["id"], sub["id"])
        respond_bidding(inv["id"], sub["id"])
        publish_package(pkg["id"])
        add1 = issue_addendum(pkg["id"], "Addendum 1")

        respond_invitation(inv["id"], sub["id"], "DECLINED")
        rows, _ = validate_paginated(
            api_client.list_addendum_acknowledgments(add1["id"], LEAD))
        assert len(rows) == 1
        assert_addendum_acknowledgment(rows[0])
        assert rows[0]["status"] == "WAIVED"
        assert rows[0]["waived_reason"] == "bidder declined"

        resp = api_client.respond_invitation(
            inv["id"], {"intent": "BIDDING"}, make_subcontractor_headers(sub["id"]))
        assert validate_success(resp)["status"] == "BIDDING"
        rows, _ = validate_paginated(
            api_client.list_addendum_acknowledgments(add1["id"], LEAD))
        assert len(rows) == 2, \
            "the WAIVED audit row is retained and a fresh PENDING row created"
        by_status = sorted(r["status"] for r in rows)
        assert by_status == ["PENDING", "WAIVED"]

    def test_acknowledge_twice_and_ghost_addendum_return_404(self):
        """PRD §3.5: "A `Subcontractor` acknowledges an addendum, resolving its
        own `PENDING` row to `ACKNOWLEDGED` and stamping `acknowledged_at`; the
        precondition is that a `PENDING` acknowledgment actually exists for the
        pair of that addendum and the caller's subcontractor id — never issued,
        already resolved, or belonging to another firm all surface as
        `ERR_ACKNOWLEDGMENT_NOT_FOUND` (HTTP 404) — and that the package is in
        `PUBLISHED` or `BIDDING_CLOSED` (otherwise `ERR_PACKAGE_INVALID_STATE`)."
        PRD §2.8: "Existence checks come next (priority 3): resource
        identifiers in the path are validated left to right, then
        body-referenced foreign keys in input order, each miss producing the
        corresponding 404 — `ERR_BID_PACKAGE_NOT_FOUND`, ... `ERR_ADDENDUM_NOT_FOUND`,
        ..."

        Design: Corner/state_machines/acknowledge_twice_returns_404
        """
        pkg = create_bid_package(name="Ack Package")
        sub = register_subcontractor(legal_name="Ack LLC")
        inv = invite(pkg["id"], sub["id"])
        respond_bidding(inv["id"], sub["id"])
        publish_package(pkg["id"])
        add1 = issue_addendum(pkg["id"], "Addendum 1")

        resp = api_client.acknowledge_addendum(
            add1["id"], make_subcontractor_headers(sub["id"]))
        acked = validate_success(resp, expected_status=200)
        assert_addendum_acknowledgment(acked)
        assert acked["status"] == "ACKNOWLEDGED"
        assert acked.get("acknowledged_at"), "acknowledged_at must be stamped"

        resp = api_client.acknowledge_addendum(
            add1["id"], make_subcontractor_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_ACKNOWLEDGMENT_NOT_FOUND)

        resp = api_client.acknowledge_addendum(
            GHOST_A, make_subcontractor_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_ADDENDUM_NOT_FOUND)


class TestLevelingSheetComplianceFields:

    def test_leveling_sheet_reflects_live_acknowledgment_state(self):
        """PRD §3.7: "The leveling sheet for a bid is a computed read returning
        the bid's `bid_id`, its `base_bid_cents`, the adjustment list with
        resolved amounts, the `leveled_amount_cents` total, a `has_exclusions`
        flag that is true when any adjustment on the bid carries the
        `EXCLUDED_SCOPE` treatment, a `pending_addendum_ack_count` of
        outstanding `PENDING` acknowledgments for this bidder on this package,
        and an `is_compliant` summary flag."
        PRD §3.5: "The `addendum_ack_complete` flag on a bid is defined
        precisely: it is true if and only if no `PENDING` acknowledgment exists
        for the pairing of that bid's package and that bid's subcontractor."

        Design: Corner/endpoints/leveling_sheet_compliance_fields
        """
        pkg = create_bid_package(name="Sheet Package")
        ctx = setup_bidder(pkg["id"])
        sub = ctx["subcontractor"]
        publish_package(pkg["id"])
        bid = submit_bid(pkg["id"], sub["id"], 1_000_000)
        add1 = issue_addendum(pkg["id"], "Addendum 1")

        before = validate_success(api_client.get_leveling_sheet(bid["id"], LEAD),
                                  expected_status=200)
        assert before["pending_addendum_ack_count"] == 1
        assert before["is_compliant"] is False
        assert get_bid(bid["id"])["addendum_ack_complete"] is False

        acknowledge_addendum(add1["id"], sub["id"])

        after = validate_success(api_client.get_leveling_sheet(bid["id"], LEAD),
                                 expected_status=200)
        assert after["pending_addendum_ack_count"] == 0
        assert after["is_compliant"] is True
        assert get_bid(bid["id"])["addendum_ack_complete"] is True
        assert after["leveled_amount_cents"] == 1_000_000
        assert after["has_exclusions"] is False
