"""Band 3 request-shape validation (PRD 2.5 band 3, V-REQ-1)."""

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from errors import ApiError

_ISO = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,6})\d*)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)

TERRITORY = re.compile(r"^[A-Z]{2}$")


def invalid():
    raise ApiError("ERR_INVALID_REQUEST")


def field(name, ftype, **kw):
    spec = {"name": name, "type": ftype}
    spec.update(kw)
    return spec


class ClientInstant(datetime):
    """A datetime parsed from a client-supplied field.

    PRD 2.4 fixes the three-fractional-digit rendering for the instants the
    *server* stamps (`created_at`, `updated_at`, `approved_at`, `certified_at`,
    `snapshot_at`).  A client-supplied instant such as a run's
    `planned_start_utc` is an input, so it is echoed back exactly as it was
    supplied; this subclass carries that original text alongside the parsed
    value used for every comparison.
    """

    raw = None

    @classmethod
    def wrap(cls, stamp, raw):
        instance = cls(stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute,
                       stamp.second, stamp.microsecond, tzinfo=stamp.tzinfo)
        instance.raw = raw
        return instance


def parse_datetime(value):
    if not isinstance(value, str):
        invalid()
    match = _ISO.match(value.strip())
    if not match:
        invalid()
    year, month, day, hour, minute = (int(match.group(i)) for i in range(1, 6))
    second = int(match.group(6) or 0)
    fraction = match.group(7) or ""
    micro = int((fraction + "000000")[:6]) if fraction else 0
    offset = match.group(8)
    try:
        stamp = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    except ValueError:
        invalid()
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta = int(body[:2]) * 60 + int(body[2:])
        stamp = stamp - timedelta(minutes=sign * delta)
    return ClientInstant.wrap(stamp, value.strip())


def _check_range(spec, value):
    if "min" in spec and value < Decimal(str(spec["min"])):
        invalid()
    if "exclusive_min" in spec and value <= Decimal(str(spec["exclusive_min"])):
        invalid()
    if "max" in spec and value > Decimal(str(spec["max"])):
        invalid()


def _coerce(spec, value):
    kind = spec["type"]

    if kind == "boolean":
        if not isinstance(value, bool):
            invalid()
        return value

    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            invalid()
        _check_range(spec, Decimal(value))
        return value

    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            invalid()
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            invalid()
        if not number.is_finite():
            invalid()
        if "decimals" in spec:
            exponent = number.as_tuple().exponent
            if isinstance(exponent, int) and -exponent > spec["decimals"]:
                invalid()
        _check_range(spec, number)
        return number

    if kind == "string":
        if not isinstance(value, str):
            invalid()
        if "enum" in spec and value not in spec["enum"]:
            invalid()
        if "min_len" in spec and len(value) < spec["min_len"]:
            invalid()
        if "max_len" in spec and len(value) > spec["max_len"]:
            invalid()
        if spec.get("non_empty") and value.strip() == "":
            invalid()
        if "regex" in spec and not spec["regex"].match(value):
            invalid()
        return value

    if kind == "datetime":
        return parse_datetime(value)

    if kind == "array":
        if not isinstance(value, list):
            invalid()
        if spec.get("non_empty") and not value:
            invalid()
        item = spec.get("item")
        if item is not None:
            return [_coerce(item, element) for element in value]
        return list(value)

    invalid()


def validate(spec, payload):
    """Validate `payload` against a field spec list, returning coerced values."""
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        invalid()
    result = {}
    for entry in spec:
        name = entry["name"]
        if name not in payload or payload[name] is None:
            if entry.get("required"):
                invalid()
            result[name] = entry.get("default")
            continue
        result[name] = _coerce(entry, payload[name])
    return result
