"""The remaining rejection families: code bindings, check-in bounds and voided
counts, registration from-states, duplicate certificates, credit and security holds."""
from test_helpers import (
    TEST_USERS,
    add_candidate,
    add_exam_form,
    add_jurisdiction,
    add_proctor,
    assign_code,
    check_in_session,
    factories as f,
    file_incident,
    finalize_report,
    get_success_data,
    issue_certificate,
    make_proctor_headers,
    purchase_batch,
    read_batch,
    resolve_incident,
    schedule_session,
    set_clock,
    setup_landscape,
    setup_sitting,
    start_session,
    submit_session,
    take_incident_into_review,
    validate_error,
    validate_paginated,
)

_ALT_ADMIN = TEST_USERS["platform_admin_alt_headers"]
_SCORING_ADMIN = TEST_USERS["scoring_admin_headers"]
_SECURITY_ADMIN = TEST_USERS["security_admin_headers"]


def test_a_code_is_bound_to_both_its_candidate_and_its_batchs_form(api):
    """Two ASSIGNED codes, two independent bindings: the wrong candidate and the
    wrong form each answer their own 409 before the matching triple is accepted.

    PRD: "Three referential rules bind the sitting to the objects it names: the code's
    `candidate_id` must equal the sitting's `candidate_id` or the request answers
    `ERR_ACCESS_CODE_CANDIDATE_MISMATCH` (HTTP 409); the exam form purchased for the
    code's batch must equal the sitting's `exam_form_id` or the request answers
    `ERR_ACCESS_CODE_FORM_MISMATCH` (HTTP 409); and a linked accommodation must belong to
    the same candidate with a `status` of either `UNDER_REVIEW` or `APPROVED`, failing
    which the request answers `ERR_ACCOMMODATION_CANDIDATE_MISMATCH` (HTTP 409)."

    Design: Corner/errors/access_code_mismatch_rejections_wrong_candidate_then_wrong_form
    """
    env = setup_landscape()
    admin, provider_headers = env["admin_headers"], env["provider_headers"]
    first_form = env["exam_form"]
    second_form = add_exam_form(env, form_code="FM-EN-02", version_label="2026.2")
    candidate_a = add_candidate(env)
    candidate_b = add_candidate(env)
    proctor = add_proctor(env)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 2}])
    code_a, batch = assign_code(env, batch, candidate_a)
    code_b, batch = assign_code(env, batch, candidate_b)
    assert code_b["candidate_id"] == candidate_b["id"]

    def book(candidate, form):
        return api.create_exam_session(
            f.create_exam_session_payload(
                candidate["id"], form["id"], code_a["id"], "2026-09-12T09:00:00Z",
                delivery_mode="IN_PERSON",
                testing_site_id=env["testing_site"]["id"],
                proctor_id=proctor["id"]),
            provider_headers)

    validate_error(book(candidate_b, first_form),
                   "ERR_ACCESS_CODE_CANDIDATE_MISMATCH", 409)
    validate_error(book(candidate_a, second_form),
                   "ERR_ACCESS_CODE_FORM_MISMATCH", 409)

    untouched = get_success_data(api.get_access_code(code_a["id"], provider_headers))
    assert untouched["status"] == "ASSIGNED"
    assert untouched["candidate_id"] == candidate_a["id"]

    booked = get_success_data(book(candidate_a, first_form), 201)
    assert booked["access_code_id"] == code_a["id"]
    assert booked["session_status"] == "SCHEDULED"
    _, meta = validate_paginated(api.list_exam_sessions(
        admin, params={"access_code_id": code_a["id"]}))
    assert meta["total_count"] == 1


def test_the_check_in_window_and_the_voided_counts_are_closed_intervals(api):
    """Both ends of the 45-minute check-in window are inclusive, and finalization
    refuses a voided-item count equal to the form's own scored-item count.

    PRD: "The logical clock must fall inside the window that opens 30 minutes before
    `scheduled_start_at` and closes 15 minutes after it, with both bounds inclusive; a
    clock outside that window is rejected with `ERR_CHECKIN_WINDOW_CLOSED` (HTTP 409)."

    PRD: "And the two counts must be coherent: `voided_item_count` must be strictly fewer
    than the form's `scored_item_count`, so a finalization can never key out every scored
    item and leave an empty denominator, and `voided_correct_count` must be less than or
    equal to both `voided_item_count` and the report's `raw_correct_count`."

    PRD: "Any breach of either count rule is rejected with `ERR_VOIDED_ITEM_COUNT_INVALID`
    (HTTP 422)."

    Design: Corner/errors/checkin_window_bounds_and_voided_item_count_rejections
    """
    env = setup_landscape()
    admin = env["admin_headers"]
    candidate = add_candidate(env)
    proctor = add_proctor(env)
    proctor_headers = make_proctor_headers(proctor["id"])
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 3}])
    sittings = []
    for start_at in ("2026-09-12T09:00:00Z", "2026-09-13T09:00:00Z",
                     "2026-09-14T09:00:00Z"):
        code, batch = assign_code(env, batch, candidate)
        sittings.append(schedule_session(env, candidate, code, start_at,
                                         proctor=proctor))
    first, second, third = sittings

    set_clock("2026-09-12T08:29:00Z", admin)
    early = api.check_in_exam_session(
        first["id"], f.create_check_in_payload(
            id_document_expires_on="2030-01-31"), proctor_headers)
    validate_error(early, "ERR_CHECKIN_WINDOW_CLOSED", 409)
    waiting = get_success_data(api.get_exam_session(first["id"], admin))
    assert waiting["session_status"] == "SCHEDULED"
    assert waiting["checked_in_at"] is None

    set_clock("2026-09-12T08:30:00Z", admin)
    on_the_minute = get_success_data(api.check_in_exam_session(
        first["id"], f.create_check_in_payload(
            id_document_expires_on="2030-01-31"), proctor_headers))
    assert on_the_minute["session_status"] == "CHECKED_IN"
    assert on_the_minute["checked_in_at"] == "2026-09-12T08:30:00Z"

    set_clock("2026-09-12T09:00:00Z", admin)
    start_session(env, first, proctor)
    set_clock("2026-09-12T10:30:00Z", admin)
    report = submit_session(env, first, proctor, scored_correct_count=60,
                            pretest_correct_count=4)
    assert report["status"] == "PROVISIONAL"
    assert report["raw_correct_count"] == 60

    void_everything = api.finalize_score_report(
        report["id"], f.create_finalization_payload(
            voided_item_count=80, voided_correct_count=0), _SCORING_ADMIN)
    validate_error(void_everything, "ERR_VOIDED_ITEM_COUNT_INVALID", 422)

    too_many_correct = api.finalize_score_report(
        report["id"], f.create_finalization_payload(
            voided_item_count=5, voided_correct_count=6), _SCORING_ADMIN)
    validate_error(too_many_correct, "ERR_VOIDED_ITEM_COUNT_INVALID", 422)

    final = get_success_data(api.finalize_score_report(
        report["id"], f.create_finalization_payload(
            voided_item_count=5, voided_correct_count=4), _SCORING_ADMIN))
    assert final["status"] == "FINAL"
    assert (final["voided_item_count"], final["voided_correct_count"]) == (5, 4)
    assert final["final_scaled_score"] == 75

    set_clock("2026-09-13T09:16:00Z", admin)
    late = api.check_in_exam_session(
        second["id"], f.create_check_in_payload(
            id_document_type="PASSPORT",
            id_document_expires_on="2031-05-31"), proctor_headers)
    validate_error(late, "ERR_CHECKIN_WINDOW_CLOSED", 409)
    assert get_success_data(api.get_exam_session(
        second["id"], admin))["session_status"] == "SCHEDULED"

    set_clock("2026-09-14T09:15:00Z", admin)
    last_instant = get_success_data(api.check_in_exam_session(
        third["id"], f.create_check_in_payload(
            id_document_type="MILITARY_ID",
            id_document_expires_on="2029-12-31"), proctor_headers))
    assert last_instant["session_status"] == "CHECKED_IN"
    assert last_instant["checked_in_at"] == "2026-09-14T09:15:00Z"


def test_filing_needs_a_willing_jurisdiction_and_every_hop_its_own_from_state(api):
    """The same body is refused for a certificate governed by a jurisdiction that
    does not require filing, and each registration action refuses every other state.

    PRD: "The filing's `jurisdiction_id` is copied from the certificate rather than
    supplied, and that jurisdiction must actually require local registration — filing into
    a jurisdiction whose `requires_local_registration` is false is rejected with
    `ERR_LOCAL_REGISTRATION_NOT_REQUIRED` (HTTP 409)."

    PRD: "On success the registration opens with `status` `FILED`, `filed_at` set to the
    logical clock, `refile_count` at zero, and `posting_deadline_at` computed as `filed_at`
    advanced by the jurisdiction's `posting_deadline_days` days; `posting_location`,
    `posted_at`, `rejection_reason` and `verified_by_user_id` are all null."

    PRD: "Confirming a posting on a registration that is neither `FILED` nor `DELINQUENT`
    answers `ERR_REGISTRATION_STATE_INVALID` (HTTP 409), and so does verification of a
    registration that is not `POSTED`, or a refiling of a registration that is not
    `REJECTED`."

    PRD: "On `REJECT` the registration moves `POSTED → REJECTED`, `rejection_reason`
    records the officer's note, and the posting evidence is torn down — both `posted_at`
    and `posting_location` are cleared back to null, so the holder cannot claim credit for
    a posting the inspector refused."

    PRD: "It optionally supplies a revised `establishment_address`, requires the
    registration to be `REJECTED` and the certificate to still be `ISSUED`, and moves
    `REJECTED → FILED` with `filed_at` reset to the logical clock, `posting_deadline_at`
    recomputed from that new filing instant, `posted_at` cleared, `rejection_reason`
    cleared back to null and `refile_count` grown by one."

    Design: Corner/errors/local_registration_rejections_not_required_jurisdiction_and_every_wrong_from_state
    """
    env = setup_landscape()
    admin, provider_headers = env["admin_headers"], env["provider_headers"]
    officer_headers = env["officer_headers"]
    assert env["jurisdiction"]["requires_local_registration"] is True
    exempt = add_jurisdiction(env, jurisdiction_code="TX-BEXAR",
                              name="Bexar County Health District",
                              requires_local_registration=False)
    filed_env = setup_sitting(stage="CERTIFIED", env=env,
                              candidate=add_candidate(env),
                              start_at="2026-09-12T09:00:00Z",
                              scoring_admin_headers=_SCORING_ADMIN)
    exempt_env = setup_sitting(stage="CERTIFIED", env=env,
                               candidate=add_candidate(
                                   env, jurisdiction_id=exempt["id"]),
                               start_at="2026-09-13T09:00:00Z",
                               scoring_admin_headers=_SCORING_ADMIN)

    not_required = api.create_local_registration(
        f.create_local_registration_payload(
            exempt_env["certificate"]["id"], establishment_name="Pearl Street Deli",
            establishment_address="1200 Pearl St"),
        provider_headers)
    validate_error(not_required, "ERR_LOCAL_REGISTRATION_NOT_REQUIRED", 409)
    _, meta = validate_paginated(api.list_local_registrations(
        admin, params={"certificate_id": exempt_env["certificate"]["id"]}))
    assert meta["total_count"] == 0

    registration = get_success_data(api.create_local_registration(
        f.create_local_registration_payload(
            filed_env["certificate"]["id"],
            establishment_name="Barton Springs Cafe",
            establishment_address="2200 Barton Springs Rd"),
        provider_headers), 201)
    assert registration["status"] == "FILED"
    assert registration["filed_at"] == "2026-09-13T09:00:00Z"
    assert registration["posting_deadline_at"] == "2026-10-13T09:00:00Z"
    assert registration["refile_count"] == 0

    too_soon = api.verify_local_registration(
        registration["id"], f.create_verification_payload("VERIFY"), officer_headers)
    validate_error(too_soon, "ERR_REGISTRATION_STATE_INVALID", 409)
    nothing_to_refile = api.refile_local_registration(
        registration["id"], {}, provider_headers)
    validate_error(nothing_to_refile, "ERR_REGISTRATION_STATE_INVALID", 409)

    posted = get_success_data(api.confirm_posting(
        registration["id"], f.create_posting_confirmation_payload(
            posting_location="Behind the host stand"), provider_headers))
    assert posted["status"] == "POSTED"

    rejected = get_success_data(api.verify_local_registration(
        registration["id"], f.create_verification_payload(
            "REJECT",
            rejection_reason="Certificate not legible from the customer side"),
        officer_headers))
    assert rejected["status"] == "REJECTED"
    assert rejected["posted_at"] is None
    assert rejected["posting_location"] is None

    repost = api.confirm_posting(
        registration["id"], f.create_posting_confirmation_payload(
            posting_location="Reprinted and reposted"), provider_headers)
    validate_error(repost, "ERR_REGISTRATION_STATE_INVALID", 409)

    refiled = get_success_data(api.refile_local_registration(
        registration["id"],
        {"establishment_address": "2200 Barton Springs Rd, Suite 2"},
        provider_headers))
    assert refiled["status"] == "FILED"
    assert refiled["refile_count"] == 1
    assert refiled["rejection_reason"] is None
    assert refiled["posted_at"] is None
    assert refiled["establishment_address"] == "2200 Barton Springs Rd, Suite 2"
    assert refiled["filed_at"] == "2026-09-13T09:00:00Z"
    assert refiled["posting_deadline_at"] == "2026-10-13T09:00:00Z"


def test_the_second_certificate_waits_for_the_first_ones_recert_authorization(api):
    """The same FINAL passing report is refused while the held certificate is
    unauthorized and accepted the instant it is, superseding its predecessor.

    PRD: "The candidate must not already hold an `ISSUED` certificate in that
    jurisdiction, unless that existing certificate has a non-null `recert_authorized_at` —
    which is precisely the recertification path — and a duplicate outside that path is
    rejected with `ERR_DUPLICATE_ACTIVE_CERTIFICATE` (HTTP 409)."

    PRD: "`recert_window_opens_at` is `expires_at` moved back by 180 days."

    PRD: "Authorization takes no body and does only one thing: it sets
    `recert_authorized_at` to the logical clock."

    PRD: "When a new certificate is subsequently issued for the same `candidate_id` and the
    same `jurisdiction_id`, and the prior certificate carries a non-null
    `recert_authorized_at`, the prior certificate is superseded in the same request: its
    `superseded_by_certificate_id` is set to the new certificate's `id`, forming the chain
    that lets an auditor walk a holder's whole certification history."

    Design: Corner/errors/second_certificate_is_refused_until_the_first_one_is_recert_authorized
    """
    env = setup_landscape(jurisdiction={"requires_local_registration": False})
    admin = env["admin_headers"]
    candidate = add_candidate(env)
    proctor = add_proctor(env)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 2}])
    first_code, batch = assign_code(env, batch, candidate)
    second_code, batch = assign_code(env, batch, candidate)
    first = schedule_session(env, candidate, first_code, "2026-09-12T09:00:00Z",
                             proctor=proctor)
    second = schedule_session(env, candidate, second_code, "2026-09-13T09:00:00Z",
                              proctor=proctor)

    reports = []
    for session, day in ((first, "2026-09-12"), (second, "2026-09-13")):
        check_in_session(env, session, proctor, at_clock=f"{day}T08:45:00Z")
        set_clock(f"{day}T09:00:00Z", admin)
        start_session(env, session, proctor)
        set_clock(f"{day}T10:30:00Z", admin)
        report = submit_session(env, session, proctor, scored_correct_count=60)
        reports.append(finalize_report(env, report, admin_headers=_SCORING_ADMIN))

    # Walking the second sitting left the clock on the 13th, and PRD 3.7 makes
    # `issued_at` "the logical clock". The window figures asserted below are the
    # ones projected from the first sitting's submission instant, so the clock is
    # pinned back there before issuance — PRD 2.4 states the clock "is settable
    # backwards as well as forwards".
    set_clock("2026-09-12T10:30:00Z", admin)
    held = issue_certificate(env, reports[0], admin_headers=admin)
    assert held["issued_at"] == "2026-09-12T10:30:00Z"
    assert held["expires_at"] == "2031-09-12T10:30:00Z"
    assert held["recert_window_opens_at"] == "2031-03-16T10:30:00Z"
    assert held["recert_authorized_at"] is None
    assert reports[1]["status"] == "FINAL"
    assert reports[1]["pass_flag"] is True

    duplicate = api.create_certificate(
        f.create_certificate_payload(reports[1]["id"]), _SCORING_ADMIN)
    validate_error(duplicate, "ERR_DUPLICATE_ACTIVE_CERTIFICATE", 409)
    _, meta = validate_paginated(api.list_certificates(
        admin, params={"candidate_id": candidate["id"]}))
    assert meta["total_count"] == 1

    set_clock("2031-03-16T10:30:00Z", admin)
    authorized = get_success_data(api.authorize_recertification(held["id"], _ALT_ADMIN))
    assert authorized["recert_authorized_at"] == "2031-03-16T10:30:00Z"
    assert authorized["status"] == "ISSUED"

    successor = get_success_data(api.create_certificate(
        f.create_certificate_payload(reports[1]["id"]), _SCORING_ADMIN), 201)
    assert successor["issued_at"] == "2031-03-16T10:30:00Z"
    assert successor["expires_at"] == "2036-03-16T10:30:00Z"
    assert successor["recert_window_opens_at"] == "2035-09-18T10:30:00Z"

    superseded = get_success_data(api.get_certificate(held["id"], admin))
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["superseded_by_certificate_id"] == successor["id"]

    summary = get_success_data(api.get_compliance_summary(candidate["id"], admin))
    assert summary["compliance_status"] == "CERTIFIED"
    assert summary["active_certificate_id"] == successor["id"]


def test_the_credit_guard_is_evaluated_against_each_debit_separately(api):
    """A wallet too thin for a 3,762-cent batch, then too thin for the 1,500-cent
    issuance fee: two 402s from the same provider, each leaving the ledger intact.

    PRD: "Before the ledger is touched, the provider's `credit_balance_cents` must be
    greater than or equal to `total_price_cents`; a balance exactly equal to the total is
    sufficient, and a shortfall is rejected with `ERR_INSUFFICIENT_CREDIT` (HTTP 402)."

    PRD: "Finally the issuance fee must be affordable, or the request answers
    `ERR_INSUFFICIENT_CREDIT`."

    PRD: "`issuance_fee_cents` is set to 1,500 cents and that same amount is added to the
    `lifetime_charged_cents` of the provider named by the candidate's
    `training_provider_id`, with `credit_balance_cents` recomputed."

    PRD: "Its ledger is three integer fields: `lifetime_credited_cents` accumulates every
    credit ever posted (prepayments and refunds), `lifetime_charged_cents` accumulates
    every debit ever posted (batch purchases and certificate issuance fees), and
    `credit_balance_cents` is always exactly `lifetime_credited_cents` minus
    `lifetime_charged_cents`."

    Design: Corner/errors/insufficient_credit_rejects_batch_purchase_and_certificate_issuance_separately
    """
    env = setup_landscape(prepay_cents=3000,
                          jurisdiction={"requires_local_registration": False})
    admin, provider_headers = env["admin_headers"], env["provider_headers"]
    provider_id = env["provider"]["id"]
    candidate = add_candidate(env)
    proctor = add_proctor(env)
    order = f.create_access_code_batch_payload(
        provider_id, env["exam_form"]["id"], expires_at="2027-06-30T00:00:00Z",
        line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 1}])

    unaffordable = api.create_access_code_batch(order, provider_headers)
    validate_error(unaffordable, "ERR_INSUFFICIENT_CREDIT", 402)
    ledger = get_success_data(api.get_training_provider(provider_id, provider_headers))
    assert ledger["credit_balance_cents"] == 3000
    assert ledger["lifetime_charged_cents"] == 0
    _, meta = validate_paginated(api.list_access_code_batches(
        admin, params={"training_provider_id": provider_id}))
    assert meta["total_count"] == 0

    topped_up = get_success_data(api.create_credit_adjustment(
        provider_id, f.create_credit_adjustment_payload(amount_cents=800,
                                                        memo="top-up-1"), admin))
    assert topped_up["credit_balance_cents"] == 3800

    batch = get_success_data(api.create_access_code_batch(order, provider_headers), 201)
    assert batch["total_price_cents"] == 3762
    assert get_success_data(api.get_training_provider(
        provider_id, provider_headers))["credit_balance_cents"] == 38

    code, batch = assign_code(env, batch, candidate)
    session = schedule_session(env, candidate, code, "2026-09-12T09:00:00Z",
                               proctor=proctor)
    check_in_session(env, session, proctor, at_clock="2026-09-12T08:45:00Z")
    set_clock("2026-09-12T09:00:00Z", admin)
    start_session(env, session, proctor)
    set_clock("2026-09-12T10:30:00Z", admin)
    report = submit_session(env, session, proctor, scored_correct_count=60,
                            pretest_correct_count=4)
    report = finalize_report(env, report, admin_headers=_SCORING_ADMIN)

    unfunded = api.create_certificate(
        f.create_certificate_payload(report["id"]), _SCORING_ADMIN)
    validate_error(unfunded, "ERR_INSUFFICIENT_CREDIT", 402)
    assert get_success_data(api.get_score_report(
        report["id"], admin))["status"] == "FINAL"
    _, cert_meta = validate_paginated(api.list_certificates(
        admin, params={"score_report_id": report["id"]}))
    assert cert_meta["total_count"] == 0

    second_top_up = get_success_data(api.create_credit_adjustment(
        provider_id, f.create_credit_adjustment_payload(amount_cents=1462,
                                                        memo="top-up-2"), admin))
    assert second_top_up["credit_balance_cents"] == 1500

    certificate = get_success_data(api.create_certificate(
        f.create_certificate_payload(report["id"]), _SCORING_ADMIN), 201)
    assert certificate["issuance_fee_cents"] == 1500
    assert certificate["status"] == "ISSUED"

    closing = get_success_data(api.get_training_provider(provider_id, provider_headers))
    assert closing["credit_balance_cents"] == 0
    assert closing["lifetime_charged_cents"] == 5262
    assert closing["lifetime_credited_cents"] == 5262


def test_a_critical_substantiation_bars_all_four_candidate_operations(api):
    """The hold is raised only by substantiating a CRITICAL incident, and it then
    stops assignment, scheduling, re-timing and check-in while reads stay open.

    PRD: "The candidate's `compliance_status` becomes `NON_COMPLIANT` and their
    `substantiated_incident_count` grows by one; their `security_hold` is set to true
    **only** when the incident's `severity` is `CRITICAL`, so a substantiated `MINOR` or
    `MAJOR` incident invalidates the sitting without barring the candidate from future
    scheduling."

    PRD: "A candidate placed under `security_hold` this way is barred from four operations:
    having a code assigned to them, having a new sitting scheduled, having an existing
    sitting re-timed, and checking in — all four answering `ERR_CANDIDATE_SECURITY_HOLD`."

    PRD: "19. The candidate is not under a security hold — `ERR_CANDIDATE_SECURITY_HOLD`."

    Design: Corner/errors/candidate_security_hold_blocks_assignment_scheduling_reschedule_and_check_in
    """
    env = setup_sitting(stage="CLOSED", quantity=4, start_at="2026-09-12T09:00:00Z",
                        scoring_admin_headers=_SCORING_ADMIN)
    admin, provider_headers = env["admin_headers"], env["provider_headers"]
    candidate, first_proctor = env["candidate"], env["proctor"]
    second_proctor = add_proctor(env)
    batch = env["batch"]
    spare_code, batch = assign_code(env, batch, candidate)
    unused_code, batch = assign_code(env, batch, candidate)
    later = schedule_session(env, candidate, spare_code, "2026-09-13T09:00:00Z",
                             proctor=second_proctor)
    assert later["session_status"] == "SCHEDULED"

    incident = file_incident(env, env["session"], first_proctor, severity="CRITICAL",
                             category="IMPERSONATION")
    take_incident_into_review(env, incident, admin_headers=_SECURITY_ADMIN)
    resolved = resolve_incident(env, incident, "SUBSTANTIATE",
                               admin_headers=_SECURITY_ADMIN)
    assert resolved["status"] == "SUBSTANTIATED"

    held = get_success_data(api.get_candidate(candidate["id"], provider_headers))
    assert held["security_hold"] is True
    assert held["compliance_status"] == "NON_COMPLIANT"
    assert held["substantiated_incident_count"] == 1

    before = read_batch(env, batch["id"])
    assert before["available_count"] == 1
    barred_assignment = api.assign_access_code(
        batch["id"],
        f.create_assignment_payload(candidate["id"], before["version"], "EXAM_ONLY"),
        provider_headers)
    validate_error(barred_assignment, "ERR_CANDIDATE_SECURITY_HOLD", 409)
    after = read_batch(env, batch["id"])
    assert (after["available_count"], after["version"]) == (1, before["version"])

    barred_scheduling = api.create_exam_session(
        f.create_exam_session_payload(
            candidate["id"], env["exam_form"]["id"], unused_code["id"],
            "2026-09-20T09:00:00Z", delivery_mode="IN_PERSON",
            testing_site_id=env["testing_site"]["id"],
            proctor_id=second_proctor["id"]),
        provider_headers)
    validate_error(barred_scheduling, "ERR_CANDIDATE_SECURITY_HOLD", 409)

    barred_reschedule = api.reschedule_exam_session(
        later["id"],
        f.create_reschedule_payload("2026-09-20T09:00:00Z", later["version"]),
        provider_headers)
    validate_error(barred_reschedule, "ERR_CANDIDATE_SECURITY_HOLD", 409)
    frozen = get_success_data(api.get_exam_session(later["id"], provider_headers))
    assert frozen["scheduled_start_at"] == "2026-09-13T09:00:00Z"
    assert frozen["version"] == later["version"]

    set_clock("2026-09-13T08:45:00Z", admin)
    barred_check_in = api.check_in_exam_session(
        later["id"], f.create_check_in_payload(id_document_expires_on="2030-01-31"),
        make_proctor_headers(second_proctor["id"]))
    validate_error(barred_check_in, "ERR_CANDIDATE_SECURITY_HOLD", 409)

    still_readable = get_success_data(api.get_exam_session(later["id"],
                                                          provider_headers))
    assert still_readable["session_status"] == "SCHEDULED"
    assert still_readable["version"] == later["version"]
    summary = get_success_data(api.get_compliance_summary(candidate["id"], admin))
    assert summary["compliance_status"] == "NON_COMPLIANT"
    assert summary["active_certificate_id"] is None
