import random
import string
import uuid


_ALPHABET = string.ascii_letters + string.digits


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(_ALPHABET, k=20))
    return f"req_{suffix}"
