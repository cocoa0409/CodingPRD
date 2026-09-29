"""Error corners on the lookup and body-shape rungs: 401s, the ten 404s and ERR_VALIDATION."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    build_rate,
    build_submission,
    build_user_headers,
    get_success_data,
    read_assignment,
    setup_env,
    setup_env_with_worker,
    validate_error,
    wage_determination_payload,
)

WEEK = "2026-08-01T00:00:00.000Z"
FRIDAY = "2026-07-31T00:00:00.000Z"
ONE_RATE = [{"fringe_hourly_rate_cents": 2000}]


def test_a_caller_presenting_an_undeclared_role_is_rejected_before_any_lookup(api):
    """An unrecognised X-User-Role is a 401 authentication failure, not a 403 authorisation one.

    PRD 2.1: "If either header is absent, or if `X-User-Role` is not exactly one of the five role
    names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers
    are well-formed but the named role is not listed as an authorized role for the endpoint being
    called (see the table in §4), the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).
    These two checks run before anything else: they are the first and second gates on every
    request in the system."

    Design: Corner/errors/an_unauthenticated_caller_is_rejected_before_any_lookup
    """
    resp = api.list_projects(build_user_headers("mystery-caller", "SiteInspector"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_activating_an_unknown_assignment_id_is_the_assignment_404(api, portal_admin_headers):
    """The activate endpoint carries no body, so only the path id can fail — and it 404s.

    PRD 2.6: "Nested paths are resolved left to right, and the first segment that fails to resolve
    determines the error. A request naming a project that does not exist fails with
    `ERR_PROJECT_NOT_FOUND`; a contract assignment, with `ERR_ASSIGNMENT_NOT_FOUND`". PRD 2.8 rung
    8: "State legality ... `ERR_INVALID_ASSIGNMENT_STATE`."

    Design: Corner/errors/activating_an_unknown_assignment_id_is_404
    """
    resp = api.activate_contract_assignment(NON_EXISTENT_UUID, portal_admin_headers)
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND.value, expected_status=404)


def test_finalizing_an_unknown_submission_id_is_the_submission_404(api, preparer_headers):
    """The wage engine never runs: the path id is resolved first and nothing is created.

    PRD 2.6: "A request naming ... a payroll submission, with `ERR_SUBMISSION_NOT_FOUND`". PRD 2.8
    rung 3: "Path-segment existence, left to right, as described in §2.6 — the ten 404
    identifiers."

    Design: Corner/errors/finalizing_an_unknown_submission_id_is_404
    """
    resp = api.finalize_payroll_submission(NON_EXISTENT_UUID, preparer_headers)
    validate_error(resp, ApiErrorId.ERR_SUBMISSION_NOT_FOUND.value, expected_status=404)


def test_disbursing_an_unknown_restitution_id_is_the_payment_404(api, preparer_headers):
    """The endpoint that moves money resolves its path id before touching any ledger.

    PRD 2.6: "A request naming ... a restitution payment, with `ERR_RESTITUTION_NOT_FOUND`". PRD
    2.6: "All ten are HTTP 404."

    Design: Corner/errors/disbursing_an_unknown_restitution_id_is_404
    """
    resp = api.disburse_restitution_payment(NON_EXISTENT_UUID, preparer_headers)
    validate_error(resp, ApiErrorId.ERR_RESTITUTION_NOT_FOUND.value, expected_status=404)


def test_cancelling_an_unknown_interview_id_is_the_interview_404(api, cruz_headers):
    """Path existence outranks the interview state gate, so a good reason cannot rescue a bad id.

    PRD 2.6: "A request naming ... an interview, with `ERR_INTERVIEW_NOT_FOUND`". PRD 3.9: "an
    attempt to cancel an interview that has already been conducted or cancelled is refused with
    `ERR_INVALID_INTERVIEW_STATE`."

    Design: Corner/errors/cancelling_an_unknown_interview_id_is_404
    """
    resp = api.cancel_interview(
        NON_EXISTENT_UUID, {"cancellation_reason": "Auditor reassigned."}, cruz_headers
    )
    validate_error(resp, ApiErrorId.ERR_INTERVIEW_NOT_FOUND.value, expected_status=404)


def test_an_unknown_apprentice_program_id_in_a_worker_body_is_the_program_404(
    api, portal_admin_headers
):
    """An optional body FK is still a checked body FK when it is supplied.

    PRD 3.2: "An apprentice additionally names an `apprentice_program_id` identifying the
    enrolling program and an `apprentice_period`, a one-based index selecting an entry from the
    published apprentice scale; both are null for a journeyworker." PRD 2.6: "An unresolvable body
    reference produces the 404 belonging to its target kind — ... or `ERR_PROGRAM_NOT_FOUND`."

    Design: Corner/errors/an_unknown_apprentice_program_id_in_the_body_is_404
    """
    env = setup_env(api, rates=ONE_RATE)
    resp = api.create_worker(
        {
            "employer_contractor_id": env["contractor"]["id"],
            "worker_number": "W-003",
            "full_name": "Ada Apprentice",
            "default_classification_code": "ELEC-INSIDE-APP",
            "apprentice_program_id": NON_EXISTENT_UUID,
            "apprentice_period": 2,
        },
        env["preparer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_FOUND.value, expected_status=404)
    assert get_success_data(api.list_workers(portal_admin_headers)) == []


def test_an_unknown_reporting_portal_id_on_a_new_project_is_the_portal_404(
    api, portal_admin_headers
):
    """The determination resolves and the portal does not, so the 404 names the portal.

    PRD 2.6: "Only after every path segment resolves does the service look at foreign keys carried
    in the request body, and those are resolved in the order the body fields are declared:
    `contract_assignment_id`, then `prepared_by_staff_id`, then `superseded_submission_id`, then
    `worker_id`, then `fringe_plan_id`, then `wage_determination_id`, then `reporting_portal_id`
    ... An unresolvable body reference produces the 404 belonging to its target kind — ...
    `ERR_PORTAL_NOT_FOUND`".

    Design: Corner/errors/an_unknown_reporting_portal_id_on_a_new_project_is_404
    """
    determination = get_success_data(
        api.create_wage_determination(wage_determination_payload(), portal_admin_headers),
        expected_status=201,
    )
    build_rate(api, determination["id"])
    activated = get_success_data(
        api.activate_wage_determination(determination["id"], portal_admin_headers, {})
    )
    assert activated["status"] == "ACTIVE"

    resp = api.create_project(
        {
            "project_name": "Alameda Transit Center",
            "awarding_agency": "City of Alameda",
            "locality_code": "CA-ALAMEDA",
            "zone_code": "BASE",
            "wage_determination_id": determination["id"],
            "reporting_portal_id": NON_EXISTENT_UUID,
            "funding_source": "FEDERAL_DAVIS_BACON",
            "contract_award_date": "2026-02-01T00:00:00.000Z",
        },
        portal_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PORTAL_NOT_FOUND.value, expected_status=404)
    assert get_success_data(api.list_projects(portal_admin_headers)) == []


def test_a_determination_whose_expiry_precedes_its_effective_date_is_a_422(
    api, portal_admin_headers
):
    """The cross-field ordering rule is body shape, caught before the row can ever exist.

    PRD 3.1: "When an `expiry_date` is supplied it must fall strictly after the `effective_date`."
    PRD 2.8 rung 7: "Body shape and field-level constraints — types, ranges, string lengths, enum
    membership, array bounds, decimal scale and required-field presence — reported as
    `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/errors/a_determination_with_an_expiry_before_its_effective_date_is_422
    """
    resp = api.create_wage_determination(
        {
            "decision_number": "CA20260099",
            "modification_number": 0,
            "locality_code": "CA-ALAMEDA",
            "effective_date": "2026-06-01T00:00:00.000Z",
            "expiry_date": "2026-03-01T00:00:00.000Z",
        },
        portal_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)
    assert get_success_data(api.list_wage_determinations(portal_admin_headers)) == []


def test_an_unknown_preparer_staff_id_on_a_new_filing_is_the_staff_404(api):
    """Body FK existence (rung 4) precedes the OCC comparison, and the tier version stays put.

    PRD 2.6: "An unresolvable body reference produces the 404 belonging to its target kind —
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`". PRD 2.8 rung 4: "Body foreign-key
    existence, in body-field declaration order, as described in §2.6 — the nine body-reference 404
    identifiers."

    Design: Corner/errors/an_unknown_preparer_staff_id_on_a_new_filing_is_404
    """
    env = setup_env(api, rates=ONE_RATE)
    before = read_assignment(api, env["assignment"]["id"])["version"]

    resp = api.create_payroll_submission(
        {
            "contract_assignment_id": env["assignment"]["id"],
            "week_ending_date": WEEK,
            "prepared_by_staff_id": NON_EXISTENT_UUID,
            "expected_contract_assignment_version": before,
        },
        env["preparer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STAFF_NOT_FOUND.value, expected_status=404)
    assert read_assignment(api, env["assignment"]["id"])["version"] == before


def test_a_week_ending_on_a_friday_is_refused(api):
    """The weekly grid is anchored on Saturday midnight UTC and is enforced at creation.

    PRD 3.5: "The `week_ending_date` must be a Saturday at exactly midnight UTC —
    `00:00:00.000Z` — and any other instant, including a Saturday with a non-zero time component,
    is refused with `ERR_WEEK_ENDING_NOT_SATURDAY`."

    Design: Corner/errors/a_week_ending_on_a_friday_is_refused
    """
    env = setup_env(api, rates=ONE_RATE)
    before = read_assignment(api, env["assignment"]["id"])["version"]

    resp = api.create_payroll_submission(
        {
            "contract_assignment_id": env["assignment"]["id"],
            "week_ending_date": FRIDAY,
            "prepared_by_staff_id": env["preparer"]["id"],
            "expected_contract_assignment_version": before,
        },
        env["preparer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_WEEK_ENDING_NOT_SATURDAY.value, expected_status=422)
    assert read_assignment(api, env["assignment"]["id"])["version"] == before


def test_an_unknown_worker_id_on_a_payroll_line_is_the_worker_404(api, portal_admin_headers):
    """The path submission resolves, so the 404 must name the worker rather than the submission.

    PRD 2.6: "An unresolvable body reference produces the 404 belonging to its target kind — ...
    `ERR_WORKER_NOT_FOUND`". PRD 2.8 rung 3: "Path-segment existence, left to right, as described
    in §2.6 — the ten 404 identifiers."

    Design: Corner/errors/an_unknown_worker_id_on_a_payroll_line_is_404
    """
    env = setup_env(api, rates=ONE_RATE)
    submission = build_submission(api, env, week_ending_date=WEEK)

    resp = api.add_payroll_line(
        submission["id"],
        {
            "worker_id": NON_EXISTENT_UUID,
            "classification_code": "ELEC-INSIDE-JW",
            "straight_hours": 40.00,
            "overtime_hours": 0.00,
            "base_rate_paid_cents": 5000,
            "overtime_rate_paid_cents": 0,
            "fringe_cash_paid_cents": 2000,
        },
        env["preparer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_WORKER_NOT_FOUND.value, expected_status=404)

    unchanged = get_success_data(api.get_payroll_submission(submission["id"], portal_admin_headers))
    assert unchanged["workflow_status"] == "DRAFT"
    assert get_success_data(
        api.list_payroll_lines(
            portal_admin_headers, params={"payroll_submission_id": submission["id"]}
        )
    ) == []


def test_an_unknown_fringe_plan_id_on_a_payroll_line_is_the_plan_404(api, portal_admin_headers):
    """Naming a plan that does not exist is a 404, never a silent fall-back to zero credit.

    PRD 3.5: "optionally `fringe_plan_id`, naming the benefit plan whose hourly credit is claimed
    on this line — left null when the entire fringe obligation was discharged in cash." PRD 2.6:
    "An unresolvable body reference produces the 404 belonging to its target kind — ...
    `ERR_FRINGE_PLAN_NOT_FOUND`".

    Design: Corner/errors/an_unknown_fringe_plan_id_on_a_payroll_line_is_404
    """
    env = setup_env_with_worker(api, rates=ONE_RATE)
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
            "fringe_plan_id": NON_EXISTENT_UUID,
        },
        env["preparer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_FRINGE_PLAN_NOT_FOUND.value, expected_status=404)

    assert get_success_data(
        api.get_payroll_submission(submission["id"], portal_admin_headers)
    )["workflow_status"] == "DRAFT"
    assert get_success_data(api.list_fringe_plans(env["contractor"]["id"], portal_admin_headers)) == []
