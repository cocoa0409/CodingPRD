"""The authoritative safety score, its advisory counterpart, and the cumulative
severity charge that walks a cook across the standing bands.

Every test builds its own world from scratch: the harness restarts the API
server before each test, so nothing here may rely on another test's data.
"""

from test_helpers import assert_fields, fixtures as fx


# ==========================================================================
# The two variants of the safety score: substantiated-only vs intake-inclusive
# ==========================================================================
def test_01_authoritative_score_charges_substantiated_incidents_only(api):
    """The written safety_score charges the SUBSTANTIATED incident and ignores the TRIAGED one.

    PRD: "The **authoritative** score — the one written to `safety_score` and the only one that ever moves `compliance_standing` — sums, over the cook's incidents whose `status` is `SUBSTANTIATED`, each incident's points multiplied by its decay weight, then subtracts that total charge from 100 and floors the result at zero."
    Design: Difficulty/dual_variant_calc/safety_score_substantiated_only_vs_intake_inclusive
    """
    fx.reset_clock(api)
    fx.create_state_policy(api, state_code="CA")
    cook = fx.register_cook(api, state_code="CA", claimed_kitchen_type="HOME_COTTAGE")
    assert cook["safety_score"] == 100

    charged = fx.substantiated_incident(
        api, cook["id"], severity="MODERATE", category="LABEL_MISSING"
    )
    pending = fx.report_incident(api, cook["id"], severity="SEVERE", category="TEMP_ABUSE")
    pending = fx.triage_incident(api, pending["id"], "ACCEPT")

    assert_fields(charged, status="SUBSTANTIATED", severity_points=12)
    assert_fields(pending, status="TRIAGED", severity_points=25)

    # 100 - 12 * 1.00 = 88; the 25 points sitting in TRIAGED are not charged.
    cook_row = fx.read_cook(api, cook["id"])
    assert_fields(cook_row, safety_score=88, compliance_standing="CLEAR")

    summary = fx.read_compliance_summary(api, cook["id"])
    assert_fields(
        summary,
        cook_id=cook["id"],
        safety_score=88,
        substantiated_incident_count=1,
        open_incident_count=1,
    )


def test_02_provisional_score_adds_open_incidents_at_half_weight(api):
    """provisional_safety_score charges the TRIAGED incident at half weight, landing at 75.

    PRD: "It takes the same substantiated charge at full decayed weight and adds, for every incident whose `status` is `INTAKE` or `TRIAGED`, that incident's decayed points multiplied by a half-weight of 0.5; the sum is again rounded half up exactly once, subtracted from 100 and floored at zero."
    Design: Difficulty/dual_variant_calc/safety_score_substantiated_only_vs_intake_inclusive
    """
    fx.reset_clock(api)
    fx.create_state_policy(api, state_code="CA", cottage_food_annual_cap_cents=5_000_000)
    cook = fx.register_cook(api, state_code="CA", claimed_kitchen_type="HOME_COTTAGE")

    fx.substantiated_incident(api, cook["id"], severity="MODERATE", category="LABEL_MISSING")
    pending = fx.report_incident(api, cook["id"], severity="SEVERE", category="TEMP_ABUSE")
    fx.triage_incident(api, pending["id"], "ACCEPT")

    # 12 * 1.00 + 25 * 1.00 * 0.5 = 24.5, rounded half up once = 25, so 100 - 25 = 75.
    summary = fx.read_compliance_summary(api, cook["id"])
    assert_fields(
        summary,
        safety_score=88,
        provisional_safety_score=75,
        compliance_standing="CLEAR",
        ytd_cottage_revenue_cents=0,
        cap_remaining_cents=5_000_000,
    )


def test_03_provisional_score_never_moves_compliance_standing(api):
    """A provisional score inside the WARNED band leaves the persisted standing at CLEAR.

    PRD: "It never writes a persisted field and never moves `compliance_standing`."
    Design: Difficulty/dual_variant_calc/safety_score_substantiated_only_vs_intake_inclusive
    """
    fx.reset_clock(api)
    fx.create_state_policy(api, state_code="CA")
    cook = fx.register_cook(api, state_code="CA", claimed_kitchen_type="HOME_COTTAGE")

    fx.substantiated_incident(api, cook["id"], severity="MODERATE", category="LABEL_MISSING")
    pending = fx.report_incident(api, cook["id"], severity="SEVERE", category="TEMP_ABUSE")
    fx.triage_incident(api, pending["id"], "ACCEPT")

    summary = fx.read_compliance_summary(api, cook["id"])
    assert summary["provisional_safety_score"] == 75
    assert summary["provisional_safety_score"] < summary["safety_score"]

    cook_row = fx.read_cook(api, cook["id"])
    assert_fields(
        cook_row,
        safety_score=88,
        compliance_standing="CLEAR",
        standing_reason=None,
        onboarding_status="DRAFT",
    )


# ==========================================================================
# Cumulative severity points crossing the standing bands
# ==========================================================================
def test_04_cumulative_charge_crosses_the_warn_band(api):
    """No single incident warns the cook; the accumulated charge of 30 points does.

    PRD: "On the system-driven edges, `CLEAR → WARNED` fires when the recomputed score is at least 60 and below 80 and stamps `standing_reason` as the literal `SAFETY_SCORE_WARN`; `CLEAR → SUSPENDED` and `WARNED → SUSPENDED` fire when the recomputed score is below 60 and stamp `standing_reason` as the literal `SAFETY_SCORE_SUSPEND`."
    Design: Corner/cross_cutting_complexity_layers/cumulative_severity_points_cross_the_standing_bands_at_their_boundaries
    """
    fx.reset_clock(api)
    setup = fx.selling_cook(api, state_code="CA")
    assert_fields(setup.cook, safety_score=100, compliance_standing="CLEAR", standing_reason=None)

    first = fx.substantiated_incident(
        api, setup.cook_id, severity="MINOR", category="LABEL_MISSING"
    )
    assert first["severity_points"] == 5
    after_first = fx.read_cook(api, setup.cook_id)
    assert_fields(
        after_first, safety_score=95, compliance_standing="CLEAR", standing_reason=None
    )

    second = fx.substantiated_incident(
        api, setup.cook_id, severity="SEVERE", category="TEMP_ABUSE"
    )
    assert second["severity_points"] == 25
    after_second = fx.read_cook(api, setup.cook_id)
    assert_fields(
        after_second,
        safety_score=70,
        compliance_standing="WARNED",
        standing_reason="SAFETY_SCORE_WARN",
    )


def test_05_score_of_exactly_sixty_stays_warned(api):
    """A charge of exactly 40 leaves the score at 60, which selects WARNED and not SUSPENDED.

    PRD: "Standing bands map the authoritative score onto `compliance_standing`: a score below 60 selects `SUSPENDED`, a score of at least 60 and below 80 selects `WARNED`, and a score of 80 or more selects `CLEAR`."
    Design: Corner/cross_cutting_complexity_layers/cumulative_severity_points_cross_the_standing_bands_at_their_boundaries
    """
    fx.reset_clock(api)
    setup = fx.selling_cook(api, state_code="CA")

    for severity, category in (
        ("MINOR", "LABEL_MISSING"),
        ("SEVERE", "TEMP_ABUSE"),
        ("MINOR", "LABEL_MISSING"),
        ("MINOR", "LABEL_MISSING"),
    ):
        fx.substantiated_incident(api, setup.cook_id, severity=severity, category=category)

    # 5 + 25 + 5 + 5 = 40, so the score sits exactly on the suspension boundary.
    cook_row = fx.read_cook(api, setup.cook_id)
    assert_fields(
        cook_row,
        safety_score=60,
        compliance_standing="WARNED",
        standing_reason="SAFETY_SCORE_WARN",
    )

    # Nothing cascaded: the cook is still WARNED, not SUSPENDED.
    assert_fields(
        fx.read_menu_item(api, setup.menu_item["id"]),
        review_status="APPROVED",
        delist_reason=None,
    )
    assert_fields(
        fx.read_window(api, setup.window["id"]), status="OPEN", cancelled_reason=None
    )


def test_06_one_minor_incident_past_the_boundary_suspends_and_delists(api):
    """A fifth MINOR incident drops the score to 55, suspending the cook and delisting the dish.

    PRD: "Every `MenuItem` of that cook in `APPROVED` moves to `DELISTED` with `delist_reason` set to `COOK_SUSPENDED`."
    Design: Corner/cross_cutting_complexity_layers/cumulative_severity_points_cross_the_standing_bands_at_their_boundaries
    """
    fx.reset_clock(api)
    setup = fx.selling_cook(api, state_code="CA")

    for severity, category in (
        ("MINOR", "LABEL_MISSING"),
        ("SEVERE", "TEMP_ABUSE"),
        ("MINOR", "LABEL_MISSING"),
        ("MINOR", "LABEL_MISSING"),
        ("MINOR", "FOREIGN_OBJECT"),
    ):
        fx.substantiated_incident(api, setup.cook_id, severity=severity, category=category)

    # 5 + 25 + 5 + 5 + 5 = 45, so 100 - 45 = 55, below the suspension boundary.
    cook_row = fx.read_cook(api, setup.cook_id)
    assert_fields(
        cook_row,
        safety_score=55,
        compliance_standing="SUSPENDED",
        standing_reason="SAFETY_SCORE_SUSPEND",
        onboarding_status="ACTIVE",
    )

    assert_fields(
        fx.read_menu_item(api, setup.menu_item["id"]),
        review_status="DELISTED",
        delist_reason="COOK_SUSPENDED",
    )


def test_07_score_driven_suspension_cancels_the_cooks_open_window(api):
    """The delisting leaves no approved dish, so the cook's OPEN window is cancelled.

    PRD: "Because the cook now has zero `APPROVED` menu items, every `ProductionWindow` of that cook in `OPEN` or `CUTOFF_PASSED` moves to `CANCELLED` with `cancelled_reason` set to `NO_APPROVED_MENU`."
    Design: Corner/cross_cutting_complexity_layers/cumulative_severity_points_cross_the_standing_bands_at_their_boundaries
    """
    fx.reset_clock(api)
    setup = fx.selling_cook(api, state_code="CA")
    assert setup.window["status"] == "OPEN"

    for severity, category in (
        ("MINOR", "LABEL_MISSING"),
        ("SEVERE", "TEMP_ABUSE"),
        ("MINOR", "LABEL_MISSING"),
        ("MINOR", "LABEL_MISSING"),
        ("MINOR", "FOREIGN_OBJECT"),
    ):
        fx.substantiated_incident(api, setup.cook_id, severity=severity, category=category)

    assert_fields(
        fx.read_cook(api, setup.cook_id), safety_score=55, compliance_standing="SUSPENDED"
    )
    assert_fields(
        fx.read_window(api, setup.window["id"]),
        status="CANCELLED",
        cancelled_reason="NO_APPROVED_MENU",
    )
