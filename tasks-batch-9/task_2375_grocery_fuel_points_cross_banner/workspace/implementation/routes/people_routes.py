"""Households, members, household linkages and fraud signals."""
from flask import Blueprint

import clock
import db
import middleware
import response
import shape
from errors import ApiError
from routes._helpers import invalid_state, listing
from services import calc, core, serializers

bp = Blueprint("people", __name__)

LINK_ROLES = ("PRIMARY", "SECONDARY")
LINK_STATUSES = ("PENDING", "ACTIVE", "SUSPENDED", "REVOKED")
LIVE_LINK_STATUSES = ("PENDING", "ACTIVE", "SUSPENDED")
SIGNAL_TYPES = ("ALT_ID_SHARING", "RAPID_TRANSFER", "CROSS_BANNER_VELOCITY",
                "OVERDRAWN_AUTH", "GEO_IMPOSSIBLE")
SIGNAL_STATUSES = ("OPEN", "CLEARED")
HOUSEHOLD_STATUSES = ("ACTIVE", "FROZEN")
BLOCKING_THAW_SIGNALS = ("ALT_ID_SHARING", "GEO_IMPOSSIBLE")


# ---------------------------------------------------------------- households

@bp.route("/households", methods=["POST"])
def create_household():
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst"))
    payload = shape.body()
    banner_id = shape.req_str(payload, "banner_id")
    household_code = shape.req_str(payload, "household_code", 4, 24)

    banner = core.fetch("banners", banner_id)

    for existing in db.households.values():
        if existing["banner_id"] == banner["id"] \
                and existing["household_code"] == household_code:
            raise ApiError("ERR_HOUSEHOLD_CODE_DUPLICATE",
                           "household_code '%s' is already used under this banner"
                           % household_code)

    household = core.new_entity()
    household.update({
        "banner_id": banner["id"],
        "household_code": household_code,
        "status": "ACTIVE",
        "frozen_reason": None,
        "frozen_at": None,
    })
    db.households[household["id"]] = household
    return response.object_response(serializers.household(household), 201)


@bp.route("/households/<household_id>", methods=["GET"])
def get_household(household_id):
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor", "PumpTerminal"))
    household = core.fetch("households", household_id)
    return response.object_response(serializers.household(household))


@bp.route("/households/<household_id>/fraud-signals", methods=["GET"])
def list_household_fraud_signals(household_id):
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor"))
    shape.pagination()
    status = shape.arg_enum("status", SIGNAL_STATUSES)
    signal_type = shape.arg_enum("signal_type", SIGNAL_TYPES)
    household = core.fetch("households", household_id)
    rows = [s for s in db.fraud_signals.values() if s["household_id"] == household["id"]]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    if signal_type is not None:
        rows = [s for s in rows if s["signal_type"] == signal_type]
    return listing(rows, serializers.fraud_signal,
                   order=lambda s: (s["detected_at"], s["created_at"], s["_seq"]))


@bp.route("/households/<household_id>/freeze", methods=["POST"])
def freeze_household(household_id):
    middleware.require(("LoyaltySupervisor", "ProgramAdmin"))
    household = core.fetch("households", household_id)
    if household["status"] != "ACTIVE":
        raise invalid_state("only an ACTIVE household may be frozen (current %s)"
                            % household["status"])
    household["status"] = "FROZEN"
    household["frozen_reason"] = "MANUAL"
    household["frozen_at"] = clock.now()
    core.bump(household)
    return response.object_response(serializers.household(household))


@bp.route("/households/<household_id>/unfreeze", methods=["POST"])
def unfreeze_household(household_id):
    middleware.require(("LoyaltySupervisor", "ProgramAdmin"))
    household = core.fetch("households", household_id)
    if household["status"] != "FROZEN":
        raise invalid_state("only a FROZEN household may be thawed (current %s)"
                            % household["status"])
    for signal in core.open_signals(household["id"]):
        if signal["signal_type"] in BLOCKING_THAW_SIGNALS:
            raise invalid_state("an OPEN %s fraud signal blocks the thaw"
                                % signal["signal_type"])
    household["status"] = "ACTIVE"
    household["frozen_reason"] = None
    household["frozen_at"] = None
    core.bump(household)
    return response.object_response(serializers.household(household))


# ------------------------------------------------------------------- members

@bp.route("/members", methods=["POST"])
def create_member():
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "StoreOperator"))
    payload = shape.body()
    banner_id = shape.req_str(payload, "banner_id")
    alt_id = shape.req_str(payload, "alt_id", 10, 12, r"^\d{10,12}$")
    card_number = shape.req_str(payload, "card_number", 8, 19, r"^\d{8,19}$")
    full_name = shape.req_str(payload, "full_name", 1, 120)

    banner = core.fetch("banners", banner_id)

    for existing in db.members.values():
        if existing["banner_id"] == banner["id"] and existing["alt_id"] == alt_id:
            raise ApiError("ERR_ALT_ID_DUPLICATE",
                           "alt_id '%s' is already enrolled under this banner" % alt_id)

    member = core.new_entity()
    member.update({
        "banner_id": banner["id"],
        "alt_id": alt_id,
        "card_number": card_number,
        "full_name": full_name,
    })
    db.members[member["id"]] = member
    return response.object_response(serializers.member(member), 201)


@bp.route("/members/<member_id>", methods=["GET"])
def get_member(member_id):
    ctx = middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor",
                              "StoreOperator", "PumpTerminal", "Member"))
    member = core.fetch("members", member_id)
    middleware.own_member(ctx, member["id"])
    return response.object_response(serializers.member(member))


@bp.route("/members", methods=["GET"])
def list_members():
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor",
                        "StoreOperator", "PumpTerminal"))
    shape.pagination()
    banner_id = shape.arg_str("banner_id")
    alt_id = shape.arg_str("alt_id")
    card_number = shape.arg_str("card_number")
    rows = list(db.members.values())
    if banner_id is not None:
        rows = [m for m in rows if m["banner_id"] == banner_id]
    if alt_id is not None:
        rows = [m for m in rows if m["alt_id"] == alt_id]
    if card_number is not None:
        rows = [m for m in rows if m["card_number"] == card_number]
    return listing(rows, serializers.member, order=core.order_key)


@bp.route("/members/<member_id>/points-summary", methods=["GET"])
def member_points_summary(member_id):
    ctx = middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor",
                              "PumpTerminal", "Member"))
    member = core.fetch("members", member_id)
    middleware.own_member(ctx, member["id"])
    return response.object_response(calc.points_summary(member))


# ---------------------------------------------------------- household links

def _live_pair_link(household_id, member_id, exclude_id=None):
    for link in db.household_links.values():
        if link["id"] == exclude_id:
            continue
        if link["household_id"] == household_id and link["member_id"] == member_id \
                and link["status"] in LIVE_LINK_STATUSES:
            return link
    return None


def _live_primary_link(household_id, exclude_id=None):
    for link in core.by_created(list(db.household_links.values())):
        if link["id"] == exclude_id:
            continue
        if link["household_id"] == household_id and link["link_role"] == "PRIMARY" \
                and link["status"] in LIVE_LINK_STATUSES:
            return link
    return None


def _coverage_propagation(household):
    """PRD 2.11: the household's derived coverage figures moved."""
    core.bump(household)


@bp.route("/household-links", methods=["POST"])
def create_household_link():
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst"))
    payload = shape.body()
    household_id = shape.req_str(payload, "household_id")
    member_id = shape.req_str(payload, "member_id")
    link_role = shape.req_enum(payload, "link_role", LINK_ROLES)

    household = core.fetch("households", household_id)
    member = core.fetch("members", member_id)

    if _live_pair_link(household["id"], member["id"]) is not None:
        raise ApiError("ERR_DUPLICATE_ACTIVE_LINK",
                       "a live linkage already exists for this household and member")
    if link_role == "PRIMARY" and _live_primary_link(household["id"]) is not None:
        raise ApiError("ERR_PRIMARY_LINK_EXISTS",
                       "household %s already holds a live PRIMARY linkage" % household["id"])

    link = core.new_entity()
    link.update({
        "household_id": household["id"],
        "member_id": member["id"],
        "link_role": link_role,
        "status": "PENDING",
        "activated_at": None,
        "revoked_at": None,
    })
    db.household_links[link["id"]] = link
    return response.object_response(serializers.household_link(link), 201)


@bp.route("/household-links/<link_id>", methods=["GET"])
def get_household_link(link_id):
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor",
                        "PumpTerminal", "Member"))
    link = core.fetch("household_links", link_id)
    return response.object_response(serializers.household_link(link))


@bp.route("/household-links", methods=["GET"])
def list_household_links():
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor", "PumpTerminal"))
    shape.pagination()
    household_id = shape.arg_str("household_id")
    member_id = shape.arg_str("member_id")
    link_role = shape.arg_enum("link_role", LINK_ROLES)
    status = shape.arg_enum("status", LINK_STATUSES)
    rows = list(db.household_links.values())
    if household_id is not None:
        rows = [l for l in rows if l["household_id"] == household_id]
    if member_id is not None:
        rows = [l for l in rows if l["member_id"] == member_id]
    if link_role is not None:
        rows = [l for l in rows if l["link_role"] == link_role]
    if status is not None:
        rows = [l for l in rows if l["status"] == status]
    return listing(rows, serializers.household_link, order=core.order_key)


@bp.route("/household-links/<link_id>/activate", methods=["POST"])
def activate_household_link(link_id):
    middleware.require(("LoyaltyAnalyst", "ProgramAdmin"))
    link = core.fetch("household_links", link_id)
    household = db.households[link["household_id"]]
    banner = db.banners[household["banner_id"]]

    if household["status"] != "ACTIVE":
        raise ApiError("ERR_HOUSEHOLD_FROZEN", "household %s is FROZEN" % household["id"])
    if banner["status"] != "ACTIVE":
        raise ApiError("ERR_BANNER_SUSPENDED", "banner %s is SUSPENDED" % banner["id"])
    if link["status"] not in ("PENDING", "SUSPENDED"):
        raise invalid_state("only a PENDING or SUSPENDED linkage may be activated (current %s)"
                            % link["status"])
    if link["status"] == "PENDING" and link["link_role"] == "PRIMARY" \
            and _live_primary_link(household["id"], exclude_id=link["id"]) is not None:
        raise ApiError("ERR_PRIMARY_LINK_EXISTS",
                       "household %s already holds a live PRIMARY linkage" % household["id"])

    link["status"] = "ACTIVE"
    link["activated_at"] = clock.now()
    core.bump(link)
    _coverage_propagation(household)
    return response.object_response(serializers.household_link(link))


@bp.route("/household-links/<link_id>/suspend", methods=["POST"])
def suspend_household_link(link_id):
    middleware.require(("LoyaltyAnalyst", "ProgramAdmin"))
    link = core.fetch("household_links", link_id)
    if link["status"] != "ACTIVE":
        raise invalid_state("only an ACTIVE linkage may be suspended (current %s)"
                            % link["status"])
    link["status"] = "SUSPENDED"
    core.bump(link)
    _coverage_propagation(db.households[link["household_id"]])
    return response.object_response(serializers.household_link(link))


@bp.route("/household-links/<link_id>/revoke", methods=["POST"])
def revoke_household_link(link_id):
    middleware.require(("LoyaltyAnalyst", "ProgramAdmin"))
    link = core.fetch("household_links", link_id)
    if link["status"] not in LIVE_LINK_STATUSES:
        raise invalid_state("linkage is already REVOKED")

    was_active = link["status"] == "ACTIVE"
    was_cross_banner = core.link_is_cross_banner(link)

    # hop 1
    link["status"] = "REVOKED"
    link["revoked_at"] = clock.now()
    core.bump(link)

    if was_active:
        household = db.households[link["household_id"]]
        # hop 2 - coverage propagation
        _coverage_propagation(household)
        # hop 3 - cross-banner authorizations lose their coverage
        if was_cross_banner:
            member = db.members[link["member_id"]]
            candidates = [r for r in db.fuel_redemptions.values()
                          if r["member_id"] == member["id"]
                          and r["authorization_status"] == "AUTHORIZED"]
            for redemption in core.by_created(candidates):
                site = db.sites[redemption["site_id"]]
                if site["banner_id"] == member["banner_id"]:
                    continue
                if core.member_has_active_link_to_banner(member["id"], site["banner_id"]):
                    continue
                core.void_redemption(redemption, member)

    return response.object_response(serializers.household_link(link))


# -------------------------------------------------------------- fraud signals

@bp.route("/fraud-signals", methods=["POST"])
def create_fraud_signal():
    ctx = middleware.require(("LoyaltyAnalyst", "ProgramAdmin"))
    payload = shape.body()
    household_id = shape.req_str(payload, "household_id")
    signal_type = shape.req_enum(payload, "signal_type", SIGNAL_TYPES)
    severity_weight = shape.req_int(payload, "severity_weight", 1, 100)

    household = core.fetch("households", household_id)

    signal = core.new_entity()
    signal.update({
        "household_id": household["id"],
        "signal_type": signal_type,
        "severity_weight": severity_weight,
        "status": "OPEN",
        "source": "ANALYST",
        "detected_at": clock.now(),
        "cleared_at": None,
        "cleared_by_user_id": None,
    })
    db.fraud_signals[signal["id"]] = signal
    core.evaluate_auto_freeze(household)
    core.bump(household)
    del ctx
    return response.object_response(serializers.fraud_signal(signal), 201)


@bp.route("/fraud-signals/<signal_id>/clear", methods=["POST"])
def clear_fraud_signal(signal_id):
    ctx = middleware.require(("LoyaltyAnalyst", "ProgramAdmin"))
    signal = core.fetch("fraud_signals", signal_id)
    if signal["status"] != "OPEN":
        raise invalid_state("only an OPEN fraud signal may be cleared")
    signal["status"] = "CLEARED"
    signal["cleared_at"] = clock.now()
    signal["cleared_by_user_id"] = ctx.user_id
    core.bump(signal)
    household = db.households[signal["household_id"]]
    core.bump(household)
    return response.object_response(serializers.fraud_signal(signal))
