"""TestPanel endpoints."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_LAB_DIRECTOR, ROLE_LAB_TECH, ROLE_ORDERING_PROVIDER, require_roles
from ..errors import err_validation
from ..helpers import (
    assert_array,
    assert_enum,
    assert_integer,
    assert_string,
    require_json_object,
)
from ..responses import created, ok
from ..services.lookups import get_test_panel
from ..services.serialize import test_panel_view
from ..services.workflows import create_common_fields
from ..store import store

bp = Blueprint("test_panels", __name__)

PANEL_CODE_PATTERN = r"^[A-Z0-9_]{3,20}$"
COMPLEXITY_VALUES = ["WAIVED", "MODERATE", "HIGH"]
SPECIMEN_TYPES = ["BLOOD", "URINE", "CSF", "SWAB"]


def _validate_analytes(items: list) -> list[dict]:
    if not items:
        raise err_validation("analytes must contain at least one entry")
    seen_codes = set()
    out: list[dict] = []
    for i, a in enumerate(items):
        if not isinstance(a, dict):
            raise err_validation(f"analytes[{i}] must be an object")
        code = assert_string(a.get("analyte_code"), f"analytes[{i}].analyte_code")
        if code in seen_codes:
            raise err_validation(f"analytes[{i}].analyte_code '{code}' duplicated")
        seen_codes.add(code)
        unit = assert_string(a.get("unit"), f"analytes[{i}].unit")
        cl = a.get("critical_low")
        ch = a.get("critical_high")
        if cl is not None and not isinstance(cl, (int, float)):
            raise err_validation(f"analytes[{i}].critical_low must be a number or null")
        if ch is not None and not isinstance(ch, (int, float)):
            raise err_validation(f"analytes[{i}].critical_high must be a number or null")
        if cl is not None and ch is not None and not (cl < ch):
            raise err_validation(f"analytes[{i}]: critical_low must be < critical_high")
        out.append(
            {
                "analyte_code": code,
                "unit": unit,
                "critical_low": cl,
                "critical_high": ch,
            }
        )
    return out


@bp.route("/test-panels", methods=["POST"])
@require_roles(ROLE_LAB_DIRECTOR)
def create_panel(**_):
    body = require_json_object()
    code = assert_string(body.get("code"), "code", pattern=PANEL_CODE_PATTERN)
    name = assert_string(body.get("name"), "name")
    complexity = assert_enum(body.get("clia_complexity"), "clia_complexity", COMPLEXITY_VALUES)
    specimen_type = assert_enum(body.get("specimen_type"), "specimen_type", SPECIMEN_TYPES)
    stability = assert_integer(body.get("stability_minutes"), "stability_minutes", minimum=1)
    analytes_raw = assert_array(body.get("analytes"), "analytes")
    analytes = _validate_analytes(analytes_raw)

    with store().lock:
        for p in store().test_panels.values():
            if p["code"] == code:
                raise err_validation(f"panel code {code} already exists")
        row = {
            **create_common_fields(),
            "code": code,
            "name": name,
            "clia_complexity": complexity,
            "specimen_type": specimen_type,
            "stability_minutes": stability,
            "analytes": analytes,
        }
        store().test_panels[row["id"]] = row
    return created(test_panel_view(row))


@bp.route("/test-panels/<pid>", methods=["GET"])
@require_roles(ROLE_ORDERING_PROVIDER, ROLE_LAB_TECH, ROLE_LAB_DIRECTOR)
def fetch_panel(pid, **_):
    row = get_test_panel(pid)
    return ok(test_panel_view(row))
