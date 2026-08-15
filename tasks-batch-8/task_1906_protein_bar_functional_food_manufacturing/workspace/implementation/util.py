"""Datetime parsing, Decimal helpers, and request-shape validation helpers."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR, getcontext

from errors import ApiError, invalid_request, invalid_enum

getcontext().prec = 40

ALLERGEN_ENUM = ["MILK", "SOY", "PEANUT", "TREE_NUT", "WHEAT", "EGG", "SESAME"]
HIGH_RISK_ALLERGENS = {"PEANUT", "TREE_NUT"}
CLAIM_TAG_ENUM = ["HIGH_PROTEIN", "GOOD_SOURCE_PROTEIN", "LOW_SUGAR", "GLUTEN_FREE"]
CLAIM_TYPE_ENUM = ["NUTRIENT_CONTENT", "STRUCTURE_FUNCTION"]
CATEGORY_ENUM = ["PROTEIN", "SWEETENER", "BINDER", "FAT", "FLAVOR", "ADDITIVE"]

ROLES = [
    "PlantAdmin",
    "FormulationScientist",
    "QualityManager",
    "ProductionPlanner",
    "LabTechnician",
    "BrandCustomerRep",
]


def D(x):
    """Exact Decimal from int/float/str."""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def round2(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ceil2(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def floor_int(d):
    return int(d.to_integral_value(rounding=ROUND_FLOOR))


def num(d):
    """Serialize a Decimal as a JSON number."""
    if isinstance(d, Decimal):
        return float(d)
    return d


def parse_dt(value, field):
    """Parse an ISO 8601 datetime; naive values are treated as UTC."""
    if not isinstance(value, str):
        raise invalid_request(f"Field '{field}' must be an ISO 8601 datetime string")
    s = value.strip()
    try:
        s2 = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
        dt = datetime.fromisoformat(s2)
    except (ValueError, TypeError):
        raise invalid_request(f"Field '{field}' is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field):
    if not isinstance(value, str):
        raise invalid_request(f"Parameter '{field}' must be a YYYY-MM-DD date string")
    try:
        d = datetime.strptime(value.strip(), "%Y-%m-%d")
    except (ValueError, TypeError):
        raise invalid_request(f"Parameter '{field}' is not a valid YYYY-MM-DD date")
    return d.replace(tzinfo=timezone.utc)


# ---------- request body helpers ----------

def get_body(request):
    if request.data:
        body = request.get_json(force=True, silent=True)
        if body is None:
            raise invalid_request("Request body must be a valid JSON object")
        if not isinstance(body, dict):
            raise invalid_request("Request body must be a JSON object")
        return body
    return {}


def require(body, field):
    if field not in body or body[field] is None:
        raise invalid_request(f"Missing required field '{field}'")
    return body[field]


def opt(body, field, default=None):
    v = body.get(field, default)
    return default if v is None else v


def check_str(v, field):
    if not isinstance(v, str):
        raise invalid_request(f"Field '{field}' must be a string")
    return v


def check_bool(v, field):
    if not isinstance(v, bool):
        raise invalid_request(f"Field '{field}' must be a boolean")
    return v


def check_int(v, field, min_v=None):
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"Field '{field}' must be an integer")
    if min_v is not None and v < min_v:
        raise invalid_request(f"Field '{field}' must be >= {min_v}")
    return v


def check_number(v, field, gt=None, gte=None, lte=None):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid_request(f"Field '{field}' must be a number")
    d = D(v)
    if gt is not None and not d > D(gt):
        raise invalid_request(f"Field '{field}' must be > {gt}")
    if gte is not None and not d >= D(gte):
        raise invalid_request(f"Field '{field}' must be >= {gte}")
    if lte is not None and not d <= D(lte):
        raise invalid_request(f"Field '{field}' must be <= {lte}")
    return d


def check_enum(v, field, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise invalid_enum(
            f"Field '{field}' must be one of {', '.join(allowed)}")
    return v


def check_array(v, field, min_len=None):
    if not isinstance(v, list):
        raise invalid_request(f"Field '{field}' must be an array")
    if min_len is not None and len(v) < min_len:
        raise invalid_request(f"Field '{field}' must contain at least {min_len} item(s)")
    return v


def check_allergen_array(v, field):
    check_array(v, field)
    for m in v:
        if not isinstance(m, str) or m not in ALLERGEN_ENUM:
            raise invalid_enum(
                f"Field '{field}' members must be allergen enum values")
    return list(v)
