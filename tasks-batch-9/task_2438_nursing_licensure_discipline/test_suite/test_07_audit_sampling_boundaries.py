"""The practice-hour audit sampling pass over an empty eligible pool."""
from test_helpers import (
    ADMIN,
    RENEWAL_CLOCK,
    ApiClient,
    assert_renewal_dimensions,
    reread_renewal,
    seed_active_license,
    seed_renewal,
    validate_success,
)


def _board_with_only_a_draft_filing(api: ApiClient):
    """A board whose single renewal filing has never been paid or submitted."""
    ctx = seed_active_license(
        api,
        program_overrides={
            "program_code": "OH-BSN-91",
            "program_name": "Ashtabula BSN",
            "degree_level": "BSN",
            "nclex_first_time_pass_rate_bp": 8000,
        },
        nurse_overrides={"full_name": "Nadia Osei", "birth_year": 1993,
                         "ssn_last4": "1010"},
    )
    renewal = seed_renewal(api, ctx["license_id"], clock=RENEWAL_CLOCK,
                           attested_practice_hours=990)
    ctx["renewal"] = renewal
    ctx["renewal_id"] = renewal["id"]
    return ctx


def test_sampling_an_empty_eligible_pool_succeeds_with_zero_quota(api: ApiClient):
    """PRD §3.5: "A renewal filing is eligible for sampling when three conditions
    hold together: its `renewal_status` is `CE_VERIFIED`, its `audit_status` is
    `NOT_SELECTED`, and the credential it was filed against has an
    `issuing_board_config_id` equal to the board being sampled."

    PRD §3.5: "When no filing is eligible, the pass still succeeds:
    `eligible_count`, `quota`, and `selected_count` are all 0 and
    `selected_renewal_application_ids` is an empty array."

    PRD §3.5: "The response reports `board_config_id`, `eligible_count`, `quota`,
    `selected_count`, and `selected_renewal_application_ids`."

    Design: Difficulty/boundary_precision_check/audit_sampling_empty_eligible_pool_yields_zero_quota_not_error
    """
    ctx = _board_with_only_a_draft_filing(api)

    result = validate_success(
        api.run_audit_sampling({"board_config_id": ctx["board_id"]}, ADMIN)
    )

    assert result["board_config_id"] == ctx["board_id"]
    assert result["eligible_count"] == 0, (
        f"A DRAFT filing is not eligible, got {result['eligible_count']}"
    )
    assert result["quota"] == 0, (
        f"An empty pool draws nothing, got {result['quota']}"
    )
    assert result["selected_count"] == 0, (
        f"Nothing was drawn, got {result['selected_count']}"
    )
    assert result["selected_renewal_application_ids"] == [], (
        f"Nothing was drawn, got {result['selected_renewal_application_ids']}"
    )


def test_ineligible_filing_is_left_unscored_and_unselected(api: ApiClient):
    """PRD §3.5: "The accumulated score is rounded half up to two decimal places
    and written to `audit_risk_score` on every eligible filing, so a filing that
    was scored but not drawn still carries evidence of its assessment."

    PRD §3.5: "The highest-ranked filings up to the quota have their
    `audit_status` moved from `NOT_SELECTED` to `SELECTED`."

    PRD §3.5: "The draw size follows the board's `audit_sample_rate_bp` as a
    basis-point rate: multiply `audit_sample_rate_bp` by the eligible count,
    divide by 10000, and round the quotient **up** to the next whole number."

    Design: Difficulty/boundary_precision_check/audit_sampling_empty_eligible_pool_yields_zero_quota_not_error
    """
    ctx = _board_with_only_a_draft_filing(api)

    validate_success(api.run_audit_sampling({"board_config_id": ctx["board_id"]}, ADMIN))

    renewal = reread_renewal(api, ctx["renewal_id"])
    assert_renewal_dimensions(renewal, "DRAFT", "NOT_SELECTED")
    assert renewal["audit_risk_score"] is None, (
        f"Only eligible filings are scored, got {renewal['audit_risk_score']}"
    )
