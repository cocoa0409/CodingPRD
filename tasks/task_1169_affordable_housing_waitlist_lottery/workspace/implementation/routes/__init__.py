"""Route registration package."""

from flask import Blueprint

bp = Blueprint("api", __name__)

from . import core  # noqa: E402,F401  (registers routes on bp)
