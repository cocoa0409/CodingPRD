"""Validation priority conflicts, cross-entity state preconditions, temporal
overlap semantics, and isolated business-constraint error paths.

Covers Difficulty queue rules priority_pair_validation_conflict,
cross_entity_state_dependency, resource_temporal_overlap, and several Corner
validations instances.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    TEST_USERS, make_officer_headers,
    fixtures as fx,
)

CARE = TEST_USERS["customer_care_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
ELIG = TEST_USERS["eligibility_worker_headers"]
NOC = TEST_USERS["noc_operator_headers"]
BILLING = TEST_USERS["billing_headers"]
ANY_READER = TEST_USERS["program_admin_headers"]


# =====================================================================
# Rule 5 — priority_pair_validation_conflict / state_beats_fiscal_on_resubmit
# =====================================================================
class TestStateBeatsFiscalOnResubmit:
    def _submitted_claim_exhausting_funds(self, api):
        grant = fx.create_grant(api, award_amount_cents=1000)
        g_v = grant["version"]
        ctx = fx.setup_active_subscription(api, grant=grant, homes_passed=100, price=6000)
        subsidy = fx.create_subsidy_program(api, monthly_discount_cents=3000)
        fx.create_active_enrollment(api, ctx["subscriber"]["id"], subsidy["id"],
                                    household_size=2, annual_income_cents=3_000_000)
        claim = fx.create_claim(api, grant["id"], [ctx["area"]["id"]], g_v)
        fx.submit_claim(api, claim["id"], analyst_user_id="analyst-1")
        return claim

    def test_resubmit_submitted_claim_reports_invalid_state(self, api):
        """PRD §2.5: "(4) whether the target resource is in a state that permits the
        requested transition, failing with `ERR_INVALID_STATE`; ... and (10) fiscal
        sufficiency."
        PRD §3.7: "Submission moves the claim `DRAFT` to `SUBMITTED`"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_resubmit
        """
        claim = self._submitted_claim_exhausting_funds(api)
        # Claim is SUBMITTED (state, priority 4) and would also exceed available=0
        # (fiscal, priority 10); the higher-priority state failure surfaces.
        validate_error(api.submit_grant_claim(claim["id"], TEST_USERS["compliance_analyst_headers"]),
                       ApiErrorId.ERR_INVALID_STATE)

    def test_resubmit_leaves_claim_submitted(self, api):
        """PRD §2.5: "All validations are evaluated in a fixed priority order, so that
        a request failing several checks always surfaces the highest-priority failure."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_resubmit
        """
        claim = self._submitted_claim_exhausting_funds(api)
        validate_error(api.submit_grant_claim(claim["id"], TEST_USERS["compliance_analyst_headers"]),
                       ApiErrorId.ERR_INVALID_STATE)
        fetched = validate_success(api.get_grant_claim(claim["id"], ANY_READER))
        assert fetched["status"] == "SUBMITTED"


# =====================================================================
# Rule 5 — priority_pair_validation_conflict / referential_beats_temporal_on_install_create
# =====================================================================
class TestReferentialBeatsTemporalOnInstall:
    def _inactive_tech_with_overlap(self, api):
        grant = fx.create_grant(api)
        area = fx.create_serviceable_area(api, grant["id"], homes_passed=100)
        plan = fx.create_plan(api)
        s1 = fx.create_subscriber(api, area["id"], full_name="S1", email="s1@x.com", service_address="1 A St")
        sub1 = fx.create_pending_subscription(api, s1["id"], plan["id"], area["id"])
        s2 = fx.create_subscriber(api, area["id"], full_name="S2", email="s2@x.com", service_address="2 A St")
        sub2 = fx.create_pending_subscription(api, s2["id"], plan["id"], area["id"])
        tech = fx.create_technician(api, job_duration_minutes=120)
        fx.schedule_install(api, sub1["id"], tech["id"], "2026-06-02T09:00:00Z")
        validate_success(api.deactivate_technician(tech["id"], ANY_READER))
        return sub2, tech

    def test_inactive_technician_wins_over_double_booked(self, api):
        """PRD §2.5: "(6) business-referential preconditions; ... (8) temporal-window
        constraints"
        PRD §3.3: "Scheduling requires the technician's `status` to be `AVAILABLE`,
        failing otherwise with `ERR_TECHNICIAN_INACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_install_create
        """
        sub2, tech = self._inactive_tech_with_overlap(api)
        # Window 10:00 overlaps the 09:00-11:00 order AND the technician is INACTIVE;
        # the higher-priority referential failure surfaces.
        validate_error(
            api.create_install_order(
                {"subscription_id": sub2["id"], "technician_id": tech["id"],
                 "scheduled_start_at": "2026-06-02T10:00:00Z"}, DISPATCH),
            ApiErrorId.ERR_TECHNICIAN_INACTIVE)

    def test_rejected_install_creates_no_order(self, api):
        """PRD §3.3: "Scheduling requires the technician's `status` to be `AVAILABLE`,
        failing otherwise with `ERR_TECHNICIAN_INACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_install_create
        """
        sub2, tech = self._inactive_tech_with_overlap(api)
        validate_error(
            api.create_install_order(
                {"subscription_id": sub2["id"], "technician_id": tech["id"],
                 "scheduled_start_at": "2026-06-02T10:00:00Z"}, DISPATCH),
            ApiErrorId.ERR_TECHNICIAN_INACTIVE)
        _, meta = validate_paginated(
            api.list_install_orders(ANY_READER, params={"subscription_id": sub2["id"]}))
        assert meta["total_count"] == 0, "the rejected install must not persist an order"


# =====================================================================
# Rule 7 — cross_entity_state_dependency / subscription_activate_requires_completed_install
# =====================================================================
class TestActivateRequiresCompletedInstall:
    def _pending_with_scheduled_install(self, api):
        grant = fx.create_grant(api)
        area = fx.create_serviceable_area(api, grant["id"], homes_passed=100)
        plan = fx.create_plan(api)
        subscriber = fx.create_subscriber(api, area["id"])
        subscription = fx.create_pending_subscription(api, subscriber["id"], plan["id"], area["id"])
        tech = fx.create_technician(api)
        fx.schedule_install(api, subscription["id"], tech["id"], "2026-06-01T09:00:00Z")
        return subscription

    def test_activate_without_completed_install_rejected(self, api):
        """PRD §3.2: "Activation moves `PENDING_INSTALL` to `ACTIVE` and is permitted
        only when an install order for this subscription has reached `COMPLETED`
        (otherwise `ERR_INSTALL_NOT_COMPLETED`) and the subscription's area is
        `SERVICEABLE`"

        Design: Difficulty/cross_entity_state_dependency/subscription_activate_requires_completed_install
        """
        subscription = self._pending_with_scheduled_install(api)
        validate_error(api.activate_subscription(subscription["id"], CARE),
                       ApiErrorId.ERR_INSTALL_NOT_COMPLETED)

    def test_subscription_stays_pending_install(self, api):
        """PRD §3.2: "Activation moves `PENDING_INSTALL` to `ACTIVE` and is permitted
        only when an install order for this subscription has reached `COMPLETED`
        (otherwise `ERR_INSTALL_NOT_COMPLETED`)"

        Design: Difficulty/cross_entity_state_dependency/subscription_activate_requires_completed_install
        """
        subscription = self._pending_with_scheduled_install(api)
        validate_error(api.activate_subscription(subscription["id"], CARE),
                       ApiErrorId.ERR_INSTALL_NOT_COMPLETED)
        fetched = validate_success(api.get_subscription(subscription["id"], ANY_READER))
        assert fetched["service_status"] == "PENDING_INSTALL"


# =====================================================================
# Rule 7 — cross_entity_state_dependency / claim_submit_requires_serviceable_area
# =====================================================================
class TestClaimSubmitRequiresServiceableArea:
    def _draft_claim_over_construction_area(self, api):
        grant = fx.create_grant(api)
        g_v = grant["version"]
        area = fx.create_area(api, grant["id"], homes_passed=100, fiber_ready=True)
        validate_success(api.advance_service_area(area["id"], ANY_READER))  # -> CONSTRUCTION only
        claim = fx.create_claim(api, grant["id"], [area["id"]], g_v)
        return claim

    def test_submit_with_non_serviceable_area_rejected(self, api):
        """PRD §3.7: "Submission requires that every area in `service_area_ids` be
        `SERVICEABLE` (otherwise `ERR_AREA_NOT_SERVICEABLE`)"

        Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_serviceable_area
        """
        claim = self._draft_claim_over_construction_area(api)
        validate_error(api.submit_grant_claim(claim["id"], TEST_USERS["compliance_analyst_headers"]),
                       ApiErrorId.ERR_AREA_NOT_SERVICEABLE)

    def test_claim_stays_draft(self, api):
        """PRD §3.7: "a new claim begins `DRAFT`."
        PRD §3.7: "Submission requires that every area in `service_area_ids` be
        `SERVICEABLE` (otherwise `ERR_AREA_NOT_SERVICEABLE`)"

        Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_serviceable_area
        """
        claim = self._draft_claim_over_construction_area(api)
        validate_error(api.submit_grant_claim(claim["id"], TEST_USERS["compliance_analyst_headers"]),
                       ApiErrorId.ERR_AREA_NOT_SERVICEABLE)
        fetched = validate_success(api.get_grant_claim(claim["id"], ANY_READER))
        assert fetched["status"] == "DRAFT"


# =====================================================================
# Rule 8 — resource_temporal_overlap / technician_double_booked_halfopen
# =====================================================================
class TestTechnicianDoubleBookedHalfOpen:
    def _tech_with_9_to_11_install(self, api):
        grant = fx.create_grant(api)
        area = fx.create_serviceable_area(api, grant["id"], homes_passed=100)
        plan = fx.create_plan(api)
        s1 = fx.create_subscriber(api, area["id"], full_name="S1", email="s1@x.com", service_address="1 A St")
        sub1 = fx.create_pending_subscription(api, s1["id"], plan["id"], area["id"])
        s2 = fx.create_subscriber(api, area["id"], full_name="S2", email="s2@x.com", service_address="2 A St")
        sub2 = fx.create_pending_subscription(api, s2["id"], plan["id"], area["id"])
        tech = fx.create_technician(api, job_duration_minutes=120)
        fx.schedule_install(api, sub1["id"], tech["id"], "2026-06-02T09:00:00Z")
        return sub2, tech

    def test_overlapping_window_rejected(self, api):
        """PRD §3.3: "The proposed window must not overlap any other `SCHEDULED`
        install for the same technician; overlap is judged on half-open intervals
        `[start, end)`, so an install that begins exactly when another ends is allowed,
        and a genuine overlap is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/technician_double_booked_halfopen
        """
        sub2, tech = self._tech_with_9_to_11_install(api)
        validate_error(
            api.create_install_order(
                {"subscription_id": sub2["id"], "technician_id": tech["id"],
                 "scheduled_start_at": "2026-06-02T10:00:00Z"}, DISPATCH),
            ApiErrorId.ERR_TECHNICIAN_DOUBLE_BOOKED)

    def test_adjacent_window_allowed(self, api):
        """PRD §3.3: "overlap is judged on half-open intervals `[start, end)`, so an
        install that begins exactly when another ends is allowed, and a genuine
        overlap is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/technician_double_booked_halfopen
        """
        sub2, tech = self._tech_with_9_to_11_install(api)
        # 11:00 == end of the 09:00-11:00 order; adjacency is allowed.
        created = validate_success(
            api.create_install_order(
                {"subscription_id": sub2["id"], "technician_id": tech["id"],
                 "scheduled_start_at": "2026-06-02T11:00:00Z"}, DISPATCH),
            expected_status=201)
        assert created["status"] == "SCHEDULED"


# =====================================================================
# Rule 8 — resource_temporal_overlap / outage_buffer_overlap_closed
# =====================================================================
class TestOutageBufferOverlapClosed:
    def _area_with_open_outage(self, api):
        grant = fx.create_grant(api)
        area = fx.create_serviceable_area(api, grant["id"], homes_passed=100)
        fx.report_outage(api, area["id"], "2026-06-01T00:00:00Z", severity="PARTIAL")
        return area

    def test_second_outage_within_buffer_rejected(self, api):
        """PRD §3.6: "a new outage must not fall within 60 minutes of an existing
        `OPEN` outage on the same area, where the window is the existing outage's
        interval extended by that buffer on each side, failing otherwise with
        `ERR_OUTAGE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/outage_buffer_overlap_closed
        """
        area = self._area_with_open_outage(api)
        validate_error(
            api.report_outage(
                {"service_area_id": area["id"], "started_at": "2026-06-01T00:30:00Z",
                 "severity": "PARTIAL"}, NOC),
            ApiErrorId.ERR_OUTAGE_OVERLAP)

    def test_rejected_outage_not_persisted(self, api):
        """PRD §3.6: "a new outage must not fall within 60 minutes of an existing
        `OPEN` outage on the same area ... failing otherwise with `ERR_OUTAGE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/outage_buffer_overlap_closed
        """
        area = self._area_with_open_outage(api)
        validate_error(
            api.report_outage(
                {"service_area_id": area["id"], "started_at": "2026-06-01T00:30:00Z",
                 "severity": "PARTIAL"}, NOC),
            ApiErrorId.ERR_OUTAGE_OVERLAP)
        _, meta = validate_paginated(api.list_outages(ANY_READER, params={"service_area_id": area["id"]}))
        assert meta["total_count"] == 1, "only the original OPEN outage should exist"


# =====================================================================
# Corner — validations
# =====================================================================
def test_duplicate_active_enrollment_rejected(api):
    """PRD §3.4: "An eligible verification also requires that the subscriber have no
    other `ACTIVE` enrollment, failing otherwise with `ERR_DUPLICATE_ACTIVE_ENROLLMENT`"

    Design: Corner/validations/duplicate_active_enrollment_rejected
    """
    grant = fx.create_grant(api)
    area = fx.create_area(api, grant["id"], homes_passed=100)
    subsidy = fx.create_subsidy_program(api)
    subscriber = fx.create_subscriber(api, area["id"])
    fx.create_active_enrollment(api, subscriber["id"], subsidy["id"],
                                household_size=2, annual_income_cents=3_000_000)
    e2 = fx.create_enrollment(api, subscriber["id"], subsidy["id"],
                              household_size=2, annual_income_cents=3_000_000)
    validate_error(api.verify_enrollment(e2["id"], ELIG), ApiErrorId.ERR_DUPLICATE_ACTIVE_ENROLLMENT)


def test_device_assign_when_already_assigned_rejected(api):
    """PRD §3.3: "Assignment requires the device to be `IN_STOCK` and exactly one of
    `subscription_id` or `enrollment_id` to be supplied — neither zero nor both —
    failing otherwise with `ERR_DEVICE_NOT_AVAILABLE`"

    Design: Corner/validations/device_assign_not_available_rejected
    """
    grant = fx.create_grant(api)
    area = fx.create_serviceable_area(api, grant["id"], homes_passed=100)
    plan = fx.create_plan(api)
    subscriber = fx.create_subscriber(api, area["id"])
    subscription = fx.create_pending_subscription(api, subscriber["id"], plan["id"], area["id"])
    device = fx.create_device(api, serial_number="SN-1")
    validate_success(api.assign_device(device["id"], {"subscription_id": subscription["id"]}, DISPATCH))
    validate_error(api.assign_device(device["id"], {"subscription_id": subscription["id"]}, DISPATCH),
                   ApiErrorId.ERR_DEVICE_NOT_AVAILABLE)


def test_payment_on_void_invoice_rejected(api):
    """PRD §3.5: "a payment against a `PAID` or `VOID` invoice is rejected with
    `ERR_INVOICE_NOT_PAYABLE`."
    PRD §3.2: "Cancelling from `PENDING_INSTALL` additionally cancels any `SCHEDULED`
    install order (with the compensating device unassignment) and voids any `ISSUED`
    invoice while reversing any applied SLA credit"

    Design: Corner/validations/payment_on_void_invoice_rejected
    """
    ctx = fx.setup_active_subscription(api, homes_passed=100, price=6000)
    invoice = fx.generate_invoice(api, ctx["subscription"]["id"])
    validate_success(api.cancel_subscription(ctx["subscription"]["id"], CARE))
    voided = validate_success(api.get_invoice(invoice["id"], ANY_READER))
    assert voided["status"] == "VOID"
    # Pay with the invoice's CURRENT version so the OCC check passes and the
    # not-payable state is the only check that can fail.
    validate_error(
        api.record_payment(invoice["id"],
                           {"amount_cents": 1000, "expected_invoice_version": voided["version"]},
                           BILLING),
        ApiErrorId.ERR_INVOICE_NOT_PAYABLE)


def test_invoice_period_end_before_start_rejected(api):
    """PRD §3.5: "`period_end` must be strictly later than `period_start`, failing
    otherwise with `ERR_PERIOD_INVALID`."

    Design: Corner/validations/invoice_period_end_before_start_rejected
    """
    ctx = fx.setup_active_subscription(api, homes_passed=100, price=6000)
    validate_error(
        api.generate_invoice(ctx["subscription"]["id"],
                             {"period_start": "2026-07-01T00:00:00Z", "period_end": "2026-06-01T00:00:00Z"},
                             BILLING),
        ApiErrorId.ERR_PERIOD_INVALID)
