"""Entry point: Flask app, error handlers, blueprint registration."""

import os
from flask import Flask

import errors
from errors import ApiError
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes.clock import bp as clock_bp
    from routes.brand_owners import bp as brand_owners_bp
    from routes.suppliers import bp as suppliers_bp
    from routes.ingredients import bp as ingredients_bp
    from routes.supplier_ingredient_approvals import bp as sia_bp
    from routes.formulas import bp as formulas_bp
    from routes.nutrient_profiles import bp as profiles_bp
    from routes.feeding_trials import bp as trials_bp
    from routes.production_batches import bp as batches_bp
    from routes.lots import bp as lots_bp
    from routes.lab_ga import bp as lab_ga_bp
    from routes.state_registrations import bp as regs_bp
    from routes.complaint_cases import bp as complaints_bp
    from routes.recall_actions import bp as recalls_bp

    prefix = "/petfood"
    for bp in (clock_bp, brand_owners_bp, suppliers_bp, ingredients_bp, sia_bp,
               formulas_bp, profiles_bp, trials_bp, batches_bp, lots_bp,
               lab_ga_bp, regs_bp, complaints_bp, recalls_bp):
        app.register_blueprint(bp, url_prefix=prefix)

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_e):
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(_e):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):
        # Unexpected errors surface as ERR_INVALID_REQUEST 500-level fallback;
        # but keep response envelope shape.
        return error_response(errors.ERR_INVALID_REQUEST,
                              f"Internal error: {exc}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
