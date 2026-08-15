"""Routes: travel packages."""

from decimal import Decimal

from flask import Blueprint, request

import domain as D
from errors import (err409, err_invalid_state, err_not_found, err_phase,
                    err_stale_version)
from store import DB
from util import (auth, check_ownership, created_key, get_body, get_or_404,
                  ok, paginate, require_role, v_int, v_str)

bp = Blueprint("travel", __name__)

PKG_READ = ["FESTIVAL_ADMIN", "TRAVEL_COORDINATOR", "FILMMAKER"]
COORD = ["TRAVEL_COORDINATOR"]


def _own_or_coord(uid, role, package):
    if role == "FILMMAKER":
        sub = DB.submissions.get(package["submission_id"])
        check_ownership(sub is not None and sub["submitter_id"] == uid)


@bp.get("/festival/travel-packages/<pid>")
def get_package(pid):
    uid, role = auth()
    require_role(role, PKG_READ)
    rec = get_or_404(DB.packages, pid)
    _own_or_coord(uid, role, rec)
    return ok(D.ser_package(rec))


@bp.get("/festival/travel-packages")
def list_packages():
    uid, role = auth()
    require_role(role, PKG_READ)
    items = list(DB.packages.values())
    if role == "FILMMAKER":
        own = {s["id"] for s in DB.submissions.values()
               if s["submitter_id"] == uid}
        items = [p for p in items if p["submission_id"] in own]
    submission_id = request.args.get("submission_id")
    edition_id = request.args.get("edition_id")
    status = request.args.get("status")
    if submission_id is not None:
        items = [p for p in items if p["submission_id"] == submission_id]
    if edition_id is not None:
        items = [p for p in items if p["edition_id"] == edition_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=created_key)
    page, meta = paginate(items)
    return ok([D.ser_package(p) for p in page], pagination=meta)


@bp.post("/festival/travel-packages/<pid>/submit")
def submit_package(pid):
    body = get_body()
    delegate_count = v_int(body, "delegate_count", min_v=1)
    origin_country_code = v_str(body, "origin_country_code")
    hotel_nights_requested = v_int(body, "hotel_nights_requested", min_v=1)
    uid, role = auth()
    require_role(role, ["FILMMAKER"])
    rec = get_or_404(DB.packages, pid)
    _own_or_coord(uid, role, rec)
    if rec["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise err_invalid_state(
            "Only DRAFT or CHANGES_REQUESTED packages may be submitted")
    edition = DB.editions.get(rec["edition_id"])
    is_international = (edition is not None
                        and origin_country_code != edition["host_country_code"])
    base = (D.INTERNATIONAL_BASE_CENTS if is_international
            else D.DOMESTIC_BASE_CENTS)
    covered_extras = max(0, min(delegate_count, D.MAX_DELEGATES_COVERED) - 1)
    raw = min(D.PER_FILM_CAP_CENTS,
              base + covered_extras * D.PER_EXTRA_DELEGATE_CENTS)
    rec["delegate_count"] = delegate_count
    rec["origin_country_code"] = origin_country_code
    rec["hotel_nights_requested"] = hotel_nights_requested
    rec["is_international"] = is_international
    rec["raw_stipend_cents"] = raw
    rec["status"] = "SUBMITTED"
    D.touch(rec)
    if edition is not None:
        D.recompute_edition_ledger(edition)
    return ok(D.ser_package(rec))


@bp.post("/festival/travel-packages/<pid>/approve")
def approve_package(pid):
    body = get_body()
    expected_edition_version = v_int(body, "expected_edition_version")
    uid, role = auth()
    require_role(role, COORD)
    rec = get_or_404(DB.packages, pid)
    if rec["status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED package may be approved")
    edition = DB.editions.get(rec["edition_id"])
    if edition is not None and edition["travel_budget_remaining"] <= 0:
        raise err409("ERR_TRAVEL_BUDGET_EXHAUSTED",
                     "The travel budget is exhausted")
    if edition is not None and edition["hotel_nights_remaining"] <= 0:
        raise err409("ERR_HOTEL_NIGHTS_EXHAUSTED",
                     "The hotel nights pool is exhausted")
    if edition is not None and expected_edition_version != edition["version"]:
        raise err_stale_version()
    # Raw figure first, then clamped against pools computed WITHOUT this
    # package (it contributes nothing while SUBMITTED).
    rec["stipend_cents"] = min(rec["raw_stipend_cents"],
                               edition["travel_budget_remaining"])
    rec["hotel_nights_allocated"] = min(rec["hotel_nights_requested"],
                                        edition["hotel_nights_remaining"])
    rec["status"] = "APPROVED"
    D.touch(rec)
    D.recompute_edition_ledger(edition)
    return ok(D.ser_package(rec))


@bp.post("/festival/travel-packages/<pid>/request-changes")
def request_changes(pid):
    get_body()
    uid, role = auth()
    require_role(role, COORD)
    rec = get_or_404(DB.packages, pid)
    if rec["status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED package may be sent back")
    rec["status"] = "CHANGES_REQUESTED"
    D.touch(rec)
    edition = DB.editions.get(rec["edition_id"])
    if edition is not None:
        D.recompute_edition_ledger(edition)
    return ok(D.ser_package(rec))


@bp.post("/festival/travel-packages/<pid>/mark-booked")
def mark_booked(pid):
    get_body()
    uid, role = auth()
    require_role(role, COORD)
    rec = get_or_404(DB.packages, pid)
    if rec["status"] != "APPROVED":
        raise err_invalid_state("Only an APPROVED package may be booked")
    rec["status"] = "BOOKED"
    D.touch(rec)
    edition = DB.editions.get(rec["edition_id"])
    if edition is not None:
        D.recompute_edition_ledger(edition)
    return ok(D.ser_package(rec))


@bp.post("/festival/travel-packages/<pid>/cancel")
def cancel_package(pid):
    get_body()
    uid, role = auth()
    require_role(role, ["TRAVEL_COORDINATOR", "FILMMAKER"])
    rec = get_or_404(DB.packages, pid)
    _own_or_coord(uid, role, rec)
    if rec["status"] not in ("APPROVED", "BOOKED"):
        raise err_invalid_state(
            "Only an APPROVED or BOOKED package may be cancelled")
    original_stipend = rec["stipend_cents"]
    if rec["status"] == "BOOKED":
        # BOOKED cancellation forfeits a quarter of the original stipend,
        # rounded half up, into the edition's penalty sink.
        rec["penalty_cents"] = D.round_half_up_cents(
            Decimal(original_stipend) * D.CANCELLATION_PENALTY_PCT)
    rec["hotel_nights_allocated"] = 0
    rec["stipend_cents"] = 0
    rec["status"] = "CANCELLED"
    D.touch(rec)
    edition = DB.editions.get(rec["edition_id"])
    if edition is not None:
        D.recompute_edition_ledger(edition)
    return ok(D.ser_package(rec))


@bp.post("/festival/travel-packages/<pid>/reconcile")
def reconcile_package(pid):
    get_body()
    uid, role = auth()
    require_role(role, COORD)
    rec = get_or_404(DB.packages, pid)
    if rec["status"] != "BOOKED":
        raise err_invalid_state("Only a BOOKED package may be reconciled")
    edition = DB.editions.get(rec["edition_id"])
    if edition is None or edition["status"] not in ("FESTIVAL_LIVE",
                                                    "AWARDS_NIGHT"):
        raise err_phase("Reconciliation requires FESTIVAL_LIVE or AWARDS_NIGHT")
    rec["status"] = "RECONCILED"
    D.touch(rec)
    if edition is not None:
        D.recompute_edition_ledger(edition)
    return ok(D.ser_package(rec))
