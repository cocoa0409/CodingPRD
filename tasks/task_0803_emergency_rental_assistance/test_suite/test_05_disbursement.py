"""Disbursement creation gates: state, funding, award ceiling, fraud hold, and OCC.

Translates queue-A cross_entity_state_dependency (disbursement side) and
transitive_cascade (pool-exhaust) instances, plus queue-B disbursement corner
instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_caseworker_headers,
    disbursement_payload,
    build_application, build_approved_application,
    create_disbursement, create_cleared_disbursement,
    recapture_case_payload,
)

ADMIN = TEST_USERS["program_admin_headers"]
CW = TEST_USERS["caseworker_headers"]
FRAUD = TEST_USERS["fraud_headers"]


# =====================================================================
# Rule 7 — cross_entity_state_dependency (disbursement gated by APPROVED)
# =====================================================================

def test_disbursement_create_on_under_review_application_rejected(api):
    """PRD §3.7: "For the ordering of gates at creation: the application must be in
    `APPROVED` state (else `ERR_INVALID_STATE`); no fraud hold may be active (§3.9, else
    `ERR_FRAUD_HOLD`); the reservation must fit within remaining funds (else
    `ERR_FUNDING_EXHAUSTED`); separation of duties must hold
    (`ERR_SEGREGATION_OF_DUTIES`); the award ceiling must hold (`ERR_AWARD_EXCEEDED`);
    and the concurrency version must match (`ERR_STALE_APPLICATION_VERSION`)."

    Design: Difficulty/cross_entity_state_dependency/disbursement_create_gated_by_application_approved
    """
    ctx = build_application(
        api, review=True, income_limits={"2": 566667},
        income_sources=(("WAGES", 400000),),
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-04-30",
        requested_prospective_months=2, ledger_lines=[],
    )
    resp = api.create_disbursement(
        ctx["aid"],
        disbursement_payload(100000, 1, "PROSPECTIVE", ctx["version"]),
        make_caseworker_headers("cw-issuer-14"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_disbursement_create_on_under_review_leaves_no_reservation(api):
    """PRD §3.7: "When it succeeds, the create reserves funds
    (`funding_pool_remaining_cents` is reduced by `amount_cents`, driving the program to
    `EXHAUSTED` if it reaches zero), reserves months (the tenant's `months_used` is
    increased by `months_covered`), records `issued_by_cw_id`, increments the
    application's `version` by one, and sets the disbursement `status` to `PENDING`."

    Design: Difficulty/cross_entity_state_dependency/disbursement_create_gated_by_application_approved
    """
    ctx = build_application(
        api, review=True, income_limits={"2": 566667},
        income_sources=(("WAGES", 400000),),
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-04-30",
        requested_prospective_months=2, ledger_lines=[],
    )
    api.create_disbursement(
        ctx["aid"], disbursement_payload(100000, 1, "PROSPECTIVE", ctx["version"]),
        make_caseworker_headers("cw-issuer-14b"))
    tenant = get_success_data(api.get_tenant(ctx["tid"], ADMIN))
    assert tenant["months_used"] == 0


# =====================================================================
# Rule 4 — transitive_cascade (disbursement create exhausts the pool)
# =====================================================================

def test_disbursement_create_zeroes_pool_and_exhausts_program(api):
    """PRD §2.7: "A program's `status` is a computed reflection of the remaining pool:
    it is `OPEN` while funds remain and becomes `EXHAUSTED` the instant
    `funding_pool_remaining_cents` reaches 0."

    Design: Difficulty/transitive_cascade/disbursement_create_pool_exhaust_depth2
    """
    ctx = build_approved_application(api, funding_pool_total_cents=1000000, approver_id="cw-approver-8")
    aid, pid, av = ctx["aid"], ctx["pid"], ctx["version"]
    create_disbursement(api, aid, amount_cents=1000000, months_covered=5,
                        coverage_kind="COMBINED", version=av, issuer_id="cw-issuer-8")
    program = get_success_data(api.get_program(pid, ADMIN))
    assert program["funding_pool_remaining_cents"] == 0
    assert program["status"] == "EXHAUSTED"


def test_disbursement_create_returns_pending_after_reservation(api):
    """PRD §3.7: "When it succeeds, the create reserves funds
    (`funding_pool_remaining_cents` is reduced by `amount_cents`, driving the program to
    `EXHAUSTED` if it reaches zero), reserves months (the tenant's `months_used` is
    increased by `months_covered`), records `issued_by_cw_id`, increments the
    application's `version` by one, and sets the disbursement `status` to `PENDING`."

    Design: Difficulty/transitive_cascade/disbursement_create_pool_exhaust_depth2
    """
    ctx = build_approved_application(api, funding_pool_total_cents=1000000, approver_id="cw-approver-8b")
    disb = create_disbursement(api, ctx["aid"], amount_cents=1000000, months_covered=5,
                               coverage_kind="COMBINED", version=ctx["version"], issuer_id="cw-issuer-8b")
    assert disb["status"] == "PENDING"


# =====================================================================
# Queue B — disbursement corner instances
# =====================================================================

def test_disbursement_amount_exceeds_award_rejected(api):
    """PRD §3.7: "Creation also enforces the award ceiling: the sum of `amount_cents`
    across all reserving disbursements (those in `PENDING`, `SENT`, or `CLEARED`)
    including this one must not exceed the pinned `total_award_cents`, and likewise the
    cumulative `months_covered` must not exceed the remaining awarded months; a breach is
    rejected with `ERR_AWARD_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/disbursement_amount_exceeds_award_returns_error
    """
    ctx = build_approved_application(api, approver_id="cw-approver-ax")
    resp = api.create_disbursement(
        ctx["aid"], disbursement_payload(1000001, 5, "COMBINED", ctx["version"]),
        make_caseworker_headers("cw-issuer-ax"))
    validate_error(resp, ApiErrorId.ERR_AWARD_EXCEEDED.value, expected_status=422)


def test_disbursement_create_over_remaining_funds_rejected(api):
    """PRD §2.7: "Any operation that would reserve more money than remains is rejected
    with `ERR_FUNDING_EXHAUSTED` (HTTP 402); fiscal admissibility is a gate, never a
    silent clamp on the amount."

    Design: Corner/validations/error_funding_exhausted_on_disbursement_create
    """
    ctx = build_approved_application(api, funding_pool_total_cents=1000000, approver_id="cw-approver-fe")
    aid, pid, av = ctx["aid"], ctx["pid"], ctx["version"]
    # Cut the pool below the award so a full disbursement no longer fits.
    get_success_data(api.update_program_funding(pid, {"funding_pool_total_cents": 500000}, ADMIN))
    resp = api.create_disbursement(
        aid, disbursement_payload(1000000, 5, "COMBINED", av),
        make_caseworker_headers("cw-issuer-fe"))
    validate_error(resp, ApiErrorId.ERR_FUNDING_EXHAUSTED.value, expected_status=402)


def test_fraud_hold_blocks_new_disbursement(api):
    """PRD §3.9: "While any recapture case for an application is in `OPEN` or
    `SUBSTANTIATED` status, three operations are blocked and rejected with
    `ERR_FRAUD_HOLD` (HTTP 409): creating a disbursement, sending a disbursement, and
    retrying a failed disbursement."

    Design: Corner/validations/fraud_hold_blocks_new_disbursement
    """
    ctx = build_approved_application(api, approver_id="cw-approver-fh")
    aid, av = ctx["aid"], ctx["version"]
    did = create_cleared_disbursement(api, aid, amount_cents=600000, months_covered=3,
                                      coverage_kind="ARREARS", version=av,
                                      issuer_id="cw-issuer-fh", payment_reference="ACH-FH")
    get_success_data(api.create_recapture_case(recapture_case_payload(aid, did, "OTHER"), FRAUD))
    av2 = get_success_data(api.get_application(aid, CW))["version"]

    resp = api.create_disbursement(
        aid, disbursement_payload(400000, 2, "PROSPECTIVE", av2),
        make_caseworker_headers("cw-issuer-fh2"))
    validate_error(resp, ApiErrorId.ERR_FRAUD_HOLD.value, expected_status=409)


def test_stale_application_version_on_second_disbursement_rejected(api):
    """PRD §2.10: "Each disbursement creation reserves funds and months and increments
    the application's `version`; a request that presents an `expected_application_version`
    older than the application's current `version` has not observed a prior reservation
    and would over-reserve against the same pinned award. Such a request is rejected with
    `ERR_STALE_APPLICATION_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_application_version_on_disbursement_returns_412
    """
    ctx = build_approved_application(api, approver_id="cw-approver-oc")
    aid, av = ctx["aid"], ctx["version"]
    # First create succeeds and bumps the application version.
    create_disbursement(api, aid, amount_cents=400000, months_covered=2,
                        coverage_kind="ARREARS", version=av, issuer_id="cw-issuer-oc")
    # Second create still carries the stale (pre-reservation) version.
    resp = api.create_disbursement(
        aid, disbursement_payload(400000, 2, "PROSPECTIVE", av),
        make_caseworker_headers("cw-issuer-oc"))
    validate_error(resp, ApiErrorId.ERR_STALE_APPLICATION_VERSION.value, expected_status=412)
