"""Role boundaries: identity resolution, exclusive operations, project-scoped parties and segregation of duties."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    U_AGENCY,
    U_LICENSEE_A,
    U_LICENSEE_REPORT,
    U_NGO,
    U_STATE_CERTIFIER,
    api_client,
    assert_ledger_matches,
    assert_postures,
    certify_obligation,
    comment_payload,
    file_pad,
    headers_without_user_id,
    make_agency_reviewer_headers,
    make_licensee_headers,
    make_stakeholder_headers,
    make_state_certifier_headers,
    new_measure,
    new_project,
    new_study_plan,
    obligation_of_type,
    project_payload,
    read_measure,
    read_obligation,
    read_project,
    read_study_plan,
    register_party,
    request_certification,
    schedule_obligation,
    set_clock,
    setup_agency_party,
    setup_licensed_project,
    setup_plan_under_agency_review,
    validate_error,
    validate_paginated,
    validate_success,
)

REGULATOR_HEADERS = TEST_USERS["regulator_headers"]
LICENSEE_HEADERS = make_licensee_headers(U_LICENSEE_A)
AGENCY_HEADERS = make_agency_reviewer_headers(U_AGENCY)
STATE_CERTIFIER_HEADERS = TEST_USERS["state_certifier_headers"]
MID_SIZED_PROJECT = dict(
    installed_capacity_mw=12.0,
    base_annual_generation_mwh=250000,
    license_expiration_date="2035-06-30",
)
NGO_PARTY = dict(
    party_name="River Alliance",
    party_type="NGO",
    vote_weight=1,
    contact_user_id=U_NGO,
)
AERATION_WEIR = dict(
    measure_name="Aeration weir",
    resource_category="WATER_QUALITY",
    source="LICENSEE_PROPOSED",
    capital_cost_usd=600000.00,
    annual_om_cost_usd=20000.00,
    construction_start_year=2026,
    implementation_months=6,
    flow_release_cfs=40,
    gross_head_ft=60,
    release_days=120,
)


class TestIdentityResolution:
    def test_an_absent_header_and_an_unbacked_reviewer_are_both_unauthorized(self):
        """Identity is settled before permission, so neither caller reaches a role check.

        PRD §2.1: "When `X-User-ID` is absent or names no known user, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 401); this identification requirement applies to every endpoint in the system except the two logical-clock endpoints described in §2.4."
        PRD §2.1: "When `X-User-Role` is `AgencyReviewer`, `X-User-ID` is the `id` of the acting `SettlementParty`, resolved through that party's `contact_user_id`, and the backing party must have `party_type` equal to `AGENCY`."

        Design: Corner/rbac/unknown_and_missing_user_identity_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        project = new_project(
            license_number="P-9051", project_name="Identity Reach", **MID_SIZED_PROJECT
        )
        file_pad(project["id"])
        plan = new_study_plan(project["id"])

        anonymous_read = api_client.get_project(
            project["id"], headers_without_user_id("Licensee")
        )
        ghost_comment = api_client.create_comment(
            comment_payload(
                plan["id"],
                NON_EXISTENT_UUID,
                resource_category="RECREATION",
                comment_text="ghost comment",
            ),
            make_agency_reviewer_headers("u_ghost"),
        )

        validate_error(anonymous_read, "ERR_UNAUTHORIZED", 401)
        validate_error(ghost_comment, "ERR_UNAUTHORIZED", 401)
        _comments, meta = validate_paginated(
            api_client.list_comments(REGULATOR_HEADERS, params={"limit": 100})
        )
        assert meta["total_count"] == 0
        assert read_study_plan(plan["id"])["open_comment_count"] == 0


class TestRoleExclusiveOperations:
    def _plan_awaiting_a_determination_with_a_pending_certification(self):
        ctx = setup_plan_under_agency_review(
            study_overrides=dict(
                resource_category="RECREATION", study_title="Recreation use survey"
            ),
            site_overrides=dict(site_code="S1", river_mile=1.0),
            license_number="P-9052",
            project_name="Role Reach",
            **MID_SIZED_PROJECT,
        )
        project_id = ctx["project"]["id"]
        ctx["agency_party"] = setup_agency_party(project_id)
        ctx["ngo_party"] = register_party(project_id, **NGO_PARTY)
        ctx["wqc"] = request_certification(project_id)
        assert ctx["plan"]["status"] == "UNDER_AGENCY_REVIEW"
        return ctx

    def test_the_registration_and_filing_desks_never_swap_seats(self):
        """The licensee cannot register a project and the regulator cannot file for the licensee.

        PRD §2.1: "The `Regulator` owns project registration and amendment, party registration, environmental review, deficiency notices, order issuance and the compliance sweep, and may not file anything on the licensee's behalf, make agency study determinations, or sign settlements."
        PRD §2.1: "When the acting role is not among the roles the target endpoint permits, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/role_exclusive_operations_across_roles_rejected
        """
        ctx = self._plan_awaiting_a_determination_with_a_pending_certification()

        licensee_registers = api_client.create_project(
            project_payload(
                license_number="P-9052-B",
                project_name="Licensee Registers Itself",
                installed_capacity_mw=5.0,
                base_annual_generation_mwh=20000,
                license_expiration_date="2035-06-30",
            ),
            LICENSEE_HEADERS,
        )
        regulator_files_the_pad = api_client.file_pre_application_document(
            ctx["project"]["id"],
            {"filing_note": "regulator files for the licensee"},
            REGULATOR_HEADERS,
        )

        validate_error(licensee_registers, "ERR_ROLE_NOT_PERMITTED", 403)
        validate_error(regulator_files_the_pad, "ERR_ROLE_NOT_PERMITTED", 403)
        _projects, meta = validate_paginated(
            api_client.list_projects(REGULATOR_HEADERS, params={"limit": 100})
        )
        assert meta["total_count"] == 1

    def test_agency_determinations_and_state_decisions_stay_with_their_owners(self):
        """Three other roles reach for the determination and the decision, and all three miss.

        PRD §2.1: "An `AgencyReviewer` alone makes study-plan determinations and study review decisions, and shares comment filing and settlement signing with `Stakeholder`; a study-plan determination additionally requires the backing party's `has_conditioning_authority` to be true, and an `AgencyReviewer` whose party lacks that authority receives `ERR_ROLE_NOT_PERMITTED`."
        PRD §2.1: "The `StateCertifier` holds exactly one authority — the water-quality decision — and may not request a certification, create measures, or touch applications, orders or obligations."

        Design: Corner/rbac/role_exclusive_operations_across_roles_rejected
        """
        ctx = self._plan_awaiting_a_determination_with_a_pending_certification()
        plan_id = ctx["plan"]["id"]

        certifier_determines = api_client.decide_study_plan(
            plan_id, {"determination": "APPROVE"}, STATE_CERTIFIER_HEADERS
        )
        stakeholder_determines = api_client.decide_study_plan(
            plan_id, {"determination": "APPROVE"}, make_stakeholder_headers(U_NGO)
        )
        licensee_decides_its_own_certification = (
            api_client.decide_water_quality_certification(
                ctx["wqc"]["id"],
                {
                    "decision": "DENY",
                    "denial_reason": "licensee decides its own certification",
                },
                LICENSEE_HEADERS,
            )
        )

        validate_error(certifier_determines, "ERR_ROLE_NOT_PERMITTED", 403)
        validate_error(stakeholder_determines, "ERR_ROLE_NOT_PERMITTED", 403)
        validate_error(
            licensee_decides_its_own_certification, "ERR_ROLE_NOT_PERMITTED", 403
        )
        assert read_study_plan(plan_id)["status"] == "UNDER_AGENCY_REVIEW"
        wqc = validate_success(
            api_client.get_water_quality_certification(
                ctx["wqc"]["id"], REGULATOR_HEADERS
            )
        )
        assert wqc["status"] == "REQUESTED"
        assert wqc["decided_at"] is None


class TestProjectScopedPartyAccess:
    def _two_projects_with_the_agency_registered_on_only_one(self):
        set_clock("2026-08-01T00:00:00Z")
        home = new_project(
            license_number="P-9053-A",
            project_name="Party Home Reach",
            **MID_SIZED_PROJECT,
        )
        foreign = new_project(
            license_number="P-9053-B", project_name="Foreign Reach", **MID_SIZED_PROJECT
        )
        home_party = setup_agency_party(home["id"])
        file_pad(foreign["id"])
        foreign_plan = new_study_plan(foreign["id"], plan_title="Plan B")
        return {
            "home": home,
            "home_party": home_party,
            "foreign": foreign,
            "foreign_plan": foreign_plan,
        }

    def test_a_party_registered_elsewhere_is_a_stranger_on_this_project(self):
        """The comment is refused as unpermitted rather than not found, and no counter moves.

        PRD §2.1: "For `AgencyReviewer` and `Stakeholder` there is a second, project-scoped access rule: the acting user must resolve to a `SettlementParty` registered on the same project as the target entity."
        PRD §2.1: "A party of a different project is treated as not permitted and receives `ERR_ROLE_NOT_PERMITTED` (HTTP 403), not a not-found error."

        Design: Corner/rbac/agency_reviewer_of_another_project_cannot_comment
        """
        ctx = self._two_projects_with_the_agency_registered_on_only_one()

        foreign_comment = api_client.create_comment(
            comment_payload(
                ctx["foreign_plan"]["id"],
                ctx["home_party"]["id"],
                resource_category="FISH_PASSAGE",
                comment_text="comment from a foreign party",
                is_mandatory_condition=True,
            ),
            AGENCY_HEADERS,
        )

        validate_error(foreign_comment, "ERR_ROLE_NOT_PERMITTED", 403)
        foreign_project = read_project(ctx["foreign"]["id"])
        assert foreign_project["unresolved_mandatory_comment_count"] == 0
        assert_postures(foreign_project, regulatory_posture="OPEN")
        assert read_study_plan(ctx["foreign_plan"]["id"])["open_comment_count"] == 0

    def test_registering_the_same_agency_there_admits_the_identical_comment(self):
        """One extra registration turns the stranger into a conditioning party of this project.

        PRD §3.3: "The payload also admits an `is_mandatory_condition` flag, but the stored value is not the client's: the server sets `is_mandatory_condition` to true exactly when the authoring party's `has_conditioning_authority` is true at the moment of filing, and to false otherwise, whatever the request said."
        PRD §3.3: "Filing increments the plan's `open_comment_count` and, for a mandatory comment, also the plan's `unresolved_mandatory_comment_count`, together with the plan's `version`; the project's `unresolved_mandatory_comment_count` and then its `regulatory_posture` are recomputed, so the first mandatory comment on a project takes it from `OPEN` to `RESTRICTED`."

        Design: Corner/rbac/agency_reviewer_of_another_project_cannot_comment
        """
        ctx = self._two_projects_with_the_agency_registered_on_only_one()
        foreign_plan_id = ctx["foreign_plan"]["id"]
        validate_error(
            api_client.create_comment(
                comment_payload(
                    foreign_plan_id,
                    ctx["home_party"]["id"],
                    resource_category="FISH_PASSAGE",
                    comment_text="comment from a foreign party",
                    is_mandatory_condition=True,
                ),
                AGENCY_HEADERS,
            ),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )

        local_party = setup_agency_party(ctx["foreign"]["id"])
        comment = validate_success(
            api_client.create_comment(
                comment_payload(
                    foreign_plan_id,
                    local_party["id"],
                    resource_category="FISH_PASSAGE",
                    comment_text="comment from the registered party",
                    is_mandatory_condition=True,
                ),
                AGENCY_HEADERS,
            ),
            201,
        )

        assert comment["is_mandatory_condition"] is True
        assert comment["resolution_status"] == "OPEN"
        plan = read_study_plan(foreign_plan_id)
        assert plan["open_comment_count"] == 1
        assert plan["unresolved_mandatory_comment_count"] == 1
        foreign_project = read_project(ctx["foreign"]["id"])
        assert foreign_project["unresolved_mandatory_comment_count"] == 1
        assert_postures(foreign_project, regulatory_posture="RESTRICTED")


class TestFourEyesOnTheDefinitiveEstimate:
    def test_the_creating_user_may_not_sign_off_its_own_estimate(self):
        """One licensee user prices what another proposed, and the variant switch moves both paths.

        PRD §3.7: "Switching a measure to the definitive variant is a distinct operation, restricted to the `Licensee` and gated by segregation of duties: the acting `X-User-ID` may not equal the measure's `created_by_user_id`, and an attempt by the creating user is rejected with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.7: "The operation flips `cost_estimate_variant` from `PRELIMINARY` to `DEFINITIVE`, stores `definitive_estimate_by_user_id` from the acting user, and re-runs all six derived figures under the definitive variant."

        Design: Corner/rbac/same_user_cannot_price_the_measure_it_created
        """
        set_clock("2026-08-01T00:00:00Z")
        project = new_project(
            license_number="P-9054", project_name="Four Eyes Reach", **MID_SIZED_PROJECT
        )
        filed = file_pad(project["id"])
        assert filed["pad_year"] == 2026
        measure = new_measure(project["id"], user_id=U_LICENSEE_A, **AERATION_WEIR)
        assert measure["status"] == "INCLUDED"
        assert measure["cost_estimate_variant"] == "PRELIMINARY"
        assert measure["created_by_user_id"] == U_LICENSEE_A
        assert measure["annual_cost_usd"] == pytest.approx(57500.00, abs=0.01)
        assert measure["annual_generation_loss_mwh"] == pytest.approx(230.4, abs=0.01)

        self_estimate = api_client.record_definitive_estimate(
            measure["id"],
            {"estimate_note": "creator prices its own measure"},
            LICENSEE_HEADERS,
        )

        validate_error(self_estimate, "ERR_SEGREGATION_OF_DUTIES", 409)
        still_preliminary = read_measure(measure["id"])
        assert still_preliminary["cost_estimate_variant"] == "PRELIMINARY"
        assert still_preliminary["definitive_estimate_by_user_id"] is None

        independent = validate_success(
            api_client.record_definitive_estimate(
                measure["id"],
                {"estimate_note": "independent estimator"},
                make_licensee_headers("u_lic_b"),
            )
        )

        assert independent["cost_estimate_variant"] == "DEFINITIVE"
        assert independent["definitive_estimate_by_user_id"] == "u_lic_b"
        assert independent["annual_cost_usd"] == pytest.approx(53000.00, abs=0.01)
        assert independent["annual_generation_loss_mwh"] == pytest.approx(497.9, abs=0.01)
        assert_ledger_matches(
            read_project(project["id"]),
            total_pme_annual_cost_usd=53000.00,
            total_generation_loss_mwh=497.9,
            administrative_annual_charge_usd=1060.00,
            total_annual_burden_usd=74971.80,
            burden_ratio_pct=0.71,
        )


class TestReporterCannotCertifyItsOwnCategory:
    def test_the_water_quality_reporter_is_barred_from_the_water_quality_article(self):
        """Nothing links the study row to the obligation row but the resource category.

        PRD §3.9: "Segregation of duties applies here too: the acting `X-User-ID` must not be a user who submitted a resource study report in the same `resource_category` as the obligation's measure on the same project, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.9: "Where the obligation's `obligation_type` is `PME_IMPLEMENTATION`, its linked measure moves `INCLUDED → IMPLEMENTED`; the measure remains economically live, since `IMPLEMENTED` counts in the ledger exactly as `INCLUDED` does, but the project burden ledger is nonetheless re-run."

        Design: Corner/rbac/study_reporter_cannot_certify_the_same_category_obligation
        """
        ctx = setup_licensed_project(
            order_number="ORD-9055",
            study_overrides=dict(
                resource_category="WATER_QUALITY",
                study_title="Dissolved oxygen monitoring",
            ),
            site_overrides=dict(site_code="S1", river_mile=1.0),
            license_number="P-9055",
            project_name="Certify Reach",
            **MID_SIZED_PROJECT,
        )
        assert ctx["study"]["report_submitted_by_user_id"] == U_LICENSEE_REPORT
        assert ctx["order"]["article_count"] == 1
        obligation = obligation_of_type(ctx["obligations"], "PME_IMPLEMENTATION")
        assert obligation["due_date"] == "2027-02-01"
        set_clock("2026-09-01T00:00:00Z")
        scheduled = schedule_obligation(obligation["id"], "2026-09-01", "2026-09-30")
        assert scheduled["status"] == "SCHEDULED"

        reporter_certifies = api_client.certify_obligation(
            obligation["id"],
            {"certification_note": "reporter certifies its own category"},
            make_licensee_headers(U_LICENSEE_REPORT),
        )

        validate_error(reporter_certifies, "ERR_SEGREGATION_OF_DUTIES", 409)
        untouched = read_obligation(obligation["id"])
        assert untouched["status"] == "SCHEDULED"
        assert untouched["certified_by_user_id"] is None

        certified = certify_obligation(obligation["id"], user_id=U_LICENSEE_A)

        assert certified["status"] == "CERTIFIED"
        assert certified["certified_by_user_id"] == U_LICENSEE_A
        assert read_measure(ctx["condition_measures"][0]["id"])["status"] == "IMPLEMENTED"
        project = read_project(ctx["project"]["id"])
        assert project["total_pme_annual_cost_usd"] == pytest.approx(53000.00, abs=0.01)
        assert project["total_annual_burden_usd"] == pytest.approx(74971.80, abs=0.01)


class TestSharedReads:
    def test_every_role_reads_the_same_project_row(self):
        """The one operation all five roles share returns the same data to each of them.

        PRD §2.1: "Every read endpoint under `/relicensing` is open to all five roles."
        PRD §2.1: "For `AgencyReviewer` and `Stakeholder` there is a second, project-scoped access rule: the acting user must resolve to a `SettlementParty` registered on the same project as the target entity."

        Design: Corner/rbac/all_five_roles_can_read_the_project
        """
        set_clock("2026-08-01T00:00:00Z")
        project = new_project(
            license_number="P-9056",
            project_name="Shared Read Reach",
            **MID_SIZED_PROJECT,
        )
        setup_agency_party(project["id"])
        register_party(project["id"], **NGO_PARTY)

        reads = [
            validate_success(api_client.get_project(project["id"], LICENSEE_HEADERS)),
            validate_success(api_client.get_project(project["id"], AGENCY_HEADERS)),
            validate_success(
                api_client.get_project(project["id"], make_stakeholder_headers(U_NGO))
            ),
            validate_success(
                api_client.get_project(
                    project["id"], make_state_certifier_headers(U_STATE_CERTIFIER)
                )
            ),
            validate_success(api_client.get_project(project["id"], REGULATOR_HEADERS)),
        ]

        assert all(row["license_number"] == "P-9056" for row in reads)
        assert all(row["id"] == project["id"] for row in reads)
        assert all(row["project_name"] == "Shared Read Reach" for row in reads)
        assert len({row["version"] for row in reads}) == 1
        _parties, meta = validate_paginated(
            api_client.list_parties(
                make_stakeholder_headers(U_NGO), params={"limit": 100}
            )
        )
        assert meta["total_count"] == 2
