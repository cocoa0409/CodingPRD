"""Entity representations: initial state, defaults, computed fields and reference integrity."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    U_LICENSEE_A,
    U_NGO,
    U_STATE_CERTIFIER,
    api_client,
    assert_consultation_comment,
    assert_dam,
    assert_postures,
    assert_relicensing_project,
    assert_study_site,
    comment_payload,
    dam_payload,
    file_pad,
    is_valid_uuid,
    leave_comment,
    make_licensee_headers,
    make_state_certifier_headers,
    new_dam,
    new_project,
    new_site,
    new_study,
    new_study_plan,
    patch_project,
    project_payload,
    read_comment,
    read_study_plan,
    register_party,
    set_clock,
    setup_agency_party,
    setup_study_phase_project,
    site_payload,
    study_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

REGULATOR_HEADERS = TEST_USERS["regulator_headers"]
LICENSEE_HEADERS = make_licensee_headers(U_LICENSEE_A)
STATE_CERTIFIER_HEADERS = make_state_certifier_headers(U_STATE_CERTIFIER)
NGO_PARTY = dict(
    party_name="River Alliance",
    party_type="NGO",
    vote_weight=2,
    contact_user_id=U_NGO,
)


class TestProjectRepresentation:
    def test_a_new_project_reports_its_declared_initial_state(self):
        """Only the required inputs are supplied, and every derived field answers for itself.

        PRD §3.1: "A freshly registered project begins in `stage` `PRE_FILING` with `wqc_status` `NONE` and `version` 1."
        PRD §3.1: "Its `pad_filed_at`, `pad_year` and `application_filed_at` are all unset, and its entire burden ledger — `total_pme_annual_cost_usd`, `total_generation_loss_mwh`, `administrative_annual_charge_usd`, `total_annual_burden_usd` and `burden_ratio_pct` — reads zero with `economically_infeasible` false."

        Design: Corner/entities/project_creation_returns_declared_initial_state
        """
        set_clock("2026-08-01T00:00:00Z")

        response = api_client.create_project(
            project_payload(
                project_name="Corner Creek",
                installed_capacity_mw=15.5,
                base_annual_generation_mwh=80000,
                license_expiration_date="2035-06-30",
            ),
            REGULATOR_HEADERS,
        )

        project = validate_success(response, 201)
        assert_relicensing_project(project)
        assert project["stage"] == "PRE_FILING"
        assert project["wqc_status"] == "NONE"
        assert project["version"] == 1
        assert_postures(project, timeline_posture="ON_TRACK", regulatory_posture="OPEN")
        assert project["total_pme_annual_cost_usd"] == pytest.approx(0.00, abs=0.01)
        assert project["total_generation_loss_mwh"] == pytest.approx(0.0, abs=0.05)
        assert project["administrative_annual_charge_usd"] == pytest.approx(0.00, abs=0.01)
        assert project["total_annual_burden_usd"] == pytest.approx(0.00, abs=0.01)
        assert project["burden_ratio_pct"] == pytest.approx(0.00, abs=0.01)
        assert project["economically_infeasible"] is False
        assert project["infeasibility_waiver_granted"] is False
        assert project["pad_filed_at"] is None
        assert project["pad_year"] is None
        assert project["last_sweep_at"] is None
        assert project["unresolved_mandatory_comment_count"] == 0
        assert project["open_deficiency_count"] == 0
        assert project["compliance_flag_count"] == 0

    def test_the_identifier_and_version_are_server_minted_and_a_rename_bumps_only_the_version(self):
        """A name-only amendment increments the version and leaves the ledger alone.

        PRD §2.5: "**`version`** (integer): a counter that starts at 1 on creation and increments by 1 on every mutation of the resource, including mutations that only rewrite derived fields."
        PRD §3.1: "The `Regulator` may later amend three fields of a project: `project_name`, `base_annual_generation_mwh` and `infeasibility_waiver_granted`."

        Design: Corner/entities/project_system_fields_are_server_minted
        """
        set_clock("2026-08-01T00:00:00Z")
        project = new_project(
            project_name="System Field Dam",
            installed_capacity_mw=9.0,
            base_annual_generation_mwh=50000,
            license_expiration_date="2035-06-30",
        )
        assert is_valid_uuid(project["id"])
        assert project["version"] == 1

        renamed = patch_project(project["id"], project_name="System Field Dam (renamed)")

        assert renamed["id"] == project["id"]
        assert renamed["project_name"] == "System Field Dam (renamed)"
        assert renamed["version"] == 2
        assert renamed["created_at"] == project["created_at"]
        assert renamed["burden_ratio_pct"] == pytest.approx(0.00, abs=0.01)

    def test_omitting_the_license_expiration_date_is_rejected_as_a_bad_request(self):
        """The field that anchors both milestones has no default, so its absence is a 400.

        PRD §2.12: "7. Required body fields are present and non-null — `ERR_INVALID_REQUEST` (400), on every create and amend operation."

        Design: Corner/entities/project_creation_missing_required_license_expiration_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        payload = project_payload(
            license_number="P-9904",
            project_name="No Expiry",
            installed_capacity_mw=9.0,
            base_annual_generation_mwh=50000,
        )
        payload.pop("license_expiration_date")

        response = api_client.create_project(payload, REGULATOR_HEADERS)

        validate_error(response, "ERR_INVALID_REQUEST", 400)
        rows, _meta = validate_paginated(
            api_client.list_projects(REGULATOR_HEADERS, params={"limit": 100})
        )
        assert [row for row in rows if row["license_number"] == "P-9904"] == []


class TestDamAndSiteRepresentation:
    def test_a_dam_reads_back_the_capacity_integers_that_drive_scheduling(self):
        """GET by id returns exactly the hazard, interval and capacity values stored.

        PRD §3.1: "A **Dam** is registered with a `project_id`, a `dam_code` that must be unique within that project, a `hazard_class` of `HIGH`, `SIGNIFICANT` or `LOW`, and an `inspection_interval_months` between 6 and 60 inclusive that fixes how long after the license takes effect the first dam-safety inspection falls due."

        Design: Corner/entities/dam_retrieval_returns_stored_fields
        """
        set_clock("2026-08-01T00:00:00Z")
        project = new_project(
            project_name="Retrieval Falls",
            installed_capacity_mw=9.0,
            base_annual_generation_mwh=50000,
            license_expiration_date="2035-06-30",
        )
        dam = new_dam(
            project["id"],
            dam_code="D7",
            hazard_class="SIGNIFICANT",
            inspection_interval_months=24,
            eap_exercise_required=False,
            max_concurrent_field_activities=3,
        )

        fetched = validate_success(api_client.get_dam(dam["id"], REGULATOR_HEADERS))

        assert_dam(fetched)
        assert fetched["dam_code"] == "D7"
        assert fetched["hazard_class"] == "SIGNIFICANT"
        assert fetched["inspection_interval_months"] == 24
        assert fetched["max_concurrent_field_activities"] == 3
        assert fetched["eap_exercise_required"] is False
        assert fetched["project_id"] == project["id"]
        assert fetched["version"] == 1

    def test_the_optional_dam_and_site_inputs_fall_back_to_their_declared_defaults(self):
        """Omitted options yield an exercise-required dam of capacity one and an unbuffered site.

        PRD §3.1: "Two optional inputs shape later obligations: `eap_exercise_required` defaults to true and, when true, causes order issuance to generate an emergency-action-plan exercise obligation for that dam; and `max_concurrent_field_activities` defaults to 1 and caps how much overlapping field activity the dam can absorb, as §3.9 details."
        PRD §3.1: "Two optional inputs govern the site's fieldwork calendar: `min_rest_buffer_days` defaults to 0 and imposes a mandatory quiet period in days that must elapse after an occupying fieldwork window ends before the next window may begin at that site, and `cultural_sensitivity` defaults to `NONE` with `MODERATE` and `HIGH` as its other values."

        Design: Corner/entities/dam_optional_inputs_take_declared_defaults
        """
        set_clock("2026-08-01T00:00:00Z")
        project = new_project(
            project_name="Default Dam",
            installed_capacity_mw=9.0,
            base_annual_generation_mwh=50000,
            license_expiration_date="2035-06-30",
        )

        dam = validate_success(
            api_client.create_dam(
                dam_payload(
                    project["id"],
                    dam_code="D1",
                    hazard_class="HIGH",
                    inspection_interval_months=12,
                ),
                LICENSEE_HEADERS,
            ),
            201,
        )
        site = validate_success(
            api_client.create_site(
                site_payload(project["id"], site_code="S1", river_mile=1.0),
                LICENSEE_HEADERS,
            ),
            201,
        )

        assert dam["eap_exercise_required"] is True
        assert dam["max_concurrent_field_activities"] == 1
        assert dam["project_id"] == project["id"]
        assert_study_site(site)
        assert site["min_rest_buffer_days"] == 0
        assert site["cultural_sensitivity"] == "NONE"
        assert site["project_id"] == project["id"]

    def test_an_unlisted_hazard_class_is_rejected_and_creates_no_dam(self):
        """A plausible EXTREME is outside the declared enum, so nothing is stored.

        PRD §2.12: "8. Field types, enum membership and numeric domains hold — `ERR_INVALID_REQUEST` (400), on every create and amend operation."

        Design: Corner/entities/dam_invalid_hazard_class_enum_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        project = new_project(
            project_name="Enum Dam",
            installed_capacity_mw=9.0,
            base_annual_generation_mwh=50000,
            license_expiration_date="2035-06-30",
        )

        response = api_client.create_dam(
            dam_payload(
                project["id"],
                dam_code="D1",
                hazard_class="EXTREME",
                inspection_interval_months=12,
            ),
            LICENSEE_HEADERS,
        )

        validate_error(response, "ERR_INVALID_REQUEST", 400)
        rows, meta = validate_paginated(
            api_client.list_dams(
                REGULATOR_HEADERS, params={"project_id": project["id"]}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_the_site_list_pages_the_filtered_set_and_reports_its_total(self):
        """Three sites read two at a time report a stable total and a closing page.

        PRD §2.3: "`limit` caps the number of items returned; it defaults to 10, may be no smaller than 1 and no larger than 100."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope."

        Design: Corner/entities/site_listing_returns_paginated_envelope
        """
        set_clock("2026-08-01T00:00:00Z")
        project = new_project(
            project_name="Paging Reach",
            installed_capacity_mw=9.0,
            base_annual_generation_mwh=50000,
            license_expiration_date="2035-06-30",
        )
        for code, mile in (("S1", 1.0), ("S2", 2.0), ("S3", 3.0)):
            new_site(project["id"], site_code=code, river_mile=mile)

        first_page, first_meta = validate_paginated(
            api_client.list_sites(
                REGULATOR_HEADERS,
                params={"project_id": project["id"], "limit": 2, "offset": 0},
            )
        )
        second_page, second_meta = validate_paginated(
            api_client.list_sites(
                REGULATOR_HEADERS,
                params={"project_id": project["id"], "limit": 2, "offset": 2},
            )
        )

        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["offset"] == 2
        assert second_meta["has_more"] is False
        assert first_page[0]["id"] != second_page[0]["id"]
        assert all(
            row["project_id"] == project["id"] for row in first_page + second_page
        )


class TestConsultationCommentRepresentation:
    def _draft_plan_with_one_ngo_party(self):
        set_clock("2026-08-01T00:00:00Z")
        project = new_project(
            project_name="Computed Flag Reach",
            installed_capacity_mw=9.0,
            base_annual_generation_mwh=50000,
            license_expiration_date="2035-06-30",
        )
        file_pad(project["id"])
        plan = new_study_plan(project["id"])
        party = register_party(project["id"], **NGO_PARTY)
        return {"project": project, "plan": plan, "party": party}

    def test_the_mandatory_flag_is_computed_from_the_party_and_ignores_the_body(self):
        """An NGO that asks for a mandatory condition gets an ordinary comment.

        PRD §3.3: "The payload also admits an `is_mandatory_condition` flag, but the stored value is not the client's: the server sets `is_mandatory_condition` to true exactly when the authoring party's `has_conditioning_authority` is true at the moment of filing, and to false otherwise, whatever the request said."
        PRD §3.5: "Three optional inputs complete the registration: `has_conditioning_authority` defaults to false and may be set true only for a party whose `party_type` is `AGENCY`, with any other combination rejected as `ERR_INVALID_REQUEST`; `vote_weight` defaults to 1 and must be at least 1; and `contact_user_id` binds the `X-User-ID` of the party's agency-reviewer or stakeholder user to this party row."

        Design: Corner/entities/comment_mandatory_flag_is_computed_from_party_authority_input_ignored
        """
        ctx = self._draft_plan_with_one_ngo_party()
        assert ctx["party"]["has_conditioning_authority"] is False

        comment = leave_comment(
            ctx["plan"]["id"],
            ctx["party"],
            role="Stakeholder",
            resource_category="RECREATION",
            comment_text="Add a boat ramp",
            is_mandatory_condition=True,
        )

        assert comment["is_mandatory_condition"] is False
        assert comment["resolution_status"] == "OPEN"
        assert comment["disposition"] is None
        assert comment["reopen_count"] == 0
        plan = read_study_plan(ctx["plan"]["id"])
        assert plan["open_comment_count"] == 1
        assert plan["unresolved_mandatory_comment_count"] == 0

    def test_a_comment_carries_only_an_identifier_and_a_creation_stamp(self):
        """A conditioning agency's comment is a ledger entry with no version of its own.

        PRD §2.5: "Two resources are append-only records of a moment rather than mutable entities, and they carry only `id` and `created_at`: a `ConsultationComment` and a `SettlementSignature`."
        PRD §2.5: "A comment's disposition state does change over its life, but the record is treated as a ledger entry rather than a versioned resource, so mutations of a comment are reflected on the owning study plan's `version` rather than on the comment itself."

        Design: Corner/entities/comment_is_immutable_and_has_no_version_field
        """
        ctx = setup_study_phase_project(
            project_name="Immutable Reach",
            installed_capacity_mw=9.0,
            base_annual_generation_mwh=50000,
            license_expiration_date="2035-06-30",
        )
        party = setup_agency_party(ctx["project"]["id"])
        comment = leave_comment(
            ctx["plan"]["id"],
            party,
            resource_category="FISH_PASSAGE",
            comment_text="Study downstream passage",
        )

        fetched = read_comment(comment["id"])

        assert_consultation_comment(fetched)
        assert fetched["resolution_status"] == "OPEN"
        assert fetched["is_mandatory_condition"] is True
        assert fetched["reopen_count"] == 0
        assert "version" not in fetched
        assert "updated_at" not in fetched

    def test_an_unknown_party_reference_answers_with_the_party_not_found_code(self):
        """The body reference is resolved per field, so the ghost party names itself.

        PRD §2.12: "5. Every reference in the request body resolves to an existing row — the referenced entity's not-found code at 404."

        Design: Corner/entities/comment_with_unknown_party_id_not_found
        """
        ctx = setup_study_phase_project(
            project_name="Unknown Party Reach",
            installed_capacity_mw=9.0,
            base_annual_generation_mwh=50000,
            license_expiration_date="2035-06-30",
        )
        party = setup_agency_party(ctx["project"]["id"])

        response = api_client.create_comment(
            comment_payload(
                ctx["plan"]["id"],
                NON_EXISTENT_UUID,
                resource_category="CULTURAL",
                comment_text="Ghost party",
            ),
            {"X-User-ID": party["contact_user_id"], "X-User-Role": "AgencyReviewer"},
        )

        validate_error(response, "ERR_PARTY_NOT_FOUND", 404)
        assert read_study_plan(ctx["plan"]["id"])["open_comment_count"] == 0


class TestResourceStudyReferences:
    def test_a_backwards_fieldwork_window_is_rejected_before_the_plan_is_touched(self):
        """An interval whose end precedes its start never reaches the calendar rules.

        PRD §2.12: "9. Interval payloads are ordered — `ERR_INVALID_REQUEST` (400). On study creation, `fieldwork_window_start` must be strictly earlier than `fieldwork_window_end`, because the fieldwork window is half-open."

        Design: Corner/entities/study_misordered_fieldwork_window_rejected
        """
        ctx = setup_study_phase_project(
            sites=[dict(site_code="S1", river_mile=1.0)],
            project_name="Interval Reach",
            installed_capacity_mw=9.0,
            base_annual_generation_mwh=50000,
            license_expiration_date="2035-06-30",
        )

        response = api_client.create_study(
            study_payload(
                ctx["plan"]["id"],
                ctx["sites"][0]["id"],
                resource_category="RECREATION",
                study_title="Backwards window",
                fieldwork_window_start="2026-10-01",
                fieldwork_window_end="2026-09-01",
            ),
            LICENSEE_HEADERS,
        )

        validate_error(response, "ERR_INVALID_REQUEST", 400)
        plan = read_study_plan(ctx["plan"]["id"])
        assert plan["attached_study_count"] == 0
        assert plan["version"] == ctx["plan"]["version"]

    def test_a_site_from_another_project_is_a_cross_project_reference_not_a_miss(self):
        """Both rows exist and both are found; only their projects disagree.

        PRD §2.10: "Third, when a single request body carries two references that both hang off a project, those references must hang off the *same* project."
        PRD §2.10: "Mixing projects is a bad reference, not a state error, and it is rejected with `ERR_CROSS_PROJECT_REFERENCE` (HTTP 422)."

        Design: Corner/entities/study_with_site_from_another_project_returns_cross_project_error
        """
        ctx = setup_study_phase_project(
            project_name="Project A",
            installed_capacity_mw=9.0,
            base_annual_generation_mwh=50000,
            license_expiration_date="2035-06-30",
        )
        other_project = new_project(
            project_name="Project B",
            installed_capacity_mw=9.0,
            base_annual_generation_mwh=50000,
            license_expiration_date="2035-06-30",
        )
        foreign_site = new_site(other_project["id"], site_code="S1", river_mile=1.0)

        response = api_client.create_study(
            study_payload(
                ctx["plan"]["id"],
                foreign_site["id"],
                resource_category="RECREATION",
                study_title="Wrong-project site",
            ),
            LICENSEE_HEADERS,
        )

        validate_error(response, "ERR_CROSS_PROJECT_REFERENCE", 422)
        still_there = validate_success(
            api_client.get_site(foreign_site["id"], REGULATOR_HEADERS)
        )
        assert still_there["project_id"] == other_project["id"]
        assert read_study_plan(ctx["plan"]["id"])["attached_study_count"] == 0

    def test_the_study_list_is_reachable_from_the_owning_plan(self):
        """Filtering by the parent plan returns that plan's study and nothing else.

        PRD §2.3: "Unless a specific endpoint says otherwise, list results are ordered by `created_at` ascending."
        PRD §2.1: "Every read endpoint under `/relicensing` is open to all five roles."

        Design: Corner/entities/studies_are_reachable_by_study_plan_filter
        """
        ctx = setup_study_phase_project(
            sites=[dict(site_code="S1", river_mile=1.0)],
            project_name="FK Reach",
            installed_capacity_mw=9.0,
            base_annual_generation_mwh=50000,
            license_expiration_date="2035-06-30",
        )
        site = ctx["sites"][0]
        study = new_study(
            ctx["plan"]["id"],
            site["id"],
            resource_category="WATER_QUALITY",
            study_title="Temperature study",
        )

        rows, meta = validate_paginated(
            api_client.list_studies(
                STATE_CERTIFIER_HEADERS, params={"study_plan_id": ctx["plan"]["id"]}
            )
        )

        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == study["id"]
        assert rows[0]["study_plan_id"] == ctx["plan"]["id"]
        assert rows[0]["site_id"] == site["id"]


class TestMeasureLookup:
    def test_an_unknown_measure_identifier_answers_with_the_measure_not_found_code(self):
        """A well-formed UUID that names nothing gets the entity-specific 404.

        PRD §2.10: "First, identifiers that appear in the URL are resolved left to right, and the first identifier that names no existing row decides the response: a request naming `project_id`, `dam_id`, `site_id`, `study_plan_id`, `study_id`, `comment_id`, `party_id`, `settlement_id`, `signature_id`, `wqc_id`, `measure_id`, `application_id`, `obligation_id` or `order_id` that resolves to nothing is answered with that entity's not-found code — `ERR_PROJECT_NOT_FOUND`, `ERR_DAM_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_STUDY_PLAN_NOT_FOUND`, `ERR_STUDY_NOT_FOUND`, `ERR_COMMENT_NOT_FOUND`, `ERR_PARTY_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_WQC_NOT_FOUND`, `ERR_MEASURE_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_OBLIGATION_NOT_FOUND` or `ERR_ORDER_NOT_FOUND` respectively — all at HTTP 404."

        Design: Corner/entities/measure_get_with_unknown_id_not_found
        """
        set_clock("2026-08-01T00:00:00Z")

        response = api_client.get_measure(NON_EXISTENT_UUID, LICENSEE_HEADERS)

        error = validate_error(response, "ERR_MEASURE_NOT_FOUND", 404)
        assert error["message"].strip() != ""
