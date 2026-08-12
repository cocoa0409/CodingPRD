"""Cross-entity cascades (SCAFFOLD.yaml §1.2 side effects / PRD §3)."""
from db import db, touch
from services.calc import current_issued_notice, recompute_ledger


def appeal_reversal_cascade(case, remanded):
    """Appeal REVERSED -> case NOTICE_ISSUED -> SANCTION_PROPOSED;
    Appeal REMANDED -> case NOTICE_ISSUED -> CLASSIFIED (offense retained).
    Both branches clear the sanction proposal fields, void the ISSUED notice,
    and cancel the case's SCHEDULED / NO_SHOW conferences (HELD/WAIVED untouched)."""
    case["status"] = "CLASSIFIED" if remanded else "SANCTION_PROPOSED"
    case["proposed_sanction_days"] = None
    case["proposed_sanction_type"] = None
    case["sanction_override"] = False
    case["override_justification"] = None
    case["proposed_at"] = None
    touch(case)

    notice = current_issued_notice(case["id"])
    if notice is not None:
        notice["status"] = "VOIDED"
        touch(notice)
        for conf in db.conferences.values():
            if conf["case_id"] == case["id"] and conf["status"] in ("SCHEDULED", "NO_SHOW"):
                conf["status"] = "CANCELLED"
                touch(conf)


def hearing_decision_cascade(case, expulsion_ordered):
    """EXPULSION_ORDERED: case -> EXPULSION_ACTIVE, student -> ALT_ED_PENDING.
    NOT_EXPELLED: case -> CLASSIFIED, referred_to_expulsion_at cleared."""
    if expulsion_ordered:
        case["status"] = "EXPULSION_ACTIVE"
        touch(case)
        student = db.students.get(case["student_id"])
        if student is not None:
            student["enrollment_status"] = "ALT_ED_PENDING"
            touch(student)
    else:
        case["status"] = "CLASSIFIED"
        case["referred_to_expulsion_at"] = None
        touch(case)


def expungement_approval_cascade(student):
    """Every CLOSED case of the student -> EXPUNGED; ledger recomputed with
    EXPUNGED rows excluded (PRD §2.7 compensation)."""
    for case in db.cases.values():
        if case["student_id"] == student["id"] and case["status"] == "CLOSED":
            case["status"] = "EXPUNGED"
            touch(case)
    recompute_ledger(student)
    touch(student)
