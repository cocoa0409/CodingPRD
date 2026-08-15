"""Judge-obligation math, school confirm/lock aggregate gates, and the OCC rules."""
from test_helpers import (
    LOCK_DAY,
    TEST_USERS,
    add_division,
    add_entry,
    add_judge,
    add_school,
    commit_judge,
    confirm_entry,
    confirm_school,
    create_contract_payload,
    create_tournament,
    get_school,
    get_tournament,
    make_coach_headers,
    open_registration,
    set_clock,
    setup_registration_scenario,
    setup_school_with_shortfall,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = TEST_USERS["director_headers"]


def _mixed_division_scenario(api):
    """Alpha with 3 confirmed CX (debate) entries and 6 confirmed OO (speech)
    entries in a 4-prelim tournament; no judges. Obligation must read
    ceil(3/2)*4 + ceil(6/5)*4 = 16."""
    ws = setup_registration_scenario(
        name="Districts OB", prelim_round_count=4, entry_fee_cents=2500,
        divisions=(("cx", "DEBATE", "CX", "VARSITY", 8, None),
                   ("oo", "SPEECH", "OO", "VARSITY", 8, None)),
        schools=(
            {"key": "a", "name": "Alpha",
             "entries": {"cx": 3, "oo": 6}, "judges": []},
        ),
        confirm_schools=False, lock=False)
    return ws


class TestJudgeObligationFormula:
    def test_obligation_sums_per_division_ceil_times_rounds(self, api):
        """PRD §3.2: "A debate division demands one judge per two such entries,
        rounded up to a whole judge; a speech division demands one judge per five
        such entries, rounded up. Each division's judge count is multiplied by the
        tournament's `prelim_round_count`, and the products sum to the school's
        `judge_obligation_rounds`."

        Design: Difficulty/combinatorial_formula/judge_obligation_mixed_event_type_ceil
        """
        ws = _mixed_division_scenario(api)
        school = get_school(ws["schools"]["a"]["id"])
        assert school["confirmed_entry_count"] == 9
        # ceil(3/2)*4 = 8 debate rounds; ceil(6/5)*4 = 8 speech rounds; total 16.
        assert school["judge_obligation_rounds"] == 16, (
            "per-division conditional rate + ceil before the round multiplier")
        assert school["covered_judge_rounds"] == 0
        assert school["shortfall_rounds"] == 16
        assert school["obligation_status"] == "DEFICIENT"

    def test_judge_commit_recomputes_shortfall_immediately(self, api):
        """PRD §3.2: "The `shortfall_rounds` is the amount by which
        `judge_obligation_rounds` exceeds `covered_judge_rounds`, never below
        zero; `obligation_status` is `SATISFIED` exactly when the shortfall is
        zero and `DEFICIENT` otherwise."
        PRD §2.10: "Derived fields on a school — its obligation, coverage,
        shortfall, obligation posture, and invoice balance — are reconciled
        immediately whenever the underlying registration graph mutates".

        Design: Difficulty/combinatorial_formula/judge_obligation_mixed_event_type_ceil
        """
        ws = _mixed_division_scenario(api)
        school_id = ws["schools"]["a"]["id"]
        judge = add_judge(ws["t"]["id"], school_id, "J-Alpha")
        commit_judge(judge["id"], school_id, 4)

        school = get_school(school_id)
        assert school["judge_obligation_rounds"] == 16
        assert school["covered_judge_rounds"] == 4
        assert school["shortfall_rounds"] == 12, "16 - 4 committed rounds"
        assert school["obligation_status"] == "DEFICIENT", (
            "still short by 12 rounds")


class TestLockGatedBySchoolObligation:
    def _scenario(self, api):
        """Alpha: 2 confirmed CX entries, no judge (obligation 4, shortfall 4).
        Beta: 1 confirmed CX entry, no judge. Clock at the lock day."""
        ws = setup_registration_scenario(
            name="Districts LG", prelim_round_count=4, entry_fee_cents=2500,
            schools=(
                {"key": "a", "name": "Alpha", "entries": {"d": 2}, "judges": []},
                {"key": "b", "name": "Beta", "entries": {"d": 1}, "judges": []},
            ),
            confirm_schools=False, lock=False)
        set_clock(LOCK_DAY)
        return ws

    def test_school_confirm_requires_zero_shortfall(self, api):
        """PRD §3.2: "A coach confirms their school — `REGISTERED` → `CONFIRMED` —
        only while the tournament is `REGISTRATION_OPEN`, only from `REGISTERED`
        (otherwise `ERR_SCHOOL_INVALID_STATE`), and only when the school's
        `obligation_status` is `SATISFIED` (otherwise
        `ERR_SCHOOL_OBLIGATION_DEFICIENT`, HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/tournament_lock_gated_by_school_obligation
        """
        ws = self._scenario(api)
        school_id = ws["schools"]["a"]["id"]
        coach = make_coach_headers(school_id)

        rejected = api.confirm_school(school_id, coach)
        validate_error(rejected, "ERR_SCHOOL_OBLIGATION_DEFICIENT")

        judge = add_judge(ws["t"]["id"], school_id, "J-Alpha")
        commit_judge(judge["id"], school_id, 4)
        confirmed = validate_success(api.confirm_school(school_id, coach))
        assert confirmed["status"] == "CONFIRMED"
        school = get_school(school_id)
        assert school["shortfall_rounds"] == 0
        assert school["obligation_status"] == "SATISFIED"

    def test_lock_rejected_while_any_school_unconfirmed(self, api):
        """PRD §3.2: "The lock requires the logical clock to be at or after
        `registration_locks_at` (otherwise `ERR_REGISTRATION_WINDOW_CLOSED`),
        requires every school of the tournament to be `CONFIRMED` with
        `obligation_status` `SATISFIED` (otherwise `ERR_SCHOOLS_NOT_LOCK_READY`)".

        Design: Difficulty/cross_entity_state_dependency/tournament_lock_gated_by_school_obligation
        """
        ws = self._scenario(api)
        # Alpha fixes its posture; Beta stays REGISTERED (and DEFICIENT).
        alpha_id = ws["schools"]["a"]["id"]
        judge = add_judge(ws["t"]["id"], alpha_id, "J-Alpha")
        commit_judge(judge["id"], alpha_id, 4)
        confirm_school(alpha_id)

        current = get_tournament(ws["t"]["id"])
        resp = api.lock_registration(ws["t"]["id"], current["version"], DIRECTOR)
        validate_error(resp, "ERR_SCHOOLS_NOT_LOCK_READY")
        assert get_tournament(ws["t"]["id"])["status"] == "REGISTRATION_OPEN", (
            "the lock did not happen while Beta is unconfirmed")


class TestHiredRoundSizing:
    def test_contract_overpurchase_rejected(self, api):
        """PRD §3.3: "The purchase must be sized against the live shortfall:
        `rounds_requested` must be at least 1 and at most the school's current
        `shortfall_rounds`, otherwise the create is rejected with
        `ERR_HIRED_ROUNDS_EXCEED_SHORTFALL` (HTTP 422)."

        Design: Corner/validations/contract_overpurchase_rejected
        """
        ws = setup_school_with_shortfall(name="OP", entries=2, prelim_round_count=4)
        school_id = ws["schools"]["a"]["id"]
        school = get_school(school_id)
        assert school["shortfall_rounds"] == 4, "ceil(2/2)*4 obligation, no judges"

        resp = api.create_contract(
            create_contract_payload(school_id, 5, school["version"]),
            make_coach_headers(school_id))
        validate_error(resp, "ERR_HIRED_ROUNDS_EXCEED_SHORTFALL")

        _data, meta = validate_paginated(
            api.list_contracts(DIRECTOR, params={"school_id": school_id}))
        assert meta["total_count"] == 0, "the rejected purchase persisted nothing"


class TestOptimisticConcurrency:
    def test_lock_with_stale_tournament_version_rejected(self, api):
        """PRD §2.6: "Locking registration requires the request body to carry
        `expected_tournament_version` equal to the tournament's current `version`.
        Locking snapshots every school's obligation and coverage; if the
        tournament's `version` has advanced since the caller last observed it —
        because entries, judges, contracts, or school confirms have mutated — the
        snapshot basis is stale and the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_lock_stale_version_rejected
        """
        tournament = create_tournament(name="OC")
        open_registration(tournament["id"])
        observed = get_tournament(tournament["id"])["version"]

        division = add_division(tournament["id"])
        school = add_school(tournament["id"], name="Alpha")
        entry = add_entry(school["id"], division["id"], "A-One")
        confirm_entry(entry["id"], school["id"])  # bumps Tournament.version
        set_clock(LOCK_DAY)

        resp = api.lock_registration(tournament["id"], observed, DIRECTOR)
        validate_error(resp, "ERR_STALE_VERSION")
        assert get_tournament(tournament["id"])["status"] == "REGISTRATION_OPEN"

    def test_contract_create_with_stale_school_version_rejected(self, api):
        """PRD §2.6: "Creating a hired-judge contract requires
        `expected_school_version` equal to the school's current `version`. The
        purchase is sized against the school's current shortfall; if the school's
        `version` has advanced since the caller last read it — an entry confirmed
        or withdrawn, a judge committed, another contract filled — the purchase
        basis is stale and the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_contract_create_stale_school_rejected
        """
        ws = setup_school_with_shortfall(name="OS", entries=2, prelim_round_count=4)
        school_id = ws["schools"]["a"]["id"]
        observed = get_school(school_id)["version"]

        judge = add_judge(ws["t"]["id"], school_id, "J-Alpha")
        commit_judge(judge["id"], school_id, 4)  # bumps School.version

        resp = api.create_contract(
            create_contract_payload(school_id, 4, observed),
            make_coach_headers(school_id))
        validate_error(resp, "ERR_STALE_VERSION")

        _data, meta = validate_paginated(
            api.list_contracts(DIRECTOR, params={"school_id": school_id}))
        assert meta["total_count"] == 0
