"""Server entry point.

Running ``python3 app.py`` directly would load this package's ``app`` module
twice (once as ``__main__`` and once as ``app`` when ``routes`` imports it),
splitting route registration onto a different Flask instance than the one
being served. Importing ``app`` from a separate entry module guarantees the
served application is the same object the routes registered on.
"""

import os

from app import app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
