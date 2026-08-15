"""Reconstitution endpoints (PRD §3.6; state machine Farm).

POST /fsa/farms/{id}/reconstitutions opens a DIVIDE or COMBINE. The
conservation check (|sum(product) - sum(source)| <= 0.01) runs at open
time; when it passes the farm moves ACTIVE -> RECONSTITUTION_PENDING ->
RECONSTITUTED and the product tracts are created. Finalize moves
RECONSTITUTED -> ACTIVE (version +1). Cancel rolls a pending
reconstitution back (products deleted, sources restored to ACTIVE).
"""

from decimal import Decimal

from flask import Blueprint

import db
from errors import (
    ApiError, ERR_BASE_ACRE_IMBALANCE, invalid_state, invalid_request,
    not_found, stale_farm_version,
)
from middleware import require_roles
from response import success_object
from services.helpers import (
    get_farm_or_404, get_tract_or_404, get_recon_or_404,
    recompute_farm_base_acres,
)
from validation import body, require_enum, require_string, optional_str_list

bp = Blueprint("reconstitutions", __name__)

TOLERANCE = Decimal("0.01")


@bp.post("/fsa/farms/<farm_id>/reconstitutions")
def open_reconstitution(farm_id):
    require_roles(["CountySpecialist"])
    farm = get_farm_or_404(farm_id)
    data = body()

    method = require_enum(data, "method", ("DIVIDE", "COMBINE"))
    source_tract_ids = data.get("source_tract_ids")
    if not isinstance(source_tract_ids, list) or not source_tract_ids \
            or not all(isinstance(x, str) for x in source_tract_ids):
        raise invalid_request("source_tract_ids must be a non-empty list of strings")
    product_specs = data.get("product_specs")
    if not isinstance(product_specs, list) or not product_specs:
        raise invalid_request("product_specs must be a non-empty list")
    expected_farm_version = data.get("expected_farm_version")
    if expected_farm_version is None or isinstance(expected_farm_version, bool) \
            or not isinstance(expected_farm_version, int):
        raise invalid_request("expected_farm_version is required and must be an integer")

    # Existence: every source tract must resolve and belong to this farm.
    source_tracts = []
    for tid in source_tract_ids:
        t = db.tracts.get(tid)
        if t is None or t["farm_id"] != farm_id:
            raise not_found(f"Tract {tid} not found on farm {farm_id}")
        source_tracts.append(t)

    # State: farm ACTIVE, no enrollment CERTIFIED/PAYMENT_COMPUTED/PAYMENT_ISSUED.
    if farm["farm_status"] != "ACTIVE":
        raise invalid_state("Farm is not ACTIVE")
    for e in db.enrollments.values():
        if e["farm_id"] == farm_id and e["enrollment_status"] in (
                "CERTIFIED", "PAYMENT_COMPUTED", "PAYMENT_ISSUED"):
            raise invalid_state(
                "An enrollment on the farm is CERTIFIED, PAYMENT_COMPUTED, or PAYMENT_ISSUED")

    # OCC (priority 5 — after state, before business rules).
    if expected_farm_version != farm["version"]:
        raise stale_farm_version()

    # Validate product specs shape.
    parsed_specs = []
    for spec in product_specs:
        if not isinstance(spec, dict):
            raise invalid_request("each product_specs entry must be an object")
        tract_number = spec.get("tract_number")
        if not isinstance(tract_number, str) or not tract_number.strip():
            raise invalid_request("each product spec requires tract_number")
        try:
            spec_base = Decimal(str(spec.get("base_acres")))
        except Exception:
            raise invalid_request("each product spec requires numeric base_acres")
        try:
            spec_cropland = Decimal(str(spec.get("cropland_acres")))
        except Exception:
            raise invalid_request("each product spec requires numeric cropland_acres")
        parsed_specs.append((tract_number, spec_base, spec_cropland))

    if method == "DIVIDE":
        if len(source_tracts) != 1:
            raise invalid_request("DIVIDE requires exactly one source tract")
        if len(parsed_specs) < 2:
            raise invalid_request("DIVIDE requires two or more product tracts")
    else:  # COMBINE
        if len(parsed_specs) != 1:
            raise invalid_request("COMBINE produces a single product tract")

    # Base-acre conservation check (priority 15).
    source_sum = sum(Decimal(str(t["base_acres"])) for t in source_tracts)
    product_sum = sum(spec[1] for spec in parsed_specs)
    if abs(product_sum - source_sum) > TOLERANCE:
        raise ApiError(
            ERR_BASE_ACRE_IMBALANCE,
            "Reconstitution products' base acres do not conserve source sum within 0.01",
            422,
        )

    # Apply: source tracts -> DIVIDED/COMBINED; products created ACTIVE.
    new_status = "DIVIDED" if method == "DIVIDE" else "COMBINED"
    for t in source_tracts:
        t["tract_status"] = new_status
        db.touch(t)

    product_tract_ids = []
    for tract_number, spec_base, spec_cropland in parsed_specs:
        tract = db.common_fields()
        tract.update({
            "farm_id": farm_id,
            "tract_number": tract_number,
            "base_acres": float(spec_base),
            "cropland_acres": float(spec_cropland),
            "tract_status": "ACTIVE",
            "reconstituted_from_tract_id": source_tracts[0]["id"]
                if method == "DIVIDE" else None,
        })
        if method == "COMBINE":
            # A combined product traces to its first source for auditability.
            tract["reconstituted_from_tract_id"] = source_tracts[0]["id"]
        db.tracts[tract["id"]] = tract
        product_tract_ids.append(tract["id"])

    recon = db.common_fields()
    recon.update({
        "farm_id": farm_id,
        "method": method,
        "source_tract_ids": list(source_tract_ids),
        "product_tract_ids": product_tract_ids,
        "recon_status": "RECONSTITUTED",  # conservation check passed at open
    })
    db.reconstitutions[recon["id"]] = recon

    # Farm ACTIVE -> RECONSTITUTION_PENDING -> (check passed) RECONSTITUTED;
    # version increments by 1 on open (PRD §3.6).
    farm["farm_status"] = "RECONSTITUTED"
    farm["version"] += 1
    farm["updated_at"] = db.wall_timestamp()
    recompute_farm_base_acres(farm)

    out = dict(farm)
    out["reconstitution_id"] = recon["id"]
    return success_object(out, 201)


@bp.post("/fsa/farms/<farm_id>/finalize-reconstitution")
def finalize_reconstitution(farm_id):
    require_roles(["CountySpecialist"])
    farm = get_farm_or_404(farm_id)
    if farm["farm_status"] != "RECONSTITUTED":
        raise invalid_state("Farm.status is not RECONSTITUTED")
    farm["farm_status"] = "ACTIVE"
    farm["version"] += 1
    farm["updated_at"] = db.wall_timestamp()
    return success_object(farm)


@bp.post("/fsa/farms/<farm_id>/reconstitutions/<recon_id>/cancel")
def cancel_reconstitution(farm_id, recon_id):
    require_roles(["CountySpecialist"])
    farm = get_farm_or_404(farm_id)
    recon = db.reconstitutions.get(recon_id)
    if recon is None or recon["farm_id"] != farm_id:
        raise not_found(f"Reconstitution {recon_id} not found on farm {farm_id}")
    # Cancel applies to a reconstitution that has been opened and not yet
    # cancelled/finalized: the farm is sitting in RECONSTITUTED awaiting
    # finalize. (PRD §3.6 — "one not yet RECONSTITUTED" refers to the
    # reconstitution transaction; in this implementation the conservation
    # check runs at open, so the cancellable window is open..finalize.)
    if recon["recon_status"] != "RECONSTITUTED":
        raise invalid_state("Reconstitution is not pending")
    if farm["farm_status"] != "RECONSTITUTED":
        raise invalid_state("Farm is not in RECONSTITUTED state")

    # Roll back: delete product tracts, restore sources to ACTIVE.
    for pid in recon["product_tract_ids"]:
        db.tracts.pop(pid, None)
    for sid in recon["source_tract_ids"]:
        src = db.tracts.get(sid)
        if src is not None:
            src["tract_status"] = "ACTIVE"
            db.touch(src)
    recon["recon_status"] = "CANCELLED"
    recon["cancelled"] = True
    db.touch(recon)

    farm["farm_status"] = "ACTIVE"
    db.touch(farm)
    recompute_farm_base_acres(farm)
    return success_object(farm)
