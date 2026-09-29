"""Engineered-to-order review, the quote waterfall, documentation scoring and money.

Four things here are order-of-evaluation questions rather than arithmetic questions:
how many clarification rounds the review loop allows, whether the volume tier is read
off the pre-discount amount or the grand total, whether each documentation fraction is
rounded before or after the weighted sum, and which retention share a cancellation
takes.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    DocPackageStatus,
    ErrorId,
    ModelStatus,
    OrderStatus,
    assert_money_conservation,
    assert_percentage,
    factories,
    fixtures,
    make_product_engineer_headers,
    make_quality_manager_headers,
)


# ─── The bounded clarification loop ───


def _order_under_clarification_pressure(api):
    """A multi-turn class-600 control-valve programme taken through all three
    clarification rounds, each one answered with a fresh datasheet revision."""
    model = fixtures.create_model(
        api,
        model_code="CV-600-F316",
        valve_type="CONTROL",
        pressure_class=600,
        body_material_grade="F316",
        bore_size_mm=200,
        seat_type="METAL",
        base_break_torque_nm=900.0,
    )
    order = fixtures.create_order(
        api,
        model["id"],
        order_code="ETO-LOOP",
        ordered_qty=2,
        unit_price_cents=800_000,
        customer_credit_limit_cents=9_000_000,
        datasheet_break_torque_nm=900.0,
        datasheet_torque_source="CUSTOMER_STATED",
    )
    fixtures.review_action(api, order["id"], "SUBMIT_REVIEW")
    for revised_torque in (910.0, 920.0, 930.0):
        clarification = fixtures.review_action(api, order["id"], "REQUEST_CLARIFICATION")
        fixtures.append_datasheet_revision(
            api,
            order["id"],
            revised_torque,
            "VENDOR_MEASURED",
            clarification["version"],
        )
    return {"model": model, "order": order}


def test_01_a_fourth_clarification_request_is_refused_once_three_rounds_are_spent(api):
    """The review loop is bounded: three rounds are allowed and the fourth request is
    refused, leaving the order under review to be approved or rejected.

    PRD §3.8: "A `QualityManager` may then request clarification, moving `UNDER_REVIEW →
    CLARIFICATION_REQUESTED` and incrementing `clarification_round_count` by 1; this is
    permitted only while that counter is still below 3, so a fourth request is refused
    with `ERR_CLARIFICATION_ROUNDS_EXHAUSTED` and the order must be approved or rejected
    instead."

    Design: Difficulty/non_linear_state_machine/engineered_order_clarification_loop_terminates_at_three_rounds
    """
    scenario = _order_under_clarification_pressure(api)

    response = api.engineered_order_review_action(
        scenario["order"]["id"],
        factories.review_action_payload("REQUEST_CLARIFICATION"),
        make_quality_manager_headers(),
    )

    validate_error(response, ErrorId.CLARIFICATION_ROUNDS_EXHAUSTED, 409)
    order = fixtures.read_order(api, scenario["order"]["id"])
    assert order["status"] == OrderStatus.UNDER_REVIEW
    assert order["clarification_round_count"] == 3


def test_02_each_answered_clarification_supersedes_the_datasheet_and_returns_to_review(api):
    """Three answered rounds leave the datasheet on its fourth revision, carrying the
    latest figures, with the order back under review.

    PRD §3.8: "The `ProductEngineer` answers a clarification by appending a datasheet
    revision that carries a new `datasheet_break_torque_nm` and `datasheet_torque_source`
    together with `expected_engineered_order_version`; a successful revision increments
    `datasheet_revision_no` by 1, replaces the datasheet fields, increments the order's
    `version` by 1, and moves `CLARIFICATION_REQUESTED → UNDER_REVIEW`."

    Design: Difficulty/non_linear_state_machine/engineered_order_clarification_loop_terminates_at_three_rounds
    """
    scenario = _order_under_clarification_pressure(api)

    order = fixtures.read_order(api, scenario["order"]["id"])

    assert order["datasheet_revision_no"] == 4, (
        "One initial datasheet plus three answered rounds is revision 4"
    )
    assert float(order["datasheet_break_torque_nm"]) == 930.0
    assert order["datasheet_torque_source"] == "VENDOR_MEASURED"
    assert order["status"] == OrderStatus.UNDER_REVIEW
    assert order["clarification_round_count"] == 3


# ─── The quote waterfall at approval ───


def _special_service_programme(api):
    """A fire-safe and cryogenic class-300 ball design, type-tested on a prototype so the
    services are evidenced, carrying an expedited four-valve programme ready to approve."""
    line = fixtures.build_traceable_line(
        api,
        foundry_code="FDY-03",
        foundry_name="Gamma Castings",
        country_code="IN",
        heat_number="H-3001",
        mtr_document_ref="MTR-3001",
        model_code="BV-300-SS",
        required_special_services=["FIRE_SAFE", "CRYOGENIC"],
        release_design=False,
        license_code="MON-03",
        scope_valve_types=["BALL"],
        grant_license=False,
    )
    fixtures.submit_model_for_review(api, line["model"]["id"])
    prototype = fixtures.open_unit(
        api,
        line["model"]["id"],
        line["component"]["id"],
        line["license"]["id"],
        serial_number="SN-PROTO",
        special_services=["FIRE_SAFE", "CRYOGENIC"],
    )
    fixtures.advance_to_assembled(api, prototype["id"])
    fixtures.record_test(
        api,
        prototype["id"],
        "SHELL",
        test_bench_code="BENCH-1",
        started_at="2026-08-01T08:00:00Z",
        ended_at="2026-08-01T09:00:00Z",
        test_pressure_bar=80.0,
        hold_seconds=60,
    )
    fixtures.record_test(
        api,
        prototype["id"],
        "SEAT",
        test_bench_code="BENCH-1",
        started_at="2026-08-01T09:00:00Z",
        ended_at="2026-08-01T10:00:00Z",
        test_pressure_bar=60.0,
        hold_seconds=60,
    )
    fixtures.record_test(
        api,
        prototype["id"],
        "FIRE_SAFE",
        test_bench_code="BENCH-2",
        started_at="2026-08-01T08:00:00Z",
        ended_at="2026-08-01T09:00:00Z",
        test_pressure_bar=60.0,
        hold_seconds=60,
    )
    fixtures.record_test(
        api,
        prototype["id"],
        "CRYOGENIC",
        test_bench_code="BENCH-2",
        started_at="2026-08-01T09:00:00Z",
        ended_at="2026-08-01T10:00:00Z",
        test_pressure_bar=60.0,
        hold_seconds=60,
    )
    model = fixtures.model_action(api, line["model"]["id"], "RELEASE")
    order = fixtures.create_order(
        api,
        model["id"],
        order_code="ETO-7",
        ordered_qty=4,
        unit_price_cents=1_250_000,
        customer_credit_limit_cents=9_000_000,
        datasheet_break_torque_nm=420.0,
        datasheet_torque_source="VENDOR_MEASURED",
        requested_special_services=["FIRE_SAFE", "CRYOGENIC"],
        expedite_requested=True,
    )
    fixtures.review_action(api, order["id"], "SUBMIT_REVIEW")
    return {"line": line, "model": model, "prototype": prototype, "order": order}


def test_03_the_volume_tier_is_keyed_on_the_pre_discount_amount_not_the_grand_total(api):
    """Four valves at 1,250,000 with two service surcharges and expedite quote at
    6,180,840 — the 0.03 tier on 5,900,000, not the 0.06 tier the total would suggest.

    PRD §3.8: "Tiering on the grand total instead of the pre-discount amount, or charging
    the expedite fee before the discount, both give a different gross — for example, an
    order of 4 valves at 1,250,000 cents each requesting fire-safe and cryogenic service
    with expedite bought quotes at 6,180,840 cents, having taken the 0.03 tier on a
    5,900,000 pre-discount amount rather than the 0.06 tier the 6,180,840 grand total
    would have crossed."

    Design: Difficulty/combinatorial_formula/eto_price_pinned_step_order_discount_tier_before_expedite
    """
    scenario = _special_service_programme(api)

    order = fixtures.review_action(api, scenario["order"]["id"], "APPROVE")

    assert order["status"] == OrderStatus.APPROVED
    assert order["gross_quoted_cents"] == 6_180_840, (
        "The pre-discount 5,900,000 takes the 0.03 tier, and expedite is charged after it"
    )


def test_04_approval_pins_the_specification_and_freezes_the_quote(api):
    """Approval captures the design revision it priced against and sets the billable
    amount to the frozen gross with nothing credited.

    PRD §3.8: "`pinned_model_id` is set to `model_id` and `pinned_model_spec_revision`
    captures the design's `spec_revision` as it stands at that moment." PRD §3.8:
    "Approval sets `net_billable_cents` equal to `gross_quoted_cents` and
    `credit_issued_cents` to 0."

    Design: Difficulty/combinatorial_formula/eto_price_pinned_step_order_discount_tier_before_expedite
    """
    scenario = _special_service_programme(api)

    order = fixtures.review_action(api, scenario["order"]["id"], "APPROVE")

    assert order["pinned_model_id"] == scenario["model"]["id"]
    assert order["pinned_model_spec_revision"] == 1
    assert order["spec_stale"] is False
    assert order["net_billable_cents"] == order["gross_quoted_cents"] == 6_180_840
    assert order["credit_issued_cents"] == 0
    assert_money_conservation(order)


# ─── Documentation completeness and its two-stage rounding ───


def _seven_valve_documentation_order(api):
    """A seven-valve gate programme with no approved actuator package, holding one
    material test report and one dimensional report."""
    model = fixtures.create_model(
        api,
        model_code="GV-150-WCB",
        valve_type="GATE",
        pressure_class=150,
        body_material_grade="WCB",
        bore_size_mm=80,
        seat_type="METAL",
        base_break_torque_nm=300.0,
    )
    order = fixtures.create_order(
        api,
        model["id"],
        order_code="ETO-DOC",
        ordered_qty=7,
        unit_price_cents=400_000,
        customer_credit_limit_cents=9_000_000,
        datasheet_break_torque_nm=300.0,
        datasheet_torque_source="VENDOR_MEASURED",
    )
    fixtures.append_document(api, order["id"], "MATERIAL_TEST_REPORT", "DOC-MTR-1")
    fixtures.append_document(api, order["id"], "DIMENSIONAL_REPORT", "DOC-DIM-1")
    return {"model": model, "order": order}


def test_05_each_category_fraction_is_rounded_before_the_weighted_sum_is_taken(api):
    """One of seven material test reports earns a rounded 0.14, so the package scores
    43.50 rather than the 43.57 the unrounded arithmetic gives.

    PRD §3.8: "For each category, the fraction earned is 1.00 outright when the required
    count is zero; otherwise it is the smaller of the present count and the required
    count, divided by the required count". PRD §3.8: "An order for 7 valves with no
    approved actuator package holding one material test report, one dimensional report and
    one non-destructive-examination report scores 43.50, not the 43.57 the unrounded
    arithmetic would give."

    Design: Difficulty/combinatorial_formula/documentation_completeness_pinned_two_stage_rounding
    """
    scenario = _seven_valve_documentation_order(api)

    order = fixtures.append_document(api, scenario["order"]["id"], "NDE_REPORT", "DOC-NDE-1")

    assert_percentage(order["documentation_completeness_pct"], 43.50, "documentation_completeness_pct")
    assert float(order["documentation_completeness_pct"]) != 43.57, (
        "43.57 would mean the fractions were summed before being rounded"
    )
    assert order["doc_package_status"] == DocPackageStatus.ASSEMBLING


def test_06_the_score_is_recomputed_on_every_appended_entry(api):
    """Two documents score 28.50 and the third lifts it to 43.50, with the package still
    assembling because it has not reached exactly 100.00.

    PRD §3.8: "The two-stage rounding order is pinned: rounding each fraction first and
    summing afterwards is not the same as summing the unrounded fractions and rounding
    once." PRD §3.8: "The package moves `ASSEMBLING → COMPLETE` automatically at the
    moment an appended entry brings `documentation_completeness_pct` to exactly 100.00."

    Design: Difficulty/combinatorial_formula/documentation_completeness_pinned_two_stage_rounding
    """
    scenario = _seven_valve_documentation_order(api)

    before = fixtures.read_order(api, scenario["order"]["id"])
    assert_percentage(
        before["documentation_completeness_pct"], 28.50, "score before the third document"
    )
    assert before["doc_package_status"] == DocPackageStatus.ASSEMBLING

    after = fixtures.append_document(api, scenario["order"]["id"], "NDE_REPORT", "DOC-NDE-1")

    assert_percentage(
        after["documentation_completeness_pct"], 43.50, "score after the third document"
    )
    assert len(after["documents"]) == 3
    assert after["doc_package_status"] == DocPackageStatus.ASSEMBLING


# ─── Cancellation: money is conserved through a credit note ───


def _expedited_order_in_production(api):
    """Four valves at 1,500,000 with expedite, approved at a gross of 6,091,200 and
    released to production."""
    model = fixtures.create_released_model(
        api,
        model_code="BV-300-MONEY",
        valve_type="BALL",
        pressure_class=300,
        body_material_grade="CF8M",
        bore_size_mm=100,
        seat_type="METAL",
        base_break_torque_nm=420.0,
    )
    order = fixtures.create_order(
        api,
        model["id"],
        order_code="ETO-MONEY",
        ordered_qty=4,
        unit_price_cents=1_500_000,
        customer_credit_limit_cents=7_000_000,
        datasheet_break_torque_nm=420.0,
        datasheet_torque_source="VENDOR_MEASURED",
        expedite_requested=True,
    )
    fixtures.approve_order(api, order["id"])
    fixtures.release_order_to_production(api, order["id"])
    return {"model": model, "order": order}


def test_07_cancellation_from_production_retains_thirty_five_hundredths(api):
    """The retention share is read off the status held at cancellation, so a programme
    cancelled out of production retains 0.35 and not the 0.10 of an approved order.

    PRD §3.8: "a cancellation from `APPROVED` retains one tenth of `gross_quoted_cents`,
    while a cancellation from either `IN_PRODUCTION` or `HELD` retains thirty-five
    hundredths of it."

    Design: Difficulty/compensating_invariant/order_cancellation_conserves_money_via_credit_note
    """
    scenario = _expedited_order_in_production(api)

    order = fixtures.lifecycle_action(api, scenario["order"]["id"], "CANCEL")

    assert order["status"] == OrderStatus.CANCELLED
    assert order["net_billable_cents"] == 2_131_920
    assert order["net_billable_cents"] != 609_120, (
        "609,120 would be the one-tenth share retained on cancelling an approved order"
    )


def test_08_the_credit_note_adds_back_to_the_frozen_gross_exactly(api):
    """Cancellation never touches the gross, and the retained share plus the credit note
    reconstruct it to the cent.

    PRD §3.8: "`net_billable_cents` becomes that retained share, rounded half up to whole
    cents, and `credit_issued_cents` becomes `gross_quoted_cents` less
    `net_billable_cents`, so the identity that the gross quote equals the net billable
    amount plus the credit issued holds before and after."

    Design: Difficulty/compensating_invariant/order_cancellation_conserves_money_via_credit_note
    """
    scenario = _expedited_order_in_production(api)
    before = fixtures.read_order(api, scenario["order"]["id"])
    assert_money_conservation(before)

    order = fixtures.lifecycle_action(api, scenario["order"]["id"], "CANCEL")

    assert order["gross_quoted_cents"] == before["gross_quoted_cents"] == 6_091_200
    assert order["credit_issued_cents"] == 3_959_280
    assert_money_conservation(order)


# ─── Release to production against a withdrawn pinned design ───


def _order_pinned_to_a_withdrawn_design(api):
    """An approved four-valve programme whose pinned design has since been withdrawn."""
    model = fixtures.create_released_model(
        api,
        model_code="BV-300-WD",
        valve_type="BALL",
        pressure_class=300,
        body_material_grade="CF8M",
        bore_size_mm=100,
        seat_type="METAL",
        base_break_torque_nm=420.0,
    )
    order = fixtures.create_order(
        api,
        model["id"],
        order_code="ETO-WD",
        ordered_qty=4,
        unit_price_cents=500_000,
        customer_credit_limit_cents=5_000_000,
        datasheet_break_torque_nm=420.0,
        datasheet_torque_source="VENDOR_MEASURED",
    )
    fixtures.approve_order(api, order["id"])
    fixtures.model_action(api, model["id"], "WITHDRAW")
    return {"model": model, "order": order}


def test_09_withdrawing_the_pinned_design_makes_the_order_stale(api):
    """The pinned revision is untouched; staleness comes from the design's new status.

    PRD §3.8: "From then on, `spec_stale` is derived and becomes true whenever
    `pinned_model_spec_revision` no longer equals the pinned design's current
    `spec_revision`, or the pinned design's status has moved to `SUPERSEDED` or
    `WITHDRAWN`." PRD §3.1: "On withdrawal, every engineered order pinned to the design
    recomputes `spec_stale` to true."

    Design: Difficulty/cross_entity_state_dependency/production_release_blocked_by_withdrawn_pinned_model
    """
    scenario = _order_pinned_to_a_withdrawn_design(api)

    model = fixtures.read_model(api, scenario["model"]["id"])
    order = fixtures.read_order(api, scenario["order"]["id"])

    assert model["status"] == ModelStatus.WITHDRAWN
    assert order["pinned_model_spec_revision"] == 1
    assert order["spec_stale"] is True
    assert order["status"] == OrderStatus.APPROVED


def test_10_release_to_production_is_refused_while_the_pinned_specification_is_stale(api):
    """The order is within its credit limit and correctly approved; the refusal is
    entirely about the design it pinned.

    PRD §3.8: "It requires `spec_stale` to be false, otherwise `ERR_PINNED_SPEC_STALE` —
    an order pinned to a revision the design has since moved past cannot be released until
    it is re-approved".

    Design: Difficulty/cross_entity_state_dependency/production_release_blocked_by_withdrawn_pinned_model
    """
    scenario = _order_pinned_to_a_withdrawn_design(api)

    response = api.engineered_order_lifecycle_action(
        scenario["order"]["id"],
        factories.lifecycle_action_payload("RELEASE_TO_PRODUCTION"),
        make_product_engineer_headers(),
    )

    validate_error(response, ErrorId.PINNED_SPEC_STALE, 409)
    order = fixtures.read_order(api, scenario["order"]["id"])
    assert order["status"] == OrderStatus.APPROVED
    assert order["spec_stale"] is True
