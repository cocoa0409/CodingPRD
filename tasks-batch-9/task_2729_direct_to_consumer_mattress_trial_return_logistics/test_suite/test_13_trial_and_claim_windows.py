"""Time-boxed and evidence-floor refusals on the trial clock and on quality claims.

Each test sits the logical clock on the exact day the rule flips and checks both
the refusal and the fact that nothing was written — or, for the one accepted
case, that the whole cascade fired.
"""

from test_helpers import (
    AGENT,
    ApiErrorId,
    api_client,
    assert_instant,
    file_quality_claim,
    get_success_data,
    quality_claim_payload,
    read_order,
    read_quality_claim,
    request_evidence,
    return_case_payload,
    set_clock,
    setup_delivered_order,
    submit_evidence_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def _delivered(tag: str, name: str, **model_overrides) -> dict:
    """One QUEEN order delivered on 2026-08-01, with its own household."""
    overrides = {"sku": f"MDL-Q-{tag.upper()}", "name": "Comfort Q",
                 "list_price_cents": 120000}
    overrides.update(model_overrides)
    return setup_delivered_order(
        model_overrides=overrides,
        customer_overrides={
            "email": f"{tag}@example.com",
            "full_name": name,
            "household_hash": f"HH-{tag.upper()}",
        },
    )


class TestTrialWindowIsExclusiveAtTheFarEnd:
    """The hundredth night is the last one; the instant itself is too late."""

    def test_opening_a_return_at_exactly_trial_ends_at_is_refused(self):
        """PRD §3.6: "At the far end, the trial window is a hard stop for both returns and exchanges: the logical clock must be strictly before `trial_ends_at`, and a request at or after that instant is refused with `ERR_TRIAL_WINDOW_EXPIRED`."

        A 2026-08-01 delivery with the default 100 trial nights closes at
        2026-11-09, so a return opened at exactly that instant is refused; the
        order is lazily re-derived to TRIAL_EXPIRED without a version bump, which
        is what lets the request reach the window rule instead of the state rule.

        Design: Corner/validations/opening_a_return_at_trial_ends_at_returns_trial_window_expired
        """
        scenario = _delivered("v1", "Vic One")
        order = scenario["order"]
        assert_instant(order["trial_ends_at"], "2026-11-09T00:00:00Z", "trial_ends_at")
        delivered_version = order["version"]

        set_clock("2026-11-09T00:00:00Z")
        response = api_client.create_return_case(
            return_case_payload(order["id"], "COMFORT"), scenario["customer_headers"]
        )
        validate_error(response, ApiErrorId.ERR_TRIAL_WINDOW_EXPIRED)

        _rows, meta = validate_paginated(
            api_client.list_return_cases(AGENT, params={"order_id": order["id"]})
        )
        assert meta["total_count"] == 0, "the refused request must not open a case"

        reloaded = read_order(order["id"])
        assert reloaded["trial_status"] == "TRIAL_EXPIRED", (
            f"the clock alone expires the trial, got {reloaded['trial_status']}"
        )
        assert reloaded["version"] == delivered_version, (
            "a lazy clock re-derivation never bumps version, got "
            f"{reloaded['version']} against {delivered_version}"
        )


class TestCompressionRecoveryWaitIsALowerBound:
    """Three nights must pass before a compression complaint is heard."""

    def test_a_complaint_on_the_second_night_is_refused(self):
        """PRD §3.4: "A compression-recovery complaint may not be filed until the mattress has been given its decompression window: the whole number of complete days between `delivered_at` and the logical clock must be at least three nights, and an earlier filing is refused with `ERR_RECOVERY_WINDOW_NOT_ELAPSED`."

        At 2026-08-03 only two complete nights have passed since the 2026-08-01
        delivery, so the claim is refused, nothing is written, and the order stays
        DELIVERED rather than moving to DAMAGED_REPORTED.

        Design: Corner/validations/compression_complaint_before_the_recovery_wait_returns_recovery_window_not_elapsed
        """
        scenario = _delivered("v2", "Val Two")
        order = scenario["order"]

        set_clock("2026-08-03T00:00:00Z")
        response = api_client.create_quality_claim(
            quality_claim_payload(order["id"], "COMPRESSION_RECOVERY", 2),
            scenario["customer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_RECOVERY_WINDOW_NOT_ELAPSED)

        _rows, meta = validate_paginated(
            api_client.list_quality_claims(AGENT, params={"order_id": order["id"]})
        )
        assert meta["total_count"] == 0
        assert read_order(order["id"])["fulfillment_status"] == "DELIVERED"

    def test_the_same_complaint_on_the_third_night_is_accepted(self):
        """PRD §3.4: "Filing a delivery-damage or compression-recovery complaint has a visible effect on the order: the fulfillment axis advances `DELIVERED → DAMAGED_REPORTED` and the order's `version` increments by one."

        One day later the wait is satisfied inclusively — three complete nights —
        so the claim opens at SUBMITTED with an empty evidence-round counter, the
        fulfillment axis advances and the trial axis is left in BREAK_IN, still
        counting underneath the complaint.

        Design: Corner/validations/compression_complaint_on_the_third_night_is_accepted
        """
        scenario = _delivered("v3", "Van Three")
        order = scenario["order"]
        delivered_version = order["version"]

        set_clock("2026-08-04T00:00:00Z")
        claim = validate_success(
            api_client.create_quality_claim(
                quality_claim_payload(order["id"], "COMPRESSION_RECOVERY", 2),
                scenario["customer_headers"],
            ),
            201,
        )

        assert claim["status"] == "SUBMITTED"
        assert claim["evidence_round_count"] == 0
        assert_instant(claim["reported_at"], "2026-08-04T00:00:00Z", "reported_at")

        reloaded = read_order(order["id"])
        assert reloaded["fulfillment_status"] == "DAMAGED_REPORTED"
        assert reloaded["trial_status"] == "BREAK_IN", (
            "the trial axis is untouched by a complaint, got "
            f"{reloaded['trial_status']}"
        )
        assert reloaded["version"] == delivered_version + 1


class TestDamageReportWindowIsAnUpperBound:
    """The shipping-damage window runs the opposite way to the recovery wait."""

    def test_a_report_on_the_eighth_night_is_refused(self):
        """PRD §3.4: "A shipping-damage complaint runs the other way — it must be filed while the delivery is still fresh, so the whole number of complete days since delivery may not exceed seven nights, and a later filing is refused with `ERR_DAMAGE_REPORT_WINDOW_CLOSED`."

        2026-08-09 is eight complete nights after the 2026-08-01 delivery, one
        past the inclusive seven-night limit, so even four photographs cannot save
        the claim and the order stays DELIVERED.

        Design: Corner/validations/shipping_damage_reported_on_the_eighth_night_returns_damage_report_window_closed
        """
        scenario = _delivered("v4", "Vera Four")
        order = scenario["order"]

        set_clock("2026-08-09T00:00:00Z")
        response = api_client.create_quality_claim(
            quality_claim_payload(order["id"], "SHIPPING_DAMAGE", 4),
            scenario["customer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_DAMAGE_REPORT_WINDOW_CLOSED)

        assert read_order(order["id"])["fulfillment_status"] == "DELIVERED"
        _rows, meta = validate_paginated(
            api_client.list_quality_claims(AGENT, params={"order_id": order["id"]})
        )
        assert meta["total_count"] == 0


class TestPhotographFloorDependsOnTheClaim:
    """Two photographs for a delivery complaint, one for a laser scan."""

    def test_a_single_photograph_on_a_shipping_damage_claim_is_refused(self):
        """PRD §3.4: "A delivery-damage or compression-recovery complaint requires at least two photographs."

        The report date of 2026-08-03 sits comfortably inside both delivery
        windows, so the only thing wrong is the evidence count, and the order is
        left at DELIVERED with its version untouched.

        Design: Corner/validations/shipping_damage_with_a_single_photograph_returns_insufficient_evidence
        """
        scenario = _delivered("v9", "Vince Nine")
        order = scenario["order"]
        delivered_version = order["version"]

        set_clock("2026-08-03T00:00:00Z")
        response = api_client.create_quality_claim(
            quality_claim_payload(order["id"], "SHIPPING_DAMAGE", 1),
            scenario["customer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_EVIDENCE)

        reloaded = read_order(order["id"])
        assert reloaded["fulfillment_status"] == "DELIVERED"
        assert reloaded["version"] == delivered_version
        _rows, meta = validate_paginated(
            api_client.list_quality_claims(AGENT, params={"order_id": order["id"]})
        )
        assert meta["total_count"] == 0


class TestIndentationThresholdIsInclusive:
    """Twenty-five millimetres qualifies; twenty-four does not."""

    def test_a_measurement_one_millimetre_short_is_refused(self):
        """PRD §3.4: "The trial order must have `trial_status` `KEPT` — a warranty is about a mattress the customer owns, not one still on trial — and `measured_indentation_mm` must reach the model's `indentation_warranty_threshold_mm`, with the boundary inclusive so a measurement exactly at the threshold qualifies."

        The mattress was kept, the single laser photograph already satisfies the
        evidence floor, and the model's threshold is the default 25 millimetres —
        so a 24-millimetre scan fails on depth alone and no claim is written.

        Design: Corner/validations/indentation_one_millimetre_below_the_threshold_returns_indentation_below_threshold
        """
        scenario = _delivered("v12", "Vida Twelve", indentation_warranty_threshold_mm=25)
        order = scenario["order"]

        set_clock("2026-09-10T00:00:00Z")
        kept = get_success_data(api_client.keep_trial_order(order["id"], {}, AGENT))
        assert kept["trial_status"] == "KEPT"

        set_clock("2027-09-10T00:00:00Z")
        response = api_client.create_quality_claim(
            quality_claim_payload(
                order["id"],
                "WARRANTY_INDENTATION",
                1,
                measurement_method="LASER_SCAN",
                measured_indentation_mm=24,
            ),
            scenario["customer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_INDENTATION_BELOW_THRESHOLD)

        _rows, meta = validate_paginated(
            api_client.list_quality_claims(AGENT, params={"order_id": order["id"]})
        )
        assert meta["total_count"] == 0

        reloaded = read_order(order["id"])
        assert reloaded["trial_status"] == "KEPT"
        assert reloaded["fulfillment_status"] == "CLOSED"


class TestEvidenceLoopIsBoundedAtTwoRounds:
    """The counter is checked before it is incremented, so the third round fails."""

    def test_a_third_evidence_submission_is_refused_and_replaces_nothing(self):
        """PRD §3.4: "The loop is bounded: at most two further evidence rounds are permitted, so a submission attempted once `evidence_round_count` has already reached two is refused with `ERR_ROUND_LIMIT_REACHED`."

        Two request-and-submit cycles take the counter to two and leave four
        photographs on file; a third request is still permitted, but the
        submission answering it is refused, the counter stays at two and the
        rejected count of five never replaces the stored four.

        Design: Corner/validations/third_evidence_round_on_a_quality_claim_returns_round_limit_reached
        """
        scenario = _delivered("v13", "Vera Thirteen")
        order = scenario["order"]
        customer_headers = scenario["customer_headers"]

        set_clock("2026-08-03T00:00:00Z")
        claim = file_quality_claim(
            order["id"], "SHIPPING_DAMAGE", 2, headers=customer_headers
        )

        for expected_round in (1, 2):
            request_evidence(claim["id"])
            submitted = get_success_data(
                api_client.submit_claim_evidence(
                    claim["id"], submit_evidence_payload(4), customer_headers
                )
            )
            assert submitted["evidence_round_count"] == expected_round, (
                f"round {expected_round} should have been counted, got "
                f"{submitted['evidence_round_count']}"
            )
            assert submitted["status"] == "SUBMITTED"

        request_evidence(claim["id"])
        response = api_client.submit_claim_evidence(
            claim["id"], submit_evidence_payload(5), customer_headers
        )
        validate_error(response, ApiErrorId.ERR_ROUND_LIMIT_REACHED)

        loaded = read_quality_claim(claim["id"])
        assert loaded["evidence_round_count"] == 2, (
            f"the refused round must not increment the counter, got "
            f"{loaded['evidence_round_count']}"
        )
        assert loaded["photo_evidence_count"] == 4, (
            "a refused submission replaces nothing, got "
            f"{loaded['photo_evidence_count']}"
        )
        assert loaded["status"] == "EVIDENCE_REQUESTED"
