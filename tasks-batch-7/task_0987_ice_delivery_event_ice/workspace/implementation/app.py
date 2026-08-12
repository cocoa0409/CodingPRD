"""Ice Delivery & Event Ice Service API — entry point.

Run: `python3 app.py` (binds 0.0.0.0:$PORT, default 10000).
Storage is in-memory only; the store starts empty on every boot.
"""
import os

from server import app  # noqa: F401  (Flask app + error handlers)

# Route modules register themselves on `app` at import time.
import routes_core  # noqa: F401,E402
import routes_orders  # noqa: F401,E402
import routes_ops  # noqa: F401,E402


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
