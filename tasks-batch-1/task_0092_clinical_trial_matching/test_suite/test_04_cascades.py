"""The two depth-three transitive cascades: consent activation ->
supersede prior -> reconsent enrollment, and adjudicate-related-severe ->
hold -> freeze trial (PRD §3.2, §3.5)."""
from test_helpers import (
    validate_success,
    set_clock, get_trial_version,
    setup_open_trial, create_eligible_screened_enrollment, consent_enrollment,
    create_consent_document, approve_consent,
    setup_randomized_enrollment,
    report_adverse_event, triage_adverse_event, adjudicate_adverse_event,
    activate_consent_payload,
    TEST_USERS,
)


# ─── Difficulty: transitive_cascade / consent activate -> reconsent ─


def test_consent_activation_supersedes_prior_and_reverts_enrollment(api):
    """PRD §3.2: "if a prior `ACTIVE` consent document already exists for the
    trial, that prior document is transitioned `ACTIVE → SUPERSEDED`"
    PRD §3.2: "for every enrollment whose `signed_consent_document_id` equals
    the now-superseded document and whose `enrollment_status` is `CONSENTED`,
    the system fires the reconsent edge that returns that enrollment from
    `CONSENTED` to `SCREENED`."

    Design: Difficulty/transitive_cascade/tc_consent_activate_supersede_reconsent_depth3
    """
    set_clock("2026-06-01T00:00:00Z")
    ot = setup_open_trial(num_arms=1)  # v1 ACTIVE
    trial_id, doc_v1 = ot["trial_id"], ot["doc_id"]

    enr_ctx = create_eligible_screened_enrollment(trial_id)
    consent_enrollment(enr_ctx["enrollment_id"], doc_v1)

    # Create + IRB-approve a second consent version, then activate it.
    doc_v2 = create_consent_document(trial_id, body_hash="v2")
    approve_consent(trial_id, doc_v2["id"])
    tv2 = get_trial_version(trial_id)
    validate_success(api.activate_consent_document(
        trial_id, doc_v2["id"], activate_consent_payload(tv2), TEST_USERS["sponsor_headers"],
    ), 200)

    docs = validate_success(api.list_consent_documents(trial_id, TEST_USERS["sponsor_headers"]), 200)
    by_id = {d["id"]: d for d in docs}
    assert by_id[doc_v1]["status"] == "SUPERSEDED", "prior ACTIVE consent is superseded"
    assert by_id[doc_v2["id"]]["status"] == "ACTIVE", "the newly activated consent is ACTIVE"

    enr = validate_success(api.get_enrollment(enr_ctx["enrollment_id"], TEST_USERS["coordinator_headers"]), 200)
    assert enr["enrollment_status"] == "SCREENED", "the CONSENTED enrollment reverts to SCREENED (reconsent)"


def test_reconsent_clears_signed_consent_fields(api):
    """PRD §3.4: "That reconsent clears both `signed_consent_document_id` and
    `signed_consent_version` (setting them null), sets `enrollment_status`
    back to `SCREENED`, and increments the enrollment's `version` by one."

    Design: Difficulty/transitive_cascade/tc_consent_activate_supersede_reconsent_depth3
    """
    set_clock("2026-06-01T00:00:00Z")
    ot = setup_open_trial(num_arms=1)
    trial_id, doc_v1 = ot["trial_id"], ot["doc_id"]

    enr_ctx = create_eligible_screened_enrollment(trial_id)
    consented = consent_enrollment(enr_ctx["enrollment_id"], doc_v1)
    assert consented["signed_consent_document_id"] == doc_v1, "signed doc recorded at consent"

    doc_v2 = create_consent_document(trial_id, body_hash="v2")
    approve_consent(trial_id, doc_v2["id"])
    tv2 = get_trial_version(trial_id)
    validate_success(api.activate_consent_document(
        trial_id, doc_v2["id"], activate_consent_payload(tv2), TEST_USERS["sponsor_headers"],
    ), 200)

    enr = validate_success(api.get_enrollment(enr_ctx["enrollment_id"], TEST_USERS["coordinator_headers"]), 200)
    assert enr["signed_consent_document_id"] is None, "signed_consent_document_id cleared on reconsent"
    assert enr["signed_consent_version"] is None, "signed_consent_version cleared on reconsent"


# ─── Difficulty: transitive_cascade / AE hold -> freeze trial ───────


def test_adjudicate_related_severe_holds_enrollment(api):
    """PRD §3.5: "With `relation` `RELATED`, the event becomes
    `ADJUDICATED_RELATED` and the adjudicating officer is recorded as
    `adjudicator_user_id`; if the event's `severity` is `SEVERE` or
    `LIFE_THREATENING`, this further cascades the enrollment `FLAGGED →
    HOLD`."

    Design: Difficulty/transitive_cascade/tc_adverse_event_hold_freeze_depth3
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_randomized_enrollment()
    ae = report_adverse_event(ctx["enrollment_id"], severity="SEVERE",
                              occurred_at="2026-06-01T09:00:00Z", is_serious=True)
    triage_adverse_event(ae["id"])
    adjudicate_adverse_event(ae["id"], "RELATED")

    enr = validate_success(api.get_enrollment(ctx["enrollment_id"], TEST_USERS["coordinator_headers"]), 200)
    assert enr["safety_status"] == "HOLD", "a related SEVERE adjudication holds the enrollment"


def test_hold_freezes_trial_and_increments_hold_count(api):
    """PRD §3.5: "When an enrollment goes `FLAGGED → HOLD`, the system
    increments the trial's `active_safety_holds` by one and recomputes the
    trial's `posture`, which becomes `FROZEN` because at least one hold is now
    active."

    Design: Difficulty/transitive_cascade/tc_adverse_event_hold_freeze_depth3
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_randomized_enrollment()
    ae = report_adverse_event(ctx["enrollment_id"], severity="LIFE_THREATENING",
                              occurred_at="2026-06-01T09:00:00Z", is_serious=True)
    triage_adverse_event(ae["id"])
    adjudicate_adverse_event(ae["id"], "RELATED")

    trial = validate_success(api.get_trial(ctx["trial_id"], TEST_USERS["sponsor_headers"]), 200)
    assert trial["active_safety_holds"] == 1, "the hold count increments to 1"
    assert trial["posture"] == "FROZEN", "the trial freezes while a hold is active"
