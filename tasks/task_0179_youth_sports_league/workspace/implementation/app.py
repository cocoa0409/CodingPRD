"""Entry point for the Youth Sports League API server."""
import os

from app.server import create_app


def main() -> None:
    port = int(os.environ.get("PORT", "10000"))
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
