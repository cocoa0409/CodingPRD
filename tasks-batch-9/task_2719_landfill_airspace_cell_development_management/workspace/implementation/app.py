"""Entry point: the Flask app, route registration and the error envelope.

Storage is in-memory only and starts completely empty on every boot: no seeding,
no preloaded entities, no file or /tmp cache. The test harness relaunches this
process through start.sh before every individual test.
"""
import os

from flask import Flask

from core import ApiError, error_body
import routes_site
import routes_liner
import routes_ops
import routes_env
import routes_gas
import routes_finance

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

for module in (routes_site, routes_liner, routes_ops, routes_env, routes_gas,
               routes_finance):
    module.register(app)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_body(exc.error_id, exc.message), exc.http_status


@app.errorhandler(404)
def handle_not_found(exc):
    return error_body("ERR_NOT_FOUND", "No route matches this request path."), 404


@app.errorhandler(405)
def handle_method_not_allowed(exc):
    return error_body("ERR_NOT_FOUND",
                      "This method is not allowed on this path."), 405


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return error_body("ERR_INVALID_REQUEST", "Unhandled request: %s" % exc), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
