"""Visit recording, voiding, and the single-violation visit guards.

Difficulty queue (A): cross_entity_state_dependency (visit needs an ACTIVE term;
void needs an ACTIVE term), resource_temporal_overlap (half-open term window),
compensating_invariant (covered-visit and à-la-carte-visit void conservation).
Corner queue (B): isolated visit guards and the same-plan plan-change error.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_plan_with_services,
    create_clinic,
    create_account_and_membership,
    add_pet,
    activate_membership,
    record_visit,
    make_member_headers,
    plan_change_payload,
    first_active_term,
    get_term,
    list_term_credits,
    get_account,
    get_visit,
    TEST_USERS,
)

PLAN_ADMIN = TEST_USERS["plan_admin_headers"]
CLINIC_STAFF = TEST_USERS["clinic_staff_headers"]


def _plus_plan():
    plan, _ = create_plan_with_services(
        [{"service_code": "EXAM", "included_quantity": 2, "unit_value_cents": 6000}],
        tier="PLUS", name="Plus", monthly_fee_cents=4500, annual_value_cents=60000,
        alacarte_discount_pct=0.20, enrollment_fee_cents=0,
    )
    return plan


# ===========================================================================
# Difficulty: cross_entity_state_dependency
# ===========================================================================
def test_visit_on_pending_membership_no_active_term(api):
    """PRD §3.5: "If the membership has no `ACTIVE` term to debit — for instance because it is
    not currently `ENROLLED` — the visit is rejected with `ERR_NO_ACTIVE_TERM`."

    Design: Difficulty/cross_entity_state_dependency/visit_record_requires_membership_enrolled_active_term
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    pet = add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    # Deliberately NOT activated -> PENDING_PAYMENT, no ACTIVE term.

    res = api.record_visit(
        membership["id"],
        {"enrolled_pet_id": pet["id"], "clinic_id": clinic["id"], "service_code": "EXAM"},
        CLINIC_STAFF,
    )
    validate_error(res, "ERR_NO_ACTIVE_TERM")


def test_void_after_cancel_requires_active_term(api):
    """PRD §3.5: "Voiding is permitted only when the visit is `COMPLETED`, failing which it is
    rejected with `ERR_VISIT_NOT_VOIDABLE`, and only when the owning contract term is `ACTIVE`,
    failing which it is rejected with `ERR_TERM_NOT_ACTIVE_FOR_VOID`."

    Design: Difficulty/cross_entity_state_dependency/visit_void_requires_contract_term_active
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    pet = add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])
    visit = record_visit(membership["id"], pet["id"], clinic["id"], "EXAM")
    # Cancel -> owning term ACTIVE -> TERMINATED.
    api.cancel_membership(membership["id"], make_member_headers(account["id"]))

    res = api.void_visit(visit["id"], CLINIC_STAFF)
    validate_error(res, "ERR_TERM_NOT_ACTIVE_FOR_VOID")


# ===========================================================================
# Difficulty: resource_temporal_overlap (half-open term window)
# ===========================================================================
def test_visit_at_term_end_instant_outside_window(api):
    """PRD §3.5: "The visit instant must fall inside the active term's window, treated as
    inclusive of `starts_at` and exclusive of `ends_at`; a visit dated on or after the term
    end, or before the term start, is rejected with `ERR_VISIT_OUTSIDE_TERM`."

    Design: Difficulty/resource_temporal_overlap/visit_must_lie_in_half_open_contract_term_window
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(
        plan["id"], clinic["id"], billing_anchor_day=1, auto_renew=False
    )
    pet = add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])  # term [2026-01-01, 2027-01-01)
    set_clock("2027-01-01T00:00:00Z")  # exactly == ends_at -> outside (exclusive right edge)

    res = api.record_visit(
        membership["id"],
        {"enrolled_pet_id": pet["id"], "clinic_id": clinic["id"], "service_code": "EXAM"},
        CLINIC_STAFF,
    )
    validate_error(res, "ERR_VISIT_OUTSIDE_TERM")


# ===========================================================================
# Difficulty: compensating_invariant
# ===========================================================================
def test_void_covered_visit_conserves_consumed(api):
    """PRD §3.5: "If the visit had been covered by a credit, the system restores one unit to
    the bucket it consumed by decrementing that bucket's `consumed_quantity` by one, and if the
    bucket had been full it moves from `EXHAUSTED` back to `OPEN`."
    PRD §3.7: "The term's `entitlement_balance_cents` is then the term's
    `entitlement_granted_cents` minus the freshly recomputed consumed total."

    Design: Difficulty/compensating_invariant/void_covered_visit_conserves_entitlement_consumed
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    pet = add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])
    term = first_active_term(membership["id"])
    visit = record_visit(membership["id"], pet["id"], clinic["id"], "EXAM")

    validate_success(api.void_visit(visit["id"], CLINIC_STAFF), 200)

    term = get_term(term["id"])
    assert term["entitlement_consumed_cents"] == 0, (
        f"void of covered visit restores consumed to 0, got {term['entitlement_consumed_cents']}"
    )
    assert term["entitlement_balance_cents"] == 12000, (
        f"balance back to granted 12000, got {term['entitlement_balance_cents']}"
    )
    exam_credits = [c for c in list_term_credits(term["id"], service_code="EXAM")]
    assert exam_credits, "EXAM credit bucket must exist"
    bucket = exam_credits[0]
    assert bucket["consumed_quantity"] == 0
    assert bucket["status"] == "OPEN"


def test_void_alacarte_visit_conserves_wallet(api):
    """PRD §3.5: "If instead the visit had been billed à-la-carte, the system credits its
    `charged_cents` back to the member's `wallet_credit_cents`."
    PRD §3.5: "in that case the à-la-carte charge debits the member's `wallet_credit_cents`."

    Design: Difficulty/compensating_invariant/void_alacarte_visit_conserves_wallet_credit
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()  # EXAM 2@6000, discount 0.20
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    pet = add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    activate_membership(membership["id"], account["id"])  # wallet -4500
    record_visit(membership["id"], pet["id"], clinic["id"], "EXAM")  # covered
    record_visit(membership["id"], pet["id"], clinic["id"], "EXAM")  # covered
    v3 = record_visit(membership["id"], pet["id"], clinic["id"], "EXAM")  # à-la-carte 4800 -> -9300

    validate_success(api.void_visit(v3["id"], CLINIC_STAFF), 200)

    acct = get_account(account["id"])
    assert acct["wallet_credit_cents"] == -4500, (
        f"void of à-la-carte visit refunds 4800, wallet back to -4500, "
        f"got {acct['wallet_credit_cents']}"
    )
    assert get_visit(v3["id"])["status"] == "VOIDED"


# ===========================================================================
# Corner: validations (single isolated violations)
# ===========================================================================
def test_visit_foreign_pet_rejected(api):
    """PRD §3.5: "The pet named by `enrolled_pet_id` must belong to the membership in the
    path — its `membership_id` must equal the path membership — or the request is rejected with
    `ERR_PET_NOT_IN_MEMBERSHIP`."

    Design: Corner/validations/visit_for_foreign_pet_alone_returns_pet_not_in_membership
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    acct1, m1 = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    add_pet(m1["id"], acct1["id"], name="P1", species="DOG", weight_kg=12)
    activate_membership(m1["id"], acct1["id"])
    acct2, m2 = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    p2 = add_pet(m2["id"], acct2["id"], name="P2", species="DOG", weight_kg=12)
    activate_membership(m2["id"], acct2["id"])

    res = api.record_visit(
        m1["id"],
        {"enrolled_pet_id": p2["id"], "clinic_id": clinic["id"], "service_code": "EXAM"},
        CLINIC_STAFF,
    )
    validate_error(res, "ERR_PET_NOT_IN_MEMBERSHIP")


def test_visit_for_removed_pet_rejected(api):
    """PRD §3.5: "The pet must currently be `ENROLLED`, since suspended or removed pets cannot
    accrue visits, or the request is rejected with `ERR_PET_NOT_ACTIVE`."

    Design: Corner/validations/visit_pet_suspended_alone_returns_pet_not_active
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    p1 = add_pet(membership["id"], account["id"], name="P1", species="DOG", weight_kg=12)
    add_pet(membership["id"], account["id"], name="P2", species="CAT", weight_kg=5)
    activate_membership(membership["id"], account["id"])
    # Membership stays ENROLLED (still one active pet); remove P1 -> REMOVED.
    validate_success(api.remove_pet(membership["id"], p1["id"], make_member_headers(account["id"])), 200)

    res = api.record_visit(
        membership["id"],
        {"enrolled_pet_id": p1["id"], "clinic_id": clinic["id"], "service_code": "EXAM"},
        CLINIC_STAFF,
    )
    validate_error(res, "ERR_PET_NOT_ACTIVE")


def test_plan_change_to_same_plan_rejected(api):
    """PRD §3.6: "The target plan must differ from the membership's current plan and must
    itself be `ACTIVE`; a no-op target or a non-active target is rejected with
    `ERR_INVALID_PLAN_CHANGE`".

    Design: Corner/validations/plan_change_to_same_plan_returns_invalid_plan_change
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = _plus_plan()
    clinic = create_clinic(name="CA Clinic", region_code="CA")
    account, membership = create_account_and_membership(plan["id"], clinic["id"], billing_anchor_day=1)
    add_pet(membership["id"], account["id"], name="Rex", species="DOG", weight_kg=12)
    membership = activate_membership(membership["id"], account["id"])

    res = api.plan_change(
        membership["id"], plan_change_payload(plan["id"], membership["version"]),
        make_member_headers(account["id"]),
    )
    validate_error(res, "ERR_INVALID_PLAN_CHANGE")
