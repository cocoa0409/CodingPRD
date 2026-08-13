"""Incidents, OSHA recordability, the incident-freeze cascade, and the
300A-style summary rates (PRD §3.6, §2.6, §2.7)."""
import pytest

from test_helpers import (
    ApiErrorId, api_client,
    validate_error, validate_success,
    assert_osha_summary,
    create_project, create_worker, create_incident, investigate_incident,
    record_determination, close_incident, get_incident, get_project,
    get_permit, get_jha,
    create_resulted_post_incident_test,
    setup_jobsite_with_issued_permit, set_clock,
    make_safety_manager_headers, make_safety_inspector_headers,
    make_compliance_auditor_headers,
)

SM = make_safety_manager_headers()
INSP1 = make_safety_inspector_headers("insp-1")
AUDITOR = make_compliance_auditor_headers()


class TestRecordability:

    def test_near_miss_with_all_flags_false_is_not_recordable(self, api):
        """PRD §3.6: "the incident is recordable when `work_related` is true and
        at least one of the following holds — medical treatment beyond first aid
        was required, days away from work is strictly greater than zero,
        restricted duty was imposed, consciousness was lost, or a significant
        diagnosis was made. A work-related `NEAR_MISS` with all five flags false
        is therefore not recordable."
        PRD §3.6: "if the incident is recordable and has a non-null `worker_id`,
        there must already exist a drug test record for this incident of type
        `POST_INCIDENT` whose result has been recorded as `NEGATIVE` or
        `POSITIVE` — otherwise the close is rejected with `ERR_DRUG_TEST_REQUIRED`"

        Design: Corner/calculations/osha_recordability_near_miss_not_recordable
        """
        set_clock("2026-08-01T08:00:00Z")
        project = create_project(name="Green Lake", annual_hours_worked=35000)
        worker = create_worker(project["id"], full_name="T Ueda")
        incident = create_incident(
            project["id"], worker_id=worker["id"], incident_type="NEAR_MISS",
            severity="MINOR", occurred_at="2026-08-02T09:00:00Z",
            work_related=True, description="falling tool missed worker",
        )
        investigate_incident(incident["id"], "tethering gap", "insp-1")

        determined = record_determination(incident["id"], manager_id="sm-1")
        assert determined["is_osha_recordable"] is False, (
            f"all-flags-false NEAR_MISS must not be recordable, got "
            f"{determined['is_osha_recordable']}"
        )

        # Not recordable: the close gate does not require any drug test.
        closed = close_incident(incident["id"])
        assert closed["status"] == "CLOSED"

    def test_recordable_close_requires_resulted_drug_test(self, api):
        """PRD §3.6: "if the incident is recordable and has a non-null
        `worker_id`, there must already exist a drug test record for this incident
        of type `POST_INCIDENT` whose result has been recorded as `NEGATIVE` or
        `POSITIVE` — otherwise the close is rejected with `ERR_DRUG_TEST_REQUIRED`."

        Design: Corner/validations/incident_close_requires_post_incident_drug_test
        """
        set_clock("2026-08-01T08:00:00Z")
        project = create_project(name="South Park", annual_hours_worked=42000)
        worker = create_worker(project["id"], full_name="V Wells")
        incident = create_incident(
            project["id"], worker_id=worker["id"], incident_type="INJURY",
            severity="SERIOUS", occurred_at="2026-08-02T08:00:00Z",
            work_related=True, description="crush injury",
        )
        investigate_incident(incident["id"], "lockout missed", "insp-1")
        record_determination(incident["id"], manager_id="sm-1",
                             medical_treatment_beyond_first_aid=True)

        # A POST_INCIDENT record exists but is still PENDING_RESULT: not enough.
        from test_helpers import create_drug_test
        create_drug_test(worker["id"], test_type="POST_INCIDENT",
                         collected_at="2026-08-02T20:00:00Z",
                         incident_id=incident["id"])

        resp = api.close_incident(incident["id"], {}, SM)
        validate_error(resp, ApiErrorId.ERR_DRUG_TEST_REQUIRED)
        assert get_incident(incident["id"])["status"] == "DETERMINATION_MADE"


class TestIncidentPipelineStates:

    def test_determination_by_investigator_rejected(self, api):
        """PRD §2.8: "the determining user must differ from the
        `investigator_user_id` recorded at investigation, again under
        `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403)."

        Design: Corner/validations/incident_determination_by_investigator_rejected
        """
        set_clock("2026-08-01T08:00:00Z")
        project = create_project(name="Sodo Yards", annual_hours_worked=64000)
        worker = create_worker(project["id"], full_name="W Xiong")
        incident = create_incident(
            project["id"], worker_id=worker["id"], incident_type="INJURY",
            severity="SERIOUS", occurred_at="2026-08-02T08:00:00Z",
            work_related=True, description="strain",
        )
        investigate_incident(incident["id"], "interviewed", "insp-1")

        # The determination call carries the investigator's X-User-ID.
        resp = api.record_determination(
            incident["id"],
            {"medical_treatment_beyond_first_aid": True, "days_away_from_work": 0,
             "restricted_duty": False, "loss_of_consciousness": False,
             "significant_diagnosis": False},
            make_safety_manager_headers("insp-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
        assert get_incident(incident["id"])["status"] == "UNDER_INVESTIGATION"

    def test_determination_before_investigation_rejected(self, api):
        """PRD §3.6: "A `SafetyInspector` opens the investigation, moving the
        incident from `REPORTED` to `UNDER_INVESTIGATION`, recording
        `investigator_user_id` from their `X-User-ID` and storing the request's
        `investigation_notes`; any other source state yields
        `ERR_INCIDENT_INVALID_STATE`."
        PRD §2.9: "Fifth (priority 5): the target resource must be in the state
        the operation requires."

        Design: Corner/errors/incident_determination_before_investigation_rejected
        """
        set_clock("2026-08-01T08:00:00Z")
        project = create_project(name="Brighton", annual_hours_worked=13000)
        worker = create_worker(project["id"], full_name="H Ito")
        incident = create_incident(
            project["id"], worker_id=worker["id"], incident_type="INJURY",
            severity="MINOR", occurred_at="2026-08-02T08:00:00Z",
            work_related=True, description="bruise",
        )
        resp = api.record_determination(
            incident["id"],
            {"medical_treatment_beyond_first_aid": False, "days_away_from_work": 0,
             "restricted_duty": False, "loss_of_consciousness": False,
             "significant_diagnosis": False},
            SM,
        )
        validate_error(resp, ApiErrorId.ERR_INCIDENT_INVALID_STATE)


class TestIncidentFreezeCascade:

    def _frozen_setup(self, severity, name="Tower 12"):
        setup = setup_jobsite_with_issued_permit(
            project_name=name, annual_hours=200000, permit_type="EXCAVATION",
        )
        incident = create_incident(
            setup["project"]["id"], worker_id=setup["worker"]["id"],
            incident_type="INJURY", severity=severity,
            occurred_at="2026-08-02T10:00:00Z", work_related=True,
            description="trench wall collapse injury",
        )
        return setup, incident

    def test_critical_incident_freezes_posture_and_suspends_permits(self, api):
        """PRD §3.6: "its creation triggers a posture recompute — a `CRITICAL` or
        `FATALITY` incident therefore freezes the project immediately, running the
        §2.6 cascade."
        PRD §2.6: "When a project transitions into `FROZEN`, every permit of that
        project in status `ISSUED` is suspended with `suspension_reason` set to
        `POSTURE_FROZEN`, and each such suspension cascades to the permit's job
        hazard analysis per §2.7."
        PRD §3.4: "suspension also decrements `issued_permit_count`, increments
        the project's `version`, and demotes the linked JHA."

        Design: Difficulty/transitive_cascade/critical_incident_freeze_cascade
        """
        setup, _incident = self._frozen_setup("CRITICAL")
        project_id = setup["project"]["id"]

        project = get_project(project_id)
        assert project["safety_posture"] == "FROZEN"
        permit = get_permit(setup["permit"]["id"])
        assert permit["status"] == "SUSPENDED"
        assert permit["suspension_reason"] == "POSTURE_FROZEN"
        assert project["issued_permit_count"] == 0

    def test_fatality_incident_runs_full_cascade_to_jha(self, api):
        """PRD §3.6: "its creation triggers a posture recompute — a `CRITICAL` or
        `FATALITY` incident therefore freezes the project immediately, running the
        §2.6 cascade."
        PRD §2.7: "Link 3 is the analysis effect: each permit suspended in link 2
        drives its linked job hazard analysis from `APPROVED` back to
        `RE_REVIEW_REQUIRED`, forcing a fresh safety review before that task's
        permits can be issued or reinstated again."

        Design: Difficulty/transitive_cascade/critical_incident_freeze_cascade
        """
        setup, _incident = self._frozen_setup("FATALITY", name="Tower 12 South")
        project_id = setup["project"]["id"]

        assert get_project(project_id)["safety_posture"] == "FROZEN"
        assert get_permit(setup["permit"]["id"])["status"] == "SUSPENDED"
        # Link 3: the permit's JHA is demoted out of APPROVED.
        assert get_jha(setup["jha"]["id"])["status"] == "RE_REVIEW_REQUIRED"
        # The cascade does not touch the involved worker's status.
        from test_helpers import get_worker
        assert get_worker(setup["worker"]["id"])["status"] == "CLEARED"


class TestOshaSummaryRates:

    def _project_with_one_closed_recordable_and_one_open(self, hours,
                                                         name="North Tower"):
        """One CLOSED recordable+DART incident and one incident still
        UNDER_INVESTIGATION; both occurred in calendar 2026."""
        set_clock("2026-08-01T08:00:00Z")
        project = create_project(name=name, annual_hours_worked=hours)
        worker = create_worker(project["id"], full_name="A Reyes")
        inc1 = create_incident(
            project["id"], worker_id=worker["id"], incident_type="INJURY",
            severity="SERIOUS", occurred_at="2026-08-02T08:00:00Z",
            work_related=True, description="hand laceration",
        )
        investigate_incident(inc1["id"], "statements taken", "insp-1")
        record_determination(inc1["id"], manager_id="sm-1",
                             medical_treatment_beyond_first_aid=True,
                             days_away_from_work=3)
        create_resulted_post_incident_test(worker["id"], inc1["id"],
                                           "2026-08-02T20:00:00Z", "NEGATIVE")
        close_incident(inc1["id"])
        inc2 = create_incident(
            project["id"], worker_id=worker["id"], incident_type="INJURY",
            severity="SERIOUS", occurred_at="2026-08-04T09:00:00Z",
            work_related=True, description="suspected fracture",
        )
        investigate_incident(inc2["id"], "pending x-ray", "insp-1")
        return project

    def test_osha_summary_final_variant_counts(self, api):
        """PRD §3.6: "The final recordable count includes only incidents in
        `DETERMINATION_MADE` or `CLOSED` whose `is_osha_recordable` is true"
        PRD §3.6: "The final DART count — days away, restricted, or transferred —
        includes only final-recordable incidents with days away from work strictly
        greater than zero or restricted duty"
        PRD §3.6: "the total recordable incident rate is the recordable count
        multiplied by 200,000 and divided by `annual_hours_worked`, rounded
        half-up to 1 decimal place; the DART rate is the same formula over the
        DART count."

        Design: Difficulty/dual_variant_calc/incident_rate_provisional_vs_final
        """
        project = self._project_with_one_closed_recordable_and_one_open(200000)
        resp = api.get_osha_summary(project["id"], SM, params={"year": 2026})
        summary = validate_success(resp, 200)
        assert_osha_summary(summary)
        assert summary["year"] == 2026
        assert summary["hours_worked"] == 200000
        assert summary["recordable_count_final"] == 1
        assert summary["dart_count_final"] == 1
        assert summary["trir_final"] == pytest.approx(1.0, abs=0.001)
        assert summary["dart_rate_final"] == pytest.approx(1.0, abs=0.001)

    def test_osha_summary_provisional_variant_adds_open_incidents(self, api):
        """PRD §3.6: "the provisional recordable count adds every incident still
        in `REPORTED` or `UNDER_INVESTIGATION` as a worst case."
        PRD §3.6: "the provisional DART count likewise adds the still-open
        incidents."

        Design: Difficulty/dual_variant_calc/incident_rate_provisional_vs_final
        """
        project = self._project_with_one_closed_recordable_and_one_open(
            200000, name="North Tower 2"
        )
        resp = api.get_osha_summary(project["id"], AUDITOR, params={"year": 2026})
        summary = validate_success(resp, 200)
        assert_osha_summary(summary)
        # Identical data, worst-case variant: one extra open incident enters
        # both the recordable and DART counts.
        assert summary["recordable_count_provisional"] == 2
        assert summary["dart_count_provisional"] == 2
        assert summary["trir_provisional"] == pytest.approx(2.0, abs=0.001)
        assert summary["dart_rate_provisional"] == pytest.approx(2.0, abs=0.001)

    def _project_with_two_closed_recordables(self):
        """Two CLOSED recordable incidents in 2026, exactly one of them DART."""
        set_clock("2026-08-01T08:00:00Z")
        project = create_project(name="Cedar Ridge", location="Bellevue",
                                 annual_hours_worked=150000)
        worker = create_worker(project["id"], full_name="B Sato")
        inc1 = create_incident(
            project["id"], worker_id=worker["id"], incident_type="INJURY",
            severity="SERIOUS", occurred_at="2026-08-02T08:00:00Z",
            work_related=True, description="fall from ladder",
        )
        investigate_incident(inc1["id"], "ladder inspection", "insp-1")
        record_determination(inc1["id"], manager_id="sm-1",
                             medical_treatment_beyond_first_aid=True,
                             days_away_from_work=5)
        create_resulted_post_incident_test(worker["id"], inc1["id"],
                                           "2026-08-02T20:00:00Z", "NEGATIVE")
        close_incident(inc1["id"])
        inc2 = create_incident(
            project["id"], worker_id=worker["id"], incident_type="INJURY",
            severity="SERIOUS", occurred_at="2026-08-03T09:00:00Z",
            work_related=True, description="stitches",
        )
        investigate_incident(inc2["id"], "tool guard missing", "insp-1")
        record_determination(inc2["id"], manager_id="sm-1",
                             medical_treatment_beyond_first_aid=True,
                             days_away_from_work=0)
        create_resulted_post_incident_test(worker["id"], inc2["id"],
                                           "2026-08-04T09:00:00Z", "NEGATIVE")
        close_incident(inc2["id"])
        return project

    def test_rates_round_half_up_to_one_decimal(self, api):
        """PRD §3.6: "the total recordable incident rate is the recordable count
        multiplied by 200,000 and divided by `annual_hours_worked`, rounded
        half-up to 1 decimal place; the DART rate is the same formula over the
        DART count."
        PRD §2.12: "The OSHA rates of §3.6 are reported to exactly 1 decimal place
        using round-half-up"

        Design: Difficulty/combinatorial_formula/osha_rate_rounding_order_spread
        """
        project = self._project_with_two_closed_recordables()
        resp = api.get_osha_summary(project["id"], AUDITOR, params={"year": 2026})
        summary = validate_success(resp, 200)
        # 2 recordables over 150000 hours -> 2.6666... -> 2.7 (round-half-up).
        assert summary["trir_final"] == pytest.approx(2.7, abs=0.001)
        # 1 DART over 150000 hours -> 1.3333... -> 1.3.
        assert summary["dart_rate_final"] == pytest.approx(1.3, abs=0.001)

    def test_rate_spread_derived_from_rounded_components(self, api):
        """PRD §3.6: "The rounding order is pinned: each rate is rounded first,
        and `rate_spread_final` is the rounded final TRIR minus the rounded final
        DART rate — it is not computed by rounding the difference of unrounded
        values."

        Design: Difficulty/combinatorial_formula/osha_rate_rounding_order_spread
        """
        project = self._project_with_two_closed_recordables()
        resp = api.get_osha_summary(project["id"], SM, params={"year": 2026})
        summary = validate_success(resp, 200)
        # 2.7 - 1.3 = 1.4 (from rounded components); rounding the raw difference
        # 1.3333... would yield 1.3.
        assert summary["rate_spread_final"] == pytest.approx(1.4, abs=0.001)
