"""Public Refrigerated Warehousing API — entry point.

In-memory Flask server. State lives in core.DB dicts and starts empty on every
boot; nothing is seeded or persisted. Listens on 0.0.0.0:$PORT (default 10000).
"""

import os

from flask import Flask

from core import register_error_handlers
import routes_a
import routes_b
import routes_c


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    register_error_handlers(app)
    app.register_blueprint(routes_a.bp)
    app.register_blueprint(routes_b.bp)
    app.register_blueprint(routes_c.bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
