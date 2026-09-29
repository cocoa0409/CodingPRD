"""Close-out gates, resale guards and trust-fund draw guards.

Each test builds every precondition it needs from declared endpoints, because the
database is empty and the logical clock reads its startup default when the test
begins.
"""

from test_helpers import (
    CLOCK_STARTUP_DEFAULT,
    MAX_ALLOWED_RENT_1BR_AT_5000_BPS,
    MAX_ALLOWED_RENT_2BR_AT_5000_BPS,
    ApiErrorId,
    assert_fee_pricing_chain,
    assert_fund_money_conserved,
    assert_obligation_equivalents_conserved,
    assert_project_state,
    assert_unit_dimensions,
    factories,
    fixtures,
    make_resident_headers,
    same_instant,
    validate_error,
    validate_paginated,
    validate_success,
)

# The canonical program prices a whole unit equivalent at the 5000 bps gap.
FULL_UNIT_GAP_CENTS = 24000000


def _monitoring_project(
    *,
    name,
    total_units,
    doc_number,
    units,
    households,
    zoning_district="R-2",
    approval_date="2026-01-15",
    developer_headers=None,
):
    """An ONSITE project carrying units and certifications, so it is MONITORING.

    `units` is a list of unit field overrides and `households` a list of
    (household overrides, certification overrides) pairs, each certification
    naming the unit at the same index.
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    fixtures.bootstrap_program()
    project = fixtures.register_project(
        headers=developer_headers,
        name=name,
        zoning_district=zoning_district,
        total_units=total_units,
        approval_date=approval_date,
    )
    fixtures.screen_project(project["id"])
    fixtures.elect_path(project["id"], "ONSITE", headers=developer_headers)
    agreement = fixtures.draft_agreement(
        project["id"],
        term_years=45,
        resale_formula="AMI_INDEXED",
        owner_appreciation_share_bps=2500,
        max_refinance_ltv_bps=9000,
    )
    agreement = fixtures.record_agreement(
        agreement["id"], doc_number=doc_number, recorded_at="2026-08-01"
    )
    created_units = [
        fixtures.add_unit(
            project["id"], agreement["id"], headers=developer_headers, **overrides
        )
        for overrides in units
    ]
    created_households = []
    created_certifications = []
    for index, (household_overrides, certification_overrides) in enumerate(households):
        household = fixtures.register_household(**household_overrides)
        created_households.append(household)
        created_certifications.append(
            fixtures.certify_income(
                household["id"], created_units[index]["id"], **certification_overrides
            )
        )
    return {
        "project": fixtures.live_project(project["id"], headers=fixtures.PA),
        "agreement": agreement,
        "units": [
            fixtures.live_unit(unit["id"], headers=fixtures.PA) for unit in created_units
        ],
        "households": created_households,
        "certifications": created_certifications,
    }


def _ownership_resale_project(unit_numbers):
    """An ONSITE project whose ownership units are restriction-recorded and sold.

    Every unit is a two-bedroom at 5000 bps whose deed restriction froze an
    original purchase price of 32500000 cents against the 2026 median, so the
    AMI-indexed ceiling of each unit is exactly that same 32500000 cents.
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    fixtures.bootstrap_program()
    project = fixtures.register_project(
        name="Resale Row",
        zoning_district="R-2",
        total_units=20,
        approval_date="2026-01-15",
    )
    fixtures.screen_project(project["id"])
    fixtures.elect_path(project["id"], "ONSITE")
    agreement = fixtures.draft_agreement(
        project["id"],
        term_years=45,
        resale_formula="AMI_INDEXED",
        owner_appreciation_share_bps=2500,
        max_refinance_ltv_bps=9000,
    )
    agreement = fixtures.record_agreement(
        agreement["id"], doc_number="DOC-RS-0001", recorded_at="2026-08-01"
    )
    units = []
    sellers = []
    certifications = []
    for index, unit_number in enumerate(unit_numbers, start=1):
        unit = fixtures.add_unit(
            project["id"],
            agreement["id"],
            unit_number=unit_number,
            bedrooms=2,
            sqft=900,
            market_comparable_sqft=1000,
            tenure="OWNERSHIP",
            affordability_level_bps=5000,
        )
        fixtures.record_restriction(
            unit["id"],
            original_purchase_price_cents=32500000,
            recorded_at="2026-08-01",
        )
        seller = fixtures.register_household(
            applicant_name=f"Owner {index}",
            household_size=3,
            gross_annual_income_cents=6000000,
        )
        certification = fixtures.certify_income(
            seller["id"],
            unit["id"],
            certified_income_cents=6000000,
            contract_rent_cents=0,
            effective_date="2026-08-01",
        )
        units.append(fixtures.live_unit(unit["id"], headers=fixtures.PA))
        sellers.append(seller)
        certifications.append(certification)
    return {
        "project": project,
        "agreement": agreement,
        "units": units,
        "sellers": sellers,
        "certifications": certifications,
    }


def _submit_resale(api, unit_id, headers, **overrides):
    """Submit a resale against a freshly read unit version."""
    unit = fixtures.live_unit(unit_id, headers=fixtures.PA)
    payload = factories.create_resale_payload(unit_id, unit["version"], **overrides)
    return api.create_resale(payload, headers=headers)


def _funded_fee_program():
    """One 40-unit C-2 fee-path project whose FULL assessment has been paid.

    The obligation is 8 whole units, so the assessment prices 80000 bps: a base of
    192000000 cents, a surcharge clamped to 5000000, a 400 bps scale discount and
    an assessed total of 189120000 cents, which is what the fund then holds.
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    return fixtures.funded_trust_fund(
        project_overrides={
            "name": "Fund Filler",
            "zoning_district": "C-2",
            "total_units": 40,
            "approval_date": "2026-01-15",
        }
    )


def test_close_out_refuses_a_project_whose_affordable_units_are_all_one_bedrooms(
    api, program_admin
):
    """A full onsite obligation delivered without a single family-sized unit is refused.

    PRD: "Multiply that count by 10000 and compare it against the project's `required_affordable_units` multiplied by 5000 basis points: if the family-unit side is strictly smaller the close-out is refused with `ERR_BEDROOM_DISTRIBUTION_FAILED`."

    Design: Corner/validations/close_out_guards_reject_a_bad_unit_mix_and_an_unmet_obligation
    """
    one_bedroom = {
        "bedrooms": 1,
        "sqft": 650,
        "market_comparable_sqft": 700,
        "tenure": "RENTAL",
        "affordability_level_bps": 5000,
    }
    ctx = _monitoring_project(
        name="Bedroom Bar",
        total_units=20,
        doc_number="DOC-BD-0001",
        units=[
            dict(one_bedroom, unit_number="BD-101"),
            dict(one_bedroom, unit_number="BD-102"),
        ],
        households=[
            (
                {
                    "applicant_name": "Xiu Renard",
                    "household_size": 2,
                    "gross_annual_income_cents": 5000000,
                },
                {
                    "certified_income_cents": 5000000,
                    "contract_rent_cents": 120000,
                    "effective_date": "2026-08-01",
                },
            )
        ],
    )
    project = ctx["project"]
    assert_project_state(project, state="MONITORING", applicability="SUBJECT")
    assert project["required_affordable_units"] == 2, project
    assert project["total_obligation_bps"] == 20000, project

    # The obligation rung that follows would have passed: both one-bedrooms count
    # as delivered onsite, so only the bedroom floor can explain the refusal.
    assert project["onsite_unit_equivalents_bps"] == 20000, project
    assert project["fee_covered_equivalents_bps"] == 0, project
    assert_obligation_equivalents_conserved(project)
    assert_project_state(project, compliance_posture="COMPLIANT_ONSITE")
    assert all(unit["bedrooms"] == 1 for unit in ctx["units"]), ctx["units"]
    certification = ctx["certifications"][0]
    assert certification["max_rent_cents"] == MAX_ALLOWED_RENT_1BR_AT_5000_BPS, certification

    response = api.close_out_project(project["id"], headers=program_admin)
    validate_error(response, ApiErrorId.ERR_BEDROOM_DISTRIBUTION_FAILED.value)

    after = fixtures.live_project(project["id"], headers=fixtures.PA)
    assert_project_state(after, state="MONITORING")
    assert_obligation_equivalents_conserved(after)


def test_close_out_refuses_a_project_that_delivered_only_half_its_obligation(
    api, program_admin
):
    """A perfect unit mix does not save a project that is short on equivalents.

    PRD: "The project's `compliance_posture` must be `COMPLIANT_ONSITE` or `COMPLIANT_BY_FEE`; a `DEFICIENT`, `UNDER_ENFORCEMENT` or `PENDING` posture is refused with `ERR_OBLIGATION_UNSATISFIED`."

    Design: Corner/validations/close_out_guards_reject_a_bad_unit_mix_and_an_unmet_obligation
    """
    ctx = _monitoring_project(
        name="Half Delivered",
        total_units=20,
        doc_number="DOC-BD-0002",
        units=[
            {
                "unit_number": "BD-201",
                "bedrooms": 2,
                "sqft": 900,
                "market_comparable_sqft": 1000,
                "tenure": "RENTAL",
                "affordability_level_bps": 5000,
            }
        ],
        households=[
            (
                {
                    "applicant_name": "Yara Petrov",
                    "household_size": 3,
                    "gross_annual_income_cents": 6000000,
                },
                {
                    "certified_income_cents": 6000000,
                    "contract_rent_cents": 140000,
                    "effective_date": "2026-08-01",
                },
            )
        ],
    )
    project = ctx["project"]
    assert_project_state(
        project, state="MONITORING", applicability="SUBJECT", compliance_posture="DEFICIENT"
    )
    assert project["required_affordable_units"] == 2, project
    assert project["total_obligation_bps"] == 20000, project
    assert project["onsite_unit_equivalents_bps"] == 10000, project
    assert project["fee_covered_equivalents_bps"] == 0, project

    # The bedroom rung above this one passes: the single delivered unit is a
    # two-bedroom, which is 10000 bps of family housing against a 10000 bps floor.
    assert ctx["units"][0]["bedrooms"] == 2, ctx["units"][0]

    response = api.close_out_project(project["id"], headers=program_admin)
    validate_error(response, ApiErrorId.ERR_OBLIGATION_UNSATISFIED.value)

    after = fixtures.live_project(project["id"], headers=fixtures.PA)
    assert_project_state(after, state="MONITORING", compliance_posture="DEFICIENT")
    assert_obligation_equivalents_conserved(after)


def test_close_out_refuses_a_project_whose_substitute_assessment_is_unpaid(
    api, compliance_officer
):
    """An assessment counts toward the obligation the moment it is booked, but must still be paid.

    PRD: "Every in-lieu assessment of the project must be in `state` `PAID` or `SUPERSEDED`; an `ASSESSED`, `PARTIALLY_PAID` or `DELINQUENT` assessment is refused with `ERR_FEE_OUTSTANDING`."

    Design: Corner/validations/close_out_guards_reject_an_unpaid_fee_and_an_open_finding
    """
    ctx = _monitoring_project(
        name="Fee Outstanding",
        total_units=20,
        doc_number="DOC-FO-0001",
        units=[
            {
                "unit_number": "FO-101",
                "bedrooms": 2,
                "sqft": 900,
                "market_comparable_sqft": 1000,
                "tenure": "RENTAL",
                "affordability_level_bps": 5000,
            }
        ],
        households=[
            (
                {
                    "applicant_name": "Zoya Marek",
                    "household_size": 3,
                    "gross_annual_income_cents": 6000000,
                },
                {
                    "certified_income_cents": 6000000,
                    "contract_rent_cents": 140000,
                    "effective_date": "2026-08-01",
                },
            )
        ],
    )
    project_id = ctx["project"]["id"]
    fee = fixtures.assess_fee(project_id, basis="FULL")
    assert fee["unit_equivalent_bps"] == 10000, fee
    assert fee["base_amount_cents"] == FULL_UNIT_GAP_CENTS, fee
    assert fee["surcharge_cents"] == 840000, fee
    assert fee["discount_bps_applied"] == 150, fee
    assert fee["assessed_amount_cents"] == 24467400, fee
    assert fee["paid_amount_cents"] == 0, fee
    assert fee["state"] == "ASSESSED", fee
    assert_fee_pricing_chain(fee)

    project = fixtures.live_project(project_id, headers=fixtures.PA)
    assert project["fee_covered_equivalents_bps"] == 10000, project
    assert_obligation_equivalents_conserved(project)
    assert_project_state(
        project, state="MONITORING", compliance_posture="COMPLIANT_BY_FEE"
    )

    response = api.close_out_project(project_id, headers=compliance_officer)
    validate_error(response, ApiErrorId.ERR_FEE_OUTSTANDING.value)

    after = fixtures.live_project(project_id, headers=fixtures.PA)
    assert_project_state(after, state="MONITORING", compliance_posture="COMPLIANT_BY_FEE")
    assert_obligation_equivalents_conserved(after)
    still_owed = validate_success(api.get_in_lieu_fee(fee["id"], headers=fixtures.PA))
    assert still_owed["state"] == "ASSESSED", still_owed


def test_close_out_refuses_a_project_carrying_an_unverified_occupancy_finding(
    api, compliance_officer
):
    """An open finding blocks close-out even when the unit is not out of compliance.

    PRD: "No monitoring review on any unit of the project may be in `state` `FINDING_ISSUED`, `CURE_SUBMITTED` or `ESCALATED`; any of those is refused with `ERR_OPEN_FINDING_BLOCKS_CLOSEOUT`."

    Design: Corner/validations/close_out_guards_reject_an_unpaid_fee_and_an_open_finding
    """
    ctx = _monitoring_project(
        name="Open Finding",
        total_units=10,
        doc_number="DOC-FO-0002",
        developer_headers=fixtures.DEV2,
        units=[
            {
                "unit_number": "FO-201",
                "bedrooms": 2,
                "sqft": 900,
                "market_comparable_sqft": 1000,
                "tenure": "RENTAL",
                "affordability_level_bps": 5000,
            }
        ],
        households=[
            (
                {
                    "applicant_name": "Wanda Oyelaran",
                    "household_size": 3,
                    "gross_annual_income_cents": 6000000,
                },
                {
                    "certified_income_cents": 6000000,
                    "contract_rent_cents": 140000,
                    "effective_date": "2026-08-01",
                },
            )
        ],
    )
    project_id = ctx["project"]["id"]
    unit_id = ctx["units"][0]["id"]
    assert ctx["units"][0]["max_allowed_rent_cents"] == MAX_ALLOWED_RENT_2BR_AT_5000_BPS, (
        ctx["units"][0]
    )

    fixtures.set_clock("2027-03-01T00:00:00Z")
    review = validate_success(
        api.create_monitoring_review(
            factories.create_monitoring_review_payload(
                unit_id,
                review_year=2027,
                reported_rent_cents=MAX_ALLOWED_RENT_2BR_AT_5000_BPS,
                reported_income_cents=6000000,
                occupancy_verified=False,
            ),
            headers=compliance_officer,
        ),
        201,
    )
    # A rent exactly at the ceiling and an income inside the growth tolerance leave
    # unverified occupancy as the only finding.
    assert review["finding_types"] == ["OCCUPANCY_UNVERIFIED"], review
    assert review["overcharge_monthly_cents"] == 0, review
    assert review["penalty_at_base_cents"] == 25000, review
    assert review["state"] == "FINDING_ISSUED", review

    unit = fixtures.live_unit(unit_id, headers=fixtures.PA)
    assert_unit_dimensions(unit, occupancy_status="OCCUPIED", compliance_status="FINDING_OPEN")
    project = fixtures.live_project(project_id, headers=fixtures.PA)
    assert project["fee_covered_equivalents_bps"] == 0, project
    assert_project_state(
        project, state="MONITORING", compliance_posture="COMPLIANT_ONSITE"
    )

    response = api.close_out_project(project_id, headers=compliance_officer)
    validate_error(response, ApiErrorId.ERR_OPEN_FINDING_BLOCKS_CLOSEOUT.value)

    after = fixtures.live_project(project_id, headers=fixtures.PA)
    assert_project_state(after, state="MONITORING", compliance_posture="COMPLIANT_ONSITE")
    assert_obligation_equivalents_conserved(after)
    unchanged = validate_success(
        api.get_monitoring_review(review["id"], headers=compliance_officer)
    )
    assert unchanged["state"] == "FINDING_ISSUED", unchanged


def test_resale_over_the_ceiling_is_accepted_at_submission_and_refused_at_approval(
    api, compliance_officer
):
    """The over-ceiling price is recorded first and audited only when it is approved.

    PRD: "The `proposed_price_cents` must be at most the frozen `max_resale_price_cents`, else `ERR_RESALE_PRICE_EXCEEDS_MAX`; the ceiling is inclusive."

    Design: Corner/validations/resale_guards_over_the_price_ceiling_the_fund_and_the_rofr_clock
    """
    ctx = _ownership_resale_project(["RS-101"])
    unit = ctx["units"][0]
    resale = validate_success(
        _submit_resale(
            api,
            unit["id"],
            compliance_officer,
            proposed_price_cents=33000000,
            appraised_value_cents=41000000,
            capital_improvements_cents=0,
            deferred_maintenance_cents=0,
            broker_fee_cents=1000000,
        ),
        201,
    )
    assert resale["state"] == "SUBMITTED", resale
    assert resale["proposed_price_cents"] == 33000000, resale
    assert resale["indexed_base_cents"] == 32500000, resale
    assert resale["max_resale_price_cents"] == 32500000, resale
    assert resale["seller_household_id"] == ctx["sellers"][0]["id"], resale

    response = api.approve_resale_price(resale["id"], headers=compliance_officer)
    validate_error(response, ApiErrorId.ERR_RESALE_PRICE_EXCEEDS_MAX.value)

    after = validate_success(api.get_resale(resale["id"], headers=compliance_officer))
    assert after["state"] == "SUBMITTED", after
    assert after.get("price_approved_at") is None, after
    assert after.get("price_approved_by_user_id") is None, after


def test_exercising_the_right_of_first_refusal_needs_a_fund_balance_a_waiver_does_not(
    api, program_admin, compliance_officer
):
    """The fund check guards only the exercising branch of the refusal decision.

    PRD: "`EXERCISE` means the city itself buys the unit, so it additionally requires the trust fund's `unencumbered_balance_cents` to be at least the `proposed_price_cents`, else `ERR_INSUFFICIENT_FUND_BALANCE`; it moves the transaction `PRICE_APPROVED → ROFR_EXERCISED`."

    Design: Corner/validations/resale_guards_over_the_price_ceiling_the_fund_and_the_rofr_clock
    """
    ctx = _ownership_resale_project(["RS-201"])
    unit = ctx["units"][0]
    resale = validate_success(
        _submit_resale(
            api,
            unit["id"],
            compliance_officer,
            proposed_price_cents=32000000,
            appraised_value_cents=41000000,
            capital_improvements_cents=0,
            deferred_maintenance_cents=0,
            broker_fee_cents=1000000,
        ),
        201,
    )
    approved = validate_success(
        api.approve_resale_price(resale["id"], headers=compliance_officer)
    )
    assert approved["state"] == "PRICE_APPROVED", approved
    assert approved["price_approved_by_user_id"] == compliance_officer["X-User-ID"], approved
    assert same_instant(approved["rofr_deadline"], "2026-08-31T00:00:00Z"), approved

    # No in-lieu payment has ever landed, so the fund cannot commit a single cent.
    summary = validate_success(api.get_trust_fund_summary(headers=program_admin))
    assert summary["unencumbered_balance_cents"] == 0, summary
    assert summary["total_inflow_cents"] == 0, summary
    assert_fund_money_conserved(summary)

    refused = api.rofr_decision(resale["id"], "EXERCISE", headers=program_admin)
    validate_error(refused, ApiErrorId.ERR_INSUFFICIENT_FUND_BALANCE.value)

    still_open = validate_success(api.get_resale(resale["id"], headers=compliance_officer))
    assert still_open["state"] == "PRICE_APPROVED", still_open
    assert still_open["rofr_auto_waived"] is False, still_open

    waived = validate_success(api.rofr_decision(resale["id"], "WAIVE", headers=program_admin))
    assert waived["state"] == "ROFR_WAIVED", waived


def test_certify_buyer_refuses_a_certification_belonging_to_another_household(
    api, program_admin, compliance_officer, second_compliance_officer
):
    """A CERTIFIED certification for the right unit still fails if it names the wrong household.

    PRD: "The referenced certification must be in `state` `CERTIFIED`, must be for this transaction's `unit_id`, and must belong to the household named in the payload; any mismatch is refused with `ERR_BUYER_CERTIFICATION_MISMATCH`."

    Design: Corner/validations/resale_guards_over_the_price_ceiling_the_fund_and_the_rofr_clock
    """
    ctx = _ownership_resale_project(["RS-301"])
    unit = ctx["units"][0]
    seller = ctx["sellers"][0]
    seller_certification = ctx["certifications"][0]
    buyer = fixtures.register_household(
        applicant_name="Ines Novak",
        household_size=2,
        gross_annual_income_cents=5000000,
    )
    resale = validate_success(
        _submit_resale(
            api,
            unit["id"],
            compliance_officer,
            proposed_price_cents=32000000,
            appraised_value_cents=41000000,
            capital_improvements_cents=0,
            deferred_maintenance_cents=0,
            broker_fee_cents=1000000,
        ),
        201,
    )
    validate_success(api.approve_resale_price(resale["id"], headers=compliance_officer))
    validate_success(api.rofr_decision(resale["id"], "WAIVE", headers=program_admin))

    live_certification = validate_success(
        api.get_certification(seller_certification["id"], headers=compliance_officer)
    )
    assert live_certification["state"] == "CERTIFIED", live_certification
    assert live_certification["unit_id"] == unit["id"], live_certification
    assert live_certification["household_id"] == seller["id"], live_certification

    # The acting officer is not the one who approved the price, so the
    # segregation-of-duties rung above this one passes.
    assert second_compliance_officer["X-User-ID"] != compliance_officer["X-User-ID"]
    response = api.certify_buyer(
        resale["id"],
        buyer["id"],
        seller_certification["id"],
        headers=second_compliance_officer,
    )
    validate_error(response, ApiErrorId.ERR_BUYER_CERTIFICATION_MISMATCH.value)

    after = validate_success(api.get_resale(resale["id"], headers=compliance_officer))
    assert after["state"] == "ROFR_WAIVED", after
    assert after.get("buyer_household_id") is None, after
    assert after.get("buyer_certification_id") is None, after


def test_a_refusal_decision_after_the_deadline_instant_is_refused_before_the_sweep_acts(
    api, program_admin, compliance_officer
):
    """The interactive window closes at the deadline instant, hours before the sweep sees it.

    PRD: "Between the deadline instant and the end of that calendar day the transaction is therefore still `PRICE_APPROVED`, yet an explicit decision arriving in that gap is refused with `ERR_ROFR_WINDOW_EXPIRED`."

    Design: Corner/validations/resale_guards_over_the_price_ceiling_the_fund_and_the_rofr_clock
    """
    ctx = _ownership_resale_project(["RS-401"])
    unit = ctx["units"][0]
    resale = validate_success(
        _submit_resale(
            api,
            unit["id"],
            compliance_officer,
            proposed_price_cents=32000000,
            appraised_value_cents=41000000,
            capital_improvements_cents=0,
            deferred_maintenance_cents=0,
            broker_fee_cents=1000000,
        ),
        201,
    )
    approved = validate_success(
        api.approve_resale_price(resale["id"], headers=compliance_officer)
    )
    assert same_instant(approved["rofr_deadline"], "2026-08-31T00:00:00Z"), approved

    sweep = fixtures.set_clock("2026-08-31T12:00:00Z")
    assert sweep["rofr_windows_auto_waived"] == 0, sweep

    response = api.rofr_decision(resale["id"], "WAIVE", headers=program_admin)
    validate_error(response, ApiErrorId.ERR_ROFR_WINDOW_EXPIRED.value)

    after = validate_success(api.get_resale(resale["id"], headers=compliance_officer))
    assert after["state"] == "PRICE_APPROVED", after
    assert after["rofr_auto_waived"] is False, after


def test_an_administrative_draw_may_reach_the_cap_exactly_but_not_a_cent_further(
    api, program_admin
):
    """The administrative ceiling is inclusive, so the very next cent is the one refused.

    PRD: "For an `ADMIN` draw, `admin_committed_cents` plus the requested `amount_cents` must be at most `admin_cap_cents`, else `ERR_ADMIN_USE_CAP_EXCEEDED`; both bounds are inclusive."

    Design: Corner/validations/trust_fund_draw_guards_over_the_admin_cap_the_balance_and_the_draw_state
    """
    ctx = _funded_fee_program()
    fee = ctx["fee"]
    assert fee["state"] == "PAID", fee
    assert fee["surcharge_cents"] == 5000000, fee
    assert fee["assessed_amount_cents"] == 189120000, fee
    assert_fee_pricing_chain(fee)

    summary = validate_success(api.get_trust_fund_summary(headers=program_admin))
    assert summary["total_inflow_cents"] == 189120000, summary
    assert summary["admin_cap_cents"] == 18912000, summary
    assert summary["admin_committed_cents"] == 0, summary

    at_the_cap = validate_success(
        api.create_disbursement(
            factories.create_disbursement_payload(
                fee["id"], 18912000, eligible_use="ADMIN"
            ),
            headers=program_admin,
        ),
        201,
    )
    assert at_the_cap["state"] == "REQUESTED", at_the_cap
    assert at_the_cap["eligible_use"] == "ADMIN", at_the_cap
    assert at_the_cap["amount_cents"] == 18912000, at_the_cap

    over_the_cap = api.create_disbursement(
        factories.create_disbursement_payload(fee["id"], 1, eligible_use="ADMIN"),
        headers=program_admin,
    )
    validate_error(over_the_cap, ApiErrorId.ERR_ADMIN_USE_CAP_EXCEEDED.value)

    after = validate_success(api.get_trust_fund_summary(headers=program_admin))
    assert after["admin_committed_cents"] == 18912000, after
    assert after["encumbered_cents"] == 18912000, after
    assert_fund_money_conserved(after)


def test_a_draw_of_any_use_may_take_the_whole_unencumbered_balance_but_not_more(
    api, program_admin
):
    """The balance guard measures the unencumbered bucket left by the earlier commitment.

    PRD: "And for every draw, the `amount_cents` must be at most `unencumbered_balance_cents`, else `ERR_INSUFFICIENT_FUND_BALANCE` — the same refusal that blocks a right-of-first-refusal exercise the fund cannot afford."

    Design: Corner/validations/trust_fund_draw_guards_over_the_admin_cap_the_balance_and_the_draw_state
    """
    ctx = _funded_fee_program()
    fee = ctx["fee"]
    fixtures.request_draw(fee["id"], 18912000, eligible_use="ADMIN")

    summary = validate_success(api.get_trust_fund_summary(headers=program_admin))
    assert summary["unencumbered_balance_cents"] == 170208000, summary
    assert summary["encumbered_cents"] == 18912000, summary

    over_the_balance = api.create_disbursement(
        factories.create_disbursement_payload(
            fee["id"], 170208001, eligible_use="AFFORDABLE_HOUSING_PRODUCTION"
        ),
        headers=program_admin,
    )
    validate_error(over_the_balance, ApiErrorId.ERR_INSUFFICIENT_FUND_BALANCE.value)

    exactly_the_balance = validate_success(
        api.create_disbursement(
            factories.create_disbursement_payload(
                fee["id"], 170208000, eligible_use="AFFORDABLE_HOUSING_PRODUCTION"
            ),
            headers=program_admin,
        ),
        201,
    )
    assert exactly_the_balance["state"] == "REQUESTED", exactly_the_balance

    drained = validate_success(api.get_trust_fund_summary(headers=program_admin))
    assert drained["unencumbered_balance_cents"] == 0, drained
    assert drained["encumbered_cents"] == 189120000, drained
    assert drained["disbursed_cents"] == 0, drained
    assert_fund_money_conserved(drained)


def test_a_disbursement_may_be_disbursed_or_voided_once_and_never_twice(
    api, program_admin, fund_auditor
):
    """Each terminal transition consumes the draw, so the repeat attempt is refused.

    PRD: "Any other state combination — disbursing something already disbursed or voided, voiding something already voided — is refused with `ERR_DISBURSEMENT_STATE_INVALID`."

    Design: Corner/validations/trust_fund_draw_guards_over_the_admin_cap_the_balance_and_the_draw_state
    """
    ctx = _funded_fee_program()
    fee = ctx["fee"]
    draw = fixtures.request_draw(fee["id"], 18912000, eligible_use="ADMIN")

    disbursed = validate_success(api.disburse(draw["id"], headers=program_admin))
    assert disbursed["state"] == "DISBURSED", disbursed
    assert same_instant(disbursed["disbursed_at"], CLOCK_STARTUP_DEFAULT), disbursed

    moved = validate_success(api.get_trust_fund_summary(headers=program_admin))
    assert moved["encumbered_cents"] == 0, moved
    assert moved["disbursed_cents"] == 18912000, moved
    assert moved["unencumbered_balance_cents"] == 170208000, moved

    repeat_disburse = api.disburse(draw["id"], headers=program_admin)
    validate_error(repeat_disburse, ApiErrorId.ERR_DISBURSEMENT_STATE_INVALID.value)

    unchanged = validate_success(api.get_disbursement(draw["id"], headers=program_admin))
    assert unchanged["state"] == "DISBURSED", unchanged
    assert same_instant(unchanged["disbursed_at"], disbursed["disbursed_at"]), unchanged

    voided = validate_success(
        api.void_disbursement(
            draw["id"], "Administrative allocation rescinded", headers=program_admin
        )
    )
    assert voided["state"] == "VOIDED", voided
    assert voided["void_reason"] == "Administrative allocation rescinded", voided

    repeat_void = api.void_disbursement(
        draw["id"], "Rescinded a second time", headers=program_admin
    )
    validate_error(repeat_void, ApiErrorId.ERR_DISBURSEMENT_STATE_INVALID.value)

    final_row = validate_success(api.get_disbursement(draw["id"], headers=program_admin))
    assert final_row["state"] == "VOIDED", final_row
    assert final_row["void_reason"] == "Administrative allocation rescinded", final_row

    restored = validate_success(api.get_trust_fund_summary(headers=fund_auditor))
    assert restored["encumbered_cents"] == 0, restored
    assert restored["disbursed_cents"] == 0, restored
    assert restored["admin_committed_cents"] == 0, restored
    assert restored["unencumbered_balance_cents"] == 189120000, restored
    assert_fund_money_conserved(restored)


def test_a_project_that_lotteries_certifies_and_reviews_cleanly_closes_out(
    api, program_admin, compliance_officer, developer
):
    """One development walks the whole obligation and clears all four close-out gates.

    PRD: "When all four gates pass, the project moves `MONITORING → CLOSED_OUT` and every regulatory agreement of that project still in `state` `RECORDED` moves `RECORDED → RELEASED`, each incrementing its own `version`."

    Design: Corner/validations/the_fully_compliant_project_passes_every_guard_end_to_end
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    fixtures.bootstrap_program()
    project = fixtures.register_project(
        name="Clean Close",
        zoning_district="R-2",
        total_units=10,
        approval_date="2026-01-15",
    )
    screened = fixtures.screen_project(project["id"])
    assert_project_state(screened, state="SCREENED_SUBJECT", applicability="SUBJECT")
    assert screened["required_affordable_units"] == 1, screened
    assert screened["total_obligation_bps"] == 10000, screened

    fixtures.elect_path(project["id"], "ONSITE")
    agreement = fixtures.draft_agreement(
        project["id"],
        term_years=45,
        resale_formula="AMI_INDEXED",
        owner_appreciation_share_bps=2500,
        max_refinance_ltv_bps=9000,
    )
    fixtures.record_agreement(
        agreement["id"], doc_number="DOC-CL-0001", recorded_at="2026-08-01"
    )
    # 800 square feet against a 1000 square foot comparable sits exactly on the
    # 8000 bps comparability floor, so the single family-sized unit is accepted.
    unit = fixtures.add_unit(
        project["id"],
        agreement["id"],
        unit_number="CL-101",
        bedrooms=2,
        sqft=800,
        tenure="RENTAL",
        affordability_level_bps=5000,
        market_comparable_sqft=1000,
    )
    assert_unit_dimensions(
        unit,
        occupancy_status="PLANNED",
        compliance_status="COMPLIANT",
        restriction_state="NOT_RECORDED",
    )
    household = fixtures.register_household(
        applicant_name="Ada Nakamura",
        household_size=3,
        gross_annual_income_cents=6000000,
    )

    plan = validate_success(
        api.create_marketing_plan(
            factories.create_marketing_plan_payload(
                project["id"],
                lottery_open_at="2026-08-05T00:00:00Z",
                lottery_close_at="2026-08-20T00:00:00Z",
                preference_categories=["DISPLACED"],
            ),
            headers=developer,
        ),
        201,
    )
    assert plan["state"] == "SUBMITTED", plan
    approved_plan = validate_success(
        api.review_marketing_plan(
            plan["id"], "APPROVE", review_note="Outreach plan accepted", headers=compliance_officer
        )
    )
    assert approved_plan["state"] == "APPROVED", approved_plan
    marketing_unit = fixtures.live_unit(unit["id"])
    assert_unit_dimensions(marketing_unit, occupancy_status="MARKETING")

    event = validate_success(
        api.create_lottery_event(
            factories.create_lottery_event_payload(
                plan["id"], units_offered=1, eligibility_level_bps=5000
            ),
            headers=program_admin,
        ),
        201,
    )
    assert event["state"] == "PENDING", event
    assert event["round_seq"] == 1, event

    fixtures.set_clock("2026-08-10T00:00:00Z")
    applied = validate_success(
        api.apply_household(
            household["id"],
            event["id"],
            preference_claims=["DISPLACED"],
            headers=make_resident_headers(household["id"]),
        )
    )
    assert applied["state"] == "APPLIED", applied
    assert applied["preference_score"] == 100, applied

    fixtures.set_clock("2026-08-20T00:00:00Z")
    drawn = validate_success(api.draw_lottery(event["id"], headers=program_admin))
    assert drawn["state"] == "DRAWN", drawn
    assert drawn["round_seq"] == 1, drawn
    assert drawn["selected_household_ids"] == [household["id"]], drawn
    assert drawn["waitlisted_household_ids"] == [], drawn
    assert drawn["drawn_by_user_id"] == program_admin["X-User-ID"], drawn

    selected = validate_success(api.get_household(household["id"], headers=program_admin))
    assert selected["state"] == "SELECTED", selected
    assert selected["rank_position"] == 1, selected
    assert selected["preference_score"] == 100, selected

    reserved_unit = fixtures.live_unit(unit["id"])
    assert_unit_dimensions(reserved_unit, occupancy_status="RESERVED")
    assert reserved_unit["occupant_household_id"] == household["id"], reserved_unit
    closed_plan = validate_success(api.get_marketing_plan(plan["id"], headers=program_admin))
    assert closed_plan["state"] == "CLOSED", closed_plan

    certification = fixtures.certify_income(
        household["id"],
        unit["id"],
        certified_income_cents=6000000,
        contract_rent_cents=MAX_ALLOWED_RENT_2BR_AT_5000_BPS,
        effective_date="2026-08-20",
    )
    assert certification["state"] == "CERTIFIED", certification
    assert certification["max_rent_cents"] == MAX_ALLOWED_RENT_2BR_AT_5000_BPS, certification

    occupied_unit = fixtures.live_unit(unit["id"])
    assert_unit_dimensions(
        occupied_unit, occupancy_status="OCCUPIED", compliance_status="COMPLIANT"
    )
    assert occupied_unit["current_rent_cents"] == MAX_ALLOWED_RENT_2BR_AT_5000_BPS, occupied_unit
    assert (
        occupied_unit["max_allowed_rent_cents"] == MAX_ALLOWED_RENT_2BR_AT_5000_BPS
    ), occupied_unit
    monitored = fixtures.live_project(project["id"], headers=fixtures.PA)
    assert_project_state(monitored, state="MONITORING", compliance_posture="COMPLIANT_ONSITE")
    assert_obligation_equivalents_conserved(monitored)

    fixtures.set_clock("2027-03-01T00:00:00Z")
    review = validate_success(
        api.create_monitoring_review(
            factories.create_monitoring_review_payload(
                unit["id"],
                review_year=2027,
                reported_rent_cents=MAX_ALLOWED_RENT_2BR_AT_5000_BPS,
                reported_income_cents=6000000,
                occupancy_verified=True,
            ),
            headers=compliance_officer,
        ),
        201,
    )
    assert review["state"] == "COMPLIANT", review
    assert review["finding_types"] == [], review
    assert review["cure_deadline"] is None, review
    assert review["penalty_at_base_cents"] == 0, review
    reviewed_unit = fixtures.live_unit(unit["id"])
    assert_unit_dimensions(
        reviewed_unit, occupancy_status="OCCUPIED", compliance_status="COMPLIANT"
    )

    closed_out = validate_success(api.close_out_project(project["id"], headers=program_admin))
    assert_project_state(
        closed_out, state="CLOSED_OUT", compliance_posture="COMPLIANT_ONSITE"
    )
    assert_obligation_equivalents_conserved(closed_out)

    released = validate_success(api.get_agreement(agreement["id"], headers=program_admin))
    assert released["state"] == "RELEASED", released
    assert released["version"] > agreement["version"], released

    fees, meta = validate_paginated(
        api.list_in_lieu_fees(project_id=project["id"], headers=program_admin)
    )
    assert fees == [], fees
    assert meta["total_count"] == 0, meta
