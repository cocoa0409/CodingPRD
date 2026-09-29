"""Path and body reference resolution — ladder tiers 4 and 5 (PRD 2.6)."""

import store
from errors import fail

NOT_FOUND = {
    "Outing": "ERR_OUTING_NOT_FOUND",
    "CourseContract": "ERR_CONTRACT_NOT_FOUND",
    "PackageTier": "ERR_TIER_NOT_FOUND",
    "Registration": "ERR_REGISTRATION_NOT_FOUND",
    "Player": "ERR_PLAYER_NOT_FOUND",
    "Team": "ERR_TEAM_NOT_FOUND",
    "SponsorshipAsset": "ERR_ASSET_NOT_FOUND",
    "SponsorAllocation": "ERR_ALLOCATION_NOT_FOUND",
    "Contest": "ERR_CONTEST_NOT_FOUND",
    "FundraisingItem": "ERR_ITEM_NOT_FOUND",
    "CharitableReceipt": "ERR_RECEIPT_NOT_FOUND",
}


def _get(kind, row_id):
    row = store.COLLECTIONS[kind].get(row_id)
    if row is None:
        fail(NOT_FOUND[kind], "%s %s does not exist." % (kind, row_id))
    return row


def outing(row_id):
    return _get("Outing", row_id)


def contract(row_id):
    return _get("CourseContract", row_id)


def tier(row_id):
    return _get("PackageTier", row_id)


def registration(row_id):
    return _get("Registration", row_id)


def player(row_id):
    return _get("Player", row_id)


def team(row_id):
    return _get("Team", row_id)


def asset(row_id):
    return _get("SponsorshipAsset", row_id)


def allocation(row_id):
    return _get("SponsorAllocation", row_id)


def contest(row_id):
    return _get("Contest", row_id)


def item(row_id):
    return _get("FundraisingItem", row_id)


def receipt(row_id):
    return _get("CharitableReceipt", row_id)
