"""Validation corners: rung ordering, uniqueness, ownership and window guards."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    build_contractor,
    build_finding,
    build_line,
    build_payment,
    build_staff,
    build_submission,
    build_worker,
    compliant_paid_line,
    fringe_plan_payload,
    get_success_data,
    make_certifier_headers,
    make_preparer_headers,
    rule_on_fringe_plan,
    setup_deficient_submission_under_review,
    setup_env,
    setup_env_with_worker,
    setup_finalized_submission,
    validate_error,
    validate_success,
)

WEEK = "2026-08-01T00:00:00.000Z"
PRIOR_WEEK = "2026-07-25T00:00:00.000Z"
NEXT_WEEK = "2026-08-08T00:00:00.000Z"
ONE_RATE = [{"fringe_hourly_rate_cents": 2000}]
APPRENTICE_RATES = [{"fringe_hourly_rate_cents": 2000, "apprentice_scale_pct": [50, 60, 70, 80]}]


def test_an_unknown_finding_id_outranks_the_missing_withdrawal_reason(api, cruz_headers):
    """Rung 3 fires on the path id, so the empty body is never even shape-checked.

    PRD 2.8: "the service reports the failure from the highest rung of the following ladder that
    the request trips, and stops there." PRD 2.8 rung 3: "Path-segment existence, left to right,
    as described in §2.6 — the ten 404 identifiers." PRD 2.8 rung 7: "Body shape and field-level
    constraints — types, ranges, string lengths, enum membership, array bounds, decimal scale and
    required-field presence — reported as `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/validations/path_existence_precedes_body_shape_on_an_unknown_finding
    """
    resp = api.withdraw_finding(NON_EXISTENT_UUID, {}, cruz_headers)
    validate_error(resp, ApiErrorId.ERR_FINDING_NOT_FOUND.value, expected_status=404)


def test_a_second_line_for_the_same_worker_in_one_week_is_rejected(api, portal_admin_headers):
    """One line per worker per submission: the duplicate is a 409 and does not move the version.

    PRD 3.5: "A submission may carry at most one line per worker, so a second line for the same
    `worker_id` on the same submission is refused with `ERR_DUPLICATE_WORKER_LINE`." PRD 3.5:
    "Adding a line advances the owning submission's `version` by one."

    Design: Corner/validations/a_second_line_for_the_same_worker_in_one_week_is_rejected
    """
    env = setup_env_with_worker(api, rates=ONE_RATE)
    submission = build_submission(api, env, week_ending_date=WEEK)
    build_line(api, env, submission["id"], env["worker"]["id"], **compliant_paid_line())

    resp = api.add_payroll_line(
        submission["id"],
        {
            "worker_id": env["worker"]["id"],
            "classification_code": "ELEC-INSIDE-JW",
            "straight_hours": 4.00,
            "overtime_hours": 0.00,
            "base_rate_paid_cents": 5000,
            "overtime_rate_paid_cents": 0,
            "fringe_cash_paid_cents": 2000,
        },
        env["preparer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_WORKER_LINE.value, expected_status=409)

    unchanged = get_success_data(api.get_payroll_submission(submission["id"], portal_admin_headers))
    assert unchanged["workflow_status"] == "DRAFT"
    assert unchanged["version"] == 2
    lines = get_success_data(
        api.list_payroll_lines(portal_admin_headers, params={"payroll_submission_id": submission["id"]})
    )
    assert len(lines) == 1


def test_back_to_back_payroll_weeks_that_share_no_day_are_permitted(api, portal_admin_headers):
    """Weeks ending 07-25 and 08-01 abut without overlapping, so both may be live at once.

    PRD 2.11: "A **payroll week** is closed on both ends. A submission whose `week_ending_date`
    is a given Saturday covers the interval running from six days before that Saturday through
    the Saturday itself, with both endpoints included. Two consecutive weekly payrolls therefore
    share no day and do not collide." PRD 3.5: "if the two intervals share any instant the create
    is refused with `ERR_PAYROLL_WEEK_OVERLAP`."

    Design: Corner/validations/back_to_back_payroll_weeks_that_share_no_day_are_permitted
    """
    env = setup_env(api, rates=ONE_RATE)
    first = build_submission(api, env, week_ending_date=PRIOR_WEEK)
    assert first["workflow_status"] == "DRAFT"

    assignment = get_success_data(
        api.get_contract_assignment(env["assignment"]["id"], portal_admin_headers)
    )
    resp = api.create_payroll_submission(
        {
            "contract_assignment_id": env["assignment"]["id"],
            "week_ending_date": WEEK,
            "prepared_by_staff_id": env["preparer"]["id"],
            "expected_contract_assignment_version": assignment["version"],
        },
        env["preparer_headers"],
    )
    second = get_success_data(resp, expected_status=201)
    validate_success(resp, expected_status=201)
    assert second["week_ending_date"] == WEEK
    assert second["workflow_status"] == "DRAFT"

    both = get_success_data(
        api.list_payroll_submissions(
            portal_admin_headers, params={"contract_assignment_id": env["assignment"]["id"]}
        )
    )
    assert len(both) == 2
    assert {row["workflow_status"] for row in both} == {"DRAFT"}


def test_a_line_may_not_claim_another_contractors_fringe_plan(
    api, officer_headers, portal_admin_headers
):
    """Plan ownership is checked against the line's tier, even for an APPROVED plan.

    PRD 3.5: "A named `fringe_plan_id` must belong to the contractor of the line's tier — naming
    another firm's plan is `ERR_FRINGE_PLAN_FOREIGN`".

    Design: Corner/validations/a_line_may_not_claim_another_contractors_fringe_plan
    """
    env = setup_env_with_worker(api, rates=ONE_RATE)
    other = build_contractor(api, legal_name="Bay Conduit")
    other_preparer = build_staff(api, other["id"], full_name="Otto Other", capability="PREPARER")
    foreign_plan = get_success_data(
        api.create_fringe_plan(
            other["id"],
            fringe_plan_payload(
                plan_name="Bay Conduit Trust",
                annual_contribution_cents=6300000,
                annual_total_hours=2100.00,
                annual_public_works_hours=2100.00,
            ),
            make_preparer_headers(other_preparer["id"]),
        ),
        expected_status=201,
    )
    approved = rule_on_fringe_plan(api, foreign_plan["id"], "APPROVED", officer_headers)
    assert approved["approval_status"] == "APPROVED"
    assert approved["annualized_credit_cents"] == 3000

    submission = build_submission(api, env, week_ending_date=WEEK)
    resp = api.add_payroll_line(
        submission["id"],
        {
            "worker_id": env["worker"]["id"],
            "classification_code": "ELEC-INSIDE-JW",
            "straight_hours": 40.00,
            "overtime_hours": 0.00,
            "base_rate_paid_cents": 5000,
            "overtime_rate_paid_cents": 0,
            "fringe_cash_paid_cents": 0,
            "fringe_plan_id": foreign_plan["id"],
        },
        env["preparer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_FRINGE_PLAN_FOREIGN.value, expected_status=422)

    unchanged = get_success_data(api.get_payroll_submission(submission["id"], portal_admin_headers))
    assert unchanged["version"] == 1
    assert float(unchanged["total_hours_reported"]) == 0.00


def test_a_week_that_has_not_closed_yet_cannot_be_finalized(api, portal_admin_headers):
    """With the clock at 08-01 a week ending 08-08 is still open, so the engine refuses to run.

    PRD 3.6: "The payroll week must be over: the logical clock must read at or after the
    submission's `week_ending_date`, and an earlier clock is refused with
    `ERR_PAYROLL_WEEK_NOT_ENDED`." PRD 3.5: "Every computed field on a fresh line —
    `required_base_cents`, `required_fringe_cents`, `creditable_fringe_cents`,
    `reclassified_journey_hours` and `line_underpayment_cents` — stays at 0 until the payroll is
    finalized."

    Design: Corner/validations/a_week_that_has_not_closed_yet_cannot_be_finalized
    """
    env = setup_env_with_worker(api, rates=ONE_RATE)
    submission = build_submission(api, env, week_ending_date=NEXT_WEEK)
    line = build_line(
        api, env, submission["id"], env["worker"]["id"], **compliant_paid_line()
    )

    resp = api.finalize_payroll_submission(submission["id"], env["preparer_headers"])
    validate_error(resp, ApiErrorId.ERR_PAYROLL_WEEK_NOT_ENDED.value, expected_status=422)

    unchanged = get_success_data(api.get_payroll_submission(submission["id"], portal_admin_headers))
    assert unchanged["workflow_status"] == "DRAFT"
    assert unchanged["compliance_status"] == "UNVERIFIED"
    assert float(unchanged["total_hours_reported"]) == 0.00
    read_line = get_success_data(api.get_payroll_line(line["id"], portal_admin_headers))
    assert read_line["required_base_cents"] == 0
    assert read_line["required_fringe_cents"] == 0
    assert read_line["line_underpayment_cents"] == 0


def test_notarization_is_demanded_only_by_portals_that_configure_it(api, portal_admin_headers):
    """The same empty certify payload is fatal under a notarizing portal and fine under a plain one.

    PRD 3.7: "A portal also declares `requires_notarized_statement`, a flag defaulting to false
    which, when true, makes the notary reference mandatory at signing time." PRD 3.7:
    "`notary_reference_number` carries the notary commission reference; when the project's portal
    has `requires_notarized_statement` true, this field must be present *and* must equal the
    acting staff member's own stored `notary_reference_number`, and an absent or non-matching
    value is refused with `ERR_NOTARIZATION_REQUIRED`."

    Design: Corner/validations/notarization_is_demanded_only_by_portals_that_configure_it
    """
    strict_env, strict_submission, _rows = setup_finalized_submission(
        api,
        lines=[compliant_paid_line()],
        week_ending_date=WEEK,
        rates=ONE_RATE,
        portal_overrides={"requires_notarized_statement": True},
    )
    assert strict_env["portal"]["requires_notarized_statement"] is True
    assert strict_submission["workflow_status"] == "PENDING_CERTIFICATION"
    notary = build_staff(
        api, strict_env["contractor"]["id"],
        full_name="Nora Notary", capability="CERTIFIER", notary_reference_number="NP-9001",
    )
    resp = api.certify_payroll_submission(
        strict_submission["id"], make_certifier_headers(notary["id"]), {}
    )
    validate_error(resp, ApiErrorId.ERR_NOTARIZATION_REQUIRED.value, expected_status=422)

    unsigned = get_success_data(
        api.get_payroll_submission(strict_submission["id"], portal_admin_headers)
    )
    assert unsigned["workflow_status"] == "PENDING_CERTIFICATION"
    assert unsigned["certified_by_staff_id"] is None
    assert unsigned["statement_signed_at"] is None
    assert unsigned["submitted_at"] is None

    # PRD 3.1: a locality may not be governed by two ACTIVE determinations at once, so the
    # second environment publishes its determination (and locks its project) in another county.
    plain_env, plain_submission, _plain_rows = setup_finalized_submission(
        api,
        lines=[compliant_paid_line()],
        week_ending_date=WEEK,
        rates=ONE_RATE,
        determination_overrides={"locality_code": "CA-SONOMA"},
        project_overrides={"locality_code": "CA-SONOMA"},
    )
    assert plain_env["portal"]["requires_notarized_statement"] is False
    signed = get_success_data(
        api.certify_payroll_submission(
            plain_submission["id"], plain_env["certifier_headers"], {}
        )
    )
    assert signed["workflow_status"] == "SUBMITTED"
    assert signed["certified_by_staff_id"] == plain_env["certifier"]["id"]


def test_trade_mismatch_is_only_reachable_after_the_wage_rate_is_matched(api, portal_admin_headers):
    """A PLUMB program on an ELEC line clears rate coverage and then trips the trade check.

    PRD 3.5: "A wage rate row must exist for the combination of the project's locked
    determination, the line's `classification_code`, and the project's `zone_code`; when none
    does, the line is refused with `ERR_NO_WAGE_RATE_FOR_CLASSIFICATION`." PRD 3.5: "that
    program's `trade_code` must equal the `trade_code` of the matched wage rate row, or the line
    is refused with `ERR_APPRENTICE_TRADE_MISMATCH`".

    Design: Corner/validations/trade_mismatch_is_only_reachable_after_the_wage_rate_is_matched
    """
    env = setup_env(
        api, rates=APPRENTICE_RATES, with_program={"trade_code": "PLUMB", "registration_status": "REGISTERED"}
    )
    assert env["program"]["trade_code"] == "PLUMB"
    assert env["rate"]["trade_code"] == "ELEC"
    apprentice = build_worker(
        api, env["contractor"]["id"], env["preparer_headers"],
        apprentice_program_id=env["program"]["id"], apprentice_period=1,
    )
    submission = build_submission(api, env, week_ending_date=WEEK)

    resp = api.add_payroll_line(
        submission["id"],
        {
            "worker_id": apprentice["id"],
            "classification_code": "ELEC-INSIDE-JW",
            "straight_hours": 8.00,
            "overtime_hours": 0.00,
            "base_rate_paid_cents": 2500,
            "overtime_rate_paid_cents": 0,
            "fringe_cash_paid_cents": 2000,
            "reported_as_apprentice": True,
        },
        env["preparer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_APPRENTICE_TRADE_MISMATCH.value, expected_status=422)

    unchanged = get_success_data(api.get_payroll_submission(submission["id"], portal_admin_headers))
    assert unchanged["workflow_status"] == "DRAFT"
    assert unchanged["version"] == 1


def test_two_legal_restitution_payments_may_not_sum_past_the_obligation(api, officer_headers):
    """Each 60000 payment fits under 100000 alone; the committed total is what is capped.

    PRD 3.11: "A ceiling applies at scheduling time: the sum of `amount_cents` over the payments
    already on that finding whose `status` is `PENDING` or `DISBURSED`, plus the new amount, must
    not exceed the finding's `restitution_required_cents`, and a request that would push the
    committed total past the obligation is refused with `ERR_RESTITUTION_EXCEEDS_OBLIGATION`."
    PRD 3.11: "A scheduled payment starts at `status` `PENDING` ... and it deliberately leaves the
    finding's outstanding balance untouched — scheduling is a promise, not a movement."

    Design: Corner/validations/two_individually_legal_restitution_payments_may_not_sum_past_the_obligation
    """
    env, submission, rows = setup_deficient_submission_under_review(api)
    finding = build_finding(
        api, env["project"]["id"], submission["id"],
        finding_type="MISCLASSIFICATION", severity="MAJOR", restitution_required_cents=100000,
    )
    assert finding["status"] == "OPEN"
    first = build_payment(api, env, finding["id"], rows[0]["worker_id"], 60000)
    assert first["status"] == "PENDING"

    resp = api.create_restitution_payment(
        finding["id"],
        {"worker_id": rows[0]["worker_id"], "amount_cents": 60000},
        env["preparer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_RESTITUTION_EXCEEDS_OBLIGATION.value, expected_status=422)

    assert get_success_data(
        api.get_restitution_payment(first["id"], officer_headers)
    )["status"] == "PENDING"
    after = get_success_data(api.get_finding(finding["id"], officer_headers))
    assert after["restitution_required_cents"] == 100000
    assert after["restitution_outstanding_cents"] == 100000
    assignment = get_success_data(
        api.get_contract_assignment(env["assignment"]["id"], officer_headers)
    )
    assert assignment["cumulative_restitution_cents"] == 0
