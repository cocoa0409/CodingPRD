"""Contamination tagging, segregation of duties, surcharge pricing, and the
strike-suspension cascade.

Covers PRD §2.1 (segregation of duties), §3.6 (tags, disputes, surcharge,
strikes), §3.4/§3.7 (credit forfeiture and restoration).
"""
from test_helpers import (
    ApiErrorId,
    assert_contamination_tag,
    complete_pickup,
    confirm_tag,
    generate_and_get_pickups,
    get_pickup,
    get_subscriber,
    get_subscription,
    get_tag,
    list_credit_entries,
    make_driver_headers,
    make_ops_headers,
    make_subscriber_headers,
    setup_active_subscription,
    setup_completed_pickup,
    tag_pickup,
    validate_error,
    validate_success,
    waive_tag,
)


class TestSurchargeInteraction:
    def test_first_confirmation_prices_severity_and_type(self, api):
        """PRD §3.6: "The `surcharge_cents` is stamped as the severity base —
        500 cents for `LOW`, 1000 for `MEDIUM`, 1500 for `HIGH` — multiplied by
        the subscriber-type multiplier, 1.0 for `RESIDENTIAL` and 2.0 for
        `COMMERCIAL`, multiplied in turn by an escalator of one plus one half
        times the smaller of the subscription's strike count immediately
        before this confirmation and three; the product is rounded half-up to
        integer cents."

        Design: Difficulty/combinatorial_formula/contamination_surcharge_severity_type_strike_interaction
        """
        env = setup_active_subscription(subscriber_type="COMMERCIAL", bin_count=2)
        pickup = generate_and_get_pickups(
            env["route"]["id"], env["subscription"]["id"], ["2026-06-01"]
        )[0]
        tag = tag_pickup(pickup["id"], severity="LOW", category="PLASTIC")
        confirmed = confirm_tag(tag["id"])
        assert_contamination_tag(confirmed)
        # 500 x 2.0 x (1 + 0.5 x 0) at strike_count_before == 0.
        assert confirmed["surcharge_cents"] == 1000
        assert confirmed["resolved_by"] == "ops-1"

    def test_escalator_uses_strike_count_before_increment(self, api):
        """PRD §3.6: "an escalator of one plus one half times the smaller of
        the subscription's strike count immediately before this confirmation
        and three". PRD §3.6: "Then the cascade runs: the subscription's
        `strike_count` increments by one; if that count reaches three, an
        `ACTIVE` subscription transitions to `SUSPENDED`; and suspension
        cancels every `SCHEDULED` pickup of the subscription into
        `CANCELLED_SYSTEM`."

        Design: Difficulty/combinatorial_formula/contamination_surcharge_severity_type_strike_interaction
        """
        env = setup_active_subscription(subscriber_type="COMMERCIAL", bin_count=2)
        sub_id = env["subscription"]["id"]
        pickups = generate_and_get_pickups(
            env["route"]["id"], sub_id, ["2026-06-01", "2026-06-08"]
        )
        tag1 = tag_pickup(pickups[0]["id"], severity="LOW", category="PLASTIC")
        confirm_tag(tag1["id"])
        tag2 = tag_pickup(pickups[1]["id"], severity="HIGH", category="LIQUIDS")
        confirmed2 = confirm_tag(tag2["id"])
        # 1500 x 2.0 x (1 + 0.5 x 1) at strike_count_before == 1.
        assert confirmed2["surcharge_cents"] == 4500
        sub = get_subscription(sub_id)
        assert sub["strike_count"] == 2
        assert sub["service_status"] == "ACTIVE"


class TestStrikeSuspensionCascade:
    def test_third_strike_suspends_subscription(self, api):
        """PRD §3.6: "Then the cascade runs: the subscription's `strike_count`
        increments by one; if that count reaches three, an `ACTIVE`
        subscription transitions to `SUSPENDED`; and suspension cancels every
        `SCHEDULED` pickup of the subscription into `CANCELLED_SYSTEM`."

        Design: Difficulty/transitive_cascade/tag_confirm_cascade_suspends_subscription_and_cancels_pickups
        """
        env = setup_active_subscription(bin_count=1)
        sub_id = env["subscription"]["id"]
        pickups = generate_and_get_pickups(
            env["route"]["id"], sub_id,
            ["2026-06-01", "2026-06-08", "2026-06-15", "2026-06-22"],
        )
        for pickup, category in zip(
            pickups[:3], ("PLASTIC", "GLASS", "METAL")
        ):
            tag = tag_pickup(pickup["id"], severity="LOW", category=category)
            confirm_tag(tag["id"])
        sub = get_subscription(sub_id)
        assert sub["strike_count"] == 3
        assert sub["service_status"] == "SUSPENDED"

    def test_suspension_cancels_scheduled_pickups(self, api):
        """PRD §3.6: "and suspension cancels every `SCHEDULED` pickup of the
        subscription into `CANCELLED_SYSTEM`." PRD §3.6: "The `surcharge_cents`
        is stamped as the severity base — 500 cents for `LOW`, 1000 for
        `MEDIUM`, 1500 for `HIGH` — multiplied by the subscriber-type
        multiplier, 1.0 for `RESIDENTIAL` and 2.0 for `COMMERCIAL`, multiplied
        in turn by an escalator of one plus one half times the smaller of the
        subscription's strike count immediately before this confirmation and
        three; the product is rounded half-up to integer cents."

        Design: Difficulty/transitive_cascade/tag_confirm_cascade_suspends_subscription_and_cancels_pickups
        """
        env = setup_active_subscription(bin_count=1)
        sub_id = env["subscription"]["id"]
        pickups = generate_and_get_pickups(
            env["route"]["id"], sub_id,
            ["2026-06-01", "2026-06-08", "2026-06-15", "2026-06-22"],
        )
        tags = [
            tag_pickup(p["id"], severity="LOW", category=c)
            for p, c in zip(pickups[:3], ("PLASTIC", "GLASS", "METAL"))
        ]
        confirm_tag(tags[0]["id"])
        confirm_tag(tags[1]["id"])
        third = confirm_tag(tags[2]["id"])
        # The untouched future stop is cancelled by the suspension cascade.
        assert get_pickup(pickups[3]["id"])["status"] == "CANCELLED_SYSTEM"
        # 500 x 1.0 x (1 + 0.5 x 2) at strike_count_before == 2, residential.
        assert third["surcharge_cents"] == 1000


class TestSegregationOfDuties:
    def test_tagging_driver_cannot_confirm_own_tag(self, api):
        """PRD §3.6: "the resolving caller's `X-User-ID` must differ from the
        tag's `tagged_by_driver_id`, otherwise the request is rejected with
        `ERR_SEGREGATION_OF_DUTIES` — even when one person holds both the
        driver and the operations grants, they may not resolve a tag they
        filed."
        PRD §2.1: "A single person may hold both `Driver` and
        `OperationsManager` grants; even so, that person remains barred from
        confirming or waiving a tag they filed as a driver."

        Design: Corner/validations/tagging_driver_cannot_confirm_own_tag
        """
        env = setup_active_subscription(bin_count=1)
        pickup = generate_and_get_pickups(
            env["route"]["id"], env["subscription"]["id"], ["2026-06-01"]
        )[0]
        tag = tag_pickup(pickup["id"], driver_id="shared-1")
        resp = api.confirm_tag(tag["id"], make_ops_headers("shared-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_tag(tag["id"])["status"] == "TAGGED"

        confirmed = confirm_tag(tag["id"], ops_id="ops-2")
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["surcharge_cents"] == 500  # 500 x 1.0 x 1.0
        assert confirmed["resolved_by"] == "ops-2"

    def test_driver_role_cannot_waive_tag(self, api, driver2_headers):
        """PRD §3.6: "Resolution belongs exclusively to an `OperationsManager`,
        and both resolution paths are guarded by segregation of duties: the
        resolving caller's `X-User-ID` must differ from the tag's
        `tagged_by_driver_id`, otherwise the request is rejected with
        `ERR_SEGREGATION_OF_DUTIES`"
        PRD §2.1: "A request whose role is not listed on the target endpoint —
        or, for a `Subscriber` caller, one that targets a resource the caller
        does not own — is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/driver_cannot_waive_contamination_tag_forbidden
        """
        env = setup_active_subscription(bin_count=1)
        pickup = generate_and_get_pickups(
            env["route"]["id"], env["subscription"]["id"], ["2026-06-01"]
        )[0]
        tag = tag_pickup(pickup["id"], driver_id="drv-1")
        resp = api.waive_tag(tag["id"], driver2_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_tag(tag["id"])["status"] == "TAGGED"


class TestTagStateMachine:
    def test_dispute_confirmed_tag_rejected(self, api):
        """PRD §3.6: "The subscriber may dispute an open tag on their own
        account, moving it from `TAGGED` to `DISPUTED`; a tag in any other
        state is rejected with `ERR_TAG_NOT_RESOLVABLE`."

        Design: Corner/state_machines/dispute_confirmed_tag_returns_not_resolvable
        """
        env = setup_active_subscription(bin_count=1)
        pickup = generate_and_get_pickups(
            env["route"]["id"], env["subscription"]["id"], ["2026-06-01"]
        )[0]
        tag = tag_pickup(pickup["id"], severity="MEDIUM", category="GLASS")
        confirm_tag(tag["id"])
        resp = api.dispute_tag(
            tag["id"], make_subscriber_headers(env["subscriber"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_TAG_NOT_RESOLVABLE)
        after = get_tag(tag["id"])
        assert after["status"] == "CONFIRMED"
        assert after["surcharge_cents"] == 1000  # 1000 x 1.0 x 1.0

    def test_second_open_tag_rejected(self, api, driver2_headers):
        """PRD §3.6: "A pickup may carry only one open tag — open meaning
        `TAGGED` or `DISPUTED` — so a second tag on a pickup that already has
        one is rejected with `ERR_TAG_ALREADY_OPEN`."

        Design: Corner/state_machines/second_open_tag_on_completed_pickup_returns_tag_already_open
        """
        env = setup_completed_pickup(bin_count=2)
        pickup = env["pickup"]
        tag_pickup(pickup["id"], severity="LOW", category="PLASTIC", driver_id="drv-1")
        resp = api.create_contamination_tag(
            pickup["id"],
            {"severity": "HIGH", "category": "METAL"},
            driver2_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TAG_ALREADY_OPEN)


class TestWaiveBranches:
    def test_waive_returns_rejected_pickup_to_scheduled(self, api):
        """PRD §3.6: "If the tagged pickup sits in `REJECTED_CONTAMINATION`, it
        returns to `SCHEDULED` for a make-up attempt — completing it after the
        original service date is allowed."
        PRD §3.6: "No strike is recorded, `surcharge_cents` remains unset, and
        `resolved_at` and `resolved_by` are stamped as on confirmation."

        Design: Corner/state_machines/waive_returns_rejected_pickup_to_scheduled
        """
        env = setup_active_subscription(bin_count=2)
        sub_id = env["subscription"]["id"]
        pickup = generate_and_get_pickups(
            env["route"]["id"], sub_id, ["2026-06-01"]
        )[0]
        tag = tag_pickup(pickup["id"], severity="LOW", category="PLASTIC")
        assert get_pickup(pickup["id"])["status"] == "REJECTED_CONTAMINATION"

        waive_tag(tag["id"])
        assert get_pickup(pickup["id"])["status"] == "SCHEDULED"
        assert get_subscription(sub_id)["strike_count"] == 0

        completed = complete_pickup(pickup["id"], 0.5)
        assert completed["status"] == "COMPLETED"
        # 20 kg x 0.5 x 10 cents/kg x 1.2 (SUMMER) = 120.
        assert get_subscriber(env["subscriber"]["id"])["credit_balance_cents"] == 120

    def test_waive_restores_forfeited_credit_on_completed_pickup(self, api):
        """PRD §3.6: "On a `COMPLETED` pickup, the facility-discovery case, the
        pickup keeps its `COMPLETED` status but the credit it earned is
        forfeited: a `REVERSAL` entry negating that pickup's `EARNED_ESTIMATED`
        amount is posted against the subscriber's balance."
        PRD §3.6: "And if the pickup's credit was forfeited by an earlier
        `REVERSAL`, the waiver posts a `MANUAL_ADJUSTMENT` entry restoring the
        forfeited amount with the reason `TAG_WAIVED_CREDIT_RESTORE`."

        Design: Corner/state_machines/waive_restores_forfeited_credit_on_completed_pickup
        """
        env = setup_completed_pickup(bin_count=2)
        pickup = env["pickup"]
        sub_id = env["subscriber"]["id"]
        assert get_subscriber(sub_id)["credit_balance_cents"] == 120

        tag = tag_pickup(pickup["id"], severity="LOW", category="PLASTIC")
        assert get_pickup(pickup["id"])["status"] == "COMPLETED"
        assert get_subscriber(sub_id)["credit_balance_cents"] == 0

        waive_tag(tag["id"])
        entries = list_credit_entries(pickup_id=pickup["id"])
        by_type = {}
        for e in entries:
            by_type.setdefault(e["entry_type"], []).append(e)
        assert any(
            e["entry_type"] == "MANUAL_ADJUSTMENT"
            and e["amount_cents"] == 120
            and e.get("reason") == "TAG_WAIVED_CREDIT_RESTORE"
            for e in entries
        ), f"expected restoring MANUAL_ADJUSTMENT, got {entries}"
        assert get_subscriber(sub_id)["credit_balance_cents"] == 120
        assert get_subscription(env["subscription"]["id"])["strike_count"] == 0
