"""Derived projections and multi-hop cascades (PRD 2.10, 3.2, 3.4, 3.9)."""
import calc
import store
from common import (D, EARLY_WINDOW_DAYS, GRACE_DAYS, READING_WINDOW, add_days,
                    whole_days_between)

OPEN_COMPLAINT_STATUSES = ("OPEN", "DIAGNOSING", "AWAITING_PARTS", "ESCALATED")
OPEN_VISIT_STATUSES = ("SCHEDULED", "IN_PROGRESS")


# ------------------------------------------------------------------ beer line

def posted_line_cycles(line_id):
    return [c for c in store.line_cycles(line_id) if c["record_status"] == "POSTED"]


def newest_posted_cycle(line_id, only_pass=False):
    rows = posted_line_cycles(line_id)
    if only_pass:
        rows = [c for c in rows if c["compliance_result"] == "PASS"]
    rows = store.newest_first(rows, "logged_at")
    return rows[0] if rows else None


def frequency_days_for(account_id):
    contract = store.active_contract(account_id)
    if contract is not None:
        return contract["cleaning_frequency_days"]
    fallback = [c for c in store.account_contracts(account_id) if c["status"] != "EXPIRED"]
    if fallback:
        return store.by_created_desc(fallback)[0]["cleaning_frequency_days"]
    return None


def line_next_due_at(line):
    last_cleaned = line.get("last_cleaned_at")
    if last_cleaned is None:
        return None
    days = frequency_days_for(line["account_id"])
    if days is None:
        return None
    return add_days(last_cleaned, days)


def line_days_overdue(line):
    due = line_next_due_at(line)
    if due is None:
        return 0
    return max(0, whole_days_between(store.now(), due))


def line_compliance_flag(line):
    if line.get("compliance_grade_flag") == "NON_COMPLIANT":
        return "NON_COMPLIANT"
    if line_days_overdue(line) > GRACE_DAYS:
        return "NON_COMPLIANT"
    return "COMPLIANT"


def newest_applied_balance(line_id):
    rows = [r for r in store.line_balance_records(line_id) if r["status"] == "APPLIED"]
    rows = store.by_created_desc(rows)
    return rows[0] if rows else None


def refresh_line_history(line):
    """Re-derive last_chemical_type / last_cleaned_at from the surviving cycles."""
    changed = False
    newest = newest_posted_cycle(line["id"])
    chem = newest["chemical_type"] if newest is not None else "NONE"
    newest_pass = newest_posted_cycle(line["id"], only_pass=True)
    cleaned = newest_pass["logged_at"] if newest_pass is not None else None
    if line["last_chemical_type"] != chem:
        line["last_chemical_type"] = chem
        changed = True
    if line["last_cleaned_at"] != cleaned:
        line["last_cleaned_at"] = cleaned
        changed = True
    return changed


def replay_line_grade(line):
    """Grade component of compliance_flag, replayed from remaining POSTED cycles."""
    failing = [c for c in posted_line_cycles(line["id"])
               if c["compliance_result"] != "PASS"]
    flag = "NON_COMPLIANT" if failing else "COMPLIANT"
    if line["compliance_grade_flag"] != flag:
        line["compliance_grade_flag"] = flag
        return True
    return False


def take_line_out_of_service(line):
    """A failure takes the line OUT_OF_SERVICE and supersedes its applied balance."""
    changed = False
    if line["status"] == "IN_SERVICE":
        line["status"] = "OUT_OF_SERVICE"
        changed = True
    for record in store.sort_created(store.line_balance_records(line["id"])):
        if record["status"] == "APPLIED":
            record["status"] = "SUPERSEDED"
            store.touch(record)
    return changed


# -------------------------------------------------------------- service account

def recompute_account_counters(account):
    changed = False
    out_of_service = len([l for l in store.account_lines(account["id"])
                          if l["status"] == "OUT_OF_SERVICE"])
    if account["lines_out_of_service_count"] != out_of_service:
        account["lines_out_of_service_count"] = out_of_service
        changed = True
    open_complaints = len([c for c in store.account_complaints(account["id"])
                           if c["status"] in OPEN_COMPLAINT_STATUSES])
    if account["open_complaint_count"] != open_complaints:
        account["open_complaint_count"] = open_complaints
        changed = True
    if changed:
        store.touch(account)
    return changed


def recompute_billing_mode(account):
    contract = store.active_contract(account["id"])
    mode = "PROGRAM_BILL" if (contract is not None
                              and contract["funding_status"] == "BREWER_FUNDED") else "DIRECT_BILL"
    if account["billing_mode"] != mode:
        account["billing_mode"] = mode
        store.touch(account)
        return True
    return False


def recompute_contract_funding_status(contract):
    program_id = contract.get("brewer_program_id")
    if program_id is None:
        status = "NONE"
    else:
        program = store.programs.get(program_id)
        if program is not None and program["status"] == "ACTIVE":
            status = "BREWER_FUNDED"
        else:
            status = "SELF_FUNDED"
    if contract["funding_status"] != status:
        contract["funding_status"] = status
        store.touch(contract)
        return True
    return False


def contracted_line_count_for_threshold(account_id):
    contract = store.active_contract(account_id)
    if contract is not None:
        return contract["contracted_line_count"]
    return None


def evaluate_suspension_threshold(account):
    """Half or more of the contracted lines out of service suspends the account."""
    if account["status"] != "ACTIVE":
        return False
    limit = contracted_line_count_for_threshold(account["id"])
    if limit is None:
        return False
    if account["lines_out_of_service_count"] * 2 >= limit:
        suspend_account(account, "LINE_COMPLIANCE_THRESHOLD")
        return True
    return False


def suspend_account(account, reason):
    account["status"] = "SUSPENDED"
    account["suspended_reason"] = reason
    store.touch(account)
    for contract in store.account_contracts(account["id"]):
        if contract["status"] == "ACTIVE":
            contract["status"] = "SUSPENDED"
            store.touch(contract)
    abandon_open_visits(account["id"], "ACCOUNT_SUSPENDED")
    recompute_billing_mode(account)


def abandon_open_visits(account_id, reason):
    """Only SCHEDULED visits are abandoned by a suspension cascade (3.4 hop three)."""
    rows = [v for v in store.account_visits(account_id)
            if v["work_status"] == "SCHEDULED"]
    rows.sort(key=lambda v: (v["scheduled_date"], v["scheduled_start_minute"],
                             v["created_at"], v["_seq"]))
    for visit in rows:
        visit["work_status"] = "ABANDONED"
        visit["abandon_reason"] = reason
        store.touch(visit)


def has_open_visits(account_id):
    return any(v["work_status"] in OPEN_VISIT_STATUSES
               for v in store.account_visits(account_id))


# ------------------------------------------------------------------ glycol loop

def loop_window_temps(loop_id):
    rows = store.newest_first(store.loop_readings(loop_id), "reading_at")
    return [r["cooler_temp_f"] for r in rows[:READING_WINDOW]]


def loop_projection(loop):
    return calc.glycol_health(loop["glycol_pct"], loop["pump_psi"],
                              loop["last_serviced_at"], store.now(),
                              loop_window_temps(loop["id"]))


def loop_status(loop):
    return loop_projection(loop)["status"]


# ------------------------------------------------------------------ visit counts

def visit_serviced_line_count(visit_id):
    posted = [c for c in store.visit_cycles(visit_id) if c["record_status"] == "POSTED"]
    return len(set(c["line_id"] for c in posted))


def visit_passed_line_count(visit_id):
    posted = [c for c in store.visit_cycles(visit_id) if c["record_status"] == "POSTED"]
    newest_by_line = {}
    for cycle in store.newest_first(posted, "logged_at"):
        newest_by_line.setdefault(cycle["line_id"], cycle)
    return len([c for c in newest_by_line.values() if c["compliance_result"] == "PASS"])


def visit_parts_charge_cents(visit_id):
    total = 0
    for row in store.visit_inspections(visit_id):
        if row["action_taken"] == "REPLACED":
            total += int(row["part_charge_cents"])
    return total


def visit_eligible_parts_cents(visit_id):
    total = 0
    for row in store.visit_inspections(visit_id):
        if row["action_taken"] != "REPLACED":
            continue
        part = store.parts.get(row.get("part_sku_id"))
        if part is not None and part["brewer_funded_eligible"]:
            total += int(row["part_charge_cents"])
    return total


def early_cleaning_floor(line):
    """A cleaning may land at most EARLY_WINDOW_DAYS before next_due_at."""
    due = line_next_due_at(line)
    if due is None:
        return None
    return add_days(due, -EARLY_WINDOW_DAYS).date()
