"""Escrow holdbacks: reads and the OCC-guarded release (PRD §3.7)."""
from flask import Blueprint, request

import db
from db import communities, escrows, homes
from errors import err_invalid_state, err_no_releasable, err_not_found, err_stale_version
from logic import OPEN_ITEM_STATUSES, RES_AFTER, _contribution
from middleware import ROLE_BUYER, ROLE_MANAGER, ROLE_REP, require_roles
from response import paginate, success_list, success_object
from validation import json_body, req_version

bp = Blueprint("escrow", __name__)

READ_ROLES = (ROLE_MANAGER, ROLE_REP, ROLE_BUYER)


def _get_escrow_or_404(escrow_id):
    esc = escrows.get(escrow_id)
    if esc is None:
        raise err_not_found("Escrow holdback %s not found." % escrow_id)
    return esc


@bp.get("/api/escrow-holdbacks/<escrow_id>")
def get_escrow(escrow_id):
    require_roles(*READ_ROLES)
    return success_object(db.public(_get_escrow_or_404(escrow_id)))


@bp.get("/api/escrow-holdbacks")
def list_escrows():
    require_roles(*READ_ROLES)
    items = list(escrows.values())
    for f in ("home_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [e for e in items if e.get(f) == v]
    items.sort(key=db.sort_key)
    page, pagination = paginate(items, request.args)
    return success_list([db.public(e) for e in page], pagination)


@bp.post("/api/escrow-holdbacks/<escrow_id>/release")
def release_escrow(escrow_id):
    require_roles(ROLE_MANAGER)
    body = json_body()
    expected = req_version(body, "expected_escrow_version")

    esc = _get_escrow_or_404(escrow_id)
    home = homes[esc["home_id"]]
    # state gate (p7) beats the fiscal gate (p11)
    if esc["status"] not in ("ACTIVE", "PARTIALLY_RELEASED"):
        raise err_invalid_state("Releases are only possible on an ACTIVE or PARTIALLY_RELEASED escrow.")
    if home["status"] != "CLOSED":
        raise err_invalid_state("Releases are only possible after the home is CLOSED.")
    if expected != esc["version"]:
        raise err_stale_version("expected_escrow_version does not match the escrow's current version.")

    community = communities[home["community_id"]]
    remaining = esc["funded_amount_cents"] - esc["released_amount_cents"]

    # Releasable: unreleased SIGNED_OFF after-closing items contribute their
    # per-line holdback contribution, consumed oldest sign-off first
    # (signed_off_at ASC, tie-break created_at ASC); never more than remaining.
    eligible = [
        i for i in db.deficiency_items.values()
        if i["home_id"] == home["id"] and i["resolution"] == RES_AFTER
        and i["status"] == "SIGNED_OFF" and not i["holdback_released"]
    ]
    eligible.sort(key=lambda i: (db.parse_dt(i["signed_off_at"]), db.parse_dt(i["created_at"])))
    contribution_sum = sum(_contribution(i, community) for i in eligible)
    releasable = min(contribution_sum, remaining)

    # Flush rule: when no after-closing item remains open, release the entire
    # remaining balance instead.
    open_after = any(
        i["home_id"] == home["id"] and i["resolution"] == RES_AFTER
        and i["status"] in OPEN_ITEM_STATUSES
        for i in db.deficiency_items.values()
    )
    flush = not open_after
    amount = remaining if flush else releasable
    if amount <= 0:
        raise err_no_releasable()

    for i in eligible:
        i["holdback_released"] = True
        db.touch(i)
    esc["released_amount_cents"] += amount
    esc["remaining_amount_cents"] = esc["funded_amount_cents"] - esc["released_amount_cents"]
    esc["status"] = "FULLY_RELEASED" if esc["remaining_amount_cents"] == 0 else "PARTIALLY_RELEASED"
    db.touch(esc)
    return success_object(db.public(esc))
