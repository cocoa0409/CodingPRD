"""Role-based access control: exclusive operations and tenant ownership."""
import test_helpers as th
from test_helpers import (
    ApiErrorId,
    api_client,
    create_dispute_payload,
    create_inspection_payload,
    create_jurisdiction,
    create_property,
    create_tenancy,
    create_tenancy_payload,
    create_unit,
    make_inspector_headers,
    make_manager_admin_headers,
    make_property_manager_headers,
    make_tenant_headers,
    schedule_inspection,
    setup_issued_statement_with_damage,
    setup_vacated_with_statement,
    validate_error,
)

ADMIN = make_manager_admin_headers()
PM = make_property_manager_headers()
INSP = make_inspector_headers()


def _portfolio():
    jur = create_jurisdiction(interest_required=False, annual_interest_rate_bp=0)
    prop = create_property(jur["id"])
    unit = create_unit(prop["id"])
    return jur, prop, unit


class TestExclusiveOperations:
    def test_inspector_cannot_create_tenancy(self):
        """PRD §2.1: "Access to specific operations is restricted by role; an
        attempt to perform an action outside the caller's designated role is
        rejected with `ERR_FORBIDDEN_FOR_ROLE`." PRD §4: POST /pm/tenancies is
        authorized for PropertyManager only.

        Inspector calling POST /pm/tenancies is denied (403).

        Design: Corner/rbac/inspector_cannot_create_tenancy
        """
        _jur, _prop, unit = _portfolio()
        resp = api_client.create_tenancy(
            create_tenancy_payload(unit_id=unit["id"],
                                   lease_start_on="2026-09-01",
                                   lease_end_on="2027-09-01"),
            INSP,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_manager_admin_cannot_complete_inspection(self):
        """PRD §2.1: "Access to specific operations is restricted by role; an
        attempt to perform an action outside the caller's designated role is
        rejected with `ERR_FORBIDDEN_FOR_ROLE`." PRD §4: POST
        /pm/inspections/{id}/complete is authorized for Inspector only.

        ManagerAdmin cannot complete an inspection; it stays DRAFT.

        Design: Corner/rbac/manager_admin_cannot_complete_inspection
        """
        _jur, _prop, unit = _portfolio()
        ten = create_tenancy(unit["id"], lease_start_on="2026-09-01",
                             lease_end_on="2027-09-01")
        mi = schedule_inspection(ten["id"], "MOVE_IN",
                                 scheduled_start_at="2026-09-01T09:00:00Z",
                                 scheduled_end_at="2026-09-01T10:00:00Z")
        resp = api_client.complete_inspection(mi["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        data = th.get_success_data(api_client.get_inspection(mi["id"], PM))
        assert data["status"] == "DRAFT"

    def test_forbidden_role_on_statement_issue(self):
        """PRD §2.1: "Access to specific operations is restricted by role; an
        attempt to perform an action outside the caller's designated role is
        rejected with `ERR_FORBIDDEN_FOR_ROLE`." PRD §4: POST
        /pm/statements/{id}/issue is authorized for PropertyManager only.

        A Tenant — even the owning tenant — cannot issue the statement; it
        stays DRAFT.

        Design: Corner/validations/forbidden_role_on_statement_issue
        """
        ctx = setup_vacated_with_statement()
        stmt = ctx["statement"]
        resp = api_client.issue_statement(
            stmt["id"], make_tenant_headers(ctx["tenancy"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert th.get_statement(stmt["id"])["status"] == "DRAFT"


class TestTenantOwnership:
    def test_tenant_cannot_dispute_other_tenancys_statement(self):
        """PRD §2.1: "When `X-User-Role` is `Tenant`, `X-User-ID` is the `id`
        of the acting `Tenancy`; ownership checks on any resource that
        references a tenancy compare the resource's `tenancy_id` foreign-key
        field to `X-User-ID`, and a mismatch is rejected with
        `ERR_FORBIDDEN_FOR_ROLE`." PRD §3.6: "the acting tenant's identity
        must equal the statement's tenancy — the dispute copies its
        `tenancy_id` from the statement at creation."

        Tenant B disputing tenancy A's statement fails ownership (403).

        Design: Corner/rbac/tenant_cannot_dispute_other_tenancys_statement
        """
        ctx_a = setup_issued_statement_with_damage(
            jurisdiction_overrides={"code": "CA-ACT"},
            tenancy_overrides={"tenant_display_name": "T A"})
        # Second tenancy B on a separate unit (any state).
        unit_b = create_unit(ctx_a["prop"]["id"], unit_number="1B")
        ten_b = create_tenancy(unit_b["id"], tenant_display_name="T B",
                               lease_start_on="2025-01-10",
                               lease_end_on="2026-08-10")
        resp = api_client.create_dispute(
            create_dispute_payload(statement_id=ctx_a["statement"]["id"],
                                   disputed_amount_cents=5_000,
                                   reason="not my statement"),
            make_tenant_headers(ten_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
