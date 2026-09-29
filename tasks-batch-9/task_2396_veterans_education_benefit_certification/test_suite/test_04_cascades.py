"""The two cascades that propagate beyond the row the client addressed.

Reconciling a change report walks five levels — report, certification,
entitlement ledger and overpayment debt, student balance, Yellow Ribbon award —
and suspending a catalog version walks four, touching only the certifications
that are sitting at exactly SUBMITTED.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers.fixtures import (
    build_certified_certification,
    build_submitted_certification,
    create_agreement,
    create_award,
    create_certification,
    create_student,
    read_agreement,
    record_va_payment,
    read_audit_entries,
    read_certification,
    read_student,
    set_clock_to,
)
from test_helpers.test_users import SAA_HEADERS

WITHDRAWAL_EFFECTIVE_DATE = "2026-09-01"
WITHDRAWAL_REPORTED_DATE = "2026-09-05"
SUSPENSION_REASON = "Refund policy withdrawn from the published catalog"


# ─── Reconciliation: five levels deep ─────────────────────────────────
def _cascade_scenario(api, baseline):
    """Build the whole chain in the order the amounts depend on."""
    scenario = build_certified_certification(api, baseline)
    agreement_id, agreement_version = create_agreement(api, baseline.sup_headers)
    award = create_award(
        api,
        baseline.sup_headers,
        scenario.certification_id,
        agreement_id,
        agreement_version,
    )
    record_va_payment(
        api, scenario.certification_id, 2790000, 776444, c.CLOCK_START_DATE
    )

    set_clock_to(api, WITHDRAWAL_REPORTED_DATE)
    change_report = get_success_data(
        api.create_enrollment_change_report(
            f.complete_withdrawal_payload(
                scenario.certification_id,
                WITHDRAWAL_EFFECTIVE_DATE,
                mitigating_circumstances_flag=False,
            ),
            baseline.sco_headers,
        )
    )
    reconciled = get_success_data(
        api.reconcile_change_report(change_report["id"], {}, baseline.sup_headers)
    )
    return scenario, agreement_id, award, change_report, reconciled


def test_reconciling_stamps_the_report_and_the_reconciling_official(api, baseline):
    """Level one records who reconciled, which is what later bars them from waiving.

    PRD: "At the first level the change report itself moves
    `REPORTED → RECONCILED`, which is terminal, and the acting official's
    `X-User-ID` is recorded as `reconciled_by_official_id` — the identifier that
    later bars that same official from waiving the resulting debt."

    Design: Difficulty/transitive_cascade/reconcile_cascade_depth_five_debt_and_award_reversal
    """
    _scenario, _agreement_id, _award, _report, reconciled = _cascade_scenario(
        api, baseline
    )

    a.assert_fields(
        reconciled,
        {
            "status": c.CHANGE_REPORT_STATUS_RECONCILED,
            "reconciled_by_official_id": baseline.sup_id,
        },
    )


def test_the_certification_is_recomputed_onto_the_reconciled_basis(api, baseline):
    """Level two rewrites the money, the housing and the entitlement, then terminates.

    PRD: "At the second level, because the report was reconciled, the
    certification is recomputed on the `AS_RECONCILED` basis."

    Design: Difficulty/transitive_cascade/reconcile_cascade_depth_five_debt_and_award_reversal
    """
    scenario, _agreement_id, _award, _report, _reconciled = _cascade_scenario(
        api, baseline
    )

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_fields(
        certification,
        {
            "status": c.CERT_STATUS_TERMINATED,
            "amount_basis": c.AMOUNT_BASIS_AS_RECONCILED,
            "mha_term_total_cents": 56987,
            "entitlement_days_charged": 8,
        },
    )
    a.assert_covered_tuition_block(
        certification,
        net_covered_cents=214545,
        ay_cap_remaining_before_cents=2790000,
        va_tuition_cents=214545,
        cap_charged_cents=214545,
        yr_gap_cents=0,
    )


def test_the_entitlement_ledger_is_credited_by_the_difference(api, baseline):
    """Level three restores the days the shortened term no longer consumes.

    PRD: "Because the certification's `entitlement_days_charged` changed, the
    student's `entitlement_days_remaining` is credited by the old charge minus
    the new charge — a credit when the charge fell and a further debit when it
    rose — so that remaining entitlement continues to equal granted entitlement
    minus everything currently charged."

    Design: Difficulty/transitive_cascade/reconcile_cascade_depth_five_debt_and_award_reversal
    """
    scenario, _agreement_id, _award, _report, _reconciled = _cascade_scenario(
        api, baseline
    )

    student = read_student(api, baseline.sco_headers, scenario.student_id)
    assert student["entitlement_days_remaining"] == 1072
    a.assert_entitlement_ledger_balances(student, 8)


def test_exactly_one_debt_is_raised_and_enters_the_students_open_balance(api, baseline):
    """Levels three and four raise the debt and add its principal to the student.

    PRD: "At the fourth level, because the debt was created, the student's
    `open_debt_principal_cents` is increased by `principal_cents` — but only when
    `debtor_type` is `STUDENT`, since a debt the school owes is not the student's
    open balance — and an audit entry with `event_type` `DEBT_CREATED` is
    appended."

    Design: Difficulty/transitive_cascade/reconcile_cascade_depth_five_debt_and_award_reversal
    """
    scenario, _agreement_id, _award, change_report, _reconciled = _cascade_scenario(
        api, baseline
    )

    debts = get_success_data(
        api.list_benefit_debts(
            baseline.sup_headers, {"change_report_id": change_report["id"]}
        )
    )
    assert len(debts) == 1, f"Expected exactly one overpayment debt, got {debts}"
    a.assert_fields(
        debts[0],
        {
            "student_id": scenario.student_id,
            "certification_id": scenario.certification_id,
            "change_report_id": change_report["id"],
            "tuition_component_cents": 2575455,
            "mha_component_cents": 719457,
            "principal_cents": 3294912,
            "outstanding_cents": 3294912,
            "debtor_type": c.DEBTOR_TYPE_STUDENT,
            "source": c.DEBT_SOURCE_AMENDMENT_OVERPAYMENT,
            "collection_status": c.DEBT_COLLECTION_OPEN,
            "notification_status": c.DEBT_NOTIFICATION_PENDING,
            "notification_due_on": "2026-10-05",
        },
    )

    student = read_student(api, baseline.sco_headers, scenario.student_id)
    assert student["open_debt_principal_cents"] == 3294912


def test_a_vanished_gap_auto_reverses_the_provisional_award(api, baseline):
    """Level five releases the school share back into the agreement pool.

    PRD: "If the recomputed `yr_gap_cents` came out at 0, then any Yellow Ribbon
    award on this certification whose `status` is `PROVISIONAL` is moved to
    `REVERSED` with `reversal_reason` set to
    `YR_GAP_ELIMINATED_BY_RECONCILIATION`, its agreement's
    `pool_remaining_cents` is credited back by the award's `school_share_cents`,
    its agreement's `participant_count` is decremented by one, and an audit entry
    with `event_type` `AWARD_REVERSED` is appended."

    Design: Difficulty/transitive_cascade/reconcile_cascade_depth_five_debt_and_award_reversal
    """
    _scenario, agreement_id, award, _report, _reconciled = _cascade_scenario(
        api, baseline
    )

    reversed_award = get_success_data(
        api.get_yellow_ribbon_award(award["id"], baseline.sup_headers)
    )
    a.assert_fields(
        reversed_award,
        {
            "status": c.AWARD_STATUS_REVERSED,
            "reversal_reason": c.REVERSAL_REASON_GAP_ELIMINATED,
        },
    )
    agreement = read_agreement(api, baseline.sup_headers, agreement_id)
    a.assert_fields(
        agreement,
        {"pool_remaining_cents": c.YR_ANNUAL_POOL_CENTS, "participant_count": 0},
    )
    a.assert_pool_ledger_balances(agreement, 0)


def test_the_reconciliation_entry_precedes_the_debt_entry_in_the_trail(api, baseline):
    """The trail reads in the order the cascade's levels fired.

    PRD: "The audit ordering here is fixed: the `AMENDMENT_RECONCILED` entry is
    appended **before** the `DEBT_CREATED` entry, so the trail reads in the order
    the events logically occurred."

    Design: Difficulty/transitive_cascade/reconcile_cascade_depth_five_debt_and_award_reversal
    """
    scenario, _agreement_id, _award, _report, _reconciled = _cascade_scenario(
        api, baseline
    )

    entries = read_audit_entries(
        api, baseline.sup_headers, scenario.certification_id, {"limit": 100}
    )
    event_types = [entry["event_type"] for entry in entries]
    assert c.EVENT_AMENDMENT_RECONCILED in event_types
    assert c.EVENT_DEBT_CREATED in event_types
    assert c.EVENT_AWARD_REVERSED in event_types
    assert event_types.index(c.EVENT_AMENDMENT_RECONCILED) < event_types.index(
        c.EVENT_DEBT_CREATED
    ), f"AMENDMENT_RECONCILED must precede DEBT_CREATED, got {event_types}"


# ─── Catalog suspension: four levels, one conditional ─────────────────
def _suspended_catalog_with_two_certifications(api, baseline):
    """One SUBMITTED and one DRAFT certification, then suspend the catalog."""
    submitted = build_submitted_certification(api, baseline)

    draft_student_id = create_student(
        api,
        baseline.sco_headers,
        student_number=c.SECOND_STUDENT_NUMBER,
        full_name=c.SECOND_STUDENT_NAME,
        delimiting_date=c.SECOND_DELIMITING_DATE,
    )
    draft_id, _version = create_certification(
        api,
        baseline.sco_headers,
        draft_student_id,
        baseline.term_id,
        baseline.program_id,
    )

    suspended = get_success_data(
        api.suspend_catalog_version(
            baseline.catalog_id,
            f.suspend_catalog_payload(suspension_reason=SUSPENSION_REASON),
            SAA_HEADERS,
        )
    )
    return submitted, draft_id, suspended


def test_suspension_pulls_the_catalog_and_its_pinned_program_down(api, baseline):
    """Levels one and two suspend the version and every program pinned to it.

    PRD: "At the second level, because that version was suspended, every program
    whose `approved_catalog_version_id` equals this catalog version's `id` is set
    to `approval_status` `SUSPENDED` — a program in that position may have been
    sitting at either `APPROVED` or `CONDITIONAL`, and both are pulled to
    `SUSPENDED`."

    Design: Difficulty/transitive_cascade/catalog_suspension_cascade_returns_only_submitted_certifications
    """
    _submitted, _draft_id, suspended = _suspended_catalog_with_two_certifications(
        api, baseline
    )

    a.assert_fields(
        suspended,
        {
            "review_status": c.CATALOG_REVIEW_SUSPENDED,
            "suspension_reason": SUSPENSION_REASON,
        },
    )
    program = get_success_data(
        api.get_program(baseline.program_id, baseline.sup_headers)
    )
    a.assert_fields(
        program,
        {
            "approval_status": c.PROGRAM_STATUS_SUSPENDED,
            "approved_catalog_version_id": baseline.catalog_id,
        },
    )


def test_only_a_certification_sitting_at_submitted_is_auto_returned(api, baseline):
    """The DRAFT certification is left entirely untouched by the cascade.

    PRD: "At the third level, because those programs became suspended, every
    enrollment certification whose program is one of them **and whose `status` is
    exactly `SUBMITTED`** is moved to `RETURNED` with `return_reason` set to
    `PROGRAM_SUSPENDED`; this level is deliberately conditional, and
    certifications sitting at `DRAFT`, `RETURNED`, `CERTIFIED`,
    `AMENDMENT_PENDING`, `TERMINATED` or `VOID` are left entirely untouched."

    Design: Difficulty/transitive_cascade/catalog_suspension_cascade_returns_only_submitted_certifications
    """
    submitted, draft_id, _suspended = _suspended_catalog_with_two_certifications(
        api, baseline
    )

    returned = read_certification(
        api, baseline.sup_headers, submitted.certification_id
    )
    a.assert_fields(
        returned,
        {
            "status": c.CERT_STATUS_RETURNED,
            "return_reason": c.RETURN_REASON_PROGRAM_SUSPENDED,
        },
    )
    untouched = read_certification(api, baseline.sup_headers, draft_id)
    a.assert_fields(
        untouched,
        {"status": c.CERT_STATUS_DRAFT, "return_reason": None},
    )


def test_one_system_written_entry_is_appended_per_auto_returned_certification(
    api, baseline
):
    """The cascade signs its audit entries with the literal system actor.

    PRD: "At the fourth level, because those certifications were returned, one
    audit entry is appended per auto-returned certification with `event_type`
    `CERTIFICATION_AUTO_RETURNED`, `actor_role` `system` and `actor_user_id` the
    literal `system`, and those entries are appended in ascending `created_at`
    order of the certifications they document."

    Design: Difficulty/transitive_cascade/catalog_suspension_cascade_returns_only_submitted_certifications
    """
    submitted, draft_id, _suspended = _suspended_catalog_with_two_certifications(
        api, baseline
    )

    returned_entries = read_audit_entries(
        api,
        baseline.sup_headers,
        submitted.certification_id,
        {"event_type": c.EVENT_CERTIFICATION_AUTO_RETURNED, "limit": 100},
    )
    assert len(returned_entries) == 1, (
        f"Expected exactly one auto-return entry, got {returned_entries}"
    )
    a.assert_system_actor(returned_entries[0])
    a.assert_audit_entry_shape(returned_entries[0])

    draft_entries = read_audit_entries(
        api,
        baseline.sup_headers,
        draft_id,
        {"event_type": c.EVENT_CERTIFICATION_AUTO_RETURNED, "limit": 100},
    )
    assert draft_entries == [], (
        f"A DRAFT certification is never auto-returned, got {draft_entries}"
    )
