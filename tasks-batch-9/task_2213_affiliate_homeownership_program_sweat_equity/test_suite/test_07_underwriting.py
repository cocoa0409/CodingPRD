"""Origination and the pinned affordability forward pass."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.test_users import ADMIN, OFFICER


def test_the_structure_is_one_forward_pass_over_the_pinned_snapshots(api):
    """Every intermediate of the pass lands on its documented figure.

    "Step two: escrow is assembled from two separately rounded components. The
    monthly tax component is the pinned `appraised_value_cents` multiplied by an
    annual tax rate of 1.25 percent and divided by 12, rounded half-up to whole
    cents. The annual hazard insurance premium is the pinned appraised value
    multiplied by 0.35 percent, rounded half-up to whole cents, and then raised to
    a floor of 60,000 cents ... Step three: the maximum total housing payment the
    household can carry is 30 percent of monthly gross income, floored to whole
    cents. Step four: `affordable_pi_payment_cents` is that maximum less
    `escrow_monthly_cents`."

    On 3,000,000 verified income and a 15,000,000 appraisal: gross 250,000, escrow
    15,625 + 5,000 = 20,625, budget 75,000, payment 54,375.

    Design: Difficulty/combinatorial_formula/affordable_structure_single_forward_pass_term_tier
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    household = X.setup_selected_household(api, program["id"])["household"]
    application = X.setup_draft_application(api, household["id"], site["id"])

    underwritten = validate_success(api.submit_underwriting(application["id"], headers=OFFICER))

    assert underwritten["status"] == C.APP_UNDERWRITING
    assert underwritten["income_basis_annual_cents"] == 3_000_000
    assert underwritten["appraised_value_cents"] == 15_000_000
    assert underwritten["escrow_monthly_cents"] == C.PINNED_ESCROW_MONTHLY_CENTS
    assert underwritten["affordable_pi_payment_cents"] == C.PINNED_AFFORDABLE_PI_CENTS
    assert underwritten["lien_status"] == C.LIEN_NONE


def test_the_term_tier_is_chosen_from_the_provisional_principal_and_never_re_derived(api):
    """The circular-looking dependency is resolved in exactly one direction.

    "Step five: a provisional principal is formed as `affordable_pi_payment_cents`
    multiplied by 360, and it is used for nothing except picking the term tier.
    Step six: `term_months` is 240 when that provisional principal reaches at least
    90 percent of the pinned appraised value ... Step seven:
    `first_mortgage_principal_cents` is the lesser of `affordable_pi_payment_cents`
    multiplied by the chosen `term_months` and the appraised value — the term is
    *not* re-derived from this figure."

    The provisional 19,575,000 clears 13,500,000, so the term is 240 and the
    principal is 13,050,000; an implementation that iterated back from that
    principal would report a 300-month term and no subsidy at all.

    Design: Difficulty/combinatorial_formula/affordable_structure_single_forward_pass_term_tier
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    household = X.setup_selected_household(api, program["id"])["household"]
    application = X.setup_draft_application(api, household["id"], site["id"])

    underwritten = validate_success(api.submit_underwriting(application["id"], headers=OFFICER))

    assert underwritten["term_months"] == C.PINNED_TERM_MONTHS
    assert underwritten["first_mortgage_principal_cents"] == C.PINNED_FIRST_MORTGAGE_CENTS
    assert underwritten["silent_second_amount_cents"] == C.PINNED_SILENT_SECOND_CENTS


def test_returning_a_file_to_draft_unpins_every_computed_figure(api):
    """The revision cycle empties the structure it had persisted.

    "Returning `UNDERWRITING → DRAFT` with a `return_reason` clears
    `appraised_value_cents`, `income_basis_annual_cents`, `escrow_monthly_cents`,
    `affordable_pi_payment_cents`, `term_months`, `first_mortgage_principal_cents`,
    and `silent_second_amount_cents` all back to null, unpinning everything."

    Design: Difficulty/non_linear_state_machine/mortgage_underwriting_revision_cycle_unpins_and_repins
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    household = X.setup_selected_household(api, program["id"])["household"]
    application = X.setup_underwritten_application(api, household["id"], site["id"])
    assert application["silent_second_amount_cents"] == C.PINNED_SILENT_SECOND_CENTS

    returned = validate_success(
        api.return_application_to_draft(
            application["id"],
            F.return_to_draft_payload(return_reason="Escrow quote must be re-sourced"),
            headers=OFFICER,
        )
    )

    assert returned["status"] == C.APP_DRAFT
    assert returned["appraised_value_cents"] is None
    assert returned["income_basis_annual_cents"] is None
    assert returned["escrow_monthly_cents"] is None
    assert returned["affordable_pi_payment_cents"] is None
    assert returned["term_months"] is None
    assert returned["first_mortgage_principal_cents"] is None
    assert returned["silent_second_amount_cents"] is None
    assert returned["lien_status"] == C.LIEN_NONE


def test_a_second_submission_repins_the_same_structure_from_current_values(api):
    """The cycle is traversable, and the second pass is a genuine recomputation.

    "The `DRAFT ↔ UNDERWRITING` revision cycle may repeat, and a re-appraisal of
    the site between loops genuinely changes the structure." Nothing was
    re-appraised here, so the second pass must reproduce the first pass exactly —
    which is only true if it re-ran rather than restored a cached copy.

    Design: Difficulty/non_linear_state_machine/mortgage_underwriting_revision_cycle_unpins_and_repins
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    household = X.setup_selected_household(api, program["id"])["household"]
    application = X.setup_underwritten_application(api, household["id"], site["id"])
    validate_success(
        api.return_application_to_draft(
            application["id"],
            F.return_to_draft_payload(return_reason="Escrow quote must be re-sourced"),
            headers=OFFICER,
        )
    )

    repinned = validate_success(api.submit_underwriting(application["id"], headers=OFFICER))

    assert repinned["status"] == C.APP_UNDERWRITING
    assert repinned["income_basis_annual_cents"] == 3_000_000
    assert repinned["appraised_value_cents"] == 15_000_000
    assert repinned["escrow_monthly_cents"] == C.PINNED_ESCROW_MONTHLY_CENTS
    assert repinned["affordable_pi_payment_cents"] == C.PINNED_AFFORDABLE_PI_CENTS
    assert repinned["term_months"] == C.PINNED_TERM_MONTHS
    assert repinned["first_mortgage_principal_cents"] == C.PINNED_FIRST_MORTGAGE_CENTS
    assert repinned["silent_second_amount_cents"] == C.PINNED_SILENT_SECOND_CENTS


def test_the_insurance_floor_and_the_appraisal_cap_erase_the_subsidy(api):
    """Two constants bite at once and the silent second collapses to zero.

    The rate alone would price this home's insurance at 52,500 a year, but the
    premium is "raised to a floor of 60,000 cents — every home carries at least a
    six-hundred-dollar annual premium", making the monthly component 5,000 rather
    than 4,375. At the other end, "`first_mortgage_principal_cents` is the lesser
    of `affordable_pi_payment_cents` multiplied by the chosen `term_months` and the
    appraised value", so a 16,650,000 note is clamped to 15,000,000 and "`if that
    difference is negative it is recorded as 0`".

    Design: Corner/calculations/insurance_annual_floor_and_appraisal_cap_squeeze_the_silent_second
    """
    program = X.setup_program(api)
    site = X.setup_site(api, program["id"])
    X.advance_site(api, site["id"], C.STEP_TITLE)
    X.advance_site(api, site["id"], C.STEP_ENVIRONMENTAL)
    X.advance_site(api, site["id"], C.STEP_UTILITIES)
    household = X.setup_selected_household(
        api,
        program["id"],
        household_overrides={"self_reported_annual_income_cents": 4_000_000},
        screen_overrides={"verified_annual_income_cents": 3_600_000},
    )["household"]
    application = X.setup_draft_application(api, household["id"], site["id"])

    underwritten = validate_success(api.submit_underwriting(application["id"], headers=OFFICER))

    assert underwritten["status"] == C.APP_UNDERWRITING
    assert underwritten["income_basis_annual_cents"] == 3_600_000
    assert underwritten["appraised_value_cents"] == 15_000_000
    # 15,625 of tax plus 5,000 of floored insurance; a rate-only read would give 20,000.
    assert underwritten["escrow_monthly_cents"] == 20_625
    assert underwritten["affordable_pi_payment_cents"] == 69_375
    assert underwritten["term_months"] == 240
    assert underwritten["first_mortgage_principal_cents"] == 15_000_000
    assert underwritten["silent_second_amount_cents"] == 0


def test_the_structure_preview_predicts_the_underwriting_without_writing(api):
    """A pure read that runs the whole pass.

    "For officers who want to see the arithmetic before committing to it, a
    read-only preview returns what the pinned snapshots would produce step by step
    — `monthly_gross_cents`, `tax_monthly_cents`, `insurance_annual_cents`,
    `insurance_monthly_cents`, `escrow_monthly_cents`, `max_total_payment_cents`,
    `affordable_pi_payment_cents`, `provisional_principal`, `term_months`,
    `first_mortgage_principal_cents`, and `silent_second_amount_cents` — without
    writing a single field."

    Design: Corner/endpoints/structure_preview_is_a_pure_read_that_predicts_the_underwriting
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    household = X.setup_selected_household(api, program["id"])["household"]
    application = X.setup_draft_application(api, household["id"], site["id"])
    version_before = application["version"]

    preview = validate_success(api.get_structure_preview(application["id"], headers=OFFICER))
    assert preview["escrow_monthly_cents"] == 20_625
    assert preview["affordable_pi_payment_cents"] == 54_375
    assert preview["term_months"] == 240
    assert preview["first_mortgage_principal_cents"] == 13_050_000
    assert preview["silent_second_amount_cents"] == 1_950_000

    untouched = validate_success(api.get_application(application["id"], headers=OFFICER))
    assert untouched["status"] == C.APP_DRAFT
    assert untouched["silent_second_amount_cents"] is None
    assert untouched["version"] == version_before

    underwritten = validate_success(api.submit_underwriting(application["id"], headers=OFFICER))
    assert underwritten["status"] == C.APP_UNDERWRITING
    assert underwritten["escrow_monthly_cents"] == 20_625
    assert underwritten["affordable_pi_payment_cents"] == 54_375
    assert underwritten["term_months"] == 240
    assert underwritten["first_mortgage_principal_cents"] == 13_050_000
    assert underwritten["silent_second_amount_cents"] == 1_950_000

    # The same snapshots, read by a different role, give the same answer.
    after = validate_success(api.get_structure_preview(application["id"], headers=ADMIN))
    assert after["escrow_monthly_cents"] == 20_625
    assert after["affordable_pi_payment_cents"] == 54_375
    assert after["term_months"] == 240
    assert after["first_mortgage_principal_cents"] == 13_050_000
    assert after["silent_second_amount_cents"] == 1_950_000


def test_origination_needs_a_selected_household_and_an_unclaimed_site(api):
    """Two different parents can block the same create.

    "The household's `selection_status` must be `SELECTED` or `PARTNERSHIP_ACTIVE`,
    or the create is refused with `ERR_HOUSEHOLD_NOT_SELECTED`. The named build
    site must be either unassigned or already assigned to this same household; a
    site whose `assigned_household_id` names a different household is refused with
    `ERR_SITE_ALREADY_ASSIGNED`."

    Design: Corner/validations/underwriting_needs_a_selected_household_and_an_unclaimed_site
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    household_a = X.setup_selected_household(api, program["id"])["household"]
    X.setup_draft_application(api, household_a["id"], site["id"])
    household_b = X.setup_selected_household(
        api, program["id"], household_overrides={"household_name": "Bell"}
    )["household"]
    household_d = X.setup_household(
        api,
        program["id"],
        household_name="Doss",
        household_size=2,
        habitability_deficiency_count=1,
        self_reported_annual_income_cents=3_000_000,
        self_reported_housing_cost_cents=100_000,
        monthly_debt_payment_cents=20_000,
        credit_score=620,
        on_time_housing_payment_months=12,
    )

    validate_error(
        api.create_application(
            F.application_payload(household_d["id"], site["id"], X.household_version(api, household_d["id"])),
            headers=OFFICER,
        ),
        E.ERR_HOUSEHOLD_NOT_SELECTED,
        409,
    )
    validate_error(
        api.create_application(
            F.application_payload(household_b["id"], site["id"], X.household_version(api, household_b["id"])),
            headers=OFFICER,
        ),
        E.ERR_SITE_ALREADY_ASSIGNED,
        409,
    )

    reread_site = validate_success(api.get_build_site(site["id"], headers=ADMIN))
    assert reread_site["assigned_household_id"] == household_a["id"]

    rows, meta = validate_paginated(api.list_applications({"build_site_id": site["id"]}, headers=OFFICER))
    assert meta["total_count"] == 1
    assert rows[0]["status"] == C.APP_DRAFT


def test_an_escrow_larger_than_the_housing_budget_leaves_no_structure(api):
    """The refusal is arithmetic: step four goes negative and the pass aborts.

    "Step four: `affordable_pi_payment_cents` is that maximum less
    `escrow_monthly_cents`; if the result is zero or negative the household has no
    structure at all and the submission is refused with
    `ERR_NO_AFFORDABLE_STRUCTURE`."

    Gross 150,000 gives a 45,000 budget while a 40,000,000 appraisal prices escrow
    at 41,667 plus 11,667, so the payment would be negative 8,334.

    Design: Corner/validations/escrow_can_consume_the_whole_housing_budget_leaving_no_structure
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(
        api,
        program["id"],
        parcel_number="P-2001",
        street_address="40 Summit Ave",
        acquisition_cost_cents=9_000_000,
        appraised_value_cents=40_000_000,
    )
    household = X.setup_selected_household(
        api,
        program["id"],
        household_overrides={
            "household_name": "Xiong",
            "self_reported_annual_income_cents": 1_800_000,
            "self_reported_housing_cost_cents": 90_000,
            "monthly_debt_payment_cents": 10_000,
        },
        screen_overrides={
            "verified_annual_income_cents": 1_800_000,
            "verified_housing_cost_cents": 90_000,
        },
    )["household"]
    application = X.setup_draft_application(
        api, household["id"], site["id"], term_months=C.TERM_360
    )

    validate_error(
        api.submit_underwriting(application["id"], headers=OFFICER), E.ERR_NO_AFFORDABLE_STRUCTURE, 422
    )

    reread = validate_success(api.get_application(application["id"], headers=OFFICER))
    assert reread["status"] == C.APP_DRAFT
    assert reread["escrow_monthly_cents"] is None
    assert reread["affordable_pi_payment_cents"] is None
    assert reread["first_mortgage_principal_cents"] is None
    assert reread["silent_second_amount_cents"] is None
    assert reread["term_months"] == C.TERM_360

    reread_program = validate_success(api.get_program(program["id"], headers=ADMIN))
    assert reread_program["subsidy_committed_cents"] == 0
    assert reread_program["subsidy_available_cents"] == 5_000_000
