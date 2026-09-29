"""Who may act, and in what capacity.

An anonymous read and an out-of-role write refused before the body is looked at, a
developer reaching for another developer's project, the two distinct reasons a
reviewer may be turned away from a determination, and the review chain driven end to
end by the three roles that exclusively own its steps.
"""

from test_helpers import (
    ApiErrorId,
    assertions,
    factories,
    fixtures,
    get_success_data,
    make_headers_without_user_id,
    make_nps_reviewer_headers,
    validate_error,
    validate_success,
)


def test_an_anonymous_read_and_an_out_of_role_write_are_refused_first(api):
    """Identity is checked before roles, and roles before the body is validated.

    The read carries no X-User-ID at all, so it is rejected as unauthenticated before
    anything else happens. The write is sent by a platform administrator, which holds
    no domain decision rights, and carries a recommendation value that is not in the
    enum: the role refusal wins, because authorization precedes schema validation.
    Neither request touches the application, which is still in review with its assigned
    state office reviewer and the version its submission gave it.

    PRD: "A request that omits `X-User-ID` or supplies it empty is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before the body is parsed."
    PRD: "Because authorization precedes schema validation, an unauthorized caller who also sends a malformed body still receives `ERR_UNAUTHORIZED`."
    PRD: "It holds no domain decision rights whatsoever: it can neither review, nor classify costs, nor claim credits."
    PRD: "Submission increments the application's `version` by one."

    Design: Corner/rbac/request_missing_x_user_id_header_and_wrong_role_rejected_before_body_validation
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="SINGLE_TIER", adjusted_basis_cents=60_000_000
    )
    application = fixtures.create_part_application(api, cast, project["id"], 1)
    fixtures.submit_part_application(api, cast, application["id"])

    anonymous = api.get_project(
        project["id"], make_headers_without_user_id("Developer")
    )
    out_of_role = api.shpo_recommend(
        application["id"],
        fixtures.ADMIN,
        recommendation="NOT_A_REAL_RECOMMENDATION",
    )

    validate_error(anonymous, ApiErrorId.UNAUTHENTICATED.value, 401)
    error = validate_error(out_of_role, ApiErrorId.UNAUTHORIZED.value, 403)
    assert error["error_id"] != ApiErrorId.INVALID_REQUEST.value, (
        "the role refusal must win over the malformed recommendation value"
    )
    assertions.assert_fields(
        get_success_data(
            api.get_part_application(application["id"], cast.developer_headers)
        ),
        "the application under review",
        status="SHPO_REVIEW",
        shpo_reviewer_id=cast.shpo_reviewer_id,
        version=2,
    )


def test_a_developer_cannot_apply_for_a_part_on_another_developers_project(api):
    """Ownership is compared against X-User-ID, so an outsider's write is refused.

    Two developers each hold their own building and their own project. The second
    developer applies for Part 1 on the first developer's project, quoting that
    project's current version so the concurrency check is satisfied and only ownership
    is left to refuse it. It is refused: no application row exists on the project, and
    the project is untouched at PRE_CERTIFICATION on its first version.

    PRD: "Concretely, a write against a project, a part application, a cost line item, an amendment, or a covenant of that project succeeds only when the project's `developer_id` equals `X-User-ID`; otherwise the write is refused with `ERR_UNAUTHORIZED`."
    PRD: "Ownership is checked after existence, so a developer touching another developer's project gets 403 while an unknown project id gets 404."
    PRD: "Creation increments the project's `version` by one."

    Design: Corner/rbac/developer_cannot_file_a_part_application_on_another_developers_project
    """
    owner = fixtures.seed_cast(api)
    outsider = fixtures.seed_cast(api, clock=None)
    project = fixtures.open_project(
        api, owner, structure_type="SINGLE_TIER", adjusted_basis_cents=60_000_000
    )

    response = api.create_part_application(
        outsider.developer_headers,
        **factories.part_application_payload(
            project["id"],
            1,
            project["version"],
            narrative="Attempt by an unrelated developer to apply for Part 1.",
        ),
    )

    validate_error(response, ApiErrorId.UNAUTHORIZED.value, 403)
    assertions.assert_page(
        api.list_part_applications(owner.developer_headers, project_id=project["id"]),
        total_count=0,
    )
    stored = fixtures.read_project(api, owner, project["id"])
    assertions.assert_project_state(stored, certification_status="PRE_CERTIFICATION")
    assertions.assert_fields(
        stored, "the untouched project", version=project["version"]
    )


def test_the_recommending_reviewer_cannot_also_issue_the_determination(api):
    """The identity that recommended is barred from deciding, whatever role it claims.

    The application's shpo_reviewer_id is the reviewer that recommended it, and the
    determination arrives from that very identity acting in the federal role. Inside the
    ownership band the identity-reuse check runs before the agency check, so the refusal
    is segregation of duties rather than a plain authorization failure. Nothing decides:
    the application is still in federal review with no federal reviewer stamped on it,
    the project is still uncertified and the building still unevaluated.

    PRD: "Separately, segregation of duties forbids the reviewer who recommended on an application from also deciding it: when `X-User-ID` equals the application's `shpo_reviewer_id`, the determination is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD: "Inside this band on a determination, the identity-reuse check runs **before** the agency check: a Reviewer whose id equals the application's `shpo_reviewer_id` receives `ERR_SEGREGATION_OF_DUTIES` whatever its agency, so the agency check only ever reports on a reviewer that did not recommend on this application."
    PRD: "A newly recorded property has not yet been evaluated: its `evaluation_status` is `UNEVALUATED`, its `certified_at` is null, and its `open_project_count` is zero."

    Design: Corner/rbac/same_reviewer_cannot_issue_the_nps_determination_it_recommended_on
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="SINGLE_TIER", adjusted_basis_cents=60_000_000
    )
    application = fixtures.create_part_application(api, cast, project["id"], 1)
    fixtures.submit_part_application(api, cast, application["id"])
    fixtures.shpo_recommend(api, cast, application["id"])

    response = api.nps_determination(
        application["id"],
        make_nps_reviewer_headers(cast.shpo_reviewer_id),
        determination="APPROVED",
    )

    error = validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)
    assert error["error_id"] != ApiErrorId.UNAUTHORIZED.value, (
        "the identity-reuse check reports before the agency check"
    )
    assertions.assert_fields(
        get_success_data(
            api.get_part_application(application["id"], cast.developer_headers)
        ),
        "the application awaiting its determination",
        status="NPS_REVIEW",
        nps_reviewer_id=None,
    )
    assertions.assert_project_state(
        fixtures.read_project(api, cast, project["id"]),
        certification_status="PRE_CERTIFICATION",
    )
    assertions.assert_fields(
        validate_success(api.get_property(cast.property_id, fixtures.ADMIN)),
        "the building under review",
        evaluation_status="UNEVALUATED",
    )


def test_a_state_office_reviewer_cannot_issue_the_federal_determination(api):
    """A second SHPO reviewer did not recommend here, so the agency check reports.

    The determination arrives from a reviewer whose agency is SHPO but who is not the
    one recorded on the application, so the identity-reuse check passes and the agency
    mismatch is what refuses it. It is an authorization failure rather than a
    segregation-of-duties one. The application keeps its recommending reviewer and
    still has no federal reviewer.

    PRD: "A reviewer's `agency` must match the decision being recorded — a Reviewer whose `agency` is `NPS` cannot issue an SHPO recommendation, a Reviewer whose `agency` is `SHPO` cannot issue a determination, and on an amendment concurrence the acting agency selects which branch of the concurrence fork the decision lands on."
    PRD: "Any of these mismatches yields `ERR_UNAUTHORIZED`."
    PRD: "Issuing the binding determination is exclusive to this role; it shares finding creation and amendment concurrence with `ShpoReviewer`, and it has the same read scope."

    Design: Corner/rbac/shpo_agency_reviewer_cannot_issue_the_nps_determination
    """
    cast = fixtures.seed_cast(api)
    second_state_reviewer = fixtures.create_reviewer(api, "SHPO")
    project = fixtures.open_project(
        api, cast, structure_type="SINGLE_TIER", adjusted_basis_cents=60_000_000
    )
    application = fixtures.create_part_application(api, cast, project["id"], 1)
    fixtures.submit_part_application(api, cast, application["id"])
    fixtures.shpo_recommend(api, cast, application["id"])

    response = api.nps_determination(
        application["id"],
        make_nps_reviewer_headers(second_state_reviewer["id"]),
        determination="APPROVED",
    )

    error = validate_error(response, ApiErrorId.UNAUTHORIZED.value, 403)
    assert error["error_id"] != ApiErrorId.SEGREGATION_OF_DUTIES.value, (
        "a reviewer that did not recommend here is refused on its agency"
    )
    assertions.assert_fields(
        get_success_data(
            api.get_part_application(application["id"], cast.developer_headers)
        ),
        "the application awaiting its determination",
        status="NPS_REVIEW",
        shpo_reviewer_id=cast.shpo_reviewer_id,
        nps_reviewer_id=None,
    )


def test_each_role_in_the_review_chain_performs_only_its_own_exclusive_step(api):
    """Developer drafts and submits, the state office recommends, the federal decides.

    Each step is taken by the single role that exclusively owns it, and each is
    accepted. The recommendation and the determination are both modifications rather
    than creations, so both return 200. The application ends APPROVED in its first
    review round carrying both reviewers, the project's certification dimension has
    advanced, and the building itself is certified historic.

    PRD: "Issuing the SHPO recommendation on an assigned application is exclusive to this role; it shares the raising of standards findings and the recording of a concurrence decision on an amendment, and it reads everything except the investor-side and ledger sub-resource listings."
    PRD: "Operations that modify an existing resource — including state transitions, classifications, attestations, and the logical-clock control — return `200 OK`."
    PRD: "For a Part 1 application, the first hop sets the property's `evaluation_status` to `CERTIFIED_HISTORIC` and stamps its `certified_at` from the logical clock, bumping the property's `version`."

    Design: Corner/rbac/each_review_chain_role_performs_its_own_exclusive_operation
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="SINGLE_TIER", adjusted_basis_cents=60_000_000
    )
    application = fixtures.create_part_application(api, cast, project["id"], 1)
    fixtures.submit_part_application(api, cast, application["id"])

    recommended = api.shpo_recommend(
        application["id"], cast.shpo_headers, recommendation="RECOMMEND_APPROVAL"
    )
    determined = api.nps_determination(
        application["id"], cast.nps_headers, determination="APPROVED"
    )

    validate_success(recommended, 200)
    approved = validate_success(determined, 200)
    assertions.assert_fields(
        approved,
        "the approved application",
        status="APPROVED",
        shpo_reviewer_id=cast.shpo_reviewer_id,
        nps_reviewer_id=cast.nps_reviewer_id,
        review_round=1,
    )
    assertions.assert_project_state(
        fixtures.read_project(api, cast, project["id"]),
        certification_status="PART1_CERTIFIED",
    )
    assertions.assert_fields(
        validate_success(api.get_property(cast.property_id, fixtures.ADMIN)),
        "the certified building",
        evaluation_status="CERTIFIED_HISTORIC",
    )
