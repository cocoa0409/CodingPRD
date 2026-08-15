"""Sail design lifecycle: revision loop, approval gates, OCC, and RBAC denials."""
from test_helpers import (
    ApiErrorId,
    assert_sail_design,
    create_boat,
    create_customer,
    create_frozen_sheet,
    create_measurement_sheet,
    create_sail_design,
    get_boat,
    get_sail_design,
    make_customer_headers,
    setup_approved_design,
    setup_boat_with_frozen_sheet,
    submit_design,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    TEST_USERS,
)

MGR = TEST_USERS["loft_manager_headers"]
SAIL = TEST_USERS["sailmaker_headers"]
MEAS = TEST_USERS["measurer_headers"]
RIG = TEST_USERS["rigger_headers"]


# ---------------------------------------------------------------------------
# Design revision cycle: DRAFT -> SUBMITTED -> REVISION_REQUESTED -> DRAFT
# ---------------------------------------------------------------------------

def test_revision_loop_returns_same_row_to_draft(api):
    """PRD §3.3: "requesting a revision on a `SUBMITTED` design — again restricted
    to the boat's owner — moves it to `REVISION_REQUESTED` and stores the payload's
    `rejection_reason` on the design. A `Sailmaker` then returns the design from
    `REVISION_REQUESTED` to `DRAFT` for editing; this is the same design row
    looping back, so its `revision_number` does not change"

    Design: Difficulty/non_linear_state_machine/sail_design_revision_loop_cycles_back_to_draft
    """
    ctx = setup_approved_design(submit_only=True, racing_class="J70", hull_length_m=9.0)
    boat_id = ctx["boat"]["id"]
    design = ctx["design"]
    assert design["design_status"] == "SUBMITTED"
    assert design["revision_number"] == 1

    revised = validate_success(
        api.request_design_revision(
            boat_id, design["id"], {"rejection_reason": "too heavy"},
            make_customer_headers(ctx["customer"]["id"]),
        )
    )
    assert revised["design_status"] == "REVISION_REQUESTED"
    assert revised["rejection_reason"] == "too heavy", (
        "request-revision must store the payload's rejection_reason"
    )

    redrafted = validate_success(api.redraft_sail_design(boat_id, design["id"], SAIL))
    assert redrafted["id"] == design["id"], "the loop must reuse the same design row"
    assert redrafted["design_status"] == "DRAFT", (
        f"redraft must return the design to DRAFT, got {redrafted['design_status']}"
    )
    assert redrafted["revision_number"] == 1, (
        f"the loop must not increment revision_number, got {redrafted['revision_number']}"
    )


def test_revision_loop_repeats_without_incrementing(api):
    """PRD §3.3: "this is the same design row looping back, so its
    `revision_number` does not change, and the row may cycle `DRAFT` → `SUBMITTED`
    → `REVISION_REQUESTED` → `DRAFT` repeatedly."

    Design: Difficulty/non_linear_state_machine/sail_design_revision_loop_cycles_back_to_draft
    """
    ctx = setup_approved_design(submit_only=True, racing_class="J70", hull_length_m=9.0)
    boat_id = ctx["boat"]["id"]
    design_id = ctx["design"]["id"]
    owner = make_customer_headers(ctx["customer"]["id"])

    for reason in ("too heavy", "still too heavy"):
        revised = validate_success(
            api.request_design_revision(boat_id, design_id, {"rejection_reason": reason}, owner)
        )
        assert revised["design_status"] == "REVISION_REQUESTED"
        assert revised["rejection_reason"] == reason
        back = validate_success(api.redraft_sail_design(boat_id, design_id, SAIL))
        assert back["design_status"] == "DRAFT"
        # After the loop the sailmaker resubmits so the cycle can repeat.
        if reason == "too heavy":
            resubmitted = validate_success(api.submit_sail_design(boat_id, design_id, SAIL))
            assert resubmitted["design_status"] == "SUBMITTED"

    final = get_sail_design(design_id)
    assert final["design_status"] == "DRAFT"
    assert final["revision_number"] == 1, (
        f"two cycles must leave revision_number at 1, got {final['revision_number']}"
    )


# ---------------------------------------------------------------------------
# Approval gates: state check runs before the credit check (PRD §3.3)
# ---------------------------------------------------------------------------

def test_approve_draft_design_reports_state_error_not_credit(api):
    """PRD §3.3: "The design-state check runs before the credit check, so an
    approval attempted on a design that is not `SUBMITTED` is rejected with
    `ERR_DESIGN_NOT_IN_REQUIRED_STATE` (HTTP 409) rather than any credit error"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_design_approve
    """
    ctx = setup_boat_with_frozen_sheet(credit_limit_cents=500000)
    boat_id = ctx["boat"]["id"]
    # RACE tier at 61.50 sqm projects 584250 cents — over the 500000 limit, so the
    # credit rule would also fail; the state error must win.
    design = create_sail_design(boat_id, ctx["sheet"]["id"], cloth_tier="RACE")

    resp = api.approve_sail_design(
        boat_id, design["id"], make_customer_headers(ctx["customer"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_DESIGN_NOT_IN_REQUIRED_STATE)

    after = get_sail_design(design["id"])
    assert after["design_status"] == "DRAFT", f"rejected approval must leave DRAFT, got {after['design_status']}"


def test_approve_submitted_design_over_credit_reports_fiscal_error(api):
    """PRD §3.3: "an approval that passes the state gate but would break the
    credit limit is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_design_approve
    """
    ctx = setup_boat_with_frozen_sheet(credit_limit_cents=500000)
    boat_id = ctx["boat"]["id"]
    design = create_sail_design(boat_id, ctx["sheet"]["id"], cloth_tier="RACE")
    submit_design(boat_id, design["id"])

    resp = api.approve_sail_design(
        boat_id, design["id"], make_customer_headers(ctx["customer"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)

    after = get_sail_design(design["id"])
    assert after["design_status"] == "SUBMITTED", (
        f"rejected approval must leave SUBMITTED, got {after['design_status']}"
    )


# ---------------------------------------------------------------------------
# Submission gate: pinned sheet must be FROZEN (PRD §3.3)
# ---------------------------------------------------------------------------

def test_submit_design_with_draft_sheet_rejected(api):
    """PRD §3.3: "the pinned measurement sheet must exist and be `FROZEN` at
    submission, and if it is missing or not frozen the submission is rejected with
    `ERR_MEASUREMENT_NOT_FROZEN` (HTTP 409)."

    Design: Corner/validations/design_submit_requires_frozen_sheet
    """
    customer = create_customer(full_name="C30")
    boat = create_boat(customer["id"], boat_name="B30", hull_length_m=9.0)
    sheet = create_measurement_sheet(boat["id"], i_height_m=10.0, j_base_m=3.0, p_main_m=12.0, e_main_m=4.0)
    design = create_sail_design(boat["id"], sheet["id"], cloth_tier="CRUISE")

    resp = api.submit_sail_design(boat["id"], design["id"], SAIL)
    validate_error(resp, ApiErrorId.ERR_MEASUREMENT_NOT_FROZEN)

    after = get_sail_design(design["id"])
    assert after["design_status"] == "DRAFT", f"rejected submit must leave DRAFT, got {after['design_status']}"


def test_credit_limit_exceeded_blocks_design_approval(api):
    """PRD §3.3: "the customer's `outstanding_balance_cents` plus the projected
    quote for the design must not exceed the customer's `credit_limit_cents`" and
    "an approval that passes the state gate but would break the credit limit is
    rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

    Design: Corner/validations/credit_limit_exceeded_blocks_design_approval
    """
    ctx = setup_approved_design(submit_only=True, credit_limit_cents=300000, cloth_tier="RACE")
    # Projected quote: 61.50 sqm * 9500 = 584250 > 300000 limit.
    resp = api.approve_sail_design(
        ctx["boat"]["id"], ctx["design"]["id"], make_customer_headers(ctx["customer"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)

    after = get_sail_design(ctx["design"]["id"])
    assert after["design_status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# Optimistic concurrency on design-revision creation (PRD §2.7)
# ---------------------------------------------------------------------------

def test_stale_boat_version_rejected_on_design_create(api):
    """PRD §2.7: "If that value does not equal the boat's current `version` —
    because another writer has advanced the boat record since the client last read
    it — the request is rejected with `ERR_STALE_BOAT_VERSION` (HTTP 412), and the
    client must re-read the boat before retrying."

    Design: Corner/errors/err_stale_boat_version_on_design_revision_create
    """
    customer = create_customer(full_name="C39")
    boat = create_boat(customer["id"], boat_name="B39", hull_length_m=9.0)
    stale_version = boat["version"]  # captured before any design write
    sheet = create_frozen_sheet(boat["id"], i_height_m=10.0, j_base_m=3.0, p_main_m=12.0, e_main_m=4.0)

    # First revision succeeds against a fresh read; it advances the boat version.
    create_sail_design(boat["id"], sheet["id"], cloth_tier="CRUISE")

    resp = api.create_sail_design(
        boat["id"],
        {
            "measurement_sheet_id": sheet["id"],
            "cloth_tier": "RACE",
            "reinforcement_level": 2,
            "option_codes": [],
            "expected_boat_version": stale_version,
        },
        SAIL,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_BOAT_VERSION)


def test_design_create_increments_boat_version(api):
    """PRD §2.7: "Both guarded creations, on success, increment the boat's
    `version` by one, so a successful write by one client stales every other
    client's captured version."

    Design: Corner/cross_cutting_layers/boat_version_increments_on_design_revision_create
    """
    customer = create_customer(full_name="C43")
    boat = create_boat(customer["id"], boat_name="B43", hull_length_m=9.0)
    sheet = create_frozen_sheet(boat["id"], i_height_m=10.0, j_base_m=3.0, p_main_m=12.0, e_main_m=4.0)

    before = get_boat(boat["id"])["version"]
    created = create_sail_design(boat["id"], sheet["id"], cloth_tier="CRUISE")
    assert_sail_design(created)
    after = get_boat(boat["id"])["version"]
    assert after - before == 1, (
        f"design create must increment boat version by exactly 1 (before={before}, after={after})"
    )


# ---------------------------------------------------------------------------
# RBAC denials
# ---------------------------------------------------------------------------

def test_rigger_cannot_create_sail_design(api):
    """PRD §2.1: "A request whose role is well-formed but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "POST | `/lofts/boats/{boatId}/sail-designs` | Create a new design
    revision pinned to a FROZEN sheet; OCC-guarded on Boat.version | Sailmaker" —
    the endpoint is Sailmaker-only.

    Design: Corner/roles/rigger_cannot_create_sail_design
    """
    customer = create_customer(full_name="C41")
    boat = create_boat(customer["id"], boat_name="B41", hull_length_m=9.0)
    sheet = create_frozen_sheet(boat["id"], i_height_m=10.0, j_base_m=3.0, p_main_m=12.0, e_main_m=4.0)
    version = get_boat(boat["id"])["version"]

    resp = api.create_sail_design(
        boat["id"],
        {
            "measurement_sheet_id": sheet["id"],
            "cloth_tier": "CRUISE",
            "reinforcement_level": 1,
            "option_codes": [],
            "expected_boat_version": version,
        },
        RIG,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_customer_cannot_approve_another_customers_design(api):
    """PRD §3.3: "Approval is the customer's call and is guarded three ways: the
    acting customer's `X-User-ID` must equal the boat's `customer_id`, the
    customer's `status` must be `ACTIVE`, and the customer's
    `outstanding_balance_cents` plus the projected quote for the design must not
    exceed the customer's `credit_limit_cents`."
    PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the
    acting Customer; ownership checks on any resource that references a Customer
    compare the resource's customer foreign-key field to `X-User-ID`."

    Design: Corner/roles/customer_cannot_approve_another_customers_design
    """
    owner_ctx = setup_approved_design(submit_only=True)
    intruder = create_customer(full_name="C42b")

    resp = api.approve_sail_design(
        owner_ctx["boat"]["id"], owner_ctx["design"]["id"], make_customer_headers(intruder["id"])
    )
    # The PRD pins the ownership check but not whether a failed check surfaces as
    # 403 or 404; both are faithful.
    actual = validate_error_is_one_of(resp, [ApiErrorId.ERR_FORBIDDEN_ROLE, ApiErrorId.ERR_RESOURCE_NOT_FOUND])
    assert resp.status_code in (403, 404), f"ownership rejection must be 403/404, got {resp.status_code} ({actual})"

    after = get_sail_design(owner_ctx["design"]["id"])
    assert after["design_status"] == "SUBMITTED", (
        f"non-owner approval must not change the design, got {after['design_status']}"
    )
