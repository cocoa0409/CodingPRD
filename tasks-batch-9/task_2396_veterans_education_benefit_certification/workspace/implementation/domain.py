"""Domain operations shared by more than one route module."""

from calc import (
    COE_PROTECTION_DAYS,
    DEBT_NOTIFICATION_DAYS,
    D,
    calc1,
    calc2_as_reconciled,
    calc3_steps_2_to_7,
    calc4_prorated,
    is_protected,
    rhu,
)
from common import (
    append_audit,
    clock_day,
    day_of,
    days_between,
    new_row,
    plus_days,
    set_computed_day,
    set_input_day,
    touch,
)
from db import db
from errors import fail

CERT_TERMINAL = ("TERMINATED", "VOID")
CERT_LIVE_FOR_OVERLAP = ("SUBMITTED", "CERTIFIED", "AMENDMENT_PENDING")
CATALOG_LIVE_FOR_WINDOW = ("PENDING_SAA", "APPROVED", "APPROVED_WITH_CONDITIONS")
CATALOG_EFFECTIVE = ("APPROVED", "APPROVED_WITH_CONDITIONS")


def guard_terminal(cert):
    """PRD §3.4: a terminal certification rejects every lifecycle action first."""
    if cert["status"] in CERT_TERMINAL:
        fail("ERR_CERTIFICATION_TERMINAL",
             "This certification is in a terminal state and admits no further action.")


# --- CALC-1 write-back -----------------------------------------------------
def apply_calc1(cert, program, student):
    """Recompute the derived enrollment block from the row's own stored inputs."""
    result = calc1(
        cert["credit_hours_total"],
        cert["credit_hours_online"],
        day_of(cert, "term_start_certified"),
        day_of(cert, "term_end_certified"),
        program,
        student,
    )
    cert["certified_days"] = result["certified_days"]
    cert["rate_of_pursuit_pct"] = result["rate_of_pursuit_pct"]
    cert["rop_tier_pct"] = result["rop_tier_pct"]
    cert["training_time"] = result["training_time"]
    cert["modality"] = result["modality"]
    cert["mha_eligible"] = result["mha_eligible"]
    cert["mha_monthly_rate_cents"] = result["mha_monthly_rate_cents"]
    return result


# --- protection snapshot ---------------------------------------------------
def refresh_protection(student):
    """Rewrite the CALC-7 snapshot; reports whether the stored value moved."""
    live = is_protected(student)
    changed = student["benefit_payment_protected"] != live
    student["benefit_payment_protected"] = live
    return changed


def open_protection_window(student, coe_issued_on_raw, document_reference):
    today = clock_day()
    set_input_day(student, "coe_issued_on", coe_issued_on_raw)
    student["verified_document_reference"] = document_reference
    student["coe_status"] = "VERIFIED"
    set_computed_day(student, "coe_verified_on", today)
    set_computed_day(student, "protected_until", plus_days(today, COE_PROTECTION_DAYS))


# --- lookups ---------------------------------------------------------------
def reported_tuition_report(certification_id):
    for report in db.tuition_reports.values():
        if report["certification_id"] == certification_id and report["status"] == "REPORTED":
            return report
    return None


def effective_catalog_version(program_id, day):
    """Half-open resolution: effective_start <= day < effective_end."""
    for version in db.catalog_versions.values():
        if version["program_id"] != program_id:
            continue
        if version["review_status"] not in CATALOG_EFFECTIVE:
            continue
        start = day_of(version, "effective_start")
        end = day_of(version, "effective_end")
        if start is not None and end is not None and start <= day < end:
            return version
    return None


# --- CASCADE-A: reconciling a change report --------------------------------
def reconcile_change_report(report, actor):
    cert = db.certifications[report["certification_id"]]
    student = db.students[cert["student_id"]]
    program = db.programs[cert["program_id"]]

    change_type = report["change_type"]
    effective_day = day_of(report, "effective_date")
    start_day = day_of(cert, "term_start_certified")
    end_day = day_of(cert, "term_end_certified")

    # R1 — snapshot everything the debt derivation needs before any write.
    paid_tuition = cert["tuition_paid_cents"]
    paid_mha = cert["mha_paid_cents"]
    old_entitlement_days = cert["entitlement_days_charged"]
    old_tier_pct = cert["rop_tier_pct"]
    old_mha_rate = cert["mha_monthly_rate_cents"]
    as_certified_net = cert["net_covered_cents"]
    as_certified_days = cert["certified_days"]

    if change_type == "CREDIT_HOUR_REDUCTION":
        post_total = report["new_credit_hours"]
        post_online = report["new_credit_hours_online"]
    else:
        post_total = cert["credit_hours_total"]
        post_online = cert["credit_hours_online"]

    if change_type == "COMPLETE_WITHDRAWAL":
        period_end = plus_days(effective_day, -1)
    elif change_type == "TERM_DATE_CHANGE":
        period_end = day_of(report, "new_term_end_certified")
    else:
        period_end = end_day

    # R2 — recompute, without writing amount_basis yet.
    post = calc1(post_total, post_online, start_day, end_day, program, student)

    new_mha_total = calc2_as_reconciled(
        start_day, period_end, effective_day, old_mha_rate, post["mha_monthly_rate_cents"]
    )

    if change_type == "COMPLETE_WITHDRAWAL" and not report["mitigating_circumstances_flag"]:
        attended_days = days_between(start_day, effective_day)  # effective_date EXCLUSIVE
        if as_certified_days:
            new_net = rhu(D(as_certified_net) * attended_days / D(as_certified_days))
        else:
            new_net = 0
    else:
        new_net = as_certified_net

    money = calc3_steps_2_to_7(cert, student, new_net)

    days_before = days_between(start_day, effective_day)
    days_after = max(0, days_between(effective_day, period_end) + 1)
    new_entitlement_days = calc4_prorated(
        days_before, old_tier_pct, days_after, post["rop_tier_pct"]
    )

    # R3 — overpayment components from the pre-recomputation disbursements.
    tuition_component = max(0, paid_tuition - money["va_tuition_cents"])
    mha_component = max(0, paid_mha - new_mha_total)
    principal = tuition_component + mha_component

    # CASCADE-A L1
    report["status"] = "RECONCILED"
    report["reconciled_by_official_id"] = actor.user_id
    touch(report)

    # R4 / CASCADE-A L2
    cert["rate_of_pursuit_pct"] = post["rate_of_pursuit_pct"]
    cert["rop_tier_pct"] = post["rop_tier_pct"]
    cert["training_time"] = post["training_time"]
    cert["modality"] = post["modality"]
    cert["mha_eligible"] = post["mha_eligible"]
    cert["mha_monthly_rate_cents"] = post["mha_monthly_rate_cents"]
    cert["mha_term_total_cents"] = new_mha_total
    cert["net_covered_cents"] = money["net_covered_cents"]
    cert["ay_cap_remaining_before_cents"] = money["ay_cap_remaining_before_cents"]
    cert["va_tuition_cents"] = money["va_tuition_cents"]
    cert["cap_charged_cents"] = money["cap_charged_cents"]
    cert["yr_gap_cents"] = money["yr_gap_cents"]
    cert["entitlement_days_charged"] = new_entitlement_days
    cert["amount_basis"] = "AS_RECONCILED"
    cert["status"] = "TERMINATED" if change_type == "COMPLETE_WITHDRAWAL" else "CERTIFIED"
    touch(cert)

    # CASCADE-A L3a — INV-1
    student["entitlement_days_remaining"] += old_entitlement_days - new_entitlement_days
    student_dirty = True

    append_audit(
        cert["id"],
        "AMENDMENT_RECONCILED",
        actor.role,
        actor.user_id,
        "Change report %s reconciled on the AS_RECONCILED basis." % report["id"],
    )

    # CASCADE-A L3b / L4 — the overpayment debt
    if principal > 0:
        if report["liability_party"] == "STUDENT":
            debtor_type, source = "STUDENT", "AMENDMENT_OVERPAYMENT"
        else:
            debtor_type, source = "SCHOOL", "LATE_REPORTING_LIABILITY"

        debt = new_row()
        debt["student_id"] = cert["student_id"]
        debt["certification_id"] = cert["id"]
        debt["change_report_id"] = report["id"]
        debt["waived_by_official_id"] = None
        debt["debtor_type"] = debtor_type
        debt["source"] = source
        debt["principal_cents"] = principal
        debt["tuition_component_cents"] = tuition_component
        debt["mha_component_cents"] = mha_component
        debt["repaid_cents"] = 0
        debt["tuition_repaid_cents"] = 0
        debt["mha_repaid_cents"] = 0
        debt["outstanding_cents"] = principal
        debt["collection_status"] = "OPEN"
        debt["notification_status"] = "PENDING"
        set_computed_day(debt, "notification_due_on",
                         plus_days(clock_day(), DEBT_NOTIFICATION_DAYS))
        debt["notified_on"] = None
        debt["acknowledged_on"] = None
        debt["notification_channel"] = None
        debt["waiver_reason"] = None
        db.debts[debt["id"]] = debt

        if debtor_type == "STUDENT":
            student["open_debt_principal_cents"] += principal

        append_audit(
            cert["id"],
            "DEBT_CREATED",
            actor.role,
            actor.user_id,
            "Overpayment debt %s raised for %d cents." % (debt["id"], principal),
        )

    if student_dirty:
        touch(student)

    # CASCADE-A L5 — a vanished gap reverses PROVISIONAL awards only
    if money["yr_gap_cents"] == 0:
        awards = [a for a in db.awards.values()
                  if a["certification_id"] == cert["id"] and a["status"] == "PROVISIONAL"]
        awards.sort(key=lambda a: (a["created_at"], a["_seq"]))
        for award in awards:
            award["status"] = "REVERSED"
            award["reversal_reason"] = "YR_GAP_ELIMINATED_BY_RECONCILIATION"
            touch(award)
            agreement = db.agreements.get(award["agreement_id"])
            if agreement is not None:
                agreement["pool_remaining_cents"] += award["school_share_cents"]
                agreement["participant_count"] -= 1
                touch(agreement)
            append_audit(
                cert["id"],
                "AWARD_REVERSED",
                "system",
                "system",
                "Award %s reversed because the reconciled Yellow Ribbon gap is zero." % award["id"],
            )

    return report
