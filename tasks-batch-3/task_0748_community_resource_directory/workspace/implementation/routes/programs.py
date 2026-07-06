from flask import request

from db import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_OWNERSHIP_VIOLATION,
    ERR_PROGRAM_NOT_FOUND,
    ERR_PROVIDER_NOT_FOUND,
    ERR_FUNDER_NOT_FOUND,
    ERR_STALE_PROGRAM_VERSION,
    ERR_WINDOW_IN_PAST,
    ERR_WINDOW_OVERLAP,
    ERR_WINDOW_SLOTS_EXCEED_CAPACITY,
    raise_error,
)
from middleware import get_auth, require_roles
from response import paginate, success
from services import (
    _touch,
    make_availability,
    make_program,
    recompute_program_posture,
    serialise_availability,
    serialise_program,
)
from util import parse_ts
from validate import (
    CATEGORY_ENUM,
    parse_pagination,
    require_body,
    require_enum,
    require_int,
    require_str,
)


def _program_or_404(pid: str):
    p = db.programs.get(pid)
    if not p:
        raise_error(ERR_PROGRAM_NOT_FOUND, f"program {pid} not found")
    return p


def _check_provider_ownership_of_program(program: dict) -> None:
    uid, role = get_auth()
    if role == "ProviderStaff" and uid != program["provider_id"]:
        raise_error(ERR_OWNERSHIP_VIOLATION, "ProviderStaff does not own this program's provider")


def register(app):
    @app.post("/programs")
    @require_roles("PlatformAdmin")
    def create_program():
        body = require_body(request.get_json(silent=True))
        provider_id = require_str(body, "provider_id")
        funder_id = require_str(body, "funder_id")
        # Body FK resolution: use ERR_INVALID_REQUEST per priority 11.
        if provider_id not in db.providers:
            raise_error(ERR_INVALID_REQUEST, f"provider_id {provider_id} not found")
        if funder_id not in db.funders:
            raise_error(ERR_INVALID_REQUEST, f"funder_id {funder_id} not found")
        category = require_enum(body, "category", CATEGORY_ENUM)
        income_max = require_int(body, "eligibility_income_max_cents")
        if income_max < 0:
            raise_error(ERR_INVALID_REQUEST, "eligibility_income_max_cents must be >= 0")
        age_min = require_int(body, "eligibility_age_min")
        age_max = require_int(body, "eligibility_age_max")
        if not (0 <= age_min <= 120):
            raise_error(ERR_INVALID_REQUEST, "eligibility_age_min out of [0,120]")
        if not (0 <= age_max <= 120):
            raise_error(ERR_INVALID_REQUEST, "eligibility_age_max out of [0,120]")
        if age_max < age_min:
            raise_error(ERR_INVALID_REQUEST, "eligibility_age_max must be >= eligibility_age_min")
        unit_cost = require_int(body, "unit_cost_cents")
        if unit_cost < 0:
            raise_error(ERR_INVALID_REQUEST, "unit_cost_cents must be >= 0")
        capacity = require_int(body, "capacity_slots_total")
        if capacity < 1:
            raise_error(ERR_INVALID_REQUEST, "capacity_slots_total must be >= 1")

        entity = make_program(provider_id, funder_id, category, income_max, age_min,
                              age_max, unit_cost, capacity)
        return success(serialise_program(entity), 201)

    @app.get("/programs/<pid>")
    @require_roles("PlatformAdmin", "ProviderStaff", "Caseworker", "Client")
    def get_program(pid):
        p = _program_or_404(pid)
        # PRD 2.7 / 1.7: ProviderStaff must own the program; Client has read-only browse
        # (no ownership check for the read).
        uid, role = get_auth()
        if role == "ProviderStaff" and uid != p["provider_id"]:
            raise_error(ERR_OWNERSHIP_VIOLATION, "ProviderStaff does not own this program's provider")
        return success(serialise_program(p), 200)

    @app.get("/programs")
    @require_roles("PlatformAdmin", "Caseworker")
    def list_programs():
        limit, offset = parse_pagination(request.args)
        pid_filter = request.args.get("provider_id")
        fid_filter = request.args.get("funder_id")
        cat_filter = request.args.get("category")

        items = list(db.programs.values())
        if pid_filter is not None:
            items = [p for p in items if p["provider_id"] == pid_filter]
        if fid_filter is not None:
            items = [p for p in items if p["funder_id"] == fid_filter]
        if cat_filter is not None:
            items = [p for p in items if p["category"] == cat_filter]
        items.sort(key=lambda x: x["created_at"])
        window, pg = paginate(items, limit, offset)
        return success([serialise_program(p) for p in window], 200, "array", pg)

    @app.patch("/programs/<pid>")
    @require_roles("PlatformAdmin")
    def patch_program(pid):
        p = _program_or_404(pid)
        body = require_body(request.get_json(silent=True))
        expected = require_int(body, "expected_program_version")

        # OCC (priority 32).
        if expected != p["version"]:
            raise_error(ERR_STALE_PROGRAM_VERSION,
                        f"expected_program_version {expected} != current {p['version']}")

        # Apply patchable fields.
        if "eligibility_income_max_cents" in body:
            v = body["eligibility_income_max_cents"]
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise_error(ERR_INVALID_REQUEST, "eligibility_income_max_cents must be int >= 0")
            p["eligibility_income_max_cents"] = v
        if "eligibility_age_min" in body:
            v = body["eligibility_age_min"]
            if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 120:
                raise_error(ERR_INVALID_REQUEST, "eligibility_age_min out of [0,120]")
            p["eligibility_age_min"] = v
        if "eligibility_age_max" in body:
            v = body["eligibility_age_max"]
            if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 120:
                raise_error(ERR_INVALID_REQUEST, "eligibility_age_max out of [0,120]")
            p["eligibility_age_max"] = v
        if p["eligibility_age_max"] < p["eligibility_age_min"]:
            raise_error(ERR_INVALID_REQUEST, "eligibility_age_max must be >= eligibility_age_min")
        if "unit_cost_cents" in body:
            v = body["unit_cost_cents"]
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise_error(ERR_INVALID_REQUEST, "unit_cost_cents must be int >= 0")
            p["unit_cost_cents"] = v
        if "capacity_slots_total" in body:
            v = body["capacity_slots_total"]
            if not isinstance(v, int) or isinstance(v, bool) or v < 1:
                raise_error(ERR_INVALID_REQUEST, "capacity_slots_total must be int >= 1")
            p["capacity_slots_total"] = v
            # Capacity total change may cause a posture recompute.
            recompute_program_posture(p)

        _touch(p)
        return success(serialise_program(p), 200)

    @app.post("/programs/<pid>/availability-windows")
    @require_roles("ProviderStaff", "PlatformAdmin")
    def create_window(pid):
        p = _program_or_404(pid)
        _check_provider_ownership_of_program(p)
        body = require_body(request.get_json(silent=True))
        start_s = require_str(body, "start_ts")
        end_s = require_str(body, "end_ts")
        max_slots = require_int(body, "max_slots")
        if max_slots < 1:
            raise_error(ERR_INVALID_REQUEST, "max_slots must be >= 1")

        start_dt = parse_ts(start_s)
        end_dt = parse_ts(end_s)
        if not (end_dt > start_dt):
            raise_error(ERR_INVALID_REQUEST, "end_ts must be strictly greater than start_ts")

        # Priority 25: start_ts must be strictly greater than the current logical clock.
        if not (start_dt > db.clock):
            raise_error(ERR_WINDOW_IN_PAST, "start_ts must be strictly after current clock")

        # Priority 26: no half-open overlap with any existing window for this program.
        for w in db.availability_windows.values():
            if w["program_id"] != pid:
                continue
            w_start = parse_ts(w["start_ts"])
            w_end = parse_ts(w["end_ts"])
            if start_dt < w_end and w_start < end_dt:
                raise_error(ERR_WINDOW_OVERLAP,
                            "window overlaps existing availability window")

        # Priority 30: sum of max_slots (including new) must be <= program.capacity_slots_total.
        current_sum = sum(
            w["max_slots"] for w in db.availability_windows.values() if w["program_id"] == pid
        )
        if current_sum + max_slots > p["capacity_slots_total"]:
            raise_error(ERR_WINDOW_SLOTS_EXCEED_CAPACITY,
                        "sum of max_slots exceeds program capacity_slots_total")

        entity = make_availability(pid, start_s, end_s, max_slots)
        return success(serialise_availability(entity), 201)

    @app.get("/programs/<pid>/availability-windows")
    @require_roles("ProviderStaff", "PlatformAdmin", "Caseworker")
    def list_windows(pid):
        p = _program_or_404(pid)
        _check_provider_ownership_of_program(p)
        limit, offset = parse_pagination(request.args)
        items = [w for w in db.availability_windows.values() if w["program_id"] == pid]
        items.sort(key=lambda x: x["created_at"])
        window, pg = paginate(items, limit, offset)
        return success([serialise_availability(w) for w in window], 200, "array", pg)
