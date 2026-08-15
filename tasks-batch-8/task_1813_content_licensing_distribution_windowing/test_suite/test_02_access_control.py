"""Role-based access control, platform ownership, and segregation of duties."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_slot,
    create_and_offer_package,
    create_direct_license,
    create_platform,
    create_rights_holder,
    create_statement,
    create_title_payload,
    finalize_statement,
    get_package,
    get_success_data,
    list_all_licenses,
    make_finance_controller_headers,
    make_line,
    make_platform_buyer_headers,
    setup_catalog,
    validate_error,
    validate_success,
)

RM = TEST_USERS["rights_manager_headers"]
FA = TEST_USERS["finance_analyst_headers"]
FC = TEST_USERS["finance_controller_headers"]


class TestExclusiveOperationDenial:
    def test_platform_buyer_cannot_create_title(self, api):
        """PRD §2.1: "A request whose role is not listed for the endpoint — including a `PlatformBuyer` attempting to act on a package or license addressed to a different platform — is rejected with `ERR_FORBIDDEN` (403)."
        PRD §4: "| POST | /licensing/titles | Register a title | RightsManager |"

        Design: Corner/rbac/platform_buyer_cannot_create_title
        """
        buyer = make_platform_buyer_headers("11111111-1111-1111-1111-111111111111")
        resp = api.create_title(create_title_payload(), buyer)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_platform_buyer_cannot_withdraw_package(self, api):
        """PRD §2.1: "A request whose role is not listed for the endpoint — including a `PlatformBuyer` attempting to act on a package or license addressed to a different platform — is rejected with `ERR_FORBIDDEN` (403)."
        PRD §4: "| POST | /licensing/avail-packages/{id}/withdraw | Pull a DRAFT or OFFERED package | RightsManager |"

        Design: Corner/rbac/platform_buyer_cannot_withdraw_package
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        package = create_and_offer_package(
            workspace["platform"]["id"], [make_line(slot["id"], flat_fee_cents=10000)],
        )

        resp = api.withdraw_package(package["id"], workspace["buyer_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        assert get_package(package["id"])["package_status"] == "OFFERED", (
            "a failed withdraw must leave the package OFFERED"
        )

    def test_finance_controller_cannot_finalize_statement(self, api):
        """PRD §2.1: "A request whose role is not listed for the endpoint — including a `PlatformBuyer` attempting to act on a package or license addressed to a different platform — is rejected with `ERR_FORBIDDEN` (403)."
        PRD §4: "| POST | /licensing/royalty-statements/{id}/finalize | Finalize a DRAFT statement | FinanceAnalyst |"

        Design: Corner/rbac/finance_controller_cannot_finalize_statement
        """
        holder = create_rights_holder()
        statement = create_statement(
            holder["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z",
        )

        resp = api.finalize_statement(statement["id"], FC)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        current = get_success_data(api.get_royalty_statement(statement["id"], FA))
        assert current["statement_status"] == "DRAFT"

    def test_rights_manager_cannot_submit_revenue_report(self, api):
        """PRD §2.1: "A request whose role is not listed for the endpoint — including a `PlatformBuyer` attempting to act on a package or license addressed to a different platform — is rejected with `ERR_FORBIDDEN` (403)."
        PRD §3.8: "Only the `PlatformBuyer` who owns the license may submit, and the license must be `EXECUTED` or `ACTIVE` with a `fee_model` other than `FLAT_FEE` — flat-fee deals have no revenue share to report — otherwise the submission is rejected with `ERR_LICENSE_NOT_REPORTABLE` (409)."

        Design: Corner/rbac/rights_manager_cannot_submit_revenue_report
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        license_agreement = create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-08-01T00:00:00Z",
            license_end="2027-08-01T00:00:00Z",
            fee_model="REVENUE_SHARE", revenue_share_pct=50,
        )

        payload = {
            "period_start": "2026-07-01T00:00:00Z",
            "period_end": "2026-07-31T00:00:00Z",
            "gross_revenue_cents": 1000,
            "expected_license_version": license_agreement["version"],
        }
        resp = api.submit_revenue_report(license_agreement["id"], payload, RM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


class TestPlatformOwnership:
    def test_platform_buyer_cannot_accept_other_platforms_package(self, api):
        """PRD §3.5: "Acceptance is the `PlatformBuyer`'s action, and only the buyer to whom the package is addressed may perform it — a caller whose `X-User-ID` does not equal the package's `platform_id` is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/platform_buyer_cannot_accept_other_platforms_package
        """
        workspace = setup_catalog()
        other_platform = create_platform(
            name="Other Platform", platform_type="AVOD",
            required_asset_profiles=["HD"],
        )
        slot = add_slot(workspace)
        package = create_and_offer_package(
            workspace["platform"]["id"], [make_line(slot["id"], flat_fee_cents=10000)],
        )

        foreign_buyer = make_platform_buyer_headers(other_platform["id"])
        resp = api.accept_package(package["id"], [slot["id"]], foreign_buyer)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        assert get_package(package["id"])["package_status"] == "OFFERED"
        assert list_all_licenses() == [], "no license may be created by a foreign buyer"


class TestSegregationOfDuties:
    def test_statement_payer_must_differ_from_finalizer(self, api):
        """PRD §3.9: "Marking paid requires the statement to be `FINALIZED`, otherwise `ERR_STATEMENT_NOT_FINALIZED` (409), and enforces segregation of duties: the caller's `X-User-ID` must differ from `finalized_by_user_id` — the same individual who finalized a statement may not mark it paid, and the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (403). On success `paid_by_user_id` records the controller and the statement reaches its terminal `PAID` state."

        Design: Corner/rbac/statement_payer_must_differ_from_finalizer
        """
        holder = create_rights_holder()
        statement = create_statement(
            holder["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z",
        )
        finalized = finalize_statement(statement["id"], user_id="user-7")
        assert finalized["finalized_by_user_id"] == "user-7"

        resp = api.mark_statement_paid(
            statement["id"], make_finance_controller_headers("user-7"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        paid = validate_success(
            api.mark_statement_paid(
                statement["id"], make_finance_controller_headers("user-8"),
            ),
            200,
        )
        assert paid["statement_status"] == "PAID"
        assert paid["paid_by_user_id"] == "user-8"
