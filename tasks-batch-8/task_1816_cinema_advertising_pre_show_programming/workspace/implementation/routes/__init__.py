from flask import Blueprint

bp = Blueprint("api", __name__)

# Import route modules so their handlers attach to the blueprint.
from . import clock, master, sales, reels, ops, billing  # noqa: E402,F401
