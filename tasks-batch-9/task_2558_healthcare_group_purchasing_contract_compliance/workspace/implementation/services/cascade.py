"""Derived counters and multi-hop cascades (PRD sections 2.7, 3.4, 3.8)."""

from db import db, ordered
from services.calc import derive_activation_price, find_tier

ACTIVE_COMMITMENT_STATUSES = ("ACTIVE", "REQUAL_REVIEW")
PRICEABLE_ACTIVATION_STATUSES = ("DRAFT", "ENDORSED", "APPROVED", "ACTIVE")


def recompute_contract_evidence_endorsed(contract):
    """True iff at least one review for that contract is ENDORSED."""
    contract["evidence_endorsed"] = any(
        review["contract_id"] == contract["id"] and review["status"] == "ENDORSED"
        for review in db.reviews.values()
    )
    db.touch(contract)


def recompute_active_commitment_count(contract):
    contract["active_commitment_count"] = sum(
        1
        for commitment in db.commitments.values()
        if commitment["contract_id"] == contract["id"]
        and commitment["election_status"] in ACTIVE_COMMITMENT_STATUSES
    )
    db.touch(contract)


def recompute_item_activation_count(item):
    item["active_activation_count"] = sum(
        1
        for activation in db.activations.values()
        if activation["contract_item_id"] == item["id"] and activation["status"] == "ACTIVE"
    )
    db.touch(item)


def recompute_items_once(item_ids):
    """Recompute active_activation_count exactly once per affected item."""
    seen = []
    for item_id in item_ids:
        if item_id in seen:
            continue
        seen.append(item_id)
        item = db.contract_items.get(item_id)
        if item is not None:
            recompute_item_activation_count(item)


def supersede_on_termination(commitment):
    """Terminating a commitment supersedes its live prices, no replacements."""
    touched = []
    for activation in ordered(db.activations.values()):
        if activation["commitment_id"] != commitment["id"]:
            continue
        if activation["status"] not in PRICEABLE_ACTIVATION_STATUSES:
            continue
        activation["status"] = "SUPERSEDED"
        activation["superseded_by_activation_id"] = None
        db.touch(activation)
        touched.append(activation["contract_item_id"])
    recompute_items_once(touched)


def _mint_replacement(original, commitment, contract, tier_code, effective_from):
    item = db.contract_items.get(original["contract_item_id"])
    tier = find_tier(contract, tier_code)
    if item is None or tier is None:
        return None
    requested = original["requested_price_cents"]
    computed_price, clamped = derive_activation_price(
        item, tier, original["activation_type"], requested
    )
    replacement = db.new_row()
    replacement.update(
        {
            "commitment_id": commitment["id"],
            "contract_item_id": original["contract_item_id"],
            "activation_type": original["activation_type"],
            "requested_price_cents": requested,
            "effective_from": effective_from,
            "effective_to": original["effective_to"],
            "tier_code_at_activation": tier_code,
            "computed_price_cents": computed_price,
            "price_clamped": clamped,
            "status": "ACTIVE",
            "endorsed_by_user_id": None,
            "approved_by_user_id": None,
            "superseded_by_activation_id": None,
            "replaces_activation_id": original["id"],
            "origin": "REQUALIFICATION_CASCADE",
            "deny_note": None,
        }
    )
    db.activations[replacement["id"]] = replacement
    return replacement


def _supersede_and_replace(original, commitment, contract, tier_code, today, touched):
    original["status"] = "SUPERSEDED"
    replacement = None
    if original["effective_to"] >= today:
        replacement = _mint_replacement(original, commitment, contract, tier_code, today)
    original["superseded_by_activation_id"] = (
        replacement["id"] if replacement is not None else None
    )
    db.touch(original)
    touched.append(original["contract_item_id"])
    if replacement is not None:
        touched.append(replacement["contract_item_id"])


def requalification_retier_cascade(commitment, previous_tier_code):
    """Hops 3, 4 and 5 of finalize: retier live prices under the new tier."""
    new_tier_code = commitment["current_tier_code"]
    if new_tier_code == previous_tier_code:
        return
    contract = db.contracts.get(commitment["contract_id"])
    if contract is None:
        return
    today = db.today()
    touched = []

    superseded_item_ids = []
    for activation in ordered(db.activations.values()):
        if activation["commitment_id"] != commitment["id"]:
            continue
        if activation["status"] != "ACTIVE" or activation["activation_type"] != "TIER_PRICE":
            continue
        _supersede_and_replace(activation, commitment, contract, new_tier_code, today, touched)
        if activation["contract_item_id"] not in superseded_item_ids:
            superseded_item_ids.append(activation["contract_item_id"])

    for item_id in superseded_item_ids:
        for activation in ordered(db.activations.values()):
            if activation["commitment_id"] != commitment["id"]:
                continue
            if activation["contract_item_id"] != item_id:
                continue
            if (
                activation["status"] != "ACTIVE"
                or activation["activation_type"] != "LOCAL_EXCEPTION"
            ):
                continue
            _supersede_and_replace(
                activation, commitment, contract, new_tier_code, today, touched
            )

    recompute_items_once(touched)
