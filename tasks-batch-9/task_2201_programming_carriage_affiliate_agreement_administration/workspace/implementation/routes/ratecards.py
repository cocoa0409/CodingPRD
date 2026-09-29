"""Immutable published rate-card rows (PRD section 3.1)."""
from flask import Blueprint

import constants as K
from auth import guard
from common import ALL_READ_ROLES, created, list_endpoint, read_endpoint
from lookup import put
from store import new_entity
from validation import bad, check_body, field

bp = Blueprint("ratecards", __name__)
BASE = "/carriage/rate-card-entries"


@bp.route(BASE, methods=["POST"])
def create_rate_card_entry():
    guard(["NetworkAdmin"])
    body = check_body(
        {
            "rate_card_class": field("enum", required=True, enum=K.RATE_CARD_CLASSES),
            "tier": field("enum", required=True, enum=K.TIERS),
            "published_rate_cents_per_sub": field(
                "number", required=True, exclusive_min=0
            ),
            "min_subscribers": field("int", default=0, minimum=0),
            "effective_from": field("datetime", required=True),
            "effective_to": field("datetime"),
        }
    )
    if body["effective_to"] is not None and body["effective_to"] <= body["effective_from"]:
        bad("effective_to must be strictly later than effective_from")

    # No created_at, no updated_at, no version: immutable reference data.
    record = new_entity(versioned=False, created=False)
    record.update(
        {
            "rate_card_class": body["rate_card_class"],
            "tier": body["tier"],
            "published_rate_cents_per_sub": body["published_rate_cents_per_sub"],
            "min_subscribers": body["min_subscribers"],
            "effective_from": body["effective_from"],
            "effective_to": body["effective_to"],
        }
    )
    put("rate_card_entry", record)
    return created(record)


@bp.route(BASE, methods=["GET"])
def list_rate_card_entries():
    return list_endpoint("rate_card_entry", ALL_READ_ROLES, ["rate_card_class", "tier"])


@bp.route(BASE + "/<entry_id>", methods=["GET"])
def read_rate_card_entry(entry_id):
    return read_endpoint("rate_card_entry", ALL_READ_ROLES, entry_id)
