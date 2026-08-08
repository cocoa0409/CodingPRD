"""Clinician roster (PRD 3.1)."""

from flask import Blueprint

import config
import envelope
import store
from fields import Field
from ladder import Op
from services import serialize

bp = Blueprint("clinicians", __name__)


@bp.post("/sbhc/clinicians")
def create_clinician():
    op = Op("POST /sbhc/clinicians", ["SbhcAdmin"])
    op.schema(
        [
            Field("full_name", "string", required=True, min_len=1),
            Field("discipline", "enum", required=True, values=config.CLINICIAN_DISCIPLINES),
            Field("license_number", "string", required=True, min_len=1),
        ]
    )
    op.run()
    clinician = store.new_row(
        "clinicians",
        {
            "full_name": op.body["full_name"],
            "discipline": op.body["discipline"],
            "license_number": op.body["license_number"],
        },
    )
    return envelope.created(serialize.dump(clinician))


@bp.get("/sbhc/clinicians/<id>")
def read_clinician(id):
    op = Op("GET /sbhc/clinicians/{id}", ["SbhcAdmin", "Registrar", "Clinician"])
    op.path_id("clinician", "clinicians", id, "ERR_CLINICIAN_NOT_FOUND")
    op.run()
    return envelope.ok(serialize.dump(op.get("clinician")))
