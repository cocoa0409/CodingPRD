"""Shared cross-aggregate helpers."""

import db
from errors import not_found


def get_farm_or_404(farm_id):
    farm = db.farms.get(farm_id)
    if farm is None:
        raise not_found(f"Farm {farm_id} not found")
    return farm


def get_producer_or_404(producer_id):
    producer = db.producers.get(producer_id)
    if producer is None:
        raise not_found(f"Producer {producer_id} not found")
    return producer


def get_tract_or_404(tract_id):
    tract = db.tracts.get(tract_id)
    if tract is None:
        raise not_found(f"Tract {tract_id} not found")
    return tract


def get_field_or_404(field_id):
    field = db.fields.get(field_id)
    if field is None:
        raise not_found(f"Field {field_id} not found")
    return field


def get_membership_or_404(membership_id):
    m = db.memberships.get(membership_id)
    if m is None:
        raise not_found(f"FarmMembership {membership_id} not found")
    return m


def get_report_or_404(report_id):
    r = db.acreage_reports.get(report_id)
    if r is None:
        raise not_found(f"AcreageReport {report_id} not found")
    return r


def get_election_or_404(election_id):
    e = db.program_elections.get(election_id)
    if e is None:
        raise not_found(f"ProgramElection {election_id} not found")
    return e


def get_yield_record_or_404(record_id):
    y = db.yield_records.get(record_id)
    if y is None:
        raise not_found(f"YieldRecord {record_id} not found")
    return y


def get_enrollment_or_404(enrollment_id):
    e = db.enrollments.get(enrollment_id)
    if e is None:
        raise not_found(f"Enrollment {enrollment_id} not found")
    return e


def get_disaster_app_or_404(app_id):
    a = db.disaster_applications.get(app_id)
    if a is None:
        raise not_found(f"DisasterApplication {app_id} not found")
    return a


def get_appeal_or_404(appeal_id):
    a = db.appeals.get(appeal_id)
    if a is None:
        raise not_found(f"Appeal {appeal_id} not found")
    return a


def get_recon_or_404(recon_id):
    r = db.reconstitutions.get(recon_id)
    if r is None:
        raise not_found(f"Reconstitution {recon_id} not found")
    return r


def active_membership(farm_id, producer_id):
    """Return the ACTIVE FarmMembership for (farm, producer) or None."""
    for m in db.memberships.values():
        if (m["farm_id"] == farm_id
                and m["producer_id"] == producer_id
                and m["membership_status"] == "ACTIVE"):
            return m
    return None


def recompute_farm_base_acres(farm):
    """Farm.total_base_acres = sum of base acres across the farm's tracts."""
    total = 0.0
    for t in db.tracts.values():
        if t["farm_id"] == farm["id"] and t["tract_status"] == "ACTIVE":
            total += float(t["base_acres"])
    farm["total_base_acres"] = round(total, 2)
    return farm["total_base_acres"]


def certified_report_for(farm_id, program_year):
    for r in db.acreage_reports.values():
        if (r["farm_id"] == farm_id
                and r["program_year"] == program_year
                and r["report_status"] == "CERTIFIED"):
            return r
    return None


def active_election_for(farm_id, program_year, commodity):
    for e in db.program_elections.values():
        if (e["farm_id"] == farm_id
                and e["program_year"] == program_year
                and e["commodity"] == commodity
                and e["election_status"] == "ACTIVE"):
            return e
    return None


def yield_record_for(farm_id, commodity):
    """The current yield record for (farm, commodity): prefer non-LOCKED
    latest; otherwise the latest created."""
    records = [
        y for y in db.yield_records.values()
        if y["farm_id"] == farm_id and y["commodity"] == commodity
    ]
    if not records:
        return None
    records.sort(key=lambda y: y["created_at"])
    return records[-1]


def enrollment_references_election(election_id):
    """Any enrollment that pinned this election in CERTIFIED-or-beyond state."""
    beyond = ("CERTIFIED", "PAYMENT_COMPUTED", "PAYMENT_ISSUED", "ON_APPEAL", "REMANDED")
    for e in db.enrollments.values():
        if e.get("pinned_election_id") == election_id and e["enrollment_status"] in beyond:
            return e
    return None


def has_open_appeal_or_disaster(farm_id):
    """Open (non-terminal) appeal or disaster application on the farm."""
    for a in db.appeals.values():
        if a["farm_id"] == farm_id and a["appeal_status"] in (
                "FILED", "CED_REVIEW", "COMMITTEE_HEARING", "REMANDED"):
            return True
    for d in db.disaster_applications.values():
        if d["farm_id"] == farm_id and d["application_status"] in (
                "DRAFT", "FILED", "UNDER_REVIEW"):
            return True
    return False
