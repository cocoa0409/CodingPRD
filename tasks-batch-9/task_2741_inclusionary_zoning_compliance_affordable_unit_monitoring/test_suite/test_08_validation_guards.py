"""Validation guards: the refusals that fence the program's reference data,
uniqueness scopes, restriction lifecycle, withdrawal/reinstatement accounting,
lottery windows, certification terms and annual monitoring.

Every test builds its own preconditions from declared endpoints because the
database is empty when it starts.
"""

from test_helpers import (
    CLOCK_STARTUP_DEFAULT,
    INCOME_LIMIT_SIZE_3_AT_5000_BPS,
    MAX_ALLOWED_RENT_2BR_AT_5000_BPS,
    ApiErrorId,
    assert_obligation_equivalents_conserved,
    assert_project_state,
    assert_unit_dimensions,
    factories,
    fixtures,
    get_success_data,
    make_resident_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# A 20-unit R-2 development owes exactly two whole affordable units and no
# residual fraction: 20 * 1000 bps = 20000 bps of obligation.
R2_TWENTY_UNITS = {
    "zoning_district": "R-2",
    "total_units": 20,
    "approval_date": "2026-01-15",
}


def _register_r2_project(name, headers=None, **overrides):
    """Register a 20-unit R-2 development approved after the canonical vintage."""
    payload = dict(R2_TWENTY_UNITS)
    payload["name"] = name
    payload.update(overrides)
    return fixtures.register_project(headers=headers, **payload)


def _recorded_r2_project(name, doc_number, headers=None):
    """Take a 20-unit R-2 development all the way to AGREEMENT_RECORDED."""
    project = _register_r2_project(name, headers=headers)
    fixtures.screen_project(project["id"])
    fixtures.elect_path(project["id"], "ONSITE", headers=headers)
    agreement = fixtures.draft_agreement(project["id"])
    agreement = fixtures.record_agreement(
        agreement["id"], doc_number=doc_number, recorded_at="2026-08-01"
    )
    return fixtures.live_project(project["id"], headers=fixtures.PA), agreement


# =============================================================================
# Reference-data guards: no governing vintage, no permitted path, no schedule
# =============================================================================
def test_screening_without_any_published_ordinance_is_refused(
    api, program_admin, compliance_officer, developer
):
    """An empty ordinance table refuses screening, and the identical call succeeds once a vintage governs the project.

    PRD: "Consider every published `Ordinance` whose `effective_date` is on or before the project's `approval_date`; if that candidate set is empty, screening is refused with `ERR_NO_GOVERNING_ORDINANCE`."

    Design: Corner/validations/bootstrap_guards_reject_screening_election_and_restriction
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    project = validate_success(
        api.create_project(
            factories.create_project_payload(name="No Reference Data", **R2_TWENTY_UNITS),
            headers=developer,
        ),
        201,
    )

    refused = api.screen_project(project["id"], headers=compliance_officer)
    validate_error(refused, ApiErrorId.ERR_NO_GOVERNING_ORDINANCE.value)

    unscreened = validate_success(api.get_project(project["id"], headers=compliance_officer))
    assert_project_state(unscreened, state="DRAFT", applicability="PENDING")
    assert unscreened["screen_count"] == 0, unscreened

    validate_success(
        api.create_ordinance(factories.create_ordinance_payload(), headers=program_admin), 201
    )
    screened = validate_success(api.screen_project(project["id"], headers=compliance_officer))
    assert_project_state(screened, state="SCREENED_SUBJECT", applicability="SUBJECT")
    assert screened["required_affordable_units"] == 2, screened
    assert screened["total_obligation_bps"] == 20000, screened
    assert screened["screen_count"] == 1, screened


def test_screening_a_project_approved_before_every_vintage_is_refused(
    api, program_admin, compliance_officer, developer
):
    """Vintage selection is chronological, so a project approved before the only published vintage has no governing ordinance.

    PRD: "Consider every published `Ordinance` whose `effective_date` is on or before the project's `approval_date`; if that candidate set is empty, screening is refused with `ERR_NO_GOVERNING_ORDINANCE`."

    Design: Corner/validations/bootstrap_guards_reject_screening_election_and_restriction
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    project = validate_success(
        api.create_project(
            factories.create_project_payload(
                name="Approved Too Early",
                zoning_district="R-2",
                total_units=20,
                approval_date="2023-06-01",
            ),
            headers=developer,
        ),
        201,
    )
    ordinance = validate_success(
        api.create_ordinance(factories.create_ordinance_payload(), headers=program_admin), 201
    )
    assert ordinance["effective_date"] == "2024-01-01", ordinance
    assert ordinance["status"] == "ACTIVE", ordinance

    refused = api.screen_project(project["id"], headers=compliance_officer)
    validate_error(refused, ApiErrorId.ERR_NO_GOVERNING_ORDINANCE.value)

    unscreened = validate_success(api.get_project(project["id"], headers=compliance_officer))
    assert_project_state(unscreened, state="DRAFT", applicability="PENDING")
    assert unscreened["ordinance_id"] is None, unscreened
    assert unscreened["screen_count"] == 0, unscreened


def test_electing_a_path_the_vintage_does_not_allow_is_refused(
    api, program_admin, compliance_officer, developer
):
    """LAND_DEDICATION is inside the compliance_path enum yet outside the vintage's permitted alternatives.

    PRD: "The submitted `compliance_path` must be `ONSITE`, or must appear in the governing vintage's `alternative_paths_allowed`; anything else — `OFFSITE`, `IN_LIEU_FEE` or `LAND_DEDICATION` under a vintage that does not permit it — is refused with `ERR_PATH_NOT_PERMITTED`."

    Design: Corner/validations/bootstrap_guards_reject_screening_election_and_restriction
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    fixtures.publish_ordinance()
    project = _register_r2_project("Path Refused", headers=developer)
    screened = fixtures.screen_project(project["id"], headers=compliance_officer)
    assert_project_state(screened, state="SCREENED_SUBJECT")

    refused = api.elect_path(project["id"], "LAND_DEDICATION", headers=developer)
    validate_error(refused, ApiErrorId.ERR_PATH_NOT_PERMITTED.value)

    still_screened = validate_success(api.get_project(project["id"], headers=developer))
    assert_project_state(still_screened, state="SCREENED_SUBJECT")
    assert still_screened["compliance_path"] is None, still_screened

    elected = validate_success(api.elect_path(project["id"], "ONSITE", headers=developer))
    assert_project_state(elected, state="PATH_ELECTED")
    assert elected["compliance_path"] == "ONSITE", elected


def test_recording_a_restriction_without_any_ami_schedule_is_refused(
    api, program_admin, compliance_officer, developer
):
    """The deed restriction cannot pin an AMI basis while no schedule has ever been published.

    PRD: "The unit must not be `WITHDRAWN`, and at least one AMI schedule must exist, else `ERR_NO_AMI_SCHEDULE`."

    Design: Corner/validations/bootstrap_guards_reject_screening_election_and_restriction
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    fixtures.publish_ordinance()
    project, agreement = _recorded_r2_project("No Schedule Yet", "DOC-NR-0001")
    unit = fixtures.add_unit(
        project["id"],
        agreement["id"],
        unit_number="NR-101",
        bedrooms=2,
        sqft=900,
        market_comparable_sqft=1000,
        tenure="OWNERSHIP",
        affordability_level_bps=5000,
    )
    schedules, meta = validate_paginated(api.list_ami_schedules(headers=program_admin))
    assert meta["total_count"] == 0, schedules

    refused = api.record_restriction(unit["id"], 32500000, "2026-08-01", headers=compliance_officer)
    validate_error(refused, ApiErrorId.ERR_NO_AMI_SCHEDULE.value)

    # The higher rungs both pass: the restriction dimension is NOT_RECORDED and
    # the tenure is OWNERSHIP, so the schedule guard is the one that fired.
    unchanged = validate_success(api.get_unit(unit["id"], headers=compliance_officer))
    assert_unit_dimensions(unchanged, restriction_state="NOT_RECORDED")
    assert unchanged["tenure"] == "OWNERSHIP", unchanged
    # The refusal froze no AMI basis: the value the unit carried at creation is
    # exactly what it still carries.  The PRD names this field only on the
    # success branch ("freezes `ami_income_at_purchase_cents` from the active
    # schedule's ... entry"), so the refusal branch is checked for non-movement
    # rather than against a specific unset sentinel.
    assert (
        unchanged["ami_income_at_purchase_cents"] == unit["ami_income_at_purchase_cents"]
    ), unchanged
    assert unchanged["version"] == unit["version"], unchanged


# =============================================================================
# Uniqueness: two global scopes, one per-parent scope
# =============================================================================
def test_republishing_an_ordinance_code_is_refused(api, program_admin):
    """An ordinance `code` is unique across every vintage, whatever the rest of the payload says.

    PRD: "Republishing a `code` that already exists is refused with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/validations/uniqueness_is_enforced_per_parent_where_the_rule_declares_a_scope
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    first = fixtures.publish_ordinance()

    refused = api.create_ordinance(
        factories.create_ordinance_payload(
            effective_date="2025-01-01", min_project_units_threshold=12
        ),
        headers=program_admin,
    )
    validate_error(refused, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)

    rows, meta = validate_paginated(api.list_ordinances(headers=program_admin))
    assert meta["total_count"] == 1, rows
    assert rows[0]["id"] == first["id"], rows
    assert rows[0]["effective_date"] == "2024-01-01", rows
    assert rows[0]["min_project_units_threshold"] == 10, rows


def test_republishing_an_ami_effective_year_is_refused(api, program_admin):
    """An AMI schedule's `effective_year` is unique across every schedule, so the second publication changes nothing.

    PRD: "It is published with an `effective_year` — a calendar year between 2000 and 2100, unique across all schedules, again refused with `ERR_DUPLICATE_RESOURCE` on collision — plus two lookup tables."

    Design: Corner/validations/uniqueness_is_enforced_per_parent_where_the_rule_declares_a_scope
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    schedule = fixtures.publish_ami_schedule()

    refused = api.create_ami_schedule(
        factories.create_ami_schedule_payload(
            median_income_cents_by_size={"1": 1, "2": 2, "3": 3, "4": 4, "5": 5},
            utility_allowance_cents_by_bedrooms={"0": 1, "1": 1, "2": 1, "3": 1},
        ),
        headers=program_admin,
    )
    validate_error(refused, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)

    rows, meta = validate_paginated(api.list_ami_schedules(headers=program_admin))
    assert meta["total_count"] == 1, rows
    kept = validate_success(api.get_ami_schedule(schedule["id"], headers=program_admin))
    assert kept["effective_year"] == 2026, kept
    assert kept["median_income_cents_by_size"]["3"] == 12669800, kept
    assert kept["utility_allowance_cents_by_bedrooms"]["2"] == 14500, kept


def test_unit_number_uniqueness_is_scoped_to_the_owning_project(
    api, program_admin, developer
):
    """The unit_number key is (project_id, unit_number): a collision inside one project is refused while the same designation is accepted in another.

    PRD: "Uniqueness holds, else `ERR_DUPLICATE_RESOURCE`: `code` is unique across all ordinance vintages, `effective_year` across all AMI schedules, `unit_number` within a project, `review_year` within a unit, and `doc_number` across all regulatory agreements."

    Design: Corner/validations/uniqueness_is_enforced_per_parent_where_the_rule_declares_a_scope
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    fixtures.bootstrap_program()
    alpha, alpha_agreement = _recorded_r2_project("Dup Alpha", "DOC-DP-0001")
    beta, beta_agreement = _recorded_r2_project("Dup Beta", "DOC-DP-0002")
    original = fixtures.add_unit(
        alpha["id"],
        alpha_agreement["id"],
        unit_number="DUP-101",
        bedrooms=2,
        sqft=900,
        market_comparable_sqft=1000,
        tenure="RENTAL",
        affordability_level_bps=5000,
    )

    refused = api.create_unit(
        factories.create_unit_payload(
            alpha["id"],
            alpha_agreement["id"],
            unit_number="DUP-101",
            bedrooms=3,
            sqft=1100,
            market_comparable_sqft=1200,
            tenure="RENTAL",
            affordability_level_bps=8000,
        ),
        headers=developer,
    )
    validate_error(refused, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)

    kept, meta = validate_paginated(api.list_units(project_id=alpha["id"], headers=program_admin))
    assert meta["total_count"] == 1, kept
    assert kept[0]["id"] == original["id"], kept

    twin = validate_success(
        api.create_unit(
            factories.create_unit_payload(
                beta["id"],
                beta_agreement["id"],
                unit_number="DUP-101",
                bedrooms=2,
                sqft=900,
                market_comparable_sqft=1000,
                tenure="RENTAL",
                affordability_level_bps=5000,
            ),
            headers=developer,
        ),
        201,
    )
    assert twin["id"] != original["id"], twin
    assert twin["unit_number"] == "DUP-101", twin
    assert twin["project_id"] == beta["id"], twin


def test_agreement_doc_number_uniqueness_is_global(api, program_admin, compliance_officer):
    """A recording document number collides across projects, and the refusal leaves both the agreement and its project where they were.

    PRD: "The supplied `doc_number` must be unique across every agreement ever recorded, else `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/validations/uniqueness_is_enforced_per_parent_where_the_rule_declares_a_scope
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    fixtures.bootstrap_program()
    _recorded_r2_project("Dup Alpha", "DOC-DP-0001")

    # The collision is only reachable from PATH_ELECTED, because a second
    # recording on an already-recorded project is stopped by the project-state
    # rung first.
    gamma = _register_r2_project("Dup Gamma", headers=fixtures.DEV2)
    fixtures.screen_project(gamma["id"])
    fixtures.elect_path(gamma["id"], "ONSITE", headers=fixtures.DEV2)
    gamma_agreement = fixtures.draft_agreement(gamma["id"])

    refused = api.record_agreement(
        gamma_agreement["id"], "DOC-DP-0001", "2026-08-01", headers=compliance_officer
    )
    validate_error(refused, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)

    unchanged = validate_success(
        api.get_agreement(gamma_agreement["id"], headers=compliance_officer)
    )
    assert unchanged["state"] == "DRAFT", unchanged
    assert unchanged["doc_number"] is None, unchanged
    assert_project_state(
        validate_success(api.get_project(gamma["id"], headers=program_admin)),
        state="PATH_ELECTED",
    )


# =============================================================================
# Restriction and release guards: agreement, tenure, dimension, live resale
# =============================================================================
def test_recording_a_restriction_under_a_draft_agreement_is_refused(
    api, program_admin, compliance_officer
):
    """The guard reads the unit's OWN agreement, so a second DRAFT agreement blocks its unit even on an AGREEMENT_RECORDED project.

    PRD: "The unit's governing agreement must itself be `RECORDED`, else `ERR_AGREEMENT_NOT_RECORDED`."

    Design: Corner/validations/restriction_and_release_guards_across_tenure_agreement_and_live_resale
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    fixtures.bootstrap_program()
    project, recorded = _recorded_r2_project("Restriction Row", "DOC-RG-0001")
    assert_project_state(project, state="AGREEMENT_RECORDED")
    second = fixtures.draft_agreement(project["id"], resale_formula="SHARED_APPRECIATION")
    assert second["state"] == "DRAFT", second
    unit = fixtures.add_unit(
        project["id"],
        second["id"],
        unit_number="RG-301",
        bedrooms=2,
        sqft=900,
        market_comparable_sqft=1000,
        tenure="OWNERSHIP",
        affordability_level_bps=5000,
    )
    assert unit["agreement_id"] == second["id"], unit

    refused = api.record_restriction(unit["id"], 30000000, "2026-08-01", headers=compliance_officer)
    validate_error(refused, ApiErrorId.ERR_AGREEMENT_NOT_RECORDED.value)

    unchanged = validate_success(api.get_unit(unit["id"], headers=compliance_officer))
    assert_unit_dimensions(unchanged, restriction_state="NOT_RECORDED")
    assert unchanged["restriction_recorded_at"] is None, unchanged


def test_recording_a_restriction_on_a_rental_unit_is_refused(
    api, program_admin, compliance_officer
):
    """A rental unit has no deed to restrict, and its agreement is recorded, so tenure is the rung that fires.

    PRD: "The unit's `tenure` must be `OWNERSHIP` — a rental unit has no deed restriction to record and is refused with `ERR_RESTRICTION_TENURE_MISMATCH`."

    Design: Corner/validations/restriction_and_release_guards_across_tenure_agreement_and_live_resale
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    fixtures.bootstrap_program()
    project, agreement = _recorded_r2_project("Restriction Row", "DOC-RG-0001")
    assert agreement["state"] == "RECORDED", agreement
    rental = fixtures.add_unit(
        project["id"],
        agreement["id"],
        unit_number="RG-201",
        bedrooms=2,
        sqft=900,
        market_comparable_sqft=1000,
        tenure="RENTAL",
        affordability_level_bps=5000,
    )

    refused = api.record_restriction(rental["id"], 30000000, "2026-08-01", headers=compliance_officer)
    validate_error(refused, ApiErrorId.ERR_RESTRICTION_TENURE_MISMATCH.value)

    unchanged = validate_success(api.get_unit(rental["id"], headers=compliance_officer))
    assert unchanged["tenure"] == "RENTAL", unchanged
    assert_unit_dimensions(unchanged, restriction_state="NOT_RECORDED")


def test_refinance_review_on_an_unrestricted_unit_is_refused(api, program_admin, developer):
    """A balance of one cent would clear any LTV ceiling, so only the restriction-dimension rung can explain the refusal.

    PRD: "The unit's `restriction_state` permits the operation — `NOT_RECORDED` to record a restriction, `RECORDED` to release one, to run a refinance review, or to submit a resale — else `ERR_UNIT_NOT_RESTRICTED`."

    Design: Corner/validations/restriction_and_release_guards_across_tenure_agreement_and_live_resale
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    fixtures.bootstrap_program()
    project, agreement = _recorded_r2_project("Restriction Row", "DOC-RG-0001")
    rental = fixtures.add_unit(
        project["id"],
        agreement["id"],
        unit_number="RG-201",
        bedrooms=2,
        sqft=900,
        market_comparable_sqft=1000,
        tenure="RENTAL",
        affordability_level_bps=5000,
    )
    assert_unit_dimensions(rental, restriction_state="NOT_RECORDED")

    refused = api.refinance_review(rental["id"], 1, headers=developer)
    validate_error(refused, ApiErrorId.ERR_UNIT_NOT_RESTRICTED.value)


def test_releasing_a_restriction_while_a_resale_is_live_is_refused(
    api, program_admin, compliance_officer
):
    """A SUBMITTED resale is a live transaction, so the deed restriction may not be released out from under it.

    PRD: "Release is blocked while any resale of that unit is live — that is, in `SUBMITTED`, `PRICE_APPROVED`, `ROFR_WAIVED`, `ROFR_EXERCISED` or `BUYER_CERTIFIED` — refused with `ERR_RESALE_IN_PROGRESS`, and it is blocked while the unit's `compliance_status` is `OUT_OF_COMPLIANCE`, refused with `ERR_UNIT_OUT_OF_COMPLIANCE`."

    Design: Corner/validations/restriction_and_release_guards_across_tenure_agreement_and_live_resale
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    fixtures.bootstrap_program()
    project, agreement = _recorded_r2_project("Restriction Row", "DOC-RG-0001")
    unit = fixtures.add_unit(
        project["id"],
        agreement["id"],
        unit_number="RG-101",
        bedrooms=2,
        sqft=900,
        market_comparable_sqft=1000,
        tenure="OWNERSHIP",
        affordability_level_bps=5000,
    )
    unit = fixtures.record_restriction(
        unit["id"], original_purchase_price_cents=32500000, recorded_at="2026-08-01"
    )
    assert_unit_dimensions(unit, restriction_state="RECORDED")
    household = fixtures.register_household(
        applicant_name="Hana Iyer", household_size=3, gross_annual_income_cents=6000000
    )
    fixtures.certify_income(
        household["id"],
        unit["id"],
        certified_income_cents=6000000,
        contract_rent_cents=0,
        effective_date="2026-08-01",
    )
    ctx = fixtures.submitted_resale(
        32000000,
        ctx={"unit": {"id": unit["id"]}},
        resale_overrides={
            "appraised_value_cents": 40000000,
            "broker_fee_cents": 1000000,
        },
    )
    assert ctx["resale"]["state"] == "SUBMITTED", ctx["resale"]

    refused = api.release_restriction(unit["id"], headers=compliance_officer)
    validate_error(refused, ApiErrorId.ERR_RESALE_IN_PROGRESS.value)

    still_restricted = validate_success(api.get_unit(unit["id"], headers=compliance_officer))
    assert_unit_dimensions(still_restricted, restriction_state="RECORDED")
    live_resale = validate_success(api.get_resale(ctx["resale"]["id"], headers=compliance_officer))
    assert live_resale["state"] == "SUBMITTED", live_resale


# =============================================================================
# Withdrawal and reinstatement: occupancy rung, then the substitution ledger
# =============================================================================
def _withdraw_walk(api):
    """Two rental units where WD-101 is withdrawn, cascading one SUBSTITUTION assessment.

    The withdrawn unit's 10000 bps price out at base 24000000 plus a 350 bps
    surcharge of 840000, a pre-discount total of 24840000 that lands in the
    150 bps tier, so the assessment is 24840000 - 372600 = 24467400.
    """
    fixtures.bootstrap_program()
    project, agreement = _recorded_r2_project("Withdraw Walk", "DOC-WD-0001")
    unit_specs = {
        "bedrooms": 2,
        "sqft": 900,
        "market_comparable_sqft": 1000,
        "tenure": "RENTAL",
        "affordability_level_bps": 5000,
    }
    first = fixtures.add_unit(project["id"], agreement["id"], unit_number="WD-101", **unit_specs)
    second = fixtures.add_unit(project["id"], agreement["id"], unit_number="WD-102", **unit_specs)
    first = get_success_data(
        api.withdraw_unit(
            first["id"], "Structural redesign removed the stack", headers=fixtures.DEV
        )
    )
    fees, meta = validate_paginated(
        api.list_in_lieu_fees(
            project_id=project["id"], basis="SUBSTITUTION", headers=fixtures.PA
        )
    )
    assert meta["total_count"] == 1, fees
    assert fees[0]["assessed_amount_cents"] == 24467400, fees[0]
    return {
        "project": project,
        "agreement": agreement,
        "withdrawn_unit": first,
        "standing_unit": second,
        "fee": fees[0],
    }


def test_withdrawing_an_already_withdrawn_unit_is_refused(api, program_admin, developer):
    """The second withdrawal is stopped by the occupancy rung, so no second substitution assessment is cascaded.

    PRD: "The unit's `occupancy_status` permits the operation — withdrawal only from `PLANNED` or `MARKETING`, reinstatement only from `WITHDRAWN` — else `ERR_UNIT_OCCUPANCY_STATE_INVALID`."

    Design: Corner/validations/withdraw_and_reinstate_guards_over_occupancy_and_substitution_fees
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    ctx = _withdraw_walk(api)
    assert_unit_dimensions(ctx["withdrawn_unit"], occupancy_status="WITHDRAWN")

    refused = api.withdraw_unit(
        ctx["withdrawn_unit"]["id"], "Second attempt at the same withdrawal", headers=developer
    )
    validate_error(refused, ApiErrorId.ERR_UNIT_OCCUPANCY_STATE_INVALID.value)

    fees, meta = validate_paginated(
        api.list_in_lieu_fees(
            project_id=ctx["project"]["id"], basis="SUBSTITUTION", headers=program_admin
        )
    )
    assert meta["total_count"] == 1, fees
    assert fees[0]["id"] == ctx["fee"]["id"], fees
    still_withdrawn = validate_success(
        api.get_unit(ctx["withdrawn_unit"]["id"], headers=program_admin)
    )
    assert_unit_dimensions(still_withdrawn, occupancy_status="WITHDRAWN")


def test_reinstating_a_planned_unit_is_refused(api, program_admin, developer):
    """The occupancy rung fires before the substitution-fee rules are consulted at all, because a PLANNED unit was never withdrawn.

    PRD: "The unit's `occupancy_status` permits the operation — withdrawal only from `PLANNED` or `MARKETING`, reinstatement only from `WITHDRAWN` — else `ERR_UNIT_OCCUPANCY_STATE_INVALID`."

    Design: Corner/validations/withdraw_and_reinstate_guards_over_occupancy_and_substitution_fees
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    ctx = _withdraw_walk(api)
    assert_unit_dimensions(ctx["standing_unit"], occupancy_status="PLANNED")

    refused = api.reinstate_unit(ctx["standing_unit"]["id"], headers=developer)
    validate_error(refused, ApiErrorId.ERR_UNIT_OCCUPANCY_STATE_INVALID.value)

    unchanged = validate_success(api.get_unit(ctx["standing_unit"]["id"], headers=program_admin))
    assert_unit_dimensions(unchanged, occupancy_status="PLANNED")


def test_reinstating_a_unit_whose_substitution_fee_is_part_paid_is_refused(
    api, program_admin, developer
):
    """Any payment at all on the substitution assessment blocks reinstatement, so no money is stranded.

    PRD: "If the selected assessment's `paid_amount_cents` is greater than 0 — any payment at all has landed on it — the reinstatement is refused with `ERR_SUBSTITUTION_FEE_PAID` rather than silently stranding the money, which is exactly what keeps the unit-equivalents quantity conserved."

    Design: Corner/validations/withdraw_and_reinstate_guards_over_occupancy_and_substitution_fees
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    ctx = _withdraw_walk(api)

    part_paid = validate_success(
        api.pay_in_lieu_fee(ctx["fee"]["id"], 1000000, headers=developer)
    )
    assert part_paid["state"] == "PARTIALLY_PAID", part_paid
    assert part_paid["paid_amount_cents"] == 1000000, part_paid

    refused = api.reinstate_unit(ctx["withdrawn_unit"]["id"], headers=developer)
    validate_error(refused, ApiErrorId.ERR_SUBSTITUTION_FEE_PAID.value)

    still_withdrawn = validate_success(
        api.get_unit(ctx["withdrawn_unit"]["id"], headers=program_admin)
    )
    assert_unit_dimensions(still_withdrawn, occupancy_status="WITHDRAWN")
    assert (
        validate_success(api.get_in_lieu_fee(ctx["fee"]["id"], headers=program_admin))["state"]
        == "PARTIALLY_PAID"
    )


def test_reinstating_a_unit_whose_substitution_fee_is_settled_is_refused(
    api, program_admin, developer
):
    """Once the assessment is PAID it has left the open set, so the selection step finds nothing and the error id changes.

    PRD: "If there is no such assessment the reinstatement is refused with `ERR_NO_SUBSTITUTION_FEE`."

    Design: Corner/validations/withdraw_and_reinstate_guards_over_occupancy_and_substitution_fees
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    ctx = _withdraw_walk(api)
    validate_success(api.pay_in_lieu_fee(ctx["fee"]["id"], 1000000, headers=developer))
    settled = validate_success(
        api.pay_in_lieu_fee(ctx["fee"]["id"], 23467400, headers=developer)
    )
    assert settled["state"] == "PAID", settled
    assert settled["paid_amount_cents"] == 24467400, settled

    refused = api.reinstate_unit(ctx["withdrawn_unit"]["id"], headers=developer)
    validate_error(refused, ApiErrorId.ERR_NO_SUBSTITUTION_FEE.value)

    still_withdrawn = validate_success(
        api.get_unit(ctx["withdrawn_unit"]["id"], headers=program_admin)
    )
    assert_unit_dimensions(still_withdrawn, occupancy_status="WITHDRAWN")


def test_a_further_full_assessment_with_nothing_left_to_price_is_refused(
    api, program_admin, developer
):
    """With the substitution assessment settled the obligation is entirely covered, so a FULL basis prices nothing.

    PRD: "If that figure is zero or negative — the project owes nothing the requested basis can price — the assessment is refused with `ERR_NO_REMAINING_OBLIGATION`."

    Design: Corner/validations/withdraw_and_reinstate_guards_over_occupancy_and_substitution_fees
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    ctx = _withdraw_walk(api)
    validate_success(api.pay_in_lieu_fee(ctx["fee"]["id"], 1000000, headers=developer))
    validate_success(api.pay_in_lieu_fee(ctx["fee"]["id"], 23467400, headers=developer))

    project = validate_success(api.get_project(ctx["project"]["id"], headers=program_admin))
    assert project["onsite_unit_equivalents_bps"] == 10000, project
    assert project["fee_covered_equivalents_bps"] == 10000, project
    assert project["total_obligation_bps"] == 20000, project
    assert_obligation_equivalents_conserved(project)

    # The expected version is the live one, so the concurrency guard passes and
    # the fiscal rule is what refuses the assessment.
    refused = api.create_in_lieu_fee(
        factories.create_in_lieu_fee_payload(project["id"], project["version"], basis="FULL"),
        headers=program_admin,
    )
    validate_error(refused, ApiErrorId.ERR_NO_REMAINING_OBLIGATION.value)

    fees, meta = validate_paginated(
        api.list_in_lieu_fees(project_id=project["id"], headers=program_admin)
    )
    assert meta["total_count"] == 1, fees


# =============================================================================
# Lottery windows: two clock rules pointing in opposite directions
# =============================================================================
LOTTERY_UNIT_SPECS = {
    "bedrooms": 2,
    "sqft": 900,
    "market_comparable_sqft": 1000,
    "tenure": "RENTAL",
    "affordability_level_bps": 5000,
}


def _lottery_project(api):
    """A 20-unit R-2 project with two rental units, ready for a marketing plan."""
    fixtures.bootstrap_program()
    project, agreement = _recorded_r2_project("Lottery Lane", "DOC-LT-0001")
    first = fixtures.add_unit(
        project["id"], agreement["id"], unit_number="LT-101", **LOTTERY_UNIT_SPECS
    )
    second = fixtures.add_unit(
        project["id"], agreement["id"], unit_number="LT-102", **LOTTERY_UNIT_SPECS
    )
    return {"project": project, "agreement": agreement, "units": [first, second]}


def _lottery_lane(api):
    """An approved plan running 2026-08-05 .. 2026-08-20 with two rounds and three households."""
    ctx = _lottery_project(api)
    plan = get_success_data(
        api.create_marketing_plan(
            factories.create_marketing_plan_payload(
                ctx["project"]["id"],
                lottery_open_at="2026-08-05T00:00:00Z",
                lottery_close_at="2026-08-20T00:00:00Z",
                preference_categories=[],
            ),
            headers=fixtures.DEV,
        )
    )
    ctx["marketing_plan"] = get_success_data(
        api.review_marketing_plan(plan["id"], "APPROVE", headers=fixtures.HCO)
    )
    ctx["round_two_units"] = get_success_data(
        api.create_lottery_event(
            factories.create_lottery_event_payload(plan["id"], units_offered=2),
            headers=fixtures.PA,
        )
    )
    ctx["round_one_unit"] = get_success_data(
        api.create_lottery_event(
            factories.create_lottery_event_payload(plan["id"], units_offered=1),
            headers=fixtures.PA,
        )
    )
    ctx["under_limit_size_three"] = fixtures.register_household(
        applicant_name="Hana Iyer", household_size=3, gross_annual_income_cents=6000000
    )
    ctx["under_limit_size_two"] = fixtures.register_household(
        applicant_name="Ines Novak", household_size=2, gross_annual_income_cents=5000000
    )
    ctx["over_limit_size_three"] = fixtures.register_household(
        applicant_name="Kira Baros", household_size=3, gross_annual_income_cents=6400000
    )
    return ctx


def test_a_zero_length_application_window_is_refused(api, program_admin, developer):
    """The window rule is strictly-earlier, so an open instant equal to the close instant is not a degenerate accept.

    PRD: "The plan declares its application window as `lottery_open_at`, the inclusive start, and `lottery_close_at`, the exclusive end, both ISO 8601 UTC instants; `lottery_open_at` must be strictly earlier than `lottery_close_at`, else the submission is refused with `ERR_INVALID_MARKETING_WINDOW`."

    Design: Corner/validations/lottery_window_guards_reject_early_late_empty_and_post_certification_calls
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    ctx = _lottery_project(api)

    refused = api.create_marketing_plan(
        factories.create_marketing_plan_payload(
            ctx["project"]["id"],
            lottery_open_at="2026-08-05T00:00:00Z",
            lottery_close_at="2026-08-05T00:00:00Z",
            preference_categories=[],
        ),
        headers=developer,
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_MARKETING_WINDOW.value)

    plans, meta = validate_paginated(
        api.list_marketing_plans(project_id=ctx["project"]["id"], headers=program_admin)
    )
    assert meta["total_count"] == 0, plans

    accepted = validate_success(
        api.create_marketing_plan(
            factories.create_marketing_plan_payload(
                ctx["project"]["id"],
                lottery_open_at="2026-08-05T00:00:00Z",
                lottery_close_at="2026-08-20T00:00:00Z",
                preference_categories=[],
            ),
            headers=developer,
        ),
        201,
    )
    assert accepted["state"] == "SUBMITTED", accepted
    assert accepted["revision_round"] == 0, accepted


def test_applications_outside_the_half_open_window_are_refused(api, program_admin):
    """The window includes its lower endpoint and excludes its upper one, so only the clock decides between 422 and 200.

    PRD: "The plan behind the round must be `APPROVED`, and the current logical instant must sit at or after the plan's `lottery_open_at` and strictly before its `lottery_close_at`; an application outside that half-open window is refused with `ERR_APPLICATION_WINDOW_CLOSED`."

    Design: Corner/validations/lottery_window_guards_reject_early_late_empty_and_post_certification_calls
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    ctx = _lottery_lane(api)
    applicant = ctx["under_limit_size_three"]
    round_id = ctx["round_two_units"]["id"]

    too_early = api.apply_household(
        applicant["id"], round_id, headers=make_resident_headers(applicant["id"])
    )
    validate_error(too_early, ApiErrorId.ERR_APPLICATION_WINDOW_CLOSED.value)
    assert (
        validate_success(api.get_household(applicant["id"], headers=program_admin))["state"]
        == "REGISTERED"
    )

    fixtures.set_clock("2026-08-10T00:00:00Z", headers=program_admin)
    accepted = validate_success(
        api.apply_household(
            applicant["id"], round_id, headers=make_resident_headers(applicant["id"])
        )
    )
    assert accepted["state"] == "APPLIED", accepted
    assert accepted["lottery_event_id"] == round_id, accepted

    # Exactly at lottery_close_at the window has already excluded applicants.
    fixtures.set_clock("2026-08-20T00:00:00Z", headers=program_admin)
    latecomer = ctx["under_limit_size_two"]
    too_late = api.apply_household(
        latecomer["id"], round_id, headers=make_resident_headers(latecomer["id"])
    )
    validate_error(too_late, ApiErrorId.ERR_APPLICATION_WINDOW_CLOSED.value)
    assert (
        validate_success(api.get_household(latecomer["id"], headers=program_admin))["state"]
        == "REGISTERED"
    )


def test_a_draw_run_while_the_window_is_open_is_refused(api, program_admin):
    """The draw needs the window over, so the instant that still admits applicants refuses the draw.

    PRD: "The application window has closed before a draw is run, else `ERR_APPLICATION_WINDOW_OPEN`."

    Design: Corner/validations/lottery_window_guards_reject_early_late_empty_and_post_certification_calls
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    ctx = _lottery_lane(api)
    round_id = ctx["round_two_units"]["id"]
    fixtures.set_clock("2026-08-10T00:00:00Z", headers=program_admin)
    fixtures.apply_to_lottery(ctx["under_limit_size_three"]["id"], round_id)
    fixtures.apply_to_lottery(ctx["under_limit_size_two"]["id"], round_id)

    refused = api.draw_lottery(round_id, headers=program_admin)
    validate_error(refused, ApiErrorId.ERR_APPLICATION_WINDOW_OPEN.value)

    pending = validate_success(api.get_lottery_event(round_id, headers=program_admin))
    assert pending["state"] == "PENDING", pending
    assert pending["drawn_at"] is None, pending
    assert pending["selected_household_ids"] == [], pending

    # The same call at exactly lottery_close_at is allowed: the endpoint the
    # applicants are excluded from is the one the draw requires.
    fixtures.set_clock("2026-08-20T00:00:00Z", headers=program_admin)
    drawn = validate_success(api.draw_lottery(round_id, headers=program_admin))
    assert drawn["state"] == "DRAWN", drawn
    assert drawn["selected_household_ids"] == [
        ctx["under_limit_size_three"]["id"],
        ctx["under_limit_size_two"]["id"],
    ], drawn
    assert drawn["round_seq"] == 1, drawn
    assert drawn["drawn_at"] is not None, drawn


def test_a_draw_with_no_income_eligible_applicant_is_refused(api, program_admin):
    """An applicant over the income limit for its own household size leaves the pool empty rather than yielding an empty selection.

    PRD: "If the pool is empty the draw is refused with `ERR_EMPTY_ELIGIBLE_POOL`."

    Design: Corner/validations/lottery_window_guards_reject_early_late_empty_and_post_certification_calls
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    ctx = _lottery_lane(api)
    round_id = ctx["round_one_unit"]["id"]
    over_limit = ctx["over_limit_size_three"]
    assert over_limit["gross_annual_income_cents"] > INCOME_LIMIT_SIZE_3_AT_5000_BPS, over_limit
    fixtures.set_clock("2026-08-10T00:00:00Z", headers=program_admin)
    applied = fixtures.apply_to_lottery(over_limit["id"], round_id)
    assert applied["state"] == "APPLIED", applied

    fixtures.set_clock("2026-08-20T00:00:00Z", headers=program_admin)
    refused = api.draw_lottery(round_id, headers=program_admin)
    validate_error(refused, ApiErrorId.ERR_EMPTY_ELIGIBLE_POOL.value)

    pending = validate_success(api.get_lottery_event(round_id, headers=program_admin))
    assert pending["state"] == "PENDING", pending
    assert pending["selected_household_ids"] == [], pending
    assert pending["waitlisted_household_ids"] == [], pending
    assert (
        validate_success(api.get_household(over_limit["id"], headers=program_admin))["state"]
        == "APPLIED"
    )


def test_a_redraw_after_one_selection_is_certified_is_refused(
    api, program_admin, compliance_officer
):
    """One certified selection in the round is enough to close the redraw, even though the other selection is merely SELECTED.

    PRD: "A `ProgramAdministrator` redraws only from `DRAWN`, supplying a `reason`, and only while no household in `selected_household_ids` has yet reached `CERTIFIED`; a redraw attempted after any selected household has been certified is refused with `ERR_REDRAW_AFTER_CERTIFICATION`."

    Design: Corner/validations/lottery_window_guards_reject_early_late_empty_and_post_certification_calls
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    ctx = _lottery_lane(api)
    round_id = ctx["round_two_units"]["id"]
    certified_household = ctx["under_limit_size_three"]
    selected_only = ctx["under_limit_size_two"]
    fixtures.set_clock("2026-08-10T00:00:00Z", headers=program_admin)
    fixtures.apply_to_lottery(certified_household["id"], round_id)
    fixtures.apply_to_lottery(selected_only["id"], round_id)
    fixtures.set_clock("2026-08-20T00:00:00Z", headers=program_admin)
    drawn = validate_success(api.draw_lottery(round_id, headers=program_admin))
    assert drawn["selected_household_ids"] == [
        certified_household["id"],
        selected_only["id"],
    ], drawn

    reserved, _ = validate_paginated(
        api.list_units(
            project_id=ctx["project"]["id"],
            occupant_household_id=certified_household["id"],
            headers=program_admin,
        )
    )
    assert len(reserved) == 1, reserved
    assert reserved[0]["unit_number"] == "LT-101", reserved
    certification = fixtures.certify_income(
        certified_household["id"],
        reserved[0]["id"],
        certified_income_cents=6000000,
        contract_rent_cents=140000,
        effective_date="2026-08-20",
        headers=compliance_officer,
    )
    assert certification["state"] == "CERTIFIED", certification
    assert (
        validate_success(api.get_household(selected_only["id"], headers=program_admin))["state"]
        == "SELECTED"
    )

    refused = api.redraw_lottery(round_id, "Preference audit reopened", headers=program_admin)
    validate_error(refused, ApiErrorId.ERR_REDRAW_AFTER_CERTIFICATION.value)

    intact = validate_success(api.get_lottery_event(round_id, headers=program_admin))
    assert intact["state"] == "DRAWN", intact
    assert intact["round_seq"] == 1, intact
    assert intact["selected_household_ids"] == [
        certified_household["id"],
        selected_only["id"],
    ], intact
    survivor = validate_success(
        api.get_certification(certification["id"], headers=compliance_officer)
    )
    assert survivor["state"] == "CERTIFIED", survivor


# =============================================================================
# Certification and recertification: eligibility, terms and predecessor state
# =============================================================================
def _recert_rise(api):
    """One rental unit and one restricted ownership unit, plus three households."""
    fixtures.bootstrap_program()
    project, agreement = _recorded_r2_project("Recert Rise", "DOC-RC-0001")
    rental = fixtures.add_unit(
        project["id"],
        agreement["id"],
        unit_number="RC-101",
        bedrooms=2,
        sqft=900,
        market_comparable_sqft=1000,
        tenure="RENTAL",
        affordability_level_bps=5000,
    )
    ownership = fixtures.add_unit(
        project["id"],
        agreement["id"],
        unit_number="RC-201",
        bedrooms=2,
        sqft=900,
        market_comparable_sqft=1000,
        tenure="OWNERSHIP",
        affordability_level_bps=5000,
    )
    ownership = fixtures.record_restriction(
        ownership["id"], original_purchase_price_cents=32500000, recorded_at="2026-08-01"
    )
    return {
        "project": project,
        "rental_unit": rental,
        "ownership_unit": ownership,
        "eligible_size_three": fixtures.register_household(
            applicant_name="Hana Iyer", household_size=3, gross_annual_income_cents=6000000
        ),
        "over_limit_size_three": fixtures.register_household(
            applicant_name="Kira Baros", household_size=3, gross_annual_income_cents=6400000
        ),
        "eligible_size_two": fixtures.register_household(
            applicant_name="Ines Novak", household_size=2, gross_annual_income_cents=5000000
        ),
    }


def test_certifying_a_household_over_its_own_income_limit_is_refused(
    api, program_admin, compliance_officer
):
    """The limit is the one for the household's own size, so 6400000 fails where 6000000 passes on the same unit.

    PRD: "Eligibility is then tested against the pinned limit: the `certified_income_cents` must be at most `income_limit_cents`, and if the unit's `occupancy_status` is `RESERVED` the household being certified must be the very household recorded as that unit's `occupant_household_id` — certifying somebody else into a unit the lottery reserved is refused."

    Design: Corner/validations/certification_and_recertification_guards_over_eligibility_and_terms
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    ctx = _recert_rise(api)
    unit = ctx["rental_unit"]

    refused = api.create_certification(
        factories.create_certification_payload(
            ctx["over_limit_size_three"]["id"],
            unit["id"],
            certified_income_cents=6400000,
            contract_rent_cents=140000,
            effective_date="2026-08-01",
        ),
        headers=compliance_officer,
    )
    validate_error(refused, ApiErrorId.ERR_HOUSEHOLD_NOT_ELIGIBLE.value)

    untouched = validate_success(api.get_unit(unit["id"], headers=compliance_officer))
    assert_unit_dimensions(untouched, occupancy_status="PLANNED")
    assert untouched["occupant_household_id"] is None, untouched

    accepted = validate_success(
        api.create_certification(
            factories.create_certification_payload(
                ctx["eligible_size_three"]["id"],
                unit["id"],
                certified_income_cents=6000000,
                contract_rent_cents=140000,
                effective_date="2026-08-01",
            ),
            headers=compliance_officer,
        ),
        201,
    )
    assert accepted["state"] == "CERTIFIED", accepted
    assert accepted["income_limit_cents"] == INCOME_LIMIT_SIZE_3_AT_5000_BPS, accepted
    assert accepted["expires_at"] == "2027-08-01", accepted


def test_recertifying_before_the_renewal_window_opens_is_refused(
    api, program_admin, compliance_officer
):
    """The renewal window opens thirty days before the term ends, so a renewal on day one of the term is refused.

    PRD: "And the renewal window must be open — the current logical instant must be at or after the predecessor's `expires_at` minus 30 days; earlier is refused with `ERR_RECERT_WINDOW_NOT_OPEN`."

    Design: Corner/validations/certification_and_recertification_guards_over_eligibility_and_terms
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    ctx = _recert_rise(api)
    certification = fixtures.certify_income(
        ctx["eligible_size_three"]["id"],
        ctx["rental_unit"]["id"],
        certified_income_cents=6000000,
        contract_rent_cents=140000,
        effective_date="2026-08-01",
    )
    assert certification["expires_at"] == "2027-08-01", certification

    refused = api.recertify(certification["id"], 6100000, 141000, headers=compliance_officer)
    validate_error(refused, ApiErrorId.ERR_RECERT_WINDOW_NOT_OPEN.value)

    predecessor = validate_success(
        api.get_certification(certification["id"], headers=compliance_officer)
    )
    assert predecessor["state"] == "CERTIFIED", predecessor
    assert predecessor["certified_income_cents"] == 6000000, predecessor
    rows, meta = validate_paginated(
        api.list_certifications(unit_id=ctx["rental_unit"]["id"], headers=compliance_officer)
    )
    assert meta["total_count"] == 1, rows


def test_recertifying_an_ownership_certification_is_refused(
    api, program_admin, compliance_officer
):
    """An ownership certification has no term, so it falls through the window rule and is caught by the not-applicable rule.

    PRD: "It must have a non-null `expires_at`: an `OWNERSHIP` certification carries no term and never recertifies, which is refused with `ERR_RECERT_NOT_APPLICABLE`."

    Design: Corner/validations/certification_and_recertification_guards_over_eligibility_and_terms
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    ctx = _recert_rise(api)
    certification = fixtures.certify_income(
        ctx["eligible_size_two"]["id"],
        ctx["ownership_unit"]["id"],
        certified_income_cents=5000000,
        contract_rent_cents=0,
        effective_date="2026-08-01",
    )
    assert certification["expires_at"] is None, certification

    refused = api.recertify(certification["id"], 5100000, 0, headers=compliance_officer)
    validate_error(refused, ApiErrorId.ERR_RECERT_NOT_APPLICABLE.value)

    unchanged = validate_success(
        api.get_certification(certification["id"], headers=compliance_officer)
    )
    assert unchanged["state"] == "CERTIFIED", unchanged
    assert unchanged["certified_income_cents"] == 5000000, unchanged


def test_recertifying_a_superseded_predecessor_is_refused(
    api, program_admin, compliance_officer
):
    """A successful renewal supersedes the predecessor, so the very id that worked a moment earlier now fails on its own state.

    PRD: "The predecessor must be in `state` `CERTIFIED`, else `ERR_CERTIFICATION_NOT_ACTIVE`."

    Design: Corner/validations/certification_and_recertification_guards_over_eligibility_and_terms
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    ctx = _recert_rise(api)
    certification = fixtures.certify_income(
        ctx["eligible_size_three"]["id"],
        ctx["rental_unit"]["id"],
        certified_income_cents=6000000,
        contract_rent_cents=140000,
        effective_date="2026-08-01",
    )
    fixtures.set_clock("2027-07-15T00:00:00Z", headers=program_admin)
    successor = validate_success(
        api.recertify(certification["id"], 6200000, 141000, headers=compliance_officer),
        201,
    )
    assert successor["is_recertification"] is True, successor
    assert successor["effective_date"] == "2027-08-02", successor
    assert successor["state"] == "CERTIFIED", successor
    superseded = validate_success(
        api.get_certification(certification["id"], headers=compliance_officer)
    )
    assert superseded["state"] == "SUPERSEDED", superseded

    refused = api.recertify(certification["id"], 6300000, 142000, headers=compliance_officer)
    validate_error(refused, ApiErrorId.ERR_CERTIFICATION_NOT_ACTIVE.value)

    unit = validate_success(api.get_unit(ctx["rental_unit"]["id"], headers=compliance_officer))
    assert unit["current_rent_cents"] == 141000, unit
    rows, meta = validate_paginated(
        api.list_certifications(unit_id=unit["id"], headers=compliance_officer)
    )
    assert meta["total_count"] == 2, rows


# =============================================================================
# Monitoring: the annual key is per unit, and the cure gate is arithmetic
# =============================================================================
def _monitor_mews(api):
    """Two occupied rental units, each with max_allowed_rent_cents pinned at 143872."""
    fixtures.bootstrap_program()
    project, agreement = _recorded_r2_project("Monitor Mews", "DOC-MN-0001")
    specs = {
        "bedrooms": 2,
        "sqft": 900,
        "market_comparable_sqft": 1000,
        "tenure": "RENTAL",
        "affordability_level_bps": 5000,
    }
    first = fixtures.add_unit(project["id"], agreement["id"], unit_number="MN-101", **specs)
    second = fixtures.add_unit(project["id"], agreement["id"], unit_number="MN-102", **specs)
    tenants = []
    for name, unit in (("Hana Iyer", first), ("Jonas Wolf", second)):
        household = fixtures.register_household(
            applicant_name=name, household_size=3, gross_annual_income_cents=6000000
        )
        fixtures.certify_income(
            household["id"],
            unit["id"],
            certified_income_cents=6000000,
            contract_rent_cents=140000,
            effective_date="2026-08-01",
        )
        tenants.append(household)
    first = fixtures.live_unit(first["id"])
    second = fixtures.live_unit(second["id"])
    assert first["max_allowed_rent_cents"] == MAX_ALLOWED_RENT_2BR_AT_5000_BPS, first
    assert second["max_allowed_rent_cents"] == MAX_ALLOWED_RENT_2BR_AT_5000_BPS, second
    fixtures.set_clock("2027-03-01T00:00:00Z")
    return {"project": project, "first_unit": first, "second_unit": second, "tenants": tenants}


def test_a_second_review_for_the_same_year_on_one_unit_is_refused(
    api, program_admin, compliance_officer
):
    """The annual key is (unit_id, review_year), so 2027 is spent on MN-101 and still free on MN-102.

    PRD: "Only one review may exist per `review_year` per `unit_id`; a second is refused with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/validations/monitoring_guards_reject_a_repeat_year_and_an_insufficient_cure
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    ctx = _monitor_mews(api)
    first_review = validate_success(
        api.create_monitoring_review(
            factories.create_monitoring_review_payload(
                ctx["first_unit"]["id"],
                review_year=2027,
                reported_rent_cents=165000,
                reported_income_cents=6000000,
                occupancy_verified=True,
            ),
            headers=compliance_officer,
        ),
        201,
    )

    refused = api.create_monitoring_review(
        factories.create_monitoring_review_payload(
            ctx["first_unit"]["id"],
            review_year=2027,
            reported_rent_cents=143000,
            reported_income_cents=6000000,
            occupancy_verified=True,
        ),
        headers=compliance_officer,
    )
    validate_error(refused, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)

    untouched = validate_success(
        api.get_monitoring_review(first_review["id"], headers=compliance_officer)
    )
    assert untouched["reported_rent_cents"] == 165000, untouched
    rows, meta = validate_paginated(
        api.list_monitoring_reviews(unit_id=ctx["first_unit"]["id"], headers=compliance_officer)
    )
    assert meta["total_count"] == 1, rows

    sibling = validate_success(
        api.create_monitoring_review(
            factories.create_monitoring_review_payload(
                ctx["second_unit"]["id"],
                review_year=2027,
                reported_rent_cents=165000,
                reported_income_cents=6000000,
                occupancy_verified=True,
            ),
            headers=compliance_officer,
        ),
        201,
    )
    assert sibling["review_year"] == 2027, sibling
    assert sibling["unit_id"] == ctx["second_unit"]["id"], sibling


def test_clearing_a_cure_that_still_overcharges_is_refused(
    api, program_admin, compliance_officer, second_compliance_officer, developer
):
    """A cure of 150000 against a 143872 ceiling is no cure, and the second officer clears the segregation rung so the arithmetic rung is what fires.

    PRD: "Two guards apply, in this order: the acting `X-User-ID` must differ from the review's `issued_by_user_id`, since the officer who issued a finding may not also clear it, refused with `ERR_SEGREGATION_OF_DUTIES`; and the submitted `corrected_rent_cents` must be at most the unit's `max_allowed_rent_cents`, because a cure that still overcharges is no cure, refused with `ERR_CURE_INSUFFICIENT`."

    Design: Corner/validations/monitoring_guards_reject_a_repeat_year_and_an_insufficient_cure
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    ctx = _monitor_mews(api)
    review = validate_success(
        api.create_monitoring_review(
            factories.create_monitoring_review_payload(
                ctx["first_unit"]["id"],
                review_year=2027,
                reported_rent_cents=165000,
                reported_income_cents=6000000,
                occupancy_verified=True,
            ),
            headers=compliance_officer,
        ),
        201,
    )
    assert review["state"] == "FINDING_ISSUED", review
    assert review["issued_by_user_id"] == compliance_officer["X-User-ID"], review
    submitted = validate_success(api.submit_cure(review["id"], 150000, headers=developer))
    assert submitted["state"] == "CURE_SUBMITTED", submitted
    assert submitted["corrected_rent_cents"] == 150000, submitted
    penalty_before = submitted["penalty_final_cents"]

    refused = api.clear_cure(review["id"], headers=second_compliance_officer)
    validate_error(refused, ApiErrorId.ERR_CURE_INSUFFICIENT.value)

    still_submitted = validate_success(
        api.get_monitoring_review(review["id"], headers=compliance_officer)
    )
    assert still_submitted["state"] == "CURE_SUBMITTED", still_submitted
    assert still_submitted["penalty_final_cents"] == penalty_before, still_submitted
    unit = validate_success(api.get_unit(ctx["first_unit"]["id"], headers=compliance_officer))
    assert_unit_dimensions(unit, compliance_status="CURE_PENDING")
    assert unit["max_allowed_rent_cents"] == MAX_ALLOWED_RENT_2BR_AT_5000_BPS, unit


def test_a_cure_exactly_at_the_ceiling_clears(
    api, program_admin, compliance_officer, second_compliance_officer, developer
):
    """A corrected rent of exactly the ceiling satisfies the rule, pinning the comparison as at-most rather than below.

    PRD: "A cure being cleared actually fixes the violation, meaning `corrected_rent_cents` is at most the unit's `max_allowed_rent_cents`, else `ERR_CURE_INSUFFICIENT`."

    Design: Corner/validations/monitoring_guards_reject_a_repeat_year_and_an_insufficient_cure
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT, headers=program_admin)
    ctx = _monitor_mews(api)
    review = validate_success(
        api.create_monitoring_review(
            factories.create_monitoring_review_payload(
                ctx["second_unit"]["id"],
                review_year=2027,
                reported_rent_cents=165000,
                reported_income_cents=6000000,
                occupancy_verified=True,
            ),
            headers=compliance_officer,
        ),
        201,
    )
    validate_success(
        api.submit_cure(review["id"], MAX_ALLOWED_RENT_2BR_AT_5000_BPS, headers=developer)
    )

    cleared = validate_success(api.clear_cure(review["id"], headers=second_compliance_officer))
    assert cleared["state"] == "CURED", cleared
    assert cleared["corrected_rent_cents"] == MAX_ALLOWED_RENT_2BR_AT_5000_BPS, cleared

    unit = validate_success(api.get_unit(ctx["second_unit"]["id"], headers=compliance_officer))
    assert_unit_dimensions(unit, compliance_status="COMPLIANT")
