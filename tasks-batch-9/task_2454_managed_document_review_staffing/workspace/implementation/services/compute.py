"""Lookups, derived figures, calculation rules and serializers."""

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from db import by_creation, db
from errors import ApiError

# ---------------------------------------------------------------------------
# Constants (PRD 3.6 / 3.8 / 3.9)
# ---------------------------------------------------------------------------
COMPLEXITY_TIER_MULTIPLIER = {
    "SIMPLE": Decimal("1.00"),
    "STANDARD": Decimal("1.15"),
    "COMPLEX": Decimal("1.35"),
}
PASS_TYPE_MULTIPLIER = {
    "FIRST_PASS": Decimal("1.00"),
    "SECOND_LEVEL": Decimal("0.60"),
}
LANGUAGE_PREMIUM_PER_LANGUAGE = Decimal("0.05")
HOURLY_INCREMENT_MINUTES = 6
QC_SURCHARGE_FACTOR = Decimal("0.20")
QC_MIN_SAMPLE_DOCS = 10
PRIVILEGE_VALIDATION_FLOOR = 2
REMOVAL_STRIKE_THRESHOLD = 3
ACCURACY_FLOOR_FOR_REMOVAL = Decimal("0.9000")
ACCURACY_FLOOR_MIN_SAMPLED_DOCS = 50
MIN_EFFECTIVE_REVIEWERS = 1

ACCURACY_WEIGHT = Decimal("0.45")
PACE_WEIGHT = Decimal("0.30")
LANGUAGE_WEIGHT = Decimal("0.15")
SUBJECT_WEIGHT = Decimal("0.10")
STRIKE_PENALTY_WEIGHT = Decimal("0.05")
STRIKE_PENALTY_CAP = 2
PACE_NORMALISATION_CAP = Decimal("1.5")

ACTIVE_ASSIGNMENT_STATUSES = ("ASSIGNED", "IN_PROGRESS", "REOPENED")
REMAINING_WORK_BATCH_STATUSES = (
    "CREATED", "ASSIGNED", "IN_PROGRESS", "SECOND_LEVEL", "QC_FAILED",
)

STRIKE_DELTA_BY_EVENT_TYPE = {
    "PACE_SHORTFALL": 1,
    "ACCURACY_MISS": 1,
    "PRIVILEGE_MISS": 1,
    "QC_FAILURE": 1,
    "CLEARED_STRIKE": -1,
    "REMOVAL": 0,
}


# ---------------------------------------------------------------------------
# Arithmetic helpers
# ---------------------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def cents(value):
    return int(round_half_up(value, 0))


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


def num(value, places):
    return float(round_half_up(value, places))


# ---------------------------------------------------------------------------
# Lookups (rank 4 / rank 5)
# ---------------------------------------------------------------------------
def get_client(client_id):
    row = db.clients.get(client_id) if isinstance(client_id, str) else None
    if row is None:
        raise ApiError("ERR_CLIENT_NOT_FOUND", "No client with that id exists.")
    return row


def get_matter(matter_id):
    row = db.matters.get(matter_id) if isinstance(matter_id, str) else None
    if row is None:
        raise ApiError("ERR_MATTER_NOT_FOUND", "No matter with that id exists.")
    return row


def get_protocol(protocol_id):
    row = db.protocols.get(protocol_id) if isinstance(protocol_id, str) else None
    if row is None:
        raise ApiError("ERR_PROTOCOL_NOT_FOUND", "No protocol revision with that id exists.")
    return row


def get_reviewer(reviewer_id):
    row = db.reviewers.get(reviewer_id) if isinstance(reviewer_id, str) else None
    if row is None:
        raise ApiError("ERR_REVIEWER_NOT_FOUND", "No reviewer with that id exists.")
    return row


def get_screening(screening_id):
    row = db.screenings.get(screening_id) if isinstance(screening_id, str) else None
    if row is None:
        raise ApiError("ERR_SCREENING_NOT_FOUND", "No conflicts screening with that id exists.")
    return row


def get_agreement(agreement_id):
    row = db.agreements.get(agreement_id) if isinstance(agreement_id, str) else None
    if row is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND", "No confidentiality agreement with that id exists.")
    return row


def get_session(session_id):
    row = db.sessions.get(session_id) if isinstance(session_id, str) else None
    if row is None:
        raise ApiError("ERR_SESSION_NOT_FOUND", "No secure-environment session with that id exists.")
    return row


def get_batch(batch_id):
    row = db.batches.get(batch_id) if isinstance(batch_id, str) else None
    if row is None:
        raise ApiError("ERR_BATCH_NOT_FOUND", "No batch with that id exists.")
    return row


def get_assignment(assignment_id):
    row = db.assignments.get(assignment_id) if isinstance(assignment_id, str) else None
    if row is None:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND", "No assignment with that id exists.")
    return row


def get_qc_sample(sample_id):
    row = db.qc_samples.get(sample_id) if isinstance(sample_id, str) else None
    if row is None:
        raise ApiError("ERR_QC_SAMPLE_NOT_FOUND", "No quality-control sample with that id exists.")
    return row


def get_privilege_entry(entry_id):
    row = db.privilege_entries.get(entry_id) if isinstance(entry_id, str) else None
    if row is None:
        raise ApiError("ERR_PRIVILEGE_ENTRY_NOT_FOUND", "No privilege log entry with that id exists.")
    return row


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------
def matters_of_client(client_id):
    return [m for m in db.matters.values() if m["client_id"] == client_id]


def protocols_of_matter(matter_id):
    return by_creation([p for p in db.protocols.values() if p["matter_id"] == matter_id])


def batches_of_matter(matter_id):
    return by_creation([b for b in db.batches.values() if b["matter_id"] == matter_id])


def assignments_of_batch(batch_id):
    return by_creation([a for a in db.assignments.values() if a["batch_id"] == batch_id])


def assignments_of_matter(matter_id):
    ids = set(b["id"] for b in db.batches.values() if b["matter_id"] == matter_id)
    return by_creation([a for a in db.assignments.values() if a["batch_id"] in ids])


def assignments_of_reviewer(reviewer_id):
    return by_creation([a for a in db.assignments.values() if a["reviewer_id"] == reviewer_id])


def samples_of_batch(batch_id):
    return by_creation([s for s in db.qc_samples.values() if s["batch_id"] == batch_id])


def entries_of_batch(batch_id):
    return by_creation([e for e in db.privilege_entries.values() if e["batch_id"] == batch_id])


def entries_of_matter(matter_id):
    return by_creation([e for e in db.privilege_entries.values() if e["matter_id"] == matter_id])


def screenings_of_pair(reviewer_id, matter_id):
    return by_creation([s for s in db.screenings.values()
                        if s["reviewer_id"] == reviewer_id and s["matter_id"] == matter_id])


def agreements_of_pair(reviewer_id, matter_id):
    return by_creation([a for a in db.agreements.values()
                        if a["reviewer_id"] == reviewer_id and a["matter_id"] == matter_id])


def agreements_of_matter(matter_id):
    return by_creation([a for a in db.agreements.values() if a["matter_id"] == matter_id])


def sessions_of_pair(reviewer_id, matter_id):
    return by_creation([s for s in db.sessions.values()
                        if s["reviewer_id"] == reviewer_id and s["matter_id"] == matter_id])


def sessions_of_matter(matter_id):
    return by_creation([s for s in db.sessions.values() if s["matter_id"] == matter_id])


def sessions_of_reviewer(reviewer_id):
    return by_creation([s for s in db.sessions.values() if s["reviewer_id"] == reviewer_id])


def events_of_reviewer(reviewer_id):
    return by_creation([e for e in db.scorecard_events.values()
                        if e["reviewer_id"] == reviewer_id])


def ledger_of_matter(matter_id):
    return by_creation([e for e in db.ledger_entries.values() if e["matter_id"] == matter_id])


def ledger_of_assignment(assignment_id):
    return by_creation([e for e in db.ledger_entries.values()
                        if e["assignment_id"] == assignment_id])


def matter_of_batch(batch):
    return db.matters[batch["matter_id"]]


def matter_of_assignment(assignment):
    return matter_of_batch(db.batches[assignment["batch_id"]])


def batch_of_assignment(assignment):
    return db.batches[assignment["batch_id"]]


# ---------------------------------------------------------------------------
# Protocol resolution
# ---------------------------------------------------------------------------
def approved_protocol(matter_id):
    for protocol in protocols_of_matter(matter_id):
        if protocol["status"] == "APPROVED":
            return protocol
    return None


def effective_protocol(matter_id):
    """The approved protocol, or the most recently approved one if it was
    superseded (a batch can only exist if some protocol was approved)."""
    current = approved_protocol(matter_id)
    if current is not None:
        return current
    approved = [p for p in protocols_of_matter(matter_id) if p["approved_at"] is not None]
    if not approved:
        return None
    approved.sort(key=lambda p: p["revision_number"])
    return approved[-1]


# ---------------------------------------------------------------------------
# Matter derived figures
# ---------------------------------------------------------------------------
def unbatched_document_count(matter):
    carved = sum(b["document_count"] for b in batches_of_matter(matter["id"])
                 if b["status"] != "DISSOLVED")
    return matter["document_count"] - carved


def committed_spend_cents(matter):
    total = 0
    for entry in ledger_of_matter(matter["id"]):
        total += entry["amount_cents"]
    return total


def staffed_reviewer_count(matter):
    matter_id = matter["id"]
    cleared = set(s["reviewer_id"] for s in db.screenings.values()
                  if s["matter_id"] == matter_id and s["status"] == "CLEARED")
    executed = set(a["reviewer_id"] for a in db.agreements.values()
                   if a["matter_id"] == matter_id and a["status"] == "EXECUTED")
    count = 0
    for reviewer_id in cleared & executed:
        reviewer = db.reviewers.get(reviewer_id)
        if reviewer is None:
            continue
        if reviewer["credential_status"] != "VERIFIED":
            continue
        if reviewer["engagement_status"] == "REMOVED":
            continue
        count += 1
    return count


def required_pace_dph(matter):
    remaining_documents = unbatched_document_count(matter)
    for batch in batches_of_matter(matter["id"]):
        if batch["status"] in REMAINING_WORK_BATCH_STATUSES:
            remaining_documents += batch["document_count"]
    if remaining_documents <= 0:
        return Decimal("0.00"), True
    seconds = int((matter["_deadline_dt"] - db.now()).total_seconds())
    if seconds < 0:
        seconds = 0
    remaining_hours = dec(seconds) / dec(3600)
    if remaining_hours == 0:
        return None, True
    effective_reviewers = staffed_reviewer_count(matter)
    if effective_reviewers < MIN_EFFECTIVE_REVIEWERS:
        effective_reviewers = MIN_EFFECTIVE_REVIEWERS
    value = dec(remaining_documents) / (remaining_hours * dec(effective_reviewers))
    return round_half_up(value, 2), True


# ---------------------------------------------------------------------------
# Reviewer derived figures
# ---------------------------------------------------------------------------
def scorecard_strikes(reviewer_id):
    running = 0
    for event in events_of_reviewer(reviewer_id):
        running = max(0, running + event["strike_delta"])
    return running


def accuracy_sample_set(reviewer_id):
    """Samples in PASSED/FAILED whose batch carries a non-VOIDED FIRST_PASS
    assignment for this reviewer (PRD 3.3)."""
    batch_ids = set()
    for assignment in db.assignments.values():
        if assignment["reviewer_id"] != reviewer_id:
            continue
        if assignment["pass_type"] != "FIRST_PASS":
            continue
        if assignment["status"] == "VOIDED":
            continue
        batch_ids.add(assignment["batch_id"])
    samples = [s for s in db.qc_samples.values()
               if s["batch_id"] in batch_ids and s["outcome"] in ("PASSED", "FAILED")]
    return by_creation(samples)


def accuracy_totals(reviewer_id):
    samples = accuracy_sample_set(reviewer_id)
    sampled = sum(s["sampled_document_count"] for s in samples)
    errors = sum(s["coding_error_count"] + s["privilege_error_count"] for s in samples)
    return samples, sampled, errors


def accuracy_score(reviewer_id, weighting="SAMPLE_WEIGHTED"):
    samples, sampled, errors = accuracy_totals(reviewer_id)
    if not samples:
        return Decimal("1.0000")
    if weighting == "ASSIGNMENT_MEAN":
        total = Decimal(0)
        for sample in samples:
            size = sample["sampled_document_count"]
            combined = sample["coding_error_count"] + sample["privilege_error_count"]
            if size <= 0:
                total += Decimal(1)
            else:
                total += Decimal(1) - (dec(combined) / dec(size))
        return round_half_up(total / dec(len(samples)), 4)
    if sampled <= 0:
        return Decimal("1.0000")
    return round_half_up(Decimal(1) - (dec(errors) / dec(sampled)), 4)


def reviewer_pace_dph(reviewer_id):
    documents = 0
    minutes = 0
    found = False
    for assignment in assignments_of_reviewer(reviewer_id):
        if assignment["status"] in ("SUBMITTED", "COMPLETED"):
            found = True
            documents += assignment["documents_coded"]
            minutes += assignment["minutes_logged"]
    if not found or minutes <= 0:
        return Decimal("0.00")
    hours = dec(minutes) / dec(60)
    return round_half_up(dec(documents) / hours, 2)


def active_assignment_count(reviewer_id):
    return len([a for a in db.assignments.values()
                if a["reviewer_id"] == reviewer_id
                and a["status"] in ACTIVE_ASSIGNMENT_STATUSES])


def removal_grounds_met(reviewer_id):
    strikes = scorecard_strikes(reviewer_id)
    if strikes >= REMOVAL_STRIKE_THRESHOLD:
        return True
    _samples, sampled, _errors = accuracy_totals(reviewer_id)
    if sampled >= ACCURACY_FLOOR_MIN_SAMPLED_DOCS:
        if accuracy_score(reviewer_id) < ACCURACY_FLOOR_FOR_REMOVAL:
            return True
    return False


def holds_cleared_and_executed_pair(reviewer_id):
    cleared = set(s["matter_id"] for s in db.screenings.values()
                  if s["reviewer_id"] == reviewer_id and s["status"] == "CLEARED")
    executed = set(a["matter_id"] for a in db.agreements.values()
                   if a["reviewer_id"] == reviewer_id and a["status"] == "EXECUTED")
    return len(cleared & executed) > 0


# ---------------------------------------------------------------------------
# Batch derived figures
# ---------------------------------------------------------------------------
def privilege_entry_count(batch_id):
    return len([e for e in db.privilege_entries.values() if e["batch_id"] == batch_id])


def qc_sample_target_size(batch):
    protocol = effective_protocol(batch["matter_id"])
    if protocol is not None:
        pct = dec(protocol["qc_sample_pct"])
    elif batch.get("_frozen_qc_sample_pct") is not None:
        pct = dec(batch["_frozen_qc_sample_pct"])
    else:
        return QC_MIN_SAMPLE_DOCS
    scaled = ceil_int(dec(batch["document_count"]) * pct)
    return max(QC_MIN_SAMPLE_DOCS, scaled)


def privilege_validation_quota(batch):
    protocol = effective_protocol(batch["matter_id"])
    total = privilege_entry_count(batch["id"])
    if protocol is None:
        return PRIVILEGE_VALIDATION_FLOOR
    scaled = ceil_int(dec(total) * dec(protocol["privilege_sample_pct"]))
    return max(PRIVILEGE_VALIDATION_FLOOR, scaled)


# ---------------------------------------------------------------------------
# Assignment derived figures
# ---------------------------------------------------------------------------
def assignment_pace_dph(assignment):
    if assignment["minutes_logged"] <= 0:
        return Decimal("0.00")
    hours = dec(assignment["minutes_logged"]) / dec(60)
    return round_half_up(dec(assignment["documents_coded"]) / hours, 2)


def assignment_accuracy_pct(assignment):
    samples = [s for s in samples_of_batch(assignment["batch_id"])
               if s["outcome"] in ("PASSED", "FAILED")]
    if not samples:
        return Decimal("1.0000")
    sampled = sum(s["sampled_document_count"] for s in samples)
    errors = sum(s["coding_error_count"] + s["privilege_error_count"] for s in samples)
    if sampled <= 0:
        return Decimal("1.0000")
    return round_half_up(Decimal(1) - (dec(errors) / dec(sampled)), 4)


# ---------------------------------------------------------------------------
# Money calculations
# ---------------------------------------------------------------------------
def language_premium_factor(reviewer, matter):
    shared = set(reviewer["languages"]) & set(matter["required_languages"])
    shared.discard("EN")
    return Decimal(1) + (LANGUAGE_PREMIUM_PER_LANGUAGE * dec(len(shared)))


def effective_per_document_cents(matter, reviewer, pass_type):
    if matter["pricing_model"] != "PER_DOCUMENT":
        return 0
    raw = dec(matter["per_document_rate_cents"])
    raw = raw * COMPLEXITY_TIER_MULTIPLIER[matter["complexity_tier"]]
    raw = raw * language_premium_factor(reviewer, matter)
    raw = raw * PASS_TYPE_MULTIPLIER[pass_type]
    return cents(raw)


def committed_amount_cents(matter, batch, protocol, effective_rate):
    if matter["pricing_model"] == "PER_DOCUMENT":
        return effective_rate * batch["document_count"]
    projected = dec(matter["hourly_rate_cents"]) * dec(batch["document_count"])
    return cents(projected / dec(protocol["min_pace_dph"]))


def billable_minutes_for(minutes_logged):
    blocks = ceil_int(dec(minutes_logged) / dec(HOURLY_INCREMENT_MINUTES))
    return blocks * HOURLY_INCREMENT_MINUTES


def hourly_billable_cents(matter, billable_minutes):
    return cents(dec(matter["hourly_rate_cents"]) * dec(billable_minutes) / dec(60))


def volume_discount_pct(provisional_total_cents):
    if provisional_total_cents < 100000:
        return Decimal("0.00")
    if provisional_total_cents < 250000:
        return Decimal("0.03")
    return Decimal("0.06")


# ---------------------------------------------------------------------------
# Interval helpers (PRD 2.9)
# ---------------------------------------------------------------------------
def coverage_contains(agreement, instant):
    return agreement["_coverage_start_dt"] <= instant <= agreement["_coverage_end_dt"]


def coverage_overlaps(existing, start, end):
    return existing["_coverage_start_dt"] <= end and existing["_coverage_end_dt"] >= start


def window_contains(session, instant):
    return session["_starts_at_dt"] <= instant < session["_ends_at_dt"]


def windows_overlap(existing, start, end):
    return existing["_starts_at_dt"] < end and existing["_ends_at_dt"] > start


def live_agreement(reviewer_id, matter_id):
    """EXECUTED agreement for the pair whose closed coverage holds the clock."""
    now = db.now()
    for agreement in agreements_of_pair(reviewer_id, matter_id):
        if agreement["status"] == "EXECUTED" and coverage_contains(agreement, now):
            return agreement
    return None


def executed_agreement(reviewer_id, matter_id):
    for agreement in agreements_of_pair(reviewer_id, matter_id):
        if agreement["status"] == "EXECUTED":
            return agreement
    return None


def has_cleared_screening(reviewer_id, matter_id):
    for screening in screenings_of_pair(reviewer_id, matter_id):
        if screening["status"] == "CLEARED":
            return True
    return False


def active_session(reviewer_id, matter_id):
    now = db.now()
    for session in sessions_of_pair(reviewer_id, matter_id):
        if session["status"] == "ACTIVE" and window_contains(session, now):
            return session
    return None


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def client_out(client):
    return {
        "id": client["id"],
        "created_at": client["created_at"],
        "updated_at": client["updated_at"],
        "version": client["version"],
        "legal_name": client["legal_name"],
        "primary_state": client["primary_state"],
        "matter_count": len(matters_of_client(client["id"])),
    }


def matter_out(matter):
    pace, _ok = required_pace_dph(matter)
    return {
        "id": matter["id"],
        "created_at": matter["created_at"],
        "updated_at": matter["updated_at"],
        "version": matter["version"],
        "client_id": matter["client_id"],
        "name": matter["name"],
        "document_count": matter["document_count"],
        "unbatched_document_count": unbatched_document_count(matter),
        "deadline_utc": matter["deadline_utc"],
        "complexity_tier": matter["complexity_tier"],
        "required_languages": list(matter["required_languages"]),
        "required_bar_states": list(matter["required_bar_states"]),
        "subject_matter_tags": list(matter["subject_matter_tags"]),
        "pricing_model": matter["pricing_model"],
        "per_document_rate_cents": matter["per_document_rate_cents"],
        "hourly_rate_cents": matter["hourly_rate_cents"],
        "budget_cap_cents": matter["budget_cap_cents"],
        "min_staffed_reviewers": matter["min_staffed_reviewers"],
        "onsite_seat_count": matter["onsite_seat_count"],
        "remote_work_permitted": matter["remote_work_permitted"],
        "status": matter["status"],
        "suspension_reason": matter["suspension_reason"],
        "staffed_reviewer_count": staffed_reviewer_count(matter),
        "committed_spend_cents": committed_spend_cents(matter),
        "required_pace_dph": None if pace is None else num(pace, 2),
    }


def protocol_out(protocol):
    return {
        "id": protocol["id"],
        "created_at": protocol["created_at"],
        "updated_at": protocol["updated_at"],
        "version": protocol["version"],
        "matter_id": protocol["matter_id"],
        "revision_number": protocol["revision_number"],
        "issue_codes": list(protocol["issue_codes"]),
        "privilege_criteria": list(protocol["privilege_criteria"]),
        "qc_sample_pct": protocol["qc_sample_pct"],
        "privilege_sample_pct": protocol["privilege_sample_pct"],
        "max_discrepancy_pct": protocol["max_discrepancy_pct"],
        "min_pace_dph": protocol["min_pace_dph"],
        "second_level_required": protocol["second_level_required"],
        "status": protocol["status"],
        "change_notes": protocol["change_notes"],
        "approved_at": protocol["approved_at"],
    }


def reviewer_out(reviewer):
    return {
        "id": reviewer["id"],
        "created_at": reviewer["created_at"],
        "updated_at": reviewer["updated_at"],
        "version": reviewer["version"],
        "full_name": reviewer["full_name"],
        "bar_admissions": list(reviewer["bar_admissions"]),
        "languages": list(reviewer["languages"]),
        "subject_matter_tags": list(reviewer["subject_matter_tags"]),
        "tier": reviewer["tier"],
        "hourly_cost_cents": reviewer["hourly_cost_cents"],
        "max_concurrent_batches": reviewer["max_concurrent_batches"],
        "remote_work_authorized": reviewer["remote_work_authorized"],
        "credential_status": reviewer["credential_status"],
        "engagement_status": reviewer["engagement_status"],
        "scorecard_strikes": scorecard_strikes(reviewer["id"]),
        "accuracy_score": num(accuracy_score(reviewer["id"]), 4),
        "pace_dph": num(reviewer_pace_dph(reviewer["id"]), 2),
        "active_assignment_count": active_assignment_count(reviewer["id"]),
        "removed_at": reviewer["removed_at"],
    }


def screening_out(screening):
    return {
        "id": screening["id"],
        "created_at": screening["created_at"],
        "updated_at": screening["updated_at"],
        "version": screening["version"],
        "reviewer_id": screening["reviewer_id"],
        "matter_id": screening["matter_id"],
        "declared_adverse_parties": list(screening["declared_adverse_parties"]),
        "status": screening["status"],
        "decision_note": screening["decision_note"],
        "screened_at": screening["screened_at"],
        "waiver_granted": screening["waiver_granted"],
    }


def agreement_out(agreement):
    return {
        "id": agreement["id"],
        "created_at": agreement["created_at"],
        "updated_at": agreement["updated_at"],
        "version": agreement["version"],
        "reviewer_id": agreement["reviewer_id"],
        "matter_id": agreement["matter_id"],
        "coverage_start_utc": agreement["coverage_start_utc"],
        "coverage_end_utc": agreement["coverage_end_utc"],
        "remote_work_addendum": agreement["remote_work_addendum"],
        "status": agreement["status"],
        "executed_at": agreement["executed_at"],
        "signature_name": agreement["signature_name"],
        "revocation_reason": agreement["revocation_reason"],
    }


def session_out(session):
    return {
        "id": session["id"],
        "created_at": session["created_at"],
        "updated_at": session["updated_at"],
        "version": session["version"],
        "reviewer_id": session["reviewer_id"],
        "matter_id": session["matter_id"],
        "workstation_class": session["workstation_class"],
        "starts_at_utc": session["starts_at_utc"],
        "ends_at_utc": session["ends_at_utc"],
        "status": session["status"],
        "activated_at": session["activated_at"],
        "closed_at": session["closed_at"],
    }


def batch_out(batch):
    return {
        "id": batch["id"],
        "created_at": batch["created_at"],
        "updated_at": batch["updated_at"],
        "version": batch["version"],
        "matter_id": batch["matter_id"],
        "batch_number": batch["batch_number"],
        "document_count": batch["document_count"],
        "priority_rank": batch["priority_rank"],
        "status": batch["status"],
        "privilege_entry_count": privilege_entry_count(batch["id"]),
        "qc_sample_target_size": qc_sample_target_size(batch),
        "released_at": batch["released_at"],
    }


def assignment_out(assignment):
    return {
        "id": assignment["id"],
        "created_at": assignment["created_at"],
        "updated_at": assignment["updated_at"],
        "version": assignment["version"],
        "batch_id": assignment["batch_id"],
        "reviewer_id": assignment["reviewer_id"],
        "reassigned_from_assignment_id": assignment["reassigned_from_assignment_id"],
        "pass_type": assignment["pass_type"],
        "status": assignment["status"],
        "documents_coded": assignment["documents_coded"],
        "minutes_logged": assignment["minutes_logged"],
        "privilege_hits_logged": assignment["privilege_hits_logged"],
        "billable_minutes": assignment["billable_minutes"],
        "effective_per_document_cents": assignment["effective_per_document_cents"],
        "committed_amount_cents": assignment["committed_amount_cents"],
        "billable_amount_cents": assignment["billable_amount_cents"],
        "pace_dph": num(assignment_pace_dph(assignment), 2),
        "accuracy_pct": num(assignment_accuracy_pct(assignment), 4),
        "started_at": assignment["started_at"],
        "submitted_at": assignment["submitted_at"],
        "voided_at": assignment["voided_at"],
        "void_reason": assignment["void_reason"],
    }


def qc_sample_out(sample):
    rate = Decimal("0.0000") if sample["outcome"] == "PENDING" else dec(sample["discrepancy_rate"])
    return {
        "id": sample["id"],
        "created_at": sample["created_at"],
        "updated_at": sample["updated_at"],
        "version": sample["version"],
        "batch_id": sample["batch_id"],
        "validated_by_reviewer_id": sample["validated_by_reviewer_id"],
        "sampled_document_count": sample["sampled_document_count"],
        "coding_error_count": sample["coding_error_count"],
        "privilege_error_count": sample["privilege_error_count"],
        "discrepancy_rate": num(rate, 4),
        "outcome": sample["outcome"],
        "validated_at": sample["validated_at"],
    }


def privilege_entry_out(entry):
    return {
        "id": entry["id"],
        "created_at": entry["created_at"],
        "updated_at": entry["updated_at"],
        "version": entry["version"],
        "matter_id": entry["matter_id"],
        "batch_id": entry["batch_id"],
        "authored_by_reviewer_id": entry["authored_by_reviewer_id"],
        "document_ref": entry["document_ref"],
        "privilege_basis": entry["privilege_basis"],
        "disposition": entry["disposition"],
        "status": entry["status"],
        "challenge_note": entry["challenge_note"],
        "validated_at": entry["validated_at"],
    }


def scorecard_event_out(event):
    return {
        "id": event["id"],
        "created_at": event["created_at"],
        "reviewer_id": event["reviewer_id"],
        "event_type": event["event_type"],
        "strike_delta": event["strike_delta"],
        "note": event["note"],
        "source_batch_number": event["source_batch_number"],
    }


def ledger_entry_out(entry):
    return {
        "id": entry["id"],
        "created_at": entry["created_at"],
        "matter_id": entry["matter_id"],
        "assignment_id": entry["assignment_id"],
        "entry_type": entry["entry_type"],
        "amount_cents": entry["amount_cents"],
        "description": entry["description"],
    }
