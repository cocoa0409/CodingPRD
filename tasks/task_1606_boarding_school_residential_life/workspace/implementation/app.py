"""Boarding School Residential Life API — entry point runner.

In-memory store only; boots with an empty store and the logical clock at
2026-08-01T00:00:00Z on every process start.
"""

import os

from server import app  # noqa: F401  (importing registers all routes)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
