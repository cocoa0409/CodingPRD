"""Seafood counter sourcing and country-of-origin labelling API.

In-memory only: every process starts with an empty store and the logical clock
at 2026-08-01T00:00:00Z.  Nothing is persisted, seeded or cached on disk.
"""

import os

from web import app

# Importing the route modules registers their endpoints on the app object.
import routes_core  # noqa: F401,E402
import routes_lots  # noqa: F401,E402
import routes_labels_ads  # noqa: F401,E402
import routes_cold  # noqa: F401,E402
import routes_samples  # noqa: F401,E402
import routes_docs  # noqa: F401,E402
import routes_shrink  # noqa: F401,E402


def main():
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
