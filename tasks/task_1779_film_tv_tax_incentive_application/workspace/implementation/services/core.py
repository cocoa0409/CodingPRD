"""Business logic: record lifecycle, credit pipeline, recompute cascades.

Calculation fidelity (PRD 2.6 / scaffold calculations):
- resident-labor uplift is rounded half up PER ENTRY before summation;
- the ATL cap product, the transfer price floor product, and the clawback
  interest cap are floored to whole cents;
- allocation shares are round-half-up at 1/100th of a percent
  (x * 10000 / S, round half up, / 100).
"""
from datetime import timedelta
from decimal import Decimal

from db import db, next_seq
from util import CLOCK, dec, floor_cents, fmt_dt, new_id, now_ts, parse_dt, round_half_up_cents


# ---------------------------------------------------------------------------
# Record lifecycle (PRD 2.4): id, created_at, updated_at (3-fractional-digit
# UTC), version starting at 1 and incrementing on every mutation, including
# system-cascade mutations.
# ---------------------------------------------------------------------------

def new_record(collection, fields):
    ts = now_ts()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    rec.update(fields)
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    rec["updated_at"] = now_ts()
    rec["version"] = int(rec.get("version", 1)) + 1


# ---------------------------------------------------------------------------
# Credit pipeline (calculations: atl_btl_cap_application + credit_amount)
# ---------------------------------------------------------------------------

def apply_atl_cap(atl_cents: int, btl_cents: int, program) -> int:
    """Pinned order: cap base is the PRE-cap total; cap product floored;
    BTL never capped."""
    t_pre = int(atl_cents) + int(btl_cents)
    atl_cap = floor_cents(dec(program["atl_cap_pct"]) * t_pre)
    return min(int(atl_cents), atl_cap) + int(btl_cents)


def credit_pipeline(atl_cents: int, btl_cents: int, program):
    """Returns (capped_total, applied_rate, credit_cents, meets_minimum).

    Tier boundary inclusive on the POST-cap total; credit rounded half up;
    below the program minimum the credit is 0 and meets_minimum is false.
    """
    capped = apply_atl_cap(atl_cents, btl_cents, program)
    meets_minimum = capped >= int(program["minimum_qualified_spend_cents"])
    if capped >= int(program["elevated_tier_threshold_cents"]):
        rate = program["base_rate_elevated"]
    else:
        rate = program["base_rate_standard"]
    credit = round_half_up_cents(dec(rate) * capped) if meets_minimum else 0
    return capped, rate, credit, meets_minimum


def effective_amount_for_entry(entry, vendor, program) -> int:
    """Per-entry effective amount at review time: resident BTL labor with a
    VERIFIED vendor earns the uplift, rounded half up per entry."""
    amount = int(entry["amount_cents"])
    if (
        entry["category"] == "BTL"
        and entry.get("is_resident_labor") is True
        and vendor is not None
        and vendor["residency_status"] == "VERIFIED"
    ):
        return amount + round_half_up_cents(dec(program["resident_uplift_pct"]) * amount)
    return amount


def transfer_price_floor_cents(program, amount_cents: int) -> int:
    return floor_cents(dec(program["transfer_price_floor_pct"]) * int(amount_cents))


# ---------------------------------------------------------------------------
# Application totals recompute + multi-jurisdiction allocation shares
# ---------------------------------------------------------------------------

def recompute_shares(production_id):
    """multi_jurisdiction_allocation: shares over sibling applications of the
    same production in APPROVED or CREDIT_ISSUED; 0 when the sibling sum is 0.
    Exactly two decimal places via round-half-up at 1/100th of a percent."""
    siblings = [
        a for a in db["applications"].values()
        if a["production_id"] == production_id
        and a["status"] in ("APPROVED", "CREDIT_ISSUED")
    ]
    total = sum(int(a["capped_total_qualified_cents"]) for a in siblings)
    for a in siblings:
        if total == 0:
            share = 0
        else:
            hundredths = round_half_up_cents(
                Decimal(int(a["capped_total_qualified_cents"]) * 10000) / Decimal(total)
            )
            share = hundredths / 100.0
        if a["allocation_share_pct"] != share:
            a["allocation_share_pct"] = share
            touch(a)


def refresh_certificate_exposure(app):
    """Exposure = max(0, issued - recomputed); a 0 -> >0 transition auto-opens
    a SPEND_SHORTFALL case, or updates the shortfall of an existing unresolved
    one (OPENED / NOTICE_SENT / APPEALED)."""
    cert = None
    for c in db["certificates"].values():
        if c["application_id"] == app["id"]:
            cert = c
            break
    if cert is None:
        return
    old = int(cert["overissued_exposure_cents"])
    new = max(0, int(cert["issued_amount_cents"]) - int(app["recomputed_credit_cents"]))
    if new != old:
        cert["overissued_exposure_cents"] = new
        touch(cert)
    if old == 0 and new > 0:
        existing = None
        for case in db["clawback_cases"].values():
            if (
                case["certificate_id"] == cert["id"]
                and case["trigger_reason"] == "SPEND_SHORTFALL"
                and case["status"] in ("OPENED", "NOTICE_SENT", "APPEALED")
            ):
                existing = case
                break
        if existing is not None:
            if int(existing["shortfall_amount_cents"]) != new:
                existing["shortfall_amount_cents"] = new
                touch(existing)
        else:
            new_record("clawback_cases", {
                "application_id": app["id"],
                "certificate_id": cert["id"],
                "trigger_reason": "SPEND_SHORTFALL",
                "penalty_mode": "SIMPLE",
                "shortfall_amount_cents": new,
                "status": "OPENED",
                "notice_sent_at": None,
                "appeal_deadline_at": None,
                "appealed_at": None,
                "resolved_at": None,
                "interest_cents": None,
                "assessed_total_cents": None,
                "recovered_from_certificate_cents": 0,
                "cash_assessment_cents": None,
                "settled_amount_cents": None,
            })


def recompute_application(app):
    """qualified_spend_totals + atl_btl_cap_application + credit_amount
    (PROVISIONAL/recomputed variants) + allocation shares + certificate
    exposure. Only QUALIFIED, non-superseded entries contribute."""
    program = db["jurisdiction_programs"].get(app["jurisdiction_program_id"])
    atl = 0
    btl = 0
    for e in db["spend_entries"].values():
        if e["application_id"] == app["id"] and e["status"] == "QUALIFIED":
            if e["category"] == "ATL":
                atl += int(e["effective_amount_cents"])
            else:
                btl += int(e["effective_amount_cents"])
    capped, _, credit, _ = credit_pipeline(atl, btl, program)
    changed = (
        app["atl_qualified_cents"] != atl
        or app["btl_qualified_cents"] != btl
        or app["capped_total_qualified_cents"] != capped
        or app["provisional_credit_cents"] != credit
        or app["recomputed_credit_cents"] != credit
    )
    app["atl_qualified_cents"] = atl
    app["btl_qualified_cents"] = btl
    app["capped_total_qualified_cents"] = capped
    app["provisional_credit_cents"] = credit
    app["recomputed_credit_cents"] = credit
    if changed:
        touch(app)
    recompute_shares(app["production_id"])
    refresh_certificate_exposure(app)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def vendor_revocation_cascade(vendor):
    """VERIFIED -> REJECTED: every QUALIFIED entry naming this vendor (across
    all applications of the production) is disqualified with
    VENDOR_RESIDENCY_REVOKED; each affected application recomputes; exposure
    transitions auto-open/update SPEND_SHORTFALL cases."""
    affected_app_ids = []
    for e in db["spend_entries"].values():
        if e["vendor_id"] == vendor["id"] and e["status"] == "QUALIFIED":
            e["status"] = "DISQUALIFIED"
            e["disqualify_reason"] = "VENDOR_RESIDENCY_REVOKED"
            e["effective_amount_cents"] = 0
            touch(e)
            if e["application_id"] not in affected_app_ids:
                affected_app_ids.append(e["application_id"])
    for app_id in affected_app_ids:
        app = db["applications"].get(app_id)
        if app is not None:
            recompute_application(app)


def issue_certificate(app, program):
    """APPROVED -> CREDIT_ISSUED: create the certificate 1:1, debit the
    program cap ledger, pin recomputed_credit_cents to final_credit_cents."""
    now = CLOCK.now()
    cert = new_record("certificates", {
        "application_id": app["id"],
        "certificate_number": "CERT-" + new_id().replace("-", "")[:12].upper(),
        "issued_amount_cents": int(app["final_credit_cents"]),
        "remaining_amount_cents": int(app["final_credit_cents"]),
        "redeemed_total_cents": 0,
        "transferred_total_cents": 0,
        "overissued_exposure_cents": 0,
        "issued_at": CLOCK.now_iso(),
        "expires_at": fmt_dt(now + timedelta(days=int(program["credit_validity_days"]))),
        "status": "ISSUED",
    })

    program["remaining_cap_cents"] = int(program["remaining_cap_cents"]) - int(app["final_credit_cents"])
    program["allocated_credit_cents"] = int(program["allocated_credit_cents"]) + int(app["final_credit_cents"])
    touch(program)

    app["status"] = "CREDIT_ISSUED"
    app["recomputed_credit_cents"] = int(app["final_credit_cents"])
    touch(app)
    recompute_shares(app["production_id"])
    return cert


def settle_transfer(transfer, cert):
    """ACCEPTED -> SETTLED: debit the certificate by the FACE amount, advance
    the certificate status, then sweep oversized sibling proposals."""
    amount = int(transfer["amount_cents"])
    transfer["status"] = "SETTLED"
    transfer["settled_at"] = CLOCK.now_iso()
    touch(transfer)

    cert["remaining_amount_cents"] = int(cert["remaining_amount_cents"]) - amount
    cert["transferred_total_cents"] = int(cert["transferred_total_cents"]) + amount
    if int(cert["remaining_amount_cents"]) == 0:
        cert["status"] = "FULLY_TRANSFERRED"
    else:
        cert["status"] = "PARTIALLY_TRANSFERRED"
    touch(cert)

    for other in db["transfers"].values():
        if (
            other["id"] != transfer["id"]
            and other["certificate_id"] == cert["id"]
            and other["status"] in ("PROPOSED", "COUNTERED")
            and int(other["amount_cents"]) > int(cert["remaining_amount_cents"])
        ):
            other["status"] = "CANCELLED"
            other["cancellation_reason"] = "INSUFFICIENT_REMAINING"
            touch(other)


def sustain_clawback(case, cert, app, program):
    """Resolve SUSTAINED: compute the assessment per penalty_mode, then run
    the recovery cascade (certificate -> CLAWED_BACK, cap restore, transfer
    cancellation, application -> REVOKED)."""
    base = int(case["shortfall_amount_cents"])
    notice = case["notice_sent_at"]
    resolved_iso = CLOCK.now_iso()
    days = (parse_dt(resolved_iso) - parse_dt(notice)).days
    if days < 0:
        days = 0
    interest_raw = round_half_up_cents(dec(program["daily_interest_rate"]) * base * days)
    interest = min(interest_raw, floor_cents(dec("0.5") * base))
    if case["penalty_mode"] == "AGGRAVATED":
        assessed = round_half_up_cents(dec("1.25") * base) + interest
    else:
        assessed = base + interest

    recovered = int(cert["remaining_amount_cents"])
    if cert["status"] in ("ISSUED", "PARTIALLY_TRANSFERRED"):
        cert["status"] = "CLAWED_BACK"
    cert["remaining_amount_cents"] = 0
    touch(cert)

    program["remaining_cap_cents"] = int(program["remaining_cap_cents"]) + recovered
    program["allocated_credit_cents"] = int(program["allocated_credit_cents"]) - recovered
    touch(program)

    for other in db["transfers"].values():
        if other["certificate_id"] == cert["id"] and other["status"] in ("PROPOSED", "COUNTERED", "ACCEPTED"):
            other["status"] = "CANCELLED"
            other["cancellation_reason"] = "CERTIFICATE_CLAWED_BACK"
            touch(other)

    if app["status"] == "CREDIT_ISSUED":
        app["status"] = "REVOKED"
        touch(app)
        recompute_shares(app["production_id"])

    case["interest_cents"] = interest
    case["assessed_total_cents"] = assessed
    case["recovered_from_certificate_cents"] = recovered
    case["cash_assessment_cents"] = max(0, assessed - recovered)
    case["resolved_at"] = resolved_iso
    case["status"] = "SUSTAINED"
    touch(case)
