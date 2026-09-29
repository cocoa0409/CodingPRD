"""Two derived figures and the input sets they are computed over."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success
from test_helpers import factories, fixtures
from test_helpers.api_errors import ERR_PROHIBITED_ADVERTISING_TERM
from test_helpers.assertions import assert_ce_standing
from test_helpers.test_users import ANALYST_USER_ID, make_analyst_headers

FIRM_NAME = "Harbor Realty Group"
BROKER_NAME = "Dana Broker"
HIT_NAME_TEXT = "The Official-Group"
HIT_NORMALIZED = "THEOFFICIALGROUP"
CLEAN_NAME_TEXT = "Harbor Homes"
CLEAN_NORMALIZED = "HARBORHOMES"


def _two_registered_names(client):
    """One name carrying a prohibited term, one clean, both in `SUBMITTED`."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name=FIRM_NAME,
        broker_name=BROKER_NAME,
        trust_account_required=False,
        open_escrow=False,
    )
    brokerage_id = firm["brokerage"]["id"]
    return {
        "firm": firm,
        "bad": fixtures.submit_advertising_name(client, brokerage_id, HIT_NAME_TEXT),
        "good": fixtures.submit_advertising_name(client, brokerage_id, CLEAN_NAME_TEXT),
    }


def _review(client, name_id, decision, rejection_reason=None):
    return client.review_advertising_name(
        name_id,
        factories.advertising_review_payload(decision, rejection_reason),
        make_analyst_headers(),
    )


class TestProhibitedTermsAreCountedOnTheNormalizedForm:
    """Punctuation cannot hide a term, and the count bites only at review."""

    def test_punctuation_and_spacing_are_stripped_before_the_substring_test(self, client):
        """A hyphen and two spaces vanish, and the buried term still counts.

        The PRD says "Normalization uppercases `name_text` and then discards every
        character that is not a letter A through Z or a digit 0 through 9, so
        spaces, punctuation, ampersands and hyphens all vanish: `"Elm & Oak
        Realty"` and `"elmoakrealty"` normalize identically."

        Design: Corner/calculations/advertising_normalization_counts_prohibited_terms_on_the_normalized_form
        """
        world = _two_registered_names(client)
        bad = world["bad"]

        assert bad["name_text"] == HIT_NAME_TEXT
        assert bad["normalized_name"] == HIT_NORMALIZED
        assert bad["prohibited_term_hits"] == 1
        assert bad["status"] == "SUBMITTED", "the term test bites at review, not at intake"
        assert bad["reviewed_by_user_id"] is None
        assert bad["rejection_reason"] is None

    def test_a_clean_name_scores_no_hits_at_all(self, client):
        """None of the six terms appears anywhere inside the normalized form.

        The PRD says "`prohibited_term_hits` counts how many of the six prohibited
        terms — `REALTOR`, `MLS`, `COMMISSION`, `STATEOF`, `GUARANTEED`,
        `OFFICIAL` — appear anywhere inside `normalized_name`; each distinct term
        is counted once no matter how often it occurs."

        Design: Corner/calculations/advertising_normalization_counts_prohibited_terms_on_the_normalized_form
        """
        world = _two_registered_names(client)
        good = world["good"]

        assert good["normalized_name"] == CLEAN_NORMALIZED
        assert good["prohibited_term_hits"] == 0
        assert good["status"] == "SUBMITTED"

    def test_approval_is_refused_while_a_single_hit_stands(self, client):
        """Zero hits is the approval boundary, and one hit is one too many.

        The PRD says "Every gate is **re-evaluated against current state at the
        moment of approval**, not against the state at submission, because the
        world may have moved: `prohibited_term_hits` must be 0, or
        `ERR_PROHIBITED_ADVERTISING_TERM`; the owning brokerage's
        `supervision_posture` must not be `RESTRICTED` or `FROZEN`, or
        `ERR_BROKERAGE_POSTURE_BLOCKED`; no other live row may hold the same
        `normalized_name`, or `ERR_ADVERTISING_NAME_TAKEN`; and for a team the
        lead must still be `ACTIVE` and still sponsored by this brokerage, or
        `ERR_TEAM_LEAD_NOT_AFFILIATED`, and the name must contain none of the
        forbidden team words, or `ERR_TEAM_NAME_IMPLIES_BROKERAGE`."

        Design: Corner/calculations/advertising_normalization_counts_prohibited_terms_on_the_normalized_form
        """
        world = _two_registered_names(client)

        validate_error(
            _review(client, world["bad"]["id"], "APPROVE"),
            ERR_PROHIBITED_ADVERTISING_TERM,
            expected_status=422,
        )
        refused = fixtures.read_advertising_name(client, world["bad"]["id"])
        assert refused["status"] == "SUBMITTED"
        assert refused["reviewed_by_user_id"] is None

    def test_rejection_stores_the_reviewer_s_reason(self, client):
        """The same row the approval refused is disposed of by hand instead.

        The PRD says "`REJECT` moves the name `SUBMITTED → REJECTED`, records
        `reviewed_by_user_id`, and stores the reviewer's `rejection_reason`, which
        is one of `PROHIBITED_TERM`, `NAME_TAKEN`, `TEAM_LEAD_INELIGIBLE`,
        `POSTURE_RESTRICTED` or `IMPLIES_BROKERAGE`."

        Design: Corner/calculations/advertising_normalization_counts_prohibited_terms_on_the_normalized_form
        """
        world = _two_registered_names(client)
        validate_error(_review(client, world["bad"]["id"], "APPROVE"), ERR_PROHIBITED_ADVERTISING_TERM)

        rejected = validate_success(
            _review(client, world["bad"]["id"], "REJECT", rejection_reason="PROHIBITED_TERM")
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "PROHIBITED_TERM"
        assert rejected["reviewed_by_user_id"] == ANALYST_USER_ID

    def test_the_clean_name_passes_the_same_review(self, client):
        """Zero hits clears the gate the other name failed.

        The PRD says "`APPROVE` moves the name `SUBMITTED → APPROVED` and records
        `reviewed_by_user_id`."

        Design: Corner/calculations/advertising_normalization_counts_prohibited_terms_on_the_normalized_form
        """
        world = _two_registered_names(client)

        approved = validate_success(_review(client, world["good"]["id"], "APPROVE"))
        assert approved["status"] == "APPROVED"
        assert approved["rejection_reason"] is None
        assert approved["reviewed_by_user_id"] == ANALYST_USER_ID


PRELICENSE_HOURS = 12
CORE_HOURS = 6
ELECTIVE_HOURS = 6
PROVIDER_NAME = "Coastal Institute"
INSTRUCTOR_NAME = "Ivy Teach"


def _student_with_three_completions(client):
    """Sam Sales issued today, with a prelicence, a core and an elective course."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name=FIRM_NAME,
        broker_name=BROKER_NAME,
        trust_account_required=False,
        open_escrow=False,
    )
    student = fixtures.affiliate_new_salesperson(
        client, firm["brokerage"]["id"], firm["broker"]["id"], "Sam Sales"
    )
    school = fixtures.approved_provider_with_instructor(
        client, provider_name=PROVIDER_NAME, instructor_name=INSTRUCTOR_NAME
    )

    def record(course_type, credit_hours):
        return fixtures.record_completion(
            client,
            student["id"],
            school["instructor"]["id"],
            school["provider"]["id"],
            credit_hours=credit_hours,
            completed_on="2026-08-01",
            course_type=course_type,
        )

    return {
        "student": student,
        "record": record,
        "prelicense": record("PRELICENSE", PRELICENSE_HOURS),
    }


class TestValidContinuingEducationHoursFilterTheirInputSet:
    """Two independent filters over one licensee's completion history."""

    def test_a_prelicence_course_contributes_nothing_to_the_continuing_total(self, client):
        """Twelve hours are recorded, banked elsewhere, and still leave a deficit.

        The PRD says "Hours from `PRELICENSE` and `POST_LICENSE` courses never
        count toward this total."

        Design: Corner/calculations/ce_hours_valid_counts_only_valid_ce_course_types
        """
        world = _student_with_three_completions(client)
        assert world["prelicense"]["credit_status"] == "VALID"
        assert world["prelicense"]["credit_hours"] == PRELICENSE_HOURS

        student = fixtures.read_licensee(client, world["student"]["id"])
        assert_ce_standing(student, valid=0, required=12)
        assert student["ce_deficient"] is True

    def test_the_core_and_elective_hours_accumulate_to_the_requirement(self, client):
        """Six then six, and the deficiency clears exactly on the boundary.

        The PRD says "`ce_hours_valid` is the sum of `credit_hours` across that
        licensee's course completions that satisfy three conditions together: the
        completion's `credit_status` is `VALID`, its `course_type` is either
        `CE_CORE` or `CE_ELECTIVE`, and its `completed_on` date falls on or after
        `ce_period_start_on`."

        Design: Corner/calculations/ce_hours_valid_counts_only_valid_ce_course_types
        """
        world = _student_with_three_completions(client)
        record = world["record"]

        core = record("CE_CORE", CORE_HOURS)
        assert core["credit_status"] == "VALID"
        half_way = fixtures.read_licensee(client, world["student"]["id"])
        assert_ce_standing(half_way, valid=CORE_HOURS, required=12)
        assert half_way["ce_deficient"] is True

        elective = record("CE_ELECTIVE", ELECTIVE_HOURS)
        assert elective["credit_status"] == "VALID"
        compliant = fixtures.read_licensee(client, world["student"]["id"])
        assert_ce_standing(compliant, valid=CORE_HOURS + ELECTIVE_HOURS, required=12)
        assert compliant["ce_deficient"] is False

    def test_the_excluded_completion_is_still_stored_and_listed(self, client):
        """Three rows in the register, one of them outside the education total.

        The PRD says "`ce_deficient` is simply true whenever `ce_hours_valid` is
        less than `ce_hours_required`, and both are re-derived on every read of
        the licensee."

        Design: Corner/calculations/ce_hours_valid_counts_only_valid_ce_course_types
        """
        world = _student_with_three_completions(client)
        world["record"]("CE_CORE", CORE_HOURS)
        world["record"]("CE_ELECTIVE", ELECTIVE_HOURS)

        rows, meta = validate_paginated(
            client.list_course_completions(
                make_analyst_headers(), params={"licensee_id": world["student"]["id"]}
            )
        )
        assert meta["total_count"] == 3
        assert [row["course_type"] for row in rows] == ["PRELICENSE", "CE_CORE", "CE_ELECTIVE"]
        assert all(row["credit_status"] == "VALID" for row in rows)
        assert sum(row["credit_hours"] for row in rows) == 24

        student = fixtures.read_licensee(client, world["student"]["id"])
        assert student["ce_hours_valid"] == 12, "the prelicence row is stored but not counted"
        assert student["ce_deficient"] is False
