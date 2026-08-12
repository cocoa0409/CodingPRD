"""Core domain services: entity construction, hierarchical lookups, and every
recomputation routine (solvency, loss ratios, fronting fee, collateral,
allocations, reserves, annual statement, risk distribution)."""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

import db
from clock import fmt_ts, now, now_iso, parse_ts
from errors import ApiError
from services import constants as C

D0 = Decimal("0")
D100 = Decimal("100")


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

def to_cents(value) -> int:
    """Round a numeric value to integer cents, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_2dp(value) -> float:
    """Round a ratio/percentage to 2 decimal places, half-up."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Entity bookkeeping
# ---------------------------------------------------------------------------

def new_id() -> str:
    return str(uuid.uuid4())


def stamp_new() -> dict:
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def touch(entity: dict) -> None:
    """Refresh updated_at and bump version on mutation."""
    entity["updated_at"] = now_iso()
    entity["version"] = int(entity.get("version", 1)) + 1


def touch_captive(captive: dict) -> None:
    touch(captive)


# ---------------------------------------------------------------------------
# Hierarchical lookups (PRD 2.4 — path params validated left-to-right)
# ---------------------------------------------------------------------------

def get_captive(cid) -> dict:
    ent = db.captives.get(cid)
    if ent is None:
        raise ApiError("ERR_CAPTIVE_NOT_FOUND", "Captive entity not found")
    return ent


def get_filing(captive, fid) -> dict:
    ent = db.filings.get(fid)
    if ent is None or ent["captive_id"] != captive["id"]:
        raise ApiError("ERR_FILING_NOT_FOUND", "Domicile filing not found")
    return ent


def get_program(captive, pid) -> dict:
    ent = db.programs.get(pid)
    if ent is None or ent["captive_id"] != captive["id"]:
        raise ApiError("ERR_PROGRAM_NOT_FOUND", "Insurance program not found")
    return ent


def get_fronting(program, fid) -> dict:
    ent = db.frontings.get(fid)
    if ent is None or ent["program_id"] != program["id"]:
        raise ApiError("ERR_FRONTING_NOT_FOUND", "Fronting arrangement not found")
    return ent


def get_collateral(fronting, cid) -> dict:
    ent = db.collaterals.get(cid)
    if ent is None or ent["fronting_arrangement_id"] != fronting["id"]:
        raise ApiError("ERR_COLLATERAL_NOT_FOUND", "Collateral posting not found")
    return ent


def get_unit(captive, uid) -> dict:
    ent = db.units.get(uid)
    if ent is None or ent["captive_id"] != captive["id"]:
        raise ApiError("ERR_OPERATING_UNIT_NOT_FOUND", "Operating unit not found")
    return ent


def get_allocation(program, aid) -> dict:
    ent = db.allocations.get(aid)
    if ent is None or ent["program_id"] != program["id"]:
        raise ApiError("ERR_ALLOCATION_NOT_FOUND", "Premium allocation not found")
    return ent


def get_claim(program, cid) -> dict:
    ent = db.claims.get(cid)
    if ent is None or ent["program_id"] != program["id"]:
        raise ApiError("ERR_CLAIM_NOT_FOUND", "Claim not found")
    return ent


def get_tpa(claim, tid) -> dict:
    ent = db.tpas.get(tid)
    if ent is None or ent["claim_id"] != claim["id"]:
        raise ApiError("ERR_TPA_NOT_FOUND", "TPA assignment not found")
    return ent


def get_reserve(program, rid) -> dict:
    ent = db.reserves.get(rid)
    if ent is None or ent["program_id"] != program["id"]:
        raise ApiError("ERR_RESERVE_NOT_FOUND", "Actuarial reserve not found")
    return ent


def get_statement(captive, sid) -> dict:
    ent = db.statements.get(sid)
    if ent is None or ent["captive_id"] != captive["id"]:
        raise ApiError("ERR_STATEMENT_NOT_FOUND", "Annual statement not found")
    return ent


def get_meeting(captive, mid) -> dict:
    ent = db.meetings.get(mid)
    if ent is None or ent["captive_id"] != captive["id"]:
        raise ApiError("ERR_MEETING_NOT_FOUND", "Board meeting not found")
    return ent


def get_tax_position(captive, pid) -> dict:
    ent = db.tax_positions.get(pid)
    if ent is None or ent["captive_id"] != captive["id"]:
        raise ApiError("ERR_TAX_POSITION_NOT_FOUND", "Tax position not found")
    return ent


def get_audit_log(captive, lid) -> dict:
    ent = db.audit_logs.get(lid)
    if ent is None or ent["captive_id"] != captive["id"]:
        raise ApiError("ERR_AUDIT_LOG_NOT_FOUND", "Audit log entry not found")
    return ent


# Flat lookups (no parent in path) — same not-found ids.
def flat_filing(fid) -> dict:
    ent = db.filings.get(fid)
    if ent is None:
        raise ApiError("ERR_FILING_NOT_FOUND", "Domicile filing not found")
    return ent


def flat_program(pid) -> dict:
    ent = db.programs.get(pid)
    if ent is None:
        raise ApiError("ERR_PROGRAM_NOT_FOUND", "Insurance program not found")
    return ent


def flat_fronting(fid) -> dict:
    ent = db.frontings.get(fid)
    if ent is None:
        raise ApiError("ERR_FRONTING_NOT_FOUND", "Fronting arrangement not found")
    return ent


def flat_collateral(cid) -> dict:
    ent = db.collaterals.get(cid)
    if ent is None:
        raise ApiError("ERR_COLLATERAL_NOT_FOUND", "Collateral posting not found")
    return ent


def flat_unit(uid) -> dict:
    ent = db.units.get(uid)
    if ent is None:
        raise ApiError("ERR_OPERATING_UNIT_NOT_FOUND", "Operating unit not found")
    return ent


def flat_allocation(aid) -> dict:
    ent = db.allocations.get(aid)
    if ent is None:
        raise ApiError("ERR_ALLOCATION_NOT_FOUND", "Premium allocation not found")
    return ent


def flat_claim(cid) -> dict:
    ent = db.claims.get(cid)
    if ent is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", "Claim not found")
    return ent


def flat_tpa(tid) -> dict:
    ent = db.tpas.get(tid)
    if ent is None:
        raise ApiError("ERR_TPA_NOT_FOUND", "TPA assignment not found")
    return ent


def flat_reserve(rid) -> dict:
    ent = db.reserves.get(rid)
    if ent is None:
        raise ApiError("ERR_RESERVE_NOT_FOUND", "Actuarial reserve not found")
    return ent


def flat_statement(sid) -> dict:
    ent = db.statements.get(sid)
    if ent is None:
        raise ApiError("ERR_STATEMENT_NOT_FOUND", "Annual statement not found")
    return ent


def flat_meeting(mid) -> dict:
    ent = db.meetings.get(mid)
    if ent is None:
        raise ApiError("ERR_MEETING_NOT_FOUND", "Board meeting not found")
    return ent


def flat_tax_position(pid) -> dict:
    ent = db.tax_positions.get(pid)
    if ent is None:
        raise ApiError("ERR_TAX_POSITION_NOT_FOUND", "Tax position not found")
    return ent


def flat_audit_log(lid) -> dict:
    ent = db.audit_logs.get(lid)
    if ent is None:
        raise ApiError("ERR_AUDIT_LOG_NOT_FOUND", "Audit log entry not found")
    return ent


# ---------------------------------------------------------------------------
# Request-body helpers
# ---------------------------------------------------------------------------

def body():
    from flask import request

    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require_field(data: dict, name: str):
    val = data.get(name)
    if val is None:
        raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {name}")
    return val


def parse_dt_field(data: dict, name: str):
    raw = require_field(data, name)
    if isinstance(raw, bool) or not isinstance(raw, str):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} must be an ISO 8601 timestamp string")
    dt = parse_ts(raw)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} must be a valid ISO 8601 timestamp")
    return dt


def opt_str(data: dict, name: str):
    val = data.get(name)
    if val is None:
        return None
    if not isinstance(val, str):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} must be a string")
    return val


def req_str(data: dict, name: str) -> str:
    val = require_field(data, name)
    if not isinstance(val, str) or not val.strip():
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} must be a non-empty string")
    return val


def req_enum(data: dict, name: str, choices) -> str:
    val = require_field(data, name)
    if val not in choices:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} must be one of {list(choices)}")
    return val


def req_num(data: dict, name: str) -> float:
    val = require_field(data, name)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} must be a number")
    return val


def opt_num(data: dict, name: str, default=None):
    val = data.get(name)
    if val is None:
        return default
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} must be a number")
    return val


def req_int(data: dict, name: str) -> int:
    val = require_field(data, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    return val


def opt_bool(data: dict, name: str, default=False) -> bool:
    val = data.get(name)
    if val is None:
        return default
    if not isinstance(val, bool):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} must be a boolean")
    return val


# ---------------------------------------------------------------------------
# Governance
# ---------------------------------------------------------------------------

def adjust_governance(captive: dict, delta: int) -> None:
    score = int(captive.get("governance_score", C.GOVERNANCE_SCORE_INITIAL)) + delta
    if score > C.GOVERNANCE_SCORE_CAP:
        score = C.GOVERNANCE_SCORE_CAP
    captive["governance_score"] = score


# ---------------------------------------------------------------------------
# Captive ledger: admitted assets / solvency / reserves / premium written
# ---------------------------------------------------------------------------

def collateral_haircut(captive: dict, collateral_type: str) -> float:
    rate = C.HAIRCUTS.get(collateral_type, 0.0)
    if captive.get("tax_classification") == "MICRO_CAPTIVE_831B":
        rate = rate * C.CONSERVATIVE_HAIRCUT_MULTIPLIER
    return rate


def collateral_effective_value(captive: dict, collateral_type: str, amount_cents) -> int:
    rate = Decimal(str(collateral_haircut(captive, collateral_type)))
    return int((Decimal(str(amount_cents)) * (Decimal("1") - rate)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def recompute_captive_ledger(captive: dict) -> None:
    """Recompute admitted_assets, solvency ratio/status, total_reserves_held and
    total_premium_written from the underlying ledgers (PRD 2.8).

    Admitted assets rest on the captive's paid-in capitalization: the posted
    capital plus verified collateral values plus in-force premium allocations,
    minus settled claim payments.
    """
    cid = captive["id"]
    assets = Decimal(str(captive.get("capitalization_amount") or 0))
    for col in db.collaterals.values():
        if col["captive_id"] == cid and col["verification_status"] == "VERIFIED":
            assets += Decimal(str(col.get("effective_value_cents") or 0))
    for alloc in db.allocations.values():
        if alloc["captive_id"] == cid and alloc["status"] in ("PROVISIONAL", "AUDITED", "FINALIZED"):
            assets += Decimal(str(alloc.get("allocated_amount_cents") or 0))
    for claim in db.claims.values():
        if claim["captive_id"] == cid and claim["claim_status"] == "SETTLED":
            assets -= Decimal(str(claim.get("paid_amount_cents") or 0))
    captive["admitted_assets"] = int(assets)

    required = captive.get("capital_minimum_required") or 0
    if required > 0:
        ratio = Decimal(str(captive["admitted_assets"])) / Decimal(str(required)) * D100
        captive["solvency_ratio"] = to_2dp(ratio)
    else:
        captive["solvency_ratio"] = 0.0
    r = Decimal(str(captive["solvency_ratio"]))
    if r >= Decimal(str(C.SOLVENCY_WARNING_THRESHOLD)):
        captive["solvency_status"] = "ADEQUATE"
    elif r >= Decimal(str(C.SOLVENCY_BREACH_THRESHOLD)):
        captive["solvency_status"] = "WARNING"
    else:
        captive["solvency_status"] = "BREACH"

    reserves = D0
    for res in db.reserves.values():
        if res["captive_id"] == cid and res["status"] in ("CERTIFIED", "FILED"):
            reserves += Decimal(str(res.get("carried_reserve_cents") or 0))
    for claim in db.claims.values():
        if claim["captive_id"] == cid and claim["claim_status"] == "RESERVED":
            reserves += Decimal(str(claim.get("reserved_amount_cents") or 0))
    # Certified/filed actuarial reserves are booked liabilities; the assets
    # backing them remain admitted, so they do not reduce admitted assets.
    captive["total_reserves_held"] = int(reserves)

    premium = D0
    for alloc in db.allocations.values():
        if alloc["captive_id"] == cid and alloc["status"] in ("PROVISIONAL", "AUDITED", "FINALIZED"):
            premium += Decimal(str(alloc.get("allocated_amount_cents") or 0))
    captive["total_premium_written"] = int(premium)


# ---------------------------------------------------------------------------
# Fronting arrangement helpers
# ---------------------------------------------------------------------------

def compute_collateral_required(program: dict, fronting: dict) -> int:
    """Collateral required by the fronting carrier: ceded share of the
    program's aggregate limit."""
    ceded = Decimal(str(fronting.get("reinsurance_ceded_pct") or 0))
    return int((Decimal(str(program.get("aggregate_limit_cents") or 0)) * ceded).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def recompute_fronting_collateral(fronting: dict) -> None:
    posted = D0
    for col in db.collaterals.values():
        if col["fronting_arrangement_id"] == fronting["id"] and col["verification_status"] == "VERIFIED":
            posted += Decimal(str(col.get("effective_value_cents") or 0))
    fronting["collateral_posted_cents"] = int(posted)
    shortfall = Decimal(str(fronting.get("collateral_required_cents") or 0)) - posted
    fronting["collateral_shortfall_cents"] = int(shortfall) if shortfall > 0 else 0


def recompute_fronting_fee(fronting: dict) -> None:
    program = db.programs.get(fronting["program_id"])
    if not program:
        return
    fee = Decimal(str(program.get("premium_allocated_cents") or 0)) * Decimal(
        str(fronting.get("fronting_fee_pct") or 0))
    fronting["fronting_fee_amount_cents"] = int(fee.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def release_fronting_collateral(fronting: dict) -> None:
    """Flip every VERIFIED posting on the arrangement to RELEASED."""
    for col in db.collaterals.values():
        if col["fronting_arrangement_id"] == fronting["id"] and col["verification_status"] == "VERIFIED":
            col["verification_status"] = "RELEASED"
            touch(col)
    recompute_fronting_collateral(fronting)


def recompute_program_fronting_fees(program: dict) -> None:
    for fr in db.frontings.values():
        if fr["program_id"] == program["id"]:
            recompute_fronting_fee(fr)


# ---------------------------------------------------------------------------
# Program / unit loss ratios
# ---------------------------------------------------------------------------

def recompute_program_loss_ratio(program: dict) -> None:
    incurred = D0
    paid = D0
    for claim in db.claims.values():
        if claim["program_id"] != program["id"]:
            continue
        if claim["claim_status"] in ("RESERVED", "SETTLED", "DENIED", "CLOSED_WITHOUT_PAYMENT"):
            incurred += Decimal(str(claim.get("net_incurred_cents") or 0))
        paid += Decimal(str(claim.get("paid_amount_cents") or 0))
    program["claims_incurred_cents"] = int(incurred)
    program["claims_paid_cents"] = int(paid)
    alloc = program.get("premium_allocated_cents") or 0
    if alloc:
        program["loss_ratio"] = to_2dp(Decimal(str(incurred)) / Decimal(str(alloc)) * D100)
    else:
        program["loss_ratio"] = 0.0


def recompute_unit_loss_ratio(unit: dict) -> None:
    incurred = D0
    for claim in db.claims.values():
        if claim.get("operating_unit_id") == unit["id"]:
            incurred += Decimal(str(claim.get("net_incurred_cents") or 0))
    unit["total_claims_incurred_cents"] = int(incurred)
    alloc = unit.get("total_premium_allocated_cents") or 0
    if alloc:
        unit["loss_ratio"] = to_2dp(Decimal(str(incurred)) / Decimal(str(alloc)) * D100)
    else:
        unit["loss_ratio"] = 0.0


def recompute_claim_net(claim: dict) -> None:
    net = (Decimal(str(claim.get("paid_amount_cents") or 0))
           + Decimal(str(claim.get("reserved_amount_cents") or 0))
           - Decimal(str(claim.get("recoverable_amount_cents") or 0)))
    claim["net_incurred_cents"] = int(net)


# ---------------------------------------------------------------------------
# Premium allocation computation (PRD 3.5)
# ---------------------------------------------------------------------------

def active_units(captive_id) -> list:
    return [u for u in db.units.values()
            if u["captive_id"] == captive_id and u["status"] == "ACTIVE"]


def compute_allocation_amount(program: dict, unit: dict, method: str,
                              risk_weight: float, manual_amount,
                              provisional: bool) -> int:
    units = active_units(program["captive_id"])
    budget = Decimal(str(program.get("premium_budget_cents") or 0))
    if method == "EXPOSURE_PRO_RATA":
        total = sum(Decimal(str(u.get("exposure_amount") or 0)) for u in units)
        share = (Decimal(str(unit.get("exposure_amount") or 0)) / total) if total > 0 else D0
        amount = budget * share
    elif method == "EQUAL_SHARE":
        amount = budget / Decimal(len(units)) if units else D0
    elif method == "MANUAL":
        if manual_amount is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "allocated_amount_cents is required for MANUAL allocation")
        amount = Decimal(str(manual_amount))
    elif method == "RISK_WEIGHTED":
        rw = Decimal(str(risk_weight))
        weighted = Decimal(str(unit.get("exposure_amount") or 0)) * rw
        total_w = sum(Decimal(str(u.get("exposure_amount") or 0)) * rw for u in units)
        amount = budget * (weighted / total_w) if total_w > 0 else D0
    else:
        raise ApiError("ERR_INVALID_REQUEST", f"Unknown allocation_method: {method}")

    if provisional:
        # Provisional allocations round up to the nearest 100 cents (PRD 3.5).
        return int((amount / D100).quantize(Decimal("1"), rounding=ROUND_CEILING) * D100)
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Claim helpers
# ---------------------------------------------------------------------------

def next_claim_number() -> str:
    stamp = now().strftime("%Y%m%d")
    key = f"CLM-{stamp}"
    seq = db.claim_seq.get(key, 0) + 1
    db.claim_seq[key] = seq
    return f"{key}-{seq:04d}"


def compute_coverage_confirmed(program: dict, loss_dt, claimed_amount_cents) -> bool:
    start = parse_ts(program.get("policy_period_start"))
    end = parse_ts(program.get("policy_period_end"))
    if start is None or end is None or loss_dt is None:
        return False
    if loss_dt < start or loss_dt > end:
        return False
    amount = claimed_amount_cents or 0
    per_occ = program.get("per_occurrence_limit_cents")
    agg = program.get("aggregate_limit_cents")
    if per_occ is not None and amount > per_occ:
        return False
    if agg is not None and amount > agg:
        return False
    return True


def find_tpa(tpa_id):
    if not tpa_id:
        return None
    return db.tpas.get(tpa_id)


# ---------------------------------------------------------------------------
# Actuarial reserve estimation (PRD 3.7)
# ---------------------------------------------------------------------------

def compute_reserve_estimates(captive: dict, program: dict, reserve: dict) -> None:
    paid_losses = D0
    for claim in db.claims.values():
        if claim["program_id"] == program["id"]:
            paid_losses += Decimal(str(claim.get("paid_amount_cents") or 0))
    premium_allocated = Decimal(str(program.get("premium_allocated_cents") or 0))
    method = reserve.get("actuarial_method")
    lob = program.get("line_of_business")
    factor = Decimal(str(C.DEVELOPMENT_FACTORS.get(lob, 1.50)))
    reserve["development_factor"] = float(factor)
    elr = Decimal(str(C.DEFAULT_EXPECTED_LOSS_RATIO))

    if method == "CHAIN_LADDER":
        central = paid_losses * (factor - Decimal("1"))
    elif method == "BORNHUETTER_FERGUSON":
        central = elr * premium_allocated * (Decimal("1") - Decimal("1") / factor)
    elif method == "EXPECTED_LOSS_RATIO":
        central = elr * premium_allocated - paid_losses
    elif method == "BERQUIST_SHERMAN":
        central = paid_losses * (factor - Decimal("1"))
    else:
        central = D0

    # Net-of-reinsurance variant: reduce by ceded share when the program has a
    # fronting arrangement.
    ceded = D0
    for fr in db.frontings.values():
        if fr["program_id"] == program["id"]:
            ceded = Decimal(str(fr.get("reinsurance_ceded_pct") or 0))
            break
    if ceded > 0:
        central = central * (Decimal("1") - ceded)

    margin = Decimal(str(C.DEFAULT_MARGIN_PCT))
    low = central * (Decimal("1") - margin)
    high = central * (Decimal("1") + margin)

    confidence = reserve.get("confidence_level_pct", C.CONFIDENCE_LEVEL_DEFAULT)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = C.CONFIDENCE_LEVEL_DEFAULT
    # Interpolate carried reserve between low and high by confidence level:
    # 50 -> central estimate, 95 -> high estimate.
    t = (Decimal(str(confidence)) - Decimal("50")) / Decimal("45")
    if t < 0:
        t = D0
    if t > 1:
        t = Decimal("1")
    carried = central + t * (high - central)

    central_c = to_cents(central)
    low_c = to_cents(low)
    high_c = to_cents(high)
    carried_c = to_cents(carried)
    # Minimum reserve floor.
    floor = C.MIN_RESERVE_FLOOR
    if central_c < floor:
        central_c = floor
    if low_c < floor:
        low_c = floor
    if high_c < floor:
        high_c = floor
    if carried_c < low_c:
        carried_c = low_c
    if carried_c > high_c:
        carried_c = high_c

    reserve["central_estimate_cents"] = central_c
    reserve["low_estimate_cents"] = low_c
    reserve["high_estimate_cents"] = high_c
    reserve["carried_reserve_cents"] = carried_c


# ---------------------------------------------------------------------------
# Annual statement computation (PRD 3.8)
# ---------------------------------------------------------------------------

def compute_statement_fields(captive: dict, statement: dict) -> None:
    cid = captive["id"]
    year = int(statement["statement_year"])

    statement["filing_deadline"] = fmt_ts(
        parse_ts(f"{year + 1}-05-31T00:00:00Z"))

    statement["total_assets_cents"] = int(captive.get("admitted_assets") or 0)

    liabilities = D0
    for res in db.reserves.values():
        if res["captive_id"] == cid and res["status"] in ("CERTIFIED", "FILED"):
            liabilities += Decimal(str(res.get("carried_reserve_cents") or 0))
    for claim in db.claims.values():
        if claim["captive_id"] == cid:
            liabilities += Decimal(str(claim.get("reserved_amount_cents") or 0))
    statement["total_liabilities_cents"] = int(liabilities)

    surplus = Decimal(str(statement["total_assets_cents"])) - liabilities
    statement["policyholder_surplus_cents"] = int(surplus)

    premium = Decimal(str(captive.get("total_premium_written") or 0))
    statement["net_premium_written_cents"] = int(premium)

    losses = D0
    for claim in db.claims.values():
        if claim["captive_id"] == cid:
            losses += Decimal(str(claim.get("net_incurred_cents") or 0))
    statement["net_losses_incurred_cents"] = int(losses)

    if premium > 0:
        loss_ratio = losses / premium * D100
    else:
        loss_ratio = D0

    fees = D0
    for tpa in db.tpas.values():
        claim = db.claims.get(tpa["claim_id"])
        if claim and claim["captive_id"] == cid:
            fees += Decimal(str(tpa.get("fee_amount_cents") or 0))
    if premium > 0:
        expense_ratio = fees / premium * D100
    else:
        expense_ratio = D0
    statement["expense_ratio"] = to_2dp(expense_ratio)
    statement["combined_ratio"] = to_2dp(loss_ratio + expense_ratio)

    investment = Decimal(str(statement.get("investment_income_cents") or 0))
    underwriting = premium - losses - fees
    statement["underwriting_result_cents"] = int(underwriting)

    acl = Decimal(str(C.RBC_ACL_BASE))
    rbc = surplus / acl * D100
    statement["rbc_ratio"] = to_2dp(rbc)
    r = Decimal(str(statement["rbc_ratio"]))
    if r >= Decimal("200"):
        level = "NONE"
    elif r >= Decimal("150"):
        level = "COMPANY_ACTION"
    elif r >= Decimal("100"):
        level = "REGULATORY_ACTION"
    elif r >= Decimal("70"):
        level = "AUTHORIZED_CONTROL"
    else:
        level = "MANDATORY_CONTROL"
    statement["rbc_action_level"] = level


def statement_uncertified_reserves(captive: dict, statement: dict) -> list:
    """Reserves for the statement's year not yet CERTIFIED/FILED."""
    year = int(statement["statement_year"])
    bad = []
    for res in db.reserves.values():
        if res["captive_id"] != captive["id"]:
            continue
        vdt = parse_ts(res.get("valuation_date"))
        if vdt is not None and vdt.year == year and res["status"] not in (
                "CERTIFIED", "FILED", "SUPERSEDED"):
            bad.append(res)
    return bad


# ---------------------------------------------------------------------------
# Risk distribution analysis (PRD 3.10)
# ---------------------------------------------------------------------------

def compute_risk_distribution(captive: dict) -> dict:
    cid = captive["id"]

    insured_units = set()
    for alloc in db.allocations.values():
        if alloc["captive_id"] != cid:
            continue
        program = db.programs.get(alloc["program_id"])
        if program and program["program_status"] in ("IN_FORCE", "RUN_OFF"):
            insured_units.add(alloc["operating_unit_id"])
    for claim in db.claims.values():
        if claim["captive_id"] != cid:
            continue
        program = db.programs.get(claim["program_id"])
        if program and program["program_status"] in ("IN_FORCE", "RUN_OFF"):
            if claim.get("operating_unit_id"):
                insured_units.add(claim["operating_unit_id"])
    insured_entities_count = len(insured_units)

    if insured_entities_count >= C.MIN_INSURED_ENTITIES:
        entity_score = 40
    elif insured_entities_count >= C.MIN_INSURED_ENTITIES // 2:
        entity_score = 20
    else:
        entity_score = 0

    per_unit = {}
    total_premium = D0
    for alloc in db.allocations.values():
        if alloc["captive_id"] != cid:
            continue
        if alloc["status"] not in ("PROVISIONAL", "AUDITED", "FINALIZED"):
            continue
        amount = Decimal(str(alloc.get("allocated_amount_cents") or 0))
        per_unit[alloc["operating_unit_id"]] = per_unit.get(alloc["operating_unit_id"], D0) + amount
        total_premium += amount

    third_party_premium = D0
    captive_unit_ids = {u["id"] for u in db.units.values() if u["captive_id"] == cid}
    for uid, amount in per_unit.items():
        if uid not in captive_unit_ids:
            third_party_premium += amount
    if total_premium > 0:
        third_party_pct = to_2dp(third_party_premium / total_premium * D100)
    else:
        third_party_pct = 0.0

    if third_party_pct >= C.MIN_THIRD_PARTY_PCT:
        third_party_score = 30
    elif third_party_pct >= C.MIN_THIRD_PARTY_PCT / 2:
        third_party_score = 15
    else:
        third_party_score = 0

    if total_premium > 0 and per_unit:
        concentration = to_2dp(max(per_unit.values()) / total_premium * D100)
    else:
        concentration = 0.0
    if concentration <= C.MAX_CONCENTRATION_PCT:
        concentration_score = 30
    elif concentration <= C.MAX_CONCENTRATION_PCT * 1.5:
        concentration_score = 15
    else:
        concentration_score = 0

    score = entity_score + third_party_score + concentration_score
    if score >= 70:
        result = "PASS"
    elif score >= 40:
        result = "MARGINAL"
    else:
        result = "FAIL"

    premium_threshold_met = int(total_premium) <= C.MICRO_CAPTIVE_PREMIUM_LIMIT

    # Premium deductibility: full when risk distribution passes, half when
    # marginal, none on fail.
    if result == "PASS":
        deductibility = 100.0
    elif result == "MARGINAL":
        deductibility = 50.0
    else:
        deductibility = 0.0

    disclosure_required = (
        captive.get("tax_classification") == "MICRO_CAPTIVE_831B"
        and not premium_threshold_met
    ) or result == "FAIL"

    return {
        "insured_entities_count": insured_entities_count,
        "third_party_premium_pct": third_party_pct,
        "risk_distribution_score": score,
        "risk_distribution_test_result": result,
        "premium_deductibility_pct": deductibility,
        "premium_threshold_met": premium_threshold_met,
        "disclosure_required": disclosure_required,
        "total_premium_cents": int(total_premium),
    }
