"""Online Consultation API — Flask entry point."""

import os

from flask import Flask


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    # Don't redirect /foo/ -> /foo (lets test paths match exactly).
    app.url_map.strict_slashes = False

    from routes import register_routes
    register_routes(app)
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
