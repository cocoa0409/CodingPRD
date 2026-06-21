"""Certificate read routes and the test-driving clock endpoint."""
from flask import request

import domain
import serializers as S
from common import get_user_context, require_role, get_json_body, check_string
from errors import err
from lookups import get_certificate, list_response
from response import success
from store import db


def register(app):

    @app.route("/certificates", methods=["GET"])
    def list_certificates():
        user_id, role = get_user_context()
        require_role(role, {"Owner", "Trainer", "FrontDesk", "AdminManager"})
        rows = list(db.certificates.values())
        enrollment_id = request.args.get("enrollment_id")
        dog_id = request.args.get("dog_id")
        if enrollment_id is not None:
            rows = [c for c in rows if c["enrollment_id"] == enrollment_id]
        if dog_id is not None:
            rows = [c for c in rows if c["dog_id"] == dog_id]
        if role == "Owner":
            owned = {d["id"] for d in db.dogs.values() if d["owner_id"] == user_id}
            rows = [c for c in rows if c["dog_id"] in owned]
        return list_response(rows, S.ser_certificate)

    @app.route("/certificates/<certificate_id>", methods=["GET"])
    def get_certificate_ep(certificate_id):
        user_id, role = get_user_context()
        require_role(role, {"Owner", "Trainer", "FrontDesk", "AdminManager"})
        cert = get_certificate(certificate_id)
        if role == "Owner":
            dog = db.dogs.get(cert["dog_id"])
            if not dog or dog["owner_id"] != user_id:
                raise err("ERR_NOT_DOG_OWNER", "Not owner of this certificate's dog")
        return success(S.ser_certificate(cert), 200)

    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        user_id, role = get_user_context()
        require_role(role, {"AdminManager"})
        body = get_json_body()
        to_iso8601 = check_string(body, "to_iso8601")
        dt = domain.parse_dt(to_iso8601)
        if dt is None:
            raise err("ERR_INVALID_REQUEST", "Invalid to_iso8601")
        db.set_clock(dt)
        return success({}, 200)
