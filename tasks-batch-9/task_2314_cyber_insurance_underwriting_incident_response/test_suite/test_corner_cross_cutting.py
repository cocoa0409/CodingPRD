"""Cross-cutting mechanics: stale-read protection on the four versioned writes,
the version counter itself, and the policy-level business interruption baseline.

Every test builds the state it needs through the public API only.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import ErrorId
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.assertions import assert_money, assert_score_2dp, assert_total_count, data_of
from test_helpers.test_users import (
    ACTUARY_HEADERS,
    ADJUSTER_2_HEADERS,
    ADJUSTER_HEADERS,
    UNDERWRITER_2_HEADERS,
    UNDERWRITER_HEADERS,
)


def test_quote_with_a_stale_expected_application_version_is_refused(api):
    """A quote built on an out-of-date read of the application mutates nothing.

    "`POST /cyber/applications/{application_id}/quote` requires
    `expected_application_version`, carrying the client's last observed
    `version` of the target `Application`. A mismatch is rejected with
    `ERR_STALE_APPLICATION_VERSION` (HTTP 412)."

    "The field is **not optional** — it must be present in the request body —
    and its value must equal that parent's current `version` at the moment the
    request is served. If it does not, the write is refused and nothing is
    mutated."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_application_version_on_quote_returns_412
    """
    FX.set_clock(api, C.DEFAULT_CLOCK)
    FX.seed_catalog(api)
    account = FX.create_account(api)
    application = FX.create_application(api, account["id"])
    FX.attest_controls(api, application["id"], C.ATTEST_95)
    FX.submit_application(api, application["id"])
    scan = FX.order_scan(api, application["id"])
    FX.complete_scan(
        api, scan["id"], [F.scan_finding("EMAIL_FILTERING", "HIGH", "PARTIAL")]
    )

    before = FX.read_application(api, application["id"])
    assert before["status"] == "UNDERWRITING"

    refused = api.quote_application(
        application["id"],
        F.quote_payload(before["version"] - 1),
        UNDERWRITER_HEADERS,
    )
    validate_error(refused, ErrorId.STALE_APPLICATION_VERSION)

    after = FX.read_application(api, application["id"])
    assert after["status"] == "UNDERWRITING"
    assert after["version"] == before["version"]
    assert after.get("premium_usd") == before.get("premium_usd")
    assert after.get("quote_expires_at") == before.get("quote_expires_at")
    assert after.get("quoted_by_user_id") == before.get("quoted_by_user_id")

    # The identical request carrying the current version succeeds.
    quoted = data_of(
        api.quote_application(
            application["id"],
            F.quote_payload(before["version"]),
            UNDERWRITER_HEADERS,
        )
    )
    assert quoted["status"] == "QUOTED"
    assert quoted["version"] == before["version"] + 1


def test_bind_with_a_stale_expected_application_version_is_refused(api):
    """A binder holding an earlier view of the application mints no policy.

    "`POST /cyber/applications/{application_id}/bind` requires
    `expected_application_version` against the same `Application`. A mismatch is
    rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412)."

    "If it does not, the write is refused and nothing is mutated."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_application_version_on_bind_returns_412
    """
    FX.set_clock(api, C.DEFAULT_CLOCK)
    chain = FX.quoted_application(api)
    application_id = chain["application"]["id"]
    before = FX.read_application(api, application_id)
    assert before["status"] == "QUOTED"

    refused = api.bind_application(
        application_id,
        F.bind_payload(before["version"] - 1),
        UNDERWRITER_2_HEADERS,
    )
    validate_error(refused, ErrorId.STALE_APPLICATION_VERSION)

    assert_total_count(
        api.list_policies(UNDERWRITER_HEADERS, params={"application_id": application_id}),
        0,
    )
    after = FX.read_application(api, application_id)
    assert after["status"] == "QUOTED"
    assert after["version"] == before["version"]

    # The identical request carrying the current version mints the policy.
    policy = data_of(
        api.bind_application(
            application_id,
            F.bind_payload(before["version"]),
            UNDERWRITER_2_HEADERS,
        ),
        201,
    )
    assert policy["application_id"] == application_id
    assert policy["lifecycle_status"] == "INFORCE"
    assert FX.read_application(api, application_id)["status"] == "BOUND"


def test_proof_submission_with_a_stale_expected_claim_version_is_refused(api):
    """A proof filed against an out-of-date claim read creates no proof row.

    "`POST /cyber/incident-claims/{claim_id}/proofs-of-loss` requires
    `expected_claim_version`, carrying the client's last observed `version` of
    the target `IncidentClaim`. A mismatch is rejected with
    `ERR_STALE_CLAIM_VERSION` (HTTP 412)."

    "If it does not, the write is refused and nothing is mutated."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_claim_version_on_proof_submission_returns_412
    """
    FX.set_clock(api, C.DEFAULT_CLOCK)
    chain = FX.bound_policy(api)
    FX.set_clock(api, "2026-09-10T00:00:00Z")
    claim = FX.confirmed_claim(
        api,
        chain["policy"]["id"],
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=300000,
    )
    claim_id = claim["id"]
    before = FX.read_claim(api, claim_id)
    assert before["status"] == "COVERAGE_CONFIRMED"

    refused = api.create_proof_of_loss(
        claim_id,
        F.proof_of_loss_payload(before["version"] - 1),
        ADJUSTER_HEADERS,
    )
    validate_error(refused, ErrorId.STALE_CLAIM_VERSION)

    assert_total_count(
        api.list_proofs_of_loss(
            ADJUSTER_HEADERS, params={"incident_claim_id": claim_id}
        ),
        0,
    )
    after = FX.read_claim(api, claim_id)
    assert after["status"] == "COVERAGE_CONFIRMED"
    assert after["version"] == before["version"]
    assert after["proof_review_round"] == 0

    # The identical request carrying the current version files the proof.
    proof = data_of(
        api.create_proof_of_loss(
            claim_id,
            F.proof_of_loss_payload(before["version"]),
            ADJUSTER_HEADERS,
        ),
        201,
    )
    assert proof["status"] == "UNDER_REVIEW"
    assert FX.read_claim(api, claim_id)["status"] == "PROOF_REVIEW"


def test_renewal_quote_with_a_stale_expected_policy_version_is_refused(api):
    """A renewal quote built on an out-of-date policy read leaves the assessment alone.

    "`POST /cyber/renewal-assessments/{assessment_id}/issue-renewal-quote`
    requires `expected_policy_version`, carrying the client's last observed
    `version` of the `Policy` under review. A mismatch is rejected with
    `ERR_STALE_POLICY_VERSION` (HTTP 412)."

    "If it does not, the write is refused and nothing is mutated."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_policy_version_on_renewal_quote_returns_412
    """
    FX.set_clock(api, C.DEFAULT_CLOCK)
    chain = FX.bound_policy(api)
    policy_id = chain["policy"]["id"]

    # The renewal window opens 90 days before the 2027-08-01 period end.
    FX.set_clock(api, "2027-05-10T00:00:00Z")
    assessment = FX.open_renewal_assessment(api, policy_id, required_control_keys=[])
    assert assessment["status"] == "CONDITIONS_MET"

    policy_before = FX.read_policy(api, policy_id)
    assessment_before = data_of(
        api.get_renewal_assessment(assessment["id"], UNDERWRITER_HEADERS)
    )

    refused = api.issue_renewal_quote(
        assessment["id"],
        F.issue_renewal_quote_payload(policy_before["version"] - 1),
        ACTUARY_HEADERS,
    )
    validate_error(refused, ErrorId.STALE_POLICY_VERSION)

    assessment_after = data_of(
        api.get_renewal_assessment(assessment["id"], UNDERWRITER_HEADERS)
    )
    assert assessment_after["status"] == "CONDITIONS_MET"
    assert assessment_after["version"] == assessment_before["version"]
    assert assessment_after.get("loss_ratio") == assessment_before.get("loss_ratio")
    assert assessment_after.get("renewal_premium_usd") == assessment_before.get(
        "renewal_premium_usd"
    )
    assert assessment_after.get("premium_adjustment_pct") == assessment_before.get(
        "premium_adjustment_pct"
    )
    policy_after = FX.read_policy(api, policy_id)
    assert policy_after["version"] == policy_before["version"]

    # The identical request carrying the current version issues the quote.
    quoted = data_of(
        api.issue_renewal_quote(
            assessment["id"],
            F.issue_renewal_quote_payload(policy_after["version"]),
            ACTUARY_HEADERS,
        )
    )
    assert quoted["status"] == "RENEWAL_QUOTED"


def test_every_write_advances_the_application_version_by_exactly_one(api):
    """The version counter starts at 1, moves one step per write, and reads leave it alone.

    "`updated_at` is an ISO 8601 UTC timestamp refreshed on every change to the
    row, and `version` is an integer that starts at 1 and increments by exactly 1
    on every mutation."

    "Each attestation write recomputes the application's
    `attested_control_score` and increments the application's `version` by 1."

    "On success the server recomputes `attested_control_score` on the attested
    basis, writes `indicative_premium_usd` from the attested-basis pricing run,
    and increments the application's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/every_write_advances_the_row_version_by_exactly_one
    """
    FX.set_clock(api, C.DEFAULT_CLOCK)
    FX.seed_catalog(api)
    account = FX.create_account(api)
    application = FX.create_application(api, account["id"])
    assert application["version"] == 1
    assert application["status"] == "DRAFT"

    expected_version = 1
    for control_key in ["MFA_PRIVILEGED", "OFFLINE_BACKUPS", "EDR_COVERAGE"]:
        data_of(
            api.create_control_attestation(
                application["id"],
                F.control_attestation_payload(control_key, "FULL"),
                UNDERWRITER_HEADERS,
            ),
            201,
        )
        expected_version += 1
        current = FX.read_application(api, application["id"])
        assert current["version"] == expected_version

    assert expected_version == 4

    FX.submit_application(api, application["id"])
    submitted = FX.read_application(api, application["id"])
    assert submitted["version"] == 5
    assert submitted["status"] == "SUBMITTED"
    assert_score_2dp(submitted["attested_control_score"], 75.00, "attested_control_score")

    # Two further reads are not mutations, so the counter does not move.
    first_read = FX.read_application(api, application["id"])
    second_read = FX.read_application(api, application["id"])
    assert first_read["version"] == 5
    assert second_read["version"] == 5


def test_bi_variant_comes_from_the_policy_baseline_when_no_override_is_supplied(api):
    """With no override the policy's own baseline method drives the whole quantification.

    "The adjuster may supply a `baseline_method_override`;
    `baseline_method_applied` records the variant actually used, which is the
    override when one is supplied and the policy's `bi_baseline_method`
    otherwise."

    "Under `SAME_PERIOD_PRIOR_YEAR` it is `prior_year_same_period_revenue_usd`
    divided by `prior_year_same_period_hours`, taken from the matching
    prior-year window, so a seasonal peak raises every downstream component and
    the assessed indemnity with it."

    "The cap is computed from the **already rounded** `bi_component_usd`, not
    from the raw product behind it."

    Design: Corner/cross_cutting_complexity_layers/bi_variant_is_selected_by_the_policy_baseline_field_without_an_override
    """
    FX.set_clock(api, C.DEFAULT_CLOCK)
    chain = FX.bound_policy(api, bi_baseline_method="SAME_PERIOD_PRIOR_YEAR")
    policy_id = chain["policy"]["id"]
    assert chain["policy"]["bi_baseline_method"] == "SAME_PERIOD_PRIOR_YEAR"

    FX.set_clock(api, "2026-09-10T00:00:00Z")
    claim = FX.confirmed_claim(
        api,
        policy_id,
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=300000,
    )
    proof = FX.file_proof(
        api,
        claim["id"],
        claimed_bi_loss_usd=400000,
        trailing_12m_revenue_usd=43800000,
        prior_year_same_period_revenue_usd=1200000,
        prior_year_same_period_hours=200,
        gross_profit_margin_pct=0.62,
        extra_expense_usd=60000,
        mitigation_savings_usd=20000,
    )

    # No baseline_method_override is supplied on acceptance.
    FX.accept_proof(api, proof["id"], headers=ADJUSTER_2_HEADERS)

    accepted = data_of(api.get_proof_of_loss(proof["id"], ADJUSTER_HEADERS))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["baseline_method_applied"] == "SAME_PERIOD_PRIOR_YEAR"
    assert float(accepted["outage_hours"]) == 72.00
    assert float(accepted["compensable_hours"]) == 60.00
    # 60 hours x (1,200,000 / 200) x 0.62
    assert_money(accepted["bi_component_usd"], 223200.00, "bi_component_usd")
    assert_money(accepted["mitigation_component_usd"], 20000.00, "mitigation_component_usd")
    # 25 percent of the already rounded 223,200.00
    assert_money(
        accepted["extra_expense_component_usd"], 55800.00, "extra_expense_component_usd"
    )
    assert_money(accepted["assessed_indemnity_usd"], 259000.00, "assessed_indemnity_usd")

    payments = FX.list_payments_for_claim(api, claim["id"])
    assert len(payments) == 1
    payment = payments[0]
    assert payment["loss_source"] == "PROOF_OF_LOSS"
    assert payment["payment_status"] == "POSTED"
    assert payment["coverage_section_id"] == chain["sections"]["BUSINESS_INTERRUPTION"]["id"]
    assert_money(payment["retention_applied_usd"], 250000.00, "retention_applied_usd")
    assert_money(payment["gross_amount_usd"], 9000.00, "gross_amount_usd")
    assert_money(payment["coinsurance_deduction_usd"], 900.00, "coinsurance_deduction_usd")
    assert_money(payment["net_paid_usd"], 8100.00, "net_paid_usd")

    settled = FX.read_claim(api, claim["id"])
    assert settled["status"] == "SETTLED"
    assert_money(settled["retention_absorbed_usd"], 250000.00, "retention_absorbed_usd")
    assert_money(settled["paid_total_usd"], 8100.00, "paid_total_usd")
    assert_money(settled["reserved_amount_usd"], 0, "reserved_amount_usd")

    section = data_of(
        api.get_coverage_section(
            chain["sections"]["BUSINESS_INTERRUPTION"]["id"], UNDERWRITER_HEADERS
        )
    )
    assert_money(section["sublimit_remaining_usd"], 1991000.00, "sublimit_remaining_usd")
    policy = FX.read_policy(api, policy_id)
    assert_money(
        policy["aggregate_limit_remaining_usd"], 4991900.00, "aggregate_limit_remaining_usd"
    )
