"""DefectClaim endpoints — the dual-variant responsibility allocation cycle."""

from flask import Blueprint

import auth
import calc
import serialize
import services
import validate
from envelope import created, ok, ok_list, paginate
from errors import ApiError
from store import base_row, db, sorted_rows, touch

bp = Blueprint("claims", __name__)

PHASES = ("FACTORY", "TRANSIT", "SITE_SET", "POST_SET")
STATUSES = ("OPEN", "ADJUDICATED", "DISPUTED", "CLOSED")
RESPONSIBILITIES = ("UNDETERMINED", "FACTORY", "FIELD", "SHARED")
BUCKETS = ("FACTORY_WARRANTY", "FIELD_WARRANTY", "SPLIT")


@bp.post("/modular/defect-claims")
@auth.endpoint("SiteSuperintendent", "FactoryProductionManager")
def create_claim():
    data = validate.body(optional=False)
    module_id = validate.field_id(data, "module_id")
    discovered_phase = validate.field_enum(data, "discovered_phase", PHASES)
    description = validate.field_str(data, "description")
    repair_cost_cents = validate.field_int(data, "repair_cost_cents", minimum=0)
    inspection_id = validate.field_id(data, "inspection_id", required=False)

    # rank 5 — module_id then inspection_id
    module = services.get_module(module_id)
    inspection = None
    if inspection_id is not None:
        inspection = services.get_inspection(inspection_id)

    # rank 88 — the cited inspection must belong to the same module
    if inspection is not None and inspection["module_id"] != module_id:
        raise ApiError(
            "ERR_CROSS_AGGREGATE_MISMATCH",
            "inspection_id belongs to a different module",
        )

    row = base_row()
    row.update(
        {
            "module_id": module_id,
            "inspection_id": inspection_id,
            "discovered_phase": discovered_phase,
            "description": description,
            "repair_cost_cents": repair_cost_cents,
            "responsibility": "UNDETERMINED",
            "factory_share_pct": calc.dec("0.00"),
            "field_share_pct": calc.dec("0.00"),
            "factory_charge_cents": 0,
            "field_charge_cents": 0,
            # PRD §3.8: a new claim is persisted with "warranty_bucket at its
            # default of SPLIT".
            "warranty_bucket": "SPLIT",
            "status": "OPEN",
            "adjudication_round": 0,
            "adjudicated_by_user_id": None,
            "dispute_note": None,
        }
    )
    db.defect_claims[row["id"]] = row
    return created(serialize.defect_claim(row))


@bp.get("/modular/defect-claims/<claim_id>")
@auth.endpoint(
    "ProgramAdmin",
    "WarrantyAdjudicator",
    "SiteSuperintendent",
    "FactoryProductionManager",
    "LenderDrawAdministrator",
)
def read_claim(claim_id):
    return ok(serialize.defect_claim(services.get_claim(claim_id)))


@bp.get("/modular/defect-claims")
@auth.endpoint(
    "ProgramAdmin",
    "WarrantyAdjudicator",
    "SiteSuperintendent",
    "FactoryProductionManager",
    "LenderDrawAdministrator",
)
def list_claims():
    module_id = validate.field_str_query("module_id")
    inspection_id = validate.field_str_query("inspection_id")
    status = validate.enum_query("status", STATUSES)
    responsibility = validate.enum_query("responsibility", RESPONSIBILITIES)
    discovered_phase = validate.enum_query("discovered_phase", PHASES)
    warranty_bucket = validate.enum_query("warranty_bucket", BUCKETS)
    rows = sorted_rows(list(db.defect_claims.values()))
    if module_id is not None:
        rows = [r for r in rows if r["module_id"] == module_id]
    if inspection_id is not None:
        rows = [r for r in rows if r["inspection_id"] == inspection_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if responsibility is not None:
        rows = [r for r in rows if r["responsibility"] == responsibility]
    if discovered_phase is not None:
        rows = [r for r in rows if r["discovered_phase"] == discovered_phase]
    if warranty_bucket is not None:
        rows = [r for r in rows if r["warranty_bucket"] == warranty_bucket]
    page, meta = paginate(rows)
    return ok_list([serialize.defect_claim(r) for r in page], meta)


@bp.post("/modular/defect-claims/<claim_id>/adjudicate")
@auth.endpoint("WarrantyAdjudicator")
def adjudicate(claim_id):
    data = validate.body()
    validate.field_str(data, "adjudication_note", required=False, allow_blank=True)

    row = services.get_claim(claim_id)

    # rank 57
    if row["status"] not in ("OPEN", "DISPUTED"):
        raise ApiError(
            "ERR_CLAIM_NOT_ADJUDICABLE",
            "status %s cannot be adjudicated" % row["status"],
        )

    module = services.get_module(row["module_id"])
    project = db.projects.get(module["project_id"])
    inspection = (
        db.inspections.get(row["inspection_id"]) if row["inspection_id"] else None
    )

    if row["status"] == "OPEN":
        row["adjudication_round"] = 1
        factory_share = calc.allocate_phase_presumption(row)
    else:
        row["adjudication_round"] = 2
        factory_share = calc.allocate_evidence_weighted(
            row, inspection, module, project
        )

    row.update(calc.allocation_tail(row, factory_share))
    row["status"] = "ADJUDICATED"
    row["adjudicated_by_user_id"] = auth.user_id()
    touch(row)

    # counters are updated AFTER the allocation, so an adjudication never feeds
    # its own evidence back into itself; a SHARED split increments neither side
    if row["responsibility"] == "FACTORY":
        module["defect_count_factory"] += 1
    elif row["responsibility"] == "FIELD":
        module["defect_count_field"] += 1
    touch(module)
    return ok(serialize.defect_claim(row))


@bp.post("/modular/defect-claims/<claim_id>/dispute")
@auth.endpoint("FactoryProductionManager", "SiteSuperintendent")
def dispute(claim_id):
    data = validate.body(optional=False)
    dispute_note = validate.field_str(data, "dispute_note")

    row = services.get_claim(claim_id)

    # rank 58
    if row["status"] != "ADJUDICATED":
        raise ApiError(
            "ERR_CLAIM_NOT_ADJUDICATED",
            "status %s cannot be disputed" % row["status"],
        )

    # rank 59
    if row["adjudication_round"] >= 2:
        raise ApiError(
            "ERR_DISPUTE_ROUND_LIMIT",
            "an evidence-weighted re-adjudication is final",
        )

    row["status"] = "DISPUTED"
    row["dispute_note"] = dispute_note
    touch(row)
    return ok(serialize.defect_claim(row))
