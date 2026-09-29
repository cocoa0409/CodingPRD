"""Two action endpoints whose interest is the ORDER in which their gates fire.

Release carries three independent preconditions and the return-to-queue edge
resets two parallel axes at once, which then re-orders the approve ladder. Both
are asserted on rows where more than one gate fails simultaneously, so the tests
observe which condition is reported rather than merely that something was.
"""

from test_helpers import (
    ApiErrorId,
    DEFAULT_ZONE_CODE,
    assert_money_equals,
    assert_warranty_reserve_conserved,
    create_plant_baseline,
    create_production_order,
    get_success_data,
    mold_payload,
    product_model_payload,
    product_model_version,
    return_to_queue_payload,
    approve_claim_payload,
    setup_claim_storage_waived,
    setup_stored_units,
    validate_error,
    validate_success,
    warehouse_payload,
    zone,
)

# The frozen site is sized so its single stored anchor hull fills it exactly.
# PRD.md section 3.7 accepts a store that lands at capacity and then derives
# posture from the rounded utilisation, which is 100.00 and therefore FROZEN.
FROZEN_CAPACITY_CUBE_M3 = 2.0


def _p3_identity_overrides(ctx, cycle_overrides=None, charge_overrides=None):
    """Name the acting technicians that the shared payload factories omit.

    ``test_helpers.factories.molding_cycle_payload`` omits
    ``operator_technician_id`` and ``resin_charge_payload`` omits
    ``created_by_technician_id``, yet PRD.md section 2.8 lists both as required
    client-supplied fields. This partition supplies each one as the acting
    identifier, which satisfies that reading and the reading in which the
    server copies it from the caller.
    """
    cyc = dict(cycle_overrides or {})
    cyc.setdefault("operator_technician_id", ctx["molding_operator_id"])
    chg = dict(charge_overrides or {})
    chg.setdefault("created_by_technician_id", ctx["resin_technician_id"])
    return cyc, chg


def _p3_release_ladder(api):
    """A frozen site, a healthy site, and a hull model with neither tool nor lot.

    The baseline site is sized to exactly one stored hull's cube so that storing
    that hull drives it to FROZEN. A second, full-size site is registered to
    carry the orders whose site must stay healthy. A second hull model widens
    the melt-index band beyond the only lot's index, so no lot can ever qualify
    for it, and no tool is registered for it either.
    """
    baseline = create_plant_baseline(
        warehouse_overrides={
            "footprint_capacity_cube_m3": FROZEN_CAPACITY_CUBE_M3,
            "zones": [zone(DEFAULT_ZONE_CODE, FROZEN_CAPACITY_CUBE_M3)],
        }
    )
    cyc, chg = _p3_identity_overrides(baseline)
    ctx = setup_stored_units(
        baseline=baseline,
        unit_count=1,
        order_overrides={"order_code": "POR-CD-REL-SEED"},
        cycle_overrides=cyc,
        charge_overrides=chg,
    )

    healthy_site = get_success_data(
        api.create_warehouse(
            warehouse_payload(site_code="WHS-CD-REL"), ctx["planner_headers"]
        )
    )
    starved_model = get_success_data(
        api.create_product_model(
            product_model_payload(
                model_code="PM-CD-REL-T3",
                min_melt_index_g10min=5.0,
                max_melt_index_g10min=7.0,
            ),
            ctx["admin_headers"],
        )
    )

    ctx["healthy_site"] = healthy_site
    ctx["frozen_site_id"] = ctx["warehouse_id"]
    ctx["starved_model"] = starved_model
    ctx["order_healthy"] = create_production_order(
        ctx,
        release=False,
        order_code="POR-CD-REL-A",
        target_warehouse_id=healthy_site["id"],
        ordered_qty=2,
    )
    ctx["order_no_tool"] = create_production_order(
        ctx,
        release=False,
        order_code="POR-CD-REL-B",
        product_model_id=starved_model["id"],
        target_warehouse_id=healthy_site["id"],
        ordered_qty=1,
    )
    ctx["order_frozen_site"] = create_production_order(
        ctx,
        release=False,
        order_code="POR-CD-REL-C",
        product_model_id=starved_model["id"],
        target_warehouse_id=ctx["warehouse_id"],
        ordered_qty=1,
    )
    return ctx


def _p3_assert_reported_condition(response, hard_error_id, soft_status, soft_reason):
    """Assert which release precondition was reported, under either PRD reading.

    PRD.md section 3.3 states the frozen-site and unqualified-resin outcomes
    twice and inconsistently. Its precondition list says "the target site's
    `posture` is not `FROZEN`, otherwise `ERR_WAREHOUSE_FROZEN` (HTTP 409) ...
    and at least one resin lot qualifies for the model, otherwise
    `ERR_RESIN_INSUFFICIENT` (HTTP 409)", while the following sentence says "Two
    soft outcomes also exist, and both still return HTTP 200: when the target
    site's `posture` is `FROZEN` the order moves `DRAFT` to `BLOCKED_WAREHOUSE`
    with `blocked_reason` `WAREHOUSE_FROZEN`; when the qualified-lot count is
    zero the order moves `DRAFT` to `BLOCKED_RESIN` with `blocked_reason`
    `NO_QUALIFIED_RESIN_LOT`." PRD.md section 3.2 corroborates the second
    reading: "Used as a **release gate**, a count of zero sends an order to
    `BLOCKED_RESIN` with `blocked_reason` `NO_QUALIFIED_RESIN_LOT` instead of
    `READY_TO_SCHEDULE`, and the releasing request still succeeds with HTTP
    200." Both encodings are therefore faithful, and what the document does pin
    without contradiction is *which* condition is reported. That is what this
    helper checks, returning True when the hard encoding was used.
    """
    body = response.json()
    if response.status_code == 200:
        data = body["data"]
        assert data["status"] == soft_status, (
            f"the soft encoding of this precondition moves the order to "
            f"{soft_status}; got {data['status']!r}"
        )
        assert data["blocked_reason"] == soft_reason
        return False
    validate_error(response, hard_error_id, 409)
    return True


class TestProductionOrderReleaseLadder:
    """Release evaluates site posture, then tool availability, then resin."""

    def test_a_release_that_passes_all_three_gates_zeroes_the_cost_roll_up(
        self, api, planner_headers
    ):
        """The healthy order reaches READY_TO_SCHEDULE with every cost at zero.

        PRD.md section 3.3: "When all five hold the order moves `DRAFT` to
        `READY_TO_SCHEDULE`, `blocked_reason` is cleared to null, the cost
        roll-up is recomputed (all zeros at this point, since no charge is
        consumed and no cycle demoulded), and `version` advances by 1."

        PRD.md section 3.3: "It starts in `DRAFT` with `completed_qty` and
        `scrapped_qty` at 0, all four cost fields at 0, `unit_cost_cents` null
        and `version` 1."

        Design: Corner/endpoints/ep_production_order_release_precondition_ladder_frozen_then_mold_then_resin
        """
        ctx = _p3_release_ladder(api)

        released = validate_success(
            api.release_production_order(ctx["order_healthy"]["id"], planner_headers)
        )

        assert released["status"] == "READY_TO_SCHEDULE"
        assert released.get("blocked_reason") is None
        assert released["version"] == 2
        assert_money_equals(released["material_cost_cents"], 0, "material_cost_cents")
        assert_money_equals(
            released["oven_energy_cost_cents"], 0, "oven_energy_cost_cents"
        )
        assert_money_equals(released["overhead_cents"], 0, "overhead_cents")
        assert_money_equals(released["total_cost_cents"], 0, "total_cost_cents")
        # PRD.md section 3.3 says `unit_cost_cents` is null while no hull is
        # completed, but section 2.8 lists ProductionOrder's money fields as
        # "all integers defaulting to 0". Both readings are faithful, so both
        # are accepted here.
        assert released.get("unit_cost_cents") in (0, None)

    def test_a_missing_tool_is_reported_ahead_of_a_missing_qualified_lot(
        self, api, planner_headers, admin_headers
    ):
        """With neither tool nor lot, the tool gate is the one that answers.

        PRD.md section 3.3: "Five preconditions are evaluated: the order is
        `DRAFT`; `ordered_qty` is at least 1; the target site's `posture` is not
        `FROZEN`, otherwise `ERR_WAREHOUSE_FROZEN` (HTTP 409); at least one
        mould exists for the order's hull model in `status` `AVAILABLE`,
        `IN_CYCLE` or `MAINTENANCE`, otherwise `ERR_NO_ELIGIBLE_MOLD` (HTTP
        409); and at least one resin lot qualifies for the model, otherwise
        `ERR_RESIN_INSUFFICIENT` (HTTP 409)."

        PRD.md section 3.2: "the lot's `melt_index_g10min` lies inside the
        model's band with *both* bounds inclusive, from `min_melt_index_g10min`
        to `max_melt_index_g10min`".

        Design: Corner/endpoints/ep_production_order_release_precondition_ladder_frozen_then_mold_then_resin
        """
        ctx = _p3_release_ladder(api)

        refused = api.release_production_order(
            ctx["order_no_tool"]["id"], planner_headers
        )

        validate_error(refused, ApiErrorId.NO_ELIGIBLE_MOLD, 409)
        unchanged = validate_success(
            api.get_production_order(ctx["order_no_tool"]["id"], admin_headers)
        )
        assert unchanged["status"] == "DRAFT", (
            "a refused release performs no partial write"
        )
        assert unchanged["version"] == 1

    def test_a_frozen_site_is_reported_ahead_of_both_other_gates(
        self, api, planner_headers, admin_headers
    ):
        """The site condition wins over the missing tool and the missing lot.

        PRD.md section 3.3: "The warehouse test is evaluated *before* the resin
        test, so an order that is both frozen-out and resin-starved lands in
        `BLOCKED_WAREHOUSE`."

        PRD.md section 3.3: "Five preconditions are evaluated: the order is
        `DRAFT`; `ordered_qty` is at least 1; the target site's `posture` is not
        `FROZEN`, otherwise `ERR_WAREHOUSE_FROZEN` (HTTP 409); at least one
        mould exists for the order's hull model in `status` `AVAILABLE`,
        `IN_CYCLE` or `MAINTENANCE`, otherwise `ERR_NO_ELIGIBLE_MOLD` (HTTP
        409); and at least one resin lot qualifies for the model, otherwise
        `ERR_RESIN_INSUFFICIENT` (HTTP 409)."

        PRD.md section 3.7: "**Posture** is derived, never stored independently:
        `posture` is `FROZEN` when `utilization_pct` is at or above
        `frozen_threshold_pct`".

        Design: Corner/endpoints/ep_production_order_release_precondition_ladder_frozen_then_mold_then_resin
        """
        ctx = _p3_release_ladder(api)
        site = validate_success(
            api.get_warehouse(ctx["frozen_site_id"], planner_headers)
        )
        assert site["posture"] == "FROZEN", (
            "the single stored hull fills this site exactly, so it must be frozen "
            "before the release is attempted"
        )

        response = api.release_production_order(
            ctx["order_frozen_site"]["id"], planner_headers
        )

        was_hard = _p3_assert_reported_condition(
            response,
            ApiErrorId.WAREHOUSE_FROZEN,
            "BLOCKED_WAREHOUSE",
            "WAREHOUSE_FROZEN",
        )
        after = validate_success(
            api.get_production_order(ctx["order_frozen_site"]["id"], admin_headers)
        )
        if was_hard:
            assert after["status"] == "DRAFT", (
                "a refused release performs no partial write"
            )
            assert after["version"] == 1
        else:
            assert after["status"] == "BLOCKED_WAREHOUSE"
            assert after["blocked_reason"] == "WAREHOUSE_FROZEN"

    def test_the_resin_gate_only_surfaces_once_a_tool_exists(
        self, api, planner_headers, admin_headers
    ):
        """Registering a tool for the starved model moves the answer to resin.

        PRD.md section 3.3: "Five preconditions are evaluated: the order is
        `DRAFT`; `ordered_qty` is at least 1; the target site's `posture` is not
        `FROZEN`, otherwise `ERR_WAREHOUSE_FROZEN` (HTTP 409); at least one
        mould exists for the order's hull model in `status` `AVAILABLE`,
        `IN_CYCLE` or `MAINTENANCE`, otherwise `ERR_NO_ELIGIBLE_MOLD` (HTTP
        409); and at least one resin lot qualifies for the model, otherwise
        `ERR_RESIN_INSUFFICIENT` (HTTP 409)."

        PRD.md section 3.2: "The qualified lot count for a model is the number
        of lots satisfying that predicate."

        Design: Corner/endpoints/ep_production_order_release_precondition_ladder_frozen_then_mold_then_resin
        """
        ctx = _p3_release_ladder(api)
        validate_error(
            api.release_production_order(ctx["order_no_tool"]["id"], planner_headers),
            ApiErrorId.NO_ELIGIBLE_MOLD,
            409,
        )
        get_success_data(
            api.create_mold(
                mold_payload(ctx["starved_model"]["id"], mold_code="MLD-CD-REL-T3"),
                admin_headers,
            )
        )

        response = api.release_production_order(
            ctx["order_no_tool"]["id"], planner_headers
        )

        was_hard = _p3_assert_reported_condition(
            response,
            ApiErrorId.RESIN_INSUFFICIENT,
            "BLOCKED_RESIN",
            "NO_QUALIFIED_RESIN_LOT",
        )
        after = validate_success(
            api.get_production_order(ctx["order_no_tool"]["id"], admin_headers)
        )
        if was_hard:
            assert after["status"] == "DRAFT"
            assert after["version"] == 1
        else:
            assert after["status"] == "BLOCKED_RESIN"
            assert after["blocked_reason"] == "NO_QUALIFIED_RESIN_LOT"


class TestClaimReturnToQueue:
    """One backward edge resets both axes and re-orders the approve ladder."""

    @staticmethod
    def _waived_claim():
        """A claim UNDER_REVIEW whose storage finding a PlantAdmin has waived."""
        baseline = create_plant_baseline()
        cyc, chg = _p3_identity_overrides(baseline)
        return setup_claim_storage_waived(
            baseline=baseline, cycle_overrides=cyc, charge_overrides=chg
        )

    def test_return_to_queue_revokes_the_waiver_and_clears_both_cleared_fields(
        self, api, warranty_agent_headers
    ):
        """Both axes move at once and the two frozen fields go back to null.

        PRD.md section 3.9: "**Returning a claim to the queue**, with a
        `return_note` recording why, is the documented backward edge and it
        resets both axes at once. `claim_status` moves `UNDER_REVIEW` back to
        `SUBMITTED`, and whichever of `GUIDANCE_VERIFIED`, `GUIDANCE_VIOLATED`
        or `WAIVED` the storage axis held returns to `NOT_STARTED`, revoking any
        administrative waiver. Both `months_in_service` and
        `storage_description` are cleared to null, so a second pass through
        review re-ages the claim against the clock as it then stands and must
        decide the storage axis afresh."

        PRD.md section 3.9: "A `WarrantyClaim` carries **two state machines on
        the same row**, and they advance independently."

        PRD.md section 2.10: "A hull model holds a two-bucket ledger in which
        `warranty_reserve_cents` plus `warranty_paid_cents` always equals the
        immutable `initial_warranty_reserve_cents`".

        Design: Corner/endpoints/ep_warranty_return_to_queue_revokes_the_waiver_and_resets_the_other_axis
        """
        ctx = self._waived_claim()
        before = ctx["warranty_claim"]
        assert before["claim_status"] == "UNDER_REVIEW"
        assert before["storage_review_status"] == "WAIVED"
        assert before["months_in_service"] == 0

        returned = validate_success(
            api.return_claim_to_queue(
                ctx["warranty_claim_id"],
                return_to_queue_payload("reassigning to a senior adjudicator"),
                warranty_agent_headers,
            )
        )

        assert returned["claim_status"] == "SUBMITTED"
        assert returned["storage_review_status"] == "NOT_STARTED"
        assert returned.get("storage_description") is None
        assert returned.get("months_in_service") is None
        assert returned["version"] > before["version"]

        model = validate_success(
            api.get_product_model(ctx["product_model_id"], warranty_agent_headers)
        )
        assert_money_equals(
            model["warranty_reserve_cents"], 500000, "warranty_reserve_cents"
        )
        assert_money_equals(model["warranty_paid_cents"], 0, "warranty_paid_cents")
        assert_warranty_reserve_conserved(model)

    def test_the_approve_ladder_reports_the_claim_axis_not_the_storage_axis(
        self, api, warranty_agent_headers, admin_headers
    ):
        """Both approve guards now fail, and the adjudication axis answers first.

        PRD.md section 3.9: "In order: the claim must be `UNDER_REVIEW`
        (`ERR_CLAIM_INVALID_STATE`); the storage axis must be
        `GUIDANCE_VERIFIED` or `WAIVED`, otherwise
        `ERR_STORAGE_REVIEW_INCOMPLETE` (HTTP 409) — a claim still `NOT_STARTED`
        or standing at an unwaived `GUIDANCE_VIOLATED` is refused before pricing
        begins; the version check follows".

        PRD.md section 3.9: "`claim_status` moves `UNDER_REVIEW` back to
        `SUBMITTED`, and whichever of `GUIDANCE_VERIFIED`, `GUIDANCE_VIOLATED`
        or `WAIVED` the storage axis held returns to `NOT_STARTED`, revoking any
        administrative waiver."

        PRD.md section 3.9: "**Approving** is the only path that spends money".

        Design: Corner/endpoints/ep_warranty_return_to_queue_revokes_the_waiver_and_resets_the_other_axis
        """
        ctx = self._waived_claim()
        get_success_data(
            api.return_claim_to_queue(
                ctx["warranty_claim_id"],
                return_to_queue_payload("reassigning to a senior adjudicator"),
                warranty_agent_headers,
            )
        )
        model_version = product_model_version(ctx["product_model_id"])

        refused = api.approve_warranty_claim(
            ctx["warranty_claim_id"],
            approve_claim_payload(model_version),
            warranty_agent_headers,
        )

        validate_error(refused, ApiErrorId.CLAIM_INVALID_STATE, 409)
        claim = validate_success(
            api.get_warranty_claim(ctx["warranty_claim_id"], warranty_agent_headers)
        )
        assert claim["claim_status"] == "SUBMITTED"
        assert claim.get("net_payout_cents") is None
        assert claim.get("payout_basis") is None

        model = validate_success(
            api.get_product_model(ctx["product_model_id"], admin_headers)
        )
        assert model["version"] == model_version, (
            "a refused approval spends nothing and mutates nothing"
        )
        assert_money_equals(
            model["warranty_reserve_cents"], 500000, "warranty_reserve_cents"
        )
        assert_warranty_reserve_conserved(model)
