"""Supplementary tests adding a second pass for every difficulty-index
instance, asserting a different facet of the same PRD claim. Each test's
docstring tag still points at the original difficulty instance."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_guest_payload,
    create_meal_option_payload,
    create_plus_one_payload,
    create_purchase_payload,
    create_seating_assignment_payload,
    create_table_payload,
    make_couple_headers,
    make_platform_integration_headers,
    set_clock,
    bootstrap_wedding_in_draft,
    bootstrap_wedding_in_rsvp_open,
    bootstrap_wedding_with_open_registry,
    bootstrap_confirmed_purchase,
)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / dual_variant_calc / registry_purchase_aggregation_provisional_vs_settled
# Facet B: settled GET hides pending_quantity divergence is intentional.
# ─────────────────────────────────────────────────────────────────────────────

def test_registry_aggregation_pending_visible_via_provisional_view(api):
    """PRD §3.5: "Two distinct read surfaces show registry data. The settled
    view — a plain read on the registry item — surfaces `fulfilled_quantity`
    but does not surface `pending_quantity`. The provisional view — the
    per-item purchase list with the `include_pending` query parameter set
    to true — surfaces every `PENDING_REVIEW` row alongside the `CONFIRMED`
    ones".

    Design: Difficulty/dual_variant_calc/registry_purchase_aggregation_provisional_vs_settled

    Note: PRD §3.5 pins "The `RegistryItem` must currently be `OPEN` at the
    moment of ingest", so PENDING_REVIEW via the ingest path requires p1
    NOT to fill the registry. We use target=2, p1.qty=1 (CONFIRMED), p2.qty=2
    (tentative=3>2 → PENDING_REVIEW).
    """
    set_clock("2027-01-01T00:00:00Z")
    wedding, item = bootstrap_wedding_with_open_registry(
        couple_user_id="couple_w1b",
        clock_iso="2027-01-01T00:00:00Z",
        target_quantity=2, sku="DIV",
    )
    couple = make_couple_headers("couple_w1b")
    integ = make_platform_integration_headers()
    validate_success(api.create_purchase(
        item["id"], create_purchase_payload(
            platform_code="STORE_A", external_purchase_id="DV1",
            quantity=1, occurred_at="2027-01-02T10:00:00Z",
        ), integ,
    ), expected_status=201)
    validate_success(api.create_purchase(
        item["id"], create_purchase_payload(
            platform_code="STORE_B", external_purchase_id="DV2",
            quantity=2, occurred_at="2027-01-02T11:00:00Z",
        ), integ,
    ), expected_status=201)

    settled = validate_success(api.get_registry_item(item["id"], couple),
                               expected_status=200)
    assert settled["fulfilled_quantity"] == 1

    provisional = api.list_registry_item_purchases(
        item["id"], couple, params={"include_pending": True},
    )
    data = validate_success(provisional, expected_status=200)
    if isinstance(data, dict):
        rows = data.get("items") or data.get("data") or []
    else:
        rows = data
    statuses = [r["status"] for r in rows]
    assert "CONFIRMED" in statuses
    assert "PENDING_REVIEW" in statuses


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / dual_variant_calc / seating_chart_dry_run_vs_commit
# Facet B: dry-run leaves zero SeatingAssignment rows persisted.
# ─────────────────────────────────────────────────────────────────────────────

def test_auto_seat_dry_run_persists_no_rows(api):
    """PRD §3.3: "The dry-run variant — a read-style call — returns the
    plan and the unseatable list without persisting anything and without
    touching `seating_dirty`."

    Design: Difficulty/dual_variant_calc/seating_chart_dry_run_vs_commit
    """
    set_clock("2027-01-10T00:00:00Z")
    wedding, meal = bootstrap_wedding_in_rsvp_open(couple_user_id="couple_w2b")
    couple = make_couple_headers("couple_w2b")
    validate_success(api.create_table(
        wedding["id"], create_table_payload(table_number=1, capacity=2),
        couple,
    ), expected_status=201)
    g = validate_success(api.create_guest(
        wedding["id"], create_guest_payload(full_name="Solo", email="solo@example.com"),
        couple,
    ), expected_status=201)
    validate_success(api.guest_rsvp(
        g["id"], {"attending": True, "meal_option_id": meal["id"]}, couple,
    ), expected_status=200)
    validate_success(api.close_rsvp(wedding["id"], couple), expected_status=200)

    validate_success(api.auto_seat_dry_run(wedding["id"], couple), expected_status=200)

    rows = validate_success(
        api.list_seating_assignments(couple, params={"wedding_id": wedding["id"]}),
        expected_status=200,
    )
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("data") or []
    assert rows == [], "dry-run must not persist any SeatingAssignment rows"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / combinatorial_formula / thank_you_completion_nested_rounding_order
# Facet B: all-SENT yields 100.00 and is_complete=true (pinned weights).
# ─────────────────────────────────────────────────────────────────────────────

def test_thank_you_completion_all_sent_yields_one_hundred(api):
    """PRD §3.6: "The boundary flag `is_complete` is true if and only if
    `n_sent` equals `n_total` and `n_total` is strictly greater than zero."
    PRD §3.6: "The weights are pinned: a `SENT` note counts for 1.00, a
    `DRAFTED` note counts for 0.40, and a `PENDING` note counts for 0.00."

    Design: Difficulty/combinatorial_formula/thank_you_completion_nested_rounding_order
    """
    set_clock("2027-02-01T00:00:00Z")
    wedding, item = bootstrap_wedding_with_open_registry(
        couple_user_id="couple_w3b", clock_iso="2027-02-01T00:00:00Z",
        target_quantity=2, sku="BLENDB",
    )
    couple = make_couple_headers("couple_w3b")
    integ = make_platform_integration_headers()
    notes = []
    for ext, hour in [("S1", 10), ("S2", 11)]:
        p = validate_success(api.create_purchase(
            item["id"], create_purchase_payload(
                platform_code="STORE_A", external_purchase_id=ext,
                quantity=1, occurred_at=f"2027-02-02T{hour:02d}:00:00Z",
            ), integ,
        ), expected_status=201)
        note_list = validate_success(
            api.list_thank_you_notes(couple, params={"purchase_id": p["id"]}),
            expected_status=200,
        )
        if isinstance(note_list, dict):
            note_rows = note_list.get("items") or note_list.get("data") or []
        else:
            note_rows = note_list
        notes.append(note_rows[0])

    for n in notes:
        validate_success(api.draft_thank_you_note(n["id"], "Thank you.", couple),
                         expected_status=200)
        validate_success(api.send_thank_you_note(n["id"], couple), expected_status=200)

    report = validate_success(api.get_thank_you_report(wedding["id"], couple),
                              expected_status=200)
    assert report["n_total"] == 2 and report["n_sent"] == 2
    assert report["completion_pct"] == pytest.approx(100.00, abs=0.005)
    assert report["is_complete"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / combinatorial_formula / seating_chart_three_input_nonlinear_kids_spill
# Facet B: child placement blocked from non-kids-only when kids_only has free
# slots — without spill, a single child stays at the kids_only table.
# ─────────────────────────────────────────────────────────────────────────────

def test_seating_chart_single_child_takes_kids_only_table(api):
    """PRD §3.3: "if the table has `kids_only=true`, the attendee's
    `is_child` must be true; and if the table has `kids_only=false`, the
    attendee's `is_child` must be false unless that attendee's `is_child`
    is true and every `kids_only=true` table in this wedding is already
    full, in which case the child is permitted to overflow into the
    non-kids-only table."

    Design: Difficulty/combinatorial_formula/seating_chart_three_input_nonlinear_kids_spill
    """
    set_clock("2027-03-01T00:00:00Z")
    wedding, _meal = bootstrap_wedding_in_rsvp_open(couple_user_id="couple_w4b")
    couple = make_couple_headers("couple_w4b")
    meal_kids = validate_success(api.create_meal_option(
        wedding["id"], create_meal_option_payload(
            code="KIDS2", label="Kids", max_servings=50, is_kids=True,
        ),
        couple,
    ), expected_status=201)
    t_kids = validate_success(api.create_table(
        wedding["id"], create_table_payload(table_number=1, capacity=4, kids_only=True),
        couple,
    ), expected_status=201)
    validate_success(api.create_table(
        wedding["id"], create_table_payload(table_number=2, capacity=4, kids_only=False),
        couple,
    ), expected_status=201)
    child = validate_success(api.create_guest(
        wedding["id"], create_guest_payload(
            full_name="OnlyKid", email="onlykid@example.com", is_child=True,
        ),
        couple,
    ), expected_status=201)
    validate_success(api.guest_rsvp(
        child["id"], {"attending": True, "meal_option_id": meal_kids["id"]}, couple,
    ), expected_status=200)
    validate_success(api.close_rsvp(wedding["id"], couple), expected_status=200)
    validate_success(api.auto_seat_commit(wedding["id"], couple), expected_status=200)

    rows = validate_success(
        api.list_seating_assignments(couple, params={"wedding_id": wedding["id"]}),
        expected_status=200,
    )
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("data") or []
    assert len(rows) == 1
    assert rows[0]["assignee_id"] == child["id"]
    assert rows[0]["table_id"] == t_kids["id"], (
        "child should be seated at the kids_only table since it has free slots"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / non_linear_state_machine / guest_state_machine_branching_with_revert
# Facet B: revoke is rejected once wedding is RSVP_CLOSED (PRD constrains it
# to RSVP_OPEN before deadline).
# ─────────────────────────────────────────────────────────────────────────────

def test_revoke_rsvp_only_while_rsvp_open(api):
    """PRD §3.2: "The couple may also reverse direction — taking a guest
    back from `ATTENDING` or `DECLINED` to `INVITED` — but only while the
    wedding is still `RSVP_OPEN` and `current_utc` is still before
    `rsvp_deadline_at`."
    PRD §2.9: "then state-machine preconditions on the target entity
    (`ERR_INVALID_STATE` at 409)."

    Design: Difficulty/non_linear_state_machine/guest_state_machine_branching_with_revert
    """
    set_clock("2027-04-01T00:00:00Z")
    wedding, meal = bootstrap_wedding_in_rsvp_open(couple_user_id="couple_rvk")
    couple = make_couple_headers("couple_rvk")
    guest = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(full_name="Rv", email="rv@example.com"),
        couple,
    ), expected_status=201)
    validate_success(api.guest_rsvp(
        guest["id"], {"attending": True, "meal_option_id": meal["id"]}, couple,
    ), expected_status=200)
    validate_success(api.close_rsvp(wedding["id"], couple), expected_status=200)

    res = api.revoke_guest_rsvp(guest["id"], couple)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / non_linear_state_machine / registry_item_cyclic_open_fulfilled
# Facet B: ingesting into FULFILLED item is rejected with ERR_INVALID_STATE.
# ─────────────────────────────────────────────────────────────────────────────

def test_ingest_into_fulfilled_registry_item_rejected(api):
    """PRD §3.5: "The `RegistryItem` must currently be `OPEN` at the moment
    of ingest; ingesting against a `FULFILLED` or `ARCHIVED` item is
    rejected with `ERR_INVALID_STATE`".

    Design: Difficulty/non_linear_state_machine/registry_item_cyclic_open_fulfilled
    """
    set_clock("2027-05-01T00:00:00Z")
    wedding, item, _p, _n = bootstrap_confirmed_purchase(
        couple_user_id="couple_w6b", clock_iso="2027-05-01T00:00:00Z",
        target_quantity=1, quantity=1,
    )
    couple = make_couple_headers("couple_w6b")
    integ = make_platform_integration_headers()
    fulfilled = validate_success(api.get_registry_item(item["id"], couple),
                                 expected_status=200)
    assert fulfilled["status"] == "FULFILLED"

    res = api.create_purchase(
        item["id"], create_purchase_payload(
            platform_code="STORE_C", external_purchase_id="LATE",
            quantity=1, occurred_at="2027-05-03T10:00:00Z",
        ), integ,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / transitive_cascade / guest_decline_in_seated_wedding_depth3_cascade
# Facet B: decline of an ATTENDING guest in RSVP_OPEN cascades to PlusOne too,
# but does NOT touch wedding posture (wedding still RSVP_OPEN).
# ─────────────────────────────────────────────────────────────────────────────

def test_guest_decline_cascades_to_plus_one_in_rsvp_open(api):
    """PRD §3.2: "An `attending=false` RSVP transitions the guest to
    `DECLINED`, sets `meal_option_id` to null, and cascades downward: every
    `PlusOne` under that guest is itself auto-declined with `meal_option_id`
    cleared".

    Design: Difficulty/transitive_cascade/guest_decline_in_seated_wedding_depth3_cascade
    """
    set_clock("2027-06-01T00:00:00Z")
    wedding, meal = bootstrap_wedding_in_rsvp_open(couple_user_id="couple_w7b")
    couple = make_couple_headers("couple_w7b")
    guest = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(
            full_name="Head", email="head@example.com", plus_one_allowed=True,
        ),
        couple,
    ), expected_status=201)
    validate_success(api.guest_rsvp(
        guest["id"], {"attending": True, "meal_option_id": meal["id"]}, couple,
    ), expected_status=200)
    plus_one = validate_success(api.create_plus_one(
        guest["id"], create_plus_one_payload(
            full_name="Partner", meal_option_id=meal["id"],
        ),
        couple,
    ), expected_status=201)
    assert plus_one["rsvp_status"] == "ATTENDING"

    validate_success(api.guest_rsvp(
        guest["id"], {"attending": False}, couple,
    ), expected_status=200)

    after_plus_one = validate_success(api.get_plus_one(plus_one["id"], couple),
                                      expected_status=200)
    assert after_plus_one["rsvp_status"] == "DECLINED"
    assert after_plus_one.get("meal_option_id") is None


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / transitive_cascade / purchase_cancel_depth2_recompute_and_notedelete
# Facet B: registry_item.version bumps by one on the cancel cascade.
# ─────────────────────────────────────────────────────────────────────────────

def test_purchase_cancel_bumps_registry_item_version(api):
    """PRD §3.5: "On the `CONFIRMED` to `CANCELLED` path, the parent's
    `fulfilled_quantity` decreases by this purchase's `quantity`, the
    registry item's `version` advances by 1".

    Design: Difficulty/transitive_cascade/purchase_cancel_depth2_recompute_and_notedelete
    """
    set_clock("2027-07-01T00:00:00Z")
    wedding, item, purchase, _note = bootstrap_confirmed_purchase(
        couple_user_id="couple_w8b", clock_iso="2027-07-01T00:00:00Z",
        target_quantity=2, quantity=1,
    )
    couple = make_couple_headers("couple_w8b")
    pre = validate_success(api.get_registry_item(item["id"], couple),
                           expected_status=200)
    validate_success(api.cancel_purchase(purchase["id"], pre["version"], couple),
                     expected_status=200)
    after = validate_success(api.get_registry_item(item["id"], couple),
                             expected_status=200)
    assert after["version"] == pre["version"] + 1


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / priority_pair_validation_conflict / state_vs_kids_meal_pairing_priority
# Facet B: with wedding state OK, an adult picking a kids meal → ERR_KIDS_MEAL_PAIRING.
# ─────────────────────────────────────────────────────────────────────────────

def test_kids_meal_pairing_fires_when_state_ok(api):
    """PRD §3.2: "the meal's `is_kids` flag must equal the guest's
    `is_child` flag — children may pick only kids meals and adults may pick
    only adult meals (otherwise `ERR_KIDS_MEAL_PAIRING`)".

    Design: Difficulty/priority_pair_validation_conflict/state_vs_kids_meal_pairing_priority
    """
    set_clock("2027-08-01T00:00:00Z")
    wedding, _adult_meal = bootstrap_wedding_in_rsvp_open(couple_user_id="couple_w9b")
    couple = make_couple_headers("couple_w9b")
    meal_kids = validate_success(api.create_meal_option(
        wedding["id"], create_meal_option_payload(
            code="KIDSB", label="Kids", max_servings=10, is_kids=True,
        ), couple,
    ), expected_status=201)
    guest = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(full_name="Adult2", email="adult2@example.com", is_child=False),
        couple,
    ), expected_status=201)
    res = api.guest_rsvp(
        guest["id"], {"attending": True, "meal_option_id": meal_kids["id"]}, couple,
    )
    validate_error(res, ApiErrorId.ERR_KIDS_MEAL_PAIRING, expected_status=422)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / priority_pair_validation_conflict / plus_one_referential_vs_meal_full_priority
# Facet B: with plus_one_allowed=true, the meal-full violation surfaces as
# ERR_MEAL_FULL.
# ─────────────────────────────────────────────────────────────────────────────

def test_meal_full_fires_when_plus_one_allowed(api):
    """PRD §3.4: "a request that would, after the change, raise count(M)
    above M.`max_servings` is rejected with `ERR_MEAL_FULL` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/plus_one_referential_vs_meal_full_priority
    """
    set_clock("2027-09-01T00:00:00Z")
    wedding, meal_low = bootstrap_wedding_in_rsvp_open(
        couple_user_id="couple_w10b", clock_iso="2027-09-01T00:00:00Z",
        adult_meal_max_servings=1,
    )
    couple = make_couple_headers("couple_w10b")
    g_eats = validate_success(api.create_guest(
        wedding["id"], create_guest_payload(full_name="Eats", email="eats2@example.com"),
        couple,
    ), expected_status=201)
    validate_success(api.guest_rsvp(
        g_eats["id"], {"attending": True, "meal_option_id": meal_low["id"]}, couple,
    ), expected_status=200)
    g_yes_plus = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(
            full_name="YesPlus", email="yp@example.com", plus_one_allowed=True,
        ),
        couple,
    ), expected_status=201)
    res = api.create_plus_one(
        g_yes_plus["id"],
        create_plus_one_payload(full_name="Partner", meal_option_id=meal_low["id"]),
        couple,
    )
    validate_error(res, ApiErrorId.ERR_MEAL_FULL, expected_status=422)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / boundary_precision_check / meal_capacity_exact_boundary_then_overflow
# Facet B: count strictly below max_servings always succeeds.
# ─────────────────────────────────────────────────────────────────────────────

def test_meal_capacity_below_max_servings_succeeds(api):
    """PRD §3.4: "Boundary inclusivity matters here — the cap is inclusive,
    so a count exactly equal to `max_servings` is permitted; only a count
    strictly greater than `max_servings` is rejected."

    Design: Difficulty/boundary_precision_check/meal_capacity_exact_boundary_then_overflow
    """
    set_clock("2027-10-01T00:00:00Z")
    wedding, _adult = bootstrap_wedding_in_rsvp_open(couple_user_id="couple_w11b")
    couple = make_couple_headers("couple_w11b")
    meal_bound = validate_success(api.create_meal_option(
        wedding["id"], create_meal_option_payload(
            code="BOUNDB", label="Bound", max_servings=3, is_kids=False,
        ), couple,
    ), expected_status=201)
    guest = validate_success(api.create_guest(
        wedding["id"], create_guest_payload(full_name="One", email="one@example.com"),
        couple,
    ), expected_status=201)
    after = validate_success(api.guest_rsvp(
        guest["id"], {"attending": True, "meal_option_id": meal_bound["id"]}, couple,
    ), expected_status=200)
    assert after["rsvp_status"] == "ATTENDING"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / boundary_precision_check / empty_attendee_seating_chart_empty_set
# Facet B: dry-run on empty attendee set also returns empty plan + unseatable.
# ─────────────────────────────────────────────────────────────────────────────

def test_auto_seat_dry_run_on_empty_attendee_set(api):
    """PRD §3.3: "The dry-run variant — a read-style call — returns the plan
    and the unseatable list without persisting anything and without touching
    `seating_dirty`."

    Design: Difficulty/boundary_precision_check/empty_attendee_seating_chart_empty_set
    """
    set_clock("2027-11-01T00:00:00Z")
    wedding, _meal = bootstrap_wedding_in_rsvp_open(couple_user_id="couple_w12b")
    couple = make_couple_headers("couple_w12b")
    validate_success(api.create_table(
        wedding["id"], create_table_payload(table_number=1, capacity=4),
        couple,
    ), expected_status=201)
    validate_success(api.close_rsvp(wedding["id"], couple), expected_status=200)

    result = validate_success(api.auto_seat_dry_run(wedding["id"], couple),
                              expected_status=200)
    assert result["plan"] == []
    assert result["unseatable"] == []


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / cross_entity_state_dependency / guest_rsvp_blocked_by_wedding_state
# Facet B: RSVP also blocked once wedding is RSVP_CLOSED (PRD §3.2 narrows
# self-RSVP window to "while the wedding is in `RSVP_OPEN`").
# ─────────────────────────────────────────────────────────────────────────────

def test_guest_rsvp_blocked_when_wedding_rsvp_closed(api):
    """PRD §3.2: "While the wedding is in `RSVP_OPEN` and `current_utc` is
    still before `rsvp_deadline_at`, an invited guest may RSVP themselves
    through their `invitation_token`, or the couple may RSVP on their
    behalf."
    PRD §2.9: "then state-machine preconditions on the target entity
    (`ERR_INVALID_STATE` at 409)."

    Design: Difficulty/cross_entity_state_dependency/guest_rsvp_blocked_by_wedding_state
    """
    set_clock("2027-12-01T00:00:00Z")
    wedding, meal = bootstrap_wedding_in_rsvp_open(couple_user_id="couple_w13b")
    couple = make_couple_headers("couple_w13b")
    g = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(full_name="Mid", email="mid@example.com"),
        couple,
    ), expected_status=201)
    validate_success(api.close_rsvp(wedding["id"], couple), expected_status=200)

    res = api.guest_rsvp(
        g["id"], {"attending": True, "meal_option_id": meal["id"]}, couple,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / cross_entity_state_dependency / thank_you_draft_blocked_by_purchase_state
# Facet B: drafting a note BEFORE cancel succeeds (positive baseline).
# ─────────────────────────────────────────────────────────────────────────────

def test_thank_you_draft_succeeds_when_purchase_confirmed(api):
    """PRD §3.6: "To draft a note, the couple supplies a non-empty
    `drafted_body` and the note transitions from `PENDING` to `DRAFTED`;
    the body text is stored, and the parent `Purchase` must currently be
    in `CONFIRMED` (otherwise `ERR_INVALID_STATE`)."

    Design: Difficulty/cross_entity_state_dependency/thank_you_draft_blocked_by_purchase_state
    """
    set_clock("2028-01-01T00:00:00Z")
    wedding, _item, purchase, note = bootstrap_confirmed_purchase(
        couple_user_id="couple_w14b", clock_iso="2028-01-01T00:00:00Z",
        target_quantity=2, quantity=1,
    )
    couple = make_couple_headers("couple_w14b")
    assert purchase["status"] == "CONFIRMED" and note is not None
    drafted = validate_success(api.draft_thank_you_note(
        note["id"], "Thanks Bob.", couple,
    ), expected_status=200)
    assert drafted["status"] == "DRAFTED"
    assert drafted["drafted_body"] == "Thanks Bob."


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / resource_temporal_overlap / table_aggregate_capacity_overflow
# Facet B: assigning to a table with free capacity succeeds (positive
# baseline reflecting the same rule).
# ─────────────────────────────────────────────────────────────────────────────

def test_seating_at_table_with_free_capacity_succeeds(api):
    """PRD §3.3: "Second, the table-capacity ceiling: an assignment that
    would push the count of existing assignments on the target `Table` above
    its `capacity` is rejected with `ERR_TABLE_FULL` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/table_aggregate_capacity_overflow
    """
    set_clock("2028-02-01T00:00:00Z")
    wedding, meal = bootstrap_wedding_in_rsvp_open(couple_user_id="couple_w15b")
    couple = make_couple_headers("couple_w15b")
    t = validate_success(api.create_table(
        wedding["id"], create_table_payload(table_number=1, capacity=2),
        couple,
    ), expected_status=201)
    g1 = validate_success(api.create_guest(
        wedding["id"], create_guest_payload(full_name="GA", email="ga@example.com"),
        couple,
    ), expected_status=201)
    g2 = validate_success(api.create_guest(
        wedding["id"], create_guest_payload(full_name="GB", email="gb@example.com"),
        couple,
    ), expected_status=201)
    validate_success(api.guest_rsvp(
        g1["id"], {"attending": True, "meal_option_id": meal["id"]}, couple,
    ), expected_status=200)
    validate_success(api.guest_rsvp(
        g2["id"], {"attending": True, "meal_option_id": meal["id"]}, couple,
    ), expected_status=200)
    validate_success(api.close_rsvp(wedding["id"], couple), expected_status=200)
    validate_success(api.create_seating_assignment(
        create_seating_assignment_payload(wedding["id"], t["id"], "GUEST", g1["id"]),
        couple,
    ), expected_status=201)
    validate_success(api.create_seating_assignment(
        create_seating_assignment_payload(wedding["id"], t["id"], "GUEST", g2["id"]),
        couple,
    ), expected_status=201)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / resource_temporal_overlap / assignee_point_uniqueness_collision
# Facet B: a PlusOne can be seated at a different table without colliding
# with their Guest's assignment (different assignee_type makes the unique
# triple distinct).
# ─────────────────────────────────────────────────────────────────────────────

def test_guest_and_plus_one_can_each_be_seated(api):
    """PRD §3.3: "Third, the per-attendee uniqueness check: the triple of
    `wedding_id`, `assignee_type`, and `assignee_id` is enforced as unique
    across `SeatingAssignment` rows".

    Design: Difficulty/resource_temporal_overlap/assignee_point_uniqueness_collision
    """
    set_clock("2028-03-01T00:00:00Z")
    wedding, meal = bootstrap_wedding_in_rsvp_open(couple_user_id="couple_w16b")
    couple = make_couple_headers("couple_w16b")
    t = validate_success(api.create_table(
        wedding["id"], create_table_payload(table_number=1, capacity=4),
        couple,
    ), expected_status=201)
    guest = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(
            full_name="Head", email="head2@example.com", plus_one_allowed=True,
        ),
        couple,
    ), expected_status=201)
    validate_success(api.guest_rsvp(
        guest["id"], {"attending": True, "meal_option_id": meal["id"]}, couple,
    ), expected_status=200)
    plus_one = validate_success(api.create_plus_one(
        guest["id"],
        create_plus_one_payload(full_name="Partner", meal_option_id=meal["id"]),
        couple,
    ), expected_status=201)
    validate_success(api.close_rsvp(wedding["id"], couple), expected_status=200)

    validate_success(api.create_seating_assignment(
        create_seating_assignment_payload(wedding["id"], t["id"], "GUEST", guest["id"]),
        couple,
    ), expected_status=201)
    # Same assignee_id as the guest, but different assignee_type — must be
    # accepted (different unique triple).
    validate_success(api.create_seating_assignment(
        create_seating_assignment_payload(
            wedding["id"], t["id"], "PLUS_ONE", plus_one["id"],
        ),
        couple,
    ), expected_status=201)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / compensating_invariant / purchase_create_cancel_preserves_fulfilled_quantity
# Facet B: intermediate fulfilled_quantity is exactly +quantity before the
# cancel (the pair is not a no-op).
# ─────────────────────────────────────────────────────────────────────────────

def test_purchase_create_advances_fulfilled_quantity_by_quantity(api):
    """PRD §3.5: "After replay, the parent `RegistryItem`'s
    `fulfilled_quantity` is recomputed as the sum of `quantity` across all
    `CONFIRMED` rows".

    Design: Difficulty/compensating_invariant/purchase_create_cancel_preserves_fulfilled_quantity
    """
    set_clock("2028-04-01T00:00:00Z")
    wedding, item = bootstrap_wedding_with_open_registry(
        couple_user_id="couple_w17b", clock_iso="2028-04-01T00:00:00Z",
        target_quantity=10, sku="TOWELSB",
    )
    couple = make_couple_headers("couple_w17b")
    integ = make_platform_integration_headers()
    before = validate_success(api.get_registry_item(item["id"], couple),
                              expected_status=200)
    assert before["fulfilled_quantity"] == 0

    validate_success(api.create_purchase(
        item["id"], create_purchase_payload(
            platform_code="STORE_A", external_purchase_id="P3",
            quantity=3, occurred_at="2028-04-02T10:00:00Z",
        ), integ,
    ), expected_status=201)
    after = validate_success(api.get_registry_item(item["id"], couple),
                             expected_status=200)
    assert after["fulfilled_quantity"] == 3


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / compensating_invariant / rsvp_decline_re_attend_preserves_meal_count
# Facet B: DECLINED guest's meal_option_id is cleared (and they stay absent
# from the count).
# ─────────────────────────────────────────────────────────────────────────────

def test_decline_clears_meal_option_id(api):
    """PRD §3.2: "An `attending=false` RSVP transitions the guest to
    `DECLINED`, sets `meal_option_id` to null".

    Design: Difficulty/compensating_invariant/rsvp_decline_re_attend_preserves_meal_count
    """
    set_clock("2028-05-01T00:00:00Z")
    wedding, meal = bootstrap_wedding_in_rsvp_open(couple_user_id="couple_w18b")
    couple = make_couple_headers("couple_w18b")
    guest = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(full_name="Back2", email="back2@example.com"),
        couple,
    ), expected_status=201)
    validate_success(api.guest_rsvp(
        guest["id"], {"attending": True, "meal_option_id": meal["id"]}, couple,
    ), expected_status=200)
    after = validate_success(api.guest_rsvp(
        guest["id"], {"attending": False}, couple,
    ), expected_status=200)
    assert after["rsvp_status"] == "DECLINED"
    assert after.get("meal_option_id") is None
