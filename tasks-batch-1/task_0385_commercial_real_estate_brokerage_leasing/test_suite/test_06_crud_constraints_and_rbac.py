"""Resource creation, field constraints, defaults, RBAC, and terminal-state lockdown.

Covers Corner-queue entities, rbac, and state_machine (terminal lockdown) instances.
"""
import pytest
from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated, ApiErrorId,
    NON_EXISTENT_UUID, build_user_headers,
    make_admin_headers, make_listing_broker_headers, make_tenant_broker_headers,
    setup_one_firm, setup_two_firms, create_broker, create_property, create_published_space,
    create_listing, create_requirement, assert_brokerage, assert_space, assert_deal,
)


class TestBrokerageAndBrokerCreation:
    def test_create_brokerage_returns_201_with_fields(self, api):
        """PRD §3.1: "A brokerage is created with a `name`, a `side` declaring which side or sides of the
        market the firm operates — one of `LISTING`, `TENANT_REP`, or `DUAL` — and
        an optional `default_commission_pct` expressing the firm's default total
        commission rate as a fraction of total lease consideration."

        Design: Corner/entities/create_brokerage_returns_201_with_fields
        """
        admin_h = make_admin_headers()
        data = validate_success(api.create_brokerage(
            {"name": "Skyline CRE", "side": "DUAL", "default_commission_pct": 0.05}, admin_h),
            expected_status=201)
        assert data["name"] == "Skyline CRE"
        assert data["side"] == "DUAL"
        assert data["default_commission_pct"] == 0.05
        assert data["version"] == 1
        assert_brokerage(data)

    def test_create_brokerage_default_commission_applied(self, api):
        """PRD §3.1: "When omitted, `default_commission_pct` defaults to 0.06 (six percent); it must be
        greater than 0 and at most 0.15."

        Design: Corner/entities/create_brokerage_default_commission_applied
        """
        admin_h = make_admin_headers()
        data = validate_success(api.create_brokerage(
            {"name": "Default Firm", "side": "LISTING"}, admin_h), expected_status=201)
        assert data["default_commission_pct"] == 0.06

    def test_create_broker_missing_license_no_rejected(self, api):
        """PRD §3.1: "A `Broker` is registered under a firm by supplying that firm's identifier as
        `brokerage_id`, the broker's `full_name`, a `license_no`, and a `role` of
        `LISTING_BROKER`, `TENANT_BROKER`, or `ADMIN`."

        Design: Corner/entities/create_broker_missing_required_license_no
        """
        admin_h = make_admin_headers()
        bkrg = validate_success(api.create_brokerage(
            {"name": "NoLic Firm", "side": "LISTING"}, admin_h), expected_status=201)
        validate_error(api.create_broker(
            {"brokerage_id": bkrg["id"], "full_name": "No License", "role": "LISTING_BROKER"},
            admin_h), ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_broker_duplicate_license_no_rejected(self, api):
        """PRD §2.9: "A broker's `license_no` is unique across all brokers; a second registration carrying
        a `license_no` already in use is rejected."

        Design: Corner/entities/create_broker_duplicate_license_no_rejected
        """
        admin_h = make_admin_headers()
        bkrg = validate_success(api.create_brokerage(
            {"name": "Dup Firm", "side": "LISTING"}, admin_h), expected_status=201)
        validate_success(api.create_broker(
            {"brokerage_id": bkrg["id"], "full_name": "First", "license_no": "L-DUP-385",
             "role": "LISTING_BROKER"}, admin_h), expected_status=201)
        validate_error(api.create_broker(
            {"brokerage_id": bkrg["id"], "full_name": "Second", "license_no": "L-DUP-385",
             "role": "TENANT_BROKER"}, admin_h), ApiErrorId.ERR_INVALID_REQUEST.value)


class TestFieldConstraints:
    def test_create_space_defaults_free_rent_and_ti(self, api):
        """PRD §3.1: "Two optional asking-package terms round out a space: `free_rent_months`, defaulting
        to 0 and bounded between 0 and 24 inclusive, and `ti_allowance_psf`, the
        tenant-improvement allowance per square foot, defaulting to 0 and never
        negative."
        PRD §3.2: "A newly created space begins in `DRAFT`".

        Design: Corner/entities/create_space_default_free_rent_and_ti
        """
        from test_helpers import create_space
        _, lb, _ = setup_one_firm()
        prop = create_property(lb["id"], "SOMA-SF", "OFFICE", total_sf=10000)
        space = create_space(lb["id"], prop["id"], "D1", rentable_sf=2000, asking_rent_psf_yr=45)
        assert space["free_rent_months"] == 0
        assert space["ti_allowance_psf"] == 0
        assert space["status"] == "DRAFT"

    def test_requirement_min_gt_max_rejected(self, api):
        """PRD §2.9: "a requirement's `min_sf` must not exceed its `max_sf` ... Violations
        of any of these body-level constraints are rejected with `ERR_INVALID_REQUEST`
        (HTTP 422)."

        Design: Corner/entities/create_requirement_min_gt_max_rejected
        """
        admin_h = make_admin_headers()
        bkrg = validate_success(api.create_brokerage(
            {"name": "Req Firm", "side": "TENANT_REP"}, admin_h), expected_status=201)
        tb = create_broker(bkrg["id"], "TENANT_BROKER", "TB Req")
        tb_h = make_tenant_broker_headers(tb["id"])
        validate_error(api.create_requirement({
            "tenant_broker_id": tb["id"], "tenant_name": "BadRange", "market": "SOMA-SF",
            "asset_class": "OFFICE", "min_sf": 8000, "max_sf": 2000, "max_rent_psf_yr": 60},
            tb_h), ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_tour_window_end_before_start_rejected(self, api):
        """PRD §2.9: "a tour's `window_start` must be strictly before its `window_end`. Violations of any
        of these body-level constraints are rejected with `ERR_INVALID_REQUEST`
        (HTTP 422)."

        Design: Corner/entities/create_tour_window_end_before_start_rejected
        """
        from test_helpers import setup_published_space_and_requirement
        base = setup_published_space_and_requirement(market="SOMA-SF", asset_class="OFFICE")
        tb_h = make_tenant_broker_headers(base["tb"]["id"])
        validate_error(api.create_tour({
            "requirement_id": base["requirement"]["id"], "tenant_broker_id": base["tb"]["id"],
            "space_id": base["space"]["id"], "window_start": "2026-07-01T12:00:00Z",
            "window_end": "2026-07-01T11:00:00Z"}, tb_h), ApiErrorId.ERR_INVALID_REQUEST.value)


class TestNotFoundAndFk:
    def test_get_space_not_found(self, api):
        """PRD §2.5: "the server validates the path left to right and rejects the first identifier that
        does not resolve to an existing resource with `ERR_NOT_FOUND`."

        Design: Corner/entities/get_space_not_found
        """
        admin_h = make_admin_headers()
        validate_error(api.get_space(NON_EXISTENT_UUID, admin_h), ApiErrorId.ERR_NOT_FOUND.value)

    def test_create_deal_unknown_listing_fk_not_found(self, api):
        """PRD §2.5: "The same `ERR_NOT_FOUND` applies when a foreign key supplied in a request body does
        not resolve to an existing resource."

        Design: Corner/entities/create_deal_unknown_listing_fk_not_found
        """
        admin_h = make_admin_headers()
        bkrg = validate_success(api.create_brokerage(
            {"name": "FKD Rep", "side": "TENANT_REP"}, admin_h), expected_status=201)
        tb = create_broker(bkrg["id"], "TENANT_BROKER", "TB FKD")
        tb_h = make_tenant_broker_headers(tb["id"])
        req = create_requirement(tb["id"], "SOMA-SF", "OFFICE", 1000, 5000, 60)
        validate_error(api.create_deal(
            {"listing_id": NON_EXISTENT_UUID, "requirement_id": req["id"]}, tb_h),
            ApiErrorId.ERR_NOT_FOUND.value)


class TestComputedFieldsAndListing:
    def test_is_co_broke_computed_true_cross_brokerage(self, api):
        """PRD §3.5: "the system stamps `listing_broker_id` from the listing's broker of record,
        `procuring_broker_id` from the requirement's tenant broker, and the computed
        `is_co_broke` flag, which is true exactly when those two brokers belong to
        different brokerages."

        Design: Corner/entities/deal_is_co_broke_computed_true_cross_brokerage
        """
        lb, tb = setup_two_firms()
        lb_h = make_listing_broker_headers(lb["id"])
        prop = create_property(lb["id"], "SOMA-SF", "OFFICE", total_sf=10000)
        from test_helpers import create_active_listing
        space, listing = create_active_listing(lb["id"], prop["id"], "CB1",
                                               rentable_sf=3000, asking_rent_psf_yr=50)
        req = create_requirement(tb["id"], "SOMA-SF", "OFFICE", 1000, 6000, 70)
        deal = validate_success(api.create_deal(
            {"listing_id": listing["id"], "requirement_id": req["id"]}, lb_h),
            expected_status=201)
        assert deal["is_co_broke"] is True
        assert deal["listing_broker_id"] == lb["id"]
        assert deal["procuring_broker_id"] == tb["id"]

    def test_list_brokers_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned ... Every
        list-based response carries `limit`, `offset`, `total_count`, and `has_more` inside
        the `meta` object of the envelope."

        Design: Corner/entities/list_brokers_pagination_envelope
        """
        admin_h = make_admin_headers()
        bkrg = validate_success(api.create_brokerage(
            {"name": "List Firm", "side": "DUAL"}, admin_h), expected_status=201)
        create_broker(bkrg["id"], "LISTING_BROKER", "B One")
        create_broker(bkrg["id"], "TENANT_BROKER", "B Two")
        resp = api.list_brokers(admin_h, {"brokerage_id": bkrg["id"], "limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert len(data) == 1


class TestTerminalLockdown:
    def test_activate_withdrawn_listing_rejected(self, api):
        """PRD §3.2: "Withdrawing a listing is permitted from `DRAFT` or `ACTIVE` and moves it to the
        terminal `WITHDRAWN` state."
        PRD §3.6: "a write that targets a transition not defined from the deal's current stage is
        rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/activate_listing_from_withdrawn_terminal_rejected
        """
        _, lb, _ = setup_one_firm()
        lb_h = make_listing_broker_headers(lb["id"])
        prop = create_property(lb["id"], "SOMA-SF", "OFFICE", total_sf=10000)
        space = create_published_space(lb["id"], prop["id"], "T1", rentable_sf=3000, asking_rent_psf_yr=50)
        listing = create_listing(lb["id"], space["id"], term_months=60)  # DRAFT
        validate_success(api.withdraw_listing(listing["id"], lb_h))
        assert get_success_data(api.get_listing(listing["id"], lb_h))["status"] == "WITHDRAWN"
        validate_error(api.activate_listing(listing["id"], lb_h), ApiErrorId.ERR_INVALID_STATE.value)
        assert get_success_data(api.get_listing(listing["id"], lb_h))["status"] == "WITHDRAWN"


class TestRbac:
    def test_tenant_broker_cannot_create_property(self, api):
        """PRD §2.1: "When a syntactically valid request is made by a role that is not permitted to
        perform the requested operation, the request is rejected with
        `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/tenant_broker_cannot_create_property
        """
        admin_h = make_admin_headers()
        bkrg = validate_success(api.create_brokerage(
            {"name": "RB Rep", "side": "TENANT_REP"}, admin_h), expected_status=201)
        tb = create_broker(bkrg["id"], "TENANT_BROKER", "TB RB")
        tb_h = make_tenant_broker_headers(tb["id"])
        validate_error(api.create_property({
            "listing_broker_id": tb["id"], "name": "Sneaky Bldg", "market": "SOMA-SF",
            "asset_class": "OFFICE", "total_sf": 10000}, tb_h),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_listing_broker_cannot_create_requirement(self, api):
        """PRD §2.1: "When a syntactically valid request is made by a role that is not permitted to
        perform the requested operation, the request is rejected with
        `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/listing_broker_cannot_create_requirement
        """
        admin_h = make_admin_headers()
        bkrg = validate_success(api.create_brokerage(
            {"name": "RB List", "side": "LISTING"}, admin_h), expected_status=201)
        lb = create_broker(bkrg["id"], "LISTING_BROKER", "LB RB")
        lb_h = make_listing_broker_headers(lb["id"])
        validate_error(api.create_requirement({
            "tenant_broker_id": lb["id"], "tenant_name": "Sneaky Req", "market": "SOMA-SF",
            "asset_class": "OFFICE", "min_sf": 1000, "max_sf": 5000, "max_rent_psf_yr": 60},
            lb_h), ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_unauthenticated_missing_role_header_rejected(self, api):
        """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the declared roles, the
        request is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/unauthenticated_missing_role_header_rejected
        """
        validate_error(api.create_brokerage(
            {"name": "NoAuth", "side": "LISTING"}, {}), ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_only_admin_can_suspend_broker(self, api):
        """PRD §2.1: "When a syntactically valid request is made by a role that is not permitted to
        perform the requested operation, the request is rejected with
        `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/broker_admin_only_can_suspend
        """
        admin_h = make_admin_headers()
        bkrg = validate_success(api.create_brokerage(
            {"name": "SUS List", "side": "LISTING"}, admin_h), expected_status=201)
        lb = create_broker(bkrg["id"], "LISTING_BROKER", "LB SUS")
        lb_h = make_listing_broker_headers(lb["id"])
        validate_error(api.suspend_broker(lb["id"], lb_h), ApiErrorId.ERR_FORBIDDEN_ROLE.value)
