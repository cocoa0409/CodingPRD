"""Test-only reset endpoint — wipes in-memory store and clock offset."""
from __future__ import annotations

from flask import Flask, jsonify

from ..clock import CLOCK
from ..store import reset_store


def register(app: Flask) -> None:
    app.add_url_rule(
        "/__test__/reset",
        view_func=reset,
        methods=["POST"],
    )


def reset():
    reset_store()
    CLOCK.reset()
    return jsonify({"ok": True}), 200
