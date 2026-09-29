"""DrawRequest endpoints — three-rounding money waterfall and the fiscal ceiling."""

from flask import Blueprint

import auth
import calc
import serialize
import services
import validate
from envelope import created, ok, ok_list, paginate
from errors import ApiError
from store import base_row, db, now, sorted_rows, touch

bp = Blueprint("draws", __name__)

BASIS_MODES = ("WIP_DEPOSIT", "MILESTONE_SET")
STATUSES = ("DRAFT", "CERTIFIED", "FUNDED", "REJECTED")


@bp.post("/modular/draw-requests")
@auth.endpoint("LenderDrawAdministrator")
def create_draw():
    data = validate.body(optional=False)
    project_id = validate.field_id(data, "project_id")
    draw_index = validate.field_int(data, "draw_index", minimum=1)
    basis_mode = validate.field_enum(data, "basis_mode", BASIS_MODES)
    certifying_agency_id = validate.field_id(data, "certifying_agency_id")

    # rank 5 — project_id then certifying_agency_id
    project = services.get_project(project_id)
    agency = services.get_agency(certifying_agency_id)

    # rank 81 — a draw certifier must be fully accredited, not merely on probation
    if agency["accreditation_state"] != "ACCREDITED":
        raise ApiError(
            "ERR_AGENCY_NOT_ACCREDITED",
            "accreditation_state %s cannot certify a draw"
            % agency["accreditation_state"],
        )

    # rank 82
    if project["state_code"] not in agency["accredited_state_codes"]:
        raise ApiError(
            "ERR_AGENCY_JURISDICTION_MISMATCH",
            "the agency is not accredited in %s" % project["state_code"],
        )

    # rank 92 — draw_index must be contiguous, starting at 1
    existing = services.draws_of_project(project_id)
    expected = max([d["draw_index"] for d in existing], default=0) + 1
    if draw_index != expected:
        raise ApiError(
            "ERR_DRAW_SEQUENCE_GAP",
            "draw_index must be %s for this project" % expected,
        )

    count, earned = services.draw_basis(project, basis_mode)
    requested = services.requested_from_basis(project, basis_mode, earned)

    row = base_row()
    row.update(
        {
            "project_id": project_id,
            "draw_index": draw_index,
            "basis_mode": basis_mode,
            "certifying_agency_id": certifying_agency_id,
            "basis_module_count": count,
            "basis_earned_cents": earned,
            "requested_cents": requested,
            "certified_basis_cents": 0,
            "certified_cents": 0,
            "retainage_held_cents": 0,
            "net_funded_cents": 0,
            "status": "DRAFT",
            "certified_at": None,
            "funded_at": None,
            "reject_reason": None,
        }
    )
    db.draws[row["id"]] = row
    return created(serialize.draw(row))


@bp.get("/modular/draw-requests/<draw_id>")
@auth.endpoint("ProgramAdmin", "LenderDrawAdministrator", "SiteSuperintendent")
def read_draw(draw_id):
    # a DRAFT basis is refreshed by the declared triggers only, never by a read
    return ok(serialize.draw(services.get_draw(draw_id)))


@bp.get("/modular/draw-requests")
@auth.endpoint("ProgramAdmin", "LenderDrawAdministrator", "SiteSuperintendent")
def list_draws():
    project_id = validate.field_str_query("project_id")
    certifying_agency_id = validate.field_str_query("certifying_agency_id")
    status = validate.enum_query("status", STATUSES)
    basis_mode = validate.enum_query("basis_mode", BASIS_MODES)
    rows = sorted_rows(list(db.draws.values()))
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if certifying_agency_id is not None:
        rows = [r for r in rows if r["certifying_agency_id"] == certifying_agency_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if basis_mode is not None:
        rows = [r for r in rows if r["basis_mode"] == basis_mode]
    page, meta = paginate(rows)
    return ok_list([serialize.draw(r) for r in page], meta)


@bp.post("/modular/draw-requests/<draw_id>/certify")
@auth.endpoint("LenderDrawAdministrator")
def certify(draw_id):
    data = validate.body()
    validate.field_str(data, "certification_note", required=False, allow_blank=True)

    row = services.get_draw(draw_id)

    # rank 42
    if row["status"] != "DRAFT":
        raise ApiError(
            "ERR_DRAW_NOT_DRAFT", "status %s cannot be certified" % row["status"]
        )

    project = services.get_project(row["project_id"])

    # recomputed from live module state, never copied from the provisional basis
    count, certified_basis = services.draw_basis(project, row["basis_mode"])
    if row["basis_mode"] == "WIP_DEPOSIT":
        certified = calc.rhu_cents(
            calc.dec(certified_basis) * calc.dec(project["deposit_pct"])
        )
    else:
        certified = int(certified_basis)
    retainage = calc.rhu_cents(calc.dec(certified) * calc.dec(project["retainage_pct"]))
    net = certified - retainage

    # rank 90 — the fiscal ceiling, evaluated before the ledger moves
    committed = sum(
        d["certified_cents"]
        for d in services.draws_of_project(project["id"])
        if d["id"] != row["id"] and d["status"] in ("CERTIFIED", "FUNDED")
    )
    ceiling = calc.rhu_cents(
        calc.dec(project["contract_price_cents"])
        * (calc.dec(1) - calc.dec(project["retainage_pct"]))
    )
    if committed + certified > ceiling:
        raise ApiError(
            "ERR_CONTRACT_BALANCE_EXCEEDED",
            "certifying %s cents would exceed the contract ceiling of %s cents"
            % (certified, ceiling),
        )

    # rank 91
    if certified_basis <= 0:
        raise ApiError(
            "ERR_NO_CERTIFIABLE_WIP", "no qualifying module work backs this draw"
        )

    row["basis_module_count"] = count
    row["basis_earned_cents"] = certified_basis
    row["requested_cents"] = services.requested_from_basis(
        project, row["basis_mode"], certified_basis
    )
    row["certified_basis_cents"] = certified_basis
    row["certified_cents"] = certified
    row["retainage_held_cents"] = retainage
    row["net_funded_cents"] = net
    row["status"] = "CERTIFIED"
    row["certified_at"] = now()
    touch(row)

    project["wip_certified_cents"] += certified
    services.refresh_project(project)
    touch(project)
    return ok(serialize.draw(row))


@bp.post("/modular/draw-requests/<draw_id>/fund")
@auth.endpoint("LenderDrawAdministrator")
def fund(draw_id):
    data = validate.body()
    validate.field_dt(data, "funded_at", required=False)

    row = services.get_draw(draw_id)

    # rank 43
    if row["status"] != "CERTIFIED":
        raise ApiError(
            "ERR_DRAW_NOT_CERTIFIED", "status %s cannot be funded" % row["status"]
        )

    row["status"] = "FUNDED"
    row["funded_at"] = now()
    touch(row)

    project = db.projects.get(row["project_id"])
    if project is not None:
        project["funded_to_date_cents"] += row["net_funded_cents"]
        services.refresh_project(project)
        touch(project)
    return ok(serialize.draw(row))


@bp.post("/modular/draw-requests/<draw_id>/reject")
@auth.endpoint("LenderDrawAdministrator")
def reject(draw_id):
    data = validate.body(optional=False)
    reject_reason = validate.field_str(data, "reject_reason", allow_blank=True)

    row = services.get_draw(draw_id)

    # rank 43 — reject accepts DRAFT or CERTIFIED
    if row["status"] not in ("DRAFT", "CERTIFIED"):
        raise ApiError(
            "ERR_DRAW_NOT_CERTIFIED", "status %s cannot be rejected" % row["status"]
        )

    was_certified = row["status"] == "CERTIFIED"
    reversal = row["certified_cents"]

    row["status"] = "REJECTED"
    row["reject_reason"] = reject_reason
    row["certified_cents"] = 0
    row["retainage_held_cents"] = 0
    row["net_funded_cents"] = 0
    touch(row)

    project = db.projects.get(row["project_id"])
    if project is not None:
        if was_certified:
            project["wip_certified_cents"] -= reversal
        services.refresh_project(project)
        touch(project)
    return ok(serialize.draw(row))
