"""Dual-variant settlement: provisional versus final pay, blended versus audit-only quality."""

import pytest

from test_helpers import (
    TEST_USERS,
    assert_pay_line_arithmetic,
    create_property_payload,
    create_quality_audit_payload,
    fixtures as fx,
    make_cleaner_headers,
    restock_entry,
    review_task_payload,
    same_instant,
    submit_task_payload,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
REVIEWER = TEST_USERS["coordinator_reviewer_headers"]
AUDITOR = TEST_USERS["quality_auditor_headers"]


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def four_line_world(api):
    """P1 with four ACTIVE supply lines, T1 accepted, started and fully verified.

    The restock row consumes exactly one unit of each of the four lines, so the
    two LINEN lines contribute 2 actual units against a summed ACTIVE LINEN
    par_qty of 14.
    """
    world = fx.world_in_progress(api, supply="four")
    entries = [restock_entry(line["id"], 1) for line in world["supply_lines"]]
    fx.submit_all_tasks(api, world, restock_entries=entries)
    fx.review_all_tasks(api, world)
    return world


@pytest.fixture
def one_line_completed_world(api):
    """P1 with a single LINEN line, driven all the way to COMPLETED at 16:00Z."""
    world = fx.build_world(api, supply=None)
    world["supply_lines"].append(fx.seed_supply_line(
        api, world["p1"]["id"], sku="LIN-SHEET-Q", name="Queen Sheet Set",
        category="LINEN", unit_cost_cents=260, par_qty=6, unit="SET",
        initial_on_hand_qty=6))
    fx.offer_turnover(api, world)
    fx.accept_offer(api, world)
    fx.start_clean(api, world)
    fx.submit_all_tasks(api, world)
    fx.review_all_tasks(api, world)
    fx.complete_clean(api, world, at=None)
    return world


@pytest.fixture
def two_turnover_audit_world(api):
    """Two completed turnovers: one with an arriving stay that has been rated,
    one vacant-gap turn that can never carry a rating."""
    fx.reset_clock(api)
    p1 = fx.seed_property(api)
    p1b = validate_success(api.create_property(create_property_payload(
        code="AUS-102", name="Zilker Studio", zone_code="ZONE_A",
        size_tier="STUDIO", owner_contact_email="owner2@example.com",
        bedroom_count=1, bathroom_count=1, bed_count=1,
        local_utc_offset_minutes=-300, min_clean_minutes=60,
        min_skill_level=1), ADMIN), 201)
    sl1 = fx.seed_supply_line(
        api, p1["id"], sku="LIN-SHEET-Q", name="Queen Sheet Set",
        category="LINEN", unit_cost_cents=260, par_qty=6, unit="SET",
        initial_on_hand_qty=6)
    sl2 = fx.seed_supply_line(
        api, p1["id"], sku="LIN-TOWEL-B", name="Bath Towel", category="LINEN",
        unit_cost_cents=180, par_qty=8, unit="EACH", initial_on_hand_qty=8)
    ca = fx.seed_cleaner(api, name="Cleaner A")
    cb = fx.seed_cleaner(api, name="Cleaner B")
    ca_headers = make_cleaner_headers(ca["id"])
    cb_headers = make_cleaner_headers(cb["id"])
    b_out, b_in = fx.seed_stay_pair(api, p1["id"])
    b_out2 = fx.seed_booking(
        api, p1b["id"], external_ref="OUT-2", guest_name="Guest Out 2",
        checkin_at="2026-08-06T21:00:00Z", checkout_at="2026-08-08T16:00:00Z")

    t1 = fx.seed_turnover(api, b_out["id"], b_in["id"])
    t2 = fx.seed_turnover(api, b_out2["id"])
    a1 = validate_success(api.assign_turnover(
        t1["id"], {"expected_turnover_version": t1["version"],
                   "cleaner_id": ca["id"]}, COORDINATOR), 201)
    a2 = validate_success(api.assign_turnover(
        t2["id"], {"expected_turnover_version": t2["version"],
                   "cleaner_id": cb["id"]}, COORDINATOR), 201)
    validate_success(api.accept_assignment(a1["id"], {}, ca_headers))
    validate_success(api.accept_assignment(a2["id"], {}, cb_headers))

    fx.reset_clock(api, "2026-08-08T16:00:00Z")
    validate_success(api.checkout_booking(b_out["id"], {}, COORDINATOR))
    validate_success(api.checkout_booking(b_out2["id"], {}, COORDINATOR))

    # T1: every row submitted and approved, restock consuming one of each linen line.
    validate_success(api.start_turnover(t1["id"], {}, ca_headers))
    k = validate_success(api.list_turnover_checklist_tasks(t1["id"], COORDINATOR))
    for task in k:
        payload = submit_task_payload(
            photo_uri="https://cdn.example.com/t1.jpg" if task["requires_photo"] else None,
            note="done",
            restock_entries=([restock_entry(sl1["id"], 1), restock_entry(sl2["id"], 1)]
                             if task["category"] == "RESTOCK" else None))
        validate_success(api.submit_checklist_task(task["id"], payload, ca_headers))
    for task in k:
        validate_success(api.review_checklist_task(
            task["id"], review_task_payload("APPROVE"), REVIEWER))
    t1 = validate_success(api.complete_turnover(t1["id"], {}, ca_headers))

    # T2: the RESTOCK row is waived because the studio carries no supply lines.
    validate_success(api.start_turnover(t2["id"], {}, cb_headers))
    m = validate_success(api.list_turnover_checklist_tasks(t2["id"], COORDINATOR))
    for task in m:
        if task["category"] == "RESTOCK":
            continue
        validate_success(api.submit_checklist_task(task["id"], submit_task_payload(
            photo_uri="https://cdn.example.com/t2.jpg" if task["requires_photo"] else None,
            note="done"), cb_headers))
    for task in m:
        if task["category"] == "RESTOCK":
            validate_success(api.review_checklist_task(task["id"], review_task_payload(
                "WAIVE", reject_reason="no supply lines configured on this unit"),
                REVIEWER))
        else:
            validate_success(api.review_checklist_task(
                task["id"], review_task_payload("APPROVE"), REVIEWER))
    t2 = validate_success(api.complete_turnover(t2["id"], {}, cb_headers))

    return {"p1": p1, "p1b": p1b, "ca": ca, "cb": cb, "b_in": b_in,
            "t1": t1, "t2": t2}


# ─── pay_variant_divergence_provisional_vs_final_linen_units ─────────────

def test_01_provisional_preview_estimates_linen_from_summed_active_par_qty(
        api, four_line_world):
    """A pre-completion preview prices linen off par level, not consumption.

    PRD §3.8: "Under the `PROVISIONAL` variant, `linen_units` is the estimate
    obtained by summing `par_qty` across the property's supply lines whose
    `category` is `LINEN` and whose `status` is `ACTIVE`; a `DISCONTINUED`
    linen line contributes nothing." PRD §3.8: "While the turnover has not
    reached `COMPLETED` the preview uses the `PROVISIONAL` variant; once the
    turnover is `COMPLETED` it uses the `FINAL` variant."

    Design: Difficulty/dual_variant_calc/pay_variant_divergence_provisional_vs_final_linen_units
    """
    world = four_line_world
    preview = validate_success(api.get_pay_preview(world["t1"]["id"], COORDINATOR))

    assert preview["variant"] == "PROVISIONAL", (
        f"an incomplete turnover must preview the PROVISIONAL variant, "
        f"got {preview['variant']}")
    assert preview["linen_units"] == 14, (
        f"linen_units must be the summed ACTIVE LINEN par_qty 6 + 8, "
        f"got {preview['linen_units']}")
    assert preview["linen_adder_cents"] == 1680, (
        f"linen_adder_cents must be 120 cents per unit times 14 units, "
        f"got {preview['linen_adder_cents']}")
    assert preview["size_base_cents"] == 8325
    assert preview["rush_premium_cents"] == 1249
    assert preview["gross_cents"] == 11254, (
        f"gross must be 8325 + 1249 + 1680, got {preview['gross_cents']}")
    assert preview["net_cents"] == 12554, (
        f"provisional net must be 11254 + 1300 bonus - 0 penalty, "
        f"got {preview['net_cents']}")
    assert_pay_line_arithmetic(preview)


def test_02_completion_reprices_linen_units_to_actual_verified_consumption(
        api, four_line_world):
    """Completion swaps the estimate for real consumption and moves the ledger.

    PRD §3.8: "Under the `FINAL` variant, `linen_units` is the actual
    consumption: the sum of `qty_used` across restock entries on the turnover's
    `VERIFIED` restock rows whose supply line's `category` is `LINEN`." PRD
    §3.8: "the cleaner's `pending_payout_cents` moves by the final `net_cents`
    less the provisional `net_cents`."

    Design: Difficulty/dual_variant_calc/pay_variant_divergence_provisional_vs_final_linen_units
    """
    world = four_line_world
    provisional_net = validate_success(
        api.get_pay_preview(world["t1"]["id"], COORDINATOR))["net_cents"]

    fx.complete_clean(api, world, at=None)

    pay_lines = validate_success(
        api.list_pay_lines(COORDINATOR, {"turnover_id": world["t1"]["id"]}))
    assert len(pay_lines) == 1, f"expected exactly one pay line, got {len(pay_lines)}"
    pay = pay_lines[0]

    assert pay["variant"] == "FINAL" and pay["status"] == "FINAL", (
        f"the pay line must settle under the FINAL variant, "
        f"got variant {pay['variant']} status {pay['status']}")
    assert pay["linen_units"] == 2, (
        f"only the two consumed LINEN units count under FINAL, "
        f"got {pay['linen_units']}")
    assert pay["linen_adder_cents"] == 240, (
        f"linen_adder_cents must be 120 times 2, got {pay['linen_adder_cents']}")
    assert pay["gross_cents"] == 9814, (
        f"final gross must be 8325 + 1249 + 240, got {pay['gross_cents']}")
    assert pay["net_cents"] == 11114, (
        f"final net must be 9814 + 1300 - 0, got {pay['net_cents']}")
    assert pay["net_cents"] - provisional_net == -1440, (
        f"the variant switch must move the settlement by exactly -1440 cents, "
        f"got {pay['net_cents'] - provisional_net}")

    cleaner = fx.read_cleaner(api, world)
    assert cleaner["pending_payout_cents"] == 11114, (
        f"the conserved ledger must hold the final net, "
        f"got {cleaner['pending_payout_cents']}")


# ─── quality_variant_divergence_blended_vs_audit_only_same_audit_score ───

def test_03_identical_audit_score_yields_blended_or_audit_only_observed_score(
        api, two_turnover_audit_world):
    """The same score 88 observes 84.80 with a guest rating and 88.00 without.

    PRD §3.9: "When the turnover's arriving stay already carries a
    `cleanliness_rating`, `variant_applied` is `BLENDED` and that rating is
    captured into `guest_rating_at_audit`." PRD §3.9: "Under the `BLENDED`
    variant, `observed_score` is the auditor's `score` weighted at sixty
    percent plus the guest's rating rescaled to the same 0-to-100 axis —
    multiplied by 20, so a 5 becomes 100 and a 3 becomes 60 — weighted at forty
    percent, with the result rounded half up to two decimal places."

    Design: Difficulty/dual_variant_calc/quality_variant_divergence_blended_vs_audit_only_same_audit_score
    """
    world = two_turnover_audit_world
    fx.reset_clock(api, "2026-08-08T21:00:00Z")
    validate_success(api.submit_guest_review(
        world["b_in"]["id"], {"cleanliness_rating": 4}, COORDINATOR))

    q1 = validate_success(api.create_quality_audit(
        create_quality_audit_payload(world["t1"]["id"], 88), AUDITOR), 201)
    q2 = validate_success(api.create_quality_audit(
        create_quality_audit_payload(world["t2"]["id"], 88), AUDITOR), 201)

    q1_final = validate_success(api.finalize_quality_audit(q1["id"], {}, AUDITOR))
    q2_final = validate_success(api.finalize_quality_audit(q2["id"], {}, AUDITOR))

    assert q1_final["variant_applied"] == "BLENDED", (
        f"a rated arriving stay must select BLENDED, "
        f"got {q1_final['variant_applied']}")
    assert q2_final["variant_applied"] == "AUDIT_ONLY", (
        f"a vacant-gap turnover has no arriving stay so it must select "
        f"AUDIT_ONLY, got {q2_final['variant_applied']}")
    assert float(q1_final["observed_score"]) == pytest.approx(84.80, abs=0.005), (
        f"observed must be 0.6*88 + 0.4*80, got {q1_final['observed_score']}")
    assert float(q2_final["observed_score"]) == pytest.approx(88.00, abs=0.005), (
        f"audit-only observed must be the raw score, "
        f"got {q2_final['observed_score']}")
    assert q1_final["guest_rating_at_audit"] == 4, (
        f"the landed rating must be captured, "
        f"got {q1_final['guest_rating_at_audit']}")
    assert q2_final["guest_rating_at_audit"] is None, (
        f"guest_rating_at_audit stays null under AUDIT_ONLY, "
        f"got {q2_final['guest_rating_at_audit']}")


def test_04_variant_divergence_moves_the_rolling_quality_score_by_0_96(
        api, two_turnover_audit_world):
    """Both variants converge on the same carryover curve, 0.96 points apart.

    PRD §3.9: "From there both variants converge: `resulting_quality_score` is
    seventy percent of the cleaner's current `quality_score` plus thirty percent
    of `observed_score`, rounded half up to two decimals, and the cleaner's
    `quality_score` is then replaced by that figure." PRD §3.9: "`pay_adjustment_cents`
    is positive 1,000 cents when the `score` is greater than or equal to 95,
    negative 1,200 cents when the `score` is strictly below 70, and 0 for any
    score inside that neutral band."

    Design: Difficulty/dual_variant_calc/quality_variant_divergence_blended_vs_audit_only_same_audit_score
    """
    world = two_turnover_audit_world
    fx.reset_clock(api, "2026-08-08T21:00:00Z")
    validate_success(api.submit_guest_review(
        world["b_in"]["id"], {"cleanliness_rating": 4}, COORDINATOR))
    q1 = validate_success(api.create_quality_audit(
        create_quality_audit_payload(world["t1"]["id"], 88), AUDITOR), 201)
    q2 = validate_success(api.create_quality_audit(
        create_quality_audit_payload(world["t2"]["id"], 88), AUDITOR), 201)

    q1_final = validate_success(api.finalize_quality_audit(q1["id"], {}, AUDITOR))
    q2_final = validate_success(api.finalize_quality_audit(q2["id"], {}, AUDITOR))

    r1 = float(q1_final["resulting_quality_score"])
    r2 = float(q2_final["resulting_quality_score"])
    assert r1 == pytest.approx(89.84, abs=0.005), (
        f"blended carryover must be 0.7*92.00 + 0.3*84.80, got {r1}")
    assert r2 == pytest.approx(90.80, abs=0.005), (
        f"audit-only carryover must be 0.7*92.00 + 0.3*88.00, got {r2}")
    assert r2 - r1 == pytest.approx(0.96, abs=0.005), (
        f"the two variants must diverge by exactly 0.96, got {r2 - r1}")

    ca = validate_success(api.get_cleaner(world["ca"]["id"], ADMIN))
    cb = validate_success(api.get_cleaner(world["cb"]["id"], ADMIN))
    assert float(ca["quality_score"]) == pytest.approx(89.84, abs=0.005), (
        f"the blended figure must replace the cleaner's rolling score, "
        f"got {ca['quality_score']}")
    assert float(cb["quality_score"]) == pytest.approx(90.80, abs=0.005), (
        f"the audit-only figure must replace the cleaner's rolling score, "
        f"got {cb['quality_score']}")

    assert q1_final["pay_adjustment_cents"] == 0 and q2_final["pay_adjustment_cents"] == 0, (
        "a score of 88 sits in the neutral band so neither audit may move money")
    pay = validate_success(
        api.list_pay_lines(COORDINATOR, {"turnover_id": world["t1"]["id"]}))[0]
    assert pay["status"] == "FINAL", (
        f"a neutral score leaves the pay line in FINAL, got {pay['status']}")


# ─── quality_variant_selection_late_guest_review_does_not_rescore ────────

def test_05_audit_finalized_before_any_rating_selects_audit_only(
        api, one_line_completed_world):
    """With no rating on the arriving stay, finalization picks AUDIT_ONLY.

    PRD §3.9: "When there is no arriving stay at all — a vacant-gap turnover —
    or its review has simply not landed yet, `variant_applied` is `AUDIT_ONLY`
    and `guest_rating_at_audit` stays null." PRD §3.9: "The first thing
    finalization does is choose a variant, and it chooses on the evidence
    available **at that instant**."

    Design: Difficulty/dual_variant_calc/quality_variant_selection_late_guest_review_does_not_rescore_finalized_audit
    """
    world = one_line_completed_world
    audit = validate_success(api.create_quality_audit(
        create_quality_audit_payload(world["t1"]["id"], 88), AUDITOR), 201)
    finalized = validate_success(api.finalize_quality_audit(audit["id"], {}, AUDITOR))

    assert finalized["variant_applied"] == "AUDIT_ONLY", (
        f"an unrated arriving stay must select AUDIT_ONLY, "
        f"got {finalized['variant_applied']}")
    assert finalized["guest_rating_at_audit"] is None, (
        f"guest_rating_at_audit must stay null, "
        f"got {finalized['guest_rating_at_audit']}")
    assert float(finalized["observed_score"]) == pytest.approx(88.00, abs=0.005)
    assert float(finalized["resulting_quality_score"]) == pytest.approx(
        90.80, abs=0.005), (
        f"carryover must be 0.7*92.00 + 0.3*88.00, "
        f"got {finalized['resulting_quality_score']}")
    assert finalized["status"] == "FINALIZED"


def test_06_rating_landing_after_finalization_never_rescores_the_audit(
        api, one_line_completed_world):
    """A late review is stored on the stay yet leaves the audit untouched.

    PRD §3.2: "Timing matters downstream in a way that is deliberate rather than
    incidental: a rating that lands *after* an audit on the relevant turnover has
    already been finalized is recorded on the booking but never retroactively
    re-scores that audit." PRD §3.9: "The order sensitivity is deliberate — a
    guest review that arrives after finalization is recorded on the booking but
    never re-scores a `FINALIZED` audit, so the same audit data can yield two
    different rolling scores depending purely on whether the guest had reviewed
    yet."

    Design: Difficulty/dual_variant_calc/quality_variant_selection_late_guest_review_does_not_rescore_finalized_audit
    """
    world = one_line_completed_world
    audit = validate_success(api.create_quality_audit(
        create_quality_audit_payload(world["t1"]["id"], 88), AUDITOR), 201)
    validate_success(api.finalize_quality_audit(audit["id"], {}, AUDITOR))

    fx.reset_clock(api, "2026-08-08T21:00:00Z")
    rated = validate_success(api.submit_guest_review(
        world["b_in"]["id"], {"cleanliness_rating": 4}, COORDINATOR))

    assert rated["cleanliness_rating"] == 4, (
        f"the late rating must still be recorded, "
        f"got {rated['cleanliness_rating']}")
    assert same_instant(rated["cleanliness_rated_at"], "2026-08-08T21:00:00Z"), (
        f"cleanliness_rated_at must be the logical clock reading, "
        f"got {rated['cleanliness_rated_at']}")

    after = validate_success(api.get_quality_audit(audit["id"], AUDITOR))
    assert after["variant_applied"] == "AUDIT_ONLY", (
        f"the finalized variant must not change, got {after['variant_applied']}")
    assert float(after["observed_score"]) == pytest.approx(88.00, abs=0.005)
    assert after["guest_rating_at_audit"] is None, (
        f"the late rating must not be captured onto the audit, "
        f"got {after['guest_rating_at_audit']}")
    assert float(after["resulting_quality_score"]) == pytest.approx(90.80, abs=0.005), (
        f"the carryover must stay 90.80 rather than the blended 89.84, "
        f"got {after['resulting_quality_score']}")

    cleaner = fx.read_cleaner(api, world)
    assert float(cleaner["quality_score"]) == pytest.approx(90.80, abs=0.005), (
        f"the rolling score must stay 90.80, got {cleaner['quality_score']}")
