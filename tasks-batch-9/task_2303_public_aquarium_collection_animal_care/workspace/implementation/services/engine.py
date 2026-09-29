"""Derived-state recomputation, state-machine side effects and named cascades."""

from datetime import timedelta
from decimal import Decimal

import db
from db import touch
from services import calc

# ---------------------------------------------------------------- constants

ALARM_CLEAR_NORMAL_READINGS = 3
ALARM_DEESCALATE_NORMAL_READINGS = 2
INTERACTION_AUTO_DISABLE_THRESHOLD = 2
PERMIT_DEADLINE_DAYS = 30
PERMIT_MAX_ROUNDS = 3
PERMIT_MAX_VALIDITY_DAYS = 730
TRANSFER_MAX_COUNTERS = 2
QUARANTINE_MAX_EXTENSIONS = 2
QUARANTINE_MIN_CLEAR_EXAMS = 2

LIVE_SESSION_STATUSES = ("SCHEDULED", "ACTIVE")
CANCELLABLE_ACQ_STATUSES = ("DRAFT", "PENDING_PERMIT", "READY_FOR_CLEARANCE", "CLEARED")
REVOCABLE_PERMIT_STATUSES = ("DRAFT", "SUBMITTED", "INFO_REQUESTED", "ISSUED")
LIVE_TRANSFER_STATUSES = ("SUBMITTED", "COUNTERED", "APPROVED")

BIOLOAD_DISPOSITIONS = ("ON_EXHIBIT", "TRANSFER_PENDING")


# ---------------------------------------------------------------- lookups


def serving_system(exhibit):
    return db.db.life_support_systems.get(exhibit["life_support_system_id"])


def species_of(row_with_species_id):
    return db.db.species.get(row_with_species_id["species_id"])


def plan_entry_of(acq):
    return db.db.collection_plan_entries.get(acq["collection_plan_entry_id"])


def species_of_acquisition(acq):
    entry = plan_entry_of(acq)
    if entry is None:
        return None
    return db.db.species.get(entry["species_id"])


def source_institution_of(acq):
    return db.db.institutions.get(acq["source_institution_id"]) if acq["source_institution_id"] else None


def exhibits_of_system(system_id):
    return db.ordered("exhibits", lambda e: e["life_support_system_id"] == system_id)


def permits_of_acquisition(acq_id):
    return db.ordered("permits", lambda p: p["acquisition_request_id"] == acq_id)


def acquisitions_of_entry(entry_id):
    return db.ordered("acquisition_requests", lambda a: a["collection_plan_entry_id"] == entry_id)


def active_quarantine_case(specimen_id):
    for case in db.ordered("quarantine_cases", lambda c: c["specimen_id"] == specimen_id):
        if case["status"] in ("ACTIVE", "EXTENDED"):
            return case
    return None


def approved_plan_entry(exhibit_id, species_id):
    for entry in db.ordered(
        "collection_plan_entries",
        lambda e: e["exhibit_id"] == exhibit_id and e["species_id"] == species_id,
    ):
        if entry["status"] == "APPROVED":
            return entry
    return None


# ---------------------------------------------------------------- derived flags


def redundancy_overdue(system):
    """Computed live from the logical clock - never stored."""
    if system is None:
        return False
    base = system["last_redundancy_test_at"] or system["created_at"]
    interval = int(system["redundancy_test_interval_days"])
    return db.db.clock >= base + timedelta(days=interval)


def clearance_exam_count(case):
    """CLOSED PREVENTIVE_EXAM cases with no findings inside [started_at, clock_now)."""
    started = case["started_at"]
    now = db.db.clock
    total = 0
    for vc in db.db.veterinary_cases.values():
        if vc["specimen_id"] != case["specimen_id"]:
            continue
        if vc["case_type"] != "PREVENTIVE_EXAM" or vc["status"] != "CLOSED":
            continue
        if vc["findings_severity"] != "NONE":
            continue
        if started <= vc["opened_at"] < now:
            total += 1
    return total


# ---------------------------------------------------------------- exhibit posture


def _exhibit_snapshot(exhibit):
    return (
        exhibit["occupied_bioload_units"],
        exhibit["bioload_utilization_pct"],
        exhibit["posture"],
        exhibit["last_posture_reason"],
        exhibit["suspended_session_count"],
        exhibit["interaction_program_enabled"],
    )


def suspend_session(session, exhibit, reason):
    session["status"] = "SUSPENDED"
    session["suspension_reason"] = reason
    touch(session)
    exhibit["suspended_session_count"] = int(exhibit["suspended_session_count"]) + 1
    if exhibit["suspended_session_count"] >= INTERACTION_AUTO_DISABLE_THRESHOLD:
        exhibit["interaction_program_enabled"] = False


def _suspend_live_sessions(exhibit, program_types=None):
    """CASCADE A links 3-5, in created_at ASC order."""
    rows = db.ordered(
        "interaction_sessions",
        lambda s: s["exhibit_id"] == exhibit["id"] and s["status"] in LIVE_SESSION_STATUSES,
    )
    for session in rows:
        if program_types is not None and session["program_type"] not in program_types:
            continue
        suspend_session(session, exhibit, "EXHIBIT_CLOSED")


def recompute_exhibit(exhibit, dive_only=False, force=False):
    """Recompute the ledger and the posture; run CASCADE A links 3-5 when needed."""
    before = _exhibit_snapshot(exhibit)
    was_closed = exhibit["posture"] == "CLOSED"
    occupied, utilization = calc.exhibit_ledger(exhibit)
    system = serving_system(exhibit)
    posture, reason = calc.exhibit_posture(system, utilization, redundancy_overdue(system))
    exhibit["occupied_bioload_units"] = occupied
    exhibit["bioload_utilization_pct"] = utilization
    exhibit["posture"] = posture
    exhibit["last_posture_reason"] = reason
    if posture == "CLOSED":
        if dive_only:
            _suspend_live_sessions(exhibit, ("DIVE_ENCOUNTER",))
        elif not was_closed:
            _suspend_live_sessions(exhibit, None)
    changed = _exhibit_snapshot(exhibit) != before
    if changed or force:
        touch(exhibit)
    return changed


def recompute_system_exhibits(system):
    changed_ids = []
    for exhibit in exhibits_of_system(system["id"]):
        if recompute_exhibit(exhibit):
            changed_ids.append(exhibit["id"])
    return changed_ids


# ---------------------------------------------------------------- plant alarms


def apply_reading(system, reading):
    """Advance the LifeSupportSystem alarm state machine for one appended reading."""
    severity = reading["severity"]
    alarm = system["alarm_state"]
    if alarm != "OFFLINE":
        if severity == "NORMAL":
            system["consecutive_normal_readings"] = int(system["consecutive_normal_readings"]) + 1
            system["consecutive_breach_readings"] = 0
            normals = system["consecutive_normal_readings"]
            if alarm == "WARNING" and normals >= ALARM_CLEAR_NORMAL_READINGS:
                system["alarm_state"] = "NORMAL"
            elif alarm == "CRITICAL" and normals >= ALARM_DEESCALATE_NORMAL_READINGS:
                system["alarm_state"] = "WARNING"
        else:
            system["consecutive_breach_readings"] = int(system["consecutive_breach_readings"]) + 1
            system["consecutive_normal_readings"] = 0
            if severity == "CRITICAL":
                system["alarm_state"] = "CRITICAL"
            elif alarm != "CRITICAL":
                system["alarm_state"] = "WARNING"
    system["water_quality_index"] = calc.plant_water_quality_index(system["id"])
    touch(system)
    recompute_system_exhibits(system)


def apply_redundancy_test(system, performed_at, result):
    system["last_redundancy_test_result"] = result
    if result == "FAIL":
        system["alarm_state"] = "OFFLINE"
    else:
        system["last_redundancy_test_at"] = performed_at
        if system["alarm_state"] == "OFFLINE":
            latest = calc.latest_reading(system["id"])
            severity = latest["severity"] if latest is not None else "NORMAL"
            system["alarm_state"] = severity
    touch(system)
    recompute_system_exhibits(system)


# ---------------------------------------------------------------- welfare


def refresh_welfare_rolling(specimen):
    """Returns True when the stored welfare value or variant changed."""
    value = calc.welfare_rolling(specimen["id"])
    if value is None:
        return False
    if specimen["welfare_score"] == value and specimen["welfare_score_variant"] == "ROLLING":
        return False
    specimen["welfare_score"] = value
    specimen["welfare_score_variant"] = "ROLLING"
    return True


def refresh_welfare_audit_snapshot(specimen):
    value = calc.welfare_audit_snapshot(specimen["id"])
    if value is None:
        return False
    if specimen["welfare_score"] == value and specimen["welfare_score_variant"] == "AUDIT_SNAPSHOT":
        return False
    specimen["welfare_score"] = value
    specimen["welfare_score_variant"] = "AUDIT_SNAPSHOT"
    return True


def refresh_withdrawal(specimen):
    value = calc.treatment_withdrawal_until(specimen["id"])
    if specimen["treatment_withdrawal_until"] == value:
        return False
    specimen["treatment_withdrawal_until"] = value
    return True


# ---------------------------------------------------------------- quota / permits


def release_quota(acq):
    """Return an acquisition's wild-take reservation to the species pool."""
    reserved = int(acq["quota_units_reserved"] or 0)
    if reserved <= 0:
        acq["quota_units_reserved"] = 0
        return
    acq["quota_units_reserved"] = 0
    species = species_of_acquisition(acq)
    if species is not None:
        species["wild_take_quota_reserved"] = max(
            0, int(species["wild_take_quota_reserved"]) - reserved)
        touch(species)


def revoke_permit(permit, reason):
    permit["status"] = "REVOKED"
    permit["decision_reason"] = reason
    touch(permit)
    decline_transfers_for_permit(permit)


def revoke_permits_of_acquisition(acq, reason="ACQUISITION_CANCELLED"):
    for permit in permits_of_acquisition(acq["id"]):
        if permit["status"] in REVOCABLE_PERMIT_STATUSES:
            revoke_permit(permit, reason)


def cancel_acquisition(acq, closure_reason):
    acq["status"] = "CANCELLED"
    acq["closure_reason"] = closure_reason
    release_quota(acq)
    touch(acq)
    revoke_permits_of_acquisition(acq)


def reject_acquisition(acq):
    acq["status"] = "REJECTED"
    acq["closure_reason"] = "PERMIT_EXPIRED"
    release_quota(acq)
    touch(acq)


# ---------------------------------------------------------------- transfers


def restore_specimen_disposition(specimen):
    """Compensating restore of a TRANSFER_PENDING specimen."""
    if specimen is None:
        return False
    if specimen["disposition_status"] != "TRANSFER_PENDING":
        return False
    previous = specimen["pre_transfer_disposition"]
    if previous is None:
        return False
    specimen["disposition_status"] = previous
    specimen["pre_transfer_disposition"] = None
    touch(specimen)
    return True


def decline_transfer(transfer, reason):
    transfer["status"] = "DECLINED"
    transfer["decline_reason"] = reason
    touch(transfer)
    restore_specimen_disposition(db.db.specimens.get(transfer["specimen_id"]))


def decline_transfers_for_permit(permit):
    rows = db.ordered(
        "transfer_requests",
        lambda t: t["transport_permit_id"] == permit["id"] and t["status"] in LIVE_TRANSFER_STATUSES,
    )
    for transfer in rows:
        decline_transfer(transfer, "TRANSPORT_PERMIT_EXPIRED")


def cascade_institution_ineligible(institution):
    """CASCADE C links 1-3."""
    rows = db.ordered(
        "transfer_requests",
        lambda t: t["receiving_institution_id"] == institution["id"]
        and t["status"] in LIVE_TRANSFER_STATUSES,
    )
    for transfer in rows:
        decline_transfer(transfer, "RECEIVER_INELIGIBLE")


# ---------------------------------------------------------------- plan entries


def suspend_plan_entry(entry, reason):
    """Plan suspension plus its acquisition / permit cascade."""
    entry["status"] = "SUSPENDED"
    entry["suspension_reason"] = reason
    touch(entry)
    for acq in acquisitions_of_entry(entry["id"]):
        if acq["status"] in CANCELLABLE_ACQ_STATUSES:
            cancel_acquisition(acq, "PLAN_SUSPENDED")


# ---------------------------------------------------------------- mortality


def declare_mortality(specimen, occurred_at, user_id):
    """CASCADE B links 1-5 plus the quarantine and transfer unwinds."""
    former_exhibit_id = specimen["exhibit_id"]
    species_id = specimen["species_id"]

    # link 1
    for case in db.ordered("veterinary_cases", lambda c: c["specimen_id"] == specimen["id"]):
        if case["case_type"] == "TREATMENT" and case["status"] == "OPEN":
            case["status"] = "CLOSED"
            case["outcome"] = "MORTALITY_REFERRED"
            case["findings_severity"] = "CRITICAL"
            case["closed_by_user_id"] = user_id
            case["closed_at"] = db.db.clock
            touch(case)

    specimen["disposition_status"] = "DECEASED"
    specimen["health_status"] = "DECEASED_PENDING_NECROPSY"
    specimen["exhibit_id"] = None
    refresh_withdrawal(specimen)
    touch(specimen)

    necropsy = db.new_row()
    necropsy.update({
        "specimen_id": specimen["id"],
        "case_type": "NECROPSY",
        "opened_at": occurred_at,
        "treatment_start_at": None,
        "withdrawal_days": None,
        "diagnosis_code": None,
        "status": "OPEN",
        "outcome": None,
        "findings_severity": None,
        "opened_by_user_id": user_id,
        "closed_by_user_id": None,
        "closed_at": None,
    })
    db.insert("veterinary_cases", necropsy)

    quarantine = active_quarantine_case(specimen["id"])
    if quarantine is not None:
        quarantine["status"] = "FAILED"
        quarantine["failure_reason"] = "MORTALITY"
        touch(quarantine)

    # transfer withdrawal
    for transfer in db.ordered(
        "transfer_requests",
        lambda t: t["specimen_id"] == specimen["id"] and t["status"] in LIVE_TRANSFER_STATUSES,
    ):
        transfer["status"] = "WITHDRAWN"
        touch(transfer)

    # links 2 to 5
    if former_exhibit_id is not None:
        exhibit = db.db.exhibits.get(former_exhibit_id)
        if exhibit is not None:
            recompute_exhibit(exhibit, force=True)
            remaining = [
                sp for sp in db.db.specimens.values()
                if sp["exhibit_id"] == former_exhibit_id
                and sp["species_id"] == species_id
                and sp["disposition_status"] in ("ON_EXHIBIT", "TRANSFER_PENDING", "CLEARED")
            ]
            if not remaining:
                entry = approved_plan_entry(former_exhibit_id, species_id)
                if entry is not None:
                    suspend_plan_entry(entry, "LAST_SPECIMEN_LOST")
    return necropsy


def critical_care_coupling(specimen):
    """CRITICAL_CARE COUPLING links 1-4 (link 1 is applied by the caller)."""
    if specimen["disposition_status"] != "ON_EXHIBIT":
        return
    exhibit = db.db.exhibits.get(specimen["exhibit_id"])
    specimen["disposition_status"] = "CLEARED"
    specimen["exhibit_id"] = None
    specimen["holding_area"] = "LAST_KNOWN_HOLDING"
    if exhibit is not None:
        recompute_exhibit(exhibit, dive_only=True, force=True)


# ---------------------------------------------------------------- audits


def rescore_audit_specimens():
    """START / REOPEN step 1: AUDIT_SNAPSHOT rescoring of every in-scope specimen."""
    for specimen in db.ordered(
        "specimens", lambda s: s["disposition_status"] in ("CLEARED", "ON_EXHIBIT")
    ):
        if refresh_welfare_audit_snapshot(specimen):
            touch(specimen)


def score_audit(audit):
    """START / REOPEN step 2: readiness scoring from the step-1 values."""
    score, subscores, blocking = calc.readiness(redundancy_overdue)
    audit["readiness_score"] = score
    audit["domain_subscores"] = subscores
    audit["blocking_finding_count"] = blocking


# ---------------------------------------------------------------- logical clock


def advance_clock(new_clock):
    """CASCADE D: permit expiry -> acquisition rejection -> quota release, then postures."""
    db.db.clock = new_clock

    expired_permit_ids = []
    rejected_ids = []

    for permit in db.ordered("permits"):
        if permit["status"] != "ISSUED":
            continue
        if permit["valid_until"] is None or permit["valid_until"] > new_clock:
            continue
        permit["status"] = "EXPIRED"
        touch(permit)
        expired_permit_ids.append(permit["id"])
        acq = db.db.acquisition_requests.get(permit["acquisition_request_id"])
        # PRD §3.5: "Its acquisition request, if `PENDING_PERMIT` or `CLEARED`,
        # moves to the terminal `REJECTED`" — the state is the only condition.
        if acq is not None and acq["status"] in ("PENDING_PERMIT", "CLEARED"):
            reject_acquisition(acq)
            rejected_ids.append(acq["id"])
        for transfer in db.ordered(
            "transfer_requests",
            lambda t, pid=permit["id"]: t["transport_permit_id"] == pid
            and t["status"] in LIVE_TRANSFER_STATUSES,
        ):
            decline_transfer(transfer, "TRANSPORT_PERMIT_EXPIRED")

    for acq in db.ordered("acquisition_requests"):
        if acq["status"] != "PENDING_PERMIT":
            continue
        deadline = acq["permit_deadline_at"]
        if deadline is None or deadline > new_clock:
            continue
        issued = [p for p in permits_of_acquisition(acq["id"]) if p["status"] == "ISSUED"]
        if issued:
            continue
        reject_acquisition(acq)
        rejected_ids.append(acq["id"])

    recomputed_exhibit_ids = []
    for exhibit in db.ordered("exhibits"):
        if recompute_exhibit(exhibit):
            recomputed_exhibit_ids.append(exhibit["id"])

    return expired_permit_ids, rejected_ids, recomputed_exhibit_ids
