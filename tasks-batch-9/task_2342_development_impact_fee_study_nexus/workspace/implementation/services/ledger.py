"""The vintage-dated fee fund: collection, FIFO expenditure, refunds, sweep (PRD 3.9)."""

import clock
import db
from services import derive
from util import add_years, bp, dec, rhu_cents


def _new_entry(**fields):
    record = db.new_record(**fields)
    db.fund_ledger_entries[record["id"]] = record
    return record


def record_collection(application, program):
    """One COLLECTION row per assessed line with a positive net (PRD 3.8)."""
    moment = clock.now()
    deadline = add_years(moment, program["statutory_expenditure_deadline_years"])
    created = []
    for line in application.get("assessed_lines") or []:
        if line["line_net_cents"] <= 0:
            continue
        created.append(_new_entry(
            facility_category_id=line["facility_category_id"],
            development_application_id=application["id"],
            refunded_entry_id=None,
            kind="COLLECTION",
            amount_cents=line["line_net_cents"],
            vintage_at=moment,
            deadline_at=deadline,
            unexpended_cents=line["line_net_cents"],
            entry_status="OPEN",
            project_name=None,
            authorized_by_user_id=None,
        ))
    return created


def eligible_total(category_id):
    return sum(entry["unexpended_cents"] for entry in derive.eligible_collections(category_id))


def record_expenditure(category, amount_cents, project_name, user_id):
    """Strict FIFO consumption on vintage; all-or-nothing (PRD 3.9)."""
    remaining = amount_cents
    for entry in derive.eligible_collections(category["id"]):
        if remaining <= 0:
            break
        take = entry["unexpended_cents"] if entry["unexpended_cents"] < remaining else remaining
        if take <= 0:
            continue
        entry["unexpended_cents"] -= take
        entry["entry_status"] = "FULLY_EXPENDED" if entry["unexpended_cents"] == 0 else "PARTIALLY_EXPENDED"
        db.touch(entry)
        remaining -= take

    row = _new_entry(
        facility_category_id=category["id"],
        development_application_id=None,
        refunded_entry_id=None,
        kind="EXPENDITURE",
        amount_cents=amount_cents,
        vintage_at=clock.now(),
        deadline_at=None,
        unexpended_cents=0,
        entry_status="POSTED",
        project_name=project_name,
        authorized_by_user_id=user_id,
    )
    derive.sync_category(category, posture=True, force=True)
    return row


def refund_amount(entry):
    """The refundable amount, selected by the source row's own state."""
    if entry["entry_status"] == "REFUND_DUE":
        return entry["unexpended_cents"]
    application = db.development_applications.get(entry.get("development_application_id"))
    if application is None:
        return 0
    overpayment = (application["paid_cents"] or 0) - (application["net_due_cents"] or 0)
    if overpayment <= 0:
        return 0
    return min(entry["unexpended_cents"], overpayment)


def record_refund(entry, user_id):
    amount = refund_amount(entry)
    entry["unexpended_cents"] -= amount
    if entry["entry_status"] == "REFUND_DUE" or entry["unexpended_cents"] == 0:
        entry["entry_status"] = "REFUNDED"
    db.touch(entry)

    row = _new_entry(
        facility_category_id=entry["facility_category_id"],
        development_application_id=entry.get("development_application_id"),
        refunded_entry_id=entry["id"],
        kind="REFUND",
        amount_cents=amount,
        vintage_at=clock.now(),
        deadline_at=None,
        unexpended_cents=0,
        entry_status="POSTED",
        project_name=None,
        authorized_by_user_id=user_id,
    )

    category = db.facility_categories.get(entry["facility_category_id"])
    if category is not None:
        derive.sync_category(category, posture=True, force=True)
    application = db.development_applications.get(entry.get("development_application_id"))
    if application is not None:
        derive.sync_application_paid(application)
    return row


def satisfy_agreements(application):
    """A payment satisfies any EXECUTED or DEFAULTED agreement (PRD 3.8)."""
    for agreement in derive.agreements_of_application(application["id"]):
        if agreement["status"] in ("EXECUTED", "DEFAULTED"):
            agreement["status"] = "SATISFIED"
            agreement["satisfied_at"] = clock.now()
            db.touch(agreement)


def deadline_sweep(program):
    """The statutory clock run over one program (PRD 3.9)."""
    moment = clock.now()
    program_categories = derive.categories_of_program(program["id"])
    category_ids = {category["id"] for category in program_categories}

    refund_due_entry_ids = []
    entries = sorted(
        (entry for entry in db.fund_ledger_entries.values()
         if entry["facility_category_id"] in category_ids),
        key=derive.fifo_key,
    )
    for entry in entries:
        if entry["kind"] != "COLLECTION":
            continue
        if entry["entry_status"] not in derive.ELIGIBLE_ENTRY_STATUSES:
            continue
        if entry.get("deadline_at") is None or moment < entry["deadline_at"]:
            continue
        entry["entry_status"] = "REFUND_DUE"
        db.touch(entry)
        refund_due_entry_ids.append(entry["id"])

    defaulted_agreement_ids = []
    delinquent_application_ids = []
    for agreement in db.ordered(db.deferral_agreements):
        if agreement["status"] != "EXECUTED":
            continue
        application = db.development_applications.get(agreement["development_application_id"])
        if application is None or application["fee_program_id"] != program["id"]:
            continue
        if application["collection_status"] != "DEFERRED":
            continue
        if agreement.get("due_at") is None or agreement["due_at"] > moment:
            continue
        agreement["status"] = "DEFAULTED"
        agreement["defaulted_at"] = moment
        db.touch(agreement)

        penalty = rhu_cents(dec(application["net_due_cents"]) * bp(program["default_penalty_bp"]))
        application["default_penalty_cents"] = penalty
        application["net_due_cents"] = application["net_due_cents"] + penalty
        application["collection_status"] = "DELINQUENT"
        db.touch(application)

        defaulted_agreement_ids.append(agreement["id"])
        delinquent_application_ids.append(application["id"])

    at_risk_category_ids = []
    refund_due_category_ids = []
    for category in program_categories:
        derive.sync_category(category, posture=True)
        if category["fund_posture"] == "AT_RISK":
            at_risk_category_ids.append(category["id"])
        elif category["fund_posture"] == "REFUND_DUE":
            refund_due_category_ids.append(category["id"])

    return {
        "refund_due_entry_ids": refund_due_entry_ids,
        "refund_due_entry_count": len(refund_due_entry_ids),
        "defaulted_agreement_ids": defaulted_agreement_ids,
        "delinquent_application_ids": delinquent_application_ids,
        "at_risk_category_ids": at_risk_category_ids,
        "refund_due_category_ids": refund_due_category_ids,
    }
