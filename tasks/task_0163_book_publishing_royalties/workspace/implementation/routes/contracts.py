"""Contracts, royalty tiers, and contract lifecycle (PRD §3.1)."""
from flask import Blueprint, request

import db
import errors
from middleware import get_principal, require_publisher, serialize
from response import object_response, array_response
from services import validate
from services.access import can_read_contract
from services.listing import paginate

bp = Blueprint("contracts", __name__)


def _public_contract(rec):
    return serialize(rec)


# ---- Create / read / list ----

@bp.route("/contracts", methods=["POST"])
def create_contract():
    role, _ = get_principal()
    require_publisher(role)
    body = validate.get_body()
    author_id = validate.req_string(body, "author_id")
    agent_id = validate.opt_string(body, "agent_id", None)
    advance_cents = validate.req_int(body, "advance_cents")
    agent_commission_pct = validate.opt_number(body, "agent_commission_pct", 0)
    reserve_pct = validate.opt_number(body, "reserve_pct", 0.25)
    reserve_hold_periods = validate.opt_int(body, "reserve_hold_periods", 2)

    # Range checks (priority: range after well-formedness).
    validate.range_ge(advance_cents, "advance_cents", 0)
    validate.range_pct_closed(agent_commission_pct, "agent_commission_pct")
    validate.range_pct_closed(reserve_pct, "reserve_pct")
    validate.range_ge(reserve_hold_periods, "reserve_hold_periods", 1)

    # Existence of FKs (priority 3 — but checked after well-formedness here;
    # FK existence is enforced before domain rules).
    if db.authors.get(author_id) is None:
        raise errors.not_found("author_id does not resolve.")
    if agent_id is not None and db.agents.get(agent_id) is None:
        raise errors.not_found("agent_id does not resolve.")

    # commission-without-agent (priority 6).
    if agent_id is None and agent_commission_pct != 0:
        raise errors.commission_without_agent()

    rec = db.make_common({
        "author_id": author_id,
        "agent_id": agent_id,
        "advance_cents": advance_cents,
        "unrecouped_advance_cents": advance_cents,
        "agent_commission_pct": agent_commission_pct,
        "reserve_pct": reserve_pct,
        "reserve_hold_periods": reserve_hold_periods,
        "status": "DRAFT",
        "lifetime_net_units": 0,
    })
    db.contracts[rec["id"]] = rec
    return object_response(_public_contract(rec), 201)


def _load_contract_for_read(cid):
    role, user_id = get_principal()
    contract = db.contracts.get(cid)
    if contract is None:
        raise errors.not_found("Contract not found.")
    if not can_read_contract(role, user_id, contract):
        raise errors.unauthorized()
    return contract


@bp.route("/contracts/<cid>", methods=["GET"])
def get_contract(cid):
    contract = _load_contract_for_read(cid)
    return object_response(_public_contract(contract))


@bp.route("/contracts", methods=["GET"])
def list_contracts():
    role, user_id = get_principal()
    limit, offset = validate.pagination()
    author_filter = request.args.get("author_id")
    agent_filter = request.args.get("agent_id")
    records = []
    for c in db.contracts.values():
        if not can_read_contract(role, user_id, c):
            continue
        if author_filter is not None and c.get("author_id") != author_filter:
            continue
        if agent_filter is not None and c.get("agent_id") != agent_filter:
            continue
        records.append(c)
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


# ---- Lifecycle ----

def _tiers_valid_cover(tiers):
    """True iff tiers form a contiguous cover from lower_unit=1 with exactly
    one open-ended (upper_unit is None) top tier and no gaps/overlaps."""
    if not tiers:
        return False
    open_tiers = [t for t in tiers if t["upper_unit"] is None]
    if len(open_tiers) != 1:
        return False
    ordered = sorted(tiers, key=lambda t: t["lower_unit"])
    if ordered[0]["lower_unit"] != 1:
        return False
    # The open-ended tier must be the last in ascending order.
    if ordered[-1]["upper_unit"] is not None:
        return False
    expected_lower = 1
    for i, t in enumerate(ordered):
        if t["lower_unit"] != expected_lower:
            return False
        if i == len(ordered) - 1:
            # last tier must be the open one
            if t["upper_unit"] is not None:
                return False
            break
        if t["upper_unit"] is None:
            # an open tier appears before the end -> invalid
            return False
        if t["upper_unit"] < t["lower_unit"]:
            return False
        expected_lower = t["upper_unit"] + 1
    return True


@bp.route("/contracts/<cid>/activate", methods=["POST"])
def activate_contract(cid):
    role, _ = get_principal()
    require_publisher(role)
    contract = db.contracts.get(cid)
    if contract is None:
        raise errors.not_found("Contract not found.")
    # State: must be DRAFT.
    if contract["status"] != "DRAFT":
        raise errors.invalid_state("Only a DRAFT contract may be activated.")

    # commission-without-agent re-check (priority 6).
    if contract.get("agent_id") is None and contract["agent_commission_pct"] != 0:
        raise errors.commission_without_agent()

    tiers = [t for t in db.royalty_tiers.values() if t["contract_id"] == cid]
    titles = [t for t in db.titles.values() if t["contract_id"] == cid]
    has_title_with_format = False
    for t in titles:
        if any(f["title_id"] == t["id"] for f in db.formats.values()):
            has_title_with_format = True
            break

    # Readiness presence check (ERR_CONTRACT_NOT_READY).
    if not tiers or not has_title_with_format:
        raise errors.contract_not_ready()

    # Tier coverage shape validity (priority 7, ERR_TIER_COVERAGE_INVALID).
    if not _tiers_valid_cover(tiers):
        raise errors.tier_coverage_invalid()

    contract["status"] = "ACTIVE"
    contract["unrecouped_advance_cents"] = contract["advance_cents"]
    db.touch(contract)
    return object_response(_public_contract(contract))


@bp.route("/contracts/<cid>/terminate", methods=["POST"])
def terminate_contract(cid):
    role, _ = get_principal()
    require_publisher(role)
    contract = db.contracts.get(cid)
    if contract is None:
        raise errors.not_found("Contract not found.")
    if contract["status"] != "ACTIVE":
        raise errors.invalid_state("Only an ACTIVE contract may be terminated.")

    # Open-liabilities check (priority 14).
    for p in db.sales_periods.values():
        if p["contract_id"] == cid and p["status"] == "CLOSED":
            raise errors.open_liabilities("A sales period is still CLOSED.")
    for s in db.author_statements.values():
        if s["contract_id"] == cid and s["status"] in ("DRAFT", "FINALIZED"):
            raise errors.open_liabilities("An author statement is unpaid.")
    for rv in db.returns_reserves.values():
        if rv["contract_id"] == cid and rv["status"] == "HELD":
            raise errors.open_liabilities("A returns reserve is still HELD.")

    contract["status"] = "TERMINATED"
    db.touch(contract)
    return object_response(_public_contract(contract))


# ---- Royalty tiers ----

@bp.route("/contracts/<cid>/royalty-tiers", methods=["POST"])
def create_tier(cid):
    role, _ = get_principal()
    require_publisher(role)
    contract = db.contracts.get(cid)
    if contract is None:
        raise errors.not_found("Contract not found.")
    # Tiers are added to a still-DRAFT contract.
    if contract["status"] != "DRAFT":
        raise errors.invalid_state("Royalty tiers may only be added to a DRAFT contract.")
    body = validate.get_body()
    lower_unit = validate.req_int(body, "lower_unit")
    upper_unit = validate.opt_int(body, "upper_unit", None)
    rate = validate.req_number(body, "rate")

    validate.range_ge(lower_unit, "lower_unit", 1)
    if upper_unit is not None and not (upper_unit >= lower_unit):
        raise errors.validation_range("upper_unit must be >= lower_unit.")
    validate.range_pct_open_low(rate, "rate")

    rec = db.make_light({
        "contract_id": cid,
        "lower_unit": lower_unit,
        "upper_unit": upper_unit,
        "rate": rate,
    })
    db.royalty_tiers[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/contracts/<cid>/royalty-tiers", methods=["GET"])
def list_tiers(cid):
    contract = _load_contract_for_read(cid)
    records = [t for t in db.royalty_tiers.values() if t["contract_id"] == contract["id"]]
    limit, offset = validate.pagination()
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)
