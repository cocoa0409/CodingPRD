"""Server entry point.

Binds the listen socket BEFORE importing Flask (the dominant boot cost),
shrinking the per-test restart window in which the runner-freed port can be
re-issued by the kernel to a concurrent run on a shared host. The prebound
socket is then handed to werkzeug via ``make_server(..., fd=...)`` so no
second bind occurs.
"""
import logging
import os
import socket


def _prebound_socket(port: int):
    """Bind+listen immediately; return the socket, or None if unavailable."""
    try:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", port))
        srv.listen(128)
        return srv
    except OSError:
        # Fall back to the normal path (werkzeug will bind and report).
        return None


def main():
    port = int(os.environ.get("PORT", "10000"))
    srv = _prebound_socket(port)

    from werkzeug.serving import make_server
    from app import create_app

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    application = create_app()
    if srv is not None:
        httpd = make_server("0.0.0.0", port, application, threaded=True, fd=srv.fileno())
    else:
        httpd = make_server("0.0.0.0", port, application, threaded=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
