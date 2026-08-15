"""BarrierCase endpoints: propose / counter / accept / escalate."""

import db
from errors import (
    err_not_found, err_invalid_state, err_unauthorized, raise_err,
    ERR_NEGOTIATION_ROUNDS_REMAINING,
)
from middleware import require_roles, get_json_body, check_int
from response import success_object, success_list, parse_pagination
from services.common import touch, recompute_pipeline
from flask import request

MAX_NEGOTIATION_ROUNDS = 3


def _serialize(c):
    return dict(c)


def _attach_note(case, body):
    note = body.get("resolution_note")
    if note is not None:
        if not isinstance(note, str):
            from errors import err_validation
            err_validation("resolution_note must be a string")
        case["resolution_note"] = note


def register(bp):
    @bp.route("/barrier-cases", methods=["GET"])
    def list_cases():
        require_roles("CoalitionAdmin", "InstitutionOfficer", "AgencyNavigator")
        limit, offset = parse_pagination(request.args)
        items = sorted(db.barrier_cases.values(), key=lambda x: db.parse_dt(x["created_at"]))
        aid = request.args.get("application_id")
        pid = request.args.get("participant_id")
        iid = request.args.get("institution_id")
        st = request.args.get("status")
        if aid is not None:
            items = [c for c in items if c["application_id"] == aid]
        if pid is not None:
            items = [c for c in items if c["participant_id"] == pid]
        if iid is not None:
            items = [c for c in items if c["institution_id"] == iid]
        if st is not None:
            items = [c for c in items if c["status"] == st]
        total = len(items)
        page = items[offset:offset + limit]
        return success_list([_serialize(c) for c in page], limit, offset, total)

    @bp.route("/barrier-cases/<cid>", methods=["GET"])
    def get_case(cid):
        require_roles("CoalitionAdmin", "InstitutionOfficer", "AgencyNavigator", "Participant")
        case = db.barrier_cases.get(cid)
        if case is None:
            err_not_found("BarrierCase not found")
        return success_object(_serialize(case))

    @bp.route("/barrier-cases/<cid>/propose", methods=["POST"])
    def propose(cid):
        user_id, _ = require_roles("InstitutionOfficer")
        case = db.barrier_cases.get(cid)
        if case is None:
            err_not_found("BarrierCase not found")
        body = get_json_body()
        if "proposed_settlement_cents" not in body or body["proposed_settlement_cents"] is None:
            from errors import err_validation
            err_validation("Missing required field: proposed_settlement_cents")
        check_int(body["proposed_settlement_cents"], "proposed_settlement_cents")
        if user_id != case["institution_id"]:
            err_unauthorized("Officer must belong to the case's institution")
        if case["status"] not in ("OPEN", "COUNTERED"):
            err_invalid_state("Case must be OPEN or COUNTERED to propose")
        case["proposed_settlement_cents"] = body["proposed_settlement_cents"]
        _attach_note(case, body)
        case["status"] = "PLAN_PROPOSED"
        touch(case)
        return success_object(_serialize(case))

    @bp.route("/barrier-cases/<cid>/counter", methods=["POST"])
    def counter(cid):
        require_roles("AgencyNavigator")
        case = db.barrier_cases.get(cid)
        if case is None:
            err_not_found("BarrierCase not found")
        body = get_json_body(required=False)
        if case["status"] != "PLAN_PROPOSED":
            err_invalid_state("Case must be PLAN_PROPOSED to counter")
        _attach_note(case, body)
        case["negotiation_rounds"] += 1
        case["status"] = "COUNTERED"
        touch(case)
        return success_object(_serialize(case))

    @bp.route("/barrier-cases/<cid>/accept", methods=["POST"])
    def accept(cid):
        user_id, _ = require_roles("Participant")
        case = db.barrier_cases.get(cid)
        if case is None:
            err_not_found("BarrierCase not found")
        body = get_json_body(required=False)
        if user_id != case["participant_id"]:
            err_unauthorized("Only the case's participant may accept")
        if case["status"] != "PLAN_PROPOSED":
            err_invalid_state("Case must be PLAN_PROPOSED to accept")
        case["final_settlement_cents"] = case["proposed_settlement_cents"]
        _attach_note(case, body)
        case["status"] = "RESOLVED"
        touch(case)
        # cascade: application DECLINED_CHEX -> REINSTATED
        app = db.account_applications.get(case["application_id"])
        if app is not None and app["status"] == "DECLINED_CHEX":
            app["status"] = "REINSTATED"
            touch(app)
        recompute_pipeline(case["participant_id"])
        return success_object(_serialize(case))

    @bp.route("/barrier-cases/<cid>/escalate", methods=["POST"])
    def escalate(cid):
        user_id, _ = require_roles("InstitutionOfficer")
        case = db.barrier_cases.get(cid)
        if case is None:
            err_not_found("BarrierCase not found")
        body = get_json_body(required=False)
        if user_id != case["institution_id"]:
            err_unauthorized("Officer must belong to the case's institution")
        if case["status"] != "COUNTERED":
            err_invalid_state("Case must be COUNTERED to escalate")
        if case["negotiation_rounds"] < MAX_NEGOTIATION_ROUNDS:
            raise_err(ERR_NEGOTIATION_ROUNDS_REMAINING, "Negotiation rounds remaining")
        _attach_note(case, body)
        case["status"] = "DENIED_FINAL"
        touch(case)
        # cascade: application DECLINED_CHEX -> DECLINED_FINAL; referral -> CLOSED_LOST
        app = db.account_applications.get(case["application_id"])
        if app is not None:
            if app["status"] == "DECLINED_CHEX":
                app["status"] = "DECLINED_FINAL"
                touch(app)
            rid = app.get("referral_id")
            if rid:
                ref = db.referrals.get(rid)
                if ref is not None:
                    ref["status"] = "CLOSED_LOST"
                    touch(ref)
        recompute_pipeline(case["participant_id"])
        return success_object(_serialize(case))
