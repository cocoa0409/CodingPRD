"""Shared state-transition services and cascades."""
import calc
from db import add_days, fmt_dt, parse_dt, store


# -- request derived instants ---------------------------------------------
def restrike_deadline(request):
    """Recompute statutory_deadline_at from its three-step definition."""
    request["is_critical_incident"] = calc.request_is_critical_incident(request)
    request["statutory_deadline_at"] = fmt_dt(calc.statutory_deadline(request))


def stale_active_estimates(request_id):
    for estimate in calc.estimates_of_request(request_id):
        if estimate["status"] == "ACTIVE":
            estimate["status"] = "STALE"


def request_of_record(record):
    return store.get("requests", record["request_id"])


# -- ledger ---------------------------------------------------------------
def write_ledger(request_id, entry_type, amount_cents, memo, source_kind,
                 reverses_entry_id=None):
    """Append one ledger line.  amount_cents is never zero."""
    if amount_cents == 0:
        return None
    return store.insert("fee_ledger_entries", {
        "request_id": request_id,
        "entry_type": entry_type,
        "amount_cents": int(amount_cents),
        "reverses_entry_id": reverses_entry_id,
        "memo": memo,
        "source_kind": source_kind,
    }, common=False)


# -- cross-dimension junctions -------------------------------------------
def close_when_fee_settled(request):
    if request["processing_status"] == "RELEASED" and \
            request["fee_status"] in ("SETTLED", "WAIVED"):
        request["processing_status"] = "CLOSED"


def settle_after_payment(request):
    figures = calc.ledger_figures(request["id"])
    if request["fee_status"] == "DEPOSIT_DUE" and \
            figures["deposit_balance_cents"] >= request["deposit_required_cents"]:
        request["fee_status"] = "DEPOSIT_PAID"
        due_at = parse_dt(request["deposit_due_at"])
        request["tolled_days"] = calc.tolled_days_for_payment(due_at, store.now())
        restrike_deadline(request)
    elif request["fee_status"] == "INVOICED" and \
            figures["deposit_paid_cents"] >= request["invoiced_total_cents"] and \
            figures["deposit_balance_cents"] >= 0:
        request["fee_status"] = "SETTLED"
    close_when_fee_settled(request)


# -- processing auto-advance ----------------------------------------------
def advance_after_task_created(request):
    if request["processing_status"] == "EXEMPTION_REVIEW":
        request["processing_status"] = "REDACTION"


def advance_after_tasks_settled(request):
    """REDACTION -> RELEASE_READY once every task is terminal."""
    if request["processing_status"] != "REDACTION":
        return
    tasks = calc.tasks_of_request(request["id"])
    if any(task["status"] not in calc.TERMINAL_TASK_STATUSES for task in tasks):
        return
    records = calc.records_of_request(request["id"])
    if not any(row["inclusion_status"] == "RESPONSIVE" for row in records):
        return
    request["processing_status"] = "RELEASE_READY"


def advance_after_adjudication(request):
    """The two mutually exclusive outcomes of PRD 3.5, plus link 4."""
    status = request["processing_status"]
    if status == "REDACTION":
        advance_after_tasks_settled(request)
        return
    if status != "EXEMPTION_REVIEW":
        return
    claims = calc.claims_of_request(request["id"])
    if any(claim["status"] == "ASSERTED" for claim in claims):
        return
    records = calc.records_of_request(request["id"])
    restricted = [row for row in records
                  if row["inclusion_status"] == "RESPONSIVE"
                  and row["release_posture"] == "RESTRICTED"]
    if restricted:
        request["processing_status"] = "REDACTION"
        return
    tasks = calc.tasks_of_request(request["id"])
    if any(task["status"] in calc.LIVE_TASK_STATUSES for task in tasks):
        return
    if any(row["inclusion_status"] == "RESPONSIVE" for row in records):
        request["processing_status"] = "RELEASE_READY"


# -- record / task cascades ----------------------------------------------
def cancel_tasks(tasks):
    for task in tasks:
        if task["status"] in calc.LIVE_TASK_STATUSES:
            task["status"] = "CANCELLED"
            task["approved_labor_minutes"] = 0


def withdraw_releases_record(record):
    """WITHHELD_IN_FULL -> RESPONSIVE once no SUSTAINED FULL_WITHHOLD remains."""
    if record["inclusion_status"] != "WITHHELD_IN_FULL":
        return
    for claim in calc.claims_of_record(record["id"]):
        if claim["status"] == "SUSTAINED" and claim["asserted_scope"] == "FULL_WITHHOLD":
            return
    record["inclusion_status"] = "RESPONSIVE"


def deposit_outstanding(request):
    """True when a required deposit is still unpaid (ladder step 30)."""
    if request["fee_status"] != "DEPOSIT_DUE":
        return False
    figures = calc.ledger_figures(request["id"])
    return figures["deposit_paid_cents"] < request["deposit_required_cents"]


def deposit_due_instant():
    return fmt_dt(add_days(store.now(), calc.DEPOSIT_DUE_DAYS))
