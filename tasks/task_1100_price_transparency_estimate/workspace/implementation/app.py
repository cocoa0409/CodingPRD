"""Price Transparency & Cost Estimate API — application entry point."""
import os
from flask import Flask

from web import register_error_handlers
from routes import bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_error_handlers(app)
    app.register_blueprint(bp)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
