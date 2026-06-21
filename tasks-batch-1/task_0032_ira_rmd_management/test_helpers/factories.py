"""Payload factories — one per entity, input fields only (PRD §3)."""


# ─── Account Owner (PRD §3.1) ──────────────────────────────────────


def create_owner_payload(
    full_name: str = "Test Owner",
    date_of_birth: str = "1980-01-01",
    tax_id_last4: str = "1234",
    filing_status: str = "SINGLE",
    modified_agi_cents: int = 0,
    **overrides,
) -> dict:
    payload = {
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "tax_id_last4": tax_id_last4,
        "filing_status": filing_status,
        "modified_agi_cents": modified_agi_cents,
    }
    payload.update(overrides)
    return payload


def patch_owner_agi_payload(
    modified_agi_cents: int, expected_owner_version: int, **overrides
) -> dict:
    payload = {
        "modified_agi_cents": modified_agi_cents,
        "expected_owner_version": expected_owner_version,
    }
    payload.update(overrides)
    return payload


def declare_deceased_payload(
    deceased_at: str, expected_owner_version: int, **overrides
) -> dict:
    payload = {
        "deceased_at": deceased_at,
        "expected_owner_version": expected_owner_version,
    }
    payload.update(overrides)
    return payload


# ─── IRA Account (PRD §3.2) ────────────────────────────────────────


def create_account_payload(
    owner_id: str, account_type: str = "TRADITIONAL", **overrides
) -> dict:
    payload = {"owner_id": owner_id, "account_type": account_type}
    payload.update(overrides)
    return payload


def account_version_payload(expected_account_version: int, **overrides) -> dict:
    payload = {"expected_account_version": expected_account_version}
    payload.update(overrides)
    return payload


# ─── Contribution (PRD §3.3) ───────────────────────────────────────


def create_contribution_payload(
    account_id: str,
    tax_year: int,
    amount_cents: int,
    contribution_kind: str,
    **overrides,
) -> dict:
    payload = {
        "account_id": account_id,
        "tax_year": tax_year,
        "amount_cents": amount_cents,
        "contribution_kind": contribution_kind,
    }
    payload.update(overrides)
    return payload


# ─── Distribution (PRD §3.4) ───────────────────────────────────────


def create_distribution_payload(
    account_id: str,
    amount_cents: int,
    distribution_reason: str,
    tax_year: int,
    federal_withholding_cents: int = 0,
    **overrides,
) -> dict:
    payload = {
        "account_id": account_id,
        "amount_cents": amount_cents,
        "distribution_reason": distribution_reason,
        "tax_year": tax_year,
        "federal_withholding_cents": federal_withholding_cents,
    }
    payload.update(overrides)
    return payload


# ─── Conversion (PRD §3.5) ─────────────────────────────────────────


def create_conversion_payload(
    source_account_id: str,
    target_account_id: str,
    gross_amount_cents: int,
    aggregate_basis: bool = None,
    **overrides,
) -> dict:
    payload = {
        "source_account_id": source_account_id,
        "target_account_id": target_account_id,
        "gross_amount_cents": gross_amount_cents,
    }
    if aggregate_basis is not None:
        payload["aggregate_basis"] = aggregate_basis
    payload.update(overrides)
    return payload


def conversion_version_payload(
    expected_source_account_version: int, **overrides
) -> dict:
    payload = {"expected_source_account_version": expected_source_account_version}
    payload.update(overrides)
    return payload


# ─── Beneficiary Designation (PRD §3.6) ────────────────────────────


def create_beneficiary_designation_payload(
    account_id: str,
    beneficiary_full_name: str,
    relationship: str,
    percentage_bps: int,
    **overrides,
) -> dict:
    payload = {
        "account_id": account_id,
        "beneficiary_full_name": beneficiary_full_name,
        "relationship": relationship,
        "percentage_bps": percentage_bps,
    }
    payload.update(overrides)
    return payload


# ─── RMD Schedule (PRD §3.7) ───────────────────────────────────────


def create_rmd_schedule_payload(owner_id: str, tax_year: int, **overrides) -> dict:
    payload = {"owner_id": owner_id, "tax_year": tax_year}
    payload.update(overrides)
    return payload


# ─── System Clock and Ops (PRD §2.10, §3.7) ────────────────────────


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


def advance_year_rollover_payload(new_tax_year: int, **overrides) -> dict:
    payload = {"new_tax_year": new_tax_year}
    payload.update(overrides)
    return payload
