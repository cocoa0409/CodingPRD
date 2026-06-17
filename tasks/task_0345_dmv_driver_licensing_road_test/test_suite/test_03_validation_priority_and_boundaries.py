"""Validation precedence and numeric/interval boundary precision.

Queue A (Difficulty): priority_pair_validation_conflict, boundary_precision_check.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    make_clerk_headers,
    make_examiner_headers,
    make_proctor_headers,
    create_license_payload,
    create_driver_record,
    create_examiner,
    pass_knowledge_test,
    scored_appointment,
    book_appointment,
    setup_served_suspension,
    eligible_record_with_passed_appointment,
    get_record_version,
)

CLERK = make_clerk_headers("clerk-1")
PROCTOR = make_proctor_headers("kp-1")


# ===========================================================================
# priority_pair_validation_conflict / occ_state_412_beats_fiscal_402_on_reinstate
# ===========================================================================
def test_reinstate_stale_version_412_beats_missing_fee_402(api):
    """PRD §2.9: "the optimistic-concurrency version check for the two guarded
    writes; (6) the target resource being in the correct state for the requested
    transition; and only then (7 and beyond) the business-safety, constraint,
    temporal, and fiscal checks specific to the operation."
    PRD §2.7: "if the record's version has advanced since the client last read it
    ... the filing is operating on a stale view and is rejected with
    ERR_STALE_RECORD_VERSION (HTTP 412). This version check is evaluated before
    any business logic on the reinstatement runs."

    The reinstate carries a stale version AND no fee; the OCC 412 fires first.

    Design: Difficulty/priority_pair_validation_conflict/occ_state_412_beats_fiscal_402_on_reinstate
    """
    ctx = setup_served_suspension(full_name="Ivy Stale", opaque_user_id="exu-7")
    record, suspension = ctx["record"], ctx["suspension"]
    stale_version = get_record_version(record["id"])
    # Bump the version with an opt-in (no reinstatement fee is ever captured).
    validate_success(api.opt_in(record["id"], {"organ_donor": True}, CLERK), 200)
    resp = api.reinstate_suspension(
        suspension["id"], {"expected_driver_record_version": stale_version}, CLERK,
    )
    validate_error(resp, "ERR_STALE_RECORD_VERSION", expected_status=412)
    susp = validate_success(api.get_suspension(suspension["id"], CLERK), 200)
    assert susp["status"] == "SERVED", f"got {susp['status']}"


def test_reinstate_stale_version_leaves_suspension_unchanged(api):
    """PRD §2.7: "Reinstatement flips the licensing track from SUSPENDED back to
    ACTIVE; if the record's version has advanced since the client last read it ...
    the filing is operating on a stale view and is rejected with
    ERR_STALE_RECORD_VERSION (HTTP 412)."

    A rejected stale reinstate is a no-op: the suspension stays SERVED.

    Design: Difficulty/priority_pair_validation_conflict/occ_state_412_beats_fiscal_402_on_reinstate
    """
    ctx = setup_served_suspension(full_name="Ivy Stale 2", opaque_user_id="exu-7b")
    record, suspension = ctx["record"], ctx["suspension"]
    stale_version = get_record_version(record["id"])
    validate_success(api.opt_in(record["id"], {"organ_donor": True}, CLERK), 200)
    resp = api.reinstate_suspension(
        suspension["id"], {"expected_driver_record_version": stale_version}, CLERK,
    )
    validate_error(resp, "ERR_STALE_RECORD_VERSION", expected_status=412)
    rec = validate_success(api.get_driver_record(record["id"], CLERK), 200)
    assert rec["licensing_status"] == "SUSPENDED"


# ===========================================================================
# priority_pair_validation_conflict / segregation_403_beats_fiscal_402_on_license_issue
# ===========================================================================
def test_license_issue_segregation_403_beats_missing_fee_402(api):
    """PRD §2.9: "Earlier checks always mask later ones."
    PRD §3.6: "the acting operator's X-User-ID must differ from that appointment's
    scored_by_examiner_id, enforcing that the examiner who scored a test cannot be
    the one who issues its license (otherwise ERR_SEGREGATION_OF_DUTIES); ... and
    there must exist a captured fee payment of purpose RENEWAL for this record
    whose amount is at least the computed fee_cents (otherwise
    ERR_RENEWAL_FEE_UNPAID)."

    Issuing as the scoring examiner with no fee captured: SoD 403 (priority 6)
    masks the fiscal 402 (priority 15).

    Design: Difficulty/priority_pair_validation_conflict/segregation_403_beats_fiscal_402_on_license_issue
    """
    ctx = eligible_record_with_passed_appointment(
        license_class="D", opaque_user_id="exu-8", full_name="Jon Sod",
    )
    record, examiner, appt = ctx["record"], ctx["examiner"], ctx["appointment"]
    assert appt["outcome"] == "PASS"
    # Issuance is a LicenseClerk action (PRD §3.6 / endpoint table). The clerk's
    # X-User-ID is opaque; here it collides with the scoring examiner's id so the
    # SoD comparison (X-User-ID == scored_by_examiner_id) trips. No RENEWAL fee was
    # captured, so the only way SoD 403 surfaces is by masking the fiscal 402.
    resp = api.create_license(
        create_license_payload(record["id"], appt["id"], license_class="D"),
        make_clerk_headers(examiner["id"]),
    )
    validate_error(resp, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
    rec = validate_success(api.get_driver_record(record["id"], CLERK), 200)
    assert rec["licensing_status"] == "ELIGIBLE", f"got {rec['licensing_status']}"


def test_license_issue_by_scoring_examiner_does_not_activate(api):
    """PRD §3.6: "the acting operator's X-User-ID must differ from that
    appointment's scored_by_examiner_id, enforcing that the examiner who scored a
    test cannot be the one who issues its license (otherwise
    ERR_SEGREGATION_OF_DUTIES)."

    The rejected issuance leaves the record ELIGIBLE — no license minted.

    Design: Difficulty/priority_pair_validation_conflict/segregation_403_beats_fiscal_402_on_license_issue
    """
    ctx = eligible_record_with_passed_appointment(
        license_class="D", opaque_user_id="exu-8b", full_name="Jon Sod 2",
    )
    record, examiner, appt = ctx["record"], ctx["examiner"], ctx["appointment"]
    # Issuance is a LicenseClerk action; the clerk's opaque X-User-ID collides with
    # the scoring examiner's id, tripping the SoD check (X-User-ID ==
    # scored_by_examiner_id) per PRD §3.6.
    resp = api.create_license(
        create_license_payload(record["id"], appt["id"], license_class="D"),
        make_clerk_headers(examiner["id"]),
    )
    validate_error(resp, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
    licenses = _list(api.list_record_licenses(record["id"], CLERK))
    assert len(licenses) == 0, f"no license should exist, got {len(licenses)}"


# ===========================================================================
# boundary_precision_check / knowledge_pass_threshold_exact_80_passes
# ===========================================================================
def test_knowledge_score_exactly_80_passes(api):
    """PRD §3.3: "If score_pct is at least the passing threshold of 80, the test
    transitions SCHEDULED → PASSED, which is terminal."
    PRD §3.3: "On the first pass within the knowledge-validity window, the
    record's knowledge_test_passed becomes true, and an UNLICENSED record advances
    licensing_status from UNLICENSED to ELIGIBLE."

    32/40 = 80.00% (inclusive boundary) -> PASSED, knowledge_test_passed true.

    Design: Difficulty/boundary_precision_check/knowledge_pass_threshold_exact_80_passes
    """
    record = create_driver_record(full_name="Kim Edge", date_of_birth="1990-01-01")
    kt = get_success_data(
        api.create_knowledge_test({"driver_record_id": record["id"], "scheduled_period": 0}, PROCTOR)
    )
    graded = validate_success(api.grade_knowledge_test(kt["id"], {"correct_answers": 32}, PROCTOR), 200)
    assert graded["score_pct"] == 80.0, f"got {graded['score_pct']}"
    assert graded["status"] == "PASSED"
    rec = validate_success(api.get_driver_record(record["id"], CLERK), 200)
    assert rec["knowledge_test_passed"] is True


def test_knowledge_score_just_below_80_fails(api):
    """PRD §3.3: "if score_pct falls below 80, it transitions SCHEDULED → FAILED."

    31/40 = 77.50% (one short of the inclusive boundary) -> FAILED.

    Design: Difficulty/boundary_precision_check/knowledge_pass_threshold_exact_80_passes
    """
    record = create_driver_record(full_name="Kim Edge 2", date_of_birth="1990-01-01")
    kt = get_success_data(
        api.create_knowledge_test({"driver_record_id": record["id"], "scheduled_period": 0}, PROCTOR)
    )
    graded = validate_success(api.grade_knowledge_test(kt["id"], {"correct_answers": 31}, PROCTOR), 200)
    assert graded["score_pct"] == 77.5, f"got {graded['score_pct']}"
    assert graded["status"] == "FAILED"


# ===========================================================================
# boundary_precision_check / examiner_slot_touching_endpoints_do_not_conflict
# ===========================================================================
def test_examiner_slots_touching_at_endpoint_do_not_conflict(api):
    """PRD §3.4: "the slot must not overlap any existing non-cancelled appointment
    on the same examiner; because intervals are half-open, two slots that merely
    touch at an endpoint (one slot's end equal to the next slot's start) do not
    overlap, but any genuine overlap is rejected with ERR_EXAMINER_SLOT_CONFLICT."

    First slot [10,20), second [20,30): a.end == b.start -> no conflict, booking
    succeeds (201, BOOKED).

    Design: Difficulty/boundary_precision_check/examiner_slot_touching_endpoints_do_not_conflict
    """
    dr1 = create_driver_record(full_name="Lee Slot1", date_of_birth="1990-01-01")
    dr2 = create_driver_record(full_name="Mae Slot2", date_of_birth="1990-01-01")
    examiner = create_examiner(certified_classes=["D"], opaque_user_id="exu-9")
    book_appointment(dr1["id"], examiner, license_class="D",
                     slot_start_period=10, slot_end_period=20)
    resp = api.create_road_test_appointment(
        {"driver_record_id": dr2["id"], "examiner_id": examiner["id"],
         "license_class": "D", "slot_start_period": 20, "slot_end_period": 30},
        CLERK,
    )
    appt2 = validate_success(resp, 201)
    assert appt2["status"] == "BOOKED"
    assert appt2["slot_start_period"] == 20


def test_examiner_slot_starting_at_prior_end_succeeds_for_same_class(api):
    """PRD §3.4: "two slots that merely touch at an endpoint (one slot's end equal
    to the next slot's start) do not overlap."

    A back-to-back [0,5) then [5,10) booking pair on one examiner both succeed,
    confirming the touching endpoint is not treated as overlap.

    Design: Difficulty/boundary_precision_check/examiner_slot_touching_endpoints_do_not_conflict
    """
    dr1 = create_driver_record(full_name="Lee Slot3", date_of_birth="1990-01-01")
    dr2 = create_driver_record(full_name="Mae Slot4", date_of_birth="1990-01-01")
    examiner = create_examiner(certified_classes=["D"], opaque_user_id="exu-9b")
    a1 = book_appointment(dr1["id"], examiner, license_class="D",
                          slot_start_period=0, slot_end_period=5)
    assert a1["status"] == "BOOKED"
    resp = api.create_road_test_appointment(
        {"driver_record_id": dr2["id"], "examiner_id": examiner["id"],
         "license_class": "D", "slot_start_period": 5, "slot_end_period": 10},
        CLERK,
    )
    a2 = validate_success(resp, 201)
    assert a2["slot_start_period"] == 5


# --- helpers -------------------------------------------------------------
def _list(resp):
    data = get_success_data(resp)
    return data if isinstance(data, list) else data.get("data", data)
