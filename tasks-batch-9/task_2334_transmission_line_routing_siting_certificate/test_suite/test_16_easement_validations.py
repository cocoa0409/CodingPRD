"""Rules that guard negotiation, condemnation and the escrow ledger.

The acquisition track and the payment track move independently, so every
refusal here is checked against the tract's two dimensions and against the
project's four escrow figures.
"""

from test_helpers import (
    ApiErrorId,
    assert_is_null,
    assert_timestamp_equals,
    get_success_data,
    validate_error,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


CANONICAL_FIRST_OFFER_CENTS = 4_163_406


class TestPaymentAndRescissionWindows:
    """Cash may not exceed the balance, and it may not be recalled forever."""

    def test_payment_above_the_escrow_balance_is_refused(self, api):
        """PRD §3.8: "It requires the tract to be at `AGREED` or `AWARDED` on the
        acquisition track, and it requires the project's `escrow_balance_cents` to be
        at least the tract's `committed_cents`; a shortfall is refused with
        `ERR_ESCROW_INSUFFICIENT` (HTTP 402)."

        Design: Corner/validations/payment_above_the_escrow_balance_rejected
        """
        ctx = fx.setup_issued_certificate(api)
        fx.setup_agreed_tract(api, ctx)
        fx.fund_escrow(api, ctx, amount_cents=1_000_000, reference="ESCROW-THIN")

        response = api.create_payment(
            ctx["tract1"], f.payment_payload(payment_reference="WIRE-9"),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(response, ApiErrorId.ESCROW_INSUFFICIENT, expected_status=402)

        tract = fx.read_tract(api, ctx["tract1"])
        assert tract["committed_cents"] == CANONICAL_FIRST_OFFER_CENTS, (
            f"Acceptance committed the first offer, got {tract['committed_cents']}"
        )
        assert tract["payment_status"] == "UNPAID", (
            f"The refused disbursement leaves the tract UNPAID, got "
            f"{tract['payment_status']}"
        )
        assert tract["paid_amount_cents"] == 0, (
            f"Nothing was disbursed, got {tract['paid_amount_cents']}"
        )
        project = fx.read_project(api, ctx)
        assert project["escrow_balance_cents"] == 1_000_000, (
            f"The thin balance is untouched, got {project['escrow_balance_cents']}"
        )
        assert project["escrow_disbursed_cents"] == 0, (
            f"Nothing reached the disbursed total, got "
            f"{project['escrow_disbursed_cents']}"
        )

    def test_rescission_at_or_beyond_thirty_days_is_refused(self, api):
        """PRD §3.8: "rescission is permitted while the logical clock is strictly
        earlier than 30 days after `paid_at`, and at or beyond that point it is refused
        with `ERR_RESCISSION_WINDOW_EXPIRED` (HTTP 422)."

        Design: Corner/validations/rescission_at_the_thirty_day_boundary_rejected
        """
        ctx = fx.setup_issued_certificate(api)
        fx.setup_paid_tract(api, ctx)
        fx.set_clock(api, "2026-11-05T00:00:00Z")

        response = api.rescind_payment(
            ctx["tract1"], f.rescission_payload(rescission_reason="Wrong parcel wired"),
            fx.COMMISSION_STAFF_HEADERS,
        )
        validate_error(
            response, ApiErrorId.RESCISSION_WINDOW_EXPIRED, expected_status=422
        )

        tract = fx.read_tract(api, ctx["tract1"])
        assert tract["payment_status"] == "PAID", (
            f"The disbursement stands, got {tract['payment_status']}"
        )
        assert tract["paid_amount_cents"] == CANONICAL_FIRST_OFFER_CENTS, (
            f"The paid amount is unchanged, got {tract['paid_amount_cents']}"
        )
        assert_timestamp_equals(tract["paid_at"], "2026-10-05T09:00:00Z", "paid_at")
        project = fx.read_project(api, ctx)
        assert project["escrow_disbursed_cents"] == CANONICAL_FIRST_OFFER_CENTS, (
            f"The disbursed total is unchanged, got "
            f"{project['escrow_disbursed_cents']}"
        )
        assert project["escrow_balance_cents"] == 595_836_594, (
            f"The balance is unchanged, got {project['escrow_balance_cents']}"
        )


class TestNegotiationCap:
    """Three offers is the whole negotiation."""

    def test_a_fourth_offer_on_a_tract_is_refused(self, api):
        """PRD §3.8: "Offers are capped at three: a tract whose `offer_round` has
        already reached 3 is refused with `ERR_OFFER_LIMIT_REACHED` (HTTP 409)."

        Design: Corner/validations/fourth_offer_on_a_tract_rejected
        """
        ctx = fx.setup_issued_certificate(api)
        fx.setup_rejected_tract(api, ctx, rounds=3)

        response = api.create_offer(
            ctx["tract1"],
            f.offer_payload(ctx["tract1_version"], offer_note="One more try"),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(response, ApiErrorId.OFFER_LIMIT_REACHED, expected_status=409)

        tract = fx.read_tract(api, ctx["tract1"])
        assert tract["offer_round"] == 3, (
            f"Three offers were extended and no more, got {tract['offer_round']}"
        )
        assert tract["acquisition_status"] == "REJECTED", (
            f"The tract rests at REJECTED, ready for condemnation, got "
            f"{tract['acquisition_status']}"
        )
        assert_is_null(tract, "agreed_compensation_cents", "EasementTract")
        assert tract["committed_cents"] == 0, (
            f"Nothing was ever committed on this tract, got {tract['committed_cents']}"
        )


class TestCondemnationGates:
    """Authority, round count, the project's hold, and the award measure."""

    def test_condemnation_after_a_single_offer_is_refused(self, api):
        """PRD §3.8: "The certificate must confer eminent-domain authority and at
        least two offers must already have been extended — that is, `offer_round` must
        be at least 2 — or the filing is refused with
        `ERR_EMINENT_DOMAIN_NOT_AUTHORIZED` (HTTP 403)."

        Design: Corner/validations/condemnation_after_a_single_offer_rejected
        """
        ctx = fx.setup_issued_certificate(api)
        fx.setup_rejected_tract(api, ctx, rounds=1)

        response = api.file_condemnation(
            ctx["tract1"],
            f.condemnation_payload(
                court_docket_number="HAR-CV-2026-118", deposit_cents=4_200_000
            ),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(
            response, ApiErrorId.EMINENT_DOMAIN_NOT_AUTHORIZED, expected_status=403
        )

        assert fx.read_certificate(api, ctx["cert"])["eminent_domain_authorized"] is True, (
            "The order did confer condemnation authority, so only the round count "
            "can be the binding conjunct"
        )
        tract = fx.read_tract(api, ctx["tract1"])
        assert tract["offer_round"] == 1, (
            f"Exactly one offer was extended, got {tract['offer_round']}"
        )
        assert tract["acquisition_status"] == "REJECTED", (
            f"The tract stays at REJECTED, got {tract['acquisition_status']}"
        )
        assert_is_null(tract, "court_docket_number", "EasementTract")
        assert_is_null(tract, "deposit_cents", "EasementTract")

    def test_a_right_of_way_hold_freezes_the_condemnation_programme(self, api):
        """PRD §3.8: "The project must not carry a right-of-way hold: a project whose
        `right_of_way_hold` is true refuses the filing with `ERR_RIGHT_OF_WAY_HOLD`
        (HTTP 409), which is how a slipping schedule freezes the condemnation
        programme."

        Design: Corner/validations/condemnation_under_a_right_of_way_hold_rejected
        """
        ctx = fx.setup_accepted_application(api)
        fx.create_landowner(api, ctx, "lo1")
        fx.petition_to_intervene(api, ctx, "int1", landowner_key="lo1")
        fx.rule_on_petition(
            api, ctx, "int1", ruling="GRANT",
            reason="Direct property interest on segment 1",
        )
        group_petition = get_success_data(
            api.create_intervention(
                f.intervention_payload(
                    ctx["app"], petitioner_kind="INTEREST_GROUP",
                    grounds="Cumulative impact on the flyway",
                    organization_name="Cumberland Flyway Alliance",
                ),
                fx.COMMISSION_STAFF_HEADERS,
            )
        )
        ctx["int2"] = group_petition["id"]
        fx.rule_on_petition(
            api, ctx, "int2", ruling="GRANT",
            reason="Representational standing shown",
        )
        fx.schedule_session(api, ctx)
        fx.set_clock(api, "2026-10-05T09:00:00Z", fx.HEARING_EXAMINER_HEADERS)
        fx.hold_session(api, ctx)
        fx.close_record(api, ctx)
        fx.record_decision(api, ctx)
        fx.capture_certificate(api, ctx)
        fx.setup_rejected_tract(api, ctx, rounds=2)

        response = api.file_condemnation(
            ctx["tract1"],
            f.condemnation_payload(
                court_docket_number="HAR-CV-2026-118", deposit_cents=4_200_000
            ),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(response, ApiErrorId.RIGHT_OF_WAY_HOLD, expected_status=409)

        application = fx.read_application(api, ctx["app"])
        assert application["suspension_days"] == 90, (
            f"The second grant suspended the statutory clock by 90 days, got "
            f"{application['suspension_days']}"
        )
        assert_timestamp_equals(
            application["decision_deadline_at"], "2027-11-29T00:00:00Z",
            "decision_deadline_at",
        )
        project = fx.read_project(api, ctx)
        assert project["schedule_posture"] == "AT_RISK", (
            f"The lengthened deadline leaves under 180 days of slack, got "
            f"{project['schedule_posture']}"
        )
        assert project["right_of_way_hold"] is True, (
            f"An AT_RISK project carries the hold, got {project['right_of_way_hold']}"
        )
        tract = fx.read_tract(api, ctx["tract1"])
        assert tract["offer_round"] == 2, (
            f"Two offers were extended, so the authority conjuncts are satisfied, got "
            f"{tract['offer_round']}"
        )
        assert_is_null(tract, "court_docket_number", "EasementTract")

    def test_an_award_without_value_diminution_is_refused(self, api):
        """PRD §3.8: "The whole-property diminution is `before_value_cents` minus
        `after_value_cents`, and that difference must be strictly positive — an award
        recorded where the before value does not exceed the after value is refused with
        `ERR_NO_VALUE_DIMINUTION` (HTTP 422)."

        Design: Corner/validations/award_without_value_diminution_rejected
        """
        ctx = fx.setup_issued_certificate(api)
        fx.create_landowner(api, ctx, "lo1")
        fx.create_tract(
            api, ctx, key="tract2", segment_key="seg2", landowner_key="lo1",
            parcel_number="B-207-04", acres=8.00, per_acre_value_cents=300_000,
            easement_factor=0.50, structure_damages_cents=0,
            before_value_cents=90_000_000, after_value_cents=90_000_000,
            severance_damages_cents=0,
        )
        for note in ("First offer", "Second offer"):
            fx.extend_offer(api, ctx, key="tract2", note=note)
            fx.respond_to_offer(
                api, ctx, key="tract2", response="REJECT", note="Refused",
                landowner_key="lo1",
            )
        fx.file_condemnation(
            api, ctx, key="tract2", court_docket_number="BOO-CV-2026-311",
            deposit_cents=1_200_000,
        )

        response = api.record_award(
            ctx["tract2"], f.award_payload(award_note="Commissioners report filed"),
            fx.COMMISSION_STAFF_HEADERS,
        )
        validate_error(response, ApiErrorId.NO_VALUE_DIMINUTION, expected_status=422)

        tract = fx.read_tract(api, ctx["tract2"])
        assert tract["acquisition_status"] == "CONDEMNATION_FILED", (
            f"The tract stays in the filed condemnation, got "
            f"{tract['acquisition_status']}"
        )
        assert_is_null(tract, "award_cents", "EasementTract")
        assert tract["committed_cents"] == 0, (
            f"No award means nothing is committed, got {tract['committed_cents']}"
        )
        assert tract["deposit_cents"] == 1_200_000, (
            f"The court deposit was recorded by the filing, got "
            f"{tract['deposit_cents']}"
        )
