"""Entry point for the FX Risk Control API server."""
import os

from app import create_app


def main() -> None:
    port = int(os.environ.get("PORT", "10000"))
    application = create_app()
    application.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
