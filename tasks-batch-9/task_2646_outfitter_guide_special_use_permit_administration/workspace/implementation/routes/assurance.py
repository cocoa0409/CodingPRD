"""Insurance certificates and performance bonds (PRD 3.6)."""
from flask import Blueprint

import calc
import envelope
import security
import serialize
import shapes
import store
from errors import ApiError
from routes.common import match, qstr
from security import ANY_ROLE, REPRESENTATIVE

bp = Blueprint("assurance", __name__)

COVERAGE_TYPES = ("GENERAL_LIABILITY", "AUTO_LIABILITY", "WATERCRAFT_LIABILITY")
FILEABLE = ("ISSUED", "ACTIVE")


def require_fileable(permit):
    if permit["administrative_status"] not in FILEABLE:
        raise ApiError(
            "ERR_PERMIT_NOT_OPERATIONAL", "evidence may be filed only against ISSUED or ACTIVE"
        )


@bp.post("/osup/permits/<permit_id>/insurance-certificates")
def file_certificate(permit_id):
    caller = security.authenticate((REPRESENTATIVE,))
    permit = store.get_or_404("permits", permit_id, "ERR_PERMIT_NOT_FOUND")
    security.require_owner(caller, permit["outfitter_id"])
    data = shapes.body()
    coverage_type = shapes.req_str(data, "coverage_type", allowed=COVERAGE_TYPES)
    carrier = shapes.req_str(data, "carrier_name")
    amount = shapes.req_int(data, "coverage_amount_cents", minimum=0)
    effective = shapes.req_date(data, "effective_date")
    expiration = shapes.req_date(data, "expiration_date")
    endorsed = shapes.opt_bool(data, "additional_insured_endorsed", default=False)
    eff_date = store.as_date(effective)
    exp_date = store.as_date(expiration)
    if exp_date <= eff_date:
        shapes.bad("expiration_date", "must be strictly after effective_date")
    require_fileable(permit)

    cert = store.insert(
        "insurance_certificates",
        {
            "permit_id": permit["id"],
            "coverage_type": coverage_type,
            "carrier_name": carrier,
            "coverage_amount_cents": amount,
            "effective_date": effective,
            "expiration_date": expiration,
            "additional_insured_endorsed": endorsed,
            "status": "ACTIVE",
        },
    )
    # narrow supersession: same type AND the new interval fully contains the old one
    for other in store.all_of("insurance_certificates"):
        if (
            other["id"] == cert["id"]
            or other["permit_id"] != permit["id"]
            or other["status"] != "ACTIVE"
            or other["coverage_type"] != coverage_type
        ):
            continue
        if (
            eff_date <= store.as_date(other["effective_date"])
            and exp_date >= store.as_date(other["expiration_date"])
        ):
            other["status"] = "SUPERSEDED"
            store.touch(other)
    calc.recompute_permit_signals(permit)
    store.touch(permit)
    calc.derive_compliance(permit)
    return envelope.ok(serialize.insurance_certificate(cert), 201)


@bp.get("/osup/permits/<permit_id>/insurance-certificates")
def list_certificates(permit_id):
    security.authenticate(ANY_ROLE, mutating=False)
    permit = store.get_or_404("permits", permit_id, "ERR_PERMIT_NOT_FOUND")
    filters = {
        "coverage_type": qstr("coverage_type"),
        "status": qstr("status"),
    }
    rows = [
        c
        for c in store.all_of("insurance_certificates")
        if c["permit_id"] == permit["id"] and match(c, **filters)
    ]
    rows = store.sort_by(rows, [lambda c: store.as_date(c["effective_date"])])
    return envelope.paginate(rows, serialize.insurance_certificate)


@bp.post("/osup/permits/<permit_id>/bonds")
def file_bond(permit_id):
    caller = security.authenticate((REPRESENTATIVE,))
    permit = store.get_or_404("permits", permit_id, "ERR_PERMIT_NOT_FOUND")
    security.require_owner(caller, permit["outfitter_id"])
    data = shapes.body()
    amount = shapes.req_int(data, "bond_amount_cents", minimum=0)
    surety = shapes.req_str(data, "surety_name")
    effective = shapes.req_date(data, "effective_date")
    expiration = shapes.req_date(data, "expiration_date")
    if store.as_date(expiration) <= store.as_date(effective):
        shapes.bad("expiration_date", "must be strictly after effective_date")
    require_fileable(permit)

    bond_row = store.insert(
        "bonds",
        {
            "permit_id": permit["id"],
            "bond_amount_cents": amount,
            "surety_name": surety,
            "effective_date": effective,
            "expiration_date": expiration,
            "required_amount_cents": calc.required_assurance(permit),
            "status": "ACTIVE",
        },
    )
    # bond supersession is unconditional: exactly one bond stands in force
    for other in store.all_of("bonds"):
        if (
            other["id"] != bond_row["id"]
            and other["permit_id"] == permit["id"]
            and other["status"] == "ACTIVE"
        ):
            other["status"] = "SUPERSEDED"
            store.touch(other)
    calc.recompute_permit_signals(permit)
    store.touch(permit)
    calc.derive_compliance(permit)
    return envelope.ok(serialize.bond(bond_row), 201)


@bp.get("/osup/permits/<permit_id>/bonds")
def list_bonds(permit_id):
    security.authenticate(ANY_ROLE, mutating=False)
    permit = store.get_or_404("permits", permit_id, "ERR_PERMIT_NOT_FOUND")
    rows = [
        b
        for b in store.all_of("bonds")
        if b["permit_id"] == permit["id"] and match(b, status=qstr("status"))
    ]
    return envelope.paginate(store.sort_created(rows), serialize.bond)
