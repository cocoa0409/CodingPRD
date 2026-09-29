"""Who may act: role entitlement, committee identity scoping, auth and self-review."""

from typing import Any, Dict

import pytest
from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    DECLARANT_HEADERS,
    ERR_ASSOCIATION_NOT_FOUND,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    FUNDING_METHOD_CASH_FLOW,
    HEADERS_WITHOUT_ROLE,
    HEADERS_WITHOUT_USER_ID,
    INSPECTOR_HEADERS,
    NON_EXISTENT_UUID,
    OUTSIDE_WINDOW_OPERATOR_USER_ID,
    RECORDS_ACTION_ACCEPT,
    SEAT_TYPE_DECLARANT_APPOINTED,
    SEAT_TYPE_OWNER_ELECTED,
    SHARED_OPERATOR_USER_ID,
    TRIGGER_BASIS_FIXED_DATE,
    UNKNOWN_ROLE_NAME,
    ApiClient,
    association_payload,
    audit_engagement_payload,
    certify_trigger_payload,
    director_payload,
    do_certify_trigger,
    do_deliver_item,
    do_issue_engagement,
    do_rescind_director,
    lot_payload,
    make_auditor_headers,
    make_declarant_headers,
    make_headers,
    make_transition_committee_headers,
    read_association,
    read_turnover_case,
    records_transition_payload,
    reserve_study_payload,
    seed_association,
    seed_audit_engagement,
    seed_lot,
    seed_owner_elected_director,
    seed_records_item,
    seed_reserve_study,
    seed_subsidy_entry,
    seed_turnover_case,
    validate_error,
    validate_paginated,
    validate_success,
)


def _seed_community(api: ApiClient, name: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "name": name,
        "total_planned_lots": 4,
        "turnover_threshold_pct": 66.67,
        "fixed_turnover_date": "2027-01-01T00:00:00Z",
        "statute_of_repose_years": 8,
        "reserve_pool_cents": 0,
        "reserve_claim_pool_cents": 0,
        "declarant_monthly_subsidy_cents": 0,
    }
    defaults.update(overrides)
    return seed_association(api, **defaults)


# ─── Quarrendon: all five roles on one community ───────────────────────


@pytest.fixture
def quarrendon(api: ApiClient) -> Dict[str, Any]:
    """A registry pair created by the administrator and nothing else."""
    association = _seed_community(api, "Quarrendon", reserve_pool_cents=500000)
    case = seed_turnover_case(api, association["id"], total_seats=3)
    return {"association": association, "case": case}


class TestEachRoleRunsItsOwnStep:
    """Every role completes its own workflow step with its own header."""

    def test_the_five_roles_each_complete_their_exclusive_operation(
        self, api: ApiClient, quarrendon: Dict[str, Any]
    ) -> None:
        """Registry, sales, study, engagement and seat, one per role.

        "`Auditor` engages over an accounting period and issues the report.
        `ElectionInspector` seats and rescinds owner-elected directors. Every read
        operation under the business mount is available to all five roles."

        Design: Corner/rbac/each_role_performs_its_own_exclusive_operations
        """
        association_id = quarrendon["association"]["id"]
        case_id = quarrendon["case"]["id"]

        lot = seed_lot(api, association_id, "Q-1")
        assert lot["sale_status"] == "UNSOLD"

        study = seed_reserve_study(
            api,
            association_id,
            FUNDING_METHOD_CASH_FLOW,
            planned_annual_contribution_cents=300000,
            projected_annual_expenditure_cents=100000,
        )
        assert study["status"] == "DRAFT"

        engagement = seed_audit_engagement(
            api, association_id, "2026-01-01T00:00:00Z", "2026-06-30T00:00:00Z"
        )
        assert engagement["status"] == "ENGAGED"

        director = seed_owner_elected_director(api, case_id, full_name="Rosalind Achebe")
        assert director["status"] == "SEATED"
        assert director["seat_type"] == SEAT_TYPE_OWNER_ELECTED
        assert director["seated_by_user_id"] == "inspector-1"

    def test_the_inspector_rescission_releases_the_seat_it_had_taken(
        self, api: ApiClient, quarrendon: Dict[str, Any]
    ) -> None:
        """Rescinding returns the three-seat board to fully vacant.

        "Rescission sets `status` to `RESCINDED`, stamps `vacated_at`, decrements
        `owner_elected_seats` by one and increments `vacant_seats` by one so the
        seat ledger still balances"

        Design: Corner/rbac/each_role_performs_its_own_exclusive_operations
        """
        case_id = quarrendon["case"]["id"]
        director = seed_owner_elected_director(api, case_id, full_name="Rosalind Achebe")

        seated_case = read_turnover_case(api, case_id)
        assert seated_case["owner_elected_seats"] == 1
        assert seated_case["vacant_seats"] == 2

        rescinded = do_rescind_director(api, director["id"])
        assert rescinded["status"] == "RESCINDED"

        released_case = read_turnover_case(api, case_id)
        assert released_case["owner_elected_seats"] == 0
        assert released_case["vacant_seats"] == 3


# ─── Ravenstonedale: another role's operation is 403 ────────────────────


@pytest.fixture
def ravenstonedale(api: ApiClient) -> Dict[str, Any]:
    """A case with one required records item already delivered by the declarant."""
    association = _seed_community(api, "Ravenstonedale")
    case = seed_turnover_case(api, association["id"], total_seats=3)
    item = seed_records_item(api, case["id"], "WARRANTIES", required=True)
    do_deliver_item(api, item["id"])
    return {
        "association": association,
        "case": case,
        "item": item,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestOtherRolesOperationsAreForbidden:
    """Denial comes both from the endpoint's role list and from the discriminator."""

    def test_four_roles_are_each_refused_another_role_exclusive_creation(
        self, api: ApiClient, ravenstonedale: Dict[str, Any]
    ) -> None:
        """Nobody borrows another role's create endpoint.

        "When the headers are well formed but the role is not entitled to the
        operation, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/other_roles_exclusive_operations_are_forbidden
        """
        association_id = ravenstonedale["association"]["id"]

        validate_error(
            api.create_association(
                association_payload(name="Sneaky Plat"), DECLARANT_HEADERS
            ),
            ERR_ROLE_NOT_PERMITTED,
        )
        validate_error(
            api.create_lot(lot_payload(association_id, "R-9"), AUDITOR_HEADERS),
            ERR_ROLE_NOT_PERMITTED,
        )
        validate_error(
            api.create_reserve_study(
                reserve_study_payload(
                    association_id,
                    FUNDING_METHOD_CASH_FLOW,
                    planned_annual_contribution_cents=100000,
                    projected_annual_expenditure_cents=50000,
                ),
                INSPECTOR_HEADERS,
            ),
            ERR_ROLE_NOT_PERMITTED,
        )
        validate_error(
            api.create_audit_engagement(
                audit_engagement_payload(
                    association_id, "2026-01-01T00:00:00Z", "2026-06-30T00:00:00Z"
                ),
                ravenstonedale["committee_headers"],
            ),
            ERR_ROLE_NOT_PERMITTED,
        )

    def test_the_declarant_cannot_send_the_committee_side_of_a_shared_dispatcher(
        self, api: ApiClient, ravenstonedale: Dict[str, Any]
    ) -> None:
        """The role check on ACCEPT outranks any state consideration.

        "Five endpoints are shared dispatchers on which the **discriminator in the
        payload decides which role may act**, and that check runs before any state
        check, so a role mismatch outranks an illegal-from-state rejection"

        Design: Corner/rbac/other_roles_exclusive_operations_are_forbidden
        """
        item_id = ravenstonedale["item"]["id"]
        case_id = ravenstonedale["case"]["id"]

        validate_error(
            api.records_item_transition(
                item_id,
                records_transition_payload(RECORDS_ACTION_ACCEPT),
                DECLARANT_HEADERS,
            ),
            ERR_ROLE_NOT_PERMITTED,
        )

        rows, meta = validate_paginated(api.list_records_items(case_id, AUDITOR_HEADERS))
        assert meta["total_count"] == 1, "Every role keeps its shared read access"
        assert rows[0]["status"] == "DELIVERED", (
            "The refused ACCEPT left the item where the declarant put it"
        )


# ─── Saxtonbury and Thurlemere: the committee id is the scope ──────────


@pytest.fixture
def two_committees(api: ApiClient) -> Dict[str, Any]:
    """Two communities whose fixed turnover date is already reached."""
    first = _seed_community(
        api,
        "Saxtonbury",
        fixed_turnover_date="2026-07-01T00:00:00Z",
        reserve_pool_cents=200000,
    )
    second = _seed_community(
        api,
        "Thurlemere",
        fixed_turnover_date="2026-07-01T00:00:00Z",
        reserve_pool_cents=200000,
    )
    return {
        "first": first,
        "second": second,
        "first_case": seed_turnover_case(api, first["id"], total_seats=3),
        "second_case": seed_turnover_case(api, second["id"], total_seats=3),
    }


class TestCommitteeIdentityScoping:
    """A committee may only act for the association its X-User-ID names."""

    def test_the_neighbouring_committee_is_refused_where_the_owner_succeeds(
        self, api: ApiClient, two_committees: Dict[str, Any]
    ) -> None:
        """Body-scoped, path-scoped and sweep calls all refuse the wrong committee.

        "ownership checks on any resource that references an `Association` compare
        the resource's `association_id` foreign-key field to `X-User-ID`, and a
        committee acting on another community's lot, component, claim, contract,
        study, schedule, records item, director or turnover case is refused with
        `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/transition_committee_acting_for_another_association_is_forbidden
        """
        first_id = two_committees["first"]["id"]
        first_case_id = two_committees["first_case"]["id"]
        intruder = make_transition_committee_headers(two_committees["second"]["id"])

        validate_error(
            api.create_reserve_study(
                reserve_study_payload(
                    first_id,
                    FUNDING_METHOD_CASH_FLOW,
                    planned_annual_contribution_cents=100000,
                    projected_annual_expenditure_cents=50000,
                ),
                intruder,
            ),
            ERR_ROLE_NOT_PERMITTED,
        )
        validate_error(
            api.certify_trigger(
                first_case_id,
                certify_trigger_payload(trigger_basis=TRIGGER_BASIS_FIXED_DATE),
                intruder,
            ),
            ERR_ROLE_NOT_PERMITTED,
        )
        validate_error(
            api.repose_sweep(first_id, intruder),
            ERR_ROLE_NOT_PERMITTED,
        )

        untouched = read_turnover_case(api, first_case_id)
        assert untouched["governance_status"] == "DECLARANT_CONTROL"

        certified = do_certify_trigger(
            api, first_case_id, first_id, TRIGGER_BASIS_FIXED_DATE
        )
        assert certified["governance_status"] == "ELECTION_CALLED"
        assert certified["trigger_certified_by_user_id"] == first_id

        neighbour = read_turnover_case(api, two_committees["second_case"]["id"])
        assert neighbour["governance_status"] == "DECLARANT_CONTROL", (
            "A certification never reaches the next community's case"
        )


# ─── Underbarrow: rung one outranks everything ─────────────────────────


@pytest.fixture
def underbarrow(api: ApiClient) -> Dict[str, Any]:
    """A community that a well-formed request would happily read or write."""
    return {"association": _seed_community(api, "Underbarrow")}


class TestUnauthenticatedRequests:
    """A missing or unknown role is 401 before anything else is considered."""

    def test_missing_headers_and_an_unknown_role_all_answer_401(
        self, api: ApiClient, underbarrow: Dict[str, Any]
    ) -> None:
        """The unknown role gets 401 even though the path id does not exist.

        "If either header is absent, or if `X-User-Role` is not one of those five
        spellings, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)
        before anything else about the request is considered."

        Design: Corner/rbac/missing_x_user_role_header_and_unknown_roles_are_unauthenticated
        """
        association_id = underbarrow["association"]["id"]

        validate_error(
            api.get_association(association_id, HEADERS_WITHOUT_ROLE),
            ERR_UNAUTHENTICATED,
        )
        validate_error(
            api.get_association(association_id, HEADERS_WITHOUT_USER_ID),
            ERR_UNAUTHENTICATED,
        )
        unknown_role_response = api.get_association(
            NON_EXISTENT_UUID, make_headers("manager-1", UNKNOWN_ROLE_NAME)
        )
        validate_error(unknown_role_response, ERR_UNAUTHENTICATED)
        assert (
            unknown_role_response.json()["data"]["error_id"]
            != ERR_ASSOCIATION_NOT_FOUND
        ), "The 401 is chosen over the 404 the same path would otherwise produce"

    def test_a_write_without_a_role_header_creates_nothing(
        self, api: ApiClient, underbarrow: Dict[str, Any]
    ) -> None:
        """The rejected lot creation leaves the association exactly as it was.

        "**Authentication.** Both headers present and `X-User-Role` among the five
        declared roles, else `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/rbac/missing_x_user_role_header_and_unknown_roles_are_unauthenticated
        """
        association = underbarrow["association"]

        validate_error(
            api.create_lot(lot_payload(association["id"], "U-1"), HEADERS_WITHOUT_ROLE),
            ERR_UNAUTHENTICATED,
        )

        _rows, meta = validate_paginated(
            api.list_lots(association["id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 0, "No Lot row is created by a 401"

        reread = read_association(api, association["id"])
        assert reread["sold_lot_count"] == 0
        assert reread["version"] == association["version"], (
            "The rejected write is not a mutation"
        )


# ─── Vellamore: two identity gates, one window-scoped ──────────────────


@pytest.fixture
def vellamore(api: ApiClient) -> Dict[str, Any]:
    """One in-window entry posted by the future auditor, one out-of-window entry."""
    association = _seed_community(
        api,
        "Vellamore",
        fixed_turnover_date="2026-07-01T00:00:00Z",
        declarant_monthly_subsidy_cents=60000,
    )
    case = seed_turnover_case(api, association["id"], total_seats=3)
    in_window = seed_subsidy_entry(
        api,
        association["id"],
        "ACCRUAL",
        60000,
        "2026-03",
        headers=make_declarant_headers(SHARED_OPERATOR_USER_ID),
    )
    out_of_window = seed_subsidy_entry(
        api,
        association["id"],
        "ACCRUAL",
        60000,
        "2025-11",
        headers=make_declarant_headers(OUTSIDE_WINDOW_OPERATOR_USER_ID),
    )
    engagement = seed_audit_engagement(
        api,
        association["id"],
        "2026-01-01T00:00:00Z",
        "2026-06-30T00:00:00Z",
        headers=make_auditor_headers(SHARED_OPERATOR_USER_ID),
    )
    do_certify_trigger(api, case["id"], association["id"], TRIGGER_BASIS_FIXED_DATE)
    return {
        "association": association,
        "case": case,
        "in_window": in_window,
        "out_of_window": out_of_window,
        "engagement": engagement,
    }


class TestSegregationOfDutiesOnBothGates:
    """Both gates compare X-User-ID against a recorded actor."""

    def test_the_in_window_poster_cannot_issue_but_the_outside_poster_can(
        self, api: ApiClient, vellamore: Dict[str, Any]
    ) -> None:
        """shared-1 posted the March entry; outsider-2 posted only November's.

        "An `Auditor` may not issue a report on an engagement when its own
        `X-User-ID` equals the `posted_by_user_id` of any `POSTED` `SubsidyEntry`
        of that association whose `period_month` falls inside the engagement's
        window — an auditor who posted money *outside* the window is untainted and
        may still issue."

        Design: Corner/rbac/segregation_of_duties_blocks_self_review_on_both_gated_endpoints
        """
        engagement_id = vellamore["engagement"]["id"]
        assert vellamore["in_window"]["posted_by_user_id"] == SHARED_OPERATOR_USER_ID

        validate_error(
            api.issue_audit_engagement(
                engagement_id, make_auditor_headers(SHARED_OPERATOR_USER_ID)
            ),
            ERR_SEGREGATION_OF_DUTIES,
        )

        issued = do_issue_engagement(
            api, engagement_id, make_auditor_headers(OUTSIDE_WINDOW_OPERATOR_USER_ID)
        )
        assert issued["status"] == "ISSUED"
        assert issued["issued_by_user_id"] == OUTSIDE_WINDOW_OPERATOR_USER_ID
        assert issued["audited_receivable_snapshot_cents"] == 60000, (
            "Only the in-window March accrual reaches the snapshot"
        )

    def test_the_trigger_certifier_cannot_seat_a_director_but_another_user_can(
        self, api: ApiClient, vellamore: Dict[str, Any]
    ) -> None:
        """The certifier here is the committee, whose X-User-ID is the association id.

        "Seating is also refused when the acting `X-User-ID` is the same user
        recorded in `trigger_certified_by_user_id`, with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/segregation_of_duties_blocks_self_review_on_both_gated_endpoints
        """
        association_id = vellamore["association"]["id"]
        case_id = vellamore["case"]["id"]
        certified = read_turnover_case(api, case_id)
        assert certified["trigger_certified_by_user_id"] == association_id

        validate_error(
            api.seat_director(
                director_payload(
                    case_id,
                    SEAT_TYPE_DECLARANT_APPOINTED,
                    full_name="Wilhelmina Osei",
                ),
                make_declarant_headers(association_id),
            ),
            ERR_SEGREGATION_OF_DUTIES,
        )

        refused = read_turnover_case(api, case_id)
        assert refused["declarant_appointed_seats"] == 0
        assert refused["vacant_seats"] == 3

        director = validate_success(
            api.seat_director(
                director_payload(
                    case_id,
                    SEAT_TYPE_DECLARANT_APPOINTED,
                    full_name="Wilhelmina Osei",
                ),
                DECLARANT_HEADERS,
            ),
            expected_status=201,
        )
        assert director["seated_by_user_id"] == "declarant-1"

        seated = read_turnover_case(api, case_id)
        assert seated["vacant_seats"] == 2
