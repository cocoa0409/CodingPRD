"""Derived-field reconciliation, the custody ledger and the cascades.

Derived fields are recomputed inside the request that changes their inputs, so
the response body of the triggering request already reflects the new values.
"""

import calc
import store
import util

# ---------------------------------------------------------------------------
# Custody ledger
# ---------------------------------------------------------------------------

def append_custody(election_id, subject_type, subject_id, event_type,
                   from_state, to_state, seal_number, actor_role, actor_user_id):
    stamp = util.now_str()
    sequence_index = len(store.events_of_subject(subject_id)) + 1
    event = {
        "election_id": election_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "event_type": event_type,
        "from_state": from_state,
        "to_state": to_state,
        "seal_number": seal_number,
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "occurred_at": stamp,
        "sequence_index": sequence_index,
    }
    return store.insert("custody_events", event, versioned=False)


def seal_in_use(election_id, seal_number, exclude_lot_id=None, exclude_unit_id=None):
    if seal_number is None:
        return False
    for lot in store.lots_of_election(election_id):
        if lot["id"] == exclude_lot_id:
            continue
        if lot.get("seal_number") == seal_number:
            return True
    for unit in store.units_of_election(election_id):
        if unit["id"] == exclude_unit_id:
            continue
        if unit.get("seal_number") == seal_number:
            return True
    return False


# ---------------------------------------------------------------------------
# Style-level derivations
# ---------------------------------------------------------------------------

def style_contest_count(style):
    codes = set(style["district_codes"])
    total = 0
    for contest in store.contests_of(style["election_id"]):
        if contest["status"] == "CERTIFIED" and contest["district_code"] in codes:
            total += 1
    return total


def recompute_style_contest_count(style):
    return store.setf(style, contest_count=style_contest_count(style))


def recompute_style_precinct_count(style):
    count = sum(1 for p in store.precincts_of(style["election_id"])
                if p["assigned_style_id"] == style["id"])
    return store.setf(style, precinct_count=count)


def recompute_rotation_seeds(election_id):
    """rotation_seed_index is the style's 0-based rank among the election's
    non-superseded styles ordered by style_code ascending."""
    live = [s for s in store.styles_of(election_id) if s["status"] != "SUPERSEDED"]
    live.sort(key=lambda s: (s["style_code"], s["created_at"], s["_seq"]))
    for index, style in enumerate(live):
        store.setf(style, rotation_seed_index=index)


def styles_covering(election_id, district_code):
    return [s for s in store.styles_of(election_id)
            if district_code in s["district_codes"]]


# ---------------------------------------------------------------------------
# Vendor derivations
# ---------------------------------------------------------------------------

ACTIVE_JOB_STATUSES = ("PROOF_PENDING", "PRINTING", "QC_HOLD", "QC_PASSED", "DELIVERED")


def recompute_vendor_active_jobs(vendor):
    if vendor is None:
        return False
    count = sum(1 for j in store.jobs_of_vendor(vendor["id"])
                if j["status"] in ACTIVE_JOB_STATUSES)
    return store.setf(vendor, active_job_count=count)


def recompute_vendor_defect_rate(vendor):
    if vendor is None:
        return False
    defects = 0
    samples = 0
    for job in store.jobs_of_vendor(vendor["id"]):
        if (job.get("inspection_count") or 0) >= 1:
            defects += job.get("defect_count") or 0
            samples += job.get("sample_size") or 0
    rate = util.round_half_up(defects * 10000, samples) if samples > 0 else 0
    return store.setf(vendor, quality_defect_rate_bp=rate)


# ---------------------------------------------------------------------------
# Precinct / election readiness propagation
# ---------------------------------------------------------------------------

def recompute_precinct(precinct):
    received = calc.precinct_ballots_received(precinct["id"])
    status = calc.precinct_deployment_status(precinct, received)
    return store.setf(precinct, ballots_received=received, deployment_status=status)


def recompute_readiness(election):
    precincts = store.precincts_of(election["id"])
    for precinct in precincts:
        recompute_precinct(precinct)
    ready = bool(precincts) and all(p["deployment_status"] == "READY" for p in precincts)
    return store.setf(election, deployment_readiness="READY" if ready else "BLOCKED")


def recompute_election_totals(election, skip_issued=False):
    received = 0
    issued = 0
    for lot in store.lots_of_election(election["id"]):
        if lot["custody_state"] in ("RECEIVED", "ISSUED", "RETURNED"):
            received += lot["quantity_received"] or 0
        if lot["custody_state"] in ("ISSUED", "RETURNED"):
            issued += lot["issued_quantity"] or 0
    changes = {"total_ballots_received": received}
    if not skip_issued:
        changes["total_ballots_issued"] = issued
    return store.setf(election, **changes)


def recompute_committed_print(election):
    total = 0
    for job in store.jobs_of_election(election["id"]):
        if job["status"] in ("PRINTING", "QC_HOLD", "QC_PASSED", "DELIVERED"):
            total += job.get("invoice_total_cents") or 0
    return store.setf(election, committed_print_cents=total)


def recompute_open_seals(election):
    applied = 0
    broken = 0
    for event in store.events_of_election(election["id"]):
        if event["event_type"] in ("SEAL_APPLIED", "RETENTION_SEAL"):
            applied += 1
        elif event["event_type"] == "SEAL_BROKEN":
            broken += 1
    return store.setf(election, open_seal_count=applied - broken)


def recompute_certified_contest_count(election):
    count = sum(1 for c in store.contests_of(election["id"]) if c["status"] == "CERTIFIED")
    return store.setf(election, certified_contest_count=count)


def sync_election(election, skip_issued=False):
    """Re-derive every derived field the election row carries."""
    if election is None:
        return
    recompute_certified_contest_count(election)
    recompute_committed_print(election)
    recompute_open_seals(election)
    recompute_election_totals(election, skip_issued=skip_issued)
    recompute_readiness(election)


# ---------------------------------------------------------------------------
# base_order_index assignment (CERTIFIED_BASIS)
# ---------------------------------------------------------------------------

def assign_base_order(contest, election):
    roster = calc.ordered_candidates(contest, election, "CERTIFIED_BASIS")
    for index, candidate in enumerate(roster):
        store.setf(candidate, base_order_index=index)


def recompute_certified_candidate_count(contest):
    count = sum(1 for c in store.candidates_of(contest["id"]) if c["status"] == "CERTIFIED")
    return store.setf(contest, certified_candidate_count=count)


# ---------------------------------------------------------------------------
# Deck voiding
# ---------------------------------------------------------------------------

def void_decks_of_style(style):
    for deck in store.decks_of_style(style["id"]):
        if deck["status"] in ("DRAFT", "SEALED"):
            store.setf(deck, status="VOIDED")


# ---------------------------------------------------------------------------
# Lot voiding / job rejection
# ---------------------------------------------------------------------------

def void_lot(lot, actor_role, actor_user_id):
    from_state = lot["custody_state"]
    if from_state not in ("IN_TRANSIT", "RECEIVED", "ISSUED"):
        return None
    lot["custody_state"] = "VOIDED"
    lot["issued_quantity"] = 0
    lot["unused_quantity"] = lot["quantity_received"] or 0
    lot["precinct_id"] = None
    lot["issued_by_user_id"] = None
    store.touch(lot)
    # A lot is only ever voided by a cascade (a rejected print job), never by a
    # direct call, so the ledger line is attributed to the system.
    append_custody(lot["election_id"], "BALLOT_LOT", lot["id"], "VOID",
                   from_state, "VOIDED", lot.get("seal_number"),
                   actor_role, "system")
    return lot


def reject_job(job, actor_role, actor_user_id):
    """A print job whose style left the approved set is pulled back."""
    if job["status"] not in ACTIVE_JOB_STATUSES:
        return
    job["status"] = "REJECTED"
    job["invoice_subtotal_cents"] = 0
    job["defect_credit_cents"] = 0
    job["freight_cents"] = 0
    job["invoice_total_cents"] = 0
    store.touch(job)
    for lot in store.lots_of_job(job["id"]):
        void_lot(lot, actor_role, actor_user_id)
    recompute_vendor_active_jobs(store.get("print_vendors", job["vendor_id"]))


# ---------------------------------------------------------------------------
# Cascade: contest withdrawal (depth 5)
# ---------------------------------------------------------------------------

def cascade_contest_withdrawn(contest, election, actor_role, actor_user_id):
    # Hop 2 -- the ballot styles that printed the contest.
    affected = []
    for style in styles_covering(election["id"], contest["district_code"]):
        if style["status"] in ("PROOFING", "APPROVED", "LOCKED"):
            style["status"] = "PROOF_REJECTED"
            style["contest_count"] = style_contest_count(style)
            style["translated_languages"] = []
            style["certified_formats"] = []
            store.touch(style)
            affected.append(style)
    # Hop 3 -- the print jobs on those styles.
    for style in affected:
        for job in store.jobs_of_style(style["id"]):
            reject_job(job, actor_role, actor_user_id)
    # Every test deck of a style rejected in hop 2.
    for style in affected:
        void_decks_of_style(style)
    # Hops 4 and 5 land through the derived-field propagation.
    sync_election(election)


# ---------------------------------------------------------------------------
# Cascade: candidate disqualification (depth 3)
# ---------------------------------------------------------------------------

def cascade_candidate_disqualified(candidate, contest, election):
    if election["status"] != "SETUP":
        assign_base_order(contest, election)
    for style in styles_covering(election["id"], contest["district_code"]):
        for deck in store.decks_of_style(style["id"]):
            if deck["status"] in ("DRAFT", "SEALED"):
                store.setf(deck, status="VOIDED")
    # A deck that references the candidate directly is voided even when its
    # style does not cover the contest's district.
    for deck in store.DB["test_decks"].values():
        if deck["status"] not in ("DRAFT", "SEALED"):
            continue
        style = store.get("ballot_styles", deck["style_id"])
        if style is None or style["election_id"] != election["id"]:
            continue
        for mark in deck["expected_marks"]:
            if mark["candidate_id"] == candidate["id"]:
                store.setf(deck, status="VOIDED")
                break


# ---------------------------------------------------------------------------
# Cascade: ballot style supersession
# ---------------------------------------------------------------------------

def cascade_style_superseded(old_style, new_style, actor_role, actor_user_id):
    store.setf(old_style, status="SUPERSEDED")
    for precinct in store.precincts_of(old_style["election_id"]):
        if precinct["assigned_style_id"] == old_style["id"]:
            store.setf(precinct, assigned_style_id=new_style["id"])
    recompute_style_precinct_count(old_style)
    recompute_style_precinct_count(new_style)
    recompute_rotation_seeds(old_style["election_id"])
    for job in store.jobs_of_style(old_style["id"]):
        if job["status"] == "PROOF_PENDING":
            reject_job(job, actor_role, actor_user_id)
    void_decks_of_style(old_style)


# ---------------------------------------------------------------------------
# Cascade: logic-and-accuracy failure (depth 4)
# ---------------------------------------------------------------------------

def cascade_la_failure(session, unit, deck, election, actor_role, actor_user_id):
    if deck["status"] == "SEALED":
        store.setf(deck, status="VOIDED")
    changes = {"program_status": "LA_FAILED"}
    if unit["custody_status"] == "DEPLOYED":
        append_custody(election["id"], "TABULATOR_UNIT", unit["id"], "SEAL_BROKEN",
                       "DEPLOYED", "IN_VAULT", unit.get("seal_number"),
                       actor_role, "system")
        changes["custody_status"] = "IN_VAULT"
        changes["seal_number"] = None
        changes["precinct_id"] = None
    store.setf(unit, **changes)
    sync_election(election)
