"""Header authentication, per-endpoint role lists, entity-backed ownership,
and left-to-right nested existence."""

from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    OPS,
    ApiErrorId,
    create_catalog_item_payload,
    create_child_payload,
    create_pause_payload,
    list_item_fees,
    list_ledger,
    make_member_headers,
    make_role_headers,
    register_member,
    setup_loss_fee,
    setup_member_with_subscription,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestHeaderAuthentication:
    def test_unknown_role_is_unauthenticated_and_unlisted_role_is_unauthorized(
            self, api, anonymous_headers):
        """PRD §2.1: "A request missing either header, or presenting a role the
        platform does not declare, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."
        PRD §2.1: "Each endpoint admits a fixed list of roles (enumerated in
        §4); a caller whose role is not on that endpoint's list is rejected
        with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/validations/unknown_role_header_returns_unauthenticated
        """
        # "Pirate" is not one of the five declared roles.
        resp1 = api.list_plans(make_role_headers("Pirate", "op-pirate-1"))
        validate_error(resp1, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

        # Anonymous is declared but GET /subscription-plans admits only
        # Member, CustomerService, PlatformAdmin (PRD §4).
        resp2 = api.list_plans(anonymous_headers)
        validate_error(resp2, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, 403)


class TestOwnership:
    def test_member_cannot_touch_other_members_subscription(self, api):
        """PRD §2.1: "A member touching a resource owned by a different member
        is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

        Design: Corner/validations/ownership_member_cannot_touch_other_members_subscription
        """
        ctx_a = setup_member_with_subscription(member_email="m.owna@x.com",
                                               with_child=False)
        member_b = register_member(email="m.ownb@x.com", full_name="Owner B")

        resp = api.pause_subscription(
            ctx_a["subscription"]["id"], create_pause_payload("2026-05-01", 7),
            make_member_headers(member_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value, 403)

        sub = validate_success(api.get_subscription(
            ctx_a["subscription"]["id"], make_member_headers(ctx_a["member"]["id"])))
        assert sub["status"] == "ACTIVE"

    def test_nested_path_validates_member_before_child(self, api):
        """PRD §2.6: "Requests that target nested resources validate path
        identifiers strictly left to right, rejecting with the 404 that
        corresponds to the first missing resource"
        PRD §2.6: "A request for a box item under a non-existent box therefore
        fails with `ERR_BOX_NOT_FOUND` before the item identifier is ever
        examined."

        Design: Corner/validations/nested_existence_left_to_right
        """
        # Existence (tier 3) runs before ownership (tier 4), so the missing
        # member id surfaces ERR_MEMBER_NOT_FOUND even though the Member caller
        # presents that same non-existent id.
        resp = api.create_child(
            NON_EXISTENT_UUID,
            create_child_payload(name="Kid", birthdate="2025-01-15"),
            make_member_headers(NON_EXISTENT_UUID),
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND.value, 404)


class TestRoleAuthorization:
    def test_member_cannot_create_catalog_item(self, api):
        """PRD §2.1: "A `PlatformAdmin` administers plans, the catalog,
        physical copies, and the logical clock."
        PRD §2.1: "Each endpoint admits a fixed list of roles (enumerated in
        §4); a caller whose role is not on that endpoint's list is rejected
        with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/member_cannot_create_catalog_item
        """
        member = register_member(email="m.rbac1@x.com")
        resp = api.create_catalog_item(
            create_catalog_item_payload(
                title="Sneaky", min_age_months=0, max_age_months=12,
                developmental_stages=["INFANT"], piece_count=1,
                retail_value_cents=100, replacement_value_cents=50),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, 403)

        data, meta = validate_paginated(api.list_catalog_items(ADMIN))
        assert meta["total_count"] == 0
        assert all(i["title"] != "Sneaky" for i in data)

    def test_operations_manager_cannot_waive_fee(self, api):
        """PRD §2.1: "A `CustomerService` agent handles wallet adjustments, fee
        waivers, dispute resolution, and member account closure."
        PRD §2.1: "Each endpoint admits a fixed list of roles (enumerated in
        §4); a caller whose role is not on that endpoint's list is rejected
        with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/ops_cannot_waive_fee
        """
        ctx = setup_loss_fee(
            item_overrides={"title": "Rattle", "piece_count": 2,
                            "retail_value_cents": 1000, "replacement_value_cents": 600},
            member_email="m.rbac2@x.com",
        )
        fee = ctx["fee"]
        resp = api.waive_fee(fee["id"], {"reason": "ops attempting waiver"}, OPS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, 403)

        fees = list_item_fees(ctx["item"]["id"], ctx["member"])
        assert len(fees) == 1 and fees[0]["status"] == "INVOICED"
        reasons = [e["reason"] for e in list_ledger(ctx["member"]["id"])]
        assert "FEE_WAIVER" not in reasons

    def test_member_cannot_run_allocation_checkpoint(self, api):
        """PRD §2.1: "An `OperationsManager` is the warehouse operator:
        shipping, carrier-event recording, inspection, box closure,
        sanitization completion, and the allocation checkpoint."
        PRD §2.1: "Each endpoint admits a fixed list of roles (enumerated in
        §4); a caller whose role is not on that endpoint's list is rejected
        with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/member_cannot_run_allocation_runs
        """
        member = register_member(email="m.rbac3@x.com")
        resp = api.run_allocation(make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, 403)
