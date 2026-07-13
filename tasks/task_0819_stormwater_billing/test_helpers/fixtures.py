"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints (the server database is empty at the start of every test). Helpers
use get_success_data() so a broken setup surfaces as a clear "Setup failed".
"""
from prd_bench_local_runner.testing import get_success_data

from .test_users import (
    TEST_USERS,
    make_billing_clerk_headers,
    make_credit_inspector_headers,
)
from . import factories as f

ASSESSOR = TEST_USERS["assessor_headers"]
BILLING_CLERK = TEST_USERS["billing_clerk_headers"]
CREDIT_INSPECTOR = TEST_USERS["credit_inspector_headers"]
STORMWATER_ADMIN = TEST_USERS["stormwater_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1/2 — accounts, parcels, active measurements
# ---------------------------------------------------------------------------

def create_account(api, **overrides) -> dict:
    resp = api.create_account(f.create_account_payload(**overrides), ASSESSOR)
    return get_success_data(resp)


def parcel_version(api, parcel_id) -> int:
    """Return the parcel's current version (for OCC-guarded measurement writes)."""
    return get_success_data(api.get_parcel(parcel_id, ASSESSOR))["version"]


def create_active_parcel(api, measured_sqft=18000, land_use="COMMERCIAL",
                         parcel_number=None, method="GIS", account=None,
                         **parcel_overrides) -> dict:
    """Account + parcel + first ACTIVE measurement (parcel DRAFT->ACTIVE).

    Returns dict: account, parcel (refetched, computed fields live),
    measurement, and parcel_version (current version after the measurement).
    """
    if account is None:
        account = create_account(api)
    p_overrides = dict(parcel_overrides)
    p_overrides["land_use"] = land_use
    if parcel_number is not None:
        p_overrides["parcel_number"] = parcel_number
    parcel = get_success_data(
        api.create_parcel(f.create_parcel_payload(account["id"], **p_overrides), ASSESSOR)
    )
    get_success_data(
        api.create_measurement(
            f.create_measurement_payload(parcel["id"], parcel["version"],
                                         measured_sqft=measured_sqft, method=method),
            ASSESSOR,
        )
    )
    parcel = get_success_data(api.get_parcel(parcel["id"], ASSESSOR))
    return {
        "account": account,
        "parcel": parcel,
        "parcel_version": parcel["version"],
    }


def grant_exemption(api, parcel_id, requested_pct, granted_pct=None,
                    category="GOVERNMENT") -> dict:
    """File and GRANT an exemption on a parcel; returns the granted exemption."""
    exemption = get_success_data(
        api.create_exemption(
            f.create_exemption_payload(parcel_id, category=category,
                                       requested_pct=requested_pct),
            ASSESSOR,
        )
    )
    payload = {"outcome": "GRANT"}
    if granted_pct is not None:
        payload["granted_pct"] = granted_pct
    return get_success_data(api.decide_exemption(exemption["id"], payload, ASSESSOR))


# ---------------------------------------------------------------------------
# Tier 3 — BMP credits and inspections
# ---------------------------------------------------------------------------

def setup_parcel_with_credit(api, measured_sqft=18000, self_reported_score=90,
                             bmp_type="RAIN_GARDEN",
                             effective_date="2026-01-01T00:00:00Z",
                             expiry_date="2027-01-01T00:00:00Z",
                             land_use="COMMERCIAL") -> dict:
    """Active parcel + one ACTIVE BMP credit. Returns the create-parcel dict
    plus a 'credit' key (refetched parcel included)."""
    base = create_active_parcel(api, measured_sqft=measured_sqft, land_use=land_use)
    credit = get_success_data(
        api.create_bmp_credit(
            f.create_bmp_credit_payload(
                base["parcel"]["id"], bmp_type=bmp_type,
                self_reported_score=self_reported_score,
                effective_date=effective_date, expiry_date=expiry_date),
            ASSESSOR,
        )
    )
    base["credit"] = credit
    base["parcel"] = get_success_data(api.get_parcel(base["parcel"]["id"], ASSESSOR))
    base["parcel_version"] = base["parcel"]["version"]
    return base


def setup_scheduled_inspection(api, measured_sqft=18000, self_reported_score=90,
                               bmp_type="RAIN_GARDEN",
                               effective_date="2026-01-01T00:00:00Z",
                               expiry_date="2027-01-01T00:00:00Z",
                               scheduled_date="2026-02-01T00:00:00Z") -> dict:
    """Active parcel + ACTIVE credit + one SCHEDULED inspection."""
    base = setup_parcel_with_credit(
        api, measured_sqft=measured_sqft, self_reported_score=self_reported_score,
        bmp_type=bmp_type, effective_date=effective_date, expiry_date=expiry_date)
    inspection = get_success_data(
        api.create_inspection(
            f.create_inspection_payload(base["credit"]["id"],
                                        scheduled_date=scheduled_date),
            CREDIT_INSPECTOR,
        )
    )
    base["inspection"] = inspection
    return base


# ---------------------------------------------------------------------------
# Tier 3 — bills
# ---------------------------------------------------------------------------

def setup_issued_bill(api, measured_sqft=18000, land_use="COMMERCIAL",
                      fee_variant=None, with_credit=False, self_reported_score=90,
                      period_start="2026-01-01T00:00:00Z",
                      period_end="2026-03-31T00:00:00Z",
                      due_date="2026-04-30T00:00:00Z") -> dict:
    """Active parcel (optionally with an ACTIVE credit) + one ISSUED bill.

    Returns dict: account, parcel, bill (refetched), and optionally credit.
    """
    if with_credit:
        base = setup_parcel_with_credit(
            api, measured_sqft=measured_sqft,
            self_reported_score=self_reported_score, land_use=land_use)
    else:
        base = create_active_parcel(api, measured_sqft=measured_sqft, land_use=land_use)
    overrides = {"period_start": period_start, "period_end": period_end,
                 "due_date": due_date}
    if fee_variant is not None:
        overrides["fee_variant"] = fee_variant
    bill = get_success_data(
        api.create_bill(
            f.create_bill_payload(base["parcel"]["id"], base["account"]["id"],
                                  **overrides),
            BILLING_CLERK,
        )
    )
    base["bill"] = get_success_data(api.get_bill(bill["id"], BILLING_CLERK))
    return base


def setup_paid_bill(api, measured_sqft=18000, amount_cents=21500,
                    creator_user_id="clerk-a", method="ACH") -> dict:
    """Active parcel + ISSUED bill + one APPLIED payment (created by
    `creator_user_id`). Returns dict with account, parcel, bill (refetched),
    and payment."""
    base = setup_issued_bill(api, measured_sqft=measured_sqft)
    payment = get_success_data(
        api.create_payment(
            f.create_payment_payload(base["bill"]["id"], base["account"]["id"],
                                     amount_cents, method=method),
            make_billing_clerk_headers(creator_user_id),
        )
    )
    base["payment"] = payment
    base["bill"] = get_success_data(api.get_bill(base["bill"]["id"], BILLING_CLERK))
    base["account"] = get_success_data(api.get_account(base["account"]["id"], BILLING_CLERK))
    return base


# ---------------------------------------------------------------------------
# Tier 3 — appeals
# ---------------------------------------------------------------------------

def setup_appeal_under_review(api, grounds="MEASUREMENT_ERROR", measured_sqft=18000,
                              bill_id=None, base=None) -> dict:
    """Active parcel + an appeal advanced SUBMITTED->UNDER_REVIEW."""
    if base is None:
        base = create_active_parcel(api, measured_sqft=measured_sqft)
    payload_over = {"grounds": grounds, "narrative": "disputed"}
    if bill_id is not None:
        payload_over["bill_id"] = bill_id
    appeal = get_success_data(
        api.create_appeal(
            f.create_appeal_payload(base["parcel"]["id"], base["account"]["id"],
                                    **payload_over),
            STORMWATER_ADMIN,
        )
    )
    get_success_data(api.review_appeal(appeal["id"], STORMWATER_ADMIN))
    base["appeal"] = get_success_data(api.get_appeal(appeal["id"], STORMWATER_ADMIN))
    return base


def setup_appeal_needs_remeasure(api, measured_sqft=18000) -> dict:
    """Active parcel + MEASUREMENT_ERROR appeal advanced to NEEDS_REMEASURE.
    Includes parcel_version (current, for the APPEAL_REMEASURE write)."""
    base = setup_appeal_under_review(api, grounds="MEASUREMENT_ERROR",
                                     measured_sqft=measured_sqft)
    get_success_data(api.remeasure_appeal(base["appeal"]["id"], STORMWATER_ADMIN))
    base["appeal"] = get_success_data(api.get_appeal(base["appeal"]["id"], STORMWATER_ADMIN))
    base["parcel"] = get_success_data(api.get_parcel(base["parcel"]["id"], ASSESSOR))
    base["parcel_version"] = base["parcel"]["version"]
    return base
