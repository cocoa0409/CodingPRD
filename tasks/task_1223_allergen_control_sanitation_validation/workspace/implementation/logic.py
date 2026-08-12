from db import CLOCK, db, new_entity, touch
from errors import ApiError
from util import parse_dt

OPEN_INCIDENT_STATUSES = ("OPEN", "INVESTIGATING", "CONTAINED")

SUSPENSION_THRESHOLD = 60
OVERDUE_PENALTY = 3
INITIAL_SCORE = 100
REINSTATE_SCORE_FLOOR = 75
SEVERITY_POINTS = {"MINOR": 2, "MAJOR": 5, "CRITICAL": 15}


def get_or_404(store, _id):
    ent = db[store].get(_id)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Resource not found: {_id}")
    return ent


def recompute_posture(line):
    lid = line["id"]
    critical_open = any(
        i["line_id"] == lid and i["severity"] == "CRITICAL"
        and i["status"] in OPEN_INCIDENT_STATUSES
        for i in db["incidents"].values())
    high_open = any(
        i["line_id"] == lid and i["severity"] == "HIGH"
        and i["status"] in OPEN_INCIDENT_STATUSES
        for i in db["incidents"].values())
    failed = any(c["line_id"] == lid and c["status"] == "FAILED"
                 for c in db["changeovers"].values())
    rework = any(c["line_id"] == lid and c["status"] == "REWORK_REQUIRED"
                 for c in db["changeovers"].values())
    # Pinned evaluation order: HOLD first, then RESTRICTED, then OPEN.
    if critical_open or failed:
        posture = "HOLD"
    elif high_open or rework:
        posture = "RESTRICTED"
    else:
        posture = "OPEN"
    line["posture"] = posture
    touch(line)


def recompute_training(tech):
    score = INITIAL_SCORE
    for f in db["findings"].values():
        if f["technician_id"] != tech["id"]:
            continue
        if f["status"] in ("OPEN", "OVERDUE", "RESOLVED"):
            score -= f["points_deducted"]
        # The overdue penalty, once incurred, is never refunded by resolution.
        if f.get("_overdue_penalty") and f["status"] in ("OVERDUE", "RESOLVED"):
            score -= OVERDUE_PENALTY
    score = max(0, min(100, score))
    tech["training_score"] = score
    if score < SUSPENSION_THRESHOLD and tech["status"] == "ACTIVE":
        tech["status"] = "SUSPENDED"
    touch(tech)


def compute_introduced(line_id, product, optimistic):
    statuses = {"COMPLETED", "IN_PROGRESS"}
    if optimistic:
        statuses.add("SCHEDULED")
    candidates = [r for r in db["runs"].values()
                  if r["line_id"] == line_id and r["status"] in statuses]
    candidates.sort(key=lambda r: (parse_dt(r["planned_start_utc"]), r["_seq"]))
    baseline = set()
    if candidates:
        last = candidates[-1]
        bp = db["products"].get(last["product_id"])
        if bp is not None:
            baseline = set(bp["allergen_set"])
    return sorted(set(product["allergen_set"]) - baseline)


def compute_changeover_needs(line, introduced_codes):
    if not introduced_codes:
        return False, 0
    code_map = {a["code"]: a for a in db["allergens"].values()}
    rel = []
    for code in introduced_codes:
        al = code_map.get(code)
        if al is None:
            continue
        for m in db["matrix"].values():
            if m["line_id"] == line["id"] and m["allergen_id"] == al["id"]:
                rel.append(m)
    if any(m["handling"] == "PROHIBITED" for m in rel):
        raise ApiError("ERR_ALLERGEN_PROHIBITED_ON_LINE", 422,
                       "An introduced allergen is PROHIBITED on this line")
    required = any(m["handling"] == "REQUIRES_CHANGEOVER" for m in rel)
    if not required and line["sanitation_class"] != "ALLERGEN_DEDICATED":
        required = True
    minutes = max([m["changeover_minutes"] for m in rel], default=0)
    return required, minutes


def covering_changeover(to_run_id, statuses):
    cands = [c for c in db["changeovers"].values()
             if c["to_run_id"] == to_run_id and c["status"] in statuses]
    if not cands:
        return None
    cands.sort(key=lambda c: c["_seq"])
    return cands[-1]


def intervals_overlap(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


def create_auto_incident(incident_type, severity, line_id=None, product_id=None,
                         allergen_id=None, source_label_reconciliation_id=None,
                         source_changeover_id=None, description="",
                         trigger_user_ids=None):
    ent = new_entity({
        "incident_type": incident_type,
        "severity": severity,
        "line_id": line_id,
        "product_id": product_id,
        "allergen_id": allergen_id,
        "source_label_reconciliation_id": source_label_reconciliation_id,
        "source_changeover_id": source_changeover_id,
        "description": description,
        "containment_action": None,
        "root_cause": None,
        "status": "OPEN",
        "_trigger_user_ids": list(trigger_user_ids or []),
    })
    db["incidents"][ent["id"]] = ent
    return ent


def compute_validation_score(changeover, procedure):
    score = 100
    actual = changeover["actual_minutes"]
    scheduled = changeover["scheduled_minutes"]
    if actual is not None:
        if actual <= scheduled:
            score += 5
        else:
            score -= min(20, (actual - scheduled) // 5)
    swabs = [s for s in db["swabs"].values()
             if s["changeover_id"] == changeover["id"]]
    margin = sum(1 for s in swabs if s["outcome"] == "PASS"
                 and float(s["measured_value"]) <= 0.5 * float(s["action_level_used"]))
    score += min(10, margin)
    score -= 2 * sum(1 for s in swabs if s["outcome"] == "INVALIDATED")
    return max(0, min(100, int(score)))


def converge_changeover(changeover):
    """Auto-transition a SWAB_PENDING changeover based on its swab book."""
    swabs = [s for s in db["swabs"].values()
             if s["changeover_id"] == changeover["id"]]
    fails = [s for s in swabs if s["outcome"] == "FAIL"]
    line = db["lines"].get(changeover["line_id"])
    if len(fails) >= 2:
        changeover["status"] = "FAILED"
        touch(changeover)
        trigger_ids = []
        for s in fails:
            if s["recorded_by_id"] not in trigger_ids:
                trigger_ids.append(s["recorded_by_id"])
        create_auto_incident(
            "SWAB_FAILURE_CLUSTER", "HIGH",
            line_id=changeover["line_id"],
            source_changeover_id=changeover["id"],
            description=f"Swab failure cluster on changeover {changeover['id']}",
            trigger_user_ids=trigger_ids)
        if line is not None:
            recompute_posture(line)
        return
    if len(fails) == 1:
        changeover["status"] = "REWORK_REQUIRED"
        touch(changeover)
        if line is not None:
            recompute_posture(line)
        return
    procedure = db["procedures"].get(changeover["procedure_id"])
    pass_zones = {s["zone_code"] for s in swabs if s["outcome"] == "PASS"}
    if procedure is not None and len(pass_zones) >= procedure["min_swab_zones"]:
        changeover["status"] = "VALIDATED"
        changeover["validation_score"] = compute_validation_score(changeover, procedure)
        touch(changeover)
        if line is not None:
            line["last_validated_changeover_id"] = changeover["id"]
            recompute_posture(line)
