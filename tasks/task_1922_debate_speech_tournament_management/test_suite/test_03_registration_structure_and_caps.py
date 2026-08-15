"""Entry caps, structural uniqueness, cross-tournament integrity, pagination,
and the small registration-graph state checks."""
from test_helpers import (
    TEST_USERS,
    add_division,
    add_entry,
    add_judge,
    add_round,
    add_school,
    commit_judge,
    confirm_entry,
    create_division_payload,
    create_entry_payload,
    create_judge_conflict_payload,
    create_round_payload,
    create_tournament,
    get_entry,
    get_judge,
    get_school,
    make_coach_headers,
    open_registration,
    setup_registration_scenario,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_entry,
)

DIRECTOR = TEST_USERS["director_headers"]
TAB = TEST_USERS["tabstaff_headers"]


class TestPerSchoolEntryCap:
    def test_fourth_entry_allowed_at_cap(self, api):
        """PRD §3.2: "Both caps are enforced at creation against counts of
        non-`WITHDRAWN` entries: creation is allowed only while the school's
        current count in the division is strictly below `per_school_entry_cap`,
        otherwise `ERR_SCHOOL_ENTRY_CAP_EXCEEDED` (HTTP 409)".
        PRD §3.1: "The `per_school_entry_cap` (default 4, at least 1) limits how
        many non-withdrawn entries one school may hold in the division".

        Design: Difficulty/boundary_precision_check/per_school_entry_cap_boundary
        """
        ws = setup_registration_scenario(
            name="Districts EC",
            schools=({"key": "a", "name": "Alpha", "entries": {}, "judges": []},),
            confirm_schools=False, lock=False)
        school_id = ws["schools"]["a"]["id"]
        division_id = ws["divisions"]["d"]["id"]
        coach = make_coach_headers(school_id)

        for n in range(4):  # count 0..3 < cap 4 -> each create allowed
            resp = api.create_entry(
                create_entry_payload(school_id, division_id, f"E-{n + 1}"), coach)
            entry = validate_success(resp, 201)
            assert entry["status"] == "REGISTERED"

        resp = api.create_entry(
            create_entry_payload(school_id, division_id, "E-Five"), coach)
        validate_error(resp, "ERR_SCHOOL_ENTRY_CAP_EXCEEDED")

    def test_rejected_over_cap_entry_not_persisted(self, api):
        """PRD §3.2: "creation is allowed only while the school's current count in
        the division is strictly below `per_school_entry_cap`, otherwise
        `ERR_SCHOOL_ENTRY_CAP_EXCEEDED` (HTTP 409)".
        PRD §2.3: "Paginated list responses carry the fields `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Difficulty/boundary_precision_check/per_school_entry_cap_boundary
        """
        ws = setup_registration_scenario(
            name="Districts EC",
            schools=({"key": "a", "name": "Alpha", "entries": {}, "judges": []},),
            confirm_schools=False, lock=False)
        school_id = ws["schools"]["a"]["id"]
        division_id = ws["divisions"]["d"]["id"]
        coach = make_coach_headers(school_id)
        for n in range(4):
            validate_success(api.create_entry(
                create_entry_payload(school_id, division_id, f"E-{n + 1}"), coach),
                201)

        validate_error(
            api.create_entry(create_entry_payload(school_id, division_id, "E-Five"),
                             coach),
            "ERR_SCHOOL_ENTRY_CAP_EXCEEDED")

        _data, meta = validate_paginated(api.list_entries(
            DIRECTOR, params={"school_id": school_id, "division_id": division_id}))
        assert meta["total_count"] == 4, "the rejected create persisted nothing"


class TestDivisionGlobalCap:
    def test_division_global_cap_reached_rejected(self, api):
        """PRD §3.2: "and only while the division-wide count is strictly below
        `global_entry_cap`, otherwise `ERR_DIVISION_GLOBAL_CAP_REACHED`
        (HTTP 409)".

        Design: Corner/validations/division_global_cap_reached_rejected
        """
        tournament = create_tournament(name="GC")
        division = add_division(tournament["id"], global_entry_cap=2)
        alpha = add_school(tournament["id"], name="Alpha")
        beta = add_school(tournament["id"], name="Beta")
        gamma = add_school(tournament["id"], name="Gamma")
        open_registration(tournament["id"])
        add_entry(alpha["id"], division["id"], "A-One")
        add_entry(beta["id"], division["id"], "B-One")

        resp = api.create_entry(
            create_entry_payload(gamma["id"], division["id"], "C-One"),
            make_coach_headers(gamma["id"]))
        validate_error(resp, "ERR_DIVISION_GLOBAL_CAP_REACHED")

        _data, meta = validate_paginated(
            api.list_entries(DIRECTOR, params={"division_id": division["id"]}))
        assert meta["total_count"] == 2


class TestStructuralUniqueness:
    def test_event_code_type_mismatch_rejected(self, api):
        """PRD §3.1: "The `event_code` must belong to the family of its
        `event_type`: debate codes are `CX`, `LD`, and `PF`, while speech codes
        are `OO`, `EXT`, and `INF`; a code outside the family is rejected with
        `ERR_EVENT_CODE_TYPE_MISMATCH` (HTTP 422)."

        Design: Corner/validations/event_code_type_mismatch_rejected
        """
        tournament = create_tournament(name="EC")
        resp = api.create_division(
            create_division_payload(tournament["id"], event_type="DEBATE",
                                    event_code="OO"),
            DIRECTOR)
        validate_error(resp, "ERR_EVENT_CODE_TYPE_MISMATCH")

    def test_duplicate_round_number_rejected(self, api):
        """PRD §3.4: "`TabStaff` schedules rounds by supplying the `division_id`,
        a `round_number` (at least 1, unique within its division — a duplicate
        yields `ERR_ROUND_NUMBER_EXISTS`, HTTP 409)".

        Design: Corner/validations/duplicate_round_number_rejected
        """
        tournament = create_tournament(name="RN")
        division = add_division(tournament["id"])
        add_round(division["id"], 1, kind="PRELIM")
        resp = api.create_round(
            create_round_payload(division["id"], round_number=1, kind="PRELIM",
                                 starts_at="2026-08-12T16:00:00Z",
                                 ends_at="2026-08-12T17:30:00Z"),
            TAB)
        validate_error(resp, "ERR_ROUND_NUMBER_EXISTS")


class TestCrossTournamentIntegrity:
    def test_cross_tournament_entry_reference_rejected(self, api):
        """PRD §2.8: "Every entity referenced by an operation — school, division,
        entry, judge, room, round, pairing, contract, or logistics order — must
        belong to the same tournament as the operation's context. A request that
        mixes references across two tournaments is rejected with
        `ERR_CROSS_TOURNAMENT_REFERENCE` (HTTP 409)."

        Design: Corner/validations/cross_tournament_entry_reference_rejected
        """
        t1 = create_tournament(name="T1")
        t2 = create_tournament(name="T2")
        d2 = add_division(t2["id"])
        alpha = add_school(t1["id"], name="Alpha")
        open_registration(t1["id"])
        open_registration(t2["id"])

        resp = api.create_entry(
            create_entry_payload(alpha["id"], d2["id"], "A-One"),
            make_coach_headers(alpha["id"]))
        validate_error(resp, "ERR_CROSS_TOURNAMENT_REFERENCE")


class TestPaginationEnvelope:
    def test_entries_limit_offset_envelope(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return: it defaults to 10 when omitted, with a minimum of 1 and a
        maximum of 100. The `offset` parameter specifies how many items to skip
        and defaults to 0."
        PRD §2.3: "Paginated list responses carry the fields `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Corner/endpoints/pagination_limit_offset_envelope
        """
        ws = setup_registration_scenario(
            name="PG",
            schools=({"key": "a", "name": "Alpha", "entries": {"d": 3},
                      "judges": []},),
            confirm_schools=False, lock=False)
        school_id = ws["schools"]["a"]["id"]

        page1_resp = api.list_entries(
            DIRECTOR, params={"school_id": school_id, "limit": 2})
        page1, meta1 = validate_paginated(page1_resp)
        assert page1_resp.json()["response_type"] == "array"
        assert page1_resp.json()["meta"].get("api_request_id"), (
            "meta carries api_request_id")
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_entries(
            DIRECTOR, params={"school_id": school_id, "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestSmallStateChecks:
    def test_entry_reconfirm_cycle_restores_invoice(self, api):
        """PRD §3.2: "a withdrawn entry may be re-confirmed on the same path
        (`WITHDRAWN` → `CONFIRMED`, a pre-lock-only cycle in which the fee is
        charged again)".
        PRD §3.2: "The recorded fee is an audit trail on the entry; the school's
        invoice includes it only while the entry's status is non-`WITHDRAWN`."

        Design: Corner/state_machines/entry_reconfirm_cycle_restores_invoice
        """
        ws = setup_registration_scenario(
            name="RC", entry_fee_cents=2500,
            schools=({"key": "a", "name": "Alpha", "entries": {"d": 1},
                      "judges": []},),
            confirm_schools=False, lock=False)
        school_id = ws["schools"]["a"]["id"]
        entry = ws["entries"]["a"][0]

        withdraw_entry(entry["id"], school_id)
        confirm_entry(entry["id"], school_id)

        fetched = get_entry(entry["id"])
        assert fetched["status"] == "CONFIRMED", "re-confirm cycle completed"
        school = get_school(school_id)
        assert school["invoice_balance_cents"] == 2500, (
            "exactly one active fee after confirm -> withdraw -> confirm")
        assert school["confirmed_entry_count"] == 1

    def test_withdraw_registered_entry_rejected(self, api):
        """PRD §3.2: "Withdrawing an entry (`CONFIRMED` → `WITHDRAWN`) is possible
        only before the lock, because it is a registration-graph write gated on
        `REGISTRATION_OPEN`; from any other entry state it yields
        `ERR_ENTRY_INVALID_STATE`."

        Design: Corner/state_machines/withdraw_registered_entry_rejected
        """
        ws = setup_registration_scenario(
            name="WR",
            schools=({"key": "a", "name": "Alpha", "entries": {}, "judges": []},),
            confirm_schools=False, lock=False)
        school_id = ws["schools"]["a"]["id"]
        entry = add_entry(school_id, ws["divisions"]["d"]["id"], "A-One")

        resp = api.withdraw_entry(entry["id"], make_coach_headers(school_id))
        validate_error(resp, "ERR_ENTRY_INVALID_STATE")
        assert get_entry(entry["id"])["status"] == "REGISTERED"

    def test_school_unconfirm_registered_rejected(self, api):
        """PRD §3.2: "Unconfirming reverses it to `REGISTERED` under the same
        phase gate."
        PRD §2.7: "Seventh, entity-state preconditions and aggregate gates are
        evaluated: the per-entity state errors `ERR_SCHOOL_INVALID_STATE`".

        Design: Corner/state_machines/school_unconfirm_registered_rejected
        """
        ws = setup_registration_scenario(
            name="SU",
            schools=({"key": "a", "name": "Alpha", "entries": {}, "judges": []},),
            confirm_schools=False, lock=False)
        school_id = ws["schools"]["a"]["id"]
        resp = api.unconfirm_school(school_id, make_coach_headers(school_id))
        validate_error(resp, "ERR_SCHOOL_INVALID_STATE")
        assert get_school(school_id)["status"] == "REGISTERED"

    def test_commit_committed_judge_rejected(self, api):
        """PRD §3.2: "the judge must currently be `REGISTERED` (otherwise
        `ERR_JUDGE_INVALID_STATE`)".

        Design: Corner/state_machines/commit_committed_judge_rejected
        """
        ws = setup_registration_scenario(
            name="CJ",
            schools=({"key": "a", "name": "Alpha", "entries": {}, "judges": []},),
            confirm_schools=False, lock=False)
        school_id = ws["schools"]["a"]["id"]
        judge = add_judge(ws["t"]["id"], school_id, "J-Alpha")
        commit_judge(judge["id"], school_id, 2)

        resp = api.commit_judge(judge["id"], 2, make_coach_headers(school_id))
        validate_error(resp, "ERR_JUDGE_INVALID_STATE")
        fetched = get_judge(judge["id"])
        assert fetched["status"] == "COMMITTED"
        assert fetched["commitment_rounds"] == 2, "no idempotent replay"

    def test_commitment_rounds_out_of_range_rejected(self, api):
        """PRD §3.2: "the supplied `commitment_rounds` must be between 1 and the
        tournament's `prelim_round_count` inclusive (otherwise
        `ERR_COMMITMENT_ROUNDS_INVALID`, HTTP 422)".
        PRD §3.1: "`prelim_round_count` (default 4, an integer between 2 and 6
        inclusive)".

        Design: Corner/state_machines/commitment_rounds_zero_rejected
        """
        ws = setup_registration_scenario(
            name="CR",
            schools=({"key": "a", "name": "Alpha", "entries": {}, "judges": []},),
            confirm_schools=False, lock=False)
        school_id = ws["schools"]["a"]["id"]
        judge = add_judge(ws["t"]["id"], school_id, "J-Alpha")
        coach = make_coach_headers(school_id)

        # Default prelim_round_count is 4: 0 is below the range, 5 above it.
        resp_zero = api.commit_judge(judge["id"], 0, coach)
        validate_error(resp_zero, "ERR_COMMITMENT_ROUNDS_INVALID")
        resp_high = api.commit_judge(judge["id"], 5, coach)
        validate_error(resp_high, "ERR_COMMITMENT_ROUNDS_INVALID")
        assert get_judge(judge["id"])["status"] == "REGISTERED"


class TestLightResourceFields:
    def test_judge_conflict_carries_only_id_and_created_at(self, api):
        """PRD §2.4: "A `JudgeConflict` record and a `PairingEntry` record carry
        only `id` and `created_at`; both `updated_at` and `version` are absent on
        these two resources."

        Design: Corner/entities/judge_conflict_immutable_common_fields
        """
        ws = setup_registration_scenario(
            name="IC",
            schools=({"key": "a", "name": "Alpha", "entries": {}, "judges": []},),
            confirm_schools=False, lock=False)
        school_id = ws["schools"]["a"]["id"]
        judge = add_judge(ws["t"]["id"], school_id, "J-Alpha")

        created = validate_success(api.create_judge_conflict(
            create_judge_conflict_payload(judge["id"], school_id, reason="alum"),
            make_coach_headers(school_id)), 201)
        assert created["id"] and created["created_at"]

        fetched = validate_success(api.get_judge_conflict(created["id"], DIRECTOR))
        assert "version" not in fetched, "JudgeConflict carries no version field"
        assert "updated_at" not in fetched, (
            "JudgeConflict carries no updated_at field")
