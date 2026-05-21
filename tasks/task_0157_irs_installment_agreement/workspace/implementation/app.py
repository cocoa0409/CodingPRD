"""Entry point: creates Flask app and serves it on PORT (default 10000), bound to 0.0.0.0."""
import os

from app import create_app

app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
