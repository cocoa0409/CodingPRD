"""Priority-pair validation conflicts: when two violations hold on one call,
PRD 2.7's fixed ordering decides which error surfaces."""
from test_helpers import ApiErrorId, add_certified_classification, add_claim, add_claim_line, add_export_shipment, add_import_entry, onboard_client, onboard_client_b, setup_trade_scenario, TEST_USERS, validate_error, validate_error_is_one_of, validate_success

ADMIN = TEST_USERS["firm_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
BROKER = TEST_USERS["broker_headers"]


def test_file_of_cancelled_claim_reports_invalid_state_not_deadline_passed(api):
    """PRD 2.7: "Stale-version checks come next (`ERR_STALE_VERSION`), then
    state-machine legality (`ERR_INVALID_STATE` for a resource not in a valid
    from-state, `ERR_ALREADY_TERMINAL` for one already terminal), then
    segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), then cross-entity
    referential rules (classification certification, client engagement,
    same-client references), then temporal rules (windows, filing deadlines,
    audit due dates), then uniqueness and overlap rules (entry numbers, measure
    windows, claim periods, deficiency limits), then match compatibility and
    quantity bounds, then frozen-ledger protections, and finally fiscal caps
    such as the export value pool and the various payment equalities."
    PRD 3.5: "`PAID`, `DENIED`, and `CANCELLED` are all terminal; any further
    transition attempt against them is `ERR_ALREADY_TERMINAL`."

    Design: Difficulty/priority_pair_validation_conflict/file_state_beats_deadline
    """
    ctx = setup_trade_scenario(
        entry_overrides={"entry_date": "2021-01-01T00:00:00Z"},
        export_overrides={"export_date": "2021-04-01T00:00:00Z"},
    )
    claim = add_claim(
        ctx["client"]["id"],
        period_start="2021-01-01T00:00:00Z",
        period_end="2021-03-31T00:00:00Z",
    )
    add_claim_line(
        claim["id"], ctx["entry"]["id"], ctx["export"]["id"], matched_quantity=40
    )
    validate_success(api.cancel_claim(claim["id"], ANALYST))

    # The deadline (2021-01-01 + 5y = 2026-01-01) is past the default clock
    # (2026-05-01) AND the claim is terminal CANCELLED: state wins.
    res = api.file_claim(claim["id"], BROKER)
    validate_error_is_one_of(
        res,
        [ApiErrorId.ERR_INVALID_STATE.value, ApiErrorId.ERR_ALREADY_TERMINAL.value],
    )

    claim_after = validate_success(api.get_claim(claim["id"], ANALYST))
    assert claim_after["status"] == "CANCELLED"


def test_cancelled_claim_never_files_even_with_fresh_entries(api):
    """PRD 3.5: "`PAID`, `DENIED`, and `CANCELLED` are all terminal; any further
    transition attempt against them is `ERR_ALREADY_TERMINAL`."
    PRD 3.4: "When a `LicensedBroker` files the claim, four preconditions hold:
    the client must still be `ACTIVE` (`ERR_CLIENT_NOT_ACTIVE`); the claim must
    have at least one `ACTIVE` line (`ERR_INVALID_REQUEST`); the broker's
    `X-User-ID` must differ from `prepared_by_user_id`
    (`ERR_SEGREGATION_OF_DUTIES`); and the logical clock must not have passed
    the claim's `filing_deadline` (`ERR_FILING_DEADLINE_PASSED`)."

    Design: Difficulty/priority_pair_validation_conflict/file_state_beats_deadline
    """
    ctx = setup_trade_scenario()
    claim = add_claim(ctx["client"]["id"])
    add_claim_line(
        claim["id"], ctx["entry"]["id"], ctx["export"]["id"], matched_quantity=40
    )
    validate_success(api.cancel_claim(claim["id"], ANALYST))

    res = api.file_claim(claim["id"], BROKER)
    validate_error_is_one_of(
        res,
        [ApiErrorId.ERR_INVALID_STATE.value, ApiErrorId.ERR_ALREADY_TERMINAL.value],
    )


def test_cross_client_line_reports_referential_error_not_fiscal_pool_error(api):
    """PRD 2.7: "then cross-entity referential rules (classification
    certification, client engagement, same-client references), then temporal
    rules (windows, filing deadlines, audit due dates), then uniqueness and
    overlap rules (entry numbers, measure windows, claim periods, deficiency
    limits), then match compatibility and quantity bounds, then frozen-ledger
    protections, and finally fiscal caps such as the export value pool and the
    various payment equalities."
    PRD 3.4: "Adding a line to a `DRAFT` claim requires `import_entry_id`,
    `export_shipment_id`, and a positive `matched_quantity`, and both referenced
    resources must belong to the same client as the claim
    (`ERR_CROSS_CLIENT_REFERENCE` otherwise)."

    Design: Difficulty/priority_pair_validation_conflict/line_referential_beats_fiscal
    """
    client_a = onboard_client()
    client_b = onboard_client_b()
    cls_b = add_certified_classification(client_b["id"])
    entry_b = add_import_entry(
        client_b["id"], cls_b["id"], entry_number="B100",
        line_quantity=1, entered_value_cents=100, duty_paid_cents=100,
    )
    # Client A's export pool is tiny, so ANY refund would breach the FOB cap —
    # but the cross-client reference must be the reported failure.
    export_a = add_export_shipment(client_a["id"], fob_value_cents=10)
    claim_a = add_claim(client_a["id"])

    res = api.add_claim_line(
        claim_a["id"],
        {
            "import_entry_id": entry_b["id"],
            "export_shipment_id": export_a["id"],
            "matched_quantity": 1,
        },
        ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_CROSS_CLIENT_REFERENCE)

    claim_after = validate_success(api.get_claim(claim_a["id"], ANALYST))
    assert claim_after["estimate_cents"] == 0, "no line may be persisted"


def test_cross_client_export_reference_also_reports_referential_error(api):
    """PRD 3.4: "Adding a line to a `DRAFT` claim requires `import_entry_id`,
    `export_shipment_id`, and a positive `matched_quantity`, and both referenced
    resources must belong to the same client as the claim
    (`ERR_CROSS_CLIENT_REFERENCE` otherwise)."
    PRD 2.7: "then cross-entity referential rules (classification
    certification, client engagement, same-client references), then temporal
    rules (windows, filing deadlines, audit due dates), then uniqueness and
    overlap rules (entry numbers, measure windows, claim periods, deficiency
    limits), then match compatibility and quantity bounds, then frozen-ledger
    protections, and finally fiscal caps such as the export value pool and the
    various payment equalities."

    Design: Difficulty/priority_pair_validation_conflict/line_referential_beats_fiscal
    """
    client_a = onboard_client()
    client_b = onboard_client_b()
    cls_a = add_certified_classification(client_a["id"])
    entry_a = add_import_entry(client_a["id"], cls_a["id"])
    export_b = add_export_shipment(client_b["id"], fob_value_cents=10)
    claim_a = add_claim(client_a["id"])

    res = api.add_claim_line(
        claim_a["id"],
        {
            "import_entry_id": entry_a["id"],
            "export_shipment_id": export_b["id"],
            "matched_quantity": 1,
        },
        ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_CROSS_CLIENT_REFERENCE)

    claim_after = validate_success(api.get_claim(claim_a["id"], ANALYST))
    assert claim_after["estimate_cents"] == 0
