"""Agreement terms amendment under optimistic concurrency control (PRD §2.7)."""
from test_helpers import (
    validate_success, validate_error,
    setup_active_agreement, TEST_USERS,
)

AE = TEST_USERS["account_executive_headers"]


def test_terms_amendment_applies_and_bumps_version(api):
    """PRD §2.7: "The request must carry `expected_agreement_version`, holding
    the `version` of the agreement the client last observed."
    PRD §2.7: "A successful amendment increments the agreement's `version`
    by 1."
    PRD §3.1: "While `ACTIVE`, the commercial terms may be amended — `monthly_management_fee_cents`, `variable_fee_pct`, `charter_owner_share_pct`, and `tax_allocation_method` are each individually optional in the amendment payload — but the amendment is guarded by the optimistic-concurrency rule of §2.7 and requires the agreement to be `ACTIVE` (`ERR_AGREEMENT_INVALID_STATE` otherwise)."

    Design: Corner/cross_cutting_layers/agreement_terms_amendment_happy_path
    """
    scenario = setup_active_agreement(tail_number="N520JX")
    agreement = scenario["agreement"]
    observed_version = agreement["version"]

    res = api.patch_agreement_terms(
        agreement["id"],
        {
            "expected_agreement_version": observed_version,
            "monthly_management_fee_cents": 550000,
        },
        AE,
    )
    amended = validate_success(res, 200)
    assert amended["monthly_management_fee_cents"] == 550000, (
        f"fee not amended: {amended['monthly_management_fee_cents']}"
    )
    assert amended["version"] == observed_version + 1, (
        f"version should increment by 1: {observed_version} -> {amended['version']}"
    )


def test_terms_amendment_stale_version_rejected(api):
    """PRD §2.7: "If that value does not equal the agreement's current
    `version` — meaning another writer has advanced the agreement since the
    client last read it — the amendment is rejected with
    `ERR_STALE_AGREEMENT_VERSION` (HTTP 412); the client's view of the fee and
    revenue-share terms is stale, so the amendment is refused rather than
    silently overwriting newer terms."

    Design: Corner/cross_cutting_layers/agreement_terms_amendment_stale_version_rejected
    """
    scenario = setup_active_agreement(tail_number="N530JX")
    agreement = scenario["agreement"]
    observed_version = agreement["version"]

    first = api.patch_agreement_terms(
        agreement["id"],
        {
            "expected_agreement_version": observed_version,
            "monthly_management_fee_cents": 550000,
        },
        AE,
    )
    validate_success(first, 200)

    stale = api.patch_agreement_terms(
        agreement["id"],
        {
            "expected_agreement_version": observed_version,
            "monthly_management_fee_cents": 575000,
        },
        AE,
    )
    validate_error(stale, "ERR_STALE_AGREEMENT_VERSION", expected_status=412)

    current = validate_success(api.get_agreement(agreement["id"], AE), 200)
    assert current["monthly_management_fee_cents"] == 550000, (
        "stale amendment must not overwrite newer terms"
    )
    assert current["version"] == observed_version + 1
