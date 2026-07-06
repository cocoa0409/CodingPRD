"""Business-logic services: seat ledger, calculations, cascades."""
from decimal import Decimal, ROUND_HALF_UP
from db import db, new_id, now_iso
from common import base_fields, touch, next_seq
from errors import err


# ---- seat ledger reconciliation --------------------------------------------

def recount_seats(cohort):
    """Derive seat counters from registration states. Does NOT touch version."""
    regs = [r for r in db.registrations.values() if r["cohort_id"] == cohort["id"]]
    cohort["seats_reserved"] = sum(1 for r in regs if r["status"] == "ENROLLED")
    cohort["seats_confirmed"] = sum(1 for r in regs if r["status"] in ("CONFIRMED", "ATTENDED"))
    cohort["seats_waitlisted"] = sum(1 for r in regs if r["status"] == "WAITLISTED")


def promote_waitlist(cohort):
    """Promote earliest WAITLISTED reg if a seat is free and cohort still OPEN.
    Each promotion is a mutation of both the registration and the cohort."""
    if cohort["status"] != "OPEN":
        return
    if cohort["seats_reserved"] + cohort["seats_confirmed"] >= cohort["seat_capacity"]:
        return
    waitlisted = [r for r in db.registrations.values()
                  if r["cohort_id"] == cohort["id"] and r["status"] == "WAITLISTED"]
    if not waitlisted:
        return
    waitlisted.sort(key=lambda r: (r["created_at"], r["_seq"]))
    promo = waitlisted[0]
    promo["status"] = "ENROLLED"
    touch(promo)
    recount_seats(cohort)
    touch(cohort)


# ---- calculations -----------------------------------------------------------

def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def assessment_percent_and_outcome(raw_score, max_score, pass_threshold_pct):
    pct = round_half_up(Decimal(100) * Decimal(raw_score) / Decimal(max_score), 2)
    pct_f = float(pct)
    if pct_f == int(pct_f):
        pct_out = float(int(pct_f))
    else:
        pct_out = pct_f
    outcome = "PASS" if pct >= Decimal(pass_threshold_pct) else "FAIL"
    return pct_out, outcome


def cohort_program_version(cohort):
    return db.program_versions.get(cohort["program_version_id"])


def compute_invoice_totals(cohort, variant):
    """variant in {PROVISIONAL, FINAL}. Returns dict of cents fields."""
    pv = cohort_program_version(cohort)
    lead = db.facilitators.get(cohort["lead_facilitator_id"])
    if variant == "PROVISIONAL":
        target_status = ("CONFIRMED",)
    else:
        target_status = ("ATTENDED",)
    seats = sum(1 for r in db.registrations.values()
                if r["cohort_id"] == cohort["id"] and r["status"] in target_status)
    if pv["pricing_model"] == "PER_SEAT":
        tuition = pv["per_seat_cents"] * seats
    else:
        tuition = pv["flat_fee_cents"]
    materials = pv["materials_kit_cents"] * seats
    if cohort["delivery_mode"] in ("ONSITE", "HYBRID"):
        travel = lead["travel_base_cents"] if lead else 0
    else:
        travel = 0
    total = tuition + materials + travel
    return {
        "tuition_cents": tuition,
        "materials_cents": materials,
        "travel_cents": travel,
        "total_cents": total,
    }


def create_invoice(cohort, variant):
    totals = compute_invoice_totals(cohort, variant)
    inv = base_fields()
    inv.update({
        "cohort_id": cohort["id"],
        "contract_id": cohort.get("contract_id"),
        "tuition_cents": totals["tuition_cents"],
        "materials_cents": totals["materials_cents"],
        "travel_cents": totals["travel_cents"],
        "total_cents": totals["total_cents"],
        "variant": variant,
        "status": variant,  # PROVISIONAL or FINAL
    })
    db.invoices[inv["id"]] = inv
    return inv


def compute_nps(cohort):
    ratings = [e["nps_rating"] for e in db.evaluations.values()
               if e.get("cohort_id") == cohort["id"]]
    n = len(ratings)
    if n == 0:
        return None
    promoters = sum(1 for r in ratings if r >= 9)
    detractors = sum(1 for r in ratings if r <= 6)
    score = round_half_up(Decimal(100) * Decimal(promoters - detractors) / Decimal(n), 0)
    return int(score)


# ---- contract helpers ------------------------------------------------------

def contract_available(contract):
    """Available budget = remaining_cents minus active soft reservations."""
    reserved = sum(c.get("_reserved_cents", 0) for c in db.cohorts.values()
                   if c.get("contract_id") == contract["id"])
    return contract["remaining_cents"] - reserved


def recompute_contract(contract):
    contract["remaining_cents"] = contract["budget_cents"] - contract["committed_cents"]


# ---- cohort cancel cascade -------------------------------------------------

def cancel_cohort_cascade(cohort):
    # L1: every non-terminal registration -> CANCELLED
    regs = [r for r in db.registrations.values() if r["cohort_id"] == cohort["id"]]
    terminal_reg = {"ATTENDED", "NO_SHOW", "WITHDRAWN", "CANCELLED"}
    for r in regs:
        if r["status"] not in terminal_reg:
            r["status"] = "CANCELLED"
            touch(r)
            # L2: revoke ISSUED certificate(s) of this registration
            certs = [c for c in db.certificates.values()
                     if c["registration_id"] == r["id"] and c["status"] == "ISSUED"]
            for cert in certs:
                cert["status"] = "REVOKED"
                # L3: ceu award removed
                cert["ceu_awarded"] = 0
                touch(cert)
    # Invoices -> VOID
    for inv in db.invoices.values():
        if inv["cohort_id"] == cohort["id"] and inv["status"] in ("PROVISIONAL", "FINAL"):
            inv["status"] = "VOID"
            touch(inv)
    # release soft reservation against contract
    if cohort.get("_reserved_cents", 0):
        cohort["_reserved_cents"] = 0
    recount_seats(cohort)


# ---- close: contract draw + NPS --------------------------------------------

def close_cohort_settlement(cohort):
    # FINAL invoice first
    inv = create_invoice(cohort, "FINAL")
    contract = None
    if cohort.get("contract_id"):
        contract = db.contracts.get(cohort["contract_id"])
    if contract is not None:
        draw = inv["total_cents"]
        if draw > contract["remaining_cents"]:
            # reject: undo the invoice we just created
            del db.invoices[inv["id"]]
            raise err("ERR_CONTRACT_BUDGET_EXCEEDED",
                      "Final draw exceeds contract remaining budget")
        # release soft reservation, apply commit
        cohort["_reserved_cents"] = 0
        contract["committed_cents"] += draw
        recompute_contract(contract)
        if contract["remaining_cents"] == 0 and contract["status"] == "ACTIVE":
            contract["status"] = "EXHAUSTED"
        touch(contract)
    cohort["nps_score"] = compute_nps(cohort)
