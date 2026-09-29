"""Body and query validation: ranks 5 and 6 of the PRD 2.9 ladder."""

from datetime import datetime, timezone

from flask import request

import constants as C
from errors import ApiError


def invalid(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def get_body():
    """The request body as a dict; a missing body is an empty object."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise invalid("Request body must be valid JSON.")
    if not isinstance(data, dict):
        raise invalid("Request body must be a JSON object.")
    return data


def raw_body():
    """Body without raising, for the rank-4 ownership peek that precedes rank 5."""
    try:
        return get_body()
    except ApiError:
        return {}


def peek_str(body, key):
    value = body.get(key)
    return value if isinstance(value, str) else None


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# scalar field readers
# ---------------------------------------------------------------------------
def _present(body, key):
    return key in body and body[key] is not None


def req_str(body, key, min_len=None, max_len=None):
    if not _present(body, key):
        raise invalid("'%s' is required." % key)
    value = body[key]
    if not isinstance(value, str):
        raise invalid("'%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        raise invalid("'%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise invalid("'%s' must be at most %d characters." % (key, max_len))
    return value


def opt_str(body, key, min_len=None, max_len=None, default=None):
    if key not in body or body[key] is None:
        return default
    return req_str(body, key, min_len, max_len)


def req_int(body, key, minimum=None, maximum=None):
    if not _present(body, key):
        raise invalid("'%s' is required." % key)
    value = body[key]
    if not is_int(value):
        raise invalid("'%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        raise invalid("'%s' must be >= %d." % (key, minimum))
    if maximum is not None and value > maximum:
        raise invalid("'%s' must be <= %d." % (key, maximum))
    return value


def opt_int(body, key, minimum=None, maximum=None, default=None):
    if key not in body or body[key] is None:
        return default
    return req_int(body, key, minimum, maximum)


def req_bool(body, key):
    if not _present(body, key):
        raise invalid("'%s' is required." % key)
    value = body[key]
    if not isinstance(value, bool):
        raise invalid("'%s' must be a boolean." % key)
    return value


def opt_bool(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    return req_bool(body, key)


def req_enum(body, key, allowed):
    value = req_str(body, key)
    if value not in allowed:
        raise invalid("'%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_enum(body, key, allowed, default=None):
    if key not in body or body[key] is None:
        return default
    return req_enum(body, key, allowed)


def req_list(body, key, min_entries=None):
    if not _present(body, key):
        raise invalid("'%s' is required." % key)
    value = body[key]
    if not isinstance(value, list):
        raise invalid("'%s' must be an array." % key)
    if min_entries is not None and len(value) < min_entries:
        raise invalid("'%s' must contain at least %d entries." % (key, min_entries))
    return value


# ---------------------------------------------------------------------------
# datetimes
# ---------------------------------------------------------------------------
def parse_instant(value, key):
    if not isinstance(value, str):
        raise invalid("'%s' must be an ISO 8601 timestamp string." % key)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise invalid("'%s' must be a valid ISO 8601 timestamp." % key)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_instant(body, key):
    if not _present(body, key):
        raise invalid("'%s' is required." % key)
    return parse_instant(body[key], key)


def opt_instant(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    return parse_instant(body[key], key)


# ---------------------------------------------------------------------------
# composite arrays
# ---------------------------------------------------------------------------
def validate_size_points(body, key="size_points"):
    """PRD 3.2 / rank 5: >= 2 entries, unique labels, unique sort_index >= 0."""
    entries = req_list(body, key, min_entries=2)
    labels = set()
    indexes = set()
    points = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise invalid("Each '%s' entry must be an object." % key)
        label = req_str(entry, "size_label", min_len=1)
        sort_index = req_int(entry, "sort_index", minimum=0)
        point = {
            "size_label": label,
            "sort_index": sort_index,
            "chest_mm": req_int(entry, "chest_mm"),
            "waist_mm": req_int(entry, "waist_mm"),
            "hip_mm": req_int(entry, "hip_mm"),
            "inseam_mm": req_int(entry, "inseam_mm"),
        }
        if label in labels:
            raise invalid("'%s' size_label values must be unique." % key)
        if sort_index in indexes:
            raise invalid("'%s' sort_index values must be unique." % key)
        labels.add(label)
        indexes.add(sort_index)
        points.append(point)
    return points


def validate_grade_rules(body, key="grade_rules"):
    entries = req_list(body, key, min_entries=1)
    seen = set()
    rules = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise invalid("Each '%s' entry must be an object." % key)
        point = req_enum(entry, "measurement_point", C.MEASUREMENT_POINTS)
        if point in seen:
            raise invalid("'%s' measurement_point values must be unique." % key)
        seen.add(point)
        rules.append({
            "measurement_point": point,
            "increment_mm": req_int(entry, "increment_mm"),
            "tolerance_pct_bp": req_int(entry, "tolerance_pct_bp"),
            "tolerance_abs_mm": req_int(entry, "tolerance_abs_mm"),
        })
    return rules


def validate_chart_rows(body, key="rows"):
    """PRD 3.3: >= 2 rows, distinct labels, distinct sort_index contiguous from 0."""
    entries = req_list(body, key, min_entries=2)
    labels = set()
    indexes = set()
    rows = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise invalid("Each '%s' entry must be an object." % key)
        label = req_str(entry, "size_label", min_len=1)
        sort_index = req_int(entry, "sort_index", minimum=0)
        row = {
            "size_label": label,
            "sort_index": sort_index,
            "body_chest_min_mm": req_int(entry, "body_chest_min_mm"),
            "body_chest_max_mm": req_int(entry, "body_chest_max_mm"),
            "body_waist_min_mm": req_int(entry, "body_waist_min_mm"),
            "body_waist_max_mm": req_int(entry, "body_waist_max_mm"),
            "conversion_us_alpha": req_str(entry, "conversion_us_alpha"),
            "conversion_us_numeric": req_str(entry, "conversion_us_numeric"),
            "conversion_eu": req_str(entry, "conversion_eu"),
            "conversion_uk": req_str(entry, "conversion_uk"),
        }
        if label in labels:
            raise invalid("'%s' size_label values must be unique." % key)
        if sort_index in indexes:
            raise invalid("'%s' sort_index values must be unique." % key)
        labels.add(label)
        indexes.add(sort_index)
        rows.append(row)
    if sorted(indexes) != list(range(len(rows))):
        raise invalid("'%s' sort_index values must be contiguous from 0." % key)
    return rows


def validate_size_label_pairs(body, key="size_label_pairs"):
    entries = req_list(body, key, min_entries=1)
    spec_labels = set()
    chart_labels = set()
    pairs = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise invalid("Each '%s' entry must be an object." % key)
        spec_label = req_str(entry, "spec_size_label", min_len=1)
        chart_label = req_str(entry, "chart_size_label", min_len=1)
        if spec_label in spec_labels:
            raise invalid("'%s' spec_size_label values must be unique." % key)
        if chart_label in chart_labels:
            raise invalid("'%s' chart_size_label values must be unique." % key)
        spec_labels.add(spec_label)
        chart_labels.add(chart_label)
        pairs.append({"spec_size_label": spec_label, "chart_size_label": chart_label})
    return pairs


# ---------------------------------------------------------------------------
# pagination (rank 6)
# ---------------------------------------------------------------------------
def pagination_params():
    args = request.args
    limit = C.PAGINATION_LIMIT_DEFAULT
    offset = C.PAGINATION_OFFSET_DEFAULT
    if "limit" in args:
        raw = args.get("limit")
        limit = _int_param(raw, "limit")
        if limit < C.PAGINATION_LIMIT_MIN or limit > C.PAGINATION_LIMIT_MAX:
            raise ApiError(
                "ERR_INVALID_PAGINATION",
                "limit must be an integer between 1 and 100.",
            )
    if "offset" in args:
        raw = args.get("offset")
        offset = _int_param(raw, "offset")
        if offset < C.PAGINATION_OFFSET_MIN:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer >= 0.")
    return limit, offset


def _int_param(raw, name):
    if raw is None:
        raise ApiError("ERR_INVALID_PAGINATION", "%s must be an integer." % name)
    text = raw.strip()
    if text == "":
        raise ApiError("ERR_INVALID_PAGINATION", "%s must be an integer." % name)
    try:
        if text[0] in "+-":
            if not text[1:].isdigit():
                raise ValueError
        elif not text.isdigit():
            raise ValueError
        return int(text)
    except ValueError:
        raise ApiError("ERR_INVALID_PAGINATION", "%s must be an integer." % name)


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta
