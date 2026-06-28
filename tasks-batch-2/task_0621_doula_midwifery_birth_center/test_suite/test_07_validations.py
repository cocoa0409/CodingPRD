"""Business and fiscal validation rules in isolated single-failure scenarios
(queue B: Corner / validations).
"""
from test_helpers import (
    api_client, TEST_USERS, validate_success, validate_error, get_success_data,
    ApiErrorId, fixtures,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["center_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
MIDWIFE = TEST_USERS["midwife_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ---- claim_amounts_inverted_invalid ----
def test_claim_amounts_inverted_invalid(api):
    """PRD §3.6: "a request that breaks paid_amount_cents ≤ allowed_amount_cents ≤
    billed_amount_cents is refused with ERR_CLAIM_AMOUNTS_INVALID (HTTP 422)."

    Design: Corner/validations/claim_amounts_inverted_invalid
    """
    ctx = fixtures.setup_episode_with_submitted_claim(global_fee_cents=800000)
    claim_id = ctx["claim"]["id"]
    resp = api.adjudicate_claim(claim_id, f.adjudicate_payload(100000, 200000), BILLING)
    validate_error(resp, ApiErrorId.ERR_CLAIM_AMOUNTS_INVALID.value)


# ---- provider_at_capacity_rejected ----
def test_provider_at_capacity_rejected(api):
    """PRD §3.4: "The provider's primary load must be below max_active_episodes before the
    assignment is admitted; a provider already at the ceiling is refused with
    ERR_PROVIDER_AT_CAPACITY (HTTP 409)."

    Design: Corner/validations/provider_at_capacity_rejected
    """
    kit, package = fixtures.create_catalog()
    c1 = fixtures.create_client()
    c2 = fixtures.create_client(full_name="Bea B", date_of_birth="1992-05-09", parity=1)
    e1 = fixtures.open_episode(package["code"], client_id=c1["id"])
    e2 = fixtures.open_episode(package["code"], client_id=c2["id"], edd="2026-09-01")
    pri = fixtures.create_provider(max_active_episodes=1)

    fixtures.assign_primary(e1["id"], pri["id"],
                            coverage_start="2026-07-01T00:00:00Z", coverage_end="2026-07-10T00:00:00Z")
    # Second assignment with a NON-overlapping window -> capacity is the failing check.
    resp = api.create_on_call_assignment(
        f.create_on_call_assignment_payload(
            e2["id"], pri["id"],
            coverage_start="2026-08-01T00:00:00Z", coverage_end="2026-08-10T00:00:00Z"),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_PROVIDER_AT_CAPACITY.value)


# ---- booking_inverted_interval_invalid ----
def test_booking_zero_length_interval_invalid(api):
    """PRD §3.5: "The interval must be well-formed: starts_at must fall strictly before
    ends_at, and a zero-length or inverted interval is refused with ERR_INVALID_INTERVAL
    (HTTP 422)."

    Design: Corner/validations/booking_inverted_interval_invalid
    """
    ctx = fixtures.setup_episode()
    ep_id = ctx["episode"]["id"]
    room = fixtures.create_room(turnover_minutes=0)
    resp = api.create_booking(
        f.create_booking_payload(ep_id, room["id"], room["version"],
                                 starts_at="2026-01-02T00:00:00Z", ends_at="2026-01-02T00:00:00Z"),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL.value)


# ---- backup_same_provider_rejected ----
def test_backup_same_provider_rejected(api):
    """PRD §3.4: "The backup provider must differ from the primary's provider: a backup
    that names the primary's own provider is refused with ERR_BACKUP_SAME_PROVIDER
    (HTTP 409)."

    Design: Corner/validations/backup_same_provider_rejected
    """
    ctx = fixtures.setup_episode()  # episode in PLANNING is fine; assignment created below
    ep_id = ctx["episode"]["id"]
    pri = fixtures.create_provider(max_active_episodes=2)
    assignment = fixtures.assign_primary(ep_id, pri["id"])

    resp = api.name_backup(assignment["id"], f.name_backup_payload(pri["id"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_BACKUP_SAME_PROVIDER.value)


# ---- overpayment_rejected ----
def test_overpayment_rejected(api):
    """PRD §3.10: "A payment may not exceed the plan's remaining_cents; any overpayment
    beyond the final installment is refused with ERR_OVERPAYMENT (HTTP 409)."

    Design: Corner/validations/overpayment_rejected
    """
    ctx = fixtures.setup_plan_active_episode(installment_count=1, global_fee_cents=800000)
    plan_id = ctx["plan"]["id"]
    resp = api.apply_payment(plan_id, f.payment_payload(160001), BILLING)
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT.value)
    plan = validate_success(api.get_payment_plan(plan_id, BILLING))
    assert plan["paid_cents"] == 0, "rejected payment applies nothing"


# ---- no_balance_plan_rejected ----
def test_no_balance_plan_rejected(api):
    """PRD §3.10: "Creation requires the episode's balance_due_cents to be strictly greater
    than zero; a plan create attempted on a zero balance is refused with ERR_NO_BALANCE
    (HTTP 409)."

    Design: Corner/validations/no_balance_plan_rejected
    """
    ctx = fixtures.setup_episode_with_submitted_claim(global_fee_cents=800000)
    ep_id = ctx["episode"]["id"]
    claim_id = ctx["claim"]["id"]
    # Adjudicate allowed=0 paid=0 -> responsibility 0, balance 0; financial still UNBILLED.
    validate_success(api.adjudicate_claim(claim_id, f.adjudicate_payload(0, 0), BILLING))
    ep = validate_success(api.get_episode(ep_id, BILLING))
    assert ep["balance_due_cents"] == 0

    resp = api.create_payment_plan(
        f.create_payment_plan_payload(ep_id, 2, ep["version"]), BILLING
    )
    validate_error(resp, ApiErrorId.ERR_NO_BALANCE.value)


# ---- postpartum_incomplete_blocks_complete_care ----
def test_postpartum_incomplete_blocks_complete_care(api):
    """PRD §3.2: "Completing care advances clinical_status from BORN to COMPLETED. This is
    allowed only when the postpartum follow-up has been fulfilled: the episode's
    prenatal_visits_completed must be at least the package's postpartum_visits_included. If
    too few qualifying visits have been completed the request is refused with
    ERR_POSTPARTUM_INCOMPLETE (HTTP 409)"

    Design: Corner/validations/postpartum_incomplete_blocks_complete_care
    """
    # Package requires 2 postpartum visits; reach BORN with 0 completed visits.
    ctx = fixtures.setup_born_episode(postpartum_visits_included=2)
    ep_id = ctx["episode"]["id"]
    assert ctx["episode"]["clinical_status"] == "BORN"

    resp = api.complete_care(ep_id, MIDWIFE)
    validate_error(resp, ApiErrorId.ERR_POSTPARTUM_INCOMPLETE.value)
    ep = validate_success(api.get_episode(ep_id, MIDWIFE))
    assert ep["clinical_status"] == "BORN", "unchanged"


# ---- void_claim_with_plan_rejected ----
def test_void_claim_with_plan_rejected(api):
    """PRD §3.6: "Voiding a claim moves it from SUBMITTED or DENIED to VOID; it is
    permitted only when no payment plan exists on the episode ... a void attempted while a
    plan exists is refused with ERR_CLAIM_HAS_PLAN (HTTP 409)."

    Design: Corner/validations/void_claim_with_plan_rejected
    """
    ctx = fixtures.setup_episode_with_submitted_claim(global_fee_cents=800000)
    ep_id = ctx["episode"]["id"]
    claim_id = ctx["claim"]["id"]
    # Plan on the estimate balance 160000.
    fixtures.create_plan(ep_id, 2)

    resp = api.void_claim(claim_id, BILLING)
    validate_error(resp, ApiErrorId.ERR_CLAIM_HAS_PLAN.value)


# ---- record_birth_without_in_use_booking_rejected ----
def test_record_birth_without_in_use_booking_rejected(api):
    """PRD §3.2: "First, the episode must have a booking that is currently IN_USE; without
    one the request is refused with ERR_NO_ACTIVE_BOOKING (HTTP 409)."

    Design: Corner/validations/record_birth_without_in_use_booking_rejected
    """
    ctx = fixtures.setup_active_episode()  # ACTIVE, risk LOW, no booking
    ep_id = ctx["episode"]["id"]
    resp = api.record_birth(ep_id, MIDWIFE)
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_BOOKING.value)
    ep = validate_success(api.get_episode(ep_id, MIDWIFE))
    assert ep["clinical_status"] == "ACTIVE", "unchanged"
