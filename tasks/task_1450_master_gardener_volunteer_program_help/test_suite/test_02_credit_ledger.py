"""Credit-entry ledger: adjudication, totals variants, recognition fields."""
import pytest

from test_helpers import (ApiErrorId, approve_entry, close_cycle,
                          create_active_volunteer, create_and_open_cycle,
                          create_approved_project, create_credit_entry_payload,
                          get_record_for, get_success_data,
                          log_and_approve_service_entry, log_ce_entry,
                          log_service_entry, make_coordinator_headers,
                          make_volunteer_headers, move_cycle_to_recertification,
                          reject_entry, setup_cycle_closed_with_shortfall_volunteer,
                          setup_cycle_with_active_volunteer, validate_error,
                          validate_success)
from test_helpers import TEST_USERS

COORD = TEST_USERS["coordinator_headers"]


class TestEntryKindAndQuantumRules:
    def test_credit_entry_hours_quantum_and_range_boundaries(self, api):
        """PRD §3.3: "Claimed `hours` must be a positive multiple of 0.25 no
        greater than 12.0"
        PRD §2.9: "`ERR_INVALID_FIELD_VALUE` (HTTP 422) for static range and
        quantum violations"

        Design: Corner/entities/credit_entry_hours_quantum_and_range_boundaries
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        hdrs = make_volunteer_headers(vol["id"])

        ok1 = validate_success(api.create_credit_entry(
            vol["id"], create_credit_entry_payload(cycle["id"], hours=12.0),
            hdrs), expected_status=201)
        assert ok1["status"] == "PENDING"

        resp = api.create_credit_entry(
            vol["id"], create_credit_entry_payload(cycle["id"], hours=12.25),
            hdrs)
        validate_error(resp, ApiErrorId.ERR_INVALID_FIELD_VALUE)

        ok2 = validate_success(api.create_credit_entry(
            vol["id"], create_credit_entry_payload(cycle["id"], hours=0.25),
            hdrs), expected_status=201)
        assert ok2["status"] == "PENDING"

        resp = api.create_credit_entry(
            vol["id"], create_credit_entry_payload(cycle["id"], hours=0.10),
            hdrs)
        validate_error(resp, ApiErrorId.ERR_INVALID_FIELD_VALUE)

    def test_entry_validation_and_state_errors(self, api):
        """PRD §3.3: "Revocation is the compensating action for approval: it
        requires an `APPROVED` entry (otherwise `ERR_ENTRY_NOT_APPROVED`)"
        PRD §3.3: "a date outside the window fails with
        `ERR_ACTIVITY_OUTSIDE_CYCLE_WINDOW` (HTTP 422)"
        PRD §3.3: "Violations fail with `ERR_MISSING_KIND_FIELDS`."

        Design: Corner/state_machines/entry_validation_and_state_errors
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        hdrs = make_volunteer_headers(vol["id"])
        entry = log_service_entry(vol["id"], cycle["id"], 4.0, "2026-08-05")

        resp = api.revoke_credit_entry(entry["id"], {"reason": "premature"},
                                       COORD)
        validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_APPROVED)

        resp = api.create_credit_entry(
            vol["id"], create_credit_entry_payload(
                cycle["id"], hours=2.0, activity_date="2027-02-01"), hdrs)
        validate_error(resp, ApiErrorId.ERR_ACTIVITY_OUTSIDE_CYCLE_WINDOW)

        payload = create_credit_entry_payload(cycle["id"], hours=2.0)
        del payload["activity_type"]
        resp = api.create_credit_entry(vol["id"], payload, hdrs)
        validate_error(resp, ApiErrorId.ERR_MISSING_KIND_FIELDS)

        after = get_success_data(api.get_credit_entry(entry["id"], COORD))
        assert after["status"] == "PENDING"


class TestTotalsVariants:
    def test_service_hours_provisional_includes_pending_no_cap(self, api):
        """PRD §3.3: "The provisional variant includes undecided work:
        `provisional_service_hours` sums the `hours` of `SERVICE` entries in
        `PENDING` or `APPROVED` status, and `provisional_ce_hours` does the
        same for `CONTINUING_ED` entries, with no caps of any kind."

        Design: Difficulty/dual_variant_calc/service_hours_provisional_vs_official_project_cap
        """
        cycle, vol, rec = setup_cycle_with_active_volunteer()
        proj = create_approved_project(cycle["id"], vol["id"],
                                       estimated_hours_per_volunteer=10.0)
        # 10 OTHER approved + 8 PROJECT approved + 8 PROJECT approved + 5 OTHER pending
        log_and_approve_service_entry(vol["id"], cycle["id"], 10.0,
                                      "2026-08-05")
        log_and_approve_service_entry(vol["id"], cycle["id"], 8.0,
                                      "2026-08-06", activity_type="PROJECT",
                                      source_type="PROJECT",
                                      source_id=proj["id"])
        log_and_approve_service_entry(vol["id"], cycle["id"], 8.0,
                                      "2026-08-07", activity_type="PROJECT",
                                      source_type="PROJECT",
                                      source_id=proj["id"])
        log_service_entry(vol["id"], cycle["id"], 5.0, "2026-08-08")

        resp = api.evaluate_record(rec["id"], COORD)
        evaluated = validate_success(resp)
        # Provisional: 10 + 8 + 8 + 5 = 31.0 (PENDING included, no cap)
        assert evaluated["provisional_service_hours"] == pytest.approx(
            31.0, abs=0.01)

    def test_service_hours_official_truncates_at_project_cap(self, api):
        """PRD §3.3: "A running total starts at zero; each entry contributes
        the smaller of its own `hours` and the headroom remaining under the
        cap, which is zero once the cap is exhausted; the running total grows
        by each counted contribution, and hours beyond the cap are silently
        not credited."
        PRD §3.6: "`max_creditable_hours_per_volunteer` becomes the lesser of
        20.0 and the project's `estimated_hours_per_volunteer` multiplied by
        1.25 and rounded half-up to two decimal places"

        Design: Difficulty/dual_variant_calc/service_hours_provisional_vs_official_project_cap
        """
        cycle, vol, rec = setup_cycle_with_active_volunteer()
        proj = create_approved_project(cycle["id"], vol["id"],
                                       estimated_hours_per_volunteer=10.0)
        assert proj["max_creditable_hours_per_volunteer"] == pytest.approx(
            12.5, abs=0.01)
        log_and_approve_service_entry(vol["id"], cycle["id"], 10.0,
                                      "2026-08-05")
        log_and_approve_service_entry(vol["id"], cycle["id"], 8.0,
                                      "2026-08-06", activity_type="PROJECT",
                                      source_type="PROJECT",
                                      source_id=proj["id"])
        log_and_approve_service_entry(vol["id"], cycle["id"], 8.0,
                                      "2026-08-07", activity_type="PROJECT",
                                      source_type="PROJECT",
                                      source_id=proj["id"])
        log_service_entry(vol["id"], cycle["id"], 5.0, "2026-08-08")

        evaluated = validate_success(api.evaluate_record(rec["id"], COORD))
        # Official: 10.0 non-project + min(8.0+8.0, 12.5 cap) = 22.5
        assert evaluated["official_service_hours"] == pytest.approx(
            22.5, abs=0.01)
        assert evaluated["provisional_service_hours"] != \
            evaluated["official_service_hours"]

    def test_rejected_entries_excluded_from_all_totals(self, api):
        """PRD §3.3: "`REJECTED` and `VOIDED` entries count toward neither
        variant."

        Design: Corner/calculations/rejected_entries_excluded_from_all_totals
        """
        cycle, vol, rec = setup_cycle_with_active_volunteer()
        log_and_approve_service_entry(vol["id"], cycle["id"], 5.0,
                                      "2026-08-05")
        e2 = log_service_entry(vol["id"], cycle["id"], 7.0, "2026-08-06")
        reject_entry(e2["id"])
        log_service_entry(vol["id"], cycle["id"], 3.0, "2026-08-07")

        evaluated = validate_success(api.evaluate_record(rec["id"], COORD))
        assert evaluated["provisional_service_hours"] == pytest.approx(
            8.0, abs=0.01)
        assert evaluated["official_service_hours"] == pytest.approx(
            5.0, abs=0.01)

    def test_ce_hours_totaled_separately_from_service(self, api):
        """PRD §3.3: "`official_ce_hours` sums `APPROVED` `CONTINUING_ED`
        hours, and `official_service_hours` sums `APPROVED` `SERVICE` hours
        with one carve-out — project-sourced hours are truncated per project
        under the cap described below, while all non-project approved service
        hours count in full."

        Design: Corner/calculations/ce_hours_totaled_separately_from_service
        """
        cycle, vol, rec = setup_cycle_with_active_volunteer()
        log_and_approve_service_entry(vol["id"], cycle["id"], 6.0,
                                      "2026-08-05")
        ce = log_ce_entry(vol["id"], cycle["id"], 4.0)
        approve_entry(ce["id"])

        evaluated = validate_success(api.evaluate_record(rec["id"], COORD))
        assert evaluated["official_service_hours"] == pytest.approx(
            6.0, abs=0.01)
        assert evaluated["official_ce_hours"] == pytest.approx(4.0, abs=0.01)
        assert evaluated["provisional_service_hours"] == pytest.approx(
            6.0, abs=0.01)
        assert evaluated["provisional_ce_hours"] == pytest.approx(4.0,
                                                                  abs=0.01)

    def test_double_approve_credit_entry_rejected(self, api):
        """PRD §3.3: "Approval of a `PENDING` entry (otherwise
        `ERR_ENTRY_NOT_PENDING`) against an `OPEN` cycle moves it to
        `APPROVED`, stamps `decided_at`, and recomputes both the
        volunteer-cycle record totals and the volunteer's recognition
        fields."

        Design: Corner/state_machines/double_approve_credit_entry_rejected
        """
        cycle, vol, rec = setup_cycle_with_active_volunteer()
        entry = log_service_entry(vol["id"], cycle["id"], 5.0, "2026-08-05")
        approve_entry(entry["id"])
        resp = api.approve_credit_entry(entry["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_PENDING)
        evaluated = validate_success(api.evaluate_record(rec["id"], COORD))
        assert evaluated["official_service_hours"] == pytest.approx(
            5.0, abs=0.01)

    def test_approve_then_evaluate_immediately_reflects_totals(self, api):
        """PRD §2.10: "The system maintains immediate consistency: every side
        effect of an operation is visible in the same response and in all
        follow-up reads."

        Design: Corner/consistency_model/approve_then_evaluate_immediately_reflects_totals
        """
        cycle, vol, rec = setup_cycle_with_active_volunteer()
        entry = log_service_entry(vol["id"], cycle["id"], 5.0, "2026-08-05")
        approve_entry(entry["id"])
        evaluated = validate_success(api.evaluate_record(rec["id"], COORD))
        assert evaluated["official_service_hours"] == pytest.approx(
            5.0, abs=0.01)

    def test_official_hours_conservation_approve_revoke(self, api):
        """PRD §3.3: "Revocation is the compensating action for approval: it
        requires an `APPROVED` entry (otherwise `ERR_ENTRY_NOT_APPROVED`),
        takes a mandatory `reason`, moves the entry `APPROVED → VOIDED`
        against an `OPEN` cycle, stamps `decided_at`, and recomputes record
        totals and recognition fields, so the official totals lose the
        revoked hours."

        Design: Difficulty/compensating_invariant/official_hours_conservation_approve_revoke
        """
        cycle, vol, rec = setup_cycle_with_active_volunteer()
        entry = log_service_entry(vol["id"], cycle["id"], 5.0, "2026-08-05")

        before = validate_success(api.evaluate_record(rec["id"], COORD))
        assert before["official_service_hours"] == pytest.approx(0.0,
                                                                 abs=0.01)
        approve_entry(entry["id"])
        mid = validate_success(api.evaluate_record(rec["id"], COORD))
        assert mid["official_service_hours"] == pytest.approx(5.0, abs=0.01)
        resp = api.revoke_credit_entry(
            entry["id"], {"reason": "logged against wrong cycle"}, COORD)
        validate_success(resp)
        after = validate_success(api.evaluate_record(rec["id"], COORD))
        assert after["official_service_hours"] == pytest.approx(0.0,
                                                                abs=0.01)

    def test_revoke_marks_entry_voided(self, api):
        """PRD §3.3: "Revocation is the compensating action for approval: it
        requires an `APPROVED` entry (otherwise `ERR_ENTRY_NOT_APPROVED`),
        takes a mandatory `reason`, moves the entry `APPROVED → VOIDED`
        against an `OPEN` cycle, stamps `decided_at`, and recomputes record
        totals and recognition fields, so the official totals lose the
        revoked hours."

        Design: Difficulty/compensating_invariant/official_hours_conservation_approve_revoke
        """
        cycle, vol, rec = setup_cycle_with_active_volunteer()
        entry = log_service_entry(vol["id"], cycle["id"], 5.0, "2026-08-05")
        approve_entry(entry["id"])
        resp = api.revoke_credit_entry(
            entry["id"], {"reason": "logged against wrong cycle"}, COORD)
        revoked = validate_success(resp)
        assert revoked["status"] == "VOIDED"


class TestRecognitionTierAndPoints:
    def test_recognition_tier_reads_unmultiplied_base_at_gold_boundary(
            self, api):
        """PRD §3.8: "Second, `recognition_tier` is read from that base:
        `GOLD` when the base has reached 40.0, otherwise `SILVER` when it has
        reached 20.0, otherwise `BRONZE`, with equality advancing the tier."

        Design: Difficulty/combinatorial_formula/recognition_tier_pinned_evaluation_order
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        for date in ("2026-08-05", "2026-08-06", "2026-08-07"):
            log_and_approve_service_entry(vol["id"], cycle["id"], 12.0, date)
        log_and_approve_service_entry(vol["id"], cycle["id"], 2.0,
                                      "2026-08-08")
        log_and_approve_service_entry(vol["id"], cycle["id"], 2.0,
                                      "2026-08-09", activity_type="OUTREACH")
        vol_after = get_success_data(api.get_volunteer(vol["id"], COORD))
        # Base = 38.0 + 2.0 outreach (unmultiplied) = 40.0 -> GOLD at equality
        assert vol_after["lifetime_base_hours"] == pytest.approx(40.0,
                                                                 abs=0.01)
        assert vol_after["recognition_tier"] == "GOLD"

    def test_recognition_points_apply_gold_outreach_bonus_after_tier(
            self, api):
        """PRD §3.8: "Third, `recognition_points` is the base plus, only when
        the tier is `GOLD`, one quarter of the current cycle's official
        `SERVICE` hours whose `activity_type` is `OUTREACH`."

        Design: Difficulty/combinatorial_formula/recognition_tier_pinned_evaluation_order
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        for date in ("2026-08-05", "2026-08-06", "2026-08-07"):
            log_and_approve_service_entry(vol["id"], cycle["id"], 12.0, date)
        log_and_approve_service_entry(vol["id"], cycle["id"], 2.0,
                                      "2026-08-08")
        log_and_approve_service_entry(vol["id"], cycle["id"], 2.0,
                                      "2026-08-09", activity_type="OUTREACH")
        vol_after = get_success_data(api.get_volunteer(vol["id"], COORD))
        # Points = 40.0 + 0.25 * 2.0 (GOLD outreach bonus) = 40.5
        assert vol_after["recognition_points"] == pytest.approx(40.5,
                                                                abs=0.01)


class TestHardshipAndCycleClose:
    def test_hardship_exemption_halves_effective_requirements(self, api):
        """PRD §3.8: "The effective requirements derive from the cycle's
        requirements and the hardship flag: each effective requirement is the
        corresponding cycle requirement multiplied by one-half when
        `hardship_exemption` is true and by one otherwise, then rounded
        half-up to the nearest quarter-hour."

        Design: Corner/calculations/hardship_exemption_halves_effective_requirements
        """
        cycle, vol, rec = setup_cycle_with_active_volunteer()
        resp = api.grant_exemption(rec["id"],
                                   {"reason": "documented medical hardship"},
                                   COORD)
        validate_success(resp)
        log_and_approve_service_entry(vol["id"], cycle["id"], 12.0,
                                      "2026-08-05")
        log_and_approve_service_entry(vol["id"], cycle["id"], 12.0,
                                      "2026-08-06")
        log_and_approve_service_entry(vol["id"], cycle["id"], 1.0,
                                      "2026-08-07")
        ce = log_ce_entry(vol["id"], cycle["id"], 6.0, title="IPM Basics")
        approve_entry(ce["id"])

        evaluated = validate_success(api.evaluate_record(rec["id"], COORD))
        assert evaluated["effective_hour_requirement"] == pytest.approx(
            20.0, abs=0.01)
        assert evaluated["effective_ce_requirement"] == pytest.approx(
            5.0, abs=0.01)

        move_cycle_to_recertification(cycle["id"])
        close_cycle(cycle["id"])
        rec_after = get_success_data(
            api.get_recertification_record(rec["id"], COORD))
        assert rec_after["status"] == "RECERTIFIED"
        vol_after = get_success_data(api.get_volunteer(vol["id"], COORD))
        assert vol_after["status"] == "ACTIVE"
        assert vol_after["consecutive_shortfall_cycles"] == 0

    def test_recertification_threshold_exact_equality_recertifies(self, api):
        """PRD §3.8: "each record's status is set to `RECERTIFIED` when its
        `official_service_hours` is at least its `effective_hour_requirement`
        and its `official_ce_hours` is at least its `effective_ce_requirement`,
        and to `SHORTFALL` otherwise, with equality passing — 40.0 hours
        against a 40.0 requirement recertifies while 39.75 shortfalls"

        Design: Difficulty/boundary_precision_check/recertification_threshold_exact_equality
        """
        cycle, vol, rec = setup_cycle_with_active_volunteer()
        for date, hours in (("2026-08-05", 12.0), ("2026-08-06", 12.0),
                            ("2026-08-07", 12.0), ("2026-08-08", 4.0)):
            log_and_approve_service_entry(vol["id"], cycle["id"], hours, date)
        ce = log_ce_entry(vol["id"], cycle["id"], 10.0, title="Advanced IPM")
        approve_entry(ce["id"])

        move_cycle_to_recertification(cycle["id"])
        close_cycle(cycle["id"])
        rec_after = get_success_data(
            api.get_recertification_record(rec["id"], COORD))
        assert rec_after["status"] == "RECERTIFIED"
        vol_after = get_success_data(api.get_volunteer(vol["id"], COORD))
        assert vol_after["status"] == "ACTIVE"
        assert vol_after["consecutive_shortfall_cycles"] == 0

    def test_recertification_one_quantum_below_shortfalls(self, api):
        """PRD §3.8: "each record's status is set to `RECERTIFIED` when its
        `official_service_hours` is at least its `effective_hour_requirement`
        and its `official_ce_hours` is at least its `effective_ce_requirement`,
        and to `SHORTFALL` otherwise, with equality passing — 40.0 hours
        against a 40.0 requirement recertifies while 39.75 shortfalls"

        Design: Difficulty/boundary_precision_check/recertification_threshold_exact_equality
        """
        cycle, vol, rec = setup_cycle_with_active_volunteer()
        for date, hours in (("2026-08-05", 12.0), ("2026-08-06", 12.0),
                            ("2026-08-07", 12.0), ("2026-08-08", 3.75)):
            log_and_approve_service_entry(vol["id"], cycle["id"], hours, date)
        ce = log_ce_entry(vol["id"], cycle["id"], 10.0, title="Advanced IPM")
        approve_entry(ce["id"])

        move_cycle_to_recertification(cycle["id"])
        close_cycle(cycle["id"])
        rec_after = get_success_data(
            api.get_recertification_record(rec["id"], COORD))
        assert rec_after["status"] == "SHORTFALL"
        vol_after = get_success_data(api.get_volunteer(vol["id"], COORD))
        assert vol_after["status"] == "INACTIVE"
        assert vol_after["consecutive_shortfall_cycles"] == 1

    def test_grant_exemption_after_close_returns_409(self, api):
        """PRD §3.8: "A coordinator grants the exemption on a `PENDING`
        record — a finalized record fails here with `ERR_RECORD_NOT_PENDING`
        as well — by supplying a `reason`"

        Design: Corner/errors/grant_exemption_after_close_returns_409
        """
        cycle, vol, rec = setup_cycle_with_active_volunteer()
        move_cycle_to_recertification(cycle["id"])
        close_cycle(cycle["id"])

        resp = api.grant_exemption(rec["id"], {"reason": "too late"}, COORD)
        validate_error(resp, ApiErrorId.ERR_RECORD_NOT_PENDING)
        rec_after = get_success_data(
            api.get_recertification_record(rec["id"], COORD))
        assert rec_after["status"] == "SHORTFALL"
        assert rec_after["hardship_exemption"] is False


class TestCrossEntityPosture:
    def test_entry_approve_blocked_by_cycle_posture_error(self, api):
        """PRD §3.1: "Once the cycle enters `RECERTIFICATION`, all
        credit-entry writes for that cycle — creation, approval, rejection,
        and revocation — freeze, and any further attempt fails with
        `ERR_CYCLE_NOT_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/entry_approve_blocked_by_cycle_posture
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        entry = log_service_entry(vol["id"], cycle["id"], 4.0, "2026-08-05")
        move_cycle_to_recertification(cycle["id"])

        resp = api.approve_credit_entry(entry["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_OPEN)

    def test_entry_approve_blocked_by_cycle_posture_entry_untouched(self, api):
        """PRD §3.1: "Once the cycle enters `RECERTIFICATION`, all
        credit-entry writes for that cycle — creation, approval, rejection,
        and revocation — freeze, and any further attempt fails with
        `ERR_CYCLE_NOT_OPEN`."
        PRD §3.3: "The entry begins in `PENDING`"

        Design: Difficulty/cross_entity_state_dependency/entry_approve_blocked_by_cycle_posture
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        entry = log_service_entry(vol["id"], cycle["id"], 4.0, "2026-08-05")
        move_cycle_to_recertification(cycle["id"])

        api.approve_credit_entry(entry["id"], COORD)
        after = get_success_data(api.get_credit_entry(entry["id"], COORD))
        assert after["status"] == "PENDING"

    def test_volunteer_state_beats_temporal_window_control_active(self, api):
        """PRD §2.9: "The sequence is: ... (11) clock and window rules —
        `ERR_ACTIVITY_OUTSIDE_CYCLE_WINDOW` at HTTP 422 and the remaining
        window errors at HTTP 409; ..."
        PRD §3.3: "`activity_date` must fall inside the cycle's inclusive
        `start_date`-to-`end_date` window; a date outside the window fails
        with `ERR_ACTIVITY_OUTSIDE_CYCLE_WINDOW` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/volunteer_state_beats_temporal_window
        """
        # Control leg of the same pair: with the volunteer ACTIVE (tier 8
        # passes), the same out-of-window activity_date reaches tier 11 and
        # surfaces the temporal error — confirming the pair's two error ids
        # each fire when they are the first failing tier.
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        assert vol["status"] == "ACTIVE"
        resp = api.create_credit_entry(
            vol["id"],
            create_credit_entry_payload(cycle["id"], hours=2.0,
                                        activity_date="2025-06-01"),
            make_volunteer_headers(vol["id"]))
        validate_error(resp, ApiErrorId.ERR_ACTIVITY_OUTSIDE_CYCLE_WINDOW)

    def test_volunteer_state_beats_temporal_window(self, api):
        """PRD §2.9: "The sequence is: ... (8) target-resource state — the
        family of transition-guard errors detailed per workflow in §3 ...;
        ... (11) clock and window rules — `ERR_ACTIVITY_OUTSIDE_CYCLE_WINDOW`
        at HTTP 422 and the remaining window errors at HTTP 409; ..."
        PRD §3.3: "the volunteer must be `ACTIVE` (otherwise
        `ERR_VOLUNTEER_NOT_ACTIVE`)"

        Design: Difficulty/priority_pair_validation_conflict/volunteer_state_beats_temporal_window
        """
        cycle1, vol = setup_cycle_closed_with_shortfall_volunteer()
        assert vol["status"] == "INACTIVE"
        cycle2 = create_and_open_cycle(year_label="2027",
                                       start_date="2027-01-01",
                                       end_date="2027-12-31",
                                       recert_opens_at="2027-11-01T00:00:00Z")
        resp = api.create_credit_entry(
            vol["id"],
            create_credit_entry_payload(cycle2["id"], hours=2.0,
                                        activity_date="2025-06-01"),
            make_volunteer_headers(vol["id"]))
        # State (tier 8) runs before the activity-window rule (tier 11).
        validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_ACTIVE)
