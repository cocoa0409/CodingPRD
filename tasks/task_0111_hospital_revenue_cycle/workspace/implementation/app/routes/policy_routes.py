"""Insurance policy endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..errors import ApiError
from ..pagination import parse_limit_offset
from ..response import paginate
from ..services.serializers import serialize_policy
from ..services.validation import (
    get_patient_or_404,
    require_int,
    require_str,
)
from ..store import LOCK, common_fields_create, get_store
from ._helpers import created, get_json_body, list_ok


def register(app: Flask) -> None:
    @app.route("/patients/<patient_id>/policies", methods=["POST"])
    @require_auth("RegistrationClerk")
    def create_policy(patient_id):
        get_patient_or_404(patient_id)
        body = get_json_body()
        payer_name = require_str(body, "payer_name")
        policy_number = require_str(body, "policy_number")
        plan_year = require_int(body, "plan_year")
        deductible_cents = require_int(body, "deductible_cents", minimum=0)
        coinsurance_rate_bps = require_int(body, "coinsurance_rate_bps", minimum=0)
        oop_max_cents = require_int(body, "oop_max_cents", minimum=0)

        if coinsurance_rate_bps > 10000:
            raise ApiError(
                "ERR_INVALID_INPUT",
                "coinsurance_rate_bps must be <= 10000.",
            )
        if oop_max_cents < deductible_cents:
            raise ApiError(
                "ERR_INVALID_INPUT",
                "oop_max_cents must be >= deductible_cents.",
            )

        store = get_store()
        with LOCK:
            base = common_fields_create()
            policy = {
                **base,
                "patient_id": patient_id,
                "payer_name": payer_name,
                "policy_number": policy_number,
                "plan_year": plan_year,
                "deductible_cents": deductible_cents,
                "deductible_met_cents": 0,
                "coinsurance_rate_bps": coinsurance_rate_bps,
                "oop_max_cents": oop_max_cents,
                "oop_accumulated_cents": 0,
                "status": "UNVERIFIED",
                "verified_at": None,
            }
            store.policies[policy["id"]] = policy
        return created(serialize_policy(policy))

    @app.route("/patients/<patient_id>/policies", methods=["GET"])
    @require_auth("RegistrationClerk", "Biller")
    def list_policies(patient_id):
        get_patient_or_404(patient_id)
        limit, offset = parse_limit_offset()
        store = get_store()
        items = [
            pol for pol in store.policies.values() if pol["patient_id"] == patient_id
        ]
        items.sort(key=lambda p: p["created_at"])
        sliced, pag = paginate(items, limit, offset)
        return list_ok([serialize_policy(p) for p in sliced], pag)
