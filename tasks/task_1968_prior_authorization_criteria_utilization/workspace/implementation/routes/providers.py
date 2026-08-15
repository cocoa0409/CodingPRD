"""Provider registry and gold-card program endpoints."""

import clock
from db import db, base_record, lean_record, touch
from errors import (
    ApiError,
    ERR_ALREADY_GOLD_CARDED,
    ERR_GOLD_CARD_NOT_ELIGIBLE,
    invalid_request,
)
from middleware import (
    ALL_ROLES,
    ROLE_UM_ADMIN,
    authorize,
    get_or_404,
    json_body,
    req_str,
    opt_str,
)
from response import list_response, ok, serialize
from services import (
    EV_GOLD_CARD_GRANTED,
    GOLD_CARD_MIN_COUNT,
    GOLD_CARD_MIN_RATE,
    add_event,
    rate4_json,
    recompute_provider_stats,
)
from . import make_blueprint

bp = make_blueprint("providers")


@bp.route("/providers", methods=["POST"])
def create_provider():
    authorize(ROLE_UM_ADMIN)
    body = json_body()
    npi = req_str(body, "npi")
    name = req_str(body, "name")
    specialty = opt_str(body, "specialty")
    # duplicate npi rejected under ERR_INVALID_REQUEST
    for p in db.providers.values():
        if p["npi"] == npi:
            raise invalid_request(f"Duplicate npi {npi}")
    rec = base_record()
    rec.update(
        {
            "npi": npi,
            "name": name,
            "specialty": specialty,
            "gold_card_status": "NOT_GOLD_CARDED",
            "gold_card_service_category": None,
            "rolling_determination_count": 0,
            "rolling_approval_count": 0,
            "rolling_approval_rate": None,
            "lifetime_determination_count": 0,
            "lifetime_approval_count": 0,
            "lifetime_approval_rate": None,
        }
    )
    db.providers[rec["id"]] = rec
    return ok(serialize(rec), status=201)


@bp.route("/providers/<pid>", methods=["GET"])
def get_provider(pid):
    authorize(*ALL_ROLES)
    rec = get_or_404(db.providers, pid, "provider")
    return ok(serialize(rec))


@bp.route("/providers/<pid>/gold-card-evaluations", methods=["POST"])
def create_gold_card_evaluation(pid):
    authorize(ROLE_UM_ADMIN)
    provider = get_or_404(db.providers, pid, "provider")
    body = json_body()
    service_category = req_str(body, "service_category")

    # priority 6 (state): evaluation blocked for an already GOLD_CARDED provider
    if provider["gold_card_status"] == "GOLD_CARDED":
        raise ApiError(
            ERR_ALREADY_GOLD_CARDED,
            409,
            "Provider is already GOLD_CARDED",
        )

    was_status = provider["gold_card_status"]

    # step 1: always recompute rolling-window stats first (human lanes only)
    stats = recompute_provider_stats(provider["id"], run_suspend_check=False)

    # step 2 (priority 11): thresholds, both inclusive; null rate never eligible
    eligible = (
        stats["rolling_count"] >= GOLD_CARD_MIN_COUNT
        and stats["rolling_rate"] is not None
        and stats["rolling_rate"] >= GOLD_CARD_MIN_RATE
    )
    if not eligible:
        raise ApiError(
            ERR_GOLD_CARD_NOT_ELIGIBLE,
            422,
            "Rolling determination count < 10 or rolling approval rate < 0.90",
        )

    decision = "REINSTATED" if was_status == "SUSPENDED" else "GRANTED"
    ev_rec = lean_record()
    ev_rec.update(
        {
            "provider_id": provider["id"],
            "service_category": service_category,
            "window_start": stats["window_start"],
            "window_end": stats["window_end"],
            "window_determination_count": stats["rolling_count"],
            "window_approval_rate": rate4_json(stats["rolling_rate"]),
            "decision": decision,
        }
    )
    db.gold_card_evaluations[ev_rec["id"]] = ev_rec

    provider["gold_card_status"] = "GOLD_CARDED"
    provider["gold_card_service_category"] = service_category
    touch(provider)
    add_event(
        EV_GOLD_CARD_GRANTED,
        None,
        provider["id"],
        f"Gold card {decision.lower()} for provider {provider['id']} "
        f"covering service category {service_category}",
    )
    return ok(serialize(ev_rec), status=201)


@bp.route("/providers/<pid>/gold-card-evaluations", methods=["GET"])
def list_gold_card_evaluations(pid):
    authorize(*ALL_ROLES)
    get_or_404(db.providers, pid, "provider")
    items = [
        e for e in db.gold_card_evaluations.values() if e["provider_id"] == pid
    ]
    return list_response(items)


@bp.route("/providers/<pid>/compliance-events", methods=["GET"])
def list_provider_compliance_events(pid):
    authorize(*ALL_ROLES)
    get_or_404(db.providers, pid, "provider")
    event_type = _opt_query("event_type")
    items = [
        e
        for e in db.events.values()
        if e["provider_id"] == pid
        and (event_type is None or e["event_type"] == event_type)
    ]
    return list_response(items)


def _opt_query(name):
    from flask import request

    v = request.args.get(name)
    return v if v not in (None, "") else None
