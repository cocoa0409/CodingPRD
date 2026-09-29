"""Uniqueness scopes, pagination range, clearance gates, signature rounds and report periods."""
import pytest

from test_helpers import (
    TEST_USERS,
    U_LICENSEE_A,
    U_NGO,
    U_TRIBE,
    annual_report_payload,
    api_client,
    assert_plan_counters,
    assert_postures,
    circulate_settlement,
    decide_plan,
    file_annual_report,
    leave_comment,
    make_licensee_headers,
    new_measure,
    new_project,
    new_settlement,
    new_site,
    new_study,
    obligation_of_type,
    project_payload,
    read_comment,
    read_measure,
    read_order,
    read_project,
    read_settlement,
    read_signature,
    read_study_plan,
    register_party,
    request_certification,
    resolve_comment,
    run_sweep,
    set_clock,
    setup_agency_party,
    setup_circulated_settlement,
    setup_licensed_project,
    setup_study_phase_project,
    sign_roster,
    sign_settlement,
    site_payload,
    study_payload,
    submit_plan,
    tally_settlement,
    validate_error,
    validate_paginated,
    validate_success,
    water_quality_certification_payload,
)

REGULATOR_HEADERS = TEST_USERS["regulator_headers"]
LICENSEE_HEADERS = make_licensee_headers(U_LICENSEE_A)
SMALL_PROJECT = dict(
    installed_capacity_mw=9.0,
    base_annual_generation_mwh=50000,
    license_expiration_date="2035-06-30",
)
TRIBE_PARTY = dict(
    party_name="River Tribe",
    party_type="TRIBE",
    vote_weight=3,
    contact_user_id=U_TRIBE,
)
NGO_PARTY = dict(
    party_name="Watershed Council",
    party_type="NGO",
    vote_weight=2,
    contact_user_id=U_NGO,
)


class TestUniquenessScopes:
    def test_a_second_project_claiming_the_same_license_number_is_refused(self):
        """The number of the existing licence identifies one file and one only.

        PRD §2.12: "13. Uniqueness holds — `ERR_DUPLICATE_KEY` (409). `license_number` is unique across all projects, `dam_code` is unique within a project, `site_code` is unique within a project, and `order_number` is unique globally."

        Design: Corner/validations/duplicate_license_number_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        first = new_project(
            license_number="P-9030", project_name="First Reach", **SMALL_PROJECT
        )

        response = api_client.create_project(
            project_payload(
                license_number="P-9030",
                project_name="Second Reach",
                installed_capacity_mw=12.0,
                base_annual_generation_mwh=70000,
                license_expiration_date="2036-06-30",
            ),
            REGULATOR_HEADERS,
        )

        validate_error(response, "ERR_DUPLICATE_KEY", 409)
        rows, meta = validate_paginated(
            api_client.list_projects(REGULATOR_HEADERS, params={"limit": 100})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [first["id"]]
        assert rows[0]["project_name"] == "First Reach"

    def test_the_same_site_code_lives_in_two_projects_but_never_twice_in_one(self):
        """S1 belongs to each reach separately and to neither reach twice.

        PRD §2.12: "13. Uniqueness holds — `ERR_DUPLICATE_KEY` (409). `license_number` is unique across all projects, `dam_code` is unique within a project, `site_code` is unique within a project, and `order_number` is unique globally."
        PRD §3.1: "A **StudySite** is likewise registered with a `project_id` and a `site_code` unique within the project, plus a `river_mile` that is carried for reporting only and drives no rule."

        Design: Corner/validations/site_code_uniqueness_is_scoped_to_the_project
        """
        set_clock("2026-08-01T00:00:00Z")
        reach_a = new_project(
            license_number="P-9031", project_name="Scope Reach A", **SMALL_PROJECT
        )
        reach_b = new_project(
            license_number="P-9032", project_name="Scope Reach B", **SMALL_PROJECT
        )

        site_a = new_site(reach_a["id"], site_code="S1", river_mile=1.0)
        site_b = new_site(reach_b["id"], site_code="S1", river_mile=4.5)
        repeat = api_client.create_site(
            site_payload(reach_a["id"], site_code="S1", river_mile=9.0),
            LICENSEE_HEADERS,
        )

        assert site_b["id"] != site_a["id"]
        assert site_b["site_code"] == "S1"
        assert site_b["river_mile"] == pytest.approx(4.5, abs=0.01)
        validate_error(repeat, "ERR_DUPLICATE_KEY", 409)
        _rows, meta = validate_paginated(
            api_client.list_sites(
                REGULATOR_HEADERS, params={"project_id": reach_a["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 1


class TestPaginationRange:
    def test_a_limit_of_one_hundred_is_inside_the_range_and_anything_outside_it_is_not(
        self,
    ):
        """The one rule in the catalogue that answers with a validation code.

        PRD §2.3: "`limit` caps the number of items returned; it defaults to 10, may be no smaller than 1 and no larger than 100."
        PRD §2.3: "A `limit` outside the range 1 through 100, or a negative `offset`, is rejected with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/validations/pagination_limit_above_one_hundred_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        new_project(
            license_number="P-9033", project_name="Pagination Reach", **SMALL_PROJECT
        )

        rows, meta = validate_paginated(
            api_client.list_projects(
                REGULATOR_HEADERS, params={"limit": 100, "offset": 0}
            )
        )

        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        for params in (
            {"limit": 101, "offset": 0},
            {"limit": 10, "offset": -1},
            {"limit": 0, "offset": 0},
        ):
            validate_error(
                api_client.list_projects(REGULATOR_HEADERS, params=params),
                "ERR_VALIDATION",
                400,
            )


class TestCulturalClearance:
    def _project_with_a_moderate_and_a_high_sensitivity_site(self):
        ctx = setup_study_phase_project(
            sites=[
                dict(site_code="SM", river_mile=1.0, cultural_sensitivity="MODERATE"),
                dict(site_code="SH", river_mile=6.0, cultural_sensitivity="HIGH"),
            ],
            project_name="Clearance Reach",
            **SMALL_PROJECT,
        )
        ctx["moderate_site"], ctx["high_site"] = ctx["sites"]
        return ctx

    def test_the_clearance_follows_the_site_and_not_the_resource_category(self):
        """A cultural study at a moderate site walks in; a recreation study at a high site does not.

        PRD §3.4: "An optional `cultural_clearance_reference` records a tribal or state historic-preservation clearance; it is stored verbatim wherever it is supplied, but it is *required* — non-empty — whenever the named site's `cultural_sensitivity` is `HIGH`, whatever the study's own `resource_category` may be."
        PRD §3.4: "A study at a `HIGH`-sensitivity site without one is rejected with `ERR_CULTURAL_CLEARANCE_MISSING`."

        Design: Corner/validations/cultural_clearance_required_only_at_high_sensitivity_sites
        """
        ctx = self._project_with_a_moderate_and_a_high_sensitivity_site()

        at_moderate_site = new_study(
            ctx["plan"]["id"],
            ctx["moderate_site"]["id"],
            resource_category="CULTURAL",
            study_title="Ethnographic survey at moderate site",
        )
        refused = api_client.create_study(
            study_payload(
                ctx["plan"]["id"],
                ctx["high_site"]["id"],
                resource_category="RECREATION",
                study_title="Recreation survey at high site",
            ),
            LICENSEE_HEADERS,
        )

        assert at_moderate_site["cultural_clearance_reference"] is None
        validate_error(refused, "ERR_CULTURAL_CLEARANCE_MISSING", 422)
        assert read_study_plan(ctx["plan"]["id"])["attached_study_count"] == 1

    def test_supplying_the_clearance_reference_admits_the_identical_payload(self):
        """The same study is accepted once the historic-preservation reference is named.

        PRD §3.4: "An optional `cultural_clearance_reference` records a tribal or state historic-preservation clearance; it is stored verbatim wherever it is supplied, but it is *required* — non-empty — whenever the named site's `cultural_sensitivity` is `HIGH`, whatever the study's own `resource_category` may be."
        PRD §3.4: "Creation sets `fieldwork_status` `PLANNED` and `review_status` `NOT_SUBMITTED`, leaves `additional_round_count` at 0 and `report_submitted_at` and `report_submitted_by_user_id` unset, and increments the owning plan's `attached_study_count` and `version`."

        Design: Corner/validations/cultural_clearance_required_only_at_high_sensitivity_sites
        """
        ctx = self._project_with_a_moderate_and_a_high_sensitivity_site()
        new_study(
            ctx["plan"]["id"],
            ctx["moderate_site"]["id"],
            resource_category="CULTURAL",
            study_title="Ethnographic survey at moderate site",
        )
        validate_error(
            api_client.create_study(
                study_payload(
                    ctx["plan"]["id"],
                    ctx["high_site"]["id"],
                    resource_category="RECREATION",
                    study_title="Recreation survey at high site",
                ),
                LICENSEE_HEADERS,
            ),
            "ERR_CULTURAL_CLEARANCE_MISSING",
            422,
        )

        cleared = new_study(
            ctx["plan"]["id"],
            ctx["high_site"]["id"],
            resource_category="RECREATION",
            study_title="Recreation survey at high site",
            cultural_clearance_reference="THPO-2026-118",
        )

        assert cleared["cultural_clearance_reference"] == "THPO-2026-118"
        assert cleared["fieldwork_status"] == "PLANNED"
        assert cleared["review_status"] == "NOT_SUBMITTED"
        assert read_study_plan(ctx["plan"]["id"])["attached_study_count"] == 2


class TestSignatureRoundDiscipline:
    def _negotiating_settlement_between_two_parties(self):
        ctx = setup_study_phase_project(project_name="Signature Reach", **SMALL_PROJECT)
        project_id = ctx["project"]["id"]
        ctx["agency_party"] = setup_agency_party(project_id)
        ctx["tribe_party"] = register_party(
            project_id,
            party_name="River Tribe",
            party_type="TRIBE",
            vote_weight=1,
            contact_user_id=U_TRIBE,
        )
        ctx["settlement"] = new_settlement(project_id, title="Round rules settlement")
        return ctx

    def test_no_position_is_taken_before_the_round_opens(self):
        """A settlement still under negotiation has no round to sign into.

        PRD §3.5: "Recording a signature while the settlement is not `CIRCULATED` is rejected with `ERR_SIGNATURE_ROUND_CLOSED`, and a second signature by the same party within the same round is rejected with `ERR_DUPLICATE_SIGNATURE`."
        PRD §3.5: "Circulation stamps `circulated_at` with the logical clock, sets `total_vote_weight` to the sum of `vote_weight` over all of the project's parties, and increments the settlement's `version`."

        Design: Corner/validations/signature_outside_a_circulated_round_and_repeat_signature_rejected
        """
        ctx = self._negotiating_settlement_between_two_parties()
        assert ctx["settlement"]["status"] == "NEGOTIATING"

        too_early = api_client.create_signature(
            {
                "settlement_id": ctx["settlement"]["id"],
                "party_id": ctx["agency_party"]["id"],
                "position": "SUPPORT",
            },
            TEST_USERS["agency_reviewer_headers"],
        )

        validate_error(too_early, "ERR_SIGNATURE_ROUND_CLOSED", 409)
        circulated = circulate_settlement(ctx["settlement"]["id"])
        assert circulated["status"] == "CIRCULATED"
        assert circulated["total_vote_weight"] == 2

    def test_a_party_signs_its_round_once_whatever_position_it_changes_to(self):
        """The agency's first mark is immutable and its change of heart is refused.

        PRD §3.5: "The signature is immutable once written: it copies `round_number` from the settlement's current round, stamps `signed_at` from the logical clock, and leaves `share_pct` unset until the round is tallied."
        PRD §3.5: "Recording a signature while the settlement is not `CIRCULATED` is rejected with `ERR_SIGNATURE_ROUND_CLOSED`, and a second signature by the same party within the same round is rejected with `ERR_DUPLICATE_SIGNATURE`."

        Design: Corner/validations/signature_outside_a_circulated_round_and_repeat_signature_rejected
        """
        ctx = self._negotiating_settlement_between_two_parties()
        circulate_settlement(ctx["settlement"]["id"])

        signature = sign_settlement(
            ctx["settlement"]["id"], ctx["agency_party"], position="SUPPORT"
        )
        repeat = api_client.create_signature(
            {
                "settlement_id": ctx["settlement"]["id"],
                "party_id": ctx["agency_party"]["id"],
                "position": "OPPOSE",
            },
            TEST_USERS["agency_reviewer_headers"],
        )

        assert signature["round_number"] == 1
        assert signature["share_pct"] is None
        validate_error(repeat, "ERR_DUPLICATE_SIGNATURE", 409)
        assert read_signature(signature["id"])["position"] == "SUPPORT"
        _rows, meta = validate_paginated(
            api_client.list_signatures(
                REGULATOR_HEADERS,
                params={"settlement_id": ctx["settlement"]["id"], "limit": 100},
            )
        )
        assert meta["total_count"] == 1


class TestConditioningPartyVeto:
    def _circulated_settlement_opposed_only_by_the_conditioning_agency(self):
        ctx = setup_circulated_settlement(
            party_specs=[dict(TRIBE_PARTY), dict(NGO_PARTY)],
            settlement_measures=[
                dict(
                    measure_name="Recreation boat ramp",
                    resource_category="RECREATION",
                    capital_cost_usd=600000.00,
                    annual_om_cost_usd=20000.00,
                    construction_start_year=2026,
                    implementation_months=6,
                    flow_release_cfs=0,
                    gross_head_ft=60,
                    release_days=0,
                )
            ],
            study_overrides=dict(
                resource_category="RECREATION", study_title="Recreation use survey"
            ),
            project_name="Veto Reach",
            **SMALL_PROJECT,
        )
        agency, tribe, ngo = ctx["parties"]
        ctx["signatures"] = sign_roster(
            ctx["settlement"]["id"],
            [(agency, "OPPOSE"), (tribe, "SUPPORT"), (ngo, "SUPPORT")],
        )
        return ctx

    def test_the_agency_veto_defeats_a_tally_that_clears_the_threshold(self):
        """Eighty-three percent of the weight supports it and the weight-one agency wins.

        PRD §3.5: "And no party with `has_conditioning_authority` true may have recorded a `position` of `OPPOSE` in the current round, or the request is rejected with `ERR_CONDITIONING_PARTY_VETO`; a conditioning agency's opposition defeats the settlement no matter how much weight supports it."
        PRD §2.12: "24. Settlement execution requires the project to have a study plan in `APPROVED` status — `ERR_STUDY_PLAN_NOT_APPROVED` (409)."

        Design: Corner/validations/conditioning_party_veto_blocks_a_tally_that_clears_the_threshold
        """
        ctx = self._circulated_settlement_opposed_only_by_the_conditioning_agency()
        assert ctx["plan"]["status"] == "APPROVED"
        assert ctx["parties"][0]["has_conditioning_authority"] is True

        response = api_client.tally_settlement(
            ctx["settlement"]["id"],
            {"intended_outcome": "EXECUTE", "tally_note": "seek execution"},
            LICENSEE_HEADERS,
        )

        validate_error(response, "ERR_CONDITIONING_PARTY_VETO", 422)
        untouched = read_settlement(ctx["settlement"]["id"])
        assert untouched["status"] == "CIRCULATED"
        assert untouched["executed_at"] is None
        assert read_measure(ctx["measures"][0]["id"])["status"] == "PROPOSED"
        assert read_project(ctx["project"]["id"])[
            "total_pme_annual_cost_usd"
        ] == pytest.approx(0.00, abs=0.01)

    def test_the_same_signatures_closed_as_a_round_still_score_eighty_three_percent(
        self,
    ):
        """The veto is a separate gate, not a discount applied to the support total.

        PRD §3.5: "Then, for each signature of the current round whose `position` is `SUPPORT`, that signature's `share_pct` is computed as 100 multiplied by the signing party's `vote_weight`, divided by `total_vote_weight`, rounded half up to two decimal places, and persisted on the signature row."
        PRD §3.5: "Below round 3, closing the round moves the settlement `CIRCULATED → NEGOTIATING`: it persists the closed round's `support_pct`, increments `round_number` by 1, clears `circulated_at` back to unset, retains every prior-round signature unchanged, and increments the settlement's `version`."

        Design: Corner/validations/conditioning_party_veto_blocks_a_tally_that_clears_the_threshold
        """
        ctx = self._circulated_settlement_opposed_only_by_the_conditioning_agency()
        validate_error(
            api_client.tally_settlement(
                ctx["settlement"]["id"],
                {"intended_outcome": "EXECUTE", "tally_note": "seek execution"},
                LICENSEE_HEADERS,
            ),
            "ERR_CONDITIONING_PARTY_VETO",
            422,
        )

        closed = tally_settlement(ctx["settlement"]["id"], "CLOSE_ROUND")

        assert closed["status"] == "NEGOTIATING"
        assert closed["round_number"] == 2
        assert closed["total_vote_weight"] == 6
        assert closed["support_pct"] == pytest.approx(83.33, abs=0.01)
        _agency_signature, tribe_signature, ngo_signature = ctx["signatures"]
        assert read_signature(tribe_signature["id"])["share_pct"] == pytest.approx(
            50.00, abs=0.01
        )
        assert read_signature(ngo_signature["id"])["share_pct"] == pytest.approx(
            33.33, abs=0.01
        )
        assert read_measure(ctx["measures"][0]["id"])["status"] == "PROPOSED"


class TestMandatoryCommentGate:
    def _plan_under_review_carrying_one_open_mandatory_comment(self):
        ctx = setup_study_phase_project(
            sites=[dict(site_code="S1", river_mile=1.0)],
            project_name="Mandatory Comment Reach",
            **SMALL_PROJECT,
        )
        project_id = ctx["project"]["id"]
        new_study(
            ctx["plan"]["id"],
            ctx["sites"][0]["id"],
            study_title="Fish passage assessment",
        )
        ctx["agency_party"] = setup_agency_party(project_id)
        ctx["comment"] = leave_comment(
            ctx["plan"]["id"],
            ctx["agency_party"],
            comment_text="Add a downstream passage study",
        )
        ctx["plan"] = submit_plan(ctx["plan"]["id"])
        return ctx

    def test_the_conditioning_agency_comment_is_mandatory_and_blocks_approval(self):
        """The determination fails on a counter the plan inherits from its comments.

        PRD §3.3: "The payload also admits an `is_mandatory_condition` flag, but the stored value is not the client's: the server sets `is_mandatory_condition` to true exactly when the authoring party's `has_conditioning_authority` is true at the moment of filing, and to false otherwise, whatever the request said."
        PRD §3.3: "It is permitted only when the plan's `unresolved_mandatory_comment_count` is zero, and a plan still carrying an open mandatory comment is rejected with `ERR_UNRESOLVED_MANDATORY_COMMENTS`."

        Design: Corner/validations/plan_approval_blocked_until_the_mandatory_comment_is_resolved
        """
        ctx = self._plan_under_review_carrying_one_open_mandatory_comment()
        assert ctx["comment"]["is_mandatory_condition"] is True
        assert ctx["plan"]["status"] == "UNDER_AGENCY_REVIEW"
        assert_plan_counters(
            ctx["plan"], open_comment_count=1, unresolved_mandatory_comment_count=1
        )

        response = api_client.decide_study_plan(
            ctx["plan"]["id"],
            {"determination": "APPROVE"},
            TEST_USERS["agency_reviewer_headers"],
        )

        validate_error(response, "ERR_UNRESOLVED_MANDATORY_COMMENTS", 409)
        blocked = read_study_plan(ctx["plan"]["id"])
        assert blocked["status"] == "UNDER_AGENCY_REVIEW"
        assert blocked["approved_at"] is None
        assert_postures(
            read_project(ctx["project"]["id"]), regulatory_posture="RESTRICTED"
        )

    def test_resolving_the_comment_once_clears_the_gate_and_a_second_resolve_is_refused(
        self,
    ):
        """The disposition is recorded exactly once and then the determination passes.

        PRD §3.3: "A comment that is already `RESOLVED` is rejected with `ERR_COMMENT_ALREADY_RESOLVED`."
        PRD §3.3: "On success it stamps `approved_at` with the logical clock, recomputes the project's `unresolved_mandatory_comment_count` and then `regulatory_posture`, and increments the plan's `version`."

        Design: Corner/validations/plan_approval_blocked_until_the_mandatory_comment_is_resolved
        """
        ctx = self._plan_under_review_carrying_one_open_mandatory_comment()
        validate_error(
            api_client.decide_study_plan(
                ctx["plan"]["id"],
                {"determination": "APPROVE"},
                TEST_USERS["agency_reviewer_headers"],
            ),
            "ERR_UNRESOLVED_MANDATORY_COMMENTS",
            409,
        )

        resolved = resolve_comment(
            ctx["comment"]["id"], "ADOPTED", resolution_note="study added"
        )
        second_resolve = api_client.resolve_comment(
            ctx["comment"]["id"],
            {"disposition": "REJECTED", "resolution_note": "changed our mind"},
            LICENSEE_HEADERS,
        )
        approved = decide_plan(ctx["plan"]["id"], "APPROVE")

        assert resolved["resolution_status"] == "RESOLVED"
        assert resolved["disposition"] == "ADOPTED"
        validate_error(second_resolve, "ERR_COMMENT_ALREADY_RESOLVED", 409)
        assert read_comment(ctx["comment"]["id"])["disposition"] == "ADOPTED"
        assert approved["status"] == "APPROVED"
        assert approved["approved_at"].startswith("2026-08-01T00:00:00")
        assert_plan_counters(
            approved, open_comment_count=0, unresolved_mandatory_comment_count=0
        )
        project = read_project(ctx["project"]["id"])
        assert project["unresolved_mandatory_comment_count"] == 0
        assert_postures(project, regulatory_posture="OPEN")


class TestPrerequisiteAcyclicity:
    def _two_measures_where_the_second_depends_on_the_first(self):
        ctx = setup_study_phase_project(
            project_name="Cycle Reach",
            installed_capacity_mw=24.0,
            base_annual_generation_mwh=250000,
            license_expiration_date="2035-06-30",
        )
        project_id = ctx["project"]["id"]
        ctx["root"] = new_measure(
            project_id,
            source="AGENCY_PRESCRIPTION",
            measure_name="Upstream collector",
            resource_category="FISH_PASSAGE",
            implementation_months=6,
        )
        ctx["dependent"] = new_measure(
            project_id,
            source="AGENCY_PRESCRIPTION",
            prerequisite_measure_id=ctx["root"]["id"],
            measure_name="Downstream bypass",
            resource_category="FISH_PASSAGE",
            implementation_months=9,
        )
        return ctx

    def test_a_back_edge_and_a_self_reference_are_both_refused_on_amendment(self):
        """The acyclicity check runs on the amend path and leaves the graph as it found it.

        PRD §2.12: "31. `prerequisite_measure_id` belongs to the same project and closes no cycle in the prerequisite graph — `ERR_PREREQUISITE_CYCLE` (422), on measure creation and measure amendment."
        PRD §3.7: "An amendment re-runs the measure calculation under the measure's *current* `cost_estimate_variant` rather than resetting the variant, rejects a `prerequisite_measure_id` that would close a cycle with `ERR_PREREQUISITE_CYCLE`, recomputes the project burden ledger and `regulatory_posture` when the measure is `INCLUDED`, and increments the measure's `version`."

        Design: Corner/validations/prerequisite_cycle_and_self_reference_rejected
        """
        ctx = self._two_measures_where_the_second_depends_on_the_first()
        root, dependent = ctx["root"], ctx["dependent"]
        assert root["prerequisite_measure_id"] is None
        assert dependent["prerequisite_measure_id"] == root["id"]

        back_edge = api_client.patch_measure(
            root["id"], {"prerequisite_measure_id": dependent["id"]}, LICENSEE_HEADERS
        )
        self_edge = api_client.patch_measure(
            dependent["id"],
            {"prerequisite_measure_id": dependent["id"]},
            LICENSEE_HEADERS,
        )

        validate_error(back_edge, "ERR_PREREQUISITE_CYCLE", 422)
        validate_error(self_edge, "ERR_PREREQUISITE_CYCLE", 422)
        assert read_measure(root["id"])["prerequisite_measure_id"] is None
        assert read_measure(dependent["id"])["version"] == dependent["version"]

    def test_an_unrelated_rename_of_the_dependent_measure_still_goes_through(self):
        """The two rejections cost the measure nothing and the next amendment bumps it once.

        PRD §3.7: "The amendable fields are `measure_name`, `capital_cost_usd`, `annual_om_cost_usd`, `construction_start_year`, `implementation_months`, `flow_release_cfs`, `gross_head_ft`, `release_days` and `prerequisite_measure_id`."

        Design: Corner/validations/prerequisite_cycle_and_self_reference_rejected
        """
        ctx = self._two_measures_where_the_second_depends_on_the_first()
        root, dependent = ctx["root"], ctx["dependent"]
        validate_error(
            api_client.patch_measure(
                root["id"],
                {"prerequisite_measure_id": dependent["id"]},
                LICENSEE_HEADERS,
            ),
            "ERR_PREREQUISITE_CYCLE",
            422,
        )
        validate_error(
            api_client.patch_measure(
                dependent["id"],
                {"prerequisite_measure_id": dependent["id"]},
                LICENSEE_HEADERS,
            ),
            "ERR_PREREQUISITE_CYCLE",
            422,
        )

        renamed = validate_success(
            api_client.patch_measure(
                dependent["id"],
                {"measure_name": "Downstream bypass and screen"},
                LICENSEE_HEADERS,
            )
        )

        assert renamed["measure_name"] == "Downstream bypass and screen"
        assert renamed["version"] == dependent["version"] + 1
        assert renamed["prerequisite_measure_id"] == root["id"]


class TestPreApplicationDeadlineAndFreeze:
    def _project_whose_stored_posture_has_gone_stale(self):
        set_clock("2026-08-01T00:00:00Z")
        project = new_project(
            license_number="P-9039",
            project_name="Missed Deadline Reach",
            installed_capacity_mw=9.0,
            base_annual_generation_mwh=50000,
            license_expiration_date="2033-12-31",
        )
        assert_postures(
            project, timeline_posture="ON_TRACK", regulatory_posture="OPEN"
        )
        set_clock("2028-07-01T00:00:00Z")
        return project

    def test_a_day_past_the_deadline_the_filing_answers_with_the_deadline_code(self):
        """The deadline rule reads the live clock while the stored posture is still open.

        PRD §3.2: "The operation is permitted only while `stage` is `PRE_FILING`, so a second filing attempt is rejected with `ERR_PROJECT_STAGE_INVALID`, and only while the logical clock's date is on or before the pre-application deadline — 66 months before `license_expiration_date` — with a late attempt rejected as `ERR_FILING_DEADLINE_PASSED`."
        PRD §2.7: "The posture is persisted on the project with an initial value of `ON_TRACK`, and it is refreshed at exactly four moments: when a project is registered, when the pre-application document is filed, when a license application is filed, and when the compliance sweep runs."

        Design: Corner/validations/pad_filed_after_the_due_date_rejected_then_the_sweep_freezes_the_project
        """
        project = self._project_whose_stored_posture_has_gone_stale()

        response = api_client.file_pre_application_document(
            project["id"], {"filing_note": "late PAD"}, LICENSEE_HEADERS
        )

        validate_error(response, "ERR_FILING_DEADLINE_PASSED", 409)
        stale = read_project(project["id"])
        assert stale["stage"] == "PRE_FILING"
        assert_postures(stale, timeline_posture="ON_TRACK", regulatory_posture="OPEN")
        assert stale["pad_filed_at"] is None
        assert stale["pad_year"] is None

    def test_the_sweep_freezes_the_project_and_the_freeze_answers_first(self):
        """Refreshing the posture moves the higher rule in front of the deadline rule.

        PRD §2.12: "15. The project's `regulatory_posture` is not `FROZEN` — `ERR_PROJECT_POSTURE_FROZEN` (409), on every licensee-initiated or agency-initiated mutation of a project or a child of a project, other than the five cure paths named in §2.8."
        PRD §2.8: "The posture is `FROZEN` when any of the following holds: the project's `wqc_status` is `DENIED`, or its `compliance_flag_count` is greater than zero, or its `timeline_posture` is `DELINQUENT`."

        Design: Corner/validations/pad_filed_after_the_due_date_rejected_then_the_sweep_freezes_the_project
        """
        project = self._project_whose_stored_posture_has_gone_stale()
        validate_error(
            api_client.file_pre_application_document(
                project["id"], {"filing_note": "late PAD"}, LICENSEE_HEADERS
            ),
            "ERR_FILING_DEADLINE_PASSED",
            409,
        )

        swept = run_sweep(project["id"])
        response = api_client.file_pre_application_document(
            project["id"], {"filing_note": "late PAD again"}, LICENSEE_HEADERS
        )

        assert_postures(
            swept, timeline_posture="DELINQUENT", regulatory_posture="FROZEN"
        )
        validate_error(response, "ERR_PROJECT_POSTURE_FROZEN", 409)
        never_filed = read_project(project["id"])
        assert never_filed["pad_filed_at"] is None
        assert never_filed["pad_year"] is None


class TestSingleOutstandingCertificationRequest:
    def test_a_second_request_is_refused_and_the_first_one_stands(self):
        """One certification request at a time, and the loser leaves no trace.

        PRD §2.12: "14. A project holds at most one water-quality certification in `REQUESTED` status, and a certification may be requested only while the project's `stage` is `STUDY_PHASE`, `APPLICATION_FILED` or `UNDER_ENVIRONMENTAL_REVIEW` — `ERR_WQC_STATE_INVALID` (409)."
        PRD §3.6: "A request is permitted only while the project's `stage` is `STUDY_PHASE`, `APPLICATION_FILED` or `UNDER_ENVIRONMENTAL_REVIEW`, and only while the project holds no other certification already in `REQUESTED` status; either violation is rejected with `ERR_WQC_STATE_INVALID`."

        Design: Corner/validations/second_requested_certification_rejected
        """
        ctx = setup_study_phase_project(
            project_name="Double WQC Reach", **SMALL_PROJECT
        )
        project_id = ctx["project"]["id"]
        first = request_certification(project_id, certifying_agency_name="State DEQ")
        assert first["status"] == "REQUESTED"

        response = api_client.create_water_quality_certification(
            water_quality_certification_payload(
                project_id, certifying_agency_name="State DEQ Region 2"
            ),
            LICENSEE_HEADERS,
        )

        validate_error(response, "ERR_WQC_STATE_INVALID", 409)
        rows, meta = validate_paginated(
            api_client.list_water_quality_certifications(
                REGULATOR_HEADERS, params={"project_id": project_id, "limit": 100}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]
        assert rows[0]["certifying_agency_name"] == "State DEQ"
        assert read_project(project_id)["wqc_status"] == "REQUESTED"


class TestAnnualReportPeriodWindow:
    def _licensed_project_with_one_article_due_next_february(self):
        ctx = setup_licensed_project(
            order_number="ORD-9041",
            project_name="Report Period Dam",
            installed_capacity_mw=24.0,
            base_annual_generation_mwh=250000,
            license_expiration_date="2035-06-30",
        )
        assert ctx["order"]["effective_date"] == "2026-08-01"
        assert ctx["order"]["article_count"] == 1
        ctx["article"] = obligation_of_type(ctx["obligations"], "PME_IMPLEMENTATION")
        assert ctx["article"]["due_date"] == "2027-02-01"
        return ctx

    def test_a_calendar_period_that_has_not_started_is_refused(self):
        """January 2027 is still in the future, so the 2027 report cannot be filed.

        PRD §3.9: "A report whose window has not yet started, meaning its period start is later than the logical clock's date, is rejected with `ERR_REPORT_PERIOD_INVALID`, as is a second report for the same basis and the same `period_year` on the same order."
        PRD §3.9: "Under `CALENDAR`, the window runs from the first of January of `period_year` through the thirty-first of December of `period_year`."

        Design: Corner/validations/annual_report_for_a_period_that_has_not_started_rejected
        """
        ctx = self._licensed_project_with_one_article_due_next_february()

        response = api_client.file_annual_report(
            ctx["order"]["id"],
            annual_report_payload("CALENDAR", 2027, report_note="next year"),
            LICENSEE_HEADERS,
        )

        validate_error(response, "ERR_REPORT_PERIOD_INVALID", 409)
        order = read_order(ctx["order"]["id"])
        assert order["compliance_state"] == "EFFECTIVE"
        assert order["open_violation_count"] == 0
        assert order["version"] == ctx["order"]["version"]

    def test_the_same_basis_and_year_may_be_filed_only_once(self):
        """The 2026 calendar window is empty, scores 100.00 and closes to repeats.

        PRD §3.9: "A report whose window has not yet started, meaning its period start is later than the logical clock's date, is rejected with `ERR_REPORT_PERIOD_INVALID`, as is a second report for the same basis and the same `period_year` on the same order."
        PRD §3.9: "`compliance_score` is 100 multiplied by the assessed count minus the noncompliant count, divided by the assessed count, rounded half up to two decimal places; when the assessed count is zero the score is exactly 100.00, never 0.00."

        Design: Corner/validations/annual_report_for_a_period_that_has_not_started_rejected
        """
        ctx = self._licensed_project_with_one_article_due_next_february()

        first = file_annual_report(ctx["order"]["id"], "CALENDAR", 2026)
        repeat = api_client.file_annual_report(
            ctx["order"]["id"],
            annual_report_payload("CALENDAR", 2026, report_note="same pair again"),
            LICENSEE_HEADERS,
        )

        assert first["assessed_obligation_count"] == 0
        assert first["noncompliant_obligation_count"] == 0
        assert first["compliance_score"] == pytest.approx(100.00, abs=0.01)
        assert first["compliance_state"] == "EFFECTIVE"
        assert first["last_report_basis"] == "CALENDAR"
        validate_error(repeat, "ERR_REPORT_PERIOD_INVALID", 409)
        assert read_order(ctx["order"]["id"])["last_report_period_year"] == 2026

    def test_the_other_basis_for_the_same_year_is_still_open_and_catches_the_article(
        self,
    ):
        """The anniversary window reaches into 2027 and flags the pending article.

        PRD §3.9: "Under `LICENSE_ANNIVERSARY`, the window starts on the month and day of the order's `effective_date` in `period_year` and runs to the day before the next anniversary — that is, the start date plus 12 months, minus one day."
        PRD §3.9: "A report with a `noncompliant_obligation_count` greater than zero moves the order `EFFECTIVE → COMPLIANCE_FLAGGED`, incrementing the order's `version`, which recomputes the project's `compliance_flag_count` and thence `regulatory_posture` to `FROZEN`, which in turn suspends the project's pending applications as described in §3.8."

        Design: Corner/validations/annual_report_for_a_period_that_has_not_started_rejected
        """
        ctx = self._licensed_project_with_one_article_due_next_february()
        file_annual_report(ctx["order"]["id"], "CALENDAR", 2026)

        anniversary = file_annual_report(
            ctx["order"]["id"], "LICENSE_ANNIVERSARY", 2026
        )

        assert anniversary["assessed_obligation_count"] == 1
        assert anniversary["noncompliant_obligation_count"] == 1
        assert anniversary["compliance_score"] == pytest.approx(0.00, abs=0.01)
        assert anniversary["last_report_basis"] == "LICENSE_ANNIVERSARY"
        assert anniversary["compliance_state"] == "COMPLIANCE_FLAGGED"
        project = read_project(ctx["project"]["id"])
        assert project["compliance_flag_count"] == 1
        assert_postures(project, regulatory_posture="FROZEN")
