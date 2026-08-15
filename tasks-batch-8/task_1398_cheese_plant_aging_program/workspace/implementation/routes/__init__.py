"""Route blueprints for the Cheese Plant Aging Program API."""

from flask import Blueprint


def make_bp(name):
    return Blueprint(name, __name__)
