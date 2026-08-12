"""Cider products, label approvals, and license lifecycle rules."""
from test_helpers import (
    validate_success, validate_error, TEST_USERS, api_client,
    create_product_payload, create_label_approval_payload, create_license,
    create_packaging_run_payload, set_clock, setup_ready_batch,
)

CO = TEST_USERS["compliance_officer_headers"]
PO = TEST_USERS["packaging_operator_headers"]


def _create_product(**overrides):
    return validate_success(api_client.create_product(create_product_payload(**overrides), CO), 201)


def _create_label(product_id, **overrides):
    return validate_success(api_client.create_label_approval(
        product_id, create_label_approval_payload(**overrides), CO), 201)


# ─── Difficulty: non_linear_state_machine / product cycle ───────────────────

def test_product_retire_then_reactivate_cycle(api):
    """PRD section 3.4: "Retiring moves an `ACTIVE` product to `RETIRED` and is
    blocked while any packaging run for the product is `SCHEDULED` or any sales
    order for it sits in `DRAFT` or `CONFIRMED`. A retired product can be
    re-issued — `RETIRED` back to `ACTIVE` — provided its label approval is
    still `APPROVED` and unexpired."

    Design: Difficulty/non_linear_state_machine/product_status_cycle_retired_to_active
    """
    product = _create_product(sku="SM-2026-002", name="Semi-Dry Reserve",
                              style="SEMI_DRY", target_abv_pct=6.0)
    label = _create_label(product["id"], market="FEDERAL_TTB",
                          application_number="TTB-2026-002")
    validate_success(api_client.approve_label(label["id"], CO), 200)

    active = validate_success(api_client.activate_product(product["id"], CO), 200)
    assert active["status"] == "ACTIVE"

    retired = validate_success(api_client.retire_product(product["id"], CO), 200)
    assert retired["status"] == "RETIRED"

    reactivated = validate_success(api_client.activate_product(product["id"], CO), 200)
    assert reactivated["status"] == "ACTIVE", "cyclic re-entry RETIRED -> ACTIVE permitted"


def test_product_retire_from_draft_rejected(api):
    """PRD section 3.4: "Retiring moves an `ACTIVE` product to `RETIRED`" —
    retirement is defined only from `ACTIVE`.
    PRD section 2.9: "suitability of the target resource's state for the
    requested action (else `ERR_INVALID_STATE`)".

    Design: Difficulty/non_linear_state_machine/product_status_cycle_retired_to_active
    """
    product = _create_product(sku="SM-DRAFT-1", target_abv_pct=6.0)
    assert product["status"] == "DRAFT"
    res = api_client.retire_product(product["id"], CO)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Difficulty: transitive_cascade / label expiry cancels runs ─────────────

def _setup_run_referencing_label(market, label_expires_at):
    """READY batch + ACTIVE product (federal approved) + one APPROVED label on
    `market` expiring at `label_expires_at` + ACTIVE license + one SCHEDULED
    packaging run referencing that label. Returns context dict."""
    chain = setup_ready_batch(actual_juice_liters=50, measured_brix=13.0,
                              gravity_brix=4.0, ready_at="2026-10-15T00:00:00Z")
    product = _create_product(sku=f"P7-{market}", target_abv_pct=5.0)
    federal = _create_label(product["id"], market="FEDERAL_TTB",
                            application_number=f"TTB-{market}")
    validate_success(api_client.approve_label(federal["id"], CO), 200)
    if market == "FEDERAL_TTB":
        run_label = federal
    else:
        run_label = _create_label(product["id"], market=market,
                                  application_number=f"{market}-APP",
                                  expires_at=label_expires_at)
        validate_success(api_client.approve_label(run_label["id"], CO), 200)
    validate_success(api_client.activate_product(product["id"], CO), 200)
    license_ = create_license()
    run = validate_success(api_client.create_packaging_run(
        create_packaging_run_payload(product["id"], chain["batch"]["id"],
                                     run_label["id"], license_["id"],
                                     volume_liters=50), PO), 201)
    assert run["status"] == "SCHEDULED", "Setup failed: run not SCHEDULED"
    return {"chain": chain, "product": product, "label": run_label,
            "license": license_, "run": run}


def test_label_expiry_cascades_to_scheduled_run_cancellation(api):
    """PRD section 3.4: "Approvals age out automatically: when the logical clock
    passes `expires_at` on any market other than `FEDERAL_TTB` — federal COLAs
    do not auto-expire — the approval moves from `APPROVED` to `EXPIRED`, and
    any `SCHEDULED` packaging runs still referencing it are cancelled."

    An NY_SLA approval expiring 2026-11-01 is EXPIRED once the logical clock
    passes that instant, and the SCHEDULED run referencing it is CANCELLED.

    Design: Difficulty/transitive_cascade/label_expire_cascades_to_packaging_run_cancellation
    """
    ctx = _setup_run_referencing_label("NY_SLA", "2026-11-01T00:00:00Z")

    set_clock("2026-11-02T00:00:00Z")

    label_after = validate_success(api_client.get_label_approval(ctx["label"]["id"], CO), 200)
    assert label_after["status"] == "EXPIRED", "non-federal approval auto-expires"

    run_after = validate_success(api_client.get_packaging_run(ctx["run"]["id"], PO), 200)
    assert run_after["status"] == "CANCELLED", "expiry cancels referencing SCHEDULED runs"


def test_federal_label_does_not_auto_expire(api):
    """PRD section 3.4: "Approvals age out automatically: when the logical clock
    passes `expires_at` on any market other than `FEDERAL_TTB` — federal COLAs
    do not auto-expire — the approval moves from `APPROVED` to `EXPIRED`, and
    any `SCHEDULED` packaging runs still referencing it are cancelled."

    A FEDERAL_TTB approval whose expires_at has passed remains APPROVED, and
    the SCHEDULED run referencing it is untouched.

    Design: Difficulty/transitive_cascade/label_expire_cascades_to_packaging_run_cancellation
    """
    chain = setup_ready_batch(actual_juice_liters=50, measured_brix=13.0,
                              gravity_brix=4.0, ready_at="2026-10-15T00:00:00Z")
    product = _create_product(sku="P7-FED", target_abv_pct=5.0)
    federal = _create_label(product["id"], market="FEDERAL_TTB",
                            application_number="TTB-FED-NEAR",
                            expires_at="2026-11-01T00:00:00Z")
    validate_success(api_client.approve_label(federal["id"], CO), 200)
    validate_success(api_client.activate_product(product["id"], CO), 200)
    license_ = create_license()
    run = validate_success(api_client.create_packaging_run(
        create_packaging_run_payload(product["id"], chain["batch"]["id"],
                                     federal["id"], license_["id"],
                                     volume_liters=50), PO), 201)

    set_clock("2026-12-01T00:00:00Z")  # past the federal label's expires_at

    label_after = validate_success(api_client.get_label_approval(federal["id"], CO), 200)
    assert label_after["status"] == "APPROVED", "federal COLAs do not auto-expire"

    run_after = validate_success(api_client.get_packaging_run(run["id"], PO), 200)
    assert run_after["status"] == "SCHEDULED", "no cascade for federal labels"


# ─── Corner: state machines / labels ────────────────────────────────────────

def test_label_resubmit_rejected_to_submitted_cycle(api):
    """PRD section 3.4: "Approval requires a non-empty `application_number` and
    stamps `approved_at`; rejection moves the filing to `REJECTED`, and
    resubmission returns a `REJECTED` filing to `SUBMITTED` with an updated
    `application_number` and a fresh `submitted_at`."

    Design: Corner/state_machines/label_resubmit_rejected_to_submitted_cycle
    """
    product = _create_product(sku="RE-001", name="Re")
    label = _create_label(product["id"], market="FEDERAL_TTB",
                          application_number="TTB-RE-1")
    rejected = validate_success(api_client.reject_label(label["id"], CO), 200)
    assert rejected["status"] == "REJECTED"

    resubmitted = validate_success(api_client.resubmit_label(
        label["id"], {"application_number": "TTB-RE-2"}, CO), 200)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["application_number"] == "TTB-RE-2"


def test_label_terminal_approved_no_reject(api):
    """PRD section 3.4: "rejection moves the filing to `REJECTED`" — rejection
    is defined for a `SUBMITTED` filing, not an `APPROVED` one.
    PRD section 2.9: "suitability of the target resource's state for the
    requested action (else `ERR_INVALID_STATE`)".

    Design: Corner/state_machines/label_terminal_approved_no_reject
    """
    product = _create_product(sku="AP-001", name="Ap")
    label = _create_label(product["id"], market="FEDERAL_TTB",
                          application_number="TTB-AP-1")
    approved = validate_success(api_client.approve_label(label["id"], CO), 200)
    assert approved["status"] == "APPROVED"

    res = api_client.reject_label(label["id"], CO)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner: validations / uniqueness ───────────────────────────────────────

def test_duplicate_sku_rejected(api):
    """PRD section 3.4: "a `ComplianceOfficer` with a unique `sku` (a duplicate
    is rejected with `ERR_DUPLICATE_SKU`)".

    Design: Corner/validations/duplicate_sku_rejected
    """
    _create_product(sku="DUP-001", name="First", target_abv_pct=5.0)
    res = api_client.create_product(
        create_product_payload(sku="DUP-001", name="Second", style="SWEET",
                               target_abv_pct=6.0), CO)
    validate_error(res, "ERR_DUPLICATE_SKU")


def test_duplicate_label_market_rejected(api):
    """PRD section 3.4: "The market is one of `FEDERAL_TTB`, `NY_SLA`, `VT_DLL`,
    or `MA_ABCC`, and exactly one approval may exist per product and market — a
    duplicate is rejected with `ERR_DUPLICATE_LABEL_MARKET`."

    Design: Corner/validations/duplicate_label_market_rejected
    """
    product = _create_product(sku="DL-001", name="DL")
    _create_label(product["id"], market="NY_SLA", application_number="NY-1",
                  expires_at="2027-12-31T23:59:59Z")
    res = api_client.create_label_approval(
        product["id"],
        create_label_approval_payload(market="NY_SLA", application_number="NY-2",
                                      expires_at="2027-12-31T23:59:59Z"), CO)
    validate_error(res, "ERR_DUPLICATE_LABEL_MARKET")
