"""CutPointSet endpoints: create, list, get, OCC-guarded row replace, publish."""
from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    get_cycle_or_404,
    get_set_or_404,
    mint_common_fields,
    publish_cutpoint_set,
    serialize,
    sorted_rows,
    touch,
)
from util import (
    D,
    apply_filters,
    as_int,
    as_list,
    as_num,
    as_str,
    body,
    filter_arg,
    pagination_args,
    required,
)

SET_STATES = {"DRAFT", "PUBLISHED", "SUPERSEDED"}

FLOOR_FIELDS = ("band_2_floor", "band_3_floor", "band_4_floor", "band_5_floor")


def _validate_row_shapes(rows):
    """Shape validation for cut point rows (priority 3)."""
    parsed = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, f"rows[{i}] must be an object"
            )
        measure_id = as_str(
            required(row, "measure_id"), f"rows[{i}].measure_id"
        )
        floors = {}
        for f in FLOOR_FIELDS:
            floors[f] = as_num(required(row, f), f"rows[{i}].{f}")
        parsed.append({"measure_id": measure_id, **floors})
    return parsed


def _check_row_measures_exist(rows):
    for row in rows:
        m = DB["measures"].get(row["measure_id"])
        if m is None:
            raise ApiError("ERR_MEASURE_NOT_FOUND", 404, "Measure not found")


def _check_row_cycle_match(rows, cycle_id):
    for row in rows:
        m = DB["measures"][row["measure_id"]]
        if m["rating_cycle_id"] != cycle_id:
            raise ApiError(
                "ERR_CUTPOINT_MEASURE_CYCLE_MISMATCH",
                409,
                "Cut point row references a measure outside the set's cycle",
            )


def _check_monotonic(rows):
    """Floors strictly monotonic per the row measure's direction (priority 9)."""
    for row in rows:
        m = DB["measures"][row["measure_id"]]
        f = [D(str(row[k])) for k in FLOOR_FIELDS]
        if m["direction"] == "HIGHER_BETTER":
            ok_order = f[0] < f[1] < f[2] < f[3]
        else:
            ok_order = f[3] < f[2] < f[1] < f[0]
        if not ok_order:
            raise ApiError(
                "ERR_CUTPOINTS_NON_MONOTONIC",
                400,
                "Cut point floors not strictly monotonic for the measure's "
                "direction",
            )


def register(app):
    @app.route("/api/cutpoint-sets", methods=["POST"])
    def create_set():
        auth(["StarsAnalyst"])
        data = body()
        rating_cycle_id = as_str(required(data, "rating_cycle_id"), "rating_cycle_id")
        label = as_str(required(data, "label"), "label")
        rows = data.get("rows", [])
        rows = _validate_row_shapes(as_list(rows, "rows"))

        cycle = get_cycle_or_404(rating_cycle_id)
        _check_row_measures_exist(rows)
        _check_row_cycle_match(rows, cycle["id"])
        _check_monotonic(rows)

        cps = {
            "rating_cycle_id": cycle["id"],
            "label": label,
            "rows": rows,
            "status": "DRAFT",
        }
        mint_common_fields(cps)
        DB["cutpoint_sets"][cps["id"]] = cps
        # Note: set creation alone does NOT re-band existing performances.
        return ok(serialize(cps), 201)

    @app.route("/api/cutpoint-sets", methods=["GET"])
    def list_sets():
        auth(ALL_ROLES)
        limit, offset = pagination_args()
        rows = sorted_rows(DB["cutpoint_sets"].values())
        rows = apply_filters(
            rows,
            [
                ("rating_cycle_id", filter_arg("rating_cycle_id")),
                ("status", filter_arg("status")),
            ],
        )
        total = len(rows)
        page = rows[offset : offset + limit]
        return ok_list([serialize(r) for r in page], total, limit, offset)

    @app.route("/api/cutpoint-sets/<setId>", methods=["GET"])
    def get_set(setId):
        auth(ALL_ROLES)
        cps = get_set_or_404(setId)
        return ok(serialize(cps))

    @app.route("/api/cutpoint-sets/<setId>", methods=["PUT"])
    def replace_rows(setId):
        auth(["StarsAnalyst"])
        data = body()
        rows = _validate_row_shapes(as_list(required(data, "rows"), "rows"))
        expected_version = as_int(
            required(data, "expected_cutpoint_set_version"),
            "expected_cutpoint_set_version",
        )
        cps = get_set_or_404(setId)
        _check_row_measures_exist(rows)
        # OCC (priority 5) precedes the DRAFT-state gate (priority 7).
        if expected_version != cps["version"]:
            raise ApiError(
                "ERR_STALE_VERSION",
                412,
                "expected_cutpoint_set_version does not match the set's "
                "current version",
            )
        if cps["status"] != "DRAFT":
            raise ApiError(
                "ERR_CUTPOINT_SET_IMMUTABLE",
                409,
                "Row replace requires the set to be DRAFT",
            )
        _check_row_cycle_match(rows, cps["rating_cycle_id"])
        _check_monotonic(rows)
        cps["rows"] = rows
        touch(cps)
        return ok(serialize(cps))

    @app.route("/api/cutpoint-sets/<setId>/publish", methods=["POST"])
    def publish_set(setId):
        auth(["StarsAdmin"])
        data = body()
        expected_cycle_version = as_int(
            required(data, "expected_rating_cycle_version"),
            "expected_rating_cycle_version",
        )
        cps = get_set_or_404(setId)
        cycle = get_cycle_or_404(cps["rating_cycle_id"])
        # OCC on the cycle (priority 5) precedes state gates (priority 7).
        if expected_cycle_version != cycle["version"]:
            raise ApiError(
                "ERR_STALE_VERSION",
                412,
                "expected_rating_cycle_version does not match the cycle's "
                "current version",
            )
        if cycle["status"] != "CUTPOINT_REVIEW":
            raise ApiError(
                "ERR_CYCLE_STATE_FORBIDS",
                409,
                "Publishing a cut point set requires the cycle in CUTPOINT_REVIEW",
            )
        if cps["status"] != "DRAFT":
            raise ApiError(
                "ERR_CUTPOINT_SET_IMMUTABLE",
                409,
                "Publish requires the set to be DRAFT",
            )
        publish_cutpoint_set(cps)
        return ok(serialize(cps))
