"""Shared gates, selectors and side-effect chains."""

import datetime
import random

import calcs
import clock as clockmod
import serializers as ser
from constants import (
    ARRIVAL_WINDOW_MINUTES,
    DRIVE_BUFFER_MINUTES_PER_STOP,
    LOANER_GRADE_RANK,
    LOCKER_ACCESS_CODE_LENGTH,
    LOCKER_CAPACITY_ITEMS,
    LOCKER_HOLD_HOURS,
    LOCKER_SIZE_RANK,
    LOCKER_TURNAROUND_BUFFER_MINUTES,
    TAXABLE_SOURCES,
)
from errors import ApiError
from store import db, stamp_new, touch

# ---------------------------------------------------------------------------
# Rung 8 -- ownership.
# ---------------------------------------------------------------------------
def own_account(ctx, account_id):
    """AccountOwner may only act on their own account."""
    if ctx.role == "AccountOwner" and account_id is not None:
        if account_id != ctx.user_id:
            raise ApiError("ERR_NOT_ACCOUNT_OWNER")


def acting_technician(ctx):
    """A Technician's X-User-ID must resolve to a Technician row."""
    if ctx.role != "Technician":
        return None
    tech = db.technicians.get(ctx.user_id)
    if tech is None:
        raise ApiError("ERR_NOT_ACCOUNT_OWNER")
    return tech


def own_run_technician(ctx, run):
    """For an operation attached to a van run, the acting technician is the
    one named on the run."""
    acting_technician(ctx)
    if ctx.role == "Technician" and run is not None:
        if run["technician_id"] != ctx.user_id:
            raise ApiError("ERR_NOT_ACCOUNT_OWNER")


# ---------------------------------------------------------------------------
# Rung 9 -- account status.
# ---------------------------------------------------------------------------
def account_active(account):
    if account is not None and account["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_SUSPENDED")


# ---------------------------------------------------------------------------
# Rung 11 -- credit limit.
# ---------------------------------------------------------------------------
def credit_gate(account):
    if account is None:
        return
    if ser.account_outstanding(account["id"]) > account["credit_limit_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_BLOCKED")


# ---------------------------------------------------------------------------
# Rung 12 -- optimistic concurrency.
# ---------------------------------------------------------------------------
def occ(body, field, parent):
    if body.get(field) != parent["version"]:
        raise ApiError("ERR_STALE_VERSION")


# ---------------------------------------------------------------------------
# Allowance ledger.
# ---------------------------------------------------------------------------
def append_allowance_entry(subscription, kind, quantity, reason, request_item_id=None):
    """The ledger never carries a zero-quantity row."""
    if quantity <= 0:
        return None
    entry = stamp_new(
        {
            "subscription_id": subscription["id"],
            "request_item_id": request_item_id,
            "cycle_index": subscription["cycle_index"],
            "kind": kind,
            "quantity": quantity,
            "reason": reason,
        },
        versioned=False,
    )
    db.allowance_entries[entry["id"]] = entry
    return entry


def account_subscription(account_id):
    """The account's live subscription (ACTIVE or PAUSED), if any."""
    rows = [
        s
        for s in db.subscriptions.values()
        if s["account_id"] == account_id and s["status"] in ("ACTIVE", "PAUSED")
    ]
    rows.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Invoices: draft lookup, line append and totals.
# ---------------------------------------------------------------------------
_SOURCE_RANK = {
    "SUBSCRIPTION_FEE": 0,
    "SERVICE": 1,
    "PART": 2,
    "LATE_FEE": 3,
    "PRORATION_CREDIT": 4,
    "WARRANTY_CREDIT": 5,
}


def new_invoice(account, service_request_id=None, billing_period=None, status="DRAFT"):
    invoice = stamp_new(
        {
            "account_id": account["id"],
            "service_request_id": service_request_id,
            "billing_mode": account["billing_mode"],
            "billing_period": billing_period,
            "tax_cents": 0,
            "status": status,
        }
    )
    db.invoices[invoice["id"]] = invoice
    return invoice


def draft_invoice_for(account):
    """The account's DRAFT invoice, minted when none exists (PRD 3.10)."""
    for invoice in db.invoices.values():
        if invoice["account_id"] == account["id"] and invoice["status"] == "DRAFT":
            return invoice
    return new_invoice(account)


def _line_sort_key(line):
    rank = _SOURCE_RANK[line["source"]]
    if line["source"] in ("SERVICE", "PART"):
        item = db.request_items.get(line["request_item_id"])
        inner = (item["created_at"], item["_seq"]) if item else (line["created_at"], line["_seq"])
    elif line["source"] == "LATE_FEE":
        issue = db.loaner_issues.get(line.get("_loaner_issue_id"))
        inner = (issue["created_at"], issue["_seq"]) if issue else (line["created_at"], line["_seq"])
    elif line["source"] == "WARRANTY_CREDIT":
        claim = db.warranty_claims.get(line["source_warranty_claim_id"])
        inner = (claim["created_at"], claim["_seq"]) if claim else (line["created_at"], line["_seq"])
    else:
        # PRORATION_CREDIT and SUBSCRIPTION_FEE keep their insertion order.
        inner = (line["created_at"], line["_seq"])
    return (rank, inner)


def append_line(
    invoice,
    source,
    description,
    amount_cents,
    request_item_id=None,
    source_warranty_claim_id=None,
    loaner_issue_id=None,
):
    line = stamp_new(
        {
            "invoice_id": invoice["id"],
            "request_item_id": request_item_id,
            "source_warranty_claim_id": source_warranty_claim_id,
            "_loaner_issue_id": loaner_issue_id,
            "source": source,
            "description": description,
            "amount_cents": amount_cents,
            "taxable": source in TAXABLE_SOURCES,
            "sequence_index": 0,
        },
        versioned=False,
    )
    db.invoice_lines[line["id"]] = line
    resequence(invoice)
    return line


def resequence(invoice):
    """sequence_index is assigned in the pinned kind order of PRD 3.10."""
    lines = [l for l in db.invoice_lines.values() if l["invoice_id"] == invoice["id"]]
    lines.sort(key=_line_sort_key)
    for index, line in enumerate(lines, start=1):
        line["sequence_index"] = index


def recompute_invoice(invoice):
    """Tax is computed once over the aggregate taxable subtotal, rounded once."""
    account = db.accounts.get(invoice["account_id"])
    taxable = ser.invoice_taxable_subtotal(invoice)
    invoice["tax_cents"] = calcs.invoice_tax(
        taxable, bool(account and account["tax_exempt"])
    )
    return invoice


def invoice_has_lines(invoice):
    return any(l["invoice_id"] == invoice["id"] for l in db.invoice_lines.values())


def invoice_covered_requests(invoice):
    return [
        r
        for r in db.service_requests.values()
        if r.get("_invoice_id") == invoice["id"]
    ]


# ---------------------------------------------------------------------------
# Warranty credit basis (PRD 3.9).
# ---------------------------------------------------------------------------
def credit_basis_for(request_item_id, account_id):
    for line in db.invoice_lines.values():
        if line["source"] != "SERVICE" or line["request_item_id"] != request_item_id:
            continue
        invoice = db.invoices.get(line["invoice_id"])
        if invoice is None or invoice["status"] == "VOID":
            continue
        if invoice["account_id"] != account_id:
            continue
        return line["amount_cents"]
    return 0


# ---------------------------------------------------------------------------
# Locker helpers.
# ---------------------------------------------------------------------------
def mint_access_code():
    return "".join(random.choice("0123456789") for _ in range(LOCKER_ACCESS_CODE_LENGTH))


def hold_expiry():
    return clockmod.now() + datetime.timedelta(hours=LOCKER_HOLD_HOURS)


def compartment_holding(service_request_id):
    for compartment in db.locker_compartments.values():
        if compartment["current_service_request_id"] == service_request_id:
            return compartment
    return None


def select_compartment(service_request):
    """calculations.compartment_assignment_selector, with its pinned empty-pool
    adjudication order (PRD 3.6)."""
    site = service_request["locker_site_code"]
    at_site = [c for c in db.locker_compartments.values() if c["site_code"] == site]
    if not at_site:
        raise ApiError("ERR_NO_AVAILABLE_COMPARTMENT")

    items = ser.request_items(service_request["id"])
    required_rank = 0
    for item in items:
        spec = db.item_class_specs.get(item["item_class_spec_id"])
        if spec is not None:
            required_rank = max(required_rank, LOCKER_SIZE_RANK[spec["min_locker_size"]])
    item_count = len(items)

    available = [c for c in at_site if c["status"] == "AVAILABLE"]
    fitting = [
        c
        for c in available
        if LOCKER_SIZE_RANK[c["size"]] >= required_rank
        and LOCKER_CAPACITY_ITEMS[c["size"]] >= item_count
    ]
    if available and not fitting:
        raise ApiError("ERR_COMPARTMENT_SIZE_UNFIT")

    now = clockmod.now()
    eligible = [
        c
        for c in fitting
        if c["last_released_at"] is None
        or now
        >= c["last_released_at"]
        + datetime.timedelta(minutes=LOCKER_TURNAROUND_BUFFER_MINUTES)
    ]
    if fitting and not eligible:
        raise ApiError("ERR_LOCKER_TURNAROUND_CONFLICT")
    if not eligible:
        raise ApiError("ERR_NO_AVAILABLE_COMPARTMENT")

    eligible.sort(key=lambda c: (LOCKER_SIZE_RANK[c["size"]], c["created_at"], c["_seq"]))
    return eligible[0]


# ---------------------------------------------------------------------------
# Loaner selector and the inspection chain (PRD 3.8).
# ---------------------------------------------------------------------------
def select_loaner_unit(item_class_spec_id, requested_grade):
    pool = [
        u
        for u in db.loaner_units.values()
        if u["status"] == "IN_STOCK"
        and u["item_class_spec_id"] == item_class_spec_id
        and LOANER_GRADE_RANK[u["grade"]] >= LOANER_GRADE_RANK[requested_grade]
    ]
    if not pool:
        raise ApiError("ERR_LOANER_STOCK_EXHAUSTED")
    pool.sort(
        key=lambda u: (
            0 if u["grade"] == requested_grade else 1,
            LOANER_GRADE_RANK[u["grade"]],
            u["cycle_count"],
            u["created_at"],
            u["_seq"],
        )
    )
    return pool[0]


def run_inspection_chain(unit, damage_reported):
    """ISSUED -> INSPECTION -> (RETIRED | IN_STOCK), always inside one request."""
    unit["status"] = "INSPECTION"
    unit["damage_reported"] = bool(damage_reported)
    unit["cycle_count"] += 1
    if unit["cycle_count"] >= unit["cycle_ceiling"] or unit["damage_reported"]:
        unit["status"] = "RETIRED"
    else:
        unit["status"] = "IN_STOCK"
    touch(unit)


def delay_attribution_for(service_request):
    if service_request is None:
        return "CUSTOMER"
    if service_request["origin_warranty_claim_id"]:
        return "SERVICE"
    for item in ser.request_items(service_request["id"]):
        if item["service_status"] == "REWORK_QUEUED":
            return "SERVICE"
    return "CUSTOMER"


def close_loaner_issue(issue, damage_reported=False):
    """OPEN -> RETURNED plus the late fee and the inspection chain."""
    service_request = db.service_requests.get(issue["service_request_id"])
    attribution = delay_attribution_for(service_request)
    now = clockmod.now()
    issue["returned_at"] = now
    issue["delay_attribution"] = attribution
    issue["late_fee_cents"] = calcs.loaner_late_fee(issue["due_at"], now, attribution)
    issue["status"] = "RETURNED"
    touch(issue)

    if issue["late_fee_cents"] > 0 and service_request is not None:
        account = db.accounts.get(service_request["account_id"])
        if account is not None:
            invoice = draft_invoice_for(account)
            append_line(
                invoice,
                "LATE_FEE",
                "Loaner late fee",
                issue["late_fee_cents"],
                loaner_issue_id=issue["id"],
            )
            recompute_invoice(invoice)
            touch(invoice)

    unit = db.loaner_units.get(issue["loaner_unit_id"])
    if unit is not None:
        run_inspection_chain(unit, damage_reported)
    return issue


def open_loaner_issue_for(service_request_id):
    for issue in db.loaner_issues.values():
        if issue["service_request_id"] == service_request_id and issue["status"] == "OPEN":
            return issue
    return None


# ---------------------------------------------------------------------------
# Route helpers.
# ---------------------------------------------------------------------------
def request_active_stop(service_request_id):
    for stop in db.route_stops.values():
        if stop["service_request_id"] == service_request_id and stop["status"] in (
            "SCHEDULED",
            "ARRIVED",
        ):
            return stop
    return None


def windows_overlap(start_a, end_a, start_b, end_b):
    """Half-open intervals; touching endpoints do not intersect."""
    return start_a < end_b and start_b < end_a


def select_receiving_run(stop):
    """calculations.next_eligible_run_selector (PRD 3.5)."""
    account = db.accounts.get(stop["account_id"])
    source_run = db.route_runs.get(stop["spilled_from_route_run_id"])
    if account is None or source_run is None:
        raise ApiError("ERR_NO_ELIGIBLE_RUN")
    minutes = ser.stop_service_minutes(stop)
    candidates = []
    for run in db.route_runs.values():
        if run["status"] != "PLANNED":
            continue
        if run["zone_code"] != account["zone_code"]:
            continue
        if run["run_date"] <= source_run["run_date"]:
            continue
        active = ser.run_active_stops(run["id"])
        if len(active) + 1 > run["stop_cap"]:
            continue
        provisional = ser.run_booked_minutes(run["id"]) + DRIVE_BUFFER_MINUTES_PER_STOP * len(
            active
        )
        if provisional + minutes + DRIVE_BUFFER_MINUTES_PER_STOP > run["service_minute_budget"]:
            continue
        candidates.append(run)
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_RUN")
    candidates.sort(key=lambda r: (r["run_date"], r["created_at"], r["_seq"]))
    return candidates[0]


def next_free_window(run):
    """The earliest 60-minute grid slot inside the run's day window that does
    not overlap a non-terminal stop's window."""
    taken = [
        (s["arrival_window_start"], s["arrival_window_end"])
        for s in ser.run_active_stops(run["id"])
    ]
    start = run["day_window_start"]
    while start + ARRIVAL_WINDOW_MINUTES <= run["day_window_end"]:
        end = start + ARRIVAL_WINDOW_MINUTES
        if not any(windows_overlap(start, end, a, b) for a, b in taken):
            return start
        start += ARRIVAL_WINDOW_MINUTES
    raise ApiError("ERR_WINDOW_OUT_OF_DAY")


def next_sequence(run):
    active = ser.run_active_stops(run["id"])
    if not active:
        return 1
    return 1 + max(s["sequence"] for s in active)
