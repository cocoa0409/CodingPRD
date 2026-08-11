"""Routes: SelfDisclosureDecision, RemediationAction, PatternAlert, clock."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g, request

import db
import errors
import resp
import services as svc
import validate as v
from transitions import need_rationale, parse_to_status, require_actor
from util import parse_dt

bp = Blueprint("disposition", __name__)


# ---------------------------------------------------------------------------
# SelfDisclosureDecision
# ---------------------------------------------------------------------------
@bp.post("/api/cases/<rid>/self-disclosure-decisions")
def create_disclosure(rid):
    case = svc.get_or_404(db.cases, rid, "Case")
    p = v.payload()
    regulator = v.need_enum(p, "regulator", svc.REGULATORS)
    decision_deadline = v.need_dt(p, "decision_deadline")
    expected = v.occ_version(p)

    # OCC (priority 5) precedes state checks (priority 6)
    if expected != case["version"]:
        errors.stale_version()

    if case["status"] not in ("FINDINGS", "DISPOSITION"):
        errors.invalid_state(
            "Disclosure decisions may be opened only while the case is FINDINGS or DISPOSITION"
        )

    for d in db.disclosures.values():
        if (
            d["case_id"] == case["id"]
            and d["regulator"] == regulator
            and d["status"] == "PENDING"
        ):
            d["status"] = "SUPERSEDED"
            svc.touch(d)

    decision = svc.new_row(
        {
            "case_id": case["id"],
            "regulator": regulator,
            "decision_deadline": decision_deadline,
            "decision": None,
            "rationale": None,
            "decided_by": None,
            "decided_at": None,
            "filed_at": None,
            "status": "PENDING",
        }
    )
    db.disclosures[decision["id"]] = decision
    svc.touch(case)
    svc.recompute_case_derived(case)
    return resp.ok(svc.dump(decision), status=201)


@bp.get("/api/self-disclosure-decisions")
def list_disclosures():
    q = request.args
    rows = list(db.disclosures.values())
    for param in ("case_id", "regulator", "status", "decision"):
        val = q.get(param)
        if val is not None:
            rows = [r for r in rows if r.get(param) == val]
    limit, offset = v.parse_pagination(q)
    rows = svc.sort_rows(rows)
    page, total = svc.paginate(rows, limit, offset)
    return resp.ok_list([svc.dump(r) for r in page], limit, offset, total)


@bp.get("/api/self-disclosure-decisions/<rid>")
def get_disclosure(rid):
    return resp.ok(svc.dump(svc.get_or_404(db.disclosures, rid, "SelfDisclosureDecision")))


DISCLOSURE_ACTORS = {
    "DECIDED": "ChiefLegalOfficer",
    "FILED": "GeneralCounsel",
    "OVERRIDDEN": "ChiefLegalOfficer",
}


@bp.post("/api/self-disclosure-decisions/<rid>/transition")
def transition_disclosure(rid):
    decision = svc.get_or_404(db.disclosures, rid, "SelfDisclosureDecision")
    p = v.payload()
    to = parse_to_status(p, svc.DISCLOSURE_STATUSES)
    require_actor(to, DISCLOSURE_ACTORS)

    src = decision["status"]
    case = svc.get_or_404(db.cases, decision["case_id"], "Case")
    now = db.clock_now()

    if src == "PENDING" and to == "DECIDED":
        dec = p.get("decision", None)
        if dec is None:
            errors.missing_field("decision")
        if dec not in ("DISCLOSE", "NO_DISCLOSE"):
            errors.validation("decision must be DISCLOSE or NO_DISCLOSE")
        rationale = v.opt_str(p, "rationale")
        decision["decision"] = dec
        if rationale is not None:
            decision["rationale"] = rationale
        decision["decided_by"] = g.user_id
        decision["decided_at"] = now
        decision["status"] = "DECIDED"
        svc.recompute_case_derived(case)
    elif src == "DECIDED" and to == "FILED":
        if decision["decision"] != "DISCLOSE":
            errors.business(
                "ERR_DECISION_NOT_DISCLOSE",
                "Only a DISCLOSE decision may be filed",
            )
        if now < decision["decided_at"] + timedelta(hours=72):
            errors.business(
                "ERR_COOLING_OFF",
                "A mandatory 72-hour cooling-off follows the decision",
            )
        decision["filed_at"] = now
        decision["status"] = "FILED"
    elif src == "DECIDED" and to == "OVERRIDDEN":
        if g.user_id == decision["decided_by"]:
            errors.business(
                "ERR_SOD_DISCLOSURE_OVERRIDE",
                "Overrider must differ from decided_by",
            )
        rationale = need_rationale(p)
        decision["rationale"] = rationale
        decision["status"] = "OVERRIDDEN"
    else:
        errors.invalid_state(f"SelfDisclosureDecision cannot transition {src} -> {to}")

    svc.touch(decision)
    return resp.ok(svc.dump(decision))


# ---------------------------------------------------------------------------
# RemediationAction
# ---------------------------------------------------------------------------
@bp.post("/api/cases/<rid>/remediation-actions")
def create_remediation(rid):
    case = svc.get_or_404(db.cases, rid, "Case")
    p = v.payload()
    action_type = v.need_enum(p, "action_type", svc.ACTION_TYPES)
    owner_ref = v.need_str(p, "owner_ref")
    description = v.need_str(p, "description")
    due_date = v.need_dt(p, "due_date")

    if case["status"] not in ("DISPOSITION", "REMEDIATION"):
        errors.invalid_state(
            "Remediation actions require the case in DISPOSITION or REMEDIATION"
        )

    action = svc.new_row(
        {
            "case_id": case["id"],
            "action_type": action_type,
            "owner_ref": owner_ref,
            "description": description,
            "due_date": due_date,
            "verified_by": None,
            "status": "OPEN",
        }
    )
    db.remediations[action["id"]] = action
    svc.recompute_case_derived(case)
    return resp.ok(svc.dump_remediation(action), status=201)


@bp.get("/api/remediation-actions")
def list_remediations():
    q = request.args
    rows = list(db.remediations.values())
    for param in ("case_id", "owner_ref", "status", "action_type"):
        val = q.get(param)
        if val is not None:
            rows = [r for r in rows if r.get(param) == val]
    limit, offset = v.parse_pagination(q)
    rows = svc.sort_rows(rows)
    page, total = svc.paginate(rows, limit, offset)
    return resp.ok_list([svc.dump_remediation(r) for r in page], limit, offset, total)


@bp.get("/api/remediation-actions/<rid>")
def get_remediation(rid):
    return resp.ok(
        svc.dump_remediation(svc.get_or_404(db.remediations, rid, "RemediationAction"))
    )


@bp.post("/api/remediation-actions/<rid>/transition")
def transition_remediation(rid):
    action = svc.get_or_404(db.remediations, rid, "RemediationAction")
    p = v.payload()
    to = parse_to_status(p, svc.REMEDIATION_STATUSES)

    src = action["status"]
    # per-transition actor depends on the from-state for IN_PROGRESS
    if to == "IN_PROGRESS":
        required = "HRBusinessPartner" if src == "OPEN" else "ComplianceAuditor"
        require_actor(to, {"IN_PROGRESS": required})
    else:
        require_actor(
            to,
            {
                "AWAITING_VERIFICATION": "HRBusinessPartner",
                "VERIFIED": "ComplianceAuditor",
                "WAIVED": "GeneralCounsel",
            },
        )

    case = svc.get_or_404(db.cases, action["case_id"], "Case")

    if src == "OPEN" and to == "IN_PROGRESS":
        action["status"] = "IN_PROGRESS"
    elif src == "IN_PROGRESS" and to == "AWAITING_VERIFICATION":
        action["status"] = "AWAITING_VERIFICATION"
    elif src == "AWAITING_VERIFICATION" and to == "VERIFIED":
        if g.user_id == action["owner_ref"]:
            errors.business(
                "ERR_SOD_REMEDIATION_VERIFICATION",
                "Verifier must differ from owner_ref",
            )
        action["verified_by"] = g.user_id
        action["status"] = "VERIFIED"
    elif src == "AWAITING_VERIFICATION" and to == "IN_PROGRESS":
        need_rationale(p)
        action["status"] = "IN_PROGRESS"
    elif src in ("OPEN", "IN_PROGRESS") and to == "WAIVED":
        need_rationale(p)
        action["status"] = "WAIVED"
    else:
        errors.invalid_state(f"RemediationAction cannot transition {src} -> {to}")

    svc.touch(action)
    svc.recompute_case_derived(case)
    return resp.ok(svc.dump_remediation(action))


# ---------------------------------------------------------------------------
# PatternAlert
# ---------------------------------------------------------------------------
@bp.post("/api/pattern-alerts/scan")
def scan_pattern_alerts():
    p = v.payload()
    window_days = p.get("window_days", None)
    if window_days is None:
        window_days = request.args.get("window_days", None)
    if window_days is None:
        window_days = 90
    if isinstance(window_days, bool) or not isinstance(window_days, (int, float, str)):
        errors.validation("window_days must be a positive number")
    try:
        window_days = float(window_days)
    except (TypeError, ValueError):
        errors.validation("window_days must be a positive number")
    if window_days <= 0:
        errors.validation("window_days must be a positive number")

    window_end = db.clock_now()
    window_start = window_end - timedelta(days=window_days)

    candidates = [
        c
        for c in db.cases.values()
        if c["status"] != "DISMISSED" and window_start <= c["created_at"] <= window_end
    ]
    by_id = {c["id"]: c for c in candidates}

    # grouping key -> set of case ids
    groups = []  # (alert_type, alert_key, case_id_set)

    by_employee = {}
    for s in db.subjects.values():
        if s["case_id"] in by_id:
            by_employee.setdefault(s["employee_ref"], set()).add(s["case_id"])
    for emp, cids in by_employee.items():
        if len(cids) >= 2:
            groups.append(("REPEAT_SUBJECT", emp, cids))

    by_category = {}
    for c in candidates:
        by_category.setdefault(c["allegation_category"], set()).add(c["id"])
    for cat, cids in by_category.items():
        if len(cids) >= 3:
            groups.append(("CATEGORY_SPIKE", cat, cids))

    by_department = {}
    for c in candidates:
        dept = c.get("department")
        if dept:
            by_department.setdefault(dept, set()).add(c["id"])
    for dept, cids in by_department.items():
        if len(cids) >= 3:
            groups.append(("DEPARTMENT_CLUSTER", dept, cids))

    # RETALIATION_RISK: witness of an earlier-created case becomes a subject
    # of a later-created case within the window
    retaliation = {}
    sorted_cases = svc.sort_rows(candidates)
    subjects_by_case = {}
    for s in db.subjects.values():
        if s["case_id"] in by_id:
            subjects_by_case.setdefault(s["case_id"], set()).add(s["employee_ref"])
    witnesses_by_case = {}
    for i in db.interviews.values():
        if i["case_id"] in by_id:
            witnesses_by_case.setdefault(i["case_id"], set()).add(i["witness_ref"])
    for later in sorted_cases:
        later_subjects = subjects_by_case.get(later["id"], set())
        if not later_subjects:
            continue
        for earlier in sorted_cases:
            if earlier["id"] == later["id"]:
                continue
            if (earlier["created_at"], earlier["_seq"]) >= (
                later["created_at"],
                later["_seq"],
            ):
                continue
            for w in witnesses_by_case.get(earlier["id"], set()):
                if w in later_subjects:
                    entry = retaliation.setdefault(w, set())
                    entry.add(earlier["id"])
                    entry.add(later["id"])
    for ref, cids in retaliation.items():
        if len(cids) >= 2:
            groups.append(("RETALIATION_RISK", ref, cids))

    produced = []
    for alert_type, alert_key, cids in groups:
        existing = None
        for a in db.alerts.values():
            if (
                a["alert_type"] == alert_type
                and a["alert_key"] == alert_key
                and a["window_start"] == window_start
                and a["status"] in ("OPEN", "ACKNOWLEDGED")
            ):
                existing = a
                break
        if existing is not None:
            produced.append(existing)
            continue
        case_rows = sorted(
            (by_id[cid] for cid in cids), key=lambda r: (r["created_at"], r["_seq"])
        )
        score, tier = svc.pattern_risk(case_rows, window_end)
        alert = svc.new_row(
            {
                "alert_type": alert_type,
                "alert_key": alert_key,
                "window_start": window_start,
                "window_end": window_end,
                "case_ids": [c["id"] for c in case_rows],
                "pattern_risk_score": score,
                "risk_tier": tier,
                "status": "OPEN",
            }
        )
        db.alerts[alert["id"]] = alert
        produced.append(alert)

    produced = svc.sort_rows(produced)
    items = [svc.dump(a) for a in produced]
    return resp.ok_list(items, len(items), 0, len(items))


@bp.get("/api/pattern-alerts")
def list_alerts():
    q = request.args
    rows = list(db.alerts.values())
    for param in ("alert_type", "alert_key", "status"):
        val = q.get(param)
        if val is not None:
            rows = [r for r in rows if r.get(param) == val]
    limit, offset = v.parse_pagination(q)
    rows = svc.sort_rows(rows)
    page, total = svc.paginate(rows, limit, offset)
    return resp.ok_list([svc.dump(r) for r in page], limit, offset, total)


@bp.get("/api/pattern-alerts/<rid>")
def get_alert(rid):
    return resp.ok(svc.dump(svc.get_or_404(db.alerts, rid, "PatternAlert")))


@bp.post("/api/pattern-alerts/<rid>/transition")
def transition_alert(rid):
    alert = svc.get_or_404(db.alerts, rid, "PatternAlert")
    p = v.payload()
    to = parse_to_status(p, svc.ALERT_STATUSES)
    src = alert["status"]

    if src == "OPEN" and to == "ACKNOWLEDGED":
        alert["status"] = "ACKNOWLEDGED"
    elif src == "ACKNOWLEDGED" and to == "ESCALATED":
        alert["status"] = "ESCALATED"
    elif src in ("OPEN", "ACKNOWLEDGED") and to == "DISMISSED":
        need_rationale(p)
        alert["status"] = "DISMISSED"
    else:
        errors.invalid_state(f"PatternAlert cannot transition {src} -> {to}")

    svc.touch(alert)
    # every alert transition recomputes pattern_escalated (and hence priority)
    # for every case it names
    for cid in alert["case_ids"]:
        case = db.cases.get(cid)
        if case is not None:
            svc.recompute_pattern_escalated(case)
    return resp.ok(svc.dump(alert))


# ---------------------------------------------------------------------------
# test-driving logical clock
# ---------------------------------------------------------------------------
@bp.post("/api/_clock/set_current_utc")
def set_clock():
    p = v.payload()
    raw = p.get("to_iso8601", None)
    if raw is None:
        errors.missing_field("to_iso8601")
    dt = parse_dt(raw)
    if dt is None:
        errors.validation("to_iso8601 must be an ISO8601 datetime")
    db.clock_set(dt)
    return resp.ok({"current_utc": svc.fmt_dt(db.clock_now())})
