"""Warranty cover, claims and adjudication (PRD 3.9)."""

from flask import Blueprint, jsonify, request

import calc
import serialize
import services
from core import (
    CLAIM_STATUSES, CLOCK, DB, DECISIONS, LOCK, VOID_REASONS,
    WARRANTY_STATUSES, Ctx, by_created, fail, make_row, need_other,
    not_terminal, ok, page, parse_date, touch,
)

bp = Blueprint("warranty", __name__)

WARRANTY_TERMINAL = ("VOIDED", "EXPIRED")
CLAIM_TERMINAL = ("APPROVED_RESERVICE", "APPROVED_CREDIT", "DENIED")


def _claim_client(claim):
    warranty = DB.warranties.get(claim["warranty_id"])
    return warranty["client_id"] if warranty else None


@bp.get("/warranties")
def list_warranties():
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Technician", "Client"])
        client_filter = request.args.get("client_id")
        if client_filter:
            ctx.scope_client(client_filter)
        status_f = ctx.enum_q("status", WARRANTY_STATUSES)
        limit, offset = ctx.pagination()
        rows = by_created(DB.rows("warranties"))
        for key in ("instrument_id", "service_order_id", "client_id"):
            value = request.args.get(key)
            if value:
                rows = [r for r in rows if r[key] == value]
        if status_f:
            rows = [r for r in rows if r["status"] == status_f]
        if ctx.is_client:
            rows = [r for r in rows if r["client_id"] == ctx.user_id]
        payload, http = page(rows, limit, offset, serialize.warranty)
        return jsonify(payload), http


@bp.get("/warranties/<wid>")
def read_warranty(wid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Technician", "Client"])
        existing = DB.warranties.get(wid)
        if existing is not None:
            ctx.scope_client(existing["client_id"])
        row = need_other("warranties", wid)
        payload, status = ok(serialize.warranty(row))
        return jsonify(payload), status


@bp.post("/warranties/<wid>/void")
def void_warranty(wid):
    with LOCK:
        ctx = Ctx(["ShopManager", "PlatformAdmin"])
        ctx.read_body(["void_reason"])
        reason = ctx.enum("void_reason", VOID_REASONS)
        warranty = need_other("warranties", wid)
        not_terminal(warranty["status"], WARRANTY_TERMINAL)
        if warranty["status"] not in ("ACTIVE", "TRANSFERRED"):
            fail("ERR_INVALID_STATE",
                 "No warranty edge from %s to VOIDED." % warranty["status"])
        services.void_warranty(warranty, reason)
        payload, status = ok(serialize.warranty(warranty))
        return jsonify(payload), status


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

@bp.post("/warranty-claims")
def create_warranty_claim():
    with LOCK:
        ctx = Ctx(["Client", "ShopManager", "PlatformAdmin"])
        peek = ctx.peek_body()
        pre = DB.warranties.get(peek.get("warranty_id")) \
            if isinstance(peek.get("warranty_id"), str) else None
        if pre is not None:
            ctx.scope_client(pre["client_id"])

        body = ctx.read_body(["warranty_id", "reported_issue",
                              "expected_warranty_version"])
        warranty = need_other("warranties", body["warranty_id"])
        client = DB.clients.get(warranty["client_id"])
        if client is not None and client["status"] != "ACTIVE":
            fail("ERR_CLIENT_NOT_ACTIVE", "The owning client is not ACTIVE.")
        if body["expected_warranty_version"] != warranty["version"]:
            fail("ERR_STALE_WARRANTY_VERSION",
                 "expected_warranty_version does not match.")

        # rung 44 -- MUTATE-THEN-REJECT: the warranty is voided on the way out.
        instrument = DB.instruments.get(warranty["instrument_id"])
        location = DB.locations.get(instrument["current_location_id"]) \
            if instrument else None
        if location is not None and location.get("out_of_band_flag"):
            if warranty["status"] in ("ACTIVE", "TRANSFERRED"):
                services.void_warranty(warranty, "CLIMATE_OUT_OF_BAND")
            fail("ERR_CLIMATE_OUT_OF_BAND",
                 "The instrument's location is judged out of band.")

        if warranty["claim_count"] >= calc.WARRANTY_CLAIM_LIMIT:
            fail("ERR_ATTEMPT_LIMIT_EXCEEDED", "The claim cap is reached.")

        fraction, variant, credit = calc.warranty_claim_resolution(
            warranty["covered_price_cents"], warranty["term_days"],
            parse_date(warranty["start_date"]), CLOCK.date)
        warranty["claim_count"] += 1
        touch(warranty)
        claim = make_row(
            warranty_id=warranty["id"],
            service_order_id=warranty["service_order_id"],
            reported_issue=body["reported_issue"],
            elapsed_fraction=fraction,
            resolution_variant=variant,
            credit_cents=credit,
            adjudicated_by_user_id=None,
            status="SUBMITTED",
        )
        DB.warranty_claims[claim["id"]] = claim
        if variant == "PRORATED_CREDIT":
            services.post_ledger(warranty["client_id"], "WARRANTY_CREDIT", credit,
                                 warranty_claim_id=claim["id"])
            services.recompute_balance_for(warranty["client_id"])
        payload, status = ok(serialize.warranty_claim(claim), 201)
        return jsonify(payload), status


@bp.get("/warranty-claims")
def list_warranty_claims():
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Client"])
        status_f = ctx.enum_q("status", CLAIM_STATUSES)
        limit, offset = ctx.pagination()
        rows = by_created(DB.rows("warranty_claims"))
        for key in ("warranty_id", "service_order_id"):
            value = request.args.get(key)
            if value:
                rows = [r for r in rows if r[key] == value]
        if status_f:
            rows = [r for r in rows if r["status"] == status_f]
        if ctx.is_client:
            rows = [r for r in rows if _claim_client(r) == ctx.user_id]
        payload, http = page(rows, limit, offset, serialize.warranty_claim)
        return jsonify(payload), http


@bp.get("/warranty-claims/<cid>")
def read_warranty_claim(cid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Client"])
        existing = DB.warranty_claims.get(cid)
        if existing is not None:
            ctx.scope_client(_claim_client(existing))
        row = need_other("warranty_claims", cid)
        payload, status = ok(serialize.warranty_claim(row))
        return jsonify(payload), status


@bp.post("/warranty-claims/<cid>/review")
def review_warranty_claim(cid):
    with LOCK:
        ctx = Ctx(["ShopManager", "PlatformAdmin"])
        ctx.read_body([])
        claim = need_other("warranty_claims", cid)
        not_terminal(claim["status"], CLAIM_TERMINAL)
        if claim["status"] != "SUBMITTED":
            fail("ERR_INVALID_STATE",
                 "No claim edge from %s to UNDER_REVIEW." % claim["status"])
        claim["status"] = "UNDER_REVIEW"
        touch(claim)
        payload, status = ok(serialize.warranty_claim(claim))
        return jsonify(payload), status


@bp.post("/warranty-claims/<cid>/adjudicate")
def adjudicate_warranty_claim(cid):
    with LOCK:
        ctx = Ctx(["ShopManager", "PlatformAdmin"], sod=True)
        ctx.read_body(["decision"])
        decision = ctx.enum("decision", DECISIONS)
        claim = need_other("warranty_claims", cid)
        not_terminal(claim["status"], CLAIM_TERMINAL)
        if claim["status"] != "UNDER_REVIEW":
            fail("ERR_INVALID_STATE",
                 "No claim edge from %s under adjudication." % claim["status"])

        releasers = set()
        for stone in DB.milestones.values():
            if stone["service_order_id"] == claim["service_order_id"] \
                    and stone["released_by_user_id"]:
                releasers.add(stone["released_by_user_id"])
        if ctx.user_id in releasers:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The adjudicator may not have released a covered milestone.")

        claim["adjudicated_by_user_id"] = ctx.user_id
        if decision == "APPROVE":
            claim["status"] = ("APPROVED_RESERVICE"
                               if claim["resolution_variant"] == "FREE_RESERVICE"
                               else "APPROVED_CREDIT")
            touch(claim)
        else:
            services.deny_claim(claim)
        payload, status = ok(serialize.warranty_claim(claim))
        return jsonify(payload), status
