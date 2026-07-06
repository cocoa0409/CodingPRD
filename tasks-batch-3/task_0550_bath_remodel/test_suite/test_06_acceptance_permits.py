"""Closing the sale: estimate-vs-final dual variant, permit surcharge tiering,
permit determination, and the automatic SOLD fork.

Queue A (difficulty): dual_variant_calc / quote_estimate_vs_final_total_permit_surcharge.
Queue B (corner): calculations / permit + surcharge instances.
"""
from test_helpers import (
    setup_presented_quote, setup_accepted_quote,
)


def test_estimate_at_presentation_excludes_permit_surcharge(api):
    """PRD §3.3: "While a quote is only being drafted, its permit_surcharge_cents
    and final_total_cents are not yet determined and remain null; the amount the
    customer is shown at this stage — the estimate — is simply the net price."
    PRD §3.5: "The final_total_cents is the net price plus this permit surcharge;
    it is set only now, at acceptance, and differs from the earlier estimate
    (which was just the net price) precisely by the surcharge whenever a permit is
    required."

    Design: Difficulty/dual_variant_calc/quote_estimate_vs_final_total_permit_surcharge
    """
    ctx = setup_presented_quote(
        api, area=60.0, wall_system="SMOOTH_ACRYLIC",
        accessibility_addon="WALK_IN_TUB", promo_code="SPRING750")
    quote = ctx["quote"]
    assert quote["net_price_cents"] == 617344
    assert quote["final_total_cents"] is None, "final_total is null until acceptance"
    assert quote["permit_surcharge_cents"] is None, "surcharge is null until acceptance"


def test_final_total_at_acceptance_adds_high_permit_surcharge(api):
    """PRD §3.5: "if the net price is at most 500000 cents the surcharge is 15000
    cents, and if the net price is greater than 500000 cents the surcharge is
    30000 cents."
    PRD §3.5: "The project then forks automatically on permit_required: when a
    permit is required it advances SOLD → PERMIT_PENDING and its permit_status
    moves to PENDING; when none is required it advances SOLD → INSTALL_READY and
    its permit_status stays NOT_APPLICABLE."

    Design: Difficulty/dual_variant_calc/quote_estimate_vs_final_total_permit_surcharge
    """
    ctx = setup_accepted_quote(
        api, area=60.0, wall_system="SMOOTH_ACRYLIC",
        accessibility_addon="WALK_IN_TUB", promo_code="SPRING750")
    quote, project = ctx["quote"], ctx["project"]
    assert quote["status"] == "ACCEPTED"
    assert quote["permit_surcharge_cents"] == 30000  # net 617344 > 500000
    assert quote["final_total_cents"] == 647344       # 617344 + 30000
    assert project["permit_required"] is True
    assert project["status"] == "PERMIT_PENDING"


def test_grab_bars_addon_triggers_no_permit_or_surcharge(api):
    """PRD §3.5: "a permit is required exactly when that add-on is WALK_IN_TUB or
    BARRIER_FREE_SHOWER, and is not required for NONE or GRAB_BARS."
    PRD §3.5: "When no permit is required, the surcharge is 0. The
    final_total_cents is the net price plus this permit surcharge."

    Design: Corner/calculations/grab_bars_addon_no_permit_no_surcharge
    """
    ctx = setup_accepted_quote(
        api, area=100.0, wall_system="TILE_LOOK_ACRYLIC", accessibility_addon="GRAB_BARS")
    quote, project = ctx["quote"], ctx["project"]
    assert quote["addon_price_cents"] == 29900
    assert quote["permit_surcharge_cents"] == 0
    assert quote["final_total_cents"] == 572700  # 542800 + 29900, no discount, no surcharge
    assert project["permit_required"] is False
    assert project["status"] == "INSTALL_READY"


def test_permit_surcharge_low_tier_barrier_free_shower(api):
    """PRD §3.5: "if the net price is at most 500000 cents the surcharge is 15000
    cents, and if the net price is greater than 500000 cents the surcharge is
    30000 cents."
    PRD §3.5: "a permit is required exactly when that add-on is WALK_IN_TUB or
    BARRIER_FREE_SHOWER, and is not required for NONE or GRAB_BARS."

    Design: Corner/calculations/permit_surcharge_low_tier_barrier_free_shower
    """
    ctx = setup_accepted_quote(
        api, area=40.0, wall_system="SMOOTH_ACRYLIC", accessibility_addon="BARRIER_FREE_SHOWER")
    quote, project = ctx["quote"], ctx["project"]
    assert quote["net_price_cents"] == 399900  # SMOOTH/40 (150000) + BFS (249900)
    assert quote["permit_surcharge_cents"] == 15000  # net 399900 <= 500000
    assert quote["final_total_cents"] == 414900
    assert project["permit_required"] is True
