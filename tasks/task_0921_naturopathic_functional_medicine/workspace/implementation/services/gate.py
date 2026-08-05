"""The global clinical write gate and the freeze / unfreeze cascades (PRD 2.5, 2.11)."""

from store import db, ordered, touch


def open_red_flag_referral(patient_id):
    """The RED_FLAG_AUTO referral holding a freeze, or None.

    Acknowledging clears the freeze; declining and abandoning never do, so the
    holding set is {SENT, DECLINED, ABANDONED} (PRD 3.5).
    """
    held = [
        r
        for r in db.referrals.values()
        if r["patient_id"] == patient_id
        and r["referral_type"] == "RED_FLAG_AUTO"
        and r["status"] in ("SENT", "DECLINED", "ABANDONED")
    ]
    if not held:
        return None
    return ordered(held)[0]


def propagate_gate(patient):
    """Links 4 and 5 of the freeze / unfreeze cascade."""
    frozen = patient["clinical_write_gate"] != "OPEN"
    for protocol in db.protocols.values():
        if protocol["patient_id"] != patient["id"]:
            continue
        if protocol["status"] == "ACTIVE":
            if protocol.get("advancement_blocked") != frozen:
                protocol["advancement_blocked"] = frozen
                touch(protocol)
            for item in db.protocol_items.values():
                if item["protocol_id"] != protocol["id"]:
                    continue
                if item["status"] in ("ACTIVE", "HELD"):
                    if item.get("titration_locked") != frozen:
                        item["titration_locked"] = frozen
                        touch(item)


def recompute_gate(patient):
    """Links 2 and 3: red_flag_referral_open, then the gate, then propagation.

    FROZEN_SCOPE_REVIEW takes precedence when both conditions are live.
    """
    referral = open_red_flag_referral(patient["id"])
    patient["red_flag_referral_open"] = referral is not None
    if patient["scope_review_status"] in ("UNDER_REVIEW", "RESTRICTED"):
        gate = "FROZEN_SCOPE_REVIEW"
    elif referral is not None:
        gate = "FROZEN_RED_FLAG"
    else:
        gate = "OPEN"
    patient["clinical_write_gate"] = gate
    propagate_gate(patient)
    return gate
