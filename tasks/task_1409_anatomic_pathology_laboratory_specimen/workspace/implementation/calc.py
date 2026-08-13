"""Computed fields, calculations, cascading side effects, and serializers.

All numeric discipline follows PRD 2.7: per-event round-half-up for tissue,
1-decimal complexity score, whole-minute truncation for durations, 4-decimal
round-half-up discrepancy rates.
"""
import uuid
from datetime import timedelta
from decimal import Decimal

from db import db
from helpers import now, ts, ts3, round1, round4

# --- constants (SCAFFOLD calculations table) --------------------------------
SPECIMEN_BASE = {"BIOPSY": 1, "EXCISION": 2, "RESECTION": 3, "CYTOLOGY": 0}
TAT_HOURS = {"SIMPLE": 48, "MODERATE": 72, "COMPLEX": 120, "HIGH_COMPLEXITY": 168}
CLASS_WEIGHT = {"SIMPLE": 1, "MODERATE": 2, "COMPLEX": 3, "HIGH_COMPLEXITY": 5}
SEVERITY_WEIGHT = {"LEVEL_1": 1, "LEVEL_2": 3, "LEVEL_3": 5}
CONSULT_WEIGHT = 2
RETENTION_DAYS = {"BIOPSY": 14, "EXCISION": 14, "RESECTION": 14, "CYTOLOGY": 14}
COLD_ISCHEMIA_LIMITS = {"HER2_IHC": 60, "PD_L1": 90}
MIN_RECUTABLE_PCT = Decimal("5.0")
MAX_REFLEX_CHAIN_DEPTH = 3
OPEN_CASE_STATUSES = {"OPEN", "WORKUP", "PENDING_SIGNOUT", "AMENDING"}

SUBSPECIALTIES = {"DERMATOPATH", "GI", "BREAST", "HEME", "GU", "GYN", "NEURO", "GENERAL"}
SPECIMEN_TYPES = {"BIOPSY", "EXCISION", "RESECTION", "CYTOLOGY"}
FIXATIVE_TYPES = {"FORMALIN", "SALINE", "FROZEN", "NONE"}
STAIN_TYPES = {"HER2_IHC", "PD_L1", "KI67", "PAX5", "CD20", "MUCIN", "GRAM", "GMS"}
SLIDE_STAIN_TYPES = {"H_E"}
RESULT_VALUES = {"POSITIVE", "NEGATIVE", "EQUIVOCAL"}
CONCORDANCES = {"CONCORDANT", "MINOR_DISCORDANT", "MAJOR_DISCORDANT"}
SEVERITIES = {"LEVEL_1", "LEVEL_2", "LEVEL_3"}
WINDOW_TYPES = {"CONSULT_SERVICE", "UNAVAILABLE"}
TAT_MODES = {"CALENDAR", "BUSINESS_HOURS"}

# ---------------------------------------------------------------------------
# generic entity plumbing
# ---------------------------------------------------------------------------

def new_entity():
    t = now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": db.next_seq(),
    }


def bump(entity):
    """Every mutation (direct or cascade) refreshes updated_at and version."""
    entity["updated_at"] = now()
    entity["version"] += 1

# ---------------------------------------------------------------------------
# graph traversal
# ---------------------------------------------------------------------------

def case_specimens(case_id):
    return [s for s in db.specimens.values() if s["case_id"] == case_id]


def specimen_blocks(specimen_id):
    return [b for b in db.blocks.values() if b["specimen_id"] == specimen_id]


def block_slides(block_id):
    return [s for s in db.slides.values() if s["block_id"] == block_id]


def case_blocks(case_id):
    return [b for b in db.blocks.values()
            if db.specimens[b["specimen_id"]]["case_id"] == case_id]


def case_slides(case_id):
    out = []
    for s in db.slides.values():
        blk = db.blocks[s["block_id"]]
        if db.specimens[blk["specimen_id"]]["case_id"] == case_id:
            out.append(s)
    return out


def case_stain_orders(case_id):
    return [o for o in db.stain_orders.values() if o["case_id"] == case_id]


def case_consultations(case_id):
    return [c for c in db.consultations.values() if c["case_id"] == case_id]


def case_discrepancies(case_id):
    return [d for d in db.discrepancies.values() if d["case_id"] == case_id]


def case_reports(case_id):
    return [r for r in db.reports.values() if r["case_id"] == case_id]


def case_of_block(block):
    return db.cases[db.specimens[block["specimen_id"]]["case_id"]]


def case_of_slide(slide):
    return case_of_block(db.blocks[slide["block_id"]])

# ---------------------------------------------------------------------------
# case complexity + turnaround
# ---------------------------------------------------------------------------

def complexity_score(case):
    specs = [s for s in case_specimens(case["id"]) if s["status"] != "REJECTED"]
    base = max([SPECIMEN_BASE[s["specimen_type"]] for s in specs], default=0)
    n_blocks = len(case_blocks(case["id"]))  # any status, DEPLETED included
    n_slides = len([s for s in case_slides(case["id"]) if s["status"] != "CANCELLED"])
    n_stains = len([o for o in case_stain_orders(case["id"])
                    if o["status"] in ("ORDERED", "IN_PROGRESS", "RESULTED")])
    score = (Decimal(base) + Decimal(n_blocks)
             + Decimal("0.5") * n_slides + Decimal(2) * n_stains)
    return round1(score)


def complexity_class(score):
    if score < Decimal("4.0"):
        return "SIMPLE"
    if score < Decimal("10.0"):
        return "MODERATE"
    if score < Decimal("20.0"):
        return "COMPLEX"
    return "HIGH_COMPLEXITY"


def tat_base_time(case):
    """Earliest received_datetime over non-REJECTED specimens; case
    created_at when no such specimen exists."""
    specs = [s for s in case_specimens(case["id"]) if s["status"] != "REJECTED"]
    if not specs:
        return case["created_at"]
    return min(s["received_datetime"] for s in specs)


def _advance_into_business_window(t):
    """Mon-Fri 08:00-17:00 UTC. Before 08:00 -> same day 08:00; at/after
    17:00 or Sat/Sun -> next business day 08:00."""
    t = t.replace(microsecond=0)
    day_start = t.replace(hour=8, minute=0, second=0)
    day_end = t.replace(hour=17, minute=0, second=0)
    if t.weekday() < 5 and day_start <= t < day_end:
        return t
    if t.weekday() < 5 and t < day_start:
        return day_start
    # at/after 17:00, or Saturday/Sunday -> next business day 08:00
    d = (t + timedelta(days=1)).replace(hour=8, minute=0, second=0)
    while d.weekday() >= 5:
        d = d + timedelta(days=1)
    return d


def add_business_hours(base, hours):
    t = _advance_into_business_window(base)
    remaining = timedelta(hours=hours)
    while True:
        day_end = t.replace(hour=17, minute=0, second=0, microsecond=0)
        avail = day_end - t
        if remaining <= avail:
            return (t + remaining).replace(microsecond=0)
        remaining -= avail
        t = (t + timedelta(days=1)).replace(hour=8, minute=0, second=0,
                                            microsecond=0)
        while t.weekday() >= 5:
            t = t + timedelta(days=1)


def turnaround_deadline(case):
    base = tat_base_time(case)
    hours = TAT_HOURS[complexity_class(complexity_score(case))]
    if case["tat_mode"] == "BUSINESS_HOURS":
        return add_business_hours(base, hours)
    return base + timedelta(hours=hours)


def breach_state(case):
    """tat_breached / breach_minutes against finalized_at (FINAL/AMENDING)
    or the current logical clock otherwise. Strictly-greater comparison."""
    deadline = turnaround_deadline(case)
    ref = case["finalized_at"] if case["status"] in ("FINAL", "AMENDING") else now()
    breached = ref > deadline
    minutes = 0
    if breached:
        minutes = int((ref - deadline).total_seconds() // 60)
    return breached, minutes


def current_signed_report(case):
    for r in case_reports(case["id"]):
        if r["status"] == "SIGNED":
            return r
    return None


def open_critical_discrepancy_count(case):
    return len([d for d in case_discrepancies(case["id"])
                if d["severity"] == "LEVEL_3"
                and d["status"] in ("OPEN", "ACKNOWLEDGED")])

# ---------------------------------------------------------------------------
# pathologist workload + discrepancy rates
# ---------------------------------------------------------------------------

def workload_score(pathologist_id):
    total = Decimal(0)
    for c in db.cases.values():
        if c["assigned_pathologist_id"] == pathologist_id \
                and c["status"] in OPEN_CASE_STATUSES:
            total += Decimal(CLASS_WEIGHT[complexity_class(complexity_score(c))])
    n_consult = len([q for q in db.consultations.values()
                     if q["consultant_pathologist_id"] == pathologist_id
                     and q["status"] == "ACCEPTED"])
    total += Decimal(CONSULT_WEIGHT) * n_consult
    return round1(total)


def discrepancy_rates(pathologist_id):
    """Trailing 365-day inclusive window on the logical clock."""
    end = now()
    start = end - timedelta(days=365)
    denom = len([r for r in db.reports.values()
                 if r["report_class"] == "FINAL"
                 and r["signed_by_pathologist_id"] == pathologist_id
                 and r["signed_at"] is not None
                 and start <= r["signed_at"] <= end])
    rows = [d for d in db.discrepancies.values()
            if d["attributed_pathologist_id"] == pathologist_id
            and d["status"] == "RESOLVED"
            and d["resolved_at"] is not None
            and start <= d["resolved_at"] <= end]
    if denom == 0:
        return 0.0, 0.0
    simple = round4(Decimal(len(rows)) / Decimal(denom))
    weighted = round4(Decimal(sum(SEVERITY_WEIGHT[d["severity"]] for d in rows))
                      / Decimal(denom))
    return float(simple), float(weighted)

# ---------------------------------------------------------------------------
# pathologist eligibility / selector
# ---------------------------------------------------------------------------

def in_unavailable_window(pathologist_id, moment):
    """True when an ACTIVE UNAVAILABLE window of the pathologist contains
    the moment under CLOSED containment (start_at <= now <= end_at)."""
    for w in db.coverage_windows.values():
        if w["pathologist_id"] == pathologist_id \
                and w["status"] == "ACTIVE" \
                and w["window_type"] == "UNAVAILABLE" \
                and w["start_at"] <= moment <= w["end_at"]:
            return True
    return False


def is_eligible(pathologist, subspecialty):
    if not pathologist["active"]:
        return False
    if subspecialty not in pathologist["subspecialties"]:
        return False
    if in_unavailable_window(pathologist["id"], now()):
        return False
    return True


def select_pathologist(subspecialty):
    """Deterministic selector: workload ASC, last_assigned_at ASC nulls
    first, then created_at ASC (insertion order breaks same-second ties)."""
    pool = [p for p in db.pathologists.values() if is_eligible(p, subspecialty)]
    if not pool:
        return None

    def key(p):
        last = p["last_assigned_at"]
        return (workload_score(p["id"]),
                0 if last is None else 1,
                last if last is not None else now(),
                p["created_at"],
                p["_seq"])

    pool.sort(key=key)
    return pool[0]

# ---------------------------------------------------------------------------
# cascading transitions
# ---------------------------------------------------------------------------

def cancel_case(case):
    """OPEN/WORKUP -> CANCELLED with the child cascade (PRD 3.6)."""
    from_status = case["status"]
    case["status"] = "CANCELLED"
    bump(case)
    for o in case_stain_orders(case["id"]):
        if o["status"] in ("ORDERED", "IN_PROGRESS"):
            o["status"] = "CANCELLED"
            bump(o)
    for q in case_consultations(case["id"]):
        if q["status"] in ("REQUESTED", "ACCEPTED", "ANSWERED"):
            q["status"] = "CANCELLED"
            bump(q)
    if from_status == "WORKUP":
        for s in case_slides(case["id"]):
            if s["status"] in ("ORDERED", "SECTIONED", "STAINED", "QC_FAILED"):
                s["status"] = "CANCELLED"
                bump(s)


def finalize_case(case, caller_id, diagnosis_text):
    """PENDING_SIGNOUT -> FINAL: create the SIGNED FINAL report and run the
    atomic sign-out cascade (PRD 3.6). Returns the created Report."""
    t = now()
    report = new_entity()
    report.update({
        "case_id": case["id"],
        "report_class": "FINAL",
        "version_number": 1,
        "supersedes_report_id": None,
        "status": "SIGNED",
        "diagnosis_text": diagnosis_text,
        "amendment_reason": None,
        "signed_by_pathologist_id": caller_id,
        "signed_at": t,
    })
    db.reports[report["id"]] = report
    case["finalized_at"] = t
    case["status"] = "FINAL"
    bump(case)
    # cascade down: in-flight specimens complete with retention set
    for s in case_specimens(case["id"]):
        if s["status"] in ("GROSSING", "PROCESSING"):
            s["status"] = "COMPLETE"
            s["retention_until"] = t + timedelta(
                days=RETENTION_DAYS[s["specimen_type"]])
            bump(s)
    # conditional cascade: open stain orders cancelled
    for o in case_stain_orders(case["id"]):
        if o["status"] in ("ORDERED", "IN_PROGRESS"):
            o["status"] = "CANCELLED"
            bump(o)
    return report


def reflex_evaluate(resulted_order):
    """Fire matching ACTIVE reflex rules (priority ASC, created_at ASC),
    at most once per case per rule, guarded by ancestry chain depth."""
    candidates = [r for r in db.reflex_rules.values()
                  if r["active"]
                  and r["trigger_stain_type"] == resulted_order["stain_type"]
                  and r["trigger_result"] == resulted_order["result_value"]]
    candidates.sort(key=lambda r: (r["priority"], r["created_at"], r["_seq"]))
    # ancestry depth of the resulted order (manual root = 0)
    depth = 0
    cur = resulted_order
    while cur["parent_stain_order_id"] is not None:
        depth += 1
        cur = db.stain_orders[cur["parent_stain_order_id"]]
    if depth >= MAX_REFLEX_CHAIN_DEPTH:
        return
    case_orders = case_stain_orders(resulted_order["case_id"])
    for rule in candidates:
        # fires at most once per case per rule
        if any(o["reflex_rule_id"] == rule["id"] for o in case_orders):
            continue
        child = new_entity()
        child.update({
            "case_id": resulted_order["case_id"],
            "block_id": resulted_order["block_id"],
            "stain_type": rule["followup_stain_type"],
            "ordered_by_pathologist_id": None,
            "reflex_rule_id": rule["id"],
            "parent_stain_order_id": resulted_order["id"],
            "status": "ORDERED",
            "result_value": None,
            "resulted_at": None,
        })
        db.stain_orders[child["id"]] = child
        case_orders.append(child)


def run_clock_sweep():
    """Setting the logical clock expires REQUESTED consultations past due
    and marks SHIPPED release requests past due_back_at as OVERDUE. Both
    comparisons are strict; equality does not trigger."""
    t = now()
    for q in db.consultations.values():
        if q["status"] == "REQUESTED" and q["due_at"] < t:
            q["status"] = "EXPIRED"
            bump(q)
    for r in db.release_requests.values():
        if r["status"] == "SHIPPED" and r["due_back_at"] < t:
            r["status"] = "OVERDUE"
            bump(r)


def material_on_loan(material_type, material_id):
    """true iff a ReleaseRequest references the material with status in
    {SHIPPED, OVERDUE}."""
    key = "block_id" if material_type == "BLOCK" else "slide_id"
    for r in db.release_requests.values():
        if r.get(key) == material_id and r["status"] in ("SHIPPED", "OVERDUE"):
            return True
    return False

# ---------------------------------------------------------------------------
# serializers (computed fields resolved on read)
# ---------------------------------------------------------------------------

def ser_patient(p):
    return {
        "id": p["id"], "mrn": p["mrn"], "full_name": p["full_name"],
        "date_of_birth": p["date_of_birth"],
        "created_at": ts3(p["created_at"]), "updated_at": ts3(p["updated_at"]),
        "version": p["version"],
    }


def ser_pathologist(p):
    simple, weighted = discrepancy_rates(p["id"])
    return {
        "id": p["id"], "full_name": p["full_name"],
        "subspecialties": list(p["subspecialties"]), "active": p["active"],
        "workload_score": float(workload_score(p["id"])),
        "discrepancy_rate_simple": simple,
        "discrepancy_rate_weighted": weighted,
        "last_assigned_at": ts(p["last_assigned_at"]),
        "created_at": ts3(p["created_at"]), "updated_at": ts3(p["updated_at"]),
        "version": p["version"],
    }


def ser_coverage_window(w):
    return {
        "id": w["id"], "pathologist_id": w["pathologist_id"],
        "window_type": w["window_type"],
        "start_at": ts(w["start_at"]), "end_at": ts(w["end_at"]),
        "status": w["status"],
        "created_at": ts3(w["created_at"]), "updated_at": ts3(w["updated_at"]),
        "version": w["version"],
    }


def ser_case(c):
    score = complexity_score(c)
    breached, minutes = breach_state(c)
    signed = current_signed_report(c)
    return {
        "id": c["id"], "patient_id": c["patient_id"],
        "subspecialty": c["subspecialty"], "tat_mode": c["tat_mode"],
        "status": c["status"],
        "complexity_class": complexity_class(score),
        "complexity_score": float(score),
        "assigned_pathologist_id": c["assigned_pathologist_id"],
        "tat_base_time": ts(tat_base_time(c)),
        "turnaround_deadline": ts(turnaround_deadline(c)),
        "finalized_at": ts(c["finalized_at"]),
        "tat_breached": breached,
        "breach_minutes": minutes,
        "current_signed_report_id": signed["id"] if signed else None,
        "amender_pathologist_id": c["amender_pathologist_id"],
        "open_critical_discrepancy_count": open_critical_discrepancy_count(c),
        "created_at": ts3(c["created_at"]), "updated_at": ts3(c["updated_at"]),
        "version": c["version"],
    }


def ser_specimen(s):
    return {
        "id": s["id"], "case_id": s["case_id"],
        "accession_number": s["accession_number"],
        "specimen_type": s["specimen_type"],
        "anatomical_site": s["anatomical_site"],
        "collection_datetime": ts(s["collection_datetime"]),
        "received_datetime": ts(s["received_datetime"]),
        "container_count": s["container_count"],
        "fixative_type": s["fixative_type"],
        "cold_ischemia_minutes": s["cold_ischemia_minutes"],
        "status": s["status"],
        "gross_description": s["gross_description"],
        "retention_until": ts(s["retention_until"]),
        "wet_tissue_disposed_at": ts(s["wet_tissue_disposed_at"]),
        "reject_reason": s["reject_reason"],
        "created_at": ts3(s["created_at"]), "updated_at": ts3(s["updated_at"]),
        "version": s["version"],
    }


def ser_block(b):
    return {
        "id": b["id"], "specimen_id": b["specimen_id"],
        "block_label": b["block_label"], "status": b["status"],
        "tissue_remaining_pct": float(b["tissue_remaining_pct"]),
        "on_loan": material_on_loan("BLOCK", b["id"]),
        "created_at": ts3(b["created_at"]), "updated_at": ts3(b["updated_at"]),
        "version": b["version"],
    }


def ser_slide(s):
    return {
        "id": s["id"], "block_id": s["block_id"],
        "slide_label": s["slide_label"], "stain_type": s["stain_type"],
        "status": s["status"],
        "consumption_pct": float(s["consumption_pct"]),
        "qc_failure_reason": s["qc_failure_reason"],
        "on_loan": material_on_loan("SLIDE", s["id"]),
        "created_at": ts3(s["created_at"]), "updated_at": ts3(s["updated_at"]),
        "version": s["version"],
    }


def ser_stain_order(o):
    return {
        "id": o["id"], "case_id": o["case_id"], "block_id": o["block_id"],
        "stain_type": o["stain_type"],
        "ordered_by_pathologist_id": o["ordered_by_pathologist_id"],
        "reflex_rule_id": o["reflex_rule_id"],
        "parent_stain_order_id": o["parent_stain_order_id"],
        "status": o["status"], "result_value": o["result_value"],
        "resulted_at": ts(o["resulted_at"]),
        "created_at": ts3(o["created_at"]), "updated_at": ts3(o["updated_at"]),
        "version": o["version"],
    }


def ser_reflex_rule(r):
    return {
        "id": r["id"], "name": r["name"],
        "trigger_stain_type": r["trigger_stain_type"],
        "trigger_result": r["trigger_result"],
        "followup_stain_type": r["followup_stain_type"],
        "priority": r["priority"], "active": r["active"],
        "created_at": ts3(r["created_at"]), "updated_at": ts3(r["updated_at"]),
        "version": r["version"],
    }


def ser_report(r):
    return {
        "id": r["id"], "case_id": r["case_id"],
        "report_class": r["report_class"],
        "version_number": r["version_number"],
        "supersedes_report_id": r["supersedes_report_id"],
        "status": r["status"],
        "diagnosis_text": r["diagnosis_text"],
        "amendment_reason": r["amendment_reason"],
        "signed_by_pathologist_id": r["signed_by_pathologist_id"],
        "signed_at": ts(r["signed_at"]),
        "created_at": ts3(r["created_at"]), "updated_at": ts3(r["updated_at"]),
        "version": r["version"],
    }


def ser_consultation(q):
    return {
        "id": q["id"], "case_id": q["case_id"],
        "requesting_pathologist_id": q["requesting_pathologist_id"],
        "consultant_pathologist_id": q["consultant_pathologist_id"],
        "subspecialty": q["subspecialty"],
        "question_text": q["question_text"],
        "due_at": ts(q["due_at"]),
        "status": q["status"],
        "opinion_text": q["opinion_text"],
        "concordance": q["concordance"],
        "answered_at": ts(q["answered_at"]),
        "decline_reason": q["decline_reason"],
        "reroute_count": q["reroute_count"],
        "created_at": ts3(q["created_at"]), "updated_at": ts3(q["updated_at"]),
        "version": q["version"],
    }


def ser_discrepancy(d):
    return {
        "id": d["id"], "case_id": d["case_id"],
        "consultation_id": d["consultation_id"],
        "report_id": d["report_id"],
        "source": d["source"], "severity": d["severity"],
        "description": d["description"], "status": d["status"],
        "attributed_pathologist_id": d["attributed_pathologist_id"],
        "resolved_at": ts(d["resolved_at"]),
        "resolved_with_amendment": d["resolved_with_amendment"],
        "created_at": ts3(d["created_at"]), "updated_at": ts3(d["updated_at"]),
        "version": d["version"],
    }


def ser_release_request(r):
    return {
        "id": r["id"], "material_type": r["material_type"],
        "block_id": r["block_id"], "slide_id": r["slide_id"],
        "requesting_institution": r["requesting_institution"],
        "reason": r["reason"],
        "requested_out_at": ts(r["requested_out_at"]),
        "due_back_at": ts(r["due_back_at"]),
        "status": r["status"],
        "shipped_at": ts(r["shipped_at"]),
        "returned_at": ts(r["returned_at"]),
        "returned_late": r["returned_late"],
        "deny_reason": r["deny_reason"],
        "created_at": ts3(r["created_at"]), "updated_at": ts3(r["updated_at"]),
        "version": r["version"],
    }
