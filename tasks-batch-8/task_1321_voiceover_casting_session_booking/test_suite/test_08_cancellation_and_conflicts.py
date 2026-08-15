"""Project cancellation cascades, optimistic-concurrency on cancel, and the
exclusivity conflict window lifecycle."""
from test_helpers import (
    ApiErrorId,
    assert_conflict_exclusion,
    cancel_project,
    create_cast_project,
    create_client,
    create_project,
    create_session,
    create_studio,
    create_talent,
    get_talent,
    get_talent_conflict_exclusions,
    make_client_headers,
    open_casting,
    set_clock,
    setup_cast_with_exclusivity,
    submit_audition,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import CD, get_project, get_session


class TestProjectCancelCascade:
    def test_cancel_releases_cast_conflict_exclusion(self, api):
        """PRD §3.9: "every `ACTIVE` conflict exclusion created by this project
        is `RELEASED` (with `active_conflict_categories` refreshed as in
        Section 3.5)".

        Design: Difficulty/transitive_cascade/project_cancel_cascades_depth3
        """
        ctx = setup_cast_with_exclusivity(product_category="AUTOMOTIVE",
                                          term_months=12)
        exclusions = ctx["exclusions"]
        assert len(exclusions) == 1
        assert exclusions[0]["status"] == "ACTIVE"

        cancel_project(ctx["project"])
        assert get_project(ctx["project"]["id"])["status"] == "CANCELLED"
        after = get_talent_conflict_exclusions(ctx["talent"]["id"])
        assert after[0]["status"] == "RELEASED"

    def test_cancel_clears_active_conflict_categories(self, api):
        """PRD §3.5: "On either release or expiry, the affected
        `product_category` is removed from the talent's
        `active_conflict_categories` — but only if no other still-`ACTIVE`
        exclusion covers the same category."

        Design: Difficulty/transitive_cascade/project_cancel_cascades_depth3
        """
        ctx = setup_cast_with_exclusivity(product_category="AUTOMOTIVE",
                                          term_months=12)
        assert "AUTOMOTIVE" in get_talent(ctx["talent"]["id"])["active_conflict_categories"]
        cancel_project(ctx["project"])
        talent = get_talent(ctx["talent"]["id"])
        assert "AUTOMOTIVE" not in talent["active_conflict_categories"]
        assert talent["active_conflict_categories"] == []


class TestCancelRestoresCastingEligibility:
    def test_active_conflict_categories_return_to_baseline(self, api):
        """PRD §3.5: "The `active_conflict_categories` array on the talent
        record is therefore a pure derivation: it contains the distinct product
        categories of that talent's exclusions that are `ACTIVE` and whose
        window currently contains the clock".

        Design: Difficulty/compensating_invariant/project_cancel_releases_conflict_exclusion
        """
        talent = create_talent()
        assert get_talent(talent["id"])["active_conflict_categories"] == []
        ctx = setup_cast_with_exclusivity(talent=talent,
                                          product_category="AUTOMOTIVE",
                                          term_months=12)
        assert get_talent(talent["id"])["active_conflict_categories"] == ["AUTOMOTIVE"]
        cancel_project(ctx["project"])
        # Invariant: after the forward action (cast) and the compensating
        # action (cancel), the derived array equals its pre-forward baseline.
        assert get_talent(talent["id"])["active_conflict_categories"] == []

    def test_talent_castable_in_same_category_after_cancel(self, api):
        """PRD §3.4: "When the project's `exclusivity_required` is true, the
        selected talent must hold no `ACTIVE` conflict exclusion in the
        project's `product_category` ... a live conflict is rejected with
        `ERR_TALENT_CONFLICT` (HTTP 409)." PRD §3.9: "every `ACTIVE` conflict
        exclusion created by this project is `RELEASED`".

        Design: Difficulty/compensating_invariant/project_cancel_releases_conflict_exclusion
        """
        talent = create_talent()
        ctx = setup_cast_with_exclusivity(talent=talent,
                                          product_category="AUTOMOTIVE",
                                          term_months=12)
        cancel_project(ctx["project"])

        # With the exclusion released, a new exclusivity project in the same
        # category may cast the same talent.
        client2 = create_client()
        project2 = create_project(client2, product_category="AUTOMOTIVE",
                                  usage_type="TERM", term_months=6,
                                  exclusivity_required=True)
        open_casting(project2["id"])
        audition2 = submit_audition(project2["id"], talent)
        resp = api.select_talent(project2["id"], audition2["id"],
                                 make_client_headers(client2["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CAST"


class TestCancelSessionCascade:
    def test_cascading_cancel_releases_sessions(self, api):
        """PRD §3.9: "A successful cancellation moves the project to the
        terminal `CANCELLED` state, increments its `version` by one, and tears
        down its dependents in one cascade: every audition still in `SUBMITTED`
        or `SHORTLISTED` moves to `REJECTED`; every `TENTATIVE` session moves
        to `CANCELLED`".

        Design: Corner/cross_cutting_complexity_layers/cascading_cancel_releases_sessions
        """
        ctx = create_cast_project()
        studio = create_studio()
        session = create_session(ctx["project"]["id"], studio)  # TENTATIVE
        cancelled = cancel_project(ctx["project"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["version"] == ctx["project"]["version"] + 1
        assert get_session(session["id"])["status"] == "CANCELLED"


class TestCancelOccAndLockdown:
    def test_project_cancel_occ_version_conflict(self, api):
        """PRD §2.7: "If the project's version has advanced since that read —
        for example because a session was confirmed in the meantime — the
        cancellation is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/endpoints/project_cancel_occ_version_conflict
        """
        client = create_client()
        project = create_project(client)
        stale_version = project["version"]
        open_casting(project["id"])  # mutates the project: version advances
        resp = api.cancel_project(project["id"], stale_version,
                                  make_client_headers(client["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_project_terminal_cancelled_lockdown(self, api):
        """PRD §3.9: "A successful cancellation moves the project to the
        terminal `CANCELLED` state". PRD §3.2: opening casting moves "the
        project `DRAFT → CASTING`" — a cancelled project is not in DRAFT, so
        the state check rejects the transition with `ERR_INVALID_STATE`.

        Design: Corner/state_machines/project_terminal_cancelled_lockdown
        """
        client = create_client()
        project = create_project(client)
        cancel_project(project)
        assert get_project(project["id"])["status"] == "CANCELLED"
        resp = api.open_casting(project["id"], CD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestOpenCastingInvalidTransition:
    def test_project_open_casting_from_casting_returns_invalid_state(self, api):
        """PRD §3.2: "When the brief is ready, a `CastingDirector` opens
        casting, moving the project `DRAFT → CASTING`." PRD §2.10: "then
        whether the target resource is in a valid state for the requested
        transition (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/project_open_casting_from_casting_returns_invalid_state
        """
        client = create_client()
        project = create_project(client)
        validate_success(api.open_casting(project["id"], CD), expected_status=200)
        resp = api.open_casting(project["id"], CD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestConflictWindowLifecycle:
    def test_conflict_exclusion_expire_via_clock(self, api):
        """PRD §2.5: "Advancing the clock has one immediate housekeeping
        effect: any `ACTIVE` conflict exclusion whose `ends_at` is at or before
        the new clock value is lazily expired." PRD §3.5: "On either release or
        expiry, the affected `product_category` is removed from the talent's
        `active_conflict_categories`".

        Design: Corner/state_machines/conflict_exclusion_expire_via_clock
        """
        ctx = setup_cast_with_exclusivity(product_category="AUTOMOTIVE",
                                          term_months=1)
        assert "AUTOMOTIVE" in get_talent(ctx["talent"]["id"])["active_conflict_categories"]
        # Window opened at 2026-08-01 and ends 2026-09-01; move past it.
        set_clock("2026-09-15T00:00:00Z")
        talent = get_talent(ctx["talent"]["id"])
        assert "AUTOMOTIVE" not in talent["active_conflict_categories"]
        exclusion = validate_success(
            api.get_conflict_exclusion(ctx["exclusions"][0]["id"], CD),
            expected_status=200,
        )
        assert exclusion["status"] == "EXPIRED"

    def test_derived_field_active_conflicts_updates_on_release(self, api):
        """PRD §3.5: "Every exclusion begins in `ACTIVE` status and ends in one
        of two terminal states: `RELEASED`, reached when a `CastingDirector`
        manually releases it or when the originating project is cancelled".
        PRD §3.5: "On either release or expiry, the affected `product_category`
        is removed from the talent's `active_conflict_categories`".

        Design: Corner/cross_cutting_complexity_layers/derived_field_active_conflicts_updates_on_release
        """
        ctx = setup_cast_with_exclusivity(product_category="AUTOMOTIVE",
                                          term_months=12)
        exclusion = ctx["exclusions"][0]
        assert_conflict_exclusion(exclusion)
        assert "AUTOMOTIVE" in get_talent(ctx["talent"]["id"])["active_conflict_categories"]

        released = validate_success(
            api.release_conflict_exclusion(exclusion["id"], CD), expected_status=200)
        assert released["status"] == "RELEASED"
        assert get_talent(ctx["talent"]["id"])["active_conflict_categories"] == []
