"""Cure time: the posted conservative SDAT estimate vs the actual stamped
safe_drive_away_at, and the cold/dry cure band (PRD 3.5)."""
from test_helpers import validate_success
from test_helpers import fixtures as fx
from test_helpers import factories as f

ADVISOR = fx.ADVISOR
MANAGER = fx.MANAGER


# ---------------------------------------------------------------------------
# Difficulty rule 1 — sdat_posted_estimate_vs_actual_diverge_on_work_order
# Posted estimate = worst band 270 min -> 13:30Z from a 09:00 clock; actual at
# temp_c=24 (WARM), humidity 40 (no dry penalty) = 60 min -> 10:00Z.
# ---------------------------------------------------------------------------
def test_posted_sdat_estimate_is_270_minutes(api):
    """PRD 3.5: "a computed read for a REPLACE work order returns posted_sdat_minutes
    and posted_safe_drive_away_at assuming the worst band for the day — the cold base
    of 240 minutes plus the dry penalty of 30 minutes, totaling 270 minutes
    regardless of any actual reading."

    Design: Difficulty/dual_variant_calc/sdat_posted_estimate_vs_actual_diverge_on_work_order
    """
    # REPLACE+ADAS in IN_SERVICE; clock at 09:00Z.
    ctx = fx.setup_in_service(decision="REPLACE", adas_equipped=True, state="CA",
                              start_at="2026-06-13T08:00:00Z", end_at="2026-06-13T09:00:00Z",
                              clock="2026-06-13T09:00:00Z")
    wo = ctx["work_order"]
    est = validate_success(api.get_sdat_estimate(wo["id"], ADVISOR), 200)
    assert est["posted_sdat_minutes"] == 270, (
        f"posted estimate must be 270 minutes, got {est['posted_sdat_minutes']}")
    assert est["posted_safe_drive_away_at"] == "2026-06-13T13:30:00.000Z", (
        f"posted SDAT instant must be 13:30Z, got {est['posted_safe_drive_away_at']}")


def test_actual_sdat_warm_dry_diverges_from_posted(api):
    """PRD 3.5: "when temp_c is at least 24 the base is 60 minutes ... a temperature
    of exactly 24 falls in the warm 60-minute band ... a humidity of exactly 15
    incurs no dry-air penalty because the penalty applies only below 15."
    PRD 3.5: "The safe_drive_away_at is the current clock at install-finish advanced
    by the base minutes plus the humidity penalty minutes".

    Design: Difficulty/dual_variant_calc/sdat_posted_estimate_vs_actual_diverge_on_work_order
    """
    ctx = fx.setup_in_service(decision="REPLACE", adas_equipped=True, state="CA",
                              start_at="2026-06-13T08:00:00Z", end_at="2026-06-13T09:00:00Z",
                              clock="2026-06-13T09:00:00Z")
    wo = ctx["work_order"]
    posted = validate_success(api.get_sdat_estimate(wo["id"], ADVISOR), 200)
    # Finish install with temp_c=24 (WARM, 60 min), humidity 40 (no penalty) -> 10:00Z.
    wo_fin = validate_success(api.finish_install(
        wo["id"], {"temp_c": 24, "humidity_pct": 40}, ctx["tech_headers"]), 200)
    assert wo_fin["safe_drive_away_at"] == "2026-06-13T10:00:00.000Z", (
        f"actual SDAT must be 10:00Z (60 min), got {wo_fin['safe_drive_away_at']}")
    assert wo_fin["safe_drive_away_at"] != posted["posted_safe_drive_away_at"], (
        "actual SDAT must diverge from the conservative posted estimate")


# ---------------------------------------------------------------------------
# Corner calculations — sdat_cold_dry_band_270min
# ---------------------------------------------------------------------------
def test_sdat_cold_dry_band_270_minutes(api):
    """PRD 3.5: "when temp_c is below 4 the base is 240 minutes. A humidity penalty
    is then added: when humidity_pct is strictly below 15 an extra 30 minutes is
    added".
    PRD 3.5: "The safe_drive_away_at is the current clock at install-finish advanced
    by the base minutes plus the humidity penalty minutes".

    Design: Corner/calculations/sdat_cold_dry_band_270min
    """
    # REPLACE non-ADAS in IN_SERVICE; clock 09:00Z; finish at temp -5 (COLD 240) + humidity 10 (dry 30) = 270.
    ctx = fx.setup_in_service(decision="REPLACE", adas_equipped=False, state="CA",
                              start_at="2026-06-13T08:00:00Z", end_at="2026-06-13T08:59:00Z",
                              clock="2026-06-13T09:00:00Z")
    wo = ctx["work_order"]
    wo_fin = validate_success(api.finish_install(
        wo["id"], {"temp_c": -5, "humidity_pct": 10}, ctx["tech_headers"]), 200)
    assert wo_fin["safe_drive_away_at"] == "2026-06-13T13:30:00.000Z", (
        f"cold+dry SDAT must be 13:30Z (270 min), got {wo_fin['safe_drive_away_at']}")
    assert wo_fin["status"] == "CURING", f"non-ADAS REPLACE must reach CURING, got {wo_fin['status']}"
