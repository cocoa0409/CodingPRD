import errors


def require_body(data):
    if data is None or not isinstance(data, dict):
        raise errors.validation("Request body must be a JSON object.")
    return data


def require_present(data, field):
    if field not in data or data[field] is None:
        raise errors.validation(f"Missing required field: {field}")
    return data[field]


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.validation(f"Field {field} must be an integer.")
    return value


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise errors.validation(f"Field {field} must be a number.")
    return value


def as_str(value, field):
    if not isinstance(value, str):
        raise errors.validation(f"Field {field} must be a string.")
    return value


def in_range_num(value, field, lo, hi):
    if value < lo or value > hi:
        raise errors.validation(f"Field {field} out of range [{lo}, {hi}].")
    return value
