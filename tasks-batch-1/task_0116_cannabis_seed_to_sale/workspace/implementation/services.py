"""Cross-aggregate business logic shared by multiple route modules:
harvest yield reconciliation, package terminalization, and harvest auto-finish
(the bubble-up cascade)."""
from decimal import Decimal

import db
from helpers import round2, touch


def recompute_harvest_yield(harvest):
    """harvest_yield_reconciliation (PRD §3.4): packaged_weight_grams is the sum
    of every package's immutable quantity_grams pulled from this harvest;
    remaining_weight_grams = dry_weight_grams - packaged (2dp, round-half-up).
    Runs ONLY on package creation. Does NOT subtract package-level waste."""
    packaged = Decimal("0")
    for pkg in db.packages.values():
        if pkg["harvest_id"] == harvest["id"]:
            packaged += Decimal(str(pkg["quantity_grams"]))
    harvest["packaged_weight_grams"] = round2(packaged)
    if harvest.get("dry_weight_grams") is not None:
        remaining = Decimal(str(harvest["dry_weight_grams"])) - packaged
        harvest["remaining_weight_grams"] = round2(remaining)
    # else remaining stays None (DRYING, pre-cure)


def maybe_auto_finish_harvest(harvest):
    """Bubble-up auto-finish (PRD §3.3 / §3.5, hop 3): a CURED harvest whose
    remaining_weight_grams == 0 and ALL of whose packages are terminal
    (DEPLETED or DESTROYED) auto-transitions CURED -> FINISHED."""
    if harvest is None:
        return
    if harvest["status"] != "CURED":
        return
    if harvest.get("remaining_weight_grams") != 0 and harvest.get("remaining_weight_grams") != 0.0:
        return
    pkgs = [p for p in db.packages.values() if p["harvest_id"] == harvest["id"]]
    if not pkgs:
        return
    if all(p["status"] in ("DEPLETED", "DESTROYED") for p in pkgs):
        harvest["status"] = "FINISHED"
        touch(harvest)
