"""Requests that violate two rules at once: the higher rung of the validation
ladder must be the one reported."""
from test_helpers import (
    ApiErrorId,
    api_client,
    list_order_lines,
    list_return_authorizations,
    make_account,
    make_branch,
    make_part,
    make_pricing_tier,
    make_servicer_headers,
    open_will_call_order,
    order_line_payload,
    read_account,
    read_line,
    read_order,
    read_part,
    return_authorization_payload,
    set_clock,
    setup_fulfilled_line,
    setup_order_at_credit_limit,
    validate_error,
)

GE_BOARD = {
    "part_number": "GE-BOARD",
    "oem_code": "GE",
    "description": "Main control board",
    "category": "ELECTRICAL",
    "list_price_cents": 128000,
    "weight_grams": 400,
}


# ---------------------------------------------------------------------------
# Shared setups
# ---------------------------------------------------------------------------

def _credit_approved_order_sitting_exactly_on_the_limit():
    """Three pumps quoted at 31,197 cents against a 31,197-cent credit limit,
    already credit-approved, so a further line breaks two rules at once."""
    return setup_order_at_credit_limit(
        unit_quantity=3, credit_limit_cents=31197,
        account_kwargs={
            "business_name": "Exact Limit Repairs",
            "core_liability_limit_cents": 5000000,
        },
    )


def _unauthorized_oem_and_a_thousand_cent_limit():
    """A WHIRLPOOL-only account with a 1,000-cent limit and an empty order, plus a
    GE electrical board that breaches authorization, certification and limit."""
    tier = make_pricing_tier(
        tier_code="GOLD", name="Gold Contract",
        electrical=0.15, mechanical=0.20, cosmetic=0.25, sealed_system=0.10,
        min_annual_volume_cents=5000000,
    )
    branch = make_branch(
        code="STL", name="St Louis DC", region_code="MW",
        will_call_enabled=True, cutoff_hour_utc=20, overnight_surcharge_cents=300,
    )
    board = make_part(**GE_BOARD)
    account = make_account(
        tier, business_name="Whirlpool Only Service",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=1000, core_liability_limit_cents=5000000,
    )
    order = open_will_call_order(account, branch)
    return {
        "branch": branch, "board": board, "account": account, "order": order,
    }


def _shipped_electrical_line_out_of_window():
    """A GE board shipped on the default clock, observed forty days later so the
    thirty-day return window has also lapsed."""
    world = setup_fulfilled_line(
        quantity=1,
        on_hand_units=5,
        part_kwargs=dict(GE_BOARD),
        account_kwargs={
            "business_name": "GE Board Specialists",
            "oem_authorizations": ["GE"],
            "core_liability_limit_cents": 5000000,
        },
        cert_kwargs={
            "technician_name": "Lee Park",
            "oem_code": "GE",
            "cert_level": "ADVANCED",
        },
        tracking_ref="WILLCALL-GE",
    )
    set_clock("2026-09-10T00:00:00Z")
    return world


# ---------------------------------------------------------------------------
# Order state (rung 10) outranks the credit limit (rung 48)
# ---------------------------------------------------------------------------

class TestOrderStateOutranksTheCreditLimit:

    def test_line_add_on_an_approved_order_reports_the_state_error_not_the_limit(self):
        """PRD §2.7: "Validation is strictly ordered. Rules are evaluated in
        ascending priority, the **first** violated rule decides the response, and
        no later rule is evaluated."
        PRD §2.7: "10. `ERR_ORDER_NOT_DRAFT` (409) — the order's
        `fulfillment_status` is `DRAFT` and its `settlement_status` is
        `PENDING_CREDIT`. Guards two operations: `POST /part-orders/{id}/lines`
        and `POST /part-orders/{id}/credit-decision`."
        PRD §2.7: "48. `ERR_CREDIT_LIMIT_EXCEEDED` (402) — the account's credit
        exposure, recomputed with the pending change applied, does not exceed
        `credit_limit_cents`. Guards two operations:
        `POST /part-orders/{id}/lines` and
        `POST /part-orders/{id}/credit-decision`."

        Design: Difficulty/priority_pair_validation_conflict/order_not_draft_state_outranks_credit_limit_fiscal_on_line_add
        """
        world = _credit_approved_order_sitting_exactly_on_the_limit()
        order = read_order(world["order"]["id"])

        response = api_client.add_order_line(
            order["id"],
            order_line_payload(world["part"]["id"], 1, order["version"]),
            make_servicer_headers(world["account"]["id"]),
        )
        body = validate_error(response, ApiErrorId.ERR_ORDER_NOT_DRAFT)
        assert body["error_id"] != ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value, (
            "the fiscal rule sits below the state rule and must not be reported"
        )

    def test_the_refused_line_add_leaves_the_order_and_the_exposure_untouched(self):
        """PRD §2.9: "The system never defers a cascade to a later request, never
        leaves a derived aggregate stale, and never partially applies a cascade: if
        the triggering write is rejected, nothing downstream of it is written
        either."
        PRD §3.5: "Approval requires the owning account to be `ACTIVE` and
        requires the account's credit exposure — which already includes this
        order's `total_cents` — to be no greater than its `credit_limit_cents`; an
        exposure exactly equal to the limit passes, one cent more fails with
        `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/order_not_draft_state_outranks_credit_limit_fiscal_on_line_add
        """
        world = _credit_approved_order_sitting_exactly_on_the_limit()
        order = read_order(world["order"]["id"])

        response = api_client.add_order_line(
            order["id"],
            order_line_payload(world["part"]["id"], 1, order["version"]),
            make_servicer_headers(world["account"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_ORDER_NOT_DRAFT)

        after = read_order(order["id"])
        assert after["subtotal_cents"] == 31197, (
            f"Expected the subtotal to stay at 31197, got {after['subtotal_cents']}"
        )
        assert after["settlement_status"] == "CREDIT_APPROVED"

        account = read_account(world["account"]["id"])
        assert account["credit_used_cents"] == 31197, (
            f"Expected the exposure to stay at 31197, got "
            f"{account['credit_used_cents']}"
        )

        lines = list_order_lines(part_order_id=order["id"])
        assert len(lines) == 1, (
            f"the refused add must not persist a second line, got {len(lines)}"
        )


# ---------------------------------------------------------------------------
# OEM authorization (rung 24) outranks certification (25) and the limit (48)
# ---------------------------------------------------------------------------

class TestOemAuthorizationOutranksTheCreditLimit:

    def test_line_add_for_an_unauthorized_oem_reports_the_authorization_error(self):
        """PRD §3.4: "It then faces three gates in sequence: the resolved part's
        `oem_code` must appear in the account's `oem_authorizations`, or the add is
        rejected with `ERR_OEM_AUTHORIZATION_MISSING`; the account must hold an
        effective certification meeting the resolved part's `cert_level_required`,
        or the add is rejected with `ERR_TECHNICIAN_CERT_REQUIRED`; and the
        account's credit exposure recomputed **with this line included** must not
        exceed its `credit_limit_cents`, or the add is rejected with
        `ERR_CREDIT_LIMIT_EXCEEDED`."
        PRD §2.7: "24. `ERR_OEM_AUTHORIZATION_MISSING` (422) — the resolved part's
        `oem_code` appears in the account's `oem_authorizations`. Guards three
        operations: `POST /part-orders/{id}/lines`, `POST /warranty-claims`, and
        `POST /substitute-requests/{id}/decision`."

        Design: Difficulty/priority_pair_validation_conflict/oem_authorization_safety_outranks_credit_limit_fiscal_on_line_add
        """
        world = _unauthorized_oem_and_a_thousand_cent_limit()

        response = api_client.add_order_line(
            world["order"]["id"],
            order_line_payload(world["board"]["id"], 1, world["order"]["version"]),
            make_servicer_headers(world["account"]["id"]),
        )
        body = validate_error(response, ApiErrorId.ERR_OEM_AUTHORIZATION_MISSING)
        assert body["error_id"] != ApiErrorId.ERR_TECHNICIAN_CERT_REQUIRED.value, (
            "the certification gate is the second of the three, not the first"
        )
        assert body["error_id"] != ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value, (
            "the fiscal gate is the last of the three"
        )

    def test_the_refused_line_add_leaves_the_empty_order_at_version_one(self):
        """PRD §2.4: "Almost every resource additionally carries `updated_at`, an
        ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an
        integer that starts at 1 on creation and increments by exactly 1 on every
        mutation of that row — including mutations the server performs on its own
        initiative as part of a cascade, and including mutations that only change
        computed money fields."
        PRD §3.4: "A new order starts with `pricing_basis` equal to `ORDER_DATE`
        and with `subtotal_cents`, `core_deposit_total_cents`, `freight_cents`, and
        `total_cents` all at zero; `invoiced_total_cents`, `fulfilled_at`,
        `tracking_ref`, and `credit_decided_by_user_id` all start null."

        Design: Difficulty/priority_pair_validation_conflict/oem_authorization_safety_outranks_credit_limit_fiscal_on_line_add
        """
        world = _unauthorized_oem_and_a_thousand_cent_limit()
        opening_version = world["order"]["version"]

        response = api_client.add_order_line(
            world["order"]["id"],
            order_line_payload(world["board"]["id"], 1, opening_version),
            make_servicer_headers(world["account"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_OEM_AUTHORIZATION_MISSING)

        order = read_order(world["order"]["id"])
        assert order["subtotal_cents"] == 0
        assert order["version"] == opening_version, (
            f"a refused add is not a mutation, so the version stays at "
            f"{opening_version}, got {order['version']}"
        )

        account = read_account(world["account"]["id"])
        assert account["credit_used_cents"] == 0


# ---------------------------------------------------------------------------
# Returnability (rung 32) outranks the return window (rung 34)
# ---------------------------------------------------------------------------

class TestReturnabilityOutranksTheReturnWindow:

    def test_an_out_of_window_electrical_return_reports_the_returnability_error(self):
        """PRD §2.7: "And the electrical-part prohibition (rule 32) precedes the
        return-window check (rule 34), so an out-of-window electrical return still
        reports `ERR_PART_NON_RETURNABLE`."
        PRD §3.9: "First, returnability: the resolved part's `is_returnable` must
        be true, so an `ELECTRICAL` part or a part whose `lifecycle_status` is
        `NLA` is refused with `ERR_PART_NON_RETURNABLE`, and no `reason_code` — not
        even `DEFECTIVE_ON_ARRIVAL` — lifts that prohibition."

        Design: Difficulty/priority_pair_validation_conflict/electrical_non_returnable_constraint_outranks_expired_window_temporal
        """
        world = _shipped_electrical_line_out_of_window()

        response = api_client.create_return_authorization(
            return_authorization_payload(
                world["account"]["id"], world["line"]["id"], 1, "WRONG_PART",
                world["branch"]["id"],
            ),
            make_servicer_headers(world["account"]["id"]),
        )
        body = validate_error(response, ApiErrorId.ERR_PART_NON_RETURNABLE)
        assert body["error_id"] != ApiErrorId.ERR_RETURN_WINDOW_EXPIRED.value, (
            "the temporal rule sits below the returnability rule"
        )

        assert read_part(world["part"]["id"])["is_returnable"] is False, (
            "an ELECTRICAL part is never returnable"
        )

    def test_the_refused_request_persists_no_authorization_against_the_line(self):
        """PRD §3.9: "A day count strictly greater than the window is refused with
        `ERR_RETURN_WINDOW_EXPIRED`; a count exactly equal to the window is still
        inside it and is accepted."
        PRD §2.9: "The system never defers a cascade to a later request, never
        leaves a derived aggregate stale, and never partially applies a cascade: if
        the triggering write is rejected, nothing downstream of it is written
        either."

        Design: Difficulty/priority_pair_validation_conflict/electrical_non_returnable_constraint_outranks_expired_window_temporal
        """
        world = _shipped_electrical_line_out_of_window()

        response = api_client.create_return_authorization(
            return_authorization_payload(
                world["account"]["id"], world["line"]["id"], 1, "WRONG_PART",
                world["branch"]["id"],
            ),
            make_servicer_headers(world["account"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_PART_NON_RETURNABLE)

        line = read_line(world["line"]["id"])
        assert line["line_status"] == "SHIPPED"
        assert line["returned_units"] == 0

        rows = list_return_authorizations(order_line_id=world["line"]["id"])
        assert rows == [], (
            f"no authorization may be persisted by the refused request, got "
            f"{len(rows)} row(s)"
        )
