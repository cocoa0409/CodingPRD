"""Import entry lifecycle, prior-notice lead-time window, supplier-approval
gating, and optimistic concurrency on evaluations."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_approved_supplier,
    create_entry,
    create_import_entry_payload,
    create_released_entry,
    create_supplier,
    create_supplier_evaluation_payload,
    get_success_data,
    make_compliance_manager_headers,
    validate_error,
    validate_success,
)

CM = TEST_USERS["compliance_manager_headers"]
IC = TEST_USERS["import_coordinator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


class TestEntryCreation:
    def test_entry_initial_state_draft(self, api):
        """PRD: "The entry starts in `DRAFT` status with `prior_notice_filed_at`,
        `prior_notice_confirmation`, and `entry_filed_at` all null."

        Design: Corner/state_machines/entry_initial_state_draft
        """
        supplier = create_approved_supplier(frn="FRN-S01")
        entry = validate_success(api.create_import_entry(
            create_import_entry_payload(
                supplier_id=supplier["id"], entry_number="E-S01",
                species_declared="TUNA", transport_mode="VESSEL",
                scheduled_arrival="2026-08-10T00:00:00Z", port_code="USLAX",
                goods_value_cents=1000, freight_cost_cents=0,
                duty_rate_pct=0.0, total_weight_kg=10),
            IC), 201)
        assert entry["status"] == "DRAFT"
        assert entry["prior_notice_filed_at"] is None
        assert entry["prior_notice_confirmation"] is None
        assert entry["entry_filed_at"] is None
        assert entry["duty_cents"] is None
        assert entry["allocatable_total_cents"] is None
        assert entry["version"] == 1

    def test_entry_invalid_enum_rejected(self, api):
        """PRD: "`transport_mode` (one of `VESSEL`, `AIR`, `ROAD`)" — a value
        outside the enum is a field-level validation failure:
        ERR_VALIDATION_FAILED (HTTP 400).

        Design: Corner/entities/entry_invalid_enum_rejected
        """
        supplier = create_approved_supplier(frn="FRN-C03")
        resp = api.create_import_entry(
            create_import_entry_payload(
                supplier_id=supplier["id"], entry_number="E-C03",
                species_declared="TUNA", transport_mode="TRUCK",
                scheduled_arrival="2026-08-10T00:00:00Z", port_code="USLAX",
                goods_value_cents=1000, freight_cost_cents=0,
                duty_rate_pct=0.0, total_weight_kg=10),
            IC)
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED)


class TestEntryTerminalLockdown:
    def test_refused_entry_terminal_lockdown(self, api):
        """PRD: "`REFUSED` and `RELEASED` are terminal states for the entry."
        A subsequent disposition attempt against REFUSED targets no valid
        from-state and is rejected ERR_INVALID_STATE (HTTP 409).

        Design: Corner/state_machines/refused_entry_terminal_lockdown
        """
        supplier = create_approved_supplier(frn="FRN-S02")
        entry = create_entry(supplier["id"], entry_number="E-S02",
                             species="TUNA", transport_mode="VESSEL",
                             goods_value_cents=1000, freight_cost_cents=0,
                             total_weight_kg=10)
        get_success_data(api.file_prior_notice(entry["id"], IC))
        get_success_data(api.file_entry(entry["id"], IC))
        refused = get_success_data(api.fda_disposition(entry["id"], "REFUSED",
                                                       IC))
        assert refused["status"] == "REFUSED"

        resp = api.fda_disposition(entry["id"], "RELEASED", IC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_import_entry(entry["id"], IC))
        assert after["status"] == "REFUSED"
        assert after["duty_cents"] is None


class TestPriorNoticeWindow:
    def test_prior_notice_deadline_boundary(self, api):
        """PRD: "the current logical time must not be later than
        `scheduled_arrival` minus the lead time for the entry's
        `transport_mode`: 8 hours for `VESSEL`, 4 hours for `AIR`, 2 hours for
        `ROAD`. Equality passes — filing exactly at the deadline is allowed. A
        missed window is rejected with `ERR_PRIOR_NOTICE_WINDOW_MISSED`
        (HTTP 422)."
        PRD: "The startup default — before any call — is exactly
        2026-08-01T00:00:00Z."

        Design: Corner/validations/prior_notice_deadline_boundary
        """
        supplier = create_approved_supplier(name="Boundary Foods", country="PE",
                                            frn="FRN-V02")
        # Arrival 2026-08-01T08:00Z by VESSEL -> deadline 2026-08-01T00:00Z,
        # exactly the default logical clock.
        entry_a = create_entry(supplier["id"], entry_number="E-V02A",
                               species="SHRIMP", transport_mode="VESSEL",
                               scheduled_arrival="2026-08-01T08:00:00Z",
                               goods_value_cents=1000, freight_cost_cents=0,
                               total_weight_kg=10)
        entry_b = create_entry(supplier["id"], entry_number="E-V02B",
                               species="SHRIMP", transport_mode="VESSEL",
                               scheduled_arrival="2026-08-01T08:00:00Z",
                               goods_value_cents=1000, freight_cost_cents=0,
                               total_weight_kg=10)

        # Exactly at the deadline: equality passes.
        filed = validate_success(api.file_prior_notice(entry_a["id"], IC))
        assert filed["status"] == "PRIOR_NOTICE_FILED"

        # One minute past the deadline: window missed.
        validate_success(api.set_clock("2026-08-01T00:01:00Z", ADMIN))
        resp = api.file_prior_notice(entry_b["id"], IC)
        validate_error(resp, ApiErrorId.ERR_PRIOR_NOTICE_WINDOW_MISSED)
        after = validate_success(api.get_import_entry(entry_b["id"], IC))
        assert after["status"] == "DRAFT"


class TestEntryFilingRequiresSupplierApproved:
    def test_file_prior_notice_blocked_when_supplier_suspended(self, api):
        """PRD: "the referenced supplier must currently have `fsvp_status` equal
        to `APPROVED` (checked at the time of the call — a supplier suspended
        between entry creation and prior-notice filing blocks the operation
        with `ERR_SUPPLIER_NOT_APPROVED`, HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/entry_filing_requires_supplier_approved
        """
        supplier = create_approved_supplier(name="Southern Seas", country="AR",
                                            frn="FRN-8001")
        entry = create_entry(supplier["id"], entry_number="E-8001",
                             species="SHRIMP", transport_mode="VESSEL",
                             goods_value_cents=300000, freight_cost_cents=12000,
                             total_weight_kg=60)
        get_success_data(api.suspend_supplier(supplier["id"], CM))

        resp = api.file_prior_notice(entry["id"], IC)
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_APPROVED)
        after = validate_success(api.get_import_entry(entry["id"], IC))
        assert after["status"] == "DRAFT"

    def test_file_entry_rechecks_supplier_approval(self, api):
        """PRD: "Supplier approval is re-checked at this point: if the supplier
        has been suspended between prior notice and entry filing, the operation
        is rejected with `ERR_SUPPLIER_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/entry_filing_requires_supplier_approved
        """
        supplier = create_approved_supplier(name="Southern Seas", country="AR",
                                            frn="FRN-8001B")
        entry = create_entry(supplier["id"], entry_number="E-8001B",
                             species="SHRIMP", transport_mode="VESSEL",
                             goods_value_cents=300000, freight_cost_cents=12000,
                             total_weight_kg=60)
        get_success_data(api.file_prior_notice(entry["id"], IC))
        get_success_data(api.suspend_supplier(supplier["id"], CM))

        resp = api.file_entry(entry["id"], IC)
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_APPROVED)
        after = validate_success(api.get_import_entry(entry["id"], IC))
        assert after["status"] == "PRIOR_NOTICE_FILED"


class TestOccOnSupplierEvaluation:
    def test_occ_stale_version_on_evaluation_rejected(self, api):
        """PRD: "**Creating a SupplierEvaluation** requires
        `expected_supplier_version` in the request payload, carrying the
        client's last observed `version` of the ForeignSupplier. If the
        supplier's current `version` does not match, the request is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_evaluation
        """
        supplier = create_approved_supplier(name="Southern Seas", country="AR",
                                            frn="FRN-X02")
        pre_suspend = validate_success(api.get_supplier(supplier["id"], CM))
        stale_version = pre_suspend["version"]
        # Suspend bumps the supplier version, making the observed value stale.
        get_success_data(api.suspend_supplier(supplier["id"], CM))

        resp = api.create_supplier_evaluation(
            create_supplier_evaluation_payload(
                supplier_id=supplier["id"],
                expected_supplier_version=stale_version,
                period_start="2025-01-01T00:00:00Z",
                period_end="2025-12-31T00:00:00Z",
                hazard_analysis_score=80, record_review_score=80,
                performance_score=80),
            CM)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_occ_fresh_version_reinstates_suspended_supplier(self, api):
        """PRD: "From `SUSPENDED`, an `APPROVED` outcome (score 70 or above)
        restores the supplier to `APPROVED` with the full date and risk
        recomputation."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_evaluation
        """
        supplier = create_approved_supplier(name="Southern Seas", country="AR",
                                            frn="FRN-X02")
        get_success_data(api.suspend_supplier(supplier["id"], CM))
        current = validate_success(api.get_supplier(supplier["id"], CM))
        assert current["fsvp_status"] == "SUSPENDED"

        ev = validate_success(api.create_supplier_evaluation(
            create_supplier_evaluation_payload(
                supplier_id=supplier["id"],
                expected_supplier_version=current["version"],
                period_start="2025-01-01T00:00:00Z",
                period_end="2025-12-31T00:00:00Z",
                hazard_analysis_score=80, record_review_score=80,
                performance_score=80),
            CM), 201)
        assert ev["outcome"] == "APPROVED"
        restored = validate_success(api.get_supplier(supplier["id"], CM))
        assert restored["fsvp_status"] == "APPROVED"
