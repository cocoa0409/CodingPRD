"""Application drafting, submission windows, revision loop, and phase gates."""
from test_helpers import (
    STANDARD_SCORES,
    TEST_USERS,
    ApiErrorId,
    advance_phase,
    api_client,
    create_application,
    create_convention,
    get_application,
    make_exhibitor_headers,
    post_jury_score,
    register_exhibitor,
    request_revision,
    set_clock,
    setup_jury_review_application,
    setup_open_convention,
    setup_submitted_application,
    submit_application,
    validate_error,
    validate_success,
)
from test_helpers.assertions import assert_application


class TestApplicationCreationDefaults:
    def test_application_create_permit_default_both_convention_modes(self, api):
        """PRD §3.3: "New drafts hold status `DRAFT`, and their `permit_status`
        opens at `PENDING` when the convention requires permits and
        `NOT_REQUIRED` otherwise."

        Design: Corner/entities/application_create_permit_default_both_convention_modes
        """
        conv_required = create_convention(category_quotas=[], dock_doors=[])
        conv_free = create_convention(
            name="NoTax Expo",
            starts_at="2026-11-05T09:00:00Z",
            ends_at="2026-11-07T18:00:00Z",
            application_close_at="2026-09-25T00:00:00Z",
            tax_permit_required=False,
            sales_tax_rate_bp=0,
            category_quotas=[],
            dock_doors=[],
        )
        exhibitor = register_exhibitor(legal_name="Dealer One LLC", category="DEALER")

        app_required = create_application(conv_required["id"], exhibitor["id"])
        assert_application(app_required)
        assert app_required["status"] == "DRAFT"
        assert app_required["permit_status"] == "PENDING"

        app_free = create_application(conv_free["id"], exhibitor["id"])
        assert app_free["status"] == "DRAFT"
        assert app_free["permit_status"] == "NOT_REQUIRED"

    def test_application_missing_required_field_rejected(self, api):
        """PRD §2.8: "Independent of this ordering, a body that is malformed — a
        missing required field, a wrong-typed value, an unknown enum value, or an
        integer outside its declared range, such as a `requested_space_count` or
        `pallet_count` below one, or a jury criterion outside zero to one hundred
        — is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.3: "An exhibitor begins by drafting an Application with a
        `convention_id`, a `category`, a `channel`, the `requested_space_kinds`
        it will accept, a `requested_space_count`, its
        `estimated_daily_sales_cents`, and an optional
        `conflicted_juror_user_ids` list defaulting to empty."

        Design: Corner/entities/application_missing_required_field_rejected
        """
        exhibitor = register_exhibitor(legal_name="Dealer One LLC", category="DEALER")
        resp = api.create_application(
            {
                # convention_id omitted
                "category": "DEALER",
                "channel": "OPEN",
                "requested_space_kinds": ["BOOTH_10X10"],
                "requested_space_count": 1,
                "estimated_daily_sales_cents": 33333,
            },
            make_exhibitor_headers(exhibitor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_application_category_mismatch_rejected(self, api):
        """PRD §3.3: "The application's `category` must equal the exhibitor's
        registered category (`ERR_CATEGORY_MISMATCH`), the requested-kinds list
        must be non-empty, and the requested count must be at least one."

        Design: Corner/validations/application_category_mismatch_rejected
        """
        conv = create_convention(
            category_quotas=[
                {"category": "ARTIST_ALLEY", "max_accepted": 2, "max_waitlisted": 2}
            ],
            dock_doors=[],
        )
        exhibitor = register_exhibitor(legal_name="Dealer One LLC", category="DEALER")
        resp = api.create_application(
            {
                "convention_id": conv["id"],
                "category": "ARTIST_ALLEY",
                "channel": "OPEN",
                "requested_space_kinds": ["ARTIST_TABLE"],
                "requested_space_count": 1,
                "estimated_daily_sales_cents": 10000,
            },
            make_exhibitor_headers(exhibitor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CATEGORY_MISMATCH)


class TestSubmissionWindows:
    def test_submit_category_not_offered_rejected(self, api):
        """PRD §3.3: "Two further gates apply to every submission: a
        CategoryQuota row must exist for the convention and the requested
        category (`ERR_CATEGORY_NOT_OFFERED`), and the exhibitor must not
        already hold another application in the same convention in a live status
        — anything other than `WITHDRAWN`, `JURIED_REJECTED`, `DECLINED`, or
        `CANCELLED` (`ERR_DUPLICATE_APPLICATION`)."

        Design: Corner/validations/submit_category_not_offered_rejected
        """
        bundle = setup_submitted_application(
            category="STUDIO",
            kinds=("BOOTH_10X10",),
            estimated_daily_sales_cents=50000,
            category_quotas=[
                {"category": "ARTIST_ALLEY", "max_accepted": 2, "max_waitlisted": 2}
            ],
            dock_doors=[],
            space_specs=[
                {
                    "space_code": "T-01",
                    "block": "T",
                    "unit_number": 1,
                    "hall": "ARTIST_ALLEY_HALL",
                    "kind": "ARTIST_TABLE",
                    "base_price_cents": 30000,
                }
            ],
            submit=False,
        )
        resp = api.submit_application(
            bundle["application"]["id"],
            make_exhibitor_headers(bundle["exhibitor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CATEGORY_NOT_OFFERED)

    def test_renewal_channel_ineligible_exhibitor_rejected(self, api):
        """PRD §3.3: "A `RENEWAL` submission is accepted from `renewal_open_at`
        until strictly before `application_close_at`, and only from exhibitors
        with at least one completed prior year and `GOOD` standing
        (`ERR_RENEWAL_NOT_ELIGIBLE`); an `OPEN` submission is accepted from
        `application_open_at` until strictly before `application_close_at`."

        Design: Corner/validations/renewal_channel_ineligible_exhibitor_rejected
        """
        bundle = setup_open_convention(
            clock="2026-08-06T00:00:00Z",  # renewal window, before public open
            category_quotas=[
                {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 1}
            ],
            dock_doors=[],
        )
        exhibitor = register_exhibitor(
            legal_name="New Dealer LLC", category="DEALER"
        )  # prior_years_completed defaults to 0
        app = create_application(
            bundle["convention"]["id"],
            exhibitor["id"],
            category="DEALER",
            channel="RENEWAL",
        )
        resp = api.submit_application(
            app["id"], make_exhibitor_headers(exhibitor["id"])
        )
        validate_error(resp, ApiErrorId.ERR_RENEWAL_NOT_ELIGIBLE)

    def test_open_channel_before_public_open_rejected(self, api):
        """PRD §3.3: "an `OPEN` submission is accepted from `application_open_at`
        until strictly before `application_close_at`."
        PRD §3.3: "Submitting outside the applicable window — including at or
        after `application_close_at` — is rejected with
        `ERR_APPLICATION_WINDOW_CLOSED`."

        Design: Corner/validations/open_channel_before_public_open_rejected
        """
        bundle = setup_open_convention(
            clock="2026-08-06T00:00:00Z",  # before application_open_at 2026-08-12
            category_quotas=[
                {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 1}
            ],
            dock_doors=[],
        )
        exhibitor = register_exhibitor(
            legal_name="Returning Dealer LLC",
            category="DEALER",
            prior_years_completed=2,
        )
        app = create_application(
            bundle["convention"]["id"], exhibitor["id"], category="DEALER"
        )
        resp = api.submit_application(
            app["id"], make_exhibitor_headers(exhibitor["id"])
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_WINDOW_CLOSED)

    def test_duplicate_live_application_rejected(self, api):
        """PRD §3.3: "Two further gates apply to every submission: a
        CategoryQuota row must exist for the convention and the requested
        category (`ERR_CATEGORY_NOT_OFFERED`), and the exhibitor must not
        already hold another application in the same convention in a live status
        — anything other than `WITHDRAWN`, `JURIED_REJECTED`, `DECLINED`, or
        `CANCELLED` (`ERR_DUPLICATE_APPLICATION`)."

        Design: Corner/validations/duplicate_live_application_rejected
        """
        bundle = setup_submitted_application(
            category_quotas=[
                {"category": "DEALER", "max_accepted": 2, "max_waitlisted": 1}
            ],
            dock_doors=[],
        )
        ex_id = bundle["exhibitor"]["id"]
        second = create_application(
            bundle["convention"]["id"],
            ex_id,
            category="DEALER",
            estimated_daily_sales_cents=50000,
        )
        resp = api.submit_application(second["id"], make_exhibitor_headers(ex_id))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION)
        assert get_application(second["id"])["status"] == "DRAFT"


class TestSubmitAndWithdrawTransitions:
    def test_submit_from_submitted_rejected(self, api):
        """PRD §3.3: "Submitting moves `DRAFT` → `SUBMITTED` and is possible only
        while the convention is in `APPLICATIONS_OPEN` (`ERR_INVALID_TRANSITION`
        otherwise)."
        PRD §2.8: "5. State preconditions — the target resource must be in a
        from-state that permits the requested transition
        (`ERR_INVALID_TRANSITION`), and the OCC version fields must match the
        current versions (`ERR_STALE_APPLICATION_VERSION`,
        `ERR_STALE_CONVENTION_VERSION`)."

        Design: Corner/state_machines/submit_from_submitted_rejected
        """
        bundle = setup_submitted_application()
        app_id = bundle["application"]["id"]
        ex_id = bundle["exhibitor"]["id"]
        resp = api.submit_application(app_id, make_exhibitor_headers(ex_id))
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
        assert get_application(app_id)["status"] == "SUBMITTED"

    def test_withdraw_terminal_lockdown(self, api):
        """PRD §3.3: "Withdrawal is the exhibitor's exit from any pre-contract
        state: from `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_REVISION`, or
        `JURIED_WAITLISTED` the application moves to `WITHDRAWN`, and every
        `PENDING` neighbor request involving that exhibitor becomes `MOOT`.
        Withdrawing from `JURIED_WAITLISTED` additionally decrements the
        category quota's `waitlisted_count`. `WITHDRAWN` is terminal."

        Design: Corner/state_machines/withdraw_terminal_lockdown
        """
        bundle = setup_submitted_application()
        app_id = bundle["application"]["id"]
        ex_id = bundle["exhibitor"]["id"]
        withdrawn = validate_success(
            api.withdraw_application(app_id, make_exhibitor_headers(ex_id))
        )
        assert withdrawn["status"] == "WITHDRAWN"

        again = api.withdraw_application(app_id, make_exhibitor_headers(ex_id))
        validate_error(again, ApiErrorId.ERR_INVALID_TRANSITION)
        resubmit = api.submit_application(app_id, make_exhibitor_headers(ex_id))
        validate_error(resubmit, ApiErrorId.ERR_INVALID_TRANSITION)


class TestApplicationOcc:
    def test_occ_stale_application_version_rejected_and_increment_verified(self, api):
        """PRD §2.7: "Revising an application requires the request to carry
        `expected_application_version`, holding the application `version` the
        client last observed; if the application's current `version` has since
        advanced — because an earlier accepted write already bumped it — the
        revision is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412),
        since the client's edits were authored against a stale snapshot and the
        newer revision supersedes them."

        Design: Corner/cross_cutting_layers/occ_stale_application_version_rejected_and_increment_verified
        """
        bundle = setup_submitted_application(submit=False)  # DRAFT
        app = bundle["application"]
        ex_headers = make_exhibitor_headers(bundle["exhibitor"]["id"])
        observed_version = app["version"]

        first = api.patch_application(
            app["id"],
            {
                "expected_application_version": observed_version,
                "requested_space_count": 2,
            },
            ex_headers,
        )
        revised = validate_success(first)
        assert revised["version"] == observed_version + 1
        assert revised["requested_space_count"] == 2

        replay = api.patch_application(
            app["id"],
            {
                "expected_application_version": observed_version,
                "requested_space_count": 3,
            },
            ex_headers,
        )
        validate_error(replay, ApiErrorId.ERR_STALE_APPLICATION_VERSION)
        assert get_application(app["id"])["requested_space_count"] == 2


class TestEarlyBirdBoundary:
    def test_early_bird_deadline_boundary_inclusive(self, api):
        """PRD §3.3: "When the application's `submitted_at` falls on or before
        the convention's `early_bird_deadline`, a further ten percent early-bird
        deduction applies."
        PRD §3.3: "Fewer than twenty sold spaces keeps pricing in tier one,
        where each space prices at its `base_price_cents`; at least twenty but
        fewer than forty-five sold spaces moves pricing to tier two, multiplying
        each base price by 1.20; forty-five or more moves it to tier three,
        multiplying by 1.45."

        Design: Corner/calculations/early_bird_deadline_boundary_inclusive
        """
        bundle = setup_open_convention(
            clock=None,  # clock is set explicitly per submission below
            category_quotas=[
                {"category": "DEALER", "max_accepted": 2, "max_waitlisted": 1}
            ],
            dock_doors=[{"door_code": "D1"}],
        )
        conv_id = bundle["convention"]["id"]
        ex_a = register_exhibitor(legal_name="Dealer Early LLC", category="DEALER")
        ex_b = register_exhibitor(legal_name="Dealer Late LLC", category="DEALER")
        app_a = create_application(conv_id, ex_a["id"], category="DEALER")
        app_b = create_application(conv_id, ex_b["id"], category="DEALER")

        set_clock("2026-08-20T00:00:00Z")  # exactly the early-bird deadline
        sub_a = submit_application(app_a["id"], ex_a["id"])
        assert sub_a["provisional_quote_cents"] == 90000, (
            f"100000 less 10% early-bird, got {sub_a['provisional_quote_cents']}"
        )

        set_clock("2026-08-20T00:00:01Z")  # one second past the deadline
        sub_b = submit_application(app_b["id"], ex_b["id"])
        assert sub_b["provisional_quote_cents"] == 100000, (
            f"no early-bird after the deadline, got {sub_b['provisional_quote_cents']}"
        )
        assert sub_b["provisional_quote_cents"] - sub_a["provisional_quote_cents"] == 10000


class TestRevisionLoop:
    def test_revision_loop_request_revision_then_patch(self, api):
        """PRD §3.3: "The jury may send an application back for changes: a
        director's revision request moves `UNDER_REVIEW` → `NEEDS_REVISION`, and
        resubmission returns `NEEDS_REVISION` → `SUBMITTED`."
        PRD §3.3: "While an application is in `DRAFT` — or later in
        `NEEDS_REVISION` — the exhibitor may revise its `requested_space_kinds`,
        `requested_space_count`, `estimated_daily_sales_cents`,
        `conflicted_juror_user_ids`, and `channel`; revisions are OCC-guarded
        per §2.7, and a stale `expected_application_version` is rejected with
        `ERR_STALE_APPLICATION_VERSION`."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle_loop
        """
        bundle = setup_jury_review_application(scores=STANDARD_SCORES[:1])
        app_id = bundle["application"]["id"]
        assert bundle["application"]["status"] == "UNDER_REVIEW"

        sent_back = request_revision(app_id)
        assert sent_back["status"] == "NEEDS_REVISION"  # cycle leg 1

        patched = validate_success(
            api_client.patch_application(
                app_id,
                {
                    "expected_application_version": sent_back["version"],
                    "requested_space_count": 2,
                },
                make_exhibitor_headers(bundle["exhibitor"]["id"]),
            )
        )
        assert patched["version"] == sent_back["version"] + 1, (
            "OCC-guarded revision must increment the version by exactly one"
        )
        assert patched["requested_space_count"] == 2

    def test_revision_loop_resubmit_in_jury_review_closes_cycle(self, api):
        """PRD §3.3: "Resubmission is allowed in two phases — during
        `APPLICATIONS_OPEN` every draft-submission check applies, and
        `ERR_APPLICATION_WINDOW_CLOSED` can only surface in this phase; during
        `JURY_REVIEW` the window checks are waived while the quota and duplicate
        checks still apply."
        PRD §3.4: "The very first score posted for an application moves it
        automatically from `SUBMITTED` to `UNDER_REVIEW`."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle_loop
        """
        bundle = setup_jury_review_application(scores=STANDARD_SCORES[:1])
        app_id = bundle["application"]["id"]
        ex_headers = make_exhibitor_headers(bundle["exhibitor"]["id"])

        sent_back = request_revision(app_id)
        patched = validate_success(
            api_client.patch_application(
                app_id,
                {
                    "expected_application_version": sent_back["version"],
                    "requested_space_count": 2,
                },
                ex_headers,
            )
        )
        assert patched["status"] == "NEEDS_REVISION"

        # Window checks are waived in JURY_REVIEW: resubmission succeeds even
        # though the clock (2026-08-26) is past application_close_at.
        resubmitted = submit_application(app_id, bundle["exhibitor"]["id"])
        assert resubmitted["status"] == "SUBMITTED"  # cycle leg 2

        # The next score auto-moves the application back to UNDER_REVIEW,
        # closing UNDER_REVIEW -> NEEDS_REVISION -> SUBMITTED -> UNDER_REVIEW.
        post_jury_score(app_id, "juror-2", 90, 80, 80, 80)
        assert get_application(app_id)["status"] == "UNDER_REVIEW"


class TestPhaseGates:
    def test_advance_phase_blocked_by_pending_applications(self, api):
        """PRD §3.1: "`JURY_REVIEW` → `PLACEMENT` requires that no application
        of the convention remains in `SUBMITTED`, `UNDER_REVIEW`, or
        `NEEDS_REVISION`."
        PRD §3.1: "Each step has its own gate, and a failed gate is rejected
        with `ERR_PHASE_PRECONDITION`:"

        Design: Corner/state_machines/advance_phase_blocked_by_pending_applications
        """
        bundle = setup_submitted_application()  # one application left SUBMITTED
        conv_id = bundle["convention"]["id"]
        set_clock("2026-08-26T00:00:00Z")
        advance_phase(conv_id)  # APPLICATIONS_OPEN -> JURY_REVIEW
        resp = api.advance_phase(conv_id, TEST_USERS["director_headers"])
        validate_error(resp, ApiErrorId.ERR_PHASE_PRECONDITION)
        assert get_application(bundle["application"]["id"])["status"] == "SUBMITTED"
        current = validate_success(
            api.get_convention(conv_id, TEST_USERS["director_headers"])
        )
        assert current["phase"] == "JURY_REVIEW"

    def test_advance_phase_blocked_before_application_close(self, api):
        """PRD §3.1: "`APPLICATIONS_OPEN` → `JURY_REVIEW` requires the clock to
        be at or after `application_close_at`."
        PRD §3.1: "Each step has its own gate, and a failed gate is rejected
        with `ERR_PHASE_PRECONDITION`:"

        Design: Corner/state_machines/advance_phase_blocked_before_application_close
        """
        bundle = setup_open_convention()  # clock 2026-08-13, APPLICATIONS_OPEN
        conv_id = bundle["convention"]["id"]
        set_clock("2026-08-20T00:00:00Z")  # still before application_close_at
        resp = api.advance_phase(conv_id, TEST_USERS["director_headers"])
        validate_error(resp, ApiErrorId.ERR_PHASE_PRECONDITION)
        current = validate_success(
            api.get_convention(conv_id, TEST_USERS["director_headers"])
        )
        assert current["phase"] == "APPLICATIONS_OPEN"
