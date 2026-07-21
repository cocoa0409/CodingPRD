import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from common import ApiError, error_response, _meta

from routes.tenants import bp as tenants_bp
from routes.landlords import bp as landlords_bp
from routes.plans import bp as plans_bp
from routes.scores import bp as scores_bp
from routes.clock import bp as clock_bp
from routes.enrollments import bp as enrollments_bp
from routes.leases import bp as leases_bp
from routes.rent_payments import bp as rent_payments_bp
from routes.reported_items import bp as reported_items_bp
from routes.disputes import bp as disputes_bp
from routes.back_reports import bp as back_reports_bp
from routes.invoices import bp as invoices_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (tenants_bp, landlords_bp, plans_bp, scores_bp, clock_bp,
               enrollments_bp, leases_bp, rent_payments_bp, reported_items_bp,
               disputes_bp, back_reports_bp, invoices_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_HTTP_" + str(err.code), "message": err.name},
        }
        return jsonify(body), err.code

    @app.errorhandler(Exception)
    def handle_uncaught(err):
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(err)},
        }
        return jsonify(body), 500

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
