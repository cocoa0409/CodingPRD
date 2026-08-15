"""Warranty basis variants, inclusive boundary, and the two estimate variants."""
from test_helpers import (
    authorize_rma,
    create_draft_rma,
    create_model,
    create_customer,
    create_unit,
    diagnose_rma,
    planned_part_line,
    setup_triaged_rma,
    validate_success,
)


def test_retail_purchase_date_basis_computes_coverage(api):
    """PRD §3.2: "For a `RETAIL` unit the basis end date is the unit's
    `purchase_date` plus the model's `standard_warranty_days`; when the unit
    carries a `registration_date`, a registration end is also computed — the
    `registration_date` plus `standard_warranty_days` plus
    `registration_bonus_days` — and the basis end becomes the later of the two."

    Design: Difficulty/dual_variant_calc/warranty_end_purchase_vs_ship_basis
    """
    model = create_model()
    customer = create_customer()
    # RETAIL basis: 2025-08-05 + 365 days = 2026-08-05; clock 2026-08-01 <= end
    unit_r = create_unit(model["id"], customer["id"], serial_number="SN-RB-1",
                         channel="RETAIL", purchase_date="2025-08-05",
                         ship_date="2025-07-01")
    rma_r = create_draft_rma(customer["id"], unit_r["id"], reported_issue="issue R")
    authorized = authorize_rma(rma_r["id"])
    assert authorized["coverage_path"] == "IN_WARRANTY", (
        f"RETAIL unit inside its purchase basis must be IN_WARRANTY, got "
        f"{authorized['coverage_path']}")
    assert authorized["warranty_end_date_used"][:10] == "2026-08-05", (
        f"purchase basis end must be 2026-08-05, got "
        f"{authorized['warranty_end_date_used']}")


def test_enterprise_ship_date_basis_ignores_purchase_date(api):
    """PRD §3.2: "For an `ENTERPRISE` unit the basis end is the `ship_date` plus
    `standard_warranty_days`, and the `purchase_date` is ignored; the two bases
    yield different end dates for identical model constants."
    PRD §3.2: "The computed basis end is pinned as `warranty_end_date_used`, and
    the RMA's `coverage_path` is pinned to `IN_WARRANTY` when the clock date is
    on or before that end — eligibility is inclusive of the final warranty day —
    and to `OUT_OF_WARRANTY` otherwise."

    Design: Difficulty/dual_variant_calc/warranty_end_purchase_vs_ship_basis
    """
    model = create_model()
    customer = create_customer()
    # ENTERPRISE basis: ship 2025-07-01 + 365 days = 2026-07-01 < clock 2026-08-01
    unit_e = create_unit(model["id"], customer["id"], serial_number="SN-EB-1",
                         channel="ENTERPRISE", purchase_date="2025-08-05",
                         ship_date="2025-07-01")
    rma_e = create_draft_rma(customer["id"], unit_e["id"], reported_issue="issue E")
    authorized = authorize_rma(rma_e["id"])
    assert authorized["coverage_path"] == "OUT_OF_WARRANTY", (
        f"ENTERPRISE unit past its ship basis must be OUT_OF_WARRANTY, got "
        f"{authorized['coverage_path']}")
    assert authorized["warranty_end_date_used"][:10] == "2026-07-01", (
        "ship basis end must be 2026-07-01 with purchase_date ignored, got "
        f"{authorized['warranty_end_date_used']}")


def test_authorize_on_final_warranty_day_is_in_warranty(api):
    """PRD §3.2: "The computed basis end is pinned as `warranty_end_date_used`,
    and the RMA's `coverage_path` is pinned to `IN_WARRANTY` when the clock date
    is on or before that end — eligibility is inclusive of the final warranty
    day — and to `OUT_OF_WARRANTY` otherwise."

    Design: Difficulty/boundary_precision_check/warranty_last_day_inclusive
    """
    model = create_model()
    customer = create_customer()
    # purchase 2025-08-01 + 365 days = 2026-08-01 == clock date (inclusive)
    unit_a = create_unit(model["id"], customer["id"], serial_number="SN-WA-1",
                         purchase_date="2025-08-01", ship_date="2025-08-01")
    rma_a = create_draft_rma(customer["id"], unit_a["id"])
    authorized = authorize_rma(rma_a["id"])
    assert authorized["coverage_path"] == "IN_WARRANTY", (
        "authorize on the exact final warranty day must be IN_WARRANTY, got "
        f"{authorized['coverage_path']}")
    assert authorized["warranty_end_date_used"][:10] == "2026-08-01"


def test_authorize_one_day_past_warranty_end_is_out_of_warranty(api):
    """PRD §3.2: "The computed basis end is pinned as `warranty_end_date_used`,
    and the RMA's `coverage_path` is pinned to `IN_WARRANTY` when the clock date
    is on or before that end — eligibility is inclusive of the final warranty
    day — and to `OUT_OF_WARRANTY` otherwise."

    Design: Difficulty/boundary_precision_check/warranty_last_day_inclusive
    """
    model = create_model()
    customer = create_customer()
    # purchase 2025-07-31 + 365 days = 2026-07-31, one day before the clock
    unit_b = create_unit(model["id"], customer["id"], serial_number="SN-WB-1",
                         purchase_date="2025-07-31", ship_date="2025-07-31")
    rma_b = create_draft_rma(customer["id"], unit_b["id"])
    authorized = authorize_rma(rma_b["id"])
    assert authorized["coverage_path"] == "OUT_OF_WARRANTY", (
        "authorize one day past the warranty end must be OUT_OF_WARRANTY, got "
        f"{authorized['coverage_path']}")
    assert authorized["warranty_end_date_used"][:10] == "2026-07-31"


def test_provisional_flat_rate_and_final_estimate_differ(api):
    """PRD §3.2: "Authorization also pins the `provisional_estimate_cents` to
    the model's `flat_rate_repair_cents`, records `authorized_at` from the
    logical clock, and emits an `RMA_AUTHORIZED` notification."
    PRD §3.4: "Diagnosis computes the final estimate, stored in
    `final_estimate_cents`: the `labor_minutes_est` multiplied by the model's
    `labor_rate_cents_per_minute`, rounded half-up to whole cents, plus the sum
    over each planned parts line of its quantity multiplied by the part's
    current `unit_cost_cents`."

    Design: Difficulty/dual_variant_calc/repair_estimate_provisional_vs_final
    """
    ctx = setup_triaged_rma()
    # provisional variant pinned at authorize: flat book rate 15000
    assert ctx["rma"]["provisional_estimate_cents"] == 15000

    diagnosed = diagnose_rma(
        ctx["rma"]["id"], labor_minutes_est=100,
        planned_parts=[planned_part_line(ctx["part"]["id"], 2)])
    # final variant: 100 * 200 + 2 * 5000 = 30000
    assert diagnosed["final_estimate_cents"] == 30000, (
        f"final estimate must be 30000 (100*200 + 2*5000), got "
        f"{diagnosed['final_estimate_cents']}")
    assert diagnosed["provisional_estimate_cents"] == 15000, (
        "the provisional pin must survive diagnosis unchanged")
    assert diagnosed["provisional_estimate_cents"] != diagnosed["final_estimate_cents"]


def test_final_estimate_drives_repair_decision_and_route(api):
    """PRD §3.4: "In every remaining case the decision is `REPAIR`."
    PRD §3.4: "A `REPAIR` decision on an RMA whose `coverage_path` is
    `IN_WARRANTY` or `GOODWILL_FULL` routes straight to `IN_REPAIR`."
    PRD §3.4: "The final variant deliberately uses raw part costs with no
    handling uplift — quotes apply handling separately, per §3.5 — so the final
    estimate and a quote total for the same work can legitimately differ, just
    as the flat book rate pinned at authorization can diverge from both once
    real labor and parts are known."

    Design: Difficulty/dual_variant_calc/repair_estimate_provisional_vs_final
    """
    ctx = setup_triaged_rma()
    diagnosed = diagnose_rma(
        ctx["rma"]["id"], labor_minutes_est=100,
        planned_parts=[planned_part_line(ctx["part"]["id"], 2)])
    # 30000 < floor(100000 * 60 / 100) = 60000 -> REPAIR
    assert diagnosed["decision"] == "REPAIR", (
        f"final estimate 30000 below the 60000 threshold must decide REPAIR, got "
        f"{diagnosed['decision']}")
    assert diagnosed["status"] == "IN_REPAIR", (
        f"in-warranty REPAIR must auto-route to IN_REPAIR, got {diagnosed['status']}")
