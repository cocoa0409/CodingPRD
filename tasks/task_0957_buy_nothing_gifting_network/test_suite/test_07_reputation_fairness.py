"""Reputation scoring (official vs provisional, per-event rounding), the
piecewise fairness score, and report SLA tier stamping (PRD §2.8, §2.9)."""
from test_helpers import (
    assert_iso_instant,
    ApiErrorId,
    apply_strike,
    complete_gift_cycle,
    create_group,
    file_report,
    get_member,
    join_group,
    make_admin_headers,
    make_member_headers,
    register_member,
    set_clock,
    setup_group_with_members,
    validate_success,
)


# ---------------------------------------------------------------------------
# Reputation variants: PENDING vs SETTLED (Difficulty/dual_variant_calc)
# ---------------------------------------------------------------------------

def test_reputation_pending_variant_diverges_before_settlement(api):
    """PRD §2.8: "Two variants are exposed on every member read. The official
    `reputation_score` sums only `SETTLED` events; the provisional
    `pending_reputation_score` applies the identical formula over `PENDING` plus
    `SETTLED` events, so the two diverge whenever any event awaits settlement."
    PRD §3.1: "The account is born `ACTIVE`, and the system immediately records
    a `WELCOME_BONUS` reputation event worth 5 points in `PENDING` status, so
    newcomers begin with a small provisional standing that only becomes official
    after it settles."

    Design: Difficulty/dual_variant_calc/reputation_pending_vs_settled
    """
    set_clock("2026-05-10T09:00:00Z")
    m = register_member("rep_m@x.com", "Rep M")
    read = get_member(m["id"], make_member_headers(m["id"]))
    assert read["reputation_score"] == 0.0, (
        f"no SETTLED events yet -> official must read 0.0, got {read['reputation_score']}"
    )
    assert read["pending_reputation_score"] == 5.0, (
        f"the PENDING WELCOME_BONUS (+5, age 0 -> weight 1.0) must appear in the "
        f"provisional variant, got {read['pending_reputation_score']}"
    )


def test_reputation_variants_converge_after_settlement_sweep(api):
    """PRD §2.8: "Events settle — moving from `PENDING` to `SETTLED` with
    `settled_at` stamped — once their age reaches seven full days, during the
    epoch sweep."
    PRD §2.8: "an event's age in whole days is the floor of the elapsed seconds
    since its `created_at` divided by 86,400; events at most 30 days old weigh
    in full (factor 1.0), events 31 to 90 days old weigh three quarters (factor
    0.75), and events older than 90 days weigh one half (factor 0.5)."

    Design: Difficulty/dual_variant_calc/reputation_pending_vs_settled
    """
    set_clock("2026-05-10T09:00:00Z")
    m = register_member("rep_s@x.com", "Rep S")
    set_clock("2026-05-18T09:00:00Z")  # +8 days: past the 7-day settlement age
    read = get_member(m["id"], make_member_headers(m["id"]))
    assert read["reputation_score"] == 5.0, (
        f"settled WELCOME_BONUS at age 8d weighs in full, got {read['reputation_score']}"
    )
    assert read["pending_reputation_score"] == 5.0, (
        "the two variants must converge once no PENDING events remain"
    )


# ---------------------------------------------------------------------------
# Per-event rounding order (Difficulty/combinatorial_formula)
# ---------------------------------------------------------------------------

def _setup_member_with_two_completed_receives():
    """Member M completes two receives on 2026-05-10 (2x RECEIVE_COMPLETED +3
    PENDING each) on top of the WELCOME_BONUS (+5 PENDING)."""
    group, members = setup_group_with_members(
        [("rg@x.com", "G"), ("rm@x.com", "M")], name="Rounding Group", zip_code="98103"
    )
    g, m = members["rg@x.com"], members["rm@x.com"]
    complete_gift_cycle(g, m, group, title="Toaster", category="HOUSEHOLD",
                        window_start="2026-05-10T12:00:00Z",
                        window_end="2026-05-10T13:00:00Z")
    complete_gift_cycle(g, m, group, title="Kettle", category="HOUSEHOLD",
                        window_start="2026-05-10T14:00:00Z",
                        window_end="2026-05-10T15:00:00Z")
    return group, g, m


def test_reputation_per_event_rounding_order_official(api):
    """PRD §2.8: "The evaluation order is pinned: each event's weighted points
    are first rounded half-up to exactly 1 decimal place, and only then summed."
    PRD §2.8: "The official `reputation_score` sums only `SETTLED` events; the
    provisional `pending_reputation_score` applies the identical formula over
    `PENDING` plus `SETTLED` events, so the two diverge whenever any event
    awaits settlement."

    At age 40d (weight 0.75), per-event-first rounding yields
    round(5*0.75)=3.8 and round(3*0.75)=2.3 twice: 3.8 + 2.3 + 2.3 = 8.4.
    The forbidden sum-then-round order would yield round(8.25) = 8.3.

    Design: Difficulty/combinatorial_formula/reputation_per_event_rounding_order
    """
    group, g, m = _setup_member_with_two_completed_receives()
    set_clock("2026-06-19T09:00:00Z")  # +40 days: all three events SETTLED, weight 0.75
    read = get_member(m["id"], make_member_headers(m["id"]))
    assert read["reputation_score"] == 8.4, (
        f"per-event round-half-up then sum must produce 8.4 (3.8 + 2.3 + 2.3), "
        f"not the sum-then-round 8.3; got {read['reputation_score']}"
    )


def test_reputation_per_event_rounding_order_pending_variant(api):
    """PRD §2.8: "The evaluation order is pinned: each event's weighted points
    are first rounded half-up to exactly 1 decimal place, and only then summed."
    PRD §3.4: "Marking the pickup complete moves the plan to `COMPLETED` and the
    claim from `ACCEPTED` to `FULFILLED`, which in turn moves the post to
    `FULFILLED` and fires the fulfillment cascade: a `GIFT_COMPLETED` reputation
    event worth 10 points in `PENDING` for the giver, a `RECEIVE_COMPLETED`
    event worth 3 points in `PENDING` for the claimer"

    Second angle: the provisional variant applies the identical per-event
    rounding; with all events settled at age 40d both variants read 8.4.

    Design: Difficulty/combinatorial_formula/reputation_per_event_rounding_order
    """
    group, g, m = _setup_member_with_two_completed_receives()
    set_clock("2026-06-19T09:00:00Z")
    read = get_member(m["id"], make_member_headers(m["id"]))
    assert read["pending_reputation_score"] == 8.4, (
        f"provisional variant uses the identical formula over PENDING+SETTLED; "
        f"got {read['pending_reputation_score']}"
    )


# ---------------------------------------------------------------------------
# Piecewise fairness score (Difficulty/combinatorial_formula)
# ---------------------------------------------------------------------------

def _setup_member_for_fairness_steps():
    """Member A with no gifts/receives/strikes and account age 0; R files
    reports. Returns (group, a, r) plus a second UNDER_REVIEW report on A."""
    group, members = setup_group_with_members(
        [("fa@x.com", "A"), ("fr@x.com", "R")], name="Fairness Group", zip_code="98102"
    )
    a, r = members["fa@x.com"], members["fr@x.com"]
    return group, a, r


def test_fairness_score_first_strike_drops_ten(api):
    """PRD §2.8: "It starts from a base of 50, gains 2 points per gift the
    member has completed within the trailing 90 whole days, loses 3 points per
    item received within the trailing 90 whole days, loses 10 points per active
    strike point, and gains a 5-point seniority bonus once the member's own
    account is at least 180 days old (measured in whole days from the member's
    `created_at`). The raw result is clamped: below 0 it becomes 0, above 100 it
    becomes 100. All arithmetic is integer arithmetic with no rounding."

    Design: Difficulty/combinatorial_formula/fairness_score_piecewise_inputs
    """
    group, a, r = _setup_member_for_fairness_steps()
    apply_strike(r, group, a, severity_points=1)
    m = get_member(a["id"], make_member_headers(a["id"]))
    assert m["fairness_score"] == 40, (
        f"50 - 10*1 must read 40, got {m['fairness_score']}"
    )
    assert m["active_strike_points"] == 1
    assert m["status"] == "ACTIVE", "1 < 3 must not suspend"


def test_fairness_score_second_strike_drops_ten_more(api):
    """PRD §2.8: "It starts from a base of 50, gains 2 points per gift the
    member has completed within the trailing 90 whole days, loses 3 points per
    item received within the trailing 90 whole days, loses 10 points per active
    strike point, and gains a 5-point seniority bonus once the member's own
    account is at least 180 days old (measured in whole days from the member's
    `created_at`). The raw result is clamped: below 0 it becomes 0, above 100 it
    becomes 100. All arithmetic is integer arithmetic with no rounding."
    PRD §2.10: "The boundaries are pinned: at 3 or more points (3 exactly
    included) but fewer than 6, the member is suspended for 14 days; at 6 or
    more points, the member is banned."

    Design: Difficulty/combinatorial_formula/fairness_score_piecewise_inputs
    """
    group, a, r = _setup_member_for_fairness_steps()
    apply_strike(r, group, a, severity_points=1)
    apply_strike(r, group, a, severity_points=1, category="HARASSMENT")
    m = get_member(a["id"], make_member_headers(a["id"]))
    assert m["fairness_score"] == 30, (
        f"50 - 10*2 must read 30, got {m['fairness_score']}"
    )
    assert m["active_strike_points"] == 2
    assert m["status"] == "ACTIVE", "2 < 3: no suspension yet"


# ---------------------------------------------------------------------------
# Report SLA tier stamping (Corner/calculations)
# ---------------------------------------------------------------------------

def test_sla_due_at_yellow_tier_default(api):
    """PRD §2.9: "A report's `sla_due_at` is computed exactly once, at the
    report's creation, from the tier in effect at that instant: 96 hours for a
    `GREEN` group, 72 hours for `YELLOW`, 48 hours for `RED`. It is never
    recomputed afterwards, even if the group's tier later changes; tier
    movements caused by resolving reports apply only to reports created
    afterwards."
    PRD §2.9: "The group's `health_tier` derives from the score: `GREEN` when
    the score is at least 20, `YELLOW` when it sits between 0 and 19 inclusive,
    and `RED` when it falls below 0."

    A fresh group has health_score 0 -> YELLOW, so a report created at
    2026-05-10T09:00:00Z gets sla_due_at = created_at + 72h.

    Design: Corner/calculations/sla_due_at_yellow_tier_default
    """
    group, members = setup_group_with_members(
        [("slr@x.com", "R"), ("slt@x.com", "T")], name="SLA Group", zip_code="98222"
    )
    r, t = members["slr@x.com"], members["slt@x.com"]
    res = api.create_report(
        {"group_id": group["id"], "target_type": "MEMBER", "target_id": t["id"],
         "category": "SPAM"},
        make_member_headers(r["id"]),
    )
    report = validate_success(res, 201)
    assert report["status"] == "OPEN"
    assert_iso_instant(
        report["sla_due_at"], "2026-05-13T09:00:00Z",
        f"fresh group is YELLOW (score 0) -> +72h, got {report['sla_due_at']}",
    )
