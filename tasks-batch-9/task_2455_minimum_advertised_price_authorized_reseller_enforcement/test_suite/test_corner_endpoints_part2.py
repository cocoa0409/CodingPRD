"""Endpoint breadth: agreements, observations, violations and notices.

Every test drives one declared operation on the contracting and enforcement
spine and checks the fields the PRD says that operation writes, together with
the filter parameters §2.10 requires each collection to expose.
"""
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    ANALYST_HEADERS,
    BCM_HEADERS,
    COUNSEL_HEADERS,
    api_client,
    make_reseller_headers,
)
from test_helpers.assertions import (
    assert_same_instant,
    deviation_pct,
    issued_rung,
    violation_points,
)
from test_helpers.constants import EVIDENCE_HASH_1, EVIDENCE_HASH_3
from test_helpers.factories import (
    agreement_payload,
    agreement_response_payload,
    cure_submission_payload,
    notice_payload,
    observation_payload,
    rescind_payload,
    violation_dispute_decision_payload,
    violation_dispute_payload,
)
from test_helpers.fixtures import (
    capture_observation,
    create_active_agreement,
    create_authorized_reseller,
    create_countersigned_agreement,
    create_detected_violation,
    create_product,
    create_published_policy,
    create_reseller,
    create_sent_agreement,
    current_reseller_version,
    evaluate_observation,
    issue_notice,
    pin_clock,
    read_notice,
    read_observation,
    read_reseller,
    read_violation,
)

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_20 = "2026-08-20T00:00:00Z"
OBSERVED_AUG_18 = "2026-08-18T00:00:00Z"
OBSERVED_AUG_19 = "2026-08-19T00:00:00Z"
CURE_DEADLINE = "2026-08-30T00:00:00Z"
TERM_ENDS = "2027-06-30T00:00:00Z"
SUSPENSION_STARTS = "2026-09-01T00:00:00Z"
SUSPENSION_ENDS = "2026-09-10T00:00:00Z"


def _setup_policy_and_reseller():
    """A published policy, its product and one applied reseller."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01, policy_code="MAP-2026-A")
    product = create_product(
        policy["id"], sku="SKU-AUDIO-1", name="Studio Headphones", msrp_cents=20000,
        standard_map_floor_cents=15000,
    )
    reseller = create_reseller(
        legal_name="Acme Retail LLC",
        contact_email="ops@acme.example",
        primary_channel="MARKETPLACE",
    )
    return policy, product, reseller


# --------------------------------------------------------------------------- #
# ResellerAgreement
# --------------------------------------------------------------------------- #
def test_drafting_an_agreement_records_both_foreign_keys_and_the_price_terms_flag():
    """The draft carries the channel grant while every lifecycle stamp stays null.

    PRD: "A fresh agreement is created in status `DRAFT` with
    `non_negotiation_acknowledged` false and with `sent_at`, `countersigned_at`,
    `countersigned_by_user_id`, `activated_at` and `closed_reason` all null."

    Design: Corner/endpoints/create_agreement_links_reseller_and_policy
    """
    policy, _product, reseller = _setup_policy_and_reseller()

    agreement = validate_success(
        api_client.create_agreement(
            agreement_payload(
                reseller["id"],
                policy["id"],
                permitted_channels=["MARKETPLACE", "OWN_WEBSITE"],
                quality_obligations=["AUTHENTICITY_LABELING"],
                term_ends_at=TERM_ENDS,
            ),
            BCM_HEADERS,
        ),
        201,
    )

    assert agreement["status"] == "DRAFT"
    assert agreement["reseller_id"] == reseller["id"]
    assert agreement["policy_id"] == policy["id"]
    assert agreement["price_terms_included"] is False
    assert agreement["non_negotiation_acknowledged"] is False
    assert agreement["sent_at"] is None
    assert agreement["countersigned_at"] is None
    assert agreement["activated_at"] is None
    assert agreement["closed_reason"] is None
    assert read_reseller(reseller["id"])["authorization_status"] == "APPLIED"


def test_sending_an_agreement_moves_the_reseller_onto_pending_agreement():
    """Sending stamps the agreement and drives the reseller's authorization axis.

    PRD: "The transition stamps `sent_at` with the current logical clock, advances the
    agreement's `version`, and moves the reseller's authorization axis
    `APPLIED → PENDING_AGREEMENT` while advancing the reseller's `version` as well."
    "The reseller's supply axis is deliberately left on `HOLD` with reason
    `PENDING_AUTHORIZATION`."

    Design: Corner/endpoints/send_agreement_moves_the_reseller_to_pending_agreement
    """
    policy, _product, reseller = _setup_policy_and_reseller()
    agreement = validate_success(
        api_client.create_agreement(
            agreement_payload(
                reseller["id"], policy["id"], permitted_channels=["MARKETPLACE", "OWN_WEBSITE"],
                term_ends_at=TERM_ENDS,
            ),
            BCM_HEADERS,
        ),
        201,
    )

    sent = validate_success(api_client.send_agreement(agreement["id"], BCM_HEADERS))

    assert sent["status"] == "SENT"
    assert_same_instant(sent["sent_at"], CLOCK_AUG_01, "sent_at")
    assert sent["version"] == agreement["version"] + 1

    moved = read_reseller(reseller["id"])
    assert moved["authorization_status"] == "PENDING_AGREEMENT"
    assert moved["supply_status"] == "HOLD"
    assert moved["hold_reason"] == "PENDING_AUTHORIZATION"
    assert moved["version"] == reseller["version"] + 1


def test_countersigning_records_the_acknowledgement_and_leaves_the_reseller_alone():
    """The reseller row is untouched by its own countersignature.

    PRD: "A `decision` of `COUNTERSIGN` moves it `SENT → COUNTERSIGNED`: it stamps
    `countersigned_at` with the current clock, records `countersigned_by_user_id` from
    the acting reseller's `X-User-ID`, and sets `non_negotiation_acknowledged` from the
    supplied `non_negotiation_acknowledged` flag." "Countersignature changes **no**
    reseller field: the authorization axis stays on `PENDING_AGREEMENT` and advances
    only at activation, so only the agreement's `version` moves."

    Design: Corner/endpoints/respond_countersign_requires_the_acknowledgement
    """
    policy, _product, reseller = _setup_policy_and_reseller()
    agreement = create_sent_agreement(
        reseller["id"], policy["id"], permitted_channels=["MARKETPLACE", "OWN_WEBSITE"],
        term_ends_at=TERM_ENDS,
    )
    pending = read_reseller(reseller["id"])

    countersigned = validate_success(
        api_client.respond_agreement(
            agreement["id"],
            agreement_response_payload("COUNTERSIGN", non_negotiation_acknowledged=True),
            make_reseller_headers(reseller["id"]),
        )
    )

    assert countersigned["status"] == "COUNTERSIGNED"
    assert_same_instant(countersigned["countersigned_at"], CLOCK_AUG_01, "countersigned_at")
    assert countersigned["countersigned_by_user_id"] == reseller["id"]
    assert countersigned["non_negotiation_acknowledged"] is True
    assert countersigned["version"] == agreement["version"] + 1

    unchanged = read_reseller(reseller["id"])
    assert unchanged["authorization_status"] == "PENDING_AGREEMENT"
    assert unchanged["version"] == pending["version"]


def test_declining_an_agreement_rolls_the_reseller_back_to_applied():
    """Only the decline branch touches the reseller, and it reverses the send.

    PRD: "Unlike countersignature, declining *does* touch the reseller: its
    `authorization_status` is rolled back to `APPLIED`, its `supply_status` set to `HOLD`
    and its `hold_reason` set to `PENDING_AUTHORIZATION`, with its `version` advanced."

    Design: Corner/endpoints/respond_decline_rolls_the_reseller_back
    """
    policy, _product, reseller = _setup_policy_and_reseller()
    agreement = create_sent_agreement(
        reseller["id"], policy["id"], permitted_channels=["MARKETPLACE", "OWN_WEBSITE"],
        term_ends_at=TERM_ENDS,
    )

    declined = validate_success(
        api_client.respond_agreement(
            agreement["id"],
            agreement_response_payload(
                "DECLINE", decline_reason="Channel restrictions are unworkable"
            ),
            make_reseller_headers(reseller["id"]),
        )
    )

    assert declined["status"] == "DECLINED"
    assert declined["closed_reason"] == "Channel restrictions are unworkable"

    rolled_back = read_reseller(reseller["id"])
    assert rolled_back["authorization_status"] == "APPLIED"
    assert rolled_back["supply_status"] == "HOLD"
    assert rolled_back["hold_reason"] == "PENDING_AUTHORIZATION"


def test_activating_an_agreement_opens_the_supply_track_in_one_write():
    """Activation is the single act that moves both reseller axes together.

    PRD: "Activation stamps `activated_at` with the current clock and advances the
    agreement's `version`, and it moves the reseller on both axes at once:
    `authorization_status` to `AUTHORIZED`, `supply_status` to `OPEN`, `hold_reason` to
    `NONE`, with the reseller's `version` advanced."

    Design: Corner/endpoints/activate_agreement_opens_the_supply_track
    """
    policy, _product, reseller = _setup_policy_and_reseller()
    agreement = create_countersigned_agreement(
        reseller["id"], policy["id"], permitted_channels=["MARKETPLACE", "OWN_WEBSITE"],
        term_ends_at=TERM_ENDS,
    )

    activated = validate_success(api_client.activate_agreement(agreement["id"], BCM_HEADERS))

    assert activated["status"] == "ACTIVE"
    assert_same_instant(activated["activated_at"], CLOCK_AUG_01, "activated_at")
    assert activated["version"] == agreement["version"] + 1

    authorized = read_reseller(reseller["id"])
    assert authorized["authorization_status"] == "AUTHORIZED"
    assert authorized["supply_status"] == "OPEN"
    assert authorized["hold_reason"] == "NONE"


def test_reading_one_agreement_returns_the_channel_grant_and_the_term():
    """The two substantive restrictions and the expiry instant read back unchanged.

    PRD: "Agreements are readable individually, and the collection may be filtered by
    `reseller_id`, by `policy_id` or by `status`."

    Design: Corner/endpoints/read_one_agreement_returns_the_channel_grant
    """
    policy, _product, reseller = _setup_policy_and_reseller()
    agreement = create_active_agreement(
        reseller["id"], policy["id"], permitted_channels=["MARKETPLACE", "OWN_WEBSITE"],
        quality_obligations=["AUTHENTICITY_LABELING"], term_ends_at=TERM_ENDS,
    )

    read = validate_success(api_client.get_agreement(agreement["id"], ANALYST_HEADERS))

    assert read["permitted_channels"] == ["MARKETPLACE", "OWN_WEBSITE"]
    assert read["quality_obligations"] == ["AUTHENTICITY_LABELING"]
    assert_same_instant(read["term_ends_at"], TERM_ENDS, "term_ends_at")
    assert read["status"] == "ACTIVE"


def test_the_agreement_collection_filters_by_counterparty_policy_and_status():
    """Two agreements on one policy separate cleanly by reseller and by status.

    PRD: "Agreements are readable individually, and the collection may be filtered by
    `reseller_id`, by `policy_id` or by `status`."

    Design: Corner/endpoints/list_agreements_filters_by_reseller_and_status
    """
    policy, _product, acme = _setup_policy_and_reseller()
    acme_agreement = create_active_agreement(
        acme["id"], policy["id"], permitted_channels=["MARKETPLACE", "OWN_WEBSITE"],
        term_ends_at=TERM_ENDS,
    )
    bravo = create_reseller(
        legal_name="Bravo Outlets Inc",
        contact_email="ops@bravo.example",
        primary_channel="RETAILER_SITE",
    )
    bravo_agreement = create_sent_agreement(
        bravo["id"], policy["id"], permitted_channels=["RETAILER_SITE"], term_ends_at=TERM_ENDS
    )

    mine, mine_meta = validate_paginated(
        api_client.list_agreements(
            BCM_HEADERS, params={"reseller_id": acme["id"], "limit": 10, "offset": 0}
        )
    )
    assert mine_meta["total_count"] == 1
    assert [row["id"] for row in mine] == [acme_agreement["id"]]

    sent, sent_meta = validate_paginated(
        api_client.list_agreements(BCM_HEADERS, params={"status": "SENT"})
    )
    assert sent_meta["total_count"] == 1
    assert [row["id"] for row in sent] == [bravo_agreement["id"]]

    active, active_meta = validate_paginated(
        api_client.list_agreements(
            BCM_HEADERS, params={"policy_id": policy["id"], "status": "ACTIVE"}
        )
    )
    assert active_meta["total_count"] == 1
    assert [row["id"] for row in active] == [acme_agreement["id"]]

    by_policy, by_policy_meta = validate_paginated(
        api_client.list_agreements(BCM_HEADERS, params={"policy_id": policy["id"]})
    )
    assert by_policy_meta["total_count"] == 2


# --------------------------------------------------------------------------- #
# PriceObservation
# --------------------------------------------------------------------------- #
def _setup_monitored_channel():
    """A published policy, its product and one AUTHORIZED marketplace reseller."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01, policy_code="MAP-2026-A")
    product = create_product(
        policy["id"], sku="SKU-AUDIO-1", name="Studio Headphones", msrp_cents=20000,
        standard_map_floor_cents=15000,
    )
    reseller, agreement = create_authorized_reseller(
        policy["id"],
        reseller_overrides={
            "legal_name": "Acme Retail LLC",
            "contact_email": "ops@acme.example",
            "primary_channel": "MARKETPLACE",
        },
        agreement_overrides={
            "permitted_channels": ["MARKETPLACE", "OWN_WEBSITE"],
            "term_ends_at": TERM_ENDS,
        },
    )
    return policy, product, reseller, agreement


def test_capturing_a_listing_opens_it_in_captured_with_every_computed_field_null():
    """Capture is pure evidence: nothing is priced until evaluation runs.

    PRD: "The row is created with `evaluation_status` `CAPTURED`,
    `unauthorized_seller_confirmed` false, `evidence_captured_by_user_id` stamped from
    the capturing analyst's `X-User-ID`, and all five computed money fields —
    `allocated_component_price_cents`, `effective_advertised_price_cents`,
    `effective_map_floor_cents`, `deviation_cents` and `deviation_pct` — still null."

    Design: Corner/endpoints/create_price_observation_starts_in_captured
    """
    _policy, product, reseller, _agreement = _setup_monitored_channel()
    pin_clock(CLOCK_AUG_20)

    observation = validate_success(
        api_client.create_observation(
            observation_payload(
                product["id"],
                channel="MARKETPLACE",
                marketplace_name="MegaMart",
                seller_display_name="Acme Store",
                listing_url="https://mkt.example/l/1",
                listed_price_cents=14000,
                observed_at=OBSERVED_AUG_18,
                evidence_hash=EVIDENCE_HASH_1,
                matched_reseller_id=reseller["id"],
            ),
            ANALYST_HEADERS,
        ),
        201,
    )

    assert observation["evaluation_status"] == "CAPTURED"
    assert observation["unauthorized_seller_confirmed"] is False
    assert observation["evidence_captured_by_user_id"] == "analyst-1"
    assert observation["marketplace_name"] == "MegaMart"
    assert observation["matched_reseller_id"] == reseller["id"]
    assert observation["shipping_cents"] == 0
    assert observation["auto_coupon_cents"] == 0
    assert observation["promo_code_cents"] == 0
    assert observation["is_bundle"] is False
    for field in (
        "allocated_component_price_cents",
        "effective_advertised_price_cents",
        "effective_map_floor_cents",
        "deviation_cents",
        "deviation_pct",
    ):
        assert observation[field] is None, f"{field} should still be null at capture"


def test_evaluating_a_breach_returns_the_whole_pricing_verdict_in_one_response():
    """The verdict reports the floor, its source, both deviations and the new violation.

    PRD: "The evaluation response reports `observation_id`, the resulting
    `evaluation_status`, `allocated_component_price_cents`,
    `effective_advertised_price_cents`, `effective_map_floor_cents`, the `floor_source`
    that produced the floor, `deviation_cents`, `deviation_pct`, `cited_policy_id`, the
    `violation_id` of the violation opened (null when none was), `provisional_points`,
    and `unauthorized_seller_confirmed`."

    Design: Corner/endpoints/evaluate_observation_emits_the_full_pricing_verdict
    """
    policy, product, reseller, _agreement = _setup_monitored_channel()
    pin_clock(CLOCK_AUG_20)
    observation = capture_observation(
        product["id"],
        listing_url="https://mkt.example/l/1",
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
        matched_reseller_id=reseller["id"],
    )

    evaluation = validate_success(
        api_client.evaluate_observation(observation["id"], ANALYST_HEADERS)
    )

    assert evaluation["observation_id"] == observation["id"]
    assert evaluation["evaluation_status"] == "EVALUATED_BREACH"
    assert evaluation["allocated_component_price_cents"] is None
    assert evaluation["effective_advertised_price_cents"] == 14000
    assert evaluation["effective_map_floor_cents"] == 15000
    assert evaluation["floor_source"] == "STANDARD"
    assert evaluation["deviation_cents"] == 1000
    assert evaluation["deviation_pct"] == deviation_pct(15000, 1000) == 0.0667
    assert evaluation["cited_policy_id"] == policy["id"]
    assert evaluation["violation_id"] is not None
    assert evaluation["provisional_points"] == violation_points(15000, 14000, "MARKETPLACE", 0) == 3
    assert evaluation["unauthorized_seller_confirmed"] is False

    violation = read_violation(evaluation["violation_id"])
    assert violation["status"] == "DETECTED"
    assert violation["cited_policy_id"] == policy["id"]
    assert violation["reseller_id"] == reseller["id"]


def test_reading_one_observation_returns_the_evidence_exactly_as_captured():
    """The evidence chain fields survive the round trip.

    PRD: "Observations are readable one at a time, and the collection may be filtered by
    `product_id`, by `matched_reseller_id`, by `evaluation_status` or by `channel`."

    Design: Corner/endpoints/read_one_observation_returns_the_stored_evidence
    """
    _policy, product, reseller, _agreement = _setup_monitored_channel()
    pin_clock(CLOCK_AUG_20)
    observation = capture_observation(
        product["id"],
        seller_display_name="Acme Store",
        listing_url="https://mkt.example/l/1",
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=EVIDENCE_HASH_1,
        matched_reseller_id=reseller["id"],
    )

    read = read_observation(observation["id"])

    assert read["product_id"] == product["id"]
    assert read["seller_display_name"] == "Acme Store"
    assert read["listing_url"] == "https://mkt.example/l/1"
    assert read["listed_price_cents"] == 14000
    assert read["evidence_hash"] == EVIDENCE_HASH_1
    assert_same_instant(read["observed_at"], OBSERVED_AUG_18, "observed_at")
    assert read["matched_reseller_id"] == reseller["id"]


def test_the_observation_collection_filters_by_verdict_and_by_channel():
    """A breach and a compliant capture on the same channel separate by status.

    PRD: "Observations are readable one at a time, and the collection may be filtered by
    `product_id`, by `matched_reseller_id`, by `evaluation_status` or by `channel`."

    Design: Corner/endpoints/list_observations_filters_by_evaluation_status_and_channel
    """
    _policy, product, reseller, _agreement = _setup_monitored_channel()
    pin_clock(CLOCK_AUG_20)
    breach = capture_observation(
        product["id"],
        listing_url="https://mkt.example/l/1",
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=EVIDENCE_HASH_1,
        matched_reseller_id=reseller["id"],
    )
    evaluate_observation(breach["id"])
    compliant = capture_observation(
        product["id"],
        listing_url="https://mkt.example/l/ok",
        listed_price_cents=15000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=EVIDENCE_HASH_3,
        matched_reseller_id=reseller["id"],
    )
    evaluate_observation(compliant["id"])

    breaches, breach_meta = validate_paginated(
        api_client.list_observations(
            ANALYST_HEADERS,
            params={"evaluation_status": "EVALUATED_BREACH", "limit": 10, "offset": 0},
        )
    )
    assert breach_meta["total_count"] == 1
    assert [row["id"] for row in breaches] == [breach["id"]]

    compliants, compliant_meta = validate_paginated(
        api_client.list_observations(
            ANALYST_HEADERS, params={"evaluation_status": "EVALUATED_COMPLIANT"}
        )
    )
    assert compliant_meta["total_count"] == 1
    assert [row["id"] for row in compliants] == [compliant["id"]]

    marketplace, marketplace_meta = validate_paginated(
        api_client.list_observations(
            ANALYST_HEADERS, params={"channel": "MARKETPLACE", "product_id": product["id"]}
        )
    )
    assert marketplace_meta["total_count"] == 2

    mine, mine_meta = validate_paginated(
        api_client.list_observations(
            ANALYST_HEADERS,
            params={"matched_reseller_id": reseller["id"], "channel": "MARKETPLACE"},
        )
    )
    assert mine_meta["total_count"] == 2
    assert len(mine) == 2


# --------------------------------------------------------------------------- #
# Violation
# --------------------------------------------------------------------------- #
def _setup_noticed_violation(listed_price_cents=14000, listing_url="https://mkt.example/l/1"):
    """One ISSUED WARNING notice worth three points against Acme."""
    policy, product, reseller, _agreement = _setup_monitored_channel()
    pin_clock(CLOCK_AUG_20)
    violation, observation, _evaluation = create_detected_violation(
        product["id"],
        reseller["id"],
        listed_price_cents=listed_price_cents,
        observed_at=OBSERVED_AUG_18,
        listing_url=listing_url,
    )
    notice = issue_notice(reseller["id"], violation["id"])
    return policy, product, reseller, violation, observation, notice


def test_curing_a_noticed_violation_satisfies_its_notice_and_keeps_the_points():
    """One call closes the violation and the notice without refunding the ledger.

    PRD: "It moves the violation `NOTICED → CURED` with `resolution_reason` set to
    `CURE_ACCEPTED` and its `version` advanced, and it moves the latest non-rescinded
    notice for that violation to `SATISFIED` with `closed_reason` recorded as
    `VIOLATION_CURED` and that notice's `version` advanced." "What curing does **not** do
    is refund points: the `assessed_points` stay in the reseller's
    `violation_points_total`, because a cured violation still counts toward the ladder."

    Design: Corner/endpoints/cure_submission_satisfies_the_notice_in_one_call
    """
    _policy, _product, reseller, violation, _observation, notice = _setup_noticed_violation()

    cured = validate_success(
        api_client.submit_cure(
            violation["id"],
            cure_submission_payload(
                cure_evidence_url="https://mkt.example/l/1?fixed", corrected_price_cents=15000
            ),
            make_reseller_headers(reseller["id"]),
        )
    )

    assert cured["status"] == "CURED"
    assert cured["resolution_reason"] == "CURE_ACCEPTED"
    assert cured["assessed_points"] == 3

    assert read_notice(notice["id"])["status"] == "SATISFIED"
    assert read_notice(notice["id"])["closed_reason"] == "VIOLATION_CURED"
    assert read_reseller(reseller["id"])["violation_points_total"] == 3


def test_opening_a_dispute_does_not_spend_a_dispute_round():
    """The counter tracks rejected rounds, so it is still zero after the first dispute.

    PRD: "Supplying a `dispute_reason` moves the violation `NOTICED → DISPUTED`,
    recording that reason and advancing the violation's `version`; it requires the
    violation to be `NOTICED` and requires `dispute_rounds` to be strictly below 2, else
    `ERR_DISPUTE_ROUNDS_EXHAUSTED`." "Note that the dispute itself does not increment
    `dispute_rounds` — that counter tracks disputes that have already been *rejected*."

    Design: Corner/endpoints/dispute_endpoint_pauses_the_cure_clock
    """
    _policy, _product, reseller, violation, _observation, notice = _setup_noticed_violation()

    disputed = validate_success(
        api_client.dispute_violation(
            violation["id"],
            violation_dispute_payload(
                dispute_reason="Listing was a third-party clone of our storefront"
            ),
            make_reseller_headers(reseller["id"]),
        )
    )

    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_rounds"] == 0
    assert disputed["assessed_points"] == 3
    assert read_notice(notice["id"])["status"] == "ISSUED"
    assert read_reseller(reseller["id"])["violation_points_total"] == 3


def test_a_sustained_dispute_voids_the_violation_and_rescinds_the_notice():
    """A SUSTAIN decision writes three rows and empties the ledger.

    PRD: "A `decision` of `SUSTAIN` moves it `DISPUTED → VOIDED`: `resolution_reason` is
    set to `DISPUTE_SUSTAINED`; the `assessed_points` are subtracted from the reseller's
    `violation_points_total` and then `assessed_points`, `assessed_floor_cents` and
    `cure_deadline_at` are all cleared to null with the reseller's `version` advanced;
    the latest non-rescinded notice for that violation moves to `RESCINDED`, which —
    when that notice's `rung` was `SUSPENSION` — reinstates the reseller as described
    below; and the violation's `version` is advanced."

    Design: Corner/endpoints/dispute_decision_sustain_voids_and_rescinds
    """
    _policy, _product, reseller, violation, _observation, notice = _setup_noticed_violation()
    validate_success(
        api_client.dispute_violation(
            violation["id"],
            violation_dispute_payload(
                dispute_reason="Listing was a third-party clone of our storefront"
            ),
            make_reseller_headers(reseller["id"]),
        )
    )

    sustained = validate_success(
        api_client.decide_violation_dispute(
            violation["id"],
            violation_dispute_decision_payload(
                "SUSTAIN", decision_reason="Listing belonged to an unaffiliated storefront"
            ),
            BCM_HEADERS,
        )
    )

    assert sustained["status"] == "VOIDED"
    assert sustained["resolution_reason"] == "DISPUTE_SUSTAINED"
    assert sustained["assessed_points"] is None
    assert sustained["assessed_floor_cents"] is None
    assert sustained["cure_deadline_at"] is None
    assert read_notice(notice["id"])["status"] == "RESCINDED"
    assert read_reseller(reseller["id"])["violation_points_total"] == 0


def test_a_noticed_violation_carries_both_the_provisional_and_the_assessed_snapshot():
    """Issuance freezes the final floor and points and sets the cure deadline.

    PRD: "The violation moves `DETECTED → NOTICED`: its `assessed_floor_cents` and
    `assessed_points` are set from the final recomputation, its `cure_deadline_at` is set
    to the current logical clock plus the cited policy's `cure_window_days`, and its
    `version` is advanced."

    Design: Corner/endpoints/read_one_violation_returns_the_assessed_snapshot
    """
    _policy, _product, _reseller, violation, observation, _notice = _setup_noticed_violation()

    read = validate_success(api_client.get_violation(violation["id"], COUNSEL_HEADERS))

    assert read["status"] == "NOTICED"
    assert read["observation_id"] == observation["id"]
    assert read["provisional_floor_cents"] == 15000
    assert read["provisional_points"] == violation_points(15000, 14000, "MARKETPLACE", 0) == 3
    assert read["assessed_floor_cents"] == 15000
    assert read["assessed_points"] == 3
    assert_same_instant(read["cure_deadline_at"], CURE_DEADLINE, "cure_deadline_at")
    assert read["dispute_rounds"] == 0


def test_the_violation_collection_filters_by_reseller_status_and_observation():
    """A noticed row and a still-detected row on one reseller separate by status.

    PRD: "Violations are readable individually and as a collection filtered by
    `observation_id`, `reseller_id`, `cited_policy_id` or `status`."

    Design: Corner/endpoints/list_violations_filters_by_reseller_and_status
    """
    policy, product, reseller, noticed, _observation, _notice = _setup_noticed_violation()
    detected, detected_observation, _evaluation = create_detected_violation(
        product["id"],
        reseller["id"],
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_19,
        listing_url="https://mkt.example/l/3",
        evidence_hash=EVIDENCE_HASH_3,
    )

    mine, mine_meta = validate_paginated(
        api_client.list_violations(
            BCM_HEADERS, params={"reseller_id": reseller["id"], "limit": 10, "offset": 0}
        )
    )
    assert mine_meta["total_count"] == 2
    assert {row["id"] for row in mine} == {noticed["id"], detected["id"]}

    still_noticed, noticed_meta = validate_paginated(
        api_client.list_violations(
            BCM_HEADERS, params={"reseller_id": reseller["id"], "status": "NOTICED"}
        )
    )
    assert noticed_meta["total_count"] == 1
    assert [row["id"] for row in still_noticed] == [noticed["id"]]

    open_rows, open_meta = validate_paginated(
        api_client.list_violations(BCM_HEADERS, params={"status": "DETECTED"})
    )
    assert open_meta["total_count"] == 1
    assert [row["id"] for row in open_rows] == [detected["id"]]

    by_observation, by_observation_meta = validate_paginated(
        api_client.list_violations(
            BCM_HEADERS, params={"observation_id": detected_observation["id"]}
        )
    )
    assert by_observation_meta["total_count"] == 1
    assert [row["id"] for row in by_observation] == [detected["id"]]

    by_policy, by_policy_meta = validate_paginated(
        api_client.list_violations(BCM_HEADERS, params={"cited_policy_id": policy["id"]})
    )
    assert by_policy_meta["total_count"] == 2


# --------------------------------------------------------------------------- #
# EnforcementNotice
# --------------------------------------------------------------------------- #
def test_issuing_a_notice_mints_the_ladder_row_and_notices_the_violation():
    """The notice is created ISSUED with the computed rung and the issuer stamped.

    PRD: "And the notice itself is created in status `ISSUED`, carrying the computed
    `rung`, the snapshotted `cumulative_points_at_issue`, an `assessed_points` mirroring
    the figure charged onto the violation, and `issued_by_user_id` stamped from the
    issuer's `X-User-ID`, with `acknowledged_at` and `closed_reason` null."

    Design: Corner/endpoints/issue_notice_links_reseller_violation_and_version
    """
    _policy, product, reseller, _agreement = _setup_monitored_channel()
    pin_clock(CLOCK_AUG_20)
    violation, _observation, _evaluation = create_detected_violation(
        product["id"],
        reseller["id"],
        listed_price_cents=14000,
        observed_at=OBSERVED_AUG_18,
        listing_url="https://mkt.example/l/1",
    )

    notice = validate_success(
        api_client.issue_notice(
            notice_payload(
                reseller["id"],
                violation["id"],
                current_reseller_version(reseller["id"]),
                delivery_channel="EMAIL",
            ),
            BCM_HEADERS,
        ),
        201,
    )

    assert notice["status"] == "ISSUED"
    assert notice["rung"] == "WARNING"
    assert notice["reseller_id"] == reseller["id"]
    assert notice["violation_id"] == violation["id"]
    assert notice["issued_by_user_id"] == "bcm-1"
    assert notice["assessed_points"] == violation_points(15000, 14000, "MARKETPLACE", 0) == 3
    assert notice["cumulative_points_at_issue"] == 3
    assert notice["delivery_channel"] == "EMAIL"
    assert notice["acknowledged_at"] is None
    assert notice["closed_reason"] is None
    assert read_violation(violation["id"])["status"] == "NOTICED"


def test_acknowledging_a_notice_stamps_the_clock_and_changes_nothing_else():
    """Acknowledgement is bookkeeping on the notice alone.

    PRD: "A reseller may acknowledge a notice, moving it `ISSUED → ACKNOWLEDGED` with
    `acknowledged_at` stamped from the current clock and the notice's `version`
    advanced." "Acknowledgement is bookkeeping; it changes nothing about the underlying
    violation or the ladder, but an `ACKNOWLEDGED` notice still counts as served when
    the rung ceiling is computed."

    Design: Corner/endpoints/acknowledge_notice_stamps_the_timestamp
    """
    _policy, _product, reseller, violation, _observation, notice = _setup_noticed_violation()

    acknowledged = validate_success(
        api_client.acknowledge_notice(notice["id"], make_reseller_headers(reseller["id"]))
    )

    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert_same_instant(acknowledged["acknowledged_at"], CLOCK_AUG_20, "acknowledged_at")
    assert acknowledged["version"] == notice["version"] + 1
    assert read_violation(violation["id"])["status"] == "NOTICED"
    assert read_reseller(reseller["id"])["violation_points_total"] == 3


def test_rescinding_a_warning_returns_the_violation_to_detected():
    """Rescission reverses the ledger entry but keeps the evidence noticeable.

    PRD: "Otherwise the notice moves to `RESCINDED` with `closed_reason` recorded from
    the supplied reason and its `version` advanced, and the reversal reaches back into
    the violation: the cited violation is returned to status `DETECTED` with
    `assessed_points`, `assessed_floor_cents` and `cure_deadline_at` all cleared to
    null, and the notice's `assessed_points` are subtracted from the reseller's
    `violation_points_total`."

    Design: Corner/endpoints/rescind_warning_notice_reopens_the_violation
    """
    _policy, _product, reseller, violation, _observation, notice = _setup_noticed_violation()

    rescinded = validate_success(
        api_client.rescind_notice(
            notice["id"],
            rescind_payload(rescinded_reason="Storefront attribution corrected"),
            COUNSEL_HEADERS,
        )
    )

    assert rescinded["status"] == "RESCINDED"
    assert rescinded["closed_reason"] == "Storefront attribution corrected"

    reopened = read_violation(violation["id"])
    assert reopened["status"] == "DETECTED"
    assert reopened["assessed_points"] is None
    assert reopened["assessed_floor_cents"] is None
    assert reopened["cure_deadline_at"] is None
    assert read_reseller(reseller["id"])["violation_points_total"] == 0


def test_reading_one_notice_returns_the_rung_and_the_cumulative_snapshot():
    """The notice keeps the figures the ladder used when it was issued.

    PRD: "Read the reseller's `violation_points_total` *before* this notice's points are
    added, then add the final points once to obtain the cumulative figure recorded on
    the notice as `cumulative_points_at_issue`."

    Design: Corner/endpoints/read_one_notice_returns_the_ladder_snapshot
    """
    _policy, product, reseller, _violation, _observation, notice = _setup_noticed_violation()
    second, _second_observation, _second_evaluation = create_detected_violation(
        product["id"],
        reseller["id"],
        listed_price_cents=9000,
        observed_at=OBSERVED_AUG_18,
        listing_url="https://mkt.example/l/2",
        evidence_hash=EVIDENCE_HASH_3,
    )

    read = validate_success(api_client.get_notice(notice["id"], COUNSEL_HEADERS))

    assert read["rung"] == "WARNING"
    assert read["assessed_points"] == 3
    assert read["cumulative_points_at_issue"] == 3
    assert read["delivery_channel"] == "EMAIL"
    assert read["suspension_starts_at"] is None
    assert read["suspension_ends_at"] is None
    assert second["provisional_points"] == violation_points(15000, 9000, "MARKETPLACE", 1) == 11


def test_the_notice_collection_filters_by_rung_and_by_status():
    """A warning and the suspension that followed it separate by rung.

    PRD: "Notices are readable individually and as a collection filtered by
    `reseller_id`, `violation_id`, `rung` or `status`."

    Design: Corner/endpoints/list_notices_filters_by_rung_and_status
    """
    _policy, product, reseller, _violation, _observation, warning = _setup_noticed_violation()
    second, _second_observation, _second_evaluation = create_detected_violation(
        product["id"],
        reseller["id"],
        listed_price_cents=9000,
        observed_at=OBSERVED_AUG_18,
        listing_url="https://mkt.example/l/2",
        evidence_hash=EVIDENCE_HASH_3,
    )
    suspension = issue_notice(
        reseller["id"],
        second["id"],
        rung="SUSPENSION",
        suspension_starts_at=SUSPENSION_STARTS,
        suspension_ends_at=SUSPENSION_ENDS,
    )
    assert suspension["cumulative_points_at_issue"] == 14
    assert issued_rung(14, 6, 12, 1) == "SUSPENSION"

    warnings, warning_meta = validate_paginated(
        api_client.list_notices(
            BCM_HEADERS, params={"reseller_id": reseller["id"], "rung": "WARNING"}
        )
    )
    assert warning_meta["total_count"] == 1
    assert [row["id"] for row in warnings] == [warning["id"]]

    suspensions, suspension_meta = validate_paginated(
        api_client.list_notices(BCM_HEADERS, params={"rung": "SUSPENSION", "status": "ISSUED"})
    )
    assert suspension_meta["total_count"] == 1
    assert [row["id"] for row in suspensions] == [suspension["id"]]

    issued, issued_meta = validate_paginated(
        api_client.list_notices(
            BCM_HEADERS, params={"reseller_id": reseller["id"], "status": "ISSUED"}
        )
    )
    assert issued_meta["total_count"] == 2

    by_violation, by_violation_meta = validate_paginated(
        api_client.list_notices(BCM_HEADERS, params={"violation_id": second["id"]})
    )
    assert by_violation_meta["total_count"] == 1
    assert [row["id"] for row in by_violation] == [suspension["id"]]
