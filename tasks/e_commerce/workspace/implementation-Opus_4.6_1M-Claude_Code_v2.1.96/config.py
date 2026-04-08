import json
from datetime import datetime, timezone


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    for key in ("stackable", "inventory_restored"):
        if key in d:
            d[key] = bool(d[key])
    for key in ("applicable_categories", "applied_promotions", "product_snapshot", "refund_items"):
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def parse_pagination(args):
    try:
        limit = int(args.get("limit", 20))
    except (ValueError, TypeError):
        limit = 20
    try:
        offset = int(args.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def check_version(resource, request_version):
    if request_version is not None:
        if resource["version"] != request_version:
            from errors import raise_error
            raise_error("ERR_STALE_DATA")
