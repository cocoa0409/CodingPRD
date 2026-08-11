"""Shared write operations and cascades."""

from decimal import Decimal

import calc
import constants as K
import derive
import store
from util import D, rhu, rhu_int, shift_hours, parse_dt, parse_date, fmt_dt


# ---------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------

def append_line(invoice, line_type, amount_cents, memo, created_by_role,
                source_consignment_lot_id=None):
    record = store.base_record(versioned=False)
    record.update({
        "invoice_id": invoice["id"],
        "source_consignment_lot_id": source_consignment_lot_id,
        "line_type": line_type,
        "amount_cents": int(amount_cents),
        "memo": memo,
        "created_by_role": created_by_role,
    })
    store.insert("invoice_lines", record)
    store.touch(invoice)
    return record


def remove_lines(invoice, line_type):
    removed = [l for l in derive.lines_of(invoice["id"]) if l["line_type"] == line_type]
    for line in removed:
        del store.DB["invoice_lines"][line["id"]]
    if removed:
        store.touch(invoice)
    return removed


# ---------------------------------------------------------------------------
# milestones
# ---------------------------------------------------------------------------

def start_milestone(milestone):
    if milestone is None or milestone["status"] != "PENDING":
        return
    milestone["status"] = "IN_PROGRESS"
    store.touch(milestone)


def successor_of(milestone):
    for row in derive.milestones_of(milestone["engagement_id"]):
        if row["sequence_index"] == milestone["sequence_index"] + 1:
            return row
    return None


def complete_milestone(milestone, completed_by_party_id):
    milestone["status"] = "COMPLETE"
    milestone["completed_at_utc"] = store.now_iso()
    if completed_by_party_id is not None:
        milestone["completed_by_party_id"] = completed_by_party_id
    if milestone["overdue_status"] == "OVERDUE":
        milestone["overdue_status"] = "RECOVERED"
    store.touch(milestone)
    start_milestone(successor_of(milestone))


def reopen_milestone(milestone):
    """COMPLETE -> REOPENED and, in the same request, REOPENED -> IN_PROGRESS.

    PRD 3.10: "REOPENED never rests: in the same request the milestone returns
    to IN_PROGRESS". The observable resting status after a reopen is therefore
    IN_PROGRESS, not REOPENED.
    """
    milestone["reopen_count"] = milestone["reopen_count"] + 1
    milestone["status"] = "REOPENED"
    milestone["completed_at_utc"] = None
    if milestone["overdue_status"] == "RECOVERED":
        milestone["overdue_status"] = "OVERDUE"
    milestone["status"] = "IN_PROGRESS"
    store.touch(milestone)


def cascade_complete_milestone(engagement_id, key):
    """System cascade: fire only when the milestone's own from-state matches."""
    milestone = derive.milestone_by_key(engagement_id, key)
    if milestone is None or milestone["status"] not in ("IN_PROGRESS", "REOPENED"):
        return False
    complete_milestone(milestone, None)
    return True


def cascade_reopen_milestone(engagement_id, key):
    """System cascade guarded by the transition's own preconditions."""
    milestone = derive.milestone_by_key(engagement_id, key)
    if milestone is None or milestone["status"] != "COMPLETE":
        return False
    if milestone["reopen_count"] >= K.MAX_MILESTONE_REOPENS:
        return False
    for row in derive.milestones_of(engagement_id):
        if row["sequence_index"] > milestone["sequence_index"] and row["status"] == "COMPLETE":
            return False
    reopen_milestone(milestone)
    return True


# ---------------------------------------------------------------------------
# engagement creation
# ---------------------------------------------------------------------------

def create_engagement_children(engagement, acting_role):
    for index, key in enumerate(K.MILESTONE_ORDER, start=1):
        record = store.base_record()
        record.update({
            "engagement_id": engagement["id"],
            "completed_by_party_id": None,
            "milestone_key": key,
            "sequence_index": index,
            "status": "IN_PROGRESS" if index == 1 else "PENDING",
            "overdue_status": "ON_TIME",
            "completed_at_utc": None,
            "reopen_count": 0,
        })
        store.insert("milestones", record)

    invoice = store.base_record()
    invoice.update({
        "engagement_id": engagement["id"],
        "status": "DRAFT",
        "coordination_fee_cents": 0,
        "payments_cents": 0,
        "recall_count": 0,
        "dispute_count": 0,
        "dispute_reason": None,
        "issued_at_utc": None,
        "finalized_at_utc": None,
    })
    store.insert("invoices", invoice)

    if engagement["billing_mode"] == "PACKAGE":
        amount = calc.package_base_charge(engagement["package_tier"])
        append_line(invoice, "PACKAGE_BASE", amount, "Package base charge", acting_role)
        # the invoice was created by this same request; its version stays at 1
        invoice["version"] = 1
    return invoice


# ---------------------------------------------------------------------------
# sort-plan approval cascade
# ---------------------------------------------------------------------------

def sort_plan_approval_cascade(plan, engagement, acting_role):
    # hop 1 - lock every non-UNDECIDED item
    for item in derive.items_of(engagement["id"]):
        if item["disposition"] != "UNDECIDED" and not item["disposition_locked"]:
            item["disposition_locked"] = True
            store.touch(item)
    # hop 2 - haul volume is a pure rollup and is therefore already current
    haul_volume = derive.haul_volume_cft(engagement["id"])
    # hop 3 - auto-order the junk haul
    if haul_volume >= D(K.HAUL_MIN_LOAD_CFT):
        existing = [a for a in store.where("vendor_assignments", engagement_id=engagement["id"])
                    if a["service_kind"] == "HAUL_AWAY"]
        if not existing:
            vendor = None
            for candidate in store.all_of("vendors"):
                if candidate["vendor_type"] == "JUNK_HAUL":
                    vendor = candidate
                    break
            if vendor is not None:
                record = store.base_record()
                record.update({
                    "engagement_id": engagement["id"],
                    "vendor_id": vendor["id"],
                    "signed_off_by_party_id": None,
                    "service_kind": "HAUL_AWAY",
                    "service_date": parse_dt(
                        engagement["scheduled_move_start_utc"]).date().isoformat(),
                    "status": "REQUESTED",
                    "quoted_cents": K.HAUL_AUTO_QUOTE_CENTS,
                    "holdback_cents": 0,
                    "paid_cents": 0,
                    "holdback_released": False,
                    "performed_at_utc": None,
                    "cancel_reason": None,
                })
                store.insert("vendor_assignments", record)
    # hop 4 - complete the SORT_PLAN milestone, starting PACK
    cascade_complete_milestone(engagement["id"], "SORT_PLAN")


# ---------------------------------------------------------------------------
# move-day completion cascade (six hops)
# ---------------------------------------------------------------------------

def move_day_completion_cascade(plan, engagement):
    now = store.now_iso()
    # hop 1 - close out every assignment still CHECKED_IN
    for assignment in derive.assignments_of_plan(plan["id"]):
        if assignment["status"] != "CHECKED_IN":
            continue
        assignment["status"] = "COMPLETED"
        assignment["checked_out_at_utc"] = now
        create_time_entry(assignment, "LABOR", assignment["checked_in_at_utc"], now)
        store.touch(assignment)
    # hops 2 and 3 - assignment money and the engagement rollups are pure
    # functions of the rows hop 1 just wrote, so they are already current.
    # hop 4 - the pipeline labour line
    invoice = derive.invoice_of(engagement["id"])
    if engagement["billing_mode"] == "HOURLY":
        amount = derive.accrued_labor_cents(engagement["id"])
        append_line(invoice, "HOURLY_LABOR", amount, "Crew labour", "SYSTEM")
    else:
        overage = calc.package_overage_charge(derive.billing_hours_total(engagement["id"]),
                                              engagement["package_tier"])
        if overage > 0:
            append_line(invoice, "OVERAGE_LABOR", overage, "Package overage labour", "SYSTEM")
    # hop 5 - the invoice aggregates are pure; the version bump is explicit
    store.touch(invoice)
    # hop 6 - complete the MOVE_DAY milestone, starting SETTLE_IN
    cascade_complete_milestone(engagement["id"], "MOVE_DAY")


def create_time_entry(assignment, entry_kind, started_at_utc, ended_at_utc):
    raw, rounded = calc.time_entry_hours(started_at_utc, ended_at_utc)
    record = store.base_record()
    record.update({
        "crew_assignment_id": assignment["id"],
        "entry_kind": entry_kind,
        "started_at_utc": started_at_utc,
        "ended_at_utc": ended_at_utc,
        "raw_hours": str(raw),
        "rounded_hours": str(rounded),
        "voided": False,
        "void_reason": None,
    })
    return store.insert("time_entries", record)


# ---------------------------------------------------------------------------
# invoice issue
# ---------------------------------------------------------------------------

def issue_invoice(invoice, engagement, acting_role):
    plan = derive.move_day_plan_of(engagement["id"])
    crew_count = derive.crew_confirmed_count(plan) if plan is not None else 0

    travel = calc.travel_surcharge(engagement["mileage_miles"])
    stairs = calc.stairs_surcharge(engagement["origin_stairs_flights"], crew_count)
    long_carry = calc.long_carry_surcharge(engagement["origin_long_carry_feet"])
    append_line(invoice, "TRAVEL_SURCHARGE", travel, "Travel surcharge", acting_role)
    append_line(invoice, "STAIRS_SURCHARGE", stairs, "Stairs surcharge", acting_role)
    append_line(invoice, "LONG_CARRY_SURCHARGE", long_carry, "Long carry surcharge", acting_role)

    subtotal = derive.invoice_subtotal(invoice)
    fee = calc.invoice_coordination_fee(subtotal)
    invoice["coordination_fee_cents"] = fee
    append_line(invoice, "COORDINATION_FEE", fee, "Coordination fee", acting_role)

    invoice["status"] = "ISSUED"
    invoice["issued_at_utc"] = store.now_iso()
    store.touch(invoice)


def projected_total_cents(engagement):
    """The value Invoice.total_cents WOULD take were the invoice issued now."""
    invoice = derive.invoice_of(engagement["id"])
    if invoice is None:
        return 0
    plan = derive.move_day_plan_of(engagement["id"])
    crew_count = derive.crew_confirmed_count(plan) if plan is not None else 0
    subtotal = derive.invoice_subtotal(invoice)
    subtotal += calc.travel_surcharge(engagement["mileage_miles"])
    subtotal += calc.stairs_surcharge(engagement["origin_stairs_flights"], crew_count)
    subtotal += calc.long_carry_surcharge(engagement["origin_long_carry_feet"])
    fee = calc.invoice_coordination_fee(subtotal)
    return subtotal + fee + derive.invoice_credits(invoice)


# ---------------------------------------------------------------------------
# ops run
# ---------------------------------------------------------------------------

def ops_run(engagement):
    now = store.now_iso()
    clock_date = parse_dt(now).date()

    flagged = 0
    for milestone in derive.milestones_of(engagement["id"]):
        if milestone["status"] not in ("PENDING", "IN_PROGRESS", "REOPENED"):
            continue
        due_on = calc.milestone_due_on(engagement["scheduled_move_start_utc"],
                                       milestone["milestone_key"])
        if clock_date > parse_date(due_on) and milestone["overdue_status"] == "ON_TIME":
            milestone["overdue_status"] = "OVERDUE"
            store.touch(milestone)
            flagged += 1

    expired = 0
    for record in store.where("authority_records", engagement_id=engagement["id"]):
        if record["status"] not in ("PENDING", "ACTIVE", "SUSPENDED"):
            continue
        if parse_dt(now) >= parse_dt(record["effective_to_utc"]):
            record["status"] = "EXPIRED"
            store.touch(record)
            expired += 1

    blocked = 0
    for assignment in store.where("vendor_assignments", engagement_id=engagement["id"]):
        if assignment["status"] != "SCHEDULED":
            continue
        vendor = store.get("vendors", assignment["vendor_id"])
        if vendor is None:
            continue
        if parse_date(vendor["coi_expires_on"]) < parse_date(assignment["service_date"]):
            assignment["status"] = "COI_BLOCKED"
            store.touch(assignment)
            blocked += 1

    engagement["ops_run_seq"] = engagement["ops_run_seq"] + 1
    store.touch(engagement)
    return flagged, expired, blocked


# ---------------------------------------------------------------------------
# listing helper
# ---------------------------------------------------------------------------

def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
