#!/usr/bin/env python3
"""Entry point: registers all routes and serves the app on 0.0.0.0:$PORT."""
import os

from core import app

# Importing the route modules registers their views on the shared app object.
import routes_cases  # noqa: F401
import routes_work  # noqa: F401
import routes_secondary  # noqa: F401


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
