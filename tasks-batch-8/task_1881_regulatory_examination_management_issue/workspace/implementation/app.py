"""Regulatory Exam Management API — entry point, error handlers, blueprint
registration. Listens on 0.0.0.0:$PORT (default 10000)."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import (ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND)
from response import err

import routes_admin
import routes_evidence
import routes_exams
import routes_fieldwork
import routes_remediation
import routes_reports


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for module in (routes_admin, routes_exams, routes_fieldwork,
                   routes_remediation, routes_evidence, routes_reports):
        app.register_blueprint(module.bp)

    for rule in app.url_map.iter_rules():
        rule.strict_slashes = False

    @app.errorhandler(ApiError)
    def _handle_api(e):
        return err(e.error_id, e.status, e.message)

    @app.errorhandler(404)
    def _handle_404(e):
        return err(ERR_NOT_FOUND, 404, "resource not found")

    @app.errorhandler(405)
    def _handle_405(e):
        return err(ERR_NOT_FOUND, 404, "resource not found")

    @app.errorhandler(Exception)
    def _handle_generic(e):
        if isinstance(e, ApiError):
            return err(e.error_id, e.status, e.message)
        if isinstance(e, HTTPException):
            if e.code == 404:
                return err(ERR_NOT_FOUND, 404, "resource not found")
            if e.code is not None and e.code < 500:
                return err(ERR_INVALID_REQUEST, e.code, e.description)
            return err("ERR_INTERNAL", 500, e.description)
        return err("ERR_INTERNAL", 500, "internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
