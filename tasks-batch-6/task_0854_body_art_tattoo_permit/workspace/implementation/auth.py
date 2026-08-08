"""Authentication, authorization and ownership — PRD §2.1 / §2.7 steps 1,2,6."""

from flask import request

import config
import store
from errors import ApiError


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_operator(self):
        return self.role == "EstablishmentOperator"

    @property
    def is_artist(self):
        return self.role == "Artist"


def authenticate(allowed_roles):
    """Step 1 then step 2 of the evaluation order."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in config.ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return Caller(user_id, role)


def require_owns_establishment(caller, establishment_id):
    """Entity-backed EstablishmentOperator ownership check (step 6)."""
    if caller.is_operator and caller.user_id != establishment_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_owns_artist(caller, artist_id, artist=None):
    """Entity-backed Artist ownership check (step 6).  An EstablishmentOperator
    acting on an artist owns them when the artist sits on their roster."""
    if caller.is_artist and caller.user_id != artist_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if caller.is_operator:
        artist = artist or store.artists.get(artist_id)
        if artist is None or caller.user_id != artist["establishment_id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")
