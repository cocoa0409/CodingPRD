"""Stop-the-clock extensions: half-open overlap, merge arithmetic, the 730-day
cap, the approve/rescind clock invariant, and state locks (PRD §2.8, §3.3)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_dossier_item,
    assert_clock_extension,
    assert_date_eq,
    assert_instant_eq,
    complete_midterm,
    file_clock_extension,
    make_candidate_headers,
    open_case,
    read_case,
    register_candidate,
    set_logical_clock,
    validate_error,
    validate_success,
)

PO_HEADERS = TEST_USERS["provost_creator_headers"]


def _fresh_case(employee_id):
    set_logical_clock()
    candidate = register_candidate(employee_id)
    case = open_case(candidate["id"], clock_policy="ANNIVERSARY")
    return candidate, case


class TestHalfOpenOverlap:
    def test_touching_extension_interval_approved_and_merged(self, api):
        """PRD §2.8: "Stop-the-clock intervals are half-open — the end date
        itself is excluded — so two approved intervals that merely touch, where
        one's `interval_start` equals the other's `interval_end`, do not overlap
        and are both permitted."
        PRD §3.3: "On approval the request moves to `APPROVED` with `decided_at`
        stamped, the case's `extension_days` is recomputed as the sum, in whole
        days, of the merged union of all approved intervals, the
        `mandatory_review_date` is recomputed accordingly, and the case's
        `version` increments by one."

        Design: Difficulty/resource_temporal_overlap/extension_half_open_touch_allowed_overlap_rejected
        """
        candidate, case = _fresh_case("E1800")
        ext1 = file_clock_extension(
            case["id"], candidate["id"], "2023-01-01", "2023-04-01",
            reason="PARENTAL_LEAVE",
        )
        approve = validate_success(api.approve_clock_extension(ext1["id"], PO_HEADERS))
        assert approve["status"] == "APPROVED"
        case_after_first = read_case(case["id"])
        assert case_after_first["extension_days"] == 90
        assert_date_eq(
            case_after_first["mandatory_review_date"], "2026-10-30",
            "mandatory_review_date after the first approval",
        )

        # Touching interval [2023-04-01, 2023-07-01) shares only the endpoint.
        ext2 = file_clock_extension(
            case["id"], candidate["id"], "2023-04-01", "2023-07-01",
            reason="MEDICAL_LEAVE",
        )
        approve2 = validate_success(api.approve_clock_extension(ext2["id"], PO_HEADERS))
        assert approve2["status"] == "APPROVED"
        case_after_second = read_case(case["id"])
        assert case_after_second["extension_days"] == 181, (
            "Merged union of 90 + 91 touching days must total 181"
        )
        assert_date_eq(
            case_after_second["mandatory_review_date"], "2027-01-29",
            "mandatory_review_date after the touching approval",
        )

    def test_overlapping_extension_interval_rejected(self, api):
        """PRD §3.3: "First, the candidate interval must not overlap any approved
        interval under the half-open semantics of §2.8 — touching intervals,
        where the new `interval_start` equals an existing `interval_end`, are
        permitted — otherwise `ERR_EXTENSION_INTERVAL_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/extension_half_open_touch_allowed_overlap_rejected
        """
        candidate, case = _fresh_case("E1801")
        ext1 = file_clock_extension(
            case["id"], candidate["id"], "2023-01-01", "2023-04-01",
            reason="PARENTAL_LEAVE",
        )
        validate_success(api.approve_clock_extension(ext1["id"], PO_HEADERS))
        ext2 = file_clock_extension(
            case["id"], candidate["id"], "2023-04-01", "2023-07-01",
            reason="MEDICAL_LEAVE",
        )
        validate_success(api.approve_clock_extension(ext2["id"], PO_HEADERS))

        # [2023-03-15, 2023-05-15) genuinely intersects both approved spans.
        ext3 = file_clock_extension(
            case["id"], candidate["id"], "2023-03-15", "2023-05-15",
            reason="BEREAVEMENT",
        )
        err = api.approve_clock_extension(ext3["id"], PO_HEADERS)
        validate_error(err, ApiErrorId.ERR_EXTENSION_INTERVAL_OVERLAP)

        ext3_after = validate_success(api.get_clock_extension(ext3["id"], PO_HEADERS))
        assert ext3_after["status"] == "PENDING", "Rejection is not a transition"
        case_after = read_case(case["id"])
        assert case_after["extension_days"] == 181, (
            "The failed approval must leave the clock unchanged"
        )
        assert_date_eq(case_after["mandatory_review_date"], "2027-01-29")


def test_extension_day_cap_boundary_730(api):
    """PRD §2.8: "The approved stop-the-clock intervals of a case are merged into
    their union — overlapping or touching intervals coalesce — and the union's
    total length may never exceed 730 days, the policy cap of two years of
    stopped clock."
    PRD §3.3: "A union exceeding the cap is rejected with
    `ERR_EXTENSION_CAP_EXCEEDED`."

    Design: Corner/calculations/extension_day_cap_boundary_730
    """
    candidate, case = _fresh_case("E9202")
    ext1 = file_clock_extension(
        case["id"], candidate["id"], "2022-01-01", "2023-01-01",
        reason="PARENTAL_LEAVE",
    )
    validate_success(api.approve_clock_extension(ext1["id"], PO_HEADERS))
    # Touching ext1: merged total becomes exactly 730, which passes the cap.
    ext2 = file_clock_extension(
        case["id"], candidate["id"], "2023-01-01", "2024-01-01",
        reason="MEDICAL_LEAVE",
    )
    approve2 = validate_success(api.approve_clock_extension(ext2["id"], PO_HEADERS))
    assert approve2["status"] == "APPROVED"

    # One more month would push the merged union to 761 days.
    ext3 = file_clock_extension(
        case["id"], candidate["id"], "2024-01-01", "2024-02-01",
        reason="BEREAVEMENT",
    )
    err = api.approve_clock_extension(ext3["id"], PO_HEADERS)
    validate_error(err, ApiErrorId.ERR_EXTENSION_CAP_EXCEEDED)
    assert read_case(case["id"])["extension_days"] == 730


class TestApproveRescindClockInvariant:
    def test_approve_extension_shifts_clock(self, api):
        """PRD §3.3: "On approval the request moves to `APPROVED` with
        `decided_at` stamped, the case's `extension_days` is recomputed as the
        sum, in whole days, of the merged union of all approved intervals, the
        `mandatory_review_date` is recomputed accordingly, and the case's
        `version` increments by one."

        Design: Difficulty/compensating_invariant/extension_approve_rescind_preserves_clock
        """
        candidate, case = _fresh_case("E2100")
        baseline = read_case(case["id"])
        assert baseline["extension_days"] == 0
        assert_date_eq(baseline["mandatory_review_date"], "2026-08-01")

        ext = file_clock_extension(
            case["id"], candidate["id"], "2023-01-01", "2023-04-01",
            reason="MEDICAL_LEAVE",
        )
        validate_success(api.approve_clock_extension(ext["id"], PO_HEADERS))
        after = read_case(case["id"])
        assert after["extension_days"] == 90
        assert_date_eq(after["mandatory_review_date"], "2026-10-30")

    def test_rescind_restores_clock_and_advances_version(self, api):
        """PRD §3.3: "An officer may also rescind an `APPROVED` request, moving
        it to `RESCINDED`: `decided_at` is stamped anew, `extension_days` and
        `mandatory_review_date` are recomputed without the rescinded interval,
        and the case's `version` increments by one."
        PRD §2.6: "approving or rescinding a clock-extension request each
        increment the case's `version` by one".

        Design: Difficulty/compensating_invariant/extension_approve_rescind_preserves_clock
        """
        candidate, case = _fresh_case("E2101")
        baseline_version = read_case(case["id"])["version"]

        ext = file_clock_extension(
            case["id"], candidate["id"], "2023-01-01", "2023-04-01",
            reason="MEDICAL_LEAVE",
        )
        validate_success(api.approve_clock_extension(ext["id"], PO_HEADERS))
        rescinded = validate_success(api.rescind_clock_extension(ext["id"], PO_HEADERS))
        assert rescinded["status"] == "RESCINDED"

        after = read_case(case["id"])
        assert after["extension_days"] == 0, "Rescind must restore extension_days"
        assert_date_eq(after["mandatory_review_date"], "2026-08-01")
        assert after["version"] == baseline_version + 2, (
            "Approve and rescind each increment the case version by one"
        )


def test_immediate_read_after_write_visibility(api):
    """PRD §2.6: "Cascades are executed atomically with their trigger: every
    mutation and every secondary effect it causes — status flips on the
    candidate, teardown of open invitations or rounds, retraction of cast
    ballots, creation of the next committee round — is visible in the same
    response."
    PRD §3.3: "On approval the request moves to `APPROVED` with `decided_at`
    stamped, the case's `extension_days` is recomputed as the sum, in whole days,
    of the merged union of all approved intervals, the `mandatory_review_date` is
    recomputed accordingly".

    Design: Corner/consistency_model/immediate_read_after_write_visibility
    """
    candidate, case = _fresh_case("E9700")
    ext = file_clock_extension(
        case["id"], candidate["id"], "2023-01-01", "2023-02-01",
        reason="MEDICAL_LEAVE",
    )
    approved = validate_success(api.approve_clock_extension(ext["id"], PO_HEADERS))
    assert approved["status"] == "APPROVED"
    assert_clock_extension(approved)
    assert_instant_eq(approved["decided_at"], "2026-08-01T00:00:00Z", "decided_at")

    # The very next read reflects the recomputed clock — no lag.
    after = read_case(case["id"])
    assert after["extension_days"] == 31
    assert_date_eq(after["mandatory_review_date"], "2026-09-01")


def test_extension_midterm_and_item_state_locks(api):
    """PRD §3.3: "Requests whose status does not permit the attempted transition
    are rejected with `ERR_INVALID_EXTENSION_STATE`."
    PRD §3.3: "completing an already-completed review is rejected with
    `ERR_INVALID_MIDTERM_STATE`".
    PRD §3.2: "Transitions that do not match the item's current status are
    rejected with `ERR_INVALID_ITEM_STATE`."

    Design: Corner/state_machines/extension_midterm_and_item_state_locks
    """
    candidate, case = _fresh_case("E9113")
    ext = file_clock_extension(
        case["id"], candidate["id"], "2023-01-01", "2023-02-01", reason="OTHER"
    )
    validate_success(api.deny_clock_extension(ext["id"], PO_HEADERS))

    review = complete_midterm(case["id"], outcome="SATISFACTORY")
    assert review["status"] == "COMPLETED"

    item = add_dossier_item(
        case["id"], candidate["id"], "SERVICE", "Old", page_count=3
    )
    validate_success(
        api.withdraw_dossier_item(item["id"], make_candidate_headers(candidate["id"]))
    )

    err_ext = api.approve_clock_extension(ext["id"], PO_HEADERS)
    validate_error(err_ext, ApiErrorId.ERR_INVALID_EXTENSION_STATE)

    err_mid = api.complete_midterm_review(
        review["id"], {"outcome": "CONCERNS"}, PO_HEADERS
    )
    validate_error(err_mid, ApiErrorId.ERR_INVALID_MIDTERM_STATE)

    err_item = api.submit_dossier_item(
        item["id"], make_candidate_headers(candidate["id"])
    )
    validate_error(err_item, ApiErrorId.ERR_INVALID_ITEM_STATE)
