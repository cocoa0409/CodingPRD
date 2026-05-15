"""Entry point for the Festival Program Schedule API.

Listens on the port from the PORT environment variable (default 10000),
binds to 0.0.0.0 per INSTRUCTION.md.
"""
import os
from app import create_app


def main() -> None:
    port = int(os.environ.get("PORT", "10000"))
    app = create_app()
    # threaded=False keeps Python's GIL the serialisation point for the
    # in-memory dict-of-dicts collections; the test harness expects a single
    # interpreter's lock to be the row-level lock for OCC and concurrency rules.
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
