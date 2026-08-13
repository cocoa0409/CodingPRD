"""Site survey schema validation, review state machine, and the anchor /
foundation readiness gates (PRD section 3.2)."""
from test_helpers import (
    CLOCK_CURED,
    CLOCK_NOT_CURED,
    ApiErrorId,
    assert_site_survey,
    create_project,
    create_site_survey_payload,
    get_project,
    set_clock,
    setup_project_mobilized,
    validate_error,
    validate_success,
)


def test_site_survey_missing_required_field_rejected(api, pm_headers, sup_headers):
    """PRD section 3.2: "Before steel can move, a `SiteSupervisor` records a
    site survey against the project, naming the parent in the payload's
    `project_id` and capturing the `survey_date`, the verified
    `anchor_bolt_count` (which must be greater than zero), the allowed
    `anchor_tolerance_mm` from the engineering specification, the worst
    actually measured deviation `anchor_measured_max_deviation_mm` (zero or
    greater), the `overhead_clearance_mm` measured along the rigging path, and
    the `foundation_pour_date` timestamp at which the foundation was poured."
    PRD section 2.6: "State and phase validity comes next
    (`ERR_INVALID_STATE`), then segregation of duties
    (`ERR_SEGREGATION_OF_DUTIES`), and only then request-schema validation —
    required fields present, enum members valid, ranges respected, and
    conditional requirements met (`ERR_VALIDATION`)."

    Design: Corner/entities/site_survey_missing_required_field_rejected
    """
    project = create_project(name="Schema Job", site_address="21 Plant Rd")
    payload = create_site_survey_payload(project_id=project["id"], anchor_bolt_count=None)
    assert "anchor_bolt_count" not in payload

    resp = api.create_site_survey(payload, sup_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)

    body = api.list_site_surveys(project["id"], pm_headers).json()
    assert body["data"] == [], "No SiteSurvey row may be created on a schema failure"


def test_labor_entry_invalid_hours_rejected(api, pm_headers, sup_headers):
    """PRD section 3.8: "Labor is reported by the `SiteSupervisor` one entry
    per worker per date, with the worker identified by `worker_ref` (their
    union card reference), a prevailing-wage `classification` of
    `MW_JOURNEYMAN`, `MW_APPRENTICE`, `MW_FOREMAN`, or `OPERATOR`, the
    `work_date`, the `hours_worked` that date (greater than zero and at most
    twenty-four), and a `shift` of `DAY` or `NIGHT`."

    Design: Corner/entities/labor_entry_invalid_hours_rejected
    """
    project = create_project(name="Hours Job", site_address="22 Plant Rd")
    resp = api.create_labor_entry(
        {
            "project_id": project["id"],
            "worker_ref": "U-9101",
            "classification": "MW_JOURNEYMAN",
            "work_date": "2026-08-08",
            "hours_worked": 25,
            "shift": "DAY",
        },
        sup_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_survey_review_from_draft_rejected(api, pm_headers, sup_headers):
    """PRD section 3.2: "A survey begins as `DRAFT`. Submission by the
    `SiteSupervisor` moves it to `SUBMITTED`, after which a `ProjectManager`
    reviews it with an `outcome` of `ACCEPTED` or `REJECTED` and an optional
    `reviewer_note` that is recorded on the survey."

    Design: Corner/state_machines/survey_review_from_draft_rejected
    """
    project = create_project(name="SM1 Job", site_address="23 Plant Rd")
    survey = validate_success(
        api.create_site_survey(
            create_site_survey_payload(project_id=project["id"]), sup_headers
        ),
        201,
    )
    assert survey["status"] == "DRAFT"

    resp = api.review_site_survey(survey["id"], {"outcome": "ACCEPTED"}, pm_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    surveys = api.list_site_surveys(project["id"], pm_headers).json()["data"]
    assert surveys[0]["status"] == "DRAFT", "Survey must remain DRAFT after a rejected review"


def test_survey_submit_after_accepted_rejected(api, pm_headers, sup_headers):
    """PRD section 3.2: "Both `ACCEPTED` and `REJECTED` are terminal; when a
    survey fails, the remedy is to record an entirely new site survey row, not
    to repair the rejected one."

    Design: Corner/state_machines/survey_submit_after_accepted_rejected
    """
    project = create_project(name="SM2 Job", site_address="24 Plant Rd")
    survey = validate_success(
        api.create_site_survey(
            create_site_survey_payload(project_id=project["id"]), sup_headers
        ),
        201,
    )
    validate_success(api.submit_site_survey(survey["id"], sup_headers))
    set_clock(CLOCK_CURED)
    accepted = validate_success(
        api.review_site_survey(survey["id"], {"outcome": "ACCEPTED"}, pm_headers)
    )
    assert accepted["status"] == "ACCEPTED"

    resp = api.submit_site_survey(survey["id"], sup_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    surveys = api.list_site_surveys(project["id"], pm_headers).json()["data"]
    assert surveys[0]["status"] == "ACCEPTED", "Survey must remain ACCEPTED"


def test_invalid_enum_outcome_rejected(api, pm_headers, sup_headers):
    """PRD section 3.2: "A survey begins as `DRAFT`. Submission by the
    `SiteSupervisor` moves it to `SUBMITTED`, after which a `ProjectManager`
    reviews it with an `outcome` of `ACCEPTED` or `REJECTED` and an optional
    `reviewer_note` that is recorded on the survey."
    PRD section 2.6: "State and phase validity comes next
    (`ERR_INVALID_STATE`), then segregation of duties
    (`ERR_SEGREGATION_OF_DUTIES`), and only then request-schema validation —
    required fields present, enum members valid, ranges respected, and
    conditional requirements met (`ERR_VALIDATION`)."

    Design: Corner/validations/invalid_enum_outcome_rejected
    """
    project = create_project(name="Enum Job", site_address="38 Plant Rd")
    survey = validate_success(
        api.create_site_survey(
            create_site_survey_payload(project_id=project["id"]), sup_headers
        ),
        201,
    )
    validate_success(api.submit_site_survey(survey["id"], sup_headers))

    resp = api.review_site_survey(survey["id"], {"outcome": "MAYBE"}, pm_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)

    surveys = api.list_site_surveys(project["id"], pm_headers).json()["data"]
    assert surveys[0]["status"] == "SUBMITTED", "Survey must remain SUBMITTED"


def test_foundation_not_cured(api, pm_headers, sup_headers):
    """PRD section 3.2: "The `foundation_cured` flag is evaluated continuously
    against the logical clock, at read time and again at review time: it
    becomes true once the current logical time has reached or passed seven full
    days after `foundation_pour_date`, so a pour that is exactly seven days old
    counts as cured."
    PRD section 3.2: "Acceptance is gated on both readiness flags: an anchor
    pattern out of tolerance is rejected with `ERR_ANCHOR_OUT_OF_TOLERANCE`,
    and a foundation poured fewer than seven days ago at review time is
    rejected with `ERR_FOUNDATION_NOT_CURED`."

    Design: Corner/validations/foundation_not_cured
    """
    project = create_project(name="Cure Job", site_address="45 Plant Rd")
    survey = validate_success(
        api.create_site_survey(
            create_site_survey_payload(project_id=project["id"]), sup_headers
        ),
        201,
    )
    validate_success(api.submit_site_survey(survey["id"], sup_headers))
    # Five days after the 2026-08-01 pour: not yet cured.
    set_clock(CLOCK_NOT_CURED)

    surveys = api.list_site_surveys(project["id"], pm_headers).json()["data"]
    assert surveys[0]["foundation_cured"] is False, (
        "foundation_cured must be false five days after the pour"
    )

    resp = api.review_site_survey(survey["id"], {"outcome": "ACCEPTED"}, pm_headers)
    validate_error(resp, ApiErrorId.ERR_FOUNDATION_NOT_CURED)

    surveys = api.list_site_surveys(project["id"], pm_headers).json()["data"]
    assert surveys[0]["status"] == "SUBMITTED", "Survey must remain SUBMITTED"


def test_anchor_out_of_tolerance(api, pm_headers, sup_headers):
    """PRD section 3.2: "The `anchor_check_passed` flag is computed at creation
    and is true when the worst measured deviation is no more than the allowed
    tolerance — a deviation exactly equal to the tolerance passes."
    PRD section 3.2: "Acceptance is gated on both readiness flags: an anchor
    pattern out of tolerance is rejected with `ERR_ANCHOR_OUT_OF_TOLERANCE`,
    and a foundation poured fewer than seven days ago at review time is
    rejected with `ERR_FOUNDATION_NOT_CURED`."

    Design: Corner/validations/anchor_out_of_tolerance
    """
    project = create_project(name="Anchor Job", site_address="46 Plant Rd")
    survey = validate_success(
        api.create_site_survey(
            create_site_survey_payload(
                project_id=project["id"],
                anchor_tolerance_mm=3.0,
                anchor_measured_max_deviation_mm=3.5,
            ),
            sup_headers,
        ),
        201,
    )
    assert_site_survey(survey)
    assert survey["anchor_check_passed"] is False, (
        "3.5 mm measured vs 3.0 mm tolerance must fail the anchor check"
    )
    validate_success(api.submit_site_survey(survey["id"], sup_headers))
    set_clock(CLOCK_CURED)  # foundation cured; only the anchor gate can fail

    resp = api.review_site_survey(survey["id"], {"outcome": "ACCEPTED"}, pm_headers)
    validate_error(resp, ApiErrorId.ERR_ANCHOR_OUT_OF_TOLERANCE)

    surveys = api.list_site_surveys(project["id"], pm_headers).json()["data"]
    assert surveys[0]["status"] == "SUBMITTED"


def test_site_survey_not_accepted_on_advance(api, pm_headers):
    """PRD section 3.2: "The mobilization-to-installation advance gate lives
    here: the project cannot enter `INSTALLING` until some survey of the
    project stands `ACCEPTED`, failing with `ERR_SITE_SURVEY_NOT_ACCEPTED`
    otherwise."

    Design: Corner/validations/site_survey_not_accepted_on_advance
    """
    ctx = setup_project_mobilized(name="No Survey Job", site_address="49 Plant Rd")
    project = ctx["project"]
    assert project["work_status"] == "MOBILIZED"

    resp = api.advance_project(project["id"], pm_headers)
    validate_error(resp, ApiErrorId.ERR_SITE_SURVEY_NOT_ACCEPTED)

    assert get_project(project["id"])["work_status"] == "MOBILIZED"
