"""Entry point: Flask app assembly, error handlers, route registration."""
import os

from flask import Flask, jsonify

from coatings.errors import ApiError
from coatings.util import error_body
from coatings import (
    views_batches,
    views_catalog,
    views_claims,
    views_color_matches,
    views_containers,
    views_customers,
    views_disposals,
    views_formulas,
    views_mills,
    views_ops,
    views_orders,
    views_voc_rules,
)

app = Flask(__name__)

for module in (
    views_customers,
    views_catalog,
    views_formulas,
    views_voc_rules,
    views_mills,
    views_batches,
    views_color_matches,
    views_containers,
    views_orders,
    views_claims,
    views_disposals,
    views_ops,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify(error_body(err.error_id, err.message)), err.status


@app.errorhandler(404)
def handle_404(err):
    return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404


@app.errorhandler(405)
def handle_405(err):
    return jsonify(error_body("ERR_NOT_FOUND", "Method not allowed")), 405


@app.errorhandler(Exception)
def handle_unexpected(err):
    return jsonify(error_body("ERR_INTERNAL", str(err))), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
