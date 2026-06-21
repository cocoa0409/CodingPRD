"""Entity CRUD: creation, defaults, NOT_FOUND, computed fields, immutability of feedback log."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    TEST_USERS, NON_EXISTENT_UUID,
    create_department_payload, create_candidate_payload,
    create_department, setup_approved_req_with_screened_app,
    schedule_interview, submit_interview_feedback,
    set_clock,
)


# =========================================================================
# Instance: department_create_minimal_returns_201_with_zero_committed
# =========================================================================

def test_department_create_minimal_returns_201_with_zero_committed(api,
                                                                   platform_admin_headers):
    """PRD §3.1: "A `PlatformAdmin` opens the lifecycle by registering a
    department. The department record carries a human-readable `name`, a
    `cost_center_code` that must be unique across departments, and a
    `hiring_budget_cents` that is floored at zero. The computed
    `committed_offer_cents` is read alongside the stored fields and starts
    at zero before any offers exist."

    Design: Corner/entities/department_create_minimal_returns_201_with_zero_committed
    """
    payload = create_department_payload(
        name="Sales",
        cost_center_code="SLS-001-MIN",
        hiring_budget_cents=50_000_000,
    )
    res = api_client.create_department(payload, platform_admin_headers)
    dept = validate_success(res, 201)
    assert dept["committed_offer_cents"] == 0
    assert dept["version"] == 1


# =========================================================================
# Instance: candidate_create_with_defaults_eeo_declined
# =========================================================================

def test_candidate_create_with_defaults_eeo_declined(api, recruiter_headers):
    """PRD §3.3: "The candidate may voluntarily self-identify four EEO/OFCCP
    attributes: `eeo_ethnicity` (one of `WHITE`, `BLACK`, `HISPANIC`, `ASIAN`,
    `NATIVE`, `PACIFIC`, `TWO_OR_MORE`, or `DECLINED`, defaulting to
    `DECLINED`), `eeo_gender` (one of `FEMALE`, `MALE`, `NONBINARY`, or
    `DECLINED`, defaulting to `DECLINED`), `eeo_veteran` (boolean,
    defaulting to false), and `eeo_disability` (boolean, defaulting to
    false)."

    Design: Corner/entities/candidate_create_with_defaults_eeo_declined
    """
    payload = create_candidate_payload(full_name="Default Cand",
                                       email="def_unique@example.com",
                                       source_channel="DIRECT")
    # Strip any EEO fields that the factory might have introduced via overrides.
    for k in ("eeo_ethnicity", "eeo_gender", "eeo_veteran", "eeo_disability"):
        payload.pop(k, None)
    res = api_client.create_candidate(payload, recruiter_headers)
    cand = validate_success(res, 201)
    assert cand["eeo_ethnicity"] == "DECLINED"
    assert cand["eeo_gender"] == "DECLINED"
    assert cand["eeo_veteran"] is False
    assert cand["eeo_disability"] is False


# =========================================================================
# Instance: requisition_get_nonexistent_returns_not_found
# =========================================================================

def test_requisition_get_nonexistent_returns_not_found(api, recruiter_headers):
    """PRD §2.5: "A request to read a single resource whose `{id}` does not
    exist is rejected with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/requisition_get_nonexistent_returns_not_found
    """
    res = api_client.get_requisition(NON_EXISTENT_UUID, recruiter_headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# =========================================================================
# Instance: application_create_with_unknown_candidate_returns_fk_not_found
# =========================================================================

def test_application_create_with_unknown_candidate_returns_fk_not_found(
        api, recruiter_headers, hiring_manager_headers):
    """PRD §2.5: "When a body payload supplies a foreign-key identifier —
    `department_id`, `candidate_id`, `requisition_id`, `application_id`,
    `offer_id`, or `interview_id` — and the referenced row does not exist,
    the request is rejected with `ERR_FK_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/application_create_with_unknown_candidate_returns_fk_not_found
    """
    dept = create_department()
    from test_helpers import create_approved_requisition
    _, req = create_approved_requisition(department_id=dept["id"])
    payload = {"candidate_id": NON_EXISTENT_UUID, "requisition_id": req["id"]}
    res = api_client.create_application(payload, recruiter_headers)
    validate_error(res, "ERR_FK_NOT_FOUND", expected_status=404)


# =========================================================================
# Instance: department_committed_offer_cents_recomputes_on_offer_create
# =========================================================================

def test_department_committed_offer_cents_recomputes_on_offer_create(
        api, platform_admin_headers, recruiter_headers):
    """PRD §2.9: "Creating an offer adds its `base_salary_cents` to
    `committed_offer_cents`; rejecting, declining, or revoking an offer
    subtracts it."
    PRD §2.9: "The denormalised aggregate `committed_offer_cents` on each
    department is the sum of `base_salary_cents` across all offers on
    requisitions belonging to that department whose `status` is one of
    `PENDING_APPROVAL`, `APPROVED`, `EXTENDED`, or `ACCEPTED`."

    Design: Corner/entities/department_committed_offer_cents_recomputes_on_offer_create
    """
    from test_helpers import create_offer
    dept, req, cand, app = setup_approved_req_with_screened_app(
        req_overrides={"base_salary_max_cents": 15_000_000},
    )
    create_offer(app["id"], base_salary_cents=11_000_000)
    after = get_success_data(api_client.get_department(dept["id"], platform_admin_headers))
    assert after["committed_offer_cents"] == 11_000_000


# =========================================================================
# Instance: interview_feedback_is_immutable_log_no_version_field
# =========================================================================

def test_interview_feedback_is_immutable_log_no_version_field(api):
    """PRD §2.4: "The InterviewFeedback resource is a write-once log row and
    carries only `id` and `created_at`; it has no `updated_at` and no
    `version`."

    Design: Corner/entities/interview_feedback_is_immutable_log_no_version_field
    """
    set_clock("2027-02-01T00:00:00Z")
    dept, req, cand, app = setup_approved_req_with_screened_app()
    intv = schedule_interview(
        app["id"], panel_user_ids=["emp_panel_imm"],
        scheduled_at="2027-02-02T10:00:00Z", duration_minutes=60,
    )
    fb = submit_interview_feedback(intv["id"], "emp_panel_imm", score=4,
                                   comments="fine")
    # Mandatory fields present per PRD §2.4.
    assert "id" in fb and fb["id"]
    assert "created_at" in fb and fb["created_at"]
    # PRD §2.4 specifies these fields are NOT on InterviewFeedback. A faithful
    # implementer is told not to emit them; their absence on the response is the
    # PRD-pinned outcome.
    assert "updated_at" not in fb, \
        f"InterviewFeedback must not carry updated_at per PRD §2.4, got {fb!r}"
    assert "version" not in fb, \
        f"InterviewFeedback must not carry version per PRD §2.4, got {fb!r}"
