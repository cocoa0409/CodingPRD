"""Consistency model: nothing in this system is eventually consistent."""
from test_helpers import (
    build_finding,
    build_line,
    build_payment,
    build_worker,
    certify,
    get_success_data,
    move_clock,
    read_assignment,
    setup_env,
    validate_success,
)

WEEK = "2026-08-01T00:00:00.000Z"
ONE_RATE = [{"fringe_hourly_rate_cents": 2000}]
# 40 h paid 4000 base + 2000 cash against a required 5000 + 2000: 1000 short per hour, 40000 total.
DEFICIENT_LINE = {
    "straight_hours": 40.00,
    "overtime_hours": 0.00,
    "base_rate_paid_cents": 4000,
    "overtime_rate_paid_cents": 0,
    "fringe_cash_paid_cents": 2000,
}


def _open_week(api, env):
    version = read_assignment(api, env["assignment"]["id"])["version"]
    return get_success_data(
        api.create_payroll_submission(
            {
                "contract_assignment_id": env["assignment"]["id"],
                "week_ending_date": WEEK,
                "prepared_by_staff_id": env["preparer"]["id"],
                "expected_contract_assignment_version": version,
            },
            env["preparer_headers"],
        ),
        expected_status=201,
    )


def test_the_finalize_response_already_carries_every_computed_total(api, officer_headers):
    """The wage engine's output is in the finalize body itself, and the next GET repeats it exactly.

    PRD 2.9: "Those summary fields are maintained by the service, never written by a client, and
    recomputed synchronously as part of whichever request caused them to change. Nothing in this
    system is eventually consistent: by the time a response is returned, every counter, posture and
    ledger the request touched has already been brought up to date, and every touched row's
    `version` has advanced." PRD 3.6: "A `make_whole_underpayment_cents` greater than zero, or an
    `excess_apprentice_hours` greater than zero, or both, drives it `UNVERIFIED → DEFICIENT`
    instead."

    Design: Corner/consistency_model/the_finalize_response_already_carries_every_computed_total
    """
    env = setup_env(api, rates=ONE_RATE)
    worker = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    submission = _open_week(api, env)
    line = build_line(api, env, submission["id"], worker["id"], **DEFICIENT_LINE)
    move_clock(api, WEEK)

    resp = api.finalize_payroll_submission(submission["id"], env["preparer_headers"])
    validate_success(resp, expected_status=200)
    finalized = get_success_data(resp)
    assert finalized["workflow_status"] == "PENDING_CERTIFICATION"
    assert finalized["compliance_status"] == "DEFICIENT"
    assert float(finalized["total_hours_reported"]) == 40.00
    assert finalized["straight_time_underpayment_cents"] == 40000
    assert finalized["make_whole_underpayment_cents"] == 40000

    re_read = get_success_data(api.get_payroll_submission(submission["id"], officer_headers))
    assert re_read["workflow_status"] == finalized["workflow_status"]
    assert re_read["compliance_status"] == finalized["compliance_status"]
    assert float(re_read["total_hours_reported"]) == 40.00
    assert re_read["straight_time_underpayment_cents"] == 40000
    assert re_read["make_whole_underpayment_cents"] == 40000
    assert re_read["version"] == finalized["version"]

    read_line = get_success_data(api.get_payroll_line(line["id"], officer_headers))
    assert read_line["required_base_cents"] == 5000
    assert read_line["required_fringe_cents"] == 2000
    assert read_line["line_underpayment_cents"] == 40000


def test_a_cascade_target_is_already_current_on_the_very_next_read(api, officer_headers):
    """A disbursement's effect on the contractor, finding and project ledgers needs no settle step.

    PRD 2.9: "Nothing in this system is eventually consistent: by the time a response is returned,
    every counter, posture and ledger the request touched has already been brought up to date, and
    every touched row's `version` has advanced." PRD 3.11: "It then reduces the finding's
    `restitution_outstanding_cents` by the paid amount, increases the owning tier's
    `cumulative_restitution_cents` by the same amount, and recomputes the contractor's
    `outstanding_restitution_cents` and `debarment_risk_score`".

    Design: Corner/consistency_model/a_cascade_target_is_already_current_on_the_very_next_read
    """
    env = setup_env(api, rates=ONE_RATE)
    worker = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    submission = _open_week(api, env)
    build_line(api, env, submission["id"], worker["id"], **DEFICIENT_LINE)
    move_clock(api, WEEK)
    get_success_data(api.finalize_payroll_submission(submission["id"], env["preparer_headers"]))
    certify(api, env, submission["id"])

    finding = build_finding(
        api, env["project"]["id"], submission["id"], worker_id=worker["id"],
        finding_type="UNDERPAYMENT", severity="MAJOR", restitution_required_cents=40000,
    )
    assert finding["restitution_outstanding_cents"] == 40000
    assert get_success_data(
        api.get_contractor(env["contractor"]["id"], officer_headers)
    )["outstanding_restitution_cents"] == 40000
    payment = build_payment(api, env, finding["id"], worker["id"], 20000)
    assert payment["status"] == "PENDING"

    resp = api.disburse_restitution_payment(payment["id"], env["preparer_headers"])
    validate_success(resp, expected_status=200)
    assert get_success_data(resp)["status"] == "DISBURSED"

    assert get_success_data(
        api.get_contractor(env["contractor"]["id"], officer_headers)
    )["outstanding_restitution_cents"] == 20000
    assert get_success_data(
        api.get_finding(finding["id"], officer_headers)
    )["restitution_outstanding_cents"] == 20000
    assert get_success_data(
        api.get_project(env["project"]["id"], officer_headers)
    )["outstanding_restitution_cents"] == 20000
    assert read_assignment(api, env["assignment"]["id"])["cumulative_restitution_cents"] == 20000
