"""Blueprint factory (flat topology: all endpoint paths are absolute)."""

from flask import Blueprint


def make_blueprint(name):
    return Blueprint(name, __name__)
