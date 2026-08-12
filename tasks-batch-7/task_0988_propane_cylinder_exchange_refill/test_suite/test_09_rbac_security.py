"""Authentication, role authorization, and segregation of duties (PRD §2.1, §2.7, §3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    balanced_session,
    count_session,
    create_cylinder_payload,
    create_driver,
    create_priced_site,
    create_site,
    create_statement,
    create_technician,
    create_technician_payload,
    dispatch_run,
    finalize_statement,
    make_admin_headers,
    make_driver_headers,
    make_host_site_manager_headers,
    make_technician_headers,
    open_session,
    record_certification,
    register_fleet_cylinders,
    report_leak,
    setup_dispatch_scenario,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK1 = TEST_USERS["site_clerk_headers"]
OFFICER1 = TEST_USERS["compliance_officer_headers"]


class TestAuthentication:
    def test_exchange_create_missing_auth_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED`."
        PRD §2.7 (stage 1): "The `X-User-Role` and `X-User-ID` headers are present and the role is one of the six declared roles; otherwise `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/exchange_create_missing_auth_returns_401
        """
        res = api.create_exchange_order({"site_id": "00000000-0000-0000-0000-000000000000"},
                                        headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRoleAuthorization:
    def test_driver_cannot_create_site(self, api):
        """PRD §4: POST `/sites` is authorized for `PlatformAdmin` only ("| POST | `/sites` | Create a host site | PlatformAdmin |").
        PRD §2.7 (stage 2): "The role is permitted for the endpoint and ownership rules hold — a driver acts only on their own runs, a host-site manager only on their own site, a clerk never registers a fleet cylinder, and a technician's `cert_level` gates the hydrostatic method and condemn requests; otherwise `ERR_FORBIDDEN`."

        Design: Corner/rbac/driver_cannot_create_site
        """
        driver = create_driver(name="RBAC Driver")
        res = api.create_site(
            {"name": "X", "cage_capacity_cylinders": 20, "par_level_full": 12,
             "commission_rate_bps": 1000},
            make_driver_headers(driver["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_clerk_cannot_confirm_leak(self, api):
        """PRD §4: leak confirmation is authorized for `ComplianceOfficer` only ("| POST | `/leak-reports/{reportId}/confirm` | Confirm a leak; `MAJOR` or cage-quarantine recommendation engages the quarantine cascade | ComplianceOfficer |").
        PRD §2.7 (stage 2): "The role is permitted for the endpoint and ownership rules hold — a driver acts only on their own runs, a host-site manager only on their own site, a clerk never registers a fleet cylinder, and a technician's `cert_level` gates the hydrostatic method and condemn requests; otherwise `ERR_FORBIDDEN`."

        Design: Corner/rbac/clerk_cannot_confirm_leak
        """
        site = create_site(name="Confirm Gate Site")
        leak = report_leak(site["id"], CLERK1, severity="MINOR")
        res = api.confirm_leak_report(leak["id"], CLERK1)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_host_manager_cannot_finalize_statement(self, api):
        """PRD §4: finalization is authorized for `PlatformAdmin` only ("| POST | `/commission-statements/{statementId}/finalize` | Finalize: computes the settlement; requires a closed, fully reconciled period | PlatformAdmin |").
        PRD §2.7 (stage 2): "The role is permitted for the endpoint and ownership rules hold — a driver acts only on their own runs, a host-site manager only on their own site, a clerk never registers a fleet cylinder, and a technician's `cert_level` gates the hydrostatic method and condemn requests; otherwise `ERR_FORBIDDEN`."

        Design: Corner/rbac/host_manager_cannot_finalize_statement
        """
        site = create_site(name="Finalize Gate Site")
        st = create_statement(site["id"], "2026-05-01", "2026-05-01")
        res = api.finalize_commission_statement(
            st["id"], make_host_site_manager_headers(site["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_clerk_cannot_register_fleet_cylinder(self, api):
        """PRD §3.2: "Fleet registration is restricted to `PlatformAdmin`; a `SiteClerk` attempting to register a fleet cylinder is rejected with `ERR_FORBIDDEN`, as clerks may register customer cylinders only."

        Design: Corner/rbac/clerk_cannot_register_fleet_cylinder
        """
        res = api.create_cylinder(
            create_cylinder_payload(serial_number="SN-FB", owner_kind="FLEET",
                                    initial_fill="FULL"),
            CLERK1,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_visual_only_technician_cannot_hydrostatic(self, api):
        """PRD §3.2: "the `HYDROSTATIC` method requires `FULL` certification, and a `VISUAL_ONLY` technician attempting it is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/visual_only_technician_cannot_hydrostatic
        """
        cyl = register_fleet_cylinders(count=1, fill="EMPTY", serial_prefix="HY")[0]
        tech = create_technician(cert_level="VISUAL_ONLY", name="V")
        res = api.create_certification_record(
            {"cylinder_id": cyl["id"], "method": "HYDROSTATIC", "outcome": "PASS"},
            make_technician_headers(tech["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_create_technician_invalid_enum(self, api):
        """PRD §3.6: "Technicians are registered with a `name` and a `cert_level` of `VISUAL_ONLY` or `FULL`, begin `ACTIVE`, and may likewise be patched between `ACTIVE` and `SUSPENDED` or to a new `cert_level`." — a `cert_level` outside the declared pair is a malformed request.
        PRD §5: `ERR_VALIDATION` | 400 Bad Request.

        Design: Corner/entities/create_technician_invalid_enum
        """
        res = api.create_technician(
            create_technician_payload(name="Tech X", cert_level="MEGA"), ADMIN)
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


class TestSegregationOfDuties:
    def test_verify_run_by_same_driver_segregation(self, api):
        """PRD §3.6: "Verification closes the route under segregation of duties: a `PlatformAdmin` or `SiteClerk` whose `X-User-ID` differs from the run's `driver_id` — an equal identity rejects with `ERR_SEGREGATION_OF_DUTIES` — verifies a `COMPLETED` run, stamping `verified_by`"

        Design: Corner/rbac/verify_run_by_same_driver_segregation
        """
        site, driver, run = setup_dispatch_scenario(
            site_full=3, depot_full=9, planned_date="2026-05-20")
        dispatch_run(run["id"])
        advance_clock("2026-05-20T00:00:00Z")  # arrive requires the planned date
        driver_headers = make_driver_headers(driver["id"])
        validate_success(api.arrive_restock_run(run["id"], driver_headers), 200)
        validate_success(
            api.complete_restock_run(
                run["id"], {"delivered_full_count": 9, "picked_up_empty_count": 0},
                driver_headers),
            200,
        )
        # Verify under an allowed role but carrying the driver's identity.
        res = api.verify_restock_run(
            run["id"], {"X-User-ID": driver["id"], "X-User-Role": "SiteClerk",
                        "Content-Type": "application/json"})
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    def test_condemn_confirm_by_same_technician_segregation(self, api):
        """PRD §3.2: "A second technician, who must be `ACTIVE`, must hold `cert_level` `FULL`, and must not be the requesting technician, either confirms or rejects the decision; a confirmer or rejecter equal to the original `technician_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/condemn_confirm_by_same_technician_segregation
        """
        cyl = register_fleet_cylinders(count=1, fill="EMPTY", manufacture_date="2014-06-01",
                                       serial_prefix="SD")[0]
        t1 = create_technician(cert_level="FULL", name="T1")
        t2 = create_technician(cert_level="FULL", name="T2")
        record = record_certification(cyl["id"], t1, method="VISUAL", outcome="CONDEMN")
        assert record["status"] == "PENDING_SECOND"
        res = api.confirm_certification_record(record["id"], {}, make_technician_headers(t1["id"]))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
        confirmed = validate_success(
            api.confirm_certification_record(record["id"], {}, make_technician_headers(t2["id"])),
            200,
        )
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["confirmer_technician_id"] == t2["id"]

    def test_resolve_session_by_shift_clerk_segregation(self, api):
        """PRD §3.8: "segregation of duties forbids the resolver from being the shift clerk whose `clerk_id` opened the session, rejecting that attempt with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.8: "Resolution stamps `resolved_by` alongside the note and lands the session in `RESOLVED`."

        Design: Corner/rbac/resolve_session_by_shift_clerk_segregation
        """
        site = create_site(name="SoD Session Site")
        session = open_session(site["id"], "2026-05-01", CLERK1)  # clerk-1 is the shift clerk
        flagged = count_session(session["id"], 20600, 0, 0, CLERK1)  # +600 -> flagged
        assert flagged["status"] == "VARIANCE_FLAGGED"
        validate_success(
            api.escalate_reconciliation_session(session["id"], {}, make_admin_headers("admin-1")),
            200,
        )
        # Resolver identity equal to the shift clerk's id is forbidden even under PlatformAdmin.
        res = api.resolve_reconciliation_session(
            session["id"], {"resolution_note": "counted twice"}, make_admin_headers("clerk-1"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
        resolved = validate_success(
            api.resolve_reconciliation_session(
                session["id"], {"resolution_note": "recount accepted, training logged"},
                make_admin_headers("admin-9")),
            200,
        )
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolved_by"] == "admin-9"


class TestHostSiteManager:
    def test_host_manager_disputes_own_finalized_statement(self, api):
        """PRD §3.7: "A `HostSiteManager` — whose `X-User-ID` must equal the statement's `site_id`, else `ERR_FORBIDDEN` — disputes a `FINALIZED` statement by supplying a `note`, which is stored as `dispute_note` while the statement moves to `DISPUTED`."

        Design: Corner/rbac/host_manager_disputes_own_finalized_statement
        """
        site, _policy = create_priced_site()
        balanced_session(site["id"], "2026-05-01", CLERK1)  # no sales: 20000/0/0
        advance_clock("2026-05-02T00:00:00Z")
        st = create_statement(site["id"], "2026-05-01", "2026-05-01")
        finalized = finalize_statement(st["id"])
        assert finalized["status"] == "FINALIZED"
        disputed = validate_success(
            api.dispute_commission_statement(
                st["id"], {"note": "leak day should be excluded"},
                make_host_site_manager_headers(site["id"])),
            200,
        )
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_note"] == "leak day should be excluded"
