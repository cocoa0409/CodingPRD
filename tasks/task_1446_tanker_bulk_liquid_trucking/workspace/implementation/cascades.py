"""Cascading consistency and compensating releases (PRD 2.9).

Every secondary mutation refreshes updated_at and increments version on the
affected resource (PRD 2.4).
"""
from calc import customer_exposure_cents
from db import store
from store_ops import touch


def recompute_exposure(customer_id):
    """Recalculate the customer's credit exposure after a billing-relevant
    transition (plan, close-meter, reconcile, unplan, cancel — PRD 3.6)."""
    c = store.customers.get(customer_id)
    if c is None:
        return
    total = customer_exposure_cents(customer_id)
    if total != c["exposure_cents"]:
        c["exposure_cents"] = total
        touch(c)


def release_trailer(trailer_id):
    """Trailer ASSIGNED -> AVAILABLE (system transition, PRD 2.9)."""
    if trailer_id is None:
        return
    trailer = store.trailers.get(trailer_id)
    if trailer is not None and trailer["status"] == "ASSIGNED":
        trailer["status"] = "AVAILABLE"
        touch(trailer)


def release_held_cert(cert_id):
    """Held certificate HELD -> CERTIFIED, rejoining the pool unchanged."""
    if cert_id is None:
        return
    cert = store.wash_certs.get(cert_id)
    if cert is not None and cert["status"] == "HELD":
        cert["status"] = "CERTIFIED"
        touch(cert)


def clear_assignment_fields(s):
    s["trailer_id"] = None
    s["driver_id"] = None
    s["rack_id"] = None
    s["wash_cert_id"] = None
    s["rack_window_start"] = None
    s["rack_window_end"] = None


def release_shipment_plan(s):
    """Compensating release for unplan / cancel-from-PLANNED / revoke
    cascade: trailer back to AVAILABLE, held certificate back to CERTIFIED,
    assignment fields cleared. Caller sets the shipment's new status and
    touches it."""
    release_trailer(s["trailer_id"])
    release_held_cert(s["wash_cert_id"])
    clear_assignment_fields(s)


def refresh_cert_lazy(cert):
    """Lazy expiry (PRD 2.5): a CERTIFIED certificate whose expires_at lies
    in the past transitions to EXPIRED on read."""
    if (cert["status"] == "CERTIFIED" and cert["expires_at"] is not None
            and store.clock > cert["expires_at"]):
        cert["status"] = "EXPIRED"
        touch(cert)


def refresh_plan_lazy(plan):
    """Lazy expiry (PRD 2.5): an APPROVED plan past expires_at -> EXPIRED."""
    if (plan["status"] == "APPROVED" and plan["expires_at"] is not None
            and store.clock > plan["expires_at"]):
        plan["status"] = "EXPIRED"
        touch(plan)
