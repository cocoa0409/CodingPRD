"""Routes: clients, properties, engineers, logical clock."""
from flask import request
from core import (db, ApiError, ok, ok_list, require_role, get_body,
                  require_fields, paginate, sort_key, base_fields, touch,
                  parse_iso)
from serializers import ser_client, ser_property, ser_engineer

CLIENT_ENTITY_TYPES = {"C_CORP", "S_CORP", "PARTNERSHIP", "INDIVIDUAL"}
BUILDING_TYPES = {"COMMERCIAL", "RESIDENTIAL_RENTAL", "INDUSTRIAL"}


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def get_or_404(coll, _id):
    ent = coll.get(_id)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return ent


def register(app):
    # ---------------- Client ----------------
    @app.route("/clients", methods=["POST"])
    def create_client():
        require_role("StudyManager")
        body = get_body()
        require_fields(body, "legal_name", "entity_type", "marginal_tax_rate")
        if body["entity_type"] not in CLIENT_ENTITY_TYPES:
            raise ApiError("ERR_VALIDATION", 400, "Invalid entity_type")
        rate = body["marginal_tax_rate"]
        if not is_number(rate):
            raise ApiError("ERR_VALIDATION", 400, "marginal_tax_rate must be a number")
        if rate < 0 or rate > 1:
            raise ApiError("ERR_INVALID_AMOUNT", 422, "marginal_tax_rate out of range")
        c = base_fields()
        c.update({
            "legal_name": body["legal_name"],
            "entity_type": body["entity_type"],
            "marginal_tax_rate": rate,
            "status": "ONBOARDING",
            "outstanding_fee_cents": 0,
        })
        db.clients[c["id"]] = c
        return ok(ser_client(c), 201)

    @app.route("/clients/<cid>", methods=["GET"])
    def get_client(cid):
        require_role("StudyManager", "Engineer", "Reviewer", "CPA")
        c = get_or_404(db.clients, cid)
        return ok(ser_client(c))

    @app.route("/clients/<cid>/activate", methods=["POST"])
    def activate_client(cid):
        require_role("StudyManager")
        c = get_or_404(db.clients, cid)
        if c["status"] != "ONBOARDING":
            raise ApiError("ERR_INVALID_STATE", 409, "Client not ONBOARDING")
        c["status"] = "ACTIVE"
        touch(c)
        return ok(ser_client(c))

    # ---------------- Property ----------------
    @app.route("/properties", methods=["POST"])
    def create_property():
        require_role("StudyManager")
        body = get_body()
        require_fields(body, "client_id", "address", "building_type",
                       "purchase_price_cents", "land_value_cents",
                       "placed_in_service_date")
        # existence of FK
        get_or_404(db.clients, body["client_id"])
        if body["building_type"] not in BUILDING_TYPES:
            raise ApiError("ERR_VALIDATION", 400, "Invalid building_type")
        pp = body["purchase_price_cents"]
        lv = body["land_value_cents"]
        if not is_int(pp) or not is_int(lv):
            raise ApiError("ERR_VALIDATION", 400, "price/land must be integers")
        if pp <= 0:
            raise ApiError("ERR_INVALID_AMOUNT", 422, "purchase_price_cents must be > 0")
        if lv < 0 or lv >= pp:
            raise ApiError("ERR_INVALID_AMOUNT", 422, "land_value_cents out of range")
        pis = parse_iso(body["placed_in_service_date"])
        p = base_fields()
        p.update({
            "client_id": body["client_id"],
            "address": body["address"],
            "building_type": body["building_type"],
            "purchase_price_cents": pp,
            "land_value_cents": lv,
            "placed_in_service_date": pis,
            "depreciable_basis_cents": pp - lv,
        })
        db.properties[p["id"]] = p
        return ok(ser_property(p), 201)

    @app.route("/properties/<pid>", methods=["GET"])
    def get_property(pid):
        require_role("StudyManager", "Engineer", "Reviewer", "CPA")
        p = get_or_404(db.properties, pid)
        return ok(ser_property(p))

    @app.route("/properties", methods=["GET"])
    def list_properties():
        require_role("StudyManager", "Engineer", "Reviewer", "CPA")
        limit, offset = paginate(request.args)
        items = list(db.properties.values())
        cid = request.args.get("client_id")
        if cid is not None:
            items = [p for p in items if p["client_id"] == cid]
        items.sort(key=sort_key)
        total = len(items)
        page = items[offset:offset + limit]
        return ok_list([ser_property(p) for p in page], limit, offset, total)

    # ---------------- Engineer ----------------
    @app.route("/engineers", methods=["POST"])
    def create_engineer():
        require_role("StudyManager")
        body = get_body()
        require_fields(body, "full_name", "email")
        e = base_fields(with_version=False)
        e.update({"full_name": body["full_name"], "email": body["email"]})
        db.engineers[e["id"]] = e
        return ok(ser_engineer(e), 201)

    @app.route("/engineers/<eid>", methods=["GET"])
    def get_engineer(eid):
        require_role("StudyManager", "Engineer", "Reviewer", "CPA")
        e = get_or_404(db.engineers, eid)
        return ok(ser_engineer(e))

    # ---------------- Logical clock ----------------
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        require_role("StudyManager")
        body = get_body()
        require_fields(body, "to_iso8601")
        db.clock = parse_iso(body["to_iso8601"])
        return ok({})
