"""Authentication context, role authorization, ownership, and optimistic
concurrency control (PRD §2.1, §2.7, §2.8, §2.9, §3.5)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    create_member_payload, create_referral_payload, create_claim_payload,
    make_member_headers,
    create_member, create_active_member, create_accepted_referral,
    create_draft_prescription, create_menu_item, create_planned_cycle,
    get_reauthorization, get_delivery,
    setup_member_with_active_prescription, setup_delivered_delivery,
    setup_submitted_claim,
)


class TestAuthenticationContext:
    def test_request_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity
        in which they act. A request in which either header is missing or empty
        is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP
        400)."

        Design: Corner/validations/request_missing_auth_headers_unauthenticated
        """
        resp = api.create_member(create_member_payload(
            full_name="V One", payer_member_id="W-V1"), headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestBodyReferenceValidation:
    def test_referral_create_with_unknown_member_returns_member_not_found(
            self, api, referring_provider_headers):
        """PRD §2.9: "request bodies that reference other resources by foreign
        key are checked for existence with resource-specific 404 errors:
        `member_id` (`ERR_MEMBER_NOT_FOUND`)"

        Design: Corner/validations/referral_create_with_unknown_member_returns_member_not_found
        """
        resp = api.create_referral(
            create_referral_payload(NON_EXISTENT_UUID),
            referring_provider_headers)
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND)


class TestRoleAuthorization:
    def test_member_cannot_freeze_menu_cycle(self, api):
        """PRD §2.1: "Each operation is restricted to designated roles; an
        authenticated user attempting an operation outside their role is
        rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: the freeze operation is authorized for the Dietitian role only.

        Design: Corner/rbac/member_cannot_freeze_menu_cycle
        """
        ctx = setup_member_with_active_prescription(
            member_overrides={"full_name": "R One", "payer_member_id": "W-R1"})
        item = create_menu_item("rice_bowl")
        planned = create_planned_cycle(ctx["member"]["id"],
                                       ctx["prescription"]["id"],
                                       "2026-05-04", [(item["id"], 5)])
        resp = api.freeze_cycle(planned["cycle"]["id"],
                                make_member_headers(ctx["member"]["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        cycle = validate_success(
            api.get_menu_cycle(planned["cycle"]["id"],
                               make_member_headers(ctx["member"]["id"])))
        assert cycle["status"] == "PLANNED"

    def test_dietitian_cannot_remit_claim(self, api, dietitian_headers,
                                          billing_specialist_headers):
        """PRD §2.1: "Each operation is restricted to designated roles; an
        authenticated user attempting an operation outside their role is
        rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §3.7: "Adjudication belongs to the `PayerReviewer`, who remits with
        an `outcome`."

        Design: Corner/rbac/dietitian_cannot_remit_claim
        """
        ctx = setup_submitted_claim(
            member_overrides={"full_name": "R Two", "payer_member_id": "W-R2",
                              "income_fpl_percent": 145, "household_size": 3},
            item_specs=(("rice_bowl", 1), ("broth_soup", 1)),
            week_start_date="2026-04-13",
            route_overrides={"driver_id": "drv-r2", "route_date": "2026-04-15"},
            submitted_by="bill-1")
        resp = api.remit_claim(ctx["claim"]["id"], "PAID", dietitian_headers,
                               remitted_amount_cents=1758)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        claim = validate_success(api.get_claim(ctx["claim"]["id"],
                                               billing_specialist_headers))
        assert claim["status"] == "SUBMITTED"


class TestMemberOwnership:
    def test_member_confirm_receipt_of_others_delivery_forbidden(
            self, api, care_coordinator_headers):
        """PRD §3.5: "Because member identity is entity-backed (§2.1), the
        delivery's `member_id` must equal the caller's `X-User-ID`; confirming
        someone else's delivery is rejected with `ERR_DELIVERY_NOT_OWNED` (HTTP
        403)."

        Design: Corner/rbac/member_confirm_receipt_of_others_delivery_forbidden
        """
        ctx = setup_delivered_delivery(
            member_overrides={"full_name": "R Three A",
                              "payer_member_id": "W-R3A"},
            week_start_date="2026-04-13",
            route_overrides={"driver_id": "drv-r3", "route_date": "2026-04-15"})
        other = create_member(full_name="R Three B", payer_member_id="W-R3B")
        resp = api.confirm_receipt(ctx["delivery"]["id"],
                                   make_member_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_DELIVERY_NOT_OWNED)
        delivery = get_delivery(ctx["delivery"]["id"])
        assert delivery["confirmed_at"] is None


class TestOptimisticConcurrency:
    def test_occ_prescription_activate_stale_member_version(
            self, api, dietitian_headers, care_coordinator_headers):
        """PRD §2.7: "if the member's current `version` has advanced beyond
        `expected_member_version`, the request is rejected with
        `ERR_STALE_MEMBER_VERSION` (HTTP 412), and the client must re-read the
        member and retry."

        Design: Corner/cross_cutting_complexity_layers/occ_prescription_activate_stale_member_version
        """
        member = create_member(full_name="L One", payer_member_id="W-L1")
        stale_version = member["version"]
        activated = validate_success(api.set_member_status(
            member["id"], "ACTIVE", care_coordinator_headers))
        assert activated["version"] > stale_version
        referral = create_accepted_referral(member["id"])
        prescription = create_draft_prescription(member["id"], referral["id"])
        resp = api.activate_prescription(prescription["id"], stale_version,
                                         dietitian_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_MEMBER_VERSION)
        rx = validate_success(api.get_prescription(prescription["id"],
                                                   dietitian_headers))
        assert rx["status"] == "DRAFT", "a stale activation must not fire"
        member_after = validate_success(api.get_member(member["id"],
                                                       care_coordinator_headers))
        assert member_after["version"] == activated["version"], \
            "the rejected call must not mutate the member"

    def test_occ_claim_create_stale_authorization_version(
            self, api, billing_specialist_headers):
        """PRD §2.7: "if the authorization's current `version` has advanced
        beyond `expected_reauthorization_version`, the request is rejected with
        `ERR_STALE_AUTHORIZATION_VERSION` (HTTP 412), and the client must
        re-read the authorization and retry."
        PRD §3.7: "Creation snapshots the member's `payer_type` into
        `payer_type_snapshot`, sets `units_delivered` to the cycle's
        `meals_count` at that moment, computes the provisional amounts below,
        increments the authorization's `version` by one, and lands the claim in
        `DRAFT`."

        Design: Corner/cross_cutting_complexity_layers/occ_claim_create_stale_authorization_version
        """
        ctx = setup_delivered_delivery(
            member_overrides={"full_name": "L Two", "payer_member_id": "W-L2",
                              "income_fpl_percent": 145, "household_size": 3},
            item_specs=(("rice_bowl", 2),),
            week_start_date="2026-04-13",
            route_overrides={"driver_id": "drv-l2", "route_date": "2026-04-15"})
        auth_id = ctx["authorization"]["id"]
        observed_version = get_reauthorization(auth_id)["version"]

        claim_a = validate_success(api.create_claim(
            create_claim_payload(ctx["member"]["id"], ctx["cycle"]["id"],
                                 auth_id, observed_version),
            billing_specialist_headers), 201)
        assert get_reauthorization(auth_id)["version"] == observed_version + 1, \
            "each successful claim creation increments the version by one"

        stale = api.create_claim(
            create_claim_payload(ctx["member"]["id"], ctx["cycle"]["id"],
                                 auth_id, observed_version),
            billing_specialist_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_AUTHORIZATION_VERSION)

        fresh_version = get_reauthorization(auth_id)["version"]
        claim_b = validate_success(api.create_claim(
            create_claim_payload(ctx["member"]["id"], ctx["cycle"]["id"],
                                 auth_id, fresh_version),
            billing_specialist_headers), 201)
        assert claim_b["status"] == "DRAFT", "retry with the fresh version succeeds"
        assert claim_b["id"] != claim_a["id"]
        assert get_reauthorization(auth_id)["version"] == fresh_version + 1
