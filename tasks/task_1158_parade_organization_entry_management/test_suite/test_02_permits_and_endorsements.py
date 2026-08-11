"""Permit filing fees, endorsement workflow, uniqueness, and permit OCC."""
import test_helpers as th
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, assert_permit, assert_endorsement,
)


class TestPermitFeeVariants:
    """Difficulty: permit_fee_provisional_flat_vs_final_agency_table."""

    def _setup(self, api):
        return th.setup_permit_pending_parade(name="Fee Parade")

    def test_provisional_fee_flat_95000_at_creation(self, api):
        """PRD §3.2: "`provisional_fee_cents` is 75,000 cents plus 5,000 cents
        per required agency, and since `required_agency_count` is always four —
        the fixed agency set `POLICE`, `FIRE`, `TRANSIT`, and `SANITATION` —
        every new application estimates at exactly 95,000 cents."

        Design: Difficulty/dual_variant_calc/permit_fee_provisional_flat_vs_final_agency_table
        """
        ctx = self._setup(api)
        permit = validate_success(
            api.get_permit(ctx["permit"]["id"], th.TEST_USERS["committee_admin_headers"])
        )
        assert_permit(permit)
        assert permit["provisional_fee_cents"] == 95000, (
            f"flat estimate must be 75000 + 5000*4 = 95000, got {permit['provisional_fee_cents']}"
        )
        assert permit["required_agency_count"] == 4

    def test_final_fee_agency_table_90000_after_submit(self, api):
        """PRD §3.2: "A successful submission stamps `submitted_at` from the
        logical clock and settles the real filing cost into `final_fee_cents`:
        the per-agency table charges 30,000 cents for `POLICE`, 25,000 for
        `FIRE`, 20,000 for `TRANSIT`, and 15,000 for `SANITATION`, a base of
        90,000 cents, and when the submission instant falls later than the
        instant fourteen days before `parade_date`, an expedite surcharge of
        twenty percent of that base, rounded half-up to whole cents, is added —
        108,000 cents in the expedited case."

        Design: Difficulty/dual_variant_calc/permit_fee_provisional_flat_vs_final_agency_table
        """
        ctx = self._setup(api)
        committee = th.TEST_USERS["committee_admin_headers"]
        # Logical clock sits at the 2026-05-01 startup default; parade_date
        # 2026-07-04 is more than fourteen days out, so no expedite surcharge.
        permit = validate_success(api.submit_permit(ctx["permit"]["id"], committee))
        assert_permit(permit)
        assert permit["final_fee_cents"] == 90000, (
            f"per-agency table base must be 90000 without expedite, got {permit['final_fee_cents']}"
        )
        assert permit["final_fee_cents"] != permit["provisional_fee_cents"], (
            "the per-agency final variant and the flat provisional variant price "
            "the same filing differently"
        )
        assert permit["submitted_at"] is not None

    def test_final_fee_expedited_surcharge_108000(self, api):
        """PRD §3.2: "A successful submission stamps `submitted_at` from the
        logical clock and settles the real filing cost into `final_fee_cents`:
        the per-agency table charges 30,000 cents for `POLICE`, 25,000 for
        `FIRE`, 20,000 for `TRANSIT`, and 15,000 for `SANITATION`, a base of
        90,000 cents, and when the submission instant falls later than the
        instant fourteen days before `parade_date`, an expedite surcharge of
        twenty percent of that base, rounded half-up to whole cents, is added —
        108,000 cents in the expedited case."

        Design: Corner/calculations/permit_final_fee_expedited_surcharge_applied
        """
        ctx = th.setup_permit_pending_parade(name="Expedite Parade")
        committee = th.TEST_USERS["committee_admin_headers"]
        # 2026-06-25 is later than 2026-07-04 minus fourteen days (2026-06-20).
        th.set_clock("2026-06-25T00:00:00Z")
        permit = validate_success(api.submit_permit(ctx["permit"]["id"], committee))
        assert permit["final_fee_cents"] == 108000, (
            f"expedited filing must be 90000 + 20% = 108000, got {permit['final_fee_cents']}"
        )
        assert permit["provisional_fee_cents"] == 95000, (
            "the stale flat estimate is preserved, not overwritten by the final fee"
        )


class TestPermitAndPlanUniqueness:

    def test_second_permit_and_plan_creation_rejected(self, api):
        """PRD §3.2: "A parade files at most one permit application; a second
        attempt is rejected with `ERR_PERMIT_ALREADY_EXISTS`."
        PRD §3.2: "A parade carries at most one — a second creation is rejected
        with `ERR_PLAN_ALREADY_EXISTS` — drafted with a guaranteed
        `emergency_lane_width_m`, an ordered, non-empty-at-submit list of
        `dispersal_corridors`, and optional free-text `evacuation_notes`."

        Design: Corner/validations/second_permit_and_plan_creation_rejected
        """
        committee = th.TEST_USERS["committee_admin_headers"]
        parade = th.create_parade(name="Unique Parade")
        get_success_data(api.create_permit(parade["id"], committee))
        get_success_data(
            api.create_dispersal_plan(parade["id"], th.create_dispersal_plan_payload(), committee)
        )

        resp1 = api.create_permit(parade["id"], committee)
        validate_error(resp1, ApiErrorId.ERR_PERMIT_ALREADY_EXISTS)

        resp2 = api.create_dispersal_plan(
            parade["id"],
            th.create_dispersal_plan_payload(emergency_lane_width_m=4.0,
                                             dispersal_corridors=["Pine Ave"]),
            committee,
        )
        validate_error(resp2, ApiErrorId.ERR_PLAN_ALREADY_EXISTS)


class TestEndorsements:

    def test_duplicate_agency_endorsement_rejected(self, api):
        """PRD §3.2: "At most one endorsement in `PENDING` or `ENDORSED` status
        may exist per agency type on a permit; a duplicate request is rejected
        with `ERR_DUPLICATE_AGENCY_ENDORSEMENT`."

        Design: Corner/validations/duplicate_agency_endorsement_rejected
        """
        committee = th.TEST_USERS["committee_admin_headers"]
        parade = th.create_parade(name="Dup Parade")
        permit = th.create_permit(parade["id"])
        first = th.request_endorsement(permit["id"], "POLICE", permit["version"])

        resp = api.create_endorsement(
            permit["id"],
            th.create_endorsement_payload("POLICE", first["permit_version"]),
            committee,
        )
        # The OCC version carried is current, so the uniqueness constraint —
        # not staleness — is what fires.
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_AGENCY_ENDORSEMENT)

    def test_endorse_immediately_visible_in_permit_count(self, api):
        """PRD §2.5: "Derived counters and aggregates follow an
        immediate-consistency model: a change that affects a derived value
        recomputes that value as part of the same write, never asynchronously."
        PRD §3.2: "An `AgencyReviewer` then decides each request: endorsing
        moves it from `PENDING` to `ENDORSED`, rejecting moves it from
        `PENDING` to `REJECTED`, and either decision stamps `decided_at` from
        the logical clock and recomputes the permit's `endorsed_count`."

        Design: Corner/consistency_model/endorse_immediately_visible_in_permit_count
        """
        committee = th.TEST_USERS["committee_admin_headers"]
        parade = th.create_parade(name="Consistent Parade")
        permit = th.create_permit(parade["id"])
        endorsement = th.request_endorsement(permit["id"], "POLICE", permit["version"])

        decided = validate_success(
            api.endorse_endorsement(endorsement["id"], th.TEST_USERS["agency_reviewer_headers"])
        )
        assert_endorsement(decided)
        assert decided["status"] == "ENDORSED"

        permit_after = validate_success(api.get_permit(permit["id"], committee))
        assert permit_after["endorsed_count"] == 1, (
            f"the very next read must show endorsed_count 1, got {permit_after['endorsed_count']}"
        )

    def test_endorsement_create_with_stale_permit_version_returns_412(self, api):
        """PRD §2.9: "Each endorsement creation legitimately succeeds on its
        own and advances the permit's version, so a creation carrying an
        earlier observed version is stale: it is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/endorsement_create_with_stale_permit_version_returns_412
        """
        committee = th.TEST_USERS["committee_admin_headers"]
        parade = th.create_parade(name="OCC Permit Parade")
        permit = th.create_permit(parade["id"])
        first = th.request_endorsement(permit["id"], "POLICE", permit["version"])

        # The POLICE creation advanced the permit version; replay the version
        # observed before it (first.permit_version - 1).
        resp = api.create_endorsement(
            permit["id"],
            th.create_endorsement_payload("FIRE", first["permit_version"] - 1),
            committee,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        endorsements, meta = th.validate_paginated(
            api.list_endorsements(permit["id"], committee)
        )
        assert meta["total_count"] == 1, "no FIRE endorsement may be persisted"


class TestDispersalLaneGate:

    def test_dispersal_submit_narrow_lane_rejected(self, api):
        """PRD §3.2: "Submitting the plan moves it from `DRAFT` to `SUBMITTED`
        and enforces two gates: the guaranteed emergency lane width must be at
        least 3.0 meters, or the submission fails with
        `ERR_EMERGENCY_LANE_TOO_NARROW` (HTTP 422), and the corridor list must
        be non-empty, or it fails with `ERR_VALIDATION`."

        Design: Corner/validations/dispersal_submit_narrow_lane_rejected
        """
        committee = th.TEST_USERS["committee_admin_headers"]
        parade = th.create_parade(name="Narrow Parade")
        plan = get_success_data(
            api.create_dispersal_plan(
                parade["id"],
                th.create_dispersal_plan_payload(emergency_lane_width_m=2.5),
                committee,
            )
        )
        resp = api.submit_dispersal_plan(plan["id"], committee)
        validate_error(resp, ApiErrorId.ERR_EMERGENCY_LANE_TOO_NARROW)

        plan_after = validate_success(api.get_dispersal_plan(plan["id"], committee))
        assert plan_after["status"] == "DRAFT"
