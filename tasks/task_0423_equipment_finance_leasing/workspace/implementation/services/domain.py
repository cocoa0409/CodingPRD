"""Domain helpers: resource lookup with path validation, cascades, the logical
clock, lapse evaluation, and computed-field projection on serialization.

All callers hold db.LOCK.
"""
import db
import errors
from services import calculations as calc
from services.common import (
    serialize, parse_iso8601, to_iso, add_months, add_days, months_between,
)

# Lifecycle states that count a lease into committed credit / portfolio sets.
COMMITTED_LIFECYCLE = {"ORIGINATION", "BOOKED", "ACTIVE", "END_OF_TERM"}
PORTFOLIO_LIFECYCLE = {"BOOKED", "ACTIVE", "END_OF_TERM"}


# --- lookups with left-to-right path validation (PRD §2.6) --------------------

def get_lessor_or_404(lessor_id):
    rec = db.lessors.get(lessor_id)
    if rec is None:
        raise errors.not_found("Lessor not found")
    return rec


def _scoped(rec, lessor_id):
    """A resource resolves under a lessor only if it belongs to that lessor."""
    return rec is not None and rec.get("lessor_id") == lessor_id


def get_vendor(lessor_id, vendor_id):
    rec = db.vendors.get(vendor_id)
    if not _scoped(rec, lessor_id):
        raise errors.not_found("Vendor not found")
    return rec


def get_credit_application(lessor_id, app_id):
    rec = db.credit_applications.get(app_id)
    if not _scoped(rec, lessor_id):
        raise errors.not_found("Credit application not found")
    return rec


def get_lessee(lessor_id, lessee_id):
    rec = db.lessees.get(lessee_id)
    if not _scoped(rec, lessor_id):
        raise errors.not_found("Lessee not found")
    return rec


def get_lease(lessor_id, lease_id):
    rec = db.leases.get(lease_id)
    if not _scoped(rec, lessor_id):
        raise errors.not_found("Lease not found")
    return rec


def get_equipment(lessor_id, equip_id):
    rec = db.equipment.get(equip_id)
    if not _scoped(rec, lessor_id):
        raise errors.not_found("Equipment unit not found")
    return rec


def get_schedule_line(lessor_id, sl_id):
    rec = db.schedule_lines.get(sl_id)
    if not _scoped(rec, lessor_id):
        raise errors.not_found("Schedule line not found")
    return rec


def get_invoice(lessor_id, inv_id):
    rec = db.invoices.get(inv_id)
    if not _scoped(rec, lessor_id):
        raise errors.not_found("Invoice not found")
    return rec


def get_payment(lessor_id, pay_id):
    rec = db.payments.get(pay_id)
    if not _scoped(rec, lessor_id):
        raise errors.not_found("Payment not found")
    return rec


def get_ucc_filing(lessor_id, ucc_id):
    rec = db.ucc_filings.get(ucc_id)
    if not _scoped(rec, lessor_id):
        raise errors.not_found("UCC filing not found")
    return rec


def get_tax_assessment(lessor_id, tax_id):
    rec = db.tax_assessments.get(tax_id)
    if not _scoped(rec, lessor_id):
        raise errors.not_found("Tax assessment not found")
    return rec


def get_add_on(lessor_id, addon_id):
    rec = db.add_ons.get(addon_id)
    if not _scoped(rec, lessor_id):
        raise errors.not_found("Add-on not found")
    return rec


def get_eot_election(lessor_id, election_id):
    rec = db.eot_elections.get(election_id)
    if not _scoped(rec, lessor_id):
        raise errors.not_found("End-of-term election not found")
    return rec


# --- child collection helpers -------------------------------------------------

def units_for_lease(lease_id):
    return [u for u in db.equipment.values() if u["lease_id"] == lease_id]


def schedule_lines_for_lease(lease_id):
    return [s for s in db.schedule_lines.values() if s["lease_id"] == lease_id]


def invoices_for_lease(lease_id):
    return [i for i in db.invoices.values() if i["lease_id"] == lease_id]


def elections_for_lease(lease_id):
    return [e for e in db.eot_elections.values() if e["lease_id"] == lease_id]


def leases_for_lessee(lessee_id):
    return [l for l in db.leases.values() if l["lessee_id"] == lessee_id]


# --- clock / temporal ---------------------------------------------------------

def lessor_clock(lessor):
    return parse_iso8601(lessor["clock_utc"])


# --- cascades (PRD §2.5) ------------------------------------------------------

def recompute_lessee_credit(lessee):
    """committed = sum financed over leases in COMMITTED_LIFECYCLE; available = approved - committed."""
    committed = sum(
        l["financed_amount_cents"]
        for l in leases_for_lessee(lessee["id"])
        if l["lifecycle_status"] in COMMITTED_LIFECYCLE
    )
    available = lessee["approved_credit_cents"] - committed
    if lessee["committed_credit_cents"] != committed or lessee["available_credit_cents"] != available:
        lessee["committed_credit_cents"] = committed
        lessee["available_credit_cents"] = available
        db.touch(lessee)


def recompute_lessor_portfolio(lessor):
    """portfolio = sum original_cost over units whose lease lifecycle in PORTFOLIO_LIFECYCLE."""
    total = 0
    for u in db.equipment.values():
        if u["lessor_id"] != lessor["id"]:
            continue
        lease = db.leases.get(u["lease_id"])
        if lease is not None and lease["lifecycle_status"] in PORTFOLIO_LIFECYCLE:
            total += u["original_cost_cents"]
    if lessor["portfolio_value_cents"] != total:
        lessor["portfolio_value_cents"] = total
        db.touch(lessor)


# --- UCC lapse evaluation (PRD §3.7) ------------------------------------------
#
# Lapse is a *derived* projection of the logical clock: a FILED filing whose
# coverage_end <= clock has LAPSED. Because the logical clock is operator-set and
# may move in either direction, we never persist LAPSED as a hard state — we
# compute the effective status against the current clock on read and on overlap
# checks. PENDING/FILED/TERMINATED are the persisted (operator-driven) states;
# LAPSED is purely temporal and reverses if the clock moves back before
# coverage_end. (TERMINATED is permanent and never reverts.)

def effective_ucc_status(lessor, filing):
    """Return the status reflecting the current clock (LAPSED projection)."""
    status = filing["status"]
    if status != "FILED":
        return status
    if filing.get("coverage_end_clock_utc") is None:
        return status
    now = lessor_clock(lessor)
    coverage_end = parse_iso8601(filing["coverage_end_clock_utc"])
    if now >= coverage_end:
        return "LAPSED"
    return status


def evaluate_ucc_lapse(lessor, filing):
    """Backwards-compatible shim: callers used to mutate state here, but lapse is
    now a derived projection, so this is a no-op."""
    return


def evaluate_all_ucc_lapse_for_lessor(lessor):
    return


# --- serialization with computed projections ----------------------------------

def serialize_lessor(rec):
    return serialize(rec)


def serialize_lessee(rec):
    return serialize(rec)


def serialize_ucc(rec, lessor):
    """Project the temporal LAPSED status at read time (PRD §3.7)."""
    out = serialize(rec)
    out["status"] = effective_ucc_status(lessor, rec)
    return out


def serialize_lease(rec):
    return serialize(rec)


def serialize_equipment(rec, lessor):
    """Project the computed assessed_value_cents at read time (PRD §3.8)."""
    out = serialize(rec)
    out["assessed_value_cents"] = current_assessed_value(rec, lessor)
    return out


def current_assessed_value(unit, lessor):
    lease = db.leases.get(unit["lease_id"])
    booked = lease.get("booked_clock_utc") if lease else None
    if booked is None:
        return calc.assessed_value(unit["original_cost_cents"], 0)
    now = lessor_clock(lessor)
    mis = months_between(parse_iso8601(booked), now)
    return calc.assessed_value(unit["original_cost_cents"], mis)


# --- serial discipline (PRD §3.5) ---------------------------------------------

def check_serial_available(lessor, serial_number):
    """Enforce the two serial rules in priority order (validations §21 then §22):

    1. ERR_DUPLICATE_SERIAL — serial held by any non-DISPOSED unit of this lessor.
    2. ERR_SERIAL_REUSE_TOO_SOON — only when no live unit holds it: a serial last
       DISPOSED at clock D is quarantined while now <= D + 30d (closed buffer).
    """
    lessor_units = [u for u in db.equipment.values() if u["lessor_id"] == lessor["id"]]

    # Instantaneous uniqueness across non-DISPOSED units.
    for u in lessor_units:
        if u["serial_number"] == serial_number and u["status"] != "DISPOSED":
            raise errors.conflict(errors.ERR_DUPLICATE_SERIAL,
                                  "serial in use by a live unit")

    # Closed-buffer reuse window measured from the most recent DISPOSED unit.
    disposed_times = [
        parse_iso8601(u["disposed_clock_utc"])
        for u in lessor_units
        if u["serial_number"] == serial_number
        and u["status"] == "DISPOSED"
        and u.get("disposed_clock_utc") is not None
    ]
    if disposed_times:
        d = max(disposed_times)
        now = lessor_clock(lessor)
        if now <= add_days(d, calc.SERIAL_REUSE_BUFFER_DAYS):
            raise errors.conflict(errors.ERR_SERIAL_REUSE_TOO_SOON,
                                  "serial reuse within the buffer window")
