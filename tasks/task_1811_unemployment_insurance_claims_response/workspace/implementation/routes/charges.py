"""ChargeStatement, ChargeLineItem, and ChargeProtest endpoints (§3.6):
quarterly statements, charge posting with the three-ledger move, audit,
protest adjudication, waiver, and reconciliation."""
import re

from flask import Blueprint

from db import STORE
from errors import (
    err,
    ERR_CROSS_PARENT_REFERENCE,
    ERR_DUPLICATE_ACTIVE_RECORD,
    ERR_FISCAL_CAP_EXCEEDED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LINE_ALREADY_PROTESTED,
    ERR_LINE_NOT_PROTESTABLE,
    ERR_LINE_NOT_WAIVABLE,
    ERR_MAX_BENEFIT_EXCEEDED,
    ERR_PROTEST_EVIDENCE_WEAK,
    ERR_PROTEST_NOT_REVIEWABLE,
    ERR_PROTESTS_IN_FLIGHT,
    ERR_STALE_VERSION,
    ERR_STATEMENT_NOT_AUDITABLE,
    ERR_STATEMENT_NOT_RECONCILABLE,
    not_found,
)
from middleware import require_roles
from response import paginate, success
from routes.state_rules import find_rule_by_code
from services.core import find_or_404, new_record, now, serialize, sorted_created, touch
from services.deadlines import calendar_window_due, timeliness as compute_timeliness
from services.rating import refresh_current_rate, supersede_models
from services.scoring import protest_evidence_score, recompute_posture, SUSTAIN_THRESHOLD
from util import as_dt, as_int, as_str, body_json, check_enum, opt, req

bp = Blueprint("charges", __name__)

ERRONEOUS_REASONS = (
    "NONE",
    "CLAIMANT_NOT_SEPARATED",
    "WRONG_EMPLOYER",
    "ALREADY_PROTESTED",
    "EXCEEDS_MAX_BENEFIT",
    "DUPLICATE_LINE",
)
PROTEST_BASES = ERRONEOUS_REASONS[1:]  # NONE excluded
OPEN_PROTEST_STATUSES = ("FILED", "UNDER_REVIEW")


def _recompute_variance(stmt):
    """charge_audit_variance (§1.3): five aggregates over the statement's
    lines; total_charged_cents stays in ledger sync (REVERSED/WAIVED lines
    never linger)."""
    lines = [l for l in STORE.charge_lines.values() if l["statement_id"] == stmt["id"]]
    audited = sum(l["amount_cents"] for l in lines if l["status"] in ("PENDING", "SUSTAINED"))
    erroneous = sum(l["amount_cents"] for l in lines if l["erroneous_reason"] != "NONE")
    protested = sum(l["amount_cents"] for l in lines if l["status"] == "PROTESTED")
    reversed_total = sum(l["amount_cents"] for l in lines if l["status"] == "REVERSED")
    stmt["audited_total_cents"] = audited
    stmt["erroneous_total_cents"] = erroneous
    stmt["protested_total_cents"] = protested
    stmt["reversed_total_cents"] = reversed_total
    stmt["variance_cents"] = erroneous - reversed_total
    # ledger sync: everything not REVERSED/WAIVED still stands charged
    stmt["total_charged_cents"] = sum(
        l["amount_cents"] for l in lines if l["status"] not in ("REVERSED", "WAIVED")
    )


def _reverse_adjust(stmt, claim, line):
    """Shared ledger adjustment for REVERSED/WAIVED transitions: statement
    total and claim charged amount each decremented by the line amount."""
    stmt["total_charged_cents"] -= line["amount_cents"]
    _recompute_variance(stmt)
    touch(stmt)
    if claim is not None:
        claim["charged_amount_cents"] -= line["amount_cents"]
        touch(claim)


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------

@bp.post("/ui/charge-statements")
def create_statement():
    require_roles("AgencyLiaison")
    body = body_json()
    employer_id = as_str(req(body, "employer_id"), "employer_id")
    state_code = as_str(req(body, "state_code"), "state_code")
    quarter = as_str(req(body, "quarter"), "quarter")
    if not re.fullmatch(r"\d{4}Q[1-4]", quarter):
        raise err(ERR_INVALID_REQUEST, 400, "quarter must match YYYYQ[1-4]")
    issued_at = as_dt(req(body, "issued_at"), "issued_at")

    find_or_404(STORE.employers, employer_id, "employer")
    rule = find_rule_by_code(state_code)
    if rule is None:
        raise not_found("state rule")

    rec = new_record({
        "employer_id": employer_id,
        "state_code": state_code,
        "quarter": quarter,
        "issued_at": issued_at,
        "protest_due_at": calendar_window_due(issued_at, rule["protest_window_days"], rule),
        "total_charged_cents": 0,
        "status": "ISSUED",
        "audited_total_cents": 0,
        "erroneous_total_cents": 0,
        "protested_total_cents": 0,
        "reversed_total_cents": 0,
        "variance_cents": 0,
    })
    STORE.charge_statements[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/ui/charge-statements/<rid>")
def get_statement(rid):
    require_roles("PlatformAdmin", "ChargeAuditor", "AgencyLiaison")
    rec = find_or_404(STORE.charge_statements, rid, "charge statement")
    return success(serialize(rec))


@bp.get("/ui/charge-statements/<rid>/line-items")
def statement_lines(rid):
    require_roles("PlatformAdmin", "ChargeAuditor", "AgencyLiaison")
    find_or_404(STORE.charge_statements, rid, "charge statement")
    items = [serialize(l) for l in sorted_created(STORE.charge_lines.values()) if l["statement_id"] == rid]
    return paginate(items)


@bp.get("/ui/charge-statements/<rid>/protests")
def statement_protests(rid):
    require_roles("PlatformAdmin", "ChargeAuditor", "AgencyLiaison")
    find_or_404(STORE.charge_statements, rid, "charge statement")
    items = [serialize(p) for p in sorted_created(STORE.charge_protests.values()) if p["statement_id"] == rid]
    return paginate(items)


@bp.post("/ui/charge-statements/<sid>/line-items")
def post_line_item(sid):
    require_roles("AgencyLiaison")
    body = body_json()
    claim_id = as_str(req(body, "claim_id"), "claim_id")
    amount_cents = as_int(req(body, "amount_cents"), "amount_cents")
    benefit_weeks = as_int(req(body, "benefit_weeks"), "benefit_weeks")
    erroneous_reason = check_enum(
        as_str(opt(body, "erroneous_reason", "NONE"), "erroneous_reason"),
        ERRONEOUS_REASONS, "erroneous_reason",
    )

    stmt = find_or_404(STORE.charge_statements, sid, "charge statement")
    claim = find_or_404(STORE.claims, claim_id, "claim")
    if claim["employer_id"] != stmt["employer_id"]:
        raise err(
            ERR_CROSS_PARENT_REFERENCE,
            422,
            "claim belongs to a different employer than the statement",
        )
    # fiscal domain: amounts are non-negative
    if amount_cents < 0:
        raise err(ERR_FISCAL_CAP_EXCEEDED, 422, "amount_cents must be non-negative")
    # aggregate cap: the claim's charged amount may not exceed its max benefit
    if claim["charged_amount_cents"] + amount_cents > claim["max_benefit_cents"]:
        raise err(ERR_MAX_BENEFIT_EXCEEDED, 422, "posting would exceed the claim's max benefit")

    rec = new_record({
        "statement_id": sid,
        "claim_id": claim_id,
        "amount_cents": amount_cents,
        "benefit_weeks": benefit_weeks,
        "erroneous_reason": erroneous_reason,
        "status": "PENDING",
    })
    STORE.charge_lines[rec["id"]] = rec

    # three-ledger move: statement total up, claim charged up, reserve debited
    stmt["total_charged_cents"] += amount_cents
    touch(stmt)
    _recompute_variance(stmt)
    claim["charged_amount_cents"] += amount_cents
    touch(claim)
    emp = STORE.employers.get(stmt["employer_id"])
    if emp is not None:
        emp["reserve_balance_cents"] -= amount_cents
        touch(emp)
        # a source charge input changed — DRAFT rating models are invalidated
        supersede_models(emp["id"], include_finalized=False)
    return success(serialize(rec), 201)


@bp.post("/ui/charge-statements/<rid>/audit")
def open_audit(rid):
    require_roles("ChargeAuditor")
    stmt = find_or_404(STORE.charge_statements, rid, "charge statement")
    if stmt["status"] != "ISSUED":
        raise err(ERR_STATEMENT_NOT_AUDITABLE, 409, "only an ISSUED statement can enter audit")
    stmt["status"] = "UNDER_AUDIT"
    _recompute_variance(stmt)
    touch(stmt)
    return success(serialize(stmt))


@bp.post("/ui/charge-statements/<rid>/audit/complete")
def complete_audit(rid):
    require_roles("ChargeAuditor")
    stmt = find_or_404(STORE.charge_statements, rid, "charge statement")
    if stmt["status"] != "UNDER_AUDIT":
        raise err(ERR_INVALID_STATE, 409, "audit completion requires UNDER_AUDIT")
    for line in STORE.charge_lines.values():
        if line["statement_id"] == rid and line["status"] == "PROTESTED":
            raise err(ERR_PROTESTS_IN_FLIGHT, 409, "a line is still PROTESTED")
    stmt["status"] = "AUDIT_COMPLETE"
    _recompute_variance(stmt)  # audit findings snapshot; erroneous totals aggregated
    touch(stmt)
    return success(serialize(stmt))


@bp.post("/ui/charge-statements/<rid>/reconcile")
def reconcile_statement(rid):
    require_roles("ChargeAuditor")
    stmt = find_or_404(STORE.charge_statements, rid, "charge statement")
    if stmt["status"] != "AUDIT_COMPLETE":
        raise err(ERR_STATEMENT_NOT_RECONCILABLE, 409, "reconcile requires AUDIT_COMPLETE")
    for p in STORE.charge_protests.values():
        if p["statement_id"] == rid and p["status"] in OPEN_PROTEST_STATUSES:
            raise err(ERR_PROTESTS_IN_FLIGHT, 409, "a protest is still open on this statement")
    stmt["status"] = "RECONCILED"
    touch(stmt)
    emp = STORE.employers.get(stmt["employer_id"])
    if emp is not None:
        # audit-trail credit counter only — the reserve was already credited
        # at each line's REVERSED transition; a second credit is forbidden
        reversed_sum = sum(
            l["amount_cents"] for l in STORE.charge_lines.values()
            if l["statement_id"] == rid and l["status"] == "REVERSED"
        )
        if reversed_sum:
            emp["protest_credits_cents"] += reversed_sum
        # derived inputs now stale: models supersede and the rate re-evaluates
        supersede_models(emp["id"], include_finalized=True)
        refresh_current_rate(emp)
    return success(serialize(stmt))


# ---------------------------------------------------------------------------
# Line items
# ---------------------------------------------------------------------------

@bp.get("/ui/charge-line-items/<rid>")
def get_line_item(rid):
    require_roles("PlatformAdmin", "ChargeAuditor", "AgencyLiaison")
    rec = find_or_404(STORE.charge_lines, rid, "charge line item")
    return success(serialize(rec))


@bp.get("/ui/charge-line-items/<rid>/protests")
def line_protests(rid):
    require_roles("PlatformAdmin", "ChargeAuditor", "AgencyLiaison")
    find_or_404(STORE.charge_lines, rid, "charge line item")
    items = [serialize(p) for p in sorted_created(STORE.charge_protests.values()) if p["line_item_id"] == rid]
    return paginate(items)


@bp.post("/ui/charge-line-items/<rid>/protests")
def file_protest(rid):
    require_roles("ChargeAuditor")
    body = body_json()
    protest_basis = check_enum(
        as_str(req(body, "protest_basis"), "protest_basis"), PROTEST_BASES, "protest_basis"
    )
    expected_statement_version = as_int(
        req(body, "expected_statement_version"), "expected_statement_version"
    )

    line = find_or_404(STORE.charge_lines, rid, "charge line item")
    stmt = STORE.charge_statements.get(line["statement_id"])
    if stmt is None:
        raise not_found("charge statement")
    if line["status"] != "PENDING":
        raise err(ERR_LINE_NOT_PROTESTABLE, 409, "only a PENDING line can be protested")
    prior = [p for p in STORE.charge_protests.values() if p["line_item_id"] == rid]
    if protest_basis == "ALREADY_PROTESTED" and not any(p["status"] == "DENIED" for p in prior):
        raise err(ERR_LINE_ALREADY_PROTESTED, 409, "ALREADY_PROTESTED requires a prior DENIED protest")
    if any(p["status"] in OPEN_PROTEST_STATUSES for p in prior):
        raise err(ERR_DUPLICATE_ACTIVE_RECORD, 409, "an open protest already exists on this line")
    # OCC runs last so business errors surface first
    if expected_statement_version != stmt["version"]:
        raise err(ERR_STALE_VERSION, 412, "expected_statement_version does not match the statement's current version")

    filed_at = now()
    tl = compute_timeliness(filed_at, stmt["protest_due_at"])
    claim = STORE.claims.get(line["claim_id"])
    rec = new_record({
        "line_item_id": rid,
        "statement_id": stmt["id"],
        "filed_at": filed_at,
        "timeliness": tl,
        "protest_basis": protest_basis,
        "evidence_strength": 0,
        "status": "FILED",
    })

    if tl == "LATE":
        # a late filing is stamped and dismissed outright; the line is untouched
        rec["status"] = "DISMISSED_UNTIMELY"
        STORE.charge_protests[rec["id"]] = rec
        return success(serialize(rec), 201)

    rec["evidence_strength"] = protest_evidence_score(claim, protest_basis) if claim else 0
    STORE.charge_protests[rec["id"]] = rec
    line["status"] = "PROTESTED"
    touch(line)
    # bubble-up: an ISSUED statement enters audit automatically
    if stmt["status"] == "ISSUED":
        stmt["status"] = "UNDER_AUDIT"
    _recompute_variance(stmt)
    touch(stmt)
    emp = STORE.employers.get(stmt["employer_id"])
    if emp is not None:
        supersede_models(emp["id"], include_finalized=False)
    return success(serialize(rec), 201)


@bp.post("/ui/charge-line-items/<rid>/waive")
def waive_line(rid):
    require_roles("AgencyLiaison")
    line = find_or_404(STORE.charge_lines, rid, "charge line item")
    if line["status"] != "PENDING":
        raise err(ERR_LINE_NOT_WAIVABLE, 409, "only a PENDING line can be waived")
    stmt = STORE.charge_statements.get(line["statement_id"])
    claim = STORE.claims.get(line["claim_id"])
    line["status"] = "WAIVED"
    touch(line)
    # same three-ledger adjustment as a reversal — but no protest credits
    if stmt is not None:
        _reverse_adjust(stmt, claim, line)
    emp = STORE.employers.get(stmt["employer_id"]) if stmt is not None else None
    if emp is not None:
        emp["reserve_balance_cents"] += line["amount_cents"]
        touch(emp)
        supersede_models(emp["id"], include_finalized=False)
    return success(serialize(line))


# ---------------------------------------------------------------------------
# Protests
# ---------------------------------------------------------------------------

@bp.get("/ui/charge-protests/<rid>")
def get_protest(rid):
    require_roles("PlatformAdmin", "ChargeAuditor", "AgencyLiaison")
    rec = find_or_404(STORE.charge_protests, rid, "charge protest")
    return success(serialize(rec))


@bp.post("/ui/charge-protests/<rid>/review")
def review_protest(rid):
    require_roles("AgencyLiaison")
    p = find_or_404(STORE.charge_protests, rid, "charge protest")
    if p["status"] != "FILED":
        raise err(ERR_PROTEST_NOT_REVIEWABLE, 409, "only a FILED protest can enter review")
    p["status"] = "UNDER_REVIEW"
    touch(p)
    return success(serialize(p))


@bp.post("/ui/charge-protests/<rid>/sustain")
def sustain_protest(rid):
    require_roles("AgencyLiaison")
    p = find_or_404(STORE.charge_protests, rid, "charge protest")
    if p["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, 409, "sustain requires UNDER_REVIEW")
    if p["evidence_strength"] < SUSTAIN_THRESHOLD:
        raise err(ERR_PROTEST_EVIDENCE_WEAK, 422, "evidence_strength below 60")
    p["status"] = "SUSTAINED"
    touch(p)
    line = STORE.charge_lines.get(p["line_item_id"])
    stmt = STORE.charge_statements.get(p["statement_id"])
    claim = STORE.claims.get(line["claim_id"]) if line is not None else None
    emp = STORE.employers.get(stmt["employer_id"]) if stmt is not None else None
    if line is not None and line["status"] == "PROTESTED":
        line["status"] = "REVERSED"
        touch(line)
        if stmt is not None:
            _reverse_adjust(stmt, claim, line)
        if emp is not None:
            emp["reserve_balance_cents"] += line["amount_cents"]
            touch(emp)
            supersede_models(emp["id"], include_finalized=False)
    return success(serialize(p))


@bp.post("/ui/charge-protests/<rid>/deny")
def deny_protest(rid):
    require_roles("AgencyLiaison")
    p = find_or_404(STORE.charge_protests, rid, "charge protest")
    if p["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, 409, "deny requires UNDER_REVIEW")
    p["status"] = "DENIED"
    touch(p)
    line = STORE.charge_lines.get(p["line_item_id"])
    if line is not None and line["status"] == "PROTESTED":
        line["status"] = "SUSTAINED"
        touch(line)
        stmt = STORE.charge_statements.get(p["statement_id"])
        if stmt is not None:
            _recompute_variance(stmt)
            touch(stmt)
        # a denied protest counts half a strike toward SANCTIONED
        emp = STORE.employers.get(stmt["employer_id"]) if stmt is not None else None
        if emp is not None:
            recompute_posture(emp)
            touch(emp)
            supersede_models(emp["id"], include_finalized=False)
    return success(serialize(p))


@bp.post("/ui/charge-protests/<rid>/withdraw")
def withdraw_protest(rid):
    require_roles("ChargeAuditor")
    p = find_or_404(STORE.charge_protests, rid, "charge protest")
    if p["status"] not in OPEN_PROTEST_STATUSES:
        raise err(ERR_INVALID_STATE, 409, "only a FILED or UNDER_REVIEW protest can be withdrawn")
    p["status"] = "WITHDRAWN"
    touch(p)
    line = STORE.charge_lines.get(p["line_item_id"])
    if line is not None and line["status"] == "PROTESTED":
        # compensating action restores the pre-protest ledger posture
        line["status"] = "PENDING"
        touch(line)
        stmt = STORE.charge_statements.get(p["statement_id"])
        if stmt is not None:
            _recompute_variance(stmt)
            touch(stmt)
    return success(serialize(p))
