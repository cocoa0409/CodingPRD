"""HusbandryCase endpoints."""
from flask import Blueprint, request

from errors import invalid_request, invalid_state, not_found, raise_err
from middleware import require_roles, ANY_ROLE
from response import ok_list, ok_object
from services import domain
from services.serializers import serialize, serialize_many
from utils import new_entity, paginate, pagination_args, sort_created, touch

bp = Blueprint("husbandry_cases", __name__)

CASE_TYPES = {"MEDICAL", "REPATRIATION", "DESERTION", "OTHER"}
SEVERITIES = {"ROUTINE", "URGENT", "CRITICAL"}


def _get_or_404(hid):
    ent = domain.get("husbandry_cases", hid)
    if ent is None:
        not_found("husbandry case")
    return ent


@bp.post("/husbandry-cases")
def create_husbandry_case():
    require_roles(["HusbandryOfficer"])
    body = request.get_json(silent=True) or {}
    call = None
    pcid = body.get("port_call_id")
    if isinstance(pcid, str):
        call = domain.get("port_calls", pcid)
        if call is None:
            not_found("port call")
    crew = None
    ccid = body.get("crew_change_id")
    if ccid is not None:
        if isinstance(ccid, str):
            crew = domain.get("crew_changes", ccid)
            if crew is None:
                not_found("crew change")
        else:
            invalid_request("crew_change_id must be a string")
    if call is not None:
        domain.require_call_editable(call)
    if (call is None
            or body.get("case_type") not in CASE_TYPES
            or body.get("severity") not in SEVERITIES
            or not isinstance(body.get("summary"), str)):
        invalid_request("invalid husbandry case payload")
    ent = new_entity("husbandry_cases", {
        "port_call_id": pcid,
        "crew_change_id": ccid,
        "case_type": body["case_type"],
        "severity": body["severity"],
        "summary": body["summary"],
        "status": "OPEN",
        "departure_waiver_granted": False,
    })
    return ok_object(serialize(ent), status=201)


@bp.get("/husbandry-cases")
def list_husbandry_cases():
    require_roles(ANY_ROLE)
    items = list(domain.all_of("husbandry_cases"))
    for param in ("port_call_id", "crew_change_id", "status", "severity"):
        value = request.args.get(param)
        if value is not None:
            items = [h for h in items if h[param] == value]
    items = sort_created(items)
    limit, offset = pagination_args(request.args)
    page, total, has_more = paginate(items, limit, offset)
    return ok_list(serialize_many(page), total, limit, offset, has_more)


@bp.get("/husbandry-cases/<hid>")
def get_husbandry_case(hid):
    require_roles(ANY_ROLE)
    return ok_object(serialize(_get_or_404(hid)))


@bp.post("/husbandry-cases/<hid>/begin-treatment")
def begin_treatment(hid):
    require_roles(["HusbandryOfficer"])
    ent = _get_or_404(hid)
    if ent["status"] != "OPEN":
        invalid_state("Only an OPEN case can begin treatment")
    ent["status"] = "IN_TREATMENT"
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/husbandry-cases/<hid>/clear")
def clear(hid):
    require_roles(["HusbandryOfficer"])
    ent = _get_or_404(hid)
    if ent["status"] not in ("OPEN", "IN_TREATMENT"):
        invalid_state("Only an OPEN or IN_TREATMENT case can be cleared")
    ent["status"] = "CLEARED"
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/husbandry-cases/<hid>/repatriate")
def repatriate(hid):
    require_roles(["HusbandryOfficer"])
    ent = _get_or_404(hid)
    if ent["status"] not in ("OPEN", "IN_TREATMENT"):
        invalid_state("Only an OPEN or IN_TREATMENT case can be repatriated")
    if not ent["crew_change_id"]:
        raise_err("ERR_NO_LINKED_CREW_CHANGE", "Repatriation requires a linked crew change")
    ent["status"] = "REPATRIATED"
    touch(ent)
    crew = domain.get("crew_changes", ent["crew_change_id"])
    if crew is not None:
        domain.lazy_expire_crew(crew)
        if crew["status"] in ("DOCS_VERIFIED", "VISA_GRANTED", "SHORE_PASS_ISSUED"):
            crew["status"] = "REPATRIATED"
            touch(crew)
    return ok_object(serialize(ent))


@bp.post("/husbandry-cases/<hid>/waive-departure-hold")
def waive_departure_hold(hid):
    require_roles(["AgencyAdmin"])
    ent = _get_or_404(hid)
    ent["departure_waiver_granted"] = True
    touch(ent)
    return ok_object(serialize(ent))
