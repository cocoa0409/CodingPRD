import secrets
import string
import uuid


def new_uuid() -> str:
    return str(uuid.uuid4())


_ALPHABET = string.ascii_uppercase + string.digits


def new_request_id() -> str:
    return "req_" + "".join(secrets.choice(_ALPHABET) for _ in range(20))
