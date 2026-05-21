"""Tracking number minting: 12-character alphanumeric uppercase."""
import random
import string

ALPHABET = string.ascii_uppercase + string.digits


def mint_tracking_number(existing: set) -> str:
    while True:
        candidate = "".join(random.choices(ALPHABET, k=12))
        if candidate not in existing:
            return candidate
