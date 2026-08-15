"""Filing creation, components, readiness, and listings (PRD §2.3, §3.3)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_final_component,
    assert_filing,
    create_filing_payload,
    create_indication,
    create_product,
    create_profile,
    get_success_data,
    setup_draft_filing,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


def test_filing_created_in_draft_with_null_workflow_fields(api):
    """PRD §3.3: "With a locked indication in hand, a `FilingAnalyst` creates a
    **Rate Filing** in `DRAFT` status".
    PRD §3.3: "A successful submission stamps `submitted_at` with the current
    logical time, assigns the `filing_number` ... computes the `deemer_date`
    (§3.5)". (All three are therefore unset before submission.)

    Design: Corner/entities/filing_created_initial_state_draft
    """
    scenario = setup_draft_filing()
    filing = scenario["filing"]

    assert_filing(filing)
    assert filing["status"] == "DRAFT"
    assert filing["filing_number"] is None
    assert filing["submitted_at"] is None
    assert filing["deemer_date"] is None
    assert filing["actual_effective_date"] is None
    assert filing["open_objection_count"] == 0


def test_create_filing_with_invalid_filing_type_rejected(api):
    """PRD §2.8: "third, request-body well-formedness — required fields
    present, no unknown fields, types correct, enum members valid, amounts
    positive, dates in ISO format — with violations rejected as
    `ERR_INVALID_REQUEST` (HTTP 400)".

    Design: Corner/entities/create_filing_invalid_enum_rejected
    """
    scenario = setup_draft_filing()
    payload = create_filing_payload(
        scenario["product"]["id"],
        "CA",
        scenario["indication"]["id"],
        filing_type="BOGUS",
    )
    res = api.create_filing(payload, fx.ANALYST)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_filing_not_found(api):
    """PRD §2.8: "fourth, the existence of every resource referenced by path
    identifiers and body foreign keys, resolved left to right, with the first
    unresolvable reference rejected as `ERR_NOT_FOUND` (HTTP 404)".

    Design: Corner/entities/get_filing_not_found_returns_404
    """
    res = api.get_filing(NON_EXISTENT_UUID, fx.ANALYST)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_list_filings_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return. If not provided, it defaults to 10, with a minimum of 1 and a
    maximum of 100. The `offset` parameter specifies the number of items to
    skip and defaults to 0."
    PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_filings_pagination_envelope
    """
    scenario = setup_draft_filing()
    data, meta = validate_paginated(
        api.list_filings(
            fx.ANALYST, params={"product_id": scenario["product"]["id"]}
        )
    )
    assert [f["id"] for f in data] == [scenario["filing"]["id"]]
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_duplicate_open_filing_rejected(api):
    """PRD §3.3: "at most one filing may be open per product and state, where
    open means `DRAFT`, `READY`, `SUBMITTED`, `UNDER_OBJECTION`, `APPROVED`,
    or `DEEMED_APPROVED` (an `EFFECTIVE` filing does not block its successor),
    and a conflicting open filing triggers `ERR_DUPLICATE_OPEN_FILING`
    (HTTP 409)".

    Design: Corner/validations/duplicate_open_filing_rejected
    """
    scenario = setup_draft_filing()
    res = api.create_filing(
        create_filing_payload(
            scenario["product"]["id"],
            "CA",
            scenario["indication"]["id"],
            filing_type="FORM_ONLY",
            proposed_change_pct=0.0,
            proposed_effective_date="2026-12-01",
        ),
        fx.ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_OPEN_FILING)


def test_filing_create_requires_locked_indication(api):
    """PRD §3.3: "The referenced indication must be `LOCKED` — a draft,
    in-review, approved-but-unlocked, or superseded indication draws
    `ERR_INDICATION_NOT_LOCKED`."

    Design: Corner/validations/filing_create_requires_locked_indication
    """
    product = create_product()
    create_profile(product["id"], "CA")
    indication = create_indication(product["id"], product["version"])
    # APPROVED but never LOCKED.
    get_success_data(api.submit_indication_review(indication["id"], fx.ACT1))
    get_success_data(api.approve_indication(indication["id"], fx.ACT2))

    res = api.create_filing(
        create_filing_payload(product["id"], "CA", indication["id"]), fx.ANALYST
    )
    validate_error(res, ApiErrorId.ERR_INDICATION_NOT_LOCKED)


def test_filing_create_with_unknown_indication_returns_not_found(api):
    """PRD §2.8: "fourth, the existence of every resource referenced by path
    identifiers and body foreign keys, resolved left to right, with the first
    unresolvable reference rejected as `ERR_NOT_FOUND` (HTTP 404)".

    Design: Corner/validations/create_filing_bogus_indication_returns_not_found
    """
    product = create_product()
    create_profile(product["id"], "CA")
    res = api.create_filing(
        create_filing_payload(product["id"], "CA", NON_EXISTENT_UUID), fx.ANALYST
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_mark_ready_happy_path(api):
    """PRD §3.3: "When the package is complete, the analyst marks the filing
    ready, moving it from `DRAFT` to `READY`."

    Design: Corner/state_machines/mark_ready_happy_path_returns_ready
    """
    scenario = setup_draft_filing()
    add_final_component(scenario["filing"]["id"], component_type="RATE")
    ready = validate_success(
        api.mark_filing_ready(scenario["filing"]["id"], fx.ANALYST), 200
    )
    assert ready["status"] == "READY"


def test_mark_ready_without_rate_component_rejected(api):
    """PRD §3.3: "a `RATE_CHANGE` or `RATE_RULE_FORM` filing must contain at
    least one `FINAL` component of type `RATE`; a `RULE_ONLY` filing at least
    one `FINAL` `RULE` component; a `FORM_ONLY` filing at least one `FINAL`
    `FORM` component. A filing short of its required set is refused with
    `ERR_COMPONENT_INCOMPLETE` (HTTP 409)."

    Design: Corner/validations/mark_ready_without_rate_component_rejected
    """
    scenario = setup_draft_filing()
    add_final_component(
        scenario["filing"]["id"],
        component_type="RULE",
        name="CA Rule Pages",
        content_ref="s3://fil/ca-rule.pdf",
    )
    res = api.mark_filing_ready(scenario["filing"]["id"], fx.ANALYST)
    validate_error(res, ApiErrorId.ERR_COMPONENT_INCOMPLETE)
    filing = get_success_data(api.get_filing(scenario["filing"]["id"], fx.ANALYST))
    assert filing["status"] == "DRAFT"


def test_component_finalize_blocked_once_filing_ready(api):
    """PRD §3.3: "Components are born `DRAFT`, and the analyst finalizes each
    one, moving it to `FINAL`; finalization likewise requires the parent filing
    to still be `DRAFT`."

    Design: Corner/state_machines/component_finalize_blocked_when_filing_ready
    """
    scenario = setup_draft_filing()
    add_final_component(scenario["filing"]["id"], component_type="RATE")
    rule_component = get_success_data(
        api.create_component(
            scenario["filing"]["id"],
            {
                "component_type": "RULE",
                "name": "CA Rule Pages",
                "content_ref": "s3://fil/ca-rule.pdf",
            },
            fx.ANALYST,
        )
    )
    assert rule_component["status"] == "DRAFT"
    get_success_data(api.mark_filing_ready(scenario["filing"]["id"], fx.ANALYST))

    res = api.finalize_component(rule_component["id"], fx.ANALYST)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = get_success_data(api.get_component(rule_component["id"], fx.ANALYST))
    assert after["status"] == "DRAFT"
