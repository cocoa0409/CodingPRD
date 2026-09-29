"""The logical clock and the daily sweep."""

import response
from db import clock
from middleware import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PROGRAM_DIRECTOR,
    authenticate,
    body,
    datetime_field,
)
from services import domain


def register(app):
    @app.post("/_clock/set_current_utc")
    def set_clock():
        # Exempt from role checking entirely (PRD 2.1).
        data = body()
        moment = datetime_field(data, "current_utc")
        clock.set(moment)
        return response.obj({"current_utc": response.iso(clock.now)})

    @app.post("/operations/daily-sweep")
    def run_daily_sweep():
        authenticate(ROLE_PROGRAM_DIRECTOR, ROLE_COMPLIANCE_OFFICER)
        return response.obj(domain.daily_sweep())
