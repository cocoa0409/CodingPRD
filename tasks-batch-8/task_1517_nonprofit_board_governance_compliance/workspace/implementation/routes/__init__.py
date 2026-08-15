from flask import Blueprint

bp = Blueprint('boardgov', __name__)

from . import core, committees, meetings, compliance, filings  # noqa: E402,F401
