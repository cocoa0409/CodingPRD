"""Concurrency tokens, version scoping and immediate read-your-writes visibility.

Exactly two write endpoints take a concurrency token, and both take it because
the parent they attach to legitimately accepts an unbounded number of children:
`POST /selections` carries `expected_duty_application_version` and
`POST /kit-allocations` carries `expected_repair_kit_version`.  The checks below
make each token genuinely stale by performing a real intervening write that
advances the parent, then replay the observation the client no longer holds and
show the rejected request left nothing behind.

The rest of the file pins the version bookkeeping and the visibility promise.  A
child write increments its own `version` and the `version` of the parent it
declared, and leaves every other candidate parent alone.  A lot's
`committed_build_count` is a recount, not a running tally, so it survives a
second build order and a scrap-driven shortage.  And because the system uses
immediate consistency, the cascaded and derived values are already in the body
of the request that caused them - a client never has to read again to see them.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_version_incremented,
    assertions,
    constants as K,
    factories as F,
    fixtures as X,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    APPLICATION_ENGINEER,
    HYDRAULIC_APPROVER,
    PRODUCTION_PLANNER,
    QUALITY_INSPECTOR,
)


# ─────────────────────────────────────────────────────────────────────────────
# The enquiry concurrency token
# ─────────────────────────────────────────────────────────────────────────────
class TestStaleEnquiryToken:
    """An enquiry accepts many selections, so the token is the only guard."""

    @pytest.fixture
    def sized_once(self, api):
        """One enquiry already sized once, so the client's first token is behind.

        Creating the first selection increments the enquiry's `version` by 1 even
        though its `status` is unchanged, which is exactly what makes the
        version observed at creation time stale.
        """
        ctx = X.setup_draft_selection(api)
        assert ctx["duty_at_create"]["version"] == 1
        assert ctx["duty"]["version"] == 2
        assert ctx["duty"]["status"] == "OPEN"
        return ctx

    def test_stale_expected_duty_application_version_on_selection_create_returns_412(
        self, api, sized_once
    ):
        """Replaying the version observed before the first sizing is refused outright.

        The enquiry was read at `version` 1, then a selection was created
        against it, which moved it to `version` 2.  A second sizing request that
        still carries `expected_duty_application_version` of 1 does not equal
        the enquiry's current `version`, so the create is rejected with
        `ERR_STALE_DUTY_APPLICATION_VERSION`.  The rejection is a complete
        no-op: only the first selection exists, and the enquiry is still at
        `version` 2 and still `OPEN`.

        Design: Corner/cross_cutting_complexity_layers/stale_expected_duty_application_version_on_selection_create_returns_412
        """
        duty_id = sized_once["duty"]["id"]

        response = api.create_selection(
            F.selection_payload(
                duty_id,
                sized_once["model"]["id"],
                sized_once["config"]["id"],
                sized_once["duty_at_create"]["version"],
            ),
            APPLICATION_ENGINEER,
        )
        validate_error(response, ApiErrorId.STALE_DUTY_APPLICATION_VERSION)

        rows, meta = validate_paginated(
            api.list_selections(APPLICATION_ENGINEER, duty_application_id=duty_id)
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [sized_once["selection"]["id"]]

        untouched = X.reread_duty_application(api, duty_id)
        assert untouched["version"] == 2
        assert untouched["status"] == "OPEN"

    def test_the_freshly_read_enquiry_version_sizes_a_second_selection(
        self, api, sized_once
    ):
        """The token returned by reading the enquiry is the one that works.

        The `version` returned by reading a single enquiry is the token to send,
        so the same request that failed on the stale value succeeds once it
        carries 2.  The new selection lands in `DRAFT` with
        `proposed_by_user_id` and `approved_by_user_id` both null, and the
        enquiry advances again to `version` 3 while staying `OPEN`, because an
        enquiry accepts more than one selection over its life.

        Design: Corner/cross_cutting_complexity_layers/stale_expected_duty_application_version_on_selection_create_returns_412
        """
        duty_id = sized_once["duty"]["id"]

        response = api.create_selection(
            F.selection_payload(
                duty_id,
                sized_once["model"]["id"],
                sized_once["config"]["id"],
                sized_once["duty"]["version"],
            ),
            APPLICATION_ENGINEER,
        )
        second = validate_success(response, 201)
        assert second["status"] == "DRAFT"
        assert second["proposed_by_user_id"] is None
        assert second["approved_by_user_id"] is None

        duty = X.reread_duty_application(api, duty_id)
        assert duty["version"] == 3
        assert duty["status"] == "OPEN"

        _, meta = validate_paginated(
            api.list_selections(APPLICATION_ENGINEER, duty_application_id=duty_id)
        )
        assert meta["total_count"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# The repair kit concurrency token
# ─────────────────────────────────────────────────────────────────────────────
class TestStaleRepairKitToken:
    """Receipts bump the kit's version, so a token taken before one is behind."""

    @pytest.fixture
    def stocked_kit(self, api):
        """A kit stocked by two receipts, holding the token from the first.

        Receipts, issues, consumptions and cascaded releases all move the kit's
        stock counters and bump its `version`, so the version observed after the
        first receipt of six units no longer describes the kit once a second
        receipt of four has landed.
        """
        ctx = X.setup_planned_build_order(api)
        kit = X.create_repair_kit(api, ctx["model"]["id"])
        after_first = get_success_data(
            api.receive_repair_kit_stock(
                kit["id"], F.kit_receipt_payload(6), PRODUCTION_PLANNER
            )
        )
        after_second = get_success_data(
            api.receive_repair_kit_stock(
                kit["id"], F.kit_receipt_payload(4), PRODUCTION_PLANNER
            )
        )
        assert after_first["version"] == 2
        assert after_second["version"] == 3
        assert after_second["qty_on_hand"] == 10
        ctx["kit_after_first_receipt"] = after_first
        ctx["kit"] = after_second
        return ctx

    def test_stale_expected_repair_kit_version_on_allocation_returns_412(
        self, api, stocked_kit
    ):
        """A reservation quoting the pre-restock version moves no units at all.

        `expected_repair_kit_version` of 2 does not equal the kit's current
        `version` of 3, so the reservation is rejected with
        `ERR_STALE_REPAIR_KIT_VERSION`, forcing the writer to re-read the
        counters before committing stock.  Nothing moved out of `qty_on_hand`
        into `qty_reserved`: the kit still holds ten units on hand, none
        reserved, and its `version` is still 3.

        Design: Corner/cross_cutting_complexity_layers/stale_expected_repair_kit_version_on_allocation_returns_412
        """
        kit = stocked_kit["kit"]

        response = api.create_kit_allocation(
            F.kit_allocation_payload(
                kit["id"],
                stocked_kit["build_order"]["id"],
                2,
                stocked_kit["kit_after_first_receipt"]["version"],
            ),
            PRODUCTION_PLANNER,
        )
        validate_error(response, ApiErrorId.STALE_REPAIR_KIT_VERSION)

        untouched = X.reread_repair_kit(api, kit["id"])
        assert untouched["qty_on_hand"] == 10
        assert untouched["qty_reserved"] == 0
        assert untouched["version"] == 3
        assertions.assert_kit_units_conserved(untouched)

        _, meta = validate_paginated(
            api.list_kit_allocations(PRODUCTION_PLANNER, repair_kit_id=kit["id"])
        )
        assert meta["total_count"] == 0

    def test_the_freshly_read_kit_version_reserves_the_units(self, api, stocked_kit):
        """With the current token the same reservation commits stock immediately.

        The `version` returned by reading a single repair kit is the token to
        send, so quoting 3 succeeds.  A reservation created this way is
        `RESERVED` with `selected_by` set to `EXPLICIT`, and creating it moves
        the two requested units out of the kit's `qty_on_hand` and into its
        `qty_reserved`, incrementing the kit's `version` to 4.

        Design: Corner/cross_cutting_complexity_layers/stale_expected_repair_kit_version_on_allocation_returns_412
        """
        kit = stocked_kit["kit"]

        response = api.create_kit_allocation(
            F.kit_allocation_payload(
                kit["id"], stocked_kit["build_order"]["id"], 2, kit["version"]
            ),
            PRODUCTION_PLANNER,
        )
        allocation = validate_success(response, 201)
        assert allocation["status"] == "RESERVED"
        assert allocation["selected_by"] == "EXPLICIT"
        assert allocation["requested_qty"] == 2
        assert allocation["repair_kit_id"] == kit["id"]

        moved = X.reread_repair_kit(api, kit["id"])
        assert moved["qty_on_hand"] == 8
        assert moved["qty_reserved"] == 2
        assert moved["version"] == 4
        assert_version_incremented(moved["version"], kit["version"])
        assertions.assert_kit_units_conserved(moved)


# ─────────────────────────────────────────────────────────────────────────────
# Version bookkeeping is scoped to the row and to the declared parent
# ─────────────────────────────────────────────────────────────────────────────
class TestVersionScoping:
    """A child write touches itself and the parent it named, and nothing else."""

    @pytest.fixture
    def two_open_enquiries(self, api):
        """One model and configuration, two `OPEN` enquiries both at version 1.

        Having two candidate parents is what makes "only the declared one"
        observable: the selection names the first enquiry and never mentions the
        second.
        """
        world = X.setup_master_data(api)
        world["declared_duty"] = X.create_duty_application(api)
        world["other_duty"] = X.create_duty_application(api)
        assert world["declared_duty"]["version"] == 1
        assert world["other_duty"]["version"] == 1
        return world

    def test_child_writes_increment_the_row_version_and_only_the_declared_parent_version(
        self, api, two_open_enquiries
    ):
        """Sizing against one enquiry leaves the other enquiry and the model at 1.

        Creating the selection increments the enquiry's `version` by 1 even
        though its `status` is unchanged, so the declared enquiry moves 1 to 2
        while the selection itself begins at 1.  Nothing else is a parent of
        this write: the second `OPEN` enquiry is still at `version` 1 and still
        `OPEN`, and the hydraulic model the selection chose is untouched at
        `version` 1 and still `ORDERABLE`.  The material and seal configuration
        is immutable after creation, so it carries neither `updated_at` nor
        `version` at all - the fields are absent rather than present and null.

        Design: Corner/cross_cutting_complexity_layers/child_writes_increment_the_row_version_and_only_the_declared_parent_version
        """
        world = two_open_enquiries
        declared_id = world["declared_duty"]["id"]
        other_id = world["other_duty"]["id"]

        response = api.create_selection(
            F.selection_payload(
                declared_id,
                world["model"]["id"],
                world["config"]["id"],
                world["declared_duty"]["version"],
            ),
            APPLICATION_ENGINEER,
        )
        selection = validate_success(response, 201)
        assert selection["version"] == 1
        assert selection["duty_application_id"] == declared_id

        declared = X.reread_duty_application(api, declared_id)
        assert declared["version"] == 2
        assert declared["status"] == "OPEN"
        assert_version_incremented(
            declared["version"], world["declared_duty"]["version"]
        )

        other = X.reread_duty_application(api, other_id)
        assert other["version"] == 1
        assert other["status"] == "OPEN"

        model = X.reread_pump_model(api, world["model"]["id"])
        assert model["version"] == 1
        assert model["status"] == "ORDERABLE"

        config = get_success_data(
            api.get_material_seal_config(world["config"]["id"], APPLICATION_ENGINEER)
        )
        assertions.assert_common_fields(config, versioned=False)

    def test_propose_moves_only_the_selection_and_approve_also_moves_the_enquiry(
        self, api, two_open_enquiries
    ):
        """Each hop bumps the selection; only the approval reaches back up the chain.

        Proposing stamps `proposed_by_user_id` on the selection and moves it
        `DRAFT -> PROPOSED`, which is a mutation of the selection alone, so the
        selection reads `version` 2 while the declared enquiry stays at the 2 it
        reached when the selection was created.  Approval then drives the parent
        enquiry `OPEN -> SELECTION_LOCKED` with its `version` incremented, so
        the selection reaches `version` 3 and the declared enquiry reaches 3.
        Throughout, the second enquiry - never named by any of the three
        requests - stays at `version` 1 and `OPEN`.

        Design: Corner/cross_cutting_complexity_layers/child_writes_increment_the_row_version_and_only_the_declared_parent_version
        """
        world = two_open_enquiries
        declared_id = world["declared_duty"]["id"]
        other_id = world["other_duty"]["id"]

        selection = get_success_data(
            api.create_selection(
                F.selection_payload(
                    declared_id,
                    world["model"]["id"],
                    world["config"]["id"],
                    world["declared_duty"]["version"],
                ),
                APPLICATION_ENGINEER,
            )
        )

        proposed = validate_success(
            api.propose_selection(selection["id"], APPLICATION_ENGINEER), 200
        )
        assert proposed["status"] == "PROPOSED"
        assert proposed["version"] == 2
        assert X.reread_duty_application(api, declared_id)["version"] == 2
        assert X.reread_duty_application(api, other_id)["version"] == 1

        approved = validate_success(
            api.approve_selection(selection["id"], HYDRAULIC_APPROVER), 200
        )
        assert approved["status"] == "APPROVED"
        assert approved["version"] == 3

        declared = X.reread_duty_application(api, declared_id)
        assert declared["version"] == 3
        assert declared["status"] == "SELECTION_LOCKED"

        other = X.reread_duty_application(api, other_id)
        assert other["version"] == 1
        assert other["status"] == "OPEN"


# ─────────────────────────────────────────────────────────────────────────────
# The committed build count is a recount, not a running tally
# ─────────────────────────────────────────────────────────────────────────────
class TestCommittedBuildCountReconciliation:
    """Two orders on one lot, then a scrap that can no longer cover them both."""

    @pytest.fixture
    def lot_with_two_orders(self, api):
        """An ACCEPTED lot of four pieces carrying two PLANNED build orders.

        The second order is opened after the logical clock has moved on, so the
        newest order bound to the lot by `created_at` is unambiguous.
        """
        ctx = X.setup_planned_build_order(api)
        second_duty = X.create_duty_application(api)
        second_selection = get_success_data(
            api.create_selection(
                F.selection_payload(
                    second_duty["id"],
                    ctx["model"]["id"],
                    ctx["config"]["id"],
                    second_duty["version"],
                ),
                APPLICATION_ENGINEER,
            )
        )
        get_success_data(
            api.propose_selection(second_selection["id"], APPLICATION_ENGINEER)
        )
        get_success_data(
            api.approve_selection(second_selection["id"], HYDRAULIC_APPROVER)
        )
        X.set_clock(api, "2026-08-02T00:00:00Z")
        ctx["second_build_order"] = get_success_data(
            api.create_build_order(
                F.build_order_payload(second_selection["id"], ctx["lot"]["id"]),
                PRODUCTION_PLANNER,
            )
        )
        return ctx

    def test_committed_build_count_reconciles_after_a_second_build_order_and_a_casting_shortage(
        self, api, lot_with_two_orders
    ):
        """Two commitments, then a scrap of three pieces strands exactly one order.

        Opening each build order increments the lot's `committed_build_count` by
        1, so the lot carries two commitments against four accepted pieces.  A
        major defect on three pieces is then dispositioned `SCRAP`, and the
        ledger is a full recompute from the defect rows: `qty_scrapped` becomes
        3, `qty_rework_pending` stays 0 and `qty_accepted` falls to 1.  One
        accepted piece is below the larger of 1 and the two committed builds, so
        the lot is driven to `QUARANTINED`, and exactly one build order is
        stranded - the newest non-terminal order bound to that lot - which moves
        to `CASTING_SHORT` while the older order stays `PLANNED`.  Because
        `committed_build_count` is the count of build orders bound to the lot
        whose status is neither `CLOSED` nor `CASTING_SHORT`, the counter lands
        back on 1, and the conservation identity still holds with four poured
        pieces split as 1 accepted, 0 in weld repair and 3 written off.

        Design: Corner/cross_cutting_complexity_layers/committed_build_count_reconciles_after_a_second_build_order_and_a_casting_shortage
        """
        ctx = lot_with_two_orders
        lot_id = ctx["lot"]["id"]
        first_order_id = ctx["build_order"]["id"]
        second_order_id = ctx["second_build_order"]["id"]

        before = X.reread_casting_lot(api, lot_id)
        assert before["committed_build_count"] == 2
        assert before["qty_poured"] == 4
        assert before["qty_accepted"] == 4
        assert before["qty_scrapped"] == 0
        assert before["status"] == "ACCEPTED"
        assertions.assert_piece_ledger_conserved(before)

        defect = X.report_defect(
            api,
            lot_id,
            headers=ctx["foundry_headers"],
            defect_type="SHRINKAGE",
            severity="MAJOR",
            affected_qty=3,
        )

        response = api.disposition_casting_defect(
            defect["id"], F.disposition_payload("SCRAP"), QUALITY_INSPECTOR
        )
        dispositioned = validate_success(response, 200)
        assert dispositioned["status"] == "DISPOSITIONED_SCRAP"
        assert dispositioned["disposition"] == "SCRAP"

        lot = X.reread_casting_lot(api, lot_id)
        assert lot["qty_scrapped"] == 3
        assert lot["qty_rework_pending"] == 0
        assert lot["qty_accepted"] == 1
        assert lot["status"] == "QUARANTINED"
        assert lot["committed_build_count"] == 1
        assert lot["qty_poured"] == (
            lot["qty_accepted"] + lot["qty_rework_pending"] + lot["qty_scrapped"]
        )
        assertions.assert_piece_ledger_conserved(lot)

        stranded = X.reread_build_order(api, second_order_id)
        assert stranded["status"] == "CASTING_SHORT"

        survivor = X.reread_build_order(api, first_order_id)
        assert survivor["status"] == "PLANNED"


# ─────────────────────────────────────────────────────────────────────────────
# Immediate consistency: the writing response already carries the outcome
# ─────────────────────────────────────────────────────────────────────────────
class TestReadYourWritesOnPourCascade:
    """Recording a pour reports the ledger, the tooling and the model at once."""

    def test_pour_cascade_and_derived_fields_are_visible_in_the_same_request(self, api):
        """One pour withdraws the tooling and constrains the model inside the response.

        The pattern's `wear_threshold` is 1, so the single pour that increments
        `pours_since_refurb` to 1 takes `wear_index` to 1 as well and reaches
        the threshold.  The create response itself is already complete: the lot
        is `POURED` with `qty_scrapped` and `qty_rework_pending` at 0,
        `qty_accepted` equal to `qty_poured`, and `committed_build_count` at 0.
        Reading the pattern straight afterwards shows the repositioning has
        already happened - the pattern moved `QUALIFIED -> WORN` - and because
        that leaves the model with no `QUALIFIED` pattern at all, the model is
        already `PATTERN_CONSTRAINED` rather than `ORDERABLE`.  Clients never
        poll for reconciliation.

        Design: Corner/consistency_model/pour_cascade_and_derived_fields_are_visible_in_the_same_request
        """
        world = X.setup_master_data(api, pattern={"wear_threshold": 1})
        pattern = world["pattern"]
        assert pattern["status"] == "QUALIFIED"
        assert pattern["pours_since_refurb"] == 0
        assert pattern["wear_index"] == 0
        assert world["model"]["status"] == "ORDERABLE"

        response = api.create_casting_lot(
            F.casting_lot_payload(pattern["id"], world["foundry"]["id"]),
            world["foundry_headers"],
        )
        lot = validate_success(response, 201)
        assert lot["status"] == "POURED"
        assert lot["qty_poured"] == 4
        assert lot["qty_accepted"] == 4
        assert lot["qty_scrapped"] == 0
        assert lot["qty_rework_pending"] == 0
        assert lot["committed_build_count"] == 0
        assertions.assert_piece_ledger_conserved(lot)

        worn = X.reread_pattern_asset(api, pattern["id"])
        assert worn["pours_since_refurb"] == 1
        assert worn["defect_pours_since_refurb"] == 0
        assert worn["wear_index"] == 1
        assert worn["status"] == "WORN"
        assertions.assert_wear_index(worn)
        assert_version_incremented(worn["version"], pattern["version"])

        constrained = X.reread_pump_model(api, world["model"]["id"])
        assert constrained["status"] == "PATTERN_CONSTRAINED"


class TestReadYourWritesOnSelectionSizing:
    """Everything on the selection is computed, and computed before the reply."""

    @pytest.fixture
    def sizing_request(self, api):
        """An `OPEN` enquiry at 265.0 m3/h and 74.0 m against HSC-14 and MSC-CI-P11."""
        world = X.setup_master_data(api)
        world["duty"] = X.create_duty_application(api)
        return world

    def test_selection_computed_fields_are_present_in_the_create_response_not_only_on_reread(
        self, api, sizing_request
    ):
        """The 201 body already carries the trim, the curve and the suction certification.

        The sizing request is compact - the engineer names an enquiry, a model, a
        configuration and the concurrency token - and everything else on the
        selection is computed.  All of it is in the response to that create: the
        impeller trims to 350.3 mm, the reconstructed curve predicts 73.97 m at
        80.96 percent efficiency and 65.96 kW absorbed against a 72.56 kW motor
        minimum, and the suction chain runs from a 3.52 m catalogue figure
        through a 1.48 m provisional margin and the 1.25 safety factor to a
        4.40 m certified requirement leaving a 0.60 m reported margin.  The
        selection lands in `DRAFT` with both user stamps null.

        Design: Corner/consistency_model/selection_computed_fields_are_present_in_the_create_response_not_only_on_reread
        """
        world = sizing_request

        response = api.create_selection(
            F.selection_payload(
                world["duty"]["id"],
                world["model"]["id"],
                world["config"]["id"],
                world["duty"]["version"],
            ),
            APPLICATION_ENGINEER,
        )
        created = validate_success(response, 201)

        assert created["status"] == "DRAFT"
        assert created["proposed_by_user_id"] is None
        assert created["approved_by_user_id"] is None

        assert created["trimmed_impeller_diameter_mm"] == pytest.approx(
            K.SEL_1001_TRIMMED_DIAMETER_MM, abs=0.01
        )
        assert created["diameter_ratio"] == pytest.approx(
            K.SEL_1001_TRIMMED_DIAMETER_MM / K.MODEL_HSC_14["max_impeller_diameter_mm"],
            abs=0.0001,
        )
        assert created["predicted_head_m"] == pytest.approx(
            K.SEL_1001_PREDICTED_HEAD_M, abs=0.01
        )
        assert created["predicted_efficiency_pct"] == pytest.approx(
            K.SEL_1001_PREDICTED_EFFICIENCY_PCT, abs=0.01
        )
        assert created["predicted_shaft_power_kw"] == pytest.approx(65.96, abs=0.01)
        assert created["min_motor_kw"] == pytest.approx(72.56, abs=0.01)
        assert created["npshr_catalog_m"] == pytest.approx(
            K.SEL_1001_NPSHR_CATALOG_M, abs=0.01
        )
        assert created["npsh_provisional_margin_m"] == pytest.approx(
            K.SEL_1001_NPSH_PROVISIONAL_MARGIN_M, abs=0.01
        )
        assert created["npsh_safety_factor"] == pytest.approx(
            K.SEL_1001_NPSH_SAFETY_FACTOR, abs=0.0001
        )
        assert created["npshr_certified_m"] == pytest.approx(
            K.SEL_1001_NPSHR_CERTIFIED_M, abs=0.01
        )
        assert created["npsh_margin_m"] == pytest.approx(
            K.SEL_1001_NPSH_MARGIN_M, abs=0.01
        )

    def test_an_immediate_reread_of_the_selection_repeats_every_computed_value(
        self, api, sizing_request
    ):
        """A fresh read agrees with the create response field for field.

        The computed values are not filled in by a later reconciliation pass, so
        `GET /selections/{id}` issued straight after the create returns exactly
        what the create returned for every derived field.  The enquiry read at
        the same moment is already at `version` 2, because creating the
        selection increments the enquiry's `version` by 1 even though its
        `status` is unchanged.

        Design: Corner/consistency_model/selection_computed_fields_are_present_in_the_create_response_not_only_on_reread
        """
        world = sizing_request
        computed_fields = (
            "trimmed_impeller_diameter_mm",
            "diameter_ratio",
            "predicted_head_m",
            "predicted_efficiency_pct",
            "predicted_shaft_power_kw",
            "min_motor_kw",
            "npshr_catalog_m",
            "npsh_provisional_margin_m",
            "npsh_safety_factor",
            "npshr_certified_m",
            "npsh_margin_m",
        )

        created = get_success_data(
            api.create_selection(
                F.selection_payload(
                    world["duty"]["id"],
                    world["model"]["id"],
                    world["config"]["id"],
                    world["duty"]["version"],
                ),
                APPLICATION_ENGINEER,
            )
        )

        reread = validate_success(
            api.get_selection(created["id"], APPLICATION_ENGINEER), 200
        )
        assert reread["id"] == created["id"]
        assert reread["status"] == "DRAFT"
        assert reread["version"] == created["version"]
        for field in computed_fields:
            assert reread[field] == pytest.approx(created[field], abs=0.0001), field

        duty = X.reread_duty_application(api, world["duty"]["id"])
        assert duty["version"] == 2
        assert duty["status"] == "OPEN"
