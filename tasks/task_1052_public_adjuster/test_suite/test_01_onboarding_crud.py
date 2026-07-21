"""Onboarding, CRUD basics, and simple lifecycle cycles.

Corner-design (queue B) translations for entities, one calculation, and two
valid-transition cycles.
"""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    create_adjuster_payload, create_client_payload, create_policy_payload,
    create_contract_payload, create_claim_payload,
    make_public_adjuster_headers,
    assert_adjuster, assert_policy,
    NON_EXISTENT_UUID,
)
from test_helpers.fixtures import (
    setup_active_contract, new_adjuster, new_license, new_client, new_policy,
    new_contract, new_draft_claim,
)

FIRM = TEST_USERS["firm_principal_headers"]
CARRIER = TEST_USERS["carrier_headers"]


def test_create_adjuster_returns_201_active(api):
    """PRD §3.1: "A `FirmPrincipal` onboards a public adjuster by creating an `Adjuster`
    with a `full_name`, a `firm_name`, and an `email`. Adjusters are always in `ACTIVE`
    `status` in this system."

    Design: Corner/entities/adjuster_create_returns_201_with_active_status
    """
    resp = api.create_adjuster(create_adjuster_payload(full_name="Ada PA"), FIRM)
    data = validate_success(resp, expected_status=201)
    assert_adjuster(data)
    assert data["status"] == "ACTIVE"
    assert data["full_name"] == "Ada PA"


def test_get_nonexistent_claim_returns_not_found(api):
    """PRD §2.7: "The first identifier that does not correspond to an existing resource
    causes the request to be rejected with `ERR_NOT_FOUND`; body-referenced resources are
    likewise checked for existence before state or business validation proceeds."

    Design: Corner/entities/claim_get_nonexistent_returns_not_found
    """
    resp = api.get_claim(NON_EXISTENT_UUID, FIRM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_policy_create_initializes_remaining_limit_to_coverage(api):
    """PRD §3.1: "A new policy starts `ACTIVE` with `committed_cents` at 0 and
    `remaining_limit_cents` equal to the full `coverage_limit_cents`; its
    `forward_exposure_cents` likewise starts at 0."

    Design: Corner/entities/policy_create_initializes_remaining_limit_to_coverage
    """
    cli = new_client(api)
    resp = api.create_policy(create_policy_payload(cli, coverage_limit_cents=100_000_000), FIRM)
    data = validate_success(resp, expected_status=201)
    assert data["committed_cents"] == 0
    assert data["remaining_limit_cents"] == 100_000_000
    assert data["forward_exposure_cents"] == 0
    assert_policy(data)


def test_contract_create_defaults_prior_advance_to_zero(api):
    """PRD §3.2: "the contingency `fee_pct` expressed as a fraction of recovery, the
    governing `statutory_cap_pct`, and optionally a `prior_advance_cents` figure recording
    cash already advanced to the client (defaulting to 0 when omitted)."

    Design: Corner/entities/contract_create_defaults_prior_advance_to_zero
    """
    adj = new_adjuster(api)
    cli = new_client(api)
    resp = api.create_contract(create_contract_payload(cli, adj), FIRM)  # no prior_advance_cents
    data = validate_success(resp, expected_status=201)
    assert data["prior_advance_cents"] == 0


def test_claim_create_missing_peril_type_rejected(api):
    """PRD §2.10: "and (12) body well-formedness — required fields present, amounts
    non-negative, enums valid (`ERR_VALIDATION`)."

    Design: Corner/entities/claim_create_missing_peril_type_rejected
    """
    adj = new_adjuster(api)
    lic = new_license(api, adj)
    cli = new_client(api)
    pol = new_policy(api, cli)
    con = new_contract(api, cli, adj)
    payload = create_claim_payload(pol, con)
    payload.pop("peril_type")
    resp = api.create_claim(payload, make_public_adjuster_headers(adj))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_pa_acv_estimate_computed_on_file(api):
    """PRD §3.3: "the system computes the actual-cash-value estimate `pa_acv_estimate_cents`
    as the replacement-cost estimate multiplied by one minus the depreciation fraction,
    rounded half up to whole cents; because the claim is now open, the policy's
    `forward_exposure_cents` is recomputed to include this claim's ACV estimate."

    Design: Corner/calculations/pa_acv_estimate_computed_on_file
    """
    ctx = setup_active_contract(api)
    clm = new_draft_claim(api, ctx["pol"], ctx["con"], ctx["adj"],
                          pa_rcv_estimate_cents=10_000_000, depreciation_pct=0.20)
    resp = api.file_claim(clm, make_public_adjuster_headers(ctx["adj"]))
    data = validate_success(resp)
    # round_half_up(10000000 * (1 - 0.20)) = 8000000
    assert data["pa_acv_estimate_cents"] == 8_000_000


def test_license_suspend_then_reinstate_cycle(api):
    """PRD §3.1: "suspending an active license drives its `status` to `SUSPENDED`,
    reinstating a suspended one returns it to `ACTIVE`, and revoking from either `ACTIVE`
    or `SUSPENDED` drives it to the terminal `REVOKED`."

    Design: Corner/state_machines/license_suspend_then_reinstate_cycle
    """
    adj = new_adjuster(api)
    lic = new_license(api, adj)["id"]
    suspended = validate_success(api.suspend_license(lic, FIRM))
    assert suspended["status"] == "SUSPENDED"
    reinstated = validate_success(api.reinstate_license(lic, FIRM))
    assert reinstated["status"] == "ACTIVE"


def test_disbursement_hold_then_resume_cycle(api):
    """PRD §3.7: "A pending disbursement may instead be held (moving `PENDING` to `HELD`)
    and later resumed (moving `HELD` back to `PENDING`) by a `PublicAdjuster` or
    `FirmPrincipal`; hold and resume may cycle."

    Design: Corner/state_machines/disbursement_hold_then_resume_cycle
    """
    from test_helpers.fixtures import setup_paid_claim_with_disbursement
    ctx = setup_paid_claim_with_disbursement(api)
    held = validate_success(api.hold_disbursement(ctx["dis"], FIRM))
    assert held["status"] == "HELD"
    resumed = validate_success(api.resume_disbursement(ctx["dis"], FIRM))
    assert resumed["status"] == "PENDING"
