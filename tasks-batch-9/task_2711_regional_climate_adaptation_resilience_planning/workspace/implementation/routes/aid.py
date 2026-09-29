"""PRD 3.9 -- mutual aid pacts, half-open commitment windows and the aid ledger."""

from flask import Blueprint

import calc
import cascades
import envelope
import lookup
import serialize
import store
import validate
from auth import ROLE_JURISDICTION_DELEGATE, guard, require_owned_jurisdiction
from core import clock
from errors import fail

bp = Blueprint("aid", __name__)

RESOURCE_CLASSES = ("CREWS", "PUMPS", "GENERATORS", "COOLING_UNITS")


@bp.post("/resilience/mutual-aid-pacts")
@guard(ROLE_JURISDICTION_DELEGATE)
def create_pact():
    body = validate.json_body()
    host = lookup.need_ref("jurisdiction", body, "host_jurisdiction_id")
    if host is None:
        validate.bad("host_jurisdiction_id", "is required.")
    require_owned_jurisdiction(host["id"], roles=(ROLE_JURISDICTION_DELEGATE,))

    resource_class = validate.enum_field(
        body, "resource_class", RESOURCE_CLASSES, required=True
    )
    pledged = validate.int_field(body, "pledged_units", required=True, minimum=1)
    window_start = validate.datetime_field(body, "window_start", required=True)
    window_end = validate.datetime_field(body, "window_end", required=True)
    max_concurrent = validate.int_field(
        body, "max_concurrent_commitments", default=3, minimum=1, maximum=20
    )
    validate.require_window(window_start, window_end)

    if host["status"] != "ACTIVE":
        fail("ERR_JURISDICTION_NOT_ACTIVE", "The pledging jurisdiction is not ACTIVE.")

    record = store.insert(store.pacts, {
        "host_jurisdiction_id": host["id"],
        "resource_class": resource_class,
        "pledged_units": pledged,
        "reserved_units": 0,
        "free_units": pledged,
        "window_start": window_start,
        "window_end": window_end,
        "max_concurrent_commitments": max_concurrent,
        "status": "OPEN",
    })
    return envelope.created(serialize.pact(record))


@bp.get("/resilience/mutual-aid-pacts")
@guard()
def list_pacts():
    rows = store.ordered(store.pacts)
    status = envelope.str_filter("status")
    if status is not None:
        rows = [row for row in rows if serialize.pact_status(row) == status]
    rows = envelope.match(
        rows,
        host_jurisdiction_id=envelope.str_filter("host_jurisdiction_id"),
        resource_class=envelope.str_filter("resource_class"),
    )
    return envelope.listing(rows, serialize.pact)


@bp.get("/resilience/mutual-aid-pacts/<pact_id>")
@guard()
def get_pact(pact_id):
    row = lookup.need("pact", pact_id)
    return envelope.ok(serialize.pact(row))


@bp.post("/resilience/mutual-aid-pacts/<pact_id>/commitments")
@guard(ROLE_JURISDICTION_DELEGATE)
def create_commitment(pact_id):
    pact = lookup.need("pact", pact_id)
    body = validate.json_body()
    requester = lookup.need_ref("jurisdiction", body, "requesting_jurisdiction_id")
    if requester is None:
        validate.bad("requesting_jurisdiction_id", "is required.")
    asset = lookup.need_ref("asset", body, "asset_id")
    if asset is None:
        validate.bad("asset_id", "is required.")
    require_owned_jurisdiction(requester["id"], roles=(ROLE_JURISDICTION_DELEGATE,))

    units = validate.int_field(body, "committed_units", required=True, minimum=1)
    window_start = validate.datetime_field(body, "window_start", required=True)
    window_end = validate.datetime_field(body, "window_end", required=True)
    expected_version = validate.int_field(
        body, "expected_mutual_aid_pact_version", required=True, minimum=0
    )

    # the nine guards, in exactly this order
    validate.require_window(window_start, window_end)
    if requester["status"] != "ACTIVE":
        fail("ERR_JURISDICTION_NOT_ACTIVE", "The requesting jurisdiction is not ACTIVE.")
    if cascades.derive_pact_status(pact) != "OPEN":
        fail("ERR_PACT_NOT_OPEN", "The pact is not OPEN.")
    if expected_version != pact["version"]:
        fail(
            "ERR_STALE_PACT_VERSION",
            "expected_mutual_aid_pact_version does not match the pact's current version.",
        )
    if not asset["is_shared"]:
        fail("ERR_ASSET_NOT_SHARED", "Only a shared lifeline asset may be supported.")
    if requester["id"] == pact["host_jurisdiction_id"]:
        fail("ERR_SELF_AID_NOT_ALLOWED", "A member may not request aid from its own pledge.")
    if window_start < pact["window_start"] or window_end > pact["window_end"]:
        fail(
            "ERR_AID_WINDOW_OUTSIDE_PACT",
            "The commitment window must lie inside the pact window.",
        )

    candidate = (window_start, window_end, units)
    candidate_set = cascades.active_commitment_windows(pact["id"], extra=candidate)
    if calc.peak_overlap_count(candidate_set) >= int(pact["max_concurrent_commitments"]):
        fail(
            "ERR_AID_CONCURRENCY_LIMIT",
            "Too many commitment windows overlap at a single instant.",
        )
    if calc.peak_unit_load(candidate_set) > int(pact["pledged_units"]):
        fail("ERR_AID_CAPACITY_EXCEEDED", "The peak unit load would exceed the pledge.")

    record = store.insert(store.commitments, {
        "pact_id": pact["id"],
        "requesting_jurisdiction_id": requester["id"],
        "asset_id": asset["id"],
        "committed_units": units,
        "window_start": window_start,
        "window_end": window_end,
        "status": "COMMITTED",
        "released_at": None,
        "fulfilled_at": None,
    })
    cascades.recompute_pact_ledger(pact)
    store.touch(pact)
    return envelope.created(serialize.commitment(record))


@bp.get("/resilience/mutual-aid-commitments")
@guard()
def list_commitments():
    rows = envelope.match(
        store.ordered(store.commitments),
        pact_id=envelope.str_filter("pact_id"),
        requesting_jurisdiction_id=envelope.str_filter("requesting_jurisdiction_id"),
        asset_id=envelope.str_filter("asset_id"),
        status=envelope.str_filter("status"),
    )
    return envelope.listing(rows, serialize.commitment)


@bp.get("/resilience/mutual-aid-commitments/<commitment_id>")
@guard()
def get_commitment(commitment_id):
    row = lookup.need("commitment", commitment_id)
    return envelope.ok(serialize.commitment(row))


@bp.post("/resilience/mutual-aid-commitments/<commitment_id>/release")
@guard(ROLE_JURISDICTION_DELEGATE)
def release_commitment(commitment_id):
    commitment = lookup.need("commitment", commitment_id)
    require_owned_jurisdiction(
        commitment["requesting_jurisdiction_id"], roles=(ROLE_JURISDICTION_DELEGATE,)
    )
    if commitment["status"] != "COMMITTED":
        fail("ERR_COMMITMENT_NOT_ACTIVE", "Only a COMMITTED draw may be released.")

    commitment["status"] = "RELEASED"
    commitment["released_at"] = clock.now()
    store.touch(commitment)
    pact = store.pacts.get(commitment["pact_id"])
    if pact is not None:
        cascades.recompute_pact_ledger(pact)
        store.touch(pact)
    return envelope.ok(serialize.commitment(commitment))


@bp.post("/resilience/mutual-aid-commitments/<commitment_id>/fulfill")
@guard(ROLE_JURISDICTION_DELEGATE)
def fulfill_commitment(commitment_id):
    commitment = lookup.need("commitment", commitment_id)
    require_owned_jurisdiction(
        commitment["requesting_jurisdiction_id"], roles=(ROLE_JURISDICTION_DELEGATE,)
    )
    if commitment["status"] != "COMMITTED":
        fail("ERR_COMMITMENT_NOT_ACTIVE", "Only a COMMITTED draw may be fulfilled.")

    # fulfilment leaves reserved_units and free_units unchanged, and only the
    # commitment's version increments
    commitment["status"] = "FULFILLED"
    commitment["fulfilled_at"] = clock.now()
    store.touch(commitment)
    return envelope.ok(serialize.commitment(commitment))
