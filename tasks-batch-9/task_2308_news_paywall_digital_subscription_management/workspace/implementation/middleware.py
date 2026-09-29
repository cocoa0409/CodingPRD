"""Authentication, role authorization and ownership (PRD 2.1 / 2.8 steps 1-2)."""
import functools

from flask import g, request

import config
from db import db
from errors import fail


def _identity():
    user_id = request.headers.get(config.HEADER_USER_ID)
    role = request.headers.get(config.HEADER_USER_ROLE)
    if not user_id or not role or role not in config.ALL_ROLES:
        fail("ERR_MISSING_AUTH_HEADERS")
    return user_id, role


def auth(*allowed_roles):
    """Step 1 (headers, 401) then step 2 (role listed for the endpoint, 403)."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id, role = _identity()
            g.user_id = user_id
            g.user_role = role
            if allowed_roles and role not in allowed_roles:
                fail("ERR_UNAUTHORIZED")
            return view(*args, **kwargs)

        return wrapper

    return decorator


def role():
    return getattr(g, "user_role", None)


def user_id():
    return getattr(g, "user_id", None)


def is_reader():
    return role() == config.ROLE_READER


def is_group_admin():
    return role() == config.ROLE_GROUP_ADMIN


def _deny():
    fail("ERR_UNAUTHORIZED")


# --------------------------------------------------------------- ownership guards
# Each guard looks the target up silently: when the row exists but belongs to
# somebody else the answer is 403 (ladder step 2); when it does not exist at all
# the guard stays quiet so the handler can report the proper 404 (ladder step 5).


def guard_reader_path(reader_id):
    if is_reader() and reader_id != user_id():
        _deny()


def guard_subscription(subscription_id):
    if is_reader():
        row = db.subscriptions.get(subscription_id)
        if row is not None and row.get("reader_id") != user_id():
            _deny()
    elif is_group_admin():
        row = db.subscriptions.get(subscription_id)
        if row is not None and row.get("group_account_id") != user_id():
            _deny()


def guard_invoice(invoice_id):
    if is_reader():
        invoice = db.invoices.get(invoice_id)
        if invoice is not None:
            sub = db.subscriptions.get(invoice["subscription_id"])
            if sub is not None and sub.get("reader_id") != user_id():
                _deny()


def guard_hold(hold_id):
    if is_reader():
        hold = db.holds.get(hold_id)
        if hold is not None:
            sub = db.subscriptions.get(hold["subscription_id"])
            if sub is not None and sub.get("reader_id") != user_id():
                _deny()


def guard_cancellation_request(request_id):
    if is_reader():
        req = db.cancellation_requests.get(request_id)
        if req is not None:
            sub = db.subscriptions.get(req["subscription_id"])
            if sub is not None and sub.get("reader_id") != user_id():
                _deny()


def guard_save_offer(save_offer_id):
    if is_reader():
        offer = db.save_offers.get(save_offer_id)
        if offer is not None:
            req = db.cancellation_requests.get(offer["cancellation_request_id"])
            if req is not None:
                sub = db.subscriptions.get(req["subscription_id"])
                if sub is not None and sub.get("reader_id") != user_id():
                    _deny()


def guard_group_account_path(group_account_id):
    if is_group_admin() and group_account_id != user_id():
        _deny()


def guard_seat(seat_id):
    seat = db.seats.get(seat_id)
    if seat is None:
        return
    if is_reader() and seat.get("reader_id") != user_id():
        _deny()
    if is_group_admin() and seat.get("group_account_id") != user_id():
        _deny()


def guard_reader_event(event_id):
    if is_reader():
        event = db.reader_events.get(event_id)
        if event is not None and event.get("reader_id") != user_id():
            _deny()


def guard_filter(param_name):
    """List endpoints: an entity-backed role may only ask about itself."""
    value = request.args.get(param_name)
    if value is not None and value != "" and value != user_id():
        _deny()
    return value
