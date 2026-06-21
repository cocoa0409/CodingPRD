"""License issuance, waiting period & expiry, officiant returns and the
accept cascade. Difficulty (queue A) + corner (queue B) instances."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    create_return_payload,
    create_applicant,
    create_under_review_application,
    create_officiant,
    make_officiant_headers,
    set_clock,
    setup_issued_license,
    setup_submitted_return,
    setup_registered_record,
    find_ledger_entries,
    CLERK_1,
    REGISTRAR_1,
)


# ===========================================================================
# License computed fields (queue B: entities)
# ===========================================================================
def test_license_computed_fields_present_on_issue(api):
    """PRD §3.3: "The valid_from instant is the moment 72 hours after issued_at ...
    The expires_at instant is the moment 90 calendar days after issued_at".

    Design: Corner/entities/license_computed_fields_present_on_issue
    """
    base = setup_issued_license(issue_clock="2026-01-10T09:00:00Z")
    lic = base["license"]
    # issued_at 2026-01-10T09:00:00Z -> valid_from +72h, expires_at +90d.
    assert lic["valid_from"].startswith("2026-01-13T09:00:00")
    assert lic["expires_at"].startswith("2026-04-10T09:00:00")


# ===========================================================================
# Return accept cascade depth-3 (queue A: transitive_cascade)
# ===========================================================================
def test_return_accept_marks_return_accepted_and_license_used(api):
    """PRD §3.4: "On a successful acceptance the return's status becomes ACCEPTED ...
    The underlying license moves from ISSUED to USED."

    Design: Difficulty/transitive_cascade/return_accept_cascade_return_license_record_depth3
    """
    base = setup_submitted_return()
    data = validate_success(api.accept_return(base["return"]["id"], REGISTRAR_1))
    assert data["status"] == "ACCEPTED"
    lic = get_success_data(api.get_license(base["license"]["id"], CLERK_1))
    assert lic["status"] == "USED"


def test_return_accept_registers_record_in_registered_state(api):
    """PRD §3.4: "That license transition in turn creates a new MarriageRecord in the
    REGISTERED state, copying the license's confidentiality into the record's own
    is_confidential and stamping registered_at with the acceptance instant".

    Design: Difficulty/transitive_cascade/return_accept_cascade_return_license_record_depth3
    """
    base = setup_submitted_return()
    validate_success(api.accept_return(base["return"]["id"], REGISTRAR_1))
    records, _ = validate_paginated(
        api.list_records(CLERK_1, params={"return_id": base["return"]["id"]}))
    assert len(records) == 1
    assert records[0]["status"] == "REGISTERED"


# ===========================================================================
# License expiry cascade depth-2 (queue A: transitive_cascade)
# ===========================================================================
def test_license_expire_check_moves_license_to_expired(api):
    """PRD §3.3: "If the clock has moved strictly past expires_at and no accepted
    return references the license, the license moves from ISSUED to EXPIRED".

    Design: Difficulty/transitive_cascade/license_expiry_cascade_license_application_depth2
    """
    base = setup_issued_license(issue_clock="2026-01-10T09:00:00Z")
    set_clock("2026-04-10T09:00:01Z")  # one second past expires_at
    data = validate_success(api.expire_check_license(base["license"]["id"], CLERK_1))
    assert data["status"] == "EXPIRED"


def test_license_expiry_bubbles_application_to_expired(api):
    """PRD §3.3: "the license moves from ISSUED to EXPIRED, and the owning application
    bubbles up from APPROVED to EXPIRED."

    Design: Difficulty/transitive_cascade/license_expiry_cascade_license_application_depth2
    """
    base = setup_issued_license(issue_clock="2026-01-10T09:00:00Z")
    set_clock("2026-04-10T09:00:01Z")
    validate_success(api.expire_check_license(base["license"]["id"], CLERK_1))
    app = get_success_data(api.get_application(base["application"]["id"], CLERK_1))
    assert app["status"] == "EXPIRED"


# ===========================================================================
# Waiting-period boundary precision (queue A: boundary_precision_check)
# ===========================================================================
def test_ceremony_exactly_at_valid_from_is_accepted(api):
    """PRD §3.3: "a ceremony whose instant falls strictly before valid_from is
    invalid, while a ceremony exactly at valid_from is valid."

    Design: Difficulty/boundary_precision_check/ceremony_exactly_at_valid_from_is_valid
    """
    base = setup_issued_license(issue_clock="2026-01-10T09:00:00Z")
    officiant = create_officiant()
    set_clock("2026-01-13T10:00:00Z")
    ret = get_success_data(api.create_return(
        create_return_payload(base["license"]["id"], officiant["id"],
                              "2026-01-13T09:00:00Z"),  # == valid_from
        make_officiant_headers(officiant["id"]),
    ))
    data = validate_success(api.accept_return(ret["id"], REGISTRAR_1))
    assert data["status"] == "ACCEPTED"
    lic = get_success_data(api.get_license(base["license"]["id"], CLERK_1))
    assert lic["status"] == "USED"


def test_ceremony_exactly_at_valid_from_registers_record(api):
    """PRD §2.5: "it drives the underlying license from ISSUED to USED and,
    transitively, brings a new marriage record into existence in the REGISTERED state."

    Design: Difficulty/boundary_precision_check/ceremony_exactly_at_valid_from_is_valid
    """
    base = setup_issued_license(issue_clock="2026-01-10T09:00:00Z")
    officiant = create_officiant()
    set_clock("2026-01-13T10:00:00Z")
    ret = get_success_data(api.create_return(
        create_return_payload(base["license"]["id"], officiant["id"],
                              "2026-01-13T09:00:00Z"),  # == valid_from boundary
        make_officiant_headers(officiant["id"]),
    ))
    validate_success(api.accept_return(ret["id"], REGISTRAR_1))
    records, _ = validate_paginated(api.list_records(CLERK_1, params={"return_id": ret["id"]}))
    assert len(records) == 1
    assert records[0]["status"] == "REGISTERED"


def test_ceremony_one_second_before_valid_from_rejected(api):
    """PRD §3.4: "The ceremony_date must be at or after the license's valid_from, or
    the acceptance is rejected with ERR_CEREMONY_BEFORE_VALID."

    Design: Difficulty/boundary_precision_check/ceremony_one_second_before_valid_from_rejected
    """
    base = setup_issued_license(issue_clock="2026-01-10T09:00:00Z")
    officiant = create_officiant()
    set_clock("2026-01-14T00:00:00Z")
    ret = get_success_data(api.create_return(
        create_return_payload(base["license"]["id"], officiant["id"],
                              "2026-01-13T08:59:59Z"),  # one second before valid_from
        make_officiant_headers(officiant["id"]),
    ))
    resp = api.accept_return(ret["id"], REGISTRAR_1)
    validate_error(resp, ApiErrorId.ERR_CEREMONY_BEFORE_VALID.value, expected_status=409)
    assert get_success_data(api.get_return(ret["id"], CLERK_1))["status"] == "SUBMITTED"
    assert get_success_data(api.get_license(base["license"]["id"], CLERK_1))["status"] == "ISSUED"


def test_ceremony_before_valid_from_creates_no_record(api):
    """PRD §3.4: "Rejection leaves the license in ISSUED, so a corrected return may be
    filed later while the license is still valid."

    Design: Difficulty/boundary_precision_check/ceremony_one_second_before_valid_from_rejected
    """
    base = setup_issued_license(issue_clock="2026-01-10T09:00:00Z")
    officiant = create_officiant()
    set_clock("2026-01-14T00:00:00Z")
    ret = get_success_data(api.create_return(
        create_return_payload(base["license"]["id"], officiant["id"],
                              "2026-01-13T08:59:59Z"),
        make_officiant_headers(officiant["id"]),
    ))
    api.accept_return(ret["id"], REGISTRAR_1)
    records, _ = validate_paginated(api.list_records(CLERK_1, params={"return_id": ret["id"]}))
    assert len(records) == 0, "a rejected before-valid acceptance must register no record"


# ===========================================================================
# Cross-entity state dependency: accept requires ISSUED license (queue A)
# ===========================================================================
def test_return_accept_rejected_when_license_void(api):
    """PRD §3.4: "The referenced license must be in ISSUED, or the acceptance is
    rejected with ERR_LICENSE_NOT_USABLE."

    Design: Difficulty/cross_entity_state_dependency/return_accept_requires_license_issued
    """
    base = setup_submitted_return()
    # Void the license while the return is still SUBMITTED (no accepted return yet).
    get_success_data(api.void_license(base["license"]["id"], REGISTRAR_1))
    resp = api.accept_return(base["return"]["id"], REGISTRAR_1)
    validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_USABLE.value, expected_status=409)
    assert get_success_data(api.get_return(base["return"]["id"], CLERK_1))["status"] == "SUBMITTED"
    assert get_success_data(api.get_license(base["license"]["id"], CLERK_1))["status"] == "VOID"


def test_return_accept_succeeds_when_license_issued(api):
    """PRD §3.4: "The referenced license must be in ISSUED, or the acceptance is
    rejected with ERR_LICENSE_NOT_USABLE."

    Design: Difficulty/cross_entity_state_dependency/return_accept_requires_license_issued
    """
    base = setup_submitted_return()
    data = validate_success(api.accept_return(base["return"]["id"], REGISTRAR_1))
    assert data["status"] == "ACCEPTED"
    assert get_success_data(api.get_license(base["license"]["id"], CLERK_1))["status"] == "USED"


# ===========================================================================
# Officiant double-booking (queue A: resource_temporal_overlap)
# ===========================================================================
def test_officiant_double_booked_within_buffer_rejected(api):
    """PRD §3.8: "A conflict exists if the absolute difference between this return's
    ceremony_date and any candidate's ceremony_date is strictly less than 60 minutes
    ... Any single conflict rejects the acceptance with ERR_OFFICIANT_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/officiant_double_booked_within_buffer
    """
    set_clock("2026-01-10T09:00:00Z")
    gA = create_applicant(full_name="Dot Wye", date_of_birth="1990-01-01")
    gB = create_applicant(full_name="Eli Yaw", date_of_birth="1991-02-02")
    gC = create_applicant(full_name="Fox Zed", date_of_birth="1989-03-03")
    gD = create_applicant(full_name="Gem Abe", date_of_birth="1988-04-04")
    officiant = create_officiant(full_name="Rev. Wun")
    # Two separate couples, two ISSUED licenses, one officiant.
    app1 = create_under_review_application(gA["id"], gB["id"])
    get_success_data(api.decide_application(app1["id"], {"decision": "APPROVE"}, CLERK_1))
    lic1 = get_success_data(api.list_application_licenses(app1["id"], CLERK_1))[0]
    app2 = create_under_review_application(gC["id"], gD["id"])
    get_success_data(api.decide_application(app2["id"], {"decision": "APPROVE"}, CLERK_1))
    lic2 = get_success_data(api.list_application_licenses(app2["id"], CLERK_1))[0]
    set_clock("2026-01-20T13:00:00Z")
    ret1 = get_success_data(api.create_return(
        create_return_payload(lic1["id"], officiant["id"], "2026-01-20T12:00:00Z"),
        make_officiant_headers(officiant["id"])))
    get_success_data(api.accept_return(ret1["id"], REGISTRAR_1))
    ret2 = get_success_data(api.create_return(
        create_return_payload(lic2["id"], officiant["id"], "2026-01-20T12:30:00Z"),  # 30 min apart
        make_officiant_headers(officiant["id"])))
    resp = api.accept_return(ret2["id"], REGISTRAR_1)
    validate_error(resp, ApiErrorId.ERR_OFFICIANT_DOUBLE_BOOKED.value, expected_status=409)
    assert get_success_data(api.get_return(ret2["id"], CLERK_1))["status"] == "SUBMITTED"
    assert get_success_data(api.get_return(ret1["id"], CLERK_1))["status"] == "ACCEPTED"


def test_officiant_exactly_60_minutes_apart_is_permitted(api):
    """PRD §3.8: "A conflict exists if the absolute difference between this return's
    ceremony_date and any candidate's ceremony_date is strictly less than 60 minutes;
    exactly 60 minutes apart is permitted, so back-to-back ceremonies at the buffer
    edge are fine."

    Design: Difficulty/resource_temporal_overlap/officiant_double_booked_within_buffer
    """
    set_clock("2026-01-10T09:00:00Z")
    gA = create_applicant(full_name="Dot Wye", date_of_birth="1990-01-01")
    gB = create_applicant(full_name="Eli Yaw", date_of_birth="1991-02-02")
    gC = create_applicant(full_name="Fox Zed", date_of_birth="1989-03-03")
    gD = create_applicant(full_name="Gem Abe", date_of_birth="1988-04-04")
    officiant = create_officiant(full_name="Rev. Wun")
    app1 = create_under_review_application(gA["id"], gB["id"])
    get_success_data(api.decide_application(app1["id"], {"decision": "APPROVE"}, CLERK_1))
    lic1 = get_success_data(api.list_application_licenses(app1["id"], CLERK_1))[0]
    app2 = create_under_review_application(gC["id"], gD["id"])
    get_success_data(api.decide_application(app2["id"], {"decision": "APPROVE"}, CLERK_1))
    lic2 = get_success_data(api.list_application_licenses(app2["id"], CLERK_1))[0]
    set_clock("2026-01-20T14:00:00Z")
    ret1 = get_success_data(api.create_return(
        create_return_payload(lic1["id"], officiant["id"], "2026-01-20T12:00:00Z"),
        make_officiant_headers(officiant["id"])))
    get_success_data(api.accept_return(ret1["id"], REGISTRAR_1))
    ret2 = get_success_data(api.create_return(
        create_return_payload(lic2["id"], officiant["id"], "2026-01-20T13:00:00Z"),  # exactly 60 min
        make_officiant_headers(officiant["id"])))
    data = validate_success(api.accept_return(ret2["id"], REGISTRAR_1))
    assert data["status"] == "ACCEPTED"


# ===========================================================================
# Applicant concurrent-license overlap (queue A: resource_temporal_overlap)
# ===========================================================================
def test_applicant_concurrent_license_window_overlap_rejected(api):
    """PRD §3.8: "If approving the application would create an overlapping window for
    either party, the approval is rejected with ERR_APPLICANT_LICENSE_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/applicant_concurrent_license_window_overlap
    """
    set_clock("2026-01-10T09:00:00Z")
    iA = create_applicant(full_name="Hank Bro", date_of_birth="1990-01-01")
    iB = create_applicant(full_name="Ida Cor", date_of_birth="1991-02-02")
    iC = create_applicant(full_name="Jeb Dow", date_of_birth="1989-03-03",
                          prior_marriage_status="DIVORCED", prior_dissolution_date="2020-01-01")
    app1 = create_under_review_application(iA["id"], iB["id"])
    get_success_data(api.decide_application(app1["id"], {"decision": "APPROVE"}, CLERK_1))
    # Second application reuses iA at the same clock -> overlapping window.
    app2 = create_under_review_application(iA["id"], iC["id"])
    resp = api.decide_application(app2["id"], {"decision": "APPROVE"}, CLERK_1)
    validate_error(resp, ApiErrorId.ERR_APPLICANT_LICENSE_OVERLAP.value, expected_status=409)
    assert get_success_data(api.get_application(app2["id"], CLERK_1))["status"] == "UNDER_REVIEW"
    assert len(get_success_data(api.list_application_licenses(app2["id"], CLERK_1))) == 0


def test_shared_applicant_approves_after_first_license_voided(api):
    """PRD §3.8: "The existing windows are taken from every MarriageLicense in status
    ISSUED whose application lists the same applicant on either side."

    Design: Difficulty/resource_temporal_overlap/applicant_concurrent_license_window_overlap
    """
    set_clock("2026-01-10T09:00:00Z")
    iA = create_applicant(full_name="Hank Bro", date_of_birth="1990-01-01")
    iB = create_applicant(full_name="Ida Cor", date_of_birth="1991-02-02")
    iC = create_applicant(full_name="Jeb Dow", date_of_birth="1989-03-03",
                          prior_marriage_status="DIVORCED", prior_dissolution_date="2020-01-01")
    app1 = create_under_review_application(iA["id"], iB["id"])
    get_success_data(api.decide_application(app1["id"], {"decision": "APPROVE"}, CLERK_1))
    lic1 = get_success_data(api.list_application_licenses(app1["id"], CLERK_1))[0]
    # Void the first license so it is no longer in ISSUED -> its window is no longer live.
    get_success_data(api.void_license(lic1["id"], REGISTRAR_1))
    app2 = create_under_review_application(iA["id"], iC["id"])
    data = validate_success(api.decide_application(app2["id"], {"decision": "APPROVE"}, CLERK_1))
    assert data["status"] == "APPROVED"
    assert len(get_success_data(api.list_application_licenses(app2["id"], CLERK_1))) == 1


# ===========================================================================
# Officiant returns_filed_count computed (queue B: entities)
# ===========================================================================
def test_officiant_returns_filed_count_is_computed(api):
    """PRD §3.1: "The officiant's returns_filed_count is a derived figure: it is the
    number of that officiant's returns currently in the ACCEPTED state, and it is
    recomputed and surfaced whenever the officiant is read."

    Design: Corner/entities/officiant_returns_filed_count_is_computed
    """
    base = setup_registered_record()
    officiant = get_success_data(api.get_officiant(base["officiant"]["id"], CLERK_1))
    assert officiant["returns_filed_count"] == 1


# ===========================================================================
# Reject an already-accepted return -> invalid state (queue B: state_machines)
# ===========================================================================
def test_reject_already_accepted_return_invalid_state(api):
    """PRD §3.4: "A registrar may instead reject a SUBMITTED return, advancing it
    from SUBMITTED to REJECTED".

    Design: Corner/state_machines/reject_an_already_accepted_return_invalid_state
    """
    base = setup_registered_record()  # return is ACCEPTED
    resp = api.reject_return(base["return"]["id"], {}, REGISTRAR_1)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    assert get_success_data(api.get_return(base["return"]["id"], CLERK_1))["status"] == "ACCEPTED"


# ===========================================================================
# Late return surcharge (queue B: calculations)
# ===========================================================================
def test_late_return_surcharge_charged_on_late_accept(api):
    """PRD §3.4: "if the return was late — that is, if it was filed after its
    filing_deadline — a CHARGE ledger row for the late-return surcharge of 2000 cents
    is appended with source_entity RETURN".

    Design: Corner/calculations/late_return_surcharge_charged_on_late_accept
    """
    base = setup_issued_license(issue_clock="2026-01-10T09:00:00Z")
    officiant = create_officiant(full_name="Rev. Lr")
    # ceremony 2026-01-20 -> filing_deadline 2026-01-30; file at 2026-02-04 (late).
    set_clock("2026-02-04T12:00:00Z")
    ret = get_success_data(api.create_return(
        create_return_payload(base["license"]["id"], officiant["id"], "2026-01-20T12:00:00Z"),
        make_officiant_headers(officiant["id"])))
    data = validate_success(api.accept_return(ret["id"], REGISTRAR_1))
    assert data["status"] == "ACCEPTED"
    ledger, _ = validate_paginated(api.list_application_ledger(base["application"]["id"], CLERK_1))
    late_rows = find_ledger_entries(ledger, kind="CHARGE", source_entity="RETURN", amount_cents=2000)
    assert len(late_rows) == 1, "expected one 2000-cent late-return surcharge CHARGE"
    license_rows = find_ledger_entries(ledger, kind="CHARGE", source_entity="LICENSE", amount_cents=9000)
    assert len(license_rows) == 1, "expected the 9000-cent license CHARGE"


# ===========================================================================
# Officiant not authorized after registration expiry (queue B: validations)
# ===========================================================================
def test_officiant_not_authorized_after_registration_expiry(api):
    """PRD §3.4: "The referenced officiant must be REGISTERED, and the ceremony_date
    must be on or before that officiant's registration_expires_on, or the acceptance
    is rejected with ERR_OFFICIANT_NOT_AUTHORIZED."

    Design: Corner/validations/officiant_not_authorized_after_registration_expiry
    """
    base = setup_issued_license(issue_clock="2026-01-10T09:00:00Z")
    officiant = create_officiant(full_name="Rev. Oa", registration_expires_on="2026-01-15")
    set_clock("2026-01-20T12:00:00Z")
    ret = get_success_data(api.create_return(
        create_return_payload(base["license"]["id"], officiant["id"], "2026-01-20T12:00:00Z"),
        make_officiant_headers(officiant["id"])))
    resp = api.accept_return(ret["id"], REGISTRAR_1)
    validate_error(resp, ApiErrorId.ERR_OFFICIANT_NOT_AUTHORIZED.value, expected_status=409)
    assert get_success_data(api.get_return(ret["id"], CLERK_1))["status"] == "SUBMITTED"


# ===========================================================================
# License void already used (queue B: errors)
# ===========================================================================
def test_license_void_already_used_rejected(api):
    """PRD §3.3: "If any accepted return references the license, the void is rejected
    with ERR_LICENSE_ALREADY_USED."

    Design: Corner/errors/license_void_already_used_rejected
    """
    base = setup_registered_record()  # license is USED via accepted return
    resp = api.void_license(base["license"]["id"], REGISTRAR_1)
    validate_error(resp, ApiErrorId.ERR_LICENSE_ALREADY_USED.value, expected_status=409)
    assert get_success_data(api.get_license(base["license"]["id"], CLERK_1))["status"] == "USED"


# ===========================================================================
# Expire-check not expired (queue B: errors)
# ===========================================================================
def test_expire_check_not_expired_rejected(api):
    """PRD §3.3: "If the clock has not yet passed expires_at, the request is rejected
    with ERR_LICENSE_NOT_EXPIRED."

    Design: Corner/errors/expire_check_not_expired_rejected
    """
    base = setup_issued_license(issue_clock="2026-01-10T09:00:00Z")
    set_clock("2026-04-10T09:00:00Z")  # exactly expires_at, not strictly past
    resp = api.expire_check_license(base["license"]["id"], CLERK_1)
    validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_EXPIRED.value, expected_status=409)
    assert get_success_data(api.get_license(base["license"]["id"], CLERK_1))["status"] == "ISSUED"


# ===========================================================================
# Filter returns by license (queue B: endpoints)
# ===========================================================================
def test_filter_returns_by_license_id(api):
    """PRD §3.4: "Returns are listable filtered by license".

    Design: Corner/endpoints/filter_returns_by_license_id
    """
    base = setup_submitted_return()
    returns, _ = validate_paginated(
        api.list_returns(CLERK_1, params={"license_id": base["license"]["id"]}))
    assert len(returns) == 1
    assert returns[0]["id"] == base["return"]["id"]


# ===========================================================================
# Immediate visibility of record after accept (queue B: consistency_model)
# ===========================================================================
def test_immediate_visibility_record_after_accept(api):
    """PRD §2.5: "Accepting an officiant return does not merely move the return
    forward — it drives the underlying license from ISSUED to USED and, transitively,
    brings a new marriage record into existence in the REGISTERED state."

    Design: Corner/consistency_model/immediate_visibility_record_after_accept
    """
    base = setup_submitted_return()
    validate_success(api.accept_return(base["return"]["id"], REGISTRAR_1))
    records, _ = validate_paginated(
        api.list_records(CLERK_1, params={"return_id": base["return"]["id"]}))
    assert len(records) == 1
    assert records[0]["status"] == "REGISTERED"
