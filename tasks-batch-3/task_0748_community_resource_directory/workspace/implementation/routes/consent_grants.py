from flask import request

from db import db
from errors import (
    ERR_CLIENT_NOT_FOUND,
    ERR_CONSENT_ALREADY_TERMINAL,
    ERR_CONSENT_GRANT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_OWNERSHIP_VIOLATION,
    raise_error,
)
from middleware import get_auth, require_roles
from response import paginate, success
from services import (
    _touch,
    cascade_referral_withdraw,
    make_consent,
    serialise_consent,
    REFERRAL_INFLIGHT,
)
from validate import (
    SCOPE_ENUM,
    parse_pagination,
    require_body,
    require_enum,
    require_str,
)


def _consent_or_404(cid: str):
    c = db.consent_grants.get(cid)
    if not c:
        raise_error(ERR_CONSENT_GRANT_NOT_FOUND, f"consent grant {cid} not found")
    return c


def register(app):
    @app.post("/clients/<cid>/consent-grants")
    @require_roles("Client", "Caseworker", "PlatformAdmin")
    def create_consent(cid):
        if cid not in db.clients:
            raise_error(ERR_CLIENT_NOT_FOUND, f"client {cid} not found")
        # Client role must be acting on self.
        uid, role = get_auth()
        if role == "Client" and uid != cid:
            raise_error(ERR_OWNERSHIP_VIOLATION, "Client can only grant consent for self")
        body = require_body(request.get_json(silent=True))
        provider_id = require_str(body, "provider_id")
        if provider_id not in db.providers:
            raise_error(ERR_INVALID_REQUEST, f"provider_id {provider_id} not found")
        scope = require_enum(body, "scope", SCOPE_ENUM)
        entity = make_consent(cid, provider_id, scope)
        return success(serialise_consent(entity), 201)

    @app.get("/consent-grants/<cid>")
    @require_roles("Client", "Caseworker", "ProviderStaff", "PlatformAdmin")
    def get_consent(cid):
        c = _consent_or_404(cid)
        uid, role = get_auth()
        if role == "Client" and uid != c["client_id"]:
            raise_error(ERR_OWNERSHIP_VIOLATION, "Client does not own this consent grant")
        if role == "ProviderStaff" and uid != c["provider_id"]:
            raise_error(ERR_OWNERSHIP_VIOLATION, "ProviderStaff does not own this provider")
        return success(serialise_consent(c), 200)

    @app.get("/consent-grants")
    @require_roles("Client", "Caseworker", "ProviderStaff", "PlatformAdmin")
    def list_consents():
        limit, offset = parse_pagination(request.args)
        client_id = request.args.get("client_id")
        provider_id = request.args.get("provider_id")
        status = request.args.get("status")
        items = list(db.consent_grants.values())
        uid, role = get_auth()
        # Scope entity-backed listings to owned rows.
        if role == "Client":
            items = [c for c in items if c["client_id"] == uid]
        elif role == "ProviderStaff":
            items = [c for c in items if c["provider_id"] == uid]
        if client_id is not None:
            items = [c for c in items if c["client_id"] == client_id]
        if provider_id is not None:
            items = [c for c in items if c["provider_id"] == provider_id]
        if status is not None:
            items = [c for c in items if c["status"] == status]
        items.sort(key=lambda x: x["created_at"])
        window, pg = paginate(items, limit, offset)
        return success([serialise_consent(c) for c in window], 200, "array", pg)

    @app.post("/consent-grants/<cid>/revoke")
    @require_roles("Client", "PlatformAdmin")
    def revoke_consent(cid):
        c = _consent_or_404(cid)
        uid, role = get_auth()
        if role == "Client" and uid != c["client_id"]:
            raise_error(ERR_OWNERSHIP_VIOLATION, "Client does not own this consent grant")
        if c["status"] != "GRANTED":
            raise_error(ERR_CONSENT_ALREADY_TERMINAL,
                        "consent grant is not in GRANTED state")
        c["status"] = "REVOKED"
        _touch(c)
        # Cascade: every in-flight referral under this consent -> WITHDRAWN (same path).
        for r in list(db.referrals.values()):
            if r["consent_grant_id"] == cid and r["status"] in REFERRAL_INFLIGHT:
                cascade_referral_withdraw(r)
        return success(serialise_consent(c), 200)
