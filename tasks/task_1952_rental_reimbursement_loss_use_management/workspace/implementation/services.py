"""Shared domain logic: serialization, derived ledgers, cascades, calculations."""
import uuid
from datetime import date, datetime, timedelta

import db
from errors import api_error, bad_request
from util import (COMPLETION_GRACE_DAYS, DOCUMENTATION_FEE_CAP_CENTS,
                  RETURN_GRACE_DAYS, day_tax_cents, iso_ts, now_ts, parse_date)

# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------


def new_entity(common_fields=True):
    e = {"id": str(uuid.uuid4()), "created_at": now_ts(), "_seq": db.next_seq()}
    if common_fields:
        e["updated_at"] = e["created_at"]
        e["version"] = 1
    return e


def bump(entity):
    """version increments by one with every modification; updated_at refreshes."""
    entity["version"] += 1
    entity["updated_at"] = now_ts()


def _convert(value):
    if isinstance(value, datetime):
        return iso_ts(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _convert(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_convert(v) for v in value]
    return value


def view(entity):
    return {k: _convert(v) for k, v in entity.items() if not k.startswith("_")}


def sorted_by_creation(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


# ---------------------------------------------------------------------------
# Request body helpers (rung 4.5 shape validation -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def need_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or not v:
        raise bad_request("missing or invalid required field: %s" % name)
    return v


def need_int(body, name):
    v = body.get(name)
    if not is_int(v):
        raise bad_request("missing or invalid required field: %s" % name)
    return v


def need_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        raise bad_request("missing or invalid required field: %s" % name)
    return v


def need_date(body, name):
    v = body.get(name)
    d = parse_date(v)
    if d is None:
        raise bad_request("missing or invalid date field: %s" % name)
    return d


def need_enum(body, name, values):
    v = body.get(name)
    if v not in values:
        raise bad_request("missing or invalid enum field: %s" % name)
    return v


def opt_str(body, name, default=None):
    v = body.get(name)
    if v is None:
        return default
    if not isinstance(v, str):
        raise bad_request("invalid field: %s" % name)
    return v


def opt_bool(body, name, default=False):
    v = body.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise bad_request("invalid field: %s" % name)
    return v


# ---------------------------------------------------------------------------
# FK existence (rung 4) helper
# ---------------------------------------------------------------------------


def check_body_fk(body, field, table, error_id):
    """If the FK field is present, it must resolve. Absence is left to shape checks."""
    v = body.get(field)
    if v is not None and v not in table:
        raise api_error(error_id, 404, "%s not found: %s" % (field, v))


# ---------------------------------------------------------------------------
# Claim derived ledgers (rental_reserve_reconciliation, §2.6)
# ---------------------------------------------------------------------------

ESTIMATE_TERM_STATUSES = {"AUTHORIZED", "ACTIVE", "EXTENSION_REVIEW"}
DAYS_TERM_STATUSES = {"AUTHORIZED", "ACTIVE", "EXTENSION_REVIEW", "RETURNED"}
RECOVERY_OPEN_STATUSES = {"OPEN", "PARTIAL_RECOVERY"}


def claim_reservations(claim_id):
    return [r for r in db.reservations.values() if r["claim_id"] == claim_id]


def claim_lou_claims(claim_id):
    return [l for l in db.lou_claims.values() if l["claim_id"] == claim_id]


def claim_recovery_cases(claim_id):
    return [rc for rc in db.recovery_cases.values() if rc["claim_id"] == claim_id]


def rental_reserve_cents(claim):
    base = claim["coverage_daily_limit_cents"] * claim["coverage_duration_cap_days"]
    est = sum(r["estimated_charge_cents"] for r in claim_reservations(claim["id"])
              if r["status"] in ESTIMATE_TERM_STATUSES)
    settled = 0
    for inv in db.invoices.values():
        if inv["status"] != "SETTLED":
            continue
        res = db.reservations.get(inv["reservation_id"])
        if res is not None and res["claim_id"] == claim["id"]:
            settled += inv["audited_payable_cents"] or 0
    return base - est - settled


def authorized_days_total(claim):
    return sum(r["authorized_days"] for r in claim_reservations(claim["id"])
               if r["status"] in DAYS_TERM_STATUSES)


def recovery_balance_cents(claim):
    return sum(rc["outstanding_amount_cents"] for rc in claim_recovery_cases(claim["id"])
               if rc["status"] in RECOVERY_OPEN_STATUSES)


def reservation_audited_charge_cents(reservation):
    return sum((inv["audited_payable_cents"] or 0) for inv in db.invoices.values()
               if inv["reservation_id"] == reservation["id"] and inv["status"] == "SETTLED")


def claim_view(claim):
    v = view(claim)
    v["rental_reserve_cents"] = rental_reserve_cents(claim)
    v["authorized_days_total"] = authorized_days_total(claim)
    v["recovery_balance_cents"] = recovery_balance_cents(claim)
    return v


def reservation_view(reservation):
    v = view(reservation)
    v["audited_charge_cents"] = reservation_audited_charge_cents(reservation)
    return v


# ---------------------------------------------------------------------------
# Shared guards
# ---------------------------------------------------------------------------


def require_claim_open(claim):
    """Rung 6: overall_status must be OPEN for any mutation under the claim."""
    if claim["overall_status"] != "OPEN":
        raise api_error("ERR_CLAIM_NOT_OPEN", 409, "claim is not OPEN")


def get_claim(claim_id):
    claim = db.claims.get(claim_id)
    if claim is None:
        raise api_error("ERR_CLAIM_NOT_FOUND", 404, "claim not found: %s" % claim_id)
    return claim


def get_reservation(reservation_id):
    res = db.reservations.get(reservation_id)
    if res is None:
        raise api_error("ERR_RESERVATION_NOT_FOUND", 404, "reservation not found: %s" % reservation_id)
    return res


def claim_of_reservation(reservation):
    return db.claims[reservation["claim_id"]]


# ---------------------------------------------------------------------------
# Fleet capacity (per-day aggregate semantics)
# ---------------------------------------------------------------------------

CLASS_CAPACITY_FIELD = {
    "ECONOMY": "economy_capacity",
    "STANDARD": "standard_capacity",
    "PREMIUM": "premium_capacity",
}


def fleet_capacity_exceeded(partner, vehicle_class, start_date, end_date, exclude_reservation_id=None):
    """True if on some day d in [start_date, end_date) the partner's same-class
    reservations in {AUTHORIZED, ACTIVE, EXTENSION_REVIEW} occupying d already
    equal the class capacity."""
    capacity = partner[CLASS_CAPACITY_FIELD[vehicle_class]]
    d = start_date
    while d < end_date:
        count = 0
        for r in db.reservations.values():
            if exclude_reservation_id is not None and r["id"] == exclude_reservation_id:
                continue
            if r["rental_partner_id"] != partner["id"]:
                continue
            if r["vehicle_class"] != vehicle_class:
                continue
            if r["status"] not in ESTIMATE_TERM_STATUSES:
                continue
            if r["pickup_date"] <= d < r["authorized_return_date"]:
                count += 1
        if count >= capacity:
            return True
        d += timedelta(days=1)
    return False


# ---------------------------------------------------------------------------
# Audited charge (audited_charge_final, §3.8)
# ---------------------------------------------------------------------------


def class_on_day(reservation, day):
    """Vehicle class in effect on a calendar day: a class change with
    effective_date e applies to all days d >= e until the next change."""
    cls = reservation["_initial_class"]
    changes = sorted_by_creation(
        [c for c in db.class_changes.values() if c["reservation_id"] == reservation["id"]])
    for ch in sorted(changes, key=lambda c: (c["effective_date"], c["_seq"])):
        if ch["effective_date"] <= day:
            cls = ch["to_class"]
    return cls


def audited_charge_final(invoice, reservation, claim):
    """Returns (audited_payable_cents, unauthorized_days)."""
    period_start = invoice["period_start"]
    period_end = invoice["period_end"]
    w_start = max(period_start, reservation["pickup_date"])
    w_end = min(period_end, reservation["authorized_return_date"])
    billed_days = max(0, (period_end - period_start).days)
    window_days = max(0, (w_end - w_start).days)
    unauthorized_days = max(0, billed_days - window_days)
    total = 0
    d = w_start
    while d < w_end:
        rate = reservation["rate_card_snapshot"][class_on_day(reservation, d)]
        day_charge = min(rate, claim["coverage_daily_limit_cents"])
        total += day_charge + day_tax_cents(day_charge)
        d += timedelta(days=1)
    allowed_fees = min(invoice["fees_cents"], DOCUMENTATION_FEE_CAP_CENTS)
    return total + allowed_fees, unauthorized_days


def invoice_auto_approved(invoice, reservation, claim):
    """invoice_auto_adjudication: AUTO_APPROVED iff all five criteria hold."""
    # (a) billed period is a subset of the authorized window
    if not (reservation["pickup_date"] <= invoice["period_start"]
            and invoice["period_end"] <= reservation["authorized_return_date"]):
        return False
    # (b) billed rate equals the reservation's currently applicable rate
    if invoice["daily_rate_cents"] != reservation["daily_rate_cents"]:
        return False
    # (c) no class change record exists on the reservation
    if any(c["reservation_id"] == reservation["id"] for c in db.class_changes.values()):
        return False
    # (d) fees within the documentation-fee cap
    if invoice["fees_cents"] > DOCUMENTATION_FEE_CAP_CENTS:
        return False
    # (e) tax equals the sum of per-day taxes (per-day round-half-up)
    days = (invoice["period_end"] - invoice["period_start"]).days
    per_day = day_tax_cents(min(invoice["daily_rate_cents"], claim["coverage_daily_limit_cents"]))
    if invoice["tax_cents"] != per_day * days:
        return False
    return True


# ---------------------------------------------------------------------------
# Automated cascades
# ---------------------------------------------------------------------------


def create_communication_log(claim_id, channel, template, body_summary):
    entry = new_entity(common_fields=False)
    entry.update({
        "claim_id": claim_id,
        "channel": channel,
        "template": template,
        "body_summary": body_summary,
        "sent_at": db.clock_now(),
    })
    db.communication_logs[entry["id"]] = entry
    return entry


def maybe_rental_track_active(claim):
    """First reservation reaching ACTIVE flips the rental track."""
    if claim["rental_track_status"] == "COVERAGE_VERIFIED":
        claim["rental_track_status"] = "RENTAL_ACTIVE"
        bump(claim)


def maybe_rental_track_closed(claim):
    """All reservations terminal (and at least one exists) closes the rental track."""
    reservations = claim_reservations(claim["id"])
    if not reservations:
        return
    if not all(r["status"] in ("CLOSED", "CANCELLED") for r in reservations):
        return
    if claim["rental_track_status"] == "RENTAL_ACTIVE":
        claim["rental_track_status"] = "RENTAL_CLOSED"
        bump(claim)


def create_recovery_case(claim, reservation, source, unnecessary_days, assessed_amount_cents):
    rc = new_entity()
    rc.update({
        "claim_id": claim["id"],
        "reservation_id": reservation["id"],
        "source": source,
        "unnecessary_days": unnecessary_days,
        "assessed_amount_cents": assessed_amount_cents,
        "recovered_amount_cents": 0,
        "waived_amount_cents": 0,
        "outstanding_amount_cents": assessed_amount_cents,
        "status": "OPEN",
    })
    db.recovery_cases[rc["id"]] = rc
    return rc
