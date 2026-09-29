"""Pinned arithmetic on the enforcement side of the contract.

Violation points with their terminal-only rounding, the ladder's
one-rung-per-notice ceiling and its treatment of rescinded notices, and the
reseller points ledger that reconciles the stored counter against the violations
it summarises.  Every figure is re-derived from an independent oracle and
compared against the pinned literal.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import BCM_HEADERS, COUNSEL_HEADERS, api_client
from test_helpers.assertions import (
    base_points_for_fraction,
    deviation_cents,
    deviation_pct,
    issued_rung,
    points_justified_rung,
    repeat_weight,
    round_half_up,
    violation_points,
)
from test_helpers.constants import EVIDENCE_HASH_1, EVIDENCE_HASH_3
from test_helpers.factories import (
    cure_submission_payload,
    notice_payload,
    violation_dispute_decision_payload,
    violation_dispute_payload,
)
from test_helpers.fixtures import (
    approve_exception,
    capture_observation,
    create_authorized_reseller,
    create_product,
    create_published_policy,
    current_reseller_version,
    evaluate_observation,
    issue_notice,
    pin_clock,
    read_compliance_summary,
    read_notice,
    read_reseller,
    read_violation,
    request_exception,
)
from test_helpers.test_users import make_reseller_headers

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_20 = "2026-08-20T00:00:00Z"
OBSERVED_AUG_18 = "2026-08-18T00:00:00Z"
OBSERVED_AUG_19 = "2026-08-19T00:00:00Z"
SUSPENSION_STARTS = "2026-09-01T00:00:00Z"
SUSPENSION_ENDS = "2026-09-10T00:00:00Z"

STANDARD_FLOOR = 15000
MSRP = 20000
SKU_AUDIO = "SKU-AUDIO-1"

WINDOW_STARTS = "2026-08-10T00:00:00Z"
WINDOW_ENDS = "2026-08-25T00:00:00Z"
MARKETING_PLAN = "BRAND_MARKETING_PLAN"


# --------------------------------------------------------------------------- #
# Shared setup
# --------------------------------------------------------------------------- #
def _setup_catalogue():
    """One published policy effective 2026-08-01 and one 15000-floor product."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01)
    product = create_product(
        policy["id"],
        sku=SKU_AUDIO,
        name="Studio Headphones",
        msrp_cents=MSRP,
        standard_map_floor_cents=STANDARD_FLOOR,
    )
    return {"policy": policy, "product": product}


def _setup_authorized_channel():
    """The catalogue plus Acme Retail AUTHORIZED on an ACTIVE marketplace agreement."""
    world = _setup_catalogue()
    reseller, agreement = create_authorized_reseller(
        world["policy"]["id"],
        reseller_overrides={
            "legal_name": "Acme Retail LLC",
            "contact_email": "ops@acme.example",
            "primary_channel": "MARKETPLACE",
        },
        agreement_overrides={"permitted_channels": ["MARKETPLACE", "OWN_WEBSITE"]},
    )
    world["reseller"] = reseller
    world["agreement"] = agreement
    pin_clock(CLOCK_AUG_20)
    return world


def _capture_matched(world, listed_price_cents, listing_url, observed_at=OBSERVED_AUG_18,
                     evidence_hash=EVIDENCE_HASH_1):
    """A marketplace listing already attributed to Acme's storefront."""
    return capture_observation(
        world["product"]["id"],
        channel="MARKETPLACE",
        seller_display_name="Acme Store",
        listing_url=listing_url,
        listed_price_cents=listed_price_cents,
        observed_at=observed_at,
        evidence_hash=evidence_hash,
        matched_reseller_id=world["reseller"]["id"],
    )


def _detect(world, listed_price_cents, listing_url, observed_at=OBSERVED_AUG_18,
            evidence_hash=EVIDENCE_HASH_1):
    """Capture and evaluate a matched breach, returning ``(violation, evaluation)``."""
    observation = _capture_matched(
        world, listed_price_cents, listing_url, observed_at, evidence_hash
    )
    evaluation = evaluate_observation(observation["id"])
    return read_violation(evaluation["violation_id"]), evaluation


def _first_warning(world):
    """Detect the 14000 listing and serve the resulting WARNING notice."""
    violation, evaluation = _detect(world, 14000, "https://mkt.example/l/1")
    notice = issue_notice(world["reseller"]["id"], violation["id"])
    world["first_violation"] = violation
    world["first_evaluation"] = evaluation
    world["first_notice"] = notice
    return world


def _second_suspension(world):
    """Detect the 9000 listing and serve the resulting SUSPENSION notice."""
    violation, _evaluation = _detect(
        world, 9000, "https://mkt.example/l/2", evidence_hash=EVIDENCE_HASH_3
    )
    notice = issue_notice(
        world["reseller"]["id"],
        violation["id"],
        rung="SUSPENSION",
        suspension_starts_at=SUSPENSION_STARTS,
        suspension_ends_at=SUSPENSION_ENDS,
    )
    world["second_violation"] = violation
    world["second_notice"] = notice
    return world


def _third_termination(world):
    """Detect a third 14000 listing and serve the resulting TERMINATION notice."""
    violation, _evaluation = _detect(
        world, 14000, "https://mkt.example/l/3", observed_at=OBSERVED_AUG_19
    )
    notice = issue_notice(
        world["reseller"]["id"],
        violation["id"],
        headers=COUNSEL_HEADERS,
        rung="TERMINATION",
        delivery_channel="CERTIFIED_MAIL",
    )
    world["third_violation"] = violation
    world["third_notice"] = notice
    return world


# --------------------------------------------------------------------------- #
# Violation points
# --------------------------------------------------------------------------- #
def test_the_second_tier_times_the_marketplace_weight_rounds_to_three_points():
    """Base 2 and a 1.5 channel weight give 3.0, so the terminal rounding is exact.

    PRD: "Otherwise take the deviation fraction to four decimal places and read the
    base points off four inclusive tiers: 1 point when the fraction is at most
    0.0500, 2 points when it is at most 0.1500, 4 points when it is at most 0.3000,
    and 6 points when it exceeds 0.3000."

    Design: Corner/calculations/violation_points_second_deviation_tier_with_marketplace_multiplier
    """
    world = _setup_authorized_channel()
    observation = _capture_matched(world, 14000, "https://mkt.example/l/1")
    evaluation = evaluate_observation(observation["id"])

    assert evaluation["deviation_cents"] == deviation_cents(STANDARD_FLOOR, 14000) == 1000
    assert evaluation["deviation_pct"] == deviation_pct(STANDARD_FLOOR, 1000) == 0.0667
    assert base_points_for_fraction(0.0667) == 2
    assert (
        evaluation["provisional_points"]
        == violation_points(STANDARD_FLOOR, 14000, "MARKETPLACE", 0)
        == 3
    )

    violation = read_violation(evaluation["violation_id"])
    assert violation["provisional_points"] == 3
    assert violation["status"] == "DETECTED"


def test_a_physical_retail_half_weight_still_rounds_up_to_a_whole_point():
    """Base 1 times 0.5 is 0.5, which the single terminal rounding lifts to 1.

    PRD: "Multiply the base points by a channel weight — a `MARKETPLACE` listing
    weighs one and a half times, a `RETAILER_SITE` or `OWN_WEBSITE` listing weighs
    exactly once, and a `PHYSICAL_RETAIL` listing weighs only half, because a
    printed circular reaches fewer shoppers than a marketplace page."

    Design: Corner/calculations/violation_points_physical_retail_half_multiplier_rounds_up_to_one
    """
    world = _setup_catalogue()
    pin_clock(CLOCK_AUG_20)
    observation = capture_observation(
        world["product"]["id"],
        channel="PHYSICAL_RETAIL",
        seller_display_name="Corner Electronics",
        listing_url="https://flyer.example/p/1",
        listed_price_cents=14300,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=EVIDENCE_HASH_1,
    )
    evaluation = evaluate_observation(observation["id"])

    assert evaluation["deviation_cents"] == deviation_cents(STANDARD_FLOOR, 14300) == 700
    assert evaluation["deviation_pct"] == deviation_pct(STANDARD_FLOOR, 700) == 0.0467
    assert round_half_up(1 * 0.5) == 1
    assert (
        evaluation["provisional_points"]
        == violation_points(STANDARD_FLOOR, 14300, "PHYSICAL_RETAIL", 0)
        == 1
    )


def test_a_retailer_site_listing_carries_its_base_points_unchanged():
    """A weight of exactly one leaves the fourth-tier base points at 4.

    PRD: "Multiply the base points by a channel weight — a `MARKETPLACE` listing
    weighs one and a half times, a `RETAILER_SITE` or `OWN_WEBSITE` listing weighs
    exactly once, and a `PHYSICAL_RETAIL` listing weighs only half, because a
    printed circular reaches fewer shoppers than a marketplace page."

    Design: Corner/calculations/violation_points_retailer_site_multiplier_is_one
    """
    world = _setup_catalogue()
    pin_clock(CLOCK_AUG_20)
    observation = capture_observation(
        world["product"]["id"],
        channel="RETAILER_SITE",
        seller_display_name="BigBox Online",
        listing_url="https://bigbox.example/p/1",
        listed_price_cents=12000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=EVIDENCE_HASH_1,
    )
    evaluation = evaluate_observation(observation["id"])

    assert evaluation["deviation_cents"] == deviation_cents(STANDARD_FLOOR, 12000) == 3000
    assert evaluation["deviation_pct"] == deviation_pct(STANDARD_FLOOR, 3000) == 0.2000
    assert base_points_for_fraction(0.2000) == 4
    assert (
        evaluation["provisional_points"]
        == violation_points(STANDARD_FLOOR, 12000, "RETAILER_SITE", 0)
        == 4
    )


def test_one_prior_noticed_violation_adds_a_quarter_to_the_repeat_weight():
    """6 times 1.5 times 1.25 is 11.25, which rounds once to 11 points.

    PRD: "Then multiply by a repeat weight that starts at 1.00 and adds a quarter
    for each prior noticed violation of the **same** reseller, counting at most four
    of them, so the repeat weight tops out at 2.00."

    Design: Corner/calculations/violation_points_repeat_multiplier_after_one_prior_notice
    """
    world = _first_warning(_setup_authorized_channel())
    assert world["first_notice"]["assessed_points"] == 3

    observation = _capture_matched(
        world, 9000, "https://mkt.example/l/2", evidence_hash=EVIDENCE_HASH_3
    )
    evaluation = evaluate_observation(observation["id"])

    assert evaluation["deviation_cents"] == deviation_cents(STANDARD_FLOOR, 9000) == 6000
    assert evaluation["deviation_pct"] == deviation_pct(STANDARD_FLOOR, 6000) == 0.4000
    assert repeat_weight(1) == 1.25
    assert (
        evaluation["provisional_points"]
        == violation_points(STANDARD_FLOOR, 9000, "MARKETPLACE", 1)
        == 11
    )
    assert read_violation(evaluation["violation_id"])["provisional_points"] == 11


def test_a_voided_violation_drops_out_of_the_repeat_tally():
    """The same 9000 listing scores 9 rather than 11 behind a sustained dispute.

    PRD: "Violations still in `DETECTED` and violations that were `VOIDED` never
    count as repeats, because the former were never noticed and the latter had their
    points reversed."

    Design: Corner/calculations/violation_points_repeat_count_excludes_voided_violations
    """
    world = _first_warning(_setup_authorized_channel())
    first_id = world["first_violation"]["id"]
    validate_success(
        api_client.dispute_violation(
            first_id,
            violation_dispute_payload(
                dispute_reason="Listing was a third-party clone of our storefront"
            ),
            make_reseller_headers(world["reseller"]["id"]),
        )
    )
    validate_success(
        api_client.decide_violation_dispute(
            first_id,
            violation_dispute_decision_payload(
                "SUSTAIN", decision_reason="Evidence hash mismatch"
            ),
            BCM_HEADERS,
        )
    )

    observation = _capture_matched(
        world, 9000, "https://mkt.example/l/2", evidence_hash=EVIDENCE_HASH_3
    )
    evaluation = evaluate_observation(observation["id"])

    assert repeat_weight(0) == 1.00
    assert (
        evaluation["provisional_points"]
        == violation_points(STANDARD_FLOOR, 9000, "MARKETPLACE", 0)
        == 9
    )

    voided = read_violation(first_id)
    assert voided["status"] == "VOIDED"
    assert voided["assessed_points"] is None
    assert read_violation(evaluation["violation_id"])["provisional_points"] == 9
    assert read_reseller(world["reseller"]["id"])["violation_points_total"] == 0


def test_a_listing_above_the_floor_short_circuits_to_zero_points():
    """A negative raw deviation floors at 0 and stops the formula immediately.

    PRD: "Begin with the floor as of the chosen instant and the deviation in cents;
    if the deviation is zero, the points are zero and no further factors are
    applied."

    Design: Corner/calculations/violation_points_zero_when_the_listing_is_at_the_floor
    """
    world = _setup_authorized_channel()
    observation = _capture_matched(world, 15500, "https://mkt.example/l/high")
    evaluation = evaluate_observation(observation["id"])

    assert evaluation["evaluation_status"] == "EVALUATED_COMPLIANT"
    assert evaluation["deviation_cents"] == deviation_cents(STANDARD_FLOOR, 15500) == 0
    assert (
        evaluation["provisional_points"]
        == violation_points(STANDARD_FLOOR, 15500, "MARKETPLACE", 0)
        == 0
    )
    assert evaluation["violation_id"] is None


def test_a_retroactive_exception_moves_the_final_points_away_from_the_provisional():
    """Detection stores 3 against the 15000 floor; issuance re-reads 14500 and stores 2.

    PRD: "The **provisional** figure is computed during evaluation with the instant
    set to `observed_at`, so the floor is the one that was in force when the listing
    was seen, and the repeat tally is counted as of `observed_at`; it is stored as
    `provisional_points` alongside `provisional_floor_cents`. The **final** figure is
    recomputed at notice issuance with the instant set to the logical clock at
    issuance, so a retroactive exception approved between detection and notice can
    move the floor, move the deviation tier and therefore move the points, and the
    repeat tally is recounted and may have grown; it is stored as `assessed_points`
    alongside `assessed_floor_cents`."

    Design: Corner/calculations/violation_points_provisional_and_final_variants_diverge
    """
    world = _setup_authorized_channel()
    violation, _evaluation = _detect(world, 14000, "https://mkt.example/l/1")

    requested = request_exception(
        world["product"]["id"],
        exception_type="PROMOTIONAL_EVENT",
        starts_at=WINDOW_STARTS,
        ends_at=WINDOW_ENDS,
        channel_scope="ALL",
        requested_override_floor_cents=14500,
        dealer_input_source=MARKETING_PLAN,
    )
    approve_exception(requested["id"], decision_reason="Late campaign registration")

    notice = issue_notice(world["reseller"]["id"], violation["id"])

    stored = read_violation(violation["id"])
    assert stored["provisional_points"] == violation_points(STANDARD_FLOOR, 14000, "MARKETPLACE", 0) == 3
    assert stored["assessed_points"] == violation_points(14500, 14000, "MARKETPLACE", 0) == 2
    assert stored["assessed_floor_cents"] == 14500
    assert stored["status"] == "NOTICED"
    assert notice["assessed_points"] == 2
    assert notice["rung"] == "WARNING"
    assert read_reseller(world["reseller"]["id"])["violation_points_total"] == 2


def test_with_an_unchanged_floor_both_variants_land_on_the_same_figure():
    """Evaluation writes the provisional field and issuance the assessed one.

    PRD: "The **provisional** figure is computed during evaluation with the instant
    set to `observed_at`, so the floor is the one that was in force when the listing
    was seen, and the repeat tally is counted as of `observed_at`; it is stored as
    `provisional_points` alongside `provisional_floor_cents`. The **final** figure is
    recomputed at notice issuance with the instant set to the logical clock at
    issuance, so a retroactive exception approved between detection and notice can
    move the floor, move the deviation tier and therefore move the points, and the
    repeat tally is recounted and may have grown; it is stored as `assessed_points`
    alongside `assessed_floor_cents`."

    Design: Corner/calculations/violation_points_variant_is_chosen_by_the_triggering_endpoint
    """
    world = _first_warning(_setup_authorized_channel())

    stored = read_violation(world["first_violation"]["id"])
    assert stored["provisional_points"] == 3
    assert stored["assessed_points"] == violation_points(STANDARD_FLOOR, 14000, "MARKETPLACE", 0) == 3
    assert stored["assessed_floor_cents"] == STANDARD_FLOOR
    assert world["first_notice"]["assessed_points"] == 3
    assert world["first_notice"]["cumulative_points_at_issue"] == 3


# --------------------------------------------------------------------------- #
# Ladder rung selection
# --------------------------------------------------------------------------- #
def test_a_first_notice_below_the_suspension_threshold_is_a_warning():
    """Three cumulative points sit below the default threshold of six.

    PRD: "Compare that figure against the cited policy's two thresholds, with both
    boundaries inclusive at the lower bound: the points-justified rung is `WARNING`
    when the cumulative figure is strictly below `suspension_points_threshold`,
    `SUSPENSION` when it is at or above `suspension_points_threshold` but strictly
    below `termination_points_threshold`, and `TERMINATION` when it is at or above
    `termination_points_threshold`."

    Design: Corner/calculations/ladder_first_notice_is_a_warning
    """
    world = _first_warning(_setup_authorized_channel())

    assert points_justified_rung(3, 6, 12) == "WARNING"
    assert world["first_notice"]["rung"] == issued_rung(3, 6, 12, 0) == "WARNING"
    assert world["first_notice"]["cumulative_points_at_issue"] == 3
    assert read_reseller(world["reseller"]["id"])["authorization_status"] == "AUTHORIZED"


def test_points_that_justify_termination_are_capped_at_the_next_rung_up():
    """Fourteen cumulative points want TERMINATION; the ceiling allows SUSPENSION.

    PRD: "Independently, find the highest rung the reseller has already been served:
    rank the rungs so that `WARNING` is first, `SUSPENSION` second and `TERMINATION`
    third, and take the highest rank appearing among that reseller's notices whose
    `status` is `ISSUED`, `ACKNOWLEDGED` or `SATISFIED`; notices in `RESCINDED` are
    ignored entirely, and if no qualifying notice exists the highest served rank is
    treated as zero. The ceiling for this notice is one rank above that highest
    served rank, capped at the third rank. The rung actually issued is whichever of
    the points-justified rung and that ceiling ranks lower."

    Design: Corner/calculations/ladder_advances_at_most_one_rung_even_at_termination_points
    """
    world = _second_suspension(_first_warning(_setup_authorized_channel()))
    notice = world["second_notice"]

    assert points_justified_rung(14, 6, 12) == "TERMINATION"
    assert notice["rung"] == issued_rung(14, 6, 12, 1) == "SUSPENSION"
    assert notice["assessed_points"] == violation_points(STANDARD_FLOOR, 9000, "MARKETPLACE", 1) == 11
    assert notice["cumulative_points_at_issue"] == 14

    summary = read_compliance_summary(world["reseller"]["id"])
    assert summary["highest_issued_rung"] == "SUSPENSION"


def test_the_suspension_rung_drives_both_reseller_axes_and_copies_the_window():
    """Serving the second rung suspends the reseller and holds its supply.

    PRD: "A `SUSPENSION` notice additionally drives the reseller's authorization axis
    to `SUSPENDED`, its supply axis to `HOLD` and its `hold_reason` to `SUSPENSION`,
    and copies the notice's `suspension_ends_at` onto the reseller's own
    `suspension_ends_at`; this is legal from either `AUTHORIZED` or `SUSPENDED`, but
    never from `TERMINATED`."

    Design: Corner/calculations/ladder_advances_at_most_one_rung_even_at_termination_points
    """
    world = _second_suspension(_first_warning(_setup_authorized_channel()))

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "SUSPENDED"
    assert reseller["supply_status"] == "HOLD"
    assert reseller["hold_reason"] == "SUSPENSION"


def test_the_third_notice_is_where_the_two_bounds_finally_coincide():
    """Nineteen points and a served SUSPENSION both point at TERMINATION.

    PRD: "The ceiling for this notice is one rank above that highest served rank,
    capped at the third rank. The rung actually issued is whichever of the
    points-justified rung and that ceiling ranks lower."

    Design: Corner/calculations/ladder_reaches_termination_on_the_third_notice
    """
    world = _third_termination(
        _second_suspension(_first_warning(_setup_authorized_channel()))
    )
    notice = world["third_notice"]

    assert points_justified_rung(19, 6, 12) == "TERMINATION"
    assert notice["rung"] == issued_rung(19, 6, 12, 2) == "TERMINATION"
    assert notice["assessed_points"] == violation_points(STANDARD_FLOOR, 14000, "MARKETPLACE", 2) == 5
    assert notice["cumulative_points_at_issue"] == 19


def test_the_termination_rung_drives_the_reseller_to_its_terminal_pair():
    """The third rung is the only one that reaches TERMINATED.

    PRD: "A `TERMINATION` notice — legal from `AUTHORIZED` or `SUSPENDED` — drives
    the reseller to `TERMINATED` on the authorization axis, `CUT_OFF` on the supply
    axis and `TERMINATION` as the `hold_reason`, stamps `terminated_at` with the
    current clock and clears `suspension_ends_at` to null."

    Design: Corner/calculations/ladder_reaches_termination_on_the_third_notice
    """
    world = _third_termination(
        _second_suspension(_first_warning(_setup_authorized_channel()))
    )

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "TERMINATED"
    assert reseller["supply_status"] == "CUT_OFF"
    assert reseller["suspension_ends_at"] is None


def test_a_rescinded_notice_no_longer_counts_as_a_rung_already_served():
    """The highest-served rank falls back to zero, re-capping the ladder at WARNING.

    PRD: "Independently, find the highest rung the reseller has already been served:
    rank the rungs so that `WARNING` is first, `SUSPENSION` second and `TERMINATION`
    third, and take the highest rank appearing among that reseller's notices whose
    `status` is `ISSUED`, `ACKNOWLEDGED` or `SATISFIED`; notices in `RESCINDED` are
    ignored entirely, and if no qualifying notice exists the highest served rank is
    treated as zero."

    Design: Corner/calculations/ladder_ignores_a_rescinded_notice_when_reading_highest_issued
    """
    world = _first_warning(_setup_authorized_channel())
    validate_success(
        api_client.rescind_notice(
            world["first_notice"]["id"],
            {"rescinded_reason": "Wrong storefront attributed"},
            COUNSEL_HEADERS,
        )
    )
    violation, _evaluation = _detect(
        world, 9000, "https://mkt.example/l/2", evidence_hash=EVIDENCE_HASH_3
    )

    fresh = get_success_data(
        api_client.issue_notice(
            notice_payload(
                world["reseller"]["id"],
                violation["id"],
                current_reseller_version(world["reseller"]["id"]),
                rung="WARNING",
            ),
            BCM_HEADERS,
        )
    )

    assert points_justified_rung(9, 6, 12) == "SUSPENSION"
    assert fresh["rung"] == issued_rung(9, 6, 12, 0) == "WARNING"
    assert fresh["assessed_points"] == violation_points(STANDARD_FLOOR, 9000, "MARKETPLACE", 0) == 9
    assert fresh["cumulative_points_at_issue"] == 9
    assert read_notice(world["first_notice"]["id"])["status"] == "RESCINDED"


def test_rescission_clears_the_ledger_before_the_replacement_notice_refills_it():
    """The nine points on the reissued notice are the only ones left standing.

    PRD: "Otherwise the notice moves to `RESCINDED` with `closed_reason` recorded
    from the supplied reason and its `version` advanced, and the reversal reaches
    back into the violation: the cited violation is returned to status `DETECTED`
    with `assessed_points`, `assessed_floor_cents` and `cure_deadline_at` all cleared
    to null, and the notice's `assessed_points` are subtracted from the reseller's
    `violation_points_total`."

    Design: Corner/calculations/ladder_ignores_a_rescinded_notice_when_reading_highest_issued
    """
    world = _first_warning(_setup_authorized_channel())
    validate_success(
        api_client.rescind_notice(
            world["first_notice"]["id"],
            {"rescinded_reason": "Wrong storefront attributed"},
            COUNSEL_HEADERS,
        )
    )

    cleared = read_violation(world["first_violation"]["id"])
    assert cleared["status"] == "DETECTED"
    assert cleared["assessed_points"] is None
    assert read_reseller(world["reseller"]["id"])["violation_points_total"] == 0

    violation, _evaluation = _detect(
        world, 9000, "https://mkt.example/l/2", evidence_hash=EVIDENCE_HASH_3
    )
    get_success_data(
        api_client.issue_notice(
            notice_payload(
                world["reseller"]["id"],
                violation["id"],
                current_reseller_version(world["reseller"]["id"]),
                rung="WARNING",
            ),
            BCM_HEADERS,
        )
    )

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "AUTHORIZED"
    assert reseller["violation_points_total"] == 9


# --------------------------------------------------------------------------- #
# The reseller points ledger
# --------------------------------------------------------------------------- #
def test_a_cured_violation_stays_in_the_ledger_while_a_detected_one_never_enters():
    """Curing does not refund points and detection has not yet charged any.

    PRD: "A reseller's `violation_points_total` equals the sum of `assessed_points`
    over that reseller's violations whose `assessed_points` is not null and whose
    `status` is one of `NOTICED`, `DISPUTED`, `CURED`, `ESCALATED` or `CLOSED_MOOT`."

    Design: Corner/calculations/points_ledger_counts_only_assessed_violations
    """
    world = _first_warning(_setup_authorized_channel())
    validate_success(
        api_client.submit_cure(
            world["first_violation"]["id"],
            cure_submission_payload(
                cure_evidence_url="https://acme.example/proof/6",
                corrected_price_cents=15000,
            ),
            make_reseller_headers(world["reseller"]["id"]),
        )
    )
    third_violation, _evaluation = _detect(
        world, 14000, "https://mkt.example/l/3", observed_at=OBSERVED_AUG_19
    )

    summary = read_compliance_summary(world["reseller"]["id"])
    assert summary["violation_points_total"] == 3
    assert summary["contributing_violation_count"] == 1
    assert summary["summed_assessed_points"] == 3

    assert read_violation(world["first_violation"]["id"])["status"] == "CURED"
    assert read_violation(third_violation["id"])["status"] == "DETECTED"
    assert read_reseller(world["reseller"]["id"])["violation_points_total"] == 3


def test_the_summary_reconciles_the_stored_total_against_three_mooted_violations():
    """Termination closes the history moot but keeps every point in the sum.

    PRD: "It reports `reseller_id`, the stored `violation_points_total`, the
    `contributing_violation_count` of violations that qualify under the ledger
    definition of §2.11, the `summed_assessed_points` obtained by adding up those
    violations' `assessed_points` — which must equal the stored total, since that is
    the whole point of the read — the `highest_issued_rung` served so far (reported
    as the empty-history case when no non-rescinded notice exists), the `next_rung`
    the ladder would install on the next notice, and the two gaps
    `points_to_suspension` and `points_to_termination`, each being the reseller's own
    governing thresholds minus the current total, floored at zero when the threshold
    has already been passed."

    Design: Corner/calculations/points_ledger_matches_the_denormalized_total_after_three_notices
    """
    world = _third_termination(
        _second_suspension(_first_warning(_setup_authorized_channel()))
    )

    summary = read_compliance_summary(world["reseller"]["id"], headers=COUNSEL_HEADERS)
    assert summary["violation_points_total"] == 3 + 11 + 5 == 19
    assert summary["summed_assessed_points"] == 19
    assert summary["contributing_violation_count"] == 3
    assert summary["highest_issued_rung"] == "TERMINATION"
    assert read_reseller(world["reseller"]["id"])["violation_points_total"] == 19


