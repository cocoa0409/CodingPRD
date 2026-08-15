"""Notice-of-default / notice-of-trustee's-sale lifecycle and publication rules."""
from test_helpers import (
    ADMIN,
    CM,
    ApiErrorId,
    assert_date_equals,
    create_beneficiary,
    create_case,
    create_nod_payload,
    create_nots_payload,
    create_publication_payload,
    get_case,
    record_nod,
    record_nots,
    record_publication,
    set_clock,
    setup_case_at_nots_recorded,
    setup_case_with_nod,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestNotsStatutoryBoundary:
    """Ninety-day reinstatement window boundary at the notice-of-sale record."""

    def test_nots_recorded_day_89_rejected(self, api):
        """PRD §3.2: "During it the borrower may cure the default by accepting a reinstatement quote (Section 3.6), and the trustee may not yet record the notice of trustee's sale: such a recording attempted before the clock date reaches `reinstatement_deadline_date` is rejected with `ERR_NOTS_TOO_EARLY` (HTTP 422), with recording on the deadline day itself permitted."

        Design: Difficulty/boundary_precision_check/nots_day90_boundary_allowed_day89_rejected
        """
        ctx = setup_case_with_nod("BEN-B1", loan_reference="LN-B1")
        case_id = ctx["case"]["id"]
        # NOD recorded 2026-08-01 -> reinstatement deadline 2026-10-30.
        set_clock("2026-10-29T00:00:00Z")
        resp = api.record_nots(
            case_id,
            create_nots_payload("2026-10-29", instrument_number="NOTS-EARLY"),
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_NOTS_TOO_EARLY, 422)

    def test_nots_recorded_day_90_allowed(self, api):
        """PRD §3.3: "Recording requires the case to be in `NOD_RECORDED` with `hold_status` of `CLEAR`, the clock date to be on or after the `reinstatement_deadline_date` (exactly on the deadline day is allowed), a `RECORDED` notice of default to exist on the case, and no other notice of trustee's sale in `RECORDED`, `PUBLICATION_COMPLETE`, or `SALE_SCHEDULED` status to exist on the case — a case carries at most one live trustee's-sale notice at a time."

        Design: Difficulty/boundary_precision_check/nots_day90_boundary_allowed_day89_rejected
        """
        ctx = setup_case_with_nod("BEN-B1", loan_reference="LN-B1")
        case_id = ctx["case"]["id"]
        nots = record_nots(case_id, recording_date="2026-10-30",
                           instrument_number="NOTS-B1")
        assert nots["status"] == "RECORDED"
        case = get_case(case_id)
        assert case["lifecycle_status"] == "NOTS_RECORDED", (
            f"boundary-day recording must advance the case, got {case['lifecycle_status']}"
        )


class TestPublicationGapSpacing:
    def test_publication_six_day_gap_rejected(self, api):
        """PRD §3.3: "then the run date must fall at least seven days after the most recent sibling run — a run exactly seven days later is acceptable — failing which the rejection is `ERR_PUBLICATION_GAP_VIOLATION` (HTTP 422);"

        Design: Difficulty/resource_temporal_overlap/publication_min_gap_spacing
        """
        ctx = setup_case_at_nots_recorded("BEN-O2", loan_reference="LN-O2")
        nots_id = ctx["nots"]["id"]
        record_publication(nots_id, "2026-11-02")
        set_clock("2026-11-08T00:00:00Z")
        resp = api.create_publication(
            nots_id, create_publication_payload("2026-11-08"), CM
        )
        validate_error(resp, ApiErrorId.ERR_PUBLICATION_GAP_VIOLATION, 422)

    def test_publication_seven_day_gap_accepted(self, api):
        """PRD §3.3: "then the run date must fall at least seven days after the most recent sibling run — a run exactly seven days later is acceptable — failing which the rejection is `ERR_PUBLICATION_GAP_VIOLATION` (HTTP 422);"
        PRD §3.3: "The notice's `first_publication_date` is maintained as the earliest `run_date` among its publication children and remains null until the first run is recorded."

        Design: Difficulty/resource_temporal_overlap/publication_min_gap_spacing
        """
        ctx = setup_case_at_nots_recorded("BEN-O2", loan_reference="LN-O2")
        nots_id = ctx["nots"]["id"]
        record_publication(nots_id, "2026-11-02")
        pub2 = record_publication(nots_id, "2026-11-09")
        assert pub2["run_index"] == 2, (
            f"run_index is the one-based creation-order sequence, got {pub2['run_index']}"
        )
        nots = validate_success(api.get_nots(nots_id, CM), 200)
        assert_date_equals(
            nots["first_publication_date"], "2026-11-02",
            label="first_publication_date",
        )


class TestNodRecordingGuards:
    def test_second_nod_while_recorded_rejected(self, api):
        """PRD §3.2: "The recording is permitted only when the case is still `REFERRED`, the case's `hold_status` is `CLEAR`, and the beneficiary is `ACTIVE` — and the checks are evaluated in that order, so a case under an active stay surfaces `ERR_ACTIVE_STAY` rather than `ERR_BENEFICIARY_SUSPENDED` even when the beneficiary is also suspended, while a case that has already moved past referral fails first with `ERR_INVALID_CASE_STATE` (HTTP 409)."

        Design: Corner/state_machines/second_nod_while_recorded_rejected
        """
        ctx = setup_case_with_nod("BEN-S1", loan_reference="LN-S1")
        resp = api.record_nod(
            ctx["case"]["id"],
            create_nod_payload(instrument_number="NOD-S1B"),
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_CASE_STATE, 409)

    def test_nod_record_on_suspended_beneficiary_rejected(self, api):
        """PRD §3.1: "Suspension is a one-way administrative action: a `TrusteeAdmin` may move a beneficiary from `ACTIVE` to `SUSPENDED`, which increments the beneficiary's `version` and blocks the recording of any new notice of default on every case that beneficiary owns — such an attempt is rejected with `ERR_BENEFICIARY_SUSPENDED` (HTTP 422)."

        Design: Corner/errors/nod_record_on_suspended_beneficiary_rejected
        """
        ben = create_beneficiary("BEN-ER11")
        case = create_case(ben["id"], loan_reference="LN-ER11")
        suspended = validate_success(api.suspend_beneficiary(ben["id"], ADMIN), 200)
        assert suspended["status"] == "SUSPENDED"
        resp = api.record_nod(
            case["id"],
            create_nod_payload(instrument_number="NOD-ER11"),
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_BENEFICIARY_SUSPENDED, 422)


class TestRescission:
    def test_terminal_case_lockdown_rejected(self, api):
        """PRD §3.2: "A case in `CANCELLED` is terminal; nothing further may be recorded or accepted against it."
        PRD §3.6: "Issuance requires the case to be in a non-terminal status (`ERR_INVALID_CASE_STATE` otherwise), and because a new quote of the same type legitimately supersedes the prior issued one, the payload must carry `expected_foreclosure_case_version` matching the case's current `version` — the case-state check runs first, then the staleness check, and a stale writer is rejected with `ERR_STALE_CASE_VERSION`."

        Design: Corner/state_machines/terminal_case_lockdown_rejected
        """
        ctx = setup_case_with_nod("BEN-S2", loan_reference="LN-S2")
        case_id = ctx["case"]["id"]
        validate_success(api.rescind_nod(ctx["nod"]["id"], CM), 200)
        case = get_case(case_id)
        assert case["lifecycle_status"] == "CANCELLED"
        resp = api.create_quote(
            case_id,
            {
                "quote_type": "PAYOFF",
                "good_through_date": "2026-09-01",
                "expected_foreclosure_case_version": case["version"],
            },
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_CASE_STATE, 409)

    def test_immediate_consistency_read_after_cascade(self, api):
        """PRD §3.2: "A `CaseManager` may rescind a notice of default that is still `RECORDED` while the case sits in `NOD_RECORDED`, `NOTS_RECORDED`, or `SALE_SCHEDULED`; the notice's `status` becomes `RESCINDED`, its `rescinded_at` is stamped, and the case moves to `CANCELLED`."

        Design: Corner/consistency_model/immediate_consistency_read_after_cascade
        """
        ctx = setup_case_with_nod("BEN-K9", loan_reference="LN-K9")
        nod = validate_success(api.rescind_nod(ctx["nod"]["id"], CM), 200)
        assert nod["status"] == "RESCINDED", (
            "the rescind response itself must report RESCINDED"
        )
        case = get_case(ctx["case"]["id"])
        assert case["lifecycle_status"] == "CANCELLED", (
            "an immediate follow-up read must agree with the cascade"
        )


class TestPublicationCompletion:
    def test_publication_bubble_up_on_third_affidavit_only(self, api):
        """PRD §3.3: "When the third publication child reaches `AFFIDAVIT_FILED` — exactly three runs, all with affidavits filed — the parent notice bubbles up from `RECORDED` to `PUBLICATION_COMPLETE` automatically, with `first_publication_date` already in place from the runs themselves."

        Design: Corner/state_machines/publication_bubble_up_not_complete_before_third_affidavit
        """
        ctx = setup_case_at_nots_recorded("BEN-S3", loan_reference="LN-S3")
        nots_id = ctx["nots"]["id"]
        p1 = record_publication(nots_id, "2026-11-02")
        p2 = record_publication(nots_id, "2026-11-09")
        p3 = record_publication(nots_id, "2026-11-16")

        validate_success(api.file_affidavit(p1["id"], CM), 200)
        validate_success(api.file_affidavit(p2["id"], CM), 200)
        mid = validate_success(api.get_nots(nots_id, CM), 200)
        assert mid["status"] == "RECORDED", (
            f"two of three affidavits is not complete, got {mid['status']}"
        )

        validate_success(api.file_affidavit(p3["id"], CM), 200)
        end = validate_success(api.get_nots(nots_id, CM), 200)
        assert end["status"] == "PUBLICATION_COMPLETE", (
            f"the third affidavit must bubble the notice up, got {end['status']}"
        )

    def test_fourth_publication_rejected(self, api):
        """PRD §3.3: "finally, a notice accepts at most three publication runs, and a fourth attempt is rejected with `ERR_PUBLICATION_LIMIT` (HTTP 422)."

        Design: Corner/state_machines/fourth_publication_rejected
        """
        ctx = setup_case_at_nots_recorded("BEN-S4", loan_reference="LN-S4")
        nots_id = ctx["nots"]["id"]
        record_publication(nots_id, "2026-11-02")
        record_publication(nots_id, "2026-11-09")
        record_publication(nots_id, "2026-11-16")
        set_clock("2026-11-23T00:00:00Z")
        resp = api.create_publication(
            nots_id, create_publication_payload("2026-11-23"), CM
        )
        validate_error(resp, ApiErrorId.ERR_PUBLICATION_LIMIT, 422)

    def test_publication_on_voided_nots_rejected(self, api):
        """PRD §3.3: "Three rules govern publication recording, evaluated after the request schema checks (including the requirement that `run_date` not lie in the future, which surfaces as `ERR_INVALID_REQUEST`): first the notice itself must be in `RECORDED` or `PUBLICATION_COMPLETE` status, failing which the request is rejected with `ERR_INVALID_NOTS_STATE`;"
        PRD §3.2: "From `NOTS_RECORDED`: the notice is rescinded; additionally, the case's notice of trustee's sale in `RECORDED` or `PUBLICATION_COMPLETE` status becomes `VOIDED`, every `ISSUED` quote becomes `VOIDED`, and the case becomes `CANCELLED`."

        Design: Corner/errors/publication_on_voided_nots_rejected
        """
        ctx = setup_case_at_nots_recorded("BEN-ER6", loan_reference="LN-ER6")
        validate_success(api.rescind_nod(ctx["nod"]["id"], CM), 200)
        resp = api.create_publication(
            ctx["nots"]["id"], create_publication_payload("2026-10-30"), CM
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_NOTS_STATE, 409)


class TestLogicalClockDefault:
    def test_clock_default_fixed_instant(self, api):
        """PRD §2.5: "At startup, before any call has been made, the logical clock reads exactly `2026-08-01T00:00:00Z`."
        PRD §2.5: "Several date-bearing inputs are checked against the logical clock as part of request validation, and violations are rejected with `ERR_INVALID_REQUEST` (HTTP 400):"
        PRD §2.5: "The `recording_date` of a notice of default and the `recording_date` of a notice of trustee's sale must each equal the current logical-clock UTC date."

        Design: Corner/cross_cutting_complexity_layers/clock_default_fixed_instant
        """
        # No clock call is made anywhere in this test: the startup default rules.
        ben = create_beneficiary("BEN-L5")
        case = create_case(ben["id"], loan_reference="LN-L5")
        future = api.record_nod(
            case["id"],
            create_nod_payload(
                recording_date="2026-08-02", instrument_number="NOD-FUTURE"
            ),
            CM,
        )
        validate_error(future, ApiErrorId.ERR_INVALID_REQUEST, 400)
        nod = validate_success(
            api.record_nod(
                case["id"],
                create_nod_payload(
                    recording_date="2026-08-01", instrument_number="NOD-L5"
                ),
                CM,
            ),
            201,
        )
        assert nod["status"] == "RECORDED"
