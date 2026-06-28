"""Role-based access control denials, ownership enforcement, missing-auth handling,
and the workshop FULL->OPEN bubble-up on withdrawal.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_tier,
    register_member,
    create_certification_for,
    setup_member_machine_cert,
    create_held_reservation,
    setup_workshop,
    enroll_member,
    make_member_headers,
    make_staff_headers,
)

MAKER_TIER = {
    "code": "MAKER", "name": "Maker", "billing_mode": "MONTHLY",
    "monthly_fee_cents": 0, "discount_bps": 1000, "prepaid_machine_minutes": 0,
    "locker_free_liters": 50, "unsupervised_allowed": True,
}
LASER_MACHINE = {
    "machine_class": "LASER", "hourly_rate_cents": 4800, "setup_fee_cents": 500,
    "min_billing_minutes": 30, "cooldown_minutes": 15, "requires_certification": True,
}


# ===========================================================================
# Corner / rbac / member_cannot_create_machine_returns_403
# ===========================================================================
def test_member_cannot_create_machine_returns_403(api):
    """PRD §2.1: "When an authenticated caller invokes an operation their role is not
    permitted to perform — or an ownership-bound role acts on a resource it does not
    own — the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: machine creation is authorized for FacilityAdmin only.

    A Member calling POST /machines is rejected.

    Design: Corner/rbac/member_cannot_create_machine_returns_403
    """
    tier = create_tier(**MAKER_TIER)
    member = register_member(tier["id"])
    validate_error(
        api.create_machine(
            {"name": "Sneaky", "machine_class": "LASER", "hourly_rate_cents": 4800},
            make_member_headers(member["id"]),
        ),
        ApiErrorId.ERR_FORBIDDEN.value,
    )


# ===========================================================================
# Corner / rbac / member_cannot_revoke_certification_returns_403
# ===========================================================================
def test_member_cannot_revoke_certification_returns_403(api):
    """PRD §2.1: "When an authenticated caller invokes an operation their role is not
    permitted to perform ... the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: certification revoke is authorized for StaffInstructor (and FacilityAdmin).

    A Member calling POST /certifications/{id}/revoke is rejected.

    Design: Corner/rbac/member_cannot_revoke_certification_returns_403
    """
    tier = create_tier(**MAKER_TIER)
    member = register_member(tier["id"])
    cert = create_certification_for(member["id"], "LASER")
    validate_error(
        api.revoke_certification(cert["id"], make_member_headers(member["id"])),
        ApiErrorId.ERR_FORBIDDEN.value,
    )


# ===========================================================================
# Corner / rbac / member_cannot_act_on_other_members_reservation_returns_403
# ===========================================================================
def test_member_cannot_cancel_other_members_reservation_returns_403(api):
    """PRD §2.1: "A member may act only on their own subscription, reservations,
    lockers, purchases, and enrollments."
    PRD §2.1: "ownership checks on any resource that references a member compare that
    resource's member foreign key (for example, a reservation's `member_id` ...) to
    `X-User-ID`."

    Member B cancelling Member A's reservation is rejected with ERR_FORBIDDEN.

    Design: Corner/rbac/member_cannot_act_on_other_members_reservation_returns_403
    """
    member_a, machine, cert = setup_member_machine_cert(
        machine_class="LASER", tier_overrides=MAKER_TIER, machine_overrides=LASER_MACHINE,
        topup_cents=10000,
    )
    res = create_held_reservation(
        member_a, machine, cert, "2026-05-29T10:00:00Z", "2026-05-29T11:00:00Z"
    )
    # A different member B acts on A's reservation.
    tier_b = create_tier(code="MAKERB", name="MakerB")
    member_b = register_member(tier_b["id"])
    validate_error(
        api.cancel_reservation(res["id"], make_member_headers(member_b["id"])),
        ApiErrorId.ERR_FORBIDDEN.value,
    )


# ===========================================================================
# Corner / rbac / missing_role_header_returns_401
# ===========================================================================
def test_missing_role_header_returns_401(api, admin_headers):
    """PRD §2.1: "A request missing either header, or carrying an `X-User-Role` that
    is not one of the three recognized roles, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    A GET /machines/{id} with no X-User-Role header is rejected.

    Design: Corner/rbac/missing_role_header_returns_401
    """
    from test_helpers import create_machine
    machine = create_machine(name="Laser Q", machine_class="LASER", hourly_rate_cents=4800)
    no_role = {"X-User-ID": "someone", "Content-Type": "application/json"}
    validate_error(
        api.get_machine(machine["id"], no_role), ApiErrorId.ERR_UNAUTHENTICATED.value
    )


# ===========================================================================
# Corner / state_machines / workshop_full_then_open_on_withdraw_bubble_up
# ===========================================================================
def test_workshop_full_then_open_on_withdraw(api):
    """PRD §3.9: "Creating an enrollment increments the workshop's `enrolled_count`,
    and when that count reaches `capacity` the workshop auto-transitions from `OPEN`
    to `FULL`."
    PRD §3.9: "Withdrawing — a member action — is permitted only while the parent
    workshop is `OPEN` or `FULL`, moves the enrollment to `WITHDRAWN`, decrements the
    workshop's `enrolled_count`, and, when the workshop was `FULL` and the count now
    falls below `capacity`, bubbles the workshop back from `FULL` to `OPEN`."

    A capacity-1 workshop becomes FULL on the first enrollment; a withdrawal returns
    it to OPEN with enrolled_count 0.

    Design: Corner/state_machines/workshop_full_then_open_on_withdraw_bubble_up
    """
    tier = create_tier(**MAKER_TIER)
    instructor = register_member(tier["id"])
    student = register_member(tier["id"])
    _, ws = setup_workshop(
        instructor_id=instructor["id"], capacity=1, starts_at="2026-05-20T09:00:00Z"
    )
    enr = enroll_member(ws["id"], student["id"])
    sh = make_staff_headers(instructor["id"])
    ws_full = validate_success(api.get_workshop(ws["id"], sh))
    assert ws_full["status"] == "FULL", ws_full["status"]
    withdrawn = validate_success(
        api.withdraw_enrollment(enr["id"], make_member_headers(student["id"]))
    )
    assert withdrawn["status"] == "WITHDRAWN"
    ws_after = validate_success(api.get_workshop(ws["id"], sh))
    assert ws_after["status"] == "OPEN", ws_after["status"]
    assert ws_after["enrolled_count"] == 0, ws_after["enrolled_count"]
