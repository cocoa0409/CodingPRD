"""Payload factories — one per entity, client-input fields only.

System-managed fields (statuses, snapshots, derived totals, actor ids) are
never supplied by the client. Optional fields that default to null are
omitted from the payload unless explicitly overridden.
"""

DEFAULTS = {
    "PRIMARY_OWNER_NAME": "Owner O",
    "OWNER_TAX_ID": "T-1",
    "OWNERSHIP_TYPE": "INDIVIDUAL",
    "PRODUCT_CODE": "SAVINGS",
    "RATE_BPS": 0,
    "OPENING_DEPOSIT_CENTS": 5000,
    "SIGNER_FULL_NAME": "Sig S",
    "SIGNER_TAX_ID": "TS-1",
    "SIGNER_ROLE": "AUTHORIZED_SIGNER",
    "CREDITOR_NAME": "CredCo",
    "DECEDENT_NAME": "Dec D",
    "REPORTED_BY": "Kin D",
    "ESTATE_REPRESENTATIVE_NAME": "Exec E",
}


def create_account_payload(**overrides) -> dict:
    defaults = {
        "primary_owner_name": DEFAULTS["PRIMARY_OWNER_NAME"],
        "owner_tax_id": DEFAULTS["OWNER_TAX_ID"],
        "ownership_type": DEFAULTS["OWNERSHIP_TYPE"],
        "product_code": DEFAULTS["PRODUCT_CODE"],
        "rate_bps": DEFAULTS["RATE_BPS"],
        "opening_deposit_cents": DEFAULTS["OPENING_DEPOSIT_CENTS"],
    }
    defaults.update(overrides)
    # pod_beneficiary_name is required exactly when ownership_type is POD;
    # leave it out of the payload entirely unless the caller supplies it.
    if defaults.get("pod_beneficiary_name") is None:
        defaults.pop("pod_beneficiary_name", None)
    return defaults


def transaction_payload(txn_type, amount_cents, **overrides) -> dict:
    defaults = {
        "txn_type": txn_type,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    # Optional inputs default server-side; omit when not overridden.
    for key in ("customer_initiated", "posted_date"):
        if defaults.get(key) is None:
            defaults.pop(key, None)
    return defaults


def signer_payload(signature_card_reference, **overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["SIGNER_FULL_NAME"],
        "tax_id": DEFAULTS["SIGNER_TAX_ID"],
        "signer_role": DEFAULTS["SIGNER_ROLE"],
        "signature_card_reference": signature_card_reference,
    }
    defaults.update(overrides)
    return defaults


def document_payload(doc_type, reference_number) -> dict:
    return {"doc_type": doc_type, "reference_number": reference_number}


def review_payload(decision, **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def title_change_payload(requested_ownership_type, expected_account_version,
                         **overrides) -> dict:
    defaults = {
        "requested_ownership_type": requested_ownership_type,
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    if defaults.get("pod_beneficiary_name") is None:
        defaults.pop("pod_beneficiary_name", None)
    return defaults


def reject_title_payload(reason, **overrides) -> dict:
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults


def deceased_case_payload(date_of_death, **overrides) -> dict:
    defaults = {
        "decedent_name": DEFAULTS["DECEDENT_NAME"],
        "date_of_death": date_of_death,
        "reported_by": DEFAULTS["REPORTED_BY"],
    }
    defaults.update(overrides)
    return defaults


def initiate_release_payload(release_variant, **overrides) -> dict:
    defaults = {
        "release_variant": release_variant,
        "estate_representative_name": DEFAULTS["ESTATE_REPRESENTATIVE_NAME"],
    }
    defaults.update(overrides)
    return defaults


def garnishment_payload(amount_cents, served_date, exemption_method,
                        **overrides) -> dict:
    defaults = {
        "order_type": "GARNISHMENT",
        "creditor_name": DEFAULTS["CREDITOR_NAME"],
        "amount_cents": amount_cents,
        "served_date": served_date,
        "exemption_method": exemption_method,
    }
    defaults.update(overrides)
    return defaults


def resolve_payload(resolution, **overrides) -> dict:
    defaults = {"resolution": resolution}
    defaults.update(overrides)
    return defaults


def statement_cycle_payload(cycle_start, cycle_end) -> dict:
    return {"cycle_start": cycle_start, "cycle_end": cycle_end}


def conversion_payload(to_product_code, new_rate_bps, effective_date) -> dict:
    return {
        "to_product_code": to_product_code,
        "new_rate_bps": new_rate_bps,
        "effective_date": effective_date,
    }
