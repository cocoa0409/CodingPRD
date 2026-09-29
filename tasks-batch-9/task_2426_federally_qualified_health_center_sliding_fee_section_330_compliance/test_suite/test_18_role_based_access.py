"""Role authorisation: exclusive writes, the shared read, and the two identity checks."""

from test_helpers import (
    ADMIN,
    OFFICER,
    PROJECT_OFFICER,
    TEST_USERS,
    VERIFIER,
    ApiErrorId,
    api_client,
    create_corrective_action_plan_payload,
    create_health_center_payload,
    make_board_chair_headers,
    make_eligibility_verifier_headers,
    make_patient_services_rep_headers,
    refresh_finding,
    refresh_health_center,
    refresh_patient,
    refresh_scope_change_request,
    setup_boot_core,
    setup_draft_scope_change_request,
    setup_income_verification,
    setup_open_finding,
    setup_patient,
    setup_proposed_site,
    submit_scope_change_request,
    validate_error,
    validate_paginated,
    validate_success,
    verify_income_verification_payload,
)


def test_a_billing_specialist_cannot_register_a_grantee():
    """A complete, valid, well-formed request still fails on the endpoint's role list.

    PRD 2.1: "If the role is recognised but is not among the roles authorised for the
    endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD 3.1: "A `PlatformAdmin` brings a Section 330 grantee onto the platform by
    registering a **health center** with its `legal_name`, its HRSA `grant_number`, its
    prospective payment system base encounter rate `pps_base_rate_cents`, and its
    per-encounter Medicare ceiling `medicare_upper_limit_cents`."

    Design: Corner/rbac/billing_specialist_cannot_create_a_health_center_unauthorized
    """
    validate_error(
        api_client.create_health_center(
            create_health_center_payload(
                legal_name="Unauthorized Health",
                grant_number="H80CS00998",
                pps_base_rate_cents=20000,
                medicare_upper_limit_cents=15000,
            ),
            TEST_USERS["billing_specialist_headers"],
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    _, meta = validate_paginated(api_client.list_health_centers(ADMIN))
    assert meta["total_count"] == 0, (
        "the refused registration created no grantee row"
    )


def test_every_declared_role_reads_the_same_grantee_record():
    """The duty segregation restricts writes; the grantee read is shared by all seven.

    PRD 4: "| GET | `/health-centers/{id}` | Reads one grantee including every derived
    counter and posture. | `PlatformAdmin`, `ComplianceOfficer`, `BoardChair`,
    `EligibilityVerifier`, `PatientServicesRep`, `BillingSpecialist`, `ProjectOfficer` |"

    Design: Corner/rbac/all_seven_roles_share_the_health_center_read_endpoint
    """
    ctx = setup_boot_core()
    readers = {
        "PlatformAdmin": TEST_USERS["platform_admin_headers"],
        "ComplianceOfficer": TEST_USERS["compliance_officer_headers"],
        "BoardChair": make_board_chair_headers(ctx["chair_id"]),
        "EligibilityVerifier": TEST_USERS["eligibility_verifier_headers"],
        "PatientServicesRep": TEST_USERS["patient_services_rep_headers"],
        "BillingSpecialist": TEST_USERS["billing_specialist_headers"],
        "ProjectOfficer": TEST_USERS["project_officer_headers"],
    }

    for role, headers in readers.items():
        seen = validate_success(
            api_client.get_health_center(ctx["health_center_id"], headers)
        )
        assert seen["id"] == ctx["health_center_id"]
        assert seen["version"] == 5, (
            f"{role} reads the same five-mutation row, got version {seen['version']}"
        )

    assert refresh_health_center(ctx["health_center_id"])["version"] == 5, (
        "seven reads mutated nothing"
    )


def test_the_operator_who_filed_the_documentation_cannot_approve_it():
    """The comparison is against the recorded identifier, not against the acting role.

    PRD 2.1: "Segregation of duties is enforced by comparing the acting `X-User-ID`
    against the identity already recorded on the row being adjudicated. Deciding a
    change-in-scope request compares against its `prepared_by_user_id`; adjudicating an
    income verification compares against its `submitted_by_user_id`; deciding an
    inability-to-pay waiver compares against its `requested_by_user_id`; adjudicating a
    corrective action plan compares against its `prepared_by_user_id`. If the acting
    identifier is equal to the recorded one, the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

    PRD 3.4: "Either way the acting verifier must not be the operator recorded in
    `submitted_by_user_id`, on pain of `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/submitter_cannot_verify_the_income_verification_they_filed
    """
    setup_boot_core()
    patient = setup_patient(mrn="MRN-C01", full_name="Val Osei", household_size=1)
    verification = setup_income_verification(
        patient,
        declared_annual_income_cents=1000000,
        household_size=1,
        documentation_type="TAX_RETURN",
        effective_date="2026-03-01T00:00:00Z",
        headers=make_patient_services_rep_headers("dual-1"),
    )
    assert verification["submitted_by_user_id"] == "dual-1"

    validate_error(
        api_client.verify_income_verification(
            verification["id"],
            verify_income_verification_payload("VERIFY"),
            make_eligibility_verifier_headers("dual-1"),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        409,
    )

    verified = validate_success(
        api_client.verify_income_verification(
            verification["id"], verify_income_verification_payload("VERIFY"), VERIFIER
        )
    )
    assert verified["status"] == "VERIFIED", (
        "a different operator in the same role completes the identical call"
    )
    assert verified["verified_by_user_id"] == "ev-1"
    assert refresh_patient(patient["id"])["sliding_fee_status"] == "VERIFIED"


def test_a_chair_holding_no_seat_cannot_take_a_request_under_review():
    """The role is on the endpoint's list, so the refusal comes from the entity check.

    PRD 2.1: "Any board-business operation on a grantee therefore compares the acting
    `X-User-ID` against the `BoardMember` rows of that grantee: the acting chair must be
    a `BoardMember` whose `health_center_id` is the grantee in question and whose
    `status` is `SEATED`. A chair that holds no seated seat on that grantee's board is
    rejected with `ERR_NOT_SEATED_BOARD_MEMBER` (HTTP 403). This check guards three
    operations: taking a change-in-scope request under review, deciding a
    change-in-scope request, and adopting a fee schedule."

    Design: Corner/rbac/board_chair_who_is_not_a_seated_member_is_forbidden
    """
    ctx = setup_boot_core()
    annex = setup_proposed_site(
        ctx,
        site_name="Corner Annex Clinic",
        address_line="2 Corner Ave",
        weekly_service_hours=20,
    )
    request = setup_draft_scope_change_request(
        ctx,
        request_type="ADD_SITE",
        target_site_id=annex["id"],
        justification="Annex clinic opens to absorb overflow primary-care demand",
    )
    submit_scope_change_request(request, headers=OFFICER)

    validate_error(
        api_client.begin_review_scope_change_request(
            request["id"],
            make_board_chair_headers("00000000-0000-4000-8000-0000000000ff"),
        ),
        ApiErrorId.ERR_NOT_SEATED_BOARD_MEMBER.value,
        403,
    )

    unmoved = refresh_scope_change_request(request["id"])
    assert unmoved["status"] == "SUBMITTED"
    assert unmoved["reviewed_by_user_id"] is None, (
        "the impostor was never recorded as the reviewing chair"
    )

    under_review = validate_success(
        api_client.begin_review_scope_change_request(
            request["id"], make_board_chair_headers(ctx["chair_id"])
        )
    )
    assert under_review["status"] == "UNDER_REVIEW", (
        "the seated chair's identical call succeeds"
    )
    assert under_review["reviewed_by_user_id"] == ctx["chair_id"]


def test_the_officer_who_adjudicates_plans_may_not_prepare_one():
    """The findings workflow is split, so preparation is closed to the awarding agency.

    PRD 2.1: "**`ComplianceOfficer`** — grantee-side Section 330 compliance staff.
    Prepares change-in-scope requests, drafts fee schedules and their tier ladders, seats
    and resigns board members, records annual reviews, decides inability-to-pay waivers,
    and prepares corrective action plans and uniform data system reports."

    PRD 2.1: "**`ProjectOfficer`** — awarding-agency project officer. Issues operational
    site visit findings, suspends and reinstates sites, and adjudicates corrective action
    plans and uniform data system reports."

    Design: Corner/rbac/project_officer_cannot_prepare_a_corrective_action_plan_unauthorized
    """
    ctx = setup_boot_core()
    finding = setup_open_finding(
        ctx,
        requirement_code="REQ_BOARD_AUTHORITY_19",
        severity="CONDITION",
        cap_due_days=30,
        service_site_id=ctx["site_id"],
        finding_summary="Governing board lacks patient-majority composition",
    )

    validate_error(
        api_client.create_corrective_action_plan(
            finding["id"],
            create_corrective_action_plan_payload(
                narrative="Officer-authored plan",
                milestone_count=2,
                target_completion_date="2026-08-20T00:00:00Z",
            ),
            PROJECT_OFFICER,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    _, meta = validate_paginated(
        api_client.list_finding_corrective_action_plans(finding["id"], PROJECT_OFFICER)
    )
    assert meta["total_count"] == 0, "no plan was drafted"
    assert refresh_finding(finding["id"])["status"] == "OPEN"
