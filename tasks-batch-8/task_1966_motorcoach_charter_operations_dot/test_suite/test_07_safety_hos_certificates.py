"""Safety scoring on driver vs customer domains, HOS accumulation gating,
and insurance certificate issuance state dependencies."""
from datetime import datetime, timezone

import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    ApiErrorId, TEST_USERS, make_customer_headers,
    set_clock, make_customer, make_vehicle, make_driver, make_quote,
    price_quote, accept_quote, pay_full_deposit, get_order, get_driver,
    get_customer, assign_order, create_incident_payload,
    create_certificate_payload, setup_assigned_order,
    setup_in_progress_order, setup_completed_order,
    setup_pending_deposit_order, accumulate_driver_cycle_hours,
)

DISPATCH = TEST_USERS["dispatch_manager_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


class TestSafetyScoreDomains:
    def test_driver_score_deducts_minor_accident_after_completion(self, api):
        """PRD §3.9: "Each report deducts by severity: 2.0 for `MINOR`, 5.0 for
        `MODERATE`, 12.0 for `MAJOR`, and 25.0 for `CRITICAL`. The deduction
        multiplies by one and a half when the incident is an `ACCIDENT`". PRD
        §3.9: "The recomputation runs whenever an incident is filed and whenever
        one of the driver's orders completes".

        MINOR ACCIDENT on the completed order: deduction 2.0 * 1.5 = 3.0 ->
        safety_score 100.0 - 3.0 = 97.0.

        Design: Difficulty/dual_variant_calc/safety_score_driver_vs_customer_domain
        """
        ctx = setup_completed_order(actual_miles=100, actual_hours=4)
        validate_success(api.create_incident(
            ctx["order"]["id"],
            create_incident_payload(ctx["driver"]["id"], ctx["vehicle"]["id"],
                                    incident_type="ACCIDENT", severity="MINOR"),
            DISPATCH), 201)
        driver = get_driver(ctx["driver"]["id"])
        assert driver["safety_score"] == 97.0
        assert driver["safety_score"] < 100.0

    def test_customer_and_driver_scores_apply_their_own_models(self, api):
        """PRD §3.9 (driver model): "Each report deducts by severity: 2.0 for
        `MINOR` ... The deduction multiplies by one and a half when the incident
        is an `ACCIDENT`" -> 100.0 - 3.0 = 97.0. PRD §3.9 (customer model):
        "Each completed order starts from a base of 100.0 and loses points for
        the incidents filed against it: 3.0 per `MINOR`", weighted by recency —
        the weight is one minus the number of days since the order's
        `completed_at`, divided by 365, but never less than 0.1" (0 days here,
        so weight 1.0) -> 97.0.

        The incident is filed while the order is IN_PROGRESS, then the trip
        completes; both recomputations run at completion (PRD §3.9, §3.5).

        Design: Difficulty/dual_variant_calc/safety_score_driver_vs_customer_domain
        """
        ctx = setup_in_progress_order(
            quote_overrides={"trip_date": "2026-07-10T08:00:00Z",
                             "return_date": "2026-07-10T14:00:00Z",
                             "estimated_miles": 100, "estimated_hours": 4},
            clock_iso="2026-07-01T00:00:00Z")
        validate_success(api.create_incident(
            ctx["order"]["id"],
            create_incident_payload(ctx["driver"]["id"], ctx["vehicle"]["id"],
                                    incident_type="ACCIDENT", severity="MINOR"),
            DISPATCH), 201)
        validate_success(api.complete_trip(
            ctx["order"]["id"], {"actual_miles": 100, "actual_hours": 4},
            DISPATCH))
        driver = get_driver(ctx["driver"]["id"])
        customer = get_customer(ctx["customer"]["id"])
        assert driver["safety_score"] == 97.0
        assert customer["safety_audit_score"] == 97.0


class TestHosAccumulationGate:
    def test_assigned_driver_leaves_available_status(self, api):
        """PRD §3.4: a successful assignment "moves each assigned driver
        `AVAILABLE` → `ON_DUTY_NOT_DRIVING`". Once on duty for one order the
        driver no longer stands `AVAILABLE` — the gate for any further
        assignment (PRD §3.4: "the named driver must exist and stand
        `AVAILABLE`").

        Design: Difficulty/resource_temporal_overlap/driver_hos_accumulation_overlap
        """
        ctx = setup_assigned_order()
        driver = get_driver(ctx["driver"]["id"])
        assert driver["status"] == "ON_DUTY_NOT_DRIVING"
        assert driver["status"] != "AVAILABLE"

    def test_cycle_limit_breach_blocks_assignment(self, api):
        """PRD §3.4: "the cycle allowance — 70.0 hours for a `CYCLE_70_8` driver
        or 60.0 for a `CYCLE_60_7` driver — minus `current_cycle_hours`,
        breaching which yields `ERR_HOS_CYCLE_LIMIT`", and PRD §2.8:
        "hours-of-service feasibility first (rejected with `ERR_HOS_VIOLATION`,
        with the more specific `ERR_HOS_DRIVING_LIMIT`,
        `ERR_HOS_ON_DUTY_WINDOW`, or `ERR_HOS_CYCLE_LIMIT` identifying the limit
        breached)". PRD §3.2: "the driver becomes `AVAILABLE` again, and the
        daily counters `current_driving_hours_today` and
        `current_on_duty_hours_today` reset to zero along with
        `consecutive_driving_minutes`" — the cycle counter is not reset.

        Six completed 10 h driving trips accumulate 60.0 cycle hours; an 11 h
        trip exceeds the remaining 10.0 h of the 70 h cycle -> rejected.

        Design: Difficulty/resource_temporal_overlap/driver_hos_accumulation_overlap
        """
        set_clock("2026-08-01T00:00:00Z")
        customer = make_customer(company_name="HOS Overlap")
        vehicle = make_vehicle()
        driver = make_driver()
        accumulate_driver_cycle_hours(driver["id"], vehicle["id"],
                                      customer["id"], trips=6, hours_each=10,
                                      base_iso="2026-08-01T00:00:00Z")
        driver_after = get_driver(driver["id"])
        assert driver_after["status"] == "AVAILABLE"
        assert driver_after["current_cycle_hours"] == 60.0

        quote = make_quote(customer["id"], trip_date="2026-08-06T08:00:00Z",
                           return_date="2026-08-06T19:00:00Z",
                           estimated_miles=400, estimated_hours=11)
        quote = price_quote(quote["id"])
        order = accept_quote(quote["id"], customer["id"])
        order = pay_full_deposit(order["id"], customer["id"])
        payload = {"vehicle_id": vehicle["id"], "driver_id": driver["id"],
                   "expected_order_version": order["version"]}
        res = api.assign_order(order["id"], payload, DISPATCH)
        assert res.status_code == 422
        validate_error_is_one_of(
            res, [ApiErrorId.ERR_HOS_VIOLATION.value,
                  ApiErrorId.ERR_HOS_CYCLE_LIMIT.value])

    def test_eleven_hour_trip_at_fresh_driver_boundary_passes(self, api):
        """PRD §3.4: "the driving allowance of 11.0 hours minus the driver's
        `current_driving_hours_today`". A fresh driver (0.0 h) assigned an
        exactly-11 h trip sits at the boundary, not beyond it, so assignment
        succeeds (`CONFIRMED` → `ASSIGNED`).

        Design: Corner/calculations/hos_feasibility_check_boundary_driving_hours
        """
        ctx = setup_assigned_order(
            quote_overrides={"trip_date": "2026-09-01T06:00:00Z",
                             "return_date": "2026-09-01T17:00:00Z",
                             "estimated_miles": 500, "estimated_hours": 11})
        assert ctx["order"]["status"] == "ASSIGNED"
        assert ctx["order"]["assigned_driver_id"] == ctx["driver"]["id"]
        assert get_driver(ctx["driver"]["id"])["status"] == "ON_DUTY_NOT_DRIVING"


class TestInsuranceCertificateIssuance:
    def test_issue_requires_order_beyond_pending_deposit(self, api):
        """PRD §3.9: "Issuance is a `ComplianceOfficer` act requiring the order
        to stand in `CONFIRMED`, `ASSIGNED`, or `IN_PROGRESS`". An order still
        in `PENDING_DEPOSIT` is in none of those states — "else
        `ERR_INVALID_STATE` (HTTP 409)" (PRD §2.8 step 4).

        Design: Difficulty/cross_entity_state_dependency/insurance_cert_issue_requires_order_confirmed
        """
        ctx = setup_pending_deposit_order()
        cert = validate_success(api.request_certificate(
            create_certificate_payload(ctx["order"]["id"]),
            make_customer_headers(ctx["customer"]["id"])), 201)
        res = api.issue_certificate(cert["id"], COMPLIANCE)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_issue_on_assigned_order_sets_number_and_expiry(self, api):
        """PRD §3.9: "Issuance moves the certificate `REQUESTED` → `ISSUED`,
        stamps `issued_at`, generates a unique `certificate_number`, and fixes
        `expires_at` at the earlier of the vehicle's insurance expiry and the
        quote's `return_date`."

        Vehicle insurance_expiry 2027-01-01 vs quote return_date
        2026-09-01T16:00Z -> expires_at is the return_date.

        Design: Difficulty/cross_entity_state_dependency/insurance_cert_issue_requires_order_confirmed
        """
        ctx = setup_assigned_order()
        cert = validate_success(api.request_certificate(
            create_certificate_payload(ctx["order"]["id"]),
            make_customer_headers(ctx["customer"]["id"])), 201)
        assert cert["status"] == "REQUESTED"
        issued = validate_success(api.issue_certificate(cert["id"], COMPLIANCE))
        assert issued["status"] == "ISSUED"
        assert issued["issued_at"] is not None
        assert isinstance(issued["certificate_number"], str)
        assert len(issued["certificate_number"]) > 0
        expires_at = datetime.fromisoformat(
            issued["expires_at"].replace("Z", "+00:00"))
        assert expires_at == datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
