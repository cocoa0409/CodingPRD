"""Scrap-disposition fork endpoints (PRD §3.7)."""
from flask import Blueprint

import db
import errors
import lookups
import validators as V
from middleware import authenticate, authorize, get_json_body
from response import object_response
from serialize import public
from services import calc

bp = Blueprint("scrap_dispositions", __name__)

DECISIONS = {"SCRAP", "REWORK"}


def _recompute_wip(wo):
    wo["wip_qty"] = wo["started_qty"] - wo["completed_qty"] - wo["scrapped_qty"]


def _is_final_op(wop):
    siblings = [w for w in db.work_order_operations.values()
                if w["work_order_id"] == wop["work_order_id"]]
    max_seq = max(w["sequence_no"] for w in siblings)
    return wop["sequence_no"] == max_seq


@bp.route("/scrap-dispositions/<rid>", methods=["GET"])
def get_scrap(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "MachineOperator",
                     "QualityInspector", "PlantAdmin"])
    return object_response(public(lookups.scrap_disposition(rid)))


@bp.route("/scrap-dispositions/<rid>/disposition", methods=["POST"])
def disposition(rid):
    _, role = authenticate()
    authorize(role, ["QualityInspector", "PlantAdmin"])
    body = get_json_body()
    with db.LOCK:
        sd = lookups.scrap_disposition(rid)
        decision = V.as_enum(V.require(body, "decision"), "decision", DECISIONS)

        # State (priority 4): must be PENDING.
        if sd["status"] != "PENDING":
            raise errors.invalid_state("Only a PENDING disposition may be dispositioned.")

        wop = db.work_order_operations.get(sd["work_order_operation_id"])
        if wop is None:
            raise errors.not_found()

        # Re-confirm quantity <= units_in - scrap_qty (ERR_SCRAP_QTY_EXCEEDS).
        available = wop["units_in"] - wop["scrap_qty"]
        if sd["quantity"] > available:
            raise errors.ApiError(errors.ERR_SCRAP_QTY_EXCEEDS,
                                  "Scrap quantity exceeds available units.", 422)

        wo = db.work_orders.get(wop["work_order_id"])

        if decision == "SCRAP":
            # Fork A: cost + WIP debit, no rework re-entry.
            product = db.products.get(wo["product_id"]) if wo else None
            unit_cost = product["unit_cost_cents"] if product else 0
            sd["scrap_cost_cents"] = calc.round_cents(
                calc._D(sd["quantity"]) * calc._D(unit_cost))
            sd["status"] = "SCRAPPED"
            db.touch(sd)

            wop["scrap_qty"] = wop["scrap_qty"] + sd["quantity"]
            db.touch(wop)

            if wo is not None:
                wo["scrapped_qty"] = wo["scrapped_qty"] + sd["quantity"]
                _recompute_wip(wo)
                db.touch(wo)
        else:
            # Fork B: REWORK — reopen op, reverse completion, void signoff.
            sd["status"] = "REWORKED"
            # scrap_cost_cents stays 0
            db.touch(sd)

            was_final = _is_final_op(wop)
            wop["status"] = "REWORK"
            db.touch(wop)

            if was_final and wo is not None:
                wo["completed_qty"] = wo["completed_qty"] - sd["quantity"]
                _recompute_wip(wo)
                db.touch(wo)

            # void the op's existing PASS traveler sign-off(s) so it must re-sign.
            for s in db.traveler_signoffs.values():
                if (s["work_order_operation_id"] == wop["id"]
                        and s["result"] == "PASS"
                        and not s.get("_voided", False)):
                    s["_voided"] = True

        return object_response(public(sd))
