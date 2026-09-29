"""
The four identity gates in their declared order: authentication, role
authorization, ownership and the two segregation-of-duties rules.
"""

from conftest import register_artist

from test_helpers import (
    APPEALS_OFFICER,
    APPEALS_OFFICER_ID,
    BOARD_MEMBER,
    FISCAL_OFFICER,
    FISCAL_OFFICER_ID,
    PROGRAM_OFFICER,
    PROGRAM_OFFICER_ID,
    api_client,
    assert_cents,
    cornermain_application_draft,
    cornermain_cycle_awarded,
    cornermain_cycle_open,
    cornermain_slate_submitted,
    cycle_version,
    make_artist_headers,
    make_headers,
    read_application,
    read_cycle,
    set_clock,
    validate_error,
    validate_success,
)

NO_HEADERS = {"Content-Type": "application/json"}


def _read_slot(slot_id):
    return validate_success(api_client.get_slot(slot_id, PROGRAM_OFFICER))


class TestAuthenticationComesFirst:
    """An unrecognized role is an identity failure, not a permission one."""

    def test_absent_unknown_and_empty_identities_are_all_unauthenticated(self):
        """
        A request carrying no identity headers, one naming a role outside the declared six and
        one whose acting user is empty are each refused as unauthenticated rather than as
        forbidden or as a missing resource, while the same read with well-formed headers
        succeeds.

        PRD: "A request with a missing or empty `X-User-ID`, or with an `X-User-Role` that is
        missing or that names anything outside the six declared roles, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401) — an unrecognized role is treated as a failure to
        establish identity, not as a permission problem."

        Design: Corner/rbac/missing_or_unknown_auth_headers_returns_unauthenticated
        """
        ctx = cornermain_cycle_open()

        for headers in (
            NO_HEADERS,
            make_headers("auditor-1", "ExternalAuditor"),
            make_headers("", "ProgramOfficer"),
        ):
            validate_error(
                api_client.get_cycle(ctx.cyc, headers), "ERR_UNAUTHENTICATED"
            )

        cycle = validate_success(api_client.get_cycle(ctx.cyc, PROGRAM_OFFICER))
        assert cycle["status"] == "OPEN", (
            f"well-formed headers read the cycle, got {cycle['status']}"
        )
        assert_cents(cycle["available_cents"], 5_700_000, "cycle.available_cents")


class TestRoleAuthorizationPrecedesEverything:
    """Four exclusive operations and one unbacked entity identity."""

    def test_five_authenticated_callers_are_each_outside_their_endpoints_list(self):
        """
        An artist advancing a cycle, a panelist recording an eligibility determination, a fiscal
        officer acting on a slot and a board member screening an appeal are all refused for their
        role before any version, state or path lookup is evaluated, and an artist-role caller
        whose acting id backs no artist row is refused the same way rather than reported missing.

        PRD: "Once identity is established, the role must appear in the acting endpoint's
        authorized-role list; otherwise the request is rejected with `ERR_UNAUTHORIZED` (HTTP
        403)."

        PRD: "This role gate is evaluated before any body parsing and before any path lookup, so
        an unauthorized caller can never learn whether a resource exists or whether their payload
        was well-formed."

        PRD: "An `X-User-ID` that resolves to no `Artist` row cannot act at all and is rejected
        with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/a_role_cannot_invoke_another_roles_exclusive_operation
        """
        ctx = cornermain_slate_submitted()
        expected = cycle_version(ctx.cyc)

        validate_error(
            api_client.set_cycle_status(ctx.cyc, "AWARDED", ctx.art_headers),
            "ERR_UNAUTHORIZED",
        )
        assert read_cycle(ctx.cyc)["status"] == "BOARD_REVIEW", (
            "the refused advance changes nothing"
        )

        validate_error(
            api_client.determine_eligibility(
                ctx.app, {"determination": "ELIGIBLE"}, ctx.pl1_headers
            ),
            "ERR_UNAUTHORIZED",
        )
        validate_error(
            api_client.board_action(
                ctx.slot,
                {"action": "APPROVE", "expected_cycle_version": expected},
                FISCAL_OFFICER,
            ),
            "ERR_UNAUTHORIZED",
        )
        assert _read_slot(ctx.slot)["status"] == "PROPOSED", (
            "the role gate runs ahead of the version comparison"
        )

        validate_error(
            api_client.screen_appeal(ctx.slot, BOARD_MEMBER), "ERR_UNAUTHORIZED"
        )
        validate_error(
            api_client.withdraw_application(
                ctx.app, make_headers(PROGRAM_OFFICER_ID, "Artist")
            ),
            "ERR_UNAUTHORIZED",
        )
        assert read_application(ctx.app)["status"] == "SCORED", (
            "none of the five refusals touched the application"
        )


class TestOwnershipStopsAForeignArtist:
    """A real artist row is not enough; it has to be the right one."""

    def test_a_stranger_cannot_submit_amend_withdraw_or_file_for_another(self):
        """
        A second registered artist is refused on four operations against the first artist's
        draft — including a submit that would also have failed the package rules — the draft is
        untouched by all four, and the owner's identical submit then succeeds.

        PRD: "An `Artist` caller acting on another artist's application, work sample, award,
        final report or appeal is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403); for an
        application the comparison runs through the application's `artist_id`, for a work sample
        and an appeal through the owning application, and for an award, an installment or a final
        report through the award's `artist_id`."

        PRD: "An `Artist` caller may only name their own `artist_id` and is otherwise rejected
        with `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/rbac/an_artist_cannot_act_on_another_artists_application
        """
        ctx = cornermain_application_draft()
        stranger = register_artist(
            "Emil Roux", "emil.roux@example.org", "2022-06-05", "SOUTH"
        )
        stranger_headers = make_artist_headers(stranger)

        validate_error(
            api_client.submit_application(ctx.app, stranger_headers),
            "ERR_NOT_RESOURCE_OWNER",
        )
        validate_error(
            api_client.create_work_sample(
                {
                    "application_id": ctx.app,
                    "medium": "MANUSCRIPT_PAGES",
                    "ordinal": 3,
                    "page_count": 4,
                    "contains_identifying_metadata": False,
                },
                stranger_headers,
            ),
            "ERR_NOT_RESOURCE_OWNER",
        )
        validate_error(
            api_client.withdraw_application(ctx.app, stranger_headers),
            "ERR_NOT_RESOURCE_OWNER",
        )
        validate_error(
            api_client.create_application(
                {
                    "cycle_id": ctx.cyc,
                    "discipline_category_id": ctx.disc,
                    "artist_id": ctx.art,
                    "artist_statement": "Filed on someone else's behalf.",
                    "career_narrative": "Not mine to file.",
                },
                stranger_headers,
            ),
            "ERR_NOT_RESOURCE_OWNER",
        )

        draft = read_application(ctx.app)
        assert draft["status"] == "DRAFT", (
            f"the draft is untouched by the four refusals, got {draft['status']}"
        )
        assert draft["work_sample_count"] == 2, (
            f"no fifth sample was attached, got {draft['work_sample_count']}"
        )

        submitted = validate_success(
            api_client.submit_application(ctx.app, ctx.art_headers)
        )
        assert submitted["status"] == "SUBMITTED", (
            f"the owner's identical call succeeds, got {submitted['status']}"
        )
        assert submitted["sealed_alias"] == "LIT-2027-0001", (
            f"the submission mints the sealed alias, got {submitted['sealed_alias']}"
        )


class TestReleaseSegregation:
    """Same role, same request, different acting user."""

    def test_the_board_member_who_approved_the_award_cannot_release_its_money(self):
        """
        Acting in the fiscal role but under the identity that approved the award, the release is
        refused for segregation of duties even on the installment that is additionally not yet
        due, and the independent officer's identical call succeeds.

        PRD: "The `FiscalOfficer` who releases an installment must have an `X-User-ID` different
        from the `approved_by_user_id` stored on that installment's award — the board member who
        committed the money may not also move it."

        PRD: "Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and the
        check runs after ownership but before any concurrency, state or business evaluation."

        Design: Corner/rbac/the_approving_board_member_may_not_release_the_payment
        """
        ctx = cornermain_cycle_awarded()
        set_clock("2027-01-01T00:00:00Z")
        approver = make_headers("board-1", "FiscalOfficer")

        validate_error(
            api_client.release_installment(ctx.i1, approver), "ERR_SEGREGATION_OF_DUTIES"
        )
        first = validate_success(api_client.get_installment(ctx.i1, FISCAL_OFFICER))
        assert first["status"] == "SCHEDULED", (
            f"the refused release leaves the row scheduled, got {first['status']}"
        )
        assert first["released_by"] is None, (
            f"nothing was stamped, got {first['released_by']}"
        )

        validate_error(
            api_client.release_installment(ctx.i2, approver), "ERR_SEGREGATION_OF_DUTIES"
        )

        released = validate_success(api_client.release_installment(ctx.i1, FISCAL_OFFICER))
        assert released["status"] == "RELEASED", (
            f"the independent officer may release, got {released['status']}"
        )
        assert released["released_by"] == FISCAL_OFFICER_ID, (
            f"the acting officer is stamped, got {released['released_by']}"
        )
        assert str(released["released_at"]).startswith("2027-01-01"), (
            f"the release is stamped from the clock, got {released['released_at']}"
        )


class TestAppealDecisionSegregation:
    """The officer under appeal may not rule on the appeal."""

    def test_the_officer_who_determined_eligibility_cannot_decide_either_way(self):
        """
        Both an uphold and a denial are refused when the deciding identity is the one recorded as
        having determined the application's eligibility, leaving the appeal screened and
        undecided, and the independent appeals officer's uphold then runs the remedy.

        PRD: "The `AppealsOfficer` who decides an appeal must have an `X-User-ID` different from
        the `eligibility_determined_by` stored on the appealed application — the officer whose
        determination is under appeal may not rule on it."

        PRD: "Both branches require the owning cycle to be `CLOSED` or `PANEL_REVIEW`, otherwise
        `ERR_CYCLE_STATE_INVALID`, and both stamp `eligibility_determined_by` with the acting
        officer's `X-User-ID` — the value that will later bar that same officer from deciding
        this application's appeal."

        Design: Corner/rbac/the_determining_officer_may_not_decide_the_appeal
        """
        ctx = cornermain_slate_submitted()
        assert read_application(ctx.app)["eligibility_determined_by"] == PROGRAM_OFFICER_ID, (
            "the determination recorded the acting officer"
        )
        validate_success(
            api_client.board_action(
                ctx.slot,
                {
                    "action": "STRIKE",
                    "expected_cycle_version": cycle_version(ctx.cyc),
                    "struck_reason_code": "BUDGET",
                },
                BOARD_MEMBER,
            )
        )
        appeal = validate_success(
            api_client.create_appeal(
                {
                    "application_id": ctx.app,
                    "grounds_code": "PANEL_COMPOSITION_DEFECT",
                    "statement": "No reader from my region was seated.",
                },
                ctx.art_headers,
            ),
            expected_status=201,
        )
        validate_success(api_client.screen_appeal(appeal["id"], APPEALS_OFFICER))

        conflicted = make_headers(PROGRAM_OFFICER_ID, "AppealsOfficer")
        validate_error(
            api_client.decide_appeal(
                appeal["id"],
                {"decision": "UPHOLD", "remedy_code": "REISSUE_SLATE"},
                conflicted,
            ),
            "ERR_SEGREGATION_OF_DUTIES",
        )
        validate_error(
            api_client.decide_appeal(appeal["id"], {"decision": "DENY"}, conflicted),
            "ERR_SEGREGATION_OF_DUTIES",
        )
        pending = validate_success(api_client.get_appeal(appeal["id"], APPEALS_OFFICER))
        assert pending["status"] == "SCREENED", (
            f"the appeal is still awaiting a decision, got {pending['status']}"
        )
        assert pending["decided_by"] is None, (
            f"no decider was stamped, got {pending['decided_by']}"
        )

        decided = validate_success(
            api_client.decide_appeal(
                appeal["id"],
                {"decision": "UPHOLD", "remedy_code": "REISSUE_SLATE"},
                APPEALS_OFFICER,
            )
        )
        assert decided["status"] == "UPHELD", (
            f"the independent officer may decide, got {decided['status']}"
        )
        assert decided["remedy_code"] == "REISSUE_SLATE", (
            f"the remedy is recorded, got {decided['remedy_code']}"
        )
        assert decided["decided_by"] == APPEALS_OFFICER_ID, (
            f"the deciding officer is stamped, got {decided['decided_by']}"
        )
        assert _read_slot(ctx.slot)["status"] == "PROPOSED", (
            "the remedy reissues the struck slot"
        )
        assert read_application(ctx.app)["status"] == "SCORED", (
            "the application returns to scored"
        )
