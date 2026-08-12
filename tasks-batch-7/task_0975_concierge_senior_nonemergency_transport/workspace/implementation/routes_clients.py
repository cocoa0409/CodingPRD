"""Client registry and family portal member endpoints."""

from core import (
    db, get_caller, require_role, get_body, ok, parse_pagination, paginate,
    field_str, field_int, field_bool, field_enum, stamp_new, touch, sort_created,
    ApiError, err_not_found, err_forbidden, err_invalid, family_member_of,
)
from domain import (
    ser_client, ser_family_member, suspend_client_cascade, OPEN_RIDE_STATUSES,
    OPEN_INVOICE_STATUSES,
)

MOBILITY_AIDS = {"NONE", "WALKER", "FOLDING_WHEELCHAIR", "POWER_WHEELCHAIR"}
ASSIST_LEVELS = {"DOOR_TO_DOOR", "DOOR_THROUGH_DOOR"}
ACCESS_LEVELS = {"VIEW_ONLY", "BOOK_FOR_CLIENT", "BILLING_PAYER"}
CLIENT_STATUSES = {"ACTIVE", "SUSPENDED", "DEACTIVATED"}


def _get_client_or_404(client_id):
    client = db.clients.get(client_id)
    if client is None:
        raise err_not_found("Client not found")
    return client


def _check_client_read_ownership(caller, client):
    if caller.role == "Client":
        if caller.user_id != client["id"]:
            raise err_forbidden("Client may only access their own record")
    elif caller.role == "FamilyMember":
        member = family_member_of(caller)
        if member is None or member["status"] != "ACTIVE":
            raise err_forbidden("Family membership not active")
        if member["client_id"] != client["id"]:
            raise err_forbidden("Family member may only access their own client")


def register(app):

    @app.route("/clients", methods=["POST"])
    def create_client():
        body = get_body()
        full_name = field_str(body, "full_name", required=True)
        mobility_aid = field_enum(body, "mobility_aid", MOBILITY_AIDS, required=True)
        assist = field_enum(body, "assist_level_default", ASSIST_LEVELS, required=True)
        home_zone = field_str(body, "home_zone", required=True)
        address = field_str(body, "address", required=True)
        hold_limit = field_int(body, "billing_hold_limit_cents", minimum=0)
        caller = get_caller()
        require_role(caller, {"Coordinator"})
        client = {
            "full_name": full_name,
            "status": "ACTIVE",
            "mobility_aid": mobility_aid,
            "assist_level_default": assist,
            "home_zone": home_zone,
            "address": address,
            "credit_balance_cents": 0,
            "billing_hold_limit_cents": 20000 if hold_limit is None else hold_limit,
            "no_show_count": 0,
        }
        stamp_new(client)
        db.clients[client["id"]] = client
        return ok(ser_client(client), status=201)

    @app.route("/clients/<cid>", methods=["GET"])
    def get_client(cid):
        caller = get_caller()
        require_role(
            caller,
            {"PlatformAdmin", "Coordinator", "BillingAdmin", "Client", "FamilyMember"},
        )
        client = _get_client_or_404(cid)
        _check_client_read_ownership(caller, client)
        return ok(ser_client(client))

    @app.route("/clients", methods=["GET"])
    def list_clients():
        caller = get_caller()
        require_role(caller, {"PlatformAdmin", "Coordinator", "BillingAdmin"})
        limit, offset = parse_pagination()
        items = sort_created(db.clients.values())
        status = __import__("flask").request.args.get("status")
        if status is not None:
            items = [c for c in items if c["status"] == status]
        page, meta = paginate(items, limit, offset)
        return ok([ser_client(c) for c in page], response_type="array", pagination=meta)

    @app.route("/clients/<cid>", methods=["PATCH"])
    def patch_client(cid):
        body = get_body()
        expected_version = field_int(body, "expected_client_version", required=True)
        new_status = field_enum(body, "status", CLIENT_STATUSES)
        home_zone = field_str(body, "home_zone")
        mobility_aid = field_enum(body, "mobility_aid", MOBILITY_AIDS)
        assist = field_enum(body, "assist_level_default", ASSIST_LEVELS)
        hold_limit = field_int(body, "billing_hold_limit_cents", minimum=0)
        caller = get_caller()
        require_role(caller, {"Coordinator"})
        client = _get_client_or_404(cid)
        # state precondition: DEACTIVATED is terminal
        if (
            new_status is not None
            and new_status != client["status"]
            and client["status"] == "DEACTIVATED"
        ):
            raise err_invalid("DEACTIVATED is terminal")
        # OCC
        if expected_version != client["version"]:
            raise ApiError(
                "ERR_STALE_VERSION", 412,
                "expected_client_version does not match the current version",
            )
        # open-work guard for deactivation
        if new_status == "DEACTIVATED" and client["status"] != "DEACTIVATED":
            for ride in db.rides.values():
                if ride["client_id"] == cid and ride["status"] in OPEN_RIDE_STATUSES:
                    raise ApiError(
                        "ERR_CLIENT_HAS_OPEN_WORK", 409,
                        "Client has rides in non-terminal states",
                    )
            for inv in db.invoices.values():
                if inv["client_id"] == cid and inv["issuance_status"] in OPEN_INVOICE_STATUSES:
                    raise ApiError(
                        "ERR_CLIENT_HAS_OPEN_WORK", 409,
                        "Client has open invoices",
                    )
        # apply
        cascade = (
            new_status == "SUSPENDED" and client["status"] == "ACTIVE"
        )
        if new_status is not None:
            client["status"] = new_status
        if home_zone is not None:
            client["home_zone"] = home_zone
        if mobility_aid is not None:
            client["mobility_aid"] = mobility_aid
        if assist is not None:
            client["assist_level_default"] = assist
        if hold_limit is not None:
            client["billing_hold_limit_cents"] = hold_limit
        touch(client)
        if cascade:
            suspend_client_cascade(client)
        return ok(ser_client(client))

    # ------------------------------------------------------------------
    # Family members
    # ------------------------------------------------------------------

    @app.route("/family-members", methods=["POST"])
    def create_family_member():
        body = get_body()
        client_id = field_str(body, "client_id", required=True)
        full_name = field_str(body, "full_name", required=True)
        relation = field_str(body, "relation", required=True)
        access_level = field_enum(body, "access_level", ACCESS_LEVELS, required=True)
        notify = field_bool(body, "notify_on_ride_events")
        caller = get_caller()
        require_role(caller, {"Coordinator"})
        _get_client_or_404(client_id)
        member = {
            "client_id": client_id,
            "full_name": full_name,
            "relation": relation,
            "access_level": access_level,
            "notify_on_ride_events": True if notify is None else notify,
            "status": "ACTIVE",
        }
        stamp_new(member)
        db.family_members[member["id"]] = member
        return ok(ser_family_member(member), status=201)

    @app.route("/family-members/<mid>", methods=["GET"])
    def get_family_member(mid):
        caller = get_caller()
        require_role(caller, {"Coordinator", "BillingAdmin", "Client", "FamilyMember"})
        member = db.family_members.get(mid)
        if member is None:
            raise err_not_found("Family member not found")
        if caller.role == "Client":
            if member["client_id"] != caller.user_id:
                raise err_forbidden("Client may only access their own family members")
        elif caller.role == "FamilyMember":
            caller_member = family_member_of(caller)
            if caller_member is None or caller_member["status"] != "ACTIVE":
                raise err_forbidden("Family membership not active")
            if caller_member["client_id"] != member["client_id"]:
                raise err_forbidden("Family member may only access their own client's members")
        return ok(ser_family_member(member))

    @app.route("/family-members", methods=["GET"])
    def list_family_members():
        caller = get_caller()
        require_role(caller, {"Coordinator", "BillingAdmin"})
        limit, offset = parse_pagination()
        req = __import__("flask").request
        items = sort_created(db.family_members.values())
        client_id = req.args.get("client_id")
        status = req.args.get("status")
        if client_id is not None:
            items = [m for m in items if m["client_id"] == client_id]
        if status is not None:
            items = [m for m in items if m["status"] == status]
        page, meta = paginate(items, limit, offset)
        return ok(
            [ser_family_member(m) for m in page],
            response_type="array", pagination=meta,
        )

    @app.route("/family-members/<mid>/revoke", methods=["POST"])
    def revoke_family_member(mid):
        get_body()
        caller = get_caller()
        require_role(caller, {"Coordinator"})
        member = db.family_members.get(mid)
        if member is None:
            raise err_not_found("Family member not found")
        if member["status"] == "ACTIVE":
            member["status"] = "REVOKED"
            touch(member)
        return ok(ser_family_member(member))
