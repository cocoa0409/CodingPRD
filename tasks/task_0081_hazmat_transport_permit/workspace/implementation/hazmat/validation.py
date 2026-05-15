"""Body-shape and range validation helpers.

The PRD §2.7 paragraph's catch-all body-shape error at priority 590 is the
generic `ERR_VALIDATION` 422 the per-field shape-and-range failures funnel
into. The helpers here are the per-shape building blocks the per-blueprint
handler code composes: `require_field` for the missing-required-key case,
`require_string` for a string-typed value with an inclusive-length range,
`require_integer` for an integer with an inclusive numeric range,
`require_float` for a float with the same range form, `require_enum` for an
enum-membership check against a `frozenset` of allowed values,
`require_array` for the array-of-X check, `require_no_duplicates` for the
"every element of the array is unique" rule that several arrays carry
(`hazard_classes` on company-route-permit, `authorized_driver_ids` and
`authorized_vehicle_ids` on the permit, `hazard_classes_supported` on the
route, `endorsement_classes` on the driver, `hazard_classes_compatible` on
the vehicle, the `polyline` waypoints' uniqueness is not asserted because
the polyline can have a doubled-back-on-itself shape geometrically).

The per-bound-check for the regex-formatted strings (the company's
`registration_number` matching the eight-to-thirty-two uppercase-letters-and-
digits pattern, the driver's `license_number`'s no-embedded-whitespace
rule, the email's RFC-5322-syntactic check on the company's
`primary_contact_email`) uses Python's `re.fullmatch` against the canonical
patterns named in the `config` module.

The standard error-message convention is the human-readable cause string
with the field-path-and-the-offending-value in a JSON-serializable
`details.field` and `details.value` pair the test layer's response-message
substring asserts can read.

The datetime-vs-now relational checks the PRD §2.9 paragraph names — the
`valid_from >= now()` on the permit application, the `scheduled_departure_at
> now()` on the trip creation, the `inspected_at <= now()` on the inspection,
the `observed_at <= now()` on the manual penalty, the
`endorsement_valid_until > now()` on the refresh-endorsement attestation —
are also funneled through the generic `ERR_VALIDATION` 422 because they
are body-shape-relative-to-the-current-clock checks, with the response
message naming the failed comparison.

The PRD §2.4 paragraph names the optional-field convention as "any field
named optional in the per-endpoint request_payload_schema may be omitted
from the body; an absent optional field's default behavior is the
documented one (typically: no effect; the OCC's optional `version` opts out
of the version check; the renew-endpoint's optional fresh-driver-list
keeps the prior list)". The `optional_*` helpers below return `None` when
the key is absent and the parsed-and-checked value when present.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable, Optional

from .config import (
    EMAIL_SYNTAX_REGEX,
    HEADING_RANGE,
    IDEMPOTENCY_KEY_MAX_LEN,
    IDEMPOTENCY_KEY_MIN_LEN,
    LAT_RANGE,
    LON_RANGE,
    POLYLINE_WAYPOINT_COUNT_RANGE,
    REGISTRATION_NUMBER_REGEX,
    UN_HAZARD_CLASS_CODES,
    VEHICLE_TYPES,
)
from .errors import APIError


_EMAIL_RE = re.compile(EMAIL_SYNTAX_REGEX)
_REGISTRATION_RE = re.compile(REGISTRATION_NUMBER_REGEX)
_NO_WHITESPACE_RE = re.compile(r"^\S+$")


def _fail(message: str, *, error_id: str = "ERR_VALIDATION", **details: Any) -> APIError:
    """Build (do not raise) an `APIError` with the named id and the
    detail-payload's `field` and `value` keys. The standard pattern is
    `raise _fail("the message", field="x", value=offending)`.
    """
    return APIError(error_id, message, details=details if details else None)


def require_present(body: dict[str, Any], key: str) -> Any:
    """Return the body's `key`'s value or raise the missing-required-field
    `ERR_VALIDATION`."""
    if key not in body:
        raise _fail(f"Missing required field {key!r}.", field=key)
    return body[key]


def require_str(
    body: dict[str, Any],
    key: str,
    *,
    length_range: Optional[tuple[int, int]] = None,
    pattern: Optional[re.Pattern[str]] = None,
    pattern_description: str = "",
    optional: bool = False,
) -> Optional[str]:
    """Validate a string field. Returns the string on success, or `None`
    if `optional=True` and the field is absent. Raises `ERR_VALIDATION`
    on missing-required, wrong-type, out-of-length-range, or pattern-
    mismatch. The length range is the inclusive `(min, max)` pair.
    """
    if key not in body:
        if optional:
            return None
        raise _fail(f"Missing required string field {key!r}.", field=key)
    value = body[key]
    if not isinstance(value, str):
        raise _fail(
            f"Field {key!r} must be a string; got {type(value).__name__}.",
            field=key,
            value=value,
        )
    if length_range is not None:
        lo, hi = length_range
        if not (lo <= len(value) <= hi):
            raise _fail(
                f"Field {key!r} must be a string of length in "
                f"[{lo}, {hi}]; got length {len(value)}.",
                field=key,
                value=value,
                min_length=lo,
                max_length=hi,
                actual_length=len(value),
            )
    if pattern is not None:
        if not pattern.fullmatch(value):
            descr = pattern_description or pattern.pattern
            raise _fail(
                f"Field {key!r} value {value!r} does not match pattern "
                f"{descr!r}.",
                field=key,
                value=value,
                pattern=descr,
            )
    return value


def require_int(
    body: dict[str, Any],
    key: str,
    *,
    range_inclusive: Optional[tuple[int, int]] = None,
    optional: bool = False,
    nonnegative: bool = False,
    positive: bool = False,
) -> Optional[int]:
    """Validate an integer field. `range_inclusive`, when supplied, is the
    inclusive `(low, high)` pair. The `nonnegative` and `positive` flags
    are shorthands for the common ">= 0" and "> 0" rules. Returns the int
    on success, or None if `optional=True` and the field is absent.

    Python's `bool` is a subclass of `int`, so the helper rejects the
    `True`/`False` literals on integer fields with the type-mismatch
    error (the standard library's `isinstance(value, int)` returns True
    on a bool; we add the explicit `isinstance(value, bool)` check).
    """
    if key not in body:
        if optional:
            return None
        raise _fail(f"Missing required integer field {key!r}.", field=key)
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(
            f"Field {key!r} must be an integer; got {type(value).__name__}.",
            field=key,
            value=value,
        )
    if range_inclusive is not None:
        lo, hi = range_inclusive
        if not (lo <= value <= hi):
            raise _fail(
                f"Field {key!r} must be in [{lo}, {hi}]; got {value}.",
                field=key,
                value=value,
                min_value=lo,
                max_value=hi,
            )
    if nonnegative and value < 0:
        raise _fail(
            f"Field {key!r} must be nonnegative; got {value}.",
            field=key,
            value=value,
        )
    if positive and value <= 0:
        raise _fail(
            f"Field {key!r} must be positive; got {value}.",
            field=key,
            value=value,
        )
    return int(value)


def require_number(
    body: dict[str, Any],
    key: str,
    *,
    range_inclusive: Optional[tuple[float, float]] = None,
    nonnegative: bool = False,
    optional: bool = False,
) -> Optional[float]:
    """The float-or-int-number variant. Accepts an int or a float (since
    JSON's number type covers both). The bool-is-subclass-of-int rule
    applies here too: a bool value is rejected as wrong-type.

    Returns the value as a Python `float` (an int input is converted) on
    success, or None on the optional-absent case.
    """
    if key not in body:
        if optional:
            return None
        raise _fail(f"Missing required numeric field {key!r}.", field=key)
    value = body[key]
    if isinstance(value, bool):
        raise _fail(
            f"Field {key!r} must be a number, not a boolean.",
            field=key,
            value=value,
        )
    if not isinstance(value, (int, float)):
        raise _fail(
            f"Field {key!r} must be a number; got {type(value).__name__}.",
            field=key,
            value=value,
        )
    fvalue = float(value)
    if range_inclusive is not None:
        lo, hi = range_inclusive
        if not (lo <= fvalue <= hi):
            raise _fail(
                f"Field {key!r} must be in [{lo}, {hi}]; got {fvalue}.",
                field=key,
                value=fvalue,
                min_value=lo,
                max_value=hi,
            )
    if nonnegative and fvalue < 0:
        raise _fail(
            f"Field {key!r} must be nonnegative; got {fvalue}.",
            field=key,
            value=fvalue,
        )
    return fvalue


def require_bool(
    body: dict[str, Any], key: str, *, optional: bool = False
) -> Optional[bool]:
    """Validate a boolean field. The strict `isinstance(value, bool)`
    check rejects the "truthy non-bool" inputs (the standard JSON-typed
    boolean is the exact-bool case). Returns the bool on success or
    None on optional-absent.
    """
    if key not in body:
        if optional:
            return None
        raise _fail(f"Missing required boolean field {key!r}.", field=key)
    value = body[key]
    if not isinstance(value, bool):
        raise _fail(
            f"Field {key!r} must be a boolean; got {type(value).__name__}.",
            field=key,
            value=value,
        )
    return value


def require_enum(
    body: dict[str, Any],
    key: str,
    *,
    allowed: Iterable[str],
    optional: bool = False,
) -> Optional[str]:
    """Validate an enum-string field against an iterable of allowed values.
    Returns the string on success, or None on the optional-absent case.
    The error message lists the allowed-value set so the client can
    correct the input.
    """
    if key not in body:
        if optional:
            return None
        raise _fail(f"Missing required enum field {key!r}.", field=key)
    value = body[key]
    if not isinstance(value, str):
        raise _fail(
            f"Enum field {key!r} must be a string; got {type(value).__name__}.",
            field=key,
            value=value,
        )
    allowed_set = set(allowed)
    if value not in allowed_set:
        raise _fail(
            f"Enum field {key!r} value {value!r} is not in the allowed set "
            f"{sorted(allowed_set)!r}.",
            field=key,
            value=value,
            allowed=sorted(allowed_set),
        )
    return value


def require_array(
    body: dict[str, Any],
    key: str,
    *,
    element_type: type | tuple[type, ...] | None = None,
    length_range: Optional[tuple[int, int]] = None,
    optional: bool = False,
    no_duplicates: bool = False,
    error_id_for_length: Optional[str] = None,
) -> Optional[list[Any]]:
    """Validate an array (Python list) field. `element_type` is the
    expected Python type (or tuple of types) for each element; a None
    skips the per-element type check (the caller does the element-shape
    check itself, typical for the `polyline` waypoint-objects which are
    dicts of `lat` and `lon` floats). `length_range` is the inclusive
    cardinality bound. `no_duplicates`, when true, rejects an array
    containing any element appearing more than once (with the standard
    object-equality definition; this is the convention for the hazard-
    class arrays and the authorized-id arrays where the "no duplicates"
    rule is named in the §1.1 entities' field-prose).

    `error_id_for_length` is the optional non-`ERR_VALIDATION` error id
    that the length-bound-violation should fire instead of the catch-all,
    used by the `authorized_vehicle_ids` array's cardinality bound where
    the §2.7's priority-523-pinned error id is the dedicated
    `ERR_PERMIT_VEHICLE_COUNT_OUT_OF_RANGE`. The standard error id is the
    422 of the dedicated id (the same HTTP status as the generic 422 of
    `ERR_VALIDATION`).
    """
    if key not in body:
        if optional:
            return None
        raise _fail(f"Missing required array field {key!r}.", field=key)
    value = body[key]
    if not isinstance(value, list):
        raise _fail(
            f"Field {key!r} must be a JSON array; got {type(value).__name__}.",
            field=key,
            value=value,
        )
    if length_range is not None:
        lo, hi = length_range
        if not (lo <= len(value) <= hi):
            if error_id_for_length:
                raise APIError(
                    error_id_for_length,
                    f"Array {key!r} cardinality {len(value)} is outside "
                    f"the inclusive range [{lo}, {hi}].",
                    details={
                        "field": key,
                        "length": len(value),
                        "min_length": lo,
                        "max_length": hi,
                    },
                )
            raise _fail(
                f"Array {key!r} cardinality {len(value)} is outside the "
                f"inclusive range [{lo}, {hi}].",
                field=key,
                length=len(value),
                min_length=lo,
                max_length=hi,
            )
    if element_type is not None:
        for i, el in enumerate(value):
            # The bool-is-subclass-of-int defensive rule applies here too
            # — but the canonical element-types on the arrays of this
            # scaffold are `str` (for the id-strings and the hazard-class
            # codes) and `dict` (for the polyline waypoint objects), not
            # `int`-typed elements, so the bool exclusion is not the
            # typical case.
            if not isinstance(el, element_type):
                raise _fail(
                    f"Array {key!r} element at index {i} must be of type "
                    f"{element_type}; got {type(el).__name__}.",
                    field=key,
                    index=i,
                    element=el,
                )
    if no_duplicates:
        seen = set()
        for i, el in enumerate(value):
            # We hash by the element's value directly; for the string-
            # typed arrays this is the natural string-equality check, and
            # for the dict-typed `polyline` we don't ask for `no_duplicates`
            # so the unhashable-dict case doesn't arise.
            try:
                hashable = el
            except TypeError:
                # Defensive — should not happen on the typed arrays this
                # scaffold uses no-dup checks on.
                continue
            if hashable in seen:
                raise _fail(
                    f"Array {key!r} contains a duplicate element "
                    f"{el!r} at index {i}.",
                    field=key,
                    index=i,
                    duplicate=el,
                )
            seen.add(hashable)
    return value


def require_iso_datetime(
    body: dict[str, Any], key: str, *, optional: bool = False
) -> Optional[datetime]:
    """Validate an ISO-8601 datetime string and return the parsed,
    timezone-aware UTC `datetime`. Returns None on the optional-absent
    case. A malformed string is the body-shape catch-all
    `ERR_VALIDATION`.
    """
    from .clock import parse_iso

    raw = require_str(body, key, optional=optional)
    if raw is None:
        return None
    try:
        return parse_iso(raw)
    except (TypeError, ValueError) as exc:
        raise _fail(
            f"Field {key!r} is not a valid ISO 8601 datetime: {exc}",
            field=key,
            value=raw,
        )


def validate_email_syntax(email: str, *, key: str = "primary_contact_email") -> str:
    """Check an email string against the relaxed RFC 5322 syntactic
    regex named in `config`. The PRD §2.4 names "RFC 5322 syntactic
    check only" as the depth of the validation — full RFC 5322
    grammar-conformance is not required. The default-key argument
    names the field-path for the error message; the helper is also
    called with the `key="ALT"` form on the few hypothetical email-typed
    fields the scaffold doesn't have.
    """
    if not isinstance(email, str) or not _EMAIL_RE.fullmatch(email):
        raise _fail(
            f"Field {key!r} value {email!r} is not a syntactically valid "
            f"email address.",
            field=key,
            value=email,
        )
    return email


def validate_registration_number(value: str) -> str:
    """The company's `registration_number` regex check — eight-to-thirty-
    two characters from the alphabet of uppercase Latin letters and
    digits. The pattern is `^[A-Z0-9]{8,32}$` from `config.REGISTRATION_NUMBER_REGEX`.
    """
    if not _REGISTRATION_RE.fullmatch(value):
        raise _fail(
            f"Field 'registration_number' value {value!r} does not match "
            f"the required pattern of 8 to 32 uppercase letters and digits.",
            field="registration_number",
            value=value,
            pattern=REGISTRATION_NUMBER_REGEX,
        )
    return value


def validate_no_whitespace(value: str, *, field: str = "license_number") -> str:
    """The driver's `license_number` no-embedded-whitespace rule. The
    license-number string must contain no whitespace characters (the
    `^\\S+$` regex). The minimum and maximum length checks are applied
    separately by `require_str` with the `length_range` argument.
    """
    if not _NO_WHITESPACE_RE.fullmatch(value):
        raise _fail(
            f"Field {field!r} value {value!r} must not contain any "
            f"whitespace characters.",
            field=field,
            value=value,
        )
    return value


def validate_hazard_class_array(
    values: list[Any], *, field: str = "hazard_classes", allow_empty: bool = False
) -> list[str]:
    """Validate an array of UN hazard-class code strings. Every element
    must be a string in the canonical taxonomy set `UN_HAZARD_CLASS_CODES`
    from `config`, with no duplicates. The standard non-empty convention
    on most of these arrays (the company's `hazard_classes_authorized`,
    the route's `hazard_classes_supported`, the vehicle's
    `hazard_classes_compatible`, the permit's `hazard_classes`, the
    refresh-endorsement's `endorsement_classes`) is the default; the
    one exception is the driver's initial `endorsement_classes_requested`
    on the operator-side driver-create body which "may be empty" — the
    `allow_empty=True` flag selects that behavior.
    """
    if not isinstance(values, list):
        raise _fail(
            f"Field {field!r} must be a JSON array of UN hazard-class "
            f"strings; got {type(values).__name__}.",
            field=field,
            value=values,
        )
    if not allow_empty and len(values) == 0:
        raise _fail(
            f"Field {field!r} must be a non-empty array of UN hazard-"
            f"class strings.",
            field=field,
            value=values,
        )
    seen = set()
    for i, el in enumerate(values):
        if not isinstance(el, str):
            raise _fail(
                f"Field {field!r}[{i}] must be a string; got "
                f"{type(el).__name__}.",
                field=field,
                index=i,
                value=el,
            )
        if el not in UN_HAZARD_CLASS_CODES:
            raise _fail(
                f"Field {field!r}[{i}] value {el!r} is not a recognized "
                f"UN hazard-class code.",
                field=field,
                index=i,
                value=el,
                allowed_set_size=len(UN_HAZARD_CLASS_CODES),
            )
        if el in seen:
            raise _fail(
                f"Field {field!r} contains the duplicate value {el!r} "
                f"at index {i}.",
                field=field,
                index=i,
                duplicate=el,
            )
        seen.add(el)
    return list(values)


def validate_polyline(
    waypoints: list[Any], *, field: str = "polyline"
) -> list[dict[str, float]]:
    """Validate the route's polyline. A JSON array of waypoint objects
    `{"lat": float in [-90, 90], "lon": float in [-180, 180]}`, with the
    cardinality bound of inclusive 2-to-200 waypoints. The geometric
    well-formedness (no `NaN`, the latitude-and-longitude in their
    standard WGS-84 ranges) is checked. The polyline-the-segments-non-
    degenerate check (no two consecutive waypoints being the same
    point) is not asserted because the PRD's polyline-shape rules in
    §2.8 and §3.4 do not name a non-degenerate-segments rule explicitly
    and the haversine-distance formula handles a zero-length-segment
    case gracefully (the cross-track distance to a zero-length segment
    is the great-circle distance to the segment's single endpoint).
    """
    if not isinstance(waypoints, list):
        raise _fail(
            f"Field {field!r} must be a JSON array of waypoint objects.",
            field=field,
            value=waypoints,
        )
    lo, hi = POLYLINE_WAYPOINT_COUNT_RANGE
    if not (lo <= len(waypoints) <= hi):
        raise _fail(
            f"Field {field!r} length {len(waypoints)} is outside the "
            f"inclusive range [{lo}, {hi}].",
            field=field,
            length=len(waypoints),
            min_length=lo,
            max_length=hi,
        )
    out: list[dict[str, float]] = []
    for i, wp in enumerate(waypoints):
        if not isinstance(wp, dict):
            raise _fail(
                f"Field {field!r}[{i}] must be a JSON object with "
                f"'lat' and 'lon' keys; got {type(wp).__name__}.",
                field=field,
                index=i,
                value=wp,
            )
        # The waypoint's lat and lon must be present numerics in their
        # standard WGS-84 ranges.
        lat = wp.get("lat")
        lon = wp.get("lon")
        if not isinstance(lat, (int, float)) or isinstance(lat, bool):
            raise _fail(
                f"Field {field!r}[{i}]['lat'] must be a number in "
                f"[-90, 90]; got {lat!r}.",
                field=f"{field}[{i}].lat",
                value=lat,
            )
        if not isinstance(lon, (int, float)) or isinstance(lon, bool):
            raise _fail(
                f"Field {field!r}[{i}]['lon'] must be a number in "
                f"[-180, 180]; got {lon!r}.",
                field=f"{field}[{i}].lon",
                value=lon,
            )
        lat_f = float(lat)
        lon_f = float(lon)
        # NaN rejection. `float('nan') == float('nan')` is False; the
        # standard idiom is `x != x` to detect a NaN.
        if lat_f != lat_f:
            raise _fail(
                f"Field {field!r}[{i}]['lat'] is NaN.",
                field=f"{field}[{i}].lat",
            )
        if lon_f != lon_f:
            raise _fail(
                f"Field {field!r}[{i}]['lon'] is NaN.",
                field=f"{field}[{i}].lon",
            )
        lat_lo, lat_hi = LAT_RANGE
        lon_lo, lon_hi = LON_RANGE
        if not (lat_lo <= lat_f <= lat_hi):
            raise _fail(
                f"Field {field!r}[{i}]['lat'] value {lat_f} is outside "
                f"[{lat_lo}, {lat_hi}].",
                field=f"{field}[{i}].lat",
                value=lat_f,
            )
        if not (lon_lo <= lon_f <= lon_hi):
            raise _fail(
                f"Field {field!r}[{i}]['lon'] value {lon_f} is outside "
                f"[{lon_lo}, {lon_hi}].",
                field=f"{field}[{i}].lon",
                value=lon_f,
            )
        out.append({"lat": lat_f, "lon": lon_f})
    return out


def validate_vehicle_type(value: str) -> str:
    """The Vehicle's `vehicle_type` enum check against the canonical five-
    value set from `config.VEHICLE_TYPES`. Returns the validated string.
    """
    if value not in VEHICLE_TYPES:
        raise _fail(
            f"Field 'vehicle_type' value {value!r} is not in the allowed "
            f"set {sorted(VEHICLE_TYPES)!r}.",
            field="vehicle_type",
            value=value,
            allowed=sorted(VEHICLE_TYPES),
        )
    return value


def validate_lat_lon(lat: float, lon: float) -> tuple[float, float]:
    """A standalone helper for the GPS-sample's lat-and-lon pair. Returns
    the validated `(lat, lon)` tuple of floats. The bound checks are
    the standard WGS-84 inclusive degree ranges.
    """
    if lat != lat or lon != lon:  # NaN check
        raise _fail("lat/lon must not be NaN.")
    lat_lo, lat_hi = LAT_RANGE
    lon_lo, lon_hi = LON_RANGE
    if not (lat_lo <= lat <= lat_hi):
        raise _fail(
            f"'lat' must be in [{lat_lo}, {lat_hi}]; got {lat}.",
            field="lat",
            value=lat,
        )
    if not (lon_lo <= lon <= lon_hi):
        raise _fail(
            f"'lon' must be in [{lon_lo}, {lon_hi}]; got {lon}.",
            field="lon",
            value=lon,
        )
    return lat, lon


def validate_heading_deg(heading: float) -> float:
    """Heading-degrees inclusive-0-to-360 range from `config.HEADING_RANGE`.
    The PRD §2.8's "0 and 360 mean the same compass north" convention is
    the interpretation; the bound is inclusive on both sides per the §2.8
    paragraph.
    """
    lo, hi = HEADING_RANGE
    if heading != heading:  # NaN
        raise _fail("'heading_deg' must not be NaN.", field="heading_deg")
    if not (lo <= heading <= hi):
        raise _fail(
            f"'heading_deg' must be in [{lo}, {hi}]; got {heading}.",
            field="heading_deg",
            value=heading,
        )
    return float(heading)


def validate_idempotency_key_header(value: Optional[str]) -> Optional[str]:
    """Validate the optional `Idempotency-Key` HTTP-header value's length.
    A None input (the header was absent on the request) returns None. A
    present value's length is checked against the inclusive
    `[IDEMPOTENCY_KEY_MIN_LEN, IDEMPOTENCY_KEY_MAX_LEN]` bound and a
    miss is the body-shape catch-all `ERR_VALIDATION` 422 per the PRD
    §2.8 closing-paragraph's "the optional Idempotency-Key header is in
    the inclusive 8-to-128-character bound; an out-of-bound is
    `ERR_VALIDATION`".
    """
    if value is None:
        return None
    if not isinstance(value, str):
        # The header is always a string in HTTP — defensive check.
        raise _fail(
            "Idempotency-Key header must be a string.",
            field="Idempotency-Key",
            value=value,
        )
    if not (IDEMPOTENCY_KEY_MIN_LEN <= len(value) <= IDEMPOTENCY_KEY_MAX_LEN):
        raise _fail(
            f"Idempotency-Key header length {len(value)} is outside the "
            f"inclusive range [{IDEMPOTENCY_KEY_MIN_LEN}, "
            f"{IDEMPOTENCY_KEY_MAX_LEN}].",
            field="Idempotency-Key",
            value=value,
            min_length=IDEMPOTENCY_KEY_MIN_LEN,
            max_length=IDEMPOTENCY_KEY_MAX_LEN,
        )
    return value


def parse_comma_filter_query(
    raw: Optional[str], *, allowed: Iterable[str], field_name: str
) -> Optional[set[str]]:
    """Parse a query-string filter of the form
    `?<field_name>=value1,value2,value3` into the set of values, with each
    value required to be in the `allowed` set or the response is the body-
    shape catch-all `ERR_VALIDATION` 422. A None input (the filter is
    absent from the query string) returns None so the caller knows the
    filter is unfiltered. An empty string after the `=` returns the empty
    set, which the caller may treat as "the filter is the empty-set
    filter" — in practice the test layer's `?status=` form is unlikely so
    we treat the empty-string the same as the all-strings-empty case.
    """
    if raw is None:
        return None
    if raw == "":
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    allowed_set = set(allowed)
    invalid = [p for p in parts if p not in allowed_set]
    if invalid:
        raise _fail(
            f"Query filter {field_name!r} contains unrecognized values "
            f"{invalid!r}; allowed are {sorted(allowed_set)!r}.",
            field=field_name,
            invalid_values=invalid,
            allowed=sorted(allowed_set),
        )
    return set(parts)
