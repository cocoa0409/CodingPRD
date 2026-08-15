"""Project intake constraints, application round-trip reads, re-submit
rejection, and optimistic concurrency on the project version."""
from test_helpers import (
    ApiErrorId,
    assert_application,
    create_application_for,
    create_application_payload,
    create_project_for,
    create_project_payload,
    list_application_assessments,
    make_applicant_headers,
    register_applicant,
    setup_submitted_application,
    validate_error,
    validate_success,
)


def test_project_affordable_units_exceeding_dwelling_units_rejected(
    api, platform_admin_headers
):
    """PRD 3.2: "a residential project declares `dwelling_units` and may
    designate some of them as `affordable_units` (never negative, never more
    than the total unit count)".
    PRD 2.9: "Malformed request bodies — a missing required field, a type
    mismatch, or an enum value outside its declared set — are rejected with
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/project_affordable_units_exceeding_dwelling_units_rejected
    """
    applicant = register_applicant(legal_name="BadCo", contact_email="b@x.com")
    headers = make_applicant_headers(applicant["id"])
    payload = create_project_payload(
        applicant["id"],
        project_name="Bad",
        dwelling_units=10,
        affordable_units=20,
    )

    response = api.create_project(payload, headers)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_application_returns_stored_entity(api):
    """PRD 3.2: "Applications are born in `DRAFT` status, free to be revised
    until formally submitted." and the create call carries "an
    `application_type` of `REZONE`, `CONDITIONAL_USE`, or `PLANNED_DEVELOPMENT`".
    PRD 2.2: "operations that create or modify a resource will return the
    created or updated resource object in the data field."

    Design: Corner/endpoints/get_application_returns_stored_entity
    """
    applicant = register_applicant(legal_name="GetCo", contact_email="g@x.com")
    project = create_project_for(
        applicant, project_name="Get", dwelling_units=7, affordable_units=1
    )
    headers = make_applicant_headers(applicant["id"])
    application = create_application_for(
        project,
        applicant,
        application_type="PLANNED_DEVELOPMENT",
        submittal_package=["SITE_PLAN", "TRAFFIC_STUDY"],
    )

    fetched = validate_success(api.get_application(application["id"], headers))
    assert_application(fetched)
    assert fetched["application_type"] == "PLANNED_DEVELOPMENT", (
        f"application_type must round-trip, got {fetched['application_type']}"
    )
    assert fetched["status"] == "DRAFT", (
        f"unsubmitted application must be DRAFT, got {fetched['status']}"
    )
    assert fetched["submittal_package"] == ["SITE_PLAN", "TRAFFIC_STUDY"]


def test_application_submit_from_submitted_returns_invalid_state(api):
    """PRD 3.3: "When an `Applicant` submits a `DRAFT` application, three
    preconditions guard the transition to `SUBMITTED`" — submission is declared
    from `DRAFT` only.
    PRD 2.9: "The target entity sits in a state from which the requested
    transition is declared, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/application_submit_from_submitted_returns_invalid_state
    """
    ctx = setup_submitted_application()
    app_id = ctx["application"]["id"]
    assert ctx["application"]["status"] == "SUBMITTED"

    response = api.submit_application(app_id, ctx["applicant_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    assessments = list_application_assessments(app_id, ctx["applicant_headers"])
    assert len(assessments) == 1, (
        f"rejected re-submit must not spawn a second provisional assessment, "
        f"found {len(assessments)}"
    )


def test_occ_stale_project_version_on_application_create(api):
    """PRD 2.7: "Creating an application requires the request to carry
    `expected_project_version`, the client's last observed `version` of the
    parent project. If the project's current `version` has advanced since that
    observation — perhaps because another writer changed the unit counts or the
    land-use type — the create is rejected with `ERR_STALE_PROJECT_VERSION`
    (HTTP 412)."
    PRD 3.2: "Successfully adding an application is itself a modification of the
    project: the project's `version` increments by one."

    Design: Corner/cross_cutting_layers/occ_stale_project_version_on_application_create
    """
    applicant = register_applicant(legal_name="OccCo", contact_email="oc@x.com")
    headers = make_applicant_headers(applicant["id"])
    project = create_project_for(applicant, project_name="Occ")
    stale_version = project["version"]

    first = create_application_for(project, applicant, application_type="REZONE")
    assert first["status"] == "DRAFT"
    bumped = validate_success(api.get_project(project["id"], headers))
    assert bumped["version"] == stale_version + 1, (
        "adding an application must increment the project version"
    )

    payload = create_application_payload(
        project["id"],
        expected_project_version=stale_version,
        application_type="CONDITIONAL_USE",
    )
    response = api.create_application(payload, headers)
    validate_error(response, ApiErrorId.ERR_STALE_PROJECT_VERSION)
