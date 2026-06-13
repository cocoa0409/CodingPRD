"""Timestamp + request-id helpers.

PRD §2.2/§2.4: ISO 8601 UTC with exactly three fractional digits, 'Z' suffix.
api_request_id is a server-generated id starting with 'req_'.
"""
import datetime
import secrets
import string

_ALPHANUM = string.ascii_letters + string.digits


def now_iso():
    """Current UTC time as ISO 8601 with millisecond precision and Z suffix."""
    dt = datetime.datetime.now(datetime.timezone.utc)
    # millisecond precision (3 fractional digits)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_dt():
    return datetime.datetime.now(datetime.timezone.utc)


def request_id():
    body = "".join(secrets.choice(_ALPHANUM) for _ in range(20))
    return "req_" + body
