"""Registration, submission intake, eligibility-at-create, and listings
(PRD §2.3, §2.6, §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID,
    create_category_config_payload, create_edition_payload,
    create_programmer_payload, create_submission_payload,
    create_submitter_payload,
    make_filmmaker_headers,
    st_advance, st_edition, st_film, st_rule, st_submitter,
    validate_error, validate_paginated, validate_success,
)


class TestRegistration:
    def test_submitter_duplicate_email_rejected(self, api, public_headers):
        """PRD §3.1: "An `email` already registered is rejected with
        `ERR_DUPLICATE_EMAIL`."

        Design: Corner/entities/submitter_duplicate_email_rejected
        """
        first = st_submitter({"email": "ivy@example.com"})
        assert first["id"]

        dup = api.create_submitter(
            create_submitter_payload(
                legal_name="Ivy Clone", email="ivy@example.com",
                country_of_residence="CA",
            ),
            public_headers,
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_EMAIL.value)

        other = validate_success(api.create_submitter(
            create_submitter_payload(
                legal_name="Other", email="other@example.com",
                country_of_residence="CA",
            ),
            public_headers,
        ), 201)
        assert other["id"] != first["id"]

    def test_programmer_create_defaults_applied(self, api, admin_headers):
        """PRD §3.1: a programmer profile records "`coi_production_companies`,
        the production companies the programmer is conflicted with, defaulting
        to empty; `max_active_assignments`, the cap on assignments the
        programmer may hold open at once, defaulting to 12; and `active`,
        defaulting to true" plus an `active_assignment_count` of zero.

        Design: Corner/entities/programmer_create_defaults_applied
        """
        data = validate_success(api.create_programmer(
            create_programmer_payload(
                display_name="Default Dan", email="dan@example.com",
                seniority="STAFF", categories_covered=["SHORT_FILM"],
            ),
            admin_headers,
        ), 201)
        assert data["active"] is True
        assert data["max_active_assignments"] == 12
        assert data["coi_production_companies"] == []
        assert data["active_assignment_count"] == 0


class TestSubmissionCreate:
    def _open_edition(self):
        ctx = st_edition()
        st_advance(ctx, "INTAKE_OPEN")
        return ctx

    def test_submitter_id_stamped_from_header(self, api, public_headers):
        """PRD §3.2: "The server stamps `submitter_id` from the caller's
        `X-User-ID`, and the film is born in `DRAFT` with `payment_status`
        `UNPAID`, `needs_info_resolved` false, and an empty `award_names`
        list."

        Design: Corner/entities/submission_create_submitter_id_input_ignored
        """
        ctx = self._open_edition()
        submitter = st_submitter({"email": "ivy@example.com"})
        payload = create_submission_payload(
            ctx["edition"]["id"], title="Ignored Field",
            premiere_status="NONE", production_company="Sol Films",
        )
        payload["submitter_id"] = NON_EXISTENT_UUID  # server must ignore this
        data = validate_success(
            api.create_submission(payload, make_filmmaker_headers(submitter["id"])),
            201,
        )
        assert data["submitter_id"] == submitter["id"]
        assert data["submitter_id"] != NON_EXISTENT_UUID
        assert data["status"] == "DRAFT"
        assert data["payment_status"] == "UNPAID"
        assert data["needs_info_resolved"] is False
        assert data["award_names"] == []

    def test_submission_create_missing_required_title(self, api):
        """PRD §2.9: "First, the request shape is checked — required fields
        present, enum values valid, integer ranges sane — and any failure
        yields `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/submission_create_missing_required_title
        """
        ctx = self._open_edition()
        submitter = st_submitter()
        payload = create_submission_payload(ctx["edition"]["id"])
        del payload["title"]
        resp = api.create_submission(
            payload, make_filmmaker_headers(submitter["id"])
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_submission_duplicate_title_rules(self, api):
        """PRD §3.2: "a `title` the same submitter has already used for a
        submission in this edition is rejected with
        `ERR_DUPLICATE_SUBMISSION`."

        Design: Corner/entities/submission_duplicate_title_rules
        """
        ctx = self._open_edition()
        s1 = st_submitter({"email": "one@example.com"})
        s2 = st_submitter({"email": "two@example.com"})
        first = st_film(ctx, s1, {"title": "Dawn"}, pay=False)
        assert first["status"] == "DRAFT"

        dup = api.create_submission(
            create_submission_payload(ctx["edition"]["id"], title="Dawn"),
            make_filmmaker_headers(s1["id"]),
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_SUBMISSION.value)

        other = validate_success(api.create_submission(
            create_submission_payload(ctx["edition"]["id"], title="Dawn"),
            make_filmmaker_headers(s2["id"]),
        ), 201)
        assert other["title"] == "Dawn"

    def test_submission_body_fk_referential(self, api):
        """PRD §3.2: "a body reference that resolves to nothing yields
        `ERR_REFERENTIAL_INTEGRITY` (HTTP 422)."

        Design: Corner/entities/submission_body_fk_referential
        """
        submitter = st_submitter()
        resp = api.create_submission(
            create_submission_payload(NON_EXISTENT_UUID, title="Ghost"),
            make_filmmaker_headers(submitter["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY.value)

    def test_intake_not_yet_open_temporal(self, api):
        """PRD §3.2: "the logical clock must read at or after the edition's
        `intake_open_at`, or the create fails with
        `ERR_INTAKE_NOT_YET_OPEN`."

        Design: Corner/validations/intake_not_yet_open_temporal
        """
        ctx = st_edition(edition_over={
            "intake_open_at": "2026-09-01T00:00:00Z",
            "early_deadline_at": "2026-09-15T00:00:00Z",
            "regular_deadline_at": "2026-10-01T00:00:00Z",
            "late_deadline_at": "2026-10-15T00:00:00Z",
        })
        st_advance(ctx, "INTAKE_OPEN")  # posture open; clock still 2026-08-01
        submitter = st_submitter()
        resp = api.create_submission(
            create_submission_payload(ctx["edition"]["id"], title="Early Bird"),
            make_filmmaker_headers(submitter["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INTAKE_NOT_YET_OPEN.value)


class TestEligibilityAtCreate:
    def test_eligibility_field_boundaries(self, api):
        """PRD §3.2: "a `runtime_minutes` outside the category's inclusive
        minimum-to-maximum window is rejected with `ERR_INELIGIBLE_RUNTIME`, a
        `completion_date` earlier than the category's `completion_cutoff` is
        rejected with `ERR_INELIGIBLE_COMPLETION_DATE`."

        Design: Corner/validations/eligibility_field_boundaries
        """
        ctx = st_edition()
        st_advance(ctx, "INTAKE_OPEN")
        submitter = st_submitter()
        headers = make_filmmaker_headers(submitter["id"])
        edition_id = ctx["edition"]["id"]

        ok = validate_success(api.create_submission(
            create_submission_payload(
                edition_id, title="Max OK", runtime_minutes=40,
                completion_date="2025-01-01", premiere_status="NONE",
            ),
            headers,
        ), 201)
        assert ok["runtime_minutes"] == 40

        over = api.create_submission(
            create_submission_payload(
                edition_id, title="Over Max", runtime_minutes=41,
                premiere_status="NONE",
            ),
            headers,
        )
        validate_error(over, ApiErrorId.ERR_INELIGIBLE_RUNTIME.value)

        old = api.create_submission(
            create_submission_payload(
                edition_id, title="Too Old", runtime_minutes=20,
                completion_date="2024-12-31", premiere_status="NONE",
            ),
            headers,
        )
        validate_error(old, ApiErrorId.ERR_INELIGIBLE_COMPLETION_DATE.value)


class TestCategoryConfig:
    def test_category_config_duplicate_rejected(self, api, admin_headers):
        """PRD §3.1: "a second configuration for the same edition and category
        is rejected with `ERR_DUPLICATE_CATEGORY_CONFIG`."

        Design: Corner/entities/category_config_duplicate_rejected
        """
        ctx = st_edition(with_config=False)
        ctx2 = st_edition(with_config=False, edition_over={"year": 2028})
        edition_id = ctx["edition"]["id"]

        first = validate_success(api.create_category_config(
            create_category_config_payload(edition_id), admin_headers,
        ), 201)
        assert first["category"] == "SHORT_FILM"

        dup = api.create_category_config(
            create_category_config_payload(edition_id), admin_headers,
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_CATEGORY_CONFIG.value)

        other = validate_success(api.create_category_config(
            create_category_config_payload(ctx2["edition"]["id"]), admin_headers,
        ), 201)
        assert other["edition_id"] == ctx2["edition"]["id"]


class TestSubmissionListing:
    def test_submission_list_pagination_envelope(self, api, admin_headers):
        """PRD §2.3: "The `meta` object of every list response carries
        `limit`, `offset`, `total_count`, and `has_more`" and "The `offset`
        parameter sets the number of items skipped and defaults to 0."

        Design: Corner/entities/submission_list_pagination_envelope
        """
        ctx = st_edition()
        st_advance(ctx, "INTAKE_OPEN")
        submitter = st_submitter()
        for title in ("P1", "P2", "P3"):
            st_film(ctx, submitter, {"title": title}, pay=False)

        page1, meta1 = validate_paginated(api.list_submissions(
            admin_headers,
            params={"edition_id": ctx["edition"]["id"], "limit": 2, "offset": 0},
        ))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_submissions(
            admin_headers,
            params={"edition_id": ctx["edition"]["id"], "limit": 2, "offset": 2},
        ))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestImmediateConsistency:
    def test_immediate_read_after_write(self, api):
        """PRD §2.6: "The `version` field is an integer that starts at its
        initial value on creation and increments on every mutation of the
        resource" and §3.2: a filmmaker may amend a DRAFT submission and "the
        amendment ... increments the submission's `version`".

        Design: Corner/consistency_model/immediate_read_after_write
        """
        ctx = st_edition()
        st_advance(ctx, "INTAKE_OPEN")
        submitter = st_submitter()
        headers = make_filmmaker_headers(submitter["id"])
        film = st_film(ctx, submitter, {"title": "Before"}, pay=False)

        patched = validate_success(
            api.update_submission(film["id"], {"title": "After"}, headers)
        )
        assert patched["title"] == "After"

        reread = validate_success(api.get_submission(film["id"], headers))
        assert reread["title"] == "After"
        assert reread["version"] == film["version"] + 1, (
            f"version must increment by exactly 1: {film['version']} -> "
            f"{reread['version']}"
        )


class TestEligibilityRuling:
    def test_premiere_requirement_enforced_at_ruling(self, api, admin_headers):
        """PRD §3.3: "A ruling of `ELIGIBLE` certifies that the film's
        `premiere_status` satisfies the category's `premiere_requirement`,
        and a film that does not satisfy it is rejected with
        `ERR_INELIGIBLE_PREMIERE`. Satisfaction follows the premiere
        hierarchy: ... `US_REQUIRED` accepts `WORLD`, `INTERNATIONAL`,
        `NORTH_AMERICA`, or `US`."

        Design: Corner/validations/premiere_requirement_enforced_at_ruling
        """
        ctx = st_edition(
            category="NARRATIVE_FEATURE",
            config_over={
                "min_runtime_minutes": 70, "max_runtime_minutes": 120,
                "premiere_requirement": "US_REQUIRED",
                "early_fee_cents": 9000, "regular_fee_cents": 12000,
                "late_fee_cents": 15000, "screener_count_required": 3,
            },
        )
        st_advance(ctx, "INTAKE_OPEN")
        submitter = st_submitter()
        film_r = st_film(ctx, submitter, {
            "title": "Regional Film", "category": "NARRATIVE_FEATURE",
            "runtime_minutes": 90, "premiere_status": "REGIONAL",
        })
        film_u = st_film(ctx, submitter, {
            "title": "US Film", "category": "NARRATIVE_FEATURE",
            "runtime_minutes": 90, "premiere_status": "US",
        })

        blocked = api.decide_eligibility(film_r["id"], "ELIGIBLE", admin_headers)
        validate_error(blocked, ApiErrorId.ERR_INELIGIBLE_PREMIERE.value)
        stays = validate_success(api.get_submission(film_r["id"], admin_headers))
        assert stays["status"] == "SUBMITTED"

        accepted = validate_success(
            api.decide_eligibility(film_u["id"], "ELIGIBLE", admin_headers)
        )
        assert accepted["status"] == "ELIGIBLE"


class TestTerminalLockdown:
    def test_terminal_lockdown_ineligible_submission(self, api, admin_headers):
        """PRD §3.3: "A ruling of `INELIGIBLE` is terminal for the film";
        §3.2: withdrawal is "available from every non-terminal program status
        — `DRAFT`, `SUBMITTED`, `NEEDS_INFO`, `ELIGIBLE`, `IN_SCREENING`,
        `ADVANCED`, `INVITED`, `WAITLISTED`, `CONFIRMED`, or `PROGRAMMED`";
        §2.9: "invalid-from states and terminal lockdowns yield
        `ERR_INVALID_STATE` (HTTP 409)"; and checkout "creates a fee payment
        for a `DRAFT` submission".

        Design: Corner/state_machines/terminal_lockdown_ineligible_submission
        """
        ctx = st_edition()
        st_advance(ctx, "INTAKE_OPEN")
        submitter = st_submitter()
        film = st_film(ctx, submitter, {"title": "Terminal"})
        st_rule(ctx, film["id"], "INELIGIBLE", reason="prior release")
        headers = make_filmmaker_headers(submitter["id"])

        rerule = api.decide_eligibility(film["id"], "ELIGIBLE", admin_headers)
        validate_error(rerule, ApiErrorId.ERR_INVALID_STATE.value)

        withdraw = api.withdraw_submission(film["id"], headers)
        validate_error(withdraw, ApiErrorId.ERR_INVALID_STATE.value)

        checkout = api.checkout_submission(film["id"], headers)
        validate_error(checkout, ApiErrorId.ERR_INVALID_STATE.value)
