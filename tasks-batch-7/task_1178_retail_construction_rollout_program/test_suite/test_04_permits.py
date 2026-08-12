"""Permit creation guards, fee schedule and rounding order, filing ledger,
refile cycle, expiry sweep, withdraw refund, and the mark-permitted gate."""
from test_helpers import (
    ApiErrorId,
    assert_permit,
    create_approved_drawing_set,
    create_issued_permit,
    create_permit,
    file_permit,
    issue_permit,
    read_permit,
    read_site,
    set_clock,
    setup_program_with_market,
    setup_site_in_permitting,
    start_permit_review,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPermitCreation:
    def test_permit_municipality_copied_from_site(self, api):
        """PRD §3.3: "The permit copies its `municipality_code` from the site
        at creation, starts at `round_number` 1 in `DRAFT`, and its
        `fee_cents` reads 0 until filing."

        Design: Corner/entities/c_permit_municipality_copied_from_site
        """
        ctx = setup_site_in_permitting()
        permit = create_permit(ctx["site"]["id"], ctx["ds"]["id"])
        assert_permit(permit)
        assert permit["municipality_code"] == "TX-DAL"
        assert permit["round_number"] == 1
        assert permit["status"] == "DRAFT"
        assert permit["fee_cents"] == 0

    def test_permit_create_without_municipality_profile_rejected(
            self, api, permit_coordinator_headers):
        """PRD §3.3: "Two creation-time guards apply: a municipality profile
        must exist for the site's `municipality_code`, failing with
        `ERR_MUNICIPALITY_PROFILE_MISSING` otherwise; and a site may hold only
        one non-terminal permit of each type, so an existing permit of the
        same type in `DRAFT`, `FILED`, `UNDER_REVIEW`, or `ISSUED` causes
        rejection with `ERR_DUPLICATE_PERMIT_TYPE`."

        Design: Corner/errors/c_permit_create_without_municipality_profile_rejected
        """
        ctx = setup_site_in_permitting(profile=False, municipality_code="TX-NONE")
        resp = api.create_permit(
            {"site_id": ctx["site"]["id"], "permit_type": "BUILDING",
             "drawing_set_id": ctx["ds"]["id"]},
            headers=permit_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_MUNICIPALITY_PROFILE_MISSING)

    def test_duplicate_permit_type_rejected(self, api, permit_coordinator_headers):
        """PRD §3.3: "a site may hold only one non-terminal permit of each
        type, so an existing permit of the same type in `DRAFT`, `FILED`,
        `UNDER_REVIEW`, or `ISSUED` causes rejection with
        `ERR_DUPLICATE_PERMIT_TYPE`."

        Design: Corner/validations/c_duplicate_permit_type_rejected
        """
        ctx = setup_site_in_permitting()
        create_issued_permit(ctx["site"]["id"], ctx["ds"]["id"])

        resp = api.create_permit(
            {"site_id": ctx["site"]["id"], "permit_type": "BUILDING",
             "drawing_set_id": ctx["ds"]["id"]},
            headers=permit_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PERMIT_TYPE)

    def test_permit_reverse_reachability_by_site(self, api,
                                                 permit_coordinator_headers):
        """PRD §3.3: "Permits list with filters on `site_id`,
        `drawing_set_id`, `status`, and `permit_type`; municipality profiles
        filter by `municipality_code`."

        Design: Corner/endpoints/c_permit_reverse_reachability_by_site
        """
        ctx = setup_site_in_permitting()
        permit = create_permit(ctx["site"]["id"], ctx["ds"]["id"])

        resp = api.list_permits(headers=permit_coordinator_headers,
                                params={"site_id": ctx["site"]["id"]})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == permit["id"]


class TestPermitFeesAndLedger:
    def test_permit_fee_per_permit_rounding_order(self, api):
        """PRD §3.3: "Filing computes the current-round fee as the profile's
        flat base fee plus the site's `square_footage` multiplied by
        `fee_per_sqft_cents` and divided by 100, that product rounded half up
        to whole cents before being added to the base."
        PRD §2.6: "Permit fees are rounded half up to whole cents per permit
        before any summation; summing unrounded per-permit amounts and
        rounding once at the end is forbidden."

        Design: Difficulty/combinatorial_formula/permit_fee_per_permit_rounding_order
        """
        # 50000 + round_half_up(4050 * 125 / 100) = 50000 + 5063 = 55063 per
        # permit; the two-permit ledger sums rounded fees to 110126 (the
        # forbidden sum-then-round order would yield 110125).
        ctx = setup_site_in_permitting(
            municipality_code="TX-FTW",
            profile_overrides={"fee_base_cents": 50_000, "fee_per_sqft_cents": 125},
            square_footage=4050)
        perm1 = create_permit(ctx["site"]["id"], ctx["ds"]["id"], permit_type="BUILDING")
        perm2 = create_permit(ctx["site"]["id"], ctx["ds"]["id"], permit_type="SIGNAGE")

        perm1 = file_permit(perm1["id"])
        perm2 = file_permit(perm2["id"])
        assert perm1["fee_cents"] == 55_063
        assert perm2["fee_cents"] == 55_063
        assert read_site(ctx["site"]["id"])["permit_fees_paid_cents"] == 110_126

    def test_permit_withdraw_refunds_exact_rounded_fee(self, api,
                                                       permit_coordinator_headers):
        """PRD §3.3: "Withdrawing — allowed from `FILED` or `UNDER_REVIEW` —
        moves the permit to `WITHDRAWN` and credits the full current-round fee
        back out of `permit_fees_paid_cents`."
        PRD §2.6: "Permit fees are rounded half up to whole cents per permit
        before any summation; summing unrounded per-permit amounts and
        rounding once at the end is forbidden."

        Design: Difficulty/combinatorial_formula/permit_fee_per_permit_rounding_order
        """
        ctx = setup_site_in_permitting(
            municipality_code="TX-FTW",
            profile_overrides={"fee_base_cents": 50_000, "fee_per_sqft_cents": 125},
            square_footage=4050)
        perm1 = create_permit(ctx["site"]["id"], ctx["ds"]["id"], permit_type="BUILDING")
        perm2 = create_permit(ctx["site"]["id"], ctx["ds"]["id"], permit_type="SIGNAGE")
        file_permit(perm1["id"])
        file_permit(perm2["id"])

        resp = api.withdraw_permit(perm2["id"], headers=permit_coordinator_headers)
        assert validate_success(resp)["status"] == "WITHDRAWN"
        # The ledger is debited/credited with the per-permit rounded fee.
        assert read_site(ctx["site"]["id"])["permit_fees_paid_cents"] == 55_063

    def test_permit_withdraw_refunds_current_round_fee(self, api,
                                                       permit_coordinator_headers):
        """PRD §3.3: "Withdrawing — allowed from `FILED` or `UNDER_REVIEW` —
        moves the permit to `WITHDRAWN` and credits the full current-round fee
        back out of `permit_fees_paid_cents`."

        Design: Corner/state_machines/c_permit_withdraw_refunds_current_round_fee
        """
        ctx = setup_site_in_permitting()
        permit = create_permit(ctx["site"]["id"], ctx["ds"]["id"])
        # base fee: 50000 + round_half_up(4000 * 250 / 100) = 60000
        permit = file_permit(permit["id"])
        assert permit["fee_cents"] == 60_000
        assert read_site(ctx["site"]["id"])["permit_fees_paid_cents"] == 60_000

        resp = api.withdraw_permit(permit["id"], headers=permit_coordinator_headers)
        assert validate_success(resp)["status"] == "WITHDRAWN"
        assert read_site(ctx["site"]["id"])["permit_fees_paid_cents"] == 0


class TestPermitRefileCycle:
    def test_permit_rejection_resubmission_cycle(self, api,
                                                 permit_coordinator_headers):
        """PRD §3.3: "Refiling is the cyclic resubmission loop: a `REJECTED`
        permit returns to `FILED` against the request's `drawing_set_id`,
        which must again identify the latest `APPROVED` revision for the
        site's program and municipality, failing with `ERR_DRAWING_SUPERSEDED`
        otherwise. Refiling increments `round_number`, re-pins the drawing to
        the supplied set, charges half of the base fee formula rounded half up
        to whole cents, debits the ledger a second time, and restamps
        `filed_at` and `review_due_on`."

        Design: Difficulty/non_linear_state_machine/permit_rejection_resubmission_cycle
        """
        ctx = setup_site_in_permitting()
        permit = create_permit(ctx["site"]["id"], ctx["ds"]["id"])
        permit = file_permit(permit["id"])
        permit = start_permit_review(permit["id"])
        resp = api.reject_permit(permit["id"], {"rejection_reason": "missing egress detail"},
                                 headers=permit_coordinator_headers)
        assert validate_success(resp)["status"] == "REJECTED"

        resp = api.refile_permit(permit["id"], {"drawing_set_id": ctx["ds"]["id"]},
                                 headers=permit_coordinator_headers)
        permit = validate_success(resp)
        assert permit["round_number"] == 2
        assert permit["fee_cents"] == 30_000, "refile charges half the 60000 base fee"
        assert permit["status"] == "FILED"

        permit = start_permit_review(permit["id"])
        permit = issue_permit(permit["id"])
        assert permit["status"] == "ISSUED"
        # Ledger: 60000 debited at round 1, 30000 at round 2.
        assert read_site(ctx["site"]["id"])["permit_fees_paid_cents"] == 90_000

    def test_permit_second_refile_charges_half_base_fee_again(
            self, api, permit_coordinator_headers):
        """PRD §3.3: "Refiling increments `round_number`, re-pins the drawing
        to the supplied set, charges half of the base fee formula rounded half
        up to whole cents, debits the ledger a second time, and restamps
        `filed_at` and `review_due_on`."

        Design: Difficulty/non_linear_state_machine/permit_rejection_resubmission_cycle
        """
        ctx = setup_site_in_permitting()
        permit = create_permit(ctx["site"]["id"], ctx["ds"]["id"])
        permit = file_permit(permit["id"])
        permit = start_permit_review(permit["id"])
        api.reject_permit(permit["id"], {"rejection_reason": "round 1 rejection"},
                          headers=permit_coordinator_headers)
        api.refile_permit(permit["id"], {"drawing_set_id": ctx["ds"]["id"]},
                          headers=permit_coordinator_headers)
        start_permit_review(permit["id"])
        resp = api.reject_permit(permit["id"], {"rejection_reason": "round 2 rejection"},
                                 headers=permit_coordinator_headers)
        assert validate_success(resp)["status"] == "REJECTED"

        resp = api.refile_permit(permit["id"], {"drawing_set_id": ctx["ds"]["id"]},
                                 headers=permit_coordinator_headers)
        permit = validate_success(resp)
        assert permit["round_number"] == 3
        assert permit["fee_cents"] == 30_000, (
            "every refile charges half the base fee, not a compounding fraction")
        assert permit["status"] == "FILED"
        # Ledger: 60000 (round 1) + 30000 (round 2) + 30000 (round 3).
        assert read_site(ctx["site"]["id"])["permit_fees_paid_cents"] == 120_000

    def test_refile_with_superseded_drawing_rejected(self, api,
                                                     permit_coordinator_headers,
                                                     design_manager_headers):
        """PRD §3.3: "Refiling is the cyclic resubmission loop: a `REJECTED`
        permit returns to `FILED` against the request's `drawing_set_id`,
        which must again identify the latest `APPROVED` revision for the
        site's program and municipality, failing with `ERR_DRAWING_SUPERSEDED`
        otherwise."

        Design: Corner/errors/c_refile_with_superseded_drawing_rejected
        """
        ctx = setup_site_in_permitting()
        ds1 = ctx["ds"]
        permit = create_permit(ctx["site"]["id"], ds1["id"])
        permit = file_permit(permit["id"])
        permit = start_permit_review(permit["id"])
        api.reject_permit(permit["id"], {"rejection_reason": "egress detail"},
                          headers=permit_coordinator_headers)

        # A second revision for the same jurisdiction supersedes the first.
        ds2 = create_approved_drawing_set(ctx["program"]["id"],
                                          jurisdiction_code="TX-DAL")

        resp = api.refile_permit(permit["id"], {"drawing_set_id": ds1["id"]},
                                 headers=permit_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_DRAWING_SUPERSEDED)

        resp = api.refile_permit(permit["id"], {"drawing_set_id": ds2["id"]},
                                 headers=permit_coordinator_headers)
        permit = validate_success(resp)
        assert permit["status"] == "FILED"
        assert permit["round_number"] == 2
        assert permit["drawing_set_id"] == ds2["id"]
        assert permit["fee_cents"] == 30_000


class TestPermitExpiryAndMarkPermitted:
    def test_permit_expiry_via_time_sweep(self, api, permit_coordinator_headers,
                                          program_director_headers):
        """PRD §3.3: "issuing performs the second, stamping `issued_at` from
        the clock and setting `expires_on` to the issue date plus
        `permit_validity_days`."
        PRD §2.5: "every `ISSUED` permit whose `expires_on` is on or before
        the current date moves to `EXPIRED`"
        PRD §3.3: "If that permit is `EXPIRED`, or is `ISSUED` but its
        `expires_on` is on or before the current date, the transition is
        rejected with `ERR_PERMIT_EXPIRED`."

        Design: Corner/state_machines/c_permit_expiry_via_time_sweep
        """
        ctx = setup_site_in_permitting(
            profile_overrides={"permit_validity_days": 30})
        permit = create_issued_permit(ctx["site"]["id"], ctx["ds"]["id"])
        assert permit["expires_on"] == "2026-05-31"

        set_clock("2026-06-01T00:00:00Z")
        resp = api.run_time_sweep(headers=program_director_headers)
        sweep = validate_success(resp)
        assert permit["id"] in sweep["expired_permit_ids"]
        assert read_permit(permit["id"])["status"] == "EXPIRED"

        resp = api.mark_site_permitted(ctx["site"]["id"],
                                       headers=permit_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_PERMIT_EXPIRED)

    def test_mark_permitted_requires_issued_building_permit(
            self, api, permit_coordinator_headers):
        """PRD §3.3: "Otherwise that latest `BUILDING` permit must exist and
        be `ISSUED`; when there is none, or the latest sits in any other
        status, the rejection is `ERR_PERMIT_NOT_ISSUED`."

        Design: Difficulty/cross_entity_state_dependency/site_mark_permitted_requires_issued_building_permit
        """
        ctx = setup_site_in_permitting()
        permit = create_permit(ctx["site"]["id"], ctx["ds"]["id"])
        permit = file_permit(permit["id"])
        permit = start_permit_review(permit["id"])

        # BUILDING permit UNDER_REVIEW: gate rejects the transition.
        resp = api.mark_site_permitted(ctx["site"]["id"],
                                       headers=permit_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ISSUED)
        assert read_site(ctx["site"]["id"])["status"] == "PERMITTING"

        # After issuance the same transition succeeds.
        issue_permit(permit["id"])
        resp = api.mark_site_permitted(ctx["site"]["id"],
                                       headers=permit_coordinator_headers)
        assert validate_success(resp)["status"] == "MOBILIZED"

    def test_mark_permitted_ignores_issued_non_building_permit(
            self, api, permit_coordinator_headers):
        """PRD §3.3: "Marking a site permitted moves it from `PERMITTING` to
        `MOBILIZED` and inspects the site's `BUILDING` permit with the latest
        `created_at`, whatever its status."
        PRD §3.3: "Otherwise that latest `BUILDING` permit must exist and be
        `ISSUED`; when there is none, or the latest sits in any other status,
        the rejection is `ERR_PERMIT_NOT_ISSUED`."

        Design: Difficulty/cross_entity_state_dependency/site_mark_permitted_requires_issued_building_permit
        """
        ctx = setup_site_in_permitting()
        # Only a SIGNAGE permit exists and is fully ISSUED; no BUILDING permit.
        create_issued_permit(ctx["site"]["id"], ctx["ds"]["id"],
                             permit_type="SIGNAGE")

        resp = api.mark_site_permitted(ctx["site"]["id"],
                                       headers=permit_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ISSUED)
        assert read_site(ctx["site"]["id"])["status"] == "PERMITTING"
