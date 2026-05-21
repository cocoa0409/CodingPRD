"""ID generation helpers."""

from __future__ import annotations

import random
import string
import uuid


def new_id() -> str:
    """UUID4 with no prefix (entities' id field)."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    """20-char alphanumeric request id, prefixed with req_."""
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(random.choices(alphabet, k=20))
    return f"req_{suffix}"
