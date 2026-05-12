"""Government One-Stop Approval Platform — Flask entry point."""

import os

from flask import Flask


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    from routes import register_routes
    register_routes(app)
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    application = create_app()
    application.run(host="0.0.0.0", port=port, debug=False, threaded=True)
