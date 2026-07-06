"""Public JSON serializers — one per entity. Strips internal fields (like _seq)
and returns only the schema fields listed in the PRD/SCAFFOLD."""


def _strip_seq(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


def member_dto(m):
    return {
        "id": m["id"],
        "email": m["email"],
        "display_name": m["display_name"],
        "home_neighborhood": m["home_neighborhood"],
        "trust_tier": m["trust_tier"],
        "verified_credential_count": m["verified_credential_count"],
        "completed_exchange_count": m["completed_exchange_count"],
        "chronological_balance_minutes": m["chronological_balance_minutes"],
        "forward_looking_balance_minutes": m["forward_looking_balance_minutes"],
        "lifetime_earned_minutes": m["lifetime_earned_minutes"],
        "lifetime_redeemed_minutes": m["lifetime_redeemed_minutes"],
        "no_show_strikes": m["no_show_strikes"],
        "is_suspended": m["is_suspended"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def skill_offer_dto(o):
    return {
        "id": o["id"],
        "member_id": o["member_id"],
        "skill_code": o["skill_code"],
        "title": o["title"],
        "minutes_per_session": o["minutes_per_session"],
        "required_trust_tier": o["required_trust_tier"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def skill_request_dto(r):
    return {
        "id": r["id"],
        "member_id": r["member_id"],
        "skill_code": r["skill_code"],
        "needed_minutes": r["needed_minutes"],
        "earliest_start_utc": r["earliest_start_utc"],
        "latest_start_utc": r["latest_start_utc"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def exchange_dto(x):
    return {
        "id": x["id"],
        "offer_id": x["offer_id"],
        "request_id": x["request_id"],
        "provider_member_id": x["provider_member_id"],
        "requester_member_id": x["requester_member_id"],
        "scheduled_start_utc": x["scheduled_start_utc"],
        "committed_minutes": x["committed_minutes"],
        "status": x["status"],
        "settled_at_utc": x.get("settled_at_utc"),
        "created_at": x["created_at"],
        "updated_at": x["updated_at"],
        "version": x["version"],
    }


def ledger_entry_dto(e):
    # No version / updated_at per §2.4.
    return {
        "id": e["id"],
        "member_id": e["member_id"],
        "exchange_id": e.get("exchange_id"),
        "redemption_id": e.get("redemption_id"),
        "entry_kind": e["entry_kind"],
        "delta_minutes": e["delta_minutes"],
        "posted_at": e["posted_at"],
        "memo": e.get("memo"),
        "created_at": e["created_at"],
    }


def redemption_dto(r):
    return {
        "id": r["id"],
        "member_id": r["member_id"],
        "reward_code": r["reward_code"],
        "minutes_cost": r["minutes_cost"],
        "expected_member_version": r["expected_member_version"],
        "status": r["status"],
        "fulfilled_at_utc": r.get("fulfilled_at_utc"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def credential_dto(c):
    return {
        "id": c["id"],
        "subject_member_id": c["subject_member_id"],
        "verifier_member_id": c.get("verifier_member_id"),
        "credential_type": c["credential_type"],
        "skill_code": c.get("skill_code"),
        "evidence_url": c["evidence_url"],
        "status": c["status"],
        "revision_round": c["revision_round"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def group_project_dto(p):
    return {
        "id": p["id"],
        "organizer_member_id": p["organizer_member_id"],
        "title": p["title"],
        "window_start_utc": p["window_start_utc"],
        "window_end_utc": p["window_end_utc"],
        "minimum_completed_ratio": p["minimum_completed_ratio"],
        "aggregate_state": p["aggregate_state"],
        "total_committed_minutes": p["total_committed_minutes"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def project_shift_dto(s):
    return {
        "id": s["id"],
        "project_id": s["project_id"],
        "role_label": s["role_label"],
        "shift_start_utc": s["shift_start_utc"],
        "duration_minutes": s["duration_minutes"],
        "capacity": s["capacity"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def shift_assignment_dto(a):
    return {
        "id": a["id"],
        "shift_id": a["shift_id"],
        "member_id": a["member_id"],
        "status": a["status"],
        "check_in_utc": a.get("check_in_utc"),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def dispute_dto(d):
    return {
        "id": d["id"],
        "exchange_id": d["exchange_id"],
        "raised_by_member_id": d["raised_by_member_id"],
        "reason_code": d["reason_code"],
        "claimed_delta_minutes": d["claimed_delta_minutes"],
        "status": d["status"],
        "admin_notes": d.get("admin_notes"),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def impact_report_dto(r):
    return {
        "id": r["id"],
        "report_month": r["report_month"],
        "total_hours_exchanged": r["total_hours_exchanged"],
        "unique_active_members": r["unique_active_members"],
        "top_skill_code": r.get("top_skill_code"),
        "generated_by_user_id": r["generated_by_user_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
