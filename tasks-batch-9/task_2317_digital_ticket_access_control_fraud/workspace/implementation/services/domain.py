"""Cross-cutting domain services: lookups, audit trail, zone posture,
fraud-score recomputation and the denied-entry / listing-suspension cascade."""

from db import base_record, db, public, sort_created_asc, touch
from errors import ApiError
from util import iso_clock, new_seed
from services import calc


# ----------------------------------------------------------------------
# Lookups
# ----------------------------------------------------------------------

def get_or_404(collection, resource_id, error_id):
    record = collection.get(resource_id)
    if record is None:
        raise ApiError(error_id)
    return record


def find_ticket_by_seed(seed_part):
    for ticket in db.tickets.values():
        if ticket["barcode_seed"] == seed_part:
            return ticket
    return None


def event_of(record):
    return db.events.get(record.get("event_id") or record.get("_event_id"))


def zones_of_event(event_id):
    return sort_created_asc([z for z in db.zones.values() if z["event_id"] == event_id])


def gates_of_event(event_id):
    return sort_created_asc([g for g in db.gates.values() if g["event_id"] == event_id])


def tickets_of_event(event_id):
    return sort_created_asc([t for t in db.tickets.values() if t["event_id"] == event_id])


def scan_events_of_event(event_id):
    return [se for se in db.scan_events.values() if se["_event_id"] == event_id]


def scan_events_of_session(session_id):
    return [se for se in db.scan_events.values() if se["scan_session_id"] == session_id]


def sessions_of_gate(gate_id):
    return sort_created_asc([s for s in db.sessions.values() if s["gate_id"] == gate_id])


def listings_of_ticket(ticket_id):
    return sort_created_asc([l for l in db.listings.values() if l["ticket_id"] == ticket_id])


def incidents_of_patron(patron_id):
    return sort_created_asc([i for i in db.incidents.values() if i["patron_id"] == patron_id])


# ----------------------------------------------------------------------
# Audit trail (PRD 3.1)
# ----------------------------------------------------------------------

def append_audit(event_id, subject_type, subject_id, action, actor_role, actor_user_id, detail):
    entry = base_record(versioned=False)
    entry["event_id"] = event_id
    entry["subject_type"] = subject_type
    entry["subject_id"] = subject_id
    entry["action"] = action
    entry["actor_role"] = actor_role
    entry["actor_user_id"] = actor_user_id
    entry["occurred_at"] = iso_clock(db.clock)
    entry["detail"] = detail
    db.audit_entries[entry["id"]] = entry
    return entry


# ----------------------------------------------------------------------
# Zone posture / counters
# ----------------------------------------------------------------------

def recompute_zone_posture(zone):
    zone["posture"] = calc.zone_posture(zone["issued_entitlement_count"], zone["fire_code_capacity"])
    return zone["posture"]


# ----------------------------------------------------------------------
# Fraud score
# ----------------------------------------------------------------------

def recompute_fraud_score(patron, variant):
    incidents = incidents_of_patron(patron["id"])
    patron["fraud_risk_score"] = calc.patron_fraud_risk_score(patron, incidents, variant)
    patron["fraud_risk_basis"] = variant
    return patron["fraud_risk_score"]


def suspend_listings_of_seller(patron, actor_role, actor_user_id, skip_ticket_id=None):
    """Cascade links 3 and 4: suspend every LISTED listing of this seller and
    revert each affected ticket to ISSUED unless that ticket is being voided."""
    listings = sort_created_asc(
        [l for l in db.listings.values() if l["seller_patron_id"] == patron["id"] and l["status"] == "LISTED"]
    )
    for listing in listings:
        listing["status"] = "SUSPENDED"
        touch(listing)
        ticket = db.tickets.get(listing["ticket_id"])
        event_id = ticket["event_id"] if ticket else None
        append_audit(
            event_id,
            "RESALE_LISTING",
            listing["id"],
            "RESALE_LISTING_SUSPENDED",
            actor_role,
            actor_user_id,
            "Resale listing %s suspended; seller %s fraud_risk_score %s"
            % (listing["id"], patron["id"], patron["fraud_risk_score"]),
        )
        if ticket is not None and ticket["id"] != skip_ticket_id and ticket["lifecycle_status"] == "LISTED":
            ticket["lifecycle_status"] = "ISSUED"
            touch(ticket)
    return listings


def open_denied_entry_incident(scan_event_id, ticket, category, event_id, actor_role, actor_user_id):
    """Cascade link 1-4 of PRD 3.7: incident, strike, provisional rescore,
    listing suspension, ticket revert."""
    patron = None
    if ticket is not None and ticket.get("holder_patron_id"):
        patron = db.patrons.get(ticket["holder_patron_id"])

    incident = base_record()
    incident["scan_event_id"] = scan_event_id
    incident["ticket_id"] = ticket["id"] if ticket is not None else None
    incident["patron_id"] = patron["id"] if patron is not None else None
    incident["category"] = category
    incident["status"] = "OPEN"
    incident["reviewer_user_id"] = None
    incident["resolution_note"] = None
    incident["remediation_credit_cents"] = None
    incident["_event_id"] = event_id
    db.incidents[incident["id"]] = incident

    if patron is not None:
        patron["strike_count"] += 1
        recompute_fraud_score(patron, "PROVISIONAL")
        touch(patron)
        if patron["fraud_risk_score"] >= calc.FRAUD_BLOCK_THRESHOLD:
            suspend_listings_of_seller(patron, actor_role, actor_user_id)
    return incident


# ----------------------------------------------------------------------
# Ticket minting (direct issuance and the credential-approval cascade)
# ----------------------------------------------------------------------

def create_ticket_record(event_id, access_zone_id, holder_patron_id, ticket_type,
                         face_value_cents, credential_request_id=None):
    """Mints a Ticket row. Counter movements are the caller's responsibility."""
    ticket = base_record()
    ticket["event_id"] = event_id
    ticket["access_zone_id"] = access_zone_id
    ticket["holder_patron_id"] = holder_patron_id
    ticket["credential_request_id"] = credential_request_id
    ticket["ticket_type"] = ticket_type
    ticket["face_value_cents"] = face_value_cents
    ticket["barcode_seed"] = new_seed()
    ticket["lifecycle_status"] = "ISSUED"
    ticket["admission_status"] = "NOT_ADMITTED"
    ticket["transfer_count"] = 0
    ticket["bound_device_fingerprint"] = None
    ticket["device_binding_status"] = "UNBOUND"
    ticket["last_admitted_at"] = None
    ticket["last_exited_at"] = None
    ticket["admitted_scan_count"] = 0
    ticket["_last_admitted_dt"] = None
    ticket["_last_exited_dt"] = None
    db.tickets[ticket["id"]] = ticket
    return ticket


# ----------------------------------------------------------------------
# Serialization
# ----------------------------------------------------------------------

def serialize(record):
    return public(record)


def serialize_all(records):
    return [public(r) for r in records]
