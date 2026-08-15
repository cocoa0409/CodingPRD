"""Entity serializers — computed fields are resolved at read time."""

from db import DB
from services.calculations import budget_reserved, category_entry_count


def contest_view(c):
    reserved = budget_reserved(c["id"])
    return {
        "id": c["id"],
        "name": c["name"],
        "start_at": c["start_at"],
        "end_at": c["end_at"],
        "prize_budget_cents": c["prize_budget_cents"],
        "max_entries_per_contestant": c["max_entries_per_contestant"],
        "status": c["status"],
        "budget_reserved_cents": reserved,
        "budget_available_cents": c["prize_budget_cents"] - reserved,
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def category_view(cat):
    return {
        "id": cat["id"],
        "contest_id": cat["contest_id"],
        "name": cat["name"],
        "skill_division": cat["skill_division"],
        "max_entries": cat["max_entries"],
        "tabulation_method": cat["tabulation_method"],
        "prize_purse_cents": cat["prize_purse_cents"],
        "status": cat["status"],
        "entry_count": category_entry_count(cat["id"]),
        "prize_rank1_cents": cat["prize_rank1_cents"],
        "prize_rank2_cents": cat["prize_rank2_cents"],
        "prize_rank3_cents": cat["prize_rank3_cents"],
        "created_at": cat["created_at"],
        "updated_at": cat["updated_at"],
        "version": cat["version"],
    }


def contestant_view(ct):
    return {
        "id": ct["id"],
        "full_name": ct["full_name"],
        "email": ct["email"],
        "birth_date": ct["birth_date"],
        "accessibility_needs": list(ct["accessibility_needs"]),
        "consents": [dict(item) for item in ct["consents"]],
        "created_at": ct["created_at"],
        "updated_at": ct["updated_at"],
        "version": ct["version"],
    }


def judge_view(j):
    return {
        "id": j["id"],
        "contest_id": j["contest_id"],
        "display_name": j["display_name"],
        "category_ids": list(j["category_ids"]),
        "linked_contestant_id": j["linked_contestant_id"],
        "created_at": j["created_at"],
        "updated_at": j["updated_at"],
        "version": j["version"],
    }


def entry_view(e):
    return {
        "id": e["id"],
        "contestant_id": e["contestant_id"],
        "category_id": e["category_id"],
        "contest_id": e["contest_id"],
        "title": e["title"],
        "character_source": e["character_source"],
        "prop_declarations": list(e["prop_declarations"]),
        "requires_prejudging": e["requires_prejudging"],
        "status": e["status"],
        "safety_status": e["safety_status"],
        "rejected_props": list(e["rejected_props"]),
        "placement_rank": e["placement_rank"],
        "final_score": e["final_score"],
        "craftsmanship_mean": e["craftsmanship_mean"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def prejudging_slot_view(s):
    return {
        "id": s["id"],
        "category_id": s["category_id"],
        "panel_name": s["panel_name"],
        "start_at": s["start_at"],
        "end_at": s["end_at"],
        "status": s["status"],
        "booked_entry_id": s["booked_entry_id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def scoresheet_view(s):
    return {
        "id": s["id"],
        "entry_id": s["entry_id"],
        "judge_id": s["judge_id"],
        "category_id": s["category_id"],
        "phase": s["phase"],
        "craftsmanship": s["craftsmanship"],
        "accuracy": s["accuracy"],
        "presentation": s["presentation"],
        "sheet_total": s["sheet_total"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def performance_slot_view(s):
    return {
        "id": s["id"],
        "entry_id": s["entry_id"],
        "contest_id": s["contest_id"],
        "sequence_number": s["sequence_number"],
        "duration_seconds": s["duration_seconds"],
        "tech_cues": s["tech_cues"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def prize_award_view(a):
    return {
        "id": a["id"],
        "category_id": a["category_id"],
        "contest_id": a["contest_id"],
        "rank": a["rank"],
        "entry_id": a["entry_id"],
        "value_cents": a["value_cents"],
        "tax_reportable": a["tax_reportable"],
        "tax_form_received": a["tax_form_received"],
        "withheld_cents": a["withheld_cents"],
        "net_payout_cents": a["net_payout_cents"],
        "status": a["status"],
        "created_by_user_id": a["created_by_user_id"],
        "approved_by_user_id": a["approved_by_user_id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def green_room_booking_view(b):
    return {
        "id": b["id"],
        "contestant_id": b["contestant_id"],
        "contest_id": b["contest_id"],
        "room_name": b["room_name"],
        "start_at": b["start_at"],
        "end_at": b["end_at"],
        "requires_accessibility_setup": b["requires_accessibility_setup"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def paginate(items, args):
    """limit/offset pagination with scaffold defaults (limit 10, min 1, max 100)."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
