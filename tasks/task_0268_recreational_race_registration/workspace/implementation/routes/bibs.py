"""BibAssignment read endpoints (creation lives in registrations.assign-bib)."""
from flask import Blueprint, request

from db import db
from middleware import auth, require_role
from response import object_response
from services.store import serialize_generic, paginate_and_respond
from services.validate import lookup

bp = Blueprint("bibs", __name__)

READ_ROLES = {"RaceDirector", "Participant", "PacketStaff", "TimingOfficial"}


@bp.route("/bib-assignments/<bib_assignment_id>", methods=["GET"])
def get_bib(bib_assignment_id):
    user_id, role = auth()
    require_role(role, READ_ROLES)
    b = lookup(db.bib_assignments, bib_assignment_id, "BibAssignment")
    return object_response(serialize_generic(b), 200)


@bp.route("/bib-assignments", methods=["GET"])
def list_bibs():
    user_id, role = auth()
    require_role(role, READ_ROLES)
    items = list(db.bib_assignments.values())
    for f in ("registration_id", "distance_id", "wave_id"):
        v = request.args.get(f)
        if v is not None:
            items = [b for b in items if b.get(f) == v]
    return paginate_and_respond("bib", items, request.args)


@bp.route("/waves/<wave_id>/bib-assignments", methods=["GET"])
def list_wave_bibs(wave_id):
    user_id, role = auth()
    require_role(role, READ_ROLES)
    lookup(db.waves, wave_id, "Wave")
    items = [b for b in db.bib_assignments.values() if b["wave_id"] == wave_id]
    return paginate_and_respond("bib", items, request.args)


@bp.route("/distances/<distance_id>/bib-assignments", methods=["GET"])
def list_distance_bibs(distance_id):
    user_id, role = auth()
    require_role(role, READ_ROLES)
    lookup(db.distances, distance_id, "Distance")
    items = [b for b in db.bib_assignments.values() if b["distance_id"] == distance_id]
    return paginate_and_respond("bib", items, request.args)
