"""Rejection-order corners, part four: the domain constraints that sit at the end of
the rejection order — uniqueness, channel permissions, the ladder rung, the dispute
cap, the two segregation-of-duties rules, the final-floor recomputation, the override
band and the annual chargeback ceiling.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ANALYST_HEADERS,
    BCM_HEADERS,
    COUNSEL_2_HEADERS,
    COUNSEL_HEADERS,
    ApiErrorId,
    api_client,
    make_reseller_headers,
)
from test_helpers.assertions import (
    assert_same_instant,
    override_floor_lower_bound,
    score_delta,
    standing_for_score,
    tier_rate_for_score,
    violation_points,
)
from test_helpers.constants import EVIDENCE_HASH_1, EVIDENCE_HASH_3
from test_helpers.factories import (
    agreement_payload,
    chargeback_payload,
    exception_decision_payload,
    exception_payload,
    notice_payload,
    observation_payload,
    product_adjustment_payload,
    product_payload,
    serial_unit_payload,
    violation_dispute_decision_payload,
    violation_dispute_payload,
)
from test_helpers.fixtures import (
    capture_observation,
    capture_purchase_serial,
    confirm_unauthorized,
    create_active_agreement,
    create_detected_violation,
    create_distributor,
    create_product,
    create_published_policy,
    create_reseller,
    create_serial_unit,
    current_distributor_version,
    current_reseller_version,
    evaluate_observation,
    issue_notice,
    order_test_purchase,
    pin_clock,
    read_agreement,
    read_distributor,
    read_exception,
    read_notice,
    read_product,
    read_reseller,
    read_violation,
)

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_20 = "2026-08-20T00:00:00Z"
OBSERVED_AUG_18 = "2026-08-18T00:00:00Z"
OBSERVED_AUG_19 = "2026-08-19T00:00:00Z"
ORDERED_AUG_19 = "2026-08-19T00:00:00Z"
TERM_ENDS = "2027-06-30T00:00:00Z"
SUSPENSION_STARTS = "2026-09-01T00:00:00Z"
SUSPENSION_ENDS = "2026-09-10T00:00:00Z"
DISPUTE_DEADLINE_AFTER_TWO_ROUNDS = "2026-09-09T00:00:00Z"

STANDARD_FLOOR = 15000
REDUCED_FLOOR = 14000


# --------------------------------------------------------------------------- #
# Shared spine
# --------------------------------------------------------------------------- #
def _published_policy():
    pin_clock(CLOCK_AUG_01)
    return create_published_policy(effective_from=CLOCK_AUG_01)


def _headphones(policy_id):
    return create_product(
        policy_id,
        sku="SKU-AUDIO-1",
        name="Studio Headphones",
        msrp_cents=20000,
        standard_map_floor_cents=STANDARD_FLOOR,
    )


def _acme():
    return create_reseller(
        legal_name="Acme Retail LLC",
        contact_email="ops@acme.example",
        primary_channel="MARKETPLACE",
    )


def _authorized_channel():
    """Published policy, headphones and an authorized Acme on the marketplace."""
    policy = _published_policy()
    product = _headphones(policy["id"])
    reseller = _acme()
    agreement = create_active_agreement(
        reseller["id"],
        policy["id"],
        permitted_channels=["MARKETPLACE", "OWN_WEBSITE"],
        quality_obligations=["AUTHENTICITY_LABELING"],
        term_ends_at=TERM_ENDS,
    )
    return {
        "policy": policy,
        "product": product,
        "reseller": reseller,
        "agreement": agreement,
    }


def _detected_first_breach(world):
    """A 14000 marketplace listing detected against Acme: three points."""
    pin_clock(CLOCK_AUG_20)
    violation, observation, _evaluation = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=14000,
        channel="MARKETPLACE",
        observed_at=OBSERVED_AUG_18,
        seller_display_name="Acme Store",
        listing_url="https://mkt.example/l/1",
        evidence_hash=EVIDENCE_HASH_1,
    )
    world["violation"] = violation
    world["observation"] = observation
    return world


def _warned_acme():
    world = _detected_first_breach(_authorized_channel())
    world["notice"] = issue_notice(world["reseller"]["id"], world["violation"]["id"])
    return world


def _suspended_acme_with_third_breach(suspension_headers=BCM_HEADERS):
    """Warning then suspension served, with an eleven-point-plus third breach pending."""
    world = _warned_acme()
    violation2, _obs2, _eval2 = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=9000,
        channel="MARKETPLACE",
        observed_at=OBSERVED_AUG_18,
        seller_display_name="Acme Store",
        listing_url="https://mkt.example/l/2",
        evidence_hash=EVIDENCE_HASH_3,
    )
    world["violation2"] = violation2
    world["notice2"] = issue_notice(
        world["reseller"]["id"],
        violation2["id"],
        headers=suspension_headers,
        suspension_starts_at=SUSPENSION_STARTS,
        suspension_ends_at=SUSPENSION_ENDS,
    )
    violation3, _obs3, _eval3 = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=14000,
        channel="MARKETPLACE",
        observed_at=OBSERVED_AUG_19,
        seller_display_name="Acme Store",
        listing_url="https://mkt.example/l/3",
        evidence_hash=EVIDENCE_HASH_1,
    )
    world["violation3"] = violation3
    return world


def _capped_trace(cap_cents, legal_name):
    """A confirmed unauthorized trace against a distributor on a tight annual cap."""
    policy = _published_policy()
    product = _headphones(policy["id"])
    distributor = create_distributor(
        legal_name=legal_name, annual_chargeback_cap_cents=cap_cents
    )
    create_serial_unit(
        product["id"], distributor["id"], serial_number="SN-0007", lot_code="LOT-C"
    )
    pin_clock(CLOCK_AUG_20)
    observation = capture_observation(
        product["id"],
        channel="MARKETPLACE",
        seller_display_name="GreyBox Deals",
        listing_url="https://mkt.example/l/9",
        listed_price_cents=9000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=EVIDENCE_HASH_1,
    )
    evaluate_observation(observation["id"])
    purchase = order_test_purchase(
        observation["id"], ordered_at=ORDERED_AUG_19, purchase_price_cents=9000
    )
    capture_purchase_serial(purchase["id"], "SN-0007")
    purchase = confirm_unauthorized(
        purchase["id"], outcome_reason="Seller has no agreement on file"
    )
    return {"product": product, "distributor": distributor, "purchase": purchase}


# --------------------------------------------------------------------------- #
# Priority 12 — domain constraints
# --------------------------------------------------------------------------- #
def test_a_second_product_reusing_a_registered_sku_is_refused():
    """The catalogue key is unique, so the second registration never lands.

    PRD: "A `BrandChannelManager` registers each branded item with a `sku` of 1 to 40
    characters that must be unique across the catalogue — a duplicate is rejected with
    `ERR_DUPLICATE_SKU` — plus a display `name`, an `msrp_cents` figure that must be
    strictly greater than zero, and a `standard_map_floor_cents` figure that must be
    strictly greater than zero and no greater than `msrp_cents`."

    Design: Corner/validations/duplicate_sku_rejected
    """
    policy = _published_policy()
    first = _headphones(policy["id"])

    validate_error(
        api_client.create_product(
            product_payload(
                policy["id"],
                sku="SKU-AUDIO-1",
                name="Studio Headphones Mk II",
                msrp_cents=25000,
                standard_map_floor_cents=19000,
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_DUPLICATE_SKU.value,
    )

    rows, meta = validate_paginated(api_client.list_products(BCM_HEADERS))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]


def test_a_second_unit_reusing_a_registered_serial_number_is_refused():
    """Serial numbers are unique across every unit the system holds.

    PRD: "A `BrandChannelManager` registers each produced unit with a `serial_number` of
    1 to 40 characters that must be unique across every unit the system holds — a
    duplicate is rejected with `ERR_DUPLICATE_SERIAL` — the `product_id` it belongs to, a
    `lot_code` of 1 to 40 characters identifying the shipment lot, and the
    `shipped_distributor_id` naming the distributor it went to."

    Design: Corner/validations/duplicate_serial_number_rejected
    """
    policy = _published_policy()
    product = _headphones(policy["id"])
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )
    first = create_serial_unit(
        product["id"], distributor["id"], serial_number="SN-0001", lot_code="LOT-A"
    )

    validate_error(
        api_client.create_serial_unit(
            serial_unit_payload(
                product["id"],
                distributor["id"],
                serial_number="SN-0001",
                lot_code="LOT-B",
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_DUPLICATE_SERIAL.value,
    )

    rows, meta = validate_paginated(api_client.list_serial_units(BCM_HEADERS))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]


def test_a_matched_listing_on_an_unpermitted_channel_is_refused():
    """A matched capture must sit on a channel the agreement actually grants.

    PRD: "And when a `matched_reseller_id` is supplied, the observed `channel` must be
    one of the members of that reseller's currently governing `permitted_channels`; a
    marketplace listing from a reseller authorized only for its own website is rejected
    with `ERR_CHANNEL_NOT_PERMITTED`."

    Design: Corner/validations/matched_observation_on_a_channel_outside_the_agreement_rejected
    """
    world = _authorized_channel()
    pin_clock(CLOCK_AUG_20)

    validate_error(
        api_client.create_observation(
            observation_payload(
                world["product"]["id"],
                channel="RETAILER_SITE",
                seller_display_name="Acme Store",
                listing_url="https://retail.example/l/2",
                listed_price_cents=12000,
                observed_at=OBSERVED_AUG_18,
                evidence_hash=EVIDENCE_HASH_1,
                matched_reseller_id=world["reseller"]["id"],
            ),
            ANALYST_HEADERS,
        ),
        ApiErrorId.ERR_CHANNEL_NOT_PERMITTED.value,
    )

    assert read_agreement(world["agreement"]["id"])["permitted_channels"] == [
        "MARKETPLACE",
        "OWN_WEBSITE",
    ]
    _rows, meta = validate_paginated(api_client.list_observations(ANALYST_HEADERS))
    assert meta["total_count"] == 0


def test_an_agreement_omitting_the_resellers_primary_channel_is_refused():
    """Authorizing a marketplace seller for everything except marketplaces is incoherent.

    PRD: "`permitted_channels` must contain the reseller's own `primary_channel`, else
    the draft is rejected with `ERR_CHANNEL_NOT_PERMITTED` — it would be incoherent to
    authorize a marketplace seller for everything except marketplaces."

    Design: Corner/validations/agreement_omitting_the_primary_channel_rejected
    """
    policy = _published_policy()
    reseller = _acme()
    assert reseller["primary_channel"] == "MARKETPLACE"

    validate_error(
        api_client.create_agreement(
            agreement_payload(
                reseller["id"],
                policy["id"],
                permitted_channels=["OWN_WEBSITE"],
                quality_obligations=["AUTHENTICITY_LABELING"],
                term_ends_at=TERM_ENDS,
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_CHANNEL_NOT_PERMITTED.value,
    )

    _rows, meta = validate_paginated(api_client.list_agreements(BCM_HEADERS))
    assert meta["total_count"] == 0


def test_asserting_termination_on_a_first_notice_is_a_rung_mismatch():
    """A reseller who has never been warned cannot be terminated.

    PRD: "If the request asserted a `rung` and the asserted value differs from the
    computed one, the request is rejected with `ERR_LADDER_RUNG_MISMATCH`; when the
    request omits `rung`, the computed value is simply installed."

    Design: Corner/validations/requesting_termination_on_the_first_notice_rejected
    """
    world = _detected_first_breach(_authorized_channel())

    validate_error(
        api_client.issue_notice(
            notice_payload(
                world["reseller"]["id"],
                world["violation"]["id"],
                current_reseller_version(world["reseller"]["id"]),
                delivery_channel="CERTIFIED_MAIL",
                rung="TERMINATION",
            ),
            COUNSEL_HEADERS,
        ),
        ApiErrorId.ERR_LADDER_RUNG_MISMATCH.value,
    )

    assert read_violation(world["violation"]["id"])["status"] == "DETECTED"
    assert read_reseller(world["reseller"]["id"])["authorization_status"] == "AUTHORIZED"


def test_a_third_dispute_round_is_refused():
    """Two rejected rounds exhaust the dispute allowance.

    PRD: "Supplying a `dispute_reason` moves the violation `NOTICED → DISPUTED`,
    recording that reason and advancing the violation's `version`; it requires the
    violation to be `NOTICED` and requires `dispute_rounds` to be strictly below 2, else
    `ERR_DISPUTE_ROUNDS_EXHAUSTED`."

    Design: Corner/validations/third_dispute_round_rejected
    """
    world = _warned_acme()
    reseller_headers = make_reseller_headers(world["reseller"]["id"])
    for reason in ("The listing was a display error.", "The price feed lagged."):
        validate_success(
            api_client.dispute_violation(
                world["violation"]["id"],
                violation_dispute_payload(dispute_reason=reason),
                reseller_headers,
            )
        )
        validate_success(
            api_client.decide_violation_dispute(
                world["violation"]["id"],
                violation_dispute_decision_payload(
                    "REJECT", decision_reason="Screenshot evidence stands."
                ),
                BCM_HEADERS,
            )
        )

    validate_error(
        api_client.dispute_violation(
            world["violation"]["id"],
            violation_dispute_payload(dispute_reason="Third attempt"),
            reseller_headers,
        ),
        ApiErrorId.ERR_DISPUTE_ROUNDS_EXHAUSTED.value,
    )

    violation = read_violation(world["violation"]["id"])
    assert violation["dispute_rounds"] == 2
    assert violation["status"] == "NOTICED"
    assert_same_instant(
        violation["cure_deadline_at"],
        DISPUTE_DEADLINE_AFTER_TWO_ROUNDS,
        "cure_deadline_at",
    )


def test_a_channel_manager_may_not_issue_a_termination_notice():
    """Termination is reserved to counsel even for an otherwise legitimate issuer.

    PRD: "A notice whose computed `rung` is `TERMINATION` may only be issued by a
    `BrandLegalCounsel`; an attempt by a `BrandChannelManager` — who is otherwise a
    legitimate issuer of warnings and suspensions — is rejected with
    `ERR_TERMINATION_REQUIRES_COUNSEL`."

    Design: Corner/validations/termination_notice_issued_by_a_channel_manager_rejected
    """
    world = _suspended_acme_with_third_breach()

    validate_error(
        api_client.issue_notice(
            notice_payload(
                world["reseller"]["id"],
                world["violation3"]["id"],
                current_reseller_version(world["reseller"]["id"]),
                delivery_channel="CERTIFIED_MAIL",
                rung="TERMINATION",
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_TERMINATION_REQUIRES_COUNSEL.value,
    )

    assert read_reseller(world["reseller"]["id"])["authorization_status"] == "SUSPENDED"
    assert read_violation(world["violation3"]["id"])["status"] == "DETECTED"


def test_the_counsel_who_suspended_may_not_also_terminate():
    """The four-eyes rule keeps one individual from both suspending and terminating.

    PRD: "On top of that, the `X-User-ID` issuing the termination must be different from
    the `X-User-ID` recorded as `issued_by_user_id` on the reseller's governing
    suspension notice, so that the same individual cannot both suspend and then
    terminate the same partner; a match is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/termination_signed_by_the_suspension_issuer_rejected
    """
    world = _suspended_acme_with_third_breach(suspension_headers=COUNSEL_HEADERS)
    assert read_notice(world["notice2"]["id"])["issued_by_user_id"] == "counsel-1"

    validate_error(
        api_client.issue_notice(
            notice_payload(
                world["reseller"]["id"],
                world["violation3"]["id"],
                current_reseller_version(world["reseller"]["id"]),
                delivery_channel="CERTIFIED_MAIL",
                rung="TERMINATION",
            ),
            COUNSEL_HEADERS,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )

    assert read_reseller(world["reseller"]["id"])["authorization_status"] == "SUSPENDED"


def test_a_second_counsel_may_sign_the_termination():
    """With four eyes satisfied the termination lands and cuts off supply.

    PRD: "A `TERMINATION` notice — legal from `AUTHORIZED` or `SUSPENDED` — drives the
    reseller to `TERMINATED` on the authorization axis, `CUT_OFF` on the supply axis and
    `TERMINATION` as the `hold_reason`, stamps `terminated_at` with the current clock and
    clears `suspension_ends_at` to null."

    Design: Corner/validations/termination_signed_by_a_second_counsel_is_accepted
    """
    world = _suspended_acme_with_third_breach(suspension_headers=COUNSEL_HEADERS)

    notice = validate_success(
        api_client.issue_notice(
            notice_payload(
                world["reseller"]["id"],
                world["violation3"]["id"],
                current_reseller_version(world["reseller"]["id"]),
                delivery_channel="CERTIFIED_MAIL",
                rung="TERMINATION",
            ),
            COUNSEL_2_HEADERS,
        ),
        expected_status=201,
    )

    assert notice["rung"] == "TERMINATION"
    assert notice["issued_by_user_id"] == "counsel-2"
    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "TERMINATED"
    assert reseller["supply_status"] == "CUT_OFF"
    assert reseller["hold_reason"] == "TERMINATION"
    assert read_agreement(world["agreement"]["id"])["status"] == "TERMINATED"


def test_a_notice_is_refused_once_the_floor_has_been_dropped_to_the_listed_price():
    """The final recomputation at issuance can extinguish the breach entirely.

    PRD: "And the recomputed final points must be strictly greater than zero, else
    `ERR_NO_BREACH_AT_FINAL_FLOOR` — a violation that a retroactive exception has already
    lifted back above the floor is not noticeable even if it is still sitting in
    `DETECTED`."

    Design: Corner/validations/notice_after_the_floor_drops_below_the_listing_rejected
    """
    world = _detected_first_breach(_authorized_channel())
    assert world["violation"]["provisional_points"] == violation_points(
        STANDARD_FLOOR, 14000, "MARKETPLACE", 0
    ) == 3

    adjusted = validate_success(
        api_client.adjust_product(
            world["product"]["id"],
            product_adjustment_payload(standard_map_floor_cents=REDUCED_FLOOR),
            BCM_HEADERS,
        )
    )
    assert adjusted["standard_map_floor_cents"] == REDUCED_FLOOR

    validate_error(
        api_client.issue_notice(
            notice_payload(
                world["reseller"]["id"],
                world["violation"]["id"],
                current_reseller_version(world["reseller"]["id"]),
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_NO_BREACH_AT_FINAL_FLOOR.value,
    )

    violation = read_violation(world["violation"]["id"])
    assert violation["status"] == "DETECTED"
    assert violation["provisional_points"] == 3
    assert violation["assessed_points"] is None
    assert read_reseller(world["reseller"]["id"])["violation_points_total"] == 0


def test_an_override_floor_at_the_standard_floor_is_out_of_range():
    """An exception that does not lower the floor is not an exception.

    PRD: "For a `BUNDLE` or `PROMOTIONAL_EVENT` exception the installed floor is exactly
    the `requested_override_floor_cents` supplied on the request, but it must sit inside
    a permitted band: it must be strictly less than the product's
    `standard_map_floor_cents` — an "exception" that raises the floor is not an exception
    — and it must be at least the product's `standard_map_floor_cents` multiplied by 0.50
    and truncated downward to whole cents, so no exception may cut the floor by more than
    half. A figure outside that band is rejected with `ERR_OVERRIDE_FLOOR_OUT_OF_RANGE`."

    Design: Corner/validations/exception_approval_with_an_out_of_range_override_rejected
    """
    policy = _published_policy()
    product = _headphones(policy["id"])
    assert override_floor_lower_bound(STANDARD_FLOOR) == 7500

    exception = validate_success(
        api_client.create_exception(
            exception_payload(
                product["id"],
                exception_type="PROMOTIONAL_EVENT",
                starts_at="2026-09-01T00:00:00Z",
                ends_at="2026-09-10T00:00:00Z",
                channel_scope="ALL",
                requested_override_floor_cents=STANDARD_FLOOR,
                dealer_input_source="BRAND_MARKETING_PLAN",
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )

    validate_error(
        api_client.decide_exception(
            exception["id"],
            exception_decision_payload(
                "APPROVE", decision_reason="Promotional depth reviewed"
            ),
            COUNSEL_HEADERS,
        ),
        ApiErrorId.ERR_OVERRIDE_FLOOR_OUT_OF_RANGE.value,
    )

    assert read_exception(exception["id"])["status"] == "REQUESTED"
    assert read_product(product["id"])["open_exception_count"] == 0


# --------------------------------------------------------------------------- #
# Priority 13 — the fiscal ceiling, checked last
# --------------------------------------------------------------------------- #
def test_a_chargeback_above_the_annual_cap_is_refused():
    """Five units at the entry tier would carry the balance past the ceiling.

    PRD: "The fiscal ceiling is checked last of all, after every other rule has passed:
    the distributor's current `chargeback_balance_cents` plus the new `amount_cents` must
    not exceed its `annual_chargeback_cap_cents`, with equality explicitly allowed.
    Exceeding it is rejected with `ERR_CHARGEBACK_CAP_EXCEEDED`."

    Design: Corner/validations/chargeback_over_the_annual_cap_rejected
    """
    world = _capped_trace(10000, "Capped Freight Inc")
    assert tier_rate_for_score(0.0) * 5 == 12500

    validate_error(
        api_client.assess_chargeback(
            chargeback_payload(
                world["distributor"]["id"],
                world["purchase"]["id"],
                current_distributor_version(world["distributor"]["id"]),
                diverted_units=5,
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_CHARGEBACK_CAP_EXCEEDED.value,
    )

    distributor = read_distributor(world["distributor"]["id"])
    assert distributor["chargeback_balance_cents"] == 0
    assert distributor["diversion_score"] == 0
    assert distributor["standing"] == "GOOD"


def test_a_chargeback_landing_exactly_on_the_annual_cap_is_assessed():
    """Equality with the ceiling is explicitly allowed.

    PRD: "The fiscal ceiling is checked last of all, after every other rule has passed:
    the distributor's current `chargeback_balance_cents` plus the new `amount_cents` must
    not exceed its `annual_chargeback_cap_cents`, with equality explicitly allowed.
    Exceeding it is rejected with `ERR_CHARGEBACK_CAP_EXCEEDED`."

    Design: Corner/validations/chargeback_exactly_at_the_annual_cap_is_accepted
    """
    world = _capped_trace(10000, "Capped Freight Inc")
    expected_amount = tier_rate_for_score(0.0) * 4
    assert expected_amount == 10000

    chargeback = validate_success(
        api_client.assess_chargeback(
            chargeback_payload(
                world["distributor"]["id"],
                world["purchase"]["id"],
                current_distributor_version(world["distributor"]["id"]),
                diverted_units=4,
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )

    assert chargeback["amount_cents"] == expected_amount
    distributor = read_distributor(world["distributor"]["id"])
    assert distributor["chargeback_balance_cents"] == 10000
    assert distributor["annual_chargeback_cap_cents"] == 10000
    assert distributor["diversion_score"] == score_delta(4) == 10.0
    assert distributor["standing"] == standing_for_score(10.0) == "PROBATION"
