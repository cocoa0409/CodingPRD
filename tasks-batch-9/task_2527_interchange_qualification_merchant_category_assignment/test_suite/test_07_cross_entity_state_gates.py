"""Writes gated on the state of a different entity, where only that other
entity's state changes between the refusal and the success.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.factories import make_incentive_enrollment_payload
from test_helpers.fixtures import (
    add_record,
    board_merchant,
    canonical_environment,
    complete_window,
    create_incentive_program,
    draft_rate_version,
    finalize_batch,
    open_batch,
    publish_rate_version,
    read_batch,
    read_incentive_program,
    read_record,
    schedule_window,
    set_clock,
    submit_batch,
    verify_merchant,
)
from test_helpers.test_users import TEST_USERS

ANALYST = "CAN-1"
FOUR_ELEMENTS = ["AUTH_CODE", "TERMINAL_ID", "TRANSACTION_DATE", "CARDHOLDER_ZIP"]


def _utility_merchant_awaiting_verification():
    """MCC 4900 requires documentation, so the boarded merchant stops in
    `PENDING_VERIFICATION`."""
    env = canonical_environment(
        "2026-09-03T00:00:00Z", mcc_codes=("4900",), program_keys=()
    )
    acquirer_id = env["acquirer"]["id"]
    program = create_incentive_program(
        program_name="Utility Growth 2026",
        eligible_mcc_codes=["4900"],
        total_capacity_cents=100000000,
        min_commitment_cents=5000000,
        reopen_threshold_cents=5000000,
        performance_threshold_pct=80.00,
    )
    merchant = board_merchant(
        acquirer_id, "UTILITY_SERVICE", legal_name="Riverside Power"
    )
    return {
        "acquirer_id": acquirer_id,
        "acquirer_headers": env["acquirer_headers"],
        "program": program,
        "merchant": merchant,
    }


def _enrollment_payload(state):
    return make_incentive_enrollment_payload(
        state["program"]["id"],
        state["merchant"]["id"],
        5000000,
        state["program"]["version"],
        waitlist_requested=False,
    )


class TestEnrollmentGatedOnMerchantVerification:
    def test_enrollment_is_refused_while_the_merchant_awaits_verification(self):
        """The merchant's documentation-gated category leaves it in
        `PENDING_VERIFICATION`, and that state alone blocks the enrollment.

        PRD 3.8: "The merchant must be `VERIFIED` — a merchant still in
        `PENDING_VERIFICATION` is refused with `ERR_MERCHANT_NOT_VERIFIED`, one held
        `UNDER_REVIEW` by an audit is refused with
        `ERR_MERCHANT_UNDER_CATEGORY_REVIEW`, and one in `MISREPRESENTED` is refused
        with `ERR_MERCHANT_MISREPRESENTED` — and the merchant's `assigned_mcc` must
        appear in the program's `eligible_mcc_codes`, failing which the refusal is
        `ERR_MCC_NOT_ELIGIBLE_FOR_PROGRAM`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_enrollment_blocked_until_merchant_mcc_status_becomes_verified
        """
        state = _utility_merchant_awaiting_verification()
        assert state["merchant"]["assigned_mcc"] == "4900"
        assert state["merchant"]["mcc_status"] == "PENDING_VERIFICATION"

        response = api_client.create_incentive_enrollment(
            _enrollment_payload(state), state["acquirer_headers"]
        )
        validate_error(response, "ERR_MERCHANT_NOT_VERIFIED", 409)

    def test_verifying_the_merchant_unblocks_the_identical_enrollment_call(self):
        """Nothing in the enrollment payload changes — only the merchant's
        `mcc_status` — and the same request then admits the merchant to the pool.

        PRD 3.3: "On success the supplied value is stored as `documentation_ref`,
        the acting operator's identity is recorded as `verified_by_user_id`, and
        `Merchant.version` advances by 1."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_enrollment_blocked_until_merchant_mcc_status_becomes_verified
        """
        state = _utility_merchant_awaiting_verification()
        api_client.create_incentive_enrollment(
            _enrollment_payload(state), state["acquirer_headers"]
        )

        verified = verify_merchant(
            state["merchant"]["id"], "DOC-UTIL-2026-0001", analyst_user_id=ANALYST
        )
        assert verified["mcc_status"] == "VERIFIED"
        assert verified["documentation_ref"] == "DOC-UTIL-2026-0001"
        assert verified["verified_by_user_id"] == ANALYST

        retry = api_client.create_incentive_enrollment(
            _enrollment_payload(state), state["acquirer_headers"]
        )
        enrollment = validate_success(retry, 201)
        assert enrollment["status"] == "ENROLLED"

        program = read_incentive_program(state["program"]["id"])
        assert program["uncommitted_capacity_cents"] == 95000000
        assert program["enrolled_count"] == 1


def _acquirer_made_non_compliant_by_a_missed_window():
    """The sweep past 2026-09-10 marks the scheduled window `MISSED`, which flips
    the acquirer out of `COMPLIANT` while an unrelated batch waits in
    `SUBMITTED`."""
    env = canonical_environment(
        "2026-09-01T12:00:00Z", program_keys=("CPS_RETAIL", "STANDARD")
    )
    acquirer_id = env["acquirer"]["id"]
    acquirer_headers = env["acquirer_headers"]
    version = draft_rate_version(
        env["programs"]["CPS_RETAIL"]["id"],
        "2026Q4",
        "2026-10-01T00:00:00Z",
        "2027-01-01T00:00:00Z",
        "2026-09-30T00:00:00Z",
        base_rate_bps=150,
        per_item_fee_cents=10,
    )
    published = publish_rate_version(version["id"])
    window = schedule_window(
        acquirer_id,
        version["id"],
        env["platform"]["id"],
        "2026-09-05T00:00:00Z",
        "2026-09-10T00:00:00Z",
        headers=acquirer_headers,
    )
    merchant = board_merchant(acquirer_id, "GROCERY", legal_name="Corner Grocer")
    batch = open_batch(acquirer_id, "2026-09-01", "USD")
    record = add_record(
        batch["id"],
        merchant["id"],
        100000,
        acquirer_id,
        expected_batch_version=batch["version"],
        auth_code="A00090",
        auth_timestamp="2026-09-01T00:00:00Z",
        clearing_timestamp="2026-09-01T02:00:00Z",
        data_elements=FOUR_ELEMENTS,
    )
    submit_batch(batch["id"], acquirer_id)
    set_clock("2026-09-20T00:00:00Z")
    return {
        "acquirer_id": acquirer_id,
        "acquirer_headers": acquirer_headers,
        "published_at": published["published_at"],
        "window": window,
        "batch": batch,
        "record": record,
    }


def _read_window(window_id):
    return validate_success(
        api_client.get_implementation_window(
            window_id, TEST_USERS["network_admin_headers"]
        )
    )


def _read_acquirer(acquirer_id):
    return validate_success(
        api_client.get_acquirer(acquirer_id, TEST_USERS["network_admin_headers"])
    )


class TestFinalizationGatedOnAcquirerCompliance:
    def test_a_missed_window_two_entities_away_blocks_finalization(self):
        """The blocking state was produced by the clock sweep rather than by any
        operator call, and it locks a batch that has nothing to do with the window.

        PRD 3.2: "Whenever a recomputation leaves the count greater than zero and
        the acquirer is `COMPLIANT`, the acquirer moves `COMPLIANT →
        NON_COMPLIANT`; while it is `NON_COMPLIANT`, finalization of *any* of its
        settlement batches is refused with `ERR_ACQUIRER_NON_COMPLIANT`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_batch_finalize_blocked_by_acquirer_compliance_status_from_missed_window
        """
        state = _acquirer_made_non_compliant_by_a_missed_window()
        assert state["published_at"] == "2026-09-01T12:00:00.000Z"
        assert _read_window(state["window"]["id"])["status"] == "MISSED"
        assert _read_acquirer(state["acquirer_id"])["compliance_status"] == "NON_COMPLIANT"

        response = api_client.finalize_settlement_batch(
            state["batch"]["id"], TEST_USERS["network_admin_headers"]
        )
        validate_error(response, "ERR_ACQUIRER_NON_COMPLIANT", 409)
        assert read_batch(state["batch"]["id"])["status"] == "SUBMITTED"

    def test_completing_the_window_late_restores_compliance_and_unblocks_finalize(self):
        """Late completion is a genuine remedy: the count returns to zero, the
        acquirer is `COMPLIANT` again and the same finalize call now books money.

        PRD 3.2: "Whenever a recomputation brings the count back to zero and the
        acquirer is `NON_COMPLIANT`, it moves `NON_COMPLIANT → COMPLIANT` and
        finalization is unblocked."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_batch_finalize_blocked_by_acquirer_compliance_status_from_missed_window
        """
        state = _acquirer_made_non_compliant_by_a_missed_window()
        api_client.finalize_settlement_batch(
            state["batch"]["id"], TEST_USERS["network_admin_headers"]
        )

        completed = complete_window(
            state["window"]["id"],
            headers=state["acquirer_headers"],
            completion_note="Certified late on 2026-09-20",
        )
        assert completed["status"] == "COMPLETED_LATE"

        acquirer = _read_acquirer(state["acquirer_id"])
        assert acquirer["missed_window_count"] == 0
        assert acquirer["compliance_status"] == "COMPLIANT"

        finalized = finalize_batch(state["batch"]["id"])
        assert finalized["status"] == "FINALIZED"

        record = read_record(state["record"]["id"])
        assert record["qualification_status"] == "QUALIFIED"
        assert record["assessed_interchange_cents"] == 1460
        assert read_batch(state["batch"]["id"])["total_assessed_cents"] == 1460
