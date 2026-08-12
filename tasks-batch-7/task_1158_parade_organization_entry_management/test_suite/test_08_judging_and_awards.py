"""Judging score variants, the sheet reopen cycle, award gating and the
deterministic winner selector."""
import pytest
import test_helpers as th
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, assert_entry, assert_score_sheet, assert_award,
)

COMMITTEE = th.make_committee_admin_headers()


def _approved_band_entry(parade_id, org_name="Sheet Band", entrant_id="entrant_1"):
    return th.create_approved_entry(parade_id, entrant_id, category="BAND", org_name=org_name)


class TestJudgingDualVariant:
    """Difficulty: judging_provisional_vs_final_trimmed_mean.
    Sheets totaling 70, 80, 81: provisional plain mean 77.00; final trimmed
    mean 80.00."""

    def _setup(self, api):
        parade = th.create_parade(name="July Parade")
        entry = _approved_band_entry(parade["id"], org_name="City Band")
        sh1 = th.create_submitted_sheet(entry["id"], "judge_1", 70)
        sh2 = th.create_submitted_sheet(entry["id"], "judge_2", 80)
        sh3 = th.create_submitted_sheet(entry["id"], "judge_3", 81)
        return parade, entry, (sh1, sh2, sh3)

    def test_provisional_score_plain_mean_over_submitted(self, api):
        """PRD §3.7: "Submitting a sheet — an action reserved to the owning
        judge, with `ERR_FORBIDDEN` for anyone else, and blocked while the
        parade is frozen — moves it from `DRAFT` to `SUBMITTED` and immediately
        recomputes the entry's `provisional_score`: the plain mean of
        `sheet_total` across all of the entry's sheets in `SUBMITTED` or
        `FINALIZED` status, or null while no such sheet exists."
        PRD §3.7: "Both score variants round half-up to 2 decimal places."

        Design: Difficulty/dual_variant_calc/judging_provisional_vs_final_trimmed_mean
        """
        _, entry, _ = self._setup(api)
        fetched = validate_success(api.get_entry(entry["id"], COMMITTEE))
        assert_entry(fetched)
        assert fetched["provisional_score"] == pytest.approx(77.00, abs=0.001), (
            f"plain mean of 70, 80, 81 must be 77.00, got {fetched['provisional_score']}"
        )
        assert fetched["final_score"] is None, "no FINALIZED sheets yet"

    def test_final_score_trimmed_mean_diverges_from_provisional(self, api):
        """PRD §3.7: "Each finalization recomputes the entry's `final_score`
        over `FINALIZED` sheets alone — when at least three sheets are
        finalized, the single highest and the single lowest `sheet_total` are
        each dropped once before averaging (a trimmed mean), while with one or
        two finalized sheets the score is their plain mean, and with none the
        score stays null."
        PRD §3.7: "Submitting a sheet — an action reserved to the owning judge,
        with `ERR_FORBIDDEN` for anyone else, and blocked while the parade is
        frozen — moves it from `DRAFT` to `SUBMITTED` and immediately
        recomputes the entry's `provisional_score`: the plain mean of
        `sheet_total` across all of the entry's sheets in `SUBMITTED` or
        `FINALIZED` status, or null while no such sheet exists."

        Design: Difficulty/dual_variant_calc/judging_provisional_vs_final_trimmed_mean
        """
        _, entry, sheets = self._setup(api)
        for sheet in sheets:
            get_success_data(api.finalize_score_sheet(sheet["id"], COMMITTEE))

        fetched = validate_success(api.get_entry(entry["id"], COMMITTEE))
        assert fetched["final_score"] == pytest.approx(80.00, abs=0.001), (
            f"trimmed mean drops 70 and 81 leaving 80.00, got {fetched['final_score']}"
        )
        assert fetched["provisional_score"] == pytest.approx(77.00, abs=0.001), (
            "FINALIZED sheets stay in the provisional set, so the variants "
            "diverge on identical data"
        )


class TestScoreSheetReopenCycle:
    """Difficulty: score_sheet_reopen_cycle."""

    def test_reopen_returns_to_draft_and_clears_provisional(self, api):
        """PRD §3.7: "Reopening, also reserved to the owning judge, moves a
        sheet from `SUBMITTED` back to `DRAFT` for revision and recomputes the
        provisional score as the sheet leaves the submitted set; reopening is
        refused once the parade has reached `COMPLETED` (`ERR_INVALID_STATE`)."

        Design: Difficulty/non_linear_state_machine/score_sheet_reopen_cycle
        """
        parade = th.create_parade(name="Sheet Parade")
        entry = _approved_band_entry(parade["id"])
        sheet = th.create_submitted_sheet(entry["id"], "judge_1", 80)

        reopened = validate_success(
            api.reopen_score_sheet(sheet["id"], th.make_judge_headers("judge_1"))
        )
        assert_score_sheet(reopened)
        assert reopened["status"] == "DRAFT", "the cycle back along SUBMITTED -> DRAFT"

        fetched = validate_success(api.get_entry(entry["id"], COMMITTEE))
        assert fetched["provisional_score"] is None, (
            "no SUBMITTED or FINALIZED sheets remain, so the provisional score is null"
        )

    def test_resubmit_restores_provisional_score(self, api):
        """PRD §3.7: "Submitting a sheet — an action reserved to the owning
        judge, with `ERR_FORBIDDEN` for anyone else, and blocked while the
        parade is frozen — moves it from `DRAFT` to `SUBMITTED` and immediately
        recomputes the entry's `provisional_score`: the plain mean of
        `sheet_total` across all of the entry's sheets in `SUBMITTED` or
        `FINALIZED` status, or null while no such sheet exists."

        Design: Difficulty/non_linear_state_machine/score_sheet_reopen_cycle
        """
        parade = th.create_parade(name="Sheet Parade 2")
        entry = _approved_band_entry(parade["id"])
        sheet = th.create_submitted_sheet(entry["id"], "judge_1", 80)
        get_success_data(api.reopen_score_sheet(sheet["id"], th.make_judge_headers("judge_1")))

        resubmitted = validate_success(
            api.submit_score_sheet(sheet["id"], th.make_judge_headers("judge_1"))
        )
        assert resubmitted["status"] == "SUBMITTED"

        fetched = validate_success(api.get_entry(entry["id"], COMMITTEE))
        assert fetched["provisional_score"] == pytest.approx(80.00, abs=0.001)


class TestScoreSheetUniquenessAndRbac:

    def test_duplicate_score_sheet_same_judge_rejected(self, api):
        """PRD §3.7: "Each `Judge` opens at most one sheet per entry — a second
        sheet for the same pairing is rejected with `ERR_DUPLICATE_SCORE_SHEET`
        — and the server records the caller as `judge_user_id` from the
        header."

        Design: Corner/validations/duplicate_score_sheet_same_judge_rejected
        """
        parade = th.create_parade(name="Sheet Dup Parade")
        entry = _approved_band_entry(parade["id"], org_name="Dup Sheet Band")
        get_success_data(
            api.create_score_sheet(entry["id"], th.create_score_sheet_payload(total=40),
                                   th.make_judge_headers("judge_1"))
        )
        resp = api.create_score_sheet(entry["id"], th.create_score_sheet_payload(total=80),
                                      th.make_judge_headers("judge_1"))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SCORE_SHEET)

    def test_judge_cannot_finalize_sheet(self, api):
        """PRD §3.7: "Final authority over scores is segregated from judging
        itself: only a `CommitteeAdmin` finalizes a sheet, moving it from
        `SUBMITTED` to `FINALIZED` while the parade is unfrozen."
        PRD §2.1: "Once authenticated, a caller may only exercise the
        operations granted to their role, and certain operations additionally
        demand ownership of the target resource; a role or ownership failure is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/judge_cannot_finalize_sheet_forbidden
        """
        parade = th.create_parade(name="SoD Judge Parade")
        entry = _approved_band_entry(parade["id"], org_name="SoD Band")
        sheet = th.create_submitted_sheet(entry["id"], "judge_1", 60)

        resp = api.finalize_score_sheet(sheet["id"], th.make_judge_headers("judge_1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        after = validate_success(api.get_score_sheet(sheet["id"], COMMITTEE))
        assert after["status"] == "SUBMITTED"


class TestAwardGating:
    """Difficulty: award_announce_requires_lineup_published."""

    def test_announce_on_locked_parade_rejected(self, api):
        """PRD §3.7: "Announcing the winner requires the parade to stand in
        `LINEUP_PUBLISHED` (`ERR_LINEUP_NOT_PUBLISHED` otherwise) and unfrozen,
        and builds its pool from the parade's entries that are `APPROVED`,
        whose `assigned_category` equals the award's eligible category — or any
        category when the award declares `ANY` — and that hold at least one
        `FINALIZED` sheet."

        Design: Difficulty/cross_entity_state_dependency/award_announce_requires_lineup_published
        """
        ctx = th.setup_locked_parade(name="Award Parade")
        award = get_success_data(
            api.create_award(ctx["parade"]["id"], th.create_award_payload(), COMMITTEE)
        )
        resp = api.announce_award(award["id"], COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_LINEUP_NOT_PUBLISHED)

    def test_rejected_announce_leaves_award_pending(self, api):
        """PRD §3.7: "A new award is `PENDING`, with `winner_entry_id` and
        `announced_at` both null."

        Design: Difficulty/cross_entity_state_dependency/award_announce_requires_lineup_published
        """
        ctx = th.setup_locked_parade(name="Award Parade 2")
        award = get_success_data(
            api.create_award(ctx["parade"]["id"], th.create_award_payload(), COMMITTEE)
        )
        validate_error(api.announce_award(award["id"], COMMITTEE),
                       ApiErrorId.ERR_LINEUP_NOT_PUBLISHED)

        after = validate_success(api.get_award(award["id"], COMMITTEE))
        assert_award(after)
        assert after["status"] == "PENDING"
        assert after["winner_entry_id"] is None

    def test_announce_with_empty_pool_rejected(self, api):
        """PRD §3.7: "An empty pool is rejected with `ERR_NO_ELIGIBLE_WINNER`
        (HTTP 422)."

        Design: Corner/validations/award_announce_no_eligible_winner_rejected
        """
        # The only APPROVED entry is BAND and holds no FINALIZED sheet; the
        # award's eligible category is FLOAT.
        ctx = th.setup_published_parade(name="Empty Pool Parade")
        award = get_success_data(
            api.create_award(ctx["parade"]["id"], th.create_award_payload(), COMMITTEE)
        )
        resp = api.announce_award(award["id"], COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_WINNER)

        after = validate_success(api.get_award(award["id"], COMMITTEE))
        assert after["status"] == "PENDING"
        assert after["winner_entry_id"] is None


class TestAwardSelector:

    def test_announce_tie_breaks_by_org_name(self, api):
        """PRD §3.7: "Otherwise the winner is resolved deterministically:
        entries are ranked by `final_score`, highest first; ties break toward
        the entry with more finalized sheets; further ties break toward the
        alphabetically earlier `org_name`; and any remaining tie breaks toward
        the earlier `created_at`."
        PRD §3.7: "The announcement records the resolved `winner_entry_id` and
        stamps `announced_at` from the logical clock."

        Design: Corner/endpoints/award_announce_selector_ranks_and_breaks_ties
        """
        ctx = th.setup_operational_parade(name="Selector Parade",
                                          staging_overrides={"name": "Lot Y", "capacity": 5})
        alpha = th.create_approved_entry(ctx["parade"]["id"], "entrant_1",
                                         category="FLOAT", org_name="Alpha Floats",
                                         estimated_participants=50)
        beta = th.create_approved_entry(ctx["parade"]["id"], "entrant_2",
                                        category="FLOAT", org_name="Beta Floats",
                                        estimated_participants=50)
        th.create_finalized_sheet(alpha["id"], "judge_1", 80)
        th.create_finalized_sheet(beta["id"], "judge_2", 80)
        th.create_tentative_assignment(
            ctx["parade"]["id"], alpha["id"], ctx["staging"]["id"], position_number=1,
            arrive_at="2026-07-04T07:00:00Z", depart_at="2026-07-04T07:30:00Z",
        )
        locked = validate_success(api.lock_parade(ctx["parade"]["id"], COMMITTEE))
        get_success_data(
            api.publish_lineup(ctx["parade"]["id"],
                               {"expected_parade_version": locked["version"]}, COMMITTEE)
        )
        award = get_success_data(
            api.create_award(ctx["parade"]["id"], th.create_award_payload(), COMMITTEE)
        )

        announced = validate_success(api.announce_award(award["id"], COMMITTEE))
        assert_award(announced)
        assert announced["status"] == "ANNOUNCED"
        # Both finalists tie at final_score 80.00 with one finalized sheet
        # each, so org_name ASC decides: "Alpha Floats" < "Beta Floats".
        assert announced["winner_entry_id"] == alpha["id"], (
            f"org_name ASC tie-break must pick Alpha Floats, got {announced['winner_entry_id']}"
        )
        assert announced["announced_at"] is not None
        assert th.DEFAULT_CLOCK_ISO[:19] in announced["announced_at"], (
            "announced_at is stamped from the logical clock (startup default)"
        )
