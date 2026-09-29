"""Lifecycles: which status a row opens in, which transitions are declared,
which are refused, which are terminal, and what each successful move cascades
onto its neighbours."""

import pytest

from test_helpers import (
    accept_receipt_payload,
    adjudicate_claim_payload,
    create_flooring_lot_payload,
    create_grade_bundle_payload,
    create_grade_run_payload,
    create_green_receipt_payload,
    finalize_lot_payload,
    freeze_product_line_payload,
    record_stress_test_payload,
    reject_receipt_payload,
    request_info_payload,
    resubmit_claim_payload,
    reverse_claim_payload,
    start_maintenance_payload,
    supersede_grade_run_payload,
    void_lot_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    CLERK,
    INSPECTOR,
    OPERATOR,
    SCHEDULER,
    SUPERVISOR,
    create_species,
    refetch_chamber,
    refetch_charge,
    refetch_claim,
    refetch_grade_run,
    refetch_lot,
    refetch_prefinish_run,
    refetch_product_line,
    refetch_receipt,
    set_logical_clock,
    setup_charge_with_receipts,
    setup_draft_grade_run,
    setup_finalized_grade_run,
    setup_line_only_submitted_claim,
    setup_loaded_charge,
    setup_planned_lot,
    setup_released_charge,
    setup_scheduled_charge,
    setup_scheduled_prefinish_run,
)
from test_helpers.test_users import (
    CLAIM_ADJUDICATOR_USER_ID,
    CLAIM_SUBMITTER_USER_ID,
    make_warranty_adjudicator_headers,
)

# One deck receipt at the schedule's own design moisture, so nothing but the
# transition under test can decide the outcome.
SINGLE_RECEIPT = [
    {
        "received_board_feet": 6000,
        "accepted_board_feet": 5800,
        "moisture_pct_at_receipt": 45.0,
        "receipt_grade": "FAS",
    }
]

ONE_CLEAR_BUNDLE = [
    {"grade_class": "CLEAR", "bundle_board_feet": 1000.00, "average_length_in": 50}
]


class TestGreenReceiptLifecycle:
    """The receiving deck has one entry state and two exits, and only one of
    them can ever be taken."""

    def test_a_new_receipt_is_received_and_a_rejection_closes_it_for_good(self, api):
        """PRD 3.2: "A new receipt opens in `RECEIVED` status with
        `accepted_board_feet` at 0, a null `kiln_charge_id` and a null
        `rejection_reason`."

        PRD 3.2: "Rejecting a receipt instead moves it from `RECEIVED` to `REJECTED`
        and records the supplied `rejection_reason`, leaving `accepted_board_feet` at
        0; `REJECTED` is terminal, as is `CONSUMED` at the other end of the
        lifecycle."

        PRD 3.2: "Attempting either action on a receipt that has already left
        `RECEIVED` — accepting an already accepted receipt, for instance — is rejected
        with `ERR_RECEIPT_STATE_INVALID`."

        PRD 3.2: "Receipts may be listed filtered by `species_profile_id`,
        `kiln_charge_id` or `status`."

        Design: Corner/state_machines/green_receipt_starts_in_received_and_rejects_to_terminal
        """
        set_logical_clock(api)
        species = create_species(api)

        receipt = validate_success(
            api.create_green_receipt(
                create_green_receipt_payload(species["id"], received_board_feet=6000),
                CLERK,
            ),
            expected_status=201,
        )
        assert receipt["status"] == "RECEIVED"
        assert receipt["accepted_board_feet"] == pytest.approx(0, abs=0.01)
        assert receipt["kiln_charge_id"] is None
        assert receipt["rejection_reason"] is None

        rejected = validate_success(
            api.reject_green_receipt(
                receipt["id"],
                reject_receipt_payload(
                    rejection_reason="Stain and insect damage beyond FAS"
                ),
                CLERK,
            ),
            expected_status=200,
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "Stain and insect damage beyond FAS"
        assert rejected["accepted_board_feet"] == pytest.approx(0, abs=0.01)

        response = api.accept_green_receipt(
            receipt["id"], accept_receipt_payload(5800), CLERK
        )
        validate_error(response, "ERR_RECEIPT_STATE_INVALID", expected_status=409)

        _rows, meta = validate_paginated(
            api.list_green_receipts(CLERK, params={"status": "REJECTED"})
        )
        assert meta["total_count"] == 1

    def test_a_second_acceptance_cannot_rewrite_the_scaled_volume(self, api):
        """PRD 3.2: "Accepting a receipt moves it from `RECEIVED` to `ACCEPTED` and
        records the `accepted_board_feet` supplied in the payload — the volume that
        survived scaling, which may be less than the gross delivered volume but may
        never exceed it."

        PRD 3.2: "Attempting either action on a receipt that has already left
        `RECEIVED` — accepting an already accepted receipt, for instance — is rejected
        with `ERR_RECEIPT_STATE_INVALID`."

        Design: Corner/state_machines/receipt_accept_twice_second_call_rejected
        """
        set_logical_clock(api)
        species = create_species(api)
        receipt = validate_success(
            api.create_green_receipt(
                create_green_receipt_payload(species["id"], received_board_feet=6000),
                CLERK,
            ),
            expected_status=201,
        )
        accepted = validate_success(
            api.accept_green_receipt(receipt["id"], accept_receipt_payload(5800), CLERK),
            expected_status=200,
        )
        assert accepted["status"] == "ACCEPTED"

        response = api.accept_green_receipt(
            receipt["id"], accept_receipt_payload(5900), CLERK
        )
        validate_error(response, "ERR_RECEIPT_STATE_INVALID", expected_status=409)

        unchanged = refetch_receipt(api, receipt["id"])
        assert unchanged["status"] == "ACCEPTED"
        assert unchanged["accepted_board_feet"] == pytest.approx(5800, abs=0.01)

    def test_scaling_may_reach_the_delivered_volume_but_not_pass_it(self, api):
        """PRD 3.2: "A value above `received_board_feet` is rejected with
        `ERR_ACCEPTED_BF_EXCEEDS_RECEIVED`."

        PRD 3.2: "A new receipt opens in `RECEIVED` status with
        `accepted_board_feet` at 0, a null `kiln_charge_id` and a null
        `rejection_reason`."

        PRD 3.2: "Accepting a receipt moves it from `RECEIVED` to `ACCEPTED` and
        records the `accepted_board_feet` supplied in the payload — the volume that
        survived scaling, which may be less than the gross delivered volume but may
        never exceed it."

        Design: Corner/state_machines/accept_above_received_board_feet_rejected
        """
        set_logical_clock(api)
        species = create_species(api)
        receipt = validate_success(
            api.create_green_receipt(
                create_green_receipt_payload(species["id"], received_board_feet=6000),
                CLERK,
            ),
            expected_status=201,
        )

        response = api.accept_green_receipt(
            receipt["id"], accept_receipt_payload(6001), CLERK
        )
        validate_error(
            response, "ERR_ACCEPTED_BF_EXCEEDS_RECEIVED", expected_status=422
        )
        still_open = refetch_receipt(api, receipt["id"])
        assert still_open["status"] == "RECEIVED"
        assert still_open["accepted_board_feet"] == pytest.approx(0, abs=0.01)

        accepted = validate_success(
            api.accept_green_receipt(receipt["id"], accept_receipt_payload(6000), CLERK),
            expected_status=200,
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["accepted_board_feet"] == pytest.approx(6000, abs=0.01)


class TestChargeLoadPreconditions:
    """A charge cannot enter the kiln empty, and it cannot skip the load."""

    def test_an_empty_charge_cannot_be_loaded_into_an_available_chamber(self, api):
        """PRD 3.4: "The charge must hold some wood — a `charged_green_bf` of 0
        cannot be loaded and is refused with `ERR_CHARGE_STATE_INVALID`, as is any
        attempt to load a `DISPLACED` charge."

        PRD 3.3: "A newly created charge opens in `SCHEDULED` status with
        `charged_green_bf` at 0, `redry_count` at 0, a null
        `weighted_initial_moisture_pct`, null stress-test readings, a null
        `dry_bf_out` and `remaining_dry_bf`, and a null `displaced_reason`."

        PRD 3.1: "Kiln chambers are registered by a `MillAdmin` with a unique
        `chamber_code` and a `capacity_board_feet` ceiling on green volume, and open in
        `AVAILABLE` status with a null `maintenance_note`."

        Design: Corner/state_machines/charge_load_with_no_allocated_volume_rejected
        """
        ctx = setup_scheduled_charge(api)
        assert ctx["chamber"]["status"] == "AVAILABLE"

        response = api.load_charge(ctx["charge"]["id"], OPERATOR)
        validate_error(response, "ERR_CHARGE_STATE_INVALID", expected_status=409)

        charge = refetch_charge(api, ctx["charge"]["id"])
        assert charge["status"] == "SCHEDULED"
        assert charge["charged_green_bf"] == pytest.approx(0, abs=0.01)
        assert charge["weighted_initial_moisture_pct"] is None
        assert refetch_chamber(api, ctx["chamber"]["id"])["status"] == "AVAILABLE"

    def test_the_drying_leg_and_the_stress_test_cannot_be_reached_from_scheduled(
        self, api
    ):
        """PRD 3.5: "The drying legs themselves are simple state advances driven by
        a `KilnOperator` and carry no payload: the charge moves from `LOADED` to
        `DRYING` when the drying leg begins, and from `DRYING` to `CONDITIONING` when
        equalisation and conditioning begin."

        PRD 3.5: "Attempting either out of order is refused with
        `ERR_CHARGE_STATE_INVALID`."

        PRD 3.5: "A `KilnOperator` records a `shell_moisture_pct` and a
        `core_moisture_pct` on a charge in `CONDITIONING` status; recording it in any
        other status is refused with `ERR_CHARGE_STATE_INVALID`."

        PRD 3.4: "A `KilnOperator` or `MillAdmin` names a `green_receipt_id` in the
        payload, and the receipt moves from `ACCEPTED` to `ALLOCATED` with its
        `kiln_charge_id` set to the target charge."

        Design: Corner/state_machines/charge_start_drying_from_scheduled_is_invalid_transition
        """
        ctx = setup_charge_with_receipts(
            api, receipts=[dict(r) for r in SINGLE_RECEIPT]
        )
        assert ctx["charge"]["charged_green_bf"] == pytest.approx(5800, abs=0.01)

        validate_error(
            api.start_drying(ctx["charge"]["id"], OPERATOR),
            "ERR_CHARGE_STATE_INVALID",
            expected_status=409,
        )
        validate_error(
            api.record_stress_test(
                ctx["charge"]["id"],
                record_stress_test_payload(6.4, 8.2),
                OPERATOR,
            ),
            "ERR_CHARGE_STATE_INVALID",
            expected_status=409,
        )

        charge = refetch_charge(api, ctx["charge"]["id"])
        assert charge["status"] == "SCHEDULED"
        assert charge["shell_moisture_pct"] is None
        assert charge["dry_bf_out"] is None
        assert refetch_receipt(api, ctx["receipts"][0]["id"])["status"] == "ALLOCATED"


class TestChamberOccupancyCascade:
    """The chamber's status is owned by the charge that sits in it."""

    def test_an_occupied_chamber_cannot_be_taken_out_of_service(self, api):
        """PRD 3.1: "A chamber that is `OCCUPIED` cannot be taken out of service,
        and a chamber that is not in `MAINTENANCE` cannot be returned from it; both
        are rejected with `ERR_CHAMBER_STATE_INVALID`."

        PRD 3.4: "The chamber moves from `AVAILABLE` to `OCCUPIED`, and every
        receipt allocated to the charge moves from `ALLOCATED` to `CONSUMED`, freezing
        its `accepted_board_feet` and its `kiln_charge_id` against any further
        allocation change — a consumed receipt can no longer be deallocated."

        Design: Corner/state_machines/start_maintenance_on_occupied_chamber_rejected
        """
        ctx = setup_loaded_charge(api, receipts=[dict(r) for r in SINGLE_RECEIPT])
        assert ctx["charge"]["status"] == "LOADED"
        assert refetch_chamber(api, ctx["chamber"]["id"])["status"] == "OCCUPIED"

        response = api.start_chamber_maintenance(
            ctx["chamber"]["id"],
            start_maintenance_payload(maintenance_note="Emergency fan inspection"),
            OPERATOR,
        )
        validate_error(response, "ERR_CHAMBER_STATE_INVALID", expected_status=409)

        chamber = refetch_chamber(api, ctx["chamber"]["id"])
        assert chamber["status"] == "OCCUPIED"
        assert chamber["maintenance_note"] is None

    def test_releasing_the_charge_frees_the_chamber_in_the_same_request(self, api):
        """PRD 3.5: "On the release branch the charge moves from `CONDITIONING` to
        `RELEASED`."

        PRD 3.5: "The stored readings and both derived figures are retained, and the
        charge's kiln-dry output is computed: `dry_bf_out` is `charged_green_bf` reduced
        by the species' `green_to_dry_shrink_pct` — that is, multiplied by one minus
        that percentage expressed as a fraction — and rounded half up to two decimal
        places."

        PRD 3.5: "The chamber the charge occupied moves from `OCCUPIED` back to
        `AVAILABLE`, free for the next load."

        PRD 3.4: "The chamber moves from `AVAILABLE` to `OCCUPIED`, and every
        receipt allocated to the charge moves from `ALLOCATED` to `CONSUMED`, freezing
        its `accepted_board_feet` and its `kiln_charge_id` against any further
        allocation change — a consumed receipt can no longer be deallocated."

        Design: Corner/state_machines/chamber_returns_to_available_when_charge_released
        """
        ctx = setup_released_charge(api, receipts=[dict(r) for r in SINGLE_RECEIPT])

        released = ctx["stress_test"]
        assert released["status"] == "RELEASED"
        assert released["dry_bf_out"] == pytest.approx(5365.00, abs=0.01)
        assert released["remaining_dry_bf"] == pytest.approx(5365.00, abs=0.01)
        assert released["moisture_gradient_pp"] == pytest.approx(1.8, abs=0.01)
        assert released["average_moisture_pct"] == pytest.approx(7.3, abs=0.01)

        assert refetch_chamber(api, ctx["chamber"]["id"])["status"] == "AVAILABLE"

        receipt = refetch_receipt(api, ctx["receipts"][0]["id"])
        assert receipt["status"] == "CONSUMED"
        assert receipt["kiln_charge_id"] == ctx["charge"]["id"]


class TestChargeClosureAndLotVoid:
    """Drawing the charge dry closes it without anyone asking, and voiding the
    drawing lot undoes exactly that."""

    def test_the_last_board_foot_drawn_auto_closes_the_charge(self, api):
        """PRD 3.6: "Planning a lot draws down the charge: the charge's
        `remaining_dry_bf` is reduced by `input_dry_bf`, and it is always `dry_bf_out`
        less the total `input_dry_bf` of the non-voided lots drawn from that charge."

        PRD 3.6: "When that remainder reaches exactly 0 the charge has nothing left
        to give and auto-advances from `RELEASED` to `CLOSED`."

        PRD 3.6: "The charge must be in `RELEASED` status, or the request is refused
        with `ERR_CHARGE_STATE_INVALID`, and the requested draw may not exceed the
        charge's `remaining_dry_bf`, or it is refused with
        `ERR_CHARGE_DRY_BF_EXCEEDED`."

        PRD 3.6: "Lots may be listed filtered by `product_line_id`,
        `kiln_charge_id`, `core_stock_id`, `final_grade_run_id` or `status`."

        Design: Corner/state_machines/charge_auto_closes_when_remaining_dry_bf_reaches_zero
        """
        ctx = setup_planned_lot(api, input_dry_bf=8972.50)
        assert ctx["lot"]["status"] == "PLANNED"
        assert ctx["lot"]["input_dry_bf"] == pytest.approx(8972.50, abs=0.01)

        charge = refetch_charge(api, ctx["charge"]["id"])
        assert charge["dry_bf_out"] == pytest.approx(8972.50, abs=0.01)
        assert charge["remaining_dry_bf"] == pytest.approx(0, abs=0.01)
        assert charge["status"] == "CLOSED"

        response = api.create_flooring_lot(
            create_flooring_lot_payload(
                ctx["product_line"]["id"], ctx["charge"]["id"], 100
            ),
            SUPERVISOR,
        )
        validate_error(response, "ERR_CHARGE_STATE_INVALID", expected_status=409)

        _rows, meta = validate_paginated(
            api.list_flooring_lots(ADMIN, params={"kiln_charge_id": ctx["charge"]["id"]})
        )
        assert meta["total_count"] == 1

    def test_voiding_that_lot_reopens_the_closed_charge_and_is_once_only(self, api):
        """PRD 3.6: "Voiding is the compensating operation for a lot, available to a
        `MillSupervisor` or `MillAdmin` from either `PLANNED` or `MILLED` and taking the
        lot to the terminal `VOIDED` state with the supplied `void_reason` recorded."

        PRD 3.6: "A void unwinds every reservation the lot made: for an
        `ENGINEERED` lot the `reserved_core_sf` is released back so that the core
        stock's `reserved_square_feet` no longer counts it; the lot's `input_dry_bf` is
        restored to the supplying charge's `remaining_dry_bf`, and a charge that had
        been auto-closed returns from `CLOSED` to `RELEASED`; and for a lot already
        `MILLED`, every byproduct batch of the lot has its `available_tons` set to 0."

        PRD 3.6: "A `SOLID` lot carries a null `reserved_core_sf`."

        PRD 3.6: "Batches are never created directly and are read-only thereafter,
        listable filtered by `flooring_lot_id` or `byproduct_type`."

        PRD 3.6: "Voiding a lot that has already reached `GRADED`, `QUARANTINED` or
        `VOIDED` is refused with `ERR_LOT_STATE_INVALID`."

        Design: Corner/state_machines/lot_void_from_planned_restores_charge_and_reopens_closed_charge
        """
        ctx = setup_planned_lot(api, input_dry_bf=8972.50)
        assert ctx["lot"]["reserved_core_sf"] is None
        assert refetch_charge(api, ctx["charge"]["id"])["status"] == "CLOSED"

        voided = validate_success(
            api.void_flooring_lot(
                ctx["lot"]["id"],
                void_lot_payload(
                    void_reason="Order cancelled before the saw was set"
                ),
                SUPERVISOR,
            ),
            expected_status=200,
        )
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "Order cancelled before the saw was set"
        assert voided["reserved_core_sf"] is None

        charge = refetch_charge(api, ctx["charge"]["id"])
        assert charge["remaining_dry_bf"] == pytest.approx(8972.50, abs=0.01)
        assert charge["status"] == "RELEASED"

        _rows, meta = validate_paginated(
            api.list_byproduct_batches(
                ADMIN, params={"flooring_lot_id": ctx["lot"]["id"]}
            )
        )
        assert meta["total_count"] == 0

        response = api.void_flooring_lot(
            ctx["lot"]["id"], void_lot_payload(void_reason="Duplicate void"), SUPERVISOR
        )
        validate_error(response, "ERR_LOT_STATE_INVALID", expected_status=409)


class TestLotClosurePreconditions:
    """Both grading and closeout are declared only from `MILLED`."""

    def test_a_planned_lot_can_neither_be_graded_nor_closed_out(self, api):
        """PRD 3.7: "Only a lot in `MILLED` status may be graded, and a lot in any
        other status is refused with `ERR_LOT_STATE_INVALID`."

        PRD 3.7: "Only a `MILLED` lot may be closed out."

        PRD 2.7: "When several checks could fail on one request, they are evaluated
        in a fixed order and the first failure is the one reported."

        PRD 2.7: "18. Flooring lot state — `ERR_LOT_STATE_INVALID` (409), on milling
        completion, lot finalization, voiding and grade run creation."

        PRD 2.7: "32. Grade run belongs to the lot — `ERR_GRADE_RUN_LOT_MISMATCH`
        (422), on lot finalization and on supersede."

        Design: Corner/state_machines/lot_finalize_from_planned_is_invalid_transition
        """
        ctx = setup_finalized_grade_run(api)
        assert ctx["grade_run"]["status"] == "FINALIZED"

        planned = validate_success(
            api.create_flooring_lot(
                create_flooring_lot_payload(
                    ctx["product_line"]["id"], ctx["charge"]["id"], 2000
                ),
                SUPERVISOR,
            ),
            expected_status=201,
        )
        assert planned["status"] == "PLANNED"

        response = api.finalize_flooring_lot(
            planned["id"], finalize_lot_payload(ctx["grade_run"]["id"]), SUPERVISOR
        )
        validate_error(response, "ERR_LOT_STATE_INVALID", expected_status=409)

        response = api.create_grade_run(
            create_grade_run_payload(planned["id"], planned["version"]), INSPECTOR
        )
        validate_error(response, "ERR_LOT_STATE_INVALID", expected_status=409)

        unchanged = refetch_lot(api, planned["id"])
        assert unchanged["status"] == "PLANNED"
        assert unchanged["final_grade_run_id"] is None
        assert unchanged["final_yield_pct"] is None


class TestGradeRunTerminalStates:
    """A finalized run is frozen, and a superseded one is frozen twice over."""

    def test_a_finalized_run_refuses_a_second_finalize_and_supersedes_once(self, api):
        """PRD 3.7: "Finalizing a run turns those lines into the run's tally and
        moves it from `DRAFT` to `FINALIZED`."

        PRD 2.7: "19. Grade run state — `ERR_GRADE_RUN_STATE_INVALID` (409), on
        bundle creation, run finalization, supersede and the run referenced by a lot
        finalization."

        PRD 3.7: "The run being superseded must also be `FINALIZED`, and it must not
        already be the run the lot was closed out against; a run that is still `DRAFT`,
        or one whose lot has already reached `GRADED` or `QUARANTINED` against it, is
        refused with `ERR_GRADE_RUN_STATE_INVALID`."

        PRD 3.7: "On success the run records its `superseded_by_run_id` and moves to
        the terminal `SUPERSEDED` status."

        PRD 3.7: "A new run opens in `DRAFT` status with null tallies, and runs may
        be listed filtered by `flooring_lot_id`, `superseded_by_run_id` or `status`."

        PRD 2.5: "A successful create increments `FlooringLot.version`, so a caller
        that read the lot before an intervening write is refused until it re-reads it."

        Design: Corner/state_machines/grade_run_finalize_twice_and_supersede_pointer_set
        """
        ctx = setup_draft_grade_run(api, bundles=[dict(b) for b in ONE_CLEAR_BUNDLE])
        run_one = ctx["grade_run"]

        # The first run's creation bumped the lot, so the second run must be pinned
        # to the version the lot carries now.
        run_two = validate_success(
            api.create_grade_run(
                create_grade_run_payload(
                    ctx["lot"]["id"],
                    ctx["lot"]["version"],
                    inspector_ruleset="MILL_CHARACTER",
                ),
                INSPECTOR,
            ),
            expected_status=201,
        )
        assert run_two["status"] == "DRAFT"
        validate_success(
            api.create_grade_bundle(
                run_two["id"],
                create_grade_bundle_payload(
                    grade_class="CLEAR", bundle_board_feet=1200.00, average_length_in=50
                ),
                INSPECTOR,
            ),
            expected_status=201,
        )

        validate_success(
            api.finalize_grade_run(run_one["id"], INSPECTOR), expected_status=200
        )
        validate_success(
            api.finalize_grade_run(run_two["id"], INSPECTOR), expected_status=200
        )

        response = api.finalize_grade_run(run_one["id"], INSPECTOR)
        validate_error(response, "ERR_GRADE_RUN_STATE_INVALID", expected_status=409)

        held = refetch_grade_run(api, run_one["id"])
        assert held["tally_board_feet"] == pytest.approx(1000.00, abs=0.01)
        assert held["credited_board_feet"] == pytest.approx(1000.0000, abs=0.01)
        assert held["tally_value_cents"] == 684800

        superseded = validate_success(
            api.supersede_grade_run(
                run_one["id"], supersede_grade_run_payload(run_two["id"]), INSPECTOR
            ),
            expected_status=200,
        )
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["superseded_by_run_id"] == run_two["id"]

        response = api.supersede_grade_run(
            run_one["id"], supersede_grade_run_payload(run_two["id"]), INSPECTOR
        )
        validate_error(response, "ERR_GRADE_RUN_STATE_INVALID", expected_status=409)

        rows, meta = validate_paginated(
            api.list_grade_runs(ADMIN, params={"superseded_by_run_id": run_two["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == run_one["id"]


class TestPrefinishRunTransitions:
    """Every prefinish action names the one status it is declared from."""

    def test_only_the_declared_move_out_of_scheduled_is_the_start(self, api):
        """PRD 3.8: "Releasing a run that is not `HELD` is refused with
        `ERR_PREFINISH_RUN_STATE_INVALID`."

        PRD 3.8: "Completing a run advances it from `RUNNING` to the terminal
        `COMPLETED`; completing a run that is not `RUNNING` is refused with
        `ERR_PREFINISH_RUN_STATE_INVALID`."

        PRD 3.8: "Starting a run is reserved to a `PrefinishScheduler` and advances
        it from `SCHEDULED` to `RUNNING`; it too requires the product line's posture to
        be `OPEN`, refusing a restricted or frozen line with
        `ERR_PRODUCT_LINE_POSTURE_BLOCKED`, and it requires the run's lot to still
        stand in `GRADED` status, which is otherwise refused with
        `ERR_LOT_NOT_GRADED`."

        PRD 2.7: "20. Prefinish run state — `ERR_PREFINISH_RUN_STATE_INVALID` (409),
        on start, complete and hold release."

        PRD 3.8: "Pushing 5000 linear feet of 3.190-inch boards through a three-pass
        line therefore consumes 47.85 litres."

        Design: Corner/state_machines/prefinish_run_release_hold_and_complete_from_scheduled_rejected
        """
        ctx = setup_scheduled_prefinish_run(api)
        run_id = ctx["prefinish_run"]["id"]
        assert ctx["prefinish_run"]["status"] == "SCHEDULED"
        assert ctx["prefinish_run"]["coating_liters"] == pytest.approx(47.85, abs=0.01)
        assert refetch_product_line(api, ctx["product_line"]["id"])["posture"] == "OPEN"

        validate_error(
            api.release_prefinish_hold(run_id, SCHEDULER),
            "ERR_PREFINISH_RUN_STATE_INVALID",
            expected_status=409,
        )
        validate_error(
            api.complete_prefinish_run(run_id, SCHEDULER),
            "ERR_PREFINISH_RUN_STATE_INVALID",
            expected_status=409,
        )

        running = validate_success(
            api.start_prefinish_run(run_id, SCHEDULER), expected_status=200
        )
        assert running["status"] == "RUNNING"
        assert running["coating_liters"] == pytest.approx(47.85, abs=0.01)

        validate_error(
            api.start_prefinish_run(run_id, SCHEDULER),
            "ERR_PREFINISH_RUN_STATE_INVALID",
            expected_status=409,
        )
        assert refetch_prefinish_run(api, run_id)["status"] == "RUNNING"


class TestClaimAdjudicationDimensions:
    """Adjudication and remediation are two independent dimensions on one row."""

    def test_a_denial_is_terminal_and_leaves_the_reserve_alone(self, api):
        """PRD 3.9: "On the `DENIED` branch the claim moves from `SUBMITTED` to the
        terminal `DENIED` status, the supplied `denial_reason` is recorded, and the
        warranty reserve is left entirely untouched — `installer_share_pct`,
        `mill_share_pct`, `service_months`, `depreciation_pct` and
        `adjudicated_liability_cents` all stay null, and the line's posture does not
        move."

        PRD 3.9: "In both branches the inspector-verified readings are stored on the
        claim and `adjudicated_by_user_id` records the deciding user."

        PRD 3.9: "On a line whose material value is 895 cents per square foot, a
        claim of 240 square feet gives a base of 328800, an administrative amount of
        26304 and an estimate of 355104 cents."

        PRD 3.9: "Work that has already finished cannot be unwound, so a claim whose
        remediation status is `COMPLETED` may not be reversed and is refused with
        `ERR_CLAIM_STATE_INVALID`, as is any attempt to reverse a claim that is not
        `APPROVED`."

        PRD 2.8: "At all times a line's `warranty_balance_cents` plus its
        `warranty_committed_cents` equals its `warranty_funded_total_cents`, and
        `warranty_committed_cents` equals the total `adjudicated_liability_cents` of the
        claims on that line whose adjudication status is `APPROVED`."

        Design: Corner/state_machines/claim_denied_leaves_reserve_untouched
        """
        ctx = setup_line_only_submitted_claim(
            api, claim_overrides={"claim_type": "GAPPING"}
        )
        assert ctx["claim"]["estimated_liability_cents"] == 355104
        adjudicator = make_warranty_adjudicator_headers(CLAIM_ADJUDICATOR_USER_ID)

        denied = validate_success(
            api.adjudicate_claim(
                ctx["claim"]["id"],
                adjudicate_claim_payload(
                    decision="DENIED",
                    denial_reason=(
                        "Subfloor moisture 10.5 pct far above the 7.0 pct install spec"
                    ),
                ),
                adjudicator,
            ),
            expected_status=200,
        )
        assert denied["adjudication_status"] == "DENIED"
        assert denied["denial_reason"] == (
            "Subfloor moisture 10.5 pct far above the 7.0 pct install spec"
        )
        assert denied["adjudicated_by_user_id"] == CLAIM_ADJUDICATOR_USER_ID
        assert denied["adjudicated_liability_cents"] is None
        assert denied["installer_share_pct"] is None
        assert denied["mill_share_pct"] is None
        assert denied["estimated_liability_cents"] == 355104
        assert denied["remediation_status"] == "NOT_STARTED"

        line = refetch_product_line(api, ctx["product_line"]["id"])
        assert line["warranty_balance_cents"] == 600000
        assert line["warranty_committed_cents"] == 0
        assert line["posture"] == "OPEN"

        response = api.reverse_claim(
            ctx["claim"]["id"],
            reverse_claim_payload(reversal_reason="Attempt to reverse a denial"),
            adjudicator,
        )
        validate_error(response, "ERR_CLAIM_STATE_INVALID", expected_status=409)

    def test_remediation_only_opens_once_the_claim_is_approved(self, api):
        """PRD 3.9: "Remediation runs on its own dimension, independent of
        adjudication, and may be driven by a `WarrantyAdjudicator` or a
        `MillSupervisor`."

        PRD 3.9: "Starting remediation moves the claim's remediation status from
        `NOT_STARTED` to `IN_PROGRESS`, and completing it moves that status from
        `IN_PROGRESS` to `COMPLETED`; both require the claim's adjudication status to be
        `APPROVED`, and both are refused with `ERR_CLAIM_STATE_INVALID` when either
        dimension is in the wrong state — remediating an unapproved claim, starting work
        already in progress, or completing work never started."

        PRD 3.9: "A verified 210 square feet on the same 895-cent line gives a base
        of 287700, an administrative amount of 23016 and a gross of 310716; installed on
        2026-03-15 and adjudicated on 2026-08-20 the claim has 5 months of service and
        2.5 percent depreciation, giving 302948; at a mill share of 50 percent the
        charge is 151474 cents."

        PRD 3.9: "Work that has already finished cannot be unwound, so a claim whose
        remediation status is `COMPLETED` may not be reversed and is refused with
        `ERR_CLAIM_STATE_INVALID`, as is any attempt to reverse a claim that is not
        `APPROVED`."

        Design: Corner/state_machines/remediation_start_requires_approved_adjudication
        """
        ctx = setup_line_only_submitted_claim(api)
        claim_id = ctx["claim"]["id"]
        adjudicator = make_warranty_adjudicator_headers(CLAIM_ADJUDICATOR_USER_ID)

        validate_error(
            api.start_remediation(claim_id, SUPERVISOR),
            "ERR_CLAIM_STATE_INVALID",
            expected_status=409,
        )
        assert refetch_claim(api, claim_id)["remediation_status"] == "NOT_STARTED"

        approved = validate_success(
            api.adjudicate_claim(claim_id, adjudicate_claim_payload(), adjudicator),
            expected_status=200,
        )
        assert approved["adjudicated_liability_cents"] == 151474
        assert approved["remediation_status"] == "NOT_STARTED"

        started = validate_success(
            api.start_remediation(claim_id, SUPERVISOR), expected_status=200
        )
        assert started["remediation_status"] == "IN_PROGRESS"
        assert started["adjudication_status"] == "APPROVED"

        completed = validate_success(
            api.complete_remediation(claim_id, SUPERVISOR), expected_status=200
        )
        assert completed["remediation_status"] == "COMPLETED"
        assert completed["adjudication_status"] == "APPROVED"

        response = api.reverse_claim(claim_id, reverse_claim_payload(), adjudicator)
        validate_error(response, "ERR_CLAIM_STATE_INVALID", expected_status=409)

    def test_a_resubmission_overwrites_the_claimant_figures_and_the_estimate(
        self, api
    ):
        """PRD 3.9: "A `WarrantyAdjudicator` may request further information, moving
        the claim from `SUBMITTED` to `INFO_REQUESTED` and recording the supplied
        `info_request_note`."

        PRD 3.9: "The claimant's corrected figures then come back through a
        resubmission, which moves the claim from `INFO_REQUESTED` back to `SUBMITTED`,
        overwrites `affected_square_feet`, `subfloor_moisture_pct_at_install` and
        `ambient_rh_pct_at_install` with the supplied values, recomputes
        `estimated_liability_cents` from them by the same four steps, and clears
        `info_request_note`."

        PRD 3.9: "First, a base is the `affected_square_feet` multiplied by the sum
        of the line's `material_value_cents_per_sf` and a remediation labour allowance
        of 475 cents per square foot."

        PRD 3.9: "Second, an administrative rate is selected by that base: 8 percent
        while the base is below 500000 cents, 6 percent while it is at most 1500000
        cents, and 4.5 percent above that."

        PRD 3.9: "A new claim captures `submitted_by_user_id` from the acting
        `X-User-ID`, opens with an adjudication status of `SUBMITTED` and a remediation
        status of `NOT_STARTED`, and carries a null `adjudicated_by_user_id`,
        `info_request_note`, `denial_reason` and `reversal_reason`."

        Design: Corner/state_machines/claim_resubmit_recomputes_estimated_liability_and_clears_note
        """
        ctx = setup_line_only_submitted_claim(api)
        claim_id = ctx["claim"]["id"]
        assert ctx["claim"]["estimated_liability_cents"] == 355104

        held = validate_success(
            api.request_claim_info(
                claim_id,
                request_info_payload(
                    info_request_note="Send the subfloor moisture log"
                ),
                make_warranty_adjudicator_headers(CLAIM_ADJUDICATOR_USER_ID),
            ),
            expected_status=200,
        )
        assert held["adjudication_status"] == "INFO_REQUESTED"
        assert held["info_request_note"] == "Send the subfloor moisture log"

        resubmitted = validate_success(
            api.resubmit_claim(
                claim_id,
                resubmit_claim_payload(
                    affected_square_feet=170,
                    subfloor_moisture_pct_at_install=9.0,
                    ambient_rh_pct_at_install=45,
                ),
                make_warranty_adjudicator_headers(CLAIM_SUBMITTER_USER_ID),
            ),
            expected_status=200,
        )
        assert resubmitted["adjudication_status"] == "SUBMITTED"
        assert resubmitted["info_request_note"] is None
        assert resubmitted["affected_square_feet"] == pytest.approx(170, abs=0.01)
        assert resubmitted["subfloor_moisture_pct_at_install"] == pytest.approx(
            9.0, abs=0.01
        )
        assert resubmitted["ambient_rh_pct_at_install"] == pytest.approx(45, abs=0.01)
        # 170 * (895 + 475) = 232900, an 8 percent administrative amount of 18632,
        # and the estimate is the base plus the administrative amount: 251532.
        assert resubmitted["estimated_liability_cents"] == 251532
        assert resubmitted["submitted_by_user_id"] == CLAIM_SUBMITTER_USER_ID

        line = refetch_product_line(api, ctx["product_line"]["id"])
        assert line["warranty_balance_cents"] == 600000
        assert line["warranty_committed_cents"] == 0


class TestProductLinePostureCascades:
    """An administrative freeze overrides the money in both directions, but it
    never resumes the work it stopped."""

    def test_a_freeze_holds_the_scheduled_run_and_unfreezing_does_not_resume_it(
        self, api
    ):
        """PRD 3.9: "The same role may administratively freeze a line with a
        supplied `freeze_reason`, which sets `freeze_override` to true and forces the
        posture to `FROZEN` from either `OPEN` or `RESTRICTED`; when the line was
        `OPEN`, the freeze also holds every `SCHEDULED` prefinish run on it, whereas a
        line that was already `RESTRICTED` has held those runs already."

        PRD 3.9: "Unfreezing clears `freeze_override` and lets the posture fall back
        to the money: the line becomes `OPEN` when `warranty_balance_cents` is at least
        500000 and `RESTRICTED` when it is below that floor."

        PRD 3.8: "When a product line's posture becomes `RESTRICTED` or `FROZEN`,
        every `SCHEDULED` run whose snapshotted `product_line_id` matches that line
        moves to `HELD` with a `hold_reason` recorded."

        PRD 3.8: "Held runs do not resume by themselves: even after the line's
        posture returns to `OPEN`, a held run stays `HELD` until someone explicitly
        releases it."

        PRD 3.8: "Releasing a hold moves the run from `HELD` back to `SCHEDULED` and
        clears `hold_reason`, and requires the product line's posture to be `OPEN` at
        that moment, or the release is refused with
        `ERR_PRODUCT_LINE_POSTURE_BLOCKED`."

        Design: Corner/state_machines/product_line_freeze_holds_runs_and_unfreeze_recomputes_posture
        """
        ctx = setup_scheduled_prefinish_run(api)
        run_id = ctx["prefinish_run"]["id"]
        line_id = ctx["product_line"]["id"]

        frozen = validate_success(
            api.freeze_product_line(
                line_id,
                freeze_product_line_payload(
                    freeze_reason="Class action review on the 2026 spring production"
                ),
                ADMIN,
            ),
            expected_status=200,
        )
        assert frozen["freeze_override"] is True
        assert frozen["posture"] == "FROZEN"
        assert frozen["warranty_balance_cents"] == 600000

        held = refetch_prefinish_run(api, run_id)
        assert held["status"] == "HELD"
        assert held["hold_reason"] is not None

        validate_error(
            api.release_prefinish_hold(run_id, SCHEDULER),
            "ERR_PRODUCT_LINE_POSTURE_BLOCKED",
            expected_status=409,
        )

        thawed = validate_success(
            api.unfreeze_product_line(line_id, ADMIN), expected_status=200
        )
        assert thawed["freeze_override"] is False
        assert thawed["posture"] == "OPEN"

        assert refetch_prefinish_run(api, run_id)["status"] == "HELD"

        released = validate_success(
            api.release_prefinish_hold(run_id, SCHEDULER), expected_status=200
        )
        assert released["status"] == "SCHEDULED"
        assert released["hold_reason"] is None
