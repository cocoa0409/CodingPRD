"""Flask application entry point for the photovoltaic-ops API."""
import os

from pv_ops import create_app


def main() -> None:
    port = int(os.environ.get("PORT", "10000"))
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
