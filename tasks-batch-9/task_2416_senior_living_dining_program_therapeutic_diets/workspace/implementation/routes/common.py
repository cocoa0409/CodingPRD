"""Shared lookup helpers -- PRD 2.6 tiers 4 and 5."""
from constants import ALL_ROLES
from db import db
from errors import api_error

EVERY_ROLE = list(ALL_ROLES)
OPERATORS = [r for r in ALL_ROLES if r != "ResidentRepresentative"]

PA = "ProgramAdministrator"
CS = "ClinicalStaff"
RD = "RegisteredDietitian"
DSM = "DiningServicesManager"
SKL = "SatelliteKitchenLead"
BS = "BillingSpecialist"
RR = "ResidentRepresentative"


def _lookup(collection, row_id, error_id, label):
    row = collection.get(row_id)
    if row is None:
        raise api_error(error_id, "%s %s was not found" % (label, row_id))
    return row


def get_community(row_id):
    return _lookup(db.communities, row_id, "ERR_COMMUNITY_NOT_FOUND", "Community")


def get_venue(row_id):
    return _lookup(db.venues, row_id, "ERR_VENUE_NOT_FOUND", "DiningVenue")


def get_resident(row_id):
    return _lookup(db.residents, row_id, "ERR_RESIDENT_NOT_FOUND", "Resident")


def get_diet_order(row_id):
    return _lookup(db.diet_orders, row_id, "ERR_DIET_ORDER_NOT_FOUND", "DietOrder")


def get_reservation(row_id):
    return _lookup(db.reservations, row_id, "ERR_RESERVATION_NOT_FOUND", "SeatingReservation")


def get_menu_cycle(row_id):
    return _lookup(db.menu_cycles, row_id, "ERR_MENU_CYCLE_NOT_FOUND", "MenuCycle")


def get_menu_item(row_id):
    return _lookup(db.menu_items, row_id, "ERR_MENU_ITEM_NOT_FOUND", "MenuItem")


def get_extension(row_id):
    return _lookup(db.extensions, row_id, "ERR_EXTENSION_NOT_FOUND", "TherapeuticExtension")


def get_ticket(row_id):
    return _lookup(db.tickets, row_id, "ERR_TICKET_NOT_FOUND", "MealServiceTicket")


def get_reconciliation(row_id):
    return _lookup(db.reconciliations, row_id, "ERR_RECONCILIATION_NOT_FOUND", "BillingReconciliation")


def get_review(row_id):
    return _lookup(db.reviews, row_id, "ERR_REVIEW_NOT_FOUND", "PlanOfCareReview")


def get_observation(row_id):
    return _lookup(db.observations, row_id, "ERR_OBSERVATION_NOT_FOUND", "IntakeObservation")
