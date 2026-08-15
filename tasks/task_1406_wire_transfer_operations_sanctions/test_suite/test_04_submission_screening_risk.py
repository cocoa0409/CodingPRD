"""Submission and screening: the five-component risk score, its inclusive
bands, the strict velocity threshold, the SWIFT conservative variant, and the
repair-time recompute."""
from test_helpers import (
    ApiErrorId,
    assert_sanctions_hit,
    assert_wire,
    create_executed_wire,
    create_wire,
    dual_approve_wire,
    get_account,
    list_wire_sanctions_hits,
    release_open_hits,
    release_wire,
    setup_wire_room,
    submit_wire,
    validate_error,
    validate_success,
    wire_version,
)
from test_helpers import TEST_USERS

OPERATOR = TEST_USERS["wire_operator_headers"]
REPAIR_SPECIALIST = TEST_USERS["repair_specialist_headers"]


class TestRiskScoreAmountBands:
    def test_risk_score_amount_band_edges(self, api):
        """PRD §3.3: "The amount band contributes nothing when the principal
        is below one million dollars, 25 points when the principal is at least
        one million dollars but below five million dollars, and 40 points when
        it is at least five million dollars."
        PRD §3.3: "By default the term is taken when the beneficiary record's
        `first_used_at` is still null."
        PRD §3.3: "a request carrying `waive_callback` set to true is honored
        when the ordering customer's `risk_rating` is `LOW`, sets the wire's
        `callback_status` to `WAIVED`, and is recorded in the audit log"

        A 99999999-cent wire scores band 0 plus the new-beneficiary 10; after
        it executes, a 100000000-cent wire to the same beneficiary scores the
        inclusive band 25 alone, with its callback obligation waived.

        Design: Corner/calculations/risk_score_amount_band_edges
        """
        room = setup_wire_room(
            business_date="2026-09-14",
            customer_overrides={"risk_rating": "LOW", "high_risk_jurisdiction": False},
            account_overrides={"daily_outgoing_limit_cents": 500000000},
        )
        account = room["account"]
        beneficiary = room["beneficiary"]

        wire_lo = create_executed_wire(
            account["id"], beneficiary["id"], "2026-09-14", 99999999)
        assert wire_lo["risk_score"] == 10, (
            f"99999999 cents: band 0 + new-beneficiary 10, got {wire_lo['risk_score']}")

        wire_hi = create_wire(account["id"], beneficiary["id"], 100000000)
        submitted = submit_wire(wire_hi["id"], "2026-09-14", waive_callback=True)
        assert_wire(submitted)
        assert submitted["risk_score"] == 25, (
            f"100000000 cents: inclusive band 25, beneficiary now used; "
            f"got {submitted['risk_score']}")
        assert submitted["callback_status"] == "WAIVED"
        assert submitted["screening_status"] == "CLEAR"


class TestSubmitNotIdempotent:
    def test_double_submit_rejected(self, api):
        """PRD §3.3: "Submission moves a wire from `INITIATED` — or from
        `CALLBACK_PENDING` once verification is satisfied — into
        `PENDING_APPROVAL`."
        PRD §2.8: "(10) the generic state precondition on action endpoints
        (`ERR_INVALID_STATE`)"
        PRD §2.6: "Submission creates a reservation: the wire's
        `reservation_active` becomes true and the wire's `amount_cents` is
        added to the ordering account's `daily_reserved_cents`."

        A second submit on a PENDING_APPROVAL wire is rejected and no second
        reservation is created.

        Design: Corner/state_machines/double_submit_rejected
        """
        room = setup_wire_room(business_date="2026-08-27")
        wire = create_wire(room["account"]["id"], room["beneficiary"]["id"], 100000)
        submit_wire(wire["id"], "2026-08-27")

        resp = api.submit_wire(wire["id"], {"business_date": "2026-08-27"}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        account = get_account(room["account"]["id"])
        assert account["daily_reserved_cents"] == 100000, (
            f"the reservation was created exactly once, got "
            f"{account['daily_reserved_cents']}")


class TestSwiftConservativeVariant:
    def test_swift_conservative_variant_on_new_beneficiary(self, api):
        """PRD §3.3: "The new-beneficiary term has two readings, and the
        wire's rail chooses between them."
        PRD §3.3: "When the wire travels by `SWIFT`, the cross-border
        convention applies instead: the term is taken whenever the
        beneficiary's **bank** — identified by the combination of `bank_name`
        and `country_code` — has never appeared on a prior `EXECUTED` wire of
        this account, even if this beneficiary record's `first_used_at` is
        already set."

        A prior EXECUTED wire to beneficiary one at BankOne/DE seeds the
        bank's history; a new beneficiary record at the same bank on a SWIFT
        wire scores 0 and screens CLEAR.

        Design: Difficulty/dual_variant_calc/risk_score_swift_conservative_variant_on_new_beneficiary
        """
        room = setup_wire_room(
            business_date="2026-08-04",
            customer_overrides={"risk_rating": "LOW", "high_risk_jurisdiction": False},
            beneficiary_overrides={
                "name": "Person One", "bank_name": "BankOne", "country_code": "DE",
            },
        )
        account = room["account"]
        ben_one = room["beneficiary"]

        create_executed_wire(
            account["id"], ben_one["id"], "2026-08-04", 50000000,
            method="Fedwire", purpose="seed wire")

        ben_two = validate_success(api.create_beneficiary(
            {
                "customer_id": room["customer"]["id"],
                "name": "Person Two",
                "bank_name": "BankOne",
                "account_number": "B-9102",
                "country_code": "DE",
            },
            OPERATOR,
        ), 201)

        wire_b = create_wire(account["id"], ben_two["id"], 50000000,
                             method="SWIFT", purpose="variant probe")
        submitted = submit_wire(wire_b["id"], "2026-08-04")
        assert_wire(submitted)
        assert submitted["risk_score"] == 0, (
            f"SWIFT conservative reading: bank already seen on this account, "
            f"new-beneficiary term not taken; got {submitted['risk_score']}")
        assert submitted["screening_status"] == "CLEAR"

    def test_default_record_reading_scores_new_beneficiary(self, api):
        """PRD §3.3: "The new-beneficiary term has two readings, and the
        wire's rail chooses between them. By default the term is taken when
        the beneficiary record's `first_used_at` is still null."

        Identical facts as the SWIFT probe except the rail is Fedwire: the
        default record-based reading takes the +10 term because the new
        beneficiary record has never been used, even though its bank has.

        Design: Difficulty/dual_variant_calc/risk_score_swift_conservative_variant_on_new_beneficiary
        """
        room = setup_wire_room(
            business_date="2026-08-04",
            customer_overrides={"risk_rating": "LOW", "high_risk_jurisdiction": False},
            beneficiary_overrides={
                "name": "Person One", "bank_name": "BankOne", "country_code": "DE",
            },
        )
        account = room["account"]
        create_executed_wire(
            account["id"], room["beneficiary"]["id"], "2026-08-04", 50000000,
            method="Fedwire", purpose="seed wire")

        ben_two = validate_success(api.create_beneficiary(
            {
                "customer_id": room["customer"]["id"],
                "name": "Person Two",
                "bank_name": "BankOne",
                "account_number": "B-9103",
                "country_code": "DE",
            },
            OPERATOR,
        ), 201)

        wire_b = create_wire(account["id"], ben_two["id"], 50000000,
                             method="Fedwire", purpose="default reading probe")
        submitted = submit_wire(wire_b["id"], "2026-08-04")
        assert submitted["risk_score"] == 10, (
            f"default reading keys on the beneficiary record's first_used_at "
            f"(null here); got {submitted['risk_score']}")
        assert submitted["screening_status"] == "CLEAR"


class TestVelocityThreshold:
    def test_velocity_threshold_strictly_greater_than_10m(self, api):
        """PRD §3.3: "The velocity component contributes 15 points when the
        sum of `amount_cents` over this account's wires that reached
        `EXECUTED` within the trailing thirty days — the window includes
        executions whose `executed_at` falls at or after thirty days before
        the current logical instant and at or before the current instant — is
        strictly greater than ten million dollars, and nothing otherwise."

        Executed volume of exactly $10M contributes nothing; $10M + 1 cent
        switches the component on (probe score 15).

        Design: Corner/cross_cutting_layers/velocity_threshold_strictly_greater_than_10m
        """
        room = setup_wire_room(
            business_date="2026-10-09",
            customer_overrides={"risk_rating": "LOW"},
            account_overrides={"daily_outgoing_limit_cents": 3000000000},
        )
        account = room["account"]
        beneficiary = room["beneficiary"]

        # Seed exactly $10M of executed volume. The $6M wire scores 50 at
        # submit (band 40 + new-beneficiary 10) and lands in REVIEW; the
        # synthetic hit is dispositioned so the seed wire can execute.
        wire_seed1 = create_wire(account["id"], beneficiary["id"], 600000000)
        submit_wire(wire_seed1["id"], "2026-10-09", waive_callback=True)
        release_open_hits(wire_seed1["id"])
        dual_approve_wire(wire_seed1["id"])
        release_wire(wire_seed1["id"])

        # Second seed ($4M) is also above the callback threshold, so the
        # LOW-risk customer's waiver carries it into the pipeline.
        wire_seed2 = create_wire(account["id"], beneficiary["id"], 400000000)
        submit_wire(wire_seed2["id"], "2026-10-09", waive_callback=True)
        dual_approve_wire(wire_seed2["id"])
        release_wire(wire_seed2["id"])

        probe_at = create_wire(account["id"], beneficiary["id"], 500000,
                               purpose="velocity probe at threshold")
        scored_at = submit_wire(probe_at["id"], "2026-10-09")
        assert scored_at["risk_score"] == 0, (
            f"executed volume exactly 1000000000 is not strictly greater: "
            f"velocity 0; got {scored_at['risk_score']}")

        tip = create_executed_wire(
            account["id"], beneficiary["id"], "2026-10-09", 1000000)
        assert tip["status"] == "EXECUTED"

        probe_over = create_wire(account["id"], beneficiary["id"], 500000,
                                 purpose="velocity probe over threshold")
        scored_over = submit_wire(probe_over["id"], "2026-10-09")
        assert scored_over["risk_score"] == 15, (
            f"executed volume 1001000000 > 1000000000 switches the velocity "
            f"component on; got {scored_over['risk_score']}")


class TestRepairRecomputesRisk:
    def test_repair_recomputes_derived_risk_and_rescreens(self, api):
        """PRD §3.4: "Repair always re-runs screening: `screening_status` is
        reset to `NOT_SCREENED` and then re-evaluated to `CLEAR` or `REVIEW`,
        and the `risk_score` is recomputed by the same five-component rule as
        at submission."
        PRD §3.3: "a risk-driven review with no party match creates one
        synthetic hit naming the `INTERNAL_WATCH` list, with the literal text
        `RISK_THRESHOLD` as its `matched_party`, the wire's `risk_score` as
        its `match_score`, and `OPEN` status."
        PRD §3.4: "When the repair changes `amount_cents`, the account's
        `daily_reserved_cents` is re-based by the delta — the new amount minus
        the old — while `reservation_active` stays true"

        Repairing the amount from 100000 to 600000000 moves the band from 0
        to 40; the recomputed 50 reaches the review threshold, flips screening
        to REVIEW, and spawns the synthetic RISK_THRESHOLD hit.

        Design: Corner/cross_cutting_layers/repair_recomputes_derived_risk_and_rescreens
        """
        room = setup_wire_room(
            business_date="2026-10-12",
            account_overrides={"daily_outgoing_limit_cents": 1000000000},
        )
        account = room["account"]
        wire = create_wire(account["id"], room["beneficiary"]["id"], 100000)
        submitted = submit_wire(wire["id"], "2026-10-12")
        assert submitted["risk_score"] == 10, (
            f"band 0 + new-beneficiary 10 at submit, got {submitted['risk_score']}")

        resp_version = wire_version(wire["id"])
        repaired = validate_success(api.repair_wire(
            wire["id"],
            {"expected_wire_version": resp_version, "amount_cents": 600000000},
            REPAIR_SPECIALIST,
        ), 200)
        assert_wire(repaired)
        assert repaired["status"] == "REPAIR"
        assert repaired["risk_score"] == 50, (
            f"band 40 + new-beneficiary 10 after repair, got {repaired['risk_score']}")
        assert repaired["screening_status"] == "REVIEW"

        hits = list_wire_sanctions_hits(wire["id"])
        assert len(hits) == 1, f"exactly one synthetic hit expected, got {len(hits)}"
        assert_sanctions_hit(hits[0])
        assert hits[0]["matched_list"] == "INTERNAL_WATCH"
        assert hits[0]["matched_party"] == "RISK_THRESHOLD"
        assert hits[0]["match_score"] == 50
        assert hits[0]["status"] == "OPEN"

        account_after = get_account(account["id"])
        assert account_after["daily_reserved_cents"] == 600000000, (
            f"reservation re-based to the corrected amount, got "
            f"{account_after['daily_reserved_cents']}")
