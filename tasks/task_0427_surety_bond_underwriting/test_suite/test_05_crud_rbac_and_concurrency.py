"""CRUD creation, credit-tier derivation, input validation, listing/pagination, RBAC, and
optimistic-concurrency on renewal.

Covers the corner queue (B) sections: entities, endpoints, rbac, and the
cross_cutting_complexity_layers OCC instances.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    NON_EXISTENT_UUID,
    create_program_payload,
    create_principal_payload,
    create_bond_payload,
    create_rider_payload,
    create_claim_payload,
    setup_approved_application,
    setup_active_bond,
    setup_referred_application,
    create_principal_with_indemnity,
    create_program,
    UW,
    SR,
    CE,
)


# ─── Corner (B) entities: creation, computed defaults, not-found, validation ───

def test_create_program_returns_201_with_computed_defaults(api):
    """PRD §3.1: "The program opens in `OPEN` status with `aggregate_committed_cents` at
    zero".
    PRD §2.6: "The available figure, `aggregate_available_cents`, is the program's
    `aggregate_limit_cents` minus its `aggregate_committed_cents`."
    PRD §2.4: "The `version` is an integer that begins at its initial value when the resource
    is created".

    Design: Corner/entities/create_program_returns_201_with_computed_defaults
    """
    res = api.create_program(
        create_program_payload(name="PC1", single_limit_cents=10_000_000,
                               aggregate_limit_cents=50_000_000,
                               referral_threshold_cents=15_000_000,
                               loss_alert_threshold_cents=50_000_000),
        SR,
    )
    prog = validate_success(res, 201)
    assert prog["status"] == "OPEN"
    assert prog["aggregate_committed_cents"] == 0
    assert prog["aggregate_available_cents"] == 50_000_000
    assert prog["version"] == 1


def test_get_program_not_found_returns_404(api):
    """PRD §2.11: "rejects the request with `ERR_NOT_FOUND` at the first reference that does
    not resolve to an existing resource."

    Design: Corner/entities/get_program_not_found_returns_404
    """
    res = api.get_program(NON_EXISTENT_UUID, UW)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_principal_missing_credit_score_invalid_request(api):
    """PRD §2.12: "Request well-formedness is fourth and applies to every write endpoint:
    required body fields must be present and correctly typed ... with any violation yielding
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_principal_missing_credit_score_returns_invalid_request
    """
    res = api.create_principal({"legal_name": "NoScore"}, UW)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_principal_credit_score_out_of_range_invalid_request(api):
    """PRD §2.12: "integer fields must fall within their declared ranges — for instance, a
    principal's credit score must lie within 300 to 850 inclusive — with any violation
    yielding `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_principal_credit_score_out_of_range_returns_invalid_request
    """
    res = api.create_principal(
        {"legal_name": "BadScore", "credit_score": 900, "working_capital_cents": 0}, UW
    )
    validate_error(res, "ERR_INVALID_REQUEST")


def test_credit_tier_preferred_at_720_boundary(api):
    """PRD §3.2: "A principal is rated `PREFERRED` when its credit score is at least 720 and
    its working capital is at least zero".

    Design: Corner/entities/principal_credit_tier_preferred_boundary_inclusive
    """
    prin = validate_success(
        api.create_principal(
            create_principal_payload(legal_name="Boundary720", credit_score=720,
                                     working_capital_cents=0), UW
        ),
        201,
    )
    assert prin["credit_tier"] == "PREFERRED"


def test_credit_tier_standard_just_below_preferred(api):
    """PRD §3.2: "failing that, it is rated `STANDARD` when its credit score is at least 620
    and its working capital is at least zero".

    Design: Corner/entities/principal_credit_tier_standard_just_below_preferred
    """
    prin = validate_success(
        api.create_principal(
            create_principal_payload(legal_name="Boundary719", credit_score=719,
                                     working_capital_cents=0), UW
        ),
        201,
    )
    assert prin["credit_tier"] == "STANDARD"


def test_credit_tier_negative_working_capital_forces_substandard(api):
    """PRD §3.2: "in every remaining case — any principal whose working capital is negative,
    or whose score is below 620 — it is rated `SUBSTANDARD`."

    Design: Corner/entities/principal_negative_working_capital_forces_substandard
    """
    prin = validate_success(
        api.create_principal(
            create_principal_payload(legal_name="NegWC", credit_score=800,
                                     working_capital_cents=-1), UW
        ),
        201,
    )
    assert prin["credit_tier"] == "SUBSTANDARD"


def test_list_programs_pagination_envelope(api):
    """PRD §2.3: "Each list response carries its pagination state in the `meta` object of the
    envelope through the fields `limit`, `offset`, `total_count`, and `has_more`, where
    `total_count` is the number of matching resources across all pages and `has_more`
    indicates whether further pages remain beyond the current one."

    Design: Corner/entities/list_programs_pagination_envelope
    """
    create_program(name="L1", single_limit_cents=10_000_000,
                   referral_threshold_cents=15_000_000)
    create_program(name="L2", single_limit_cents=10_000_000,
                   referral_threshold_cents=15_000_000)
    data, meta = validate_paginated(api.list_programs(UW, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ─── Corner (B) endpoints ──────────────────────────────────────────────────────

def test_bind_returns_issued_bond_with_zero_earned_and_full_net_retained(api):
    """PRD §3.4: "On success the application moves to `BOUND` and a new `Bond` is created in
    `ISSUED` status."
    PRD §3.4: "A freshly bound bond has `earned_premium_cents` of zero, `ceded_penal_sum_cents`
    of zero, and therefore `net_retained_cents` equal to its full penal sum".
    PRD §3.4: "the program's `aggregate_committed_cents` rises by the new bond's
    `net_retained_cents`".

    Design: Corner/endpoints/bind_returns_issued_bond_with_zero_earned_and_full_net_retained
    """
    prog = create_program(name="E2")
    prin, _ = create_principal_with_indemnity(
        legal_name="E2Prin", credit_score=700, working_capital_cents=1_000_000
    )
    _, _, app = setup_approved_application(
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    res = api.create_bond(create_bond_payload(app["id"]), UW)
    bond = validate_success(res, 201)
    assert bond["status"] == "ISSUED"
    assert bond["earned_premium_cents"] == 0
    assert bond["ceded_penal_sum_cents"] == 0
    assert bond["net_retained_cents"] == 5_000_000
    app_after = validate_success(api.get_application(app["id"], UW), 200)
    assert app_after["status"] == "BOUND"
    prog_after = validate_success(api.get_program(prog["id"], UW), 200)
    assert prog_after["aggregate_committed_cents"] == 5_000_000


def test_list_claims_filtered_by_bond_id(api):
    """PRD §4 (Endpoint Definitions): "List claims, filterable by bond".
    PRD §2.3: "where `total_count` is the number of matching resources across all pages".

    Design: Corner/endpoints/list_claims_filtered_by_bond_id
    """
    prog = create_program(name="E1")
    prin, _ = create_principal_with_indemnity(
        legal_name="E1Prin", credit_score=700, working_capital_cents=1_000_000
    )
    _, _, _, bond = setup_active_bond(
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    get_success_data(
        api.create_claim(create_claim_payload(bond["id"], claimant_name="E1 A",
                                              demand_cents=100_000, reserve_cents=100_000), CE)
    )
    get_success_data(
        api.create_claim(create_claim_payload(bond["id"], claimant_name="E1 B",
                                              demand_cents=200_000, reserve_cents=200_000), CE)
    )
    data, meta = validate_paginated(api.list_claims(CE, params={"bond_id": bond["id"]}))
    assert meta["total_count"] == 2
    for claim in data:
        assert claim["bond_id"] == bond["id"]


# ─── Corner (B) rbac ───────────────────────────────────────────────────────────

def test_underwriter_cannot_create_program(api):
    """PRD §2.1: "and in addition owns the operations reserved to the senior tier: creating
    and suspending programs, creating and closing treaties, and approving applications that
    have been referred."
    PRD §2.1: "When the headers are well-formed but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/underwriter_cannot_create_program
    """
    res = api.create_program(
        create_program_payload(name="RB1", single_limit_cents=10_000_000,
                               referral_threshold_cents=15_000_000),
        UW,
    )
    validate_error(res, "ERR_FORBIDDEN")


def test_underwriter_cannot_approve_referred_application(api):
    """PRD §3.3: "Approval of a `REFERRED` application is reserved to a `SeniorUnderwriter` — a
    front-line underwriter cannot approve a referred file, by segregation of duties".

    Design: Corner/rbac/underwriter_cannot_approve_referred_application
    """
    prog = create_program(name="RB2", referral_threshold_cents=10_000_000,
                          single_limit_cents=20_000_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="RB2Prin", credit_score=760, working_capital_cents=5_000_000
    )
    _, _, app = setup_referred_application(
        program=prog, principal=prin,
        app_overrides={"bond_type": "BID", "requested_penal_sum_cents": 12_000_000,
                       "term_months": 12},
    )
    assert app["status"] == "REFERRED"
    res = api.approve_application(app["id"], UW)
    validate_error(res, "ERR_FORBIDDEN")
    after = validate_success(api.get_application(app["id"], UW), 200)
    assert after["status"] == "REFERRED"


def test_claims_examiner_cannot_bind_bond(api):
    """PRD §2.1: "A `ClaimsExaminer` handles claims exclusively — filing, investigating, and
    settling them — and may read bonds, programs, and claims for context, but may never
    underwrite, bind, or approve."

    Design: Corner/rbac/claims_examiner_cannot_bind_bond
    """
    prog = create_program(name="RB3")
    prin, _ = create_principal_with_indemnity(
        legal_name="RB3Prin", credit_score=700, working_capital_cents=1_000_000
    )
    _, _, app = setup_approved_application(
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    res = api.create_bond(create_bond_payload(app["id"]), CE)
    validate_error(res, "ERR_FORBIDDEN")


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "A request missing the role header, or carrying a role the system does not
    recognize, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    res = api.list_programs({})
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─── Corner (B) cross_cutting: OCC on renewal ──────────────────────────────────

def test_renew_with_correct_version_succeeds_and_supersedes(api):
    """PRD §3.5: "On success the system creates a successor `Bond` in `ISSUED` status copying
    the predecessor's penal sum, rate, and term; sets the predecessor's `superseded_by_bond_id`
    to the successor's identifier; moves the predecessor to `RENEWED`; and shifts program
    exposure from predecessor to successor by releasing the predecessor's `net_retained_cents`
    from `aggregate_committed_cents` and committing the successor's `penal_sum_cents`."

    Design: Corner/cross_cutting_complexity_layers/occ_renew_correct_version_succeeds_and_supersedes
    """
    prog = create_program(name="CC1")
    prin, _ = create_principal_with_indemnity(
        legal_name="CC1Prin", credit_score=700, working_capital_cents=1_000_000
    )
    _, _, _, bond = setup_active_bond(
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    res = api.renew_bond(bond["id"], {"expected_bond_version": bond["version"]}, UW)
    renewed = validate_success(res, 200)
    assert renewed["status"] == "RENEWED"
    assert renewed["superseded_by_bond_id"]
    prog_after = validate_success(api.get_program(prog["id"], UW), 200)
    # Predecessor released, successor committed; no cessions -> still 5,000,000.
    assert prog_after["aggregate_committed_cents"] == 5_000_000


def test_renew_with_stale_version_after_rider_bump_returns_412(api):
    """PRD §2.5: "If `expected_bond_version` does not equal the bond's current `version` at the
    moment the server processes the request, the renewal is rejected with `ERR_STALE_VERSION`
    and HTTP status 412. This guards against the case where an intervening rider application or
    cession recapture has already advanced the bond's `version` since the client last read it".

    Design: Corner/cross_cutting_complexity_layers/occ_renew_stale_version_after_rider_bump_returns_412
    """
    prog = create_program(name="CC3")
    prin, _ = create_principal_with_indemnity(
        legal_name="CC3Prin", credit_score=700, working_capital_cents=1_000_000
    )
    _, _, _, bond = setup_active_bond(
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    stale_version = bond["version"]
    # Apply a DECREASE rider, which mutates and bumps the bond's version.
    rider = get_success_data(
        api.create_rider(
            create_rider_payload(bond["id"], rider_type="DECREASE",
                                 penal_sum_delta_cents=-1_000_000), UW
        )
    )
    get_success_data(api.apply_rider(rider["id"], UW))
    res = api.renew_bond(bond["id"], {"expected_bond_version": stale_version}, UW)
    validate_error(res, "ERR_STALE_VERSION")
    after = validate_success(api.get_bond(bond["id"], UW), 200)
    assert after["status"] == "ACTIVE"
