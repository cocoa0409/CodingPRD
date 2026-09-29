"""club_posture_propagation: the pinned seven-step routine of PRD §2.8."""
from db import touch
from services import calc


def propagate(club):
    """Re-derive the club's whole posture. Returns (frozen_ids, restored_ids)."""
    club_id = club["id"]
    changed = False

    # 1. preliminary compliance score
    preliminary = calc.preliminary_score(club_id)
    if club.get("compliance_score") != preliminary:
        club["compliance_score"] = preliminary
        changed = True

    # 2. adjudicated compliance score
    adjudicated = calc.adjudicated_score(club_id)
    if club.get("adjudicated_compliance_score") != adjudicated:
        club["adjudicated_compliance_score"] = adjudicated
        changed = True

    # 3. outstanding fine ledger
    outstanding = calc.outstanding_fine_cents(club_id)
    if club.get("outstanding_fine_cents") != outstanding:
        club["outstanding_fine_cents"] = outstanding
        changed = True

    # 4. open violation count
    open_count = calc.open_violation_count(club_id)
    if club.get("open_violation_count") != open_count:
        club["open_violation_count"] = open_count
        changed = True

    # 5. escalation tier
    tier = calc.tier_for_score(preliminary)
    if club.get("escalation_tier") != tier:
        club["escalation_tier"] = tier
        changed = True

    # 6. compliance posture
    status = calc.posture_for_score(preliminary)
    if club.get("status") != status:
        club["status"] = status
        changed = True

    if changed:
        touch(club)

    # 7. case propagation in created_at ASC order
    frozen_ids = []
    restored_ids = []
    for case in calc.club_cases(club_id):
        case_changed = False
        if status == "SANCTIONED" and case["case_status"] in (
            "RTP_IN_PROGRESS",
            "PENDING_INC_CLEARANCE",
        ):
            case["frozen_from_status"] = case["case_status"]
            case["case_status"] = "STAGE_FROZEN"
            frozen_ids.append(case["id"])
            case_changed = True
        elif status != "SANCTIONED" and case["case_status"] == "STAGE_FROZEN":
            restore_to = case.get("frozen_from_status") or "RTP_IN_PROGRESS"
            case["case_status"] = restore_to
            case["frozen_from_status"] = None
            restored_ids.append(case["id"])
            case_changed = True

        if case["case_status"] != "CLEARED_FOR_CONTACT":
            desired = status in ("PROBATION", "SANCTIONED")
            if case.get("heightened_review_required") != desired:
                case["heightened_review_required"] = desired
                case_changed = True

        if case_changed:
            touch(case)

    return frozen_ids, restored_ids
