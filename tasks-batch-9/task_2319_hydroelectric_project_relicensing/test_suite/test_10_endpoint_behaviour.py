"""Endpoint behaviour: project amendment, signature linkage, the sweep checkpoint, cures and fieldwork actions."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    U_LICENSEE_A,
    U_TRIBE,
    api_client,
    assert_ledger_matches,
    assert_postures,
    circulate_settlement,
    make_licensee_headers,
    new_project,
    new_settlement,
    patch_project,
    raise_deficiency,
    read_application,
    read_project,
    read_study,
    register_party,
    report_study,
    request_certification,
    run_sweep,
    set_clock,
    setup_agency_party,
    setup_application_under_review,
    setup_plan_under_agency_review,
    setup_study_phase_project,
    sign_settlement,
    validate_error,
    validate_paginated,
    validate_success,
)

REGULATOR_HEADERS = TEST_USERS["regulator_headers"]
LICENSEE_HEADERS = make_licensee_headers(U_LICENSEE_A)
AGENCY_HEADERS = TEST_USERS["agency_reviewer_headers"]
MID_SIZED_PROJECT = dict(
    installed_capacity_mw=12.0,
    base_annual_generation_mwh=250000,
    license_expiration_date="2035-06-30",
)


class TestProjectAmendment:
    def _registry_entry_with_an_empty_ledger(self):
        set_clock("2026-08-01T00:00:00Z")
        project = new_project(
            license_number="P-9042", project_name="Patch Reach", **MID_SIZED_PROJECT
        )
        assert project["version"] == 1
        return project

    def test_a_rename_bumps_the_version_and_leaves_the_ledger_alone(self):
        """The registry's one amendment endpoint takes each of its fields on its own.

        PRD §3.1: "The `Regulator` may later amend three fields of a project: `project_name`, `base_annual_generation_mwh` and `infeasibility_waiver_granted`."
        PRD §3.1: "Its `pad_filed_at`, `pad_year` and `application_filed_at` are all unset, and its entire burden ledger — `total_pme_annual_cost_usd`, `total_generation_loss_mwh`, `administrative_annual_charge_usd`, `total_annual_burden_usd` and `burden_ratio_pct` — reads zero with `economically_infeasible` false."

        Design: Corner/endpoints/project_patch_updates_the_name_and_bumps_the_version
        """
        project = self._registry_entry_with_an_empty_ledger()

        renamed = patch_project(project["id"], project_name="Patch Reach Renamed")

        assert renamed["project_name"] == "Patch Reach Renamed"
        assert renamed["version"] == 2
        assert renamed["license_number"] == "P-9042"
        assert_ledger_matches(
            renamed,
            total_pme_annual_cost_usd=0.00,
            total_generation_loss_mwh=0.0,
            administrative_annual_charge_usd=0.00,
            total_annual_burden_usd=0.00,
            burden_ratio_pct=0.00,
        )

    def test_amending_the_generation_baseline_and_the_waiver_re_runs_the_ledger(self):
        """Two ledger inputs move in one request and a read afterwards bumps nothing.

        PRD §3.1: "Changing either of the latter two re-runs the burden ledger and then the regulatory posture, because both are ledger inputs; every amendment increments the project's `version`."
        PRD §2.9: "There is no lazy reconciliation and no background job: by the time a response is emitted, every counter, ledger figure and posture affected by the request already reflects the new reality."

        Design: Corner/endpoints/project_patch_updates_the_name_and_bumps_the_version
        """
        project = self._registry_entry_with_an_empty_ledger()
        patch_project(project["id"], project_name="Patch Reach Renamed")

        amended = patch_project(
            project["id"],
            base_annual_generation_mwh=500000,
            infeasibility_waiver_granted=True,
        )

        assert amended["base_annual_generation_mwh"] == 500000
        assert amended["infeasibility_waiver_granted"] is True
        assert amended["version"] == 3
        assert amended["burden_ratio_pct"] == pytest.approx(0.00, abs=0.01)
        assert amended["economically_infeasible"] is False
        assert_postures(amended, regulatory_posture="OPEN")
        after_read = read_project(project["id"])
        assert after_read["project_name"] == "Patch Reach Renamed"
        assert after_read["license_number"] == "P-9042"
        assert after_read["version"] == 3


class TestSignatureLinkage:
    def _circulated_settlement_with_an_agency_and_a_tribal_party(self):
        ctx = setup_study_phase_project(
            sites=[dict(site_code="S1", river_mile=1.0)],
            project_name="Signature Link Reach",
            **MID_SIZED_PROJECT,
        )
        project_id = ctx["project"]["id"]
        ctx["agency_party"] = setup_agency_party(project_id)
        ctx["tribe_party"] = register_party(
            project_id,
            party_name="River Tribe",
            party_type="TRIBE",
            vote_weight=1,
            contact_user_id=U_TRIBE,
        )
        settlement = new_settlement(project_id)
        ctx["settlement"] = circulate_settlement(settlement["id"])
        return ctx

    def test_the_junction_row_names_an_existing_settlement_and_an_existing_party(self):
        """Both halves of the link are resolved before any signature is written.

        PRD §2.10: "Second, every reference supplied in a request body is resolved the same way and yields the same not-found code for the referenced entity."
        PRD §3.5: "While a settlement is `CIRCULATED`, an `AgencyReviewer` or `Stakeholder` records a **SettlementSignature** by naming the `settlement_id`, its own `party_id` — which must equal the acting `X-User-ID` — and a `position` of `SUPPORT`, `OPPOSE` or `ABSTAIN`."

        Design: Corner/endpoints/signature_links_a_settlement_to_a_party
        """
        ctx = self._circulated_settlement_with_an_agency_and_a_tribal_party()

        unknown_settlement = api_client.create_signature(
            {
                "settlement_id": NON_EXISTENT_UUID,
                "party_id": ctx["agency_party"]["id"],
                "position": "SUPPORT",
            },
            AGENCY_HEADERS,
        )
        unknown_party = api_client.create_signature(
            {
                "settlement_id": ctx["settlement"]["id"],
                "party_id": NON_EXISTENT_UUID,
                "position": "SUPPORT",
            },
            AGENCY_HEADERS,
        )

        validate_error(unknown_settlement, "ERR_SETTLEMENT_NOT_FOUND", 404)
        validate_error(unknown_party, "ERR_PARTY_NOT_FOUND", 404)
        _rows, meta = validate_paginated(
            api_client.list_signatures(REGULATOR_HEADERS, params={"limit": 100})
        )
        assert meta["total_count"] == 0

    def test_the_recorded_position_is_reachable_from_the_party_that_took_it(self):
        """One party's row exists, the other party's does not, and the link points both ways.

        PRD §3.5: "The signature is immutable once written: it copies `round_number` from the settlement's current round, stamps `signed_at` from the logical clock, and leaves `share_pct` unset until the round is tallied."
        PRD §2.10: "Because collections are peers rather than nested, references travel in request bodies."

        Design: Corner/endpoints/signature_links_a_settlement_to_a_party
        """
        ctx = self._circulated_settlement_with_an_agency_and_a_tribal_party()

        signature = sign_settlement(
            ctx["settlement"]["id"], ctx["agency_party"], position="SUPPORT"
        )

        assert signature["round_number"] == 1
        assert signature["position"] == "SUPPORT"
        assert signature["share_pct"] is None
        assert signature["signed_at"].startswith("2026-08-01T00:00:00")
        rows, meta = validate_paginated(
            api_client.list_signatures(REGULATOR_HEADERS, params={"limit": 100})
        )
        assert meta["total_count"] == 1
        assert rows[0]["settlement_id"] == ctx["settlement"]["id"]
        assert rows[0]["party_id"] == ctx["agency_party"]["id"]
        assert rows[0]["party_id"] != ctx["tribe_party"]["id"]
        by_id = validate_success(
            api_client.get_signature(signature["id"], REGULATOR_HEADERS)
        )
        assert by_id["settlement_id"] == ctx["settlement"]["id"]
        assert by_id["party_id"] == ctx["agency_party"]["id"]


class TestComplianceSweepCheckpoint:
    def test_running_the_checkpoint_twice_at_one_clock_changes_nothing_the_second_time(
        self,
    ):
        """The statutory waiver is stamped once and the repeat sweep leaves it alone.

        PRD §3.9: "The sweep is idempotent for a fixed clock value: running it twice without moving the clock changes nothing the second time."
        PRD §3.9: "Second, a water-quality certification of the project still in `REQUESTED` status whose `statutory_waiver_date` the clock has reached or passed moves to `WAIVED` as described in §3.6, with the project's `wqc_status` set to `WAIVED`."

        Design: Corner/endpoints/compliance_sweep_is_idempotent_at_a_fixed_clock
        """
        ctx = setup_study_phase_project(
            project_name="Sweep Reach", **MID_SIZED_PROJECT
        )
        project_id = ctx["project"]["id"]
        wqc = request_certification(project_id)
        assert wqc["statutory_waiver_date"] == "2027-08-01"
        set_clock("2027-08-01T00:00:00Z")

        first_pass = run_sweep(project_id)
        after_first = validate_success(
            api_client.get_water_quality_certification(wqc["id"], REGULATOR_HEADERS)
        )
        second_pass = run_sweep(project_id)
        after_second = validate_success(
            api_client.get_water_quality_certification(wqc["id"], REGULATOR_HEADERS)
        )

        assert after_first["status"] == "WAIVED"
        assert after_first["decided_at"].startswith("2027-08-01T00:00:00")
        assert first_pass["wqc_status"] == "WAIVED"
        assert first_pass["last_sweep_at"].startswith("2027-08-01T00:00:00")
        assert after_second["status"] == "WAIVED"
        assert after_second["decided_at"] == after_first["decided_at"]
        assert after_second["version"] == after_first["version"]
        assert second_pass["wqc_status"] == "WAIVED"
        assert second_pass["last_sweep_at"].startswith("2027-08-01T00:00:00")
        assert first_pass["compliance_flag_count"] == 0
        assert second_pass["compliance_flag_count"] == 0
        assert_postures(first_pass, regulatory_posture="OPEN")
        assert_postures(second_pass, regulatory_posture="OPEN")


class TestApplicationCureAvailability:
    def _application_under_review_with_nothing_to_cure(self):
        ctx = setup_application_under_review(
            ea_stage="SCOPING",
            definitive=False,
            study_overrides=dict(
                resource_category="RECREATION", study_title="Recreation use survey"
            ),
            site_overrides=dict(site_code="S1", river_mile=1.0),
            project_name="Cure Reach",
            **MID_SIZED_PROJECT,
        )
        assert ctx["application"]["filing_status"] == "UNDER_REVIEW"
        assert ctx["application"]["ea_stage"] == "SCOPING"
        assert ctx["application"]["deficiency_count"] == 0
        return ctx

    def test_a_cure_before_any_deficiency_notice_is_refused(self):
        """There is nothing to revive while the application is simply under review.

        PRD §3.8: "A cure attempted from a `filing_status` other than `DEFICIENT` or `SUSPENDED` is rejected with `ERR_APPLICATION_STATE_INVALID`."
        PRD §3.8: "A deficiency raised outside `UNDER_REVIEW` is rejected with `ERR_APPLICATION_STATE_INVALID`."

        Design: Corner/endpoints/application_cure_is_only_available_from_deficient_or_suspended
        """
        ctx = self._application_under_review_with_nothing_to_cure()

        response = api_client.cure_application(
            ctx["application"]["id"],
            {"cure_note": "nothing to cure yet"},
            LICENSEE_HEADERS,
        )

        validate_error(response, "ERR_APPLICATION_STATE_INVALID", 409)
        unchanged = read_application(ctx["application"]["id"])
        assert unchanged["filing_status"] == "UNDER_REVIEW"
        assert unchanged["deficiency_count"] == 0
        assert_postures(
            read_project(ctx["project"]["id"]), regulatory_posture="OPEN"
        )

    def test_the_notice_opens_the_cure_path_and_the_deficiency_count_never_falls(self):
        """The loop restricts the project and releases it, counting up the whole way.

        PRD §3.8: "The `Regulator` raises a deficiency with a required `deficiency_note`, moving `filing_status` `UNDER_REVIEW → DEFICIENT`, incrementing `deficiency_count` by 1, storing the note as `last_deficiency_note`, recomputing the project's `open_deficiency_count` and then `regulatory_posture` — which takes the project from `OPEN` to `RESTRICTED` — and incrementing the application's `version`."
        PRD §3.8: "A cure re-pins the snapshot from current state, rewriting `pinned_study_plan_version`, `pinned_settlement_version`, `pinned_measure_ids` and `pinned_total_annual_burden_usd`, then recomputes the project's `open_deficiency_count` and `regulatory_posture` and increments the application's `version`."

        Design: Corner/endpoints/application_cure_is_only_available_from_deficient_or_suspended
        """
        ctx = self._application_under_review_with_nothing_to_cure()
        application_id = ctx["application"]["id"]
        validate_error(
            api_client.cure_application(
                application_id, {"cure_note": "nothing to cure yet"}, LICENSEE_HEADERS
            ),
            "ERR_APPLICATION_STATE_INVALID",
            409,
        )

        deficient = raise_deficiency(
            application_id, deficiency_note="recreation plan incomplete"
        )
        restricted = read_project(ctx["project"]["id"])
        cured = validate_success(
            api_client.cure_application(
                application_id,
                {"cure_note": "revised recreation plan filed"},
                LICENSEE_HEADERS,
            )
        )
        released = read_project(ctx["project"]["id"])
        deficient_again = raise_deficiency(
            application_id, deficiency_note="second round of questions"
        )

        assert deficient["filing_status"] == "DEFICIENT"
        assert deficient["deficiency_count"] == 1
        assert deficient["last_deficiency_note"] == "recreation plan incomplete"
        assert restricted["open_deficiency_count"] == 1
        assert_postures(restricted, regulatory_posture="RESTRICTED")
        assert cured["filing_status"] == "UNDER_REVIEW"
        assert cured["deficiency_count"] == 1
        assert cured["ea_stage"] == "SCOPING"
        assert released["open_deficiency_count"] == 0
        assert_postures(released, regulatory_posture="OPEN")
        assert deficient_again["filing_status"] == "DEFICIENT"
        assert deficient_again["deficiency_count"] == 2
        assert deficient_again["last_deficiency_note"] == "second round of questions"


class TestFieldworkActions:
    def _study_awaiting_its_first_day_in_the_field(self):
        return setup_plan_under_agency_review(
            study_overrides=dict(
                resource_category="FISH_PASSAGE",
                study_title="Downstream passage survival",
            ),
            site_overrides=dict(site_code="S1", river_mile=1.0),
            project_name="Fieldwork Reach",
            **MID_SIZED_PROJECT,
        )

    def _fieldwork(self, study_id, action, **extra):
        payload = {"action": action}
        payload.update(extra)
        return api_client.study_fieldwork(study_id, payload, LICENSEE_HEADERS)

    def test_each_action_answers_only_from_the_status_it_belongs_to(self):
        """Resuming before starting and completing while suspended are both refused.

        PRD §3.4: "An action that does not match the current `fieldwork_status` is rejected with `ERR_STUDY_STATE_INVALID`."
        PRD §3.4: "`SUSPEND` moves `IN_PROGRESS → SUSPENDED`."

        Design: Corner/endpoints/fieldwork_actions_walk_the_suspend_resume_cycle
        """
        ctx = self._study_awaiting_its_first_day_in_the_field()
        study_id = ctx["study"]["id"]
        assert ctx["study"]["fieldwork_status"] == "PLANNED"
        assert ctx["study"]["review_status"] == "NOT_SUBMITTED"

        premature_resume = self._fieldwork(
            study_id, "RESUME", fieldwork_note="resume before start"
        )
        started = validate_success(self._fieldwork(study_id, "START"))
        suspended = validate_success(
            self._fieldwork(study_id, "SUSPEND", fieldwork_note="high flows")
        )
        premature_complete = self._fieldwork(study_id, "COMPLETE")

        validate_error(premature_resume, "ERR_STUDY_STATE_INVALID", 409)
        assert started["fieldwork_status"] == "IN_PROGRESS"
        assert started["review_status"] == "NOT_SUBMITTED"
        assert suspended["fieldwork_status"] == "SUSPENDED"
        validate_error(premature_complete, "ERR_STUDY_STATE_INVALID", 409)
        assert read_study(study_id)["fieldwork_status"] == "SUSPENDED"

    def test_the_suspend_resume_loop_never_touches_the_review_dimension(self):
        """Four field actions move one dimension; only the report moves the other.

        PRD §3.4: "Each of the four increments the study's `version` and touches `fieldwork_status` alone — `review_status` is never modified by a fieldwork action."
        PRD §3.4: "A report submission, whose body carries only an optional `report_note`, moves `review_status` `NOT_SUBMITTED → UNDER_REVIEW` on the first pass and `ADDITIONAL_REQUIRED → UNDER_REVIEW` on any subsequent pass."

        Design: Corner/endpoints/fieldwork_actions_walk_the_suspend_resume_cycle
        """
        ctx = self._study_awaiting_its_first_day_in_the_field()
        study_id = ctx["study"]["id"]
        validate_success(self._fieldwork(study_id, "START"))
        validate_success(self._fieldwork(study_id, "SUSPEND"))

        resumed = validate_success(self._fieldwork(study_id, "RESUME"))
        completed = validate_success(self._fieldwork(study_id, "COMPLETE"))
        reported = report_study(study_id)

        assert resumed["fieldwork_status"] == "IN_PROGRESS"
        assert resumed["review_status"] == "NOT_SUBMITTED"
        assert completed["fieldwork_status"] == "COMPLETED"
        assert completed["review_status"] == "NOT_SUBMITTED"
        assert reported["fieldwork_status"] == "COMPLETED"
        assert reported["review_status"] == "UNDER_REVIEW"
        assert reported["additional_round_count"] == 0
