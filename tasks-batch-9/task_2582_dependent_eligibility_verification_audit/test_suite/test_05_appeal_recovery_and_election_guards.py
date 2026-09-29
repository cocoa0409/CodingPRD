"""Appeals, claims recovery, and the guards that stand in front of both.

The workflow this module exercises is the back half of an audit wave: a
subscriber whose dependent has been put under notice files a documentation
exception, an independent reviewer remands and then decides it, a recovery agent
prices and collects the claims the plan already paid, and the administrator
finally closes the program out. Alongside those writes sit the guards that must
fire first — the grounds-support rule on an appeal, the fiscal ceilings on a
demand and a payment, the outstanding-work gates at program close, the
point-of-enrollment selector's refusal to guess, and the precedence order that
decides which of several simultaneous violations is reported.
"""
from __future__ import annotations

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.assertions import (
    assert_demand_pricing,
    assert_fields,
    assert_instant_equals,
    assert_mutable_common_fields,
)
from test_helpers.constants import MONTHLY_COST_CENTS
from test_helpers.fixtures import (
    FINALIZE_INSTANT,
    RECONCILE_INSTANT,
    announced_wave,
    appeal_wave,
    escalated_wave,
    recovery_wave,
    response_window_wave,
)
from test_helpers.test_users import (
    PROGRAM_ADMIN,
    RECOVERY_AGENT,
    REVIEWER,
    REVIEWER_USER_ID,
    employee_headers,
)

# A working instant inside the thirty-day appeal window on a 2026-10-17 notice.
APPEAL_FILING_INSTANT = "2026-10-20T00:00:00Z"
# The instant the amnesty scenarios below record their voluntary removal on.
AMNESTY_RECORDING_INSTANT = "2026-09-10T00:00:00Z"
# A later instant, still inside the same appeal window.
LATE_APPEAL_INSTANT = "2026-11-05T00:00:00Z"


def _appeals_on_file(client):
    """Every appeal the service holds, as the reviewer sees them."""
    return validate_paginated(
        client.list_appeals(REVIEWER, params={"limit": 10, "offset": 0})
    )


def _removals_of(b, dependent_id: str):
    """Every amnesty removal recorded against one dependent."""
    return b.dependent_removals(dependent_id, limit=10, offset=0)


def test_custody_grounds_are_unsupported_for_a_spouse_dependent_even_with_a_custody_order(
    b, client
):
    """Asserting `CUSTODY_ARRANGEMENT` likewise requires two things together:
    `custody_order_reference` must be present, and the dependent's
    `relationship_type` must be one of `CHILD_BIOLOGICAL`, `STEPCHILD`,
    `ADOPTED_CHILD`, or `LEGAL_GUARDIANSHIP` ... A failure of either half of either
    ground is refused with `ERR_APPEAL_GROUNDS_UNSUPPORTED`.

    Design: Corner/validations/corner_appeal_grounds_must_be_supported_by_the_relationship_type_and_the_rule
    """
    ctx = escalated_wave(b, relationships=("SPOUSE", "CHILD_BIOLOGICAL"))
    b.set_clock(APPEAL_FILING_INSTANT)
    payload = f.appeal_payload(
        ctx.case["id"],
        ctx.dep1["id"],
        "CUSTODY_ARRANGEMENT",
        custody_order_reference="CO-2026-771",
    )

    response = client.create_appeal(payload, employee_headers(ctx.employee["id"]))

    validate_error(response, E.ERR_APPEAL_GROUNDS_UNSUPPORTED, expected_status=422)
    _rows, meta = _appeals_on_file(client)
    assert meta["total_count"] == 0, meta


def test_affidavit_grounds_are_unsupported_when_the_relationship_rule_never_allowed_one(
    b, client
):
    """Asserting `DOMESTIC_PARTNERSHIP_AFFIDAVIT` requires two things together:
    `affidavit_reference` must be present, and the `AUDIT`-phase documentation rule
    for the dependent's `relationship_type` must have `affidavit_allowed` set to
    true

    Design: Corner/validations/corner_appeal_grounds_must_be_supported_by_the_relationship_type_and_the_rule
    """
    ctx = escalated_wave(
        b,
        relationships=("SPOUSE", "CHILD_BIOLOGICAL"),
        rule_overrides={"SPOUSE": {"affidavit_allowed": False}},
    )
    b.set_clock(APPEAL_FILING_INSTANT)
    payload = f.appeal_payload(
        ctx.case["id"],
        ctx.dep1["id"],
        "DOMESTIC_PARTNERSHIP_AFFIDAVIT",
        affidavit_reference="AFF-2026-118",
    )

    response = client.create_appeal(payload, employee_headers(ctx.employee["id"]))

    validate_error(response, E.ERR_APPEAL_GROUNDS_UNSUPPORTED, expected_status=422)
    _rows, meta = _appeals_on_file(client)
    assert meta["total_count"] == 0, meta


def test_a_custody_appeal_for_the_child_dependent_opens_at_round_one_without_a_reviewer(
    b, client
):
    """A new appeal is created in `SUBMITTED` with `round_number` at 1 and
    `reviewer_user_id`, `assigned_at`, `decided_at`, `decision_rationale`, and
    `remand_reason` all null.

    Design: Corner/validations/corner_appeal_grounds_must_be_supported_by_the_relationship_type_and_the_rule
    """
    ctx = escalated_wave(b, relationships=("SPOUSE", "CHILD_BIOLOGICAL"))
    b.set_clock(APPEAL_FILING_INSTANT)
    payload = f.appeal_payload(
        ctx.case["id"],
        ctx.dep2["id"],
        "CUSTODY_ARRANGEMENT",
        custody_order_reference="CO-2025-402",
    )

    appeal = validate_success(
        client.create_appeal(payload, employee_headers(ctx.employee["id"])),
        expected_status=201,
    )

    assert_mutable_common_fields(appeal)
    assert_fields(
        appeal,
        case_id=ctx.case["id"],
        dependent_id=ctx.dep2["id"],
        grounds="CUSTODY_ARRANGEMENT",
        status="SUBMITTED",
        round_number=1,
        reviewer_user_id=None,
        assigned_at=None,
        decided_at=None,
        decision_rationale=None,
        remand_reason=None,
    )
    rows, meta = _appeals_on_file(client)
    assert meta["total_count"] == 1, meta
    assert rows[0]["dependent_id"] == ctx.dep2["id"], rows


def _appeal_taken_up_for_a_second_round(b):
    """A wave whose appeal has been remanded once, resubmitted, and taken again."""
    ctx = appeal_wave(b, stage="ESCALATION", appeal_at=APPEAL_FILING_INSTANT)
    b.decide_appeal(ctx.appeal["id"], "REMAND")
    b.resubmit_appeal(ctx.appeal["id"], ctx.employee["id"])
    ctx.appeal = b.assign_appeal(ctx.appeal["id"])
    return ctx


def test_a_remanded_appeal_that_was_resubmitted_once_cannot_be_remanded_again(b, client):
    """It is permitted only while `round_number` is strictly less than the two-round
    cap; a remand that would push the appeal past it is refused with
    `ERR_APPEAL_ROUNDS_EXHAUSTED`.

    Design: Corner/validations/corner_second_remand_is_refused_once_the_round_cap_is_reached
    """
    ctx = _appeal_taken_up_for_a_second_round(b)
    assert_fields(
        ctx.appeal, status="UNDER_REVIEW", round_number=2, remand_reason=None
    )

    response = client.decide_appeal(
        ctx.appeal["id"], f.appeal_decision_payload("REMAND"), REVIEWER
    )

    validate_error(response, E.ERR_APPEAL_ROUNDS_EXHAUSTED, expected_status=409)
    still_open = b.read_appeal(ctx.appeal["id"])
    assert_fields(
        still_open,
        status="UNDER_REVIEW",
        round_number=2,
        remand_reason=None,
    )
    # "the request is rejected and nothing changes" (PRD §2.4) - the refused
    # remand leaves the prior decision stamp exactly as it was. PRD §3.8 lists
    # resubmission as clearing only remand_reason, reviewer_user_id and
    # assigned_at, so decided_at is not asserted to be null here.
    assert still_open["decided_at"] == ctx.appeal["decided_at"], still_open


def test_the_second_round_reviewer_may_still_deny_the_appeal_outright(b, client):
    """A **denial** moves the appeal `UNDER_REVIEW → DENIED`. The dependent's
    `TerminationNotice` proceeds entirely unchanged

    Design: Corner/validations/corner_second_remand_is_refused_once_the_round_cap_is_reached
    """
    ctx = _appeal_taken_up_for_a_second_round(b)

    decided = validate_success(
        client.decide_appeal(
            ctx.appeal["id"], f.appeal_decision_payload("DENY"), REVIEWER
        )
    )

    assert_fields(
        decided,
        status="DENIED",
        round_number=2,
        reviewer_user_id=REVIEWER_USER_ID,
    )
    assert_instant_equals(decided["decided_at"], APPEAL_FILING_INSTANT)

    notice = b.notice_for(ctx.dep["id"])
    assert notice["status"] == "ISSUED", notice
    assert notice["rescinded_at"] is None, notice
    assert b.read_dependent(ctx.dep["id"])["coverage_status"] == "TERMINATION_PENDING"


def test_a_payment_before_the_demand_is_priced_and_an_oversized_waiver_are_both_refused(
    b, client
):
    """The recovery's `status` must be `DEMAND_ISSUED` or `PARTIALLY_RECOVERED`,
    otherwise the payment is refused with `ERR_RECOVERY_STATE_INVALID` ... may not
    exceed the row's `recoverable_subtotal_cents` — an excessive credit is refused
    with `ERR_WAIVER_EXCEEDS_SUBTOTAL`.

    Design: Corner/validations/corner_recovery_fiscal_ceilings_bound_the_waiver_and_every_payment
    """
    ctx = recovery_wave(b)
    assert ctx.recovery["status"] == "OPEN", ctx.recovery

    early_payment = client.record_payment(
        ctx.recovery["id"], f.payment_payload(10000, "2026-11-02"), RECOVERY_AGENT
    )
    validate_error(early_payment, E.ERR_RECOVERY_STATE_INVALID, expected_status=409)

    oversized_waiver = client.issue_demand(
        ctx.recovery["id"],
        f.issue_demand_payload(ctx.recovery["recoverable_subtotal_cents"] + 1),
        RECOVERY_AGENT,
    )
    validate_error(
        oversized_waiver, E.ERR_WAIVER_EXCEEDS_SUBTOTAL, expected_status=422
    )

    untouched = b.read_recovery(ctx.recovery["id"])
    assert_fields(
        untouched,
        status="OPEN",
        waiver_credit_cents=0,
        recovered_cents=0,
        net_demand_cents=0,
        demand_issued_at=None,
    )


def test_the_priced_demand_applies_the_five_percent_tier_before_the_goodwill_credit(
    b, client
):
    """Step four subtracts last: `net_demand_cents` is the subtotal plus
    `admin_fee_cents` minus `waiver_credit_cents`.

    Design: Corner/validations/corner_recovery_fiscal_ceilings_bound_the_waiver_and_every_payment
    """
    ctx = recovery_wave(b)

    issued = validate_success(
        client.issue_demand(
            ctx.recovery["id"], f.issue_demand_payload(20000), RECOVERY_AGENT
        )
    )

    assert issued["status"] == "DEMAND_ISSUED", issued
    assert_demand_pricing(issued, subtotal_cents=150000, waiver_credit_cents=20000)
    assert issued["net_demand_cents"] == 137500, issued
    assert_instant_equals(issued["demand_issued_at"], FINALIZE_INSTANT)
    assert b.read_program(ctx.program["id"])["recovery_ledger_cents"] == 137500


def test_collection_stops_at_the_net_demand_and_the_closing_payment_settles_the_row(
    b, client
):
    """the sum of the existing `recovered_cents` and the incoming `amount_cents` must
    be no greater than `net_demand_cents`, with an overshoot refused with
    `ERR_PAYMENT_EXCEEDS_DEMAND`

    Design: Corner/validations/corner_recovery_fiscal_ceilings_bound_the_waiver_and_every_payment
    """
    ctx = recovery_wave(b, issue=True, waiver_credit_cents=20000)
    assert ctx.recovery["net_demand_cents"] == 137500, ctx.recovery

    part_paid = b.payment(ctx.recovery["id"], 100000)
    assert_fields(part_paid, status="PARTIALLY_RECOVERED", recovered_cents=100000)

    overshoot = client.record_payment(
        ctx.recovery["id"], f.payment_payload(40000, "2026-11-03"), RECOVERY_AGENT
    )
    validate_error(overshoot, E.ERR_PAYMENT_EXCEEDS_DEMAND, expected_status=422)
    assert b.read_recovery(ctx.recovery["id"])["recovered_cents"] == 100000

    settled = b.payment(ctx.recovery["id"], 37500, received_date="2026-11-04")
    assert_fields(settled, status="RECOVERED", recovered_cents=137500)

    program = b.read_program(ctx.program["id"])
    assert_fields(
        program, recovered_total_cents=137500, recovery_ledger_cents=137500
    )


def test_the_program_cannot_be_shut_while_a_filed_appeal_is_still_awaiting_review(
    b, client
):
    """no appeal belonging to any of this program's cases may sit in `SUBMITTED`,
    `UNDER_REVIEW`, or `REMANDED`, or the close is refused with
    `ERR_OPEN_APPEALS_REMAIN`

    Design: Corner/validations/corner_program_close_is_blocked_while_an_appeal_is_still_open
    """
    ctx = appeal_wave(
        b, stage="FINALIZED", appeal_at=LATE_APPEAL_INSTANT, assign=False
    )
    assert ctx.appeal["status"] == "SUBMITTED", ctx.appeal
    b.set_clock(RECONCILE_INSTANT)
    b.sweep(ctx.program["id"])
    assert b.read_program(ctx.program["id"])["status"] == "RECONCILIATION"

    response = client.close_program(ctx.program["id"], {}, PROGRAM_ADMIN)

    validate_error(response, E.ERR_OPEN_APPEALS_REMAIN, expected_status=409)
    program = b.read_program(ctx.program["id"])
    assert program["status"] == "RECONCILIATION", program
    assert b.read_case(ctx.case["id"])["status"] == "CLOSED"
    assert b.read_dependent(ctx.dep["id"])["coverage_status"] == "TERMINATED"


def test_once_the_appeal_has_been_denied_the_program_closes_with_the_settled_savings(
    b, client
):
    """On success the program moves `RECONCILIATION → CLOSED`, which is terminal, and
    its `version` increments. ... And `audited_annual_savings_cents` is recomputed one
    final time, so the closed program carries the settled figure.

    Design: Corner/validations/corner_program_close_is_blocked_while_an_appeal_is_still_open
    """
    ctx = appeal_wave(b, stage="ESCALATION", appeal_at=APPEAL_FILING_INSTANT)
    b.decide_appeal(ctx.appeal["id"], "DENY")
    b.set_clock(FINALIZE_INSTANT)
    b.sweep(ctx.program["id"])
    b.set_clock(RECONCILE_INSTANT)
    b.sweep(ctx.program["id"])
    reconciling = b.read_program(ctx.program["id"])
    assert reconciling["status"] == "RECONCILIATION", reconciling

    closed = validate_success(client.close_program(ctx.program["id"], {}, PROGRAM_ADMIN))

    assert closed["status"] == "CLOSED", closed
    assert closed["version"] == reconciling["version"] + 1, closed
    terminated = b.read_dependent(ctx.dep["id"])
    assert terminated["coverage_end_date"] == "2026-10-31", terminated
    assert closed["audited_annual_savings_cents"] == (
        MONTHLY_COST_CENTS["SPOUSE"] * (12 - 10)
    ), closed


def _two_indistinguishable_governing_programs(b):
    """Two live programs a new child could equally belong to, and a fresh household."""
    audited_a = b.employee()
    audited_b = b.employee()
    newcomer = b.employee(
        coverage_tier="EMPLOYEE_SPOUSE", employer_monthly_premium_cents=121000
    )
    b.dependent(audited_a["id"], "CHILD_BIOLOGICAL")
    b.dependent(audited_b["id"], "CHILD_BIOLOGICAL")

    for program_name, audited in (
        ("PY2026 Audit Wave A", audited_a),
        ("PY2026 Audit Wave B", audited_b),
    ):
        program = b.program(
            program_name=program_name, plan_year=2026, poe_verification_enabled=True
        )
        b.doc_rule(program["id"], "CHILD_BIOLOGICAL")
        b.doc_rule(
            program["id"],
            "CHILD_BIOLOGICAL",
            "POINT_OF_ENROLLMENT",
            grace_days=30,
            auto_terminate_on_lapse=True,
        )
        b.scope(program["id"], "TARGETED", targeted_employee_ids=[audited["id"]])
        b.communicate(program["id"])
    return newcomer


def test_a_new_child_cannot_be_enrolled_while_two_programs_govern_it_equally(
    b, client, clock
):
    """If after applying both keys the leading two candidates are still tied on both,
    the enrollment is refused with `ERR_POE_PROGRAM_AMBIGUOUS` — the service will not
    pick arbitrarily between two governing programs.

    Design: Corner/validations/corner_point_of_enrollment_selector_refuses_to_guess_between_two_tied_programs
    """
    newcomer = _two_indistinguishable_governing_programs(b)

    response = client.create_dependent(
        newcomer["id"], f.dependent_payload("CHILD_BIOLOGICAL"), PROGRAM_ADMIN
    )

    validate_error(response, E.ERR_POE_PROGRAM_AMBIGUOUS, expected_status=409)
    assert b.read_employee(newcomer["id"])["enrolled_dependent_count"] == 0
    assert b.dependents_of(newcomer["id"]) == []


def test_a_relationship_class_no_program_governs_enrolls_outright_with_no_deadline(
    b, client, clock
):
    """If instead the candidate pool is empty, that is not an error at all: the
    dependent is simply created with `coverage_status` `ENROLLED`, `poe_program_id`
    null, and `poe_deadline_at` null.

    Design: Corner/validations/corner_point_of_enrollment_selector_refuses_to_guess_between_two_tied_programs
    """
    newcomer = _two_indistinguishable_governing_programs(b)

    spouse = validate_success(
        client.create_dependent(
            newcomer["id"], f.dependent_payload("SPOUSE"), PROGRAM_ADMIN
        ),
        expected_status=201,
    )

    assert_fields(
        spouse,
        relationship_type="SPOUSE",
        coverage_status="ENROLLED",
        poe_program_id=None,
        poe_deadline_at=None,
        documentation_complete=False,
        accepted_proof_type_count=0,
    )
    household = b.dependents_of(newcomer["id"])
    assert [row["id"] for row in household] == [spouse["id"]], household


def test_registering_a_second_employee_on_an_address_already_in_the_census_is_refused(
    b, client, clock
):
    """a `work_email` that serves as the notification address and must be unique
    across all employees — a duplicate address is a malformed request and yields
    `ERR_INVALID_REQUEST`

    Design: Corner/validations/corner_request_shape_rules_cover_email_uniqueness_and_the_amnesty_attestation
    """
    first = b.employee(work_email="dana.reyes@example.test")

    response = client.create_employee(
        f.employee_payload(work_email="dana.reyes@example.test"), PROGRAM_ADMIN
    )

    validate_error(response, E.ERR_INVALID_REQUEST, expected_status=400)
    held = b.read_employee(first["id"])
    assert held["work_email"] == "dana.reyes@example.test", held
    assert held["version"] == 1, held

    accepted = validate_success(
        client.create_employee(
            f.employee_payload(work_email="dana.reyes+two@example.test"), PROGRAM_ADMIN
        ),
        expected_status=201,
    )
    assert accepted["id"] != first["id"], accepted


def test_a_voluntary_removal_without_a_signed_attestation_is_refused(b, client):
    """an `attestation_signed` flag that must be exactly true — the employee is
    attesting that the dependent is ineligible, and a false or absent attestation is
    refused with `ERR_INVALID_REQUEST`

    Design: Corner/validations/corner_request_shape_rules_cover_email_uniqueness_and_the_amnesty_attestation
    """
    ctx = announced_wave(b, relationships=("SPOUSE",))
    b.set_clock(AMNESTY_RECORDING_INSTANT)

    response = client.create_amnesty_removal(
        f.amnesty_removal_payload(
            ctx.dep["id"], ctx.case["id"], attestation_signed=False
        ),
        employee_headers(ctx.employee["id"]),
    )

    validate_error(response, E.ERR_INVALID_REQUEST, expected_status=400)
    _rows, meta = _removals_of(b, ctx.dep["id"])
    assert meta["total_count"] == 0, meta
    assert b.read_dependent(ctx.dep["id"])["coverage_status"] == "PENDING_VERIFICATION"


def test_a_signed_attestation_removes_the_dependent_from_the_end_of_that_month(
    b, client
):
    """The removal cascades. The dependent moves `PENDING_VERIFICATION →
    AMNESTY_REMOVED` with its own `coverage_end_date` set to the removal's.

    Design: Corner/validations/corner_request_shape_rules_cover_email_uniqueness_and_the_amnesty_attestation
    """
    ctx = announced_wave(b, relationships=("SPOUSE",))
    b.set_clock(AMNESTY_RECORDING_INSTANT)

    removal = validate_success(
        client.create_amnesty_removal(
            f.amnesty_removal_payload(ctx.dep["id"], ctx.case["id"]),
            employee_headers(ctx.employee["id"]),
        ),
        expected_status=201,
    )

    assert_instant_equals(removal["recorded_at"], AMNESTY_RECORDING_INSTANT)
    assert removal["coverage_end_date"] == "2026-09-30", removal
    removed = b.read_dependent(ctx.dep["id"])
    assert_fields(
        removed, coverage_status="AMNESTY_REMOVED", coverage_end_date="2026-09-30"
    )
    _rows, meta = _removals_of(b, ctx.dep["id"])
    assert meta["total_count"] == 1, meta


def test_a_removal_after_the_amnesty_closed_reports_the_phase_rather_than_the_window(
    b, client
):
    """When a single request violates more than one rule, the response must report the
    violation that comes first in the following precedence order. ... 9. Program phase
    admits the operation — `ERR_PROGRAM_PHASE_INVALID` (409), across all program, case,
    submission, amnesty, and appeal write endpoints.

    Design: Corner/validations/corner_program_phase_rule_outranks_the_amnesty_window_rule
    """
    ctx = response_window_wave(b, relationships=("SPOUSE",))
    assert ctx.program["status"] == "RESPONSE_WINDOW", ctx.program

    response = client.create_amnesty_removal(
        f.amnesty_removal_payload(ctx.dep["id"], ctx.case["id"]),
        employee_headers(ctx.employee["id"]),
    )

    validate_error(response, E.ERR_PROGRAM_PHASE_INVALID, expected_status=409)
    _rows, meta = _removals_of(b, ctx.dep["id"])
    assert meta["total_count"] == 0, meta
    assert b.read_dependent(ctx.dep["id"])["coverage_status"] == "PENDING_VERIFICATION"
    assert b.read_program(ctx.program["id"])["amnesty_removed_count"] == 0


def test_reading_a_dependent_that_was_never_enrolled_reports_the_lookup_before_ownership(
    b, client, clock
):
    """Existence of every path-segment resource, resolved left to right — the matching
    404 from the eight-member family in §2.5.

    Design: Corner/validations/corner_existence_is_checked_before_ownership_on_employee_reads
    """
    subscriber = b.employee()

    response = client.get_dependent(
        NON_EXISTENT_UUID, employee_headers(subscriber["id"])
    )

    validate_error(response, E.ERR_DEPENDENT_NOT_FOUND, expected_status=404)


def test_a_subscriber_reading_a_colleagues_dependent_is_refused_as_not_the_owner(
    b, client, clock
):
    """An `Employee` caller who addresses a resource that does not resolve to their own
    employee record is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

    Design: Corner/validations/corner_existence_is_checked_before_ownership_on_employee_reads
    """
    subscriber = b.employee()
    colleague = b.employee()
    colleagues_dependent = b.dependent(colleague["id"], "SPOUSE")

    response = client.get_dependent(
        colleagues_dependent["id"], employee_headers(subscriber["id"])
    )

    validate_error(response, E.ERR_NOT_RESOURCE_OWNER, expected_status=403)


def test_a_subscriber_may_read_their_own_dependent_and_sees_the_scheduled_cost(
    b, client, clock
):
    """This ownership check guards a specific set of operations: reading one employee,
    listing an employee's dependents, reading one dependent

    Design: Corner/validations/corner_existence_is_checked_before_ownership_on_employee_reads
    """
    subscriber = b.employee(
        coverage_tier="EMPLOYEE_SPOUSE", employer_monthly_premium_cents=121000
    )
    own_dependent = b.dependent(subscriber["id"], "SPOUSE")

    dependent = validate_success(
        client.get_dependent(own_dependent["id"], employee_headers(subscriber["id"]))
    )

    assert_fields(
        dependent,
        id=own_dependent["id"],
        employee_id=subscriber["id"],
        coverage_status="ENROLLED",
        monthly_cost_cents=MONTHLY_COST_CENTS["SPOUSE"],
    )
