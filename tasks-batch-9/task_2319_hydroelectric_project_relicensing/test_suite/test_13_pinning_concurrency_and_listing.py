"""Version pins on the two guarded creates, the filing snapshot, study listing pages and immediate consistency."""
import pytest

from test_helpers import (
    TEST_USERS,
    U_LICENSEE_A,
    advance_environmental_review,
    api_client,
    application_payload,
    assert_ledger_matches,
    assert_postures,
    certify_with_conditions,
    cure_application,
    file_application,
    file_pad,
    list_measures,
    make_licensee_headers,
    move_fieldwork,
    new_project,
    new_site,
    new_study,
    new_study_plan,
    patch_project,
    project_version,
    raise_deficiency,
    read_application,
    read_project,
    read_study,
    record_definitive_estimate,
    request_certification,
    set_clock,
    settlement_payload,
    setup_certification_conditioned_project,
    setup_study_phase_project,
    submit_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

REGULATOR_HEADERS = TEST_USERS["regulator_headers"]
LICENSEE_HEADERS = make_licensee_headers(U_LICENSEE_A)
MID_SIZED_PROJECT = dict(
    installed_capacity_mw=12.0,
    base_annual_generation_mwh=250000,
    license_expiration_date="2035-06-30",
)
RECREATION_STUDY = dict(
    resource_category="RECREATION", study_title="Recreation use survey"
)
FIRST_SITE = dict(site_code="S1", river_mile=1.0)


class TestSettlementVersionPin:
    def test_the_version_read_before_the_pad_filing_is_already_stale(self):
        """The pin captured at registration no longer matches once anything writes the project.

        PRD §2.11: "Opening a settlement — the create at `POST /relicensing/settlements` — must carry `expected_project_version` matching the target project's current `version`. If the project's version has advanced since the client last read it, the create is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."
        PRD §3.5: "The settlement starts in `NEGOTIATING` with `round_number` 1, unset `circulated_at`, `executed_at` and `withdrawn_at`, and `support_pct`, `total_vote_weight` and `included_measure_count` all zero."

        Design: Corner/cross_cutting_complexity_layers/stale_project_version_on_settlement_creation_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        project = new_project(
            license_number="P-9057",
            project_name="Occ Settlement Reach",
            **MID_SIZED_PROJECT,
        )
        version_at_registration = project["version"]
        assert version_at_registration == 1
        after_pad = file_pad(project["id"])
        assert after_pad["version"] == 2

        stale = api_client.create_settlement(
            settlement_payload(
                project["id"],
                version_at_registration,
                title="Settlement at a stale version",
            ),
            LICENSEE_HEADERS,
        )

        validate_error(stale, "ERR_STALE_PROJECT_VERSION", 412)
        _rows, meta = validate_paginated(
            api_client.list_settlements(REGULATOR_HEADERS, params={"limit": 100})
        )
        assert meta["total_count"] == 0

        current_version = project_version(project["id"])
        assert current_version == 2
        opened = validate_success(
            api_client.create_settlement(
                settlement_payload(
                    project["id"],
                    current_version,
                    title="Settlement at the current version",
                ),
                LICENSEE_HEADERS,
            ),
            201,
        )

        assert opened["status"] == "NEGOTIATING"
        assert opened["round_number"] == 1
        assert opened["support_pct"] == pytest.approx(0.00, abs=0.01)
        assert opened["included_measure_count"] == 0
        assert project_version(project["id"]) == 3


class TestApplicationVersionPin:
    def test_the_pin_is_checked_before_the_stage_the_project_is_actually_in(self):
        """A stale pin on a pre-filing project answers 412; a fresh pin reaches the stage rule.

        PRD §2.12: "12. `expected_project_version` equals the target project's `version` — `ERR_STALE_PROJECT_VERSION` (412), on settlement creation and application filing."
        PRD §2.12: "16. The project's `stage` permits the operation — `ERR_PROJECT_STAGE_INVALID` (409)."

        Design: Corner/cross_cutting_complexity_layers/stale_project_version_on_application_filing_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        project = new_project(
            license_number="P-9058", project_name="Occ Filing Reach", **MID_SIZED_PROJECT
        )
        version_at_registration = project["version"]
        assert version_at_registration == 1
        renamed = patch_project(project["id"], project_name="Occ Filing Reach Renamed")
        assert renamed["version"] == 2
        assert renamed["stage"] == "PRE_FILING"

        stale = api_client.create_application(
            application_payload(
                project["id"],
                version_at_registration,
                filing_note="stale and out of stage",
            ),
            LICENSEE_HEADERS,
        )

        validate_error(stale, "ERR_STALE_PROJECT_VERSION", 412)

        current_version = project_version(project["id"])
        assert current_version == 2
        wrong_stage = api_client.create_application(
            application_payload(
                project["id"], current_version, filing_note="fresh version, wrong stage"
            ),
            LICENSEE_HEADERS,
        )

        validate_error(wrong_stage, "ERR_PROJECT_STAGE_INVALID", 409)
        _rows, meta = validate_paginated(
            api_client.list_applications(REGULATOR_HEADERS, params={"limit": 100})
        )
        assert meta["total_count"] == 0
        assert read_project(project["id"])["stage"] == "PRE_FILING"


class TestFilingSnapshot:
    def test_the_pinned_burden_holds_still_until_a_cure_re_pins_it(self):
        """Re-pricing the state's condition moves the live ledger and leaves the snapshot behind.

        PRD §3.8: "`pinned_total_annual_burden_usd` records the project's `total_annual_burden_usd` as observed at filing."
        PRD §3.8: "A cure re-pins the snapshot from current state, rewriting `pinned_study_plan_version`, `pinned_settlement_version`, `pinned_measure_ids` and `pinned_total_annual_burden_usd`, then recomputes the project's `open_deficiency_count` and `regulatory_posture` and increments the application's `version`."

        Design: Corner/cross_cutting_complexity_layers/application_pins_state_at_filing_and_repins_on_cure
        """
        ctx = setup_certification_conditioned_project(
            definitive=False,
            study_overrides=RECREATION_STUDY,
            site_overrides=FIRST_SITE,
            license_number="P-9059",
            project_name="Pinning Reach",
            **MID_SIZED_PROJECT,
        )
        project_id = ctx["project"]["id"]
        plan = ctx["plan"]
        condition_measure = ctx["condition_measures"][0]
        assert condition_measure["cost_estimate_variant"] == "PRELIMINARY"
        assert ctx["project"]["total_annual_burden_usd"] == pytest.approx(
            68326.80, abs=0.01
        )

        application = file_application(project_id)

        assert application["pinned_study_plan_id"] == plan["id"]
        assert application["pinned_study_plan_version"] == plan["version"]
        assert application["pinned_settlement_id"] is None
        assert application["pinned_total_annual_burden_usd"] == pytest.approx(
            68326.80, abs=0.01
        )
        assert application["pinned_measure_ids"] == [condition_measure["id"]]

        repriced = record_definitive_estimate(condition_measure["id"])

        assert repriced["cost_estimate_variant"] == "DEFINITIVE"
        assert_ledger_matches(
            read_project(project_id),
            total_pme_annual_cost_usd=53000.00,
            total_generation_loss_mwh=497.9,
            administrative_annual_charge_usd=1060.00,
            total_annual_burden_usd=74971.80,
            burden_ratio_pct=0.71,
        )
        assert read_application(application["id"])[
            "pinned_total_annual_burden_usd"
        ] == pytest.approx(68326.80, abs=0.01)

        advance_environmental_review(application["id"], "SCOPING")
        raise_deficiency(application["id"], deficiency_note="update the cost exhibit")
        cured = cure_application(
            application["id"], cure_note="definitive cost exhibit filed"
        )

        assert cured["filing_status"] == "UNDER_REVIEW"
        assert cured["pinned_study_plan_id"] == plan["id"]
        assert cured["pinned_total_annual_burden_usd"] == pytest.approx(
            74971.80, abs=0.01
        )


class TestStudyListing:
    def _four_studies_on_one_submitted_plan(self):
        ctx = setup_study_phase_project(
            sites=[dict(site_code="S1", river_mile=1.0, min_rest_buffer_days=0)],
            license_number="P-9060",
            project_name="Listing Reach",
            **MID_SIZED_PROJECT,
        )
        project_id = ctx["project"]["id"]
        plan_id = ctx["plan"]["id"]
        first_site = ctx["sites"][0]
        second_site = new_site(
            project_id, site_code="S2", river_mile=2.0, min_rest_buffer_days=0
        )
        studies = [
            new_study(
                plan_id,
                first_site["id"],
                resource_category="FISH_PASSAGE",
                study_title="A upstream passage",
                fieldwork_window_start="2026-09-01",
                fieldwork_window_end="2026-10-01",
            ),
            new_study(
                plan_id,
                first_site["id"],
                resource_category="WATER_QUALITY",
                study_title="B dissolved oxygen",
                fieldwork_window_start="2026-11-01",
                fieldwork_window_end="2026-12-01",
            ),
            new_study(
                plan_id,
                second_site["id"],
                resource_category="RECREATION",
                study_title="C recreation use",
                fieldwork_window_start="2026-09-01",
                fieldwork_window_end="2026-10-01",
            ),
            new_study(
                plan_id,
                second_site["id"],
                resource_category="CULTURAL",
                study_title="D ethnographic survey",
                fieldwork_window_start="2026-11-01",
                fieldwork_window_end="2026-12-01",
            ),
        ]
        submit_plan(plan_id)
        ctx.update({"sites": [first_site, second_site], "studies": studies})
        return ctx

    def test_two_pages_of_two_cover_the_whole_set_exactly_once(self):
        """`total_count` describes the set while `has_more` describes the page.

        PRD §2.3: "`limit` caps the number of items returned; it defaults to 10, may be no smaller than 1 and no larger than 100."
        PRD §2.3: "`offset` is the number of items to skip; it defaults to 0 and may not be negative."

        Design: Corner/cross_cutting_complexity_layers/study_listing_filter_and_pagination_interact
        """
        ctx = self._four_studies_on_one_submitted_plan()
        all_ids = {study["id"] for study in ctx["studies"]}

        first_page, first_meta = validate_paginated(
            api_client.list_studies(REGULATOR_HEADERS, params={"limit": 2, "offset": 0})
        )
        second_page, second_meta = validate_paginated(
            api_client.list_studies(REGULATOR_HEADERS, params={"limit": 2, "offset": 2})
        )

        assert len(first_page) == 2
        assert first_meta["total_count"] == 4
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True
        assert len(second_page) == 2
        assert second_meta["total_count"] == 4
        assert second_meta["offset"] == 2
        assert second_meta["has_more"] is False
        first_ids = {row["id"] for row in first_page}
        second_ids = {row["id"] for row in second_page}
        assert first_ids.isdisjoint(second_ids)
        assert first_ids | second_ids == all_ids

        out_of_range = api_client.list_studies(
            REGULATOR_HEADERS, params={"limit": 101, "offset": 0}
        )

        validate_error(out_of_range, "ERR_VALIDATION", 400)

    def test_starting_one_study_moves_it_between_the_status_buckets(self):
        """The lifecycle field is also the filter name, so one transition re-sorts the listing.

        PRD §2.5: "Lifecycle state is spelled differently from resource to resource, and the spelling matters because it is also the name of the filter a client passes when listing."
        PRD §3.4: "An `action` of `START` moves `PLANNED → IN_PROGRESS` and additionally requires that the parent plan's status be `UNDER_AGENCY_REVIEW`, `REVISION_REQUIRED` or `APPROVED`, and that the project's `regulatory_posture` not be `FROZEN`."

        Design: Corner/cross_cutting_complexity_layers/study_listing_filter_and_pagination_interact
        """
        ctx = self._four_studies_on_one_submitted_plan()
        first_study = ctx["studies"][0]

        planned_before, planned_before_meta = validate_paginated(
            api_client.list_studies(
                REGULATOR_HEADERS, params={"fieldwork_status": "PLANNED", "limit": 100}
            )
        )

        assert planned_before_meta["total_count"] == 4
        assert len(planned_before) == 4

        move_fieldwork(first_study["id"], "START")

        planned_after, planned_after_meta = validate_paginated(
            api_client.list_studies(
                REGULATOR_HEADERS, params={"fieldwork_status": "PLANNED", "limit": 100}
            )
        )
        running, running_meta = validate_paginated(
            api_client.list_studies(
                REGULATOR_HEADERS,
                params={"fieldwork_status": "IN_PROGRESS", "limit": 100},
            )
        )

        assert planned_after_meta["total_count"] == 3
        assert len(planned_after) == 3
        assert all(row["fieldwork_status"] == "PLANNED" for row in planned_after)
        assert first_study["id"] not in {row["id"] for row in planned_after}
        assert running_meta["total_count"] == 1
        assert running_meta["has_more"] is False
        assert running[0]["id"] == first_study["id"]
        assert read_study(first_study["id"])["fieldwork_status"] == "IN_PROGRESS"


class TestImmediateConsistency:
    def test_the_first_read_after_the_decision_already_shows_every_consequence(self):
        """Measure, ledger, infeasibility flag and posture all land in one request.

        PRD §2.9: "There is no lazy reconciliation and no background job: by the time a response is emitted, every counter, ledger figure and posture affected by the request already reflects the new reality."
        PRD §3.6: "Because those measures are `INCLUDED` on arrival, each insertion feeds the project burden ledger: `total_pme_annual_cost_usd`, `total_generation_loss_mwh`, `administrative_annual_charge_usd`, `total_annual_burden_usd` and `burden_ratio_pct` are all recomputed, the recomputed `burden_ratio_pct` sets `economically_infeasible`, and that flag recomputes `regulatory_posture` — moving the project from `OPEN` to `RESTRICTED` the moment the ratio reaches 15.00 with no infeasibility waiver in force."

        Design: Corner/consistency_model/certification_cascade_is_visible_in_the_immediately_following_read
        """
        set_clock("2026-08-01T00:00:00Z")
        project = new_project(
            license_number="P-9061",
            project_name="Immediate Reach",
            installed_capacity_mw=2.5,
            base_annual_generation_mwh=10000,
            license_expiration_date="2035-06-30",
        )
        file_pad(project["id"])
        new_study_plan(project["id"])
        wqc = request_certification(project["id"])
        before = read_project(project["id"])
        assert before["total_annual_burden_usd"] == pytest.approx(0.00, abs=0.01)
        assert before["economically_infeasible"] is False
        assert_postures(before, regulatory_posture="OPEN")

        decided = certify_with_conditions(wqc["id"])

        assert decided["status"] == "CERTIFIED_WITH_CONDITIONS"
        assert decided["condition_count"] == 1
        assert decided["decided_at"].startswith("2026-08-01T00:00:00")

        first_read = read_project(project["id"])

        assert first_read["wqc_status"] == "CERTIFIED_WITH_CONDITIONS"
        assert_ledger_matches(
            first_read,
            total_pme_annual_cost_usd=57500.00,
            total_generation_loss_mwh=230.4,
            administrative_annual_charge_usd=1150.00,
            total_annual_burden_usd=68326.80,
            burden_ratio_pct=16.27,
        )
        assert first_read["economically_infeasible"] is True
        assert_postures(first_read, regulatory_posture="RESTRICTED")

        measures = list_measures(project["id"], source="WQC_CONDITION")
        second_read = read_project(project["id"])

        assert len(measures) == 1
        assert measures[0]["status"] == "INCLUDED"
        assert measures[0]["cost_estimate_variant"] == "PRELIMINARY"
        assert measures[0]["annual_cost_usd"] == pytest.approx(57500.00, abs=0.01)
        assert second_read["total_annual_burden_usd"] == pytest.approx(
            68326.80, abs=0.01
        )
        assert_postures(second_read, regulatory_posture="RESTRICTED")
