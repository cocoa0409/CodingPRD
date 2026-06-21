"""Disclosure lifecycle: APR snapshot computation (provisional vs final),
the re-disclosure check on closing disclosures, and the first-CD edge case.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_disclosure_payload,
    create_rate_lock_payload,
    extend_rate_lock_payload,
    setup_prequalified_loan_application,
    setup_prequalified_with_active_lock,
    set_clock,
    TEST_USERS,
    ApiErrorId,
)


# =============================================================================
# Queue A — Difficulty
# =============================================================================

def test_apr_provisional_versus_final_diverge_after_extension(api, lo_headers):
    """PRD §3.7: "The provisional APR treats the prepaid finance charge as
    zero — the loan estimate excludes any lock-extension fees that may have
    accumulated. The final APR uses the application's current `ACTIVE` rate
    lock's cumulative `extension_fee_cents` as the prepaid finance charge — so
    whenever extensions exist, the final APR will be strictly greater than the
    provisional."

    Design: Difficulty/dual_variant_calc/apr_provisional_vs_final_diverge_on_disclosure
    """
    set_clock("2026-06-01T00:00:00Z", role_headers=lo_headers)
    applicant, app, lock = setup_prequalified_with_active_lock(
        applicant_overrides={
            "full_name": "Bob R",
            "email": "bob.apr@test.com",
            "ssn_last4": "5678",
            "annual_income_cents": 7_726_104,
        },
        loan_overrides={
            "property_address": "456 Oak",
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 31_578_948,
            "loan_term_months": 360,
        },
        locked_rate_bps=687,
        lock_term_days=30,
    )

    app_after_lock = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    le = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "LOAN_ESTIMATE", app_after_lock["version"]),
            lo_headers,
        ),
        201,
    )
    le_delivered = validate_success(api.deliver_disclosure(le["id"], lo_headers), 200)
    assert le_delivered["apr_at_issuance"] == pytest.approx(6.870, abs=1e-3)

    # Submit for review (precondition for delivering CLOSING_DISCLOSURE)
    validate_success(api.submit_for_review_loan_application(app["id"], lo_headers), 200)

    # Extend by 30 days — adds extension_fee_cents = 75000
    validate_success(api.extend_rate_lock(lock["id"], extend_rate_lock_payload(30), lo_headers), 200)

    app_after_ext = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    cd = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "CLOSING_DISCLOSURE", app_after_ext["version"]),
            lo_headers,
        ),
        201,
    )
    cd_delivered = validate_success(api.deliver_disclosure(cd["id"], lo_headers), 200)
    # PRD §3.7: converged apr_decimal (≈0.068946) is rounded half-up to 4 decimal
    # places (→ 0.0689), then ×100 = 6.89, rounded half-up to 3 decimal places
    # (→ 6.890). The two-step rounding is load-bearing.
    assert cd_delivered["apr_at_issuance"] == pytest.approx(6.890, abs=1e-3)

    # The two snapshots are different.
    assert le_delivered["apr_at_issuance"] != cd_delivered["apr_at_issuance"]

    final_app = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    assert final_app["provisional_apr"] == pytest.approx(6.870, abs=1e-3)
    assert final_app["final_apr"] == pytest.approx(6.890, abs=1e-3)

    lock_final = validate_success(api.get_rate_lock(lock["id"], lo_headers), 200)
    assert lock_final["extension_fee_cents"] == 75_000


def test_cd_redisclose_flag_triggers_when_apr_delta_strictly_above_12_5_bps(
    api, lo_headers
):
    """PRD §3.7: "Each time a `CLOSING_DISCLOSURE` is delivered, the system
    compares its `apr_at_issuance` to that of the immediately prior `DELIVERED`
    or `SUPERSEDED` `CLOSING_DISCLOSURE` for the same application (ordered by
    `delivered_at` descending, with `created_at` descending as the tie-break,
    and id never used as a tie-break). If there is no prior CD, this is the
    first one and `change_requires_redisclose` is `false`. Otherwise the
    absolute difference of the two APR percentages is multiplied by 100 to
    convert percent to basis points, and `change_requires_redisclose` is set
    to true when that basis-point delta is strictly greater than 12.5."

    Design: Difficulty/boundary_precision_check/cd_redisclose_apr_delta_just_under_vs_just_over_125_bps
    """
    set_clock("2026-06-01T00:00:00Z", role_headers=lo_headers)
    applicant, app, lock1 = setup_prequalified_with_active_lock(
        applicant_overrides={
            "full_name": "O",
            "email": "o.cd@test.com",
            "ssn_last4": "9005",
            "annual_income_cents": 9_000_000,
        },
        loan_overrides={
            "property_address": "CD-Bound",
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 35_000_000,
            "loan_term_months": 360,
        },
        locked_rate_bps=625,
        lock_term_days=60,
    )

    app_after_lock = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    le = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "LOAN_ESTIMATE", app_after_lock["version"]),
            lo_headers,
        ),
        201,
    )
    validate_success(api.deliver_disclosure(le["id"], lo_headers), 200)
    validate_success(api.submit_for_review_loan_application(app["id"], lo_headers), 200)

    app_after_submit = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    cd1 = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "CLOSING_DISCLOSURE", app_after_submit["version"]),
            lo_headers,
        ),
        201,
    )
    cd1_delivered = validate_success(api.deliver_disclosure(cd1["id"], lo_headers), 200)
    assert cd1_delivered["apr_at_issuance"] == pytest.approx(6.250, abs=1e-3)

    # Create a new lock at 638 bps — supersedes the prior, bumps app.version twice.
    app_after_cd1 = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    validate_success(
        api.create_rate_lock(
            create_rate_lock_payload(
                app["id"], app_after_cd1["version"], locked_rate_bps=638, lock_term_days=60
            ),
            lo_headers,
        ),
        201,
    )
    app_after_lock2 = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    cd2 = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "CLOSING_DISCLOSURE", app_after_lock2["version"]),
            lo_headers,
        ),
        201,
    )
    cd2_delivered = validate_success(api.deliver_disclosure(cd2["id"], lo_headers), 200)
    assert cd2_delivered["apr_at_issuance"] == pytest.approx(6.380, abs=1e-3)
    assert cd2_delivered["change_requires_redisclose"] is True


def test_apr_provisional_and_final_match_when_no_extensions(api, lo_headers):
    """PRD §3.7: "The provisional APR treats the prepaid finance charge as
    zero — the loan estimate excludes any lock-extension fees that may have
    accumulated. The final APR uses the application's current `ACTIVE` rate
    lock's cumulative `extension_fee_cents` as the prepaid finance charge — so
    whenever extensions exist, the final APR will be strictly greater than the
    provisional."

    Companion to the post-extension divergence test — confirms the converse:
    when extension_fee_cents == 0, the two variants compute the same APR.

    Design: Difficulty/dual_variant_calc/apr_provisional_vs_final_diverge_on_disclosure
    """
    from test_helpers import make_applicant_headers

    set_clock("2026-06-01T00:00:00Z", role_headers=lo_headers)
    applicant, app, lock = setup_prequalified_with_active_lock(
        applicant_overrides={
            "full_name": "NoExt",
            "email": "noext.apr@test.com",
            "ssn_last4": "5679",
            "annual_income_cents": 9_000_000,
        },
        loan_overrides={
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 35_000_000,
            "loan_term_months": 360,
        },
        locked_rate_bps=687,
        lock_term_days=60,
    )
    app_v2 = validate_success(api.get_loan_application(app["id"], lo_headers), 200)["version"]
    le = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "LOAN_ESTIMATE", app_v2),
            lo_headers,
        ),
        201,
    )
    le_delivered = validate_success(api.deliver_disclosure(le["id"], lo_headers), 200)
    validate_success(api.submit_for_review_loan_application(app["id"], lo_headers), 200)

    # Skip the lock extension — extension_fee_cents stays 0.
    app_after_submit = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    cd = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "CLOSING_DISCLOSURE", app_after_submit["version"]),
            lo_headers,
        ),
        201,
    )
    cd_delivered = validate_success(api.deliver_disclosure(cd["id"], lo_headers), 200)
    # With zero prepaid finance charge, provisional and final must match.
    assert cd_delivered["apr_at_issuance"] == pytest.approx(
        le_delivered["apr_at_issuance"], abs=1e-3
    )


def test_cd_redisclose_apr_delta_at_or_below_125_bps_returns_false(api, lo_headers):
    """PRD §3.7: "The boundary is sharp: a delta of exactly 12.5 basis points
    is **not** a re-disclosure trigger."

    Companion to the just-over (13.0 bps → true) test — focuses on the
    just-under side: a CD2 at locked_rate 637 bps (apr 6.370%) vs CD1 at 625
    bps (apr 6.250%) → delta=12.0 bps, change_requires_redisclose=false.

    Design: Difficulty/boundary_precision_check/cd_redisclose_apr_delta_just_under_vs_just_over_125_bps
    """
    set_clock("2026-06-01T00:00:00Z", role_headers=lo_headers)
    applicant, app, lock1 = setup_prequalified_with_active_lock(
        applicant_overrides={
            "full_name": "Just-Under",
            "email": "ju.cd@test.com",
            "ssn_last4": "8801",
            "annual_income_cents": 9_000_000,
        },
        loan_overrides={
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 35_000_000,
            "loan_term_months": 360,
        },
        locked_rate_bps=625,
        lock_term_days=60,
    )
    v2 = validate_success(api.get_loan_application(app["id"], lo_headers), 200)["version"]
    le = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "LOAN_ESTIMATE", v2),
            lo_headers,
        ),
        201,
    )
    validate_success(api.deliver_disclosure(le["id"], lo_headers), 200)
    validate_success(api.submit_for_review_loan_application(app["id"], lo_headers), 200)

    v3 = validate_success(api.get_loan_application(app["id"], lo_headers), 200)["version"]
    cd1 = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "CLOSING_DISCLOSURE", v3),
            lo_headers,
        ),
        201,
    )
    validate_success(api.deliver_disclosure(cd1["id"], lo_headers), 200)

    # Supersede prior lock with a 637 bps lock — delta 12 bps from CD1's 625.
    v4 = validate_success(api.get_loan_application(app["id"], lo_headers), 200)["version"]
    validate_success(
        api.create_rate_lock(
            create_rate_lock_payload(
                app["id"], v4, locked_rate_bps=637, lock_term_days=60
            ),
            lo_headers,
        ),
        201,
    )
    v5 = validate_success(api.get_loan_application(app["id"], lo_headers), 200)["version"]
    cd2 = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "CLOSING_DISCLOSURE", v5),
            lo_headers,
        ),
        201,
    )
    cd2_delivered = validate_success(api.deliver_disclosure(cd2["id"], lo_headers), 200)
    assert cd2_delivered["apr_at_issuance"] == pytest.approx(6.370, abs=1e-3)
    assert cd2_delivered["change_requires_redisclose"] is False


# =============================================================================
# Queue B — Corner
# =============================================================================

def test_cd_redisclose_first_cd_no_prior_returns_false(api, lo_headers):
    """PRD §3.7: "If there is no prior CD, this is the first one and
    `change_requires_redisclose` is `false`."

    Design: Corner/calculations/cd_redisclose_first_cd_no_prior_returns_false
    """
    set_clock("2026-06-01T00:00:00Z", role_headers=lo_headers)
    applicant, app, lock = setup_prequalified_with_active_lock(
        applicant_overrides={
            "full_name": "C",
            "email": "c.firstcd@test.com",
            "ssn_last4": "1110",
            "annual_income_cents": 9_000_000,
        },
        loan_overrides={
            "property_address": "First-CD",
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 35_000_000,
            "loan_term_months": 360,
        },
        locked_rate_bps=625,
        lock_term_days=60,
    )
    app_after_lock = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    le = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "LOAN_ESTIMATE", app_after_lock["version"]),
            lo_headers,
        ),
        201,
    )
    validate_success(api.deliver_disclosure(le["id"], lo_headers), 200)
    validate_success(api.submit_for_review_loan_application(app["id"], lo_headers), 200)
    app_after_submit = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    cd = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "CLOSING_DISCLOSURE", app_after_submit["version"]),
            lo_headers,
        ),
        201,
    )
    cd_delivered = validate_success(api.deliver_disclosure(cd["id"], lo_headers), 200)
    assert cd_delivered["change_requires_redisclose"] is False
    assert cd_delivered["apr_at_issuance"] == pytest.approx(6.250, abs=1e-3)


def test_disclosure_acknowledge_from_draft_returns_invalid_state(api, lo_headers):
    """PRD §3.7: "The `Applicant` acknowledges a `DELIVERED` disclosure — this
    is the one operation the borrower-as-user performs directly through the
    API."
    PRD §2.8: "then current-state legality (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/disclosure_acknowledge_from_draft_returns_invalid_state
    """
    from test_helpers import make_applicant_headers

    applicant, app, lock = setup_prequalified_with_active_lock(
        applicant_overrides={
            "full_name": "D2",
            "email": "d2.ack@test.com",
            "ssn_last4": "7020",
            "annual_income_cents": 7_726_104,
        },
        loan_overrides={
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 31_578_948,
        },
    )
    app_after_lock = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    le = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "LOAN_ESTIMATE", app_after_lock["version"]),
            lo_headers,
        ),
        201,
    )
    assert le["status"] == "DRAFT"

    appl_headers = make_applicant_headers(applicant["id"])
    res = api.acknowledge_disclosure(le["id"], appl_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    final = validate_success(api.get_disclosure(le["id"], lo_headers), 200)
    assert final["status"] == "DRAFT"
