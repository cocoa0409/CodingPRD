"""Baseline documentation: completeness bar, review loop, disposition rules
(PRD §3.1)."""
from test_helpers import (
    ApiErrorId,
    accept_baseline,
    create_baseline,
    create_draft_easement,
    create_initial_landowner,
    make_board_reviewer_headers,
    submit_baseline,
    validate_error,
    validate_success,
)


def _get_baseline(api, baseline_id, headers):
    return validate_success(api.get_baseline_report(baseline_id, headers), 200)


class TestBaselineReviewLoop:
    def test_baseline_revision_loop_increments_review_round(self, api, coordinator_headers,
                                                            trust_admin_headers):
        """PRD §3.1: "Each successful submission moves the report to `SUBMITTED`,
        increments `review_round` by one, and stamps `submitted_on` with the
        clock date."
        PRD §3.1: "Requesting revision returns the report to `REVISION_REQUESTED`
        and captures the reviewer's `revision_notes`; the coordinator revises and
        submits again, and the cycle can repeat."
        PRD §3.1: "Acceptance moves it to `ACCEPTED` and stamps `accepted_on`
        with the clock date"

        Design: Corner/state_machines/baseline_revision_loop_increments_review_round
        """
        easement = create_draft_easement(name="E-BL", parcel_acreage=500)
        create_initial_landowner(easement["id"])
        baseline = create_baseline(easement["id"], prepared_by="staff-prep-1",
                                   photo_point_count=5)
        assert baseline["review_round"] == 0
        assert baseline["status"] == "DRAFT"

        first = validate_success(
            api.submit_baseline_report(baseline["id"], coordinator_headers), 200
        )
        assert first["status"] == "SUBMITTED"
        assert first["review_round"] == 1

        revision = validate_success(
            api.request_baseline_revision(
                baseline["id"], {"revision_notes": "add photos"},
                make_board_reviewer_headers("board-1"),
            ),
            200,
        )
        assert revision["status"] == "REVISION_REQUESTED"

        second = validate_success(
            api.submit_baseline_report(baseline["id"], coordinator_headers), 200
        )
        assert second["status"] == "SUBMITTED"
        assert second["review_round"] == 2

        accepted = validate_success(
            api.accept_baseline_report(
                baseline["id"], make_board_reviewer_headers("board-1")
            ),
            200,
        )
        assert accepted["status"] == "ACCEPTED"


class TestBaselineCompleteness:
    def test_baseline_submit_incomplete_rejected(self, api, coordinator_headers,
                                                 trust_admin_headers):
        """PRD §3.1: "`photo_point_count` must be at least `required_photo_points`,
        where `required_photo_points` is the larger of 4 and the parcel's acreage
        divided by 100 rounded up to a whole number, recomputed from the
        easement's current acreage at submit time. Submitting short of that bar
        is rejected with `ERR_INCOMPLETE_BASELINE` (422)"

        Design: Corner/state_machines/baseline_submit_incomplete_rejected
        """
        # 500 acres -> the bar is max(4, ceil(500/100)) = 5, so 4 photo points fail.
        easement = create_draft_easement(name="E-INC", parcel_acreage=500,
                                         matrix={"AGRICULTURE": "PERMITTED"})
        baseline = create_baseline(easement["id"], prepared_by="staff-prep-1",
                                   photo_point_count=4)
        resp = api.submit_baseline_report(baseline["id"], coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INCOMPLETE_BASELINE)
        assert _get_baseline(api, baseline["id"], trust_admin_headers)["status"] == "DRAFT"

        # A sibling 500-acre baseline carrying exactly 5 photo points submits —
        # together with the failure above, the bar is pinned to exactly 5.
        easement_ok = create_draft_easement(name="E-INC-OK", parcel_acreage=500,
                                            matrix={"AGRICULTURE": "PERMITTED"})
        baseline_ok = create_baseline(easement_ok["id"], prepared_by="staff-prep-1",
                                      photo_point_count=5)
        submitted = validate_success(
            api.submit_baseline_report(baseline_ok["id"], coordinator_headers), 200
        )
        assert submitted["status"] == "SUBMITTED"

    def test_required_photo_points_floor_and_ceiling(self, api, coordinator_headers):
        """PRD §3.1: "`photo_point_count` must be at least `required_photo_points`,
        where `required_photo_points` is the larger of 4 and the parcel's acreage
        divided by 100 rounded up to a whole number, recomputed from the
        easement's current acreage at submit time."

        Design: Corner/calculations/required_photo_points_floor_and_ceiling
        """
        # 250 acres: ceil(250/100) = 3, so the floor binds at 4 —
        # 3 photo points must fail and 4 must succeed.
        e250_short = create_draft_easement(name="E-RP1", parcel_acreage=250,
                                           matrix={"AGRICULTURE": "PERMITTED"})
        b250_short = create_baseline(e250_short["id"], prepared_by="staff-prep-1",
                                     photo_point_count=3)
        validate_error(
            api.submit_baseline_report(b250_short["id"], coordinator_headers),
            ApiErrorId.ERR_INCOMPLETE_BASELINE,
        )

        e250_exact = create_draft_easement(name="E-RP1B", parcel_acreage=250,
                                           matrix={"AGRICULTURE": "PERMITTED"})
        b250_exact = create_baseline(e250_exact["id"], prepared_by="staff-prep-1",
                                     photo_point_count=4)
        ok250 = validate_success(
            api.submit_baseline_report(b250_exact["id"], coordinator_headers), 200
        )
        assert ok250["status"] == "SUBMITTED"

        # 500 acres: ceil(500/100) = 5 exceeds the floor —
        # 4 photo points must fail and 5 must succeed.
        e500_short = create_draft_easement(name="E-RP2", parcel_acreage=500,
                                           matrix={"AGRICULTURE": "PERMITTED"})
        b500_short = create_baseline(e500_short["id"], prepared_by="staff-prep-1",
                                     photo_point_count=4)
        validate_error(
            api.submit_baseline_report(b500_short["id"], coordinator_headers),
            ApiErrorId.ERR_INCOMPLETE_BASELINE,
        )

        e500_exact = create_draft_easement(name="E-RP2B", parcel_acreage=500,
                                           matrix={"AGRICULTURE": "PERMITTED"})
        b500_exact = create_baseline(e500_exact["id"], prepared_by="staff-prep-1",
                                     photo_point_count=5)
        ok500 = validate_success(
            api.submit_baseline_report(b500_exact["id"], coordinator_headers), 200
        )
        assert ok500["status"] == "SUBMITTED"


class TestBaselineDispositionRules:
    def test_baseline_accept_from_draft_rejected(self, api, trust_admin_headers):
        """PRD §3.1: "Either disposition attempted on a report that is not
        `SUBMITTED` is rejected with `ERR_INVALID_BASELINE_STATE`."

        Design: Corner/state_machines/baseline_accept_from_draft_rejected
        """
        easement = create_draft_easement(name="E-BS", parcel_acreage=100,
                                         matrix={"AGRICULTURE": "PERMITTED"})
        baseline = create_baseline(easement["id"], prepared_by="staff-prep-1",
                                   photo_point_count=4)
        resp = api.accept_baseline_report(
            baseline["id"], make_board_reviewer_headers("board-1")
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_BASELINE_STATE)
        assert _get_baseline(api, baseline["id"], trust_admin_headers)["status"] == "DRAFT"

    def test_baseline_accept_by_preparer_sod_rejected(self, api, coordinator_headers,
                                                      trust_admin_headers):
        """PRD §3.1: "the acceptor must not be the preparer — an `X-User-ID`
        matching `prepared_by_user_id` is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."
        PRD §2.11: "Four prepare-and-approve pairs are segregated, and crossing
        any of them with a single identity is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (403): the staffer who prepared a baseline
        report (`prepared_by_user_id`) may not accept it; the staffer who
        detected a violation (`detected_by_user_id`) may not verify its
        resolution; the board reviewer who executed an enforcement agreement
        (`executed_by_user_id`) may not complete it; and the submitter of an
        amendment (`submitted_by_user_id`) may not approve it."

        Design: Corner/errors/baseline_accept_by_preparer_sod_rejected
        """
        easement = create_draft_easement(name="E-SD", parcel_acreage=100,
                                         matrix={"AGRICULTURE": "PERMITTED"})
        baseline = create_baseline(easement["id"], prepared_by="staff-prep-1",
                                   photo_point_count=4)
        submit_baseline(baseline["id"])

        resp = api.accept_baseline_report(
            baseline["id"], make_board_reviewer_headers("staff-prep-1")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert _get_baseline(api, baseline["id"], trust_admin_headers)["status"] == "SUBMITTED"

    def test_duplicate_baseline_rejected(self, api, coordinator_headers):
        """PRD §3.1: "A `StewardshipCoordinator` creates the easement's single
        baseline report — a second one for the same easement is rejected with
        `ERR_BASELINE_ALREADY_EXISTS`"

        Design: Corner/validations/duplicate_baseline_rejected
        """
        easement = create_draft_easement(name="E-DB", parcel_acreage=100,
                                         matrix={"AGRICULTURE": "PERMITTED"})
        create_baseline(easement["id"], prepared_by="staff-prep-1", photo_point_count=4)
        resp = api.create_baseline_report(
            {
                "easement_id": easement["id"],
                "prepared_by_user_id": "staff-prep-2",
                "condition_narrative": "second attempt",
                "photo_point_count": 6,
            },
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BASELINE_ALREADY_EXISTS)
