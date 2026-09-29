"""Derived counters and aggregates (PRD section 2.7).

Every aggregate the PRD describes as "recomputed from its contributing rows"
is computed here on demand, so it is always consistent with the rows that feed
it.  Only the two monotonic incident counters (staffing_gap_count,
unseated_guest_count) and the stamped money snapshots are stored.
"""

from calc import credential_status, planned_minutes
from store import db, sort_rows

OPEN_ELEMENT_STATUSES = ("PLANNED", "PERMIT_BLOCKED", "READY")
VENUE_OCCUPYING_STATUSES = ("PLANNED", "PERMIT_BLOCKED", "READY", "DELIVERED")
STAFF_OCCUPYING_STATUSES = ("CONFIRMED", "CHECKED_IN", "COMPLETED")
SEAT_OCCUPYING_STATUSES = ("ASSIGNED", "CHECKED_IN")
BLOCKING_PERMIT_STATUSES = ("DRAFT", "SUBMITTED", "CONDITIONS_REQUESTED", "DENIED")
SETTLED_PAYMENT_STATUSES = ("APPROVED", "PAID")


# --------------------------------------------------------------------------
# collections
# --------------------------------------------------------------------------

def elements_of_program(program_id):
    return sort_rows([e for e in db.elements.values() if e["program_id"] == program_id])


def all_elements():
    return sort_rows(list(db.elements.values()))


def elements_of_venue(venue_id):
    return sort_rows([e for e in db.elements.values() if e.get("venue_id") == venue_id])


def segments_of_program(program_id):
    return sort_rows([s for s in db.segments.values() if s["program_id"] == program_id])


def entries_of_segment(segment_id):
    return sort_rows([m for m in db.manifest_entries.values() if m["segment_id"] == segment_id])


def permits_of_element(element_id):
    return sort_rows([p for p in db.permits.values() if p["element_id"] == element_id])


def lines_of_program(program_id):
    return sort_rows([l for l in db.recon_lines.values() if l["program_id"] == program_id])


def assignments_of_element(element_id):
    return sort_rows([a for a in db.staff_assignments.values()
                      if a.get("element_id") == element_id])


def assignments_of_segment(segment_id):
    return sort_rows([a for a in db.staff_assignments.values()
                      if a.get("segment_id") == segment_id])


def assignments_of_staff(staff_id):
    return sort_rows([a for a in db.staff_assignments.values() if a["staff_id"] == staff_id])


def assignments_of_program(program_id):
    return sort_rows([a for a in db.staff_assignments.values() if a["program_id"] == program_id])


def contracts_of_program(program_id):
    return sort_rows([c for c in db.contracts.values() if c["program_id"] == program_id])


def payments_of_program(program_id):
    return sort_rows([p for p in db.settlements.values() if p["program_id"] == program_id])


def payments_of_contract(contract_id):
    return sort_rows([p for p in db.settlements.values() if p["contract_id"] == contract_id])


# --------------------------------------------------------------------------
# program aggregates
# --------------------------------------------------------------------------

def element_count(program_id):
    return len(elements_of_program(program_id))


def open_element_count(program_id):
    return len([e for e in elements_of_program(program_id)
                if e["status"] in OPEN_ELEMENT_STATUSES])


def actual_attendance_total(program_id):
    total = 0
    for element in elements_of_program(program_id):
        if element["status"] == "DELIVERED" and element.get("actual_headcount") is not None:
            total += int(element["actual_headcount"])
    return total


def booked_seat_count(segment_id):
    total = 0
    for entry in entries_of_segment(segment_id):
        if entry["status"] in SEAT_OCCUPYING_STATUSES:
            total += int(entry["seat_count"])
    return total


def seated_guest_count(program_id):
    return sum(booked_seat_count(s["id"]) for s in segments_of_program(program_id))


def approved_lines(program_id):
    return [l for l in lines_of_program(program_id) if l["status"] == "APPROVED"]


def final_subtotal_cents(program_id):
    return sum(int(l["supplier_cost_cents"]) for l in approved_lines(program_id))


def disclosed_markup_cents(program_id):
    return sum(int(l["markup_cents"]) for l in approved_lines(program_id))


def supplier_gross_payable_cents(program_id):
    return final_subtotal_cents(program_id)


def supplier_settled_cents(program_id):
    return sum(int(p["net_payable_cents"]) for p in payments_of_program(program_id)
               if p["status"] in SETTLED_PAYMENT_STATUSES)


def supplier_open_payable_cents(program_id):
    return supplier_gross_payable_cents(program_id) - supplier_settled_cents(program_id)


def confirmed_minutes_total(staff_id):
    total = 0
    for assignment in assignments_of_staff(staff_id):
        if assignment["status"] in STAFF_OCCUPYING_STATUSES:
            total += planned_minutes(assignment)
    return total


def staff_credential_status(member):
    return credential_status(member)


# --------------------------------------------------------------------------
# helpers over permits and contracts
# --------------------------------------------------------------------------

def element_has_blocking_permit(element_id):
    return any(p["status"] in BLOCKING_PERMIT_STATUSES for p in permits_of_element(element_id))


def element_has_approved_special_venue_permit(element_id):
    return any(p["permit_type"] == "SPECIAL_VENUE" and p["status"] == "APPROVED"
               for p in permits_of_element(element_id))


def active_contract_for(program_id, supplier_id):
    for contract in contracts_of_program(program_id):
        if contract["supplier_id"] == supplier_id and contract["status"] == "ACTIVE":
            return contract
    return None


_TIER_RANK = {"ACTIVE": 0, "TERMINATED": 1, "COUNTERED": 2, "SENT": 3}


def governing_contract(program_id, supplier_id):
    """Contract whose cancellation schedule governs an element (PRD section 3.7)."""
    candidates = [c for c in contracts_of_program(program_id)
                  if c["supplier_id"] == supplier_id and c["status"] in _TIER_RANK]
    if not candidates:
        return None
    candidates.sort(key=lambda c: (_TIER_RANK[c["status"]],
                                   -c["created_at"].timestamp(),
                                   -c["_seq"]))
    return candidates[0]


def cancellation_tier_for(element):
    contract = governing_contract(element["program_id"], element["supplier_id"])
    if contract is None:
        return "STANDARD"
    return contract["cancellation_tier"]
