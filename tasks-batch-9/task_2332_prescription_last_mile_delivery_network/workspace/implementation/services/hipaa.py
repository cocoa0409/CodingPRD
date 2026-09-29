"""HIPAA minimum-necessary courier projection and its immutable disclosure trail."""

from constants import DISCLOSED_FIELDS, REDACTED_FIELD_COUNT
from db import db, iso, new_row


def masked_name(full_name):
    """First character of each whitespace token, the rest replaced by asterisks."""
    tokens = full_name.split()
    return " ".join(token[0] + "*" * (len(token) - 1) for token in tokens)


def build_projection(delivery, order, patient, window, disclosure_id):
    return {
        "delivery_id": delivery["id"],
        "order_id": order["id"],
        "patient_masked_name": patient["masked_name"],
        "patient_phone_last4": patient["phone_last4"],
        "address_line": patient["address_line"],
        "window_start": iso(window["window_start"]),
        "window_end": iso(window["window_end"]),
        "handling_class": delivery["handling_class"],
        "signature_required": delivery["signature_required"],
        "required_id_verification": delivery["required_id_verification"],
        "rx_line_count": order["rx_line_count"],
        "redacted_field_count": REDACTED_FIELD_COUNT,
        "disclosure_id": disclosure_id,
    }


def record_disclosure(delivery, courier_id, purpose):
    row = new_row(versioned=False)
    row["delivery_id"] = delivery["id"]
    row["courier_id"] = courier_id
    row["disclosed_at"] = db.clock
    row["purpose"] = purpose
    row["fields_disclosed"] = list(DISCLOSED_FIELDS)
    row["redacted_field_count"] = REDACTED_FIELD_COUNT
    row["minimization_profile"] = "COURIER_LIMITED"
    db.disclosures[row["id"]] = row
    return row
