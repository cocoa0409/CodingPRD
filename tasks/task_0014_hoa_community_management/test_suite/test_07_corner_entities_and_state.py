"""Corner-design translations from queue (B): entities §1 and state_machines §2.

Skipped instances:
  * create_owner_missing_required_field_returns_invalid_request — PRD never
    names ERR_INVALID_REQUEST in prose (only the §5 error catalog table),
    so the rule fails the "asserted error_id is named in PRD prose" check.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    bootstrap_lien_via_cascade,
    bootstrap_paid_assessment,
    bootstrap_tenant,
    create_acc_request,
    create_assessment,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    make_acc_member_headers,
    make_board_president_headers,
    make_board_secretary_headers,
    make_homeowner_headers,
    make_platform_admin_headers,
    make_treasurer_headers,
)


# ─────────────────────────────────────────────────────────────────────────────
# Section: entities
# ─────────────────────────────────────────────────────────────────────────────

def test_create_community_with_required_fields_applies_defaults(api):
    """PRD §3.1: "Several governance knobs may be provided at creation and
    otherwise fall back to defaults: the days of grace before a late fee
    is assessed (`late_fee_grace_days`, defaulting to 15), the flat
    late-fee component per grace cycle in cents (`late_fee_flat_cents`,
    defaulting to 2500), the percentage late-fee component expressed in
    basis points of the overdue principal (`late_fee_pct_bps`, defaulting
    to 1000 — that is, 10 percent), the aggregate property delinquency
    in cents at which a lien is auto-filed (`lien_threshold_cents`,
    defaulting to 250000), the quorum threshold expressed as an integer
    percent of eligible owners (`election_quorum_pct`, defaulting to 33),
    and the annual inflation in basis points applied to reserve component
    replacement costs (`reserve_inflation_bps`, defaulting to 300)."

    Design: Corner/entities/create_community_with_all_required_fields_returns_201
    """
    resp = api.create_community(
        {
            "name": "TestHOA",
            "fiscal_year_start_month": 1,
            "regular_assessment_cents": 30000,
        },
        make_platform_admin_headers(),
    )
    data = validate_success(resp, expected_status=201)
    assert data["late_fee_grace_days"] == 15
    assert data["late_fee_flat_cents"] == 2500
    assert data["late_fee_pct_bps"] == 1000
    assert data["lien_threshold_cents"] == 250000
    assert data["election_quorum_pct"] == 33
    assert data["reserve_inflation_bps"] == 300


def test_get_community_with_unknown_uuid_returns_not_found(api):
    """PRD §2.9: "Path-templated existence checks are evaluated strictly
    left to right: when the path references a parent resource by `id`
    followed by a child resource by `id`, the parent must resolve to an
    existing row before the child is even looked up. Either failure raises
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_community_by_nonexistent_id_returns_not_found
    """
    resp = api.get_community(NON_EXISTENT_UUID, make_platform_admin_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_property_account_balance_increases_when_assessment_created(api):
    """PRD §3.1: "Two derived fields hang off every property and update
    automatically as ledger and adjudication events unfold:
    `account_balance_cents`, the sum of `outstanding_cents` across the
    property's `Assessment`s in `DUE` or `OVERDUE` status, and
    `compliance_posture`, the derived rollup detailed in §2.7."
    PRD §3.2: "The new `Assessment` is born in the `DUE` state with
    `late_fee_cents` of zero, `paid_cents` of zero, and `outstanding_cents`
    equal to `principal_cents`. Each fresh assessment refreshes the
    owning property's `account_balance_cents`."

    Design: Corner/entities/property_account_balance_recomputed_on_assessment_creation
    """
    _community, _owner, prop = bootstrap_tenant(
        community_name="Comp1", owner_email="cf@x.com", owner_name="CF",
        unit_label="CF-1",
    )
    # initial state
    assert prop["account_balance_cents"] == 0
    create_assessment(
        prop["id"], kind="REGULAR", principal_cents=20000,
        due_date="2027-01-01T00:00:00Z",
    )
    refreshed = validate_success(
        api.get_property(prop["id"], make_treasurer_headers()),
        expected_status=200,
    )
    assert refreshed["account_balance_cents"] == 20000, (
        f"balance must equal sum of outstanding (20000) after one DUE "
        f"assessment, got {refreshed['account_balance_cents']}"
    )


def test_payment_application_appended_state_is_applied_and_unchanged_on_get(api):
    """PRD §2.4: "A `PaymentApplication` carries only `id` and `created_at`;
    it has no `updated_at` and no `version`. A reversal does not edit the
    original `PaymentApplication` in place — the original row's `state`
    is moved to `REVERSED` as the single permitted transition out of
    `APPLIED`, and that single state change is the event the system reports."

    Design: Corner/entities/payment_application_is_immutable_no_update_endpoint
    """
    _community, _owner, prop = bootstrap_tenant(
        community_name="Immut", owner_email="im@x.com", owner_name="IM",
        unit_label="IM-1", regular_assessment_cents=10000,
    )
    a = create_assessment(
        prop["id"], kind="REGULAR", principal_cents=10000,
        due_date="2027-06-01T00:00:00Z",
    )
    pa = validate_success(
        api.create_payment(
            {
                "assessment_id": a["id"],
                "amount_cents": 5000,
                "expected_assessment_version": a["version"],
            },
            make_treasurer_headers(),
        ),
        expected_status=201,
    )
    assert pa["state"] == "APPLIED"
    # PRD §2.4: PaymentApplication carries only id + created_at — no version,
    # no updated_at. The single permitted state transition is APPLIED →
    # REVERSED; a plain GET must report state APPLIED.
    got = validate_success(
        api.get_payment(pa["id"], make_treasurer_headers()),
        expected_status=200,
    )
    assert got["state"] == "APPLIED", (
        f"PaymentApplication state must remain APPLIED on plain GET, "
        f"got {got['state']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Section: state_machines
# ─────────────────────────────────────────────────────────────────────────────

def test_new_assessment_initial_state_is_due(api):
    """PRD §3.2: "The new `Assessment` is born in the `DUE` state with
    `late_fee_cents` of zero, `paid_cents` of zero, and `outstanding_cents`
    equal to `principal_cents`."

    Design: Corner/state_machines/assessment_initial_state_is_due
    """
    _community, _owner, prop = bootstrap_tenant(
        community_name="Init", owner_email="in@x.com", owner_name="IN",
        unit_label="IN-1", regular_assessment_cents=10000,
    )
    a = create_assessment(
        prop["id"], kind="REGULAR", principal_cents=10000,
        due_date="2027-01-01T00:00:00Z",
    )
    assert a["status"] == "DUE"
    assert a["late_fee_cents"] == 0
    assert a["paid_cents"] == 0
    assert a["outstanding_cents"] == 10000


def test_contest_violation_already_paid_returns_invalid_state(api):
    """PRD §3.5: "The owner of the property has two responses available
    while the violation is `OPEN`. They may contest within thirty days of
    `opened_at` — that is, while `current_utc` is at or before `opened_at`
    plus 30 days — moving the violation to `CONTESTED`. A late contest
    (after the 30-day window) is refused with `ERR_INVALID_STATE`. The
    owner may alternatively pay the fine directly, moving the violation
    from `OPEN` to `PAID` (terminal) and refreshing the property's
    `compliance_posture`."

    A PAID violation is no longer in the from-state OPEN — per PRD §2.11
    state-machine eligibility ("State-machine eligibility
    (`ERR_INVALID_STATE`) is checked before any business rule"), contest
    on a PAID violation must reject with ERR_INVALID_STATE.

    Design: Corner/state_machines/contest_violation_from_paid_returns_invalid_state
    """
    _community, owner, prop = bootstrap_tenant(
        community_name="InvT", owner_email="it@x.com", owner_name="IT",
        unit_label="IT-1",
    )
    v = validate_success(
        api.create_violation(
            {"property_id": prop["id"], "category": "PARKING"},
            make_board_secretary_headers(),
        ),
        expected_status=201,
    )
    validate_success(
        api.pay_violation_fine(v["id"], make_homeowner_headers(owner["id"])),
        expected_status=200,
    )
    resp = api.contest_violation(v["id"], make_homeowner_headers(owner["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_waive_assessment_in_paid_state_returns_invalid_state(api):
    """PRD §2.11: "State-machine eligibility (`ERR_INVALID_STATE`) is
    checked before any business rule."
    PRD §3.2: "The `BoardPresident` is the only role authorized to waive
    an unpaid assessment, transitioning it from `DUE` to `WAIVED` (a
    terminal state)."

    The waive action's from-state per PRD §3.2 is DUE; an Assessment in
    PAID (terminal) is not eligible → ERR_INVALID_STATE.

    Design: Corner/state_machines/assessment_paid_is_terminal_no_further_transitions
    """
    _community, _owner, _prop, paid = bootstrap_paid_assessment(
        community_name="Term", unit_label="TR-1",
    )
    assert paid["status"] == "PAID"
    resp = api.waive_assessment(paid["id"], make_board_president_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_acc_revision_limit_fourth_request_rejected(api):
    """PRD §3.6: "Request-revision is itself capped: if the existing
    `revision_count` is already 3, the request-revision action is refused
    with `ERR_ACC_REVISION_LIMIT` — meaning the revision cycle can be
    entered at most three times in the lifetime of a single request."

    Setup: drive three full request-revision/resubmit cycles, then try a
    fourth request-revision when revision_count == 3 → ERR_ACC_REVISION_LIMIT.

    Design: Corner/state_machines/acc_revision_limit_three_then_fourth_request_revision_rejected
    """
    _community, owner, prop = bootstrap_tenant(
        community_name="RevLim", owner_email="rl@x.com", owner_name="RL",
        unit_label="RL-1",
    )
    acc = create_acc_request(
        prop["id"], owner["id"], scope="LANDSCAPING",
        description="Garden",
    )
    ho_headers = make_homeowner_headers(owner["id"])
    acc_headers = make_acc_member_headers()
    for _ in range(3):
        validate_success(
            api.request_revision_acc(acc["id"], acc_headers),
            expected_status=200,
        )
        validate_success(
            api.resubmit_acc_request(acc["id"], ho_headers),
            expected_status=200,
        )
    # Fourth attempt: revision_count == 3, capped.
    resp = api.request_revision_acc(acc["id"], acc_headers)
    validate_error(resp, ApiErrorId.ERR_ACC_REVISION_LIMIT)


def test_initiate_foreclosure_before_180_day_cooldown_rejected(api):
    """PRD §3.4: "The temporal precondition is that `current_utc` is at
    or past `filed_at` plus 180 days — a six-month cooling-off period
    that must have fully elapsed before foreclosure can be initiated; if
    the cool-off window has not yet expired, the request is refused with
    `ERR_INVALID_STATE`."

    Setup: Lien filed via cascade (filed_at = 2026-02-01). Advance clock
    to 2026-04-01 (~59 days < 180). Foreclosure must reject with
    ERR_INVALID_STATE.

    Design: Corner/state_machines/foreclosure_before_180_day_cooldown_rejected
    """
    _community, _owner, _prop, _assess, lien = bootstrap_lien_via_cascade(
        community_name="ForeC", owner_email="fc@x.com", owner_name="FC",
        unit_label="FC-1",
    )
    set_clock("2026-04-01T00:00:00Z")
    resp = api.initiate_foreclosure(lien["id"], make_board_president_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
