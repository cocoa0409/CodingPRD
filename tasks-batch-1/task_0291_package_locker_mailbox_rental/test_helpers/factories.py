"""Payload factories — one per entity, input fields only.

Each factory returns a dict carrying the PRD-declared input fields with sensible
defaults; pass **overrides to control individual values for a test.
"""

DEFAULTS = {
    "FACILITY_NAME": "Test Facility",
    "TIME_ZONE": "UTC",
    "LOCKER_LABEL": "L1",
    "LOCKER_SIZE": "MEDIUM",
    "BOX_NUMBER": "B1",
    "MAILBOX_SIZE": "MEDIUM",
    "MONTHLY_FEE_CENTS": 3000,
    "CUSTOMER_NAME": "Test Customer",
    "CUSTOMER_EMAIL": "cust@example.com",
    "CUSTOMER_PHONE": "5551234567",
    "PRIMARY_ID_TYPE": "PASSPORT",
    "ADDRESS_PROOF_TYPE": "LEASE",
    "RECIPIENT_NAME": "Test Recipient",
    "RELATIONSHIP": "SELF",
    "TERM_MONTHS": 1,
    "CARRIER": "UPS",
    "PACKAGE_SIZE": "MEDIUM",
    "LONGEST_DIM_CM": 40,
    "WEIGHT_G": 3000,
    "MAIL_CLASS": "FIRST_CLASS",
    "FORWARD_KIND": "SCAN",
    "DESTINATION_ADDRESS": "1 Main St",
    "PAYMENT_METHOD": "CARD_MANUAL",
}


def create_facility_payload(**overrides) -> dict:
    payload = {"name": DEFAULTS["FACILITY_NAME"], "time_zone": DEFAULTS["TIME_ZONE"]}
    payload.update(overrides)
    return payload


def create_locker_unit_payload(facility_id, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "label": DEFAULTS["LOCKER_LABEL"],
        "size_tier": DEFAULTS["LOCKER_SIZE"],
    }
    payload.update(overrides)
    return payload


def create_mailbox_unit_payload(facility_id, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "box_number": DEFAULTS["BOX_NUMBER"],
        "size_tier": DEFAULTS["MAILBOX_SIZE"],
        "monthly_fee_cents": DEFAULTS["MONTHLY_FEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_customer_payload(facility_id, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "full_name": DEFAULTS["CUSTOMER_NAME"],
        "email": DEFAULTS["CUSTOMER_EMAIL"],
        "phone": DEFAULTS["CUSTOMER_PHONE"],
    }
    payload.update(overrides)
    return payload


def create_form_1583_payload(facility_id, customer_id, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "customer_id": customer_id,
        "primary_id_type": DEFAULTS["PRIMARY_ID_TYPE"],
        "address_proof_type": DEFAULTS["ADDRESS_PROOF_TYPE"],
    }
    payload.update(overrides)
    return payload


def create_recipient_payload(**overrides) -> dict:
    payload = {
        "recipient_name": DEFAULTS["RECIPIENT_NAME"],
        "relationship": DEFAULTS["RELATIONSHIP"],
    }
    payload.update(overrides)
    return payload


def create_rental_agreement_payload(facility_id, customer_id, mailbox_unit_id,
                                    form_1583_id, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "customer_id": customer_id,
        "mailbox_unit_id": mailbox_unit_id,
        "form_1583_id": form_1583_id,
        "term_months": DEFAULTS["TERM_MONTHS"],
    }
    payload.update(overrides)
    return payload


def create_package_payload(facility_id, rental_agreement_id, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "rental_agreement_id": rental_agreement_id,
        "carrier": DEFAULTS["CARRIER"],
        "size_tier": DEFAULTS["PACKAGE_SIZE"],
        "longest_dim_cm": DEFAULTS["LONGEST_DIM_CM"],
        "weight_g": DEFAULTS["WEIGHT_G"],
    }
    payload.update(overrides)
    return payload


def create_mail_item_payload(facility_id, rental_agreement_id, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "rental_agreement_id": rental_agreement_id,
        "mail_class": DEFAULTS["MAIL_CLASS"],
    }
    payload.update(overrides)
    return payload


def create_forwarding_request_payload(mail_item_id, **overrides) -> dict:
    payload = {
        "mail_item_id": mail_item_id,
        "kind": DEFAULTS["FORWARD_KIND"],
    }
    payload.update(overrides)
    return payload


def create_payment_payload(invoice_id, amount_cents, **overrides) -> dict:
    payload = {
        "invoice_id": invoice_id,
        "amount_cents": amount_cents,
        "method": DEFAULTS["PAYMENT_METHOD"],
    }
    payload.update(overrides)
    return payload
