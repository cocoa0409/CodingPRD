"""Insurance authorization: the pinned three-step award, the bounded appeal loop,
and the four-hop denial cascade."""
from test_helpers import (
    CASE_MANAGER,
    DISCHARGE_COORDINATOR,
    UR_NURSE,
    ApiErrorId,
    assert_authorization,
    confirm_order,
    create_transport_order,
    make_payer_rep_headers,
    mark_episode_ready,
    read_barriers,
    read_episode,
    read_logistics_order,
    record_bundle,
    seed_network_contract,
    seed_provider,
    seed_vehicle,
    setup_screened_episode,
    submit_authorization,
    validate_error,
    validate_success,
)

MERIDIAN_SNF = {
    "name": "Meridian Health", "coinsurance_pct": 0.200,
    "snf_auth_required": True, "hh_auth_required": True, "auth_expiry_days": 30,
}
MERIDIAN_HH = {
    "name": "Meridian Health", "coinsurance_pct": 0.200,
    "snf_auth_required": False, "hh_auth_required": True, "auth_expiry_days": 30,
}


def _contracted_snf_authorization(mrn, negotiated_daily_rate_cents, requested_days=20,
                                  billed_daily_rate_cents=32000):
    env = setup_screened_episode(
        payer=dict(MERIDIAN_SNF),
        patient={
            "mrn": mrn, "full_name": "Dee Salaam", "date_of_birth": "1943-11-02",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
        episode={"admission_type": "EMERGENT", "drg_code": "DRG-190",
                 "drg_gmlos_days": 4.0, "attending_unit": "3N",
                 "admitted_at": "2026-08-01T00:00:00Z"},
    )
    cedar = seed_provider(name="Cedar SNF", bed_unit_codes=["UNIT-A", "UNIT-B"])
    seed_network_contract(
        env["payer"]["id"], cedar["id"], in_network=True,
        negotiated_daily_rate_cents=negotiated_daily_rate_cents,
    )
    env["provider"] = cedar
    env["authorization"] = submit_authorization(
        env["episode"]["id"], cedar["id"], level_of_care="SNF",
        requested_days=requested_days, billed_daily_rate_cents=billed_daily_rate_cents,
    )
    return env


def test_volume_discount_tier_is_keyed_on_the_pre_discount_gross(api):
    """PRD §3.6: "Then `gross_projection_cents` is that raw daily rate multiplied by
    `approved_days` — a flat product, with no day tiering at all; the tiering that appears
    in the placement projection has no counterpart here. Step two reads the volume-discount
    tier from that **pre-discount** gross and from nothing else: a gross of fifteen thousand
    dollars or more sets `volume_discount_pct` to 0.05, otherwise a gross of five thousand
    dollars or more sets it to 0.03, otherwise it is 0.00. The comparisons are inclusive, so
    a gross of exactly five hundred thousand cents already qualifies for the lower tier."
    PRD §3.6: "Step three subtracts: `authorized_amount_cents` is `gross_projection_cents`
    less the gross multiplied by `volume_discount_pct` and rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/volume_discount_tier_keyed_on_pre_discount_gross
    """
    env = _contracted_snf_authorization("MRN-2201", 25000)

    data = validate_success(
        api.decide_authorization(
            env["authorization"]["id"], {"decision": "APPROVE"},
            make_payer_rep_headers(env["payer"]["id"]),
        )
    )

    assert_authorization(data)
    assert data["status"] == "APPROVED"
    assert data["approved_days"] == 20
    assert data["rate_variant_applied"] == "NETWORK_RATE"
    assert data["gross_projection_cents"] == 500000, (
        f"25000 contracted cents over 20 days, flat, got {data['gross_projection_cents']}"
    )
    assert data["volume_discount_pct"] == 0.03, (
        "500000 exactly meets the inclusive lower tier"
    )
    assert data["authorized_amount_cents"] == 485000


def test_the_discount_tier_is_never_re_keyed_on_the_discounted_amount(api):
    """PRD §3.6: "The tier is deliberately **not** re-keyed on the discounted amount, even
    though the discounted amount is what the payer ultimately owes — that dependency would
    be circular, and the order pinned here is what makes it well defined."
    PRD §3.6: "Approval is reachable from either `SUBMITTED` or `PENDED`; it sets
    `approved_days` equal to `requested_days`, sets `decided_at` to the logical clock
    instant, and sets `expires_at` to that instant plus the payer's `auth_expiry_days` in
    days."
    PRD §2.10: "`Episode.authorized_days_total` is the sum of `approved_days` across that
    episode's authorization requests in `APPROVED` or `PARTIALLY_APPROVED` status; an
    approval credits it and an expiry debits the same number of days back out."

    Design: Difficulty/combinatorial_formula/volume_discount_tier_keyed_on_pre_discount_gross
    """
    env = _contracted_snf_authorization("MRN-2202", 25000)

    data = validate_success(
        api.decide_authorization(
            env["authorization"]["id"], {"decision": "APPROVE"},
            make_payer_rep_headers(env["payer"]["id"]),
        )
    )

    assert data["authorized_amount_cents"] == 485000
    assert data["authorized_amount_cents"] < 500000, (
        "the post-discount amount falls under the tier boundary"
    )
    assert data["volume_discount_pct"] == 0.03, (
        "re-keying the tier on 485000 would have produced 0.00 and an award of 500000"
    )
    assert data["expires_at"] == "2026-08-31T00:00:00.000Z", (
        "thirty days after the decision instant of 2026-08-01T00:00:00Z"
    )
    assert read_episode(env["episode"]["id"])["authorized_days_total"] == 20


def test_a_gross_just_below_the_lower_tier_earns_no_discount(api):
    """PRD §3.6: "Step two reads the volume-discount tier from that **pre-discount** gross
    and from nothing else: a gross of fifteen thousand dollars or more sets
    `volume_discount_pct` to 0.05, otherwise a gross of five thousand dollars or more sets
    it to 0.03, otherwise it is 0.00."
    PRD §3.6: "Step one establishes the rate: exactly as with the placement projection, the
    single network contract joining the request's `payer_id` and `provider_id` is consulted,
    and when it exists with `in_network` true, `rate_variant_applied` is `NETWORK_RATE` and
    the raw daily rate is the contract's `negotiated_daily_rate_cents`; otherwise
    `rate_variant_applied` is `BILLED_RATE` and the raw daily rate is
    `billed_daily_rate_cents` multiplied by 1.25 and rounded half up to whole cents."

    Design: Corner/calculations/authorization_award_just_below_volume_tier_one_boundary
    """
    env = _contracted_snf_authorization(
        "MRN-C302", 24999, requested_days=20, billed_daily_rate_cents=40000
    )

    data = validate_success(
        api.decide_authorization(
            env["authorization"]["id"], {"decision": "APPROVE"},
            make_payer_rep_headers(env["payer"]["id"]),
        )
    )

    assert data["rate_variant_applied"] == "NETWORK_RATE", (
        "the contract wins, so the 40000 billed rate is never consulted"
    )
    assert data["gross_projection_cents"] == 499980, (
        f"24999 over 20 days is 20 cents short of the tier, got {data['gross_projection_cents']}"
    )
    assert data["volume_discount_pct"] == 0.00
    assert data["authorized_amount_cents"] == 499980, "the gross passes through unchanged"
    assert read_episode(env["episode"]["id"])["authorized_days_total"] == 20


def test_a_third_appeal_on_the_same_request_is_refused(api):
    """PRD §3.6: "`appeal_round` increments by one and must be strictly below two before a
    new appeal is accepted — so a request may travel the `SUBMITTED → DENIED → SUBMITTED`
    loop at most twice, and a third attempt is refused with `ERR_APPEAL_LIMIT_REACHED`
    (HTTP 422)."
    PRD §3.6: "Denial is reachable from either `SUBMITTED` or `PENDED`, sets `approved_days`
    to 0, records the `denial_reason` and `decided_at`, and leaves `expires_at` null."

    Design: Corner/state_machines/authorization_third_appeal_returns_appeal_limit_reached
    """
    env = setup_screened_episode(
        payer=dict(MERIDIAN_SNF),
        patient={
            "mrn": "MRN-C205", "full_name": "Gus Haddad", "date_of_birth": "1944-07-07",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    cedar = seed_provider(name="Cedar SNF", bed_unit_codes=["UNIT-A"])
    payer_rep = make_payer_rep_headers(env["payer"]["id"])
    authorization = submit_authorization(
        env["episode"]["id"], cedar["id"], level_of_care="SNF",
        requested_days=14, billed_daily_rate_cents=30000,
    )

    validate_success(
        api.decide_authorization(
            authorization["id"],
            {"decision": "DENY", "denial_reason": "INCOMPLETE_CLINICALS"}, payer_rep,
        )
    )
    first_appeal = validate_success(
        api.appeal_authorization(
            authorization["id"], {"appeal_note": "clinicals attached"}, UR_NURSE
        )
    )
    assert first_appeal["status"] == "SUBMITTED"
    assert first_appeal["appeal_round"] == 1
    validate_success(
        api.decide_authorization(
            authorization["id"],
            {"decision": "DENY", "denial_reason": "NOT_MEDICALLY_NECESSARY"}, payer_rep,
        )
    )
    second_appeal = validate_success(
        api.appeal_authorization(
            authorization["id"], {"appeal_note": "peer to peer requested"}, UR_NURSE
        )
    )
    assert second_appeal["appeal_round"] == 2
    validate_success(
        api.decide_authorization(
            authorization["id"],
            {"decision": "DENY", "denial_reason": "NOT_MEDICALLY_NECESSARY"}, payer_rep,
        )
    )

    response = api.appeal_authorization(
        authorization["id"], {"appeal_note": "third try"}, UR_NURSE
    )

    validate_error(response, ApiErrorId.ERR_APPEAL_LIMIT_REACHED, 422)
    final = validate_success(api.get_authorization(authorization["id"], CASE_MANAGER))
    assert final["appeal_round"] == 2, "the refused appeal must not increment the counter"
    assert final["status"] == "DENIED"
    assert final["approved_days"] == 0
    assert read_episode(env["episode"]["id"])["authorized_days_total"] == 0


def _ready_episode_with_confirmed_transport(mrn):
    """A READY_FOR_DISCHARGE episode with a CONFIRMED 12-mile transport order and a
    SUBMITTED home-health authorization awaiting a decision."""
    env = setup_screened_episode(
        payer=dict(MERIDIAN_HH),
        patient={
            "mrn": mrn, "full_name": "Hana Duval", "date_of_birth": "1953-06-21",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
        episode={"admission_type": "ELECTIVE", "drg_code": "DRG-470",
                 "drg_gmlos_days": 3.5, "attending_unit": "7E",
                 "admitted_at": "2026-08-01T00:00:00Z"},
    )
    home_health = seed_provider(
        name="Riverside Home Health", provider_type="HOME_HEALTH", quality_star_rating=4,
        distance_miles_from_hospital=8, bed_unit_codes=[],
    )
    vehicle = seed_vehicle(
        operator_name="Valley Medi-Ride", vehicle_type="WHEELCHAIR_VAN",
        base_rate_cents=25000, per_mile_cents=900,
    )
    record_bundle(env["episode"]["id"], pcp_followup_booked=True)
    order = create_transport_order(
        env["episode"]["id"], vehicle["id"], mileage_miles=12,
        window_start="2026-08-02T14:00:00Z", window_end="2026-08-02T15:00:00Z",
    )
    confirm_order(order["id"], DISCHARGE_COORDINATOR)
    authorization = submit_authorization(
        env["episode"]["id"], home_health["id"], level_of_care="HOME_HEALTH",
        requested_days=14, billed_daily_rate_cents=18000,
    )
    env["episode"] = mark_episode_ready(env["episode"]["id"], "HOME_SELF_CARE")
    env.update(provider=home_health, vehicle=vehicle, order=order,
               authorization=authorization)
    return env


def test_a_denial_lands_the_request_and_raises_the_insurance_barrier(api):
    """PRD §3.6: "The first hop is the decision itself: `approved_days` becomes 0 and the
    request lands in `DENIED`. The second hop raises a barrier on the episode with
    `barrier_code` of `INSURANCE_AUTH`, `severity` of `HIGH`, `delay_reason_code` of
    `AWAITING_AUTH`, and `origin` of `AUTH_DENIAL_AUTO`, with `clock_start_at` at the
    logical clock instant — except that when such a barrier already exists in `RESOLVED`
    status, it is reopened instead, incrementing its `reopen_count` and restarting its clock
    rather than creating a duplicate row."

    Design: Difficulty/transitive_cascade/auth_denial_cascade_depth_four_to_transport_cancellation
    """
    env = _ready_episode_with_confirmed_transport("MRN-4101")

    denied = validate_success(
        api.decide_authorization(
            env["authorization"]["id"],
            {"decision": "DENY", "denial_reason": "NOT_MEDICALLY_NECESSARY"},
            make_payer_rep_headers(env["payer"]["id"]),
        )
    )

    assert denied["status"] == "DENIED"
    assert denied["approved_days"] == 0
    assert denied["denial_reason"] == "NOT_MEDICALLY_NECESSARY"

    barriers = read_barriers(env["episode"]["id"])
    assert len(barriers) == 1, (
        f"the denial raises exactly one barrier, got {[b['barrier_code'] for b in barriers]}"
    )
    raised = barriers[0]
    assert raised["barrier_code"] == "INSURANCE_AUTH"
    assert raised["severity"] == "HIGH"
    assert raised["delay_reason_code"] == "AWAITING_AUTH"
    assert raised["origin"] == "AUTH_DENIAL_AUTO"
    assert raised["status"] == "OPEN"


def test_a_denial_reverts_readiness_and_cancels_the_confirmed_transport(api):
    """PRD §3.6: "The third hop recomputes `barrier_posture`, which becomes `ACTIVE`, or
    `ESCALATED` should the new barrier be critical or should another open barrier have aged
    past seventy-two hours; and when the episode's `case_status` is `READY_FOR_DISCHARGE`,
    the episode is reverted to `PLANNING`."
    PRD §3.6: "The fourth hop follows from that revert: every logistics order on the episode
    with `order_type` of `PATIENT_TRANSPORT` and `status` of `CONFIRMED` moves to
    `CANCELLED` with `cancel_reason` of `READINESS_REVERTED`, each cancellation releasing
    that order's occupied vehicle interval and debiting `logistics_committed_cents` by that
    order's `cost_cents`."
    PRD §3.8: "The revert clears `marked_ready_by_user_id` and `marked_ready_at` back to
    null but **retains** `discharge_disposition`."

    Design: Difficulty/transitive_cascade/auth_denial_cascade_depth_four_to_transport_cancellation
    """
    env = _ready_episode_with_confirmed_transport("MRN-4102")
    assert env["episode"]["case_status"] == "READY_FOR_DISCHARGE"
    assert env["episode"]["logistics_committed_cents"] == 35800

    validate_success(
        api.decide_authorization(
            env["authorization"]["id"],
            {"decision": "DENY", "denial_reason": "NOT_MEDICALLY_NECESSARY"},
            make_payer_rep_headers(env["payer"]["id"]),
        )
    )

    episode = read_episode(env["episode"]["id"])
    assert episode["barrier_posture"] == "ACTIVE"
    assert episode["case_status"] == "PLANNING"
    assert episode["marked_ready_by_user_id"] is None
    assert episode["discharge_disposition"] == "HOME_SELF_CARE", (
        "the disposition survives the revert"
    )

    order = read_logistics_order(env["order"]["id"])
    assert order["status"] == "CANCELLED"
    assert order["cancel_reason"] == "READINESS_REVERTED"
    assert order["cost_cents"] == 35800, "cancellation never rewrites the pinned cost"
    assert episode["logistics_committed_cents"] == 0, (
        f"the ledger returns to zero, got {episode['logistics_committed_cents']}"
    )
