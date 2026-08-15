"""Change orders: pricing/revision cycle, approval freeze, and the
incorporation cascade into cost baseline, provisional shares, and liquidated
damages.

PRD §3.7 (change orders, liquidated damages), §2.7 (posture), §3.1 (waterfall).
"""
from test_helpers import (
    validate_success,
    create_project,
    create_change_order_payload,
    setup_mobilized_project,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["pm_headers"]


def _incorporate(api, project_id, description, delta_cost_cents, delta_delay_days, delay_cause):
    """Create a change order and walk it PROPOSED -> PRICED -> APPROVED ->
    INCORPORATED. Returns the incorporated change order."""
    co = validate_success(api.create_change_order(
        create_change_order_payload(project_id, description=description), PM), 201)
    validate_success(api.transition_change_order(
        co["id"], {"to": "PRICED", "delta_cost_cents": delta_cost_cents,
                   "delta_delay_days": delta_delay_days, "delay_cause": delay_cause}, PM), 200)
    validate_success(api.transition_change_order(co["id"], {"to": "APPROVED"}, PM), 200)
    return validate_success(
        api.transition_change_order(co["id"], {"to": "INCORPORATED"}, PM), 200)


class TestIncorporationCascade:
    def _setup(self, api):
        """3-party mobilized project (est 1000001, bp 3333/3333/3334) with
        provisional shares 333301/333300/333400."""
        project, parts = setup_mobilized_project(
            [
                {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 3333, "sequence_order": 1},
                {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 3333, "sequence_order": 2},
                {"utility_name": "U3", "utility_type": "CATV", "cost_share_bp": 3334, "sequence_order": 3},
            ],
            name="CO Cascade Project", rule20_credit_cents=0,
            estimated_total_cost_cents=1000001,
            target_cutover_on="2026-12-31T00:00:00Z", contingency_days=0,
        )
        co = validate_success(api.create_change_order(
            create_change_order_payload(project["id"], description="rock excavation adder"),
            PM), 201)
        validate_success(api.transition_change_order(
            co["id"], {"to": "PRICED", "delta_cost_cents": 500000,
                       "delta_delay_days": 0, "delay_cause": "EXCUSABLE"}, PM), 200)
        validate_success(api.transition_change_order(co["id"], {"to": "APPROVED"}, PM), 200)
        return project, parts, co

    def test_approval_freezes_then_incorporation_reprices(self, api):
        """PRD §2.7: "The derivation is ordered: the posture is `FROZEN`
        whenever any change order of the project is `APPROVED`; otherwise it is
        `CONDITIONAL` whenever any `TRENCH` easement on any parcel of the
        project is `REFUSED`, or whenever any participation's `variance_flag`
        is true; otherwise it is `CLEAR`."
        PRD §3.7: "Incorporation (`APPROVED → INCORPORATED`) folds the change
        into the baseline through one cascade: the project's
        `estimated_total_cost_cents` increases by `delta_cost_cents` (which may
        lower it when the delta is negative) and `cumulative_delay_days`
        increases by `delta_delay_days`; the provisional share waterfall of
        §3.1 reruns for all non-withdrawn participants against the new
        estimate; each participant's `variance_flag` refreshes and the project
        posture recomputes; the frozen segments unfreeze; and the project's
        `liquidated_damages_cents` is recomputed."

        Design: Difficulty/transitive_cascade/change_order_incorporation_cascade
        """
        project, _parts, co = self._setup(api)
        frozen = validate_success(api.get_project(project["id"], PM), 200)
        assert frozen["posture"] == "FROZEN", (
            f"an APPROVED change order freezes posture before incorporation, got {frozen['posture']}"
        )
        validate_success(api.transition_change_order(co["id"], {"to": "INCORPORATED"}, PM), 200)
        after = validate_success(api.get_project(project["id"], PM), 200)
        assert after["estimated_total_cost_cents"] == 1500001, (
            f"1000001 + 500000, got {after['estimated_total_cost_cents']}"
        )

    def test_incorporation_recomputes_shares_flags_and_posture(self, api):
        """PRD §3.7: "the provisional share waterfall of §3.1 reruns for all
        non-withdrawn participants against the new estimate; each participant's
        `variance_flag` refreshes and the project posture recomputes".
        PRD §3.1: "The computation also maintains `variance_flag` on each
        participation: the flag becomes true when a previous provisional value
        existed and the absolute difference between the new and old values is
        at least ten percent of the old value."

        Design: Difficulty/transitive_cascade/change_order_incorporation_cascade
        """
        project, parts, co = self._setup(api)
        validate_success(api.transition_change_order(co["id"], {"to": "INCORPORATED"}, PM), 200)

        shares = []
        for p in parts:
            data = validate_success(api.get_participation(p["id"], PM), 200)
            shares.append(data["provisional_share_cents"])
        assert shares == [499951, 499950, 500100], (
            f"waterfall over 1500001 at bp 3333/3333/3334, got {shares}"
        )
        assert sum(shares) == 1500001

        p1 = validate_success(api.get_participation(parts[0]["id"], PM), 200)
        assert p1["variance_flag"] is True, (
            "|499951 - 333301| / 333301 ~= 50% >= 10% must raise the flag"
        )
        proj = validate_success(api.get_project(project["id"], PM), 200)
        assert proj["posture"] == "CONDITIONAL", (
            f"variance flags keep the posture below CLEAR after unfreeze, got {proj['posture']}"
        )


class TestLiquidatedDamagesTieredCap:
    def _setup(self, api):
        return create_project(
            name="LD Project", rule20_credit_cents=0,
            estimated_total_cost_cents=10000000,
            target_cutover_on="2026-12-31T00:00:00Z", contingency_days=0,
        )

    def test_weighted_days_below_cap(self, api):
        """PRD §3.7: "Each incorporated order contributes its `delta_delay_days`
        weighted by cause: full weight for `NEGLIGENT`, half weight for
        `MIXED`, and zero for `EXCUSABLE`. The weighted days are summed, the
        project's `contingency_days` allowance is subtracted, and the result is
        floored at zero — the excusable-delay buffer absorbs overrun before
        damages accrue. The raw damages are those billable days multiplied by
        five hundred dollars per day (50000 cents). The cap is ten percent of
        the project's `estimated_total_cost_cents`, rounded half up to a whole
        cent. The project's `liquidated_damages_cents` is the smaller of the
        raw figure and the cap."

        Design: Difficulty/combinatorial_formula/delay_damages_tiered_cap
        """
        project = self._setup(api)
        _incorporate(api, project["id"], "weather", 0, 2, "EXCUSABLE")
        _incorporate(api, project["id"], "contractor", 0, 5, "NEGLIGENT")
        _incorporate(api, project["id"], "mixed", 0, 4, "MIXED")

        proj = validate_success(api.get_project(project["id"], PM), 200)
        assert proj["cumulative_delay_days"] == 11, (
            f"2 + 5 + 4 days accumulate, got {proj['cumulative_delay_days']}"
        )
        # billable = 2*0 + 5*1.0 + 4*0.5 = 7; raw = 7 * 50000 = 350000;
        # cap = round_half_up(10000000 * 0.10) = 1000000 (not binding)
        assert proj["liquidated_damages_cents"] == 350000, (
            f"tiered weighting at 50000/day, got {proj['liquidated_damages_cents']}"
        )

    def test_raw_damages_clamped_at_cap(self, api):
        """PRD §3.7: "The raw damages are those billable days multiplied by
        five hundred dollars per day (50000 cents). The cap is ten percent of
        the project's `estimated_total_cost_cents`, rounded half up to a whole
        cent. The project's `liquidated_damages_cents` is the smaller of the
        raw figure and the cap."

        Design: Difficulty/combinatorial_formula/delay_damages_tiered_cap
        """
        project = self._setup(api)
        _incorporate(api, project["id"], "weather", 0, 2, "EXCUSABLE")
        _incorporate(api, project["id"], "contractor", 0, 5, "NEGLIGENT")
        _incorporate(api, project["id"], "mixed", 0, 4, "MIXED")
        _incorporate(api, project["id"], "big negligent", 0, 40, "NEGLIGENT")

        proj = validate_success(api.get_project(project["id"], PM), 200)
        assert proj["cumulative_delay_days"] == 51
        # billable = 7 + 40 = 47; raw = 47 * 50000 = 2350000 > cap 1000000
        assert proj["liquidated_damages_cents"] == 1000000, (
            f"raw 2350000 clamps to the 10% cap 1000000, got {proj['liquidated_damages_cents']}"
        )


class TestRevisionCycle:
    def test_change_order_revision_cycle(self, api):
        """PRD §3.7: "All three are required to price; all three are cleared
        back to null if the order is revised (`PRICED → PROPOSED`), which also
        increments the order's `revision_count` — a counter that starts at zero
        on creation — by one."

        Design: Corner/state_machines/change_order_revision_cycle
        """
        project = create_project(name="SM6", rule20_credit_cents=0,
                                 estimated_total_cost_cents=1000000,
                                 target_cutover_on="2026-12-31T00:00:00Z",
                                 contingency_days=0)
        co = validate_success(api.create_change_order(
            create_change_order_payload(project["id"], description="revise me"), PM), 201)
        assert co["revision_count"] == 0
        validate_success(api.transition_change_order(
            co["id"], {"to": "PRICED", "delta_cost_cents": 1000,
                       "delta_delay_days": 1, "delay_cause": "NEGLIGENT"}, PM), 200)

        revised = validate_success(
            api.transition_change_order(co["id"], {"to": "PROPOSED"}, PM), 200)
        assert revised["status"] == "PROPOSED"
        assert revised["revision_count"] == 1, (
            f"revision loop increments the counter, got {revised['revision_count']}"
        )

        validate_success(api.transition_change_order(
            co["id"], {"to": "PRICED", "delta_cost_cents": 2000,
                       "delta_delay_days": 0, "delay_cause": "EXCUSABLE"}, PM), 200)
        approved = validate_success(
            api.transition_change_order(co["id"], {"to": "APPROVED"}, PM), 200)
        assert approved["status"] == "APPROVED", "re-pricing after revision allows approval"
