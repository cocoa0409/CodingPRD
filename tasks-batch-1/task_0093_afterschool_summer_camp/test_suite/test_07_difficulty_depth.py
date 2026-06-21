"""Second-coverage depth tests for the hardest PRD behaviors.

Each test here is a complementary angle on a behavior already exercised once in
test_01..test_06 — a boundary partner, a distinct observable, or a positive/negative
counterpart — so every depth behavior carries at least two tests. Every assertion
remains derivable from a verbatim PRD sentence.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_program_payload,
    create_session_payload,
    create_enrollment_payload,
    finalize_invoice_payload,
    make_guardian_headers,
    # fixtures
    create_guardian,
    setup_eligible_child,
    setup_open_session_with_offering,
    setup_confirmed_enrollment,
    setup_offering_at_capacity,
    setup_confirmed_plus_waitlisted,
    setup_offering_with_rain_alternate,
    get_offering,
    get_invoice,
    get_enrollment,
    enroll_child,
)

DIRECTOR = TEST_USERS["program_director_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


# ---------------------------------------------------------------------------
# dual_variant_calc / tuition_provisional_vs_final_on_enrollment (2nd)
# ---------------------------------------------------------------------------
def test_final_tuition_zero_until_invoice_locks(api):
    """PRD §3.6: "The final variant snapshots the discount at the moment the invoice is
    finalized, writes it to final_tuition_cents, and freezes it". (While DRAFT, no final
    variant has run, so a CONFIRMED line's final_tuition_cents is still 0 and provisional
    carries the live CAMP line 21500.)

    Design: Difficulty/dual_variant_calc/tuition_provisional_vs_final_on_enrollment
    """
    scene = setup_confirmed_enrollment(
        program_overrides={"name": "PvF Camp", "program_type": "CAMP"},
        session_overrides={"base_weekly_tuition_cents": 20000},
    )
    e = get_enrollment(scene["enrollment"]["id"])
    assert e["provisional_tuition_cents"] == 21500, f"provisional expected 21500, got {e['provisional_tuition_cents']}"
    assert e["final_tuition_cents"] == 0, f"final must be 0 while DRAFT, got {e['final_tuition_cents']}"


# ---------------------------------------------------------------------------
# dual_variant_calc / capacity_state_posture_vs_offering_count (2nd)
# ---------------------------------------------------------------------------
def test_offering_available_posture_while_below_capacity(api):
    """PRD §2.8: "An offering is AVAILABLE while its confirmed count is below its session's
    weekly_capacity and FULL once the confirmed count reaches or exceeds it." (Capacity 2
    with 1 confirmed: count 1, posture AVAILABLE — count and posture read the same row but
    mean different things.)

    Design: Difficulty/dual_variant_calc/capacity_state_posture_vs_offering_count
    """
    scene = setup_offering_at_capacity(capacity=1, session_overrides={"weekly_capacity": 2})
    data = validate_success(api.get_weekly_offering(scene["offering"]["id"], DIRECTOR), 200)
    assert data["enrolled_count"] == 1, f"expected enrolled_count 1, got {data['enrolled_count']}"
    assert data["capacity_state"] == "AVAILABLE", f"count 1 below capacity 2 must be AVAILABLE, got {data['capacity_state']}"


# ---------------------------------------------------------------------------
# combinatorial_formula / line_tuition_scale_then_round_then_add_surcharge (2nd)
# ---------------------------------------------------------------------------
def test_afterschool_line_has_no_surcharge_with_partial_scholarship(api):
    """PRD §3.6: "a CAMP program adds a flat materials surcharge of 1,500 cents per enrolled
    week on top of the scholarship-reduced amount, while an AFTERSCHOOL program adds
    nothing." (AFTERSCHOOL base 20001, PARTIAL 0.5 -> round_half_up(10000.5)=10001, no
    surcharge.)

    Design: Difficulty/combinatorial_formula/line_tuition_scale_then_round_then_add_surcharge
    """
    eligible = setup_eligible_child(with_scholarship_tier="PARTIAL", approve_scholarship=True)
    gid = eligible["guardian"]["id"]
    scene = setup_open_session_with_offering(
        program_overrides={"name": "AS Round", "program_type": "AFTERSCHOOL"},
        session_overrides={"base_weekly_tuition_cents": 20001},
    )
    e = enroll_child(gid, eligible["child"]["id"], scene["offering"]["id"], scene["offering"]["version"])
    assert e["provisional_tuition_cents"] == 10001, (
        f"round_half_up(20001*0.5)=10001 with no AFTERSCHOOL surcharge, got {e['provisional_tuition_cents']}"
    )


# ---------------------------------------------------------------------------
# combinatorial_formula / sibling_discount_sum_then_round_evaluation_order (2nd)
# ---------------------------------------------------------------------------
def test_sibling_discount_rounds_summed_product_half_up(api):
    """PRD §3.6: "Sum those per-child highest lines across all eligible children, multiply
    the sum by the sibling discount rate of 0.10 (ten percent), and round the single summed
    product half-up to whole cents — the rounding happens once on the total, not per child."
    (Two AFTERSCHOOL children, anchor line 15000 and eligible line 12345:
    round_half_up(0.10*12345) = round_half_up(1234.5) = 1235; subtotal 27345; total 26110.)

    Design: Difficulty/combinatorial_formula/sibling_discount_sum_then_round_evaluation_order
    """
    guardian = create_guardian()
    gid = guardian["id"]
    # Two distinct eligible children under one guardian, no scholarships.
    child_anchor = setup_eligible_child(
        guardian_id=gid, child_overrides={"first_name": "Anch", "birth_date": "2016-01-01"}
    )["child"]
    child_sib = setup_eligible_child(
        guardian_id=gid, child_overrides={"first_name": "Sibl", "birth_date": "2016-02-01"}
    )["child"]
    program = api_client.create_program(
        create_program_payload(name="Round Sib", program_type="AFTERSCHOOL"), DIRECTOR
    ).json()["data"]
    s_anchor = api_client.create_session(
        create_session_payload(program["id"], title="Anchor", base_weekly_tuition_cents=15000), DIRECTOR
    ).json()["data"]
    s_sib = api_client.create_session(
        create_session_payload(program["id"], title="Sib", base_weekly_tuition_cents=12345), DIRECTOR
    ).json()["data"]
    # Both offerings share the same week_start: PRD §3.6 computes the sibling discount over
    # the CONFIRMED lines of a SINGLE draft invoice, and PRD §3.7 keys the draft invoice on
    # the guardian + the offering's billing period — so the two siblings must enroll in the
    # same billing week to share one invoice. The week-overlap check (PRD §3.4) is per-child,
    # so two distinct children in the same week do not clash.
    wo_anchor = api_client.create_weekly_offering({"session_id": s_anchor["id"], "week_start": "2026-06-08"}, DIRECTOR).json()["data"]
    wo_sib = api_client.create_weekly_offering({"session_id": s_sib["id"], "week_start": "2026-06-08"}, DIRECTOR).json()["data"]
    validate_success(api_client.publish_program(program["id"], DIRECTOR), 200)
    validate_success(api_client.open_session(s_anchor["id"], DIRECTOR), 200)
    validate_success(api_client.open_session(s_sib["id"], DIRECTOR), 200)
    ea = enroll_child(gid, child_anchor["id"], wo_anchor["id"], get_offering(wo_anchor["id"])["version"])
    invoice_id = ea["invoice_id"]
    enroll_child(gid, child_sib["id"], wo_sib["id"], get_offering(wo_sib["id"])["version"])
    inv = get_invoice(invoice_id)
    assert inv["subtotal_cents"] == 27345, f"expected subtotal 27345, got {inv['subtotal_cents']}"
    assert inv["sibling_discount_cents"] == 1235, f"expected sibling discount 1235 (half-up), got {inv['sibling_discount_cents']}"
    assert inv["total_due_cents"] == 26110, f"expected total 26110, got {inv['total_due_cents']}"


# ---------------------------------------------------------------------------
# non_linear_state_machine / enrollment_fork_join_waitlist_promotion (2nd)
# ---------------------------------------------------------------------------
def test_waitlisted_enrollment_has_zero_provisional_tuition(api):
    """PRD §3.4: "No invoice line is created while an enrollment is waitlisted, and its
    provisional_tuition_cents stays at 0." (The WAITLISTED fork has a divergent side-effect
    set from CONFIRMED: no invoice line, zero tuition.)

    Design: Difficulty/non_linear_state_machine/enrollment_fork_join_waitlist_promotion
    """
    scene = setup_confirmed_plus_waitlisted()
    eb = get_enrollment(scene["enrollment_b"]["id"], guardian_id=scene["guardian"]["id"])
    assert eb["status"] == "WAITLISTED", f"second child must be WAITLISTED, got {eb['status']}"
    assert eb["provisional_tuition_cents"] == 0, (
        f"waitlisted enrollment provisional must stay 0, got {eb['provisional_tuition_cents']}"
    )
    assert eb["waitlist_rank"] == 1, f"first waitlisted holds rank 1, got {eb['waitlist_rank']}"


# ---------------------------------------------------------------------------
# non_linear_state_machine / weekly_offering_parallel_weather_dimension_cycle (2nd)
# ---------------------------------------------------------------------------
def test_rain_activation_sets_weather_state_independently(api):
    """PRD §3.5: "this advances that offering's weather dimension NORMAL -> RAIN_ACTIVATED,
    a posture that runs independently of the occupancy posture (AVAILABLE/FULL) on the same
    offering." (With no enrollments, declaring rain flips weather_state to RAIN_ACTIVATED
    while capacity_state stays AVAILABLE — the two axes are independent.)

    Design: Difficulty/non_linear_state_machine/weekly_offering_parallel_weather_dimension_cycle
    """
    rain = setup_offering_with_rain_alternate()
    w1 = rain["w1"]
    validate_success(api.create_weather_event({"weekly_offering_id": w1["id"]}, DIRECTOR), 201)
    data = get_offering(w1["id"])
    assert data["weather_state"] == "RAIN_ACTIVATED", f"weather must be RAIN_ACTIVATED, got {data['weather_state']}"
    assert data["capacity_state"] == "AVAILABLE", f"occupancy axis stays AVAILABLE, got {data['capacity_state']}"


# ---------------------------------------------------------------------------
# transitive_cascade / session_cancel_depth3_cascade_to_invoice_totals (2nd)
# ---------------------------------------------------------------------------
def test_session_cancel_drops_waitlist_count_to_zero(api):
    """PRD §3.2: "every enrollment currently in CONFIRMED or WAITLISTED is moved to
    WITHDRAWN. Second, ... each such offering re-runs its count reconciliation, dropping
    enrolled_count and waitlist_count accordingly." (Capacity-1 offering with one CONFIRMED
    and one WAITLISTED: after cancel both withdraw and counts fall to 0.)

    Design: Difficulty/transitive_cascade/session_cancel_depth3_cascade_to_invoice_totals
    """
    scene = setup_confirmed_plus_waitlisted()
    validate_success(api.cancel_session(scene["session"]["id"], DIRECTOR), 200)
    offering = get_offering(scene["offering"]["id"])
    assert offering["enrolled_count"] == 0, f"enrolled_count must be 0 after cancel, got {offering['enrolled_count']}"
    assert offering["waitlist_count"] == 0, f"waitlist_count must be 0 after cancel, got {offering['waitlist_count']}"
    eb = get_enrollment(scene["enrollment_b"]["id"], guardian_id=scene["guardian"]["id"])
    assert eb["status"] == "WITHDRAWN", f"waitlisted enrollment must be WITHDRAWN after cancel, got {eb['status']}"


# ---------------------------------------------------------------------------
# transitive_cascade / scholarship_approve_depth3_reprice_to_total_due (2nd)
# ---------------------------------------------------------------------------
def test_full_scholarship_approval_reprices_camp_line_to_surcharge_only(api):
    """PRD §3.6: "Approving an award ... every DRAFT invoice that holds a CONFIRMED
    enrollment for that child re-runs the provisional line price on those lines with the
    newly locked discount; ... each touched line's new provisional_tuition_cents feeds the
    invoice's subtotal, lowering subtotal_cents". (CAMP base 20000, FULL approval ->
    round_half_up(20000*0)=0 +1500 = 1500.)

    Design: Difficulty/transitive_cascade/scholarship_approve_depth3_reprice_to_total_due
    """
    scene = setup_confirmed_enrollment(
        program_overrides={"name": "SchFull Camp", "program_type": "CAMP"},
        session_overrides={"base_weekly_tuition_cents": 20000},
        with_scholarship_tier="FULL",
        approve_scholarship=False,
    )
    validate_success(api.approve_scholarship_award(scene["scholarship"]["id"], DIRECTOR), 200)
    e = get_enrollment(scene["enrollment"]["id"])
    assert e["provisional_tuition_cents"] == 1500, f"FULL reprice expected 1500, got {e['provisional_tuition_cents']}"
    inv = get_invoice(scene["invoice_id"])
    assert inv["subtotal_cents"] == 1500, f"subtotal after FULL reprice expected 1500, got {inv['subtotal_cents']}"
    assert inv["total_due_cents"] == 1500, f"total after FULL reprice expected 1500, got {inv['total_due_cents']}"


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / session_not_open_beats_authorization_incomplete (2nd)
# ---------------------------------------------------------------------------
def test_authorization_incomplete_surfaces_when_session_is_open(api):
    """PRD §3.4: "The child must hold both an APPROVED authorization form of type MEDICAL
    and an APPROVED form of type PICKUP; lacking either yields ERR_AUTHORIZATION_INCOMPLETE."
    (With the session OPEN — removing the higher-priority session-state failure — the same
    no-authorization child now fails on the lower-priority authorization check, confirming
    the two checks are distinct and the loser fires only in isolation.)

    Design: Difficulty/priority_pair_validation_conflict/session_not_open_beats_authorization_incomplete
    """
    guardian = create_guardian()
    gid = guardian["id"]
    gh = make_guardian_headers(gid)
    child = api_client.create_child(
        {"guardian_id": gid, "first_name": "NoAuth", "birth_date": "2016-03-01"}, gh
    ).json()["data"]
    # Emergency contact present, but NO approved authorization forms.
    api_client.create_emergency_contact(
        {"child_id": child["id"], "contact_name": "N", "contact_phone": "1", "relationship": "aunt"}, gh
    )
    scene = setup_open_session_with_offering(program_overrides={"name": "OpenAuth Camp"})
    ver = get_offering(scene["offering"]["id"])["version"]
    resp = api.create_enrollment(create_enrollment_payload(child["id"], scene["offering"]["id"], ver), gh)
    validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_INCOMPLETE.value)


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / not_resource_owner_beats_age_out_of_group (2nd)
# ---------------------------------------------------------------------------
def test_age_out_of_group_surfaces_for_owning_guardian(api):
    """PRD §3.4: "The child's age, computed as of the session's reference date, must fall
    within the session's age group; an age outside the group yields ERR_AGE_OUT_OF_GROUP."
    (With the OWNING guardian acting — removing the higher-priority ownership failure — the
    same age-3 child now fails on the lower-priority age check, confirming the loser fires
    in isolation.)

    Design: Difficulty/priority_pair_validation_conflict/not_resource_owner_beats_age_out_of_group
    """
    owner = create_guardian()
    owner_id = owner["id"]
    eligible = setup_eligible_child(
        guardian_id=owner_id, child_overrides={"first_name": "Tot", "birth_date": "2023-01-01"}
    )  # age 3 as of 2026-06-01
    scene = setup_open_session_with_offering(
        program_overrides={"name": "AgeOwn Camp"},
        session_overrides={"age_group_min": 8, "age_group_max": 10},
    )
    owner_gh = make_guardian_headers(owner_id)
    ver = get_offering(scene["offering"]["id"])["version"]
    resp = api.create_enrollment(
        create_enrollment_payload(eligible["child"]["id"], scene["offering"]["id"], ver), owner_gh
    )
    validate_error(resp, ApiErrorId.ERR_AGE_OUT_OF_GROUP.value)


# ---------------------------------------------------------------------------
# boundary_precision_check / capacity_last_seat_confirm_then_next_waitlists (2nd)
# ---------------------------------------------------------------------------
def test_capacity_one_first_confirms_second_waitlists(api):
    """PRD §2.8: "a request that arrives while a seat remains is confirmed, and one that
    arrives when the week is full is waitlisted." (Capacity 1 boundary: the first enroll
    (count 0 < 1) confirms, the second (count 1 >= 1) waitlists.)

    Design: Difficulty/boundary_precision_check/capacity_last_seat_confirm_then_next_waitlists
    """
    scene = setup_offering_at_capacity(capacity=1, session_overrides={"weekly_capacity": 1})
    gid = scene["guardian"]["id"]
    assert scene["confirmed"][0]["status"] == "CONFIRMED", (
        f"first enroll at capacity 1 must confirm, got {scene['confirmed'][0]['status']}"
    )
    second = setup_eligible_child(guardian_id=gid, child_overrides={"first_name": "Sec", "birth_date": "2016-07-01"})["child"]
    ver = get_offering(scene["offering"]["id"])["version"]
    eb = enroll_child(gid, second["id"], scene["offering"]["id"], ver)
    assert eb["status"] == "WAITLISTED", f"second enroll at capacity 1 must waitlist, got {eb['status']}"


# ---------------------------------------------------------------------------
# boundary_precision_check / empty_invoice_finalize_zero_confirmed_lines (2nd)
# ---------------------------------------------------------------------------
def test_finalize_with_one_confirmed_line_succeeds(api):
    """PRD §3.7: "A BillingAdmin finalizes a draft invoice, advancing it DRAFT -> FINALIZED,
    but only when it holds at least one CONFIRMED enrollment line". (The boundary partner:
    exactly one CONFIRMED line clears the zero-line check and finalize succeeds.)

    Design: Difficulty/boundary_precision_check/empty_invoice_finalize_zero_confirmed_lines
    """
    scene = setup_confirmed_enrollment(
        program_overrides={"name": "OneLine Camp", "program_type": "AFTERSCHOOL"},
        session_overrides={"base_weekly_tuition_cents": 15000},
    )
    inv = get_invoice(scene["invoice_id"])
    resp = api.finalize_invoice(scene["invoice_id"], finalize_invoice_payload(inv["version"]), BILLING)
    data = validate_success(resp, 200)
    assert data["status"] == "FINALIZED", f"invoice with one confirmed line must finalize, got {data['status']}"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / enrollment_requires_session_open (2nd)
# ---------------------------------------------------------------------------
def test_enroll_into_closed_session_rejected_session_not_open(api):
    """PRD §3.2: "closing records SESSION_CLOSED, bumps the version, and means that any
    subsequent enrollment request against any week of that session is refused with
    ERR_SESSION_NOT_OPEN." (A CLOSED session — distinct from the never-opened SCHEDULED
    case — also fails the Session.status == OPEN dependency.)

    Design: Difficulty/cross_entity_state_dependency/enrollment_requires_session_open
    """
    eligible = setup_eligible_child()
    gid = eligible["guardian"]["id"]
    gh = make_guardian_headers(gid)
    scene = setup_open_session_with_offering(program_overrides={"name": "Closed Camp"})
    validate_success(api.close_session(scene["session"]["id"], DIRECTOR), 200)
    ver = get_offering(scene["offering"]["id"])["version"]
    resp = api.create_enrollment(
        create_enrollment_payload(eligible["child"]["id"], scene["offering"]["id"], ver), gh
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_OPEN.value)


# ---------------------------------------------------------------------------
# resource_temporal_overlap / child_week_overlap_same_week_rejected (2nd)
# ---------------------------------------------------------------------------
def test_adjacent_week_for_one_child_is_allowed(api):
    """PRD §3.4: "a child cannot be in two camps the same week, though enrolling in strictly
    adjacent weeks (the very next Monday, with no overlap) is permitted". (Half-open
    [week_start, +7d) intervals 2026-06-08 and 2026-06-15 do not intersect, so the second
    enroll is allowed.)

    Design: Difficulty/resource_temporal_overlap/child_week_overlap_same_week_rejected
    """
    eligible = setup_eligible_child()
    gid = eligible["guardian"]["id"]
    program = api_client.create_program(create_program_payload(name="Adj Camp"), DIRECTOR).json()["data"]
    sa = api_client.create_session(create_session_payload(program["id"], title="AdjA"), DIRECTOR).json()["data"]
    sb = api_client.create_session(create_session_payload(program["id"], title="AdjB"), DIRECTOR).json()["data"]
    wa = api_client.create_weekly_offering({"session_id": sa["id"], "week_start": "2026-06-08"}, DIRECTOR).json()["data"]
    wb = api_client.create_weekly_offering({"session_id": sb["id"], "week_start": "2026-06-15"}, DIRECTOR).json()["data"]
    validate_success(api_client.publish_program(program["id"], DIRECTOR), 200)
    validate_success(api_client.open_session(sa["id"], DIRECTOR), 200)
    validate_success(api_client.open_session(sb["id"], DIRECTOR), 200)
    enroll_child(gid, eligible["child"]["id"], wa["id"], get_offering(wa["id"])["version"])
    ver_b = get_offering(wb["id"])["version"]
    resp = api.create_enrollment(create_enrollment_payload(eligible["child"]["id"], wb["id"], ver_b), make_guardian_headers(gid))
    data = validate_success(resp, 201)
    assert data["status"] == "CONFIRMED", f"adjacent non-overlapping week must confirm, got {data['status']}"


# ---------------------------------------------------------------------------
# resource_temporal_overlap / rain_alternate_aggregate_capacity_overflow_rejected (2nd)
# ---------------------------------------------------------------------------
def test_rain_relocation_within_overflow_tolerance_succeeds(api):
    """PRD §3.5: "The number of confirmed children to relocate may exceed the alternate
    offering's weekly_capacity by at most one — a hard overflow tolerance that protects the
    indoor room ... Children that fit within the alternate's capacity remain CONFIRMED
    there; any that overflow the alternate's weekly_capacity are placed WAITLISTED on the
    alternate but are still relocated." (2 confirmed to relocate, alternate capacity 1 +
    tolerance 1 = 2: within tolerance, so the declaration succeeds and both move.)

    Design: Difficulty/resource_temporal_overlap/rain_alternate_aggregate_capacity_overflow_rejected
    """
    rain = setup_offering_with_rain_alternate(
        out_session_overrides={"weekly_capacity": 5, "age_group_min": 8, "age_group_max": 12},
        in_session_overrides={"weekly_capacity": 1, "age_group_min": 8, "age_group_max": 12},
    )
    w1, w2 = rain["w1"], rain["w2"]
    guardian = create_guardian()
    gid = guardian["id"]
    for i in range(2):
        child = setup_eligible_child(
            guardian_id=gid, child_overrides={"first_name": f"Ok{i}", "birth_date": f"2016-0{i + 1}-01"}
        )["child"]
        enroll_child(gid, child["id"], w1["id"], get_offering(w1["id"])["version"])
    resp = api.create_weather_event({"weekly_offering_id": w1["id"]}, DIRECTOR)
    wev = validate_success(resp, 201)
    assert wev["moved_enrollment_count"] == 2, f"both confirmed children must relocate, got {wev['moved_enrollment_count']}"
    w1_after = get_offering(w1["id"])
    assert w1_after["enrolled_count"] == 0, f"source W1 enrolled_count must be 0 after relocation, got {w1_after['enrolled_count']}"


# ---------------------------------------------------------------------------
# compensating_invariant / scholarship_revoke_restores_invoice_subtotal (2nd)
# ---------------------------------------------------------------------------
def test_scholarship_revoke_restores_total_due(api):
    """PRD §3.6: "so revoking an approval returns the books exactly to where they would have
    stood without it." and "total_due_cents is the subtotal minus sibling_discount_cents,
    floored at 0." (Single child, no siblings: total_due tracks subtotal back to 21500.)

    Design: Difficulty/compensating_invariant/scholarship_revoke_restores_invoice_subtotal
    """
    scene = setup_confirmed_enrollment(
        program_overrides={"name": "RevTot Camp", "program_type": "CAMP"},
        session_overrides={"base_weekly_tuition_cents": 20000},
        with_scholarship_tier="PARTIAL",
        approve_scholarship=True,
    )
    invoice_id = scene["invoice_id"]
    # Confirm the discounted state first.
    discounted = get_invoice(invoice_id)
    assert discounted["total_due_cents"] == 11500, f"approved PARTIAL total expected 11500, got {discounted['total_due_cents']}"
    validate_success(api.revoke_scholarship_award(scene["scholarship"]["id"], DIRECTOR), 200)
    restored = get_invoice(invoice_id)
    assert restored["total_due_cents"] == 21500, f"total_due must restore to 21500 after revoke, got {restored['total_due_cents']}"


# ---------------------------------------------------------------------------
# compensating_invariant / withdraw_promotion_conserves_offering_seat_count (2nd)
# ---------------------------------------------------------------------------
def test_withdraw_with_no_waitlist_frees_the_seat(api):
    """PRD §3.4: "the offering's reconciliation decrements enrolled_count, freeing a seat."
    PRD §2.8: an offering is "AVAILABLE while its confirmed count is below its session's
    weekly_capacity". (Capacity-1 offering with one CONFIRMED and no waitlist: withdrawing
    drops enrolled_count to 0 and the posture returns to AVAILABLE — no phantom occupant.)

    Design: Difficulty/compensating_invariant/withdraw_promotion_conserves_offering_seat_count
    """
    scene = setup_offering_at_capacity(capacity=1, session_overrides={"weekly_capacity": 1})
    gid = scene["guardian"]["id"]
    gh = make_guardian_headers(gid)
    validate_success(api.withdraw_enrollment(scene["confirmed"][0]["id"], gh), 200)
    offering = get_offering(scene["offering"]["id"])
    assert offering["enrolled_count"] == 0, f"enrolled_count must drop to 0 with no waitlist, got {offering['enrolled_count']}"
    assert offering["capacity_state"] == "AVAILABLE", f"freed seat must be AVAILABLE, got {offering['capacity_state']}"
