"""Threshold arithmetic at the exact boundary and one unit beyond it."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CLAIMS_EXAMINER_HEADERS,
    ERR_ENROLLMENT_FILE_EMPTY,
    ERR_STOP_LOSS_NOT_ATTACHED,
    IPA_ADMIN_HEADERS,
    append_row,
    assert_fields,
    assign_enrollee,
    build_approved_claim,
    build_paid_claim,
    build_single_member_funded_pool,
    create_active_agreement,
    create_active_physician,
    create_enrollee,
    create_enrollment_file,
    create_pool,
    list_file_remittances,
    pay_claim_state,
    read_agreement,
    read_enrollee,
    read_file,
    read_physician,
    read_pool,
    set_clock,
    state_payload,
)


def _funded_pool_with_two_approved_claims(api):
    built = build_single_member_funded_pool(api, base_pmpm_cents=20000)
    built["large"] = build_approved_claim(
        api,
        built["agreement"]["id"],
        built["enrollee"]["id"],
        built["physician"]["id"],
        19000,
        service_date="2026-06-15T00:00:00Z",
    )
    built["one_cent"] = build_approved_claim(
        api,
        built["agreement"]["id"],
        built["enrollee"]["id"],
        built["physician"]["id"],
        1,
        service_date="2026-06-16T00:00:00Z",
    )
    return built


class TestPoolDeficitFlagStrictlyGreater:
    def test_exactly_9500_basis_points_does_not_flag_a_deficit(self, api):
        """PRD §3.5: "Equality does not flag: 20000 cents funded against 19000
        cents paid gives exactly 9500 basis points and leaves `deficit_flag`
        false, while 20000 funded against 19001 paid gives 9501 basis points and
        sets it true."

        Design: Difficulty/boundary_precision_check/pool_deficit_flag_strict_greater_at_9500_bps
        """
        built = _funded_pool_with_two_approved_claims(api)
        assert read_pool(api, built["pool"]["id"])["funded_cents"] == 20000

        pay_claim_state(api, built["large"]["id"])

        assert_fields(
            read_pool(api, built["pool"]["id"]),
            {"paid_claims_cents": 19000, "loss_ratio_bps": 9500, "deficit_flag": False},
        )

    def test_one_cent_beyond_the_threshold_sets_the_deficit_flag(self, api):
        """PRD §3.5: "Otherwise `loss_ratio_bps` is `paid_claims_cents`
        multiplied by 10000 and divided by `funded_cents`, rounded half up to
        whole basis points."

        Design: Difficulty/boundary_precision_check/pool_deficit_flag_strict_greater_at_9500_bps
        """
        built = _funded_pool_with_two_approved_claims(api)
        pay_claim_state(api, built["large"]["id"])
        pay_claim_state(api, built["one_cent"]["id"])

        assert_fields(
            read_pool(api, built["pool"]["id"]),
            {"paid_claims_cents": 19001, "loss_ratio_bps": 9501, "deficit_flag": True},
        )

    def test_the_posture_and_the_panel_only_move_once_the_flag_is_set(self, api):
        """PRD §3.1: "Otherwise, if any risk pool of the agreement has
        `deficit_flag` set to true, the posture is `UNDER_REVIEW`."

        Design: Difficulty/boundary_precision_check/pool_deficit_flag_strict_greater_at_9500_bps
        """
        built = _funded_pool_with_two_approved_claims(api)

        pay_claim_state(api, built["large"]["id"])
        assert (
            read_agreement(api, built["agreement"]["id"])["capitation_posture"]
            == "CURRENT"
        )
        assert read_physician(api, built["physician"]["id"])["panel_status"] == "OPEN"

        pay_claim_state(api, built["one_cent"]["id"])
        assert (
            read_agreement(api, built["agreement"]["id"])["capitation_posture"]
            == "UNDER_REVIEW"
        )
        assert (
            read_physician(api, built["physician"]["id"])["panel_status"]
            == "CLOSED_TO_NEW"
        )


def _member_paid_exactly_to_the_attachment(api):
    """One member whose paid total sits exactly on a 100000 cent attachment."""
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(
        api,
        reconciliation_method="ROSTER_SNAPSHOT",
        base_pmpm_cents=20000,
        quality_withhold_bps=0,
        professional_pool_share_bps=10000,
        institutional_pool_share_bps=0,
        stop_loss_attachment_cents=100000,
        reinsurance_recovery_bps=9000,
        max_panel_size=5,
    )
    physician = create_active_physician(api, agreement["id"])
    pool = create_pool(api, agreement["id"], pool_type="PROFESSIONAL")
    enrollee = create_enrollee(api, agreement["id"], risk_score_bps=10000)
    assign_enrollee(api, enrollee["id"], physician["id"])

    build_paid_claim(
        api,
        agreement["id"],
        enrollee["id"],
        physician["id"],
        100000,
        service_date="2026-04-10T00:00:00Z",
    )
    return {
        "agreement": agreement,
        "physician": physician,
        "pool": pool,
        "enrollee": enrollee,
    }


class TestStopLossAttachmentBoundary:
    def test_a_paid_total_exactly_at_attachment_is_refused(self, api):
        """PRD §2.10: "A recovery may be created only when the enrollee's
        paid-claim total in the pool strictly exceeds the agreement's
        `stop_loss_attachment_cents`; exactly at the attachment point the excess
        is zero and the create is refused."

        Design: Difficulty/boundary_precision_check/stop_loss_attachment_rejected_at_exact_then_allowed_one_cent_above
        """
        built = _member_paid_exactly_to_the_attachment(api)
        assert (
            read_enrollee(api, built["enrollee"]["id"])["cumulative_paid_claims_cents"]
            == 100000
        )
        assert (
            read_pool(api, built["pool"]["id"])["stop_loss_eligible_enrollee_count"] == 0
        )

        response = api.create_recovery(
            {"pool_id": built["pool"]["id"], "enrollee_id": built["enrollee"]["id"]},
            CLAIMS_EXAMINER_HEADERS,
        )
        validate_error(response, ERR_STOP_LOSS_NOT_ATTACHED, 422)

    def test_the_refused_create_leaves_no_recovery_row_behind(self, api):
        """PRD §3.7: "Exactly at attachment the excess is zero and the create is
        refused with `ERR_STOP_LOSS_NOT_ATTACHED`."

        Design: Difficulty/boundary_precision_check/stop_loss_attachment_rejected_at_exact_then_allowed_one_cent_above
        """
        built = _member_paid_exactly_to_the_attachment(api)
        api.create_recovery(
            {"pool_id": built["pool"]["id"], "enrollee_id": built["enrollee"]["id"]},
            CLAIMS_EXAMINER_HEADERS,
        )

        response = api.list_recoveries(
            CLAIMS_EXAMINER_HEADERS,
            {"pool_id": built["pool"]["id"], "limit": 10, "offset": 0},
        )
        rows, meta = validate_paginated(response)
        assert rows == []
        assert meta["total_count"] == 0

    def test_one_cent_above_attachment_yields_a_one_cent_recovery(self, api):
        """PRD §3.7: "`recovery_cents` is `excess_cents` multiplied by the
        agreement's `reinsurance_recovery_bps` as a proportion of 10000, rounded
        half up to whole cents in a single rounding step."

        Design: Difficulty/boundary_precision_check/stop_loss_attachment_rejected_at_exact_then_allowed_one_cent_above
        """
        built = _member_paid_exactly_to_the_attachment(api)
        build_paid_claim(
            api,
            built["agreement"]["id"],
            built["enrollee"]["id"],
            built["physician"]["id"],
            1,
            service_date="2026-04-11T00:00:00Z",
        )

        assert (
            read_enrollee(api, built["enrollee"]["id"])["cumulative_paid_claims_cents"]
            == 100001
        )
        assert (
            read_pool(api, built["pool"]["id"])["stop_loss_eligible_enrollee_count"] == 1
        )

        response = api.create_recovery(
            {"pool_id": built["pool"]["id"], "enrollee_id": built["enrollee"]["id"]},
            CLAIMS_EXAMINER_HEADERS,
        )
        recovery = validate_success(response, 201)
        assert_fields(
            recovery,
            {
                "attachment_cents": 100000,
                "eligible_paid_cents": 100001,
                "excess_cents": 1,
                "recovery_cents": 1,
                "status": "DRAFT",
            },
        )


def _file_with_no_rows(api):
    """A July file opened against a roster of exactly one assigned member."""
    agreement = create_active_agreement(
        api, quality_withhold_bps=0, max_panel_size=5
    )
    physician = create_active_physician(api, agreement["id"])
    enrollee = create_enrollee(api, agreement["id"], external_member_id="EF-0001")
    assign_enrollee(api, enrollee["id"], physician["id"])
    enrollment_file = create_enrollment_file(
        api, agreement["id"], coverage_month="2026-07"
    )
    return {
        "agreement": agreement,
        "physician": physician,
        "enrollee": enrollee,
        "file": enrollment_file,
    }


class TestEnrollmentFileRowCountBoundary:
    def test_a_file_with_zero_rows_cannot_be_parsed(self, api):
        """PRD §2.10: "An enrollment file may reach `PARSED` only when its
        `row_count` is at least 1, and may reach `RECONCILED` only when its
        `matched_row_count` is at least 1."

        Design: Difficulty/boundary_precision_check/enrollment_file_row_count_boundary_at_zero_then_one
        """
        built = _file_with_no_rows(api)
        assert built["file"]["row_count"] == 0

        response = api.set_enrollment_file_state(
            built["file"]["id"], state_payload("PARSED"), IPA_ADMIN_HEADERS
        )
        validate_error(response, ERR_ENROLLMENT_FILE_EMPTY, 422)
        assert read_file(api, built["file"]["id"])["status"] == "RECEIVED"

    def test_a_single_unmatched_row_parses_but_matches_nothing(self, api):
        """PRD §3.5: "If no enrollee was found, the row's `match_status` is
        `UNMATCHED`."

        Design: Difficulty/boundary_precision_check/enrollment_file_row_count_boundary_at_zero_then_one
        """
        built = _file_with_no_rows(api)
        append_row(
            api,
            built["file"]["id"],
            "EF-9999",
            built["physician"]["npi"],
            row_action="ADD",
            claimed_capitation_cents=20000,
        )

        parsed = validate_success(
            api.set_enrollment_file_state(
                built["file"]["id"], state_payload("PARSED"), IPA_ADMIN_HEADERS
            ),
            200,
        )
        assert_fields(
            parsed,
            {
                "status": "PARSED",
                "row_count": 1,
                "matched_row_count": 0,
                "exception_row_count": 1,
                "claimed_capitation_cents": 0,
            },
        )

        rows, _meta = validate_paginated(
            api.list_enrollment_file_rows(
                built["file"]["id"], IPA_ADMIN_HEADERS, {"limit": 10, "offset": 0}
            )
        )
        assert len(rows) == 1
        assert rows[0]["match_status"] == "UNMATCHED"

    def test_a_parsed_file_with_no_matched_rows_cannot_be_reconciled(self, api):
        """PRD §3.5: "`exception_row_count` is `row_count` less
        `matched_row_count`."

        Design: Difficulty/boundary_precision_check/enrollment_file_row_count_boundary_at_zero_then_one
        """
        built = _file_with_no_rows(api)
        append_row(
            api,
            built["file"]["id"],
            "EF-9999",
            built["physician"]["npi"],
            row_action="ADD",
            claimed_capitation_cents=20000,
        )
        validate_success(
            api.set_enrollment_file_state(
                built["file"]["id"], state_payload("PARSED"), IPA_ADMIN_HEADERS
            ),
            200,
        )

        response = api.set_enrollment_file_state(
            built["file"]["id"], state_payload("RECONCILED"), IPA_ADMIN_HEADERS
        )
        validate_error(response, ERR_ENROLLMENT_FILE_EMPTY, 422)

        still_parsed = read_file(api, built["file"]["id"])
        assert still_parsed["status"] == "PARSED"
        assert still_parsed["exception_row_count"] == 1
        assert list_file_remittances(api, built["file"]["id"]) == []
