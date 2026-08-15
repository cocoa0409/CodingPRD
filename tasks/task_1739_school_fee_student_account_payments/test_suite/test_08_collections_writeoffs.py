"""Collections aging buckets, broken-promise cycle, write-off gates, posture."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    setup_account_with_assessment, setup_account_with_collections_case,
    setup_written_off_account, age_account_to_collections,
    advance_case_to_bucket3, pay_and_settle, set_clock,
    make_bookkeeper_headers, make_family_headers, make_superintendent_headers,
)

BK = make_bookkeeper_headers()


class TestAgingBuckets:
    def test_aging_bucket_boundary_at_exactly_k_days(self):
        """PRD §3.8: "The age below k is `CURRENT`; at least k but below twice k
        is `BUCKET_1`; at least twice k but below three times k is `BUCKET_2`;
        three times k or more is `BUCKET_3`. Boundaries include the lower edge
        and exclude the upper."

        Design: Difficulty/boundary_precision_check/aging_bucket_boundary_at_exactly_k_days
        """
        env = setup_account_with_collections_case(
            assessed_amount_cents=2000, case_open_date="2026-08-12")
        case_id = env["case"]["id"]
        # Age 9 days (k-1): still CURRENT
        set_clock("2026-08-21T00:00:00Z")
        get_success_data(api_client.run_ops(env["year"]["id"], BK))
        case = get_success_data(api_client.get_collections_case(
            env["account"]["id"], case_id, BK))
        assert case["aging_bucket"] == "CURRENT", (
            f"Age 9 < k=10 must stay CURRENT; got {case['aging_bucket']}")
        # Age exactly 10 days (k): flips to BUCKET_1 (lower edge inclusive)
        set_clock("2026-08-22T00:00:00Z")
        get_success_data(api_client.run_ops(env["year"]["id"], BK))
        case = get_success_data(api_client.get_collections_case(
            env["account"]["id"], case_id, BK))
        assert case["aging_bucket"] == "BUCKET_1", (
            f"Age exactly k=10 must be BUCKET_1 (>= lower edge); got {case['aging_bucket']}")

    def test_aging_bucket_upper_edge_exclusive(self):
        """PRD §3.8: "at least twice k but below three times k is `BUCKET_2`;
        three times k or more is `BUCKET_3`. Boundaries include the lower edge
        and exclude the upper."

        Design: Difficulty/boundary_precision_check/aging_bucket_boundary_at_exactly_k_days
        """
        env = setup_account_with_collections_case(
            assessed_amount_cents=2000, case_open_date="2026-08-12")
        case_id = env["case"]["id"]
        # Age 29 days (< 3k=30): BUCKET_2
        set_clock("2026-09-10T00:00:00Z")
        get_success_data(api_client.run_ops(env["year"]["id"], BK))
        case = get_success_data(api_client.get_collections_case(
            env["account"]["id"], case_id, BK))
        assert case["aging_bucket"] == "BUCKET_2", (
            f"Age 29 in [2k, 3k) must be BUCKET_2; got {case['aging_bucket']}")
        # Age 30 days (== 3k): BUCKET_3
        set_clock("2026-09-11T00:00:00Z")
        get_success_data(api_client.run_ops(env["year"]["id"], BK))
        case = get_success_data(api_client.get_collections_case(
            env["account"]["id"], case_id, BK))
        assert case["aging_bucket"] == "BUCKET_3", (
            f"Age 30 >= 3k must be BUCKET_3; got {case['aging_bucket']}")

    def test_posture_collections_precedence_over_graduation_hold(self):
        """PRD §3.2: "If the account has a collections case in `WRITTEN_OFF`
        status, posture is `WRITTEN_OFF`. Otherwise, if the account has a case
        `OPEN` or `PAYMENT_PROMISED`, posture is `COLLECTIONS`. Otherwise, when
        the amount owed — a positive balance_cents — is strictly greater than the
        year's graduation_hold_threshold_cents, posture is `GRADUATION_HOLD`"

        Design: Corner/calculations/posture_collections_precedence_over_graduation_hold
        """
        env = setup_account_with_assessment(assessed_amount_cents=8000)
        set_clock("2026-08-12T00:00:00Z")
        get_success_data(api_client.run_ops(env["year"]["id"], BK))
        account = get_success_data(api_client.get_student_account(
            env["account"]["id"], BK))
        assert account["balance_cents"] == 8000, (
            f"8000 > threshold 5000 would alone hold; got {account['balance_cents']}")
        assert account["posture"] == "COLLECTIONS", (
            f"Open case takes precedence over the threshold branch; got {account['posture']}")


class TestBrokenPromiseCycle:
    def test_collections_case_broken_promise_cycle(self):
        """PRD §3.8: "Fourth, a `PAYMENT_PROMISED` case with no `SUCCEEDED`
        payment created after the promise timestamp reverts to `OPEN` — the
        broken-promise loop."
        PRD §3.8: "Between sweeps, a `Bookkeeper` may record a payment promise,
        moving a case `OPEN` → `PAYMENT_PROMISED`"

        Design: Difficulty/non_linear_state_machine/collections_case_broken_promise_cycle
        """
        env = setup_account_with_collections_case(
            assessed_amount_cents=3000, case_open_date="2026-08-12")
        case_id = env["case"]["id"]
        assert env["case"]["status"] == "OPEN"
        promised = get_success_data(api_client.promise_collections_case(
            env["account"]["id"], case_id, BK))
        assert promised["status"] == "PAYMENT_PROMISED"
        # No SUCCEEDED payment intervenes; next sweep reverts the case
        set_clock("2026-08-20T00:00:00Z")
        get_success_data(api_client.run_ops(env["year"]["id"], BK))
        case = get_success_data(api_client.get_collections_case(
            env["account"]["id"], case_id, BK))
        assert case["status"] == "OPEN", (
            f"Broken promise reverts PAYMENT_PROMISED -> OPEN; got {case['status']}")
        # age 8 days < k=10 -> CURRENT
        assert case["aging_bucket"] == "CURRENT"

    def test_case_resolves_when_balance_settles(self):
        """PRD §3.8: "Cases resolve themselves: whenever a payment settlement
        drives the account's balance_cents to zero or below, an `OPEN` or
        `PAYMENT_PROMISED` case becomes `RESOLVED` and posture recomputes,
        clearing `COLLECTIONS`."

        Design: Difficulty/non_linear_state_machine/collections_case_broken_promise_cycle
        """
        env = setup_account_with_collections_case(
            assessed_amount_cents=3000, case_open_date="2026-08-12")
        account_id = env["account"]["id"]
        pay_and_settle(account_id, 3000, idempotency_key="k1")
        case = get_success_data(api_client.get_collections_case(
            account_id, env["case"]["id"], BK))
        assert case["status"] == "RESOLVED"
        account = get_success_data(api_client.get_student_account(account_id, BK))
        assert account["posture"] == "CLEAR"


class TestWriteOffGates:
    def test_case_not_aged_writeoff_rejected(self):
        """PRD §3.8: "The case must have aged to `BUCKET_3`, else
        `ERR_CASE_NOT_AGED` (HTTP 409)."

        Design: Corner/validations/case_not_aged_writeoff_rejected
        """
        env = setup_account_with_collections_case(
            assessed_amount_cents=3000, case_open_date="2026-08-12")
        # Age 20 days with k=10 -> BUCKET_2
        set_clock("2026-09-01T00:00:00Z")
        get_success_data(api_client.run_ops(env["year"]["id"], BK))
        case = get_success_data(api_client.get_collections_case(
            env["account"]["id"], env["case"]["id"], BK))
        assert case["aging_bucket"] == "BUCKET_2"
        resp = api_client.write_off_case(
            env["account"]["id"], case["id"], {"amount_cents": 3000},
            make_bookkeeper_headers("bk-1"))
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_AGED)

    def test_writeoff_above_limit_needs_superintendent(self):
        """PRD §3.8: "When the requested amount_cents exceeds the year's
        writeoff_max_cents, the case's approved_writeoff_cents must cover the
        requested amount — that coverage is the `Superintendent`'s co-approval,
        recorded by supplying approved_writeoff_cents — else
        `ERR_WRITEOFF_NEEDS_APPROVAL` (HTTP 403)."

        Design: Corner/validations/writeoff_above_limit_needs_superintendent
        """
        env = setup_account_with_collections_case(
            assessed_amount_cents=200000, case_open_date="2026-08-12")
        advance_case_to_bucket3(env, "2026-09-11")
        case = get_success_data(api_client.get_collections_case(
            env["account"]["id"], env["case"]["id"], BK))
        assert case["aging_bucket"] == "BUCKET_3", "aging gate satisfied — only approval fails"
        resp = api_client.write_off_case(
            env["account"]["id"], case["id"], {"amount_cents": 200000},
            make_bookkeeper_headers("bk-1"))
        validate_error(resp, ApiErrorId.ERR_WRITEOFF_NEEDS_APPROVAL)

    def test_writeoff_sod_rejected_then_other_user_succeeds(self):
        """PRD §3.8: "And the write-off actor's `X-User-ID` must differ from the
        identifier that recorded the most recent `SUCCEEDED` payment on the
        account, when such a payment exists, else `ERR_WRITEOFF_SOD` (HTTP 403)."

        Design: Corner/validations/writeoff_sod_rejected_then_other_user_succeeds
        """
        env = setup_account_with_assessment(assessed_amount_cents=8000)
        account_id = env["account"]["id"]
        # fam-7 records the most recent SUCCEEDED payment on the account
        pay_and_settle(account_id, 2000, idempotency_key="k1", method="CASH",
                       family_user_id="fam-7")
        cases = age_account_to_collections(env, "2026-08-12")
        env["case"] = cases[0]  # advance_case_to_bucket3 reads env["case"]
        advance_case_to_bucket3(env, "2026-09-11")
        case_id = cases[0]["id"]
        resp = api_client.write_off_case(
            account_id, case_id, {"amount_cents": 6000},
            make_bookkeeper_headers("fam-7"))
        validate_error(resp, ApiErrorId.ERR_WRITEOFF_SOD)
        ok = get_success_data(api_client.write_off_case(
            account_id, case_id, {"amount_cents": 6000},
            make_bookkeeper_headers("bk-2")))
        assert ok["status"] == "WRITTEN_OFF"
        assert ok["written_off_cents"] == 6000

    def test_writeoff_within_limit_succeeds_without_coapproval(self):
        """PRD §3.8: "Executing the write-off sets the case's written_off_cents
        to the amount and moves the case to `WRITTEN_OFF`."
        PRD §3.8: "The account's posture becomes `WRITTEN_OFF` and the family
        balance recomputes; every assessment still `DELINQUENT` or `ASSESSED`
        under the case moves to `VOID`, its obligation zeroed through the
        write-off ledger so the reconciliation invariant holds."

        Design: Corner/validations/case_not_aged_writeoff_rejected
        """
        env = setup_written_off_account(assessed_amount_cents=3000,
                                        writeoff_user_id="bk-9")
        assert env["case"]["status"] == "WRITTEN_OFF"
        account = get_success_data(api_client.get_student_account(
            env["account"]["id"], BK))
        assert account["posture"] == "WRITTEN_OFF"
        assert account["balance_cents"] == 0


class TestWrittenOffAccountGate:
    def test_settle_on_written_off_account_state_beats_fiscal(self):
        """PRD §2.10: "Checks run in ascending priority order, and the first
        failing check determines the error returned — an earlier failure masks
        later ones." Rung 6 (From-state) precedes rung 16 (Overpayment policy).
        PRD §3.5: "Settling requires the payment to be `PENDING`, else
        `ERR_INVALID_STATE`, and refuses accounts in `WRITTEN_OFF` posture with
        `ERR_ACCOUNT_WRITTEN_OFF` (HTTP 409)."
        PRD §3.8: "From then on, payment settlement against the account is
        refused with `ERR_ACCOUNT_WRITTEN_OFF`."

        Design: Difficulty/priority_pair_validation_conflict/settle_on_written_off_account_state_beats_fiscal
        """
        env = setup_written_off_account(assessed_amount_cents=3000,
                                        writeoff_user_id="bk-9")
        account_id = env["account"]["id"]
        payment = get_success_data(api_client.create_payment(
            account_id,
            {"amount_cents": 999999, "method": "CARD", "idempotency_key": "k9",
             "overpayment_policy": "REJECT"},
            make_family_headers()))
        resp = api_client.settle_payment(account_id, payment["id"],
                                         {"outcome": "SUCCEEDED"},
                                         make_family_headers())
        # State gate (rung 6) masks the overpayment ceiling check (rung 16)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_WRITTEN_OFF)
        payment_now = get_success_data(api_client.get_payment(account_id, payment["id"], BK))
        assert payment_now["status"] == "PENDING", "no allocation rows written"

    def test_settle_written_off_rejects_even_exact_amount(self):
        """PRD §3.8: "From then on, payment settlement against the account is
        refused with `ERR_ACCOUNT_WRITTEN_OFF`."

        Design: Difficulty/priority_pair_validation_conflict/settle_on_written_off_account_state_beats_fiscal
        """
        env = setup_written_off_account(assessed_amount_cents=3000,
                                        writeoff_user_id="bk-9")
        account_id = env["account"]["id"]
        payment = get_success_data(api_client.create_payment(
            account_id, {"amount_cents": 100, "method": "CARD",
                         "idempotency_key": "k-small"}, make_family_headers()))
        resp = api_client.settle_payment(account_id, payment["id"],
                                         {"outcome": "SUCCEEDED"}, make_family_headers())
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_WRITTEN_OFF)


class TestExistencePrecedence:
    def test_existence_beats_state_on_settle(self):
        """PRD §2.10: "Checks run in ascending priority order, and the first
        failing check determines the error returned — an earlier failure masks
        later ones." Rung 3 (Path existence) precedes rung 6 (From-state).
        PRD §2.8: "The first identifier that does not resolve to an existing
        resource fails the request with `ERR_NOT_FOUND` (HTTP 404)"

        Design: Corner/validations/existence_beats_state_on_settle
        """
        from test_helpers import NON_EXISTENT_UUID
        env = setup_written_off_account(assessed_amount_cents=3000,
                                        writeoff_user_id="bk-9")
        resp = api_client.settle_payment(env["account"]["id"], NON_EXISTENT_UUID,
                                         {"outcome": "SUCCEEDED"},
                                         make_family_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
