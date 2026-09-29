"""Path and body foreign-key resolution — PRD 2.6 error vocabulary."""
import errors
from db import db


def model_or_404(model_id):
    row = db.models.get(model_id)
    if row is None:
        raise errors.model_not_found(model_id)
    return row


def dealer_or_404(dealer_id):
    row = db.dealers.get(dealer_id)
    if row is None:
        raise errors.dealer_not_found(dealer_id)
    return row


def unit_or_404(unit_id):
    row = db.units.get(unit_id)
    if row is None:
        raise errors.unit_not_found(unit_id)
    return row


def order_or_404(order_id):
    row = db.orders.get(order_id)
    if row is None:
        raise errors.order_not_found(order_id)
    return row


def claim_or_404(claim_id):
    row = db.claims.get(claim_id)
    if row is None:
        raise errors.claim_not_found(claim_id)
    return row


def jig_or_404(jig_id):
    row = db.jigs.get(jig_id)
    if row is None:
        raise errors.resource_not_found("Weld jig", jig_id)
    return row


def lane_or_404(lane_id):
    row = db.lanes.get(lane_id)
    if row is None:
        raise errors.resource_not_found("Test lane", lane_id)
    return row


def road_test_or_404(test_id):
    row = db.road_tests.get(test_id)
    if row is None:
        raise errors.resource_not_found("Road test", test_id)
    return row


def option_or_404(option_id):
    row = db.options.get(option_id)
    if row is None:
        raise errors.resource_not_found("Option install", option_id)
    return row


def unique_or_409(collection, field, value):
    for row in collection.values():
        if row.get(field) == value:
            raise errors.duplicate_code(field, value)
