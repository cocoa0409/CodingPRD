import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from helpers import error_response

from routes.clock_routes import bp as clock_bp
from routes.program_routes import bp as program_bp
from routes.account_routes import bp as account_bp
from routes.election_routes import bp as election_bp
from routes.transaction_routes import bp as transaction_bp
from routes.batch_routes import bp as batch_bp
from routes.fee_routes import bp as fee_bp
from routes.waiver_routes import bp as waiver_bp
from routes.notice_routes import bp as notice_bp
from routes.offer_routes import bp as offer_bp
from routes.report_routes import bp as report_bp

app = Flask(__name__)

for bp in (clock_bp, program_bp, account_bp, election_bp, transaction_bp,
           batch_bp, fee_bp, waiver_bp, notice_bp, offer_bp, report_bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return error_response(ApiError(ERR_NOT_FOUND, 404, "Method not allowed"))


@app.errorhandler(400)
def handle_400(e):
    return error_response(ApiError(ERR_INVALID_REQUEST, 400, "Malformed request"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    return error_response(ApiError("ERR_INTERNAL", 500, str(e)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
