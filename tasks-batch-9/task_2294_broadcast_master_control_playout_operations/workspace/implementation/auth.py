"""Authentication, identity, authorisation and actor fitness (ladder rows 1-7)."""
from flask import request

import store
import timeutil
from constants import ENTITY_BACKED_ROLES, ROLES, ROLE_CLASS_BY_ROLE
from errors import fail


class Ctx(object):
    def __init__(self, user_id, role, operator):
        self.user_id = user_id
        self.role = role
        self.operator = operator


def certification_state(operator):
    """VALID while the logical clock is at or before certification_expires_utc."""
    expires = operator.get("certification_expires_utc")
    if expires is None:
        return "VALID"
    return "VALID" if timeutil.sec(store.clock()) <= timeutil.sec(expires) else "EXPIRED"


def refresh_certification(operator):
    operator["certification_state"] = certification_state(operator)
    return operator


def authorize(roles, cert=False, mutating=True):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        fail("ERR_MISSING_AUTH_HEADERS", "Both X-User-ID and X-User-Role are required.")
    if role not in ROLES:
        fail("ERR_UNKNOWN_ROLE", "Unknown role '%s'." % role)
    operator = None
    if role in ENTITY_BACKED_ROLES:
        operator = store.operators.get(user_id)
        if operator is None:
            fail("ERR_OPERATOR_NOT_FOUND", "X-User-ID does not resolve to an operator.")
        if operator.get("role_class") != ROLE_CLASS_BY_ROLE[role]:
            fail("ERR_ROLE_IDENTITY_MISMATCH",
                 "Operator role_class does not correspond to the claimed role.")
    if role not in roles:
        fail("ERR_ROLE_NOT_PERMITTED", "Role '%s' may not perform this operation." % role)
    if mutating and operator is not None and operator.get("status") == "SUSPENDED":
        fail("ERR_OPERATOR_SUSPENDED", "The acting operator is suspended.")
    if cert and operator is not None and certification_state(operator) == "EXPIRED":
        fail("ERR_OPERATOR_CERTIFICATION_EXPIRED", "The acting operator's certification has expired.")
    return Ctx(user_id, role, operator)


def ctx():
    """The acting identity of the current request (headers were validated by authorize)."""
    user_id = request.headers.get("X-User-ID")
    return Ctx(user_id, request.headers.get("X-User-Role"), store.operators.get(user_id))


def actor_id():
    return request.headers.get("X-User-ID")


# --- path and body reference resolution ------------------------------------

def _get(collection, ident, error_id):
    rec = collection.get(ident) if isinstance(ident, str) else None
    if rec is None:
        fail(error_id)
    return rec


def transmitter(ident):
    return _get(store.transmitters, ident, "ERR_TRANSMITTER_NOT_FOUND")


def multiplex(ident):
    return _get(store.multiplexes, ident, "ERR_MULTIPLEX_NOT_FOUND")


def channel(ident):
    return _get(store.channels, ident, "ERR_CHANNEL_NOT_FOUND")


def operator_ref(ident):
    return _get(store.operators, ident, "ERR_OPERATOR_REFERENCE_NOT_FOUND")


def asset(ident):
    return _get(store.assets, ident, "ERR_ASSET_NOT_FOUND")


def qc_report(ident):
    return _get(store.qc_reports, ident, "ERR_QC_REPORT_NOT_FOUND")


def playlist(ident):
    return _get(store.playlists, ident, "ERR_PLAYLIST_NOT_FOUND")


def playlist_item(ident):
    return _get(store.items, ident, "ERR_PLAYLIST_ITEM_NOT_FOUND")


def spot_order(ident):
    return _get(store.spot_orders, ident, "ERR_SPOT_ORDER_NOT_FOUND")


def feed_window(ident):
    return _get(store.feed_windows, ident, "ERR_FEED_WINDOW_NOT_FOUND")


def override(ident):
    return _get(store.overrides, ident, "ERR_OVERRIDE_NOT_FOUND")


def fault(ident):
    return _get(store.faults, ident, "ERR_FAULT_NOT_FOUND")


def notification(ident):
    return _get(store.notifications, ident, "ERR_NOTIFICATION_NOT_FOUND")
