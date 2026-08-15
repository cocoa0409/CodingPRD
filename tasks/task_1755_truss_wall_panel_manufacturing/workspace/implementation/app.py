"""Entry point: Flask app, error handlers, route registration.

Storage is in-memory only (module-level dicts in db.py). Nothing is seeded at
startup; the store starts empty on every boot.
"""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from response import error as error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.customers import bp as customers_bp
    from routes.master_data import bp as master_data_bp
    from routes.jobs import bp as jobs_bp
    from routes.designs import bp as designs_bp
    from routes.cutlists import bp as cutlists_bp
    from routes.inventory import bp as inventory_bp
    from routes.batches import bp as batches_bp
    from routes.loads import bp as loads_bp
    from routes.claims import bp as claims_bp
    from routes.changeorders import bp as changeorders_bp
    from routes.clock import bp as clock_bp

    for bp in (customers_bp, master_data_bp, jobs_bp, designs_bp, cutlists_bp,
               inventory_bp, batches_bp, loads_bp, claims_bp, changeorders_bp, clock_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.status, err.message)

    @app.errorhandler(404)
    def handle_404(_err):
        return error_response(ERR_NOT_FOUND, 404, "resource not found")

    @app.errorhandler(405)
    def handle_405(_err):
        return error_response(ERR_NOT_FOUND, 404, "resource not found")

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
