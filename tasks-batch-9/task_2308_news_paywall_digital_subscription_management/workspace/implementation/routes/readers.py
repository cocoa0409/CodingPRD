"""Readers, cards, engagement signals and interventions (PRD 3.4)."""
from flask import Blueprint, request

import config
import lookup
import middleware
import serializers
import validation as v
from clock import clock
from db import db, new_entity
from errors import fail
from middleware import auth
from response import mark_created, listing, object_response, touch
from services import engagement
from services.events import create_event

bp = Blueprint("readers", __name__)


def _validate_card(data, required):
    card_last4 = v.get_string(data, "card_last4", required=required, min_len=4, max_len=4)
    if card_last4 is not None and not card_last4.isdigit():
        fail("ERR_INVALID_REQUEST", "Field 'card_last4' must be exactly four digits.")
    exp_required = required or card_last4 is not None
    card_exp_month = v.get_int(
        data, "card_exp_month", required=exp_required, minimum=1, maximum=12
    )
    card_exp_year = v.get_int(
        data, "card_exp_year", required=exp_required, minimum=2020, maximum=2099
    )
    return card_last4, card_exp_month, card_exp_year


@bp.post("/readers")
@auth(config.ROLE_OPS)
def create_reader():
    data = v.body()
    email = v.get_string(data, "email", min_len=1, max_len=200)
    is_registered = v.get_bool(data, "is_registered", default=False)
    propensity_band = v.get_enum(
        data, "propensity_band", config.PROPENSITY_BANDS, default="MEDIUM"
    )
    card_last4, card_exp_month, card_exp_year = _validate_card(data, required=False)
    card_updater_registered = v.get_bool(data, "card_updater_registered", default=False)

    if is_registered:
        if email is None:
            fail("ERR_INVALID_REQUEST", "Field 'email' is required for a registered reader.")
        for existing in db.readers.values():
            if existing.get("email") == email:
                fail("ERR_INVALID_REQUEST", "Field 'email' must be unique among readers.")

    reader = new_entity()
    reader.update(
        {
            "email": email,
            "is_registered": is_registered,
            "propensity_band": propensity_band,
            "engagement_score": 0.0,
            "churn_risk_band": "SEVERE",
            "metered_article_ids": [],
            "metered_distinct_article_count": 0,
            "meter_period_started_on": clock.date().isoformat(),
            "entitlement_source": "NONE",
            "card_last4": card_last4,
            "card_exp_month": card_exp_month,
            "card_exp_year": card_exp_year,
            "card_updater_registered": card_updater_registered,
            "card_updater_status": "NOT_APPLICABLE",
        }
    )
    db.readers[reader["id"]] = reader
    mark_created(reader)
    return object_response(serializers.reader(reader), 201)


@bp.post("/readers/<reader_id>/card")
@auth(config.ROLE_READER, config.ROLE_OPS)
def replace_card(reader_id):
    middleware.guard_reader_path(reader_id)
    data = v.body()
    card_last4, card_exp_month, card_exp_year = _validate_card(data, required=True)
    card_updater_registered = v.get_bool(data, "card_updater_registered", default=None)

    reader = lookup.reader(reader_id)
    reader["card_last4"] = card_last4
    reader["card_exp_month"] = card_exp_month
    reader["card_exp_year"] = card_exp_year
    if card_updater_registered is not None:
        reader["card_updater_registered"] = card_updater_registered
    reader["card_updater_status"] = "NOT_APPLICABLE"
    touch(reader)
    return object_response(serializers.reader(reader))


@bp.post("/readers/<reader_id>/events")
@auth(config.ROLE_READER, config.ROLE_OPS)
def create_reader_event(reader_id):
    middleware.guard_reader_path(reader_id)
    data = v.body()
    event_type = v.get_enum(data, "event_type", config.EVENT_TYPES, required=True)
    occurred_at = v.get_datetime(data, "occurred_at")
    article_id = v.get_id(data, "article_id")

    reader = lookup.reader(reader_id)
    if article_id is not None:
        lookup.article(article_id)
    if (
        occurred_at is not None
        and occurred_at < clock.now()
        and middleware.role() != config.ROLE_OPS
    ):
        fail("ERR_UNAUTHORIZED", "Only a SubscriptionOpsAgent may backdate a reader event.")

    if event_type in config.INTERVENTION_EVENT_TYPES:
        if reader["churn_risk_band"] not in ("HIGH", "SEVERE"):
            fail("ERR_INTERVENTION_NOT_WARRANTED")
        if engagement.intervention_count_in_period(reader) >= 2:
            fail("ERR_INTERVENTION_NOT_WARRANTED")
    if event_type in config.SYSTEM_ONLY_EVENT_TYPES:
        fail("ERR_EVENT_TYPE_SYSTEM_ONLY")

    event = create_event(
        reader, event_type, article_id=article_id, occurred_dt=occurred_at
    )
    engagement.rescore(reader)
    touch(reader)
    return object_response(serializers.reader_event(event), 201)


@bp.get("/readers/<reader_id>")
@auth(config.ROLE_READER, config.ROLE_OPS, config.ROLE_GROUP_ADMIN)
def read_reader(reader_id):
    middleware.guard_reader_path(reader_id)
    return object_response(serializers.reader(lookup.reader(reader_id)))


@bp.get("/reader-events")
@auth(config.ROLE_READER, config.ROLE_OPS, config.ROLE_REVENUE)
def list_reader_events():
    reader_id = request.args.get("reader_id")
    if middleware.is_reader():
        middleware.guard_filter("reader_id")
        reader_id = middleware.user_id()
    rows = sorted(
        db.reader_events.values(), key=lambda e: (e["_occurred_dt"], e["_seq"])
    )
    if reader_id:
        rows = [r for r in rows if r["reader_id"] == reader_id]
    for param in ("article_id", "applied_rule_id", "event_type"):
        value = request.args.get(param)
        if value:
            rows = [r for r in rows if r[param] == value]
    return listing(rows, serializers.reader_event)


@bp.get("/reader-events/<event_id>")
@auth(config.ROLE_READER, config.ROLE_OPS, config.ROLE_REVENUE)
def read_reader_event(event_id):
    middleware.guard_reader_event(event_id)
    event = lookup.require("reader_events", event_id, "ERR_NOT_FOUND")
    return object_response(serializers.reader_event(event))
