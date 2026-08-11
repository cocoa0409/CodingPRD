"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import (charities, clock, credits, dropboxes, funds, kits, partners,
                    periods, pickups, reports, residents, tickets, zones)

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

for module in (zones, residents, kits, pickups, partners, dropboxes, tickets,
               reports, credits, funds, charities, periods, clock):
    app.register_blueprint(module.bp)


@app.errorhandler(404)
def not_found(_e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def method_not_allowed(_e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def unhandled(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(ApiError("ERR_INTERNAL", 500, "Internal error: %s" % e))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
