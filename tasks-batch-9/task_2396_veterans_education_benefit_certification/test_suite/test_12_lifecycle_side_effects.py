"""What each transition writes besides its own status field.

The catalog pinned and the submitter stamped at submission, the paid ledger and the
statutory shield at disbursement, the supersession chain behind a corrected price,
the two independent dimensions of a debt, and the award's two refused replays.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers.fixtures import (
    approve_catalog_version,
    build_certified_certification,
    build_paid_certification,
    create_agreement,
    create_award,
    create_catalog_version,
    create_certification,
    create_verified_student,
    price_certification,
    read_agreement,
    read_certification,
    read_student,
    set_clock_to,
    submit_certification,
)
from test_helpers.test_users import (
    BURSAR_HEADERS,
    VA_HEADERS,
    make_student_headers,
    make_supervisory_sco_headers,
)

LATER_CATALOG_YEAR = "2027-2028"
LATER_WINDOW_START = "2027-07-01"
LATER_WINDOW_END = "2028-07-01"

PAID_TUITION_CENTS = 2790000
PAID_MHA_CENTS = 776444
PAYMENT_POSTED_ON = "2026-08-15"
FIRST_PROTECTED_UNTIL = "2026-10-30"

CORRECTED_GROSS_CENTS = 3200000
CORRECTED_NET_COVERED_CENTS = 3150000

WITHDRAWAL_REPORTED_ON = "2026-09-05"
WITHDRAWAL_EFFECTIVE_DATE = "2026-09-15"
SECOND_SUPERVISOR_NAME = "Rowan Diaz"
SECOND_SUPERVISOR_EMAIL = "rowan.diaz@u.edu"
WAIVER_REASON = "Overpayment traced to an institutional reporting error"

EXPECTED_POOL_AFTER_AWARD_CENTS = 920000
REVERSAL_REASON = "Duplicate submission withdrawn"


# ─── Submission's side effects ────────────────────────────────────────
def _two_approved_catalogs_and_a_priced_draft(api, baseline):
    """A program governed by two consecutive approved windows, plus one draft row."""
    later_id = create_catalog_version(
        api,
        baseline.sup_headers,
        baseline.program_id,
        catalog_year=LATER_CATALOG_YEAR,
        effective_start=LATER_WINDOW_START,
        effective_end=LATER_WINDOW_END,
    )
    approve_catalog_version(api, baseline.sup_headers, later_id)

    student_id = create_verified_student(api, baseline.sco_headers)
    certification_id, version = create_certification(
        api, baseline.sco_headers, student_id, baseline.term_id, baseline.program_id
    )
    _report_id, next_version = price_certification(api, certification_id, version)
    return certification_id, next_version, later_id


def test_submission_pins_the_catalog_version_governing_the_certified_start(
    api, baseline
):
    """Of the two approved windows only the earlier one contains 2026-08-24.

    PRD: "That resolved version is captured on the certification as
    `pinned_catalog_version_id`, so the catalog the enrollment was certified under
    is a matter of record even if the catalog is later replaced or suspended."

    Design: Corner/state_machines/submitting_a_certification_pins_the_effective_catalog_and_stamps_the_submitter
    """
    certification_id, _version, later_id = _two_approved_catalogs_and_a_priced_draft(
        api, baseline
    )
    assert (
        read_certification(api, baseline.sco_headers, certification_id)[
            "pinned_catalog_version_id"
        ]
        is None
    )

    submitted = submit_certification(api, baseline.sco_headers, certification_id)
    assert submitted["pinned_catalog_version_id"] == baseline.catalog_id
    assert submitted["pinned_catalog_version_id"] != later_id


def test_submission_stamps_the_submitter_and_appends_the_first_audit_entry(
    api, baseline
):
    """The acting official is recorded and the trail opens at sequence index 1.

    PRD: "A successful submission moves the certification `DRAFT → SUBMITTED` or
    `RETURNED → SUBMITTED`, records the acting official's `X-User-ID` as
    `submitted_by_official_id`, pins the resolved catalog version, clears
    `return_reason` when the submission came from `RETURNED`, and appends an audit
    entry with `event_type` `CERTIFICATION_SUBMITTED`."

    Design: Corner/state_machines/submitting_a_certification_pins_the_effective_catalog_and_stamps_the_submitter
    """
    certification_id, version, _later_id = _two_approved_catalogs_and_a_priced_draft(
        api, baseline
    )

    submitted = submit_certification(api, baseline.sco_headers, certification_id)
    a.assert_fields(
        submitted,
        {
            "status": c.CERT_STATUS_SUBMITTED,
            "submitted_by_official_id": baseline.sco_id,
            "certified_by_official_id": None,
            "version": version + 1,
        },
    )
    entries = get_success_data(
        api.list_audit_entries(certification_id, baseline.sup_headers)
    )
    a.assert_event_sequence(entries, [c.EVENT_CERTIFICATION_SUBMITTED])


# ─── Disbursement's side effects ──────────────────────────────────────
def test_a_certified_but_unpaid_student_is_protected(api, baseline):
    """All three conjuncts of the statutory predicate hold before VA pays.

    PRD: "The service reduces that statute to a three-part predicate that must all
    hold at once for a student to count as protected: their `coe_status` is
    `VERIFIED`; the current logical clock date is on or before their
    `protected_until`, with the boundary day itself still inside the window; and at
    least one enrollment certification exists for that student whose `status` is
    `CERTIFIED` or `AMENDMENT_PENDING` and whose `tuition_payment_posted_on` is
    still null."

    Design: Corner/state_machines/recording_the_va_payment_syncs_the_paid_ledger_and_lifts_the_penalty_shield
    """
    scenario = build_certified_certification(api, baseline)

    student = read_student(api, baseline.sco_headers, scenario.student_id)
    a.assert_fields(
        student,
        {
            "coe_status": c.COE_STATUS_VERIFIED,
            "protected_until": FIRST_PROTECTED_UNTIL,
            "benefit_payment_protected": True,
        },
    )
    assert (
        read_certification(api, baseline.sup_headers, scenario.certification_id)[
            "tuition_payment_posted_on"
        ]
        is None
    )


def test_recording_the_payment_writes_the_paid_ledger_and_lifts_the_shield(
    api, baseline
):
    """Only the predicate flips; the window's end date is left where it was.

    PRD: "Those are written to the certification as `tuition_paid_cents`,
    `mha_paid_cents` and `tuition_payment_posted_on` respectively, the student's
    `benefit_payment_protected` is recomputed — losing its third conjunct for this
    certification — and an audit entry with `event_type` `VA_PAYMENT_RECORDED` is
    appended."

    Design: Corner/state_machines/recording_the_va_payment_syncs_the_paid_ledger_and_lifts_the_penalty_shield
    """
    scenario = build_paid_certification(
        api, baseline, PAID_TUITION_CENTS, PAID_MHA_CENTS, PAYMENT_POSTED_ON
    )

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_fields(
        certification,
        {
            "tuition_paid_cents": PAID_TUITION_CENTS,
            "mha_paid_cents": PAID_MHA_CENTS,
            "tuition_payment_posted_on": PAYMENT_POSTED_ON,
        },
    )
    student = read_student(api, baseline.sco_headers, scenario.student_id)
    a.assert_fields(
        student,
        {
            "benefit_payment_protected": False,
            "protected_until": FIRST_PROTECTED_UNTIL,
        },
    )


def test_a_second_disbursement_is_refused_and_the_paid_ledger_stands(api, baseline):
    """A non-null posted date is exactly how the replay is recognised.

    PRD: "A disbursement may be recorded only once per certification: a second
    attempt, recognisable because `tuition_payment_posted_on` is no longer null, is
    refused with `ERR_VA_PAYMENT_ALREADY_RECORDED`."

    Design: Corner/state_machines/recording_the_va_payment_syncs_the_paid_ledger_and_lifts_the_penalty_shield
    """
    scenario = build_paid_certification(
        api, baseline, PAID_TUITION_CENTS, PAID_MHA_CENTS, PAYMENT_POSTED_ON
    )

    response = api.record_va_payment(
        scenario.certification_id,
        f.record_va_payment_payload(1, 1, PAYMENT_POSTED_ON),
        VA_HEADERS,
    )
    validate_error(response, e.ERR_VA_PAYMENT_ALREADY_RECORDED, 409)

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    assert certification["tuition_paid_cents"] == PAID_TUITION_CENTS
    payments = get_success_data(
        api.list_audit_entries(
            scenario.certification_id,
            baseline.sup_headers,
            {"event_type": c.EVENT_VA_PAYMENT_RECORDED},
        )
    )
    assert len(payments) == 1


# ─── Re-pricing's side effects ────────────────────────────────────────
def _repriced_certification(api, baseline):
    """One certification priced twice, the second time at a higher gross tuition."""
    student_id = create_verified_student(api, baseline.sco_headers)
    certification_id, version = create_certification(
        api, baseline.sco_headers, student_id, baseline.term_id, baseline.program_id
    )
    first_report_id, second_version = price_certification(
        api, certification_id, version
    )
    second_report = get_success_data(
        api.create_tuition_fee_report(
            f.tuition_fee_report_payload(
                certification_id,
                second_version,
                gross_tuition_cents=CORRECTED_GROSS_CENTS,
            ),
            BURSAR_HEADERS,
        ),
        expected_status=201,
    )
    return certification_id, version, first_report_id, second_report


def test_a_corrected_report_supersedes_the_first_and_leaves_one_in_force(
    api, baseline
):
    """The superseded row keeps its own arithmetic rather than being rewritten.

    PRD: "A report is created with `status` `REPORTED`, and in the same operation
    any earlier report for the same `certification_id` that was still `REPORTED` is
    moved `REPORTED → SUPERSEDED`, which is terminal — so a certification always
    has exactly one report in force and an arbitrarily long trail of superseded
    ones behind it."

    Design: Corner/state_machines/a_second_tuition_report_supersedes_the_first_and_rewrites_the_certification
    """
    certification_id, _version, first_report_id, second_report = _repriced_certification(
        api, baseline
    )

    first_report = get_success_data(
        api.get_tuition_fee_report(first_report_id, BURSAR_HEADERS)
    )
    a.assert_fields(
        first_report,
        {
            "status": c.TUITION_REPORT_STATUS_SUPERSEDED,
            "net_covered_cents": c.CANONICAL_NET_COVERED_CENTS,
        },
    )
    a.assert_fields(
        second_report,
        {
            "status": c.TUITION_REPORT_STATUS_REPORTED,
            "net_covered_cents": CORRECTED_NET_COVERED_CENTS,
        },
    )
    in_force = get_success_data(
        api.list_tuition_fee_reports(
            BURSAR_HEADERS,
            {
                "certification_id": certification_id,
                "status": c.TUITION_REPORT_STATUS_REPORTED,
            },
        )
    )
    assert [row["id"] for row in in_force] == [second_report["id"]]


def test_the_correction_replaces_the_covered_amount_and_bumps_the_version_again(
    api, baseline
):
    """The new figure replaces the old one instead of accumulating with it.

    PRD: "Acceptance of a report also writes the derived covered amount onto the
    certification itself as the certification's `net_covered_cents`, and because
    that is a mutation of the certification row it increments the certification's
    `version` by one."

    Design: Corner/state_machines/a_second_tuition_report_supersedes_the_first_and_rewrites_the_certification
    """
    certification_id, version, _first_id, _second = _repriced_certification(
        api, baseline
    )

    certification = read_certification(api, baseline.sco_headers, certification_id)
    a.assert_fields(
        certification,
        {
            "net_covered_cents": CORRECTED_NET_COVERED_CENTS,
            "version": version + 2,
        },
    )


# ─── A debt's two independent dimensions ──────────────────────────────
def _debt_from_a_withdrawal(api, baseline):
    """A paid term withdrawn part-way, reconciled into one student-owed debt."""
    scenario = build_paid_certification(
        api, baseline, PAID_TUITION_CENTS, PAID_MHA_CENTS, PAYMENT_POSTED_ON
    )
    set_clock_to(api, WITHDRAWAL_REPORTED_ON)
    change_report = get_success_data(
        api.create_enrollment_change_report(
            f.complete_withdrawal_payload(
                scenario.certification_id, WITHDRAWAL_EFFECTIVE_DATE
            ),
            baseline.sco_headers,
        )
    )
    get_success_data(
        api.reconcile_change_report(change_report["id"], {}, baseline.sup_headers)
    )
    debts = get_success_data(
        api.list_benefit_debts(
            baseline.sup_headers, {"change_report_id": change_report["id"]}
        )
    )
    assert len(debts) == 1, f"Expected exactly one debt, got {debts}"
    return scenario, change_report, debts[0]


def _second_supervisor_headers(api):
    """A supervisory official who took no part in the reconciliation."""
    official = get_success_data(
        api.create_certifying_official(
            f.supervisory_official_payload(
                full_name=SECOND_SUPERVISOR_NAME, email=SECOND_SUPERVISOR_EMAIL
            ),
            VA_HEADERS,
        )
    )
    return official["id"], make_supervisory_sco_headers(official["id"])


def test_acknowledging_a_debt_that_was_never_notified_is_refused(api, baseline):
    """PENDING has no edge to ACKNOWLEDGED.

    PRD: "It is permitted while the `notification_status` is `SENT` or `OVERDUE`
    and is otherwise refused with `ERR_DEBT_NOT_NOTIFIED`, and the acting
    `X-User-ID` must equal the debt's `student_id`, failing which the request is
    refused with `ERR_STUDENT_SCOPE_VIOLATION`."

    Design: Corner/state_machines/debt_notification_and_collection_dimensions_advance_independently
    """
    scenario, _change_report, debt = _debt_from_a_withdrawal(api, baseline)
    assert debt["notification_status"] == c.DEBT_NOTIFICATION_PENDING

    response = api.acknowledge_benefit_debt(
        debt["id"], {}, make_student_headers(scenario.student_id)
    )
    validate_error(response, e.ERR_DEBT_NOT_NOTIFIED, 409)

    reread = get_success_data(api.get_benefit_debt(debt["id"], baseline.sup_headers))
    a.assert_fields(
        reread,
        {
            "notification_status": c.DEBT_NOTIFICATION_PENDING,
            "acknowledged_on": None,
        },
    )


def test_notification_moves_the_debt_to_sent_and_stores_the_channel(api, baseline):
    """The send date comes from the logical clock, not from the client.

    PRD: "The debt moves `PENDING → SENT`, the channel is stored, and `notified_on`
    is stamped with the current logical clock date."

    Design: Corner/state_machines/debt_notification_and_collection_dimensions_advance_independently
    """
    _scenario, _change_report, debt = _debt_from_a_withdrawal(api, baseline)

    notified = get_success_data(
        api.notify_benefit_debt(
            debt["id"], f.notify_debt_payload(), baseline.sco_headers
        )
    )
    a.assert_fields(
        notified,
        {
            "notification_status": c.DEBT_NOTIFICATION_SENT,
            "notification_channel": c.NOTIFICATION_CHANNEL_EMAIL,
            "notified_on": WITHDRAWAL_REPORTED_ON,
        },
    )


def test_a_second_notification_is_refused_and_the_channel_stands(api, baseline):
    """Notification requires the notification dimension to be exactly PENDING.

    PRD: "Notification is sent by either certifying-official role and requires the
    debt's `notification_status` to be exactly `PENDING`; anything else is refused
    with `ERR_DEBT_ALREADY_NOTIFIED`."

    Design: Corner/state_machines/debt_notification_and_collection_dimensions_advance_independently
    """
    _scenario, _change_report, debt = _debt_from_a_withdrawal(api, baseline)
    get_success_data(
        api.notify_benefit_debt(
            debt["id"], f.notify_debt_payload(), baseline.sco_headers
        )
    )

    response = api.notify_benefit_debt(
        debt["id"],
        f.notify_debt_payload(notification_channel=c.NOTIFICATION_CHANNEL_POSTAL),
        baseline.sco_headers,
    )
    validate_error(response, e.ERR_DEBT_ALREADY_NOTIFIED, 409)

    reread = get_success_data(api.get_benefit_debt(debt["id"], baseline.sup_headers))
    a.assert_fields(
        reread,
        {
            "notification_status": c.DEBT_NOTIFICATION_SENT,
            "notification_channel": c.NOTIFICATION_CHANNEL_EMAIL,
        },
    )


def test_acknowledgement_leaves_the_collection_dimension_where_it_was(api, baseline):
    """Being told about a debt is not the same as paying any of it.

    PRD: "Acknowledgement moves the debt to `ACKNOWLEDGED` and stamps
    `acknowledged_on` with the current logical clock date."

    Design: Corner/state_machines/debt_notification_and_collection_dimensions_advance_independently
    """
    scenario, _change_report, debt = _debt_from_a_withdrawal(api, baseline)
    get_success_data(
        api.notify_benefit_debt(
            debt["id"], f.notify_debt_payload(), baseline.sco_headers
        )
    )

    acknowledged = get_success_data(
        api.acknowledge_benefit_debt(
            debt["id"], {}, make_student_headers(scenario.student_id)
        )
    )
    a.assert_fields(
        acknowledged,
        {
            "notification_status": c.DEBT_NOTIFICATION_ACKNOWLEDGED,
            "acknowledged_on": WITHDRAWAL_REPORTED_ON,
            "collection_status": c.DEBT_COLLECTION_OPEN,
            "repaid_cents": 0,
            "outstanding_cents": debt["principal_cents"],
        },
    )


def _acknowledged_debt(api, baseline):
    """A notified and acknowledged debt, still wholly unpaid."""
    scenario, change_report, debt = _debt_from_a_withdrawal(api, baseline)
    get_success_data(
        api.notify_benefit_debt(
            debt["id"], f.notify_debt_payload(), baseline.sco_headers
        )
    )
    get_success_data(
        api.acknowledge_benefit_debt(
            debt["id"], {}, make_student_headers(scenario.student_id)
        )
    )
    return scenario, change_report, debt


def test_waiving_moves_only_the_collection_dimension(api, baseline):
    """The notification dimension keeps its own terminal state.

    PRD: "A waiver takes a `waiver_reason`, sets `collection_status` to `WAIVED`,
    records the acting `X-User-ID` as `waived_by_official_id`, stores the reason,
    and drives `outstanding_cents` to 0 while leaving `principal_cents` untouched."

    Design: Corner/state_machines/debt_notification_and_collection_dimensions_advance_independently
    """
    _scenario, _change_report, debt = _acknowledged_debt(api, baseline)
    waiver_id, waiver_headers = _second_supervisor_headers(api)

    waived = get_success_data(
        api.waive_benefit_debt(
            debt["id"], f.waive_debt_payload(), waiver_headers
        )
    )
    a.assert_fields(
        waived,
        {
            "collection_status": c.DEBT_COLLECTION_WAIVED,
            "outstanding_cents": 0,
            "principal_cents": debt["principal_cents"],
            "waived_by_official_id": waiver_id,
            "waiver_reason": WAIVER_REASON,
            "notification_status": c.DEBT_NOTIFICATION_ACKNOWLEDGED,
        },
    )


def test_the_waiver_clears_the_students_open_balance(api, baseline):
    """The whole outstanding balance leaves the running total in one step.

    PRD: "When `debtor_type` is `STUDENT`, the student's
    `open_debt_principal_cents` falls by the debt's outstanding balance as it stood
    immediately before the waiver — not by the full principal, since any part
    already repaid has already been removed from that running total."

    Design: Corner/state_machines/debt_notification_and_collection_dimensions_advance_independently
    """
    scenario, _change_report, debt = _acknowledged_debt(api, baseline)
    assert debt["debtor_type"] == c.DEBTOR_TYPE_STUDENT
    before = read_student(api, baseline.sco_headers, scenario.student_id)
    assert before["open_debt_principal_cents"] == debt["principal_cents"]

    _waiver_id, waiver_headers = _second_supervisor_headers(api)
    get_success_data(
        api.waive_benefit_debt(debt["id"], f.waive_debt_payload(), waiver_headers)
    )

    after = read_student(api, baseline.sco_headers, scenario.student_id)
    assert after["open_debt_principal_cents"] == 0


def test_a_repayment_against_a_waived_debt_is_refused(api, baseline):
    """WAIVED is terminal on the collection dimension.

    PRD: "Repayments are booked by the `BursarOfficer` against a debt whose
    `collection_status` is `OPEN` or `PARTIALLY_REPAID`; a debt already `SATISFIED`
    or `WAIVED` is refused with `ERR_DEBT_ALREADY_SETTLED`."

    Design: Corner/state_machines/debt_notification_and_collection_dimensions_advance_independently
    """
    _scenario, _change_report, debt = _acknowledged_debt(api, baseline)
    _waiver_id, waiver_headers = _second_supervisor_headers(api)
    get_success_data(
        api.waive_benefit_debt(debt["id"], f.waive_debt_payload(), waiver_headers)
    )

    response = api.create_debt_repayment(
        debt["id"], f.repayment_payload(1000), BURSAR_HEADERS
    )
    validate_error(response, e.ERR_DEBT_ALREADY_SETTLED, 409)

    reread = get_success_data(api.get_benefit_debt(debt["id"], baseline.sup_headers))
    a.assert_fields(
        reread,
        {"collection_status": c.DEBT_COLLECTION_WAIVED, "repaid_cents": 0},
    )


def test_replaying_the_reconciliation_is_refused_and_raises_no_second_debt(
    api, baseline
):
    """RECONCILED is terminal, so the cascade cannot run a second time.

    PRD: "Two conditions guard it: the change report's `status` must be
    `REPORTED`, else `ERR_CHANGE_REPORT_ALREADY_RECONCILED`, and the
    certification's `status` must be `AMENDMENT_PENDING`, else
    `ERR_CERTIFICATION_NOT_CERTIFIED`."

    Design: Corner/state_machines/debt_notification_and_collection_dimensions_advance_independently
    """
    _scenario, change_report, debt = _debt_from_a_withdrawal(api, baseline)

    response = api.reconcile_change_report(
        change_report["id"], {}, baseline.sup_headers
    )
    validate_error(response, e.ERR_CHANGE_REPORT_ALREADY_RECONCILED, 409)

    debts = get_success_data(
        api.list_benefit_debts(
            baseline.sup_headers, {"change_report_id": change_report["id"]}
        )
    )
    assert [row["id"] for row in debts] == [debt["id"]]


# ─── The award's refused replays ──────────────────────────────────────
def _provisional_award(api, baseline):
    """One provisional award drawing half of a 160000-cent gap from the pool."""
    scenario = build_certified_certification(api, baseline)
    agreement_id, agreement_version = create_agreement(api, baseline.sup_headers)
    award = create_award(
        api,
        baseline.sup_headers,
        scenario.certification_id,
        agreement_id,
        agreement_version,
    )
    return agreement_id, award


def test_finalizing_an_already_final_award_is_refused_as_not_provisional(api, baseline):
    """The refusal names the phase that failed, not the reversal that never happened.

    PRD: "Once VA confirms the match, a `SupervisorySCO` finalizes the award,
    moving it `PROVISIONAL → FINAL`; an award not at `PROVISIONAL` is refused with
    `ERR_AWARD_NOT_PROVISIONAL`."

    Design: Corner/state_machines/award_finalize_and_reverse_refuse_their_own_replays
    """
    agreement_id, award = _provisional_award(api, baseline)

    finalized = get_success_data(
        api.finalize_yellow_ribbon_award(award["id"], {}, baseline.sup_headers)
    )
    assert finalized["status"] == c.AWARD_STATUS_FINAL
    agreement = read_agreement(api, baseline.sup_headers, agreement_id)
    a.assert_fields(
        agreement,
        {
            "pool_remaining_cents": EXPECTED_POOL_AFTER_AWARD_CENTS,
            "participant_count": 1,
        },
    )

    response = api.finalize_yellow_ribbon_award(
        award["id"], {}, baseline.sup_headers
    )
    validate_error(response, e.ERR_AWARD_NOT_PROVISIONAL, 409)


def test_reversing_an_already_reversed_award_is_refused(api, baseline):
    """REVERSED is terminal, and the refused replay restores nothing twice.

    PRD: "Reversal is the release valve, and it is available from either
    `PROVISIONAL` or `FINAL`; an award already `REVERSED` is refused with
    `ERR_AWARD_ALREADY_REVERSED`."

    Design: Corner/state_machines/award_finalize_and_reverse_refuse_their_own_replays
    """
    agreement_id, award = _provisional_award(api, baseline)
    get_success_data(
        api.finalize_yellow_ribbon_award(award["id"], {}, baseline.sup_headers)
    )

    reversed_award = get_success_data(
        api.reverse_yellow_ribbon_award(
            award["id"],
            f.reverse_award_payload(reversal_reason=REVERSAL_REASON),
            baseline.sup_headers,
        )
    )
    a.assert_fields(
        reversed_award,
        {"status": c.AWARD_STATUS_REVERSED, "reversal_reason": REVERSAL_REASON},
    )

    response = api.reverse_yellow_ribbon_award(
        award["id"],
        f.reverse_award_payload(reversal_reason="A different reason entirely"),
        baseline.sup_headers,
    )
    validate_error(response, e.ERR_AWARD_ALREADY_REVERSED, 409)

    reread = get_success_data(
        api.get_yellow_ribbon_award(award["id"], baseline.sup_headers)
    )
    assert reread["reversal_reason"] == REVERSAL_REASON
    agreement = read_agreement(api, baseline.sup_headers, agreement_id)
    a.assert_fields(
        agreement,
        {"pool_remaining_cents": c.YR_ANNUAL_POOL_CENTS, "participant_count": 0},
    )
