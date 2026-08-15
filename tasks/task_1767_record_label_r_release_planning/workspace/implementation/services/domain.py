"""Cross-entity lookups and shared side effects."""

from db import db, today
from helpers import touch

OPEN_MEMO_STATES = ("DRAFT", "PROPOSED", "COUNTERED", "APPROVED")


def artist_of_contract(contract):
    return db.artists.get(contract["artist_id"])


def label_of_artist(artist):
    return db.labels.get(artist["label_id"]) if artist else None


def label_of_contract(contract):
    return label_of_artist(artist_of_contract(contract))


def contract_of_account(account):
    return db.contracts.get(account["contract_id"])


def account_of_contract(contract_id):
    for acc in db.recoupment_accounts.values():
        if acc["contract_id"] == contract_id:
            return acc
    return None


def project_contract(project):
    return db.contracts.get(project["contract_id"])


def artist_of_project(project):
    contract = project_contract(project)
    return artist_of_contract(contract) if contract else None


def release_contract(release):
    return db.contracts.get(release["contract_id"])


def artist_of_release(release):
    contract = release_contract(release)
    return artist_of_contract(contract) if contract else None


def tour_contract(tour):
    return db.contracts.get(tour["contract_id"])


def artist_of_tour(tour):
    contract = tour_contract(tour)
    return artist_of_contract(contract) if contract else None


def has_open_memo(artist_id, exclude_memo_id=None):
    for memo in db.deal_memos.values():
        if memo["artist_id"] != artist_id:
            continue
        if exclude_memo_id is not None and memo["id"] == exclude_memo_id:
            continue
        if memo["status"] in OPEN_MEMO_STATES:
            return True
    return False


def artist_has_contract(artist_id):
    return any(c["artist_id"] == artist_id for c in db.contracts.values())


def maybe_revert_artist_to_scouted(artist):
    """IN_NEGOTIATION -> SCOUTED when no other open memo and no contract."""
    if artist is None or artist["status"] != "IN_NEGOTIATION":
        return
    if has_open_memo(artist["id"]):
        return
    if artist_has_contract(artist["id"]):
        return
    artist["status"] = "SCOUTED"
    touch(artist)


def expire_memo(memo):
    """Lazily expire a memo and apply the artist reversion side effect."""
    memo["status"] = "EXPIRED"
    touch(memo)
    maybe_revert_artist_to_scouted(db.artists.get(memo["artist_id"]))


def memo_is_expired(memo):
    valid_until = memo.get("_valid_until")
    return valid_until is not None and today() > valid_until
