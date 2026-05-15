"""Counterparties — register and patch ratings."""
from __future__ import annotations

from flask import Blueprint, g

from app.auth import require_auth
from app.clock import clock
from app.errors import make_error
from app.responses import success_object
from app.services.counterparty import (
    BAND_SEVERITY,
    EXTERNAL_BAND,
    recompute_counterparty,
)
from app.services.serializers import counterparty_dto
from app.store import store
from app.validation import (
    check_version,
    get_json_body,
    require_enum,
    require_int,
    require_str,
)


bp = Blueprint("counterparties", __name__, url_prefix="/fx-risk")


@bp.route("/counterparties", methods=["POST"])
@require_auth(["ComplianceOfficer"])
def create_counterparty():
    with store.lock:
        body = get_json_body()
        name = require_str(body, "name", min_len=1, max_len=200)
        external_rating = require_enum(body, "external_rating", set(EXTERNAL_BAND.keys()))
        internal_score = require_int(body, "internal_score", lo=0, hi=100)
        meta = store.stamp_common(create=True)
        row = {
            **meta,
            "name": name,
            "external_rating": external_rating,
            "internal_score": internal_score,
        }
        recompute_counterparty(row)
        store.counterparties[row["id"]] = row
        store.audit(
            event_type="RATING_CHANGE",
            actor_user_id=g.user_id,
            actor_role=g.role,
            subject_entity="Counterparty",
            subject_id=row["id"],
            before_snapshot=None,
            after_snapshot={
                "external_rating": external_rating,
                "internal_score": internal_score,
                "rating_band": row["rating_band"],
                "on_watchlist": row["on_watchlist"],
            },
        )
        return success_object(counterparty_dto(row), status=201)


@bp.route("/counterparties/<cp_id>", methods=["PATCH"])
@require_auth(["ComplianceOfficer"])
def patch_counterparty(cp_id: str):
    with store.lock:
        cp = store.counterparties.get(cp_id)
        if cp is None:
            raise make_error("ERR_NOT_FOUND")
        body = get_json_body()
        check_version(body, cp["version"])
        before = {
            "external_rating": cp["external_rating"],
            "internal_score": cp["internal_score"],
            "rating_band": cp["rating_band"],
            "on_watchlist": cp["on_watchlist"],
        }
        new_external = body.get("external_rating")
        if new_external is not None:
            if new_external not in EXTERNAL_BAND:
                raise make_error("ERR_VALIDATION",
                                 "external_rating must be one of " + ",".join(sorted(EXTERNAL_BAND)))
            cp["external_rating"] = new_external
        new_internal = body.get("internal_score")
        if new_internal is not None:
            if isinstance(new_internal, bool) or not isinstance(new_internal, int):
                raise make_error("ERR_VALIDATION", "internal_score must be an integer 0..100.")
            if new_internal < 0 or new_internal > 100:
                raise make_error("ERR_VALIDATION", "internal_score must be 0..100.")
            cp["internal_score"] = new_internal
        recompute_counterparty(cp)
        cp["updated_at"] = clock.now_iso()
        cp["version"] = cp["version"] + 1
        store.audit(
            event_type="RATING_CHANGE",
            actor_user_id=g.user_id,
            actor_role=g.role,
            subject_entity="Counterparty",
            subject_id=cp["id"],
            before_snapshot=before,
            after_snapshot={
                "external_rating": cp["external_rating"],
                "internal_score": cp["internal_score"],
                "rating_band": cp["rating_band"],
                "on_watchlist": cp["on_watchlist"],
            },
        )
        return success_object(counterparty_dto(cp))
