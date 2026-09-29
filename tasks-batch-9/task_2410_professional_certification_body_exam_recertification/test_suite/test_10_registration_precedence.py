"""Form state outranks the exam fee on one underpaid registration."""

from test_helpers import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success

UNDERPAID = 1000


def _assembled_form_and_approved_application(api):
    """An operational item, a form still ASSEMBLED, and an approved applicant."""
    program = fx.active_program(api)
    item = fx.operational_item(api, program["id"])
    form = fx.assembled_form(api, program["id"], [item["id"]])
    candidate = fx.create_candidate(api)
    application = fx.approved_application(api, candidate["id"], program["id"])
    return program, form, candidate, application


class TestRegistrationRejectionPrecedence:
    """One body that is both underpaid and cites an unpublished form."""

    def test_unpublished_form_outranks_the_insufficient_fee(self, api):
        """The fee is a fortieth of the price and the form has no cut score, and the
        form's state is the answer.

        PRD §2.7: "Registering with an insufficient fee against a form that is not
        published returns `ERR_FORM_NOT_PUBLISHED`, not
        `ERR_EXAM_FEE_INSUFFICIENT`, because form state sits at layer 14 and the fee
        at layer 44."

        Design: Difficulty/priority_pair_validation_conflict/exam_form_not_published_outranks_insufficient_exam_fee_on_one_registration
        """
        _program, form, _candidate, application = _assembled_form_and_approved_application(api)
        assert form["status"] == "ASSEMBLED"

        refused = api.create_exam_registration(
            f.create_registration_payload(application["id"], form["id"], UNDERPAID),
            fx.EXAM_OPERATIONS)

        validate_error(refused, ApiErrorId.ERR_FORM_NOT_PUBLISHED.value, 409)

    def test_publishing_the_form_exposes_the_fee_rule_for_an_identical_body(self, api):
        """Once the form is published the byte-identical underpaid body flips to the
        fee refusal, so the two rules differ only in rank.

        PRD §2.7: "**Exam fee.** The tendered `fee_paid_cents` is at least the
        program's `exam_fee_cents` → otherwise `ERR_EXAM_FEE_INSUFFICIENT` (402)."

        PRD §3.5: "Publication is the `ProgramAdmin`'s gate, optionally annotated
        with a `publication_note`, and it moves the form `CUT_SCORE_SET →
        PUBLISHED`."

        Design: Difficulty/priority_pair_validation_conflict/exam_form_not_published_outranks_insufficient_exam_fee_on_one_registration
        """
        _program, form, _candidate, application = _assembled_form_and_approved_application(api)
        body = f.create_registration_payload(application["id"], form["id"], UNDERPAID)
        validate_error(api.create_exam_registration(body, fx.EXAM_OPERATIONS),
                       ApiErrorId.ERR_FORM_NOT_PUBLISHED.value, 409)

        rated = fx.submit_ratings(api, form["id"], [0.6])
        adopted = fx.cut_score_form(api, form["id"], rated["version"])
        assert adopted["status"] == "CUT_SCORE_SET"
        assert adopted["raw_cut_score"] == 0
        published = validate_success(api.publish_form(
            form["id"], f.publish_form_payload(), fx.PROGRAM_ADMIN), 200)
        assert published["status"] == "PUBLISHED"

        refused = api.create_exam_registration(body, fx.EXAM_OPERATIONS)

        validate_error(refused, ApiErrorId.ERR_EXAM_FEE_INSUFFICIENT.value, 402)

    def test_only_the_fully_paid_body_creates_a_registration(self, api):
        """Neither refusal leaves a row behind; the paid body creates the first
        attempt with both dimensions at their initial values.

        PRD §3.7: "A new registration begins with `seat_status` `UNSCHEDULED`,
        `score_status` `NOT_APPLICABLE`, `form_reassignment_required` false,
        `session_id` and `session_ends_at` null".

        PRD §3.7: "Otherwise the new registration's `attempt_number` is that count
        plus 1."

        Design: Difficulty/priority_pair_validation_conflict/exam_form_not_published_outranks_insufficient_exam_fee_on_one_registration
        """
        _program, form, _candidate, application = _assembled_form_and_approved_application(api)
        underpaid = f.create_registration_payload(application["id"], form["id"], UNDERPAID)
        api.create_exam_registration(underpaid, fx.EXAM_OPERATIONS)

        rated = fx.submit_ratings(api, form["id"], [0.6])
        fx.cut_score_form(api, form["id"], rated["version"])
        validate_success(api.publish_form(form["id"], f.publish_form_payload(),
                                         fx.PROGRAM_ADMIN), 200)
        api.create_exam_registration(underpaid, fx.EXAM_OPERATIONS)

        created = validate_success(api.create_exam_registration(
            f.create_registration_payload(application["id"], form["id"], 45000),
            fx.EXAM_OPERATIONS), 201)

        assert created["seat_status"] == "UNSCHEDULED"
        assert created["score_status"] == "NOT_APPLICABLE"
        assert created["attempt_number"] == 1

        registrations, _meta = validate_paginated(api.list_exam_registrations(
            fx.EXAM_OPERATIONS, {"application_id": application["id"]}))
        assert len(registrations) == 1
