"""Boundary arithmetic: the session-length cap applied last, and the compliance
run's empty candidate set against the inclusive T_180 tier instant."""
from test_helpers import (
    TEST_USERS,
    add_candidate,
    add_exam_form,
    add_proctor,
    assign_code,
    factories as f,
    get_success_data,
    purchase_batch,
    run_compliance,
    schedule_session,
    set_clock,
    setup_landscape,
    setup_sitting,
    validate_success,
)


def _approved_accommodation(api, env, candidate, multiplier, accommodation_type):
    request = get_success_data(api.create_accommodation_request(
        f.create_accommodation_request_payload(
            candidate["id"], accommodation_type=accommodation_type,
            requested_multiplier=multiplier, requested_language="ES"),
        env["provider_headers"]), 201)
    validate_success(api.open_accommodation_review(request["id"], env["admin_headers"]))
    reviewed = get_success_data(api.review_accommodation(
        request["id"], f.create_accommodation_review_payload(
            "APPROVE", approved_multiplier=multiplier,
            decision_reason="Documented processing accommodation"),
        env["admin_headers"]))
    assert reviewed["status"] == "APPROVED"
    return reviewed


def _spanish_form_with_three_accommodated_candidates(api):
    env = setup_landscape()
    form_es = add_exam_form(env, form_code="FM-ES-01", language="ES",
                            translated_extra_minutes=30)
    proctor = add_proctor(env, languages_certified=["EN", "ES"], remote_certified=True)
    candidates, accommodations, codes = [], [], []
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 3}],
                           exam_form_id=form_es["id"])
    for multiplier, kind in ((1.75, "EXTRA_TIME"), (2.0, "READER_ASSIST"),
                             (1.5, "SEPARATE_ROOM")):
        candidate = add_candidate(env, preferred_language="ES")
        candidates.append(candidate)
        accommodations.append(
            _approved_accommodation(api, env, candidate, multiplier, kind))
        code, batch = assign_code(env, batch, candidate)
        codes.append(code)
    env.update({"form_es": form_es, "proctor": proctor, "candidates": candidates,
                "accommodations": accommodations, "codes": codes, "batch": batch})
    return env


def test_allowed_minutes_landing_exactly_on_the_cap_is_not_clamped(api):
    """round_half_up(120 * 1.75) = 210 plus the 30-minute translation allowance is
    exactly 240, so the cap changes nothing.

    PRD: "The uncapped figure is the form's `base_minutes` multiplied by the
    multiplier and rounded half up to a whole number of minutes **first**, and only
    then increased by the translation allowance and the delivery allowance."

    PRD: "The translation allowance is the form's `translated_extra_minutes` when
    the form's `language` is anything other than `EN`, and zero when the form is in
    `EN`."

    Design: Difficulty/boundary_precision_check/allowed_minutes_at_exactly_max_session_minutes_is_not_clamped
    """
    env = _spanish_form_with_three_accommodated_candidates(api)

    session = schedule_session(
        env, env["candidates"][0], env["codes"][0], "2026-09-10T09:00:00Z",
        proctor=env["proctor"], exam_form_id=env["form_es"]["id"],
        accommodation_request_id=env["accommodations"][0]["id"])

    assert session["allowed_minutes"] == 240
    assert session["scheduled_end_at"] == "2026-09-10T13:00:00Z"


def test_the_cap_is_applied_after_both_additive_allowances(api):
    """A 2.0 multiplier on a remote Spanish sitting computes 240 + 30 + 10 = 280,
    which the cap trims back to 240.

    PRD: "`allowed_minutes` is the lesser of 240 minutes (four hours) and that
    uncapped figure, so the cap is applied last, after both additive allowances."

    PRD: "The delivery allowance is 10 minutes of remote setup time for a `REMOTE`
    sitting and zero for an `IN_PERSON` one."

    Design: Difficulty/boundary_precision_check/allowed_minutes_at_exactly_max_session_minutes_is_not_clamped
    """
    env = _spanish_form_with_three_accommodated_candidates(api)

    session = schedule_session(
        env, env["candidates"][1], env["codes"][1], "2026-09-11T09:00:00Z",
        proctor=env["proctor"], delivery_mode="REMOTE", testing_site=None,
        exam_form_id=env["form_es"]["id"],
        accommodation_request_id=env["accommodations"][1]["id"])

    assert session["allowed_minutes"] == 240
    assert session["scheduled_end_at"] == "2026-09-11T13:00:00Z"
    assert session["testing_site_id"] is None


def test_a_shorter_sitting_stays_below_the_cap_and_both_reservations_add_up(api):
    """A 1.5 multiplier gives 180 + 30 = 210 minutes, and the cap does not inflate
    it; the remote sitting contributes to the proctor only.

    PRD: "A site's `reserved_seat_minutes` is the sum of `allowed_minutes` over the
    sittings at that site whose `session_status` is `SCHEDULED`, `CHECKED_IN` or
    `IN_PROGRESS`, and it is maintained on every reservation and release."

    PRD: "A proctor's own `reserved_minutes` mirrors the exclusive rule: it is the
    sum of `allowed_minutes` over that proctor's sittings whose `session_status` is
    `SCHEDULED`, `CHECKED_IN` or `IN_PROGRESS` and whose `proctoring_status` is
    `ASSIGNED`."

    Design: Difficulty/boundary_precision_check/allowed_minutes_at_exactly_max_session_minutes_is_not_clamped
    """
    env = _spanish_form_with_three_accommodated_candidates(api)
    admin = env["admin_headers"]
    schedule_session(env, env["candidates"][0], env["codes"][0],
                     "2026-09-10T09:00:00Z", proctor=env["proctor"],
                     exam_form_id=env["form_es"]["id"],
                     accommodation_request_id=env["accommodations"][0]["id"])
    schedule_session(env, env["candidates"][1], env["codes"][1],
                     "2026-09-11T09:00:00Z", proctor=env["proctor"],
                     delivery_mode="REMOTE", testing_site=None,
                     exam_form_id=env["form_es"]["id"],
                     accommodation_request_id=env["accommodations"][1]["id"])

    third = schedule_session(
        env, env["candidates"][2], env["codes"][2], "2026-09-10T13:15:00Z",
        proctor=env["proctor"], exam_form_id=env["form_es"]["id"],
        accommodation_request_id=env["accommodations"][2]["id"])

    assert third["allowed_minutes"] == 210
    assert third["scheduled_end_at"] == "2026-09-10T16:45:00Z"
    assert get_success_data(api.get_testing_site(
        env["testing_site"]["id"], admin))["reserved_seat_minutes"] == 450
    assert get_success_data(api.get_proctor(
        env["proctor"]["id"], admin))["reserved_minutes"] == 690


def test_a_run_with_nothing_due_reports_zero_notices_and_an_empty_array(api):
    """A clock strictly before every deadline still succeeds; the empty candidate
    set is reported as zero and [], not as an error.

    PRD: "An empty candidate set is not an error: the run succeeds with
    `reminder_notices_sent_count` at zero and `notified_certificate_ids` as an
    empty array."

    Design: Difficulty/boundary_precision_check/compliance_run_with_nothing_due_returns_zero_and_empty_list_then_fires_at_exact_t180
    """
    env = setup_sitting(stage="POSTED", scored_correct_count=60,
                        scoring_admin_headers=TEST_USERS["scoring_admin_headers"])
    admin = env["admin_headers"]
    certificate = env["certificate"]
    assert certificate["reminder_tiers_sent"] == []

    set_clock("2026-10-01T00:00:00Z", admin)
    summary = run_compliance(env)

    assert summary["run_epoch"] == "2026-10-01T00:00:00Z"
    assert summary["reminder_notices_sent_count"] == 0
    assert summary["notified_certificate_ids"] == []
    assert summary["certificates_expired_count"] == 0
    assert summary["registrations_delinquent_count"] == 0
    assert summary["batches_expired_count"] == 0

    unchanged = get_success_data(api.get_certificate(certificate["id"], admin))
    assert unchanged["status"] == "ISSUED"
    assert unchanged["reminder_tiers_sent"] == []


def test_a_clock_exactly_on_the_recert_window_dispatches_the_t180_tier(api):
    """The inclusive boundary: the same certificate that was silent one run ago
    fires T_180 the moment the clock sits exactly on recert_window_opens_at.

    PRD: "Every boundary comparison is inclusive, so a clock sitting exactly on
    `recert_window_opens_at` dispatches `T_180`."

    PRD: "Dispatching appends the chosen tier to that certificate's
    `reminder_tiers_sent`, in dispatch order, and a tier already present is never
    appended twice, so a certificate whose `T_90` was sent by an earlier run is
    skipped rather than re-notified until it becomes due for a different tier."

    Design: Difficulty/boundary_precision_check/compliance_run_with_nothing_due_returns_zero_and_empty_list_then_fires_at_exact_t180
    """
    env = setup_sitting(stage="POSTED", scored_correct_count=60,
                        scoring_admin_headers=TEST_USERS["scoring_admin_headers"])
    admin = env["admin_headers"]
    certificate = env["certificate"]
    set_clock("2026-10-01T00:00:00Z", admin)
    assert run_compliance(env)["reminder_notices_sent_count"] == 0

    set_clock(certificate["recert_window_opens_at"], admin)
    summary = run_compliance(env)

    assert summary["run_epoch"] == certificate["recert_window_opens_at"]
    assert summary["reminder_notices_sent_count"] == 1
    assert summary["notified_certificate_ids"] == [certificate["id"]]
    assert summary["certificates_expired_count"] == 0
    assert summary["registrations_delinquent_count"] == 0
    assert summary["batches_expired_count"] == 1

    notified = get_success_data(api.get_certificate(certificate["id"], admin))
    assert notified["reminder_tiers_sent"] == ["T_180"]
    assert notified["status"] == "ISSUED"
    assert notified["recert_authorized_at"] is None
    assert get_success_data(api.get_local_registration(
        env["local_registration"]["id"], admin))["status"] == "POSTED"
