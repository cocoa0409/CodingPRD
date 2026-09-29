"""Error taxonomy: per-entity not-found codes, body-shape refusals and the filing prerequisite ladder."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    U_LICENSEE_A,
    U_TRIBE,
    advance_environmental_review,
    api_client,
    application_payload,
    assert_ledger_matches,
    assert_postures,
    certify_with_conditions,
    decide_plan,
    decide_study_review,
    deny_certification,
    file_application,
    file_pad,
    issue_order,
    list_measures,
    list_obligations,
    make_licensee_headers,
    move_fieldwork,
    new_project,
    new_study,
    new_study_plan,
    party_payload,
    project_version,
    read_measure,
    read_project,
    read_settlement,
    read_study,
    record_definitive_estimate,
    report_study,
    request_certification,
    set_clock,
    settlement_payload,
    setup_agency_party,
    setup_approved_study_plan,
    setup_circulated_settlement,
    setup_study_phase_project,
    sign_roster,
    submit_plan,
    tally_settlement,
    validate_error,
    validate_paginated,
    validate_success,
)

REGULATOR_HEADERS = TEST_USERS["regulator_headers"]
LICENSEE_HEADERS = make_licensee_headers(U_LICENSEE_A)
STATE_CERTIFIER_HEADERS = TEST_USERS["state_certifier_headers"]
MID_SIZED_PROJECT = dict(
    installed_capacity_mw=12.0,
    base_annual_generation_mwh=250000,
    license_expiration_date="2035-06-30",
)
TRIBE_PARTY = dict(
    party_name="River Tribe",
    party_type="TRIBE",
    vote_weight=1,
    contact_user_id=U_TRIBE,
)
SETTLEMENT_FISHWAY = dict(
    measure_name="Upstream fishway",
    resource_category="FISH_PASSAGE",
    capital_cost_usd=600000.00,
    annual_om_cost_usd=20000.00,
    construction_start_year=2026,
    implementation_months=12,
    flow_release_cfs=40,
    gross_head_ft=60,
    release_days=120,
)
RECREATION_STUDY = dict(
    resource_category="RECREATION", study_title="Recreation use survey"
)
FIRST_SITE = dict(site_code="S1", river_mile=1.0)


class TestPerEntityNotFoundCodes:
    def test_one_unknown_identifier_answers_with_a_distinct_code_per_collection(self):
        """The same absent id read through every collection never shares a code.

        PRD §2.10: "First, identifiers that appear in the URL are resolved left to right, and the first identifier that names no existing row decides the response: a request naming `project_id`, `dam_id`, `site_id`, `study_plan_id`, `study_id`, `comment_id`, `party_id`, `settlement_id`, `signature_id`, `wqc_id`, `measure_id`, `application_id`, `obligation_id` or `order_id` that resolves to nothing is answered with that entity's not-found code — `ERR_PROJECT_NOT_FOUND`, `ERR_DAM_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_STUDY_PLAN_NOT_FOUND`, `ERR_STUDY_NOT_FOUND`, `ERR_COMMENT_NOT_FOUND`, `ERR_PARTY_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_WQC_NOT_FOUND`, `ERR_MEASURE_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_OBLIGATION_NOT_FOUND` or `ERR_ORDER_NOT_FOUND` respectively — all at HTTP 404."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

        Design: Corner/errors/unknown_ids_return_entity_specific_not_found_codes
        """
        set_clock("2026-08-01T00:00:00Z")

        lookups = [
            (api_client.get_project, "ERR_PROJECT_NOT_FOUND"),
            (api_client.get_dam, "ERR_DAM_NOT_FOUND"),
            (api_client.get_site, "ERR_SITE_NOT_FOUND"),
            (api_client.get_study_plan, "ERR_STUDY_PLAN_NOT_FOUND"),
            (api_client.get_study, "ERR_STUDY_NOT_FOUND"),
            (api_client.get_comment, "ERR_COMMENT_NOT_FOUND"),
            (api_client.get_party, "ERR_PARTY_NOT_FOUND"),
            (api_client.get_settlement, "ERR_SETTLEMENT_NOT_FOUND"),
            (
                api_client.get_water_quality_certification,
                "ERR_WQC_NOT_FOUND",
            ),
            (api_client.get_measure, "ERR_MEASURE_NOT_FOUND"),
            (api_client.get_application, "ERR_APPLICATION_NOT_FOUND"),
            (api_client.get_order, "ERR_ORDER_NOT_FOUND"),
            (api_client.get_obligation, "ERR_OBLIGATION_NOT_FOUND"),
        ]
        seen = []
        for read_one, expected_error_id in lookups:
            response = read_one(NON_EXISTENT_UUID, REGULATOR_HEADERS)
            validate_error(response, expected_error_id, 404)
            body = response.json()
            assert body["response_type"] == "error"
            assert isinstance(body["data"]["message"], str)
            assert body["data"]["message"] != ""
            seen.append(body["data"]["error_id"])

        assert len(set(seen)) == len(lookups)


class TestOrderIssuanceNeedsADecidedCertification:
    def test_a_certification_still_awaiting_the_state_blocks_the_license(self):
        """Final environmental review passes on an empty condition set, then the order does not.

        PRD §3.8: "And the project's `wqc_status` must be `CERTIFIED_WITH_CONDITIONS` or `WAIVED`, so that the state's conditions are actually reflected in the license; a `wqc_status` still reading `REQUESTED` is rejected with `ERR_WQC_CONDITION_NOT_INCORPORATED`."
        PRD §3.8: "A `target_stage` of `FINAL_EA` moves `ea_stage` `DRAFT_EA → FINAL_EA`, requires `filing_status` to be `UNDER_REVIEW`, and imposes one cross-entity condition: every measure of the project whose `source` is `WQC_CONDITION` must carry a `cost_estimate_variant` of `DEFINITIVE`."

        Design: Corner/errors/order_issuance_with_a_requested_certification_rejected
        """
        ctx = setup_approved_study_plan(
            study_overrides=RECREATION_STUDY,
            site_overrides=FIRST_SITE,
            project_name="Undecided Reach",
            **MID_SIZED_PROJECT,
        )
        project_id = ctx["project"]["id"]
        wqc = request_certification(project_id)
        assert wqc["status"] == "REQUESTED"
        application = file_application(project_id)
        for stage in ("SCOPING", "DRAFT_EA", "FINAL_EA"):
            application = advance_environmental_review(application["id"], stage)
        assert application["ea_stage"] == "FINAL_EA"

        refused = api_client.issue_order(
            application["id"], {"order_number": "ORD-9047"}, REGULATOR_HEADERS
        )

        validate_error(refused, "ERR_WQC_CONDITION_NOT_INCORPORATED", 422)
        unchanged = validate_success(
            api_client.get_application(application["id"], REGULATOR_HEADERS)
        )
        assert unchanged["filing_status"] == "UNDER_REVIEW"
        assert unchanged["ea_stage"] == "FINAL_EA"
        project = read_project(project_id)
        assert project["stage"] == "UNDER_ENVIRONMENTAL_REVIEW"
        assert project["wqc_status"] == "REQUESTED"
        _orders, meta = validate_paginated(
            api_client.list_orders(REGULATOR_HEADERS, params={"limit": 100})
        )
        assert meta["total_count"] == 0


class TestSettlementFrozenIntoTheLicense:
    def _licensed_project_built_on_an_executed_settlement(self):
        ctx = setup_circulated_settlement(
            party_specs=[TRIBE_PARTY],
            settlement_measures=[SETTLEMENT_FISHWAY],
            study_overrides=RECREATION_STUDY,
            site_overrides=FIRST_SITE,
            project_name="Licensed Reach",
            **MID_SIZED_PROJECT,
        )
        project_id = ctx["project"]["id"]
        settlement_id = ctx["settlement"]["id"]
        agency_party, tribe_party = ctx["parties"]
        assert ctx["measures"][0]["status"] == "PROPOSED"

        sign_roster(settlement_id, [(agency_party, "SUPPORT"), (tribe_party, "SUPPORT")])
        executed = tally_settlement(settlement_id, "EXECUTE")
        assert executed["status"] == "EXECUTED"
        assert executed["support_pct"] == pytest.approx(100.00, abs=0.01)
        assert executed["included_measure_count"] == 1
        assert_ledger_matches(
            read_project(project_id),
            total_pme_annual_cost_usd=45000.00,
            total_generation_loss_mwh=230.4,
            administrative_annual_charge_usd=900.00,
            total_annual_burden_usd=55576.80,
            burden_ratio_pct=0.53,
        )

        wqc = request_certification(project_id)
        certify_with_conditions(wqc["id"])
        condition_measure = list_measures(project_id, source="WQC_CONDITION")[0]
        record_definitive_estimate(condition_measure["id"])

        application = file_application(project_id)
        for stage in ("SCOPING", "DRAFT_EA", "FINAL_EA"):
            application = advance_environmental_review(application["id"], stage)
        order = issue_order(application["id"], "ORD-9048")
        assert order["compliance_state"] == "EFFECTIVE"
        assert order["effective_date"] == "2026-08-01"
        assert order["article_count"] == 2
        ctx.update(
            {
                "settlement_measure": ctx["measures"][0],
                "condition_measure": condition_measure,
                "application": application,
                "order": order,
            }
        )
        return ctx

    def test_the_executed_settlement_cannot_be_unwound_once_the_order_is_effective(self):
        """The withdrawal is refused and every included measure keeps its place in the ledger.

        PRD §3.5: "Withdrawal is the compensating action for execution, and it is deliberately hard. It moves an `EXECUTED` settlement to `WITHDRAWN`, requires a `withdrawal_reason` in the body, and is permitted only while no license order of the project has a `compliance_state` of `EFFECTIVE` or `COMPLIANCE_FLAGGED` — once a license is live, its settlement cannot be unwound, and the attempt is rejected with `ERR_ORDER_STATE_INVALID`."
        PRD §3.7: "The live set is every measure of the project whose status is `INCLUDED` or `IMPLEMENTED`; measures in `PROPOSED`, `WITHDRAWN` or `SUPERSEDED` are excluded."

        Design: Corner/errors/settlement_withdrawal_after_the_license_issues_rejected
        """
        ctx = self._licensed_project_built_on_an_executed_settlement()
        project_id = ctx["project"]["id"]

        refused = api_client.withdraw_settlement(
            ctx["settlement"]["id"],
            {"withdrawal_reason": "party wants out after the license issued"},
            LICENSEE_HEADERS,
        )

        validate_error(refused, "ERR_ORDER_STATE_INVALID", 409)
        settlement = read_settlement(ctx["settlement"]["id"])
        assert settlement["status"] == "EXECUTED"
        assert settlement["included_measure_count"] == 1
        assert settlement["withdrawn_at"] is None
        assert read_measure(ctx["settlement_measure"]["id"])["status"] == "INCLUDED"
        project = read_project(project_id)
        assert project["stage"] == "LICENSED"
        assert_ledger_matches(
            project,
            total_pme_annual_cost_usd=98000.00,
            total_generation_loss_mwh=728.3,
            administrative_annual_charge_usd=1960.00,
            total_annual_burden_usd=130548.60,
            burden_ratio_pct=1.24,
        )
        obligations = list_obligations(ctx["order"]["id"])
        due_dates = sorted(o["due_date"] for o in obligations)
        assert due_dates == ["2027-02-01", "2027-08-01"]
        assert all(o["status"] == "PENDING" for o in obligations)

    def test_no_replacement_settlement_may_be_opened_beside_the_executed_one(self):
        """A correct version pin does not help: the executed settlement holds the slot.

        PRD §3.5: "Opening a settlement while the project already has one in `EXECUTED` status is rejected with `ERR_SETTLEMENT_STATE_INVALID`."
        PRD §2.11: "Opening a settlement — the create at `POST /relicensing/settlements` — must carry `expected_project_version` matching the target project's current `version`."

        Design: Corner/errors/settlement_withdrawal_after_the_license_issues_rejected
        """
        ctx = self._licensed_project_built_on_an_executed_settlement()
        project_id = ctx["project"]["id"]

        refused = api_client.create_settlement(
            settlement_payload(
                project_id,
                project_version(project_id),
                title="Replacement settlement",
            ),
            LICENSEE_HEADERS,
        )

        validate_error(refused, "ERR_SETTLEMENT_STATE_INVALID", 409)
        _rows, meta = validate_paginated(
            api_client.list_settlements(REGULATOR_HEADERS, params={"limit": 100})
        )
        assert meta["total_count"] == 1
        assert read_settlement(ctx["settlement"]["id"])["status"] == "EXECUTED"


class TestCertificationDecisionShape:
    def _certification_awaiting_the_state(self):
        set_clock("2026-08-01T00:00:00Z")
        project = new_project(
            license_number="P-9049", project_name="Shape Reach", **MID_SIZED_PROJECT
        )
        file_pad(project["id"])
        new_study_plan(project["id"])
        wqc = request_certification(project["id"])
        assert wqc["status"] == "REQUESTED"
        return {"project": project, "wqc": wqc}

    def test_each_branch_of_the_decision_demands_its_own_half_of_the_body(self):
        """An empty condition array and a reasonless denial are both shape failures.

        PRD §3.6: "A `decision` of `ISSUE_WITH_CONDITIONS` moves the certification `REQUESTED → CERTIFIED_WITH_CONDITIONS` and requires the `conditions` array to be non-empty, rejecting an empty or absent array with `ERR_INVALID_REQUEST`."
        PRD §3.6: "A `decision` of `DENY` moves the certification `REQUESTED → DENIED` and requires a non-empty `denial_reason`, rejecting an empty or absent one with `ERR_INVALID_REQUEST`."

        Design: Corner/errors/certification_decision_and_party_payload_shape_rejected
        """
        ctx = self._certification_awaiting_the_state()
        wqc_id = ctx["wqc"]["id"]

        empty_conditions = api_client.decide_water_quality_certification(
            wqc_id,
            {"decision": "ISSUE_WITH_CONDITIONS", "conditions": []},
            STATE_CERTIFIER_HEADERS,
        )
        reasonless_denial = api_client.decide_water_quality_certification(
            wqc_id, {"decision": "DENY"}, STATE_CERTIFIER_HEADERS
        )

        validate_error(empty_conditions, "ERR_INVALID_REQUEST", 400)
        validate_error(reasonless_denial, "ERR_INVALID_REQUEST", 400)
        undecided = validate_success(
            api_client.get_water_quality_certification(wqc_id, REGULATOR_HEADERS)
        )
        assert undecided["status"] == "REQUESTED"
        assert undecided["condition_count"] == 0
        assert undecided["decided_at"] is None
        _measures, meta = validate_paginated(
            api_client.list_measures(REGULATOR_HEADERS, params={"limit": 100})
        )
        assert meta["total_count"] == 0
        project = read_project(ctx["project"]["id"])
        assert project["wqc_status"] == "REQUESTED"

    def test_conditioning_authority_belongs_to_agencies_and_the_denial_then_freezes(self):
        """A tribe claiming conditioning authority is refused; the well-formed denial lands.

        PRD §3.5: "Three optional inputs complete the registration: `has_conditioning_authority` defaults to false and may be set true only for a party whose `party_type` is `AGENCY`, with any other combination rejected as `ERR_INVALID_REQUEST`; `vote_weight` defaults to 1 and must be at least 1; and `contact_user_id` binds the `X-User-ID` of the party's agency-reviewer or stakeholder user to this party row."
        PRD §3.6: "The project's `wqc_status` becomes `DENIED`, which by itself drives `regulatory_posture` to `FROZEN`."

        Design: Corner/errors/certification_decision_and_party_payload_shape_rejected
        """
        ctx = self._certification_awaiting_the_state()
        project_id = ctx["project"]["id"]

        overreaching_party = api_client.create_party(
            party_payload(
                project_id,
                party_name="River Tribe",
                party_type="TRIBE",
                has_conditioning_authority=True,
                vote_weight=1,
                contact_user_id=U_TRIBE,
            ),
            REGULATOR_HEADERS,
        )

        validate_error(overreaching_party, "ERR_INVALID_REQUEST", 400)
        _parties, meta = validate_paginated(
            api_client.list_parties(REGULATOR_HEADERS, params={"limit": 100})
        )
        assert meta["total_count"] == 0

        denied = deny_certification(
            ctx["wqc"]["id"], denial_reason="state standards cannot be met"
        )

        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "state standards cannot be met"
        assert denied["decided_at"].startswith("2026-08-01T00:00:00")
        project = read_project(project_id)
        assert project["wqc_status"] == "DENIED"
        assert_postures(project, regulatory_posture="FROZEN")


class TestFilingPrerequisiteLadder:
    def _approved_plan_whose_study_is_still_unreviewed(self):
        ctx = setup_study_phase_project(
            sites=[FIRST_SITE], project_name="Ladder Reach", **MID_SIZED_PROJECT
        )
        plan_id = ctx["plan"]["id"]
        study = new_study(
            plan_id,
            ctx["sites"][0]["id"],
            resource_category="WATER_QUALITY",
            study_title="Dissolved oxygen monitoring",
        )
        submit_plan(plan_id)
        setup_agency_party(ctx["project"]["id"])
        plan = decide_plan(plan_id, "APPROVE")
        assert plan["status"] == "APPROVED"
        assert study["review_status"] == "NOT_SUBMITTED"
        ctx.update({"plan": plan, "study": study})
        return ctx

    def _filing_attempt(self, project_id, filing_note):
        return api_client.create_application(
            application_payload(
                project_id, project_version(project_id), filing_note=filing_note
            ),
            LICENSEE_HEADERS,
        )

    def test_the_prerequisites_are_repaired_one_rung_at_a_time(self):
        """An unaccepted study answers first, then a certification that was never requested.

        PRD §3.8: "Every resource study of that approved plan must have `review_status` `ACCEPTED`, or `ERR_STUDY_NOT_ACCEPTED`. The project's `wqc_status` must be something other than `NONE` — `REQUESTED`, `CERTIFIED_WITH_CONDITIONS` or `WAIVED` all suffice at this stage — or `ERR_WQC_STATE_INVALID`."
        PRD §3.8: "On success the project's `stage` advances `STUDY_PHASE → APPLICATION_FILED`, `application_filed_at` is stamped from the logical clock, `timeline_posture` is recomputed — with both milestone timestamps now set, no milestone remains outstanding and the posture becomes `ON_TRACK` — and `regulatory_posture` is recomputed."

        Design: Corner/errors/application_filing_before_study_acceptance_and_certification_rejected
        """
        ctx = self._approved_plan_whose_study_is_still_unreviewed()
        project_id = ctx["project"]["id"]
        study_id = ctx["study"]["id"]
        assert read_project(project_id)["wqc_status"] == "NONE"

        too_early = self._filing_attempt(project_id, "too early")

        validate_error(too_early, "ERR_STUDY_NOT_ACCEPTED", 409)

        move_fieldwork(study_id, "START")
        move_fieldwork(study_id, "COMPLETE")
        report_study(study_id)
        accepted = decide_study_review(study_id, "ACCEPT")
        still_too_early = self._filing_attempt(project_id, "still too early")

        assert accepted["review_status"] == "ACCEPTED"
        validate_error(still_too_early, "ERR_WQC_STATE_INVALID", 409)
        assert read_project(project_id)["stage"] == "STUDY_PHASE"

        request_certification(project_id)
        filed = validate_success(
            self._filing_attempt(project_id, "relicense application"), 201
        )

        assert filed["filing_status"] == "FILED"
        assert filed["pinned_study_plan_id"] == ctx["plan"]["id"]
        project = read_project(project_id)
        assert project["stage"] == "APPLICATION_FILED"
        assert project["application_filed_at"].startswith("2026-08-01T00:00:00")
        assert read_study(study_id)["review_status"] == "ACCEPTED"
