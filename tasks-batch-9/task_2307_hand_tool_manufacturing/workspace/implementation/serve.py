"""Process entry point. Boots the Toolworks WSGI application on $PORT.

Kept separate from app.py so the running process's command line is stable and
distinct from the application module itself.

The server deliberately closes the TCP connection after every response
(``protocol_version = "HTTP/1.0"``, which is Werkzeug's default and is asserted
explicitly here so a library default change cannot silently enable keep-alive).
Two consequences matter for this service:

* a client that pools connections can never hand a request to a socket the
  server has already discarded, so no request observes a reset peer;
* nothing but the listening socket is ever bound to $PORT, and the process
  exits immediately on SIGTERM, so the harness's per-test teardown is cheap.
"""

import os

from werkzeug.serving import WSGIRequestHandler

from app import app

if __name__ == "__main__":
    WSGIRequestHandler.protocol_version = "HTTP/1.0"
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
