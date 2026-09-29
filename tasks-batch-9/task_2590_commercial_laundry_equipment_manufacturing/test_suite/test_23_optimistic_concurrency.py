"""Version tokens on quote lines and claim adjudications, and the training threshold.

Two writes in this system are guarded by a version the client must have observed:
adding a quote line quotes the parent quote's version back, and adjudicating a
warranty claim quotes the claimed part's version back. A token that has gone stale
is refused with nothing written, and the refreshed token succeeds. The channel's
authorization threshold is the same kind of care applied to a conjunction: two
distinct trained technicians and both required modules, counted separately.
"""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import api_errors as E
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    CHANNEL_MANAGER,
    PLANT_MANAGER,
    TRAINING_ADMIN,
    WARRANTY_ANALYST,
)


class TestQuoteLineVersionToken:
    """The quote's version is what tells a client its money figures moved."""

    def test_01_replaying_a_spent_quote_version_is_refused(self, api):
        """Two identical lines are a legal two-line quote, so the only thing that
        can refuse the replayed request is its spent version token, and the
        refreshed token then adds the second line for real.

        PRD: "If `expected_quote_version` does not equal the quote's current `version`, the request is rejected with `ERR_STALE_QUOTE_VERSION` and HTTP 412, and nothing is written."
        Design: Corner/cross_cutting_complexity_layers/stale_expected_quote_version_on_line_create_returns_412
        """
        model = fx.make_model(api)
        channel = fx.make_pending_distributor(api)
        quote = fx.make_quote(api, channel, financing_program="NONE")
        drafted_version = quote["version"]

        first_line = validate_success(
            api.create_quote_line(
                quote["id"],
                f.quote_line_payload(model["id"], drafted_version, quantity=1),
                channel["headers"],
            ),
            expected_status=201,
        )
        a.assert_cents(first_line["line_total_cents"], 1250000)

        # Exactly the same body a second time: the token is the only thing wrong.
        replayed = api.create_quote_line(
            quote["id"],
            f.quote_line_payload(model["id"], drafted_version, quantity=1),
            channel["headers"],
        )
        validate_error(replayed, E.ERR_STALE_QUOTE_VERSION, expected_status=412)

        after_rejection = validate_success(
            api.get_quote(quote["id"], channel["headers"]), expected_status=200
        )
        assert after_rejection["line_count"] == 1
        a.assert_cents(after_rejection["total_cents"], 1250000)
        assert after_rejection["version"] == drafted_version + 1

        second_line = validate_success(
            api.create_quote_line(
                quote["id"],
                f.quote_line_payload(
                    model["id"], after_rejection["version"], quantity=1
                ),
                channel["headers"],
            ),
            expected_status=201,
        )
        assert second_line["id"] != first_line["id"]

        settled = validate_success(
            api.get_quote(quote["id"], channel["headers"]), expected_status=200
        )
        assert settled["line_count"] == 2
        a.assert_cents(settled["line_subtotal_cents"], 2500000)
        a.assert_cents(settled["total_cents"], 2500000)
        a.assert_money_identity(settled)
        assert settled["version"] == drafted_version + 2
        a.assert_cents(settled["origination_fee_cents"], 0)
        assert settled["provisional_apr_bp"] is None


class TestClaimAdjudicationPartVersionToken:
    """The token guards the part, which a stock receipt moves under the analyst."""

    def test_01_a_receipt_between_read_and_adjudicate_invalidates_the_token(
        self, api, submitted_claim
    ):
        """A stock receipt on the claimed part moves the part but not the claim, so
        the analyst's remembered part version is refused and must be re-read before
        the settlement commits.

        PRD: "If `expected_part_version` does not equal the part's current `version`, the request is rejected with `ERR_STALE_PART_VERSION` and HTTP 412, and neither the claim nor the part is modified."
        Design: Corner/cross_cutting_complexity_layers/stale_expected_part_version_on_claim_adjudicate_returns_412
        """
        claim_id = submitted_claim["claim"]["id"]
        part_id = submitted_claim["part"]["id"]
        observed_version = fx.read_part_version(api, part_id)

        # The warehouse receives one more unit while the analyst is deciding.
        validate_success(
            api.create_stock_adjustment(
                part_id, f.stock_adjustment_payload(1, "RECEIPT"), PLANT_MANAGER
            ),
            expected_status=200,
        )

        stale = api.adjudicate_warranty_claim(
            claim_id, f.adjudicate_payload(observed_version, "APPROVE"), WARRANTY_ANALYST
        )
        validate_error(stale, E.ERR_STALE_PART_VERSION, expected_status=412)

        untouched_claim = validate_success(
            api.get_warranty_claim(claim_id, WARRANTY_ANALYST), expected_status=200
        )
        a.assert_claim_state(untouched_claim, "SUBMITTED")
        a.assert_cents(untouched_claim["covered_amount_cents"], 0)
        assert untouched_claim["coverage_variant"] == "NONE"

        untouched_part = validate_success(
            api.get_service_part(part_id, WARRANTY_ANALYST), expected_status=200
        )
        assert untouched_part["on_hand_qty"] == 4, "No unit may be consumed by a 412"
        assert untouched_part["version"] == observed_version + 1

        settled = validate_success(
            api.adjudicate_warranty_claim(
                claim_id,
                f.adjudicate_payload(untouched_part["version"], "APPROVE"),
                WARRANTY_ANALYST,
            ),
            expected_status=200,
        )
        a.assert_claim_state(settled, "APPROVED")
        assert settled["coverage_variant"] == "FULL_REPLACEMENT"
        a.assert_cents(settled["covered_amount_cents"], 42000)

        part_after = validate_success(
            api.get_service_part(part_id, WARRANTY_ANALYST), expected_status=200
        )
        assert part_after["on_hand_qty"] == 3
        assert part_after["stock_state"] == "IN_STOCK"
        assert part_after["version"] == observed_version + 2
        a.assert_unit_conservation(part_after, 4)

        distributor = validate_success(
            api.get_distributor(submitted_claim["distributor"]["id"], CHANNEL_MANAGER),
            expected_status=200,
        )
        a.assert_cents(distributor["warranty_credit_cents"], 42000)
        assert distributor["open_claim_count"] == 0

        # A settled claim is out of scope for the version check altogether.
        replayed = api.adjudicate_warranty_claim(
            claim_id,
            f.adjudicate_payload(part_after["version"], "APPROVE"),
            WARRANTY_ANALYST,
        )
        validate_error(replayed, E.ERR_CLAIM_STATE_INVALID, expected_status=409)


class TestChannelAuthorizationThreshold:
    """Two independent conditions, and the module half is satisfied first."""

    def test_01_one_technician_holding_both_modules_does_not_authorize(self, api):
        """A single technician trained on installation and on payment systems leaves
        the distributor waiting, and the second distinct technician flips it even
        though that third record only repeats a module already covered.

        PRD: "The **authorization threshold** is met when, after the new key has been appended, two conditions hold together: at least two distinct technicians appear in `completed_training_keys`, and both the `INSTALLATION` module and the `PAYMENT_SYSTEMS` module appear somewhere among those keys."
        Design: Corner/cross_cutting_complexity_layers/distributor_authorization_threshold_needs_two_distinct_technicians
        """
        channel = fx.make_pending_distributor(api)
        distributor_id = channel["distributor"]["id"]
        admitted_version = channel["distributor"]["version"]
        first, second = channel["technicians"]

        after_first = validate_success(
            api.create_training_completion(
                distributor_id,
                f.training_completion_payload(
                    first["id"], "INSTALLATION", "2026-07-20"
                ),
                TRAINING_ADMIN,
            ),
            expected_status=200,
        )
        assert after_first["distributor_state"] == "PENDING_TRAINING"
        assert after_first["trained_technician_count"] == 1
        assert after_first["installation_training_state"] == "IN_PROGRESS"

        after_second = validate_success(
            api.create_training_completion(
                distributor_id,
                f.training_completion_payload(
                    first["id"], "PAYMENT_SYSTEMS", "2026-07-21"
                ),
                TRAINING_ADMIN,
            ),
            expected_status=200,
        )
        # Both modules are now covered, but by one pair of hands.
        assert after_second["distributor_state"] == "PENDING_TRAINING"
        assert after_second["trained_technician_count"] == 1
        assert len(after_second["completed_training_keys"]) == 2

        after_third = validate_success(
            api.create_training_completion(
                distributor_id,
                f.training_completion_payload(
                    second["id"], "INSTALLATION", "2026-07-22"
                ),
                TRAINING_ADMIN,
            ),
            expected_status=200,
        )
        assert after_third["distributor_state"] == "AUTHORIZED"
        assert after_third["trained_technician_count"] == 2
        assert after_third["installation_training_state"] == "COMPLETE"
        assert len(after_third["completed_training_keys"]) == 3
        assert after_third["probation_reason"] == "NONE"
        assert after_third["version"] == admitted_version + 3

        # Each key joins the technician identifier to the module with a bar.
        assert set(after_third["completed_training_keys"]) == {
            f"{first['id']}|INSTALLATION",
            f"{first['id']}|PAYMENT_SYSTEMS",
            f"{second['id']}|INSTALLATION",
        }
