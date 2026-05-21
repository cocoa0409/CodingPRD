"""Entry point — instantiate the Flask app and serve."""
import os
from app import create_app


def main() -> None:
    port = int(os.environ.get("PORT", "10000"))
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
