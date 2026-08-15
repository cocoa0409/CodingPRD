"""Admin concerns: fee schedule windows, recipient soft-deactivation,
authentication/authorization, referenced-FK existence, reissue review."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_reissue_request,
    create_delivered_order,
    create_fee_schedule,
    create_fee_schedule_payload,
    create_recipient,
    create_reissue_request,
    create_student,
    get_success_data,
    make_student_headers,
    reset_clock,
    set_clock,
    validate_error,
    validate_success,
)


def _admin():
    return TEST_USERS["admin_headers"]


def _reviewer():
    return TEST_USERS["reviewer_headers"]


def _bursar():
    return TEST_USERS["bursar_headers"]


class TestFeeScheduleWindows:
    def test_schedule_window_inverted_returns_invalid(self, api):
        """PRD §2.5: "then business-temporal rules (`ERR_CONSENT_EXPIRED`,
        `ERR_VERIFICATION_EXPIRED`, `ERR_SCHEDULE_WINDOW_INVALID`, all 422)".

        Design: Corner/validations/schedule_window_inverted_returns_invalid
        """
        reset_clock()
        payload = create_fee_schedule_payload(
            code="FS-BAD",
            effective_from="2026-09-01T00:00:00Z",
            effective_to="2026-08-01T00:00:00Z",
        )
        resp = api.create_fee_schedule(payload, _admin())
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_WINDOW_INVALID)

    def test_fee_schedule_window_overlap_on_active_schedules_rejected(self, api):
        """PRD §2.8: "only one schedule may be active at any logical instant, and
        registering a new active schedule atomically deactivates any other
        schedule whose effective window overlaps".

        Design: Difficulty/resource_temporal_overlap/fee_schedule_window_overlap_on_active_schedules_rejected
        """
        reset_clock()
        create_fee_schedule(
            code="FS-OVER-A",
            effective_from="2026-08-01T00:00:00Z",
            effective_to="2026-09-01T00:00:00Z",
        )
        # Overlapping active window: the pre-existing active schedule is
        # atomically deactivated, so only one active schedule remains.
        resp = api.create_fee_schedule(
            create_fee_schedule_payload(
                code="FS-OVER-B",
                effective_from="2026-08-15T00:00:00Z",
                effective_to="2026-10-01T00:00:00Z",
            ),
            _admin(),
        )
        fs_b = validate_success(resp, expected_status=201)
        assert fs_b["active"] is True
        fs_a_after = get_success_data(
            api.list_fee_schedules(_admin(), params={"active": True})
        )
        body = fs_a_after
        # Only the newest schedule may be active after the atomic deactivation.
        assert isinstance(body, list)
        assert len(body) == 1
        assert body[0]["id"] == fs_b["id"]

    def test_fee_schedule_adjacent_windows_both_usable(self, api):
        """PRD §3.5: "First the server locates the `FeeSchedule` active at
        `submitted_at` — the one whose `effective_from` is at or before
        `submitted_at` and whose `effective_to` is strictly after it, with a null
        `effective_to` meaning open-ended."

        Design: Difficulty/resource_temporal_overlap/fee_schedule_window_overlap_on_active_schedules_rejected
        """
        reset_clock()
        # Adjacent (non-overlapping) half-open windows: A ends where B begins.
        fs_a = create_fee_schedule(
            code="FS-ADJ-A",
            official_base_cents=1000,
            effective_from="2026-08-01T00:00:00Z",
            effective_to="2026-09-01T00:00:00Z",
            active=False,
        )
        fs_b = create_fee_schedule(
            code="FS-ADJ-B",
            official_base_cents=1200,
            unofficial_base_cents=600,
            effective_from="2026-09-01T00:00:00Z",
            effective_to="2026-10-01T00:00:00Z",
            active=True,
        )
        assert fs_b["active"] is True
        # The adjacent non-overlapping inactive schedule is untouched.
        fs_a_after = get_success_data(api.get_fee_schedule(fs_a["id"], _admin()))
        assert fs_a_after["active"] is False


class TestRecipientSoftDelete:
    def test_soft_delete_recipient_deactivation_blocks_new_lines(self, api):
        """PRD §2.8: "A `Recipient` whose `active` flag has been flipped to false
        can no longer be added to new orders and can no longer receive new
        dispatches, but historical `OrderLineItem` rows keep their reference to
        it."
        PRD §3.3: "The referenced `Recipient` must exist and must still be
        `active` at add time; a reference to a deactivated recipient is rejected
        with `ERR_RECIPIENT_INACTIVE` (HTTP 422)."

        Design: Corner/cross_cutting_layers/soft_delete_recipient_deactivation_blocks_new_lines
        """
        reset_clock()
        student = create_student(
            student_number="SC006101", full_name="SD T",
            date_of_birth="2000-01-01", email="sd@x.edu",
        )
        recipient = create_recipient(
            kind="EMAIL_PDF", display_name="Old Emp", email_address="old@x.com"
        )
        get_success_data(api.update_recipient(recipient["id"], {"active": False}, _admin()))
        student_headers = make_student_headers(student["id"])
        order = get_success_data(
            api.create_order(
                {"student_id": student["id"], "order_kind": "OFFICIAL"}, student_headers
            )
        )
        resp = api.add_line_item(
            order["id"],
            {
                "recipient_id": recipient["id"],
                "delivery_kind": "EMAIL_PDF",
                "quantity": 1,
                "expected_order_version": order["version"],
            },
            student_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RECIPIENT_INACTIVE)


class TestAuthentication:
    def test_unauthenticated_request_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or presenting one in a
        malformed form, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_request_returns_401
        """
        resp = api.list_students(headers={"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_unauthorized_role_returns_403(self, api):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /registrar/fee-schedules is authorized for
        "RegistrarAdmin".

        Design: Corner/validations/unauthorized_role_returns_403
        """
        reset_clock()
        resp = api.create_fee_schedule(
            create_fee_schedule_payload(code="FS-DENY"),
            make_student_headers("00000000-0000-0000-0000-000000000001"),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestReferencedForeignKeys:
    def test_order_references_student_via_fk(self, api):
        """PRD §2.5: "followed by existence of every body-supplied foreign key
        such as `student_id`, `recipient_id`, `consent_grant_id`,
        `original_order_id`, or `digitized_record_id` (`ERR_REFERENCED_NOT_FOUND`,
        404)".

        Design: Corner/entities/order_references_student_via_fk
        """
        reset_clock()
        resp = api.create_order(
            {"student_id": NON_EXISTENT_UUID, "order_kind": "OFFICIAL"},
            make_student_headers(NON_EXISTENT_UUID),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCED_NOT_FOUND)


class TestReissue:
    def test_reissue_reject_reverts_order_to_delivered(self, api):
        """PRD §3.10: "Rejection requires the same segregation check, moves the
        `ReissueRequest` from `REQUESTED` to `REJECTED`, and reverts the original
        order from `REISSUE_PENDING` to `DELIVERED`."

        Design: Corner/state_machines/reissue_reject_reverts_order_to_delivered
        """
        reset_clock()
        create_fee_schedule(code="FS-SM5")
        student = create_student(
            student_number="SC000303", full_name="SM Five",
            date_of_birth="2000-01-01", email="sm5@x.edu",
        )
        recipient = create_recipient(kind="EMAIL_PDF", display_name="Self", email_address="sm5@x.edu")
        order, _payment, _lines = create_delivered_order(
            student["id"],
            lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 1}],
        )
        reissue = create_reissue_request(order["id"], student["id"], reason="NAME_CORRECTION")
        student_headers = make_student_headers(student["id"])
        mid = get_success_data(api.get_order(order["id"], student_headers))
        assert mid["fulfillment_status"] == "REISSUE_PENDING"

        resp = api.reject_reissue_request(reissue["id"], _reviewer())
        rejected = validate_success(resp, expected_status=200)
        assert_reissue_request(rejected)
        assert rejected["status"] == "REJECTED"
        order_after = get_success_data(api.get_order(order["id"], student_headers))
        assert order_after["fulfillment_status"] == "DELIVERED"

    def test_reissue_approve_by_student_who_placed_order_rejected_sod(self, api):
        """PRD §3.10: "Review is segregated: the `RegistrarReviewer` who approves
        or rejects must have an `X-User-ID` different from the `id` of the
        `Student` who placed the original order, otherwise the action is rejected
        with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_reissue_on_non_delivered
        """
        reset_clock()
        create_fee_schedule(code="FS-PRIO2")
        student = create_student(
            student_number="S6000002", full_name="Karl Mo",
            date_of_birth="1999-09-09", email="karl@example.edu",
        )
        recipient = create_recipient(
            kind="EMAIL_PDF", display_name="Self", email_address="karl@example.edu"
        )
        order, _payment, _lines = create_delivered_order(
            student["id"],
            lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 1}],
        )
        reissue = create_reissue_request(
            order["id"], student["id"], reason="NAME_CORRECTION", fee_waived=True
        )
        # Reviewer presents the student's own id as X-User-ID: SoD violation.
        from prd_bench_local_runner.testing import build_user_headers

        resp = api.approve_reissue_request(
            reissue["id"], build_user_headers(student["id"], "RegistrarReviewer")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        reissue_after = get_success_data(api.get_reissue_request(reissue["id"], _reviewer()))
        assert reissue_after["status"] == "REQUESTED"

    def test_reissue_approve_by_distinct_reviewer_succeeds(self, api):
        """PRD §3.10: "On approval the request moves to `APPROVED`, `reviewed_by`
        is set to the reviewer's `X-User-ID`, and a replacement `TranscriptOrder`
        is created with `reissue_of_order_id` pointing at the original and
        `fulfillment_status` initialized to `READY_TO_FULFILL`; the
        `ReissueRequest`'s `replacement_order_id` is populated with the new
        order's `id`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_reissue_on_non_delivered
        """
        reset_clock()
        create_fee_schedule(code="FS-PRIO2B")
        student = create_student(
            student_number="S6000102", full_name="Karl Mo B",
            date_of_birth="1999-09-09", email="karlb@example.edu",
        )
        recipient = create_recipient(
            kind="EMAIL_PDF", display_name="Self", email_address="karlb@example.edu"
        )
        order, _payment, _lines = create_delivered_order(
            student["id"],
            lines=[{"recipient_id": recipient["id"], "delivery_kind": "EMAIL_PDF", "quantity": 1}],
        )
        reissue = create_reissue_request(
            order["id"], student["id"], reason="NAME_CORRECTION", fee_waived=True
        )
        resp = api.approve_reissue_request(reissue["id"], _reviewer())
        approved = validate_success(resp, expected_status=200)
        assert approved["status"] == "APPROVED"
        assert approved["replacement_order_id"], "replacement_order_id must be populated"
        replacement = get_success_data(
            api.get_order(approved["replacement_order_id"], _reviewer())
        )
        assert replacement["reissue_of_order_id"] == order["id"]
        assert replacement["fulfillment_status"] == "READY_TO_FULFILL"
