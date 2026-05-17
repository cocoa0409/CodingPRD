"""Sweep route — SCAFFOLD §1.5 / PRD §3.4 (expire abandoned episodes)."""
from flask import Blueprint, jsonify

from ..auth import require_auth
from ..clock import clock_today_iso
from ..responses import success_response
from ..services.episodes import episode_eligible_for_expire, expire_episode
from ..services.serialize import episode_view
from ..store import get_lock, get_store


bp = Blueprint("sweep", __name__)


@bp.post("/_sweep/expire-episodes")
@require_auth("PlatformAdmin")
def sweep_expire_episodes():
    expired = []
    with get_lock():
        store = get_store()
        today = clock_today_iso()
        # Snapshot OPEN episodes; expire each that meets the cutoff.
        candidates = [e for e in store.episodes.values() if e["status"] == "OPEN"]
        for e in candidates:
            if episode_eligible_for_expire(e, today):
                expire_episode(e, now=None)
                expired.append(e)
        # Deterministic order: by created_at ascending.
        expired.sort(key=lambda e: e["created_at"])

    body, status = success_response(
        [episode_view(e) for e in expired], status=200, response_type="array"
    )
    return jsonify(body), status
