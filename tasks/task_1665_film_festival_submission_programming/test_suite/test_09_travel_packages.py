"""Travel packages: stipend computation, budget/hotel clamps, cancellation
penalties, and the approval OCC guard (PRD §2.7, §2.8, §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_inv_hotel, assert_inv_travel,
    fx_responded,
    st_approve_package, st_submit_package,
    validate_error, validate_success,
    TEST_USERS,
)

TRAVEL = TEST_USERS["travel_headers"]


def _package_ctx(api, *, edition_over=None, films=1, capacity_slots=1):
    """Edition NOTIFICATION with all invited films accepted (packages DRAFT)."""
    return fx_responded(
        films=films, capacity_slots=capacity_slots,
        sign_agreements=False, edition_over=edition_over,
    )


class TestStipendVariants:
    def test_travel_stipend_variant_values(self, api):
        """PRD §3.7: "The `raw_stipend_cents` is the uncapped-by-budget
        figure: a base of 50000 cents domestic or 150000 cents international,
        plus 20000 cents for each covered delegate beyond the first, with at
        most 2 delegates covered"; "an international production sending 3
        delegates computes 150000 plus a single 20000 allowance, 170000
        cents, below the cap; a domestic solo delegate computes 50000."

        Design: Corner/calculations/travel_stipend_variant_values
        """
        ctx = _package_ctx(api, films=[
            {"title": "Domestic"},
            {"title": "International",
             "submitter_over": {"country_of_residence": "FR"}},
        ], capacity_slots=2)
        dom, intl = ctx["films"][0], ctx["films"][1]

        pkg_d = st_submit_package(
            ctx["packages"][0]["id"], dom["submitter"]["id"],
            {"delegate_count": 1, "origin_country_code": "US",
             "hotel_nights_requested": 2},
        )
        assert pkg_d["is_international"] is False
        assert pkg_d["raw_stipend_cents"] == 50000

        pkg_i = st_submit_package(
            ctx["packages"][1]["id"], intl["submitter"]["id"],
            {"delegate_count": 2, "origin_country_code": "FR",
             "hotel_nights_requested": 2},
        )
        assert pkg_i["is_international"] is True
        assert pkg_i["raw_stipend_cents"] == 170000


class TestStipendClamp:
    def _international_clamp_ctx(self, api):
        """One FR film confirmed; edition travel budget exactly 100000."""
        ctx = _package_ctx(
            api,
            edition_over={"travel_budget_cents": 100000},
            films=[{"title": "Marseille Nights",
                    "submitter_over": {"country_of_residence": "FR"}}],
        )
        spec = ctx["films"][0]
        package = st_submit_package(
            ctx["packages"][0]["id"], spec["submitter"]["id"],
            {"delegate_count": 3, "origin_country_code": "FR",
             "hotel_nights_requested": 6},
        )
        return ctx, spec, package

    def test_raw_computed_then_clamped_by_budget(self, api):
        """PRD §3.7: "On approval the package's `stipend_cents` is set to the
        smaller of `raw_stipend_cents` and the edition's
        `travel_budget_remaining` computed without this package — so a raw
        figure of 170000 against 100000 remaining commits exactly 100000."

        Design: Difficulty/combinatorial_formula/travel_stipend_multi_input_clamp
        """
        ctx, _spec, package = self._international_clamp_ctx(api)
        assert package["is_international"] is True
        assert package["raw_stipend_cents"] == 170000, (
            "150000 + 20000 * (min(3, 2) - 1); the 200000 per-film cap is "
            "not reached"
        )

        approved = st_approve_package(package["id"], ctx["edition"]["id"])
        assert approved["stipend_cents"] == 100000

    def test_hotel_allocation_and_remaining_pools_after_approval(self, api):
        """PRD §3.7: "`hotel_nights_allocated` is set to the smaller of
        `hotel_nights_requested` and the edition's `hotel_nights_remaining`"
        and "Approval recomputes the edition's travel and hotel aggregates".

        Design: Difficulty/combinatorial_formula/travel_stipend_multi_input_clamp
        """
        ctx, _spec, package = self._international_clamp_ctx(api)
        approved = st_approve_package(package["id"], ctx["edition"]["id"])
        assert approved["hotel_nights_allocated"] == 6  # min(6, pool 10)

        edition = validate_success(api.get_edition(ctx["edition"]["id"], TRAVEL))
        assert edition["travel_budget_remaining"] == 0
        assert edition["hotel_nights_remaining"] == 4
        assert_inv_travel(edition)
        assert_inv_hotel(edition)


class TestHotelPoolClamp:
    def _two_package_ctx(self, api):
        ctx = _package_ctx(api, films=[{"title": "Hotel A"},
                                       {"title": "Hotel B"}],
                           capacity_slots=2)
        pkg_a = st_submit_package(
            ctx["packages"][0]["id"], ctx["films"][0]["submitter"]["id"],
            {"delegate_count": 1, "origin_country_code": "US",
             "hotel_nights_requested": 6},
        )
        pkg_b = st_submit_package(
            ctx["packages"][1]["id"], ctx["films"][1]["submitter"]["id"],
            {"delegate_count": 1, "origin_country_code": "US",
             "hotel_nights_requested": 5},
        )
        return ctx, pkg_a, pkg_b

    def test_second_approval_clamps_to_remaining_pool(self, api):
        """PRD §3.7: "`hotel_nights_allocated` is set to the smaller of
        `hotel_nights_requested` and the edition's `hotel_nights_remaining`"
        — a clamp, not an error, so the approval still lands `APPROVED`.

        Design: Difficulty/resource_temporal_overlap/hotel_pool_aggregate_capacity_clamp
        """
        ctx, pkg_a, pkg_b = self._two_package_ctx(api)
        edition_id = ctx["edition"]["id"]

        approved_a = st_approve_package(pkg_a["id"], edition_id)
        assert approved_a["hotel_nights_allocated"] == 6  # min(6, 10)

        approved_b = st_approve_package(pkg_b["id"], edition_id)
        assert approved_b["status"] == "APPROVED"
        assert approved_b["hotel_nights_allocated"] == 4, (
            "requested 5 with only 4 remaining: clamped, not rejected"
        )

    def test_pool_fully_consumed_after_clamp(self, api):
        """PRD §2.8: "`hotel_nights_remaining` equals `hotel_nights_pool`
        minus that allocation; the invariant INV-HOTEL holds at all times —
        allocated nights plus remaining nights always equal the pool."

        Design: Difficulty/resource_temporal_overlap/hotel_pool_aggregate_capacity_clamp
        """
        ctx, pkg_a, pkg_b = self._two_package_ctx(api)
        edition_id = ctx["edition"]["id"]
        st_approve_package(pkg_a["id"], edition_id)
        st_approve_package(pkg_b["id"], edition_id)

        edition = validate_success(api.get_edition(edition_id, TRAVEL))
        assert edition["hotel_nights_allocated"] == 10
        assert edition["hotel_nights_remaining"] == 0
        assert_inv_hotel(edition)


class TestHotelConservation:
    def _approved_ctx(self, api):
        ctx = _package_ctx(api, films=[{"title": "Nights"}])
        spec = ctx["films"][0]
        package = st_submit_package(
            ctx["packages"][0]["id"], spec["submitter"]["id"],
            {"delegate_count": 1, "origin_country_code": "US",
             "hotel_nights_requested": 6},
        )
        return ctx, spec, package

    def test_approve_allocates_from_pool(self, api):
        """PRD §3.7: on approval "`hotel_nights_allocated` is set to the
        smaller of `hotel_nights_requested` and the edition's
        `hotel_nights_remaining`"; §2.8 pins INV-HOTEL: "allocated nights
        plus remaining nights always equal the pool."

        Design: Difficulty/compensating_invariant/hotel_nights_conservation_across_approve_cancel
        """
        ctx, _spec, package = self._approved_ctx(api)
        approved = st_approve_package(package["id"], ctx["edition"]["id"])
        assert approved["hotel_nights_allocated"] == 6

        edition = validate_success(api.get_edition(ctx["edition"]["id"], TRAVEL))
        assert edition["hotel_nights_allocated"] == 6
        assert edition["hotel_nights_remaining"] == 4
        assert_inv_hotel(edition)

    def test_cancel_returns_nights_to_pool(self, api):
        """PRD §3.7: cancellation "moves an `APPROVED` or `BOOKED` package to
        terminal `CANCELLED`: the allocated hotel nights and committed
        stipend are released back to the edition's pools by zeroing
        `hotel_nights_allocated` and `stipend_cents` ... Either way the
        edition aggregates recompute, restoring the INV-HOTEL and INV-TRAVEL
        invariants of §2.8."

        Design: Difficulty/compensating_invariant/hotel_nights_conservation_across_approve_cancel
        """
        ctx, _spec, package = self._approved_ctx(api)
        st_approve_package(package["id"], ctx["edition"]["id"])

        cancelled = validate_success(
            api.cancel_travel_package(package["id"], TRAVEL)
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["hotel_nights_allocated"] == 0
        assert cancelled["stipend_cents"] == 0
        assert cancelled["penalty_cents"] == 0, (
            "cancelling a merely APPROVED package carries no penalty"
        )

        edition = validate_success(api.get_edition(ctx["edition"]["id"], TRAVEL))
        assert edition["hotel_nights_allocated"] == 0
        assert edition["hotel_nights_remaining"] == 10
        assert_inv_hotel(edition)


class TestTravelBudgetConservation:
    def _booked_ctx(self, api):
        ctx = _package_ctx(api, films=[{"title": "Budget"}])
        spec = ctx["films"][0]
        package = st_submit_package(
            ctx["packages"][0]["id"], spec["submitter"]["id"],
            {"delegate_count": 1, "origin_country_code": "US",
             "hotel_nights_requested": 2},
        )
        return ctx, package

    def test_booked_cancel_forfeits_quarter_penalty(self, api):
        """PRD §3.7: "a package cancelled from `BOOKED` additionally forfeits
        a cancellation penalty — `penalty_cents` is one quarter of the
        package's original stipend, rounded half up, and flows into the
        edition's `travel_penalty_sink_cents`."

        Design: Difficulty/compensating_invariant/travel_budget_conservation_with_penalty_sink
        """
        ctx, package = self._booked_ctx(api)
        approved = st_approve_package(package["id"], ctx["edition"]["id"])
        assert approved["stipend_cents"] == 50000  # domestic base, 1 delegate
        booked = validate_success(api.mark_travel_booked(package["id"], TRAVEL))
        assert booked["status"] == "BOOKED"

        cancelled = validate_success(
            api.cancel_travel_package(package["id"], TRAVEL)
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["penalty_cents"] == 12500, (
            "round_half_up(50000 * 0.25) forfeited from the BOOKED package"
        )
        assert cancelled["stipend_cents"] == 0

    def test_inv_travel_holds_across_penalty(self, api):
        """PRD §2.8: "These three figures obey a standing invariant,
        INV-TRAVEL: the remaining budget plus the committed amount plus the
        penalty sink always equals the edition's `travel_budget_cents`."

        Design: Difficulty/compensating_invariant/travel_budget_conservation_with_penalty_sink
        """
        ctx, package = self._booked_ctx(api)
        st_approve_package(package["id"], ctx["edition"]["id"])
        validate_success(api.mark_travel_booked(package["id"], TRAVEL))
        validate_success(api.cancel_travel_package(package["id"], TRAVEL))

        edition = validate_success(api.get_edition(ctx["edition"]["id"], TRAVEL))
        assert edition["travel_committed_cents"] == 0
        assert edition["travel_penalty_sink_cents"] == 12500
        assert edition["travel_budget_remaining"] == 387500
        assert_inv_travel(edition)


class TestFiscalGuards:
    def test_travel_budget_exhausted_blocks_approval(self, api):
        """PRD §3.7: "Two resource gates guard approval: an edition whose
        `travel_budget_remaining` has reached zero rejects with
        `ERR_TRAVEL_BUDGET_EXHAUSTED`."

        Design: Corner/validations/travel_budget_exhausted_blocks_approval
        """
        ctx = _package_ctx(api, edition_over={"travel_budget_cents": 0},
                           films=[{"title": "Broke"}])
        spec = ctx["films"][0]
        package = st_submit_package(
            ctx["packages"][0]["id"], spec["submitter"]["id"],
            {"delegate_count": 1, "origin_country_code": "US",
             "hotel_nights_requested": 2},
        )
        edition = validate_success(api.get_edition(ctx["edition"]["id"], TRAVEL))
        blocked = api.approve_travel_package(
            package["id"], edition["version"], TRAVEL,
        )
        validate_error(blocked, ApiErrorId.ERR_TRAVEL_BUDGET_EXHAUSTED.value)

        after = validate_success(api.get_travel_package(package["id"], TRAVEL))
        assert after["status"] == "SUBMITTED"
        assert after["stipend_cents"] == 0

    def test_hotel_nights_exhausted_blocks_approval(self, api):
        """PRD §3.7: "an edition whose `hotel_nights_remaining` has reached
        zero rejects with `ERR_HOTEL_NIGHTS_EXHAUSTED`."

        Design: Corner/validations/hotel_nights_exhausted_blocks_approval
        """
        ctx = _package_ctx(api, edition_over={"hotel_nights_pool": 0},
                           films=[{"title": "No Rooms"}])
        spec = ctx["films"][0]
        package = st_submit_package(
            ctx["packages"][0]["id"], spec["submitter"]["id"],
            {"delegate_count": 1, "origin_country_code": "US",
             "hotel_nights_requested": 2},
        )
        edition = validate_success(api.get_edition(ctx["edition"]["id"], TRAVEL))
        blocked = api.approve_travel_package(
            package["id"], edition["version"], TRAVEL,
        )
        validate_error(blocked, ApiErrorId.ERR_HOTEL_NIGHTS_EXHAUSTED.value)

        after = validate_success(api.get_travel_package(package["id"], TRAVEL))
        assert after["status"] == "SUBMITTED"
        assert after["hotel_nights_allocated"] == 0


class TestApprovalOcc:
    def test_occ_stale_travel_approve(self, api):
        """PRD §2.7: "Approving a travel package — `POST
        /festival/travel-packages/{id}/approve` — requires
        `expected_edition_version` carrying the edition's last observed
        `version`" and the endpoint "rejects the request with
        `ERR_STALE_VERSION` (HTTP 412) when the supplied value does not match
        the parent entity's current `version`."

        Design: Corner/cross_cutting_layers/occ_stale_travel_approve_expression
        """
        ctx = _package_ctx(api, films=[{"title": "OCC Travel"}])
        spec = ctx["films"][0]
        package = st_submit_package(
            ctx["packages"][0]["id"], spec["submitter"]["id"],
            {"delegate_count": 1, "origin_country_code": "US",
             "hotel_nights_requested": 2},
        )
        edition = validate_success(api.get_edition(ctx["edition"]["id"], TRAVEL))
        current = edition["version"]

        stale = api.approve_travel_package(package["id"], current - 1, TRAVEL)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)

        approved = validate_success(
            api.approve_travel_package(package["id"], current, TRAVEL)
        )
        assert approved["status"] == "APPROVED"
        assert approved["stipend_cents"] == 50000
        assert approved["hotel_nights_allocated"] == 2
