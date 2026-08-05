"""Disbursement calculation (GRANT provisional vs attainment-adjusted final), the
ACCEPTED-report precondition, the payment cap, invalid-state guards, and OCC on version."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_active_agreement, setup_active_grant_with_accepted_report,
    submit_report, accept_report, add_covenant,
    create_disbursement, pay_disbursement_full, agreement_version,
    create_disbursement_payload,
    make_officer_headers,
)

OFFICER = make_officer_headers("officer-1")


def test_grant_disbursement_gross_entitlement_is_full_base(api):
    """PRD §3.6: "For a `GRANT` agreement, the entitlement is attainment-adjusted:
    `gross_entitlement_cents` is the per-period base, while `disbursed_amount_cents` is the
    per-period base multiplied by an attainment ratio, then rounded half up to whole cents."
    per_period_base = round(50,000,000 / 5) = 10,000,000.

    Design: Difficulty/dual_variant_calc/grant_provisional_vs_final_disbursement
    """
    ctx = setup_active_grant_with_accepted_report(actual_jobs=80)
    disb = create_disbursement(ctx["agreement"]["id"], ctx["report"]["id"])
    assert disb["gross_entitlement_cents"] == 10_000_000, disb["gross_entitlement_cents"]
    assert disb["status"] == "CALCULATED"


def test_grant_disbursement_final_amount_attainment_adjusted(api):
    """PRD §3.6: "That attainment ratio is the report's `actual_jobs` divided by the
    agreement's `awarded_jobs`, capped at 1.0 — so a grant recipient that meets or exceeds its
    job commitment receives the full per-period base, while one that falls short receives a
    proportionally reduced amount." 80/100 -> 10,000,000 * 0.8 = 8,000,000.

    Design: Difficulty/dual_variant_calc/grant_provisional_vs_final_disbursement
    """
    ctx = setup_active_grant_with_accepted_report(actual_jobs=80)
    disb = create_disbursement(ctx["agreement"]["id"], ctx["report"]["id"])
    assert disb["disbursed_amount_cents"] == 8_000_000, disb["disbursed_amount_cents"]


def test_disbursement_against_submitted_report_rejected(api):
    """PRD §3.6: "The linked report must be in `ACCEPTED`; otherwise the create is rejected
    with `ERR_NO_ACCEPTED_REPORT` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/disbursement_requires_accepted_report
    """
    ctx = setup_active_agreement(app_overrides={"but_for_attested": True})
    agr_id = ctx["agreement"]["id"]
    rep = submit_report(agr_id, actual_jobs=80, attestation=True)  # SUBMITTED, not accepted
    v = agreement_version(agr_id)
    validate_error(api.create_disbursement(create_disbursement_payload(agr_id, rep["id"], v), OFFICER),
                   ApiErrorId.ERR_NO_ACCEPTED_REPORT)


def test_disbursement_against_accepted_report_succeeds(api):
    """PRD §3.6: "The linked report must be in `ACCEPTED`; otherwise the create is rejected
    with `ERR_NO_ACCEPTED_REPORT` (HTTP 409)." Once the report is ACCEPTED the create
    succeeds and the disbursement is CALCULATED.

    Design: Difficulty/cross_entity_state_dependency/disbursement_requires_accepted_report
    """
    ctx = setup_active_agreement(app_overrides={"but_for_attested": True})
    agr_id = ctx["agreement"]["id"]
    rep = submit_report(agr_id, actual_jobs=100, attestation=True)
    accept_report(rep["id"])
    v = agreement_version(agr_id)
    data = validate_success(api.create_disbursement(
        create_disbursement_payload(agr_id, rep["id"], v), OFFICER), expected_status=201)
    assert data["status"] == "CALCULATED"


def test_pay_calculated_disbursement_returns_invalid_state(api):
    """PRD §3.6: "Approving or paying a disbursement from an illegal state yields
    `ERR_DISBURSEMENT_INVALID_STATE`." Paying a still-CALCULATED (never approved) disbursement.

    Design: Corner/state_machines/pay_calculated_disbursement_returns_invalid_state
    """
    ctx = setup_active_grant_with_accepted_report(actual_jobs=100)
    disb = create_disbursement(ctx["agreement"]["id"], ctx["report"]["id"])
    validate_error(api.pay_disbursement(disb["id"], OFFICER), ApiErrorId.ERR_DISBURSEMENT_INVALID_STATE)


def test_disbursement_pay_exceeds_cap_returns_402(api):
    """PRD §3.6: "Payment is capped: the agreement's `gross_disbursed_cents` plus this
    disbursement's `disbursed_amount_cents` must not exceed the agreement's `max_incentive_cents`,
    otherwise the payment is rejected with `ERR_DISBURSEMENT_EXCEEDS_CAP` (HTTP 402)."
    term_years=1 -> per_period_base == cap 50,000,000; the second full payment would total
    100,000,000.

    Design: Corner/validations/disbursement_pay_exceeds_cap_returns_402
    """
    ctx = setup_active_agreement(agreement_overrides={"term_years": 1},
                                 app_overrides={"but_for_attested": True})
    agr_id = ctx["agreement"]["id"]
    # keep the agreement ACTIVE across acceptances via a permanently-breached covenant
    add_covenant(agr_id, covenant_type="INVESTMENT", target_value=1_000_000_000,
                 measurement_start_date="2030-01-01T00:00:00.000Z",
                 measurement_end_date="2030-12-31T00:00:00.000Z")
    r1 = submit_report(agr_id, reporting_year=2027,
                       period_start_date="2027-01-01T00:00:00.000Z",
                       period_end_date="2028-01-01T00:00:00.000Z",
                       actual_jobs=100, attestation=True)
    accept_report(r1["id"])
    d1 = create_disbursement(agr_id, r1["id"])
    pay_disbursement_full(d1["id"])
    r2 = submit_report(agr_id, reporting_year=2028,
                       period_start_date="2028-01-01T00:00:00.000Z",
                       period_end_date="2029-01-01T00:00:00.000Z",
                       actual_jobs=100, attestation=True)
    accept_report(r2["id"])
    d2 = create_disbursement(agr_id, r2["id"])
    validate_success(api.approve_disbursement(d2["id"], OFFICER))
    validate_error(api.pay_disbursement(d2["id"], OFFICER), ApiErrorId.ERR_DISBURSEMENT_EXCEEDS_CAP)


def test_occ_stale_agreement_version_rejected(api):
    """PRD §2.8: "If that value does not equal the agreement's current `version`, the request
    is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)." A second create carrying the
    pre-advance version (the first create advanced it) is refused.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_agreement_version_rejected
    """
    ctx = setup_active_grant_with_accepted_report(actual_jobs=100)
    agr_id = ctx["agreement"]["id"]
    rep_id = ctx["report"]["id"]
    stale_v = agreement_version(agr_id)
    validate_success(api.create_disbursement(
        create_disbursement_payload(agr_id, rep_id, stale_v), OFFICER), expected_status=201)
    validate_error(api.create_disbursement(
        create_disbursement_payload(agr_id, rep_id, stale_v), OFFICER),
        ApiErrorId.ERR_STALE_AGREEMENT_VERSION)
