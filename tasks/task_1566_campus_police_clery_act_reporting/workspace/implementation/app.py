"""Campus Police Clery Act Reporting API — entry point."""

import os
import traceback

from flask import Flask, jsonify

from core import (ApiError, clock, error_response, get_body, parse_dt,
                  req_str, require_roles, success)

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def _handle_404(e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def _handle_405(e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def _handle_generic(e):
    traceback.print_exc()
    return error_response(ApiError("ERR_INTERNAL", 500, str(e)))


@app.get("/")
def _root():
    return jsonify({"status": "ok"}), 200


@app.post("/_clock/set_current_utc")
@require_roles("SystemAdmin")
def set_clock():
    data = get_body()
    raw = req_str(data, "to_iso8601")
    dt = parse_dt(raw)
    clock.current = dt
    return success({"current_utc": raw}, 200)


from routes import register_blueprints  # noqa: E402

register_blueprints(app)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
