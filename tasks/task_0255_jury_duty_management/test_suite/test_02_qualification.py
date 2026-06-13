"""Qualification questionnaire evaluation and its branching.

Translates corner-design instances from §1.9 sections `entities`
(Computed Fields) and `state_machines` (Invalid Transitions).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    qualification_payload,
    make_juror_headers,
    setup_summoned, get_summons, get_juror,
)


def test_ineligible_questionnaire_excuses_summons_and_marks_juror(api):
    """PRD §3.3: "When the response evaluates to `INELIGIBLE`, the juror's
    `qualification_status` is set to `INELIGIBLE` and the summons short-circuits
    directly to the terminal `EXCUSED` state, the excusal reason being
    ineligibility itself."
    PRD §3.3: "The juror qualifies only when all of the following hold together:
    `is_citizen` is true, `is_resident` is true, `english_proficient` is true,
    `felony_conviction` is false, and the computed age is at least 18."

    Design: Corner/entities/questionnaire_ineligible_marks_juror_and_excuses_summons
    """
    s = setup_summoned(term_overrides={"name": "C5"})
    resp = api.submit_qualification(
        s["summons"]["id"],
        qualification_payload(is_citizen=False),
        make_juror_headers(s["juror"]["id"]),
    )
    data = validate_success(resp, 201)
    assert data["evaluated_status"] == "INELIGIBLE", (
        f"is_citizen false must evaluate INELIGIBLE, got {data['evaluated_status']}"
    )
    assert get_summons(s["summons"]["id"])["status"] == "EXCUSED"
    assert get_juror(s["juror"]["id"])["qualification_status"] == "INELIGIBLE"


def test_second_questionnaire_on_qualified_pending_invalid_state(api):
    """PRD §3.3: "Exactly one qualification response may exist per summons, and the
    summons must be in `SUMMONED` when it is submitted; a second submission or one
    against a summons past `SUMMONED` is an invalid-state condition
    (`ERR_INVALID_STATE`, HTTP 409)."

    Design: Corner/state_machines/requalify_already_qualified_summons_invalid_state
    """
    s = setup_summoned(term_overrides={"name": "S1"})
    headers = make_juror_headers(s["juror"]["id"])
    # First submission moves SUMMONED -> QUALIFIED_PENDING.
    validate_success(api.submit_qualification(s["summons"]["id"], qualification_payload(), headers), 201)
    # Second submission must be rejected.
    resp = api.submit_qualification(s["summons"]["id"], qualification_payload(), headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_summons(s["summons"]["id"])["status"] == "QUALIFIED_PENDING"
