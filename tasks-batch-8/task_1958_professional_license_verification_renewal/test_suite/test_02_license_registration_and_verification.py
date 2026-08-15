"""License registration defaults, date guards, verification log, and chronology."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_active_license,
    create_employee,
    create_license,
    create_license_payload,
    create_license_type,
    get_success_data,
    make_officer_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]


class TestLicenseCreationDefaults:
    def test_license_created_with_pending_defaults(self, api):
        """PRD §3.3: "A freshly registered license enters at
        `PENDING_VERIFICATION` with `verification_posture` of `NEVER_VERIFIED`,
        `last_verified_on` null, both CE tallies at zero, and
        `ce_cycle_anchor_on` set to `issued_on`; its `alert_tier` is computed
        immediately."

        Design: Corner/entities/license_created_with_pending_defaults
        """
        lt = create_license_type()
        emp = create_employee(work_email="nora.def@example.com")
        data = validate_success(api.create_license(
            create_license_payload(employee_id=emp["id"], license_type_id=lt["id"],
                                   license_number="RN-9001"), OFFICER), 201)
        assert data["status"] == "PENDING_VERIFICATION"
        assert data["verification_posture"] == "NEVER_VERIFIED"
        assert data["cycle_ce_hours_validated"] == 0.0
        assert data["ce_cycle_anchor_on"] == "2026-01-01"

    def test_license_alert_tier_none_far_from_expiry(self, api):
        """PRD §3.5: "For a license in `PENDING_VERIFICATION` or `ACTIVE`, count
        the whole days from the logical current date to `expires_on`: ninety-one
        or more days out reads `NONE`".

        Design: Corner/entities/license_created_with_pending_defaults
        """
        lt = create_license_type()
        emp = create_employee(work_email="nora.def2@example.com")
        data = validate_success(api.create_license(
            create_license_payload(employee_id=emp["id"], license_type_id=lt["id"],
                                   expires_on="2027-06-30"), OFFICER), 201)
        # 2026-08-01 -> 2027-06-30 is 333 days: ninety-one or more reads NONE.
        assert data["alert_tier"] == "NONE"


class TestLicenseNotFound:
    def test_get_nonexistent_license_returns_not_found(self, api):
        """PRD §2.6: "Path identifiers are validated in strict left-to-right
        order, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the
        first identifier that does not correspond to an existing resource".

        Design: Corner/entities/get_nonexistent_license_returns_not_found
        """
        create_license_type()
        resp = api.get_license(NON_EXISTENT_UUID, OFFICER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestLicenseDateGuards:
    def test_expires_not_after_issued_rejected(self, api):
        """PRD §3.3: "`expires_on` must fall strictly after `issued_on`
        (`ERR_INVALID_DATES`)".

        Design: Corner/validations/expires_not_after_issued_rejected
        """
        lt = create_license_type()
        emp = create_employee(work_email="nora.dates@example.com")
        resp = api.create_license(
            create_license_payload(employee_id=emp["id"], license_type_id=lt["id"],
                                   license_number="RN-9306",
                                   issued_on="2026-01-01",
                                   expires_on="2026-01-01"), OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_DATES, 422)

    def test_validity_window_exceeded_at_731_days(self, api):
        """PRD §3.3: "`expires_on` may not exceed `issued_on` by more than 730
        days (`ERR_VALIDITY_WINDOW_EXCEEDED`)".

        Design: Corner/validations/validity_window_730_day_boundary
        """
        lt = create_license_type()
        emp = create_employee(work_email="nora.window@example.com")
        resp = api.create_license(
            create_license_payload(employee_id=emp["id"], license_type_id=lt["id"],
                                   license_number="RN-9304",
                                   issued_on="2026-01-01",
                                   expires_on="2028-01-02"), OFFICER)
        validate_error(resp, ApiErrorId.ERR_VALIDITY_WINDOW_EXCEEDED, 422)

    def test_validity_window_exactly_730_days_allowed(self, api):
        """PRD §3.3: "`expires_on` may not exceed `issued_on` by more than 730
        days (`ERR_VALIDITY_WINDOW_EXCEEDED`)".

        Design: Corner/validations/validity_window_730_day_boundary
        """
        lt = create_license_type()
        emp = create_employee(work_email="nora.window2@example.com")
        data = validate_success(api.create_license(
            create_license_payload(employee_id=emp["id"], license_type_id=lt["id"],
                                   state_code="NV", license_number="RN-9305",
                                   issued_on="2026-01-01",
                                   expires_on="2028-01-01"), OFFICER), 201)
        assert data["status"] == "PENDING_VERIFICATION"

    def test_expires_equal_issued_checked_before_window(self, api):
        """PRD §3.3: "Two date rules guard creation, evaluated in this order so
        the simpler defect surfaces first: `expires_on` must fall strictly after
        `issued_on` (`ERR_INVALID_DATES`), and only then is the validity window
        checked".

        Design: Corner/validations/expires_not_after_issued_rejected
        """
        lt = create_license_type()
        emp = create_employee(work_email="nora.dates2@example.com")
        resp = api.create_license(
            create_license_payload(employee_id=emp["id"], license_type_id=lt["id"],
                                   license_number="RN-9306b",
                                   issued_on="2026-06-01",
                                   expires_on="2026-06-01"), OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_DATES, 422)


class TestLicenseUniqueness:
    def test_duplicate_license_triple_rejected(self, api):
        """PRD §3.3: "Uniqueness is per holder, type, and state: a second license
        for the same triple fails with `ERR_DUPLICATE_LICENSE`."

        Design: Corner/validations/duplicate_license_triple_rejected
        """
        lt = create_license_type()
        emp = create_employee(work_email="nora.duplic@example.com")
        create_license(emp["id"], lt["id"], license_number="RN-9302")
        resp = api.create_license(
            create_license_payload(employee_id=emp["id"], license_type_id=lt["id"],
                                   license_number="RN-9999",
                                   issued_on="2026-02-01"), OFFICER)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LICENSE, 409)


class TestVerification:
    def test_verification_event_system_fields_recorded(self, api):
        """PRD §3.3: "Every recorded event is appended to the license's
        verification log — an append-only sequence capturing `license_id`,
        `verified_on`, `source`, `outcome`, the recording officer's
        `verifier_user_id`, and the `next_verification_due_on` in effect after
        the event."
        PRD §2.4: "A VerificationEvent is an append-only record and carries only
        `id` and `created_at`; both `updated_at` and `version` are absent".

        Design: Corner/entities/verification_event_system_fields_recorded
        """
        lt = create_license_type()
        emp = create_employee(work_email="nora.ve@example.com")
        lic = create_license(emp["id"], lt["id"], license_number="RN-9002")

        validate_success(api.verify_license(lic["id"], {
            "verified_on": "2026-08-01", "source": "STATE_BOARD_API",
            "outcome": "VERIFIED",
        }, make_officer_headers("officer-1")), 200)

        events, meta = validate_paginated(
            api.list_verification_events(lic["id"], OFFICER))
        assert meta["total_count"] == 1
        ev = events[0]
        assert ev["verified_on"] == "2026-08-01"
        assert ev["source"] == "STATE_BOARD_API"
        assert ev["outcome"] == "VERIFIED"
        assert ev["verifier_user_id"] == "officer-1"
        # min(2026-08-01 + 180d, 2027-06-30) = 2027-01-28
        assert ev["next_verification_due_on"] == "2027-01-28"
        assert "version" not in ev
        assert "updated_at" not in ev

    def test_verification_due_clamped_at_expiry(self, api):
        """PRD §3.3: "In every successful case, `next_verification_due_on`
        defaults to the earlier of `verified_on` plus the type's
        `verification_frequency_days` and the (possibly extended) `expires_on`".

        Design: Corner/calculations/verification_due_clamped_at_expiry
        """
        from test_helpers import create_pe_license_type
        lt = create_pe_license_type()
        emp = create_employee(full_name="Eric Engineer",
                              work_email="eric.clamp@example.com",
                              role_code="FIELD_ENGINEER")
        lic = create_license(emp["id"], lt["id"], license_number="PE-9202",
                             expires_on="2026-12-31")
        data = validate_success(api.verify_license(lic["id"], {
            "verified_on": "2026-08-01", "source": "MANUAL_UPLOAD",
            "outcome": "VERIFIED",
        }, OFFICER), 200)
        # 2026-08-01 + 365d = 2027-08-01, clamped to expires_on 2026-12-31.
        assert data["next_verification_due_on"] == "2026-12-31"
        assert data["verification_posture"] == "CURRENT"

    def test_verification_out_of_order_rejected(self, api):
        """PRD §3.3: "on a license that has been verified before, `verified_on`
        must be strictly after `last_verified_on`
        (`ERR_VERIFICATION_OUT_OF_ORDER`)".

        Design: Corner/validations/verification_out_of_order_rejected
        """
        lt = create_license_type()
        emp = create_employee(work_email="nora.ooo@example.com")
        lic = create_active_license(emp["id"], lt["id"], license_number="RN-9311")
        resp = api.verify_license(lic["id"], {
            "verified_on": "2026-07-15", "source": "MANUAL_UPLOAD",
            "outcome": "VERIFIED",
        }, OFFICER)
        validate_error(resp, ApiErrorId.ERR_VERIFICATION_OUT_OF_ORDER, 422)

    def test_duplicate_verification_same_day_rejected(self, api):
        """PRD §3.3: "any repeat of a date already present in the license's log
        is a duplicate (`ERR_DUPLICATE_VERIFICATION`) — which is why a same-day
        re-verification surfaces as a duplicate rather than as out-of-order."

        Design: Corner/validations/duplicate_verification_same_day_rejected
        """
        lt = create_license_type()
        emp = create_employee(work_email="nora.dupv@example.com")
        lic = create_active_license(emp["id"], lt["id"], license_number="RN-9312")
        set_clock("2026-08-15T00:00:00Z")
        validate_success(api.verify_license(lic["id"], {
            "verified_on": "2026-08-15", "source": "NURSYS",
            "outcome": "VERIFIED",
        }, OFFICER), 200)

        resp = api.verify_license(lic["id"], {
            "verified_on": "2026-08-15", "source": "MANUAL_UPLOAD",
            "outcome": "MISMATCH",
        }, OFFICER)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VERIFICATION, 409)

    def test_verify_expired_pending_license_rejected(self, api):
        """PRD §3.3: "a pending license that has already expired cannot be
        verified, so an `expires_on` earlier than `verified_on` is rejected with
        `ERR_INVALID_VERIFICATION_DATE`."

        Design: Corner/validations/verify_expired_pending_license_rejected
        """
        lt = create_license_type()
        emp = create_employee(work_email="nora.ivd@example.com")
        lic = create_license(emp["id"], lt["id"], license_number="RN-9313",
                             expires_on="2026-06-30")
        # Default clock is 2026-08-01, after expires_on 2026-06-30.
        resp = api.verify_license(lic["id"], {
            "verified_on": "2026-08-01", "source": "STATE_BOARD_API",
            "outcome": "VERIFIED",
        }, OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_VERIFICATION_DATE, 422)


class TestImmediateConsistency:
    def test_verify_response_immediately_reflects_new_state(self, api):
        """PRD §3.3: "On a `PENDING_VERIFICATION` license, a `VERIFIED` outcome
        promotes the license to `ACTIVE` and stamps `last_verified_on`"; "`next_verification_due_on`
        defaults to the earlier of `verified_on` plus the type's
        `verification_frequency_days` and the (possibly extended) `expires_on`".

        Design: Corner/consistency_model/verify_response_immediately_reflects_new_state
        """
        lt = create_license_type()
        emp = create_employee(work_email="nora.imm@example.com")
        lic = create_license(emp["id"], lt["id"], license_number="RN-9605")
        resp_data = validate_success(api.verify_license(lic["id"], {
            "verified_on": "2026-08-01", "source": "STATE_BOARD_API",
            "outcome": "VERIFIED",
        }, OFFICER), 200)
        assert resp_data["status"] == "ACTIVE"
        assert resp_data["next_verification_due_on"] == "2027-01-28"

        get_data = get_success_data(api.get_license(lic["id"], OFFICER))
        assert get_data["status"] == resp_data["status"]
        assert get_data["next_verification_due_on"] == resp_data["next_verification_due_on"]
