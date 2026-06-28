"""Warranty claims and load cascades: the depth-3 approve cascade, the
fail-then-replace load conservation invariant, the add-on activate/remove
invariant, FULL vs DEPRECIATED credit variants, denial, out-of-warranty
gating, immediate load visibility, and reverse-reachability listing.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    setup_project_with_transformer_and_zone,
    setup_installed_project,
    submit_warranty_claim,
    set_clock,
    create_fixture,
    api_client,
    TEST_USERS,
)
import test_helpers.factories as F

DESIGNER = TEST_USERS["lighting_designer_headers"]
TECH = TEST_USERS["install_tech_headers"]
PROGRAMMER = TEST_USERS["control_programmer_headers"]
ADMIN = TEST_USERS["operations_admin_headers"]


def _installed_with_one_80w(price=9000, warranty=60):
    """An INSTALLED project, one INSTALLED 80W fixture (committed 80), clock 2026-04-15."""
    ctx = setup_installed_project(
        fixture_specs=[{"model_code": "SPOT-80", "category": "SPOT", "wattage_w": 80,
                        "purchase_price_cents": price, "warranty_months": warranty}],
        quote_lines=[{"model_code": "SPOT-80", "quantity": 1, "unit_price_cents": price}],
    )
    set_clock("2026-04-15T00:00:00Z")
    ctx["fixture_id"] = ctx["fixtures"][0]["id"]
    return ctx


# ---------------------------------------------------------------------------
# Depth-3 cascade on claim approve (difficulty: transitive_cascade)
# ---------------------------------------------------------------------------
def test_claim_approve_reinstalls_fixture(api):
    """PRD §3.11: "the approval proceeds: it moves the claim from `SUBMITTED` to
    `APPROVED`, computes the replacement credit and its variant, credits the
    customer's `wallet_credit_cents` by that credit, and re-energizes the fixture
    by moving it from `FAILED` back to `INSTALLED`, re-stamping its `installed_at`
    from the clock and recomputing the zone's `zone_load_va` and the transformer's
    `committed_load_va` upward by the fixture's wattage."

    Link 1 of the cascade: the approve sets the failed fixture back to INSTALLED.

    Design: Difficulty/transitive_cascade/claim_approve_depth3_cascade
    """
    ctx = _installed_with_one_80w()
    claim = submit_warranty_claim(ctx, ctx["fixture_id"], reason="Driver dead")
    validate_success(api.approve_warranty_claim(claim["id"], ADMIN))
    fixture = validate_success(api.get_fixture(ctx["fixture_id"], DESIGNER))
    assert fixture["status"] == "INSTALLED", fixture["status"]


def test_claim_approve_recomputes_zone_and_transformer_load(api):
    """PRD §3.11: "recomputing the zone's `zone_load_va` and the transformer's
    `committed_load_va` upward by the fixture's wattage."

    Links 2 and 3 of the cascade: the re-installed fixture re-enters the load set,
    so zone_load_va and the transformer's committed_load_va both return to 80.

    Design: Difficulty/transitive_cascade/claim_approve_depth3_cascade
    """
    ctx = _installed_with_one_80w()
    claim = submit_warranty_claim(ctx, ctx["fixture_id"], reason="Driver dead")
    validate_success(api.approve_warranty_claim(claim["id"], ADMIN))
    zone = validate_success(api.get_zone(ctx["zone_id"], DESIGNER))
    tx = validate_success(api.get_transformer(ctx["tx_id"], DESIGNER))
    assert zone["zone_load_va"] == 80, zone["zone_load_va"]
    assert tx["committed_load_va"] == 80, tx["committed_load_va"]


# ---------------------------------------------------------------------------
# Load conserved under fail-then-replace (difficulty: compensating_invariant)
# ---------------------------------------------------------------------------
def test_committed_load_drops_to_zero_while_fixture_failed(api):
    """PRD §3.11: "as a cascade it immediately moves that fixture from `INSTALLED`
    to `FAILED`, which drops the fixture out of the load set: the zone's
    `zone_load_va` and the transformer's `committed_load_va` are recomputed
    downward by the fixture's wattage."

    Submitting the claim fails the only fixture, dropping committed_load_va to 0.

    Design: Difficulty/compensating_invariant/transformer_load_conserved_under_fail_then_replace
    """
    ctx = _installed_with_one_80w()
    submit_warranty_claim(ctx, ctx["fixture_id"], reason="Out")
    tx = validate_success(api.get_transformer(ctx["tx_id"], DESIGNER))
    assert tx["committed_load_va"] == 0, tx["committed_load_va"]


def test_committed_load_restored_after_approve(api):
    """PRD §3.11: "re-energizes the fixture by moving it from `FAILED` back to
    `INSTALLED`, re-stamping its `installed_at` from the clock and recomputing the
    zone's `zone_load_va` and the transformer's `committed_load_va` upward by the
    fixture's wattage."

    The compensating approve restores committed_load_va to its exact pre-claim
    value of 80.

    Design: Difficulty/compensating_invariant/transformer_load_conserved_under_fail_then_replace
    """
    ctx = _installed_with_one_80w()
    claim = submit_warranty_claim(ctx, ctx["fixture_id"], reason="Out")
    validate_success(api.approve_warranty_claim(claim["id"], ADMIN))
    fixture = validate_success(api.get_fixture(ctx["fixture_id"], DESIGNER))
    tx = validate_success(api.get_transformer(ctx["tx_id"], DESIGNER))
    assert fixture["status"] == "INSTALLED", fixture["status"]
    assert tx["committed_load_va"] == 80, tx["committed_load_va"]


# ---------------------------------------------------------------------------
# Load conserved under add-on activate/remove (difficulty: compensating_invariant)
# ---------------------------------------------------------------------------
def _installed_with_addon():
    """INSTALLED project, one INSTALLED 80W fixture (committed 80), plus a
    PROPOSED zone-powered AUDIO add-on power_draw 40. Returns (ctx, addon_id)."""
    ctx = setup_installed_project(
        fixture_specs=[{"model_code": "SPOT-80", "category": "SPOT", "wattage_w": 80,
                        "purchase_price_cents": 9000}],
        quote_lines=[{"model_code": "SPOT-80", "quantity": 1, "unit_price_cents": 9000}],
    )
    addon = validate_success(api_client.create_add_on(
        F.create_add_on_payload(ctx["project_id"], kind="AUDIO", power_draw_va=40, zone_id=ctx["zone_id"]),
        PROGRAMMER), expected_status=201)
    return ctx, addon["id"]


def test_addon_activate_adds_power_draw_to_committed_load(api):
    """PRD §3.8: "On activation of a zone-powered module, the transformer's
    `committed_load_va` is recomputed to include this module's `power_draw_va`."

    Activating the 40VA add-on raises committed_load_va from 80 to 120.

    Design: Difficulty/compensating_invariant/customer_wallet_conserved_under_addon_activate_then_remove
    """
    ctx, addon_id = _installed_with_addon()
    validate_success(api.activate_add_on(addon_id, PROGRAMMER))
    tx = validate_success(api.get_transformer(ctx["tx_id"], DESIGNER))
    assert tx["committed_load_va"] == 120, tx["committed_load_va"]


def test_addon_remove_restores_committed_load(api):
    """PRD §3.8: "Removing an active module moves it from `ACTIVE` to `REMOVED`
    (terminal); if it was zone-powered, the transformer's `committed_load_va` is
    recomputed downward by its `power_draw_va`."

    The compensating remove subtracts the 40VA draw, restoring committed_load_va
    to 80.

    Design: Difficulty/compensating_invariant/customer_wallet_conserved_under_addon_activate_then_remove
    """
    ctx, addon_id = _installed_with_addon()
    validate_success(api.activate_add_on(addon_id, PROGRAMMER))
    removed = validate_success(api.remove_add_on(addon_id, PROGRAMMER))
    assert removed["status"] == "REMOVED", removed["status"]
    tx = validate_success(api.get_transformer(ctx["tx_id"], DESIGNER))
    assert tx["committed_load_va"] == 80, tx["committed_load_va"]


# ---------------------------------------------------------------------------
# FULL vs DEPRECIATED warranty credit (difficulty: dual_variant_calc)
# ---------------------------------------------------------------------------
def test_warranty_credit_full_when_within_full_window(api):
    """PRD §3.11: "When the age is at most the 12-month full-coverage window
    (`FULL_WINDOW_MONTHS`), the variant is **FULL** and the `credit_cents` equals
    the fixture's full `purchase_price_cents`."

    A claim approved at fixture age 0 months grants FULL credit of 9000.

    Design: Difficulty/dual_variant_calc/warranty_credit_full_vs_depreciated
    """
    ctx = _installed_with_one_80w(price=9000, warranty=60)
    set_clock("2026-04-15T00:00:00Z")
    claim = submit_warranty_claim(ctx, ctx["fixture_id"], reason="LED out")
    approved = validate_success(api.approve_warranty_claim(claim["id"], ADMIN))
    assert approved["credit_variant"] == "FULL", approved["credit_variant"]
    assert approved["credit_cents"] == 9000, approved["credit_cents"]


def test_warranty_credit_depreciated_after_full_window(api):
    """PRD §3.11: "When the age is greater than 12 months but still strictly less
    than the warranty term ... the variant is **DEPRECIATED**: the system computes
    the remaining months as the warranty term minus the age, and the `credit_cents`
    is the `purchase_price_cents` multiplied by those remaining months, divided by
    the `warranty_months` term, rounded half up to a whole cent."

    Age 30 months on a 60-month/9000 fixture: 9000 * 30 / 60 = 4500.

    Design: Difficulty/dual_variant_calc/warranty_credit_full_vs_depreciated
    """
    ctx = _installed_with_one_80w(price=9000, warranty=60)
    set_clock("2028-09-17T00:00:00Z")  # 900 days -> age 30 months
    claim = submit_warranty_claim(ctx, ctx["fixture_id"], reason="Corrosion")
    approved = validate_success(api.approve_warranty_claim(claim["id"], ADMIN))
    assert approved["credit_variant"] == "DEPRECIATED", approved["credit_variant"]
    assert approved["credit_cents"] == 4500, approved["credit_cents"]


# ---------------------------------------------------------------------------
# Deny keeps fixture FAILED (corner: state_machines)
# ---------------------------------------------------------------------------
def test_deny_claim_grants_no_credit_and_leaves_fixture_failed(api):
    """PRD §3.11: "Denial moves the claim from `SUBMITTED` to `DENIED` (terminal);
    the fixture stays `FAILED` and no credit is granted."

    Design: Corner/state_machines/warranty_claim_deny_keeps_fixture_failed
    """
    ctx = _installed_with_one_80w(price=9000, warranty=60)
    claim = submit_warranty_claim(ctx, ctx["fixture_id"], reason="x")
    denied = validate_success(api.deny_warranty_claim(claim["id"], ADMIN))
    assert denied["status"] == "DENIED", denied["status"]
    assert denied["credit_cents"] == 0, denied["credit_cents"]
    fixture = validate_success(api.get_fixture(ctx["fixture_id"], DESIGNER))
    assert fixture["status"] == "FAILED", fixture["status"]


# ---------------------------------------------------------------------------
# Out-of-warranty boundary (corner: validations)
# ---------------------------------------------------------------------------
def test_approve_out_of_warranty_rejected_at_term_boundary(api):
    """PRD §3.11: "If that age is at least the fixture's `warranty_months`, the
    fixture is out of warranty and approval is rejected with `ERR_OUT_OF_WARRANTY`
    — the boundary where age equals the warranty term is itself out and rejected."

    Age 60 == warranty 60 months (clock at install + 1800 days) is OUT.

    Design: Corner/validations/out_of_warranty_approve_rejected
    """
    ctx = _installed_with_one_80w(price=9000, warranty=60)
    set_clock("2031-03-06T00:00:00Z")  # 1800 days -> age 60 == warranty
    claim = submit_warranty_claim(ctx, ctx["fixture_id"], reason="old")
    validate_error(api.approve_warranty_claim(claim["id"], ADMIN), ApiErrorId.ERR_OUT_OF_WARRANTY.value)
    claim_now = validate_success(api.get_warranty_claim(claim["id"], ADMIN))
    assert claim_now["status"] == "SUBMITTED", claim_now["status"]
    fixture = validate_success(api.get_fixture(ctx["fixture_id"], DESIGNER))
    assert fixture["status"] == "FAILED", fixture["status"]


# ---------------------------------------------------------------------------
# Immediate consistency (corner: consistency_model)
# ---------------------------------------------------------------------------
def test_assign_zone_immediately_reflects_project_total_load(api):
    """PRD §2.5: "A project surfaces `total_committed_load_va`, the sum of
    `committed_load_va` across all transformers belonging to that project". PRD
    §2.11: "The system performs every cascade synchronously and immediately".

    Immediately after a 10W assign, GET /projects/{id} reports
    total_committed_load_va == 10.

    Design: Corner/consistency_model/assign_zone_immediately_reflects_committed_load
    """
    ctx = setup_project_with_transformer_and_zone()
    fx = create_fixture(ctx["project_id"], model_code="A", wattage_w=10, purchase_price_cents=4000)
    validate_success(api.assign_zone(fx["id"], F.assign_zone_payload(ctx["zone_id"], ctx["tx_version"]), DESIGNER))
    project = validate_success(api.get_project(ctx["project_id"], DESIGNER))
    assert project["total_committed_load_va"] == 10, project["total_committed_load_va"]


# ---------------------------------------------------------------------------
# Reverse-reachability listing (corner: cross_cutting_complexity_layers)
# ---------------------------------------------------------------------------
def test_zone_fixtures_list_returns_assigned_fixture(api):
    """PRD §2.9: "the zones fed by a transformer, the lines on a quote, or the
    visits on a route" — nested reads reached through a parent path. PRD §3.2:
    "Assigning a `PLANNED` fixture to a zone is a self-loop that leaves the fixture
    in `PLANNED` but sets its `zone_id`".

    After one assign, GET /zones/{id}/fixtures returns exactly that one fixture.

    Design: Corner/cross_cutting_complexity_layers/fk_reverse_reachability_zone_fixtures_list
    """
    ctx = setup_project_with_transformer_and_zone()
    fx = create_fixture(ctx["project_id"], model_code="A", wattage_w=10, purchase_price_cents=4000)
    validate_success(api.assign_zone(fx["id"], F.assign_zone_payload(ctx["zone_id"], ctx["tx_version"]), DESIGNER))
    fixtures, _meta = validate_paginated(api.list_zone_fixtures(ctx["zone_id"], DESIGNER))
    assert len(fixtures) == 1, fixtures
    assert fixtures[0]["id"] == fx["id"], fixtures[0]["id"]
