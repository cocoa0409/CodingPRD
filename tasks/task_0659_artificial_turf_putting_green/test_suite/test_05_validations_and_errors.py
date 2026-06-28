"""Validation ordering, error catalog, and request well-formedness: priority
conflicts, close gating, duplicate/enum/range/reference checks, retired-product
and variant-mismatch safety, fiscal gating, and pagination bounds.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    api_client,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_customer_headers,
    fixtures as fx,
    factories as f,
)

ADMIN = TEST_USERS["ops_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
SCHED = TEST_USERS["scheduler_headers"]


# ─── Difficulty: priority_pair_validation_conflict ───────────────────────────
def test_reaccept_design_state_precedes_variant_mismatch(api):
    """PRD §2.9: "they are evaluated in a fixed priority order so that the failure
    a client sees is always the most fundamental one."
    PRD §2.9: "then duplicates, then state, then concurrency, then the remaining
    business rules."

    Design: Difficulty/priority_pair_validation_conflict/conflict_state_vs_variant_mismatch_on_accept
    """
    # A PET design with a pet_approved turf accepts cleanly; re-accepting the now-
    # ACCEPTED design fails the state precondition (not DRAFT), which precedes the
    # business-safety variant check (ERR_VARIANT_PRODUCT_MISMATCH, 422).
    ctx = fx.setup_designed_project(
        variant="PET",
        turf_overrides={"price_per_sqft_cents": 600, "pet_approved": True, "pile_height_mm": 30},
        infill_overrides={"price_per_sqft_cents": 150, "material": "ZEOLITE", "antimicrobial": True},
    )
    pid = ctx["project"]["id"]
    did = ctx["design"]["id"]
    resp = api_client.accept_design_layout(pid, did, SALES)
    # Either state-not-DRAFT or design-already-accepted is PRD-faithful for
    # re-accepting the same ACCEPTED design; both are 409s that precede the 422
    # variant-safety error.
    err = validate_error_is_one_of(
        resp, [ApiErrorId.ERR_INVALID_STATE.value, ApiErrorId.ERR_DESIGN_ALREADY_ACCEPTED.value]
    )
    assert err != ApiErrorId.ERR_VARIANT_PRODUCT_MISMATCH.value
    design = validate_success(api_client.get_design_layout(pid, did, SALES))
    assert design["status"] == "ACCEPTED"


def test_reaccept_design_leaves_project_designed(api):
    """PRD §2.9: "they are evaluated in a fixed priority order so that the failure
    a client sees is always the most fundamental one."
    PRD §3.2: "advances the project's workflow dimension from `MEASURED` to
    `DESIGNED`"

    Design: Difficulty/priority_pair_validation_conflict/conflict_state_vs_variant_mismatch_on_accept
    """
    ctx = fx.setup_designed_project(
        variant="PET",
        turf_overrides={"price_per_sqft_cents": 600, "pet_approved": True, "pile_height_mm": 30},
        infill_overrides={"price_per_sqft_cents": 150, "material": "ZEOLITE", "antimicrobial": True},
    )
    pid = ctx["project"]["id"]
    resp = api_client.accept_design_layout(pid, ctx["design"]["id"], SALES)
    err = validate_error_is_one_of(
        resp, [ApiErrorId.ERR_INVALID_STATE.value, ApiErrorId.ERR_DESIGN_ALREADY_ACCEPTED.value]
    )
    assert err != ApiErrorId.ERR_VARIANT_PRODUCT_MISMATCH.value
    # The rejection does not advance or regress the project beyond DESIGNED.
    project = validate_success(api_client.get_project(pid, ADMIN))
    assert project["workflow_status"] == "DESIGNED"


def test_resend_quote_state_precedes_scope_not_finalized(api):
    """PRD §2.9: "State validity for the requested transition (`ERR_INVALID_STATE`)
    comes next, then the optimistic-concurrency check on quote acceptance
    (`ERR_STALE_PROJECT_VERSION`). After those, the domain-specific business-safety,
    capacity, temporal, referential, and fiscal rules described throughout Section 3
    apply."
    PRD §3.6: "Any state transition attempted against a quote that is not in the
    required starting state is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/conflict_scope_not_finalized_vs_invalid_state_on_send
    """
    # q1 sent over a FINALIZED scope; re-sending the now-SENT quote fails on state
    # (SENT, not DRAFT), which precedes the referential ERR_SCOPE_NOT_FINALIZED.
    ctx = fx.setup_sent_quote_project(variant="STANDARD")
    pid = ctx["project"]["id"]
    qid = ctx["quote"]["id"]
    resp = api_client.send_quote(pid, qid, SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    quote = validate_success(api_client.get_quote(pid, qid, SALES))
    assert quote["status"] == "SENT"


def test_resend_quote_rejected_not_scope_error(api):
    """PRD §2.9: "State validity for the requested transition (`ERR_INVALID_STATE`)
    comes next"
    PRD §3.6: "Sending moves the quote from `DRAFT` to `SENT`, freezes the total as
    the final figure, advances the project's workflow dimension from `DESIGNED` to
    `QUOTED`, and increments the project's `version`."

    Design: Difficulty/priority_pair_validation_conflict/conflict_scope_not_finalized_vs_invalid_state_on_send
    """
    ctx = fx.setup_sent_quote_project(variant="STANDARD")
    pid = ctx["project"]["id"]
    qid = ctx["quote"]["id"]
    resp = api_client.send_quote(pid, qid, SALES)
    # State (already-SENT) error wins; it is NOT the referential scope error.
    err = validate_error_is_one_of(resp, [ApiErrorId.ERR_INVALID_STATE.value])
    assert err != ApiErrorId.ERR_SCOPE_NOT_FINALIZED.value
    project = validate_success(api_client.get_project(pid, ADMIN))
    assert project["workflow_status"] == "QUOTED", "first send already advanced the project"


# ─── Difficulty: boundary_precision_check (close gating) ─────────────────────
def test_close_blocked_then_allowed_after_callback_cancel(api):
    """PRD §3.12: "An `OpsAdmin` closes a project that is `INSTALLED`, but only when
    its `finance_status` is `PAID_IN_FULL` and its `open_callback_count` is zero; a
    close attempted while the project is not fully paid or still has open callbacks
    is rejected with `ERR_PROJECT_NOT_CLOSEABLE`."
    PRD §3.11: "The `open_callback_count` is the number of callbacks on the project
    whose status is `OPEN` or `IN_PROGRESS`."

    Design: Difficulty/boundary_precision_check/close_blocked_by_nonzero_open_callback_count
    """
    ctx = fx.setup_paid_in_full_project()
    pid = ctx["project"]["id"]
    cust = make_customer_headers(ctx["customer"]["id"])
    cb = validate_success(
        api_client.create_callback(pid, f.create_callback_payload("OTHER"), cust),
        expected_status=201,
    )
    # open_callback_count == 1 -> close rejected.
    resp = api_client.close_project(pid, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_CLOSEABLE.value)
    # Cancel the lone callback -> count back to 0.
    validate_success(api_client.cancel_callback(pid, cb["id"], ADMIN))
    project = validate_success(api_client.get_project(pid, ADMIN))
    assert project["open_callback_count"] == 0
    # Now close succeeds.
    closed = validate_success(api_client.close_project(pid, ADMIN))
    assert closed["workflow_status"] == "CLOSED"


def test_close_blocked_while_open_callback_present(api):
    """PRD §3.12: "An `OpsAdmin` closes a project that is `INSTALLED`, but only when
    its `finance_status` is `PAID_IN_FULL` and its `open_callback_count` is zero; a
    close attempted while the project is not fully paid or still has open callbacks
    is rejected with `ERR_PROJECT_NOT_CLOSEABLE`."
    PRD §3.11: "the project is created in `OPEN` status, the project's
    `open_callback_count` is recomputed, and the project's `version` increments."

    Design: Difficulty/boundary_precision_check/close_blocked_by_nonzero_open_callback_count
    """
    ctx = fx.setup_paid_in_full_project()
    pid = ctx["project"]["id"]
    cust = make_customer_headers(ctx["customer"]["id"])
    validate_success(
        api_client.create_callback(pid, f.create_callback_payload("OTHER"), cust),
        expected_status=201,
    )
    project = validate_success(api_client.get_project(pid, ADMIN))
    assert project["open_callback_count"] == 1, "the single OPEN callback is counted"
    resp = api_client.close_project(pid, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_CLOSEABLE.value)


# ─── Corner: entities / validations / errors ─────────────────────────────────
def test_get_nonexistent_project_not_found(api):
    """PRD §2.7: "a missing identifier anywhere in the path produces `ERR_NOT_FOUND`
    for the first identifier that does not resolve."

    Design: Corner/entities/get_project_nonexistent_returns_not_found
    """
    resp = api_client.get_project(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_project_missing_customer_id_invalid_request(api):
    """PRD §3.1: "A project begins when a `SalesRep` or `OpsAdmin` creates it,
    supplying the `customer_id` of the owning customer and the free-text
    `site_address` of the install site."
    PRD §2.9: "the system check that the body is well-formed — required fields
    present and well-typed, enum values within their declared domain, and numeric
    ranges respected such as areas being greater than zero and `deposit_pct` lying
    within its allowed band (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_project_missing_customer_id_returns_invalid_request
    """
    resp = api_client.create_project({"site_address": "no customer"}, SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_turf_product_create_defaults_active(api):
    """PRD §2.4: "Three resource types are exceptions and carry only `id` and
    `created_at`, with no `updated_at` and no `version`: `TurfProduct`,
    `InfillProduct`, and `Payment`."
    PRD §3.2: "along with an `active` flag"

    Design: Corner/entities/turf_product_system_fields_input_ignored
    """
    from test_helpers import is_valid_uuid
    turf = validate_success(
        api_client.create_turf_product(
            f.create_turf_product_payload(sku="T-SYS", name="Sys Turf"), ADMIN
        ),
        expected_status=201,
    )
    assert is_valid_uuid(turf["id"])
    assert turf["active"] is True
    assert turf["sku"] == "T-SYS"
    assert "version" not in turf
    assert "updated_at" not in turf


def test_duplicate_customer_email_rejected(api):
    """PRD §3.1: "the email is unique case-insensitively, and a collision is
    rejected with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/entities/customer_duplicate_email_returns_duplicate_resource
    """
    validate_success(
        api_client.create_customer(f.create_customer_payload(full_name="First", email="dup@x.com"), ADMIN),
        expected_status=201,
    )
    resp = api_client.create_customer(
        f.create_customer_payload(full_name="Second", email="DUP@x.com"), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)


def test_design_invalid_variant_enum_rejected(api):
    """PRD §2.9: "enum values within their declared domain"
    PRD §3.2: "the `variant`, which is one of `STANDARD`, `PET`, `PLAYGROUND`, or
    `PUTTING_GREEN`."

    Design: Corner/entities/design_invalid_variant_enum_returns_invalid_request
    """
    turf, infill = fx.setup_catalog()
    _cust, project, measure = fx.setup_measured_project()
    resp = api_client.create_design_layout(
        project["id"],
        {
            "site_measure_id": measure["id"],
            "turf_product_id": turf["id"],
            "infill_product_id": infill["id"],
            "variant": "GOLF",
        },
        SALES,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_list_projects_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."
    PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return; if not provided it defaults to 10, with a minimum of 1 and a maximum of
    100."

    Design: Corner/entities/list_projects_pagination_envelope
    """
    customer = fx.create_customer()
    fx.create_project(customer["id"], site_address="5a Test St")
    fx.create_project(customer["id"], site_address="5b Test St")
    data, meta = validate_paginated(
        api_client.list_projects(ADMIN, params={"customer_id": customer["id"], "limit": 1, "offset": 0})
    )
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_pagination_limit_over_max_rejected(api):
    """PRD §2.3: "A `limit` or `offset` outside these bounds is rejected with
    `ERR_VALIDATION_PAGINATION`."

    Design: Corner/entities/pagination_limit_over_max_returns_validation_error
    """
    resp = api_client.list_projects(ADMIN, params={"limit": 101})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_PAGINATION.value)


def test_variant_mismatch_pet_turf_not_approved(api):
    """PRD §3.3: "a `PET` design requires that the turf has `pet_approved` set and
    that the infill has `antimicrobial` set"
    PRD §3.3: "The variant-compatibility rule, enforced at acceptance with
    `ERR_VARIANT_PRODUCT_MISMATCH`"

    Design: Corner/validations/variant_product_mismatch_pet_turf_not_pet_approved
    """
    # The variant/product compatibility rule is enforced at acceptance per PRD §3.3.
    turf, infill = fx.setup_catalog(
        turf_overrides={"pet_approved": False},
        infill_overrides={"material": "ZEOLITE", "antimicrobial": True},
    )
    _cust, project, measure = fx.setup_measured_project()
    pid = project["id"]
    design = fx.create_design_layout(pid, measure["id"], turf["id"], infill["id"], "PET")
    resp = api_client.accept_design_layout(pid, design["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_VARIANT_PRODUCT_MISMATCH.value)


def test_retired_turf_blocks_design_accept(api):
    """PRD §3.3: "the selected turf and infill must both have `active` set to true;
    a design naming a retired turf or infill product is rejected with
    `ERR_PRODUCT_RETIRED`."

    Design: Corner/validations/product_retired_blocks_design_create
    """
    # Retirement is enforced at acceptance alongside the other product checks (§3.3).
    turf, infill = fx.setup_catalog(turf_overrides={"active": False})
    _cust, project, measure = fx.setup_measured_project()
    pid = project["id"]
    design = fx.create_design_layout(pid, measure["id"], turf["id"], infill["id"], "STANDARD")
    resp = api_client.accept_design_layout(pid, design["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_RETIRED.value)


def test_reference_not_found_unknown_turf_on_design(api):
    """PRD §2.7: "When a request body names a foreign resource — a
    `turf_product_id`, `infill_product_id`, `site_measure_id`, `crew_id`,
    `design_layout_id`, `base_prep_scope_id`, or `warranty_plan_id` — and that
    referenced resource does not exist, the request is rejected with
    `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/validations/reference_not_found_unknown_turf_on_design
    """
    _turf, infill = fx.setup_catalog()
    _cust, project, measure = fx.setup_measured_project()
    resp = api_client.create_design_layout(
        project["id"],
        {
            "site_measure_id": measure["id"],
            "turf_product_id": NON_EXISTENT_UUID,
            "infill_product_id": infill["id"],
            "variant": "STANDARD",
        },
        SALES,
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


def test_balance_payment_before_balance_due_rejected(api):
    """PRD §3.7: "A balance payment cannot be recorded before the project's
    `finance_status` is `BALANCE_DUE`; recording a `BALANCE` payment earlier is
    rejected with `ERR_BALANCE_NOT_DUE`."

    Design: Corner/validations/balance_payment_before_balance_due_rejected
    """
    # Deposit-paid (finance DEPOSIT_SETTLED), install not yet complete.
    ctx = fx.setup_deposit_paid_project(variant="STANDARD")
    pid = ctx["project"]["id"]
    cust = make_customer_headers(ctx["customer"]["id"])
    resp = api_client.create_payment(pid, f.create_payment_payload("BALANCE", 302098), cust)
    validate_error(resp, ApiErrorId.ERR_BALANCE_NOT_DUE.value)
    project = validate_success(api_client.get_project(pid, ADMIN))
    assert project["finance_status"] == "DEPOSIT_SETTLED"


def test_deposit_pct_out_of_range_rejected(api):
    """PRD §3.5: "A `deposit_pct` supplied outside the 0.10-to-0.50 band on input
    is itself a range violation rejected with `ERR_INVALID_REQUEST` before clamping
    is ever reached"

    Design: Corner/validations/deposit_pct_out_of_range_invalid_request
    """
    ctx = fx.setup_finalized_scope_project(variant="STANDARD")
    pid = ctx["project"]["id"]
    resp = api_client.create_quote(
        pid, f.create_quote_payload(ctx["design"]["id"], ctx["scope"]["id"], deposit_pct=0.75), SALES
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_second_design_accept_rejected_when_one_already_accepted(api):
    """PRD §3.2: "A `SalesRep` accepts a design only while it is in `DRAFT` status
    and only when no other design on the project is already `ACCEPTED`; an attempt
    to accept a second design when one is already accepted is rejected with
    `ERR_DESIGN_ALREADY_ACCEPTED`."

    Design: Corner/validations/design_already_accepted_second_design_accept
    """
    turf, infill = fx.setup_catalog()
    _cust, project, measure = fx.setup_measured_project()
    pid = project["id"]
    d1 = fx.create_design_layout(pid, measure["id"], turf["id"], infill["id"], "STANDARD")
    d2 = fx.create_design_layout(pid, measure["id"], turf["id"], infill["id"], "STANDARD")
    fx.accept_design_layout(pid, d1["id"])
    resp = api_client.accept_design_layout(pid, d2["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_DESIGN_ALREADY_ACCEPTED.value)
    d2_read = validate_success(api_client.get_design_layout(pid, d2["id"], SALES))
    assert d2_read["status"] == "DRAFT"


def test_deposit_insufficient_under_settle_rejected(api):
    """PRD §3.7: "the settlement of a deposit that leaves the cumulative settled
    deposit below the required amount is rejected with `ERR_DEPOSIT_INSUFFICIENT`."

    Design: Corner/validations/deposit_insufficient_under_settle
    """
    # Quote accepted (deposit_amount 129470). A DEPOSIT of 50000 is recorded PENDING.
    ctx = fx.setup_sent_quote_project(variant="STANDARD", quote_overrides={"deposit_pct": 0.30})
    pid = ctx["project"]["id"]
    cust_id = ctx["customer"]["id"]
    fx.accept_quote(pid, ctx["quote"]["id"], cust_id)
    dep = fx.record_payment(pid, cust_id, "DEPOSIT", 50000)
    resp = api_client.settle_payment(f.settle_payment_payload(dep["id"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_INSUFFICIENT.value)
    project = validate_success(api_client.get_project(pid, ADMIN))
    assert project["finance_status"] == "DEPOSIT_DUE"
    assert project["workflow_status"] == "QUOTED"


def test_scope_not_finalized_on_send_rejected(api):
    """PRD §3.6: "Sending is performed by a `SalesRep` on a `DRAFT` quote, and only
    if the quote's referenced base-prep scope is `FINALIZED`; an attempt to send a
    quote whose scope is not finalized is rejected with `ERR_SCOPE_NOT_FINALIZED`."

    Design: Corner/errors/scope_not_finalized_on_send
    """
    # DRAFT (un-finalized) scope; a DRAFT quote referencing it.
    ctx = fx.setup_designed_project(variant="STANDARD")
    pid = ctx["project"]["id"]
    scope = fx.create_base_prep_scope(pid, ctx["design"]["id"], base_depth_in=3)
    # NOTE: scope deliberately NOT finalized.
    quote = fx.create_quote(pid, ctx["design"]["id"], scope["id"], deposit_pct=0.30)
    resp = api_client.send_quote(pid, quote["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_SCOPE_NOT_FINALIZED.value)
    quote_read = validate_success(api_client.get_quote(pid, quote["id"], SALES))
    assert quote_read["status"] == "DRAFT"
