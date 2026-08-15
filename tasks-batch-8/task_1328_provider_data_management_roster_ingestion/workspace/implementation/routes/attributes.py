"""ProviderAttribute endpoints (PRD §3.4)."""

from flask import Blueprint, request

from db import DB
from errors import ApiError, not_found, invalid_state, invalid_request
from errors import ERR_INVALID_DATE_RANGE, ERR_STALE_VERSION
from middleware import require_roles, json_body
from response import success_object, paginate
from services.common import (
    new_common, touch, require_string, require_enum, validate_date_string,
)
from services.attributes import apply_effective_dating

bp = Blueprint("attributes", __name__)

GROUPS = {"DEMOGRAPHIC", "SPECIALTY", "PRACTICE_ADDRESS", "CONTACT", "LICENSE"}


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _get_provider(pid):
    p = DB.providers.get(pid)
    if p is None:
        raise not_found()
    return p


def _get_attr(aid):
    a = DB.provider_attributes.get(aid)
    if a is None:
        raise not_found()
    return a


@bp.route("/pdm/providers/<pid>/attributes", methods=["POST"])
def add_attribute(pid):
    require_roles("DataSteward")
    p = _get_provider(pid)
    body = json_body()
    group = require_enum(body, "attribute_group", GROUPS)
    key = require_string(body, "attribute_key")
    value = require_string(body, "attribute_value")
    eff_s = require_string(body, "effective_date")
    validate_date_string(eff_s, "effective_date")
    term_s = body.get("term_date")
    if term_s is not None:
        validate_date_string(term_s, "term_date")
        if term_s <= eff_s:
            raise ApiError(ERR_INVALID_DATE_RANGE, 422, "term_date <= effective_date")
    attr = {
        **new_common(),
        "provider_id": pid,
        "attribute_group": group,
        "attribute_key": key,
        "attribute_value": value,
        "effective_date": eff_s,
        "term_date": term_s,
        "roster_source_id": None,
        "roster_row_id": None,
        "supersedes_attribute_id": None,
        "status": "PENDING",
    }
    DB.provider_attributes[attr["id"]] = attr
    apply_effective_dating(pid, attr)
    touch(p)
    return success_object(_public(attr), status=201)


@bp.route("/pdm/providers/<pid>/attributes", methods=["GET"])
def list_provider_attributes(pid):
    require_roles("DataSteward", "IntakeOperator", "DistributionOperator")
    _get_provider(pid)
    items = [a for a in DB.provider_attributes.values() if a["provider_id"] == pid]
    group = request.args.get("attribute_group")
    status = request.args.get("status")
    as_of = request.args.get("as_of_date")
    if group is not None:
        items = [a for a in items if a["attribute_group"] == group]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if as_of is not None:
        validate_date_string(as_of, "as_of_date")
        items = [
            a for a in items
            if a["effective_date"] <= as_of
            and (a.get("term_date") is None or as_of < a["term_date"])
        ]
    return paginate([_public(a) for a in items], request.args)


@bp.route("/pdm/provider-attributes/<aid>", methods=["GET"])
def get_attribute(aid):
    require_roles("DataSteward", "IntakeOperator")
    return success_object(_public(_get_attr(aid)))


@bp.route("/pdm/provider-attributes", methods=["GET"])
def list_attributes():
    require_roles("DataSteward", "IntakeOperator")
    items = list(DB.provider_attributes.values())
    pid = request.args.get("provider_id")
    rsid = request.args.get("roster_source_id")
    rrid = request.args.get("roster_row_id")
    supers = request.args.get("supersedes_attribute_id")
    status = request.args.get("status")
    if pid is not None:
        items = [a for a in items if a["provider_id"] == pid]
    if rsid is not None:
        items = [a for a in items if a.get("roster_source_id") == rsid]
    if rrid is not None:
        items = [a for a in items if a.get("roster_row_id") == rrid]
    if supers is not None:
        items = [a for a in items if a.get("supersedes_attribute_id") == supers]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paginate([_public(a) for a in items], request.args)


@bp.route("/pdm/provider-attributes/<aid>", methods=["PATCH"])
def patch_attribute(aid):
    require_roles("DataSteward")
    attr = _get_attr(aid)
    p = _get_provider(attr["provider_id"])
    body = json_body()
    allowed = {"attribute_value", "term_date"}
    for k in body:
        if k not in allowed:
            raise invalid_request(f"Field {k} is not mutable")
    if "term_date" in body:
        v = body["term_date"]
        if v is not None:
            validate_date_string(v, "term_date")
            if v <= attr["effective_date"]:
                raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                               "term_date <= effective_date")
        attr["term_date"] = v
    if "attribute_value" in body:
        v = body["attribute_value"]
        if not isinstance(v, str):
            raise invalid_request("attribute_value must be a string")
        attr["attribute_value"] = v
    touch(attr)
    # Re-run interval logic for the group.
    attr["status"] = "PENDING"
    apply_effective_dating(attr["provider_id"], attr)
    touch(p)
    return success_object(_public(attr))


@bp.route("/pdm/provider-attributes/<aid>/approve-retro", methods=["POST"])
def approve_retro(aid):
    require_roles("DataSteward")
    attr = _get_attr(aid)
    if attr["status"] != "RETRO_PENDING":
        raise invalid_state()
    p = _get_provider(attr["provider_id"])
    body = json_body()
    expected = body.get("expected_provider_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise invalid_request("expected_provider_version is required")
    if expected != p["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_provider_version does not match the provider's "
                       "current version")
    # Approve: re-run dating for the group, intervals may split.
    attr["status"] = "PENDING"
    touch(attr)
    # Bypass the retro guard by treating it as an approved insert: temporarily
    # mark as applying from its effective_date via the standard apply.
    _apply_approved(attr)
    touch(p)
    return success_object(_public(attr))


def _apply_approved(attr):
    """Apply an approved retro attribute to the timeline. The retro guard does
    not re-fire (steward approved); standard rewrite rules run."""
    from db import CLOCK
    today = CLOCK.today()
    pid = attr["provider_id"]
    group = attr["attribute_group"]
    key = attr["attribute_key"]
    if attr["effective_date"] > today:
        attr["status"] = "PENDING"
        touch(attr)
        return
    # Clear the retro guard by removing pre-existing earlier intervals from
    # consideration: reuse the apply machinery but skip the guard by calling
    # the rewrite directly with the guard disabled.
    import services.attributes as attrsvc
    existing = [
        a for a in DB.provider_attributes.values()
        if a["provider_id"] == pid
        and a["attribute_group"] == group
        and a["attribute_key"] == key
        and a["status"] == "ACTIVE"
        and a["id"] != attr["id"]
    ]
    attr["status"] = "ACTIVE"
    touch(attr)
    new_eff = attr["effective_date"]
    new_term = attr.get("term_date")
    for inc in list(existing):
        if not attrsvc._overlaps(attr, inc):
            continue
        inc_start = inc["effective_date"]
        inc_end = inc.get("term_date")
        inside_existing = (
            new_eff < today
            and inc_start < new_eff
            and (inc_end is None or new_eff < inc_end)
            and (new_term is not None and (inc_end is None or new_term < inc_end))
        )
        if inside_existing:
            right = {
                **new_common(),
                "provider_id": pid,
                "attribute_group": group,
                "attribute_key": key,
                "attribute_value": inc["attribute_value"],
                "effective_date": new_term,
                "term_date": inc_end,
                "roster_source_id": inc["roster_source_id"],
                "roster_row_id": inc.get("roster_row_id"),
                "supersedes_attribute_id": None,
                "status": "ACTIVE",
            }
            DB.provider_attributes[right["id"]] = right
            inc["term_date"] = new_eff
            touch(inc)
            continue
        if inc_start >= new_eff and (
            inc_end is None
            or (new_term is not None and inc_end <= new_term)
            or new_term is None
        ):
            inc["status"] = "SUPERSEDED"
            attr["supersedes_attribute_id"] = inc["id"]
            touch(inc)
            continue
        if inc_start < new_eff and (inc_end is None or inc_end > new_eff):
            inc["term_date"] = new_eff
            if inc["term_date"] is not None and inc["term_date"] <= inc["effective_date"]:
                inc["status"] = "SUPERSEDED"
                attr["supersedes_attribute_id"] = inc["id"]
            touch(inc)


@bp.route("/pdm/provider-attributes/<aid>/void", methods=["POST"])
def void_attribute(aid):
    require_roles("DataSteward")
    attr = _get_attr(aid)
    if attr["status"] != "RETRO_PENDING":
        raise invalid_state()
    attr["status"] = "VOIDED"
    touch(attr)
    return success_object(_public(attr))
