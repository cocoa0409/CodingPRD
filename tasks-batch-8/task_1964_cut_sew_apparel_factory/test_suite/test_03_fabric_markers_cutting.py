"""Markers, fabric reservation, and the cut room (PRD §3.5, §2.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_fabric_ledger_invariants,
    create_available_fabric_roll,
    create_fabric_roll_payload,
    create_marker_payload,
    create_production_order,
    create_style,
    get_success_data,
    plan_order,
    setup_style_with_approved_pack,
    validate_error,
    validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]
MATS = TEST_USERS["materials_planner_headers"]
CUTMGR = TEST_USERS["cutting_manager_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
ANY = TEST_USERS["any_headers"]


def _order_and_available_roll(order_qty=100, received_yards=41.3):
    """Style + order (no pack needed for marker creation) + QC-passed roll."""
    style = create_style()
    order = create_production_order(
        style["id"], PLANNER, size_quantities=[{"size": "M", "qty": order_qty}],
    )
    roll = create_available_fabric_roll(MATS, received_yards=received_yards)
    return style, order, roll


def _draft_marker(order_id, roll_id, length=40.0, pieces=100):
    return get_success_data(api_client.create_marker(
        create_marker_payload(
            production_order_id=order_id, fabric_roll_id=roll_id,
            marker_length_yards=length, planned_pieces=pieces,
        ),
        CUTMGR,
    ))


class TestMarkerUtilizationVariants:
    def test_marker_utilization_gross_vs_net(self):
        """PRD §3.5: "`utilization_gross_pct` is the face length as a
        percentage of the full `allocated_yards`, splice included;
        `utilization_net_pct` is the face length as a percentage of
        `allocated_yards` with the half-yard splice allowance removed".

        Design: Difficulty/dual_variant_calc/marker_utilization_gross_vs_net
        """
        _style, order, roll = _order_and_available_roll()
        marker = _draft_marker(order["id"], roll["id"])
        marker = get_success_data(api_client.approve_marker(
            marker["id"], {"expected_fabric_roll_version": roll["version"]}, CUTMGR,
        ))
        # allocated = round(40.0 * 1.02, 2) + 0.5 = 41.3
        assert marker["allocated_yards"] == pytest.approx(41.3, abs=1e-9)
        assert marker["utilization_gross_pct"] == pytest.approx(96.9, abs=1e-9)
        assert marker["utilization_net_pct"] == pytest.approx(98.0, abs=1e-9)
        assert marker["utilization_gross_pct"] != marker["utilization_net_pct"]

    def test_marker_approve_response_reflects_mutation_immediately(self):
        """PRD §4: "Operations that modify an existing resource — including
        every state-transition action, computed write, and decision endpoint —
        return 200 OK." and PRD §2.2: "Unless otherwise noted, operations that
        create or modify a resource will return the created or updated resource
        object in the data field."

        Design: Corner/endpoints/marker_approve_response_reflects_mutation_immediately
        """
        _style, order, roll = _order_and_available_roll()
        marker = _draft_marker(order["id"], roll["id"])
        resp = api_client.approve_marker(
            marker["id"], {"expected_fabric_roll_version": roll["version"]}, CUTMGR,
        )
        data = validate_success(resp, 200)
        assert data["status"] == "APPROVED"
        assert data["allocated_yards"] == pytest.approx(41.3, abs=1e-9)
        assert data["utilization_gross_pct"] == pytest.approx(96.9, abs=1e-9)
        assert data["utilization_net_pct"] == pytest.approx(98.0, abs=1e-9)
        assert data["version"] == marker["version"] + 1


    def test_marker_utilization_net_strictly_larger_with_positive_splice(self):
        """PRD §3.5: "so the net variant reports the same spread against net
        spread yards and is strictly larger whenever the splice allowance is
        positive."

        Design: Difficulty/dual_variant_calc/marker_utilization_gross_vs_net
        """
        _style, order, roll = _order_and_available_roll()
        marker = _draft_marker(order["id"], roll["id"], length=30.0, pieces=80)
        marker = get_success_data(api_client.approve_marker(
            marker["id"], {"expected_fabric_roll_version": roll["version"]}, CUTMGR,
        ))
        # allocated = round(30.0 * 1.02, 2) + 0.5 = 30.6 + 0.5 = 31.1
        assert marker["allocated_yards"] == pytest.approx(31.1, abs=1e-9)
        # gross = 30.0/31.1 = 96.5 ; net = 30.0/30.6 = 98.0
        assert marker["utilization_gross_pct"] == pytest.approx(96.5, abs=1e-9)
        assert marker["utilization_net_pct"] == pytest.approx(98.0, abs=1e-9)
        assert marker["utilization_net_pct"] > marker["utilization_gross_pct"]


class TestMarkerApproveGuards:
    def test_insufficient_fabric_rejected_at_approve(self):
        """PRD §3.5: "the roll's `available_yards` must be at least the
        computed allocation — equality is permitted — or the approval fails
        with `ERR_INSUFFICIENT_FABRIC` (HTTP 409)."

        Design: Corner/validations/insufficient_fabric_rejected_at_approve
        """
        _style, order, roll = _order_and_available_roll(received_yards=40.0)
        marker = _draft_marker(order["id"], roll["id"])
        resp = api_client.approve_marker(
            marker["id"], {"expected_fabric_roll_version": roll["version"]}, CUTMGR,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FABRIC)
        marker_after = get_success_data(api_client.get_marker(marker["id"], ANY))
        assert marker_after["status"] == "DRAFT"
        roll_after = get_success_data(api_client.get_fabric_roll(roll["id"], ANY))
        assert roll_after["allocated_yards"] == 0
        assert roll_after["available_yards"] == pytest.approx(40.0, abs=1e-9)

    def test_approve_marker_on_unqcd_roll_rejected(self):
        """PRD §3.5: "The referenced roll must be `AVAILABLE`, or the rejection
        is `ERR_ROLL_NOT_AVAILABLE` (HTTP 409)."

        Design: Corner/validations/approve_marker_on_unqcd_roll_rejected
        """
        style = create_style()
        order = create_production_order(
            style["id"], PLANNER, size_quantities=[{"size": "M", "qty": 100}],
        )
        roll = get_success_data(api_client.create_fabric_roll(
            create_fabric_roll_payload(), MATS,
        ))
        assert roll["status"] == "RECEIVED"
        marker = _draft_marker(order["id"], roll["id"])
        resp = api_client.approve_marker(
            marker["id"], {"expected_fabric_roll_version": roll["version"]}, CUTMGR,
        )
        validate_error(resp, ApiErrorId.ERR_ROLL_NOT_AVAILABLE)

    def test_marker_approve_state_beats_fiscal(self):
        """PRD §3.5: "The marker must be `DRAFT` — checked before any business
        rule — or the approval is rejected with `ERR_MARKER_NOT_DRAFT`
        (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/marker_approve_state_beats_fiscal
        """
        _style, order, roll = _order_and_available_roll()
        marker = _draft_marker(order["id"], roll["id"])
        get_success_data(api_client.approve_marker(
            marker["id"], {"expected_fabric_roll_version": roll["version"]}, CUTMGR,
        ))
        # Roll now has 0 available yards (fiscal would also fail); re-approve
        # the same marker with the fresh roll version so OCC passes.
        roll_now = get_success_data(api_client.get_fabric_roll(roll["id"], ANY))
        resp = api_client.approve_marker(
            marker["id"],
            {"expected_fabric_roll_version": roll_now["version"]},
            CUTMGR,
        )
        validate_error(resp, ApiErrorId.ERR_MARKER_NOT_DRAFT)

    def test_marker_approve_state_error_leaves_roll_unchanged(self):
        """PRD §3.5: "The marker must be `DRAFT` — checked before any business
        rule — or the approval is rejected with `ERR_MARKER_NOT_DRAFT`
        (HTTP 409)." and PRD §2.9: "Approving a marker moves yards into
        `allocated_yards`".

        Design: Difficulty/priority_pair_validation_conflict/marker_approve_state_beats_fiscal
        """
        _style, order, roll = _order_and_available_roll()
        marker = _draft_marker(order["id"], roll["id"])
        get_success_data(api_client.approve_marker(
            marker["id"], {"expected_fabric_roll_version": roll["version"]}, CUTMGR,
        ))
        roll_now = get_success_data(api_client.get_fabric_roll(roll["id"], ANY))
        resp = api_client.approve_marker(
            marker["id"],
            {"expected_fabric_roll_version": roll_now["version"]},
            CUTMGR,
        )
        validate_error(resp, ApiErrorId.ERR_MARKER_NOT_DRAFT)
        marker_after = get_success_data(api_client.get_marker(marker["id"], ANY))
        assert marker_after["status"] == "APPROVED"
        roll_after = get_success_data(api_client.get_fabric_roll(roll["id"], ANY))
        # No double reservation: allocated stays at the first approval's 41.3.
        assert roll_after["allocated_yards"] == pytest.approx(41.3, abs=1e-9)
        assert_fabric_ledger_invariants(roll_after)


class TestOccMarkerApprove:
    def test_occ_marker_approve_stale_roll_version(self):
        """PRD §2.7: "an approval carrying a pre-reservation baseline is
        rejected with `ERR_STALE_VERSION` (HTTP 412) even when enough yardage
        remains."

        Design: Corner/cross_cutting_layers/occ_marker_approve_stale_roll_version
        """
        style = create_style()
        order = create_production_order(
            style["id"], PLANNER, size_quantities=[{"size": "M", "qty": 200}],
        )
        roll = create_available_fabric_roll(MATS, received_yards=82.6)
        m1 = _draft_marker(order["id"], roll["id"])
        m2 = _draft_marker(order["id"], roll["id"])
        stale_version = roll["version"]
        get_success_data(api_client.approve_marker(
            m1["id"], {"expected_fabric_roll_version": stale_version}, CUTMGR,
        ))
        resp = api_client.approve_marker(
            m2["id"], {"expected_fabric_roll_version": stale_version}, CUTMGR,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        m2_after = get_success_data(api_client.get_marker(m2["id"], ANY))
        assert m2_after["status"] == "DRAFT"

    def test_occ_marker_approve_retry_with_fresh_version_succeeds(self):
        """PRD §2.7: "Approving a marker requires `expected_fabric_roll_version`,
        carrying the `version` of the referenced `FabricRoll` as the cutting
        manager last observed it."

        Design: Corner/cross_cutting_layers/occ_marker_approve_stale_roll_version
        """
        style = create_style()
        order = create_production_order(
            style["id"], PLANNER, size_quantities=[{"size": "M", "qty": 200}],
        )
        roll = create_available_fabric_roll(MATS, received_yards=82.6)
        m1 = _draft_marker(order["id"], roll["id"])
        m2 = _draft_marker(order["id"], roll["id"])
        stale_version = roll["version"]
        get_success_data(api_client.approve_marker(
            m1["id"], {"expected_fabric_roll_version": stale_version}, CUTMGR,
        ))
        resp = api_client.approve_marker(
            m2["id"], {"expected_fabric_roll_version": stale_version}, CUTMGR,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        fresh_version = get_success_data(
            api_client.get_fabric_roll(roll["id"], ANY)
        )["version"]
        m2 = get_success_data(api_client.approve_marker(
            m2["id"], {"expected_fabric_roll_version": fresh_version}, CUTMGR,
        ))
        assert m2["status"] == "APPROVED"


class TestFabricBoundaryAndDepletion:
    def test_fabric_approve_at_exact_available_accepted(self):
        """PRD §3.5: "the roll's `available_yards` must be at least the
        computed allocation — equality is permitted — or the approval fails
        with `ERR_INSUFFICIENT_FABRIC` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/fabric_approve_at_exact_available_then_depleted
        """
        _style, order, roll = _order_and_available_roll()
        marker = _draft_marker(order["id"], roll["id"])
        marker = get_success_data(api_client.approve_marker(
            marker["id"], {"expected_fabric_roll_version": roll["version"]}, CUTMGR,
        ))
        assert marker["status"] == "APPROVED"
        roll_after = get_success_data(api_client.get_fabric_roll(roll["id"], ANY))
        assert roll_after["allocated_yards"] == pytest.approx(41.3, abs=1e-9)
        assert roll_after["available_yards"] == pytest.approx(0.0, abs=1e-9)
        # DEPLETED only fires on a cut, not on reservation alone.
        assert roll_after["status"] == "AVAILABLE"

    def test_cut_to_exactly_zero_auto_depletes_roll(self):
        """PRD §2.9: "a cut that drives `available_yards` to exactly zero
        additionally transitions the roll from `AVAILABLE` to `DEPLETED`".

        Design: Difficulty/boundary_precision_check/fabric_approve_at_exact_available_then_depleted
        """
        style, pack, _ops = setup_style_with_approved_pack()
        order = create_production_order(
            style["id"], PLANNER, size_quantities=[{"size": "M", "qty": 100}],
        )
        plan_order(order["id"], pack["id"], PLANNER)
        roll = create_available_fabric_roll(MATS, received_yards=41.3)
        marker = _draft_marker(order["id"], roll["id"])
        get_success_data(api_client.approve_marker(
            marker["id"], {"expected_fabric_roll_version": roll["version"]}, CUTMGR,
        ))
        get_success_data(api_client.start_cutting(order["id"], PLANNER))
        get_success_data(api_client.cut_marker(
            marker["id"], {"size_quantities": [{"size": "M", "qty": 100}]}, CUTMGR,
        ))
        roll_after = get_success_data(api_client.get_fabric_roll(roll["id"], ANY))
        assert roll_after["consumed_yards"] == pytest.approx(41.3, abs=1e-9)
        assert roll_after["allocated_yards"] == pytest.approx(0.0, abs=1e-9)
        assert roll_after["available_yards"] == pytest.approx(0.0, abs=1e-9)
        assert roll_after["status"] == "DEPLETED"


class TestMarkerCancelConservation:
    def test_fabric_yards_approve_cancel_conservation(self):
        """PRD §3.5: "Cancelling an `APPROVED` marker additionally returns its
        reservation: the roll's `allocated_yards` is decremented by the
        marker's `allocated_yards`, `available_yards` recomputed, the roll's
        `version` incremented, and the marker's `allocated_yards` reset to
        zero".

        Design: Difficulty/compensating_invariant/fabric_yards_approve_cancel_conservation
        """
        _style, order, roll = _order_and_available_roll()
        marker = _draft_marker(order["id"], roll["id"])
        get_success_data(api_client.approve_marker(
            marker["id"], {"expected_fabric_roll_version": roll["version"]}, CUTMGR,
        ))
        roll_mid = get_success_data(api_client.get_fabric_roll(roll["id"], ANY))
        assert roll_mid["allocated_yards"] == pytest.approx(41.3, abs=1e-9)
        assert roll_mid["available_yards"] == pytest.approx(0.0, abs=1e-9)
        get_success_data(api_client.cancel_marker(marker["id"], CUTMGR))
        roll_after = get_success_data(api_client.get_fabric_roll(roll["id"], ANY))
        assert roll_after["allocated_yards"] == pytest.approx(0.0, abs=1e-9)
        assert roll_after["consumed_yards"] == pytest.approx(0.0, abs=1e-9)
        assert roll_after["available_yards"] == pytest.approx(41.3, abs=1e-9)
        assert_fabric_ledger_invariants(roll_after)

    def test_cancelled_marker_carries_zero_allocation(self):
        """PRD §3.5: "Cancelling an `APPROVED` marker additionally returns its
        reservation: ... the marker's `allocated_yards` reset to zero before
        its own `version` increments."

        Design: Difficulty/compensating_invariant/fabric_yards_approve_cancel_conservation
        """
        _style, order, roll = _order_and_available_roll()
        marker = _draft_marker(order["id"], roll["id"])
        get_success_data(api_client.approve_marker(
            marker["id"], {"expected_fabric_roll_version": roll["version"]}, CUTMGR,
        ))
        marker = get_success_data(api_client.cancel_marker(marker["id"], CUTMGR))
        assert marker["status"] == "CANCELLED"
        assert marker["allocated_yards"] == pytest.approx(0.0, abs=1e-9)


class TestMarkerCutGuards:
    def test_cut_cancelled_marker_returns_marker_not_approved(self):
        """PRD §3.5: "The marker must be `APPROVED` (otherwise
        `ERR_MARKER_NOT_APPROVED`, HTTP 409)".

        Design: Corner/state_machines/cut_cancelled_marker_returns_marker_not_approved
        """
        _style, order, roll = _order_and_available_roll(order_qty=10)
        marker = _draft_marker(order["id"], roll["id"], pieces=10)
        marker = get_success_data(api_client.cancel_marker(marker["id"], CUTMGR))
        assert marker["status"] == "CANCELLED"
        resp = api_client.cut_marker(
            marker["id"], {"size_quantities": [{"size": "M", "qty": 10}]}, CUTMGR,
        )
        validate_error(resp, ApiErrorId.ERR_MARKER_NOT_APPROVED)

    def test_cut_beyond_uncut_qty_rejected(self):
        """PRD §3.5: "for every size, the cumulative cut quantity across all of
        the order's already-cut markers plus this cut must not exceed the
        ordered quantity for that size, or the cut is rejected with
        `ERR_CUT_EXCEEDS_UNCUT` (HTTP 422)".

        Design: Corner/validations/cut_beyond_uncut_qty_rejected
        """
        style, pack, _ops = setup_style_with_approved_pack()
        order = create_production_order(
            style["id"], PLANNER, size_quantities=[{"size": "M", "qty": 3}],
        )
        plan_order(order["id"], pack["id"], PLANNER)
        roll = create_available_fabric_roll(MATS, received_yards=82.6)
        m1 = _draft_marker(order["id"], roll["id"], pieces=3)
        get_success_data(api_client.approve_marker(
            m1["id"], {"expected_fabric_roll_version": roll["version"]}, CUTMGR,
        ))
        get_success_data(api_client.start_cutting(order["id"], PLANNER))
        get_success_data(api_client.cut_marker(
            m1["id"], {"size_quantities": [{"size": "M", "qty": 3}]}, CUTMGR,
        ))
        roll_now = get_success_data(api_client.get_fabric_roll(roll["id"], ANY))
        m2 = _draft_marker(order["id"], roll["id"], pieces=1)
        get_success_data(api_client.approve_marker(
            m2["id"], {"expected_fabric_roll_version": roll_now["version"]}, CUTMGR,
        ))
        resp = api_client.cut_marker(
            m2["id"], {"size_quantities": [{"size": "M", "qty": 1}]}, CUTMGR,
        )
        validate_error(resp, ApiErrorId.ERR_CUT_EXCEEDS_UNCUT)
        m2_after = get_success_data(api_client.get_marker(m2["id"], ANY))
        assert m2_after["status"] == "APPROVED"

    def test_cut_wrong_total_rejected(self):
        """PRD §3.5: "and the supplied quantities must sum exactly to the
        marker's `planned_pieces`, or the request is `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/cut_cancelled_marker_returns_marker_not_approved
        """
        style, pack, _ops = setup_style_with_approved_pack()
        order = create_production_order(
            style["id"], PLANNER, size_quantities=[{"size": "M", "qty": 10}],
        )
        plan_order(order["id"], pack["id"], PLANNER)
        roll = create_available_fabric_roll(MATS)
        marker = _draft_marker(order["id"], roll["id"], pieces=10)
        get_success_data(api_client.approve_marker(
            marker["id"], {"expected_fabric_roll_version": roll["version"]}, CUTMGR,
        ))
        get_success_data(api_client.start_cutting(order["id"], PLANNER))
        resp = api_client.cut_marker(
            marker["id"], {"size_quantities": [{"size": "M", "qty": 9}]}, CUTMGR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestFabricRollQc:
    def test_record_qc_on_rejected_roll_returns_invalid_state(self):
        """PRD §3.3: "The roll must still be `RECEIVED`, or the recording is
        rejected with `ERR_INVALID_STATE_TRANSITION`. ... a `result` of `FAIL`
        moves it to `REJECTED` — a terminal state — and pins `usable_yards` at
        zero."

        Design: Corner/state_machines/record_qc_on_rejected_roll_returns_invalid_state
        """
        roll = get_success_data(api_client.create_fabric_roll(
            create_fabric_roll_payload(), MATS,
        ))
        roll = get_success_data(
            api_client.record_fabric_qc(roll["id"], {"result": "FAIL"}, MATS)
        )
        assert roll["status"] == "REJECTED"
        resp = api_client.record_fabric_qc(roll["id"], {"result": "PASS"}, MATS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        roll_after = get_success_data(api_client.get_fabric_roll(roll["id"], ANY))
        assert roll_after["status"] == "REJECTED"
        assert roll_after["usable_yards"] == 0

    def test_get_missing_marker_returns_not_found(self):
        """PRD §2.5: "Any existence failure is rejected with `ERR_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/get_missing_marker_returns_not_found
        """
        resp = api_client.get_marker(NON_EXISTENT_UUID, ANY)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
