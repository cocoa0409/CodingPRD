"""Shared route helpers: entity lookup with ERR_NOT_FOUND, ownership checks."""
import errors
from db import db


def get_or_404(store, rid):
    rec = store.get(rid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Resource not found")
    return rec


def show_id_of_episode(episode):
    return episode["show_id"]


def show_id_of_deliverable(deliverable):
    episode = db.episodes.get(deliverable["episode_id"])
    return episode["show_id"] if episode else None


def show_id_of_asset_version(av):
    deliverable = db.deliverables.get(av["deliverable_id"])
    if deliverable is None:
        return None
    return show_id_of_deliverable(deliverable)


def show_id_of_invoice(invoice):
    return invoice["show_id"]


def show_id_of_retainer_cycle(cycle):
    contract = db.contracts.get(cycle["contract_id"])
    return contract["show_id"] if contract else None


def assert_show_owner(auth, show_id):
    """PRD §2.1/§2.8: a ShowOwner acting on a resource that chains to a show must
    own that show (X-User-ID == Show.id), else ERR_NOT_RESOURCE_OWNER."""
    if auth.role == "ShowOwner" and show_id is not None and auth.user_id != show_id:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER, "Not the owner of this resource")


def assert_session_engineer(auth, session):
    """A ProducerEng acting on a session must be the session's engineer."""
    if auth.role == "ProducerEng" and auth.user_id != session["engineer_id"]:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER, "Not the engineer for this session")
