"""Shared resource helpers, body validation, lookup utilities.

Syntactic sanity (malformed body, missing required field, wrong type, enum
outside its declared set) yields ERR_INVALID_REQUEST (400) at priority tier 3,
after auth and alongside path-existence checks, before deeper business rules.
"""
import itertools
import uuid
from datetime import timedelta

import db
import errors
import util
from middleware import get_auth, require_roles

# Monotonic creation sequence: created_at is taken from the logical clock and
# can tie to the millisecond; _seq orders same-instant creations by arrival.
_seq_counter = itertools.count(1)


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------

def now_iso():
    return util.clock_iso()


def new_id():
    return str(uuid.uuid4())


def init_common():
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": next(_seq_counter)}


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Request body helpers
# ---------------------------------------------------------------------------

def body_json(required=True):
    from flask import request
    if not request.data:
        if required:
            raise errors.invalid_request("Request body must be a JSON object")
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON")
    if data is None:
        if required:
            raise errors.invalid_request("Request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return data


def req_string(body, field):
    v = body.get(field)
    if v is None:
        raise errors.invalid_request(f"Missing required field: {field}")
    if not isinstance(v, str) or v == "":
        raise errors.invalid_request(f"Field {field} must be a non-empty string")
    return v


def opt_string(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise errors.invalid_request(f"Field {field} must be a string")
    return v


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(body, field):
    v = body.get(field)
    if v is None:
        raise errors.invalid_request(f"Missing required field: {field}")
    if not is_int(v):
        raise errors.invalid_request(f"Field {field} must be an integer")
    return v


def opt_int(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not is_int(v):
        raise errors.invalid_request(f"Field {field} must be an integer")
    return v


def opt_bool(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise errors.invalid_request(f"Field {field} must be a boolean")
    return v


def req_enum(body, field, values):
    v = body.get(field)
    if v is None:
        raise errors.invalid_request(f"Missing required field: {field}")
    if not isinstance(v, str) or v not in values:
        raise errors.invalid_request(
            f"Field {field} must be one of {sorted(values)}")
    return v


def req_datetime(body, field):
    v = body.get(field)
    if v is None:
        raise errors.invalid_request(f"Missing required field: {field}")
    dt = util.try_parse_iso(v)
    if dt is None:
        raise errors.invalid_request(f"Field {field} must be an ISO 8601 datetime")
    return dt


def opt_datetime(body, field):
    v = body.get(field)
    if v is None:
        return None
    dt = util.try_parse_iso(v)
    if dt is None:
        raise errors.invalid_request(f"Field {field} must be an ISO 8601 datetime")
    return dt


def opt_number(body, field):
    v = body.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.invalid_request(f"Field {field} must be a number")
    return v


# ---------------------------------------------------------------------------
# Existence lookups (ERR_NOT_FOUND, validated left-to-right by callers)
# ---------------------------------------------------------------------------

def get_site(sid):
    s = db.sites.get(sid)
    if s is None:
        raise errors.not_found(f"Site {sid} does not exist")
    return s


def get_facility(fid):
    f = db.facilities.get(fid)
    if f is None:
        raise errors.not_found(f"Facility {fid} does not exist")
    return f


def get_renter(oid):
    r = db.renters.get(oid)
    if r is None:
        raise errors.not_found(f"RenterOrganization {oid} does not exist")
    return r


def get_policy(pid):
    p = db.policies.get(pid)
    if p is None:
        raise errors.not_found(f"RateClassPolicy {pid} does not exist")
    return p


def get_event(eid):
    e = db.calendar_events.get(eid)
    if e is None:
        raise errors.not_found(f"SchoolCalendarEvent {eid} does not exist")
    return e


def get_request(rid):
    r = db.requests.get(rid)
    if r is None:
        raise errors.not_found(f"RentalRequest {rid} does not exist")
    return r


def get_cert(cid):
    c = db.certificates.get(cid)
    if c is None:
        raise errors.not_found(f"InsuranceCertificate {cid} does not exist")
    return c


def get_permit(pid):
    p = db.permits.get(pid)
    if p is None:
        raise errors.not_found(f"Permit {pid} does not exist")
    return p


def get_wo(wid):
    w = db.work_orders.get(wid)
    if w is None:
        raise errors.not_found(f"CustodialWorkOrder {wid} does not exist")
    return w


def get_invoice(iid):
    i = db.invoices.get(iid)
    if i is None:
        raise errors.not_found(f"Invoice {iid} does not exist")
    return i


def get_assessment(aid):
    a = db.damage_assessments.get(aid)
    if a is None:
        raise errors.not_found(f"DamageAssessment {aid} does not exist")
    return a


def get_payment(pid):
    p = db.payments.get(pid)
    if p is None:
        raise errors.not_found(f"PaymentTransaction {pid} does not exist")
    return p


def get_series(sid):
    s = db.seasonal_permits.get(sid)
    if s is None:
        raise errors.not_found(f"SeasonalPermit {sid} does not exist")
    return s


# ---------------------------------------------------------------------------
# Cross-resource utilities
# ---------------------------------------------------------------------------

def site_of_facility(fac):
    return db.sites.get(fac["site_id"])


def policy_for(rate_class, facility_tier, starts_at):
    """The ACTIVE policy for (rate_class, tier) covering starts_at, or None."""
    for p in db.policies.values():
        if p["policy_status"] != "ACTIVE":
            continue
        if p["rate_class"] != rate_class or p["facility_tier"] != facility_tier:
            continue
        ef = util.parse_iso(p["effective_from"])
        et = util.parse_iso(p["effective_to"]) if p.get("effective_to") else None
        if ef <= starts_at and (et is None or starts_at < et):
            return p
    return None


PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def request_priority_key(req):
    """Lexicographic: priority class ASC, submitted_at ASC, created_at ASC.
    The resource id is never an ordering key; same-instant ties (the logical
    clock can freeze created_at to the millisecond) fall to arrival order via
    the internal creation sequence."""
    sub = req.get("submitted_at") or "9999"
    return (
        PRIORITY_ORDER.get(req.get("request_priority_class") or "P3", 3),
        sub,
        req["created_at"],
        req.get("_seq", 0),
    )


def derive_priority_class(renter, district_sponsored):
    rc = renter["rate_class"]
    if rc == "INTERNAL":
        return "P0"
    if rc == "NONPROFIT":
        return "P1" if district_sponsored else "P2"
    return "P3"


def insurance_sufficient(renter, headcount, ends_at):
    """True iff renter is INTERNAL (exempt) or holds a VALID certificate whose
    window covers the event end with limits meeting the headcount tier."""
    if renter["rate_class"] == "INTERNAL":
        return True
    if headcount < 100:
        per_occ, agg = 100000000, 200000000
    elif headcount < 500:
        per_occ, agg = 200000000, 400000000
    else:
        per_occ, agg = 500000000, 1000000000
    for c in db.certificates.values():
        if c["renter_org_id"] != renter["id"] or c["cert_status"] != "VALID":
            continue
        ef = util.parse_iso(c["effective_from"])
        et = util.parse_iso(c["effective_to"])
        if ef <= ends_at and et >= ends_at and \
                c["per_occurrence_limit_cents"] >= per_occ and \
                c["aggregate_limit_cents"] >= agg:
            return True
    return False


def calendar_conflict(facility, start, end):
    """A SCHEDULED calendar event overlapping [start, end) on this facility or
    as a site-wide blackout."""
    for e in db.calendar_events.values():
        if e["event_status"] != "SCHEDULED" or e["site_id"] != facility["site_id"]:
            continue
        if e.get("facility_id") not in (None, facility["id"]):
            continue
        if util.overlaps(start, end,
                         util.parse_iso(e["starts_at"]),
                         util.parse_iso(e["ends_at"])):
            return True
    return False


def permit_blocked_conflict(facility_id, blocked_start, blocked_end, exclude_permit_id=None):
    """An ISSUED/ACTIVE permit on the same facility whose blocked interval
    overlaps [blocked_start, blocked_end)."""
    for p in db.permits.values():
        if p["facility_id"] != facility_id:
            continue
        if exclude_permit_id and p["id"] == exclude_permit_id:
            continue
        if p["lifecycle_status"] not in ("ISSUED", "ACTIVE"):
            continue
        if util.overlaps(blocked_start, blocked_end,
                         util.parse_iso(p["blocked_start"]),
                         util.parse_iso(p["blocked_end"])):
            return True
    return False


def any_blocking_permit(facility_id, start, end):
    """Any ISSUED/ACTIVE permit on this facility whose blocked interval
    overlaps [start, end) — used by the waitlist promotion sweep."""
    for p in db.permits.values():
        if p["facility_id"] != facility_id:
            continue
        if p["lifecycle_status"] not in ("ISSUED", "ACTIVE"):
            continue
        if util.overlaps(start, end,
                         util.parse_iso(p["blocked_start"]),
                         util.parse_iso(p["blocked_end"])):
            return True
    return False


def post_txn(permit_id, invoice_id, txn_kind, amount_cents, idempotency_key=None):
    rec = {
        "id": new_id(),
        "created_at": now_iso(),
        "permit_id": permit_id,
        "invoice_id": invoice_id,
        "txn_kind": txn_kind,
        "amount_cents": amount_cents,
        "posted_at": now_iso(),
        "idempotency_key": idempotency_key,
    }
    db.payments[rec["id"]] = rec
    return rec


def fee_payments_total(permit_id):
    total = 0
    for p in db.payments.values():
        if p["permit_id"] == permit_id and p["txn_kind"] == "FEE_PAYMENT":
            total += p["amount_cents"]
    return total


def open_assessment_exists(permit_id):
    for a in db.damage_assessments.values():
        if a["permit_id"] == permit_id and a["assessment_status"] in (
                "OPEN", "ADJUDICATED", "APPEALED"):
            return True
    return False


def issue_invoice(permit, renter, kind, rental_fee, staffing, after_hours,
                  discount, total):
    """Create an invoice born DRAFT and immediately ISSUED; FINAL/DAMAGE
    issuance accrues total_cents onto the renter's outstanding balance."""
    rec = init_common()
    rec.update({
        "permit_id": permit["id"],
        "renter_org_id": renter["id"],
        "invoice_kind": kind,
        "rental_fee_cents": rental_fee,
        "staffing_charge_cents": staffing,
        "after_hours_charge_cents": after_hours,
        "discount_cents": discount,
        "total_cents": total,
        "amount_paid_cents": 0,
        "invoice_status": "ISSUED",
    })
    db.invoices[rec["id"]] = rec
    if kind in ("FINAL", "DAMAGE") and total != 0:
        # Stamp the arrears clock when the balance first goes above zero; the
        # thirty-day suspension rule measures continuity from this instant.
        if renter["outstanding_balance_cents"] == 0:
            renter["_balance_since"] = now_iso()
        renter["outstanding_balance_cents"] += total
        touch(renter)
        recompute_standing(renter)
    return rec


def void_invoice(inv):
    if inv["invoice_status"] not in ("DRAFT", "ISSUED"):
        return
    was_issued = inv["invoice_status"] == "ISSUED"
    inv["invoice_status"] = "VOID"
    touch(inv)
    if was_issued and inv["invoice_kind"] in ("FINAL", "DAMAGE") and inv["total_cents"] != 0:
        renter = db.renters.get(inv["renter_org_id"])
        if renter is not None:
            renter["outstanding_balance_cents"] = max(
                0, renter["outstanding_balance_cents"] - inv["total_cents"])
            touch(renter)
            recompute_standing(renter)


def recompute_standing(renter):
    """SUSPENDED -> GOOD_STANDING when balance returns to 0 and forfeits < 3.
    GOOD_STANDING -> SUSPENDED when forfeiture_count reaches 3 (arrears-based
    suspension is handled by the clock sweep, which tracks duration)."""
    if renter["org_standing"] == "BARRED":
        return
    if renter["org_standing"] == "SUSPENDED":
        if renter["outstanding_balance_cents"] == 0 and renter["forfeiture_count"] < 3:
            renter["org_standing"] = "GOOD_STANDING"
            renter.pop("_balance_since", None)
            touch(renter)
    elif renter["org_standing"] == "GOOD_STANDING":
        if renter["forfeiture_count"] >= 3:
            renter["org_standing"] = "SUSPENDED"
            touch(renter)


def run_waitlist_sweep(facility_id):
    """Promote the single best eligible WAITLISTED request on this facility
    whose window is no longer blocked by any ISSUED/ACTIVE permit."""
    fac = db.facilities.get(facility_id)
    if fac is None or fac["facility_status"] != "AVAILABLE":
        return
    candidates = []
    for r in db.requests.values():
        if r["request_status"] != "WAITLISTED":
            continue
        if r["facility_id"] != facility_id:
            continue
        renter = db.renters.get(r["renter_org_id"])
        if renter is None or renter["org_standing"] != "GOOD_STANDING":
            continue
        if r["headcount_estimate"] > fac["capacity"]:
            continue
        start = util.parse_iso(r["starts_at"])
        end = util.parse_iso(r["ends_at"])
        if any_blocking_permit(facility_id, start, end):
            continue
        candidates.append(r)
    if not candidates:
        return
    best = min(candidates, key=request_priority_key)
    best["request_status"] = "UNDER_REVIEW"
    touch(best)


def cancel_permit_record(permit, cancellation_class, refund_destination=None,
                         zero_refund_status=None):
    """Shared cancel/supersede/lapse machinery: refund waterfall, work-order
    cancel, provisional void, waitlist sweep. cancellation_class is
    'ADMINISTRATIVE' or 'STANDARD'. zero_refund_status pins the financial
    landing state when the refundable amount is zero (STANDARD cancellation
    tiers land on SETTLED per §3.7; supersession's pinned side effect is
    REFUND_PENDING regardless). Returns the permit."""
    import services  # late import to avoid a module cycle

    renter = db.renters.get(permit["renter_org_id"])
    fac = db.facilities.get(permit["facility_id"])
    tz = util.tz_for_site(db.sites.get(fac["site_id"]) if fac else None)
    now = util.clock_now()

    # Refund waterfall over gross paid.
    gross_paid = permit["deposit_held_cents"] + fee_payments_total(permit["id"])
    if cancellation_class == "ADMINISTRATIVE":
        fee_cents, refund_pct = 0, 1.0
    else:
        days_before = util.whole_days_between(
            now, util.parse_iso(permit["occupancy_start"]), tz)
        if days_before >= 14:
            fee_cents, refund_pct = 0, 1.0
        elif days_before >= 7:
            fee_cents, refund_pct = 2500, 0.5
        else:
            fee_cents, refund_pct = 0, 0.0
    refundable_before_fee = util.round_half_up_cents(gross_paid * refund_pct)
    refund_total = max(0, refundable_before_fee - fee_cents)
    deposit_refund = min(refund_total, permit["deposit_held_cents"])
    fee_refund = refund_total - deposit_refund
    deposit_forfeit = permit["deposit_held_cents"] - deposit_refund

    # Work order cancellation.
    for w in db.work_orders.values():
        if w["permit_id"] == permit["id"] and w["wo_status"] in (
                "SCHEDULED", "IN_PROGRESS"):
            w["wo_status"] = "CANCELLED"
            touch(w)

    # Provisional invoice void.
    for inv in db.invoices.values():
        if inv["permit_id"] == permit["id"] and inv["invoice_kind"] == "PROVISIONAL":
            void_invoice(inv)

    # REFUND invoice for the refundable amount.
    refund_invoice = None
    if refund_total > 0:
        refund_invoice = issue_invoice(
            permit, renter, "REFUND", 0, 0, 0, 0, refund_total)

    # Refund/forfeit transactions.
    if deposit_refund > 0:
        post_txn(permit["id"], refund_invoice["id"] if refund_invoice else None,
                 "DEPOSIT_REFUND", deposit_refund)
    if fee_refund > 0:
        post_txn(permit["id"], refund_invoice["id"] if refund_invoice else None,
                 "FEE_REFUND", fee_refund)
    if deposit_forfeit > 0:
        post_txn(permit["id"], None, "DEPOSIT_FORFEIT", deposit_forfeit)
    if deposit_refund + fee_refund > 0:
        permit["deposit_held_cents"] = deposit_forfeit

    # Financial dimension.
    if refund_total > 0:
        permit["financial_status"] = "REFUND_PENDING"
        permit["financial_status"] = "REFUNDED"
        if refund_invoice is not None:
            refund_invoice["invoice_status"] = "REFUNDED"
            touch(refund_invoice)
        if refund_destination == "CREDIT" and renter is not None:
            renter["credit_balance_cents"] += refund_total
            touch(renter)
    else:
        permit["financial_status"] = zero_refund_status or "SETTLED"
    if renter is not None:
        recompute_standing(renter)
    touch(permit)
    run_waitlist_sweep(permit["facility_id"])
    return permit
