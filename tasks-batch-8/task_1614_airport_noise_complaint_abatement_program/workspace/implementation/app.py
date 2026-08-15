"""Airport Noise Complaint & Abatement Program API — entry point."""
import os

from flask import Flask

from errors import ApiError
from response import error_response, success_object

from routes.complainants import bp as complainants_bp
from routes.complaints import bp as complaints_bp
from routes.flights import bp as flights_bp
from routes.monitors import bp as monitors_bp
from routes.events import bp as events_bp
from routes.curfew import bp as curfew_bp
from routes.notifications import bp as notifications_bp
from routes.studies import bp as studies_bp
from routes.funds import bp as funds_bp
from routes.outreach import bp as outreach_bp
from routes.reports import bp as reports_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

for bp in (complainants_bp, complaints_bp, flights_bp, monitors_bp, events_bp,
           curfew_bp, notifications_bp, studies_bp, funds_bp, outreach_bp):
    app.register_blueprint(bp, url_prefix="/noise-program")
# reports blueprint also carries the /_clock endpoints, so register without prefix
app.register_blueprint(reports_bp)
# ...and under the program prefix for the report/zone routes
app.register_blueprint(reports_bp, url_prefix="/noise-program",
                       name="reports_np")


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    from errors import err
    return error_response(err("ERR_NOT_FOUND", "Resource not found"))


@app.errorhandler(405)
def handle_405(e):
    from errors import err
    return error_response(err("ERR_NOT_FOUND", "Resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e)
    import traceback
    traceback.print_exc()
    from errors import err
    return error_response(err("ERR_VALIDATION", f"Unexpected error: {e}"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
