"""Boarding match endpoints (read-only, matches are created via reservation confirmation)."""

from flask import Blueprint
import db
from middleware import require_role
from response import success_object
from errors import raise_error

bp = Blueprint("boarding_matches", __name__)


def serialize_match(m):
    return {k: v for k, v in m.items()}
