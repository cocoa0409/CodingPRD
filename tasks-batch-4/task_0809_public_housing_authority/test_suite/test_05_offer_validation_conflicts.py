"""Offer/accept guard precedence and the make-ready turnover buffer."""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_applicant_headers,
)
from test_helpers.fixtures import (
    set_clock, create_unit, create_offer,
    setup_drawn_active_entry, setup_terminated_tenancy,
)

IC = TEST_USERS["intake_clerk_headers"]
HS = TEST_USERS["housing_specialist_headers"]


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / accept_invalid_state_beats_offer_expired
# ---------------------------------------------------------------------------
def test_accept_refused_and_expired_offer_returns_invalid_state(api):
    """PRD §3.4: "three conditions are checked in order after existence and ownership:
    the offer must be PENDING (else ERR_INVALID_STATE), the offered unit must still be
    in OFFERED (else ERR_UNIT_NOT_AVAILABLE), and the current logical time must be at or
    before the offer's expires_at (else ERR_OFFER_EXPIRED)."

    Design: Difficulty/priority_pair_validation_conflict/accept_invalid_state_beats_offer_expired
    """
    ctx = setup_drawn_active_entry(api, applicant_name="Prio1")
    unit = create_unit(api, bedroom_size=2)
    offer = create_offer(api, ctx["entry_id"], unit["id"], expires_at="2026-03-05T00:00:00Z")
    app_headers = make_applicant_headers(ctx["applicant"]["id"])
    get_success_data(api.refuse_offer(offer["id"], app_headers))
    set_clock(api, "2026-03-10T00:00:00Z")
    resp = api.accept_offer(offer["id"], app_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_accept_refused_offer_leaves_it_refused(api):
    """PRD §3.4: "An offer's status is one of PENDING, ACCEPTED, or REFUSED, with
    ACCEPTED and REFUSED terminal." (a rejected accept must not mutate the offer).

    Design: Difficulty/priority_pair_validation_conflict/accept_invalid_state_beats_offer_expired
    """
    ctx = setup_drawn_active_entry(api, applicant_name="Prio1b")
    unit = create_unit(api, bedroom_size=2)
    offer = create_offer(api, ctx["entry_id"], unit["id"], expires_at="2026-03-05T00:00:00Z")
    app_headers = make_applicant_headers(ctx["applicant"]["id"])
    get_success_data(api.refuse_offer(offer["id"], app_headers))
    set_clock(api, "2026-03-10T00:00:00Z")
    api.accept_offer(offer["id"], app_headers)
    assert get_success_data(api.get_offer(offer["id"], HS))["status"] == "REFUSED"


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / offer_bedroom_mismatch_beats_turnover_buffer
# ---------------------------------------------------------------------------
def test_offer_bedroom_mismatch_beats_turnover_buffer(api):
    """PRD §3.4: "the unit's bedroom_size must equal the bedroom size of the waitlist
    behind the entry, or the offer is rejected with ERR_BEDROOM_MISMATCH; and if the
    unit carries a last_lease_end_date, the current logical time must be on or after 14
    days past that date (the make-ready buffer), otherwise the offer is rejected with
    ERR_UNIT_TURNOVER_CONFLICT."

    Design: Difficulty/priority_pair_validation_conflict/offer_bedroom_mismatch_beats_turnover_buffer
    """
    freed = setup_terminated_tenancy(api, bedroom_size=3)  # bedroom-3 unit, AVAILABLE, buffered
    b2 = setup_drawn_active_entry(api, bedroom_size=2, applicant_name="B2", site_name="Site 2BR")
    resp = api.create_offer(
        {"waitlist_entry_id": b2["entry_id"], "unit_id": freed["unit"]["id"],
         "expires_at": "2026-12-31T00:00:00Z"}, HS)
    validate_error(resp, ApiErrorId.ERR_BEDROOM_MISMATCH)


def test_offer_bedroom_mismatch_creates_no_offer(api):
    """PRD §3.4: "creating it moves the unit from AVAILABLE to OFFERED" — a rejected
    offer creates nothing and leaves the freed unit AVAILABLE.

    Design: Difficulty/priority_pair_validation_conflict/offer_bedroom_mismatch_beats_turnover_buffer
    """
    freed = setup_terminated_tenancy(api, bedroom_size=3)
    b2 = setup_drawn_active_entry(api, bedroom_size=2, applicant_name="B2b", site_name="Site 2BRb")
    api.create_offer(
        {"waitlist_entry_id": b2["entry_id"], "unit_id": freed["unit"]["id"],
         "expires_at": "2026-12-31T00:00:00Z"}, HS)
    assert get_success_data(api.get_unit(freed["unit"]["id"], HS))["status"] == "AVAILABLE"


# ---------------------------------------------------------------------------
# resource_temporal_overlap / unit_make_ready_buffer_not_elapsed
# ---------------------------------------------------------------------------
def test_offer_within_make_ready_buffer_rejected(api):
    """PRD §3.4: "if the unit carries a last_lease_end_date, the current logical time
    must be on or after 14 days past that date (the make-ready buffer), otherwise the
    offer is rejected with ERR_UNIT_TURNOVER_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/unit_make_ready_buffer_not_elapsed
    """
    freed = setup_terminated_tenancy(api, bedroom_size=2)  # last_lease_end_date 2026-03-01
    set_clock(api, "2026-03-10T00:00:00Z")  # only 9 days later, inside the 14-day buffer
    b2 = setup_drawn_active_entry(api, bedroom_size=2, applicant_name="MR-B2", site_name="Site B")
    resp = api.create_offer(
        {"waitlist_entry_id": b2["entry_id"], "unit_id": freed["unit"]["id"],
         "expires_at": "2026-12-31T00:00:00Z"}, HS)
    validate_error(resp, ApiErrorId.ERR_UNIT_TURNOVER_CONFLICT)


def test_offer_within_make_ready_buffer_leaves_unit_available(api):
    """PRD §3.4: "the unit moves from OCCUPIED back to AVAILABLE and records the freed
    lease's end date into its last_lease_end_date (which in turn arms the make-ready
    buffer for that unit's next offer)." A buffered offer creates nothing.

    Design: Difficulty/resource_temporal_overlap/unit_make_ready_buffer_not_elapsed
    """
    freed = setup_terminated_tenancy(api, bedroom_size=2)
    set_clock(api, "2026-03-10T00:00:00Z")
    b2 = setup_drawn_active_entry(api, bedroom_size=2, applicant_name="MR-B2b", site_name="Site Bb")
    api.create_offer(
        {"waitlist_entry_id": b2["entry_id"], "unit_id": freed["unit"]["id"],
         "expires_at": "2026-12-31T00:00:00Z"}, HS)
    assert get_success_data(api.get_unit(freed["unit"]["id"], HS))["status"] == "AVAILABLE"


# ---------------------------------------------------------------------------
# Corner: accept_expired_pending_offer_returns_offer_expired
# ---------------------------------------------------------------------------
def test_accept_expired_pending_offer_returns_offer_expired(api):
    """PRD §3.4: "the current logical time must be at or before the offer's expires_at
    (else ERR_OFFER_EXPIRED)."

    Design: Corner/validations/accept_expired_pending_offer_returns_offer_expired
    """
    ctx = setup_drawn_active_entry(api, applicant_name="Exp")
    unit = create_unit(api, bedroom_size=2)
    offer = create_offer(api, ctx["entry_id"], unit["id"], expires_at="2026-03-05T00:00:00Z")
    set_clock(api, "2026-03-10T00:00:00Z")
    resp = api.accept_offer(offer["id"], make_applicant_headers(ctx["applicant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED)
