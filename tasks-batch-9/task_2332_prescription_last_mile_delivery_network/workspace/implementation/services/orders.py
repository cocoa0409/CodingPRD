"""Order-level derivations: handling class and the door-step proof requirements."""

from constants import SIGNATURE_VALUE_THRESHOLD_CENTS


def is_cold(order):
    return bool(order["cold_chain_required"])


def is_controlled(order):
    return order["controlled_schedule"] != "NONE"


def handling_class(order):
    cold = is_cold(order)
    controlled = is_controlled(order)
    if cold and controlled:
        return "COLD_CHAIN_CONTROLLED"
    if cold:
        return "COLD_CHAIN"
    if controlled:
        return "CONTROLLED"
    return "STANDARD"


def signature_required(order):
    return (is_cold(order)
            or is_controlled(order)
            or order["total_rx_value_cents"] >= SIGNATURE_VALUE_THRESHOLD_CENTS)


def required_id_verification(order):
    """Strictly ordered cascade; cold bags settle at DOB_MATCH."""
    if order["controlled_schedule"] == "CII":
        return "GOVT_ID_SCAN"
    if order["controlled_schedule"] == "CIII":
        return "PHOTO_ID"
    if order["total_rx_value_cents"] >= SIGNATURE_VALUE_THRESHOLD_CENTS:
        return "PHOTO_ID"
    return "DOB_MATCH"


def apply_proof_requirements(order):
    order["signature_required"] = signature_required(order)
    order["required_id_verification"] = required_id_verification(order)
