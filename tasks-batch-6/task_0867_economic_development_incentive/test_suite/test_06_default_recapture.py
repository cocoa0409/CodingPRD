"""Default cascade, recapture math (cliff vs pro-rata), the finalize clawback that
conserves the agreement disbursement ledger, and the dispute/reopen cycle."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_active_agreement, add_covenant, submit_report, accept_report,
    create_disbursement, pay_disbursement_full, declare_default, recapture_for_agreement,
    make_applicant_headers, make_officer_headers, make_director_headers,
)

APPLICANT = make_applicant_headers("applicant-1")
OFFICER = make_officer_headers("officer-1")
DIRECTOR = make_director_headers("director-1")


def _partial_default_context(api):
    """Active GRANT agreement: JOBS(100) BREACHED (actual 80), INVESTMENT(100M) MET
    (actual 150M), one PAID disbursement of 8,000,000, then PARTIAL default."""
    ctx = setup_active_agreement(app_overrides={"but_for_attested": True})
    agr_id = ctx["agreement"]["id"]
    add_covenant(agr_id, covenant_type="JOBS", target_value=100,
                 measurement_start_date="2027-01-01T00:00:00.000Z",
                 measurement_end_date="2027-12-31T00:00:00.000Z")
    add_covenant(agr_id, covenant_type="INVESTMENT", target_value=100_000_000,
                 measurement_start_date="2027-01-01T00:00:00.000Z",
                 measurement_end_date="2027-12-31T00:00:00.000Z")
    rep = submit_report(agr_id, actual_jobs=80, actual_investment_cents=150_000_000, attestation=True)
    accept_report(rep["id"])
    disb = create_disbursement(agr_id, rep["id"])
    pay_disbursement_full(disb["id"])
    declare_default(agr_id, "PARTIAL", "jobs shortfall")
    return agr_id, recapture_for_agreement(agr_id)


def test_partial_recapture_prorata_amount(api):
    """PRD §3.7: "A `PARTIAL` default is pro-rata: the agreement's `net_disbursed_cents` is
    multiplied by the ratio of `breached_covenants_count` to `total_covenants_count`, then
    rounded half up to whole cents." 8,000,000 * 1/2 = 4,000,000.

    Design: Difficulty/dual_variant_calc/recapture_cliff_vs_prorata
    """
    _, ra = _partial_default_context(api)
    assert ra["assessed_amount_cents"] == 4_000_000, ra["assessed_amount_cents"]


def test_partial_recapture_records_covenant_counts(api):
    """PRD §3.7: "a `breached_covenants_count` equal to the number of covenants not in `MET` or
    `WAIVED` at default time, and a `total_covenants_count` equal to all covenants on the
    agreement at default time." One breached (JOBS) of two total.

    Design: Difficulty/dual_variant_calc/recapture_cliff_vs_prorata
    """
    _, ra = _partial_default_context(api)
    assert ra["severity"] == "PARTIAL"
    assert ra["breached_covenants_count"] == 1, ra["breached_covenants_count"]
    assert ra["total_covenants_count"] == 2, ra["total_covenants_count"]


def test_declare_default_breaches_covenant_and_defaults_agreement(api):
    """PRD §3.7: "Declaring default advances the agreement `ACTIVE → DEFAULTED`, increments
    its `version`, and fires the default cascade in two hops: first, every covenant currently
    `ACTIVE` is driven to `BREACHED`; second, the resulting set of covenants not in `MET` or `WAIVED`
    gives rise to exactly one recapture assessment in status `ASSESSED`."

    Design: Difficulty/transitive_cascade/default_breach_recapture_depth3
    """
    ctx = setup_active_agreement(app_overrides={"but_for_attested": True})
    agr_id = ctx["agreement"]["id"]
    cov = add_covenant(agr_id, covenant_type="JOBS", target_value=100)
    declare_default(agr_id, "MATERIAL", "abandonment")
    agr = validate_success(api.get_agreement(agr_id, DIRECTOR))
    covd = validate_success(api.get_covenant(cov["id"], DIRECTOR))
    assert agr["status"] == "DEFAULTED"
    assert covd["status"] == "BREACHED"


def test_declare_default_creates_assessed_recapture(api):
    """PRD §3.7: "A `MATERIAL` default is a cliff: the full `net_disbursed_cents` of the
    agreement is recaptured." With no disbursements the recapture is ASSESSED at 0 with one
    breached covenant.

    Design: Difficulty/transitive_cascade/default_breach_recapture_depth3
    """
    ctx = setup_active_agreement(app_overrides={"but_for_attested": True})
    agr_id = ctx["agreement"]["id"]
    add_covenant(agr_id, covenant_type="JOBS", target_value=100)
    declare_default(agr_id, "MATERIAL", "abandonment")
    ra = recapture_for_agreement(agr_id)
    assert ra["status"] == "ASSESSED"
    assert ra["breached_covenants_count"] == 1, ra["breached_covenants_count"]
    assert ra["assessed_amount_cents"] == 0, ra["assessed_amount_cents"]


def _finalized_clawback_context(api):
    """Active GRANT agreement: JOBS(100) MET, INVESTMENT(300M) BREACHED keep it ACTIVE; one
    PAID disbursement of 10,000,000; MATERIAL default; recapture finalized (clawback)."""
    ctx = setup_active_agreement(app_overrides={"but_for_attested": True})
    agr_id = ctx["agreement"]["id"]
    add_covenant(agr_id, covenant_type="JOBS", target_value=100,
                 measurement_start_date="2027-01-01T00:00:00.000Z",
                 measurement_end_date="2027-12-31T00:00:00.000Z")
    add_covenant(agr_id, covenant_type="INVESTMENT", target_value=300_000_000,
                 measurement_start_date="2028-01-01T00:00:00.000Z",
                 measurement_end_date="2028-12-31T00:00:00.000Z")
    rep = submit_report(agr_id, actual_jobs=100, actual_investment_cents=150_000_000, attestation=True)
    accept_report(rep["id"])
    disb = create_disbursement(agr_id, rep["id"])
    pay_disbursement_full(disb["id"])
    declare_default(agr_id, "MATERIAL", "investment shortfall")
    ra = recapture_for_agreement(agr_id)
    validate_success(api.finalize_assessment(ra["id"], OFFICER))
    return agr_id, disb["id"]


def test_clawback_conserves_gross_and_zeroes_net(api):
    """PRD §2.7: "`net_disbursed_cents` is the current cash out the door and always equals
    `gross_disbursed_cents` minus `clawed_back_cents`." After clawback gross stays 10,000,000,
    net is 0, and clawed_back is 10,000,000; the disbursement is CLAWED_BACK.

    Design: Difficulty/compensating_invariant/agreement_disbursement_ledger_conserved
    """
    agr_id, disb_id = _finalized_clawback_context(api)
    agr = validate_success(api.get_agreement(agr_id, DIRECTOR))
    disb = validate_success(api.get_disbursement(disb_id, OFFICER))
    assert agr["gross_disbursed_cents"] == 10_000_000, agr["gross_disbursed_cents"]
    assert agr["net_disbursed_cents"] == 0, agr["net_disbursed_cents"]
    assert agr["clawed_back_cents"] == 10_000_000, agr["clawed_back_cents"]
    assert disb["status"] == "CLAWED_BACK"


def test_finalize_closes_agreement(api):
    """PRD §3.7: "Otherwise finalization advances the record from `ASSESSED` or `DISPUTED` to
    `FINALIZED` and drives the recapture cascade — every `PAID` disbursement on the agreement
    moves to `CLAWED_BACK` (each hop subtracting the disbursed amount from the agreement's
    `net_disbursed_cents`, adding it to `clawed_back_cents`, leaving `gross_disbursed_cents`
    unchanged, and returning the amount from the program's disbursed bucket into available),
    and the agreement bubbles `DEFAULTED → CLOSED`."

    Design: Difficulty/compensating_invariant/agreement_disbursement_ledger_conserved
    """
    agr_id, _ = _finalized_clawback_context(api)
    agr = validate_success(api.get_agreement(agr_id, DIRECTOR))
    assert agr["status"] == "CLOSED"


def test_recapture_dispute_reopen_cycle(api):
    """PRD §3.7: "Finalization carries an optional `reopen` flag: when `reopen` is true against a
    `DISPUTED` assessment, the officer bounces it back `DISPUTED → ASSESSED` for further review
    without any clawback."

    Design: Corner/state_machines/recapture_dispute_reopen_cycle
    """
    ctx = setup_active_agreement(app_overrides={"but_for_attested": True})
    agr_id = ctx["agreement"]["id"]
    add_covenant(agr_id, covenant_type="JOBS", target_value=100)
    declare_default(agr_id, "PARTIAL", "no reporting")
    ra = recapture_for_agreement(agr_id)
    disputed = validate_success(api.dispute_assessment(ra["id"], APPLICANT, {"grounds": "force majeure"}))
    assert disputed["status"] == "DISPUTED"
    reopened = validate_success(api.finalize_assessment(ra["id"], OFFICER, {"reopen": True}))
    assert reopened["status"] == "ASSESSED"
