"""Entry point: starts the Flask app on PORT env var, bound to 0.0.0.0."""
import os

from app import create_app


def main() -> None:
    port = int(os.environ.get("PORT", "10000"))
    application = create_app()
    application.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
