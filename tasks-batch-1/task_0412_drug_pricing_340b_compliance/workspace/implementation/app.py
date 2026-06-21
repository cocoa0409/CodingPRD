"""340B Drug Pricing & Compliance API — Flask entry point.

In-memory storage only; no seeding at startup. The store starts empty and is
rebuilt from scratch on every process boot.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response

from routes.covered_entities import bp as covered_entities_bp
from routes.people import bp as people_bp
from routes.drug_products import bp as drug_products_bp
from routes.contract_pharmacies import bp as contract_pharmacies_bp
from routes.accumulators import bp as accumulators_bp
from routes.dispenses import bp as dispenses_bp
from routes.audit_findings import bp as audit_findings_bp
from routes.repayments import bp as repayments_bp
from routes.purchase_orders import bp as purchase_orders_bp

API_PREFIX = "/340b"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        covered_entities_bp,
        people_bp,
        drug_products_bp,
        contract_pharmacies_bp,
        accumulators_bp,
        dispenses_bp,
        audit_findings_bp,
        repayments_bp,
        purchase_orders_bp,
    ):
        app.register_blueprint(bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        body = error_response(e.error_id, e.message)
        return jsonify(body), e.http_status

    @app.errorhandler(404)
    def handle_404(e):
        body = error_response("ERR_NOT_FOUND", "Resource not found")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(e):
        body = error_response("ERR_NOT_FOUND", "Method not allowed")
        return jsonify(body), 404

    @app.errorhandler(400)
    def handle_400(e):
        body = error_response("ERR_INVALID_REQUEST", "Bad request")
        return jsonify(body), 422

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Surface unexpected errors as a generic invalid-request rather than a
        # bare 500 HTML page, but re-raise ApiError handled above.
        if isinstance(e, ApiError):
            return handle_api_error(e)
        body = error_response("ERR_INVALID_REQUEST", "Internal error: %s" % str(e))
        return jsonify(body), 422

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
