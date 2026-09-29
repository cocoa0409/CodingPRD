"""ScriptDrop prescription last-mile delivery API.

Boots a completely empty in-memory store on every process start: no seeding, no
persistence, no disk state of any kind.
"""

import os

from flask import Flask

import middleware
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
    middleware.install(app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
