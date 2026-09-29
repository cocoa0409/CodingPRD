"""Endpoint corners: the sole PATCH, closeout gating, composite reads and self edges."""
from test_helpers import (
    ApiErrorId,
    build_finding,
    build_interview,
    build_program,
    build_submission,
    certify,
    compliant_paid_line,
    get_success_data,
    read_assignment,
    setup_env_with_worker,
    setup_finalized_submission,
    validate_error,
    validate_success,
)

WEEK = "2026-08-01T00:00:00.000Z"
ONE_RATE = [{"fringe_hourly_rate_cents": 2000}]


def test_patching_a_program_to_lapsed_updates_only_its_registration_standing(
    api, portal_admin_headers
):
    """The one PATCH in the surface moves the standing and leaves the program's terms alone.

    PRD 3.2: "Only a program in `REGISTERED` standing supports apprentice-rate payroll lines —
    `PROVISIONAL` and `LAPSED` programs do not — and a `PortalAdmin` may move a program between
    the three standings at any time, which advances the program's `version` by one." PRD endpoint
    catalogue: "PATCH `/apprentice-programs/{id}` Updates a program's registration standing".

    Design: Corner/endpoints/patching_a_program_to_lapsed_updates_only_registration_status
    """
    program = build_program(
        api,
        registration_number="AP-ELEC-77",
        sponsor_name="Alameda Electrical JATC",
        trade_code="ELEC",
        registration_status="REGISTERED",
        allowed_apprentice_hours_per_100_journey=25,
        period_count=4,
    )
    resp = api.update_apprentice_program(
        program["id"], {"registration_status": "LAPSED"}, portal_admin_headers
    )
    patched = get_success_data(resp)
    validate_success(resp, expected_status=200)
    assert patched["registration_status"] == "LAPSED"
    assert patched["sponsor_name"] == "Alameda Electrical JATC"
    assert patched["trade_code"] == "ELEC"
    assert patched["allowed_apprentice_hours_per_100_journey"] == 25
    assert patched["period_count"] == 4
    assert patched["version"] == 2


def test_closeout_is_refused_while_a_finding_and_a_live_payroll_remain(
    api, portal_admin_headers, cruz_headers
):
    """Two of the three closeout conditions fail at once and none of the CLOSED cascade runs.

    PRD 3.11: "Three conditions must hold together: the project's `open_finding_count` must be 0,
    its `outstanding_restitution_cents` must be 0, and no payroll submission on any of its tiers
    may sit in `DRAFT`, `PENDING_CERTIFICATION`, `SUBMITTED`, `UNDER_REVIEW` or `RETURNED`. Any of
    the three failing refuses the closeout with `ERR_OPEN_FINDINGS_BLOCK_CLOSEOUT`". PRD 3.11: "A
    successful closeout sets `status` to `CLOSED` ... and drives every tier on the project whose
    `status` is `INVITED`, `ACTIVE` or `SUSPENDED` to `TERMINATED`".

    Design: Corner/endpoints/closeout_is_refused_while_a_finding_and_a_live_payroll_remain
    """
    env, submission, rows = setup_finalized_submission(
        api, lines=[compliant_paid_line()], week_ending_date=WEEK, rates=ONE_RATE
    )
    submission = certify(api, env, submission["id"])
    assert submission["workflow_status"] == "SUBMITTED"
    finding = build_finding(
        api, env["project"]["id"], submission["id"],
        worker_id=rows[0]["worker_id"], finding_type="FRINGE_CREDIT",
        severity="MINOR", restitution_required_cents=0,
    )
    assert finding["status"] == "OPEN"
    staged = get_success_data(
        api.set_project_status(
            env["project"]["id"], {"to_status": "SUBSTANTIALLY_COMPLETE"}, portal_admin_headers
        )
    )
    assert staged["status"] == "SUBSTANTIALLY_COMPLETE"

    resp = api.set_project_status(
        env["project"]["id"], {"to_status": "CLOSED"}, portal_admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_OPEN_FINDINGS_BLOCK_CLOSEOUT.value, expected_status=409)

    project = get_success_data(api.get_project(env["project"]["id"], portal_admin_headers))
    assert project["status"] == "SUBSTANTIALLY_COMPLETE"
    assert project["open_finding_count"] == 1
    assert read_assignment(api, env["assignment"]["id"])["status"] == "ACTIVE"
    assert get_success_data(
        api.get_payroll_submission(submission["id"], cruz_headers)
    )["workflow_status"] == "SUBMITTED"


def test_the_underpayment_summary_reports_both_variants_and_their_delta(api, officer_headers):
    """4000 straight-time, 5200 make-whole, delta 1200: the read echoes and subtracts only.

    PRD 3.6: "A read-only summary exposes both variants side by side for any submission, echoing
    the `payroll_submission_id`, reporting `straight_time_underpayment_cents` and
    `make_whole_underpayment_cents`, the `variant_delta_cents` between them — the make-whole total
    minus the straight-time total — plus the submission's `excess_apprentice_hours` and the
    `line_count` of payroll lines it carries." PRD 3.6: "`straight_time_underpayment_cents` is the
    sum of the per-line straight-time deficiencies only ... `make_whole_underpayment_cents` is the
    sum of the per-line `line_underpayment_cents` values".

    Design: Corner/endpoints/underpayment_summary_reports_both_variants_and_their_delta
    """
    env, submission, rows = setup_finalized_submission(
        api,
        lines=[{
            "straight_hours": 40.00,
            "overtime_hours": 8.00,
            "base_rate_paid_cents": 4900,
            "overtime_rate_paid_cents": 7350,
            "fringe_cash_paid_cents": 2000,
        }],
        week_ending_date=WEEK,
        rates=ONE_RATE,
    )
    # 100 cents short on 40 straight hours; 150 cents short of round(5000 * 1.5) on 8 OT hours.
    assert submission["straight_time_underpayment_cents"] == 4000
    assert submission["make_whole_underpayment_cents"] == 5200

    resp = api.get_underpayment_summary(submission["id"], officer_headers)
    summary = get_success_data(resp)
    validate_success(resp, expected_status=200)
    assert summary["payroll_submission_id"] == submission["id"]
    assert summary["straight_time_underpayment_cents"] == 4000
    assert summary["make_whole_underpayment_cents"] == 5200
    assert summary["variant_delta_cents"] == 1200
    assert float(summary["excess_apprentice_hours"]) == 0.00
    assert summary["line_count"] == 1

    line = get_success_data(api.get_payroll_line(rows[0]["id"], officer_headers))
    assert line["line_underpayment_cents"] == 5200
    assert env["project"]["zone_code"] == "BASE"


def test_cancelling_an_interview_frees_its_buffered_window(api, cruz_headers):
    """The overlapping second slot is a 201 only because CANCELLED rows occupy nothing.

    PRD 3.9: "The requested window is expanded by a full hour — sixty minutes — on each side, and
    the expanded span must not intersect the *unexpanded* window of any other interview on the
    same `worker_id` whose `status` is `SCHEDULED`, `CONDUCTED_MATCHED` or
    `CONDUCTED_DISCREPANT`." PRD 3.9: "Interviews in `CANCELLED` do not occupy anything:
    cancelling frees the window, and a new interview on the same worker may then take an
    overlapping or buffer-adjacent slot."

    Design: Corner/endpoints/cancelling_an_interview_frees_its_buffered_window
    """
    env = setup_env_with_worker(api, rates=ONE_RATE)
    first = build_interview(
        api, env, env["worker"]["id"],
        "2026-07-29T10:00:00.000Z", "2026-07-29T12:00:00.000Z",
    )
    assert first["status"] == "SCHEDULED"
    cancelled = get_success_data(
        api.cancel_interview(
            first["id"], {"cancellation_reason": "Auditor reassigned to another site."},
            cruz_headers,
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["version"] == 2

    resp = api.create_interview(
        {
            "project_id": env["project"]["id"],
            "contract_assignment_id": env["assignment"]["id"],
            "worker_id": env["worker"]["id"],
            "window_start": "2026-07-29T11:00:00.000Z",
            "window_end": "2026-07-29T13:00:00.000Z",
        },
        cruz_headers,
    )
    second = get_success_data(resp, expected_status=201)
    validate_success(resp, expected_status=201)
    assert second["status"] == "SCHEDULED"
    assert get_success_data(api.get_worker(env["worker"]["id"], cruz_headers))["interview_count"] == 0


def test_a_correction_filing_links_back_to_the_returned_week_it_replaces(api, officer_headers):
    """The RETURNED row releases its week, and the self edge resolves in both directions.

    PRD 3.5: "Rows in `RETURNED` are the exception: a returned filing releases its week, so a
    correction may be filed for it." PRD 3.5: "When `superseded_submission_id` is supplied it must
    name a submission on the same `contract_assignment_id`, carrying the same `week_ending_date`,
    and currently in `workflow_status` `RETURNED`". PRD 3.5: "because returning a payroll advances
    the tier's `version`, a preparer who read the tier before the return must re-read it, or their
    correction filing will be rejected as stale."

    Design: Corner/endpoints/a_correction_filing_links_back_to_the_returned_week_it_replaces
    """
    env, first, _rows = setup_finalized_submission(
        api, lines=[compliant_paid_line()], week_ending_date=WEEK, rates=ONE_RATE
    )
    certify(api, env, first["id"])
    get_success_data(api.begin_review_payroll_submission(first["id"], officer_headers))
    returned = get_success_data(
        api.return_payroll_submission(
            first["id"],
            {"return_reason": "Classification for W-001 does not match the site observation."},
            officer_headers,
        )
    )
    assert returned["workflow_status"] == "RETURNED"

    correction = build_submission(
        api, env, week_ending_date=WEEK, superseded_submission_id=first["id"]
    )
    assert correction["superseded_submission_id"] == first["id"]
    assert correction["workflow_status"] == "DRAFT"
    assert correction["week_ending_date"] == WEEK

    resp = api.list_payroll_submissions(
        officer_headers, params={"superseded_submission_id": first["id"]}
    )
    reverse = get_success_data(resp)
    validate_success(resp, expected_status=200)
    assert resp.json()["meta"]["total_count"] == 1
    assert reverse[0]["id"] == correction["id"]
    assert get_success_data(
        api.get_payroll_submission(first["id"], officer_headers)
    )["workflow_status"] == "RETURNED"
    assert float(read_assignment(api, env["assignment"]["id"])["cumulative_certified_hours"]) == 0.00
