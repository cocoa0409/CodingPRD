"""Shared cascades: risk scoring, fee ledger, credit-application persistence,
recertification, carryover conservation, provider/course compensation."""
import calc
import constants as C
import db
import util

EARNED_FIELDS = (
    "earned_countable_minutes",
    "earned_ethics_minutes",
    "earned_technology_minutes",
    "earned_bias_minutes",
    "earned_live_minutes",
)


def set_fields(row, values):
    """Assign values, touching the row only when something actually changed."""
    changed = False
    for key, value in values.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        db.touch(row)
    return changed


# ------------------------------------------------------------------ risk score
def refresh_risk(provider):
    score, variant = calc.compute_risk_score(provider)
    set_fields(provider, {"risk_score": float(score), "risk_score_variant": variant})
    return provider


# ------------------------------------------------------------------ fee ledger
def assess_fee(fee_type, amount_cents, attorney=None, cycle=None, provider=None, sweep_id=None):
    fee = db.insert(
        "fee_assessments",
        {
            "fee_type": fee_type,
            "amount_cents": int(amount_cents),
            "status": "ASSESSED",
            "assessed_at": util.now_iso(),
            "settled_at": None,
            "waiver_reason": None,
            "attorney_id": attorney["id"] if attorney else None,
            "cycle_id": cycle["id"] if cycle else None,
            "provider_id": provider["id"] if provider else None,
            "assessed_by_sweep_id": sweep_id,
        },
    )
    if attorney is not None:
        set_fields(
            attorney,
            {"outstanding_fee_cents": int(attorney.get("outstanding_fee_cents") or 0) + int(amount_cents)},
        )
    return fee


def release_fee(fee, new_status, waiver_reason=None):
    updates = {"status": new_status, "settled_at": util.now_iso()}
    if waiver_reason is not None:
        updates["waiver_reason"] = waiver_reason
    set_fields(fee, updates)
    attorney = db.get("attorneys", fee.get("attorney_id"))
    if attorney is not None:
        set_fields(
            attorney,
            {
                "outstanding_fee_cents": int(attorney.get("outstanding_fee_cents") or 0)
                - int(fee.get("amount_cents") or 0)
            },
        )
    return fee


def provider_has_open_fee(provider, fee_type):
    for fee in db.all_rows("fee_assessments"):
        if fee.get("provider_id") == provider["id"] and fee.get("fee_type") == fee_type:
            if fee.get("status") == "ASSESSED":
                return True
    return False


# ----------------------------------------------------------- cycle bookkeeping
def cycle_for_instant(attorney_id, instant):
    for cycle in db.all_rows("compliance_cycles"):
        if cycle.get("attorney_id") != attorney_id:
            continue
        start = util.parse_dt(cycle.get("period_start"))
        end = util.parse_dt(cycle.get("period_end"))
        if start <= instant < end:
            return cycle
    return None


def bump_deficiency_count(attorney, delta):
    set_fields(
        attorney,
        {"open_deficiency_count": max(0, int(attorney.get("open_deficiency_count") or 0) + delta)},
    )


def persist_application(cycle, variant, carryover_in_general_override=None):
    """Run the credit application and persist its outputs (PRD 3.6)."""
    res = calc.credit_application(cycle, variant, carryover_in_general_override)
    set_fields(
        cycle,
        {
            "earned_countable_minutes": res["earned_countable_minutes"],
            "earned_ethics_minutes": res["earned_ethics_minutes"],
            "earned_technology_minutes": res["earned_technology_minutes"],
            "earned_bias_minutes": res["earned_bias_minutes"],
            "earned_live_minutes": res["earned_live_minutes"],
        },
    )
    for record in res["all_records"]:
        countable = res["per_record"].get(record["id"], 0)
        set_fields(record, {"countable_minutes": countable})
    return res


def rerun_cycle(cycle, visited=None):
    """Re-run the credit application for a cycle after any input changed, then
    apply the recertification and carryover-conservation consequences."""
    if visited is None:
        visited = set()
    if cycle["id"] in visited:
        return None
    visited.add(cycle["id"])

    if cycle.get("credit_status") == "OPEN":
        return persist_application(cycle, "PROVISIONAL")

    res = persist_application(cycle, "FINAL")

    if cycle.get("credit_status") == "CLOSED_COMITY":
        set_fields(cycle, {"earned_countable_minutes": int(cycle.get("required_total_minutes") or 0)})
        out_general, out_ethics = 0, 0
    else:
        out_general, out_ethics = calc.carryover_determination(cycle, res)

    if cycle.get("credit_status") == "SATISFIED" and calc.has_any_deficiency(res):
        # Recertification: a void has undone a settled finding (PRD 3.8).
        set_fields(cycle, {"credit_status": "OPEN", "certified_at": None})
        out_general, out_ethics = 0, 0
        attorney = db.get("attorneys", cycle.get("attorney_id"))
        if attorney is not None:
            set_fields(
                attorney,
                {
                    "pending_recertification_count": int(attorney.get("pending_recertification_count") or 0)
                    + 1
                },
            )

    write_carryover_out(cycle, out_general, out_ethics, visited)
    return res


def write_carryover_out(cycle, out_general, out_ethics, visited=None):
    """Store the carried-out figures and conserve the transfer to successors."""
    set_fields(
        cycle,
        {
            "carryover_out_general_minutes": out_general,
            "carryover_out_ethics_minutes": out_ethics,
        },
    )
    if visited is None:
        visited = {cycle["id"]}
    for successor in db.all_rows("compliance_cycles"):
        if successor.get("previous_cycle_id") != cycle["id"]:
            continue
        if successor["id"] in visited:
            continue
        set_fields(
            successor,
            {
                "carryover_in_general_minutes": out_general,
                "carryover_in_ethics_minutes": out_ethics,
            },
        )
        rerun_cycle(successor, visited)


# ------------------------------------------------------- credit record moves
def mark_verified(record):
    set_fields(record, {"status": "VERIFIED"})
    course = db.get("courses", record.get("course_id"))
    if course is not None:
        set_fields(
            course,
            {"verified_credit_record_count": int(course.get("verified_credit_record_count") or 0) + 1},
        )
    cycle = db.get("compliance_cycles", record.get("cycle_id"))
    if cycle is not None:
        rerun_cycle(cycle)
    return record


def mark_rejected(record, reason):
    set_fields(record, {"status": "REJECTED", "void_reason": reason})
    cycle = db.get("compliance_cycles", record.get("cycle_id"))
    if cycle is not None:
        rerun_cycle(cycle)
    return record


def mark_voided(record, reason):
    set_fields(record, {"status": "VOIDED", "void_reason": reason, "countable_minutes": 0})
    course = db.get("courses", record.get("course_id"))
    if course is not None:
        set_fields(
            course,
            {
                "verified_credit_record_count": max(
                    0, int(course.get("verified_credit_record_count") or 0) - 1
                )
            },
        )
    cycle = db.get("compliance_cycles", record.get("cycle_id"))
    if cycle is not None:
        rerun_cycle(cycle)
    return record


# ---------------------------------------------------------- provider cascades
def suspend_self_certified_courses(provider):
    """Sponsor suspension / lapse cascade (PRD 3.1, 3.2)."""
    now = util.now_dt()
    for course in db.all_rows("courses"):
        if course.get("provider_id") != provider["id"]:
            continue
        if course.get("status") != "APPROVED":
            continue
        if course.get("approval_pathway") != "PROVIDER_ACCREDITED":
            continue
        expires = util.parse_dt(course.get("expires_at"))
        if expires is None or expires <= now:
            continue
        set_fields(course, {"status": "SUSPENDED_PENDING_REVIEW"})
        for record in db.all_rows("credit_records"):
            if record.get("course_id") != course["id"]:
                continue
            if record.get("status") != "PENDING_VERIFICATION":
                continue
            mark_rejected(record, "SPONSOR_NOT_IN_GOOD_STANDING")


def restore_suspended_courses(provider):
    """Sponsor reinstatement / renewal compensation cascade — no credit-record
    compensation whatsoever (PRD 3.1)."""
    now = util.now_dt()
    for course in db.all_rows("courses"):
        if course.get("provider_id") != provider["id"]:
            continue
        if course.get("status") != "SUSPENDED_PENDING_REVIEW":
            continue
        expires = util.parse_dt(course.get("expires_at"))
        if expires is None or expires <= now:
            continue
        set_fields(course, {"status": "APPROVED"})


def move_provider_status(provider, status):
    set_fields(
        provider,
        {
            "accreditation_status": status,
            "self_certification_enabled": status == "ACCREDITED",
        },
    )
