"""Multi-step journeys through the catalogue, channel and warranty action endpoints.

A certified model is released and then manually suspended, a submitted package
quote is pushed back for revision and resubmitted against an amended line set,
per-model warranty exposure is aggregated by component class and duty cycle, and a
claim naming an unknown service part is refused before its other body references
are resolved.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as E
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    CHANNEL_MANAGER,
    COMPLIANCE_OFFICER,
    PRODUCT_ENGINEER,
    UID_CHANNEL_MANAGER,
    WARRANTY_ANALYST,
)

# Path identifiers that resolve to nothing, used to probe body reference ordering.
UNKNOWN_BUILD_ORDER_ID = "00000000-0000-4000-8000-0000000000b1"
UNKNOWN_TECHNICIAN_ID = "00000000-0000-4000-8000-0000000000c1"


def _submitted_cash_quote(api):
    """An AUTHORIZED distributor holding one submitted, unfinanced single-unit quote."""
    channel = fx.make_authorized_distributor(api)
    model = fx.make_model(api)
    quote = fx.make_quote(api, channel, financing_program="NONE")
    fx.add_quote_line(api, quote["id"], channel, model["id"], quantity=1)
    submitted = validate_success(
        api.submit_quote(quote["id"], channel["headers"]), expected_status=200
    )
    return {"channel": channel, "model": model, "quote": submitted}


class TestModelLifecycleActions:
    """One action endpoint carries both of the model's manual transitions."""

    def test_01_release_moves_a_certified_model_to_released(self, api, certified_model):
        """A release makes a certified machine model sellable without touching its
        suspension record.

        PRD: "A release moves the model from `CERTIFIED` to `RELEASED` and advances its `version` by 1; attempting it from any other state is `ERR_MODEL_STATE_INVALID`."
        Design: Corner/endpoints/model_lifecycle_release_then_manual_suspend
        """
        released = validate_success(
            api.machine_model_lifecycle_action(
                certified_model["model"]["id"],
                f.lifecycle_action_payload("RELEASE"),
                PRODUCT_ENGINEER,
            ),
            expected_status=200,
        )
        assert released["certification_state"] == "RELEASED"
        assert released["suspended_reason"] == "NONE"
        assert released["version"] == 3

    def test_02_manual_suspend_from_released_records_a_manual_reason(
        self, api, released_model
    ):
        """Suspending a released model by hand records MANUAL rather than the
        cascade's own reason and clears the model's rebate snapshot.

        PRD: "A manual suspension moves the model from `RELEASED` to `SUSPENDED`, sets `suspended_reason` to `MANUAL`, empties `rebate_program_codes` and resets `rebate_amount_cents` to 0, and advances the model's `version` by 1; attempting it from any state other than `RELEASED` is likewise `ERR_MODEL_STATE_INVALID`."
        Design: Corner/endpoints/model_lifecycle_release_then_manual_suspend
        """
        suspended = validate_success(
            api.machine_model_lifecycle_action(
                released_model["model"]["id"],
                f.lifecycle_action_payload("SUSPEND", reason="MANUAL"),
                PRODUCT_ENGINEER,
            ),
            expected_status=200,
        )
        assert suspended["certification_state"] == "SUSPENDED"
        assert suspended["suspended_reason"] == "MANUAL"
        assert suspended["rebate_program_codes"] == []
        a.assert_cents(suspended["rebate_amount_cents"], 0)
        assert suspended["version"] == 4

        dossier = validate_success(
            api.get_certification_dossier(
                released_model["dossier"]["id"], COMPLIANCE_OFFICER
            ),
            expected_status=200,
        )
        assert dossier["dossier_state"] == "CERTIFIED"


class TestQuoteRevisionRound:
    """A revision request is the one channel decision that reopens a quote."""

    def test_01_request_revision_reopens_the_quote_without_final_terms(self, api):
        """Pushing a submitted quote back for revision counts the round and clears
        the provisional terms while leaving the final terms unwritten.

        PRD: "A revision request moves the quote from `SUBMITTED` to `REVISION_REQUESTED`, increases `revision_round` by 1, resets `provisional_apr_bp` and `provisional_monthly_payment_cents` back to null so that the next submission recomputes them from whatever the lines then say, and makes the lines editable again."
        Design: Corner/endpoints/quote_decision_requests_revision_then_accepts_resubmission
        """
        env = _submitted_cash_quote(api)
        revised = validate_success(
            api.decide_quote(
                env["quote"]["id"],
                f.quote_decision_payload("REQUEST_REVISION", note="add the second washer"),
                CHANNEL_MANAGER,
            ),
            expected_status=200,
        )
        a.assert_quote_state(revised, "REVISION_REQUESTED")
        assert revised["revision_round"] == 1
        assert revised["decided_by_user_id"] == UID_CHANNEL_MANAGER
        assert revised["provisional_apr_bp"] is None
        assert revised["provisional_monthly_payment_cents"] is None
        assert revised["verified_credit_score"] is None
        assert revised["final_apr_bp"] is None

    def test_02_resubmission_carries_the_amended_line_set(self, api):
        """A distributor may add a line to a quote that came back for revision and
        resubmit it, and the second submission prices the amended package.

        PRD: "Submitting a quote for a channel decision moves it from `DRAFT` to `SUBMITTED`, or from `REVISION_REQUESTED` to `SUBMITTED`, and advances the quote's `version` by 1."
        Design: Corner/endpoints/quote_decision_requests_revision_then_accepts_resubmission
        """
        env = _submitted_cash_quote(api)
        channel = env["channel"]
        quote_id = env["quote"]["id"]
        validate_success(
            api.decide_quote(
                quote_id, f.quote_decision_payload("REQUEST_REVISION"), CHANNEL_MANAGER
            ),
            expected_status=200,
        )

        second_line = validate_success(
            api.create_quote_line(
                quote_id,
                f.quote_line_payload(
                    env["model"]["id"],
                    fx.read_quote_version(api, quote_id, channel),
                    quantity=1,
                ),
                channel["headers"],
            ),
            expected_status=201,
        )
        a.assert_cents(second_line["line_total_cents"], 1250000)

        resubmitted = validate_success(
            api.submit_quote(quote_id, channel["headers"]), expected_status=200
        )
        a.assert_quote_state(resubmitted, "SUBMITTED")
        assert resubmitted["line_count"] == 2
        a.assert_cents(resubmitted["total_cents"], 2500000)
        assert resubmitted["revision_round"] == 1
        a.assert_cents(resubmitted["origination_fee_cents"], 0)


class TestWarrantyExposureAnalysis:
    """The per-model exposure read is computed over the model's whole claim set."""

    def test_01_the_rollup_aggregates_the_models_settled_claims(
        self, api, warranty_environment
    ):
        """One approved full-replacement claim on a model's accepted unit is
        reported by the model's exposure read and grouped on both axes.

        PRD: "It aggregates every warranty claim whose claimed unit belongs to the addressed model and reports: the `model_id` addressed; `claim_count`, the total number of matching claims; `approved_claim_count`, `denied_claim_count`, `blocked_claim_count` and `voided_claim_count`, the counts sitting in `APPROVED`, `DENIED`, `FULFILLMENT_BLOCKED` and `VOIDED` respectively; `covered_amount_total_cents`, the summed settled amount **excluding** voided claims, since voided money was reversed even though the claim retains its figure; `full_replacement_count` and `pro_rata_count`, the number of settlements produced by each coverage form; `component_class_breakdown`, the exposure grouped by the `component_class` of the claimed part; and `duty_cycle_breakdown`, the same exposure grouped by `duty_cycle_class`."
        Design: Corner/endpoints/warranty_analysis_computed_read_groups_by_component_and_duty
        """
        env = warranty_environment
        claim = fx.make_submitted_claim(api, env)
        fx.adjudicate_claim(api, claim["id"], env["part"]["id"], "APPROVE")

        analysis = validate_success(
            api.get_warranty_analysis(env["model"]["id"], WARRANTY_ANALYST),
            expected_status=200,
        )
        assert analysis["model_id"] == env["model"]["id"]
        assert analysis["claim_count"] == 1
        assert analysis["approved_claim_count"] == 1
        assert analysis["denied_claim_count"] == 0
        assert analysis["blocked_claim_count"] == 0
        assert analysis["voided_claim_count"] == 0
        a.assert_cents(analysis["covered_amount_total_cents"], 42000)
        assert analysis["full_replacement_count"] == 1
        assert analysis["pro_rata_count"] == 0
        assert set(analysis["component_class_breakdown"]) == {"BEARING"}
        assert set(analysis["duty_cycle_breakdown"]) == {"STANDARD"}

    def test_02_the_duty_cycle_filter_narrows_the_claim_set(
        self, api, warranty_environment
    ):
        """Asking for HEAVY duty exposure on a model whose only claim is STANDARD
        returns an empty rollup rather than the unfiltered totals.

        PRD: "Finally, the manufacturer needs to see where warranty money is actually going, and that is the purpose of the per-model warranty exposure read, available to a `WarrantyAnalyst` and to a `ProductEngineer` and optionally narrowed by a `duty_cycle_class` filter."
        Design: Corner/endpoints/warranty_analysis_computed_read_groups_by_component_and_duty
        """
        env = warranty_environment
        claim = fx.make_submitted_claim(api, env)
        fx.adjudicate_claim(api, claim["id"], env["part"]["id"], "APPROVE")

        narrowed = validate_success(
            api.get_warranty_analysis(
                env["model"]["id"], WARRANTY_ANALYST, duty_cycle_class="HEAVY"
            ),
            expected_status=200,
        )
        assert narrowed["model_id"] == env["model"]["id"]
        assert narrowed["claim_count"] == 0
        a.assert_cents(narrowed["covered_amount_total_cents"], 0)


class TestWarrantyClaimBodyReferences:
    """Body foreign keys on a claim filing are resolved in a fixed order."""

    def test_01_claim_naming_an_unknown_part_reports_the_part_failure(
        self, api, pending_distributor
    ):
        """A filing whose part, unit and reporting technician are all unknown is
        refused for the part specifically, and nothing is recorded.

        PRD: "A body `part_id` resolves to a stored service part, and a body `supersedes_part_id` resolves to a stored service part when it is present — otherwise `ERR_PART_NOT_FOUND`, HTTP 404."
        Design: Corner/endpoints/warranty_claim_referencing_unknown_part_not_found
        """
        env = pending_distributor
        rejected = api.create_warranty_claim(
            f.warranty_claim_payload(
                UNKNOWN_BUILD_ORDER_ID,
                NON_EXISTENT_UUID,
                env["distributor"]["id"],
                UNKNOWN_TECHNICIAN_ID,
                failure_cycle_count=1000,
                in_service_months=6,
                duty_cycle_class="STANDARD",
                diagnostics_code="BRG-NOISE",
            ),
            env["headers"],
        )
        validate_error(rejected, E.ERR_PART_NOT_FOUND, expected_status=404)

        rows, meta = validate_paginated(api.list_warranty_claims(WARRANTY_ANALYST))
        assert rows == []
        assert meta["total_count"] == 0

        distributor = validate_success(
            api.get_distributor(env["distributor"]["id"], CHANNEL_MANAGER),
            expected_status=200,
        )
        assert distributor["open_claim_count"] == 0
