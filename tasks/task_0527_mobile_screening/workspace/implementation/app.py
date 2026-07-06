import os
from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.roster import bp as roster_bp
from routes.sponsors import bp as sponsors_bp
from routes.events import bp as events_bp
from routes.participants import bp as participants_bp
from routes.appointments import bp as appointments_bp
from routes.referrals import bp as referrals_bp
from routes.charges import bp as charges_bp
from routes.reminders import bp as reminders_bp
from routes.clock_route import bp as clock_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

for bp in (clock_bp, roster_bp, sponsors_bp, events_bp, participants_bp,
           appointments_bp, referrals_bp, charges_bp, reminders_bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, HTTPException):
        return error_response("ERR_NOT_FOUND", e.code if e.code else 500, str(e))
    return error_response("ERR_INVALID_REQUEST", 400, "Bad request: %s" % e)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
