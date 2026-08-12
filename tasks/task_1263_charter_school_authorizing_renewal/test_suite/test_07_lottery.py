"""Lottery operations: seal boundary, seat conservation, school-state gate,
and zero-capacity execution (PRD §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_approved_school, create_open_school, create_draft_contract,
    add_standard_targets, create_lottery, create_open_lottery, add_lottery_entry,
    assert_lottery_seat_partition,
    make_staff_headers, make_school_operator_headers, api_client,
)

STAFF = make_staff_headers("staff_1")


def _seal_boundary_context():
    """Open school + OPEN lottery with one auto-VERIFIED entry and one PENDING
    (SIBLING) entry."""
    ctx = create_open_school(school_name="BP Seal Academy", applicant_id="applicant_bp2")
    lottery = create_open_lottery(ctx["school"]["id"], academic_year=2028, capacity=10)
    add_lottery_entry(lottery["id"], ctx["school"]["id"],
                      student_ref="stu_bp2_plain", preference_codes=[])
    pending = add_lottery_entry(lottery["id"], ctx["school"]["id"],
                                student_ref="stu_bp2_sib", preference_codes=["SIBLING"])
    return ctx, lottery, pending


class TestSealRequiresZeroPendingEntries:
    def test_one_pending_entry_blocks_seal(self, api):
        """PRD §3.4: "Sealing the lottery (`OPEN` → `SEALED`) freezes the pool
        and demands that every preference claim be resolved: a single `PENDING`
        entry blocks the seal with `ERR_UNVERIFIED_PREFERENCE_ENTRIES` — zero
        is the only acceptable count — and a lottery not `OPEN` draws
        `ERR_LOTTERY_INVALID_STATE`."

        Design: Difficulty/boundary_precision_check/seal_requires_zero_pending_entries
        """
        _ctx, lottery, pending = _seal_boundary_context()
        assert pending["preference_status"] == "PENDING"
        res = api.seal_lottery(lottery["id"], STAFF)
        validate_error(res, ApiErrorId.ERR_UNVERIFIED_PREFERENCE_ENTRIES,
                       expected_status=409)
        current = validate_success(api.get_lottery(lottery["id"], STAFF), 200)
        assert current["status"] == "OPEN"

    def test_rejecting_pending_entry_unblocks_seal(self, api):
        """PRD §3.4: "Staff adjudicate a `PENDING` claim by passing an `outcome`
        of `VERIFIED` or `REJECTED`; adjudicating an entry whose preference
        claim is not `PENDING` is rejected with `ERR_ENTRY_INVALID_STATE`, and
        the adjudicator is stamped as `preference_verified_by`."

        Design: Difficulty/boundary_precision_check/seal_requires_zero_pending_entries
        """
        _ctx, lottery, pending = _seal_boundary_context()
        adjudicated = validate_success(
            api.verify_preference(pending["id"], {"outcome": "REJECTED"},
                                  make_staff_headers("staff_verify_1")), 200)
        assert adjudicated["preference_status"] == "REJECTED"
        assert adjudicated["preference_verified_by"] == "staff_verify_1"
        sealed = validate_success(api.seal_lottery(lottery["id"], STAFF), 200)
        assert sealed["status"] == "SEALED"


def _executed_lottery_context():
    """Open school + EXECUTED lottery (capacity 2) with three entries:
    stu_b2 VERIFIED preference (weight 10), stu_a1 / stu_c3 no preferences."""
    ctx = create_open_school(school_name="CI Lottery Academy", applicant_id="applicant_ci1")
    lottery = create_open_lottery(ctx["school"]["id"], academic_year=2028, capacity=2)
    e1 = add_lottery_entry(lottery["id"], ctx["school"]["id"],
                           student_ref="stu_a1", preference_codes=[])
    e2 = add_lottery_entry(lottery["id"], ctx["school"]["id"],
                           student_ref="stu_b2", preference_codes=["SIBLING"])
    e3 = add_lottery_entry(lottery["id"], ctx["school"]["id"],
                           student_ref="stu_c3", preference_codes=[])
    validate_success(api_client.verify_preference(e2["id"], {"outcome": "VERIFIED"}, STAFF), 200)
    validate_success(api_client.seal_lottery(lottery["id"], STAFF), 200)
    executed = validate_success(api_client.execute_lottery(lottery["id"], STAFF), 200)
    return ctx, lottery, executed, {"stu_a1": e1, "stu_b2": e2, "stu_c3": e3}


class TestLotterySeatConservationUnderDecline:
    def test_execute_ranks_by_preference_weight_then_recency_then_ref(self, api):
        """PRD §3.4: "Entries are ordered by preference weight descending, then
        by `created_at` ascending, then by `student_ref` ascending — ties are
        never broken by `id` — and `rank_position` is assigned 1 through N in
        that order. Entries whose rank is at most `capacity` become `OFFERED`;
        ranks beyond capacity become `WAITLISTED`; and a lottery with zero
        capacity waitlists every entry."

        Design: Difficulty/compensating_invariant/lottery_seat_conservation_under_decline
        """
        ctx, lottery, executed, entries = _executed_lottery_context()
        assert executed["status"] == "EXECUTED"
        listed = validate_success(api.list_lottery_entries(lottery["id"], STAFF), 200)
        by_ref = {e["student_ref"]: e for e in listed}
        assert by_ref["stu_b2"]["rank_position"] == 1
        assert by_ref["stu_b2"]["outcome"] == "OFFERED"
        assert by_ref["stu_a1"]["rank_position"] == 2
        assert by_ref["stu_a1"]["outcome"] == "OFFERED"
        assert by_ref["stu_c3"]["rank_position"] == 3
        assert by_ref["stu_c3"]["outcome"] == "WAITLISTED"
        partition = assert_lottery_seat_partition(listed, capacity=2)
        assert partition == {"offered": 2, "waitlisted": 1, "declined": 0}

    def test_decline_promotes_smallest_waitlisted_rank_and_conserves_seats(self, api):
        """PRD §3.4: "When the owning `SchoolOperator` declines an offered seat
        — the entry must be `OFFERED`, else `ERR_ENTRY_INVALID_STATE`, and
        ownership is checked per §2.1 — the entry becomes `DECLINED` and, if
        any `WAITLISTED` entries remain, the one with the smallest
        `rank_position` is promoted to `OFFERED`, leaving the offered count
        unchanged."

        Design: Difficulty/compensating_invariant/lottery_seat_conservation_under_decline
        """
        ctx, lottery, _executed, entries = _executed_lottery_context()
        declined = validate_success(
            api.decline_entry(entries["stu_b2"]["id"],
                              make_school_operator_headers(ctx["school"]["id"])), 200)
        assert declined["outcome"] == "DECLINED"
        listed = validate_success(api.list_lottery_entries(lottery["id"], STAFF), 200)
        by_ref = {e["student_ref"]: e for e in listed}
        assert by_ref["stu_c3"]["outcome"] == "OFFERED"   # promoted from rank 3
        assert by_ref["stu_a1"]["outcome"] == "OFFERED"
        partition = assert_lottery_seat_partition(listed, capacity=2)
        assert partition == {"offered": 2, "waitlisted": 0, "declined": 1}


class TestLotteryOpenRequiresSchoolOpen:
    def test_open_while_pre_opening_rejected(self, api):
        """PRD §3.4: "Opening it moves `DRAFT` → `OPEN` and additionally
        requires the school to be `OPEN` — a lottery drafted during pre-opening
        waits for the first contract activation — with `ERR_SCHOOL_NOT_OPEN`
        for a school not open and `ERR_LOTTERY_INVALID_STATE` for a lottery not
        in `DRAFT`."

        Design: Difficulty/cross_entity_state_dependency/lottery_open_requires_school_open
        """
        _app, school = create_approved_school(school_name="CE Lottery Academy",
                                              applicant_id="applicant_ce1")
        assert school["status"] == "PRE_OPENING"
        lottery = create_lottery(school["id"], academic_year=2028, capacity=20)
        res = api.open_lottery(lottery["id"], STAFF)
        validate_error(res, ApiErrorId.ERR_SCHOOL_NOT_OPEN, expected_status=409)
        current = validate_success(api.get_lottery(lottery["id"], STAFF), 200)
        assert current["status"] == "DRAFT"

    def test_open_after_first_contract_activation_succeeds(self, api):
        """PRD §3.2: "Activation then cascades: any other `ACTIVE` contract for
        the same school is superseded (`ACTIVE` → `SUPERSEDED`), the school's
        `current_contract_id` is pointed at the newly active contract, and a
        `PRE_OPENING` school opens its doors (`PRE_OPENING` → `OPEN`)."

        Design: Difficulty/cross_entity_state_dependency/lottery_open_requires_school_open
        """
        _app, school = create_approved_school(school_name="CE Lottery Academy",
                                              applicant_id="applicant_ce1")
        lottery = create_lottery(school["id"], academic_year=2028, capacity=20)
        school_now = validate_success(api.get_school(school["id"], STAFF), 200)
        contract = create_draft_contract(school["id"], school_now["version"])
        add_standard_targets(contract["id"])
        validate_success(api.activate_contract(contract["id"], STAFF), 200)
        opened = validate_success(api.open_lottery(lottery["id"], STAFF), 200)
        assert opened["status"] == "OPEN"


class TestLotteryZeroCapacity:
    def test_zero_capacity_waitlists_every_entry(self, api):
        """PRD §3.4: "Entries whose rank is at most `capacity` become
        `OFFERED`; ranks beyond capacity become `WAITLISTED`; and a lottery
        with zero capacity waitlists every entry."

        Design: Corner/calculations/calc_lottery_zero_capacity_all_waitlisted
        """
        ctx = create_open_school(school_name="Calc ZeroCap Academy",
                                 applicant_id="applicant_c2")
        lottery = create_open_lottery(ctx["school"]["id"], academic_year=2028, capacity=0)
        add_lottery_entry(lottery["id"], ctx["school"]["id"],
                          student_ref="stu_z1", preference_codes=[])
        add_lottery_entry(lottery["id"], ctx["school"]["id"],
                          student_ref="stu_z2", preference_codes=[])
        validate_success(api.seal_lottery(lottery["id"], STAFF), 200)
        executed = validate_success(api.execute_lottery(lottery["id"], STAFF), 200)
        assert executed["status"] == "EXECUTED"
        listed = validate_success(api.list_lottery_entries(lottery["id"], STAFF), 200)
        by_ref = {e["student_ref"]: e for e in listed}
        assert by_ref["stu_z1"]["outcome"] == "WAITLISTED"
        assert by_ref["stu_z1"]["rank_position"] == 1
        assert by_ref["stu_z2"]["outcome"] == "WAITLISTED"
        assert by_ref["stu_z2"]["rank_position"] == 2
        partition = assert_lottery_seat_partition(listed, capacity=0)
        assert partition["offered"] == 0
