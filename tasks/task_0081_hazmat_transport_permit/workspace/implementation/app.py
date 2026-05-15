"""Entry-point script. The Dockerfile's CMD invokes this module.

The Flask app is built by the `hazmat.create_app` application-factory, and the
Werkzeug development server is run with `threaded=True` so the optimistic-
concurrency-control test fixtures' concurrent-request scenarios serialize on the
in-process global lock that the `hazmat.store` module's `STATE_LOCK` provides.
The port and the bind address are read from the environment as the
INSTRUCTION.md contract requires: bind 0.0.0.0, listen on the integer value of
the `PORT` environment variable (default 10000), and respond to HTTP traffic
within 60 seconds of container start.
"""

from __future__ import annotations

import os

from hazmat import create_app


def main() -> None:
    app = create_app()
    port = int(os.environ.get("PORT", "10000"))
    # threaded=True so concurrent requests can race against the shared in-memory
    # store under the module-level threading.Lock the store-module owns. The
    # OCC-version-field-mismatch-yields-409 contract and the Idempotency-Key
    # body-hash registry both rely on the read-modify-write sequence being
    # serialized by that lock, so the threaded WSGI server is the canonical
    # match for the contract the test harness asserts against.
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
