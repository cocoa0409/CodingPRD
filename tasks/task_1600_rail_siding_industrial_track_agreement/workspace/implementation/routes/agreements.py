"""TrackAgreement endpoints."""
from flask import request

from db import DB, new_id
from errors import ApiError
from middleware import ALL_ROLES, auth, require_shipper_party
from response import ok, ok_list
from services import (
    apply_expiry_sweep_to_agreement,
    cascade_file_abandonment,
    cascade_terminate,
    cascade_verify_removal,
    extend_agreement_term,
    get_agreement_or_404,
    has_open_claims,
    mint_common_fields,
    touch,
)
from util import (
    as_int,
    as_iso_date,
    as_list,
    as_non_negative_int,
    as_pct,
    as_positive_int,
    as_str,
    body,
    logical_today,
    pagination_args,
    parse_ymd,
    required,
)

VALID_DAYS = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}


def _serialize(a):
    apply_expiry_sweep_to_agreement(a)
    return a


def register(app):
    @app.route("/agreements", methods=["POST"])
    def create_agreement():
        user_id, role = auth(["RailroadContractsManager"])
        data = body()

        shipper_name = as_str(required(data, "shipper_name"), "shipper_name")
        shipper_user_id = as_str(required(data, "shipper_user_id"), "shipper_user_id")
        facility_name = as_str(required(data, "facility_name"), "facility_name")
        term_start_date = as_iso_date(required(data, "term_start_date"), "term_start_date")
        term_end_date = as_iso_date(required(data, "term_end_date"), "term_end_date")
        renewal_notice_days = as_non_negative_int(
            required(data, "renewal_notice_days"), "renewal_notice_days"
        )
        renewal_term_months = as_positive_int(
            required(data, "renewal_term_months"), "renewal_term_months"
        )
        shipper_cost_share_pct = as_pct(
            required(data, "shipper_cost_share_pct"), "shipper_cost_share_pct"
        )
        liability_cap_cents = as_non_negative_int(
            required(data, "liability_cap_cents"), "liability_cap_cents"
        )
        shipper_indemnity_default_pct = as_pct(
            required(data, "shipper_indemnity_default_pct"),
            "shipper_indemnity_default_pct",
        )
        free_time_hours = as_non_negative_int(
            required(data, "free_time_hours"), "free_time_hours"
        )
        demurrage_base_rate_cents = as_non_negative_int(
            required(data, "demurrage_base_rate_cents"), "demurrage_base_rate_cents"
        )
        demurrage_escalated_rate_cents = as_non_negative_int(
            required(data, "demurrage_escalated_rate_cents"),
            "demurrage_escalated_rate_cents",
        )
        storage_rate_per_car_month_cents = as_non_negative_int(
            required(data, "storage_rate_per_car_month_cents"),
            "storage_rate_per_car_month_cents",
        )
        inspection_cadence_days = as_positive_int(
            required(data, "inspection_cadence_days"), "inspection_cadence_days"
        )
        removal_period_days = as_positive_int(
            required(data, "removal_period_days"), "removal_period_days"
        )
        removal_penalty_per_day_cents = as_non_negative_int(
            required(data, "removal_penalty_per_day_cents"),
            "removal_penalty_per_day_cents",
        )
        service_days_of_week = as_list(
            required(data, "service_days_of_week"), "service_days_of_week"
        )
        if not service_days_of_week:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "service_days_of_week must be non-empty"
            )
        for d in service_days_of_week:
            if d not in VALID_DAYS:
                raise ApiError(
                    "ERR_INVALID_REQUEST",
                    400,
                    f"service_days_of_week entries must be one of {sorted(VALID_DAYS)}",
                )
        max_switches_per_day = as_positive_int(
            required(data, "max_switches_per_day"), "max_switches_per_day"
        )

        # Business constraint: term_end_date must be > term_start_date
        if parse_ymd(term_end_date) <= parse_ymd(term_start_date):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "term_end_date must be after term_start_date"
            )

        agreement = {
            "shipper_name": shipper_name,
            "shipper_user_id": shipper_user_id,
            "facility_name": facility_name,
            "term_start_date": term_start_date,
            "term_end_date": term_end_date,
            "renewal_notice_days": renewal_notice_days,
            "renewal_term_months": renewal_term_months,
            "shipper_cost_share_pct": shipper_cost_share_pct,
            "liability_cap_cents": liability_cap_cents,
            "shipper_indemnity_default_pct": shipper_indemnity_default_pct,
            "free_time_hours": free_time_hours,
            "demurrage_base_rate_cents": demurrage_base_rate_cents,
            "demurrage_escalated_rate_cents": demurrage_escalated_rate_cents,
            "storage_rate_per_car_month_cents": storage_rate_per_car_month_cents,
            "inspection_cadence_days": inspection_cadence_days,
            "removal_period_days": removal_period_days,
            "removal_penalty_per_day_cents": removal_penalty_per_day_cents,
            "service_days_of_week": list(service_days_of_week),
            "max_switches_per_day": max_switches_per_day,
            "abandonment_notice_date": None,
            "removal_deadline_date": None,
            "removal_penalty_cents": 0,
            "status": "DRAFT",
        }
        mint_common_fields(agreement)
        DB["agreements"][agreement["id"]] = agreement
        return ok(agreement, 201)

    @app.route("/agreements", methods=["GET"])
    def list_agreements():
        auth(ALL_ROLES)
        limit, offset = pagination_args()
        items = sorted(
            DB["agreements"].values(), key=lambda x: (x["created_at"], x["id"])
        )
        # Apply expiry sweep to each row
        for a in items:
            apply_expiry_sweep_to_agreement(a)
        total = len(items)
        page = items[offset : offset + limit]
        return ok_list(page, total, limit, offset)

    @app.route("/agreements/<agreementId>", methods=["GET"])
    def get_agreement(agreementId):
        auth(ALL_ROLES)
        a = get_agreement_or_404(agreementId)
        return ok(_serialize(a))

    @app.route("/agreements/<agreementId>/submit", methods=["POST"])
    def submit_agreement(agreementId):
        auth(["RailroadContractsManager"])
        a = get_agreement_or_404(agreementId)
        apply_expiry_sweep_to_agreement(a)
        if a["status"] != "DRAFT":
            raise ApiError(
                "ERR_AGREEMENT_INVALID_STATE", 409, "Agreement must be DRAFT to submit"
            )
        a["status"] = "PENDING_COUNTERSIGN"
        touch(a)
        return ok(a)

    @app.route("/agreements/<agreementId>/countersign", methods=["POST"])
    def countersign_agreement(agreementId):
        user_id, _role = auth(["ShipperFacilityManager"])
        a = get_agreement_or_404(agreementId)
        apply_expiry_sweep_to_agreement(a)
        if a["status"] != "PENDING_COUNTERSIGN":
            raise ApiError(
                "ERR_AGREEMENT_INVALID_STATE",
                409,
                "Agreement must be PENDING_COUNTERSIGN",
            )
        require_shipper_party(user_id, a)
        a["status"] = "ACTIVE"
        touch(a)
        return ok(a)

    @app.route("/agreements/<agreementId>/renewal-offer", methods=["POST"])
    def renewal_offer(agreementId):
        auth(["RailroadContractsManager"])
        a = get_agreement_or_404(agreementId)
        apply_expiry_sweep_to_agreement(a)
        if a["status"] != "ACTIVE":
            raise ApiError(
                "ERR_AGREEMENT_INVALID_STATE", 409, "Agreement must be ACTIVE"
            )
        if has_open_claims(a["id"]):
            raise ApiError(
                "ERR_OPEN_CLAIMS_BLOCK_RENEWAL",
                409,
                "Open liability claims block renewal offers",
            )
        # Window check: current logical date <= term_end_date - renewal_notice_days
        end = parse_ymd(a["term_end_date"])
        from util import add_days as _add_days

        closing = _add_days(end, -int(a["renewal_notice_days"]))
        if logical_today() > closing:
            raise ApiError(
                "ERR_RENEWAL_WINDOW_CLOSED", 409, "Renewal window is closed"
            )
        a["status"] = "RENEWAL_OFFERED"
        touch(a)
        return ok(a)

    @app.route("/agreements/<agreementId>/accept-renewal", methods=["POST"])
    def accept_renewal(agreementId):
        user_id, _role = auth(["ShipperFacilityManager"])
        a = get_agreement_or_404(agreementId)
        apply_expiry_sweep_to_agreement(a)
        if a["status"] != "RENEWAL_OFFERED":
            raise ApiError(
                "ERR_AGREEMENT_INVALID_STATE",
                409,
                "Agreement must be RENEWAL_OFFERED",
            )
        require_shipper_party(user_id, a)
        end = parse_ymd(a["term_end_date"])
        from util import add_days as _add_days

        closing = _add_days(end, -int(a["renewal_notice_days"]))
        if logical_today() > closing:
            raise ApiError(
                "ERR_RENEWAL_WINDOW_CLOSED", 409, "Renewal window is closed"
            )
        extend_agreement_term(a)
        a["status"] = "ACTIVE"
        touch(a)
        return ok(a)

    @app.route("/agreements/<agreementId>/terminate", methods=["POST"])
    def terminate_agreement(agreementId):
        auth(["RailroadContractsManager"])
        a = get_agreement_or_404(agreementId)
        apply_expiry_sweep_to_agreement(a)
        if a["status"] != "ACTIVE":
            raise ApiError(
                "ERR_AGREEMENT_INVALID_STATE", 409, "Agreement must be ACTIVE"
            )
        cascade_terminate(a)
        a["status"] = "TERMINATED"
        touch(a)
        return ok(a)

    @app.route("/agreements/<agreementId>/file-abandonment-notice", methods=["POST"])
    def file_abandonment(agreementId):
        user_id, _role = auth(["ShipperFacilityManager"])
        a = get_agreement_or_404(agreementId)
        apply_expiry_sweep_to_agreement(a)
        if a["status"] not in ("TERMINATED", "EXPIRED"):
            raise ApiError(
                "ERR_AGREEMENT_INVALID_STATE",
                409,
                "Agreement must be TERMINATED or EXPIRED",
            )
        require_shipper_party(user_id, a)
        data = body()
        notice_date = as_iso_date(required(data, "notice_date"), "notice_date")
        cascade_file_abandonment(a, notice_date)
        a["status"] = "ABANDONMENT_IN_PROGRESS"
        touch(a)
        return ok(a)

    @app.route("/agreements/<agreementId>/verify-removal", methods=["POST"])
    def verify_removal(agreementId):
        auth(["RailroadEngineer"])
        a = get_agreement_or_404(agreementId)
        apply_expiry_sweep_to_agreement(a)
        if a["status"] != "ABANDONMENT_IN_PROGRESS":
            raise ApiError(
                "ERR_AGREEMENT_INVALID_STATE",
                409,
                "Agreement must be ABANDONMENT_IN_PROGRESS",
            )
        data = body()
        removal_verified_date = as_iso_date(
            required(data, "removal_verified_date"), "removal_verified_date"
        )
        cascade_verify_removal(a, removal_verified_date)
        a["status"] = "CLOSED"
        touch(a)
        return ok(a)
