"""Points ledger, tiers, and stipend computation (FINAL vs PROVISIONAL bases,
pinned tier-then-waiver order, the GOLD boundary, and points conservation on void).

Queue A: dual_variant_calc/stipend_provisional_vs_final,
combinatorial_formula/stipend_pinned_tier_then_waiver_order,
boundary_precision_check/stipend_tier_gold_boundary_at_20_points,
compensating_invariant/points_conserved_on_turnout_void.
Queue B: corner_duty_points_12h_shift.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    create_officer,
    create_member,
    create_eligible_member,
    create_station_with_apparatus,
    create_released_turnout,
    create_verified_duty,
    create_published_shift,
    assign_member,
)
from test_helpers.factories import create_point_adjustment_payload


# ------------------------------------------------------- FINAL vs PROVISIONAL
def _setup_stipend_member(api):
    """EMT member with 9 released turnout pts + 6 verified duty pts + a scheduled
    (ASSIGNED) 6-pt future duty. dues=0. Returns (officer_headers, member_id)."""
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(
        api, apparatus_type="AMBULANCE", unit_designation="MEDIC-1"
    )
    m, _ = create_eligible_member(api, off, role_class="EMT", dues=0)
    create_released_turnout(
        api, off, station["id"], apparatus["id"], m["id"],
        "STRUCTURE_FIRE", "2026-03-02T00:55:00Z", "2026-03-02T01:00:00Z", "2026-03-02T03:30:00Z",
    )
    create_verified_duty(
        api, off, station["id"], apparatus["id"], m["id"],
        "2026-03-03T06:00:00Z", "2026-03-03T18:00:00Z",
        "2026-03-03T06:05:00Z", "2026-03-03T18:05:00Z",
    )
    sh2 = create_published_shift(
        api, off, station["id"], apparatus["id"], "2026-03-10T06:00:00Z", "2026-03-10T18:00:00Z"
    )
    assign_member(api, off, sh2["id"], m["id"], sh2["version"])
    return off, m["id"]


def test_stipend_final_basis_excludes_scheduled_duty(api):
    """PRD §3.6: "Under the **FINAL** basis (the default, and the basis stamped
    onto the member's stored `stipend_cents`), P counts only released turnout
    points, verified duty points, and non-reversed point adjustments; it excludes
    duty that is scheduled but not yet verified."
    PRD §3.6: "Third, compute a gross stipend as P multiplied by the tier's
    per-point rate — 0 cents per point for `BRONZE`, 150 cents per point for
    `SILVER`, and 250 cents per point for `GOLD`."

    Design: Difficulty/dual_variant_calc/stipend_provisional_vs_final
    """
    off, m_id = _setup_stipend_member(api)
    data = validate_success(api.get_member_summary(m_id, off, params={"basis": "FINAL"}), 200)
    assert data["points_ytd"] == 15
    assert data["stipend_cents"] == 2250


def test_stipend_provisional_basis_includes_scheduled_duty(api):
    """PRD §3.6: "Under the **PROVISIONAL** basis, P additionally counts scheduled
    duty that has not yet been verified — assignments in `ASSIGNED` or
    `CHECKED_IN` are scored as if they will be verified — so a member can preview
    the points and stipend an upcoming shift would earn."
    PRD §3.6: "Third, compute a gross stipend as P multiplied by the tier's
    per-point rate — 0 cents per point for `BRONZE`, 150 cents per point for
    `SILVER`, and 250 cents per point for `GOLD`."

    Design: Difficulty/dual_variant_calc/stipend_provisional_vs_final
    """
    off, m_id = _setup_stipend_member(api)
    data = validate_success(api.get_member_summary(m_id, off, params={"basis": "PROVISIONAL"}), 200)
    assert data["points_ytd"] == 21
    assert data["stipend_cents"] == 5250


# ------------------------------------------------- pinned tier-then-waiver order
def _setup_gold_dues_member(api):
    off_id, off = create_officer(api)
    m = create_member(api, role_class="EMT", dues=1000)
    get_success_data(
        api.create_point_adjustment(
            m["id"], create_point_adjustment_payload(points=20, reason="drill points"), off
        )
    )
    return off, m["id"]


def test_gold_tier_fixed_before_dues_waiver(api):
    """PRD §3.6: "the tier is `GOLD` when points are at least 20, `SILVER` when
    points are at least 10 (but below 20), and `BRONZE` otherwise — so exactly 20
    points is `GOLD` and exactly 19 points is `SILVER`."

    Design: Difficulty/combinatorial_formula/stipend_pinned_tier_then_waiver_order
    """
    off, m_id = _setup_gold_dues_member(api)
    data = validate_success(api.get_member_summary(m_id, off, params={"basis": "FINAL"}), 200)
    assert data["points_tier"] == "GOLD"


def test_gold_stipend_full_waiver_leaves_gross_intact(api):
    """PRD §3.6: "Fourth, compute a dues waiver: the member's entire
    `dues_balance_cents` is waived at `GOLD` ... Fifth, the net stipend is the
    gross stipend minus the portion of the dues balance that was **not** waived
    (that is, minus the balance less the waiver), and never less than zero — the
    net is the larger of zero and that difference."

    Design: Difficulty/combinatorial_formula/stipend_pinned_tier_then_waiver_order
    """
    off, m_id = _setup_gold_dues_member(api)
    data = validate_success(api.get_member_summary(m_id, off, params={"basis": "FINAL"}), 200)
    # P=20, GOLD rate 250 -> gross 5000; full 1000 waiver -> net = 5000 - (1000-1000) = 5000.
    assert data["stipend_cents"] == 5000


# ----------------------------------------------------- GOLD boundary at 20 pts
def _member_with_points(api, off, points):
    m = create_member(api, role_class="EMT", dues=0)
    get_success_data(
        api.create_point_adjustment(
            m["id"], create_point_adjustment_payload(points=points, reason=f"b{points}"), off
        )
    )
    return m["id"]


def test_points_tier_silver_at_19(api):
    """PRD §3.6: "the tier is `GOLD` when points are at least 20, `SILVER` when
    points are at least 10 (but below 20), and `BRONZE` otherwise — so exactly 20
    points is `GOLD` and exactly 19 points is `SILVER`."
    PRD §3.6: "Third, compute a gross stipend as P multiplied by the tier's
    per-point rate — 0 cents per point for `BRONZE`, 150 cents per point for
    `SILVER`, and 250 cents per point for `GOLD`."

    Design: Difficulty/boundary_precision_check/stipend_tier_gold_boundary_at_20_points
    """
    off_id, off = create_officer(api)
    m_id = _member_with_points(api, off, 19)
    data = validate_success(api.get_member_summary(m_id, off, params={"basis": "FINAL"}), 200)
    assert data["points_tier"] == "SILVER"
    # SILVER rate 150 -> gross 19*150 = 2850; dues 0 -> net 2850.
    assert data["stipend_cents"] == 2850


def test_points_tier_gold_at_20(api):
    """PRD §3.6: "the tier is `GOLD` when points are at least 20, `SILVER` when
    points are at least 10 (but below 20), and `BRONZE` otherwise — so exactly 20
    points is `GOLD` and exactly 19 points is `SILVER`."
    PRD §3.6: "Third, compute a gross stipend as P multiplied by the tier's
    per-point rate — 0 cents per point for `BRONZE`, 150 cents per point for
    `SILVER`, and 250 cents per point for `GOLD`."

    Design: Difficulty/boundary_precision_check/stipend_tier_gold_boundary_at_20_points
    """
    off_id, off = create_officer(api)
    m_id = _member_with_points(api, off, 20)
    data = validate_success(api.get_member_summary(m_id, off, params={"basis": "FINAL"}), 200)
    assert data["points_tier"] == "GOLD"
    # GOLD rate 250 -> gross 20*250 = 5000; dues 0 -> net 5000.
    assert data["stipend_cents"] == 5000


# ------------------------------------------------- points conserved on void
def _setup_released_turnout_member(api):
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(api)
    m = create_member(api, role_class="EMT", dues=0)
    inc, turnout = create_released_turnout(
        api, off, station["id"], apparatus["id"], m["id"],
        "STRUCTURE_FIRE", "2026-03-02T00:50:00Z", "2026-03-02T01:00:00Z", "2026-03-02T03:30:00Z",
    )
    return off, m["id"], turnout["id"]


def test_points_return_to_zero_after_turnout_void(api):
    """PRD §3.6: "voiding a released turnout removes its awarded points from the
    member's ledger and resets that turnout's `turnout_points` to zero, so the
    conserved ledger identity of §2.9 still holds."

    Design: Difficulty/compensating_invariant/points_conserved_on_turnout_void
    """
    off, m_id, t_id = _setup_released_turnout_member(api)
    before = validate_success(api.get_member(m_id, off), 200)
    assert before["points_ytd"] == 9
    get_success_data(api.void_turnout(t_id, off))
    after = validate_success(api.get_member(m_id, off), 200)
    assert after["points_ytd"] == 0


def test_voided_turnout_points_reset_to_zero(api):
    """PRD §3.6: "A released turnout may be voided by an Officer,
    `RELEASED → VOIDED` (terminal); voiding a released turnout removes its awarded
    points from the member's ledger and resets that turnout's `turnout_points` to
    zero, so the conserved ledger identity of §2.9 still holds."

    Design: Difficulty/compensating_invariant/points_conserved_on_turnout_void
    """
    off, m_id, t_id = _setup_released_turnout_member(api)
    voided = validate_success(api.void_turnout(t_id, off), 200)
    assert voided["status"] == "VOIDED"
    assert voided["turnout_points"] == 0


# --------------------------------------------------------- duty points (12h)
def test_duty_points_for_12h_shift(api):
    """PRD §3.4: "take the shift's duration in hours (the seconds between
    `start_at` and `end_at` divided by 3600), multiply by half a point per hour,
    round the product half up to a whole number, and then take the larger of that
    value and a floor of 2 points — so every verified duty is worth at least 2
    points."

    Design: Corner/calculations/corner_duty_points_12h_shift
    """
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(
        api, apparatus_type="AMBULANCE", unit_designation="MEDIC-D"
    )
    m, _ = create_eligible_member(api, off, role_class="EMT", dues=0)
    a = create_verified_duty(
        api, off, station["id"], apparatus["id"], m["id"],
        "2026-03-05T06:00:00Z", "2026-03-05T18:00:00Z",
        "2026-03-05T06:05:00Z", "2026-03-05T18:05:00Z",
    )
    assert a["status"] == "VERIFIED"
    assert a["duty_points"] == 6
    member = validate_success(api.get_member(m["id"], off), 200)
    assert member["points_ytd"] == 6
