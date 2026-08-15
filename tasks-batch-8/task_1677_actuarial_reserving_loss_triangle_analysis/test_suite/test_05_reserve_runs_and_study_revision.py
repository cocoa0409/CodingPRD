"""Reserve-run creation guards (covering pattern, fresh triangle, uniqueness),
study-creation uniqueness, optimistic concurrency on study revision, and the
WITHDRAWN terminal lockdown (PRD §2.9, §3.5, §3.7).
"""
from test_helpers import (
    ApiErrorId,
    create_pattern,
    create_study,
    patch_study_payload,
    post_payment,
    setup_minimal_book,
    setup_minimal_book_with_pattern,
    setup_minimal_book_with_run,
    setup_minimal_book_with_triangle,
    validate_error,
    validate_success,
    withdraw_study_by,
)


class TestReserveRunCreationGuards:
    def test_run_creation_without_selected_pattern_rejected(
        self, api, actuarial_analyst_headers
    ):
        """PRD §3.5: "A `SELECTED` pattern of the same segment and basis whose
        window covers the valuation quarter must exist — without one the
        request fails with `ERR_NO_SELECTED_PATTERN` — and the run's
        `development_pattern_id` is bound to that covering pattern at
        computation time."

        Design: Corner/validations/run_creation_without_selected_pattern_rejected
        """
        ctx = setup_minimal_book_with_triangle()
        # The pattern is created but left DRAFT — never selected.
        create_pattern(ctx["segment"]["id"], "PAID", "2025-Q1", "2025-Q1", "2025-Q3")

        resp = api.create_reserve_run(
            {
                "segment_id": ctx["segment"]["id"],
                "valuation_quarter": "2025-Q1",
                "method": "CHAIN_LADDER",
                "basis": "PAID",
            },
            actuarial_analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_SELECTED_PATTERN)

    def test_duplicate_fresh_run_rejected(self, api, actuarial_analyst_headers):
        """PRD §3.5: "And at most one non-stale run may exist for a given
        segment, valuation quarter, method, and basis: a second fresh run for
        the same combination is refused with `ERR_RUN_ALREADY_EXISTS`."

        Design: Corner/validations/duplicate_fresh_run_rejected
        """
        ctx = setup_minimal_book_with_run()
        resp = api.create_reserve_run(
            {
                "segment_id": ctx["segment"]["id"],
                "valuation_quarter": "2025-Q1",
                "method": "CHAIN_LADDER",
                "basis": "PAID",
            },
            actuarial_analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RUN_ALREADY_EXISTS)

    def test_run_creation_with_stale_triangle_rejected(
        self, api, actuarial_analyst_headers
    ):
        """PRD §3.5: "The triangle for the segment, basis, and valuation
        quarter must be non-stale, else `ERR_TRIANGLE_STALE`."
        PRD §2.7: "Posting a claim transaction sets `is_stale` to true on every
        triangle of the segment whose valuation quarter is on or after the
        transaction's effective quarter."

        Design: Corner/validations/run_creation_with_stale_triangle_rejected
        """
        ctx = setup_minimal_book_with_pattern()
        # A payment dated inside the triangle's valuation quarter dirties it.
        post_payment(ctx["claim"]["id"], "2025-02-20T00:00:00Z", 2000)

        resp = api.create_reserve_run(
            {
                "segment_id": ctx["segment"]["id"],
                "valuation_quarter": "2025-Q1",
                "method": "CHAIN_LADDER",
                "basis": "PAID",
            },
            actuarial_analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TRIANGLE_STALE)


class TestStudyCreationUniqueness:
    def test_duplicate_open_study_for_quarter_rejected(
        self, api, actuarial_analyst_headers
    ):
        """PRD §3.7: "At most one non-`WITHDRAWN` study may exist per segment
        and valuation quarter; a second active study for the same pair is
        refused with `ERR_STUDY_ALREADY_EXISTS`."
        PRD §3.7: "Withdrawal moves a study to the terminal `WITHDRAWN` state
        from `DRAFT`, `IN_REVIEW`, or `APPROVED`"

        Design: Corner/validations/duplicate_open_study_for_quarter_rejected
        """
        ctx = setup_minimal_book()
        first = create_study(ctx["segment"]["id"], "2025-Q1", "CHAIN_LADDER", "PAID")

        resp = api.create_study(
            {
                "segment_id": ctx["segment"]["id"],
                "valuation_quarter": "2025-Q1",
                "selected_method": "BORNHUETTER_FERGUSON",
                "selected_basis": "PAID",
            },
            actuarial_analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STUDY_ALREADY_EXISTS)

        withdraw_study_by(first["id"])
        resp = api.create_study(
            {
                "segment_id": ctx["segment"]["id"],
                "valuation_quarter": "2025-Q1",
                "selected_method": "BORNHUETTER_FERGUSON",
                "selected_basis": "PAID",
            },
            actuarial_analyst_headers,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT", (
            "withdrawing the first study frees the (segment, quarter) slot"
        )


class TestStudyRevisionOcc:
    def test_study_patch_occ_stale_version_conflict(
        self, api, actuarial_analyst_headers
    ):
        """PRD §2.9: "When `expected_study_version` does not equal the study's
        current `version`, the revision is rejected with `ERR_STALE_VERSION`
        (HTTP 412), preventing the client from silently overwriting a selection
        change it has not observed."
        PRD §3.7: "While a study is in `DRAFT`, the analyst may revise its
        `selected_method` or `selected_basis`; both are optional on a revision,
        and the request must also carry `expected_study_version` under the
        optimistic-concurrency rule of §2.9 — a stale expectation is refused
        with `ERR_STALE_VERSION`."

        Design: Corner/cross_cutting_layers/study_patch_occ_stale_version_conflict
        """
        ctx = setup_minimal_book()
        study = create_study(ctx["segment"]["id"], "2025-Q1", "CHAIN_LADDER", "PAID")
        observed_version = study["version"]

        resp = api.patch_study(
            study["id"],
            patch_study_payload(observed_version, selected_method="BORNHUETTER_FERGUSON"),
            actuarial_analyst_headers,
        )
        data = validate_success(resp, 200)
        assert data["version"] == observed_version + 1, (
            "the revision increments the study's version by one"
        )
        assert data["selected_method"] == "BORNHUETTER_FERGUSON"

        # A second revision carrying the pre-mutation version is stale.
        resp = api.patch_study(
            study["id"],
            patch_study_payload(observed_version, selected_method="CHAIN_LADDER"),
            actuarial_analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        data = validate_success(api.get_study(study["id"], actuarial_analyst_headers))
        assert data["selected_method"] == "BORNHUETTER_FERGUSON", (
            "the rejected revision must leave no partial write"
        )
        assert data["version"] == observed_version + 1


class TestStudyTerminalLockdown:
    def test_study_withdrawn_terminal_lockdown(self, api, actuarial_analyst_headers):
        """PRD §3.7: "Acting on a `LOCKED` or `WITHDRAWN` study — or
        submitting, reviewing, revising, or withdrawing from a status the
        transition does not start from — is refused with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/study_withdrawn_terminal_lockdown
        """
        ctx = setup_minimal_book_with_run()
        study = create_study(ctx["segment"]["id"], "2025-Q1", "CHAIN_LADDER", "PAID")
        withdrawn = withdraw_study_by(study["id"])
        assert withdrawn["status"] == "WITHDRAWN"

        resp = api.submit_study(study["id"], actuarial_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        data = validate_success(api.get_study(study["id"], actuarial_analyst_headers))
        assert data["status"] == "WITHDRAWN"
