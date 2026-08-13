"""Route blueprints."""
from flask import Blueprint


def _bp(name):
    return Blueprint(name, __name__, url_prefix="/api")
