"""The edges a housing lifecycle refuses, and the side effects a fork carries.

Triage sends a complaint down one of two branches whose cross-entity effects are
deliberately unequal, and only one of them restores a spent appeal. The
transitions that do not exist — confirming a booking that has no manifest,
countersigning an already executed contract, adjudicating a closed complaint —
are refused outright and leave no partial mutation behind. Closing the housing
window and upholding an escalated complaint each drive a multi-link cascade whose
last link lands on a registration.
"""

from test_helpers import (
    CLOSED_WITHOUT_DECISION,
    EXCEPTION_REVIEWER_2_HEADERS,
    HOUSING_MANAGER_HEADERS,
    HOUSING_MANAGER_ID,
    RIGHTS_HOLDER_HEADERS,
    RIGHTS_HOLDER_ID,
    SYSTEM_AUTO,
    ApiErrorId,
    ComplaintCategory,
    ComplaintOutcome,
    ComplaintRoute,
    ExceptionReasonCode,
    NegotiationAction,
    RemedyType,
    ReviewAction,
    TeamAction,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_error,
    validate_success,
)

HM = HOUSING_MANAGER_HEADERS
RIGHTS = RIGHTS_HOLDER_HEADERS


def _filed_complaint_env(api) -> fx.Env:
    """A `FILED` complaint naming all three subjects: the registration, a
    `SUBMITTED` exception request on it and a `DRAFT` booking."""
    env = fx.draft_booking_env(api)
    fx.add_exception_request(env)
    fx.add_complaint(
        env,
        registration_id=env.registration_id,
        cited_exception_request_id=env.exception_request["id"],
        affected_booking_id=env.booking_id,
    )
    return env


def _investigating_complaint_env(api) -> fx.Env:
    """A complaint routed `INVESTIGATE`, naming only the booking it disputes."""
    env = fx.draft_booking_env(api)
    fx.add_complaint(env, affected_booking_id=env.booking_id)
    fx.triage_complaint(env, ComplaintRoute.INVESTIGATE.value)
    return env


def _spent_appeal_env(api) -> fx.Env:
    """An exception request denied, appealed once and denied again by a second
    reviewer, so it sits at `DENIED` with its single appeal spent; plus a `FILED`
    complaint citing it."""
    env = fx.denied_exception_env(api)
    get_success_data(
        api.team_action_exception_request(
            env.exception_request["id"],
            f.team_action_payload(TeamAction.APPEAL.value),
            env.team_headers,
        )
    )
    fx.review_exception(
        env,
        ReviewAction.DENY.value,
        headers=EXCEPTION_REVIEWER_2_HEADERS,
        decision_note="the appeal adds nothing new",
    )
    fx.add_complaint(
        env,
        registration_id=env.registration_id,
        cited_exception_request_id=env.exception_request["id"],
        category=ComplaintCategory.POLICY_FAIRNESS.value,
    )
    return env


def _fee_waiver_upheld_env(api) -> fx.Env:
    """A four-room stay confirmed and then cancelled forty days out, with an
    investigated complaint already upheld against it for a fee waiver."""
    env = fx.confirmed_booking_env(api)
    env.booking = get_success_data(
        api.cancel_booking(env.booking_id, f.cancel_payload(), HM)
    )
    fx.add_complaint(env, affected_booking_id=env.booking_id)
    fx.triage_complaint(env, ComplaintRoute.INVESTIGATE.value)
    fx.adjudicate_complaint(
        env,
        ComplaintOutcome.UPHOLD.value,
        RemedyType.FEE_WAIVER.value,
        remedy_amount_cents=60000,
    )
    return env


def _escalated_policy_complaint_env(api) -> fx.Env:
    """A registration with no bookings at all, a denied four-room hardship
    request, the window closed behind it, and an escalated complaint citing that
    denial."""
    env = fx.registered_team_env(api)
    fx.add_exception_request(
        env,
        reason_code=ExceptionReasonCode.FINANCIAL_HARDSHIP.value,
        requested_rooms_exempt=4,
        justification="the travelling families cannot fund four hotel rooms",
    )
    fx.review_exception(env, ReviewAction.START_REVIEW.value)
    fx.review_exception(
        env, ReviewAction.DENY.value, decision_note="hardship not documented"
    )
    fx.close_booking_window(env)
    fx.add_complaint(
        env,
        registration_id=env.registration_id,
        cited_exception_request_id=env.exception_request["id"],
        category=ComplaintCategory.POLICY_FAIRNESS.value,
    )
    fx.triage_complaint(env, ComplaintRoute.ESCALATE.value)
    return env


class TestComplaintTriageFork:
    """The two triage branches, and the cross-entity effect only one of them
    carries."""

    def test_investigating_a_complaint_leaves_the_cited_exemption_untouched(self, api):
        """Routing a complaint to investigation records the route and the
        triaging operator, and does not disturb the exception request the
        complaint cites.

        PRD §3.9: "A `HousingManager` supplies a `route` of either `INVESTIGATE`,
        moving the complaint `FILED → INVESTIGATING`, or `ESCALATE`, moving it
        `FILED → ESCALATED`."

        PRD §3.9: "Both require the complaint to be at `FILED` and the
        tournament's `posture` to be anything other than `SETTLED`, and both
        record the chosen `route` and set `triaged_by_user_id` to the acting
        `X-User-ID`."

        PRD §3.9: "The `INVESTIGATE` branch has no cross-entity effect at all."

        PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601
        UTC timestamp in the same format, and `version`, an integer that starts
        at 1 when the row is created and is incremented by exactly 1 on every
        mutation of that row."

        Design: Corner/state_machines/complaint_triage_investigate_transition
        """
        env = _filed_complaint_env(api)
        assert env.complaint["status"] == "FILED"
        assert env.complaint["route"] is None

        complaint = validate_success(
            api.triage_complaint(
                env.complaint["id"],
                f.triage_payload(ComplaintRoute.INVESTIGATE.value),
                HM,
            )
        )

        assert complaint["status"] == "INVESTIGATING"
        assert complaint["route"] == "INVESTIGATE"
        assert complaint["triaged_by_user_id"] == HOUSING_MANAGER_ID
        assert complaint["adjudicated_by_user_id"] is None
        assert complaint["version"] == 2
        request = env.refresh_exception_request()
        assert request["status"] == "SUBMITTED"
        assert request["appeal_count"] == 0
        assert request["version"] == 1

    def test_escalating_a_complaint_resets_the_spent_appeal_counter(self, api):
        """Escalating a complaint that cites a denied exemption hands the team
        back the appeal it has already used up.

        PRD §3.9: "The `ESCALATE` branch carries one: when the complaint names a
        `cited_exception_request_id` and that exception request's `status` is
        `DENIED`, the request's `appeal_count` is reset to 0 and its `version`
        incremented by 1, restoring one appeal cycle to a team whose single
        appeal has already been spent."

        Design: Corner/state_machines/escalate_branch_restores_one_appeal_cycle
        """
        env = _spent_appeal_env(api)
        assert env.exception_request["status"] == "DENIED"
        assert env.exception_request["appeal_count"] == 1

        complaint = validate_success(
            api.triage_complaint(
                env.complaint["id"], f.triage_payload(ComplaintRoute.ESCALATE.value), HM
            )
        )

        assert complaint["status"] == "ESCALATED"
        assert complaint["route"] == "ESCALATE"
        request = env.refresh_exception_request()
        assert request["appeal_count"] == 0
        assert request["status"] == "DENIED"

    def test_the_restored_cycle_lets_the_team_appeal_a_second_time(self, api):
        """The appeal refused for the cap before escalation is accepted after
        it, so the reset is a behavioural restoration and not just a field.

        PRD §3.6: "That loop is capped at one appeal: an `APPEAL` against a
        request whose `appeal_count` already stands at 1 is rejected with
        `ERR_APPEAL_LIMIT_REACHED`, which is what makes the cycle terminate."

        PRD §3.6: "The **appeal loop** lets a team contest a denial: an `APPEAL`
        action moves the request `DENIED → UNDER_REVIEW` and increments both
        `appeal_count` and `review_round` by 1."

        Design: Corner/state_machines/escalate_branch_restores_one_appeal_cycle
        """
        env = _spent_appeal_env(api)
        request_id = env.exception_request["id"]

        refused = api.team_action_exception_request(
            request_id, f.team_action_payload(TeamAction.APPEAL.value), env.team_headers
        )
        validate_error(
            refused, ApiErrorId.ERR_APPEAL_LIMIT_REACHED.value, expected_status=409
        )

        fx.triage_complaint(env, ComplaintRoute.ESCALATE.value)
        request = validate_success(
            api.team_action_exception_request(
                request_id,
                f.team_action_payload(TeamAction.APPEAL.value),
                env.team_headers,
            )
        )

        assert request["status"] == "UNDER_REVIEW"
        assert request["appeal_count"] == 1


class TestAdjudicationVocabularyAndTerminality:
    """The two join edges into `UPHELD` accept different remedies, and neither
    edge may be walked twice."""

    def test_an_investigated_complaint_refuses_a_rate_adjustment_remedy(self, api):
        """A rate adjustment belongs to the escalation branch, so offering it on
        an investigated complaint is refused and the complaint keeps sitting at
        `INVESTIGATING` with no remedy recorded.

        PRD §3.9: "A complaint routed `INVESTIGATE` may only be resolved with
        `NONE` or `FEE_WAIVER` — the narrow, money-only vocabulary."

        PRD §3.9: "A remedy outside the branch's vocabulary is rejected with
        `ERR_REMEDY_NOT_AVAILABLE_ON_ROUTE`."

        PRD §3.9: "This is why triage matters: only escalation unlocks a rate
        adjustment or a policy exemption."

        Design: Corner/state_machines/investigate_branch_rejects_rate_adjustment_remedy
        """
        env = _investigating_complaint_env(api)
        assert env.complaint["status"] == "INVESTIGATING"

        response = api.adjudicate_complaint(
            env.complaint["id"],
            f.adjudicate_payload(
                ComplaintOutcome.UPHOLD.value, RemedyType.RATE_ADJUSTMENT.value
            ),
            RIGHTS,
        )

        validate_error(
            response,
            ApiErrorId.ERR_REMEDY_NOT_AVAILABLE_ON_ROUTE.value,
            expected_status=422,
        )
        complaint = env.refresh_complaint()
        assert complaint["status"] == "INVESTIGATING"
        assert complaint["remedy_type"] == "NONE"
        assert complaint["remedy_credit_cents"] == 0
        assert complaint["adjudicated_by_user_id"] is None
        assert complaint["version"] == 2

    def test_a_second_adjudication_of_an_upheld_complaint_is_refused(self, api):
        """`UPHELD` is the end of the line: a later dismissal is refused and the
        fee waiver already granted is neither erased nor credited twice.

        PRD §3.9: "Both `UPHELD` and `DISMISSED` are terminal."

        PRD §2.11: "The target resource's current state is a declared source
        state of the requested transition — otherwise `ERR_INVALID_STATE`."

        PRD §3.9: "On the `INVESTIGATING → UPHELD` transition, only a
        `FEE_WAIVER` moves money: when `remedy_type` is `FEE_WAIVER` and
        `affected_booking_id` is non-null, the affected booking's
        `penalty_credit_cents` is increased by `remedy_credit_cents` and that
        booking's `version` is incremented by 1."

        PRD §3.5: "Note that `penalty_credit_cents`, the relief a complaint
        remedy may grant, is tracked separately and **never** reduces
        `penalty_cents` itself; the two figures coexist on the booking so that
        the charge and the relief remain independently auditable."

        Design: Corner/state_machines/adjudicate_on_upheld_complaint_rejected
        """
        env = _fee_waiver_upheld_env(api)
        assert env.complaint["status"] == "UPHELD"
        assert env.complaint["remedy_credit_cents"] == 44700

        response = api.adjudicate_complaint(
            env.complaint["id"],
            f.adjudicate_payload(
                ComplaintOutcome.DISMISS.value, RemedyType.NONE.value
            ),
            RIGHTS,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
        complaint = env.refresh_complaint()
        assert complaint["status"] == "UPHELD"
        assert complaint["remedy_type"] == "FEE_WAIVER"
        assert complaint["remedy_credit_cents"] == 44700
        booking = env.refresh_booking()
        assert booking["penalty_cents"] == 44700
        assert booking["penalty_credit_cents"] == 44700


class TestAbsentEdgesLeaveNoTrace:
    """A transition with no such source state is refused, and its cascade never
    starts."""

    def test_confirming_a_booking_that_has_no_rooming_list_is_refused(self, api):
        """`DRAFT` is not a source state of confirmation, so the block's
        occupancy counters and the team's compliance reading both stay where
        booking creation left them.

        PRD §3.4: "It moves a booking `ROOMING_LIST_SUBMITTED → CONFIRMED`, and
        it requires the governing tournament to be `OPEN`, the owning contract
        to be `EXECUTED`, and the block's `status` to still be `OPEN` or
        `RESTRICTED`."

        PRD §2.11: "The target resource's current state is a declared source
        state of the requested transition — otherwise `ERR_INVALID_STATE`."

        PRD §3.4: "Creation alone leaves the block's `rooms_committed`,
        `rooms_available` and `utilization_pct` **untouched** — confirmation is
        the only trigger that moves them."

        PRD §3.3: "The rest of the registration record is initialised to
        `exempt_rooms_granted` of 0, `effective_required_rooms` equal to
        `minimum_rooms_for_compliance`, `committed_rooms` of 0 and `status`
        `PENDING_HOUSING`."

        Design: Corner/state_machines/booking_confirm_from_draft_rejected
        """
        env = fx.draft_booking_env(api)
        assert env.booking["booking_status"] == "DRAFT"

        response = api.confirm_booking(env.booking_id, HM)

        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
        booking = env.refresh_booking()
        assert booking["booking_status"] == "DRAFT"
        assert booking["version"] == 1
        block = env.refresh_block()
        assert block["rooms_committed"] == 0
        assert block["rooms_available"] == 20
        assert block["utilization_pct"] == 0.0
        assert block["status"] == "OPEN"
        assert env.refresh_registration()["status"] == "PENDING_HOUSING"

    def test_countersigning_an_executed_contract_twice_is_refused(self, api):
        """A replayed countersignature is refused rather than absorbed, so the
        event's executed-contract counter is not lifted a second time.

        PRD §3.2: "A `COUNTERSIGN` action moves the contract `NEGOTIATING →
        EXECUTED`, again requiring the tournament to be `OPEN`; it records
        `countersigned_by_hotel_id` as the acting `X-User-ID`, then recomputes
        the tournament's `executed_contract_count` and `sold_out_contract_count`
        and re-derives its `housing_pressure`."

        PRD §2.11: "The target resource's current state is a declared source
        state of the requested transition — otherwise `ERR_INVALID_STATE`."

        PRD §3.2: "A tournament's `housing_pressure` then aggregates upward:
        `executed_contract_count` is the number of its contracts whose `status`
        is `EXECUTED` or `CLOSED`, and `sold_out_contract_count` is the number of
        those same contracts whose `block_posture` is `SOLD_OUT`."

        PRD §3.2: "`housing_pressure` reads `CONSTRAINED` when
        `executed_contract_count` is at least 1 and `sold_out_contract_count`
        equals `executed_contract_count`; in every other case, including the case
        of no executed contracts at all, it reads `NORMAL`."

        Design: Corner/state_machines/second_countersign_rejected
        """
        env = fx.executed_contract_env(api)
        assert env.contract["status"] == "EXECUTED"

        response = api.negotiate_contract(
            env.contract_id,
            f.negotiation_payload(NegotiationAction.COUNTERSIGN.value),
            env.hotel_headers,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
        contract = env.refresh_contract()
        assert contract["status"] == "EXECUTED"
        assert contract["revision_round"] == 0
        assert contract["countersigned_by_hotel_id"] == env.hotel_id
        tournament = env.refresh_tournament()
        assert tournament["executed_contract_count"] == 1
        assert tournament["sold_out_contract_count"] == 0
        assert tournament["housing_pressure"] == "NORMAL"


class TestCloseWindowCascade:
    """Closing the housing window finalises compliance and then disposes of the
    exemptions that were still in flight."""

    def test_closing_the_window_makes_an_unhoused_team_non_compliant(self, api):
        """A team that never booked lands on `NON_COMPLIANT` once the window
        shuts, while a block whose release deadline is still ahead is left open.

        PRD §3.7: "A `HousingManager` moves the tournament `OPEN →
        BOOKING_CLOSED`, which requires that at least one hotel contract of the
        event has reached `EXECUTED` or `CLOSED` — an event with no signed
        inventory has no housing program to close."

        PRD §3.7: "The first link re-evaluates every registration of the event
        whose `status` is `PENDING_HOUSING` against the compliance rules of §3.3;
        because the tournament's `posture` is no longer `OPEN`, any registration
        whose `committed_rooms` falls short of its `effective_required_rooms` now
        lands on `NON_COMPLIANT` rather than staying pending."

        PRD §3.7: "Blocks whose `release_deadline` still lies in the future are
        left alone and must be released explicitly later."

        Design: Corner/state_machines/cascade_close_denies_open_exception_requests
        """
        env = fx.exception_request_env(api)
        assert env.refresh_registration()["status"] == "PENDING_HOUSING"

        tournament = validate_success(api.close_booking(env.tournament_id, HM))

        assert tournament["posture"] == "BOOKING_CLOSED"
        registration = env.refresh_registration()
        assert registration["status"] == "NON_COMPLIANT"
        assert registration["committed_rooms"] == 0
        assert env.refresh_block()["status"] == "OPEN"

    def test_the_close_denies_the_still_open_exemption_without_shrinking_the_requirement(
        self, api
    ):
        """The undecided request is denied by the platform itself with the pinned
        note, and because a denied request grants nothing the team's requirement
        stays at four rooms.

        PRD §3.7: "The second link, caused by the first, deals with the exception
        requests of exactly those registrations that just became `NON_COMPLIANT`:
        every such request sitting at `SUBMITTED`, `UNDER_REVIEW` or
        `INFO_REQUESTED` is moved to `DENIED` by the system, with
        `decided_by_user_id` set to the literal `SYSTEM_AUTO` and `decision_note`
        set to the literal `closed without decision`."

        PRD §3.7: "The third link, caused by the second, recomputes each touched
        registration's `exempt_rooms_granted` and `effective_required_rooms` and
        refreshes its `compliance_evaluated_at`, since denying a pending request
        changes the inputs the second link's own outcome was derived from."

        PRD §3.3: "First, `exempt_rooms_granted` becomes the sum of
        `approved_rooms_exempt` across the registration's exception requests
        whose `status` is `APPROVED`; requests sitting at `SUBMITTED`,
        `UNDER_REVIEW`, `INFO_REQUESTED` or `DENIED` contribute nothing."

        Design: Corner/state_machines/cascade_close_denies_open_exception_requests
        """
        env = fx.exception_request_env(api)
        assert env.exception_request["status"] == "SUBMITTED"

        validate_success(api.close_booking(env.tournament_id, HM))

        request = env.refresh_exception_request()
        assert request["status"] == "DENIED"
        assert request["decided_by_user_id"] == SYSTEM_AUTO
        assert request["decision_note"] == CLOSED_WITHOUT_DECISION
        assert request["approved_rooms_exempt"] == 0
        registration = env.refresh_registration()
        assert registration["exempt_rooms_granted"] == 0
        assert registration["effective_required_rooms"] == 4


class TestPolicyExemptionRemedyCascade:
    """Upholding an escalated complaint with a policy exemption revives the
    denial it cites and excuses the team."""

    def test_the_remedy_revives_the_denied_request_and_excuses_the_team(self, api):
        """The cited denial is reopened as an approval for its full requested
        rooms, which takes the registration's requirement to zero and moves it
        from `NON_COMPLIANT` to `EXCEPTION_GRANTED` without a single booked room.

        PRD §3.9: "The escalated branch additionally carries the three-link
        remedy chain, which fires only when `remedy_type` is `POLICY_EXEMPTION`,
        the complaint names a `cited_exception_request_id`, and that request's
        `status` is `DENIED`: the first link moves that request `DENIED →
        APPROVED` with `approved_rooms_exempt` set to its full
        `requested_rooms_exempt` and `decided_by_user_id` set to the literal
        `SYSTEM_AUTO`; the second link, caused by the first, recomputes that
        request's registration's `exempt_rooms_granted` and
        `effective_required_rooms`; and the third link, caused by the second,
        re-derives that registration's `status`, which may move `NON_COMPLIANT →
        EXCEPTION_GRANTED`."

        PRD §3.3: "Otherwise, if `effective_required_rooms` has fallen to 0
        **and** `exempt_rooms_granted` is at least 1, the registration is
        `EXCEPTION_GRANTED`, recording that it was excused rather than that it
        complied."

        Design: Corner/state_machines/cascade_remedy_policy_exemption_only_when_request_denied
        """
        env = _escalated_policy_complaint_env(api)
        assert env.complaint["status"] == "ESCALATED"
        assert env.refresh_registration()["status"] == "NON_COMPLIANT"

        validate_success(
            api.adjudicate_complaint(
                env.complaint["id"],
                f.adjudicate_payload(
                    ComplaintOutcome.UPHOLD.value, RemedyType.POLICY_EXEMPTION.value
                ),
                RIGHTS,
            )
        )

        request = env.refresh_exception_request()
        assert request["status"] == "APPROVED"
        assert request["approved_rooms_exempt"] == 4
        assert request["decided_by_user_id"] == SYSTEM_AUTO
        registration = env.refresh_registration()
        assert registration["exempt_rooms_granted"] == 4
        assert registration["effective_required_rooms"] == 0
        assert registration["committed_rooms"] == 0
        assert registration["status"] == "EXCEPTION_GRANTED"

    def test_a_policy_exemption_grants_policy_relief_and_no_money(self, api):
        """The complaint is upheld with the exemption recorded against the
        adjudicating rights holder, yet the credit it carries is zero.

        PRD §3.9: "Upholding a complaint sets `remedy_type` from the payload,
        computes `remedy_credit_cents`, and sets `adjudicated_by_user_id` to the
        acting `X-User-ID`."

        PRD §3.9: "A `POLICY_EXEMPTION` credits 0, because its relief is policy
        relief rather than money."

        Design: Corner/state_machines/cascade_remedy_policy_exemption_only_when_request_denied
        """
        env = _escalated_policy_complaint_env(api)

        complaint = validate_success(
            api.adjudicate_complaint(
                env.complaint["id"],
                f.adjudicate_payload(
                    ComplaintOutcome.UPHOLD.value, RemedyType.POLICY_EXEMPTION.value
                ),
                RIGHTS,
            )
        )

        assert complaint["status"] == "UPHELD"
        assert complaint["remedy_type"] == "POLICY_EXEMPTION"
        assert complaint["remedy_credit_cents"] == 0
        assert complaint["adjudicated_by_user_id"] == RIGHTS_HOLDER_ID
