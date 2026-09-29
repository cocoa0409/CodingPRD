"""Shared query-string helpers for list endpoints."""

from flask import request


def query_value(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value.strip()
