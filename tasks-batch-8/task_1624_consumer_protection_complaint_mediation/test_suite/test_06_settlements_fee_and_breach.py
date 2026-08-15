"""Settlement documentation: fee tiering, OCC, execution, and breach."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_offer,
    assert_iso_instant,
    assert_settlement,
    complaint_version,
    create_settlement_payload,
    drive_to_executed_settlement,
    get_complaint,
    make_intake_officer_headers,
    make_mediator_headers,
    register_case_parties,
    set_clock,
    setup_mediation_active_case,
    tender_offer,
    validate_error,
    validate_success,
)

OFFICER_1 = TEST_USERS["intake_officer_headers"]
DIRECTOR_1 = TEST_USERS["unit_director_headers"]


def _setup_accepted_big_offer(api):
    """Complaint MEDIATION_ACTIVE with a 600,000-cent offer ACCEPTED by the consumer."""
    ctx = setup_mediation_active_case(
        consumer_overrides={"full_name": "C F", "email": "cf@x.com"},
        business_overrides={"legal_name": "FeeCo"},
        complaint_overrides={
            "category": "CONTRACT_VIOLATION",
            "description": "big",
            "amount_in_dispute_cents": 600000,
        },
    )
    complaint_id = ctx["complaint"]["id"]
    offer = tender_offer(complaint_id, ctx["business"], "BUSINESS", 600000)
    accepted = accept_offer(offer["id"], ctx["consumer"], "CONSUMER")
    return ctx, accepted


class TestSettlementFeeEvaluationOrder:
    def test_tier3_fee_keyed_on_restitution_subtotal(self, api):
        """PRD §3.6: "The unit charges a tiered mediation fee keyed on the restitution subtotal only — never on the fee-inclusive total."
        PRD §3.6: "When it is 500,000 cents or more, the fee is two percent of the first 500,000 cents plus one percent of the excess above 500,000 cents, the sum rounded half-up to whole cents."
        PRD §3.6: "a restitution of 600,000 cents yields a fee of 11,000 cents and a `total_due_cents` of 611,000 cents, whereas the same rate mistakenly applied to the fee-inclusive total would produce 11,110 and 611,110"

        Design: Difficulty/combinatorial_formula/d_fee_evaluation_order
        """
        ctx, accepted = _setup_accepted_big_offer(api)
        set_clock(accepted["cooling_off_until"])
        version = complaint_version(ctx["complaint"]["id"])
        settlement = validate_success(
            api.create_settlement(
                ctx["complaint"]["id"], create_settlement_payload(version),
                make_mediator_headers(ctx["mediator"]["id"]),
            ),
            201,
        )
        assert_settlement(settlement)
        # 0.02 * 500000 + 0.01 * (600000 - 500000) = 10000 + 1000 = 11000.
        assert settlement["mediation_fee_cents"] == 11000

    def test_total_due_is_restitution_plus_fee_not_fee_on_total(self, api):
        """PRD §3.6: "The `total_due_cents` is then the restitution plus the fee."
        PRD §3.6: "The new settlement copies `restitution_amount_cents` from its source offer and both `business_id` and `consumer_id` from the complaint"
        PRD §3.6: "opens with a `settlement_status` of `DRAFT` and `fulfilled_cents` at zero"

        Design: Difficulty/combinatorial_formula/d_fee_evaluation_order
        """
        ctx, accepted = _setup_accepted_big_offer(api)
        set_clock(accepted["cooling_off_until"])
        version = complaint_version(ctx["complaint"]["id"])
        settlement = validate_success(
            api.create_settlement(
                ctx["complaint"]["id"], create_settlement_payload(version),
                make_mediator_headers(ctx["mediator"]["id"]),
            ),
            201,
        )
        assert settlement["restitution_amount_cents"] == 600000
        assert settlement["total_due_cents"] == 611000, "fee computed on the restitution subtotal"
        assert settlement["settlement_status"] == "DRAFT"
        assert settlement["fulfilled_cents"] == 0
        assert settlement["outstanding_cents"] == 600000
        assert settlement["source_offer_id"] == accepted["id"]
        assert settlement["business_id"] == ctx["business"]["id"]
        assert settlement["consumer_id"] == ctx["consumer"]["id"]


class TestSettlementOptimisticConcurrency:
    def test_settlement_create_with_stale_complaint_version_rejected(self, api):
        """PRD §2.8: "If the complaint's current `version` has advanced beyond the supplied value, the write is refused with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the complaint before retrying."
        PRD §2.8: "documenting a settlement supersedes an existing settlement and likewise advances the `version`"
        PRD §3.6: "the complaint's `active_settlement_id` is repointed to the new document"

        Design: Corner/complexity_layers/c_occ_settlement_stale_version_rejected
        """
        ctx = setup_mediation_active_case(
            consumer_overrides={"full_name": "OS2", "email": "os2@x.com"},
            business_overrides={"legal_name": "OccCo"},
            complaint_overrides={"category": "OTHER", "description": "os2"},
        )
        complaint_id = ctx["complaint"]["id"]
        offer = tender_offer(complaint_id, ctx["business"], "BUSINESS", 1000)
        accepted = accept_offer(offer["id"], ctx["consumer"], "CONSUMER")
        set_clock(accepted["cooling_off_until"])

        stale_version = complaint_version(complaint_id)
        first = validate_success(
            api.create_settlement(
                complaint_id, create_settlement_payload(stale_version),
                make_mediator_headers(ctx["mediator"]["id"]),
            ),
            201,
        )
        assert first["settlement_status"] == "DRAFT", "first create succeeded and bumped the version"

        replayed = api.create_settlement(
            complaint_id, create_settlement_payload(stale_version),
            make_mediator_headers(ctx["mediator"]["id"]),
        )
        validate_error(replayed, ApiErrorId.ERR_STALE_VERSION)

        complaint = get_complaint(complaint_id)
        assert complaint["active_settlement_id"] == first["id"], "no second settlement materialized"


class TestSettlementBreach:
    def test_breach_after_due_date_reopens_mediation(self, api):
        """PRD §3.6: "Execution stamps `executed_at`, sets the `due_date` thirty days later"
        PRD §3.6: "When the `due_date` has strictly passed and money remains outstanding, an `IntakeOfficer` or the `UnitDirector` may mark the settlement `BREACHED`"
        PRD §3.6: "Breach reopens negotiation: the complaint falls back from `SETTLEMENT_PENDING` to `MEDIATION_IMPASSE`, and a `SETTLEMENT_BREACHED` event is written."

        Design: Corner/state_machines/c_sm_settlement_breach_reopens_mediation
        """
        parties = register_case_parties(
            consumer_overrides={"full_name": "Br", "email": "br@x.com"},
            business_overrides={"legal_name": "BrCo"},
        )
        ctx = drive_to_executed_settlement(
            parties["consumer"], parties["business"], parties["mediator"], parties["room"],
            incident_date="2026-07-01", description="br", restitution_cents=5000,
            session_starts_at="2026-08-10T10:00:00Z", session_ends_at="2026-08-10T11:00:00Z",
        )
        settlement = ctx["settlement"]
        assert_iso_instant(settlement["due_date"], "2026-09-03T00:00:00Z", "due_date")
        assert get_complaint(ctx["complaint"]["id"])["case_status"] == "SETTLEMENT_PENDING"

        set_clock("2026-09-04T00:00:00Z")  # strictly past the due date
        breached = validate_success(api.mark_settlement_breached(settlement["id"], OFFICER_1))
        assert breached["settlement_status"] == "BREACHED"
        assert get_complaint(ctx["complaint"]["id"])["case_status"] == "MEDIATION_IMPASSE"

    def test_breach_before_due_date_rejected(self, api):
        """PRD §3.6: "marking too early — current time at or before the `due_date` — or with nothing outstanding draws `ERR_BREACH_NOT_DUE`"

        Design: Corner/errors/c_err_breach_not_due_rejected
        """
        parties = register_case_parties(
            consumer_overrides={"full_name": "BD", "email": "bd@x.com"},
            business_overrides={"legal_name": "BdCo"},
        )
        ctx = drive_to_executed_settlement(
            parties["consumer"], parties["business"], parties["mediator"], parties["room"],
            incident_date="2026-07-01", description="bd", restitution_cents=5000,
            session_starts_at="2026-08-10T10:00:00Z", session_ends_at="2026-08-10T11:00:00Z",
        )
        set_clock("2026-08-20T00:00:00Z")  # at-or-before the 2026-09-03 due date
        resp = api.mark_settlement_breached(ctx["settlement"]["id"], OFFICER_1)
        validate_error(resp, ApiErrorId.ERR_BREACH_NOT_DUE)

        settlement = validate_success(api.get_settlement(ctx["settlement"]["id"], OFFICER_1))
        assert settlement["settlement_status"] == "EXECUTED", "unchanged by the early breach attempt"
