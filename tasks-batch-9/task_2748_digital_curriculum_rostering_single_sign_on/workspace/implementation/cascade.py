"""Derived counters and the multi-hop cascades of PRD section 2.9.

Whenever a cascade reaches a record, that record's own updated_at and version
move, exactly as if it had been written directly.
"""
import calc
import store


def _apply(record, updates, force=False):
    """Write updates; bump updated_at/version when anything actually changed."""
    changed = False
    for field, value in updates.items():
        if record.get(field) != value:
            record[field] = value
            changed = True
    if changed or force:
        store.touch(record)
    return changed


# --------------------------------------------------------------------------
# Counter families
# --------------------------------------------------------------------------
def recompute_school_headcount(school):
    if school is None:
        return
    count = sum(1 for s in store.students.values()
                if s.get("school_id") == school["id"]
                and s.get("enrollment_state") == "ENROLLED")
    _apply(school, {"enrolled_student_count": count})


def recompute_section_count(section):
    if section is None:
        return
    count = sum(1 for e in store.enrollments.values()
                if e.get("section_id") == section["id"]
                and e.get("roster_status") in ("PENDING_ADD", "ACTIVE"))
    _apply(section, {"active_enrollment_count": count})


def recompute_student_count(student):
    if student is None:
        return
    count = sum(1 for e in store.enrollments.values()
                if e.get("student_id") == student["id"]
                and e.get("roster_status") in ("PENDING_ADD", "ACTIVE", "PENDING_DROP"))
    _apply(student, {"active_enrollment_count": count})


def allocations_of(vendor_id):
    rows = [a for a in store.building_allocations.values()
            if a.get("vendor_app_id") == vendor_id]
    rows.sort(key=lambda a: (a["created_at"], a["_seq"]))
    return rows


def accounts_of_allocation(allocation_id):
    return [a for a in store.app_accounts.values()
            if a.get("building_allocation_id") == allocation_id]


def recompute_allocation(allocation):
    accounts = accounts_of_allocation(allocation["id"])
    live = [a for a in accounts if a.get("seat_status") in ("RESERVED", "ACTIVE")]
    consumed = len(live)
    borrowed = sum(1 for a in live if a.get("_borrowed_seat"))
    _apply(allocation, {"consumed_seats": consumed, "borrowed_seats": borrowed})


def recompute_vendor(vendor, bump_version=True):
    """Recompute every derived figure of a license (and of its allocations)."""
    if vendor is None:
        return
    allocations = allocations_of(vendor["id"])
    for allocation in allocations:
        recompute_allocation(allocation)
    accounts = calc.vendor_accounts(vendor["id"])
    consumed = sum(1 for a in accounts
                   if a.get("seat_status") in ("RESERVED", "ACTIVE"))
    allocated_sum = sum((a.get("allocated_seats") or 0) for a in allocations)
    borrowed_sum = sum((a.get("borrowed_seats") or 0) for a in allocations)
    committed = sum(((a.get("seat_charge_cents") or 0)
                     - (a.get("refunded_charge_cents") or 0)) for a in accounts)
    updates = {
        "consumed_seats": consumed,
        "unallocated_seats": (vendor.get("total_seats") or 0) - allocated_sum - borrowed_sum,
        "committed_charge_cents": committed,
    }
    for field, value in updates.items():
        vendor[field] = value
    if accounts:
        figures = calc.renewal_figures(vendor, "final")
        vendor["renewal_score"] = figures["renewal_score"]
        vendor["renewal_recommendation"] = figures["renewal_recommendation"]
    else:
        vendor["renewal_score"] = None
        vendor["renewal_recommendation"] = None
    if bump_version:
        store.touch(vendor)


def recompute_run_counters(run):
    if run is None:
        return
    items = [i for i in store.error_queue_items.values()
             if i.get("sync_run_id") == run["id"] and i.get("status") == "OPEN"]
    blocking = sum(1 for i in items if i.get("severity") == "BLOCKING")
    advisory = sum(1 for i in items if i.get("severity") == "ADVISORY")
    _apply(run, {"blocking_error_count": blocking,
                 "advisory_error_count": advisory})


def compute_sync_health(vendor):
    """BLOCKED while a run of this vendor is HELD or holds an OPEN BLOCKING item."""
    for run in store.sync_runs.values():
        if run.get("vendor_app_id") != vendor["id"]:
            continue
        if run.get("state") == "HELD":
            return "BLOCKED"
        for item in store.error_queue_items.values():
            if (item.get("sync_run_id") == run["id"]
                    and item.get("status") == "OPEN"
                    and item.get("severity") == "BLOCKING"):
                return "BLOCKED"
    return "OK"


def apply_sync_health(vendor, bump_version=False):
    """Set sync_health; bump the license version only when asked to."""
    health = compute_sync_health(vendor)
    if vendor.get("sync_health") != health:
        vendor["sync_health"] = health
        if not bump_version:
            store.touch(vendor)
    return health


# --------------------------------------------------------------------------
# Seat release and identity wind-down
# --------------------------------------------------------------------------
def vendor_of_account(account):
    return store.vendor_apps.get(account.get("_vendor_app_id"))


def deprovision_identity(account, effective_date=None, stamp_schedule=True):
    updates = {"identity_status": "DEPROVISIONED", "password_state": "EXPIRED"}
    if stamp_schedule and effective_date is not None:
        updates["deprovision_scheduled_date"] = store.fmt_date(effective_date)
    _apply(account, updates)


def release_seat(account, refund_basis_date, identity=None,
                 deprovision_date=None, recompute=True, bump_version=True):
    """Seat axis -> RELEASED under the standard refund rule."""
    vendor = vendor_of_account(account)
    term = store.terms.get(vendor.get("term_id")) if vendor else None
    refunded = 0
    if term is not None:
        refunded = calc.refund_amount(account, term, refund_basis_date)
    updates = {"seat_status": "RELEASED", "refunded_charge_cents": refunded}
    if identity == "DEPROVISIONED":
        updates["identity_status"] = "DEPROVISIONED"
        updates["password_state"] = "EXPIRED"
        if deprovision_date is not None:
            updates["deprovision_scheduled_date"] = store.fmt_date(deprovision_date)
    elif identity == "SUSPENDED":
        updates["identity_status"] = "SUSPENDED"
    _apply(account, updates, force=True)
    if recompute:
        recompute_vendor(vendor, bump_version=bump_version)
    return vendor


def student_retained_by_vendor(student, vendor):
    """True while the student still has a live enrollment inside the license scope."""
    bands = vendor.get("grade_band_scope") or []
    for enrollment in store.enrollments.values():
        if enrollment.get("student_id") != student["id"]:
            continue
        if enrollment.get("roster_status") not in ("PENDING_ADD", "ACTIVE", "PENDING_DROP"):
            continue
        section = store.sections.get(enrollment.get("section_id"))
        if section is None:
            continue
        if section.get("term_id") != vendor.get("term_id"):
            continue
        if section.get("status") != "ACTIVE":
            continue
        school = store.schools.get(section.get("school_id"))
        if school is None or school.get("grade_band") not in bands:
            continue
        return True
    return False


def student_accounts(student):
    rows = [a for a in store.app_accounts.values()
            if a.get("subject_type") == "STUDENT"
            and a.get("student_id") == student["id"]]
    rows.sort(key=lambda a: (a["created_at"], a["_seq"]))
    return rows


def release_student_seats(student, refund_basis_date, identity=None,
                          deprovision_date=None, term_id=None,
                          aggregate=None):
    """The conditional hop: release only where the license no longer retains
    the student. When `aggregate` is a set, affected license ids are collected
    there and their counters are recomputed once by the caller."""
    for account in student_accounts(student):
        if account.get("seat_status") not in ("RESERVED", "ACTIVE"):
            continue
        vendor = vendor_of_account(account)
        if vendor is None:
            continue
        if term_id is not None and vendor.get("term_id") != term_id:
            continue
        if student_retained_by_vendor(student, vendor):
            continue
        release_seat(account, refund_basis_date, identity=identity,
                     deprovision_date=deprovision_date,
                     recompute=(aggregate is None))
        if aggregate is not None:
            aggregate.add(vendor["id"])

# --------------------------------------------------------------------------
# Triage items
# --------------------------------------------------------------------------
def open_item(run_id, category, source_ref):
    for item in store.error_queue_items.values():
        if (item.get("sync_run_id") == run_id
                and item.get("category") == category
                and item.get("source_ref") == source_ref
                and item.get("status") == "OPEN"):
            return item
    return None


def raise_item(run, category, severity, source_ref, section_id=None,
               student_id=None, duplicate_id=None):
    """One OPEN item per (category, source_ref) per run."""
    existing = open_item(run["id"], category, source_ref)
    if existing is not None:
        return existing
    item = {
        "sync_run_id": run["id"],
        "category": category,
        "severity": severity,
        "status": "OPEN",
        "source_ref": source_ref,
        "subject_section_id": section_id,
        "subject_student_id": student_id,
        "duplicate_candidate_student_id": duplicate_id,
        "resolved_by_user_id": None,
        "resolution_note": None,
        "resolved_at": None,
    }
    store.stamp_new(item)
    store.error_queue_items[item["id"]] = item
    return item


def hold_run(run):
    """A blocking defect parks an in-flight run and voids its projections."""
    updates = {"projected_seat_delta": None, "projected_charge_cents": None}
    if run.get("state") in ("EXTRACTED", "TRANSFORMED"):
        updates["state"] = "HELD"
    _apply(run, updates)


def in_flight_runs(vendor_id=None):
    rows = [r for r in store.sync_runs.values()
            if r.get("state") in ("EXTRACTED", "TRANSFORMED", "HELD")
            and (vendor_id is None or r.get("vendor_app_id") == vendor_id)]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows
