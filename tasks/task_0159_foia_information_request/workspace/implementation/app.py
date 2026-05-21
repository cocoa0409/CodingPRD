"""Entry point for the FOIA Information Request API.

The server reads its listening port from the PORT environment variable
(default 10000) and binds to 0.0.0.0 as required by the benchmark harness.
"""

import os

from app import create_app


def main() -> None:
    app = create_app()
    port = int(os.environ.get("PORT", "10000"))
    # Disable the reloader/debugger so the container stays single-process and
    # responses are deterministic for the test harness.
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
