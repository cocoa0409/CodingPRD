import os

from flask import Flask, g

import auth
import response
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.before_request
def _before():
    if g.get("_skip_auth", False):
        return None
    auth.authenticate()
    return None


@app.errorhandler(ApiError)
def _api_error(e):
    return response.error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def _not_found(e):
    return response.error("ERR_VALIDATION", "No such route", 404)


@app.errorhandler(405)
def _bad_method(e):
    return response.error("ERR_VALIDATION", "Method not allowed", 405)


@app.errorhandler(Exception)
def _unhandled(e):
    if isinstance(e, ApiError):
        return response.error(e.error_id, e.message, e.http_status)
    app.logger.exception("unhandled")
    return response.error("ERR_VALIDATION", "Internal error: %s" % e, 400)


def register_all():
    from routes import admin, parties, fiber, pulp, machines, runs, rolls, orders, env, steam
    for mod in (admin, parties, fiber, pulp, machines, runs, rolls, orders, env, steam):
        app.register_blueprint(mod.bp)


register_all()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
