"""RBAC and ownership claims (PRD §2.1, §3.3, §3.5, §4)."""
from test_helpers import (
    ADMIN,
    AUDITOR,
    BILLING,
    SCHED,
    ApiErrorId,
    all_tefra_steps_true,
    build_user_headers,
    create_case,
    create_crna,
    create_fee_schedule,
    create_physician,
    create_published_roster,
    create_provider,
    create_roster,
    create_site,
    get_success_data,
    make_crna_headers,
    make_physician_headers,
    propose_assignment,
    setup_site_fee_roster,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)


class TestRoleDeny:
    def test_scheduler_cannot_manage_providers(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted for the
        target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP
        403)."
        PRD §2.1: "`GroupAdministrator` — the group's business-office
        administrator. Owns configuration (sites, providers, fee schedules,
        stipend agreements), credential maintenance, stipend-entry voids, and
        the logical clock." (provider registration is GroupAdministrator-only
        per the §4 endpoint table; Scheduler is not listed there).

        Design: Corner/rbac/scheduler_cannot_manage_providers
        """
        resp = api.create_provider(
            {"full_name": "Crna One", "provider_type": "CRNA",
             "npi": "1000000003", "credential_expires_on": "2027-01-31",
             "dea_expires_on": "2027-01-31"}, SCHED)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        _, meta = validate_paginated(api.list_providers(ADMIN))
        assert meta["total_count"] == 0

    def test_crna_cannot_create_roster(self, api):
        """PRD §2.1: "`CRNA` — a certified registered nurse anesthetist member
        of the group. Accepts or declines the CRNA's own assignments." (the §4
        endpoint table lists roster creation under Scheduler only).
        PRD §2.1: "A request whose role is valid but not permitted for the
        target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP
        403)."

        Design: Corner/rbac/crna_cannot_create_roster
        """
        site = create_site()
        provider = create_crna("Crna One")
        resp = api.create_roster(
            {"site_id": site["id"], "service_date": "2026-08-10",
             "required_primary_slots": 1, "scheduled_day_end_minute": 1020},
            make_crna_headers(provider["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_billing_specialist_cannot_run_audit(self, api):
        """PRD §2.1: "`ComplianceAuditor` — an independent compliance
        reviewer. Runs roster audits, resolves or dismisses findings, and
        closes audits." (the §4 endpoint table lists audit scans under
        ComplianceAuditor only; BillingSpecialist is not listed there).
        PRD §2.1: "A request whose role is valid but not permitted for the
        target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP
        403)."

        Design: Corner/rbac/billing_specialist_cannot_run_audit
        """
        site = create_site()
        roster = create_roster(site["id"], required_primary_slots=0,
                               scheduled_day_end_minute=1020)
        resp = api.run_audit_scan({"roster_id": roster["id"]}, BILLING)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_compliance_auditor_cannot_void_stipend_entry(self, api):
        """PRD §2.1: "`GroupAdministrator` — the group's business-office
        administrator. Owns configuration (sites, providers, fee schedules,
        stipend agreements), credential maintenance, stipend-entry voids, and
        the logical clock." (stipend-entry voids are GroupAdministrator-only).
        PRD §2.8: role authorization (layer 2) precedes existence (layer 4):
        "**Role authorization** — a valid role not listed for the endpoint
        yields `ERR_INSUFFICIENT_PERMISSIONS`." and "**Existence** — path
        identifiers are validated left to right".

        Design: Corner/rbac/compliance_auditor_cannot_void_stipend_entry
        """
        resp = api.void_stipend_entry(
            "00000000-0000-4000-8000-000000000000", AUDITOR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert resp.status_code == 403, "authorization precedes existence (not 404)"

    def test_crna_cannot_read_stipend_entries(self, api):
        """PRD §2.1: "CRNAs cannot see stipend-ledger endpoints."
        PRD §2.1: "A request whose role is valid but not permitted for the
        target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP
        403)."

        Design: Corner/rbac/crna_cannot_read_stipend_entries
        """
        provider = create_crna("Crna One")
        resp = api.list_stipend_entries(
            make_crna_headers(provider["id"]),
            params={"provider_id": provider["id"]})
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_group_admin_cannot_submit_attestation(self, api):
        """PRD §3.5: "Submission is the physician's own act — the caller's
        `X-User-ID` must equal the attestation's `physician_id`, else
        `ERR_OWNERSHIP_MISMATCH`".
        PRD §2.1: "A request whose role is valid but not permitted for the
        target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP
        403)." (the §4 endpoint table lists attestation submission under
        AttendingAnesthesiologist only; GroupAdministrator is not listed
        there).

        Design: Corner/rbac/group_admin_cannot_submit_attestation
        """
        site, fee, roster = setup_site_fee_roster(required_primary_slots=0,
                                                  scheduled_day_end_minute=1020)
        director = create_physician("Dr. Direct")
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        att = get_success_data(api.create_attestation(
            {"case_id": case["id"], "physician_id": director["id"]}, SCHED))
        resp = api.submit_attestation(att["id"], all_tefra_steps_true(), ADMIN)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        after = get_success_data(api.get_attestation(att["id"], SCHED))
        assert after["status"] == "IN_PROGRESS"


class TestOwnership:
    def test_accept_assignment_by_other_provider_forbidden(self, api):
        """PRD §3.3: "Acceptance — permitted to `AttendingAnesthesiologist`
        and `CRNA` actors whose `X-User-ID` equals the assignment's
        `provider_id`, with mismatches rejected as `ERR_OWNERSHIP_MISMATCH`".

        Design: Corner/rbac/accept_assignment_by_other_provider_forbidden
        """
        site, fee, roster = setup_site_fee_roster(scheduled_day_end_minute=1200)
        p1 = create_crna("Crna One")
        p2 = create_crna("Crna Two")
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        assignment = propose_assignment(case["id"], p1["id"], "CASE_PRIMARY")
        resp = api.accept_assignment(assignment["id"],
                                     make_crna_headers(p2["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
        after = get_success_data(api.get_assignment(assignment["id"], SCHED))
        assert after["status"] == "PROPOSED"

    def test_physician_self_attestation_create_allowed(self, api):
        """PRD §3.5: "Either a `Scheduler` or the physician personally may
        create it; when an `AttendingAnesthesiologist` creates it, the
        `physician_id` must equal the caller's `X-User-ID`, else
        `ERR_OWNERSHIP_MISMATCH`."

        Design: Corner/rbac/physician_self_attestation_create_allowed_other_forbidden
        """
        site, fee, roster = setup_site_fee_roster(required_primary_slots=0,
                                                  scheduled_day_end_minute=1020)
        director = create_physician("Dr. Direct")
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        resp = api.create_attestation(
            {"case_id": case["id"], "physician_id": director["id"]},
            make_physician_headers(director["id"]))
        created = validate_success(resp, expected_status=201)
        assert created["status"] == "IN_PROGRESS"

    def test_physician_creating_for_colleague_forbidden(self, api):
        """PRD §3.5: "when an `AttendingAnesthesiologist` creates it, the
        `physician_id` must equal the caller's `X-User-ID`, else
        `ERR_OWNERSHIP_MISMATCH`."

        Design: Corner/rbac/physician_self_attestation_create_allowed_other_forbidden
        """
        site, fee, roster = setup_site_fee_roster(required_primary_slots=0,
                                                  scheduled_day_end_minute=1020)
        director = create_physician("Dr. Direct")
        peer = create_physician("Dr. Peer")
        case = create_case(roster["id"], scheduled_start_minute=660,
                           scheduled_end_minute=720)
        resp = api.create_attestation(
            {"case_id": case["id"], "physician_id": peer["id"]},
            make_physician_headers(director["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
