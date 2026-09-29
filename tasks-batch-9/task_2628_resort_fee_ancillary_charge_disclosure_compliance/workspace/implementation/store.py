"""In-memory data store. Dicts keyed by id. No seeding whatsoever."""

import uuid

import clock

jurisdictions = {}
taxability_rules = {}
properties = {}
channels = {}
fee_programs = {}
fees = {}
fee_inclusions = {}
profiles = {}
bookings = {}
folios = {}
folio_lines = {}
opt_out_requests = {}
complaints = {}
inquiries = {}
revenue_models = {}

_ALL = [
    jurisdictions, taxability_rules, properties, channels, fee_programs, fees,
    fee_inclusions, profiles, bookings, folios, folio_lines, opt_out_requests,
    complaints, inquiries, revenue_models,
]

_seq = {"n": 0}


def reset():
    for table in _ALL:
        table.clear()
    _seq["n"] = 0
    clock.reset()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    """Monotonic insertion counter used as the id tiebreaker for stable ordering."""
    _seq["n"] += 1
    return _seq["n"]


def stamp_new(row, versioned=True):
    """Attach the common system fields to a freshly created row."""
    row["id"] = new_id()
    row["created_at"] = clock.now()
    row["_seq"] = next_seq()
    if versioned:
        row["updated_at"] = clock.now()
        row["version"] = 1
    return row


def touch(row):
    """Record a mutation of a row that carries updated_at / version."""
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        row["updated_at"] = clock.now()
    return row


def sort_default(rows):
    """created_at ASC, then id ASC (PRD 2.3)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["id"]))


def sort_created(rows):
    """created_at ASC with insertion order as the deterministic tiebreaker."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------- lookups

def fees_of_program(program_id):
    return sort_created([f for f in fees.values() if f["fee_program_id"] == program_id])


def mandatory_fees_of_program(program_id):
    return [f for f in fees_of_program(program_id) if f["classification"] == "MANDATORY"]


def inclusions_of_fee(fee_id):
    return sort_created([i for i in fee_inclusions.values() if i["fee_id"] == fee_id])


def programs_of_property(property_id):
    return sort_created([p for p in fee_programs.values() if p["property_id"] == property_id])


def profiles_of_property(property_id):
    return sort_created([p for p in profiles.values() if p["property_id"] == property_id])


def bookings_of_property(property_id):
    return sort_created([b for b in bookings.values() if b["property_id"] == property_id])


def folio_of_booking(booking_id):
    matches = sort_created([f for f in folios.values() if f["booking_id"] == booking_id])
    return matches[0] if matches else None


def folios_of_booking(booking_id):
    return sort_created([f for f in folios.values() if f["booking_id"] == booking_id])


def lines_of_folio(folio_id):
    rows = [l for l in folio_lines.values() if l["folio_id"] == folio_id]
    return sorted(rows, key=lambda l: l["sequence_no"])


def opt_outs_of_booking(booking_id):
    return sort_created([o for o in opt_out_requests.values() if o["booking_id"] == booking_id])


def complaints_of_booking(booking_id):
    return sort_created([c for c in complaints.values() if c["booking_id"] == booking_id])


def inquiries_of_property(property_id):
    return sort_created([i for i in inquiries.values() if i["property_id"] == property_id])


def taxability_rule(jurisdiction_id, fee_code):
    for rule in taxability_rules.values():
        if rule["jurisdiction_id"] == jurisdiction_id and rule["fee_code"] == fee_code:
            return rule
    return None
