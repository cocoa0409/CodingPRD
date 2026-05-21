"""Application entry point for the Last-Mile Delivery API."""
import os
from server import create_app


def main():
    app = create_app()
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
