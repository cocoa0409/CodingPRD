"""Dispersal logging, take-permit accounting: provisional vs authoritative
reconciliation, budget boundary, permit validity window."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    assert_take_permit,
    set_clock,
    create_airport,
    create_species,
    create_biologist,
    setup_permit_scenario,
    create_logged_dispersal,
    review_dispersal,
    close_dispersal,
    make_biologist_headers,
    ApiErrorId,
)


def test_dispersal_activity_initial_state_logged(api):
    """PRD §3.4: "New dispersals enter in `LOGGED`. The dispersal list view
    supports filtering by `airport_id`, `performed_by_biologist_id`, `status`,
    `method`, `species_id`, and `take_permit_id`, as well as by time range via
    `performed_after` and `performed_before` bounds on the `performed_at`
    field."

    Design: Corner/state_machines/dispersal_activity_initial_state_logged
    """
    set_clock()
    airport = create_airport(icao_code="KFFF", name="Foxtrot Airport")
    sp = create_species(
        common_name="House Sparrow", scientific_name="Passer domesticus",
        guild="SONGBIRD", risk_tier="LOW", body_mass_g=30,
        is_protected_federally=False,
    )
    b2 = create_biologist(airport["id"], is_senior=False, certification_id="CERT-F01")
    dispersal = validate_success(
        api.create_dispersal_activity(
            {
                "airport_id": airport["id"],
                "performed_by_biologist_id": b2["id"],
                "performed_at": "2026-07-15T10:00:00Z",
                "method": "PYROTECHNICS",
                "species_id": sp["id"],
                "animals_dispersed": 5,
                "animals_taken_lethal": 0,
            },
            make_biologist_headers(b2["id"]),
        ),
        201,
    )
    assert dispersal["status"] == "LOGGED"


class TestTakeReconciliationVariants:
    """Authoritative take_consumed counts CLOSED only; the preview projection
    additionally counts REVIEWED."""

    def _setup_closed_plus_reviewed(self, icao_code):
        ctx = setup_permit_scenario(icao_code=icao_code, authorized_take_total=10,
                                    permit_number="MB0001-00")
        # D1: lethal take 3, fully closed.
        d1 = create_logged_dispersal(
            ctx["airport"]["id"], ctx["performer"], ctx["species"]["id"],
            performed_at="2026-07-15T10:00:00Z", animals_taken_lethal=3,
            take_permit_id=ctx["permit"]["id"],
        )
        review_dispersal(d1["id"], ctx["senior"])
        close_dispersal(d1["id"], ctx["senior"])
        # D2: lethal take 2, left in REVIEWED.
        d2 = create_logged_dispersal(
            ctx["airport"]["id"], ctx["performer"], ctx["species"]["id"],
            performed_at="2026-07-20T10:00:00Z", animals_dispersed=4,
            animals_taken_lethal=2, take_permit_id=ctx["permit"]["id"],
        )
        review_dispersal(d2["id"], ctx["senior"])
        return ctx, d1, d2

    def test_authoritative_take_consumed_counts_closed_only(self, api):
        """PRD §3.4: "the permit's `take_consumed` must equal the sum of
        `animals_taken_lethal` across every `CLOSED` dispersal referencing the
        permit."

        Design: Difficulty/dual_variant_calc/permit_take_reconciliation_provisional_vs_authoritative
        """
        ctx, d1, d2 = self._setup_closed_plus_reviewed("KBBB")
        permit = validate_success(
            api.get_take_permit(ctx["permit"]["id"], ctx["regulator_headers"]), 200,
        )
        assert_take_permit(permit)
        assert permit["take_consumed"] == 3, (
            f"only the CLOSED dispersal (take 3) counts, got "
            f"{permit['take_consumed']}"
        )
        assert permit["status"] == "ACTIVE"

    def test_provisional_take_preview_includes_reviewed(self, api):
        """PRD §4: GET /wildlife/take-permits/{id}/take-preview — "Projected
        take_consumed including REVIEWED (provisional)".
        PRD §3.4: "the permit's `take_consumed` must equal the sum of
        `animals_taken_lethal` across every `CLOSED` dispersal referencing the
        permit."

        Design: Difficulty/dual_variant_calc/permit_take_reconciliation_provisional_vs_authoritative
        """
        ctx, d1, d2 = self._setup_closed_plus_reviewed("KBBD")
        preview = validate_success(
            api.get_take_preview(ctx["permit"]["id"], ctx["regulator_headers"]), 200,
        )
        assert preview["projected_take_consumed"] == 5, (
            f"preview counts CLOSED(3) + REVIEWED(2) = 5, got "
            f"{preview['projected_take_consumed']}"
        )

        # The provisional read must not persist: authoritative value stays 3.
        permit = validate_success(
            api.get_take_permit(ctx["permit"]["id"], ctx["regulator_headers"]), 200,
        )
        assert permit["take_consumed"] == 3


class TestTakeBudgetBoundary:
    """At take_consumed + proposed == authorized_take_total the close
    succeeds; anything above is rejected."""

    def test_close_at_exact_budget_succeeds_and_exhausts_permit(self, api):
        """PRD §3.4: "`take_consumed` plus the proposed `animals_taken_lethal`
        must not exceed the permit's `authorized_take_total`"
        PRD §3.4: "A permit in `ACTIVE` moves to `EXHAUSTED` when
        `take_consumed` reaches `authorized_take_total` after a dispersal
        closure"

        Design: Difficulty/boundary_precision_check/take_budget_exhaustion_at_exact_boundary
        """
        ctx = setup_permit_scenario(icao_code="KLLL", authorized_take_total=5,
                                    permit_number="MB0003-00")
        d1 = create_logged_dispersal(
            ctx["airport"]["id"], ctx["performer"], ctx["species"]["id"],
            performed_at="2026-07-15T10:00:00Z", animals_taken_lethal=3,
            take_permit_id=ctx["permit"]["id"],
        )
        review_dispersal(d1["id"], ctx["senior"])
        close_dispersal(d1["id"], ctx["senior"])

        d2 = create_logged_dispersal(
            ctx["airport"]["id"], ctx["performer"], ctx["species"]["id"],
            performed_at="2026-07-16T10:00:00Z", animals_dispersed=3,
            animals_taken_lethal=2, take_permit_id=ctx["permit"]["id"],
        )
        review_dispersal(d2["id"], ctx["senior"])
        closed = close_dispersal(d2["id"], ctx["senior"])
        assert closed["status"] == "CLOSED"

        permit = validate_success(
            api.get_take_permit(ctx["permit"]["id"], ctx["regulator_headers"]), 200,
        )
        assert permit["take_consumed"] == 5, (
            f"3 + 2 must land exactly at the authorized total, got "
            f"{permit['take_consumed']}"
        )
        assert permit["status"] == "EXHAUSTED", (
            f"permit must auto-exhaust at the boundary, got {permit['status']}"
        )

    def test_close_over_budget_rejected_without_partial_consumption(self, api):
        """PRD §3.4: "a closure that would overrun the budget is rejected with
        `ERR_TAKE_BUDGET_EXCEEDED` (HTTP 422). Successful closure with lethal
        take recomputes the permit's `take_consumed`."

        Design: Difficulty/boundary_precision_check/take_budget_exhaustion_at_exact_boundary
        """
        ctx = setup_permit_scenario(icao_code="KLLM", authorized_take_total=5,
                                    permit_number="MB0003-01")
        # Create the over-budget dispersal first (while nothing is consumed),
        # then a second dispersal that lawfully consumes the whole budget.
        d_over = create_logged_dispersal(
            ctx["airport"]["id"], ctx["performer"], ctx["species"]["id"],
            performed_at="2026-07-16T10:00:00Z", animals_dispersed=4,
            animals_taken_lethal=3, take_permit_id=ctx["permit"]["id"],
        )
        d_full = create_logged_dispersal(
            ctx["airport"]["id"], ctx["performer"], ctx["species"]["id"],
            performed_at="2026-07-15T10:00:00Z", animals_taken_lethal=5,
            take_permit_id=ctx["permit"]["id"],
        )
        review_dispersal(d_full["id"], ctx["senior"])
        close_dispersal(d_full["id"], ctx["senior"])
        permit = validate_success(
            api.get_take_permit(ctx["permit"]["id"], ctx["regulator_headers"]), 200,
        )
        assert permit["take_consumed"] == 5

        review_dispersal(d_over["id"], ctx["senior"])
        res = api.close_dispersal_activity(
            d_over["id"], ctx["senior_headers"],
        )
        assert res.status_code == 422, (
            f"over-budget close must be a 422, got {res.status_code}: {res.text}"
        )
        validate_error_is_one_of(res, [
            ApiErrorId.ERR_TAKE_BUDGET_EXCEEDED.value,
            ApiErrorId.ERR_TAKE_PERMIT_REQUIRED.value,
        ])

        d_over_after = validate_success(
            api.get_dispersal_activity(d_over["id"], ctx["senior_headers"]), 200,
        )
        assert d_over_after["status"] == "REVIEWED", (
            "no partial consumption: the rejected close leaves the dispersal "
            "in REVIEWED"
        )
        permit_after = validate_success(
            api.get_take_permit(ctx["permit"]["id"], ctx["regulator_headers"]), 200,
        )
        assert permit_after["take_consumed"] == 5


class TestPermitValidityWindow:
    """Permit validity window is inclusive on both ends."""

    def _setup_july_permit(self):
        ctx = setup_permit_scenario(
            icao_code="KPPP", authorized_take_total=10,
            valid_from="2026-07-01", valid_to="2026-07-31",
            clock="2026-07-15T00:00:00Z", permit_number="MB0004-00",
        )
        assert ctx["permit"]["status"] == "ACTIVE"
        return ctx

    def test_dispersals_at_window_boundaries_accepted(self, api):
        """PRD §3.4: "Take permits are issued by a `RegulatorAgent` and carry
        the `airport_id`, the `species_id`, the `issued_by_regulator_id`, a
        unique `permit_number`, an `authorized_take_total` of at least one,
        and a validity window from `valid_from` to `valid_to` inclusive."
        PRD §3.4: "Independently, the `performed_at` timestamp must fall
        within the permit's `valid_from` to `valid_to` window inclusive;
        violations surface `ERR_PERMIT_OUTSIDE_WINDOW`."

        Design: Difficulty/resource_temporal_overlap/permit_validity_window_inclusive_boundary
        """
        ctx = self._setup_july_permit()
        d_start = validate_success(
            api.create_dispersal_activity(
                {
                    "airport_id": ctx["airport"]["id"],
                    "performed_by_biologist_id": ctx["performer"]["id"],
                    "performed_at": "2026-07-01T00:00:00Z",
                    "method": "PYROTECHNICS",
                    "species_id": ctx["species"]["id"],
                    "animals_dispersed": 5,
                    "animals_taken_lethal": 1,
                    "take_permit_id": ctx["permit"]["id"],
                },
                ctx["performer_headers"],
            ),
            201,
        )
        assert d_start["status"] == "LOGGED"

        d_end = validate_success(
            api.create_dispersal_activity(
                {
                    "airport_id": ctx["airport"]["id"],
                    "performed_by_biologist_id": ctx["performer"]["id"],
                    "performed_at": "2026-07-31T23:59:59Z",
                    "method": "PYROTECHNICS",
                    "species_id": ctx["species"]["id"],
                    "animals_dispersed": 3,
                    "animals_taken_lethal": 1,
                    "take_permit_id": ctx["permit"]["id"],
                },
                ctx["performer_headers"],
            ),
            201,
        )
        assert d_end["status"] == "LOGGED"

    def test_dispersal_outside_window_rejected(self, api):
        """PRD §3.4: "Independently, the `performed_at` timestamp must fall
        within the permit's `valid_from` to `valid_to` window inclusive;
        violations surface `ERR_PERMIT_OUTSIDE_WINDOW`."

        Design: Difficulty/resource_temporal_overlap/permit_validity_window_inclusive_boundary
        """
        ctx = self._setup_july_permit()
        for performed_at in ("2026-08-01T00:00:00Z", "2026-06-30T23:59:59Z"):
            res = api.create_dispersal_activity(
                {
                    "airport_id": ctx["airport"]["id"],
                    "performed_by_biologist_id": ctx["performer"]["id"],
                    "performed_at": performed_at,
                    "method": "PYROTECHNICS",
                    "species_id": ctx["species"]["id"],
                    "animals_dispersed": 2,
                    "animals_taken_lethal": 1,
                    "take_permit_id": ctx["permit"]["id"],
                },
                ctx["performer_headers"],
            )
            validate_error(
                res, ApiErrorId.ERR_PERMIT_OUTSIDE_WINDOW.value, expected_status=422,
            )
