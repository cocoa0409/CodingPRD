"""State machines whose current state does not predict the next legal move.

An allocation round re-enters drafting by two different edges before it adopts,
and a settlement instrument carries a legal axis and a compliance axis that
advance independently of one another.
"""
from test_helpers.assertions import assert_percentage, assert_share_totals
from test_helpers.fixtures import (
    add_verified_waste_in,
    cast_ballot,
    create_decree,
    create_investigation,
    create_listed_site,
    create_participating_party,
    enter_decree,
    lodge_decree,
    open_balloting,
    open_round,
    read_round,
    read_site,
    record_cure,
    record_penalty_assessment,
    record_violation,
    reopen_round,
    set_clock,
    share_for,
)

FIRST_REVISION_NOTE = "Reopened before the second ballot to re-brief the parties."
SECOND_REVISION_NOTE = "Reopened out of FAILED after mediation."


def _harlow_bend_round():
    """A drafting round over two parties whose shares are 99.28 and 0.72.

    No ownership period exists, so the ownership factor total is zero, that
    weight renormalises away and the remaining two factors carry the split.
    """
    set_clock("2027-02-01T09:00:00Z")
    site = create_listed_site(
        name="Harlow Bend Drum Salvage", epa_region=3, hrs_score=44.60
    )
    prp_a = create_participating_party(
        site["id"],
        legal_name="Harlow Chemical Works",
        party_type="OWNER_OPERATOR",
        viability_score=85,
    )
    prp_b = create_participating_party(
        site["id"],
        legal_name="Bend Print Shop LLC",
        party_type="GENERATOR",
        viability_score=22,
    )
    add_verified_waste_in(site["id"], prp_a["id"], 3960, "II", "A", 1974)
    add_verified_waste_in(site["id"], prp_b["id"], 40, "IV", "B", 1989)
    create_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        scope_summary="OU-1 soil and groundwater",
    )
    allocation_round = open_round(site["id"], weights=(5000, 3000, 2000))
    return site, prp_a, prp_b, allocation_round


class TestAllocationRoundCyclesBeforeAdoption:
    def test_reopening_from_balloting_clears_a_partial_ballot_and_returns_to_drafting(self):
        """Reopening mid-ballot restores the drafting state and the right to vote.

        PRD: "Reopening clears `ballot`, `ballot_rationale` and `ballot_cast_at` on every share, resets `balloted_count` to 0 and `accept_share_pct` to 0.00, re-derives `provisional_pct` against current data, and mints shares for any party that has entered the candidate set since the round was opened."

        Design: Difficulty/non_linear_state_machine/allocation_round_cycles_balloting_failed_drafting_before_adoption
        """
        _, prp_a, prp_b, allocation_round = _harlow_bend_round()
        round_id = allocation_round["id"]
        assert_percentage(
            share_for(round_id, prp_a["id"])["provisional_pct"], 99.28, "provisional_pct"
        )
        assert_percentage(
            share_for(round_id, prp_b["id"])["provisional_pct"], 0.72, "provisional_pct"
        )

        open_balloting(round_id)
        cast_ballot(round_id, prp_a["id"], "REJECT", "Volumetric weight too high.")
        reopened = reopen_round(round_id, FIRST_REVISION_NOTE)

        assert reopened["status"] == "DRAFTING"
        assert reopened["balloted_count"] == 0
        assert_percentage(reopened["accept_share_pct"], 0.00, "accept_share_pct")
        assert reopened["revision_note"] == FIRST_REVISION_NOTE
        share_a = share_for(round_id, prp_a["id"])
        assert share_a["ballot"] in (None, "")
        assert share_a["ballot_cast_at"] in (None, "")

    def test_a_failing_vote_leaves_every_disposition_pending_without_a_final_percentage(self):
        """An acceptance weight of 0.72 fails the two-thirds threshold.

        PRD: "Otherwise it moves `BALLOTING → FAILED`, no `final_pct` is stamped anywhere, and every share keeps its `disposition` at `PENDING`."

        Design: Difficulty/non_linear_state_machine/allocation_round_cycles_balloting_failed_drafting_before_adoption
        """
        _, prp_a, prp_b, allocation_round = _harlow_bend_round()
        round_id = allocation_round["id"]
        open_balloting(round_id)
        cast_ballot(round_id, prp_a["id"], "REJECT", "Volumetric weight too high.")
        reopen_round(round_id, FIRST_REVISION_NOTE)

        open_balloting(round_id)
        cast_ballot(round_id, prp_a["id"], "REJECT")
        cast_ballot(round_id, prp_b["id"], "ACCEPT")

        failed = read_round(round_id)
        assert failed["status"] == "FAILED"
        assert failed["balloted_count"] == 2
        assert_percentage(failed["accept_share_pct"], 0.72, "accept_share_pct")
        share_a = share_for(round_id, prp_a["id"])
        assert share_a["disposition"] == "PENDING"
        assert share_a["final_pct"] in (None, "")

    def test_reopening_out_of_failed_uses_the_same_clearing_as_reopening_from_balloting(self):
        """The failed state is not terminal; the second reopening edge behaves alike.

        PRD: "Both reopening paths — from balloting and from failure — perform exactly the same clearing and recomputation."

        Design: Difficulty/non_linear_state_machine/allocation_round_cycles_balloting_failed_drafting_before_adoption
        """
        _, prp_a, prp_b, allocation_round = _harlow_bend_round()
        round_id = allocation_round["id"]
        open_balloting(round_id)
        cast_ballot(round_id, prp_a["id"], "REJECT", "Volumetric weight too high.")
        reopen_round(round_id, FIRST_REVISION_NOTE)
        open_balloting(round_id)
        cast_ballot(round_id, prp_a["id"], "REJECT")
        cast_ballot(round_id, prp_b["id"], "ACCEPT")

        reopened = reopen_round(round_id, SECOND_REVISION_NOTE)

        assert reopened["status"] == "DRAFTING"
        assert reopened["balloted_count"] == 0
        assert_percentage(reopened["accept_share_pct"], 0.00, "accept_share_pct")
        assert reopened["revision_note"] == SECOND_REVISION_NOTE

    def test_the_third_balloting_cycle_adopts_the_same_round_number_one(self):
        """Three balloting cycles later the same round adopts without renumbering.

        PRD: "If `accept_share_pct` is at least 66.67 — two thirds of the allocated liability, with exact equality adopting — the round moves `BALLOTING → ADOPTED`."

        Design: Difficulty/non_linear_state_machine/allocation_round_cycles_balloting_failed_drafting_before_adoption
        """
        site, prp_a, prp_b, allocation_round = _harlow_bend_round()
        round_id = allocation_round["id"]
        open_balloting(round_id)
        cast_ballot(round_id, prp_a["id"], "REJECT", "Volumetric weight too high.")
        reopen_round(round_id, FIRST_REVISION_NOTE)
        open_balloting(round_id)
        cast_ballot(round_id, prp_a["id"], "REJECT")
        cast_ballot(round_id, prp_b["id"], "ACCEPT")
        reopen_round(round_id, SECOND_REVISION_NOTE)

        open_balloting(round_id)
        cast_ballot(round_id, prp_a["id"], "ACCEPT")
        cast_ballot(round_id, prp_b["id"], "ACCEPT")

        adopted = read_round(round_id)
        assert adopted["status"] == "ADOPTED"
        assert_percentage(adopted["accept_share_pct"], 100.00, "accept_share_pct")
        assert adopted["round_number"] == 1
        share_a = share_for(round_id, prp_a["id"])
        share_b = share_for(round_id, prp_b["id"])
        assert_percentage(share_a["final_pct"], 99.28, "final_pct")
        assert share_a["disposition"] == "ALLOCATED"
        assert_percentage(share_b["final_pct"], 0.72, "final_pct")
        assert share_b["disposition"] == "ALLOCATED"
        assert_share_totals(adopted, 100.00, 0.00, 0.00)
        assert read_site(site["id"])["adopted_round_id"] == round_id


def _ridgeline_entered_decree():
    """An entered decree over an adopted allocation at a two-party site."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_listed_site(name="Ridgeline Fibre Mill", epa_region=1, hrs_score=47.85)
    prp_a = create_participating_party(
        site["id"], legal_name="Ridgeline Paper Co", party_type="OWNER_OPERATOR", viability_score=88
    )
    prp_b = create_participating_party(
        site["id"], legal_name="Cobalt Ink Supply LLC", party_type="GENERATOR", viability_score=30
    )
    add_verified_waste_in(site["id"], prp_a["id"], 3960, "II", "A", 1976)
    add_verified_waste_in(site["id"], prp_b["id"], 40, "IV", "B", 1991)
    create_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        scope_summary="OU-1 lagoon sludge and groundwater",
    )
    allocation_round = open_round(site["id"], weights=(5000, 3000, 2000))
    open_balloting(allocation_round["id"])
    cast_ballot(allocation_round["id"], prp_a["id"], "ACCEPT")
    cast_ballot(allocation_round["id"], prp_b["id"], "ACCEPT")
    decree = create_decree(
        site["id"],
        [prp_a["id"], prp_b["id"]],
        scope_type="RD_RA_CONSENT_DECREE",
        scope_summary="RD/RA for OU-1 with EPA oversight reimbursement",
        oversight_cost_cap_cents=250_000_000,
        stipulated_penalty_per_day_cents=250_000,
        performance_deadline="2028-06-30",
    )
    set_clock("2027-03-01T10:00:00Z")
    lodged = lodge_decree(decree["id"])
    set_clock("2027-04-01T09:00:00Z")
    entered = enter_decree(decree["id"], court_docket_number="1:27-cv-00418-RFM")
    return site, decree, lodged, entered


class TestDecreeLegalAndComplianceAxesAdvanceIndependently:
    def test_lodging_derives_the_comment_close_and_entry_derives_the_penalty_cap(self):
        """Lodging sets a thirty-day window and entry stamps ten percent of the cap.

        PRD: "Lodging stamps `lodged_at` with the logical clock and derives `public_comment_close_at` as 30 days after that instant."

        Design: Difficulty/non_linear_state_machine/consent_decree_legal_and_compliance_dimensions_advance_independently
        """
        _, _, lodged, entered = _ridgeline_entered_decree()

        assert lodged["lodged_at"].startswith("2027-03-01T10:00:00")
        assert lodged["public_comment_close_at"].startswith("2027-03-31T10:00:00")
        assert entered["penalty_cap_cents"] == 25_000_000
        assert entered["legal_status"] == "ENTERED"

    def test_a_violation_restricts_the_site_without_moving_the_legal_axis(self):
        """The compliance axis moves to in-violation while the legal axis stays entered.

        PRD: "Because an open violation is one of the four restriction triggers, the site's `cost_posture` is recomputed and becomes `RESTRICTED`, which halts new contract awards and new work windows but leaves oversight billing and recovery actions untouched."

        Design: Difficulty/non_linear_state_machine/consent_decree_legal_and_compliance_dimensions_advance_independently
        """
        site, decree, _, _ = _ridgeline_entered_decree()
        set_clock("2027-04-05T08:00:00Z")
        after = record_violation(
            decree["id"], "2027-04-05T00:00:00Z", violation_type="MISSED_MILESTONE"
        )

        assert after["compliance_status"] == "IN_VIOLATION"
        assert after["legal_status"] == "ENTERED"
        assert after["first_noncompliance_date"].startswith("2027-04-05")
        assert after["open_violation_count"] == 1
        assert after["violation_type"] == "MISSED_MILESTONE"
        assert read_site(site["id"])["cost_posture"] == "RESTRICTED"

    def test_the_first_assessment_accrues_forty_six_days_and_freezes_the_site(self):
        """Days in violation count both endpoints, so 5 April to 20 May is 46 days.

        PRD: "The `days_in_violation` count is the number of days from `first_noncompliance_date` through the event's `effective_at` **inclusive of both endpoints**, so 1 March 2027 through 30 March 2027 is 30 days."

        Design: Difficulty/non_linear_state_machine/consent_decree_legal_and_compliance_dimensions_advance_independently
        """
        site, decree, _, _ = _ridgeline_entered_decree()
        set_clock("2027-04-05T08:00:00Z")
        record_violation(decree["id"], "2027-04-05T00:00:00Z", violation_type="MISSED_MILESTONE")
        set_clock("2027-05-20T08:00:00Z")
        after = record_penalty_assessment(decree["id"], "2027-05-20T00:00:00Z")

        assert after["compliance_status"] == "PENALTY_ACCRUING"
        assert after["legal_status"] == "ENTERED"
        assert after["days_in_violation"] == 46
        assert after["accrued_penalty_cents"] == 13_500_000
        assert after["penalty_capped"] is False
        assert read_site(site["id"])["cost_posture"] == "FROZEN"

    def test_a_second_assessment_recomputes_the_accrual_instead_of_adding_to_it(self):
        """The self-loop replaces the earlier accrual rather than accumulating.

        PRD: "**Repeat assessments recompute the whole accrual from `first_noncompliance_date`; they never add to the previous figure.**"

        Design: Difficulty/non_linear_state_machine/consent_decree_legal_and_compliance_dimensions_advance_independently
        """
        _, decree, _, _ = _ridgeline_entered_decree()
        set_clock("2027-04-05T08:00:00Z")
        record_violation(decree["id"], "2027-04-05T00:00:00Z", violation_type="MISSED_MILESTONE")
        set_clock("2027-05-20T08:00:00Z")
        record_penalty_assessment(decree["id"], "2027-05-20T00:00:00Z")
        set_clock("2027-05-25T08:00:00Z")
        after = record_penalty_assessment(decree["id"], "2027-05-25T00:00:00Z")

        assert after["days_in_violation"] == 51
        assert after["accrued_penalty_cents"] == 15_375_000
        assert after["accrued_penalty_cents"] != 28_875_000
        assert after["legal_status"] == "ENTERED"

    def test_a_cure_clears_the_compliance_axis_and_never_enters_the_recovery_ledger(self):
        """Penalty money settles the books but is punitive, not recovered cost.

        PRD: "As §2.10 states, penalty money paid on a cure is punitive: it does **not** increase the site's `recovered_cost_cents` and does not reduce `unrecovered_cost_cents`."

        Design: Difficulty/non_linear_state_machine/consent_decree_legal_and_compliance_dimensions_advance_independently
        """
        site, decree, _, _ = _ridgeline_entered_decree()
        set_clock("2027-04-05T08:00:00Z")
        record_violation(decree["id"], "2027-04-05T00:00:00Z", violation_type="MISSED_MILESTONE")
        set_clock("2027-05-20T08:00:00Z")
        record_penalty_assessment(decree["id"], "2027-05-20T00:00:00Z")
        set_clock("2027-05-25T08:00:00Z")
        record_penalty_assessment(decree["id"], "2027-05-25T00:00:00Z")

        after = record_cure(decree["id"], 15_375_000, "2027-05-26T00:00:00Z")

        assert after["compliance_status"] == "COMPLIANT"
        assert after["paid_penalty_cents"] == 15_375_000
        assert after["first_noncompliance_date"] in (None, "")
        assert after["last_assessment_at"] in (None, "")
        assert after["days_in_violation"] == 0
        assert after["open_violation_count"] == 0
        assert after["legal_status"] == "ENTERED"
        assert after["terminated_at"] in (None, "")
        site_after = read_site(site["id"])
        assert site_after["cost_posture"] == "OPEN"
        assert site_after["recovered_cost_cents"] == 0
