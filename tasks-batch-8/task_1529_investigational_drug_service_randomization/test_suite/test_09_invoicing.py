"""Site invoicing: the five lines, variant divergence, tier boundary, storage
input-set filtering, and pinned rounding order (PRD §2.9, §3.9)."""
from test_helpers import (
    api_client, validate_success, ApiErrorId,
    setup_pharmacy, setup_dual_variant_invoice_scenario,
    setup_monitor_rounding_scenario, setup_subject_with_allocated_kit,
    upload_slots, slot_spec, register_subject, randomize_subject,
    allocate_next_kit, set_clock, dispense_kit,
)
from test_helpers import TEST_USERS

SPONSOR = TEST_USERS["sponsor_admin_headers"]

PERIOD = {"period_start": "2026-08-01T00:00:00Z", "period_end": "2026-10-01T00:00:00Z"}


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / invoice_provisional_includes_pipeline_fees_final_excludes
# ---------------------------------------------------------------------------

def test_invoice_final_excludes_pipeline_fees():
    """PRD §3.9: "under the `FINAL` variant, visits in `CLOSED_RECONCILED` or
    `CLOSED_DISCREPANCY` whose `closed_at` falls in the period are billed at
    their `actual_minutes`" and "under `FINAL`, the count of unblinding requests
    belonging to subjects at this site in `EXECUTED` status whose `updated_at`
    (the execution time) falls in the period". PRD §3.9: "The invoice then
    totals in a pinned order: `subtotal_cents` is the sum of the five lines;
    `overhead_cents` is the subtotal multiplied by `overhead_pct` and divided by
    one hundred, rounded half-up to a whole cent; and `total_cents` is the
    subtotal plus the overhead."

    Design: Difficulty/dual_variant_calc/invoice_provisional_includes_pipeline_fees_final_excludes
    """
    world = setup_dual_variant_invoice_scenario()
    resp = api_client.get_site_invoice(world["site"]["id"], SPONSOR,
                                       params={**PERIOD, "variant": "FINAL"})
    invoice = validate_success(resp)
    assert invoice["setup_fee_cents"] == 100000, "activated_at 2026-08-01 is in the period"
    assert invoice["dispensing_fees_cents"] == 18000, (
        "SUB-A 5000+5000+3000 (tier crossing), SUB-B 5000"
    )
    assert invoice["monitoring_fees_cents"] == 8334, (
        "two closed 25-minute visits; the SCHEDULED visit is excluded under FINAL"
    )
    assert invoice["storage_fees_cents"] == 200, "only K-5 and K-6 remain AVAILABLE"
    assert invoice["unblinding_fees_cents"] == 0, (
        "the APPROVED-but-unexecuted request is excluded under FINAL"
    )
    assert invoice["subtotal_cents"] == 126534
    assert invoice["overhead_cents"] == 12653
    assert invoice["total_cents"] == 139187


def test_invoice_provisional_includes_pipeline_fees_and_diverges():
    """PRD §3.9: "under `PROVISIONAL`, any visit in `SCHEDULED`, `IN_PROGRESS`,
    `CLOSED_RECONCILED`, or `CLOSED_DISCREPANCY` whose scheduled window overlaps
    the period is billed, using `actual_minutes` for closed visits and the whole
    minutes between `scheduled_start` and `scheduled_end` for unclosed ones" and
    "under `PROVISIONAL`, requests in `APPROVED` or `EXECUTED` with `updated_at`
    in the period." PRD §3.9: "For identical site data the two variants diverge
    exactly when pipeline visits or approved-but-not-yet-executed unblinding
    requests exist."

    Design: Difficulty/dual_variant_calc/invoice_provisional_includes_pipeline_fees_final_excludes
    """
    world = setup_dual_variant_invoice_scenario()
    provisional = validate_success(api_client.get_site_invoice(
        world["site"]["id"], SPONSOR, params={**PERIOD, "variant": "PROVISIONAL"}))
    final = validate_success(api_client.get_site_invoice(
        world["site"]["id"], SPONSOR, params={**PERIOD, "variant": "FINAL"}))
    assert provisional["monitoring_fees_cents"] == 18334, (
        "adds the SCHEDULED 60-minute visit at 10000 cents"
    )
    assert provisional["unblinding_fees_cents"] == 25000, (
        "the APPROVED request is included under PROVISIONAL"
    )
    assert provisional["subtotal_cents"] == 161534
    assert provisional["overhead_cents"] == 16153
    assert provisional["total_cents"] == 177687
    assert provisional["total_cents"] != final["total_cents"], (
        "the two variants diverge for identical site data"
    )


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / monitoring_fee_per_line_rounding_pinned
# ---------------------------------------------------------------------------

def test_monitoring_fee_rounded_per_visit_before_summing():
    """PRD §3.9: "Each visit's fee is `monitoring_fee_cents_per_hour` multiplied
    by its minutes and divided by sixty, rounded half-up to a whole cent per
    visit, and the line is the sum of those per-visit amounts." PRD §2.9: "Two
    rounding points are pinned: per-visit monitoring fees are rounded half-up
    individually before they are summed into the monitoring line, and overhead
    is computed once on the already-rounded line subtotal and rounded half-up a
    single time."

    Design: Difficulty/combinatorial_formula/monitoring_fee_per_line_rounding_pinned
    """
    world = setup_monitor_rounding_scenario()
    invoice = validate_success(api_client.get_site_invoice(
        world["site"]["id"], SPONSOR, params={**PERIOD, "variant": "FINAL"}))
    assert invoice["monitoring_fees_cents"] == 8334, (
        "per-line rounding: round_half_up(10000*25/60) = 4167 twice = 8334, "
        "not the sum-then-round 8333"
    )


def test_monitoring_fee_rounding_invoice_totals():
    """PRD §3.9: "The invoice then totals in a pinned order: `subtotal_cents` is
    the sum of the five lines; `overhead_cents` is the subtotal multiplied by
    `overhead_pct` and divided by one hundred, rounded half-up to a whole cent;
    and `total_cents` is the subtotal plus the overhead."

    Design: Difficulty/combinatorial_formula/monitoring_fee_per_line_rounding_pinned
    """
    world = setup_monitor_rounding_scenario()
    invoice = validate_success(api_client.get_site_invoice(
        world["site"]["id"], SPONSOR, params={**PERIOD, "variant": "FINAL"}))
    assert invoice["subtotal_cents"] == 8334, "all other fee lines are zero"
    assert invoice["overhead_cents"] == 833, "round_half_up(8334 x 10 / 100) = 833"
    assert invoice["total_cents"] == 9167


# ---------------------------------------------------------------------------
# Corner: calculations
# ---------------------------------------------------------------------------

def test_dispensing_tier_boundary_exact_threshold_gets_base_fee():
    """PRD §3.9: "Within each subject's own records, ordered by `dispensed_at`
    with ties broken by `created_at`, the subject's cumulative dispensing index
    decides the rate: positions up to and including `dispensing_tier_threshold`
    each bill `dispensing_fee_cents`, and every position beyond the threshold
    bills `dispensing_tier_fee_cents`."

    Design: Corner/calculations/dispensing_tier_boundary_exact_threshold_gets_base_fee
    """
    world = setup_pharmacy(protocol_number="P-CAL-1", kit_numbers=("K-T1", "K-T2", "K-T3"),
                           pharmacist_license="L-CAL-1",
                           fee_overrides={"storage_fee_cents_per_kit_month": 0})
    p_id = world["pharmacist"]["id"]
    upload_slots(world["study"]["id"], world["study_version"], [
        slot_spec(1, "K-T1", arm_code="TRT-A"), slot_spec(2, "K-T2", arm_code="PBO"),
        slot_spec(3, "K-T3", arm_code="TRT-A"),
    ])
    kits = {k["kit_number"]: k for k in world["kits"]}
    subject = randomize_subject(register_subject(world["site"]["id"], "SUB-TB", p_id)["id"], p_id)
    dispense_kit(subject["id"], kits["K-T1"]["id"], 1, 1, p_id)
    allocate_next_kit(subject["id"], p_id)
    set_clock("2026-08-29T00:00:00Z")
    dispense_kit(subject["id"], kits["K-T2"]["id"], 2, 1, p_id)
    allocate_next_kit(subject["id"], p_id)
    set_clock("2026-09-26T00:00:00Z")
    dispense_kit(subject["id"], kits["K-T3"]["id"], 3, 1, p_id)
    invoice = validate_success(api_client.get_site_invoice(
        world["site"]["id"], SPONSOR, params={**PERIOD, "variant": "FINAL"}))
    assert invoice["dispensing_fees_cents"] == 13000, (
        "5000 for n=1, 5000 for n=2 at the threshold (inclusive), 3000 for n=3"
    )
    assert invoice["total_cents"] == 13000, "all other lines zero and overhead 0%"


def test_invoice_storage_line_excludes_dispensed_kits():
    """PRD §3.9: "**Storage** — the count of kits at the site in `AVAILABLE`,
    `ALLOCATED`, or `QUARANTINED_EXCURSION` whose `created_at` precedes
    `period_end`, evaluated at read time and identical under both variants,
    multiplied by `storage_fee_cents_per_kit_month`."

    Design: Corner/calculations/invoice_storage_line_excludes_dispensed_kits
    """
    world = setup_pharmacy(protocol_number="P-CAL-4", kit_numbers=("K-ST1", "K-ST2"),
                           pharmacist_license="L-CAL-4",
                           fee_overrides={"dispensing_fee_cents": 0,
                                          "dispensing_tier_fee_cents": 0,
                                          "monitoring_fee_cents_per_hour": 0,
                                          "unblinding_fee_cents": 0})
    disp = setup_subject_with_allocated_kit(world, subject_number="SUB-ST",
                                            kit_numbers=["K-ST1"])
    dispense_kit(disp["subject"]["id"], disp["kit"]["id"], 1, 1,
                 world["pharmacist"]["id"])
    invoice = validate_success(api_client.get_site_invoice(
        world["site"]["id"], SPONSOR, params={**PERIOD, "variant": "FINAL"}))
    assert invoice["storage_fees_cents"] == 100, (
        "only K-ST2 is in a storage state; the DISPENSED K-ST1 is excluded"
    )
