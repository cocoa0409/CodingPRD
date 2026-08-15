"""Amendment endpoints."""
from flask import request

from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth, require_shipper_party
from response import ok, ok_list
from services import (
    apply_amendment_to_agreement,
    apply_expiry_sweep_to_agreement,
    get_agreement_or_404,
    mint_common_fields,
    supersede_pending_amendments,
    touch,
)
from util import (
    as_enum,
    as_int,
    as_iso_date,
    as_pct,
    body,
    pagination_args,
    required,
)

AMENDMENT_TYPES = {"COST_SHARE", "LIABILITY_CAP", "STORAGE_RATE", "DEMURRAGE_RATES", "TERM"}

# amendment_type -> required new_* fields
PINNED_FIELDS = {
    "COST_SHARE": ["new_shipper_cost_share_pct"],
    "LIABILITY_CAP": ["new_liability_cap_cents"],
    "STORAGE_RATE": ["new_storage_rate_per_car_month_cents"],
    "DEMURRAGE_RATES": ["new_demurrage_base_rate_cents", "new_demurrage_escalated_rate_cents"],
    "TERM": ["new_term_end_date"],
}

ALL_NEW_FIELDS = [
    "new_shipper_cost_share_pct",
    "new_liability_cap_cents",
    "new_storage_rate_per_car_month_cents",
    "new_demurrage_base_rate_cents",
    "new_demurrage_escalated_rate_cents",
    "new_term_end_date",
]


def _get_amendment_or_404(amendment_id):
    a = DB["amendments"].get(amendment_id)
    if a is None:
        raise ApiError("ERR_AMENDMENT_NOT_FOUND", 404, "Amendment not found")
    return a


def register(app):
    @app.route("/agreements/<agreementId>/amendments", methods=["POST"])
    def create_amendment(agreementId):
        user_id, role = auth(["RailroadContractsManager", "ShipperFacilityManager"])
        agreement = get_agreement_or_404(agreementId)
        apply_expiry_sweep_to_agreement(agreement)
        # Shipper party check
        if role == "ShipperFacilityManager":
            require_shipper_party(user_id, agreement)
        data = body()

        amendment_type = as_enum(
            required(data, "amendment_type"), "amendment_type", AMENDMENT_TYPES
        )
        expected_version = required(data, "expected_agreement_version")
        expected_version = as_int(expected_version, "expected_agreement_version")

        # Field shape: pinned fields must be present, others absent (null)
        pinned = PINNED_FIELDS[amendment_type]
        for f in pinned:
            if data.get(f) is None:
                raise ApiError(
                    "ERR_INVALID_REQUEST",
                    400,
                    f"Field {f} is required for amendment_type {amendment_type}",
                )
        for f in ALL_NEW_FIELDS:
            if f not in pinned and data.get(f) is not None:
                raise ApiError(
                    "ERR_INVALID_REQUEST",
                    400,
                    f"Field {f} must be absent for amendment_type {amendment_type}",
                )

        # Validate field types and ranges
        if amendment_type == "COST_SHARE":
            new_cost_share = as_pct(data["new_shipper_cost_share_pct"], "new_shipper_cost_share_pct")
            new_fields = {"new_shipper_cost_share_pct": new_cost_share}
        elif amendment_type == "LIABILITY_CAP":
            v = as_int(data["new_liability_cap_cents"], "new_liability_cap_cents")
            if v < 0:
                raise ApiError(
                    "ERR_INVALID_REQUEST", 400, "new_liability_cap_cents must be >= 0"
                )
            new_fields = {"new_liability_cap_cents": v}
        elif amendment_type == "STORAGE_RATE":
            v = as_int(
                data["new_storage_rate_per_car_month_cents"],
                "new_storage_rate_per_car_month_cents",
            )
            if v < 0:
                raise ApiError(
                    "ERR_INVALID_REQUEST",
                    400,
                    "new_storage_rate_per_car_month_cents must be >= 0",
                )
            new_fields = {"new_storage_rate_per_car_month_cents": v}
        elif amendment_type == "DEMURRAGE_RATES":
            base = as_int(
                data["new_demurrage_base_rate_cents"], "new_demurrage_base_rate_cents"
            )
            esc = as_int(
                data["new_demurrage_escalated_rate_cents"],
                "new_demurrage_escalated_rate_cents",
            )
            if base < 0 or esc < 0:
                raise ApiError(
                    "ERR_INVALID_REQUEST", 400, "Demurrage rates must be >= 0"
                )
            new_fields = {
                "new_demurrage_base_rate_cents": base,
                "new_demurrage_escalated_rate_cents": esc,
            }
        else:  # TERM
            v = as_iso_date(data["new_term_end_date"], "new_term_end_date")
            new_fields = {"new_term_end_date": v}

        # Cross-entity state: parent agreement must be ACTIVE
        if agreement["status"] != "ACTIVE":
            raise ApiError(
                "ERR_AGREEMENT_NOT_ACTIVE",
                409,
                "Parent agreement must be ACTIVE to propose an amendment",
            )

        # OCC: expected_agreement_version must equal current version
        if expected_version != agreement["version"]:
            raise ApiError(
                "ERR_STALE_AGREEMENT_VERSION",
                412,
                "expected_agreement_version does not match current agreement version",
            )

        # Supersede existing PENDING amendments on this agreement
        supersede_pending_amendments(agreement["id"])

        # Build the amendment row with all new_* fields defaulted to None
        amendment = {
            "agreement_id": agreement["id"],
            "amendment_type": amendment_type,
            "proposed_by_role": role,
            "proposed_by_user_id": user_id,
            "status": "PENDING",
        }
        for f in ALL_NEW_FIELDS:
            amendment[f] = new_fields.get(f)
        mint_common_fields(amendment)
        DB["amendments"][amendment["id"]] = amendment

        # Agreement version bumps on amendment create
        touch(agreement)

        return ok(amendment, 201)

    @app.route("/amendments", methods=["GET"])
    def list_amendments():
        auth(ALL_ROLES)
        limit, offset = pagination_args()
        agreement_id = request.args.get("agreement_id")
        items = list(DB["amendments"].values())
        if agreement_id is not None:
            items = [a for a in items if a.get("agreement_id") == agreement_id]
        items.sort(key=lambda x: (x["created_at"], x["id"]))
        total = len(items)
        page = items[offset : offset + limit]
        return ok_list(page, total, limit, offset)

    @app.route("/amendments/<amendmentId>", methods=["GET"])
    def get_amendment(amendmentId):
        auth(ALL_ROLES)
        return ok(_get_amendment_or_404(amendmentId))

    @app.route("/amendments/<amendmentId>/respond", methods=["POST"])
    def respond_amendment(amendmentId):
        user_id, role = auth(["RailroadContractsManager", "ShipperFacilityManager"])
        amendment = _get_amendment_or_404(amendmentId)
        agreement = get_agreement_or_404(amendment["agreement_id"])
        apply_expiry_sweep_to_agreement(agreement)
        data = body()
        decision = as_enum(required(data, "decision"), "decision", {"ACCEPT", "REJECT"})

        # Amendment must be PENDING
        if amendment["status"] != "PENDING":
            raise ApiError(
                "ERR_AMENDMENT_INVALID_STATE",
                409,
                "Amendment must be PENDING to respond",
            )
        # Segregation of duties: responder role != proposer role
        if role == amendment["proposed_by_role"]:
            raise ApiError(
                "ERR_SAME_PARTY_RESPONSE",
                403,
                "Responder role must differ from proposer role",
            )
        # Shipper party check
        if role == "ShipperFacilityManager":
            require_shipper_party(user_id, agreement)

        if decision == "ACCEPT":
            # Parent agreement must be ACTIVE
            if agreement["status"] != "ACTIVE":
                raise ApiError(
                    "ERR_AGREEMENT_NOT_ACTIVE",
                    409,
                    "Parent agreement must be ACTIVE to accept an amendment",
                )
            apply_amendment_to_agreement(amendment, agreement)
            touch(agreement)
            amendment["status"] = "ACCEPTED"
        else:
            amendment["status"] = "REJECTED"
        touch(amendment)
        return ok(amendment)
