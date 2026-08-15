"""Access control: authentication-first cascade, role authorization, grower
ownership chains, and exclusive-operation denials in both directions.
"""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    create_mortality_report_payload,
    create_pig_group_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    FEEDMILL,
    FIELDTECH,
    book_load,
    create_grower,
    create_scheduled_group,
    create_slot,
    create_verified_truck_wash,
    get_group,
    record_barn_wash,
    setup_contract_with_barn,
    setup_manure_plan,
    setup_placed_group,
)
from test_helpers.test_users import (
    make_envmgr_headers,
    make_grower_headers,
)

MISSING_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


class TestAuthenticationFirst:
    def test_auth_header_missing_beats_not_found(self, api):
        """PRD §2.1: "A request missing either header, or carrying an empty
        value for either, is rejected with `ERR_UNAUTHENTICATED`."
        PRD §2.6: "1. **Authentication.** `X-User-ID` and `X-User-Role` must
        both be present and non-empty; otherwise the request fails with
        `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.6: "Every mutating request is validated against a fixed cascade
        of checks, and the first failing check determines the error returned —
        later checks are not evaluated for that request."

        Against a nonexistent id, the answer is 401, never 404.

        Design: Corner/validations/auth_header_missing_beats_not_found
        """
        res = api.get_barn(MISSING_UUID, headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRoleAuthorization:
    def test_grower_cannot_create_pig_group_even_with_bad_refs(self, api):
        """PRD §2.1: "Each endpoint declares the roles permitted to call it; a
        caller whose role is not on that list is rejected with
        `ERR_FORBIDDEN_ROLE`."
        PRD §2.6: "2. **Role authorization.** The presented role must appear in
        the endpoint's role list; otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "POST | `/pig-groups` | Schedule pig placement | FieldTech,
        IntegratorAdmin".

        The role check precedes existence: even with unresolvable body
        references, the answer is 403 rather than 404.

        Design: Corner/validations/grower_cannot_create_pig_group_even_with_bad_refs
        """
        grower = create_grower()
        payload = create_pig_group_payload(
            MISSING_UUID, MISSING_UUID, grower["id"], head_placed=100,
            placement_date="2026-09-01", target_market_date="2027-01-12",
        )
        res = api.create_pig_group(payload, make_grower_headers(grower["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    def test_feedmill_cannot_dispatch_load(self, api):
        """PRD §2.1: "Each endpoint declares the roles permitted to call it; a
        caller whose role is not on that list is rejected with
        `ERR_FORBIDDEN_ROLE`."
        PRD §4: "POST | `/market-loads/{id}/dispatch` | Dispatch with verified
        truck wash | TransportCoordinator".

        FeedMill schedules and delivers feed but may not dispatch loads.

        Design: Corner/rbac/feedmill_cannot_dispatch_load
        """
        ctx = setup_placed_group(head_placed=500)
        slot = create_slot(slot_date="2026-07-13", shift="AM", capacity_head=500,
                           min_weight_lbs=240, max_weight_lbs=320)
        load = book_load(ctx["group"]["id"], slot["id"], 100)
        wash = create_verified_truck_wash("2026-07-12T08:00:00Z")

        res = api.dispatch_market_load(
            load["id"], {"truck_wash_id": wash["id"]}, FEEDMILL
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
        assert get_success_data(
            api.get_market_load(load["id"], ADMIN)
        )["load_status"] == "SCHEDULED"

    def test_environmental_manager_cannot_approve_plan(self, api):
        """PRD §2.1: "Each endpoint declares the roles permitted to call it; a
        caller whose role is not on that list is rejected with
        `ERR_FORBIDDEN_ROLE`."
        PRD §4: "POST | `/manure-plans/{id}/approve` | Approve plan; supersedes
        other approved plans of site | IntegratorAdmin".

        The role that submits plans cannot approve them.

        Design: Corner/rbac/environmental_manager_cannot_approve_plan
        """
        _site, plan = setup_manure_plan()
        get_success_data(
            api.submit_manure_plan(plan["id"], make_envmgr_headers("em_1"))
        )

        res = api.approve_manure_plan(plan["id"], make_envmgr_headers("em_2"))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
        assert get_success_data(
            api.get_manure_plan(plan["id"], ADMIN)
        )["plan_status"] == "SUBMITTED"

    def test_fieldtech_cannot_report_and_grower_cannot_verify_wash(self, api):
        """PRD §2.1: "Each endpoint declares the roles permitted to call it; a
        caller whose role is not on that list is rejected with
        `ERR_FORBIDDEN_ROLE`."
        PRD §3.4: "Losses on the farm are reported by the `Grower` who owns the
        group".
        PRD §3.6: "An `IntegratorAdmin` other than the recorder verifies the
        wash — `RECORDED` → `VERIFIED`, stamping `verified_by`".

        Exclusive operations hold both ways: FieldTech cannot file mortality
        reports; Grower cannot verify barn washes.

        Design: Corner/rbac/fieldtech_cannot_create_mortality_report_and_grower_cannot_verify_wash
        """
        ctx = setup_placed_group(head_placed=500)
        group_id = ctx["group"]["id"]
        grower_id = ctx["grower"]["id"]

        res = api.create_mortality_report(
            group_id,
            create_mortality_report_payload(
                report_date="2026-03-05", mortality_count=2, cull_count=0,
                reason_code="OTHER",
            ),
            FIELDTECH,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

        get_success_data(api.close_out_pig_group(group_id, FIELDTECH))
        wash = record_barn_wash(
            ctx["barn"]["id"], grower_id, "2026-03-02T12:00:00Z",
            clock="2026-03-02T12:00:00Z",
        )
        res = api.verify_barn_wash(wash["id"], make_grower_headers(grower_id))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
        assert get_success_data(
            api.get_barn_wash(wash["id"], ADMIN)
        )["wash_status"] == "RECORDED"


class TestGrowerOwnership:
    def test_grower_reading_foreign_group_forbidden(self, api):
        """PRD §2.1: "A grower acting on a resource whose grower chain does not
        resolve to their own `X-User-ID` is rejected with
        `ERR_NOT_RESOURCE_OWNER`."
        PRD §2.1: "a pig group resolves through its contract's `grower_id`".

        Design: Corner/validations/grower_reading_foreign_group_forbidden
        """
        ctx = setup_contract_with_barn()
        grower_a = ctx["grower"]
        grower_b = create_grower(grower_code="G-B", legal_name="GB",
                                 email="b@x.com")
        group = create_scheduled_group(
            ctx["barn"]["id"], ctx["contract"]["id"], head_placed=500
        )

        res = api.get_pig_group(group["id"], make_grower_headers(grower_b["id"]))
        validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)

        ok = validate_success(
            api.get_pig_group(group["id"], make_grower_headers(grower_a["id"])),
            200,
        )
        assert ok["group_status"] == "SCHEDULED"
        assert ok["id"] == group["id"]
        assert get_group(group["id"])["group_status"] == "SCHEDULED"
