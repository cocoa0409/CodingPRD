"""Money formulas whose answer depends on the order the steps are taken in.

Both families pick inputs where the pinned order and the natural-looking order
give *different* integers, so the assertion discriminates the specification from
a plausible re-reading of it.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import assert_cents, assert_field_values
from test_helpers.factories import credential_payload, presentation_session_payload
from test_helpers.fixtures import (
    create_attested_device,
    create_holder,
    create_listed_reader_app,
    create_presentation_ready_world,
    create_profile,
    create_verified_session,
    decide_trust,
    device_version,
    disclose,
    grant_consent,
    provision_credential,
    activate_credential,
)
from test_helpers.test_users import ADJUDICATOR, ADMIN, make_verifier_operator_headers


class TestInvoiceRoundsEachLineBeforeSummation:
    """Two lines of exactly 34.5 cents must sum to 70, never to 69."""

    @staticmethod
    def _verifier_with_two_billed_reader_apps(api):
        world = create_presentation_ready_world(
            api,
            verifier_overrides={
                "organization_name": "Prairie Cellars",
                "category": "AGE_RESTRICTED_RETAIL",
                "purpose_scope": ["family_name", "age_over_21"],
                "retention_ceiling_days": 30,
            },
            reader_app_overrides={
                "app_identifier": "till-a",
                "certificate_serial": "SER-A1",
                "requested_elements": ["family_name", "age_over_21"],
                "base_rate_cents": 30,
            },
        )
        verifier_id = world["verifier"]["id"]
        second_app = create_listed_reader_app(
            api,
            verifier_id,
            app_identifier="till-b",
            certificate_serial="SER-B1",
            requested_elements=["family_name", "age_over_21"],
            base_rate_cents=30,
        )

        for reader_app_id, purpose in (
            (world["reader_app"]["id"], "age check lane one"),
            (second_app["id"], "age check lane two"),
        ):
            session = validate_success(
                api.create_presentation_session(
                    presentation_session_payload(
                        world["credential"]["id"],
                        reader_app_id,
                        purpose=purpose,
                        retention_days=5,
                    ),
                    make_verifier_operator_headers(verifier_id),
                ),
                201,
            )
            grant_consent(api, session["id"], world["holder"]["id"])
            disclose(api, session["id"], verifier_id)

        return world

    def test_two_half_cent_lines_each_round_up_and_then_sum(self, api):
        """On probation both lines are worth 34.5 cents raw; the pinned order
        rounds each to 35 and totals 70.

        PRD 3.9: "The invoice total is the **sum of the already-rounded line
        amounts**. Rounding is applied once per line, before summation - it is
        emphatically not applied once to the sum of the unrounded line values.
        Two lines whose unrounded values both end exactly halfway between two
        cents yield two upward roundings under the pinned order and only one
        under the sum-then-round reading, so the two orders give different totals
        and only the pinned one is correct."

        Design: Difficulty/combinatorial_formula/invoice_round_each_line_then_sum_two_half_cent_lines
        """
        world = self._verifier_with_two_billed_reader_apps(api)
        verifier_id = world["verifier"]["id"]
        decide_trust(api, verifier_id, "PROBATION")

        invoice = validate_success(
            api.get_invoice(verifier_id, make_verifier_operator_headers(verifier_id))
        )
        assert_field_values(invoice, {"line_count": 2, "surcharge_pct": 0.15})
        assert_cents(invoice, "invoice_amount_cents", 70)
        assert invoice["invoice_amount_cents"] != 69

    def test_the_surcharge_is_the_only_thing_probation_changes(self, api):
        """The same two lines total 60 while the verifier is approved, and the
        outstanding balance is untouched by the surcharge either way.

        PRD 3.9: "A surcharge percentage of 15 percent applies when the
        verifier's `trust_status` is `PROBATION`, and nothing otherwise."
        PRD 3.9: "The computation returns `invoice_amount_cents`, the
        `line_count` of applications that contributed a line, the
        `surcharge_pct` in force, and the verifier's current
        `billable_query_balance_cents`."

        Design: Difficulty/combinatorial_formula/invoice_round_each_line_then_sum_two_half_cent_lines
        """
        world = self._verifier_with_two_billed_reader_apps(api)
        verifier_id = world["verifier"]["id"]
        operator = make_verifier_operator_headers(verifier_id)

        approved_invoice = validate_success(api.get_invoice(verifier_id, operator))
        assert approved_invoice["surcharge_pct"] == 0
        assert_cents(approved_invoice, "invoice_amount_cents", 60)
        assert_cents(approved_invoice, "billable_query_balance_cents", 60)

        decide_trust(api, verifier_id, "PROBATION")
        probation_invoice = validate_success(api.get_invoice(verifier_id, operator))
        assert_cents(probation_invoice, "invoice_amount_cents", 70)
        assert_cents(probation_invoice, "billable_query_balance_cents", 60)


class TestReissuanceWaiverTierComesFromThePreWaiverTotal:
    """Selecting the tier off the settlement instead is a different number."""

    @staticmethod
    def _lost_handset_and_a_replacement_ready(api):
        create_profile(api)
        holder = create_holder(api)
        first_device = create_attested_device(api, holder["id"])
        first_session = create_verified_session(api, holder["id"])
        first_credential = provision_credential(
            api, holder["id"], first_device["id"], first_session["id"]
        )
        activate_credential(api, first_credential["id"], holder["id"])
        validate_success(api.report_device_lost(first_device["id"], ADMIN))

        second_device = create_attested_device(
            api,
            holder["id"],
            secure_element_grade="HARDWARE_TEE",
            platform="IOS",
            model_name="iPhone 17",
        )
        second_session = create_verified_session(
            api,
            holder["id"],
            [
                {
                    "evidence_type": "DOCUMENT_SCAN",
                    "quality": "STRONG",
                    "captured_at": "2026-07-28T09:00:00Z",
                    "source_reference": "doc-2",
                },
                {
                    "evidence_type": "BIOMETRIC_MATCH",
                    "quality": "STRONG",
                    "captured_at": "2026-07-28T09:05:00Z",
                    "source_reference": "bio-2",
                },
            ],
        )
        return holder, first_credential, second_device, second_session

    @staticmethod
    def _reissue(api, holder, predecessor, device, session):
        return api.create_credential(
            credential_payload(
                holder["id"],
                device["id"],
                session["id"],
                device_version(api, device["id"]),
                supersedes_credential_id=predecessor["id"],
                expedite=True,
            ),
            ADJUDICATOR,
        )

    def test_the_settlement_uses_the_tier_of_the_pre_waiver_total(self, api):
        """An expedited rebinding after a loss totals 5300 pre-waiver, which is
        tier one plus the loss allowance, settling at 3975.

        PRD 3.4: "The waiver tier is selected **from the pre-waiver total, never
        from the settlement**: 20 percent when the pre-waiver total is at least
        5300 cents, otherwise 10 percent when it is at least 3800 cents,
        otherwise nothing."
        PRD 3.4: "Re-deriving the tier from the step-6 result would produce a
        different and wrong number and is explicitly forbidden."

        Design: Difficulty/combinatorial_formula/reissuance_waiver_tier_pinned_to_pre_waiver_total_not_settlement
        """
        holder, predecessor, device, session = self._lost_handset_and_a_replacement_ready(
            api
        )

        replacement = validate_success(
            self._reissue(api, holder, predecessor, device, session), 201
        )
        assert_cents(replacement, "reissuance_settlement_cents", 3975)
        assert replacement["reissuance_settlement_cents"] != 4505

    def test_the_replacement_points_at_a_predecessor_still_suspended_for_loss(self, api):
        """The five-percent loss allowance is earned by a predecessor that is
        still SUSPENDED for DEVICE_LOST at provisioning time.

        PRD 3.4: "An additional 5 percent is added to the waiver percentage when
        the predecessor credential is `SUSPENDED` with a `suspend_reason` of
        `DEVICE_LOST` - the resident whose phone was stolen is not charged full
        price for the replacement."

        Design: Difficulty/combinatorial_formula/reissuance_waiver_tier_pinned_to_pre_waiver_total_not_settlement
        """
        holder, predecessor, device, session = self._lost_handset_and_a_replacement_ready(
            api
        )

        replacement = validate_success(
            self._reissue(api, holder, predecessor, device, session), 201
        )
        assert_field_values(
            replacement,
            {
                "supersedes_credential_id": predecessor["id"],
                "lifecycle_state": "PENDING_PROVISION",
            },
        )

        old = validate_success(api.get_credential(predecessor["id"], ADMIN))
        assert_field_values(
            old, {"lifecycle_state": "SUSPENDED", "suspend_reason": "DEVICE_LOST"}
        )
