"""Results landing exactly on their requirement, the input set the hardness
indices draw from, and the per-line pack discount."""

import pytest

from test_helpers import (
    TEST_USERS,
    advance_lot,
    api_client,
    assert_specimen_ledger,
    create_chamber,
    create_pack,
    create_sku,
    pack_member_payload,
    read_lot,
    read_pack,
    read_test_run,
    schedule_test_run,
    setup_lot_at_stage,
    setup_lot_with_completed_campaign,
    submit_results,
    validate_paginated,
    validate_success,
    void_payload,
)

CM = TEST_USERS["channel_manager_headers"]
QE = TEST_USERS["quality_engineer_headers"]

DIM_WINDOW = ("2026-08-03T08:00:00Z", "2026-08-03T09:00:00Z")
SALT_WINDOW = ("2026-08-04T00:00:00Z", "2026-08-08T00:00:00Z")
HARD_FIRST_WINDOW = ("2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
HARD_SECOND_WINDOW = ("2026-08-03T12:00:00Z", "2026-08-03T13:00:00Z")

BRANDED_SOCKET = {
    "sku_code": "SO-20-BR",
    "tool_family": "SOCKET",
    "channel": "BRANDED",
    "nominal_size_mm": 20,
    "alloy_grade": "CR_V",
    "list_price_cents": 1500,
    "warranty_tier": "LIFETIME",
}


# ---------------------------------------------------------------------------
# Results exactly on the requirement
# ---------------------------------------------------------------------------


def _boundary_battery():
    """A PLATED CR_MO wrench lot of 20 specimens driven through four two-specimen
    runs, each landing on or one tenth below its requirement."""
    ctx = setup_lot_at_stage("PLATED", lot_overrides={"specimen_pool_total": 20})
    lot_id = ctx["lot"]["id"]
    chamber = create_chamber(coupon_capacity=24)
    ctx["chamber"] = chamber

    dim = schedule_test_run(lot_id, "DIMENSIONAL", 2, DIM_WINDOW)
    ctx["dimensional"] = submit_results(dim["id"], (0.15, -0.10))

    salt = schedule_test_run(lot_id, "SALT_SPRAY", 2, SALT_WINDOW, chamber_id=chamber["id"])
    ctx["salt_spray"] = submit_results(salt["id"], (96.0, 100.0))

    first = schedule_test_run(lot_id, "HARDNESS", 2, HARD_FIRST_WINDOW)
    ctx["hardness_on_the_bar"] = submit_results(first["id"], (49.5, 50.5))

    second = schedule_test_run(lot_id, "HARDNESS", 2, HARD_SECOND_WINDOW)
    ctx["hardness_below_the_bar"] = submit_results(second["id"], (49.8, 50.0))

    ctx["lot"] = read_lot(lot_id)
    return ctx


def test_a_worst_deviation_exactly_on_the_tolerance_passes_with_no_headroom():
    """The largest absolute deviation is 0.15 against a 0.15 tolerance, an
    inclusive at-most comparison that yields a flat zero margin.

    PRD §3.4: "For `DIMENSIONAL` the direction inverts: the governing statistic is
    the largest absolute value among the readings, treating a deviation of minus
    0.12 millimetres exactly as severe as plus 0.12, the requirement is a tolerance
    of 0.15 millimetres, and the run passes when the statistic is at most the
    requirement."

    Design: Corner/calculations/test_outcome_boundaries_at_exact_requirement_and_one_step_below
    """
    ctx = _boundary_battery()
    run = ctx["dimensional"]

    assert run["governing_statistic"] == pytest.approx(0.15, abs=0.01)
    assert run["requirement_value"] == pytest.approx(0.15, abs=0.01)
    assert run["status"] == "PASSED"
    assert run["result_margin_pct"] == pytest.approx(0.00, abs=0.01)


def test_the_weakest_coupon_exactly_on_the_channel_standard_passes():
    """A BRANDED SKU is judged on 96 hours, and the smallest of the two readings is
    the governing figure even though the mean is higher.

    PRD §3.4: "For `SALT_SPRAY` the governing statistic is the smallest reading in
    hours of exposure and the requirement is the channel's corrosion standard — 96
    hours for `BRANDED`, 48 hours for `PRIVATE_LABEL`, 168 hours for
    `PROFESSIONAL` — pass-when-at-least."

    Design: Corner/calculations/test_outcome_boundaries_at_exact_requirement_and_one_step_below
    """
    ctx = _boundary_battery()
    run = ctx["salt_spray"]

    assert run["governing_statistic"] == pytest.approx(96.0, abs=0.01)
    assert run["requirement_value"] == pytest.approx(96.0, abs=0.01)
    assert run["mean_reading"] == pytest.approx(98.0, abs=0.01)
    assert run["status"] == "PASSED"
    assert run["result_margin_pct"] == pytest.approx(0.00, abs=0.01)


def test_a_hardness_mean_landing_on_the_alloy_minimum_passes():
    """Readings of 49.5 and 50.5 average to exactly the CR_MO minimum of 50.0, and
    the inclusive comparison passes it with zero headroom.

    PRD §3.4: "Every comparison is inclusive, so a hardness mean landing exactly on
    the alloy minimum passes, and a worst deviation landing exactly on the tolerance
    passes."

    Design: Corner/calculations/test_outcome_boundaries_at_exact_requirement_and_one_step_below
    """
    ctx = _boundary_battery()
    run = ctx["hardness_on_the_bar"]

    assert run["mean_reading"] == pytest.approx(50.0, abs=0.01)
    assert run["requirement_value"] == pytest.approx(50.0, abs=0.01)
    assert run["status"] == "PASSED"
    assert run["result_margin_pct"] == pytest.approx(0.00, abs=0.01)


def test_one_tenth_below_the_minimum_fails_and_rejects_the_whole_lot():
    """A mean of 49.9 is a negative margin of -0.20 on a mandatory wrench test, so
    the dossier is rejected and the metal quarantined in the same request.

    PRD §3.4: "And if the failed run was `mandatory` and the lot's dossier is
    `IN_TEST`, the failure **rejects the whole lot**, firing a three-link cascade
    in the same request."

    Design: Corner/calculations/test_outcome_boundaries_at_exact_requirement_and_one_step_below
    """
    ctx = _boundary_battery()
    run = ctx["hardness_below_the_bar"]

    assert run["mean_reading"] == pytest.approx(49.9, abs=0.01)
    assert run["status"] == "FAILED"
    assert run["result_margin_pct"] == pytest.approx(-0.20, abs=0.01)

    lot = ctx["lot"]
    assert lot["cert_status"] == "REJECTED"
    assert lot["disposition"] == "QUARANTINED"
    assert lot["specimens_consumed"] == 8
    assert lot["specimens_available"] == 12
    assert_specimen_ledger(lot)


# ---------------------------------------------------------------------------
# What the hardness indices are allowed to see
# ---------------------------------------------------------------------------


def _lot_with_a_void_a_pending_and_a_passed_hardness_run():
    """A HEAT_TREATED lot of 20 specimens carrying one VOID run of four, one
    SCHEDULED run of three, and one PASSED run of two."""
    ctx = setup_lot_with_completed_campaign(lot_overrides={"specimen_pool_total": 20})
    lot_id = ctx["lot"]["id"]
    advance_lot(lot_id, "HEAT_TREATED")

    voided = schedule_test_run(lot_id, "HARDNESS", 4, DIM_WINDOW)
    ctx["voided"] = validate_success(
        api_client.void_test_run(
            voided["id"], void_payload(void_reason="Specimens mislabelled"), QE
        )
    )
    ctx["pending"] = schedule_test_run(lot_id, "HARDNESS", 3, HARD_FIRST_WINDOW)

    passed = schedule_test_run(lot_id, "HARDNESS", 2, HARD_SECOND_WINDOW)
    ctx["passed"] = submit_results(passed["id"], (52.0, 53.0))

    ctx["lot"] = read_lot(lot_id)
    return ctx


def test_both_indices_read_only_the_passed_run_and_ignore_the_void_and_pending_ones():
    """With a single qualifying run of 52.0 and 53.0 the two variants coincide at
    52.50 instead of being diluted by the excluded rows.

    PRD §3.4: "The lot's two hardness indices are computed from the same input set
    — every `HARDNESS` run on the lot whose status is `PASSED`, taken in
    `created_at` ascending order, with `SCHEDULED`, `FAILED` and `VOID` runs
    excluded from both — but they aggregate it differently, and the difference is
    not cosmetic."

    Design: Corner/calculations/hardness_index_input_set_excludes_void_and_scheduled_runs
    """
    ctx = _lot_with_a_void_a_pending_and_a_passed_hardness_run()

    assert ctx["voided"]["status"] == "VOID"
    assert read_test_run(ctx["pending"]["id"])["status"] == "SCHEDULED"
    assert ctx["passed"]["status"] == "PASSED"
    assert ctx["passed"]["mean_reading"] == pytest.approx(52.5, abs=0.01)

    lot = ctx["lot"]
    assert lot["hardness_index_pooled"] == pytest.approx(52.50, abs=0.01)
    assert lot["hardness_index_sample"] == pytest.approx(52.50, abs=0.01)


def test_the_three_run_history_is_visible_while_only_the_scheduled_run_holds_specimens():
    """The voided four are back in the pool, the scheduled three are still
    committed and the resolved two are consumed, yet all three rows remain
    listable.

    PRD §2.9: "Scheduling a test moves specimens from available to committed;
    recording a result moves them from committed to consumed; voiding a scheduled run
    moves them from committed back to available, which makes scheduling and voiding an
    exact forward-and-compensating pair."

    Design: Corner/calculations/hardness_index_input_set_excludes_void_and_scheduled_runs
    """
    ctx = _lot_with_a_void_a_pending_and_a_passed_hardness_run()
    lot = ctx["lot"]

    assert lot["specimens_committed"] == 3
    assert lot["specimens_consumed"] == 2
    assert lot["specimens_available"] == 15
    assert_specimen_ledger(lot)

    _, meta = validate_paginated(
        api_client.list_lot_test_runs(lot["id"], QE, params={"test_type": "HARDNESS"})
    )
    assert meta["total_count"] == 3


# ---------------------------------------------------------------------------
# Per-line pack pricing
# ---------------------------------------------------------------------------


def _two_packs_on_the_same_hero_sku():
    """One DRAFT display carton and one DRAFT multipack built around the same
    3300 cent wrench, with a 1500 cent socket available as a second member."""
    hero = create_sku()
    partner = create_sku(**BRANDED_SOCKET)
    display = create_pack(hero["id"], pack_code="PK-RD-1", pack_type="RETAIL_DISPLAY")
    multipack = create_pack(hero["id"], pack_code="PK-MP-1", pack_type="MULTIPACK")
    return hero, partner, display, multipack


def test_the_same_sku_and_quantity_price_differently_in_a_display_and_a_multipack():
    """A display carton sells at list, so two wrenches extend to 6600 cents, while
    the twelve-percent multipack concession makes the identical line 5808.

    PRD §3.6: "The discount is 1.00 for `RETAIL_DISPLAY` and for `SECURITY` — those
    formats are sold at list — and 0.88 for `MULTIPACK`, the twelve-percent volume
    concession that makes a multipack worth buying."

    Design: Corner/calculations/pack_member_line_extension_applies_pack_type_discount
    """
    hero, _, display, multipack = _two_packs_on_the_same_hero_sku()

    display_line = validate_success(
        api_client.add_pack_member(display["id"], pack_member_payload(hero["id"], 2), CM), 201
    )
    multipack_line = validate_success(
        api_client.add_pack_member(multipack["id"], pack_member_payload(hero["id"], 2), CM), 201
    )

    assert display_line["line_extended_cents"] == 6600
    assert multipack_line["line_extended_cents"] == 5808


def test_each_line_is_priced_from_its_own_sku_and_quantity_at_append_time():
    """Three sockets at 1500 cents take the same 0.88 concession to 3960, and the
    two lines refresh the multipack's subtotal and member count.

    PRD §3.6: "Each accepted line stores `line_extended_cents`, the SKU's
    `list_price_cents` multiplied by the line's `quantity` multiplied by the
    pack-type discount, rounded half up to a whole number of cents."

    Design: Corner/calculations/pack_member_line_extension_applies_pack_type_discount
    """
    hero, partner, display, multipack = _two_packs_on_the_same_hero_sku()

    validate_success(
        api_client.add_pack_member(display["id"], pack_member_payload(hero["id"], 2), CM), 201
    )
    validate_success(
        api_client.add_pack_member(multipack["id"], pack_member_payload(hero["id"], 2), CM), 201
    )
    second_line = validate_success(
        api_client.add_pack_member(multipack["id"], pack_member_payload(partner["id"], 3), CM), 201
    )

    assert second_line["line_extended_cents"] == 3960

    priced = read_pack(multipack["id"])
    assert priced["status"] == "DRAFT"
    assert priced["distinct_member_count"] == 2
    assert priced["member_subtotal_cents"] == 9768
    assert priced["security_surcharge_cents"] == 0
    assert priced["pack_total_cents"] == 0

    assert read_pack(display["id"])["distinct_member_count"] == 1
