"""Products and state regulatory profiles (PRD §2.4, §2.5, §3.1)."""
from test_helpers import (
    ApiErrorId,
    assert_filing,
    assert_instant_equals,
    assert_product,
    create_filing,
    create_locked_indication,
    create_product,
    create_product_payload,
    create_profile,
    create_profile_payload,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


def test_product_creation_populates_system_fields(api):
    """PRD §2.5: "version (integer): a system-managed integer that starts at 1
    when the resource is created and increments by one on every mutation."
    PRD §3.1: "The product also maintains `current_locked_indication_id`, a
    pointer to the most recently locked countrywide rate indication; it remains
    null until the first countrywide indication locks (§3.2)."
    PRD §2.4: "At startup the clock reads exactly `2026-08-01T00:00:00Z`, and
    it never consults wall-clock time".

    Design: Corner/entities/product_creation_defaults_and_system_fields
    """
    product = validate_success(
        api.create_product(create_product_payload(), fx.ACT1), 201
    )
    assert_product(product)
    assert product["version"] == 1
    assert product["current_locked_indication_id"] is None
    assert_instant_equals(product["created_at"], "2026-08-01T00:00:00Z")


def test_create_product_missing_product_code_rejected(api):
    """PRD §2.8: "third, request-body well-formedness — required fields
    present, no unknown fields, types correct, enum members valid, amounts
    positive, dates in ISO format — with violations rejected as
    `ERR_INVALID_REQUEST` (HTTP 400)".

    Design: Corner/entities/create_product_missing_required_product_code
    """
    res = api.create_product({"name": "Personal Auto"}, fx.ACT1)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_duplicate_profile_rejected(api):
    """PRD §3.1: "Only one profile may exist for a given product and state: a
    second attempt is rejected with `ERR_DUPLICATE_PROFILE` (HTTP 409)."

    Design: Corner/validations/duplicate_profile_rejected
    """
    product = create_product()
    create_profile(product["id"], "CA")
    res = api.create_profile(
        create_profile_payload(
            product["id"],
            "CA",
            filing_method="FILE_AND_USE",
            min_effective_lead_days=10,
            objection_response_sla_days=15,
            deemer_days=0,
            max_single_change_pct=0.20,
            renewal_notice_days=20,
            disapproval_window_days=30,
        ),
        fx.OFFICER,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_PROFILE)


def test_profile_suspend_reactivate_cycle(api):
    """PRD §3.1: "A `ComplianceOfficer` may suspend a profile, moving it from
    `ACTIVE` to `SUSPENDED`, and later reactivate it, returning it to `ACTIVE`."

    Design: Corner/state_machines/profile_suspend_reactivate_cycle
    """
    product = create_product()
    profile = create_profile(product["id"], "CA")
    assert profile["status"] == "ACTIVE"
    indication = create_locked_indication(product)

    suspended = validate_success(api.suspend_profile(profile["id"], fx.OFFICER), 200)
    assert suspended["status"] == "SUSPENDED"

    reactivated = validate_success(
        api.reactivate_profile(profile["id"], fx.OFFICER), 200
    )
    assert reactivated["status"] == "ACTIVE"

    # A reactivated profile immediately accepts new filings again.
    filing = create_filing(product["id"], "CA", indication["id"])
    assert_filing(filing)
    assert filing["status"] == "DRAFT"


def test_suspended_profile_blocks_filing_creation(api):
    """PRD §3.1: "While a profile is `SUSPENDED`, no new rate filing may be
    created for that product and state — the attempt is rejected with
    `ERR_PROFILE_INACTIVE` (HTTP 409)".

    Design: Corner/validations/suspended_profile_blocks_filing_creation
    """
    product = create_product()
    profile = create_profile(product["id"], "CA")
    get_success_data(api.suspend_profile(profile["id"], fx.OFFICER))
    indication = create_locked_indication(product)

    res = api.create_filing(
        {
            "product_id": product["id"],
            "state_code": "CA",
            "filing_type": "RATE_CHANGE",
            "proposed_change_pct": 0.10,
            "proposed_effective_date": "2026-10-01",
            "indication_id": indication["id"],
        },
        fx.ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_PROFILE_INACTIVE)
