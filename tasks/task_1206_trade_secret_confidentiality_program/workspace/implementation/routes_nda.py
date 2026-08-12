"""Counterparty, NdaAgreement, and NdaObligation routes (PRD §3.2)."""

from flask import Blueprint, request

from db import (
    add_days,
    add_months,
    all_rows,
    by_id,
    created_asc,
    db,
    fmt_ts,
    new_record,
    now,
    parse_dt,
    serialize,
    stamp,
    touch,
)
from errors import (
    err_counterparty_not_active,
    err_date_order,
    err_invalid_request,
    err_invalid_state,
    err_nda_window_overlap,
    err_not_found,
    err_ownership,
    err_stale_version,
    err_unauthorized_role,
)
from middleware import actor, body, require_enum, require_field, require_int, require_roles, require_str
from response import ok_list, ok_object, paginate
from services import (
    CLASS_ORDER,
    bar_counterparty_cascade,
    recompute_counterparty_exposure,
    recompute_nda_counts,
    terminate_nda,
)

bp = Blueprint("nda", __name__)

COUNTERPARTY_TYPES = ("VENDOR", "PARTNER", "CUSTOMER", "CONSULTANT")
COUNTERPARTY_STATUSES = ("ACTIVE", "SUSPENDED", "BARRED")
RISK_TIERS = ("LOW", "MEDIUM", "HIGH")
CLASSIFICATIONS = ("INTERNAL", "CONFIDENTIAL", "RESTRICTED", "CROWN_JEWEL")
NDA_STATUSES = (
    "DRAFT",
    "SENT",
    "EXECUTED",
    "ACTIVE",
    "BREACH_ALLEGED",
    "SUPERSEDED",
    "TERMINATED",
    "EXPIRED",
)
NDA_NON_TERMINAL = ("DRAFT", "SENT", "EXECUTED", "ACTIVE", "BREACH_ALLEGED")
OBLIGATION_TYPES = (
    "NON_DISCLOSURE",
    "NON_USE",
    "RETURN_OR_DESTROY",
    "NO_REVERSE_ENGINEERING",
    "AUDIT_RIGHT",
)
OBLIGATION_STATUSES = ("PENDING", "FULFILLED", "WAIVED", "OVERDUE", "ESCALATED")


def _paginate_list(store_name, filters):
    rows = []
    for r in created_asc(all_rows(store_name)):
        if all(r.get(k) == v for k, v in filters):
            rows.append(serialize(r))
    page, limit, offset, total = paginate(rows, request.args)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Counterparty
# ---------------------------------------------------------------------------
@bp.post("/api/counterparties")
def create_counterparty():
    _uid, role = actor()
    require_roles(role, "IPCounsel")
    data = body()
    rec = new_record(
        "counterparties",
        {
            "legal_name": require_str(data, "legal_name"),
            "counterparty_type": require_enum(data, "counterparty_type", COUNTERPARTY_TYPES),
            "status": "ACTIVE",
            "exposure_index_trailing": 0,
            "exposure_index_lifetime": 0,
            "risk_tier": "LOW",
        },
    )
    return ok_object(serialize(rec), code=201)


@bp.get("/api/counterparties")
def list_counterparties():
    _uid, role = actor()
    require_roles(role, "IPCounsel", "SeniorCounsel", "SecurityOfficer")
    filters = [(f, request.args[f]) for f in ("status", "risk_tier") if f in request.args]
    return _paginate_list("counterparties", filters)


@bp.get("/api/counterparties/<rid>")
def get_counterparty(rid):
    _uid, role = actor()
    require_roles(role, "IPCounsel", "SeniorCounsel", "SecurityOfficer")
    cp = by_id("counterparties", rid)
    if cp is None:
        raise err_not_found("counterparty not found")
    recompute_counterparty_exposure(cp)
    return ok_object(serialize(cp))


@bp.post("/api/counterparties/<rid>/state")
def counterparty_state(rid):
    _uid, role = actor()
    require_roles(role, "IPCounsel")
    cp = by_id("counterparties", rid)
    if cp is None:
        raise err_not_found("counterparty not found")
    data = body()
    to_status = require_str(data, "to_status")
    if to_status not in COUNTERPARTY_STATUSES:
        raise err_invalid_request(f"to_status must be one of {list(COUNTERPARTY_STATUSES)}")
    cur = cp["status"]
    if to_status == "SUSPENDED":
        if cur != "ACTIVE":
            raise err_invalid_state(f"Cannot move counterparty from {cur} to SUSPENDED")
        cp["status"] = "SUSPENDED"
        touch(cp)
    elif to_status == "ACTIVE":
        if cur != "SUSPENDED":
            raise err_invalid_state(f"Cannot move counterparty from {cur} to ACTIVE")
        cp["status"] = "ACTIVE"
        touch(cp)
    elif to_status == "BARRED":
        if cur not in ("ACTIVE", "SUSPENDED"):
            raise err_invalid_state(f"Cannot move counterparty from {cur} to BARRED")
        cp["status"] = "BARRED"
        touch(cp)
        bar_counterparty_cascade(cp)
    return ok_object(serialize(cp))


# ---------------------------------------------------------------------------
# NdaAgreement
# ---------------------------------------------------------------------------
def _check_window_overlap(counterparty_id, eff, exp, exclude_id=None):
    """Closed-interval overlap against every other non-terminal NDA of the same
    counterparty; touching boundary dates count as overlap (PRD §3.2)."""
    for other in all_rows("ndas"):
        if other["counterparty_id"] != counterparty_id:
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other["status"] not in NDA_NON_TERMINAL:
            continue
        if eff <= other["_expiry_dt"] and other["_effective_dt"] <= exp:
            raise err_nda_window_overlap()


def _validate_nda_payload(data):
    template_version = require_str(data, "template_version")
    governing_law = require_str(data, "governing_law")
    eff_raw = require_field(data, "effective_date")
    exp_raw = require_field(data, "expiry_date")
    eff = parse_dt(eff_raw)
    exp = parse_dt(exp_raw)
    if eff is None or exp is None:
        raise err_invalid_request("effective_date / expiry_date must be ISO 8601 timestamps")
    survival = require_int(data, "survival_months")
    ceiling = require_enum(data, "classification_ceiling", CLASSIFICATIONS)
    return template_version, governing_law, eff_raw, eff, exp_raw, exp, survival, ceiling


@bp.post("/api/ndas")
def create_nda():
    _uid, role = actor()
    require_roles(role, "IPCounsel")
    data = body()
    counterparty_id = require_str(data, "counterparty_id")
    cp = by_id("counterparties", counterparty_id)
    if cp is None:
        raise err_not_found("counterparty not found")
    template_version, governing_law, eff_raw, eff, exp_raw, exp, survival, ceiling = _validate_nda_payload(data)
    # Temporal rules (priority 8) before referenced-state gates (priority 9).
    if exp <= eff:
        raise err_date_order("expiry_date must be strictly after effective_date")
    _check_window_overlap(counterparty_id, eff, exp)
    if cp["status"] != "ACTIVE":
        raise err_counterparty_not_active("Counterparty is not ACTIVE")
    if survival < 0:
        raise err_invalid_request("survival_months must be >= 0")
    conf_end = add_months(exp, survival)
    rec = new_record(
        "ndas",
        {
            "counterparty_id": counterparty_id,
            "supersedes_id": None,
            "template_version": template_version,
            "governing_law": governing_law,
            "effective_date": eff_raw if isinstance(eff_raw, str) else fmt_ts(eff),
            "expiry_date": exp_raw if isinstance(exp_raw, str) else fmt_ts(exp),
            "_effective_dt": eff,
            "_expiry_dt": exp,
            "survival_months": survival,
            "classification_ceiling": ceiling,
            "status": "DRAFT",
            "terminated_at": None,
            "confidentiality_end": fmt_ts(conf_end),
            "obligations_total_count": 0,
            "obligations_open_count": 0,
            "obligations_fulfilled_count": 0,
            "obligations_waived_count": 0,
        },
    )
    return ok_object(serialize(rec), code=201)


@bp.post("/api/ndas/<rid>/amendments")
def create_amendment(rid):
    """OCC-guarded amendment (PRD §2.6): expected_superseded_nda_version is
    non-optional; amendment linkage mutates the superseded NDA (version +1)."""
    _uid, role = actor()
    require_roles(role, "IPCounsel")
    target = by_id("ndas", rid)
    if target is None:
        raise err_not_found("NDA not found")
    data = body()
    expected = require_field(data, "expected_superseded_nda_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err_invalid_request("expected_superseded_nda_version must be an integer")
    if expected != target["version"]:
        raise err_stale_version()
    if target["status"] not in ("ACTIVE", "BREACH_ALLEGED"):
        raise err_invalid_state("Amendment target NDA must be ACTIVE or BREACH_ALLEGED")
    template_version, governing_law, eff_raw, eff, exp_raw, exp, survival, ceiling = _validate_nda_payload(data)
    if exp <= eff:
        raise err_date_order("expiry_date must be strictly after effective_date")
    # The amendment may overlap the NDA it supersedes, but no other
    # non-terminal NDA of the same counterparty.
    _check_window_overlap(target["counterparty_id"], eff, exp, exclude_id=target["id"])
    if survival < 0:
        raise err_invalid_request("survival_months must be >= 0")
    conf_end = add_months(exp, survival)
    rec = new_record(
        "ndas",
        {
            "counterparty_id": target["counterparty_id"],
            "supersedes_id": target["id"],
            "template_version": template_version,
            "governing_law": governing_law,
            "effective_date": eff_raw if isinstance(eff_raw, str) else fmt_ts(eff),
            "expiry_date": exp_raw if isinstance(exp_raw, str) else fmt_ts(exp),
            "_effective_dt": eff,
            "_expiry_dt": exp,
            "survival_months": survival,
            "classification_ceiling": ceiling,
            "status": "DRAFT",
            "terminated_at": None,
            "confidentiality_end": fmt_ts(conf_end),
            "obligations_total_count": 0,
            "obligations_open_count": 0,
            "obligations_fulfilled_count": 0,
            "obligations_waived_count": 0,
        },
    )
    touch(target)  # amendment linkage is a mutation of the superseded NDA
    return ok_object(serialize(rec), code=201)


@bp.get("/api/ndas")
def list_ndas():
    _uid, role = actor()
    require_roles(role, "IPCounsel", "SeniorCounsel")
    filters = [(f, request.args[f]) for f in ("counterparty_id", "supersedes_id", "status") if f in request.args]
    return _paginate_list("ndas", filters)


@bp.get("/api/ndas/<rid>")
def get_nda(rid):
    _uid, role = actor()
    require_roles(role, "IPCounsel", "SeniorCounsel")
    nda = by_id("ndas", rid)
    if nda is None:
        raise err_not_found("NDA not found")
    recompute_nda_counts(nda)
    return ok_object(serialize(nda))


@bp.post("/api/ndas/<rid>/state")
def nda_state(rid):
    user_id, role = actor()
    require_roles(role, "IPCounsel", "CounterpartyRep")
    nda = by_id("ndas", rid)
    if nda is None:
        raise err_not_found("NDA not found")
    data = body()
    to_status = require_str(data, "to_status")
    if to_status not in NDA_STATUSES:
        raise err_invalid_request(f"to_status must be one of {list(NDA_STATUSES)}")
    cur = nda["status"]

    if to_status == "SENT":
        if role != "IPCounsel":
            raise err_unauthorized_role("SENT requires IPCounsel")
        if cur != "DRAFT":
            raise err_invalid_state(f"Cannot move NDA from {cur} to SENT")
        nda["status"] = "SENT"
        touch(nda)
    elif to_status == "EXECUTED":
        if role != "CounterpartyRep":
            raise err_unauthorized_role("EXECUTED requires CounterpartyRep")
        # Ownership (priority 3): the representative acts for their own NDA.
        if user_id != nda["counterparty_id"]:
            raise err_ownership("CounterpartyRep may execute only their own NDAs")
        if cur != "SENT":
            raise err_invalid_state(f"Cannot move NDA from {cur} to EXECUTED")
        nda["status"] = "EXECUTED"
        touch(nda)
    elif to_status == "ACTIVE":
        if role != "IPCounsel":
            raise err_unauthorized_role("ACTIVE requires IPCounsel")
        if cur not in ("EXECUTED", "BREACH_ALLEGED"):
            raise err_invalid_state(f"Cannot move NDA from {cur} to ACTIVE")
        nda["status"] = "ACTIVE"
        touch(nda)
        if nda["supersedes_id"]:
            prior = by_id("ndas", nda["supersedes_id"])
            if prior is not None and prior["status"] != "SUPERSEDED":
                prior["status"] = "SUPERSEDED"
                touch(prior)
    elif to_status == "BREACH_ALLEGED":
        if role != "IPCounsel":
            raise err_unauthorized_role("BREACH_ALLEGED requires IPCounsel")
        if cur != "ACTIVE":
            raise err_invalid_state(f"Cannot move NDA from {cur} to BREACH_ALLEGED")
        nda["status"] = "BREACH_ALLEGED"
        touch(nda)
    elif to_status == "TERMINATED":
        if role != "IPCounsel":
            raise err_unauthorized_role("TERMINATED requires IPCounsel")
        if cur not in ("ACTIVE", "BREACH_ALLEGED"):
            raise err_invalid_state(f"Cannot move NDA from {cur} to TERMINATED")
        terminate_nda(nda, now())
    else:  # SUPERSEDED / EXPIRED are cascade/sweep-only
        raise err_invalid_state(f"Cannot move NDA from {cur} to {to_status}")
    return ok_object(serialize(nda))


# ---------------------------------------------------------------------------
# NdaObligation
# ---------------------------------------------------------------------------
@bp.post("/api/obligations")
def create_obligation():
    _uid, role = actor()
    require_roles(role, "IPCounsel")
    data = body()
    nda_id = require_str(data, "nda_id")
    nda = by_id("ndas", nda_id)
    if nda is None:
        raise err_not_found("NDA not found")
    obligation_type = require_enum(data, "obligation_type", OBLIGATION_TYPES)
    due_raw = data.get("due_at")
    due_dt = None
    if due_raw is not None:
        due_dt = parse_dt(due_raw)
        if due_dt is None:
            raise err_invalid_request("due_at must be an ISO 8601 timestamp")
    if obligation_type == "RETURN_OR_DESTROY" and due_raw is not None:
        # Return-or-destroy rows are created with due_at empty and anchored at
        # NDA termination/expiry (PRD §3.2).
        raise err_invalid_request("RETURN_OR_DESTROY obligations take due_at=null")
    rec = new_record(
        "obligations",
        {
            "nda_id": nda_id,
            "obligation_type": obligation_type,
            "due_at": due_raw if isinstance(due_raw, str) else (fmt_ts(due_dt) if due_dt else None),
            "_due_at_dt": due_dt,
            "status": "PENDING",
            "fulfilled_at": None,
            "escalated_at": None,
        },
    )
    recompute_nda_counts(nda)
    return ok_object(serialize(rec), code=201)


@bp.get("/api/obligations")
def list_obligations():
    _uid, role = actor()
    require_roles(role, "IPCounsel", "SeniorCounsel", "CounterpartyRep")
    filters = [(f, request.args[f]) for f in ("nda_id", "status", "obligation_type") if f in request.args]
    rows = []
    cp_filter = request.args.get("counterparty_id")
    for r in created_asc(all_rows("obligations")):
        if not all(r.get(k) == v for k, v in filters):
            continue
        if cp_filter is not None:
            nda = by_id("ndas", r["nda_id"])
            if nda is None or nda["counterparty_id"] != cp_filter:
                continue
        rows.append(serialize(r))
    page, limit, offset, total = paginate(rows, request.args)
    return ok_list(page, limit, offset, total)


@bp.get("/api/obligations/<rid>")
def get_obligation(rid):
    _uid, role = actor()
    require_roles(role, "IPCounsel", "SeniorCounsel", "CounterpartyRep")
    ob = by_id("obligations", rid)
    if ob is None:
        raise err_not_found("obligation not found")
    return ok_object(serialize(ob))


@bp.post("/api/obligations/<rid>/state")
def obligation_state(rid):
    user_id, role = actor()
    require_roles(role, "IPCounsel", "CounterpartyRep")
    ob = by_id("obligations", rid)
    if ob is None:
        raise err_not_found("obligation not found")
    data = body()
    to_status = require_str(data, "to_status")
    if to_status not in OBLIGATION_STATUSES:
        raise err_invalid_request(f"to_status must be one of {list(OBLIGATION_STATUSES)}")
    cur = ob["status"]
    nda = by_id("ndas", ob["nda_id"])

    if to_status == "FULFILLED":
        if role != "CounterpartyRep":
            raise err_unauthorized_role("FULFILLED requires CounterpartyRep")
        if nda is None or user_id != nda["counterparty_id"]:
            raise err_ownership("CounterpartyRep may fulfill only their own obligations")
        if cur not in ("PENDING", "OVERDUE", "ESCALATED"):
            raise err_invalid_state(f"Cannot move obligation from {cur} to FULFILLED")
        ob["status"] = "FULFILLED"
        stamp(ob, "fulfilled_at")
        touch(ob)
        if nda is not None:
            recompute_nda_counts(nda)
            cp = by_id("counterparties", nda["counterparty_id"])
            if cp is not None:
                recompute_counterparty_exposure(cp)
    elif to_status == "WAIVED":
        if role != "IPCounsel":
            raise err_unauthorized_role("WAIVED requires IPCounsel")
        if cur not in ("PENDING", "OVERDUE"):
            raise err_invalid_state(f"Cannot move obligation from {cur} to WAIVED")
        ob["status"] = "WAIVED"
        touch(ob)
        if nda is not None:
            recompute_nda_counts(nda)
    elif to_status == "ESCALATED":
        if role != "IPCounsel":
            raise err_unauthorized_role("ESCALATED requires IPCounsel")
        if cur != "OVERDUE":
            raise err_invalid_state(f"Cannot move obligation from {cur} to ESCALATED")
        ob["status"] = "ESCALATED"
        stamp(ob, "escalated_at")
        touch(ob)
        if nda is not None:
            recompute_nda_counts(nda)
            cp = by_id("counterparties", nda["counterparty_id"])
            if cp is not None:
                recompute_counterparty_exposure(cp)
    else:  # PENDING / OVERDUE are not manual targets
        raise err_invalid_state(f"Cannot move obligation from {cur} to {to_status}")
    return ok_object(serialize(ob))
