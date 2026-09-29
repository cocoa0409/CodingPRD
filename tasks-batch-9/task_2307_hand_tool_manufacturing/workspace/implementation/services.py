"""Derived-quantity recomputation and the two automatic cascades (PRD §2.9, §2.10)."""

from datetime import timedelta

import calculations as calc
from store import sorted_rows, store, touch


# --------------------------------------------------------------------------- #
# row collections (always in canonical created_at ASC order)
# --------------------------------------------------------------------------- #
def lot_runs(lot_id):
    return sorted_rows([r for r in store.runs.values() if r["lot_id"] == lot_id])


def lot_campaigns(lot_id):
    return sorted_rows([c for c in store.campaigns.values() if c["lot_id"] == lot_id])


def sku_lots(sku_id):
    return sorted_rows([l for l in store.lots.values() if l["sku_id"] == sku_id])


def sku_reports(sku_id):
    return sorted_rows([r for r in store.reports.values() if r["sku_id"] == sku_id])


def sku_claims(sku_id):
    return sorted_rows([c for c in store.claims.values() if c["sku_id"] == sku_id])


def program_claims(program_id):
    return sorted_rows([c for c in store.claims.values() if c["program_id"] == program_id])


def claimant_claims(claimant_id):
    return sorted_rows([c for c in store.claims.values() if c["claimant_id"] == claimant_id])


def pack_members(pack_id):
    return sorted_rows([m for m in store.pack_members.values() if m["pack_id"] == pack_id])


def claim_lines(claim_id):
    return sorted_rows([l for l in store.claim_lines.values() if l["claim_id"] == claim_id])


def sku_pack_memberships(sku_id):
    return sorted_rows([m for m in store.pack_members.values() if m["sku_id"] == sku_id])


# --------------------------------------------------------------------------- #
# specimen ledger
# --------------------------------------------------------------------------- #
def recompute_specimens(lot):
    runs = lot_runs(lot["id"])
    committed = sum(r["specimen_count"] for r in runs if r["status"] == "SCHEDULED")
    consumed = sum(r["specimen_count"] for r in runs if r["status"] in ("PASSED", "FAILED"))
    lot["specimens_committed"] = committed
    lot["specimens_consumed"] = consumed
    lot["specimens_available"] = lot["specimen_pool_total"] - committed - consumed


def recompute_hardness(lot):
    qualifying = [r for r in lot_runs(lot["id"])
                  if r["test_type"] == "HARDNESS" and r["status"] == "PASSED"]
    sample, pooled = calc.lot_hardness_index(qualifying)
    lot["hardness_index_sample"] = sample
    lot["hardness_index_pooled"] = pooled


# --------------------------------------------------------------------------- #
# replacement unit ledger
# --------------------------------------------------------------------------- #
def recompute_units(sku):
    claims = sku_claims(sku["id"])
    reserved = sum(c["replacement_unit_count"] for c in claims if c["status"] == "APPROVED")
    shipped = sum(c["replacement_unit_count"] for c in claims if c["status"] == "FULFILLED")
    sku["units_reserved"] = reserved
    sku["units_shipped"] = shipped
    sku["units_on_hand"] = sku["units_received_total"] - reserved - shipped


# --------------------------------------------------------------------------- #
# reserve ledger
# --------------------------------------------------------------------------- #
def recompute_reserve(program):
    claims = program_claims(program["id"])
    charged = sum(c["reserve_charge_cents"] for c in claims
                  if c["status"] in ("APPROVED", "FULFILLED"))
    program["reserve_balance_cents"] = program["reserve_funded_cents"] - charged
    program["open_hold_count"] = sum(1 for c in claims if c["status"] == "FRAUD_HOLD")


# --------------------------------------------------------------------------- #
# claim roll-ups
# --------------------------------------------------------------------------- #
def recompute_claim_rollups(claim):
    lines = claim_lines(claim["id"])
    claim["reserve_charge_cents"] = sum(l["line_reserve_cents"] for l in lines)
    claim["replacement_unit_count"] = sum(l["quantity"] for l in lines)
    claim["line_count"] = len(lines)


# --------------------------------------------------------------------------- #
# pack pricing
# --------------------------------------------------------------------------- #
def recompute_pack_members(pack):
    """Step 1 of pack_pricing: subtotal and member count (no surcharge, no total)."""
    members = pack_members(pack["id"])
    pack["member_subtotal_cents"] = sum(m["line_extended_cents"] for m in members)
    pack["distinct_member_count"] = len(members)


def price_pack(pack):
    """Full three-step pinned pricing performed at approval."""
    members = pack_members(pack["id"])
    subtotal = 0
    for member in members:
        sku = store.skus[member["sku_id"]]
        member["line_extended_cents"] = calc.member_line_extended_cents(
            sku["list_price_cents"], member["quantity"], pack["pack_type"])
        subtotal += member["line_extended_cents"]
    pack["member_subtotal_cents"] = subtotal
    pack["distinct_member_count"] = len(members)
    pack["security_surcharge_cents"] = calc.security_surcharge_cents(pack["pack_type"], subtotal)
    pack["pack_total_cents"] = subtotal + pack["security_surcharge_cents"]


# --------------------------------------------------------------------------- #
# fraud scores
# --------------------------------------------------------------------------- #
def intake_fraud_score(claimant, new_serial_code):
    cutoff = store.now() - timedelta(days=calc.CLAIM_WINDOW_DAYS)
    window = [c for c in claimant_claims(claimant["id"])
              if c["status"] != "REVOKED" and c["created_at"] >= cutoff]
    claim_set = window + [{"serial_code": new_serial_code}]
    return calc.fraud_score(claim_set, claimant["claimant_type"], 0)


def adjudication_fraud_score(claimant):
    claim_set = [c for c in claimant_claims(claimant["id"]) if c["status"] != "REVOKED"]
    restricted = 0
    for claim in claim_set:
        sku = store.skus.get(claim["sku_id"])
        if sku is not None and sku["warranty_posture"] != "OPEN":
            restricted += 1
    return calc.fraud_score(claim_set, claimant["claimant_type"], restricted)


def refresh_adjudication(claimant):
    claimant["fraud_risk_score_adjudication"] = adjudication_fraud_score(claimant)
    touch(claimant)


def refresh_lifetime_count(claimant):
    claimant["lifetime_claim_count"] = len(claimant_claims(claimant["id"]))


# --------------------------------------------------------------------------- #
# cascade B — a mandatory test failure rejects the lot (PRD §3.4)
# --------------------------------------------------------------------------- #
def cascade_lot_rejection(lot):
    lot["cert_status"] = "REJECTED"
    lot["disposition"] = "QUARANTINED"

    for campaign in lot_campaigns(lot["id"]):
        if campaign["status"] == "SCHEDULED":
            campaign["status"] = "RELEASED"
            touch(campaign)

    for run in lot_runs(lot["id"]):
        if run["status"] == "SCHEDULED":
            run["status"] = "VOID"
            run["void_reason"] = "CASCADE_LOT_REJECTED"
            touch(run)

    recompute_specimens(lot)
    touch(lot)


# --------------------------------------------------------------------------- #
# cascade A — a confirmed counterfeit degrades the SKU's posture (PRD §3.9)
# --------------------------------------------------------------------------- #
def cascade_counterfeit_confirmed(report):
    sku = store.skus[report["sku_id"]]
    previous_posture = sku["warranty_posture"]

    confirmed = [r for r in sku_reports(sku["id"]) if r["status"] == "CONFIRMED"]
    sku["confirmed_counterfeit_count"] = len(confirmed)
    sku["brand_risk_score"] = min(100, sum(r["risk_points"] for r in confirmed))
    sku["warranty_posture"] = calc.derive_posture(sku["brand_risk_score"])
    touch(sku)

    if previous_posture == "OPEN" and sku["warranty_posture"] != "OPEN":
        affected_claimants = []
        for claim in sku_claims(sku["id"]):
            if claim["status"] != "SUBMITTED":
                continue
            claim["status"] = "FRAUD_HOLD"
            claim["hold_reason"] = "COUNTERFEIT_POSTURE"
            claim["held_by_user_id"] = None
            touch(claim)
            program = store.programs.get(claim["program_id"])
            if program is not None:
                recompute_reserve(program)
                touch(program)
            claimant = store.claimants.get(claim["claimant_id"])
            if claimant is not None and claimant["id"] not in [c["id"] for c in affected_claimants]:
                affected_claimants.append(claimant)
        for claimant in affected_claimants:
            refresh_adjudication(claimant)

    if sku["warranty_posture"] == "SUSPENDED" and previous_posture != "SUSPENDED":
        member_pack_ids = [m["pack_id"] for m in sku_pack_memberships(sku["id"])]
        for pack in sorted_rows([p for p in store.packs.values() if p["id"] in member_pack_ids]):
            if pack["status"] == "APPROVED":
                pack["status"] = "WITHDRAWN"
                touch(pack)
