import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_audits
import routes_claims
import routes_drugs
import routes_formulary
import routes_members
import routes_pas
import routes_pharmacies
import routes_plans
from errors import ApiError
from response import err

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

for module in (
    routes_plans,
    routes_drugs,
    routes_formulary,
    routes_pharmacies,
    routes_members,
    routes_pas,
    routes_claims,
    routes_audits,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err(e.error_id, e.message, e.status)


@app.errorhandler(HTTPException)
def handle_http_error(e):
    if e.code == 405:
        return err("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)
    return err("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    return err("ERR_INTERNAL", "Internal server error", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
