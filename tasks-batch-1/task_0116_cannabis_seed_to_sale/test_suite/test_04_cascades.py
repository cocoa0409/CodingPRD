"""Transitive cascades: the FAILED_TEST destruction depth-3 chain and the
sale-finalize depletion depth-2 chain."""
from test_helpers import (
    validate_success,
    create_cultivation_license, create_testing_license,
    create_failed_package, setup_retail_scenario,
    open_sale_with_line, finalize_sale,
    cult_h, cm_h, bud_h,
)
from test_helpers import api_client


# ---------------------------------------------------------------------------
# Rule 4 (transitive_cascade): FAILED_TEST destroy, depth 3
# ---------------------------------------------------------------------------
def test_failed_test_full_destroy_terminalizes_package(api):
    """PRD §3.5: "First, the destruction sets the package's `remaining_grams` to
    0; because the destruction is required to consume the full remaining grams,
    this drives the package to the terminal `DESTROYED` status as the second
    hop, and the package's `version` increments."

    Design: Difficulty/transitive_cascade/failed_test_destroy_cascade_depth3
    """
    cul = create_cultivation_license()
    lab = create_testing_license()
    pkg, harvest = create_failed_package(cul["id"], lab["id"], quantity_grams=600,
                                         dry_weight_grams=600)
    assert pkg["status"] == "FAILED"
    api.create_waste_event({
        "source_type": "PACKAGE", "package_id": pkg["id"], "reason": "FAILED_TEST",
        "destroyed_grams": 600, "destroyed_at": "2026-06-05T00:00:00Z",
    }, cm_h("cm-1"))
    data = validate_success(api.get_package(pkg["id"], cm_h("cm-1")))
    assert data["remaining_grams"] == 0  # hop 1
    assert data["status"] == "DESTROYED"  # hop 2


def test_failed_test_destroy_auto_finishes_harvest(api):
    """PRD §3.3: "when the harvest is `CURED` with `remaining_weight_grams` at
    exactly 0 and every one of its packages has reached a terminal status —
    either `DEPLETED` through sale or `DESTROYED` through a failed-test
    destruction — the system closes the harvest from `CURED` to `FINISHED` on
    its own and increments the harvest's `version`."

    Design: Difficulty/transitive_cascade/failed_test_destroy_cascade_depth3
    """
    cul = create_cultivation_license()
    lab = create_testing_license()
    pkg, harvest = create_failed_package(cul["id"], lab["id"], quantity_grams=600,
                                         dry_weight_grams=600)
    assert harvest["status"] == "CURED"
    assert harvest["remaining_weight_grams"] == 0.0
    api.create_waste_event({
        "source_type": "PACKAGE", "package_id": pkg["id"], "reason": "FAILED_TEST",
        "destroyed_grams": 600, "destroyed_at": "2026-06-05T00:00:00Z",
    }, cm_h("cm-1"))
    data = validate_success(api.get_harvest(harvest["id"], cult_h()))
    assert data["status"] == "FINISHED"  # hop 3 bubble-up auto-finish


# ---------------------------------------------------------------------------
# Rule 4 (transitive_cascade): sale finalize depletion, depth 2
# ---------------------------------------------------------------------------
def test_sale_finalize_depletes_package_to_zero(api):
    """PRD §3.7: "each line's package has its `remaining_grams` decremented by
    that line's `grams` as a cascade, any package whose `remaining_grams`
    thereby reaches exactly 0 auto-transitions from `ACTIVE` to the terminal
    `DEPLETED` state (with its `version` advancing)"

    Design: Difficulty/transitive_cascade/sale_finalize_deplete_cascade_depth2
    """
    scn = setup_retail_scenario(daily_purchase_limit_grams=28.5, is_medical=False,
                                product_category="FLOWER", package_quantity=10)
    pkg_id = scn["package"]["id"]
    assert scn["package"]["remaining_grams"] == 10.0
    sale = open_sale_with_line(scn["ret"]["id"], scn["customer"]["id"], pkg_id, 10.0,
                               sale_date="2026-06-06T00:00:00Z")
    validate_success(finalize_sale(sale["id"], expected_version=sale["version"]))
    data = validate_success(api.get_package(pkg_id, cult_h()))
    assert data["remaining_grams"] == 0  # hop 1
    assert data["status"] == "DEPLETED"  # hop 2


def test_sale_finalize_marks_sale_finalized(api):
    """PRD §3.7: "On a successful finalize, the sale moves to `FINALIZED`, each
    line's package has its `remaining_grams` decremented by that line's `grams`
    as a cascade"

    Design: Difficulty/transitive_cascade/sale_finalize_deplete_cascade_depth2
    """
    scn = setup_retail_scenario(daily_purchase_limit_grams=28.5, is_medical=False,
                                product_category="FLOWER", package_quantity=10)
    sale = open_sale_with_line(scn["ret"]["id"], scn["customer"]["id"],
                               scn["package"]["id"], 10.0,
                               sale_date="2026-06-06T00:00:00Z")
    data = validate_success(finalize_sale(sale["id"], expected_version=sale["version"]))
    assert data["status"] == "FINALIZED"
