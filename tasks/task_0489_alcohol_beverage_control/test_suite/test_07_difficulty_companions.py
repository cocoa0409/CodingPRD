"""Second-test companions for each depth (difficulty) instance: boundary
counterparts, opposite branches, and isolation checks. Every companion still
cites a verbatim PRD rule and is uniquely derivable from PRD prose alone.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_applicant_headers,
    make_director_headers,
    make_examiner_headers,
    ApiErrorId,
    setup_reference_data,
    create_submitted_application,
    setup_issued_license,
    setup_license_with_active_permit,
    advance_to_protest_period,
    setup_application_in_protest_period_with_filed_protest,
    setup_application_in_protest_hearing,
    create_server_permit,
    file_violation,
    sustain_violation,
    get_quota_status,
)

DIRECTOR = TEST_USERS["director_headers"]
EXAMINER = TEST_USERS["examiner_headers"]
ZONING = TEST_USERS["zoning_officer_headers"]
ADJUDICATOR = TEST_USERS["adjudication_officer_headers"]


# ─── dual_variant_calc (companion) ────────────────────────────────────────
def test_sustain_egregious_fine_and_demerit_dual_outputs(api):
    """PRD §3.9: "A severity base is selected — twenty-five thousand cents for
    `MINOR`, seventy-five thousand cents for `SERIOUS`, two hundred thousand cents
    for `EGREGIOUS`."
    PRD §3.9: "a `MINOR` violation adds two points, a `SERIOUS` adds four, and an
    `EGREGIOUS` adds six."

    EGREGIOUS sustained as FINE at prior demerit 0: fine 200000 (on the action)
    and demerit_points += 6 (on the license) — two outputs, distinct subjects.

    Design: Difficulty/dual_variant_calc/fine_vs_demerit_dual_output_on_violation_and_license
    """
    bundle = setup_issued_license()
    lic_id = bundle["license"]["id"]
    vio = file_violation(lic_id, severity="EGREGIOUS")
    sustained = validate_success(api.sustain_violation(vio["id"], {"action_type": "FINE"}, ADJUDICATOR))
    action = get_success_data(api.get_administrative_action(sustained["action_id"], DIRECTOR))
    assert action["fine_cents"] == 200000, f"got {action['fine_cents']}"
    lic = get_success_data(api.get_license(lic_id, DIRECTOR))
    assert lic["demerit_points"] == 6, f"got {lic['demerit_points']}"


# ─── combinatorial_formula (companions) ───────────────────────────────────
def test_fine_low_recidivism_multiplier_one_full_fine(api):
    """PRD §3.9: "a multiplier of one when the prior points are below four"
    PRD §3.9: "a `FINE` pays the full raw amount, rounded half up to whole cents"

    With prior demerit_points 0 (< 4), a SERIOUS FINE pays the full base
    75000 * 1.0 = 75000 — the recidivism low band of the three-input formula.

    Design: Difficulty/combinatorial_formula/fine_assessment_three_input_nonlinear_recidivism
    """
    bundle = setup_issued_license()
    lic_id = bundle["license"]["id"]
    vio = file_violation(lic_id, severity="SERIOUS")
    sustained = sustain_violation(vio["id"], action_type="FINE")
    action = get_success_data(api.get_administrative_action(sustained["action_id"], DIRECTOR))
    assert action["fine_cents"] == 75000, f"expected 75000 at recidivism 1.0, got {action['fine_cents']}"


def test_fee_rounding_zoning_surcharge_rounded_independently(api):
    """PRD §3.2: "A zoning surcharge of ten percent of the base applies when the
    class requires zoning, and zero otherwise."
    PRD §3.2: "each surcharge is computed as its percentage of the base and
    rounded to whole cents independently first, and only then are the base and the
    two rounded surcharges summed to give `fee_quoted_cents`."

    OFF_21 base 50005 requires_zoning, non-manufacturer: zoning surcharge
    round(5000.5)=5001; fee = 50005 + 5001 = 55006.

    Design: Difficulty/combinatorial_formula/fee_rounding_order_per_component_vs_sum_then_round
    """
    ref = setup_reference_data(
        class_overrides={
            "code": "OFF_21", "premise_type": "OFF_PREMISE", "quota_managed": False,
            "base_fee_cents": 50005, "renewal_cycle_months": 12, "requires_zoning": True,
            "max_servers_per_license": 0,
        },
        applicant_overrides={"legal_name": "Package Store"},
    )
    owner = make_applicant_headers(ref["owner_id"])
    app = get_success_data(api.create_application(
        {"applicant_id": ref["owner_id"], "premise_id": ref["premise"]["id"],
         "license_class_code": "OFF_21"}, owner))
    submitted = validate_success(api.submit_application(app["id"], {}, owner))
    assert submitted["fee_quoted_cents"] == 55006, f"got {submitted['fee_quoted_cents']}"


def test_excise_wholesaler_face_value_rebate(api):
    """PRD §3.11: "`SUPPLIER` doubles the rebate base, `WHOLESALER` takes it at
    face value, and `RETAILER` earns no rebate at all"

    gross_sales 6000000 WHOLESALER: excise 240000, rebate_base round(240000*.10)=
    24000 taken at face value, excise_due = 240000-24000 = 216000.

    Design: Difficulty/combinatorial_formula/excise_circular_rebate_keyed_on_excise_tier_evaluation_order
    """
    bundle = setup_issued_license()
    owner = make_applicant_headers(bundle["ref"]["owner_id"])
    report = validate_success(api.create_compliance_report(
        {"license_id": bundle["license"]["id"], "tier": "WHOLESALER",
         "period_code": "2026-Q3", "gross_sales_cents": 6000000}, owner), expected_status=201)
    assert report["excise_due_cents"] == 216000, f"got {report['excise_due_cents']}"


# ─── non_linear_state_machine (companion) ─────────────────────────────────
def test_license_active_flips_to_renewal_due_when_window_opens(api):
    """PRD §3.8: "When the clock reaches `renewal_window_opens_at`, a re-evaluation
    flips an `ACTIVE` license to `RENEWAL_DUE` — a posture change that leaves child
    permit operations untouched but makes renewal actionable."

    The first leg of the renewal cycle: ACTIVE -> RENEWAL_DUE once the clock
    crosses renewal_window_opens_at and check-renewal-window is invoked.

    Design: Difficulty/non_linear_state_machine/license_renewal_cycle_active_to_renewal_due_to_active
    """
    bundle = setup_issued_license()
    lic_id = bundle["license"]["id"]
    get_success_data(api.set_clock("2026-12-15T00:00:00Z", DIRECTOR))
    flipped = validate_success(api.check_renewal_window(lic_id, EXAMINER))
    assert flipped["status"] == "RENEWAL_DUE", f"expected RENEWAL_DUE, got {flipped['status']}"


# ─── transitive_cascade (companions) ──────────────────────────────────────
def test_demerit_below_threshold_does_not_suspend(api):
    """PRD §3.9: "if the license's `demerit_points` has reached ten or more, the
    suspension threshold fires"
    PRD §3.9: "a `SERIOUS` adds four"

    Boundary below the threshold: two SERIOUS sustains reach demerit_points 8
    (< 10), so the license stays ACTIVE — the cascade does NOT fire.

    Design: Difficulty/transitive_cascade/violation_sustain_cascade_depth_four_to_server_permit_expiry
    """
    bundle = setup_license_with_active_permit()
    lic_id = bundle["license"]["id"]
    v1 = file_violation(lic_id, severity="SERIOUS")
    sustain_violation(v1["id"], action_type="FINE")
    v2 = file_violation(lic_id, severity="SERIOUS")
    sustain_violation(v2["id"], action_type="FINE")
    lic = get_success_data(api.get_license(lic_id, DIRECTOR))
    assert lic["demerit_points"] == 8, f"got {lic['demerit_points']}"
    assert lic["status"] == "ACTIVE", f"expected still ACTIVE at 8 demerits, got {lic['status']}"
    assert lic["active_server_count"] == 1, "permit not expired below threshold"


def test_hearing_sustain_frees_region_quota_count(api):
    """PRD §3.5: "A `PROTEST_SUSTAINED` outcome moves the hearing to
    `PROTEST_SUSTAINED`, marks the protest `SUSTAINED`, denies the application
    (moving it to `DENIED`), and releases any reserved quota slot, freeing the
    region's count by one."
    PRD §3.6: "Applications in `DRAFT`, `DENIED`, or `WITHDRAWN` do not hold a slot
    and are not counted."

    After the sustain-driven DENIED release, the region's quota-status shows the
    slot freed: available back to cap (2), used 0.

    Design: Difficulty/transitive_cascade/hearing_sustain_cascade_depth_three_to_quota_release
    """
    ref, app, protest, hearing_id = setup_application_in_protest_hearing(
        grounds="PUBLIC_NUISANCE", room_code="RM-3",
        starts_at="2026-01-10T09:00:00Z", ends_at="2026-01-10T11:00:00Z")
    get_success_data(api.set_clock("2026-01-10T12:00:00Z", DIRECTOR))
    validate_success(api.render_hearing(hearing_id, {"outcome": "PROTEST_SUSTAINED"}, ADJUDICATOR))
    status = get_quota_status(ref["region"]["id"], "ON_47")
    assert status["available"] == 2, f"expected available 2, got {status['available']}"
    assert status["used"] == 0, f"expected used 0, got {status['used']}"


# ─── priority_pair_validation_conflict (companions) ───────────────────────
def test_renew_renewal_due_with_outstanding_fine_returns_outstanding_fine(api):
    """PRD §3.8: "Renewal is permitted only when the clock has reached
    `renewal_window_opens_at` and the license is in `RENEWAL_DUE` ...; when
    `outstanding_fine_cents` is zero (otherwise `ERR_OUTSTANDING_FINE`, 422)"

    Isolation of the fiscal rule: a RENEWAL_DUE license (state gate passes) with an
    unpaid fine -> ERR_OUTSTANDING_FINE, confirming the fiscal check binds once the
    state precondition is met.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_renew_terminal_beats_outstanding_fine
    """
    bundle = setup_issued_license()
    lic_id = bundle["license"]["id"]
    owner = make_applicant_headers(bundle["ref"]["owner_id"])
    # One SERIOUS sustain -> outstanding 75000, demerit 4 (< 10, so renew not demerit-blocked).
    vio = file_violation(lic_id, severity="SERIOUS")
    sustain_violation(vio["id"], action_type="FINE")
    # Move into the renewal window and flip to RENEWAL_DUE.
    get_success_data(api.set_clock("2026-12-15T00:00:00Z", DIRECTOR))
    flipped = get_success_data(api.check_renewal_window(lic_id, EXAMINER))
    assert flipped["status"] == "RENEWAL_DUE" and flipped["outstanding_fine_cents"] == 75000
    resp = api.renew_license(lic_id, {"renewal_fee_paid_cents": 100000}, owner)
    validate_error(resp, ApiErrorId.ERR_OUTSTANDING_FINE.value)


def test_approve_early_by_distinct_director_returns_window_open(api):
    """PRD §3.5: "the protest window must have fully elapsed — the current clock
    instant must be greater than or equal to `protest_period_ends_at`; approving
    early is rejected with `ERR_PROTEST_WINDOW_OPEN` (422)."

    Isolation of the temporal rule: a Director whose id differs from the examiner
    (segregation passes) approves before the window elapsed -> the window error
    surfaces, ERR_PROTEST_WINDOW_OPEN.

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_approve_segregation_beats_window_open
    """
    ref, app = create_submitted_application()
    advance_to_protest_period(ref, app, examiner_user_id="exam-9")
    # Clock still before protest_period_ends_at; Director 'dir-1' != examiner 'exam-9'.
    resp = api.approve_application(app["id"], make_director_headers("dir-1"))
    validate_error(resp, ApiErrorId.ERR_PROTEST_WINDOW_OPEN.value)


# ─── boundary_precision_check (companions) ────────────────────────────────
def test_quota_submit_succeeds_when_one_slot_available(api):
    """PRD §3.6: "A new submit of a quota-managed application is permitted only
    when available is strictly greater than zero"
    PRD §3.2: "For a quota-managed class it reserves a slot by setting
    `quota_slot_held` true"

    The positive boundary: with available == 1 (> 0), the submit succeeds and the
    application holds a slot.

    Design: Difficulty/boundary_precision_check/quota_last_slot_available_strictly_greater_than_zero_on_submit
    """
    # cap=1 region; first (and only) submit is at available 1>0.
    ref, app = create_submitted_application(
        region_overrides={"region_code": "CTY_SM", "population": 30000, "persons_per_license": 30000},
    )
    assert app["status"] == "SUBMITTED", f"expected SUBMITTED, got {app['status']}"
    assert app["quota_slot_held"] is True


def test_zoning_buffer_distance_one_below_required_not_satisfied(api):
    """PRD §3.3: "The boundary is inclusive — `buffer_satisfied` is true exactly
    when the premise's `distance_to_school_m` is greater than or equal to the
    required separation, so a distance equal to the requirement satisfies it."

    The X-1 boundary: distance_to_school_m 99 (< 100 required for ON_PREMISE)
    makes buffer_satisfied false.

    Design: Difficulty/boundary_precision_check/zoning_buffer_distance_exactly_equals_required_is_satisfied
    """
    ref = setup_reference_data(applicant_overrides={"legal_name": "Close Bar"})
    owner = make_applicant_headers(ref["owner_id"])
    prem = get_success_data(api.create_premise(
        {"applicant_id": ref["owner_id"], "region_code": ref["region"]["region_code"],
         "street_address": "99 Close St", "distance_to_school_m": 99,
         "zoning_district": "COMMERCIAL"}, owner))
    app = get_success_data(api.create_application(
        {"applicant_id": ref["owner_id"], "premise_id": prem["id"], "license_class_code": "ON_47"},
        owner))
    reg_now = get_success_data(api.get_quota_region(ref["region"]["id"], DIRECTOR))
    get_success_data(api.submit_application(
        app["id"], {"expected_region_version": reg_now["version"]}, owner))
    zr = get_success_data(api.list_application_zoning_reviews(app["id"], ZONING))
    assert zr[0]["buffer_satisfied"] is False, "distance 99 < 100 must not satisfy the buffer"


# ─── cross_entity_state_dependency (companions) ───────────────────────────
def test_begin_review_blocked_when_zoning_blocked(api):
    """PRD §3.4: "when a zoning review exists, that review's `result` must be
    either `CLEARED` or `VARIANCE_GRANTED` — otherwise `ERR_ZONING_NOT_CLEARED`
    (422); a `BLOCKED` or still-`PENDING` zoning review bars review."

    A different cross-entity gate on the same SUBMITTED -> UNDER_REVIEW transition:
    background PASSED but zoning BLOCKED -> ERR_ZONING_NOT_CLEARED.

    Design: Difficulty/cross_entity_state_dependency/begin_review_blocked_until_background_check_passed
    """
    ref, app = create_submitted_application()
    # Pass background, but BLOCK zoning.
    bc = get_success_data(api.list_application_background_checks(app["id"], EXAMINER))
    get_success_data(api.resolve_background_check(bc[0]["id"], {"decision": "PASS"}, EXAMINER))
    zr = get_success_data(api.list_application_zoning_reviews(app["id"], ZONING))
    get_success_data(api.decide_zoning_review(zr[0]["id"], {"decision": "BLOCK"}, ZONING))
    resp = api.begin_review(app["id"], EXAMINER)
    validate_error(resp, ApiErrorId.ERR_ZONING_NOT_CLEARED.value)


def test_server_activate_succeeds_when_license_active(api):
    """PRD §3.7: "Activating a permit advances it from `PENDING` to `ACTIVE` ...
    On activation the server sets the permit's `expires_at` to thirty-six months
    after the current clock instant, increments the parent license's
    `active_server_count` by one, and advances the license's `version`."

    The positive cross-entity case: with the license ACTIVE and a trained permit,
    activate succeeds and bubbles active_server_count to 1.

    Design: Difficulty/cross_entity_state_dependency/server_activate_blocked_unless_license_active
    """
    bundle = setup_issued_license()
    lic = bundle["license"]
    owner_id = bundle["ref"]["owner_id"]
    permit = create_server_permit(lic["id"], owner_id, training_completed=True, holder_name="Bartender C")
    activated = validate_success(api.activate_server_permit(
        permit["id"], {"expected_license_version": lic["version"]}, make_applicant_headers(owner_id)))
    assert activated["status"] == "ACTIVE", f"got {activated['status']}"
    lic_after = get_success_data(api.get_license(lic["id"], DIRECTOR))
    assert lic_after["active_server_count"] == 1, f"got {lic_after['active_server_count']}"


# ─── resource_temporal_overlap (companions) ───────────────────────────────
def test_hearing_room_adjacent_window_allowed(api):
    """PRD §3.5: "Overlap here uses **half-open** semantics — two windows that
    merely touch, where one ends exactly when the next begins, do **not** conflict
    and are allowed"

    A second hearing in RM-1 [11:00, 12:00) starting exactly when the first
    [09:00, 11:00) ends is allowed (adjacency); the protest schedules to SCHEDULED.

    Design: Difficulty/resource_temporal_overlap/hearing_room_half_open_adjacency_allowed_overlap_rejected
    """
    refA, appA = create_submitted_application(applicant_overrides={"legal_name": "Bar A2"})
    advance_to_protest_period(refA, appA)
    prA = get_success_data(api.create_protest(
        {"application_id": appA["id"], "protester_name": "P1", "grounds": "ZONING"},
        TEST_USERS["anonymous_headers"]))
    get_success_data(api.schedule_hearing(
        prA["id"], {"room_code": "RM-1", "starts_at": "2026-01-05T09:00:00Z",
                    "ends_at": "2026-01-05T11:00:00Z"}, ADJUDICATOR))
    reg = get_success_data(api.list_quota_regions(DIRECTOR))[0]
    oB = get_success_data(api.create_applicant({"legal_name": "Bar B2"}, DIRECTOR))
    pB = get_success_data(api.create_premise(
        {"applicant_id": oB["id"], "region_code": reg["region_code"], "street_address": "2 B St",
         "distance_to_school_m": 200, "zoning_district": "COMMERCIAL"}, make_applicant_headers(oB["id"])))
    aB = get_success_data(api.create_application(
        {"applicant_id": oB["id"], "premise_id": pB["id"], "license_class_code": "ON_47"},
        make_applicant_headers(oB["id"])))
    reg_now = get_success_data(api.get_quota_region(reg["id"], DIRECTOR))
    get_success_data(api.submit_application(
        aB["id"], {"expected_region_version": reg_now["version"]}, make_applicant_headers(oB["id"])))
    zrB = get_success_data(api.list_application_zoning_reviews(aB["id"], ZONING))
    get_success_data(api.decide_zoning_review(zrB[0]["id"], {"decision": "CLEAR"}, ZONING))
    bcB = get_success_data(api.list_application_background_checks(aB["id"], EXAMINER))
    get_success_data(api.resolve_background_check(bcB[0]["id"], {"decision": "PASS"}, EXAMINER))
    get_success_data(api.begin_review(aB["id"], EXAMINER))
    get_success_data(api.open_protest_period(aB["id"], EXAMINER))
    prB = get_success_data(api.create_protest(
        {"application_id": aB["id"], "protester_name": "P2", "grounds": "ZONING"},
        TEST_USERS["anonymous_headers"]))
    scheduled = validate_success(api.schedule_hearing(
        prB["id"], {"room_code": "RM-1", "starts_at": "2026-01-05T11:00:00Z",
                    "ends_at": "2026-01-05T12:00:00Z"}, ADJUDICATOR))
    assert scheduled["status"] == "SCHEDULED", f"adjacency should be allowed, got {scheduled['status']}"


def test_premise_relocation_clean_approval_succeeds(api):
    """PRD §3.12: "On a clean location approval the premise is relocated with no
    region change."
    PRD §3.12: "the target premise must lie in the same region as the license"

    A LOCATION transfer onto an empty same-region premise (no hosted license, no
    term conflict) -> APPROVED.

    Design: Difficulty/resource_temporal_overlap/premise_term_closed_interval_overlap_conflicts
    """
    bundle = setup_issued_license()
    lic = bundle["license"]
    ref = bundle["ref"]
    owner = make_applicant_headers(ref["owner_id"])
    target = get_success_data(api.create_premise(
        {"applicant_id": ref["owner_id"], "region_code": ref["region"]["region_code"],
         "street_address": "5 Empty St", "distance_to_school_m": 200,
         "zoning_district": "COMMERCIAL"}, owner))
    tr = get_success_data(api.create_transfer_request(
        {"license_id": lic["id"], "transfer_type": "LOCATION", "new_premise_id": target["id"]}, owner))
    approved = validate_success(api.approve_transfer_request(tr["id"], DIRECTOR))
    assert approved["status"] == "APPROVED", f"clean relocation should approve, got {approved['status']}"


# ─── compensating_invariant (companions) ──────────────────────────────────
def test_submit_reserves_one_slot_forward_leg(api):
    """PRD §3.2: "For a quota-managed class it reserves a slot by setting
    `quota_slot_held` true and advancing the region's `version`, so that the
    availability count immediately reflects this application."
    PRD §3.6: "The number of slots **used** is the count of applications for that
    same region and class that currently hold a slot"

    The forward leg in isolation: after one submit on a cap-2 region, used 1 and
    available 1 (cap minus the one held slot).

    Design: Difficulty/compensating_invariant/quota_reserve_then_withdraw_conserves_region_slot_count
    """
    ref, app = create_submitted_application()
    assert app["quota_slot_held"] is True
    status = get_quota_status(ref["region"]["id"], "ON_47")
    assert status["used"] == 1, f"expected used 1, got {status['used']}"
    assert status["available"] == 1, f"expected available 1, got {status['available']}"


def test_fine_partial_payment_reduces_outstanding_ledger(api):
    """PRD §3.9: "a fine payment supplies the `action_id` of the administrative
    action and an `amount_cents`, adding that amount to the action's
    `fine_paid_cents` and subtracting it from the license's `outstanding_fine_cents`,
    floored at zero."

    Partial payment of the ledger: pay 50000 of a 75000 fine -> outstanding 25000,
    fine_paid_cents 50000 (the running ledger identity holds before full payoff).

    Design: Difficulty/compensating_invariant/fine_charge_then_payment_conserves_outstanding_fine_ledger
    """
    bundle = setup_issued_license()
    lic_id = bundle["license"]["id"]
    owner = make_applicant_headers(bundle["ref"]["owner_id"])
    vio = file_violation(lic_id, severity="SERIOUS")
    sustained = sustain_violation(vio["id"], action_type="FINE")
    action_id = sustained["action_id"]
    lic = validate_success(api.pay_fine(lic_id, {"action_id": action_id, "amount_cents": 50000}, owner))
    assert lic["outstanding_fine_cents"] == 25000, f"got {lic['outstanding_fine_cents']}"
    action = get_success_data(api.get_administrative_action(action_id, DIRECTOR))
    assert action["fine_paid_cents"] == 50000, f"got {action['fine_paid_cents']}"
