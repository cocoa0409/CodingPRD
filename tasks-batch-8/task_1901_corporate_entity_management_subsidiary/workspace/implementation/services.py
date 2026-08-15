"""Business logic: dates, calculations, lazy evaluation, posture, cascades.

All rules trace to PRD.md §3 and SCAFFOLD.yaml §1.2/§1.3.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

import store

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
TAX_BASE_CENTS = 17500
FREE_SHARES = 5000
SHARE_BLOCK_SIZE = 10000
PER_BLOCK_CENTS = 8500
TAX_CAP_CENTS = 2000000
NONPROFIT_FLAT_CENTS = 2500
DAILY_TAX_RATE = Decimal("0.00037")
DAILY_REPORT_RATE = Decimal("0.00041")
SUSPEND_AFTER_GRACE_DAYS = 30
CERT_VALID_DAYS = 90
EXPEDITED_MULTIPLIER = Decimal("1.5")

SINGLE_HOLDER_TITLES = {"PRESIDENT", "SECRETARY", "TREASURER"}
OFFICE_TITLES = {"PRESIDENT", "SECRETARY", "TREASURER", "CEO", "CFO", "DIRECTOR"}
GRANT_SCOPES = {"BANKING", "CONTRACTS", "TAX_FILINGS", "GOVERNMENT_FILINGS"}

AUTHORIZATION_TYPES = {"AUTHORIZE_FORMATION", "AUTHORIZE_DISSOLUTION", "REVOKE_DISSOLUTION"}
JURISDICTION_PAYLOAD_TYPES = {"AUTHORIZE_QUALIFICATION", "AUTHORIZE_WITHDRAWAL"}

FILING_OPEN_STATUSES = {"SCHEDULED", "PREPARED", "OVERDUE", "SUBMITTED", "REJECTED"}


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------
def parse_date(s):
    """Strict YYYY-MM-DD parse; returns date or None."""
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def is_valid_date(s):
    return parse_date(s) is not None


def fmt_date(d):
    return d.isoformat()


def add_days(d, n):
    return d + timedelta(days=n)


def is_leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------
def filings_of(entity_id):
    return [f for f in store.filings.values() if f["entity_id"] == entity_id]


def resolutions_of(entity_id):
    return [r for r in store.resolutions.values() if r["entity_id"] == entity_id]


def grants_of(entity_id):
    return [g for g in store.grants.values() if g["entity_id"] == entity_id]


def certs_of(entity_id):
    return [c for c in store.certificates.values() if c["entity_id"] == entity_id]


def quals_of(entity_id):
    return [q for q in store.qualifications.values() if q["entity_id"] == entity_id]


def agent_appts_of(entity_id):
    return [a for a in store.agent_appointments.values() if a["entity_id"] == entity_id]


def officer_appts_of(entity_id):
    return [a for a in store.officer_appointments.values() if a["entity_id"] == entity_id]


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Compliance events (PRD §3.14)
# ---------------------------------------------------------------------------
def append_event(entity_id, event_type, payload):
    ev = {
        "id": store.new_id(),
        "_seq": store.next_seq(),
        "created_at": store.now_iso(),
        "entity_id": entity_id,
        "event_type": event_type,
        "payload": payload or {},
        "occurred_at": store.now_iso(),
    }
    store.compliance_events[ev["id"]] = ev
    return ev


# ---------------------------------------------------------------------------
# Calculations (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def calc_due_date(jurisdiction, entity, period_year):
    """filing_due_date: rule-based date + weekend roll to Monday."""
    if jurisdiction["annual_report_due_rule"] == "FIXED_MONTH_DAY":
        due = date(period_year, jurisdiction["annual_report_due_month"],
                   jurisdiction["annual_report_due_day"])
    else:  # FORMATION_ANNIVERSARY
        f = parse_date(entity["formation_date"])
        month, day = f.month, f.day
        if month == 2 and day == 29 and not is_leap(period_year):
            day = 28
        due = date(period_year, month, day)
    while due.weekday() >= 5:  # Saturday/Sunday -> next Monday
        due += timedelta(days=1)
    return due


def calc_franchise_tax(entity_type, method, shares):
    """franchise_tax formula; shares per variant (ESTIMATED/ACTUAL)."""
    if entity_type == "NONPROFIT_CORPORATION":
        return NONPROFIT_FLAT_CENTS
    if method == "SHARES_TIERED":
        blocks = -(-max(0, shares - FREE_SHARES) // SHARE_BLOCK_SIZE)  # ceil
        return min(TAX_CAP_CENTS, TAX_BASE_CENTS + blocks * PER_BLOCK_CENTS)
    if method == "FLAT":
        return TAX_BASE_CENTS
    return 0  # NONE


def _round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calc_late_penalty(jurisdiction, due_date_str, submitted_date, tax_assessed, report_fee):
    """late_filing_penalty: days_late + penalty_cents with per-component rounding."""
    due = parse_date(due_date_str)
    grace_end = due + timedelta(days=jurisdiction["grace_period_days"])
    if submitted_date <= grace_end:
        return 0, 0
    if jurisdiction["penalty_day_counting"] == "BUSINESS_DAYS":
        days = 0
        d = grace_end + timedelta(days=1)
        while d <= submitted_date:
            if d.weekday() < 5:
                days += 1
            d += timedelta(days=1)
        days_late = days
    else:  # CALENDAR_DAYS
        days_late = (submitted_date - grace_end).days
    if days_late == 0:
        return 0, 0
    tax_component = _round_half_up_cents(
        Decimal(tax_assessed) * DAILY_TAX_RATE * days_late)
    report_component = _round_half_up_cents(
        Decimal(report_fee) * DAILY_REPORT_RATE * days_late)
    penalty = min(jurisdiction["late_penalty_cap_cents"],
                  jurisdiction["late_penalty_base_cents"] + tax_component + report_component)
    return days_late, penalty


def calc_cert_fee(jurisdiction, delivery_speed):
    if delivery_speed == "EXPEDITED":
        return _round_half_up_cents(Decimal(jurisdiction["cert_fee_cents"]) * EXPEDITED_MULTIPLIER)
    return jurisdiction["cert_fee_cents"]


# ---------------------------------------------------------------------------
# Posture derivation (SCAFFOLD §1.3 compliance_posture_derivation, PRD §3.13)
# ---------------------------------------------------------------------------
def _apply_overdue_eval(entity):
    """Flip SCHEDULED/PREPARED filings past due_date to OVERDUE (lazy path)."""
    changed = 0
    today = store.today()
    for f in filings_of(entity["id"]):
        if f["status"] in ("SCHEDULED", "PREPARED") and parse_date(f["due_date"]) < today:
            f["status"] = "OVERDUE"
            store.touch(f)
            append_event(entity["id"], "FILING_OVERDUE", {"filing_id": f["id"]})
            changed += 1
    return changed


def derive_posture(entity):
    """Returns (posture, suspended_since); applies lazy overdue eval first."""
    _apply_overdue_eval(entity)
    today = store.today()
    registered = set()
    if entity["status"] in ("ACTIVE", "DISSOLUTION_PENDING"):
        registered.add(entity["formation_jurisdiction_id"])
    for q in quals_of(entity["id"]):
        if q["status"] in ("PENDING", "QUALIFIED", "WITHDRAWAL_PENDING"):
            registered.add(q["jurisdiction_id"])
    coverage_lost = False
    for j in registered:
        covered = False
        for a in agent_appts_of(entity["id"]):
            if a["jurisdiction_id"] != j:
                continue
            if a["status"] not in ("ACTIVE", "NOTICE_PENDING"):
                continue
            if parse_date(a["start_date"]) > today:
                continue
            if a["status"] == "NOTICE_PENDING" and parse_date(a["effective_end_date"]) < today:
                continue
            covered = True
            break
        if not covered:
            coverage_lost = True
            break
    hard_overdue = False
    any_overdue = False
    for f in filings_of(entity["id"]):
        if f["status"] != "OVERDUE":
            continue
        any_overdue = True
        j = store.jurisdictions[f["jurisdiction_id"]]
        limit = parse_date(f["due_date"]) + timedelta(
            days=j["grace_period_days"] + SUSPEND_AFTER_GRACE_DAYS)
        if today > limit:
            hard_overdue = True
    suspended_since = entity.get("suspended_since")
    if isinstance(suspended_since, str):
        suspended_since = parse_date(suspended_since)
    if coverage_lost or hard_overdue:
        if suspended_since is None:
            suspended_since = today
        fj = store.jurisdictions[entity["formation_jurisdiction_id"]]
        if today >= suspended_since + timedelta(days=fj["forfeiture_window_days"]):
            return "FORFEITED", suspended_since
        return "SUSPENDED", suspended_since
    suspended_since = None
    if any_overdue:
        return "DELINQUENT", None
    return "GOOD_STANDING", None


def recompute_posture(entity, auto_deny=False, counters=None):
    """Persist derived posture; POSTURE_CHANGED event on change; optional cert auto-deny."""
    posture, suspended_since = derive_posture(entity)
    old = entity["compliance_posture"]
    changed = False
    if suspended_since is None:
        new_ss = None
    else:
        new_ss = fmt_date(suspended_since) if isinstance(suspended_since, date) else suspended_since
    if old != posture or entity.get("suspended_since") != new_ss:
        entity["compliance_posture"] = posture
        entity["suspended_since"] = new_ss
        entity["updated_at"] = store.now_iso()
        changed = True
    if old != posture:
        append_event(entity["id"], "POSTURE_CHANGED",
                     {"from_posture": old, "to_posture": posture})
        if counters is not None:
            counters["posture_changes"] += 1
    if auto_deny and posture != "GOOD_STANDING":
        for c in certs_of(entity["id"]):
            if c["status"] == "REQUESTED":
                c["status"] = "DENIED"
                c["denial_reason"] = "POSTURE_LOST"
                store.touch(c)
                append_event(entity["id"], "CERTIFICATE_DENIED",
                             {"certificate_id": c["id"]})
                if counters is not None:
                    counters["certificates_auto_denied"] += 1
    return changed


# ---------------------------------------------------------------------------
# Grant revocation cascade
# ---------------------------------------------------------------------------
def revoke_grant(grant, reason=None):
    """Revoke one ACTIVE/SUSPENDED grant and cascade to delegated grants."""
    if grant["status"] not in ("ACTIVE", "SUSPENDED"):
        return
    grant["status"] = "REVOKED"
    store.touch(grant)
    payload = {"grant_id": grant["id"]}
    if reason:
        payload["reason"] = reason
    append_event(grant["entity_id"], "GRANT_REVOKED", payload)
    for g in list(store.grants.values()):
        if g.get("delegated_from_grant_id") == grant["id"] and g["status"] in ("ACTIVE", "SUSPENDED"):
            revoke_grant(g)


def revoke_officer_grants(entity_id, officer_id):
    """Officer-exit grant cascade: that officer's grants at this entity, then delegated."""
    for g in list(store.grants.values()):
        if (g["entity_id"] == entity_id and g["officer_id"] == officer_id
                and g["status"] in ("ACTIVE", "SUSPENDED")):
            revoke_grant(g)


# ---------------------------------------------------------------------------
# Resolution EFFECTIVE materialization
# ---------------------------------------------------------------------------
def materialize_resolution(resolution, counters=None):
    """ADOPTED -> EFFECTIVE materialization. Returns 'effective' | 'blocked' | None."""
    if resolution["status"] != "ADOPTED":
        return None
    if parse_date(resolution["effective_date"]) > store.today():
        return None
    entity = store.entities[resolution["entity_id"]]
    rtype = resolution["resolution_type"]
    payload = resolution.get("payload") or {}
    if rtype == "APPOINT_OFFICER":
        title = payload.get("office_title")
        if title in SINGLE_HOLDER_TITLES:
            occupied = any(
                a for a in officer_appts_of(entity["id"])
                if a["office_title"] == title and a["status"] == "APPOINTED")
            if occupied:
                if not resolution.get("_effective_blocked"):
                    resolution["_effective_blocked"] = True
                    append_event(entity["id"], "RESOLUTION_EFFECTIVE_BLOCKED",
                                 {"resolution_id": resolution["id"]})
                if counters is not None:
                    counters["resolutions_blocked"] += 1
                return "blocked"
        appt = store.new_record()
        appt.update({
            "entity_id": entity["id"],
            "officer_id": payload.get("officer_id"),
            "resolution_id": resolution["id"],
            "office_title": title,
            "start_date": payload.get("start_date"),
            "end_date": None,
            "status": "APPOINTED",
        })
        store.officer_appointments[appt["id"]] = appt
    elif rtype in ("REMOVE_OFFICER", "ACCEPT_RESIGNATION"):
        appt = store.officer_appointments.get(payload.get("appointment_id"))
        if appt is not None and appt["status"] == "APPOINTED":
            appt["status"] = "REMOVED" if rtype == "REMOVE_OFFICER" else "RESIGNED"
            appt["end_date"] = resolution["effective_date"]
            store.touch(appt)
            append_event(entity["id"],
                         "OFFICER_REMOVED" if rtype == "REMOVE_OFFICER" else "OFFICER_RESIGNED",
                         {"appointment_id": appt["id"]})
            revoke_officer_grants(entity["id"], appt["officer_id"])
    elif rtype == "REVOKE_SIGNATURE_AUTHORITY":
        grant = store.grants.get(payload.get("grant_id"))
        if grant is not None and grant["status"] in ("ACTIVE", "SUSPENDED"):
            revoke_grant(grant)
    # AUTHORIZE_* / REVOKE_DISSOLUTION / GRANT_SIGNATURE_AUTHORITY: no record mutation
    resolution["_effective_blocked"] = False
    resolution["status"] = "EFFECTIVE"
    store.touch(resolution)
    if counters is not None:
        counters["resolutions_made_effective"] += 1
    return "effective"


def apply_resolution_eval(resolution, counters=None):
    return materialize_resolution(resolution, counters)


# ---------------------------------------------------------------------------
# Grant / certificate lazy expiry
# ---------------------------------------------------------------------------
def apply_grant_expiry(grant, counters=None):
    if grant["status"] == "ACTIVE" and parse_date(grant["expiry_date"]) <= store.today():
        grant["status"] = "EXPIRED"
        store.touch(grant)
        append_event(grant["entity_id"], "GRANT_REVOKED",
                     {"grant_id": grant["id"], "reason": "EXPIRED"})
        if counters is not None:
            counters["grants_expired"] += 1
        return True
    return False


def apply_cert_expiry(cert, counters=None):
    if cert["status"] == "ISSUED" and store.today() > parse_date(cert["valid_until"]):
        cert["status"] = "EXPIRED"
        store.touch(cert)
        if counters is not None:
            counters["certificates_expired"] += 1
        return True
    return False


def lazy_eval_entity(entity, auto_deny=True):
    """Full lazy clock-driven evaluation for an entity graph (GET entity, mutations)."""
    for f in filings_of(entity["id"]):
        if f["status"] in ("SCHEDULED", "PREPARED") and parse_date(f["due_date"]) < store.today():
            f["status"] = "OVERDUE"
            store.touch(f)
            append_event(entity["id"], "FILING_OVERDUE", {"filing_id": f["id"]})
    for r in resolutions_of(entity["id"]):
        apply_resolution_eval(r)
    for g in grants_of(entity["id"]):
        apply_grant_expiry(g)
    for c in certs_of(entity["id"]):
        apply_cert_expiry(c)
    recompute_posture(entity, auto_deny=auto_deny)


# ---------------------------------------------------------------------------
# Filing generation (formation confirm, qualification confirm, rollover)
# ---------------------------------------------------------------------------
def _basis_snapshot(entity, jurisdiction_id):
    """ESTIMATED basis: latest prior ACCEPTED FRANCHISE_TAX shares_basis else authorized_shares."""
    accepted = [f for f in filings_of(entity["id"])
                if f["jurisdiction_id"] == jurisdiction_id
                and f["filing_type"] == "FRANCHISE_TAX" and f["status"] == "ACCEPTED"]
    if accepted:
        accepted.sort(key=lambda f: (f["period_year"], f.get("_seq", 0)))
        return accepted[-1]["shares_basis"]
    return entity["authorized_shares"]


def _create_filing(entity, jurisdiction, filing_type, period_year):
    rec = store.new_record()
    rec.update({
        "entity_id": entity["id"],
        "jurisdiction_id": jurisdiction["id"],
        "filing_type": filing_type,
        "period_year": period_year,
        "due_date": fmt_date(calc_due_date(jurisdiction, entity, period_year)),
        "report_fee_cents": jurisdiction["report_fee_cents"],
        "shares_basis": _basis_snapshot(entity, jurisdiction["id"]),
        "tax_estimated_cents": None,
        "tax_assessed_cents": None,
        "submitted_date": None,
        "submitted_by_user_id": None,
        "days_late": None,
        "penalty_cents": None,
        "fee_cents": None,
        "status": "SCHEDULED",
    })
    store.filings[rec["id"]] = rec
    return rec


def _filing_exists(entity_id, jurisdiction_id, filing_type, period_year):
    return any(f for f in store.filings.values()
               if f["entity_id"] == entity_id and f["jurisdiction_id"] == jurisdiction_id
               and f["filing_type"] == filing_type and f["period_year"] == period_year)


def generate_filings(entity, jurisdiction, period_year):
    created = []
    if not _filing_exists(entity["id"], jurisdiction["id"], "ANNUAL_REPORT", period_year):
        created.append(_create_filing(entity, jurisdiction, "ANNUAL_REPORT", period_year))
    if jurisdiction["franchise_tax_method"] != "NONE":
        if not _filing_exists(entity["id"], jurisdiction["id"], "FRANCHISE_TAX", period_year):
            created.append(_create_filing(entity, jurisdiction, "FRANCHISE_TAX", period_year))
    return created


def qualification_first_period(entity, jurisdiction):
    """period_year = year(formation)+1 if not already past, else the period
    containing the current logical date per filing_due_date."""
    p0 = parse_date(entity["formation_date"]).year + 1
    if calc_due_date(jurisdiction, entity, p0) >= store.today():
        return p0
    p = p0
    while calc_due_date(jurisdiction, entity, p) < store.today():
        p += 1
    return p


# ---------------------------------------------------------------------------
# Authorizing resolution lookup
# ---------------------------------------------------------------------------
def find_authorizing_resolution(entity_id, rtype, payload_match=None):
    """Earliest-created resolution of rtype with status ADOPTED/EFFECTIVE whose
    payload matches the given key/values."""
    matches = []
    for r in store.resolutions.values():
        if r["entity_id"] != entity_id or r["resolution_type"] != rtype:
            continue
        if r["status"] not in ("ADOPTED", "EFFECTIVE"):
            continue
        if payload_match:
            payload = r.get("payload") or {}
            if any(payload.get(k) != v for k, v in payload_match.items()):
                continue
        matches.append(r)
    if not matches:
        return None
    matches.sort(key=lambda r: r.get("_seq", 0))
    return matches[0]


# ---------------------------------------------------------------------------
# System sweep (PRD §3.15)
# ---------------------------------------------------------------------------
def run_sweep():
    counters = {
        "filings_marked_overdue": 0,
        "resolutions_made_effective": 0,
        "resolutions_blocked": 0,
        "grants_expired": 0,
        "certificates_expired": 0,
        "certificates_auto_denied": 0,
        "posture_changes": 0,
    }
    today = store.today()
    for entity in list(store.entities.values()):
        for f in filings_of(entity["id"]):
            if f["status"] in ("SCHEDULED", "PREPARED") and parse_date(f["due_date"]) < today:
                f["status"] = "OVERDUE"
                store.touch(f)
                append_event(entity["id"], "FILING_OVERDUE", {"filing_id": f["id"]})
                counters["filings_marked_overdue"] += 1
    for r in list(store.resolutions.values()):
        apply_resolution_eval(r, counters)
    for g in list(store.grants.values()):
        apply_grant_expiry(g, counters)
    for entity in list(store.entities.values()):
        recompute_posture(entity, auto_deny=True, counters=counters)
    for c in list(store.certificates.values()):
        apply_cert_expiry(c, counters)
    return counters


# ---------------------------------------------------------------------------
# Ownership chart (SCAFFOLD §1.3 ownership_consolidation, PRD §3.11)
# ---------------------------------------------------------------------------
def _covering_active_edges(today=None):
    today = today or store.today()
    edges = []
    for r in store.ownership_records.values():
        if r["status"] != "ACTIVE":
            continue
        if parse_date(r["effective_date"]) > today:
            continue
        if r["end_date"] is not None and today >= parse_date(r["end_date"]):
            continue
        edges.append(r)
    return edges


def ownership_chart(root_id):
    today = store.today()
    edges = _covering_active_edges(today)
    out_edges = {}
    for e in edges:
        out_edges.setdefault(e["parent_entity_id"], []).append(e)
    for lst in out_edges.values():
        lst.sort(key=lambda e: (e["effective_date"], e["created_at"], e.get("_seq", 0)))

    nodes = []
    node_info = {}  # entity_id -> {depth, look_through}
    emitted_edges = []
    emitted_edge_ids = set()
    root_entry = {"entity_id": root_id, "depth": 0, "look_through_percentage_bps": None}
    nodes.append(root_entry)
    node_info[root_id] = root_entry

    # BFS over all directed paths; look-through sums path products with
    # per-edge integer truncation; depth = first (minimum) BFS discovery depth.
    queue = [(root_id, None, 0)]  # (node, path_acc, depth)
    while queue:
        next_queue = []
        for node, path_acc, depth in queue:
            for e in out_edges.get(node, []):
                child = e["subsidiary_entity_id"]
                if e["id"] not in emitted_edge_ids:
                    emitted_edge_ids.add(e["id"])
                    emitted_edges.append({
                        "parent_entity_id": e["parent_entity_id"],
                        "subsidiary_entity_id": e["subsidiary_entity_id"],
                        "percentage_bps": e["percentage_bps"],
                    })
                child_acc = e["percentage_bps"] if path_acc is None else (path_acc * e["percentage_bps"]) // 10000
                info = node_info.get(child)
                if info is None:
                    info = {"entity_id": child, "depth": depth + 1,
                            "look_through_percentage_bps": 0}
                    node_info[child] = info
                    nodes.append(info)
                info["look_through_percentage_bps"] += child_acc
                next_queue.append((child, child_acc, depth + 1))
        queue = next_queue

    return {"root_entity_id": root_id, "nodes": nodes, "edges": emitted_edges}
