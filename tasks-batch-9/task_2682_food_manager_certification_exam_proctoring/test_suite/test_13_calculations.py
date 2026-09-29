"""Arithmetic with a right answer: calendar-month validity, half-up minute
rounding, the additive allowances, whole-order volume tiers and refund tiers."""
from test_helpers import (
    TEST_USERS,
    add_candidate,
    add_exam_form,
    add_proctor,
    assign_code,
    check_in_session,
    factories as f,
    finalize_report,
    get_success_data,
    issue_certificate,
    purchase_batch,
    run_compliance,
    schedule_session,
    set_clock,
    setup_landscape,
    setup_sitting,
    shift_iso,
    start_session,
    submit_session,
    validate_paginated,
)

_SCORING_ADMIN = TEST_USERS["scoring_admin_headers"]
_ALT_ADMIN = TEST_USERS["platform_admin_alt_headers"]


def _accommodation(api, env, candidate, requested, approved=None, decide=True):
    """File one accommodation, take it into review and optionally approve it."""
    request = get_success_data(api.create_accommodation_request(
        f.create_accommodation_request_payload(
            candidate["id"], accommodation_type="EXTRA_TIME",
            requested_multiplier=requested, documentation_ref="DOC-ADA-118"),
        env["provider_headers"]), 201)
    request = get_success_data(api.open_accommodation_review(request["id"], _ALT_ADMIN))
    if not decide:
        return request
    return get_success_data(api.review_accommodation(
        request["id"], f.create_accommodation_review_payload(
            "APPROVE", approved_multiplier=approved or requested), _ALT_ADMIN))


def test_the_certificate_window_walks_calendar_months_and_a_180_day_offset(api):
    """A 60-month cycle lands on the same day of the month five years out, and the
    recert window opens exactly 180 days before that.

    PRD: "`expires_at` is `issued_at` advanced by that jurisdiction's
    `recert_cycle_months` in calendar months, landing on the same day of the month —
    month arithmetic, not repeated 30-day steps, so a certificate issued on 15 March
    with a 60-month cycle expires on 15 March five years later."

    PRD: "`recert_window_opens_at` is `expires_at` moved back by 180 days."

    PRD: "`issuance_fee_cents` is set to 1,500 cents and that same amount is added
    to the `lifetime_charged_cents` of the provider named by the candidate's
    `training_provider_id`, with `credit_balance_cents` recomputed."

    Design: Corner/calculations/certificate_validity_window_uses_calendar_months_and_a_180_day_recert_offset
    """
    env = setup_landscape()
    admin = env["admin_headers"]
    candidate = add_candidate(env)
    proctor = add_proctor(env)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 1}])
    code, batch = assign_code(env, batch, candidate)
    session = schedule_session(env, candidate, code, "2026-09-12T09:00:00Z",
                               proctor=proctor)
    session = check_in_session(env, session, proctor, at_clock="2026-09-12T08:45:00Z")
    set_clock("2026-09-12T09:00:00Z", admin)
    session = start_session(env, session, proctor)
    set_clock("2026-09-12T10:30:00Z", admin)
    report = submit_session(env, session, proctor, scored_correct_count=60)
    report = finalize_report(env, report, admin_headers=_SCORING_ADMIN)
    assert report["pass_flag"] is True

    certificate = issue_certificate(env, report, admin_headers=_SCORING_ADMIN)

    assert certificate["status"] == "ISSUED"
    assert certificate["candidate_id"] == candidate["id"]
    assert certificate["score_report_id"] == report["id"]
    assert certificate["jurisdiction_id"] == env["jurisdiction"]["id"]
    assert certificate["issued_at"] == "2026-09-12T10:30:00Z"
    assert certificate["expires_at"] == "2031-09-12T10:30:00Z"
    assert certificate["recert_window_opens_at"] == "2031-03-16T10:30:00Z"
    assert certificate["issuance_fee_cents"] == 1500
    assert certificate["reminder_tiers_sent"] == []
    assert certificate["recert_authorized_at"] is None
    assert certificate["superseded_by_certificate_id"] is None
    assert certificate["revocation_reason"] is None
    assert certificate["certificate_number"]
    assert get_success_data(api.get_candidate(
        candidate["id"], admin))["compliance_status"] == "CERTIFIED"
    ledger = get_success_data(api.get_training_provider(env["provider"]["id"], admin))
    assert ledger["lifetime_charged_cents"] == 5262
    assert ledger["lifetime_credited_cents"] == 500000
    assert ledger["credit_balance_cents"] == 494738


def test_the_multiplier_product_is_rounded_half_up_before_any_allowance(api):
    """105 base minutes at 1.5 is the exact half 157.5, which must resolve upward to
    158 and drive both the interval end and the reservation.

    PRD: "The uncapped figure is the form's `base_minutes` multiplied by the
    multiplier and rounded half up to a whole number of minutes **first**, and only
    then increased by the translation allowance and the delivery allowance."

    PRD: "`scheduled_end_at` is `scheduled_start_at` advanced by `allowed_minutes`
    minutes, and it is the interval end that both occupancy rules of §2.9 use."

    Design: Corner/calculations/allowed_minutes_rounds_the_multiplier_product_half_up_before_the_allowances
    """
    env = setup_landscape(testing_site={"seat_count": 2})
    form = add_exam_form(env, form_code="FM-EN-105", base_minutes=105)
    candidate = add_candidate(env)
    accommodation = _accommodation(api, env, candidate, 1.5)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 1}],
                           exam_form_id=form["id"])
    code, batch = assign_code(env, batch, candidate)

    session = schedule_session(env, candidate, code, "2026-09-10T09:00:00Z",
                               exam_form_id=form["id"],
                               accommodation_request_id=accommodation["id"])

    assert session["allowed_minutes"] == 158
    assert session["scheduled_end_at"] == "2026-09-10T11:38:00Z"
    assert get_success_data(api.get_testing_site(
        env["testing_site"]["id"], env["admin_headers"]))["reserved_seat_minutes"] == 158
    assert session["session_status"] == "SCHEDULED"
    assert session["proctoring_status"] == "PENDING_ASSIGNMENT"


def test_a_remote_translated_sitting_adds_both_additive_allowances(api):
    """120 + 30 translation + 10 remote setup is 160 minutes, and the remote sitting
    holds proctor minutes without touching any site.

    PRD: "The translation allowance is the form's `translated_extra_minutes` when
    the form's `language` is anything other than `EN`, and zero when the form is in
    `EN`."

    PRD: "The delivery allowance is 10 minutes of remote setup time for a `REMOTE`
    sitting and zero for an `IN_PERSON` one."

    Design: Corner/calculations/remote_translated_sitting_adds_both_additive_allowances
    """
    env = setup_landscape()
    form = add_exam_form(env, form_code="FM-ES-01", language="ES",
                         base_minutes=120, translated_extra_minutes=30)
    candidate = add_candidate(env, preferred_language="ES")
    proctor = add_proctor(env, languages_certified=["ES"], remote_certified=True)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 1}],
                           exam_form_id=form["id"])
    code, batch = assign_code(env, batch, candidate)

    session = schedule_session(env, candidate, code, "2026-09-10T09:00:00Z",
                               proctor=proctor, delivery_mode="REMOTE",
                               testing_site=None, exam_form_id=form["id"])

    assert session["allowed_minutes"] == 160
    assert session["scheduled_end_at"] == "2026-09-10T11:40:00Z"
    assert session["testing_site_id"] is None
    assert session["delivery_mode"] == "REMOTE"
    assert get_success_data(api.get_testing_site(
        env["testing_site"]["id"], env["admin_headers"]))["reserved_seat_minutes"] == 0
    assert get_success_data(api.get_proctor(
        proctor["id"], env["admin_headers"]))["reserved_minutes"] == 160
    assert session["session_status"] == "SCHEDULED"
    assert session["proctoring_status"] == "ASSIGNED"


def test_a_void_refunds_only_the_codes_that_were_still_available(api):
    """Two of three units are refundable, the gross is keyed to the pro-rata share
    and the restock tier is chosen from that gross rather than from the net.

    PRD: "Step two computes the gross credit as the batch's `total_price_cents`
    multiplied by the refundable-unit count and divided by `quantity_purchased`,
    rounded half up to a whole number of cents; that figure is stored in
    `void_gross_credit_cents`."

    PRD: "Step three chooses the restock fee rate **from that gross credit, not
    from the net**: five percent when the gross credit is 50,000 cents (five hundred
    dollars) or more, otherwise ten percent when it is 10,000 cents (one hundred
    dollars) or more, otherwise fifteen percent."

    PRD: "Only codes whose `status` is still `AVAILABLE` at the instant of the void
    are refundable; codes already `ASSIGNED` or `CONSUMED`, and codes previously
    `VOIDED` or `EXPIRED`, are excluded from the refund and are left in whatever
    status they hold."

    Design: Corner/calculations/void_refunds_only_the_still_available_codes_of_a_partly_assigned_batch
    """
    env = setup_landscape()
    provider_headers, admin = env["provider_headers"], env["admin_headers"]
    candidate = add_candidate(env)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 3}])
    assert batch["total_price_cents"] == 11286
    assert get_success_data(api.get_training_provider(
        env["provider"]["id"], admin))["credit_balance_cents"] == 488714
    kept, batch = assign_code(env, batch, candidate)
    assert batch["available_count"] == 2

    voided = get_success_data(api.void_access_code_batch(
        batch["id"], f.create_void_payload(batch["version"],
                                           reason="Cohort cancelled by the client"),
        provider_headers))

    assert voided["void_gross_credit_cents"] == 7524
    assert voided["void_restock_fee_cents"] == 1129
    assert voided["void_net_credit_cents"] == 6395
    assert voided["status"] == "VOIDED"
    assert voided["available_count"] == 0
    assert voided["assigned_count"] == 1
    assert voided["consumed_count"] == 0
    assert voided["voided_count"] == 2
    assert voided["version"] == batch["version"] + 1

    assert get_success_data(api.get_access_code(
        kept["id"], provider_headers))["status"] == "ASSIGNED"
    codes, meta = validate_paginated(api.list_access_codes(
        provider_headers, params={"batch_id": batch["id"],
                                  "status": "VOIDED"}))
    assert meta["total_count"] == 2

    ledger = get_success_data(api.get_training_provider(env["provider"]["id"], admin))
    assert ledger["lifetime_credited_cents"] == 506395
    assert ledger["lifetime_charged_cents"] == 11286
    assert ledger["credit_balance_cents"] == 495109


def test_a_lower_jurisdiction_override_never_lowers_the_national_bar(api):
    """An override of 65 sits below the form's 70, so the frozen cut stays 70 and a
    69 is a failure rather than the pass a naive override would produce.

    PRD: "when that jurisdiction's `min_passing_score_override` is null the effective
    cut is simply the form's `national_cut_score`, and when an override is present
    the effective cut is the greater of the form's `national_cut_score` and that
    override — so a jurisdiction may only make passing harder, never easier."

    PRD: "The `provisional_scaled_score` is 100 multiplied by `raw_correct_count`,
    divided by the form's `scored_item_count`, rounded half up to a whole number; the
    ratio itself is never rounded before the multiplication."

    PRD: "`pass_flag` is then set to true when `final_scaled_score` is greater than
    or equal to the report's frozen `effective_cut_score`, and false otherwise — a
    score exactly equal to the cut is a pass."

    Design: Corner/calculations/effective_cut_score_takes_the_max_so_a_lower_override_never_lowers_the_bar
    """
    env = setup_landscape(jurisdiction={"min_passing_score_override": 65})
    admin = env["admin_headers"]
    assert env["jurisdiction"]["min_passing_score_override"] == 65
    assert env["exam_form"]["national_cut_score"] == 70
    assert env["exam_form"]["scored_item_count"] == 80

    env = setup_sitting(stage="SUBMITTED", env=env, scored_correct_count=55)
    report = env["score_report"]
    assert report["effective_cut_score"] == 70
    assert report["raw_correct_count"] == 55
    assert report["provisional_scaled_score"] == 69
    assert report["pass_flag"] is None

    final = finalize_report(env, report, admin_headers=_SCORING_ADMIN)

    assert final["effective_cut_score"] == 70
    assert final["final_scaled_score"] == 69
    assert final["pass_flag"] is False
    assert get_success_data(api.get_exam_session(
        env["session"]["id"], admin))["session_status"] == "CLOSED"
    assert get_success_data(api.get_candidate(
        env["candidate"]["id"], admin))["compliance_status"] == "NOT_CERTIFIED"


def test_nineteen_units_at_list_price_cost_what_twenty_do_at_five_percent_off(api):
    """The first discount tier exactly cancels the extra unit: 19 undiscounted units
    and 20 units at five percent off both come to 71,478 cents.

    PRD: "A volume discount is then chosen from that line's own `quantity` alone:
    fifteen percent when the quantity is 100 or more, otherwise ten percent when it
    is 50 or more, otherwise five percent when it is 20 or more, otherwise no
    discount."

    PRD: "The line's subtotal is the base unit price multiplied by the line's
    quantity multiplied by one minus the discount rate, rounded half up to a whole
    number of cents."

    Design: Corner/calculations/nineteen_units_at_list_price_cost_the_same_as_twenty_at_the_first_discount
    """
    env = setup_landscape()
    provider_headers, admin = env["provider_headers"], env["admin_headers"]

    nineteen = purchase_batch(
        env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 19}])
    twenty = purchase_batch(
        env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 20}])

    assert nineteen["total_price_cents"] == 71478
    assert twenty["total_price_cents"] == 71478
    assert nineteen["quantity_purchased"] == 19
    assert twenty["quantity_purchased"] == 20
    assert nineteen["available_count"] == 19
    assert twenty["available_count"] == 20

    _, meta = validate_paginated(api.list_access_codes(
        provider_headers, params={"batch_id": twenty["id"],
                                  "status": "AVAILABLE", "limit": 5}))
    assert meta["total_count"] == 20

    ledger = get_success_data(api.get_training_provider(env["provider"]["id"], admin))
    assert ledger["lifetime_charged_cents"] == 142956
    assert ledger["lifetime_credited_cents"] == 500000
    assert ledger["credit_balance_cents"] == 357044


def test_approving_an_accommodation_re_times_the_sitting_and_both_holds(api):
    """While the request is under review the sitting runs at 1.0; approval re-runs the
    computation and pushes the 60-minute delta into the site and the proctor.

    PRD: "The multiplier is the linked accommodation's `approved_multiplier` when the
    sitting carries an `accommodation_request_id` **and** that request's `status` is
    `APPROVED`; in every other case — no accommodation, or an accommodation still
    `REQUESTED` or `UNDER_REVIEW`, or a `DENIED` one — the multiplier is 1.0."

    PRD: "Approval then sets `approved_multiplier` to the supplied value, or to
    `requested_multiplier` when the field was omitted, and re-times every such
    `SCHEDULED` sitting: each one has its `allowed_minutes` and `scheduled_end_at`
    recomputed by the rule in §3.5, and the resulting minute delta is applied to both
    the site's `reserved_seat_minutes` and the assigned proctor's `reserved_minutes`."

    Design: Corner/calculations/accommodation_approval_propagates_new_minutes_into_both_reservations
    """
    env = setup_landscape()
    admin = env["admin_headers"]
    site_id = env["testing_site"]["id"]
    candidate = add_candidate(env)
    proctor = add_proctor(env)
    pending = _accommodation(api, env, candidate, 1.5, decide=False)
    assert pending["status"] == "UNDER_REVIEW"
    assert pending["approved_multiplier"] is None
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 1}])
    code, batch = assign_code(env, batch, candidate)

    session = schedule_session(env, candidate, code, "2026-09-10T09:00:00Z",
                               proctor=proctor,
                               accommodation_request_id=pending["id"])
    assert session["allowed_minutes"] == 120
    assert session["scheduled_end_at"] == "2026-09-10T11:00:00Z"
    assert get_success_data(api.get_testing_site(
        site_id, admin))["reserved_seat_minutes"] == 120
    assert get_success_data(api.get_proctor(
        proctor["id"], admin))["reserved_minutes"] == 120

    approved = get_success_data(api.review_accommodation(
        pending["id"], f.create_accommodation_review_payload(
            "APPROVE", approved_multiplier=1.5), _ALT_ADMIN))
    assert approved["status"] == "APPROVED"
    assert float(approved["approved_multiplier"]) == 1.5

    retimed = get_success_data(api.get_exam_session(session["id"], admin))
    assert retimed["allowed_minutes"] == 180
    assert retimed["scheduled_end_at"] == "2026-09-10T12:00:00Z"
    assert retimed["scheduled_start_at"] == "2026-09-10T09:00:00Z"
    assert retimed["session_status"] == "SCHEDULED"
    assert retimed["reschedule_count"] == 0
    assert get_success_data(api.get_testing_site(
        site_id, admin))["reserved_seat_minutes"] == 180
    assert get_success_data(api.get_proctor(
        proctor["id"], admin))["reserved_minutes"] == 180


def test_the_run_dispatches_one_tier_and_the_replay_dispatches_nothing(api):
    """A clock past expiry picks T_LAPSED alone, and the second run finds the tier
    already recorded and sends nothing at all.

    PRD: "The due tier is chosen most-overdue-first, and exactly one is chosen:
    `T_LAPSED` when the logical clock is at or after `expires_at`; otherwise `T_30`
    when the clock is at or after 30 days before `expires_at`; otherwise `T_90` when
    the clock is at or after 90 days before `expires_at`; otherwise `T_180` when the
    clock is at or after `recert_window_opens_at`, which is 180 days before
    `expires_at`; and otherwise no tier at all, in which case the certificate is
    skipped."

    PRD: "Dispatching appends the chosen tier to that certificate's
    `reminder_tiers_sent`, in dispatch order, and a tier already present is never
    appended twice, so a certificate whose `T_90` was sent by an earlier run is
    skipped rather than re-notified until it becomes due for a different tier."

    PRD: "An empty candidate set is not an error: the run succeeds with
    `reminder_notices_sent_count` at zero and `notified_certificate_ids` as an empty
    array."

    Design: Corner/calculations/compliance_run_dispatches_only_the_most_overdue_tier_and_never_repeats_it
    """
    env = setup_sitting(stage="CERTIFIED", scored_correct_count=60,
                        expires_at="2027-06-30T00:00:00Z",
                        scoring_admin_headers=_SCORING_ADMIN)
    admin = env["admin_headers"]
    certificate = env["certificate"]
    assert certificate["reminder_tiers_sent"] == []

    lapsed_clock = shift_iso(certificate["expires_at"], days=19)
    set_clock(lapsed_clock, admin)
    first = run_compliance(env)

    assert first["run_epoch"] == lapsed_clock
    assert first["certificates_expired_count"] == 1
    assert first["registrations_delinquent_count"] == 0
    assert first["batches_expired_count"] == 1
    assert first["reminder_notices_sent_count"] == 1
    assert first["notified_certificate_ids"] == [certificate["id"]]

    after = get_success_data(api.get_certificate(certificate["id"], admin))
    assert after["status"] == "EXPIRED"
    assert after["reminder_tiers_sent"] == ["T_LAPSED"]
    assert get_success_data(api.get_candidate(
        env["candidate"]["id"], admin))["compliance_status"] == "LAPSED"

    second = run_compliance(env)

    assert second["run_epoch"] == lapsed_clock
    assert second["certificates_expired_count"] == 0
    assert second["registrations_delinquent_count"] == 0
    assert second["batches_expired_count"] == 0
    assert second["reminder_notices_sent_count"] == 0
    assert second["notified_certificate_ids"] == []
    assert get_success_data(api.get_certificate(
        certificate["id"], admin))["reminder_tiers_sent"] == ["T_LAPSED"]
