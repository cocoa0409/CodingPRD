"""Tiered sweep pricing: the provisional-vs-final dual variant and the tiered
combinatorial selection over inspection level, creosote class, glaze, and trip zone."""
from test_helpers import TEST_USERS
from test_helpers import fixtures as fx

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------- dvc provisional vs final
def test_provisional_sweep_quote_at_job_creation():
    """PRD §3.2: "The base charge is set by inspection level: 15000 cents for level
    1, 24000 cents for level 2, and 40000 cents for level 3."
    PRD §3.2: "A trip fee is added by zone: 0 cents for zone `A`, 3500 cents for
    zone `B`, and 7000 cents for zone `C`. The provisional quote is the sum of
    base, creosote surcharge, glaze surcharge, and trip fee."

    Design: Difficulty/dual_variant_calc/dvc_sweep_provisional_vs_final
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 2, "expected_creosote_class": 1, "trip_zone": "B"})
    # 24000 (level 2) + 0 (class 1) + 0 (no glaze) + 3500 (zone B) = 27500
    assert setup["job"]["sweep_provisional_cost_cents"] == 27500


def test_final_sweep_cost_differs_from_provisional_after_sweep():
    """PRD §3.4: "Logging the sweep computes the **final sweep cost** and writes it
    to the job's `sweep_final_cost_cents`, while the log's own `billed_cost_cents`
    mirrors that same amount."
    PRD §3.4: "the creosote surcharge is taken from the `measured_creosote_class`,
    and a glaze surcharge of 5000 cents is added when `glaze_present` is true (and
    zero when false)."

    Design: Difficulty/dual_variant_calc/dvc_sweep_provisional_vs_final
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 2, "expected_creosote_class": 1, "trip_zone": "B"})
    job_id = setup["job"]["id"]
    log = fx.record_sweep(job_id, setup["technician"], measured_creosote_class=3, glaze_present=True)
    # 24000 (level 2) + 18000 (class 3) + 5000 (glaze) + 3500 (zone B) = 50500
    assert log["billed_cost_cents"] == 50500
    job = fx.get_job(job_id)
    assert job["sweep_final_cost_cents"] == 50500
    assert job["sweep_provisional_cost_cents"] == 27500
    assert job["sweep_provisional_cost_cents"] != job["sweep_final_cost_cents"]


# ---------------------------------------------------------------- cf tiered selection
def test_final_cost_tiered_selection_high_tiers():
    """PRD §3.4: "The final cost uses the identical tiered formula as the
    provisional quote — base by inspection level, creosote surcharge by class,
    glaze surcharge, and trip fee by zone — but with the actual field values rather
    than the booking assumptions."
    PRD §3.4: "Base charges (15000, 24000, 40000 cents for levels 1, 2, 3),
    creosote surcharges (0, 6000, 18000 cents for classes 1, 2, 3), and trip fees
    (0, 3500, 7000 cents for zones `A`, `B`, `C`) are exactly as in §3.2."

    Design: Difficulty/combinatorial_formula/cf_sweep_tiered_selection_mode_a
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 3, "trip_zone": "C"})
    job_id = setup["job"]["id"]
    fx.record_sweep(job_id, setup["technician"], measured_creosote_class=2, glaze_present=False)
    # 40000 (level 3) + 6000 (class 2) + 0 (no glaze) + 7000 (zone C) = 53000
    assert fx.get_job(job_id)["sweep_final_cost_cents"] == 53000


def test_final_cost_includes_glaze_surcharge_branch():
    """PRD §3.4: "the creosote surcharge is taken from the `measured_creosote_class`,
    and a glaze surcharge of 5000 cents is added when `glaze_present` is true (and
    zero when false)."
    PRD §3.4: "Base charges (15000, 24000, 40000 cents for levels 1, 2, 3),
    creosote surcharges (0, 6000, 18000 cents for classes 1, 2, 3), and trip fees
    (0, 3500, 7000 cents for zones `A`, `B`, `C`) are exactly as in §3.2."

    Design: Difficulty/combinatorial_formula/cf_sweep_tiered_selection_mode_a
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 1, "trip_zone": "A"})
    job_id = setup["job"]["id"]
    fx.record_sweep(job_id, setup["technician"], measured_creosote_class=1, glaze_present=True)
    # 15000 (level 1) + 0 (class 1) + 5000 (glaze) + 0 (zone A) = 20000
    assert fx.get_job(job_id)["sweep_final_cost_cents"] == 20000
