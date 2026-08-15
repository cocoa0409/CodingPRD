"""Authentication header presence, exclusive write roles, and universal reads."""
from test_helpers import (
    ApiErrorId,
    add_customer,
    add_site,
    add_staff,
    api_client,
    create_soil_evaluation_payload,
    make_inspector_headers,
    setup_company,
    validate_error,
    validate_success,
)


class TestAuthDiscipline:
    def test_missing_auth_headers_returns_401(self, api):
        """PRD section 2.1: "Every request carries two headers: `X-User-ID`,
        identifying the acting principal, and `X-User-Role`, naming exactly one of
        the six roles below. A request missing either header, or carrying an empty
        value for either, is rejected with `ERR_MISSING_AUTH` (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_returns_401
        """
        resp = api_client.list_installer_companies(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH)

    def test_manager_cannot_record_science(self, api):
        """PRD section 2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD section 4: "| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/soil-evaluations | Record a soil evaluation; supersedes any RECORDED evaluation for the site | SoilScientist |"

        Design: Corner/rbac/manager_cannot_record_science
        """
        ctx = setup_company()
        add_staff(ctx, designer=False, officer=False, scientist=False)
        add_customer(ctx)
        add_site(ctx)
        resp = api_client.create_soil_evaluation(
            ctx.cid, ctx.cu, ctx.s,
            create_soil_evaluation_payload(ctx.m1), ctx.manager)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_all_roles_can_read(self, api):
        """PRD section 2.1: "All six roles may use every read endpoint. Write
        privileges are exclusive per role as detailed throughout §3 and summarized
        in §4."

        Design: Corner/rbac/all_roles_can_read
        """
        ctx = setup_company()
        add_staff(ctx, designer=False, officer=False, manager=False,
                  scientist=False, inspector=True)
        resp = api_client.get_installer_company(
            ctx.cid, make_inspector_headers(ctx.i1))
        data = validate_success(resp)
        assert data["legal_name"] == "Clearwater Onsite LLC"
