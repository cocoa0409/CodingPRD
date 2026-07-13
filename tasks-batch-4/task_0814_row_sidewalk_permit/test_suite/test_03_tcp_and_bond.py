"""Traffic-control-plan approval, restoration-bond posting, the optimistic
concurrency guard, and the issuance safety/fiscal gates."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_applicant_headers,
    create_bond_payload,
    fixtures,
)

ADMIN = TEST_USERS["admin_headers"]
REVIEWER_1 = TEST_USERS["reviewer_headers"]
REVIEWER_2 = TEST_USERS["reviewer_2_headers"]


def test_double_approving_tcp_returns_invalid_state(api):
    """PRD §3.3: "Deciding a plan that is not `SUBMITTED` is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/tcp_double_approve_idempotency
    """
    ctx = fixtures.setup_approved_permit(api)
    tcp = fixtures.attach_and_approve_tcp(api, ctx["permit_id"], ctx["app_id"], approve=True)
    resp = api.decide_traffic_control_plan(tcp["id"], {"outcome": "APPROVED"}, REVIEWER_1)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_tcp_approval_requires_flaggers_when_flagged(api):
    """PRD §3.3: "if the plan's `requires_flaggers` is true, its `flagger_count`
    must be at least 1, or the approval is rejected with `ERR_FLAGGERS_REQUIRED`."

    Design: Corner/validations/flaggers_required_violation_to_error
    """
    ctx = fixtures.setup_approved_permit(api)
    tcp = fixtures.attach_and_approve_tcp(
        api, ctx["permit_id"], ctx["app_id"],
        requires_flaggers=True, flagger_count=0, approve=False,
    )
    resp = api.decide_traffic_control_plan(tcp["id"], {"outcome": "APPROVED"}, REVIEWER_1)
    validate_error(resp, ApiErrorId.ERR_FLAGGERS_REQUIRED.value)


def test_bond_required_uses_fixed_floor(api):
    """PRD §3.3: "The system computes the minimum `required_cents` as the larger
    of a fixed floor of 50000 cents and twice the permit's estimated occupancy
    fee — that is, the estimated occupancy fee (the estimated variant defined in
    §3.4, using the permit's requested window) multiplied by 2, compared against
    50000 cents, taking whichever is greater."

    Design: Corner/calculations/bond_required_floor_applied
    """
    ctx = fixtures.setup_approved_permit(
        api, zone_class="RESIDENTIAL", obstruction_type="LANE",
        requested_start_date="2026-04-01", requested_end_date="2026-04-05",
        block_label="Elm 4", last_repaved_date="2020-01-01",
    )
    bond = fixtures.post_bond(api, ctx["permit_id"], ctx["app_id"], 50000, ctx["approved_version"])
    assert bond["required_cents"] == 50000


def test_bond_below_required_rejected(api):
    """PRD §3.3: "If `posted_cents` is less than `required_cents`, the post is
    rejected with `ERR_BOND_INSUFFICIENT`."

    Design: Corner/validations/bond_insufficient_violation_to_error
    """
    ctx = fixtures.setup_approved_permit(api)  # COMMERCIAL LANE, est 40000, required 80000
    resp = api.post_bond(
        ctx["permit_id"],
        create_bond_payload(40000, ctx["approved_version"]),
        make_applicant_headers(ctx["app_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BOND_INSUFFICIENT.value)


def test_approver_cannot_issue_segregation_of_duties(api):
    """PRD §3.4: "the issuing `X-User-ID` must differ from the permit's
    `assigned_reviewer_user_id`, so the reviewer who approved a permit may not
    issue it; a match is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/segregation_of_duties_on_issue_denied
    """
    ctx = fixtures.setup_approved_permit(api)
    fixtures.attach_and_approve_tcp(api, ctx["permit_id"], ctx["app_id"], approve=True)
    fixtures.post_bond(api, ctx["permit_id"], ctx["app_id"], 80000, ctx["approved_version"])
    # reviewer-1 approved this permit; issuing as reviewer-1 must be refused.
    resp = api.issue_permit(ctx["permit_id"], REVIEWER_1)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_stale_permit_version_on_bond_repost_rejected(api):
    """PRD §2.6: "If `expected_permit_version` does not equal the permit's
    current `version`, the request is rejected with `ERR_STALE_PERMIT_VERSION`
    (HTTP 412)."
    PRD §2.6: "a successful post advances the permit's `version` by one; a
    subsequent post that still carries the older value is therefore refused as
    stale, ensuring the client cannot overwrite a bond state it has not observed."

    Design: Corner/cross_cutting/occ_stale_permit_version_on_bond_repost
    """
    ctx = fixtures.setup_approved_permit(api)
    stale_version = ctx["approved_version"]
    # First post succeeds and advances the permit's version.
    fixtures.post_bond(api, ctx["permit_id"], ctx["app_id"], 80000, stale_version)
    # Second post still carrying the pre-first-post version is stale.
    resp = api.post_bond(
        ctx["permit_id"],
        create_bond_payload(90000, stale_version),
        make_applicant_headers(ctx["app_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_PERMIT_VERSION.value)


def test_tcp_not_approved_gate_precedes_bond_on_issue(api):
    """PRD §3.4: "The permit's traffic-control plan must exist and be `APPROVED`,
    or issuance is rejected with `ERR_TCP_NOT_APPROVED`."
    PRD §2.9: "Business rules follow in this order: safety gates for issuance and
    plan approval (`ERR_TCP_NOT_APPROVED`, `ERR_FLAGGERS_REQUIRED`); referential
    and clearance conflicts for new occupancy (`ERR_CLOSURE_CONFLICT`,
    `ERR_SIDEWALK_BUFFER_CONFLICT`, `ERR_ADA_CLEARANCE`); the utility-cut
    moratorium (`ERR_UTILITY_CUT_MORATORIUM`); the outstanding-occupancy gate for
    close-out and bond release (`ERR_CLOSURES_OUTSTANDING`); and the fiscal
    sufficiency gate for the bond (`ERR_BOND_INSUFFICIENT`)."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_issue
    """
    ctx = fixtures.setup_approved_permit(api)
    # TCP attached but only SUBMITTED (not approved); no bond posted at all.
    fixtures.attach_and_approve_tcp(api, ctx["permit_id"], ctx["app_id"], approve=False)
    resp = api.issue_permit(ctx["permit_id"], REVIEWER_2)
    validate_error(resp, ApiErrorId.ERR_TCP_NOT_APPROVED.value)


def test_failed_issue_leaves_permit_approved(api):
    """PRD §3.4: "The permit's traffic-control plan must exist and be `APPROVED`,
    or issuance is rejected with `ERR_TCP_NOT_APPROVED`."
    PRD §3.4: "A `PermitReviewer` issues a permit that is `APPROVED`, carrying it
    to `ISSUED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_issue
    """
    ctx = fixtures.setup_approved_permit(api)
    fixtures.attach_and_approve_tcp(api, ctx["permit_id"], ctx["app_id"], approve=False)
    resp = api.issue_permit(ctx["permit_id"], REVIEWER_2)
    validate_error(resp, ApiErrorId.ERR_TCP_NOT_APPROVED.value)
    permit = get_success_data(api.get_permit(ctx["permit_id"], REVIEWER_2))
    assert permit["status"] == "APPROVED"
