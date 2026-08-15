"""Provider site lifecycle: enrollment defaults, sanctions, termination, RBAC."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    NO_AUTH_HEADERS,
    TEST_USERS,
    add_order_line,
    assert_provider_site,
    create_provider_site_payload,
    get_site,
    make_audit_findings_issued,
    make_clinic,
    make_order,
    make_patient,
    make_private_lot,
    make_product,
    make_public_dose,
    make_public_lot,
    make_screening,
    make_site,
    make_unit,
    open_excursion,
    setup_open_borrow,
    submit_order,
    validate_error,
    validate_success,
)

VM = TEST_USERS["vaccine_manager_headers"]
SPO = TEST_USERS["state_program_officer_headers"]
CA = TEST_USERS["compliance_auditor_headers"]


class TestSiteEnrollment:
    def test_site_creation_defaults_active_and_zero_counters(self, api):
        """PRD §3.1: "The new site's `status` begins as `ACTIVE`, and its three
        computed counters — `excursion_count_open`, `accountability_balance_doses`,
        and `private_lending_balance` — all begin at zero."

        Design: Corner/entities/provider_site_creation_defaults_status_active
        """
        resp = api.create_provider_site(create_provider_site_payload(), CA)
        data = validate_success(resp, expected_status=201)
        assert_provider_site(data)
        assert data["status"] == "ACTIVE"
        assert data["excursion_count_open"] == 0
        assert data["accountability_balance_doses"] == 0
        assert data["private_lending_balance"] == 0

    def test_site_creation_missing_vfc_pin_rejected(self, api):
        """PRD §3.1: enrollment requires "supplying a `site_name` and the
        state-issued `vfc_pin`". PRD §2.4: "Requests with a missing required
        field, a type mismatch, or a value outside its permitted range — for
        example, a dose quantity below 1 — are rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/provider_site_creation_missing_vfc_pin_returns_invalid_request
        """
        resp = api.create_provider_site({"site_name": "No PIN"}, CA)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestAccessControl:
    def test_missing_user_context_header_rejected(self, api):
        """PRD §2.1: "A request in which either header is missing or
        syntactically invalid is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api.create_provider_site(create_provider_site_payload(), NO_AUTH_HEADERS)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_get_nonexistent_site_returns_not_found(self, api):
        """PRD §2.9: "Each identifier in the path is resolved in turn, and the
        request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first
        identifier that does not correspond to an existing resource".

        Design: Corner/validations/not_found_on_nonexistent_provider_site_id
        """
        resp = api.get_provider_site(NON_EXISTENT_UUID, CA)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_vaccine_manager_cannot_terminate_site(self, api):
        """PRD §2.1: "An attempt to perform an operation outside the caller's
        role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: POST /provider-sites/{id}/terminate is authorized for
        ComplianceAuditor only.

        Design: Corner/validations/role_denial_vaccine_manager_cannot_terminate_site
        """
        site = make_site()
        resp = api.terminate_provider_site(site["id"], VM)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_state_program_officer_cannot_create_lots(self, api):
        """PRD §2.1: "An attempt to perform an operation outside the caller's
        role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: POST /provider-sites/{id}/lots is authorized for
        VaccineManager only.

        Design: Corner/roles/state_program_officer_cannot_create_lots
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        payload = {
            "storage_unit_id": unit["id"],
            "vaccine_product_id": product["id"],
            "lot_number": "L-X",
            "stock_type": "PRIVATE",
            "quantity_on_hand": 5,
            "expires_on": "2027-06-30",
        }
        resp = api.create_lot(site["id"], payload, SPO)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_vaccine_manager_cannot_approve_orders(self, api):
        """PRD §2.1: "An attempt to perform an operation outside the caller's
        role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: POST /provider-sites/{id}/vaccine-orders/{orderId}/approve is
        authorized for StateProgramOfficer only.

        Design: Corner/roles/vaccine_manager_cannot_approve_orders
        """
        site = make_site()
        product = make_product()
        order = make_order(site["id"], expected_vfc_doses=5)
        add_order_line(site["id"], order["id"], product["id"], 5)
        submit_order(site["id"], order["id"])
        sv = get_site(site["id"])["version"]
        resp = api.approve_order(
            site["id"], order["id"],
            {"approved_vfc_doses": 5, "expected_provider_site_version": sv},
            VM,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_compliance_auditor_cannot_administer_doses(self, api):
        """PRD §2.1: "An attempt to perform an operation outside the caller's
        role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: POST /provider-sites/{id}/dose-administrations is authorized
        for VaccineManager only.

        Design: Corner/roles/compliance_auditor_cannot_administer_doses
        """
        ctx = make_clinic(public_doses=3)
        site_id = ctx["site"]["id"]
        patient = make_patient(site_id)
        screening = make_screening(patient["id"])
        resp = api.create_dose_administration(
            site_id,
            {
                "patient_id": patient["id"],
                "eligibility_screening_id": screening["id"],
                "lot_id": ctx["pub_lot_id"],
                "administration_date": "2026-08-05",
            },
            CA,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestSiteTermination:
    def test_terminated_site_locks_all_transitions(self, api):
        """PRD §3.1: "suspension moves the site from `ACTIVE` to
        `SUSPENDED_ORDERING`; attempting the transition from any other state is
        rejected with `ERR_INVALID_STATE`" and "Reinstatement returns a
        `SUSPENDED_ORDERING` site to `ACTIVE`, and again any other source state
        draws `ERR_INVALID_STATE`." Termination "may be invoked from either
        `ACTIVE` or `SUSPENDED_ORDERING`", and PRD §2.12: "the target
        resource's current state is checked against the requested transition
        (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/provider_site_terminal_terminated_lockdown
        """
        site = make_site()
        terminated = validate_success(api.terminate_provider_site(site["id"], CA))
        assert terminated["status"] == "TERMINATED"
        for call in (
            api.suspend_ordering,
            api.reinstate_ordering,
            api.terminate_provider_site,
        ):
            resp = call(site["id"], CA)
            validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_open_excursion_blocks_termination(self, api):
        """PRD §3.1: "It is blocked while any of the site's storage units has
        an excursion in `OPEN` or `UNDER_REVIEW`
        (`ERR_OPEN_EXCURSION_EXISTS`)".

        Design: Corner/errors/error_open_excursion_blocks_termination
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        make_private_lot(site["id"], unit["id"], product["id"], quantity_on_hand=3)
        open_excursion(unit["id"])
        resp = api.terminate_provider_site(site["id"], CA)
        validate_error(resp, ApiErrorId.ERR_OPEN_EXCURSION_EXISTS)

    def test_open_borrow_ticket_blocks_termination(self, api):
        """PRD §3.1: termination is blocked "while any borrow ticket at the
        site is `OPEN` or `PARTIALLY_REPAID` (`ERR_OPEN_BORROW_TICKET_EXISTS`)".

        Design: Corner/errors/error_open_borrow_ticket_blocks_termination
        """
        ctx = setup_open_borrow(public_doses=10, private_doses=8, borrow_qty=2)
        resp = api.terminate_provider_site(ctx["site"]["id"], CA)
        validate_error(resp, ApiErrorId.ERR_OPEN_BORROW_TICKET_EXISTS)


class TestAuditCloseFailCascade:
    def test_close_fail_suspends_site_ordering(self, api):
        """PRD §3.9: "Closing as failed requires only the `FINDINGS_ISSUED`
        state and lands the audit in `CLOSED_FAIL` with a consequential
        cascade: the site's `status` is set to `SUSPENDED_ORDERING`, cutting
        off new orders until the compliance posture is restored."

        Design: Difficulty/transitive_cascade/audit_close_fail_cascades_site_suspend_and_blocks_order_submit
        """
        ctx = _setup_audit_findings_with_gap(api)
        audit = validate_success(
            api.close_audit_fail(ctx["site"]["id"], ctx["audit"]["id"], CA)
        )
        assert audit["status"] == "CLOSED_FAIL"
        site = get_site(ctx["site"]["id"])
        assert site["status"] == "SUSPENDED_ORDERING", (
            f"close-fail must cascade the site to SUSPENDED_ORDERING, got {site['status']}"
        )

    def test_close_fail_cascade_blocks_downstream_order_submit(self, api):
        """PRD §3.1: "While suspended, the site cannot submit vaccine orders —
        submission is refused with `ERR_SITE_SUSPENDED_ORDERING`". The block is
        a downstream consequence of the audit close-fail cascade (PRD §3.9).

        Design: Difficulty/transitive_cascade/audit_close_fail_cascades_site_suspend_and_blocks_order_submit
        """
        ctx = _setup_audit_findings_with_gap(api)
        validate_success(api.close_audit_fail(ctx["site"]["id"], ctx["audit"]["id"], CA))
        resp = api.submit_order(ctx["site"]["id"], ctx["new_order"]["id"], VM)
        validate_error(resp, ApiErrorId.ERR_SITE_SUSPENDED_ORDERING)


def _setup_audit_findings_with_gap(api) -> dict:
    """5 public doses received, 1 administered; audit at FINDINGS_ISSUED; a
    fresh DRAFT order (with one line) ready to submit after the cascade."""
    site = make_site()
    unit = make_unit(site["id"])
    product = make_product()
    pub = make_public_lot(site["id"], unit["id"], product["id"], 5)
    make_public_dose(site["id"], pub["lot_id"])
    audit = make_audit_findings_issued(site["id"])
    new_order = make_order(site["id"], expected_vfc_doses=2)
    add_order_line(site["id"], new_order["id"], product["id"], 2)
    return {"site": site, "unit": unit, "product": product, "audit": audit,
            "new_order": new_order}
