"""Breadth coverage: warranty-window calculations, body/business validations,
RBAC denials, optimistic-concurrency on authorize, and immediate consistency.

Covers corner queue sections: calculations, validations, rbac,
cross_cutting_complexity_layers, consistency_model.
"""
from test_helpers import (
    validate_success,
    validate_error,
    fixtures as fx,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    TEST_USERS,
    make_customer_headers,
    make_technician_headers,
)
from test_helpers import factories as f

SM = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["service_advisor_headers"]
PM = TEST_USERS["parts_manager_headers"]


# ===========================================================================
# calculations — warranty window
# ===========================================================================
class TestWarrantyCalculations:
    def test_warranty_part_line_billed_zero(self, api):
        """PRD §3.5: "If the line is a warranty line, its `extended_charge_cents` is
        zero and no further computation occurs."

        Design: Corner/calculations/warranty_part_line_billed_zero
        """
        base = fx.setup_closed_original_ro(
            api, closed_clock="2026-01-01T08:00:00Z", odometer_miles=40000
        )
        fx.setup_markup_matrix(api, [(0, 0, 20000, 0.40)])
        fx.set_clock(api, "2026-02-01T08:00:00Z")
        ro_c = fx.create_repair_order(
            api, base["customer"]["id"], base["vehicle"]["id"], comeback_of_ro_id=base["ro"]["id"]
        )
        pl = validate_success(
            api.create_part_line(
                ro_c["id"],
                f.create_part_line_payload(
                    "WPL-9", 1, 9000, markup_mode="FLAT_BRACKET", is_warranty=True
                ),
                PM,
            ),
            201,
        )
        assert pl["extended_charge_cents"] == 0

    def test_warranty_window_inclusive_boundary_at_90_days(self, api):
        """PRD §3.8: "The time bound holds when the current time is no later than
        the original order's `closed_at` plus the warranty period of 90 days — the
        boundary at exactly ninety days is inclusive."

        Design: Corner/calculations/warranty_window_inclusive_boundary_at_90_days
        """
        base = fx.setup_closed_original_ro(
            api, closed_clock="2026-01-01T08:00:00Z", odometer_miles=40000
        )
        # +90 days exactly (inclusive).
        fx.set_clock(api, "2026-04-01T08:00:00Z")
        resp = api.create_repair_order(
            f.create_repair_order_payload(
                base["customer"]["id"], base["vehicle"]["id"], comeback_of_ro_id=base["ro"]["id"]
            ),
            SM,
        )
        data = validate_success(resp, 201)
        assert data["is_comeback"] is True

    def test_warranty_window_expired_past_90_days_rejected(self, api):
        """PRD §3.8: "If either bound is exceeded, the warranty claim is rejected
        with `ERR_WARRANTY_EXPIRED`."

        Design: Corner/calculations/warranty_window_expired_past_90_days_rejected
        """
        base = fx.setup_closed_original_ro(
            api, closed_clock="2026-01-01T08:00:00Z", odometer_miles=40000
        )
        # +91 days (past WARRANTY_DAYS).
        fx.set_clock(api, "2026-04-02T08:00:00Z")
        resp = api.create_repair_order(
            f.create_repair_order_payload(
                base["customer"]["id"], base["vehicle"]["id"], comeback_of_ro_id=base["ro"]["id"]
            ),
            SM,
        )
        validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED.value)


# ===========================================================================
# validations
# ===========================================================================
class TestValidationCorners:
    def test_create_ro_with_nonexistent_vehicle_returns_referenced_not_found(self, api):
        """PRD §2.5: "the system validates that foreign keys carried in the body —
        such as `customer_id`, `vehicle_id`, `bay_id`, `comeback_of_ro_id`,
        `labor_operation_id`, and `technician_id` — point at resources that actually
        exist; an unresolved body foreign key is rejected with
        `ERR_REFERENCED_ENTITY_NOT_FOUND`."

        Design: Corner/validations/create_ro_with_nonexistent_vehicle_returns_referenced_not_found
        """
        customer = fx.create_customer(api)
        resp = api.create_repair_order(
            {"customer_id": customer["id"], "vehicle_id": "11111111-1111-4111-8111-111111111111"},
            SM,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND.value)

    def test_part_line_no_covering_markup_tier_returns_missing(self, api):
        """PRD §3.5: "If no tier's band contains the cost, the request is rejected
        with `ERR_MARKUP_TIER_MISSING`."

        Design: Corner/validations/part_line_no_covering_markup_tier_returns_missing
        """
        fx.setup_markup_matrix(api, [(0, 0, 20000, 0.40)])
        customer, vehicle = fx.create_customer_and_vehicle(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"])
        resp = api.create_part_line(
            ro["id"],
            f.create_part_line_payload("MT-50k", 1, 50000, markup_mode="FLAT_BRACKET"),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_MARKUP_TIER_MISSING.value)

    def test_authorize_empty_ro_returns_nothing_to_authorize(self, api):
        """PRD §3.3: "the order must have something to bill — at least one labor
        line or part line, or at least one recommended job already in `APPROVED`
        status — otherwise it is rejected with `ERR_NOTHING_TO_AUTHORIZE`."

        Design: Corner/validations/authorize_empty_ro_returns_nothing_to_authorize
        """
        customer, vehicle = fx.create_customer_and_vehicle(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"])
        resp = api.authorize_repair_order(
            ro["id"],
            {"expected_repair_order_version": ro["version"]},
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOTHING_TO_AUTHORIZE.value)

    def test_start_without_bay_returns_bay_not_assigned(self, api):
        """PRD §3.3: "Starting work advances an order from `APPROVED` to
        `IN_PROGRESS`; it requires the order to currently be `APPROVED` (else
        `ERR_INVALID_STATE`) and to have an assigned `bay_id` (else
        `ERR_BAY_NOT_ASSIGNED`)."

        Design: Corner/validations/start_without_bay_returns_bay_not_assigned
        """
        operation = fx.create_labor_operation(api, book_hours=0.5, default_rate_cents=10000)
        customer, vehicle = fx.create_customer_and_vehicle(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"])
        validate_success(
            api.create_labor_line(ro["id"], f.create_labor_line_payload(operation["id"]), SM), 201
        )
        fx.authorize_ro(api, ro["id"], customer["id"])
        resp = api.transition_repair_order(ro["id"], {"action": "START"}, SA)
        validate_error(resp, ApiErrorId.ERR_BAY_NOT_ASSIGNED.value)
        unchanged = validate_success(api.get_repair_order(ro["id"], SM), 200)
        assert unchanged["status"] == "APPROVED"


# ===========================================================================
# rbac
# ===========================================================================
class TestRbacCorners:
    def test_technician_cannot_create_technician(self, api):
        """PRD §4: the `POST /technicians` endpoint authorizes only `ShopManager`.
        PRD §2.1: "When the headers are well-formed but the role is not permitted to
        perform the requested operation, the request is rejected with
        `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/rbac/technician_cannot_create_technician
        """
        actor = fx.create_technician(api)
        resp = api.create_technician(
            f.create_technician_payload(full_name="Sneaky Tech"),
            make_technician_headers(actor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)

    def test_customer_cannot_schedule_repair_order(self, api):
        """PRD §4: the `POST /repair-orders/{id}/schedule` endpoint authorizes only
        `ServiceAdvisor` and `ShopManager`.
        PRD §2.1: "When the headers are well-formed but the role is not permitted to
        perform the requested operation, the request is rejected with
        `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/rbac/customer_cannot_schedule_repair_order
        """
        customer, vehicle = fx.create_customer_and_vehicle(api)
        bay = fx.create_service_bay(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"])
        resp = api.schedule_repair_order(
            ro["id"],
            f.schedule_payload(bay["id"], "2026-06-10T08:00:00Z", "2026-06-10T12:00:00Z"),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)

    def test_customer_cannot_decide_on_unowned_ro(self, api):
        """PRD §2.1: "a customer may only authorize an estimate or decide a
        recommended job on a repair order whose vehicle they own — an ownership
        violation is reported as `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §3.11: "in every case the acting customer must own the order's vehicle
        or the decision is refused with `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/rbac/customer_cannot_decide_on_unowned_ro
        """
        s = fx.setup_inspection_with_pending_job(api, item_severity="YELLOW")
        # A second, unrelated customer who does not own the RO's vehicle.
        customer_b = fx.create_customer(api)
        resp = api.decide_recommended_job(
            s["recommended_job"]["id"], {"decision": "APPROVE"},
            make_customer_headers(customer_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)
        rj = validate_success(api.get_recommended_job(s["recommended_job"]["id"], SM), 200)
        assert rj["status"] == "PENDING"


# ===========================================================================
# cross_cutting_complexity_layers — optimistic concurrency
# ===========================================================================
class TestOptimisticConcurrency:
    def test_occ_authorize_stale_version_conflict(self, api):
        """PRD §2.9: "If another writer has advanced that `version` since the
        customer last read the order — for instance by adding a line, returning a
        core, or approving recommended work — the customer's view of the estimate
        total is stale and the authorization is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_authorize_stale_version_conflict
        """
        fx.setup_markup_matrix(api, [(0, 0, 20000, 0.40)])
        customer, vehicle = fx.create_customer_and_vehicle(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"])
        stale_version = ro["version"]
        # A part-line add bumps the RO version, making stale_version stale.
        fx.add_part_line(api, ro["id"], "OCC-P", 1, 8000, markup_mode="FLAT_BRACKET")
        resp = api.authorize_repair_order(
            ro["id"],
            {"expected_repair_order_version": stale_version},
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
        unchanged = validate_success(api.get_repair_order(ro["id"], SM), 200)
        assert unchanged["status"] == "ESTIMATE"

    def test_occ_version_increments_on_authorize_success(self, api):
        """PRD §3.3: "On success the server snapshots `authorized_total_cents` from
        the order's `grand_total_cents`, advances the order to `APPROVED`,
        increments `version`, and records `authorized_version` as the `version`
        value that results from this mutation."

        Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_authorize_success
        """
        operation = fx.create_labor_operation(api, book_hours=1.0, default_rate_cents=10000)
        customer, vehicle = fx.create_customer_and_vehicle(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"], tax_rate=0.0)
        validate_success(
            api.create_labor_line(
                ro["id"],
                f.create_labor_line_payload(operation["id"], billing_method="FLAT_RATE"),
                SM,
            ),
            201,
        )
        current = validate_success(api.get_repair_order(ro["id"], SM), 200)
        before_version = current["version"]
        authorized = validate_success(
            api.authorize_repair_order(
                ro["id"],
                {"expected_repair_order_version": before_version},
                make_customer_headers(customer["id"]),
            ),
            200,
        )
        assert authorized["status"] == "APPROVED"
        assert authorized["authorized_total_cents"] == 10000
        assert authorized["version"] == before_version + 1


# ===========================================================================
# consistency_model — immediate totals
# ===========================================================================
class TestImmediateConsistency:
    def test_immediate_totals_visible_in_repair_order_after_part_add(self, api):
        """PRD §3.5: "The part's `extended_charge_cents` is computed at creation ...
        and adding the line recomputes the order's totals."
        PRD §3.6: "Finally `grand_total_cents` is the plain sum of
        `labor_total_cents`, `parts_total_cents`, `core_deposit_total_cents`, and
        `tax_cents`".

        Design: Corner/consistency_model/immediate_totals_visible_in_part_line_response
        """
        fx.setup_markup_matrix(api, [(0, 0, 20000, 0.40)])
        customer, vehicle = fx.create_customer_and_vehicle(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"], tax_rate=0.0)
        fx.add_part_line(api, ro["id"], "IM-1", 1, 8000, markup_mode="FLAT_BRACKET")
        ro_now = validate_success(api.get_repair_order(ro["id"], SM), 200)
        # 8000 * 1.4 = 11200.
        assert ro_now["parts_total_cents"] == 11200
        assert ro_now["grand_total_cents"] == 11200
