"""The operational sweep (PRD §3.11) with its pinned processing order."""
import constants as C
from db import db, fmt_ts, sort_rows, touch
from services import audits as audit_service
from services import calc
from services import posture

_BREACHABLE = ("INITIATED", "SCREENED", "LOCKER_ROOM_EXAM")


def run_sweep():
    breached_evaluation_ids = []
    auto_opened_audit_ids = []
    expired_baseline_test_ids = []
    expired_inc_clearance_ids = []
    prolonged_watch_case_ids = []
    offseason_monitoring_case_ids = []
    touched_club_ids = []

    # ---- 1. evaluation breaches --------------------------------------------
    for evaluation in sort_rows(list(db.sideline_evaluations.values())):
        if evaluation["status"] not in _BREACHABLE:
            continue
        if db.now < evaluation["protocol_deadline_at"]:
            continue
        was_in_exam = evaluation["status"] == "LOCKER_ROOM_EXAM"
        evaluation["status"] = "PROTOCOL_BREACH"
        touch(evaluation)
        breached_evaluation_ids.append(evaluation["id"])

        codes = ["EVALUATION_DEADLINE_BREACH"]
        if was_in_exam:
            codes.append("INCOMPLETE_LOCKER_ROOM_EXAM")
        player = db.players.get(evaluation["player_id"])
        club_id = player["club_id"] if player is not None else None
        if club_id is None:
            continue
        audit = audit_service.open_auto_issued_audit(
            club_id, codes, sideline_evaluation_id=evaluation["id"], exposure_days=0)
        auto_opened_audit_ids.append(audit["id"])
        if club_id not in touched_club_ids:
            touched_club_ids.append(club_id)

    # ---- 2. baseline expiry ------------------------------------------------
    affected_player_ids = []
    for test in sort_rows(list(db.baseline_tests.values())):
        if test["status"] != "VALID":
            continue
        if db.now < test["validity_expires_at"]:
            continue
        test["status"] = "EXPIRED"
        test["retest_required_reason"] = "SEASON_ROLLOVER"
        touch(test)
        expired_baseline_test_ids.append(test["id"])
        if test["player_id"] not in affected_player_ids:
            affected_player_ids.append(test["player_id"])
    for player_id in affected_player_ids:
        player = db.players.get(player_id)
        if player is None:
            continue
        resolved = calc.resolve_baseline_status(player_id)
        if player["baseline_status"] != resolved:
            player["baseline_status"] = resolved
            touch(player)

    # ---- 3. clearance expiry -----------------------------------------------
    for clearance in sort_rows(list(db.inc_clearances.values())):
        if clearance["status"] != "APPROVED":
            continue
        expires_at = clearance.get("expires_at")
        if expires_at is None or db.now < expires_at:
            continue
        case = db.concussion_cases.get(clearance["case_id"])
        if case is not None and case["case_status"] == "CLEARED_FOR_CONTACT":
            continue
        clearance["status"] = "EXPIRED"
        touch(clearance)
        expired_inc_clearance_ids.append(clearance["id"])

    # ---- 4. monitoring advance --------------------------------------------
    for case in sort_rows(list(db.concussion_cases.values())):
        offseason_at = calc.offseason_start_at(case["season_year"])
        if (db.now >= offseason_at
                and case["monitoring_status"] in ("ACTIVE_SYMPTOM_WATCH",
                                                 "PROLONGED_SYMPTOM_WATCH")):
            case["monitoring_status"] = "OFFSEASON_MONITORING"
            touch(case)
            offseason_monitoring_case_ids.append(case["id"])
            continue
        if (case["monitoring_status"] == "ACTIVE_SYMPTOM_WATCH"
                and case["case_status"] != "CLEARED_FOR_CONTACT"
                and calc.days_since_diagnosis(case) >= C.PROLONGED_SYMPTOM_DAYS):
            case["monitoring_status"] = "PROLONGED_SYMPTOM_WATCH"
            touch(case)
            prolonged_watch_case_ids.append(case["id"])
            player = db.players.get(case["player_id"])
            if player is not None and player["availability_status"] != "PROTOCOL_RESTRICTED":
                player["availability_status"] = "PROTOCOL_RESTRICTED"
                touch(player)

    # ---- 5. club posture for every club touched in step 1 ------------------
    frozen_case_ids = []
    restored_case_ids = []
    clubs = [db.clubs[cid] for cid in touched_club_ids if cid in db.clubs]
    clubs = sort_rows(clubs)
    for club in clubs:
        frozen, restored = posture.propagate(club)
        frozen_case_ids.extend(frozen)
        restored_case_ids.extend(restored)

    return {
        "swept_at": fmt_ts(db.now),
        "breached_evaluation_ids": breached_evaluation_ids,
        "auto_opened_audit_ids": auto_opened_audit_ids,
        "expired_baseline_test_ids": expired_baseline_test_ids,
        "expired_inc_clearance_ids": expired_inc_clearance_ids,
        "prolonged_watch_case_ids": prolonged_watch_case_ids,
        "offseason_monitoring_case_ids": offseason_monitoring_case_ids,
        "frozen_case_ids": frozen_case_ids,
        "restored_case_ids": restored_case_ids,
    }
