"""ID generators — UUIDs (no type prefix) and request IDs."""
import secrets
import string
import uuid


_ALPHANUM = string.ascii_uppercase + string.digits


def new_uuid() -> str:
    """Server-generated UUID emitted without a type prefix."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    """Random alphanumeric request id, prefix `req_`, 20 character body."""
    body = "".join(secrets.choice(_ALPHANUM) for _ in range(20))
    return f"req_{body}"
