"""ContractProposal endpoints (PRD §3.8)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db as _db
from db import parse_date
from errors import (
    err_not_found,
    err_invalid_state,
    err_invalid_request,
    err_stale_contract_version,
    err_contract_not_active,
    err_proposal_stale,
    err_invalid_rate_parameters,
    err_contract_window_overlap,
    err_duplicate_contract_code,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.serializers import serialize_proposal, serialize_contract
from services.validation import body, reject_unknown, as_str, as_int, as_enum, as_date, as_list
from services.pricing import (
    rhu,
    resolve_term_rates,
    apply_escalators_flat,
    apply_escalators_per_diem,
    covered_days,
    touch,
)
from routes.contracts import SERVICE_CATEGORIES, _check_window_overlap, _validate_volume_tiers

bp = Blueprint("proposals", __name__)

RATE_MODELS = {"PER_DIEM", "CASE_RATE", "PERCENT_OF_CHARGE", "DRG_BASE"}
PROPOSAL_STATUSES = {"DRAFT", "MODELED", "SUBMITTED", "COUNTERED", "ACCEPTED", "REJECTED", "WITHDRAWN"}
OPEN_STATUSES = {"DRAFT", "MODELED", "SUBMITTED", "COUNTERED"}
DRG_NORMALIZED_WEIGHT = Decimal("1.000")


def _validate_proposed_terms(contract_id, proposed_terms):
    if not isinstance(proposed_terms, list) or not proposed_terms:
        raise err_invalid_request("proposed_terms must be a non-empty list")
    for pt in proposed_terms:
        if not isinstance(pt, dict):
            raise err_invalid_request("proposed_terms entries must be objects")
        extra = set(pt.keys()) - {"service_category", "rate_model", "base_rate_cents", "percent_of_charge_bp"}
        if extra:
            raise err_invalid_request(f"Unknown proposed_terms fields: {sorted(extra)}")
        cat = pt.get("service_category")
        if cat not in SERVICE_CATEGORIES:
            raise err_invalid_request("proposed_terms.service_category invalid")
        rm = pt.get("rate_model")
        if rm not in RATE_MODELS:
            raise err_invalid_request("proposed_terms.rate_model invalid")
        brc = pt.get("base_rate_cents")
        pct = pt.get("percent_of_charge_bp")
        if brc is not None and (isinstance(brc, bool) or not isinstance(brc, int) or brc < 0):
            raise err_invalid_request("base_rate_cents must be a non-negative integer")
        if pct is not None and (isinstance(pct, bool) or not isinstance(pct, int) or pct < 0 or pct > 10000):
            raise err_invalid_request("percent_of_charge_bp must be in [0, 10000]")
        if rm == "PERCENT_OF_CHARGE":
            if pct is None or brc is not None:
                raise err_invalid_rate_parameters(
                    "PERCENT_OF_CHARGE proposed term requires percent_of_charge_bp and forbids base_rate_cents"
                )
        else:
            if brc is None or pct is not None:
                raise err_invalid_rate_parameters(
                    f"{rm} proposed term requires base_rate_cents and forbids percent_of_charge_bp"
                )
        exists = any(
            t["contract_id"] == contract_id and t["service_category"] == cat
            for t in _db.store.terms.values()
        )
        if not exists:
            raise err_invalid_rate_parameters(
                f"No ContractTerm exists for service_category {cat} on this contract"
            )
    return proposed_terms


def _validate_volume_mix(mix):
    if not isinstance(mix, list):
        raise err_invalid_request("projected_volume_mix must be a list")
    for entry in mix:
        if not isinstance(entry, dict):
            raise err_invalid_request("projected_volume_mix entries must be objects")
        extra = set(entry.keys()) - {"service_category", "annual_units"}
        if extra:
            raise err_invalid_request(f"Unknown projected_volume_mix fields: {sorted(extra)}")
        if entry.get("service_category") not in SERVICE_CATEGORIES:
            raise err_invalid_request("projected_volume_mix.service_category invalid")
        au = entry.get("annual_units")
        if isinstance(au, bool) or not isinstance(au, int) or au < 0:
            raise err_invalid_request("projected_volume_mix.annual_units must be a non-negative integer")
    return mix


@bp.post("/api/contract-proposals")
def create_proposal():
    require_roles(["ContractAnalyst"])
    data = body()
    reject_unknown(data, {"contract_id", "proposed_terms", "projected_volume_mix", "expected_contract_version"})
    contract_id = as_str(data, "contract_id")
    expected_contract_version = as_int(data, "expected_contract_version", required=True)

    contract = _db.store.contracts.get(contract_id)
    if contract is None:
        raise err_not_found("Contract not found")

    # OCC (rung 5)
    if expected_contract_version != contract["version"]:
        raise err_stale_contract_version()

    # Rung 10 consistency checks
    proposed_terms = _validate_proposed_terms(contract_id, data.get("proposed_terms"))
    projected_volume_mix = _validate_volume_mix(data.get("projected_volume_mix"))

    now = _db.now_iso()
    proposal = {
        "id": _db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": _db.store.next_seq(),
        "contract_id": contract_id,
        "round_number": 1,
        "proposed_terms": proposed_terms,
        "projected_volume_mix": projected_volume_mix,
        "modeled_contract_version": None,
        "baseline_same_store_cents": None,
        "delta_same_store_cents": None,
        "baseline_mix_shifted_cents": None,
        "delta_mix_shifted_cents": None,
        "status": "DRAFT",
    }
    _db.store.proposals[proposal["id"]] = proposal

    # Withdraw the contract's prior open proposals
    for other in _db.store.proposals.values():
        if (
            other["id"] != proposal["id"]
            and other["contract_id"] == contract_id
            and other["status"] in OPEN_STATUSES
        ):
            other["status"] = "WITHDRAWN"
            touch(other)

    # Bump contract version
    touch(contract)

    return success_object(serialize_proposal(proposal), status=201)


@bp.get("/api/contract-proposals/<pid>")
def get_proposal(pid):
    require_roles(ALL_ROLES)
    p = _db.store.proposals.get(pid)
    if p is None:
        raise err_not_found("ContractProposal not found")
    return success_object(serialize_proposal(p))


@bp.get("/api/contract-proposals")
def list_proposals():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    contract_id = request.args.get("contract_id")
    status = request.args.get("status")
    if status is not None and status not in PROPOSAL_STATUSES:
        raise err_invalid_request("status filter invalid")
    items = list(_db.store.proposals.values())
    if contract_id is not None:
        items = [p for p in items if p["contract_id"] == contract_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: p["seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_proposal(p) for p in page], limit, offset, total)


def _get_proposal_or_404(pid):
    p = _db.store.proposals.get(pid)
    if p is None:
        raise err_not_found("ContractProposal not found")
    return p


def _is_stale(p):
    contract = _db.store.contracts.get(p["contract_id"])
    if contract is None or p["status"] not in {"MODELED", "SUBMITTED", "COUNTERED"}:
        return False
    mv = p.get("modeled_contract_version")
    return mv is not None and mv != contract["version"]


@bp.post("/api/contract-proposals/<pid>/run_model")
def run_model(pid):
    require_roles(["ContractAnalyst"])
    p = _get_proposal_or_404(pid)
    if p["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT proposal may run the model")
    contract = _db.store.contracts.get(p["contract_id"])
    if contract is None:
        raise err_not_found("Contract not found")

    today = _db.today()
    window_start = today - timedelta(days=364)

    # Trailing units per category with a term on the contract
    terms = [t for t in _db.store.terms.values() if t["contract_id"] == contract["id"]]
    T = {}
    current_unit = {}
    for term in terms:
        cat = term["service_category"]
        U = 0
        for c in _db.store.claims.values():
            if c.get("priced_contract_id") != contract["id"]:
                continue
            if c["pricing_status"] not in {"PRICED", "REPRICED"}:
                continue
            if c["service_category"] != cat:
                continue
            d = parse_date(c["discharge_date"])
            if not (window_start <= d <= today):
                continue
            if term["rate_model"] == "PER_DIEM":
                U += covered_days(c)
            elif term["rate_model"] in {"CASE_RATE", "DRG_BASE"}:
                U += 1
            else:
                U += c["total_billed_charges_cents"]
        T[cat] = U

        # Current unit rate at anchor = today, through amendments + APPLIED escalators
        _, base_rate, pct = resolve_term_rates(contract["id"], cat, today)
        rm = term["rate_model"]
        if rm == "PER_DIEM":
            # Unit = patient-day: one day at the per-diem rate with escalation
            unit = apply_escalators_per_diem(contract["id"], cat, base_rate, today, today + timedelta(days=1))
        elif rm == "CASE_RATE":
            unit = apply_escalators_flat(contract["id"], cat, base_rate, today)
        elif rm == "DRG_BASE":
            base = rhu(Decimal(base_rate) * DRG_NORMALIZED_WEIGHT)
            unit = apply_escalators_flat(contract["id"], cat, base, today)
        else:  # PERCENT_OF_CHARGE: unit = charge cent -> rate per charge cent
            unit = Decimal(pct) / Decimal(10000)
        current_unit[cat] = unit

    # Proposed unit rates
    proposed_map = {pt["service_category"]: pt for pt in p["proposed_terms"]}
    proposed_unit = {}
    for term in terms:
        cat = term["service_category"]
        pt = proposed_map.get(cat)
        if pt is None:
            proposed_unit[cat] = current_unit[cat]
            continue
        rm = pt["rate_model"]
        if rm == "PER_DIEM":
            proposed_unit[cat] = pt["base_rate_cents"]
        elif rm == "CASE_RATE":
            proposed_unit[cat] = pt["base_rate_cents"]
        elif rm == "DRG_BASE":
            proposed_unit[cat] = rhu(Decimal(pt["base_rate_cents"]) * DRG_NORMALIZED_WEIGHT)
        else:
            proposed_unit[cat] = Decimal(pt["percent_of_charge_bp"]) / Decimal(10000)

    mix_map = {m["service_category"]: m["annual_units"] for m in p["projected_volume_mix"]}

    # Per-category products rounded half up before summing
    def product(units, unit):
        return rhu(Decimal(units) * Decimal(unit)) if isinstance(unit, Decimal) else rhu(Decimal(units) * Decimal(unit))

    baseline_same = 0
    modeled_same = 0
    baseline_mix = 0
    modeled_mix = 0
    for term in terms:
        cat = term["service_category"]
        t_u = T[cat]
        m_u = mix_map.get(cat, t_u)
        cu = current_unit[cat]
        pu = proposed_unit[cat]
        baseline_same += rhu(Decimal(t_u) * Decimal(cu))
        modeled_same += rhu(Decimal(t_u) * Decimal(pu))
        baseline_mix += rhu(Decimal(m_u) * Decimal(cu))
        modeled_mix += rhu(Decimal(m_u) * Decimal(pu))

    p["baseline_same_store_cents"] = baseline_same
    p["delta_same_store_cents"] = modeled_same - baseline_same
    p["baseline_mix_shifted_cents"] = baseline_mix
    p["delta_mix_shifted_cents"] = modeled_mix - baseline_mix
    p["modeled_contract_version"] = contract["version"]
    p["status"] = "MODELED"
    touch(p)
    return success_object(serialize_proposal(p))


@bp.post("/api/contract-proposals/<pid>/submit")
def submit_proposal(pid):
    require_roles(["ContractManager"])
    p = _get_proposal_or_404(pid)
    # State (rung 6)
    if p["status"] not in {"MODELED", "COUNTERED"}:
        raise err_invalid_state("Only a MODELED or COUNTERED proposal may be submitted")
    contract = _db.store.contracts.get(p["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        raise err_contract_not_active()
    if _is_stale(p):
        raise err_proposal_stale()
    if p["status"] == "COUNTERED":
        p["round_number"] = p.get("round_number", 1) + 1
    p["status"] = "SUBMITTED"
    touch(p)
    return success_object(serialize_proposal(p))


@bp.post("/api/contract-proposals/<pid>/record_counter")
def record_counter(pid):
    require_roles(["ContractManager"])
    p = _get_proposal_or_404(pid)
    if p["status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED proposal may record a counter-offer")
    p["status"] = "COUNTERED"
    touch(p)
    return success_object(serialize_proposal(p))


@bp.post("/api/contract-proposals/<pid>/accept")
def accept_proposal(pid):
    require_roles(["FinanceDirector"])
    p = _get_proposal_or_404(pid)
    data = body()
    reject_unknown(data, {"successor_contract_code", "successor_effective_date", "successor_expiration_date"})
    succ_code = as_str(data, "successor_contract_code")
    succ_eff = as_date(data, "successor_effective_date")
    succ_exp = as_date(data, "successor_expiration_date")
    if parse_date(succ_eff) > parse_date(succ_exp):
        raise err_invalid_request("successor_effective_date must be <= successor_expiration_date")

    # State (rung 6)
    if p["status"] not in {"SUBMITTED", "COUNTERED"}:
        raise err_invalid_state("Only a SUBMITTED or COUNTERED proposal may be accepted")
    if _is_stale(p):
        raise err_proposal_stale()

    contract = _db.store.contracts.get(p["contract_id"])
    # Successor creation goes through the same window-overlap and code-uniqueness rules
    _check_window_overlap(contract["payer_id"], succ_eff, succ_exp, contract["id"], exclude_id=None)
    for c in _db.store.contracts.values():
        if c["payer_id"] == contract["payer_id"] and c["contract_code"] == succ_code:
            raise err_duplicate_contract_code()

    now = _db.now_iso()
    successor = {
        "id": _db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": _db.store.next_seq(),
        "payer_id": contract["payer_id"],
        "contract_code": succ_code,
        "effective_date": succ_eff,
        "expiration_date": succ_exp,
        "prior_contract_id": contract["id"],
        "payment_terms_days": contract["payment_terms_days"],
        "underpayment_threshold_cents": contract["underpayment_threshold_cents"],
        "underpayment_threshold_bp": contract["underpayment_threshold_bp"],
        "volume_tiers": [dict(t) for t in (contract.get("volume_tiers") or [])],
        "status": "DRAFT",
    }
    _db.store.contracts[successor["id"]] = successor
    # One ContractTerm per proposed_terms entry
    for pt in p["proposed_terms"]:
        now2 = _db.now_iso()
        term = {
            "id": _db.new_id(),
            "created_at": now2,
            "updated_at": now2,
            "version": 1,
            "seq": _db.store.next_seq(),
            "contract_id": successor["id"],
            "service_category": pt["service_category"],
            "rate_model": pt["rate_model"],
            "base_rate_cents": pt.get("base_rate_cents"),
            "percent_of_charge_bp": pt.get("percent_of_charge_bp"),
        }
        _db.store.terms[term["id"]] = term

    p["status"] = "ACCEPTED"
    touch(p)
    return success_object(serialize_proposal(p))


@bp.post("/api/contract-proposals/<pid>/reject")
def reject_proposal(pid):
    require_roles(["ContractManager"])
    p = _get_proposal_or_404(pid)
    if p["status"] not in {"SUBMITTED", "COUNTERED"}:
        raise err_invalid_state("Only a SUBMITTED or COUNTERED proposal may be rejected")
    p["status"] = "REJECTED"
    touch(p)
    return success_object(serialize_proposal(p))


@bp.post("/api/contract-proposals/<pid>/withdraw")
def withdraw_proposal(pid):
    require_roles(["ContractManager", "ContractAnalyst"])
    p = _get_proposal_or_404(pid)
    if p["status"] not in OPEN_STATUSES:
        raise err_invalid_state("Only an open proposal may be withdrawn")
    p["status"] = "WITHDRAWN"
    touch(p)
    return success_object(serialize_proposal(p))
