"""Admission tests on the after-sales side: the return gates that must all pass
before an authorization exists, the quantity ceiling across two authorizations, the
core-deposit ceiling on hand-over, the ninety-day warranty edge, and the
certification requirement read off the resolved part."""
import pytest

from test_helpers import (
    CREDIT_MANAGER,
    WARRANTY_ADMIN,
    ApiErrorId,
    add_line,
    allocate_order,
    api_client,
    approve_credit,
    assert_inventory_units,
    decide_return,
    fulfill_order,
    inventory_for,
    list_order_lines,
    list_return_authorizations,
    make_account,
    make_branch,
    make_branch_counter_rep_headers,
    make_certification,
    make_claim,
    make_inventory,
    make_part,
    make_pricing_tier,
    make_servicer_headers,
    open_will_call_order,
    order_line_payload,
    read_account,
    read_claim,
    read_line,
    read_order,
    read_return_authorization,
    receive_return,
    record_supersession,
    request_return,
    return_authorization_payload,
    return_decision_payload,
    set_clock,
    setup_fulfilled_line,
    setup_will_call_order,
    submit_claim,
    validate_error,
    validate_success,
)

STL_BRANCH = {
    "code": "STL",
    "name": "St Louis DC",
    "region_code": "MW",
    "will_call_enabled": True,
    "cutoff_hour_utc": 20,
    "overnight_surcharge_cents": 300,
}
COMPRESSOR = {
    "part_number": "W10-COMP",
    "oem_code": "WHIRLPOOL",
    "description": "Sealed system compressor",
    "category": "SEALED_SYSTEM",
    "list_price_cents": 320000,
    "weight_grams": 12000,
    "core_required": True,
    "core_deposit_cents": 8500,
}


# ---------------------------------------------------------------------------
# Shared setups
# ---------------------------------------------------------------------------

def _three_shipped_units_observed_on_day_five():
    """Three mechanical units shipped on 2026-08-01 and looked at on 2026-08-06."""
    world = setup_fulfilled_line(
        quantity=3, branch_kwargs=dict(STL_BRANCH), on_hand_units=10,
        account_kwargs={"core_liability_limit_cents": 5000000},
        purchase_order_ref="PO-3009", tracking_ref="WILLCALL-3009",
    )
    set_clock("2026-08-06T00:00:00Z")
    return world


def _two_shipped_units_with_one_already_returned():
    """Two shipped units, one of which has already come back and been credited."""
    world = setup_fulfilled_line(
        quantity=2, branch_kwargs=dict(STL_BRANCH), on_hand_units=10,
        account_kwargs={"core_liability_limit_cents": 5000000},
        purchase_order_ref="PO-3010", tracking_ref="WILLCALL-3010",
    )
    first = request_return(
        world["account"], world["line"], 1, "NO_LONGER_NEEDED", world["branch"]
    )
    decide_return(first["id"], "APPROVE", waive_restocking_fee=False)
    receive_return(first["id"], world["branch"])
    world["first_authorization"] = first
    return world


def _allocated_compressors_against_a_tiny_core_ceiling():
    """Two core-required compressors reserved for an account whose core ceiling is
    only 10,000 cents."""
    return setup_will_call_order(
        stage="allocated", quantity=2,
        branch_kwargs=dict(STL_BRANCH),
        part_kwargs=dict(COMPRESSOR),
        on_hand_units=5,
        account_kwargs={
            "business_name": "Small Ceiling Service",
            "core_liability_limit_cents": 10000,
        },
        cert_kwargs={
            "technician_name": "Sam Ortiz",
            "oem_code": "WHIRLPOOL",
            "cert_level": "SEALED_SYSTEM",
        },
        purchase_order_ref="PO-3011",
    )


def _two_shipped_lines_with_a_claim_on_each():
    """One order fulfilled on 2026-08-01 carrying a three-unit line and a
    single-unit line, with a draft claim standing against each."""
    tier = make_pricing_tier(
        tier_code="GOLD", name="Gold Contract",
        electrical=0.15, mechanical=0.20, cosmetic=0.25, sealed_system=0.10,
        min_annual_volume_cents=5000000,
    )
    branch = make_branch(**STL_BRANCH)
    pump = make_part(
        part_number="W10-PUMP", oem_code="WHIRLPOOL",
        description="Drain pump assembly", category="MECHANICAL",
        list_price_cents=12999, weight_grams=5200,
    )
    account = make_account(
        tier, business_name="Ace Appliance Repair",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    make_certification(
        account, technician_name="Dana Ruiz", oem_code="WHIRLPOOL",
        cert_level="BASIC", training_completed_at="2026-01-01T00:00:00Z",
        expires_at="2027-01-01T00:00:00Z",
    )
    make_inventory(branch, pump, on_hand_units=10, reorder_point=2)

    order = open_will_call_order(account, branch, purchase_order_ref="PO-3012")
    first_line = add_line(order, pump, quantity=3)
    second_line = add_line(order, pump, quantity=1)
    approve_credit(order)
    allocate_order(order, branch)
    fulfill_order(order, branch, tracking_ref="WILLCALL-3012")
    return {
        "branch": branch, "part": pump, "account": account, "order": order,
        "first_line": first_line, "second_line": second_line,
        "first_claim": make_claim(
            account, first_line, defect_code="PUMP-SEIZED",
            appliance_model_number="WTW5000DW1",
        ),
        "second_claim": make_claim(
            account, second_line, defect_code="PUMP-LEAK",
            appliance_model_number="WTW5000DW1",
        ),
    }


def _mechanical_part_superseded_by_an_electrical_one():
    """A MECHANICAL part whose supersession target is ELECTRICAL, ordered by an
    account holding no certification at all."""
    tier = make_pricing_tier(
        tier_code="GOLD", name="Gold Contract",
        electrical=0.15, mechanical=0.20, cosmetic=0.25, sealed_system=0.10,
        min_annual_volume_cents=5000000,
    )
    branch = make_branch(**STL_BRANCH)
    replacement = make_part(
        part_number="W10-BOARD-NEW", oem_code="WHIRLPOOL",
        description="Electronic pump control", category="ELECTRICAL",
        list_price_cents=13000, weight_grams=400,
    )
    requested = make_part(
        part_number="W10-PUMP", oem_code="WHIRLPOOL",
        description="Drain pump assembly", category="MECHANICAL",
        list_price_cents=12999, weight_grams=5200,
    )
    record_supersession(requested, replacement)
    account = make_account(
        tier, business_name="Uncertified Repairs",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    return {
        "branch": branch, "requested": requested, "replacement": replacement,
        "account": account,
        "order": open_will_call_order(account, branch, purchase_order_ref="PO-3013"),
    }


# ---------------------------------------------------------------------------
# The happy path through the return gates
# ---------------------------------------------------------------------------

class TestReturnAuthorizationAdmission:

    def test_a_partial_return_inside_the_window_is_admitted_and_priced(self):
        """PRD §3.9: "A new authorization has `ra_status` equal to `REQUESTED`,
        `fee_waived` false, `created_by_user_id` stamped with the raising operator's
        `X-User-ID`, `decided_by_user_id` and `received_at` null, and
        `restocking_fee_pct` null."
        PRD §3.9: "`days_since_fulfilled_at_request` is the whole days between the
        order's `fulfilled_at` and the logical clock at the moment the authorization
        is raised — the difference in epoch seconds divided by 86400 and floored."
        PRD §3.9: "At creation the authorization also fixes its
        `gross_return_cents`: the line's `invoiced_unit_price_cents` multiplied by
        the authorization's `quantity` for a goods return, and exactly 0 for a
        `CORE_RETURN`, because a core return refunds the deposit and never the part
        price."
        PRD §3.9: "Multiply it by `gross_return_cents` and round half up to a whole
        cent to get `restocking_fee_cents`, then take `credit_amount_cents` as
        `gross_return_cents` minus `restocking_fee_cents` — an exact integer
        remainder, so fee plus credit always reconstitutes the gross exactly."

        Design: Corner/validations/return_authorization_is_created_when_every_gate_is_satisfied
        """
        world = _three_shipped_units_observed_on_day_five()

        created = validate_success(
            api_client.create_return_authorization(
                return_authorization_payload(
                    world["account"]["id"], world["line"]["id"], 2, "WRONG_PART",
                    world["branch"]["id"],
                ),
                make_servicer_headers(world["account"]["id"]),
            ),
            201,
        )
        assert created["ra_status"] == "REQUESTED"
        assert created["days_since_fulfilled_at_request"] == 5, (
            f"Expected the pinned five whole days, got "
            f"{created['days_since_fulfilled_at_request']}"
        )
        assert created["gross_return_cents"] == 20798, (
            f"Expected the invoiced 10399 x 2, got {created['gross_return_cents']}"
        )
        assert created["fee_waived"] is False
        assert created["restocking_fee_pct"] is None

        response = api_client.decide_return_authorization(
            created["id"],
            dict(return_decision_payload("APPROVE"), decision_note="inside window"),
            CREDIT_MANAGER,
        )
        validate_success(response, 200)

        ra = read_return_authorization(created["id"])
        assert ra["ra_status"] == "APPROVED"
        assert ra["restocking_fee_pct"] == pytest.approx(0.10, abs=1e-9)
        assert ra["restocking_fee_cents"] == 2080, (
            f"Expected 20798 x 0.10 rounded half up, got "
            f"{ra['restocking_fee_cents']}"
        )
        assert ra["credit_amount_cents"] == 18718, (
            f"Expected the exact remainder 20798 - 2080, got "
            f"{ra['credit_amount_cents']}"
        )
        assert ra["core_deposit_refund_cents"] == 0
        assert ra["fee_waived"] is False


class TestReturnQuantityCeiling:

    def test_a_second_authorization_cannot_take_the_line_past_its_quantity(self):
        """PRD §3.9: "Second, quantity: the requested `quantity` plus the quantities
        already committed to that line's other authorizations in `REQUESTED`,
        `APPROVED`, `RECEIVED`, or `CREDITED` must not exceed the line's `quantity`,
        or the request is refused with `ERR_RETURN_QUANTITY_EXCEEDS_SHIPPED`; core
        returns are counted in their own class, independent of goods returns,
        because they release deposits rather than units."
        PRD §3.9: "For a non-core reason, the line's `returned_units` rises by the
        authorization's `quantity`, and when `returned_units` reaches the line's
        full `quantity` the line moves `SHIPPED → RETURNED`; a partial return leaves
        the line in `SHIPPED` with `returned_units` below `quantity`."

        Design: Corner/validations/two_partial_returns_cannot_exceed_the_shipped_quantity
        """
        world = _two_shipped_units_with_one_already_returned()

        response = api_client.create_return_authorization(
            return_authorization_payload(
                world["account"]["id"], world["line"]["id"], 2, "NO_LONGER_NEEDED",
                world["branch"]["id"],
            ),
            make_servicer_headers(world["account"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_RETURN_QUANTITY_EXCEEDS_SHIPPED)

        line = read_line(world["line"]["id"])
        assert line["returned_units"] == 1, (
            f"the refused request commits nothing, got {line['returned_units']}"
        )
        assert line["line_status"] == "SHIPPED"

        rows = list_return_authorizations(order_line_id=world["line"]["id"])
        assert len(rows) == 1, (
            f"only the first authorization exists, got {len(rows)} row(s)"
        )


# ---------------------------------------------------------------------------
# The core-deposit ceiling on hand-over
# ---------------------------------------------------------------------------

class TestCoreLiabilityCeiling:

    def test_hand_over_is_refused_when_the_deposits_would_breach_the_ceiling(self):
        """PRD §3.6: "Finally, core liability is checked: the account's current
        `core_liability_cents` plus the sum, over the order's `ALLOCATED` lines whose
        resolved part has `core_required` true, of that part's `core_deposit_cents`
        multiplied by the line's `quantity`, must not exceed the account's
        `core_liability_limit_cents`; exceeding it is rejected with
        `ERR_CORE_LIABILITY_LIMIT_EXCEEDED`."
        PRD §3.4: "The `core_deposit_total_cents` is the sum, over lines whose
        `line_status` is `SHIPPED` or `RETURNED` and whose resolved part has
        `core_required` true, of that line's `core_deposit_cents` multiplied by its
        `quantity`; it is zero before hand-over, because core deposits are invoiced
        rather than quoted."

        Design: Corner/validations/core_deposit_ceiling_blocks_a_shipment_that_would_breach_it
        """
        world = _allocated_compressors_against_a_tiny_core_ceiling()

        response = api_client.fulfill_part_order(
            world["order"]["id"],
            {"tracking_ref": "WILLCALL-3011"},
            make_branch_counter_rep_headers(world["branch"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_CORE_LIABILITY_LIMIT_EXCEEDED)

        order = read_order(world["order"]["id"])
        assert order["fulfillment_status"] == "ALLOCATED", (
            f"the refused hand-over leaves the order allocated, got "
            f"{order['fulfillment_status']}"
        )
        assert order["settlement_status"] == "CREDIT_APPROVED"
        assert order["subtotal_cents"] == 576000, (
            f"Expected 320000 x 0.90 x 2, got {order['subtotal_cents']}"
        )
        assert order["core_deposit_total_cents"] == 0, (
            "deposits are invoiced at hand-over, and hand-over did not happen"
        )
        assert order["fulfilled_at"] is None

        assert read_line(world["line"]["id"])["line_status"] == "ALLOCATED"

        account = read_account(world["account"]["id"])
        assert account["core_liability_cents"] == 0

        stock = inventory_for(world["branch"]["id"], world["part"]["id"])
        assert_inventory_units(stock, on_hand=5, reserved=2, available=3)


# ---------------------------------------------------------------------------
# The ninety-day warranty edge
# ---------------------------------------------------------------------------

class TestWarrantyWindowEdge:

    def test_day_ninety_submits_and_day_ninety_one_is_refused(self):
        """PRD §3.8: "Three conditions gate it beyond the claim being `DRAFT`: the
        account must be `ACTIVE`, the whole days elapsed since the order's
        `fulfilled_at` must be at most 90, and the account must hold an effective
        certification for the claim's `oem_code`."
        PRD §3.8: "Exceeding the ninety-day window is rejected with
        `ERR_WARRANTY_PERIOD_EXPIRED`; lacking the certification is rejected with
        `ERR_TECHNICIAN_CERT_REQUIRED`, which makes a revocation by the warranty
        desk immediately felt on the claim side as well as the ordering side."
        PRD §3.8: "A new claim has `claim_status` equal to `DRAFT`,
        `resubmission_count` at zero, and `submitted_at`, `oem_reference`,
        `claim_amount_cents`, and `credit_amount_cents` all unset."

        Design: Corner/validations/warranty_window_accepts_day_ninety_and_rejects_day_ninety_one
        """
        world = _two_shipped_lines_with_a_claim_on_each()

        set_clock("2026-10-30T00:00:00Z")
        submitted = submit_claim(world["first_claim"]["id"], "WP-CLAIM-A")
        assert submitted["claim_status"] == "SUBMITTED", (
            "exactly ninety whole days is still inside the window"
        )
        assert submitted["claim_amount_cents"] == 31197, (
            f"Expected the invoiced 10399 x 3, got {submitted['claim_amount_cents']}"
        )

        set_clock("2026-10-31T00:00:00Z")
        response = api_client.submit_warranty_claim(
            world["second_claim"]["id"], {"oem_reference": "WP-CLAIM-B"},
            WARRANTY_ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_WARRANTY_PERIOD_EXPIRED)

        first = read_claim(world["first_claim"]["id"])
        assert first["claim_status"] == "SUBMITTED"
        assert first["claim_amount_cents"] == 31197

        second = read_claim(world["second_claim"]["id"])
        assert second["claim_status"] == "DRAFT", (
            f"one day past the window nothing moves, got {second['claim_status']}"
        )
        assert second["claim_amount_cents"] is None
        assert second["submitted_at"] is None


# ---------------------------------------------------------------------------
# Which part the competence gate reads
# ---------------------------------------------------------------------------

class TestCertificationGateReadsTheResolvedPart:

    def test_the_competence_demanded_is_the_resolved_parts_not_the_requested_ones(self):
        """PRD §3.4: "The line first walks the supersession chain of §3.1 to
        establish its `resolved_part_id` and `supersession_hops`."
        PRD §3.4: "It then faces three gates in sequence: the resolved part's
        `oem_code` must appear in the account's `oem_authorizations`, or the add is
        rejected with `ERR_OEM_AUTHORIZATION_MISSING`; the account must hold an
        effective certification meeting the resolved part's `cert_level_required`,
        or the add is rejected with `ERR_TECHNICIAN_CERT_REQUIRED`; and the
        account's credit exposure recomputed **with this line included** must not
        exceed its `credit_limit_cents`, or the add is rejected with
        `ERR_CREDIT_LIMIT_EXCEEDED`."
        PRD §2.7: "25. `ERR_TECHNICIAN_CERT_REQUIRED` (422) — the account holds an
        effective certification for the part's `oem_code` at a `cert_level` that
        meets or exceeds the part's `cert_level_required`. Guards two operations:
        `POST /part-orders/{id}/lines` and `POST /warranty-claims/{id}/submit`."

        Design: Corner/validations/cert_requirement_is_derived_from_the_resolved_part_not_the_requested_one
        """
        world = _mechanical_part_superseded_by_an_electrical_one()
        assert world["requested"]["cert_level_required"] == "NONE", (
            "the part the servicer asked for demands nothing on its own"
        )
        assert world["replacement"]["cert_level_required"] == "ADVANCED"

        response = api_client.add_order_line(
            world["order"]["id"],
            order_line_payload(
                world["requested"]["id"], 1, world["order"]["version"]
            ),
            make_servicer_headers(world["account"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_TECHNICIAN_CERT_REQUIRED)

        order = read_order(world["order"]["id"])
        assert order["subtotal_cents"] == 0
        assert order["version"] == 1, (
            f"the refused add is not a mutation of the order, got version "
            f"{order['version']}"
        )

        assert list_order_lines(part_order_id=world["order"]["id"]) == [], (
            "no line row survives the refused add"
        )
