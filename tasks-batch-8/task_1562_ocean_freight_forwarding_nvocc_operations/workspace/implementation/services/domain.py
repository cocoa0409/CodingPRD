"""Domain logic for the Ocean Freight NVOCC API.

Calculations (PRD section 2.7 / scaffold section 1.3), cross-entity cascades
(PRD section 2.10), gate re-evaluations (DOCUMENTATION_CLEARED / LOADED
bubble-ups), lazy expiry, and computed-field refresh. All money math uses
Decimal with round-half-up; day counts are whole 24h periods (floor).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import db
from util import dec, pub, round_half_up_int, round_half_up_3dp

# ---------------------------------------------------------------------------
# Constants (scaffold section 1.3)
# ---------------------------------------------------------------------------

BAF_PCT = Decimal("0.10")
THC_FCL_PER_CONTAINER_CENTS = 25000
THC_LCL_PER_RT_CENTS = 1200
DOC_FEE_CENTS = 7500

ISF_LATE_PENALTY_CENTS = 500000
AMS_LATE_PENALTY_CENTS = 300000
MIN_BOND_AVAILABLE_CENTS = 75000

MIN_PREMIUM_CENTS = 2500
INSURED_MARKUP = Decimal("1.10")
PREMIUM_RATES = {
    "ALL_RISK": Decimal("0.006"),
    "WA": Decimal("0.004"),
    "FPA": Decimal("0.0025"),
}

ROLLOVER_FEE_CENTS = 150000
CANCELLATION_FEE_CENTS = 75000
MAX_ROLLOVERS = 2
MAX_AMENDMENTS = 3

CREDIT_TERMS_DAYS = {"PREPAID_ONLY": 0, "NET_7": 7, "NET_30": 30}

# Status sets used across rules
FORWARD_BOOKING_STATUSES = {"CONFIRMED", "DOCUMENTATION_CLEARED", "LOADED", "DEPARTED", "ARRIVED"}
POSTED_INVOICE_STATUSES = {"ISSUED", "PARTIALLY_PAID"}
BILLED_FREIGHT_STATUSES = {"DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID"}
LIVE_ASSIGNMENT_STATUSES = {"STUFFED", "GATED_IN", "LOADED"}
VOIDABLE_BL_STATUSES = {"DRAFT", "ISSUED", "AMENDMENT_PENDING", "SURRENDERED"}


# ---------------------------------------------------------------------------
# Lazy expiry (PRD section 2.5)
# ---------------------------------------------------------------------------

def lazy_expire_bond(bond: dict) -> None:
    if bond["status"] == "ACTIVE" and db.clock() >= db.parse_iso(bond["effective_to"]):
        bond["status"] = "EXPIRED"
        db.touch(bond)


def lazy_expire_all_bonds() -> None:
    for bond in db.surety_bonds.values():
        lazy_expire_bond(bond)


def lazy_expire_contract(contract: dict) -> None:
    if contract["status"] == "ACTIVE" and db.clock() > db.parse_iso(contract["service_end"]):
        contract["status"] = "EXPIRED"
        db.touch(contract)


def lazy_expire_all_contracts() -> None:
    for contract in db.carrier_contracts.values():
        lazy_expire_contract(contract)


def lazy_expire_all() -> None:
    lazy_expire_all_bonds()
    lazy_expire_all_contracts()


# ---------------------------------------------------------------------------
# Surety bond available coverage (computed; PRD section 3.4)
# ---------------------------------------------------------------------------

def recompute_bond_coverage(bond: dict) -> None:
    accrued = sum(
        f["penalty_amount_cents"]
        for f in db.compliance_filings.values()
        if f["penalty_status"] == "ACCRUED" and f.get("_penalty_bond_id") == bond["id"]
    )
    db.write_if_changed(bond, "available_coverage_cents", bond["coverage_amount_cents"] - accrued)


def select_accrual_bond():
    """Bond debited by a penalty accrual: ACTIVE, window covers the logical
    clock, earliest created_at among qualifiers; None when none qualify."""
    lazy_expire_all_bonds()
    now = db.clock()
    qualifying = [
        b
        for b in db.surety_bonds.values()
        if b["status"] == "ACTIVE"
        and db.parse_iso(b["effective_from"]) <= now < db.parse_iso(b["effective_to"])
    ]
    if not qualifying:
        return None
    return min(qualifying, key=lambda b: (b["created_at"], b.get("_seq", 0)))


def qualifying_bond_exists() -> bool:
    """B/L issue gate: an ACTIVE bond inside its window with available coverage
    >= MIN_BOND_AVAILABLE_CENTS (75000)."""
    lazy_expire_all_bonds()
    now = db.clock()
    for bond in db.surety_bonds.values():
        if (
            bond["status"] == "ACTIVE"
            and db.parse_iso(bond["effective_from"]) <= now < db.parse_iso(bond["effective_to"])
        ):
            recompute_bond_coverage(bond)
            if bond["available_coverage_cents"] >= MIN_BOND_AVAILABLE_CENTS:
                return True
    return False


# ---------------------------------------------------------------------------
# Shipper credit exposure (two variants; PRD section 3.1)
# ---------------------------------------------------------------------------

def shipper_of_invoice(invoice: dict):
    booking = db.bookings.get(invoice["booking_id"])
    return booking["shipper_id"] if booking else None


def compute_exposures(shipper: dict) -> tuple[int, int]:
    posted = sum(
        inv["balance_cents"]
        for inv in db.invoices.values()
        if shipper_of_invoice(inv) == shipper["id"] and inv["status"] in POSTED_INVOICE_STATUSES
    )
    forward_add = 0
    for b in db.bookings.values():
        if b["shipper_id"] != shipper["id"]:
            continue
        if b["status"] not in FORWARD_BOOKING_STATUSES:
            continue
        has_billed_freight = any(
            inv["booking_id"] == b["id"]
            and inv["invoice_type"] == "FREIGHT"
            and inv["status"] in BILLED_FREIGHT_STATUSES
            for inv in db.invoices.values()
        )
        if not has_billed_freight:
            forward_add += b["estimated_freight_cents"]
    return posted, posted + forward_add


def recompute_shipper_exposure(shipper: dict) -> None:
    posted, forward = compute_exposures(shipper)
    changed = False
    if shipper.get("credit_exposure_posted_cents") != posted:
        shipper["credit_exposure_posted_cents"] = posted
        changed = True
    if shipper.get("credit_exposure_forward_cents") != forward:
        shipper["credit_exposure_forward_cents"] = forward
        changed = True
    if changed:
        db.touch(shipper)


def recompute_all_shipper_exposures() -> None:
    for shipper in db.shippers.values():
        recompute_shipper_exposure(shipper)


def auto_suspend_if_over_limit(shipper: dict) -> None:
    """Invoice-issue trigger: posted exposure over the limit auto-suspends."""
    if (
        shipper["status"] == "ACTIVE"
        and shipper["credit_exposure_posted_cents"] > shipper["credit_limit_cents"]
    ):
        shipper["status"] = "SUSPENDED"
        db.touch(shipper)


# ---------------------------------------------------------------------------
# Ocean freight charge (scaffold section 1.3 ocean_freight_charge)
# ---------------------------------------------------------------------------

def compute_chargeable_rt(gross_weight_kg, volume_cbm) -> float:
    """Revenue tons: max(weight_kg / 1000, volume_cbm), 3dp round-half-up."""
    w = dec(gross_weight_kg) / Decimal(1000)
    v = dec(volume_cbm)
    return round_half_up_3dp(max(w, v))


def compute_freight(
    *,
    mode: str,
    container_count,
    chargeable_rt: float,
    rate_source: str,
    spot_rate_per_unit_cents,
    tariff: dict,
) -> dict:
    """Sell-side estimate. Returns the decomposition used for invoices and the
    insurance freight-base snapshot."""
    unit = (
        tariff["rate_per_unit_cents"]
        if rate_source == "CONTRACT"
        else spot_rate_per_unit_cents
    )
    if mode == "FCL":
        base = container_count * unit
        thc = container_count * THC_FCL_PER_CONTAINER_CENTS
        of_quantity = container_count
        of_unit_rate = unit
        thc_quantity = container_count
        thc_unit_rate = THC_FCL_PER_CONTAINER_CENTS
    else:
        raw = dec(chargeable_rt) * unit
        minimum = tariff.get("minimum_charge_cents") or 0
        base = round_half_up_int(max(raw, Decimal(minimum)))
        thc = round_half_up_int(dec(chargeable_rt) * THC_LCL_PER_RT_CENTS)
        if raw < Decimal(minimum):
            # Minimum-charge floor bound: the line carries the floored base.
            of_quantity = 1
            of_unit_rate = base
        else:
            of_quantity = chargeable_rt
            of_unit_rate = unit
        thc_quantity = chargeable_rt
        thc_unit_rate = THC_LCL_PER_RT_CENTS
    baf = round_half_up_int(dec(base) * BAF_PCT)
    doc = DOC_FEE_CENTS
    total = base + baf + thc + doc
    return {
        "base_cents": base,
        "baf_cents": baf,
        "thc_cents": thc,
        "doc_cents": doc,
        "total_cents": total,
        "of_quantity": of_quantity,
        "of_unit_rate_cents": of_unit_rate,
        "thc_quantity": thc_quantity,
        "thc_unit_rate_cents": thc_unit_rate,
    }


def recompute_booking_estimate(booking: dict) -> None:
    tariff = db.tariffs.get(booking["tariff_id"])
    rt = compute_chargeable_rt(booking["gross_weight_kg"], booking["volume_cbm"])
    fr = compute_freight(
        mode=booking["mode"],
        container_count=booking.get("container_count"),
        chargeable_rt=rt,
        rate_source=booking["rate_source"],
        spot_rate_per_unit_cents=booking.get("spot_rate_per_unit_cents"),
        tariff=tariff,
    )
    booking["chargeable_weight_rt"] = rt
    booking["estimated_freight_cents"] = fr["total_cents"]
    booking["_freight"] = fr


# ---------------------------------------------------------------------------
# Demurrage / detention (scaffold section 1.3 demurrage_detention_charge)
# ---------------------------------------------------------------------------

def full_days(t0_iso: str, t1_iso: str) -> int:
    """Whole 24-hour periods between two timestamps (floor)."""
    delta = db.parse_iso(t1_iso) - db.parse_iso(t0_iso)
    return int(delta.total_seconds() // 86400)


def tiered_demurrage(days: int, tiers: list) -> int:
    remaining = days
    charge = 0
    for tier in sorted(tiers, key=lambda t: t["from_day"]):
        if remaining <= 0:
            break
        to_day = tier.get("to_day")
        span = remaining if to_day is None else min(remaining, to_day - tier["from_day"] + 1)
        charge += span * tier["per_diem_cents"]
        remaining -= span
    return charge


def compute_demurrage(contract: dict, discharged_iso: str, gated_out_iso: str) -> tuple[int, int]:
    days = max(0, full_days(discharged_iso, gated_out_iso) - contract["demurrage_free_days"])
    return days, tiered_demurrage(days, contract["demurrage_tiers"])


def compute_detention(contract: dict, gated_out_iso: str, empty_iso: str) -> tuple[int, int]:
    days = max(0, full_days(gated_out_iso, empty_iso) - contract["detention_free_days"])
    return days, days * contract["detention_per_diem_cents"]


def contract_for_assignment(asg: dict):
    booking = db.bookings.get(asg["booking_id"])
    voyage = db.voyages.get(booking["voyage_id"]) if booking else None
    return db.carrier_contracts.get(voyage["carrier_contract_id"]) if voyage else None


# ---------------------------------------------------------------------------
# Consolidation utilization (scaffold section 1.3 consolidation_utilization)
# ---------------------------------------------------------------------------

def consolidation_members(con: dict) -> list:
    return [
        a
        for a in db.container_assignments.values()
        if a.get("consolidation_id") == con["id"] and a["status"] in LIVE_ASSIGNMENT_STATUSES
    ]


def recompute_consolidation_used(con: dict) -> None:
    members = consolidation_members(con)
    con["used_weight_kg"] = sum((a["stuffed_weight_kg"] for a in members), 0)
    con["used_volume_cbm"] = sum((a["stuffed_volume_cbm"] for a in members), 0)


def cancel_consolidation(con: dict) -> None:
    """OPEN/CLOSED/TENDERED -> CANCELLED; live members cancelled; usage zeroed."""
    for a in db.container_assignments.values():
        if a.get("consolidation_id") == con["id"] and a["status"] in ("STUFFED", "GATED_IN"):
            a["status"] = "CANCELLED"
            db.touch(a)
    con["used_weight_kg"] = 0
    con["used_volume_cbm"] = 0
    con["status"] = "CANCELLED"
    db.touch(con)


def cancel_assignment_cascade(asg: dict, allow_reopen: bool = True) -> None:
    """Assignment -> CANCELLED (from STUFFED/GATED_IN) with the LCL consolidation
    recompute and the CLOSED -> OPEN reopen rule (PRD section 3.8)."""
    if asg["status"] not in ("STUFFED", "GATED_IN"):
        return
    asg["status"] = "CANCELLED"
    db.touch(asg)
    con_id = asg.get("consolidation_id")
    if con_id:
        con = db.consolidations.get(con_id)
        if con is not None and con["status"] != "CANCELLED":
            recompute_consolidation_used(con)
            if allow_reopen and con["status"] == "CLOSED" and not consolidation_members(con):
                con["status"] = "OPEN"
            db.touch(con)


# ---------------------------------------------------------------------------
# Booking gate re-evaluation (bubble-ups; PRD sections 3.8 / 3.11)
# ---------------------------------------------------------------------------

def reevaluate_doc_gate(booking: dict) -> bool:
    """CONFIRMED -> DOCUMENTATION_CLEARED when ISF + AMS ACCEPTED and a B/L is
    ISSUED or SURRENDERED."""
    if booking["status"] != "CONFIRMED":
        return False
    filings = [f for f in db.compliance_filings.values() if f["booking_id"] == booking["id"]]
    isf_ok = any(f["filing_type"] == "ISF" and f["status"] == "ACCEPTED" for f in filings)
    ams_ok = any(f["filing_type"] == "AMS" and f["status"] == "ACCEPTED" for f in filings)
    bl_ok = any(
        bl["booking_id"] == booking["id"] and bl["status"] in ("ISSUED", "SURRENDERED")
        for bl in db.bills_of_lading.values()
    )
    if isf_ok and ams_ok and bl_ok:
        booking["status"] = "DOCUMENTATION_CLEARED"
        db.touch(booking)
        reevaluate_loaded_gate(booking)
        return True
    return False


def reevaluate_loaded_gate(booking: dict) -> bool:
    """DOCUMENTATION_CLEARED -> LOADED bubble-up.

    FCL: exactly container_count assignments in {GATED_IN, LOADED}.
    LCL: a live assignment's consolidation reached TENDERED/DEPARTED/ARRIVED.
    Member assignments in GATED_IN flip to LOADED alongside.
    """
    if booking["status"] != "DOCUMENTATION_CLEARED":
        return False
    asgs = [a for a in db.container_assignments.values() if a["booking_id"] == booking["id"]]
    ready = False
    if booking["mode"] == "FCL":
        target = booking.get("container_count") or 0
        count = sum(1 for a in asgs if a["status"] in ("GATED_IN", "LOADED"))
        ready = target > 0 and count == target
    else:
        for a in asgs:
            if a["status"] in LIVE_ASSIGNMENT_STATUSES and a.get("consolidation_id"):
                con = db.consolidations.get(a["consolidation_id"])
                if con is not None and con["status"] in ("TENDERED", "DEPARTED", "ARRIVED"):
                    ready = True
                    break
    if not ready:
        return False
    booking["status"] = "LOADED"
    db.touch(booking)
    for a in asgs:
        if a["status"] == "GATED_IN":
            a["status"] = "LOADED"
            db.touch(a)
    return True


# ---------------------------------------------------------------------------
# Booking cascades (roll / cancel / voyage depart / blank; PRD sections 3.5-3.7)
# ---------------------------------------------------------------------------

def void_bls_for_booking(booking: dict) -> None:
    for bl in db.bills_of_lading.values():
        if bl["booking_id"] == booking["id"] and bl["status"] in VOIDABLE_BL_STATUSES:
            bl["status"] = "VOIDED"
            db.touch(bl)


def void_draft_freight_invoices(booking: dict) -> None:
    for inv in db.invoices.values():
        if (
            inv["booking_id"] == booking["id"]
            and inv["invoice_type"] == "FREIGHT"
            and inv["status"] == "DRAFT"
        ):
            inv["status"] = "VOID"
            db.touch(inv)


def booking_dependent_cascade(booking: dict) -> None:
    """Shared cascade for roll / system-cancel: void live B/Ls, void DRAFT
    FREIGHT invoices, cancel STUFFED/GATED_IN assignments (with consolidation
    recompute and CLOSED -> OPEN reopen)."""
    void_bls_for_booking(booking)
    void_draft_freight_invoices(booking)
    for a in [a for a in db.container_assignments.values() if a["booking_id"] == booking["id"]]:
        cancel_assignment_cascade(a)


def cancel_policies_for_booking(booking: dict) -> None:
    """Booking-cancel cascade: open claims are cascade-DENIED first, then
    QUOTED/BOUND policies are CANCELLED (open-claims precondition bypassed on
    the system path; PRD section 3.13)."""
    for pol in db.insurance_policies.values():
        if pol["booking_id"] == booking["id"] and pol["status"] in ("QUOTED", "BOUND"):
            for cl in db.cargo_claims.values():
                if cl["policy_id"] == pol["id"] and cl["status"] in (
                    "FILED",
                    "UNDER_REVIEW",
                    "APPROVED",
                ):
                    cl["status"] = "DENIED"
                    cl["settlement_amount_cents"] = 0
                    db.touch(cl)
            pol["status"] = "CANCELLED"
            db.touch(pol)


def roll_booking(booking: dict, reason: str) -> None:
    """Transition into ROLLED with the rollover cap; excess cancels instead."""
    if booking["rollover_count"] + 1 > MAX_ROLLOVERS:
        booking["status"] = "CANCELLED"
        db.touch(booking)
        booking_dependent_cascade(booking)
        return
    booking["status"] = "ROLLED"
    booking["rolled_reason"] = reason
    booking["rollover_count"] += 1
    db.touch(booking)
    booking_dependent_cascade(booking)


def voyage_booking_cascade(voyage: dict, roll_reason: str, loaded_to: str | None) -> None:
    """Depart / blank cascade over the voyage's bookings."""
    for b in [b for b in db.bookings.values() if b["voyage_id"] == voyage["id"]]:
        if b["status"] in ("CONFIRMED", "DOCUMENTATION_CLEARED"):
            roll_booking(b, roll_reason)
        elif b["status"] == "LOADED":
            if loaded_to == "DEPARTED":
                b["status"] = "DEPARTED"
                db.touch(b)
            else:
                # Blank sailing: LOADED bookings roll too.
                roll_booking(b, roll_reason)
        elif b["status"] == "QUOTED":
            b["status"] = "CANCELLED"
            db.touch(b)


def voyage_depart_cascade(voyage: dict) -> None:
    voyage_booking_cascade(voyage, "MISSED_DEPARTURE", "DEPARTED")
    for con in [c for c in db.consolidations.values() if c["voyage_id"] == voyage["id"]]:
        if con["status"] in ("OPEN", "CLOSED"):
            cancel_consolidation(con)
        elif con["status"] == "TENDERED":
            # TENDERED consolidations ride the voyage (PRD section 3.9).
            con["status"] = "DEPARTED"
            db.touch(con)
    recompute_all_shipper_exposures()


def voyage_blank_cascade(voyage: dict) -> None:
    voyage_booking_cascade(voyage, "BLANK_SAILING", None)
    for con in [c for c in db.consolidations.values() if c["voyage_id"] == voyage["id"]]:
        if con["status"] in ("OPEN", "CLOSED", "TENDERED"):
            cancel_consolidation(con)
    recompute_all_shipper_exposures()


def voyage_arrive_cascade(voyage: dict) -> None:
    now_iso = db.now_domain_iso()
    for b in [b for b in db.bookings.values() if b["voyage_id"] == voyage["id"]]:
        if b["status"] == "DEPARTED":
            b["status"] = "ARRIVED"
            db.touch(b)
            for a in [
                a
                for a in db.container_assignments.values()
                if a["booking_id"] == b["id"] and a["status"] == "LOADED"
            ]:
                a["status"] = "DISCHARGED"
                a["discharged_at"] = now_iso
                db.touch(a)
    for con in [c for c in db.consolidations.values() if c["voyage_id"] == voyage["id"]]:
        if con["status"] == "DEPARTED":
            con["status"] = "ARRIVED"
            db.touch(con)


# ---------------------------------------------------------------------------
# Invoices (scaffold section 1.3 invoice_total)
# ---------------------------------------------------------------------------

def line(line_type: str, description: str, quantity, unit_rate_cents: int, amount_cents: int):
    return {
        "line_type": line_type,
        "description": description,
        "quantity": quantity,
        "unit_rate_cents": unit_rate_cents,
        "amount_cents": amount_cents,
    }


def invoice_recompute_totals(inv: dict) -> None:
    inv["total_cents"] = sum(l["amount_cents"] for l in inv["lines"])
    inv["balance_cents"] = inv["total_cents"] - inv["paid_cents"]


def build_freight_invoice_lines(booking: dict) -> list:
    fr = booking["_freight"]
    lines = [
        line(
            "OCEAN_FREIGHT",
            "Ocean freight",
            fr["of_quantity"],
            fr["of_unit_rate_cents"],
            fr["base_cents"],
        ),
        line("BAF", "Bunker adjustment factor", 1, fr["baf_cents"], fr["baf_cents"]),
        line(
            "THC",
            "Terminal handling charge",
            fr["thc_quantity"],
            fr["thc_unit_rate_cents"],
            fr["thc_cents"],
        ),
        line("DOC_FEE", "Documentation fee", 1, fr["doc_cents"], fr["doc_cents"]),
    ]
    for pol in db.insurance_policies.values():
        if pol["booking_id"] == booking["id"] and pol["status"] == "BOUND":
            lines.append(
                line(
                    "INSURANCE_PREMIUM",
                    "Cargo insurance premium",
                    1,
                    pol["premium_cents"],
                    pol["premium_cents"],
                )
            )
    if booking.get("pending_rollover_fee_cents", 0) > 0:
        fee = booking["pending_rollover_fee_cents"]
        lines.append(line("ROLLOVER_FEE", "Rollover fee", 1, fee, fee))
        booking["pending_rollover_fee_cents"] = 0
        db.touch(booking)
    return lines


def create_cancellation_invoice(booking: dict) -> dict:
    lines = [
        line(
            "CANCELLATION_FEE",
            "Cancellation fee",
            1,
            CANCELLATION_FEE_CENTS,
            CANCELLATION_FEE_CENTS,
        )
    ]
    inv = {
        "booking_id": booking["id"],
        "invoice_number": f"INV-{db.next_seq('invoice')}",
        "invoice_type": "CANCELLATION",
        "lines": lines,
        "total_cents": 0,
        "paid_cents": 0,
        "balance_cents": 0,
        "issued_at": None,
        "due_date": None,
        "status": "DRAFT",
    }
    db.stamp_new(inv)
    invoice_recompute_totals(inv)
    db.invoices[inv["id"]] = inv
    return inv


def create_dd_invoice(booking: dict, dem_days: int, dem_charge: int, det_days: int, det_charge: int, det_rate: int) -> dict:
    lines = []
    if dem_charge > 0:
        lines.append(line("DEMURRAGE", "Demurrage", 1, dem_charge, dem_charge))
    if det_charge > 0:
        lines.append(line("DETENTION", "Detention", det_days, det_rate, det_charge))
    inv = {
        "booking_id": booking["id"],
        "invoice_number": f"INV-{db.next_seq('invoice')}",
        "invoice_type": "DEMURRAGE_DETENTION",
        "lines": lines,
        "total_cents": 0,
        "paid_cents": 0,
        "balance_cents": 0,
        "issued_at": None,
        "due_date": None,
        "status": "DRAFT",
    }
    db.stamp_new(inv)
    invoice_recompute_totals(inv)
    db.invoices[inv["id"]] = inv
    return inv


def compute_due_date(issued_at_iso: str, credit_terms: str) -> str:
    days = CREDIT_TERMS_DAYS[credit_terms]
    return db.format_iso(db.parse_iso(issued_at_iso) + timedelta(days=days))


# ---------------------------------------------------------------------------
# Insurance and claims (scaffold section 1.3 insured_value_premium, claim_settlement)
# ---------------------------------------------------------------------------

def compute_insured_and_premium(coverage_type: str, cargo_value_cents: int, freight_base_cents: int) -> tuple[int, int]:
    insured = round_half_up_int(dec(cargo_value_cents + freight_base_cents) * INSURED_MARKUP)
    premium = max(
        MIN_PREMIUM_CENTS,
        round_half_up_int(dec(insured) * PREMIUM_RATES[coverage_type]),
    )
    return insured, premium


def compute_deductible(coverage_type: str, insured_value_cents: int) -> int:
    if coverage_type == "FPA":
        return max(100000, round_half_up_int(dec(insured_value_cents) * Decimal("0.02")))
    return max(50000, round_half_up_int(dec(insured_value_cents) * Decimal("0.01")))


def compute_settlement(claim: dict, policy: dict) -> int:
    """Waterfall: DELAY excluded everywhere; FPA covers total loss only; else
    max(0, min(claimed, insured) - deductible)."""
    if claim["claim_type"] == "DELAY":
        return 0
    if policy["coverage_type"] == "FPA" and claim["claim_type"] in ("DAMAGE", "SHORTAGE"):
        return 0
    return max(
        0,
        min(claim["claimed_amount_cents"], policy["insured_value_cents"]) - claim["deductible_cents"],
    )


# ---------------------------------------------------------------------------
# Serializers with computed-on-read refresh (PRD section 2.10)
# ---------------------------------------------------------------------------

def serialize_shipper(shipper: dict) -> dict:
    recompute_shipper_exposure(shipper)
    return pub(shipper)


def serialize_bond(bond: dict) -> dict:
    lazy_expire_bond(bond)
    recompute_bond_coverage(bond)
    return pub(bond)


def serialize_contract(contract: dict) -> dict:
    lazy_expire_contract(contract)
    return pub(contract)


def serialize_assignment(asg: dict) -> dict:
    """Provisional D&D figures refresh on read while the assignment is
    DISCHARGED or GATED_OUT; pure reads do not mutate the stored resource."""
    out = pub(asg)
    if asg["status"] == "DISCHARGED":
        contract = contract_for_assignment(asg)
        if contract is not None:
            _, ch = compute_demurrage(contract, asg["discharged_at"], db.now_domain_iso())
            out["provisional_demurrage_cents"] = ch
            out["provisional_detention_cents"] = 0
    elif asg["status"] == "GATED_OUT":
        contract = contract_for_assignment(asg)
        if contract is not None:
            out["provisional_demurrage_cents"] = asg["demurrage_charge_cents"]
            _, dch = compute_detention(contract, asg["gated_out_at"], db.now_domain_iso())
            out["provisional_detention_cents"] = dch
    return out
