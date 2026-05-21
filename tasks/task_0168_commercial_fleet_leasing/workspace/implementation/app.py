"""Application entry point — boots a Flask app listening on $PORT (default 10000)."""
import os

from server import create_app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
