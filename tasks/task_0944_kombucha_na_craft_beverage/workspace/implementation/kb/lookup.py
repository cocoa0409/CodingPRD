"""Existence resolution and the three not-found families (PRD 2.7)."""

from .errors import ApiError
from .store import db

PRODUCTION = "ERR_PRODUCTION_RESOURCE_NOT_FOUND"
PACKAGING = "ERR_PACKAGING_RESOURCE_NOT_FOUND"
COMMERCIAL = "ERR_COMMERCIAL_RESOURCE_NOT_FOUND"


def _get(mapping, identifier, error_id, label):
    if not isinstance(identifier, str) or not identifier:
        raise ApiError(error_id, "%s not found." % label)
    record = mapping.get(identifier)
    if record is None:
        raise ApiError(error_id, "%s not found." % label)
    return record


def recipe(identifier):
    return _get(db.recipes, identifier, PRODUCTION, "Recipe")


def label_approval(identifier):
    return _get(db.label_approvals, identifier, PRODUCTION, "LabelApproval")


def scoby_culture(identifier):
    return _get(db.scoby_cultures, identifier, PRODUCTION, "ScobyCulture")


def vessel(identifier):
    return _get(db.vessels, identifier, PRODUCTION, "Vessel")


def ingredient_lot(identifier):
    return _get(db.ingredient_lots, identifier, PRODUCTION, "IngredientLot")


def batch(identifier):
    return _get(db.batches, identifier, PRODUCTION, "Batch")


def batch_ingredient_use(identifier):
    return _get(
        db.batch_ingredient_uses, identifier, PRODUCTION, "BatchIngredientUse"
    )


def packaging_run(identifier):
    return _get(db.packaging_runs, identifier, PACKAGING, "PackagingRun")


def finished_lot(identifier):
    return _get(db.finished_lots, identifier, PACKAGING, "FinishedLot")


def keg(identifier):
    return _get(db.kegs, identifier, PACKAGING, "Keg")


def account(identifier):
    return _get(db.accounts, identifier, COMMERCIAL, "Account")


def shipment(identifier):
    return _get(db.shipments, identifier, COMMERCIAL, "Shipment")


def subscription(identifier):
    return _get(db.subscriptions, identifier, COMMERCIAL, "Subscription")


def subscription_allocation(identifier):
    return _get(
        db.subscription_allocations, identifier, COMMERCIAL, "SubscriptionAllocation"
    )


def taproom_fill(identifier):
    return _get(db.taproom_fills, identifier, COMMERCIAL, "TaproomFill")


def recall_notice(identifier):
    return _get(db.recall_notices, identifier, COMMERCIAL, "RecallNotice")
