"""Role exclusivity, peer isolation, version tokens, paging and ops-run policy."""

from prd_bench_local_runner.testing import (
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as asserts
from test_helpers import constants as const
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    INSTALLATION_HOUSING_OFFICE_USER_ID,
    MAINTENANCE_TECH_USER_ID,
    PROPERTY_MANAGER_USER_ID,
    TEST_USERS,
    make_service_member_headers,
)

ANONYMOUS = {"Content-Type": "application/json"}
ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["property_manager_headers"]
TECH = TEST_USERS["maintenance_tech_headers"]
SPECIALIST = TEST_USERS["environmental_specialist_headers"]
HOUSING_OFFICE = TEST_USERS["installation_housing_office_headers"]

BILL_OF_RIGHTS_VERSION = "2026.1"
RANGE_DESCRIPTION = "Range burner dead"
MUSTY_SYMPTOMS = "Musty smell in the hall closet"
BURNER_COMPLAINT = "Burner repair never scheduled"
NEXT_YEAR_START = {"start_date": "2027-01-01"}
YOUNG_CHILD_PRESENT = {"child_under_six_present": True}


def test_every_exclusive_operation_refuses_the_role_that_would_reach_for_it(api):
    """Seven single-role endpoints, each tried by the role most tempted by it.

    PRD: "If both headers are present and well formed but the named role does not appear in the authorised-role list for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/every_exclusive_operation_refuses_the_role_that_would_reach_for_it
    """
    state = fx.setup_occupied_lease(api)
    sponsor = state["sponsor"]
    sponsor_headers = make_service_member_headers(sponsor["id"])
    lease_id = state["lease"]["id"]
    unit_id = state["unit"]["id"]
    order = fx.submit_work_order(
        api,
        unit_id,
        lease_id=lease_id,
        category="APPLIANCE",
        description=RANGE_DESCRIPTION,
        habitability_impact=False,
    )
    hazard = fx.report_hazard(
        api,
        unit_id,
        headers=sponsor_headers,
        lease_id=lease_id,
        hazard_type="MOLD",
        reported_symptoms=MUSTY_SYMPTOMS,
    )
    dispute = fx.open_dispute(
        api,
        lease_id,
        sponsor,
        category="MAINTENANCE_QUALITY",
        description=BURNER_COMPLAINT,
    )
    assign_payload = f.assign_work_order_payload(MAINTENANCE_TECH_USER_ID)

    # The technician who will do the work may not dispatch himself.
    validate_error(
        api.assign_work_order(order["id"], assign_payload, TECH),
        ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        403,
    )
    # The manager who dispatches may not also record the labour.
    validate_error(
        api.start_work_order(order["id"], MANAGER),
        ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        403,
    )
    validate_error(
        api.assess_hazard_case(
            hazard["id"], f.assess_hazard_case_payload(**YOUNG_CHILD_PRESENT), MANAGER
        ),
        ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        403,
    )
    # The landlord may never sign the Bill of Rights for the family.
    validate_error(
        api.tenant_acknowledge(
            state["inspection"]["id"],
            f.tenant_acknowledge_payload(
                f"{sponsor['first_name']} {sponsor['last_name']}",
                BILL_OF_RIGHTS_VERSION,
            ),
            MANAGER,
        ),
        ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        403,
    )
    # The role rung fires here, not the state rung that would refuse an
    # UNDER_REVIEW case, and not the segregation-of-duties rung below it.
    validate_error(
        api.decide_escalated_dispute(
            dispute["id"], f.installation_decision_payload(0), MANAGER
        ),
        ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        403,
    )
    validate_error(
        api.create_installation(f.create_installation_payload(), MANAGER),
        ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        403,
    )
    # The housing office co-runs the offer cycle but does not sign a tenancy.
    validate_error(
        api.create_lease(
            f.create_lease_payload(
                state["application"]["id"], unit_id, **NEXT_YEAR_START
            ),
            HOUSING_OFFICE,
        ),
        ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        403,
    )
    # A request with no role header is refused one rung earlier, so the
    # missing-header case and the wrong-role case stay distinguishable.
    validate_error(
        api.assign_work_order(order["id"], assign_payload, ANONYMOUS),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )

    untouched_order = fx.read_work_order(api, order["id"])
    assert untouched_order["status"] == "SUBMITTED"
    assert untouched_order["assigned_tech_user_id"] is None
    assert untouched_order["first_response_at"] is None
    untouched_dispute = fx.read_dispute(api, dispute["id"])
    assert untouched_dispute["status"] == "UNDER_REVIEW"
    assert untouched_dispute["round_count"] == 0
    untouched_hazard = fx.read_hazard_case(api, hazard["id"])
    assert untouched_hazard["status"] == "REPORTED"
    assert untouched_hazard["assessment_severity"] is None
    assert untouched_hazard["remediation_work_order_id"] is None
    # No refused assessment means no hold on the unit.
    assert fx.read_housing_unit(api, unit_id)["status"] == "OCCUPIED"


DISHWASHER_DESCRIPTION = "Dishwasher will not drain"
CORPORATE_DESCRIPTION = "Corporate-raised ticket"


def test_a_shared_operation_admits_each_declared_role_and_still_excludes_the_rest(api):
    """One payload, three accepted authors and a fourth role turned away.

    PRD: "A `WorkOrder` may be raised by a `PropertyManager`, by a resident `ServiceMember`, or by a `MaintenanceTech` who finds something else while on site."

    Design: Corner/rbac/a_shared_operation_admits_each_declared_role_and_still_excludes_the_rest
    """
    state = fx.setup_occupied_lease(api)
    lease_id = state["lease"]["id"]
    sponsor_headers = make_service_member_headers(state["sponsor"]["id"])
    payload = f.create_work_order_payload(
        state["unit"]["id"],
        lease_id=lease_id,
        category="APPLIANCE",
        description=DISHWASHER_DESCRIPTION,
        habitability_impact=False,
    )

    by_manager = validate_success(api.create_work_order(payload, MANAGER), 201)
    by_sponsor = validate_success(api.create_work_order(payload, sponsor_headers), 201)
    by_tech = validate_success(api.create_work_order(payload, TECH), 201)

    # Three genuinely distinct rows, not one row answered three times.
    created_ids = {by_manager["id"], by_sponsor["id"], by_tech["id"]}
    assert len(created_ids) == 3
    for created in (by_manager, by_sponsor, by_tech):
        assert created["status"] == "SUBMITTED"
        # APPLIANCE is the routine tier and no habitability floor was raised.
        assert created["priority_class"] == "ROUTINE"
        assert created["lease_id"] == lease_id
        asserts.assert_work_order(created)

    # Shared is not universal: the corporate operator is absent from this list.
    validate_error(
        api.create_work_order(
            f.create_work_order_payload(
                state["unit"]["id"],
                lease_id=lease_id,
                category="APPLIANCE",
                description=CORPORATE_DESCRIPTION,
                habitability_impact=False,
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        403,
    )

    rows, meta = validate_paginated(
        api.list_work_orders(HOUSING_OFFICE, params={"lease_id": lease_id})
    )
    assert meta["total_count"] == 3
    assert len(rows) == 3
    assert {row["id"] for row in rows} == created_ids


HVAC_COMPLAINT = "Repeat repairs never fixed the leak"
ROUND_REMEDIES = (
    "Re-seal the shower pan, round 1",
    "Re-seal the shower pan, round 2",
    "Re-seal the shower pan, round 3",
)
DECISION_NOTE = {"decision_note": "Landlord position sustained"}
PROPOSER_WEARING_THE_OFFICE_HAT = build_user_headers(
    PROPERTY_MANAGER_USER_ID, "InstallationHousingOffice"
)


def test_the_decider_of_an_escalated_dispute_may_not_be_the_author_of_the_offer(api):
    """The same call, same payload and same case: refused, then taken by a peer.

    PRD: "On a dispute case, the `PropertyManager` whose `X-User-ID` was stamped as `proposed_by_user_id` on the most recent proposal may not be the `InstallationHousingOffice` user who renders the escalated decision; the deciding `X-User-ID` must differ."

    Design: Corner/rbac/the_decider_of_an_escalated_dispute_may_not_be_the_author_of_the_offer
    """
    state = fx.setup_occupied_lease(api)
    lease_id = state["lease"]["id"]
    dispute = fx.open_dispute(
        api,
        lease_id,
        state["sponsor"],
        category="MAINTENANCE_QUALITY",
        description=HVAC_COMPLAINT,
    )
    for remedy in ROUND_REMEDIES:
        fx.propose_resolution(api, dispute["id"], remedy, 0)
        fx.respond_to_proposal(api, dispute["id"], state["sponsor"], False)
    escalated = fx.read_dispute(api, dispute["id"])
    assert escalated["status"] == "ESCALATED_INSTALLATION"
    assert escalated["proposed_by_user_id"] == PROPERTY_MANAGER_USER_ID

    # A legitimate InstallationHousingOffice header clears the role rung and the
    # identity behind it is refused one rung further down.
    validate_error(
        api.decide_escalated_dispute(
            dispute["id"],
            f.installation_decision_payload(0, **DECISION_NOTE),
            PROPOSER_WEARING_THE_OFFICE_HAT,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    decided = validate_success(
        api.decide_escalated_dispute(
            dispute["id"],
            f.installation_decision_payload(0, **DECISION_NOTE),
            HOUSING_OFFICE,
        )
    )

    # A different user of the same role, on the same case, is accepted.
    assert decided["status"] == "CLOSED_RESOLVED"
    assert decided["decided_by_user_id"] == INSTALLATION_HOUSING_OFFICE_USER_ID
    assert decided["proposed_by_user_id"] == PROPERTY_MANAGER_USER_ID
    assert decided["credit_award_cents"] == 0
    assert decided["round_count"] == const.DISPUTE_ROUND_CAP
    asserts.assert_dispute_case(decided)
    _, ledger_meta = validate_paginated(
        api.list_lease_allotment_transactions(lease_id, MANAGER)
    )
    # A zero award posts no REFUND row.
    assert ledger_meta["total_count"] == 0


PEER_SPONSOR = {"dodid": "1000000002", "last_name": "Blake", "first_name": "Dana"}
OPAQUE_READERS = ("maintenance", "specialist", "housing office")


def test_only_the_entity_backed_role_is_narrowed_between_peers(api):
    """Four accepted reads and one refusal on one path, one row, one field.

    PRD: "The server records it wherever a transition in this specification stamps an actor — as `conducted_by_user_id` on a `MoveInInspection`, as `assessed_by_user_id` or `cleared_by_user_id` on a `HazardCase`, as `proposed_by_user_id` or `decided_by_user_id` on a `DisputeCase` — but it never compares such an identifier to any entity's `id`, and no ownership rule constrains these five roles."

    Design: Corner/rbac/only_the_entity_backed_role_is_narrowed_between_peers
    """
    state = fx.setup_occupied_lease(api)
    lease_id = state["lease"]["id"]
    peer = fx.create_service_member(api, **PEER_SPONSOR)

    # The peer holds the very same role as the tenant and is still refused.
    validate_error(
        api.get_lease(lease_id, make_service_member_headers(peer["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )

    owner_view = validate_success(
        api.get_lease(lease_id, make_service_member_headers(state["sponsor"]["id"]))
    )
    assert owner_view["gross_rent_cents"] == const.BASE_GROSS_RENT_CENTS
    assert owner_view["service_member_id"] == state["sponsor"]["id"]

    # The three opaque identities read another family's lease unconditionally.
    opaque_views = [
        validate_success(api.get_lease(lease_id, headers))
        for headers in (TECH, SPECIALIST, HOUSING_OFFICE)
    ]
    for label, view in zip(OPAQUE_READERS, opaque_views):
        assert view["gross_rent_cents"] == const.BASE_GROSS_RENT_CENTS, label
        assert view["service_member_id"] == state["sponsor"]["id"], label
        asserts.assert_lease(view)


REDETERMINATION_DATE = "2026-10-01"


def test_the_lease_version_token_is_consumed_by_the_write_that_uses_it(api):
    """Stale refused, fresh taken, the same token replayed, then a re-read taken.

    PRD: "Redetermination is repeatable, which is precisely why it is guarded by the stale-version check of §2.6 rather than by a state precondition."

    Design: Corner/cross_cutting_complexity_layers/the_lease_version_token_is_consumed_by_the_write_that_uses_it
    """
    state = fx.setup_occupied_lease(api)
    lease_id = state["lease"]["id"]
    lease = fx.read_lease(api, lease_id)
    opening_version = lease["version"]
    assert lease["rent_basis"] == "MOVE_IN_FINAL"
    assert lease["gross_rent_cents"] == const.BASE_GROSS_RENT_CENTS

    validate_error(
        api.redetermine_rent(
            lease_id,
            f.rent_redetermination_payload(opening_version - 1, REDETERMINATION_DATE),
            MANAGER,
        ),
        ApiErrorId.ERR_STALE_LEASE_VERSION,
        412,
    )

    first = validate_success(
        api.redetermine_rent(
            lease_id,
            f.rent_redetermination_payload(opening_version, REDETERMINATION_DATE),
            MANAGER,
        )
    )
    assert first["version"] == opening_version + 1

    # Replaying the token that just worked is refused: the token is consumed by
    # the write rather than by the payload.
    validate_error(
        api.redetermine_rent(
            lease_id,
            f.rent_redetermination_payload(opening_version, REDETERMINATION_DATE),
            MANAGER,
        ),
        ApiErrorId.ERR_STALE_LEASE_VERSION,
        412,
    )

    second = validate_success(
        api.redetermine_rent(
            lease_id,
            f.rent_redetermination_payload(first["version"], REDETERMINATION_DATE),
            ADMIN,
        )
    )

    assert second["version"] == opening_version + 2
    # A 2026 effective date selects the same rate row, so the version moved and
    # the money did not.
    for repriced in (first, second):
        assert repriced["gross_rent_cents"] == const.BASE_GROSS_RENT_CENTS
        assert repriced["net_rent_cents"] == const.BASE_NET_RENT_CENTS
        assert repriced["rent_basis"] == "MOVE_IN_FINAL"
        assert repriced["rent_effective_year"] == 2026
        asserts.assert_lease_money_invariants(repriced)
    _, ledger_meta = validate_paginated(
        api.list_lease_allotment_transactions(lease_id, MANAGER)
    )
    # The new rent applies to subsequent allotment runs only.
    assert ledger_meta["total_count"] == 0


CONTROL_DATE = "2026-08-25"
CANONICAL_BEDROOM_ELIGIBILITY = 2
CANONICAL_DEPENDENT_COUNT = 3


def test_recertification_is_repeatable_in_output_but_not_in_token(api):
    """Byte-identical business output twice over, and the version is the only mark.

    PRD: "Recertification is legitimately repeatable while the application is `PENDING`, so a second sequential recertification from a fresh read succeeds; the version check is what catches a writer who did not observe an intervening offer, decline penalty or earlier recertification."

    Design: Corner/cross_cutting_complexity_layers/recertification_is_repeatable_in_output_but_not_in_token
    """
    state = fx.setup_pending_application(api, unit_specs=())
    application_id = state["application"]["id"]
    opening = validate_success(
        api.get_waitlist_application(application_id, HOUSING_OFFICE)
    )
    opening_version = opening["version"]
    assert opening["effective_control_date"] == CONTROL_DATE
    assert opening["bedroom_eligibility"] == CANONICAL_BEDROOM_ELIGIBILITY

    validate_error(
        api.recertify_waitlist_application(
            application_id, f.recertify_payload(opening_version - 1), HOUSING_OFFICE
        ),
        ApiErrorId.ERR_STALE_APPLICATION_VERSION,
        412,
    )

    first = validate_success(
        api.recertify_waitlist_application(
            application_id, f.recertify_payload(opening_version), HOUSING_OFFICE
        )
    )
    assert first["version"] == opening_version + 1

    # The consumed token is refused from the other authorised role too, so the
    # token belongs to the row and not to the caller.
    validate_error(
        api.recertify_waitlist_application(
            application_id, f.recertify_payload(opening_version), ADMIN
        ),
        ApiErrorId.ERR_STALE_APPLICATION_VERSION,
        412,
    )

    second = validate_success(
        api.recertify_waitlist_application(
            application_id, f.recertify_payload(first["version"]), ADMIN
        )
    )

    assert second["version"] == opening_version + 2
    # No decline and no orders change, so the re-derivation reproduces itself.
    for recertified in (first, second):
        assert recertified["effective_control_date"] == CONTROL_DATE
        assert recertified["bedroom_eligibility"] == CANONICAL_BEDROOM_ELIGIBILITY
        assert recertified["dependent_count_at_application"] == (
            CANONICAL_DEPENDENT_COUNT
        )
        # Recertification is not a state transition.
        assert recertified["status"] == "PENDING"
        assert recertified["decline_count"] == 0
        asserts.assert_waitlist_application(recertified)


ACCOUNT_CLOCK = fx.CLOCK_AT_MOVE_IN
OPENING_BALANCE_CENTS = const.TEST_DEFAULTS["OPENING_BALANCE_CENTS"]
DRAW_CENTS = 100000
BALANCE_AFTER_ONE_DRAW_CENTS = 4900000
BALANCE_AFTER_TWO_DRAWS_CENTS = 4800000
WILDLY_OVERDRAWN_CENTS = 99000000
FIRST_PURPOSE = {"purpose": "Playground resurfacing"}
SECOND_PURPOSE = {"purpose": "Playground fencing"}
REBUILD_PURPOSE = {"purpose": "Whole-neighbourhood rebuild"}


def test_a_stale_account_token_is_reported_before_the_balance_is_even_checked(api):
    """One call breaks the version rule and the balance rule; the version answers.

    PRD: "Because these rungs sit above every state and business rung, a stale version is reported even when the request would also have failed a later business check."

    Design: Corner/cross_cutting_complexity_layers/a_stale_account_token_is_reported_before_the_balance_is_even_checked
    """
    fx.set_clock(api, ACCOUNT_CLOCK)
    installation = fx.create_installation(api)
    account = fx.create_reinvestment_account(api, installation["id"])
    opening = validate_success(api.get_reinvestment_account(account["id"], MANAGER))
    opening_version = opening["version"]
    assert opening["closing_balance_cents"] == OPENING_BALANCE_CENTS

    validate_error(
        api.authorize_expenditure(
            account["id"],
            f.expenditure_payload(opening_version - 1, DRAW_CENTS, **FIRST_PURPOSE),
            MANAGER,
        ),
        ApiErrorId.ERR_STALE_ACCOUNT_VERSION,
        412,
    )
    # The refused draw moved no money.
    assert fx.read_account(api, account["id"])["closing_balance_cents"] == (
        OPENING_BALANCE_CENTS
    )

    first = validate_success(
        api.authorize_expenditure(
            account["id"],
            f.expenditure_payload(opening_version, DRAW_CENTS, **FIRST_PURPOSE),
            MANAGER,
        )
    )
    assert first["version"] == opening_version + 1
    assert first["expenditures_cents"] == DRAW_CENTS
    # 5000000 + 0 - 100000.
    assert first["closing_balance_cents"] == BALANCE_AFTER_ONE_DRAW_CENTS

    # Replaying the token stops the same capital draw being taken twice.
    validate_error(
        api.authorize_expenditure(
            account["id"],
            f.expenditure_payload(opening_version, DRAW_CENTS, **FIRST_PURPOSE),
            MANAGER,
        ),
        ApiErrorId.ERR_STALE_ACCOUNT_VERSION,
        412,
    )
    # Both stale and wildly overdrawn: the concurrency rung outranks the fiscal
    # rung, so the balance is never consulted.
    validate_error(
        api.authorize_expenditure(
            account["id"],
            f.expenditure_payload(
                opening_version - 1, WILDLY_OVERDRAWN_CENTS, **REBUILD_PURPOSE
            ),
            MANAGER,
        ),
        ApiErrorId.ERR_STALE_ACCOUNT_VERSION,
        412,
    )

    second = validate_success(
        api.authorize_expenditure(
            account["id"],
            f.expenditure_payload(first["version"], DRAW_CENTS, **SECOND_PURPOSE),
            ADMIN,
        )
    )

    assert second["version"] == opening_version + 2
    assert second["expenditures_cents"] == DRAW_CENTS * 2
    assert second["closing_balance_cents"] == BALANCE_AFTER_TWO_DRAWS_CENTS
    asserts.assert_reinvestment_account(second)


SEPTEMBER = "2026-09"
OCTOBER = "2026-10"
NOVEMBER = "2026-11"
OCTOBER_RUN_CLOCK = "2026-10-01T09:00:00Z"
GOODWILL_CREDIT_CENTS = 5000
GOODWILL_REMEDY = "One-off goodwill credit"
HEAT_COMPLAINT = "Charged a full month for a half month of heat"
FIRST_RUNNING_BALANCE_CENTS = 218150
SECOND_RUNNING_BALANCE_CENTS = 436300
THIRD_RUNNING_BALANCE_CENTS = 431300
SEPTEMBER_SOURCE_REF = "ALLOTMENT_RUN:2026-09"
FIRST_PAGE = {"limit": 2, "offset": 0}
SECOND_PAGE = {"limit": 2, "offset": 2}
OVER_CEILING_PAGE = {"limit": 101, "offset": 0}


def test_the_ledger_read_pages_and_filters_the_same_three_rows_seven_ways(api):
    """Two windows, four filter combinations and one refused page size.

    PRD: "A `limit` below 1 or above 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400) rather than being silently clamped."

    Design: Corner/cross_cutting_complexity_layers/the_ledger_read_pages_and_filters_the_same_three_rows_seven_ways
    """
    state = fx.setup_charged_lease(api, period_month=SEPTEMBER)
    lease_id = state["lease"]["id"]
    sponsor_headers = make_service_member_headers(state["sponsor"]["id"])
    fx.set_clock(api, OCTOBER_RUN_CLOCK)
    fx.run_allotment_run(api, state["installation"]["id"], OCTOBER)
    dispute = fx.open_dispute(
        api, lease_id, state["sponsor"], description=HEAT_COMPLAINT
    )
    fx.propose_resolution(api, dispute["id"], GOODWILL_REMEDY, GOODWILL_CREDIT_CENTS)
    accepted = fx.respond_to_proposal(api, dispute["id"], state["sponsor"], True)
    assert accepted["credit_award_cents"] == GOODWILL_CREDIT_CENTS

    first_page, first_meta = validate_paginated(
        api.list_lease_allotment_transactions(lease_id, MANAGER, params=FIRST_PAGE)
    )
    # total_count reports the filtered-then-unpaged size, not the page size.
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert len(first_page) == 2
    assert first_page[0]["type"] == "CHARGE"
    assert first_page[0]["amount_cents"] == const.BASE_NET_RENT_CENTS
    assert first_page[0]["running_balance_cents"] == FIRST_RUNNING_BALANCE_CENTS
    assert first_page[1]["period_month"] == OCTOBER
    assert first_page[1]["running_balance_cents"] == SECOND_RUNNING_BALANCE_CENTS
    asserts.assert_created_at_ascending(first_page)

    second_page, second_meta = validate_paginated(
        api.list_lease_allotment_transactions(
            lease_id, sponsor_headers, params=SECOND_PAGE
        )
    )
    # Offset 2 resumes exactly where page 1 stopped and repeats nothing.
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert len(second_page) == 1
    assert second_page[0]["type"] == "REFUND"
    assert second_page[0]["amount_cents"] == -GOODWILL_CREDIT_CENTS
    assert second_page[0]["running_balance_cents"] == THIRD_RUNNING_BALANCE_CENTS

    charges, charges_meta = validate_paginated(
        api.list_lease_allotment_transactions(
            lease_id, ADMIN, params={"type": "CHARGE"}
        )
    )
    # The type filter drops the REFUND row and total_count follows the filter.
    assert charges_meta["total_count"] == 2
    assert charges_meta["has_more"] is False
    assert len(charges) == 2

    september, september_meta = validate_paginated(
        api.list_lease_allotment_transactions(
            lease_id, HOUSING_OFFICE, params={"period_month": SEPTEMBER}
        )
    )
    assert september_meta["total_count"] == 1
    assert september[0]["source_ref"] == SEPTEMBER_SOURCE_REF

    # The two filters compose as AND rather than OR.
    october_charges, october_meta = validate_paginated(
        api.list_lease_allotment_transactions(
            lease_id, MANAGER, params={"type": "CHARGE", "period_month": OCTOBER}
        )
    )
    assert october_meta["total_count"] == 1
    assert october_charges[0]["running_balance_cents"] == SECOND_RUNNING_BALANCE_CENTS

    # The refund belongs to October, so this conjunction is genuinely empty.
    empty, empty_meta = validate_paginated(
        api.list_lease_allotment_transactions(
            lease_id, MANAGER, params={"type": "REFUND", "period_month": SEPTEMBER}
        )
    )
    assert empty == []
    assert empty_meta["total_count"] == 0

    validate_error(
        api.list_lease_allotment_transactions(
            lease_id, MANAGER, params=OVER_CEILING_PAGE
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )


FORT_BLISS = {"name": "Fort Bliss Family Housing", "mha_code": "TX-ELP"}
SECOND_UNIT_CODE = {"unit_code": "B-201"}
EARLIER_CONTROL_DATE = {
    "pcs_orders_date": "2026-08-20",
    "expected_arrival_date": "2026-09-10",
}
OFFER_RUN_CLOCK = fx.CLOCK_BEFORE_ARRIVAL
OFFER_EXPIRES_AT = "2026-08-28T00:00:00Z"


def test_one_offer_run_sees_only_its_own_installations_units_and_applicants(api):
    """The better-ranked applicant next door is simply not in the pool.

    PRD: "For each unit in that order the run assembles a candidate set from the installation's applications."

    Design: Corner/cross_cutting_complexity_layers/one_offer_run_sees_only_its_own_installations_units_and_applicants
    """
    home = fx.setup_installation_with_unit(api, clock=OFFER_RUN_CLOCK)
    neighbour = fx.setup_installation_with_unit(
        api,
        clock=None,
        installation_overrides=FORT_BLISS,
        unit_overrides=SECOND_UNIT_CODE,
    )
    home_sponsor, _ = fx.setup_sponsor_family(api)
    neighbour_sponsor, _ = fx.setup_sponsor_family(api, **PEER_SPONSOR)
    home_application = fx.submit_application(
        api, home["installation"]["id"], home_sponsor
    )
    neighbour_application = fx.submit_application(
        api,
        neighbour["installation"]["id"],
        neighbour_sponsor,
        **EARLIER_CONTROL_DATE,
    )

    run = fx.run_offer_run(api, home["installation"]["id"])

    # The acting installation's checkpoint and counters moved.
    assert run["offer_run_epoch"] == 1
    assert run["assigned_unit_count"] == 1
    assert run["pending_application_count"] == 0
    asserts.assert_instant_equals(run["last_offer_run_at"], OFFER_RUN_CLOCK)
    offered = fx.read_application(api, home_application["id"])
    assert offered["status"] == "OFFERED"
    assert offered["offered_unit_id"] == home["unit"]["id"]
    asserts.assert_instant_equals(offered["offer_expires_at"], OFFER_EXPIRES_AT)

    # A control date five days earlier does not help an applicant out of scope.
    outsider = fx.read_application(api, neighbour_application["id"])
    assert outsider["effective_control_date"] == EARLIER_CONTROL_DATE[
        "pcs_orders_date"
    ]
    assert outsider["status"] == "PENDING"
    assert outsider["offered_unit_id"] is None
    assert outsider["offer_count"] == 0
    # The unit pool is scoped by installation, not by matching bedrooms and rank.
    assert fx.read_housing_unit(api, neighbour["unit"]["id"])["status"] == "AVAILABLE"

    untouched = fx.read_installation(api, neighbour["installation"]["id"])
    assert untouched["offer_run_epoch"] == 0
    assert untouched["last_offer_run_at"] is None
    assert untouched["assigned_unit_count"] == 0
    assert untouched["available_unit_count"] == 1
    assert untouched["pending_application_count"] == 1
    asserts.assert_installation_counter_conservation(untouched)

    neighbour_units, neighbour_units_meta = validate_paginated(
        api.list_housing_units(
            TECH, params={"installation_id": neighbour["installation"]["id"]}
        )
    )
    assert neighbour_units_meta["total_count"] == 1
    assert neighbour_units[0]["unit_code"] == SECOND_UNIT_CODE["unit_code"]
    home_applications, home_applications_meta = validate_paginated(
        api.list_waitlist_applications(
            HOUSING_OFFICE, params={"installation_id": home["installation"]["id"]}
        )
    )
    assert home_applications_meta["total_count"] == 1
    assert home_applications[0]["id"] == home_application["id"]


def test_three_ops_runs_keep_three_different_re_run_policies(api):
    """Skip-if-present, always-advance and hard refusal on one installation.

    PRD: "A run that made no offers still advances the epoch and stamps the timestamp."

    Design: Corner/cross_cutting_complexity_layers/three_ops_runs_keep_three_different_re_run_policies
    """
    state = fx.setup_occupied_lease(api)
    installation_id = state["installation"]["id"]
    lease_id = state["lease"]["id"]
    account = fx.create_reinvestment_account(api, installation_id)
    assert state["installation"]["offer_run_epoch"] == 1
    assert account["metrics_run_epoch"] == 0
    assert account["last_metrics_run_at"] is None
    fx.set_clock(api, OCTOBER_RUN_CLOCK)

    first_run = validate_success(
        api.run_allotment_run(
            installation_id, f.allotment_run_payload(SEPTEMBER), MANAGER
        )
    )
    assert first_run["offer_run_epoch"] == 1
    assert fx.read_lease(api, lease_id)["allotment_balance_cents"] == (
        FIRST_RUNNING_BALANCE_CENTS
    )

    # A repeated allotment run for the same period is a silent no-op.
    validate_success(
        api.run_allotment_run(
            installation_id, f.allotment_run_payload(SEPTEMBER), ADMIN
        )
    )

    assert fx.read_lease(api, lease_id)["allotment_balance_cents"] == (
        FIRST_RUNNING_BALANCE_CENTS
    )
    _, september_meta = validate_paginated(
        api.list_lease_allotment_transactions(
            lease_id, MANAGER, params={"period_month": SEPTEMBER}
        )
    )
    assert september_meta["total_count"] == 1

    # The offer run has nothing left to offer and still moves its checkpoint.
    offer_run = validate_success(
        api.run_waitlist_offer_run(installation_id, HOUSING_OFFICE)
    )

    assert offer_run["offer_run_epoch"] == 2
    asserts.assert_instant_equals(offer_run["last_offer_run_at"], OCTOBER_RUN_CLOCK)
    assert offer_run["pending_application_count"] == 0
    assert offer_run["assigned_unit_count"] == 0

    metrics = validate_success(
        api.run_metrics_run(account["id"], f.metrics_run_payload(SEPTEMBER), MANAGER)
    )
    assert metrics["metrics_run_epoch"] == 1
    asserts.assert_instant_equals(metrics["last_metrics_run_at"], OCTOBER_RUN_CLOCK)

    # The metrics re-run policy is a hard refusal, in both directions.
    validate_error(
        api.run_metrics_run(account["id"], f.metrics_run_payload(SEPTEMBER), MANAGER),
        ApiErrorId.ERR_PERIOD_ALREADY_POSTED,
        409,
    )
    refused_state = fx.read_account(api, account["id"])
    assert refused_state["metrics_run_epoch"] == 1
    asserts.assert_instant_equals(
        refused_state["last_metrics_run_at"], OCTOBER_RUN_CLOCK
    )
    validate_error(
        api.run_metrics_run(account["id"], f.metrics_run_payload(NOVEMBER), MANAGER),
        ApiErrorId.ERR_PERIOD_ALREADY_POSTED,
        409,
    )
