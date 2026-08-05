"""Referral and MediationSession routes."""

from flask import request

import envelope
import services
import store
from common import (authorize, check_case_ownership, get_body, lookup, owns_case,
                    pagination_params, paginate, require_dt, require_enum,
                    require_str)
from errors import ApiError

REFERRAL_READ_ROLES = {"Clerk", "Landlord", "Tenant", "ProgramAdmin", "Judge"}
MEDIATION_READ_ROLES = {"Clerk", "Landlord", "Tenant", "Mediator", "Judge"}
REFERRAL_TYPES = {"LEGAL_AID", "RENTAL_ASSISTANCE"}
REFERRAL_STATUSES = {"SUBMITTED", "APPROVED", "DENIED", "DISBURSED"}
MEDIATION_STATUSES = {"SCHEDULED", "HELD", "AGREEMENT", "IMPASSE"}


def _scope(case):
    return case is None or owns_case(case)


def register(app):
    # -------------------------------------------------------------- referrals
    @app.route("/referrals", methods=["POST"])
    def create_referral():
        authorize({"Tenant", "Clerk"})
        body = get_body()
        case_id = require_str(body, "case_id")
        referral_type = require_enum(body, "referral_type", REFERRAL_TYPES)
        provider_name = require_str(body, "provider_name")
        case = lookup("cases", case_id)
        check_case_ownership(case)
        if case["status"] not in {"ANSWERED", "IN_DIVERSION"}:
            raise ApiError("ERR_INVALID_STATE", "Referral requires an answered case")
        ref = services.new_entity("referrals", versioned=True)
        ref["case_id"] = case_id
        ref["referral_type"] = referral_type
        ref["provider_name"] = provider_name
        ref["requested_amount_cents"] = 0
        ref["disbursed_amount_cents"] = 0
        ref["status"] = "SUBMITTED"
        if case["status"] == "ANSWERED":
            case["status"] = "IN_DIVERSION"
            services.touch(case)
        return envelope.created(ref)

    @app.route("/referrals/<referral_id>", methods=["GET"])
    def get_referral(referral_id):
        authorize(REFERRAL_READ_ROLES)
        ref = lookup("referrals", referral_id)
        check_case_ownership(store.db["cases"].get(ref["case_id"], {}))
        return envelope.success(ref)

    @app.route("/referrals", methods=["GET"])
    def list_referrals():
        authorize(REFERRAL_READ_ROLES)
        limit, offset = pagination_params()
        args = request.args
        items = []
        for r in store.db["referrals"].values():
            case = store.db["cases"].get(r["case_id"])
            if not _scope(case):
                continue
            if args.get("case_id") and r["case_id"] != args.get("case_id"):
                continue
            if args.get("referral_type") and r["referral_type"] != args.get("referral_type"):
                continue
            if args.get("status") and r["status"] != args.get("status"):
                continue
            items.append(r)
        page, total = paginate(items, limit, offset)
        return envelope.listing(page, limit, offset, total)

    @app.route("/referrals/<referral_id>/transition", methods=["POST"])
    def transition_referral(referral_id):
        authorize({"ProgramAdmin"})
        ref = lookup("referrals", referral_id)
        body = get_body()
        to = require_str(body, "to_status")
        if to not in REFERRAL_STATUSES:
            raise ApiError("ERR_VALIDATION", "Unknown to_status: %s" % to)
        cur = ref["status"]
        case = store.db["cases"].get(ref["case_id"])
        if to == "APPROVED":
            if cur != "SUBMITTED":
                raise ApiError("ERR_INVALID_STATE", "Referral not SUBMITTED")
            if case is not None and (case["sealed"] or case["status"] in services.CASE_TERMINAL):
                raise ApiError("ERR_INVALID_STATE", "Case sealed or terminal")
            if ref["referral_type"] == "RENTAL_ASSISTANCE":
                tenant = store.db["tenants"].get(case["tenant_id"]) if case else None
                award = min(
                    services.final_net_arrears(case) if case else 0,
                    services.income_cap(tenant) if tenant else 0,
                    services.program_budget_remaining(),
                )
                ref["requested_amount_cents"] = award
            ref["status"] = "APPROVED"
            services.touch(ref)
        elif to == "DENIED":
            if cur != "SUBMITTED":
                raise ApiError("ERR_INVALID_STATE", "Referral not SUBMITTED")
            ref["status"] = "DENIED"
            services.touch(ref)
        elif to == "DISBURSED":
            if cur != "APPROVED":
                raise ApiError("ERR_INVALID_STATE", "Referral not APPROVED")
            if ref["referral_type"] != "RENTAL_ASSISTANCE":
                raise ApiError("ERR_NOT_DISBURSABLE", "Only rental assistance may be disbursed")
            budget = services.program_budget_remaining()
            if budget < 1:
                raise ApiError("ERR_ASSISTANCE_BUDGET_EXCEEDED", "Program budget exhausted")
            disbursed = min(
                services.final_net_arrears(case) if case else 0,
                ref["requested_amount_cents"],
                budget,
            )
            ref["disbursed_amount_cents"] = disbursed
            ref["status"] = "DISBURSED"
            services.touch(ref)
            if case is not None:
                services.maybe_satisfy_after_money(case)
        else:
            raise ApiError("ERR_INVALID_STATE", "Illegal referral transition to %s" % to)
        return envelope.success(ref)

    # ------------------------------------------------------ mediation sessions
    @app.route("/mediation-sessions", methods=["POST"])
    def create_mediation():
        authorize({"Clerk", "Mediator"})
        body = get_body()
        case_id = require_str(body, "case_id")
        mediator_user_id = require_str(body, "mediator_user_id")
        scheduled_at = require_dt(body, "scheduled_at")
        case = lookup("cases", case_id)
        if case["status"] not in {"ANSWERED", "IN_DIVERSION"}:
            raise ApiError("ERR_INVALID_STATE", "Mediation requires an answered case")
        ms = services.new_entity("mediation_sessions", versioned=True)
        ms["case_id"] = case_id
        ms["mediator_user_id"] = mediator_user_id
        ms["scheduled_at"] = scheduled_at
        ms["outcome_notes"] = body.get("outcome_notes") or ""
        ms["status"] = "SCHEDULED"
        if case["status"] == "ANSWERED":
            case["status"] = "IN_DIVERSION"
            services.touch(case)
        return envelope.created(ms)

    @app.route("/mediation-sessions/<session_id>", methods=["GET"])
    def get_mediation(session_id):
        authorize(MEDIATION_READ_ROLES)
        ms = lookup("mediation_sessions", session_id)
        check_case_ownership(store.db["cases"].get(ms["case_id"], {}))
        return envelope.success(ms)

    @app.route("/mediation-sessions", methods=["GET"])
    def list_mediation():
        authorize(MEDIATION_READ_ROLES)
        limit, offset = pagination_params()
        args = request.args
        items = []
        for ms in store.db["mediation_sessions"].values():
            case = store.db["cases"].get(ms["case_id"])
            if not _scope(case):
                continue
            if args.get("case_id") and ms["case_id"] != args.get("case_id"):
                continue
            if args.get("status") and ms["status"] != args.get("status"):
                continue
            items.append(ms)
        page, total = paginate(items, limit, offset)
        return envelope.listing(page, limit, offset, total)

    @app.route("/mediation-sessions/<session_id>/transition", methods=["POST"])
    def transition_mediation(session_id):
        authorize({"Mediator"})
        ms = lookup("mediation_sessions", session_id)
        body = get_body()
        to = require_str(body, "to_status")
        if to not in MEDIATION_STATUSES:
            raise ApiError("ERR_VALIDATION", "Unknown to_status: %s" % to)
        cur = ms["status"]
        case = store.db["cases"].get(ms["case_id"])
        if to == "HELD":
            if cur != "SCHEDULED":
                raise ApiError("ERR_INVALID_STATE", "Session not SCHEDULED")
            if store.now() < ms["scheduled_at"]:
                raise ApiError("ERR_INVALID_STATE", "Session cannot be held before scheduled_at")
            if body.get("outcome_notes") is not None:
                ms["outcome_notes"] = body.get("outcome_notes")
            ms["status"] = "HELD"
            services.touch(ms)
        elif to == "AGREEMENT":
            if cur != "HELD":
                raise ApiError("ERR_INVALID_STATE", "Session not HELD")
            if body.get("outcome_notes") is not None:
                ms["outcome_notes"] = body.get("outcome_notes")
            ms["status"] = "AGREEMENT"
            services.touch(ms)
            if case is not None and case["status"] == "IN_LITIGATION":
                case["status"] = "IN_DIVERSION"
                services.touch(case)
        elif to == "IMPASSE":
            if cur != "HELD":
                raise ApiError("ERR_INVALID_STATE", "Session not HELD")
            if body.get("outcome_notes") is not None:
                ms["outcome_notes"] = body.get("outcome_notes")
            ms["status"] = "IMPASSE"
            services.touch(ms)
        elif to == "SCHEDULED":
            if cur != "IMPASSE":
                raise ApiError("ERR_INVALID_STATE", "Session not IMPASSE")
            new_at = require_dt(body, "scheduled_at")
            ms["scheduled_at"] = new_at
            ms["status"] = "SCHEDULED"
            services.touch(ms)
        return envelope.success(ms)
