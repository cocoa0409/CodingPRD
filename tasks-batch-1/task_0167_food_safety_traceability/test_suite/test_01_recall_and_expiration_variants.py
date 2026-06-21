"""Dual-variant calculations: recall exposure (provisional vs finalized) and
the effective-expiration metric (provisional vs finalized).

Queue A — Difficulty/dual_variant_calc.
"""
import pytest
from test_helpers import (
    api_client, validate_success,
    setup_two_finished_lots_from_one_source,
    setup_facility_supplier_ingredient, receive_lot, attach_coa, decide_coa,
    issue_hold, resolve_hold,
    TEST_USERS,
)

QM = TEST_USERS["quality_manager_headers"]
AUDITOR = TEST_USERS["safety_auditor_headers"]


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/recall_exposure_provisional_vs_finalized
# ---------------------------------------------------------------------------

def test_recall_exposure_provisional_sums_all_downstream():
    """PRD 3.9: "When the recalled lot is not covered by any disposed hold at trace
    time, the provisional variant applies: `exposure_variant` reflects the provisional
    case, and `exposure_qty` is the sum of `received_qty` over all downstream finished
    lots in the closure — the worst case in which every produced unit is assumed
    still in commerce."

    Design: Difficulty/dual_variant_calc/recall_exposure_provisional_vs_finalized
    """
    facility, ingredient, lotR, f1_lot, f2_lot, run2_id = \
        setup_two_finished_lots_from_one_source()

    trace = validate_success(api_client.recall_trace(lotR, AUDITOR), 200)
    # F1 received_qty 50 + F2 received_qty 30 = 80 (sum over all downstream finished lots)
    assert trace["exposure_qty"] == 80, f"expected 80, got {trace['exposure_qty']}"
    assert trace["exposure_variant"] == "provisional_exposure"


def test_recall_exposure_finalized_excludes_destroyed_downstream():
    """PRD 3.9: "When the recalled lot is covered by a disposed hold at trace time,
    the finalized variant applies: `exposure_qty` is the sum of `received_qty` over the
    downstream finished lots in the closure excluding any currently in `DESTROYED`
    status, netting out the units already pulled."

    Design: Difficulty/dual_variant_calc/recall_exposure_provisional_vs_finalized
    """
    facility, ingredient, lotR, f1_lot, f2_lot, run2_id = \
        setup_two_finished_lots_from_one_source()

    # Issue and DISPOSE a hold on R. Per PRD 3.7 the dispose destroys R together with
    # its entire downstream genealogy closure {F1, F2}, so every downstream finished
    # lot is now DESTROYED. R is then covered by a disposed hold -> finalized variant.
    hold_r = issue_hold(facility["id"], lotR, reason="RECALL")
    resolve_hold(hold_r["id"], "DISPOSE", hold_r["version"])

    trace = validate_success(api_client.recall_trace(lotR, AUDITOR), 200)
    assert trace["exposure_variant"] == "finalized_exposure"
    # Both downstream finished lots are DESTROYED by the dispose cascade and are
    # therefore excluded from the finalized sum -> exposure_qty nets to 0.
    assert trace["exposure_qty"] == 0, f"expected 0, got {trace['exposure_qty']}"


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/effective_expiration_provisional_vs_finalized
# ---------------------------------------------------------------------------

def test_effective_expiration_provisional_uses_ingredient_shelf_life():
    """PRD 3.2: "The lot's controlling expiration metric, `effective_expiration_date`,
    is set from the provisional rule: it equals the supplied `expiration_date` if one
    was given, otherwise the `production_date` plus the ingredient's `shelf_life_days`."

    Design: Difficulty/dual_variant_calc/effective_expiration_provisional_vs_finalized
    """
    facility, supplier, ingredient = setup_facility_supplier_ingredient(
        coa_required=True,
        ingredient_overrides={"shelf_life_days": 10, "declared_allergen_codes": ["MILK"]})
    lot = receive_lot(facility["id"], ingredient["id"], "L", supplier_id=supplier["id"],
                      received_qty=50, production_date="2026-01-01T00:00:00Z")
    # provisional: production_date 2026-01-01 + ingredient.shelf_life_days 10 = 2026-01-11
    # (timestamps are rendered with three fractional digits per PRD 2.2)
    assert lot["effective_expiration_date"] == "2026-01-11T00:00:00.000Z", \
        f"got {lot['effective_expiration_date']}"


def test_effective_expiration_finalized_shortens_on_coa_accept():
    """PRD 3.2: "Once a certificate on the lot is accepted, the metric is recomputed
    by the finalized rule: it becomes the `production_date` plus the smaller of the
    ingredient's `shelf_life_days` and the certificate's attested shelf life."

    The lot is received with a supplied `expiration_date` far in the future, so the
    provisional metric equals that long date; accepting the certificate recomputes
    the metric down to `production_date + min(shelf_life_days, attested)`, which is
    strictly shorter. Per PRD 3.3 a certificate's `declared_shelf_life_days` must be
    at least the ingredient's `shelf_life_days` to be accepted at all, so the
    attested value is >= 10 and the min resolves to the ingredient's 10 days.

    Design: Difficulty/dual_variant_calc/effective_expiration_provisional_vs_finalized
    """
    facility, supplier, ingredient = setup_facility_supplier_ingredient(
        coa_required=True,
        ingredient_overrides={"shelf_life_days": 10, "declared_allergen_codes": ["MILK"]})
    lot = receive_lot(facility["id"], ingredient["id"], "L", supplier_id=supplier["id"],
                      received_qty=50, production_date="2026-01-01T00:00:00Z",
                      expiration_date="2026-02-15T00:00:00Z")
    # provisional metric uses the supplied (long) expiration_date verbatim
    assert lot["effective_expiration_date"] == "2026-02-15T00:00:00.000Z", \
        f"provisional got {lot['effective_expiration_date']}"
    coa = attach_coa(lot["id"], measured_allergen_codes=["MILK"], pathogen_pass=True,
                     declared_shelf_life_days=12)
    decide_coa(coa["id"], "ACCEPT")

    refreshed = validate_success(api_client.get_lot(lot["id"], QM), 200)
    # finalized: production_date 2026-01-01 + min(10, 12) = 10 days = 2026-01-11,
    # strictly shorter than the provisional 2026-02-15
    assert refreshed["effective_expiration_date"] == "2026-01-11T00:00:00.000Z", \
        f"got {refreshed['effective_expiration_date']}"
