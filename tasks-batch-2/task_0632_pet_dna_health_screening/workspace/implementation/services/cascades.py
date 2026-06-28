"""Cross-resource cascades (PRD §2.6, §3.1, §3.4, §3.8). Each touched resource
is independently mutated: updated_at refreshed and version incremented by one
(except the two version-less entities)."""
from db import db, touch
from services.report_service import recompute_pet_finalized_report_id


def withdraw_estimated_matches_for_pet(pet_id):
    """Cascade from per-pet opt-out: ESTIMATED matches referencing this pet
    auto-withdraw (PRD §3.1). Only ESTIMATED, per the state machine."""
    for m in db.relative_matches.values():
        if m["status"] != "ESTIMATED":
            continue
        if m["pet_id"] == pet_id or m["relative_pet_id"] == pet_id:
            m["status"] = "WITHDRAWN"
            touch(m)


def withdraw_estimated_matches_for_account(account_id):
    """Account-level opt-out: outstanding ESTIMATED matches of the account's
    pets auto-withdraw (PRD §3.1)."""
    pet_ids = {p["id"] for p in db.pets.values() if p["account_id"] == account_id}
    for m in db.relative_matches.values():
        if m["status"] != "ESTIMATED":
            continue
        if m["pet_id"] in pet_ids or m["relative_pet_id"] in pet_ids:
            m["status"] = "WITHDRAWN"
            touch(m)


def revoke_active_share_links_for_report(report_id):
    """Cascade: revoke all ACTIVE ShareLink for this report
    (ACTIVE -> REVOKED) (PRD §3.4)."""
    for sl in db.share_links.values():
        if sl["report_id"] == report_id and sl["status"] == "ACTIVE":
            sl["status"] = "REVOKED"
            touch(sl)


def purge_finalize_cascade(account_id):
    """PRD §3.8 purge-finalize:
      - every pet on the account is archived (REGISTERED -> ARCHIVED),
        decrementing pet_count (derived) and incrementing each pet's version;
      - every ACTIVE share link of those pets' reports is revoked;
      - every ESTIMATED or CONFIRMED relative match referencing those pets is
        withdrawn.
    """
    account_pet_ids = set()
    for p in db.pets.values():
        if p["account_id"] != account_id:
            continue
        account_pet_ids.add(p["id"])
        # Archive pet (only those in REGISTERED transition; archival is the
        # cascade). Per the state machine the precondition is pet.status ==
        # REGISTERED; archive each registered pet.
        if p["status"] == "REGISTERED":
            p["status"] = "ARCHIVED"
            touch(p)

    # Revoke ACTIVE share links of those pets' reports.
    pet_report_ids = {
        r["id"] for r in db.reports.values() if r["pet_id"] in account_pet_ids
    }
    for sl in db.share_links.values():
        if sl["status"] == "ACTIVE" and sl["report_id"] in pet_report_ids:
            sl["status"] = "REVOKED"
            touch(sl)

    # Withdraw ESTIMATED/CONFIRMED matches referencing those pets.
    for m in db.relative_matches.values():
        if m["status"] in ("ESTIMATED", "CONFIRMED"):
            if m["pet_id"] in account_pet_ids or m["relative_pet_id"] in account_pet_ids:
                m["status"] = "WITHDRAWN"
                touch(m)
