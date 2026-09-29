"""Surface access: negotiated agreements and statutory entry (PRD 3.4)."""
from flask import Blueprint

import validate as v
from auth import (DETERMINATION_REVIEWER, FIELD_INSPECTOR, PROGRAM_ADMIN,
                  endpoint)
from envelope import filter_value, object_response, paginated
from errors import ApiError
from lookup import collect, get_site_access, get_well
from store import clock, db, days, new_row, touch

bp = Blueprint("site_accesses", __name__)

MODES = ("AGREEMENT", "STATUTORY_ENTRY")
OUTCOMES = ("EXECUTE_AGREEMENT", "ORDER_ENTRY", "DENY")
DEFAULT_WAITING_DAYS = {"STATUTORY_ENTRY": 30, "AGREEMENT": 0}
MAX_WAITING_PERIOD_DAYS = 180
CONFLICTING_STATUSES = ("REQUESTED", "AGREEMENT_EXECUTED", "ENTRY_ORDERED")
WINDOW_OCCUPYING_STATUSES = ("REQUESTED", "DENIED")

READERS = (PROGRAM_ADMIN, FIELD_INSPECTOR, DETERMINATION_REVIEWER)


def bad_transition(message):
    return ApiError("ERR_INVALID_STATE_TRANSITION", message)


def _well_accesses(well_id):
    return [r for r in db.site_accesses.values() if r["well_id"] == well_id]


@bp.route("/wells/<well_id>/site-accesses", methods=["POST"])
@endpoint((PROGRAM_ADMIN, FIELD_INSPECTOR))
def create_site_access(well_id):
    well = get_well(well_id)
    data = v.body()
    surface_owner_name = v.str_field(data, "surface_owner_name")
    mode = v.enum_field(data, "mode", MODES)
    waiting_period_days = v.int_field(data, "waiting_period_days", required=False,
                                      minimum=0, maximum=MAX_WAITING_PERIOD_DAYS)
    compensation_cents = v.int_field(data, "compensation_cents", required=False,
                                     minimum=0)
    if waiting_period_days is None:
        waiting_period_days = DEFAULT_WAITING_DAYS[mode]
    if compensation_cents is None:
        compensation_cents = 0

    existing = _well_accesses(well_id)

    notice_sent_at = clock()
    window_end_at = notice_sent_at + days(waiting_period_days)

    # Closed notice windows may not overlap; touching endpoints conflict. The
    # well's access dimension is a mirrored, merely referenced row here, so its
    # own edge availability is judged only after this check -- otherwise
    # ERR_ACCESS_WINDOW_CONFLICT could never be reached, because every row in
    # CONFLICTING_STATUSES also holds the well out of NO_ACCESS_REQUESTED and
    # ACCESS_DENIED.
    for row in existing:
        if row["status"] not in CONFLICTING_STATUSES:
            continue
        if notice_sent_at <= row["window_end_at"] and row["notice_sent_at"] <= window_end_at:
            raise ApiError(
                "ERR_ACCESS_WINDOW_CONFLICT",
                "The requested notice window overlaps an existing one.",
            )

    # The well's access dimension must have this edge available.
    if well["access_status"] not in ("NO_ACCESS_REQUESTED", "ACCESS_DENIED"):
        raise bad_transition(
            "A well whose access_status is %s cannot open a new request."
            % well["access_status"]
        )
    for row in existing:
        if row["status"] == "REQUESTED":
            raise bad_transition(
                "This well already has a live site-access request."
            )
    if well["access_status"] == "ACCESS_DENIED":
        for row in existing:
            if row["status"] in WINDOW_OCCUPYING_STATUSES:
                if not row["window_end_at"] < clock():
                    raise bad_transition(
                        "A prior notice window on this well is still running."
                    )

    row = new_row()
    row.update({
        "well_id": well_id,
        "surface_owner_name": surface_owner_name,
        "mode": mode,
        "waiting_period_days": waiting_period_days,
        "compensation_cents": compensation_cents,
        "notice_sent_at": notice_sent_at,
        "window_end_at": window_end_at,
        "status": "REQUESTED",
        "legal_authority_citation": None,
        "resolved_at": None,
    })
    db.site_accesses[row["id"]] = row

    well["access_status"] = "ACCESS_PENDING"
    touch(well)

    return object_response(row, 201)


@bp.route("/site-accesses/<access_id>", methods=["GET"])
@endpoint(READERS)
def fetch_site_access(access_id):
    return object_response(get_site_access(access_id))


@bp.route("/wells/<well_id>/site-accesses", methods=["GET"])
@endpoint(READERS)
def list_site_accesses(well_id):
    get_well(well_id)
    status = filter_value("status")

    def keep(row):
        if row["well_id"] != well_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    rows = collect(db.site_accesses, keep, sort_key=lambda r: r["notice_sent_at"])
    return paginated(rows)


@bp.route("/site-accesses/<access_id>/resolution", methods=["POST"])
@endpoint((PROGRAM_ADMIN,))
def resolve_site_access(access_id):
    access = get_site_access(access_id)
    data = v.body()
    outcome = v.enum_field(data, "outcome", OUTCOMES)
    citation = v.str_field(
        data, "legal_authority_citation", required=(outcome == "ORDER_ENTRY")
    )

    if access["status"] != "REQUESTED":
        raise bad_transition(
            "A site-access row in %s cannot be resolved." % access["status"]
        )
    if outcome == "EXECUTE_AGREEMENT" and access["mode"] != "AGREEMENT":
        raise bad_transition(
            "EXECUTE_AGREEMENT is only available on an AGREEMENT request."
        )
    if outcome == "ORDER_ENTRY" and access["mode"] != "STATUTORY_ENTRY":
        raise bad_transition(
            "ORDER_ENTRY is only available on a STATUTORY_ENTRY request."
        )

    if outcome == "ORDER_ENTRY" and clock() < access["window_end_at"]:
        raise ApiError(
            "ERR_STATUTORY_NOTICE_PERIOD_ACTIVE",
            "The statutory notice period has not fully elapsed.",
        )

    well = get_well(access["well_id"])
    if outcome == "EXECUTE_AGREEMENT":
        access["status"] = "AGREEMENT_EXECUTED"
        well["access_status"] = "AGREEMENT_EXECUTED"
    elif outcome == "ORDER_ENTRY":
        access["status"] = "ENTRY_ORDERED"
        access["legal_authority_citation"] = citation
        well["access_status"] = "ENTRY_ORDERED"
    else:
        access["status"] = "DENIED"
        well["access_status"] = "ACCESS_DENIED"
    access["resolved_at"] = clock()
    touch(access)
    touch(well)

    return object_response(access)
