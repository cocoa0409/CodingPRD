"""Shared list-endpoint plumbing for the route blueprints."""

from flask import request

import db
import middleware
import response


def _match(value, raw):
    if isinstance(value, bool):
        low = raw.strip().lower()
        if low in ("true", "1"):
            return value is True
        if low in ("false", "0"):
            return value is False
        return False
    if value is None:
        return False
    return str(value) == raw


def apply_filters(rows, mapping):
    """mapping is a sequence of (query parameter, row field) pairs."""
    out = rows
    for param, field in mapping:
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        out = [row for row in out if _match(row.get(field), raw)]
    return out


def listing(rows, limit, offset):
    items, total = middleware.page(rows, limit, offset)
    return response.ok_list(
        [response.serialize(row) for row in items], limit, offset, total
    )


def owner_of_site(site_id):
    site = db.get("sites", site_id)
    return site["customer_id"] if site is not None else None


def owner_of_placement(placement):
    if placement is None:
        return None
    return owner_of_site(placement["site_id"])


def owner_of_ticket(ticket):
    if ticket is None:
        return None
    return owner_of_placement(db.get("machine_placements", ticket["placement_id"]))


def owner_of_visit(visit):
    if visit is None:
        return None
    return owner_of_ticket(db.get("service_tickets", visit["ticket_id"]))


def owner_of_dispenser(dispenser):
    if dispenser is None:
        return None
    return owner_of_placement(
        db.get("machine_placements", dispenser["placement_id"])
    )


def scope_list_to_customer(rows, role, user_id, owner):
    """Restrict a list result to the caller's own account."""
    if role != middleware.ROLE_CUSTOMER_CONTACT:
        return rows
    return [row for row in rows if owner(row) == user_id]
