"""Company onboarding, customer/site registration, site clock and freeze lifecycle."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_customer,
    add_design,
    add_science,
    add_site,
    add_staff,
    advance_clock,
    api_client,
    assert_site,
    create_customer_payload,
    create_installer_company_payload,
    create_site_payload,
    freeze_site,
    get_site,
    is_iso8601_timestamp,
    is_valid_uuid,
    setup_company,
    setup_site,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestRegistrationAndSiteBasics:
    def test_create_installer_company_returns_201_with_all_fields(self, api):
        """PRD section 4: "Endpoints that create a new resource respond with HTTP
        201 and the created resource in the envelope's `data` field".
        PRD section 2.4: "The `id` is a server-minted UUID with no type prefix.
        `created_at` and `updated_at` are ISO 8601 UTC timestamps with three
        fractional digits, recorded at creation and refreshed on every mutation
        respectively."

        Design: Corner/entities/create_installer_company_returns_201_with_all_fields
        """
        resp = api_client.create_installer_company(
            create_installer_company_payload(county_codes=["WH", "BG"]), ADMIN)
        data = validate_success(resp, 201)
        assert data["legal_name"] == "Clearwater Onsite LLC"
        assert data["license_number"] == "CW-100"
        assert data["county_codes"] == ["WH", "BG"]
        assert is_valid_uuid(data["id"]), "id must be a bare server-minted UUID"
        assert is_iso8601_timestamp(data["created_at"]), "created_at must be ISO 8601 UTC"

    def test_create_site_applies_system_defaults(self, api):
        """PRD section 3.1: "A new site's `status` is `OPEN`, its
        `current_period_index` is 0, and its `seasonal_freeze_until` is -1,
        meaning no freeze."

        Design: Corner/entities/create_site_applies_system_defaults
        """
        ctx = setup_company()
        add_staff(ctx, designer=False, officer=False, scientist=False)
        add_customer(ctx)
        resp = api_client.create_site(ctx.cid, ctx.cu, create_site_payload(), ctx.manager)
        data = validate_success(resp, 201)
        assert_site(data)
        assert data["current_period_index"] == 0
        assert data["seasonal_freeze_until"] == -1
        assert data["status"] == "OPEN"

    def test_get_site_with_unknown_id_returns_404(self, api):
        """PRD section 2.5: "Nested path validation proceeds strictly left to
        right: every identifier in the path must exist, and each resource must
        belong to its declared parent chain — company to customer to site to the
        child record. Any break in that chain is `ERR_NOT_FOUND` (HTTP 404)".

        Design: Corner/entities/get_site_with_unknown_id_returns_404
        """
        ctx = setup_company()
        add_staff(ctx, designer=False, officer=False, scientist=False)
        add_customer(ctx)
        resp = api_client.get_site(ctx.cid, ctx.cu, NON_EXISTENT_UUID, ctx.manager)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_create_customer_missing_email_returns_invalid_request(self, api):
        """PRD section 3.1: "With staff in place, a `ProjectManager` registers
        customers with `full_name`, `email`, and `phone`; the email must be unique
        within the installer company, again enforced as `ERR_INVALID_REQUEST`."
        PRD section 2.9: "(19) field ranges and uniqueness — `ERR_INVALID_REQUEST`".

        Design: Corner/entities/create_customer_missing_email_returns_invalid_request
        """
        ctx = setup_company()
        add_staff(ctx, designer=False, officer=False, scientist=False)
        add_customer_payload = create_customer_payload()
        del add_customer_payload["email"]
        resp = api_client.create_customer(ctx.cid, add_customer_payload, ctx.manager)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_system_fields_on_create_ignore_client_supplied_id_and_version(self, api):
        """PRD section 2.4: "The `id` is a server-minted UUID with no type prefix."
        PRD section 3.1: "A new site's `status` is `OPEN`, its
        `current_period_index` is 0, and its `seasonal_freeze_until` is -1,
        meaning no freeze."

        Design: Corner/entities/system_fields_on_create_ignore_client_supplied_id_and_version
        """
        ctx = setup_company()
        add_staff(ctx, designer=False, officer=False, scientist=False)
        add_customer(ctx)
        resp = api_client.create_site(
            ctx.cid, ctx.cu,
            create_site_payload(parcel_id="P-9", address_line="9 Meadow Ln"),
            ctx.manager)
        data = validate_success(resp, 201)
        assert is_valid_uuid(data["id"]), "the server mints the id as a bare UUID"
        reread = validate_success(api_client.get_site(ctx.cid, ctx.cu, data["id"], ctx.manager))
        assert reread["id"] == data["id"]
        assert reread["status"] == "OPEN"

    def test_child_creation_under_wrong_parent_returns_404(self, api):
        """PRD section 2.5: "Nested path validation proceeds strictly left to
        right: every identifier in the path must exist, and each resource must
        belong to its declared parent chain — company to customer to site to the
        child record. Any break in that chain is `ERR_NOT_FOUND` (HTTP 404); the
        server never reveals whether the failing segment was the parent or the
        child."

        Design: Corner/entities/child_creation_under_wrong_parent_returns_404
        """
        ctx = setup_company()
        add_staff(ctx, designer=False, officer=False, scientist=False)
        add_customer(ctx)
        other = setup_company(legal_name="Bedrock Septic Inc", license_number="BS-200")
        resp = api_client.create_site(
            other.cid, ctx.cu,
            create_site_payload(parcel_id="P-X", address_line="X"),
            ctx.manager)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestFreezeAndClockLifecycle:
    def test_immediate_consistency_response_reflects_mutation(self, api):
        """PRD section 2.2: "Unless otherwise noted, operations that create or
        modify a resource will return the created or updated resource object in
        the data field."
        PRD section 2.4: "`version` is an integer that increments by one on every
        mutation of the resource, whether the mutation arrives through a direct
        client action or through an internal cascade."
        PRD section 3.7: "A successful freeze moves the site's `status` to
        `FROZEN` and records the bound in `seasonal_freeze_until`."

        Design: Corner/consistency_model/immediate_consistency_response_reflects_mutation
        """
        ctx = setup_site()
        created = get_site(ctx)
        frozen = validate_success(api_client.freeze_site(
            ctx.cid, ctx.cu, ctx.s, {"freeze_until_period": 5}, ctx.manager))
        assert frozen["status"] == "FROZEN"
        assert frozen["seasonal_freeze_until"] == 5
        assert frozen["version"] == created["version"] + 1, (
            "the freeze mutation bumps version by exactly one")
        reread = get_site(ctx)
        assert reread["status"] == frozen["status"]
        assert reread["seasonal_freeze_until"] == frozen["seasonal_freeze_until"]
        assert reread["version"] == frozen["version"]

    def test_site_unfreeze_on_clock_advance(self, api):
        """PRD section 2.6: "When the new `current_period_index` moves past a
        frozen site's `seasonal_freeze_until`, the site thaws automatically,
        returning to `OPEN` with its freeze marker reset to -1."

        Design: Corner/state_machines/site_unfreeze_on_clock_advance
        """
        ctx = setup_site()
        freeze_site(ctx, 3)
        at_three = advance_clock(ctx, 3)
        assert at_three["status"] == "FROZEN", (
            "period 3 does not move past freeze_until 3 (strict > not yet met)")
        at_four = advance_clock(ctx, 1)
        assert at_four["status"] == "OPEN"
        assert at_four["seasonal_freeze_until"] == -1

    def test_satisfaction_of_freeze_window_passes(self, api):
        """PRD section 3.7: "the value must not lie in the past — it must be at
        least the site's `current_period_index`, else `ERR_FREEZE_IN_PAST`".

        Design: Corner/validations/satisfaction_of_freeze_window_passes
        """
        ctx = setup_site()
        advance_clock(ctx, 2)
        resp = api_client.freeze_site(
            ctx.cid, ctx.cu, ctx.s, {"freeze_until_period": 1}, ctx.manager)
        validate_error(resp, ApiErrorId.ERR_FREEZE_IN_PAST)
        ok = validate_success(api_client.freeze_site(
            ctx.cid, ctx.cu, ctx.s, {"freeze_until_period": 2}, ctx.manager))
        assert ok["status"] == "FROZEN"
        assert ok["seasonal_freeze_until"] == 2

    def test_error_open_work_remains_on_site_close(self, api):
        """PRD section 3.7: "A `ProjectManager` may close an `OPEN` site only when
        no open work remains: no design in `DRAFT` or `SUBMITTED`, no installation
        in any non-terminal state from `NOT_STARTED` through `READY_FOR_FINAL` or
        sitting in `FAILED_HOLD`, and no repair case in `OPEN`, `TRIAGED`, or
        `IN_REMEDIATION`. Any residue fails with `ERR_OPEN_WORK_REMAINS`."
        PRD section 3.4: "A designer may also withdraw a `DRAFT` design outright,
        moving it to `WITHDRAWN`".

        Design: Corner/validations/error_open_work_remains_on_site_close
        """
        ctx = setup_site()
        add_science(ctx)
        design = add_design(ctx)
        resp = api_client.close_site(ctx.cid, ctx.cu, ctx.s, ctx.manager)
        validate_error(resp, ApiErrorId.ERR_OPEN_WORK_REMAINS)
        validate_success(api_client.withdraw_design(
            ctx.cid, ctx.cu, ctx.s, design["id"], ctx.designer))
        closed = validate_success(api_client.close_site(ctx.cid, ctx.cu, ctx.s, ctx.manager))
        assert closed["status"] == "CLOSED"
