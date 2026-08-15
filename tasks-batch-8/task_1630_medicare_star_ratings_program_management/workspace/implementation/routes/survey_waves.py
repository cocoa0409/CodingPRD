"""SurveyWave endpoints: plan, field/close/score transitions with window gates."""
from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    NON_TERMINAL_WAVE_STATES,
    get_cycle_or_404,
    get_vendor_or_404,
    get_wave_or_404,
    mint_common_fields,
    serialize,
    sorted_rows,
    touch,
    windows_intersect,
)
from util import (
    D,
    apply_filters,
    as_enum,
    as_int,
    as_iso_dt,
    as_positive_int,
    as_str,
    body,
    filter_arg,
    logical_now_dt,
    pagination_args,
    parse_dt,
    required,
    round4f,
)

SURVEY_TYPES = {"CAHPS", "HOS"}
WAVE_STATES = {"PLANNED", "FIELDING", "CLOSED_FIELD", "SCORED"}

MIN_RESPONSE_RATE = D("0.40")


def register(app):
    @app.route("/api/survey-waves", methods=["POST"])
    def create_wave():
        auth(["SurveyCoordinator"])
        data = body()
        rating_cycle_id = as_str(required(data, "rating_cycle_id"), "rating_cycle_id")
        survey_type = as_enum(
            required(data, "survey_type"), "survey_type", SURVEY_TYPES
        )
        vendor_id = as_str(required(data, "vendor_id"), "vendor_id")
        window_start = as_iso_dt(required(data, "window_start"), "window_start")
        window_end = as_iso_dt(required(data, "window_end"), "window_end")
        sample_size = as_positive_int(required(data, "sample_size"), "sample_size")

        cycle = get_cycle_or_404(rating_cycle_id)
        vendor = get_vendor_or_404(vendor_id)

        ws = parse_dt(window_start)
        we = parse_dt(window_end)
        if not ws < we:
            raise ApiError(
                "ERR_INVALID_WINDOW", 400, "window_start must be before window_end"
            )
        # Lane exclusivity: no intersection with a non-terminal wave in the
        # same (cycle, survey_type) lane; adjacency allowed.
        for w in DB["survey_waves"].values():
            if w["status"] not in NON_TERMINAL_WAVE_STATES:
                continue
            if (
                w["rating_cycle_id"] == cycle["id"]
                and w["survey_type"] == survey_type
                and windows_intersect(
                    ws, we, parse_dt(w["window_start"]), parse_dt(w["window_end"])
                )
            ):
                raise ApiError(
                    "ERR_SURVEY_WINDOW_OVERLAP",
                    409,
                    "New wave overlaps an existing non-terminal wave in the "
                    "same (cycle, survey_type) lane",
                )
        # Vendor capacity: intersecting non-terminal waves of this vendor must
        # remain strictly below max_concurrent_waves.
        overlapping = sum(
            1
            for w in DB["survey_waves"].values()
            if w["vendor_id"] == vendor["id"]
            and w["status"] in NON_TERMINAL_WAVE_STATES
            and windows_intersect(
                ws, we, parse_dt(w["window_start"]), parse_dt(w["window_end"])
            )
        )
        if overlapping >= vendor["max_concurrent_waves"]:
            raise ApiError(
                "ERR_VENDOR_CAPACITY_EXCEEDED",
                409,
                "Vendor's overlapping-wave count would reach "
                "max_concurrent_waves",
            )
        wave = {
            "rating_cycle_id": cycle["id"],
            "survey_type": survey_type,
            "vendor_id": vendor["id"],
            "window_start": window_start,
            "window_end": window_end,
            "sample_size": sample_size,
            "response_count": None,
            "response_rate": None,
            "sufficient": None,
            "status": "PLANNED",
        }
        mint_common_fields(wave)
        DB["survey_waves"][wave["id"]] = wave
        return ok(serialize(wave), 201)

    @app.route("/api/survey-waves", methods=["GET"])
    def list_waves():
        auth(ALL_ROLES)
        limit, offset = pagination_args()
        rows = sorted_rows(DB["survey_waves"].values())
        rows = apply_filters(
            rows,
            [
                ("rating_cycle_id", filter_arg("rating_cycle_id")),
                ("vendor_id", filter_arg("vendor_id")),
                ("survey_type", filter_arg("survey_type")),
                ("status", filter_arg("status")),
            ],
        )
        total = len(rows)
        page = rows[offset : offset + limit]
        return ok_list([serialize(r) for r in page], total, limit, offset)

    @app.route("/api/survey-waves/<waveId>", methods=["GET"])
    def get_wave(waveId):
        auth(ALL_ROLES)
        wave = get_wave_or_404(waveId)
        return ok(serialize(wave))

    @app.route("/api/survey-waves/<waveId>/transition", methods=["POST"])
    def transition_wave(waveId):
        auth(["SurveyCoordinator"])
        data = body()
        to_state = as_enum(required(data, "to_state"), "to_state", WAVE_STATES)
        response_count = None
        if to_state == "SCORED":
            response_count = as_int(
                required(data, "response_count"), "response_count"
            )
        wave = get_wave_or_404(waveId)
        cur = wave["status"]
        legal = {
            ("PLANNED", "FIELDING"),
            ("FIELDING", "CLOSED_FIELD"),
            ("CLOSED_FIELD", "SCORED"),
        }
        if (cur, to_state) not in legal:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                409,
                f"Cannot transition SurveyWave from {cur} to {to_state}",
            )
        now = logical_now_dt()
        if to_state == "FIELDING":
            if not (parse_dt(wave["window_start"]) <= now < parse_dt(wave["window_end"])):
                raise ApiError(
                    "ERR_WAVE_OUTSIDE_WINDOW",
                    409,
                    "Logical clock outside the wave's fielding window",
                )
        elif to_state == "CLOSED_FIELD":
            if not now >= parse_dt(wave["window_end"]):
                raise ApiError(
                    "ERR_WAVE_OUTSIDE_WINDOW",
                    409,
                    "Logical clock before window_end; cannot close fielding",
                )
        elif to_state == "SCORED":
            if response_count < 0 or response_count > wave["sample_size"]:
                raise ApiError(
                    "ERR_INVALID_REQUEST",
                    400,
                    "response_count must be between 0 and sample_size inclusive",
                )
            wave["response_count"] = response_count
            rate = round4f(D(response_count) / D(wave["sample_size"]))
            wave["response_rate"] = rate
            wave["sufficient"] = bool(D(str(rate)) >= MIN_RESPONSE_RATE)
        wave["status"] = to_state
        touch(wave)
        return ok(serialize(wave))
