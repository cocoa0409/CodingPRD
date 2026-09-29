"""Per-entity not-found codes and the access rules that outrank them: role
lists, member self-scope, dual control and header authentication.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    build_user_headers,
    create_published_tier,
    enrol_member,
    read_coverage_area,
    read_funder,
    read_gift_offer,
    read_member,
    register_coverage_area,
    setup_cleared_funder,
    setup_cleared_gift_offer,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    BO_HEADERS,
    DO2_HEADERS,
    DO_HEADERS,
    ED_HEADERS,
    FC_HEADERS,
)
from test_helpers.test_users import USER_IDS, make_member_headers

_UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


class TestUnknownIdsReturnEntitySpecificNotFoundCodes:
    def test_thirteen_reads_on_one_unknown_uuid_return_thirteen_codes(self):
        """The same syntactically valid identifier produces a different 404 code on
        each collection, in the order the ladder lists them.

        PRD: "Path-parameter existence, resolved strictly left to right. Each entity
        has its own not-found code, and the code returned is the one belonging to the
        *first* path segment that fails to resolve: `ERR_FISCAL_PERIOD_NOT_FOUND`,
        `ERR_MEMBERSHIP_TIER_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
        `ERR_COVERAGE_AREA_NOT_FOUND`, `ERR_FUNDER_NOT_FOUND`,
        `ERR_DISCLOSURE_NOT_FOUND`, `ERR_INFLUENCE_CONTACT_NOT_FOUND`,
        `ERR_GIFT_OFFER_NOT_FOUND`, `ERR_GRANT_PROPOSAL_NOT_FOUND`,
        `ERR_GRANT_REPORT_NOT_FOUND`, `ERR_CONTRIBUTION_NOT_FOUND`,
        `ERR_COLLABORATION_NOT_FOUND` and `ERR_PARTNER_NOT_FOUND` (all HTTP 404)."

        Design: Corner/Errors/err_unknown_ids_return_entity_specific_not_found_codes
        """
        reads = [
            (api_client.get_fiscal_period, ApiErrorId.ERR_FISCAL_PERIOD_NOT_FOUND),
            (api_client.get_membership_tier, ApiErrorId.ERR_MEMBERSHIP_TIER_NOT_FOUND),
            (api_client.get_member, ApiErrorId.ERR_MEMBER_NOT_FOUND),
            (api_client.get_coverage_area, ApiErrorId.ERR_COVERAGE_AREA_NOT_FOUND),
            (api_client.get_funder, ApiErrorId.ERR_FUNDER_NOT_FOUND),
            (api_client.get_firewall_disclosure, ApiErrorId.ERR_DISCLOSURE_NOT_FOUND),
            (
                api_client.get_influence_contact,
                ApiErrorId.ERR_INFLUENCE_CONTACT_NOT_FOUND,
            ),
            (api_client.get_gift_offer, ApiErrorId.ERR_GIFT_OFFER_NOT_FOUND),
            (api_client.get_grant_proposal, ApiErrorId.ERR_GRANT_PROPOSAL_NOT_FOUND),
            (api_client.get_grant_report, ApiErrorId.ERR_GRANT_REPORT_NOT_FOUND),
            (api_client.get_contribution, ApiErrorId.ERR_CONTRIBUTION_NOT_FOUND),
            (api_client.get_collaboration, ApiErrorId.ERR_COLLABORATION_NOT_FOUND),
            (api_client.get_collaboration_partner, ApiErrorId.ERR_PARTNER_NOT_FOUND),
        ]
        assert len(reads) == 13

        for read, expected_error in reads:
            response = read(_UNKNOWN_ID, DO_HEADERS)
            assert response.status_code == 404
            validate_error(response, expected_error)

    def test_none_of_the_failed_reads_creates_a_row(self):
        """Thirteen 404s leave every collection empty.

        PRD: "Validation proceeds in a fixed ladder and the **first** violated rule
        decides the response; no later rule is evaluated and no partial mutation is
        ever written."

        Design: Corner/Errors/err_unknown_ids_return_entity_specific_not_found_codes
        """
        for read in (
            api_client.get_fiscal_period,
            api_client.get_membership_tier,
            api_client.get_member,
            api_client.get_coverage_area,
            api_client.get_funder,
        ):
            read(_UNKNOWN_ID, DO_HEADERS)

        for listing in (
            api_client.list_fiscal_periods,
            api_client.list_membership_tiers,
            api_client.list_members,
            api_client.list_coverage_areas,
            api_client.list_funders,
            api_client.list_gift_offers,
            api_client.list_grant_proposals,
            api_client.list_contributions,
        ):
            _, meta = validate_paginated(listing(DO_HEADERS))
            assert meta["total_count"] == 0


def _release(headers):
    return api_client.release_restricted_funds(
        _UNKNOWN_ID, {"request_amount_cents": 100000}, headers
    )


class TestDevelopmentOfficerCannotReleaseRestrictedFunds:
    def test_the_role_gate_answers_before_the_proposal_is_looked_up(self):
        """The officer learns nothing about which proposals exist, because
        authorization sits above path-parameter existence on the ladder.

        PRD: "Authorization - the supplied role appears on the endpoint's role list
        (`ERR_UNAUTHORIZED`)."

        Design: Corner/RBAC/rbac_development_officer_cannot_release_restricted_funds
        """
        response = _release(DO_HEADERS)
        assert response.status_code == 403
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

    def test_the_authorized_controller_reaches_the_existence_check(self):
        """The identical body under the finance role gets as far as resolving the
        path id, and reports the proposal's own not-found code.

        PRD: "Path-parameter existence, resolved strictly left to right."

        Design: Corner/RBAC/rbac_development_officer_cannot_release_restricted_funds
        """
        response = _release(FC_HEADERS)
        assert response.status_code == 404
        validate_error(response, ApiErrorId.ERR_GRANT_PROPOSAL_NOT_FOUND)


_PERIOD_BODY = {
    "label": "FY2027",
    "start_date": "2026-08-01",
    "end_date": "2027-07-31",
    "monthly_expense_base_cents": 200000,
    "reserve_balance_cents": 500000,
}


class TestBoardOversightCannotOpenAFiscalPeriod:
    def test_the_board_is_refused_at_creation_and_nothing_is_opened(self):
        """The board may override the reserve policy on a period but may not create
        one.

        PRD: "**`BoardOversight`** - board-level oversight. Ratifies large or
        elevated-risk gifts and records reserve/concentration overrides. Read-only
        everywhere else, and never originates funding activity."

        Design: Corner/RBAC/rbac_board_oversight_cannot_open_a_fiscal_period
        """
        response = api_client.create_fiscal_period(dict(_PERIOD_BODY), BO_HEADERS)
        assert response.status_code == 403
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

        _, meta = validate_paginated(api_client.list_fiscal_periods(BO_HEADERS))
        assert meta["total_count"] == 0

    def test_the_identical_body_opens_the_period_under_finance(self):
        """Only the role header changes between the refusal and the 201.

        PRD: "A period opens in status `OPEN` with `board_override_active` false,
        `board_override_justification` null and `locked_at` null"

        Design: Corner/RBAC/rbac_board_oversight_cannot_open_a_fiscal_period
        """
        validate_error(
            api_client.create_fiscal_period(dict(_PERIOD_BODY), BO_HEADERS),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

        created = validate_success(
            api_client.create_fiscal_period(dict(_PERIOD_BODY), FC_HEADERS),
            expected_status=201,
        )
        assert created["status"] == "OPEN"
        assert created["label"] == "FY2027"
        assert created["board_override_active"] is False
        assert created["locked_at"] is None


def _setup_published_tier_and_one_member():
    """One published tier and one enrolled member."""
    tier = create_published_tier(
        benefits=[],
        tier_code="SUSTAINER",
        name="Sustainer",
        renewal_cadence="MONTHLY",
        contribution_amount_cents=2500,
    )
    member = enrol_member(tier["id"], email="ana@example.org", full_name="Ana Ruiz")
    return {"tier": tier, "member": member}


class TestBoardOversightAndEditorialDirectorCannotReadMemberRows:
    def test_neither_the_board_nor_the_newsroom_may_reach_donor_identity(self):
        """Both member endpoints refuse the two roles that may read every funder,
        gift offer and grant row.

        PRD: "If the headers are well formed but the supplied role is not among the
        roles authorized for the requested endpoint (§4), the request is rejected
        with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/RBAC/rbac_board_oversight_and_editorial_director_cannot_read_member_rows
        """
        ctx = _setup_published_tier_and_one_member()

        validate_error(
            api_client.list_members(BO_HEADERS), ApiErrorId.ERR_UNAUTHORIZED
        )
        validate_error(
            api_client.get_member(ctx["member"]["id"], BO_HEADERS),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
        validate_error(
            api_client.list_members(ED_HEADERS), ApiErrorId.ERR_UNAUTHORIZED
        )
        validate_error(
            api_client.get_member(ctx["member"]["id"], ED_HEADERS),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

    def test_the_same_row_is_readable_by_the_enrolling_officer(self):
        """The wall is around the role, not around the row: the officer reads the
        email the two refused roles could not see.

        PRD: "A member row may be read individually, and the collection may be listed
        with optional `tier_id`, `linked_funder_id`, `status` and `is_major_donor`
        filters."

        Design: Corner/RBAC/rbac_board_oversight_and_editorial_director_cannot_read_member_rows
        """
        ctx = _setup_published_tier_and_one_member()
        validate_error(
            api_client.get_member(ctx["member"]["id"], ED_HEADERS),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

        row = validate_success(api_client.get_member(ctx["member"]["id"], DO_HEADERS))
        assert row["email"] == "ana@example.org"
        assert row["full_name"] == "Ana Ruiz"
        assert row["status"] == "PENDING"

        rows, meta = validate_paginated(api_client.list_members(FC_HEADERS))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == ctx["member"]["id"]


def _setup_two_members_on_one_tier():
    """One published tier and two enrolled members on it."""
    tier = create_published_tier(
        benefits=[],
        tier_code="SUSTAINER",
        name="Sustainer",
        renewal_cadence="MONTHLY",
        contribution_amount_cents=2500,
    )
    first = enrol_member(tier["id"], email="ana@example.org", full_name="Ana Ruiz")
    second = enrol_member(tier["id"], email="bo@example.org", full_name="Bo Nkemelu")
    return {"tier": tier, "first": first, "second": second}


class TestMemberCannotReadAnotherMembersRow:
    def test_a_sibling_row_is_out_of_scope_rather_than_unauthorized(self):
        """The `Member` role is on the endpoint's role list, so the refusal comes
        from the self-scope rung instead.

        PRD: "A `Member` caller may only read the member row whose `id` equals
        `X-User-ID`, may only drive lifecycle actions and tier changes on that same
        row, may only create a contribution whose `member_id` equals `X-User-ID`,
        and may only read a contribution whose `member_id` equals `X-User-ID`."

        Design: Corner/RBAC/rbac_member_cannot_read_another_members_row
        """
        ctx = _setup_two_members_on_one_tier()

        response = api_client.get_member(
            ctx["second"]["id"], make_member_headers(ctx["first"]["id"])
        )
        assert response.status_code == 403
        validate_error(response, ApiErrorId.ERR_MEMBER_SCOPE_FORBIDDEN)

    def test_the_same_endpoint_returns_the_callers_own_row(self):
        """Scope is decided by comparing `X-User-ID` with the addressed row, so the
        identical read of the caller's own id succeeds.

        PRD: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting
        `Member` row, and ownership is enforced by comparing the addressed resource
        against that id."

        Design: Corner/RBAC/rbac_member_cannot_read_another_members_row
        """
        ctx = _setup_two_members_on_one_tier()
        own = validate_success(
            api_client.get_member(
                ctx["first"]["id"], make_member_headers(ctx["first"]["id"])
            )
        )
        assert own["id"] == ctx["first"]["id"]
        assert own["email"] == "ana@example.org"

    def test_a_lifecycle_action_on_the_sibling_is_refused_and_changes_nothing(self):
        """Writes are scoped exactly as reads are, and the sibling row is untouched.

        PRD: "Any of those four operations addressed at another member's data is
        rejected with `ERR_MEMBER_SCOPE_FORBIDDEN` (HTTP 403)."

        Design: Corner/RBAC/rbac_member_cannot_read_another_members_row
        """
        ctx = _setup_two_members_on_one_tier()

        validate_error(
            api_client.member_lifecycle_action(
                ctx["second"]["id"],
                {"action": "CANCEL"},
                make_member_headers(ctx["first"]["id"]),
            ),
            ApiErrorId.ERR_MEMBER_SCOPE_FORBIDDEN,
        )

        untouched = read_member(ctx["second"]["id"])
        assert untouched["status"] == "PENDING"
        assert untouched["version"] == ctx["second"]["version"]


def _setup_cleared_400000_offer():
    """A CLEARED foundation and an unrestricted 400000-cent gift offer solicited by
    user-do-1 and cleared by user-ed-1."""
    return setup_cleared_gift_offer(
        offered_amount_cents=400000, designation="UNRESTRICTED"
    )


def _accept(offer_id, headers):
    return api_client.accept_gift_offer(
        offer_id, {"received_date": "2026-08-01"}, headers
    )


class TestSolicitorCannotAcceptTheGiftTheySolicited:
    def test_the_soliciting_officer_is_refused_by_dual_control(self):
        """Both callers hold the same role; the refusal keys on `X-User-ID` against
        the offer's `solicited_by_user_id`.

        PRD: "Accepting a gift offer requires that the acting `X-User-ID` differ from
        the offer's `solicited_by_user_id`, and so does ruling on that offer in
        independence review."

        Design: Corner/RBAC/rbac_solicitor_cannot_accept_the_gift_they_solicited
        """
        ctx = _setup_cleared_400000_offer()
        assert ctx["offer"]["solicited_by_user_id"] == USER_IDS["development_officer"]

        response = _accept(ctx["offer"]["id"], DO_HEADERS)
        assert response.status_code == 403
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        assert read_gift_offer(ctx["offer"]["id"])["status"] == "CLEARED"

    def test_a_second_officer_completes_the_same_call_and_writes_the_contribution(self):
        """The identical request from user-do-2 lands the gift and creates the
        contribution the client never asked for.

        PRD: "Acceptance takes the offer to the terminal status `ACCEPTED` and writes
        a contribution the client never asked for: a row on the `MAJOR_GIFT` revenue
        stream carrying this offer's `funder_id` and `gift_offer_id`, an
        `amount_cents` equal to `net_acceptable_amount_cents` - the **net**, not the
        gross - settlement status `INITIATED` and acknowledgment status
        `UNACKNOWLEDGED`."

        Design: Corner/RBAC/rbac_solicitor_cannot_accept_the_gift_they_solicited
        """
        ctx = _setup_cleared_400000_offer()
        validate_error(
            _accept(ctx["offer"]["id"], DO_HEADERS),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )

        accepted = validate_success(_accept(ctx["offer"]["id"], DO2_HEADERS))
        assert accepted["status"] == "ACCEPTED"
        assert accepted["net_acceptable_amount_cents"] == 400000
        assert accepted["board_ratification_required"] is False

        rows, meta = validate_paginated(
            api_client.list_contributions(
                FC_HEADERS, params={"gift_offer_id": ctx["offer"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["revenue_stream"] == "MAJOR_GIFT"
        assert rows[0]["amount_cents"] == 400000
        assert rows[0]["received_date"] == "2026-08-01"
        assert rows[0]["settlement_status"] == "INITIATED"
        assert rows[0]["acknowledgment_status"] == "UNACKNOWLEDGED"


def _setup_cultivated_funder_and_a_beat():
    """A funder cultivated by user-do-1 and then cleared, plus one coverage area."""
    area = register_coverage_area(area_code="CLIMATE", name="Climate")
    funder = setup_cleared_funder(legal_name="Ironwood Trust")
    return {"area": area, "funder": read_funder(funder["id"])}


def _file(funder, area_id, headers):
    return api_client.create_firewall_disclosure(
        {
            "funder_id": funder["id"],
            "coverage_area_id": area_id,
            "disclosure_text": (
                "Ironwood funds climate coverage; the climate desk retains "
                "editorial control."
            ),
            "expected_funder_version": funder["version"],
        },
        headers,
    )


class TestDisclosureAuthorCannotBeTheFunderCultivator:
    def test_the_cultivating_identity_is_refused_even_under_the_right_role(self):
        """The acting role is the required `EditorialDirector`, but the acting
        `X-User-ID` is the funder's cultivator.

        PRD: "Concretely, filing a firewall disclosure requires that the acting
        `X-User-ID` differ from the funder's `cultivated_by_user_id`; re-attesting a
        stale disclosure carries the same requirement."

        Design: Corner/RBAC/rbac_disclosure_author_cannot_be_the_funder_cultivator
        """
        ctx = _setup_cultivated_funder_and_a_beat()
        assert ctx["funder"]["cultivated_by_user_id"] == USER_IDS[
            "development_officer"
        ]

        cultivator_as_director = build_user_headers(
            USER_IDS["development_officer"], "EditorialDirector"
        )
        response = _file(ctx["funder"], ctx["area"]["id"], cultivator_as_director)
        assert response.status_code == 403
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        _, meta = validate_paginated(api_client.list_firewall_disclosures(ED_HEADERS))
        assert meta["total_count"] == 0
        assert read_coverage_area(ctx["area"]["id"])["disclosed_funder_count"] == 0

    def test_a_different_director_files_the_identical_disclosure(self):
        """Only the acting identity changes, and the beat then counts its first
        disclosed funder.

        PRD: "It is enforced on `X-User-ID`: the user who cultivated money may never
        be the user who clears it, attests to its disclosure, or ratifies it at board
        level, regardless of which role header that user presents."

        Design: Corner/RBAC/rbac_disclosure_author_cannot_be_the_funder_cultivator
        """
        ctx = _setup_cultivated_funder_and_a_beat()
        validate_error(
            _file(
                ctx["funder"],
                ctx["area"]["id"],
                build_user_headers(
                    USER_IDS["development_officer"], "EditorialDirector"
                ),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )

        filed = validate_success(
            _file(ctx["funder"], ctx["area"]["id"], ED_HEADERS), expected_status=201
        )
        assert filed["status"] == "ACTIVE"
        assert filed["attested_by_user_id"] == USER_IDS["editorial_director"]

        assert read_coverage_area(ctx["area"]["id"])["disclosed_funder_count"] == 1


class TestUndeclaredRoleHeaderIsUnauthenticatedNotUnauthorized:
    def test_a_role_outside_the_five_fails_the_presence_check_first(self):
        """`Auditor` never reaches the endpoint's role list, so the answer is 401
        rather than the 403 an unauthorized declared role would get.

        PRD: "If either header is absent, or if `X-User-Role` is not one of the five
        role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
        401)."

        Design: Corner/RBAC/rbac_undeclared_role_header_is_unauthenticated_not_unauthorized
        """
        response = api_client.list_fiscal_periods(
            build_user_headers("user-au-1", "Auditor")
        )
        assert response.status_code == 401
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_a_missing_user_id_header_is_the_same_401(self):
        """A declared role with no acting identity fails the same rung, and no
        period is opened.

        PRD: "Every request must carry two headers: `X-User-ID`, identifying the
        acting user, and `X-User-Role`, naming the capacity in which that user is
        acting."

        Design: Corner/RBAC/rbac_undeclared_role_header_is_unauthenticated_not_unauthorized
        """
        headerless = {"X-User-Role": "FinanceController"}
        response = api_client.create_fiscal_period(dict(_PERIOD_BODY), headerless)
        assert response.status_code == 401
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)

        _, meta = validate_paginated(api_client.list_fiscal_periods(FC_HEADERS))
        assert meta["total_count"] == 0
