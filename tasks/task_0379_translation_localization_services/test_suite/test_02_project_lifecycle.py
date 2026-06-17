"""Project state-machine transitions and their preconditions.

Covers corner-design instances under section `state_machines`.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_client, create_rate_card, create_project_payload,
    make_client_headers,
    setup_issued_invoice, current_project_version,
)

PM = TEST_USERS["pm_headers"]
AR = TEST_USERS["ar_headers"]


def _draft_project_with_job(bands=None):
    client = create_client()
    rate_card = create_rate_card()
    project = validate_success(api_create_project(client, rate_card), 201)
    return client, rate_card, project


def api_create_project(client, rate_card, name="P1"):
    from test_helpers import api_client
    return api_client.create_project(
        create_project_payload(client["id"], rate_card["id"], name=name), PM)


def test_approve_project_from_draft_returns_invalid_state(api):
    """PRD §3.4: "Once a project is `QUOTED`, the buyer reviews and approves it,
    advancing it from `QUOTED` to `APPROVED`."
    PRD §2.6: "(5) the state check that the target resource is in a state from which
    the requested transition is allowed, which fails with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/approve_project_from_draft_returns_invalid_state
    """
    client = create_client()
    rate_card = create_rate_card()
    project = validate_success(api_create_project(client, rate_card), 201)
    resp = api.approve_project(project["id"], make_client_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_quote_project_with_no_jobs_returns_no_jobs(api):
    """PRD §3.3: "Two preconditions guard this: the project must have at least one job,
    otherwise the request is rejected with `ERR_NO_JOBS`".

    Design: Corner/state_machines/quote_project_with_no_jobs_returns_no_jobs
    """
    client = create_client()
    rate_card = create_rate_card()
    project = validate_success(api_create_project(client, rate_card), 201)
    resp = api.quote_project(project["id"], PM)
    validate_error(resp, ApiErrorId.ERR_NO_JOBS.value, 409)


def test_cancel_terminal_project_returns_invalid_state(api):
    """PRD §3.11: "A `ProjectManager` may cancel a project, moving it to `CANCELLED`,
    the project's only terminal state."
    PRD §2.6: "(5) the state check that the target resource is in a state from which
    the requested transition is allowed, which fails with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/cancel_terminal_project_returns_invalid_state
    """
    client = create_client()
    rate_card = create_rate_card()
    project = validate_success(api_create_project(client, rate_card), 201)
    validate_success(api.cancel_project(project["id"], PM), 200)
    resp = api.cancel_project(project["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_add_job_to_quoted_project_reopens_to_draft(api):
    """PRD §3.2: "Adding a job to a project that is already in `QUOTED` re-opens the
    estimate: the project's `quoted_total_cents` is reset to null and the project moves
    from `QUOTED` back to `DRAFT`, because the previously computed quote no longer
    reflects the work."

    Design: Corner/state_machines/add_job_to_quoted_project_reopens_to_draft
    """
    client = create_client()
    rate_card = create_rate_card()
    project = validate_success(api_create_project(client, rate_card), 201)
    api.create_job(project["id"], {"filename": "a.docx",
                                   "quoted_no_match_words": 1000}, PM)
    quoted = validate_success(api.quote_project(project["id"], PM), 200)
    assert quoted["status"] == "QUOTED"
    api.create_job(project["id"], {"filename": "b.docx",
                                   "quoted_no_match_words": 500}, PM)
    reopened = validate_success(api.get_project(project["id"], PM), 200)
    assert reopened["status"] == "DRAFT", f"got {reopened['status']}"
    assert reopened["quoted_total_cents"] is None, f"got {reopened['quoted_total_cents']}"


# NOTE: A test asserting ERR_PROJECT_HAS_INVOICE on cancel was removed here.
# PRD §3.11 blocks cancellation with ERR_PROJECT_HAS_INVOICE only "Once the project is
# APPROVED or IN_PRODUCTION" and an ISSUED/PAID invoice exists. But PRD §3.8 (line 174)
# states issuing an invoice atomically bubbles the project DELIVERED -> INVOICED, and
# issuing requires the project be DELIVERED. There is therefore no PRD-faithful path to a
# project in APPROVED/IN_PRODUCTION that also has an ISSUED/PAID invoice: the
# ERR_PROJECT_HAS_INVOICE source-state combination is structurally unreachable. Any
# setup that issues an invoice leaves the project INVOICED, from which cancel is not an
# allowed transition, so a faithful implementation correctly returns ERR_INVALID_STATE
# (priority-5 state check) — never ERR_PROJECT_HAS_INVOICE. Unique-derivability fails.
