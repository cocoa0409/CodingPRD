"""Retainage releases (PRD 2.6 ledger, 2.7 OCC, 3.6): server-computed amounts,
phase-bound kinds, compensating approve/void money movement."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

from authz import GCPM, OWNER, ALL_ROLES, require_roles
from db import store
from errors import (
    invalid_state, release_amount_zero, release_kind_already_used, stale_version,
)
from respond import success
from serialize import ser_release
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate, query_filters,
    req_enum, req_int, req_str, sorted_by_creation, touch,
)

bp = Blueprint("releases", __name__, url_prefix="/closeout")

REDUCTION_PCT = Decimal("0.5")
MINOR_WITHHOLD_CENTS = 25000
LIVE_STATUSES = ("REQUESTED", "PAID")


@bp.route("/retainage-releases", methods=["POST"])
def create_release():
    require_roles([GCPM])
    data = json_body()
    project_id = req_str(data, "project_id")
    kind = req_enum(data, "kind", ("REDUCTION", "FINAL"))
    expected_project_version = req_int(data, "expected_project_version")
    p = get_or_404(store.projects, project_id)
    # OCC (priority 7): the release ledger view must not be stale.
    if expected_project_version != p["version"]:
        raise stale_version()
    # Phase binding (priority 8): REDUCTION at SC, FINAL at FINAL_RELEASE_PENDING.
    if kind == "REDUCTION" and p["status"] != "SUBSTANTIALLY_COMPLETE":
        raise invalid_state("A REDUCTION release requires SUBSTANTIALLY_COMPLETE")
    if kind == "FINAL" and p["status"] != "FINAL_RELEASE_PENDING":
        raise invalid_state("A FINAL release requires FINAL_RELEASE_PENDING")
    # Fiscal (priority 13): each kind may be used at most once in a live state.
    if any(r["project_id"] == project_id and r["kind"] == kind
           and r["status"] in LIVE_STATUSES
           for r in store.retainage_releases.values()):
        raise release_kind_already_used()
    # The client never states an amount; the server computes it (PRD 3.6).
    if kind == "REDUCTION":
        # Rounding order is pinned: derive from the frozen, already-rounded
        # retainage_held_cents — never recompute contract * pct * 0.5.
        base = int((Decimal(p["retainage_held_cents"]) * REDUCTION_PCT).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
        if p["reduction_policy"] == "ADJUSTED":
            # Withhold 25000 cents per blocking MINOR item, floored at zero.
            amount = max(0, base - p["open_minor_count"] * MINOR_WITHHOLD_CENTS)
        else:
            amount = base
        if amount == 0:
            raise release_amount_zero()
    else:
        # FINAL: retainage_outstanding_cents at request time (PAID releases only).
        paid = sum(r["amount_cents"] for r in store.retainage_releases.values()
                   if r["project_id"] == project_id and r["status"] == "PAID")
        amount = p["retainage_held_cents"] - paid
    r = {
        "id": new_id(),
        "_seq": next(store.seq),
        "project_id": project_id,
        "kind": kind,
        "amount_cents": amount,
        "status": "REQUESTED",
    }
    r.update(new_common_fields())
    store.retainage_releases[r["id"]] = r
    # Release creation mutates the project's ledger view (PRD 2.6, scaffold
    # side effect): the project version advances even though no field changes.
    touch(p)
    return success(ser_release(r), status=201)


@bp.route("/retainage-releases/<rid>", methods=["GET"])
def get_release(rid):
    require_roles(ALL_ROLES)
    return success(ser_release(get_or_404(store.retainage_releases, rid)))


@bp.route("/retainage-releases", methods=["GET"])
def list_releases():
    require_roles(ALL_ROLES)
    filters = query_filters("project_id", "kind", "status")
    items = [r for r in store.retainage_releases.values()
             if all(r[k] == v for k, v in filters.items())]
    page, pagination = paginate(sorted_by_creation(items))
    return success([ser_release(r) for r in page], response_type="array",
                   pagination=pagination)


@bp.route("/retainage-releases/<rid>/approve", methods=["POST"])
def approve_release(rid):
    require_roles([OWNER])
    r = get_or_404(store.retainage_releases, rid)
    if r["status"] != "REQUESTED":
        raise invalid_state("Only a REQUESTED release can be approved")
    r["status"] = "PAID"
    touch(r)
    p = store.projects[r["project_id"]]
    p["retainage_paid_cents"] += r["amount_cents"]
    p["retainage_outstanding_cents"] -= r["amount_cents"]
    touch(p)
    return success(ser_release(r))


@bp.route("/retainage-releases/<rid>/void", methods=["POST"])
def void_release(rid):
    require_roles([GCPM])
    r = get_or_404(store.retainage_releases, rid)
    p = store.projects[r["project_id"]]
    if r["status"] == "REQUESTED":
        # No money ever moved; the project's release ledger view still changes.
        r["status"] = "VOIDED"
        touch(r)
        touch(p)
    elif r["status"] == "PAID":
        # Clawback: the ledger is restored exactly as if the payment had never
        # occurred (PRD 2.6 compensating invariant).
        r["status"] = "VOIDED"
        touch(r)
        p["retainage_paid_cents"] -= r["amount_cents"]
        p["retainage_outstanding_cents"] += r["amount_cents"]
        touch(p)
    else:
        raise invalid_state("Only REQUESTED or PAID releases can be voided")
    return success(ser_release(r))
