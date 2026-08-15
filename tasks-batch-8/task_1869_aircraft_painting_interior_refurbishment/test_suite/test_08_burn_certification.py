"""Soft-goods burn certification: bounded retest cycle, quarantine (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_burn_test,
    assert_soft_good_lot,
    create_engagement,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    create_soft_good_lot_payload,
    record_burn_test_payload,
)

_TECH = TEST_USERS["shop_technician_headers"]


def _create_lot(api, program_id: str, **overrides) -> dict:
    resp = api.create_soft_good_lot(
        create_soft_good_lot_payload(program_id=program_id, **overrides), _TECH
    )
    return validate_success(resp, 201)


def _record(api, lot_id: str, result: str, method: str = "VERTICAL_12S"):
    return api.record_burn_test(
        lot_id, record_burn_test_payload(test_method=method, result=result), _TECH
    )


def _get_lot(api, lot_id: str) -> dict:
    return validate_success(api.get_soft_good_lot(lot_id, _TECH))


class TestBoundedRetestCycle:
    def test_fail_fail_fail_walks_to_quarantine(self, api):
        """PRD §3.8: "The first test recorded moves the lot from `UNCERTIFIED`
        to `IN_TEST`. From there, each new test is judged as the latest: a
        `PASS` moves the lot to `CERTIFIED`; a `FAIL` increments `fail_count`
        and moves the lot to `CERT_FAILED` when the resulting count is below
        three, or to `CERT_QUARANTINED` — terminal — when the count reaches
        three. A `CERT_FAILED` lot returns to `IN_TEST` when a further test is
        recorded".

        Design: Difficulty/non_linear_state_machine/soft_good_lot_bounded_retest_cycle
        """
        ctx = create_engagement()
        lot = _create_lot(api, ctx["program"]["id"],
                          description="Sidewall panels", material="Nomex composite",
                          quantity=12, estimated_weight_lbs=140.0)
        assert lot["status"] == "UNCERTIFIED"
        assert lot["fail_count"] == 0

        validate_success(_record(api, lot["id"], "FAIL"), 201)
        lot = _get_lot(api, lot["id"])
        assert lot["status"] == "CERT_FAILED" and lot["fail_count"] == 1

        validate_success(_record(api, lot["id"], "FAIL"), 201)
        lot = _get_lot(api, lot["id"])
        assert lot["status"] == "CERT_FAILED" and lot["fail_count"] == 2, (
            "CERT_FAILED -> IN_TEST -> CERT_FAILED cycle edge traversed by the next test"
        )

        validate_success(_record(api, lot["id"], "FAIL", method="VERTICAL_60S"), 201)
        lot = _get_lot(api, lot["id"])
        assert lot["status"] == "CERT_QUARANTINED" and lot["fail_count"] == 3

    def test_quarantined_lot_rejects_further_tests(self, api):
        """PRD §3.8: "Tests may not be recorded against lots already
        `CERTIFIED` or `CERT_QUARANTINED`." PRD §2.10: "**State validity** — the
        entity is in a valid from-state for the requested transition, including
        terminal lockdown (`ERR_INVALID_STATE`, 409)".

        Design: Difficulty/non_linear_state_machine/soft_good_lot_bounded_retest_cycle
        """
        ctx = create_engagement()
        lot = _create_lot(api, ctx["program"]["id"], description="Sidewall panels")
        for _ in range(3):
            validate_success(_record(api, lot["id"], "FAIL"), 201)
        assert _get_lot(api, lot["id"])["status"] == "CERT_QUARANTINED"

        resp = _record(api, lot["id"], "PASS")
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestRetestCountBoundary:
    def test_two_fails_leave_lot_retestable(self, api):
        """PRD §3.8: "a `FAIL` increments `fail_count` and moves the lot to
        `CERT_FAILED` when the resulting count is below three, or to
        `CERT_QUARANTINED` — terminal — when the count reaches three."

        Design: Difficulty/boundary_precision_check/retest_count_third_fail_quarantines
        """
        ctx = create_engagement()
        lot = _create_lot(api, ctx["program"]["id"], description="Carpet roll",
                          material="Wool blend", quantity=4, estimated_weight_lbs=60.0)
        validate_success(_record(api, lot["id"], "FAIL", method="HORIZONTAL_25"), 201)
        validate_success(_record(api, lot["id"], "FAIL", method="HORIZONTAL_25"), 201)
        lot = _get_lot(api, lot["id"])
        assert lot["status"] == "CERT_FAILED" and lot["fail_count"] == 2, (
            "one FAIL below the cap: still retestable"
        )

    def test_third_fail_reaches_cap_and_quarantines(self, api):
        """PRD §3.8: "or to `CERT_QUARANTINED` — terminal — when the count
        reaches three."

        Design: Difficulty/boundary_precision_check/retest_count_third_fail_quarantines
        """
        ctx = create_engagement()
        lot = _create_lot(api, ctx["program"]["id"], description="Carpet roll")
        for _ in range(3):
            validate_success(_record(api, lot["id"], "FAIL", method="HORIZONTAL_25"), 201)
        lot = _get_lot(api, lot["id"])
        assert lot["status"] == "CERT_QUARANTINED"
        assert lot["fail_count"] == 3, "exactly-at-cap triggers quarantine (>= not >)"


class TestBurnTestRecordShape:
    def test_burn_test_record_is_append_only(self, api):
        """PRD §2.5: "One entity is deliberately exempt: a **Burn Test** is an
        append-only record and carries only `id` and `created_at` — both
        `updated_at` and `version` are absent, because a recorded test result
        is never modified after the fact." PRD §3.8: "Each test receives the
        next per-lot `test_sequence`, a monotone sequence starting at one".

        Design: Corner/entities/burn_test_record_is_immutable
        """
        ctx = create_engagement()
        lot = _create_lot(api, ctx["program"]["id"], description="Carpet roll")
        resp = _record(api, lot["id"], "PASS")
        record = validate_success(resp, 201)
        assert_burn_test(record)  # asserts no updated_at / version keys
        assert record["test_sequence"] == 1
        assert record["lot_id"] == lot["id"]
        assert record["result"] == "PASS"
        assert record["lab_name"] == "AeroBurn Labs"
