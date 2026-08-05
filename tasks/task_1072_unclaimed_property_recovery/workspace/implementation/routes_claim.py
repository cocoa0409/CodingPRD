"""Claim lifecycle, evidence, approval waterfall, payment and void."""
from flask import request, g

from store import STORE, new_id
from common import (
    ApiError, ok, ok_list, require_roles, get_json, require_str, require_enum,
    require_number, stamp_new, touch, serialize, serialize_list, paginate, D,
)
import lookups
import calc
import ledger

NON_TERMINAL_CLAIM = {"FILED", "UNDER_REVIEW", "NEEDS_EVIDENCE", "APPROVED", "PAID"}
FILED_BY = {"OWNER", "FIRM"}
DOC_TYPES = {"GOV_ID", "PROOF_OF_ADDRESS", "DEATH_CERTIFICATE", "OWNERSHIP_PROOF"}
DECISIONS = {"ACCEPTED", "REJECTED"}


def register(app):
    @app.post("/claims")
    @require_roles("Owner", "RecoveryAgent")
    def create_claim():
        body = get_json()
        property_id = require_str(body, "property_id")
        claimant_owner_id = require_str(body, "claimant_owner_id")
        filed_by = require_enum(body, "filed_by", FILED_BY)
        recovery_firm_id = body.get("recovery_firm_id")
        if recovery_firm_id is not None and not isinstance(recovery_firm_id, str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "recovery_firm_id must be a string.")
        contract_fee_pct = body.get("contract_fee_pct", 0)
        if contract_fee_pct is None:
            contract_fee_pct = 0
        if isinstance(contract_fee_pct, bool) or not isinstance(contract_fee_pct, (int, float)):
            raise ApiError("ERR_INVALID_REQUEST", 400, "contract_fee_pct must be a number.")
        # Existence, left to right
        prop = lookups.prop(property_id)
        lookups.owner(claimant_owner_id)
        firm = None
        if recovery_firm_id is not None:
            firm = lookups.recovery_firm(recovery_firm_id)
        # State: property must be ESCHEATED
        if prop["status"] != "ESCHEATED":
            raise ApiError("ERR_PROPERTY_NOT_CLAIMABLE", 409, "Property is not ESCHEATED.")
        # filed_by shape
        if filed_by == "FIRM":
            if recovery_firm_id is None:
                raise ApiError("ERR_FIRM_REQUIRED", 422, "FIRM-filed claim requires recovery_firm_id.")
        else:  # OWNER
            if recovery_firm_id is not None or D(contract_fee_pct) != D(0):
                raise ApiError("ERR_FIRM_REQUIRED", 422,
                               "OWNER-filed claim must have no firm and zero fee.")
        # At most one active claim per property
        for c in STORE.claims.values():
            if c["property_id"] == property_id and c["status"] in NON_TERMINAL_CLAIM:
                raise ApiError("ERR_CLAIM_ALREADY_ACTIVE", 409, "Property already has an active claim.")
        # Fee cap (only meaningful when a firm is involved)
        if firm is not None:
            cap = min(D(firm["max_fee_pct"]), calc.STATE_MAX_FEE_PCT)
            if D(contract_fee_pct) > cap:
                raise ApiError("ERR_FEE_EXCEEDS_CAP", 422, "contract_fee_pct exceeds the cap.")

        claim_amount = prop["remitted_amount_cents"]
        provisional = calc.provisional_fee(contract_fee_pct, prop["amount_cents"])
        ent = {
            "id": new_id(),
            "property_id": property_id,
            "claimant_owner_id": claimant_owner_id,
            "recovery_firm_id": recovery_firm_id,
            "filed_by": filed_by,
            "contract_fee_pct": contract_fee_pct,
            "claim_amount_cents": claim_amount,
            "provisional_fee_cents": provisional,
            "fee_cents": 0,
            "admin_deduction_cents": 0,
            "net_payout_cents": 0,
            "examiner_user_id": None,
            "approver_user_id": None,
            "status": "FILED",
        }
        stamp_new(ent)
        STORE.claims[ent["id"]] = ent
        return ok(serialize(ent), 201)

    @app.get("/claims/<cid>")
    @require_roles("StateAdmin", "StateExaminer", "StateApprover", "Owner", "RecoveryAgent")
    def get_claim(cid):
        return ok(serialize(lookups.claim(cid)))

    @app.get("/claims")
    @require_roles("StateAdmin", "StateExaminer", "StateApprover", "Owner", "RecoveryAgent")
    def list_claims():
        items = list(STORE.claims.values())
        for key in ("property_id", "claimant_owner_id", "recovery_firm_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [c for c in items if c.get(key) == val]
        items = serialize_list(items)
        page, limit, offset, total = paginate(items)
        return ok_list([serialize(c) for c in page], limit, offset, total)

    @app.post("/claims/<cid>/examine")
    @require_roles("StateExaminer")
    def examine_claim(cid):
        claim = lookups.claim(cid)
        if claim["status"] != "FILED":
            raise ApiError("ERR_INVALID_STATE", 409, "Claim is not FILED.")
        claim["examiner_user_id"] = g.user_id
        claim["status"] = "UNDER_REVIEW"
        touch(claim)
        return ok(serialize(claim))

    @app.post("/claims/<cid>/request-evidence")
    @require_roles("StateExaminer")
    def request_evidence(cid):
        claim = lookups.claim(cid)
        if claim["status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE", 409, "Claim is not UNDER_REVIEW.")
        claim["status"] = "NEEDS_EVIDENCE"
        touch(claim)
        return ok(serialize(claim))

    @app.post("/claims/<cid>/evidence")
    @require_roles("Owner", "RecoveryAgent")
    def upload_evidence(cid):
        claim = lookups.claim(cid)
        body = get_json()
        doc_type = require_enum(body, "doc_type", DOC_TYPES)
        ent = {
            "id": new_id(),
            "claim_id": claim["id"],
            "doc_type": doc_type,
            "reviewed_by_user_id": None,
            "status": "PENDING",
        }
        stamp_new(ent)
        STORE.evidence[ent["id"]] = ent
        return ok(serialize(ent), 201)

    @app.get("/claims/<cid>/evidence")
    @require_roles("StateAdmin", "StateExaminer", "StateApprover", "Owner", "RecoveryAgent")
    def list_evidence(cid):
        lookups.claim(cid)
        items = [e for e in STORE.evidence.values() if e["claim_id"] == cid]
        items = serialize_list(items)
        page, limit, offset, total = paginate(items)
        return ok_list([serialize(e) for e in page], limit, offset, total)

    @app.post("/claims/<cid>/evidence/<doc_id>/review")
    @require_roles("StateExaminer")
    def review_evidence(cid, doc_id):
        lookups.claim(cid)
        doc = lookups.evidence(doc_id)
        if doc["claim_id"] != cid:
            raise ApiError("ERR_EVIDENCE_NOT_FOUND", 404, "Evidence does not belong to this claim.")
        body = get_json()
        decision = require_enum(body, "decision", DECISIONS)
        doc["status"] = decision
        doc["reviewed_by_user_id"] = g.user_id
        touch(doc)
        return ok(serialize(doc))

    @app.post("/claims/<cid>/resubmit")
    @require_roles("Owner", "RecoveryAgent")
    def resubmit_claim(cid):
        claim = lookups.claim(cid)
        if claim["status"] != "NEEDS_EVIDENCE":
            raise ApiError("ERR_INVALID_STATE", 409, "Claim is not NEEDS_EVIDENCE.")
        has_accepted = any(e["claim_id"] == cid and e["status"] == "ACCEPTED"
                           for e in STORE.evidence.values())
        if not has_accepted:
            raise ApiError("ERR_INVALID_STATE", 409, "No accepted evidence to resubmit.")
        claim["status"] = "UNDER_REVIEW"
        touch(claim)
        return ok(serialize(claim))

    @app.post("/claims/<cid>/approve")
    @require_roles("StateApprover")
    def approve_claim(cid):
        claim = lookups.claim(cid)
        if claim["status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE", 409, "Claim is not UNDER_REVIEW.")
        if g.user_id == claim["examiner_user_id"]:
            raise ApiError("ERR_SOD_VIOLATION", 403, "Approver must differ from examiner.")
        prop = STORE.properties.get(claim["property_id"])
        if prop is None or prop["status"] != "ESCHEATED":
            raise ApiError("ERR_INVALID_STATE", 409, "Property is not ESCHEATED.")
        pending = any(e["claim_id"] == cid and e["status"] == "PENDING"
                      for e in STORE.evidence.values())
        if pending:
            raise ApiError("ERR_EVIDENCE_REQUIRED", 422, "Evidence still pending review.")
        fee, admin, net = calc.payout_waterfall(claim["contract_fee_pct"], claim["claim_amount_cents"])
        claim["fee_cents"] = fee
        claim["admin_deduction_cents"] = admin
        claim["net_payout_cents"] = net
        claim["approver_user_id"] = g.user_id
        claim["status"] = "APPROVED"
        touch(claim)
        return ok(serialize(claim))

    @app.post("/claims/<cid>/pay")
    @require_roles("StateApprover")
    def pay_claim(cid):
        claim = lookups.claim(cid)
        if claim["status"] != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", 409, "Claim is not APPROVED.")
        if g.user_id == claim["examiner_user_id"]:
            raise ApiError("ERR_SOD_VIOLATION", 403, "Payer must differ from examiner.")
        claim["status"] = "PAID"
        prop = STORE.properties.get(claim["property_id"])
        if prop is not None:
            prop["status"] = "CLAIMED"
            touch(prop)
            account = lookups.find_state_account_by_code(prop["escheat_state"])
            if account is None:
                raise ApiError("ERR_STATE_ACCOUNT_NOT_FOUND", 404, "No custody account.")
            ledger.write_entry(account, "PAYOUT_OUT", claim["net_payout_cents"],
                               property_id=prop["id"], ref_claim_id=claim["id"])
            ledger.write_entry(account, "FEE_OUT", claim["fee_cents"],
                               property_id=prop["id"], ref_claim_id=claim["id"])
        touch(claim)
        return ok(serialize(claim))

    @app.post("/claims/<cid>/deny")
    @require_roles("StateExaminer")
    def deny_claim(cid):
        claim = lookups.claim(cid)
        if claim["status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE", 409, "Claim is not UNDER_REVIEW.")
        claim["status"] = "DENIED"
        touch(claim)
        return ok(serialize(claim))

    @app.post("/claims/<cid>/void")
    @require_roles("StateApprover")
    def void_claim(cid):
        claim = lookups.claim(cid)
        if claim["status"] != "PAID":
            raise ApiError("ERR_INVALID_STATE", 409, "Claim is not PAID.")
        claim["status"] = "VOIDED"
        prop = STORE.properties.get(claim["property_id"])
        if prop is not None:
            prop["status"] = "ESCHEATED"
            touch(prop)
            account = lookups.find_state_account_by_code(prop["escheat_state"])
            if account is None:
                raise ApiError("ERR_STATE_ACCOUNT_NOT_FOUND", 404, "No custody account.")
            amount = claim["net_payout_cents"] + claim["fee_cents"]
            ledger.write_entry(account, "CLAWBACK_IN", amount,
                               property_id=prop["id"], ref_claim_id=claim["id"])
        touch(claim)
        return ok(serialize(claim))
