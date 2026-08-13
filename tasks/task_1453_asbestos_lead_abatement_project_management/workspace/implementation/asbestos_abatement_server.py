"""Entry point for the Asbestos & Lead Abatement Project Management API."""
import os

from core import app

# Route modules register their endpoints on the shared app at import time.
import routes_a  # noqa: F401,E402
import routes_b  # noqa: F401,E402

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
