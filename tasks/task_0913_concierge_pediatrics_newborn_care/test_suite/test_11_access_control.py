"""Identity, role authorisation, ownership and not-found routing."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    create_child,
    create_family,
    create_family_payload,
    create_membership_payload,
    create_physician,
    create_waitlist_entry_payload,
    enroll,
    issue_and_pay,
    make_parent_headers,
    make_physician_headers,
    open_encounter,
    set_clock,
    setup_household,
    setup_practice,
    validate_error,
    validate_paginated,
    validate_success,
    well_visit_for,
)

ADMIN = TEST_USERS["admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]

UNKNOWN_CHILD_ID = "33333333-3333-4333-8333-333333333333"
UNKNOWN_PLAN_ID = "44444444-4444-4444-8444-444444444444"
UNKNOWN_PHYSICIAN_ID = "55555555-5555-4555-8555-555555555555"
UNKNOWN_INVOICE_ID = "66666666-6666-4666-8666-666666666666"


# ==========================================================================
# Authentication and role authorisation
# ==========================================================================


def test_a_request_without_a_role_header_is_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, naming the caller,
    and `X-User-Role`, naming the capacity the caller acts in. If either header is
    missing, or if `X-User-Role` carries a value outside the five declared roles, the
    request is rejected with `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/rbac/corner_request_without_x_user_role_header_returns_unauthenticated
    """
    set_clock("2026-05-01T00:00:00Z")
    payload = create_family_payload(
        household_name="Headerless", family_monthly_cap_cents=100000
    )

    headerless = api.post(
        "/peds/families",
        json=payload,
        headers={"X-User-ID": "operator-1", "Content-Type": "application/json"},
    )
    validate_error(headerless, ApiErrorId.ERR_UNAUTHENTICATED)
    assert headerless.status_code == 401

    undeclared_role = api.post(
        "/peds/families",
        json=payload,
        headers={
            "X-User-ID": "operator-1",
            "X-User-Role": "Janitor",
            "Content-Type": "application/json",
        },
    )
    validate_error(undeclared_role, ApiErrorId.ERR_UNAUTHENTICATED)
    assert undeclared_role.status_code == 401

    accepted = api.create_family(payload, ADMIN)
    validate_success(accepted, 201)


def test_a_parent_may_not_enrol_a_membership(api):
    """PRD §2.1: "A caller whose role is recognised but is not listed among the authorised
    roles for the endpoint it is calling is rejected with `ERR_FORBIDDEN_ROLE` (403)."
    PRD §2.7: "**Role authorisation.** The acting role appears in the endpoint's
    authorised-role list in §4 — otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to every
    endpoint."

    Design: Corner/rbac/corner_parent_cannot_enroll_a_membership_returns_forbidden_role
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z")
    household = setup_household(household_name="Yamada", child_first_name="Haru")
    family, child = household["family"], household["child"]

    resp = api.create_membership(
        create_membership_payload(
            child["id"],
            practice["plan"]["id"],
            practice["physician"]["id"],
            "2026-06-01",
            family["version"],
        ),
        make_parent_headers(family["id"]),
    )
    error = validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert resp.status_code == 403
    assert error["error_id"] != ApiErrorId.ERR_NOT_RESOURCE_OWNER.value

    _, meta = validate_paginated(
        api.list_memberships(ADMIN, params={"family_id": family["id"]})
    )
    assert meta["total_count"] == 0


def test_a_care_coordinator_may_not_submit_encounter_billing(api):
    """PRD §2.1: "A caller whose role is recognised but is not listed among the authorised
    roles for the endpoint it is calling is rejected with `ERR_FORBIDDEN_ROLE` (403)."
    PRD §3.6: "On the billing axis, a `BillingSpecialist` or `PracticeAdmin` submits the
    charges, moving the encounter `BILLING_PENDING → BILLING_ROUTED`."

    Design: Corner/rbac/corner_care_coordinator_cannot_submit_billing_returns_forbidden_role
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z")
    household = setup_household(household_name="Zubair", child_first_name="Rida")
    membership = enroll(
        household["child"]["id"],
        practice["plan"]["id"],
        practice["physician"]["id"],
        "2026-06-01",
        household["family"]["id"],
    )
    issue_and_pay(household["family"]["id"])
    set_clock("2026-06-15T20:00:00Z")

    encounter = open_encounter(membership["id"], "2026-06-15T10:00:00Z")

    resp = api.submit_encounter_billing(encounter["id"], COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert resp.status_code == 403

    unchanged = validate_success(api.get_encounter(encounter["id"], BILLING))
    assert unchanged["billing_status"] == "BILLING_PENDING"

    _, meta = validate_paginated(
        api.list_service_lines(BILLING, params={"encounter_id": encounter["id"]})
    )
    assert meta["total_count"] == 0


# ==========================================================================
# Ownership
# ==========================================================================


def test_a_parent_may_not_read_another_households_child(api):
    """PRD §2.1: "**Ownership enforcement.** A `Parent` may only reach resources belonging
    to their own household. The household is reached from the target resource by whichever
    path exists: a child's `family_id`, a membership's `family_id`, or — for a consult
    booking, encounter, form request, invoice, service line or panel waitlist entry — the
    household of the membership (or, for an invoice, the household named directly on the
    row) that the resource belongs to. If the household so reached is not the caller's own
    `X-User-ID`, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (403)."
    PRD §2.1: "When `X-User-Role` is `Parent`, `X-User-ID` is the `id` of the acting Family
    row; ownership checks on any resource that reaches a household compare that
    household's identifier to `X-User-ID`."

    Design: Corner/rbac/corner_parent_reading_another_household_returns_not_resource_owner
    """
    set_clock("2026-06-01T00:00:00Z")
    f1 = create_family(household_name="Ahmadi")
    child_a = create_child(f1["id"], first_name="Sara", date_of_birth="2026-04-01")
    f2 = create_family(household_name="Boateng")
    child_b = create_child(f2["id"], first_name="Kojo", date_of_birth="2026-04-01")

    outsider = make_parent_headers(f2["id"])

    cross = api.get_child(child_a["id"], outsider)
    validate_error(cross, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert cross.status_code == 403

    own = validate_success(api.get_child(child_b["id"], outsider))
    assert own["id"] == child_b["id"]

    as_admin = validate_success(api.get_child(child_a["id"], ADMIN))
    assert as_admin["id"] == child_a["id"], (
        "the denial is identity-scoped, not a missing route"
    )


def test_a_physician_may_not_complete_another_panels_well_visit(api):
    """PRD §2.1: "A `Physician` is subject to the same rung on four clinical writes only —
    completing a well visit, completing the clinical axis of an encounter, cancelling an
    encounter, and issuing a form request — where the targeted membership's `physician_id`
    must equal `X-User-ID`, failing which the rejection is again `ERR_NOT_RESOURCE_OWNER`
    (403)."
    PRD §3.5: "On success the visit records its `completed_date`, classifies
    `punctuality`, and produces a service line: `service_code` `WELL_VISIT`, route
    `COVERED_BY_MEMBERSHIP`, `billed_amount_cents` 22 000, `membership_covered_cents`
    22 000, `patient_responsibility_cents` 0, carrying the `well_visit_id` of the visit
    and created directly in status `SETTLED`."

    Design: Corner/rbac/corner_physician_completing_another_panels_well_visit_returns_not_resource_owner
    """
    practice = setup_practice(clock="2026-05-24T09:00:00Z", physician_name="Dr One")
    doc1 = practice["physician"]
    doc2 = create_physician(full_name="Dr Two", panel_slot_cap=20.0, licensed_state_codes=["CA"])

    household = setup_household(
        household_name="Cisse", child_first_name="Aminata", date_of_birth="2026-04-01"
    )
    membership = enroll(
        household["child"]["id"],
        practice["plan"]["id"],
        doc1["id"],
        "2026-05-24",
        household["family"]["id"],
    )
    issue_and_pay(household["family"]["id"])

    visit = well_visit_for(membership["id"], "M2")

    intruder = api.complete_well_visit(
        visit["id"], {"completed_date": "2026-05-24"}, make_physician_headers(doc2["id"])
    )
    validate_error(intruder, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert intruder.status_code == 403

    untouched = validate_success(api.get_well_visit(visit["id"], COORDINATOR))
    assert untouched["status"] == "DUE"
    assert untouched["completed_date"] is None

    owner = validate_success(
        api.complete_well_visit(
            visit["id"], {"completed_date": "2026-05-24"}, make_physician_headers(doc1["id"])
        )
    )
    assert owner["status"] == "COMPLETED"
    assert owner["punctuality"] == "ON_SCHEDULE"

    _, meta = validate_paginated(
        api.list_service_lines(BILLING, params={"well_visit_id": visit["id"]})
    )
    assert meta["total_count"] == 1


# ==========================================================================
# Not-found routing and pagination limits
# ==========================================================================


def test_enrolling_an_unknown_child_returns_child_not_found(api):
    """PRD §2.7: "`child_id` is checked on membership creation, waitlist-entry creation and
    immunization-dose creation (`ERR_CHILD_NOT_FOUND`)."
    PRD §2.6: "A child yields `ERR_CHILD_NOT_FOUND`."

    Design: Corner/errors/corner_enroll_with_unknown_child_id_returns_child_not_found
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z")
    family = create_family(household_name="Ustinov")

    resp = api.create_membership(
        create_membership_payload(
            UNKNOWN_CHILD_ID,
            practice["plan"]["id"],
            practice["physician"]["id"],
            "2026-06-01",
            family["version"],
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_CHILD_NOT_FOUND)
    assert resp.status_code == 404


def test_enrolling_on_an_unknown_plan_returns_plan_not_found(api):
    """PRD §2.7: "`plan_id` on membership creation and `requested_plan_id` on
    waitlist-entry creation are checked against the plan collection
    (`ERR_PLAN_NOT_FOUND`)."
    PRD §2.6: "A plan tier yields `ERR_PLAN_NOT_FOUND`, covering both `plan_id` and
    `requested_plan_id`."

    Design: Corner/errors/corner_enroll_with_unknown_plan_id_returns_plan_not_found
    """
    set_clock("2026-06-01T00:00:00Z")
    physician = create_physician()
    household = setup_household(household_name="Varga", child_first_name="Zsofi")

    resp = api.create_membership(
        create_membership_payload(
            household["child"]["id"],
            UNKNOWN_PLAN_ID,
            physician["id"],
            "2026-06-01",
            household["family"]["version"],
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_FOUND)
    assert resp.status_code == 404

    _, meta = validate_paginated(
        api.list_memberships(ADMIN, params={"child_id": household["child"]["id"]})
    )
    assert meta["total_count"] == 0


def test_queueing_for_an_unknown_physician_returns_physician_not_found(api):
    """PRD §2.7: "`physician_id` on membership creation and waitlist-entry creation, and
    `consultant_physician_id` on consult-booking creation, are checked against the
    physician collection (`ERR_PHYSICIAN_NOT_FOUND`)."
    PRD §2.6: "A physician yields `ERR_PHYSICIAN_NOT_FOUND` — this covers `physician_id`
    and `consultant_physician_id` alike."

    Design: Corner/errors/corner_waitlist_with_unknown_physician_id_returns_physician_not_found
    """
    set_clock("2026-06-01T00:00:00Z")
    practice_plan = validate_success(
        api.create_membership_plan(
            {
                "tier": "PLUS",
                "monthly_rate_cents": 40000,
                "included_lactation_consults": 3,
                "included_sleep_consults": 2,
                "form_sla_hours": 72,
                "after_hours_surcharge_waived": False,
                "overage_consult_fee_cents": 15000,
            },
            ADMIN,
        ),
        201,
    )
    household = setup_household(household_name="Wu", child_first_name="Lan")

    resp = api.create_waitlist_entry(
        create_waitlist_entry_payload(
            UNKNOWN_PHYSICIAN_ID, household["child"]["id"], practice_plan["id"]
        ),
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_PHYSICIAN_NOT_FOUND)
    assert resp.status_code == 404

    _, meta = validate_paginated(
        api.list_waitlist_entries(COORDINATOR, params={"child_id": household["child"]["id"]})
    )
    assert meta["total_count"] == 0


def test_reading_an_unknown_invoice_returns_the_generic_not_found(api):
    """PRD §2.6: "Everything else — an insurance policy, panel waitlist entry, entitlement
    grant, consult booking, well visit, immunization dose, encounter, service line,
    invoice or form request — yields the generic `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/errors/corner_get_unknown_invoice_returns_resource_not_found
    """
    set_clock("2026-05-01T00:00:00Z")

    resp = api.get_invoice(UNKNOWN_INVOICE_ID, BILLING)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)
    assert resp.status_code == 404


def test_a_limit_above_one_hundred_is_rejected_rather_than_clamped(api):
    """PRD §2.3: "`limit` caps how many rows the page returns; it defaults to 10, may be no
    smaller than 1 and no larger than 100."
    PRD §2.3: "A `limit` below 1 or above 100, or a negative `offset`, is rejected with
    `ERR_VALIDATION` (400)."

    Design: Corner/validations/corner_list_children_with_limit_above_max_returns_invalid_request
    """
    set_clock("2026-06-01T00:00:00Z")
    family = create_family(household_name="Nasser")
    create_child(family["id"], first_name="Sami", date_of_birth="2026-01-01")

    resp = api.list_children(COORDINATOR, params={"family_id": family["id"], "limit": 500})
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    assert resp.status_code == 400

    ok = api.list_children(COORDINATOR, params={"family_id": family["id"], "limit": 100})
    rows, meta = validate_paginated(ok)
    assert len(rows) == 1 and meta["total_count"] == 1


def test_the_logical_clock_may_not_be_moved_backwards(api):
    """PRD §2.4: "The clock may only move forward or stand still: a `to_iso8601` value
    earlier than the clock's present value is rejected with `ERR_INVALID_DATE_RANGE`
    (400)."
    PRD §2.4: "A `PracticeAdmin` moves it by supplying a `to_iso8601` instant; the response
    reports the new setting as `current_utc`."

    Design: Corner/validations/corner_moving_the_clock_backwards_returns_invalid_date_range
    """
    forward = validate_success(
        api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, ADMIN)
    )
    assert forward["current_utc"] is not None

    backwards = api.set_clock({"to_iso8601": "2026-05-15T00:00:00Z"}, ADMIN)
    validate_error(backwards, ApiErrorId.ERR_INVALID_DATE_RANGE)
    assert backwards.status_code == 400

    standing_still = validate_success(
        api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, ADMIN)
    )
    assert_instant_equals(
        standing_still["current_utc"], "2026-06-01T00:00:00.000Z", "clock.current_utc"
    )
