"""Entry point: Flask app, error handlers, route registration (INSTRUCTION.md)."""
import os

from flask import Flask

from clock import CLOCK, iso_from_dt
from errors import ApiError, invalid
from middleware import require_roles
from response import error_response, success
from services.cascade import sweep_clock
from services.common import parse_body

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError("ERR_NOT_FOUND", "Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError("ERR_NOT_FOUND", "Resource not found"))


@app.errorhandler(500)
def handle_500(err):
    return error_response(ApiError("ERR_INVALID_REQUEST", "Internal error"))


@app.post("/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_current_utc():
    body = parse_body()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise invalid("Missing required field: to_iso8601")
    from services.common import parse_iso_datetime

    now = parse_iso_datetime(body["to_iso8601"], "to_iso8601")
    CLOCK.set(now)
    sweep_clock(now)
    return success({"now": iso_from_dt(now)})


from services import (awards, challenges, employees, employers, enrollments,
                      events, hras, invoices, participations, programs,
                      referrals, reports, screenings)

for module in (awards, challenges, employees, employers, enrollments, events,
               hras, invoices, participations, programs, referrals, reports,
               screenings):
    app.register_blueprint(module.bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
