"""Common entity helpers — common-fields stamping, version bumps, validation utilities."""

from decimal import Decimal, ROUND_HALF_UP

from errors import raise_error, ERR_INVALID_REQUEST, ERR_VERSION_CONFLICT
from db import new_id
from services.time_util import utc_now_iso


def stamp_create(entity: dict, with_common_fields: bool = True):
    """Stamp a freshly created entity with id, timestamps and starting version=1."""
    entity.setdefault("id", new_id())
    if with_common_fields:
        now = utc_now_iso()
        entity["created_at"] = now
        entity["updated_at"] = now
        entity["version"] = 1
    else:
        entity["created_at"] = utc_now_iso()
    return entity


def stamp_subordinate(entity: dict):
    """For append-only sub-entities (no version/updated_at)."""
    entity.setdefault("id", new_id())
    entity["created_at"] = utc_now_iso()
    return entity


def bump(entity: dict):
    """Bump version and updated_at on any mutation."""
    entity["version"] = int(entity.get("version", 1)) + 1
    entity["updated_at"] = utc_now_iso()
    return entity


def check_version(entity: dict, body: dict):
    """Optimistic-concurrency check. Skipped when `version` is omitted from body."""
    if not isinstance(body, dict):
        return
    if "version" in body and body["version"] is not None:
        try:
            client_version = int(body["version"])
        except (ValueError, TypeError):
            raise_error(ERR_VERSION_CONFLICT, "version must be an integer")
        if client_version != int(entity.get("version", 1)):
            raise_error(ERR_VERSION_CONFLICT, "version does not match server")


def require_body_dict(body):
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_field(body: dict, name: str, types=None):
    if name not in body or body[name] is None:
        raise_error(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    val = body[name]
    if types is not None and not isinstance(val, types):
        raise_error(ERR_INVALID_REQUEST, f"Field {name} has wrong type")
    return val


def require_enum(body: dict, name: str, allowed):
    val = require_field(body, name, str)
    if val not in allowed:
        raise_error(ERR_INVALID_REQUEST,
                    f"Field {name} must be one of {sorted(allowed)}")
    return val


def round_half_up(n) -> int:
    """Round a numeric value half-up to a whole integer using Decimal."""
    d = Decimal(str(n)) if not isinstance(n, Decimal) else n
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_decimal(n, places=0):
    d = Decimal(str(n)) if not isinstance(n, Decimal) else n
    quant = Decimal("1") if places == 0 else Decimal("1").scaleb(-places)
    return d.quantize(quant, rounding=ROUND_HALF_UP)
