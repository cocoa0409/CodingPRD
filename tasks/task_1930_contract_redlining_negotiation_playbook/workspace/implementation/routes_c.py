"""Routes: signature packets, obligations, analytics, flat collection endpoints."""
import hashlib
import math
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

from core import (
    db, now, parse_iso, fmt, seconds_between, ok, err, authenticate, body,
    get_or_404, stamp_new, touch, pub, paginate, apply_filters, new_id, ALL_ROLES,
)
from domain import extract_obligations

bp = Blueprint("routes_c", __name__)

ANALYTICS_ROLES = ["LegalCounsel", "FinanceController", "ChiefCounsel", "OpsAdmin"]


def _get_neg(negotiationId):
    return get_or_404(db.negotiations, negotiationId)


def _get_packet(neg, packetId):
    p = get_or_404(db.packets, packetId)
    if p["negotiation_id"] != neg["id"]:
        err("ERR_NOT_FOUND", 404, "Packet %s not found under negotiation %s." % (packetId, neg["id"]))
    return p


# --------------------------------------------------------------------------
# Signature packets
# --------------------------------------------------------------------------


@bp.route("/negotiations/<negotiationId>/signature-packets", methods=["POST"])
def create_packet(negotiationId):
    user, role = authenticate(["LegalCounsel"])
    neg = _get_neg(negotiationId)
    if neg["draft_status"] != "AWAITING_COUNTERSIGN":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Signature packets require AWAITING_COUNTERSIGN.")
    b = body()
    expected = b.get("expected_negotiation_version")
    if expected is None:
        err("ERR_INVALID_REQUEST", 400, "expected_negotiation_version is required.")
    if expected != neg["version"]:
        err("ERR_STALE_VERSION", 412, "Negotiation version has advanced; re-read before creating a packet.")
    for p in db.packets.values():
        if p["negotiation_id"] == neg["id"] and p["status"] in ("ROUTING", "PARTIALLY_SIGNED", "FULLY_SIGNED"):
            err("ERR_SIGNATURE_PACKET_ALREADY_ACTIVE", 409, "Another signature packet is already active.")
    signatories = b.get("signatories")
    if not isinstance(signatories, list) or len(signatories) == 0:
        err("ERR_INVALID_REQUEST", 400, "signatories must be a non-empty array.")
    for s in signatories:
        if not isinstance(s, dict) or "user_id" not in s or "order_index" not in s \
                or "authority_cap_cents" not in s:
            err("ERR_INVALID_REQUEST", 400, "Each signatory requires user_id, order_index, authority_cap_cents.")
    opens = b.get("signature_window_opens_at")
    closes = b.get("signature_window_closes_at")
    if not opens or not closes:
        err("ERR_INVALID_REQUEST", 400, "signature_window_opens_at and signature_window_closes_at are required.")
    try:
        opens_dt = parse_iso(opens)
        closes_dt = parse_iso(closes)
    except ValueError:
        err("ERR_INVALID_REQUEST", 400, "Signature window bounds must be ISO-8601 timestamps.")
    if not closes_dt > opens_dt:
        err("ERR_INVALID_REQUEST", 400, "signature_window_closes_at must be strictly later than opens_at.")
    pkt = {
        "id": new_id(),
        "negotiation_id": neg["id"],
        "signatories": signatories,
        "signature_window_opens_at": opens,
        "signature_window_closes_at": closes,
        "signed_record": [],
        "status": "ROUTING",
    }
    stamp_new(pkt)
    db.packets[pkt["id"]] = pkt
    neg["signature_status"] = "ROUTING"
    touch(neg)
    return ok(pub(pkt), 201)


@bp.route("/negotiations/<negotiationId>/signature-packets", methods=["GET"])
def list_packets(negotiationId):
    authenticate(ALL_ROLES)
    neg = _get_neg(negotiationId)
    items = [p for p in db.packets.values() if p["negotiation_id"] == neg["id"]]
    items = apply_filters(items, [("status", "status")])
    page, info = paginate(items)
    return ok(page, 200, info)


@bp.route("/negotiations/<negotiationId>/signature-packets/<packetId>", methods=["GET"])
def get_packet(negotiationId, packetId):
    authenticate(ALL_ROLES)
    neg = _get_neg(negotiationId)
    return ok(pub(_get_packet(neg, packetId)))


def _next_signatory(pkt):
    signed_ids = {e["user_id"] for e in pkt["signed_record"]}
    remaining = [s for s in pkt["signatories"] if s["user_id"] not in signed_ids]
    if not remaining:
        return None
    remaining.sort(key=lambda s: s["order_index"])
    return remaining[0]


@bp.route("/negotiations/<negotiationId>/signature-packets/<packetId>/sign", methods=["POST"])
def sign_packet(negotiationId, packetId):
    user, role = authenticate(["Signatory"])
    neg = _get_neg(negotiationId)
    pkt = _get_packet(neg, packetId)
    if pkt["status"] not in ("ROUTING", "PARTIALLY_SIGNED"):
        err("ERR_INVALID_STATE_TRANSITION", 409, "Packet is not in a signable state.")
    # 1. authority
    if not (user["can_sign_above_cents"] > neg["contract_value_cents"]):
        err("ERR_SIGNATORY_AUTHORITY_EXCEEDED", 403, "Signatory authority ceiling does not cover this contract value.")
    # 2. window
    n = now()
    opens = parse_iso(pkt["signature_window_opens_at"])
    closes = parse_iso(pkt["signature_window_closes_at"])
    if not (opens <= n <= closes):
        err("ERR_SIGNATURE_WINDOW_VIOLATION", 409, "Current time is outside the signature window.")
    # 3. order
    nxt = _next_signatory(pkt)
    if nxt is None or nxt["user_id"] != user["id"]:
        err("ERR_SIGNATORY_OUT_OF_ORDER", 409, "Signatory is not next in the routing order.")
    signed_at = fmt(n)
    entry = {
        "user_id": user["id"],
        "signed_at": signed_at,
        "signature_hash": hashlib.sha256((user["id"] + signed_at).encode("utf-8")).hexdigest(),
    }
    pkt["signed_record"].append(entry)
    if len(pkt["signed_record"]) >= len(pkt["signatories"]):
        pkt["status"] = "FULLY_SIGNED"
        neg["signature_status"] = "FULLY_SIGNED"
    else:
        pkt["status"] = "PARTIALLY_SIGNED"
        neg["signature_status"] = "PARTIALLY_SIGNED"
    touch(pkt)
    touch(neg)
    return ok(pub(pkt))


@bp.route("/negotiations/<negotiationId>/signature-packets/<packetId>/record-execution", methods=["POST"])
def record_execution(negotiationId, packetId):
    user, role = authenticate(["Signatory"])
    neg = _get_neg(negotiationId)
    pkt = _get_packet(neg, packetId)
    if pkt["status"] != "FULLY_SIGNED":
        err("ERR_SIGNATURE_INCOMPLETE", 409, "Packet is not FULLY_SIGNED.")
    b = body()
    ex_ts_raw = b.get("execution_timestamp")
    if ex_ts_raw is None:
        err("ERR_INVALID_REQUEST", 400, "execution_timestamp is required.")
    try:
        ex_ts = parse_iso(ex_ts_raw)
    except ValueError:
        err("ERR_INVALID_REQUEST", 400, "execution_timestamp must be an ISO-8601 timestamp.")
    opens = parse_iso(pkt["signature_window_opens_at"])
    closes = parse_iso(pkt["signature_window_closes_at"])
    if not (opens <= ex_ts <= closes):
        err("ERR_SIGNATURE_WINDOW_VIOLATION", 409, "execution_timestamp is outside the signature window.")
    for entry in pkt["signed_record"]:
        u = db.users.get(entry["user_id"])
        if u is None or not (u["can_sign_above_cents"] > neg["contract_value_cents"]):
            err("ERR_SIGNATORY_AUTHORITY_EXCEEDED", 403, "A signer's authority ceiling does not cover the final contract value.")
    pkt["status"] = "EXECUTION_RECORDED"
    touch(pkt)
    neg["draft_status"] = "EXECUTED"
    neg["signature_status"] = "EXECUTION_RECORDED"
    neg["cycle_time_seconds"] = seconds_between(parse_iso(neg["created_at"]), ex_ts)
    neg["_executed_at"] = fmt(ex_ts)
    touch(neg)
    cp = db.counterparties.get(neg["counterparty_id"])
    if cp is not None:
        cp["last_executed_at"] = fmt(ex_ts)
        cp["active_negotiation_count"] -= 1
        touch(cp)
    pb = db.playbooks.get(neg["playbook_id"])
    if pb is not None:
        pb["active_negotiation_count"] -= 1
        touch(pb)
    offsets = {}
    default_offset = 0
    raw_offsets = b.get("obligation_offsets")
    if isinstance(raw_offsets, list):
        for o in raw_offsets:
            if isinstance(o, dict) and "clause_template_id" in o:
                offsets[o["clause_template_id"]] = o.get("due_offset_days", 0)
    if isinstance(b.get("due_offset_days"), int):
        default_offset = b["due_offset_days"]
    extract_obligations(neg, offsets, default_offset)
    return ok(pub(neg))


@bp.route("/negotiations/<negotiationId>/signature-packets/<packetId>/void", methods=["POST"])
def void_packet(negotiationId, packetId):
    user, role = authenticate(["LegalCounsel"])
    neg = _get_neg(negotiationId)
    pkt = _get_packet(neg, packetId)
    if pkt["status"] in ("VOIDED", "EXECUTION_RECORDED", "EXPIRED"):
        err("ERR_INVALID_STATE_TRANSITION", 409, "Packet is not in a voidable state.")
    if len(pkt["signed_record"]) > 0:
        err("ERR_SIGNATURE_ALREADY_STARTED", 409, "Packet already has signatures and cannot be voided.")
    pkt["status"] = "VOIDED"
    touch(pkt)
    neg["signature_status"] = "NOT_STARTED"
    touch(neg)
    return ok(pub(pkt))


# --------------------------------------------------------------------------
# Obligations
# --------------------------------------------------------------------------

OBLIGATION_FILTERS = [
    ("owner_role", "owner_role"),
    ("extraction_source", "extraction_source"),
    ("clause_template_id", "clause_template_id"),
]


@bp.route("/negotiations/<negotiationId>/obligations", methods=["GET"])
def list_obligations_nested(negotiationId):
    authenticate(ALL_ROLES)
    neg = _get_neg(negotiationId)
    items = [o for o in db.obligations.values() if o["negotiation_id"] == neg["id"]]
    items = apply_filters(items, OBLIGATION_FILTERS)
    page, info = paginate(items)
    return ok(page, 200, info)


@bp.route("/obligations", methods=["GET"])
def list_obligations_flat():
    authenticate(ALL_ROLES)
    items = apply_filters(
        list(db.obligations.values()),
        [("negotiation_id", "negotiation_id")] + OBLIGATION_FILTERS,
    )
    page, info = paginate(items)
    return ok(page, 200, info)


@bp.route("/obligations/<obligationId>", methods=["GET"])
def get_obligation(obligationId):
    authenticate(ALL_ROLES)
    return ok(pub(get_or_404(db.obligations, obligationId)))


# --------------------------------------------------------------------------
# Flat collections
# --------------------------------------------------------------------------


@bp.route("/triage-decisions", methods=["GET"])
def list_triage_decisions_flat():
    authenticate(ALL_ROLES)
    items = apply_filters(list(db.triage_decisions.values()), [("intake_request_id", "intake_request_id")])
    page, info = paginate(items)
    return ok(page, 200, info)


@bp.route("/triage-decisions/<triageDecisionId>", methods=["GET"])
def get_triage_decision(triageDecisionId):
    authenticate(ALL_ROLES)
    return ok(pub(get_or_404(db.triage_decisions, triageDecisionId)))


@bp.route("/rounds", methods=["GET"])
def list_rounds_flat():
    authenticate(ALL_ROLES)
    items = apply_filters(
        list(db.rounds.values()),
        [("negotiation_id", "negotiation_id"), ("status", "status"),
         ("opened_by_user_id", "opened_by_user_id"), ("closed_by_user_id", "closed_by_user_id")],
    )
    page, info = paginate(items)
    return ok(page, 200, info)


@bp.route("/rounds/<roundId>", methods=["GET"])
def get_round_flat(roundId):
    authenticate(ALL_ROLES)
    return ok(pub(get_or_404(db.rounds, roundId)))


@bp.route("/deviations", methods=["GET"])
def list_deviations_flat():
    authenticate(ALL_ROLES)
    items = apply_filters(
        list(db.deviations.values()),
        [("negotiation_id", "negotiation_id"), ("status", "status"),
         ("severity", "severity"), ("clause_template_id", "clause_template_id"),
         ("round_id", "round_id"), ("assigned_approver_id", "assigned_approver_id")],
    )
    page, info = paginate(items)
    return ok(page, 200, info)


@bp.route("/deviations/<deviationId>", methods=["GET"])
def get_deviation_flat(deviationId):
    authenticate(ALL_ROLES)
    return ok(pub(get_or_404(db.deviations, deviationId)))


@bp.route("/approval-decisions", methods=["GET"])
def list_decisions_flat():
    authenticate(ALL_ROLES)
    items = apply_filters(
        list(db.decisions.values()),
        [("deviation_id", "deviation_id"), ("decided_by_user_id", "decided_by_user_id")],
    )
    page, info = paginate(items)
    return ok(page, 200, info)


@bp.route("/approval-decisions/<decisionId>", methods=["GET"])
def get_decision_flat(decisionId):
    authenticate(ALL_ROLES)
    return ok(pub(get_or_404(db.decisions, decisionId)))


@bp.route("/signature-packets", methods=["GET"])
def list_packets_flat():
    authenticate(ALL_ROLES)
    items = apply_filters(
        list(db.packets.values()),
        [("negotiation_id", "negotiation_id"), ("status", "status")],
    )
    page, info = paginate(items)
    return ok(page, 200, info)


@bp.route("/signature-packets/<packetId>", methods=["GET"])
def get_packet_flat(packetId):
    authenticate(ALL_ROLES)
    return ok(pub(get_or_404(db.packets, packetId)))


# --------------------------------------------------------------------------
# Analytics
# --------------------------------------------------------------------------


def _parse_window():
    from flask import request
    from_iso = request.args.get("from_iso")
    to_iso = request.args.get("to_iso")
    if not from_iso or not to_iso:
        err("ERR_INVALID_REQUEST", 400, "from_iso and to_iso are required.")
    try:
        return parse_iso(from_iso), parse_iso(to_iso)
    except ValueError:
        err("ERR_INVALID_REQUEST", 400, "from_iso and to_iso must be ISO-8601 timestamps.")


def _percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    rank = math.ceil(p / 100 * len(sorted_vals))
    if rank < 1:
        rank = 1
    return sorted_vals[rank - 1]


def _mean(vals):
    if not vals:
        return None
    m = Decimal(sum(vals)) / Decimal(len(vals))
    return int(m.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@bp.route("/analytics/cycle-time", methods=["GET"])
def analytics_cycle_time():
    authenticate(ANALYTICS_ROLES)
    from_dt, to_dt = _parse_window()
    from flask import request
    ct_filter = request.args.get("contract_type_id")
    cohort = request.args.get("cohort")
    values = []
    if cohort is None or str(cohort).lower() in ("executed",):
        for neg in db.negotiations.values():
            if neg["draft_status"] != "EXECUTED" or not neg.get("_executed_at"):
                continue
            if ct_filter and neg["contract_type_id"] != ct_filter:
                continue
            ex = parse_iso(neg["_executed_at"])
            if from_dt <= ex < to_dt:
                values.append(neg["cycle_time_seconds"])
    elif str(cohort).lower() in ("active", "in_flight", "inflight"):
        n = now()
        for neg in db.negotiations.values():
            if neg["draft_status"] in ("EXECUTED", "ABORTED"):
                continue
            if ct_filter and neg["contract_type_id"] != ct_filter:
                continue
            values.append(seconds_between(parse_iso(neg["created_at"]), n))
    else:
        err("ERR_INVALID_REQUEST", 400, "cohort must be 'executed' or 'active'.")
    values.sort()
    return ok({
        "cohort_size": len(values),
        "p50_seconds": _percentile(values, 50),
        "p90_seconds": _percentile(values, 90),
        "p99_seconds": _percentile(values, 99),
        "mean_seconds": _mean(values),
    })


@bp.route("/analytics/bottlenecks", methods=["GET"])
def analytics_bottlenecks():
    authenticate(ANALYTICS_ROLES)
    from_dt, to_dt = _parse_window()
    from flask import request
    ct_filter = request.args.get("contract_type_id")

    def neg_ok(neg_id):
        neg = db.negotiations.get(neg_id)
        if neg is None:
            return False
        if ct_filter and neg["contract_type_id"] != ct_filter:
            return False
        return True

    legal_review = 0
    escalated = 0
    for d in db.deviations.values():
        if d["resolved_at"] is None or not neg_ok(d["negotiation_id"]):
            continue
        resolved = parse_iso(d["resolved_at"])
        if not (from_dt <= resolved < to_dt):
            continue
        span = seconds_between(parse_iso(d["opened_at"]), resolved)
        if d.get("escalated_to_chief_counsel"):
            escalated += span
        else:
            legal_review += span
    drafter_rework = 0
    for r in db.rounds.values():
        if r.get("clause_change_count", 0) <= 0 or r.get("round_duration_seconds") is None:
            continue
        if not neg_ok(r["negotiation_id"]):
            continue
        if r["closed_at"] is None:
            continue
        closed = parse_iso(r["closed_at"])
        if from_dt <= closed < to_dt:
            drafter_rework += r["round_duration_seconds"]
    signature_wait = 0
    for p in db.packets.values():
        if p["status"] != "EXECUTION_RECORDED" or not p["signed_record"]:
            continue
        if not neg_ok(p["negotiation_id"]):
            continue
        last_signed = max(parse_iso(e["signed_at"]) for e in p["signed_record"])
        if from_dt <= last_signed < to_dt:
            signature_wait += seconds_between(parse_iso(p["signature_window_opens_at"]), last_signed)
    totals = [
        ("escalated_seconds", escalated),
        ("legal_review_seconds", legal_review),
        ("drafter_rework_seconds", drafter_rework),
        ("signature_wait_seconds", signature_wait),
    ]
    best = max(t for _, t in totals)
    primary = next(name for name, t in totals if t == best)
    return ok({
        "legal_review_seconds": legal_review,
        "escalated_seconds": escalated,
        "drafter_rework_seconds": drafter_rework,
        "signature_wait_seconds": signature_wait,
        "primary_bottleneck": primary,
    })
