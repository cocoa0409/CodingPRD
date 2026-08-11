"""Validation pipeline ordering, specification version pinning, OCC guards, and
role/scope authorization (PRD §2.1, §2.7, §2.8, §2.9, §3.3, §3.4)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, TWO_TIER_TABLE, make_district_buyer_headers,
    validate_error, validate_success, add_po_line, add_spec_line,
    build_accepted_award_context, cancel_po, close_spec, create_district,
    create_po, create_spec, get_po_line, issue_addendum, publish_spec, set_clock,
)

ADMIN = TEST_USERS["admin_headers"]
CM = TEST_USERS["contract_manager_headers"]
FC = TEST_USERS["fulfillment_coordinator_headers"]


class TestValidationPriorityPairs:
    def test_po_accept_state_error_beats_fiscal_cap_error(self, api):
        """PRD §2.8: "Every request is evaluated against a fixed validation
        pipeline; earlier stages mask later ones, so the error a client receives is
        always from the earliest failing stage." (state guards are stage 6; the
        district fiscal cap is stage 15)

        Design: Difficulty/priority_pair_validation_conflict/po_accept_state_error_beats_fiscal_cap_error
        """
        ctx = build_accepted_award_context(annual_cap_cents=200000,
                                           with_site=False, with_crew=False)
        d_id = ctx["district"]["id"]
        po = create_po(ctx["award"]["id"], d_id, po_number="PO-1")
        add_po_line(po["id"], ctx["spec_line"]["id"], d_id, 20)  # total 220000 > cap
        cancel_po(po["id"], d_id)  # CANCELLED while RECEIVED

        resp = api.accept_purchase_order(po["id"], FC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_fiscal_cap_error_fires_when_state_valid(self, api):
        """PRD §3.4: "the sum of `total_cents` across the district's orders in
        `ACCEPTED`, `IN_FULFILLMENT`, `FULFILLED`, or `CLOSED` status within the
        same `fiscal_year`, plus this order's `total_cents`, must not exceed the
        district's `annual_cap_cents`; breach is rejected with
        `ERR_DISTRICT_FISCAL_CAP_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/po_accept_state_error_beats_fiscal_cap_error
        """
        ctx = build_accepted_award_context(annual_cap_cents=200000,
                                           with_site=False, with_crew=False)
        d_id = ctx["district"]["id"]
        po = create_po(ctx["award"]["id"], d_id, po_number="PO-1")
        add_po_line(po["id"], ctx["spec_line"]["id"], d_id, 20)  # total 220000 > cap

        resp = api.accept_purchase_order(po["id"], FC)
        validate_error(resp, ApiErrorId.ERR_DISTRICT_FISCAL_CAP_EXCEEDED)

    def test_poline_create_temporal_error_beats_spec_version_error(self, api):
        """PRD §2.8: "earlier stages mask later ones, so the error a client receives
        is always from the earliest failing stage." (temporal windows are stage 8;
        the specification version pin is stage 9)
        PRD §3.4: "the creation date must fall on or before the award's
        `order_by_date` (`ERR_ORDER_WINDOW_CLOSED`)"

        Design: Difficulty/priority_pair_validation_conflict/poline_create_temporal_error_beats_spec_version_error
        """
        ctx = build_accepted_award_context(pricing_mode="COOP_TIERED",
                                           tier_table=TWO_TIER_TABLE,
                                           with_site=False, with_crew=False)
        d_id = ctx["district"]["id"]
        assert ctx["award"]["awarded_spec_version"] == 1
        # Post-award addendum cycle: spec_version advances to 2, pin now stale.
        issue_addendum(ctx["spec"]["id"], d_id, note="post-award clarification")
        republished = publish_spec(ctx["spec"]["id"], d_id)
        assert republished["spec_version"] == 2
        set_clock("2026-06-02T09:00:00Z")  # past order_by_date 2026-06-01
        po = create_po(ctx["award"]["id"], d_id, po_number="PO-1")

        resp = api.create_po_line(
            {"purchase_order_id": po["id"], "spec_line_id": ctx["spec_line"]["id"],
             "ordered_qty": 5},
            make_district_buyer_headers(d_id))
        validate_error(resp, ApiErrorId.ERR_ORDER_WINDOW_CLOSED)

    def test_spec_version_stale_fires_when_temporal_ok(self, api):
        """PRD §2.9: "if the specification's `spec_version` no longer equals the
        award's `awarded_spec_version` (because an addendum was issued and
        re-published without a corresponding award amendment), line creation is
        rejected with `ERR_SPEC_VERSION_STALE`."

        Design: Difficulty/priority_pair_validation_conflict/poline_create_temporal_error_beats_spec_version_error
        """
        ctx = build_accepted_award_context(pricing_mode="COOP_TIERED",
                                           tier_table=TWO_TIER_TABLE,
                                           with_site=False, with_crew=False,
                                           clock="2026-05-10T00:00:00Z")
        d_id = ctx["district"]["id"]
        issue_addendum(ctx["spec"]["id"], d_id, note="post-award clarification")
        publish_spec(ctx["spec"]["id"], d_id)
        po = create_po(ctx["award"]["id"], d_id, po_number="PO-1")

        resp = api.create_po_line(
            {"purchase_order_id": po["id"], "spec_line_id": ctx["spec_line"]["id"],
             "ordered_qty": 5},
            make_district_buyer_headers(d_id))
        validate_error(resp, ApiErrorId.ERR_SPEC_VERSION_STALE)


class TestVersionPinningAndOCC:
    def test_version_pinning_stale_spec_blocks_line_until_amendment_repins(self, api):
        """PRD §2.9: "if the specification's `spec_version` no longer equals the
        award's `awarded_spec_version` (because an addendum was issued and
        re-published without a corresponding award amendment), line creation is
        rejected with `ERR_SPEC_VERSION_STALE`."
        PRD §3.3: "A successful amendment re-pins `awarded_spec_version` to the
        specification's current `spec_version` and increments the award's `version`
        by one, re-enabling line ordering under the new content."

        Design: Corner/cross_cutting_layers/version_pinning_stale_spec_blocks_line_until_amendment_repins
        """
        ctx = build_accepted_award_context(pricing_mode="COOP_TIERED",
                                           tier_table=TWO_TIER_TABLE,
                                           with_site=False, with_crew=False,
                                           clock="2026-05-10T00:00:00Z")
        d_id = ctx["district"]["id"]
        issue_addendum(ctx["spec"]["id"], d_id, note="post-award clarification")
        republished = publish_spec(ctx["spec"]["id"], d_id)
        assert republished["spec_version"] == 2
        po = create_po(ctx["award"]["id"], d_id, po_number="PO-1")

        blocked = api.create_po_line(
            {"purchase_order_id": po["id"], "spec_line_id": ctx["spec_line"]["id"],
             "ordered_qty": 5},
            make_district_buyer_headers(d_id))
        validate_error(blocked, ApiErrorId.ERR_SPEC_VERSION_STALE)

        amended = validate_success(api.issue_amendment(
            ctx["award"]["id"],
            {"expected_award_version": ctx["award"]["version"],
             "amendment_note": "ratify addendum 1"},
            make_district_buyer_headers(d_id)))
        assert amended["awarded_spec_version"] == 2

        line = validate_success(api.create_po_line(
            {"purchase_order_id": po["id"], "spec_line_id": ctx["spec_line"]["id"],
             "ordered_qty": 5},
            make_district_buyer_headers(d_id)), 201)
        assert line["status"] == "PENDING"

    def test_occ_stale_version_on_award_amendment_returns_412(self, api):
        """PRD §2.7: "An award amendment request must carry
        `expected_award_version` holding the value of the target award's `version`
        the client last observed. If the award's current `version` has advanced
        since then — because another amendment was legitimately applied in the
        meantime — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and
        no re-pinning occurs."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_award_amendment_returns_412
        """
        ctx = build_accepted_award_context(pricing_mode="COOP_TIERED",
                                           tier_table=[{"min_qty": 1, "unit_price_cents": 12000}],
                                           with_site=False, with_crew=False,
                                           clock="2026-05-10T00:00:00Z")
        d_id = ctx["district"]["id"]
        issue_addendum(ctx["spec"]["id"], d_id)
        publish_spec(ctx["spec"]["id"], d_id)
        observed_version = ctx["award"]["version"]

        first = validate_success(api.issue_amendment(
            ctx["award"]["id"],
            {"expected_award_version": observed_version,
             "amendment_note": "ratify addendum 1"},
            make_district_buyer_headers(d_id)))
        assert first["awarded_spec_version"] == 2
        assert first["version"] == observed_version + 1

        replay = api.issue_amendment(
            ctx["award"]["id"],
            {"expected_award_version": observed_version,
             "amendment_note": "stale replay"},
            make_district_buyer_headers(d_id))
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)


class TestAuthAndScope:
    def test_missing_auth_headers_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role the
        system does not declare, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        resp = api._request(
            "POST", "/v1/districts",
            {"name": "District D1", "annual_cap_cents": 1000},
            headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_forbidden_role_districtbuyer_cannot_create_crew(self, api):
        """PRD §2.1: "Each endpoint admits a defined set of roles; a well-formed
        request whose role is not on that endpoint's list is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §2.1: "a `ContractorAdmin` administers the platform itself (registering
        districts and crews, driving the logical clock)"

        Design: Corner/validations/forbidden_role_districtbuyer_cannot_create_crew
        """
        district = create_district()
        resp = api.create_crew({"name": "Crew Rogue"},
                               make_district_buyer_headers(district["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_districtbuyer_cannot_publish_other_districts_spec(self, api):
        """PRD §2.1: "ownership checks on any resource whose district chain
        resolves to a district — a school site, a bid specification, an award, a
        purchase order, a PO line, a warranty claim or appeal — compare that
        resource's district foreign key to `X-User-ID`, and a mismatch is rejected
        with `ERR_SCOPE_VIOLATION` (HTTP 403)."

        Design: Corner/validations/districtbuyer_cannot_publish_other_districts_spec
        """
        set_clock()
        d1 = create_district(name="District D1")
        d2 = create_district(name="District D2")
        spec2 = create_spec(d2["id"], title="Spec of D2")
        add_spec_line(spec2["id"], d2["id"])

        resp = api.publish_bid_spec(spec2["id"], make_district_buyer_headers(d1["id"]))
        validate_error(resp, ApiErrorId.ERR_SCOPE_VIOLATION)
