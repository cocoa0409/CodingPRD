"""Nonconformance reports, MRB disposition costing, and serial cascades (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_ncr,
    disposition_ncr,
    get_serial,
    get_work_order,
    make_headers,
    setup_ncr_in_mrb,
    setup_wo_in_production,
    validate_error,
    validate_success,
)

MP = TEST_USERS["manufacturing_planner"]
QI = TEST_USERS["quality_inspector"]  # insp-1 — NCR discoverer
QI2 = TEST_USERS["quality_inspector_2"]
QM = TEST_USERS["quality_manager"]
MRB = TEST_USERS["mrb_member"]  # mrb-1


def _setup_ncr_mrb(wo_quantity=3, **ncr_overrides):
    """IN_PRODUCTION WO with all serials created, NCR in MRB_REVIEW."""
    bundle = setup_wo_in_production(wo_quantity=wo_quantity, quantity=wo_quantity)
    ncr_defaults = {"quantity_affected": wo_quantity}
    ncr_defaults.update(ncr_overrides)
    ncr = setup_ncr_in_mrb(bundle["wo"]["id"], **ncr_defaults)
    return bundle, ncr


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / ncr_estimated_vs_actual_cost
# ---------------------------------------------------------------------------

def test_ncr_estimated_cost_at_disposition(api):
    """PRD §3.7: "Disposition stores the decision, anchors
    `disposition_by_user_id` to the board member, and computes
    `estimated_cost_cents`: each affected unit's raw cost is
    `rework_hours_per_unit` multiplied by the standard labor rate of 12,500
    cents per hour, plus `material_cost_per_unit_cents`; that per-unit figure
    is rounded half up to integer cents first, and only then multiplied by
    `quantity_affected`."

    Design: Difficulty/dual_variant_calc/ncr_estimated_vs_actual_cost
    """
    bundle, ncr = _setup_ncr_mrb(wo_quantity=3)
    dispositioned = disposition_ncr(
        ncr["id"],
        disposition="REWORK",
        rework_hours_per_unit=0.083,
        material_cost_per_unit_cents=262,
    )
    assert_ncr(dispositioned)
    assert dispositioned["status"] == "DISPOSITIONED"
    # per-unit raw = 0.083 x 12500 + 262 = 1299.5 -> 1300; x 3 units = 3900
    assert dispositioned["estimated_cost_cents"] == 3900, (
        f"round-half-up(1299.5)=1300 then x3 must give 3900, got "
        f"{dispositioned['estimated_cost_cents']}"
    )


def test_ncr_actual_cost_diverges_from_estimate(api):
    """PRD §3.7: "Verification accepts the optional actuals
    `actual_rework_hours_per_unit` and `actual_material_cost_per_unit_cents`;
    when supplied, `actual_cost_cents` is computed with the same
    per-unit-round-then-multiply formula as the estimate, substituting the
    actual inputs — the same formula over different inputs legitimately
    producing a different value for identical quantities."

    Design: Difficulty/dual_variant_calc/ncr_estimated_vs_actual_cost
    """
    bundle, ncr = _setup_ncr_mrb(wo_quantity=3)
    dispositioned = disposition_ncr(
        ncr["id"],
        disposition="REWORK",
        rework_hours_per_unit=0.083,
        material_cost_per_unit_cents=262,
    )
    assert dispositioned["estimated_cost_cents"] == 3900
    verified = validate_success(
        api_client.verify_ncr(
            ncr["id"],
            {
                "actual_rework_hours_per_unit": 0.5,
                "actual_material_cost_per_unit_cents": 262,
            },
            QI2,
        )
    )
    # per-unit actual = 0.5 x 12500 + 262 = 6512; x 3 = 19536
    assert verified["status"] == "VERIFIED"
    assert verified["actual_cost_cents"] == 19536, (
        f"6512 x 3 must give 19536, got {verified['actual_cost_cents']}"
    )
    assert verified["actual_cost_cents"] != verified["estimated_cost_cents"], (
        "the actual variant over different inputs legitimately differs from "
        "the estimate for identical quantities"
    )


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / ncr_cost_per_unit_rounding_order
# ---------------------------------------------------------------------------

def test_ncr_cost_rounds_per_unit_then_multiplies(api):
    """PRD §3.7: "The rounding order is pinned — round each unit, then
    multiply — because summing raw costs across units before rounding yields a
    different result and is not permitted."
    PRD §3.7: "Disposition stores the decision, anchors
    `disposition_by_user_id` to the board member, and computes
    `estimated_cost_cents`: each affected unit's raw cost is
    `rework_hours_per_unit` multiplied by the standard labor rate of 12,500
    cents per hour, plus `material_cost_per_unit_cents`; that per-unit figure
    is rounded half up to integer cents first, and only then multiplied by
    `quantity_affected`."

    Design: Difficulty/combinatorial_formula/ncr_cost_per_unit_rounding_order
    """
    bundle, ncr = _setup_ncr_mrb(wo_quantity=3)
    dispositioned = disposition_ncr(
        ncr["id"],
        disposition="REWORK",
        rework_hours_per_unit=0.083,
        material_cost_per_unit_cents=262,
    )
    # Pinned order: round_half_up(1299.5) = 1300 per unit, then x 3 = 3900.
    assert dispositioned["estimated_cost_cents"] == 3900


def test_ncr_cost_sum_then_round_would_differ(api):
    """PRD §3.7: "The rounding order is pinned — round each unit, then
    multiply — because summing raw costs across units before rounding yields a
    different result and is not permitted."

    Design: Difficulty/combinatorial_formula/ncr_cost_per_unit_rounding_order
    """
    bundle, ncr = _setup_ncr_mrb(wo_quantity=3)
    dispositioned = disposition_ncr(
        ncr["id"],
        disposition="REWORK",
        rework_hours_per_unit=0.083,
        material_cost_per_unit_cents=262,
    )
    # The forbidden sum-then-round order would give round_half_up(3 x 1299.5)
    # = round_half_up(3898.5) = 3899; the pinned order yields 3900.
    assert dispositioned["estimated_cost_cents"] != 3899, (
        "sum-then-round (3899) is not permitted; per-unit-then-multiply is pinned"
    )
    assert dispositioned["estimated_cost_cents"] == 3 * 1300


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / ncr_kickback_and_scrap_branching
# ---------------------------------------------------------------------------

def test_ncr_kickback_cycle_returns_to_open(api):
    """PRD §3.7: "An `MRBMember` may kick a report back — `MRB_REVIEW → OPEN`
    — recording a `reason`, when containment information is insufficient,
    likewise from `MRB_REVIEW` only (`ERR_INVALID_STATE` otherwise)."
    PRD §3.7: "A `QualityManager` submits an `OPEN` report to the board —
    `OPEN → MRB_REVIEW` — from that state only (`ERR_INVALID_STATE`
    otherwise)."

    Design: Difficulty/non_linear_state_machine/ncr_kickback_and_scrap_branching
    """
    bundle = setup_wo_in_production(wo_quantity=2, quantity=2)
    s1 = bundle["serials"][0]
    ncr = setup_ncr_in_mrb(
        bundle["wo"]["id"],
        defect_code="BURR",
        description="burr on flange",
        quantity_affected=1,
        affected_serial_ids=[s1["id"]],
    )
    kicked = validate_success(
        api_client.kickback_ncr(ncr["id"], {"reason": "containment scope unclear"}, MRB)
    )
    assert kicked["status"] == "OPEN", f"kickback cycles back to OPEN, got {kicked['status']}"
    resubmitted = validate_success(api_client.submit_ncr_mrb(ncr["id"], QM))
    assert resubmitted["status"] == "MRB_REVIEW"


def test_ncr_scrap_disposition_after_kickback(api):
    """PRD §3.7: "Under `SCRAP`, every affected serial in `CREATED` or
    `QUARANTINED` moves to `SCRAPPED`, the owning work order's
    `scrapped_quantity` and `good_quantity` are recomputed, and if the work
    order's `good_quantity` has fallen to zero while at least one serial was
    ever created and the work order is `IN_PRODUCTION`, the work order moves to
    `QUALITY_HOLD`."
    PRD §3.7: "Disposition stores the decision, anchors `disposition_by_user_id`
    to the board member, and computes `estimated_cost_cents`: each affected
    unit's raw cost is `rework_hours_per_unit` multiplied by the standard labor
    rate of 12,500 cents per hour, plus `material_cost_per_unit_cents`; that
    per-unit figure is rounded half up to integer cents first, and only then
    multiplied by `quantity_affected`."

    Design: Difficulty/non_linear_state_machine/ncr_kickback_and_scrap_branching
    """
    bundle = setup_wo_in_production(wo_quantity=2, quantity=2)
    s1, s2 = bundle["serials"][0], bundle["serials"][1]
    ncr = setup_ncr_in_mrb(
        bundle["wo"]["id"],
        defect_code="BURR",
        description="burr on flange",
        quantity_affected=1,
        affected_serial_ids=[s1["id"]],
    )
    assert s2["status"] == "CREATED"
    # Kick back and re-submit before dispositioning (the rework loop).
    validate_success(
        api_client.kickback_ncr(ncr["id"], {"reason": "containment scope unclear"}, MRB)
    )
    validate_success(api_client.submit_ncr_mrb(ncr["id"], QM))

    dispositioned = disposition_ncr(
        ncr["id"],
        disposition="SCRAP",
        rework_hours_per_unit=0.5,
        material_cost_per_unit_cents=0,
    )
    assert dispositioned["status"] == "DISPOSITIONED"
    assert dispositioned["disposition"] == "SCRAP"
    # per-unit = 0.5 x 12500 = 6250; x 1 unit = 6250
    assert dispositioned["estimated_cost_cents"] == 6250

    s1_after = get_serial(s1["id"])
    assert s1_after["status"] == "SCRAPPED", (
        f"the affected CREATED serial is scrapped, got {s1_after['status']}"
    )
    wo = get_work_order(bundle["wo"]["id"])
    assert wo["scrapped_quantity"] == 1
    assert wo["good_quantity"] == 1, (
        f"one good serial remains, got good_quantity {wo['good_quantity']}"
    )
    assert wo["status"] == "IN_PRODUCTION", (
        f"no hold while a good serial remains, got {wo['status']}"
    )


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / ncr_scrap_disposition_cascade
# ---------------------------------------------------------------------------

def test_ncr_scrap_disposition_scraps_affected_serials(api):
    """PRD §3.7: "Under `SCRAP`, every affected serial in `CREATED` or
    `QUARANTINED` moves to `SCRAPPED`, the owning work order's
    `scrapped_quantity` and `good_quantity` are recomputed, and if the work
    order's `good_quantity` has fallen to zero while at least one serial was
    ever created and the work order is `IN_PRODUCTION`, the work order moves to
    `QUALITY_HOLD`."

    Design: Difficulty/transitive_cascade/ncr_scrap_disposition_cascade
    """
    bundle = setup_wo_in_production(wo_quantity=2, quantity=2)
    s1, s2 = bundle["serials"][0], bundle["serials"][1]
    ncr = setup_ncr_in_mrb(
        bundle["wo"]["id"],
        defect_code="CRACK",
        description="crack at runout",
        quantity_affected=2,
        affected_serial_ids=[s1["id"], s2["id"]],
    )
    disposition_ncr(
        ncr["id"], disposition="SCRAP", rework_hours_per_unit=0,
        material_cost_per_unit_cents=8000,
    )
    for serial in (s1, s2):
        after = get_serial(serial["id"])
        assert after["status"] == "SCRAPPED", (
            f"every affected serial moves to SCRAPPED, got {after['status']}"
        )
    wo = get_work_order(bundle["wo"]["id"])
    assert wo["scrapped_quantity"] == 2
    assert wo["good_quantity"] == 0


def test_ncr_scrap_of_last_good_serial_holds_work_order(api):
    """PRD §3.7: "Under `SCRAP`, every affected serial in `CREATED` or
    `QUARANTINED` moves to `SCRAPPED`, the owning work order's
    `scrapped_quantity` and `good_quantity` are recomputed, and if the work
    order's `good_quantity` has fallen to zero while at least one serial was
    ever created and the work order is `IN_PRODUCTION`, the work order moves to
    `QUALITY_HOLD`."

    Design: Difficulty/transitive_cascade/ncr_scrap_disposition_cascade
    """
    bundle = setup_wo_in_production(wo_quantity=2, quantity=2)
    s1, s2 = bundle["serials"][0], bundle["serials"][1]
    ncr = setup_ncr_in_mrb(
        bundle["wo"]["id"],
        defect_code="CRACK",
        description="crack at runout",
        quantity_affected=2,
        affected_serial_ids=[s1["id"], s2["id"]],
    )
    disposition_ncr(
        ncr["id"], disposition="SCRAP", rework_hours_per_unit=0,
        material_cost_per_unit_cents=8000,
    )
    wo = get_work_order(bundle["wo"]["id"])
    assert wo["good_quantity"] == 0
    assert wo["serials_created_count"] == 2
    assert wo["status"] == "QUALITY_HOLD", (
        f"good_quantity reaching zero on an IN_PRODUCTION order moves it to "
        f"QUALITY_HOLD, got {wo['status']}"
    )


# ---------------------------------------------------------------------------
# Corner: validations / ncr_disposition_by_discoverer_forbidden
# ---------------------------------------------------------------------------

def test_ncr_disposition_by_discoverer_forbidden(api):
    """PRD §2.9: "Second, the Material Review Board member who dispositions a
    nonconformance report must not be the person who discovered it: the
    disposer's `X-User-ID` must differ from the report's
    `discovered_by_user_id`."
    PRD §2.9: "Three operations enforce segregation of duties by comparing the
    caller's `X-User-ID` to an identifier anchored on the resource, rejecting
    a match with `ERR_SOD_VIOLATION` (403)."

    Design: Corner/validations/ncr_disposition_by_discoverer_forbidden
    """
    bundle = setup_wo_in_production(wo_quantity=1, quantity=1)
    ncr = setup_ncr_in_mrb(bundle["wo"]["id"])  # discovered by insp-1
    # Disposition attempt under the MRBMember role but with the discoverer's id.
    resp = api_client.disposition_ncr(
        ncr["id"],
        {
            "disposition": "REWORK",
            "rework_hours_per_unit": 0.5,
            "material_cost_per_unit_cents": 0,
        },
        make_headers("insp-1", "MRBMember"),
    )
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION.value)


# ---------------------------------------------------------------------------
# Corner: validations / ncr_verify_use_as_is_requires_concession
# ---------------------------------------------------------------------------

def test_ncr_verify_use_as_is_requires_concession(api):
    """PRD §3.7: "Verification then moves `DISPOSITIONED → VERIFIED` under a
    `QualityInspector`, from that state only (`ERR_INVALID_STATE` otherwise);
    a `USE_AS_IS` disposition may not verify until the concession is recorded,
    failing with `ERR_NCR_REQUIRES_CONCESSION` while `concession_approved` is
    false."

    Design: Corner/validations/ncr_verify_use_as_is_requires_concession
    """
    bundle, ncr = _setup_ncr_mrb(wo_quantity=1)
    dispositioned = disposition_ncr(
        ncr["id"],
        disposition="USE_AS_IS",
        rework_hours_per_unit=0,
        material_cost_per_unit_cents=0,
    )
    assert dispositioned["disposition"] == "USE_AS_IS"
    assert dispositioned["concession_approved"] is False
    resp = api_client.verify_ncr(ncr["id"], {}, QI2)
    validate_error(resp, ApiErrorId.ERR_NCR_REQUIRES_CONCESSION.value)
