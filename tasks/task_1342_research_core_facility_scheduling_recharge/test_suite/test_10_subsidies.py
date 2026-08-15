"""Subsidy waterfall ordering, award offset reversal, and award-shape
eligibility (PRD §2.10, §3.8, §3.9, §3.10)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    TEST_USERS, create_subsidy_application_payload, create_award_approval_payload,
    make_researcher_headers,
    setup_canonical_stack, create_user, create_approved_booking, open_batch,
    finalize_batch, run_session_to_completed, create_and_validate_usage_log,
    create_subsidy_award, get_award, get_grant, find_entries,
    find_entry_for_usage_log,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
STAFF2 = TEST_USERS["staff2_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestWaterfallOrder:
    def _setup(self, api):
        """u1 holds awA (5000, valid_until 2026-10-01) and awB (20000,
        valid_until 2026-12-01); a 90-actual-minute session charges 18000."""
        stack = setup_canonical_stack()
        u1 = stack["u1"]
        awA = create_subsidy_award(
            u1, kind="SUBSIDY", requested_amount_cents=5000,
            awarded_amount_cents=5000, valid_from="2026-08-01T00:00:00Z",
            valid_until="2026-10-01T00:00:00Z",
        )
        awB = create_subsidy_award(
            u1, kind="SUBSIDY", requested_amount_cents=20000,
            awarded_amount_cents=20000, valid_from="2026-08-01T00:00:00Z",
            valid_until="2026-12-01T00:00:00Z",
        )
        b1 = create_approved_booking(stack)
        open_batch(2026, 9)
        completed = run_session_to_completed(
            b1, "2026-09-01T09:00:00Z", "2026-09-01T10:30:00Z"
        )
        log = create_and_validate_usage_log(
            completed, "2026-09-01T09:00:00Z", "2026-09-01T10:30:00Z"
        )
        entry = find_entry_for_usage_log(log["id"])
        return stack, awA, awB, entry

    def test_entry_fully_offset_by_waterfall(self, api):
        """PRD §3.8: "Starting with the full `amount_cents` as the
        remaining-to-cover, each award in turn contributes the smaller of its
        own `remaining_amount_cents` and the remaining-to-cover; the award's
        balance decrements and the remainder shrinks." and "The entry's
        `subsidy_offset_cents` is the total drawn; its `net_amount_cents` is
        what remains."

        Design: Difficulty/combinatorial_formula/subsidy_waterfall_evaluation_order
        """
        stack, awA, awB, entry = self._setup(api)
        assert entry["amount_cents"] == 18000, "90 billable min x 200"
        assert entry["subsidy_offset_cents"] == 18000
        assert entry["net_amount_cents"] == 0
        grant = get_grant(stack["g1"]["id"])
        assert grant["budget_used_cents"] == 0, "fully subsidized: net 0 debited"

    def test_earlier_valid_until_drains_first(self, api):
        """PRD §3.8: "Candidates are consumed in ascending `valid_until` order,
        ties broken by ascending `created_at`." and "When an award's take
        exactly empties it, the award becomes `EXHAUSTED` and the next award
        continues the same entry."

        Design: Difficulty/combinatorial_formula/subsidy_waterfall_evaluation_order
        """
        stack, awA, awB, entry = self._setup(api)
        award_a = get_award(awA["id"])
        assert award_a["remaining_amount_cents"] == 0
        assert award_a["status"] == "EXHAUSTED", (
            "the award with the earlier valid_until (2026-10-01) drains first"
        )
        award_b = get_award(awB["id"])
        assert award_b["remaining_amount_cents"] == 7000, "20000 - 13000"
        assert award_b["status"] == "ACTIVE"


class TestOffsetReversalConservation:
    def _setup(self, api):
        """u1 holds a single award of exactly 18000; the 18000-cent session
        charge is fully offset; the entry is billed, disputed, and batch
        2026-10 is open."""
        stack = setup_canonical_stack()
        aw1 = create_subsidy_award(
            stack["u1"], kind="SUBSIDY", requested_amount_cents=18000,
            awarded_amount_cents=18000, valid_from="2026-08-01T00:00:00Z",
            valid_until="2026-12-01T00:00:00Z",
        )
        b1 = create_approved_booking(stack)
        bat9 = open_batch(2026, 9)
        completed = run_session_to_completed(
            b1, "2026-09-01T09:00:00Z", "2026-09-01T10:30:00Z"
        )
        log = create_and_validate_usage_log(
            completed, "2026-09-01T09:00:00Z", "2026-09-01T10:30:00Z"
        )
        entry = find_entry_for_usage_log(log["id"])
        finalize_batch(bat9["id"])
        validate_success(
            api.dispute_recharge_entry(
                entry["id"], {"dispute_reason": "session aborted early"},
                make_researcher_headers(stack["u1"]["id"]),
            ),
            200,
        )
        open_batch(2026, 10)
        return stack, aw1, entry

    def test_exhaustion_then_reversal_restores_active(self, api):
        """PRD §3.10: "When the waterfall drains an award to zero it becomes
        `EXHAUSTED`". PRD §3.9: "The subsidy is reversed too: the award that
        funded the original offset regains `original.subsidy_offset_cents` on
        its `remaining_amount_cents`, and an award may thereby recover from
        `EXHAUSTED` to `ACTIVE` unless it is `EXPIRED` or `REVOKED`."

        Design: Difficulty/compensating_invariant/subsidy_award_offset_reversal_conservation
        """
        stack, aw1, entry = self._setup(api)
        mid = get_award(aw1["id"])
        assert mid["remaining_amount_cents"] == 0
        assert mid["status"] == "EXHAUSTED", "the 18000 offset fully consumed it"

        validate_success(
            api.resolve_recharge_entry_dispute(
                entry["id"], {"resolution": "WRITE_OFF"}, FINANCE
            ),
            200,
        )
        post = get_award(aw1["id"])
        assert post["remaining_amount_cents"] == 18000, "offset fully restored"
        assert post["status"] == "ACTIVE", "EXHAUSTED -> ACTIVE on reversal"

    def test_entry_fields_and_untouched_grant(self, api):
        """PRD §3.9: "`WRITE_OFF` moves the entry to `WRITTEN_OFF`". PRD §3.8:
        "The entry's `subsidy_offset_cents` is the total drawn; its
        `net_amount_cents` is what remains." PRD §2.10: "`budget_used_cents` is
        the sum of `net_amount_cents` over the grant's recharge entries of kind
        `USAGE` or `PENALTY` whose status is `PENDING`, `BILLED`, `PAID`, or
        `DISPUTED`".

        Design: Difficulty/compensating_invariant/subsidy_award_offset_reversal_conservation
        """
        stack, aw1, entry = self._setup(api)
        grant_mid = get_grant(stack["g1"]["id"])
        assert grant_mid["budget_used_cents"] == 0, "net 0 was debited"
        validate_success(
            api.resolve_recharge_entry_dispute(
                entry["id"], {"resolution": "WRITE_OFF"}, FINANCE
            ),
            200,
        )
        entry_after = validate_success(
            api.get_recharge_entry(entry["id"], FINANCE), 200
        )
        assert entry_after["status"] == "WRITTEN_OFF"
        assert entry_after["subsidy_offset_cents"] == 18000
        assert entry_after["net_amount_cents"] == 0
        grant_post = get_grant(stack["g1"]["id"])
        assert grant_post["budget_used_cents"] == 0
        award_post = get_award(aw1["id"])
        assert award_post["awarded_amount_cents"] == 18000
        assert award_post["remaining_amount_cents"] == 18000, (
            "awarded == remaining + sum of non-reversed offsets (0)"
        )


class TestAwardShapeEligibility:
    def test_subsidy_ineligible_award_shapes(self, api):
        """PRD §3.10: "The award may not exceed the request —
        `awarded_amount_cents` must be strictly positive and at most
        `requested_amount_cents` — and `conveys_priority` true is permitted
        only for `STARTUP` applications; either violation is
        `ERR_SUBSIDY_INELIGIBLE`."

        Design: Corner/validations/subsidy_ineligible_award_shapes
        """
        u1 = create_user(is_pi=True)
        owner = make_researcher_headers(u1["id"])
        app_ids = []
        for amount, justification in ((5000, "pilot"), (9000, "second")):
            application = validate_success(
                api.create_subsidy_application(
                    create_subsidy_application_payload(
                        u1["id"], requested_amount_cents=amount,
                        justification=justification,
                    ),
                    owner,
                ),
                201,
            )
            validate_success(
                api.submit_subsidy_application(application["id"], owner), 200
            )
            validate_success(
                api.review_subsidy_application(application["id"], FINANCE), 200
            )
            app_ids.append(application["id"])

        over_award = api.approve_subsidy_application(
            app_ids[0],
            create_award_approval_payload(awarded_amount_cents=6000),
            FINANCE,
        )
        validate_error(over_award, "ERR_SUBSIDY_INELIGIBLE", expected_status=422)

        priority_on_subsidy = api.approve_subsidy_application(
            app_ids[1],
            create_award_approval_payload(
                awarded_amount_cents=9000, conveys_priority=True
            ),
            FINANCE,
        )
        validate_error(
            priority_on_subsidy, "ERR_SUBSIDY_INELIGIBLE", expected_status=422
        )

        for app_id in app_ids:
            application = validate_success(
                api.get_subsidy_application(app_id, FINANCE), 200
            )
            assert application["status"] == "UNDER_REVIEW"
        assert validate_success(api.list_subsidy_awards(FINANCE), 200) == [], (
            "no award may be minted by a rejected approval"
        )
