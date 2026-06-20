"""Drug-screen pipeline: chain of custody, lab result, MRO review, recollection cycle,
segregation of duties, MRO assignment. Translates difficulty queue (non_linear_state_machine
/ drug_screen_recollection_cycle, priority_pair_validation_conflict / state_outranks_mro_assignment,
cross_entity_state_dependency / complete_requires_drug_screen_verified) plus corner drug-screen,
custody, RBAC, and error instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, make_clinician_headers, make_mro_headers,
    ApiErrorId, panel, create_drug_screen_payload, create_custody_event_payload,
    setup_drug_screen, setup_drug_screen_at_collected, setup_drug_screen_at_lab_reported,
    setup_drug_screen_at_mro_review, advance_drug_screen_to_at_lab,
    advance_drug_screen_to_lab_reported, advance_drug_screen_to_mro_review,
    setup_checked_in_encounter, issue_clearance, assert_custody_event,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
CLIN = TEST_USERS["clinician_headers"]
COLLECTOR = TEST_USERS["collector_headers"]


# ─── Recollection cycle (non-linear state machine) ────

def test_recollection_cycle_returns_to_awaiting_collection(api):
    """PRD §3.6: "Immediately after a recollection is ordered, the system automatically returns
    the screen from `RECOLLECT_ORDERED` to `AWAITING_COLLECTION`, resets both `lab_result` and
    `mro_verified_result` to null, and restarts the chain of custody so that fresh `COLLECT` and
    subsequent custody events are required."
    PRD §3.6: "Ordering a recollection adds one to `recollection_count`."

    Design: Difficulty/non_linear_state_machine/drug_screen_recollection_cycle
    """
    # Seal not intact -> recollection justified; lab REJECTED_FOR_TESTING.
    emp, wkr, enc, ds = setup_drug_screen_at_mro_review(
        lab_result="REJECTED_FOR_TESTING", specimen_seal_intact=False, mro_user_id="mro-1")
    out = get_success_data(api.order_recollection(ds["id"], make_mro_headers("mro-1")))
    assert out["status"] == "AWAITING_COLLECTION"
    assert out["recollection_count"] == 1
    assert out["lab_result"] is None


def test_recollection_resets_mro_verified_result(api):
    """PRD §3.6: "Immediately after a recollection is ordered, the system automatically returns
    the screen from `RECOLLECT_ORDERED` to `AWAITING_COLLECTION`, resets both `lab_result` and
    `mro_verified_result` to null, and restarts the chain of custody so that fresh `COLLECT` and
    subsequent custody events are required."

    Design: Difficulty/non_linear_state_machine/drug_screen_recollection_cycle
    """
    emp, wkr, enc, ds = setup_drug_screen_at_mro_review(
        lab_result="REJECTED_FOR_TESTING", specimen_seal_intact=False, mro_user_id="mro-1")
    out = get_success_data(api.order_recollection(ds["id"], make_mro_headers("mro-1")))
    assert out["mro_verified_result"] is None
    assert out["recollection_count"] == 1
    assert out["status"] == "AWAITING_COLLECTION"


def test_recollection_limit_reached_after_two(api):
    """PRD §3.6: "it is permitted only while `recollection_count` is less than 2 (otherwise
    `ERR_RECOLLECTION_LIMIT_REACHED`)."
    PRD §3.6: "A screen may therefore loop from `AWAITING_COLLECTION` through `MRO_REVIEW` and
    back up to two times before the recollection limit halts further loops."

    Design: Corner/errors/error_recollection_limit_reached_after_two
    """
    emp, wkr, enc, ds = setup_drug_screen_at_mro_review(
        lab_result="REJECTED_FOR_TESTING", specimen_seal_intact=False, mro_user_id="mro-1")
    # Loop twice, each time restarting custody, lab-reporting REJECTED, MRO receiving.
    for _ in range(2):
        get_success_data(api.order_recollection(ds["id"], make_mro_headers("mro-1")))
        advance_drug_screen_to_at_lab(ds["id"])
        advance_drug_screen_to_lab_reported(ds["id"], lab_result="REJECTED_FOR_TESTING")
        advance_drug_screen_to_mro_review(ds["id"], mro_user_id="mro-1")
    # Third order-recollection attempt: count already at 2.
    resp = api.order_recollection(ds["id"], make_mro_headers("mro-1"))
    validate_error(resp, ApiErrorId.ERR_RECOLLECTION_LIMIT_REACHED.value)


def test_order_recollection_not_justified_when_seal_intact_negative(api):
    """PRD §3.6: "it is justified only when `specimen_seal_intact` is false or `lab_result` is
    `REJECTED_FOR_TESTING` (otherwise `ERR_RECOLLECTION_NOT_JUSTIFIED`)".

    Design: Corner/state_machines/order_recollection_when_seal_intact_and_negative_not_justified
    """
    emp, wkr, enc, ds = setup_drug_screen_at_mro_review(
        lab_result="NEGATIVE", specimen_seal_intact=True, mro_user_id="mro-1")
    resp = api.order_recollection(ds["id"], make_mro_headers("mro-1"))
    validate_error(resp, ApiErrorId.ERR_RECOLLECTION_NOT_JUSTIFIED.value)


# ─── Custody sequencing (PRD §3.5) ────────────────────

def test_custody_lab_receive_before_collect_rejected(api):
    """PRD §3.5: "The very first custody step must be `COLLECT`, which moves an
    `AWAITING_COLLECTION` screen to `COLLECTED` and appends the event ... a non-`COLLECT` first
    step is rejected as an out-of-order custody step."
    PRD §3.5: "Any custody step recorded out of this canonical order is rejected with
    `ERR_CUSTODY_SEQUENCE_VIOLATION`."

    Design: Corner/state_machines/custody_lab_receive_before_collect_rejected
    """
    emp, wkr, enc, ds = setup_drug_screen(specimen_seal_intact=True)
    resp = api.create_custody_event(create_custody_event_payload(ds["id"], "LAB_RECEIVE"), COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_CUSTODY_SEQUENCE_VIOLATION.value)


def test_custody_seal_and_ship_keep_status_collected(api):
    """PRD §3.5: "While the screen is `COLLECTED`, the optional `SEAL` and `SHIP` events may be
    recorded without changing the screen's status."
    PRD §3.5: "a monotonic per-screen `seq` index that starts at 1 and defines custody ordering".

    Design: Corner/state_machines/custody_seal_and_ship_keep_status_collected
    """
    emp, wkr, enc, ds = setup_drug_screen_at_collected(specimen_seal_intact=True)
    seal = get_success_data(api.create_custody_event(
        create_custody_event_payload(ds["id"], "SEAL"), COLLECTOR))
    ship = get_success_data(api.create_custody_event(
        create_custody_event_payload(ds["id"], "SHIP"), COLLECTOR))
    assert seal["seq"] == 2
    assert ship["seq"] == 3
    fresh = get_success_data(api.get_drug_screen(ds["id"], ADMIN))
    assert fresh["status"] == "COLLECTED"


def test_custody_event_is_append_only_no_version(api):
    """PRD §2.4: "A **CustodyEvent** is an append-only forensic record and carries only `id` and
    `created_at` — it has neither an `updated_at` nor a `version`, because a custody event is
    never modified after it is written."

    Design: Corner/entities/custody_event_immutable_no_version_field
    """
    emp, wkr, enc, ds = setup_drug_screen_at_collected(specimen_seal_intact=True)
    # The COLLECT event (seq 1) exists; discover it via the filtered list, then read it directly.
    data = validate_success(api.list_custody_events(ADMIN, params={"drug_screen_id": ds["id"]}))
    assert len(data) >= 1
    ce_id = data[0]["id"]
    ce = validate_success(api.get_custody_event(ce_id, COLLECTOR))
    assert_custody_event(ce)
    assert ce["seq"] == 1
    assert "version" not in ce


def test_list_custody_events_ordered_by_seq(api):
    """PRD §2.3: "The chain-of-custody listing is the documented exception: custody events are
    returned ordered by their per-screen `seq` index."

    Design: Corner/endpoints/list_custody_events_ordered_by_seq
    """
    emp, wkr, enc, ds = setup_drug_screen(specimen_seal_intact=True)
    advance_drug_screen_to_at_lab(ds["id"])  # COLLECT (seq 1), LAB_RECEIVE (seq 2)
    data = validate_success(api.list_custody_events(COLLECTOR, params={"drug_screen_id": ds["id"]}))
    assert len(data) == 2
    assert data[0]["seq"] == 1 and data[0]["step"] == "COLLECT"
    assert data[1]["seq"] == 2 and data[1]["step"] == "LAB_RECEIVE"


# ─── Lab result + MRO verify (PRD §3.5, §3.6) ─────────

def test_lab_result_when_not_at_lab_rejected(api):
    """PRD §3.5: "Once the specimen is at the lab, a `Clinician` records the lab result,
    advancing the screen from `AT_LAB` to `LAB_REPORTED`; this requires the screen to be `AT_LAB`
    (otherwise `ERR_DRUG_SCREEN_NOT_AT_LAB`)".

    Design: Corner/state_machines/drug_screen_lab_result_when_not_at_lab_rejected
    """
    emp, wkr, enc, ds = setup_drug_screen_at_collected(specimen_seal_intact=True)
    resp = api.record_lab_result(ds["id"], {"lab_result": "NEGATIVE"}, CLIN)
    validate_error(resp, ApiErrorId.ERR_DRUG_SCREEN_NOT_AT_LAB.value)


def test_mro_verify_negative_lab_with_positive_inconsistent(api):
    """PRD §3.6: "if `lab_result` is `NEGATIVE`, the `mro_verified_result` must be `NEGATIVE` ...
    either inconsistency is rejected with `ERR_MRO_RESULT_INCONSISTENT`."

    Design: Corner/state_machines/mro_verify_negative_lab_with_positive_result_inconsistent
    """
    emp, wkr, enc, ds = setup_drug_screen_at_mro_review(lab_result="NEGATIVE", mro_user_id="mro-1")
    resp = api.mro_verify(ds["id"], {"mro_verified_result": "POSITIVE"}, make_mro_headers("mro-1"))
    validate_error(resp, ApiErrorId.ERR_MRO_RESULT_INCONSISTENT.value)


def test_mro_verify_rejected_lab_noncancelled_inconsistent(api):
    """PRD §3.6: "if `lab_result` is `REJECTED_FOR_TESTING`, a verification to anything other than
    cancelled is inconsistent — either inconsistency is rejected with
    `ERR_MRO_RESULT_INCONSISTENT`."

    Design: Corner/state_machines/mro_verify_rejected_lab_noncancelled_inconsistent
    """
    emp, wkr, enc, ds = setup_drug_screen_at_mro_review(
        lab_result="REJECTED_FOR_TESTING", mro_user_id="mro-1")
    resp = api.mro_verify(ds["id"], {"mro_verified_result": "NEGATIVE"}, make_mro_headers("mro-1"))
    validate_error(resp, ApiErrorId.ERR_MRO_RESULT_INCONSISTENT.value)


def test_mro_verify_positive_on_nonnegative_lab_succeeds(api):
    """PRD §3.6: "Verifying with a non-cancelled determination supplies an `mro_verified_result`
    of `NEGATIVE`, `POSITIVE`, or `REFUSAL` and advances the screen to `VERIFIED`".

    Design: Corner/state_machines/mro_verify_positive_on_nonnegative_lab_succeeds
    """
    emp, wkr, enc, ds = setup_drug_screen_at_mro_review(
        lab_result="NON_NEGATIVE", mro_user_id="mro-1")
    out = validate_success(api.mro_verify(ds["id"], {"mro_verified_result": "POSITIVE"},
                                          make_mro_headers("mro-1")))
    assert out["status"] == "VERIFIED"
    assert out["mro_verified_result"] == "POSITIVE"


def test_mro_verify_cancelled_terminal(api):
    """PRD §3.6: "Verifying with a cancelled determination supplies `mro_verified_result` of
    `CANCELLED` and moves the screen to `CANCELLED`, recording `mro_verified_result` as
    `CANCELLED`".

    Design: Corner/state_machines/mro_verify_cancelled_terminal_satisfies_completion
    """
    emp, wkr, enc, ds = setup_drug_screen_at_mro_review(
        lab_result="REJECTED_FOR_TESTING", mro_user_id="mro-1")
    out = validate_success(api.mro_verify(ds["id"], {"mro_verified_result": "CANCELLED"},
                                          make_mro_headers("mro-1")))
    assert out["status"] == "CANCELLED"
    assert out["mro_verified_result"] == "CANCELLED"


# ─── State-vs-safety priority (difficulty) ────────────

def test_state_outranks_mro_assignment(api):
    """PRD §2.6: "the target resource's state precondition for the requested transition (the
    `ERR_..._NOT_...` state errors, 409)" is evaluated before "Business-rule checks specific to
    an operation — custody sequencing, MRO assignment, segregation of duties ...".
    PRD §3.6: "it requires the screen to be `MRO_REVIEW` (otherwise
    `ERR_DRUG_SCREEN_NOT_IN_MRO_REVIEW`)".

    Design: Difficulty/priority_pair_validation_conflict/state_outranks_mro_assignment
    """
    # Screen at AT_LAB (not yet MRO_REVIEW); a wrong MRO calls mro-verify.
    emp, wkr, enc, ds = setup_drug_screen(specimen_seal_intact=True, mro_user_id="mro-1")
    advance_drug_screen_to_at_lab(ds["id"])
    resp = api.mro_verify(ds["id"], {"mro_verified_result": "NEGATIVE"},
                          make_mro_headers("wrong-mro"))
    validate_error(resp, ApiErrorId.ERR_DRUG_SCREEN_NOT_IN_MRO_REVIEW.value)


def test_state_outranks_mro_assignment_at_collected(api):
    """PRD §2.6: "the target resource's state precondition for the requested transition (the
    `ERR_..._NOT_...` state errors, 409)" is evaluated before "Business-rule checks specific to
    an operation — custody sequencing, MRO assignment, segregation of duties ...".
    PRD §3.6: "it requires the screen to be `MRO_REVIEW` (otherwise
    `ERR_DRUG_SCREEN_NOT_IN_MRO_REVIEW`)".

    Design: Difficulty/priority_pair_validation_conflict/state_outranks_mro_assignment
    """
    # Second translation: screen still at COLLECTED (before lab), wrong MRO calls mro-verify.
    emp, wkr, enc, ds = setup_drug_screen_at_collected(specimen_seal_intact=True, mro_user_id="mro-1")
    resp = api.mro_verify(ds["id"], {"mro_verified_result": "NEGATIVE"},
                          make_mro_headers("wrong-mro"))
    validate_error(resp, ApiErrorId.ERR_DRUG_SCREEN_NOT_IN_MRO_REVIEW.value)


# ─── MRO assignment & segregation of duties (PRD §3.6) ─

def test_mro_not_assigned_wrong_mro_id_forbidden(api):
    """PRD §3.6: "the acting operator's `X-User-ID` must equal the owning employer's assigned
    `mro_user_id`; an operator who is not the assigned MRO is rejected with
    `ERR_MRO_NOT_ASSIGNED`."

    Design: Corner/rbac/mro_not_assigned_wrong_mro_id_forbidden
    """
    emp, wkr, enc, ds = setup_drug_screen_at_lab_reported(lab_result="NEGATIVE", mro_user_id="mro-1")
    resp = api.mro_receive(ds["id"], make_mro_headers("mro-other"))
    validate_error(resp, ApiErrorId.ERR_MRO_NOT_ASSIGNED.value)


def test_mro_segregation_of_duties_mro_equals_clinician_forbidden(api):
    """PRD §3.6: "for the receive and verify actions, the acting MRO's `X-User-ID` must differ
    from the encounter's pinned `clinician_user_id`; an MRO who is also the encounter's clinician
    is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/mro_segregation_of_duties_mro_equals_clinician_forbidden
    """
    # Employer's mro_user_id == shared-1; encounter created by clinician shared-1.
    emp, wkr, enc, ds = setup_drug_screen_at_lab_reported(
        lab_result="NEGATIVE", mro_user_id="shared-1", clinician_id="shared-1")
    resp = api.mro_receive(ds["id"], make_mro_headers("shared-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ─── Cross-entity completion guard (difficulty) ───────

def test_complete_requires_drug_screen_verified(api):
    """PRD §3.4: "for a `DRUG_SCREEN` the `DrugScreen.status` must be either `VERIFIED` or
    `CANCELLED` (otherwise `ERR_DRUG_SCREEN_NOT_VERIFIED`)".

    Design: Difficulty/cross_entity_state_dependency/complete_requires_drug_screen_verified
    """
    # Screen at AT_LAB (not VERIFIED); a FIT clearance is issued so the missing-clearance branch
    # cannot fire — only the drug-screen-not-verified precondition can.
    emp, wkr, enc, ds = setup_drug_screen(specimen_seal_intact=True, mro_user_id="mro-1")
    advance_drug_screen_to_at_lab(ds["id"])
    issue_clearance(enc["id"], "FIT")
    resp = api.complete_encounter(enc["id"], CLIN)
    validate_error(resp, ApiErrorId.ERR_DRUG_SCREEN_NOT_VERIFIED.value)


def test_complete_requires_drug_screen_verified_at_lab_reported(api):
    """PRD §3.4: "for a `DRUG_SCREEN` the `DrugScreen.status` must be either `VERIFIED` or
    `CANCELLED` (otherwise `ERR_DRUG_SCREEN_NOT_VERIFIED`)".

    Design: Difficulty/cross_entity_state_dependency/complete_requires_drug_screen_verified
    """
    # Second translation: screen at LAB_REPORTED (still not VERIFIED), FIT clearance present.
    emp, wkr, enc, ds = setup_drug_screen_at_lab_reported(lab_result="NEGATIVE", mro_user_id="mro-1")
    issue_clearance(enc["id"], "FIT")
    resp = api.complete_encounter(enc["id"], CLIN)
    validate_error(resp, ApiErrorId.ERR_DRUG_SCREEN_NOT_VERIFIED.value)


# ─── RBAC on drug-screen ops (PRD §2.1, §4) ───────────

def test_clinician_cannot_mro_receive_forbidden(api):
    """PRD §2.1: "When the headers are present and well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/clinician_cannot_mro_receive_forbidden
    """
    emp, wkr, enc, ds = setup_drug_screen_at_lab_reported(lab_result="NEGATIVE", mro_user_id="mro-1")
    resp = api.mro_receive(ds["id"], CLIN)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_collector_shared_op_create_drug_screen_succeeds(api):
    """PRD §2.1: "The `Collector` records chain-of-custody collection steps and may create drug
    screens."

    Design: Corner/rbac/collector_shared_op_create_drug_screen_succeeds
    """
    emp, wkr, enc = setup_checked_in_encounter(
        encounter_type="DRUG_SCREEN", panel_code="DRUG_NON_DOT", job_category="PACKER",
        panels=[panel("DRUG_NON_DOT", "PACKER", 8000, 0)])
    out = validate_success(api.create_drug_screen(
        create_drug_screen_payload(enc["id"], specimen_seal_intact=True), COLLECTOR), 201)
    assert out["status"] == "AWAITING_COLLECTION"
