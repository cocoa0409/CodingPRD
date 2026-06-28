"""Corner coverage — endpoints (filtered list, amend recompute), errors (no payment method,
roster full), RBAC (forbidden role, ownership, unauthenticated), cross-cutting (OCC stale
version, trip-confirm fee cascade), and consistency (immediate visibility).

Queue B (Corner): sections `endpoints`, `errors`, `rbac`, `cross_cutting`, `consistency_model`.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    TEST_USERS, ApiErrorId, make_instructor_headers, make_parent_headers,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f

ADMIN_H = TEST_USERS["admin_headers"]
ANON_H = TEST_USERS["anonymous_headers"]


# =========================================================================
# endpoints
# =========================================================================
def test_list_sections_filtered_by_term(api):
    """PRD §2.3: "List endpoints accept two query parameters. The `limit` parameter caps the
    number of items returned ... Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    GET /sections?term_id=X returns an array containing the term's section with pagination meta.

    Design: Corner/endpoints/list_sections_filtered_by_term
    """
    term = fx.create_term()
    room = fx.create_room(capacity=10)
    instructor = fx.create_instructor()
    section = fx.create_section(term["id"], room["id"], instructor["id"], discipline="JAZZ")
    data, meta = validate_paginated(api.list_sections(ADMIN_H, params={"term_id": term["id"]}))
    ids = [s["id"] for s in data]
    assert section["id"] in ids
    assert "total_count" in meta
    assert "has_more" in meta


def test_amend_attendance_recomputes_makeup_eligible(api):
    """PRD §3.5: "An attendance row's `makeup_eligible` is true only when its `result` is
    `ABSENT_EXCUSED` and no makeup has yet been consumed against it; amending the `result`
    recomputes this flag."

    Amending PRESENT -> ABSENT_EXCUSED flips makeup_eligible to true.

    Design: Corner/endpoints/amend_attendance_recomputes_makeup_eligible
    """
    env = fx.setup_confirmed_enrollment()
    instr_headers = make_instructor_headers(env["instructor"]["id"])
    att = get_success_data(api.mark_attendance(
        env["enrollment"]["id"],
        f.mark_attendance_payload(env["session"]["id"], "2026-02-02", "PRESENT"), instr_headers))
    assert att["makeup_eligible"] is False
    amended = validate_success(api.amend_attendance(
        att["id"], {"result": "ABSENT_EXCUSED"}, instr_headers))
    assert amended["result"] == "ABSENT_EXCUSED"
    assert amended["makeup_eligible"] is True


# =========================================================================
# errors
# =========================================================================
def test_enable_autopay_without_payment_method_rejected(api):
    """PRD §3.1: "turning `autopay_enabled` on is refused with `ERR_NO_PAYMENT_METHOD` unless a
    method is already on file."
    PRD §3.1: "The patch endpoint also accepts an optional `expected_family_version`."

    Design: Corner/errors/no_payment_method_blocks_autopay
    """
    family = fx.create_family(email="npmfam@x.com", family_name="NPM")
    resp = api.patch_family(family["id"], {
        "autopay_enabled": True, "expected_family_version": family["version"]}, ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_NO_PAYMENT_METHOD.value)
    fam_after = validate_success(api.get_family(family["id"], ADMIN_H))
    assert fam_after["autopay_enabled"] is False


def test_roster_full_rejected(api):
    """PRD §3.7: "the add must not push `roster_count` above the team's `roster_cap` ... either
    violation is rejected with `ERR_ROSTER_FULL`."

    A team with roster_cap=1 already at roster_count 1: a 2nd add -> ERR_ROSTER_FULL.

    Design: Corner/errors/roster_full_rejected
    """
    team = fx.create_team(min_level="NOVICE", roster_cap=1)
    family = fx.create_family()
    s1 = fx.create_student(family["id"], full_name="RF1", level="ELITE")
    s2 = fx.create_student(family["id"], full_name="RF2", level="ELITE")
    m1 = get_success_data(api.create_membership(
        team["id"], f.create_membership_payload(s1["id"], team["version"]), ADMIN_H))
    team_v1 = m1.get("team_version") or validate_success(api.get_team(team["id"], ADMIN_H))["version"]
    resp = api.create_membership(
        team["id"], f.create_membership_payload(s2["id"], team_v1), ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_ROSTER_FULL.value)
    team_after = validate_success(api.get_team(team["id"], ADMIN_H))
    assert team_after["roster_count"] == 1


# =========================================================================
# rbac
# =========================================================================
def test_parent_cannot_generate_invoice(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the targeted endpoint
    is rejected with `ERR_FORBIDDEN_ROLE`."

    POST /invoices/generate is StudioAdmin-only; a Parent caller -> ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/parent_cannot_generate_invoice
    """
    family = fx.create_family(email="pcfam@x.com", family_name="PC")
    term = fx.create_term()
    resp = api.generate_invoice(
        f.generate_invoice_payload(family["id"], term["id"], "2026-02"),
        make_parent_headers(family["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_parent_cannot_act_on_other_family(api):
    """PRD §2.1: "a `Parent` may only act on a `Student`, `Enrollment`, `SeatAssignment`,
    `CostumeOrder`, `Invoice`, or `Family` whose owning family is their own; an attempt to act on
    another household's resource is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Parent of F1 adding a student under F2's collection -> ERR_NOT_RESOURCE_OWNER.

    Design: Corner/rbac/parent_cannot_act_on_other_family_student
    """
    f1 = fx.create_family(email="f1own@x.com", family_name="F1")
    f2 = fx.create_family(email="f2own@x.com", family_name="F2")
    resp = api.create_student(
        f2["id"], f.create_student_payload(full_name="Sneaky", level="ELITE"),
        make_parent_headers(f1["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "A request that omits `X-User-Role`, or carries a value outside this set, is
    rejected with `ERR_UNAUTHENTICATED`. The `Anonymous` role is accepted only on the family
    self-registration endpoint; everywhere else an `Anonymous` (or header-less) request is
    unauthenticated."

    POST /terms by an Anonymous caller (not the self-registration endpoint) -> ERR_UNAUTHENTICATED.

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    resp = api.create_term(f.create_term_payload(name="NoAuth"), ANON_H)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# =========================================================================
# cross_cutting
# =========================================================================
def test_stale_recital_version_on_second_seat_hold(api):
    """PRD §2.8: "A seat-hold request against a recital must carry `expected_recital_version`, and
    that value must equal the target `Recital`'s current `version`. If another writer has held a
    seat since the client last read the recital ... the hold is rejected with `ERR_STALE_VERSION`
    (HTTP 412). A successful hold increments the recital's `version` by one."

    After one hold advances the recital version, a second hold carrying the pre-advance
    expected_recital_version -> ERR_STALE_VERSION.

    Design: Corner/cross_cutting/occ_stale_recital_version_on_seat_hold
    """
    base = fx.setup_recital_on_sale(recital_overrides={
        "total_seats": 5, "ticket_price_cents": 2000, "free_tickets_per_family": 0})
    family = fx.create_family()
    stale_version = base["recital_version"]
    get_success_data(api.hold_seat(
        base["recital"]["id"],
        f.hold_seat_payload(family["id"], "A-1", stale_version), ADMIN_H))
    resp = api.hold_seat(
        base["recital"]["id"],
        f.hold_seat_payload(family["id"], "A-2", stale_version), ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    recital_after = validate_success(api.get_recital(base["recital"]["id"], ADMIN_H))
    assert recital_after["seats_sold"] == 1


def test_stale_team_version_on_second_roster_add(api):
    """PRD §2.8: "a team-membership add must carry `expected_team_version`, which must equal the
    target `CompetitionTeam`'s current `version`. If another writer has rostered a student since
    the client last read the team ... the add is rejected with `ERR_STALE_VERSION` (HTTP 412). A
    successful roster add increments the team's `version` by one."

    After one membership add advances the team version, a second add carrying the pre-advance
    expected_team_version -> ERR_STALE_VERSION.

    Design: Corner/cross_cutting/occ_stale_team_version_on_roster_add
    """
    team = fx.create_team(min_level="NOVICE", roster_cap=5)
    family = fx.create_family()
    s1 = fx.create_student(family["id"], full_name="OT1", level="ELITE")
    s2 = fx.create_student(family["id"], full_name="OT2", level="ELITE")
    stale_version = team["version"]
    get_success_data(api.create_membership(
        team["id"], f.create_membership_payload(s1["id"], stale_version), ADMIN_H))
    resp = api.create_membership(
        team["id"], f.create_membership_payload(s2["id"], stale_version), ADMIN_H)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    team_after = validate_success(api.get_team(team["id"], ADMIN_H))
    assert team_after["roster_count"] == 1


def test_trip_confirm_charges_family_invoice(api):
    """PRD §3.7: "On confirmation the trip moves to `CONFIRMED` and each `GOING` participant's
    `per_member_cost_cents` is added as a fee line to that participant's family's open invoice."

    Confirming a trip with per_member_cost 30000 and one GOING participant adds 30000 to that
    family's OPEN invoice fees_cents.

    Design: Corner/cross_cutting/trip_confirm_charges_each_family_cascade
    """
    env = fx.setup_confirmed_enrollment()
    family = env["family"]
    student = env["student"]
    invoice = fx.generate_invoice(family["id"], env["term"]["id"], "2026-02")
    team = fx.create_team(min_level="NOVICE", roster_cap=5)
    membership = get_success_data(api.create_membership(
        team["id"], f.create_membership_payload(student["id"], team["version"]), ADMIN_H))
    get_success_data(api.lock_team(team["id"], ADMIN_H))
    trip = get_success_data(api.create_trip(
        team["id"], f.create_trip_payload(destination="Worlds", per_member_cost_cents=30000,
                                          chaperone_ratio=4, chaperone_count=1), ADMIN_H))
    get_success_data(api.create_participant(
        trip["id"], f.create_participant_payload(membership["id"]), ADMIN_H))
    trip_after = validate_success(api.confirm_trip(trip["id"], ADMIN_H))
    assert trip_after["status"] == "CONFIRMED"
    invoice_after = validate_success(api.get_invoice(invoice["id"], ADMIN_H))
    assert invoice_after["fees_cents"] == 30000


# =========================================================================
# consistency_model
# =========================================================================
def test_enrolled_count_immediately_visible_after_confirm(api):
    """PRD §2.6: "A confirmed enrollment increments its section's `enrolled_count` ... Discount
    tiers, waitlist ranks, and family statuses are likewise recomputed in the same request that
    disturbs them."
    PRD §2.1 (intro §1): "the system treats every mutation as immediately consistent: derived
    counts, discount-adjusted charges, family wallet balances, and parent/child statuses are
    reconciled within the same request that triggers them, never deferred to a later sweep."

    After a confirm, an immediate GET /sections/{id} reflects enrolled_count == 1.

    Design: Corner/consistency_model/immediate_visibility_of_enrolled_count
    """
    env = fx.setup_confirmed_enrollment(section_overrides={"capacity_cap": 20})
    section_after = validate_success(api.get_section(env["section"]["id"], ADMIN_H))
    assert section_after["enrolled_count"] == 1
    assert section_after["status"] == "OPEN"
