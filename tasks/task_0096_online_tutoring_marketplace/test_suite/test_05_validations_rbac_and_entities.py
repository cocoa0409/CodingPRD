"""Validation rejections, RBAC enforcement, OCC, and entity CRUD corners.

Covers missing-header / authorization / ownership rejections, the temporal and
amount validations, the OCC stale-version guard, and the basic entity shape /
default / not-found claims.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_policy,
    create_booking,
    create_funded_parent,
    create_student,
    create_subject,
    create_tutor_payload,
    create_verified_tutor,
    deliver_booking,
    make_parent_headers,
    make_tutor_headers,
    propose_and_approve_tag,
    set_clock,
    setup_confirmed_standard_session,
    setup_countered_refund_case,
    setup_marketplace,
    setup_open_refund_case,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["trust_officer_headers"]


class TestEntityCrud:
    def test_create_subject_returns_201_with_fields(self, api):
        """PRD §3.1: "A subject is created with a unique `code` (such as
        `MATH_ALGEBRA_2`), a human-readable `display_name`, and a `category` ...
        Subjects are immutable configuration: once created, a subject's `status`
        is `ACTIVE`".

        Design: Corner/entities/create_subject_returns_201_with_fields
        """
        set_clock("2026-06-01T00:00:00Z")
        resp = api.create_subject(
            {"code": "ENG_ESSAY", "display_name": "Essay Writing", "category": "HUMANITIES"}, ADMIN
        )
        data = validate_success(resp, 201)
        from test_helpers import is_valid_uuid
        assert is_valid_uuid(data["id"])
        assert data["status"] == "ACTIVE"
        assert data["requires_credential"] is False

    def test_create_tutor_missing_required_field_rejected(self, api):
        """PRD §2.5: "A request body that is malformed, carries a field of the
        wrong type, or omits a required field is rejected with `ERR_VALIDATION`."
        PRD §3.2: "A tutor registers with an `email`, a `full_name`, and a
        `base_hourly_rate_cents`".

        Design: Corner/entities/create_tutor_missing_required_field_rejected
        """
        set_clock("2026-06-01T00:00:00Z")
        resp = api.create_tutor({"email": "t@x.com", "full_name": "No Rate"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_subject_default_requires_credential_false(self, api):
        """PRD §3.1: "A subject may be flagged with `requires_credential`; when
        this flag is true, a tutor must hold a verified credential for that subject
        before being tagged to it, and when omitted the flag defaults to false."

        Design: Corner/entities/subject_default_requires_credential_false_applied
        """
        set_clock("2026-06-01T00:00:00Z")
        resp = api.create_subject({"code": "MUS_PIANO", "display_name": "Piano", "category": "MUSIC"}, ADMIN)
        data = validate_success(resp, 201)
        assert data["requires_credential"] is False

    def test_tutor_system_fields_generated(self, api):
        """PRD §3.2: "A freshly registered tutor begins life with a
        `verification_status` of `UNVERIFIED`."
        PRD §2.4: "`version` — an integer that begins at its initial value and
        increments by one on each mutation."

        Design: Corner/entities/tutor_system_fields_generated_input_ignored
        """
        set_clock("2026-06-01T00:00:00Z")
        resp = api.create_tutor(
            {"email": "t@x.com", "full_name": "T", "base_hourly_rate_cents": 6000, "verification_status": "VERIFIED"}, ADMIN
        )
        data = validate_success(resp, 201)
        assert data["verification_status"] == "UNVERIFIED"
        assert data["version"] == 1
        from test_helpers import is_valid_uuid
        assert is_valid_uuid(data["id"])

    def test_tutor_computed_balances_start_zero(self, api):
        """PRD §3.2: "Several balances start empty and are maintained by the system
        thereafter: `lifetime_net_earnings_cents` ... `payout_balance_cents`,
        `clawback_owed_cents`, the `reliability_score`, and `active_subject_count`".

        Design: Corner/entities/tutor_computed_lifetime_earnings_starts_zero
        """
        set_clock("2026-06-01T00:00:00Z")
        tutor = validate_success(api.create_tutor(create_tutor_payload(), ADMIN), 201)
        fetched = validate_success(api.get_tutor(tutor["id"], ADMIN))
        assert fetched["lifetime_net_earnings_cents"] == 0
        assert fetched["payout_balance_cents"] == 0
        assert fetched["active_subject_count"] == 0

    def test_get_tutor_not_found(self, api):
        """PRD §2.5: "a missing tutor yields `ERR_TUTOR_NOT_FOUND`".

        Design: Corner/entities/get_tutor_not_found
        """
        set_clock("2026-06-01T00:00:00Z")
        resp = api.get_tutor("00000000-0000-4000-8000-000000000000", ADMIN)
        validate_error(resp, ApiErrorId.ERR_TUTOR_NOT_FOUND.value)

    def test_archive_student_decrements_child_count(self, api):
        """PRD §3.4: "Archiving a student moves its `status` to `ARCHIVED` and
        decrements `child_count`".

        Design: Corner/entities/student_immutable_after_archive_listed_filtered
        """
        set_clock("2026-06-01T00:00:00Z")
        parent = create_funded_parent(0)
        p_headers = make_parent_headers(parent["id"])
        create_student(parent["id"], display_name="Keep")
        gone = create_student(parent["id"], display_name="Gone", grade_level=10)
        archived = validate_success(api.archive_student(gone["id"], p_headers))
        assert archived["status"] == "ARCHIVED"
        parent_after = validate_success(api.get_parent_account(parent["id"], p_headers))
        assert parent_after["child_count"] == 1


class TestStateValidations:
    def test_confirm_already_confirmed_session_rejected(self, api):
        """PRD §3.7: "Both confirm and dispute require the session to currently be
        in `REPORTED`, and any other starting state is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/confirm_already_confirmed_session_invalid_state
        """
        mk = setup_marketplace(base_hourly_rate_cents=6000)
        booking = create_booking(mk, "2026-06-02T10:00:00Z", planned_minutes=30)
        session = deliver_booking(mk, booking["id"], 30, "2026-06-02T11:00:00Z")
        validate_success(api.confirm_session(session["id"], mk["parent_headers"]))
        resp = api.confirm_session(session["id"], mk["parent_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_approve_revoked_tag_rejected(self, api):
        """PRD §3.3: "A `TrustOfficer` approves the tag, which requires three
        conditions to hold: the tag must currently be `PROPOSED` ... The first two
        failures surface as `ERR_INVALID_STATE`".
        PRD §3.3: "Revoking a tag that is still `PROPOSED` simply moves it to
        `REVOKED` ... `REVOKED` is terminal."

        Design: Corner/state_machines/approve_already_revoked_tag_invalid_state
        """
        set_clock("2026-06-01T00:00:00Z")
        subject = create_subject()
        tutor, _ = create_verified_tutor(subject["id"])
        t_headers = make_tutor_headers(tutor["id"])
        tag = validate_success(
            api.create_subject_tag({"tutor_id": tutor["id"], "subject_id": subject["id"]}, t_headers), 201
        )
        validate_success(api.revoke_subject_tag(tag["id"], OFFICER))
        resp = api.approve_subject_tag(tag["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        tag_after = validate_success(api.get_subject_tag(tag["id"], OFFICER))
        assert tag_after["status"] == "REVOKED"


class TestTemporalAndAmountValidations:
    def test_missing_user_context_header_rejected(self, api):
        """PRD §2.1: "Every request must carry two headers identifying the caller:
        `X-User-ID`, the caller's identifier, and `X-User-Role`, the caller's role.
        If either header is missing or malformed, the request is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_user_context_header_rejected
        """
        resp = api.create_subject(
            {"code": "X", "display_name": "X", "category": "STEM"}, {"Content-Type": "application/json"}
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_booking_start_in_past_rejected(self, api):
        """PRD §3.5: "The `scheduled_start` must be strictly later than the current
        deterministic clock, and `planned_minutes` must be at least 15 and at most
        240; a start that is not in the future or a duration outside that range is
        rejected with `ERR_BOOKING_TIME_INVALID`."

        Design: Corner/validations/booking_time_in_past_rejected
        """
        set_clock("2026-06-05T00:00:00Z")
        create_active_policy()
        subject = create_subject()
        tutor, _ = create_verified_tutor(subject["id"])
        propose_and_approve_tag(tutor["id"], subject["id"])
        parent = create_funded_parent(100000)
        p_headers = make_parent_headers(parent["id"])
        student = create_student(parent["id"])
        resp = api.create_booking(
            {
                "parent_account_id": parent["id"], "student_id": student["id"],
                "tutor_id": tutor["id"], "subject_id": subject["id"],
                "scheduled_start": "2026-06-01T10:00:00Z", "planned_minutes": 60,
            },
            p_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BOOKING_TIME_INVALID.value)

    def test_refund_window_closed_rejected(self, api):
        """PRD §3.9: "A case may be opened only while the current clock is at or
        before the session's end plus the policy's `refund_window_hours`, and only
        while the session's `settlement_status` is `SETTLED` or `DISPUTED`; opening
        it after the window has closed ... is rejected with
        `ERR_REFUND_WINDOW_CLOSED`."

        Design: Corner/validations/refund_window_closed_rejected
        """
        mk, std_booking, std_session = setup_confirmed_standard_session(std_planned_minutes=30, std_actual_minutes=30)
        # Session ended 2026-06-03; advance far past + 168h window.
        set_clock("2026-06-20T00:00:00Z")
        resp = api.create_refund_case({"session_id": std_session["id"], "claimed_amount_cents": 1000}, mk["parent_headers"])
        validate_error(resp, ApiErrorId.ERR_REFUND_WINDOW_CLOSED.value)

    def test_counter_above_parent_offer_rejected(self, api):
        """PRD §3.9: "a counter supplies `counter_amount_cents`, which must be less
        than or equal to the current `parent_offer_cents`".
        PRD §3.9: "An offer that violates these monotone-narrowing bounds (a tutor
        counter above the parent offer ...) is rejected with
        `ERR_OFFER_OUT_OF_BOUNDS`".

        Design: Corner/validations/counter_above_parent_offer_out_of_bounds
        """
        mk, std_session, case = setup_open_refund_case(claimed_amount_cents=2000)
        resp = api.counter_refund_case(
            case["id"], {"counter_amount_cents": 3000, "expected_refund_case_version": case["version"]}, mk["tutor_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_OUT_OF_BOUNDS.value)


class TestErrorConditions:
    def test_insufficient_wallet_balance_on_booking(self, api):
        """PRD §3.5: "Before the booking is accepted, the parent's
        `available_balance_cents` must be at least the computed `hold_amount_cents`;
        if available funds cannot cover the hold, the booking is rejected with
        `ERR_INSUFFICIENT_WALLET_BALANCE`."

        Design: Corner/errors/insufficient_wallet_balance_on_booking
        """
        set_clock("2026-06-01T00:00:00Z")
        subject = create_subject()
        tutor, _ = create_verified_tutor(subject["id"], base_hourly_rate_cents=6000)
        propose_and_approve_tag(tutor["id"], subject["id"])
        parent = create_funded_parent(1000)  # only 1000c
        p_headers = make_parent_headers(parent["id"])
        student = create_student(parent["id"])
        # planned 60 -> hold 6000 > 1000.
        resp = api.create_booking(
            {
                "parent_account_id": parent["id"], "student_id": student["id"],
                "tutor_id": tutor["id"], "subject_id": subject["id"],
                "scheduled_start": "2026-06-02T10:00:00Z", "planned_minutes": 60,
            },
            p_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_WALLET_BALANCE.value)

    def test_escalate_before_round_one_rejected(self, api):
        """PRD §3.9: "Escalation is allowed from either `PARENT_PROPOSED` or
        `TUTOR_COUNTERED` provided `round_count` is at least 1".
        PRD §3.9: "an escalation attempted before at least one round has completed,
        is rejected with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`."

        Design: Corner/errors/escalate_before_round_one_rejected
        """
        mk, std_session, case = setup_open_refund_case(claimed_amount_cents=2000)
        # round_count is 0 (freshly opened, no counter yet).
        resp = api.escalate_refund_case(case["id"], mk["parent_headers"])
        validate_error(resp, ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED.value)


class TestRbacAndOwnership:
    def test_parent_cannot_approve_subject_tag(self, api):
        """PRD §2.1: "When the headers are well-formed but the role is not permitted
        to invoke the requested operation (per the authorization column in Section
        4), the request is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/parent_cannot_approve_subject_tag
        """
        set_clock("2026-06-01T00:00:00Z")
        subject = create_subject()
        tutor = validate_success(api.create_tutor(create_tutor_payload(), ADMIN), 201)
        t_headers = make_tutor_headers(tutor["id"])
        tag = validate_success(
            api.create_subject_tag({"tutor_id": tutor["id"], "subject_id": subject["id"]}, t_headers), 201
        )
        parent_headers = make_parent_headers("some-parent-id")
        resp = api.approve_subject_tag(tag["id"], parent_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_tutor_cannot_submit_credential_for_other_tutor(self, api):
        """PRD §2.1: "When an entity-backed caller acts on a resource it does not
        own — a tutor operating on another tutor's credential ... — the request is
        rejected with `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/rbac/tutor_cannot_act_on_other_tutors_credential
        """
        set_clock("2026-06-01T00:00:00Z")
        subject = create_subject()
        tutor_a = validate_success(api.create_tutor(create_tutor_payload(), ADMIN), 201)
        tutor_b = validate_success(api.create_tutor(create_tutor_payload(), ADMIN), 201)
        # Tutor B acts (X-User-ID = B) but body names tutor A.
        b_headers = make_tutor_headers(tutor_b["id"])
        resp = api.create_credential(
            {"tutor_id": tutor_a["id"], "subject_id": subject["id"], "kind": "DEGREE", "document_ref": "x"}, b_headers
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


class TestOptimisticConcurrency:
    def test_stale_repropose_rejected(self, api):
        """PRD §2.7: "Before applying the write, the server compares
        `expected_refund_case_version` against the case's current `version`. If
        they differ ... the write is rejected with `ERR_STALE_REFUND_CASE_VERSION`
        and HTTP status 412".

        Design: Corner/cross_cutting/occ_stale_repropose_conflict
        """
        # After the tutor's counter, the version observed at open time is stale.
        mk, std_session, open_case, countered = setup_countered_refund_case(
            claimed_amount_cents=2000, counter_amount_cents=800
        )
        stale_version = open_case["version"]
        assert stale_version != countered["version"], "counter must advance the version"
        resp = api.repropose_refund_case(
            countered["id"],
            {"new_offer_cents": 1500, "expected_refund_case_version": stale_version},
            mk["parent_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_REFUND_CASE_VERSION.value)


class TestRefundCaseWithdraw:
    def test_withdraw_restores_session_settled(self, api):
        """PRD §3.9: "At any point while a case is `PARENT_PROPOSED` or
        `TUTOR_COUNTERED`, the parent may withdraw it, which returns the session's
        `settlement_status` to `SETTLED`, moves no money, and advances the case to
        the terminal `WITHDRAWN`."

        Design: Corner/state_machines/refund_case_withdraw_restores_session_settled
        """
        mk, std_session, case = setup_open_refund_case(claimed_amount_cents=2000)
        withdrawn = validate_success(api.withdraw_refund_case(case["id"], mk["parent_headers"]))
        assert withdrawn["status"] == "WITHDRAWN"
        session_after = validate_success(api.get_session(std_session["id"], mk["parent_headers"]))
        assert session_after["settlement_status"] == "SETTLED"
        tutor = validate_success(api.get_tutor(mk["tutor"]["id"], mk["parent_headers"]))
        # 1500 trial + 4500 std == 6000, unchanged.
        assert tutor["payout_balance_cents"] == 6000
