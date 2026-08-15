"""Design change orders: apply cascade, withdraw/reject exits, job cancel cascade."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_customer_contact_headers,
    make_jig,
    make_lumber_lot,
    make_load,
    make_batch,
    make_design,
    explode_cut_list,
    cut_list_line_payload,
    reserve_lumber,
    submit_design,
    setup_confirmed_job,
    setup_sealed_roof_design,
    setup_change_order_requested,
    setup_mega_chain_approved,
    create_change_order_payload,
    change_order_fresh,
    design_fresh,
    cut_list_fresh,
    batch_fresh,
    bundle_fresh,
    load_fresh,
    lot_fresh,
    job_fresh,
    line_fresh,
    reservation_fresh,
)

PM = TEST_USERS["plant_manager_headers"]
PP = TEST_USERS["production_planner_headers"]
SC = TEST_USERS["shipping_coordinator_headers"]


class TestChangeOrderApplyCascade:
    def test_apply_runs_six_hop_cascade(self, api):
        """PRD §3.9: "The apply then executes a six-hop cascade in order. Hop 1: the
        superseded design moves `SEALED` to `SUPERSEDED`. Hop 2: each cut list of that
        design moves — a list in `EXPLODED` goes to `SUPERSEDED`; a list in `RELEASED`
        with no line in `CUT` goes to `SUPERSEDED`; a list in `RELEASED` with at least
        one line in `CUT` goes to `RECONCILING`" and "Hop 5: every bundle in `PACKED`
        referencing a cancelled batch moves to `SUPERSEDED`, its delivery load — if in
        `PLANNED`, `STAGED`, or `LOADING` — reopens to `PLANNED`, and the load's
        `actual_total_weight_lbs` is recomputed excluding the superseded bundles.
        Hop 6: the job's posture is recomputed, reading `BLOCKED` for as long as any
        cut list remains `RECONCILING`." Also §3.9: "`impact_lines_scrapped` counts
        the lines in `CUT` status across all cut lists of the superseded design at
        that moment, and `impact_open_reservations` counts the reservations still
        `RESERVED` on lines or lists of that design".

        Design: Difficulty/transitive_cascade/change_order_apply_cascade
        """
        ns = setup_mega_chain_approved()
        # Assessment quantified the blast radius: cl2's single line is CUT (1);
        # its reservations were already CONSUMED at CUTTING (0 open).
        assert ns.co1["impact_lines_scrapped"] == 1
        assert ns.co1["impact_open_reservations"] == 0

        applied = validate_success(api.apply_change_order(ns.co1["id"], PM))
        assert applied["status"] == "APPLIED"
        assert design_fresh(ns.dsg2["id"])["status"] == "SUPERSEDED", "hop 1"
        assert cut_list_fresh(ns.cl2["id"])["status"] == "RECONCILING", \
            "hop 2: RELEASED with one CUT line goes to RECONCILING"
        assert cut_list_fresh(ns.cl1["id"])["status"] == "RELEASED", \
            "the other design's list is untouched"
        assert batch_fresh(ns.bat2["id"])["status"] == "CANCELLED", "hop 4"
        assert batch_fresh(ns.bat1["id"])["status"] == "STAGED", \
            "the other list's batch is untouched"
        assert bundle_fresh(ns.bnd2["id"])["status"] == "SUPERSEDED", "hop 5"
        assert load_fresh(ns.load1["id"])["status"] == "PLANNED", "hop 5: load reopens"
        assert bundle_fresh(ns.bnd1["id"])["status"] == "PACKED"
        assert job_fresh(ns.job["id"])["posture"] == "BLOCKED", \
            "hop 6: BLOCKED while a cut list remains RECONCILING"

    def test_reconcile_closes_list_and_restores_posture(self, api):
        """PRD §3.4: "scraps every remaining `PENDING` line with no lot impact (their
        reservations were already released by the cascade), and scraps every `CUT`
        line with waste accrual: for each such line, walking its `CONSUMED`
        reservations in reservation `created_at` ascending order, each touched lot's
        `scrapped_bf` increases by the covered amount and its `consumed_bf` decreases
        by the same amount, until the line's full `required_board_feet` has been
        accounted". PRD §2.10: "The tiers are evaluated in strict priority, and the
        first matching tier wins."

        Design: Difficulty/transitive_cascade/change_order_apply_cascade
        """
        ns = setup_mega_chain_approved()
        validate_success(api.apply_change_order(ns.co1["id"], PM))
        closed = validate_success(api.reconcile_cut_list(ns.cl2["id"], PP))
        assert closed["status"] == "CLOSED"
        assert line_fresh(ns.lines2["PS-1"]["id"])["status"] == "SCRAPPED"
        lot4 = lot_fresh(ns.lots.lot4["id"])
        assert lot4["scrapped_bf"] == pytest.approx(140.01), \
            "the CUT line's required_board_feet accrues as scrap"
        assert lot4["consumed_bf"] == pytest.approx(72.67)
        assert lot4["available_bf"] == pytest.approx(187.32), \
            "conservation: 187.32 + 0 + 72.67 + 140.01 == 400.00 received"
        assert lot4["reserved_bf"] == pytest.approx(0)
        assert job_fresh(ns.job["id"])["posture"] == "GREEN", \
            "the BLOCKED condition cleared with the reconcile"


class TestChangeOrderExits:
    def test_withdraw_and_reject_paths(self, api):
        """PRD §3.9: "A `PlantManager` may instead reject the order from `REQUESTED`
        or `IMPACT_ASSESSED`, and the owning customer may withdraw it from
        `REQUESTED` — withdrawal requires `X-User-ID` equal to the job's
        `customer_id`, else `ERR_FORBIDDEN_OWNERSHIP`."

        Design: Corner/state_machines/change_order_withdraw_and_reject_paths
        """
        ns = setup_change_order_requested(by_customer=True)  # co1 by the customer
        job = job_fresh(ns.job["id"])
        co2 = get_success_data(api.create_change_order(
            ns.job["id"], create_change_order_payload(ns.dsg1["id"], job["version"],
                                                      reason="load change"), PP))
        withdrawn = validate_success(api.withdraw_change_order(
            ns.co1["id"], make_customer_contact_headers(ns.customer["id"])))
        assert withdrawn["status"] == "WITHDRAWN", "customer exit from REQUESTED"
        rejected = validate_success(api.reject_change_order(co2["id"], PM))
        assert rejected["status"] == "REJECTED", "manager exit from REQUESTED"
        assert design_fresh(ns.dsg1["id"])["status"] == "SEALED", \
            "neither exit touched the design"

    def test_approve_from_requested_rejected(self, api):
        """PRD §3.9: "Approval by a `PlantManager` — `IMPACT_ASSESSED` to `APPROVED` —
        demands a chain-valid successor" and "Any action attempted from a status that
        does not declare it is rejected with `ERR_CHANGE_ORDER_INVALID_TRANSITION`
        (HTTP 409)."

        Design: Corner/state_machines/change_order_approve_from_requested_rejected
        """
        ns = setup_change_order_requested(by_customer=False)
        resp = api.approve_change_order(ns.co1["id"], PM)
        validate_error(resp, ApiErrorId.ERR_CHANGE_ORDER_INVALID_TRANSITION)
        assert change_order_fresh(ns.co1["id"])["status"] == "REQUESTED"


class TestJobCancelCascade:
    def test_cancel_fans_out_and_cancelled_load_locks(self, api):
        """PRD §3.2: "Cancelling a job fires a full down-cascade in one operation:
        every load in `PLANNED`, `STAGED`, or `LOADING` moves to `CANCELLED`, and each
        cancelled load's bundles in `PACKED` (for a load in `LOADING`, also bundles in
        `LOADED`) move to `SUPERSEDED`; every production batch not already `LOADED` or
        `CANCELLED` moves to `CANCELLED`, with the surviving batches' build sequence
        renumbered per §3.6; every cut list in `EXPLODED`, `RELEASED`, or
        `RECONCILING` moves to `SUPERSEDED`; and every reservation still `RESERVED` on
        lines or lists of the job moves to `RELEASED`, restoring each touched lot's
        availability and incrementing each lot's `version`." PRD §3.7: "any undeclared
        transition or failed state guard is rejected with `ERR_LOAD_INVALID_TRANSITION`
        (HTTP 409)."

        Design: Corner/state_machines/job_cancel_cascade_and_load_terminal_lockdown
        """
        ns = setup_sealed_roof_design(job_name="Cancel Job")
        ns.jig_roof = make_jig()
        cl1, lines = explode_cut_list(ns.dsg1["id"], ns.jig_roof["id"],
                                      [cut_list_line_payload("TC-1", "L2X6", 12.0, 10)])
        validate_success(api.release_cut_list(cl1["id"], PP))  # job IN_PRODUCTION
        lot6 = make_lumber_lot(lumber_dimension="L2X6", received_board_feet=500.0)
        rsv = reserve_lumber(lot6["id"], lines["TC-1"]["id"], 126.00)
        bat = make_batch(ns.job["id"], cl1["id"], ns.jig_roof["id"])
        load = make_load(ns.job["id"], planned_weight_est_lbs=5000)

        cancelled = validate_success(api.cancel_job(ns.job["id"], PM))
        assert cancelled["status"] == "CANCELLED"
        assert load_fresh(load["id"])["status"] == "CANCELLED"
        assert batch_fresh(bat["id"])["status"] == "CANCELLED"
        assert cut_list_fresh(cl1["id"])["status"] == "SUPERSEDED"
        assert reservation_fresh(rsv["id"])["status"] == "RELEASED"
        lot = lot_fresh(lot6["id"])
        assert lot["available_bf"] == pytest.approx(500.00), "availability restored exactly"
        assert lot["reserved_bf"] == pytest.approx(0)

        resp = api.transition_load(load["id"], {"to_state": "DISPATCHED"}, SC)
        validate_error(resp, ApiErrorId.ERR_LOAD_INVALID_TRANSITION)


class TestPosturePriority:
    def test_blocked_beats_at_risk(self, api):
        """PRD §2.10: "The tiers are evaluated in strict priority, and the first
        matching tier wins. A job is `BLOCKED` if any of the following holds: its
        customer's `credit_hold` is true; any of its change orders is in `APPROVED`;
        any of its cut lists is in `RECONCILING`; or any damage claim on any of its
        loads is in `APPROVED_REBUILD` or `REBUILD_IN_PROGRESS`. Otherwise the job is
        `AT_RISK` if any of the following holds: any of its production batches is in
        `QC_FAILED` or `REWORK`; any of its delivery loads is in `RETURNED`; or any of
        its component designs is in `SEAL_REQUESTED`. Otherwise the job is `GREEN`."
        PRD §3.1: "setting `credit_hold` to true immediately recomputes the posture of
        every job belonging to that customer, flipping each to `BLOCKED` per §2.10."

        Design: Corner/calculations/posture_priority_blocked_beats_at_risk
        """
        ns = setup_confirmed_job(job_name="Posture Job", contract=100000)
        dsg = make_design(ns.job["id"], ns.eng1)
        submit_design(dsg["id"], ns.eng1)  # SEAL_REQUESTED outstanding
        assert job_fresh(ns.job["id"])["posture"] == "AT_RISK"
        validate_success(api.update_customer_account(ns.customer["id"], {"credit_hold": True}, PM))
        assert job_fresh(ns.job["id"])["posture"] == "BLOCKED", \
            "credit_hold dominates the AT_RISK condition"
        validate_success(api.update_customer_account(ns.customer["id"], {"credit_hold": False}, PM))
        assert job_fresh(ns.job["id"])["posture"] == "AT_RISK", \
            "derived, never stored: clearing the hold restores AT_RISK"
