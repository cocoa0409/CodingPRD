"""Pricing engine: resolution, expected-reimbursement chain, variance, cascades.

Implements PRD §3.5, §3.6 and scaffold §1.3 calculations.
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db as _db
from db import parse_date
from errors import (
    err_no_matching_term,
    err_claim_has_no_lines,
    err_missing_drg_weight,
    err_invalid_request,
    err_invalid_state,
    err_case_already_active,
)


def rhu(x):
    """Round half up to whole cents; x may be Decimal, int, or numeric string."""
    if not isinstance(x, Decimal):
        x = Decimal(str(x))
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


DEFAULT_THRESHOLD_CENTS = 5000
DEFAULT_THRESHOLD_BP = 100


# ---------------------------------------------------------------------------
# Paid / variance / threshold
# ---------------------------------------------------------------------------

def compute_paid_amount(claim_id):
    total = 0
    for r in _db.store.remittances.values():
        if r["claim_id"] == claim_id and r["status"] == "POSTED":
            total += r["paid_amount_cents"]
    return total


def compute_variance(claim):
    exp = claim.get("expected_reimbursement_cents")
    if exp is None:
        return None
    return exp - compute_paid_amount(claim["id"])


def queue_threshold(claim):
    """max(absolute floor, round_half_up(expected * bp / 10000)); defaults for non-contract paths."""
    exp = claim.get("expected_reimbursement_cents") or 0
    contract = None
    if claim.get("priced_contract_id"):
        contract = _db.store.contracts.get(claim["priced_contract_id"])
    abs_leg = contract["underpayment_threshold_cents"] if contract else DEFAULT_THRESHOLD_CENTS
    bp = contract["underpayment_threshold_bp"] if contract else DEFAULT_THRESHOLD_BP
    rel_leg = rhu(Decimal(exp) * Decimal(bp) / Decimal(10000))
    return max(abs_leg, rel_leg)


# ---------------------------------------------------------------------------
# Amendment rate resolution (§3.3)
# ---------------------------------------------------------------------------

def resolve_term_rates(contract_id, service_category, anchor):
    """Returns (term, base_rate_cents, percent_of_charge_bp) after EFFECTIVE amendments
    whose applicability date <= anchor. Greatest applicability_date wins; ties -> created_at ASC.
    Returns (None, None, None) if no term exists for the category."""
    term = None
    for t in _db.store.terms.values():
        if t["contract_id"] == contract_id and t["service_category"] == service_category:
            term = t
            break
    if term is None:
        return None, None, None
    base_rate = term.get("base_rate_cents")
    pct = term.get("percent_of_charge_bp")
    best = None
    best_key = None
    for a in _db.store.amendments.values():
        if a["contract_id"] != contract_id or a["status"] != "EFFECTIVE":
            continue
        applicability = a.get("retroactive_to_date") or a["effective_date"]
        if parse_date(applicability) > anchor:
            continue
        for ov in a.get("term_overrides", []):
            if ov.get("service_category") != service_category:
                continue
            key = (parse_date(applicability), -a["seq"])  # later date wins; tie -> earliest created_at (smaller seq)
            if best_key is None or key > best_key:
                # We must apply ONLY the winning amendment's overrides; track it
                best_key = key
                best = ov
    if best is not None:
        if "base_rate_cents" in best and best["base_rate_cents"] is not None:
            base_rate = best["base_rate_cents"]
        if "percent_of_charge_bp" in best and best["percent_of_charge_bp"] is not None:
            pct = best["percent_of_charge_bp"]
    return term, base_rate, pct


# ---------------------------------------------------------------------------
# Escalator adjustment (§3.5 stage 2)
# ---------------------------------------------------------------------------

def _applicable_escalators(contract_id, service_category):
    escs = []
    for e in _db.store.escalators.values():
        if e["contract_id"] != contract_id or e["status"] != "APPLIED":
            continue
        cat = e.get("applies_to_category")
        if cat is not None and cat != service_category:
            continue
        escs.append(e)
    escs.sort(key=lambda e: (parse_date(e["effective_date"]), e["seq"]))
    return escs


def _multiplier_at(escalators, day):
    m = Decimal(1)
    for e in escalators:
        if parse_date(e["effective_date"]) <= day:
            if e.get("compounding", True):
                m = m * (Decimal(1) + Decimal(e["escalator_bp"]) / Decimal(10000))
            else:
                m = m + Decimal(e["escalator_bp"]) / Decimal(10000)
    return m


def apply_escalators_per_diem(contract_id, service_category, base_rate_cents, admission, discharge):
    """Each calendar day d in [admission, discharge) gets its own multiplier; day rate
    = round_half_up(base_rate * m_d); return sum of day rates."""
    escs = _applicable_escalators(contract_id, service_category)
    total = 0
    d = admission
    while d < discharge:
        m = _multiplier_at(escs, d)
        total += rhu(Decimal(base_rate_cents) * m)
        d = d + timedelta(days=1)
    return total


def apply_escalators_flat(contract_id, service_category, base, anchor):
    """Non-PER_DIEM: multiplier evaluated at anchor; round half up once."""
    escs = _applicable_escalators(contract_id, service_category)
    m = _multiplier_at(escs, anchor)
    return rhu(Decimal(base) * m)


# ---------------------------------------------------------------------------
# Volume tiers (§3.5 stage 3)
# ---------------------------------------------------------------------------

def covered_days(claim):
    adm = parse_date(claim["admission_date"])
    dis = parse_date(claim["discharge_date"])
    return max(1, (dis - adm).days)


def select_volume_tier(contract, claim, exclude_claim_id=None):
    tiers = [t for t in (contract.get("volume_tiers") or []) if t.get("service_category") == claim["service_category"]]
    if not tiers:
        return None
    anchor = parse_date(claim["discharge_date"])
    window_start = anchor - timedelta(days=364)
    term, _, _ = resolve_term_rates(contract["id"], claim["service_category"], anchor)
    if term is None:
        return None
    U = 0
    for c in _db.store.claims.values():
        if c["id"] == exclude_claim_id:
            continue
        if c.get("priced_contract_id") != contract["id"]:
            continue
        if c["pricing_status"] not in {"PRICED", "REPRICED"}:
            continue
        if c["service_category"] != claim["service_category"]:
            continue
        d = parse_date(c["discharge_date"])
        if not (window_start <= d <= anchor):
            continue
        rm = term["rate_model"]
        if rm == "PER_DIEM":
            U += covered_days(c)
        elif rm in {"CASE_RATE", "DRG_BASE"}:
            U += 1
        else:  # PERCENT_OF_CHARGE
            U += c["total_billed_charges_cents"]
    best = None
    for t in tiers:
        if U >= t["min_annual_units"]:
            if best is None or t["min_annual_units"] > best["min_annual_units"]:
                best = t
    return best


# ---------------------------------------------------------------------------
# Carve-outs (§3.5 stage 4)
# ---------------------------------------------------------------------------

def _carve_provisions(contract_id):
    provs = [p for p in _db.store.carve_outs.values() if p["contract_id"] == contract_id]
    provs.sort(key=lambda p: p["seq"])
    return provs


def price_carve_outs(contract_id, lines):
    """Returns (carve_out_cents, per_line_priced map line_id->amount).
    Raises ERR_INVALID_REQUEST when INVOICE_COST_PLUS line lacks invoice_cost_cents."""
    provs = _carve_provisions(contract_id)
    total = 0
    per_line = {}
    for line in lines:
        match = None
        for p in provs:
            if line["revenue_code"] in (p.get("revenue_codes") or []):
                match = p
                break  # earliest-created provision wins
        if match is None:
            continue
        if match["rate_model"] == "PERCENT_OF_CHARGE":
            raw = Decimal(line["charge_cents"]) * Decimal(match["percent_bp"]) / Decimal(10000)
        else:  # INVOICE_COST_PLUS
            cost = line.get("invoice_cost_cents")
            if cost is None:
                raise err_invalid_request(
                    "invoice_cost_cents is required for lines matched by an INVOICE_COST_PLUS carve-out"
                )
            raw = Decimal(cost) * (Decimal(1) + Decimal(match["invoice_markup_bp"]) / Decimal(10000))
        amt = rhu(raw)
        cap = match.get("max_cap_cents")
        if cap is not None and amt > cap:
            amt = cap
        per_line[line["id"]] = amt
        total += amt
    return total, per_line


def is_carve_out_line(contract_id, revenue_code):
    for p in _db.store.carve_outs.values():
        if p["contract_id"] == contract_id and revenue_code in (p.get("revenue_codes") or []):
            return True
    return False


# ---------------------------------------------------------------------------
# Stop-loss / outlier overlay (§3.5 stage 5)
# ---------------------------------------------------------------------------

def _pick_provision(contract_id, service_category, ptype):
    specific = None
    wildcard = None
    for p in _db.store.stop_losses.values():
        if p["contract_id"] != contract_id or p["provision_type"] != ptype:
            continue
        cat = p.get("service_category")
        if cat == service_category:
            if specific is None or p["seq"] < specific["seq"]:
                specific = p
        elif cat is None:
            if wildcard is None or p["seq"] < wildcard["seq"]:
                wildcard = p
    return specific or wildcard


def stop_loss_outlier_overlay(contract_id, claim, tiered_base, carve_out_cents):
    cat = claim["service_category"]
    charges = claim["total_billed_charges_cents"]
    outlier_cents = 0
    outlier = _pick_provision(contract_id, cat, "OUTLIER")
    if outlier is not None and charges >= outlier["threshold_cents"]:
        outlier_cents = rhu(
            Decimal(charges - outlier["threshold_cents"]) * Decimal(outlier["rate_bp"]) / Decimal(10000)
        )
    subtotal = tiered_base + carve_out_cents + outlier_cents
    stop_loss_cents = 0
    final = subtotal
    sl = _pick_provision(contract_id, cat, "STOP_LOSS")
    if sl is not None and charges >= sl["threshold_cents"]:
        stop_loss_cents = rhu(Decimal(charges) * Decimal(sl["rate_bp"]) / Decimal(10000))
        final = max(subtotal, stop_loss_cents)
    return final, outlier_cents, stop_loss_cents


# ---------------------------------------------------------------------------
# Pricing contract resolution (§3.5)
# ---------------------------------------------------------------------------

def resolve_payment_instrument(claim):
    """Returns dict with resolution_path in {CONTRACT, WRAP_CONFIRMED, SILENT_PPO_SUSPECT, OUT_OF_NETWORK}
    plus contract / agreement references."""
    payer_id = claim["payer_id"]
    anchor = parse_date(claim["discharge_date"])

    # Step 1: contract path — status != DRAFT, window contains anchor
    cands = []
    for c in _db.store.contracts.values():
        if c["payer_id"] != payer_id or c["status"] == "DRAFT":
            continue
        if parse_date(c["effective_date"]) <= anchor <= parse_date(c["expiration_date"]):
            cands.append(c)
    if cands:
        cands.sort(key=lambda c: (-parse_date(c["effective_date"]).toordinal(), c["seq"]))
        winner = cands[0]
        return {
            "resolution_path": "CONTRACT",
            "contract": winner,
            "agreement": None,
            "network_flag": "NONE",
        }

    # Step 2: wrap path — VERIFIED agreements covering anchor
    wraps = []
    for n in _db.store.network_agreements.values():
        if n["payer_id"] != payer_id or n["status"] != "VERIFIED":
            continue
        if parse_date(n["effective_date"]) <= anchor <= parse_date(n["expiration_date"]):
            wraps.append(n)
    if wraps:
        wraps.sort(key=lambda n: (-n["wrap_rate_bp"], n["precedence_rank"], n["seq"]))
        winner = wraps[0]
        return {
            "resolution_path": "WRAP_CONFIRMED",
            "contract": None,
            "agreement": winner,
            "network_flag": "WRAP_CONFIRMED",
        }

    # Step 3: suspect path — any REGISTERED or FLAGGED_SUSPECT agreement covering anchor
    for n in _db.store.network_agreements.values():
        if n["payer_id"] != payer_id:
            continue
        if n["status"] not in {"REGISTERED", "FLAGGED_SUSPECT"}:
            continue
        if parse_date(n["effective_date"]) <= anchor <= parse_date(n["expiration_date"]):
            return {
                "resolution_path": "SILENT_PPO_SUSPECT",
                "contract": None,
                "agreement": None,
                "network_flag": "SILENT_PPO_SUSPECT",
            }

    # Step 4: out of network
    return {
        "resolution_path": "OUT_OF_NETWORK",
        "contract": None,
        "agreement": None,
        "network_flag": "OUT_OF_NETWORK",
    }


# ---------------------------------------------------------------------------
# Full pricing run
# ---------------------------------------------------------------------------

def run_pricing(claim, variant):
    """Runs the full pricing chain. Mutates the claim and its lines; does NOT
    touch variance/cases — caller follows with reevaluate_claim_after_change.
    Returns nothing; raises ApiError on failure (no state committed before raise
    for precondition failures)."""
    lines = [l for l in _db.store.claim_lines.values() if l["claim_id"] == claim["id"]]
    lines.sort(key=lambda l: l["seq"])

    resolution = resolve_payment_instrument(claim)
    anchor = parse_date(claim["discharge_date"])

    trace = {
        "resolution_path": resolution["resolution_path"],
        "contract_id": None,
        "term_id": None,
        "base_amount_cents": None,
        "escalated_amount_cents": None,
        "volume_tier_bp": None,
        "carve_out_cents": None,
        "outlier_cents": None,
        "stop_loss_cents": None,
        "wrap_rate_bp": None,
        "final_expected_cents": None,
    }

    if resolution["resolution_path"] in {"SILENT_PPO_SUSPECT", "OUT_OF_NETWORK"}:
        expected = claim["total_billed_charges_cents"]
        trace["final_expected_cents"] = expected
        priced_contract_id = None
        network_agreement_id = None
        # line priced amounts: no contract; leave at full charge per line
        for l in lines:
            l["is_carve_out"] = False
            l["priced_amount_cents"] = l["charge_cents"]
            _touch(l)

    elif resolution["resolution_path"] == "WRAP_CONFIRMED":
        agreement = resolution["agreement"]
        expected = 0
        for l in lines:
            amt = rhu(Decimal(l["charge_cents"]) * Decimal(agreement["wrap_rate_bp"]) / Decimal(10000))
            l["is_carve_out"] = False
            l["priced_amount_cents"] = amt
            _touch(l)
            expected += amt
        trace["wrap_rate_bp"] = agreement["wrap_rate_bp"]
        trace["final_expected_cents"] = expected
        priced_contract_id = None
        network_agreement_id = agreement["id"]

    else:  # CONTRACT
        contract = resolution["contract"]
        priced_contract_id = contract["id"]
        network_agreement_id = None
        term, base_rate, pct = resolve_term_rates(contract["id"], claim["service_category"], anchor)
        if term is None:
            raise err_no_matching_term()
        trace["contract_id"] = contract["id"]
        trace["term_id"] = term["id"]

        # Preconditions that need the resolved term (rung 8 fires before rung 10)
        if not lines:
            raise err_claim_has_no_lines()
        if term["rate_model"] == "DRG_BASE" and claim.get("drg_weight") is None:
            raise err_missing_drg_weight()

        # Stage 1: base
        if term["rate_model"] == "PER_DIEM":
            # covered days = max(1, discharge - admission); escalation per day below
            adm = parse_date(claim["admission_date"])
            dis = parse_date(claim["discharge_date"])
            days = max(1, (dis - adm).days)
            if days == 1 and adm == dis:
                # same-day stay: a single day at the rate, multiplier at that day
                escs = _applicable_escalators(contract["id"], claim["service_category"])
                m = _multiplier_at(escs, adm)
                escalated = rhu(Decimal(base_rate) * m)
                base = base_rate
            else:
                base = base_rate * days
                escalated = apply_escalators_per_diem(
                    contract["id"], claim["service_category"], base_rate, adm, dis
                )
            for l in lines:
                l["is_carve_out"] = is_carve_out_line(contract["id"], l["revenue_code"])
                l["priced_amount_cents"] = None
                _touch(l)
        elif term["rate_model"] == "CASE_RATE":
            base = base_rate
            escalated = apply_escalators_flat(contract["id"], claim["service_category"], base, anchor)
            for l in lines:
                l["is_carve_out"] = is_carve_out_line(contract["id"], l["revenue_code"])
                l["priced_amount_cents"] = None
                _touch(l)
        elif term["rate_model"] == "DRG_BASE":
            base = rhu(Decimal(base_rate) * Decimal(str(claim["drg_weight"])))
            escalated = apply_escalators_flat(contract["id"], claim["service_category"], base, anchor)
            for l in lines:
                l["is_carve_out"] = is_carve_out_line(contract["id"], l["revenue_code"])
                l["priced_amount_cents"] = None
                _touch(l)
        else:  # PERCENT_OF_CHARGE — per non-carved line, round per line then sum
            base = 0
            for l in lines:
                carved = is_carve_out_line(contract["id"], l["revenue_code"])
                l["is_carve_out"] = carved
                if carved:
                    l["priced_amount_cents"] = None  # set by carve stage
                else:
                    amt = rhu(Decimal(l["charge_cents"]) * Decimal(pct) / Decimal(10000))
                    l["priced_amount_cents"] = amt
                    base += amt
                _touch(l)
            escalated = apply_escalators_flat(contract["id"], claim["service_category"], base, anchor)

        trace["base_amount_cents"] = base
        trace["escalated_amount_cents"] = escalated

        # Stage 3: volume tiers
        tier = select_volume_tier(contract, claim, exclude_claim_id=claim["id"])
        tier_bp = tier["rate_adjustment_bp"] if tier else 0
        tiered = rhu(Decimal(escalated) * (Decimal(1) + Decimal(tier_bp) / Decimal(10000))) if tier else escalated
        trace["volume_tier_bp"] = tier_bp if tier else 0

        # Stage 4: carve-outs
        carve_total, per_line = price_carve_outs(contract["id"], lines)
        for l in lines:
            if l["id"] in per_line:
                l["priced_amount_cents"] = per_line[l["id"]]
                _touch(l)
        trace["carve_out_cents"] = carve_total

        # Stage 5: stop-loss / outlier overlay
        final, outlier_cents, stop_loss_cents = stop_loss_outlier_overlay(
            contract["id"], claim, tiered, carve_total
        )
        trace["outlier_cents"] = outlier_cents
        trace["stop_loss_cents"] = stop_loss_cents
        trace["final_expected_cents"] = final
        expected = final

    claim["expected_reimbursement_cents"] = expected
    if variant == "PROSPECTIVE":
        claim["original_expected_cents"] = expected
        claim["pricing_status"] = "PRICED"
    else:
        claim["pricing_status"] = "REPRICED"
    claim["pricing_variant"] = variant
    claim["priced_contract_id"] = priced_contract_id
    claim["network_agreement_id"] = network_agreement_id
    claim["network_flag"] = resolution["network_flag"]
    claim["pricing_trace"] = trace
    _touch(claim)


# ---------------------------------------------------------------------------
# Remittance-dimension re-evaluation and case queue interaction
# ---------------------------------------------------------------------------

def _active_case_for_claim(claim_id):
    for c in _db.store.cases.values():
        if c["claim_id"] == claim_id and c["status"] not in {
            "RECOVERED", "DENIED_FINAL", "WRITTEN_OFF", "WITHDRAWN",
        }:
            return c
    return None


def _any_case_for_claim(claim_id):
    for c in _db.store.cases.values():
        if c["claim_id"] == claim_id:
            return c
    return None


def queue_threshold_met(claim):
    v = compute_variance(claim)
    if v is None:
        return False
    return v >= queue_threshold(claim)


def create_case_for_claim(claim):
    """Creates a QUEUED UnderpaymentCase. Caller guarantees no active case exists.
    Raises ERR_CASE_ALREADY_ACTIVE defensively."""
    if _active_case_for_claim(claim["id"]) is not None:
        raise err_case_already_active()
    case_id = _db.new_id()
    now = _db.now_iso()
    case = {
        "id": case_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": _db.store.next_seq(),
        "claim_id": claim["id"],
        "payer_id": claim["payer_id"],
        "contract_id": claim.get("priced_contract_id"),
        "original_variance_cents": compute_variance(claim) or 0,
        "write_off_amount_cents": 0,
        "escalation_level": 0,
        "status": "QUEUED",
        "claimed_by_user_id": None,
        "queued_date": _db.today().isoformat(),
    }
    _db.store.cases[case_id] = case
    return case


def restate_case(case, claim):
    """original_variance_cents := claim.variance_cents; outstanding recomputed at read."""
    case["original_variance_cents"] = compute_variance(claim) or 0
    _touch(case)


def reevaluate_claim_after_change(claim, restate_original=False, payment_driven=False):
    """Runs the remittance-dimension machine + case queue consequences after any
    paid/expected change on the claim (price, reprice, remittance post/reverse,
    appeal recovery). Caller must have updated expected/paid inputs already.

    restate_original=True rewrites the active case's original_variance_cents :=
    claim.variance_cents (PRD §3.6: every landing restates the active case —
    "its original_variance_cents overwritten with the current variance and its
    outstanding recomputed"). The appeal-recovery path (record_outcome) passes
    False: recoveries are tracked in recovered_to_date_cents, and restating
    original would double-count them against the §3.7 money-ledger invariant.

    payment_driven=True marks callers whose event is a payment or recovery
    (remittance post, appeal recovery). Only those may fire the §3.7
    auto-RECOVERED transition ("the moment a payment or recovery drives
    current_outstanding_cents to zero"), and only for a case "in UNDER_REVIEW
    or at any appeal level" — never QUEUED, and never on a reprice/restate
    event (§3.6: landing on RECONCILED "never auto-closes" the case).

    Rules (PRD §3.6):
      - no POSTED remittances -> AWAITING_REMITTANCE; restate active case if any
      - else variance >= threshold -> VARIANCE_FLAGGED; create/restate case
      - else -> RECONCILED; restate active case, never auto-close
    """
    posted = [r for r in _db.store.remittances.values()
              if r["claim_id"] == claim["id"] and r["status"] == "POSTED"]
    active_case = _active_case_for_claim(claim["id"])

    if not posted:
        claim["remittance_status"] = "AWAITING_REMITTANCE"
        _touch(claim)
        if active_case is not None and restate_original:
            restate_case(active_case, claim)
    else:
        if queue_threshold_met(claim):
            claim["remittance_status"] = "VARIANCE_FLAGGED"
            _touch(claim)
            if active_case is None:
                active_case = create_case_for_claim(claim)
            elif restate_original:
                restate_case(active_case, claim)
        else:
            claim["remittance_status"] = "RECONCILED"
            _touch(claim)
            if active_case is not None and restate_original:
                restate_case(active_case, claim)

    # §3.7 auto-RECOVERED: a payment or recovery drove the outstanding balance
    # to zero for a case in UNDER_REVIEW or at an appeal level.
    if active_case is not None and payment_driven:
        from services.cases import compute_case_ledger
        ledger = compute_case_ledger(active_case)
        if ledger["current_outstanding_cents"] == 0 and active_case["status"] in {
            "UNDER_REVIEW", "APPEAL_L1", "APPEAL_L2", "MEDIATION", "ARBITRATION",
        }:
            active_case["status"] = "RECOVERED"
            _touch(active_case)


def _touch(entity):
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = _db.now_iso()


def touch(entity):
    _touch(entity)
