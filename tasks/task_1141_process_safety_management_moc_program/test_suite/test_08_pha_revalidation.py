"""PHA studies: dual due-date variants, sweep thresholds, revalidation cycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    drive_incident_to_findings_submitted,
    get_pha_study,
    get_unit,
    list_unit_action_items,
    new_incident,
    new_personnel,
    new_study,
    new_unit,
    set_clock,
    setup_unit_with_study,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["manager_headers"]


def _study_with_incident_at_findings_submitted():
    """Unit (cycle 12), study validated 2026-01-15, one HIGH incident moved to
    FINDINGS_SUBMITTED with zero findings. Returns (unit, study, incident)."""
    unit = new_unit(name="Crude", unit_code="CRU1", pha_cycle_months=12)
    study = new_study(unit["id"], method="HAZOP", initial_validated_at="2026-01-15")
    inv = new_personnel("Inv", "E-INV")
    new_personnel("Req", "E-REQ")
    incident = new_incident(unit["id"], inv["id"], severity_class="HIGH", occurred_at="2026-04-20",
                            title="Seal leak")
    drive_incident_to_findings_submitted(incident, findings=[])
    return unit, study, incident


class TestDualDueVariants:
    def test_incident_close_collapses_risk_accelerated_due(self, api):
        """PRD §3.7: "The `nominal_next_due` is `last_validated_at` plus
        `pha_cycle_months` converted at thirty days per month — pure calendar
        arithmetic that ignores incidents."
        PRD §3.7: "letting N be the number of the unit's `CLOSED` incident
        investigations with `severity_class` `HIGH` or `CATASTROPHIC` whose
        `occurred_at` is on or after `last_validated_at`, the cycle length in days
        is multiplied by the larger of 0.25 and (one minus one tenth of N),
        rounded down to a whole number of days, and added to `last_validated_at`"
        — N = 1 gives floor(360 × 0.9) = 324 days.
        PRD §3.7: "The `effective_next_due` is the earlier of the nominal and
        risk-accelerated dates."

        Design: Difficulty/dual_variant_calc/pha_nominal_vs_risk_accelerated_due
        """
        unit, study, incident = _study_with_incident_at_findings_submitted()
        validate_success(api.close_incident(incident["id"], MANAGER), 200)

        after = get_pha_study(study["id"])
        assert after["nominal_next_due"] == "2027-01-10T00:00:00Z", (
            f"calendar variant unchanged by incidents, got {after['nominal_next_due']}"
        )
        assert after["risk_accelerated_due"] == "2026-12-05T00:00:00Z", (
            f"2026-01-15 + floor(360*0.9)=324d must be 2026-12-05, got {after['risk_accelerated_due']}"
        )
        assert after["effective_next_due"] == "2026-12-05T00:00:00Z"

    def test_incident_close_forces_revalidation_required(self, api):
        """PRD §3.7: "A `PsmManager` closes it from there, which sets `feeds_pha`
        to true exactly when `severity_class` is `HIGH` or `CATASTROPHIC`. When
        `feeds_pha` is true and the unit's study stands in `CURRENT`, `DUE_SOON`,
        or `OVERDUE`, closure forces the study into `REVALIDATION_REQUIRED` and
        spawns a `P1` action item with `source_type` `PHA_REVALIDATION` sourced to
        the study, assigned to the investigation's `investigator_id`, due thirty
        days after the clock date".

        Design: Difficulty/dual_variant_calc/pha_nominal_vs_risk_accelerated_due
        """
        unit, study, incident = _study_with_incident_at_findings_submitted()
        closed = validate_success(api.close_incident(incident["id"], MANAGER), 200)
        assert closed["feeds_pha"] is True
        assert get_pha_study(study["id"])["status"] == "REVALIDATION_REQUIRED"

        items = list_unit_action_items(unit["id"])
        forced = [i for i in items if i["source_type"] == "PHA_REVALIDATION"]
        assert len(forced) == 1
        assert forced[0]["priority"] == "P1"
        assert forced[0]["source_id"] == study["id"]
        assert forced[0]["assignee_id"] == incident["investigator_id"]


class TestSweepThresholds:
    def test_pha_due_soon_and_overdue_threshold_boundaries(self, api):
        """PRD §3.7: "When the clock reaches sixty days before
        `effective_next_due` — that is, the clock is on or after
        `effective_next_due` minus sixty days and on or before
        `effective_next_due` itself — a `CURRENT` study becomes `DUE_SOON`. Once
        the clock passes `effective_next_due`, a study in `CURRENT` or `DUE_SOON`
        becomes `OVERDUE`" — with dues at 2027-01-10 the boundary dates are
        2026-11-11 (inclusive) and 2027-01-11 (strictly past).

        Design: Corner/calculations/pha_due_soon_and_overdue_threshold_boundaries
        """
        unit, study = setup_unit_with_study(validated_at="2026-01-15")

        set_clock("2026-11-10T00:00:00Z")
        assert get_pha_study(study["id"])["status"] == "CURRENT"
        set_clock("2026-11-11T00:00:00Z")
        assert get_pha_study(study["id"])["status"] == "DUE_SOON", (
            "DUE_SOON starts at effective_next_due - 60d inclusive"
        )
        set_clock("2027-01-10T00:00:00Z")
        assert get_pha_study(study["id"])["status"] == "DUE_SOON", (
            "on the due date itself the study is not yet OVERDUE"
        )
        set_clock("2027-01-11T00:00:00Z")
        after = get_pha_study(study["id"])
        assert after["status"] == "OVERDUE"
        assert after["effective_next_due"] == "2027-01-10T00:00:00Z"


class TestRevalidation:
    def _overdue_study_with_leader(self):
        """Study validated 2026-01-01 (cycle 12 → dues 2026-12-27); clock
        2026-12-28 makes it OVERDUE. Returns (unit, study, haz, req)."""
        unit = new_unit(name="U", unit_code="U1", pha_cycle_months=12)
        study = new_study(unit["id"], method="HAZOP", initial_validated_at="2026-01-01")
        haz = new_personnel("Haz", "E-HAZ", qualifications=["HAZOP_LEADER"])
        req = new_personnel("Req", "E-REQ")
        set_clock("2026-12-28T00:00:00Z")
        assert get_pha_study(study["id"])["status"] == "OVERDUE"
        return unit, study, haz, req

    def test_revalidation_complete_resets_pha_schedule(self, api):
        """PRD §3.7: "it resets `last_validated_at` to the clock date, increments
        `revalidation_count` by one, recomputes all three dues, returns the study
        to `CURRENT`, moves the revalidation to `COMPLETED`, and spawns one action
        item per element of the optional `findings` array — each carrying a
        `title`, a `priority` of `P1`, `P2`, or `P3`, and an `assignee_id` — with
        `source_type` `PHA_REVALIDATION` sourced to the revalidation itself, due
        per the SLA, with unit counts and index updated."
        At clock 2026-12-28 with a 360-day cycle the new nominal due is
        2027-12-23; a P2 finding item is due 90 days out (2027-03-28).

        Design: Corner/state_machines/revalidation_complete_resets_pha_schedule
        """
        unit, study, haz, req = self._overdue_study_with_leader()
        rv = validate_success(api.open_revalidation(study["id"], {"leader_id": haz["id"]}, MANAGER), 201)

        completed = validate_success(api.complete_revalidation(
            rv["id"],
            {"findings_summary": "2 nodes reviewed",
             "findings": [{"title": "Update P&ID", "priority": "P2", "assignee_id": req["id"]}]},
            MANAGER), 200)
        assert completed["status"] == "COMPLETED"

        after = get_pha_study(study["id"])
        assert after["status"] == "CURRENT"
        assert after["last_validated_at"] == "2026-12-28T00:00:00Z"
        assert after["revalidation_count"] == 1
        assert after["nominal_next_due"] == "2027-12-23T00:00:00Z", (
            f"2026-12-28 + 360d must be 2027-12-23, got {after['nominal_next_due']}"
        )

        items = list_unit_action_items(unit["id"])
        assert len(items) == 1
        assert items[0]["source_type"] == "PHA_REVALIDATION"
        assert items[0]["source_id"] == rv["id"]
        assert items[0]["due_date"] == "2027-03-28T00:00:00Z"
        assert get_unit(unit["id"])["open_action_count"] == 1

    def test_open_revalidation_captures_prior_status(self, api):
        """PRD §3.7: "A `PsmManager` opens a revalidation from `DUE_SOON`,
        `OVERDUE`, or `REVALIDATION_REQUIRED` (`ERR_PHA_STUDY_INVALID_STATE` from
        anywhere else), naming a `leader_id` who must be active personnel holding
        `HAZOP_LEADER` (`ERR_QUALIFICATION_MISSING`). The study captures its
        current status into `status_before_revalidation`, moves to
        `IN_REVALIDATION`, and a **PhaRevalidation** is created in `OPEN` status
        bound to the study by `study_id`".

        Design: Difficulty/compensating_invariant/pha_open_abandon_schedule_invariant
        """
        unit, study, haz, req = self._overdue_study_with_leader()
        rv = validate_success(api.open_revalidation(study["id"], {"leader_id": haz["id"]}, MANAGER), 201)
        assert rv["status"] == "OPEN"
        assert rv["study_id"] == study["id"]

        during = get_pha_study(study["id"])
        assert during["status"] == "IN_REVALIDATION"
        assert during["status_before_revalidation"] == "OVERDUE"

    def test_abandon_restores_schedule_unchanged(self, api):
        """PRD §3.7: "Abandonment, the sibling exit from `OPEN`, moves the
        revalidation to `ABANDONED` and restores the study to whatever
        `status_before_revalidation` captured — back to `DUE_SOON`, to `OVERDUE`,
        or to `REVALIDATION_REQUIRED` as the case may be — while leaving
        `last_validated_at`, all three due dates, and `revalidation_count`
        unchanged: an abandoned attempt leaves the validation schedule exactly as
        it found it."

        Design: Difficulty/compensating_invariant/pha_open_abandon_schedule_invariant
        """
        unit, study, haz, req = self._overdue_study_with_leader()
        rv = validate_success(api.open_revalidation(study["id"], {"leader_id": haz["id"]}, MANAGER), 201)

        abandoned = validate_success(api.abandon_revalidation(rv["id"], MANAGER), 200)
        assert abandoned["status"] == "ABANDONED"

        after = get_pha_study(study["id"])
        assert after["status"] == "OVERDUE", "status_before_revalidation must be restored"
        assert after["last_validated_at"] == "2026-01-01T00:00:00Z"
        assert after["nominal_next_due"] == "2026-12-27T00:00:00Z"
        assert after["risk_accelerated_due"] == "2026-12-27T00:00:00Z"
        assert after["effective_next_due"] == "2026-12-27T00:00:00Z"
        assert after["revalidation_count"] == 0

    def test_revalidation_leader_qualification_missing_rejected(self, api):
        """PRD §3.7: open-revalidation names "a `leader_id` who must be active
        personnel holding `HAZOP_LEADER` (`ERR_QUALIFICATION_MISSING`)".

        Design: Corner/validations/revalidation_leader_qualification_missing_rejected
        """
        unit = new_unit(name="U", unit_code="U1", pha_cycle_months=12)
        study = new_study(unit["id"], method="HAZOP", initial_validated_at="2026-01-15")
        haz = new_personnel("Haz", "E-HAZ")  # no HAZOP_LEADER qualification
        set_clock("2027-01-11T00:00:00Z")  # past effective due 2027-01-10 → OVERDUE

        resp = api.open_revalidation(study["id"], {"leader_id": haz["id"]}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_QUALIFICATION_MISSING.value)
        assert get_pha_study(study["id"])["status"] == "OVERDUE"
