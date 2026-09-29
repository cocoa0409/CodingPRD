"""
Queue B — §1.9 section ``rbac``.

The three access-control layers of PRD §2.1 kept apart: the 401 that answers an
undeclared role, the 403 that answers a declared role missing from an endpoint's
list, the 403 that answers a representative reaching outside its own institution,
and the separate 403 that answers the analyst who prepared the file trying to
decide it. Plus the positive case — the roles an endpoint does list both work.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import (
    ERR_INSTITUTION_SCOPE_VIOLATION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_fields,
    assert_id_order,
    assert_nulls,
    assert_pagination_meta,
)
from test_helpers.factories import (
    collateral_asset_payload,
    committee_decision_payload,
    giving_period_payload,
    governance_authorization_payload,
    institution_payload,
    pledge_campaign_payload,
)
from test_helpers.fixtures import (
    build_giving_period,
    build_institution,
    chain_through_assignment,
    refer_to_committee,
    reset_clock,
)
from test_helpers.test_users import (
    ANALYST_1,
    COMMITTEE_1,
    COMMITTEE_MEMBER,
    CREDIT_ANALYST,
    GOVERNANCE_OFFICER,
    LOAN_SERVICER,
    PLATFORM_ADMIN,
    make_committee_member_headers,
    make_credit_analyst_headers,
    make_institution_representative_headers,
    make_undeclared_role_headers,
)

# The recipes in this section file no endowment figure.
BORROWER = {"endowment_market_value_cents": None}

SECOND_BAPTIST = {
    "legal_name": "Second Baptist",
    "institution_type": "CONGREGATION",
    "denomination_code": "SBC",
    "requires_denominational_approval": False,
    "bylaws_borrowing_cap_cents": 100000000,
    "bylaws_quorum_pct": 0.5000,
    "community_program_count": 1,
    "endowment_market_value_cents": None,
}


def test_eight_well_formed_calls_are_refused_on_the_role_header_alone(api):
    """
    Five writes and two reads reserved to other roles, plus the clock, are each
    refused with the same 403 purely because of the acting role — and nothing they
    would have written exists afterwards, the clock included.

    PRD §2.1: "A syntactically valid request whose acting role is not listed among the authorised roles for the endpoint it targets is rejected with `ERR_UNAUTHORIZED` (HTTP 403) — for example, a `LoanServicer` attempting to waive a covenant breach, which is reserved to `CreditCommitteeMember`."
    PRD §2.10: "The acting role appears in the target endpoint's authorised-role list — `ERR_UNAUTHORIZED`, applied to every endpoint."
    PRD §2.5: "An operator holding `PlatformAdmin` may reposition it by submitting a `to_iso8601` instant to `POST /_clock/set_current_utc`, which answers with `current_utc` — the ISO 8601 UTC instant the clock now reports."
    PRD §2.5: "Four families of rule consult the clock, and all four are rebased the moment it moves: a collateral asset's `appraisal_age_days`, computed as whole days from `appraisal_date` to the current logical instant with any fractional day discarded; the giving-period selection window, which admits only periods whose `period_end` falls at or before the current instant; the expiry test on a governance packet's `expires_on`; and the lien-window comparisons that decide whether a proposed collateral occupation collides with a prior one."
    PRD §3.1: "Filing a period also reconciles its institution. `period_count` rises by 1, and `audited_period_count` rises by 1 as well when the new period's `source` is `AUDITED`."

    Design: Corner/rbac/roles_cannot_perform_other_roles_exclusive_operations
    """
    reset_clock(api)
    institution = build_institution(api, **BORROWER)

    refusals = [
        # Registering an institution is reserved to PlatformAdmin.
        api.create_institution(institution_payload(**SECOND_BAPTIST), CREDIT_ANALYST),
        # Opening a governance packet is the representative's own act.
        api.create_governance_authorization(
            governance_authorization_payload(institution["id"]), CREDIT_ANALYST
        ),
        # Launching a campaign likewise.
        api.create_pledge_campaign(
            pledge_campaign_payload(institution["id"]), CREDIT_ANALYST
        ),
        # Filing giving is for the analyst or the representative, not the officer.
        api.create_giving_period(
            giving_period_payload(institution["id"]), GOVERNANCE_OFFICER
        ),
        # Registering collateral is not a servicing act.
        api.create_collateral_asset(
            collateral_asset_payload(institution["id"]), LOAN_SERVICER
        ),
        # The denial is symmetric across reads.
        api.list_institutions(GOVERNANCE_OFFICER),
        api.list_governance_authorizations(LOAN_SERVICER),
        # And the clock is the admin's alone.
        api.set_clock("2027-01-01T00:00:00Z", LOAN_SERVICER),
    ]
    for response in refusals:
        validate_error(response, ERR_UNAUTHORIZED, 403)

    _, institution_meta = validate_paginated(api.list_institutions(PLATFORM_ADMIN))
    assert_pagination_meta(institution_meta, total_count=1)
    _, period_meta = validate_paginated(api.list_giving_periods(PLATFORM_ADMIN))
    assert_pagination_meta(period_meta, total_count=0)
    _, asset_meta = validate_paginated(api.list_collateral_assets(PLATFORM_ADMIN))
    assert_pagination_meta(asset_meta, total_count=0)

    reread = get_success_data(api.get_institution(institution["id"], PLATFORM_ADMIN))
    assert_fields(reread, period_count=0, audited_period_count=0)

    # The refused clock call left the logical instant at the startup value, so a
    # 2025-06-01 appraisal is still 426 whole days old.
    asset = get_success_data(
        api.create_collateral_asset(
            collateral_asset_payload(institution["id"]), CREDIT_ANALYST
        ),
        201,
    )
    assert_fields(asset, appraisal_age_days=426)


def test_an_undeclared_role_header_is_unauthenticated_before_it_can_be_unauthorized(api):
    """
    A role string outside the six declared ones answers 401 on both a read and a
    write, because position 1 outranks position 2; a declared role that the
    endpoint simply does not list answers 403 instead.

    PRD §2.1: "Six roles exist, spelled exactly as follows: `PlatformAdmin`, `InstitutionRepresentative`, `GovernanceOfficer`, `CreditAnalyst`, `CreditCommitteeMember` and `LoanServicer`."
    PRD §2.1: "A request missing either header, or presenting an `X-User-Role` value that is not one of those six strings, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.10: "Authentication headers present and `X-User-Role` one of the six declared roles — `ERR_UNAUTHENTICATED`, applied to every endpoint."
    PRD §2.10: "Validations are evaluated in the ascending order set out below; the **first** rule that a request violates determines the single error the response carries, and no later rule can mask an earlier one."

    Design: Corner/rbac/requests_carrying_an_undeclared_role_header_are_unauthenticated
    """
    reset_clock(api)
    institution = build_institution(api, **BORROWER)
    stranger = make_undeclared_role_headers()

    validate_error(
        api.get_institution(institution["id"], stranger), ERR_UNAUTHENTICATED, 401
    )
    validate_error(
        api.create_institution(institution_payload(**SECOND_BAPTIST), stranger),
        ERR_UNAUTHENTICATED,
        401,
    )
    # A declared role missing from this endpoint's list is the other failure.
    validate_error(api.list_institutions(GOVERNANCE_OFFICER), ERR_UNAUTHORIZED, 403)

    _, meta = validate_paginated(api.list_institutions(PLATFORM_ADMIN))
    assert_pagination_meta(meta, total_count=1)


def test_a_representative_is_walled_out_of_the_other_institutions_rows(api):
    """
    With two institutions on file, the first one's representative is refused the
    second one's row, the second one's giving period — reached through that
    period's own institution_id — and a campaign launched against it, while the
    identical read inside its own scope succeeds.

    PRD §2.1: "When `X-User-Role` is `InstitutionRepresentative`, `X-User-ID` is the `id` of the acting `Institution`."
    PRD §2.1: "That comparison is made directly where the resource carries `institution_id` itself — giving periods, governance packets, pledge campaigns, collateral assets and loan applications — and transitively otherwise: a pledge is owned through its campaign's `institution_id`, a loan through its application's `institution_id`, and a draw request, covenant or workout plan through its loan and that loan's application."
    PRD §2.1: "An `InstitutionRepresentative` acting on a resource that belongs to any other institution is rejected with `ERR_INSTITUTION_SCOPE_VIOLATION` (HTTP 403)."
    PRD §2.10: "An `InstitutionRepresentative` acts only within its own institution — `ERR_INSTITUTION_SCOPE_VIOLATION`, applied to every endpoint whose authorised roles include that role."

    Design: Corner/rbac/institution_representative_cannot_touch_another_institutions_rows
    """
    reset_clock(api)
    first = build_institution(api, **BORROWER)
    second = build_institution(api, **SECOND_BAPTIST)
    own_period = build_giving_period(api, first["id"])
    other_period = build_giving_period(
        api,
        second["id"],
        total_contributions_cents=30000000,
        restricted_contributions_cents=1000000,
        donor_restricted_endowment_draw_cents=0,
        operating_expense_cents=20000000,
        member_household_count=200,
    )
    representative = make_institution_representative_headers(first["id"])

    validate_error(
        api.get_institution(second["id"], representative),
        ERR_INSTITUTION_SCOPE_VIOLATION,
        403,
    )
    validate_error(
        api.get_giving_period(other_period["id"], representative),
        ERR_INSTITUTION_SCOPE_VIOLATION,
        403,
    )
    validate_error(
        api.create_pledge_campaign(pledge_campaign_payload(second["id"]), representative),
        ERR_INSTITUTION_SCOPE_VIOLATION,
        403,
    )
    _, campaign_meta = validate_paginated(api.list_pledge_campaigns(PLATFORM_ADMIN))
    assert_pagination_meta(campaign_meta, total_count=0)

    inside_scope = get_success_data(
        api.get_giving_period(own_period["id"], representative)
    )
    assert inside_scope["id"] == own_period["id"]
    assert inside_scope["institution_id"] == first["id"]


def test_both_roles_an_endpoint_lists_can_write_and_the_counters_prove_it(api):
    """
    The analyst and the borrower's own representative are both listed on giving-period
    and collateral registration, and all four writes land: the institution reports two
    periods of which one is audited, and each asset carries the valuation its own age
    and type produce.

    PRD §4: "| POST | `/giving-periods` | Record one non-overlapping annual giving period for an institution, split between unrestricted and donor-restricted contributions. | `CreditAnalyst`, `InstitutionRepresentative` |"
    PRD §4: "| POST | `/collateral-assets` | Register a special-purpose property or endowment asset with its appraisal and marketability profile. | `CreditAnalyst`, `InstitutionRepresentative` |"
    PRD §3.1: "Filing a period also reconciles its institution. `period_count` rises by 1, and `audited_period_count` rises by 1 as well when the new period's `source` is `AUDITED`."
    PRD §3.4: "Registration computes `appraisal_age_days` and `lending_value_cents` immediately, and leaves `assigned_loan_application_id`, `lien_position`, `lien_effective_from` and `lien_effective_to` all null with `lien_history` an empty list."
    PRD §2.3: "Unless a collection declares otherwise below, records are returned sorted by `created_at` ascending."
    PRD §2.3: "Five collections invert that default and return the newest record first, sorted by `created_at` descending: institutions, governance authorizations, pledge campaigns, loan applications and loans."

    Design: Corner/rbac/shared_operations_work_for_every_role_that_declares_them
    """
    reset_clock(api)
    institution = build_institution(api, **BORROWER)
    representative = make_institution_representative_headers(institution["id"])

    audited = get_success_data(
        api.create_giving_period(giving_period_payload(institution["id"]), CREDIT_ANALYST),
        201,
    )
    assert audited["source"] == "AUDITED"
    internal = get_success_data(
        api.create_giving_period(
            giving_period_payload(
                institution["id"],
                period_label="2025Q2",
                period_start="2025-04-01T00:00:00Z",
                period_end="2025-06-30T00:00:00Z",
                source="INTERNAL",
                total_contributions_cents=62000000,
                operating_expense_cents=40999950,
                member_household_count=510,
            ),
            representative,
        ),
        201,
    )
    assert internal["source"] == "INTERNAL"

    # PARSONAGE at score 4 proposes 70 percent and is capped at 70 percent, and a
    # 92-day-old appraisal takes no seasoning haircut.
    parsonage = get_success_data(
        api.create_collateral_asset(
            collateral_asset_payload(
                institution["id"],
                asset_type="PARSONAGE",
                description_label="Parsonage on Elm Street",
                appraised_value_cents=100000000,
                appraisal_date="2026-05-01T00:00:00Z",
                alternative_use_score=4,
            ),
            representative,
        ),
        201,
    )
    assert_fields(parsonage, appraisal_age_days=92, lending_value_cents=70000000)
    # SANCTUARY at score 2 proposes 50 percent under a 55 percent ceiling, and a
    # 426-day-old appraisal is haircut to 90 percent.
    sanctuary = get_success_data(
        api.create_collateral_asset(
            collateral_asset_payload(institution["id"]), CREDIT_ANALYST
        ),
        201,
    )
    assert_fields(sanctuary, appraisal_age_days=426, lending_value_cents=225000000)

    reread = get_success_data(api.get_institution(institution["id"], LOAN_SERVICER))
    assert_fields(
        reread, period_count=2, audited_period_count=1, cumulative_forgiveness_cents=0
    )

    # Collateral assets are not among the five collections that invert the default,
    # so the two rows come back oldest first.
    rows, meta = validate_paginated(
        api.list_collateral_assets(LOAN_SERVICER, {"institution_id": institution["id"]})
    )
    assert_pagination_meta(meta, total_count=2, has_more=False)
    assert_id_order(rows, [parsonage["id"], sanctuary["id"]])


def test_the_analyst_who_prepared_the_file_cannot_decide_it_even_wearing_the_committee_hat(api):
    """
    The identical approval body answers three ways on one application: refused for
    segregation of duties when the acting id is the preparer's, refused earlier for
    the role when that same id acts as an analyst, and approved when a different
    committee member submits it.

    PRD §3.6: "Segregation of duties is absolute: the acting `X-User-ID` must differ from the application's `prepared_by_user_id`, and an analyst attempting to decide the application it underwrote is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §2.10: "The acting `X-User-ID` differs from the application's `prepared_by_user_id` — `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), on the committee decision."
    PRD §2.10: "The acting role appears in the target endpoint's authorised-role list — `ERR_UNAUTHORIZED`, applied to every endpoint."
    PRD §3.5: "`prepared_by_user_id` is set to the acting `X-User-ID`, `revision_reason` is cleared to null, and `version` advances by 1."
    PRD §3.6: "All three arms set `decided_by_user_id` to the acting `X-User-ID` and advance the application's `version` by 1."
    PRD §3.6: "On success the application moves `COMMITTEE_REVIEW → APPROVED`."

    Design: Corner/rbac/the_preparing_analyst_cannot_render_the_committee_decision
    """
    reset_clock(api)
    chain = chain_through_assignment(api, institution_overrides=BORROWER)
    refer_to_committee(api, chain.loan_application_id, ANALYST_1)

    staged = chain.read_application()
    assert_fields(staged, status="COMMITTEE_REVIEW", prepared_by_user_id=ANALYST_1)

    validate_error(
        api.committee_decision(
            chain.loan_application_id,
            committee_decision_payload("APPROVE"),
            make_committee_member_headers(ANALYST_1),
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    blocked = chain.read_application()
    assert blocked["status"] == "COMMITTEE_REVIEW"
    assert_nulls(blocked, "decided_by_user_id")

    # The same id acting as an analyst never reaches position 33.
    validate_error(
        api.committee_decision(
            chain.loan_application_id,
            committee_decision_payload("APPROVE"),
            make_credit_analyst_headers(ANALYST_1),
        ),
        ERR_UNAUTHORIZED,
        403,
    )

    approved = get_success_data(
        api.committee_decision(
            chain.loan_application_id, committee_decision_payload("APPROVE"), COMMITTEE_MEMBER
        )
    )
    assert_fields(approved, status="APPROVED", decided_by_user_id=COMMITTEE_1)
