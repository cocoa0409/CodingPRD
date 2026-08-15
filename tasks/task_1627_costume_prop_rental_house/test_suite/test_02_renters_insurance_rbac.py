"""Renter registration, insurance certificate lifecycle, and role-based access."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_certificate,
    create_active_renter,
    create_confirmed_production,
    create_item_payload,
    decide_certificate,
    get_renter,
    make_house_admin_headers,
    make_renter_contact_headers,
    place_reservation,
    publish_rate_card,
    register_renter,
    create_catalog_item,
    acquire_unit,
    submit_certificate,
    validate_error,
    validate_success,
)


class TestInsuranceCertificates:
    def test_cert_starts_submitted_and_verify_flips_renter(self, api, house_admin_headers):
        """PRD §3.1: "The new certificate's `status` is `SUBMITTED`, one of the four
        certificate states `SUBMITTED`, `VERIFIED`, `REJECTED`, `EXPIRED`" and "A new renter
        starts in `PENDING_VERIFICATION` status with `outstanding_balance_cents` of 0 and
        `credit_hold` false." and "if the owning renter is `PENDING_VERIFICATION` or
        `SUSPENDED`, the renter's `status` becomes `ACTIVE` — so the first verified
        certificate activates a new renter".

        Design: Corner/state_machines/cert_starts_submitted_and_verify_flips_renter
        """
        renter = register_renter(api, name="R")
        assert renter["status"] == "PENDING_VERIFICATION"

        cert = submit_certificate(
            api, renter["id"], coverage_cents=100000, expiry_date="2027-06-30",
        )
        assert_certificate(cert)
        assert cert["status"] == "SUBMITTED"
        assert cert["decided_by_user_id"] is None

        decided = decide_certificate(api, cert["id"], decision="VERIFIED", admin_id="admin-9")
        assert decided["status"] == "VERIFIED"
        assert decided["decided_by_user_id"] == "admin-9"

        after = get_renter(api, renter["id"])
        assert after["status"] == "ACTIVE", (
            "the VERIFIED decision — not the create — flips the renter ACTIVE"
        )

    def test_cert_double_decide_rejected(self, api, house_admin_headers):
        """PRD §3.1: "A `HouseAdmin` decides a `SUBMITTED` certificate by supplying a
        `decision`." and the certificate states "of which `REJECTED` and `EXPIRED` are
        terminal."
        PRD §2.9: "the target resource is in a valid from-state for the requested transition;
        this covers `ERR_INVALID_STATE`".

        Design: Corner/state_machines/cert_double_decide_rejected
        """
        renter = register_renter(api, name="R")
        cert = submit_certificate(
            api, renter["id"], coverage_cents=100000, expiry_date="2027-06-30",
        )
        decide_certificate(api, cert["id"], decision="VERIFIED", admin_id="admin-1")

        resp = api.decide_certificate(
            cert["id"], "REJECTED", make_house_admin_headers("admin-2"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        unchanged = validate_success(api.get_certificate(cert["id"], house_admin_headers))
        assert unchanged["status"] == "VERIFIED"
        assert unchanged["decided_by_user_id"] == "admin-1"

    def test_error_insufficient_coverage_and_minimum_boundary(self, api, house_admin_headers):
        """PRD §3.1: "the `coverage_cents` must meet the renter-type minimum — 100000 cents
        for `THEATRE`, 500000 for `FILM`, 250000 for `EVENT`, and 50000 for `INDIVIDUAL` — or
        the decision is rejected with `ERR_INSUFFICIENT_COVERAGE`".

        Design: Corner/errors/error_insufficient_coverage_and_minimum_boundary
        """
        renter = register_renter(api, name="R", renter_type="INDIVIDUAL")
        c_low = submit_certificate(
            api, renter["id"], coverage_cents=49999, expiry_date="2027-06-30",
        )
        c_ok = submit_certificate(
            api, renter["id"], coverage_cents=50000, expiry_date="2027-06-30",
        )

        resp = api.decide_certificate(c_low["id"], "VERIFIED", house_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_COVERAGE, 422)
        still = validate_success(api.get_certificate(c_low["id"], house_admin_headers))
        assert still["status"] == "SUBMITTED"

        # Exactly at the INDIVIDUAL minimum (50000) meets it (>= semantics).
        ok = validate_success(
            api.decide_certificate(c_ok["id"], "VERIFIED", house_admin_headers)
        )
        assert ok["status"] == "VERIFIED"
        assert get_renter(api, renter["id"])["status"] == "ACTIVE"

    def test_error_certificate_expired_at_verify(self, api, house_admin_headers):
        """PRD §3.1: "the `expiry_date` must be on or after the current logical date, or the
        decision is rejected with `ERR_CERTIFICATE_EXPIRED`."
        PRD §2.4: "Before any call to the clock-setting capability, the logical clock reads
        exactly `2026-08-01T00:00:00Z`".

        Design: Corner/errors/error_certificate_expired_at_verify
        """
        renter = register_renter(api, name="R", renter_type="THEATRE")
        cert = submit_certificate(
            api, renter["id"], coverage_cents=100000,
            effective_date="2025-01-01", expiry_date="2026-07-01",
        )
        resp = api.decide_certificate(cert["id"], "VERIFIED", house_admin_headers)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_EXPIRED, 422)


class TestAuthenticationAndRbac:
    def test_error_unauthenticated_missing_header(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying the
        acting user, and `X-User-Role`, identifying their operational capacity. A request
        missing either header, or carrying an unrecognized role, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/error_unauthenticated_missing_header
        """
        renter = register_renter(api, name="R")
        resp = api.get_renter(renter["id"], headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_renter_scope_violation_on_foreign_resources(self, api):
        """PRD §2.1: "A `RenterContact` may act only on resources whose `renter_id` equals
        their `X-User-ID` — the `renter_id` in a production-creation body, and any production,
        reservation, pull list, fitting authorization, invoice, or damage claim reachable
        through the request path or body. A violation is rejected with
        `ERR_RENTER_SCOPE_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/renter_scope_violation_on_foreign_resources
        """
        publish_rate_card(api)
        item = create_catalog_item(api, name="I1")
        acquire_unit(api, item["id"], barcode="BC-SC1")
        renter_a = create_active_renter(api, name="A")["renter"]
        renter_b = create_active_renter(api, name="B")["renter"]
        prod_b = create_confirmed_production(api, renter_b, title="PB")
        res_b = place_reservation(api, prod_b["id"], renter_b, item["id"], quantity=1)

        # A tries to create a production naming B's renter_id in the body.
        resp = api.create_production(
            {
                "renter_id": renter_b["id"],
                "title": "Forged",
                "rehearsal_start_date": "2026-08-10",
                "performance_start_date": "2026-09-01",
                "closing_date": "2026-09-20",
            },
            make_renter_contact_headers(renter_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RENTER_SCOPE_VIOLATION, 403)

        # A tries to confirm B's reservation (path-reachable foreign resource).
        resp = api.confirm_reservation(
            res_b["id"], make_renter_contact_headers(renter_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RENTER_SCOPE_VIOLATION, 403)
        unchanged = validate_success(
            api.get_reservation(res_b["id"], make_house_admin_headers())
        )
        assert unchanged["status"] == "HELD"

    def test_wardrobe_cannot_issue_invoice_rejected(self, api, wardrobe_staff_headers):
        """PRD §2.1: "A request whose role is not permitted on the target endpoint is rejected
        with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: `POST /rental-house/invoices/{id}/issue` is authorized for Accountant only, and
        PRD §2.9 orders role authorization (2) before existence (4), so the denial fires even
        for a non-existent invoice id.

        Design: Corner/rbac/wardrobe_cannot_issue_invoice_rejected
        """
        resp = api.issue_invoice(NON_EXISTENT_UUID, wardrobe_staff_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_accountant_cannot_create_claim_rejected(self, api, accountant_headers):
        """PRD §2.1: "`Accountant` is the house accountant: invoice generation, issue,
        payments, credit notes, and damage-claim posting and waiving." — claim creation is not
        among them (it is WardrobeStaff's per PRD §3.7), so the role check rejects with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/accountant_cannot_create_claim_rejected
        """
        resp = api.create_claim(
            {"pull_list_line_id": NON_EXISTENT_UUID, "claim_type": "DAMAGE"},
            accountant_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_renter_contact_cannot_create_item_rejected(self, api):
        """PRD §2.1: "`HouseAdmin` is the rental-house administrator: catalog and
        acquisitions, rate cards, insurance decisions, fitting decisions, deaccession, the
        operations checkpoint, and the logical clock." — catalog creation is HouseAdmin-only,
        so a RenterContact is "rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/renter_contact_cannot_create_item_rejected
        """
        renter = register_renter(api, name="R")
        resp = api.create_item(
            create_item_payload(name="Forge"),
            make_renter_contact_headers(renter["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
