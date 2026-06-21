"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Only source:input fields appear here; system and
computed fields (id, status, counters, card_status, version, due_date, ...) are
server-minted and never sent.
"""


def create_branch_payload(**overrides) -> dict:
    """Branch: only `name` is required; every policy knob is optional with a
    server-side default (PRD §3.1). Tests override the knobs they pin."""
    defaults = {"name": "Test Branch"}
    defaults.update(overrides)
    return defaults


def create_patron_payload(branch_id: str, **overrides) -> dict:
    """Patron: branch_id and full_name required; patron_type/checkout_limit/
    hold_limit optional (PRD §3.1)."""
    defaults = {"branch_id": branch_id, "full_name": "Test Patron"}
    defaults.update(overrides)
    return defaults


def create_title_payload(branch_id: str, isbn: str = "9780000000000", **overrides) -> dict:
    """Title: branch_id, isbn, title_text required; default_replacement_cents
    optional (PRD §3.2)."""
    defaults = {"branch_id": branch_id, "isbn": isbn, "title_text": "Test Title"}
    defaults.update(overrides)
    return defaults


def create_copy_payload(title_id: str, branch_id: str, barcode: str = "BC-TEST",
                        acquired_on: str = "2025-06-01T00:00:00Z", **overrides) -> dict:
    """Copy: title_id, branch_id, barcode, acquired_on required; condition_factor
    optional (default 1.0) (PRD §3.2)."""
    defaults = {
        "title_id": title_id,
        "branch_id": branch_id,
        "barcode": barcode,
        "acquired_on": acquired_on,
    }
    defaults.update(overrides)
    return defaults


def create_loan_payload(copy_id: str, patron_id: str, **overrides) -> dict:
    """Loan checkout: copy_id, patron_id (PRD §3.3)."""
    defaults = {"copy_id": copy_id, "patron_id": patron_id}
    defaults.update(overrides)
    return defaults


def create_hold_payload(title_id: str, patron_id: str, **overrides) -> dict:
    """Hold: title_id, patron_id (PRD §3.6)."""
    defaults = {"title_id": title_id, "patron_id": patron_id}
    defaults.update(overrides)
    return defaults


def create_resource_payload(branch_id: str, resource_kind: str = "ROOM",
                            label: str = "Test Resource", **overrides) -> dict:
    """BookableResource: branch_id, resource_kind, label required; capacity
    optional (default 1) (PRD §3.7)."""
    defaults = {"branch_id": branch_id, "resource_kind": resource_kind, "label": label}
    defaults.update(overrides)
    return defaults


def create_reservation_payload(resource_id: str, patron_id: str, start_at: str,
                               end_at: str, expected_resource_version: int,
                               **overrides) -> dict:
    """Reservation: all of resource_id, patron_id, start_at, end_at, and the
    mandatory expected_resource_version are required (PRD §2.9, §3.7)."""
    defaults = {
        "resource_id": resource_id,
        "patron_id": patron_id,
        "start_at": start_at,
        "end_at": end_at,
        "expected_resource_version": expected_resource_version,
    }
    defaults.update(overrides)
    return defaults


def create_ill_request_payload(patron_id: str, branch_id: str,
                               isbn: str = "9780000000000", **overrides) -> dict:
    """IllRequest: patron_id, branch_id, isbn required; lending_fee_cents optional
    (default 500) (PRD §3.8)."""
    defaults = {"patron_id": patron_id, "branch_id": branch_id, "isbn": isbn}
    defaults.update(overrides)
    return defaults


def create_license_pool_payload(title_id: str, total_licenses: int = 1, **overrides) -> dict:
    """LicensePool: title_id, total_licenses required; loan_term_days optional
    (default 14) (PRD §3.9)."""
    defaults = {"title_id": title_id, "total_licenses": total_licenses}
    defaults.update(overrides)
    return defaults


def create_ebook_loan_payload(pool_id: str, patron_id: str, **overrides) -> dict:
    """EbookLoan checkout: pool_id, patron_id (PRD §3.9)."""
    defaults = {"pool_id": pool_id, "patron_id": patron_id}
    defaults.update(overrides)
    return defaults
