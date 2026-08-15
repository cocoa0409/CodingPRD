"""Elections, payouts, withholding, default treatment, and the stale-check
sweep — including blackout interaction and the OCC guard on participants."""
from test_helpers import (
    AFTER_DEFAULT_TREATMENT,
    DEFAULT_TREATMENT_DATE,
    ApiErrorId,
    assert_fund_conservation,
    assert_instant_equal,
    assert_payout,
    assert_version_incremented,
    complete_blackout,
    create_accepted_payout,
    create_blackout_with_advisory,
    create_cleared_rollover,
    election_payout,
    flag_participant,
    get_case,
    get_election,
    get_participant,
    list_participant_payouts,
    set_clock,
    setup_case_in_distribution,
    setup_missing_participant,
    submit_election,
    activate_blackout,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
    make_participant_headers,
)

ADMIN = TEST_USERS["admin_headers"]
RECORDKEEPER = TEST_USERS["recordkeeper_headers"]


class TestElectionLifecycle:
    def test_election_reject_and_resubmit_cycle(self, api):
        """PRD §3.6: "Rejection, instead, requires the election to be
        `SUBMITTED` (otherwise `ERR_ELECTION_INVALID_STATE`), carries a
        mandatory `reason`, moves the election `SUBMITTED → REJECTED`, and
        returns the participant `ELECTION_SUBMITTED → PENDING_ELECTION`."

        Design: Corner/state_machines/election_reject_and_resubmit_cycle
        """
        case, plist = setup_case_in_distribution(
            participants=[(250000, 100)], plan_name="Resubmit Co 401k", plan_number="124"
        )
        participant = plist[0]
        election1 = submit_election(participant["id"], "LUMP_SUM_CHECK", None)
        resp = api.reject_election(
            election1["id"], {"reason": "Illegible rollover instructions."}, ADMIN
        )
        election1 = validate_success(resp)
        assert election1["status"] == "REJECTED"
        assert get_participant(participant["id"])["distribution_status"] == "PENDING_ELECTION"

        election2 = submit_election(participant["id"], "DIRECT_ROLLOVER_IRA")
        assert election2["status"] == "SUBMITTED", (
            "rejection returns the participant to PENDING_ELECTION, so a fresh "
            "election is accepted"
        )
        assert get_participant(participant["id"])["distribution_status"] == "ELECTION_SUBMITTED"

        resp = api.reject_election(
            election1["id"],
            {"reason": "Second rejection attempt on a terminal election."},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_ELECTION_INVALID_STATE)

    def test_missing_blocks_election_create_and_accept(self, api):
        """PRD §3.6: "the participant's `locate_status` must not be `MISSING`
        (otherwise `ERR_PARTICIPANT_MISSING_BLOCKS_ELECTION`, HTTP 409 — a
        missing participant goes through the search protocol instead of
        electing)".
        PRD §3.6: "Acceptance requires the election to be `SUBMITTED`
        (otherwise `ERR_ELECTION_INVALID_STATE`) and the participant not
        `MISSING` (otherwise `ERR_PARTICIPANT_MISSING_BLOCKS_ELECTION`)."

        Design: Corner/validations/missing_blocks_election_create_and_accept
        """
        case, plist = setup_case_in_distribution(
            participants=[(250000, 100), (250000, 100)],
            plan_name="MissingVote Co 401k", plan_number="157",
        )
        p_x, p_y = plist
        election_y = submit_election(p_y["id"], "DIRECT_ROLLOVER_IRA")
        for participant in (p_x, p_y):
            setup_missing_participant(participant["id"], flag_clock=None)

        p_x = get_participant(p_x["id"])
        resp = api.create_election(
            {
                "participant_id": p_x["id"],
                "election_method": "DIRECT_ROLLOVER_IRA",
                "expected_participant_version": p_x["version"],
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_PARTICIPANT_MISSING_BLOCKS_ELECTION)

        resp = api.accept_election(election_y["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PARTICIPANT_MISSING_BLOCKS_ELECTION)
        assert get_election(election_y["id"])["status"] == "SUBMITTED", (
            "the blocked acceptance leaves the election in place"
        )


class TestElectionRbac:
    def test_participant_cannot_elect_for_other(self, api):
        """PRD §2.1: "In particular, a `Participant` submitting a distribution
        election must send a payload whose `participant_id` equals `X-User-ID`,
        and any mismatch is rejected with
        `ERR_PARTICIPANT_OWNERSHIP_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/participant_cannot_elect_for_other
        """
        case, plist = setup_case_in_distribution(
            participants=[(250000, 100), (250000, 100)],
            plan_name="Rbac Two Co 401k", plan_number="171",
        )
        p_a, p_b = plist
        p_b = get_participant(p_b["id"])
        resp = api.create_election(
            {
                "participant_id": p_b["id"],
                "election_method": "DIRECT_ROLLOVER_IRA",
                "expected_participant_version": p_b["version"],
            },
            make_participant_headers(p_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PARTICIPANT_OWNERSHIP_VIOLATION)

    def test_participant_self_service_election_succeeds(self, api):
        """PRD §3.6: "Submitting a `DistributionElection` — by the `Participant`
        themself or by a `PlanAdministrator` on their behalf — carries
        `participant_id`, an `election_method` of `LUMP_SUM_CHECK`,
        `DIRECT_ROLLOVER_IRA`, or `DIRECT_ROLLOVER_QUALIFIED_PLAN`, an optional
        `destination_detail` for rollover institution or mailing instructions,
        and the OCC field `expected_participant_version` (§2.6)."
        PRD §2.1: "When `X-User-Role` is `Participant`, `X-User-ID` is the `id`
        of the acting `Participant` record; ownership checks on any resource
        that references a `Participant` compare the resource's foreign-key field
        to `X-User-ID`."

        Design: Corner/rbac/participant_self_service_election_succeeds
        """
        case, plist = setup_case_in_distribution(
            participants=[(250000, 100)], plan_name="Rbac Three Co 401k",
            plan_number="172",
        )
        participant = plist[0]
        own_headers = make_participant_headers(participant["id"])
        election = submit_election(
            participant["id"], "LUMP_SUM_CHECK", None, headers=own_headers
        )
        assert election["status"] == "SUBMITTED"
        assert (
            get_participant(participant["id"])["distribution_status"]
            == "ELECTION_SUBMITTED"
        )

    def test_recordkeeper_cannot_accept_election(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/distribution-elections/{id}/accept` | Accept a
        SUBMITTED election; computes withholding and creates the Payout |
        PlanAdministrator |"

        Design: Corner/rbac/recordkeeper_cannot_accept_election
        """
        case, plist = setup_case_in_distribution(
            participants=[(250000, 100)], plan_name="Rbac One Co 401k", plan_number="170"
        )
        election = submit_election(plist[0]["id"], "DIRECT_ROLLOVER_IRA")
        resp = api.accept_election(election["id"], RECORDKEEPER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_election(election["id"])["status"] == "SUBMITTED"


class TestElectionOcc:
    def test_occ_stale_participant_version_rejected(self, api):
        """PRD §2.6: "Submitting a distribution election requires the request
        body to carry `expected_participant_version`, holding the `version` of
        the electing `Participant` as the client last observed it. If the
        participant's version has advanced — whether because a newer election
        legitimately superseded the previously submitted one, or because a
        cascade such as the vesting re-computation, a contact flag, or a
        forfeiture restoration mutated the participant — the submission is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_participant_version_rejected
        """
        case, plist = setup_case_in_distribution(
            participants=[(250000, 100)], plan_name="Occ Part Co 401k", plan_number="181"
        )
        participant = get_participant(plist[0]["id"])
        stale_version = participant["version"]
        flag_participant(participant["id"], "UNDELIVERABLE_MAIL")  # bumps version
        resp = api.create_election(
            {
                "participant_id": participant["id"],
                "election_method": "LUMP_SUM_CHECK",
                "expected_participant_version": stale_version,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh_version = get_participant(participant["id"])["version"]
        assert_version_incremented(fresh_version, stale_version)
        resp = api.create_election(
            {
                "participant_id": participant["id"],
                "election_method": "LUMP_SUM_CHECK",
                "expected_participant_version": fresh_version,
            },
            ADMIN,
        )
        election = validate_success(resp, 201)
        assert election["status"] == "SUBMITTED"
        assert_version_incremented(
            get_participant(participant["id"])["version"], fresh_version
        )


class TestPayouts:
    def test_payouts_of_election_empty_before_accept(self, api):
        """PRD §4: "| GET | `/distribution-elections/{id}/payouts` | List
        payouts spawned by an election (0 or 1 element) |".
        PRD §3.6: "Acceptance moves the election `SUBMITTED → ACCEPTED`, the
        participant to `ELECTION_ACCEPTED`, and creates the `Payout` with
        `source` `ELECTION` and a back-reference in `distribution_election_id`
        (null for payouts created by default treatment)."

        Design: Corner/endpoints/payouts_of_election_empty_before_accept
        """
        case, plist = setup_case_in_distribution(
            participants=[(250000, 100)], plan_name="EmptyPay Co 401k", plan_number="162"
        )
        election = submit_election(plist[0]["id"], "DIRECT_ROLLOVER_IRA")
        data, meta = validate_paginated(api.list_election_payouts(election["id"], ADMIN))
        assert data == [] and meta["total_count"] == 0, (
            "before acceptance the reverse read is an empty array"
        )
        validate_success(api.accept_election(election["id"], ADMIN))
        data, meta = validate_paginated(api.list_election_payouts(election["id"], ADMIN))
        assert len(data) == 1
        payout = data[0]
        assert payout["distribution_election_id"] == election["id"]
        assert payout["source"] == "ELECTION"
        assert payout["status"] == "ISSUED"

    def test_cleared_payout_rejects_second_clear(self, api):
        """PRD §3.6: "Marking a payout cleared requires it to be `ISSUED`
        (otherwise `ERR_PAYOUT_NOT_CLEARABLE`, HTTP 409); clearing stamps
        `cleared_at`, moves the payout `ISSUED → CLEARED`, moves the linked
        election (if any) `ACCEPTED → SETTLED`, and resolves the participant by
        method".

        Design: Corner/state_machines/cleared_payout_rejects_second_clear
        """
        case, plist = setup_case_in_distribution(
            participants=[(200000, 100)], plan_name="Twice Clear Co 401k",
            plan_number="123",
        )
        _, payout = create_cleared_rollover(plist[0]["id"])
        assert payout["status"] == "CLEARED"
        resp = api.mark_payout_cleared(payout["id"], RECORDKEEPER)
        validate_error(resp, ApiErrorId.ERR_PAYOUT_NOT_CLEARABLE)
        case = get_case(case["id"])
        assert case["paid_out_cents"] == 200000, (
            "the rejected second clear must not double-count the payout"
        )
        assert case["resolved_participant_count"] == 1

    def test_payout_void_returns_participant_to_pending(self, api):
        """PRD §3.6: "The void moves the payout to `VOIDED` with no ledger
        movement — the uncashed gross never left `remaining_undistributed_cents`
        in the first place — returns the participant `ELECTION_ACCEPTED →
        PENDING_ELECTION`, and flips the linked election (if any) `ACCEPTED →
        SUPERSEDED`, so a fresh election is required to re-resolve the
        participant."
        PRD §3.3: "A transition on one dimension never changes the other unless
        a stated cascade says so."

        Design: Corner/state_machines/payout_void_returns_participant_to_pending
        """
        case, plist = setup_case_in_distribution(
            participants=[(150000, 100)], plan_name="Void Co 401k", plan_number="119"
        )
        participant = plist[0]
        set_clock("2026-10-16T00:00:00Z")
        election, payout = create_accepted_payout(
            participant["id"], "LUMP_SUM_CHECK", None
        )
        set_clock("2027-01-14T00:00:00Z")  # issued_at + 90 days: sweep fires
        resp = api.void_payout(payout["id"], RECORDKEEPER)
        payout = validate_success(resp)
        assert payout["status"] == "VOIDED"
        participant = get_participant(participant["id"])
        assert participant["distribution_status"] == "PENDING_ELECTION"
        assert participant["locate_status"] == "FLAGGED_UNCASHED", (
            "the stale-sweep flag on the locate dimension survives the void"
        )
        assert get_election(election["id"])["status"] == "SUPERSEDED"
        case = get_case(case["id"])
        assert case["paid_out_cents"] == 0
        assert case["remaining_undistributed_cents"] == 150000
        assert_fund_conservation(case)

    def test_prepared_payout_released_on_blackout_complete(self, api):
        """PRD §3.6: "The payout's initial status depends on the case's blackout
        posture: `PREPARED` when `blackout_active` is true, otherwise `ISSUED`
        with `issued_at` stamped."
        PRD §3.5: "Completion stamps `completed_at`, recomputes `blackout_active`
        to false, and releases the queue: every payout of the case sitting in
        `PREPARED` moves to `ISSUED` with `issued_at` set to the completion
        clock time."

        Design: Corner/state_machines/prepared_payout_released_on_blackout_complete
        """
        case, plist = setup_case_in_distribution(
            participants=[(250000, 100)], plan_name="Queue Co 401k", plan_number="120"
        )
        participant = plist[0]
        election = submit_election(participant["id"], "DIRECT_ROLLOVER_IRA")
        blackout = create_blackout_with_advisory(
            case["id"], "2026-11-01T00:00:00Z", "2026-11-05T00:00:00Z",
            advisory_clock="2026-10-01T00:00:00Z",
        )
        activate_blackout(blackout["id"], "2026-11-02T00:00:00Z")
        accept_resp = api.accept_election(election["id"], ADMIN)
        validate_success(accept_resp)
        payout = election_payout(election["id"])
        assert payout["status"] == "PREPARED", "the payout queues behind the blackout"
        assert payout["issued_at"] is None

        complete_blackout(blackout["id"], "2026-11-05T00:00:00Z")
        data = list_participant_payouts(participant["id"])
        payout = data[0]
        assert payout["status"] == "ISSUED"
        assert_instant_equal(
            payout["issued_at"], "2026-11-05T00:00:00Z",
            "issued_at is the blackout completion clock time",
        )
        assert get_case(case["id"])["blackout_active"] is False


class TestWithholding:
    def test_withholding_floor_boundary(self, api):
        """PRD §3.6: "Withholding is computed at creation: when the method is
        `LUMP_SUM_CHECK` and the gross is at least 20000 cents (200.00 dollars —
        at or above the floor, withhold; below it, zero), `withholding_cents` is
        20 percent of the gross rounded half up to whole cents; in every other
        case `withholding_cents` is zero."

        Design: Corner/calculations/withholding_floor_boundary
        """
        case, plist = setup_case_in_distribution(
            participants=[(19999, 100), (20000, 100)],
            plan_name="Floor Co 401k", plan_number="130",
        )
        _, payout_lo = create_accepted_payout(plist[0]["id"], "LUMP_SUM_CHECK", None)
        assert_payout(payout_lo)
        assert payout_lo["gross_cents"] == 19999
        assert payout_lo["withholding_cents"] == 0, "below the floor: no withholding"
        assert payout_lo["net_cents"] == 19999

        _, payout_hi = create_accepted_payout(plist[1]["id"], "LUMP_SUM_CHECK", None)
        assert payout_hi["gross_cents"] == 20000
        assert payout_hi["withholding_cents"] == 4000, (
            "at the inclusive floor: 20% of 20000 = 4000"
        )
        assert payout_hi["net_cents"] == 16000

    def test_withholding_lump_sum_branch(self, api):
        """PRD §3.6: "Withholding is computed at creation: when the method is
        `LUMP_SUM_CHECK` and the gross is at least 20000 cents (200.00 dollars —
        at or above the floor, withhold; below it, zero), `withholding_cents` is
        20 percent of the gross rounded half up to whole cents; in every other
        case `withholding_cents` is zero. `net_cents` is the gross minus the
        withholding."

        Design: Difficulty/combinatorial_formula/withholding_branch_interaction
        """
        case, plist = setup_case_in_distribution(
            participants=[(120000, 100)], plan_name="Withhold Co 401k", plan_number="030"
        )
        _, payout = create_accepted_payout(plist[0]["id"], "LUMP_SUM_CHECK", None)
        assert payout["method"] == "LUMP_SUM_CHECK"
        assert payout["gross_cents"] == 120000
        assert payout["withholding_cents"] == 24000
        assert payout["net_cents"] == 96000

    def test_withholding_rollover_branch(self, api):
        """PRD §3.6: "Withholding is computed at creation: when the method is
        `LUMP_SUM_CHECK` and the gross is at least 20000 cents (200.00 dollars —
        at or above the floor, withhold; below it, zero), `withholding_cents` is
        20 percent of the gross rounded half up to whole cents; in every other
        case `withholding_cents` is zero."

        Design: Difficulty/combinatorial_formula/withholding_branch_interaction
        """
        case, plist = setup_case_in_distribution(
            participants=[(120000, 100)], plan_name="Withhold Co 401k", plan_number="030"
        )
        _, payout = create_accepted_payout(plist[0]["id"], "DIRECT_ROLLOVER_IRA")
        assert payout["method"] == "DIRECT_ROLLOVER_IRA"
        assert payout["gross_cents"] == 120000
        assert payout["withholding_cents"] == 0, "the rollover branch never withholds"
        assert payout["net_cents"] == 120000


class TestDefaultTreatment:
    def test_default_treatment_below_1000_cashes_out(self, api):
        """PRD §3.6: "The tier is resolved on `net_distributable_cents` against
        two statutory limits: below 100000 cents (1000.00 dollars) the payout
        method is `LUMP_SUM_CHECK`; at or above 100000 and at or below 500000
        cents (5000.00 dollars) the method is `AUTO_ROLLOVER_IRA`; above 500000
        the request is rejected with `ERR_BALANCE_EXCEEDS_FORCED_LIMIT`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/default_treatment_1000_dollar_boundary
        """
        case, plist = setup_case_in_distribution(
            participants=[(99999, 100)], plan_name="Tier Co 401k", plan_number="070"
        )
        set_clock(AFTER_DEFAULT_TREATMENT)
        resp = api.apply_default_treatment(plist[0]["id"], ADMIN)
        participant = validate_success(resp)
        assert participant["distribution_status"] == "ELECTION_ACCEPTED"
        payout = list_participant_payouts(participant["id"])[0]
        assert payout["method"] == "LUMP_SUM_CHECK"
        assert payout["source"] == "DEFAULT_TREATMENT"
        assert payout["gross_cents"] == 99999
        assert payout["withholding_cents"] == 20000  # 99999 >= 20000 floor
        assert payout["net_cents"] == 79999

    def test_default_treatment_at_1000_rolls_over(self, api):
        """PRD §3.6: "The boundaries are inclusive-low and inclusive-high:
        exactly 100000 cents rolls over, exactly 500000 cents rolls over, and
        500001 is rejected."

        Design: Difficulty/boundary_precision_check/default_treatment_1000_dollar_boundary
        """
        case, plist = setup_case_in_distribution(
            participants=[(100000, 100)], plan_name="Tier Co 401k", plan_number="070"
        )
        set_clock(AFTER_DEFAULT_TREATMENT)
        resp = api.apply_default_treatment(plist[0]["id"], ADMIN)
        participant = validate_success(resp)
        assert participant["distribution_status"] == "ELECTION_ACCEPTED"
        payout = list_participant_payouts(participant["id"])[0]
        assert payout["method"] == "AUTO_ROLLOVER_IRA", (
            "exactly 100000 cents is inside the rollover tier"
        )
        assert payout["withholding_cents"] == 0, "rollovers never withhold"
        assert payout["net_cents"] == 100000

    def test_default_treatment_5000_ceiling(self, api):
        """PRD §3.6: "The boundaries are inclusive-low and inclusive-high:
        exactly 100000 cents rolls over, exactly 500000 cents rolls over, and
        500001 is rejected."

        Design: Corner/calculations/default_treatment_5000_dollar_ceiling
        """
        case, plist = setup_case_in_distribution(
            participants=[(500000, 100), (500001, 100)],
            plan_name="Ceiling Co 401k", plan_number="131",
        )
        set_clock(AFTER_DEFAULT_TREATMENT)
        resp = api.apply_default_treatment(plist[0]["id"], ADMIN)
        validate_success(resp)
        payout = list_participant_payouts(plist[0]["id"])[0]
        assert payout["method"] == "AUTO_ROLLOVER_IRA"
        assert payout["gross_cents"] == 500000
        assert payout["withholding_cents"] == 0

        resp = api.apply_default_treatment(plist[1]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_BALANCE_EXCEEDS_FORCED_LIMIT)
        assert (
            get_participant(plist[1]["id"])["distribution_status"] == "PENDING_ELECTION"
        )
        assert list_participant_payouts(plist[1]["id"]) == []

    def test_default_treatment_before_window_rejected(self, api):
        """PRD §3.6: "After the clock has passed the case's
        `default_treatment_date` — strictly after; applying at or before it is
        rejected with `ERR_DEFAULT_TREATMENT_WINDOW_NOT_PASSED` (HTTP 409)".

        Design: Corner/calculations/default_treatment_before_window_returns_error
        """
        case, plist = setup_case_in_distribution(
            participants=[(150000, 100)], plan_name="Early Co 401k", plan_number="132"
        )
        case = get_case(case["id"])
        assert_instant_equal(
            case["default_treatment_date"], DEFAULT_TREATMENT_DATE,
            "default_treatment_date is the distribution date plus 30 days",
        )
        set_clock(DEFAULT_TREATMENT_DATE)  # exactly at the date: not strictly after
        resp = api.apply_default_treatment(plist[0]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_DEFAULT_TREATMENT_WINDOW_NOT_PASSED)

        set_clock(AFTER_DEFAULT_TREATMENT)
        resp = api.apply_default_treatment(plist[0]["id"], ADMIN)
        participant = validate_success(resp)
        assert participant["distribution_status"] == "ELECTION_ACCEPTED"
        payout = list_participant_payouts(participant["id"])[0]
        assert payout["method"] == "AUTO_ROLLOVER_IRA"
        assert payout["gross_cents"] == 150000

    def test_default_treatment_on_missing_requires_search(self, api):
        """PRD §3.6: "a `PlanAdministrator` may apply the default to a
        participant whose `distribution_status` is `PENDING_ELECTION` or
        `RESTORED` (otherwise `ERR_ELECTION_INVALID_STATE`) and whose
        `locate_status` is not `MISSING` (otherwise
        `ERR_PARTICIPANT_MISSING_REQUIRES_SEARCH`, HTTP 409 — the search
        protocol must run for missing participants)."

        Design: Corner/validations/default_treatment_on_missing_requires_search
        """
        case, plist = setup_case_in_distribution(
            participants=[(100000, 100)], plan_name="SearchFirst Co 401k",
            plan_number="158",
        )
        setup_missing_participant(plist[0]["id"], flag_clock=None)
        set_clock(AFTER_DEFAULT_TREATMENT)
        resp = api.apply_default_treatment(plist[0]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PARTICIPANT_MISSING_REQUIRES_SEARCH)
        participant = get_participant(plist[0]["id"])
        assert participant["distribution_status"] == "PENDING_ELECTION"
        assert list_participant_payouts(participant["id"]) == []


class TestElectionBlackoutInteraction:
    def _case_with_active_blackout(self, api):
        case, plist = setup_case_in_distribution(
            participants=[(250000, 100)], plan_name="Blockout Co 401k", plan_number="080"
        )
        blackout = create_blackout_with_advisory(
            case["id"], "2026-11-01T00:00:00Z", "2026-11-05T00:00:00Z",
            advisory_clock="2026-10-01T00:00:00Z",
        )
        activate_blackout(blackout["id"], "2026-11-02T00:00:00Z")
        return case, plist[0], blackout

    def test_election_blocked_by_active_blackout(self, api):
        """PRD §3.6: "no `BlackoutPeriod` of the case may be `ACTIVE`
        (otherwise `ERR_BLACKOUT_ACTIVE_ELECTIONS_BLOCKED`, HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/election_blocked_by_active_blackout
        """
        case, participant, _ = self._case_with_active_blackout(api)
        assert get_case(case["id"])["blackout_active"] is True
        participant = get_participant(participant["id"])
        resp = api.create_election(
            {
                "participant_id": participant["id"],
                "election_method": "DIRECT_ROLLOVER_IRA",
                "expected_participant_version": participant["version"],
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_BLACKOUT_ACTIVE_ELECTIONS_BLOCKED)
        assert (
            get_participant(participant["id"])["distribution_status"]
            == "PENDING_ELECTION"
        )
        data, _ = validate_paginated(
            api.list_elections(ADMIN, params={"participant_id": participant["id"]})
        )
        assert data == [], "the rejected submission creates no election row"

    def test_election_succeeds_after_blackout_completes(self, api):
        """PRD §3.6: "no `BlackoutPeriod` of the case may be `ACTIVE`
        (otherwise `ERR_BLACKOUT_ACTIVE_ELECTIONS_BLOCKED`, HTTP 409)".
        PRD §3.5: "Completion stamps `completed_at`, recomputes
        `blackout_active` to false, and releases the queue".

        Design: Difficulty/cross_entity_state_dependency/election_blocked_by_active_blackout
        """
        case, participant, blackout = self._case_with_active_blackout(api)
        complete_blackout(blackout["id"], "2026-11-05T00:00:00Z")
        assert get_case(case["id"])["blackout_active"] is False
        election = submit_election(participant["id"], "DIRECT_ROLLOVER_IRA")
        assert election["status"] == "SUBMITTED"
        assert (
            get_participant(participant["id"])["distribution_status"]
            == "ELECTION_SUBMITTED"
        )


class TestStaleCheckSweep:
    def _issued_lump_sum_payout(self, api):
        """Case in DISTRIBUTION_IN_PROGRESS; LUMP_SUM_CHECK payout issued at
        2026-10-16 (150000 gross, withholding 30000, net 120000)."""
        case, plist = setup_case_in_distribution(
            participants=[(150000, 100)], plan_name="Stale Co 401k", plan_number="051"
        )
        participant = plist[0]
        set_clock("2026-10-16T00:00:00Z")
        election, payout = create_accepted_payout(
            participant["id"], "LUMP_SUM_CHECK", None
        )
        assert payout["status"] == "ISSUED"
        assert_instant_equal(payout["issued_at"], "2026-10-16T00:00:00Z", "issued_at")
        return case, participant, election, payout

    def test_stale_sweep_boundary_at_ninety_days(self, api):
        """PRD §3.6: "Every clock advance runs a sweep over all `ISSUED` payouts
        with method `LUMP_SUM_CHECK` across all cases, in `issued_at` ascending
        order (ties by `created_at` ascending): a check becomes `STALE_UNCASHED`
        when the current clock has reached its `issued_at` plus 90 days — the
        boundary is inclusive, so a check exactly 90 days old is stale."

        Design: Difficulty/transitive_cascade/clock_sweep_stale_check_flag_cascade
        """
        _, participant, _, payout = self._issued_lump_sum_payout(api)
        set_clock("2027-01-13T00:00:00Z")  # issued_at + 89 days
        current = list_participant_payouts(participant["id"])[0]
        assert current["status"] == "ISSUED", "89 days: the threshold is not crossed"

        set_clock("2027-01-14T00:00:00Z")  # issued_at + 90 days exactly
        current = list_participant_payouts(participant["id"])[0]
        assert current["status"] == "STALE_UNCASHED", (
            "at exactly 90 days the inclusive >= boundary flips the payout"
        )
        assert_instant_equal(
            current["stale_marked_at"], "2027-01-14T00:00:00Z", "stale_marked_at"
        )

    def test_stale_sweep_flags_participant_and_preserves_amounts(self, api):
        """PRD §3.6: "The transition stamps `stale_marked_at`, and its cascade
        flags the participant `FLAGGED_UNCASHED` (with `flagged_at` stamped)
        only when the participant's `locate_status` was `UNVERIFIED` — this is
        the system's half of uncashed-check identification, complementing the
        `Recordkeeper`'s manual flag."

        Design: Difficulty/transitive_cascade/clock_sweep_stale_check_flag_cascade
        """
        _, participant, _, payout = self._issued_lump_sum_payout(api)
        assert get_participant(participant["id"])["locate_status"] == "UNVERIFIED"
        set_clock("2027-01-14T00:00:00Z")
        participant = get_participant(participant["id"])
        assert participant["locate_status"] == "FLAGGED_UNCASHED"
        assert_instant_equal(
            participant["flagged_at"], "2027-01-14T00:00:00Z", "flagged_at"
        )
        current = list_participant_payouts(participant["id"])[0]
        assert current["gross_cents"] == 150000
        assert current["withholding_cents"] == 30000
        assert current["net_cents"] == 120000, (
            "the stale flip moves no money — amounts are untouched"
        )
