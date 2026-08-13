"""AttestationCampaign and AttestationRequest endpoints (PRD §3.8)."""

from datetime import timedelta

from flask import Blueprint, request

from db import DB, CLOCK
from errors import ApiError, not_found, invalid_state, invalid_request
from errors import (
    ERR_CAMPAIGN_NOT_OPEN, ERR_CAMPAIGN_HAS_OPEN_REQUESTS,
    ERR_PROVIDER_NOT_LINKABLE, ERR_ATTESTATION_ALREADY_INFLIGHT,
    ERR_ATTESTATION_WINDOW_CLOSED, ERR_ESCALATION_WINDOW_CLOSED,
    ERR_CORRECTION_PAYLOAD_REQUIRED,
)
from middleware import require_roles, json_body
from response import success_object, paginate
from services.common import (
    new_common, touch, require_string, require_int, require_enum,
)
from services.attributes import apply_effective_dating
from services.quality import run_quality_scoring, compute_staleness_flag

bp = Blueprint("attestation", __name__)

OUTCOMES = {"CONFIRMED", "CORRECTED"}


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _get_campaign(cid):
    c = DB.attestation_campaigns.get(cid)
    if c is None:
        raise not_found()
    return c


def _get_request(rid):
    r = DB.attestation_requests.get(rid)
    if r is None:
        raise not_found()
    return r


def _get_provider(pid):
    p = DB.providers.get(pid)
    if p is None:
        raise not_found()
    return p


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------

@bp.route("/pdm/attestation-campaigns", methods=["POST"])
def create_campaign():
    require_roles("DataSteward")
    body = json_body()
    name = require_string(body, "name")
    window_days = require_int(body, "window_days", minimum=1)
    rec = {
        **new_common(),
        "name": name,
        "window_days": window_days,
        "status": "DRAFT",
    }
    DB.attestation_campaigns[rec["id"]] = rec
    return success_object(_public(rec), status=201)


@bp.route("/pdm/attestation-campaigns", methods=["GET"])
def list_campaigns():
    require_roles("DataSteward", "ProviderContact")
    items = list(DB.attestation_campaigns.values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate([_public(c) for c in items], request.args)


@bp.route("/pdm/attestation-campaigns/<cid>", methods=["GET"])
def get_campaign(cid):
    require_roles("DataSteward", "ProviderContact")
    return success_object(_public(_get_campaign(cid)))


@bp.route("/pdm/attestation-campaigns/<cid>/open", methods=["POST"])
def open_campaign(cid):
    require_roles("DataSteward")
    c = _get_campaign(cid)
    if c["status"] != "DRAFT":
        raise invalid_state()
    c["status"] = "OPEN"
    touch(c)
    return success_object(_public(c))


@bp.route("/pdm/attestation-campaigns/<cid>/close", methods=["POST"])
def close_campaign(cid):
    require_roles("DataSteward")
    c = _get_campaign(cid)
    if c["status"] != "OPEN":
        raise invalid_state()
    if any(
        r["attestation_campaign_id"] == cid and r["status"] in ("SENT", "ESCALATED")
        for r in DB.attestation_requests.values()
    ):
        raise ApiError(ERR_CAMPAIGN_HAS_OPEN_REQUESTS, 409,
                       "Campaign close blocked by SENT/ESCALATED requests")
    for r in DB.attestation_requests.values():
        if r["attestation_campaign_id"] == cid and r["status"] == "DRAFT":
            r["status"] = "WITHDRAWN"
            touch(r)
    c["status"] = "CLOSED"
    touch(c)
    return success_object(_public(c))


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

@bp.route("/pdm/attestation-campaigns/<cid>/attestation-requests", methods=["POST"])
def create_request(cid):
    require_roles("DataSteward")
    _get_campaign(cid)
    body = json_body()
    provider_id = require_string(body, "provider_id")
    _get_provider(provider_id)
    rec = {
        **new_common(),
        "attestation_campaign_id": cid,
        "provider_id": provider_id,
        "sent_at": None,
        "due_at": None,
        "responded_at": None,
        "attestation_outcome": None,
        "corrected_payload": None,
        "status": "DRAFT",
    }
    DB.attestation_requests[rec["id"]] = rec
    return success_object(_public(rec), status=201)


@bp.route("/pdm/attestation-campaigns/<cid>/attestation-requests", methods=["GET"])
def list_campaign_requests(cid):
    require_roles("DataSteward", "ProviderContact")
    _get_campaign(cid)
    items = [r for r in DB.attestation_requests.values()
             if r["attestation_campaign_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate([_public(r) for r in items], request.args)


@bp.route("/pdm/attestation-requests", methods=["GET"])
def list_requests():
    require_roles("DataSteward", "ProviderContact")
    items = list(DB.attestation_requests.values())
    pid = request.args.get("provider_id")
    status = request.args.get("status")
    cid = request.args.get("attestation_campaign_id")
    if pid is not None:
        items = [r for r in items if r["provider_id"] == pid]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if cid is not None:
        items = [r for r in items if r["attestation_campaign_id"] == cid]
    return paginate([_public(r) for r in items], request.args)


@bp.route("/pdm/attestation-requests/<rid>", methods=["GET"])
def get_request(rid):
    require_roles("DataSteward", "ProviderContact")
    return success_object(_public(_get_request(rid)))


@bp.route("/pdm/attestation-requests/<rid>/send", methods=["POST"])
def send_request(rid):
    require_roles("DataSteward")
    r = _get_request(rid)
    if r["status"] != "DRAFT":
        raise invalid_state()
    # Guards in order: provider ACTIVE, no inflight request, campaign OPEN.
    provider = _get_provider(r["provider_id"])
    if provider["lifecycle_status"] != "ACTIVE":
        raise ApiError(ERR_PROVIDER_NOT_LINKABLE, 409,
                       "Target provider not ACTIVE for attestation send")
    for other in DB.attestation_requests.values():
        if other["id"] != rid and other["provider_id"] == r["provider_id"] \
                and other["status"] in ("SENT", "ESCALATED"):
            raise ApiError(ERR_ATTESTATION_ALREADY_INFLIGHT, 409,
                           "Provider already has a SENT or ESCALATED request")
    campaign = _get_campaign(r["attestation_campaign_id"])
    if campaign["status"] != "OPEN":
        raise ApiError(ERR_CAMPAIGN_NOT_OPEN, 409,
                       "Campaign not OPEN when sending a request")
    sent_at = CLOCK.now()
    from db import iso_ts
    r["sent_at"] = iso_ts(sent_at)
    due = sent_at + timedelta(days=campaign["window_days"])
    r["due_at"] = iso_ts(due)
    r["status"] = "SENT"
    touch(r)
    return success_object(_public(r))


@bp.route("/pdm/attestation-requests/<rid>/respond", methods=["POST"])
def respond_request(rid):
    require_roles("ProviderContact")
    r = _get_request(rid)
    if r["status"] != "SENT":
        raise invalid_state()
    body = json_body()
    outcome = require_enum(body, "attestation_outcome", OUTCOMES)
    # Window check before payload check.
    from services.common import parse_iso_datetime
    due = parse_iso_datetime(r["due_at"])
    if not (CLOCK.now() < due):
        raise ApiError(ERR_ATTESTATION_WINDOW_CLOSED, 409,
                       "Respond attempted at or after due_at")
    if outcome == "CORRECTED":
        payload = body.get("corrected_payload")
        if not isinstance(payload, dict) or not payload:
            raise ApiError(ERR_CORRECTION_PAYLOAD_REQUIRED, 422,
                           "attestation_outcome=CORRECTED without corrected_payload")
    else:
        payload = body.get("corrected_payload")

    from db import iso_ts
    r["responded_at"] = iso_ts(CLOCK.now())
    r["attestation_outcome"] = outcome
    r["corrected_payload"] = payload
    r["status"] = "RESPONDED"
    touch(r)

    if outcome == "CORRECTED" and isinstance(payload, dict):
        _apply_corrections(r, payload)
    run_quality_scoring(r["provider_id"])
    return success_object(_public(r))


def _apply_corrections(r, payload):
    """Upsert corrected_payload fields as ProviderAttribute rows with
    effective_date = logical clock date. Provenance: the source that names
    this campaign as its default_attestation_campaign_id when configured,
    otherwise the incumbent attribute's own source."""
    pid = r["provider_id"]
    cid = r["attestation_campaign_id"]
    today = CLOCK.today()
    default_source = None
    for s in DB.roster_sources.values():
        if s.get("default_attestation_campaign_id") == cid:
            default_source = s["id"]
            break
    for key, value in payload.items():
        group = None
        attr_key = key
        if isinstance(key, str) and "." in key:
            group, attr_key = key.split(".", 1)
        elif isinstance(value, dict):
            continue
        if group is None:
            group = "DEMOGRAPHIC"
        incumbent_source = None
        for a in DB.provider_attributes.values():
            if (a["provider_id"] == pid and a["attribute_group"] == group
                    and a["attribute_key"] == attr_key and a["status"] == "ACTIVE"):
                incumbent_source = a.get("roster_source_id")
                break
        source_id = default_source or incumbent_source
        attr = {
            **new_common(),
            "provider_id": pid,
            "attribute_group": group,
            "attribute_key": attr_key,
            "attribute_value": value if isinstance(value, str) else str(value),
            "effective_date": today,
            "term_date": None,
            "roster_source_id": source_id,
            "roster_row_id": None,
            "supersedes_attribute_id": None,
            "status": "PENDING",
        }
        DB.provider_attributes[attr["id"]] = attr
        apply_effective_dating(pid, attr)


@bp.route("/pdm/attestation-requests/<rid>/escalate", methods=["POST"])
def escalate_request(rid):
    require_roles("DataSteward")
    r = _get_request(rid)
    if r["status"] != "EXPIRED":
        raise invalid_state()
    campaign = _get_campaign(r["attestation_campaign_id"])
    from services.common import parse_iso_datetime
    due = parse_iso_datetime(r["due_at"])
    deadline = due + timedelta(days=campaign["window_days"])
    if not (CLOCK.now() < deadline):
        raise ApiError(ERR_ESCALATION_WINDOW_CLOSED, 409,
                       "Escalate attempted at or after due_at + window_days")
    r["status"] = "ESCALATED"
    touch(r)
    # Auto-suspend on the second consecutive expiry (threshold inclusive >= 2).
    pid = r["provider_id"]
    reqs = [
        x for x in DB.attestation_requests.values()
        if x["provider_id"] == pid and x.get("sent_at") is not None
    ]
    reqs.sort(key=lambda x: (x["sent_at"], x["created_at"]), reverse=True)
    consecutive = 0
    for x in reqs:
        if x["status"] in ("EXPIRED", "ESCALATED"):
            consecutive += 1
        elif x["status"] in ("RESPONDED", "WITHDRAWN"):
            break
    if consecutive >= 2:
        provider = DB.providers.get(pid)
        if provider is not None and provider["lifecycle_status"] == "ACTIVE":
            provider["lifecycle_status"] = "SUSPENDED"
            touch(provider)
    run_quality_scoring(pid)
    return success_object(_public(r))


@bp.route("/pdm/attestation-requests/<rid>/withdraw", methods=["POST"])
def withdraw_request(rid):
    require_roles("DataSteward")
    r = _get_request(rid)
    if r["status"] != "DRAFT":
        raise invalid_state()
    r["status"] = "WITHDRAWN"
    touch(r)
    return success_object(_public(r))


@bp.route("/pdm/attestation-requests/sweep", methods=["POST"])
def sweep_requests():
    require_roles("DataSteward")
    from services.common import parse_iso_datetime
    now = CLOCK.now()
    expired = []
    for r in DB.attestation_requests.values():
        if r["status"] != "SENT" or r.get("due_at") is None:
            continue
        due = parse_iso_datetime(r["due_at"])
        if now >= due:
            r["status"] = "EXPIRED"
            touch(r)
            expired.append(r["id"])
            provider = DB.providers.get(r["provider_id"])
            if provider is not None:
                provider["staleness_flag"] = compute_staleness_flag(provider["id"])
                run_quality_scoring(provider["id"])
    expired.sort()
    return success_object({
        "expired_count": len(expired),
        "expired_request_ids": expired,
    })
