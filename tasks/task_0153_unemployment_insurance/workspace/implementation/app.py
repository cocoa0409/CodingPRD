"""Entry point for the Unemployment Insurance API server."""
import os

from app import create_app


def main() -> None:
    flask_app = create_app()
    port = int(os.environ.get("PORT", "10000"))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
