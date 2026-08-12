"""Block Party Street Closure API — entry point, error handlers, route wiring."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import err_body
from errors import ApiError

import routes_admin
import routes_petitions
import routes_applications
import routes_plans
import routes_insurance
import routes_equipment
import routes_money
import routes_reports


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for mod in (routes_admin, routes_petitions, routes_applications, routes_plans,
                routes_insurance, routes_equipment, routes_money, routes_reports):
        app.register_blueprint(mod.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err_body(e.error_id, e.message), e.status

    @app.errorhandler(HTTPException)
    def handle_http_error(e):
        eid = 'ERR_NOT_FOUND' if e.code == 404 else 'ERR_INVALID_REQUEST'
        msg = 'Resource not found' if e.code == 404 else (e.description or 'Bad request')
        return err_body(eid, msg), (e.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return err_body('ERR_INTERNAL', 'Internal server error: %s' % e), 500

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')), threaded=True)
