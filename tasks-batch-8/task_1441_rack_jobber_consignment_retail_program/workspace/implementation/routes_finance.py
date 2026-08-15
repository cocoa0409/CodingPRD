"""AuditCount, MarkdownAuthorization, SettlementStatement, SeasonalSet endpoints."""
from flask import Blueprint, request

import response
from db import store, fmt_dt
from errors import err
from middleware import extract_identity, require_role, ALL_ROLES
from common import (
    new_entity, touch, public, get_json, get_or_404, fk_exists,
    require_str, optional_str, require_enum, require_int, require_num,
    rhu, dec, parse_date, require_from_state, require_store_manager,
    parse_pagination, list_page,
)
from services import (
    CATEGORIES, get_balance, get_or_create_balance, recompute_posture,
    recompute_shrink_ratio, evaluate_suspension, audit_valuation_unit_cents,
    period_window, current_period_window, scans_in_window,
    compute_statement_fields, teardown_penalty_cents, _effective_directive,
)

bp = Blueprint("finance", __name__)

AUDIT_TERMINAL = {"LOCKED"}
MARKDOWN_TERMINAL = {"REJECTED", "APPLIED", "EXPIRED"}
SETTLEMENT_TERMINAL = {"PAID"}
SET_TERMINAL = {"RECONCILED"}


# =============================================================================
# Shrink audits (PRD Section 3.7)
# =============================================================================

@bp.route("/audit-counts", methods=["POST"])
def create_audit():
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    body = get_json(request)
    fk_exists(body, "store_agreement_id", store.agreements)
    agreement_id = require_str(body, "store_agreement_id")
    scope = require_enum(body, "scope", ["FULL", "CATEGORY"])
    # category is required exactly when the scope is CATEGORY.
    category = None
    if scope == "CATEGORY":
        category = require_enum(body, "category", CATEGORIES)
    elif body.get("category") is not None:
        category = require_enum(body, "category", CATEGORIES)
    audit = new_entity({
        "store_agreement_id": agreement_id,
        "scope": scope,
        "category": category,
        "status": "SCHEDULED",
        "counted_lines": [],
        "counted_by_user_id": None,
        "scanned_units_since_last_audit": None,
        "variance_units": 0,
        "free_allowance_units": 0,
        "chargeable_units": 0,
        "valuation_unit_cents": None,
        "variance_value_cents": 0,
        "retailer_charge_cents": 0,
        "submitted_at": None,
        "certified_at": None,
        "certified_by_user_id": None,
    })
    store.audit_counts[audit["id"]] = audit
    return response.success(public(audit), http_status=201)


@bp.route("/audit-counts", methods=["GET"])
def list_audits():
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = store.audit_counts.values()
    for param in ("store_agreement_id", "status"):
        val = request.args.get(param)
        if val is not None:
            rows = [a for a in rows if a[param] == val]
    page, meta = list_page(rows, limit, offset)
    return response.success(page, is_list=True, pagination=meta)


@bp.route("/audit-counts/<aid>", methods=["GET"])
def get_audit(aid):
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    audit = get_or_404(store.audit_counts, aid, "audit count")
    return response.success(public(audit))


@bp.route("/audit-counts/<aid>/start", methods=["POST"])
def start_audit(aid):
    _, role = extract_identity(request.headers)
    require_role(role, ["FieldAuditor"])
    audit = get_or_404(store.audit_counts, aid, "audit count")
    get_json(request)
    require_from_state(audit, ["SCHEDULED"], AUDIT_TERMINAL, "audit count", target="IN_PROGRESS")
    agreement = store.agreements[audit["store_agreement_id"]]
    if agreement["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "agreement is not ACTIVE")
    audit["status"] = "IN_PROGRESS"
    touch(audit)
    return response.success(public(audit))


@bp.route("/audit-counts/<aid>/submit", methods=["POST"])
def submit_audit(aid):
    user_id, role = extract_identity(request.headers)
    require_role(role, ["FieldAuditor"])
    audit = get_or_404(store.audit_counts, aid, "audit count")
    body = get_json(request)
    lines = body.get("counted_lines")
    if not isinstance(lines, list):
        raise err("ERR_INVALID_REQUEST", "counted_lines must be an array")
    parsed = []
    for line in lines:
        if not isinstance(line, dict):
            raise err("ERR_INVALID_REQUEST", "each counted line must be an object")
        pid = line.get("product_id")
        if not isinstance(pid, str) or pid == "":
            raise err("ERR_INVALID_REQUEST", "line product_id is required")
        if pid not in store.products:
            raise err("ERR_NOT_FOUND", "product_id %s does not exist" % pid)
        counted = line.get("counted_units")
        if not isinstance(counted, int) or isinstance(counted, bool):
            raise err("ERR_INVALID_REQUEST", "line counted_units must be an integer")
        if counted < 0:
            raise err("ERR_RANGE_INVALID", "line counted_units must be >= 0")
        parsed.append({"product_id": pid, "counted_units": counted})
    require_from_state(audit, ["IN_PROGRESS"], AUDIT_TERMINAL, "audit count", target="SUBMITTED")
    agreement = store.agreements[audit["store_agreement_id"]]
    submitted_at = store.now_iso()
    # Freeze the evidentiary record, including book on-hand per line.
    frozen = []
    for line in parsed:
        balance = get_balance(agreement["id"], line["product_id"])
        book = balance["on_hand_units"] if balance is not None else 0
        frozen.append({
            "product_id": line["product_id"],
            "counted_units": line["counted_units"],
            "_book_on_hand": book,
        })
    # scanned_units_since_last_audit: MATCHED SALE units of the audited
    # products at/after the previous CERTIFIED/LOCKED audit's submitted_at
    # (or agreement activation) and strictly before this audit's submitted_at.
    prior = [
        a for a in store.audit_counts.values()
        if a["store_agreement_id"] == agreement["id"]
        and a["id"] != audit["id"]
        and a["status"] in ("CERTIFIED", "LOCKED")
        and a.get("submitted_at") is not None
    ]
    if prior:
        anchor = max(prior, key=lambda a: (a["submitted_at"], a["_seq"]))["submitted_at"]
    else:
        anchor = agreement["activated_at"]
    audited_products = {l["product_id"] for l in frozen}
    scanned = 0
    for s in store.scan_events.values():
        if (s["store_agreement_id"] == agreement["id"]
                and s["status"] == "MATCHED"
                and s["event_type"] == "SALE"
                and s["product_id"] in audited_products
                and (anchor is None or s["scanned_at"] >= anchor)
                and s["scanned_at"] < submitted_at):
            scanned += s["quantity"]
    variance = sum(l["_book_on_hand"] - l["counted_units"] for l in frozen)
    free_allowance = rhu(dec(scanned) * dec(agreement["free_allowance_pct"]))
    audit["counted_lines"] = frozen
    audit["counted_by_user_id"] = user_id
    audit["submitted_at"] = submitted_at
    audit["scanned_units_since_last_audit"] = scanned
    audit["variance_units"] = variance
    audit["free_allowance_units"] = free_allowance
    audit["chargeable_units"] = max(0, variance - free_allowance)
    audit["status"] = "SUBMITTED"
    touch(audit)
    return response.success(public(audit))


@bp.route("/audit-counts/<aid>/dispute", methods=["POST"])
def dispute_audit(aid):
    user_id, role = extract_identity(request.headers)
    require_role(role, ["RetailerManager"])
    audit = get_or_404(store.audit_counts, aid, "audit count")
    get_json(request)  # optional reason accepted and ignored
    agreement = store.agreements[audit["store_agreement_id"]]
    require_store_manager(user_id, agreement)
    require_from_state(audit, ["SUBMITTED"], AUDIT_TERMINAL, "audit count", target="DISPUTED")
    audit["status"] = "DISPUTED"
    touch(audit)
    return response.success(public(audit))


@bp.route("/audit-counts/<aid>/order-recount", methods=["POST"])
def order_recount(aid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    audit = get_or_404(store.audit_counts, aid, "audit count")
    get_json(request)
    require_from_state(audit, ["DISPUTED"], AUDIT_TERMINAL, "audit count", target="IN_PROGRESS")
    # Revision loop: clear the frozen lines, counter identity, computed fields.
    audit["counted_lines"] = []
    audit["counted_by_user_id"] = None
    audit["submitted_at"] = None
    audit["scanned_units_since_last_audit"] = None
    audit["variance_units"] = 0
    audit["free_allowance_units"] = 0
    audit["chargeable_units"] = 0
    audit["status"] = "IN_PROGRESS"
    touch(audit)
    return response.success(public(audit))


@bp.route("/audit-counts/<aid>/certify", methods=["POST"])
def certify_audit(aid):
    user_id, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    audit = get_or_404(store.audit_counts, aid, "audit count")
    body = get_json(request)
    expected = require_int(body, "expected_audit_count_version")
    require_from_state(audit, ["SUBMITTED"], AUDIT_TERMINAL, "audit count", target="CERTIFIED")
    # OCC (stage 11) precedes segregation of duties (stage 12).
    if expected != audit["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_audit_count_version does not match current version")
    if user_id == audit["counted_by_user_id"]:
        raise err("ERR_SOD_CERTIFIER_IS_COUNTER",
                  "certifier must differ from the auditor who counted")
    agreement = store.agreements[audit["store_agreement_id"]]
    # Price the variance per the agreement's shrink valuation variant.
    valuation = audit_valuation_unit_cents(audit, agreement)
    audit["valuation_unit_cents"] = valuation
    audit["variance_value_cents"] = audit["chargeable_units"] * (valuation or 0)
    audit["retailer_charge_cents"] = rhu(
        dec(audit["variance_value_cents"]) * dec(agreement["shrink_retailer_share_pct"]))
    audit["certified_at"] = store.now_iso()
    audit["certified_by_user_id"] = user_id
    # Cascade link 1: each counted line rewrites its inventory balance.
    for line in audit["counted_lines"]:
        balance = get_or_create_balance(agreement["id"], line["product_id"])
        balance["on_hand_units"] = line["counted_units"]
        balance["lifetime_shrink_units"] += max(0, line["_book_on_hand"] - line["counted_units"])
        recompute_posture(balance)
        touch(balance)
    # Cascade link 2: the agreement accumulates physical shrink (floored at 0).
    agreement["cumulative_shrink_units"] += max(0, audit["variance_units"])
    recompute_shrink_ratio(agreement)
    touch(agreement)
    # Cascade link 3: the suspension posture (which cancels scheduled visits).
    evaluate_suspension(agreement)
    touch(audit)
    audit["status"] = "CERTIFIED"
    return response.success(public(audit))


@bp.route("/audit-counts/<aid>/lock", methods=["POST"])
def lock_audit(aid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    audit = get_or_404(store.audit_counts, aid, "audit count")
    get_json(request)
    require_from_state(audit, ["CERTIFIED"], AUDIT_TERMINAL, "audit count", target="LOCKED")
    audit["status"] = "LOCKED"
    touch(audit)
    return response.success(public(audit))


# =============================================================================
# Markdown authorizations (PRD Section 3.8)
# =============================================================================

@bp.route("/markdown-authorizations", methods=["POST"])
def create_markdown():
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    body = get_json(request)
    fk_exists(body, "store_agreement_id", store.agreements)
    fk_exists(body, "product_id", store.products)
    agreement_id = require_str(body, "store_agreement_id")
    product_id = require_str(body, "product_id")
    auth_type = require_enum(body, "auth_type", ["MARKDOWN", "RETURN_TO_VENDOR"])
    units = require_int(body, "units")
    markdown_price = None
    if auth_type == "MARKDOWN":
        markdown_price = require_int(body, "markdown_price_cents")
    if units < 1:
        raise err("ERR_RANGE_INVALID", "units must be >= 1")
    if auth_type == "MARKDOWN":
        # May be zero but must sit strictly below the current directive price.
        if markdown_price < 0:
            raise err("ERR_RANGE_INVALID", "markdown_price_cents must be >= 0")
        directive = _effective_directive(agreement_id, product_id)
        if directive is not None and markdown_price >= directive["price_cents"]:
            raise err("ERR_RANGE_INVALID",
                      "markdown_price_cents must be below the current directive price")
    row = new_entity({
        "store_agreement_id": agreement_id,
        "product_id": product_id,
        "auth_type": auth_type,
        "units": units,
        "markdown_price_cents": markdown_price,
        "status": "REQUESTED",
        "credit_cents": 0,
        "approved_at": None,
        "applied_at": None,
    })
    store.markdown_authorizations[row["id"]] = row
    return response.success(public(row), http_status=201)


@bp.route("/markdown-authorizations", methods=["GET"])
def list_markdowns():
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = store.markdown_authorizations.values()
    for param in ("store_agreement_id", "product_id", "status"):
        val = request.args.get(param)
        if val is not None:
            rows = [m for m in rows if m[param] == val]
    page, meta = list_page(rows, limit, offset)
    return response.success(page, is_list=True, pagination=meta)


@bp.route("/markdown-authorizations/<mid>", methods=["GET"])
def get_markdown(mid):
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    row = get_or_404(store.markdown_authorizations, mid, "markdown authorization")
    return response.success(public(row))


@bp.route("/markdown-authorizations/<mid>/approve", methods=["POST"])
def approve_markdown(mid):
    user_id, role = extract_identity(request.headers)
    require_role(role, ["RetailerManager"])
    row = get_or_404(store.markdown_authorizations, mid, "markdown authorization")
    get_json(request)
    agreement = store.agreements[row["store_agreement_id"]]
    require_store_manager(user_id, agreement)
    require_from_state(row, ["REQUESTED"], MARKDOWN_TERMINAL, "markdown authorization", target="APPROVED")
    row["status"] = "APPROVED"
    row["approved_at"] = store.now_iso()
    touch(row)
    return response.success(public(row))


@bp.route("/markdown-authorizations/<mid>/reject", methods=["POST"])
def reject_markdown(mid):
    user_id, role = extract_identity(request.headers)
    require_role(role, ["RetailerManager"])
    row = get_or_404(store.markdown_authorizations, mid, "markdown authorization")
    get_json(request)  # optional reason accepted and ignored
    agreement = store.agreements[row["store_agreement_id"]]
    require_store_manager(user_id, agreement)
    require_from_state(row, ["REQUESTED"], MARKDOWN_TERMINAL, "markdown authorization", target="REJECTED")
    row["status"] = "REJECTED"
    touch(row)
    return response.success(public(row))


@bp.route("/markdown-authorizations/<mid>/apply", methods=["POST"])
def apply_markdown(mid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    row = get_or_404(store.markdown_authorizations, mid, "markdown authorization")
    get_json(request)
    require_from_state(row, ["APPROVED"], MARKDOWN_TERMINAL, "markdown authorization", target="APPLIED")
    agreement = store.agreements[row["store_agreement_id"]]
    if row["auth_type"] == "MARKDOWN":
        # Credit = price gap * units * jobber share, rounded half-up.
        directive = _effective_directive(row["store_agreement_id"], row["product_id"])
        directive_price = directive["price_cents"] if directive is not None else 0
        if agreement["markdown_liability"] == "JOBBER":
            share = dec(1)
        elif agreement["markdown_liability"] == "RETAILER":
            share = dec(0)
        else:
            share = dec(agreement["markdown_jobber_share_pct"])
        credit = rhu(dec(directive_price - row["markdown_price_cents"])
                     * row["units"] * share)
        # Per-period cap keyed on the clock-current period's gross sales.
        window = current_period_window(agreement, store.today())
        gross = 0
        if window is not None:
            gross = sum(s["line_value_cents"]
                        for s in scans_in_window(agreement["id"], window[0], window[1]))
        cap = rhu(dec(agreement["markdown_cap_pct_of_gross"]) * gross)
        if credit > cap:
            raise err("ERR_MARKDOWN_CAP_EXCEEDED",
                      "markdown credit exceeds the per-period cap")
        row["credit_cents"] = credit
    else:  # RETURN_TO_VENDOR: the balance must physically cover the pull.
        balance = get_balance(row["store_agreement_id"], row["product_id"])
        on_hand = balance["on_hand_units"] if balance is not None else 0
        if on_hand < row["units"]:
            raise err("ERR_RANGE_INVALID", "units exceed on-hand balance")
        balance["on_hand_units"] -= row["units"]
        balance["lifetime_rma_units"] += row["units"]
        recompute_posture(balance)
        touch(balance)
        row["credit_cents"] = 0
    row["status"] = "APPLIED"
    row["applied_at"] = store.now_iso()
    touch(row)
    return response.success(public(row))


# =============================================================================
# Settlement statements (PRD Section 3.9)
# =============================================================================

@bp.route("/settlement-statements", methods=["POST"])
def create_statement():
    user_id, role = extract_identity(request.headers)
    require_role(role, ["JobberFinance"])
    body = get_json(request)
    fk_exists(body, "store_agreement_id", store.agreements)
    agreement_id = require_str(body, "store_agreement_id")
    period_index = require_int(body, "period_index")
    if period_index < 0:
        raise err("ERR_RANGE_INVALID", "period_index must be >= 0")
    agreement = store.agreements[agreement_id]
    program = store.programs[agreement["program_id"]]
    # Stage 16: the period must have begun (needs an activation anchor).
    if agreement.get("activated_at"):
        period_start, _ = period_window(agreement, period_index)
        if period_start.strftime("%Y-%m-%d") > store.today_str():
            raise err("ERR_SETTLEMENT_PERIOD_NOT_CLOSED", "period has not begun")
    # Stage 19: one statement per (agreement, period_index).
    for s in store.settlement_statements.values():
        if s["store_agreement_id"] == agreement_id and s["period_index"] == period_index:
            raise err("ERR_SETTLEMENT_ALREADY_EXISTS",
                      "a statement already exists for this agreement and period")
    # Stage 27: the agreement must be ACTIVE.
    if agreement["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "agreement is not ACTIVE")
    fields = compute_statement_fields(agreement, program, period_index, "PROVISIONAL")
    statement = new_entity({
        "store_agreement_id": agreement_id,
        "period_index": period_index,
        "status": "PROVISIONAL",
        "created_by_user_id": user_id,
        "approved_by_user_id": None,
        "paid_at": None,
    })
    statement.update(fields)
    store.settlement_statements[statement["id"]] = statement
    return response.success(public(statement), http_status=201)


@bp.route("/settlement-statements", methods=["GET"])
def list_statements():
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = store.settlement_statements.values()
    for param in ("store_agreement_id", "status"):
        val = request.args.get(param)
        if val is not None:
            rows = [s for s in rows if s[param] == val]
    page, meta = list_page(rows, limit, offset)
    return response.success(page, is_list=True, pagination=meta)


@bp.route("/settlement-statements/<sid>", methods=["GET"])
def get_statement(sid):
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    statement = get_or_404(store.settlement_statements, sid, "settlement statement")
    return response.success(public(statement))


@bp.route("/settlement-statements/<sid>/finalize", methods=["POST"])
def finalize_statement(sid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberFinance"])
    statement = get_or_404(store.settlement_statements, sid, "settlement statement")
    body = get_json(request)
    expected = require_int(body, "expected_settlement_statement_version")
    require_from_state(statement, ["PROVISIONAL"], SETTLEMENT_TERMINAL, "settlement statement", target="FINALIZED")
    # Stage 11: OCC on the statement version.
    if expected != statement["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_settlement_statement_version does not match current version")
    agreement = store.agreements[statement["store_agreement_id"]]
    program = store.programs[agreement["program_id"]]
    # Stage 16: the period must be fully closed (clock date >= period_end).
    period_start, period_end = period_window(agreement, statement["period_index"])
    if store.today_str() < period_end.strftime("%Y-%m-%d"):
        raise err("ERR_SETTLEMENT_PERIOD_NOT_CLOSED", "period is not fully closed")
    # Stage 28: every in-window audit must be CERTIFIED or LOCKED.
    from services import _window_bounds
    lo, hi = _window_bounds(period_start, period_end)
    for a in store.audit_counts.values():
        if (a["store_agreement_id"] == agreement["id"]
                and a.get("submitted_at") is not None
                and lo <= a["submitted_at"] < hi
                and a["status"] not in ("CERTIFIED", "LOCKED")):
            raise err("ERR_AUDIT_NOT_CERTIFIED",
                      "an in-window audit is not certified")
    fields = compute_statement_fields(agreement, program, statement["period_index"], "FINAL")
    statement.update(fields)
    # Stamp the included scans and lock the included certified audits.
    for s in scans_in_window(agreement["id"], period_start, period_end):
        if s.get("settled_in_statement_id") is None:
            s["settled_in_statement_id"] = statement["id"]
    for a in store.audit_counts.values():
        if (a["store_agreement_id"] == agreement["id"]
                and a["status"] == "CERTIFIED"
                and a.get("certified_at") is not None
                and lo <= a["certified_at"] < hi):
            a["status"] = "LOCKED"
            touch(a)
    statement["status"] = "FINALIZED"
    touch(statement)
    return response.success(public(statement))


@bp.route("/settlement-statements/<sid>/dispute", methods=["POST"])
def dispute_statement(sid):
    user_id, role = extract_identity(request.headers)
    require_role(role, ["RetailerManager"])
    statement = get_or_404(store.settlement_statements, sid, "settlement statement")
    get_json(request)  # optional reason accepted and ignored
    agreement = store.agreements[statement["store_agreement_id"]]
    require_store_manager(user_id, agreement)
    require_from_state(statement, ["FINALIZED"], SETTLEMENT_TERMINAL, "settlement statement", target="DISPUTED")
    statement["status"] = "DISPUTED"
    touch(statement)
    return response.success(public(statement))


@bp.route("/settlement-statements/<sid>/revise", methods=["POST"])
def revise_statement(sid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberFinance"])
    statement = get_or_404(store.settlement_statements, sid, "settlement statement")
    get_json(request)
    require_from_state(statement, ["DISPUTED"], SETTLEMENT_TERMINAL, "settlement statement", target="PROVISIONAL")
    agreement = store.agreements[statement["store_agreement_id"]]
    program = store.programs[agreement["program_id"]]
    fields = compute_statement_fields(agreement, program, statement["period_index"], "PROVISIONAL")
    statement.update(fields)
    statement["status"] = "PROVISIONAL"
    touch(statement)
    return response.success(public(statement))


@bp.route("/settlement-statements/<sid>/approve", methods=["POST"])
def approve_statement(sid):
    user_id, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    statement = get_or_404(store.settlement_statements, sid, "settlement statement")
    get_json(request)
    require_from_state(statement, ["FINALIZED"], SETTLEMENT_TERMINAL, "settlement statement", target="APPROVED")
    # SoD: the approver must differ from the statement's creator.
    if user_id == statement["created_by_user_id"]:
        raise err("ERR_SOD_APPROVER_IS_CREATOR",
                  "approver must differ from the statement's creator")
    statement["status"] = "APPROVED"
    statement["approved_by_user_id"] = user_id
    touch(statement)
    return response.success(public(statement))


@bp.route("/settlement-statements/<sid>/pay", methods=["POST"])
def pay_statement(sid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberFinance"])
    statement = get_or_404(store.settlement_statements, sid, "settlement statement")
    get_json(request)
    require_from_state(statement, ["APPROVED"], SETTLEMENT_TERMINAL, "settlement statement", target="PAID")
    agreement = store.agreements[statement["store_agreement_id"]]
    program = store.programs[agreement["program_id"]]
    if statement["net_payable_to_jobber_cents"] < program["min_payout_cents"]:
        raise err("ERR_PAYOUT_BELOW_MINIMUM",
                  "net payable is below the program payout minimum")
    statement["status"] = "PAID"
    statement["paid_at"] = store.now_iso()
    touch(statement)
    return response.success(public(statement))


# =============================================================================
# Seasonal sets (PRD Section 3.4)
# =============================================================================

@bp.route("/seasonal-sets", methods=["POST"])
def create_set():
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    body = get_json(request)
    fk_exists(body, "store_agreement_id", store.agreements)
    agreement_id = require_str(body, "store_agreement_id")
    theme = require_str(body, "theme")
    category = require_enum(body, "category", CATEGORIES)
    facings = require_int(body, "allocated_facings")
    start = parse_date(body.get("set_window_start"), "set_window_start")
    end = parse_date(body.get("set_window_end"), "set_window_end")
    deadline = parse_date(body.get("teardown_deadline"), "teardown_deadline")
    if facings < 1:
        raise err("ERR_RANGE_INVALID", "allocated_facings must be >= 1")
    # Setup windows are closed intervals: start <= end.
    if start > end:
        raise err("ERR_WINDOW_INVALID", "set_window_start must not follow set_window_end")
    row = new_entity({
        "store_agreement_id": agreement_id,
        "theme": theme,
        "category": category,
        "allocated_facings": facings,
        "set_window_start": start.strftime("%Y-%m-%d"),
        "set_window_end": end.strftime("%Y-%m-%d"),
        "teardown_deadline": deadline.strftime("%Y-%m-%d"),
        "status": "PLANNED",
        "actual_teardown_date": None,
        "penalty_cents": 0,
        "_reconciled_at": None,
    })
    store.seasonal_sets[row["id"]] = row
    return response.success(public(row), http_status=201)


@bp.route("/seasonal-sets", methods=["GET"])
def list_sets():
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = store.seasonal_sets.values()
    for param in ("store_agreement_id", "status"):
        val = request.args.get(param)
        if val is not None:
            rows = [s for s in rows if s[param] == val]
    page, meta = list_page(rows, limit, offset)
    return response.success(page, is_list=True, pagination=meta)


@bp.route("/seasonal-sets/<sid>", methods=["GET"])
def get_set(sid):
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    row = get_or_404(store.seasonal_sets, sid, "seasonal set")
    return response.success(public(row))


@bp.route("/seasonal-sets/<sid>/begin-setup", methods=["POST"])
def begin_setup(sid):
    _, role = extract_identity(request.headers)
    require_role(role, ["RouteDriver"])
    row = get_or_404(store.seasonal_sets, sid, "seasonal set")
    get_json(request)
    require_from_state(row, ["PLANNED"], SET_TERMINAL, "seasonal set", target="SET_IN_PROGRESS")
    today = store.today_str()
    if not (row["set_window_start"] <= today <= row["set_window_end"]):
        raise err("ERR_SEASONAL_WINDOW_NOT_OPEN",
                  "clock date is outside the setup window")
    row["status"] = "SET_IN_PROGRESS"
    touch(row)
    return response.success(public(row))


@bp.route("/seasonal-sets/<sid>/complete-setup", methods=["POST"])
def complete_setup(sid):
    _, role = extract_identity(request.headers)
    require_role(role, ["RouteDriver"])
    row = get_or_404(store.seasonal_sets, sid, "seasonal set")
    get_json(request)
    require_from_state(row, ["SET_IN_PROGRESS"], SET_TERMINAL, "seasonal set", target="SET_COMPLETE")
    # Requires a covering ACTIVE allocation in the set's category.
    covering = any(
        a["store_agreement_id"] == row["store_agreement_id"]
        and a["category"] == row["category"]
        and a["status"] == "ACTIVE"
        and a["facings"] >= row["allocated_facings"]
        for a in store.space_allocations.values()
    )
    if not covering:
        raise err("ERR_SEASONAL_ALLOCATION_MISSING",
                  "no covering ACTIVE space allocation for this category")
    row["status"] = "SET_COMPLETE"
    touch(row)
    return response.success(public(row))


@bp.route("/seasonal-sets/<sid>/activate", methods=["POST"])
def activate_set(sid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    row = get_or_404(store.seasonal_sets, sid, "seasonal set")
    get_json(request)
    require_from_state(row, ["SET_COMPLETE"], SET_TERMINAL, "seasonal set", target="ACTIVE_SEASON")
    row["status"] = "ACTIVE_SEASON"
    touch(row)
    return response.success(public(row))


@bp.route("/seasonal-sets/<sid>/teardown", methods=["POST"])
def teardown_set(sid):
    _, role = extract_identity(request.headers)
    require_role(role, ["RouteDriver"])
    row = get_or_404(store.seasonal_sets, sid, "seasonal set")
    get_json(request)
    require_from_state(row, ["ACTIVE_SEASON", "TEARDOWN_DUE"], SET_TERMINAL, "seasonal set", target="TORN_DOWN")
    today = store.today_str()
    row["actual_teardown_date"] = today
    row["penalty_cents"] = teardown_penalty_cents(row["teardown_deadline"], today)
    row["status"] = "TORN_DOWN"
    touch(row)
    return response.success(public(row))


@bp.route("/seasonal-sets/<sid>/reconcile", methods=["POST"])
def reconcile_set(sid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    row = get_or_404(store.seasonal_sets, sid, "seasonal set")
    get_json(request)
    require_from_state(row, ["TORN_DOWN"], SET_TERMINAL, "seasonal set", target="RECONCILED")
    # The penalty lands in the settlement window containing the reconcile date.
    row["_reconciled_at"] = store.now_iso()
    row["status"] = "RECONCILED"
    touch(row)
    return response.success(public(row))
