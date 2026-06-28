"""Floor-plan notes (PRD §3.2)."""
import calc
import errors
from clock import clock
from db import db, make_common, touch
from errors import err
from middleware import require_roles
from routes.common import lookup, list_and_respond, respond
from services import recompute_note, serialize_note
from validation import get_json, require_fk, require_int

FM_ADMIN = ("FinanceManager", "DealerAdmin")


def _has_active_note_for_unit(unit_id, exclude_id=None):
    for n in db.floor_plan_notes.values():
        if n["id"] == exclude_id:
            continue
        if n["unit_id"] == unit_id and n["status"] in ("ACTIVE", "CURTAILMENT_DUE"):
            return True
    return False


def register(app):

    @app.route("/floor-plan-notes", methods=["POST"])
    @require_roles(*FM_ADMIN)
    def create_note():
        body = get_json()
        unit_id = require_fk(body, "unit_id")
        # existence (priority 3) — but field validation precedes for the body
        principal_cents = require_int(body, "principal_cents", gt=0)
        annual_rate_bps = require_int(body, "annual_rate_bps", gt=0)
        lookup(db.units, unit_id)

        note = {
            "unit_id": unit_id,
            "principal_cents": principal_cents,
            "annual_rate_bps": annual_rate_bps,
            "curtailment_paid_cents": 0,
            "interest_accrued_cents": 0,
            "days_outstanding": 0,
            "activated_on": None,
            "curtailment_stage": 0,
            "status": "DRAFT",
        }
        make_common(note)
        db.floor_plan_notes[note["id"]] = note
        return respond(serialize_note(note), status=201)

    @app.route("/floor-plan-notes", methods=["GET"])
    @require_roles(*FM_ADMIN)
    def list_notes():
        from flask import request
        items = list(db.floor_plan_notes.values())
        unit_id = request.args.get("unit_id")
        status = request.args.get("status")
        if unit_id is not None:
            items = [n for n in items if n["unit_id"] == unit_id]
        if status is not None:
            items = [n for n in items if n["status"] == status]
        return list_and_respond(items, lambda n: serialize_note(n))

    @app.route("/floor-plan-notes/<note_id>", methods=["GET"])
    @require_roles(*FM_ADMIN)
    def get_note(note_id):
        note = lookup(db.floor_plan_notes, note_id)
        # read-time recompute of interest/days only (does not bump version)
        return respond(serialize_note(note, recompute=True))

    @app.route("/floor-plan-notes/<note_id>/activate", methods=["POST"])
    @require_roles(*FM_ADMIN)
    def activate_note(note_id):
        note = lookup(db.floor_plan_notes, note_id)
        if note["status"] != "DRAFT":
            raise err(errors.ERR_INVALID_STATE, "Note is not DRAFT.")
        unit = db.units.get(note["unit_id"])
        if unit is None or unit["status"] != "AVAILABLE" or \
                _has_active_note_for_unit(note["unit_id"], exclude_id=note["id"]):
            raise err(errors.ERR_INVALID_STATE,
                      "Unit must be AVAILABLE with no other active note.")
        note["status"] = "ACTIVE"
        note["activated_on"] = clock.now()
        note["days_outstanding"] = 0
        note["interest_accrued_cents"] = 0
        note["curtailment_stage"] = 0
        touch(note)
        unit["floor_planned"] = True
        touch(unit)
        return respond(serialize_note(note))

    @app.route("/floor-plan-notes/<note_id>/recompute", methods=["POST"])
    @require_roles(*FM_ADMIN)
    def recompute_endpoint(note_id):
        note = lookup(db.floor_plan_notes, note_id)
        if note["status"] not in ("ACTIVE", "CURTAILMENT_DUE"):
            raise err(errors.ERR_INVALID_STATE, "Note is not ACTIVE/CURTAILMENT_DUE.")
        recompute_note(note)
        touch(note)
        return respond(serialize_note(note))

    @app.route("/floor-plan-notes/<note_id>/curtail", methods=["POST"])
    @require_roles(*FM_ADMIN)
    def curtail_note(note_id):
        note = lookup(db.floor_plan_notes, note_id)
        body = get_json()
        payment_cents = require_int(body, "payment_cents", gt=0)
        if note["status"] != "CURTAILMENT_DUE":
            raise err(errors.ERR_INVALID_STATE, "Note is not CURTAILMENT_DUE.")
        stage = note["curtailment_stage"]
        shortfall = calc.curtailment_shortfall(
            note["principal_cents"], stage, note["curtailment_paid_cents"]
        )
        if payment_cents < shortfall:
            raise err(errors.ERR_CURTAILMENT_SHORT,
                      "Payment below required curtailment shortfall.")
        note["curtailment_paid_cents"] += payment_cents
        # recompute interest base on the reduced principal; if all due stages
        # satisfied, return to ACTIVE.
        new_shortfall = calc.curtailment_shortfall(
            note["principal_cents"], note["curtailment_stage"],
            note["curtailment_paid_cents"]
        )
        if new_shortfall <= 0:
            note["status"] = "ACTIVE"
        # refresh interest against the reduced base at the current clock
        note["interest_accrued_cents"] = calc.floor_plan_interest(
            note["principal_cents"], note["curtailment_paid_cents"],
            note["annual_rate_bps"], note["days_outstanding"]
        )
        touch(note)
        return respond(serialize_note(note))

    @app.route("/floor-plan-notes/<note_id>/default", methods=["POST"])
    @require_roles("DealerAdmin")
    def default_note(note_id):
        note = lookup(db.floor_plan_notes, note_id)
        if note["status"] != "CURTAILMENT_DUE":
            raise err(errors.ERR_INVALID_STATE, "Note is not CURTAILMENT_DUE.")
        note["status"] = "DEFAULTED"
        # Unit.floor_planned stays true (lender holds title)
        touch(note)
        return respond(serialize_note(note))
