"""List endpoints, authentication/authorization, and damage-claim rules (PRD §2.1, §2.3, §3.7, §3.9)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data,
    create_customer_payload, create_item_payload, create_claim_payload,
    packing_list_line, create_packing_list_payload,
    invoice_line, create_commercial_invoice_payload,
    create_customer, create_job, add_item, create_wood_batch,
    accept_quote, make_customer_headers,
    setup_quoted_job_with_item, setup_job_with_approved_design,
    setup_packing_job_with_crate, setup_delivered_job,
    setup_delivered_job_with_reviewed_claims,
    assert_damage_claim,
)
from test_helpers import TEST_USERS

SR = TEST_USERS["sales_rep_headers"]
CD = TEST_USERS["crating_designer_headers"]
SF = TEST_USERS["shop_foreman_headers"]
CO = TEST_USERS["compliance_officer_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
PA = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Items list pagination (corner: endpoints)
# ---------------------------------------------------------------------------

def test_items_list_first_page_reports_total_and_has_more(api, sales_rep_headers):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0."
    PRD §2.3: "Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/items_list_pagination
    """
    customer = create_customer(name="Page Co", site_code="PAG-01")
    job = create_job(customer)
    for i in range(12):
        add_item(job["id"], description=f"Part {i + 1:02d}", length_cm=10, width_cm=10,
                 height_cm=10, weight_kg=1, declared_value_cents=100)

    data, meta = validate_paginated(api.list_items(
        sales_rep_headers, params={"packing_job_id": job["id"], "limit": 10}))
    assert len(data) == 10
    assert meta["total_count"] == 12
    assert meta["has_more"] is True


def test_items_list_second_page_returns_remainder(api, sales_rep_headers):
    """PRD §2.3: "The `offset` parameter specifies the number of items to skip and defaults to 0."

    Design: Corner/endpoints/items_list_pagination
    """
    customer = create_customer(name="Page Co", site_code="PAG-01")
    job = create_job(customer)
    for i in range(12):
        add_item(job["id"], description=f"Part {i + 1:02d}", length_cm=10, width_cm=10,
                 height_cm=10, weight_kg=1, declared_value_cents=100)

    data, meta = validate_paginated(api.list_items(
        sales_rep_headers, params={"packing_job_id": job["id"], "limit": 10, "offset": 10}))
    assert len(data) == 2
    assert meta["total_count"] == 12
    assert meta["has_more"] is False


# ---------------------------------------------------------------------------
# Crates filter by status (corner: endpoints)
# ---------------------------------------------------------------------------

def _setup_packing_job_with_two_crates_one_built():
    customer = create_customer(name="Filter Co", site_code="FLT-01")
    job = create_job(customer)
    item1 = add_item(job["id"], description="Motor A", weight_kg=50,
                     declared_value_cents=30000)
    item2 = add_item(job["id"], description="Motor B", weight_kg=50,
                     declared_value_cents=30000)
    batch = create_wood_batch(received_board_feet=5000, stamps_acquired=2)
    from test_helpers import create_design_payload, submit_and_approve_design
    d1 = get_success_data(api_client.create_design(
        item1["id"], create_design_payload(item1["version"]), CD))
    d1 = submit_and_approve_design(d1["id"], batch["id"])
    d2 = get_success_data(api_client.create_design(
        item2["id"], create_design_payload(item2["version"]), CD))
    d2 = submit_and_approve_design(d2["id"], batch["id"])
    accept_quote(customer, job["id"])
    get_success_data(api_client.start_packing(job["id"], SF))
    crate1 = get_success_data(api_client.create_crate(item1["id"], {"design_id": d1["id"]}, SF))
    crate2 = get_success_data(api_client.create_crate(item2["id"], {"design_id": d2["id"]}, SF))
    get_success_data(api_client.build_crate(crate1["id"], SF))
    return job, crate1, crate2


def test_crates_filter_returns_only_built(api, shop_foreman_headers):
    """PRD §4: "List endpoints accept the `limit` and `offset` pagination parameters of §2.3 plus optional filters: customers by `status`; packing jobs by `customer_id` and `status`; items by `packing_job_id` and `status`; designs by `item_id`, `wood_batch_id`, and `status`; wood batches by `status`; crates by `item_id`, `packing_job_id`, `container_id`, `design_id`, and `status`; declarations by `item_id` and `status`; packing lists and commercial invoices by `packing_job_id` and `status`; labor bookings by `crew_id`, `packing_job_id`, and `status`; permits by `packing_job_id`, `site_code`, and `status`; claims by `packing_job_id`, `crate_id`, and `status`."

    Design: Corner/endpoints/crates_filter_by_status
    """
    job, crate1, _ = _setup_packing_job_with_two_crates_one_built()
    data, meta = validate_paginated(api.list_crates(
        shop_foreman_headers, params={"packing_job_id": job["id"], "status": "BUILT"}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == crate1["id"]
    assert data[0]["status"] == "BUILT"


def test_crates_filter_returns_only_planned(api, shop_foreman_headers):
    """PRD §4: "List endpoints accept the `limit` and `offset` pagination parameters of §2.3 plus optional filters: customers by `status`; packing jobs by `customer_id` and `status`; items by `packing_job_id` and `status`; designs by `item_id`, `wood_batch_id`, and `status`; wood batches by `status`; crates by `item_id`, `packing_job_id`, `container_id`, `design_id`, and `status`; declarations by `item_id` and `status`; packing lists and commercial invoices by `packing_job_id` and `status`; labor bookings by `crew_id`, `packing_job_id`, and `status`; permits by `packing_job_id`, `site_code`, and `status`; claims by `packing_job_id`, `crate_id`, and `status`."
    PRD §3.4: "the crate is born `PLANNED` with `container_id`, `stamp_serial`, and `stamp_status` null and `compliance_hold` false."

    Design: Corner/endpoints/crates_filter_by_status
    """
    job, _, crate2 = _setup_packing_job_with_two_crates_one_built()
    data, meta = validate_paginated(api.list_crates(
        shop_foreman_headers, params={"packing_job_id": job["id"], "status": "PLANNED"}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == crate2["id"]
    assert data[0]["status"] == "PLANNED"


# ---------------------------------------------------------------------------
# Authentication (corner: errors)
# ---------------------------------------------------------------------------

def test_request_without_auth_headers_rejected(api):
    """PRD §2.1: "Every request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. ... A request with missing headers or an unrecognized role is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/missing_auth_headers_returns_401
    """
    res = api._request("POST", "/crating/customers",
                       {"name": "NoAuth Co", "site_code": "NAU-01",
                        "credit_limit_cents": 1000},
                       headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ---------------------------------------------------------------------------
# Document-release role split (corner: rbac)
# ---------------------------------------------------------------------------

def _setup_finalized_docs_ctx():
    ctx = setup_job_with_approved_design(
        item_overrides={"description": "Valve", "weight_kg": 50,
                        "declared_value_cents": 10000},
        batch_overrides={"received_board_feet": 5000, "stamps_acquired": 2},
        accept=True)
    crate = get_success_data(api_client.create_crate(
        ctx["item"]["id"], {"design_id": ctx["design"]["id"]}, SF))
    ctx["crate"] = crate
    get_success_data(api_client.upsert_packing_list(
        ctx["job"]["id"], create_packing_list_payload([
            packing_list_line(crate["id"], "Valve", 1, 50.0, 98.6)]), SR))
    get_success_data(api_client.upsert_commercial_invoice(
        ctx["job"]["id"], create_commercial_invoice_payload([
            invoice_line(crate["id"], "Valve", 1, 10000)]), SR))
    get_success_data(api_client.finalize_docs(ctx["job"]["id"], SR))
    return ctx


def test_sales_rep_cannot_release_documents(api, sales_rep_headers):
    """PRD §2.10: "Export documents follow a similar split: a `SalesRep` drafts and finalizes the packing list and commercial invoice, but only a `ComplianceOfficer` may release them, keeping the person who wrote the numbers from being the person who certifies them."
    PRD §2.1: "a caller whose role is not admitted by the endpoint is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/salesrep_cannot_release_docs
    """
    ctx = _setup_finalized_docs_ctx()
    res = api.release_docs(ctx["job"]["id"], sales_rep_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)
    pls, _ = validate_paginated(api.list_packing_lists(
        CO, params={"packing_job_id": ctx["job"]["id"]}))
    cis, _ = validate_paginated(api.list_commercial_invoices(
        CO, params={"packing_job_id": ctx["job"]["id"]}))
    assert pls[0]["status"] == "FINALIZED" and cis[0]["status"] == "FINALIZED"


# ---------------------------------------------------------------------------
# Claim filing window (corner: validations)
# ---------------------------------------------------------------------------

def test_claim_filed_after_thirty_day_window_rejected(api, platform_admin_headers):
    """PRD §3.9: "the logical clock at filing must be no more than thirty days after the job's `delivered_at` (otherwise `ERR_CLAIM_WINDOW_EXPIRED`)".
    PRD §2.5: "delivery stamps `delivered_at` from the logical clock, and the damage-claim filing window and the moisture-depreciation schedule both measure elapsed time from that stamp."

    Design: Corner/validations/claim_window_expired_returns_422
    """
    ctx = setup_delivered_job()  # delivered at the startup clock 2026-08-01
    get_success_data(api_client.set_logical_clock(
        {"to_iso8601": "2026-09-05T00:00:00Z"}, platform_admin_headers))
    res = api.create_claim(
        ctx["job"]["id"],
        create_claim_payload(ctx["crate"]["id"], description="Late discovery",
                             amount_claimed_cents=50000),
        make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, "ERR_CLAIM_WINDOW_EXPIRED", expected_status=422)


# ---------------------------------------------------------------------------
# Claim settlement variants (difficulty: dual_variant_calc)
# ---------------------------------------------------------------------------

def _setup_two_reviewed_claims():
    return setup_delivered_job_with_reviewed_claims(
        claim_specs=[
            {"claim_type": "IMPACT", "description": "Forklift puncture",
             "amount_claimed_cents": 250000},
            {"claim_type": "MOISTURE", "description": "Barrier failure, rust",
             "amount_claimed_cents": 250000},
        ],
        advance_clock_to="2026-08-25T00:00:00Z")


def test_impact_claim_caps_at_full_declared_value(api, claims_adjuster_headers):
    """PRD §3.9: "Approval computes `amount_approved_cents` as the lesser of the claimed amount and a cap that depends on the claim variant. For `IMPACT` and `TILT` claims the cap is the full `declared_value_cents` of the damaged crate's item."

    Design: Difficulty/dual_variant_calc/claim_settlement_declared_vs_depreciated_cap
    """
    _, claims = _setup_two_reviewed_claims()
    approved = validate_success(api.approve_claim(claims[0]["id"], claims_adjuster_headers), 200)
    assert_damage_claim(approved)
    assert approved["status"] == "APPROVED"
    assert approved["amount_approved_cents"] == 200000, "min(250000, 200000)"


def test_moisture_claim_cap_depreciates_per_whole_week(api, claims_adjuster_headers):
    """PRD §3.9: "For a `MOISTURE` claim the cap depreciates: the elapsed time from `delivered_at` to `filed_at` is reduced to whole days and then to whole weeks, the cap is the declared value multiplied by the larger of one half and one percent off per whole week — that is, the declared value scaled by one minus one hundredth per whole week since delivery, never falling below half — rounded half-up to whole cents."
    PRD §3.9: "The same claimed amount therefore yields a lower approved figure under `MOISTURE` than under `IMPACT` or `TILT` once a full week has passed".

    Design: Difficulty/dual_variant_calc/claim_settlement_declared_vs_depreciated_cap
    """
    _, claims = _setup_two_reviewed_claims()
    # Delivered at the 2026-08-01 startup clock; filed at 2026-08-25 ->
    # 24 whole days -> 3 whole weeks -> cap = 200000 * (1 - 0.03) = 194000.
    approved_impact = validate_success(api.approve_claim(claims[0]["id"], ADJ), 200)
    approved_moisture = validate_success(api.approve_claim(claims[1]["id"], claims_adjuster_headers), 200)
    assert approved_moisture["amount_approved_cents"] == 194000
    assert approved_moisture["amount_approved_cents"] != approved_impact["amount_approved_cents"], \
        "variant selection by claim_type diverges for identical claimed amounts"
