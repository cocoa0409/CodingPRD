"""RecoveryClaim endpoints."""

from flask import request

from db import STORE, create_entity, touch, public, sort_default
from errors import (ApiError, ERR_INVALID_STATE, ERR_INVALID_REQUEST,
                    ERR_AMOUNT_INVALID, ERR_CLAIM_EXCEEDS_PAID,
                    ERR_RECOVERY_EXCEEDS_CLAIMED)
from middleware import (authenticate, require_roles, guard_read_scope,
                        guard_mutation_scope, in_read_scope,
                        require_client_active, resolve, READ_ROLES)
from response import success_object, success_list
from validate import get_body, check_shape, parse_pagination

CHANNELS = ["CREDIT_MEMO", "REFUND", "OFFSET"]
CLAIM_OUTCOMES = ["ACKNOWLEDGE", "REBUT"]


def register(app):

    @app.route("/fap/invoices/<iid>/recovery-claims", methods=["POST"])
    def create_claim(iid):
        uid, role = authenticate()
        require_roles(role, {"AuditAnalyst"})
        invoice = resolve(STORE.invoices, iid)
        require_client_active(STORE.clients.get(invoice["client_id"]))
        body = get_body(allow_empty=False)
        check_shape(body, {
            "claimed_amount_minor": {"kind": "integer", "required": True},
            "channel": {"kind": "string", "required": True, "enum": CHANNELS},
        })
        # Stage 6: the invoice must be PAID or SHORT_PAID.
        if invoice["payment_status"] not in ("PAID", "SHORT_PAID"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Recovery claims require a PAID or SHORT_PAID invoice")
        # Stage 11: fiscal amounts.
        if body["claimed_amount_minor"] <= 0:
            raise ApiError(ERR_AMOUNT_INVALID, 422,
                           "claimed_amount_minor must be positive")
        if body["claimed_amount_minor"] > invoice["paid_minor"]:
            raise ApiError(ERR_CLAIM_EXCEEDS_PAID, 409,
                           "claimed_amount_minor exceeds invoice paid_minor")
        claim = create_entity(STORE.claims, {
            "client_id": invoice["client_id"],
            "invoice_id": invoice["id"],
            "claimed_amount_minor": body["claimed_amount_minor"],
            "channel": body["channel"],
            "recovered_minor": 0,
            "status": "DRAFTED",
        })
        return success_object(public(claim), status=201)

    @app.route("/fap/clients/<cid>/recovery-claims", methods=["GET"])
    def list_client_claims(cid):
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        client = guard_read_scope(role, uid, "client", STORE.clients.get(cid))
        limit, offset = parse_pagination()
        rows = [c for c in STORE.claims.values() if c["client_id"] == cid]
        rows = [c for c in rows if in_read_scope(role, uid, "claim", c)]
        status = request.args.get("status")
        if status is not None:
            rows = [c for c in rows if c["status"] == status]
        rows = sort_default(rows)
        total = len(rows)
        page = rows[offset:offset + limit]
        return success_list([public(c) for c in page], limit, offset, total)

    @app.route("/fap/recovery-claims/<cid>/file", methods=["POST"])
    def file_claim(cid):
        uid, role = authenticate()
        require_roles(role, {"AuditAnalyst"})
        claim = resolve(STORE.claims, cid)
        require_client_active(STORE.clients.get(claim["client_id"]))
        body = get_body()
        check_shape(body, {})
        if claim["status"] not in ("DRAFTED", "REBUTTED"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Claim cannot be filed from %s" % claim["status"])
        claim["status"] = "FILED"
        touch(claim)
        return success_object(public(claim))

    @app.route("/fap/recovery-claims/<cid>/carrier_respond", methods=["POST"])
    def claim_carrier_respond(cid):
        uid, role = authenticate()
        require_roles(role, {"CarrierRep"})
        claim = resolve(STORE.claims, cid)
        guard_mutation_scope(role, uid, "claim", claim)
        require_client_active(STORE.clients.get(claim["client_id"]))
        body = get_body(allow_empty=False)
        check_shape(body, {
            "outcome": {"kind": "string", "required": True,
                        "enum": CLAIM_OUTCOMES},
        })
        if claim["status"] != "FILED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Claim cannot be answered from %s" % claim["status"])
        claim["status"] = ("ACKNOWLEDGED" if body["outcome"] == "ACKNOWLEDGE"
                           else "REBUTTED")
        touch(claim)
        return success_object(public(claim))

    @app.route("/fap/recovery-claims/<cid>/collect", methods=["POST"])
    def collect_claim(cid):
        uid, role = authenticate()
        require_roles(role, {"FinanceController"})
        claim = resolve(STORE.claims, cid)
        require_client_active(STORE.clients.get(claim["client_id"]))
        body = get_body(allow_empty=False)
        check_shape(body, {
            "recovered_minor": {"kind": "integer", "required": True},
        })
        if claim["status"] != "ACKNOWLEDGED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Claim cannot be collected from %s" % claim["status"])
        recovered = body["recovered_minor"]
        if recovered < 0:
            raise ApiError(ERR_AMOUNT_INVALID, 422,
                           "recovered_minor must be non-negative")
        if recovered > claim["claimed_amount_minor"]:
            raise ApiError(ERR_RECOVERY_EXCEEDS_CLAIMED, 409,
                           "recovered_minor exceeds claimed_amount_minor")
        claim["recovered_minor"] = recovered
        claim["status"] = "COLLECTED"
        touch(claim)
        return success_object(public(claim))

    @app.route("/fap/recovery-claims/<cid>/abandon", methods=["POST"])
    def abandon_claim(cid):
        uid, role = authenticate()
        require_roles(role, {"AuditAnalyst"})
        claim = resolve(STORE.claims, cid)
        require_client_active(STORE.clients.get(claim["client_id"]))
        body = get_body()
        check_shape(body, {})
        if claim["status"] not in ("DRAFTED", "FILED", "REBUTTED"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Claim cannot be abandoned from %s" % claim["status"])
        claim["status"] = "ABANDONED"
        touch(claim)
        return success_object(public(claim))
