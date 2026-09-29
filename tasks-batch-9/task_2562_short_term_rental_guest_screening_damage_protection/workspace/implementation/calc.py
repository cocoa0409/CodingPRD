"""Derived fields, calculations and cascades (PRD 3.x).

Every computed field is derived on read from the in-memory store, so a cascade
cannot leave a stale denormalised copy behind.  Version bumps remain explicit
because the PRD enumerates them one by one.
"""

from decimal import Decimal

from core import (at_time, db, dec, fail, hours, now, round_half_up, touch,
                  new_row, sort_rows)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def guest(gid):
    return db.guests.get(gid)


def host(hid):
    return db.hosts.get(hid)


def rule(rid):
    return db.jurisdiction_rules.get(rid)


def prop(pid):
    return db.properties.get(pid)


def reservation(rid):
    return db.reservations.get(rid)


def claim(cid):
    return db.damage_claims.get(cid)


def prop_rule(p):
    return db.jurisdiction_rules.get(p["jurisdiction_rule_id"])


def res_prop(r):
    return db.properties.get(r["property_id"])


def guest_reservations(guest_id):
    return [r for r in db.reservations.values() if r["guest_id"] == guest_id]


def guest_documents(guest_id):
    return [d for d in db.identity_documents.values()
            if d["guest_id"] == guest_id]


def property_devices(property_id):
    return [d for d in db.monitoring_devices.values()
            if d["property_id"] == property_id]


def claim_evidence_rows(claim_id):
    return [e for e in db.claim_evidence.values() if e["claim_id"] == claim_id]


def claim_allocations(claim_id):
    return [a for a in db.settlement_allocations.values()
            if a["claim_id"] == claim_id]


def guest_incidents(guest_id):
    out = []
    for inc in db.incidents.values():
        r = db.reservations.get(inc["reservation_id"])
        if r is not None and r["guest_id"] == guest_id:
            out.append(inc)
    return out


def guest_blocklist_entries(guest_id):
    return [b for b in db.blocklist_entries.values()
            if b["guest_id"] == guest_id]


# ---------------------------------------------------------------------------
# Guest verification and risk (PRD 3.2)
# ---------------------------------------------------------------------------

def accepted_doc_count(g):
    return len([d for d in guest_documents(g["id"])
                if d["review_state"] == "ACCEPTED"])


def accepted_gov_id_count(g):
    return len([d for d in guest_documents(g["id"])
                if d["review_state"] == "ACCEPTED"
                and d["doc_type"] == "GOVERNMENT_ID"])


def verification_state(g):
    docs = guest_documents(g["id"])
    if accepted_gov_id_count(g) >= 1 and accepted_doc_count(g) >= 2:
        return "VERIFIED"
    if any(d["review_state"] == "PENDING" for d in docs):
        return "PENDING_REVIEW"
    if any(d["review_state"] == "EXPIRED" for d in docs):
        return "VERIFICATION_EXPIRED"
    return "UNVERIFIED"


def completed_stay_count(g):
    return len([r for r in guest_reservations(g["id"])
                if r["stay_state"] == "COMPLETED"])


SUBSTANTIATED_STATES = ("ACKNOWLEDGED", "ESCALATED_LAW_ENFORCEMENT", "CLOSED")


def substantiated_incident_count(g):
    return len([i for i in guest_incidents(g["id"])
                if i["substantiated"] is True
                and i["incident_state"] in SUBSTANTIATED_STATES])


def escalated_incident_count(g):
    return len([i for i in guest_incidents(g["id"]) if i["escalated"] is True])


def approved_claim_count(g):
    return g["approved_claim_count"]


def deposit_held_cents(g):
    total = 0
    for r in guest_reservations(g["id"]):
        if r["deposit_state"] == "HELD":
            total += r["deposit_hold_cents"]
    return total


ENFORCING_STATES = ("ACTIVE", "DISPUTED")


def active_blocklist_scope_count(g):
    return len([b for b in guest_blocklist_entries(g["id"])
                if b["entry_state"] in ENFORCING_STATES])


SIGNAL_POINTS = {"CLEAN": 0, "WATCH": 12, "ADVERSE": 30}


def risk_score(g):
    raw = 35
    if verification_state(g) == "VERIFIED":
        raw += -15
    raw += max(-20, -4 * completed_stay_count(g))
    raw += SIGNAL_POINTS[g["payment_risk_signal"]]
    raw += 5 * g["chargeback_count"]
    raw += min(40, 9 * substantiated_incident_count(g)
               + 25 * escalated_incident_count(g))
    raw += 7 * approved_claim_count(g)
    if raw < 0:
        return 0
    if raw > 100:
        return 100
    return raw


def risk_tier_of(score):
    if score <= 24:
        return "LOW"
    if score <= 49:
        return "ELEVATED"
    if score <= 74:
        return "HIGH"
    return "CRITICAL"


def risk_tier(g):
    return risk_tier_of(risk_score(g))


# ---------------------------------------------------------------------------
# Blocklist coverage (PRD 3.9)
# ---------------------------------------------------------------------------

def entry_covers(entry, p):
    scope = entry["scope"]
    if scope == "PLATFORM":
        return True
    if scope == "HOST":
        return entry["host_id"] == p["host_id"]
    if scope == "PROPERTY":
        return entry["property_id"] == p["id"]
    return False


def is_blocklisted(guest_id, p):
    for entry in guest_blocklist_entries(guest_id):
        if entry["entry_state"] in ENFORCING_STATES and entry_covers(entry, p):
            return True
    return False


# ---------------------------------------------------------------------------
# Listing postures (PRD 3.1)
# ---------------------------------------------------------------------------

def sensor_compliance_state(p):
    devices = property_devices(p["id"])
    if any(d["disclosure_state"] == "REJECTED" for d in devices):
        return "NON_COMPLIANT"
    if any(d["disclosure_state"] in ("DRAFT", "PENDING_REVIEW")
           for d in devices):
        return "PENDING_REVIEW"
    return "COMPLIANT"


def layer_consumed_cents(layer):
    total = 0
    for alloc in db.settlement_allocations.values():
        if alloc["coverage_layer_id"] == layer["id"] and not alloc["voided"]:
            total += alloc["gross_cents"]
    return total


def visible_layers(p):
    out = []
    for layer in db.coverage_layers.values():
        if layer["scope"] == "PLATFORM_GLOBAL" \
                or layer["property_id"] == p["id"]:
            out.append(layer)
    return out


def coverage_posture(p):
    visible = visible_layers(p)
    available = [l for l in visible if l["layer_state"] == "AVAILABLE"]
    if len(available) == 0:
        return "UNPROTECTED"
    if len(available) < len(visible):
        return "REDUCED"
    return "FULL"


def open_reservation_count(p):
    return len([r for r in db.reservations.values()
                if r["property_id"] == p["id"]
                and r["stay_state"] in ("REQUESTED", "CONFIRMED", "IN_STAY")])


LIVE_CLAIM_STATES = ("AWAITING_EVIDENCE", "UNDER_REVIEW", "APPEALED")


def open_claim_count(p):
    total = 0
    for c in db.damage_claims.values():
        r = db.reservations.get(c["reservation_id"])
        if r is not None and r["property_id"] == p["id"] \
                and c["claim_state"] in LIVE_CLAIM_STATES:
            total += 1
    return total


def effective_max_occupancy(p):
    jr = prop_rule(p)
    cap = jr["max_occupancy_cap"] if jr else p["max_occupancy"]
    return min(p["max_occupancy"], cap)


def suspend_listing(p, reason):
    """ACTIVE -> SUSPENDED as the tail of a cascade fired in this request."""
    if p["listing_state"] != "ACTIVE":
        return False
    p["listing_state"] = "SUSPENDED"
    p["suspension_reason"] = reason
    touch(p)
    return True


# ---------------------------------------------------------------------------
# Blocklist creation and the CRITICAL auto-ban cascade (PRD 3.2 / 3.9)
# ---------------------------------------------------------------------------

def create_blocklist_row(guest_row, scope, reason_code, created_by_role,
                         created_by_user_id, property_id=None, host_id=None,
                         auto_generated=False):
    entry = new_row()
    entry.update({
        "guest_id": guest_row["id"],
        "scope": scope,
        "property_id": property_id,
        "host_id": host_id,
        "supersedes_entry_id": None,
        "reason_code": reason_code,
        "created_by_role": created_by_role,
        "created_by_user_id": created_by_user_id,
        "auto_generated": auto_generated,
        "entry_state": "ACTIVE",
        "dispute_window_state": "OPEN",
        "dispute_statement_code": None,
        "dispute_decided_by_user_id": None,
        "dispute_reason_code": None,
    })
    db.blocklist_entries[entry["id"]] = entry
    return entry


def cancel_future_dated_reservations(guest_row):
    """Every REQUESTED/CONFIRMED stay whose check_in_at is still ahead."""
    for r in sort_rows(guest_reservations(guest_row["id"])):
        if r["stay_state"] not in ("REQUESTED", "CONFIRMED"):
            continue
        if not (r["check_in_at"] > now()):
            continue
        r["stay_state"] = "CANCELLED"
        r["cancel_reason_code"] = "BLOCKLISTED"
        if r["deposit_state"] == "HELD":
            r["deposit_state"] = "RELEASED"
            r["deposit_refunded_cents"] = r["deposit_hold_cents"]
        touch(r)


def apply_risk_cascade(guest_row):
    """Fires when a live re-band pushes risk_tier to CRITICAL."""
    if risk_tier(guest_row) != "CRITICAL":
        return None
    for entry in guest_blocklist_entries(guest_row["id"]):
        if entry["scope"] == "PLATFORM" \
                and entry["entry_state"] in ENFORCING_STATES:
            return None
    entry = create_blocklist_row(
        guest_row, "PLATFORM", "RISK_TIER_CRITICAL",
        "system", "system", auto_generated=True)
    cancel_future_dated_reservations(guest_row)
    return entry


# ---------------------------------------------------------------------------
# Reservation charge (PRD 3.3)
# ---------------------------------------------------------------------------

WAIVER_MULTIPLIER = {
    "LOW": dec("1.00"),
    "ELEVATED": dec("1.25"),
    "HIGH": dec("1.60"),
    "CRITICAL": dec("2.00"),
}


def compute_charge(p, nights, tier):
    if p["protection_product"] == "WAIVER":
        deposit_hold_cents_value = 0
        waiver_fee = round_half_up(
            dec(p["waiver_nightly_fee_cents"]) * dec(nights)
            * WAIVER_MULTIPLIER[tier])
    else:
        deposit_hold_cents_value = p["deposit_amount_cents"]
        waiver_fee = 0
    accommodation = p["nightly_rate_cents"] * nights
    pre_fee = accommodation + waiver_fee
    # STEP 1 -- the band is pinned to pre_fee_subtotal_cents, never re-selected.
    pct = dec("0.035") if pre_fee < 100000 else dec("0.025")
    trust_fee = round_half_up(dec(pre_fee) * pct)
    return {
        "nights": nights,
        "accommodation_cents": accommodation,
        "waiver_fee_cents": waiver_fee,
        "pre_fee_subtotal_cents": pre_fee,
        "trust_fee_pct": float(pct),
        "trust_fee_cents": trust_fee,
        "total_charged_cents": pre_fee + trust_fee,
        "deposit_hold_cents": deposit_hold_cents_value,
    }


# ---------------------------------------------------------------------------
# Screening decision (PRD 3.3) -- top-down, first match wins.
# ---------------------------------------------------------------------------

def screening_decision(tier, event_declared, jr, p, guest_count):
    if tier == "CRITICAL":
        return "DENIED", "RISK_CRITICAL"
    if event_declared and (jr["events_prohibited"]
                           or p["event_policy"] == "EVENTS_PROHIBITED"):
        return "DENIED", "EVENT_PROHIBITED"
    if event_declared and tier == "HIGH":
        return "DENIED", "EVENT_RISK"
    if event_declared:
        return "MANUAL_REVIEW", "EVENT_REVIEW"
    if tier == "HIGH":
        return "MANUAL_REVIEW", "HIGH_RISK_REVIEW"
    if tier == "ELEVATED" and guest_count >= p["max_occupancy"]:
        return "MANUAL_REVIEW", "ELEVATED_FULL_HOUSE"
    return "CLEARED", "LOW_RISK_AUTO_CLEAR"


# ---------------------------------------------------------------------------
# Evidence requirement schedule (PRD 3.6)
# ---------------------------------------------------------------------------

def evidence_complete(c):
    rows = claim_evidence_rows(c["id"])

    def count(kind):
        return len([e for e in rows if e["evidence_type"] == kind])

    if count("PHOTO") < 2:
        return False
    if c["claimed_amount_cents"] >= 50000 and count("RECEIPT") < 1:
        return False
    if c["claimed_amount_cents"] >= 250000 and count("POLICE_REPORT") < 1:
        return False
    if c["incident_id"] is not None:
        inc = db.incidents.get(c["incident_id"])
        if inc is not None and inc["source"] == "SENSOR" \
                and count("SENSOR_LOG") < 1:
            return False
    if c["evidence_round"] > 1:
        if not any(e["evidence_round"] == c["evidence_round"] for e in rows):
            return False
    return True


# ---------------------------------------------------------------------------
# Settlement waterfall (PRD 3.7)
# ---------------------------------------------------------------------------

def eligible_layers(p):
    out = []
    for layer in db.coverage_layers.values():
        if layer["layer_state"] != "AVAILABLE":
            continue
        if not (layer["scope"] == "PLATFORM_GLOBAL"
                or layer["property_id"] == p["id"]):
            continue
        if layer["source"] == "DAMAGE_WAIVER" \
                and p["protection_product"] != "WAIVER":
            continue
        out.append(layer)
    # layer_order ascending, created_at ascending as the tie-break -- never id.
    return sorted(out, key=lambda l: (l["layer_order"], l["created_at"],
                                      l["_seq"]))


def layer_visible_properties(layer):
    if layer["scope"] == "PLATFORM_GLOBAL":
        return list(db.properties.values())
    target = db.properties.get(layer["property_id"])
    return [target] if target is not None else []


def refresh_layer_state(layer):
    consumed = layer_consumed_cents(layer)
    desired = "EXHAUSTED" if consumed >= layer["limit_cents"] else "AVAILABLE"
    if layer["layer_state"] == desired:
        return None
    layer["layer_state"] = desired
    touch(layer)
    return desired


def plan_waterfall(r, p, gross):
    """Pure computation -- no side effects."""
    remaining = gross
    deposit_slice = 0
    if r["deposit_state"] == "HELD":
        headroom = r["deposit_hold_cents"] - r["deposit_applied_cents"]
        if headroom < 0:
            headroom = 0
        deposit_slice = min(remaining, headroom)
        remaining -= deposit_slice
    lines = []
    sequence_index = 0
    for layer in eligible_layers(p):
        if remaining == 0:
            break
        capacity = layer["limit_cents"] - layer_consumed_cents(layer)
        if capacity <= 0:
            continue
        charged_gross = min(remaining, capacity)
        net = charged_gross - layer["deductible_cents"]
        if net < 0:
            net = 0
        allocated = round_half_up(dec(net) * dec(layer["coverage_pct"]))
        lines.append({
            "layer": layer,
            "sequence_index": sequence_index,
            "gross_cents": charged_gross,
            "deductible_cents": layer["deductible_cents"],
            "allocated_cents": allocated,
        })
        remaining -= charged_gross
        sequence_index += 1
    recovered = deposit_slice + sum(l["allocated_cents"] for l in lines)
    return {
        "deposit_slice": deposit_slice,
        "lines": lines,
        "recovered_cents": recovered,
        "uncovered_cents": remaining,
        "host_absorbed_cents": gross - recovered,
    }


def run_provisional_waterfall(c, r, p):
    gross = min(c["claimed_amount_cents"], p["claim_ceiling_cents"])
    plan = plan_waterfall(r, p, gross)
    c["projected_recovery_cents"] = plan["recovered_cents"]
    return plan


def run_final_waterfall(c, r, p, guest_row):
    gross = c["approved_amount_cents"]
    plan = plan_waterfall(r, p, gross)

    for line in plan["lines"]:
        alloc = new_row(with_version=False)
        alloc.update({
            "claim_id": c["id"],
            "coverage_layer_id": line["layer"]["id"],
            "sequence_index": line["sequence_index"],
            "gross_cents": line["gross_cents"],
            "deductible_cents": line["deductible_cents"],
            "allocated_cents": line["allocated_cents"],
            "voided": False,
        })
        db.settlement_allocations[alloc["id"]] = alloc

    if plan["deposit_slice"] > 0:
        r["deposit_state"] = "APPLIED"
        r["deposit_applied_cents"] = plan["deposit_slice"]
        touch(r)
        if guest_row is not None:
            touch(guest_row)

    c["deposit_applied_cents"] = plan["deposit_slice"]
    c["recovered_cents"] = plan["recovered_cents"]
    c["uncovered_cents"] = plan["uncovered_cents"]
    c["host_absorbed_cents"] = plan["host_absorbed_cents"]

    for line in plan["lines"]:
        if refresh_layer_state(line["layer"]) == "EXHAUSTED":
            for target in layer_visible_properties(line["layer"]):
                if target["listing_state"] == "ACTIVE" \
                        and coverage_posture(target) == "UNPROTECTED":
                    suspend_listing(target, "COVERAGE_EXHAUSTED")
    return plan


def void_allocations(c):
    """Overturned approval -- every line is voided and capacity returns."""
    affected = []
    for alloc in claim_allocations(c["id"]):
        if not alloc["voided"]:
            alloc["voided"] = True
            affected.append(db.coverage_layers.get(alloc["coverage_layer_id"]))
    for layer in affected:
        if layer is not None:
            refresh_layer_state(layer)
