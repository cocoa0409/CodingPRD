"""Shipping and VOC compliance: the multi-input VOC computation, rule
resolution (state, wildcard, exemption, windows), and gate ordering."""

import test_helpers as fx
from test_helpers import ApiErrorId, validate_error, validate_success


def _setup_voc_matrix(api, extra_fills=()):
    """A 100-gal NONFLAT batch tinted to voc 154.57 g/L, QC approved, with
    two GALLON cans and one QUART can (plus any extra_fills, each a
    (size_code, grams) pair, recorded before filling completes); rules:
    national NONFLAT 250 open-ended, CA NONFLAT 100 (1.0 L exemption) through
    2027-06-01, CA NONFLAT 50 (1.0 L exemption) from 2027-06-01; AZ and CA
    customers with orders. The batch is left in FILLING when extra_fills is
    given, so callers can finish reconciliation themselves if needed."""
    fx.set_clock("2026-05-01T00:00:00Z")
    tb1, c1, f1, m1 = fx.setup_plant()
    fx.create_active_voc_rule(category="NONFLAT", state_code="*",
                              max_voc_gpl=250, effective_from="2026-01-01")
    fx.create_active_voc_rule(category="NONFLAT", state_code="CA",
                              max_voc_gpl=100, effective_from="2026-01-01",
                              effective_to="2027-06-01", exempt_container_l=1.0)
    fx.create_active_voc_rule(category="NONFLAT", state_code="CA",
                              max_voc_gpl=50, effective_from="2027-06-01",
                              exempt_container_l=1.0)
    cu_az = fx.create_customer(name="Sunbelt Paints AZ", home_state_code="AZ")
    cu_ca = fx.create_customer(name="Golden Gate Paint CA", home_state_code="CA")

    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=100)
    fx.start_batch(b1["id"])
    fx.record_adjustment(b1["id"], kind="THINNER", quantity=2000)
    fx.record_adjustment(b1["id"], kind="EXEMPT_SOLVENT", quantity=5000)
    fx.dispersion_pass(b1["id"], 18)
    fx.record_adjustment(b1["id"], kind="TINT_SHOT", quantity=50,
                         colorant_id=c1["id"])
    fx.submit_qc(b1["id"], 100)
    cm1 = fx.enter_measurement(b1["id"], 0.42)
    fx.approve_match(cm1["id"])

    fx.set_clock("2026-06-10T10:00:00Z")
    k_g1 = fx.fill_container(b1["id"], "GALLON", 4600)
    k_g2 = fx.fill_container(b1["id"], "GALLON", 4600)
    k_q = fx.fill_container(b1["id"], "QUART", 1150)
    extras = [fx.fill_container(b1["id"], size, grams)
              for size, grams in extra_fills]
    if not extras:
        fx.complete_filling(b1["id"], 97.75)

    o_az = validate_success(
        api.create_order(
            fx.create_order_payload(cu_az["id"], f1["id"]),
            fx.make_dealer_headers(cu_az["id"]),
        ),
        expected_status=201,
    )
    o_ca = validate_success(
        api.create_order(
            fx.create_order_payload(cu_ca["id"], f1["id"],
                                    destination_state_code="CA"),
            fx.make_dealer_headers(cu_ca["id"]),
        ),
        expected_status=201,
    )
    o_ca_q = validate_success(
        api.create_order(
            fx.create_order_payload(
                cu_ca["id"], f1["id"], destination_state_code="CA",
                lines=[{"formula_id": f1["id"], "gallons": 1,
                        "size_code": "QUART"}],
            ),
            fx.make_dealer_headers(cu_ca["id"]),
        ),
        expected_status=201,
    )
    fx.set_clock("2026-06-15T09:00:00Z")
    return {
        "b1": b1, "k_g1": k_g1, "k_g2": k_g2, "k_q": k_q, "extras": extras,
        "o_az": o_az, "o_ca": o_ca, "o_ca_q": o_ca_q,
    }


def test_voc_actual_nonlinear_multi_input_computation(api):
    """PRD §3.5: "The total VOC mass in grams is the tint base's
    `base_voc_gpl` multiplied by the batch volume in liters, plus the
    colorant VOC mass, plus the thinner VOC mass. The regulatory denominator
    is the batch volume in liters minus the water volume minus the
    exempt-solvent volume. Finally, `voc_actual_gpl` is the total VOC mass
    divided by that denominator, rounded half up to two decimal places."
    PRD §3.2: "the container ships only if the batch's `voc_actual_gpl` is
    less than or equal to that limit, with equality passing; exceeding it is
    `ERR_VOC_LIMIT_EXCEEDED`."

    Design: Difficulty/combinatorial_formula/voc_actual_nonlinear_multi_input
    """
    env = _setup_voc_matrix(api)

    # (80 * 378.541 + 450 * 5 + 2000 * 0.9) / (378.541 - 151.4164 - 5.0)
    batch = fx.read_batch(env["b1"]["id"])
    assert batch["voc_actual_gpl"] == 154.57
    assert batch["status"] == "FILLED"

    # GALLON (3.785 L, above the CA exemption) to CA: 154.57 > 100.
    refused = api.ship_container(env["k_g1"]["id"],
                                 {"order_id": env["o_ca"]["id"]},
                                 fx.PRODUCTION_OPERATOR)
    validate_error(refused, ApiErrorId.ERR_VOC_LIMIT_EXCEEDED.value, 422)
    assert fx.read_container(env["k_g1"]["id"])["status"] == "IN_STOCK", (
        "a failed shipment leaves the container state unchanged"
    )


def test_voc_exemption_and_wildcard_resolution(api):
    """PRD §3.2: "From that eligible set, any rule whose `exempt_container_l`
    is set and whose threshold is greater than or equal to the shipping
    container's `size_liters` is dropped as exempting this package."
    PRD §3.2: "Otherwise the applicable limit is the strictest — the minimum
    `max_voc_gpl` among the remaining rules — and the container ships only if
    the batch's `voc_actual_gpl` is less than or equal to that limit, with
    equality passing; exceeding it is `ERR_VOC_LIMIT_EXCEEDED`."

    Design: Difficulty/combinatorial_formula/voc_actual_nonlinear_multi_input
    """
    env = _setup_voc_matrix(api)
    assert fx.read_batch(env["b1"]["id"])["voc_actual_gpl"] == 154.57

    # QUART (0.946 L <= 1.0) to CA: both CA rules exempt this package, so the
    # wildcard national limit 250 governs and 154.57 passes.
    quart = validate_success(
        api.ship_container(env["k_q"]["id"], {"order_id": env["o_ca_q"]["id"]},
                           fx.PRODUCTION_OPERATOR)
    )
    assert quart["status"] == "SHIPPED"
    assert quart["destination_state_code"] == "CA"

    # GALLON to AZ: no state rule, wildcard 250 governs — 154.57 passes.
    gallon_az = validate_success(
        api.ship_container(env["k_g2"]["id"], {"order_id": env["o_az"]["id"]},
                           fx.PRODUCTION_OPERATOR)
    )
    assert gallon_az["status"] == "SHIPPED"
    assert gallon_az["destination_state_code"] == "AZ"


def _setup_primer_shipment(api, with_rule=False, activate_rule=True):
    """A PRIMER batch closed to FILLED with two GALLON cans, an AZ order, and
    optionally a PRIMER wildcard rule 250 (DRAFT or ACTIVE)."""
    fx.set_clock("2026-05-01T00:00:00Z")
    tb3 = fx.create_tb3()
    c1 = fx.create_c1()
    f3 = fx.create_f3(tb3["id"], c1["id"])
    fx.activate_formula(f3["id"])
    m1 = fx.create_mill()
    b1 = fx.plan_batch(f3["id"], m1["id"], planned_gallons=2)
    fx.start_batch(b1["id"])
    fx.dispersion_pass(b1["id"], 12)
    fx.submit_qc(b1["id"], 2)
    cm1 = fx.enter_measurement(b1["id"], 0.4)
    fx.approve_match(cm1["id"])
    fx.set_clock("2026-06-10T10:00:00Z")
    k1 = fx.fill_container(b1["id"], "GALLON", 4600)
    fx.fill_container(b1["id"], "GALLON", 4600)
    fx.complete_filling(b1["id"], 0)
    cu1 = fx.create_customer(name="Sunbelt Paints AZ")
    o1 = validate_success(
        api.create_order(
            fx.create_order_payload(
                cu1["id"], f3["id"],
                lines=[{"formula_id": f3["id"], "gallons": 2,
                        "size_code": "GALLON"}],
            ),
            fx.make_dealer_headers(cu1["id"]),
        ),
        expected_status=201,
    )
    vr = None
    if with_rule:
        vr = validate_success(
            api.create_voc_rule(
                fx.create_voc_rule_payload(category="PRIMER", state_code="*",
                                           max_voc_gpl=250,
                                           effective_from="2026-01-01"),
                fx.REGULATORY_CLERK,
            ),
            expected_status=201,
        )
        if activate_rule:
            vr = validate_success(
                api.activate_voc_rule(vr["id"], fx.REGULATORY_CLERK)
            )
    fx.set_clock("2026-06-15T09:00:00Z")
    return {"k1": k1, "o1": o1, "vr": vr, "b1": b1}


def test_ship_requires_resolvable_voc_rule(api):
    """PRD §3.2: "If the eligible set was empty before any exemption
    filtering, shipment is rejected with `ERR_VOC_RULE_MISSING` — no law on
    the books means no shipment."

    Design: Difficulty/cross_entity_state_dependency/ship_requires_resolvable_voc_rule
    """
    env = _setup_primer_shipment(api, with_rule=False)

    refused = api.ship_container(env["k1"]["id"], {"order_id": env["o1"]["id"]},
                                 fx.PRODUCTION_OPERATOR)
    validate_error(refused, ApiErrorId.ERR_VOC_RULE_MISSING.value, 422)
    assert fx.read_container(env["k1"]["id"])["status"] == "IN_STOCK"


def test_ship_succeeds_once_covering_rule_activated(api):
    """PRD §3.2: "The eligible set is every `ACTIVE` rule whose `category`
    equals the batch's snapshotted `product_category`, whose `state_code` is
    either the order's `destination_state_code` or the wildcard `*`, and
    whose window contains the ship date — the logical clock's calendar date
    on the day of shipment, on or after `effective_from` and strictly before
    `effective_to` when that bound exists."
    PRD §3.8: "A successful shipment moves the container to `SHIPPED`, copies
    the order reference into the container's `order_id`, copies the order's
    destination into the container's `destination_state_code`, stamps
    `shipped_at` from the logical clock, and re-runs the fulfillment
    bubble-up of §3.3."

    Design: Difficulty/cross_entity_state_dependency/ship_requires_resolvable_voc_rule
    """
    env = _setup_primer_shipment(api, with_rule=False)

    refused = api.ship_container(env["k1"]["id"], {"order_id": env["o1"]["id"]},
                                 fx.PRODUCTION_OPERATOR)
    validate_error(refused, ApiErrorId.ERR_VOC_RULE_MISSING.value, 422)

    # Activate a covering wildcard PRIMER rule; the identical ship succeeds.
    vr = fx.create_active_voc_rule(category="PRIMER", state_code="*",
                                   max_voc_gpl=250, effective_from="2026-01-01")
    assert vr["status"] == "ACTIVE"
    shipped = validate_success(
        api.ship_container(env["k1"]["id"], {"order_id": env["o1"]["id"]},
                           fx.PRODUCTION_OPERATOR)
    )
    assert shipped["status"] == "SHIPPED"
    assert shipped["order_id"] == env["o1"]["id"]
    assert shipped["destination_state_code"] == "AZ"
    assert shipped["shipped_at"].startswith("2026-06-15T09:00:00")


def test_voc_rule_resolution_excludes_draft_rules(api):
    """PRD §3.2: "A rule is born `DRAFT` and binds nothing until activated."
    PRD §3.2: "If the eligible set was empty before any exemption filtering,
    shipment is rejected with `ERR_VOC_RULE_MISSING` — no law on the books
    means no shipment."

    Design: Corner/calculations/voc_rule_resolution_excludes_draft_rules
    """
    env = _setup_primer_shipment(api, with_rule=True, activate_rule=False)
    assert env["vr"]["status"] == "DRAFT"

    # The covering rule exists but is DRAFT: it does not enter resolution.
    refused = api.ship_container(env["k1"]["id"], {"order_id": env["o1"]["id"]},
                                 fx.PRODUCTION_OPERATOR)
    validate_error(refused, ApiErrorId.ERR_VOC_RULE_MISSING.value, 422)

    validate_success(api.activate_voc_rule(env["vr"]["id"], fx.REGULATORY_CLERK))
    shipped = validate_success(
        api.ship_container(env["k1"]["id"], {"order_id": env["o1"]["id"]},
                           fx.PRODUCTION_OPERATOR)
    )
    assert shipped["status"] == "SHIPPED"


def test_ship_state_gate_masks_voc_safety_gate(api):
    """PRD §2.9: "Every request passes through eleven ordered gates, and a
    failure at an earlier gate masks every later check — the error returned
    is always the first failing gate's error."
    PRD §2.9: "Gate six is state permission: the target resource must be in a
    state that permits the operation — this is the gate that catches
    stale-cycle color measurements, cancellation of an order already in
    production, completion of a hazardous disposal that never passed through
    its manifest, and adjustments recorded in the wrong batch phase, all as
    `ERR_INVALID_STATE`."
    PRD §2.9: "Gate seven, on container shipment only, is VOC compliance —
    `ERR_VOC_RULE_MISSING` or `ERR_VOC_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/ship_state_beats_safety
    """
    env = _setup_voc_matrix(api, extra_fills=[("GALLON", 4530)])
    # Condemn the underweight can: born QUARANTINED, then marked REJECTED.
    condemned = env["extras"][0]
    assert condemned["status"] == "QUARANTINED"
    rejected = validate_success(
        api.reweigh_container(condemned["id"],
                              {"actual_fill_g": 4530, "mark_rejected": True},
                              fx.QC_INSPECTOR)
    )
    assert rejected["status"] == "REJECTED"

    # Both violations are present: state (REJECTED can) and safety
    # (batch voc 154.57 > CA limit 100). The state gate fires first.
    assert fx.read_batch(env["b1"]["id"])["voc_actual_gpl"] == 154.57
    response = api.ship_container(rejected["id"],
                                  {"order_id": env["o_ca"]["id"]},
                                  fx.PRODUCTION_OPERATOR)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert fx.read_container(rejected["id"])["status"] == "REJECTED"


def test_ship_state_gate_fires_for_quarantined_container_too(api):
    """PRD §3.8: "A `ProductionOperator` ships an `IN_STOCK` container against
    an order by naming the `order_id`. The order must exist
    (`ERR_NOT_FOUND`), must be `PLACED`, `SCHEDULED`, or `IN_PRODUCTION` —
    shipping against an order in any other state is `ERR_INVALID_STATE` — and
    the shipment must clear the VOC gate of §3.2"
    PRD §2.9: "a failure at an earlier gate masks every later check — the
    error returned is always the first failing gate's error."

    Design: Difficulty/priority_pair_validation_conflict/ship_state_beats_safety
    """
    env = _setup_voc_matrix(api, extra_fills=[("GALLON", 4530)])
    quarantined = env["extras"][0]
    assert quarantined["status"] == "QUARANTINED"
    assert fx.read_batch(env["b1"]["id"])["voc_actual_gpl"] == 154.57

    # State violation (QUARANTINED is not IN_STOCK) with the CA safety
    # violation also present: the earlier state gate answers.
    response = api.ship_container(quarantined["id"],
                                  {"order_id": env["o_ca"]["id"]},
                                  fx.PRODUCTION_OPERATOR)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert fx.read_container(quarantined["id"])["status"] == "QUARANTINED"
