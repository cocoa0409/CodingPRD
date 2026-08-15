"""Suspension, reinstatement, expulsion, withdrawal, and their cascades."""
from datetime import datetime

import pytest

from test_helpers import (
    CLERK,
    ApiErrorId,
    create_transfer_payload,
    drive_member_delinquent,
    drive_member_suspended,
    get_member,
    get_success_data,
    get_transfer,
    list_member_notices,
    make_assessment_run,
    make_classification,
    make_local,
    make_member,
    make_member_headers,
    make_transfer,
    run_period,
    send_notice,
    set_clock,
    setup_flat_local_with_journeyman,
    sweep_delinquency,
    validate_error,
    validate_success,
)


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestReinstateGuards:
    def test_reinstate_non_suspended_member_rejected(self, api, secretary_treasurer_headers):
        """PRD section on reinstatement: "Reinstatement requires the member to
        be `SUSPENDED` (`ERR_MEMBER_NOT_SUSPENDED` otherwise)".

        Design: Corner/state_machines/reinstate_non_suspended_member_rejected
        """
        local, cls = setup_flat_local_with_journeyman()
        member = make_member(local["id"], cls["id"], full_name="Active Al", member_number="M-001")
        set_clock("2026-08-01T00:00:00Z")
        resp = api.reinstate_member(member["id"], {"amount_cents": 2500}, secretary_treasurer_headers)
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_SUSPENDED)


class TestReinstatementExactAmountBoundary:
    """The reinstatement quote is arrears plus base-fee times suspension
    count, and the posted amount must equal the recomputed total exactly."""

    def _setup_suspended(self, api):
        local, cls = setup_flat_local_with_journeyman()
        member = make_member(local["id"], cls["id"], full_name="Rein Rhoda", member_number="M-001")
        drive_member_suspended(local["id"], member["id"], ("2026-05", "2026-06", "2026-07"))
        return local, member

    def test_quote_and_under_by_one_cent_rejected(self, api, secretary_treasurer_headers):
        """PRD section on reinstatement: "first the member's arrears before any
        fee posting, straight from the waterfall; then the fee, which is the
        local's `reinstatement_base_fee_cents` multiplied by the member's
        current `suspension_count`", and "the request's `amount_cents` must
        equal the recomputed `total_due_cents` exactly, and any mismatch is
        rejected with `ERR_REINSTATEMENT_AMOUNT_MISMATCH`".

        Design: Difficulty/boundary_precision_check/reinstatement_exact_amount_boundary
        """
        _, member = self._setup_suspended(api)
        quote = get_success_data(api.get_reinstatement_quote(member["id"], secretary_treasurer_headers))
        assert quote["arrears_cents"] == 15000
        assert quote["reinstatement_fee_cents"] == 2500, "base 2500 x suspension_count 1"
        assert quote["total_due_cents"] == 17500
        resp = api.reinstate_member(member["id"], {"amount_cents": 17499}, secretary_treasurer_headers)
        validate_error(resp, ApiErrorId.ERR_REINSTATEMENT_AMOUNT_MISMATCH)
        still = get_member(member["id"])
        assert still["status"] == "SUSPENDED", "the failed attempt changes nothing"

    def test_exact_amount_reinstates(self, api, secretary_treasurer_headers):
        """PRD section on reinstatement: "A successful reinstatement posts a
        `REINSTATEMENT_FEE` charge for the fee first and a `DIRECT_PAYMENT`
        credit for the full amount second, both against the current clock
        period; the member returns to `ACTIVE` with arrears recomputed to
        zero, `suspended_since` cleared to null, `last_suspension_ended_at`
        set to the logical clock time, and `version` incremented."

        Design: Difficulty/boundary_precision_check/reinstatement_exact_amount_boundary
        """
        _, member = self._setup_suspended(api)
        resp = api.reinstate_member(member["id"], {"amount_cents": 17500}, secretary_treasurer_headers)
        reinstated = validate_success(resp, 200)
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["suspended_since"] is None
        after = get_member(member["id"])
        assert after["arrears_cents"] == 0
        assert after["suspension_count"] == 1
        assert _parse(after["last_suspension_ended_at"]) == _parse("2026-08-12T00:00:00Z")


class TestExpulsion:
    def test_expulsion_at_suspension_cap(self, api):
        """PRD section on the sweep: "when the suspension would raise the
        member's `suspension_count` to reach `max_suspensions`, the sweep
        expels instead of suspending." With max_suspensions 1 the first notice
        expiry expels, and the count never increments.

        Design: Corner/cross_cutting_layers/expulsion_at_suspension_cap
        """
        local, cls = setup_flat_local_with_journeyman(max_suspensions=1)
        member = make_member(local["id"], cls["id"], full_name="Cap Colin", member_number="M-001")
        after, _ = drive_member_suspended(local["id"], member["id"], ("2026-05", "2026-06"))
        assert after["status"] == "EXPELLED", "0 + 1 reaches the cap of 1"
        assert after["suspension_count"] == 0, "the member was never actually suspended"

    def test_expulsion_after_expel_months_boundary(self, api):
        """PRD section on the sweep: "a `SUSPENDED` member whose suspension
        began at least `expel_after_months` calendar months before the current
        clock date is expelled." One day short of twelve months the member
        stays suspended; at exactly twelve months the sweep expels.

        Design: Corner/cross_cutting_layers/expulsion_after_expel_months_boundary
        """
        local, cls = setup_flat_local_with_journeyman()
        member = make_member(local["id"], cls["id"], full_name="Long Larry", member_number="M-001")
        after, _ = drive_member_suspended(local["id"], member["id"], ("2026-05", "2026-06"))
        assert after["status"] == "SUSPENDED"
        set_clock("2027-08-11T00:00:00Z")
        sweep_delinquency(local["id"])
        early = get_member(member["id"])
        assert early["status"] == "SUSPENDED", "one day before the twelve-month boundary"
        set_clock("2027-08-12T00:00:00Z")
        sweep_delinquency(local["id"])
        final = get_member(member["id"])
        assert final["status"] == "EXPELLED", "exactly suspended_since + 12 calendar months"


class TestWithdrawal:
    def test_withdraw_with_arrears_rejected(self, api):
        """PRD section on withdrawal: "`arrears_cents` must be zero, otherwise
        the withdrawal is rejected with `ERR_ARREARS_OUTSTANDING`."

        Design: Corner/validations/withdraw_with_arrears_rejected
        """
        local, cls = setup_flat_local_with_journeyman()
        member = make_member(local["id"], cls["id"], full_name="Owing Owen", member_number="M-001")
        set_clock("2026-08-01T00:00:00Z")
        make_assessment_run(local["id"], "2026-08")
        resp = api.withdraw_member(member["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_ARREARS_OUTSTANDING)


class TestSuspensionCancelsPendingTransfer:
    """Delinquency alone leaves a pending transfer alone; the suspension that
    follows notice expiry cancels it."""

    def _setup_transfer_then_suspension(self, api):
        local, cls = setup_flat_local_with_journeyman(local_name="Local 200")
        local2 = make_local("FLAT", name="Local 400", default_flat_dues_cents=1000)
        set_clock("2026-05-01T00:00:00Z")
        member = make_member(local["id"], cls["id"], full_name="Trina Transfer", member_number="M-001")
        transfer = make_transfer(member["id"], local2["id"], "2026-09")
        validate_success(api.certify_transfer(transfer["id"], CLERK), 200)
        return local, member, transfer

    def test_delinquency_alone_does_not_cancel_transfer(self, api):
        """PRD section on suspension and expulsion: "suspension cancels any
        transfer in `INITIATED` or `PENDING_TARGET`, because suspension breaks
        the good-standing precondition those transfers rest on" — delinquency
        is not suspension, so the transfer survives the first sweep.

        Design: Difficulty/transitive_cascade/suspension_cancels_pending_transfer
        """
        local, member, transfer = self._setup_transfer_then_suspension(api)
        drive_member_delinquent(local["id"], member["id"], ("2026-05", "2026-06", "2026-07"))
        assert get_member(member["id"])["status"] == "DELINQUENT"
        mid = get_transfer(transfer["id"])
        assert mid["status"] == "PENDING_TARGET", "delinquency alone leaves the transfer pending"

    def test_suspension_cascade_cancels_transfer(self, api):
        """PRD section on the sweep: a member with a SENT notice whose
        cure_deadline "has been reached — the deadline is at or before the
        current clock time — and who is still over has the notice move to
        `EXPIRED` and is suspended", and "suspension cancels any transfer in
        `INITIATED` or `PENDING_TARGET`".

        Design: Difficulty/transitive_cascade/suspension_cancels_pending_transfer
        """
        local, member, transfer = self._setup_transfer_then_suspension(api)
        drive_member_delinquent(local["id"], member["id"], ("2026-05", "2026-06", "2026-07"))
        notice = list_member_notices(member["id"])[0]
        send_notice(member["id"], notice["id"])
        set_clock("2026-08-12T00:00:00Z")
        sweep_delinquency(local["id"])
        after = get_member(member["id"])
        assert after["status"] == "SUSPENDED" and after["suspension_count"] == 1
        notices = list_member_notices(member["id"])
        assert notices[0]["status"] == "EXPIRED"
        end = get_transfer(transfer["id"])
        assert end["status"] == "CANCELLED", "the suspension, not the sweep, cancelled it"


class TestObjectorFileWhileSuspended:
    def test_objector_file_while_suspended_rejected(self, api):
        """PRD section on objector cases: "it is refused when the member
        already has a non-terminal case (`ERR_OBJECTOR_CASE_EXISTS`), when the
        member is `SUSPENDED` (`ERR_MEMBER_STATE_FORBIDDEN`), and when the
        member is `WITHDRAWN` or `EXPELLED` (`ERR_MEMBER_TERMINAL_STATE`)."

        Design: Corner/errors/objector_file_while_suspended_rejected
        """
        local, cls = setup_flat_local_with_journeyman()
        member = make_member(local["id"], cls["id"], full_name="Susp Sam", member_number="M-001")
        drive_member_suspended(local["id"], member["id"], ("2026-05", "2026-06"))
        resp = api.create_objector_case(member["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_MEMBER_STATE_FORBIDDEN)
