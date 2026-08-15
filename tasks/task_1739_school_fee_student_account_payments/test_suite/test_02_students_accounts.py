"""Students, accounts, family balance aggregation, posture and graduation gates."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    api_client, ApiErrorId,
    create_student_payload, create_fee_catalog_item_payload,
    setup_open_year, setup_year_with_fee, add_student_with_account,
    setup_account_with_assessment, setup_account_with_collections_case,
    pay_and_settle, set_clock, current_account_version,
    is_valid_uuid, NON_EXISTENT_UUID, CLOCK_DEFAULT_ISO,
)


class TestStudentResource:
    def test_common_fields_system_minted(self, bookkeeper_headers):
        """PRD §2.4: "Before any operator call to set it, the logical clock is
        exactly 2026-08-01T00:00:00Z."
        PRD §2.5: "id (string): a server-minted UUID with no type prefix." and
        "version (integer): a system-managed integer that increments by 1 with
        every modification to the resource."

        Design: Corner/entities/common_fields_system_minted
        """
        resp = api_client.create_student(create_student_payload(
            external_ref="S-1", full_name="Ada", grade_level=10, family_id="fam-a"),
            bookkeeper_headers)
        data = validate_success(resp, 201)
        assert is_valid_uuid(data["id"]), f"Expected a server-minted UUID, got {data['id']}"
        assert data["created_at"].startswith("2026-08-01T00:00:00"), (
            f"created_at must reflect the logical clock default, got {data['created_at']}")
        assert data["version"] == 1
        assert data["status"] == "ENROLLED"

    def test_get_roundtrip_echoes_fields(self, bookkeeper_headers, family_headers):
        """PRD §3.2: "A `Bookkeeper` registers each **student** with an
        external_ref (the district SIS identifier, globally unique), a full_name,
        a grade_level from 9 to 12 — grade 12 students are graduation candidates —
        and a family_id grouping siblings."

        Design: Corner/endpoints/get_roundtrip_echoes_fields
        """
        created = get_success_data(api_client.create_student(
            create_student_payload(external_ref="SIS-99", full_name="Ada Lovelace",
                                   grade_level=10, family_id="fam-a"), bookkeeper_headers))
        resp = api_client.get_student(created["id"], family_headers)
        data = validate_success(resp, 200)
        assert data["external_ref"] == "SIS-99"
        assert data["full_name"] == "Ada Lovelace"
        assert data["grade_level"] == 10
        assert data["family_id"] == "fam-a"

    def test_entity_not_found_returns_404(self, bookkeeper_headers):
        """PRD §2.8: "The first identifier that does not resolve to an existing
        resource fails the request with `ERR_NOT_FOUND` (HTTP 404), and later
        identifiers are not examined."

        Design: Corner/entities/entity_not_found_returns_404
        """
        resp = api_client.get_student(NON_EXISTENT_UUID, bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestStudentAccountDefaults:
    def test_student_account_initial_aggregates_zero(self, bookkeeper_headers):
        """PRD §3.2: "The account records its owning school_year_id and student_id
        and initializes every aggregate to zero with posture `CLEAR`."

        Design: Corner/entities/student_account_initial_aggregates_zero
        """
        env = setup_open_year()
        student = get_success_data(api_client.create_student(
            create_student_payload(), bookkeeper_headers))
        resp = api_client.create_student_account(
            env["year"]["id"], {"student_id": student["id"]}, bookkeeper_headers)
        data = validate_success(resp, 201)
        assert data["assessed_cents"] == 0
        assert data["paid_cents"] == 0
        assert data["waived_cents"] == 0
        assert data["balance_cents"] == 0
        assert data["posture"] == "CLEAR"


class TestFamilyBalance:
    def test_family_balance_sibling_aggregation(self, bookkeeper_headers):
        """PRD §3.2: "family_balance_cents — the sum of balance_cents over all
        accounts whose student shares this student's family_id and whose school
        year is `OPEN`. Every sibling account computes the identical family total."

        Design: Corner/calculations/family_balance_sibling_aggregation
        """
        env = setup_year_with_fee(fee_amount=1000)
        year_id = env["year"]["id"]
        s1, a1 = add_student_with_account(year_id, external_ref="S-1", grade_level=10,
                                          family_id="fam-x", full_name="Ada")
        s2, a2 = add_student_with_account(year_id, external_ref="S-2", grade_level=9,
                                          family_id="fam-x", full_name="Ben")
        s3, a3 = add_student_with_account(year_id, external_ref="S-3", grade_level=11,
                                          family_id="fam-y", full_name="Cid")
        get_success_data(api_client.create_fee_assessment(
            a1["id"], {"fee_item_id": env["fee_item"]["id"], "assessed_amount_cents": 3000},
            bookkeeper_headers))
        get_success_data(api_client.create_fee_assessment(
            a2["id"], {"fee_item_id": env["fee_item"]["id"], "assessed_amount_cents": 2000},
            bookkeeper_headers))
        get_success_data(api_client.create_fee_assessment(
            a3["id"], {"fee_item_id": env["fee_item"]["id"], "assessed_amount_cents": 9000},
            bookkeeper_headers))
        fam1 = get_success_data(api_client.get_student_account(a1["id"], bookkeeper_headers))["family_balance_cents"]
        fam2 = get_success_data(api_client.get_student_account(a2["id"], bookkeeper_headers))["family_balance_cents"]
        fam3 = get_success_data(api_client.get_student_account(a3["id"], bookkeeper_headers))["family_balance_cents"]
        assert fam1 == 5000, f"Sibling A1 family total must be 5000, got {fam1}"
        assert fam2 == 5000, f"Sibling A2 family total must be 5000, got {fam2}"
        assert fam3 == 9000, f"Unrelated fam-y account reports only its own 9000, got {fam3}"


class TestGraduation:
    def test_graduate_non_senior_rejected(self, bookkeeper_headers):
        """PRD §3.2: "Moving a student `ENROLLED` → `GRADUATED` requires grade_level
        exactly 12 — any other grade is rejected with
        `ERR_NOT_GRADUATION_CANDIDATE` (HTTP 422)"

        Design: Corner/validations/graduate_non_senior_rejected
        """
        env = setup_open_year()
        student, account = add_student_with_account(
            env["year"]["id"], grade_level=11)
        resp = api_client.graduate_student(student["id"], bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_GRADUATION_CANDIDATE)

    def test_graduation_hold_threshold_strict_greater(self, bookkeeper_headers):
        """PRD §2.6: "the amount owed must be strictly greater than the threshold;
        an exact tie does not trigger the hold."

        Design: Difficulty/boundary_precision_check/graduation_hold_threshold_strict_greater
        """
        env = setup_account_with_assessment(
            assessed_amount_cents=5000, grade_level=12,
            year_overrides={"graduation_hold_threshold_cents": 5000})
        account_id = env["account"]["id"]
        # Balance 5000 == threshold: posture stays CLEAR
        acct = get_success_data(api_client.get_student_account(account_id, bookkeeper_headers))
        assert acct["balance_cents"] == 5000
        assert acct["posture"] == "CLEAR", (
            f"Balance equal to threshold must not hold; got {acct['posture']}")
        # One more cent crosses the threshold
        get_success_data(api_client.create_fee_assessment(
            account_id, {"fee_item_id": env["fee_item"]["id"], "assessed_amount_cents": 1},
            bookkeeper_headers))
        acct = get_success_data(api_client.get_student_account(account_id, bookkeeper_headers))
        assert acct["balance_cents"] == 5001
        assert acct["posture"] == "GRADUATION_HOLD", (
            f"Balance 5001 > 5000 must hold; got {acct['posture']}")
        resp = api_client.graduate_student(env["student"]["id"], bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_HOLD_BLOCKS_GRADUATION)

    def test_graduation_hold_boundary_below_threshold_clear(self, bookkeeper_headers):
        """PRD §3.2: "Otherwise, when the amount owed — a positive balance_cents —
        is strictly greater than the year's graduation_hold_threshold_cents,
        posture is `GRADUATION_HOLD`; an amount exactly equal to the threshold
        does not hold."

        Design: Difficulty/boundary_precision_check/graduation_hold_threshold_strict_greater
        """
        env = setup_account_with_assessment(
            assessed_amount_cents=4999, grade_level=12,
            year_overrides={"graduation_hold_threshold_cents": 5000})
        acct = get_success_data(api_client.get_student_account(
            env["account"]["id"], bookkeeper_headers))
        assert acct["posture"] == "CLEAR"
        # And the graduate call succeeds for a held-free senior
        resp = api_client.graduate_student(env["student"]["id"], bookkeeper_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "GRADUATED"

    def test_graduation_gated_by_account_posture(self, bookkeeper_headers):
        """PRD §3.2: "Graduation is gated. Moving a student `ENROLLED` → `GRADUATED`
        requires grade_level exactly 12 — any other grade is rejected with
        `ERR_NOT_GRADUATION_CANDIDATE` (HTTP 422) — and requires that no account of
        the student for the current year holds posture `GRADUATION_HOLD` or
        `COLLECTIONS`, otherwise `ERR_ACCOUNT_HOLD_BLOCKS_GRADUATION` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/graduation_gated_by_account_posture
        """
        env = setup_account_with_assessment(
            assessed_amount_cents=6000, grade_level=12,
            year_overrides={"graduation_hold_threshold_cents": 5000})
        account_id = env["account"]["id"]
        # Hold engaged: graduate rejected
        resp = api_client.graduate_student(env["student"]["id"], bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_HOLD_BLOCKS_GRADUATION)
        # Paying the full balance clears the hold
        pay_and_settle(account_id, 6000, idempotency_key="k1")
        acct = get_success_data(api_client.get_student_account(account_id, bookkeeper_headers))
        assert acct["posture"] == "CLEAR"
        resp2 = api_client.graduate_student(env["student"]["id"], bookkeeper_headers)
        data = validate_success(resp2, 200)
        assert data["status"] == "GRADUATED"

    def test_graduation_hold_blocks_then_partial_payment_keeps_block(self, bookkeeper_headers):
        """PRD §3.2: "requires that no account of the student for the current year
        holds posture `GRADUATION_HOLD` or `COLLECTIONS`, otherwise
        `ERR_ACCOUNT_HOLD_BLOCKS_GRADUATION` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/graduation_gated_by_account_posture
        """
        env = setup_account_with_assessment(
            assessed_amount_cents=6000, grade_level=12,
            year_overrides={"graduation_hold_threshold_cents": 5000})
        account_id = env["account"]["id"]
        # Partial payment of 500 leaves balance 5500 > 5000: still on hold
        pay_and_settle(account_id, 500, idempotency_key="k-part")
        acct = get_success_data(api_client.get_student_account(account_id, bookkeeper_headers))
        assert acct["balance_cents"] == 5500
        assert acct["posture"] == "GRADUATION_HOLD"
        resp = api_client.graduate_student(env["student"]["id"], bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_HOLD_BLOCKS_GRADUATION)


class TestWithdrawGates:
    def test_withdraw_blocked_while_in_collections(self, bookkeeper_headers):
        """PRD §3.7: "It is refused while any account of the student holds posture
        `COLLECTIONS` — `ERR_STUDENT_IN_COLLECTIONS` (HTTP 409)."

        Design: Corner/validations/withdraw_blocked_while_in_collections
        """
        env = setup_account_with_collections_case(assessed_amount_cents=3000)
        acct = get_success_data(api_client.get_student_account(
            env["account"]["id"], bookkeeper_headers))
        assert acct["posture"] == "COLLECTIONS"
        resp = api_client.withdraw_student(env["student"]["id"], bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_STUDENT_IN_COLLECTIONS)
        student = get_success_data(api_client.get_student(env["student"]["id"], bookkeeper_headers))
        assert student["status"] == "ENROLLED"

    def test_student_withdraw_twice_terminal_lockdown(self, bookkeeper_headers):
        """PRD §3.2: "A student is born `ENROLLED` and ends either `WITHDRAWN` or
        `GRADUATED`."
        PRD §2.10: "The target resource must be in the from-state its state machine
        requires — otherwise `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/student_withdraw_twice_terminal_lockdown
        """
        env = setup_open_year()
        student, account = add_student_with_account(env["year"]["id"])
        first = api_client.withdraw_student(student["id"], bookkeeper_headers)
        data = validate_success(first, 200)
        assert data["status"] == "WITHDRAWN"
        second = api_client.withdraw_student(student["id"], bookkeeper_headers)
        validate_error(second, ApiErrorId.ERR_INVALID_STATE)
