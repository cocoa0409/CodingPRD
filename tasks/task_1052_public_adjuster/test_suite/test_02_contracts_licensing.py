"""Contract lifecycle, statutory fee cap, rescission window, license overlap."""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    create_contract_payload, create_license_payload,
    make_client_headers, make_public_adjuster_headers,
)
from test_helpers.fixtures import (
    setup_active_contract, new_adjuster, new_license, new_client, new_contract,
    set_clock,
)

FIRM = TEST_USERS["firm_principal_headers"]


# ---------------------------------------------- statutory fee cap (boundary triple)
def test_contract_fee_pct_equal_to_statutory_cap_accepted(api):
    """PRD §3.2: "a contract whose `fee_pct` is greater than its `statutory_cap_pct` is
    rejected with `ERR_FEE_EXCEEDS_STATUTORY_CAP`, while equality is accepted."

    Design: Difficulty/boundary_precision_check/contract_fee_pct_equal_to_statutory_cap_accepted
    """
    adj = new_adjuster(api)
    cli = new_client(api)
    resp = api.create_contract(create_contract_payload(cli, adj, fee_pct=0.10, statutory_cap_pct=0.10), FIRM)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"
    assert data["fee_pct"] == 0.10


def test_contract_fee_pct_below_statutory_cap_accepted(api):
    """PRD §3.2: "a contract whose `fee_pct` is greater than its `statutory_cap_pct` is
    rejected with `ERR_FEE_EXCEEDS_STATUTORY_CAP`, while equality is accepted."

    Design: Difficulty/boundary_precision_check/contract_fee_pct_equal_to_statutory_cap_accepted
    """
    adj = new_adjuster(api)
    cli = new_client(api)
    resp = api.create_contract(create_contract_payload(cli, adj, fee_pct=0.09, statutory_cap_pct=0.10), FIRM)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"
    assert data["fee_pct"] == 0.09


def test_contract_fee_pct_above_cap_rejected(api):
    """PRD §3.2: "a contract whose `fee_pct` is greater than its `statutory_cap_pct` is
    rejected with `ERR_FEE_EXCEEDS_STATUTORY_CAP`, while equality is accepted."

    Design: Corner/validations/contract_fee_pct_above_cap_rejected
    """
    adj = new_adjuster(api)
    cli = new_client(api)
    resp = api.create_contract(create_contract_payload(cli, adj, fee_pct=0.11, statutory_cap_pct=0.10), FIRM)
    validate_error(resp, ApiErrorId.ERR_FEE_EXCEEDS_STATUTORY_CAP.value)


# ------------------------------------------------------ contract transitions (corner)
def test_contract_activate_twice_is_invalid_transition(api):
    """PRD §3.2: "Activation, performed by a `FirmPrincipal`, moves the contract from
    `SIGNED` to `ACTIVE` but only if the retained adjuster holds a currently-valid `ACTIVE`
    license in the contract's `loss_state_code` at the current clock instant; otherwise it
    is rejected with `ERR_LICENSE_NOT_VALID`."

    Design: Corner/state_machines/contract_activate_twice_is_invalid_transition
    """
    ctx = setup_active_contract(api)  # contract already ACTIVE
    resp = api.activate_contract(ctx["con"], FIRM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ------------------------------------------------------- rescission window (corner)
def test_rescind_after_window_closed_rejected(api):
    """PRD §3.2: "A cooling-off rescission may be initiated by either the `Client` or a
    `FirmPrincipal` from either the `SIGNED` or the `ACTIVE` state, provided the current
    clock instant is on or before `rescission_deadline_at`; a later attempt is rejected
    with `ERR_RESCISSION_WINDOW_CLOSED`."

    Design: Corner/validations/rescind_after_window_closed_rejected
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    ctx = setup_active_contract(api)  # signed at 2026-07-01, deadline 2026-07-04
    set_clock(api, "2026-07-10T00:00:00Z")  # past deadline
    resp = api.rescind_contract(ctx["con"], make_client_headers(ctx["cli"]))
    validate_error(resp, ApiErrorId.ERR_RESCISSION_WINDOW_CLOSED.value)


# ------------------------------------------- license validity-interval overlap (difficulty)
def test_license_validity_interval_overlap_rejected(api):
    """PRD §2.9: "When a new license is issued, its validity interval must not overlap the
    interval of any existing non-`REVOKED` license held by the same adjuster in the same
    state; an overlap is rejected with `ERR_LICENSE_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/license_validity_interval_overlap_rejected
    """
    adj = new_adjuster(api)
    new_license(api, adj, license_number="TX-1",
                effective_date="2026-01-01T00:00:00Z", expiry_date="2027-01-01T00:00:00Z")
    resp = api.create_license(
        create_license_payload(adj, license_number="TX-2",
                               effective_date="2026-06-01T00:00:00Z",
                               expiry_date="2026-12-01T00:00:00Z"),
        FIRM,
    )
    validate_error(resp, ApiErrorId.ERR_LICENSE_PERIOD_OVERLAP.value)


def test_license_validity_interval_identical_overlap_rejected(api):
    """PRD §3.1: "issuance is rejected with `ERR_LICENSE_PERIOD_OVERLAP` when the new
    interval overlaps any existing non-`REVOKED` license for that `(adjuster_id,
    state_code)` pair."

    Design: Difficulty/resource_temporal_overlap/license_validity_interval_overlap_rejected
    """
    adj = new_adjuster(api)
    new_license(api, adj, license_number="TX-1",
                effective_date="2026-01-01T00:00:00Z", expiry_date="2027-01-01T00:00:00Z")
    resp = api.create_license(
        create_license_payload(adj, license_number="TX-2",
                               effective_date="2026-01-01T00:00:00Z",
                               expiry_date="2027-01-01T00:00:00Z"),
        FIRM,
    )
    validate_error(resp, ApiErrorId.ERR_LICENSE_PERIOD_OVERLAP.value)
