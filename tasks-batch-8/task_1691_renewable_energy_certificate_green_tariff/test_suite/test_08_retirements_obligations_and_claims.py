"""Retirements, compliance obligations, and annual claim reports: vintage and
geographic eligibility windows, immutable retirement evidence, obligation
coverage and true-up evaluation order, shortfall penalties, claim pinning and
bucket reconciliation, the double-count guard ordering, segregation of duties
on adjudication, and report lifecycle lockdowns."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    accept_claim_report,
    assert_claim_report,
    assert_obligation,
    assert_retirement,
    close_obligation,
    create_active_generator,
    create_claim_report,
    create_obligation,
    create_program,
    get_certificate,
    get_claim_report,
    get_obligation,
    get_program,
    get_retirement,
    list_certificates,
    list_retirements,
    make_auditor_headers,
    patch_obligation,
    reject_claim_report,
    retire_compliance,
    retire_voluntary,
    revise_claim_report,
    run_mint,
    set_clock,
    setup_minted_generator,
    submit_claim_report,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import create_accepted_reading as _accept_reading

ADMIN = TEST_USERS["registry_admin_headers"]
PM = TEST_USERS["program_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]

JULY = ("2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")


def _voluntary_setup(kwh=1000, claim_cap=10000, **program_overrides):
    """DRAFT VOLUNTARY program + one minted certificate (default 1 MWh,
    vintage 2026-07)."""
    program = create_program(annual_claim_cap_mwh=claim_cap, **program_overrides)
    setup = setup_minted_generator(
        readings=[{"period_start": JULY[0], "period_end": JULY[1], "metered_kwh": kwh}]
    )
    return program, setup


def _report_with_retirement(kwh=1000, claim_cap=10000, submitter="pm-1"):
    """Program + one retired certificate + one DRAFT report pinned to it."""
    program, setup = _voluntary_setup(kwh=kwh, claim_cap=claim_cap)
    cert = setup["certificates"][0]
    ret = retire_voluntary(cert["id"], program["id"])
    report = create_claim_report(
        scope="VOLUNTARY_PROGRAM", program_id=program["id"], report_year=2026
    )
    return program, cert, ret, report


# ---------------------------------------------------------------------------
# Vintage eligibility: closed month window (voluntary) and year window
# ---------------------------------------------------------------------------

def test_vintage_at_window_edge_eligible(api):
    """PRD §3.7: "the vintage rule is a closed month window: counting the
    months between the certificate's `vintage_month` and the logical clock's
    month — twelve times the year difference plus the month difference — the
    count must be at least zero and at most one less than the program's
    `vintage_window_months`; with the default twelve-month window, a
    certificate is eligible from its vintage month through the eleventh month
    that follows it".

    Design: Difficulty/resource_temporal_overlap/vintage_closed_month_window_eligibility
    """
    program = create_program(vintage_window_months=12)
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    set_clock("2025-09-05T00:00:00Z")
    _accept_reading(gen["id"], "2025-08-01T00:00:00Z", "2025-09-01T00:00:00Z", 1000)
    set_clock("2025-10-05T00:00:00Z")
    _accept_reading(gen["id"], "2025-09-01T00:00:00Z", "2025-10-01T00:00:00Z", 1000)
    run_mint(gen["id"])
    c_old = list_certificates(generator_id=gen["id"], vintage_month="2025-08")[0]
    c_edge = list_certificates(generator_id=gen["id"], vintage_month="2025-09")[0]

    set_clock("2026-08-15T00:00:00Z")  # clock month 2026-08
    # months_between(2026-08, 2025-09) == 11 == vintage_window_months - 1.
    ret = retire_voluntary(c_edge["id"], program["id"])
    assert_retirement(ret)
    assert ret["vintage_month"] == "2025-09"
    assert get_certificate(c_edge["id"])["status"] == "RETIRED"
    # The older 2025-08 certificate (12 months back) is left untouched here;
    # the paired test exercises its rejection.
    assert get_certificate(c_old["id"])["status"] == "ACTIVE"


def test_vintage_one_month_past_window_rejected(api):
    """PRD §3.7: "anything older is rejected with `ERR_VINTAGE_INELIGIBLE`" —
    at clock month 2026-08 with a 12-month window, vintage 2025-08 is 12
    months back, one month past the closed window.

    Design: Difficulty/resource_temporal_overlap/vintage_closed_month_window_eligibility
    """
    program = create_program(vintage_window_months=12)
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    set_clock("2025-09-05T00:00:00Z")
    _accept_reading(gen["id"], "2025-08-01T00:00:00Z", "2025-09-01T00:00:00Z", 1000)
    run_mint(gen["id"])
    c_old = list_certificates(generator_id=gen["id"], vintage_month="2025-08")[0]

    set_clock("2026-08-15T00:00:00Z")
    resp = api.create_retirement(
        {"certificate_id": c_old["id"], "purpose": "VOLUNTARY_PROGRAM",
         "program_id": program["id"]},
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_VINTAGE_INELIGIBLE, expected_status=422)
    assert get_certificate(c_old["id"])["status"] == "ACTIVE", (
        "an ineligible-vintage rejection leaves the certificate ACTIVE"
    )


def test_compliance_vintage_year_window(api):
    """PRD §3.7: "the vintage rule is a closed year window — the
    certificate's vintage year must be the obligation's `year` or one of the
    two years immediately preceding it, else `ERR_VINTAGE_INELIGIBLE`".

    Design: Corner/calculations/compliance_vintage_year_window
    """
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    set_clock("2023-12-10T00:00:00Z")
    _accept_reading(gen["id"], "2023-12-01T00:00:00Z", "2023-12-10T00:00:00Z", 1000)
    set_clock("2024-12-10T00:00:00Z")
    _accept_reading(gen["id"], "2024-12-01T00:00:00Z", "2024-12-10T00:00:00Z", 1000)
    run_mint(gen["id"])
    c23 = list_certificates(generator_id=gen["id"], vintage_month="2023-12")[0]
    c24 = list_certificates(generator_id=gen["id"], vintage_month="2024-12")[0]

    obligation = create_obligation(lse_name="LSE One", year=2026, region_code="CAISO",
                                   required_mwh=5)
    set_clock("2026-08-01T00:00:00Z")

    ret = retire_compliance(c24["id"], obligation["id"])
    assert_retirement(ret)
    assert ret["quantity_mwh"] == 1, "vintage 2024 == 2026 - 2: lower boundary inclusive"

    resp = api.create_retirement(
        {"certificate_id": c23["id"], "purpose": "COMPLIANCE",
         "obligation_id": obligation["id"]},
        CO,
    )
    validate_error(resp, ApiErrorId.ERR_VINTAGE_INELIGIBLE, expected_status=422)

    assert get_obligation(obligation["id"])["covered_mwh"] == 1, (
        "only the eligible retirement counts toward coverage"
    )


# ---------------------------------------------------------------------------
# Region and technology eligibility
# ---------------------------------------------------------------------------

def test_region_and_technology_ineligibility(api):
    """PRD §3.7: "The certificate's `region_code` must be a member of the
    program's `eligible_region_codes`, else `ERR_REGION_INELIGIBLE`, and its
    `technology` a member of `eligible_technologies`, else
    `ERR_TECHNOLOGY_INELIGIBLE`." and "the certificate's `region_code` must
    equal the obligation's `region_code` exactly, else
    `ERR_REGION_INELIGIBLE`."

    Design: Corner/validations/region_and_technology_ineligibility
    """
    program = create_program()  # CAISO / SOLAR only
    wind_ercot = setup_minted_generator(
        legal_name="West Wind", facility_code="WW1", technology="WIND",
        region_code="ERCOT",
    )["certificates"][0]
    wind_caiso = setup_minted_generator(
        legal_name="North Wind", facility_code="NW1", technology="WIND",
        region_code="CAISO",
    )["certificates"][0]
    obligation = create_obligation(lse_name="LSE West", year=2026, region_code="ERCOT",
                                   required_mwh=5)

    resp_region = api.create_retirement(
        {"certificate_id": wind_ercot["id"], "purpose": "VOLUNTARY_PROGRAM",
         "program_id": program["id"]},
        PM,
    )
    validate_error(resp_region, ApiErrorId.ERR_REGION_INELIGIBLE, expected_status=422)

    resp_tech = api.create_retirement(
        {"certificate_id": wind_caiso["id"], "purpose": "VOLUNTARY_PROGRAM",
         "program_id": program["id"]},
        PM,
    )
    validate_error(resp_tech, ApiErrorId.ERR_TECHNOLOGY_INELIGIBLE, expected_status=422)

    resp_comp = api.create_retirement(
        {"certificate_id": wind_caiso["id"], "purpose": "COMPLIANCE",
         "obligation_id": obligation["id"]},
        CO,
    )
    validate_error(resp_comp, ApiErrorId.ERR_REGION_INELIGIBLE, expected_status=422)

    assert get_certificate(wind_ercot["id"])["status"] == "ACTIVE"
    assert get_certificate(wind_caiso["id"])["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Retirement evidence rows
# ---------------------------------------------------------------------------

def test_retirement_immutable_event_entity(api):
    """PRD §2.5: "The `Retirement` resource is the deliberate exception:
    retirement rows are immutable once created and carry only `id` and
    `created_at`; both `updated_at` and `version` are absent, and no
    operation ever modifies a retirement row in place."
    PRD §3.7: "writes an immutable `Retirement` row that freezes the
    certificate's `quantity_mwh`, `vintage_month`, `region_code`, and
    `technology`, records the holder's `account_id` at retirement time, and
    starts with `claimed_in_report_id` unset."

    Design: Corner/entities/retirement_immutable_event_entity
    """
    program, setup = _voluntary_setup()
    cert = setup["certificates"][0]
    ret = retire_voluntary(cert["id"], program["id"])
    assert_retirement(ret)
    assert ret["quantity_mwh"] == 1
    assert ret["vintage_month"] == "2026-07"
    assert ret["region_code"] == "CAISO"
    assert ret["technology"] == "SOLAR"
    assert ret["account_id"] == setup["account"]["id"], (
        "the holder at retirement time is the generator's GENERATOR account"
    )
    assert ret["claimed_in_report_id"] is None

    fetched = get_retirement(ret["id"])
    assert_retirement(fetched)
    assert fetched["certificate_id"] == cert["id"]


# ---------------------------------------------------------------------------
# Obligation state gating of compliance retirements
# ---------------------------------------------------------------------------

def test_compliance_retirement_into_closed_obligation_rejected(api):
    """PRD §3.7: "For `COMPLIANCE`, the target obligation must be `OPEN`,
    else `ERR_OBLIGATION_NOT_OPEN`".
    PRD §3.8: "Closing an already closed obligation is rejected with
    `ERR_OBLIGATION_NOT_OPEN`, and both `CLOSED_MET` and `CLOSED_SHORTFALL`
    are terminal."

    Design: Difficulty/cross_entity_state_dependency/retirement_requires_open_obligation
    """
    obligation = create_obligation(lse_name="LSE One", year=2026, region_code="CAISO",
                                   required_mwh=5)
    closed = close_obligation(obligation["id"])
    assert closed["status"] == "CLOSED_SHORTFALL"  # zero coverage

    cert = setup_minted_generator()["certificates"][0]
    resp = api.create_retirement(
        {"certificate_id": cert["id"], "purpose": "COMPLIANCE",
         "obligation_id": obligation["id"]},
        CO,
    )
    validate_error(resp, ApiErrorId.ERR_OBLIGATION_NOT_OPEN, expected_status=409)
    assert get_certificate(cert["id"])["status"] == "ACTIVE", (
        "the certificate is untouched by the rejected retirement"
    )


def test_compliance_retirement_into_met_obligation_rejected(api):
    """PRD §3.8: "Compliance retirements are accepted only while the
    obligation is `OPEN`, so once an obligation has flipped to `MET`,
    further compliance retirements against it are rejected with
    `ERR_OBLIGATION_NOT_OPEN` unless a true-up amendment reopens it."

    Design: Difficulty/cross_entity_state_dependency/retirement_requires_open_obligation
    """
    obligation = create_obligation(lse_name="LSE One", year=2026, region_code="CAISO",
                                   required_mwh=1)
    setup = setup_minted_generator(
        readings=[
            {"period_start": JULY[0], "period_end": JULY[1], "metered_kwh": 1000},
            {"period_start": "2026-08-01T00:00:00Z",
             "period_end": "2026-08-15T00:00:00Z", "metered_kwh": 1000,
             "clock": "2026-09-01T00:00:00Z"},
        ]
    )
    certs = setup["certificates"]
    assert len(certs) == 2

    retire_compliance(certs[0]["id"], obligation["id"])
    met = get_obligation(obligation["id"])
    assert met["status"] == "MET", "coverage 1 == required 1 flips the obligation to MET"
    assert met["covered_mwh"] == 1

    resp = api.create_retirement(
        {"certificate_id": certs[1]["id"], "purpose": "COMPLIANCE",
         "obligation_id": obligation["id"]},
        CO,
    )
    validate_error(resp, ApiErrorId.ERR_OBLIGATION_NOT_OPEN, expected_status=409)
    assert get_certificate(certs[1]["id"])["status"] == "ACTIVE"


def test_existence_beats_state_on_retire(api):
    """PRD §2.8: "Every write request traverses a fixed validation pipeline.
    A failure at any stage short-circuits the rest, so the error a client
    sees is always the earliest applicable one." — stage "4. Existence"
    precedes stage "6. State-machine admissibility".

    Design: Difficulty/priority_pair_validation_conflict/existence_vs_state_on_retire
    """
    obligation = create_obligation(lse_name="LSE One", year=2026, region_code="CAISO",
                                   required_mwh=5)
    close_obligation(obligation["id"])  # CLOSED_SHORTFALL with zero coverage

    resp = api.create_retirement(
        {"certificate_id": NON_EXISTENT_UUID, "purpose": "COMPLIANCE",
         "obligation_id": obligation["id"]},
        CO,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_existence_error_leaves_no_retirement_trace(api):
    """PRD §2.8: "Existence — path identifiers are resolved first, validated
    left to right, and only then are the foreign keys referenced in the
    request body ... resolved (`ERR_NOT_FOUND`)" — the rejected request
    records nothing against the (closed) obligation.

    Design: Difficulty/priority_pair_validation_conflict/existence_vs_state_on_retire
    """
    obligation = create_obligation(lse_name="LSE One", year=2026, region_code="CAISO",
                                   required_mwh=5)
    closed = close_obligation(obligation["id"])
    assert closed["status"] == "CLOSED_SHORTFALL"

    resp = api.create_retirement(
        {"certificate_id": NON_EXISTENT_UUID, "purpose": "COMPLIANCE",
         "obligation_id": obligation["id"]},
        CO,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    rows = list_retirements(obligation_id=obligation["id"])
    assert rows == [], "no retirement row is created by the 404 request"
    after = get_obligation(obligation["id"])
    assert after["status"] == "CLOSED_SHORTFALL"
    assert after["covered_mwh"] == 0


# ---------------------------------------------------------------------------
# Obligation coverage, true-up evaluation order, and shortfall penalty
# ---------------------------------------------------------------------------

def _obligation_with_500_coverage():
    """Obligation (required 500, rate 5000) driven to MET by a 500-MWh
    compliance retirement."""
    setup = setup_minted_generator(
        readings=[{"period_start": JULY[0], "period_end": JULY[1], "metered_kwh": 500000}]
    )
    cert = setup["certificates"][0]
    assert cert["quantity_mwh"] == 500
    obligation = create_obligation(lse_name="LSE One", year=2026, region_code="CAISO",
                                   required_mwh=500, penalty_rate_cents_per_mwh=5000)
    retire_compliance(cert["id"], obligation["id"])
    return obligation, cert


def test_trueup_amendment_above_coverage_flips_met_back_to_open(api):
    """PRD §3.7: "if coverage has reached or exceeded `required_mwh` — exact
    equality counts — the obligation flips from `OPEN` to `MET` in the same
    atomic mutation".
    PRD §3.8: "Its evaluation order is pinned: first coverage is frozen from
    the retirements already recorded, then the amendment is applied, then the
    obligation's state is re-derived — `MET` if coverage reaches the new
    requirement, otherwise `OPEN` — and only then is the result persisted."

    Design: Difficulty/combinatorial_formula/obligation_trueup_evaluation_order
    """
    obligation, _ = _obligation_with_500_coverage()
    met = get_obligation(obligation["id"])
    assert met["status"] == "MET", "covered 500 == required 500: exact equality counts"
    assert met["covered_mwh"] == 500

    amended = patch_obligation(obligation["id"], required_mwh=620)
    assert amended["status"] == "OPEN", (
        "amending the requirement above frozen coverage re-derives OPEN in the "
        "same write"
    )
    assert amended["covered_mwh"] == 500, "coverage is frozen before the amendment"
    assert amended["required_mwh"] == 620


def test_close_after_trueup_computes_shortfall_penalty(api):
    """PRD §3.8: "When coverage falls short, it closes as `CLOSED_SHORTFALL`
    and the penalty is exact integer arithmetic: the deficit in megawatt-hours
    — `required_mwh` minus `covered_mwh` — multiplied by the obligation's
    `penalty_rate_cents_per_mwh`, stored in `penalty_cents`."

    Design: Difficulty/combinatorial_formula/obligation_trueup_evaluation_order
    """
    obligation, _ = _obligation_with_500_coverage()
    patch_obligation(obligation["id"], required_mwh=620)
    assert get_obligation(obligation["id"])["status"] == "OPEN"

    closed = close_obligation(obligation["id"])
    assert_obligation(closed)
    assert closed["status"] == "CLOSED_SHORTFALL"
    assert closed["penalty_cents"] == 600000, "(620 - 500) * 5000"


def test_occ_obligation_patch_stale_version(api):
    """PRD §2.7: "Amending a compliance obligation requires
    `expected_obligation_version`, matched against that obligation's current
    `version`."
    PRD §2.5: "When a single request mutates several resources ... every
    touched resource refreshes its own `updated_at` and increments its own
    `version` by one" — the coverage write from a retirement therefore
    invalidates a pre-retirement observed version.

    Design: Corner/cross_cutting_complexity_layers/occ_obligation_patch_stale_version
    """
    obligation = create_obligation(lse_name="LSE One", year=2026, region_code="CAISO",
                                   required_mwh=500)
    observed = obligation["version"]

    cert = setup_minted_generator()["certificates"][0]
    retire_compliance(cert["id"], obligation["id"])
    bumped = get_obligation(obligation["id"])
    assert bumped["covered_mwh"] == 1
    assert bumped["version"] > observed, "the retirement's coverage write bumps the version"

    stale = api.patch_obligation(
        obligation["id"],
        {"expected_obligation_version": observed, "required_mwh": 620},
        CO,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    fresh = patch_obligation(obligation["id"], required_mwh=620)
    assert fresh["required_mwh"] == 620


# ---------------------------------------------------------------------------
# Claim report pinning, reconciliation, and the revision cycle
# ---------------------------------------------------------------------------

def test_claim_report_bucket_reconciliation(api):
    """PRD §3.9: "From that pinned set the report derives `total_mwh` as the
    summed `quantity_mwh`, plus two bucket maps: `totals_by_technology`
    summing `quantity_mwh` per technology and `totals_by_region` summing it
    per `region_code`. A reconciliation invariant holds at all times: the
    bucket values of each map must sum exactly to `total_mwh`."

    Design: Corner/calculations/claim_report_bucket_reconciliation
    """
    program = create_program(
        eligible_region_codes=["CAISO", "ERCOT"],
        eligible_technologies=["SOLAR", "WIND"],
    )
    solar = setup_minted_generator(
        readings=[{"period_start": JULY[0], "period_end": JULY[1], "metered_kwh": 2000}],
        legal_name="Sierra Solar", facility_code="SS1", technology="SOLAR",
        region_code="CAISO",
    )["certificates"][0]
    wind = setup_minted_generator(
        readings=[{"period_start": JULY[0], "period_end": JULY[1], "metered_kwh": 3000}],
        legal_name="West Wind", facility_code="WW1", technology="WIND",
        region_code="ERCOT",
    )["certificates"][0]
    retire_voluntary(solar["id"], program["id"])
    retire_voluntary(wind["id"], program["id"])

    report = create_claim_report(
        scope="VOLUNTARY_PROGRAM", program_id=program["id"], report_year=2026
    )
    assert_claim_report(report)
    assert report["total_mwh"] == 5
    assert report["totals_by_technology"] == {"SOLAR": 2, "WIND": 3}
    assert report["totals_by_region"] == {"CAISO": 2, "ERCOT": 3}
    assert len(report["retirement_ids"]) == 2


def test_rejected_report_revises_back_to_draft_and_repins(api):
    """PRD §3.9: "Revising a `REJECTED` report returns it to `DRAFT` under
    the same scope-role match as submission, recomputes the pinned
    `retirement_ids` from scratch — dropping retirements claimed elsewhere
    since and picking up newly eligible ones — recomputes the totals, and
    clears both `rejection_reason` and `submitted_by_user_id`".

    Design: Difficulty/non_linear_state_machine/claim_report_revision_cycle
    """
    program, cert, ret, report = _report_with_retirement(kwh=2000)
    submitted = submit_claim_report(report["id"], user_id="pm-1")
    assert submitted["status"] == "SUBMITTED"

    rejected = reject_claim_report(report["id"], auditor_id="aud-1",
                                   reason="incomplete evidence")
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "incomplete evidence"

    revised = revise_claim_report(report["id"])
    assert revised["status"] == "DRAFT", "rejection returns the report to DRAFT"
    assert ret["id"] in revised["retirement_ids"], (
        "the still-unclaimed retirement re-pins on revise"
    )
    assert revised["rejection_reason"] is None
    assert revised["submitted_by_user_id"] is None
    assert revised["total_mwh"] == 2

    resubmitted = submit_claim_report(report["id"], user_id="pm-1")
    assert resubmitted["status"] == "SUBMITTED", "the cycle loops back to SUBMITTED"


def test_accepted_report_marks_retirements_claimed(api):
    """PRD §3.9: "Accepting moves the report from `SUBMITTED` to the terminal
    `ACCEPTED` state and stamps every pinned retirement's
    `claimed_in_report_id` with this report's id — the moment that locks
    those retirements out of any future claim."

    Design: Difficulty/non_linear_state_machine/claim_report_revision_cycle
    """
    program, cert, ret, report = _report_with_retirement(kwh=2000)
    submit_claim_report(report["id"], user_id="pm-1")
    reject_claim_report(report["id"], auditor_id="aud-1")
    revise_claim_report(report["id"])
    submit_claim_report(report["id"], user_id="pm-1")

    accepted = accept_claim_report(report["id"], auditor_id="aud-1")
    assert accepted["status"] == "ACCEPTED"
    assert accepted["total_mwh"] == 2

    ret_after = get_retirement(ret["id"])
    assert ret_after["claimed_in_report_id"] == report["id"], (
        "acceptance stamps the pinned retirement with the report id"
    )


def test_claim_report_accepted_terminal_lockdown(api):
    """PRD §3.9: "a submission, acceptance, rejection, or revision attempted
    from a state the transition does not allow is rejected with
    `ERR_REPORT_STATE_INVALID`" and accepting moves the report "to the
    terminal `ACCEPTED` state".

    Design: Corner/state_machines/claim_report_accepted_terminal_lockdown
    """
    program, cert, ret, report = _report_with_retirement()
    submit_claim_report(report["id"], user_id="pm-1")
    accept_claim_report(report["id"], auditor_id="aud-1")

    resp_submit = api.submit_claim_report(
        report["id"], TEST_USERS["program_manager_headers"]
    )
    validate_error(resp_submit, ApiErrorId.ERR_REPORT_STATE_INVALID, expected_status=409)

    resp_revise = api.revise_claim_report(
        report["id"], TEST_USERS["program_manager_headers"]
    )
    validate_error(resp_revise, ApiErrorId.ERR_REPORT_STATE_INVALID, expected_status=409)

    resp_accept = api.accept_claim_report(report["id"], make_auditor_headers("aud-9"))
    validate_error(resp_accept, ApiErrorId.ERR_REPORT_STATE_INVALID, expected_status=409)

    assert get_claim_report(report["id"])["status"] == "ACCEPTED"


# ---------------------------------------------------------------------------
# Report submission guards: empty, cap, duplicate, double-count ordering
# ---------------------------------------------------------------------------

def test_claim_report_empty_submit_rejected(api):
    """PRD §3.9: "then the pinned set must be non-empty, else
    `ERR_REPORT_EMPTY`".

    Design: Corner/validations/claim_report_empty_submit_rejected
    """
    program = create_program()
    report = create_claim_report(
        scope="VOLUNTARY_PROGRAM", program_id=program["id"], report_year=2026
    )
    assert report["retirement_ids"] == []
    assert report["total_mwh"] == 0

    resp = api.submit_claim_report(
        report["id"], TEST_USERS["program_manager_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_REPORT_EMPTY, expected_status=422)
    assert get_claim_report(report["id"])["status"] == "DRAFT"


def test_claim_cap_exceeded_pure_fiscal(api):
    """PRD §3.9: "finally, for the `VOLUNTARY_PROGRAM` scope, the recomputed
    `total_mwh` may not exceed the program's `annual_claim_cap_mwh`, else
    `ERR_CLAIM_CAP_EXCEEDED`".

    Design: Corner/validations/claim_cap_exceeded_pure_fiscal
    """
    program, cert, ret, report = _report_with_retirement(kwh=5000, claim_cap=3)
    assert report["total_mwh"] == 5

    resp = api.submit_claim_report(
        report["id"], TEST_USERS["program_manager_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_CAP_EXCEEDED, expected_status=422)
    assert get_claim_report(report["id"])["status"] == "DRAFT"


def test_duplicate_report_after_acceptance_rejected(api):
    """PRD §3.9: "creation is refused with `ERR_DUPLICATE_REPORT` when an
    `ACCEPTED` report already exists for the same scope target and
    `report_year`."

    Design: Corner/validations/duplicate_report_after_acceptance_rejected
    """
    program, cert, ret, report = _report_with_retirement()
    submit_claim_report(report["id"], user_id="pm-1")
    accept_claim_report(report["id"], auditor_id="aud-1")

    resp = api.create_claim_report(
        {"scope": "VOLUNTARY_PROGRAM", "program_id": program["id"], "report_year": 2026},
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORT, expected_status=409)


def _double_count_setup():
    """Program claim cap 3; certificates A (3 MWh, 2026-07) and B (2 MWh,
    2026-08) retired as retA/retB; R1 pins [retA] and is SUBMITTED; R2 pins
    [retA, retB] while retA is still unclaimed; then R1 is ACCEPTED (claiming
    retA)."""
    program = create_program(annual_claim_cap_mwh=3)
    gen = create_active_generator(legal_name="Sierra Solar", facility_code="SS1")
    _accept_reading(gen["id"], JULY[0], JULY[1], 3000)
    run_mint(gen["id"])
    ca = list_certificates(generator_id=gen["id"], vintage_month="2026-07")[0]
    reta = retire_voluntary(ca["id"], program["id"])

    rep1 = create_claim_report(scope="VOLUNTARY_PROGRAM", program_id=program["id"],
                               report_year=2026)
    submit_claim_report(rep1["id"], user_id="pm-1")

    set_clock("2026-09-01T00:00:00Z")
    _accept_reading(gen["id"], "2026-08-01T00:00:00Z", "2026-08-15T00:00:00Z", 2000)
    run_mint(gen["id"])
    cb = list_certificates(generator_id=gen["id"], vintage_month="2026-08")[0]
    retb = retire_voluntary(cb["id"], program["id"])

    rep2 = create_claim_report(scope="VOLUNTARY_PROGRAM", program_id=program["id"],
                               report_year=2026)
    accept_claim_report(rep1["id"], auditor_id="aud-1")
    return program, reta, retb, rep1, rep2


def test_double_count_beats_claim_cap_on_submit(api):
    """PRD §2.8: "And a claim report submission runs its double-count guard
    before the empty-report and claim-cap checks — safety before fiscal."
    PRD §3.9: "the double-count guard — no pinned retirement may carry a
    `claimed_in_report_id` set by another `ACCEPTED` report, else
    `ERR_DOUBLE_COUNT`".

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_fiscal_on_report_submit
    """
    program, reta, retb, rep1, rep2 = _double_count_setup()
    pinned = get_claim_report(rep2["id"])
    assert set(pinned["retirement_ids"]) == {reta["id"], retb["id"]}, (
        "R2 pinned both retirements while retA was still unclaimed"
    )
    assert pinned["total_mwh"] == 5

    resp = api.submit_claim_report(
        rep2["id"], TEST_USERS["program_manager_headers"]
    )
    # Double-count (retA now claimed by ACCEPTED R1) wins even though
    # total 5 > annual_claim_cap_mwh 3 also holds.
    validate_error(resp, ApiErrorId.ERR_DOUBLE_COUNT, expected_status=422)


def test_double_count_rejection_leaves_report_and_claims_untouched(api):
    """PRD §3.9: "no pinned retirement may carry a `claimed_in_report_id` set
    by another `ACCEPTED` report, else `ERR_DOUBLE_COUNT`" — the rejected
    submission leaves the report in DRAFT and stamps nothing on its other
    pinned retirement.

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_fiscal_on_report_submit
    """
    program, reta, retb, rep1, rep2 = _double_count_setup()
    resp = api.submit_claim_report(
        rep2["id"], TEST_USERS["program_manager_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_DOUBLE_COUNT, expected_status=422)

    assert get_claim_report(rep2["id"])["status"] == "DRAFT"
    assert get_retirement(reta["id"])["claimed_in_report_id"] == rep1["id"]
    assert get_retirement(retb["id"])["claimed_in_report_id"] is None, (
        "retB remains unclaimed and re-pinnable"
    )


# ---------------------------------------------------------------------------
# Segregation of duties on adjudication; purpose-role match on retirements
# ---------------------------------------------------------------------------

def test_self_approval_rejected(api):
    """PRD §3.9: "Either decision by the same user who submitted the report
    is rejected with `ERR_SELF_APPROVAL`."
    PRD §2.1: "`Auditor` — independent claims auditor who may never decide a
    report submitted by the same user."

    Design: Corner/rbac/self_approval_rejected
    """
    program, cert, ret, report = _report_with_retirement()
    submit_claim_report(report["id"], user_id="pm-1")

    resp = api.accept_claim_report(report["id"], make_auditor_headers("pm-1"))
    validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL, expected_status=403)

    accepted = accept_claim_report(report["id"], auditor_id="aud-9")
    assert accepted["status"] == "ACCEPTED", "a different auditor decides fine"


def test_compliance_officer_cannot_retire_voluntary(api):
    """PRD §2.1: "`VOLUNTARY_PROGRAM` retirements are `ProgramManager`-only,
    `COMPLIANCE` retirements are `ComplianceOfficer`-only, and
    `WHOLESALE_CLAIM` retirements are `BrokerTrader`-only with the ownership
    match above."
    PRD §3.7: "The role must match the purpose per §2.1".

    Design: Corner/rbac/compliance_officer_cannot_retire_voluntary
    """
    program, setup = _voluntary_setup()
    cert = setup["certificates"][0]

    resp = api.create_retirement(
        {"certificate_id": cert["id"], "purpose": "VOLUNTARY_PROGRAM",
         "program_id": program["id"]},
        CO,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
    assert get_certificate(cert["id"])["status"] == "ACTIVE"
