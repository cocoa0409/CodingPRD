"""WaitlistEvent — currently only exposed via /programs/{id}/waitlist-events.

This module is a placeholder so the blueprint registration is complete and
future extensions (e.g. a top-level GET /enrollment/waitlist-events) can drop in.
"""
from flask import Blueprint


bp = Blueprint("waitlist_events", __name__, url_prefix="/enrollment/waitlist-events")
