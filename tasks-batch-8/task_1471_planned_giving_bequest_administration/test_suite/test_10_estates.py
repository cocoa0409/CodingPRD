"""Estates and probate: lifecycle, distribution gates, waterfall, fund credit,
alternate valuation election, milestone clock sweep, and the contest cycle."""
from test_helpers import (
    DEFAULT_MIN_ENDOWMENT_CENTS,
    ApiErrorId,
    close_milestone,
    create_gift_asset_payload,
    make_active_rate_table,
    make_deceased_donor,
    make_donor,
    make_draft_agreement,
    make_estate,
    make_estate_manager_headers,
    make_fund,
    make_liquidated_cash_asset,
    make_milestone,
    make_probate_open_estate,
    make_verified_designation,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

EM2 = make_estate_manager_headers("em-2")


def _probate_open_estate():
    """Deceased donor + PROBATE_OPEN estate recorded by the default
    EstateManager (em-1)."""
    donor = make_deceased_donor(full_name="Estate Owner")
    return make_probate_open_estate(donor["id"])


class TestDonorVitalGateBothDirections:
    def test_donor_state_mismatch_both_directions(
        self, api, gift_officer_headers, estate_manager_headers
    ):
        """PRD §3.2: "A `GiftOfficer` models a prospective gift by creating an
        **illustration** for a living donor (a deceased donor is rejected with
        `ERR_DONOR_STATE_MISMATCH`, HTTP 409)."
        PRD §3.7: "manually when an `EstateManager` opens a file for a
        `DECEASED` donor — supplying `donor_id`, the `notified_on` date the
        office learned of the death, and optionally the related
        `gift_agreement_id` — with a `LIVING` donor rejected as
        `ERR_DONOR_STATE_MISMATCH`."

        Design: Corner/validations/donor_state_mismatch_both_directions
        """
        living = make_donor(full_name="Living")
        deceased = make_deceased_donor(full_name="Deceased", date_of_birth="1930-01-01T00:00:00Z")
        make_active_rate_table()

        resp = api.create_illustration(
            {
                "donor_id": deceased["id"],
                "vehicle_type": "CGA",
                "gift_amount_cents": 1000000,
                "payout_rate_bps": 600,
                "lives": 1,
                "annuitant_1_age": 90,
                "funding_month": "2026-08",
            },
            gift_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DONOR_STATE_MISMATCH)
        assert resp.status_code == 409

        resp = api.create_estate(
            {"donor_id": living["id"], "notified_on": "2026-08-05T00:00:00Z"},
            estate_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DONOR_STATE_MISMATCH)
        assert resp.status_code == 409


class TestMilestoneClockBoundary:
    def test_clock_default_milestone_boundary(self, api, estate_manager_headers):
        """PRD §2.4: "At server startup, before any client call, the logical
        clock reads exactly `2026-08-01T00:00:00Z`."
        PRD §2.4: "Second, every probate milestone in `PENDING` or `FILED`
        status whose `due_date` is strictly before the current clock time flips
        to `OVERDUE`."

        Design: Corner/cross_cutting_complexity_layers/clock_default_milestone_boundary
        """
        donor = make_deceased_donor(
            full_name="Clock Default",
            deceased_on="2026-07-15T00:00:00Z",
        )
        estate = make_estate(donor["id"], notified_on="2026-07-16T00:00:00Z")
        # Due exactly at the startup clock instant: strictly-before means NOT
        # overdue yet.
        milestone = make_milestone(estate["id"], due_date="2026-08-01T00:00:00Z")
        assert milestone["status"] == "PENDING"

        set_clock("2026-08-02T00:00:00Z")
        milestones, meta = validate_paginated(
            api.list_probate_milestones(
                estate_manager_headers, params={"estate_id": estate["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert milestones[0]["status"] == "OVERDUE"


class TestContestResolveCycle:
    def test_begin_distribution_rejected_while_contested(self, api, estate_manager_headers):
        """PRD §3.7: "contesting moves `PROBATE_OPEN` → `CONTESTED`, and
        resolving the contest returns the estate to `PROBATE_OPEN`."
        PRD §3.7: "Beginning distribution is the estate's fiscal climax,
        performed by an `EstateManager` on a `PROBATE_OPEN` estate".

        Design: Difficulty/non_linear_state_machine/estate_contest_resolve_cycle
        """
        estate = _probate_open_estate()
        contested = validate_success(
            api.transition_estate(estate["id"], {"action": "CONTEST"}, estate_manager_headers)
        )
        assert contested["status"] == "CONTESTED"

        resp = api.transition_estate(
            estate["id"],
            {
                "action": "BEGIN_DISTRIBUTION",
                "administration_costs_cents": 0,
                "specific_bequests_cents": 0,
            },
            EM2,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409

    def test_resolve_contest_reopens_distribution(self, api, estate_manager_headers):
        """PRD §3.7: "contesting moves `PROBATE_OPEN` → `CONTESTED`, and
        resolving the contest returns the estate to `PROBATE_OPEN`."
        PRD §3.7: "On success the estate stores both supplied cost figures,
        computes `residual_to_university_cents` as `gross_proceeds_cents` minus
        `administration_costs_cents` minus `specific_bequests_cents` — an exact
        subtraction with no rounding drift, conserving the gross exactly across
        the three buckets — and moves to `DISTRIBUTION_PENDING`."

        Design: Difficulty/non_linear_state_machine/estate_contest_resolve_cycle
        """
        estate = _probate_open_estate()
        validate_success(
            api.transition_estate(estate["id"], {"action": "CONTEST"}, estate_manager_headers)
        )
        resolved = validate_success(
            api.transition_estate(
                estate["id"], {"action": "RESOLVE_CONTEST"}, estate_manager_headers
            )
        )
        assert resolved["status"] == "PROBATE_OPEN"

        distributed = validate_success(
            api.transition_estate(
                estate["id"],
                {
                    "action": "BEGIN_DISTRIBUTION",
                    "administration_costs_cents": 0,
                    "specific_bequests_cents": 0,
                },
                EM2,
            )
        )
        assert distributed["status"] == "DISTRIBUTION_PENDING"
        assert distributed["residual_to_university_cents"] == 0


class TestDistributionGates:
    def test_estate_distribution_blocked_by_open_milestones(self, api, estate_manager_headers):
        """PRD §3.7: "Four gates apply, in the order of §2.10: the actor must
        differ from the estate's `recorded_by_user_id`
        (`ERR_SEGREGATION_OF_DUTIES`); every linked milestone must be `CLOSED`
        (`ERR_MILESTONES_OPEN`, HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/estate_distribution_blocked_by_open_milestones
        """
        estate = _probate_open_estate()
        milestone = make_milestone(estate["id"], due_date="2027-01-01T00:00:00Z")
        assert milestone["status"] == "PENDING"

        resp = api.transition_estate(
            estate["id"],
            {
                "action": "BEGIN_DISTRIBUTION",
                "administration_costs_cents": 0,
                "specific_bequests_cents": 0,
            },
            EM2,
        )
        validate_error(resp, ApiErrorId.ERR_MILESTONES_OPEN)
        assert resp.status_code == 409

    def test_closing_milestone_unblocks_distribution(self, api, estate_manager_headers):
        """PRD §3.7: "every linked milestone must be `CLOSED`
        (`ERR_MILESTONES_OPEN`, HTTP 409)".
        PRD §3.7: "A milestone begins `PENDING`; filing it (action `FILE`,
        stamping `filed_on` from the logical clock) moves it to `FILED`,
        including as a late cure from `OVERDUE`; closing moves `FILED` →
        `CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/estate_distribution_blocked_by_open_milestones
        """
        estate = _probate_open_estate()
        milestone = make_milestone(estate["id"], due_date="2027-01-01T00:00:00Z")
        resp = api.transition_estate(
            estate["id"],
            {
                "action": "BEGIN_DISTRIBUTION",
                "administration_costs_cents": 0,
                "specific_bequests_cents": 0,
            },
            EM2,
        )
        validate_error(resp, ApiErrorId.ERR_MILESTONES_OPEN)

        closed = close_milestone(milestone["id"])
        assert closed["status"] == "CLOSED"
        after = validate_success(
            api.transition_estate(
                estate["id"],
                {
                    "action": "BEGIN_DISTRIBUTION",
                    "administration_costs_cents": 0,
                    "specific_bequests_cents": 0,
                },
                EM2,
            )
        )
        assert after["status"] == "DISTRIBUTION_PENDING"

    def test_sod_beats_referential_on_begin_distribution(self, api, estate_manager_headers):
        """PRD §2.10: "Every request is validated against an ordered chain of
        checks, and the **first** failure wins — a request that would fail two
        checks receives the error of the earlier one." The global order lists
        "3. Segregation of duties on the three anchored operations —
        `ERR_SEGREGATION_OF_DUTIES`" ahead of "22. Estate milestone
        completeness — `ERR_MILESTONES_OPEN`."
        PRD §2.1: "Third, beginning distribution on an estate requires the
        acting `EstateManager` to differ from the estate's
        `recorded_by_user_id`."

        Design: Difficulty/priority_pair_validation_conflict/sod_beats_referential_on_begin_distribution
        """
        estate = _probate_open_estate()
        make_milestone(estate["id"], due_date="2027-01-01T00:00:00Z")

        # The recorder (em-1) calls BEGIN_DISTRIBUTION while a milestone is
        # still PENDING: SoD (earlier) masks the referential failure.
        resp = api.transition_estate(
            estate["id"],
            {
                "action": "BEGIN_DISTRIBUTION",
                "administration_costs_cents": 0,
                "specific_bequests_cents": 0,
            },
            estate_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert resp.status_code == 403

    def test_failed_sod_attempt_changes_nothing(self, api, estate_manager_headers):
        """PRD §2.1: "Third, beginning distribution on an estate requires the
        acting `EstateManager` to differ from the estate's
        `recorded_by_user_id`."
        PRD §2.10: "22. Estate milestone completeness — `ERR_MILESTONES_OPEN`."

        Design: Difficulty/priority_pair_validation_conflict/sod_beats_referential_on_begin_distribution
        """
        estate = _probate_open_estate()
        make_milestone(estate["id"], due_date="2027-01-01T00:00:00Z")

        resp = api.transition_estate(
            estate["id"],
            {
                "action": "BEGIN_DISTRIBUTION",
                "administration_costs_cents": 0,
                "specific_bequests_cents": 0,
            },
            estate_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = validate_success(api.get_estate(estate["id"], estate_manager_headers))
        assert after["status"] == "PROBATE_OPEN"

        # A non-recorder caller on the unchanged estate meets the referential
        # gate instead — proving the SoD rejection applied nothing.
        resp = api.transition_estate(
            estate["id"],
            {
                "action": "BEGIN_DISTRIBUTION",
                "administration_costs_cents": 0,
                "specific_bequests_cents": 0,
            },
            EM2,
        )
        validate_error(resp, ApiErrorId.ERR_MILESTONES_OPEN)

    def test_assets_not_liquidated_rejected(self, api, estate_manager_headers):
        """PRD §3.7: "every linked gift asset must be `LIQUIDATED`,
        `DISTRIBUTED`, or `RETURNED` (`ERR_ASSETS_NOT_LIQUIDATED`, HTTP 409)".

        Design: Corner/validations/assets_not_liquidated_rejected
        """
        estate = _probate_open_estate()
        asset = validate_success(
            api.create_gift_asset(
                create_gift_asset_payload(estate_id=estate["id"], pledged_value_cents=1000000),
                estate_manager_headers,
            ),
            201,
        )
        validate_success(
            api.transition_gift_asset(asset["id"], {"action": "RECEIVE"}, estate_manager_headers)
        )
        resp = api.transition_estate(
            estate["id"],
            {
                "action": "BEGIN_DISTRIBUTION",
                "administration_costs_cents": 0,
                "specific_bequests_cents": 0,
            },
            EM2,
        )
        validate_error(resp, ApiErrorId.ERR_ASSETS_NOT_LIQUIDATED)
        assert resp.status_code == 409
        after = validate_success(api.get_estate(estate["id"], estate_manager_headers))
        assert after["status"] == "PROBATE_OPEN"


class TestDistributionWaterfall:
    def test_estate_waterfall_overflow_then_conservation(self, api, estate_manager_headers):
        """PRD §3.7: "the waterfall must not overflow —
        `administration_costs_cents` plus `specific_bequests_cents` must not
        exceed `gross_proceeds_cents`, else `ERR_DISTRIBUTION_OVERFLOW`
        (HTTP 422)."
        PRD §3.7: "On success the estate stores both supplied cost figures,
        computes `residual_to_university_cents` as `gross_proceeds_cents` minus
        `administration_costs_cents` minus `specific_bequests_cents` — an exact
        subtraction with no rounding drift, conserving the gross exactly across
        the three buckets — and moves to `DISTRIBUTION_PENDING`."

        Design: Corner/calculations/estate_waterfall_overflow_then_conservation
        """
        estate = _probate_open_estate()
        make_liquidated_cash_asset(estate["id"], 1000000)

        resp = api.transition_estate(
            estate["id"],
            {
                "action": "BEGIN_DISTRIBUTION",
                "administration_costs_cents": 600000,
                "specific_bequests_cents": 500000,
            },
            EM2,
        )
        validate_error(resp, ApiErrorId.ERR_DISTRIBUTION_OVERFLOW)
        assert resp.status_code == 422
        mid = validate_success(api.get_estate(estate["id"], estate_manager_headers))
        assert mid["status"] == "PROBATE_OPEN"

        settled = validate_success(
            api.transition_estate(
                estate["id"],
                {
                    "action": "BEGIN_DISTRIBUTION",
                    "administration_costs_cents": 400000,
                    "specific_bequests_cents": 500000,
                },
                EM2,
            )
        )
        assert settled["status"] == "DISTRIBUTION_PENDING"
        assert settled["residual_to_university_cents"] == 100000
        # Conservation: costs + bequests + residual == gross, exactly.
        assert (
            settled["administration_costs_cents"]
            + settled["specific_bequests_cents"]
            + settled["residual_to_university_cents"]
            == settled["gross_proceeds_cents"]
            == 1000000
        )


class TestEstateFullLifecycle:
    def test_estate_full_happy_path_to_closed(self, api, estate_manager_headers):
        """PRD §3.7: "Marking the estate distributed (`MARK_DISTRIBUTED`)
        stamps `distributed_on` from the logical clock and moves
        `DISTRIBUTION_PENDING` → `DISTRIBUTED`; closing moves `DISTRIBUTED` →
        `CLOSED`, which is terminal."
        PRD §3.5: "Distribution moves a `LIQUIDATED` asset to `DISTRIBUTED`; an
        estate-linked asset may only be distributed while its estate is
        `DISTRIBUTION_PENDING` or `DISTRIBUTED`, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/estate_full_happy_path_to_closed
        """
        estate = _probate_open_estate()
        milestone = make_milestone(estate["id"], due_date="2027-01-01T00:00:00Z")
        close_milestone(milestone["id"])
        asset = make_liquidated_cash_asset(estate["id"], 1000000)

        pending = validate_success(
            api.transition_estate(
                estate["id"],
                {
                    "action": "BEGIN_DISTRIBUTION",
                    "administration_costs_cents": 100000,
                    "specific_bequests_cents": 200000,
                },
                EM2,
            )
        )
        assert pending["status"] == "DISTRIBUTION_PENDING"
        assert pending["residual_to_university_cents"] == 700000

        distributed_asset = validate_success(
            api.transition_gift_asset(asset["id"], {"action": "DISTRIBUTE"}, estate_manager_headers)
        )
        assert distributed_asset["status"] == "DISTRIBUTED"

        distributed = validate_success(
            api.transition_estate(
                estate["id"], {"action": "MARK_DISTRIBUTED"}, estate_manager_headers
            )
        )
        assert distributed["status"] == "DISTRIBUTED"

        closed = validate_success(
            api.transition_estate(estate["id"], {"action": "CLOSE"}, estate_manager_headers)
        )
        assert closed["status"] == "CLOSED"

        # CLOSED is terminal.
        resp = api.transition_estate(
            estate["id"], {"action": "OPEN_PROBATE"}, estate_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409


class TestFundEndowmentBoundary:
    def _setup_estate_with_exact_minimum_residual(self, api, gift_admin_headers):
        """Bequest (5M) EXECUTED with an attached PROPOSED fund at the default
        2500000 minimum; donor death matures it and auto-creates the estate;
        a 2500000 cash asset is received and liquidated; probate opened.
        Returns (estate_id, fund_id)."""
        donor = make_donor(full_name="Boundary Fund", date_of_birth="1935-01-01T00:00:00Z")
        make_active_rate_table()
        bequest = make_draft_agreement(
            donor["id"], vehicle_type="BEQUEST", gift_amount_cents=5000000
        )
        fund = make_fund(bequest["id"], name="Exact Minimum Fund")
        amended = validate_success(
            api.amend_gift_agreement(
                bequest["id"],
                {
                    "expected_gift_agreement_version": bequest["version"],
                    "fund_id": fund["id"],
                },
                gift_admin_headers,
            )
        )
        assert amended["fund_id"] == fund["id"]
        make_verified_designation(bequest["id"])
        validate_success(api.execute_gift_agreement(bequest["id"], gift_admin_headers))

        validate_success(
            api.record_death(
                donor["id"],
                {"deceased_on": "2026-09-01T00:00:00Z"},
                make_estate_manager_headers("em-1"),
            )
        )
        estates, meta = validate_paginated(
            api.list_estates(EM2, params={"gift_agreement_id": bequest["id"]})
        )
        assert meta["total_count"] == 1
        estate = estates[0]
        make_liquidated_cash_asset(estate["id"], 2500000)
        validate_success(
            api.transition_estate(
                estate["id"], {"action": "OPEN_PROBATE"}, make_estate_manager_headers("em-1")
            )
        )
        return estate["id"], fund["id"]

    def test_exact_minimum_residual_endows_fund(
        self, api, gift_admin_headers, finance_steward_headers
    ):
        """PRD §3.7: "The residual then cascades: if the estate's
        `gift_agreement_id` is set and that agreement names a `fund_id`, the
        fund's `balance_cents` grows by the residual, and if that credit lifts
        a `PROPOSED` fund to at least its `minimum_endowment_cents`, the fund
        auto-transitions to `ENDOWED` (inclusive boundary)".
        PRD §3.8: "an optional `minimum_endowment_cents` defaulting to 2500000
        cents (twenty-five thousand dollars)".

        Design: Difficulty/boundary_precision_check/fund_activation_exact_minimum_endows
        """
        estate_id, fund_id = self._setup_estate_with_exact_minimum_residual(
            api, gift_admin_headers
        )
        estate = validate_success(
            api.transition_estate(
                estate_id,
                {
                    "action": "BEGIN_DISTRIBUTION",
                    "administration_costs_cents": 0,
                    "specific_bequests_cents": 0,
                },
                EM2,
            )
        )
        assert estate["status"] == "DISTRIBUTION_PENDING"
        assert estate["residual_to_university_cents"] == DEFAULT_MIN_ENDOWMENT_CENTS

        fund = validate_success(api.get_fund(fund_id, finance_steward_headers))
        # Exactly the default minimum: the inclusive boundary endows.
        assert fund["balance_cents"] == DEFAULT_MIN_ENDOWMENT_CENTS
        assert fund["status"] == "ENDOWED"

    def test_endowed_fund_activates(
        self, api, gift_admin_headers, finance_steward_headers
    ):
        """PRD §3.8: "`ACTIVATE` moves a `PROPOSED` or `ENDOWED` fund to
        `ACTIVE` and requires the balance to meet the endowment minimum, else
        `ERR_FUND_MINIMUM_NOT_MET` (HTTP 409)".

        Design: Difficulty/boundary_precision_check/fund_activation_exact_minimum_endows
        """
        estate_id, fund_id = self._setup_estate_with_exact_minimum_residual(
            api, gift_admin_headers
        )
        validate_success(
            api.transition_estate(
                estate_id,
                {
                    "action": "BEGIN_DISTRIBUTION",
                    "administration_costs_cents": 0,
                    "specific_bequests_cents": 0,
                },
                EM2,
            )
        )
        fund = validate_success(api.get_fund(fund_id, finance_steward_headers))
        assert fund["status"] == "ENDOWED"

        activated = validate_success(
            api.transition_fund(fund_id, {"action": "ACTIVATE"}, finance_steward_headers)
        )
        assert activated["status"] == "ACTIVE"
