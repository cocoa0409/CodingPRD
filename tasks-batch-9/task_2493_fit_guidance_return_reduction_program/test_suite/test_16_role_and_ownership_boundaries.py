"""Who may act, on whose rows, and which operator may not act twice.

Each test pairs a refusal with the acceptance that proves the refusal was about
identity and nothing else: the same call by the right role, the byte-identical body
from the owning brand, the same request from the shopper who actually bought the
garment, and the same closure by a second auditor.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ANALYST_USER_ID,
    CLASSIFY_AUDITOR_USER_ID,
    RESOLVE_AUDITOR_USER_ID,
    ApiErrorId,
    create_measurement_spec_payload,
    create_return_case_payload,
    is_iso8601_timestamp,
    make_customer_headers,
    make_fit_analyst_headers,
    make_merch_ops_admin_headers,
    make_returns_auditor_headers,
    make_vendor_user_headers,
    resolve_return_case_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx  # noqa: E402

SCENARIO_START = "2026-06-01T00:00:00Z"

TOPS_THIRTY_DAY_POLICY = {
    "window_days": 30,
    "restocking_applies": True,
    "non_refundable_shipping": False,
    "effective_from": "2026-01-01T00:00:00Z",
}

DELIVERED_LINE = {
    "size_label": "M",
    "quantity": 1,
    "unit_price_cents": 2295,
    "shipping_allocated_cents": 0,
    "delivered_at": "2026-05-20T00:00:00Z",
}


def test_the_catalogue_administrator_cannot_verify_a_specification(api):
    """PRD §2.9: "**Authorization.** The acting role appears in the endpoint's authorized
    list, otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."  Verification
    belongs to the analyst alone, and the role that registers brands, drafts charts and
    runs the checkpoint is not a superuser over it: the refused attempt leaves the
    specification awaiting verification with no verifying operator recorded, and the
    identical call by an analyst then decides it.

    Design: Corner/rbac/merch_ops_admin_cannot_verify_a_specification_returns_unauthorized
    """
    fx.set_clock(api, SCENARIO_START)
    vendor = fx.create_vendor(api)
    item = fx.create_item(api, vendor["id"])
    spec = fx.create_spec(api, item["id"], vendor["id"])
    fx.submit_spec(api, spec["id"], vendor["id"])

    response = api.verify_measurement_spec(spec["id"], make_merch_ops_admin_headers())
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    untouched = fx.read_spec(api, spec["id"])
    assert untouched["status"] == "SUBMITTED"
    assert untouched["verified_by_user_id"] is None

    verified = fx.verify_spec(api, spec["id"])
    assert verified["status"] == "VERIFIED"
    assert verified["violation_count"] == 0
    assert verified["verified_by_user_id"] == ANALYST_USER_ID
    assert is_iso8601_timestamp(verified["verified_at"])
    assert verified["verified_at"].startswith("2026-06-01T00:00:00")


def test_a_brand_cannot_file_a_specification_for_another_brands_item(api):
    """PRD §2.9: "**Ownership.** For the two entity-backed roles, the acting `X-User-ID`
    owns the target as described in §2.1, otherwise `ERR_NOT_RESOURCE_OWNER` (403).
    Applies to every `VendorUser` and `Customer` operation."  Holding the
    specification-write operation is not enough, because the acting brand identity is
    compared against the item's supplying brand: the outside brand's request is a
    permission failure rather than a missing item, and the identical body from the owner
    is accepted, leaving the item with exactly one specification.

    Design: Corner/rbac/vendor_user_cannot_file_a_specification_for_another_vendors_item
    """
    fx.set_clock(api, SCENARIO_START)
    owner = fx.create_vendor(api)
    outsider = fx.create_vendor(
        api, name="Southport Knitwear", brand_code="SOUT", correction_budget_cents=250000
    )
    item = fx.create_item(api, owner["id"])

    payload = create_measurement_spec_payload(item["id"])
    response = api.create_measurement_spec(
        payload, make_vendor_user_headers(outsider["id"])
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    accepted = validate_success(
        api.create_measurement_spec(payload, make_vendor_user_headers(owner["id"])), 201
    )
    assert accepted["status"] == "DRAFT"
    assert accepted["revision_round"] == 0
    assert accepted["item_id"] == item["id"]

    rows, meta = validate_paginated(
        api.list_measurement_specs(
            make_merch_ops_admin_headers(),
            {"item_id": item["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [accepted["id"]]


def test_a_shopper_cannot_open_a_return_on_another_shoppers_purchase(api):
    """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting
    `CustomerProfile`; ownership checks compare the resource's customer foreign key to
    `X-User-ID` — the `customer_profile_id` of the `OrderLine` behind a return case on
    return-case writes and reads, the `customer_profile_id` supplied in the body on
    fit-feedback creation, the `customer_profile_id` of the `FitFeedback` row on
    retraction, and the `customer_profile_id` query value on the fit-recommendation
    read."  The second shopper holds a perfectly good identity and the line is well
    inside its window, but the line is not theirs, so the refusal leaves their own
    return counter at zero while the buyer's request succeeds.

    Design: Corner/rbac/customer_cannot_open_a_return_case_on_another_shoppers_order_line
    """
    built = fx.setup_listed_item(api, SCENARIO_START)
    policy = fx.create_policy(api, category_code="TOPS", **TOPS_THIRTY_DAY_POLICY)
    buyer = fx.create_customer(api, email="shopper-a@example.com")
    stranger = fx.create_customer(api, email="shopper-b@example.com")
    line = fx.create_order_line(api, buyer["id"], built["item"]["id"], **DELIVERED_LINE)

    payload = create_return_case_payload(
        line["id"], requested_reason_code="FIT_TOO_LARGE"
    )
    response = api.create_return_case(payload, make_customer_headers(stranger["id"]))
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    case = validate_success(
        api.create_return_case(payload, make_customer_headers(buyer["id"])), 201
    )
    assert case["status"] == "TRIAGE"
    assert case["effective_policy_id"] == policy["id"]

    _, meta = validate_paginated(
        api.list_return_cases(
            make_merch_ops_admin_headers(),
            {"order_line_id": line["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1

    assert fx.read_customer(api, stranger["id"])["return_case_count"] == 0
    assert fx.read_customer(api, buyer["id"])["return_case_count"] == 1


def test_the_auditor_who_coded_the_case_cannot_also_close_it(api):
    """PRD §3.8: "Closing the case is a second `ReturnsAuditor` action and it must be a
    *different* operator: the acting `X-User-ID` must differ from the stored
    `classified_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`."  The refused
    operator holds exactly the right role, so the check is on the recorded identity
    rather than on capability, and the refusal writes no cost ledger at all; a second
    operator of the same role then closes the case and the whole closure fires.

    Design: Corner/rbac/the_classifying_auditor_cannot_resolve_the_same_case
    """
    built = fx.setup_classified_case(
        api,
        SCENARIO_START,
        "FIT_TOO_SMALL",
        case_overrides={"requested_reason_code": "FIT_TOO_SMALL"},
        policy_overrides=dict(TOPS_THIRTY_DAY_POLICY),
        customer_overrides={"email": "shopper-r4@example.com"},
        line_overrides=dict(DELIVERED_LINE),
    )
    assert built["case"]["status"] == "FIT_REVIEW"
    assert built["case"]["classified_by_user_id"] == CLASSIFY_AUDITOR_USER_ID

    response = api.resolve_return_case(
        built["case"]["id"],
        resolve_return_case_payload("RESELLABLE_A"),
        make_returns_auditor_headers(CLASSIFY_AUDITOR_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert fx.read_cost_postings(api, built["case"]["id"]) == []

    resolved = fx.resolve_case(api, built["case"]["id"], "RESELLABLE_A")
    assert resolved["status"] == "RESOLVED_REFUNDED"
    assert resolved["refund_amount_cents"] == 2295
    assert resolved["total_cost_cents"] == 1454
    assert resolved["resolved_by_user_id"] == RESOLVE_AUDITOR_USER_ID
    assert resolved["classified_by_user_id"] == CLASSIFY_AUDITOR_USER_ID

    assert fx.read_order_line(api, built["order_line"]["id"])["status"] == "RETURNED"
    assert fx.read_item(api, built["item"]["id"])["fit_return_count"] == 1


def test_the_case_read_is_shared_by_auditor_and_admin_but_closed_to_the_analyst(api):
    """PRD §2.1: "A `FitAnalyst` verifies specifications, maps brand sizes onto
    standardized charts, and turns fit guidance on — and can never author a
    specification or resolve a return."  Return-reason detail is not part of the
    fit-analysis surface, so the two roles that work returns read the same row and the
    analyst — who may freely read the item and its charts — is refused on the case, and
    the refusal changes nothing about it.

    Design: Corner/rbac/return_case_read_is_shared_by_auditor_and_admin_but_fit_analyst_returns_unauthorized
    """
    built = fx.setup_triage_case(
        api,
        SCENARIO_START,
        case_overrides={"requested_reason_code": "EXPECTATION_MISMATCH"},
        policy_overrides=dict(TOPS_THIRTY_DAY_POLICY),
        customer_overrides={"email": "shopper-r5@example.com"},
        line_overrides=dict(DELIVERED_LINE),
    )
    case_id = built["case"]["id"]

    by_auditor = validate_success(
        api.get_return_case(case_id, make_returns_auditor_headers())
    )
    by_admin = validate_success(
        api.get_return_case(case_id, make_merch_ops_admin_headers())
    )
    assert by_auditor["status"] == "TRIAGE"
    assert by_admin["status"] == "TRIAGE"
    assert by_auditor["requested_reason_code"] == "EXPECTATION_MISMATCH"
    assert by_admin["requested_reason_code"] == "EXPECTATION_MISMATCH"

    response = api.get_return_case(case_id, make_fit_analyst_headers())
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    assert fx.read_case(api, case_id)["status"] == "TRIAGE"
