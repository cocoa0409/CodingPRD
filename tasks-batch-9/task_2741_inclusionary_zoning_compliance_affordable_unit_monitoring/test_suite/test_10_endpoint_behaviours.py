"""Endpoint-level behaviours: what each declared endpoint returns in one call.

Every test builds its own preconditions from declared endpoints only, because the
database is empty and the logical clock reads its startup default at the first
line of every test.
"""

from test_helpers import (
    ApiClient,
    assert_fund_money_conserved,
    assert_money_cents,
    assert_project_state,
    assert_unit_dimensions,
    assert_waterfall_conserved,
    factories,
    fixtures,
    get_success_data,
    make_resident_headers,
    same_instant,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    AMI_2026_MEDIAN_INCOME_CENTS_BY_SIZE,
    CLOCK_STARTUP_DEFAULT,
    INCOME_LIMIT_SIZE_2_AT_5000_BPS,
    MAX_ALLOWED_RENT_2BR_AT_5000_BPS,
)

# The R-2 development every instance below screens: 20 units at a 1000 bps
# set-aside is exactly two whole affordable units and no residual fraction.
TWENTY_UNIT_R2 = {
    "name": "Amend Alley",
    "zoning_district": "R-2",
    "total_units": 20,
    "approval_date": "2026-01-15",
}

# A two-bedroom ownership unit that clears the comparability floor.
OWNERSHIP_2BR = {
    "bedrooms": 2,
    "sqft": 900,
    "market_comparable_sqft": 1000,
    "tenure": "OWNERSHIP",
    "affordability_level_bps": 5000,
}

# The 2026 median for household size 3, which is a two-bedroom unit's
# bedrooms-plus-one household size.
MEDIAN_SIZE_3 = AMI_2026_MEDIAN_INCOME_CENTS_BY_SIZE["3"]


# =============================================================================
# PATCH /iz-compliance/projects/{project_id}
# =============================================================================
def test_amending_a_screened_project_reverts_it_to_draft_and_clears_every_output(
    api: ApiClient, developer: dict
) -> None:
    """A partial update re-opens screening and zeroes every derived output at once.

    PRD: "In every case the screening outputs are cleared: `applicability` returns to `PENDING`, `required_affordable_units`, `fractional_obligation_bps` and `total_obligation_bps` return to 0, `compliance_path` and `ordinance_id` are cleared to null, `compliance_posture` returns to `PENDING`, and the project's `version` increments — including on the self-transition, where the clears are no-ops on a project that was never screened but the version bump still happens, which is exactly what a subsequent re-screen depends on."

    Design: Corner/endpoints/patching_a_screened_project_reverts_it_to_draft_and_clears_the_outputs
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    program = fixtures.bootstrap_program()
    project = fixtures.register_project(**TWENTY_UNIT_R2)
    screened = fixtures.screen_project(project["id"])
    assert_project_state(screened, state="SCREENED_SUBJECT", applicability="SUBJECT")
    assert screened["required_affordable_units"] == 2
    assert screened["total_obligation_bps"] == 20000
    assert screened["ordinance_id"] == program["ordinance"]["id"]
    elected = fixtures.elect_path(project["id"], "ONSITE")
    assert elected["compliance_path"] == "ONSITE"

    amended = get_success_data(
        api.patch_project(project["id"], {"total_units": 40}, headers=developer)
    )

    assert amended["total_units"] == 40
    assert_project_state(
        amended, state="DRAFT", applicability="PENDING", compliance_posture="PENDING"
    )
    assert amended["ordinance_id"] is None
    assert amended["compliance_path"] is None
    assert amended["required_affordable_units"] == 0
    assert amended["fractional_obligation_bps"] == 0
    assert amended["total_obligation_bps"] == 0
    # The fields the payload omitted keep their stored values.
    assert amended["name"] == "Amend Alley"
    assert amended["zoning_district"] == "R-2"
    assert amended["approval_date"] == "2026-01-15"
    assert amended["version"] == elected["version"] + 1


def test_re_screening_after_the_amendment_recomputes_the_obligation(
    api: ApiClient, developer: dict, compliance_officer: dict
) -> None:
    """The second screening sizes the obligation from the amended unit count.

    PRD: "On the subject branch the raw obligation, in basis points of one dwelling, is the project's `total_units` multiplied by the district's set-aside rate in basis points."

    Design: Corner/endpoints/patching_a_screened_project_reverts_it_to_draft_and_clears_the_outputs
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    program = fixtures.bootstrap_program()
    project = fixtures.register_project(**TWENTY_UNIT_R2)
    first = fixtures.screen_project(project["id"])
    assert first["screen_count"] == 1
    fixtures.elect_path(project["id"], "ONSITE")
    get_success_data(api.patch_project(project["id"], {"total_units": 40}, headers=developer))

    rescreened = get_success_data(api.screen_project(project["id"], headers=compliance_officer))

    # The amendment does not reset screen_count, which is how the re-screen shows.
    assert rescreened["screen_count"] == 2
    assert_project_state(rescreened, state="SCREENED_SUBJECT", applicability="SUBJECT")
    assert rescreened["required_affordable_units"] == 4
    assert rescreened["fractional_obligation_bps"] == 0
    assert rescreened["total_obligation_bps"] == 40000
    assert rescreened["ordinance_id"] == program["ordinance"]["id"]


# =============================================================================
# POST /iz-compliance/affordable-units/{unit_id}/record-restriction
# =============================================================================
def _ownership_unit_ready_for_restriction() -> dict:
    """An ONSITE project carrying one unrestricted OWNERSHIP two-bedroom unit."""
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    unit_overrides = dict(OWNERSHIP_2BR)
    unit_overrides["unit_number"] = "FZ-101"
    return fixtures.project_with_unit(
        unit_overrides=unit_overrides,
        project_overrides=dict(TWENTY_UNIT_R2, name="Freeze Point"),
    )


def test_recording_the_restriction_freezes_the_price_and_the_ami_basis(
    api: ApiClient, compliance_officer: dict
) -> None:
    """Recording stores the paid price and freezes the bedrooms-plus-one median.

    PRD: "Recording moves the unit `NOT_RECORDED → RECORDED` on the restriction dimension, stores `restriction_recorded_at` and `original_purchase_price_cents`, and freezes `ami_income_at_purchase_cents` from the active schedule's `median_income_cents_by_size` entry for the unit's `bedrooms` plus one."

    Design: Corner/endpoints/recording_a_restriction_freezes_the_ami_basis_against_later_schedules
    """
    ctx = _ownership_unit_ready_for_restriction()
    before = ctx["unit"]
    assert_unit_dimensions(before, restriction_state="NOT_RECORDED")

    response = api.record_restriction(
        before["id"],
        original_purchase_price_cents=32500000,
        recorded_at="2026-08-01",
        headers=compliance_officer,
    )

    # The action works on an existing row, so it answers 200 rather than 201.
    recorded = validate_success(response, expected_status=200)
    assert_unit_dimensions(recorded, restriction_state="RECORDED")
    assert str(recorded["restriction_recorded_at"]).startswith("2026-08-01")
    assert_money_cents(recorded["original_purchase_price_cents"], "original_purchase_price_cents")
    assert recorded["original_purchase_price_cents"] == 32500000
    # bedrooms 2 plus 1 is household size 3, not the size-2 or size-4 median.
    assert recorded["ami_income_at_purchase_cents"] == MEDIAN_SIZE_3 == 12669800
    assert recorded["ami_income_at_purchase_cents"] != AMI_2026_MEDIAN_INCOME_CENTS_BY_SIZE["2"]
    assert recorded["ami_income_at_purchase_cents"] != AMI_2026_MEDIAN_INCOME_CENTS_BY_SIZE["4"]
    assert recorded["version"] == before["version"] + 1


def test_a_later_ami_schedule_does_not_disturb_the_frozen_basis(api: ApiClient, fund_auditor: dict) -> None:
    """Publishing the 2028 schedule touches schedule rows only, not the frozen unit.

    PRD: "A new schedule's `status` is `ACTIVE`, and publishing it transitions every `ACTIVE` schedule with a strictly earlier `effective_year` from `ACTIVE` to `SUPERSEDED`, each bumping its own `version`."

    Design: Corner/endpoints/recording_a_restriction_freezes_the_ami_basis_against_later_schedules
    """
    ctx = _ownership_unit_ready_for_restriction()
    restricted = fixtures.record_restriction(
        ctx["unit"]["id"], original_purchase_price_cents=32500000, recorded_at="2026-08-01"
    )
    assert restricted["ami_income_at_purchase_cents"] == 12669800

    later = fixtures.publish_later_ami_schedule()
    assert later["effective_year"] == 2028

    reread = get_success_data(api.get_unit(ctx["unit"]["id"], headers=fund_auditor))
    assert reread["ami_income_at_purchase_cents"] == 12669800
    assert reread["original_purchase_price_cents"] == 32500000
    assert reread["version"] == restricted["version"]


# =============================================================================
# POST /_clock/set_current_utc
# =============================================================================
def _three_due_rows(api: ApiClient) -> dict:
    """One lapsing tenancy, one unpaid assessment and one open ROFR window.

    The three rows live in three unrelated tables of three different projects, so
    a single clock advance has to reach all of them.
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    fixtures.bootstrap_program()

    # Project A: a RENTAL tenancy certified on 2026-08-01, so its term lapses
    # 365 days later on 2027-08-01.
    project_a = fixtures.register_project(**dict(TWENTY_UNIT_R2, name="Sweep A"))
    fixtures.screen_project(project_a["id"])
    fixtures.elect_path(project_a["id"], "ONSITE")
    agreement_a = fixtures.draft_agreement(project_a["id"])
    fixtures.record_agreement(
        agreement_a["id"], doc_number="DOC-CS-0001", recorded_at="2026-08-01"
    )
    unit_a = fixtures.add_unit(
        project_a["id"],
        agreement_a["id"],
        unit_number="CS-101",
        bedrooms=2,
        sqft=900,
        market_comparable_sqft=1000,
        tenure="RENTAL",
        affordability_level_bps=5000,
    )
    household_1 = fixtures.register_household(
        applicant_name="Hana Iyer", household_size=3, gross_annual_income_cents=6000000
    )
    certification_1 = fixtures.certify_income(
        household_1["id"],
        unit_a["id"],
        certified_income_cents=6000000,
        contract_rent_cents=140000,
        effective_date="2026-08-01",
    )

    # Project B: a FULL assessment of the whole 20000 bps obligation, due
    # 2026-08-01 plus 45 days, left entirely unpaid.
    project_b = fixtures.register_project(**dict(TWENTY_UNIT_R2, name="Sweep B"))
    fixtures.screen_project(project_b["id"])
    fixtures.elect_path(project_b["id"], "IN_LIEU_FEE")
    fee = fixtures.assess_fee(project_b["id"], basis="FULL")

    # Project C: an OWNERSHIP unit whose resale price was approved on
    # 2026-08-01, so its ROFR window closes on 2026-08-31.
    project_c = fixtures.register_project(**dict(TWENTY_UNIT_R2, name="Sweep C"))
    fixtures.screen_project(project_c["id"])
    fixtures.elect_path(project_c["id"], "ONSITE")
    agreement_c = fixtures.draft_agreement(project_c["id"])
    fixtures.record_agreement(
        agreement_c["id"], doc_number="DOC-CS-0002", recorded_at="2026-08-01"
    )
    unit_c = fixtures.add_unit(
        project_c["id"],
        agreement_c["id"],
        unit_number="CS-201",
        **dict(OWNERSHIP_2BR),
    )
    fixtures.record_restriction(
        unit_c["id"], original_purchase_price_cents=32500000, recorded_at="2026-08-01"
    )
    household_2 = fixtures.register_household(
        applicant_name="Jonas Wolf", household_size=3, gross_annual_income_cents=6000000
    )
    certification_2 = fixtures.certify_income(
        household_2["id"],
        unit_c["id"],
        certified_income_cents=6000000,
        contract_rent_cents=0,
        effective_date="2026-08-01",
    )
    live_c = fixtures.live_unit(unit_c["id"])
    resale = get_success_data(
        api.create_resale(
            factories.create_resale_payload(
                live_c["id"],
                live_c["version"],
                proposed_price_cents=32000000,
                appraised_value_cents=41000000,
                capital_improvements_cents=0,
                deferred_maintenance_cents=0,
                broker_fee_cents=1000000,
            ),
            headers=fixtures.HCO,
        )
    )
    resale = get_success_data(api.approve_resale_price(resale["id"], headers=fixtures.HCO))

    return {
        "unit_a": unit_a,
        "certification_1": certification_1,
        "fee": fee,
        "certification_2": certification_2,
        "resale": resale,
    }


def test_one_clock_call_sweeps_three_tables_and_reports_three_counts(
    api: ApiClient, program_admin: dict, compliance_officer: dict
) -> None:
    """A single clock advance expires, marks delinquent and auto-waives in one call.

    PRD: "The response to a clock advance reports the new `current_utc` together with three counters: `certifications_expired`, `fees_marked_delinquent`, and `rofr_windows_auto_waived`."

    Design: Corner/endpoints/the_clock_endpoint_sweeps_every_due_row_in_one_call_and_reports_counts
    """
    ctx = _three_due_rows(api)
    assert ctx["fee"]["assessed_amount_cents"] == 48934800
    assert ctx["fee"]["due_date"] == "2026-09-15"
    assert ctx["resale"]["state"] == "PRICE_APPROVED"

    swept = validate_success(
        api.set_clock("2027-09-16T00:00:00Z", headers=program_admin), expected_status=200
    )

    assert same_instant(swept["current_utc"], "2027-09-16T00:00:00Z")
    assert swept["certifications_expired"] == 1
    assert swept["fees_marked_delinquent"] == 1
    assert swept["rofr_windows_auto_waived"] == 1

    # Step 2: the rental certification expired and vacated its unit.
    expired = get_success_data(
        api.get_certification(ctx["certification_1"]["id"], headers=compliance_officer)
    )
    assert expired["state"] == "EXPIRED"
    vacated = fixtures.live_unit(ctx["unit_a"]["id"])
    assert_unit_dimensions(vacated, occupancy_status="VACANT", compliance_status="COMPLIANT")
    assert vacated["occupant_household_id"] is None
    assert vacated["current_rent_cents"] == 0

    # An OWNERSHIP certification has no term, so it is invisible to step 2.
    ownership_certification = get_success_data(
        api.get_certification(ctx["certification_2"]["id"], headers=compliance_officer)
    )
    assert ownership_certification["expires_at"] is None
    assert ownership_certification["state"] == "CERTIFIED"

    # Step 3: the unpaid assessment turned delinquent without being re-priced.
    delinquent = get_success_data(api.get_in_lieu_fee(ctx["fee"]["id"], headers=program_admin))
    assert delinquent["state"] == "DELINQUENT"
    assert delinquent["assessed_amount_cents"] == 48934800
    assert delinquent["paid_amount_cents"] == 0

    # Step 4: the ROFR window closed by itself once its day had elapsed.
    waived = get_success_data(api.get_resale(ctx["resale"]["id"], headers=compliance_officer))
    assert waived["state"] == "ROFR_WAIVED"
    assert waived["rofr_auto_waived"] is True
    assert waived["proposed_price_cents"] == 32000000


def test_a_second_clock_call_reports_zero_counts_and_moves_no_version(
    api: ApiClient, program_admin: dict, compliance_officer: dict
) -> None:
    """Re-observing the clock cannot penalise a row the first sweep already moved.

    PRD: "Every `IncomeCertification` still in state `CERTIFIED` whose `expires_at` is now strictly in the past transitions to `EXPIRED`, and each such expiry vacates its unit: the unit's `occupancy_status` moves from `OCCUPIED` to `VACANT`, its `current_rent_cents` is reset to 0, its `occupant_household_id` is cleared to null, and the owning project's `compliance_posture` is recomputed."

    Design: Corner/endpoints/the_clock_endpoint_sweeps_every_due_row_in_one_call_and_reports_counts
    """
    ctx = _three_due_rows(api)
    fixtures.set_clock("2027-09-16T00:00:00Z")
    certification_after_first = get_success_data(
        api.get_certification(ctx["certification_1"]["id"], headers=compliance_officer)
    )
    fee_after_first = get_success_data(api.get_in_lieu_fee(ctx["fee"]["id"], headers=program_admin))
    resale_after_first = get_success_data(
        api.get_resale(ctx["resale"]["id"], headers=compliance_officer)
    )

    again = validate_success(
        api.set_clock("2027-09-17T00:00:00Z", headers=program_admin), expected_status=200
    )

    assert again["certifications_expired"] == 0
    assert again["fees_marked_delinquent"] == 0
    assert again["rofr_windows_auto_waived"] == 0
    certification_after_second = get_success_data(
        api.get_certification(ctx["certification_1"]["id"], headers=compliance_officer)
    )
    fee_after_second = get_success_data(api.get_in_lieu_fee(ctx["fee"]["id"], headers=program_admin))
    resale_after_second = get_success_data(
        api.get_resale(ctx["resale"]["id"], headers=compliance_officer)
    )
    assert certification_after_second["version"] == certification_after_first["version"]
    assert fee_after_second["version"] == fee_after_first["version"]
    assert resale_after_second["version"] == resale_after_first["version"]


# =============================================================================
# GET /iz-compliance/funder-reports
# =============================================================================
def _project_with_both_legs_delivered() -> dict:
    """A 20000 bps obligation half met on site and half converted to money.

    The rental unit is occupied and compliant, the assessment is only partly
    paid, and neither leg is a stored report figure: both are recomputed on read.
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    fixtures.bootstrap_program()
    project = fixtures.register_project(**dict(TWENTY_UNIT_R2, name="Funder Facing"))
    fixtures.screen_project(project["id"])
    fixtures.elect_path(project["id"], "ONSITE")
    agreement = fixtures.draft_agreement(project["id"])
    fixtures.record_agreement(
        agreement["id"], doc_number="DOC-FR-0001", recorded_at="2026-08-01"
    )
    unit = fixtures.add_unit(
        project["id"],
        agreement["id"],
        unit_number="FR-101",
        bedrooms=2,
        sqft=900,
        market_comparable_sqft=1000,
        tenure="RENTAL",
        affordability_level_bps=5000,
    )
    household = fixtures.register_household(
        applicant_name="Hana Iyer", household_size=3, gross_annual_income_cents=6000000
    )
    certification = fixtures.certify_income(
        household["id"],
        unit["id"],
        certified_income_cents=6000000,
        contract_rent_cents=140000,
        effective_date="2026-08-01",
    )
    # The unit's frozen ceiling is what a later over-ceiling review is measured against.
    occupied = fixtures.live_unit(unit["id"])
    assert occupied["max_allowed_rent_cents"] == MAX_ALLOWED_RENT_2BR_AT_5000_BPS
    # FULL prices what is still outstanding: 20000 minus the 10000 now on site.
    fee = fixtures.assess_fee(project["id"], basis="FULL")
    fee = fixtures.pay_fee(fee["id"], 1000000)
    return {
        "project": fixtures.live_project(project["id"]),
        "unit": occupied,
        "household": household,
        "certification": certification,
        "fee": fee,
    }


def test_the_two_funder_bases_share_every_figure_except_the_ratio(
    api: ApiClient, fund_auditor: dict
) -> None:
    """Both bases recompute the same live figures and differ only in the ratio.

    PRD: "On the `ENTITLEMENT` basis the ratio is 10000 multiplied by `delivered_equivalents_bps`, divided by `total_obligation_bps`, rounded half up."

    Design: Corner/endpoints/the_funder_report_recomputes_both_bases_from_live_program_state
    """
    ctx = _project_with_both_legs_delivered()
    project_id = ctx["project"]["id"]
    assert ctx["fee"]["unit_equivalent_bps"] == 10000
    assert ctx["fee"]["assessed_amount_cents"] == 24467400
    assert ctx["fee"]["state"] == "PARTIALLY_PAID"

    entitlement = validate_success(
        api.get_funder_report(project_id, "ENTITLEMENT", headers=fund_auditor),
        expected_status=200,
    )
    occupancy = validate_success(
        api.get_funder_report(project_id, "OCCUPANCY", headers=fund_auditor),
        expected_status=200,
    )

    assert entitlement["project_id"] == project_id
    assert entitlement["basis"] == "ENTITLEMENT"
    assert occupancy["basis"] == "OCCUPANCY"
    # The six basis-independent figures are identical on both reports.
    for shared in (
        "total_obligation_bps",
        "delivered_equivalents_bps",
        "occupied_equivalents_bps",
        "open_findings_count",
        "total_fees_assessed_cents",
        "total_fees_paid_cents",
    ):
        assert entitlement[shared] == occupancy[shared], shared
    assert entitlement["total_obligation_bps"] == 20000
    # 10000 bps of unit on site plus the 10000 bps the assessment covers.
    assert entitlement["delivered_equivalents_bps"] == 20000
    assert entitlement["occupied_equivalents_bps"] == 10000
    assert entitlement["open_findings_count"] == 0
    assert entitlement["total_fees_assessed_cents"] == 24467400
    assert entitlement["total_fees_paid_cents"] == 1000000
    # Only the ratio moves: 20000/20000 on paper against 10000/20000 in fact.
    assert entitlement["compliance_ratio_bps"] == 10000
    assert occupancy["compliance_ratio_bps"] == 5000
    # A report is a computed read, so neither call mutated the project.
    assert fixtures.live_project(project_id)["version"] == ctx["project"]["version"]


def test_a_finding_lowers_only_the_occupancy_ratio(
    api: ApiClient, fund_auditor: dict, compliance_officer: dict
) -> None:
    """An over-ceiling review empties the occupancy leg and leaves the paper leg whole.

    PRD: "The funder is crediting households actually housed: in-lieu fees contribute nothing at all, and a unit counts only while it is both occupied and compliant, so a finding on an occupied unit lowers this ratio without moving the entitlement ratio by a single basis point."

    Design: Corner/endpoints/the_funder_report_recomputes_both_bases_from_live_program_state
    """
    ctx = _project_with_both_legs_delivered()
    project_id = ctx["project"]["id"]
    fixtures.set_clock("2027-03-01T00:00:00Z")

    review = get_success_data(
        api.create_monitoring_review(
            factories.create_monitoring_review_payload(
                ctx["unit"]["id"], review_year=2027, reported_rent_cents=165000
            ),
            headers=compliance_officer,
        )
    )

    assert review["state"] == "FINDING_ISSUED"
    assert "RENT_OVERCHARGE" in review["finding_types"]
    flagged = fixtures.live_unit(ctx["unit"]["id"])
    assert_unit_dimensions(
        flagged, occupancy_status="OCCUPIED", compliance_status="FINDING_OPEN"
    )
    entitlement = validate_success(
        api.get_funder_report(project_id, "ENTITLEMENT", headers=fund_auditor),
        expected_status=200,
    )
    occupancy = validate_success(
        api.get_funder_report(project_id, "OCCUPANCY", headers=fund_auditor),
        expected_status=200,
    )
    assert entitlement["delivered_equivalents_bps"] == 20000
    assert entitlement["compliance_ratio_bps"] == 10000
    assert occupancy["occupied_equivalents_bps"] == 0
    assert occupancy["compliance_ratio_bps"] == 0
    assert entitlement["open_findings_count"] == 1
    assert occupancy["open_findings_count"] == 1
    # The delinquency the clock advance booked does not re-price the assessment.
    assert entitlement["total_fees_assessed_cents"] == 24467400
    assert entitlement["total_fees_paid_cents"] == 1000000


# =============================================================================
# POST /iz-compliance/resale-transactions/{resale_transaction_id}/rofr-decision
# =============================================================================
def _price_approved_resale_and_a_funded_fund(api: ApiClient) -> dict:
    """A resale awaiting the city's answer, beside a fund that can afford it.

    The fund is filled by a wholly separate C-2 development's paid assessment, so
    the money and the resale have no relationship other than the city's balance.
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    fund = fixtures.funded_trust_fund(
        project_overrides={
            "name": "Fund Source",
            "zoning_district": "C-2",
            "total_units": 40,
            "approval_date": "2026-01-15",
        }
    )
    project = fixtures.register_project(**dict(TWENTY_UNIT_R2, name="Refusal Right"))
    fixtures.screen_project(project["id"])
    fixtures.elect_path(project["id"], "ONSITE")
    agreement = fixtures.draft_agreement(project["id"])
    fixtures.record_agreement(
        agreement["id"], doc_number="DOC-RF-0001", recorded_at="2026-08-01"
    )
    unit = fixtures.add_unit(
        project["id"], agreement["id"], unit_number="RF-101", **dict(OWNERSHIP_2BR)
    )
    fixtures.record_restriction(
        unit["id"], original_purchase_price_cents=32500000, recorded_at="2026-08-01"
    )
    seller = fixtures.register_household(
        applicant_name="Jonas Wolf", household_size=3, gross_annual_income_cents=6000000
    )
    seller_certification = fixtures.certify_income(
        seller["id"],
        unit["id"],
        certified_income_cents=6000000,
        contract_rent_cents=0,
        effective_date="2026-08-01",
    )
    live = fixtures.live_unit(unit["id"])
    resale = get_success_data(
        api.create_resale(
            factories.create_resale_payload(
                live["id"],
                live["version"],
                proposed_price_cents=32000000,
                appraised_value_cents=41000000,
                capital_improvements_cents=0,
                deferred_maintenance_cents=0,
                broker_fee_cents=1000000,
            ),
            headers=fixtures.HCO,
        )
    )
    resale = get_success_data(api.approve_resale_price(resale["id"], headers=fixtures.HCO))
    return {
        "fund": fund["summary"],
        "unit": live,
        "seller": seller,
        "seller_certification": seller_certification,
        "resale": resale,
    }


def test_exercising_the_refusal_right_consults_the_fund_without_debiting_it(
    api: ApiClient, program_admin: dict, fund_auditor: dict
) -> None:
    """The city's purchase is gated on the balance yet books no draw against it.

    PRD: "`EXERCISE` means the city itself buys the unit, so it additionally requires the trust fund's `unencumbered_balance_cents` to be at least the `proposed_price_cents`, else `ERR_INSUFFICIENT_FUND_BALANCE`; it moves the transaction `PRICE_APPROVED → ROFR_EXERCISED`."

    Design: Corner/endpoints/the_rofr_decision_endpoint_branches_on_exercise_versus_waive
    """
    ctx = _price_approved_resale_and_a_funded_fund(api)
    assert ctx["fund"]["unencumbered_balance_cents"] == 189120000
    assert ctx["resale"]["max_resale_price_cents"] == 32500000

    exercised = validate_success(
        api.rofr_decision(ctx["resale"]["id"], "EXERCISE", headers=program_admin),
        expected_status=200,
    )

    assert exercised["state"] == "ROFR_EXERCISED"
    assert exercised["rofr_auto_waived"] is False
    # The city, not a household, is the buyer, so both buyer fields stay null.
    assert exercised["buyer_household_id"] is None
    assert exercised["buyer_certification_id"] is None
    # The balance was a precondition, not a payment: nothing left the fund.
    after = validate_success(api.get_trust_fund_summary(headers=fund_auditor))
    assert after["unencumbered_balance_cents"] == 189120000
    assert after["encumbered_cents"] == 0
    assert after["disbursed_cents"] == 0
    assert after["total_recapture_cents"] == 0
    assert_fund_money_conserved(after)
    draws, meta = validate_paginated(api.list_disbursements(headers=fund_auditor))
    assert meta["total_count"] == 0
    assert draws == []


def test_closing_an_exercised_resale_leaves_the_unit_vacant(
    api: ApiClient, program_admin: dict, second_compliance_officer: dict, fund_auditor: dict
) -> None:
    """The city purchase pays the seller its basis and hands back an empty unit.

    PRD: "On the `CLOSED` branch the unit's `occupant_household_id` becomes the `buyer_household_id` and its `occupancy_status` becomes `OCCUPIED`; on the `CITY_PURCHASE_CLOSED` branch the `occupant_household_id` is cleared to null and the `occupancy_status` becomes `VACANT`, because the city holds an empty unit awaiting a new placement."

    Design: Corner/endpoints/the_rofr_decision_endpoint_branches_on_exercise_versus_waive
    """
    ctx = _price_approved_resale_and_a_funded_fund(api)
    get_success_data(api.rofr_decision(ctx["resale"]["id"], "EXERCISE", headers=program_admin))

    closed = validate_success(
        api.close_resale(ctx["resale"]["id"], headers=second_compliance_officer),
        expected_status=200,
    )

    assert closed["state"] == "CITY_PURCHASE_CLOSED"
    # 32000000 asked minus the 1000000 broker fee, all of it inside the basis.
    assert closed["net_proceeds_cents"] == 31000000
    assert closed["seller_equity_cents"] == 31000000
    assert closed["seller_improvement_credit_cents"] == 0
    assert closed["seller_appreciation_share_cents"] == 0
    assert closed["city_recapture_cents"] == 0
    assert_waterfall_conserved(closed)
    vacated = fixtures.live_unit(ctx["unit"]["id"])
    assert_unit_dimensions(vacated, occupancy_status="VACANT", restriction_state="RECORDED")
    assert vacated["occupant_household_id"] is None
    # The basis resets to what the city paid, ready for the next resale.
    assert vacated["original_purchase_price_cents"] == 32000000
    assert vacated["ami_income_at_purchase_cents"] == MEDIAN_SIZE_3
    retired = get_success_data(
        api.get_certification(ctx["seller_certification"]["id"], headers=fund_auditor)
    )
    assert retired["state"] == "SUPERSEDED"
    # No recapture was booked, so the exercised branch adds nothing to the fund.
    summary = validate_success(api.get_trust_fund_summary(headers=fund_auditor))
    assert summary["total_recapture_cents"] == 0
    assert summary["unencumbered_balance_cents"] == 189120000


def test_waiving_the_refusal_right_needs_no_fund_and_is_not_an_auto_waiver(
    api: ApiClient, program_admin: dict
) -> None:
    """A waiver on an empty fund still succeeds and is marked as a deliberate one.

    PRD: "`WAIVE` moves the transaction `PRICE_APPROVED → ROFR_WAIVED` and the private sale proceeds."

    Design: Corner/endpoints/the_rofr_decision_endpoint_branches_on_exercise_versus_waive
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    unit_overrides = dict(OWNERSHIP_2BR, unit_number="WV-101")
    ctx = fixtures.price_approved_resale(
        32000000,
        ctx=fixtures.restricted_ownership_unit(
            unit_overrides=unit_overrides,
            original_purchase_price_cents=32500000,
            project_overrides=dict(TWENTY_UNIT_R2, name="Waiver Way"),
        ),
        resale_overrides={
            "appraised_value_cents": 41000000,
            "broker_fee_cents": 1000000,
        },
    )
    empty_fund = fixtures.fund_summary()
    assert empty_fund["unencumbered_balance_cents"] == 0
    assert empty_fund["total_inflow_cents"] == 0

    waived = validate_success(
        api.rofr_decision(ctx["resale"]["id"], "WAIVE", headers=program_admin),
        expected_status=200,
    )

    assert waived["state"] == "ROFR_WAIVED"
    # An explicit waiver is distinguishable from one the clock produced.
    assert waived["rofr_auto_waived"] is False
    assert waived["buyer_household_id"] is None
    assert waived["version"] == ctx["resale"]["version"] + 1


# =============================================================================
# POST /iz-compliance/resale-transactions/{resale_transaction_id}/certify-buyer
# =============================================================================
def _resale_awaiting_its_buyer(api: ApiClient) -> dict:
    """A waived resale whose seller is still in place and whose buyer is certified.

    The seller initiates its own resale, a first officer approves the price, and a
    second household is certified into the same ownership unit as the incoming buyer.
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.restricted_ownership_unit(
        unit_overrides=dict(OWNERSHIP_2BR, unit_number="BL-101"),
        original_purchase_price_cents=32500000,
        project_overrides=dict(TWENTY_UNIT_R2, name="Buyer Link"),
    )
    seller = fixtures.register_household(
        applicant_name="Hana Iyer", household_size=3, gross_annual_income_cents=6000000
    )
    seller_certification = fixtures.certify_income(
        seller["id"],
        ctx["unit"]["id"],
        certified_income_cents=6000000,
        contract_rent_cents=0,
        effective_date="2026-08-01",
    )
    live = fixtures.live_unit(ctx["unit"]["id"])
    assert live["occupant_household_id"] == seller["id"]
    resale = get_success_data(
        api.create_resale(
            factories.create_resale_payload(
                live["id"],
                live["version"],
                proposed_price_cents=32000000,
                appraised_value_cents=41000000,
                capital_improvements_cents=0,
                deferred_maintenance_cents=0,
                broker_fee_cents=1000000,
            ),
            headers=make_resident_headers(seller["id"]),
        )
    )
    resale = get_success_data(api.approve_resale_price(resale["id"], headers=fixtures.HCO))
    resale = get_success_data(api.rofr_decision(resale["id"], "WAIVE", headers=fixtures.PA))
    buyer = fixtures.register_household(
        applicant_name="Ines Novak", household_size=2, gross_annual_income_cents=5000000
    )
    buyer_certification = fixtures.certify_income(
        buyer["id"],
        ctx["unit"]["id"],
        certified_income_cents=5000000,
        contract_rent_cents=0,
        effective_date="2026-08-15",
        headers=fixtures.HCO2,
    )
    return {
        "unit": ctx["unit"],
        "seller": seller,
        "seller_certification": seller_certification,
        "buyer": buyer,
        "buyer_certification": buyer_certification,
        "resale": resale,
    }


def test_certifying_the_buyer_links_the_household_and_its_own_certification(
    api: ApiClient, second_compliance_officer: dict
) -> None:
    """Both buyer references land on the transaction and nothing else moves yet.

    PRD: "Success stores `buyer_household_id` and `buyer_certification_id` and moves the transaction `ROFR_WAIVED → BUYER_CERTIFIED`."

    Design: Corner/endpoints/certify_buyer_links_a_household_and_its_own_certification_to_the_resale
    """
    ctx = _resale_awaiting_its_buyer(api)
    assert ctx["resale"]["state"] == "ROFR_WAIVED"
    assert ctx["resale"]["buyer_household_id"] is None
    assert ctx["buyer_certification"]["income_limit_cents"] == INCOME_LIMIT_SIZE_2_AT_5000_BPS

    linked = validate_success(
        api.certify_buyer(
            ctx["resale"]["id"],
            ctx["buyer"]["id"],
            ctx["buyer_certification"]["id"],
            headers=second_compliance_officer,
        ),
        expected_status=200,
    )

    assert linked["state"] == "BUYER_CERTIFIED"
    assert linked["buyer_household_id"] == ctx["buyer"]["id"]
    assert linked["buyer_certification_id"] == ctx["buyer_certification"]["id"]
    assert linked["seller_household_id"] == ctx["seller"]["id"]
    assert linked["version"] == ctx["resale"]["version"] + 1
    # The waterfall only runs at close, so the money fields are still unset.
    assert linked["closed_at"] is None
    # Title has not changed hands either: the seller still occupies the unit.
    still_sellers = fixtures.live_unit(ctx["unit"]["id"])
    assert_unit_dimensions(still_sellers, occupancy_status="OCCUPIED")
    assert still_sellers["occupant_household_id"] == ctx["seller"]["id"]


def test_the_seller_and_buyer_certifications_coexist_on_one_ownership_unit(
    api: ApiClient, compliance_officer: dict
) -> None:
    """Two live certifications on one unit is exactly what a pending resale needs.

    PRD: "`EXPIRED` and `SUPERSEDED` certifications are invisible to the scan, and so is every `OWNERSHIP` certification: an `OWNERSHIP` unit skips the overlap scan entirely, which is precisely what allows the incoming buyer of a pending resale to be certified while the departing seller's certification is still `CERTIFIED`."

    Design: Corner/endpoints/certify_buyer_links_a_household_and_its_own_certification_to_the_resale
    """
    ctx = _resale_awaiting_its_buyer(api)

    live_certifications, meta = validate_paginated(
        api.list_certifications(
            unit_id=ctx["unit"]["id"], state="CERTIFIED", headers=compliance_officer
        )
    )

    assert meta["total_count"] == 2
    by_id = {row["id"]: row for row in live_certifications}
    assert set(by_id) == {ctx["seller_certification"]["id"], ctx["buyer_certification"]["id"]}
    for certification in by_id.values():
        # No term, so no closed interval for the scan to collide with.
        assert certification["expires_at"] is None
        assert certification["contract_rent_cents"] == 0
        assert certification["state"] == "CERTIFIED"
    assert by_id[ctx["seller_certification"]["id"]]["household_id"] == ctx["seller"]["id"]
    assert by_id[ctx["buyer_certification"]["id"]]["household_id"] == ctx["buyer"]["id"]
