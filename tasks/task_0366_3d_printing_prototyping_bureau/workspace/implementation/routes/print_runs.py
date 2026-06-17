"""PrintRun routes: schedule (create), start, complete, fail, adjudicate, cancel.

This module carries the trickiest workflow logic: the failure -> reprint cycle,
the FORWARD (provisional) vs CHRONOLOGICAL (final) cost attribution, spool
conservation, machine utilization, and order bubble-up.
"""

from flask import Blueprint, request

import errors
import validation as V
from db import DB, LOCK, stamp_create, touch
from middleware import require_auth, require_role
from pagination import paginate
from response import object_response, array_response
from services import calc, domain, ownership

bp = Blueprint("print_runs", __name__)

FAIL_CAUSES = ("MACHINE_FAULT", "OPERATOR_ERROR", "FILE_DEFECT", "CUSTOMER_CHANGE")
READ_ROLES = ("Operator", "BureauAdmin", "QAReviewer", "Customer")


def _intervals_overlap(a_start, a_dur, b_start, b_dur):
    """Half-open [start, start+dur). Returns True on genuine overlap."""
    a_end = a_start + a_dur
    b_end = b_start + b_dur
    return a_start < b_end and b_start < a_end


def _create_run_internal(line, machine, spool, start_min, duration_min):
    """Build a QUEUED PrintRun after all gates have passed. Computes run_grams,
    persists it, and recomputes spool + machine derived fields.

    Caller is responsible for having validated material/process/machine/slot/
    capacity/spool gates beforehand.
    """
    print_file = DB.print_files[line["print_file_id"]]
    material = DB.materials[line["material_id"]]
    grams = calc.run_grams(print_file, material, line["quantity"])

    run = stamp_create({
        "bureau_id": line["bureau_id"],
        "order_line_id": line["id"],
        "machine_id": machine["id"],
        "spool_id": spool["id"],
        "start_min": start_min,
        "duration_min": duration_min,
        "run_grams": grams,
        "fail_cause": None,
        "status": "QUEUED",
    })
    DB.print_runs[run["id"]] = run
    domain.recompute_spool(spool)
    domain.recompute_machine_utilization(machine)
    return run


def _run_create_gates(line, machine, spool, start_min, duration_min):
    """Apply the PRD §3.6 ordered business gates for run creation."""
    material = DB.materials[line["material_id"]]
    bureau = DB.bureaus[line["bureau_id"]]

    # p8: material ACTIVE.
    if material["status"] != "ACTIVE":
        raise errors.conflict(errors.ERR_MATERIAL_RETIRED, "Material is retired")
    # p8: machine.process == material.process.
    if machine["process"] != material["process"]:
        raise errors.conflict(errors.ERR_PROCESS_MISMATCH, "Machine process mismatch")
    # p8: machine not in MAINTENANCE.
    if machine["status"] != "ONLINE":
        raise errors.conflict(errors.ERR_MACHINE_OFFLINE, "Machine is offline")

    # p9: half-open slot overlap against QUEUED/PRINTING runs on the same machine.
    for r in DB.print_runs.values():
        if r["machine_id"] != machine["id"]:
            continue
        if r["status"] not in ("QUEUED", "PRINTING"):
            continue
        if _intervals_overlap(start_min, duration_min, r["start_min"], r["duration_min"]):
            raise errors.conflict(errors.ERR_MACHINE_SLOT_CONFLICT, "Machine slot conflict")

    # p11: capacity. scheduled_minutes + new duration must not EXCEED capacity.
    scheduled = sum(
        r["duration_min"] for r in DB.print_runs.values()
        if r["machine_id"] == machine["id"] and r["status"] in ("QUEUED", "PRINTING")
    )
    if scheduled + duration_min > bureau["shift_capacity_minutes"]:
        raise errors.conflict(errors.ERR_MACHINE_CAPACITY_EXCEEDED, "Machine capacity exceeded")

    # p12: spool stock. run_grams must not exceed grams_remaining.
    print_file = DB.print_files[line["print_file_id"]]
    grams = calc.run_grams(print_file, material, line["quantity"])
    if grams > spool["grams_remaining"]:
        raise errors.conflict(errors.ERR_SPOOL_INSUFFICIENT, "Spool stock insufficient")


@bp.route("/bureaus/print-runs", methods=["POST"])
def create_print_run():
    with LOCK:
        principal = require_auth()
        require_role(principal, ("Operator",))
        body = V.get_body()
        order_line_id = V.require_id(body, "order_line_id")
        machine_id = V.require_id(body, "machine_id")
        spool_id = V.require_id(body, "spool_id")
        start_min = V.require_nonneg_int(body, "start_min")
        duration_min = V.require_positive_int(body, "duration_min")

        line = DB.order_lines.get(order_line_id)
        if line is None:
            raise errors.reference_not_found()
        bureau_id = line["bureau_id"]
        machine = domain.ref_or_404(DB.machines, machine_id, bureau_id)
        spool = domain.ref_or_404(DB.spools, spool_id, bureau_id)

        _run_create_gates(line, machine, spool, start_min, duration_min)
        run = _create_run_internal(line, machine, spool, start_min, duration_min)
        return object_response(run, 201)


@bp.route("/bureaus/print-runs/<run_id>", methods=["GET"])
def get_print_run(run_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, READ_ROLES)
        run = domain.get_or_404(DB.print_runs, run_id)
        if principal.role == "Customer" and principal.user_id != ownership.run_customer_id(run):
            raise errors.forbidden()
        return object_response(run, 200)


@bp.route("/bureaus/print-runs", methods=["GET"])
def list_print_runs():
    with LOCK:
        principal = require_auth()
        require_role(principal, READ_ROLES)
        items = list(DB.print_runs.values())
        for key in ("bureau_id", "order_line_id", "machine_id", "spool_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [r for r in items if r.get(key) == val]
        if principal.role == "Customer":
            items = [r for r in items if ownership.run_customer_id(r) == principal.user_id]
        page, limit, offset, total = paginate(items)
        return array_response(page, limit, offset, total)


@bp.route("/bureaus/print-runs/<run_id>/start", methods=["POST"])
def start_print_run(run_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, ("Operator",))
        run = domain.get_or_404(DB.print_runs, run_id)
        if run["status"] != "QUEUED":
            raise errors.invalid_state()

        machine = DB.machines[run["machine_id"]]
        # machine ONLINE.
        if machine["status"] != "ONLINE":
            raise errors.conflict(errors.ERR_MACHINE_OFFLINE, "Machine is offline")
        # No other run on this machine is PRINTING.
        for r in DB.print_runs.values():
            if r["machine_id"] == machine["id"] and r["id"] != run["id"] and r["status"] == "PRINTING":
                raise errors.conflict(errors.ERR_MACHINE_BUSY, "Machine is busy")

        line = DB.order_lines[run["order_line_id"]]
        order = DB.orders[line["order_id"]]
        if order["payment_status"] != "ESCROWED":
            raise errors.conflict(errors.ERR_ORDER_NOT_ESCROWED, "Owning order not escrowed")

        run["status"] = "PRINTING"
        touch(run)
        domain.recompute_machine_utilization(machine)

        # Bubble: CONFIRMED -> IN_PRODUCTION.
        if order["fulfillment_status"] == "CONFIRMED":
            order["fulfillment_status"] = "IN_PRODUCTION"
            touch(order)
        return object_response(run, 200)


@bp.route("/bureaus/print-runs/<run_id>/complete", methods=["POST"])
def complete_print_run(run_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, ("Operator",))
        run = domain.get_or_404(DB.print_runs, run_id)
        if run["status"] != "PRINTING":
            raise errors.invalid_state()

        run["status"] = "DONE"
        touch(run)
        # grams move committed -> consumed (recompute by status partition).
        domain.recompute_spool(DB.spools[run["spool_id"]])
        domain.recompute_machine_utilization(DB.machines[run["machine_id"]])

        line = DB.order_lines[run["order_line_id"]]
        order = DB.orders[line["order_id"]]
        domain.bubble_on_run_complete(order)
        return object_response(run, 200)


@bp.route("/bureaus/print-runs/<run_id>/fail", methods=["POST"])
def fail_print_run(run_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, ("Operator",))
        run = domain.get_or_404(DB.print_runs, run_id)
        body = V.get_body()
        fail_cause = V.require_enum(body, "fail_cause", FAIL_CAUSES)

        if run["status"] != "PRINTING":
            raise errors.invalid_state()

        failed_line = DB.order_lines[run["order_line_id"]]
        order = DB.orders[failed_line["order_id"]]
        customer = DB.customers[order["customer_id"]]

        # FORWARD provisional reprint charge = full original line_total.
        forward_charge = calc.reprint_charge_forward(failed_line)

        # The reprint line is a copy of the failed line; its line_total is the
        # FORWARD provisional charge for now (CHRONOLOGICAL re-attributes later).
        reprint_line = stamp_create({
            "bureau_id": failed_line["bureau_id"],
            "order_id": failed_line["order_id"],
            "print_file_id": failed_line["print_file_id"],
            "material_id": failed_line["material_id"],
            "layer_height_mm": failed_line["layer_height_mm"],
            "quantity": failed_line["quantity"],
            "print_minutes": failed_line["print_minutes"],
            "per_part_cents": failed_line["per_part_cents"],
            "line_total_cents": forward_charge,
            "finishing_total_cents": 0,
            "reprint_of_line_id": failed_line["id"],
            "reprint_cause": fail_cause,
            "status": "ACTIVE",
        })

        # Pre-check wallet: escrow top-up for the reprint must be coverable.
        # The top-up equals the increase in grand_total caused by the new line.
        old_grand = order["grand_total_cents"]
        # Tentatively measure new grand total with the reprint line included.
        prospective_active = domain.active_lines_of_order(order["id"]) + [reprint_line]
        _, _, _, new_grand = calc.order_totals(prospective_active, order["lead_tier"])
        delta = new_grand - old_grand
        if delta > 0 and customer["wallet_balance_cents"] < delta:
            raise errors.insufficient_wallet("Wallet cannot cover reprint top-up")

        # Commit the failure side effects now that wallet is sufficient.
        run["status"] = "FAILED"
        run["fail_cause"] = fail_cause
        touch(run)
        # grams: committed -> consumed (waste).
        domain.recompute_spool(DB.spools[run["spool_id"]])
        domain.recompute_machine_utilization(DB.machines[run["machine_id"]])

        DB.order_lines[reprint_line["id"]] = reprint_line

        # Recompute order totals (now includes the reprint line).
        domain.recompute_order_totals(order)

        # Escrow top-up: move delta from wallet to escrow_held.
        if delta != 0:
            customer["wallet_balance_cents"] -= delta
            customer["escrow_held_cents"] += delta
            touch(customer)

        return object_response(run, 200)


@bp.route("/bureaus/print-runs/<run_id>/adjudicate", methods=["POST"])
def adjudicate_print_run(run_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, ("QAReviewer",))
        run = domain.get_or_404(DB.print_runs, run_id)
        body = V.get_body()
        if "expected_run_version" not in body:
            raise errors.invalid_request("Missing field: expected_run_version")
        expected = body["expected_run_version"]
        if not V.is_int(expected):
            raise errors.invalid_request("expected_run_version must be an integer")
        machine_id = V.require_id(body, "machine_id")
        spool_id = V.require_id(body, "spool_id")
        start_min = V.require_nonneg_int(body, "start_min")
        duration_min = V.require_positive_int(body, "duration_min")

        # FK resolution (p4) for the reprint's new run.
        bureau_id = run["bureau_id"]
        machine = domain.ref_or_404(DB.machines, machine_id, bureau_id)
        spool = domain.ref_or_404(DB.spools, spool_id, bureau_id)

        # OCC stale-version. PRD §2.10 explicitly states that a SECOND adjudication
        # carrying the stale (pre-first-adjudication) version — after the run has
        # already been adjudicated once (FAILED -> QUEUED, version advanced) — is
        # rejected with ERR_STALE_VERSION, "preventing a second adjudication from
        # double-reconciling." This version-echo check therefore pre-empts the
        # FAILED state-legality check for adjudication.
        if expected != run["version"]:
            raise errors.stale_version()

        # State legality: must be FAILED.
        if run["status"] != "FAILED":
            raise errors.invalid_state()

        failed_line = DB.order_lines[run["order_line_id"]]
        order = DB.orders[failed_line["order_id"]]
        customer = DB.customers[order["customer_id"]]
        print_file = DB.print_files[failed_line["print_file_id"]]
        material = DB.materials[failed_line["material_id"]]

        # Locate the reprint line spawned at /fail.
        reprint_line = next(
            (l for l in DB.order_lines.values()
             if l["reprint_of_line_id"] == failed_line["id"]),
            None,
        )

        reprint_cause = run["fail_cause"]
        forward_charge = calc.reprint_charge_forward(failed_line)
        final_charge = calc.reprint_charge_chronological(failed_line, print_file, material, reprint_cause)
        reconcile_delta = final_charge - forward_charge

        # Re-attribute the reprint line's cost to the FINAL chronological charge.
        if reprint_line is not None:
            reprint_line["line_total_cents"] = final_charge
            touch(reprint_line)

        # Recompute order totals with the finalized reprint cost.
        domain.recompute_order_totals(order)

        # Reconcile customer ledger: escrow_held += delta; wallet -= delta.
        if reconcile_delta != 0:
            customer["escrow_held_cents"] += reconcile_delta
            customer["wallet_balance_cents"] -= reconcile_delta
            touch(customer)

        # Run version advances (the adjudication mutation) and the run
        # transitions from FAILED back to QUEUED (PRD §3.7).
        run["status"] = "QUEUED"
        touch(run)

        # Create a fresh QUEUED PrintRun for the reprint line on the supplied
        # machine/spool/slot, closing the reprint cycle.
        if reprint_line is not None:
            _run_create_gates(reprint_line, machine, spool, start_min, duration_min)
            _create_run_internal(reprint_line, machine, spool, start_min, duration_min)

        return object_response(run, 200)


@bp.route("/bureaus/print-runs/<run_id>/cancel", methods=["POST"])
def cancel_print_run(run_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, ("Operator",))
        run = domain.get_or_404(DB.print_runs, run_id)
        if run["status"] != "QUEUED":
            raise errors.invalid_state()
        run["status"] = "CANCELLED"
        touch(run)
        # Released grams (committed -> released, NOT consumed).
        domain.recompute_spool(DB.spools[run["spool_id"]])
        domain.recompute_machine_utilization(DB.machines[run["machine_id"]])
        return object_response(run, 200)
