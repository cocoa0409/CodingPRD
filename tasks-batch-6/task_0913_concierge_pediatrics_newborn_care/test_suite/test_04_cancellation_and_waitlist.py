"""Leaving the panel: the cancellation fan-out and the promotion chain."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_date_equals,
    assert_grant_conservation,
    assert_waitlist_entry,
    book_consult,
    create_child,
    create_family,
    create_waitlist_entry_payload,
    enroll,
    family_version,
    find_invoice,
    get_grant,
    get_invoice,
    get_membership,
    get_physician,
    get_waitlist_entry,
    grants_for,
    memberships_where,
    panel_summary,
    queue_for_panel,
    request_form,
    set_clock,
    setup_active_membership,
    setup_practice,
    validate_error,
    validate_paginated,
    validate_success,
    well_visit_for,
    well_visits_for,
    complete_well_visit,
    service_lines_for_membership,
)

ADMIN = TEST_USERS["admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]


def _promotion_scenario():
    """A full panel with two waiting entries, the earlier one needing less weight."""
    practice = setup_practice(clock="2026-06-01T00:00:00Z", panel_slot_cap=4.0)
    plan_id, doc_id = practice["plan"]["id"], practice["physician"]["id"]

    f1 = create_family(household_name="F1 Hale", family_monthly_cap_cents=100000)
    child_a = create_child(f1["id"], first_name="Ann", date_of_birth="2026-03-01")
    mem_a = enroll(child_a["id"], plan_id, doc_id, "2026-06-01", f1["id"])

    f2 = create_family(household_name="F2 Iyer", family_monthly_cap_cents=100000)
    child_b = create_child(f2["id"], first_name="Bo", date_of_birth="2026-02-01")
    mem_b = enroll(child_b["id"], plan_id, doc_id, "2026-06-01", f2["id"])

    f3 = create_family(household_name="F3 Jung", family_monthly_cap_cents=100000)
    child_c = create_child(f3["id"], first_name="Cai", date_of_birth="2022-06-01")
    e1 = queue_for_panel(doc_id, child_c["id"], plan_id)

    f4 = create_family(household_name="F4 Kaur", family_monthly_cap_cents=100000)
    child_d = create_child(f4["id"], first_name="Dev", date_of_birth="2026-04-01")
    e2 = queue_for_panel(doc_id, child_d["id"], plan_id)

    return {
        "plan_id": plan_id,
        "doc_id": doc_id,
        "f1": f1, "f2": f2, "f3": f3, "f4": f4,
        "child_c": child_c,
        "mem_a": mem_a, "mem_b": mem_b,
        "e1": e1, "e2": e2,
    }


def test_cancellation_frees_weight_and_promotes_the_first_fitting_entry(api):
    """PRD §3.4: "**Hop two — the promotion selector runs.** Because free weight appeared,
    the service examines the panel waitlist entries for that physician whose status is
    `WAITING`, ordered by `created_at` ascending, and promotes the **first** entry whose
    `candidate_slot_weight` is less than or equal to the physician's newly recomputed
    `available_panel_weight`."
    PRD §3.4: "Exactly one entry is promoted per cancellation, even when the freed weight
    would comfortably have accommodated two."
    PRD §3.4: "**Hop three — a membership is created.** Because an entry was promoted, a
    new membership is created for that entry's `child_id` on the `requested_plan_id` the
    entry recorded and on the same `physician_id`, with `start_date` set to today's date
    and status `PENDING_ACTIVATION`."

    Design: Difficulty/transitive_cascade/membership_cancel_frees_weight_promotes_waitlist_and_seeds_new_membership
    """
    s = _promotion_scenario()

    cancelled = validate_success(
        api.cancel_membership(
            s["mem_a"]["id"],
            {"effective_date": "2026-06-01", "expected_family_version": family_version(s["f1"]["id"])},
            ADMIN,
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert_date_equals(
        cancelled["cancellation_effective_date"], "2026-06-01", "cancellation_effective_date"
    )
    assert float(cancelled["slot_weight"]) == 0.0

    panel = panel_summary(s["doc_id"])
    assert float(panel["weighted_occupancy"]) == 3.0
    assert float(panel["available_panel_weight"]) == 1.0

    e1 = get_waitlist_entry(s["e1"]["id"])
    e2 = get_waitlist_entry(s["e2"]["id"])
    assert_waitlist_entry(e1)
    assert e1["status"] == "PROMOTED"
    assert e2["status"] == "WAITING", (
        "only one entry is promoted per cancellation, even though 2.0 was released"
    )

    promoted = memberships_where(child_id=s["child_c"]["id"])
    assert len(promoted) == 1
    mem_c = promoted[0]
    assert mem_c["status"] == "PENDING_ACTIVATION"
    assert mem_c["plan_id"] == s["plan_id"]
    assert mem_c["physician_id"] == s["doc_id"]
    assert_date_equals(mem_c["start_date"], "2026-06-01", "Membership.start_date")
    assert e1["promoted_membership_id"] == mem_c["id"]


def test_promoted_membership_grows_its_own_grants_visits_and_invoice(api):
    """PRD §3.4: "**Hop four — the new membership's scaffolding appears.** Because a
    membership was created, its two entitlement grants are generated — one per benefit
    type at `membership_year_index` 0 — and its well-visit rows are generated under the
    periodicity rules of §3.5. The promoted child's household then gains a `DRAFT`
    invoice for the current cycle if it had none, or has its existing draft recomputed if
    it did, so that the new enrolment-prorated line appears on it."
    PRD §3.4: "**Draft invoices are rebuilt.** Every invoice of that household still in
    `DRAFT` is recomputed under §3.3, using the cancellation proration shape for the
    departing membership's own line."

    Design: Difficulty/transitive_cascade/membership_cancel_frees_weight_promotes_waitlist_and_seeds_new_membership
    """
    s = _promotion_scenario()

    validate_success(
        api.cancel_membership(
            s["mem_a"]["id"],
            {"effective_date": "2026-06-01", "expected_family_version": family_version(s["f1"]["id"])},
            ADMIN,
        )
    )

    mem_c = memberships_where(child_id=s["child_c"]["id"])[0]

    grants = grants_for(mem_c["id"])
    assert len(grants) == 2
    by_type = {g["benefit_type"]: g for g in grants}
    assert by_type["LACTATION_CONSULT"]["granted_count"] == 3
    assert by_type["SLEEP_CONSULT"]["granted_count"] == 2
    assert all(g["membership_year_index"] == 0 and g["status"] == "OPEN" for g in grants)

    visits = well_visits_for(mem_c["id"])
    assert sorted(v["milestone_code"] for v in visits) == ["M48", "M60"]
    assert all(v["status"] == "DUE" for v in visits)

    f3_invoices, meta = validate_paginated(
        api.list_invoices(BILLING, params={"family_id": s["f3"]["id"]})
    )
    assert meta["total_count"] == 1
    assert f3_invoices[0]["status"] == "DRAFT"
    assert_date_equals(f3_invoices[0]["cycle_start_date"], "2026-06-01", "cycle_start_date")
    assert f3_invoices[0]["total_cents"] == 40000

    f1_invoice = find_invoice(s["f1"]["id"])
    assert f1_invoice["status"] == "DRAFT"
    assert len(f1_invoice["lines"]) == 1
    assert f1_invoice["lines"][0]["covered_days"] == 1
    assert f1_invoice["lines"][0]["prorated_cents"] == 1333
    assert f1_invoice["subtotal_cents"] == 1333
    assert f1_invoice["total_cents"] == 1333

    other_family_membership = get_membership(s["mem_b"]["id"])
    assert other_family_membership["enrollment_sequence"] == 1, (
        "a different family's ladder is untouched"
    )


def test_cancellation_expires_benefit_pools_and_cancels_held_bookings(api):
    """PRD §3.4: "**Benefit pools expire.** Every entitlement grant of that membership
    currently in `OPEN` or `EXHAUSTED` transitions to `EXPIRED`. Units already burned are
    not given back: `consumed_count` is preserved exactly as it stood, while
    `booked_count` is driven to 0 as the held bookings cancel underneath it."
    PRD §3.4: "**Scheduled consults are cancelled.** Every consult booking of that
    membership still in `SCHEDULED` transitions to `CANCELLED`, which releases its
    entitlement hold in the ordinary way described in §3.8."

    Design: Corner/state_machines/corner_entitlement_grants_expire_when_membership_cancels
    """
    scenario = setup_active_membership(clock="2026-06-01T00:00:00Z", household_name="Traore")
    membership, doc, family = scenario["membership"], scenario["physician"], scenario["family"]

    booking = book_consult(
        membership["id"], doc["id"], "2026-06-20T09:00:00Z", "2026-06-20T09:45:00Z"
    )
    grant_id = booking["grant_id"]

    cancelled = validate_success(
        api.cancel_membership(
            membership["id"],
            {"effective_date": "2026-06-01", "expected_family_version": family_version(family["id"])},
            ADMIN,
        )
    )
    assert cancelled["status"] == "CANCELLED"

    assert validate_success(api.get_consult_booking(booking["id"], COORDINATOR))["status"] == "CANCELLED"

    grant = get_grant(grant_id)
    assert grant["status"] == "EXPIRED"
    assert grant["granted_count"] == 3
    assert grant["booked_count"] == 0
    assert grant["consumed_count"] == 0
    assert grant["released_count"] == 1
    assert grant["available_count"] == 3
    assert_grant_conservation(grant)

    all_grants = grants_for(membership["id"])
    assert len(all_grants) == 2
    assert all(g["status"] == "EXPIRED" for g in all_grants)

    assert service_lines_for_membership(membership["id"]) == [], (
        "no service line is created by a cancellation"
    )


def test_cancellation_leaves_completed_visits_and_issued_forms_alone(api):
    """PRD §3.4: "**Open well visits are cancelled.** Every well visit of that membership
    in `DUE` or `SCHEDULED` transitions to `CANCELLED`. Well visits already in `COMPLETED`
    or `MISSED` are left exactly as they are — history is not rewritten."
    PRD §3.4: "**Pending forms block.** Every form request of that membership in `PENDING`
    transitions `PENDING → BLOCKED` with `blocked_reason` set to `MEMBERSHIP_NOT_ACTIVE`.
    Form requests already in `ISSUED` are not touched and no issued form is ever revoked."
    PRD §3.4: "Invoices already in `ISSUED` or `PAID` are not touched."

    Design: Corner/state_machines/corner_membership_cancel_leaves_completed_visits_and_issued_forms_untouched
    """
    scenario = setup_active_membership(
        clock="2026-06-01T00:00:00Z",
        household_name="Reyes",
        child_first_name="Cleo",
        date_of_birth="2026-05-20",
        advance_clock_to="2026-06-15T00:00:00Z",
    )
    membership, doc, family = scenario["membership"], scenario["physician"], scenario["family"]

    wv_m1 = well_visit_for(membership["id"], "M1")
    complete_well_visit(wv_m1["id"], doc["id"], "2026-06-15")

    form = request_form(membership["id"], form_type="SCHOOL", needed_by_date="2026-08-01")
    issued = validate_success(
        api.issue_form_request(form["id"], scenario["physician_headers"])
    )
    assert issued["status"] == "ISSUED"

    cancelled = validate_success(
        api.cancel_membership(
            membership["id"],
            {"effective_date": "2026-06-15", "expected_family_version": family_version(family["id"])},
            ADMIN,
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert_date_equals(
        cancelled["cancellation_effective_date"], "2026-06-15", "cancellation_effective_date"
    )

    kept = validate_success(api.get_well_visit(wv_m1["id"], COORDINATOR))
    assert kept["status"] == "COMPLETED"
    assert kept["punctuality"] == "ON_SCHEDULE"

    rows, meta = validate_paginated(
        api.list_well_visits(
            COORDINATOR, params={"membership_id": membership["id"], "status": "CANCELLED"}
        )
    )
    assert meta["total_count"] == 9, "M2 through M60 were still DUE and are now cancelled"

    form_after = validate_success(api.get_form_request(form["id"], COORDINATOR))
    assert form_after["status"] == "ISSUED"
    assert form_after["blocked_reason"] is None

    invoice = get_invoice(scenario["invoice"]["id"])
    assert invoice["status"] == "PAID"
    assert invoice["total_cents"] == 40000
    assert len(invoice["lines"]) == 1

    assert float(get_physician(doc["id"])["weighted_occupancy"]) == 0.0

    lines = service_lines_for_membership(membership["id"])
    assert len(lines) == 1 and lines[0]["status"] == "SETTLED"


def test_withdrawing_an_already_withdrawn_entry_is_refused(api):
    """PRD §3.2: "An entry may be withdrawn at any time while it is `WAITING`, moving it
    `WAITING → WITHDRAWN` and removing it from every future promotion selector;
    withdrawal aimed at an entry in any other status is `ERR_INVALID_STATE`."
    PRD §3.2: "The entry opens in `WAITING` with `promoted_membership_id` null, and
    exposes a live `candidate_slot_weight` — the child's `current_slot_weight` today,
    which is the weight a promotion would consume."

    Design: Corner/state_machines/corner_withdrawn_waitlist_entry_cannot_be_withdrawn_again
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z", panel_slot_cap=4.0)
    family = create_family(household_name="Lombardi", family_monthly_cap_cents=100000)
    child = create_child(family["id"], first_name="Gia", date_of_birth="2026-04-01")

    entry = queue_for_panel(practice["physician"]["id"], child["id"], practice["plan"]["id"])
    validate_success(api.withdraw_waitlist_entry(entry["id"], COORDINATOR))

    resp = api.withdraw_waitlist_entry(entry["id"], COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409

    row = get_waitlist_entry(entry["id"])
    assert row["status"] == "WITHDRAWN"
    assert float(row["candidate_slot_weight"]) == 2.0
    assert row["promoted_membership_id"] is None


def test_waiting_entry_expires_the_day_after_its_ninety_day_life(api):
    """PRD §3.2: "Waiting entries also age out: whenever the logical clock moves, every
    entry still in `WAITING` whose creation date plus 90 days falls strictly before the
    new current date is swept `WAITING → EXPIRED`."

    Design: Corner/state_machines/corner_waitlist_entry_expires_exactly_one_day_after_ttl
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z", panel_slot_cap=4.0)
    doc_id = practice["physician"]["id"]
    family = create_family(household_name="Mensah", family_monthly_cap_cents=100000)
    child = create_child(family["id"], first_name="Kwesi", date_of_birth="2026-04-01")

    entry = queue_for_panel(doc_id, child["id"], practice["plan"]["id"])

    set_clock("2026-08-30T00:00:00Z")
    at_ttl = get_waitlist_entry(entry["id"])
    assert at_ttl["status"] == "WAITING", "created_at + 90 days is not strictly before today"

    set_clock("2026-08-31T00:00:00Z")
    past_ttl = get_waitlist_entry(entry["id"])
    assert past_ttl["status"] == "EXPIRED"
    assert past_ttl["promoted_membership_id"] is None

    rows, meta = validate_paginated(
        api.list_waitlist_entries(
            COORDINATOR, params={"physician_id": doc_id, "status": "WAITING"}
        )
    )
    assert meta["total_count"] == 0 and rows == []


def test_second_waiting_entry_for_the_same_physician_and_child_is_rejected(api):
    """PRD §3.2: "A household may not stack duplicates: a second `WAITING` entry for the
    same physician and child is refused with `ERR_DUPLICATE_WAITLIST_ENTRY`."
    PRD §3.2: "An entry may be withdrawn at any time while it is `WAITING`, moving it
    `WAITING → WITHDRAWN` and removing it from every future promotion selector"

    Design: Corner/validations/corner_second_waiting_entry_for_same_physician_and_child_is_rejected
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z", panel_slot_cap=4.0)
    doc_id, plan_id = practice["physician"]["id"], practice["plan"]["id"]
    family = create_family(household_name="Larsen", family_monthly_cap_cents=100000)
    child = create_child(family["id"], first_name="Ola", date_of_birth="2026-04-01")

    first = queue_for_panel(doc_id, child["id"], plan_id)

    dup = api.create_waitlist_entry(
        create_waitlist_entry_payload(doc_id, child["id"], plan_id), COORDINATOR
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_WAITLIST_ENTRY)
    assert dup.status_code == 409

    validate_success(api.withdraw_waitlist_entry(first["id"], COORDINATOR))
    assert get_waitlist_entry(first["id"])["status"] == "WITHDRAWN"

    retry = validate_success(
        api.create_waitlist_entry(
            create_waitlist_entry_payload(doc_id, child["id"], plan_id), COORDINATOR
        ),
        201,
    )
    assert retry["status"] == "WAITING"

    _, all_meta = validate_paginated(
        api.list_waitlist_entries(COORDINATOR, params={"physician_id": doc_id})
    )
    assert all_meta["total_count"] == 2

    _, waiting_meta = validate_paginated(
        api.list_waitlist_entries(
            COORDINATOR, params={"physician_id": doc_id, "status": "WAITING"}
        )
    )
    assert waiting_meta["total_count"] == 1
