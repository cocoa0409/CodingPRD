"""Declared initial states at creation and terminal-state lockdown.

New tenants are APPLICANT, offerings OPEN with a zero eligible count, bids
SUBMITTED, leases DRAFT; terminal states (AWARDED offering, WITHDRAWN bid,
ACTIVE-from-DRAFT activation) reject further transitions with
ERR_INVALID_STATE.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_lease,
    assert_tenant,
    create_lease_payload,
    get_bid,
    get_offering,
    make_tenant_headers,
    setup_active_lease,
    setup_bid,
    setup_draft_lease,
    setup_field,
    setup_landlord,
    setup_offering,
    setup_tenant,
    shortlist_close_award,
    validate_error,
    validate_success,
)

MGR = TEST_USERS["farm_manager_headers"]


def test_created_entities_start_in_initial_state(api):
    """PRD §3.1: "A new tenant starts in `APPLICANT` status with a `compliance_score` of 100, on a scale that runs from 0 to 100."
    PRD §3.2: "An offering opens in `OPEN` status with an `eligible_bid_count` of zero"
    PRD §3.2: "A bid that passes starts in `SUBMITTED` status, its `evaluation_score` is computed, and the offering's `eligible_bid_count` is recomputed."
    PRD §3.4: "The draft's `term_index` starts at 1, its `landlord_credit_cents` at zero, and its `status` at `DRAFT`."

    Design: Corner/state_machines/created_entities_start_in_initial_state
    """
    landlord = setup_landlord(name="L Ini", contact_email="li2@x.com")
    tenant_resp = api.create_tenant(
        {"name": "T Ini", "years_experience": 5}, MGR
    )
    tenant = validate_success(tenant_resp, 201)
    assert_tenant(tenant)
    assert tenant["status"] == "APPLICANT", "tenant starts APPLICANT"
    assert tenant["compliance_score"] == 100, "compliance_score starts at 100"
    validate_success(api.approve_tenant(tenant["id"], MGR))

    field = setup_field(landlord["id"], name="FIni")
    offering_resp = api.create_offering(
        {
            "field_id": field["id"],
            "term_years": 1,
            "term_start_date": "2027-03-01T00:00:00Z",
            "min_bid_per_acre_cents": 20000,
            "reference_yield_bu_per_acre": 200,
            "reference_price_cents_per_bu": 500,
            "bid_deadline": "2026-06-15T00:00:00Z",
        },
        MGR,
    )
    offering = validate_success(offering_resp, 201)
    assert offering["status"] == "OPEN", "offering opens in OPEN status"
    assert offering["eligible_bid_count"] == 0, "eligible_bid_count starts at zero"

    bid = setup_bid(offering["id"], tenant["id"], "CASH")
    assert bid["status"] == "SUBMITTED", "bid starts SUBMITTED"

    bid = shortlist_close_award(offering["id"], bid["id"], landlord["id"])
    lease_resp = api.create_lease(create_lease_payload(bid["id"]), MGR)
    lease = validate_success(lease_resp, 201)
    assert_lease(lease)
    assert lease["status"] == "DRAFT", "lease starts DRAFT"
    assert lease["term_index"] == 1, "term_index starts at 1"
    assert lease["landlord_credit_cents"] == 0, "landlord_credit_cents starts at zero"


def test_lease_double_activate_rejected(api):
    """PRD §3.4: "A successful activation moves the lease from `DRAFT` to `ACTIVE`"
    PRD §2.8: "State preconditions — the target resource must be in a valid from-state for the requested transition (`ERR_INVALID_STATE`, HTTP 409)"

    Design: Corner/state_machines/lease_double_activate_rejected
    """
    ctx = setup_active_lease("CASH")
    assert ctx["lease"]["status"] == "ACTIVE"
    resp = api.activate_lease(ctx["lease"]["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_awarded_offering_close_rejected(api):
    """PRD §3.3: "A successful award moves the offering from `CLOSED` to the terminal `AWARDED` state"
    PRD §2.8: "State preconditions — the target resource must be in a valid from-state for the requested transition (`ERR_INVALID_STATE`, HTTP 409)"

    Design: Corner/state_machines/awarded_offering_close_rejected
    """
    ctx = setup_active_lease("CASH", activate=False)
    offering = get_offering(ctx["offering"]["id"])
    assert offering["status"] == "AWARDED"
    resp = api.close_offering(offering["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    bid = get_bid(ctx["bid"]["id"])
    assert bid["status"] == "ACCEPTED", "winning bid is untouched by the failed close"


def test_bid_withdraw_twice_rejected(api):
    """PRD §3.2: "A tenant may also withdraw a bid they own — the bid's `tenant_id` must equal the caller's `X-User-ID`, else `ERR_NOT_RESOURCE_OWNER` — moving it from `SUBMITTED` or `SHORTLISTED` to `WITHDRAWN`"
    PRD §2.8: "State preconditions — the target resource must be in a valid from-state for the requested transition (`ERR_INVALID_STATE`, HTTP 409)"

    Design: Corner/state_machines/bid_withdraw_twice_rejected
    """
    landlord = setup_landlord(name="L WW", contact_email="lww@x.com")
    tenant = setup_tenant(name="T WW", years_experience=5)
    field = setup_field(landlord["id"], name="FWW")
    offering = setup_offering(field["id"])
    bid = setup_bid(offering["id"], tenant["id"], "CASH")

    first = api.withdraw_bid(bid["id"], make_tenant_headers(tenant["id"]))
    withdrawn = validate_success(first)
    assert withdrawn["status"] == "WITHDRAWN"

    resp = api.withdraw_bid(bid["id"], make_tenant_headers(tenant["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
