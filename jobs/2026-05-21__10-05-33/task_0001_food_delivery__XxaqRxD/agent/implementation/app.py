import os

from server.app import create_app


def main() -> None:
    app = create_app()
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, use_reloader=False)


if __name__ == "__main__":
    main()
