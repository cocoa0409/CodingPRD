"""
Contracting a placement: proposal-time checks, the contract encumbrance, the
activation gates and the exclusivity of a student's placement windows.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_INSUFFICIENT_FISCAL_AUTHORITY,
    ERR_INVALID_PLACEMENT_WINDOW,
    ERR_INVALID_STATE_TRANSITION,
    ERR_PLACEMENT_DATE_OVERLAP,
    ERR_RATE_SCHEDULE_NOT_EFFECTIVE,
    ERR_RESIDENTIAL_NOT_AUTHORIZED,
    ERR_SCHOOL_NOT_APPROVED,
)
from test_helpers.assertions import (
    assert_instant_equals,
    assert_ledger,
    assert_placement_encumbrance_mirror,
)
from test_helpers.fixtures import (
    ACTIVATION_INSTANT,
    build_contracted_day_placement,
    build_reference_data,
    list_rows,
    make_active_placement,
    make_approved_decision,
    make_proposed_placement,
    read_account,
    read_placement,
    read_student,
    set_clock,
)
from test_helpers.test_users import (
    COORDINATOR_HEADERS,
    FISCAL_OFFICER_HEADERS,
    SYSTEM_ADMIN_HEADERS,
)

DAY_CONTRACT_ENCUMBRANCE_CENTS = 5760000


class TestDoubleContractExecution:
    def test_second_execution_reports_the_state_error_not_the_money(self, api):
        """
        On an account with only 240 000 cents left, a second execute-contract on an
        already CONTRACTED placement reports the state error, because state legality
        is evaluated before fiscal capacity.

        PRD: "Before that figure is booked, the account must be able to cover it: `available_cents` must be at least the computed contract encumbrance, or the request is refused with `ERR_INSUFFICIENT_FISCAL_AUTHORITY` (402) — and, per §2.10, only after every state, referential, temporal, safety and constraint check has already passed."

        Design: Difficulty/priority_pair_validation_conflict/state_priority_8_beats_fiscal_priority_13_on_double_execute_contract
        """
        world = build_contracted_day_placement(
            api, account_overrides={"authorized_cents": 6000000}
        )
        assert_ledger(
            read_account(api, world["account"]["id"]),
            available=240000,
            encumbered=DAY_CONTRACT_ENCUMBRANCE_CENTS,
            disbursed=0,
        )

        response = api.execute_contract(
            world["placement"]["id"], FISCAL_OFFICER_HEADERS
        )
        validate_error(response, ERR_INVALID_STATE_TRANSITION, 409)

    def test_second_execution_does_not_double_book_the_commitment(self, api):
        """
        The refused second execution books nothing a second time: the placement keeps
        one contract encumbrance and the account decomposition is unmoved.

        PRD: "For every account, `authorized_cents` always equals the sum of `available_cents`, `encumbered_cents` and `disbursed_cents`."

        Design: Difficulty/priority_pair_validation_conflict/state_priority_8_beats_fiscal_priority_13_on_double_execute_contract
        """
        world = build_contracted_day_placement(
            api, account_overrides={"authorized_cents": 6000000}
        )
        validate_error(
            api.execute_contract(world["placement"]["id"], FISCAL_OFFICER_HEADERS),
            ERR_INVALID_STATE_TRANSITION,
            409,
        )

        placement = read_placement(api, world["placement"]["id"])
        assert placement["status"] == "CONTRACTED"
        assert placement["contract_encumbrance_cents"] == DAY_CONTRACT_ENCUMBRANCE_CENTS
        assert_placement_encumbrance_mirror(placement)
        assert_ledger(
            read_account(api, world["account"]["id"]),
            available=240000,
            encumbered=DAY_CONTRACT_ENCUMBRANCE_CENTS,
            disbursed=0,
        )


class TestActivationGatedOnSchoolStanding:
    def test_revoked_and_provisional_standing_both_block_activation(self, api):
        """
        A school revoked after the contract was executed blocks activation, and
        moving it to provisional standing does not unblock it.

        PRD: "The school's `approval_status` must be exactly `APPROVED` at this instant — both `PROVISIONAL` and `REVOKED` block activation with `ERR_SCHOOL_NOT_APPROVED`, so a school revoked between contract execution and activation stops the placement dead even though the contract was legitimately executed against a provisional or approved school."

        Design: Difficulty/cross_entity_state_dependency/placement_activation_gated_on_school_approval_standing
        """
        world = build_contracted_day_placement(api)
        placement_id = world["placement"]["id"]
        validate_success(
            api.patch_school_approval_status(
                world["school"]["id"],
                f.approval_status_payload("REVOKED"),
                SYSTEM_ADMIN_HEADERS,
            )
        )
        set_clock(api, ACTIVATION_INSTANT)

        validate_error(
            api.activate_placement(placement_id, COORDINATOR_HEADERS),
            ERR_SCHOOL_NOT_APPROVED,
            409,
        )
        blocked = read_placement(api, placement_id)
        assert blocked["status"] == "CONTRACTED"
        assert blocked["activated_at"] is None

        validate_success(
            api.patch_school_approval_status(
                world["school"]["id"],
                f.approval_status_payload("PROVISIONAL"),
                SYSTEM_ADMIN_HEADERS,
            )
        )
        validate_error(
            api.activate_placement(placement_id, COORDINATOR_HEADERS),
            ERR_SCHOOL_NOT_APPROVED,
            409,
        )
        still_blocked = read_placement(api, placement_id)
        assert still_blocked["status"] == "CONTRACTED"
        assert still_blocked["activated_at"] is None
        assert (
            still_blocked["contract_encumbrance_cents"]
            == DAY_CONTRACT_ENCUMBRANCE_CENTS
        )

    def test_restoring_approved_standing_lets_the_same_placement_activate(self, api):
        """
        Once the school is approved again the same placement activates, and the
        commitment booked at execution never moved while activation was blocked.

        PRD: "On success: `status` becomes `ACTIVE`, `activated_at` is stamped from the logical clock, the student's `placement_status` becomes `OOD_ACTIVE` with the student's `version` incremented, and the placement's `version` is incremented."

        Design: Difficulty/cross_entity_state_dependency/placement_activation_gated_on_school_approval_standing
        """
        world = build_contracted_day_placement(api)
        placement_id = world["placement"]["id"]
        school_id = world["school"]["id"]
        for status in ("REVOKED", "PROVISIONAL"):
            validate_success(
                api.patch_school_approval_status(
                    school_id, f.approval_status_payload(status), SYSTEM_ADMIN_HEADERS
                )
            )
            if status == "REVOKED":
                set_clock(api, ACTIVATION_INSTANT)
            validate_error(
                api.activate_placement(placement_id, COORDINATOR_HEADERS),
                ERR_SCHOOL_NOT_APPROVED,
                409,
            )
            assert_ledger(
                read_account(api, world["account"]["id"]),
                encumbered=DAY_CONTRACT_ENCUMBRANCE_CENTS,
            )

        validate_success(
            api.patch_school_approval_status(
                school_id, f.approval_status_payload("APPROVED"), SYSTEM_ADMIN_HEADERS
            )
        )
        activated = validate_success(
            api.activate_placement(placement_id, COORDINATOR_HEADERS)
        )
        assert activated["status"] == "ACTIVE"
        assert_instant_equals(activated["activated_at"], ACTIVATION_INSTANT)
        assert activated["contract_encumbrance_cents"] == DAY_CONTRACT_ENCUMBRANCE_CENTS
        assert read_student(api, world["student"]["id"])["placement_status"] == "OOD_ACTIVE"
        assert_ledger(
            read_account(api, world["account"]["id"]),
            available=100000000 - DAY_CONTRACT_ENCUMBRANCE_CENTS,
            encumbered=DAY_CONTRACT_ENCUMBRANCE_CENTS,
            disbursed=0,
        )


def _student_with_two_decisions_and_an_active_placement(api):
    """One student, two independently approved decisions, one ACTIVE placement."""
    ref = build_reference_data(api)
    first_decision = make_approved_decision(api, ref["student"]["id"])
    second_decision = make_approved_decision(api, ref["student"]["id"])
    ref["placement"] = make_active_placement(api, ref, decision=first_decision)
    ref["second_decision"] = second_decision
    return ref


def _successor_payload(ref, start_date):
    return f.placement_payload(
        ref["student"]["id"],
        ref["school"]["id"],
        ref["second_decision"]["id"],
        ref["schedule"]["id"],
        ref["account"]["id"],
        start_date=start_date,
        end_date="2027-06-28",
        contracted_instructional_days=10,
    )


class TestStudentPlacementExclusivity:
    def test_a_single_shared_endpoint_day_is_an_intersection(self, api):
        """
        A successor placement starting on the incumbent's own end date shares one day
        with it and is refused, leaving the student with a single placement row.

        PRD: "Adjacency is permitted with no buffer whatsoever — the prior placement's `end_date` need only be strictly earlier than the new `start_date` — but a single shared day is an intersection and draws `ERR_PLACEMENT_DATE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/student_placement_windows_are_closed_intervals_so_shared_endpoint_collides
        """
        ref = _student_with_two_decisions_and_an_active_placement(api)

        response = api.create_placement(
            _successor_payload(ref, "2027-06-15"), COORDINATOR_HEADERS
        )
        validate_error(response, ERR_PLACEMENT_DATE_OVERLAP, 409)

        rows, meta = list_rows(
            api.list_placements(
                COORDINATOR_HEADERS, {"student_id": ref["student"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == ref["placement"]["id"]

    def test_the_next_day_is_adjacency_and_is_admitted_fiscally_inert(self, api):
        """
        Moving the successor one day later makes the intervals adjacent rather than
        intersecting, and the accepted proposal commits no money at all.

        PRD: "Its `status` is `PROPOSED`, all four encumbrance components — `contract_encumbrance_cents`, `addendum_encumbrance_cents`, `transport_encumbrance_cents` and `transition_reserve_cents` — are zero, so its `encumbrance_cents` and `released_encumbrance_cents` are zero too, `paid_total_ytd_cents` is zero, and `transport_status` is `NOT_REQUIRED` regardless of what `transportation_required` says."

        Design: Difficulty/resource_temporal_overlap/student_placement_windows_are_closed_intervals_so_shared_endpoint_collides
        """
        ref = _student_with_two_decisions_and_an_active_placement(api)
        validate_error(
            api.create_placement(
                _successor_payload(ref, "2027-06-15"), COORDINATOR_HEADERS
            ),
            ERR_PLACEMENT_DATE_OVERLAP,
            409,
        )

        successor = validate_success(
            api.create_placement(
                _successor_payload(ref, "2027-06-16"), COORDINATOR_HEADERS
            ),
            201,
        )
        assert successor["status"] == "PROPOSED"
        assert successor["contract_encumbrance_cents"] == 0
        assert successor["encumbrance_cents"] == 0
        assert_placement_encumbrance_mirror(successor)

        _, meta = list_rows(
            api.list_placements(
                COORDINATOR_HEADERS, {"student_id": ref["student"]["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert_ledger(
            read_account(api, ref["account"]["id"]),
            available=100000000 - DAY_CONTRACT_ENCUMBRANCE_CENTS,
            encumbered=DAY_CONTRACT_ENCUMBRANCE_CENTS,
            disbursed=0,
        )


class TestProposalState:
    def test_a_new_placement_lands_proposed_and_books_nothing(self, api):
        """
        Creation puts the placement in PROPOSED with every encumbrance component at
        zero and leaves the funding account completely untouched.

        PRD: "Its `status` is `PROPOSED`, all four encumbrance components — `contract_encumbrance_cents`, `addendum_encumbrance_cents`, `transport_encumbrance_cents` and `transition_reserve_cents` — are zero, so its `encumbrance_cents` and `released_encumbrance_cents` are zero too, `paid_total_ytd_cents` is zero, and `transport_status` is `NOT_REQUIRED` regardless of what `transportation_required` says."

        Design: Corner/state_machines/placement_created_in_declared_initial_state_proposed
        """
        ref = build_reference_data(api)
        decision = make_approved_decision(api, ref["student"]["id"])
        created = validate_success(
            api.create_placement(
                f.placement_payload(
                    ref["student"]["id"],
                    ref["school"]["id"],
                    decision["id"],
                    ref["schedule"]["id"],
                    ref["account"]["id"],
                ),
                COORDINATOR_HEADERS,
            ),
            201,
        )
        assert created["status"] == "PROPOSED"
        assert created["contract_encumbrance_cents"] == 0
        assert created["addendum_encumbrance_cents"] == 0
        assert created["transport_encumbrance_cents"] == 0
        assert created["transition_reserve_cents"] == 0
        assert created["paid_total_ytd_cents"] == 0
        assert created["released_encumbrance_cents"] == 0
        assert created["encumbrance_cents"] == 0
        assert created["transport_status"] == "NOT_REQUIRED"
        assert created["version"] == 1
        assert_ledger(
            read_account(api, ref["account"]["id"]),
            available=100000000,
            encumbered=0,
            disbursed=0,
        )

    def test_activation_from_proposed_is_refused_before_any_contract_exists(self, api):
        """
        Activation is only reachable from CONTRACTED, so a PROPOSED placement cannot
        skip the money-committing step.

        PRD: "A `PlacementCoordinator` advances the placement `CONTRACTED → ACTIVE` once the student is actually in the seat."

        Design: Corner/state_machines/activate_before_contract_execution_rejected
        """
        ref = build_reference_data(api)
        placement = make_proposed_placement(api, ref)

        validate_error(
            api.activate_placement(placement["id"], COORDINATOR_HEADERS),
            ERR_INVALID_STATE_TRANSITION,
            409,
        )

        after = read_placement(api, placement["id"])
        assert after["status"] == "PROPOSED"
        assert after["activated_at"] is None
        assert after["version"] == 1
        assert_ledger(
            read_account(api, ref["account"]["id"]),
            available=100000000,
            encumbered=0,
            disbursed=0,
        )
        assert read_student(api, ref["student"]["id"])["placement_status"] == "DECISION_APPROVED"

    def test_inverted_and_backdated_windows_draw_the_same_refusal(self, api):
        """
        An end date on or before the start date and a start date behind the logical
        clock are the two arms of one window rule and share one error code.

        PRD: "Third, window sanity: `end_date` must be strictly later than `start_date`, and `start_date` must not precede the current logical clock date, or the refusal is `ERR_INVALID_PLACEMENT_WINDOW`."

        Design: Corner/errors/inverted_and_backdated_placement_windows_rejected
        """
        ref = build_reference_data(api)
        decision = make_approved_decision(api, ref["student"]["id"])

        def proposal(**overrides):
            return f.placement_payload(
                ref["student"]["id"],
                ref["school"]["id"],
                decision["id"],
                ref["schedule"]["id"],
                ref["account"]["id"],
                **overrides,
            )

        validate_error(
            api.create_placement(
                proposal(start_date="2026-09-01", end_date="2026-08-15"),
                COORDINATOR_HEADERS,
            ),
            ERR_INVALID_PLACEMENT_WINDOW,
            409,
        )
        validate_error(
            api.create_placement(
                proposal(start_date="2026-07-01", end_date="2027-06-15"),
                COORDINATOR_HEADERS,
            ),
            ERR_INVALID_PLACEMENT_WINDOW,
            409,
        )

        _, meta = list_rows(
            api.list_placements(
                COORDINATOR_HEADERS, {"student_id": ref["student"]["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestContractEncumbrance:
    def test_residential_placement_commits_both_day_and_night_components(self, api):
        """
        A residential contract commits instructional days at the day rate plus
        contracted nights at the residential rate, and nothing else.

        PRD: "The residential component is `contracted_residential_nights` multiplied by the schedule's `residential_rate_cents` when `placement_type` is `RESIDENTIAL`, and exactly zero when it is `DAY`."

        Design: Corner/calculations/placement_encumbrance_correct_for_residential_day_and_night_mix
        """
        ref = build_reference_data(api)
        placement = make_proposed_placement(
            api,
            ref,
            residential=True,
            placement_type="RESIDENTIAL",
            contracted_instructional_days=180,
            contracted_residential_nights=300,
        )

        contracted = validate_success(
            api.execute_contract(placement["id"], FISCAL_OFFICER_HEADERS)
        )
        assert contracted["status"] == "CONTRACTED"
        assert contracted["contract_encumbrance_cents"] == 21210000
        assert contracted["addendum_encumbrance_cents"] == 0
        assert contracted["transport_encumbrance_cents"] == 0
        assert contracted["transition_reserve_cents"] == 0
        assert contracted["encumbrance_cents"] == 21210000
        assert_placement_encumbrance_mirror(contracted)
        assert_ledger(
            read_account(api, ref["account"]["id"]),
            available=78790000,
            encumbered=21210000,
            disbursed=0,
        )

    def test_execution_beyond_the_available_authority_is_refused(self, api):
        """
        An account holding less than the computed commitment cannot underwrite it, and
        the refused execution leaves the placement proposed and the ledger flat.

        PRD: "Before that figure is booked, the account must be able to cover it: `available_cents` must be at least the computed contract encumbrance, or the request is refused with `ERR_INSUFFICIENT_FISCAL_AUTHORITY` (402) — and, per §2.10, only after every state, referential, temporal, safety and constraint check has already passed."

        Design: Corner/validations/contract_execution_beyond_available_authority_rejected
        """
        ref = build_reference_data(
            api,
            account_overrides={
                "account_code": "OOD-TIGHT-2027",
                "authorized_cents": 5000000,
            },
        )
        placement = make_proposed_placement(api, ref)

        validate_error(
            api.execute_contract(placement["id"], FISCAL_OFFICER_HEADERS),
            ERR_INSUFFICIENT_FISCAL_AUTHORITY,
            402,
        )

        after = read_placement(api, placement["id"])
        assert after["status"] == "PROPOSED"
        assert after["contract_encumbrance_cents"] == 0
        assert after["version"] == 1
        assert_ledger(
            read_account(api, ref["account"]["id"]),
            available=5000000,
            encumbered=0,
            disbursed=0,
        )

    def test_authority_exactly_equal_to_the_commitment_is_sufficient(self, api):
        """
        The fiscal comparison is inclusive, so an account holding exactly the
        commitment underwrites it and is drained to zero available cents.

        PRD: "Before that figure is booked, the account must be able to cover it: `available_cents` must be at least the computed contract encumbrance, or the request is refused with `ERR_INSUFFICIENT_FISCAL_AUTHORITY` (402) — and, per §2.10, only after every state, referential, temporal, safety and constraint check has already passed."

        Design: Corner/validations/contract_execution_succeeds_when_authority_exactly_equals_the_encumbrance
        """
        ref = build_reference_data(
            api,
            account_overrides={
                "account_code": "OOD-EXACT-2027",
                "authorized_cents": DAY_CONTRACT_ENCUMBRANCE_CENTS,
            },
        )
        placement = make_proposed_placement(api, ref)

        contracted = validate_success(
            api.execute_contract(placement["id"], FISCAL_OFFICER_HEADERS)
        )
        assert contracted["status"] == "CONTRACTED"
        assert contracted["contract_encumbrance_cents"] == DAY_CONTRACT_ENCUMBRANCE_CENTS
        assert contracted["transport_status"] == "NOT_REQUIRED"
        assert_ledger(
            read_account(api, ref["account"]["id"]),
            available=0,
            encumbered=DAY_CONTRACT_ENCUMBRANCE_CENTS,
            disbursed=0,
        )

        validate_error(
            api.execute_contract(placement["id"], FISCAL_OFFICER_HEADERS),
            ERR_INVALID_STATE_TRANSITION,
            409,
        )


class TestProposalPreconditions:
    def test_residential_placement_at_a_day_only_school_is_refused(self, api):
        """
        A school that is not residential capable cannot take a residential placement
        even when the team's decision recommended residential care.

        PRD: "Fourth, residential authorisation: a `RESIDENTIAL` placement requires the named decision's `recommended_placement_type` to be `RESIDENTIAL` **and** the named school's `residential_capable` to be true, or the refusal is `ERR_RESIDENTIAL_NOT_AUTHORIZED`."

        Design: Corner/validations/residential_placement_at_a_day_only_school_rejected
        """
        ref = build_reference_data(api, school_overrides={"residential_capable": False})
        decision = make_approved_decision(api, ref["student"]["id"], residential=True)

        validate_error(
            api.create_placement(
                f.placement_payload(
                    ref["student"]["id"],
                    ref["school"]["id"],
                    decision["id"],
                    ref["schedule"]["id"],
                    ref["account"]["id"],
                    placement_type="RESIDENTIAL",
                    contracted_residential_nights=300,
                ),
                COORDINATOR_HEADERS,
            ),
            ERR_RESIDENTIAL_NOT_AUTHORIZED,
            409,
        )

        _, meta = list_rows(
            api.list_placements(
                COORDINATOR_HEADERS, {"student_id": ref["student"]["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert_ledger(
            read_account(api, ref["account"]["id"]),
            available=100000000,
            encumbered=0,
        )

    def test_start_date_before_the_schedules_effective_from_is_refused(self, api):
        """
        A start date one month ahead of the pinned schedule's effective window fails
        rate effectivity, which is checked before the window-sanity rule.

        PRD: "Second, rate effectivity: the named schedule's `approval_state` must be `STATE_APPROVED` and the placement's `start_date` must fall inside the schedule's inclusive `effective_from` to `effective_to` window, or the proposal is refused with `ERR_RATE_SCHEDULE_NOT_EFFECTIVE` — a `DRAFT` or `SUPERSEDED` schedule can never underwrite a placement."

        Design: Corner/validations/placement_start_before_the_rate_schedule_effective_from_rejected
        """
        ref = build_reference_data(api, rate_overrides={"effective_from": "2026-10-01"})
        decision = make_approved_decision(api, ref["student"]["id"])

        validate_error(
            api.create_placement(
                f.placement_payload(
                    ref["student"]["id"],
                    ref["school"]["id"],
                    decision["id"],
                    ref["schedule"]["id"],
                    ref["account"]["id"],
                    start_date="2026-09-01",
                ),
                COORDINATOR_HEADERS,
            ),
            ERR_RATE_SCHEDULE_NOT_EFFECTIVE,
            409,
        )

        _, meta = list_rows(
            api.list_placements(
                COORDINATOR_HEADERS, {"student_id": ref["student"]["id"]}
            )
        )
        assert meta["total_count"] == 0
