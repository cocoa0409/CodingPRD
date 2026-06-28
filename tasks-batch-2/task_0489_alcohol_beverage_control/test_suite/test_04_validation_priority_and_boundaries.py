"""Validation-priority conflicts, numeric/temporal boundaries, cross-entity state
dependencies, and interval-overlap rules (hearing room vs premise term).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_applicant_headers,
    make_director_headers,
    make_examiner_headers,
    ApiErrorId,
    setup_reference_data,
    create_submitted_application,
    setup_issued_license,
    setup_license_with_active_permit,
    advance_to_protest_period,
    approve_and_issue,
    file_violation,
    sustain_violation,
    create_server_permit,
)

DIRECTOR = TEST_USERS["director_headers"]
EXAMINER = TEST_USERS["examiner_headers"]
ZONING = TEST_USERS["zoning_officer_headers"]
ADJUDICATOR = TEST_USERS["adjudication_officer_headers"]


# ─── Queue A: priority_pair_validation_conflict ───────────────────────────
def test_renew_suspended_with_outstanding_fine_returns_invalid_state(api):
    """PRD §2.8: "Whether the target is in a state from which the requested
    transition is defined is checked fourth, failing with `ERR_INVALID_STATE`
    (409)."
    PRD §2.8: "Only after these gates do the domain-specific business rules of
    Section 3 apply — disqualification, zoning, background, protest timing and
    resolution, capacity, training, renewal timing, fines, demerits, quota,
    transfer-type integrity, and premise overlap"

    A SUSPENDED license (wrong state for renew) that also has outstanding fines
    surfaces ERR_INVALID_STATE: the state gate (4) precedes the fiscal business
    rule (outstanding fine).

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_renew_terminal_beats_outstanding_fine
    """
    bundle = setup_license_with_active_permit()
    lic_id = bundle["license"]["id"]
    owner = make_applicant_headers(bundle["ref"]["owner_id"])
    # Drive to SUSPENDED via demerit 10 (EGREGIOUS 6 + SERIOUS 4), leaving fines unpaid.
    v1 = file_violation(lic_id, severity="EGREGIOUS")
    sustain_violation(v1["id"], action_type="FINE")
    v2 = file_violation(lic_id, severity="SERIOUS")
    sustain_violation(v2["id"], action_type="FINE")
    lic = get_success_data(api.get_license(lic_id, DIRECTOR))
    assert lic["status"] == "SUSPENDED" and lic["outstanding_fine_cents"] > 0
    resp = api.renew_license(lic_id, {"renewal_fee_paid_cents": 100000}, owner)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_approve_by_examiner_before_window_returns_segregation(api):
    """PRD §2.8: "Separation-of-duties is evaluated fifth, failing with
    `ERR_SEGREGATION_OF_DUTIES` (403). Only after these gates do the
    domain-specific business rules of Section 3 apply ... protest timing and
    resolution"
    PRD §3.5: "the approving `Director`'s `X-User-ID` must differ from the
    application's `examiner_user_id`, since the issuer may not be the recommender;
    a match is rejected with `ERR_SEGREGATION_OF_DUTIES` (403)."

    The examiner (user 'dual-1') attempts approve before the protest window
    elapsed: both segregation (gate 5) and window-open (a Section-3 business rule)
    fail; segregation wins.

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_approve_segregation_beats_window_open
    """
    ref, app = create_submitted_application()
    # Examiner footprint == 'dual-1'.
    advance_to_protest_period(ref, app, examiner_user_id="dual-1")
    # Clock still before protest_period_ends_at; Director acts as the same user 'dual-1'.
    resp = api.approve_application(app["id"], make_director_headers("dual-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ─── Queue A: boundary_precision_check ────────────────────────────────────
def test_quota_last_slot_submit_strictly_greater_than_zero(api):
    """PRD §3.6: "A new submit of a quota-managed application is permitted only
    when available is strictly greater than zero; when available equals zero the
    submit is blocked with `ERR_QUOTA_EXHAUSTED` (422)"

    Region CTY_SM cap 1; first submit consumes the only slot (available 1>0,
    succeeds), a second submit at available 0 is rejected ERR_QUOTA_EXHAUSTED.

    Design: Difficulty/boundary_precision_check/quota_last_slot_available_strictly_greater_than_zero_on_submit
    """
    get_success_data(api.set_clock("2026-01-01T00:00:00Z", DIRECTOR))
    get_success_data(api.create_license_class(
        {"code": "ON_47", "premise_type": "ON_PREMISE", "quota_managed": True,
         "base_fee_cents": 100000, "renewal_cycle_months": 12, "requires_zoning": True,
         "max_servers_per_license": 5}, DIRECTOR))
    region = get_success_data(api.create_quota_region(
        {"region_code": "CTY_SM", "population": 30000, "persons_per_license": 30000}, DIRECTOR))
    # First applicant takes the only slot.
    o1 = get_success_data(api.create_applicant({"legal_name": "First Bar"}, DIRECTOR))
    p1 = get_success_data(api.create_premise(
        {"applicant_id": o1["id"], "region_code": "CTY_SM", "street_address": "1 A St",
         "distance_to_school_m": 200, "zoning_district": "COMMERCIAL"}, make_applicant_headers(o1["id"])))
    a1 = get_success_data(api.create_application(
        {"applicant_id": o1["id"], "premise_id": p1["id"], "license_class_code": "ON_47"},
        make_applicant_headers(o1["id"])))
    get_success_data(api.submit_application(
        a1["id"], {"expected_region_version": region["version"]}, make_applicant_headers(o1["id"])))
    # Second applicant: region version advanced by the first submit.
    o2 = get_success_data(api.create_applicant({"legal_name": "Second Bar"}, DIRECTOR))
    p2 = get_success_data(api.create_premise(
        {"applicant_id": o2["id"], "region_code": "CTY_SM", "street_address": "2 B St",
         "distance_to_school_m": 200, "zoning_district": "COMMERCIAL"}, make_applicant_headers(o2["id"])))
    a2 = get_success_data(api.create_application(
        {"applicant_id": o2["id"], "premise_id": p2["id"], "license_class_code": "ON_47"},
        make_applicant_headers(o2["id"])))
    region_now = get_success_data(api.get_quota_region(region["id"], DIRECTOR))
    resp = api.submit_application(
        a2["id"], {"expected_region_version": region_now["version"]}, make_applicant_headers(o2["id"]))
    validate_error(resp, ApiErrorId.ERR_QUOTA_EXHAUSTED.value)
    after = get_success_data(api.get_application(a2["id"], DIRECTOR))
    assert after["status"] == "DRAFT"
    assert after["quota_slot_held"] is False


def test_zoning_buffer_distance_exactly_equal_satisfies(api):
    """PRD §3.3: "The boundary is inclusive — `buffer_satisfied` is true exactly
    when the premise's `distance_to_school_m` is greater than or equal to the
    required separation, so a distance equal to the requirement satisfies it."
    PRD §3.3: "A `CLEAR` decision moves it to `CLEARED` but is only permitted when
    `buffer_satisfied` is true"

    distance_to_school_m == 100 (exactly the ON_PREMISE buffer) -> buffer_satisfied
    true -> CLEAR succeeds, review CLEARED.

    Design: Difficulty/boundary_precision_check/zoning_buffer_distance_exactly_equals_required_is_satisfied
    """
    # Build the pipeline directly with a premise at exactly 100 metres.
    ref = setup_reference_data(
        applicant_overrides={"legal_name": "Edge Bar"},
    )
    owner = make_applicant_headers(ref["owner_id"])
    prem = get_success_data(api.create_premise(
        {"applicant_id": ref["owner_id"], "region_code": ref["region"]["region_code"],
         "street_address": "100 Edge St", "distance_to_school_m": 100,
         "zoning_district": "COMMERCIAL"}, owner))
    app2 = get_success_data(api.create_application(
        {"applicant_id": ref["owner_id"], "premise_id": prem["id"], "license_class_code": "ON_47"},
        owner))
    reg_now = get_success_data(api.get_quota_region(ref["region"]["id"], DIRECTOR))
    get_success_data(api.submit_application(
        app2["id"], {"expected_region_version": reg_now["version"]}, owner))
    zr = get_success_data(api.list_application_zoning_reviews(app2["id"], ZONING))
    zr_id = zr[0]["id"]
    assert zr[0]["buffer_satisfied"] is True, "distance 100 == buffer should satisfy"
    decided = validate_success(api.decide_zoning_review(zr_id, {"decision": "CLEAR"}, ZONING))
    assert decided["result"] == "CLEARED", f"got {decided['result']}"


# ─── Queue A: cross_entity_state_dependency ───────────────────────────────
def test_begin_review_blocked_until_background_passed(api):
    """PRD §3.4: "the application's background check must have resolved to
    `PASSED` — otherwise `ERR_BACKGROUND_NOT_PASSED` (422)"

    With the background check still PENDING (zoning already CLEARED), begin-review
    fails ERR_BACKGROUND_NOT_PASSED and the application stays SUBMITTED.

    Design: Difficulty/cross_entity_state_dependency/begin_review_blocked_until_background_check_passed
    """
    ref, app = create_submitted_application()
    # Clear zoning but leave background PENDING.
    zr = get_success_data(api.list_application_zoning_reviews(app["id"], ZONING))
    get_success_data(api.decide_zoning_review(zr[0]["id"], {"decision": "CLEAR"}, ZONING))
    resp = api.begin_review(app["id"], EXAMINER)
    validate_error(resp, ApiErrorId.ERR_BACKGROUND_NOT_PASSED.value)
    after = get_success_data(api.get_application(app["id"], DIRECTOR))
    assert after["status"] == "SUBMITTED"


def test_server_activate_blocked_unless_license_active(api):
    """PRD §3.7: "Activating a permit advances it from `PENDING` to `ACTIVE` and
    is gated three ways: the holder's `training_completed` must be true ...; the
    parent license must be `ACTIVE`; and the license's `active_server_count` must
    be strictly less than the class's `max_servers_per_license`"
    PRD §2.8: "Whether the target is in a state from which the requested
    transition is defined is checked fourth, failing with `ERR_INVALID_STATE`
    (409)."

    With the license SUSPENDED (demerit cascade), activating a fresh trained
    PENDING permit fails ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/server_activate_blocked_unless_license_active
    """
    bundle = setup_issued_license()
    lic_id = bundle["license"]["id"]
    owner_id = bundle["ref"]["owner_id"]
    permit = create_server_permit(lic_id, owner_id, training_completed=True, holder_name="Bartender B")
    # Drive license to SUSPENDED.
    v1 = file_violation(lic_id, severity="EGREGIOUS")
    sustain_violation(v1["id"], action_type="FINE")
    v2 = file_violation(lic_id, severity="SERIOUS")
    sustain_violation(v2["id"], action_type="FINE")
    lic = get_success_data(api.get_license(lic_id, DIRECTOR))
    assert lic["status"] == "SUSPENDED"
    resp = api.activate_server_permit(
        permit["id"], {"expected_license_version": lic["version"]}, make_applicant_headers(owner_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api.get_server_permit(permit["id"], DIRECTOR))
    assert after["status"] == "PENDING"


# ─── Queue A: resource_temporal_overlap ───────────────────────────────────
def test_hearing_room_overlap_rejected_half_open(api):
    """PRD §3.5: "The room may not be double-booked: the requested window must not
    overlap any existing hearing already booked in the same `room_code`. Overlap
    here uses **half-open** semantics — two windows that merely touch, where one
    ends exactly when the next begins, do **not** conflict and are allowed; any
    genuine overlap is rejected with `ERR_HEARING_ROOM_CONFLICT` (409)."

    A second hearing in RM-1 [10:30, 11:30) genuinely overlaps the first
    [09:00, 11:00) -> ERR_HEARING_ROOM_CONFLICT; the protest stays FILED.

    Design: Difficulty/resource_temporal_overlap/hearing_room_half_open_adjacency_allowed_overlap_rejected
    """
    # First application -> SCHEDULED hearing in RM-1 [09:00, 11:00).
    refA, appA = create_submitted_application(applicant_overrides={"legal_name": "Bar A"})
    advance_to_protest_period(refA, appA)
    prA = get_success_data(api.create_protest(
        {"application_id": appA["id"], "protester_name": "P1", "grounds": "ZONING"},
        TEST_USERS["anonymous_headers"]))
    get_success_data(api.schedule_hearing(
        prA["id"], {"room_code": "RM-1", "starts_at": "2026-01-05T09:00:00Z",
                    "ends_at": "2026-01-05T11:00:00Z"}, ADJUDICATOR))
    # Second application in the same region -> FILED protest.
    reg = get_success_data(api.list_quota_regions(DIRECTOR))[0]
    oB = get_success_data(api.create_applicant({"legal_name": "Bar B"}, DIRECTOR))
    pB = get_success_data(api.create_premise(
        {"applicant_id": oB["id"], "region_code": reg["region_code"], "street_address": "2 B St",
         "distance_to_school_m": 200, "zoning_district": "COMMERCIAL"}, make_applicant_headers(oB["id"])))
    aB = get_success_data(api.create_application(
        {"applicant_id": oB["id"], "premise_id": pB["id"], "license_class_code": "ON_47"},
        make_applicant_headers(oB["id"])))
    reg_now = get_success_data(api.get_quota_region(reg["id"], DIRECTOR))
    get_success_data(api.submit_application(
        aB["id"], {"expected_region_version": reg_now["version"]}, make_applicant_headers(oB["id"])))
    zrB = get_success_data(api.list_application_zoning_reviews(aB["id"], ZONING))
    get_success_data(api.decide_zoning_review(zrB[0]["id"], {"decision": "CLEAR"}, ZONING))
    bcB = get_success_data(api.list_application_background_checks(aB["id"], EXAMINER))
    get_success_data(api.resolve_background_check(bcB[0]["id"], {"decision": "PASS"}, EXAMINER))
    get_success_data(api.begin_review(aB["id"], EXAMINER))
    get_success_data(api.open_protest_period(aB["id"], EXAMINER))
    prB = get_success_data(api.create_protest(
        {"application_id": aB["id"], "protester_name": "P2", "grounds": "ZONING"},
        TEST_USERS["anonymous_headers"]))
    # Overlapping window [10:30, 11:30) in RM-1.
    resp = api.schedule_hearing(
        prB["id"], {"room_code": "RM-1", "starts_at": "2026-01-05T10:30:00Z",
                    "ends_at": "2026-01-05T11:30:00Z"}, ADJUDICATOR)
    validate_error(resp, ApiErrorId.ERR_HEARING_ROOM_CONFLICT.value)
    after = get_success_data(api.get_protest(prB["id"], DIRECTOR))
    assert after["status"] == "FILED"


def test_premise_term_closed_interval_overlap_conflicts(api):
    """PRD §3.12: "Two closed windows conflict when the relocating license's
    `term_start_at` is less than or equal to the candidate's `term_end_at` and the
    candidate's `term_start_at` is less than or equal to the relocating license's
    `term_end_at`."
    PRD §3.12: "A conflict is rejected with `ERR_PREMISE_TERM_CONFLICT` (409)."

    A LOCATION transfer onto a premise already hosting a same-class ON_47 license
    whose 12-month term overlaps the relocating license's term -> conflict.

    Design: Difficulty/resource_temporal_overlap/premise_term_closed_interval_overlap_conflicts
    """
    # Host license at premT (term [2026-02-01, 2027-02-01]).
    get_success_data(api.set_clock("2026-01-01T00:00:00Z", DIRECTOR))
    get_success_data(api.create_license_class(
        {"code": "ON_47", "premise_type": "ON_PREMISE", "quota_managed": True,
         "base_fee_cents": 100000, "renewal_cycle_months": 12, "requires_zoning": True,
         "max_servers_per_license": 5}, DIRECTOR))
    region = get_success_data(api.create_quota_region(
        {"region_code": "CTY_LA", "population": 50000, "persons_per_license": 25000}, DIRECTOR))

    def issue_license_at(legal_name, street):
        owner = get_success_data(api.create_applicant({"legal_name": legal_name}, DIRECTOR))
        oh = make_applicant_headers(owner["id"])
        prem = get_success_data(api.create_premise(
            {"applicant_id": owner["id"], "region_code": "CTY_LA", "street_address": street,
             "distance_to_school_m": 200, "zoning_district": "COMMERCIAL"}, oh))
        app = get_success_data(api.create_application(
            {"applicant_id": owner["id"], "premise_id": prem["id"], "license_class_code": "ON_47"}, oh))
        reg_now = get_success_data(api.get_quota_region(region["id"], DIRECTOR))
        get_success_data(api.submit_application(
            app["id"], {"expected_region_version": reg_now["version"]}, oh))
        bc = get_success_data(api.list_application_background_checks(app["id"], EXAMINER))
        get_success_data(api.resolve_background_check(bc[0]["id"], {"decision": "PASS"}, EXAMINER))
        zr = get_success_data(api.list_application_zoning_reviews(app["id"], ZONING))
        get_success_data(api.decide_zoning_review(zr[0]["id"], {"decision": "CLEAR"}, ZONING))
        get_success_data(api.begin_review(app["id"], EXAMINER))
        get_success_data(api.open_protest_period(app["id"], EXAMINER))
        return owner, oh, prem, app

    ownerH, ohH, premT, appH = issue_license_at("Host Bar", "1 Host St")
    ownerM, ohM, premM, appM = issue_license_at("Mover Bar", "2 Mover St")
    # Approve+issue both at clock 2026-02-01 so both terms are [2026-02-01, 2027-02-01].
    get_success_data(api.set_clock("2026-02-01T00:00:00Z", DIRECTOR))
    for owner_h, app in ((ohH, appH), (ohM, appM)):
        get_success_data(api.approve_application(app["id"], DIRECTOR))
        get_success_data(api.pay_fee(app["id"], {"amount_cents": 110000}, owner_h))
        get_success_data(api.issue_application(app["id"], DIRECTOR))
    licM = get_success_data(api.list_licenses(DIRECTOR, params={"application_id": appM["id"]}))[0]
    # LOCATION transfer of Mover's license onto the Host premise (overlapping term).
    tr = get_success_data(api.create_transfer_request(
        {"license_id": licM["id"], "transfer_type": "LOCATION", "new_premise_id": premT["id"]}, ohM))
    resp = api.approve_transfer_request(tr["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_PREMISE_TERM_CONFLICT.value)
    after = get_success_data(api.get_transfer_request(tr["id"], DIRECTOR))
    assert after["status"] == "PENDING"
