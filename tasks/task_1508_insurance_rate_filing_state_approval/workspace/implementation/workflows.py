"""Shared workflow machinery: compliance calendar entries, filing bubble-up,
withdrawal/disapproval cascades, wave reversal, and the logical-clock sweep.
"""
from datetime import timedelta

from calc import resolve_actual_effective_date
from errors import err, ERR_NOT_FOUND
from store import db, new_id, now, touch
from timeutil import end_of_day_utc, start_of_day_utc, parse_date

# Objection statuses counted in RateFiling.open_objection_count (PRD §3.4).
OPEN_OBJECTION_STATUSES = {
    "RAISED",
    "RESPONSE_DRAFTED",
    "RESPONSE_SUBMITTED",
    "OVERDUE",
    "REOPENED",
}
# Statuses that hold the filing in UNDER_OBJECTION (bubble-up set). Note the
# deliberate asymmetry: RESPONSE_SUBMITTED counts as open but does not hold.
HOLDING_OBJECTION_STATUSES = {"RAISED", "RESPONSE_DRAFTED", "OVERDUE", "REOPENED"}


# --- entities ----------------------------------------------------------------

def base_entity():
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def get_or_404(collection, entity_id):
    entity = collection.get(entity_id)
    if entity is None:
        raise err(ERR_NOT_FOUND)
    return entity


# --- compliance calendar ------------------------------------------------------

def create_calendar_entry(entry_type, due_date, filing_id=None, wave_id=None,
                          objection_id=None, policy_id=None):
    entry = base_entity()
    entry.update({
        "filing_id": filing_id,
        "wave_id": wave_id,
        "objection_id": objection_id,
        "entry_type": entry_type,
        "due_date": due_date,
        "status": "PENDING",
        "resolved_at": None,
        "_policy_id": policy_id,
    })
    db.compliance_calendar_entries[entry["id"]] = entry
    return entry


def find_entries(entry_type=None, filing_id=None, wave_id=None, objection_id=None,
                 policy_id=None, status=None):
    out = []
    for e in db.compliance_calendar_entries.values():
        if entry_type is not None and e["entry_type"] != entry_type:
            continue
        if filing_id is not None and e["filing_id"] != filing_id:
            continue
        if wave_id is not None and e["wave_id"] != wave_id:
            continue
        if objection_id is not None and e["objection_id"] != objection_id:
            continue
        if policy_id is not None and e.get("_policy_id") != policy_id:
            continue
        if status is not None and e["status"] != status:
            continue
        out.append(e)
    return out


def entry_resolve(entry, status, allow_missed_source=False):
    """Drive an entry out of PENDING. Explicit MET transitions may also claim
    a MISSED entry (the obligation was ultimately satisfied); WAIVED/MISSED
    sweeps only apply from PENDING. Never overrides a WAIVED entry."""
    if entry["status"] == "PENDING" or (allow_missed_source and entry["status"] == "MISSED"):
        if entry["status"] != status:
            entry["status"] = status
            entry["resolved_at"] = now()
            touch(entry)
        elif entry["resolved_at"] is None and status == "PENDING":
            pass


def entry_mark_met(entry):
    if entry is not None and entry["status"] in ("PENDING", "MISSED"):
        entry["status"] = "MET"
        entry["resolved_at"] = now()
        touch(entry)


def entry_waive(entry):
    if entry is not None and entry["status"] == "PENDING":
        entry["status"] = "WAIVED"
        entry["resolved_at"] = now()
        touch(entry)


def entry_mark_missed(entry):
    if entry is not None and entry["status"] == "PENDING":
        entry["status"] = "MISSED"
        entry["resolved_at"] = now()
        touch(entry)


def reanchor_effective_date_entry(filing, actual_effective_date):
    """Re-anchor the EFFECTIVE_DATE entry to the resolved actual date;
    a MISSED entry is re-established as PENDING (never resurrects WAIVED)."""
    entries = find_entries("EFFECTIVE_DATE", filing_id=filing["id"])
    for e in entries:
        if e["status"] in ("PENDING", "MISSED"):
            e["due_date"] = end_of_day_utc(parse_date(actual_effective_date))
            e["status"] = "PENDING"
            e["resolved_at"] = None
            touch(e)


# --- filing objection bookkeeping --------------------------------------------

def recompute_filing_objections(filing):
    """Recompute open_objection_count; bubble UNDER_OBJECTION back to
    SUBMITTED once no objection remains in the holding set."""
    objs = [o for o in db.objections.values() if o["filing_id"] == filing["id"]]
    open_count = sum(1 for o in objs if o["status"] in OPEN_OBJECTION_STATUSES)
    changed = False
    if filing["open_objection_count"] != open_count:
        filing["open_objection_count"] = open_count
        changed = True
    if filing["status"] == "UNDER_OBJECTION" and not any(
        o["status"] in HOLDING_OBJECTION_STATUSES for o in objs
    ):
        filing["status"] = "SUBMITTED"
        changed = True
    if changed:
        touch(filing)


# --- cascades -----------------------------------------------------------------

def _withdraw_components(filing):
    for c in db.filing_components.values():
        if c["filing_id"] == filing["id"] and c["status"] in ("DRAFT", "FINAL"):
            c["status"] = "WITHDRAWN"
            touch(c)


def _supersede_components(filing):
    for c in db.filing_components.values():
        if c["filing_id"] == filing["id"] and c["status"] == "FINAL":
            c["status"] = "SUPERSEDED"
            touch(c)


def _withdraw_deviations(filing, approved_to):
    for d in db.deviations.values():
        if d["filing_id"] != filing["id"]:
            continue
        if d["status"] == "PROPOSED":
            d["status"] = "WITHDRAWN"
            touch(d)
        elif d["status"] == "APPROVED" and approved_to == "SUPERSEDED":
            d["status"] = "SUPERSEDED"
            touch(d)


def _withdraw_objection(obj):
    """Full withdrawal semantics for one non-terminal objection."""
    if obj["status"] in ("RESOLVED", "WITHDRAWN"):
        return
    for r in db.objection_responses.values():
        if r["objection_id"] == obj["id"] and r["status"] == "DRAFT":
            r["status"] = "SUPERSEDED"
            touch(r)
    for e in find_entries("OBJECTION_RESPONSE_DUE", objection_id=obj["id"], status="PENDING"):
        entry_waive(e)
    obj["status"] = "WITHDRAWN"
    obj["resolved_at"] = now()
    touch(obj)


def cascade_filing_withdrawn(filing, from_status):
    """PRD §3.6 withdrawal cascade, shaped by how far the filing progressed."""
    _withdraw_components(filing)
    if from_status in ("SUBMITTED", "UNDER_OBJECTION", "APPROVED", "DEEMED_APPROVED"):
        _withdraw_deviations(filing, approved_to="SUPERSEDED")
    else:  # DRAFT, READY
        _withdraw_deviations(filing, approved_to="WITHDRAWN")
    if from_status in ("SUBMITTED", "UNDER_OBJECTION"):
        for e in find_entries("DEEMER_DATE", filing_id=filing["id"]):
            entry_waive(e)
        for e in find_entries("EFFECTIVE_DATE", filing_id=filing["id"]):
            entry_waive(e)
    if from_status in ("APPROVED", "DEEMED_APPROVED"):
        for e in find_entries("EFFECTIVE_DATE", filing_id=filing["id"]):
            entry_waive(e)
    if from_status == "UNDER_OBJECTION":
        for o in db.objections.values():
            if o["filing_id"] == filing["id"]:
                _withdraw_objection(o)
    filing["status"] = "WITHDRAWN"
    touch(filing)


def reverse_wave(wave):
    """RELEASED -> REVERSED with full premium restoration (PRD §3.6/§3.7)."""
    for p in db.renewal_policies.values():
        if p["wave_id"] != wave["id"]:
            continue
        if p["status"] == "RATED":
            for e in find_entries("RENEWAL_NOTICE_DUE", wave_id=wave["id"],
                                  policy_id=p["id"], status="PENDING"):
                entry_waive(e)
            p["status"] = "PENDING"
            _null_rating_fields(p, null_wave=True)
            touch(p)
        elif p["status"] in ("NOTICE_SENT", "COMPLETED"):
            p["current_premium_cents"] = p["baseline_premium_cents"]
            p["status"] = "RESCINDED"
            _null_rating_fields(p, null_wave=False)  # wave_id retained for audit
            touch(p)
    for e in find_entries("WAVE_WINDOW", wave_id=wave["id"]):
        entry_waive(e)
    wave["rated_policy_count"] = 0
    wave["status"] = "REVERSED"
    touch(wave)


def cancel_wave(wave):
    for e in find_entries("WAVE_WINDOW", wave_id=wave["id"]):
        entry_waive(e)
    wave["status"] = "CANCELLED"
    touch(wave)


def _null_rating_fields(p, null_wave):
    if null_wave:
        p["wave_id"] = None
    p["baseline_premium_cents"] = None
    p["raw_change_pct"] = None
    p["raw_new_premium_cents"] = None
    p["was_capped"] = None
    p["final_premium_cents"] = None
    p["notice_due_date"] = None


def recompute_wave_rated_count(wave):
    count = sum(
        1
        for p in db.renewal_policies.values()
        if p["wave_id"] == wave["id"] and p["status"] in ("RATED", "NOTICE_SENT", "COMPLETED")
    )
    if wave["rated_policy_count"] != count:
        wave["rated_policy_count"] = count
        touch(wave)


def approve_filing_common(filing, profile, approval_dt):
    """Shared approval side effects for APPROVED and DEEMED_APPROVED."""
    filing["approved_at"] = approval_dt
    filing["actual_effective_date"] = resolve_actual_effective_date(
        profile, filing["proposed_effective_date"], approval_dt.date()
    )
    for e in find_entries("DEEMER_DATE", filing_id=filing["id"]):
        entry_mark_met(e)
    reanchor_effective_date_entry(filing, filing["actual_effective_date"])


# --- the system sweep -----------------------------------------------------------

def run_sweep():
    """One deterministic pass reconciling time-driven state (PRD §2.4).

    Order: objection OVERDUE transitions, deemer approvals, late-notice policy
    bounce, wave completion, then generic calendar MISSED evaluation.
    """
    with db.lock:
        current = now()
        today = current.date()

        # 1. Objections in RAISED | RESPONSE_DRAFTED past due_at -> OVERDUE
        for obj in list(db.objections.values()):
            if obj["status"] in ("RAISED", "RESPONSE_DRAFTED") and current > obj["due_at"]:
                obj["status"] = "OVERDUE"
                obj["late_breach"] = True
                touch(obj)
                for e in find_entries("OBJECTION_RESPONSE_DUE",
                                      objection_id=obj["id"], status="PENDING"):
                    entry_mark_missed(e)

        # 2. Deemed approvals (deemer tolls while any objection is non-terminal)
        for filing in list(db.rate_filings.values()):
            if filing["status"] != "SUBMITTED" or filing["deemer_date"] is None:
                continue
            if today < parse_date(filing["deemer_date"]):
                continue
            has_open = any(
                o["filing_id"] == filing["id"] and o["status"] in OPEN_OBJECTION_STATUSES
                for o in db.objections.values()
            )
            if has_open:
                continue
            profile = db.state_profiles.get(filing["profile_id"])
            filing["status"] = "DEEMED_APPROVED"
            touch(filing)
            approve_filing_common(
                filing, profile, start_of_day_utc(parse_date(filing["deemer_date"]))
            )

        # 3. Late-notice bounce: RATED policy whose notice deadline has passed
        for p in list(db.renewal_policies.values()):
            if p["status"] != "RATED" or p["notice_due_date"] is None:
                continue
            if today > parse_date(p["notice_due_date"]):
                wave = db.implementation_waves.get(p["wave_id"])
                for e in find_entries("RENEWAL_NOTICE_DUE", policy_id=p["id"],
                                      status="PENDING"):
                    entry_mark_missed(e)
                p["status"] = "PENDING"
                _null_rating_fields(p, null_wave=True)
                p["exclusion_reason"] = "LATE_NOTICE_SWEEP"
                touch(p)
                if wave is not None:
                    recompute_wave_rated_count(wave)

        # 4. Wave completion: window closed and every assigned policy settled
        for wave in list(db.implementation_waves.values()):
            if wave["status"] != "RELEASED":
                continue
            if today <= parse_date(wave["wave_end_date"]):
                continue
            outstanding = any(
                p["wave_id"] == wave["id"] and p["status"] in ("RATED", "NOTICE_SENT")
                for p in db.renewal_policies.values()
            )
            if outstanding:
                continue
            wave["status"] = "COMPLETED"
            touch(wave)
            for e in find_entries("WAVE_WINDOW", wave_id=wave["id"]):
                entry_mark_met(e)

        # 5. Generic calendar MISSED: PENDING entries past their deadline
        for e in list(db.compliance_calendar_entries.values()):
            if e["status"] == "PENDING" and current > e["due_date"]:
                entry_mark_missed(e)
