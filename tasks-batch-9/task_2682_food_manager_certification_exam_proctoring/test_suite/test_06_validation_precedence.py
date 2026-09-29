"""Requests that break two rules at once must answer with the earlier rule in the
§2.10 ordering, and each control call proves the later rule was genuinely live."""
from test_helpers import (
    TEST_USERS,
    add_candidate,
    add_proctor,
    assign_code,
    check_in_session,
    factories as f,
    finalize_report,
    get_success_data,
    purchase_batch,
    schedule_session,
    setup_landscape,
    setup_sitting,
    start_session,
    submit_session,
    validate_error,
    validate_paginated,
)

_SLOT_A = "2026-09-20T09:00:00Z"
_SLOT_CLASH = "2026-09-20T10:00:00Z"
_SCORING_ADMIN = TEST_USERS["scoring_admin_headers"]


def _one_seat_site_with_a_consumed_code(api):
    """A 1-seat site whose only seat is taken at _SLOT_A, plus a CONSUMED code."""
    env = setup_landscape(testing_site={"seat_count": 1})
    c1 = add_candidate(env)
    c2 = add_candidate(env)
    p1 = add_proctor(env, languages_certified=["EN"], remote_certified=False)
    p2 = add_proctor(env, languages_certified=["EN"], remote_certified=True)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 3}])
    code1, batch = assign_code(env, batch, c1)
    code2, batch = assign_code(env, batch, c2)
    code3, batch = assign_code(env, batch, c2)

    schedule_session(env, c1, code1, _SLOT_A, proctor=p1)
    remote = schedule_session(env, c2, code2, "2026-09-11T09:00:00Z", proctor=p2,
                              delivery_mode="REMOTE", testing_site=None)
    remote = check_in_session(env, remote, p2, biometric_match_score=92,
                             proctor_attestation=False)
    remote = start_session(env, remote, p2)
    submit_session(env, remote, p2, scored_correct_count=40)

    env.update({"c1": c1, "c2": c2, "p1": p1, "p2": p2,
                "code2": code2, "code3": code3, "remote_session": remote})
    return env


def _clash_payload(env, code):
    return f.create_exam_session_payload(
        env["c2"]["id"], env["exam_form"]["id"], code["id"], _SLOT_CLASH,
        delivery_mode="IN_PERSON",
        testing_site_id=env["testing_site"]["id"],
        proctor_id=env["p2"]["id"])


def test_consumed_code_outranks_the_seat_capacity_conflict(api):
    """The code was consumed (priority 10) and the single seat is taken
    (priority 48); the access-code state error is the one that must surface.

    PRD: "Validations are evaluated strictly in the ascending priority order
    below, and the first violated rule decides the response."

    PRD: "10. Access-code state permits it — `ERR_ACCESS_CODE_STATE_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/consumed_code_and_full_site_returns_access_code_state_invalid_not_seat_capacity
    """
    env = _one_seat_site_with_a_consumed_code(api)
    consumed = get_success_data(api.get_access_code(env["code2"]["id"],
                                                    env["provider_headers"]))
    assert consumed["status"] == "CONSUMED"

    response = api.create_exam_session(_clash_payload(env, env["code2"]),
                                       env["provider_headers"])

    validate_error(response, "ERR_ACCESS_CODE_STATE_INVALID", 409)

    # Nothing moved: no sitting was created and neither code changed status.
    _, meta = validate_paginated(api.list_exam_sessions(
        env["admin_headers"], params={"candidate_id": env["c2"]["id"]}))
    assert meta["total_count"] == 1
    assert get_success_data(api.get_access_code(
        env["code3"]["id"], env["provider_headers"]))["status"] == "ASSIGNED"


def test_the_same_slot_with_a_live_code_reports_the_seat_capacity_conflict(api):
    """Control for the pair: swapping in an ASSIGNED code leaves only the seat
    rule broken, and priority 48 then answers.

    PRD: "48. The site has a free seat — `ERR_SITE_SEAT_CAPACITY_EXCEEDED`."

    PRD: "The new sitting is rejected with `ERR_SITE_SEAT_CAPACITY_EXCEEDED`
    (HTTP 409) when the count of overlapping sittings is already greater than or
    equal to the site's `seat_count`"

    Design: Difficulty/priority_pair_validation_conflict/consumed_code_and_full_site_returns_access_code_state_invalid_not_seat_capacity
    """
    env = _one_seat_site_with_a_consumed_code(api)

    response = api.create_exam_session(_clash_payload(env, env["code3"]),
                                       env["provider_headers"])

    validate_error(response, "ERR_SITE_SEAT_CAPACITY_EXCEEDED", 409)
    _, meta = validate_paginated(api.list_exam_sessions(
        env["admin_headers"], params={"candidate_id": env["c2"]["id"]}))
    assert meta["total_count"] == 1


def _two_finalized_reports_on_an_empty_wallet(api):
    """One failing report and one passing report, with 1000 cents left in the
    provider's wallet — less than the 1500-cent issuance fee."""
    env = setup_landscape(prepay_cents=8524)
    c1 = add_candidate(env)
    c2 = add_candidate(env)
    proctor = add_proctor(env)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 2}])
    code1, batch = assign_code(env, batch, c1)
    code2, batch = assign_code(env, batch, c2)

    # Both sittings are scheduled while the clock still sits at its 2026-08-01
    # default, because PRD 3.5 requires every `scheduled_start_at` to clear a
    # 1,440-minute lead-time floor measured from the logical clock. Checking the
    # first sitting in pins the clock to 2026-09-10T09:00:00Z, so a sitting
    # booked after that point could no longer clear the floor.
    walk = []
    for name, candidate, code, start, correct in (
            ("failing", c1, code1, "2026-09-10T09:00:00Z", 40),
            ("passing", c2, code2, "2026-09-10T11:15:00Z", 60)):
        session = schedule_session(env, candidate, code, start, proctor=proctor)
        walk.append((name, session, correct))

    reports = {}
    for name, session, correct in walk:
        session = check_in_session(env, session, proctor)
        session = start_session(env, session, proctor)
        report = submit_session(env, session, proctor, scored_correct_count=correct)
        reports[name] = finalize_report(env, report, admin_headers=_SCORING_ADMIN)

    env.update({"c1": c1, "c2": c2, "reports": reports})
    return env


def test_a_failing_report_outranks_the_providers_empty_wallet(api):
    """Issuance breaks the passing rule (priority 41) and the funding rule
    (priority 51); the candidate-did-not-pass error is the one that must surface.

    PRD: "41. The score report is final and passing — `ERR_CANDIDATE_DID_NOT_PASS`."

    PRD: "51. The provider's balance covers the debit — `ERR_INSUFFICIENT_CREDIT`."

    Design: Difficulty/priority_pair_validation_conflict/failed_score_and_exhausted_credit_returns_did_not_pass_not_insufficient_credit
    """
    env = _two_finalized_reports_on_an_empty_wallet(api)
    admin = env["admin_headers"]
    failing = env["reports"]["failing"]
    assert (failing["final_scaled_score"], failing["pass_flag"]) == (50, False)
    assert failing["effective_cut_score"] == 70
    assert get_success_data(api.get_training_provider(
        env["provider"]["id"], admin))["credit_balance_cents"] == 1000

    response = api.create_certificate(
        f.create_certificate_payload(failing["id"]), admin)

    validate_error(response, "ERR_CANDIDATE_DID_NOT_PASS", 422)

    _, meta = validate_paginated(api.list_certificates(
        admin, params={"candidate_id": env["c1"]["id"]}))
    assert meta["total_count"] == 0
    ledger = get_success_data(api.get_training_provider(env["provider"]["id"], admin))
    assert ledger["lifetime_charged_cents"] == 7524
    assert ledger["credit_balance_cents"] == 1000


def test_a_passing_report_on_the_same_empty_wallet_reports_insufficient_credit(api):
    """Control for the pair: with the passing rule satisfied, only the funding
    rule is left broken and priority 51 answers.

    PRD: "Before any debit is posted the provider's `credit_balance_cents` must be
    greater than or equal to the amount about to be charged — a balance exactly
    equal to the charge is sufficient — and a shortfall is rejected with
    `ERR_INSUFFICIENT_CREDIT` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/failed_score_and_exhausted_credit_returns_did_not_pass_not_insufficient_credit
    """
    env = _two_finalized_reports_on_an_empty_wallet(api)
    admin = env["admin_headers"]
    passing = env["reports"]["passing"]
    assert (passing["final_scaled_score"], passing["pass_flag"]) == (75, True)

    response = api.create_certificate(
        f.create_certificate_payload(passing["id"]), admin)

    validate_error(response, "ERR_INSUFFICIENT_CREDIT", 402)

    _, meta = validate_paginated(api.list_certificates(
        admin, params={"candidate_id": env["c2"]["id"]}))
    assert meta["total_count"] == 0
    assert get_success_data(api.get_training_provider(
        env["provider"]["id"], admin))["credit_balance_cents"] == 1000


def test_a_provisional_report_outranks_its_own_failing_score(api):
    """Issuance from a still-PROVISIONAL failing report breaks priority 14 and
    priority 41; the score-report state error is the one that must surface.

    PRD: "14. Score report state permits it — `ERR_SCORE_REPORT_STATE_INVALID`."

    PRD: "The named report must be `FINAL` with `pass_flag` true; a
    still-`PROVISIONAL` or `VOIDED` report answers
    `ERR_SCORE_REPORT_STATE_INVALID`, and a `FINAL` report whose `pass_flag` is
    false answers `ERR_CANDIDATE_DID_NOT_PASS` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/provisional_report_and_failing_score_returns_score_report_state_invalid_first
    """
    env = setup_sitting(stage="SUBMITTED", scored_correct_count=40)
    report = env["score_report"]
    assert report["status"] == "PROVISIONAL"
    assert report["provisional_scaled_score"] == 50
    assert report["effective_cut_score"] == 70

    response = api.create_certificate(
        f.create_certificate_payload(report["id"]), env["admin_headers"])

    validate_error(response, "ERR_SCORE_REPORT_STATE_INVALID", 409)
    assert get_success_data(api.get_training_provider(
        env["provider"]["id"], env["admin_headers"]))["credit_balance_cents"] == 496238


def test_finalizing_the_same_report_then_reveals_the_failing_score_rule(api):
    """Control for the pair: once the report is FINAL the state rule is satisfied
    and the retry answers with priority 41 instead.

    PRD: "an unvoided finalization with both counts at their zero defaults
    reproduces the `provisional_scaled_score` exactly"

    PRD: "and a `FINAL` report whose `pass_flag` is false answers
    `ERR_CANDIDATE_DID_NOT_PASS` (HTTP 422)"

    Design: Difficulty/priority_pair_validation_conflict/provisional_report_and_failing_score_returns_score_report_state_invalid_first
    """
    env = setup_sitting(stage="SUBMITTED", scored_correct_count=40)
    admin = env["admin_headers"]

    final = finalize_report(env, env["score_report"], admin_headers=_SCORING_ADMIN)
    assert final["status"] == "FINAL"
    assert final["final_scaled_score"] == 50
    assert final["final_scaled_score"] == final["provisional_scaled_score"]
    assert final["pass_flag"] is False

    response = api.create_certificate(f.create_certificate_payload(final["id"]), admin)

    validate_error(response, "ERR_CANDIDATE_DID_NOT_PASS", 422)
    session = get_success_data(api.get_exam_session(env["session"]["id"], admin))
    assert (session["session_status"], session["proctoring_status"]) == (
        "CLOSED", "CLEARED")
    assert get_success_data(api.get_training_provider(
        env["provider"]["id"], admin))["credit_balance_cents"] == 496238
