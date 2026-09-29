"""Insurance certificates: filing and independent verification."""
from flask import Blueprint

import auth
import calc
import derive
import response
import serialize
import store
import validators as V
from errors import fail
from store import S, insert, now, touch

bp = Blueprint("insurance", __name__)


@bp.route("/contractors/<contractor_id>/insurance-certificates", methods=["POST"])
def create_certificate(contractor_id):
    user_id, role = auth.authenticate([auth.ROLE_CONTRACTOR_ADMIN])
    body = V.parse_body(
        [
            ("contractor_id", "string", False),
            ("coverage_type", "string", True),
            ("carrier_name", "string", True),
            ("each_occurrence_limit", "integer", True),
            ("aggregate_limit", "integer", True),
            ("effective_date", "string", True),
            ("expiration_date", "string", True),
            ("additional_insured", "boolean", False),
            ("waiver_of_subrogation", "boolean", False),
        ]
    )
    coverage_type = V.check_enum("coverage_type", body["coverage_type"], calc.COVERAGE_TYPES)
    carrier_name = V.check_str_len("carrier_name", body["carrier_name"], 1, 120)
    each_occurrence_limit = V.check_int_range(
        "each_occurrence_limit", body["each_occurrence_limit"], lo=0
    )
    aggregate_limit = V.check_int_range("aggregate_limit", body["aggregate_limit"], lo=0)
    effective_date = V.parse_instant("effective_date", body["effective_date"])
    expiration_date = V.parse_instant("expiration_date", body["expiration_date"])
    if aggregate_limit < each_occurrence_limit:
        fail(
            "ERR_INVALID_FIELD_VALUE",
            "aggregate_limit must be at least each_occurrence_limit.",
        )
    if expiration_date <= effective_date:
        fail("ERR_INVALID_FIELD_VALUE", "expiration_date must be strictly after effective_date.")
    additional_insured = bool(body["additional_insured"]) if body["additional_insured"] is not None else False
    waiver = bool(body["waiver_of_subrogation"]) if body["waiver_of_subrogation"] is not None else False

    contractor = V.get_contractor(contractor_id)
    auth.check_owner(role, user_id, contractor_id=contractor["id"])

    existing_rows = derive.certs_of(contractor["id"])
    for existing in existing_rows:
        if existing["coverage_type"] != coverage_type:
            continue
        if existing["verification_status"] not in ("PENDING", "VERIFIED"):
            continue
        if calc.intervals_intersect_half_open(
            effective_date,
            expiration_date,
            existing["effective_date"],
            existing["expiration_date"],
        ):
            fail("ERR_COVERAGE_PERIOD_OVERLAP", "A live certificate already covers that interval.")

    row = store.base_row()
    row.update(
        {
            "contractor_id": contractor["id"],
            "coverage_type": coverage_type,
            "carrier_name": carrier_name,
            "each_occurrence_limit": each_occurrence_limit,
            "aggregate_limit": aggregate_limit,
            "effective_date": effective_date,
            "expiration_date": expiration_date,
            "additional_insured": additional_insured,
            "waiver_of_subrogation": waiver,
            "verification_status": "PENDING",
            "verified_by_user_id": None,
            "lifecycle_status": None,
            "available_aggregate": None,
        }
    )
    row["lifecycle_status"] = calc.lifecycle_status(row, now())
    row["available_aggregate"] = calc.available_aggregate(
        aggregate_limit, contractor["open_severe_incident_count"]
    )
    insert(S.insurance_certificates, row)

    # Sweep previously refused certificates of the same coverage type whose
    # interval intersects this one: they become SUPERSEDED.
    for existing in existing_rows:
        if existing["coverage_type"] != coverage_type:
            continue
        if existing["verification_status"] != "REJECTED":
            continue
        if calc.intervals_intersect_half_open(
            effective_date,
            expiration_date,
            existing["effective_date"],
            existing["expiration_date"],
        ):
            if existing["lifecycle_status"] != "SUPERSEDED":
                existing["lifecycle_status"] = "SUPERSEDED"
                touch(existing)

    derive.recompute_verified_coverage_types(contractor)
    return response.created(serialize.insurance_certificate(row))


@bp.route("/insurance-certificates/<certificate_id>/verify", methods=["POST"])
def verify_certificate(certificate_id):
    user_id, role = auth.authenticate([auth.ROLE_VERIFICATION_ANALYST])
    body = V.parse_body([("decision", "string", True)])
    decision = V.check_enum("decision", body["decision"], ("VERIFY", "REJECT"))

    row = V.get_certificate(certificate_id)
    contractor = S.contractors[row["contractor_id"]]

    # Priority 8: segregation of verification duties, ahead of transition legality.
    for preq in derive.preqs_of_contractor(contractor["id"]):
        for statistic in derive.stats_of(preq["id"]):
            if statistic["verified_by_user_id"] == user_id:
                fail(
                    "ERR_SEGREGATION_OF_DUTIES",
                    "This analyst identity already verified a safety statistic of this contractor.",
                )

    if row["verification_status"] != "PENDING":
        fail("ERR_TRANSITION_NOT_ALLOWED", "The certificate has already been decided.")

    if decision == "VERIFY":
        if not calc.per_occurrence_adequate(
            row["coverage_type"], row["each_occurrence_limit"], contractor["base_hazard_tier"]
        ):
            fail(
                "ERR_COVERAGE_LIMIT_INSUFFICIENT",
                "each_occurrence_limit is below the applicable floor.",
            )
        row["verification_status"] = "VERIFIED"
        row["verified_by_user_id"] = user_id
        row["lifecycle_status"] = calc.lifecycle_status(row, now())
        row["available_aggregate"] = calc.available_aggregate(
            row["aggregate_limit"], contractor["open_severe_incident_count"]
        )
    else:
        row["verification_status"] = "REJECTED"
        row["verified_by_user_id"] = user_id
    touch(row)
    derive.recompute_verified_coverage_types(contractor)
    return response.ok(serialize.insurance_certificate(row))
