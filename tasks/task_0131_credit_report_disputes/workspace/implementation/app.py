"""Entry point: creates the Flask app and starts the HTTP server."""
import os

from server import create_app


def main() -> None:
    app = create_app()
    port = int(os.environ.get("PORT", "10000"))
    # Bind to 0.0.0.0 so containerized clients can reach us.
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
