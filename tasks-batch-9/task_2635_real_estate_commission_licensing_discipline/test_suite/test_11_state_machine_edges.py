"""Transitions at their edges: what a move does not do, and what the clock forbids."""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_EXAM_ATTEMPTS_EXHAUSTED,
    ERR_FIELDWORK_NOT_STARTED,
    ERR_HEARING_NOT_STARTED,
    ERR_INVALID_STATE,
    ERR_ORDER_ALREADY_VACATED,
)
from test_helpers.assertions import (
    assert_case_number,
    assert_posture,
    expected_ce_hours_required,
    expected_priority_score,
)
from test_helpers.clock import instant_plus_days
from test_helpers.constants import CLOCK_STARTUP_DEFAULT, STATUTE_PERIOD_DAYS
from test_helpers.test_users import (
    make_analyst_headers,
    make_auditor_headers,
    make_chair_headers,
    make_counsel_headers,
    make_public_headers,
    make_salesperson_headers,
    make_trustee_headers,
)

FIRM_NAME = "Harbor Realty Group"
BROKER_NAME = "Dana Broker"
LICENCE_EXPIRY = "2028-07-31T00:00:00Z"


class TestActivationDoesNotIssueTheDesignatedBroker:
    """Two moves in a fixed order, and the first one seats nobody."""

    def test_activation_moves_the_firm_and_recomputes_its_posture(self, client):
        """The firm alone advances: status, posture and version.

        The PRD says "Activation recomputes `supervision_posture` and advances
        the brokerage's `version`."

        Design: Corner/state_machines/brokerage_activation_moves_pending_to_active_and_the_self_affiliation_issues_the_broker
        """
        broker = fixtures.create_exam_passed_licensee(client, "BROKER", BROKER_NAME)
        pending = fixtures.register_brokerage(
            client, broker["id"], FIRM_NAME, trust_account_required=False
        )
        assert pending["status"] == "PENDING"
        version_before = pending["version"]

        activated = validate_success(
            client.activate_brokerage(
                pending["id"], make_analyst_headers(), {"attestation_note": "no trust account required"}
            )
        )
        assert activated["status"] == "ACTIVE"
        assert_posture(activated, "COMPLIANT")
        assert activated["version"] == version_before + 1

    def test_the_broker_is_still_exam_passed_the_instant_after_activation(self, client):
        """Activation issues nobody, so the count is still off zero.

        The PRD says "It is important to understand what activation does **not**
        do: it does not issue the designated broker's licence."

        Design: Corner/state_machines/brokerage_activation_moves_pending_to_active_and_the_self_affiliation_issues_the_broker
        """
        broker = fixtures.create_exam_passed_licensee(client, "BROKER", BROKER_NAME)
        pending = fixtures.register_brokerage(
            client, broker["id"], FIRM_NAME, trust_account_required=False
        )
        activated = fixtures.activate(client, pending["id"])

        unseated = fixtures.read_licensee(client, broker["id"])
        assert unseated["license_status"] == "EXAM_PASSED"
        assert unseated["sponsoring_brokerage_id"] is None
        assert unseated["license_issued_at"] is None
        assert activated["affiliated_licensee_count"] == 0
        assert fixtures.read_brokerage(client, pending["id"])["affiliated_licensee_count"] == 0

    def test_the_self_affiliation_issues_the_licence_and_counts_once(self, client):
        """The bootstrap affiliation stamps the term and lifts the count to one.

        The PRD says "An `EXAM_PASSED` broker becomes `ACTIVE` only by being
        affiliated, naming themselves as their own supervising broker, and that
        affiliation — not the activation — is what first raises
        `affiliated_licensee_count` above 0."

        Design: Corner/state_machines/brokerage_activation_moves_pending_to_active_and_the_self_affiliation_issues_the_broker
        """
        broker = fixtures.create_exam_passed_licensee(client, "BROKER", BROKER_NAME)
        pending = fixtures.register_brokerage(
            client, broker["id"], FIRM_NAME, trust_account_required=False
        )
        activated = fixtures.activate(client, pending["id"])

        seated = validate_success(
            client.create_affiliation(
                broker["id"],
                factories.affiliation_payload(pending["id"], broker["id"], activated["version"]),
                make_analyst_headers(),
            )
        )
        assert seated["license_status"] == "ACTIVE"
        assert seated["sponsoring_brokerage_id"] == pending["id"]
        assert seated["supervising_broker_id"] == broker["id"]
        assert seated["license_issued_at"] == CLOCK_STARTUP_DEFAULT
        assert seated["license_expires_at"] == LICENCE_EXPIRY
        assert seated["ce_period_start_on"] == "2026-08-01"

        firm = fixtures.read_brokerage(client, pending["id"])
        assert firm["affiliated_licensee_count"] == 1
        assert firm["version"] == activated["version"] + 1


HEARING_START = "2026-08-10T09:00:00Z"
HEARING_END = "2026-08-10T11:00:00Z"
CHAIR = "chair-01"


def _hearing_scheduled_for_next_week(client):
    """A misrepresentation case at probable cause with a sitting a week out."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name=FIRM_NAME,
        broker_name=BROKER_NAME,
        trust_account_required=False,
        open_escrow=False,
    )
    complaint = fixtures.complaint_at_probable_cause(
        client, firm["broker"]["id"], "MISREPRESENTATION", 1000000
    )
    hearing = fixtures.schedule_hearing(
        client, complaint["id"], CHAIR, HEARING_START, HEARING_END, "ROOM-A"
    )
    assert hearing["status"] == "SCHEDULED"
    return {"firm": firm, "complaint": complaint, "hearing": hearing}


def _convene(client, hearing_id):
    return client.hearing_disposition(
        hearing_id, factories.hearing_disposition_payload("CONVENE"), make_chair_headers(CHAIR)
    )


class TestConveningBeforeTheSlotArrives:
    """The same body, refused and then accepted, on the clock alone."""

    def test_an_early_convene_is_refused_and_leaves_no_trace(self, client):
        """Nine days early the sitting cannot open, and nothing moves.

        The PRD says "It may not be taken early: the clock must have reached
        `scheduled_start_at`, and an attempt before then is refused with
        `ERR_HEARING_NOT_STARTED`."

        Design: Corner/state_machines/hearing_convene_before_the_scheduled_start_is_rejected
        """
        world = _hearing_scheduled_for_next_week(client)

        validate_error(_convene(client, world["hearing"]["id"]), ERR_HEARING_NOT_STARTED)

        unopened = validate_success(
            client.get_hearing(world["hearing"]["id"], make_analyst_headers())
        )
        assert unopened["status"] == "SCHEDULED"
        assert unopened["convened_at"] is None
        assert fixtures.read_complaint(client, world["complaint"]["id"])["status"] == (
            "HEARING_SCHEDULED"
        )
        assert fixtures.read_licensee(client, world["firm"]["broker"]["id"])[
            "discipline_status"
        ] == "PENDING_HEARING"

    def test_convening_at_exactly_the_scheduled_start_is_allowed(self, client):
        """The boundary belongs to the sitting, not to the refusal.

        The PRD says "Convening at exactly `scheduled_start_at` is allowed."

        Design: Corner/state_machines/hearing_convene_before_the_scheduled_start_is_rejected
        """
        world = _hearing_scheduled_for_next_week(client)
        validate_error(_convene(client, world["hearing"]["id"]), ERR_HEARING_NOT_STARTED)

        fixtures.move_clock(client, HEARING_START)
        opened = validate_success(_convene(client, world["hearing"]["id"]))
        assert opened["status"] == "CONVENED"
        assert opened["convened_at"] == HEARING_START


AUDITOR = "auditor-42"
FIELDWORK_START = "2026-08-05T09:00:00Z"
FIELDWORK_END = "2026-08-05T17:00:00Z"


def _audit_scheduled_for_a_window_that_has_not_opened(client):
    """An escrow account 100,000 cents short, with fieldwork four days out."""
    firm = fixtures.bootstrap_active_brokerage(
        client, name=FIRM_NAME, broker_name=BROKER_NAME
    )
    account_id = firm["account"]["id"]
    fixtures.append_ledger_entry(
        client, account_id, "OBLIGATION_OPENED", 500000, "2026-08-01", "OBL-42"
    )
    fixtures.append_ledger_entry(
        client, account_id, "DEPOSIT", 400000, "2026-08-01", "DEP-42", cleared_date="2026-08-01"
    )
    audit = fixtures.schedule_audit(
        client,
        account_id,
        AUDITOR,
        basis="BOOK",
        as_of_date="2026-08-31",
        fieldwork_start_at=FIELDWORK_START,
        fieldwork_end_at=FIELDWORK_END,
    )
    assert audit["status"] == "SCHEDULED"
    assert audit["computed_shortage_cents"] is None
    return {"firm": firm, "account_id": account_id, "audit_id": audit["id"]}


class TestOpeningFieldworkBeforeTheWindow:
    """The shortage snapshot is frozen only by a move that succeeds."""

    def test_an_early_fieldwork_call_is_refused_and_freezes_nothing(self, client):
        """The preview computed at scheduling is still not persisted.

        The PRD says "The current instant must be at or after
        `fieldwork_start_at`, or the attempt is refused with
        `ERR_FIELDWORK_NOT_STARTED`."

        Design: Corner/state_machines/audit_fieldwork_before_the_window_start_is_rejected
        """
        world = _audit_scheduled_for_a_window_that_has_not_opened(client)

        validate_error(
            client.open_fieldwork(
                world["audit_id"], factories.fieldwork_payload(), make_auditor_headers(AUDITOR)
            ),
            ERR_FIELDWORK_NOT_STARTED,
        )
        refused = fixtures.read_audit(client, world["audit_id"])
        assert refused["status"] == "SCHEDULED"
        assert refused["computed_shortage_cents"] is None
        assert fixtures.read_trust_account(client, world["account_id"])["last_audited_at"] is None

    def test_at_exactly_the_window_start_the_book_shortage_is_frozen(self, client):
        """Five hundred thousand owed against four hundred thousand held.

        The PRD says "Opening fieldwork freezes `computed_shortage_cents` under
        the audit's declared basis and stamps `last_audited_at` on the account."

        Design: Corner/state_machines/audit_fieldwork_before_the_window_start_is_rejected
        """
        world = _audit_scheduled_for_a_window_that_has_not_opened(client)
        validate_error(
            client.open_fieldwork(
                world["audit_id"], factories.fieldwork_payload(), make_auditor_headers(AUDITOR)
            ),
            ERR_FIELDWORK_NOT_STARTED,
        )

        fixtures.move_clock(client, FIELDWORK_START)
        opened = fixtures.start_fieldwork(client, world["audit_id"], AUDITOR)
        assert opened["status"] == "FIELDWORK"
        assert opened["computed_shortage_cents"] == 100000

        account = fixtures.read_trust_account(client, world["account_id"])
        assert account["status"] == "OPEN", "fieldwork alone restricts nothing"
        assert account["last_audited_at"] == FIELDWORK_START


ORDER_INSTANT = "2026-08-05T09:00:00Z"
ORDER_END = "2026-08-05T11:00:00Z"
FINE_CENTS = 200000
VACATING_CHAIR = "chair-02"


def _vacated_fine_order(client):
    """A 200,000-cent fine order, adjudicated by chair-01 and vacated by chair-02."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name=FIRM_NAME,
        broker_name=BROKER_NAME,
        trust_account_required=False,
        open_escrow=False,
    )
    respondent_id = firm["broker"]["id"]
    complaint = fixtures.complaint_at_probable_cause(
        client, respondent_id, "MISREPRESENTATION", 1000000
    )
    decided = fixtures.issue_order_by_hearing(
        client,
        complaint["id"],
        CHAIR,
        sanction_type="FINE",
        fine_cents=FINE_CENTS,
        suspension_days=0,
        scheduled_start_at=ORDER_INSTANT,
        scheduled_end_at=ORDER_END,
    )
    order = decided["order"]
    assert order["status"] == "ISSUED"
    assert order["fine_cents"] == FINE_CENTS

    vacated = validate_success(
        client.vacate_order(
            order["id"], make_chair_headers(VACATING_CHAIR), factories.vacatur_payload()
        )
    )
    assert vacated["status"] == "VACATED"
    assert vacated["vacated_at"] == ORDER_INSTANT
    return {"respondent_id": respondent_id, "order": vacated}


class TestAVacatedOrderRefusesEverythingButAClaim:
    """The compensation chain runs once, and the terminal state holds."""

    def test_a_second_vacatur_is_refused_without_re_running_the_chain(self, client):
        """Replaying the reconsideration would claw money back twice.

        The PRD says "**Order not already vacated** —
        `ERR_ORDER_ALREADY_VACATED`, on vacatur and on fine payments. Filing a
        recovery claim is deliberately not covered: a claim against a vacated
        order is accepted and auto-denied instead."

        Design: Corner/state_machines/a_second_vacatur_and_a_fine_payment_on_a_vacated_order_are_rejected
        """
        world = _vacated_fine_order(client)

        validate_error(
            client.vacate_order(
                world["order"]["id"],
                make_chair_headers(VACATING_CHAIR),
                factories.vacatur_payload("Reconsidered a second time."),
            ),
            ERR_ORDER_ALREADY_VACATED,
        )
        unchanged = fixtures.read_sanction_order(client, world["order"]["id"])
        assert unchanged["status"] == "VACATED"
        assert unchanged["vacated_at"] == ORDER_INSTANT

    def test_a_fine_payment_on_a_vacated_order_credits_nothing(self, client):
        """The refused tender leaves both the order and the fund alone.

        The PRD says "**Order not already vacated** —
        `ERR_ORDER_ALREADY_VACATED`, on vacatur and on fine payments. Filing a
        recovery claim is deliberately not covered: a claim against a vacated
        order is accepted and auto-denied instead."

        Design: Corner/state_machines/a_second_vacatur_and_a_fine_payment_on_a_vacated_order_are_rejected
        """
        world = _vacated_fine_order(client)
        fund_before = fixtures.read_fund(client)

        validate_error(
            client.create_fine_payment(
                world["order"]["id"],
                factories.fine_payment_payload(FINE_CENTS, "2026-08-06"),
                make_analyst_headers(),
            ),
            ERR_ORDER_ALREADY_VACATED,
        )

        order = fixtures.read_sanction_order(client, world["order"]["id"])
        assert order["fine_paid_cents"] == 0
        assert order["fund_credited_cents"] == 0
        fund_after = fixtures.read_fund(client)
        assert fund_after["fine_credits_cents"] == fund_before["fine_credits_cents"] == 0
        assert fund_after["balance_cents"] == fund_before["balance_cents"]
        assert fund_after["version"] == fund_before["version"]

    def test_a_claim_against_a_vacated_order_is_accepted_and_auto_denied(self, client):
        """The one route that answers 201, and the only way to reach that reason.

        The PRD says "Otherwise it becomes `DENIED` with a `denial_reason` naming
        the defect: `ORDER_NOT_DISCIPLINARY` when the `sanction_type` is
        `REPRIMAND` or `PROBATION`, `WINDOW_CLOSED` when the 365-day window has
        elapsed, and `ORDER_VACATED` when the order has already been vacated."

        Design: Corner/state_machines/a_second_vacatur_and_a_fine_payment_on_a_vacated_order_are_rejected
        """
        world = _vacated_fine_order(client)

        claim = validate_success(
            client.create_recovery_claim(
                world["order"]["id"],
                factories.recovery_claim_payload(400000, "Ora Buyer"),
                make_trustee_headers(),
            ),
            expected_status=201,
        )
        assert claim["status"] == "DENIED"
        assert claim["denial_reason"] == "ORDER_VACATED"
        assert claim["awarded_cents"] == 0

    def test_the_respondent_keeps_the_standing_the_first_vacatur_restored(self, client):
        """A fine never touched the licence, and the replay never touched it either.

        The PRD says "The `discipline_status` returns `SANCTIONED → CLEARED` only
        when no other non-vacated order against them remains."

        Design: Corner/state_machines/a_second_vacatur_and_a_fine_payment_on_a_vacated_order_are_rejected
        """
        world = _vacated_fine_order(client)
        validate_error(
            client.vacate_order(
                world["order"]["id"], make_chair_headers(VACATING_CHAIR), factories.vacatur_payload()
            ),
            ERR_ORDER_ALREADY_VACATED,
        )

        respondent = fixtures.read_licensee(client, world["respondent_id"])
        assert respondent["license_status"] == "ACTIVE"
        assert respondent["discipline_status"] == "CLEARED"
        assert respondent["prior_sanction_count"] == 0


REPLAY_INSTANT = "2026-09-15T00:00:00Z"


def _parked_salesperson_under_a_live_firm(client):
    """Sam Sales, affiliated and then parked at the startup instant."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name=FIRM_NAME,
        broker_name=BROKER_NAME,
        trust_account_required=False,
        open_escrow=False,
    )
    salesperson = fixtures.affiliate_new_salesperson(
        client, firm["brokerage"]["id"], firm["broker"]["id"], "Sam Sales"
    )
    assert fixtures.read_brokerage(client, firm["brokerage"]["id"])[
        "affiliated_licensee_count"
    ] == 2
    parked = fixtures.go_inactive(
        client, salesperson["id"], make_salesperson_headers(salesperson["id"])
    )
    assert parked["license_status"] == "INACTIVE"
    assert parked["inactive_since"] == CLOCK_STARTUP_DEFAULT
    return {"firm": firm, "parked": parked}


class TestParkingAnAlreadyParkedLicence:
    """`GO_INACTIVE` is declared from `ACTIVE` only, so the replay is illegal."""

    def test_the_replayed_parking_is_refused_at_the_from_state_rung(self, client):
        """Six weeks later the same request has no legal origin.

        The PRD says "The target row must currently be in a state from which the
        requested transition is declared, including action-specific origins:
        verifying remediation requires `REMEDIATION_ORDERED`, executing a consent
        agreement requires `ACCEPTED`, convening requires `SCHEDULED`, and a
        manual escalation additionally requires a `remediation_round` of at least
        2, so escalating a first-round remediation order by hand answers with
        this same error."

        Design: Corner/state_machines/go_inactive_twice_is_an_invalid_transition
        """
        world = _parked_salesperson_under_a_live_firm(client)
        licensee_id = world["parked"]["id"]

        fixtures.move_clock(client, REPLAY_INSTANT)
        validate_error(
            fixtures.status_change(
                client,
                licensee_id,
                "GO_INACTIVE",
                headers=make_salesperson_headers(licensee_id),
            ),
            ERR_INVALID_STATE,
        )

    def test_the_refusal_does_not_re_stamp_the_absence_clock(self, client):
        """A second stamp would silently reset the education escalation.

        The PRD says "Parking stamps `inactive_since` with the current logical
        instant and clears both `sponsoring_brokerage_id` and
        `supervising_broker_id`."

        Design: Corner/state_machines/go_inactive_twice_is_an_invalid_transition
        """
        world = _parked_salesperson_under_a_live_firm(client)
        licensee_id = world["parked"]["id"]
        version_before = world["parked"]["version"]

        fixtures.move_clock(client, REPLAY_INSTANT)
        fixtures.status_change(
            client, licensee_id, "GO_INACTIVE", headers=make_salesperson_headers(licensee_id)
        )

        still_parked = fixtures.read_licensee(client, licensee_id)
        assert still_parked["inactive_since"] == CLOCK_STARTUP_DEFAULT
        assert still_parked["version"] == version_before
        assert still_parked["sponsoring_brokerage_id"] is None
        assert still_parked["supervising_broker_id"] is None

    def test_the_firm_counts_the_departure_exactly_once(self, client):
        """Two affiliates became one, and the refused replay leaves it there.

        The PRD says "`affiliated_licensee_count` counts licensees whose
        `sponsoring_brokerage_id` is this brokerage **and** whose
        `license_status` is `ACTIVE` — inactive, suspended and expired affiliates
        do not count."

        Design: Corner/state_machines/go_inactive_twice_is_an_invalid_transition
        """
        world = _parked_salesperson_under_a_live_firm(client)
        brokerage_id = world["firm"]["brokerage"]["id"]
        assert fixtures.read_brokerage(client, brokerage_id)["affiliated_licensee_count"] == 1

        fixtures.move_clock(client, REPLAY_INSTANT)
        fixtures.status_change(
            client,
            world["parked"]["id"],
            "GO_INACTIVE",
            headers=make_salesperson_headers(world["parked"]["id"]),
        )

        firm = fixtures.read_brokerage(client, brokerage_id)
        assert firm["affiliated_licensee_count"] == 1
        assert_posture(firm, "COMPLIANT")


FAILING_SCORES = (70, 72, 74)


def _denied_applicant(client):
    """Sam Sales, three failures deep and terminally denied."""
    applicant = fixtures.create_applicant(client, "SALESPERSON", "Sam Sales")
    seen = []
    for score in FAILING_SCORES:
        seen.append(
            validate_success(
                client.record_exam_result(
                    applicant["id"],
                    factories.exam_result_payload(score, "2026-08-01"),
                    make_analyst_headers(),
                )
            )
        )
    return {"applicant": applicant, "attempts": seen}


class TestTheFourthExaminationAttempt:
    """`DENIED` is terminal, and the cap error owns the refusal.

    The attempt cap is the only rung that can answer here, because the
    from-state ladder stands aside for this exact pair.
    """

    def test_three_failures_walk_the_applicant_into_the_terminal_state(self, client):
        """The first two leave the applicant sitting; the third denies them.

        The PRD says "A score below 75 recorded when `exam_attempt_count` stood
        at exactly 2 before the call — that is, the third attempt — moves the
        applicant to the terminal `DENIED` state with `exam_attempt_count`
        settled at 3."

        Design: Corner/state_machines/fourth_exam_attempt_on_a_denied_applicant_is_rejected_with_the_attempt_cap_error
        """
        world = _denied_applicant(client)
        first, second, third = world["attempts"]

        assert first["license_status"] == "APPLICANT"
        assert first["exam_attempt_count"] == 1
        assert second["license_status"] == "APPLICANT"
        assert second["exam_attempt_count"] == 2
        assert third["license_status"] == "DENIED"
        assert third["exam_attempt_count"] == 3
        assert third["exam_best_score"] == 74
        assert third["exam_passed_at"] is None

    def test_the_fourth_attempt_answers_with_the_attempt_cap_error(self, client):
        """Not a bare state complaint: the specific rung is reserved for this.

        The PRD says "Only a terminal `DENIED` licence can have an
        `exam_attempt_count` of 3, and this is exactly why a fourth attempt
        answers with the attempt-cap error rather than a bare state complaint —
        the from-state ladder deliberately steps aside for this case."

        Design: Corner/state_machines/fourth_exam_attempt_on_a_denied_applicant_is_rejected_with_the_attempt_cap_error
        """
        world = _denied_applicant(client)

        validate_error(
            client.record_exam_result(
                world["applicant"]["id"],
                factories.exam_result_payload(80, "2026-08-15"),
                make_analyst_headers(),
            ),
            ERR_EXAM_ATTEMPTS_EXHAUSTED,
        )

    def test_a_passing_fourth_score_cannot_resurrect_a_denied_applicant(self, client):
        """The refused attempt is not counted and the pass is not stamped.

        The PRD says "First the attempt cap: an applicant may sit the examination
        at most three times, so if `exam_attempt_count` has already reached 3 the
        result is refused with `ERR_EXAM_ATTEMPTS_EXHAUSTED`."

        Design: Corner/state_machines/fourth_exam_attempt_on_a_denied_applicant_is_rejected_with_the_attempt_cap_error
        """
        world = _denied_applicant(client)
        client.record_exam_result(
            world["applicant"]["id"],
            factories.exam_result_payload(95, "2026-08-15"),
            make_analyst_headers(),
        )

        denied = fixtures.read_licensee(client, world["applicant"]["id"])
        assert denied["license_status"] == "DENIED"
        assert denied["exam_attempt_count"] == 3
        assert denied["exam_best_score"] == 74
        assert denied["exam_passed_at"] is None


ALLEGED_LOSS_CENTS = 250000
STATUTE_DEADLINE = "2027-01-28T00:00:00Z"


def _complaint_filed_by_a_member_of_the_public(client):
    """A live firm, its self-supervising broker, and one publicly filed complaint."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name=FIRM_NAME,
        broker_name=BROKER_NAME,
        trust_account_required=False,
        open_escrow=False,
    )
    complaint = validate_success(
        client.create_complaint(
            factories.complaint_payload(
                firm["broker"]["id"],
                "AGENCY_DISCLOSURE",
                ALLEGED_LOSS_CENTS,
                "Ora Buyer",
                "undisclosed dual agency",
            ),
            make_public_headers(),
        ),
        expected_status=201,
    )
    return {"firm": firm, "complaint": complaint}


class TestComplaintIntakeRestingState:
    """One create stamps a number, a deadline and a score all at once."""

    def test_the_case_opens_in_submitted_with_every_screening_field_null(self, client):
        """The global counter starts at one and no officer is on the case yet.

        The PRD says "Intake mints a `case_number` of the form `CMP-` followed by
        a six-digit zero-padded counter that is **global across all complaints**
        and incremented on every create, so the first complaint ever filed is
        `CMP-000001`."

        Design: Corner/state_machines/complaint_starts_in_submitted_with_a_statute_deadline_and_an_intake_score
        """
        world = _complaint_filed_by_a_member_of_the_public(client)
        complaint = world["complaint"]

        assert complaint["status"] == "SUBMITTED"
        assert_case_number(complaint["case_number"])
        assert complaint["case_number"] == "CMP-000001"
        assert complaint["amendment_count"] == 0
        assert complaint["screener_user_id"] is None
        assert complaint["investigator_user_id"] is None
        assert complaint["source_audit_id"] is None

    def test_the_limitation_deadline_is_a_hundred_and_eighty_days_out(self, client):
        """Filed at the startup instant, barred a hundred and eighty days later.

        The PRD says "The complaint opens in `SUBMITTED` with `filed_at` stamped
        at the current logical instant and `statute_deadline_at` set to that
        instant plus a 180-day limitation period, expressed as 180 multiples of
        86,400 seconds."

        Design: Corner/state_machines/complaint_starts_in_submitted_with_a_statute_deadline_and_an_intake_score
        """
        world = _complaint_filed_by_a_member_of_the_public(client)
        complaint = world["complaint"]

        assert complaint["filed_at"] == CLOCK_STARTUP_DEFAULT
        assert complaint["statute_deadline_at"] == STATUTE_DEADLINE
        assert complaint["statute_deadline_at"] == instant_plus_days(
            CLOCK_STARTUP_DEFAULT, STATUTE_PERIOD_DAYS
        )

    def test_the_sponsorship_is_snapshotted_and_the_score_omits_the_later_terms(self, client):
        """Base thirty-five plus two harm points, with no prior and no bump.

        The PRD says "While the complaint is still `SUBMITTED`, the **intake
        variant** applies: the score is the base plus the harm term, capped at 100
        points in total, with the prior and posture terms omitted entirely because
        the commission has not yet verified the respondent's history."

        Design: Corner/state_machines/complaint_starts_in_submitted_with_a_statute_deadline_and_an_intake_score
        """
        world = _complaint_filed_by_a_member_of_the_public(client)
        complaint = world["complaint"]

        assert complaint["respondent_brokerage_id"] == world["firm"]["brokerage"]["id"]
        assert complaint["priority_score"] == 37
        assert complaint["priority_score"] == expected_priority_score(
            "AGENCY_DISCLOSURE", ALLEGED_LOSS_CENTS
        )
        assert fixtures.read_licensee(client, world["firm"]["broker"]["id"])[
            "discipline_status"
        ] == "NONE", "intake alone does not open an investigation"


INVESTIGATOR = "counsel-05"


def _salesperson_under_investigation(client):
    """Sam Sales `ACTIVE` under Dana, with a commission dispute in investigation."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name=FIRM_NAME,
        broker_name=BROKER_NAME,
        trust_account_required=False,
        open_escrow=False,
    )
    salesperson = fixtures.affiliate_new_salesperson(
        client, firm["brokerage"]["id"], firm["broker"]["id"], "Sam Sales"
    )
    complaint = fixtures.file_complaint(
        client, salesperson["id"], "COMMISSION_DISPUTE", 400000, "Ora Buyer"
    )
    opened = fixtures.dispose_complaint(
        client, complaint["id"], "INVESTIGATE", counsel_user_id=INVESTIGATOR
    )
    return {"firm": firm, "salesperson": salesperson, "complaint": opened}


class TestTheTwoLicenceDimensionsMoveIndependently:
    """One row, two machines: discipline advances while the licence holds."""

    def test_opening_an_investigation_leaves_the_licence_active(self, client):
        """The screener and the investigator are the same acting counsel.

        The PRD says "A licensee's `discipline_status` evolves entirely
        independently of their `license_status`, driven by the complaints and
        orders against them."

        Design: Corner/state_machines/discipline_status_advances_while_license_status_holds_and_blocks_inactivation
        """
        world = _salesperson_under_investigation(client)

        assert world["complaint"]["status"] == "INVESTIGATION"
        assert world["complaint"]["investigator_user_id"] == INVESTIGATOR
        assert world["complaint"]["screener_user_id"] == INVESTIGATOR

        under_scrutiny = fixtures.read_licensee(client, world["salesperson"]["id"])
        assert under_scrutiny["discipline_status"] == "UNDER_INVESTIGATION"
        assert under_scrutiny["license_status"] == "ACTIVE"
        assert under_scrutiny["inactive_since"] is None

    def test_closing_without_action_returns_the_discipline_dimension_to_cleared(self, client):
        """The investigation exit clears the person without moving the licence.

        The PRD says "It returns from `UNDER_INVESTIGATION` to `CLEARED` when a
        complaint is dismissed or closed without action and no other open
        complaint remains, and from `SANCTIONED` to `CLEARED` when the last
        non-vacated order against them is vacated — precisely, when the count of
        orders naming them whose `status` is `ISSUED`, `IN_DEFAULT` or
        `SATISFIED` reaches zero."

        Design: Corner/state_machines/discipline_status_advances_while_license_status_holds_and_blocks_inactivation
        """
        world = _salesperson_under_investigation(client)

        closed = fixtures.dispose_complaint(
            client, world["complaint"]["id"], "CLOSE_NO_ACTION", counsel_user_id=INVESTIGATOR
        )
        assert closed["status"] == "CLOSED_NO_ACTION"

        cleared = fixtures.read_licensee(client, world["salesperson"]["id"])
        assert cleared["discipline_status"] == "CLEARED"
        assert cleared["license_status"] == "ACTIVE"

    def test_the_cleared_licensee_can_then_park_the_licence(self, client):
        """The licence machine was never blocked from its own legal move.

        The PRD says "With `action` set to `GO_INACTIVE`, an `ACTIVE` licence is
        parked and the licensee moves `ACTIVE → INACTIVE`."

        Design: Corner/state_machines/discipline_status_advances_while_license_status_holds_and_blocks_inactivation
        """
        world = _salesperson_under_investigation(client)
        licensee_id = world["salesperson"]["id"]
        fixtures.dispose_complaint(
            client, world["complaint"]["id"], "CLOSE_NO_ACTION", counsel_user_id=INVESTIGATOR
        )

        parked = validate_success(
            fixtures.status_change(
                client, licensee_id, "GO_INACTIVE", headers=make_salesperson_headers(licensee_id)
            )
        )
        assert parked["license_status"] == "INACTIVE"
        assert parked["inactive_since"] == CLOCK_STARTUP_DEFAULT
        assert parked["discipline_status"] == "CLEARED"

        firm = fixtures.read_brokerage(client, world["firm"]["brokerage"]["id"])
        assert firm["affiliated_licensee_count"] == 1
        assert_posture(firm, "COMPLIANT")


TERM_EXPIRY_SWEEP_INSTANT = "2028-08-01T00:00:00Z"
SWEEP_COUNTERS = (
    "expired_licensee_count",
    "escalated_audit_count",
    "defaulted_order_count",
    "restored_licensee_count",
    "suspended_provider_count",
)


def _register_two_years_past_the_broker_s_term(client):
    """Dana `ACTIVE` and Sam `INACTIVE`, read at an instant past both terms."""
    world = _parked_salesperson_under_a_live_firm(client)
    broker = fixtures.read_licensee(client, world["firm"]["broker"]["id"])
    assert broker["license_status"] == "ACTIVE"
    assert broker["license_expires_at"] == LICENCE_EXPIRY
    fixtures.move_clock(client, TERM_EXPIRY_SWEEP_INSTANT)
    return world


class TestTheSweepExpiresOnlyActiveLicences:
    """Step one is conditional on the from-state as well as on the clock."""

    def test_the_first_sweep_expires_the_broker_and_stamps_the_absence(self, client):
        """Two years and a day on, the term has run out and the sweep says so.

        The PRD says "Every licensee whose `license_status` is `ACTIVE` and whose
        `license_expires_at` is at or before the current instant moves `ACTIVE →
        EXPIRED`."

        Design: Corner/state_machines/compliance_sweep_expires_only_active_licences_past_their_term
        """
        world = _register_two_years_past_the_broker_s_term(client)

        report = fixtures.run_sweep(client)
        assert report["expired_licensee_count"] == 1

        expired = fixtures.read_licensee(client, world["firm"]["broker"]["id"])
        assert expired["license_status"] == "EXPIRED"
        assert expired["inactive_since"] == TERM_EXPIRY_SWEEP_INSTANT
        assert expired["sponsoring_brokerage_id"] is None
        assert expired["supervising_broker_id"] is None

    def test_an_already_parked_licence_is_not_swept_and_not_re_stamped(self, client):
        """Sam's term ran out too, but step one has no origin to move from.

        The PRD says "Every licensee whose `license_status` is `ACTIVE` and whose
        `license_expires_at` is at or before the current instant moves `ACTIVE →
        EXPIRED`."

        Design: Corner/state_machines/compliance_sweep_expires_only_active_licences_past_their_term
        """
        world = _register_two_years_past_the_broker_s_term(client)
        fixtures.run_sweep(client)

        untouched = fixtures.read_licensee(client, world["parked"]["id"])
        assert untouched["license_status"] == "INACTIVE"
        assert untouched["inactive_since"] == CLOCK_STARTUP_DEFAULT

    def test_the_expiring_designated_broker_freezes_the_firm_without_closing_it(self, client):
        """The first matching tier wins, so the posture skips two rungs.

        The PRD says "The consequence for the firm can be severe: when the
        expiring licensee was the designated broker, the recomputed posture of
        that firm lands on `FROZEN`."

        Design: Corner/state_machines/compliance_sweep_expires_only_active_licences_past_their_term
        """
        world = _register_two_years_past_the_broker_s_term(client)
        brokerage_id = world["firm"]["brokerage"]["id"]
        assert_posture(fixtures.read_brokerage(client, brokerage_id), "COMPLIANT")

        fixtures.run_sweep(client)

        firm = fixtures.read_brokerage(client, brokerage_id)
        assert_posture(firm, "FROZEN")
        assert firm["status"] == "ACTIVE", "an expiry does not close the brokerage"
        assert firm["affiliated_licensee_count"] == 0
        assert firm["new_affiliation_blocked"] is True

    def test_a_second_sweep_at_the_same_instant_reports_five_zeroes(self, client):
        """Every qualifying row has already left its qualifying state.

        The PRD says "It is **idempotent with respect to the clock**: running it
        twice at the same logical instant produces the same register, and the
        second run reports all five counters as 0 because every qualifying row has
        already moved out of its qualifying state."

        Design: Corner/state_machines/compliance_sweep_expires_only_active_licences_past_their_term
        """
        world = _register_two_years_past_the_broker_s_term(client)
        fixtures.run_sweep(client)
        after_first = fixtures.read_licensee(client, world["firm"]["broker"]["id"])

        second = fixtures.run_sweep(client)
        assert [second[counter] for counter in SWEEP_COUNTERS] == [0, 0, 0, 0, 0]

        after_second = fixtures.read_licensee(client, world["firm"]["broker"]["id"])
        assert after_second["inactive_since"] == TERM_EXPIRY_SWEEP_INSTANT
        assert after_second["version"] == after_first["version"]
        assert after_second["license_status"] == "EXPIRED"

    def test_the_expired_licence_starts_its_absence_at_the_base_requirement(self, client):
        """Zero full thirty-day months of absence means zero escalation blocks.

        The PRD says "take the elapsed time from `inactive_since` to the current
        logical instant, divide it by thirty days and truncate downward to get the
        number of full thirty-day months of absence, divide that count by six and
        truncate downward again to get the number of completed six-month blocks,
        add 3 hours for each such block on top of the 12-hour base, and finally
        cap the result at 36 hours."

        Design: Corner/state_machines/compliance_sweep_expires_only_active_licences_past_their_term
        """
        world = _register_two_years_past_the_broker_s_term(client)
        fixtures.run_sweep(client)

        expired = fixtures.read_licensee(client, world["firm"]["broker"]["id"])
        assert expired["license_status"] == "EXPIRED"
        assert expired["ce_hours_required"] == 12
        assert expired["ce_hours_required"] == expected_ce_hours_required("EXPIRED", 0)
