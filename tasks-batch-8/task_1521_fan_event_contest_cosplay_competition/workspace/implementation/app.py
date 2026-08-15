"""Fan Contest Cosplay Ops API — Flask entry point.

All state lives in process memory (db.DB); no files, no sqlite, no /tmp.
Re-launching start.sh wipes all state. Nothing is seeded at startup.
"""

import os
import sys

from flask import Flask, jsonify

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from errors import ApiError, err_not_found
from response import error as error_response
from response import success

from routes.contest_events import bp as contest_events_bp
from routes.categories import bp as categories_bp
from routes.contestants import bp as contestants_bp
from routes.judges import bp as judges_bp
from routes.entries import bp as entries_bp
from routes.prejudging_slots import bp as prejudging_slots_bp
from routes.scoresheets import bp as scoresheets_bp
from routes.performance_slots import bp as performance_slots_bp
from routes.prize_awards import bp as prize_awards_bp
from routes.green_room_bookings import bp as green_room_bookings_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(contest_events_bp)
    app.register_blueprint(categories_bp)
    app.register_blueprint(contestants_bp)
    app.register_blueprint(judges_bp)
    app.register_blueprint(entries_bp)
    app.register_blueprint(prejudging_slots_bp)
    app.register_blueprint(scoresheets_bp)
    app.register_blueprint(performance_slots_bp)
    app.register_blueprint(prize_awards_bp)
    app.register_blueprint(green_room_bookings_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_):
        e = err_not_found("Route not found")
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(405)
    def handle_405(_):
        e = err_not_found("Method not allowed")
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", str(exc), 500)

    @app.route("/healthz", methods=["GET"])
    def healthz():
        return success({"status": "ok"})

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
