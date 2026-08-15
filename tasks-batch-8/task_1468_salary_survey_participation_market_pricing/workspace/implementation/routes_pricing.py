"""MarketComposites, MarketAdjustmentCycles, MarketAdjustments,
CompensationReports, AuditEvents, and the logical-clock endpoint."""
from decimal import Decimal

from flask import Blueprint, g, request

from calc import (
    CUSTOM_GEO_INDEX_BP, build_market_position_snapshot, compa_ratio_bp,
    compute_composite_values,
)
from common import (
    ApiError, ALL_ROLES, actor_employee_id, body, current_date, db, emit_audit,
    filter_records, get_or_404, iso, new_record, ok, ok_list, parse_date,
    parse_iso8601, pub, require_roles, set_clock, touch, v_date, v_int, v_str,
)

bp = Blueprint("pricing", __name__)


def _max_adjustment_cents(base_salary):
    """15% of current base, exact Decimal comparison (no premature rounding)."""
    return Decimal(base_salary) * Decimal("0.15")


def _check_amount(proposed, base_salary):
    if proposed <= 0 or Decimal(proposed) > _max_adjustment_cents(base_salary):
        raise ApiError("ERR_INVALID_AMOUNT", 422,
                       "proposed_amount_cents must be > 0 and <= 15% of current base salary")


# ---------------------------------------------------------------------------
# Market composites
# ---------------------------------------------------------------------------
@bp.route("/jobs/<jid>/composites", methods=["POST"])
@require_roles("CompManager")
def create_composite(jid):
    job = get_or_404("jobs", jid)
    b = body()
    strategy_id = b.get("strategy_policy_id")
    if not isinstance(strategy_id, str) or not strategy_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "strategy_policy_id is required")
    geo_code = v_str(b, "job_geo_code")
    strategy = db["strategies"].get(strategy_id)
    if strategy is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Strategy {strategy_id} not found")
    if (strategy["geo_differential_policy"] == "CUSTOM_GEO_INDEX"
            and geo_code not in CUSTOM_GEO_INDEX_BP):
        raise ApiError("ERR_GEO_INDEX_MISSING", 422,
                       f"CUSTOM_GEO_INDEX policy has no geo index entry for {geo_code}")
    rec = new_record()
    rec.update({
        "job_id": job["id"],
        "strategy_policy_id": strategy_id,
        "job_geo_code": geo_code,
        "blended_p25_cents": None,
        "blended_p50_cents": None,
        "blended_p75_cents": None,
        "blended_p90_cents": None,
        "geo_differential_bp": None,
        "source_count": 0,
        "published_at": None,
        "status": "DRAFT",
    })
    db["composites"][rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.route("/composites/<cid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_composite(cid):
    return ok(pub(get_or_404("composites", cid)))


@bp.route("/composites", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_composites():
    return ok_list(filter_records("composites", {
        "job_id": request.args.get("job_id"),
        "strategy_policy_id": request.args.get("strategy_policy_id"),
        "status": request.args.get("status"),
    }))


@bp.route("/jobs/<jid>/composites", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_job_composites(jid):
    job = get_or_404("jobs", jid)
    return ok_list(filter_records("composites", {"job_id": job["id"]}))


@bp.route("/strategies/<sid>/composites", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_strategy_composites(sid):
    strategy = get_or_404("strategies", sid)
    return ok_list(filter_records("composites", {"strategy_policy_id": strategy["id"]}))


@bp.route("/composites/<cid>/recompute", methods=["POST"])
@require_roles("CompManager")
def recompute_composite(cid):
    comp = get_or_404("composites", cid)
    if comp["status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot recompute a composite in status {comp['status']}")
    values = compute_composite_values(comp)
    comp.update(values)
    touch(comp)
    return ok(pub(comp))


@bp.route("/composites/<cid>/publish", methods=["POST"])
@require_roles("CompManager")
def publish_composite(cid):
    comp = get_or_404("composites", cid)
    b = body()
    expected_job_version = v_int(b, "expected_job_version")
    if comp["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot publish a composite in status {comp['status']}")
    job = db["jobs"][comp["job_id"]]
    # Rung 17: one PUBLISHED composite per job+strategy
    for c in db["composites"].values():
        if (c["job_id"] == job["id"] and c["id"] != comp["id"]
                and c["status"] == "PUBLISHED"
                and c["strategy_policy_id"] == comp["strategy_policy_id"]):
            raise ApiError("ERR_ALREADY_PUBLISHED", 409,
                           "Another PUBLISHED composite exists for this job and strategy")
    # Rungs 18-19: sources and geo-index coverage (raises ERR_NO_SOURCES / ERR_GEO_INDEX_MISSING)
    values = compute_composite_values(comp)
    # Rung 20: optimistic concurrency on the parent Job
    if expected_job_version != job["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_job_version does not match the job's current version")
    comp.update(values)
    comp["status"] = "PUBLISHED"
    comp["published_at"] = iso()
    touch(comp)
    # Supersede any prior PUBLISHED composite for the same job
    for c in db["composites"].values():
        if c["job_id"] == job["id"] and c["id"] != comp["id"] and c["status"] == "PUBLISHED":
            c["status"] = "SUPERSEDED"
            touch(c)
    job["current_market_composite_id"] = comp["id"]
    touch(job)
    emit_audit(job["org_id"], actor_employee_id(), "COMPOSITE_PUBLISH",
               "MarketComposite", comp["id"], {"status": "PUBLISHED"})
    return ok(pub(comp))


# ---------------------------------------------------------------------------
# Market adjustment cycles
# ---------------------------------------------------------------------------
@bp.route("/orgs/<oid>/cycles", methods=["POST"])
@require_roles("CompManager")
def create_cycle(oid):
    org = get_or_404("orgs", oid)
    b = body()
    name = v_str(b, "name")
    effective_date = v_date(b, "effective_date")
    budget = v_int(b, "budget_cents")
    new_eff = parse_date(effective_date)
    for c in db["cycles"].values():
        if c["org_id"] == org["id"] and c["status"] in ("OPEN", "LOCKED"):
            created_d = parse_iso8601(c["created_at"]).date()
            if created_d <= new_eff <= parse_date(c["effective_date"]):
                raise ApiError("ERR_CYCLE_EFFECTIVE_OVERLAP", 409,
                               "effective_date falls inside another OPEN or LOCKED cycle's window")
    rec = new_record()
    rec.update({
        "org_id": org["id"],
        "name": name,
        "effective_date": effective_date,
        "budget_cents": budget,
        "allocated_cents": 0,
        "status": "OPEN",
    })
    db["cycles"][rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.route("/cycles/<cid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_cycle(cid):
    return ok(pub(get_or_404("cycles", cid)))


@bp.route("/cycles", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_cycles():
    return ok_list(filter_records("cycles", {
        "org_id": request.args.get("org_id"),
        "status": request.args.get("status"),
    }))


@bp.route("/orgs/<oid>/cycles", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_org_cycles(oid):
    org = get_or_404("orgs", oid)
    return ok_list(filter_records("cycles", {"org_id": org["id"]}))


@bp.route("/cycles/<cid>/lock", methods=["POST"])
@require_roles("CompManager")
def lock_cycle(cid):
    c = get_or_404("cycles", cid)
    if c["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot lock a cycle in status {c['status']}")
    for a in db["adjustments"].values():
        if a["cycle_id"] == c["id"] and a["status"] == "PENDING_APPROVAL":
            raise ApiError("ERR_CYCLE_HAS_PENDING", 409,
                           "Cycle has at least one PENDING_APPROVAL adjustment")
    c["status"] = "LOCKED"
    touch(c)
    emit_audit(c["org_id"], actor_employee_id(), "CYCLE_LOCK",
               "MarketAdjustmentCycle", c["id"], {"status": "LOCKED"})
    return ok(pub(c))


@bp.route("/cycles/<cid>/unlock", methods=["POST"])
@require_roles("CompManager")
def unlock_cycle(cid):
    c = get_or_404("cycles", cid)
    if c["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot unlock a cycle in status {c['status']}")
    c["status"] = "OPEN"
    touch(c)
    emit_audit(c["org_id"], actor_employee_id(), "CYCLE_UNLOCK",
               "MarketAdjustmentCycle", c["id"], {"status": "OPEN"})
    return ok(pub(c))


@bp.route("/cycles/<cid>/close", methods=["POST"])
@require_roles("CompManager")
def close_cycle(cid):
    c = get_or_404("cycles", cid)
    if c["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot close a cycle in status {c['status']}")
    for a in db["adjustments"].values():
        if a["cycle_id"] == c["id"] and a["status"] not in ("APPLIED", "REJECTED"):
            raise ApiError("ERR_CYCLE_HAS_UNAPPLIED", 409,
                           "Cycle has adjustments that are not in a terminal state")
    c["status"] = "CLOSED"
    touch(c)
    emit_audit(c["org_id"], actor_employee_id(), "CYCLE_CLOSE",
               "MarketAdjustmentCycle", c["id"], {"status": "CLOSED"})
    return ok(pub(c))


# ---------------------------------------------------------------------------
# Market adjustments
# ---------------------------------------------------------------------------
@bp.route("/cycles/<cid>/adjustments", methods=["POST"])
@require_roles("CompAnalyst")
def create_adjustment(cid):
    cycle = get_or_404("cycles", cid)
    b = body()
    employee_id = b.get("employee_id")
    if not isinstance(employee_id, str) or not employee_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "employee_id is required")
    if "proposed_amount_cents" not in b:
        raise ApiError("ERR_INVALID_REQUEST", 400, "proposed_amount_cents is required")
    amount = b["proposed_amount_cents"]
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "proposed_amount_cents must be an integer")
    proposed_by = v_str(b, "proposed_by_employee_id")
    emp = db["employees"].get(employee_id)
    if emp is None or emp["org_id"] != cycle["org_id"]:
        raise ApiError("ERR_NOT_FOUND", 404, f"Employee {employee_id} not found in this organization")
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN", 409,
                       f"Cycle is in status {cycle['status']}, not OPEN")
    _check_amount(amount, emp["base_salary_annual_cents"])
    rec = new_record()
    rec.update({
        "cycle_id": cycle["id"],
        "employee_id": employee_id,
        "job_id": emp["job_id"],
        "proposed_amount_cents": amount,
        "proposed_by_employee_id": proposed_by,
        "approved_by_employee_id": None,
        "pre_adjustment_compa_ratio_bp": None,
        "post_adjustment_compa_ratio_bp": None,
        "status": "DRAFT",
    })
    db["adjustments"][rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.route("/adjustments/<aid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_adjustment(aid):
    return ok(pub(get_or_404("adjustments", aid)))


@bp.route("/adjustments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_adjustments():
    return ok_list(filter_records("adjustments", {
        "cycle_id": request.args.get("cycle_id"),
        "employee_id": request.args.get("employee_id"),
        "job_id": request.args.get("job_id"),
        "proposed_by_employee_id": request.args.get("proposed_by_employee_id"),
        "approved_by_employee_id": request.args.get("approved_by_employee_id"),
        "status": request.args.get("status"),
    }))


@bp.route("/cycles/<cid>/adjustments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_cycle_adjustments(cid):
    cycle = get_or_404("cycles", cid)
    return ok_list(filter_records("adjustments", {"cycle_id": cycle["id"]}))


@bp.route("/employees/<eid>/adjustments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_employee_adjustments(eid):
    emp = get_or_404("employees", eid)
    return ok_list(filter_records("adjustments", {"employee_id": emp["id"]}))


@bp.route("/jobs/<jid>/adjustments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_job_adjustments(jid):
    job = get_or_404("jobs", jid)
    return ok_list(filter_records("adjustments", {"job_id": job["id"]}))


@bp.route("/adjustments/<aid>/submit", methods=["POST"])
@require_roles("CompAnalyst")
def submit_adjustment(aid):
    adj = get_or_404("adjustments", aid)
    if adj["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot submit an adjustment in status {adj['status']}")
    cycle = db["cycles"][adj["cycle_id"]]
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN", 409,
                       f"Cycle is in status {cycle['status']}, not OPEN")
    job = db["jobs"][adj["job_id"]]
    if not job["current_market_composite_id"]:
        raise ApiError("ERR_NO_PUBLISHED_COMPOSITE", 409,
                       "Job has no PUBLISHED MarketComposite")
    emp = db["employees"][adj["employee_id"]]
    if emp["status"] != "ACTIVE":
        raise ApiError("ERR_EMPLOYEE_NOT_ACTIVE", 422,
                       "Employee is not ACTIVE")
    _check_amount(adj["proposed_amount_cents"], emp["base_salary_annual_cents"])
    comp = db["composites"][job["current_market_composite_id"]]
    base = emp["base_salary_annual_cents"]
    adj["pre_adjustment_compa_ratio_bp"] = compa_ratio_bp(base, comp["blended_p50_cents"])
    adj["post_adjustment_compa_ratio_bp"] = compa_ratio_bp(
        base + adj["proposed_amount_cents"], comp["blended_p50_cents"])
    adj["status"] = "PENDING_APPROVAL"
    touch(adj)
    return ok(pub(adj))


@bp.route("/adjustments/<aid>/approve", methods=["POST"])
@require_roles("CompManager")
def approve_adjustment(aid):
    adj = get_or_404("adjustments", aid)
    b = body()
    expected_cycle_version = v_int(b, "expected_cycle_version")
    if adj["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot approve an adjustment in status {adj['status']}")
    cycle = db["cycles"][adj["cycle_id"]]
    if g.user_id == adj["proposed_by_employee_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 409,
                       "Approver must differ from the proposer")
    if expected_cycle_version != cycle["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_cycle_version does not match the cycle's current version")
    if cycle["allocated_cents"] + adj["proposed_amount_cents"] > cycle["budget_cents"]:
        raise ApiError("ERR_BUDGET_EXCEEDED", 409,
                       "Approval would push allocated_cents above budget_cents")
    adj["status"] = "APPROVED"
    adj["approved_by_employee_id"] = g.user_id
    touch(adj)
    cycle["allocated_cents"] += adj["proposed_amount_cents"]
    touch(cycle)
    emit_audit(cycle["org_id"], actor_employee_id(), "ADJUSTMENT_APPROVE",
               "MarketAdjustment", adj["id"], {"status": "APPROVED"})
    return ok(pub(adj))


@bp.route("/adjustments/<aid>/reject", methods=["POST"])
@require_roles("CompManager")
def reject_adjustment(aid):
    adj = get_or_404("adjustments", aid)
    if adj["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot reject an adjustment in status {adj['status']}")
    adj["status"] = "REJECTED"
    touch(adj)
    cycle = db["cycles"][adj["cycle_id"]]
    emit_audit(cycle["org_id"], actor_employee_id(), "ADJUSTMENT_REJECT",
               "MarketAdjustment", adj["id"], {"status": "REJECTED"})
    return ok(pub(adj))


@bp.route("/adjustments/<aid>/retract", methods=["POST"])
@require_roles("CompAnalyst")
def retract_adjustment(aid):
    adj = get_or_404("adjustments", aid)
    if adj["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot retract an adjustment in status {adj['status']}")
    cycle = db["cycles"][adj["cycle_id"]]
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN", 409,
                       f"Cycle is in status {cycle['status']}, not OPEN")
    if g.user_id != adj["proposed_by_employee_id"]:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403,
                       "Only the proposer may retract an adjustment")
    adj["status"] = "DRAFT"
    touch(adj)
    return ok(pub(adj))


@bp.route("/adjustments/<aid>/apply", methods=["POST"])
@require_roles("CompManager")
def apply_adjustment(aid):
    adj = get_or_404("adjustments", aid)
    if adj["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot apply an adjustment in status {adj['status']}")
    cycle = db["cycles"][adj["cycle_id"]]
    if cycle["status"] != "LOCKED":
        raise ApiError("ERR_CYCLE_NOT_LOCKED", 409,
                       f"Cycle is in status {cycle['status']}, not LOCKED")
    if current_date() < parse_date(cycle["effective_date"]):
        raise ApiError("ERR_ADJUSTMENT_NOT_YET_EFFECTIVE", 409,
                       "Current date is before the cycle's effective_date")
    emp = db["employees"][adj["employee_id"]]
    emp["base_salary_annual_cents"] += adj["proposed_amount_cents"]
    touch(emp)
    adj["status"] = "APPLIED"
    touch(adj)
    emit_audit(cycle["org_id"], actor_employee_id(), "ADJUSTMENT_APPLY",
               "MarketAdjustment", adj["id"], {"status": "APPLIED"})
    return ok(pub(adj))


# ---------------------------------------------------------------------------
# Compensation reports
# ---------------------------------------------------------------------------
@bp.route("/orgs/<oid>/reports", methods=["POST"])
@require_roles("CompManager")
def create_report(oid):
    org = get_or_404("orgs", oid)
    b = body()
    title = v_str(b, "title")
    period_start = v_date(b, "reporting_period_start")
    period_end = v_date(b, "reporting_period_end")
    pinned = b.get("pinned_strategy_policy_id")
    if not isinstance(pinned, str) or not pinned:
        raise ApiError("ERR_INVALID_REQUEST", 400, "pinned_strategy_policy_id is required")
    if db["strategies"].get(pinned) is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Strategy {pinned} not found")
    rec = new_record()
    rec.update({
        "org_id": org["id"],
        "title": title,
        "reporting_period_start": period_start,
        "reporting_period_end": period_end,
        "pinned_strategy_policy_id": pinned,
        "snapshot_payload": None,
        "presented_at": None,
        "status": "DRAFT",
    })
    db["reports"][rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.route("/reports/<rid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_report(rid):
    return ok(pub(get_or_404("reports", rid)))


@bp.route("/reports", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_reports():
    return ok_list(filter_records("reports", {
        "org_id": request.args.get("org_id"),
        "status": request.args.get("status"),
        "pinned_strategy_policy_id": request.args.get("pinned_strategy_policy_id"),
    }))


@bp.route("/orgs/<oid>/reports", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_org_reports(oid):
    org = get_or_404("orgs", oid)
    return ok_list(filter_records("reports", {"org_id": org["id"]}))


@bp.route("/reports/<rid>/finalize", methods=["POST"])
@require_roles("CompManager")
def finalize_report(rid):
    report = get_or_404("reports", rid)
    b = body()
    exclude_job_ids = b.get("exclude_job_ids")
    if exclude_job_ids is not None:
        if (not isinstance(exclude_job_ids, list)
                or any(not isinstance(x, str) for x in exclude_job_ids)):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "exclude_job_ids must be an array of strings")
    if report["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot finalize a report in status {report['status']}")
    strategy = db["strategies"][report["pinned_strategy_policy_id"]]
    if strategy["status"] != "ACTIVE":
        raise ApiError("ERR_STRATEGY_NOT_ACTIVE", 409,
                       "Pinned strategy policy is not ACTIVE")
    exclude = set(exclude_job_ids or [])
    for job in db["jobs"].values():
        if job["org_id"] != report["org_id"]:
            continue
        cid = job["current_market_composite_id"]
        if not cid:
            continue
        comp = db["composites"][cid]
        if comp["status"] == "PUBLISHED" and comp["strategy_policy_id"] != strategy["id"]:
            if job["id"] not in exclude:
                raise ApiError("ERR_MIXED_STRATEGY_SOURCES", 409,
                               "Report mixes composites from different strategy policies")
    report["snapshot_payload"] = build_market_position_snapshot(report, exclude)
    report["status"] = "FINALIZED"
    touch(report)
    return ok(pub(report))


@bp.route("/reports/<rid>/present", methods=["POST"])
@require_roles("HRDirector")
def present_report(rid):
    report = get_or_404("reports", rid)
    if report["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot present a report in status {report['status']}")
    report["status"] = "PRESENTED"
    report["presented_at"] = iso()
    touch(report)
    emit_audit(report["org_id"], actor_employee_id(), "REPORT_PRESENT",
               "CompensationReport", report["id"], {"status": "PRESENTED"})
    return ok(pub(report))


# ---------------------------------------------------------------------------
# Audit events (read-only)
# ---------------------------------------------------------------------------
@bp.route("/audit_events/<aid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_audit_event(aid):
    return ok(pub(get_or_404("audit_events", aid)))


@bp.route("/audit_events", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_audit_events():
    return ok_list(filter_records("audit_events", {
        "org_id": request.args.get("org_id"),
        "target_entity": request.args.get("target_entity"),
        "target_id": request.args.get("target_id"),
        "actor_employee_id": request.args.get("actor_employee_id"),
    }))


@bp.route("/orgs/<oid>/audit_events", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_org_audit_events(oid):
    org = get_or_404("orgs", oid)
    return ok_list(filter_records("audit_events", {"org_id": org["id"]}))


# ---------------------------------------------------------------------------
# Logical clock (test-driving capability)
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("VendorAdmin")
def set_current_utc():
    b = body()
    raw = b.get("to_iso8601")
    dt = parse_iso8601(raw)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "to_iso8601 must be a valid ISO 8601 timestamp")
    set_clock(dt)
    return ok({"current_utc": iso()})
