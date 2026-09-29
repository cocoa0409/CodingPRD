"""Who may call what, whose records they may touch, and how a page is cut.

Covers the application listing's oldest-first window arithmetic and validated
limit bounds, the role-exclusive operations that no other role may borrow, and
the boundary between an unknown role, a foreign holder and the owner.
"""
from test_helpers import (
    ApiErrorId,
    create_application,
    create_guide,
    create_outfitter,
    create_prospectus,
    create_submitted_application,
    create_use_area,
    guide_payload,
    insurance_certificate_payload,
    list_noncompliance_actions,
    make_headers,
    noncompliance_action_payload,
    performance_evaluation_payload,
    read_application,
    read_guide,
    read_permit,
    read_prospectus,
    set_clock,
    setup_issued_permit,
    submit_application,
    trip_use_report_payload,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
    TEST_USERS,
    make_outfitter_representative_headers,
)

ADMIN = TEST_USERS["program_administrator_headers"]
SPECIALIST = TEST_USERS["permit_specialist_headers"]
OFFICER = TEST_USERS["authorized_officer_headers"]
BETA = {
    "legal_name": "Beta River Guides LLC",
    "ein": "410000002",
    "contact_email": "ops@beta.example",
    "prequalification_insurance_verified": True,
}


def _four_applications():
    """Four applications on one area for one outfitter, each drafted a day after
    the last so `created_at` strictly increases, with the first two submitted."""
    set_clock()
    area = create_use_area()
    outfitter = create_outfitter()
    applications = []
    for index, days in enumerate((10, 20, 30, 40)):
        set_clock(f"2027-01-0{5 + index}T00:00:00Z")
        applications.append(
            create_application(
                outfitter["id"], area["id"],
                requested_service_days=days, proposed_activity_type="FISHING",
            )
        )
    for application in applications[:2]:
        assert submit_application(application["id"], outfitter["id"])["status"] == "SUBMITTED"
    return area, outfitter, applications


def test_the_application_listing_pages_oldest_first_and_validates_its_limit():
    """PRD §2.3: "`limit` controls page size: it defaults to 10, must be at least 1, and must not
    exceed 100. `offset` controls the starting position: it defaults to 0 and must not be negative. A
    value outside those bounds is a malformed request and is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."
    PRD §2.3: "`total_count` is the number of records matching the request's filters before the
    window is applied, and `has_more` is true whenever records matching the filters remain beyond the
    current window."
    PRD §2.3: "Unless a listing endpoint states otherwise, results are ordered by `created_at`
    ascending."
    PRD §4: "| GET | `/osup/permit-applications` | Lists applications oldest first, filterable by
    outfitter, area, solicitation, type, routing decision and status. | `OutfitterRepresentative`,
    `PermitSpecialist`, `AuthorizedOfficer`, `ProgramAdministrator` |"

    Design: Corner/endpoints/application_listing_combines_filter_sort_and_offset_pagination
    """
    area, _outfitter, applications = _four_applications()
    first, second, third, fourth = applications

    rows, meta = validate_paginated(
        api_client.list_permit_applications(SPECIALIST, params={"limit": 2, "offset": 0})
    )
    assert [row["id"] for row in rows] == [first["id"], second["id"]]
    assert meta["total_count"] == 4
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    rows, meta = validate_paginated(
        api_client.list_permit_applications(SPECIALIST, params={"limit": 2, "offset": 2})
    )
    assert [row["id"] for row in rows] == [third["id"], fourth["id"]]
    assert meta["total_count"] == 4
    assert meta["has_more"] is False, "the second page completes the pool exactly"

    rows, meta = validate_paginated(
        api_client.list_permit_applications(SPECIALIST, params={"status": "SUBMITTED"})
    )
    assert [row["id"] for row in rows] == [first["id"], second["id"]]
    assert meta["total_count"] == 2, "total_count counts the filtered population, not the table"
    assert meta["limit"] == 10, "the default page size"
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api_client.list_permit_applications(
            SPECIALIST, params={"status": "DRAFT", "limit": 1}
        )
    )
    assert [row["id"] for row in rows] == [third["id"]], "the filtered order is still oldest first"
    assert meta["total_count"] == 2
    assert meta["has_more"] is True

    rows, meta = validate_paginated(
        api_client.list_permit_applications(
            SPECIALIST, params={"use_area_id": area["id"], "season_year": 2028}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False, "an empty filtered page is not an error"

    for limit in (0, 101):
        validate_error(
            api_client.list_permit_applications(SPECIALIST, params={"limit": limit}),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

    individual = read_application(third["id"])
    assert individual["requested_service_days"] == 30
    assert individual["status"] == "DRAFT"
    assert individual["proposed_activity_type"] == "FISHING"
    assert individual["created_at"] == third["created_at"]


def test_the_administrator_cannot_stand_in_for_the_operations_the_table_reserves():
    """PRD §2.1: "Once the caller is authenticated, the role is checked against the endpoint's
    authorized-role list from the table in §4; a role that does not appear there receives
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "A `ProgramAdministrator` opens use areas, drives the logical clock and the nightly
    compliance sweep, closes fee assessments, and may stand in for the specialist's and the officer's
    decision operations — but may never act as the holder: filing applications, plans, guides,
    certificates, bonds, use reports, amendments, payments, cures and appeals are closed to it."
    PRD §4: "| POST | `/osup/permit-applications/{id}/screen` | Runs the capacity screen, places the
    service-day hold and routes the application to direct award or to solicitation. |
    `PermitSpecialist` |"
    PRD §4: "| POST | `/osup/prospectuses/{id}/close-submissions` | Closes the submission window and
    scores every responsive application with the preliminary variant, writing
    `preliminary_evaluation_score` on each. | `PermitSpecialist` |"
    PRD §4: "| POST | `/osup/permits/{id}/performance-evaluations` | Records the annual performance
    evaluation for an `evaluation_year` and computes the published `rating` in six pinned steps. |
    `AuthorizedOfficer` |"
    PRD §4: "| POST | `/osup/permits/{id}/noncompliance-actions` | Issues a noncompliance action,
    deriving `points` from `severity` and screening `action_type` against it. | `AuthorizedOfficer` |"
    PRD §2.4: "A request that is rejected writes nothing at all: no field changes, no `updated_at`
    refresh and no `version` increment"

    Design: Corner/rbac/role_exclusive_operations_are_unauthorized_for_every_other_role
    """
    context = setup_issued_permit(
        application_overrides={"requested_service_days": 200},
        permit_overrides={"term_start_date": "2027-01-01", "term_end_date": "2029-12-31"},
    )
    permit_id = context["permit"]["id"]
    area_id = context["use_area"]["id"]
    outfitter_id = context["outfitter"]["id"]
    second = create_submitted_application(
        outfitter_id, area_id, requested_service_days=100, proposed_activity_type="FISHING"
    )
    prospectus = create_prospectus(area_id, context["needs_assessment"]["id"])
    assert prospectus["status"] == "OPEN"

    for headers in (OFFICER, ADMIN):
        validate_error(
            api_client.screen_permit_application(second["id"], headers),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
    validate_error(
        api_client.close_prospectus_submissions(prospectus["id"], ADMIN),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.create_performance_evaluation(
            permit_id, performance_evaluation_payload(2027, resource_protection_score=90), ADMIN
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.create_noncompliance_action(
            permit_id, noncompliance_action_payload(), SPECIALIST
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    assert read_prospectus(prospectus["id"])["status"] == "OPEN"
    _rows, meta = validate_paginated(
        api_client.list_performance_evaluations(permit_id, SPECIALIST)
    )
    assert meta["total_count"] == 0
    _rows, meta = list_noncompliance_actions(permit_id)
    assert meta["total_count"] == 0
    assert read_application(second["id"])["status"] == "SUBMITTED"

    screened = validate_success(
        api_client.screen_permit_application(second["id"], SPECIALIST)
    )
    assert screened["status"] == "DIRECT_AWARD_PENDING", (
        "the identical request the other roles were refused succeeds for the role that owns it"
    )


def test_the_program_roles_cannot_borrow_each_others_exclusive_operations():
    """PRD §2.1: "A `PermitSpecialist` may register outfitters, record prequalification, draft needs
    assessments, issue solicitations, screen applications, take an operating plan under review,
    request revisions, qualify guides, accept use reports and finalize fee assessments — but may not
    award a solicitation, deny an application, activate, suspend, reinstate or revoke a permit, or
    approve or reject a plan."
    PRD §2.1: "An `AuthorizedOfficer` publishes assessments, awards and cancels solicitations, denies
    applications, issues permits, activates, suspends, reinstates and revokes them, approves holder
    changes, approves or rejects plans, records performance evaluations, issues noncompliance actions
    and decides appeals — but may not screen an application, accept a use report or register an
    outfitter."
    PRD §4: "| POST | `/osup/use-areas` | Opens a use area for a season with its allocation ceiling,
    seasonal window, party and ratio limits and minimum liability coverage. | `ProgramAdministrator` |"
    PRD §4: "| POST | `/osup/_clock/set_current_utc` | Repositions the server's logical clock to
    `to_iso8601` and returns the resulting `current_utc`. Writes no entity rows. |
    `ProgramAdministrator` |"
    PRD §4: "| POST | `/osup/_ops/run-daily-compliance-sweep` | Runs the six-step nightly compliance
    batch against the current logical clock and returns `swept_at` with the six counters of rows
    moved. | `ProgramAdministrator` |"
    PRD §4: "| POST | `/osup/outfitters/{id}/guides` | Adds a guide to the outfitter's roster in
    `PENDING_QUALIFICATION`. | `OutfitterRepresentative` |"
    PRD §4: "| POST | `/osup/permits/{id}/acknowledge-indemnification` | The holder accepts the
    hold-harmless and indemnification clause; irreversible once set. | `OutfitterRepresentative` |"
    PRD §4: "| POST | `/osup/guides/{id}/qualify` | Qualifies a guide whose first-aid certification is
    present and unexpired. | `PermitSpecialist`, `AuthorizedOfficer` |"
    PRD §2.1: "Read access is uniform. Every retrieval endpoint in §4 is open to all four roles,
    including an `OutfitterRepresentative` reading another outfitter's records; ownership and role
    restrictions bite only on writes."
    PRD §3.1: "A `LEAD` holding `WFR` with seven completed seasons therefore carries 8 (the lesser of
    8 and 8) plus 2 (seven divided by three, floored, capped at 2), for 10."

    Design: Corner/rbac/role_exclusive_operations_are_unauthorized_for_every_other_role
    """
    context = setup_issued_permit(
        application_overrides={"requested_service_days": 200},
        permit_overrides={"term_start_date": "2027-01-01", "term_end_date": "2029-12-31"},
    )
    permit_id = context["permit"]["id"]
    outfitter_id = context["outfitter"]["id"]
    holder = make_outfitter_representative_headers(outfitter_id)
    rogue_area = {
        "area_code": "BRW-09", "name": "Rogue Draw", "total_allocated_service_days": 100,
        "season_year": 2027, "season_open_date": "2027-05-15",
        "season_close_date": "2027-09-30", "party_size_max": 8, "max_clients_per_guide": 8,
        "reserved_admin_service_days": 0, "min_liability_coverage_cents": 100_000_000,
    }

    for headers in (SPECIALIST, OFFICER):
        validate_error(
            api_client.create_use_area(dict(rogue_area), headers),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
    validate_error(
        api_client.set_clock("2027-02-01T00:00:00Z", OFFICER),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.run_daily_compliance_sweep(SPECIALIST),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.create_outfitter(dict(BETA, legal_name="Rogue Guides LLC", ein="410000099"),
                                    OFFICER),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.create_guide(
            outfitter_id,
            {
                "full_name": "Sam Kite", "qualification_level": "ASSISTANT",
                "first_aid_cert_type": "WFR", "first_aid_expires_on": "2030-06-30",
                "seasons_experience": 2,
            },
            SPECIALIST,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.acknowledge_indemnification(permit_id, OFFICER),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.activate_permit(permit_id, SPECIALIST),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    _areas, meta = validate_paginated(api_client.list_use_areas(SPECIALIST))
    assert meta["total_count"] == 1, "neither refused create opened an area"
    _guides, meta = validate_paginated(api_client.list_guides(outfitter_id, SPECIALIST))
    assert meta["total_count"] == 0

    rita = create_guide(outfitter_id, full_name="Rita Long")
    assert rita["created_at"].startswith("2027-01-05"), "the refused clock move left it in place"
    assert rita["status"] == "PENDING_QUALIFICATION"
    nora = create_guide(outfitter_id, full_name="Nora Vale")

    qualified_by_specialist = validate_success(api_client.qualify_guide(rita["id"], SPECIALIST))
    qualified_by_officer = validate_success(api_client.qualify_guide(nora["id"], OFFICER))
    for guide in (qualified_by_specialist, qualified_by_officer):
        assert guide["status"] == "QUALIFIED"
        assert guide["base_client_capacity"] == 10
    assert read_guide(rita["id"])["status"] == "QUALIFIED"

    read_by_holder = validate_success(api_client.get_permit(permit_id, holder))
    assert read_by_holder["id"] == permit_id
    assert read_by_holder["administrative_status"] == "ISSUED", "the refused activation held"
    assert read_by_holder["authorized_client_capacity_total"] == 0


def test_the_unknown_role_the_foreign_holder_and_the_owner_get_three_different_answers():
    """PRD §2.1: "A request whose `X-User-Role` header is absent or whose value is not one of the four
    role names below is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)"
    PRD §2.1: "Concretely, a write is permitted only when the caller's own outfitter id equals
    `PermitApplication.outfitter_id` for an application, `Permit.outfitter_id` for a permit,
    `Guide.outfitter_id` for a guide, and the `outfitter_id` of the permit behind an operating plan, a
    trip use report, a guide authorization, an insurance certificate, a bond or a fee assessment."
    PRD §2.1: "Any mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §2.1: "Read access is uniform. Every retrieval endpoint in §4 is open to all four roles,
    including an `OutfitterRepresentative` reading another outfitter's records; ownership and role
    restrictions bite only on writes."
    PRD §2.5: "Checks are evaluated strictly in the following order, and the **first** violated check
    produces the response; no later check is consulted."
    PRD §3.4: "The indemnification acknowledgement is a small, separate, holder-only act with
    outsized consequences: the holder accepts the hold-harmless and indemnification clause,
    `indemnification_acknowledged` flips to true, and it is irreversible once set."

    Design: Corner/rbac/foreign_holder_and_unknown_role_calls_are_unauthorized_at_the_boundary
    """
    context = setup_issued_permit(
        application_overrides={"requested_service_days": 200},
        permit_overrides={
            "term_start_date": "2027-01-01", "term_end_date": "2029-12-31",
            "indemnification_acknowledged": False,
        },
    )
    permit_id = context["permit"]["id"]
    alpine_headers = context["holder_headers"]
    beta = create_outfitter(**BETA)
    beta_headers = make_outfitter_representative_headers(beta["id"])
    stranger = make_headers("rogue-1", "UNKNOWN_ROLE")
    assert read_permit(permit_id)["indemnification_acknowledged"] is False
    version_before = read_permit(permit_id)["version"]

    validate_error(
        api_client.acknowledge_indemnification(permit_id, beta_headers),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    validate_error(
        api_client.create_insurance_certificate(
            permit_id, insurance_certificate_payload(carrier_name="Beta Mutual"), beta_headers
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    validate_error(
        api_client.create_trip_use_report(
            permit_id,
            trip_use_report_payload(
                period_start_date="2027-05-15", period_end_date="2027-06-01",
                service_days_used=5, client_count=4, gross_revenue_cents=100_000,
            ),
            beta_headers,
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    validate_error(
        api_client.create_guide(
            context["outfitter"]["id"], guide_payload(full_name="Beta Ringer"), beta_headers
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    validate_error(
        api_client.acknowledge_indemnification(permit_id, stranger),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        api_client.get_permit(permit_id, stranger),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )

    foreign_read = validate_success(api_client.get_permit(permit_id, beta_headers))
    assert foreign_read["id"] == permit_id
    assert foreign_read["outfitter_id"] == context["outfitter"]["id"]
    assert foreign_read["indemnification_acknowledged"] is False
    assert foreign_read["version"] == version_before

    acknowledged = validate_success(
        api_client.acknowledge_indemnification(permit_id, alpine_headers)
    )
    assert acknowledged["indemnification_acknowledged"] is True
    assert acknowledged["version"] == version_before + 1, (
        "the four refusals were identity decisions and moved nothing"
    )
