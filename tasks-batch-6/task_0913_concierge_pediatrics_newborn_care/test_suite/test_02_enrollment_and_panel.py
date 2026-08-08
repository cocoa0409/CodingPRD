"""Joining a panel: weighted capacity, the sibling ladder and the household token."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_date_equals,
    assert_invoice_conservation,
    assert_membership,
    create_child,
    create_family,
    create_membership_payload,
    enroll,
    family_version,
    find_invoice,
    get_family,
    get_membership,
    get_physician,
    grants_for,
    issue_and_pay,
    panel_summary,
    queue_for_panel,
    set_clock,
    setup_practice,
    validate_error,
    validate_paginated,
    validate_success,
    well_visits_for,
)

ADMIN = TEST_USERS["admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]


def _family_with_children(household_name, cap_cents, births):
    family = create_family(
        household_name=household_name, family_monthly_cap_cents=cap_cents
    )
    children = [
        create_child(family["id"], first_name=f"Kid{i}", date_of_birth=dob)
        for i, dob in enumerate(births)
    ]
    return family, children


# ==========================================================================
# The sibling ladder and per-line rounding
# ==========================================================================


def test_invoice_subtotal_rounds_each_line_before_summing(api):
    """PRD §3.3: "Rounding each line then summing yields a subtotal of 76 066 — the
    correct answer; summing first and rounding once would have yielded 76 067 and is
    wrong."
    PRD §3.3: "set `prorated_cents` to the discounted monthly rate multiplied by
    `covered_days` and divided by `days_in_cycle`, rounded half-up to whole cents right
    here, before anything is added to anything."

    Design: Difficulty/combinatorial_formula/family_invoice_rounds_per_line_before_summing
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z")
    plan_id, doc_id = practice["plan"]["id"], practice["physician"]["id"]
    family, children = _family_with_children(
        "Alvarez", 100000, ["2026-03-01", "2024-06-01", "2020-06-01"]
    )

    enroll(children[0]["id"], plan_id, doc_id, "2026-06-01", family["id"])
    enroll(children[1]["id"], plan_id, doc_id, "2026-06-11", family["id"])
    enroll(children[2]["id"], plan_id, doc_id, "2026-06-14", family["id"])

    invoice = find_invoice(family["id"])

    assert_date_equals(invoice["cycle_start_date"], "2026-06-01", "Invoice.cycle_start_date")
    assert invoice["days_in_cycle"] == 30
    assert invoice["subtotal_cents"] == 76066, (
        "40000 + 21333 + 14733 with each line rounded before the sum"
    )
    assert invoice["subtotal_cents"] != 76067, "summing first and rounding once is wrong"
    assert invoice["cap_adjustment_cents"] == 0
    assert invoice["total_cents"] == 76066
    assert_invoice_conservation(invoice)

    lines = invoice["lines"]
    assert len(lines) == 3
    assert (lines[0]["enrollment_sequence"], lines[0]["covered_days"], lines[0]["prorated_cents"]) == (1, 30, 40000)
    assert (lines[1]["enrollment_sequence"], lines[1]["covered_days"], lines[1]["prorated_cents"]) == (2, 20, 21333)
    assert (lines[2]["enrollment_sequence"], lines[2]["covered_days"], lines[2]["prorated_cents"]) == (3, 17, 14733)


def test_sibling_ladder_sequences_discounts_and_rates_after_the_mutation(api):
    """PRD §3.2: "Third, derive `discount_pct` from the sequence: the first-ranked
    membership takes 0.00, the second takes 0.20, and every membership ranked third or
    beyond takes 0.35. Fourth, set each membership's `monthly_rate_cents` to its plan's
    `monthly_rate_cents` multiplied by one minus its `discount_pct`, rounded half-up to
    whole cents."
    PRD §3.2: "Second, order that set by `start_date` ascending and then by `created_at`
    ascending, and assign `enrollment_sequence` as the 1-based position in that order"

    Design: Difficulty/combinatorial_formula/family_invoice_rounds_per_line_before_summing
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z")
    plan_id, doc_id = practice["plan"]["id"], practice["physician"]["id"]
    family, children = _family_with_children(
        "Alvarez", 100000, ["2026-03-01", "2024-06-01", "2020-06-01"]
    )

    mem_a = enroll(children[0]["id"], plan_id, doc_id, "2026-06-01", family["id"])
    mem_b = enroll(children[1]["id"], plan_id, doc_id, "2026-06-11", family["id"])
    mem_c = enroll(children[2]["id"], plan_id, doc_id, "2026-06-14", family["id"])

    a, b, c = (get_membership(m["id"]) for m in (mem_a, mem_b, mem_c))
    for row in (a, b, c):
        assert_membership(row)

    assert (a["enrollment_sequence"], float(a["discount_pct"]), a["monthly_rate_cents"]) == (1, 0.00, 40000)
    assert (b["enrollment_sequence"], float(b["discount_pct"]), b["monthly_rate_cents"]) == (2, 0.20, 32000)
    assert (c["enrollment_sequence"], float(c["discount_pct"]), c["monthly_rate_cents"]) == (3, 0.35, 26000)


def test_cancelling_the_first_sibling_shifts_survivors_up_the_ladder(api):
    """PRD §3.4: "**The pricing ladder is rerun.** Every remaining membership of the
    household is re-sequenced, re-discounted and re-priced under §3.2's pinned order,
    with the just-cancelled membership excluded from the occupancy set."
    PRD §3.2: "A membership that has been cancelled keeps the `enrollment_sequence`,
    `discount_pct` and `monthly_rate_cents` it held at cancellation, frozen for audit."
    PRD §3.3: "The array is ordered by whether the membership is cancelled ascending — a
    membership in any status other than `CANCELLED` sorts before one that is — then by
    `enrollment_sequence` ascending, then by `created_at` ascending."

    Design: Corner/calculations/corner_sibling_ladder_resequences_when_the_first_child_cancels
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z")
    plan_id, doc_id = practice["plan"]["id"], practice["physician"]["id"]
    family, children = _family_with_children(
        "Ueda", 100000, ["2026-03-01", "2024-06-01", "2020-06-01"]
    )

    mem_a = enroll(children[0]["id"], plan_id, doc_id, "2026-06-01", family["id"])
    mem_b = enroll(children[1]["id"], plan_id, doc_id, "2026-06-11", family["id"])
    mem_c = enroll(children[2]["id"], plan_id, doc_id, "2026-06-14", family["id"])

    cancel_resp = api.cancel_membership(
        mem_a["id"],
        {"effective_date": "2026-06-01", "expected_family_version": family_version(family["id"])},
        ADMIN,
    )
    cancelled = validate_success(cancel_resp)
    assert cancelled["status"] == "CANCELLED"

    b, c, a = (get_membership(m["id"]) for m in (mem_b, mem_c, mem_a))
    assert (b["enrollment_sequence"], float(b["discount_pct"]), b["monthly_rate_cents"]) == (1, 0.00, 40000)
    assert (c["enrollment_sequence"], float(c["discount_pct"]), c["monthly_rate_cents"]) == (2, 0.20, 32000)
    assert a["enrollment_sequence"] == 1, "the cancelled row freezes the sequence it held"

    invoice = find_invoice(family["id"])
    lines = invoice["lines"]
    assert len(lines) == 3
    assert [line["membership_id"] for line in lines] == [mem_b["id"], mem_c["id"], mem_a["id"]]
    assert (lines[0]["covered_days"], lines[0]["prorated_cents"]) == (20, 26667)
    assert (lines[1]["covered_days"], lines[1]["prorated_cents"]) == (17, 18133)
    assert (lines[2]["covered_days"], lines[2]["prorated_cents"]) == (1, 1333)
    assert invoice["subtotal_cents"] == 46133
    assert invoice["cap_adjustment_cents"] == 0
    assert invoice["total_cents"] == 46133
    assert_invoice_conservation(invoice)

    assert get_family(family["id"])["active_membership_count"] == 2


def test_family_cap_waterfall_drains_the_last_line_first(api):
    """PRD §3.3: "With the cap set to 60 000 instead of 100 000, the adjustment is
    16 066: the third line surrenders all 14 733, the second surrenders the remaining
    1 333 and drops from 21 333 to 20 000, the first is untouched, and `total_cents`
    lands on exactly 60 000."
    PRD §3.3: "Step four: that adjustment is waterfalled against the lines in the
    **exact reverse** of the line order defined above — so the cancelled-mid-cycle line
    absorbs the cap first and the sequence-1 line absorbs it last."

    Design: Corner/calculations/corner_family_cap_waterfall_charges_the_last_line_first
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z")
    plan_id, doc_id = practice["plan"]["id"], practice["physician"]["id"]
    family, children = _family_with_children(
        "Vlasenko", 60000, ["2026-03-01", "2024-06-01", "2020-06-01"]
    )

    enroll(children[0]["id"], plan_id, doc_id, "2026-06-01", family["id"])
    enroll(children[1]["id"], plan_id, doc_id, "2026-06-11", family["id"])
    enroll(children[2]["id"], plan_id, doc_id, "2026-06-14", family["id"])

    invoice = find_invoice(family["id"])
    assert invoice["subtotal_cents"] == 76066
    assert invoice["cap_adjustment_cents"] == 16066
    assert invoice["total_cents"] == 60000

    lines = invoice["lines"]
    assert (lines[0]["prorated_cents"], lines[0]["cap_adjustment_cents"], lines[0]["line_total_cents"]) == (40000, 0, 40000)
    assert (lines[1]["prorated_cents"], lines[1]["cap_adjustment_cents"], lines[1]["line_total_cents"]) == (21333, 1333, 20000)
    assert (lines[2]["prorated_cents"], lines[2]["cap_adjustment_cents"], lines[2]["line_total_cents"]) == (14733, 14733, 0)
    assert sum(line["line_total_cents"] for line in lines) == 60000
    assert_invoice_conservation(invoice)


# ==========================================================================
# Panel capacity
# ==========================================================================


def test_panel_capacity_refuses_the_enrolment_that_exceeds_the_cap(api):
    """PRD §3.2: "The physician's current `weighted_occupancy` plus the candidate child's
    `current_slot_weight` must be less than or equal to that physician's
    `panel_slot_cap`; landing exactly on the cap is an acceptance, not a rejection.
    Exceeding it is `ERR_PANEL_CAPACITY_EXCEEDED`."
    PRD §3.2: "Read on 2026-06-01 their ages are 335 and 61 days, both weighted 2.0,
    giving an occupancy of 4.0; a third child born 2022-01-01 would weigh 1.0 and push
    the total to 5.0, so the enrolment is refused."

    Design: Difficulty/boundary_precision_check/panel_capacity_exact_equality_reached_only_after_slot_weight_ages_down
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z", panel_slot_cap=4.5)
    plan_id, doc_id = practice["plan"]["id"], practice["physician"]["id"]

    f1, kids1 = _family_with_children("Xu", 100000, ["2025-07-01"])
    mem_x = enroll(kids1[0]["id"], plan_id, doc_id, "2026-06-01", f1["id"])
    f2, kids2 = _family_with_children("Yates", 100000, ["2026-04-01"])
    mem_y = enroll(kids2[0]["id"], plan_id, doc_id, "2026-06-01", f2["id"])
    f3, kids3 = _family_with_children("Zeller", 100000, ["2022-01-01"])

    panel = panel_summary(doc_id)
    assert float(panel["weighted_occupancy"]) == 4.0
    assert float(panel["available_panel_weight"]) == 0.5

    assert float(get_membership(mem_x["id"])["slot_weight"]) == 2.0
    assert float(get_membership(mem_y["id"])["slot_weight"]) == 2.0

    payload = create_membership_payload(
        kids3[0]["id"], plan_id, doc_id, "2026-06-01", family_version(f3["id"])
    )
    resp = api.create_membership(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PANEL_CAPACITY_EXCEEDED)
    assert resp.status_code == 409


def test_panel_capacity_accepts_the_same_enrolment_once_a_slot_weight_ages_down(api):
    """PRD §3.2: "Read a month later on 2026-07-01 the elder child's age is exactly 365
    days, its weight drops to 1.5, occupancy falls to 3.5, and the identical enrolment
    now lands on exactly 4.5 and is accepted."
    PRD §3.1: "Because the weight is a function of the child's age **at today's date**
    rather than at enrolment, a physician's occupancy falls on its own as the panel ages,
    and a panel that could not accept a new baby last month may be able to accept one
    this month without anybody having left."

    Design: Difficulty/boundary_precision_check/panel_capacity_exact_equality_reached_only_after_slot_weight_ages_down
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z", panel_slot_cap=4.5)
    plan_id, doc_id = practice["plan"]["id"], practice["physician"]["id"]

    f1, kids1 = _family_with_children("Xu", 100000, ["2025-07-01"])
    mem_x = enroll(kids1[0]["id"], plan_id, doc_id, "2026-06-01", f1["id"])
    f2, kids2 = _family_with_children("Yates", 100000, ["2026-04-01"])
    mem_y = enroll(kids2[0]["id"], plan_id, doc_id, "2026-06-01", f2["id"])
    f3, kids3 = _family_with_children("Zeller", 100000, ["2022-01-01"])

    set_clock("2026-07-01T00:00:00Z")

    july = panel_summary(doc_id)
    assert float(july["weighted_occupancy"]) == 3.5
    assert float(july["available_panel_weight"]) == 1.0
    assert float(get_membership(mem_x["id"])["slot_weight"]) == 1.5
    assert float(get_membership(mem_y["id"])["slot_weight"]) == 2.0

    payload = create_membership_payload(
        kids3[0]["id"], plan_id, doc_id, "2026-07-01", family_version(f3["id"])
    )
    mem_z = validate_success(api.create_membership(payload, ADMIN), 201)
    assert float(mem_z["slot_weight"]) == 1.0, "a child of 1095 days or more consumes 1.0"

    after = panel_summary(doc_id)
    assert float(after["weighted_occupancy"]) == 4.5, "equality with the cap is accepted"
    assert float(after["available_panel_weight"]) == 0.0

    rows, meta = validate_paginated(api.list_memberships(ADMIN, params={"physician_id": doc_id}))
    assert meta["total_count"] == 3


def test_duplicate_membership_is_reported_before_panel_capacity(api):
    """PRD §2.7: "Rules are evaluated in a strict ascending order and the **first** rule
    that fails determines the response."
    PRD §2.7: "**Uniqueness.** On membership creation, the child must hold no other
    membership whose status is `PENDING_ACTIVATION`, `ACTIVE` or `SUSPENDED` — otherwise
    `ERR_DUPLICATE_MEMBERSHIP` (409)."
    PRD §2.7: "**Panel capacity.** On membership creation, the physician's
    `weighted_occupancy` plus the candidate child's `current_slot_weight` must be less
    than or equal to the physician's `panel_slot_cap`; equality is accepted. Exceeding it
    is `ERR_PANEL_CAPACITY_EXCEEDED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/duplicate_membership_outranks_panel_capacity
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z", panel_slot_cap=2.0)
    plan_id, doc_id = practice["plan"]["id"], practice["physician"]["id"]
    family, children = _family_with_children("Novak", 100000, ["2026-04-01"])

    enroll(children[0]["id"], plan_id, doc_id, "2026-06-01", family["id"])

    payload = create_membership_payload(
        children[0]["id"], plan_id, doc_id, "2026-06-15", family_version(family["id"])
    )
    resp = api.create_membership(payload, ADMIN)
    error = validate_error(resp, ApiErrorId.ERR_DUPLICATE_MEMBERSHIP)

    assert resp.status_code == 409
    assert error["error_id"] != ApiErrorId.ERR_PANEL_CAPACITY_EXCEEDED.value


def test_rejected_duplicate_enrolment_leaves_panel_and_token_untouched(api):
    """PRD §2.7: "No later rule runs and no partial mutation is persisted."
    PRD §3.1: "`weighted_occupancy`, the live sum of the slot weights of every membership
    on that physician whose status is `PENDING_ACTIVATION`, `ACTIVE` or `SUSPENDED`,
    evaluated against today's date; and `available_panel_weight`, which is the
    `panel_slot_cap` minus the `weighted_occupancy` and is floored at 0 so it never
    reports a negative figure."

    Design: Difficulty/priority_pair_validation_conflict/duplicate_membership_outranks_panel_capacity
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z", panel_slot_cap=2.0)
    plan_id, doc_id = practice["plan"]["id"], practice["physician"]["id"]
    family, children = _family_with_children("Novak", 100000, ["2026-04-01"])

    enroll(children[0]["id"], plan_id, doc_id, "2026-06-01", family["id"])
    version_before = family_version(family["id"])

    payload = create_membership_payload(
        children[0]["id"], plan_id, doc_id, "2026-06-15", version_before
    )
    validate_error(api.create_membership(payload, ADMIN), ApiErrorId.ERR_DUPLICATE_MEMBERSHIP)

    rows, meta = validate_paginated(
        api.list_memberships(ADMIN, params={"child_id": children[0]["id"]})
    )
    assert meta["total_count"] == 1, "the rejected create wrote no second membership"

    doc = get_physician(doc_id)
    assert float(doc["weighted_occupancy"]) == 2.0
    assert float(doc["available_panel_weight"]) == 0.0
    assert family_version(family["id"]) == version_before, (
        "a rejected create never advances the household token"
    )


# ==========================================================================
# Weighted-occupancy conservation
# ==========================================================================


def test_enrolling_raises_weighted_occupancy_by_the_child_weight(api):
    """PRD §3.1: "`weighted_occupancy`, the live sum of the slot weights of every
    membership on that physician whose status is `PENDING_ACTIVATION`, `ACTIVE` or
    `SUSPENDED`, evaluated against today's date"
    PRD §3.1: "A separate panel-summary capability returns the same physician's
    `physician_id`, `panel_slot_cap`, `weighted_occupancy` and `available_panel_weight`
    alongside two counts: `occupying_membership_count`, how many memberships currently
    occupy the panel in those three statuses, and `waiting_entry_count`, how many panel
    waitlist entries for that physician are still `WAITING`."

    Design: Difficulty/compensating_invariant/panel_weighted_occupancy_conserved_across_enroll_and_cancel
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z", panel_slot_cap=10.0)
    plan_id, doc_id = practice["plan"]["id"], practice["physician"]["id"]

    f1, kids1 = _family_with_children("Aoki", 100000, ["2026-03-01"])
    enroll(kids1[0]["id"], plan_id, doc_id, "2026-06-01", f1["id"])
    f2, kids2 = _family_with_children("Bianchi", 100000, ["2026-02-01"])

    before = panel_summary(doc_id)
    assert float(before["weighted_occupancy"]) == 2.0
    assert float(before["available_panel_weight"]) == 8.0
    assert before["occupying_membership_count"] == 1

    mem_b = enroll(kids2[0]["id"], plan_id, doc_id, "2026-06-01", f2["id"])
    assert float(mem_b["slot_weight"]) == 2.0

    after = panel_summary(doc_id)
    assert float(after["weighted_occupancy"]) == 4.0
    assert float(after["available_panel_weight"]) == 6.0
    assert after["occupying_membership_count"] == 2


def test_cancelling_returns_weighted_occupancy_to_its_pre_enrolment_value(api):
    """PRD §3.4: "The direct write sets the membership's status to `CANCELLED`, records
    the supplied `effective_date` in `cancellation_effective_date`, drives its
    `slot_weight` to 0.0, and increments the household's `version` by 1."
    PRD §3.4: "**Hop one — the panel loosens.** Because the membership has left the
    occupancy set, the physician's `weighted_occupancy` is recomputed and falls by
    exactly the weight that membership used to carry, and `available_panel_weight` rises
    by the same amount."

    Design: Difficulty/compensating_invariant/panel_weighted_occupancy_conserved_across_enroll_and_cancel
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z", panel_slot_cap=10.0)
    plan_id, doc_id = practice["plan"]["id"], practice["physician"]["id"]

    f1, kids1 = _family_with_children("Aoki", 100000, ["2026-03-01"])
    mem_a = enroll(kids1[0]["id"], plan_id, doc_id, "2026-06-01", f1["id"])
    f2, kids2 = _family_with_children("Bianchi", 100000, ["2026-02-01"])
    mem_b = enroll(kids2[0]["id"], plan_id, doc_id, "2026-06-01", f2["id"])

    cancelled = validate_success(
        api.cancel_membership(
            mem_b["id"],
            {"effective_date": "2026-06-01", "expected_family_version": family_version(f2["id"])},
            ADMIN,
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert float(cancelled["slot_weight"]) == 0.0

    after = panel_summary(doc_id)
    assert float(after["weighted_occupancy"]) == 2.0, "exactly the value held before the enrolment"
    assert float(after["available_panel_weight"]) == 8.0
    assert after["occupying_membership_count"] == 1

    rows, meta = validate_paginated(
        api.list_waitlist_entries(COORDINATOR, params={"physician_id": doc_id})
    )
    assert meta["total_count"] == 0, "no promotion could have fired against an empty queue"

    survivor = get_membership(mem_a["id"])
    assert survivor["status"] == "PENDING_ACTIVATION"
    assert survivor["enrollment_sequence"] == 1


def test_panel_summary_is_a_computed_read_with_membership_and_waiting_counts(api):
    """PRD §3.1: "A separate panel-summary capability returns the same physician's
    `physician_id`, `panel_slot_cap`, `weighted_occupancy` and `available_panel_weight`
    alongside two counts: `occupying_membership_count`, how many memberships currently
    occupy the panel in those three statuses, and `waiting_entry_count`, how many panel
    waitlist entries for that physician are still `WAITING`."

    Design: Corner/endpoints/corner_physician_panel_summary_is_a_computed_read
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z", panel_slot_cap=10.0)
    plan_id, doc_id = practice["plan"]["id"], practice["physician"]["id"]

    f1, kids1 = _family_with_children("Pike", 100000, ["2026-04-01"])
    mem_a = enroll(kids1[0]["id"], plan_id, doc_id, "2026-06-01", f1["id"])
    f2, kids2 = _family_with_children("Quill", 100000, ["2024-06-01"])
    mem_b = enroll(kids2[0]["id"], plan_id, doc_id, "2026-06-01", f2["id"])
    f3, kids3 = _family_with_children("Rask", 100000, ["2026-05-01"])
    queue_for_panel(doc_id, kids3[0]["id"], plan_id)

    summary = validate_success(api.get_physician_panel(doc_id, COORDINATOR))
    assert float(summary["weighted_occupancy"]) == 3.5
    assert float(summary["available_panel_weight"]) == 6.5
    assert float(summary["panel_slot_cap"]) == 10.0
    assert summary["physician_id"] == doc_id
    assert summary["occupying_membership_count"] == 2
    assert summary["waiting_entry_count"] == 1

    assert float(get_membership(mem_a["id"])["slot_weight"]) == 2.0
    assert float(get_membership(mem_b["id"])["slot_weight"]) == 1.5
    assert float(get_physician(doc_id)["weighted_occupancy"]) == 3.5


# ==========================================================================
# The household concurrency token
# ==========================================================================


def test_enrolling_with_a_stale_household_token_is_rejected(api):
    """PRD §2.8: "A `POST /peds/memberships` request must carry `expected_family_version`,
    a non-optional integer holding the client's last observed `version` of the Family
    reached through the named child. If that value does not equal the family's current
    `version`, the create is rejected with `ERR_STALE_VERSION` (412)."
    PRD §3.2: "the operation increments the household's `version` by 1"

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_expected_family_version_on_enroll
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z")
    plan_id, doc_id = practice["plan"]["id"], practice["physician"]["id"]
    family, children = _family_with_children("Delacroix", 100000, ["2026-04-01", "2024-06-01"])
    token_v0 = family["version"]

    first = validate_success(
        api.create_membership(
            create_membership_payload(children[0]["id"], plan_id, doc_id, "2026-06-01", token_v0),
            ADMIN,
        ),
        201,
    )
    assert first["status"] == "PENDING_ACTIVATION"

    stale = api.create_membership(
        create_membership_payload(children[1]["id"], plan_id, doc_id, "2026-06-11", token_v0),
        ADMIN,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412

    rows, meta = validate_paginated(
        api.list_memberships(ADMIN, params={"family_id": family["id"]})
    )
    assert meta["total_count"] == 1, "the rejected create wrote nothing"

    token_v1 = family_version(family["id"])
    assert token_v1 == token_v0 + 1

    retry = validate_success(
        api.create_membership(
            create_membership_payload(children[1]["id"], plan_id, doc_id, "2026-06-11", token_v1),
            ADMIN,
        ),
        201,
    )
    assert retry["enrollment_sequence"] == 2


def test_household_version_advances_on_enrol_and_cancel_only(api):
    """PRD §3.2: "the operation increments the household's `version` by 1"
    PRD §3.4: "The direct write sets the membership's status to `CANCELLED`, records the
    supplied `effective_date` in `cancellation_effective_date`, drives its `slot_weight`
    to 0.0, and increments the household's `version` by 1."
    PRD §3.3: "every membership of that household sitting in `PENDING_ACTIVATION` whose
    `start_date` falls between the invoice's `cycle_start_date` and `cycle_end_date`,
    both bounds inclusive, transitions `PENDING_ACTIVATION → ACTIVE` and has its own
    `version` incremented by 1."

    Design: Corner/cross_cutting_complexity_layers/corner_family_version_increments_on_every_membership_write
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z")
    plan_id, doc_id = practice["plan"]["id"], practice["physician"]["id"]
    family, children = _family_with_children("Fournier", 100000, ["2026-04-01"])

    assert family["version"] == 1, "a freshly created household reads version 1"

    membership = enroll(children[0]["id"], plan_id, doc_id, "2026-06-01", family["id"])
    assert family_version(family["id"]) == 2

    issue_and_pay(family["id"])
    assert family_version(family["id"]) == 2, (
        "invoice writes advance the invoice's own version, not the household's"
    )

    validate_success(
        api.cancel_membership(
            membership["id"],
            {"effective_date": "2026-06-01", "expected_family_version": family_version(family["id"])},
            ADMIN,
        )
    )
    assert family_version(family["id"]) == 3
    assert get_family(family["id"])["active_membership_count"] == 0


def test_membership_start_date_beyond_the_current_month_is_rejected(api):
    """PRD §3.2: "The `start_date` may not be earlier than today and may not be later
    than the last calendar day of the month containing today; anything outside that
    window is `ERR_INVALID_DATE_RANGE`."

    Design: Corner/validations/corner_membership_start_date_outside_current_month_returns_invalid_date_range
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z")
    plan_id, doc_id = practice["plan"]["id"], practice["physician"]["id"]
    family, children = _family_with_children("Ovadia", 100000, ["2026-04-01"])
    token = family["version"]

    resp = api.create_membership(
        create_membership_payload(children[0]["id"], plan_id, doc_id, "2026-07-05", token),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)
    assert resp.status_code == 400

    rows, meta = validate_paginated(
        api.list_memberships(ADMIN, params={"family_id": family["id"]})
    )
    assert meta["total_count"] == 0
    assert family_version(family["id"]) == token
    assert float(get_physician(doc_id)["weighted_occupancy"]) == 0.0


def test_enrollment_cascade_is_visible_immediately(api):
    """PRD §3.2: "it creates one entitlement grant per benefit type — one for
    `LACTATION_CONSULT` and one for `SLEEP_CONSULT` — at `membership_year_index` 0, as
    §3.8 details; it generates the child's well-visit schedule, as §3.5 details; and it
    touches the household's billing."
    PRD §3.2: "Specifically, if the family has no invoice at all for the calendar month
    containing `start_date`, a `DRAFT` invoice for that cycle is opened automatically;
    then every `DRAFT` invoice of the family is recomputed from scratch."

    Design: Corner/consistency_model/corner_immediate_consistency_enrollment_cascade_is_visible_at_once
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z")
    plan_id, doc_id = practice["plan"]["id"], practice["physician"]["id"]
    family, children = _family_with_children("Guerrero", 100000, ["2026-04-01"])

    membership = validate_success(
        api.create_membership(
            create_membership_payload(
                children[0]["id"], plan_id, doc_id, "2026-06-01", family["version"]
            ),
            ADMIN,
        ),
        201,
    )
    assert membership["status"] == "PENDING_ACTIVATION"
    assert membership["enrollment_sequence"] == 1
    assert float(membership["discount_pct"]) == 0.00
    assert membership["monthly_rate_cents"] == 40000
    assert float(membership["slot_weight"]) == 2.0

    grants = grants_for(membership["id"])
    assert len(grants) == 2
    granted = {g["benefit_type"]: g["granted_count"] for g in grants}
    assert granted == {"LACTATION_CONSULT": 3, "SLEEP_CONSULT": 2}
    assert all(g["membership_year_index"] == 0 for g in grants)

    visits = well_visits_for(membership["id"])
    assert len(visits) == 9
    assert all(v["status"] == "DUE" for v in visits)

    invoice = find_invoice(family["id"])
    assert invoice["status"] == "DRAFT"
    assert_date_equals(invoice["cycle_start_date"], "2026-06-01", "Invoice.cycle_start_date")
    assert invoice["days_in_cycle"] == 30
    assert invoice["subtotal_cents"] == 40000
    assert invoice["total_cents"] == 40000

    summary = panel_summary(doc_id)
    assert float(summary["weighted_occupancy"]) == 2.0
    assert float(summary["available_panel_weight"]) == 18.0
    assert get_family(family["id"])["active_membership_count"] == 1
