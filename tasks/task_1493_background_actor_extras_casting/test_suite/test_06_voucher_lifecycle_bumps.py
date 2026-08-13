"""Voucher lifecycle (issue/dispute/adjust), bump decisions under SoD, OCC."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_batch_item,
    create_batch,
    create_bump,
    get_voucher_for_booking,
    make_actor_headers,
    make_associate_headers,
    make_director_headers,
    setup_issued_voucher,
    setup_shooting_booking,
    setup_wrapped_day,
    submit_batch,
    validate_error,
    validate_success,
)

ASSOC = TEST_USERS["associate_headers"]

# Canonical wrapped day used by the revision loop: NONUNION rate 10000,
# duration 600, timely meal 12:00-12:30, wrap 16:00 -> net 510, gross 10938.
DAY = {
    "meals": [("2026-08-10T12:00:00Z", "2026-08-10T12:30:00Z")],
    "wrap_at": "2026-08-10T16:00:00Z",
}


class TestIssueGuards:
    def test_voucher_issue_before_wrap_rejected(self, api, associate_headers):
        """PRD §3.6: "it requires the voucher `DRAFT` (`ERR_VOUCHER_INVALID_STATE`)
        and the booking `WRAPPED` (`ERR_BOOKING_NOT_WRAPPED`)"

        Design: Corner/errors/voucher_issue_before_wrap_rejected
        """
        prod, call, actor, booking = setup_shooting_booking(
            check_in=True, check_in_at="2026-08-10T07:00:00Z"
        )
        voucher = get_voucher_for_booking(booking["id"])
        assert voucher["status"] == "DRAFT"
        res = api.issue_voucher(voucher["id"], associate_headers)
        validate_error(res, ApiErrorId.ERR_BOOKING_NOT_WRAPPED)
        voucher_after = validate_success(api.get_voucher(voucher["id"], associate_headers), 200)
        assert voucher_after["status"] == "DRAFT"

    def test_voucher_double_issue_rejected(self, api, associate_headers):
        """PRD §3.6: "it requires the voucher `DRAFT` (`ERR_VOUCHER_INVALID_STATE`)"

        Design: Corner/errors/voucher_double_issue_rejected
        """
        _p, _c, _a, _b, voucher = setup_issued_voucher(wrap_at="2026-08-10T12:00:00Z")
        assert voucher["status"] == "ISSUED"
        res = api.issue_voucher(voucher["id"], associate_headers)
        validate_error(res, ApiErrorId.ERR_VOUCHER_INVALID_STATE)


class TestDisputeAdjustLoop:
    def _dispute_and_approve(self, api):
        """Issued voucher (gross 10938) -> dispute by owner -> PENDING bump 2500
        approved mid-dispute. Returns (voucher_id, dispute_response_data, actor_id)."""
        prod, call, actor, booking, voucher = setup_issued_voucher(**DAY)
        assert voucher["gross_total_cents"] == 10938
        disputed = validate_success(
            api.dispute_voucher(
                voucher["id"],
                {"reason": "missing wardrobe bump"},
                make_actor_headers(actor["id"]),
            ),
            200,
        )
        bump = create_bump(voucher["id"], amount_cents=2500, requester="assoc-1")
        approved = validate_success(
            api.approve_bump(bump["id"], make_director_headers("dir-1")), 200
        )
        assert approved["status"] == "APPROVED"
        return voucher["id"], disputed, actor["id"]

    def test_voucher_dispute_adjust_revision_loop_gross(self, api):
        """PRD §3.6: "The associate's road is the adjustment, which recomputes the
        final gross over the current effective events and the current `APPROVED`
        bumps and re-issues the voucher: it is permitted from `ISSUED`,
        `DISPUTED`, or `REJECTED` (any other state fails with
        `ERR_VOUCHER_INVALID_STATE`)"

        Design: Difficulty/non_linear_state_machine/voucher_dispute_adjust_revision_loop
        """
        voucher_id, disputed, _actor_id = self._dispute_and_approve(api)
        adjusted = validate_success(
            api.adjust_voucher(
                voucher_id,
                {"expected_voucher_version": disputed["version"]},
                make_associate_headers("assoc-2"),
            ),
            200,
        )
        assert adjusted["status"] == "ISSUED"
        assert adjusted["gross_total_cents"] == 13438  # 10938 + 2500 approved bump
        assert adjusted["bumps_total_cents"] == 2500

    def test_voucher_dispute_adjust_revision_loop_states(self, api):
        """PRD §3.6: "A dispute moves the voucher to `DISPUTED`" and the
        adjustment "returns the voucher to `ISSUED`, and increments its `version`
        by exactly one."
        PRD §3.6: "The performer themselves may dispute an `ISSUED` voucher — the
        caller must own the underlying booking (`ERR_FORBIDDEN_OWNERSHIP`)".

        Design: Difficulty/non_linear_state_machine/voucher_dispute_adjust_revision_loop
        """
        voucher_id, disputed, _actor_id = self._dispute_and_approve(api)
        assert disputed["status"] == "DISPUTED"
        adjusted = validate_success(
            api.adjust_voucher(
                voucher_id,
                {"expected_voucher_version": disputed["version"]},
                make_associate_headers("assoc-2"),
            ),
            200,
        )
        assert adjusted["status"] == "ISSUED"
        assert adjusted["version"] == disputed["version"] + 1
        assert adjusted["adjusted_by_user_id"] == "assoc-2"


class TestBumpDecisions:
    def test_sod_bump_self_approval_rejected(self, api, director_headers):
        """PRD §3.7: "both approval and rejection compare the decider's
        `X-User-ID` against `requested_by_user_id` and refuse self-adjudication
        with `ERR_SOD_SELF_APPROVAL`"
        PRD §3.7: "Approval additionally re-checks the voucher lock — approving
        against a `SUBMITTED` or `PAID` voucher fails with
        `ERR_BUMP_VOUCHER_LOCKED` — and stamps `decided_by_user_id`."

        Design: Corner/rbac/sod_bump_self_approval_rejected
        """
        _p, _c, _a, _b, voucher = setup_wrapped_day(wrap_at="2026-08-10T12:00:00Z")
        bump = create_bump(
            voucher["id"], amount_cents=1800, requester="assoc-1", category="PROPS_OWN"
        )
        assert bump["status"] == "PENDING"
        assert bump["requested_by_user_id"] == "assoc-1"

        # Same operator id that requested the bump cannot approve it, even with
        # the director role.
        res = api.approve_bump(bump["id"], make_director_headers("assoc-1"))
        validate_error(res, ApiErrorId.ERR_SOD_SELF_APPROVAL)
        bump_after = validate_success(
            api.get_bump_adjustment(bump["id"], director_headers), 200
        )
        assert bump_after["status"] == "PENDING"

        approved = validate_success(
            api.approve_bump(bump["id"], make_director_headers("dir-1")), 200
        )
        assert approved["status"] == "APPROVED"
        assert approved["decided_by_user_id"] == "dir-1"

    def test_bump_double_approve_rejected(self, api, director_headers):
        """PRD §3.7: "both approval and rejection compare the decider's
        `X-User-ID` against `requested_by_user_id` and refuse self-adjudication
        with `ERR_SOD_SELF_APPROVAL`, and both require the adjustment still
        `PENDING` (`ERR_BUMP_INVALID_STATE` otherwise)."

        Design: Corner/errors/bump_double_approve_rejected
        """
        _p, _c, _a, _b, voucher = setup_wrapped_day(wrap_at="2026-08-10T12:00:00Z")
        bump = create_bump(
            voucher["id"], amount_cents=900, requester="assoc-1", category="HAIR_MAKEUP"
        )
        validate_success(api.approve_bump(bump["id"], make_director_headers("dir-1")), 200)
        res = api.approve_bump(bump["id"], make_director_headers("dir-2"))
        validate_error(res, ApiErrorId.ERR_BUMP_INVALID_STATE)


class TestBumpVoucherLock:
    def test_bump_approve_blocked_when_voucher_submitted(self, api, director_headers):
        """PRD §3.7: "Approval additionally re-checks the voucher lock —
        approving against a `SUBMITTED` or `PAID` voucher fails with
        `ERR_BUMP_VOUCHER_LOCKED`"

        Design: Difficulty/cross_entity_state_dependency/bump_approve_blocked_when_voucher_submitted
        """
        voucher_id, bump_id = self._submitted_voucher_with_pending_bump(api)
        res = api.approve_bump(bump_id, make_director_headers("dir-1"))
        validate_error(res, ApiErrorId.ERR_BUMP_VOUCHER_LOCKED)
        bump_after = validate_success(
            api.get_bump_adjustment(bump_id, director_headers), 200
        )
        assert bump_after["status"] == "PENDING"

    def test_bump_blocked_leaves_batch_and_voucher_unchanged(
        self, api, director_headers, payroll_headers
    ):
        """PRD §3.7: "Approval additionally re-checks the voucher lock —
        approving against a `SUBMITTED` or `PAID` voucher fails with
        `ERR_BUMP_VOUCHER_LOCKED`" — the rejected approval performs no voucher or
        batch recomputation.


        Design: Difficulty/cross_entity_state_dependency/bump_approve_blocked_when_voucher_submitted
        """
        voucher_id, bump_id, batch_id = self._submitted_voucher_with_pending_bump2(api)
        res = api.approve_bump(bump_id, make_director_headers("dir-1"))
        validate_error(res, ApiErrorId.ERR_BUMP_VOUCHER_LOCKED)
        assert res.status_code == 409

        voucher = validate_success(api.get_voucher(voucher_id, payroll_headers), 200)
        assert voucher["status"] == "SUBMITTED"
        assert voucher["gross_total_cents"] == 10938
        assert voucher["bumps_total_cents"] == 0
        batch = validate_success(api.get_payroll_batch(batch_id, payroll_headers), 200)
        assert batch["status"] == "SUBMITTED"
        assert batch["voucher_count"] == 1

    def _submitted_voucher_with_pending_bump(self, api):
        voucher_id, bump_id, _batch_id = self._submitted_voucher_with_pending_bump2(api)
        return voucher_id, bump_id

    def _submitted_voucher_with_pending_bump2(self, api):
        """Issued voucher with a PENDING bump, then batch -> add -> submit so the
        voucher rides a SUBMITTED batch. Returns (voucher_id, bump_id, batch_id)."""
        prod, _c, actor, booking, voucher = setup_issued_voucher(**DAY)
        bump = create_bump(voucher["id"], amount_cents=1500, requester="assoc-1")
        batch = create_batch(prod["id"], creator="pc-1")
        add_batch_item(
            batch["id"], voucher["id"],
            expected_batch_version=batch["version"], operator="pc-1",
        )
        submit_batch(batch["id"], operator="pc-1")
        return voucher["id"], bump["id"], batch["id"]


class TestVoucherOCC:
    def test_occ_stale_voucher_version_rejected(self, api, associate_headers):
        """PRD §2.9: "Recomputing and re-issuing a voucher requires the request
        to carry `expected_voucher_version`, holding the voucher `version` the
        client last observed. A mismatch with the voucher's current `version` is
        rejected with `ERR_STALE_VOUCHER_VERSION` (HTTP 412), since the
        adjustment would otherwise be based on a computation the client never
        saw."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_voucher_version_rejected
        """
        _p, _c, _a, _b, voucher = setup_issued_voucher(wrap_at="2026-08-10T12:00:00Z")
        observed_version = voucher["version"]

        first = validate_success(
            api.adjust_voucher(
                voucher["id"],
                {"expected_voucher_version": observed_version},
                associate_headers,
            ),
            200,
        )
        assert first["status"] == "ISSUED"
        assert first["version"] > observed_version

        # Same stale version now fails.
        res = api.adjust_voucher(
            voucher["id"],
            {"expected_voucher_version": observed_version},
            associate_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VOUCHER_VERSION)
