"""Retainer routes: CRUD + lifecycle + billing-cycle rollover (OCC)."""
from flask import Blueprint, request

import calc
import services
from auth import require_auth, require_role
from db import store, base_record, touch
from errors import err
from helpers import (
    get_body, require_str, require_int, require_enum, opt_number,
    find, assert_owns_client, paginate, parse_pagination,
)
from response import ok_object, ok_list

bp = Blueprint("retainers", __name__)

TIERS = {"STARTER", "GROWTH", "DOMINATE"}


@bp.route("/retainers", methods=["POST"])
def create_retainer():
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    body = get_body()
    client_id = require_str(body, "client_id")
    client = find("client", client_id)
    tier = require_enum(body, "tier", TIERS)
    monthly_credits = require_int(body, "monthly_credits", minimum=0)
    wholesale_price_cents = require_int(body, "wholesale_price_cents", minimum=0)
    rollover_cap_pct = opt_number(body, "rollover_cap_pct", default=0.25, minimum=0.0, maximum=1.0)

    rec = base_record(versioned=True)
    rec.update({
        "client_id": client_id,
        "tier": tier,
        "monthly_credits": monthly_credits,
        "wholesale_price_cents": wholesale_price_cents,
        "rollover_cap_pct": rollover_cap_pct,
        "credits_granted": 0,
        "credits_committed": 0,
        "credits_consumed": 0,
        "credits_available": 0,
        "billing_price_cents": 0,
        "cycle_index": 0,
        "status": "DRAFT",
    })
    store.retainers[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.route("/retainers/<rid>", methods=["GET"])
def get_retainer(rid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Reseller", "Client"])
    r = find("retainer", rid)
    client = find("client", r["client_id"])
    assert_owns_client(principal, client)
    services.recompute_retainer_balance(r)
    return ok_object(r, 200)


@bp.route("/retainers", methods=["GET"])
def list_retainers():
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Reseller", "Client"])
    parse_pagination()
    client_filter = request.args.get("client_id")
    status_filter = request.args.get("status")
    records = list(store.retainers.values())
    if principal.role == "Client":
        records = [r for r in records if r["client_id"] == principal.user_id]
    elif principal.role == "Reseller":
        records = [r for r in records
                   if (c := store.clients.get(r["client_id"])) is not None
                   and c.get("reseller_id") == principal.user_id]
    if client_filter is not None:
        records = [r for r in records if r["client_id"] == client_filter]
    if status_filter is not None:
        records = [r for r in records if r["status"] == status_filter]
    page, limit, offset, total = paginate(records)
    return ok_list(page, limit, offset, total)


@bp.route("/retainers/<rid>/activate", methods=["POST"])
def activate_retainer(rid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    r = find("retainer", rid)
    if r["status"] not in ("DRAFT", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Retainer must be DRAFT or SUSPENDED to activate")

    client = find("client", r["client_id"])

    if r["status"] == "DRAFT":
        # DRAFT -> ACTIVE requires client AUDITED or ACTIVE
        if client["status"] not in ("AUDITED", "ACTIVE"):
            raise err("ERR_CLIENT_NOT_AUDITED", "Client must be AUDITED or ACTIVE")
        r["status"] = "ACTIVE"
        r["credits_granted"] = r["monthly_credits"]
        reseller = services.reseller_for_client(client)
        r["billing_price_cents"] = calc.retainer_billing_price(r["wholesale_price_cents"], reseller)
        services.recompute_retainer_balance(r)
        touch(r)
        # bubble-up: AUDITED client -> ACTIVE on first ACTIVE retainer
        if client["status"] == "AUDITED":
            client["status"] = "ACTIVE"
            services.recompute_open_dispute_count(client)
            services.recompute_health_score(client)
            touch(client)
    else:  # SUSPENDED -> ACTIVE (reactivation)
        r["status"] = "ACTIVE"
        touch(r)
    return ok_object(r, 200)


@bp.route("/retainers/<rid>/suspend", methods=["POST"])
def suspend_retainer(rid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    r = find("retainer", rid)
    if r["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Retainer must be ACTIVE to suspend")
    r["status"] = "SUSPENDED"
    touch(r)
    return ok_object(r, 200)


@bp.route("/retainers/<rid>/close", methods=["POST"])
def close_retainer(rid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    r = find("retainer", rid)
    if r["status"] not in ("ACTIVE", "SUSPENDED", "DRAFT"):
        raise err("ERR_INVALID_STATE", "Retainer must be ACTIVE, SUSPENDED, or DRAFT to close")
    r["status"] = "CLOSED"
    services.cancel_non_terminal_deliverables_for_retainer(r)
    touch(r)
    return ok_object(r, 200)


@bp.route("/retainers/<rid>/rollover", methods=["POST"])
def rollover_retainer(rid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    r = find("retainer", rid)
    body = get_body()
    expected_version = require_int(body, "expected_retainer_version")

    if r["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Retainer must be ACTIVE to roll over")
    # OCC check (priority 7) after state check
    if expected_version != r["version"]:
        raise err("ERR_STALE_RETAINER_VERSION", "expected_retainer_version is stale")

    # ensure available reflects live ledger before measuring leftover
    services.recompute_retainer_balance(r)
    leftover = r["credits_available"]
    rolled = calc.capped_rollover(leftover, r["monthly_credits"], r["rollover_cap_pct"])

    r["cycle_index"] += 1
    r["credits_granted"] = r["monthly_credits"] + rolled
    r["credits_committed"] = 0
    r["credits_consumed"] = 0
    # recompute available against new cycle (committed/consumed reset to 0,
    # deliverables from prior cycle no longer count toward this cycle)
    services.recompute_retainer_balance(r)
    touch(r)

    # contract bubble-up: ACTIVE contract advances cycles_elapsed; may
    # auto-renew or auto-expire on term completion.
    contract = _active_contract_for_retainer(rid)
    if contract is not None and contract["status"] == "ACTIVE":
        contract["cycles_elapsed"] += 1
        if contract["cycles_elapsed"] >= contract["term_cycles"]:
            if contract["auto_renew"]:
                contract["status"] = "RENEWED"
                contract["cycles_elapsed"] = 0
                contract["early_termination_fee_cents"] = calc.early_termination_fee(
                    contract["term_cycles"], contract["cycles_elapsed"], r["billing_price_cents"]
                )
            else:
                contract["status"] = "EXPIRED"
                contract["early_termination_fee_cents"] = 0
        touch(contract)

    return ok_object(r, 200)


def _active_contract_for_retainer(retainer_id):
    candidates = [c for c in store.contracts.values()
                  if c["retainer_id"] == retainer_id and c["status"] == "ACTIVE"]
    if not candidates:
        return None
    return max(candidates, key=lambda c: c["_seq"])
