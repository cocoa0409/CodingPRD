"""Ladder helpers: existence, per-row state, OCC, party and floor gates.

Each helper corresponds to one rung of the global precedence ladder in
PRD 2.11; callers invoke them in the ladder's order.
"""
import calc
from db import db
from errors import ApiError


def _find(store, row_id, error_id, label):
    if not isinstance(row_id, str) or row_id not in store:
        raise ApiError(error_id, "%s not found" % label)
    return store[row_id]


def get_venue_contract(row_id):
    return _find(db.venue_contracts, row_id, "ERR_VENUE_CONTRACT_NOT_FOUND", "venue contract")


def get_show(row_id):
    return _find(db.shows, row_id, "ERR_SHOW_NOT_FOUND", "show")


def get_exhibitor(row_id):
    return _find(db.exhibitors, row_id, "ERR_EXHIBITOR_NOT_FOUND", "exhibitor")


def get_booth(row_id):
    return _find(db.booths, row_id, "ERR_BOOTH_NOT_FOUND", "booth")


def get_contract(row_id):
    return _find(db.space_contracts, row_id, "ERR_SPACE_CONTRACT_NOT_FOUND", "space contract")


def get_appointment(row_id):
    return _find(db.selection_appointments, row_id, "ERR_APPOINTMENT_NOT_FOUND",
                 "selection appointment")


def get_package(row_id):
    return _find(db.sponsorship_packages, row_id, "ERR_SPONSORSHIP_PACKAGE_NOT_FOUND",
                 "sponsorship package")


def get_deal(row_id):
    return _find(db.sponsorship_deals, row_id, "ERR_SPONSORSHIP_DEAL_NOT_FOUND",
                 "sponsorship deal")


def get_registration(row_id):
    return _find(db.registrations, row_id, "ERR_REGISTRATION_NOT_FOUND", "registration")


def get_violation(row_id):
    return _find(db.rule_violations, row_id, "ERR_RULE_VIOLATION_NOT_FOUND", "rule violation")


def get_obligation(deal, row_id):
    """The nested path is the identity: a real obligation under the wrong
    deal is a 404, not a 422 (PRD 2.10)."""
    obligation = db.fulfillment_obligations.get(row_id) if isinstance(row_id, str) else None
    if obligation is None or obligation["sponsorship_deal_id"] != deal["id"]:
        raise ApiError("ERR_OBLIGATION_NOT_FOUND", "fulfillment obligation not found")
    return obligation


def get_booths(booth_ids):
    return [get_booth(booth_id) for booth_id in booth_ids]


# ------------------------------------------------------------------- state
def require_venue_executed(venue_contract):
    if venue_contract["status"] != "EXECUTED":
        raise ApiError("ERR_VENUE_CONTRACT_NOT_EXECUTED",
                       "the venue contract is not EXECUTED")


def require_venue_draft(venue_contract):
    if venue_contract["status"] != "DRAFT":
        raise ApiError("ERR_VENUE_CONTRACT_NOT_DRAFT", "the venue contract is not DRAFT")


def require_show_status(show, allowed):
    if show["status"] not in allowed:
        raise ApiError("ERR_INVALID_SHOW_STATUS",
                       "show status %s does not allow this operation" % show["status"])


def require_show_closed(show):
    if show["status"] != "CLOSED":
        raise ApiError("ERR_SHOW_NOT_CLOSED", "the show is not CLOSED")


def require_contract_status(contract, allowed):
    if contract["status"] not in allowed:
        raise ApiError("ERR_INVALID_CONTRACT_STATUS",
                       "contract status %s does not allow this operation" % contract["status"])


def require_appointment_state(appointment, allowed):
    if appointment["state"] not in allowed:
        raise ApiError("ERR_INVALID_APPOINTMENT_STATE",
                       "appointment state %s does not allow this operation"
                       % appointment["state"])


def require_deal_status(deal, allowed):
    if deal["deal_status"] not in allowed:
        raise ApiError("ERR_INVALID_DEAL_STATUS",
                       "deal status %s does not allow this operation" % deal["deal_status"])


def require_obligation_pending(obligation):
    if obligation["status"] != "PENDING":
        raise ApiError("ERR_OBLIGATION_ALREADY_RESOLVED",
                       "the obligation is already resolved")


def require_violation_open(violation):
    if violation["status"] != "OPEN":
        raise ApiError("ERR_VIOLATION_ALREADY_ADJUDICATED",
                       "the citation has already been adjudicated")


def reject_merged_booths(booths):
    for booth in booths:
        if booth["status"] == "MERGED" or booth["combined_parent_booth_id"] is not None:
            raise ApiError("ERR_BOOTH_MERGED", "booth %s has been merged away"
                           % booth["booth_number"])


# --------------------------------------------------------------------- OCC
def check_show_version(show, expected, error_id="ERR_STALE_SHOW_VERSION"):
    if expected is None:
        return
    if expected != show["version"]:
        raise ApiError(error_id, "the show has changed since version %s" % expected)


def check_venue_version(venue_contract, expected):
    if expected is None:
        return
    if expected != venue_contract["version"]:
        raise ApiError("ERR_STALE_VENUE_CONTRACT_VERSION",
                       "the venue contract has changed since version %s" % expected)


# ------------------------------------------------------------ party and floor
def require_exhibitor_active(exhibitor):
    if exhibitor["status"] != "ACTIVE":
        raise ApiError("ERR_EXHIBITOR_SUSPENDED", "the exhibitor is SUSPENDED")


def reject_frozen_floor(show):
    if calc.floor_posture(show) == "FROZEN":
        raise ApiError("ERR_SHOW_FLOOR_FROZEN", "the show floor is FROZEN")


def require_open_floor(show):
    posture = calc.floor_posture(show)
    if posture != "OPEN":
        raise ApiError("ERR_SHOW_FLOOR_SPACE_LOCKED",
                       "the show floor is %s where OPEN is required" % posture)


def require_booths_in_show(booths, show_id, error_id="ERR_BOOTH_NOT_IN_SHOW"):
    for booth in booths:
        if booth["show_id"] != show_id:
            raise ApiError(error_id, "booth %s belongs to another show" % booth["booth_number"])


def require_booths_available(booths, contract_id=None):
    for booth in booths:
        if booth["status"] == "AVAILABLE":
            continue
        if contract_id is not None and booth["space_contract_id"] == contract_id:
            continue
        raise ApiError("ERR_BOOTH_NOT_AVAILABLE",
                       "booth %s is not available" % booth["booth_number"])


def reject_duplicate_active_contract(show_id, exhibitor_id):
    for contract in db.space_contracts.values():
        if (contract["show_id"] == show_id
                and contract["exhibitor_id"] == exhibitor_id
                and contract["status"] in calc.ACTIVE_CONTRACT_STATUSES):
            raise ApiError("ERR_DUPLICATE_ACTIVE_CONTRACT",
                           "this exhibitor already holds an active contract on this show")
