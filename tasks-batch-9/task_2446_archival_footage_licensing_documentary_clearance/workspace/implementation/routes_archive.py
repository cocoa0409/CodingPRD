"""Archives, rate cards and the archive-side source-candidate view."""
from flask import Blueprint, g, request

from core import (ROLE_ARCHIVE_RESEARCHER, ROLE_CLEARANCE_SUPERVISOR, ROLE_LEGAL_COUNSEL,
                  ROLE_PRODUCTION_ADMIN, ROLE_RIGHTS_HOLDER_REP, body, created, db, fail, guard,
                  iso_date, new_row, ok, ok_list, opt_enum, opt_int, opt_str, pagination,
                  parse_date, public, req_date, req_enum, req_int, req_num, req_str, touch)
from domain import get_archive, rate_cards_of_archive

bp = Blueprint("archives", __name__)

HOLDER_TYPES = ("FILM_ARCHIVE", "NEWS_ARCHIVE", "STUDIO", "RECORD_LABEL", "MUSIC_PUBLISHER",
                "INDIVIDUAL")
MFN_POLICIES = ("NONE", "RATE_MFN")
ARCHIVE_STATUSES = ("ACTIVE", "SUSPENDED")

RATE_CARD_NUMBERS = (
    ("tier2_rate_multiplier", 1.25),
    ("tier3_rate_multiplier", 1.60),
    ("media_multiplier_theatrical", 1.40),
    ("media_multiplier_broadcast", 1.15),
    ("media_multiplier_streaming", 1.30),
    ("media_multiplier_all_media", 1.75),
    ("territory_multiplier_world", 1.50),
    ("territory_multiplier_domestic", 1.00),
    ("term_multiplier_per_year", 0.20),
    ("festival_window_multiplier", 0.35),
    ("all_media_window_multiplier", 1.00),
)


@bp.post("/archives")
@guard(ROLE_ARCHIVE_RESEARCHER, ROLE_PRODUCTION_ADMIN)
def create_archive():
    data = body()
    row = new_row()
    row.update({
        "name": req_str(data, "name"),
        "holder_type": req_enum(data, "holder_type", HOLDER_TYPES),
        "mfn_policy": opt_enum(data, "mfn_policy", MFN_POLICIES, "NONE"),
        "status": "ACTIVE",
    })
    db.archives[row["id"]] = row
    return created(public(row))


@bp.get("/archives/<aid>")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR, ROLE_ARCHIVE_RESEARCHER,
       ROLE_RIGHTS_HOLDER_REP, ROLE_LEGAL_COUNSEL)
def read_archive(aid):
    return ok(public(get_archive(aid)))


@bp.post("/archives/<aid>/state")
@guard(ROLE_CLEARANCE_SUPERVISOR)
def archive_state(aid):
    archive = get_archive(aid)
    data = body()
    to_status = req_enum(data, "to_status", ARCHIVE_STATUSES)
    if archive["status"] == to_status:
        fail("ERR_INVALID_STATE_TRANSITION",
             "The archive is already %s." % to_status)
    archive["status"] = to_status
    touch(archive)
    return ok(public(archive))


def _own_archive_or_fail(aid):
    if g.role == ROLE_RIGHTS_HOLDER_REP and g.user_id != aid:
        fail("ERR_ARCHIVE_OWNERSHIP_MISMATCH",
             "A RightsHolderRep may only act on its own archive.")


@bp.post("/archives/<aid>/rate-cards")
@guard(ROLE_ARCHIVE_RESEARCHER, ROLE_RIGHTS_HOLDER_REP)
def publish_rate_card(aid):
    _own_archive_or_fail(aid)
    archive = get_archive(aid)
    data = body()

    card = new_row()
    card.update({
        "archive_id": aid,
        "base_rate_per_30s_cents": req_int(data, "base_rate_per_30s_cents", minimum=0),
        "minimum_fee_cents": req_int(data, "minimum_fee_cents", minimum=0),
        "festival_minimum_fee_cents": req_int(data, "festival_minimum_fee_cents", minimum=0),
        "tier1_max_seconds": opt_int(data, "tier1_max_seconds", 30, minimum=0),
        "tier2_max_seconds": opt_int(data, "tier2_max_seconds", 120, minimum=0),
        "effective_from_date": iso_date(req_date(data, "effective_from_date")),
        "status": "ACTIVE",
    })
    for key, default in RATE_CARD_NUMBERS:
        value = req_num(data, key, default)
        card[key] = value

    if archive["status"] != "ACTIVE":
        fail("ERR_ARCHIVE_SUSPENDED", "A SUSPENDED archive may not publish a rate card.")

    incoming_from = parse_date(card["effective_from_date"], "effective_from_date")
    current = None
    for existing in rate_cards_of_archive(aid):
        if existing["status"] == "ACTIVE":
            current = existing
            break

    if current is not None:
        current_from = parse_date(current["effective_from_date"], "effective_from_date")
        if incoming_from >= current_from:
            current["status"] = "SUPERSEDED"
            touch(current)
        else:
            # A back-dated card never unseats the live one.
            card["status"] = "SUPERSEDED"

    db.rate_cards[card["id"]] = card
    return created(public(card))


@bp.get("/archives/<aid>/rate-cards")
@guard(ROLE_ARCHIVE_RESEARCHER, ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR,
       ROLE_RIGHTS_HOLDER_REP)
def list_rate_cards(aid):
    _own_archive_or_fail(aid)
    get_archive(aid)
    limit, offset = pagination()
    rows = rate_cards_of_archive(aid)
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]

    def sort_key(card):
        group = 0 if card["status"] == "ACTIVE" else 1
        return (group, [-part for part in
                        _date_parts(card["effective_from_date"])], card["_seq"])

    rows = sorted(rows, key=sort_key)
    return ok_list([public(r) for r in rows], limit, offset)


def _date_parts(value):
    d = parse_date(value, "effective_from_date")
    return [d.year, d.month, d.day]


@bp.get("/archives/<aid>/source-candidates")
@guard(ROLE_ARCHIVE_RESEARCHER, ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR)
def list_archive_candidates(aid):
    get_archive(aid)
    limit, offset = pagination()
    from core import by_seq
    rows = by_seq([c for c in db.source_candidates.values() if c["archive_id"] == aid])
    for key in ("availability_status", "selection_status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return ok_list([public(r) for r in rows], limit, offset)
