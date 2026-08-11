"""The organization-wide surety bond."""

from flask import Blueprint

from core import serialize
from core.aggregates import in_force_bond, recompute_bond
from core.audit import set_subject
from core.envelope import object_response
from core.errors import fail
from core.pipeline import audited, authorize, resolve
from core.store import bump, new_row
from routes.authorizations import _check_date_span

bp = Blueprint("bonds", __name__)


@bp.post("/dmm/surety-bonds")
@audited("SuretyBond")
def register_bond():
    ctx = authorize("PlatformAdmin")                           # rungs 1-2
    ctx.check_shape([                                          # rung 4
        ("carrier_name", str, True),
        ("bond_number", str, True),
        ("coverage_cents", int, True),
        ("effective_date", str, True),
        ("expiry_date", str, True),
    ])

    coverage = ctx.body["coverage_cents"]
    if coverage <= 0:                                          # rung 15
        fail("ERR_VALIDATION", "coverage_cents must be greater than zero.")

    _check_date_span(ctx.body["effective_date"], ctx.body["expiry_date"])   # rung 17

    previous = in_force_bond()
    if previous is not None:
        previous["status"] = "SUPERSEDED"
        bump(previous)

    row = new_row("surety_bonds", {
        "carrier_name": ctx.body["carrier_name"],
        "bond_number": ctx.body["bond_number"],
        "coverage_cents": coverage,
        "effective_date": ctx.body["effective_date"],
        "expiry_date": ctx.body["expiry_date"],
        "status": "IN_FORCE",
        "exposure_committed_cents": 0,
        "exposure_settled_inclusive_cents": 0,
        "headroom_committed_cents": coverage,
    })
    recompute_bond()
    set_subject(row["id"])
    return object_response(serialize.surety_bond(row), 201)


@bp.get("/dmm/surety-bonds/<sid>")
def read_bond(sid):
    authorize("FiduciaryManager", "ComplianceOfficer", "PlatformAdmin")
    return object_response(serialize.surety_bond(resolve("surety_bonds", sid)), 200)
