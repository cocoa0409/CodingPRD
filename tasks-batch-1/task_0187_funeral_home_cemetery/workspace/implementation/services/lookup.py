"""Existence resolution (PRD §2.5, §2.9 priority 3): left-to-right, first miss 404."""
import db
import errors


def funeral_home(home_id):
    h = db.funeral_homes.get(home_id)
    if h is None:
        raise errors.not_found("Funeral home not found")
    return h


def gpl_item(item_id):
    i = db.gpl_items.get(item_id)
    if i is None:
        raise errors.not_found("GPL item not found")
    return i


def case(case_id):
    c = db.cases.get(case_id)
    if c is None:
        raise errors.not_found("Case not found")
    return c


def statement_line(line_id):
    l = db.statement_lines.get(line_id)
    if l is None:
        raise errors.not_found("Statement line not found")
    return l


def contract(contract_id):
    c = db.contracts.get(contract_id)
    if c is None:
        raise errors.not_found("Contract not found")
    return c


def trust_deposit(deposit_id):
    d = db.trust_deposits.get(deposit_id)
    if d is None:
        raise errors.not_found("Trust deposit not found")
    return d


def insurance_assignment(assignment_id):
    a = db.insurance_assignments.get(assignment_id)
    if a is None:
        raise errors.not_found("Insurance assignment not found")
    return a


def plot(plot_id):
    p = db.plots.get(plot_id)
    if p is None:
        raise errors.not_found("Plot not found")
    return p


def venue(venue_id):
    v = db.venues.get(venue_id)
    if v is None:
        raise errors.not_found("Venue not found")
    return v


def event(event_id):
    e = db.events.get(event_id)
    if e is None:
        raise errors.not_found("Event not found")
    return e


def permit(permit_id):
    p = db.permits.get(permit_id)
    if p is None:
        raise errors.not_found("Permit not found")
    return p


def contract_for_case(case_id):
    for c in db.contracts.values():
        if c["case_id"] == case_id:
            return c
    return None
