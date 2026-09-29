"""Gates that fire in a fixed order, and keys that are wider than they look."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success
from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_ADVERTISING_NAME_TAKEN,
    ERR_CE_HOURS_INSUFFICIENT,
    ERR_DESIGNATED_BROKER_NOT_BROKER,
    ERR_DUPLICATE_TRANSACTION_REFERENCE,
    ERR_REINSTATEMENT_FEE_MISMATCH,
    ERR_TEAM_LEAD_NOT_AFFILIATED,
    ERR_TEAM_NAME_IMPLIES_BROKERAGE,
)
from test_helpers.assertions import (
    assert_book_position,
    assert_ce_standing,
    assert_immutable_row,
    assert_posture,
)
from test_helpers.constants import CLOCK_STARTUP_DEFAULT, REINSTATEMENT_BASE_CENTS
from test_helpers.test_users import make_analyst_headers, make_salesperson_headers

FIRM_NAME = "Harbor Realty Group"
BROKER_NAME = "Dana Broker"
REACTIVATION_INSTANT = "2026-08-20T00:00:00Z"
NEW_TERM_EXPIRY = "2028-08-19T00:00:00Z"
EXACT_FEE_CENTS = 15000


def _parked_salesperson_and_a_school(client):
    """Sam Sales parked with no education banked, and a school ready to teach."""
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
    school = fixtures.approved_provider_with_instructor(
        client, provider_name="Coastal Institute", instructor_name="Ivy Teach"
    )
    parked = fixtures.go_inactive(
        client, salesperson["id"], make_salesperson_headers(salesperson["id"])
    )
    assert parked["ce_hours_valid"] == 0
    fixtures.move_clock(client, REACTIVATION_INSTANT)
    return {"firm": firm, "parked": parked, "school": school}


def _reactivate(client, world, fee_cents):
    licensee_id = world["parked"]["id"]
    return fixtures.status_change(
        client,
        licensee_id,
        "REACTIVATE",
        brokerage_id=world["firm"]["brokerage"]["id"],
        supervising_broker_id=world["firm"]["broker"]["id"],
        reinstatement_fee_paid_cents=fee_cents,
        headers=make_salesperson_headers(licensee_id),
    )


def _bank_twelve_core_hours(client, world):
    return fixtures.record_completion(
        client,
        world["parked"]["id"],
        world["school"]["instructor"]["id"],
        world["school"]["provider"]["id"],
        credit_hours=12,
        # Inside the window opened at issuance and strictly before the
        # reactivation date, so the fresh window cannot re-count these hours:
        # "its `completed_on` date falls on or after `ce_period_start_on`".
        completed_on="2026-08-10",
        course_type="CE_CORE",
    )


class TestTheEducationGateDecidesBeforeTheFeeArithmetic:
    """Both defects are present, and the lower rung number owns the answer."""

    def test_a_deficient_licensee_paying_the_wrong_fee_hears_about_the_hours(self, client):
        """Rung 37 answers while rung 51 is equally true of the same body.

        The PRD says "The server therefore evaluates rules in one fixed ladder and
        returns the first failure it meets."

        Design: Corner/validations/reactivation_is_refused_for_a_ce_deficit_before_the_fee_is_ever_checked
        """
        world = _parked_salesperson_and_a_school(client)

        validate_error(_reactivate(client, world, 99999), ERR_CE_HOURS_INSUFFICIENT)

        still_parked = fixtures.read_licensee(client, world["parked"]["id"])
        assert still_parked["license_status"] == "INACTIVE"
        assert still_parked["inactive_since"] == CLOCK_STARTUP_DEFAULT
        assert_ce_standing(still_parked, valid=0, required=12)

    def test_with_the_hours_in_hand_one_cent_over_is_still_refused(self, client):
        """Neither an underpayment nor an overpayment buys the licence back.

        The PRD says "The tendered `reinstatement_fee_paid_cents` must equal the
        computed assessment **exactly** — neither an underpayment nor an
        overpayment is accepted, and a mismatch in either direction is refused with
        `ERR_REINSTATEMENT_FEE_MISMATCH`."

        Design: Corner/validations/reactivation_is_refused_for_a_ce_deficit_before_the_fee_is_ever_checked
        """
        world = _parked_salesperson_and_a_school(client)
        _bank_twelve_core_hours(client, world)

        educated = fixtures.read_licensee(client, world["parked"]["id"])
        assert_ce_standing(educated, valid=12, required=12)
        assert educated["ce_deficient"] is False

        validate_error(
            _reactivate(client, world, EXACT_FEE_CENTS + 1), ERR_REINSTATEMENT_FEE_MISMATCH
        )
        assert fixtures.read_licensee(client, world["parked"]["id"])["license_status"] == "INACTIVE"

    def test_the_exact_base_fee_reopens_a_fresh_education_window(self, client):
        """Nineteen days away costs the bare base, and the window restarts.

        The PRD says "A successful reactivation sets `sponsoring_brokerage_id` and
        `supervising_broker_id` from the payload, clears `inactive_since`,
        re-stamps `license_expires_at` to the current instant plus 730 days, and —
        this is the part licensees find expensive — re-stamps `ce_period_start_on`
        to the current calendar date, opening a **fresh** accrual window."

        Design: Corner/validations/reactivation_is_refused_for_a_ce_deficit_before_the_fee_is_ever_checked
        """
        world = _parked_salesperson_and_a_school(client)
        _bank_twelve_core_hours(client, world)
        validate_error(
            _reactivate(client, world, EXACT_FEE_CENTS + 1), ERR_REINSTATEMENT_FEE_MISMATCH
        )

        assert EXACT_FEE_CENTS == REINSTATEMENT_BASE_CENTS
        revived = validate_success(_reactivate(client, world, EXACT_FEE_CENTS))
        assert revived["license_status"] == "ACTIVE"
        assert revived["inactive_since"] is None
        assert revived["license_expires_at"] == NEW_TERM_EXPIRY
        assert revived["ce_period_start_on"] == "2026-08-20"
        assert revived["ce_hours_valid"] == 0

        firm = fixtures.read_brokerage(client, world["firm"]["brokerage"]["id"])
        assert firm["affiliated_licensee_count"] == 2


DEPOSIT_CENTS = 100000
OBLIGATION_CENTS = 250000
SHARED_REFERENCE = "DEP-01"


def _account_with_one_deposit(client):
    """An escrow account holding a single cleared deposit under `DEP-01`."""
    firm = fixtures.bootstrap_active_brokerage(client, name=FIRM_NAME, broker_name=BROKER_NAME)
    account_id = firm["account"]["id"]
    fixtures.append_ledger_entry(
        client,
        account_id,
        "DEPOSIT",
        DEPOSIT_CENTS,
        "2026-08-01",
        SHARED_REFERENCE,
        cleared_date="2026-08-01",
    )
    account = fixtures.read_trust_account(client, account_id)
    return {"account_id": account_id, "version": account["version"]}


def _append(client, account_id, entry_type, amount_cents, reference, version):
    return client.create_ledger_entry(
        account_id,
        factories.ledger_entry_payload(
            entry_type, amount_cents, "2026-08-02", reference, version
        ),
        make_analyst_headers(),
    )


class TestLedgerReferencesAreUniquePerAccountAndEntryClass:
    """The key is the triple, so one reference can serve two classes."""

    def test_a_second_deposit_under_the_same_reference_is_refused(self, client):
        """Two identical deposits cannot be booked twice under one reference.

        The PRD says "References are unique per account **and entry class**: the
        combination of the owning `trust_account_id`, the `entry_type` and the
        `transaction_reference` must not already exist, or the append is refused
        with `ERR_DUPLICATE_TRANSACTION_REFERENCE`."

        Design: Corner/validations/duplicate_transaction_reference_within_one_entry_type_is_rejected
        """
        world = _account_with_one_deposit(client)

        validate_error(
            _append(
                client,
                world["account_id"],
                "DEPOSIT",
                DEPOSIT_CENTS,
                SHARED_REFERENCE,
                world["version"],
            ),
            ERR_DUPLICATE_TRANSACTION_REFERENCE,
        )

        account = fixtures.read_trust_account(client, world["account_id"])
        assert account["version"] == world["version"], "a refused append consumes no version"
        assert account["book_available_cents"] == DEPOSIT_CENTS
        rows, meta = validate_paginated(
            client.list_ledger_entries(world["account_id"], make_analyst_headers())
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1

    def test_a_different_entry_class_may_reuse_the_reference(self, client):
        """The composite key is exactly what lets a class share a reference.

        The PRD says "That composite is exactly what lets a correction reuse the
        reference of the disbursement it reverses while still preventing two
        identical disbursements from being booked twice under one reference."

        Design: Corner/validations/duplicate_transaction_reference_within_one_entry_type_is_rejected
        """
        world = _account_with_one_deposit(client)
        validate_error(
            _append(
                client,
                world["account_id"],
                "DEPOSIT",
                DEPOSIT_CENTS,
                SHARED_REFERENCE,
                world["version"],
            ),
            ERR_DUPLICATE_TRANSACTION_REFERENCE,
        )

        obligation = validate_success(
            _append(
                client,
                world["account_id"],
                "OBLIGATION_OPENED",
                OBLIGATION_CENTS,
                SHARED_REFERENCE,
                world["version"],
            ),
            expected_status=201,
        )
        assert obligation["transaction_reference"] == SHARED_REFERENCE
        assert obligation["entry_type"] == "OBLIGATION_OPENED"
        assert_immutable_row(obligation)

        account = fixtures.read_trust_account(client, world["account_id"])
        assert_book_position(account, OBLIGATION_CENTS, DEPOSIT_CENTS)
        assert account["shortage_cents"] == 150000
        assert account["version"] == world["version"] + 1


HELD_NAME_TEXT = "Harbor Homes"
COLLIDING_NAME_TEXT = "harbor-homes!"
HELD_NORMALIZED = "HARBORHOMES"


def _firm_holding_a_submitted_name(client):
    """A live firm whose first advertising name is still awaiting review."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name=FIRM_NAME,
        broker_name=BROKER_NAME,
        trust_account_required=False,
        open_escrow=False,
    )
    brokerage_id = firm["brokerage"]["id"]
    first = fixtures.submit_advertising_name(client, brokerage_id, HELD_NAME_TEXT)
    assert first["status"] == "SUBMITTED"
    assert first["normalized_name"] == HELD_NORMALIZED
    return {"firm": firm, "brokerage_id": brokerage_id, "first": first}


def _submit(client, brokerage_id, name_text, kind="DBA", team_lead_licensee_id=None):
    return client.create_advertising_name(
        factories.advertising_name_payload(brokerage_id, name_text, kind, team_lead_licensee_id),
        make_analyst_headers(),
    )


class TestALiveNormalizedNameIsHeldAgainstAllComers:
    """Punctuation is no disguise, and only a live row holds the form."""

    def test_a_differently_punctuated_submission_collides(self, client):
        """Both texts normalize to the same form, so the second is refused.

        The PRD says "No two names may share a `normalized_name` while both are
        live, where live means a `status` of `SUBMITTED` or `APPROVED`; a collision
        answers `ERR_ADVERTISING_NAME_TAKEN`."

        Design: Corner/validations/a_normalized_name_already_held_is_rejected_until_the_holder_is_rejected
        """
        world = _firm_holding_a_submitted_name(client)

        validate_error(
            _submit(client, world["brokerage_id"], COLLIDING_NAME_TEXT),
            ERR_ADVERTISING_NAME_TAKEN,
        )

        _rows, meta = validate_paginated(
            client.list_advertising_names(
                make_analyst_headers(), params={"brokerage_id": world["brokerage_id"]}
            )
        )
        assert meta["total_count"] == 1, "the refused submission created no row"

    def test_rejecting_the_holder_releases_the_form_for_re_use(self, client):
        """A rejected row is outside the uniqueness input set.

        The PRD says "Names in `REJECTED` or `REVOKED` release their normalized
        form for anyone to take, so a name lost to revocation immediately becomes
        available again."

        Design: Corner/validations/a_normalized_name_already_held_is_rejected_until_the_holder_is_rejected
        """
        world = _firm_holding_a_submitted_name(client)
        validate_error(
            _submit(client, world["brokerage_id"], COLLIDING_NAME_TEXT),
            ERR_ADVERTISING_NAME_TAKEN,
        )

        rejected = fixtures.review_advertising_name(
            client, world["first"]["id"], "REJECT", rejection_reason="NAME_TAKEN"
        )
        assert rejected["status"] == "REJECTED"

        second = validate_success(
            _submit(client, world["brokerage_id"], COLLIDING_NAME_TEXT), expected_status=201
        )
        assert second["normalized_name"] == HELD_NORMALIZED
        assert second["status"] == "SUBMITTED"

    def test_the_released_and_the_reissued_rows_coexist_in_filing_order(self, client):
        """History is kept: the rejected row is still on the register.

        The PRD says "Unless a list's own description says otherwise, results are
        ordered by `created_at` ascending."

        Design: Corner/validations/a_normalized_name_already_held_is_rejected_until_the_holder_is_rejected
        """
        world = _firm_holding_a_submitted_name(client)
        fixtures.review_advertising_name(
            client, world["first"]["id"], "REJECT", rejection_reason="NAME_TAKEN"
        )
        second = validate_success(
            _submit(client, world["brokerage_id"], COLLIDING_NAME_TEXT), expected_status=201
        )

        rows, meta = validate_paginated(
            client.list_advertising_names(
                make_analyst_headers(), params={"brokerage_id": world["brokerage_id"]}
            )
        )
        assert meta["total_count"] == 2
        assert [row["id"] for row in rows] == [world["first"]["id"], second["id"]]
        assert [row["status"] for row in rows] == ["REJECTED", "SUBMITTED"]


TEAM_NAME_TEXT = "Field Realty Team"
TEAM_NORMALIZED = "FIELDREALTYTEAM"
DBA_NAME_TEXT = "Harbor Realty Homes"
DBA_NORMALIZED = "HARBORREALTYHOMES"
CLEAN_TEAM_TEXT = "Coastal Partners Team"
CLEAN_TEAM_NORMALIZED = "COASTALPARTNERSTEAM"
LEAD_NAME = "Rae Field"


def _firm_with_an_active_team_lead(client):
    """A live firm and one issued salesperson eligible to lead a team."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name=FIRM_NAME,
        broker_name=BROKER_NAME,
        trust_account_required=False,
        open_escrow=False,
    )
    lead = fixtures.affiliate_new_salesperson(
        client, firm["brokerage"]["id"], firm["broker"]["id"], LEAD_NAME
    )
    assert lead["license_status"] == "ACTIVE"
    assert lead["sponsoring_brokerage_id"] == firm["brokerage"]["id"]
    return {"brokerage_id": firm["brokerage"]["id"], "lead": lead}


def _review_raw(client, name_id, decision, rejection_reason=None):
    return client.review_advertising_name(
        name_id,
        factories.advertising_review_payload(decision, rejection_reason),
        make_analyst_headers(),
    )


class TestTheForbiddenTeamWordsBiteOnlyAtReviewAndOnlyForTeams:
    """A team may not sound like a firm, but nobody says so until approval."""

    def test_a_team_name_carrying_realty_is_still_admitted_at_intake(self, client):
        """Registration normalizes the text and files the row without judgement.

        The PRD says "Normalization uppercases `name_text` and then discards every
        character that is not a letter A through Z or a digit 0 through 9, so
        spaces, punctuation, ampersands and hyphens all vanish: `"Elm & Oak
        Realty"` and `"elmoakrealty"` normalize identically."

        The PRD says "A successful registration starts in `SUBMITTED` with
        `reviewed_by_user_id` and `rejection_reason` null."

        Design: Corner/validations/a_team_name_that_implies_a_brokerage_is_refused_at_review
        """
        world = _firm_with_an_active_team_lead(client)

        filed = validate_success(
            _submit(
                client,
                world["brokerage_id"],
                TEAM_NAME_TEXT,
                kind="TEAM",
                team_lead_licensee_id=world["lead"]["id"],
            ),
            expected_status=201,
        )
        assert filed["normalized_name"] == TEAM_NORMALIZED
        assert filed["status"] == "SUBMITTED"
        assert filed["prohibited_term_hits"] == 0, "none of the six prohibited terms occur"
        assert filed["reviewed_by_user_id"] is None

    def test_approval_refuses_the_team_word_that_intake_let_through(self, client):
        """The forbidden-word test runs at review, and the row does not move.

        The PRD says "and for a team the lead must still be `ACTIVE` and still
        sponsored by this brokerage, or `ERR_TEAM_LEAD_NOT_AFFILIATED`, and the
        name must contain none of the forbidden team words, or
        `ERR_TEAM_NAME_IMPLIES_BROKERAGE`."

        Design: Corner/validations/a_team_name_that_implies_a_brokerage_is_refused_at_review
        """
        world = _firm_with_an_active_team_lead(client)
        filed = validate_success(
            _submit(
                client,
                world["brokerage_id"],
                TEAM_NAME_TEXT,
                kind="TEAM",
                team_lead_licensee_id=world["lead"]["id"],
            ),
            expected_status=201,
        )

        validate_error(
            _review_raw(client, filed["id"], "APPROVE"),
            ERR_TEAM_NAME_IMPLIES_BROKERAGE,
            expected_status=422,
        )

        held = fixtures.read_advertising_name(client, filed["id"])
        assert held["status"] == "SUBMITTED"
        assert held["reviewed_by_user_id"] is None
        assert held["rejection_reason"] is None

    def test_the_same_word_inside_a_dba_name_is_approved(self, client):
        """The forbidden-word test is scoped to `TEAM`, so a DBA sails through.

        The PRD says "Separately, and only for a name whose `kind` is `TEAM`, a
        second test counts how many of the five forbidden team words — `REALTY`,
        `REALESTATE`, `BROKERAGE`, `COMPANY`, `AGENCY` — appear inside
        `normalized_name`, on the principle that a team must not sound like an
        independent firm."

        Design: Corner/validations/a_team_name_that_implies_a_brokerage_is_refused_at_review
        """
        world = _firm_with_an_active_team_lead(client)
        filed = validate_success(
            _submit(client, world["brokerage_id"], DBA_NAME_TEXT), expected_status=201
        )
        assert filed["normalized_name"] == DBA_NORMALIZED

        approved = validate_success(_review_raw(client, filed["id"], "APPROVE"))
        assert approved["status"] == "APPROVED"
        assert approved["reviewed_by_user_id"] is not None
        assert approved["rejection_reason"] is None


class TestTheTeamLeadFieldIsRequiredExactlyWhereTheKindDemandsIt:
    """One error id answers both the missing lead and the surplus one."""

    def test_a_team_without_a_lead_is_refused(self, client):
        """A `TEAM` whose lead is absent is refused, and no row is filed.

        The PRD says "For a `DBA` or a `BRANCH` the `team_lead_licensee_id` **must
        be null**; supplying one is refused with `ERR_TEAM_LEAD_NOT_AFFILIATED`,
        the same error that answers a team whose lead is missing, whose
        `license_status` is not `ACTIVE`, or whose `sponsoring_brokerage_id` is not
        the brokerage the name is registered under."

        Design: Corner/validations/team_lead_is_required_for_team_kind_and_forbidden_otherwise
        """
        world = _firm_with_an_active_team_lead(client)

        validate_error(
            _submit(client, world["brokerage_id"], CLEAN_TEAM_TEXT, kind="TEAM"),
            ERR_TEAM_LEAD_NOT_AFFILIATED,
            expected_status=422,
        )

    def test_a_dba_that_names_a_lead_is_refused_with_the_same_error(self, client):
        """The field must be null for a DBA, and supplying it is the same refusal.

        The PRD says "For a `DBA` or a `BRANCH` the `team_lead_licensee_id` **must
        be null**; supplying one is refused with `ERR_TEAM_LEAD_NOT_AFFILIATED`,
        the same error that answers a team whose lead is missing, whose
        `license_status` is not `ACTIVE`, or whose `sponsoring_brokerage_id` is not
        the brokerage the name is registered under."

        Design: Corner/validations/team_lead_is_required_for_team_kind_and_forbidden_otherwise
        """
        world = _firm_with_an_active_team_lead(client)

        validate_error(
            _submit(
                client,
                world["brokerage_id"],
                DBA_NAME_TEXT,
                kind="DBA",
                team_lead_licensee_id=world["lead"]["id"],
            ),
            ERR_TEAM_LEAD_NOT_AFFILIATED,
            expected_status=422,
        )

    def test_neither_refusal_leaves_a_row_and_the_correct_pairing_registers(self, client):
        """Two rejected filings register nothing; the well-formed team does.

        The PRD says "A successful registration starts in `SUBMITTED` with
        `reviewed_by_user_id` and `rejection_reason` null."

        Design: Corner/validations/team_lead_is_required_for_team_kind_and_forbidden_otherwise
        """
        world = _firm_with_an_active_team_lead(client)
        brokerage_id = world["brokerage_id"]
        validate_error(
            _submit(client, brokerage_id, CLEAN_TEAM_TEXT, kind="TEAM"),
            ERR_TEAM_LEAD_NOT_AFFILIATED,
        )
        validate_error(
            _submit(
                client,
                brokerage_id,
                DBA_NAME_TEXT,
                team_lead_licensee_id=world["lead"]["id"],
            ),
            ERR_TEAM_LEAD_NOT_AFFILIATED,
        )

        _rows, meta = validate_paginated(
            client.list_advertising_names(
                make_analyst_headers(), params={"brokerage_id": brokerage_id}
            )
        )
        assert meta["total_count"] == 0, "a refused registration files nothing"

        filed = validate_success(
            _submit(
                client,
                brokerage_id,
                CLEAN_TEAM_TEXT,
                kind="TEAM",
                team_lead_licensee_id=world["lead"]["id"],
            ),
            expected_status=201,
        )
        assert filed["kind"] == "TEAM"
        assert filed["team_lead_licensee_id"] == world["lead"]["id"]
        assert filed["normalized_name"] == CLEAN_TEAM_NORMALIZED
        assert filed["status"] == "SUBMITTED"
        assert filed["reviewed_by_user_id"] is None
        assert filed["rejection_reason"] is None


BROKER_APPLICANT_NAME = "Quinn Broker"
SALESPERSON_NAME = "Sal Person"
BROKER_PASSING_SCORE = 91


def _two_ineligible_nominees(client):
    """A salesperson who passed her exam and a broker who has not sat his."""
    salesperson = fixtures.create_exam_passed_licensee(
        client, "SALESPERSON", SALESPERSON_NAME, score=82
    )
    assert salesperson["person_type"] == "SALESPERSON"
    assert salesperson["license_status"] == "EXAM_PASSED"
    broker_applicant = fixtures.create_applicant(client, "BROKER", BROKER_APPLICANT_NAME)
    assert broker_applicant["person_type"] == "BROKER"
    assert broker_applicant["license_status"] == "APPLICANT"
    return {"salesperson": salesperson, "broker_applicant": broker_applicant}


def _register(client, designated_broker_id, name=FIRM_NAME):
    return client.create_brokerage(
        factories.brokerage_payload(name, designated_broker_id, False, 5),
        make_analyst_headers(),
    )


class TestTheDesignatedBrokerMustBeABrokerInALicensableState:
    """Two independent conditions, one error id, and no half-registered firm."""

    def test_a_licensable_salesperson_is_the_wrong_person_type(self, client):
        """`EXAM_PASSED` is the right standing on the wrong class of licence.

        The PRD says "The nominated designated broker must be a licensee whose
        `person_type` is `BROKER` and whose `license_status` is either
        `EXAM_PASSED` or `ACTIVE`; anything else is refused with
        `ERR_DESIGNATED_BROKER_NOT_BROKER`, and the same check is re-run at
        activation because the broker's standing may have changed in between."

        Design: Corner/validations/designated_broker_must_be_a_broker_in_a_licensable_state
        """
        world = _two_ineligible_nominees(client)

        validate_error(
            _register(client, world["salesperson"]["id"]),
            ERR_DESIGNATED_BROKER_NOT_BROKER,
            expected_status=422,
        )

    def test_a_broker_who_has_not_passed_the_exam_is_in_the_wrong_state(self, client):
        """The right class of licence in the wrong standing fails the same gate.

        The PRD says "The nominated designated broker must be a licensee whose
        `person_type` is `BROKER` and whose `license_status` is either
        `EXAM_PASSED` or `ACTIVE`; anything else is refused with
        `ERR_DESIGNATED_BROKER_NOT_BROKER`, and the same check is re-run at
        activation because the broker's standing may have changed in between."

        Design: Corner/validations/designated_broker_must_be_a_broker_in_a_licensable_state
        """
        world = _two_ineligible_nominees(client)

        validate_error(
            _register(client, world["broker_applicant"]["id"]),
            ERR_DESIGNATED_BROKER_NOT_BROKER,
            expected_status=422,
        )

    def test_the_exam_result_makes_the_identical_registration_succeed(self, client):
        """Nothing registers until the nominee qualifies; then the firm rests at zero.

        The PRD says "A newly registered brokerage sits in `PENDING` with
        `affiliated_licensee_count`, `open_shortage_cents`, `open_complaint_count`
        and `overdue_remediation_count` all at 0 and its `supervision_posture`
        computed from those zeros."

        Design: Corner/validations/designated_broker_must_be_a_broker_in_a_licensable_state
        """
        world = _two_ineligible_nominees(client)
        nominee_id = world["broker_applicant"]["id"]
        validate_error(_register(client, world["salesperson"]["id"]), ERR_DESIGNATED_BROKER_NOT_BROKER)
        validate_error(_register(client, nominee_id), ERR_DESIGNATED_BROKER_NOT_BROKER)

        _rows, meta = validate_paginated(client.list_brokerages(make_analyst_headers()))
        assert meta["total_count"] == 0, "neither refusal left a firm behind"

        qualified = validate_success(
            client.record_exam_result(
                nominee_id,
                factories.exam_result_payload(BROKER_PASSING_SCORE, "2026-08-01"),
                make_analyst_headers(),
            )
        )
        assert qualified["license_status"] == "EXAM_PASSED"

        firm = validate_success(_register(client, nominee_id), expected_status=201)
        assert firm["status"] == "PENDING"
        assert firm["designated_broker_id"] == nominee_id
        assert firm["affiliated_licensee_count"] == 0
        assert firm["open_shortage_cents"] == 0
        assert firm["open_complaint_count"] == 0
        assert firm["overdue_remediation_count"] == 0
        assert_posture(firm, "COMPLIANT")
