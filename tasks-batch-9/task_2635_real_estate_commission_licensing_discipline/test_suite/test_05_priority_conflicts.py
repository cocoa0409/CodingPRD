"""Requests that break two rules at once, where only the ladder decides."""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import factories, fixtures
from test_helpers.assertions import assert_posture, expected_assessment_cents
from test_helpers.test_users import make_analyst_headers, make_counsel_headers

AUDITOR = "auditor-31"
AS_OF_DATE = "2026-08-31"
FIELDWORK_START = "2026-08-01T00:00:00Z"
FIELDWORK_END = "2026-08-01T16:00:00Z"


def _restricted_firm_with_a_salesperson_and_an_applicant(client):
    """A firm driven to `RESTRICTED`, plus a nominee who is only a salesperson."""
    firm = fixtures.bootstrap_active_brokerage(
        client, name="Harbor Realty Group", broker_name="Dana Broker"
    )
    brokerage_id = firm["brokerage"]["id"]
    account_id = firm["account"]["id"]
    salesperson = fixtures.affiliate_new_salesperson(
        client, brokerage_id, firm["broker"]["id"], "Sam Sales"
    )
    applicant = fixtures.create_exam_passed_licensee(client, "SALESPERSON", "Pat Newman", score=90)

    fixtures.append_ledger_entry(
        client, account_id, "OBLIGATION_OPENED", 1000000, "2026-08-01", "OBL-31"
    )
    fixtures.append_ledger_entry(
        client, account_id, "DEPOSIT", 850000, "2026-08-01", "DEP-31", cleared_date="2026-08-01"
    )
    audit = fixtures.schedule_audit(
        client,
        account_id,
        AUDITOR,
        basis="BOOK",
        as_of_date=AS_OF_DATE,
        fieldwork_start_at=FIELDWORK_START,
        fieldwork_end_at=FIELDWORK_END,
    )
    fixtures.start_fieldwork(client, audit["id"], AUDITOR)
    fixtures.dispose_audit(client, audit["id"], AUDITOR, "ISSUE_FINDINGS", remediation_days=3)
    return {
        "firm": firm,
        "brokerage_id": brokerage_id,
        "account_id": account_id,
        "audit_id": audit["id"],
        "salesperson": salesperson,
        "applicant": applicant,
    }


def _affiliate_naming_the_salesperson(client, world):
    """The doubly-defective affiliation, always with the firm's live version."""
    version = fixtures.read_brokerage(client, world["brokerage_id"])["version"]
    return client.create_affiliation(
        world["applicant"]["id"],
        factories.affiliation_payload(
            world["brokerage_id"], world["salesperson"]["id"], version
        ),
        make_analyst_headers(),
    )


def _clear_the_remediation(client, world):
    fixtures.append_ledger_entry(
        client,
        world["account_id"],
        "DEPOSIT",
        150000,
        "2026-08-02",
        "DEP-32",
        cleared_date="2026-08-02",
    )
    return fixtures.dispose_audit(client, world["audit_id"], AUDITOR, "VERIFY_REMEDIATION")


class TestPostureOutranksSupervisingBrokerEligibility:
    """Rung 16 answers while rung 22 is equally true of the same body."""

    def test_the_posture_block_answers_first(self, client):
        """Both defects hold, and the higher rung owns the response.

        The PRD says "Its `supervision_posture` must be neither `RESTRICTED` nor
        `FROZEN`, or the request is refused with `ERR_BROKERAGE_POSTURE_BLOCKED`
        — supervision integrity ranks above every capacity and eligibility rule
        that follows it, so a firm under a remediation order cannot absorb new
        agents no matter how much headroom it has."

        Design: Difficulty/priority_pair_validation_conflict/posture_safety_priority16_outranks_supervising_broker_referential_priority22
        """
        world = _restricted_firm_with_a_salesperson_and_an_applicant(client)
        assert_posture(fixtures.read_brokerage(client, world["brokerage_id"]), "RESTRICTED")
        assert world["salesperson"]["person_type"] == "SALESPERSON", (
            "the nominee is also ineligible to supervise anyone"
        )

        validate_error(
            _affiliate_naming_the_salesperson(client, world),
            "ERR_BROKERAGE_POSTURE_BLOCKED",
            expected_status=409,
        )

    def test_the_refused_affiliation_changed_nothing(self, client):
        """A ladder refusal is total: no partial affiliation is applied.

        The PRD says "The server therefore evaluates rules in one fixed ladder
        and returns the first failure it meets."

        Design: Difficulty/priority_pair_validation_conflict/posture_safety_priority16_outranks_supervising_broker_referential_priority22
        """
        world = _restricted_firm_with_a_salesperson_and_an_applicant(client)
        _affiliate_naming_the_salesperson(client, world)

        applicant = fixtures.read_licensee(client, world["applicant"]["id"])
        assert applicant["license_status"] == "EXAM_PASSED"
        assert applicant["sponsoring_brokerage_id"] is None
        assert fixtures.read_brokerage(client, world["brokerage_id"])[
            "affiliated_licensee_count"
        ] == 2

    def test_clearing_the_remediation_exposes_the_ineligible_nominee(self, client):
        """The same body switches error once the higher rung stops firing.

        The PRD says "A nominee failing any of those is refused with
        `ERR_SUPERVISING_BROKER_INELIGIBLE`."

        Design: Difficulty/priority_pair_validation_conflict/posture_safety_priority16_outranks_supervising_broker_referential_priority22
        """
        world = _restricted_firm_with_a_salesperson_and_an_applicant(client)
        validate_error(
            _affiliate_naming_the_salesperson(client, world), "ERR_BROKERAGE_POSTURE_BLOCKED"
        )

        closed = _clear_the_remediation(client, world)
        assert closed["status"] == "CLOSED"
        assert closed["verified_shortage_cents"] == 0
        assert fixtures.read_trust_account(client, world["account_id"])["status"] == "OPEN"
        assert_posture(fixtures.read_brokerage(client, world["brokerage_id"]), "COMPLIANT")

        validate_error(
            _affiliate_naming_the_salesperson(client, world),
            "ERR_SUPERVISING_BROKER_INELIGIBLE",
            expected_status=422,
        )
        applicant = fixtures.read_licensee(client, world["applicant"]["id"])
        assert applicant["license_status"] == "EXAM_PASSED"
        assert fixtures.read_brokerage(client, world["brokerage_id"])[
            "affiliated_licensee_count"
        ] == 2


ORDER_INSTANT = "2026-08-05T09:00:00Z"
OUTSIDE_WINDOW = "2027-09-01T00:00:00Z"
INSIDE_WINDOW = "2026-09-01T00:00:00Z"


def _revoked_salesperson_with_one_claim_and_a_floor_level_fund(client):
    """A revocation order, one eligible claim, and a fund sitting exactly on the floor."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name="Harbor Realty Group",
        broker_name="Dana Broker",
        trust_account_required=False,
        open_escrow=False,
    )
    respondent = fixtures.affiliate_new_salesperson(
        client, firm["brokerage"]["id"], firm["broker"]["id"], "Rae Field"
    )
    complaint = fixtures.complaint_at_probable_cause(
        client, respondent["id"], "MISREPRESENTATION", 3000000
    )
    fixtures.move_clock(client, ORDER_INSTANT)
    order = fixtures.issue_order_by_consent(
        client,
        complaint["id"],
        respondent["id"],
        sanction_type="REVOCATION",
        fine_cents=0,
        suspension_days=0,
    )
    claim = fixtures.file_claim(client, order["id"], 1000000, "Ora Buyer")
    fixtures.appropriate(client, 500000)
    return {"respondent": respondent, "order": order, "claim": claim}


class TestClaimWindowOutranksTheReserveFloor:
    """Rung 44 answers while rung 47 is equally true of the same run."""

    def test_the_closed_window_answers_before_the_reserve_floor(self, client):
        """A stale order and an empty fund; the temporal rung owns the answer.

        The PRD says "**Recovery window still open** — `ERR_CLAIM_WINDOW_CLOSED`,
        on the disbursement run."

        Design: Difficulty/priority_pair_validation_conflict/claim_window_temporal_priority44_outranks_fund_reserve_fiscal_priority47
        """
        world = _revoked_salesperson_with_one_claim_and_a_floor_level_fund(client)
        assert world["order"]["effective_at"] == ORDER_INSTANT
        assert world["claim"]["status"] == "ELIGIBLE"
        fund = fixtures.read_fund(client)
        assert fund["balance_cents"] == 500000, "exactly on the reserve floor"

        fixtures.move_clock(client, OUTSIDE_WINDOW)
        validate_error(
            fixtures.disburse(client, world["order"]["id"]),
            "ERR_CLAIM_WINDOW_CLOSED",
            expected_status=409,
        )

    def test_neither_refusal_applies_any_part_of_the_waterfall(self, client):
        """Rewinding inside the window leaves only the fiscal defect.

        The PRD says "the fund's `balance_cents` must exceed the 500,000-cent
        reserve floor, otherwise `ERR_FUND_RESERVE_FLOOR`".

        Design: Difficulty/priority_pair_validation_conflict/claim_window_temporal_priority44_outranks_fund_reserve_fiscal_priority47
        """
        world = _revoked_salesperson_with_one_claim_and_a_floor_level_fund(client)
        version_before = fixtures.read_fund(client)["version"]

        fixtures.move_clock(client, OUTSIDE_WINDOW)
        validate_error(fixtures.disburse(client, world["order"]["id"]), "ERR_CLAIM_WINDOW_CLOSED")

        fixtures.move_clock(client, INSIDE_WINDOW)
        validate_error(
            fixtures.disburse(client, world["order"]["id"]),
            "ERR_FUND_RESERVE_FLOOR",
            expected_status=409,
        )

        fund = fixtures.read_fund(client)
        assert fund["awarded_cents"] == 0
        assert fund["assessment_cents"] == 0
        assert fund["balance_cents"] == 500000
        assert fund["version"] == version_before, "a refused run bumps nothing"
        claim = fixtures.claims_for_order(client, world["order"]["id"])[0]
        assert claim["status"] == "ELIGIBLE"
        assert claim["awarded_cents"] == 0

    def test_topping_the_fund_up_lets_the_identical_run_through(self, client):
        """With both defects gone the waterfall pays out in full.

        The PRD says "An **administrative assessment** of 2 percent is then
        retained out of that total, rounded half up to whole cents."

        Design: Difficulty/priority_pair_validation_conflict/claim_window_temporal_priority44_outranks_fund_reserve_fiscal_priority47
        """
        world = _revoked_salesperson_with_one_claim_and_a_floor_level_fund(client)
        fixtures.move_clock(client, INSIDE_WINDOW)
        validate_error(fixtures.disburse(client, world["order"]["id"]), "ERR_FUND_RESERVE_FLOOR")

        fixtures.appropriate(client, 3000000)
        run = validate_success(fixtures.disburse(client, world["order"]["id"]))

        assert run["total_awarded_cents"] == 1000000
        assert run["assessment_cents"] == expected_assessment_cents(1000000) == 20000
        assert run["balance_cents_after"] == 2480000
        assert run["shaved_claim_id"] is None
        assert run["paid_claim_count"] == 1
        assert run["partially_paid_claim_count"] == 0

        claim = fixtures.claims_for_order(client, world["order"]["id"])[0]
        assert claim["status"] == "PAID"
        assert claim["awarded_cents"] == 1000000
        respondent = fixtures.read_licensee(client, world["respondent"]["id"])
        assert respondent["recovery_paid_cents"] == 1000000


SITTING_START = "2026-08-05T09:00:00Z"
SITTING_END = "2026-08-05T11:00:00Z"
BUFFERED_START = "2026-08-05T11:30:00Z"
BUFFERED_END = "2026-08-05T12:30:00Z"
CASE_A_INVESTIGATOR = "counsel-05"
CASE_B_INVESTIGATOR = "counsel-09"


def _two_cases_with_one_room_already_sitting(client):
    """Case A holds ROOM-A from 09:00 to 11:00; case B is waiting at probable cause."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name="Harbor Realty Group",
        broker_name="Dana Broker",
        trust_account_required=False,
        open_escrow=False,
    )
    brokerage_id = firm["brokerage"]["id"]
    broker_id = firm["broker"]["id"]
    rae = fixtures.affiliate_new_salesperson(client, brokerage_id, broker_id, "Rae Field")
    ken = fixtures.affiliate_new_salesperson(client, brokerage_id, broker_id, "Ken Ito")

    case_a = fixtures.file_complaint(client, rae["id"], "AGENCY_DISCLOSURE", 800000, "Ora Buyer")
    fixtures.dispose_complaint(
        client, case_a["id"], "INVESTIGATE", counsel_user_id=CASE_A_INVESTIGATOR
    )
    fixtures.dispose_complaint(
        client, case_a["id"], "PROBABLE_CAUSE", counsel_user_id=CASE_A_INVESTIGATOR
    )
    sitting = fixtures.schedule_hearing(
        client,
        case_a["id"],
        "chair-01",
        SITTING_START,
        SITTING_END,
        "ROOM-A",
        counsel_user_id=CASE_A_INVESTIGATOR,
    )

    case_b = fixtures.file_complaint(client, ken["id"], "MISREPRESENTATION", 900000, "Ivo Renter")
    fixtures.dispose_complaint(
        client, case_b["id"], "INVESTIGATE", counsel_user_id=CASE_B_INVESTIGATOR
    )
    fixtures.dispose_complaint(
        client, case_b["id"], "PROBABLE_CAUSE", counsel_user_id=CASE_B_INVESTIGATOR
    )
    return {"ken": ken, "case_a": case_a, "case_b": case_b, "sitting": sitting}


def _schedule_case_b(client, world, panel_chair_user_id, start_at, end_at):
    return client.schedule_hearing(
        world["case_b"]["id"],
        factories.hearing_payload(panel_chair_user_id, start_at, end_at, "ROOM-A"),
        make_counsel_headers(CASE_B_INVESTIGATOR),
    )


class TestSegregationOutranksTheHearingRoomBuffer:
    """Rung 17 answers while rung 40 is equally true of the same slot."""

    def test_the_investigator_as_chair_answers_before_the_room_clash(self, client):
        """A tainted chair and a back-to-back slot; the safety rung wins.

        The PRD says "The chair may not be the complaint's
        `investigator_user_id` — the officer who built the case may not judge it
        — and such an attempt is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/priority_pair_validation_conflict/segregation_safety_priority17_outranks_hearing_room_temporal_priority40
        """
        world = _two_cases_with_one_room_already_sitting(client)

        validate_error(
            _schedule_case_b(client, world, CASE_B_INVESTIGATOR, SITTING_END, "2026-08-05T12:00:00Z"),
            "ERR_SEGREGATION_OF_DUTIES",
            expected_status=409,
        )

        case_b = fixtures.read_complaint(client, world["case_b"]["id"])
        assert case_b["status"] == "PROBABLE_CAUSE"
        assert fixtures.read_licensee(client, world["ken"]["id"])["discipline_status"] == (
            "UNDER_INVESTIGATION"
        )

    def test_a_clean_chair_exposes_the_zero_gap_room_conflict(self, client):
        """The identical slot, a clean chair, and now the buffer bites.

        The PRD says "Back-to-back booking with a gap of exactly zero is
        therefore a **conflict**, while a gap of exactly 30 minutes is
        permitted."

        Design: Difficulty/priority_pair_validation_conflict/segregation_safety_priority17_outranks_hearing_room_temporal_priority40
        """
        world = _two_cases_with_one_room_already_sitting(client)
        validate_error(
            _schedule_case_b(client, world, CASE_B_INVESTIGATOR, SITTING_END, "2026-08-05T12:00:00Z"),
            "ERR_SEGREGATION_OF_DUTIES",
        )

        validate_error(
            _schedule_case_b(client, world, "chair-02", SITTING_END, "2026-08-05T12:00:00Z"),
            "ERR_HEARING_ROOM_CONFLICT",
            expected_status=409,
        )
        assert fixtures.read_complaint(client, world["case_b"]["id"])["status"] == "PROBABLE_CAUSE"

    def test_one_full_buffer_later_the_same_room_is_bookable(self, client):
        """Both defects removed, the hearing is created and the case moves on.

        The PRD says "Scheduling creates the hearing in `SCHEDULED` with
        `continuance_count` 0 and `convened_at`, `decided_at` and `finding` all
        null, moves the complaint `PROBABLE_CAUSE → HEARING_SCHEDULED`, moves the
        respondent's `discipline_status` `UNDER_INVESTIGATION → PENDING_HEARING`
        — which is what bars them from transferring brokerages — and recomputes
        the brokerage posture."

        Design: Difficulty/priority_pair_validation_conflict/segregation_safety_priority17_outranks_hearing_room_temporal_priority40
        """
        world = _two_cases_with_one_room_already_sitting(client)
        _schedule_case_b(client, world, CASE_B_INVESTIGATOR, SITTING_END, "2026-08-05T12:00:00Z")
        _schedule_case_b(client, world, "chair-02", SITTING_END, "2026-08-05T12:00:00Z")

        hearing = validate_success(
            _schedule_case_b(client, world, "chair-02", BUFFERED_START, BUFFERED_END),
            expected_status=201,
        )
        assert hearing["hearing_room"] == "ROOM-A"
        assert hearing["status"] == "SCHEDULED"
        assert hearing["continuance_count"] == 0

        assert fixtures.read_complaint(client, world["case_b"]["id"])["status"] == (
            "HEARING_SCHEDULED"
        )
        assert fixtures.read_licensee(client, world["ken"]["id"])["discipline_status"] == (
            "PENDING_HEARING"
        )

        sitting = validate_success(
            client.get_hearing(world["sitting"]["id"], make_analyst_headers())
        )
        assert sitting["status"] == "SCHEDULED"
        assert sitting["hearing_room"] == "ROOM-A"
        assert sitting["scheduled_start_at"] == SITTING_START
        assert sitting["scheduled_end_at"] == SITTING_END
