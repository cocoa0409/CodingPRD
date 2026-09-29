"""Cross-cutting complexity: the two optimistic-concurrency guards of PRD 2.7."""
from test_helpers import (
    ApiErrorId,
    build_finding,
    build_line,
    build_payment,
    build_worker,
    certify,
    get_success_data,
    move_clock,
    read_assignment,
    setup_env,
    validate_error,
    validate_paginated,
)

WEEK = "2026-08-01T00:00:00.000Z"
NEXT_WEEK = "2026-08-08T00:00:00.000Z"
ONE_RATE = [{"fringe_hourly_rate_cents": 2000}]


def _file_week(api, env, week, expected_version):
    return api.create_payroll_submission(
        {
            "contract_assignment_id": env["assignment"]["id"],
            "week_ending_date": week,
            "prepared_by_staff_id": env["preparer"]["id"],
            "expected_contract_assignment_version": expected_version,
        },
        env["preparer_headers"],
    )


def test_a_second_filing_with_the_first_filings_assignment_version_is_412(
    api, portal_admin_headers
):
    """Filing week one bumps the tier, so re-using the activation-time version is stale at 412.

    PRD 2.7: "`POST /payroll-submissions` requires a non-optional
    `expected_contract_assignment_version` field carrying the `version` of the `ContractAssignment`
    named in `contract_assignment_id` as the client last read it. If that value does not equal the
    assignment's current `version`, the create is rejected with `ERR_STALE_ASSIGNMENT_VERSION`
    (HTTP 412)." PRD 3.5: "creating it also advances the owning tier's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/a_second_filing_with_the_first_filings_assignment_version_is_412
    """
    env = setup_env(api, rates=ONE_RATE)
    captured = read_assignment(api, env["assignment"]["id"])["version"]
    first = get_success_data(_file_week(api, env, WEEK, captured), expected_status=201)
    assert first["week_ending_date"] == WEEK
    after_first = read_assignment(api, env["assignment"]["id"])["version"]
    assert after_first == captured + 1

    resp = _file_week(api, env, NEXT_WEEK, captured)
    validate_error(resp, ApiErrorId.ERR_STALE_ASSIGNMENT_VERSION.value, expected_status=412)

    assert read_assignment(api, env["assignment"]["id"])["version"] == after_first
    surviving = get_success_data(
        api.list_payroll_submissions(
            portal_admin_headers, params={"contract_assignment_id": env["assignment"]["id"]}
        )
    )
    assert [row["week_ending_date"] for row in surviving] == [WEEK]


def test_re_reading_the_assignment_version_lets_the_next_week_through(api, portal_admin_headers):
    """The version is a counter, not a token: a fresh read makes the identical payload succeed.

    PRD 2.7: "If that value does not equal the assignment's current `version`, the create is
    rejected with `ERR_STALE_ASSIGNMENT_VERSION` (HTTP 412)." PRD 3.5: "A new submission is created
    with `workflow_status` `DRAFT` and `compliance_status` `UNVERIFIED` ... creating it also
    advances the owning tier's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/re_reading_the_assignment_version_lets_the_next_week_through
    """
    env = setup_env(api, rates=ONE_RATE)
    captured = read_assignment(api, env["assignment"]["id"])["version"]
    get_success_data(_file_week(api, env, WEEK, captured), expected_status=201)

    rows, _meta = validate_paginated(
        api.list_contract_assignments(
            env["preparer_headers"], params={"project_id": env["project"]["id"]}
        )
    )
    re_read = next(row for row in rows if row["id"] == env["assignment"]["id"])["version"]
    assert re_read == captured + 1

    second = get_success_data(_file_week(api, env, NEXT_WEEK, re_read), expected_status=201)
    assert second["workflow_status"] == "DRAFT"
    assert second["compliance_status"] == "UNVERIFIED"
    assert second["week_ending_date"] == NEXT_WEEK
    assert read_assignment(api, env["assignment"]["id"])["version"] == captured + 2


def test_responding_to_a_finding_whose_balance_moved_underneath_you_is_412(api, officer_headers):
    """A sibling disbursement moves the version while the finding stays OPEN, so it is 412 not 409.

    PRD 2.7: "`POST /findings/{id}/response` requires a non-optional `expected_finding_version`
    field carrying the `version` of the target `Finding` as the client last read it. If that value
    does not equal the finding's current `version`, the response filing is rejected with
    `ERR_STALE_FINDING_VERSION` (HTTP 412)." PRD 3.11: "It then reduces the finding's
    `restitution_outstanding_cents` by the paid amount ... advancing the `version` of the payment,
    the finding, the tier and the contractor by one each."

    Design: Corner/cross_cutting_complexity_layers/responding_to_a_finding_whose_balance_moved_underneath_you_is_412
    """
    env = setup_env(api, rates=ONE_RATE)
    worker = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    version = read_assignment(api, env["assignment"]["id"])["version"]
    submission = get_success_data(_file_week(api, env, WEEK, version), expected_status=201)
    build_line(
        api, env, submission["id"], worker["id"],
        straight_hours=40.00, overtime_hours=0.00,
        base_rate_paid_cents=4000, overtime_rate_paid_cents=0, fringe_cash_paid_cents=2000,
    )
    move_clock(api, WEEK)
    finalized = get_success_data(api.finalize_payroll_submission(submission["id"], env["preparer_headers"]))
    assert finalized["make_whole_underpayment_cents"] == 40000
    certify(api, env, submission["id"])

    finding = build_finding(
        api, env["project"]["id"], submission["id"], worker_id=worker["id"],
        finding_type="UNDERPAYMENT", severity="MAJOR", restitution_required_cents=40000,
    )
    captured_version = finding["version"]
    payment = build_payment(api, env, finding["id"], worker["id"], 20000)
    disbursed = get_success_data(
        api.disburse_restitution_payment(payment["id"], env["preparer_headers"])
    )
    assert disbursed["status"] == "DISBURSED"

    resp = api.file_finding_response(
        finding["id"],
        {
            "response_narrative": "Half the restitution is already out the door.",
            "expected_finding_version": captured_version,
        },
        env["certifier_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_FINDING_VERSION.value, expected_status=412)

    after = get_success_data(api.get_finding(finding["id"], officer_headers))
    assert after["status"] == "OPEN"
    assert after["response_round"] == 0
    assert after["response_narrative"] is None
    assert after["restitution_outstanding_cents"] == 20000
    assert after["version"] > captured_version
    assert get_success_data(
        api.get_restitution_payment(payment["id"], officer_headers)
    )["status"] == "DISBURSED"
