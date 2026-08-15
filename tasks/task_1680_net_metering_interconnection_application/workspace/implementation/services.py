"""Business logic: capacity ledger, queue, screening, netting, true-up,
release cascades (PRD 3 / scaffold 1.2-1.3)."""

import datetime

import clock as clockmod
from store import db, stamp_new, touch

# ---------------------------------------------------------------------------
# Constants (scaffold 1.3)
# ---------------------------------------------------------------------------

CLASS_CAP_WATTS = {
    "RESIDENTIAL": 25000,
    "COMMERCIAL": 1000000,
    "INDUSTRIAL": 5000000,
}
SIZE_TO_LOAD_LIMIT_PCT = 110
TRANSFORMER_LIMIT_PCT = 50
FEEDER_LIMIT_PCT = 15
FAST_TRACK_LIMIT_WATTS = 2000000
ESTIMATE_VALIDITY_DAYS = 30
RESERVATION_VALIDITY_DAYS = 180
TRUE_UP_RUN_WINDOW_DAYS = 60
CREW_BUFFER_MINUTES = 30

REQUIRED_DOC_TYPES = ("SITE_PLAN", "SINGLE_LINE_DIAGRAM", "INSURANCE_CERTIFICATE")

RESERVATION_HOLDING = (
    "CAPACITY_RESERVED",
    "SUPPLEMENTAL_REVIEW",
    "SCREEN_PASSED",
    "AWAITING_COST_ESTIMATE",
    "CUSTOMER_DECISION_PENDING",
    "UPGRADE_IN_PROGRESS",
)
INTERCONNECTED = ("PTO_GRANTED", "OPERATING")
TERMINAL = ("WITHDRAWN", "DENIED", "OPERATING")
WITHDRAWABLE = (
    "DRAFT",
    "PENDING_COMPLETENESS",
    "INCOMPLETE",
    "WAITING_FOR_CAPACITY",
    "CAPACITY_RESERVED",
    "SUPPLEMENTAL_REVIEW",
    "SCREEN_PASSED",
    "AWAITING_COST_ESTIMATE",
    "CUSTOMER_DECISION_PENDING",
    "UPGRADE_IN_PROGRESS",
)


def round_half_up_milli(wh_times_millicents):
    """round_half_up(x / 1_000_000) for a non-negative integer numerator."""
    return (wh_times_millicents + 500000) // 1000000


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def account_of(application):
    return db.accounts.get(application["service_account_id"])


def program_of(application):
    return db.programs.get(application["program_id"])


def transformer_of(account):
    return db.transformers.get(account["transformer_id"])


def feeder_of(account):
    transformer = transformer_of(account)
    return db.feeders.get(transformer["feeder_id"]) if transformer else None


def account_program(account):
    """The program under which the account is net-metered: the program of its
    PTO_GRANTED/OPERATING application (latest when several)."""
    apps = [
        a for a in db.applications.values()
        if a["service_account_id"] == account["id"]
        and a["application_status"] in INTERCONNECTED
    ]
    if not apps:
        return None
    apps.sort(key=lambda a: (a["created_at"], a["_seq"]))
    return db.programs.get(apps[-1]["program_id"])


def applications_of_program(program_id):
    return [a for a in db.applications.values() if a["program_id"] == program_id]


def applications_of_account(account_id):
    return [a for a in db.applications.values() if a["service_account_id"] == account_id]


def effective_tariff(program_id, instant):
    """The schedule of the program whose half-open window covers `instant`."""
    for tariff in db.tariffs.values():
        if tariff["program_id"] != program_id:
            continue
        if tariff["_from"] <= instant and (tariff["_to"] is None or instant < tariff["_to"]):
            return tariff
    return None


# ---------------------------------------------------------------------------
# Program capacity ledger (PRD 2.7)
# ---------------------------------------------------------------------------

def program_available(program):
    return (
        program["aggregate_cap_watts"]
        - program["interconnected_watts"]
        - program["reserved_watts"]
    )


def recompute_posture(program):
    available = program_available(program)
    if available <= 0 and program["program_status"] == "OPEN":
        program["program_status"] = "CAP_REACHED"
        touch(program)
    elif available > 0 and program["program_status"] == "CAP_REACHED":
        program["program_status"] = "OPEN"
        touch(program)


# ---------------------------------------------------------------------------
# Capacity queue (PRD 3.3 / 3.6)
# ---------------------------------------------------------------------------

def queued_applications(program_id):
    rows = [
        a for a in db.applications.values()
        if a["program_id"] == program_id
        and a["application_status"] == "WAITING_FOR_CAPACITY"
    ]
    rows.sort(key=lambda a: (a["queue_position"], a["_seq"]))
    return rows


def enqueue(application):
    program = program_of(application)
    existing = queued_applications(program["id"])
    position = max(a["queue_position"] for a in existing) + 1 if existing else 1
    application["queue_position"] = position
    application["application_status"] = "WAITING_FOR_CAPACITY"
    program["queued_count"] += 1
    touch(program)
    touch(application)


def _close_queue_gap(program, departed_position):
    for other in queued_applications(program["id"]):
        if other["queue_position"] > departed_position:
            other["queue_position"] -= 1
            touch(other)


def dequeue(application):
    """Remove a queued application from the queue, closing the gap."""
    program = program_of(application)
    position = application["queue_position"]
    others = [a for a in queued_applications(program["id"]) if a["id"] != application["id"]]
    application["queue_position"] = None
    program["queued_count"] -= 1
    for other in others:
        if other["queue_position"] > position:
            other["queue_position"] -= 1
            touch(other)
    touch(program)


def reserve_capacity(application):
    program = program_of(application)
    application["capacity_reserved_watts"] = application["system_size_watts_ac"]
    application["reservation_expires_at"] = (
        clockmod.now() + datetime.timedelta(days=RESERVATION_VALIDITY_DAYS)
    )
    application["application_status"] = "CAPACITY_RESERVED"
    program["reserved_watts"] += application["system_size_watts_ac"]
    touch(program)
    touch(application)
    recompute_posture(program)


def release_reservation(application):
    """Return the application's reserved watts to the program (PRD 3.6)."""
    if application["capacity_reserved_watts"] > 0:
        program = program_of(application)
        program["reserved_watts"] -= application["capacity_reserved_watts"]
        application["capacity_reserved_watts"] = 0
        application["reservation_expires_at"] = None
        touch(program)


def promotion_scan(program):
    """Waterfall allocation over the queue, ascending queue_position (PRD 3.6)."""
    for candidate in queued_applications(program["id"]):
        if candidate["application_status"] != "WAITING_FOR_CAPACITY":
            continue
        if program_available(program) >= candidate["system_size_watts_ac"]:
            position = candidate["queue_position"]
            candidate["queue_position"] = None
            candidate["capacity_reserved_watts"] = candidate["system_size_watts_ac"]
            candidate["reservation_expires_at"] = (
                clockmod.now() + datetime.timedelta(days=RESERVATION_VALIDITY_DAYS)
            )
            candidate["application_status"] = "CAPACITY_RESERVED"
            program["reserved_watts"] += candidate["system_size_watts_ac"]
            program["queued_count"] -= 1
            _close_queue_gap(program, position)
            touch(candidate)
            touch(program)


# ---------------------------------------------------------------------------
# Release cascade (PRD 3.6)
# ---------------------------------------------------------------------------

def cancel_children(application):
    for review in db.reviews.values():
        if review["application_id"] == application["id"] and review["review_status"] == "OPEN":
            review["review_status"] = "CLOSED"
            touch(review)
    for estimate in db.estimates.values():
        if estimate["application_id"] == application["id"] and estimate["estimate_status"] == "ISSUED":
            estimate["estimate_status"] = "CANCELLED"
            touch(estimate)
    for inspection in db.inspections.values():
        if inspection["application_id"] == application["id"] and inspection["inspection_status"] == "SCHEDULED":
            inspection["inspection_status"] = "CANCELLED"
            touch(inspection)
    for exchange in db.exchanges.values():
        if exchange["application_id"] == application["id"] and exchange["exchange_status"] in ("SCHEDULED", "FAILED"):
            exchange["exchange_status"] = "CANCELLED"
            touch(exchange)


def withdraw_application(application, reason, run_scan=True):
    """Shared withdrawal cascade (PRD 3.6, sweep 2.4)."""
    program = program_of(application)
    if application["application_status"] == "WAITING_FOR_CAPACITY":
        dequeue(application)
    release_reservation(application)
    application["application_status"] = "WITHDRAWN"
    application["withdrawal_reason"] = reason
    cancel_children(application)
    touch(application)
    if run_scan:
        promotion_scan(program)
    recompute_posture(program)


# ---------------------------------------------------------------------------
# Eligibility (PRD 3.3)
# ---------------------------------------------------------------------------

def eligibility_denial_reason(account, size_watts, production_wh):
    """Size checked first; production boundary is inclusive (== passes)."""
    if size_watts > CLASS_CAP_WATTS[account["service_class"]]:
        return "SIZE_EXCEEDS_CLASS_CAP"
    production_cap = account["prior_annual_usage_wh"] * SIZE_TO_LOAD_LIMIT_PCT // 100
    if production_wh > production_cap:
        return "PRODUCTION_EXCEEDS_LOAD"
    return None


# ---------------------------------------------------------------------------
# Grid aggregates and technical screens (PRD 3.1 / 3.4)
# ---------------------------------------------------------------------------

def _on_transformer(application, transformer_id):
    account = db.accounts.get(application["service_account_id"])
    return account is not None and account["transformer_id"] == transformer_id


def _on_feeder(application, feeder_id):
    account = db.accounts.get(application["service_account_id"])
    if account is None:
        return False
    transformer = db.transformers.get(account["transformer_id"])
    return transformer is not None and transformer["feeder_id"] == feeder_id


def node_aggregate_der(node_kind, node):
    """aggregate_der_watts (PRD 3.1): pre-existing plus reserved and
    interconnected watts of applications on the node; queued never count."""
    on_node = _on_transformer if node_kind == "transformer" else _on_feeder
    total = node["pre_existing_der_watts"]
    for application in db.applications.values():
        if not on_node(application, node["id"]):
            continue
        status = application["application_status"]
        if status in RESERVATION_HOLDING:
            total += application["capacity_reserved_watts"]
        elif status in INTERCONNECTED:
            total += application["system_size_watts_ac"]
    return total


def screening_basis_aggregate(node_kind, node, program, screened_application):
    """The basis aggregate of PRD 3.4: pre-existing + other reservation
    holders + interconnected (+ queued under INCLUDE_QUEUED), excluding the
    screened application itself."""
    on_node = _on_transformer if node_kind == "transformer" else _on_feeder
    total = node["pre_existing_der_watts"]
    for application in db.applications.values():
        if application["id"] == screened_application["id"]:
            continue
        if not on_node(application, node["id"]):
            continue
        status = application["application_status"]
        if status in RESERVATION_HOLDING:
            total += application["capacity_reserved_watts"]
        elif status in INTERCONNECTED:
            total += application["system_size_watts_ac"]
        elif status == "WAITING_FOR_CAPACITY" and program["screening_basis"] == "INCLUDE_QUEUED":
            total += application["system_size_watts_ac"]
    return total


# ---------------------------------------------------------------------------
# Credit ledger (PRD 2.8) and monthly netting (PRD 3.9)
# ---------------------------------------------------------------------------

def post_ledger_entry(service_account_id, entry_type, amount_cents, quantity_wh,
                      meter_reading_id=None, annual_reconciliation_id=None,
                      reversal_of_bank=False):
    entry = {
        "service_account_id": service_account_id,
        "meter_reading_id": meter_reading_id,
        "annual_reconciliation_id": annual_reconciliation_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "quantity_wh": quantity_wh,
        "posted_at": clockmod.now(),
        "_reversal_of_bank": reversal_of_bank,
    }
    stamp_new(entry, versioned=False)
    db.ledger[entry["id"]] = entry
    return entry


def account_balances(account_id):
    """credit_balance_cents / banked_wh projections over the append-only ledger."""
    credit = 0
    banked = 0
    for entry in db.ledger.values():
        if entry["service_account_id"] != account_id:
            continue
        credit += entry["amount_cents"]
        if entry["entry_type"] in ("BANK_DEPOSIT", "BANK_DRAW", "BANK_FORFEIT"):
            banked += entry["quantity_wh"]
        elif entry["entry_type"] == "REVERSAL" and entry.get("_reversal_of_bank"):
            banked += entry["quantity_wh"]
    return credit, banked


def reverse_reading_entries(reading):
    """Append REVERSAL entries negating the reading's original postings."""
    originals = [
        e for e in db.ledger.values()
        if e.get("meter_reading_id") == reading["id"] and e["entry_type"] != "REVERSAL"
    ]
    originals.sort(key=lambda e: e["_seq"])
    for original in originals:
        post_ledger_entry(
            service_account_id=reading["service_account_id"],
            entry_type="REVERSAL",
            amount_cents=-original["amount_cents"],
            quantity_wh=-original["quantity_wh"],
            meter_reading_id=reading["id"],
            reversal_of_bank=original["entry_type"] in ("BANK_DEPOSIT", "BANK_DRAW", "BANK_FORFEIT"),
        )


def apply_monthly_netting(reading, account, program, tariff):
    """Compute the bill and post the ledger entries of PRD 3.9."""
    import_wh = reading["import_wh"]
    export_wh = reading["export_wh"]
    offset_wh = min(import_wh, export_wh)
    surplus_wh = export_wh - offset_wh
    billable_import_wh = import_wh - offset_wh
    raw_bill_cents = round_half_up_milli(
        billable_import_wh * tariff["import_rate_millicents_per_kwh"]
    )
    reading["credit_applied_cents"] = 0
    reading["bank_drawn_wh"] = 0
    reading["bank_deposited_wh"] = 0
    if program["metering_variant"] == "MONETARY_CREDIT":
        surplus_credit_cents = round_half_up_milli(
            surplus_wh * tariff["export_rate_millicents_per_kwh"]
        )
        if surplus_credit_cents > 0:
            post_ledger_entry(
                account["id"], "EXPORT_SURPLUS_CREDIT",
                surplus_credit_cents, surplus_wh,
                meter_reading_id=reading["id"],
            )
        credit_balance, _ = account_balances(account["id"])
        credit_draw_cents = min(credit_balance, raw_bill_cents)
        if credit_draw_cents > 0:
            post_ledger_entry(
                account["id"], "CREDIT_APPLIED",
                -credit_draw_cents, 0,
                meter_reading_id=reading["id"],
            )
        reading["bill_cents"] = raw_bill_cents - credit_draw_cents
        reading["credit_applied_cents"] = credit_draw_cents
    else:  # ENERGY_BANKING
        net_wh = import_wh - export_wh
        if net_wh > 0:
            _, banked_wh = account_balances(account["id"])
            bank_drawn_wh = min(banked_wh, net_wh)
            if bank_drawn_wh > 0:
                post_ledger_entry(
                    account["id"], "BANK_DRAW",
                    0, -bank_drawn_wh,
                    meter_reading_id=reading["id"],
                )
            billable_wh = net_wh - bank_drawn_wh
            reading["bill_cents"] = round_half_up_milli(
                billable_wh * tariff["import_rate_millicents_per_kwh"]
            )
            reading["bank_drawn_wh"] = bank_drawn_wh
        else:
            bank_deposited_wh = -net_wh
            if bank_deposited_wh > 0:
                post_ledger_entry(
                    account["id"], "BANK_DEPOSIT",
                    0, bank_deposited_wh,
                    meter_reading_id=reading["id"],
                )
            reading["bill_cents"] = 0
            reading["bank_deposited_wh"] = bank_deposited_wh
