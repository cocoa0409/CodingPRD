"""Routes: negotiations, rounds, deviations, decisions, signature packets,
obligations, analytics, and flat collection endpoints."""
import hashlib
from datetime import timedelta

from flask import Blueprint

from core import (
    db, now, parse_iso, fmt, seconds_between, ok, err, authenticate, body,
    get_or_404, stamp_new, stamp_audit, touch, pub, paginate, apply_filters,
    new_id, ALL_ROLES, LADDER,
)
from domain import (
    compute_value_tier, compute_risk_score, compute_required_role, pick_approver,
    recompute_deviation_counters, current_open_round, close_round,
    extract_obligations,
)

bp = Blueprint("routes_b", __name__)

REVIEW_ROLES = ["LegalCounsel", "BusinessOwner", "FinanceController", "ChiefCounsel"]
DECISIONS = {"APPROVE", "REJECT", "ESCALATE", "ABSTAIN"}


def _get_neg(negotiationId):
    return get_or_404(db.negotiations, negotiationId)


def _get_dev(neg, deviationId):
    d = get_or_404(db.deviations, deviationId)
    if d["negotiation_id"] != neg["id"]:
        err("ERR_NOT_FOUND", 404, "Deviation %s not found under negotiation %s." % (deviationId, neg["id"]))
    return d


def _get_round(neg, roundId):
    r = get_or_404(db.rounds, roundId)
    if r["negotiation_id"] != neg["id"]:
        err("ERR_NOT_FOUND", 404, "Round %s not found under negotiation %s." % (roundId, neg["id"]))
    return r


def _get_packet(neg, packetId):
    p = get_or_404(db.packets, packetId)
    if p["negotiation_id"] != neg["id"]:
        err("ERR_NOT_FOUND", 404, "Packet %s not found under negotiation %s." % (packetId, neg["id"]))
    return p


# --------------------------------------------------------------------------
# Negotiations
# --------------------------------------------------------------------------


@bp.route("/negotiations", methods=["GET"])
def list_negotiations():
    authenticate(ALL_ROLES)
    items = apply_filters(
        list(db.negotiations.values()),
        [
            ("intake_request_id", "intake_request_id"),
            ("playbook_id", "playbook_id"),
            ("contract_type_id", "contract_type_id"),
            ("counterparty_id", "counterparty_id"),
            ("business_owner_id", "business_owner_id"),
            ("legal_counsel_id", "legal_counsel_id"),
            ("drafter_user_id", "drafter_user_id"),
            ("draft_status", "draft_status"),
            ("approval_status", "approval_status"),
            ("signature_status", "signature_status"),
        ],
    )
    page, info = paginate(items)
    return ok(page, 200, info)


@bp.route("/negotiations/<negotiationId>", methods=["GET"])
def get_negotiation(negotiationId):
    authenticate(ALL_ROLES)
    return ok(pub(_get_neg(negotiationId)))


# --------------------------------------------------------------------------
# Rounds
# --------------------------------------------------------------------------


@bp.route("/negotiations/<negotiationId>/rounds", methods=["POST"])
def open_round(negotiationId):
    user, role = authenticate(["ContractAnalyst"])
    neg = _get_neg(negotiationId)
    if neg["draft_status"] not in ("OPEN", "REDLINING"):
        err("ERR_INVALID_STATE_TRANSITION", 409, "Negotiation is not in a state that opens rounds.")
    if current_open_round(neg["id"]) is not None:
        err("ERR_ROUND_ALREADY_OPEN", 409, "A round is already OPEN for this negotiation.")
    if neg["draft_status"] == "OPEN" and neg["current_round_index"] != 0:
        err("ERR_INVALID_STATE_TRANSITION", 409, "Inconsistent round state.")
    b = body()
    if not b.get("change_summary") or not isinstance(b.get("change_summary"), str):
        err("ERR_INVALID_REQUEST", 400, "change_summary is required.")
    idx = neg["current_round_index"] + 1
    rnd = {
        "id": new_id(),
        "negotiation_id": neg["id"],
        "round_index": idx,
        "opened_at": fmt(now()),
        "closed_at": None,
        "opened_by_user_id": user["id"],
        "closed_by_user_id": None,
        "status": "OPEN",
        "change_summary": b["change_summary"],
        "clause_change_count": 0,
        "round_duration_seconds": None,
    }
    stamp_audit(rnd)
    db.rounds[rnd["id"]] = rnd
    neg["current_round_index"] = idx
    neg["total_rounds"] += 1
    if neg["draft_status"] == "OPEN":
        neg["draft_status"] = "REDLINING"
    touch(neg)
    return ok(pub(rnd), 201)


@bp.route("/negotiations/<negotiationId>/rounds", methods=["GET"])
def list_rounds(negotiationId):
    authenticate(ALL_ROLES)
    neg = _get_neg(negotiationId)
    items = [r for r in db.rounds.values() if r["negotiation_id"] == neg["id"]]
    items = apply_filters(
        items,
        [("status", "status"), ("opened_by_user_id", "opened_by_user_id"),
         ("closed_by_user_id", "closed_by_user_id")],
    )
    page, info = paginate(items)
    return ok(page, 200, info)


@bp.route("/negotiations/<negotiationId>/rounds/<roundId>", methods=["GET"])
def get_round(negotiationId, roundId):
    authenticate(ALL_ROLES)
    neg = _get_neg(negotiationId)
    return ok(pub(_get_round(neg, roundId)))


@bp.route("/negotiations/<negotiationId>/rounds/<roundId>/close", methods=["POST"])
def close_round_endpoint(negotiationId, roundId):
    user, role = authenticate(["ContractAnalyst"])
    neg = _get_neg(negotiationId)
    rnd = _get_round(neg, roundId)
    if rnd["status"] != "OPEN":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only an OPEN round can be closed.")
    if neg["blocking_deviation_count"] != 0:
        err("ERR_DEVIATIONS_BLOCKING_ROUND_CLOSE", 409, "Blocking deviations prevent round close.")
    close_round(rnd, user["id"])
    touch(neg)
    return ok(pub(rnd))


# --------------------------------------------------------------------------
# Finalize / abort
# --------------------------------------------------------------------------


@bp.route("/negotiations/<negotiationId>/finalize-redlining", methods=["POST"])
def finalize_redlining(negotiationId):
    user, role = authenticate(["LegalCounsel"])
    neg = _get_neg(negotiationId)
    if neg["approval_status"] not in ("NO_DEVIATIONS", "APPROVED_WITH_DEVIATIONS"):
        err("ERR_DEVIATIONS_UNRESOLVED", 409, "Approval dimension is not settled.")
    if neg["draft_status"] != "REDLINING":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Negotiation is not REDLINING.")
    rnd = current_open_round(neg["id"])
    if rnd is None:
        err("ERR_INVALID_STATE_TRANSITION", 409, "The current round is not OPEN.")
    pb = db.playbooks.get(neg["playbook_id"])
    b = body()
    override = b.get("playbook_staleness_override") is True
    if pb is not None and neg["playbook_version_at_pin"] != pb["version"] and not override:
        err("ERR_PLAYBOOK_STALE", 409, "Playbook has drifted since the negotiation was pinned.")
    close_round(rnd, user["id"])
    neg["draft_status"] = "AWAITING_COUNTERSIGN"
    touch(neg)
    return ok(pub(neg))


@bp.route("/negotiations/<negotiationId>/abort", methods=["POST"])
def abort_negotiation(negotiationId):
    user, role = authenticate(["ContractAnalyst", "LegalCounsel"])
    neg = _get_neg(negotiationId)
    if neg["draft_status"] in ("EXECUTED", "ABORTED"):
        err("ERR_INVALID_STATE_TRANSITION", 409, "Negotiation is already terminal.")
    if neg["draft_status"] == "AWAITING_COUNTERSIGN":
        if role != "LegalCounsel":
            err("ERR_FORBIDDEN_FOR_ROLE", 403, "Only LegalCounsel may abort from AWAITING_COUNTERSIGN.")
        for p in db.packets.values():
            if p["negotiation_id"] == neg["id"] and p["status"] in ("FULLY_SIGNED", "EXECUTION_RECORDED"):
                err("ERR_SIGNATURE_ALREADY_FINAL", 409, "A signature packet is already final.")
        for p in db.packets.values():
            if p["negotiation_id"] == neg["id"] and p["status"] in ("ROUTING", "PARTIALLY_SIGNED"):
                p["status"] = "VOIDED"
                touch(p)
        neg["signature_status"] = "NOT_STARTED"
    else:
        # OPEN or REDLINING
        if neg["draft_status"] == "REDLINING":
            rnd = current_open_round(neg["id"])
            if rnd is not None:
                ts = now()
                rnd["status"] = "SUPERSEDED"
                rnd["closed_at"] = fmt(ts)
                rnd["round_duration_seconds"] = seconds_between(parse_iso(rnd["opened_at"]), ts)
        ts = now()
        for d in db.deviations.values():
            if d["negotiation_id"] == neg["id"] and d["status"] in ("OPEN", "IN_REVIEW", "ESCALATED"):
                d["status"] = "WITHDRAWN"
                d["resolved_at"] = fmt(ts)
                d["cycle_time_seconds"] = seconds_between(parse_iso(d["opened_at"]), ts)
                touch(d)
        recompute_deviation_counters(neg)
    neg["draft_status"] = "ABORTED"
    touch(neg)
    cp = db.counterparties.get(neg["counterparty_id"])
    if cp is not None:
        cp["active_negotiation_count"] -= 1
        touch(cp)
    pb = db.playbooks.get(neg["playbook_id"])
    if pb is not None:
        pb["active_negotiation_count"] -= 1
        touch(pb)
    return ok(pub(neg))


# --------------------------------------------------------------------------
# Deviations
# --------------------------------------------------------------------------


@bp.route("/negotiations/<negotiationId>/deviations", methods=["POST"])
def create_deviation(negotiationId):
    user, role = authenticate(["ContractAnalyst", "LegalCounsel"])
    neg = _get_neg(negotiationId)
    b = body()
    if "clause_template_id" in b and b["clause_template_id"] is not None \
            and b["clause_template_id"] not in db.clauses:
        err("ERR_FOREIGN_KEY_NOT_FOUND", 422, "clause_template_id does not resolve.")
    if not b.get("clause_template_id"):
        err("ERR_INVALID_REQUEST", 400, "clause_template_id is required.")
    if "proposed_text" not in b or not isinstance(b.get("proposed_text"), str):
        err("ERR_INVALID_REQUEST", 400, "proposed_text is required.")
    if "fallback_index" not in b or not isinstance(b.get("fallback_index"), int) \
            or isinstance(b.get("fallback_index"), bool):
        err("ERR_INVALID_REQUEST", 400, "fallback_index is required and must be an integer.")
    clause = db.clauses[b["clause_template_id"]]
    if neg["draft_status"] != "REDLINING":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Deviations may only be recorded while REDLINING.")
    rnd = current_open_round(neg["id"])
    if rnd is None:
        err("ERR_INVALID_STATE_TRANSITION", 409, "No round is currently OPEN.")
    # Duplicate-deviation guard
    prior = None
    for d in db.deviations.values():
        if d["negotiation_id"] == neg["id"] and d["clause_template_id"] == clause["id"]:
            if d["status"] == "ESCALATED":
                err("ERR_DEVIATION_ALREADY_OPEN", 409, "An ESCALATED deviation already exists for this clause.")
            if d["status"] in ("OPEN", "IN_REVIEW"):
                prior = d
    # Fallback-index range check
    fi = b["fallback_index"]
    positions = clause["fallback_positions"]
    if fi != -1 and (len(positions) == 0 or fi < 0 or fi >= len(positions)):
        err("ERR_FALLBACK_INDEX_OUT_OF_RANGE", 422, "fallback_index is out of range for this clause.")
    severity = "NON_STANDARD" if fi == -1 else "FALLBACK"
    # Supersede the prior live deviation, if any
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        prior["resolved_at"] = fmt(now())
        prior["cycle_time_seconds"] = seconds_between(parse_iso(prior["opened_at"]), now())
        touch(prior)
    ct = db.contract_types.get(neg["contract_type_id"])
    cp = db.counterparties.get(neg["counterparty_id"])
    tier = compute_value_tier(ct, neg["contract_value_cents"]) if ct else "LOW"
    cp_risk = cp["risk_tier"] if cp else "STANDARD"
    risk = compute_risk_score(
        severity, clause["category"], tier, cp_risk,
        neg["current_round_index"], clause["deviation_severity_cap"],
    )
    req_role, escalated = compute_required_role(
        clause, severity, neg["contract_value_cents"], ct,
    )
    ts = fmt(now())
    dev = {
        "id": new_id(),
        "negotiation_id": neg["id"],
        "round_id": rnd["id"],
        "clause_template_id": clause["id"],
        "proposed_text": b["proposed_text"],
        "fallback_index": fi,
        "severity": severity,
        "risk_score": risk,
        "required_approver_role": req_role,
        "escalated_to_chief_counsel": escalated,
        "assigned_approver_id": pick_approver(req_role),
        "status": "OPEN",
        "opened_at": ts,
        "resolved_at": None,
        "cycle_time_seconds": None,
    }
    stamp_new(dev)
    dev["opened_at"] = dev["created_at"]
    db.deviations[dev["id"]] = dev
    rnd["clause_change_count"] += 1
    # Auto-approval shortcut: value strictly below auto_approve_below_cents and FALLBACK
    if ct is not None and neg["contract_value_cents"] < ct["auto_approve_below_cents"] \
            and severity == "FALLBACK":
        dev["status"] = "APPROVED"
        dev["resolved_at"] = dev["opened_at"]
        dev["cycle_time_seconds"] = 0
        touch(dev)
    recompute_deviation_counters(neg)
    touch(neg)
    return ok(pub(dev), 201)


@bp.route("/negotiations/<negotiationId>/deviations", methods=["GET"])
def list_deviations(negotiationId):
    authenticate(ALL_ROLES)
    neg = _get_neg(negotiationId)
    items = [d for d in db.deviations.values() if d["negotiation_id"] == neg["id"]]
    items = apply_filters(
        items,
        [("status", "status"), ("severity", "severity"),
         ("clause_template_id", "clause_template_id"), ("round_id", "round_id"),
         ("assigned_approver_id", "assigned_approver_id")],
    )
    page, info = paginate(items)
    return ok(page, 200, info)


@bp.route("/negotiations/<negotiationId>/deviations/<deviationId>", methods=["GET"])
def get_deviation(negotiationId, deviationId):
    authenticate(ALL_ROLES)
    neg = _get_neg(negotiationId)
    return ok(pub(_get_dev(neg, deviationId)))


@bp.route("/negotiations/<negotiationId>/deviations/<deviationId>/begin-review", methods=["POST"])
def begin_review(negotiationId, deviationId):
    user, role = authenticate(REVIEW_ROLES)
    neg = _get_neg(negotiationId)
    dev = _get_dev(neg, deviationId)
    if dev["assigned_approver_id"] != user["id"] and user["primary_role"] != "CHIEF_COUNSEL":
        err("ERR_NOT_ASSIGNED_APPROVER", 403, "Actor is not the assigned approver on this deviation.")
    if dev["status"] != "OPEN":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Only an OPEN deviation can enter review.")
    if neg["draft_status"] != "REDLINING":
        err("ERR_INVALID_STATE_TRANSITION", 409, "Negotiation is not REDLINING.")
    dev["status"] = "IN_REVIEW"
    touch(dev)
    recompute_deviation_counters(neg)
    touch(neg)
    return ok(pub(dev))


@bp.route("/negotiations/<negotiationId>/deviations/<deviationId>/decide", methods=["POST"])
def decide_deviation(negotiationId, deviationId):
    user, role = authenticate(REVIEW_ROLES)
    neg = _get_neg(negotiationId)
    dev = _get_dev(neg, deviationId)
    b = body()
    decision = b.get("decision")
    # 1. state validity
    if dev["status"] == "IN_REVIEW":
        pass
    elif dev["status"] == "ESCALATED":
        if decision == "ESCALATE":
            err("ERR_INVALID_STATE_TRANSITION", 409, "An ESCALATED deviation cannot be escalated again.")
    else:
        err("ERR_INVALID_STATE_TRANSITION", 409, "Deviation is not in a decidable state.")
    # 2. version freshness
    expected = b.get("expected_negotiation_version")
    if expected is None:
        err("ERR_INVALID_REQUEST", 400, "expected_negotiation_version is required.")
    if expected != neg["version"]:
        err("ERR_STALE_VERSION", 412, "Negotiation version has advanced; re-read before deciding.")
    # 3. segregation of duties + assigned approver (combined per PRD 3.6)
    if user["id"] == neg["drafter_user_id"] or dev["assigned_approver_id"] != user["id"]:
        err("ERR_SEGREGATION_OF_DUTIES_VIOLATION", 403, "Approver must be the assigned approver and not the drafter.")
    # 4. approver-role sufficiency
    if LADDER.get(user["primary_role"], 0) < LADDER.get(dev["required_approver_role"], 99):
        err("ERR_INSUFFICIENT_APPROVER_ROLE", 403, "Approver role is below the required approver role.")
    clause = db.clauses.get(dev["clause_template_id"])
    # 5. escalation eligibility
    if decision == "ESCALATE" and clause is not None and clause["deviation_severity_cap"] == "LOW":
        err("ERR_SEVERITY_NOT_ESCATABLE", 409, "A LOW-severity-cap clause cannot be escalated.")
    # 6. body completeness
    if decision not in DECISIONS:
        err("ERR_INVALID_REQUEST", 400, "decision must be APPROVE | REJECT | ESCALATE | ABSTAIN.")
    rationale = b.get("decision_rationale")
    if decision in ("REJECT", "ESCALATE") and not rationale:
        err("ERR_INVALID_REQUEST", 400, "decision_rationale is required on REJECT and ESCALATE.")
    # Persist the audit row
    dec = {
        "id": new_id(),
        "deviation_id": dev["id"],
        "decided_by_user_id": user["id"],
        "decision": decision,
        "decision_rationale": rationale,
        "decided_at": fmt(now()),
        "snapshot_clause_version": clause["version"] if clause is not None else None,
    }
    stamp_audit(dec)
    db.decisions[dec["id"]] = dec
    ts = now()
    if decision == "ABSTAIN":
        return ok(pub(dev))
    if decision == "APPROVE":
        dev["status"] = "APPROVED"
        dev["resolved_at"] = fmt(ts)
        dev["cycle_time_seconds"] = seconds_between(parse_iso(dev["opened_at"]), ts)
    elif decision == "REJECT":
        dev["status"] = "REJECTED"
        dev["resolved_at"] = fmt(ts)
        dev["cycle_time_seconds"] = seconds_between(parse_iso(dev["opened_at"]), ts)
    elif decision == "ESCALATE":
        dev["status"] = "ESCALATED"
        dev["escalated_to_chief_counsel"] = True
        dev["required_approver_role"] = "CHIEF_COUNSEL"
        ct = db.contract_types.get(neg["contract_type_id"])
        cp = db.counterparties.get(neg["counterparty_id"])
        tier = compute_value_tier(ct, neg["contract_value_cents"]) if ct else "LOW"
        cp_risk = cp["risk_tier"] if cp else "STANDARD"
        if clause is not None:
            dev["risk_score"] = compute_risk_score(
                dev["severity"], clause["category"], tier, cp_risk,
                neg["current_round_index"], clause["deviation_severity_cap"],
            )
        dev["assigned_approver_id"] = pick_approver("CHIEF_COUNSEL")
    touch(dev)
    recompute_deviation_counters(neg)
    touch(neg)
    return ok(pub(dev))


@bp.route("/negotiations/<negotiationId>/deviations/<deviationId>/decisions", methods=["GET"])
def list_decisions_nested(negotiationId, deviationId):
    authenticate(ALL_ROLES)
    neg = _get_neg(negotiationId)
    dev = _get_dev(neg, deviationId)
    items = [d for d in db.decisions.values() if d["deviation_id"] == dev["id"]]
    items = apply_filters(items, [("decided_by_user_id", "decided_by_user_id")])
    page, info = paginate(items)
    return ok(page, 200, info)


@bp.route("/negotiations/<negotiationId>/deviations/<deviationId>/withdraw", methods=["POST"])
def withdraw_deviation(negotiationId, deviationId):
    user, role = authenticate(["ContractAnalyst"])
    neg = _get_neg(negotiationId)
    dev = _get_dev(neg, deviationId)
    if neg["draft_status"] not in ("OPEN", "REDLINING"):
        err("ERR_INVALID_STATE_TRANSITION", 409, "Negotiation is not in a state that permits withdrawal.")
    if user["id"] != neg["drafter_user_id"]:
        err("ERR_NOT_DRAFTER", 403, "Only the negotiation's drafter may withdraw its deviations.")
    if dev["status"] not in ("OPEN", "IN_REVIEW", "REJECTED"):
        err("ERR_INVALID_STATE_TRANSITION", 409, "Deviation is not in a withdrawable state.")
    ts = now()
    dev["status"] = "WITHDRAWN"
    dev["resolved_at"] = fmt(ts)
    dev["cycle_time_seconds"] = seconds_between(parse_iso(dev["opened_at"]), ts)
    touch(dev)
    recompute_deviation_counters(neg)
    touch(neg)
    return ok(pub(dev))
