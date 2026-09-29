"""Technicians: registration and the certification action with its two cascades."""

import lookup
import response
import validate
from db import base_row, bump, by_key, db
from errors import (ERR_DISTRIBUTOR_NOT_AUTHORIZED, ERR_DUPLICATE_RESOURCE_CODE,
                    ERR_INVALID_REQUEST, ERR_TECHNICIAN_STATE_INVALID, fail)
from middleware import (CHANNEL_MANAGER, DISTRIBUTOR, PLANT_MANAGER,
                        QUALITY_INSPECTOR, TECHNICIAN, TRAINING_ADMINISTRATOR,
                        WARRANTY_ANALYST, endpoint)
from services.cascades import regrant_cascade, revocation_cascade
from validate import CERT_SCOPES

EMPLOYERS = ["FACTORY", "DISTRIBUTOR"]
CERT_STATES = ["UNCERTIFIED", "ACTIVE", "EXPIRED", "REVOKED"]

GRANT_FROM = ("UNCERTIFIED", "EXPIRED", "REVOKED")
RENEW_FROM = ("ACTIVE", "EXPIRED")


def register(app):
    @app.post("/clm/technicians")
    @endpoint([TRAINING_ADMINISTRATOR])
    def create_technician():
        body = validate.parse_body()
        employee_code = body.code("employee_code")
        full_name = body.string("full_name", 1, 120)
        employer = body.enum("employer", EMPLOYERS)
        distributor_id = body.id_ref("distributor_id", required=False)
        if employer == "DISTRIBUTOR" and distributor_id is None:
            fail(ERR_INVALID_REQUEST,
                 "distributor_id is required when employer is DISTRIBUTOR.")
        if employer == "FACTORY" and distributor_id is not None:
            fail(ERR_INVALID_REQUEST,
                 "distributor_id must be null when employer is FACTORY.")
        # rule 21: the employing distributor must resolve
        if distributor_id is not None:
            lookup.distributor(distributor_id)
        # rule 48: natural-key uniqueness
        if any(t["employee_code"] == employee_code for t in db.technicians.values()):
            fail(ERR_DUPLICATE_RESOURCE_CODE,
                 "employee_code '%s' already exists." % employee_code)

        row = base_row()
        row.update({
            "employee_code": employee_code,
            "full_name": full_name,
            "employer": employer,
            "distributor_id": distributor_id,
            "cert_scopes": [],
            "cert_state": "UNCERTIFIED",
            "cert_expires_on": None,
            "last_cert_action_at": None,
            "revocation_count": 0,
        })
        db.technicians[row["id"]] = row
        return response.created(row)

    @app.get("/clm/technicians/<technician_id>")
    @endpoint([TRAINING_ADMINISTRATOR, PLANT_MANAGER, CHANNEL_MANAGER,
               WARRANTY_ANALYST, TECHNICIAN, QUALITY_INSPECTOR, DISTRIBUTOR])
    def read_technician(technician_id):
        return response.ok(lookup.technician(technician_id))

    @app.get("/clm/technicians")
    @endpoint([TRAINING_ADMINISTRATOR, PLANT_MANAGER, CHANNEL_MANAGER,
               WARRANTY_ANALYST, DISTRIBUTOR])
    def list_technicians():
        limit, offset = validate.q_pagination()
        distributor_id = validate.q_str("distributor_id")
        cert_state = validate.q_enum("cert_state", CERT_STATES)
        employer = validate.q_enum("employer", EMPLOYERS)
        rows = list(db.technicians.values())
        if distributor_id is not None:
            rows = [r for r in rows if r["distributor_id"] == distributor_id]
        if cert_state is not None:
            rows = [r for r in rows if r["cert_state"] == cert_state]
        if employer is not None:
            rows = [r for r in rows if r["employer"] == employer]
        rows = by_key(rows, "employee_code")
        page, total = validate.paginate(rows, limit, offset)
        return response.listing(page, limit, offset, total)

    @app.post("/clm/technicians/<technician_id>/certification-actions")
    @endpoint([TRAINING_ADMINISTRATOR])
    def technician_certification_action(technician_id):
        body = validate.parse_body()
        action = body.enum("action", ["GRANT", "RENEW", "REVOKE"])
        scopes = None
        expires_on = None
        if action in ("GRANT", "RENEW"):
            scopes = body.enum_array("scopes", CERT_SCOPES)
            expires_on = body.instant("expires_on")
            # the system refuses to issue a certification that is already stale
            if expires_on <= db.now:
                fail(ERR_INVALID_REQUEST,
                     "expires_on must be strictly after the current logical clock.")
        else:
            body.string("reason", maxlen=500)

        technician = lookup.technician(technician_id)
        # rule 28: the technician's cert_state permits the action
        state = technician["cert_state"]
        if action == "GRANT" and state not in GRANT_FROM:
            fail(ERR_TECHNICIAN_STATE_INVALID,
                 "A grant requires cert_state UNCERTIFIED, EXPIRED or REVOKED.")
        if action == "RENEW" and state not in RENEW_FROM:
            fail(ERR_TECHNICIAN_STATE_INVALID,
                 "A renewal requires cert_state ACTIVE or EXPIRED.")
        if action == "REVOKE" and state != "ACTIVE":
            fail(ERR_TECHNICIAN_STATE_INVALID, "A revocation requires cert_state ACTIVE.")
        # rule 54: a grant for a distributor-employed technician needs standing
        if action == "GRANT" and technician["employer"] == "DISTRIBUTOR":
            employer = db.distributors.get(technician["distributor_id"])
            if employer is None or employer["distributor_state"] not in (
                    "AUTHORIZED", "PROBATION"):
                fail(ERR_DISTRIBUTOR_NOT_AUTHORIZED,
                     "The employing distributor must be AUTHORIZED or on PROBATION.")

        if action == "REVOKE":
            technician["cert_state"] = "REVOKED"
            technician["cert_scopes"] = []
            technician["revocation_count"] = technician["revocation_count"] + 1
            technician["last_cert_action_at"] = db.now
            bump(technician)
            revocation_cascade(technician)
            return response.ok(technician)

        was_revoked = state == "REVOKED"
        technician["cert_state"] = "ACTIVE"
        technician["cert_scopes"] = scopes
        technician["cert_expires_on"] = expires_on
        technician["last_cert_action_at"] = db.now
        bump(technician)
        if action == "GRANT" and was_revoked:
            regrant_cascade()
        return response.ok(technician)
