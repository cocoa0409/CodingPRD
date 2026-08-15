"""Plant resources (PRD 3.1)."""

from db import STORES, new_record, touch
from helpers import ALL_ROLES, auth, body, f_bool, f_str, get_or_404
from response import serialize, success
from routes import make_bp

bp = make_bp("plants")


@bp.post("/plant/plants")
def create_plant():
    auth("PlantAdmin")
    b = body()
    name = f_str(b, "name")
    license_number = f_str(b, "license_number")
    export_listed = f_bool(b, "export_listed", required=False, default=False)
    rec = new_record()
    rec.update(
        name=name,
        license_number=license_number,
        export_listed=export_listed,
        total_aging_capacity_wheels=0,
    )
    STORES["plants"][rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/plant/plants/<plantId>")
def get_plant(plantId):
    auth(*ALL_ROLES)
    rec = get_or_404("plants", plantId, "plant")
    return success(serialize(rec))


@bp.patch("/plant/plants/<plantId>")
def update_plant(plantId):
    auth("PlantAdmin")
    b = body(required=False)
    rec = get_or_404("plants", plantId, "plant")
    export_listed = f_bool(b, "export_listed", required=False)
    if export_listed is not None:
        rec["export_listed"] = export_listed
    touch(rec)
    return success(serialize(rec))
