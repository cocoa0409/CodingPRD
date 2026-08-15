"""Quote lifecycle: issue/accept/reject/revise cycle, OCC, caps, fiscal gate."""
from datetime import datetime, timezone, timedelta

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_quote, api_client,
    create_customer, create_part, create_aog_request, create_quote,
    make_quote_line, issue_quote, accept_quote, get_order_for_quote,
    set_clock, setup_issued_quote, make_customer_headers, TEST_USERS,
)

AGENT = TEST_USERS["aog_desk_agent_headers"]


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestQuoteRevisionCycleReissue:
    def _drive_cycle(self):
        ctx = setup_issued_quote(
            customer_name="CycleAir",
            part_overrides={"part_number": "PN-C", "list_price_cents": 50_000},
            aog_overrides={"aircraft_tail": "N500CY", "airport_code": "ATL"},
            line_overrides={"unit_price_cents": 50_000},
        )
        rejected = validate_success(
            api_client_reject(ctx["quote"]["id"], ctx["customer"]["id"])
        )
        return ctx, rejected

    def test_cycle_statuses_and_revision_count(self, api):
        """PRD §3.4: "a desk agent may revise a `REJECTED` or `EXPIRED` quote
        back to `DRAFT`, supplying `expected_quote_version` per §2.9" and "The
        revision increments `revision_count` — which starts at zero on a
        freshly drafted quote — by 1, clears `issued_at`, `expires_at`, and
        `tier_at_issue`, recomputes all price fields, and increments `version`
        — the cycle `DRAFT` → `ISSUED` → `REJECTED` → `DRAFT` may repeat as
        often as negotiation demands."

        Design: Difficulty/non_linear_state_machine/quote_revision_cycle_reissue
        """
        ctx, rejected = self._drive_cycle()
        assert rejected["status"] == "REJECTED"
        quote_id = ctx["quote"]["id"]

        # 12h: a revised window distinct from the original 24h, yet inside the
        # STANDARD tier cap of 24h (PRD §3.4) so the re-issue below succeeds.
        revised = validate_success(api.revise_quote(
            quote_id, {"expected_quote_version": rejected["version"],
                       "validity_hours": 12}, AGENT,
        ))
        assert revised["status"] == "DRAFT"
        assert revised["revision_count"] == 1
        assert revised["issued_at"] is None
        assert revised["expires_at"] is None
        assert revised["tier_at_issue"] is None

        reissued = validate_success(api.issue_quote(quote_id, AGENT))
        assert reissued["status"] == "ISSUED"

    def test_reissue_rearms_validity_clock(self, api):
        """PRD §3.4: "A successful issue moves the quote `DRAFT` → `ISSUED`,
        snapshots `tier_at_issue` from the customer, stamps `issued_at` with
        the clock, sets `expires_at` exactly `validity_hours` hours later".

        With the logical clock at 2026-05-01T00:00:00Z and a revised validity
        of 12 hours (the original 24h was revised down to 12h; the revised
        value must govern, and it fits the STANDARD tier cap of 24h per
        §3.4), the re-issued quote must expire at 2026-05-01T12:00:00Z.

        Design: Difficulty/non_linear_state_machine/quote_revision_cycle_reissue
        """
        ctx, rejected = self._drive_cycle()
        quote_id = ctx["quote"]["id"]
        validate_success(api.revise_quote(
            quote_id, {"expected_quote_version": rejected["version"],
                       "validity_hours": 12}, AGENT,
        ))
        reissued = validate_success(api.issue_quote(quote_id, AGENT))
        issued_at = _parse(reissued["issued_at"])
        expires_at = _parse(reissued["expires_at"])
        assert expires_at - issued_at == timedelta(hours=12)
        assert expires_at == datetime(2026, 5, 1, 12, tzinfo=timezone.utc)
        # version: 1 create, 2 issue, 3 reject, 4 revise, 5 re-issue
        assert reissued["version"] == 5


def api_client_reject(quote_id, customer_id):
    """Local helper: reject as the owning customer contact."""
    return api_client.reject_quote(quote_id, make_customer_headers(customer_id))


def test_quote_terminal_lockdown_after_accept(api):
    """PRD §3.4: "a SalesOrder is created referencing the quote (one order per
    quote)" and per §2.11 gate 4 "The target entity's status must permit the
    transition ... Failures surface `ERR_INVALID_STATE`" — an ACCEPTED quote
    admits neither a second accept nor a reject.

    Design: Corner/state_machines/quote_terminal_lockdown_after_accept
    """
    ctx = setup_issued_quote(customer_name="TermAir",
                             part_overrides={"part_number": "PN-TM"},
                             aog_overrides={"aircraft_tail": "N9TM"})
    accepted = accept_quote(ctx["quote"]["id"], ctx["customer"]["id"],
                            ctx["quote"]["version"])
    assert accepted["status"] == "ACCEPTED"

    second = api.accept_quote(
        ctx["quote"]["id"],
        {"expected_quote_version": accepted["version"]},
        make_customer_headers(ctx["customer"]["id"]),
    )
    validate_error(second, "ERR_INVALID_STATE", expected_status=409)

    reject = api.reject_quote(
        ctx["quote"]["id"], make_customer_headers(ctx["customer"]["id"])
    )
    validate_error(reject, "ERR_INVALID_STATE", expected_status=409)

    data, meta = validate_paginated(
        api.list_orders(AGENT, params={"quote_id": ctx["quote"]["id"]})
    )
    assert meta["total_count"] == 1


def test_quote_double_issue_invalid(api):
    """PRD §3.4: "A successful issue moves the quote `DRAFT` → `ISSUED`" — no
    `ISSUED` → `ISSUED` transition exists, and §2.11 gate 4 surfaces
    `ERR_INVALID_STATE` when "The target entity's status must permit the
    transition" fails.

    Design: Corner/state_machines/quote_double_issue_invalid
    """
    ctx = setup_issued_quote(customer_name="DblAir",
                             part_overrides={"part_number": "PN-DI"},
                             aog_overrides={"aircraft_tail": "N8DI"})
    issued_at = ctx["quote"]["issued_at"]

    res = api.issue_quote(ctx["quote"]["id"], AGENT)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    after = validate_success(api.get_quote(ctx["quote"]["id"], AGENT))
    assert after["status"] == "ISSUED"
    assert after["issued_at"] == issued_at


def test_duplicate_active_quote_rejected(api):
    """PRD §3.4: "A request may carry at most one non-terminal quote: drafting
    while a `DRAFT` or `ISSUED` quote already exists for the request is
    refused with `ERR_DUPLICATE_ACTIVE_QUOTE`." A draft the desk abandons
    moves `DRAFT` → `CANCELLED`, after which a fresh draft is admissible.

    Design: Corner/validations/duplicate_active_quote_rejected
    """
    customer = create_customer(name="DupQAir")
    part = create_part(part_number="PN-DQ")
    aog = create_aog_request(customer["id"], part["id"], aircraft_tail="N9DQ")
    line = make_quote_line(part["id"])
    first = create_quote(aog["id"], customer["id"], [line])

    dup = api.create_quote(
        {"aog_request_id": aog["id"], "customer_id": customer["id"],
         "lines": [line], "validity_hours": 24, "freight_mode": "STANDARD",
         "distance_km": 800, "chargeable_weight_kg": 4,
         "destination_country": "US"},
        AGENT,
    )
    validate_error(dup, "ERR_DUPLICATE_ACTIVE_QUOTE", expected_status=409)

    validate_success(api.cancel_quote(first["id"], AGENT))
    fresh = validate_success(api.create_quote(
        {"aog_request_id": aog["id"], "customer_id": customer["id"],
         "lines": [line], "validity_hours": 24, "freight_mode": "STANDARD",
         "distance_km": 800, "chargeable_weight_kg": 4,
         "destination_country": "US"},
        AGENT,
    ), 201)
    assert_quote(fresh)


def test_validity_cap_enforced_per_tier(api):
    """PRD §3.4: "the `validity_hours` to fit the cap of the tier in effect at
    issue time — 24 hours for `STANDARD`, 48 for `PRIORITY`, 72 for `PLATINUM`
    — with an over-cap window refused as `ERR_VALIDITY_EXCEEDS_TIER_CAP`."

    Design: Corner/validations/validity_cap_enforced_per_tier
    """
    customer = create_customer(name="CapAir")
    assert customer["priority_tier"] == "STANDARD"
    part = create_part(part_number="PN-VC")
    aog = create_aog_request(customer["id"], part["id"], aircraft_tail="N9VC")
    quote = create_quote(aog["id"], customer["id"],
                         [make_quote_line(part["id"])], validity_hours=48)

    res = api.issue_quote(quote["id"], AGENT)
    validate_error(res, "ERR_VALIDITY_EXCEEDS_TIER_CAP", expected_status=422)

    after = validate_success(api.get_quote(quote["id"], AGENT))
    assert after["status"] == "DRAFT"


class TestExpiredQuoteBeatsCreditLimit:
    def _setup(self):
        ctx = setup_issued_quote(
            customer_name="LimitCo", credit_limit_cents=1_000,
            part_overrides={"part_number": "PN-EXP", "list_price_cents": 50_000},
            aog_overrides={"aircraft_tail": "N900EX", "airport_code": "PHX"},
            line_overrides={"unit_price_cents": 50_000},
        )
        set_clock("2026-05-02T00:00:01Z")
        return ctx

    def test_expired_quote_error_precedes_credit_limit(self, api):
        """PRD §3.4: "an `ISSUED` quote whose `expires_at` has passed is
        treated as `EXPIRED` — lazily, even if no sweep has run — and refuses
        with `ERR_QUOTE_EXPIRED` (acceptance exactly at the expiry instant
        still succeeds)"; the fiscal gate comes later in the same list:
        "finally the fiscal gate — `ERR_CREDIT_LIMIT_EXCEEDED` when the
        customer's outstanding balance plus the quote's `total_cents` plus the
        core deposits over its `EXCHANGE` lines is strictly greater than
        `credit_limit_cents`". A doubly-violating accept surfaces
        ERR_QUOTE_EXPIRED.

        Design: Difficulty/priority_pair_validation_conflict/expired_quote_beats_credit_limit
        """
        ctx = self._setup()
        res = api.accept_quote(
            ctx["quote"]["id"],
            {"expected_quote_version": ctx["quote"]["version"]},
            make_customer_headers(ctx["customer"]["id"]),
        )
        validate_error(res, "ERR_QUOTE_EXPIRED", expected_status=409)

    def test_lazy_expiry_does_not_mutate_quote_row(self, api):
        """PRD §3.4: "an `ISSUED` quote whose `expires_at` has passed is
        treated as `EXPIRED` — lazily, even if no sweep has run"; PRD §3.9
        assigns the actual transition to the sweep: "every `ISSUED` quote
        whose `expires_at` has passed moves to `EXPIRED`".

        Design: Difficulty/priority_pair_validation_conflict/expired_quote_beats_credit_limit
        """
        ctx = self._setup()
        res = api.accept_quote(
            ctx["quote"]["id"],
            {"expected_quote_version": ctx["quote"]["version"]},
            make_customer_headers(ctx["customer"]["id"]),
        )
        validate_error(res, "ERR_QUOTE_EXPIRED", expected_status=409)

        stored = validate_success(api.get_quote(ctx["quote"]["id"], AGENT))
        assert stored["status"] == "ISSUED", (
            "lazy expiry treats the quote as EXPIRED without mutating it; "
            "only a sweep moves the row"
        )


class TestCreditLimitEqualityPasses:
    """Quote total engineered to 110770 (subtotal 100000 + handling 4500 +
    STANDARD tier fee 6270), no EXCHANGE lines so no deposit exposure."""

    def _accepted_attempt(self, api, customer_name, credit_limit_cents):
        ctx = setup_issued_quote(
            customer_name=customer_name, credit_limit_cents=credit_limit_cents,
            part_overrides={"part_number": "PN-EQ", "list_price_cents": 100_000},
            aog_overrides={"aircraft_tail": "N110EQ", "airport_code": "STL"},
            line_overrides={"unit_price_cents": 100_000},
        )
        assert ctx["quote"]["total_cents"] == 110_770
        return api.accept_quote(
            ctx["quote"]["id"],
            {"expected_quote_version": ctx["quote"]["version"]},
            make_customer_headers(ctx["customer"]["id"]),
        )

    def test_exposure_exactly_at_limit_passes(self, api):
        """PRD §3.4: "finally the fiscal gate — `ERR_CREDIT_LIMIT_EXCEEDED`
        when the customer's outstanding balance plus the quote's `total_cents`
        plus the core deposits over its `EXCHANGE` lines is strictly greater
        than `credit_limit_cents`. Equality at the credit limit passes."

        Design: Difficulty/boundary_precision_check/credit_limit_equality_passes
        """
        res = self._accepted_attempt(api, "EqCo", 110_770)
        accepted = validate_success(res, 200)
        assert accepted["status"] == "ACCEPTED"

    def test_one_cent_over_limit_rejected(self, api):
        """PRD §3.4: "`ERR_CREDIT_LIMIT_EXCEEDED` when the customer's
        outstanding balance plus the quote's `total_cents` plus the core
        deposits over its `EXCHANGE` lines is strictly greater than
        `credit_limit_cents`." 110770 > 110769, so the accept must fail.

        Design: Difficulty/boundary_precision_check/credit_limit_equality_passes
        """
        res = self._accepted_attempt(api, "UnderCo", 110_769)
        validate_error(res, "ERR_CREDIT_LIMIT_EXCEEDED", expected_status=402)


def test_occ_quote_revise_stale_version(api):
    """PRD §2.9: "Revising a quote likewise requires `expected_quote_version`.
    A revise whose expected version trails the quote's current `version` —
    another writer may already have revised it back to `DRAFT` and even
    re-issued it — is rejected with `ERR_STALE_QUOTE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_quote_revise_stale_version
    """
    ctx = setup_issued_quote(customer_name="OccAir",
                             part_overrides={"part_number": "PN-OC2"},
                             aog_overrides={"aircraft_tail": "N9OC"})
    quote_id = ctx["quote"]["id"]
    cust_headers = make_customer_headers(ctx["customer"]["id"])

    # v2 ISSUED -> v3 REJECTED -> v4 DRAFT (revise) -> v5 ISSUED -> v6 REJECTED
    rejected1 = validate_success(api.reject_quote(quote_id, cust_headers))
    stale_version = rejected1["version"]  # 3
    validate_success(api.revise_quote(
        quote_id, {"expected_quote_version": stale_version}, AGENT,
    ))
    validate_success(api.issue_quote(quote_id, AGENT))
    rejected2 = validate_success(api.reject_quote(quote_id, cust_headers))
    fresh_version = rejected2["version"]  # 6
    assert fresh_version == 6

    stale = api.revise_quote(
        quote_id, {"expected_quote_version": stale_version}, AGENT,
    )
    validate_error(stale, "ERR_STALE_QUOTE_VERSION", expected_status=412)

    fresh = validate_success(api.revise_quote(
        quote_id, {"expected_quote_version": fresh_version}, AGENT,
    ))
    assert fresh["status"] == "DRAFT"
    assert fresh["revision_count"] == 2


def test_occ_quote_accept_stale_version(api):
    """PRD §2.9: "Accepting a quote requires the request body to carry
    `expected_quote_version`, holding the `version` of the quote as the
    customer last observed it. If the quote's current `version` no longer
    matches — for example because a revise cycle re-priced the quote after
    the customer read it — the acceptance is rejected with
    `ERR_STALE_QUOTE_VERSION` (HTTP 412), so a customer is never bound to
    terms they never saw."

    Design: Corner/cross_cutting_layers/occ_quote_accept_stale_version
    """
    ctx = setup_issued_quote(customer_name="OccAcc",
                             part_overrides={"part_number": "PN-OA"},
                             aog_overrides={"aircraft_tail": "N9OA"})
    quote_id = ctx["quote"]["id"]
    cust_headers = make_customer_headers(ctx["customer"]["id"])
    stale_version = ctx["quote"]["version"]  # 2 (as the customer observed it)

    rejected = validate_success(api.reject_quote(quote_id, cust_headers))
    validate_success(api.revise_quote(
        quote_id, {"expected_quote_version": rejected["version"],
                   "validity_hours": 24}, AGENT,
    ))
    reissued = validate_success(api.issue_quote(quote_id, AGENT))
    fresh_version = reissued["version"]  # 5
    assert fresh_version == 5

    stale = api.accept_quote(
        quote_id, {"expected_quote_version": stale_version}, cust_headers,
    )
    validate_error(stale, "ERR_STALE_QUOTE_VERSION", expected_status=412)

    fresh = validate_success(api.accept_quote(
        quote_id, {"expected_quote_version": fresh_version}, cust_headers,
    ))
    assert fresh["status"] == "ACCEPTED"
    order = get_order_for_quote(quote_id)
    assert order["quote_id"] == quote_id


def test_customer_contact_cannot_accept_others_quote(api):
    """PRD §3.4: "Acceptance belongs to the customer contact, who must own the
    quote (`ERR_FORBIDDEN` otherwise)"; PRD §2.1: "ownership checks on any
    resource that references a `Customer` compare the resource's `customer_id`
    field to `X-User-ID`."

    Design: Corner/rbac/customer_contact_cannot_accept_others_quote
    """
    owner = create_customer(name="OwnerAir")
    other = create_customer(name="OtherAir")
    part = create_part(part_number="PN-OO")
    aog = create_aog_request(owner["id"], part["id"], aircraft_tail="N9OO")
    quote = create_quote(aog["id"], owner["id"], [make_quote_line(part["id"])])
    issued = issue_quote(quote["id"])

    res = api.accept_quote(
        quote["id"], {"expected_quote_version": issued["version"]},
        make_customer_headers(other["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)

    after = validate_success(api.get_quote(quote["id"], AGENT))
    assert after["status"] == "ISSUED"
