"""Payload factories: one per request body described by the PRD.

Every factory returns a dict carrying only caller-supplied input fields, with
sensible defaults, and accepts **overrides. Passing ``field=None`` keeps the key
with a null value; use ``omit_fields`` to drop keys entirely when a test needs
to exercise an omitted optional field or a missing required field.
"""

DEFAULTS = {
    "LEASE_NUMBER": "L-001",
    "LESSOR_NAME": "Alpha Minerals",
    "GROSS_ACRES": 640.00,
    "ROYALTY_RATE": 0.1875,
    "PRIMARY_TERM_END_DATE": "2026-09-30",
    "EXTENSION_OPTION_MONTHS": 24,
    "EXTENSION_BONUS_PER_ACRE_CENTS": 15000,
    "SHUT_IN_ROYALTY_PER_ACRE_CENTS": 500,
    "CONTINUOUS_DEV_WINDOW_DAYS": 180,
    "WELL_NAME": "Sandstone 1H",
    "API_NUMBER": "42-123-45678",
    "PRODUCT_TYPE": "OIL",
    "TOTAL_DEPTH_FT": 9500,
    "SPUD_DATE": "2026-02-10",
    "OWNER_NAME": "Operator Energy LLC",
    "OWNER_TYPE": "WORKING_INTEREST_PARTNER",
    "CONTACT_EMAIL": "operator@example.com",
    "AFE_NUMBER": "AFE-2026-001",
    "OPERATION_TYPE": "DRILL",
    "ESTIMATED_COST_CENTS": 2_000_000,
    "COST_CLASS": "CAPITAL",
    "ELECTION_DEADLINE_DATE": "2026-07-31",
    "STATEMENT_NUMBER": "JIB-2026-06",
    "BILLING_PERIOD_START": "2026-06-01",
    "BILLING_PERIOD_END": "2026-06-30",
    "COST_BASIS": "ACCRUAL",
    "ACTIVITY_CLASS": "PRODUCING",
    "OVERHEAD_RATE_CLASS": "PERCENTAGE_BASIS",
    "BASIS_NOTE": "Overhead allocation appears overstated for the period.",
    "PRODUCTION_MONTH": "2026-06",
    "GROSS_REVENUE_CENTS": 5_000_000,
    "VOLUME_UNITS": 6200.0,
}


def _finish(defaults: dict, overrides: dict) -> dict:
    omit = overrides.pop("omit_fields", None) or []
    if isinstance(omit, str):
        omit = [omit]
    defaults.update(overrides)
    for key in omit:
        defaults.pop(key, None)
    return defaults


# --- Logical clock --------------------------------------------------------


def set_clock_payload(current_utc: str, **overrides) -> dict:
    return _finish({"current_utc": current_utc}, overrides)


# --- Leases ---------------------------------------------------------------


def create_lease_payload(**overrides) -> dict:
    return _finish(
        {
            "lease_number": DEFAULTS["LEASE_NUMBER"],
            "lessor_name": DEFAULTS["LESSOR_NAME"],
            "gross_acres": DEFAULTS["GROSS_ACRES"],
            "royalty_rate": DEFAULTS["ROYALTY_RATE"],
            "primary_term_end_date": DEFAULTS["PRIMARY_TERM_END_DATE"],
            "extension_option_months": DEFAULTS["EXTENSION_OPTION_MONTHS"],
            "extension_bonus_per_acre_cents": DEFAULTS[
                "EXTENSION_BONUS_PER_ACRE_CENTS"
            ],
            "shut_in_royalty_per_acre_cents": DEFAULTS[
                "SHUT_IN_ROYALTY_PER_ACRE_CENTS"
            ],
            "continuous_dev_window_days": DEFAULTS["CONTINUOUS_DEV_WINDOW_DAYS"],
        },
        overrides,
    )


def minimal_lease_payload(**overrides) -> dict:
    """Only the fields the PRD requires at recording; every optional term
    omitted so the declared defaults apply."""
    return _finish(
        {
            "lease_number": DEFAULTS["LEASE_NUMBER"],
            "lessor_name": DEFAULTS["LESSOR_NAME"],
            "gross_acres": DEFAULTS["GROSS_ACRES"],
            "royalty_rate": DEFAULTS["ROYALTY_RATE"],
            "primary_term_end_date": DEFAULTS["PRIMARY_TERM_END_DATE"],
        },
        overrides,
    )


def lease_extension_payload(bonus_paid_cents: int, **overrides) -> dict:
    return _finish({"bonus_paid_cents": bonus_paid_cents}, overrides)


def obligation_event_payload(event_type: str, event_date: str, **overrides) -> dict:
    return _finish({"event_type": event_type, "event_date": event_date}, overrides)


# --- Wells ----------------------------------------------------------------


def create_well_payload(**overrides) -> dict:
    return _finish(
        {
            "well_name": DEFAULTS["WELL_NAME"],
            "api_number": DEFAULTS["API_NUMBER"],
            "product_type": DEFAULTS["PRODUCT_TYPE"],
            "total_depth_ft": DEFAULTS["TOTAL_DEPTH_FT"],
            "spud_date": DEFAULTS["SPUD_DATE"],
        },
        overrides,
    )


def well_status_change_payload(to_status: str, **overrides) -> dict:
    return _finish({"to_status": to_status}, overrides)


def lease_allocation_payload(lease_id: str, committed_acres: float, **overrides) -> dict:
    return _finish(
        {"lease_id": lease_id, "committed_acres": committed_acres}, overrides
    )


def pooling_effectuation_payload(effective_date: str, **overrides) -> dict:
    return _finish({"effective_date": effective_date}, overrides)


# --- Interest owners ------------------------------------------------------


def create_interest_owner_payload(**overrides) -> dict:
    return _finish(
        {
            "owner_name": DEFAULTS["OWNER_NAME"],
            "owner_type": DEFAULTS["OWNER_TYPE"],
            "contact_email": DEFAULTS["CONTACT_EMAIL"],
            "tax_id_on_file": True,
            "bond_posted_cents": 50_000_000,
            "audit_window_days": 730,
        },
        overrides,
    )


def minimal_interest_owner_payload(**overrides) -> dict:
    """Only the fields the PRD requires at registration."""
    return _finish(
        {
            "owner_name": DEFAULTS["OWNER_NAME"],
            "owner_type": DEFAULTS["OWNER_TYPE"],
            "contact_email": DEFAULTS["CONTACT_EMAIL"],
        },
        overrides,
    )


def compliance_update_payload(**overrides) -> dict:
    return _finish({}, overrides)


# --- Well interests ------------------------------------------------------


def create_well_interest_payload(
    owner_id: str,
    working_interest_pct: float,
    net_revenue_interest_pct: float,
    effective_from: str,
    expected_well_version: int,
    **overrides,
) -> dict:
    return _finish(
        {
            "owner_id": owner_id,
            "working_interest_pct": working_interest_pct,
            "net_revenue_interest_pct": net_revenue_interest_pct,
            "effective_from": effective_from,
            "is_operator": False,
            "preferential_right": False,
            "expected_well_version": expected_well_version,
        },
        overrides,
    )


def interest_termination_payload(effective_to: str, **overrides) -> dict:
    return _finish({"effective_to": effective_to}, overrides)


# --- AFEs and elections --------------------------------------------------


def create_afe_payload(**overrides) -> dict:
    return _finish(
        {
            "afe_number": DEFAULTS["AFE_NUMBER"],
            "operation_type": DEFAULTS["OPERATION_TYPE"],
            "estimated_cost_cents": DEFAULTS["ESTIMATED_COST_CENTS"],
            "cost_class": DEFAULTS["COST_CLASS"],
            "election_deadline_date": DEFAULTS["ELECTION_DEADLINE_DATE"],
            "non_consent_penalty_multiple": 3.0,
            "minimum_consent_pct": 0.500000,
        },
        overrides,
    )


def minimal_afe_payload(**overrides) -> dict:
    """Only the fields the PRD requires when issuing an authorization."""
    return _finish(
        {
            "afe_number": DEFAULTS["AFE_NUMBER"],
            "operation_type": DEFAULTS["OPERATION_TYPE"],
            "estimated_cost_cents": DEFAULTS["ESTIMATED_COST_CENTS"],
            "cost_class": DEFAULTS["COST_CLASS"],
            "election_deadline_date": DEFAULTS["ELECTION_DEADLINE_DATE"],
        },
        overrides,
    )


def afe_election_payload(owner_id: str, election_type: str, **overrides) -> dict:
    return _finish({"owner_id": owner_id, "election_type": election_type}, overrides)


def election_closure_payload(**overrides) -> dict:
    return _finish({}, overrides)


# --- Cost entries --------------------------------------------------------


def create_cost_entry_payload(
    cost_category: str = "LEASE_OPERATING",
    cost_class: str = "OPERATING",
    amount_cents: int = 300_000,
    incurred_date: str = "2026-06-15",
    **overrides,
) -> dict:
    return _finish(
        {
            "cost_category": cost_category,
            "cost_class": cost_class,
            "amount_cents": amount_cents,
            "incurred_date": incurred_date,
        },
        overrides,
    )


def cost_entry_payment_payload(paid_date: str, **overrides) -> dict:
    return _finish({"paid_date": paid_date}, overrides)


# --- Joint interest billing statements -----------------------------------


def create_jib_statement_payload(**overrides) -> dict:
    return _finish(
        {
            "statement_number": DEFAULTS["STATEMENT_NUMBER"],
            "billing_period_start": DEFAULTS["BILLING_PERIOD_START"],
            "billing_period_end": DEFAULTS["BILLING_PERIOD_END"],
            "cost_basis": DEFAULTS["COST_BASIS"],
            "activity_class": DEFAULTS["ACTIVITY_CLASS"],
            "overhead_rate_class": DEFAULTS["OVERHEAD_RATE_CLASS"],
        },
        overrides,
    )


def statement_revision_payload(
    statement_number: str, expected_jib_statement_version: int, **overrides
) -> dict:
    return _finish(
        {
            "statement_number": statement_number,
            "expected_jib_statement_version": expected_jib_statement_version,
        },
        overrides,
    )


# --- Disputes -------------------------------------------------------------


def file_dispute_payload(
    owner_id: str,
    disputed_amount_cents: int,
    dispute_kind: str = "BILLING_DISPUTE",
    **overrides,
) -> dict:
    return _finish(
        {
            "owner_id": owner_id,
            "dispute_kind": dispute_kind,
            "disputed_amount_cents": disputed_amount_cents,
            "basis_note": DEFAULTS["BASIS_NOTE"],
        },
        overrides,
    )


def dispute_exchange_payload(
    exchange_type: str, exchange_note: str = "Recorded exchange.", **overrides
) -> dict:
    return _finish(
        {"exchange_type": exchange_type, "exchange_note": exchange_note}, overrides
    )


def dispute_resolution_payload(
    outcome: str, adjustment_amount_cents: int, **overrides
) -> dict:
    return _finish(
        {"outcome": outcome, "adjustment_amount_cents": adjustment_amount_cents},
        overrides,
    )


# --- Production revenue and disbursements --------------------------------


def create_production_revenue_payload(
    production_month: str = DEFAULTS["PRODUCTION_MONTH"],
    gross_revenue_cents: int = DEFAULTS["GROSS_REVENUE_CENTS"],
    volume_units: float = DEFAULTS["VOLUME_UNITS"],
    sale_date: str = "2026-07-05",
    **overrides,
) -> dict:
    return _finish(
        {
            "production_month": production_month,
            "gross_revenue_cents": gross_revenue_cents,
            "volume_units": volume_units,
            "sale_date": sale_date,
        },
        overrides,
    )


def disbursement_payment_payload(**overrides) -> dict:
    return _finish({}, overrides)


# --- Assignment transfers -------------------------------------------------


def create_assignment_transfer_payload(
    assignor_owner_id: str,
    assignee_owner_id: str,
    transfer_wi_pct: float,
    transfer_nri_pct: float,
    notice_date: str,
    effective_date: str,
    sale_price_cents: int = 25_000_000,
    **overrides,
) -> dict:
    return _finish(
        {
            "assignor_owner_id": assignor_owner_id,
            "assignee_owner_id": assignee_owner_id,
            "transfer_wi_pct": transfer_wi_pct,
            "transfer_nri_pct": transfer_nri_pct,
            "sale_price_cents": sale_price_cents,
            "notice_date": notice_date,
            "effective_date": effective_date,
        },
        overrides,
    )


def ppr_election_payload(election: str, **overrides) -> dict:
    return _finish({"election": election}, overrides)


def transfer_closing_payload(closing_date: str, **overrides) -> dict:
    return _finish({"closing_date": closing_date}, overrides)


def statement_void_payload(void_reason: str, **overrides) -> dict:
    return _finish({"void_reason": void_reason}, overrides)


def statement_settlement_payload(settled_on: str, **overrides) -> dict:
    return _finish({"settled_on": settled_on}, overrides)
