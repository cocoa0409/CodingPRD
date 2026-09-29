"""Cascades, waitlist promotion and the checkpoint sweep (PRD 3.10)."""

import datetime

import calc
import store

UNAUTHORIZED_STATUSES = ("AUTHORIZATION_SUSPENDED", "UNAUTHORIZED")


def _client_of(matter):
    return store.get("clients", matter.get("client_id"))


def recompute_client(client):
    from routes.core import recompute_client as impl
    return impl(client)


# --------------------------------------------------------------------------
# matter creation from an accepted screening
# --------------------------------------------------------------------------

def create_matter_for_screening(screening, pool, principal_matter_id=None):
    case_type = screening["case_type"]
    row = store.new_row({
        "client_id": screening["client_id"],
        "intake_id": screening["id"],
        "cycle_id": screening["cycle_id"],
        "principal_matter_id": principal_matter_id,
        "facility_id": screening.get("facility_id"),
        "case_type": case_type,
        "forum": calc.FORUM_BY_CASE_TYPE[case_type],
        "detained": bool(screening.get("detained")),
        "representation_status": "UNSTAFFED",
        "filing_status": "PRE_FILING",
        "slot_pool_consumed": pool,
        "statutory_deadline_date": screening.get("statutory_deadline_date"),
        "expedited_deadline_date": None,
        "effective_filing_deadline_date": None,
        "readiness_index_weighted": store.rhu(0, 4),
        "readiness_ready_strict": False,
        "evidence_blocking_count": 0,
        "readiness_gate_applied": None,
        "interpretation_cost_cents": 0,
        "direct_hours_logged": store.rhu(0, 2),
        "supervision_hours_logged": store.rhu(0, 2),
        "coverage_gap_flag": False,
        "outcome": None,
        "outcome_recorded_at_utc": None,
        "closed_at_utc": None,
    })
    calc.recompute_matter_deadlines(row)
    store.insert("matters", row)
    return row


# --------------------------------------------------------------------------
# waitlist ranking and promotion
# --------------------------------------------------------------------------

def cycle_screenings(cycle_id):
    return sorted(
        [s for s in store.db["screenings"].values() if s.get("cycle_id") == cycle_id],
        key=store.order_key,
    )


def rerank_waitlist(cycle_id):
    waiting = [s for s in cycle_screenings(cycle_id) if s.get("status") == "WAITLISTED"]
    for index, screening in enumerate(waiting, start=1):
        if screening.get("waitlist_rank") != index:
            screening["waitlist_rank"] = index
            store.touch(screening)


def next_waitlist_rank(cycle_id):
    return 1 + sum(1 for s in store.db["screenings"].values()
                   if s.get("cycle_id") == cycle_id and s.get("status") == "WAITLISTED")


def is_promotable(screening, cycle):
    if screening.get("status") != "WAITLISTED":
        return False
    expires = store.parse_dt(screening.get("waitlist_expires_at_utc"))
    if expires is None or store.clock_dt() >= expires:
        return False
    posture = calc.effective_posture(cycle)
    if posture not in ("OPEN", "RESTRICTED"):
        return False
    if posture == "RESTRICTED" and screening.get("urgency_tier") not in ("URGENT", "EMERGENCY"):
        return False
    if calc.resolve_pool(cycle, bool(screening.get("detained"))) is None:
        return False
    return True


def promote_screening(screening, cycle, bump_cycle=True):
    """Shared promotion side effects (PRD 3.4)."""
    pool = calc.resolve_pool(cycle, bool(screening.get("detained")))
    screening["status"] = "ACCEPTED"
    screening["decision_reason_code"] = "ACCEPTED_ON_MERIT"
    screening["decided_at_utc"] = store.clock_iso()
    screening["waitlist_rank"] = None
    screening["waitlist_expires_at_utc"] = None
    store.touch(screening)
    matter = create_matter_for_screening(screening, pool)
    calc.recompute_cycle(cycle, bump=bump_cycle)
    rerank_waitlist(cycle["id"])
    client = _client_of(matter)
    if client is not None:
        recompute_client(client)
    return matter


def promote_next(cycle, bump_cycle=True):
    candidates = [s for s in cycle_screenings(cycle["id"]) if is_promotable(s, cycle)]
    if not candidates:
        return None
    candidates.sort(key=lambda s: (int(s.get("waitlist_rank") or 10 ** 9),
                                   store.order_key(s)))
    return promote_screening(candidates[0], cycle, bump_cycle=bump_cycle)


def promote_loop(cycle, bump_cycle=True):
    promoted = []
    guard = 0
    while guard < 1000:
        guard += 1
        matter = promote_next(cycle, bump_cycle=bump_cycle)
        if matter is None:
            break
        promoted.append(matter)
    return promoted


# --------------------------------------------------------------------------
# assignment release helpers
# --------------------------------------------------------------------------

def release_assignment(assignment, reason, terminal=True):
    assignment["status"] = "RELEASED" if terminal else "SUSPENDED"
    assignment["release_reason_code"] = reason
    if terminal:
        assignment["released_at_utc"] = store.clock_iso()
    store.touch(assignment)


def refresh_reps(rep_ids):
    for rep_id in rep_ids:
        rep = store.get("representatives", rep_id)
        if rep is not None:
            calc.recompute_rep_counters(rep)


def refresh_matters(matter_ids):
    for matter_id in matter_ids:
        matter = store.get("matters", matter_id)
        if matter is not None:
            calc.recompute_representation_status(matter)


def supervisor_rep_ids(assignment):
    """The representative behind an assignment's supervision link, if any."""
    link_id = assignment.get("supervision_link_id")
    if not link_id:
        return []
    link = store.get("assignments", link_id)
    if link is None:
        return []
    return [link.get("representative_id")]


def release_representative_authority(rep_id):
    """Accreditation REVOKE side effect (PRD 3.5)."""
    touched_reps = {rep_id}
    touched_matters = set()
    for assignment in calc.rep_assignments(rep_id):
        if assignment.get("status") not in ("PROPOSED", "ACTIVE"):
            continue
        release_assignment(assignment, "AUTHORIZATION_REVOKED", terminal=True)
        touched_matters.add(assignment.get("matter_id"))
        touched_reps.update(supervisor_rep_ids(assignment))
    refresh_reps(touched_reps)
    refresh_matters(touched_matters)


def suspend_unauthorized_assignments(rep, reason):
    """Move a now-unauthorized representative's ACTIVE assignments to SUSPENDED."""
    touched_reps = {rep["id"]}
    touched_matters = set()
    for assignment in calc.rep_assignments(rep["id"]):
        if assignment.get("status") != "ACTIVE":
            continue
        release_assignment(assignment, reason, terminal=False)
        touched_matters.add(assignment.get("matter_id"))
        touched_reps.update(supervisor_rep_ids(assignment))
    refresh_reps(touched_reps)
    return touched_matters


# --------------------------------------------------------------------------
# cascade A -- recognition LAPSE (PRD 3.10)
# --------------------------------------------------------------------------

def recognition_accreditations(recognition_id):
    return sorted(
        [a for a in store.db["accreditations"].values()
         if a.get("recognition_id") == recognition_id],
        key=store.order_key,
    )


def recognition_lapse(recognition):
    # hop 0
    recognition["status"] = "LAPSED"
    recognition["lapsed_at_utc"] = store.clock_iso()
    recognition["conditional_reason_code"] = None

    # hop 1
    affected_reps = []
    for accreditation in recognition_accreditations(recognition["id"]):
        if accreditation.get("status") in calc.QUALIFYING_ACCREDITATION_STATUSES:
            accreditation["status"] = "SUSPENDED_BY_RECOGNITION"
            accreditation["decision_reason_code"] = "RECOGNITION_LAPSE"
            store.touch(accreditation)
            rep_id = accreditation.get("representative_id")
            if rep_id not in affected_reps:
                affected_reps.append(rep_id)
    recognition["suspended_accreditation_count"] = sum(
        1 for a in recognition_accreditations(recognition["id"])
        if a.get("status") == "SUSPENDED_BY_RECOGNITION")
    store.touch(recognition)

    # hop 2
    gap_matters = set()
    for rep_id in affected_reps:
        rep = store.get("representatives", rep_id)
        if rep is None:
            continue
        if calc.authorization_status(rep) == "AUTHORIZATION_SUSPENDED":
            gap_matters |= suspend_unauthorized_assignments(rep, "RECOGNITION_LAPSE")

    # hop 3
    coverage = []
    for matter_id in sorted(gap_matters):
        matter = store.get("matters", matter_id)
        if matter is None:
            continue
        calc.recompute_representation_status(matter)
        if matter.get("representation_status") == "COVERAGE_GAP":
            coverage.append(matter)

    # hop 4
    horizon = store.clock_dt() + datetime.timedelta(days=14)
    for matter in sorted(coverage, key=store.order_key):
        for declaration in sorted(store.db["declarations"].values(), key=store.order_key):
            if declaration.get("matter_id") != matter["id"]:
                continue
            if declaration.get("status") != "IN_REVIEW":
                continue
            declaration["status"] = "REVISION_REQUESTED"
            declaration["revision_reason_code"] = "SUPERVISION_REQUIRED"
            declaration["revision_round"] = int(declaration.get("revision_round") or 0) + 1
            store.touch(declaration)
        for event in sorted(store.db["events"].values(), key=store.order_key):
            if event.get("matter_id") != matter["id"]:
                continue
            if event.get("status") not in calc.EVENT_ACTIVE_STATUSES:
                continue
            starts = store.parse_dt(event.get("starts_at_utc"))
            if starts is None or starts < store.clock_dt() or starts > horizon:
                continue
            if event.get("coverage_gap_flag"):
                continue
            event["coverage_gap_flag"] = True
            store.touch(event)
    return recognition


def recognition_reinstate(recognition):
    """Partial compensation after a LAPSE (PRD 3.10)."""
    affected_reps = []
    for accreditation in recognition_accreditations(recognition["id"]):
        if accreditation.get("status") != "SUSPENDED_BY_RECOGNITION":
            continue
        expiry = store.parse_date(accreditation.get("expiry_date"))
        if expiry is not None and expiry >= store.clock_date():
            accreditation["status"] = "APPROVED"
        else:
            accreditation["status"] = "EXPIRED"
        store.touch(accreditation)
        rep_id = accreditation.get("representative_id")
        if rep_id not in affected_reps:
            affected_reps.append(rep_id)
    recognition["suspended_accreditation_count"] = sum(
        1 for a in recognition_accreditations(recognition["id"])
        if a.get("status") == "SUSPENDED_BY_RECOGNITION")

    touched_matters = set()
    touched_supervisors = set()
    for rep_id in affected_reps:
        rep = store.get("representatives", rep_id)
        if rep is None:
            continue
        if calc.authorization_status(rep) in UNAUTHORIZED_STATUSES:
            continue
        for assignment in calc.rep_assignments(rep_id):
            if assignment.get("status") != "SUSPENDED":
                continue
            if assignment.get("release_reason_code") != "RECOGNITION_LAPSE":
                continue
            assignment["status"] = "ACTIVE"
            assignment["release_reason_code"] = None
            store.touch(assignment)
            touched_matters.add(assignment.get("matter_id"))
            # A revived assignment counts against its supervisor again, and PRD 2.6
            # holds that "supervisee_count equals the count of assignments whose
            # status is ACTIVE and whose supervision_link_id is non-null".
            touched_supervisors.update(supervisor_rep_ids(assignment))
        calc.recompute_rep_counters(rep)
    refresh_reps({a.get("representative_id") for a in
                  recognition_accreditations(recognition["id"])})
    refresh_reps(sorted(rid for rid in touched_supervisors if rid))
    refresh_matters(sorted(touched_matters))
    return recognition


# --------------------------------------------------------------------------
# cascade B -- withdrawal of an accepted screening (PRD 3.10)
# --------------------------------------------------------------------------

def matter_for_screening(screening_id):
    for matter in sorted(store.db["matters"].values(), key=store.order_key):
        if matter.get("intake_id") == screening_id:
            return matter
    return None


def close_matter_assignments(matter, reason):
    touched_reps = set()
    for assignment in calc.matter_assignments(matter["id"]):
        if assignment.get("status") not in ("PROPOSED", "ACTIVE", "SUSPENDED"):
            continue
        release_assignment(assignment, reason, terminal=True)
        touched_reps.add(assignment.get("representative_id"))
        touched_reps.update(supervisor_rep_ids(assignment))
    refresh_reps(touched_reps)


def withdraw_accepted_screening(screening):
    matter = matter_for_screening(screening["id"])
    if matter is None:
        return None
    # hop 1
    matter["representation_status"] = "WITHDRAWN_FROM"
    matter["filing_status"] = "CLOSED_NO_FILING"
    matter["outcome"] = "WITHDRAWN"
    matter["outcome_recorded_at_utc"] = store.clock_iso()
    matter["closed_at_utc"] = store.clock_iso()
    store.touch(matter)
    # hop 2
    close_matter_assignments(matter, "CLIENT_WITHDREW")
    # hop 3
    cycle = store.get("cycles", matter.get("cycle_id"))
    if cycle is not None:
        calc.recompute_cycle(cycle)
    client = _client_of(matter)
    if client is not None:
        recompute_client(client)
    # hop 4
    if cycle is not None:
        promote_next(cycle)
    return matter


# --------------------------------------------------------------------------
# checkpoint sweep (PRD 3.10)
# --------------------------------------------------------------------------

def _expire_waitlist(cycle):
    now = store.clock_dt()
    changed = False
    for screening in cycle_screenings(cycle["id"]):
        if screening.get("status") != "WAITLISTED":
            continue
        expires = store.parse_dt(screening.get("waitlist_expires_at_utc"))
        if expires is None or now < expires:
            continue
        screening["status"] = "WAITLIST_EXPIRED"
        screening["waitlist_rank"] = None
        store.touch(screening)
        changed = True
    if changed:
        rerank_waitlist(cycle["id"])
    return changed


def _age_credentials():
    today = store.clock_date()
    accreditations = sorted(store.db["accreditations"].values(), key=store.order_key)
    for accreditation in accreditations:
        if accreditation.get("status") != "APPROVED":
            continue
        expiry = store.parse_date(accreditation.get("expiry_date"))
        if expiry is None or expiry < today:
            continue
        if (expiry - today).days <= calc.ACCREDITATION_EXPIRING_WINDOW_DAYS:
            accreditation["status"] = "EXPIRING"
            store.touch(accreditation)

    affected_reps = []
    for accreditation in accreditations:
        if accreditation.get("status") not in ("APPROVED", "EXPIRING", "RENEWAL_PENDING",
                                              "SUSPENDED_BY_RECOGNITION"):
            continue
        expiry = store.parse_date(accreditation.get("expiry_date"))
        if expiry is None or today <= expiry:
            continue
        accreditation["status"] = "EXPIRED"
        store.touch(accreditation)
        rep_id = accreditation.get("representative_id")
        if rep_id not in affected_reps:
            affected_reps.append(rep_id)

    touched_matters = set()
    for rep_id in affected_reps:
        rep = store.get("representatives", rep_id)
        if rep is None:
            continue
        if calc.authorization_status(rep) in UNAUTHORIZED_STATUSES:
            touched_matters |= suspend_unauthorized_assignments(rep, "AUTHORIZATION_REVOKED")
    refresh_matters(sorted(touched_matters))


def run_checkpoint(cycle):
    _expire_waitlist(cycle)
    promote_loop(cycle, bump_cycle=False)
    _age_credentials()
    calc.recompute_cycle(cycle, bump=False)
    cycle["checkpoint_epoch"] = int(cycle.get("checkpoint_epoch") or 0) + 1
    cycle["last_checkpoint_utc"] = store.clock_iso()
    store.touch(cycle)
    return cycle
