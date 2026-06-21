"""Costing roll-up and where-used impact analysis.

Covers the dual-variant calculations (planned vs. effective cost, as-designed vs.
as-released where-used) and the combinatorial cost formula (part-type branching,
per-line rounding-then-sum), all from PRD 3.3 / 3.4.
"""
from test_helpers import (
    api_client, validate_success,
    TEST_USERS, make_change_admin_headers, make_approver_headers,
    factories, get_success_data,
)

DESIGNER = TEST_USERS["designer_headers"]
SUPPLIER_MGR = TEST_USERS["supplier_manager_headers"]
VIEWER = TEST_USERS["viewer_headers"]
CA = "ca1"
CHANGE_ADMIN = make_change_admin_headers(CA)


def _release_rev(part_id, rev_id, effectivity="2026-01-02T00:00:00Z", clock="2026-01-03T00:00:00Z"):
    """Full ECO flow to RELEASE an IN_REVIEW revision."""
    ecr = get_success_data(api_client.create_change_request(
        factories.create_change_request_payload(part_id), DESIGNER))
    get_success_data(api_client.submit_change_request(ecr["id"], DESIGNER))
    get_success_data(api_client.approve_change_request(ecr["id"], CHANGE_ADMIN))
    eco = get_success_data(api_client.create_change_order(
        factories.create_change_order_payload(ecr["id"], effectivity, required_approvals=1),
        CHANGE_ADMIN))
    get_success_data(api_client.add_affected_item(
        eco["id"], factories.create_affected_item_payload(rev_id), CHANGE_ADMIN))
    task = get_success_data(api_client.add_approval_task(
        eco["id"], factories.create_approval_task_payload("ap1"), CHANGE_ADMIN))
    get_success_data(api_client.submit_eco_for_approval(eco["id"], CHANGE_ADMIN))
    get_success_data(api_client.approve_task(task["id"], make_approver_headers("ap1")))
    get_success_data(api_client.set_clock(clock, CHANGE_ADMIN))
    get_success_data(api_client.make_change_order_effective(eco["id"], CHANGE_ADMIN))


def _new_rev(part_id):
    part = get_success_data(api_client.get_part(part_id, DESIGNER))
    return get_success_data(api_client.create_revision(
        part_id, factories.create_revision_payload(part["version"]), DESIGNER))


def _add_line(rev_id, child_id, qty, scrap=None):
    rev = get_success_data(api_client.get_revision(rev_id, DESIGNER))
    payload = factories.create_bom_line_payload(child_id, qty, rev["version"])
    if scrap is not None:
        payload["scrap_factor"] = scrap
    return get_success_data(api_client.add_bom_line(rev_id, payload, DESIGNER))


def _build_planned_vs_effective_scenario():
    """ASM-A consuming C1 (qty 2) and C2 (qty 1). C1 has released rev A (C3 qty 4)
    and a newer WORKING rev B (C3 qty 6); C2 is a BUY part with no released rev."""
    sup = get_success_data(api_client.create_supplier(
        factories.create_supplier_payload(), SUPPLIER_MGR))
    c3 = get_success_data(api_client.create_part(
        factories.create_part_payload("BUY", base_cost_cents=350, default_supplier_id=sup["id"]),
        DESIGNER))
    c2 = get_success_data(api_client.create_part(
        factories.create_part_payload("BUY", base_cost_cents=1200, default_supplier_id=sup["id"]),
        DESIGNER))
    c1 = get_success_data(api_client.create_part(
        factories.create_part_payload("MAKE", base_cost_cents=800), DESIGNER))
    # C1 rev A -> release (C3 qty 4)
    c1a = _new_rev(c1["id"])
    _add_line(c1a["id"], c3["id"], 4)
    get_success_data(api_client.submit_revision_review(c1a["id"], DESIGNER))
    _release_rev(c1["id"], c1a["id"])
    # C1 rev B WORKING (C3 qty 6)
    c1b = _new_rev(c1["id"])
    _add_line(c1b["id"], c3["id"], 6)
    # Assembly A WORKING rev (C1 qty 2, C2 qty 1)
    asm = get_success_data(api_client.create_part(
        factories.create_part_payload("MAKE", base_cost_cents=5000), DESIGNER))
    arev = _new_rev(asm["id"])
    _add_line(arev["id"], c1["id"], 2)
    _add_line(arev["id"], c2["id"], 1)
    return arev


class TestPlannedVsEffectiveCost:
    def test_planned_uses_latest_non_obsolete_child_revision(self, api):
        """PRD 3.3: "For `planned_cost_cents`, each child contributes the cost of that
        child part's latest non-`OBSOLETE` revision, taken by `rev_label` sequence (the
        newest of `A`, `B`, `C`, and so on) — this reflects the design intent and
        ignores effectivity."

        Design: Difficulty/dual_variant_calc/bom_cost_planned_vs_effective_diverges
        """
        arev = _build_planned_vs_effective_scenario()
        cost = validate_success(api.get_revision_cost(arev["id"], VIEWER))
        assert cost["planned_cost_cents"] == 12000, cost

    def test_effective_uses_released_revision_only(self, api):
        """PRD 3.3: "For `effective_cost_cents`, each child contributes the cost of
        that child part's `released_revision_id` only — the single currently-released
        revision — and if the child has no released revision, the child contributes its
        own `base_cost_cents` instead."

        Design: Difficulty/dual_variant_calc/bom_cost_planned_vs_effective_diverges
        """
        arev = _build_planned_vs_effective_scenario()
        cost = validate_success(api.get_revision_cost(arev["id"], VIEWER))
        assert cost["effective_cost_cents"] == 10600, cost

    def test_planned_and_effective_diverge(self, api):
        """PRD 3.3: "The child's unit cost depends on which of the two figures is being
        computed, and this is the only difference between them."

        Design: Difficulty/dual_variant_calc/bom_cost_planned_vs_effective_diverges
        """
        arev = _build_planned_vs_effective_scenario()
        cost = validate_success(api.get_revision_cost(arev["id"], VIEWER))
        assert cost["planned_cost_cents"] == 12000
        assert cost["effective_cost_cents"] == 10600
        assert cost["planned_cost_cents"] != cost["effective_cost_cents"]


def _build_where_used_scenario():
    """Target T (BUY) consumed by P1 (RELEASED rev) and P2 (WORKING rev)."""
    sup = get_success_data(api_client.create_supplier(
        factories.create_supplier_payload(), SUPPLIER_MGR))
    t = get_success_data(api_client.create_part(
        factories.create_part_payload("BUY", base_cost_cents=500, default_supplier_id=sup["id"]),
        DESIGNER))
    # P1 RELEASED consuming T
    p1 = get_success_data(api_client.create_part(
        factories.create_part_payload("MAKE", base_cost_cents=100), DESIGNER))
    p1r = _new_rev(p1["id"])
    _add_line(p1r["id"], t["id"], 1)
    get_success_data(api_client.submit_revision_review(p1r["id"], DESIGNER))
    _release_rev(p1["id"], p1r["id"])
    # P2 WORKING consuming T
    p2 = get_success_data(api_client.create_part(
        factories.create_part_payload("MAKE", base_cost_cents=100), DESIGNER))
    p2r = _new_rev(p2["id"])
    _add_line(p2r["id"], t["id"], 1)
    return t, p1, p2


class TestWhereUsedBlastRadius:
    def test_as_designed_counts_all_non_obsolete_parents(self, api):
        """PRD 3.4: "A parent part counts toward the as-designed radius when any of its
        revisions consuming the target is in a state other than `OBSOLETE`; this is the
        broad blast radius reflecting the design as drawn."

        Design: Difficulty/dual_variant_calc/where_used_as_designed_vs_as_released_diverges
        """
        t, _p1, _p2 = _build_where_used_scenario()
        data = validate_success(api.where_used(t["id"], VIEWER))
        assert data["as_designed_affected_count"] == 2, data

    def test_as_released_counts_only_released_revision_parents(self, api):
        """PRD 3.4: "A parent part counts toward the as-released radius only when the
        consuming parent revision is exactly that parent part's `released_revision_id`;
        this is the narrow blast radius reflecting what is currently shipping."

        Design: Difficulty/dual_variant_calc/where_used_as_designed_vs_as_released_diverges
        """
        t, _p1, _p2 = _build_where_used_scenario()
        data = validate_success(api.where_used(t["id"], VIEWER))
        assert data["as_released_affected_count"] == 1, data

    def test_as_designed_and_as_released_diverge(self, api):
        """PRD 3.4: "The response echoes the queried `part_id`, reports
        `as_designed_affected_count` and `as_released_affected_count`, and lists the
        `direct_parent_revision_ids` — the parent revision ids that directly consume the
        target."

        Design: Difficulty/dual_variant_calc/where_used_as_designed_vs_as_released_diverges
        """
        t, _p1, _p2 = _build_where_used_scenario()
        data = validate_success(api.where_used(t["id"], VIEWER))
        assert data["part_id"] == t["id"]
        assert data["as_designed_affected_count"] == 2
        assert data["as_released_affected_count"] == 1
        assert data["as_designed_affected_count"] != data["as_released_affected_count"]


class TestCostFormulaPartTypeBranching:
    def _build(self):
        """BUY leaf L (700) -> PHANTOM PH (base 999 ignored, line L qty 3) ->
        MAKE M (labor 2000, line PH qty 2)."""
        sup = get_success_data(api_client.create_supplier(
            factories.create_supplier_payload(), SUPPLIER_MGR))
        leaf = get_success_data(api_client.create_part(
            factories.create_part_payload("BUY", base_cost_cents=700, default_supplier_id=sup["id"]),
            DESIGNER))
        ph = get_success_data(api_client.create_part(
            factories.create_part_payload("PHANTOM", base_cost_cents=999), DESIGNER))
        phr = _new_rev(ph["id"])
        _add_line(phr["id"], leaf["id"], 3)
        m = get_success_data(api_client.create_part(
            factories.create_part_payload("MAKE", base_cost_cents=2000), DESIGNER))
        mr = _new_rev(m["id"])
        _add_line(mr["id"], ph["id"], 2)
        return mr

    def test_phantom_adds_no_own_cost_make_adds_labor(self, api):
        """PRD 3.3: "For a `PHANTOM` revision the sum of the lines is the total — a
        phantom contributes no cost of its own, and its `base_cost_cents` is treated as
        zero."
        PRD 3.3: "For a `MAKE` revision, the part's own `base_cost_cents`, representing
        its labor and overhead adder, is added on top of the summed line costs."

        Design: Difficulty/combinatorial_formula/bom_rollup_nonlinear_by_part_type
        """
        mr = self._build()
        cost = validate_success(api.get_revision_cost(mr["id"], VIEWER))
        # PH planned: round(3*700)=2100 (no own cost). M planned: round(2*2100)=4200 + 2000 = 6200
        assert cost["planned_cost_cents"] == 6200, cost

    def test_buy_leaf_is_base_cost(self, api):
        """PRD 3.3: "For a revision whose part is of type `BUY`, the cost is simply that
        part's `base_cost_cents` — a `BUY` part is a purchased leaf."

        Design: Difficulty/combinatorial_formula/bom_rollup_nonlinear_by_part_type
        """
        sup = get_success_data(api.create_supplier(
            factories.create_supplier_payload(), SUPPLIER_MGR))
        leaf = get_success_data(api.create_part(
            factories.create_part_payload("BUY", base_cost_cents=700, default_supplier_id=sup["id"]),
            DESIGNER))
        leaf_rev = _new_rev(leaf["id"])
        cost = validate_success(api.get_revision_cost(leaf_rev["id"], VIEWER))
        assert cost["planned_cost_cents"] == 700, cost


class TestCostFormulaRounding:
    def _build(self):
        """MAKE RA (labor 5000): line X(100) qty1 scrap 0.005, line Y(300) qty1 scrap 0.005."""
        sup = get_success_data(api_client.create_supplier(
            factories.create_supplier_payload(), SUPPLIER_MGR))
        x = get_success_data(api_client.create_part(
            factories.create_part_payload("BUY", base_cost_cents=100, default_supplier_id=sup["id"]),
            DESIGNER))
        y = get_success_data(api_client.create_part(
            factories.create_part_payload("BUY", base_cost_cents=300, default_supplier_id=sup["id"]),
            DESIGNER))
        ra = get_success_data(api_client.create_part(
            factories.create_part_payload("MAKE", base_cost_cents=5000), DESIGNER))
        rar = _new_rev(ra["id"])
        _add_line(rar["id"], x["id"], 1, scrap=0.005)
        _add_line(rar["id"], y["id"], 1, scrap=0.005)
        return rar

    def test_round_per_line_then_sum(self, api):
        """PRD 2.8: "the extended cost of each individual line is rounded to whole
        cents first, and only the already-rounded per-line amounts are summed."

        Design: Difficulty/combinatorial_formula/bom_rollup_round_per_line_then_sum
        """
        rar = self._build()
        cost = validate_success(api.get_revision_cost(rar["id"], VIEWER))
        # round(100*1.005=100.5)=101, round(300*1.005=301.5)=302, sum 403 + labor 5000 = 5403
        assert cost["planned_cost_cents"] == 5403, cost

    def test_per_line_rounding_differs_from_sum_then_round(self, api):
        """PRD 2.8: "The system must never sum the raw fractional line amounts and
        round the total at the end; the per-line rounding boundary is observable and
        is part of the contract."

        Design: Difficulty/combinatorial_formula/bom_rollup_round_per_line_then_sum
        """
        rar = self._build()
        cost = validate_success(api.get_revision_cost(rar["id"], VIEWER))
        # sum-then-round would give round(100.5+301.5)=402 + 5000 = 5402; contract pins 5403.
        assert cost["planned_cost_cents"] == 5403
        assert cost["planned_cost_cents"] != 5402, "must round per line, not sum-then-round"
