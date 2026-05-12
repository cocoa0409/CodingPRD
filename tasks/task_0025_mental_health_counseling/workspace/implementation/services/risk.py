"""Client risk-flag recompute helpers."""
from clock import now, parse_iso

import db
from services.calculations import compute_risk_score, risk_flag_for_score


def _hydrate(inc: dict) -> dict:
    out = dict(inc)
    out["_created_at_dt"] = parse_iso(inc["created_at"])
    fc = inc.get("follow_up_completed_at")
    out["_follow_up_completed_at_dt"] = parse_iso(fc) if fc else None
    return out


def _client_incidents(client_id: str):
    return [_hydrate(i) for i in db.crisis_incidents.values()
            if i["client_id"] == client_id]


def recompute_for_client(client_id: str) -> tuple:
    """Recompute risk flag for client. Returns (raw_score, risk_flag)."""
    client = db.clients.get(client_id)
    if client is None:
        return 0, "NONE"
    incidents = _client_incidents(client_id)
    score = compute_risk_score(incidents, now())
    flag = risk_flag_for_score(score)
    if client.get("risk_flag") != flag:
        client["risk_flag"] = flag
        db.stamp_update(client)
    else:
        client["risk_flag"] = flag
    return score, flag


def get_score_for_client(client_id: str) -> int:
    incidents = _client_incidents(client_id)
    return compute_risk_score(incidents, now())
