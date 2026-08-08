"""Victim intake, case defaults, and eligibility determination (PRD §2.1, §3.2)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    assert_case,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["program_admin_headers"]
INTAKE = TEST_USERS["intake_counselor_headers"]
ADJ = TEST_USERS["adjudicator_headers"]


# --------------------------------------------------------------------------
# Corner — entities: required fields & defaults on case create
# --------------------------------------------------------------------------
def test_create_case_missing_victim_name_returns_validation(api):
    """PRD §2.9: "then the remaining business constraints, and finally field-level
    shape validation (`ERR_VALIDATION`, 400)."
    PRD §3.2: "An `IntakeCounselor` opens a matter by creating a `VictimCase` under a
    program, providing the owning `program_id`, the `victim_name`, the `incident_date`
    on which the qualifying crime occurred, the `crime_type` ... a `reported_to_le`
    boolean ... and the `filing_date` on which the compensation claim was filed."

    Design: Corner/entities/create_case_missing_required_victim_name_returns_validation
    """
    program = fx.make_program(api)
    payload = {
        "program_id": program["id"],
        "incident_date": "2026-01-01",
        "crime_type": "ASSAULT",
        "reported_to_le": True,
        "filing_date": "2026-02-01",
    }
    resp = api.create_case(payload, INTAKE)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_case_cooperation_defaults_pending(api):
    """PRD §3.2: "If `cooperation_status` is omitted it defaults to `PENDING`; the
    other permitted values are `COOPERATIVE` and `NONCOOPERATIVE`."
    PRD §3.2: "On creation the case is in `status` `DRAFT` and its computed
    `eligibility_status` is `UNDETERMINED`."

    Design: Corner/entities/create_case_cooperation_status_defaults_pending
    """
    program = fx.make_program(api)
    payload = {
        "program_id": program["id"],
        "victim_name": "Jane Roe",
        "incident_date": "2026-01-01",
        "crime_type": "ASSAULT",
        "reported_to_le": True,
        "filing_date": "2026-02-01",
    }
    data = validate_success(api.create_case(payload, INTAKE), 201)
    assert_case(data)
    assert data["cooperation_status"] == "PENDING"
    assert data["status"] == "DRAFT"


# --------------------------------------------------------------------------
# Corner — calculations & validations: eligibility gates
# --------------------------------------------------------------------------
def test_filing_deadline_past_365_days_rejected(api):
    """PRD §3.2: "counting whole days from `incident_date` to `filing_date`, the
    elapsed count must be at least 0 and at most the filing deadline of 365 days (one
    year), inclusive at the boundary, so that a filing exactly 365 days out is timely
    and a filing at 366 days is late; a late filing is rejected with
    `ERR_FILING_DEADLINE_PASSED` (HTTP 422)."

    Design: Corner/calculations/filing_deadline_past_365_days_rejected
    """
    # incident 2026-01-01, filing 2027-01-02 = 366 days > 365.
    _, case = fx.make_under_review_case(api, incident_date="2026-01-01", filing_date="2027-01-02")
    resp = api.transition_case(case["id"], {"to_status": "ELIGIBLE"}, ADJ)
    validate_error(resp, ApiErrorId.ERR_FILING_DEADLINE_PASSED.value)


def test_set_eligible_without_cooperation_returns_criteria_not_met(api):
    """PRD §3.2: "the crime must have been reported to law enforcement and the
    survivor must be cooperating — that is, `reported_to_le` is true and
    `cooperation_status` equals `COOPERATIVE`; if not, the determination is rejected
    with `ERR_ELIGIBILITY_CRITERIA_NOT_MET` (HTTP 422)."

    Design: Corner/validations/set_eligible_without_cooperation_returns_criteria_not_met
    """
    _, case = fx.make_under_review_case(api, reported_to_le=True, cooperation_status="NONCOOPERATIVE")
    resp = api.transition_case(case["id"], {"to_status": "ELIGIBLE"}, ADJ)
    validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_CRITERIA_NOT_MET.value)


# --------------------------------------------------------------------------
# Corner — RBAC: eligibility determination is Adjudicator-exclusive
# --------------------------------------------------------------------------
def test_intake_counselor_cannot_determine_eligibility(api):
    """PRD §3.2: "An `Adjudicator` then takes it `SUBMITTED → UNDER_REVIEW`, and from
    `UNDER_REVIEW` reaches one of two determinations."
    PRD §2.1: "When the headers are well-formed but the acting role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/intake_counselor_cannot_determine_eligibility
    """
    _, case = fx.make_under_review_case(api)
    resp = api.transition_case(case["id"], {"to_status": "ELIGIBLE"}, INTAKE)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
