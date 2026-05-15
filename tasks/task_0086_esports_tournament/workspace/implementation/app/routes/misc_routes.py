"""Misc/health endpoints."""
from __future__ import annotations

from flask import Flask

from ._helpers import ok


def register(app: Flask) -> None:

    @app.get("/healthz")
    def healthz():
        return ok({"status": "ok"})

    @app.get("/")
    def root():
        return ok({"service": "esports-tournament-api"})
