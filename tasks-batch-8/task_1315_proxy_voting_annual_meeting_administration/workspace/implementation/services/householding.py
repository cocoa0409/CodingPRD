"""Householding package grouping (scaffold §1.3 householding_grouping, PRD §3.3).

ELIGIBLE accounts with delivery_preference NOTICE_AND_ACCESS or FULL_MAIL, no
householding_opt_out, and a non-null address_key are grouped by
(address_key, delivery_preference); each group yields one package whose
representative is the earliest-created member. Every other eligible account
(E_DELIVERY, opted-out, or no address_key) gets an individual package.
Packages are created in ascending order of their representative's creation.
"""

from __future__ import annotations

import db

_PHYSICAL_CHANNELS = ("NOTICE_AND_ACCESS", "FULL_MAIL")


def _creation_key(account: dict):
    return (account.get("created_at", ""), account.get("_seq", 0))


def build_packages(meeting: dict) -> list:
    eligible = [
        a
        for a in db.accounts.values()
        if a["meeting_id"] == meeting["id"] and a["status"] == "ELIGIBLE"
    ]
    eligible.sort(key=_creation_key)

    physical = [
        a
        for a in eligible
        if a["delivery_preference"] in _PHYSICAL_CHANNELS
        and not a["householding_opt_out"]
        and a.get("address_key") is not None
    ]

    groups: dict[tuple[str, str], list] = {}
    for a in physical:
        groups.setdefault((a["address_key"], a["delivery_preference"]), []).append(a)

    grouped_ids: set[str] = set()
    specs = []  # (channel, representative, members)
    for (address_key, pref), members in groups.items():
        members.sort(key=_creation_key)
        representative = members[0]
        grouped_ids.update(m["id"] for m in members)
        specs.append((pref, representative, members))

    for a in eligible:
        if a["id"] in grouped_ids:
            continue
        specs.append((a["delivery_preference"], a, [a]))

    # Package creation order: by representative created_at ASC (_seq tie-break).
    specs.sort(key=lambda s: _creation_key(s[1]))

    packages = []
    for channel, representative, members in specs:
        package = {
            "meeting_id": meeting["id"],
            "channel": channel,
            "representative_account_id": representative["id"],
            "covered_account_ids": [m["id"] for m in members],
            "covered_shares": sum(m["shares_held"] for m in members),
            "status": "ACTIVE",
        }
        db.stamp_new(package)
        db.distributions[package["id"]] = package
        packages.append(package)
    return packages
