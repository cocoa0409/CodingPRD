"""PartnerCompany routes (PRD 3.1)."""

from flask import Blueprint

from db import store
from middleware import require_roles
from response import ok_object
from routes.common import get_or_404, list_response
from util import json_body, new_record, req_enum, req_str, to_public, touch

bp = Blueprint("partner_companies", __name__)

PARTNER_KINDS = ("CO_PRODUCER", "RENTER")
STANDINGS = ("GOOD", "WATCH", "BARRED")


@bp.post("/opera/partner-companies")
def create_partner_company():
    require_roles("PlatformAdmin")
    body = json_body()
    name = req_str(body, "name")
    kind = req_enum(body, "partner_kind", PARTNER_KINDS)
    rec = new_record(name=name, partner_kind=kind, standing="GOOD")
    store.partner_companies[rec["id"]] = rec
    return ok_object(to_public(rec), 201)


@bp.get("/opera/partner-companies")
def list_partner_companies():
    require_roles("Any")
    return list_response(
        store.partner_companies.values(),
        [("partner_kind", "partner_kind"), ("standing", "standing")],
    )


@bp.get("/opera/partner-companies/<cid>")
def get_partner_company(cid):
    require_roles("Any")
    return ok_object(to_public(get_or_404(store.partner_companies, cid, "PartnerCompany")))


@bp.post("/opera/partner-companies/<cid>/transition")
def transition_partner_company(cid):
    require_roles("PlatformAdmin")
    body = json_body()
    to_state = req_enum(body, "to_state", STANDINGS)
    rec = get_or_404(store.partner_companies, cid, "PartnerCompany")
    # Standing is a free administrative flag: all three values are reachable
    # from any other (PRD 3.1), including a same-value resubmission.
    rec["standing"] = to_state
    touch(rec)
    return ok_object(to_public(rec))
