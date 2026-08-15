"""ConstructionProject endpoints."""
from flask import request

from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth, require_shipper_party
from response import ok, ok_list
from services import (
    apply_expiry_sweep_to_agreement,
    compute_cost_share,
    get_agreement_or_404,
    mint_common_fields,
    touch,
)
from util import (
    as_enum,
    as_int,
    as_non_negative_int,
    as_num,
    as_pct,
    as_str,
    body,
    pagination_args,
    required,
)

TIE_MATERIALS = {"WOOD", "CONCRETE", "STEEL"}


def _get_project_or_404(project_id):
    p = DB["construction_projects"].get(project_id)
    if p is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND", 404, "ConstructionProject not found")
    return p


def register(app):
    @app.route("/construction-projects", methods=["POST"])
    def create_project():
        user_id, role = auth(["ShipperFacilityManager"])
        data = body()
        agreement_id = as_str(required(data, "agreement_id"), "agreement_id")
        agreement = get_agreement_or_404(agreement_id)
        apply_expiry_sweep_to_agreement(agreement)
        require_shipper_party(user_id, agreement)

        project_name = as_str(required(data, "project_name"), "project_name")
        estimated_cost_cents = as_non_negative_int(
            required(data, "estimated_cost_cents"), "estimated_cost_cents"
        )
        if "shipper_share_pct" in data and data["shipper_share_pct"] is not None:
            shipper_share_pct = as_pct(data["shipper_share_pct"], "shipper_share_pct")
        else:
            shipper_share_pct = agreement["shipper_cost_share_pct"]

        if agreement["status"] != "ACTIVE":
            raise ApiError(
                "ERR_AGREEMENT_NOT_ACTIVE",
                409,
                "Parent agreement must be ACTIVE",
            )

        project = {
            "agreement_id": agreement["id"],
            "project_name": project_name,
            "estimated_cost_cents": estimated_cost_cents,
            "shipper_share_pct": shipper_share_pct,
            "rail_weight_lb_per_yard": None,
            "tie_material": None,
            "ballast_depth_inches": None,
            "spec_revision_no": 0,
            "shipper_estimated_share_cents": None,
            "actual_cost_cents": None,
            "shipper_final_share_cents": None,
            "amount_paid_cents": 0,
            "outstanding_share_cents": None,
            "status": "DRAFT",
        }
        mint_common_fields(project)
        DB["construction_projects"][project["id"]] = project
        return ok(project, 201)

    @app.route("/construction-projects", methods=["GET"])
    def list_projects():
        auth(ALL_ROLES)
        limit, offset = pagination_args()
        agreement_id = request.args.get("agreement_id")
        items = list(DB["construction_projects"].values())
        if agreement_id is not None:
            items = [p for p in items if p.get("agreement_id") == agreement_id]
        items.sort(key=lambda x: (x["created_at"], x["id"]))
        total = len(items)
        return ok_list(items[offset : offset + limit], total, limit, offset)

    @app.route("/construction-projects/<projectId>", methods=["GET"])
    def get_project(projectId):
        auth(ALL_ROLES)
        return ok(_get_project_or_404(projectId))

    @app.route("/construction-projects/<projectId>/submit-spec", methods=["POST"])
    def submit_spec(projectId):
        user_id, role = auth(["ShipperFacilityManager"])
        p = _get_project_or_404(projectId)
        agreement = get_agreement_or_404(p["agreement_id"])
        apply_expiry_sweep_to_agreement(agreement)
        require_shipper_party(user_id, agreement)
        data = body()
        rail_weight = as_num(
            required(data, "rail_weight_lb_per_yard"), "rail_weight_lb_per_yard"
        )
        tie_material = as_enum(
            required(data, "tie_material"), "tie_material", TIE_MATERIALS
        )
        ballast = as_num(
            required(data, "ballast_depth_inches"), "ballast_depth_inches"
        )
        if p["status"] not in ("DRAFT", "SPEC_REJECTED"):
            raise ApiError(
                "ERR_PROJECT_INVALID_STATE",
                409,
                "Project must be DRAFT or SPEC_REJECTED to submit a spec",
            )
        p["rail_weight_lb_per_yard"] = rail_weight
        p["tie_material"] = tie_material
        p["ballast_depth_inches"] = ballast
        p["spec_revision_no"] = p.get("spec_revision_no", 0) + 1
        p["status"] = "SPEC_SUBMITTED"
        touch(p)
        return ok(p)

    @app.route("/construction-projects/<projectId>/approve-spec", methods=["POST"])
    def approve_spec(projectId):
        auth(["RailroadEngineer"])
        p = _get_project_or_404(projectId)
        if p["status"] != "SPEC_SUBMITTED":
            raise ApiError(
                "ERR_PROJECT_INVALID_STATE",
                409,
                "Project must be SPEC_SUBMITTED to approve",
            )
        p["shipper_estimated_share_cents"] = compute_cost_share(
            p["estimated_cost_cents"], p["shipper_share_pct"]
        )
        p["status"] = "SPEC_APPROVED"
        touch(p)
        return ok(p)

    @app.route("/construction-projects/<projectId>/reject-spec", methods=["POST"])
    def reject_spec(projectId):
        auth(["RailroadEngineer"])
        p = _get_project_or_404(projectId)
        data = body()
        as_str(required(data, "rejection_reason"), "rejection_reason")
        if p["status"] != "SPEC_SUBMITTED":
            raise ApiError(
                "ERR_PROJECT_INVALID_STATE",
                409,
                "Project must be SPEC_SUBMITTED to reject",
            )
        p["status"] = "SPEC_REJECTED"
        touch(p)
        return ok(p)

    @app.route("/construction-projects/<projectId>/complete", methods=["POST"])
    def complete_project(projectId):
        user_id, role = auth(["ShipperFacilityManager"])
        p = _get_project_or_404(projectId)
        agreement = get_agreement_or_404(p["agreement_id"])
        apply_expiry_sweep_to_agreement(agreement)
        require_shipper_party(user_id, agreement)
        data = body()
        actual_cost_cents = as_non_negative_int(
            required(data, "actual_cost_cents"), "actual_cost_cents"
        )
        if p["status"] != "SPEC_APPROVED":
            raise ApiError(
                "ERR_PROJECT_INVALID_STATE",
                409,
                "Project must be SPEC_APPROVED to complete",
            )
        p["actual_cost_cents"] = actual_cost_cents
        p["shipper_final_share_cents"] = compute_cost_share(
            actual_cost_cents, p["shipper_share_pct"]
        )
        p["outstanding_share_cents"] = (
            p["shipper_final_share_cents"] - p["amount_paid_cents"]
        )
        p["status"] = "COMPLETED"
        touch(p)
        return ok(p)

    @app.route("/construction-projects/<projectId>/settle", methods=["POST"])
    def settle_project(projectId):
        auth(["RailroadContractsManager"])
        p = _get_project_or_404(projectId)
        data = body()
        payment = as_int(required(data, "payment_cents"), "payment_cents")

        # State check: project must be COMPLETED
        if p["status"] != "COMPLETED":
            raise ApiError(
                "ERR_PROJECT_INVALID_STATE",
                409,
                "Project must be COMPLETED to settle",
            )
        # Money checks (priority 12)
        if payment == 0:
            raise ApiError(
                "ERR_OVERPAYMENT", 402, "payment_cents must not be zero"
            )
        outstanding = p["outstanding_share_cents"]
        if payment > 0 and payment > outstanding:
            raise ApiError(
                "ERR_OVERPAYMENT",
                402,
                "payment_cents exceeds outstanding_share_cents",
            )
        if payment < 0 and (-payment) > p["amount_paid_cents"]:
            raise ApiError(
                "ERR_REFUND_EXCEEDS_PAID",
                402,
                "Refund magnitude exceeds amount_paid_cents",
            )

        p["amount_paid_cents"] = p["amount_paid_cents"] + payment
        p["outstanding_share_cents"] = (
            p["shipper_final_share_cents"] - p["amount_paid_cents"]
        )
        if p["outstanding_share_cents"] == 0:
            p["status"] = "SETTLED"
        touch(p)
        return ok(p)
