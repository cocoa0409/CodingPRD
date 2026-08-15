"""Measure endpoints."""
from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    get_cycle_or_404,
    get_measure_or_404,
    mint_common_fields,
    serialize,
    sorted_rows,
    touch,
)
from util import (
    apply_filters,
    as_bool,
    as_enum,
    as_int_range,
    as_str,
    body,
    filter_arg,
    pagination_args,
    required,
)

DOMAINS = {
    "STAYING_HEALTHY",
    "CHRONIC_CARE",
    "MEMBER_EXPERIENCE",
    "MEMBER_COMPLAINTS",
    "CUSTOMER_SERVICE",
    "DRUG_SAFETY",
}
MEASURE_TYPES = {"PROCESS", "OUTCOME", "PATIENT_EXPERIENCE"}
DIRECTIONS = {"HIGHER_BETTER", "LOWER_BETTER"}
DATA_SOURCES = {"HEDIS", "CAHPS", "HOS", "PHARMACY_PDE", "COMPLAINTS", "APPEALS"}
MEASURE_STATES = {"DRAFT", "ACTIVE", "RETIRED"}

WEIGHT_BY_TYPE = {"PROCESS": 1, "OUTCOME": 3, "PATIENT_EXPERIENCE": 4}

LEGAL_TRANSITIONS = {("DRAFT", "ACTIVE"), ("ACTIVE", "RETIRED")}


def register(app):
    @app.route("/api/measures", methods=["POST"])
    def create_measure():
        auth(["StarsAnalyst"])
        data = body()
        rating_cycle_id = as_str(required(data, "rating_cycle_id"), "rating_cycle_id")
        code = as_str(required(data, "code"), "code")
        title = as_str(required(data, "title"), "title")
        domain = as_enum(required(data, "domain"), "domain", DOMAINS)
        measure_type = as_enum(
            required(data, "measure_type"), "measure_type", MEASURE_TYPES
        )
        direction = as_enum(required(data, "direction"), "direction", DIRECTIONS)
        data_source = as_enum(required(data, "data_source"), "data_source", DATA_SOURCES)
        improvement_eligible = as_bool(
            required(data, "improvement_eligible"), "improvement_eligible"
        )
        prior_cycle_star = data.get("prior_cycle_star")
        if prior_cycle_star is not None:
            prior_cycle_star = as_int_range(prior_cycle_star, "prior_cycle_star", 1, 5)

        cycle = get_cycle_or_404(rating_cycle_id)
        for m in DB["measures"].values():
            if m["rating_cycle_id"] == cycle["id"] and m["code"] == code:
                raise ApiError(
                    "ERR_DUPLICATE_MEASURE_CODE",
                    409,
                    "Measure code already used within the cycle",
                )
        measure = {
            "rating_cycle_id": cycle["id"],
            "code": code,
            "title": title,
            "domain": domain,
            "measure_type": measure_type,
            "weight": WEIGHT_BY_TYPE[measure_type],
            "direction": direction,
            "data_source": data_source,
            "improvement_eligible": improvement_eligible,
            "prior_cycle_star": prior_cycle_star,
            "status": "DRAFT",
        }
        mint_common_fields(measure)
        DB["measures"][measure["id"]] = measure
        return ok(serialize(measure), 201)

    @app.route("/api/measures", methods=["GET"])
    def list_measures():
        auth(ALL_ROLES)
        limit, offset = pagination_args()
        rows = sorted_rows(DB["measures"].values())
        rows = apply_filters(
            rows,
            [
                ("rating_cycle_id", filter_arg("rating_cycle_id")),
                ("status", filter_arg("status")),
                ("domain", filter_arg("domain")),
            ],
        )
        total = len(rows)
        page = rows[offset : offset + limit]
        return ok_list([serialize(r) for r in page], total, limit, offset)

    @app.route("/api/measures/<measureId>", methods=["GET"])
    def get_measure(measureId):
        auth(ALL_ROLES)
        measure = get_measure_or_404(measureId)
        return ok(serialize(measure))

    @app.route("/api/measures/<measureId>/transition", methods=["POST"])
    def transition_measure(measureId):
        auth(["StarsAnalyst"])
        data = body()
        to_state = as_enum(required(data, "to_state"), "to_state", MEASURE_STATES)
        measure = get_measure_or_404(measureId)
        cur = measure["status"]
        if (cur, to_state) not in LEGAL_TRANSITIONS:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                409,
                f"Cannot transition Measure from {cur} to {to_state}",
            )
        cycle = get_cycle_or_404(measure["rating_cycle_id"])
        if to_state == "ACTIVE":
            if cycle["status"] not in ("SETUP", "DATA_COLLECTION"):
                raise ApiError(
                    "ERR_CYCLE_STATE_FORBIDS",
                    409,
                    "Measure activation requires owning cycle in SETUP or "
                    "DATA_COLLECTION",
                )
        elif to_state == "RETIRED":
            if cycle["status"] in ("OFFICIAL_PUBLISHED", "CLOSED"):
                raise ApiError(
                    "ERR_CYCLE_STATE_FORBIDS",
                    409,
                    "Measure retirement forbidden once the owning cycle is "
                    "OFFICIAL_PUBLISHED or CLOSED",
                )
        measure["status"] = to_state
        touch(measure)
        return ok(serialize(measure))
