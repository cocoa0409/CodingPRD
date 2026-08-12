"""Free agency, budgets, sign gate, compensating release (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    GM_HEADERS,
    advance_target,
    api_client,
    create_budget,
    create_free_agent_target,
    create_offered_target,
    create_roster_need,
    get_budget,
    get_success_data,
    sign_target,
    validate_error,
)


class TestStateBeatsFiscalOnSign:
    """Difficulty: priority_pair_validation_conflict/state_beats_fiscal_on_sign."""

    def test_identified_target_sign_rejected_with_target_not_offered(self, api):
        """PRD §3.7: "A `GeneralManager` signs an `OFFERED` target against a
        budget by supplying a `budget_id`; a target in any other state rejects
        with `ERR_TARGET_NOT_OFFERED`." Validation ordering (PRD §2.9 item 5
        before item 9) makes the state guard fire first.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_sign
        """
        bud = create_budget(season_year=2026, base_cap_cents=100000000, rollover_cents=0)
        t1 = create_free_agent_target(
            player_name="Big Vet", position="WR", season_year=2026,
            base_salary_cents=150000000, signing_bonus_cents=0, contract_years=1,
        )
        resp = api_client.sign_target(t1["id"], {"budget_id": bud["id"]}, GM_HEADERS)
        validate_error(resp, ApiErrorId.ERR_TARGET_NOT_OFFERED)
        assert resp.status_code == 409

    def test_state_error_not_fiscal_even_when_hit_exceeds_available(self, api):
        """PRD §2.9: "5. State guards — the entity's current state permits the
        transition ... 9. Fiscal constraints — sign gate and budget-adjustment
        floor (`ERR_BUDGET_EXCEEDED`)." The target here is IDENTIFIED
        (priority 5 fails) AND its hit 150000000 exceeds available 100000000
        (priority 9 would also fail); the state guard's
        `ERR_TARGET_NOT_OFFERED` must be reported, never `ERR_BUDGET_EXCEEDED`.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_sign
        """
        bud = create_budget(season_year=2026, base_cap_cents=100000000, rollover_cents=0)
        t1 = create_free_agent_target(
            player_name="Big Vet", position="WR", season_year=2026,
            base_salary_cents=150000000, signing_bonus_cents=0, contract_years=1,
        )
        resp = api_client.sign_target(t1["id"], {"budget_id": bud["id"]}, GM_HEADERS)
        data = resp.json()["data"]
        assert data["error_id"] == "ERR_TARGET_NOT_OFFERED"
        assert data["error_id"] != "ERR_BUDGET_EXCEEDED"
        assert resp.status_code == 409


class TestBudgetSignExactAvailableAllowed:
    """Difficulty: boundary_precision_check/budget_sign_exact_available_allowed.

    Budget base_cap 100000000, rollover 0. Two targets each with hit
    50000000: signing both drives available to exactly 0; posture TIGHT. A
    third target of hit 100 is then rejected ERR_BUDGET_EXCEEDED.
    """

    def _setup(self):
        bud = create_budget(season_year=2026, base_cap_cents=100000000, rollover_cents=0)
        create_roster_need(season_year=2026, position="QB", priority_tier="P3")
        t1 = create_offered_target(
            player_name="T1", position="QB", season_year=2026,
            base_salary_cents=50000000, signing_bonus_cents=0, contract_years=1,
        )
        t2 = create_offered_target(
            player_name="T2", position="QB", season_year=2026,
            base_salary_cents=50000000, signing_bonus_cents=0, contract_years=1,
        )
        t3 = create_offered_target(
            player_name="T3", position="QB", season_year=2026,
            base_salary_cents=100, signing_bonus_cents=0, contract_years=1,
        )
        return bud, t1, t2, t3

    def test_sign_with_hit_equal_to_available_is_allowed(self, api):
        """PRD §3.7: "the signing is allowed only if the cap hit is less than
        or equal to available — equality is permitted". After t1 signs
        (available 50000000), t2's hit of exactly 50000000 is allowed.

        Design: Difficulty/boundary_precision_check/budget_sign_exact_available_allowed
        """
        bud, t1, t2, _ = self._setup()
        sign_target(t1["id"], bud["id"])
        signed = sign_target(t2["id"], bud["id"])
        assert signed["status"] == "SIGNED"

    def test_available_zero_posture_tight_and_further_sign_rejected(self, api):
        """PRD §3.7: "`posture`... is `TIGHT` whenever available is strictly
        less than one-tenth of the sum of base cap and rollover". At available
        0 < 10000000 the budget is TIGHT; a further sign of 100 is rejected
        `ERR_BUDGET_EXCEEDED` (100 > 0).

        Design: Difficulty/boundary_precision_check/budget_sign_exact_available_allowed
        """
        bud, t1, t2, t3 = self._setup()
        sign_target(t1["id"], bud["id"])
        sign_target(t2["id"], bud["id"])
        budget = get_budget(bud["id"])
        assert budget["available_cents"] == 0
        assert budget["posture"] == "TIGHT"
        resp = api_client.sign_target(t3["id"], {"budget_id": bud["id"]}, GM_HEADERS)
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)


class TestBudgetSignReleaseConservesCommitted:
    """Difficulty: compensating_invariant/budget_sign_release_conserves_committed.

    Budget base_cap 200000000, rollover 10000000 (total 210000000). Target
    base 30000000, bonus 9999999, 3 years -> proration round_half_up
    (9999999/3 = 3333333) -> hit 33333333. Sign then release restores
    committed to 0.
    """

    def _setup(self):
        bud = create_budget(season_year=2026, base_cap_cents=200000000, rollover_cents=10000000)
        create_roster_need(season_year=2026, position="QB", priority_tier="P2")
        t1 = create_offered_target(
            player_name="Pair Vet", position="QB", season_year=2026,
            base_salary_cents=30000000, signing_bonus_cents=9999999, contract_years=3,
        )
        return bud, t1

    def test_sign_raises_committed_by_exact_hit(self, api):
        """PRD §3.7: "the year-one cap hit is the base salary plus the signing
        bonus prorated across the contract years, with the proration rounded
        half-up to the nearest cent". round_half_up(9999999/3) = 3333333 so
        hit = 33333333; "committed_cents, the sum of `annual_cap_hit_cents`
        across all `FreeAgentTarget` rows with `status` `SIGNED` against this
        budget" -> 33333333 after sign.

        Design: Difficulty/compensating_invariant/budget_sign_release_conserves_committed
        """
        bud, t1 = self._setup()
        target = api_client.get_free_agent_target(t1["id"], GM_HEADERS)
        assert get_success_data(target)["annual_cap_hit_cents"] == 33333333
        sign_target(t1["id"], bud["id"])
        budget = get_budget(bud["id"])
        assert budget["committed_cents"] == 33333333

    def test_release_restores_committed_available_posture(self, api):
        """PRD §3.7: "Release is the compensating action: releasing a `SIGNED`
        target moves it to `RELEASED`, after which its cap hit no longer
        counts toward `committed_cents`". Committed returns to its pre-sign
        value 0, available returns to 210000000, posture HEALTHY.

        Design: Difficulty/compensating_invariant/budget_sign_release_conserves_committed
        """
        bud, t1 = self._setup()
        c0 = bud["committed_cents"]
        assert c0 == 0
        sign_target(t1["id"], bud["id"])
        api_client.release_target(t1["id"], GM_HEADERS)
        budget = get_budget(bud["id"])
        assert budget["committed_cents"] == c0 == 0
        assert budget["available_cents"] == 210000000
        assert budget["posture"] == "HEALTHY"


class TestTargetApproveRequiresOpenRosterNeed:
    """Difficulty: cross_entity_state_dependency/target_approve_requires_open_roster_need."""

    def test_approve_rejected_without_open_need(self, api):
        """PRD §3.7: "The step from `EVALUATING` to `APPROVED` is gated by
        roster need: an `OPEN` `RosterNeed` whose `position` equals the
        target's `position` and whose `season_year` equals the target's
        `season_year` must exist, otherwise the advance is rejected with
        `ERR_NO_ROSTER_NEED`."

        Design: Difficulty/cross_entity_state_dependency/target_approve_requires_open_roster_need
        """
        t1 = create_free_agent_target(
            player_name="Needy Vet", position="CB", season_year=2026,
            base_salary_cents=5000000, signing_bonus_cents=0, contract_years=1,
        )
        advance_target(t1["id"], "EVALUATING")
        resp = api_client.advance_target(t1["id"], {"to_state": "APPROVED"}, GM_HEADERS)
        validate_error(resp, ApiErrorId.ERR_NO_ROSTER_NEED)
        assert resp.status_code == 409

    def test_approve_succeeds_after_open_need_created(self, api):
        """PRD §3.7: "The step from `EVALUATING` to `APPROVED` is gated by
        roster need: an `OPEN` `RosterNeed` whose `position` equals the
        target's `position` and whose `season_year` equals the target's
        `season_year` must exist, otherwise the advance is rejected with
        `ERR_NO_ROSTER_NEED`." Once an OPEN need matching position + season
        exists, the same advance succeeds and the target moves to `APPROVED`.

        Design: Difficulty/cross_entity_state_dependency/target_approve_requires_open_roster_need
        """
        t1 = create_free_agent_target(
            player_name="Needy Vet", position="CB", season_year=2026,
            base_salary_cents=5000000, signing_bonus_cents=0, contract_years=1,
        )
        advance_target(t1["id"], "EVALUATING")
        create_roster_need(season_year=2026, position="CB", priority_tier="P1")
        approved = advance_target(t1["id"], "APPROVED")
        assert approved["status"] == "APPROVED"


class TestCapHitProration:
    def test_bonus_proration_rounds_half_up(self, api):
        """PRD §3.7: "the proration rounded half-up to the nearest cent".
        10000001 / 3 = 3333333.67 -> 3333334, so the hit is
        10000000 + 3333334 = 13333334.

        Design: Corner/calculations/cap_hit_bonus_proration_rounds_half_up
        """
        t1 = create_free_agent_target(
            player_name="Prorate", position="TE", season_year=2026,
            base_salary_cents=10000000, signing_bonus_cents=10000001, contract_years=3,
        )
        assert t1["annual_cap_hit_cents"] == 13333334


class TestBudgetPostureBoundary:
    def test_available_exactly_ten_percent_is_healthy(self, api):
        """PRD §3.7: "`posture`... is `TIGHT` whenever available is strictly
        less than one-tenth of the sum of base cap and rollover, and `HEALTHY`
        otherwise — available equal to exactly one-tenth of that sum is
        `HEALTHY`, not `TIGHT`." Signing a 90000000-hit target against
        100000000 leaves available 10000000 = exactly 10%.

        Design: Corner/calculations/budget_posture_exact_ten_percent_healthy
        """
        bud = create_budget(season_year=2026, base_cap_cents=100000000, rollover_cents=0)
        create_roster_need(season_year=2026, position="QB", priority_tier="P3")
        t1 = create_offered_target(
            player_name="T1", position="QB", season_year=2026,
            base_salary_cents=90000000, signing_bonus_cents=0, contract_years=1,
        )
        sign_target(t1["id"], bud["id"])
        budget = get_budget(bud["id"])
        assert budget["available_cents"] == 10000000
        assert budget["posture"] == "HEALTHY"

    def test_one_cent_below_ten_percent_is_tight(self, api):
        """PRD §3.7: strictly-less-than rule for TIGHT — "available equal to
        exactly one-tenth of that sum is `HEALTHY`, not `TIGHT`". Signing a
        further 1-cent target leaves 9999999 < 10000000 (10%) -> TIGHT.

        Design: Corner/calculations/budget_posture_exact_ten_percent_healthy
        """
        bud = create_budget(season_year=2026, base_cap_cents=100000000, rollover_cents=0)
        create_roster_need(season_year=2026, position="QB", priority_tier="P3")
        t1 = create_offered_target(
            player_name="T1", position="QB", season_year=2026,
            base_salary_cents=90000000, signing_bonus_cents=0, contract_years=1,
        )
        t2 = create_offered_target(
            player_name="T2", position="QB", season_year=2026,
            base_salary_cents=1, signing_bonus_cents=0, contract_years=1,
        )
        sign_target(t1["id"], bud["id"])
        sign_target(t2["id"], bud["id"])
        budget = get_budget(bud["id"])
        assert budget["available_cents"] == 9999999
        assert budget["posture"] == "TIGHT"


class TestSignImmediatelyVisible:
    def test_sign_immediately_visible_on_budget(self, api):
        """PRD §3.7: "On a successful signing, ... the budget's
        `committed_cents`, `available_cents`, and `posture` are recomputed
        per the formulas above, and the budget's `version` is incremented by
        1." A plain GET right after the sign shows committed_cents 40000000.

        Design: Corner/consistency_model/sign_immediately_visible_on_budget
        """
        bud = create_budget(season_year=2026, base_cap_cents=100000000, rollover_cents=0)
        create_roster_need(season_year=2026, position="QB", priority_tier="P3")
        t1 = create_offered_target(
            player_name="Vet", position="QB", season_year=2026,
            base_salary_cents=40000000, signing_bonus_cents=0, contract_years=1,
        )
        sign_target(t1["id"], bud["id"])
        budget = get_budget(bud["id"])
        assert budget["committed_cents"] == 40000000
