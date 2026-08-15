"""Recovery desk operations, claim settlement gating, and customer
communication logging."""
import pytest

from test_helpers import (
    ADJUSTER,
    DEFAULT_LOGICAL_CLOCK,
    DESK,
    RECOVERY,
    SETTLEMENT,
    ApiErrorId,
    api_client,
    assert_communication_log,
    assert_recovery_case,
    assert_recovery_case_conservation,
    assert_timestamp_matches_clock,
    create_communication_log_payload,
    get_claim_view,
    list_claim_communications,
    open_claim,
    record_recovery_payment_payload,
    register_policyholder,
    setup_authorized_rental_scenario,
    setup_overstay_recovery_scenario,
    setup_settled_childless_claim,
    validate_error,
    validate_success,
)


class TestRecoveryDesk:
    def test_recovery_waive_on_terminal_rejected(self, api):
        """PRD §3.9: "Recording a payment requires an `amount_cents` of at least
        one and no more than the current outstanding amount — anything outside
        that range is `ERR_INVALID_REQUEST` — and any collection action on a
        `CLOSED` or `WAIVED` case is `ERR_RECOVERY_INVALID_STATE`."

        Design: Corner/state_machines/recovery_waive_on_terminal_rejected
        """
        ctx = setup_overstay_recovery_scenario()
        case_id = ctx["recovery_case"]["id"]
        validate_success(api.waive_recovery_case(case_id, RECOVERY), 200)

        resp = api.waive_recovery_case(case_id, RECOVERY)
        validate_error(resp, ApiErrorId.ERR_RECOVERY_INVALID_STATE)

    def test_partial_payment_moves_case_to_partial_recovery(self, api):
        """PRD §3.9: "A payment smaller than the outstanding amount moves the case
        from `OPEN` to `PARTIAL_RECOVERY`; a payment exactly equal to the
        outstanding amount closes it. Either way, `recovered_amount_cents` grows
        by the payment, the outstanding amount is recomputed under the invariant,
        the claim's `recovery_balance_cents` falls by the payment, and the claim's
        `version` increments."

        Design: Difficulty/compensating_invariant/recovery_payment_waive_conservation
        """
        ctx = setup_overstay_recovery_scenario()
        case = ctx["recovery_case"]
        assert case["assessed_amount_cents"] == 12000, (
            f"Setup: 2 unnecessary days x 6000 == 12000, "
            f"got {case['assessed_amount_cents']}"
        )

        resp = api.record_recovery_payment(
            case["id"], record_recovery_payment_payload(5000), RECOVERY)
        updated = validate_success(resp, 200)
        assert updated["status"] == "PARTIAL_RECOVERY"
        assert updated["recovered_amount_cents"] == 5000
        assert updated["outstanding_amount_cents"] == 7000
        assert_recovery_case_conservation(updated)
        assert get_claim_view(ctx["claim"]["id"])["recovery_balance_cents"] == 7000

    def test_waive_after_payment_conserves_assessed_amount(self, api):
        """PRD §2.6: "Every recovery case obeys its own conservation invariant at
        all times: `assessed_amount_cents` always equals the sum of
        `recovered_amount_cents`, `waived_amount_cents`, and
        `outstanding_amount_cents` — equivalently, the outstanding amount is the
        assessed amount minus what has been recovered and what has been waived."
        PRD §3.9: "Where recovery is not worth the candle, the specialist may
        instead waive the case from `OPEN` or `PARTIAL_RECOVERY`: the
        `waived_amount_cents` is set to the then-outstanding amount, the
        outstanding amount goes to zero, the claim's recovery balance falls by the
        waived amount with a version increment, and the case lands in `WAIVED`.
        Both `CLOSED` and `WAIVED` are terminal."

        Design: Difficulty/compensating_invariant/recovery_payment_waive_conservation
        """
        ctx = setup_overstay_recovery_scenario()
        case_id = ctx["recovery_case"]["id"]
        validate_success(api.record_recovery_payment(
            case_id, record_recovery_payment_payload(5000), RECOVERY), 200)

        resp = api.waive_recovery_case(case_id, RECOVERY)
        waived = validate_success(resp, 200)
        assert_recovery_case(waived)
        assert waived["status"] == "WAIVED"
        assert waived["recovered_amount_cents"] == 5000
        assert waived["waived_amount_cents"] == 7000
        assert waived["outstanding_amount_cents"] == 0
        assert_recovery_case_conservation(waived)
        assert get_claim_view(ctx["claim"]["id"])["recovery_balance_cents"] == 0, (
            "The claim's recovery balance must return to 0 once the case is "
            "terminal"
        )


class TestClaimSettlement:
    def test_claim_settle_blocked_with_open_reservation(self, api):
        """PRD §3.9: "Settlement is a `SettlementApprover` action requiring
        `overall_status` to be `OPEN`, and three conditions must all hold, with
        any shortfall rejected as `ERR_CLAIM_SETTLE_BLOCKED`: every reservation on
        the claim must be terminal — `CLOSED` or `CANCELLED` — or none may exist;
        every loss-of-use claim must be terminal — `PAID` or `DENIED` — or none
        may exist; and the claim's `recovery_balance_cents` must be exactly zero,
        meaning every recovery case has been collected in full or waived."

        Design: Corner/state_machines/claim_settle_blocked_with_open_reservation
        """
        ctx = setup_authorized_rental_scenario()  # AUTHORIZED = non-terminal
        resp = api.settle_claim(ctx["claim"]["id"], SETTLEMENT)
        validate_error(resp, ApiErrorId.ERR_CLAIM_SETTLE_BLOCKED)

    def test_claim_close_state_sequence_enforced(self, api):
        """PRD §3.9: "Closing is the final act, again a `SettlementApprover`
        action, and it alone among claim mutations requires the claim to be
        `SETTLED` rather than `OPEN` — closing an unsettled claim fails with
        `ERR_CLAIM_NOT_SETTLED`. A successful close moves `overall_status` to its
        terminal `CLOSED` state, after which no mutation under the claim is
        possible."

        Design: Corner/state_machines/claim_close_state_sequence_enforced
        """
        policyholder = register_policyholder()
        claim = open_claim(policyholder["id"])

        early = api.close_claim(claim["id"], SETTLEMENT)
        validate_error(early, ApiErrorId.ERR_CLAIM_NOT_SETTLED)

        settled = validate_success(api.settle_claim(claim["id"], SETTLEMENT), 200)
        assert settled["overall_status"] == "SETTLED"
        closed = validate_success(api.close_claim(claim["id"], SETTLEMENT), 200)
        assert closed["overall_status"] == "CLOSED"

        again = api.close_claim(claim["id"], SETTLEMENT)
        validate_error(again, ApiErrorId.ERR_CLAIM_NOT_SETTLED)

    def test_claim_not_open_blocks_mutation(self, api):
        """PRD §2.7: "the claim-open gate requiring `overall_status` to be `OPEN`
        for any mutation under the claim (rung 6, `ERR_CLAIM_NOT_OPEN`), whose
        sole exception is claim closure, which requires `SETTLED` and fails with
        `ERR_CLAIM_NOT_SETTLED`"

        Design: Corner/validations/claim_not_open_blocks_mutation
        """
        ctx = setup_settled_childless_claim()
        resp = api.create_communication_log(
            create_communication_log_payload(
                ctx["claim"]["id"], template="RETURN_REMINDER",
                body_summary="please return"),
            DESK,
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_OPEN)


class TestCommunicationLog:
    def test_communication_log_manual_create(self, api):
        """PRD §3.9: "Beyond the automated `EXPECTATION_SET`, `EXTENSION_UPDATE`,
        and `RECOVERY_NOTICE` entries fired by the delay cascade, extension
        decisions, and invoice disputes, a `RentalDeskAgent` may log a
        communication against a claim at any time, supplying the `claim_id`, a
        `channel` of `EMAIL`, `SMS`, or `PHONE`, a `template` — the full set being
        `COVERAGE_EXPLAINED`, `EXPECTATION_SET`, `EXTENSION_UPDATE`,
        `RETURN_REMINDER`, and `RECOVERY_NOTICE` — and a `body_summary`. Each
        entry is stamped with `sent_at` from the logical clock, is append-only,
        and is listed under its claim; `COVERAGE_EXPLAINED` and `RETURN_REMINDER`
        exist precisely for these desk-initiated touches."
        PRD §2.4: "Before any call is made, the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and it must never fall back to wall-clock time."

        Design: Corner/endpoints/communication_log_manual_create
        """
        policyholder = register_policyholder()
        claim = open_claim(policyholder["id"])
        resp = api.create_communication_log(
            create_communication_log_payload(
                claim["id"], channel="EMAIL", template="COVERAGE_EXPLAINED",
                body_summary="60/day, 20 days max"),
            DESK,
        )
        entry = validate_success(resp, 201)
        assert_communication_log(entry)
        assert_timestamp_matches_clock(entry["sent_at"], DEFAULT_LOGICAL_CLOCK)

        logs = list_claim_communications(claim["id"])
        assert len(logs) == 1
        assert logs[0]["template"] == "COVERAGE_EXPLAINED"
