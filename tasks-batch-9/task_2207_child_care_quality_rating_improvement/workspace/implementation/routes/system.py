"""Logical clock, expiry run and standard domain configuration (PRD §2.8, §3.1)."""

from decimal import Decimal

from flask import Blueprint, request

import calculations as calc
import cascades
import response
import serializers
import store
import validation as v
from auth import require
from errors import fail
from validation import as_date, body, parse_instant

bp = Blueprint("system", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require("StateAdministrator")
    data = body()
    raw = v.req_field(data, "to_iso8601")
    store.DB.logical_clock = parse_instant(raw, "to_iso8601")
    return response.empty()


@bp.post("/qris/expiry-runs")
def expiry_run():
    require("StateAdministrator")
    body()
    clock_date = store.today()

    # 1. Awarded cycles whose effective date has arrived advance to ACTIVE.
    awarded = [c for c in store.DB.rating_cycles.values() if c["status"] == "AWARDED"]
    for cycle in store.sort_created(awarded):
        effective = as_date(cycle.get("effective_date"))
        if effective is not None and effective <= clock_date:
            cascades.promote_cycle_to_active(cycle)

    # 2. Active cycles whose expires_on is strictly earlier than the clock date expire.
    active = [c for c in store.DB.rating_cycles.values() if c["status"] == "ACTIVE"]
    for cycle in store.sort_created(active):
        expires = as_date(cycle.get("expires_on"))
        if expires is not None and expires < clock_date:
            cascades.expire_cycle(cycle)

    # 3. Open grants past their spend deadline (or whose funding cycle left ACTIVE) freeze.
    grants = [g for g in store.DB.improvement_grants.values() if g["status"] == "OPEN"]
    for grant in store.sort_created(grants):
        cycle = store.DB.rating_cycles.get(grant.get("rating_cycle_id"))
        cycle_inactive = cycle is None or cycle["status"] != "ACTIVE"
        deadline = as_date(grant.get("spend_deadline"))
        if cycle_inactive or (deadline is not None and clock_date > deadline):
            cascades.freeze_grant(grant)

    # 4. Every provider's credential compliance is recomputed.
    for provider in store.sort_created(list(store.DB.providers.values())):
        if calc.refresh_credential_compliance(provider):
            store.touch(provider)

    return response.empty()


@bp.post("/standard-domains")
def create_standard_domain():
    require("StateAdministrator")
    data = body()
    domain_code = v.req_enum(data, "domain_code", v.DOMAIN_CODES)
    block_level = v.req_int(data, "block_level", 1, 3)
    max_points = v.req_int(data, "max_points", 1, 100)
    block_min_points = v.req_int(data, "block_min_points", 1, max_points)
    weight = v.req_decimal(data, "weight", minimum=0, maximum=1, exclusive_min=True)
    observation_linked = data.get("observation_linked", False)
    if observation_linked is None:
        observation_linked = False
    if not isinstance(observation_linked, bool):
        fail("ERR_VALIDATION", "observation_linked must be a boolean")
    min_composite = v.opt_decimal(data, "min_composite_for_block",
                                  minimum=Decimal("1.00"), maximum=Decimal("7.00"),
                                  max_places=2)
    if not observation_linked:
        min_composite = None

    for existing in store.DB.standard_domains.values():
        if existing["domain_code"] == domain_code:
            fail("ERR_DUPLICATE_RESOURCE", "domain_code %s is already declared" % domain_code)

    rec = store.base_record(
        domain_code=domain_code,
        block_level=block_level,
        max_points=max_points,
        block_min_points=block_min_points,
        weight=weight,
        observation_linked=observation_linked,
        min_composite_for_block=min_composite,
    )
    store.DB.standard_domains[rec["id"]] = rec
    return response.created(serializers.dump("standard_domain", rec))


@bp.get("/standard-domains")
def list_standard_domains():
    require("StateAdministrator", "Provider", "FamilyViewer")
    records = store.sort_created(list(store.DB.standard_domains.values()))
    block_level = request.args.get("block_level")
    if block_level is not None and block_level != "":
        try:
            wanted = int(block_level)
        except ValueError:
            fail("ERR_VALIDATION", "block_level must be an integer")
        records = [r for r in records if r["block_level"] == wanted]
    observation_linked = request.args.get("observation_linked")
    if observation_linked is not None and observation_linked != "":
        flag = str(observation_linked).lower()
        if flag not in ("true", "false"):
            fail("ERR_VALIDATION", "observation_linked must be true or false")
        wanted_flag = flag == "true"
        records = [r for r in records if bool(r["observation_linked"]) == wanted_flag]
    return response.paginate(records, serializers.maker("standard_domain"))
