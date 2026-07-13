"""Cross-entity queries, lazy expiry, and cascading state transitions."""
from store import store, new_entity, touch
from timeutil import add_days, add_years
from calc import (
    inspection_score, license_fee, violation_penalty,
    CURE_DAYS, NOTICE_ACK_DAYS, OPEN_VIOLATION_STATUSES, LEAD_YEAR,
)

# --------------------------------------------------------------------------
# Reverse-reachability queries
# --------------------------------------------------------------------------

def licenses_of_property(pid):
    return [l for l in store.licenses.values() if l["property_id"] == pid]


def violations_of_property(pid):
    return [v for v in store.violations.values() if v["property_id"] == pid]


def open_violations(pid):
    return [v for v in violations_of_property(pid) if v["status"] in OPEN_VIOLATION_STATUSES]


def open_critical_count(pid):
    return sum(1 for v in open_violations(pid) if v["severity"] == "CRITICAL")


def checklist_items_of(inspection_id):
    items = [c for c in store.checklist_items.values() if c["inspection_id"] == inspection_id]
    items.sort(key=lambda x: x["_seq"])
    return items


def escalation_index(pid):
    """CRITICAL violations with status IN {OPEN, REMEDIATION_SUBMITTED}."""
    return sum(
        1 for v in violations_of_property(pid)
        if v["severity"] == "CRITICAL" and v["status"] in ("OPEN", "REMEDIATION_SUBMITTED")
    )


# --------------------------------------------------------------------------
# Lazy expiry
# --------------------------------------------------------------------------

def refresh_license(lic):
    if lic["status"] == "ACTIVE" and lic.get("expires_at") and store.now() >= lic["expires_at"]:
        lic["status"] = "EXPIRED"
    return lic


def refresh_notice(n):
    if n["status"] == "SENT" and n.get("ack_deadline") and store.now() > n["ack_deadline"]:
        n["status"] = "EXPIRED"
    return n


# --------------------------------------------------------------------------
# Notice creation (manual + auto-generated)
# --------------------------------------------------------------------------

def create_notice(property_id, notice_type, recipient_email=None, recipient_unit=None):
    now = store.now()
    fields = {
        "property_id": property_id,
        "recipient_email": recipient_email,
        "recipient_unit": recipient_unit,
        "notice_type": notice_type,
        "status": "SENT",
        "sent_at": now,
        "ack_deadline": add_days(now, NOTICE_ACK_DAYS),
        "acknowledged_at": None,
    }
    return new_entity(store.notices, fields)


# --------------------------------------------------------------------------
# Property suspension / reinstatement / condemnation cascades
# --------------------------------------------------------------------------

def suspend_property(prop):
    if prop["registration_status"] != "REGISTERED":
        return
    prop["registration_status"] = "SUSPENDED"
    touch(prop)
    for lic in licenses_of_property(prop["id"]):
        if lic["status"] in ("ACTIVE", "EXPIRED"):
            lic["status"] = "SUSPENDED"
            touch(lic)


def reinstate_property(prop):
    prop["registration_status"] = "REGISTERED"
    touch(prop)
    for lic in licenses_of_property(prop["id"]):
        if lic["status"] == "SUSPENDED":
            lic["status"] = "ACTIVE"
            touch(lic)


def condemn_property(prop):
    # First hop: property -> CONDEMNED, generate condemnation notice.
    prop["registration_status"] = "CONDEMNED"
    touch(prop)
    create_notice(prop["id"], "CONDEMNATION_NOTICE")
    # Second hop: revoke non-terminal license(s).
    for lic in licenses_of_property(prop["id"]):
        if lic["status"] in ("ACTIVE", "EXPIRED", "SUSPENDED"):
            lic["status"] = "REVOKED"
            touch(lic)
    # Third hop: non-terminal violations -> CONDEMNED_BASIS.
    for v in violations_of_property(prop["id"]):
        if v["status"] in OPEN_VIOLATION_STATUSES:
            v["status"] = "CONDEMNED_BASIS"
            touch(v)


# --------------------------------------------------------------------------
# Inspection completion
# --------------------------------------------------------------------------

def complete_inspection(insp):
    items = checklist_items_of(insp["id"])
    score, passes = inspection_score(items, final=True)
    now = store.now()
    insp["conducted_at"] = now
    insp["result_score"] = score
    insp["status"] = "PASSED" if passes else "FAILED"
    touch(insp)

    itype = insp["inspection_type"]
    if passes:
        if itype == "COMPLAINT":
            _resolve_complaint(insp)
        if itype == "REINSPECTION":
            _reconcile_reinspection(insp, items)
    else:
        if itype in ("PERIODIC", "COMPLAINT"):
            _create_violations_and_cascade(insp, items)
        if itype == "REINSPECTION":
            _reconcile_reinspection(insp, items)
    return insp


def _resolve_complaint(insp):
    cid = insp.get("complaint_id")
    if not cid:
        return
    c = store.complaints.get(cid)
    if c and c["status"] == "INSPECTION_SCHEDULED":
        c["status"] = "RESOLVED"
        touch(c)


def _create_violations_and_cascade(insp, items):
    prop = store.properties[insp["property_id"]]
    created = []
    for it in items:
        if it["result"] == "FAIL":
            sev = it["severity"]
            fields = {
                "inspection_id": insp["id"],
                "property_id": prop["id"],
                "checklist_item_id": it["id"],
                "code": it["code"],
                "category": it["category"],
                "severity": sev,
                "status": "OPEN",
                "cure_deadline": add_days(insp["conducted_at"], CURE_DAYS[sev]),
                "remediation_notes": None,
            }
            created.append(new_entity(store.violations, fields))
    if any(v["severity"] == "CRITICAL" for v in created):
        suspend_property(prop)


def _reconcile_reinspection(insp, items):
    prior_id = insp.get("prior_inspection_id")
    if not prior_id:
        return
    prop = store.properties[insp["property_id"]]
    by_code = {}
    for it in items:  # already sorted by seq
        by_code.setdefault(it["code"], it)

    prior_viols = [
        v for v in store.violations.values()
        if v["inspection_id"] == prior_id and v["status"] in OPEN_VIOLATION_STATUSES
    ]
    for v in sorted(prior_viols, key=lambda x: x["_seq"]):
        it = by_code.get(v["code"])
        if it is None:
            continue
        if it["result"] == "PASS":
            v["status"] = "VERIFIED_RESOLVED"
            touch(v)
            if prop["registration_status"] == "SUSPENDED" and open_critical_count(prop["id"]) == 0:
                reinstate_property(prop)
        elif it["result"] == "FAIL":
            if v["status"] == "REMEDIATION_SUBMITTED":
                v["status"] = "OPEN"
                touch(v)


# --------------------------------------------------------------------------
# Property computed compliance fields
# --------------------------------------------------------------------------

def property_compliance(prop):
    pid = prop["id"]
    openv = open_violations(pid)
    crit = sum(1 for v in openv if v["severity"] == "CRITICAL")
    total = 0
    for v in sorted(openv, key=lambda x: x["_seq"]):
        total += violation_penalty(v, store.now())
    return {
        "has_lead_risk": prop["year_built"] < LEAD_YEAR,
        "open_violation_count": len(openv),
        "open_critical_violation_count": crit,
        "total_penalty_cents": total,
    }
