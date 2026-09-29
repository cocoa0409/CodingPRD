"""
Panel readiness composition, the double-booking window rule and the discipline's
concurrent-panel ceiling.
"""

from conftest import create_panel, nominate, seat

from test_helpers import (
    PROGRAM_OFFICER,
    api_client,
    assert_panel_readiness,
    assert_score,
    conflict_payload,
    cyclemain_cycle_panel_review,
    read_application,
    read_cycle,
    read_panel,
    validate_error,
    validate_success,
)


def _block(panelist_id: str, application_id: str) -> str:
    """Declare a discretionary conflict and screen it BLOCKING."""
    conflict_id = validate_success(
        api_client.create_conflict(
            conflict_payload(panelist_id, application_id, "SAME_INSTITUTION"),
            PROGRAM_OFFICER,
        ),
        expected_status=201,
    )["id"]
    validate_success(
        api_client.screen_conflict(
            conflict_id, {"disposition": "BLOCKING"}, PROGRAM_OFFICER
        )
    )
    return conflict_id


def _four_of_five_panel(ctx, window_start, window_end, email_tag, specialist=False):
    """A five-seat panel with four seated readers covering all three required regions."""
    panel_id = create_panel(
        ctx.cyc,
        ctx.disc,
        required_seats=5,
        required_regions=["NORTH", "CENTRAL", "SOUTH"],
        window_start=window_start,
        window_end=window_end,
    )
    chair = nominate(
        panel_id, f"chair.{email_tag}@example.org", "Iris Vance", "NORTH", is_chair=True
    )
    central = nominate(panel_id, f"central.{email_tag}@example.org", "Omar Diaz", "CENTRAL")
    south = nominate(
        panel_id,
        f"south.{email_tag}@example.org",
        "Neve Okoro",
        "SOUTH",
        expertise_codes=(
            ["LITERARY_ARTS", "TRADITIONAL_ARTS"] if specialist else ["LITERARY_ARTS"]
        ),
    )
    north2 = nominate(panel_id, f"north2.{email_tag}@example.org", "Piet Halvorsen", "NORTH")
    for panelist_id in (chair, central, south, north2):
        seat(panelist_id)
    return panel_id, central


class TestReadinessComposition:
    """Seat ratio, region ratio, conflict penalty and specialist bonus compose."""

    def test_the_specialist_bonus_lifts_an_otherwise_identical_four_of_five_panel(self):
        """
        Two panels seat four of five readers with full regional coverage and no conflict;
        the one carrying a traditional-arts reader scores 88.00 against the other's 80.00.

        PRD: "Apply a specialist bonus of 1.10 when at least one seated panelist carries
        `TRADITIONAL_ARTS` among their `expertise_codes`, and a bonus of 1.00 otherwise."

        Design: Difficulty/combinatorial_formula/panel_readiness_seat_region_conflict_and_specialist_bonus_compose
        """
        ctx = cyclemain_cycle_panel_review()
        plain_id, _ = _four_of_five_panel(
            ctx, "2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z", "plain"
        )
        specialist_id, _ = _four_of_five_panel(
            ctx,
            "2026-11-01T00:00:00Z",
            "2026-12-01T00:00:00Z",
            "spec",
            specialist=True,
        )

        assert_panel_readiness(
            read_panel(plain_id),
            seated_count=4,
            region_coverage_count=3,
            blocking_conflict_count=0,
            readiness_score=80.00,
        )
        assert_panel_readiness(
            read_panel(specialist_id),
            seated_count=4,
            region_coverage_count=3,
            blocking_conflict_count=0,
            readiness_score=88.00,
        )

    def test_one_blocking_conflict_drops_the_plain_panel_below_the_charter_gate(self):
        """
        A single blocking conflict on each panel multiplies both readiness figures by
        0.92: the plain panel falls to 73.60 and is refused chartering while the
        specialist panel holds at 80.96 and charters, taking the cycle's one eligible
        application with it.

        PRD: "Worked out: five of five seats with full region coverage and no conflict
        scores 100.00 after the cap; three of five seats with full coverage scores 60.00,
        which fails the gate even though quorum is met; four of five with full coverage
        scores 80.00 and passes; that same four-of-five panel with one blocking conflict
        scores 73.60 and fails; and adding a `TRADITIONAL_ARTS` specialist to it lifts the
        score to 80.96 and passes."

        Design: Difficulty/combinatorial_formula/panel_readiness_seat_region_conflict_and_specialist_bonus_compose
        """
        ctx = cyclemain_cycle_panel_review()
        plain_id, plain_central = _four_of_five_panel(
            ctx, "2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z", "plain"
        )
        specialist_id, specialist_central = _four_of_five_panel(
            ctx,
            "2026-11-01T00:00:00Z",
            "2026-12-01T00:00:00Z",
            "spec",
            specialist=True,
        )
        _block(plain_central, ctx.app1)
        _block(specialist_central, ctx.app1)

        assert_panel_readiness(
            read_panel(plain_id),
            seated_count=4,
            region_coverage_count=3,
            blocking_conflict_count=1,
            readiness_score=73.60,
        )
        assert_panel_readiness(
            read_panel(specialist_id),
            seated_count=4,
            region_coverage_count=3,
            blocking_conflict_count=1,
            readiness_score=80.96,
        )
        for recused in (plain_central, specialist_central):
            panelist = validate_success(api_client.get_panelist(recused, PROGRAM_OFFICER))
            assert panelist["status"] == "RECUSED", (
                f"a blocking conflict recuses its panelist, got {panelist['status']}"
            )

        validate_error(
            api_client.charter_panel(plain_id, PROGRAM_OFFICER), "ERR_PANEL_NOT_READY"
        )
        assert read_panel(plain_id)["status"] == "FORMING", (
            "a refused charter leaves the panel FORMING"
        )

        chartered = validate_success(
            api_client.charter_panel(specialist_id, PROGRAM_OFFICER)
        )
        assert chartered["status"] == "CHARTERED", (
            f"a readiness of 80.96 clears the 75.00 gate, got {chartered['status']}"
        )
        assert chartered["assigned_application_count"] == 1, (
            "the charter sweep should attach the cycle's one eligible application, got "
            f"{chartered['assigned_application_count']}"
        )


class TestPanelistWindowOverlap:
    """One human may not hold two seats over intersecting deliberation windows."""

    def test_an_intersecting_window_refuses_the_second_seating(self):
        """
        The same person seated on a panel deliberating from 1 November to 1 December
        cannot also be seated on a panel deliberating from 15 November to 15 December.

        PRD: "It also enforces the double-booking rule: no other panelist with the same
        `person_email` may already be `SEATED` on another panel of the same cycle whose
        half-open deliberation window intersects this panel's window, and a collision is
        rejected with `ERR_PANELIST_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/same_person_seated_on_panels_with_half_open_window_overlap
        """
        ctx = cyclemain_cycle_panel_review()
        email = "roving.reader@example.org"
        panel_w = create_panel(
            ctx.cyc,
            ctx.disc,
            window_start="2026-11-01T00:00:00Z",
            window_end="2026-12-01T00:00:00Z",
        )
        panel_x = create_panel(
            ctx.cyc,
            ctx.disc,
            window_start="2026-11-15T00:00:00Z",
            window_end="2026-12-15T00:00:00Z",
        )
        rov_w = nominate(panel_w, email, "Rowan Vega", "NORTH")
        rov_x = nominate(panel_x, email, "Rowan Vega", "NORTH")

        assert seat(rov_w)["status"] == "SEATED", "the first seating should succeed"

        validate_error(
            api_client.seat_panelist(rov_x, PROGRAM_OFFICER),
            "ERR_PANELIST_WINDOW_CONFLICT",
        )
        blocked = validate_success(api_client.get_panelist(rov_x, PROGRAM_OFFICER))
        assert blocked["status"] == "NOMINATED", (
            f"the refused nomination stays NOMINATED, got {blocked['status']}"
        )
        assert blocked["seated_at"] is None, "seated_at must stay null on a refused seating"
        assert_panel_readiness(
            read_panel(panel_x),
            seated_count=0,
            region_coverage_count=0,
            blocking_conflict_count=0,
            readiness_score=0.0,
        )

    def test_a_window_that_starts_where_another_ends_is_not_a_collision(self):
        """
        The half-open interval lets the same person take a second seat on a panel whose
        deliberation begins at the exact instant the first one ends, and that seating
        recomputes the new panel's coverage and readiness to 11.11.

        PRD: "Because the intervals are half-open, a panel that starts at the exact
        instant another ends is not a conflict."

        Design: Difficulty/resource_temporal_overlap/same_person_seated_on_panels_with_half_open_window_overlap
        """
        ctx = cyclemain_cycle_panel_review()
        email = "roving.reader@example.org"
        panel_w = create_panel(
            ctx.cyc,
            ctx.disc,
            window_start="2026-11-01T00:00:00Z",
            window_end="2026-12-01T00:00:00Z",
        )
        panel_y = create_panel(
            ctx.cyc,
            ctx.disc,
            window_start="2026-12-01T00:00:00Z",
            window_end="2027-01-01T00:00:00Z",
        )
        seat(nominate(panel_w, email, "Rowan Vega", "NORTH"))
        rov_y = nominate(panel_y, email, "Rowan Vega", "NORTH")

        assert seat(rov_y)["status"] == "SEATED", (
            "an abutting window must not be treated as an intersection"
        )
        assert_panel_readiness(
            read_panel(panel_y),
            seated_count=1,
            region_coverage_count=1,
            blocking_conflict_count=0,
            readiness_score=11.11,
        )


class TestDisciplinePanelCapacity:
    """Only panels in an active status occupy the discipline's concurrency ceiling."""

    def _ready_panel(self, ctx, tag, window_start, window_end):
        panel_id = create_panel(
            ctx.cyc,
            ctx.disc,
            required_seats=3,
            required_regions=["NORTH", "CENTRAL", "SOUTH"],
            window_start=window_start,
            window_end=window_end,
        )
        seat(nominate(panel_id, f"n.{tag}@example.org", "Nia Brandt", "NORTH", is_chair=True))
        seat(nominate(panel_id, f"c.{tag}@example.org", "Otto Lind", "CENTRAL"))
        seat(nominate(panel_id, f"s.{tag}@example.org", "Pia Novak", "SOUTH"))
        return panel_id

    def test_an_overlapping_second_charter_exceeds_the_concurrency_ceiling(self):
        """
        With the discipline capped at one concurrent panel, chartering a fully ready panel
        whose deliberation window intersects an already chartered one is refused and
        leaves the second panel untouched.

        PRD: "And the discipline's concurrency ceiling must hold: among panels of the same
        `discipline_category_id` whose status is `CHARTERED`, `SCORING`, `DELIBERATING` or
        `SLATE_SUBMITTED`, the number whose half-open deliberation window intersects this
        panel's window must be strictly fewer than the discipline's
        `max_concurrent_panels`, and an excess is rejected with
        `ERR_DISCIPLINE_PANEL_CAPACITY`."

        Design: Difficulty/resource_temporal_overlap/discipline_concurrent_panel_capacity_counts_only_active_panels
        """
        ctx = cyclemain_cycle_panel_review()
        panel_p = self._ready_panel(ctx, "p", "2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z")
        panel_q = self._ready_panel(ctx, "q", "2026-11-15T00:00:00Z", "2026-12-15T00:00:00Z")

        for panel_id in (panel_p, panel_q):
            panel = read_panel(panel_id)
            assert_score(panel["readiness_score"], 100.00, "panel.readiness_score")
            assert panel["quorum_min_reviews"] == 3, (
                "a three-seat panel needs three counted reviews, got "
                f"{panel['quorum_min_reviews']}"
            )

        first = validate_success(api_client.charter_panel(panel_p, PROGRAM_OFFICER))
        assert first["assigned_application_count"] == 1, (
            f"the first charter takes the eligible application, got {first['assigned_application_count']}"
        )

        validate_error(
            api_client.charter_panel(panel_q, PROGRAM_OFFICER),
            "ERR_DISCIPLINE_PANEL_CAPACITY",
        )
        blocked = read_panel(panel_q)
        assert blocked["status"] == "FORMING", (
            f"the refused panel stays FORMING, got {blocked['status']}"
        )
        assert blocked["chartered_by"] is None, "chartered_by must stay null"
        assert blocked["assigned_application_count"] == 0, (
            "no application may be attached by a refused charter"
        )
        assert read_application(ctx.app1)["assigned_panel_id"] == panel_p, (
            "the application should remain attached to the first panel"
        )

    def test_a_disjoint_window_charters_and_finds_nothing_left_to_assign(self):
        """
        A panel whose window begins where the chartered one ends clears the concurrency
        ceiling and charters, but its sweep finds no unassigned eligible application and
        attaches none.

        PRD: "A successful charter moves the panel `FORMING → CHARTERED`, stamps
        `chartered_by` with the acting officer's `X-User-ID`, and then sweeps the cycle in
        application `created_at` ascending order: every application of the cycle whose
        `discipline_category_id` matches the panel's, whose `status` is `ELIGIBLE`, whose
        `assigned_panel_id` is `null` and whose `anonymity_status` is `SEALED` or
        `REDACTED` moves `ELIGIBLE → UNDER_REVIEW` with `assigned_panel_id` set to this
        panel."

        Design: Difficulty/resource_temporal_overlap/discipline_concurrent_panel_capacity_counts_only_active_panels
        """
        ctx = cyclemain_cycle_panel_review()
        panel_p = self._ready_panel(ctx, "p", "2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z")
        panel_r = self._ready_panel(ctx, "r", "2026-12-01T00:00:00Z", "2027-01-01T00:00:00Z")
        validate_success(api_client.charter_panel(panel_p, PROGRAM_OFFICER))

        chartered = validate_success(api_client.charter_panel(panel_r, PROGRAM_OFFICER))
        assert chartered["status"] == "CHARTERED", (
            f"a disjoint window should charter, got {chartered['status']}"
        )
        assert chartered["assigned_application_count"] == 0, (
            "the already assigned application must not be swept a second time, got "
            f"{chartered['assigned_application_count']}"
        )
        assert read_cycle(ctx.cyc)["status"] == "PANEL_REVIEW", (
            "chartering does not move the cycle"
        )
