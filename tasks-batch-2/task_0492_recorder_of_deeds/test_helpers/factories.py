"""Payload factories — one per entity, input fields only."""


def create_office_payload(**overrides) -> dict:
    defaults = {
        "county_name": "Acme",
        "book_capacity": 3,
    }
    defaults.update(overrides)
    return defaults


def create_submitter_payload(**overrides) -> dict:
    defaults = {
        "name": "Title Co",
        "submitter_type": "TITLE_COMPANY",
    }
    defaults.update(overrides)
    return defaults


def deposit_escrow_payload(submitter_id, amount_cents, **overrides) -> dict:
    defaults = {
        "submitter_id": submitter_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_package_payload(submitter_id, office_id, **overrides) -> dict:
    defaults = {
        "submitter_id": submitter_id,
        "office_id": office_id,
        "doc_type": "DEED",
        "declared_page_count": 1,
        "declared_consideration_cents": 0,
        "first_page_top_margin_inches": 3.0,
        "notary_present": True,
    }
    defaults.update(overrides)
    return defaults


def party_entry_payload(party_role, party_name, **overrides) -> dict:
    defaults = {
        "party_role": party_role,
        "party_name": party_name,
    }
    defaults.update(overrides)
    return defaults


def assessment_payload(verified_page_count, verified_consideration_cents,
                       expected_package_version, **overrides) -> dict:
    defaults = {
        "verified_page_count": verified_page_count,
        "verified_consideration_cents": verified_consideration_cents,
        "expected_package_version": expected_package_version,
    }
    defaults.update(overrides)
    return defaults


def reject_payload(reason_code, **overrides) -> dict:
    defaults = {"reason_code": reason_code}
    defaults.update(overrides)
    return defaults


def payment_payload(amount_cents, method, expected_package_version, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "method": method,
        "expected_package_version": expected_package_version,
    }
    defaults.update(overrides)
    return defaults


def create_plat_payload(submitter_id, office_id, start_lot, end_lot, **overrides) -> dict:
    defaults = {
        "submitter_id": submitter_id,
        "office_id": office_id,
        "subdivision_name": "MAPLE",
        "block_number": 1,
        "start_lot": start_lot,
        "end_lot": end_lot,
    }
    defaults.update(overrides)
    return defaults


def create_ucc_filing_payload(submitter_id, office_id, lien_type, parcel_id,
                              debtor_name, effective_date, **overrides) -> dict:
    defaults = {
        "submitter_id": submitter_id,
        "office_id": office_id,
        "lien_type": lien_type,
        "parcel_id": parcel_id,
        "debtor_name": debtor_name,
        "effective_date": effective_date,
    }
    defaults.update(overrides)
    return defaults


def create_copy_search_payload(submitter_id, request_type, **overrides) -> dict:
    defaults = {
        "submitter_id": submitter_id,
        "request_type": request_type,
    }
    defaults.update(overrides)
    return defaults
