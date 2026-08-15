import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import err


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes_core
    import routes_doors
    import routes_people
    import routes_groups
    import routes_incidents
    import routes_campaigns
    import routes_charges

    for mod in (routes_core, routes_doors, routes_people, routes_groups,
                routes_incidents, routes_campaigns, routes_charges):
        app.register_blueprint(mod.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err(e.error_id, e.message, e.status)

    @app.errorhandler(404)
    def handle_404(e):
        return err(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return err(ERR_INVALID_REQUEST, "Method not allowed", 405)

    @app.errorhandler(500)
    def handle_500(e):
        return err(ERR_INVALID_REQUEST, "Internal error: %s" % e, 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
