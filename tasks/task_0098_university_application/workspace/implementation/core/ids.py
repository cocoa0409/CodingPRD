"""ID generation utilities."""
from __future__ import annotations
import secrets
import string
import uuid


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"
