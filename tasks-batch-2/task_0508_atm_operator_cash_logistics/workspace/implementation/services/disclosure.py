"""Fee-disclosure approval (PRD §3.9, SCAFFOLD §1.4 priority 8/9/10).

Approval check order (priority order — lowest number wins):
  8  ERR_SURCHARGE_CAP_EXCEEDED  disclosed_surcharge_cents <= regulatory_cap_cents
  9  ERR_ACK_TEXT_MISSING        ack_text_present == true
  10 ERR_DISCLOSURE_MISMATCH     disclosed_surcharge_cents == ATM.surcharge_cents

On success: status -> APPROVED; any prior APPROVED disclosure for the ATM ->
REJECTED (superseded); ATM.fee_disclosure_id := this disclosure.
"""
from errors import err


def approve(store, disclosure, atm):
    # 8 cap
    if disclosure["disclosed_surcharge_cents"] > disclosure["regulatory_cap_cents"]:
        raise err("ERR_SURCHARGE_CAP_EXCEEDED",
                  "Disclosed surcharge exceeds the jurisdiction regulatory cap.")
    # 9 ack text
    if not disclosure["ack_text_present"]:
        raise err("ERR_ACK_TEXT_MISSING",
                  "Consumer acknowledgement text is missing.")
    # 10 mismatch
    if disclosure["disclosed_surcharge_cents"] != atm["surcharge_cents"]:
        raise err("ERR_DISCLOSURE_MISMATCH",
                  "Disclosed surcharge does not equal the ATM's current surcharge.")

    # Supersede any prior APPROVED disclosure on this ATM.
    for other in store.fee_disclosures.values():
        if other["id"] == disclosure["id"]:
            continue
        if other["atm_id"] == atm["id"] and other["status"] == "APPROVED":
            other["status"] = "REJECTED"
            store.touch(other)

    disclosure["status"] = "APPROVED"
    store.touch(disclosure)

    atm["fee_disclosure_id"] = disclosure["id"]
    store.touch(atm)
    return disclosure
