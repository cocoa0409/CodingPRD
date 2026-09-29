"""Field-level and cross-field guards, satisfied and violated.

A classification that clears both of its preconditions, an ineligible reviewer, an
aggregate allocation that overflows the portfolio, an election that has no window to
move through, and a path id that is resolved before a body id.
"""

from test_helpers import (
    ApiErrorId,
    assertions,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_success,
)

UNKNOWN_APPLICATION_ID = "55555555-5555-5555-5555-555555555555"
UNKNOWN_REVIEWER_ID = "66666666-6666-6666-6666-666666666666"


def test_an_eligible_in_period_cost_moves_onto_the_qualified_side(api):
    """Both preconditions hold, so the classification is accepted.

    The item's category is not one of the statutorily excluded ones and its incurred
    date falls inside the half-open window, so moving it from unclassified to qualified
    is accepted. Its exclusion reason stays NONE, the operation counts as one
    reclassification, and the project's qualified total picks up the full 30000000.

    PRD: "Moving an item onto the qualified side has two hard preconditions: its `category` must not be one of the statutorily excluded categories `ACQUISITION`, `ENLARGEMENT`, `SITE_WORK`, `PERSONAL_PROPERTY`, `FFE`, or `LANDSCAPING` — those can never be qualified rehabilitation expenditures, and an attempt is refused with `ERR_NONQUALIFIED_CATEGORY` — and its `in_measuring_period` must be true, else `ERR_OUTSIDE_MEASURING_PERIOD`."
    PRD: "Reclassification is a first-class operation, and each successful one raises `reclassification_count` by one."
    PRD: "Moving an item to `QRE` sets `exclusion_reason` back to `NONE`; moving it to `NON_QRE` sets `exclusion_reason` to the supplied value when one is given, and otherwise derives it — `NONQUALIFIED_CATEGORY` for a statutorily excluded category, `OUTSIDE_MEASURING_PERIOD` when `in_measuring_period` is false, `DEVELOPER_FEE_CAP` for the disallowed slice of a developer fee, and `REVIEWER_DISALLOWED` for an auditor's disallowance."

    Design: Corner/validations/cost_classification_satisfaction_passes_for_eligible_in_period_cost
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api,
        cast,
        structure_type="SINGLE_TIER",
        adjusted_basis_cents=60_000_000,
        measuring_period_months=24,
        measuring_period_start_date="2026-09-01",
    )
    item = fixtures.add_cost(
        api,
        cast,
        project["id"],
        category="HARD_CONSTRUCTION",
        amount_cents=30_000_000,
        incurred_date="2027-05-01",
    )
    assertions.assert_fields(
        item, "unclassified item", classification="PENDING_CLASSIFICATION"
    )

    classified = validate_success(
        api.classify_cost_line_item(
            item["id"], cast.developer_headers, classification="QRE"
        )
    )

    assertions.assert_fields(
        classified,
        "classified item",
        classification="QRE",
        exclusion_reason="NONE",
        reclassification_count=1,
        in_measuring_period=True,
    )
    assertions.assert_ledger(
        fixtures.read_project(api, cast, project["id"]),
        qre_total_final_cents=30_000_000,
    )


def test_a_suspended_reviewer_cannot_be_assigned_at_submission(api):
    """The named reviewer must be credentialled, so a suspended one is refused.

    The only state office reviewer available was registered as SUSPENDED. Naming that
    reviewer at submission is refused on eligibility grounds, and the application never
    leaves DRAFT: no reviewer and no submission stamp are written onto it.

    PRD: "The named reviewer must exist, must have `agency` of `SHPO`, and must have `credential_status` of `ACTIVE`; a suspended or wrong-agency reviewer is refused with `ERR_REVIEWER_NOT_ELIGIBLE`."
    PRD: "A reviewer carries a `full_name` of 1 to 80 characters, an `agency` of either `SHPO` or `NPS`, a `state_code` giving the two-letter uppercase USPS code of the reviewer's office, and a `credential_status` that defaults to `ACTIVE` and may alternatively be `SUSPENDED`."

    Design: Corner/validations/suspended_shpo_reviewer_assignment_rejected
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    developer = fixtures.create_developer(api)
    suspended = fixtures.create_reviewer(api, "SHPO", credential_status="SUSPENDED")
    stored_property = fixtures.create_property(api)
    headers = fixtures.make_developer_headers(developer["id"])
    project = validate_success(
        api.create_project(
            headers,
            **factories.project_payload(
                developer["id"],
                stored_property["id"],
                structure_type="SINGLE_TIER",
                adjusted_basis_cents=60_000_000,
            ),
        ),
        201,
    )
    application = validate_success(
        api.create_part_application(
            headers,
            **factories.part_application_payload(
                project["id"], 1, project["version"]
            ),
        ),
        201,
    )

    response = api.submit_part_application(
        application["id"], headers, shpo_reviewer_id=suspended["id"]
    )

    validate_error(response, ApiErrorId.REVIEWER_NOT_ELIGIBLE.value, 422)
    assertions.assert_fields(
        get_success_data(api.get_reviewer(suspended["id"], fixtures.ADMIN)),
        "suspended reviewer",
        credential_status="SUSPENDED",
    )
    assertions.assert_fields(
        get_success_data(api.get_part_application(application["id"], headers)),
        "application after the refused submission",
        status="DRAFT",
        shpo_reviewer_id=None,
        submitted_at=None,
    )


def test_an_admission_pushing_the_portfolio_past_one_hundred_percent_is_refused(api):
    """Sixty percent is already allocated, so a further fifty percent overflows.

    The first partner holds 60 percent of the credit and is fully admitted, scoring the
    base 10 with nothing added for a taxable C corporation, no lease term and an
    inapplicable election. Admitting a second partner at 50 percent would take the
    portfolio to 110 percent, so it is refused, the project keeps its single interest
    and its standing maximum score stays at that partner's 10.

    PRD: "Allocation is also policed in aggregate, because each interest can be individually valid while the portfolio is not: if admitting the interest would push the sum of `credit_allocation_pct` across the project's `ADMITTED` interests above one hundred percent, the admission is refused with `ERR_ALLOCATION_EXCEEDS_LIMIT`."
    PRD: "A successfully admitted interest has `status` of `ADMITTED`, `election_at` null, and `pass_through_election` of `PENDING` when its `kind` is `MASTER_LEASE_LESSEE` or `NOT_APPLICABLE` when it is `DIRECT_PARTNER`."
    PRD: "Every interest starts from a base risk of 10 points. Its `party_tax_status` adds points on a fixed scale: nothing for `TAXABLE_C_CORP`, 10 points for `PARTNERSHIP`, 35 points for `GOVERNMENTAL_UNIT`, and 45 points for `TAX_EXEMPT_ORG`."

    Design: Corner/validations/aggregate_allocation_over_one_hundred_percent_rejected
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="SINGLE_TIER", adjusted_basis_cents=60_000_000
    )
    first = fixtures.admit_direct_partner(
        api,
        cast,
        project["id"],
        party_legal_name="Riverbend Credit Corp",
        party_tax_status="TAXABLE_C_CORP",
        capital_committed_cents=40_000_000,
        credit_allocation_pct=60,
    )

    response = api.create_investor_interest(
        cast.developer_headers,
        **factories.investor_interest_payload(
            project["id"],
            kind="DIRECT_PARTNER",
            party_legal_name="Harbor Line Capital Inc",
            party_tax_status="TAXABLE_C_CORP",
            capital_committed_cents=20_000_000,
            credit_allocation_pct=50,
        ),
    )

    validate_error(response, ApiErrorId.ALLOCATION_EXCEEDS_LIMIT.value, 422)
    stored_first = validate_success(
        api.get_investor_interest(first["id"], cast.developer_headers)
    )
    assertions.assert_fields(
        stored_first,
        "admitted partner",
        status="ADMITTED",
        pass_through_election="NOT_APPLICABLE",
    )
    assert stored_first["credit_allocation_pct"] == 60, (
        "the admitted partner still holds sixty percent of the credit"
    )
    assertions.assert_risk_score(stored_first, 10, "ADMISSION")
    assertions.assert_ledger(
        fixtures.read_project(api, cast, project["id"]), max_investor_risk_score=10
    )
    assertions.assert_page(
        api.list_project_investor_interests(project["id"], cast.developer_headers),
        total_count=1,
    )


def test_a_direct_partner_has_no_pass_through_election_to_make(api):
    """The election field reads NOT_APPLICABLE, so the window is closed.

    On a single-tier project the interest is a direct partner whose election field is
    NOT_APPLICABLE rather than PENDING, so there is no election to move. The attempt is
    refused, and the interest is left with no election stamp, its admission score of 10
    and the version it was created with.

    PRD: "An election on an interest whose `pass_through_election` is already `ELECTED`, or on an interest of a `SINGLE_TIER` project where the field reads `NOT_APPLICABLE`, is refused with `ERR_ELECTION_WINDOW_CLOSED`."
    PRD: "The pass-through election is what lets a master tenant actually take the credit, and only an `InvestorAdmin` may make it."
    PRD: "`version` is an integer that starts at 1 on creation and increments by exactly one on every mutation of that row; it is the value optimistic concurrency control is checked against."

    Design: Corner/validations/pass_through_election_on_single_tier_interest_rejected
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="SINGLE_TIER", adjusted_basis_cents=60_000_000
    )
    partner = fixtures.admit_direct_partner(
        api,
        cast,
        project["id"],
        party_legal_name="Riverbend Credit Corp",
        party_tax_status="TAXABLE_C_CORP",
        credit_allocation_pct=100,
    )

    response = api.elect_pass_through(
        partner["id"], fixtures.investor_headers(partner)
    )

    validate_error(response, ApiErrorId.ELECTION_WINDOW_CLOSED.value, 422)
    stored = validate_success(
        api.get_investor_interest(partner["id"], cast.developer_headers)
    )
    assertions.assert_fields(
        stored,
        "direct partner after the refused election",
        pass_through_election="NOT_APPLICABLE",
        election_at=None,
        version=1,
    )
    assertions.assert_risk_score(stored, 10, "ADMISSION")


def test_the_unknown_application_in_the_path_beats_the_unknown_reviewer_in_the_body(api):
    """Both ids are dangling, and the one in the path is the one reported.

    The submission names an application that does not exist and a reviewer that does
    not exist either. Path existence is resolved first, so the refusal is the part
    application's own not-found error rather than the reviewer's.

    PRD: "Path existence resolves before any body reference, so an unknown path id always yields the path entity's 404 rather than a body reference error."
    PRD: "Every foreign key supplied in the body resolves to an existing row of its declared parent entity, else that parent entity's not-found error (404)."

    Design: Corner/validations/unknown_submit_path_id_reported_before_unknown_reviewer_body_id
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    developer = fixtures.create_developer(api)

    response = api.submit_part_application(
        UNKNOWN_APPLICATION_ID,
        fixtures.make_developer_headers(developer["id"]),
        shpo_reviewer_id=UNKNOWN_REVIEWER_ID,
    )

    error = validate_error(response, ApiErrorId.PART_APPLICATION_NOT_FOUND.value, 404)
    assert error["error_id"] != ApiErrorId.REVIEWER_NOT_FOUND.value, (
        "the body reference must not be the one reported"
    )
