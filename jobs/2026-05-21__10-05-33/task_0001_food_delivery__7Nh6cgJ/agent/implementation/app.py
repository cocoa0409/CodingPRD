"""Entry point — start the HTTP server."""

from __future__ import annotations

import os

from server import create_app


def main() -> None:
    app = create_app()
    port = int(os.environ.get("PORT", "10000"))
    # Threaded to support concurrent requests; the store guards itself with a lock.
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
