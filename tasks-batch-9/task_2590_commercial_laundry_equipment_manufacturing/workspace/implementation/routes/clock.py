"""The logical clock and its two ordered sweeps (PRD 2.5)."""

import response
import validate
from db import bump, db, order_created_asc
from middleware import OPERATOR_ROLES, endpoint


def register(app):
    @app.post("/_clock/set_current_utc")
    @endpoint(OPERATOR_ROLES)
    def set_current_utc():
        body = validate.parse_body()
        to_iso8601 = body.instant("to_iso8601")
        db.now = to_iso8601

        # sweep 1: technician certification lapse
        expired = 0
        for technician in order_created_asc(db.technicians.values()):
            if technician["cert_state"] != "ACTIVE":
                continue
            expires_on = technician["cert_expires_on"]
            if expires_on is None or expires_on > db.now:
                continue
            technician["cert_state"] = "EXPIRED"
            technician["cert_scopes"] = []
            bump(technician)
            expired += 1

        # sweep 2: rebate program retirement (strictly past the final day)
        retired = 0
        for program in order_created_asc(db.programs.values()):
            if program["program_state"] != "ACTIVE":
                continue
            if program["effective_to"].date() >= db.now.date():
                continue
            program["program_state"] = "RETIRED"
            bump(program)
            retired += 1

        return response.ok({
            "current_utc": db.now,
            "expired_technician_count": expired,
            "retired_program_count": retired,
        })
