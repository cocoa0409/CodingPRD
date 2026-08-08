"""Appointment scheduling: prior-auth gating, expiry, the referential-beats-
temporal precedence, and the two distinct resource collision models.

The two precedence/dependency difficulty instances each carry a complementary
second test that removes the winning violation to confirm the pre-empted rule
was genuinely present. The two overlap instances each pair the conflict with the
adjacent boundary that is allowed.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_appointment_payload, approve_prior_authorization_payload,
    fixtures, TEST_USERS,
)

PROVIDER = TEST_USERS["provider_staff_headers"]
PAYER = TEST_USERS["payer_analyst_headers"]

START = "2026-06-02T10:00:00Z"
END = "2026-06-02T11:00:00Z"


# ==========================================================================
# Helpers
# ==========================================================================
def _issue_accept(api, patient_id, contract_id, procedure_id):
    est = fixtures.new_estimate(api, patient_id, estimate_type="GFE_INSURED",
                                contract_id=contract_id)
    fixtures.add_line(api, est["id"], procedure_id)
    fixtures.issue(api, est["id"])
    return fixtures.accept(api, est["id"], patient_id)


def _two_accepted_estimates(api):
    """One patient with two ACCEPTED insured estimates (no prior-auth), two free
    providers and two free rooms. Used by the overlap and precedence tests."""
    fixtures.set_clock(api)
    plan = fixtures.new_benefit_plan(api)
    patient = fixtures.new_patient(api, plan["id"])
    contract = fixtures.new_active_contract(api)
    procedure = fixtures.new_procedure(api, requires_prior_auth=False)
    fixtures.ingest_flat_rate(api, contract["id"], procedure["id"], 200000)
    prov1 = fixtures.new_provider(api, npi="1000000101")
    prov2 = fixtures.new_provider(api, npi="1000000102")
    room1 = fixtures.new_room(api, name="Room-1")
    room2 = fixtures.new_room(api, name="Room-2")
    e0 = _issue_accept(api, patient["id"], contract["id"], procedure["id"])
    e1 = _issue_accept(api, patient["id"], contract["id"], procedure["id"])
    return {
        "patient": patient, "prov1": prov1, "prov2": prov2,
        "room1": room1, "room2": room2, "e0": e0, "e1": e1,
    }


def _accepted_prior_auth_estimate(api):
    """One ACCEPTED insured estimate whose only procedure requires_prior_auth,
    plus a free provider and room and a REQUESTED prior auth on the estimate."""
    fixtures.set_clock(api)
    plan = fixtures.new_benefit_plan(api)
    patient = fixtures.new_patient(api, plan["id"])
    contract = fixtures.new_active_contract(api)
    procedure = fixtures.new_procedure(
        api, code="27447", setting="INPATIENT", requires_prior_auth=True)
    fixtures.ingest_flat_rate(api, contract["id"], procedure["id"], 200000)
    est = _issue_accept(api, patient["id"], contract["id"], procedure["id"])
    provider = fixtures.new_provider(api, npi="1000000201")
    room = fixtures.new_room(api, name="OR-1", room_type="PROCEDURE")
    pa = fixtures.request_prior_auth(api, est["id"], procedure_code="27447")
    return {"patient": patient, "estimate": est, "provider": provider,
            "room": room, "prior_auth": pa}


def _schedule(api, patient_id, estimate_id, provider_id, room_id,
              start, end, prior_auth_id=None):
    return api.create_appointment(
        create_appointment_payload(patient_id, estimate_id, provider_id, room_id,
                                   start, end, prior_auth_id=prior_auth_id),
        PROVIDER)


# ==========================================================================
# Difficulty — appointment requires an APPROVED prior auth
# ==========================================================================
def test_schedule_denied_prior_auth_rejected(api):
    """PRD §3.7: "If any procedure on the estimate's lines has requires_prior_auth
    set, the request must also carry a prior_auth_id whose PriorAuthorization is
    in APPROVED status; a missing or non-approved authorization is refused with
    ERR_PRIOR_AUTH_NOT_APPROVED."

    Design: Difficulty/cross_entity_state_dependency/cesd_appointment_requires_prior_auth_approved
    """
    s = _accepted_prior_auth_estimate(api)
    fixtures.deny_prior_auth(api, s["prior_auth"]["id"], "Insufficient documentation")
    resp = _schedule(api, s["patient"]["id"], s["estimate"]["id"],
                     s["provider"]["id"], s["room"]["id"], START, END,
                     prior_auth_id=s["prior_auth"]["id"])
    validate_error(resp, ApiErrorId.ERR_PRIOR_AUTH_NOT_APPROVED.value, 409)


def test_schedule_succeeds_with_approved_prior_auth(api):
    """PRD §3.7: "the request must also carry a `prior_auth_id` whose
    `PriorAuthorization` is in `APPROVED` status." PRD §3.7: "A successful
    schedule creates the appointment in `SCHEDULED`." (Approving the same auth
    lets scheduling through, isolating the authorization state as the gate.)

    Design: Difficulty/cross_entity_state_dependency/cesd_appointment_requires_prior_auth_approved
    """
    s = _accepted_prior_auth_estimate(api)
    fixtures.approve_prior_auth(api, s["prior_auth"]["id"], auth_number="AUTH-OK",
                                expiration_date="2026-12-31T00:00:00Z")
    appt = validate_success(
        _schedule(api, s["patient"]["id"], s["estimate"]["id"],
                  s["provider"]["id"], s["room"]["id"], START, END,
                  prior_auth_id=s["prior_auth"]["id"]), 201)
    assert appt["status"] == "SCHEDULED"


# ==========================================================================
# Corner — expired prior auth
# ==========================================================================
def test_schedule_expired_prior_auth_rejected(api):
    """PRD §3.7: "an authorization that is approved but whose expiration_date
    falls before the appointment's start is refused with ERR_PRIOR_AUTH_EXPIRED."

    Design: Corner/state_machines/schedule_with_expired_prior_auth_returns_expired
    """
    s = _accepted_prior_auth_estimate(api)
    fixtures.approve_prior_auth(api, s["prior_auth"]["id"], auth_number="AUTH-9",
                                expiration_date="2026-06-01T00:00:00Z")  # before start
    resp = _schedule(api, s["patient"]["id"], s["estimate"]["id"],
                     s["provider"]["id"], s["room"]["id"], START, END,
                     prior_auth_id=s["prior_auth"]["id"])
    validate_error(resp, ApiErrorId.ERR_PRIOR_AUTH_EXPIRED.value, 409)


# ==========================================================================
# Difficulty — referential (prior auth) beats temporal (provider) precedence
# ==========================================================================
def _prior_auth_and_provider_conflict_scenario(api):
    """Provider busy 10:00-11:00; a second ACCEPTED estimate whose procedure
    requires_prior_auth with a REQUESTED (not approved) auth; free room2."""
    fixtures.set_clock(api)
    plan = fixtures.new_benefit_plan(api)
    patient = fixtures.new_patient(api, plan["id"])
    contract = fixtures.new_active_contract(api)
    proc_noauth = fixtures.new_procedure(api, code="70450", requires_prior_auth=False)
    fixtures.ingest_flat_rate(api, contract["id"], proc_noauth["id"], 200000)
    proc_auth = fixtures.new_procedure(
        api, code="27447", setting="INPATIENT", requires_prior_auth=True)
    fixtures.ingest_flat_rate(api, contract["id"], proc_auth["id"], 200000)
    provider = fixtures.new_provider(api, npi="1000000301")
    room1 = fixtures.new_room(api, name="Room-1", room_type="PROCEDURE")
    room2 = fixtures.new_room(api, name="Room-2", room_type="PROCEDURE")
    # First accepted estimate + appointment occupying the provider 10:00-11:00.
    e0 = _issue_accept(api, patient["id"], contract["id"], proc_noauth["id"])
    fixtures.schedule_appointment(api, patient["id"], e0["id"], provider["id"],
                                  room1["id"], START, END)
    # Second accepted estimate needing prior auth, with a REQUESTED auth.
    e1 = _issue_accept(api, patient["id"], contract["id"], proc_auth["id"])
    pa = fixtures.request_prior_auth(api, e1["id"], procedure_code="27447")
    return {"patient": patient, "provider": provider, "room2": room2,
            "e1": e1, "prior_auth": pa}


def test_prior_auth_error_preempts_provider_conflict(api):
    """PRD §3.7: "a missing or non-approved authorization is refused with
    ERR_PRIOR_AUTH_NOT_APPROVED ... The provider-buffer and room-half-open
    availability checks of Section 2.9 then apply." The prior-auth check is
    sequenced before the availability checks, so it wins.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_prior_auth_referential_beats_provider_temporal
    """
    s = _prior_auth_and_provider_conflict_scenario(api)
    # Requested (not approved) auth AND provider busy in the 10:30-11:30 window.
    resp = _schedule(api, s["patient"]["id"], s["e1"]["id"], s["provider"]["id"],
                     s["room2"]["id"], "2026-06-02T10:30:00Z", "2026-06-02T11:30:00Z",
                     prior_auth_id=s["prior_auth"]["id"])
    validate_error(resp, ApiErrorId.ERR_PRIOR_AUTH_NOT_APPROVED.value, 409)


def test_provider_conflict_surfaces_once_auth_approved(api):
    """PRD §2.9: "A provider is unavailable for a requested window if the provider
    already has an appointment in SCHEDULED or COMPLETED status such that fewer
    than 15 minutes of clearance separate the two windows ... A conflict yields
    ERR_PROVIDER_UNAVAILABLE." (Approving the auth removes the referential block,
    revealing the temporal conflict that was pre-empted.)

    Design: Difficulty/priority_pair_validation_conflict/ppvc_prior_auth_referential_beats_provider_temporal
    """
    s = _prior_auth_and_provider_conflict_scenario(api)
    fixtures.approve_prior_auth(api, s["prior_auth"]["id"], auth_number="AUTH-OK",
                                expiration_date="2026-12-31T00:00:00Z")
    resp = _schedule(api, s["patient"]["id"], s["e1"]["id"], s["provider"]["id"],
                     s["room2"]["id"], "2026-06-02T10:30:00Z", "2026-06-02T11:30:00Z",
                     prior_auth_id=s["prior_auth"]["id"])
    validate_error(resp, ApiErrorId.ERR_PROVIDER_UNAVAILABLE.value, 409)


# ==========================================================================
# Difficulty — provider buffered overlap
# ==========================================================================
def test_provider_buffered_conflict(api):
    """PRD §2.9: "provider bookings are buffered by 15 minutes. A provider is
    unavailable for a requested window if the provider already has an appointment
    in SCHEDULED or COMPLETED status such that fewer than 15 minutes of clearance
    separate the two windows."

    Design: Difficulty/resource_temporal_overlap/rto_provider_buffered_overlap
    """
    s = _two_accepted_estimates(api)
    fixtures.schedule_appointment(api, s["patient"]["id"], s["e0"]["id"],
                                  s["prov1"]["id"], s["room1"]["id"], START, END)
    # Same provider, 5-minute gap (< 15) -> unavailable; different room isolates it.
    resp = _schedule(api, s["patient"]["id"], s["e1"]["id"], s["prov1"]["id"],
                     s["room2"]["id"], "2026-06-02T11:05:00Z", "2026-06-02T12:00:00Z")
    validate_error(resp, ApiErrorId.ERR_PROVIDER_UNAVAILABLE.value, 409)


def test_provider_exact_buffer_gap_allowed(api):
    """PRD §2.9: "such that fewer than 15 minutes of clearance separate the two
    windows." A full 15-minute gap is not fewer than 15, so it is allowed.

    Design: Difficulty/resource_temporal_overlap/rto_provider_buffered_overlap
    """
    s = _two_accepted_estimates(api)
    fixtures.schedule_appointment(api, s["patient"]["id"], s["e0"]["id"],
                                  s["prov1"]["id"], s["room1"]["id"], START, END)
    # Same provider, exactly 15-minute clearance (11:00 -> 11:15) -> allowed.
    appt = validate_success(
        _schedule(api, s["patient"]["id"], s["e1"]["id"], s["prov1"]["id"],
                  s["room2"]["id"], "2026-06-02T11:15:00Z", "2026-06-02T12:00:00Z"), 201)
    assert appt["status"] == "SCHEDULED"


# ==========================================================================
# Difficulty — room half-open overlap
# ==========================================================================
def test_room_halfopen_conflict(api):
    """PRD §2.9: "a room is unavailable only if some existing SCHEDULED or
    COMPLETED appointment for that room has a half-open interval that actually
    overlaps the requested half-open interval." A room conflict yields
    ERR_ROOM_UNAVAILABLE.

    Design: Difficulty/resource_temporal_overlap/rto_room_halfopen_overlap
    """
    s = _two_accepted_estimates(api)
    fixtures.schedule_appointment(api, s["patient"]["id"], s["e0"]["id"],
                                  s["prov1"]["id"], s["room1"]["id"], START, END)
    # Same room, 10:30-11:30 overlaps 10:00-11:00; a free provider isolates the room.
    resp = _schedule(api, s["patient"]["id"], s["e1"]["id"], s["prov2"]["id"],
                     s["room1"]["id"], "2026-06-02T10:30:00Z", "2026-06-02T11:30:00Z")
    validate_error(resp, ApiErrorId.ERR_ROOM_UNAVAILABLE.value, 409)


def test_room_back_to_back_allowed(api):
    """PRD §2.9: "two bookings that merely touch end-to-start (one ending exactly
    when the next begins) do not conflict."

    Design: Difficulty/resource_temporal_overlap/rto_room_halfopen_overlap
    """
    s = _two_accepted_estimates(api)
    fixtures.schedule_appointment(api, s["patient"]["id"], s["e0"]["id"],
                                  s["prov1"]["id"], s["room1"]["id"], START, END)
    # Same room, 11:00-12:00 begins exactly when 10:00-11:00 ends -> allowed.
    appt = validate_success(
        _schedule(api, s["patient"]["id"], s["e1"]["id"], s["prov2"]["id"],
                  s["room1"]["id"], "2026-06-02T11:00:00Z", "2026-06-02T12:00:00Z"), 201)
    assert appt["status"] == "SCHEDULED"
