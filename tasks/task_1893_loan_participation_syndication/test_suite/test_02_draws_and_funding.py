"""Draws, funding settlements, headroom, window overlap, and funding bubbles
(PRD §2.8, §3.3)."""
from test_helpers import (
    ApiErrorId,
    add_participant,
    api_client,
    assert_draw,
    assert_funding_settlement,
    commit_participant,
    create_borrower,
    create_draw,
    create_draw_payload,
    create_facility,
    facility_version,
    get_draw,
    get_facility,
    get_participant,
    get_success_data,
    make_agent_headers,
    make_participant_headers,
    set_clock,
    settlement_for_participant,
    setup_committed_facility,
    validate_error,
    validate_success,
    wire_and_confirm,
    wire_and_confirm_due,
)

AGENT = make_agent_headers()


class TestDrawHeadroomBoundary:
    def test_draw_headroom_exact_equality_boundary(self):
        """PRD §3.3: "The cumulative amount of all non-cancelled draws may not
        exceed `total_commitment_cents`; a draw that would breach that headroom
        rejects with `ERR_DRAW_EXCEEDS_COMMITMENT`."
        PRD §3.3: "The agent creates a Draw against a facility whose status is
        `COMMITTED` — any other status rejects with `ERR_FACILITY_NOT_COMMITTED`."

        The boundary is exercised per facility: the first draw moves the
        facility COMMITTED -> FUNDING, so cumulative headroom is observable
        only as a single draw measured against the ceiling.

        Design: Difficulty/boundary_precision_check/draw_headroom_exact_equality_boundary
        """
        # Exact equality: a draw equal to the whole ceiling is allowed.
        setup = setup_committed_facility([("Solo", 10_000_000)])
        facility = setup["facility"]

        d1 = validate_success(
            api_client.create_draw(
                create_draw_payload(
                    facility["id"],
                    expected_facility_version=facility_version(facility["id"]),
                    draw_amount_cents=10_000_000,
                    accrual_start_date="2026-08-01",
                    accrual_end_date="2027-08-01",
                ),
                AGENT,
            ),
            expected_status=201,
        )
        assert_draw(d1)

        # No draw has settled, so the facility remains in FUNDING.
        assert get_facility(facility["id"])["status"] == "FUNDING"

        # One cent over the ceiling breaches the headroom on a fresh facility.
        over = setup_committed_facility([("SoloOver", 10_000_000)])
        over_facility = over["facility"]
        resp = api_client.create_draw(
            create_draw_payload(
                over_facility["id"],
                expected_facility_version=facility_version(over_facility["id"]),
                draw_amount_cents=10_000_001,
                accrual_start_date="2026-08-01",
                accrual_end_date="2027-08-01",
            ),
            AGENT,
        )
        validate_error(resp, ApiErrorId.ERR_DRAW_EXCEEDS_COMMITMENT, expected_status=409)

    def test_draw_full_headroom_single_shot_and_zero_amount_rejected(self):
        """PRD §3.3: "The cumulative amount of all non-cancelled draws may not
        exceed `total_commitment_cents`; a draw that would breach that headroom
        rejects with `ERR_DRAW_EXCEEDS_COMMITMENT`."
        PRD §3.3: "The agent creates a Draw against a facility whose status is
        `COMMITTED` — any other status rejects with `ERR_FACILITY_NOT_COMMITTED`."

        Design: Difficulty/boundary_precision_check/draw_headroom_exact_equality_boundary
        """
        setup = setup_committed_facility([("Solo", 10_000_000)])
        facility = setup["facility"]

        # A single draw equal to the whole commitment succeeds.
        validate_success(
            api_client.create_draw(
                create_draw_payload(
                    facility["id"],
                    expected_facility_version=facility_version(facility["id"]),
                    draw_amount_cents=10_000_000,
                    accrual_start_date="2026-08-01",
                    accrual_end_date="2027-08-01",
                ),
                AGENT,
            ),
            expected_status=201,
        )

        # The first draw moved the facility COMMITTED -> FUNDING, so any
        # further draw is rejected at the facility-posture check (§2.9
        # priority 7, ahead of the headroom cap at priority 13).
        resp = api_client.create_draw(
            create_draw_payload(
                facility["id"],
                expected_facility_version=facility_version(facility["id"]),
                draw_amount_cents=1,
                accrual_start_date="2027-08-01",
                accrual_end_date="2028-08-01",
            ),
            AGENT,
        )
        validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_COMMITTED, expected_status=409)

    def test_draw_zero_amount_rejected_as_invalid(self):
        """PRD §3.3: "The agent creates a Draw against a facility whose status
        is `COMMITTED` — any other status rejects with `ERR_FACILITY_NOT_COMMITTED`
        — carrying `facility_id`, a strictly positive `draw_amount_cents`, and the
        interest accrual window `accrual_start_date` to `accrual_end_date`."

        Design: Difficulty/boundary_precision_check/draw_headroom_exact_equality_boundary
        """
        setup = setup_committed_facility([("Solo", 10_000_000)])
        facility = setup["facility"]
        resp = api_client.create_draw(
            create_draw_payload(
                facility["id"],
                expected_facility_version=facility_version(facility["id"]),
                draw_amount_cents=0,
            ),
            AGENT,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestDrawWindowOverlap:
    def test_cancelled_draw_window_is_freed(self):
        """PRD §3.3: "Accrual windows of non-cancelled draws on the same facility
        are half-open intervals — a new window whose start equals a sibling's end
        is permitted — and any true overlap rejects with
        `ERR_DRAW_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/draw_windows_half_open_adjacency_allowed
        """
        setup = setup_committed_facility([("Solo", 10_000_000)])
        facility = setup["facility"]

        d1 = create_draw(facility["id"], 1_000_000, "2026-08-01", "2026-09-01")
        get_success_data(api_client.cancel_draw(d1["id"], AGENT))

        # The cancelled draw's window no longer blocks a straddling window.
        d2 = validate_success(
            api_client.create_draw(
                create_draw_payload(
                    facility["id"],
                    expected_facility_version=facility_version(facility["id"]),
                    draw_amount_cents=1_000_000,
                    accrual_start_date="2026-08-15",
                    accrual_end_date="2026-09-15",
                ),
                AGENT,
            ),
            expected_status=201,
        )
        assert_draw(d2)


class TestDrawSettlementBubble:
    def test_draw_settles_only_when_all_settlements_confirmed(self):
        """PRD §3.3: "A draw settles when every one of its settlements has
        reached `CONFIRMED` or `LATE_CONFIRMED`: the draw moves `FUNDING` →
        `SETTLED`, its `outstanding_cents` is set to `draw_amount_cents`,
        `settled_at` is stamped, the facility's `funded_principal_cents` and
        `outstanding_principal_cents` are recomputed, and the first settled draw
        bubbles the facility `FUNDING` → `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/draw_settles_only_when_all_settlements_confirmed
        """
        setup = setup_committed_facility([("P1", 1_000_000), ("P2", 1_000_000)])
        facility = setup["facility"]
        p1, p2 = setup["participants"]
        draw = create_draw(facility["id"], 2_000_000)
        s1 = settlement_for_participant(p1["id"], draw["id"])
        s2 = settlement_for_participant(p2["id"], draw["id"])

        wire_and_confirm_due(s1)
        mid = get_draw(draw["id"])
        assert mid["status"] == "FUNDING", (
            "draw must stay FUNDING while a sibling settlement is unconfirmed"
        )

        wire_and_confirm_due(s2)
        final = get_draw(draw["id"])
        assert_draw(final)
        assert final["status"] == "SETTLED"
        assert final["outstanding_cents"] == 2_000_000
        assert final["settled_at"] is not None

        refreshed = get_facility(facility["id"])
        assert refreshed["status"] == "ACTIVE"
        assert refreshed["funded_principal_cents"] == 2_000_000
        assert refreshed["outstanding_principal_cents"] == 2_000_000
        assert get_participant(p1["id"])["status"] == "FUNDED"
        assert get_participant(p2["id"])["status"] == "FUNDED"

    def test_draw_settles_with_late_confirmed_settlement(self):
        """PRD §3.3: "A draw settles when every one of its settlements has
        reached `CONFIRMED` or `LATE_CONFIRMED`".
        PRD §3.3: "When the wire date is after the due date, confirmation moves
        `WIRED` → `LATE_CONFIRMED`".

        Design: Difficulty/cross_entity_state_dependency/draw_settles_only_when_all_settlements_confirmed
        """
        setup = setup_committed_facility([("Q", 1_200_000), ("R", 800_000)])
        facility = setup["facility"]
        q, r = setup["participants"]
        draw = create_draw(facility["id"], 2_000_000)  # due date 2026-08-06
        sq = settlement_for_participant(q["id"], draw["id"])
        sr = settlement_for_participant(r["id"], draw["id"])
        assert sq["due_cents"] == 1_200_000
        assert sr["due_cents"] == 800_000

        wire_and_confirm_due(sq)

        # R misses the due date: mark DEFAULTED once strictly past 2026-08-06,
        # then wire late and confirm with the exact 2-day penalty.
        set_clock("2026-08-07T00:00:00Z")
        defaulted = validate_success(api_client.mark_settlement_defaulted(sr["id"], AGENT))
        assert defaulted["status"] == "DEFAULTED"
        set_clock("2026-08-08T00:00:00Z")
        get_success_data(
            api_client.report_wire(
                sr["id"], {"amount_cents": 800_000}, make_participant_headers(r["id"])
            )
        )
        confirmed = validate_success(
            api_client.confirm_settlement(sr["id"], {"penalty_received_cents": 2_400}, AGENT)
        )
        assert confirmed["status"] == "LATE_CONFIRMED"

        final_draw = get_draw(draw["id"])
        assert final_draw["status"] == "SETTLED"
        assert final_draw["outstanding_cents"] == 2_000_000
        assert get_facility(facility["id"])["status"] == "ACTIVE"
        assert get_participant(r["id"])["status"] == "FUNDED"


class TestDrawCancellation:
    def test_draw_cancel_voids_pending_settlements(self):
        """PRD §3.3: "Cancellation moves the draw `FUNDING` → `CANCELLED`, voids
        every settlement still in `PENDING`, `WIRED`, or `DEFAULTED` into `VOID`,
        and, if no non-cancelled draw then remains on a facility still in
        `FUNDING`, reverts the facility `FUNDING` → `COMMITTED`."

        Design: Corner/state_machines/draw_cancel_voids_pending_settlements
        """
        setup = setup_committed_facility([("CP", 5_000_000)])
        facility = setup["facility"]
        participant = setup["participants"][0]
        draw = create_draw(facility["id"], 2_000_000)
        settlement = settlement_for_participant(participant["id"], draw["id"])

        cancelled = validate_success(api_client.cancel_draw(draw["id"], AGENT))
        assert_draw(cancelled)
        assert cancelled["status"] == "CANCELLED"

        refreshed_settlement = get_success_data(
            api_client.get_funding_settlement(settlement["id"], AGENT)
        )
        assert refreshed_settlement["status"] == "VOID"

        # No non-cancelled draw remains: facility reverts FUNDING -> COMMITTED.
        assert get_facility(facility["id"])["status"] == "COMMITTED"

    def test_draw_cancel_with_confirmed_funds_rejected(self):
        """PRD §3.3: "A draw that will not complete may instead be cancelled by
        the agent, provided none of its settlements has reached `CONFIRMED` or
        `LATE_CONFIRMED` — confirmed funds block cancellation with
        `ERR_DRAW_HAS_CONFIRMED_FUNDS`."

        Design: Corner/state_machines/draw_cancel_with_confirmed_funds_rejected
        """
        # Two participants so the draw stays FUNDING after one confirmation;
        # the confirmed-funds rule is then the only failing check at cancel.
        setup = setup_committed_facility([("P1", 3_000_000), ("P2", 2_000_000)])
        facility = setup["facility"]
        p1, _ = setup["participants"]
        draw = create_draw(facility["id"], 1_000_000)
        s1 = settlement_for_participant(p1["id"], draw["id"])
        wire_and_confirm_due(s1)
        assert get_draw(draw["id"])["status"] == "FUNDING"

        resp = api_client.cancel_draw(draw["id"], AGENT)
        validate_error(resp, ApiErrorId.ERR_DRAW_HAS_CONFIRMED_FUNDS, expected_status=409)
        assert get_draw(draw["id"])["status"] == "FUNDING"


class TestSettlementConfirmAndDefault:
    def test_settlement_confirm_amount_mismatch_rejected(self):
        """PRD §3.3: "When the wire date is on or before the `funding_due_date`,
        confirmation moves `WIRED` → `CONFIRMED` and requires only that
        `received_cents` equals `due_cents` exactly, failing
        `ERR_FUNDING_AMOUNT_MISMATCH`."

        Design: Corner/state_machines/settlement_confirm_amount_mismatch_rejected
        """
        setup = setup_committed_facility([("MP", 5_000_000)])
        facility = setup["facility"]
        participant = setup["participants"][0]
        draw = create_draw(facility["id"], 2_000_000)
        settlement = settlement_for_participant(participant["id"], draw["id"])
        assert settlement["due_cents"] == 2_000_000

        get_success_data(
            api_client.report_wire(
                settlement["id"],
                {"amount_cents": 1_999_999},
                make_participant_headers(participant["id"]),
            )
        )
        resp = api_client.confirm_settlement(settlement["id"], {}, AGENT)
        validate_error(resp, ApiErrorId.ERR_FUNDING_AMOUNT_MISMATCH, expected_status=409)
        refreshed = get_success_data(api_client.get_funding_settlement(settlement["id"], AGENT))
        assert refreshed["status"] == "WIRED"

    def test_settlement_mark_defaulted_before_due_rejected(self):
        """PRD §3.3: "A settlement still `PENDING` after its due date may be
        marked `DEFAULTED` by the agent — but only once the current clock date is
        strictly after `funding_due_date`, failing `ERR_FUNDING_NOT_YET_DUE`
        earlier".
        PRD §3.3: "Every settlement records the `draw_id`, the `participant_id`,
        and a denormalized `facility_id` for filtered listing, starts in
        `PENDING` with `received_cents` at zero, and carries a `funding_due_date`
        set five calendar days — the funding window — after the draw's creation
        date."

        Design: Corner/state_machines/settlement_mark_defaulted_before_due_rejected
        """
        setup = setup_committed_facility([("DP", 5_000_000)])
        facility = setup["facility"]
        participant = setup["participants"][0]
        draw = create_draw(facility["id"], 2_000_000)  # created at clock 2026-08-01
        settlement = settlement_for_participant(participant["id"], draw["id"])
        assert settlement["funding_due_date"] == "2026-08-06"

        set_clock("2026-08-03T00:00:00Z")
        resp = api_client.mark_settlement_defaulted(settlement["id"], AGENT)
        validate_error(resp, ApiErrorId.ERR_FUNDING_NOT_YET_DUE, expected_status=409)

    def test_late_funding_penalty_exact_amount(self):
        """PRD §3.3: "The penalty is the floor of the settlement's `due_cents`
        multiplied by fifteen basis points per calendar day of lateness — the
        days between `funding_due_date` and the wire date, always a positive
        count — divided by ten thousand, and it is recorded on the settlement as
        `penalty_interest_cents`."
        PRD §3.3: "then the caller-supplied `penalty_received_cents` must equal
        the late-funding penalty exactly, failing `ERR_PENALTY_AMOUNT_MISMATCH`."

        Design: Corner/calculations/late_funding_penalty_exact_amount
        """
        setup = setup_committed_facility([("Q", 1_200_000), ("R", 800_000)])
        facility = setup["facility"]
        q, r = setup["participants"]
        draw = create_draw(facility["id"], 1_000_000)  # due 2026-08-06
        sq = settlement_for_participant(q["id"], draw["id"])
        sr = settlement_for_participant(r["id"], draw["id"])
        assert sq["due_cents"] == 600_000
        assert sr["due_cents"] == 400_000

        wire_and_confirm_due(sq)

        set_clock("2026-08-07T00:00:00Z")
        validate_success(api_client.mark_settlement_defaulted(sr["id"], AGENT))
        set_clock("2026-08-08T00:00:00Z")
        get_success_data(
            api_client.report_wire(
                sr["id"], {"amount_cents": 400_000}, make_participant_headers(r["id"])
            )
        )

        # floor(400,000 * 15 * 2 / 10,000) == 1,200; one cent short is rejected.
        resp = api_client.confirm_settlement(
            sr["id"], {"penalty_received_cents": 1_199}, AGENT
        )
        validate_error(resp, ApiErrorId.ERR_PENALTY_AMOUNT_MISMATCH, expected_status=409)

        confirmed = validate_success(
            api_client.confirm_settlement(sr["id"], {"penalty_received_cents": 1_200}, AGENT)
        )
        assert_funding_settlement(confirmed)
        assert confirmed["status"] == "LATE_CONFIRMED"
        assert confirmed["penalty_interest_cents"] == 1_200

        assert get_draw(draw["id"])["status"] == "SETTLED"
        assert get_facility(facility["id"])["status"] == "ACTIVE"
        assert get_participant(r["id"])["status"] == "FUNDED"
