"""Warranty / PIP / recall claims (PRD §3.7)."""
import calc
import errors
from db import db, make_common, touch
from errors import err
from middleware import require_roles
from routes.common import lookup, list_and_respond, respond
from services import serialize_generic
from validation import get_json, require_fk, require_enum, optional_string

CLAIM_READ_ROLES = ("ServiceAdvisor", "DealerAdmin", "FinanceManager")


def register(app):

    @app.route("/warranty-claims", methods=["POST"])
    @require_roles("ServiceAdvisor", "DealerAdmin")
    def create_claim():
        body = get_json()
        unit_id = require_fk(body, "unit_id")
        claim_type = require_enum(body, "claim_type", {"WARRANTY", "PIP", "RECALL"})
        campaign_code = optional_string(body, "campaign_code", default=None)
        lookup(db.units, unit_id)

        claim = {
            "unit_id": unit_id,
            "claim_type": claim_type,
            "campaign_code": campaign_code,
            "claimed_cents": 0,
            "approved_cents": 0,
            "status": "DRAFT",
        }
        make_common(claim)
        db.warranty_claims[claim["id"]] = claim
        return respond(serialize_generic(claim), status=201)

    @app.route("/warranty-claims", methods=["GET"])
    @require_roles(*CLAIM_READ_ROLES)
    def list_claims():
        from flask import request
        items = list(db.warranty_claims.values())
        for key in ("unit_id", "claim_type", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [c for c in items if c.get(key) == val]
        return list_and_respond(items, serialize_generic)

    @app.route("/warranty-claims/<claim_id>", methods=["GET"])
    @require_roles(*CLAIM_READ_ROLES)
    def get_claim(claim_id):
        claim = lookup(db.warranty_claims, claim_id)
        return respond(serialize_generic(claim))

    @app.route("/warranty-claims/<claim_id>/submit", methods=["POST"])
    @require_roles("ServiceAdvisor", "DealerAdmin")
    def submit_claim(claim_id):
        claim = lookup(db.warranty_claims, claim_id)
        if claim["status"] != "DRAFT":
            raise err(errors.ERR_INVALID_STATE, "Claim is not DRAFT.")
        # require at least one CLOSED work order referencing this claim
        linked_closed = [
            w for w in db.work_orders.values()
            if w.get("warranty_claim_id") == claim_id and w["status"] == "CLOSED"
        ]
        if not linked_closed:
            raise err(errors.ERR_INVALID_STATE,
                      "No CLOSED work order references this claim.")
        claim["claimed_cents"] = sum(w["total_charge_cents"] for w in linked_closed)
        claim["status"] = "SUBMITTED"
        touch(claim)
        return respond(serialize_generic(claim))

    @app.route("/warranty-claims/<claim_id>/adjudicate", methods=["POST"])
    @require_roles("DealerAdmin")
    def adjudicate_claim(claim_id):
        claim = lookup(db.warranty_claims, claim_id)
        body = get_json()
        decision = require_enum(body, "decision", {"FULL", "PARTIAL", "DENY"})
        if claim["status"] != "SUBMITTED":
            raise err(errors.ERR_INVALID_STATE, "Claim is not SUBMITTED.")
        # safety rule: a RECALL claim can never be denied
        if decision == "DENY" and claim["claim_type"] == "RECALL":
            raise err(errors.ERR_RECALL_CANNOT_DENY,
                      "A RECALL claim cannot be denied.")

        approved = calc.warranty_approved(
            claim["claimed_cents"], claim["claim_type"], decision
        )
        claim["approved_cents"] = approved
        if decision == "FULL":
            claim["status"] = "APPROVED"
        elif decision == "PARTIAL":
            claim["status"] = "PARTIAL"
        else:
            claim["status"] = "DENIED"
        touch(claim)
        return respond(serialize_generic(claim))

    @app.route("/warranty-claims/<claim_id>/pay", methods=["POST"])
    @require_roles("DealerAdmin")
    def pay_claim(claim_id):
        claim = lookup(db.warranty_claims, claim_id)
        if claim["status"] not in ("APPROVED", "PARTIAL"):
            raise err(errors.ERR_INVALID_STATE, "Claim is not APPROVED/PARTIAL.")
        claim["status"] = "PAID"
        touch(claim)
        return respond(serialize_generic(claim))
