"""Exhibitions, the logical clock and gallery wall inventory."""

import datetime as dt
import math
from decimal import Decimal

from flask import Blueprint

from core import *  # noqa: F401,F403
from errors import ApiError

bp = Blueprint("exhibitions", __name__)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


@bp.post("/_clock/set_current_utc")
def clock_set():
    authenticate()
    require_roles(ALL_ROLES)
    payload = body()
    raw = v_dt(payload, "to_iso8601")
    db.clock = parse_dt(raw)
    db.clock_raw = raw
    return ok({"current_utc": raw})


# ---------------------------------------------------------------------------
# Exhibitions
# ---------------------------------------------------------------------------

EXHIBITION_DATETIMES = (
    "call_opens_at",
    "call_closes_at",
    "notification_at",
    "delivery_window_start_at",
    "delivery_window_end_at",
    "opening_at",
    "closing_at",
)


def _weights_sum_to_one(exhibition):
    total = (
        D(exhibition["score_weight_technique"])
        + D(exhibition["score_weight_originality"])
        + D(exhibition["score_weight_relevance"])
    )
    return total == Decimal("1")


@bp.post("/exhibitions")
def create_exhibition():
    authenticate()
    require_roles("CallManager")
    payload = body()

    fields = {
        "title": v_str(payload, "title"),
        "season_year": v_int(payload, "season_year"),
        "status": "DRAFT",
        "settlement_status": "NOT_STARTED",
    }
    for field in EXHIBITION_DATETIMES:
        fields[field] = v_dt(payload, field)
    fields["claim_deadline_days"] = v_int(
        payload, "claim_deadline_days", required=False, default=30, minimum=0
    )
    fields["entry_fee_base_cents"] = v_int(payload, "entry_fee_base_cents", minimum=0)
    fields["works_included_in_base"] = v_int(
        payload, "works_included_in_base", required=False, default=2, minimum=0
    )
    fields["entry_fee_additional_cents"] = v_int(
        payload, "entry_fee_additional_cents", minimum=0
    )
    fields["member_discount_pct"] = v_num(
        payload, "member_discount_pct", required=False, default=0.175, minimum=0
    )
    fields["max_works_per_entry"] = v_int(
        payload, "max_works_per_entry", required=False, default=5, minimum=1
    )
    fields["max_entries_per_artist"] = v_int(
        payload, "max_entries_per_artist", required=False, default=1, minimum=1
    )
    fields["max_dimension_cm"] = v_num(payload, "max_dimension_cm", minimum=0)
    fields["max_weight_kg"] = v_num(payload, "max_weight_kg", minimum=0)
    fields["per_work_insurance_cap_cents"] = v_int(
        payload, "per_work_insurance_cap_cents", minimum=0
    )
    fields["allowed_media_categories"] = v_list(
        payload, "allowed_media_categories", MEDIA_CATEGORIES
    )
    codes = v_list(payload, "eligible_state_codes")
    for code in codes:
        if len(code) != 2:
            bad("eligible_state_codes must contain two-letter codes.")
    fields["eligible_state_codes"] = codes
    fields["acceptance_capacity"] = v_int(payload, "acceptance_capacity", minimum=0)
    fields["waitlist_capacity"] = v_int(payload, "waitlist_capacity", minimum=0)
    fields["jury_quorum"] = v_int(payload, "jury_quorum", minimum=0)
    fields["advance_score_threshold"] = v_num(payload, "advance_score_threshold")
    fields["score_weight_technique"] = v_num(payload, "score_weight_technique", minimum=0)
    fields["score_weight_originality"] = v_num(
        payload, "score_weight_originality", minimum=0
    )
    fields["score_weight_relevance"] = v_num(payload, "score_weight_relevance", minimum=0)
    fields["commission_pct"] = v_num(payload, "commission_pct", minimum=0)
    fields["sales_tax_pct"] = v_num(payload, "sales_tax_pct", minimum=0)
    fields["award_budget_cents"] = v_int(payload, "award_budget_cents", minimum=0)

    if not _weights_sum_to_one(fields):
        bad("The three score weights must sum to exactly 1.00.")

    for zeroed in (
        "shortlisted_count",
        "accepted_count",
        "waitlisted_count",
        "insured_value_total_cents",
        "insurance_premium_cents",
        "award_committed_cents",
        "jury_cost_committed_cents",
        "sales_gross_cents",
        "commission_total_cents",
        "sales_tax_total_cents",
        "artist_payable_total_cents",
        "payouts_released_cents",
        "council_retention_cents",
    ):
        fields[zeroed] = 0

    record = new_record(fields)
    db.exhibitions[record["id"]] = record
    return created(record)


@bp.get("/exhibitions")
def list_exhibitions():
    authenticate()
    require_roles(ALL_ROLES)
    items = all_of("exhibitions")
    status = qs("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    season = qs_int("season_year")
    if season is not None:
        items = [e for e in items if e["season_year"] == season]
    return listing(items)


@bp.get("/exhibitions/<exhibition_id>")
def read_exhibition(exhibition_id):
    authenticate()
    require_roles(ALL_ROLES)
    return ok(find("exhibitions", exhibition_id))


# ---------------------------------------------------------------------------
# Cascades shared with other modules
# ---------------------------------------------------------------------------


def deadline_sweep(exhibition):
    """OPEN_FOR_ENTRIES -> JURYING: drop unpaid entries and their works."""
    for entry in entries_of_exhibition(exhibition["id"]):
        if entry.get("status") not in ("DRAFT", "PENDING_FEE"):
            continue
        setv(entry, "status", "WITHDRAWN")
        for artwork in artworks_of_entry(entry["id"]):
            if artwork.get("status") in ("DRAFT", "SUBMITTED"):
                set_artwork_status(artwork, "WITHDRAWN")
        recompute_entry_counts(entry)
    recompute_exhibition_counts(exhibition)
    recompute_insurance(exhibition)
    recompute_rounds_of(exhibition)


def closing_cascade(exhibition):
    closing_at = ts(exhibition, "closing_at")
    deadline = closing_at + dt.timedelta(days=int(exhibition["claim_deadline_days"]))
    touched_walls = set()
    for artwork in artworks_of_exhibition(exhibition["id"]):
        if artwork.get("status") != "ON_VIEW":
            continue
        set_artwork_status(artwork, "RETURN_PENDING")
        setv(artwork, "claim_deadline_at", iso(deadline))
        if artwork.get("placement_status") == "INSTALLED":
            set_placement(artwork, "DEINSTALLED")
            if artwork.get("wall_segment_id"):
                touched_walls.add(artwork["wall_segment_id"])
    for wall_id in touched_walls:
        recompute_wall(db.wall_segments.get(wall_id))
    recompute_insurance(exhibition)


# ---------------------------------------------------------------------------
# Phase advance
# ---------------------------------------------------------------------------

PHASE_TRANSITIONS = {
    "OPEN_FOR_ENTRIES": "DRAFT",
    "JURYING": "OPEN_FOR_ENTRIES",
    "INSTALLATION": "RESULTS_PUBLISHED",
    "ON_VIEW": "INSTALLATION",
    "CLOSED": "ON_VIEW",
}


@bp.post("/exhibitions/<exhibition_id>/phase-advance")
def phase_advance(exhibition_id):
    authenticate()
    require_roles("CallManager")
    exhibition = find("exhibitions", exhibition_id)
    payload = body()
    target = v_enum(payload, "target_status", EXHIBITION_STATUSES)

    required_from = PHASE_TRANSITIONS.get(target)
    if required_from is None or exhibition["status"] != required_from:
        raise ApiError("ERR_EXHIBITION_PHASE_INVALID")

    clock = now()
    if target == "OPEN_FOR_ENTRIES":
        if not _weights_sum_to_one(exhibition):
            bad("The three score weights must sum to exactly 1.00.")
        if not exhibition["allowed_media_categories"] or not exhibition[
            "eligible_state_codes"
        ]:
            bad("allowed_media_categories and eligible_state_codes must be non-empty.")
        if clock >= ts(exhibition, "call_closes_at"):
            raise ApiError("ERR_CALL_WINDOW_CLOSED")
        setv(exhibition, "status", target)
    elif target == "JURYING":
        if clock < ts(exhibition, "call_closes_at"):
            raise ApiError("ERR_CALL_WINDOW_NOT_CLOSED")
        setv(exhibition, "status", target)
        deadline_sweep(exhibition)
    elif target == "INSTALLATION":
        if clock > ts(exhibition, "delivery_window_end_at"):
            raise ApiError("ERR_DELIVERY_WINDOW_INVALID")
        walls = [
            w
            for w in all_of("wall_segments")
            if w.get("exhibition_id") == exhibition["id"]
        ]
        if not walls:
            raise ApiError("ERR_WALL_SEGMENT_REQUIRED")
        setv(exhibition, "status", target)
    elif target == "ON_VIEW":
        if clock < ts(exhibition, "opening_at"):
            raise ApiError("ERR_PHASE_TIME_NOT_REACHED")
        works = artworks_of_exhibition(exhibition["id"])
        for artwork in works:
            if artwork.get("status") in ("ACCEPTED", "DELIVERED") and artwork.get(
                "placement_status"
            ) != "INSTALLED":
                raise ApiError("ERR_INSTALLATION_INCOMPLETE")
        setv(exhibition, "status", target)
        for artwork in works:
            if (
                artwork.get("status") == "DELIVERED"
                and artwork.get("placement_status") == "INSTALLED"
            ):
                set_artwork_status(artwork, "ON_VIEW")
        recompute_insurance(exhibition)
    else:  # CLOSED
        if clock < ts(exhibition, "closing_at"):
            raise ApiError("ERR_PHASE_TIME_NOT_REACHED")
        setv(exhibition, "status", target)
        closing_cascade(exhibition)

    touch(exhibition)
    return ok(exhibition)


# ---------------------------------------------------------------------------
# Acceptance list
# ---------------------------------------------------------------------------


@bp.post("/exhibitions/<exhibition_id>/acceptance-list")
def acceptance_list(exhibition_id):
    authenticate()
    require_roles("JuryChair")
    exhibition = find("exhibitions", exhibition_id)
    payload = body()
    expected = v_int(payload, "expected_exhibition_version")

    rounds = rounds_of_exhibition(exhibition["id"])
    for jury_round in rounds:
        if jury_round.get("status") != "CLOSED":
            raise ApiError("ERR_JURY_ROUND_STATE_INVALID")

    if exhibition["status"] != "JURYING":
        raise ApiError("ERR_EXHIBITION_PHASE_INVALID")

    candidates = []
    for artwork in artworks_of_exhibition(exhibition["id"]):
        if artwork.get("status") != "SHORTLISTED":
            continue
        entry = entry_of(artwork)
        if entry is None or entry.get("status") != "SUBMITTED":
            continue
        candidates.append(artwork)
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_ARTWORKS")

    if expected != exhibition["version"]:
        raise ApiError("ERR_STALE_VERSION")

    def rank_key(artwork):
        score = artwork.get("certified_mean_score")
        score = D(score) if score is not None else Decimal("-1")
        return (-score, artwork.get("created_at"), artwork.get("_seq"))

    ranked = sorted(candidates, key=rank_key)

    capacity = int(exhibition["acceptance_capacity"])
    waitlist_capacity = int(exhibition["waitlist_capacity"])
    medium_cap = int(math.ceil(float(D(capacity) * MEDIUM_CAP_PCT)))

    accepted, waitlisted, declined = [], [], []
    per_medium = {}
    for artwork in ranked:
        medium = artwork["medium_category"]
        if len(accepted) < capacity and per_medium.get(medium, 0) < medium_cap:
            accepted.append(artwork)
            per_medium[medium] = per_medium.get(medium, 0) + 1
        elif len(waitlisted) < waitlist_capacity:
            waitlisted.append(artwork)
        else:
            declined.append(artwork)

    for artwork in accepted:
        set_artwork_status(artwork, "ACCEPTED")
    for artwork in waitlisted:
        set_artwork_status(artwork, "WAITLISTED")
    for artwork in declined:
        set_artwork_status(artwork, "DECLINED")

    for entry in entries_of_exhibition(exhibition["id"]):
        recompute_entry_counts(entry)
    setv(exhibition, "status", "RESULTS_PUBLISHED")
    recompute_exhibition_counts(exhibition)
    recompute_insurance(exhibition)
    recompute_rounds_of(exhibition)
    touch(exhibition)

    result = {
        "accepted_artwork_ids": [a["id"] for a in accepted],
        "waitlisted_artwork_ids": [a["id"] for a in waitlisted],
        "declined_artwork_ids": [a["id"] for a in declined],
        "accepted_count": len(accepted),
        "waitlisted_count": len(waitlisted),
        "declined_count": len(declined),
        "exhibition_status": "RESULTS_PUBLISHED",
    }
    return ok(result)


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------

SETTLEMENT_TRANSITIONS = {
    "RECONCILING": "NOT_STARTED",
    "PAYOUTS_RELEASED": "RECONCILING",
    "BOOKS_CLOSED": "PAYOUTS_RELEASED",
}


@bp.post("/exhibitions/<exhibition_id>/settlement")
def settlement(exhibition_id):
    authenticate()
    require_roles("FinanceOfficer")
    exhibition = find("exhibitions", exhibition_id)
    payload = body()
    target = v_enum(payload, "target_settlement_status", SETTLEMENT_STATUSES)

    if target == "RECONCILING":
        if exhibition["status"] not in ("ON_VIEW", "CLOSED"):
            raise ApiError("ERR_EXHIBITION_PHASE_INVALID")
    elif target == "BOOKS_CLOSED":
        if exhibition["status"] != "CLOSED":
            raise ApiError("ERR_EXHIBITION_PHASE_INVALID")

    required_from = SETTLEMENT_TRANSITIONS.get(target)
    if required_from is None or exhibition["settlement_status"] != required_from:
        raise ApiError("ERR_SETTLEMENT_PHASE_INVALID")

    if target == "PAYOUTS_RELEASED":
        sales = sales_of_exhibition(exhibition["id"])
        for sale in sales:
            if sale.get("status") in ("RECORDED", "INVOICED"):
                raise ApiError("ERR_PAYOUT_INCOMPLETE")
        if int(exhibition["payouts_released_cents"]) != int(
            exhibition["artist_payable_total_cents"]
        ):
            raise ApiError("ERR_PAYOUT_INCOMPLETE")

    setv(exhibition, "settlement_status", target)
    if target in ("RECONCILING", "PAYOUTS_RELEASED"):
        recompute_money(exhibition)
    touch(exhibition)
    return ok(exhibition)


# ---------------------------------------------------------------------------
# Unclaimed sweep
# ---------------------------------------------------------------------------


@bp.post("/exhibitions/<exhibition_id>/unclaimed-sweep")
def unclaimed_sweep(exhibition_id):
    authenticate()
    require_roles("Registrar")
    exhibition = find("exhibitions", exhibition_id)
    clock = now()

    swept, forfeited = [], []
    total = 0
    artists = []
    for artwork in artworks_of_exhibition(exhibition["id"]):
        if artwork.get("status") not in ("RETURN_PENDING", "RETURN_SCHEDULED"):
            continue
        method = artwork.get("return_method")
        if method not in (None, "ARTIST_PICKUP"):
            continue
        deadline = ts(artwork, "claim_deadline_at")
        if deadline is None or clock < deadline:
            continue
        overdue_days = int((clock - deadline).total_seconds() // 86400) + 1
        fee = min(
            STORAGE_FEE_PER_DAY_CENTS * overdue_days,
            int(D(artwork["declared_value_cents"]) * STORAGE_FEE_CAP_PCT),
        )
        setv(artwork, "storage_fee_cents", fee)
        swept.append(artwork["id"])
        total += fee
        if overdue_days > FORFEIT_GRACE_DAYS:
            set_artwork_status(artwork, "UNCLAIMED_FORFEIT")
            forfeited.append(artwork["id"])
            artist = artist_of_artwork(artwork)
            if artist is not None and artist not in artists:
                artists.append(artist)

    for artist in artists:
        recompute_artist_forfeits(artist)
    if forfeited:
        recompute_exhibition_counts(exhibition)
        recompute_insurance(exhibition)

    return ok(
        {
            "swept_artwork_ids": swept,
            "forfeited_artwork_ids": forfeited,
            "storage_fee_total_cents": total,
            "swept_at": iso(clock),
        }
    )


# ---------------------------------------------------------------------------
# Wall segments
# ---------------------------------------------------------------------------


@bp.post("/wall-segments")
def create_wall_segment():
    authenticate()
    require_roles("CallManager", "Registrar")
    payload = body()
    exhibition = fk(payload, "exhibition_id", "exhibitions")
    if exhibition is None:
        req(payload, "exhibition_id")
    label = v_str(payload, "label")
    length_cm = v_num(payload, "length_cm", minimum=0)
    max_weight_kg = v_num(payload, "max_weight_kg", minimum=0)
    lighting = v_enum(
        payload, "lighting_class", LIGHTING_CLASSES, required=False, default="STANDARD"
    )
    record = new_record(
        {
            "exhibition_id": exhibition["id"],
            "label": label,
            "length_cm": length_cm,
            "max_weight_kg": max_weight_kg,
            "lighting_class": lighting,
            "occupied_cm": 0,
            "available_cm": num(length_cm),
            "loaded_weight_kg": 0,
        }
    )
    db.wall_segments[record["id"]] = record
    return created(record)


@bp.get("/wall-segments")
def list_wall_segments():
    authenticate()
    require_roles("CallManager", "Registrar", "JuryChair")
    items = all_of("wall_segments")
    exhibition_id = qs("exhibition_id")
    if exhibition_id is not None:
        items = [w for w in items if w.get("exhibition_id") == exhibition_id]
    return listing(items)


@bp.get("/wall-segments/<wall_id>")
def read_wall_segment(wall_id):
    authenticate()
    require_roles("CallManager", "Registrar", "JuryChair")
    return ok(find("wall_segments", wall_id))
