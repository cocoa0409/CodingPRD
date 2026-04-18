import os
from flask import Flask
from errors import register_error_handlers
from routes import register_all


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    register_error_handlers(app)
    register_all(app)
    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
