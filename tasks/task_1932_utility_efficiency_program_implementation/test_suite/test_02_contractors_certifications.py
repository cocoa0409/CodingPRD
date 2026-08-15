"""Contractors and certifications: initial standing, empty-zip acceptance,
terminate guard, certification expiry boundary, and the revoke cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_contractor,
    create_active_program,
    create_approved_project,
    create_contractor_payload,
    create_contractor_with_cert,
    create_customer,
    create_lead,
    create_work_order,
    distribute_lead,
    set_clock,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]


class TestContractorCreation:
    def test_contractor_create_applied_initial_state(self, api, pm_headers):
        """PRD 3.2: "New contractors land in `APPLIED` with a pristine
        `qa_score_bps` of 10,000 basis points, a `qa_window_size` of ten
        inspections, and every counter — `active_certification_count`,
        `on_time_installs`, `late_installs`, `complaint_count_90d` — at zero."

        Design: Corner/entities/contractor_create_applied_initial_state
        """
        resp = api.create_contractor(create_contractor_payload(), pm_headers)
        data = validate_success(resp, expected_status=201)
        assert_contractor(data)
        assert data["status"] == "APPLIED"
        assert data["qa_score_bps"] == 10000
        assert data["qa_window_size"] == 10
        assert data["active_certification_count"] == 0
        assert data["on_time_installs"] == 0
        assert data["late_installs"] == 0
        assert data["complaint_count_90d"] == 0

    def test_contractor_service_zip_codes_default_handling(self, api, pm_headers):
        """PRD 3.2: "the platform records the firm's `legal_name`, its state
        `license_number`, the `sector` it serves, and the `service_zip_codes`
        it covers." No minimum-population rule is stated for the ZIP list, so
        an empty list is recorded as supplied.

        Design: Corner/entities/contractor_service_zip_codes_default_handling
        """
        resp = api.create_contractor(
            create_contractor_payload(service_zip_codes=[]), pm_headers)
        data = validate_success(resp, expected_status=201)
        assert data["service_zip_codes"] == []


class TestTerminateContractorGuard:
    def test_terminate_contractor_with_open_work_orders_rejected(self, api, pm_headers):
        """PRD 3.2: "from `APPROVED` or `SUSPENDED` a contractor moves to
        `TERMINATED`, but the platform refuses with `ERR_CONTRACTOR_BUSY` while
        any of the firm's work orders remains `SCHEDULED` or `IN_PROGRESS`."

        Design: Corner/state_machines/terminate_contractor_with_open_work_orders_rejected
        """
        set_clock()
        ctx = create_approved_project()
        wo = create_work_order(ctx["project"]["id"], ctx["contractor"]["id"],
                               scheduled_on="2026-08-05T09:00:00Z")
        assert wo["status"] == "SCHEDULED"
        resp = api.terminate_contractor(ctx["contractor"]["id"], pm_headers)
        validate_error(resp, ApiErrorId.ERR_CONTRACTOR_BUSY)


class TestCertificationExpiryWindow:
    def test_certification_expired_at_exact_expires_on(self, api, pm_headers):
        """PRD 2.5: "Advancing the clock sweeps every certification whose
        `expires_on` falls at or before the new instant, moving it from
        `ACTIVE` to `EXPIRED` and applying the standing consequences described
        in §3.2 — each expiry decrements the owning contractor's
        `active_certification_count`, and when that count reaches zero on an
        `APPROVED` contractor, the contractor is automatically suspended."
        PRD 2.5: "A ProgramManager-only capability
        (`POST /efficiency/_clock/set_current_utc`) advances the clock to a
        caller-supplied instant `to_iso8601`; the response reports the
        resulting `current_utc` and a count `certifications_expired` of
        certifications swept by the advance."
        At the exact `expires_on` instant ("at or before") the certification
        is swept.

        Design: Difficulty/resource_temporal_overlap/certification_expiry_window
        """
        bundle = create_contractor_with_cert(
            approve=False,
            cert_overrides={"expires_on": "2026-08-10T00:00:00Z"})
        cert_id = bundle["certification"]["id"]
        set_clock("2026-08-01T00:00:00Z")
        clock = api.set_clock("2026-08-10T00:00:00Z", PM)
        clock_data = validate_success(clock, expected_status=200)
        assert clock_data["certifications_expired"] == 1
        cert = validate_success(api.get_certification(cert_id, pm_headers))
        assert cert["status"] == "EXPIRED"

    def test_certification_active_one_second_before_expiry(self, api, pm_headers):
        """PRD 2.5: "Advancing the clock sweeps every certification whose
        `expires_on` falls at or before the new instant, moving it from
        `ACTIVE` to `EXPIRED` and applying the standing consequences described
        in §3.2 — each expiry decrements the owning contractor's
        `active_certification_count`, and when that count reaches zero on an
        `APPROVED` contractor, the contractor is automatically suspended."
        One second before `expires_on` the instant has not been reached, so
        the certification is not swept.

        Design: Difficulty/resource_temporal_overlap/certification_expiry_window
        """
        bundle = create_contractor_with_cert(
            approve=False,
            cert_overrides={"expires_on": "2026-08-10T00:00:00Z"})
        cert_id = bundle["certification"]["id"]
        set_clock("2026-08-01T00:00:00Z")
        clock = api.set_clock("2026-08-09T23:59:59Z", PM)
        clock_data = validate_success(clock, expected_status=200)
        assert clock_data["certifications_expired"] == 0
        cert = validate_success(api.get_certification(cert_id, pm_headers))
        assert cert["status"] == "ACTIVE"


class TestCertificationRevokeCascade:
    def _setup(self, api):
        """APPROVED contractor with exactly one ACTIVE certification and one
        OFFERED lead assigned to it."""
        program = create_active_program(budget_cents=100000)
        bundle = create_contractor_with_cert()
        contractor, cert = bundle["contractor"], bundle["certification"]
        customer = create_customer()
        lead = create_lead(customer["id"], program["id"], estimated_annual_kwh_savings=500)
        offered = distribute_lead(lead["id"], lead["version"])
        assert offered["assigned_contractor_id"] == contractor["id"]
        return program, contractor, cert, offered

    def test_revoke_last_certification_suspends_contractor(self, api, pm_headers):
        """PRD 3.2: "Either ending decrements `active_certification_count`, and
        when that decrement leaves an `APPROVED` contractor with zero active
        certifications, the contractor is automatically suspended".

        Design: Difficulty/transitive_cascade/certification_revoke_cascades_to_suspension
        """
        _program, contractor, cert, _offered = self._setup(api)
        resp = api.revoke_certification(cert["id"], pm_headers)
        revoked = validate_success(resp, expected_status=200)
        assert revoked["status"] == "REVOKED"
        after = validate_success(api.get_contractor(contractor["id"], pm_headers))
        assert after["active_certification_count"] == 0
        assert after["status"] == "SUSPENDED"

    def test_revoke_cascade_expires_offered_lead(self, api, pm_headers):
        """PRD 3.2: "an automatic suspension carries exactly the consequences
        of a manual one, described below" and "Suspension moves a contractor
        `APPROVED` → `SUSPENDED`: the firm is excluded from future lead
        distribution, and every `OFFERED` lead currently assigned to it
        automatically expires (`OFFERED` → `EXPIRED`), clearing the lead's
        `assigned_contractor_id`."

        Design: Difficulty/transitive_cascade/certification_revoke_cascades_to_suspension
        """
        _program, contractor, cert, offered = self._setup(api)
        validate_success(api.revoke_certification(cert["id"], pm_headers), 200)
        lead_after = validate_success(api.get_lead(offered["id"], pm_headers))
        assert lead_after["status"] == "EXPIRED"
        assert lead_after["assigned_contractor_id"] is None
