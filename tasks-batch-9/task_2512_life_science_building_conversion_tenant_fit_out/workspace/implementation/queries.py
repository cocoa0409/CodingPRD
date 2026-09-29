"""Relationship traversals over the in-memory collections.

Relationships are carried by explicit identifier fields (PRD 2.5), so every
traversal here is an ordinary scan filtered on those fields.
"""
import db


def ordered(values):
    return db.ordered(values)


# ------------------------------------------------------------------- building
def floors_of(building_id):
    return ordered(f for f in db.floors.values() if f["building_id"] == building_id)


def floor_by_number(building_id, floor_number):
    for floor in floors_of(building_id):
        if floor["floor_number"] == floor_number:
            return floor
    return None


def scope_items_of(building_id):
    return ordered(i for i in db.scope_items.values() if i["building_id"] == building_id)


def lab_exhaust_item(building_id):
    for item in scope_items_of(building_id):
        if item["discipline"] == "LAB_EXHAUST":
            return item
    return None


def assessments_of(building_id):
    return ordered(a for a in db.assessments.values() if a["building_id"] == building_id)


def amenities_of(building_id):
    return ordered(a for a in db.amenities.values() if a["building_id"] == building_id)


# ---------------------------------------------------------------------- lease
def proposals_of(lease_id):
    return ordered(p for p in db.proposals.values() if p["lease_id"] == lease_id)


def open_proposal(lease_id):
    for proposal in proposals_of(lease_id):
        if proposal["status"] == "OPEN":
            return proposal
    return None


def accepted_proposal(lease_id):
    for proposal in proposals_of(lease_id):
        if proposal["status"] == "ACCEPTED":
            return proposal
    return None


def projects_of_lease(lease_id):
    return ordered(p for p in db.projects.values() if p["lease_id"] == lease_id)


def phases_of_lease(lease_id):
    project_ids = {p["id"] for p in db.projects.values() if p["lease_id"] == lease_id}
    return ordered(p for p in db.phases.values() if p["project_id"] in project_ids)


def permits_of_lease(lease_id):
    project_ids = {p["id"] for p in db.projects.values() if p["lease_id"] == lease_id}
    return ordered(p for p in db.permits.values() if p["project_id"] in project_ids)


def reservations_of_lease(lease_id):
    project_ids = {p["id"] for p in db.projects.values() if p["lease_id"] == lease_id}
    return ordered(r for r in db.reservations.values() if r["project_id"] in project_ids)


# -------------------------------------------------------------------- project
def phases_of_project(project_id):
    return ordered(p for p in db.phases.values() if p["project_id"] == project_id)


def reservations_of_project(project_id):
    return ordered(r for r in db.reservations.values() if r["project_id"] == project_id)


def permits_of_project(project_id):
    return ordered(p for p in db.permits.values() if p["project_id"] == project_id)


def allocations_of_project(project_id):
    return ordered(a for a in db.allocations.values() if a["project_id"] == project_id)


def records_of_project(project_id):
    return ordered(r for r in db.records.values() if r["project_id"] == project_id)


def lease_of_project(project):
    return db.leases.get(project["lease_id"])


def floor_of_project(project):
    return db.floors.get(project["floor_id"])


def building_of_project(project):
    floor = db.floors.get(project["floor_id"])
    if floor is None:
        return None
    return db.buildings.get(floor["building_id"])


def building_of_floor(floor):
    return db.buildings.get(floor["building_id"])


def floor_of_permit(permit):
    return db.floors.get(permit["floor_id"])


# ---------------------------------------------------------------- reservations
def reservations_of_building(building_id):
    return ordered(r for r in db.reservations.values() if r["building_id"] == building_id)


# ------------------------------------------------------------------- amenities
def allocations_of_amenity(amenity_id):
    return ordered(a for a in db.allocations.values() if a["amenity_id"] == amenity_id)


# ----------------------------------------------------------------- phase chain
def direct_successors(phase_id):
    return ordered(p for p in db.phases.values() if p["predecessor_phase_id"] == phase_id)


def transitive_successors(phase_id):
    """Every phase downstream of phase_id through the predecessor chain."""
    found = []
    seen = {phase_id}
    frontier = [phase_id]
    while frontier:
        current = frontier.pop(0)
        for child in direct_successors(current):
            if child["id"] in seen:
                continue
            seen.add(child["id"])
            found.append(child)
            frontier.append(child["id"])
    return db.ordered(found)


# ---------------------------------------------------------------------- lease
def tenant_of_lease(lease):
    return db.tenants.get(lease["tenant_id"])
