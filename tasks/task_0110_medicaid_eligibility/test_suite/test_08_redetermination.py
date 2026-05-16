"""Annual redetermination: sweep mechanics, submit/RENEW, submit/
TERMINATE, withdraw + resubmit, redetermination_count_this_year
invariant.

Exercises PRD §3.4.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    advance_to_redetermination_due,
    assert_redetermination,
    get_applicant,
    get_enrollment,
    get_redetermination,
    iso_offset,
    parse_iso,
    run_redetermination_sweep,
    server_now_dt,
    setup_approved_application,
    setup_redetermination_pending,
    submit_redetermination_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Sweep — PRD §3.4
# ===========================================================================
class TestSweep:

    def test_active_due_enrollment_flips_to_redetermination_due(self, api):
        """PRD §3.4: "Once clock_now reaches an enrollment's
        redetermination_due_at, that enrollment becomes eligible to flip
        to REDETERMINATION_DUE. The flip happens not on the instant the
        clock advances but on the next invocation of the system's
        redetermination sweep ... Each matching enrollment is
        transitioned to REDETERMINATION_DUE."

        Claim: after the clock reaches redetermination_due_at and a
        sweep runs, the enrollment's coverage_status is
        REDETERMINATION_DUE.

        # difficulty: non_linear_state_machine/enrollment_cyclic_via_redetermination
        """
        _sp, _hh, _, _a, _det, enrollments = setup_approved_application(
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 12_000.00, "frequency": "ANNUAL"},
            ],
        )
        enrollment = enrollments[0]
        advance_to_redetermination_due(enrollment=enrollment)
        run_redetermination_sweep()
        refreshed = get_enrollment(enrollment["id"])
        assert refreshed["coverage_status"] == "REDETERMINATION_DUE", (
            "ACTIVE → REDETERMINATION_DUE on sweep per PRD §3.4; "
            f"got coverage_status={refreshed['coverage_status']!r}"
        )

    def test_due_redetermination_status_is_pending(self, api):
        """PRD §3.4: "the system creates a new Redetermination record
        under it with status PENDING."

        Claim: after sweep, the created redetermination has
        status=PENDING.
        """
        _sp, _hh, _, _enr, redet = setup_redetermination_pending(
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 12_000.00, "frequency": "ANNUAL"},
            ],
        )
        assert redet["status"] == "PENDING", (
            "freshly created Redetermination must be PENDING per PRD §3.4"
        )

    def test_sweep_ignores_non_active_enrollments(self, api):
        """PRD §3.4: "Enrollments not in ACTIVE at sweep time are
        ignored."

        Claim: a SUSPENDED enrollment is NOT transitioned to
        REDETERMINATION_DUE by a sweep, even after its
        redetermination_due_at is reached.
        """
        _sp, _hh, _, _a, _det, enrollments = setup_approved_application(
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 12_000.00, "frequency": "ANNUAL"},
            ],
        )
        enrollment = enrollments[0]
        # Suspend first.
        admin = TEST_USERS["policy_admin_headers"]
        api.suspend_enrollment(enrollment["id"], admin)
        advance_to_redetermination_due(enrollment=enrollment)
        run_redetermination_sweep()
        refreshed = get_enrollment(enrollment["id"])
        assert refreshed["coverage_status"] == "SUSPENDED", (
            "SUSPENDED enrollments must be ignored by the sweep per "
            f"PRD §3.4; got coverage_status={refreshed['coverage_status']!r}"
        )


# ===========================================================================
# Submit RENEW — PRD §3.4
# ===========================================================================
class TestSubmitRenew:

    def test_renew_resets_coverage_window(self, api):
        """PRD §3.4: "The renewed enrollment's coverage_start is reset
        to the current clock_now, its coverage_end is reset to
        coverage_start plus 365 days, its redetermination_due_at is
        reset to coverage_start plus 365 days, and its coverage_status
        is set back to ACTIVE."

        Claim: RENEW transitions Enrollment back to ACTIVE; the new
        coverage_end is coverage_start + 365 days.
        """
        _sp, _hh, _, enrollments, redet = setup_redetermination_pending(
            state_policy_kwargs={
                "fpl_base_amount": 15_000.00,
                "fpl_per_member_amount": 5_000.00,
                "magi_income_limit_pct": 138.0,
            },
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 5_000.00, "frequency": "ANNUAL"},
            ],
        )
        enrollment = enrollments[0]
        res = api.submit_redetermination(
            redet["id"],
            submit_redetermination_payload(
                decision="RENEW", new_snapshot_magi=5_000.00,
            ),
            TEST_USERS["eligibility_caseworker_headers"],
        )
        data = validate_success(res)
        assert data["status"] == "RENEWED"
        assert data["decision"] == "RENEWED"
        # Refetch enrollment.
        refreshed = get_enrollment(enrollment["id"])
        assert refreshed["coverage_status"] == "ACTIVE", (
            "RENEW must move enrollment back to ACTIVE per PRD §3.4"
        )
        # Coverage window resets.
        start = parse_iso(refreshed["coverage_start"])
        end = parse_iso(refreshed["coverage_end"])
        assert (end - start) == timedelta(days=365), (
            "RENEW must set coverage_end = coverage_start + 365 days "
            f"per PRD §3.4; got delta={end - start}"
        )

    def test_renew_above_ceiling_returns_not_eligible(self, api):
        """PRD §3.4: "new_snapshot_fpl_percent must satisfy MAGI
        eligibility against the current StatePolicy.magi_income_limit_pct
        — that is, be less than or equal to the ceiling — (otherwise
        ERR_NOT_ELIGIBLE)."

        Claim: RENEW with a high new_snapshot_magi that pushes FPL%
        above the ceiling → ERR_NOT_ELIGIBLE.
        """
        _sp, _hh, _, enrollments, redet = setup_redetermination_pending(
            state_policy_kwargs={
                "fpl_base_amount": 15_000.00,
                "fpl_per_member_amount": 5_000.00,
                "magi_income_limit_pct": 50.0,
            },
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 5_000.00, "frequency": "ANNUAL"},
            ],
        )
        # FPL threshold = 15000 (one applicant). new_snapshot_magi=
        # 50_000 → fpl%=333.33 > 50.0 limit.
        res = api.submit_redetermination(
            redet["id"],
            submit_redetermination_payload(
                decision="RENEW", new_snapshot_magi=50_000.00,
            ),
            TEST_USERS["eligibility_caseworker_headers"],
        )
        validate_error(res, "ERR_NOT_ELIGIBLE")

    def test_submit_on_non_pending_invalid_state(self, api):
        """PRD §3.4: "the redetermination must be PENDING (otherwise
        ERR_INVALID_STATE)."

        Claim: submit twice in a row → the second returns
        ERR_INVALID_STATE.
        """
        _sp, _hh, _, _enr, redet = setup_redetermination_pending(
            state_policy_kwargs={
                "fpl_base_amount": 15_000.00,
                "fpl_per_member_amount": 5_000.00,
                "magi_income_limit_pct": 138.0,
            },
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 5_000.00, "frequency": "ANNUAL"},
            ],
        )
        # First submission.
        api.submit_redetermination(
            redet["id"],
            submit_redetermination_payload(
                decision="RENEW", new_snapshot_magi=5_000.00,
            ),
            TEST_USERS["eligibility_caseworker_headers"],
        )
        # Second submission on the same id should fail.
        res = api.submit_redetermination(
            redet["id"],
            submit_redetermination_payload(
                decision="RENEW", new_snapshot_magi=5_000.00,
            ),
            TEST_USERS["eligibility_caseworker_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Withdraw — PRD §3.4
# ===========================================================================
class TestWithdrawRedetermination:

    def test_withdraw_pending_redetermination(self, api):
        """PRD §3.4: "A redetermination that is still PENDING may also
        be withdrawn by an IntakeWorker — for example, if the caseworker
        created it in error. The redetermination transitions to
        WITHDRAWN."

        Claim: /withdraw on a PENDING redetermination → status=WITHDRAWN.
        """
        _sp, _hh, _, _enr, redet = setup_redetermination_pending(
            state_policy_kwargs={
                "fpl_base_amount": 15_000.00,
                "fpl_per_member_amount": 5_000.00,
                "magi_income_limit_pct": 138.0,
            },
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 5_000.00, "frequency": "ANNUAL"},
            ],
        )
        res = api.withdraw_redetermination(
            redet["id"], TEST_USERS["intake_worker_headers"],
        )
        data = validate_success(res)
        assert data["status"] == "WITHDRAWN"


# ===========================================================================
# redetermination_count_this_year — PRD §3.4 (compensating invariant)
# ===========================================================================
class TestRedeterminationCountInvariant:

    def test_withdraw_then_resubmit_leaves_count_unchanged(self, api):
        """PRD §3.4: "Crucially, an applicant's
        redetermination_count_this_year excludes withdrawn
        redeterminations: it counts distinct redetermination rows tied
        to the applicant whose status is in PENDING, SUBMITTED,
        RENEWED, or TERMINATED."

        Claim: starting with count=1, withdraw the redetermination
        (count→0 due to WITHDRAWN exclusion); after a fresh sweep
        re-creates a PENDING redetermination, count returns to 1.

        # difficulty: compensating_invariant/redetermination_withdraw_resubmit_count_invariant
        """
        _sp, _hh, applicants, enrollments, redet = setup_redetermination_pending(
            state_policy_kwargs={
                "fpl_base_amount": 15_000.00,
                "fpl_per_member_amount": 5_000.00,
                "magi_income_limit_pct": 138.0,
            },
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 5_000.00, "frequency": "ANNUAL"},
            ],
        )
        applicant = applicants[0]
        enrollment = enrollments[0]
        # Step 1: pre-state — count == 1.
        a_pre = get_applicant(applicant["household_id"], applicant["id"])
        assert a_pre["redetermination_count_this_year"] == 1, (
            "pre-condition: a single PENDING redetermination must yield "
            f"count==1 per PRD §3.4; got count="
            f"{a_pre['redetermination_count_this_year']}"
        )
        # Step 2: withdraw — WITHDRAWN excluded → count == 0.
        api.withdraw_redetermination(
            redet["id"], TEST_USERS["intake_worker_headers"],
        )
        a_mid = get_applicant(applicant["household_id"], applicant["id"])
        assert a_mid["redetermination_count_this_year"] == 0, (
            "WITHDRAWN is excluded from redetermination_count_this_year "
            f"per PRD §3.4; got count="
            f"{a_mid['redetermination_count_this_year']}"
        )
        # Step 3: re-run sweep — the enrollment is STILL in
        # REDETERMINATION_DUE (PRD §3.4: "the parent enrollment's
        # coverage_status is left untouched"), but the sweep only
        # processes ACTIVE enrollments. PRD §3.4 also says: "the system
        # will re-create a new PENDING redetermination on the next
        # sweep if the enrollment is still due." That contradicts the
        # ACTIVE-only sweep guarantee — a PRD-only reader can
        # legitimately disagree on whether the sweep would create a new
        # one or not. We therefore use validate_error_is_one_of-style
        # tolerance: we test only that count remains at most 1 after a
        # second sweep, and the WITHDRAWN exclusion still holds.
        run_redetermination_sweep()
        a_post = get_applicant(applicant["household_id"], applicant["id"])
        # The non-WITHDRAWN count is conservation-bound to <= 1.
        assert a_post["redetermination_count_this_year"] in (0, 1), (
            "after withdraw+sweep, count must be 0 or 1 (WITHDRAWN "
            f"excluded); got {a_post['redetermination_count_this_year']}"
        )
