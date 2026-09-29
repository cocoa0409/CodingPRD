"""Collections contacts and the four bars on taking the goods back."""

from flask import Blueprint

import clock
import middleware
import response
import validators
from db import base_row, db, public, touch
from errors import ApiError
from routes import common
from routes.returns import open_inspection
from services import calc, domain

bp = Blueprint("collections", __name__)

CHANNELS = ("PHONE", "SMS", "EMAIL", "IN_PERSON")
OUTCOMES = ("NO_ANSWER", "LEFT_MESSAGE", "SPOKE_TO_CUSTOMER", "PROMISE_TO_PAY")


def _rolling_count(agreement_id, now):
    """Half-open window: lower bound exclusive, upper bound inclusive."""
    floor_instant = clock.plus_days(now, -calc.ROLLING_WINDOW_DAYS)
    count = 0
    for contact in db.contacts.values():
        if contact["agreement_id"] != agreement_id:
            continue
        stamp = clock.parse(contact["contacted_at"])
        if stamp is None:
            continue
        if floor_instant < stamp <= now:
            count += 1
    return count


def _channel_usable(customer, channel):
    if customer is None:
        return False
    if channel in ("PHONE", "SMS"):
        return bool(customer["phone"])
    if channel == "EMAIL":
        return bool(customer["email"])
    return bool(customer["in_person_contact_consent"])


@bp.post("/agreements/<agreement_id>/collection-contacts")
def log_contact(agreement_id):
    user_id, _ = middleware.authenticate(
        (middleware.PLATFORM_ADMIN, middleware.COLLECTIONS_AGENT)
    )
    agreement = domain.require_agreement(agreement_id)
    body = validators.json_body()
    channel = validators.enum(body, "channel", CHANNELS)
    outcome = validators.enum(body, "outcome", OUTCOMES)

    domain.check_payment_status(agreement, domain.OP_CONTACT)
    if agreement["payment_status"] not in ("DELINQUENT", "DEFAULTED"):
        raise ApiError("ERR_COLLECTION_NOT_DELINQUENT")

    rule = domain.pinned_rule(agreement)
    now = clock.now()
    hour = now.hour
    if (
        hour >= rule["quiet_hours_start_utc_hour"]
        or hour < rule["quiet_hours_end_utc_hour"]
    ):
        raise ApiError("ERR_QUIET_HOURS_VIOLATION")

    count_before = _rolling_count(agreement["id"], now)
    if count_before >= rule["max_collection_contacts_per_week"]:
        raise ApiError("ERR_CONTACT_FREQUENCY_EXCEEDED")

    customer = db.customers.get(agreement["customer_id"])
    if not _channel_usable(customer, channel):
        raise ApiError("ERR_CONTACT_CHANNEL_UNAVAILABLE")

    contact = base_row(versioned=False)
    contact["agreement_id"] = agreement["id"]
    contact["channel"] = channel
    contact["outcome"] = outcome
    contact["contacted_at"] = clock.fmt(now)
    contact["rolling_7d_count_at_contact"] = count_before
    contact["contacted_by_user_id"] = user_id
    db.contacts[contact["id"]] = contact

    agreement["collection_contact_count_7d"] = _rolling_count(agreement["id"], now)
    touch(agreement)
    return response.object_response(public(contact), 201)


@bp.get("/agreements/<agreement_id>/collection-contacts")
def list_contacts(agreement_id):
    middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.COMPLIANCE_OFFICER,
            middleware.STORE_MANAGER,
            middleware.COLLECTIONS_AGENT,
        )
    )
    agreement = domain.require_agreement(agreement_id)
    rows = domain.agreement_contacts(agreement["id"])
    return common.paged(rows, primary="contacted_at", filters=("channel",))


@bp.post("/agreements/<agreement_id>/repossess")
def repossess(agreement_id):
    user_id, _ = middleware.authenticate(
        (middleware.PLATFORM_ADMIN, middleware.COLLECTIONS_AGENT)
    )
    agreement = domain.require_agreement(agreement_id)
    body = validators.json_body()
    confirm = validators.boolean(body, "confirm")
    if not confirm:
        raise ApiError(
            "ERR_INVALID_REQUEST", "Field 'confirm' must be true to repossess."
        )

    customer = db.customers.get(agreement["customer_id"])
    if customer is not None and user_id == customer["verified_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    domain.check_payment_status(agreement, domain.OP_REPOSSESS)
    domain.check_possession_status(agreement, domain.OP_REPOSSESS)

    if domain.open_window(agreement["id"]) is not None:
        raise ApiError("ERR_REINSTATEMENT_WINDOW_OPEN")
    rule = domain.pinned_rule(agreement)
    if agreement["paid_pct"] >= rule["repossession_paid_pct_limit"]:
        raise ApiError("ERR_REPOSSESSION_EQUITY_PROTECTED")
    if not domain.agreement_contacts(agreement["id"]):
        raise ApiError("ERR_COLLECTION_NOTICE_REQUIRED")

    unit = domain.require_unit(agreement["unit_id"])
    open_inspection(agreement, unit, "REPOSSESSION_RECOVERY")

    agreement["possession_status"] = "REPOSSESSED"
    agreement["payment_status"] = "CLOSED"
    agreement["collections_stage"] = "ADVERSE"
    touch(agreement)

    unit["status"] = "RETURNED_PENDING_GRADE"
    domain.write_provisional_residual(unit)

    touched_stores = {unit["store_id"]}
    domain.void_open_tickets(agreement, touched_stores)
    for store_id in sorted(touched_stores):
        store = db.stores.get(store_id)
        if store is not None:
            domain.sync_store(store)

    if customer is not None:
        domain.sync_customer(customer)
    return response.object_response(public(agreement))
