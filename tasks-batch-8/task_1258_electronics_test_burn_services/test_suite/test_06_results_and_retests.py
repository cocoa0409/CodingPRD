"""Test-result recording gates, the bounded segregation-of-duties retest loop,
authorization expiry, and the append-only result shape (PRD §3.5)."""
from datetime import datetime, timezone

from test_helpers import (
    assert_lot_tally_invariant,
    assert_test_result,
    authorize_retest,
    create_test_result_payload,
    parse_iso8601,
    record_hard_fail,
    record_pass,
    record_soft_fail,
    setup_in_test_lot,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ENG1, ENG2, OPS


class TestRecordingGates:
    def test_bin_not_mapped_rejected(self, api):
        """PRD §3.5: "Finally, the observed `bin_code` must be a key of the pinned
        program's `bin_map`, otherwise `ERR_BIN_NOT_MAPPED`."

        Design: Corner/validations/bin_not_mapped_rejected
        """
        ctx = setup_in_test_lot(quantity=1, part_number="PN-219")
        res = api.create_test_result(
            create_test_result_payload(ctx["units"][0]["id"], ctx["fixture"]["id"],
                                       bin_code=7),
            ENG1,
        )
        validate_error(res, "ERR_BIN_NOT_MAPPED", expected_status=422)
        unit = validate_success(api.get_unit(ctx["units"][0]["id"], ENG1), 200)
        assert unit["test_status"] == "UNTESTED", "rejected insert must persist nothing"

    def test_result_on_passed_unit_rejected(self, api):
        """PRD §3.5: "A unit that stands `PASSED` accepts no further insertions: the
        attempt is rejected with `ERR_RESULT_IMMUTABLE`."

        Design: Corner/validations/result_on_passed_unit_rejected
        """
        ctx = setup_in_test_lot(quantity=1, part_number="PN-231",
                                bin_map={"1": "PASS", "2": "SOFT_FAIL"})
        record_pass(ctx["units"][0], ctx["fixture"]["id"])
        res = api.create_test_result(
            create_test_result_payload(ctx["units"][0]["id"], ctx["fixture"]["id"],
                                       bin_code=2),
            ENG1,
        )
        validate_error(res, "ERR_RESULT_IMMUTABLE", expected_status=409)
        unit = validate_success(api.get_unit(ctx["units"][0]["id"], ENG1), 200)
        assert unit["test_status"] == "PASSED"
        assert unit["retest_count"] == 0, "rejected insert must not manufacture a retest"

    def test_retest_without_active_authorization_rejected(self, api):
        """PRD §3.5: "When the new insertion's index would be 2 or higher, the
        recording must find an `ACTIVE` authorization for the unit — with none
        present the insertion is rejected with `ERR_NO_ACTIVE_AUTHORIZATION` — and
        that authorization must still be live against the logical clock: an
        authorization whose `expires_at` has been reached or passed is treated as
        `EXPIRED` and the insertion is rejected with `ERR_AUTHORIZATION_EXPIRED`."

        Design: Corner/validations/retest_without_active_authorization_rejected
        """
        ctx = setup_in_test_lot(quantity=1, part_number="PN-230",
                                bin_map={"1": "PASS", "2": "SOFT_FAIL"})
        record_soft_fail(ctx["units"][0], ctx["fixture"]["id"])
        # No authorization created: the second insertion has nothing to consume.
        res = api.create_test_result(
            create_test_result_payload(ctx["units"][0]["id"], ctx["fixture"]["id"],
                                       bin_code=1),
            ENG1,
        )
        validate_error(res, "ERR_NO_ACTIVE_AUTHORIZATION", expected_status=409)


class TestRetestPolicyGate:
    def test_retest_authorization_on_passed_unit_returns_invalid_state(self, api):
        """PRD §3.5: "The unit must currently stand `FAILED` — otherwise
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/retest_authorization_on_passed_unit_returns_invalid_state
        """
        ctx = setup_in_test_lot(quantity=1, part_number="PN-209",
                                bin_map={"1": "PASS", "2": "SOFT_FAIL"})
        record_pass(ctx["units"][0], ctx["fixture"]["id"])
        res = api.create_retest_authorization(
            {"unit_id": ctx["units"][0]["id"], "reason": "not needed"}, ENG2
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_hard_fail_bin_not_retestable(self, api):
        """PRD §3.5: "The unit's latest bin must map to `SOFT_FAIL` in the program's
        bin map; units whose latest bin maps to `HARD_FAIL` may never be retested,
        and the request is rejected with `ERR_HARD_FAIL_NO_RETEST`."

        Design: Corner/validations/hard_fail_bin_not_retestable
        """
        ctx = setup_in_test_lot(quantity=1, part_number="PN-218")
        record_hard_fail(ctx["units"][0], ctx["fixture"]["id"])
        res = api.create_retest_authorization(
            {"unit_id": ctx["units"][0]["id"], "reason": "try anyway"}, ENG2
        )
        validate_error(res, "ERR_HARD_FAIL_NO_RETEST", expected_status=422)

    def test_retest_segregation_same_engineer_forbidden(self, api):
        """PRD §3.5: "The authorizing engineer's identity must differ from the
        `recorded_by_user_id` of the unit's latest tally-effective result — the
        engineer who recorded the failure may not authorize its retest, and a
        self-authorization is rejected with `ERR_RETEST_SEGREGATION`."

        Design: Corner/validations/retest_segregation_same_engineer_forbidden
        """
        ctx = setup_in_test_lot(quantity=1, part_number="PN-220",
                                bin_map={"1": "PASS", "2": "SOFT_FAIL"})
        record_soft_fail(ctx["units"][0], ctx["fixture"]["id"], ENG1)
        # eng-1 recorded the failing result; eng-1 may not authorize its retest.
        res = api.create_retest_authorization(
            {"unit_id": ctx["units"][0]["id"], "reason": "self approval attempt"}, ENG1
        )
        validate_error(res, "ERR_RETEST_SEGREGATION", expected_status=403)


class TestRetestLimitBoundary:
    def _setup_unit_at_retest_count_one(self, api):
        """Unit soft-fails insertion 1 (count 0), authorized retest soft-fails
        again (count 1) against a max_retests_per_unit == 2 program."""
        ctx = setup_in_test_lot(quantity=1, part_number="PN-111")
        unit = ctx["units"][0]
        record_soft_fail(unit, ctx["fixture"]["id"], ENG1)
        authorize_retest(unit["id"], reason="retry one", engineer_headers=ENG2)
        record_soft_fail(unit, ctx["fixture"]["id"], ENG1)
        return ctx, unit

    def test_authorization_below_ceiling_succeeds(self, api):
        """PRD §3.5: "And the unit's `retest_count` must be strictly below the
        program's `max_retests_per_unit` — a count already equal to the ceiling is
        rejected with `ERR_RETEST_LIMIT_REACHED`." (Strict less-than: a count one
        below the ceiling is admitted.)

        Design: Difficulty/boundary_precision_check/retest_limit_boundary_at_max
        """
        ctx, unit = self._setup_unit_at_retest_count_one(api)
        unit_now = validate_success(api.get_unit(unit["id"], ENG1), 200)
        assert unit_now["retest_count"] == 1
        # retest_count 1 < max 2: the authorization is granted.
        auth2 = validate_success(
            api.create_retest_authorization(
                {"unit_id": unit["id"], "reason": "retry two at boundary count 1 < 2"},
                ENG2,
            ),
            201,
        )
        assert auth2["status"] == "ACTIVE"

    def test_authorization_at_ceiling_rejected(self, api):
        """PRD §3.5: "And the unit's `retest_count` must be strictly below the
        program's `max_retests_per_unit` — a count already equal to the ceiling is
        rejected with `ERR_RETEST_LIMIT_REACHED`."

        Design: Difficulty/boundary_precision_check/retest_limit_boundary_at_max
        """
        ctx, unit = self._setup_unit_at_retest_count_one(api)
        # Consume the second authorization: count reaches 2 == max.
        authorize_retest(unit["id"], reason="retry two", engineer_headers=ENG2)
        record_soft_fail(unit, ctx["fixture"]["id"], ENG1)
        res = api.create_retest_authorization(
            {"unit_id": unit["id"], "reason": "retry three past boundary count 2 >= 2"},
            ENG2,
        )
        validate_error(res, "ERR_RETEST_LIMIT_REACHED", expected_status=422)
        unit_after = validate_success(api.get_unit(unit["id"], ENG1), 200)
        assert unit_after["retest_count"] == 2, "rejected authorization changed nothing"
        assert unit_after["test_status"] == "FAILED"


class TestRetestCycleLoop:
    def test_failed_self_loop_then_pass_with_consumed_authorizations(self, api):
        """PRD §3.5: "The loop may repeat: a retest that still fails leaves the unit
        `FAILED` and may be authorized again, each cycle consuming one authorization
        and bounded by the retest ceiling, while a passing retest moves the unit to
        `PASSED`."
        PRD §3.5: "A successful retest insertion consumes the authorization — it
        transitions to `CONSUMED` and its id is stored on the result as
        `consumed_authorization_id` — and increments the unit's `retest_count` by
        one."

        Design: Difficulty/non_linear_state_machine/unit_retest_cycle_bounded_loop
        """
        ctx = setup_in_test_lot(quantity=1, part_number="PN-500")
        unit = ctx["units"][0]
        fixture_id = ctx["fixture"]["id"]
        record_soft_fail(unit, fixture_id, ENG1)

        auth1 = authorize_retest(unit["id"], reason="first retry", engineer_headers=ENG2)
        r2 = record_soft_fail(unit, fixture_id, ENG1)
        assert r2["insertion_index"] == 2
        assert r2["consumed_authorization_id"] == auth1["id"]

        auth2 = authorize_retest(unit["id"], reason="second retry", engineer_headers=ENG2)
        r3 = record_pass(unit, fixture_id, ENG1)
        assert r3["insertion_index"] == 3
        assert r3["consumed_authorization_id"] == auth2["id"]

        unit_after = validate_success(api.get_unit(unit["id"], ENG1), 200)
        assert unit_after["test_status"] == "PASSED"
        assert unit_after["retest_count"] == 2
        assert unit_after["current_bin"] == 1

        auth1_after = validate_success(
            api.get_retest_authorization(auth1["id"], ENG2), 200
        )
        assert auth1_after["status"] == "CONSUMED", (
            "exactly one authorization is consumed per retest insertion"
        )

    def test_failed_self_loop_preserves_failed_state(self, api):
        """PRD §3.5: "Replaying a unit's results that are neither voided nor
        excluded — in creation order, with insertion index breaking ties — yields
        the unit's `test_status`: `UNTESTED` when the replay set is empty, `PASSED`
        when the latest effective result passed, and `FAILED` otherwise."
        PRD §3.5: "The loop may repeat: a retest that still fails leaves the unit
        `FAILED` and may be authorized again, each cycle consuming one authorization
        and bounded by the retest ceiling, while a passing retest moves the unit to
        `PASSED`."

        Design: Difficulty/non_linear_state_machine/unit_retest_cycle_bounded_loop
        """
        ctx = setup_in_test_lot(quantity=1, part_number="PN-500")
        unit = ctx["units"][0]
        record_soft_fail(unit, ctx["fixture"]["id"], ENG1)
        auth1 = authorize_retest(unit["id"], reason="first retry", engineer_headers=ENG2)
        record_soft_fail(unit, ctx["fixture"]["id"], ENG1)
        # Self-loop FAILED -> FAILED: one retest consumed, still failing.
        unit_mid = validate_success(api.get_unit(unit["id"], ENG1), 200)
        assert unit_mid["test_status"] == "FAILED"
        assert unit_mid["retest_count"] == 1
        assert unit_mid["current_bin"] == 2
        auth1_mid = validate_success(api.get_retest_authorization(auth1["id"], ENG2), 200)
        assert auth1_mid["status"] == "CONSUMED"


class TestAuthorizationExpiry:
    def test_authorization_expired_after_48h(self, api):
        """PRD §3.5: "A granted authorization begins `ACTIVE` with
        `authorized_by_user_id` recorded and an `expires_at` exactly 48 hours after
        its creation."
        PRD §3.5: "an authorization whose `expires_at` has been reached or passed is
        treated as `EXPIRED` and the insertion is rejected with
        `ERR_AUTHORIZATION_EXPIRED`."
        PRD §2.5: "A retest authorization is likewise treated as `EXPIRED` once its
        `expires_at` is at or before the clock."

        Design: Corner/validations/authorization_expired_after_48h
        """
        ctx = setup_in_test_lot(quantity=1, part_number="PN-221",
                                bin_map={"1": "PASS", "2": "SOFT_FAIL"})
        unit = ctx["units"][0]
        validate_success(api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, OPS), 200)
        record_soft_fail(unit, ctx["fixture"]["id"], ENG1)
        auth = authorize_retest(unit["id"], reason="retry window", engineer_headers=ENG2)
        # created_at + 48h exactly.
        assert parse_iso8601(auth["expires_at"]) == datetime(
            2026, 6, 3, 0, 0, tzinfo=timezone.utc
        ), "expires_at must be exactly 48 hours after creation"

        validate_success(api.set_clock({"to_iso8601": "2026-06-03T01:00:00Z"}, OPS), 200)
        res = api.create_test_result(
            create_test_result_payload(unit["id"], ctx["fixture"]["id"], bin_code=1),
            ENG1,
        )
        validate_error(res, "ERR_AUTHORIZATION_EXPIRED", expected_status=409)
        auth_after = validate_success(api.get_retest_authorization(auth["id"], ENG2), 200)
        assert auth_after["status"] == "EXPIRED", (
            "the lapsed authorization lazily reads back as EXPIRED"
        )


class TestResultEventShape:
    def test_test_result_immutability_no_version_field(self, api):
        """PRD §2.4: "A **TestResult** is the deliberate exception: as an immutable
        event record it carries only `id` and `created_at`. Both `updated_at` and
        `version` are absent from a test result, even after the result is later
        voided."
        PRD §3.5: "Its `insertion_index` is assigned chronologically as the
        one-based count of the unit's tally-effective results including this one —
        so a unit's first effective insertion is index 1."
        PRD §3.5: "The result also denormalizes the unit's `lot_id` and the lot's
        `program_id` onto itself at creation, pinning the exact program revision
        used, and captures the recording engineer's identity as
        `recorded_by_user_id`."

        Design: Corner/entities/test_result_immutability_no_version_field
        """
        ctx = setup_in_test_lot(quantity=1, part_number="PN-203",
                                bin_map={"1": "PASS", "9": "HARD_FAIL"},
                                max_retests_per_unit=1)
        res = api.create_test_result(
            create_test_result_payload(ctx["units"][0]["id"], ctx["fixture"]["id"],
                                       bin_code=1),
            ENG1,
        )
        result = validate_success(res, 201)
        assert_test_result(result)  # enforces absence of updated_at and version
        assert result["insertion_index"] == 1
        assert result["passed"] is True
        assert result["recorded_by_user_id"] == "eng-1"
        assert result["lot_id"] == ctx["lot"]["id"]
        assert result["program_id"] == ctx["program"]["id"]
        assert result["voided"] is False and result["excluded_from_tally"] is False

        fetched = validate_success(api.get_test_result(result["id"], ENG1), 200)
        assert "updated_at" not in fetched and "version" not in fetched


class TestResultListing:
    def test_fk_reverse_lookup_results_by_unit(self, api):
        """PRD §4: "List test results, filterable by unit, lot, fixture, equipment,
        and program" (endpoint table row for `GET /api/test-results`).
        PRD §2.3: "Unless otherwise specified, all list endpoints return resources
        sorted by their creation timestamp in ascending order."
        PRD §3.5: "Its `insertion_index` is assigned chronologically as the
        one-based count of the unit's tally-effective results including this one —
        so a unit's first effective insertion is index 1."

        Design: Corner/endpoints/fk_reverse_lookup_results_by_unit
        """
        ctx = setup_in_test_lot(quantity=1, part_number="PN-234",
                                bin_map={"1": "PASS", "2": "SOFT_FAIL"})
        unit = ctx["units"][0]
        record_soft_fail(unit, ctx["fixture"]["id"], ENG1)
        authorize_retest(unit["id"], reason="retry", engineer_headers=ENG2)
        record_pass(unit, ctx["fixture"]["id"], ENG1)

        rows, meta = validate_paginated(
            api.list_test_results(ENG1, params={"unit_id": unit["id"]})
        )
        assert len(rows) == 2 and meta["total_count"] == 2
        assert rows[0]["bin_code"] == 2, "first row is the original soft-fail"
        assert rows[1]["bin_code"] == 1, "second row is the retest pass"
        assert rows[1]["insertion_index"] == 2


class TestImmediateConsistency:
    def test_immediate_tally_consistency_after_record(self, api):
        """PRD §3.5: "Every insertion recomputes this projection for the unit and
        recomputes the lot's tallies — `units_untested`, `units_passed`, and
        `units_failed` count the units in each status, and the three always sum to
        the lot's `quantity`, before and after any record, void, rework, or escape
        mutation."
        PRD §3.5: "Its `passed` flag is computed as true exactly when the program's
        `bin_map` maps the observed bin to `PASS`."

        Design: Corner/consistency_model/immediate_tally_consistency_after_record
        """
        ctx = setup_in_test_lot(quantity=2, part_number="PN-240",
                                bin_map={"1": "PASS"}, max_retests_per_unit=1)
        result = record_pass(ctx["units"][0], ctx["fixture"]["id"], ENG1)
        assert result["passed"] is True, "computed in-request, not deferred"
        lot = validate_success(api.get_lot(ctx["lot"]["id"], ENG1), 200)
        assert lot["units_passed"] == 1 and lot["units_untested"] == 1, (
            "no reconciliation lag between the write and the follow-up read"
        )
        assert_lot_tally_invariant(lot)
