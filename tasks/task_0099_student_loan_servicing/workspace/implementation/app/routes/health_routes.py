"""Liveness probe."""
from flask import Flask

from ._helpers import ok


def register(app: Flask) -> None:
    @app.route("/_health", methods=["GET"])
    def health():
        return ok({"status": "ok"})
