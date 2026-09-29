"""Customers and the trial-abuse signal ledger."""
from flask import Blueprint

from db import base_record, db, ordered, paginate, touch
from errors import invalid
from middleware import require, require_customer_owner
from response import collection, single
from serialize import ABUSE_SIGNAL, CUSTOMER, dump, dump_many
from services import calc, entities
from validate import Fields, Query

bp = Blueprint("customers", __name__)


@bp.route("/customers", methods=["POST"])
@require("PlatformAdmin", "TrialSupportAgent")
def create_customer():
    fields = Fields("email", "full_name", "household_hash")
    email = fields.string("email")
    full_name = fields.string("full_name")
    household_hash = fields.string("household_hash")
    if any(c["email"] == email for c in db.customers.values()):
        raise invalid("email must be unique")
    record = base_record()
    record.update({
        "email": email,
        "full_name": full_name,
        "household_hash": household_hash,
        "status": "ACTIVE",
        "lifetime_trial_count": 0,
        "completed_return_count": 0,
        "abuse_score_rolling": 0,
        "abuse_score_lifetime": 0,
        "trial_block_until": None,
        "signal_count": 0,
    })
    db.customers[record["id"]] = record
    return single(dump(record, CUSTOMER), 201)


@bp.route("/customers/<customer_id>", methods=["GET"])
@require("Customer", "TrialSupportAgent", "FinanceController", "PlatformAdmin")
def read_customer(customer_id):
    customer = entities.get_customer(customer_id)
    require_customer_owner(customer["id"], "customer")
    return single(dump(customer, CUSTOMER), 200)


@bp.route("/customers/<customer_id>/abuse-signals", methods=["GET"])
@require("TrialSupportAgent", "PlatformAdmin")
def list_abuse_signals(customer_id):
    query = Query("signal_type")
    limit, offset = query.page()
    signal_type = query.enum("signal_type", calc.SIGNAL_TYPES)
    customer = entities.get_customer(customer_id)
    matches = ordered([
        s for s in db.abuse_signals.values()
        if s["customer_id"] == customer["id"]
        and (signal_type is None or s["signal_type"] == signal_type)
    ])
    page, total = paginate(matches, limit, offset)
    return collection(dump_many(page, ABUSE_SIGNAL), limit, offset, total)


@bp.route("/trial-abuse-signals", methods=["POST"])
@require("PlatformAdmin")
def create_abuse_signal():
    fields = Fields("customer_id", "signal_type", "recorded_at", "source_note")
    customer_id = fields.reference("customer_id")
    signal_type = fields.enum("signal_type", calc.SIGNAL_TYPES)
    recorded_at = fields.timestamp("recorded_at", required=False, default=None)
    source_note = fields.string("source_note", required=False, default=None,
                                non_empty=False)
    customer = entities.get_customer(customer_id)
    signal = entities.add_signal(customer, signal_type,
                                 recorded_at=recorded_at,
                                 source_note=source_note)
    entities.derive_customer(customer)
    touch(customer)
    return single(dump(signal, ABUSE_SIGNAL), 201)
