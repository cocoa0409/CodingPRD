import os

from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(err):
    return error_response("ERR_INVALID_REQUEST", 404, "Route not found")


@app.errorhandler(405)
def handle_405(err):
    return error_response("ERR_INVALID_REQUEST", 405, "Method not allowed")


@app.errorhandler(400)
def handle_400(err):
    return error_response("ERR_INVALID_REQUEST", 400, "Bad request")


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response("ERR_INVALID_REQUEST", 500, str(err))


from routes.clock import bp as clock_bp
from routes.assets import bp as assets_bp
from routes.broadcasters import bp as broadcasters_bp
from routes.packages import bp as packages_bp
from routes.bids import bp as bids_bp
from routes.deals import bp as deals_bp
from routes.payment_milestones import bp as milestones_bp
from routes.production import bp as production_bp
from routes.sublicense import bp as sublicense_bp
from routes.renewals import bp as renewals_bp

app.register_blueprint(clock_bp)
app.register_blueprint(assets_bp)
app.register_blueprint(broadcasters_bp)
app.register_blueprint(packages_bp)
app.register_blueprint(bids_bp)
app.register_blueprint(deals_bp)
app.register_blueprint(milestones_bp)
app.register_blueprint(production_bp)
app.register_blueprint(sublicense_bp)
app.register_blueprint(renewals_bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
