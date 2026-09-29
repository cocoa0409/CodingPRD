"""Corner validations: requests that break two rules at once, and which rule answers.

PRD.md section 2.7 is the source of every ordering claim in this module: "Each endpoint
evaluates its applicable checks in a fixed ascending priority order and returns on the
first failure it finds; no endpoint reports two errors, and no later check runs after an
earlier one has failed."  Its ascending bands run from "**Authentication and
authorization**" through "**Existence**", "**Schema, range, enum and uniqueness**",
"**Resource and lifecycle state**", "**Product safety and process compliance** — regrind
ceiling, lot qualification, melt-index band, charge-mass tolerance, cooling-time floor,
cooling-mode agreement, size-class capability, and storage-guidance acknowledgement",
"**Referential agreement and temporal constraints**", "**Capacity, quota and money** —
mould eligibility and occupancy, cooling-bay slots, resin sufficiency, zone and site cube,
build-ahead quota, trailer cube and payload, order overbuild, and warranty reserve
sufficiency", to "**Optimistic concurrency** — the five stale-version guards of section
2.6, last of all".

The same section then names the precedences that are easiest to invert: "When a hull is
stored into a site whose posture is frozen *and* its demand bucket is already at its
build-ahead cap, the frozen-site failure wins. When a claim is approved for a suspended
customer *and* the payout would exceed the model's remaining reserve, the
suspended-customer failure wins."

Every test here drives one request that genuinely violates both rules, then drives a
second request that violates only the lower-ranked one, so the loser's rule is proved to
have been live rather than merely unimplemented.
"""

from test_helpers import (
    DEFAULT_ZONE_CODE,
    ApiErrorId,
    Q_CUBE,
    Q_MASS,
    Q_PERCENT,
    advance_unit_to_outfitted,
    approve_claim_payload,
    assert_decimal_equals,
    assert_footprint_summary_consistent,
    assert_resin_ledger_conserved,
    assert_warranty_reserve_conserved,
    create_plant_baseline,
    create_resin_lot,
    inspect_payload,
    product_model_version,
    resin_charge_payload,
    resin_lot_version,
    set_clock,
    setup_build_ahead_bucket,
    setup_scheduled_cycle,
    setup_sellable_units,
    setup_submitted_claim,
    storage_review_payload,
    store_payload,
    store_unit,
    suspend_payload,
    validate_error,
    validate_paginated,
    validate_success,
    warehouse_payload,
    warehouse_version,
    warranty_claim_payload,
    zone,
)


def test_resin_lot_not_qualified_outranks_resin_insufficient_on_the_same_charge(api):
    """A charge from an unqualified, nearly empty lot reports the qualification failure.

    PRD.md section 3.2 declares both rules for `POST /resin-charges`: "the lot must
    qualify for the cycle's hull model, otherwise `ERR_RESIN_LOT_NOT_QUALIFIED`
    (HTTP 422)", and separately "the lot's `available_kg` must be at least `charge_kg`,
    equality being legal and draining the lot to exactly 0.000, otherwise
    `ERR_RESIN_INSUFFICIENT` (HTTP 409)".

    PRD.md section 2.7 ranks them: qualification sits in band 5, "**Product safety and
    process compliance** — regrind ceiling, lot qualification, melt-index band,
    charge-mass tolerance, cooling-time floor, cooling-mode agreement, size-class
    capability, and storage-guidance acknowledgement", while sufficiency sits in band 7,
    "**Capacity, quota and money** — mould eligibility and occupancy, cooling-bay slots,
    resin sufficiency, zone and site cube, build-ahead quota, trailer cube and payload,
    order overbuild, and warranty reserve sufficiency".  The lower band answers.

    The two single-defect controls that follow prove both rules are live: an unqualified
    lot holding far more mass than the charge still fails on qualification, and a fully
    qualified lot holding too little still fails on sufficiency, with a different error
    id *and* a different HTTP status.

    Design: Corner/validations/val_priority_ordering_resin_lot_not_qualified_beats_resin_insufficient
    """
    # The lot the order was released against is qualified and holds exactly the charge.
    ctx = setup_scheduled_cycle(charge=False, lot_overrides={"received_kg": 20.0})
    cycle_id = ctx["molding_cycle_id"]
    tech_headers = ctx["resin_tech_headers"]
    admin_headers = ctx["admin_headers"]
    qualified_exact = ctx["resin_lot"]

    # MDPE against an HDPE_LINEAR model: unqualified, and far short of the 20.000 kg ask.
    unqualified_thin = create_resin_lot(resin_grade="MDPE", received_kg=5.0)
    # The same grade mismatch with ample mass: qualification alone.
    unqualified_rich = create_resin_lot(resin_grade="MDPE", received_kg=100.0)
    # Qualified but short of the 20.000 kg ask. PRD.md section 3.2 folds a mass
    # floor into qualification itself — "the lot's `available_kg` is at least the
    # model's minimum shot mass, computed as `nominal_charge_kg` multiplied by
    # one minus `charge_tolerance_pct` divided by 100" — so this lot must clear
    # 12.0 * 0.95 = 11.400 kg to reach band 7 at all.
    qualified_thin = create_resin_lot(received_kg=15.0)

    def charge_from(lot):
        return resin_charge_payload(
            cycle_id, lot["id"], resin_lot_version(lot["id"]), charge_kg=20.0, regrind_kg=2.0
        )

    # Both rules violated by one request: band 5 owns the response.
    both = api.create_resin_charge(charge_from(unqualified_thin), tech_headers)
    validate_error(both, ApiErrorId.RESIN_LOT_NOT_QUALIFIED, 422)

    # Qualification alone, with 100.000 kg on hand.
    qualification_only = api.create_resin_charge(charge_from(unqualified_rich), tech_headers)
    validate_error(qualification_only, ApiErrorId.RESIN_LOT_NOT_QUALIFIED, 422)

    # Sufficiency alone: this is the proof that band 7 was genuinely violated above.
    sufficiency_only = api.create_resin_charge(charge_from(qualified_thin), tech_headers)
    validate_error(sufficiency_only, ApiErrorId.RESIN_INSUFFICIENT, 409)

    # The equality case of the sufficiency rule: 20.000 against exactly 20.000 available.
    accepted = validate_success(
        api.create_resin_charge(charge_from(qualified_exact), tech_headers), 201
    )
    assert accepted["status"] == "RESERVED"

    drained = api.read_entity("get_resin_lot", qualified_exact["id"], admin_headers)
    assert_decimal_equals(drained["available_kg"], 0.0, Q_MASS, "available_kg")
    assert_decimal_equals(drained["reserved_kg"], 20.0, Q_MASS, "reserved_kg")
    assert_decimal_equals(drained["consumed_kg"], 0.0, Q_MASS, "consumed_kg")
    assert_resin_ledger_conserved(drained)
    # PRD.md section 3.2: "a lot whose `available_kg` reaches exactly 0.000 moves
    # `AVAILABLE` to `DEPLETED`".
    assert drained["status"] == "DEPLETED"

    # PRD.md section 3.2: "A refused charge writes nothing: no row, no mass movement, no
    # version increment."
    for lot, expected_available in (
        (unqualified_thin, 5.0),
        (unqualified_rich, 100.0),
        (qualified_thin, 15.0),
    ):
        untouched = api.read_entity("get_resin_lot", lot["id"], admin_headers)
        assert_decimal_equals(
            untouched["available_kg"], expected_available, Q_MASS, "available_kg"
        )
        assert_decimal_equals(untouched["reserved_kg"], 0.0, Q_MASS, "reserved_kg")
        assert untouched["version"] == lot["version"]
        assert_resin_ledger_conserved(untouched)

    cycle = api.read_entity("get_molding_cycle", cycle_id, admin_headers)
    assert_decimal_equals(cycle["charged_mass_kg"], 20.0, Q_MASS, "charged_mass_kg")
    # The blended regrind share stays well inside the ceiling, so neither failure above
    # can be confused with ERR_REGRIND_LIMIT_EXCEEDED.
    assert_decimal_equals(cycle["cycle_regrind_pct"], 10.0, Q_PERCENT, "cycle_regrind_pct")

    _rows, meta = validate_paginated(
        api.list_resin_charges({"molding_cycle_id": cycle_id}, tech_headers)
    )
    assert meta["total_count"] == 1, "none of the three refused charges may leave a row"


def test_frozen_site_outranks_the_build_ahead_cap_and_the_zone_cube(api, planner_headers):
    """A store into a frozen, full site against an exhausted bucket reports the freeze.

    PRD.md section 3.7 states the ladder for `POST /finished-units/{id}/store` outright:
    "Four gates apply in priority order. First, the site's `posture` must not be
    `FROZEN`, otherwise `ERR_WAREHOUSE_FROZEN` (HTTP 409). Second, when the producing
    order names a `demand_bucket_id`, the logical clock's calendar date must lie inside
    that bucket's window from `window_start_on` through `window_end_on`, **both bounds
    inclusive**, otherwise `ERR_BUILD_AHEAD_WINDOW_MISMATCH` (HTTP 409) — and when the
    date is out of window the quota check is never reached at all. Third, an eligible
    zone must exist, otherwise `ERR_NO_ELIGIBLE_ZONE` (HTTP 409). Fourth, the bucket's
    quota and then the site's total cube must both hold. When the site is frozen *and*
    the bucket is already at its cap, the frozen-site failure is the one reported."

    PRD.md section 2.7 states the same precedence among its named pairs: "When a hull is
    stored into a site whose posture is frozen *and* its demand bucket is already at its
    build-ahead cap, the frozen-site failure wins."

    The site here is sized so that one anchored hull takes it to 95.24 percent, which
    PRD.md section 2.8 turns into a freeze — `frozen_threshold_pct` is "compared with
    at-or-above" — and simultaneously leaves the single zone 0.0500 m3 against a
    0.5000 m3 nested candidate, while PRD.md section 3.7's quota rule is already
    exhausted: "when `build_ahead_committed_qty` plus 1 exceeds `build_ahead_cap_qty` the
    store is refused with `ERR_BUILD_AHEAD_CAP_EXCEEDED` (HTTP 409)".  The second store,
    at a roomy NORMAL site charged to the very same bucket, isolates that quota rule.

    Design: Corner/validations/val_priority_conflict_pair3_warehouse_frozen_beats_build_ahead_cap_and_zone
    """
    tight_baseline = create_plant_baseline(
        model_overrides={"gross_cube_m3": 1.0, "unit_weight_kg": 30.0},
        warehouse_overrides={
            "footprint_capacity_cube_m3": 1.05,
            "zones": [zone("Z1", 1.05)],
        },
    )
    # The bucket caps at floor(2 * 60.00 / 100) == 1, and exactly one hull is stored.
    ctx = setup_build_ahead_bucket(
        baseline=tight_baseline, forecast_qty=2, build_ahead_cap_pct=60.0
    )
    tight_warehouse_id = ctx["warehouse_id"]

    frozen_site = api.read_entity("get_warehouse", tight_warehouse_id, planner_headers)
    assert_decimal_equals(frozen_site["committed_cube_m3"], 1.0, Q_CUBE, "committed_cube_m3")
    assert_decimal_equals(frozen_site["utilization_pct"], 95.24, Q_PERCENT, "utilization_pct")
    assert frozen_site["posture"] == "FROZEN"

    bucket = api.read_entity(
        "get_demand_forecast_bucket", ctx["demand_bucket_id"], planner_headers
    )
    assert bucket["build_ahead_cap_qty"] == 1
    assert bucket["build_ahead_committed_qty"] == 1

    # The second hull of the tight order: frozen site AND no zone room AND bucket at cap.
    second_hull = ctx["sellable_units"][1]
    version_before = warehouse_version(tight_warehouse_id)
    all_three = api.store_finished_unit(
        second_hull["id"], store_payload(version_before), planner_headers
    )
    frozen_error = validate_error(all_three, ApiErrorId.WAREHOUSE_FROZEN, 409)

    # A roomy NORMAL site, a second order on the same model charged to the same bucket:
    # gates one, two and three all pass, so the quota gate answers alone.
    roomy_baseline = dict(tight_baseline)
    roomy_warehouse = validate_success(
        api.create_warehouse(
            warehouse_payload(
                footprint_capacity_cube_m3=20.0, zones=[zone("Z1", 20.0)]
            ),
            planner_headers,
        ),
        201,
    )
    roomy_baseline["warehouse"] = roomy_warehouse
    roomy_baseline["warehouse_id"] = roomy_warehouse["id"]
    roomy_ctx = setup_sellable_units(
        baseline=roomy_baseline,
        order_overrides={"demand_bucket_id": ctx["demand_bucket_id"]},
        cycle_overrides={"oven_start_at": "2026-08-01T12:00:00Z"},
        actual_oven_start_at="2026-08-01T12:00:00Z",
        actual_oven_end_at="2026-08-01T13:00:00Z",
        actual_cooling_end_at="2026-08-01T13:35:00Z",
        unit_count=1,
    )
    assert roomy_warehouse["posture"] == "NORMAL"
    quota_only = api.store_finished_unit(
        roomy_ctx["sellable_units"][0]["id"],
        store_payload(warehouse_version(roomy_warehouse["id"])),
        planner_headers,
    )
    quota_error = validate_error(quota_only, ApiErrorId.BUILD_AHEAD_CAP_EXCEEDED, 409)

    # Both refusals are HTTP 409 with different ids, so a handler returning the
    # first-found 409 without ordering fails exactly one of the two calls.
    assert frozen_error["error_id"] != quota_error["error_id"]

    summary = api.read_footprint_summary(tight_warehouse_id, planner_headers)
    assert_footprint_summary_consistent(summary)
    tight_zone = {z["zone_code"]: z for z in summary["zones"]}["Z1"]
    assert_decimal_equals(tight_zone["committed_cube_m3"], 1.0, Q_CUBE, "zone committed")
    assert_decimal_equals(tight_zone["remaining_cube_m3"], 0.05, Q_CUBE, "zone remaining")
    assert tight_zone["stored_unit_count"] == 1
    assert ctx["product_model_id"] in tight_zone["anchor_product_model_ids"]

    # Nothing moved on the refused store.
    untouched = api.read_entity("get_finished_unit", second_hull["id"], planner_headers)
    assert untouched["logistics_status"] == "UNALLOCATED"
    assert untouched["warehouse_id"] is None
    assert untouched["storage_zone_code"] is None
    assert untouched["is_zone_anchor"] is False
    assert_decimal_equals(
        untouched["stored_footprint_cube_m3"], 0.0, Q_CUBE, "stored_footprint_cube_m3"
    )
    assert warehouse_version(tight_warehouse_id) == version_before


def test_unit_build_state_outranks_a_stale_warehouse_version_on_the_same_body(
    api, planner_headers
):
    """One store body, two answers: the build-state refusal first, the stale one after.

    PRD.md section 3.7 fixes what may be stored: "Storage is a `LogisticsPlanner`
    operation on a hull that is `build_status` `SELLABLE` and `logistics_status`
    `UNALLOCATED`."  An `OUTFITTED` hull is therefore refused, and PRD.md section 2.7
    places that refusal in band 4, "**Resource and lifecycle state** — the status of the
    target row and of every row the operation touches, including equipment up/down state,
    mould and lot disposition, order schedulability, cycle and claim transition legality,
    and the two independent finished-unit axes".

    The declared `expected_warehouse_version` in the very same body is provably stale,
    because the sibling hull's accepted store has already advanced the site.  PRD.md
    section 2.6 ranks that guard last: "These guards are evaluated late — after
    authorization, after existence, after schema, after every state and capacity rule the
    endpoint declares — so a request that is both stale and otherwise invalid reports the
    other failure, not the stale-version failure."  PRD.md section 2.7 agrees, ending its
    ladder with "**Optimistic concurrency** — the five stale-version guards of section
    2.6, last of all", and PRD.md section 2.6 names this one: "Storing a finished unit
    requires `expected_warehouse_version`, compared against the `version` of the
    destination `Warehouse`. A mismatch yields `ERR_STALE_WAREHOUSE_VERSION`."

    Replaying the byte-identical body once the hull is `SELLABLE` yields the 412, which
    proves the concurrency guard was violated all along and merely out-ranked.

    Design: Corner/validations/val_priority_ordering_unit_build_state_beats_stale_warehouse_version
    """
    ctx = setup_sellable_units(
        unit_count=1,
        model_overrides={"gross_cube_m3": 1.0},
        warehouse_overrides={
            "footprint_capacity_cube_m3": 100.0,
            "zones": [zone(DEFAULT_ZONE_CODE, 100.0)],
        },
    )
    warehouse_id = ctx["warehouse_id"]
    anchor_hull = ctx["sellable_units"][0]
    second_hull = ctx["finished_units"][1]

    # The second hull stops one step short of SELLABLE.
    advance_unit_to_outfitted(ctx, second_hull)
    before = api.read_entity("get_finished_unit", second_hull["id"], planner_headers)
    assert before["build_status"] == "OUTFITTED"
    assert before["logistics_status"] == "UNALLOCATED"
    assert before["inspection_verdict"] == "PENDING"

    # This version is captured before the sibling's store, so it goes stale immediately.
    stale_warehouse_version = warehouse_version(warehouse_id)
    store_unit(ctx, anchor_hull)
    assert warehouse_version(warehouse_id) == stale_warehouse_version + 1

    # Both defects at once: band 4 answers, not band 8.
    both = api.store_finished_unit(
        second_hull["id"], store_payload(stale_warehouse_version), planner_headers
    )
    validate_error(both, ApiErrorId.UNIT_INVALID_BUILD_STATE, 409)

    # Remove the build-state defect and nothing else.
    inspected = validate_success(
        api.inspect_finished_unit(
            second_hull["id"], inspect_payload(), ctx["inspector_headers"]
        )
    )
    assert inspected["build_status"] == "SELLABLE"
    assert inspected["inspection_verdict"] == "PASS"

    # The byte-identical body now surfaces the guard that was out-ranked.
    stale_only = api.store_finished_unit(
        second_hull["id"], store_payload(stale_warehouse_version), planner_headers
    )
    validate_error(stale_only, ApiErrorId.STALE_WAREHOUSE_VERSION, 412)

    # With a freshly read version the same hull stores and nests behind the anchor.
    stored = validate_success(
        api.store_finished_unit(
            second_hull["id"], store_payload(warehouse_version(warehouse_id)), planner_headers
        )
    )
    assert stored["logistics_status"] == "STORED"
    assert stored["storage_zone_code"] == DEFAULT_ZONE_CODE
    assert stored["is_zone_anchor"] is False
    assert_decimal_equals(
        stored["stored_footprint_cube_m3"], 0.5, Q_CUBE, "stored_footprint_cube_m3"
    )

    summary = api.read_footprint_summary(warehouse_id, planner_headers)
    assert_footprint_summary_consistent(summary)
    assert_decimal_equals(summary["committed_cube_m3"], 1.5, Q_CUBE, "committed_cube_m3")
    assert_decimal_equals(summary["remaining_cube_m3"], 98.5, Q_CUBE, "remaining_cube_m3")
    assert_decimal_equals(summary["utilization_pct"], 1.5, Q_PERCENT, "utilization_pct")
    assert summary["posture"] == "NORMAL"

    # The site's version moved exactly twice: once per accepted store, never on a refusal.
    assert warehouse_version(warehouse_id) == stale_warehouse_version + 2


def test_suspending_the_claimant_voids_the_claim_before_the_reserve_gate_can_speak(
    api, admin_headers, warranty_agent_headers
):
    """The suspended-customer rung is unreachable on approve, because suspension voids.

    PRD.md section 3.9 gives approve an explicit ordered list: "In order: the claim must
    be `UNDER_REVIEW` (`ERR_CLAIM_INVALID_STATE`); the storage axis must be
    `GUIDANCE_VERIFIED` or `WAIVED`, otherwise `ERR_STORAGE_REVIEW_INCOMPLETE`
    (HTTP 409) ...; the version check follows; the claimant must be `ACTIVE`
    (`ERR_CUSTOMER_NOT_ACTIVE`); the hull's `logistics_status` must be `DELIVERED` ...;
    the frozen `months_in_service` must be at or below the warranty term of 60 months
    ...; and finally the computed payout must fit the reserve."

    That list is what makes this a decidable ordering rather than a guess.  The reserve
    gate is dead last, so it answers a claim that is otherwise impeccable — asserted here
    first, in isolation.  The claimant is then suspended, and PRD.md section 2.14 states
    the cascade: "the suspension voids that customer's open warranty claims, moving every
    claim in `claim_status` `SUBMITTED` or `UNDER_REVIEW` to `VOIDED` with `denial_reason`
    `APPROVAL_VOIDED`. No money moves on those voids, because no payout had been booked."
    The retried approve therefore violates the `ACTIVE` rung and the reserve rung at once,
    yet answers with neither: the very act that made the customer inactive also moved the
    claim out of `UNDER_REVIEW`, and that rung stands above both.

    PRD.md section 2.14 also fixes the closing state: reinstatement "does *not* resurrect
    a voided claim", while a fresh claim from the reinstated customer is accepted.

    Design: Corner/validations/val_priority_conflict_pair4_customer_suspension_voids_the_claim_before_the_reserve_gate
    """
    delivered_at = "2026-08-01T18:00:00Z"
    ctx = setup_submitted_claim(
        model_overrides={"msrp_cents": 400000, "initial_warranty_reserve_cents": 50000},
        acknowledged_at=delivered_at,
        delivered_at=delivered_at,
        claim_overrides={"reported_deformation_mm": 3.5},
    )
    model_id = ctx["product_model_id"]
    customer_id = ctx["customer_id"]
    claim_id = ctx["warranty_claim_id"]
    second_hull = ctx["delivered_units"][1]

    model_at_start = api.read_entity("get_product_model", model_id, admin_headers)
    assert model_at_start["warranty_reserve_cents"] == 50000
    assert model_at_start["warranty_paid_cents"] == 0
    assert_warranty_reserve_conserved(model_at_start)

    # Exactly twelve complete calendar months after delivery, frozen by start-review.
    set_clock("2027-08-01T18:00:00Z")
    reviewing = validate_success(api.start_claim_review(claim_id, warranty_agent_headers))
    assert reviewing["claim_status"] == "UNDER_REVIEW"
    assert reviewing["months_in_service"] == 12
    verified = validate_success(
        api.submit_storage_review(
            claim_id, storage_review_payload("VERIFIED"), warranty_agent_headers
        )
    )
    assert verified["storage_review_status"] == "GUIDANCE_VERIFIED"

    # The reserve rung in isolation: every rung above it is satisfied. At 12 frozen
    # months the PRO_RATA_AGE coverage is (60 - 12) / 60 * 100 == 80.00 percent, the
    # HULL_DEFORMATION type factor is 1.00, so the gross is 400000 * 80.00 / 100 ==
    # 320000; the fee tier is chosen once from that gross, which exceeds 200000, giving
    # 5.00 percent == 16000; the storage deduction is 0 under GUIDANCE_VERIFIED; and the
    # net 304000 dwarfs the 50000 reserve.
    reserve_only = api.approve_warranty_claim(
        claim_id,
        approve_claim_payload(product_model_version(model_id)),
        warranty_agent_headers,
    )
    validate_error(reserve_only, ApiErrorId.WARRANTY_RESERVE_EXHAUSTED, 409)

    # The refused approve wrote nothing at all.
    model_after_refusal = api.read_entity("get_product_model", model_id, admin_headers)
    assert model_after_refusal["warranty_reserve_cents"] == 50000
    assert model_after_refusal["warranty_paid_cents"] == 0
    assert model_after_refusal["version"] == model_at_start["version"]
    assert_warranty_reserve_conserved(model_after_refusal)
    held = api.read_entity("get_warranty_claim", claim_id, warranty_agent_headers)
    assert held["claim_status"] == "UNDER_REVIEW"
    assert held["net_payout_cents"] is None
    assert held["payout_basis"] is None
    assert held["denial_reason"] is None

    # The only way to make the claimant non-ACTIVE also empties UNDER_REVIEW.
    suspended = validate_success(
        api.suspend_customer(
            customer_id,
            suspend_payload("unpaid balance referred to collections"),
            admin_headers,
        )
    )
    assert suspended["status"] == "SUSPENDED"
    voided = api.read_entity("get_warranty_claim", claim_id, warranty_agent_headers)
    assert voided["claim_status"] == "VOIDED"
    assert voided["denial_reason"] == "APPROVAL_VOIDED"
    assert voided["net_payout_cents"] is None

    # No money moved on the void.
    model_after_void = api.read_entity("get_product_model", model_id, admin_headers)
    assert model_after_void["warranty_reserve_cents"] == 50000
    assert model_after_void["warranty_paid_cents"] == 0
    assert_warranty_reserve_conserved(model_after_void)

    # Two rungs are broken at once now — a non-ACTIVE claimant and a payout the reserve
    # cannot cover — and the answer is the rung that sits above both of them.
    both_rungs = api.approve_warranty_claim(
        claim_id,
        approve_claim_payload(product_model_version(model_id)),
        warranty_agent_headers,
    )
    validate_error(both_rungs, ApiErrorId.CLAIM_INVALID_STATE, 409)

    # Reinstatement restores the customer but not the claim.
    reinstated = validate_success(api.reinstate_customer(customer_id, admin_headers))
    assert reinstated["status"] == "ACTIVE"
    still_voided = api.read_entity("get_warranty_claim", claim_id, warranty_agent_headers)
    assert still_voided["claim_status"] == "VOIDED"
    assert still_voided["denial_reason"] == "APPROVAL_VOIDED"

    # A fresh claim from the reinstated customer against the sibling hull is accepted.
    fresh = validate_success(
        api.create_warranty_claim(
            warranty_claim_payload(
                second_hull["id"], customer_id, claim_type="COSMETIC"
            ),
            warranty_agent_headers,
        ),
        201,
    )
    assert fresh["claim_status"] == "SUBMITTED"
    assert fresh["storage_review_status"] == "NOT_STARTED"
    assert fresh["net_payout_cents"] is None
    assert fresh["id"] != claim_id

    # Across one refused approve, one void cascade and one reinstatement the ledger is
    # untouched, so no rung leaked a partial payout.
    model_at_end = api.read_entity("get_product_model", model_id, admin_headers)
    assert model_at_end["warranty_reserve_cents"] == 50000
    assert model_at_end["warranty_paid_cents"] == 0
    assert_warranty_reserve_conserved(model_at_end)

    claims, meta = validate_paginated(
        api.list_warranty_claims({"customer_id": customer_id}, warranty_agent_headers)
    )
    assert meta["total_count"] == 2, "one voided claim and one fresh claim, nothing else"
    assert {claim["claim_status"] for claim in claims} == {"VOIDED", "SUBMITTED"}
