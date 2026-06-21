"""Entity creation defaults, system fields, FK integrity, listing pagination,
RBAC denials and ownership checks, optimistic concurrency, and derived-field
reconciliation.

These are the breadth corners that exercise the structural surface of the API.
"""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_customer, create_technician, create_service_job,
    create_flat_rate_item, create_part, create_truck_stock,
    propose_assignment, setup_on_site_job, setup_presented_estimate,
    create_estimate_on_job, add_flat_rate_line, present_estimate,
    api_client, TEST_USERS, make_customer_headers, make_technician_headers,
    build_user_headers,
)

OM = TEST_USERS["office_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]

NORMAL_START = "2026-06-16T10:00:00.000Z"
NORMAL_END = "2026-06-16T12:00:00.000Z"
NORMAL_ETA = "2026-06-16T10:15:00.000Z"


class TestEntityCreationCorners:
    def test_create_service_job_returns_201_with_defaults(self, api):
        """PRD §3.2: "The job is born in status `RECEIVED`."
        PRD §3.2: "an optional `priority` that is one of `STANDARD` or `EMERGENCY`
        (defaulting to `STANDARD`)".
        PRD §2.4: "a `version` (an integer that begins at its initial value on
        creation and increments by one on every mutation of that resource)."

        Design: Corner/entities/create_service_job_returns_201_with_defaults
        """
        customer = create_customer(credit_limit_cents=100000)
        resp = api.create_service_job(
            {"customer_id": customer["id"], "category": "LEAK"}, DISP)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "RECEIVED"
        assert data["priority"] == "STANDARD"
        assert data["version"] == 1

    def test_create_service_job_missing_category_rejected(self, api):
        """PRD §2.6: "Request well-formedness comes fourth: a body that fails to parse,
        a missing required field, or a value that violates an enum, type, or range
        constraint yields `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_service_job_missing_category_returns_invalid_request
        """
        customer = create_customer(credit_limit_cents=100000)
        resp = api.create_service_job({"customer_id": customer["id"]}, DISP)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_service_job_bad_category_enum_rejected(self, api):
        """PRD §3.2: "a `category` that is one of `LEAK`, `DRAIN`, `WATER_HEATER`, or
        `REPIPE`".
        PRD §2.6: "a value that violates an enum, type, or range constraint yields
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_service_job_bad_category_enum_returns_invalid_request
        """
        customer = create_customer(credit_limit_cents=100000)
        resp = api.create_service_job(
            {"customer_id": customer["id"], "category": "PLUMBING"}, DISP)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_get_nonexistent_service_job_returns_not_found(self, api):
        """PRD §2.6: "Existence comes third: any referenced resource (path identifier
        left-to-right, then body foreign key) that does not exist yields
        `ERR_NOT_FOUND`."

        Design: Corner/entities/get_service_job_nonexistent_returns_not_found
        """
        resp = api.get_service_job(NON_EXISTENT_UUID, DISP)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_create_customer_default_credit_limit(self, api):
        """PRD §3.1: "an optional `credit_limit_cents` (defaulting to 100000 cents)".
        PRD §3.1: "The customer's `committed_credit_cents` is a computed running
        total, starting at 0".

        Design: Corner/entities/create_customer_omitting_credit_limit_applies_default
        """
        resp = api.create_customer(
            {"name": "Cust DEF", "service_address": "4 A St"}, OM)
        data = validate_success(resp, expected_status=201)
        assert data["credit_limit_cents"] == 100000, \
            f"default credit limit is 100000, got {data['credit_limit_cents']}"
        assert data["committed_credit_cents"] == 0, \
            f"committed credit starts at 0, got {data['committed_credit_cents']}"

    def test_create_service_job_with_unknown_customer_fk_rejected(self, api):
        """PRD §2.5: "Only after every path identifier resolves does the system
        validate foreign keys referenced in the request body, likewise rejecting
        unknown references with `ERR_NOT_FOUND`."

        Design: Corner/entities/create_service_job_with_nonexistent_customer_fk_returns_not_found
        """
        resp = api.create_service_job(
            {"customer_id": "11111111-1111-4111-8111-111111111111",
             "category": "LEAK"}, DISP)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_technician_system_fields_defaulted_on_create(self, api):
        """PRD §3.1: "Each technician carries a system-managed availability `status`
        — one of `AVAILABLE`, `ON_CALL`, or `OFF_DUTY`, defaulting to `AVAILABLE`".
        PRD §3.1: "A technician also accumulates several computed counters discussed
        in §3.7 and §3.8: `lifetime_completed_count`, `lifetime_callback_count`, and
        `needs_restock_skus`, each defaulting to 0."

        Design: Corner/entities/system_fields_generated_on_create_input_ignored
        """
        resp = api.create_technician({"name": "Tech SYS", "skill_level": 3}, OM)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "AVAILABLE"
        assert data["lifetime_completed_count"] == 0
        assert data["version"] == 1

    def test_list_service_jobs_pagination_envelope(self, api):
        """PRD §2.3: "Paginated list-based responses include the following fields in
        the `meta` object of the response envelope: `limit`, `offset`, `total_count`,
        and `has_more`."

        Design: Corner/entities/list_service_jobs_pagination_envelope
        """
        customer = create_customer(credit_limit_cents=100000)
        create_service_job(customer["id"], category="LEAK")
        create_service_job(customer["id"], category="DRAIN")
        resp = api.list_service_jobs(
            DISP, params={"customer_id": customer["id"], "limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2, \
            f"two jobs for the customer, got total_count {meta['total_count']}"
        assert meta["has_more"] is True, "limit 1 of 2 leaves more"
        assert len(data) == 1, f"one item returned under limit 1, got {len(data)}"


class TestRbacCorners:
    def test_dispatcher_cannot_approve_estimate(self, api):
        """PRD §2.1: "When a well-authenticated principal attempts an operation its
        role is not permitted to perform ... the request is rejected with
        `ERR_UNAUTHORIZED`."
        PRD §3.4: "**Approval** of an estimate is reserved to the owning customer".

        Design: Corner/rbac/dispatcher_cannot_approve_estimate_unauthorized
        """
        fr = create_flat_rate_item(code="RB-1", category="LEAK",
                                   base_price_cents=20000, skill_required=1)
        scenario = setup_presented_estimate(
            flat_rate_lines=[{"item": fr, "quantity": 1}],
            customer_overrides={"credit_limit_cents": 100000},
            technician_overrides={"skill_level": 2},
            job_overrides={"category": "LEAK"},
            window_start=NORMAL_START, window_end=NORMAL_END, eta=NORMAL_ETA)
        resp = api.approve_estimate(scenario["estimate"]["id"], DISP)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
        reread = get_success_data(api.get_estimate(scenario["estimate"]["id"], OM))
        assert reread["status"] == "PRESENTED"

    def test_customer_cannot_approve_other_customers_estimate(self, api):
        """PRD §2.1: "a customer may only approve, decline, or file callbacks against
        jobs whose `customer_id` equals its own `X-User-ID`."
        PRD §3.4: "the acting `Customer` must own the job whose `customer_id` equals
        the caller's `X-User-ID`, or the request is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/customer_cannot_approve_other_customers_estimate_unauthorized
        """
        fr = create_flat_rate_item(code="OW-1", category="LEAK",
                                   base_price_cents=20000, skill_required=1)
        customer_b = create_customer(credit_limit_cents=100000)
        scenario = setup_presented_estimate(
            flat_rate_lines=[{"item": fr, "quantity": 1}],
            customer_overrides={"credit_limit_cents": 100000},
            technician_overrides={"skill_level": 2},
            job_overrides={"category": "LEAK"},
            window_start=NORMAL_START, window_end=NORMAL_END, eta=NORMAL_ETA)
        # Customer B (not the job's owner) tries to approve customer A's estimate.
        cust_b_h = make_customer_headers(customer_b["id"])
        resp = api.approve_estimate(scenario["estimate"]["id"], cust_b_h)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
        reread = get_success_data(api.get_estimate(scenario["estimate"]["id"], OM))
        assert reread["status"] == "PRESENTED"

    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request that omits either header, or carries a malformed
        value, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        resp = api._request(
            "POST", "/plumbing/service-jobs",
            {"customer_id": NON_EXISTENT_UUID, "category": "LEAK"}, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_technician_cannot_create_part(self, api):
        """PRD §2.1: "An `OfficeManager` is the back-office operator: it configures
        membership plans, the flat-rate book, the parts catalog, technicians, and
        inspectors".
        PRD §2.1: "When a well-authenticated principal attempts an operation its role
        is not permitted to perform ... the request is rejected with
        `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/technician_cannot_create_part_unauthorized
        """
        technician = create_technician(skill_level=2)
        tech_h = make_technician_headers(technician["id"])
        resp = api.create_part(
            {"sku": "NP-1", "name": "Nope", "list_price_cents": 100}, tech_h)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


class TestOptimisticConcurrency:
    def test_stale_job_version_on_estimate_create_rejected(self, api):
        """PRD §2.7: "The request body must include `expected_job_version`; if its
        value does not equal the target job's current `version`, the create is
        rejected with `ERR_STALE_JOB_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_job_version_on_estimate_create
        """
        scenario = setup_on_site_job(
            customer_overrides={"credit_limit_cents": 100000},
            technician_overrides={"skill_level": 3},
            job_overrides={"category": "LEAK"},
            window_start=NORMAL_START, window_end=NORMAL_END, eta=NORMAL_ETA)
        tech_id = scenario["technician"]["id"]
        job = scenario["job"]
        observed_version = job["version"]
        tech_h = make_technician_headers(tech_id)
        # First create succeeds and bumps job.version, making observed_version stale.
        validate_success(api.create_estimate(
            job["id"], {"expected_job_version": observed_version}, tech_h),
            expected_status=201)
        resp = api.create_estimate(
            job["id"], {"expected_job_version": observed_version}, tech_h)
        validate_error(resp, ApiErrorId.ERR_STALE_JOB_VERSION.value)

    def test_dispatch_create_with_current_version_succeeds_and_increments(self, api):
        """PRD §2.7: "Its body likewise must include `expected_job_version`".
        PRD §3.2: "A newly created assignment begins in status `PROPOSED`, and
        creating it increments the parent job's `version`."

        Design: Corner/cross_cutting_complexity_layers/occ_correct_job_version_succeeds_and_increments
        """
        customer = create_customer(credit_limit_cents=100000)
        technician = create_technician(skill_level=3)
        job = create_service_job(customer["id"], category="LEAK")
        assert job["version"] == 1
        resp = api.create_dispatch_assignment(
            {"job_id": job["id"], "technician_id": technician["id"],
             "window_start": NORMAL_START, "window_end": NORMAL_END,
             "eta": NORMAL_ETA, "expected_job_version": job["version"]}, DISP)
        validate_success(resp, expected_status=201)
        reread = get_success_data(api.get_service_job(job["id"], DISP))
        assert reread["version"] == 2, \
            f"dispatch-create increments the job version to 2, got {reread['version']}"


class TestDerivedFieldReconciliation:
    def test_needs_restock_computed_on_truck_stock_create(self, api):
        """PRD §3.1: "The `needs_restock` flag is true exactly when the row's
        `quantity` is at or below its `reorder_point`."
        PRD §3.1: "Whenever a truck-stock row is created, restocked, or otherwise has
        its quantity recomputed, the system re-evaluates `needs_restock` and recomputes
        the owning technician's `needs_restock_skus`, which is the count of that
        technician's truck-stock rows currently flagged for restock."

        Design: Corner/cross_cutting_complexity_layers/derived_field_needs_restock_recomputed_on_restock
        """
        part = create_part(sku="DR-1", name="Washer", list_price_cents=50)
        technician = create_technician(skill_level=2)
        resp = api.create_truck_stock(
            {"technician_id": technician["id"], "part_id": part["id"],
             "quantity": 2, "reorder_point": 2}, OM)
        data = validate_success(resp, expected_status=201)
        assert data["needs_restock"] is True, \
            "quantity 2 <= reorder_point 2 -> needs_restock true on create"
        reread_tech = get_success_data(api.get_technician(technician["id"], OM))
        assert reread_tech["needs_restock_skus"] == 1, \
            f"the flagged row bumps needs_restock_skus to 1, got {reread_tech['needs_restock_skus']}"


class TestConsistencyModel:
    def test_committed_credit_visible_immediately_after_approve(self, api):
        """PRD §3.4: "The customer's `committed_credit_cents` is increased by that
        same estimate total, reserving the credit."
        PRD §3.1: "The customer's `committed_credit_cents` is a computed running
        total, starting at 0, of authorized estimate amounts across its jobs; it rises
        on estimate approval".

        Design: Corner/consistency_model/immediate_consistency_committed_credit_visible_in_same_flow
        """
        fr = create_flat_rate_item(code="IM-1", category="DRAIN",
                                   base_price_cents=20000, skill_required=1)
        scenario = setup_presented_estimate(
            flat_rate_lines=[{"item": fr, "quantity": 1}],
            customer_overrides={"credit_limit_cents": 100000},
            technician_overrides={"skill_level": 2},
            job_overrides={"category": "DRAIN"},
            window_start=NORMAL_START, window_end=NORMAL_END, eta=NORMAL_ETA)
        committed_amount = scenario["estimate"]["estimate_total_cents"]
        cust_h = make_customer_headers(scenario["customer"]["id"])
        validate_success(api.approve_estimate(scenario["estimate"]["id"], cust_h))
        reread = get_success_data(api.get_customer(scenario["customer"]["id"], OM))
        assert reread["committed_credit_cents"] == committed_amount, \
            ("committed credit is visible immediately in the same flow; expected "
             f"{committed_amount}, got {reread['committed_credit_cents']}")
