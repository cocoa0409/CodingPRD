"""Three validation pairs where both members are genuinely live at once.

PRD.md section 2.7 fixes one ascending priority order per endpoint and then names
five precedences explicitly because they are easy to invert. Three of those five
are exercised here, each with the same three-call shape:

* the **conflict call**, where both members of the pair are violated by a single
  request, and only one error id may come back;
* **control A**, where the winning member is violated alone, to establish that the
  conflict call's outcome really is the winner's own signature;
* **control B**, where the losing member is violated alone, which is the falsifying
  half — it proves the loser was live during the conflict call and was suppressed
  by priority order rather than by being satisfied.

Because both members of pairs 1 and 5 are refusals, the tests also pin what a
refused request must *not* leave behind: PRD.md sections 3.4, 3.2 and 2.10 all
require that nothing at all is persisted, so no child row appears and no version
moves on any of the three calls.
"""

from test_helpers import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    ApiErrorId,
    Q_MASS,
    Q_PERCENT,
    api_client,
    approve_claim_payload,
    assert_decimal_equals,
    assert_instant_equals,
    assert_null_fields,
    assert_resin_ledger_conserved,
    assert_version_unchanged,
    assert_warranty_reserve_conserved,
    create_plant_baseline,
    create_production_order,
    create_resin_lot,
    mold_payload,
    molding_cycle_payload,
    product_model_version,
    production_order_version,
    resin_charge_payload,
    resin_lot_version,
    schedule_cycle,
    set_clock,
    setup_delivered_unit_with_customer,
    setup_scheduled_cycle,
    storage_review_payload,
    validate_error,
    validate_paginated,
    validate_success,
    warranty_claim_payload,
)


# ----------------------------------------------------------------------
# Pair 1: order state (band 4) beats the oven arm window (band 6)
# ----------------------------------------------------------------------

_P1_TAKEN_ARM_START = "2026-08-01T09:00:00Z"
_P1_OVERLAPPING_START = "2026-08-01T09:30:00Z"
_P1_CLEAR_START = "2026-08-01T13:00:00Z"


def _p1_one_taken_arm_two_moulds_and_a_draft_order():
    """A busy arm 1, a DRAFT order and a released order that could use the arm.

    The model carries two single-cavity tools rather than one. The second tool is
    deliberate: it keeps the mould pool non-empty over the contested window, so
    neither `ERR_MOLD_WINDOW_CONFLICT` nor `ERR_NO_ELIGIBLE_MOLD` can stand in for
    the pair's losing member.

    Arm 1 of the station is held from 09:00 to 10:00 by a SCHEDULED cycle, and the
    station's `changeover_buffer_min` of 15 widens that *stored* span to 08:45
    through 10:15, so a candidate opening at 09:30 overlaps it.
    """
    ctx = create_plant_baseline(
        mold_overrides={"cavity_count": 1, "nominal_charge_kg": 12.0},
    )
    second_mold = validate_success(
        api_client.create_mold(
            mold_payload(
                ctx["product_model_id"], cavity_count=1, nominal_charge_kg=12.0
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    create_resin_lot()
    order_a = create_production_order(ctx, ordered_qty=1)
    cycle_a = schedule_cycle(ctx, order_a, oven_start_at=_P1_TAKEN_ARM_START)
    draft_order = create_production_order(ctx, release=False, ordered_qty=1)
    released_order = create_production_order(ctx, ordered_qty=1)

    assert ctx["oven_station"]["arm_count"] == 2, (
        "the station must offer a second arm for control A, got "
        f"{ctx['oven_station']['arm_count']}"
    )
    assert ctx["oven_station"]["changeover_buffer_min"] == 15, (
        "the buffer that widens the stored span must be 15 minutes, got "
        f"{ctx['oven_station']['changeover_buffer_min']}"
    )
    assert cycle_a["status"] == "SCHEDULED", (
        f"only a SCHEDULED or OVEN_RUNNING cycle occupies an arm, got {cycle_a['status']}"
    )
    assert cycle_a["arm_index"] == 1, (
        f"the contested arm is arm 1, got {cycle_a['arm_index']}"
    )
    assert draft_order["status"] == "DRAFT", (
        f"the pair's winning member needs an unreleased order, got {draft_order['status']}"
    )
    assert released_order["status"] == "READY_TO_SCHEDULE", (
        "control B needs an order that passes the order-state check, got "
        f"{released_order['status']}"
    )
    assert second_mold["status"] == "AVAILABLE", (
        f"the spare tool must be selectable, got {second_mold['status']}"
    )
    ctx.update(
        {
            "cycle_a": cycle_a,
            "draft_order": draft_order,
            "released_order": released_order,
            "second_mold": second_mold,
        }
    )
    return ctx


def _p1_book(ctx, order, **overrides):
    """Attempt one booking and hand back the raw response, refused or not."""
    return api_client.create_molding_cycle(
        molding_cycle_payload(
            order["id"],
            ctx["oven_station_id"],
            ctx["cooling_bay_id"],
            production_order_version(order["id"]),
            **overrides,
        ),
        ctx["operator_headers"],
    )


def _p1_cycles_for(order):
    rows, _meta = validate_paginated(
        api_client.list_molding_cycles({"production_order_id": order["id"]}, ADMIN_HEADERS)
    )
    return rows


class TestOrderStateBeatsOvenWindowConflict:
    """Two 409s, so only the error id can tell which check ran first."""

    def test_the_unreleased_order_is_reported_and_the_taken_arm_is_not(self):
        """The conflict call violates both members and must name the order state.

        PRD.md section 2.7: "Each endpoint evaluates its applicable checks in a fixed
        ascending priority order and returns on the first failure it finds; no
        endpoint reports two errors, and no later check runs after an earlier one has
        failed."

        PRD.md section 2.7: "When a cycle targets an order that is not schedulable
        *and* asks for an oven arm window that is already taken, the order-state
        failure wins."

        PRD.md section 3.4: "The order's `status` must be `READY_TO_SCHEDULE` or
        `IN_PRODUCTION`; a `DRAFT`, `BLOCKED_RESIN`, `BLOCKED_WAREHOUSE`, `COMPLETE`
        or `CANCELLED` order cannot take a new cycle and is refused with
        `ERR_ORDER_NOT_SCHEDULABLE` (HTTP 409)."

        PRD.md section 3.4: "Then the oven arm window, then the bay slot count, then
        the mould pool, then the overbuild ceiling, and last of all
        `expected_production_order_version`."

        Both members carry HTTP 409, so the response status cannot distinguish them
        and the error id is the entire observation.

        Design: Difficulty/priority_pair_validation_conflict/pair1_order_not_schedulable_beats_oven_window_conflict
        """
        ctx = _p1_one_taken_arm_two_moulds_and_a_draft_order()

        refused = _p1_book(
            ctx, ctx["draft_order"], arm_index=1, oven_start_at=_P1_OVERLAPPING_START
        )

        validate_error(refused, ApiErrorId.ORDER_NOT_SCHEDULABLE, expected_status=409)
        assert refused.status_code == 409, (
            "both members of this pair are 409s, which is exactly why the id matters, "
            f"got {refused.status_code}"
        )

    def test_the_refusal_writes_no_cycle_and_bumps_no_version(self):
        """A refused booking leaves the order exactly as it was.

        PRD.md section 3.4: "A refused booking writes nothing at all — no cycle row,
        no order version bump."

        PRD.md section 2.10: "When any link of a cascade cannot be applied, or when
        any validation the triggering request declares fails, nothing at all is
        persisted: no child row, no ledger movement, no status change, no version
        increment."

        The cycle that occupies the contested arm is also untouched: losing a
        booking never disturbs the booking that won the arm.

        Design: Difficulty/priority_pair_validation_conflict/pair1_order_not_schedulable_beats_oven_window_conflict
        """
        ctx = _p1_one_taken_arm_two_moulds_and_a_draft_order()
        before = api_client.read_entity(
            "get_production_order", ctx["draft_order"]["id"], ADMIN_HEADERS
        )

        validate_error(
            _p1_book(
                ctx, ctx["draft_order"], arm_index=1, oven_start_at=_P1_OVERLAPPING_START
            ),
            ApiErrorId.ORDER_NOT_SCHEDULABLE,
            expected_status=409,
        )

        after = api_client.read_entity(
            "get_production_order", ctx["draft_order"]["id"], ADMIN_HEADERS
        )
        assert after["status"] == "DRAFT", (
            f"the refused order does not advance, got {after['status']}"
        )
        assert_version_unchanged(before, after, "draft production order")
        assert _p1_cycles_for(ctx["draft_order"]) == [], (
            "the refusal persists no cycle row for the unreleased order"
        )
        incumbent = api_client.read_entity(
            "get_molding_cycle", ctx["cycle_a"]["id"], ADMIN_HEADERS
        )
        assert incumbent["status"] == "SCHEDULED", (
            f"the cycle holding the arm is unaffected, got {incumbent['status']}"
        )

    def test_control_a_reproduces_the_verdict_from_the_order_state_alone(self):
        """Member A alone, on a free arm, produces the conflict call's own outcome.

        PRD.md section 3.4: "a `DRAFT`, `BLOCKED_RESIN`, `BLOCKED_WAREHOUSE`,
        `COMPLETE` or `CANCELLED` order cannot take a new cycle and is refused with
        `ERR_ORDER_NOT_SCHEDULABLE` (HTTP 409)."

        PRD.md section 2.9: "cycles sharing an `oven_station_id` but holding
        different `arm_index` values never conflict, so a station whose `arm_count`
        is 4 can hold four fully coincident windows."

        Arm 2 at 13:00 is doubly clear — a different arm and a disjoint window — so
        the window check has nothing to say and the same id comes back.

        Design: Difficulty/priority_pair_validation_conflict/pair1_order_not_schedulable_beats_oven_window_conflict
        """
        ctx = _p1_one_taken_arm_two_moulds_and_a_draft_order()

        refused = _p1_book(
            ctx, ctx["draft_order"], arm_index=2, oven_start_at=_P1_CLEAR_START
        )

        validate_error(refused, ApiErrorId.ORDER_NOT_SCHEDULABLE, expected_status=409)
        assert _p1_cycles_for(ctx["draft_order"]) == [], (
            "control A persists no cycle either"
        )

    def test_control_b_shows_the_arm_conflict_was_live_and_merely_suppressed(self):
        """Member B alone, over the identical window, returns the other id.

        PRD.md section 2.9: "The station's `changeover_buffer_min` is applied
        symmetrically to both ends of each *already-stored* cycle's span — never to
        the candidate's — so the buffer is counted exactly once per comparison."

        PRD.md section 2.9: "A single overlap is enough to refuse the booking with
        `ERR_OVEN_WINDOW_CONFLICT` (HTTP 409)."

        PRD.md section 3.4: "The order's `status` must be `READY_TO_SCHEDULE` or
        `IN_PRODUCTION`."

        This is the falsifying half of the pair. The request differs from the
        conflict call in one respect only — the order it names is released — and the
        window it asks for is the same contested 09:30 span. Getting
        `ERR_OVEN_WINDOW_CONFLICT` here proves the window check was violated during
        the conflict call too and was suppressed purely by priority order.

        Design: Difficulty/priority_pair_validation_conflict/pair1_order_not_schedulable_beats_oven_window_conflict
        """
        ctx = _p1_one_taken_arm_two_moulds_and_a_draft_order()
        before = api_client.read_entity(
            "get_production_order", ctx["released_order"]["id"], ADMIN_HEADERS
        )

        refused = _p1_book(
            ctx, ctx["released_order"], arm_index=1, oven_start_at=_P1_OVERLAPPING_START
        )

        validate_error(refused, ApiErrorId.OVEN_WINDOW_CONFLICT, expected_status=409)
        after = api_client.read_entity(
            "get_production_order", ctx["released_order"]["id"], ADMIN_HEADERS
        )
        assert after["status"] == "READY_TO_SCHEDULE", (
            "a refused booking does not move the order into production, got "
            f"{after['status']}"
        )
        assert_version_unchanged(before, after, "released production order")
        assert _p1_cycles_for(ctx["released_order"]) == [], (
            "control B persists no cycle either"
        )


# ----------------------------------------------------------------------
# Pair 2: the regrind ceiling (band 5) beats resin sufficiency (band 7)
# ----------------------------------------------------------------------

_P1_FULL_SHOT_KG = 24.0
_P1_BREACHING_REGRIND_KG = 12.0
_P1_COMPLIANT_REGRIND_KG = 2.4
_P1_THIN_LOT_KG = 23.0


def _p1_scheduled_cycle_with_a_thin_and_a_deep_lot():
    """One empty SCHEDULED cycle plus two lots that differ only in mass.

    The model's minimum shot mass is `nominal_charge_kg` times one minus
    `charge_tolerance_pct` over 100, which is 24.000 times 0.95 rounded to 22.800.
    The thin lot holds 23.000 kg, so it clears that qualification threshold and can
    be drawn on, yet it holds less than the 24.000 kg full shot a charge asks for.
    That is what keeps the pair's losing member live without letting lot
    qualification decide the request instead.
    """
    ctx = setup_scheduled_cycle(
        charge=False,
        model_overrides={"nominal_charge_kg": 24.0},
        mold_overrides={"cavity_count": 1, "nominal_charge_kg": 24.0},
        order_overrides={"ordered_qty": 1},
    )
    thin_lot = create_resin_lot(received_kg=_P1_THIN_LOT_KG)

    assert ctx["molding_cycle"]["status"] == "SCHEDULED", (
        f"a charge may only target a SCHEDULED cycle, got {ctx['molding_cycle']['status']}"
    )
    assert_decimal_equals(
        ctx["molding_cycle"]["charged_mass_kg"], 0.000, Q_MASS, "charged_mass_kg"
    )
    assert_decimal_equals(
        ctx["molding_cycle"]["cycle_regrind_pct"], 0.00, Q_PERCENT, "cycle_regrind_pct"
    )
    assert_decimal_equals(
        ctx["product_model"]["max_regrind_pct"], 30.00, Q_PERCENT, "max_regrind_pct"
    )
    assert thin_lot["status"] == "AVAILABLE", (
        f"the thin lot must be nameable in a charge request, got {thin_lot['status']}"
    )
    assert_decimal_equals(
        thin_lot["available_kg"], _P1_THIN_LOT_KG, Q_MASS, "thin lot available_kg"
    )
    assert_decimal_equals(
        ctx["resin_lot"]["available_kg"], 500.000, Q_MASS, "deep lot available_kg"
    )
    ctx["thin_lot"] = thin_lot
    ctx["deep_lot"] = ctx["resin_lot"]
    return ctx


def _p1_reserve(ctx, lot, **overrides):
    """Attempt one reservation and hand back the raw response, refused or not."""
    return api_client.create_resin_charge(
        resin_charge_payload(
            ctx["molding_cycle_id"],
            lot["id"],
            resin_lot_version(lot["id"]),
            **overrides,
        ),
        ctx["resin_tech_headers"],
    )


def _p1_charges_for(ctx):
    rows, _meta = validate_paginated(
        api_client.list_resin_charges(
            {"molding_cycle_id": ctx["molding_cycle_id"]}, ADMIN_HEADERS
        )
    )
    return rows


def _p1_read_lot(lot):
    return api_client.read_entity("get_resin_lot", lot["id"], ADMIN_HEADERS)


class TestRegrindCeilingBeatsResinInsufficiency:
    """Here the two members carry different statuses, so 422 versus 409 is itself the verdict."""

    def test_the_blend_breach_is_reported_and_the_shortfall_is_not(self):
        """The conflict call overdraws a thin lot with an illegal blend.

        PRD.md section 2.7: "When a candidate charge would both breach the blended
        regrind ceiling *and* draw more mass than the lot has available, the regrind
        failure wins."

        PRD.md section 3.2: "A percentage strictly greater than the model's
        `max_regrind_pct` is refused with `ERR_REGRIND_LIMIT_EXCEEDED` (HTTP 422); a
        blend landing at exactly the ceiling — 30.00 against a default ceiling of
        30.00 — is accepted, and 30.01 is not."

        PRD.md section 3.2: "A candidate charge that would both breach the ceiling
        and overdraw the lot reports the regrind failure, never the insufficiency."

        The cycle holds no other charge, so the post-add blend is the candidate
        alone: 12.000 kg of regrind in a 24.000 kg shot is 50.00 percent against a
        30.00 percent ceiling. The same request asks for 24.000 kg from a lot holding
        23.000 kg.

        Design: Difficulty/priority_pair_validation_conflict/pair2_regrind_limit_beats_resin_insufficient
        """
        ctx = _p1_scheduled_cycle_with_a_thin_and_a_deep_lot()

        refused = _p1_reserve(
            ctx,
            ctx["thin_lot"],
            charge_kg=_P1_FULL_SHOT_KG,
            regrind_kg=_P1_BREACHING_REGRIND_KG,
        )

        validate_error(refused, ApiErrorId.REGRIND_LIMIT_EXCEEDED, expected_status=422)
        assert refused.status_code == 422, (
            "had mass availability been tested first the response would have been a "
            f"409, got {refused.status_code}"
        )

    def test_the_refused_charge_moves_no_mass_and_leaves_no_row(self):
        """Both ledgers and both roll-ups stand exactly where they started.

        PRD.md section 3.2: "A refused charge writes nothing: no row, no mass
        movement, no version increment."

        PRD.md section 2.10: "A resin lot holds a three-bucket ledger in which the
        rounded sum of `available_kg`, `reserved_kg` and `consumed_kg` always equals
        the immutable `received_kg`."

        PRD.md section 3.2: "`charged_mass_kg` is the sum of `charge_kg` over the
        participating charges rounded to three decimals."

        Design: Difficulty/priority_pair_validation_conflict/pair2_regrind_limit_beats_resin_insufficient
        """
        ctx = _p1_scheduled_cycle_with_a_thin_and_a_deep_lot()

        validate_error(
            _p1_reserve(
                ctx,
                ctx["thin_lot"],
                charge_kg=_P1_FULL_SHOT_KG,
                regrind_kg=_P1_BREACHING_REGRIND_KG,
            ),
            ApiErrorId.REGRIND_LIMIT_EXCEEDED,
            expected_status=422,
        )

        assert _p1_charges_for(ctx) == [], (
            "the refusal leaves no partial charge row behind"
        )
        thin_after = _p1_read_lot(ctx["thin_lot"])
        assert_decimal_equals(
            thin_after["available_kg"], _P1_THIN_LOT_KG, Q_MASS, "thin lot available_kg"
        )
        assert_decimal_equals(
            thin_after["reserved_kg"], 0.000, Q_MASS, "thin lot reserved_kg"
        )
        assert_decimal_equals(
            thin_after["consumed_kg"], 0.000, Q_MASS, "thin lot consumed_kg"
        )
        assert_resin_ledger_conserved(thin_after)
        assert_version_unchanged(ctx["thin_lot"], thin_after, "thin resin lot")
        cycle_after = api_client.read_entity(
            "get_molding_cycle", ctx["molding_cycle_id"], ADMIN_HEADERS
        )
        assert_decimal_equals(
            cycle_after["charged_mass_kg"], 0.000, Q_MASS, "charged_mass_kg"
        )
        assert_decimal_equals(
            cycle_after["cycle_regrind_pct"], 0.00, Q_PERCENT, "cycle_regrind_pct"
        )

    def test_control_b_shows_the_shortfall_was_live_and_merely_suppressed(self):
        """Member B alone, from the same thin lot, returns the other id and status.

        PRD.md section 3.2: "Only after that ceiling passes is **mass availability**
        tested: the lot's `available_kg` must be at least `charge_kg`, equality being
        legal and draining the lot to exactly 0.000, otherwise
        `ERR_RESIN_INSUFFICIENT` (HTTP 409)."

        This is the falsifying half. Dropping the regrind to 2.400 kg makes the blend
        10.00 percent, well inside the ceiling, and changes nothing else: the same
        thin lot is still asked for 24.000 kg it does not hold. The 409 that comes
        back proves the sufficiency check was violated during the conflict call and
        never got to run.

        Design: Difficulty/priority_pair_validation_conflict/pair2_regrind_limit_beats_resin_insufficient
        """
        ctx = _p1_scheduled_cycle_with_a_thin_and_a_deep_lot()

        refused = _p1_reserve(
            ctx,
            ctx["thin_lot"],
            charge_kg=_P1_FULL_SHOT_KG,
            regrind_kg=_P1_COMPLIANT_REGRIND_KG,
        )

        validate_error(refused, ApiErrorId.RESIN_INSUFFICIENT, expected_status=409)
        assert _p1_charges_for(ctx) == [], "control B persists no charge row either"
        assert_resin_ledger_conserved(_p1_read_lot(ctx["thin_lot"]))

    def test_control_a_reproduces_the_verdict_from_the_blend_alone(self):
        """Member A alone, from a lot with mass to spare, gives the same 422.

        PRD.md section 3.2: "the cycle's regrind percentage is then
        `total_regrind_kg` divided by `total_charge_kg` times 100, rounded to two
        decimals — the two masses are rounded *before* the division, and when
        `total_charge_kg` is 0.000 the percentage is 0.00."

        The deep lot holds 500.000 kg, so the shortfall member is satisfied outright
        and the illegal 50.00 percent blend is the only thing left to fail on.

        Design: Difficulty/priority_pair_validation_conflict/pair2_regrind_limit_beats_resin_insufficient
        """
        ctx = _p1_scheduled_cycle_with_a_thin_and_a_deep_lot()

        refused = _p1_reserve(
            ctx,
            ctx["deep_lot"],
            charge_kg=_P1_FULL_SHOT_KG,
            regrind_kg=_P1_BREACHING_REGRIND_KG,
        )

        validate_error(refused, ApiErrorId.REGRIND_LIMIT_EXCEEDED, expected_status=422)
        deep_after = _p1_read_lot(ctx["deep_lot"])
        assert_decimal_equals(
            deep_after["available_kg"], 500.000, Q_MASS, "deep lot available_kg"
        )
        assert_decimal_equals(
            deep_after["reserved_kg"], 0.000, Q_MASS, "deep lot reserved_kg"
        )
        assert _p1_charges_for(ctx) == [], "control A persists no charge row either"


# ----------------------------------------------------------------------
# Pair 5: the storage review (band 4) beats the warranty term (band 6)
# ----------------------------------------------------------------------

_P1_DELIVERED_AT = "2026-08-02T00:00:00Z"
_P1_TWELVE_MONTHS_ON = "2027-08-02T00:00:00Z"
_P1_SIXTY_TWO_MONTHS_ON = "2031-10-02T00:00:00Z"
_P1_INITIAL_RESERVE_CENTS = 500000


def _p1_two_delivered_hulls_and_an_active_customer():
    """Two DELIVERED hulls owned by a customer who read the storage guidance in time.

    Both hulls carry the same `delivered_at`, which is the origin of the warranty
    clock, so moving the logical clock is the only thing that ages a claim. Every
    guard below the pair is satisfied on purpose: the customer is ACTIVE, both hulls
    are DELIVERED, the acknowledgement predates delivery, and the model's reserve
    has never been drawn on.
    """
    ctx = setup_delivered_unit_with_customer(
        model_overrides={"msrp_cents": 300000, "warranty_basis": "FLAT_SCHEDULE"},
        lot_overrides={"expires_on": "2035-12-31"},
    )

    assert len(ctx["delivered_units"]) == 2, (
        "the pair needs one hull per control, got "
        f"{len(ctx['delivered_units'])} delivered hulls"
    )
    for hull in ctx["delivered_units"]:
        assert hull["logistics_status"] == "DELIVERED", (
            f"a claim may only be approved on a delivered hull, got {hull['logistics_status']}"
        )
        assert_instant_equals(hull["delivered_at"], _P1_DELIVERED_AT, "delivered_at")
    assert ctx["customer"]["status"] == "ACTIVE", (
        f"the claimant must be ACTIVE, got {ctx['customer']['status']}"
    )
    assert_instant_equals(
        ctx["customer"]["storage_guidance_acknowledged_at"],
        "2026-08-01T00:00:00Z",
        "storage_guidance_acknowledged_at",
    )
    model = _p1_read_model(ctx)
    assert model["warranty_reserve_cents"] == _P1_INITIAL_RESERVE_CENTS, (
        f"the reserve starts whole, got {model['warranty_reserve_cents']}"
    )
    assert model["warranty_paid_cents"] == 0, (
        f"nothing has been paid yet, got {model['warranty_paid_cents']}"
    )
    return ctx


def _p1_read_model(ctx):
    return api_client.read_entity(
        "get_product_model", ctx["product_model_id"], ADMIN_HEADERS
    )


def _p1_read_claim(claim_id):
    return api_client.read_entity("get_warranty_claim", claim_id, AGENT_HEADERS)


def _p1_claim_aged_to(ctx, hull, clock_at, expected_months):
    """File a claim on ``hull`` and freeze its age by starting review at ``clock_at``."""
    set_clock(clock_at)
    claim = validate_success(
        api_client.create_warranty_claim(
            warranty_claim_payload(hull["id"], ctx["customer_id"]), AGENT_HEADERS
        ),
        201,
    )
    reviewed = validate_success(
        api_client.start_claim_review(claim["id"], AGENT_HEADERS), 200
    )
    assert reviewed["claim_status"] == "UNDER_REVIEW", (
        f"approval is only attempted from UNDER_REVIEW, got {reviewed['claim_status']}"
    )
    assert reviewed["months_in_service"] == expected_months, (
        f"the frozen age must be {expected_months} complete calendar months, got "
        f"{reviewed['months_in_service']}"
    )
    assert reviewed["storage_review_status"] == "NOT_STARTED", (
        "the storage axis starts undecided, got "
        f"{reviewed['storage_review_status']}"
    )
    return reviewed


def _p1_approve(ctx, claim_id):
    """Attempt an approval with a freshly read model version, refused or not."""
    return api_client.approve_warranty_claim(
        claim_id,
        approve_claim_payload(product_model_version(ctx["product_model_id"])),
        AGENT_HEADERS,
    )


class TestStorageReviewIncompleteBeatsWarrantyTermExpired:
    """Two hulls, two ages, and one claim that violates both members at once."""

    def test_control_a_reproduces_the_verdict_from_the_undecided_axis_alone(self):
        """Member A alone, comfortably inside the term, establishes the winner's signature.

        PRD.md section 3.9: "the storage axis must be `GUIDANCE_VERIFIED` or
        `WAIVED`, otherwise `ERR_STORAGE_REVIEW_INCOMPLETE` (HTTP 409) — a claim
        still `NOT_STARTED` or standing at an unwaived `GUIDANCE_VIOLATED` is refused
        before pricing begins".

        PRD.md section 3.9: "It computes and freezes `months_in_service` as the
        number of **complete calendar months** from the hull's `delivered_at` to the
        logical clock, floored: a hull delivered twelve months and twenty-nine days
        ago reads 12, not 13."

        PRD.md section 3.9: "the frozen `months_in_service` must be at or below the
        warranty term of 60 months, otherwise `ERR_WARRANTY_TERM_EXPIRED` (HTTP 422),
        with exactly 60 still inside the term".

        At 12 months this claim is well inside the term, so the losing member is
        satisfied and only the undecided storage axis can refuse the approval.

        Design: Difficulty/priority_pair_validation_conflict/pair5_storage_review_incomplete_beats_warranty_term_expired
        """
        ctx = _p1_two_delivered_hulls_and_an_active_customer()
        claim = _p1_claim_aged_to(
            ctx, ctx["delivered_units"][1], _P1_TWELVE_MONTHS_ON, 12
        )

        refused = _p1_approve(ctx, claim["id"])

        validate_error(
            refused, ApiErrorId.STORAGE_REVIEW_INCOMPLETE, expected_status=409
        )
        assert _p1_read_claim(claim["id"])["claim_status"] == "UNDER_REVIEW", (
            "a refused approval leaves the adjudication axis where it was"
        )

    def test_the_undecided_axis_is_reported_and_the_expired_term_is_not(self):
        """The conflict call violates both members and must name the storage axis.

        PRD.md section 2.7: "When a claim is approved with an incomplete storage
        review *and* the hull is out of warranty term, the storage-review failure
        wins."

        PRD.md section 3.9: "In order: the claim must be `UNDER_REVIEW`
        (`ERR_CLAIM_INVALID_STATE`); the storage axis must be `GUIDANCE_VERIFIED` or
        `WAIVED`, otherwise `ERR_STORAGE_REVIEW_INCOMPLETE` (HTTP 409)".

        PRD.md section 2.7: "no endpoint reports two errors, and no later check runs
        after an earlier one has failed."

        Sixty-two complete calendar months separate delivery from the clock, which is
        outside the sixty-month term, and the storage axis is still `NOT_STARTED`.
        The two members carry different statuses, so an implementation that priced
        the claim before finishing its validation ladder would be caught by the
        status code alone.

        Design: Difficulty/priority_pair_validation_conflict/pair5_storage_review_incomplete_beats_warranty_term_expired
        """
        ctx = _p1_two_delivered_hulls_and_an_active_customer()
        claim = _p1_claim_aged_to(
            ctx, ctx["delivered_units"][0], _P1_SIXTY_TWO_MONTHS_ON, 62
        )

        refused = _p1_approve(ctx, claim["id"])

        validate_error(
            refused, ApiErrorId.STORAGE_REVIEW_INCOMPLETE, expected_status=409
        )
        assert refused.status_code == 409, (
            "the term failure would have answered 422, so the status is part of the "
            f"observation, got {refused.status_code}"
        )

    def test_control_b_shows_the_expired_term_was_live_and_merely_suppressed(self):
        """Satisfying member A on the same claim surfaces member B underneath it.

        PRD.md section 3.9: "`VERIFIED` sets the axis to `GUIDANCE_VERIFIED` and
        guarantees a zero storage deduction".

        PRD.md section 3.9: "Deciding the storage axis never moves the adjudication
        axis — the claim stays `UNDER_REVIEW` — and approval reads the storage axis
        as a precondition rather than driving it."

        PRD.md section 3.9: "the frozen `months_in_service` must be at or below the
        warranty term of 60 months, otherwise `ERR_WARRANTY_TERM_EXPIRED` (HTTP 422)".

        This is the falsifying half of the pair. The storage review is the only thing
        that changed between the two approvals of this one claim, and the age it was
        frozen with is untouched, so the 422 proves the term check was violated during
        the conflict call and was suppressed purely by priority order.

        Design: Difficulty/priority_pair_validation_conflict/pair5_storage_review_incomplete_beats_warranty_term_expired
        """
        ctx = _p1_two_delivered_hulls_and_an_active_customer()
        claim = _p1_claim_aged_to(
            ctx, ctx["delivered_units"][0], _P1_SIXTY_TWO_MONTHS_ON, 62
        )
        validate_error(
            _p1_approve(ctx, claim["id"]),
            ApiErrorId.STORAGE_REVIEW_INCOMPLETE,
            expected_status=409,
        )

        verified = validate_success(
            api_client.submit_storage_review(
                claim["id"], storage_review_payload("VERIFIED"), AGENT_HEADERS
            ),
            200,
        )
        assert verified["storage_review_status"] == "GUIDANCE_VERIFIED", (
            f"the storage axis must now clear approval, got {verified['storage_review_status']}"
        )
        assert verified["claim_status"] == "UNDER_REVIEW", (
            f"deciding the storage axis moves no adjudication, got {verified['claim_status']}"
        )
        assert verified["months_in_service"] == 62, (
            f"the frozen age is not re-aged by the storage review, got {verified['months_in_service']}"
        )

        refused = _p1_approve(ctx, claim["id"])

        validate_error(refused, ApiErrorId.WARRANTY_TERM_EXPIRED, expected_status=422)

    def test_none_of_the_three_refusals_prices_the_claim_or_moves_the_reserve(self):
        """Three rejected approvals leave the money fields null and the ledger whole.

        PRD.md section 3.9: "A new claim starts with `claim_status` `SUBMITTED`,
        `storage_review_status` `NOT_STARTED`, `months_in_service` null and every
        money field — `payout_basis`, `pre_fee_gross_cents`,
        `storage_deduction_cents`, `admin_fee_cents`, `net_payout_cents` — and
        `denial_reason` null, with `version` 1."

        PRD.md section 3.9: "The invariant `warranty_reserve_cents` plus
        `warranty_paid_cents` equals `initial_warranty_reserve_cents` holds after
        every ledger move, without exception."

        PRD.md section 2.10: "A hull model holds a two-bucket ledger in which
        `warranty_reserve_cents` plus `warranty_paid_cents` always equals the
        immutable `initial_warranty_reserve_cents`; approving a claim moves the net
        payout from reserve to paid".

        Approval is the only path that spends money, and none of these three
        approvals succeeded. The only version that legitimately moves in this test
        belongs to the claim itself, from the storage-review call; the model's must
        not move at all.

        Design: Difficulty/priority_pair_validation_conflict/pair5_storage_review_incomplete_beats_warranty_term_expired
        """
        ctx = _p1_two_delivered_hulls_and_an_active_customer()
        model_before = _p1_read_model(ctx)
        inside_term = _p1_claim_aged_to(
            ctx, ctx["delivered_units"][1], _P1_TWELVE_MONTHS_ON, 12
        )
        validate_error(
            _p1_approve(ctx, inside_term["id"]),
            ApiErrorId.STORAGE_REVIEW_INCOMPLETE,
            expected_status=409,
        )
        expired = _p1_claim_aged_to(
            ctx, ctx["delivered_units"][0], _P1_SIXTY_TWO_MONTHS_ON, 62
        )
        validate_error(
            _p1_approve(ctx, expired["id"]),
            ApiErrorId.STORAGE_REVIEW_INCOMPLETE,
            expected_status=409,
        )
        validate_success(
            api_client.submit_storage_review(
                expired["id"], storage_review_payload("VERIFIED"), AGENT_HEADERS
            ),
            200,
        )

        validate_error(
            _p1_approve(ctx, expired["id"]),
            ApiErrorId.WARRANTY_TERM_EXPIRED,
            expected_status=422,
        )

        settled = _p1_read_claim(expired["id"])
        assert settled["claim_status"] == "UNDER_REVIEW", (
            f"the claim is neither approved nor denied, got {settled['claim_status']}"
        )
        assert settled["storage_review_status"] == "GUIDANCE_VERIFIED", (
            f"the storage axis keeps its own outcome, got {settled['storage_review_status']}"
        )
        assert_null_fields(
            settled,
            [
                "payout_basis",
                "pre_fee_gross_cents",
                "storage_deduction_cents",
                "admin_fee_cents",
                "net_payout_cents",
            ],
            "refused warranty claim",
        )
        model_after = _p1_read_model(ctx)
        assert model_after["warranty_reserve_cents"] == _P1_INITIAL_RESERVE_CENTS, (
            f"no payout was made, got {model_after['warranty_reserve_cents']}"
        )
        assert model_after["warranty_paid_cents"] == 0, (
            f"no payout was made, got {model_after['warranty_paid_cents']}"
        )
        assert_warranty_reserve_conserved(model_after)
        assert_version_unchanged(model_before, model_after, "product model")
