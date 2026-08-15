"""Identity verification shape/expiry and hold placement/release segregation."""
from test_helpers import (
    ApiErrorId,
    assert_hold,
    create_hold,
    create_order_payload,
    create_student,
    create_recipient,
    get_success_data,
    make_student_headers,
    reset_clock,
    set_clock,
    validate_error,
    validate_success,
)


class TestIdentityVerificationShape:
    def test_identity_verification_immutable_no_update_endpoint(self, api, admin_headers):
        """PRD §2.4: "`IdentityVerification` carries only `id` and `created_at`;
        it has neither `updated_at` nor `version`."
        PRD §3.4: "The server mints a one-time `verification_token` and stamps
        `expires_at` at exactly 72 hours after creation."

        Design: Corner/entities/identity_verification_immutable_no_update_endpoint
        """
        reset_clock()
        student = create_student(
            student_number="SB000301", full_name="IV T",
            date_of_birth="2000-01-01", email="iv@x.edu",
        )
        recipient = create_recipient(
            kind="EMAIL_PDF", display_name="Self", email_address="iv@x.edu"
        )
        student_headers = make_student_headers(student["id"])
        order = get_success_data(
            api.create_order(
                {"student_id": student["id"], "order_kind": "OFFICIAL"}, student_headers
            )
        )
        get_success_data(
            api.add_line_item(
                order["id"],
                {
                    "recipient_id": recipient["id"],
                    "delivery_kind": "EMAIL_PDF",
                    "quantity": 1,
                    "expected_order_version": order["version"],
                },
                student_headers,
            )
        )
        idv = get_success_data(
            api.create_identity_verification(
                {
                    "student_id": student["id"],
                    "order_id": order["id"],
                    "method": "SSN_DOB",
                },
                student_headers,
            )
        )
        resp = api.get_identity_verification(idv["id"], admin_headers)
        data = validate_success(resp, expected_status=200)
        assert "version" not in data, "IdentityVerification must not carry version"
        assert "updated_at" not in data, "IdentityVerification must not carry updated_at"
        assert isinstance(data.get("verification_token"), str)


class TestIdentityVerificationExpiry:
    def test_identity_verification_token_expiry_window(self, api):
        """PRD §3.4: "Confirming the verification requires the caller to present
        the `verification_token`; confirmation succeeds only while the record is
        `PENDING`, the token matches, and the logical clock is still earlier than
        `expires_at`. A confirm attempted after expiry is rejected with
        `ERR_VERIFICATION_EXPIRED` (HTTP 422)."
        PRD §3.4: "The server mints a one-time `verification_token` and stamps
        `expires_at` at exactly 72 hours after creation."

        Design: Difficulty/resource_temporal_overlap/identity_verification_token_expiry_window
        """
        reset_clock()
        student = create_student(
            student_number="S9000001", full_name="Paula Ho",
            date_of_birth="2000-04-25", email="paula@example.edu",
        )
        recipient = create_recipient(
            kind="EMAIL_PDF", display_name="Self", email_address="paula@example.edu"
        )
        student_headers = make_student_headers(student["id"])
        order = get_success_data(
            api.create_order(
                {"student_id": student["id"], "order_kind": "OFFICIAL"}, student_headers
            )
        )
        get_success_data(
            api.add_line_item(
                order["id"],
                {
                    "recipient_id": recipient["id"],
                    "delivery_kind": "EMAIL_PDF",
                    "quantity": 1,
                    "expected_order_version": order["version"],
                },
                student_headers,
            )
        )
        idv = get_success_data(
            api.create_identity_verification(
                {
                    "student_id": student["id"],
                    "order_id": order["id"],
                    "method": "SSN_DOB",
                },
                student_headers,
            )
        )
        # Created at 2026-08-01T00:00:00Z -> expires at exactly 2026-08-04T00:00:00Z.
        # At the expiry instant the record has been moved to EXPIRED by the clock.
        set_clock("2026-08-04T00:00:00Z")
        resp = api.confirm_identity_verification(
            idv["id"], {"verification_token": idv["verification_token"]}, student_headers
        )
        validate_error(resp, ApiErrorId.ERR_VERIFICATION_EXPIRED)

    def test_identity_verification_token_expiry_window_state_not_verified(self, api):
        """PRD §2.4: "setting the clock re-evaluates ... every
        `IdentityVerification` whose `expires_at` has been reached (transitioning
        each from `PENDING` to `EXPIRED`)".

        Design: Difficulty/resource_temporal_overlap/identity_verification_token_expiry_window
        """
        reset_clock()
        student = create_student(
            student_number="S9000101", full_name="Paula Ho Two",
            date_of_birth="2000-04-25", email="paula2@example.edu",
        )
        recipient = create_recipient(
            kind="EMAIL_PDF", display_name="Self", email_address="paula2@example.edu"
        )
        student_headers = make_student_headers(student["id"])
        order = get_success_data(
            api.create_order(
                {"student_id": student["id"], "order_kind": "OFFICIAL"}, student_headers
            )
        )
        get_success_data(
            api.add_line_item(
                order["id"],
                {
                    "recipient_id": recipient["id"],
                    "delivery_kind": "EMAIL_PDF",
                    "quantity": 1,
                    "expected_order_version": order["version"],
                },
                student_headers,
            )
        )
        idv = get_success_data(
            api.create_identity_verification(
                {
                    "student_id": student["id"],
                    "order_id": order["id"],
                    "method": "SSN_DOB",
                },
                student_headers,
            )
        )
        # One second before expiry: still confirmable.
        set_clock("2026-08-03T23:59:59Z")
        resp = api.confirm_identity_verification(
            idv["id"], {"verification_token": idv["verification_token"]}, student_headers
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "VERIFIED"


class TestHolds:
    def test_hold_initial_state_is_active(self, api, library_headers, admin_headers):
        """PRD §3.2: "The server stamps `placed_at` at creation and leaves
        `released_at` null while the hold is `ACTIVE`."

        Design: Corner/state_machines/hold_initial_state_is_active
        """
        reset_clock()
        student = create_student(
            student_number="SC000101", full_name="H Init",
            date_of_birth="2000-01-01", email="h@x.edu",
        )
        resp = api.create_hold(
            {"student_id": student["id"], "hold_type": "LIBRARY", "blocking_scope": "OFFICIAL"},
            library_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_hold(data)
        assert data["status"] == "ACTIVE"
        assert data["placed_at"] is not None
        assert data["released_at"] is None

    def test_hold_release_wrong_office_returns_office_mismatch(
        self, api, bursar_headers, library_headers
    ):
        """PRD §3.2: "Releasing a hold requires the acting role to match the
        office that owns the `hold_type`: `FINANCIAL` is released only by
        `BursarOffice`, `LIBRARY` only by `LibraryOffice`, and `REGISTRAR` or
        `DISCIPLINARY` only by `RegistrarAdmin`. A mismatched attempt is rejected
        with `ERR_HOLD_OFFICE_MISMATCH` (HTTP 403)."

        Design: Corner/validations/hold_release_wrong_office_returns_office_mismatch
        """
        reset_clock()
        student = create_student(
            student_number="SC002001", full_name="HO T",
            date_of_birth="2000-01-01", email="ho@x.edu",
        )
        hold = create_hold(
            student["id"], role="bursar",
            hold_type="FINANCIAL", blocking_scope="OFFICIAL", amount_cents=5000,
        )
        resp = api.release_hold(hold["id"], library_headers)
        validate_error(resp, ApiErrorId.ERR_HOLD_OFFICE_MISMATCH)
        # Hold is untouched.
        after = validate_success(api.get_hold(hold["id"], bursar_headers), expected_status=200)
        assert after["status"] == "ACTIVE"

    def test_hold_release_by_matching_office_succeeds(self, api, bursar_headers):
        """PRD §3.2: "A successful release moves the hold from `ACTIVE` to
        `RELEASED`, stamps `released_at`, increments the hold's `version`, emits
        a `HOLD_RELEASED` audit event".

        Design: Corner/validations/hold_release_wrong_office_returns_office_mismatch
        """
        reset_clock()
        student = create_student(
            student_number="SC002002", full_name="HO T2",
            date_of_birth="2000-01-01", email="ho2@x.edu",
        )
        hold = create_hold(
            student["id"], role="bursar",
            hold_type="FINANCIAL", blocking_scope="OFFICIAL", amount_cents=5000,
        )
        resp = api.release_hold(hold["id"], bursar_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "RELEASED"
        assert data["released_at"] is not None
        assert data["version"] == hold["version"] + 1


class TestHoldRbac:
    def test_student_cannot_release_hold(self, api, bursar_headers):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /registrar/holds/{id}/release is authorized for
        "BursarOffice, LibraryOffice, RegistrarAdmin".

        Design: Corner/rbac/student_cannot_release_hold
        """
        reset_clock()
        student = create_student(
            student_number="SC005001", full_name="RB T",
            date_of_birth="2000-01-01", email="rb@x.edu",
        )
        hold = create_hold(
            student["id"], role="bursar",
            hold_type="FINANCIAL", blocking_scope="OFFICIAL", amount_cents=1000,
        )
        resp = api.release_hold(hold["id"], make_student_headers(student["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        after = validate_success(api.get_hold(hold["id"], bursar_headers), expected_status=200)
        assert after["status"] == "ACTIVE"
