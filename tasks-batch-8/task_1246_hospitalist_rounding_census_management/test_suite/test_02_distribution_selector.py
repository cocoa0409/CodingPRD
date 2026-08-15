"""Admission distribution selector tests: clamped continuity score, leveling
evaluation order, tie-breaks, empty pool fallback, decliner exclusion.
"""
import pytest

from test_helpers import (
    validate_success, get_success_data, ApiErrorId,
    TEST_USERS, make_hospitalist_headers,
    set_clock, create_hospitalist, create_patient, create_shift,
    admit_and_accept, discharge_patient,
)

ADMIN = TEST_USERS["group_admin_headers"]


class TestDistributionScoreClampedContinuity:
    """Difficulty instance: distribution_score_clamped_continuity."""

    def _setup_continuity_scenario(self, api):
        """H_A cap 4 DAY 07-19 with census 1; H_B cap 1 DAY 06-18 with census 0
        after discharging P1 (CLOSED within 30 days -> continuity for H_B)."""
        h_a = create_hospitalist("H A", "INTERNAL_MEDICINE", max_census_cap=4)
        h_b = create_hospitalist("H B", "FAMILY_MEDICINE", max_census_cap=1)
        s_a = create_shift(h_a["id"], "DAY", "2026-05-01T07:00:00Z", "2026-05-01T19:00:00Z", activate=True)
        s_b = create_shift(h_b["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        # First patient: tie 1.0 vs 1.0 -> H_B wins (earlier shift start)
        p1 = create_patient(mrn="M201", acuity="MEDIUM", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:30:00Z")
        a1 = get_success_data(api.create_admission({"patient_id": p1["id"]}, ADMIN))
        assert a1["offered_to_hospitalist_id"] == h_b["id"]
        get_success_data(api.accept_admission(a1["id"], make_hospitalist_headers(h_b["id"])))
        # H_B now at cap 1
        # Second patient goes to H_A
        p2 = create_patient(mrn="M202", acuity="LOW", admit_source="DIRECT",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:35:00Z")
        a2 = get_success_data(api.create_admission({"patient_id": p2["id"]}, ADMIN))
        assert a2["offered_to_hospitalist_id"] == h_a["id"]
        get_success_data(api.accept_admission(a2["id"], make_hospitalist_headers(h_a["id"])))
        # Discharge P1 from H_B -> CLOSED assignment seeds continuity
        discharge_patient(p1["id"], h_b["id"], target_discharge_at="2026-05-02T15:00:00Z")
        return h_a, h_b, p1

    def test_continuity_clamped_score_wins(self, api):
        """PRD §3.3: "Add a continuity bonus of 0.25 when the continuity
        predicate holds — that is, when a `CLOSED` assignment exists pairing
        this candidate with this patient whose `closed_at` lies within 30 days
        of now. Take the smaller of that sum and 1.0."

        Design: Difficulty/combinatorial_formula/distribution_score_clamped_continuity
        """
        h_a, h_b, p1 = self._setup_continuity_scenario(api)
        # Re-admit P1; H_B has census 0, cap 1, continuity bonus applies
        a3 = get_success_data(api.create_admission({"patient_id": p1["id"]}, ADMIN))
        assert a3["status"] == "OFFERED"
        assert a3["offered_to_hospitalist_id"] == h_b["id"]
        # raw: (1-0)/1 + 0.25 = 1.25, clamped to 1.0
        assert a3["distribution_score"] == pytest.approx(1.0, abs=0.0001)

    def test_loser_lower_score_not_selected(self, api):
        """PRD §3.3: "Scoring rewards spare capacity and continuity while
        taxing night load. Start with the candidate's remaining-capacity
        fraction: `max_census_cap` minus `current_census`, divided by
        `max_census_cap`."
        PRD §3.3: "Candidates rank by score descending".

        Design: Difficulty/combinatorial_formula/distribution_score_clamped_continuity
        """
        h_a, h_b, p1 = self._setup_continuity_scenario(api)
        a3 = get_success_data(api.create_admission({"patient_id": p1["id"]}, ADMIN))
        # H_A scores (4-1)/4 = 0.75; H_B clamps at 1.0. Winner is H_B.
        assert a3["offered_to_hospitalist_id"] == h_b["id"]
        assert a3["offered_to_hospitalist_id"] != h_a["id"]


class TestLevelingGroupAvgFromCurrentOnly:
    """Difficulty instance: leveling_group_avg_from_current_only.

    Setup shape: H1 holds two accepted patients (current census 2); H2 holds
    none; P3 is queued and offered to H2 but left un-accepted. The report is
    then read at a moment when H1 and H2 both hold ACTIVE shifts covering now.
    """

    def _setup_leveling_scenario(self, api):
        # Create both hospitalists but only H1's shift covers the early window.
        h1 = create_hospitalist("H One", "INTERNAL_MEDICINE", max_census_cap=16)
        h2 = create_hospitalist("H Two", "FAMILY_MEDICINE", max_census_cap=16)
        s1 = create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        # H2's shift becomes ACTIVE but does not cover the early admission window;
        # we will later move the clock into H2's coverage for the report read.
        s2 = create_shift(h2["id"], "DAY", "2026-05-01T10:00:00Z", "2026-05-01T22:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        # P1 -> H1 (only eligible)
        p1 = create_patient(mrn="M401", acuity="MEDIUM", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
        a1 = get_success_data(api.create_admission({"patient_id": p1["id"]}, ADMIN))
        assert a1["offered_to_hospitalist_id"] == h1["id"]
        get_success_data(api.accept_admission(a1["id"], make_hospitalist_headers(h1["id"])))
        # P2 -> H1 again (H2 still has no covering ACTIVE shift at 09:00)
        p2 = create_patient(mrn="M402", acuity="LOW", admit_source="DIRECT",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:10:00Z")
        a2 = get_success_data(api.create_admission({"patient_id": p2["id"]}, ADMIN))
        assert a2["offered_to_hospitalist_id"] == h1["id"]
        get_success_data(api.accept_admission(a2["id"], make_hospitalist_headers(h1["id"])))
        # Move clock into H2's coverage window; now queue P3. H1 scores
        # (16-2)/16 = 0.875; H2 scores 1.0 -> offered to H2.
        set_clock("2026-05-01T11:00:00Z")
        p3 = create_patient(mrn="M403", acuity="HIGH", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:20:00Z")
        a3 = get_success_data(api.create_admission({"patient_id": p3["id"]}, ADMIN))
        assert a3["status"] == "OFFERED"
        assert a3["offered_to_hospitalist_id"] == h2["id"]
        return h1, h2, p1, p2, p3, a1, a2, a3

    def test_group_avg_uses_current_census_only(self, api):
        """PRD §3.4: "`group_avg_census` is the sum of current census across
        that set divided by the larger of 1 and the set's size — computed
        from current census only, never from projections."

        Design: Difficulty/combinatorial_formula/leveling_group_avg_from_current_only
        """
        h1, h2, p1, p2, p3, a1, a2, a3 = self._setup_leveling_scenario(api)
        report = get_success_data(api.get_census_leveling_report(ADMIN))
        # current census totals 2 (H1=2, H2=0) over 2 eligible -> 1.0.
        # A projection-fed average would yield (2+1)/2 = 1.5 — rejected by the PRD.
        assert report["group_avg_census"] == pytest.approx(1.0, abs=0.0001)

    def test_projected_census_adds_outstanding_offers(self, api):
        """PRD §3.4: "each eligible hospitalist's projected census adds their
        outstanding offers — admissions in status `OFFERED` naming them — to
        current census".
        PRD §3.4: "`leveling_needed` is true when the largest absolute
        deviation across the group exceeds 0.15."

        Design: Difficulty/combinatorial_formula/leveling_group_avg_from_current_only
        """
        h1, h2, p1, p2, p3, a1, a2, a3 = self._setup_leveling_scenario(api)
        report = get_success_data(api.get_census_leveling_report(ADMIN))
        rows = {r["hospitalist_id"]: r for r in report["rows"]}
        assert rows[h1["id"]]["current_census"] == 2
        assert rows[h1["id"]]["projected_census"] == 2
        assert rows[h2["id"]]["current_census"] == 0
        # one OFFERED admission -> projected_census 1 for H2
        assert rows[h2["id"]]["projected_census"] == 1
        # leveling_needed: max |dev| = max(|2-1|/1, |1-1|/1) = 1.0 > 0.15
        assert report["leveling_needed"] is True


class TestDistributionTieBreakShiftCreatedAt:
    """Corner instance: distribution_tie_break_shift_created_at."""

    def test_earliest_created_shift_wins_final_tiebreak(self, api):
        """PRD §3.3: "Candidates rank by score descending; ties break toward
        the lower `current_census`, then toward the candidate whose covering
        shift has the earlier `start_at`, then toward the candidate whose
        covering shift has the earlier `created_at` — never by hospitalist id."

        Design: Corner/calculations/distribution_tie_break_shift_created_at
        """
        h_a = create_hospitalist("H A", "ICU", max_census_cap=16)
        h_c = create_hospitalist("H C", "INTERNAL_MEDICINE", max_census_cap=16)
        # Create H_A's shift first (created_at earlier by one logical second).
        set_clock("2026-05-01T06:00:00Z")
        s_a = create_shift(h_a["id"], "DAY", "2026-05-01T07:00:00Z", "2026-05-01T19:00:00Z")
        set_clock("2026-05-01T06:00:01Z")
        s_c = create_shift(h_c["id"], "DAY", "2026-05-01T07:00:00Z", "2026-05-01T19:00:00Z")
        # Activate both
        get_success_data(api.activate_shift(s_a["id"], ADMIN))
        get_success_data(api.activate_shift(s_c["id"], ADMIN))
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="K009", acuity="LOW", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:30:00Z")
        a1 = get_success_data(api.create_admission({"patient_id": p1["id"]}, ADMIN))
        # Equal score 1.0, equal census 0, equal shift start_at -> shift created_at decides.
        assert a1["offered_to_hospitalist_id"] == h_a["id"]
        assert a1["distribution_score"] == pytest.approx(1.0, abs=0.0001)


class TestDistributionEmptyPoolStaysQueued:
    """Corner instance: distribution_empty_pool_stays_queued."""

    def test_empty_pool_no_error(self, api):
        """PRD §3.3: "When the pool is empty the admission simply remains
        `QUEUED` with a null `offered_to_hospitalist_id` — a documented
        fallback, not an error — and waits for capacity, a shift change, or a
        decline elsewhere to change the picture."
        PRD §3.3: "The new row starts `QUEUED` with `offered_to_hospitalist_id`
        null, `declined_hospitalist_ids` empty, `distribution_score` null, and
        `assignment_id` null."

        Design: Corner/calculations/distribution_empty_pool_stays_queued
        """
        create_hospitalist("H One", "ICU")  # exists but has no shift
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="K010", acuity="LOW", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:30:00Z")
        resp = api.create_admission({"patient_id": p1["id"]}, ADMIN)
        a1 = validate_success(resp, expected_status=201)
        assert a1["status"] == "QUEUED"
        assert a1["offered_to_hospitalist_id"] is None
        assert a1["distribution_score"] is None


class TestDistributionExcludesDecliner:
    """Corner instance: distribution_excludes_decliner."""

    def test_decline_reruns_selector_excluding_decliner(self, api):
        """PRD §3.3: "The caller's id is appended to `declined_hospitalist_ids`,
        `offered_to_hospitalist_id` and `distribution_score` are cleared, the
        decliner's `pending_offers` decrements, and the admission returns
        `OFFERED` → `QUEUED` — at which point the selector immediately
        re-runs, excluding every decliner, so a `QUEUED` → `OFFERED` hop to
        the next candidate may land inside the very same request."
        PRD §3.3: "the hospitalist's id does not appear in this admission's
        `declined_hospitalist_ids`".

        Design: Corner/calculations/distribution_excludes_decliner
        """
        h_a = create_hospitalist("H A", "ICU", max_census_cap=16)
        h_b = create_hospitalist("H B", "INTERNAL_MEDICINE", max_census_cap=16)
        s_a = create_shift(h_a["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        s_b = create_shift(h_b["id"], "DAY", "2026-05-01T07:00:00Z", "2026-05-01T19:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="K011", acuity="LOW", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:30:00Z")
        a1 = get_success_data(api.create_admission({"patient_id": p1["id"]}, ADMIN))
        assert a1["offered_to_hospitalist_id"] == h_a["id"]  # earlier shift start

        # H_A declines -> re-run excludes H_A -> offered to H_B
        after = get_success_data(api.decline_admission(a1["id"], make_hospitalist_headers(h_a["id"])))
        assert after["status"] == "OFFERED"
        assert after["offered_to_hospitalist_id"] == h_b["id"]
        assert h_a["id"] in after["declined_hospitalist_ids"]

        # pending_offers: H_A decremented back to 0, H_B incremented to 1
        h_a_now = get_success_data(api.get_hospitalist(h_a["id"], ADMIN))
        h_b_now = get_success_data(api.get_hospitalist(h_b["id"], ADMIN))
        assert h_a_now["pending_offers"] == 0
        assert h_b_now["pending_offers"] == 1
