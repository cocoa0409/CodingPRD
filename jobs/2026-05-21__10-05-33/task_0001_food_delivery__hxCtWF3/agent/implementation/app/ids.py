"""Identifier generation: UUIDs without prefix, plus the req_ prefixed request id."""
import secrets
import uuid


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    body = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{body}"
