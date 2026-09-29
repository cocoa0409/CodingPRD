"""Blue-sky (state registration) capacity ledger."""
import db
from constants import REGISTRATION_SELECTABLE
from money import q2


def remaining(registration):
    return q2(
        registration["registered_amount"]
        - registration["reserved_amount"]
        - registration["consumed_amount"]
    )


def for_class(share_class_id):
    return [r for r in db.store.registrations.values() if r["share_class_id"] == share_class_id]


def expire_stale(share_class_id, state_code, trade_date):
    """A registration whose expiration_date is on or before the trade date expires."""
    for registration in db.store.registrations.values():
        if registration["share_class_id"] != share_class_id:
            continue
        if registration["state_code"] != state_code:
            continue
        if registration["status"] != "ACTIVE":
            continue
        if registration["expiration_date"] <= trade_date:
            registration["status"] = "EXPIRED"
            db.bump_now(registration)


def select(share_class_id, state_code, trade_date):
    """Greatest effective_date wins; ties broken by earliest created_at."""
    best = None
    for registration in db.store.registrations.values():
        if registration["share_class_id"] != share_class_id:
            continue
        if registration["state_code"] != state_code:
            continue
        if registration["status"] not in REGISTRATION_SELECTABLE:
            continue
        if not (registration["effective_date"] <= trade_date < registration["expiration_date"]):
            continue
        if best is None:
            best = registration
            continue
        if registration["effective_date"] > best["effective_date"]:
            best = registration
        elif (registration["effective_date"] == best["effective_date"]
              and registration["created_at"] < best["created_at"]):
            best = registration
    return best


def refresh_status(registration):
    left = remaining(registration)
    if left == 0 and registration["status"] == "ACTIVE":
        db.set_field(registration, "status", "EXHAUSTED")
    elif left > 0 and registration["status"] == "EXHAUSTED":
        db.set_field(registration, "status", "ACTIVE")


def reserve(registration, amount):
    db.set_field(registration, "reserved_amount", q2(registration["reserved_amount"] + amount))
    refresh_status(registration)


def release_reserved(registration, amount):
    db.set_field(registration, "reserved_amount", q2(registration["reserved_amount"] - amount))
    refresh_status(registration)


def consume_reserved(registration, amount):
    db.set_field(registration, "reserved_amount", q2(registration["reserved_amount"] - amount))
    db.set_field(registration, "consumed_amount", q2(registration["consumed_amount"] + amount))
    refresh_status(registration)


def consume(registration, amount):
    db.set_field(registration, "consumed_amount", q2(registration["consumed_amount"] + amount))
    refresh_status(registration)


def release_consumed(registration, amount):
    db.set_field(registration, "consumed_amount", q2(registration["consumed_amount"] - amount))
    refresh_status(registration)
