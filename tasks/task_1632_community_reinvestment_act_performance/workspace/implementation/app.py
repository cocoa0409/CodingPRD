"""Entry point: registers all routes and serves the CRA Performance Management API."""

import os

from core import app

# Route modules register themselves on the shared app at import time.
import routes_areas  # noqa: F401,E402
import routes_lending  # noqa: F401,E402
import routes_branches_files  # noqa: F401,E402
import routes_exams  # noqa: F401,E402
import routes_applications  # noqa: F401,E402

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
