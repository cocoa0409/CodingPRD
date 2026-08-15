"""CareGap endpoints: open, close/reopen/exclude transitions, intervene."""
from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    credit_gap_close,
    credit_gap_exclude,
    credit_gap_open,
    credit_gap_reopen,
    gap_cycle,
    get_gap_or_404,
    get_measure_or_404,
    get_member_or_404,
    mint_common_fields,
    perf_for_measure,
    serialize,
    sorted_rows,
    touch,
)
from util import (
    apply_filters,
    as_enum,
    as_str,
    body,
    filter_arg,
    pagination_args,
    required,
)

GAP_TYPES = {"PHARMACY_ADHERENCE", "SCREENING", "FOLLOW_UP", "IMMUNIZATION"}
GAP_STATES = {"OPEN", "CLOSED", "REOPENED", "EXCLUDED"}
CHANNELS = {"CALL", "MAIL", "SMS", "PHARMACIST_CONSULT"}

INTERVENTION_CAP = 3


def _cycle_must_be_collecting(gap):
    cycle = gap_cycle(gap)
    if cycle is None or cycle["status"] != "DATA_COLLECTION":
        raise ApiError(
            "ERR_CYCLE_NOT_COLLECTING",
            409,
            "Care gap mutation requires owning cycle in DATA_COLLECTION",
        )


def register(app):
    @app.route("/api/care-gaps", methods=["POST"])
    def create_gap():
        auth(["QualityOps"])
        data = body()
        member_id = as_str(required(data, "member_id"), "member_id")
        measure_id = as_str(required(data, "measure_id"), "measure_id")
        gap_type = as_enum(required(data, "gap_type"), "gap_type", GAP_TYPES)

        member = get_member_or_404(member_id)
        measure = get_measure_or_404(measure_id)
        if member["status"] != "ENROLLED":
            raise ApiError(
                "ERR_MEMBER_NOT_ENROLLED",
                409,
                "Gap create requires member ENROLLED",
            )
        for g in DB["care_gaps"].values():
            if (
                g["member_id"] == member["id"]
                and g["measure_id"] == measure["id"]
                and g["status"] in ("OPEN", "REOPENED")
            ):
                raise ApiError(
                    "ERR_DUPLICATE_OPEN_GAP",
                    409,
                    "An OPEN or REOPENED gap already exists for (member, measure)",
                )
        is_pharm_gap = gap_type == "PHARMACY_ADHERENCE"
        is_pharm_measure = measure["data_source"] == "PHARMACY_PDE"
        if is_pharm_gap != is_pharm_measure:
            raise ApiError(
                "ERR_GAP_TYPE_MEASURE_MISMATCH",
                409,
                "PHARMACY_ADHERENCE gaps require a PHARMACY_PDE measure; other "
                "gap types require a non-PHARMACY_PDE measure",
            )
        gap = {
            "member_id": member["id"],
            "measure_id": measure["id"],
            "gap_type": gap_type,
            "intervention_count": 0,
            "last_intervention_channel": None,
            "status": "OPEN",
        }
        mint_common_fields(gap)
        DB["care_gaps"][gap["id"]] = gap
        # Credit the linked performance (denominator += 1) when mutable.
        credit_gap_open(gap)
        return ok(serialize(gap), 201)

    @app.route("/api/care-gaps", methods=["GET"])
    def list_gaps():
        auth(ALL_ROLES)
        limit, offset = pagination_args()
        rows = sorted_rows(DB["care_gaps"].values())
        rows = apply_filters(
            rows,
            [
                ("member_id", filter_arg("member_id")),
                ("measure_id", filter_arg("measure_id")),
                ("status", filter_arg("status")),
                ("gap_type", filter_arg("gap_type")),
            ],
        )
        total = len(rows)
        page = rows[offset : offset + limit]
        return ok_list([serialize(r) for r in page], total, limit, offset)

    @app.route("/api/care-gaps/<gapId>", methods=["GET"])
    def get_gap(gapId):
        auth(ALL_ROLES)
        gap = get_gap_or_404(gapId)
        return ok(serialize(gap))

    @app.route("/api/care-gaps/<gapId>/transition", methods=["POST"])
    def transition_gap(gapId):
        auth(["QualityOps"])
        data = body()
        to_state = as_enum(required(data, "to_state"), "to_state", GAP_STATES)
        gap = get_gap_or_404(gapId)
        cur = gap["status"]

        if to_state == "CLOSED":
            if cur not in ("OPEN", "REOPENED"):
                raise ApiError(
                    "ERR_GAP_NOT_OPEN", 409, "Close requires gap OPEN or REOPENED"
                )
            member = get_member_or_404(gap["member_id"])
            if member["status"] != "ENROLLED":
                raise ApiError(
                    "ERR_MEMBER_NOT_ENROLLED",
                    409,
                    "Gap close requires member ENROLLED",
                )
            _cycle_must_be_collecting(gap)
            perf = perf_for_measure(gap["measure_id"])
            if perf is None or perf["status"] == "LOCKED":
                raise ApiError(
                    "ERR_PERFORMANCE_LOCKED",
                    409,
                    "Linked performance is LOCKED or missing; numerator "
                    "mutations forbidden",
                )
            credit_gap_close(gap)
        elif to_state == "REOPENED":
            if cur != "CLOSED":
                raise ApiError(
                    "ERR_GAP_NOT_CLOSED", 409, "Reopen requires gap CLOSED"
                )
            _cycle_must_be_collecting(gap)
            perf = perf_for_measure(gap["measure_id"])
            if perf is not None and perf["status"] == "LOCKED":
                raise ApiError(
                    "ERR_PERFORMANCE_LOCKED",
                    409,
                    "Linked performance is LOCKED; numerator mutations forbidden",
                )
            credit_gap_reopen(gap)
        elif to_state == "EXCLUDED":
            if cur not in ("OPEN", "REOPENED"):
                raise ApiError(
                    "ERR_GAP_NOT_OPEN",
                    409,
                    "Exclusion requires gap OPEN or REOPENED",
                )
            _cycle_must_be_collecting(gap)
            perf = perf_for_measure(gap["measure_id"])
            if perf is not None and perf["status"] == "LOCKED":
                raise ApiError(
                    "ERR_PERFORMANCE_LOCKED",
                    409,
                    "Linked performance is LOCKED; denominator mutations "
                    "forbidden",
                )
            credit_gap_exclude(gap)
        else:  # OPEN: no transition targets OPEN
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                409,
                f"Cannot transition CareGap from {cur} to {to_state}",
            )
        gap["status"] = to_state
        touch(gap)
        return ok(serialize(gap))

    @app.route("/api/care-gaps/<gapId>/intervene", methods=["POST"])
    def intervene_gap(gapId):
        auth(["QualityOps"])
        data = body()
        channel = as_enum(required(data, "channel"), "channel", CHANNELS)
        gap = get_gap_or_404(gapId)
        if gap["status"] not in ("OPEN", "REOPENED"):
            raise ApiError(
                "ERR_GAP_NOT_OPEN",
                409,
                "Intervention requires gap OPEN or REOPENED",
            )
        if gap["intervention_count"] >= INTERVENTION_CAP:
            raise ApiError(
                "ERR_INTERVENTION_LIMIT_REACHED",
                409,
                "Gap already has 3 interventions",
            )
        if gap["gap_type"] != "PHARMACY_ADHERENCE":
            raise ApiError(
                "ERR_INTERVENTION_GAP_TYPE_MISMATCH",
                400,
                "Interventions only allowed on PHARMACY_ADHERENCE gaps",
            )
        gap["intervention_count"] += 1
        gap["last_intervention_channel"] = channel
        touch(gap)
        return ok(serialize(gap))
