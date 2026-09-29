"""Responsible-person designees."""

from flask import Blueprint

import access
import domain
import envelope
import schema
import store
from access import Checks, Ctx

bp = Blueprint("persons", __name__)


@bp.post("/cosmetics/responsible-persons")
def create_responsible_person():
    access.authorize("ResponsiblePersonAgent")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()

    def validate():
        payload = body if body is not None else {}
        ctx.legal_name = schema.string_field(payload, "legal_name", max_len=200)
        ctx.address = schema.string_field(payload, "us_address_line", max_len=300)
        ctx.phone = schema.string_field(payload, "contact_phone", min_len=7, max_len=32)
        ctx.email = schema.email_field(payload, "contact_email")
        ctx.cap = schema.int_field(payload, "designation_cap", required=False, minimum=1,
                                   maximum=500, default=domain.DESIGNATION_CAP_DEFAULT)

    checks.add(access.R_INVALID, validate)
    checks.run()

    rp = store.insert("responsible_persons", {
        "legal_name": ctx.legal_name,
        "us_address_line": ctx.address,
        "contact_phone": ctx.phone,
        "contact_email": ctx.email,
        "designation_cap": ctx.cap,
    })
    return envelope.created(domain.responsible_person_json(rp))


@bp.get("/cosmetics/responsible-persons/<rid>")
def get_responsible_person(rid):
    auth = access.authorize("ResponsiblePersonAgent", "RegulatoryReviewer", "EnforcementOfficer",
                            "SystemOperator")
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_RESPONSIBLE_PERSON,
               lambda: ctx.set("rp", access.need_responsible_person(rid)))
    checks.add(access.R_OWNER,
               lambda: access.check_owner(auth, responsible_person_id=ctx.rp["id"]))
    checks.run()
    return envelope.ok(domain.responsible_person_json(ctx.rp))
