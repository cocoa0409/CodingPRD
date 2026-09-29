"""Deterministic multi-entity cascades (PRD 3.5 - 3.9).

None of these functions touches a derived counter: every counter in this system
is re-derived at read time from the child rows, which is what makes the
create/cancel and open/void pairs exactly compensating (PRD 2.10).
"""

from datetime import timedelta

import calc
from store import db, new_row, ordered, touch

CANDIDATE_TERMINAL = ("EXCLUDED", "CLOSED")
SEARCH_TERMINAL = ("NO_MATCH_FOUND", "FULFILLED")
SEARCH_BLOCKED = ("NO_MATCH_FOUND", "FULFILLED", "STALLED")


# ---------------------------------------------------------------- lookups ----
def candidate_of(case):
    return db.candidates.get(case["match_candidate_id"])


def search_of_candidate(candidate):
    return db.searches.get(candidate["search_request_id"])


def donor_of_candidate(candidate):
    return db.donors.get(candidate["donor_id"])


def registry_of_donor(donor):
    return db.registries.get(donor["registry_id"])


def patient_of_search(search):
    return db.patients.get(search["patient_id"])


def patient_of_case(case):
    candidate = candidate_of(case)
    if candidate is None:
        return None
    search = search_of_candidate(candidate)
    if search is None:
        return None
    return patient_of_search(search)


def case_bookings(case_id):
    return ordered([b for b in db.bookings.values()
                    if b["workup_case_id"] == case_id])


def case_clearance_items(case_id):
    return ordered([c for c in db.clearance_items.values()
                    if c["workup_case_id"] == case_id])


def clearance_item(case_id, item_type):
    for item in case_clearance_items(case_id):
        if item["item_type"] == item_type:
            return item
    return None


def booking_shipments(booking_id):
    return ordered([s for s in db.shipments.values()
                    if s["collection_booking_id"] == booking_id])


def case_shipments(case_id):
    rows = []
    for booking in case_bookings(case_id):
        rows.extend(booking_shipments(booking["id"]))
    return ordered(rows)


def open_case_of_patient(patient_id):
    """The patient's OPEN workup case, reached through search -> candidate."""
    for case in ordered(list(db.workup_cases.values())):
        if case["case_status"] != "OPEN":
            continue
        if patient_of_case(case) is not None and \
                patient_of_case(case)["id"] == patient_id:
            return case
    return None


def cases_of_patient(patient_id):
    rows = []
    for case in ordered(list(db.workup_cases.values())):
        holder = patient_of_case(case)
        if holder is not None and holder["id"] == patient_id:
            rows.append(case)
    return rows


def candidate_typing_requests(candidate_id):
    return ordered([t for t in db.typing_requests.values()
                    if t["match_candidate_id"] == candidate_id])


def search_typing_requests(search_id):
    rows = []
    for candidate in ordered([c for c in db.candidates.values()
                              if c["search_request_id"] == search_id]):
        rows.extend(candidate_typing_requests(candidate["id"]))
    return ordered(rows)


def search_candidates(search_id):
    return ordered([c for c in db.candidates.values()
                    if c["search_request_id"] == search_id])


# ------------------------------------------------------- calendar windows ----
def create_window(donor, date_from, date_to, reason, source_booking_id=None):
    row = new_row(
        donor_id=donor["id"],
        source_booking_id=source_booking_id,
        date_from=date_from,
        date_to=date_to,
        reason=reason,
        day_count=calc.day_count(date_from, date_to),
        status="ACTIVE",
        released_at=None,
    )
    db.windows[row["id"]] = row
    return row


def active_windows(donor_id):
    return ordered([w for w in db.windows.values()
                    if w["donor_id"] == donor_id and w["status"] == "ACTIVE"])


def release_window(window):
    window["status"] = "RELEASED"
    window["released_at"] = db.now()
    touch(window)
    return window


def release_booking_windows(booking):
    for window in ordered(list(db.windows.values())):
        if window["source_booking_id"] == booking["id"] and \
                window["status"] == "ACTIVE":
            release_window(window)


def defer_donor_temporarily(donor, until_date):
    """AVAILABLE -> TEMPORARILY_DEFERRED with an ACTIVE DEFERRAL window."""
    donor["availability_status"] = "TEMPORARILY_DEFERRED"
    donor["deferral_until"] = until_date
    touch(donor)
    create_window(donor, db.today(), until_date, "DEFERRAL")


# ------------------------------------------------------ promotion cascade ----
def promotable_backups(search_id):
    rows = []
    for candidate in search_candidates(search_id):
        if candidate["candidate_role"] != "BACKUP":
            continue
        if candidate["status"] == "IDENTIFIED":
            rows.append(candidate)
        elif candidate["status"] == "TYPING_EXPIRED" and \
                candidate["ct_attempt_count"] < calc.MAX_CT_ATTEMPTS:
            rows.append(candidate)
    return rows


def promote_backup(search, outgoing):
    """Lift the promotable BACKUP holding the smallest rank_position.

    Never re-ranks anything and never refills the vacated backup slot.
    """
    pool = promotable_backups(search["id"])
    if not pool:
        return None
    winner = min(pool, key=lambda c: c["rank_position"])
    winner["candidate_role"] = "PRIMARY"
    winner["promoted_from_rank"] = winner["rank_position"]
    touch(winner)
    if outgoing is not None and outgoing["candidate_role"] == "PRIMARY":
        outgoing["candidate_role"] = "ARCHIVED_POOL"
        touch(outgoing)
    return winner


def primary_lost(search, outgoing):
    """The single entry point for every loss of a search's primary."""
    if search is None:
        return None
    promoted = promote_backup(search, outgoing)
    if search["status"] in ("SEARCHING", "PRIMARY_ENGAGED", "WORKUP_ACTIVE"):
        search["status"] = "BACKUP_REQUIRED"
        touch(search)
    return promoted


def candidate_alive(candidate):
    if candidate["status"] in CANDIDATE_TERMINAL:
        return False
    if candidate["status"] == "DEFERRED":
        return False
    if candidate["status"] == "TYPING_EXPIRED" and \
            candidate["ct_attempt_count"] >= calc.MAX_CT_ATTEMPTS:
        return False
    return True


def stall_if_unpromotable(search):
    """PRD 3.4: no live PRIMARY and no promotable backup leaves the search STALLED."""
    if search["status"] in SEARCH_BLOCKED:
        return
    for candidate in search_candidates(search["id"]):
        if candidate["candidate_role"] == "PRIMARY" and candidate_alive(candidate):
            return
    if promotable_backups(search["id"]):
        return
    search["status"] = "STALLED"
    touch(search)


# ------------------------------------------------- permanent deferral reach ----
def exclude_donor_candidates(donor, skip_candidate_id=None):
    """A permanent deferral reaches sideways across every search (PRD 3.5)."""
    for candidate in ordered(list(db.candidates.values())):
        if candidate["donor_id"] != donor["id"]:
            continue
        if candidate["id"] == skip_candidate_id:
            continue
        if candidate["status"] in CANDIDATE_TERMINAL:
            continue
        candidate["status"] = "EXCLUDED"
        touch(candidate)
        cancel_open_typing_requests(candidate)


def cancel_open_typing_requests(candidate):
    for request in candidate_typing_requests(candidate["id"]):
        if request["status"] == "REQUESTED":
            request["status"] = "CANCELLED"
            touch(request)


# ------------------------------------------------ clearance re-derivation ----
def rederive_clearance_status(case):
    items = case_clearance_items(case["id"])
    results = [item["result"] for item in items]
    if "FAIL" in results:
        new_status = "FAILED"
    elif results and all(result == "PASS" for result in results):
        new_status = "CLEARED"
    elif "PASS" in results:
        new_status = "IN_PROGRESS"
    else:
        new_status = "PENDING"
    if case["clearance_status"] != new_status:
        case["clearance_status"] = new_status
        touch(case)
    return new_status


def refresh_idm_resulted_at(case):
    item = clearance_item(case["id"], "IDM_PANEL")
    value = None
    if item is not None and item["result"] == "PASS":
        value = item["resulted_at"]
    if case["idm_resulted_at"] != value:
        case["idm_resulted_at"] = value
        touch(case)


# ------------------------------------------------------------- bookings ------
def cancel_booking(booking, reason):
    booking["status"] = "CANCELLED"
    booking["cancel_reason"] = reason
    touch(booking)
    release_booking_windows(booking)


def revert_logistics_when_unbooked(case):
    for booking in case_bookings(case["id"]):
        if booking["status"] in ("HELD", "CONFIRMED"):
            return
    if case["logistics_status"] == "BOOKED":
        case["logistics_status"] = "METHOD_SET"
        touch(case)


def void_provisional_claims(case, reason):
    for claim in ordered(list(db.claims.values())):
        if claim["workup_case_id"] == case["id"] and \
                claim["status"] == "PROVISIONAL":
            claim["status"] = "VOID"
            claim["void_reason"] = reason
            touch(claim)


# ---------------------------------------------- failing clearance cascade ----
CLEARANCE_FAIL_REASON = "CLEARANCE_FAILED"


def clearance_fail_cascade(case, item):
    """PRD 3.6: the deepest cascade, identical whichever item failed."""
    case["case_status"] = "ABORTED"
    case["abort_reason"] = CLEARANCE_FAIL_REASON
    touch(case)

    candidate = candidate_of(case)
    donor = donor_of_candidate(candidate) if candidate else None
    if item["item_type"] in ("PHYSICAL_EXAM", "IDM_PANEL") and donor is not None:
        if donor["availability_status"] == "AVAILABLE":
            until = db.today() + timedelta(days=calc.CLEARANCE_FAIL_DEFERRAL_DAYS)
            defer_donor_temporarily(donor, until)

    if candidate is not None:
        candidate["status"] = "DEFERRED"
        touch(candidate)

    void_provisional_claims(case, CLEARANCE_FAIL_REASON)

    if candidate is not None:
        search = search_of_candidate(candidate)
        if candidate["candidate_role"] == "PRIMARY":
            primary_lost(search, candidate)
        elif search is not None and search["status"] == "WORKUP_ACTIVE":
            search["status"] = "BACKUP_REQUIRED"
            touch(search)


# --------------------------------------------- conditioning abort cascade ----
CONDITIONING_ABORT_REASON = "CONDITIONING_ABORTED"
CONDITIONING_RESCHEDULE_REASON = "CONDITIONING_RESCHEDULED"


def conditioning_abort_cascade(patient, reason):
    """PRD 3.8: the widest cascade; identical from SCHEDULED or from STARTED."""
    case = open_case_of_patient(patient["id"])
    search = None
    candidate = None
    if case is not None:
        candidate = candidate_of(case)
        if candidate is not None:
            search = search_of_candidate(candidate)
    else:
        for row in ordered(list(db.searches.values())):
            if row["patient_id"] == patient["id"] and \
                    row["status"] not in SEARCH_TERMINAL:
                search = row

    if case is not None:
        for booking in case_bookings(case["id"]):
            if booking["status"] in ("HELD", "CONFIRMED"):
                cancel_booking(booking, CONDITIONING_ABORT_REASON)
        for shipment in case_shipments(case["id"]):
            if shipment["status"] == "SCHEDULED":
                shipment["status"] = "CANCELLED"
                touch(shipment)

    if search is not None:
        for request in search_typing_requests(search["id"]):
            if request["status"] == "REQUESTED":
                request["status"] = "CANCELLED"
                touch(request)

    if case is not None:
        case["case_status"] = "ABORTED"
        case["abort_reason"] = CONDITIONING_ABORT_REASON
        touch(case)
        void_provisional_claims(case, CONDITIONING_ABORT_REASON)

    if candidate is not None and candidate["status"] in ("WORKUP_OPEN", "COLLECTED"):
        candidate["status"] = "CLOSED"
        touch(candidate)

    if search is not None and search["status"] not in SEARCH_TERMINAL:
        if search["status"] != "STALLED":
            search["status"] = "STALLED"
            touch(search)
