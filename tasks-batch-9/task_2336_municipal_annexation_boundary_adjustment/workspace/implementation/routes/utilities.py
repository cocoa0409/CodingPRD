"""Utility accounts serving the territory from outside the corporate limits (PRD §3.8)."""

from flask import Blueprint

import validate as v
from auth import ANY_ROLE, check_municipality_scope, prelude
from db import base_record, db
from errors import ApiError
from response import object_response, paginate
from services import calc, domain

bp = Blueprint("utilities", __name__)


@bp.post("/utility-accounts")
def create_account():
    user_id, role = prelude(("MunicipalPlanner",))
    body = v.get_body()

    soft_parcel = domain.soft("parcels", body.get("parcel_id"))
    check_municipality_scope(
        role, user_id, domain.municipality_id_of_case(domain.case_of_parcel(soft_parcel))
    )

    parcel_id = v.id_field(body, "parcel_id")
    parcel = domain.body_ref("parcels", parcel_id)
    provider_id = v.id_field(body, "service_provider_id")
    provider = domain.body_ref("service_providers", provider_id)

    service_type = v.enum_field(body, "service_type", ("WATER", "SEWER"))
    monthly_base_cents = v.int_field(body, "monthly_base_cents", minimum=1)

    case = domain.case_of_parcel(parcel)
    domain.assert_case_not_terminal(case)

    if case is None or provider["municipality_id"] != case["municipality_id"]:
        raise ApiError(
            "ERR_PARCEL_CASE_MISMATCH",
            "The service provider belongs to another municipality.",
        )

    municipality = domain.municipality_of_case(case)
    record = base_record()
    record.update(
        {
            "parcel_id": parcel["id"],
            "service_provider_id": provider["id"],
            "service_type": service_type,
            "monthly_base_cents": monthly_base_cents,
            "rate_schedule": "OUTSIDE_CITY_SURCHARGE",
            "account_status": "OUTSIDE_CITY",
            "effective_monthly_cents": calc.utility_effective_monthly_cents(
                monthly_base_cents,
                "OUTSIDE_CITY_SURCHARGE",
                municipality["utility_outside_surcharge_pct"] if municipality else 0,
            ),
        }
    )
    db.utility_accounts[record["id"]] = record
    return object_response(record, 201)


@bp.get("/utility-accounts/<account_id>")
def read_account(account_id):
    prelude(ANY_ROLE)
    return object_response(domain.path_record("utility_accounts", account_id))


@bp.get("/utility-accounts")
def list_accounts():
    prelude(ANY_ROLE)
    return paginate(
        domain.rows("utility_accounts"), ("parcel_id", "service_provider_id", "account_status")
    )
