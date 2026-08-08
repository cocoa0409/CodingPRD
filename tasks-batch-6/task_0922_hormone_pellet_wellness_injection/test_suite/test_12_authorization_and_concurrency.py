"""Authentication, role and ownership gates, the delegation gate, and the three
stale-version guards."""

from test_helpers import (
    ApiErrorId,
    NO_AUTH_HEADERS,
    TEST_USERS,
    attach_consent_to,
    book_procedure,
    make_headers_with_role,
    make_nurse_headers,
    make_patient_headers,
    make_physician_headers,
    membership_version,
    new_membership,
    new_nurse,
    new_patient,
    new_physician,
    new_standing_order,
    open_supply_for,
    patient_version,
    procedure_version,
    read_lot,
    read_membership,
    read_patient,
    read_procedure,
    read_standing_order,
    record_consult,
    run_allocation_for,
    set_clock,
    set_hold,
    setup_clinic,
    setup_pellet_procedure,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import assert_lot_buckets

ADMIN = TEST_USERS["clinic_admin_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]
INVENTORY = TEST_USERS["inventory_manager_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _cancelled_procedure_under_a_revoked_order(api):
    """A tray opened then cancelled, and the governing order revoked afterwards."""
    ctx = setup_clinic(
        api, prescribed_dose_mg=1000, patient_name="Pat Sixteen",
        patient_email="p16@example.com",
        lot_specs=[{"lot_code": "T200-A", "strength_mg": 200, "qty_received": 10}],
    )
    nurse = new_nurse(api)
    procedure = book_procedure(
        api, ctx["patient_id"], nurse["id"], ctx["consult_id"], ctx["standing_order_id"],
        room_code="RM9", scheduled_start="2026-05-30T09:00:00Z",
    )
    attach_consent_to(api, procedure["id"], ctx["consent"]["id"])
    run_allocation_for(api, procedure["id"])
    open_supply_for(api, procedure["id"], ctx["physician_id"])
    validate_success(
        api.cancel_procedure(procedure["id"], {"reason": "Patient withdrew"}, FRONT_DESK), 200
    )
    validate_success(
        api.revoke_standing_order(
            ctx["standing_order_id"], {"reason": "Physician left the practice"},
            make_physician_headers(ctx["physician_id"]),
        ),
        200,
    )
    ctx["nurse"] = nurse
    ctx["procedure_id"] = procedure["id"]
    return ctx


def test_nurse_hears_the_delegation_gate_on_a_cancelled_procedure(api):
    """PRD §2.8: "The gate fires **only** when `X-User-Role` is `NurseInjector`, and **only**
    on three endpoints — `POST /clinic/procedures/{id}/open-supply`,
    `POST /clinic/procedures/{id}/perform`, and
    `POST /clinic/injection-visits/{id}/administer`. On those three requests, the
    `StandingOrder` referenced by the target row must satisfy every one of four conditions: its
    `status` must be `ACTIVE` (both `SUSPENDED` and `REVOKED` fail);"
    PRD §2.8: "The gate sits above state, above concurrency and above every business rule. A
    `NurseInjector` acting under a lapsed order therefore sees `ERR_STANDING_ORDER_INVALID`
    even when the target row is also in the wrong state, also stale, and also short of
    inventory."

    Design: Difficulty/priority_pair_validation_conflict/standing_order_gate_pre_empts_terminal_state_for_nurse
    """
    ctx = _cancelled_procedure_under_a_revoked_order(api)

    response = api.perform_procedure(
        ctx["procedure_id"],
        {
            "expected_patient_version": patient_version(api, ctx["patient_id"]),
            "pellets_wasted": 0,
        },
        make_nurse_headers(ctx["nurse"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_STANDING_ORDER_INVALID.value)
    assert response.status_code == 403

    procedure = read_procedure(api, ctx["procedure_id"])
    assert procedure["status"] == "CANCELLED"
    assert procedure["pellets_wasted"] == 5
    assert_lot_buckets(
        read_lot(api, ctx["lots"]["T200-A"]["id"]),
        on_hand=5, reserved=0, consumed=0, wasted=5, returned=0,
    )


def test_physician_hears_the_terminal_state_on_the_same_cancelled_procedure(api):
    """PRD §2.8: "Four exclusions keep the rest of the ladder reachable and are as binding as
    the gate itself. First, the same three endpoints performed by a `Physician` are outside
    the gate entirely — a physician acts on their own licence, so no delegation is needed."
    PRD §2.9: "**Rung 11** — the target row is not already in a terminal state for the axis
    being moved, on every action endpoint. The terminal sets are: a procedure's `status` in
    `CANCELLED` or `VOIDED`; a lot's `sterility_status` at `RECALLED`; a standing order's
    `status` at `REVOKED`; a series pack's `status` in `EXPIRED` or `REFUNDED`; an injection
    visit's `status` in `CANCELLED` or `VOIDED`; a membership's `status` at `CANCELLED`; a
    financing plan's `status` in `DEFAULTED`, `PAID_OFF` or `CANCELLED`; an adverse event's
    `status` at `CLOSED`; and a notification's `status` at `ACKNOWLEDGED`. Otherwise
    `ERR_ALREADY_TERMINAL` (409)."

    Design: Difficulty/priority_pair_validation_conflict/standing_order_gate_pre_empts_terminal_state_for_nurse
    """
    ctx = _cancelled_procedure_under_a_revoked_order(api)

    response = api.perform_procedure(
        ctx["procedure_id"],
        {
            "expected_patient_version": patient_version(api, ctx["patient_id"]),
            "pellets_wasted": 0,
        },
        make_physician_headers(ctx["physician_id"]),
    )
    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL.value)
    assert response.status_code == 409

    assert read_procedure(api, ctx["procedure_id"])["status"] == "CANCELLED"


def test_front_desk_cannot_receive_a_pellet_lot(api):
    """PRD §2.9: "**Rung 3** — the acting role appears in the addressed endpoint's
    authorised-role list, on every endpoint. Otherwise `ERR_FORBIDDEN_ROLE` (403)."
    PRD §3.5: "Pellets enter the clinic in manufacturer lots, and only an `InventoryManager`
    may receive one."

    Design: Corner/rbac/front_desk_cannot_receive_a_pellet_lot
    """
    response = api.create_pellet_lot(
        {
            "lot_code": "T200-FD",
            "hormone_type": "TESTOSTERONE",
            "strength_mg": 200,
            "expiry_date": "2026-12-01T00:00:00Z",
            "qty_received": 10,
        },
        FRONT_DESK,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert response.status_code == 403


def test_nurse_injector_cannot_author_a_standing_order(api):
    """PRD §3.8: "A standing order is how a physician lends their licence. Only a `Physician`
    may author one, and it names the delegating `physician_id` (who must be a provider whose
    `provider_type` is `PHYSICIAN`), a `scope_hormone_types` array that is a subset of
    testosterone and estradiol and may be empty, a `scope_injection_types` array that is a
    subset of `B12`, `LIPOTROPIC`, `VITAMIN_D` and `GLUTATHIONE` and may likewise be empty, a
    `max_dose_mg` greater than zero capping the planned milligrams a nurse may deliver under
    it, and the inclusive window `valid_from` to `valid_until`."
    PRD §2.9: "**Rung 3** — the acting role appears in the addressed endpoint's
    authorised-role list, on every endpoint. Otherwise `ERR_FORBIDDEN_ROLE` (403)."

    Design: Corner/rbac/nurse_injector_cannot_author_a_standing_order
    """
    nurse = new_nurse(api)

    response = api.create_standing_order(
        {
            "physician_id": nurse["id"],
            "scope_hormone_types": ["TESTOSTERONE"],
            "scope_injection_types": ["B12"],
            "max_dose_mg": 1500,
            "valid_from": "2026-05-01T00:00:00Z",
            "valid_until": "2026-10-01T00:00:00Z",
        },
        make_nurse_headers(nurse["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert response.status_code == 403

    rows, meta = validate_paginated(
        api.list_standing_orders(FRONT_DESK, {"physician_id": nurse["id"]})
    )
    assert meta["total_count"] == 0


def test_compliance_officer_cannot_schedule_a_procedure(api):
    """PRD §2.1: "A `ComplianceOfficer` provides quality and safety oversight: they may
    execute recalls and read every clinical record, but may not schedule, administer, allocate
    or bill."
    PRD §2.9: "**Rung 3** — the acting role appears in the addressed endpoint's
    authorised-role list, on every endpoint. Otherwise `ERR_FORBIDDEN_ROLE` (403)."

    Design: Corner/rbac/compliance_officer_cannot_schedule_a_procedure
    """
    physician = new_physician(api)
    patient = new_patient(api, "Corner ThirtyNine", "c39@example.com")
    consult = record_consult(api, patient["id"], physician["id"], prescribed_dose_mg=1000)
    order = new_standing_order(api, physician["id"])

    response = api.create_procedure(
        {
            "patient_id": patient["id"],
            "provider_id": physician["id"],
            "consult_id": consult["id"],
            "standing_order_id": order["id"],
            "procedure_type": "INITIAL",
            "room_code": "RM61",
            "scheduled_start": "2026-06-21T09:00:00Z",
        },
        COMPLIANCE,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert response.status_code == 403

    rows, meta = validate_paginated(
        api.list_procedures(FRONT_DESK, {"consult_id": consult["id"]})
    )
    assert meta["total_count"] == 0


def test_patient_cannot_read_another_patients_procedure(api):
    """PRD §2.1: "A `Patient` acts on their own records only. When `X-User-Role` is `Patient`,
    `X-User-ID` is the `id` of the acting `Patient` record, and ownership is enforced by
    comparing `X-User-ID` against the addressed row's `patient_id`. A `Patient` who addresses
    a row belonging to somebody else is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403) —
    the same code a physician receives when acting on a standing order they did not author."
    PRD §2.9: "**Rung 8** — for the entity-backed roles, `X-User-ID` owns the addressed row."

    Design: Corner/rbac/patient_cannot_read_another_patients_procedure
    """
    physician = new_physician(api)
    owner = new_patient(api, "Corner Forty A", "c40a@example.com")
    stranger = new_patient(
        api, "Corner Forty B", "c40b@example.com", date_of_birth="1980-01-02"
    )
    consult = record_consult(api, owner["id"], physician["id"], prescribed_dose_mg=1000)
    order = new_standing_order(api, physician["id"])
    procedure = book_procedure(
        api, owner["id"], physician["id"], consult["id"], order["id"],
        room_code="RM62", scheduled_start="2026-06-22T09:00:00Z",
    )

    response = api.get_procedure(procedure["id"], make_patient_headers(stranger["id"]))
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value)
    assert response.status_code == 403

    assert read_procedure(api, procedure["id"])["status"] == "SCHEDULED"


def test_physician_cannot_revoke_another_physicians_standing_order(api):
    """PRD §2.1: "Concretely, withdrawing or reinstating a standing order requires that
    `X-User-ID` equal that order's `physician_id`, and reviewing an adverse event compares
    `X-User-ID` against `reported_by_provider_id` and `reviewed_by_provider_id`."
    PRD §2.9: "**Rung 8** — for the entity-backed roles, `X-User-ID` owns the addressed row. A
    `Patient` may only read or act on rows whose `patient_id` equals `X-User-ID`; a `Physician`
    or `NurseInjector` must supply an `X-User-ID` that is a `Provider` id; and for
    standing-order revoke and reinstate the acting `X-User-ID` must equal that order's
    `physician_id`. Applies to every endpoint whose acting role is `Patient`, `Physician` or
    `NurseInjector`. Otherwise `ERR_FORBIDDEN_OWNERSHIP` (403)."

    Design: Corner/rbac/physician_cannot_revoke_another_physicians_standing_order
    """
    author = new_physician(api)
    interloper = new_physician(api, "Dr Ben Sato", "1000000002")
    order = new_standing_order(api, author["id"])

    response = api.revoke_standing_order(
        order["id"], {"reason": "Not mine to revoke"}, make_physician_headers(interloper["id"])
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value)
    assert response.status_code == 403

    assert read_standing_order(api, order["id"])["status"] == "ACTIVE"


def test_stale_procedure_version_is_rejected_on_the_allocation_planner(api):
    """PRD §2.7: "`POST /clinic/procedures/{id}/allocations` requires
    `expected_procedure_version` carrying the client's last observed `version` of the addressed
    `Procedure`. A fresh allocation request legitimately supersedes whatever allocation set the
    procedure already holds — the prior reserved rows are released and a new plan is minted —
    so the operation can never be refused on state grounds alone, and the stale-version check
    is the only thing standing between the caller and silently discarding an allocation set
    that was produced from a newer plan. A mismatch is rejected with
    `ERR_STALE_PROCEDURE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_procedure_version_rejected_on_allocations
    """
    ctx = setup_pellet_procedure(
        api, target_status="SCHEDULED", prescribed_dose_mg=1000,
        patient_name="Corner FortyTwo", patient_email="c42@example.com",
        room_code="RM63", scheduled_start="2026-06-23T09:00:00Z",
        lot_specs=[{"lot_code": "T200-A", "strength_mg": 200, "qty_received": 20}],
    )
    attach_consent_to(api, ctx["procedure_id"], ctx["consent"]["id"])
    observed = procedure_version(api, ctx["procedure_id"])
    run_allocation_for(api, ctx["procedure_id"], expected_version=observed)

    response = api.run_allocation(
        ctx["procedure_id"], {"expected_procedure_version": observed}, INVENTORY
    )
    validate_error(response, ApiErrorId.ERR_STALE_PROCEDURE_VERSION.value)
    assert response.status_code == 412

    assert_lot_buckets(
        read_lot(api, ctx["lots"]["T200-A"]["id"]),
        on_hand=15, reserved=5, consumed=0, wasted=0, returned=0,
    )
    assert read_procedure(api, ctx["procedure_id"])["pellets_allocated"] == 5


def test_stale_patient_version_is_rejected_on_perform(api):
    """PRD §2.7: "`POST /clinic/procedures/{id}/perform` requires `expected_patient_version`
    carrying the client's last observed `version` of the procedure's `Patient`."
    PRD §2.7: "If `expected_patient_version` does not equal the patient's current `version`,
    the request is rejected with `ERR_STALE_PATIENT_VERSION` (HTTP 412) and nothing is written."

    Design: Corner/cross_cutting_layers/occ_stale_patient_version_rejected_on_perform
    """
    ctx = setup_pellet_procedure(
        api, target_status="SUPPLY_OPENED", prescribed_dose_mg=1000,
        patient_name="Corner FortyThree", patient_email="c43@example.com",
        room_code="RM64", scheduled_start="2026-05-10T09:00:00Z",
        lot_specs=[{"lot_code": "T200-A", "strength_mg": 200, "qty_received": 10}],
    )
    stale_version = patient_version(api, ctx["patient_id"])
    set_hold(
        api, ctx["patient_id"], "CLINICAL", "SET",
        physician_id=ctx["physician_id"], reason="Pending clearance",
    )
    set_hold(
        api, ctx["patient_id"], "CLINICAL", "CLEAR",
        physician_id=ctx["physician_id"], reason="Cleared",
    )
    set_clock(api, "2026-05-10T09:00:00Z")

    response = api.perform_procedure(
        ctx["procedure_id"],
        {"expected_patient_version": stale_version, "pellets_wasted": 0},
        make_physician_headers(ctx["physician_id"]),
    )
    validate_error(response, ApiErrorId.ERR_STALE_PATIENT_VERSION.value)
    assert response.status_code == 412

    patient = read_patient(api, ctx["patient_id"])
    assert patient["clinical_hold"] is False
    assert patient["eligibility_status"] == "CLEAR"

    procedure = read_procedure(api, ctx["procedure_id"])
    assert procedure["status"] == "SUPPLY_OPENED"
    assert procedure["delivered_total_mg"] == 0
    assert_lot_buckets(
        read_lot(api, ctx["lots"]["T200-A"]["id"]),
        on_hand=5, reserved=5, consumed=0, wasted=0, returned=0,
    )


def test_stale_membership_version_is_rejected_on_tier_change(api):
    """PRD §2.7: "`POST /clinic/memberships/{id}/tier-change` requires
    `expected_membership_version` carrying the client's last observed `version` of the
    addressed `Membership`. A tier change legitimately supersedes the prior tier, restarts the
    period and resets the included-visit counter, so it would otherwise succeed from any active
    state; the stale-version check is what prevents a change computed against a pre-pause fee
    basis from overwriting a period that a pause or an included-visit redemption has since
    moved. A mismatch is rejected with `ERR_STALE_MEMBERSHIP_VERSION` (HTTP 412)."
    PRD §3.7: "It rewrites `tier`, `monthly_fee_cents`, `discount_pct` and
    `included_visits_allowance` from the new tier, resets `included_visits_used` to 0 — the
    only thing that ever resets it — restamps `period_start` from the logical clock with
    `period_end` set 30 days later, and increments the `version`."

    Design: Corner/cross_cutting_layers/occ_stale_membership_version_rejected_on_tier_change
    """
    patient = new_patient(api, "Corner FortyFour", "c44@example.com", sex_at_birth="FEMALE")
    membership = new_membership(api, patient["id"], "BASIC")
    observed = membership_version(api, membership["id"])

    validate_success(
        api.change_membership_tier(
            membership["id"], {"tier": "ELITE", "expected_membership_version": observed},
            FRONT_DESK,
        ),
        200,
    )

    response = api.change_membership_tier(
        membership["id"], {"tier": "PLUS", "expected_membership_version": observed}, FRONT_DESK
    )
    validate_error(response, ApiErrorId.ERR_STALE_MEMBERSHIP_VERSION.value)
    assert response.status_code == 412

    kept = read_membership(api, membership["id"])
    assert kept["tier"] == "ELITE"
    assert kept["monthly_fee_cents"] == 19900
    assert kept["discount_pct"] == 0.20
    assert kept["included_visits_allowance"] == 4
    assert kept["included_visits_used"] == 0


def test_request_without_identity_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to every endpoint — reads included — must carry two headers:
    `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity in which they
    act. If either header is absent or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.9: "**Rung 1** — `X-User-Role` and `X-User-ID` are both present and non-empty, on
    every endpoint. Otherwise `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/cross_cutting_layers/missing_auth_headers_returns_unauthenticated
    """
    response = api._request(
        "POST",
        "/clinic/patients",
        {
            "full_name": "Corner FortyFive",
            "date_of_birth": "1980-01-01",
            "email": "c45@example.com",
            "sex_at_birth": "MALE",
        },
        NO_AUTH_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert response.status_code == 401

    # The email is unique across all patients, so an authenticated registration
    # reusing it can only succeed if the rejected request persisted nothing.
    retry = api.create_patient(
        {
            "full_name": "Corner FortyFive",
            "date_of_birth": "1980-01-01",
            "email": "c45@example.com",
            "sex_at_birth": "MALE",
        },
        ADMIN,
    )
    validate_success(retry, 201)


def test_unknown_role_string_is_an_authentication_failure_not_a_permission_one(api):
    """PRD §2.1: "If `X-User-Role` carries a string that is not one of the seven declared
    roles, the same `ERR_UNAUTHENTICATED` is returned — an unknown role is treated as a failure
    to authenticate, not as a permission problem."
    PRD §2.9: "**Rung 2** — `X-User-Role` names one of the seven declared roles, on every
    endpoint. Otherwise `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/cross_cutting_layers/unknown_role_header_returns_unauthenticated
    """
    response = api.create_patient(
        {
            "full_name": "Corner FortySix",
            "date_of_birth": "1980-01-01",
            "email": "c46@example.com",
            "sex_at_birth": "MALE",
        },
        make_headers_with_role("ops-admin-1", "BILLING_BOT"),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert response.status_code == 401, (
        "An unrecognised role is rejected at rung 2 with 401, not at rung 3 with 403"
    )

    retry = api.create_patient(
        {
            "full_name": "Corner FortySix",
            "date_of_birth": "1980-01-01",
            "email": "c46@example.com",
            "sex_at_birth": "MALE",
        },
        ADMIN,
    )
    validate_success(retry, 201)
