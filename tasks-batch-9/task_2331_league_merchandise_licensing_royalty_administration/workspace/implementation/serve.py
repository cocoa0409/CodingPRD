"""Process entry point for the League Merch Licensing API.

The WSGI application itself lives in ``app.py``; this module only owns the
"run the development server" concern, so the application module stays free of
process-level plumbing.  Storage remains in-memory only and starts empty on
every boot.
"""

import os

from app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
