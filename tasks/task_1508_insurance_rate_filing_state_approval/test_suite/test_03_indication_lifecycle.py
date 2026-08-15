"""Indication review cycle, locking, segregation of duties, and OCC (PRD §3.2, §2.7)."""
from test_helpers import (
    ApiErrorId,
    create_indication,
    create_indication_payload,
    create_product,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


def test_return_increments_review_round(api):
    """PRD §3.2: "a fresh indication carries `review_round` 1."
    PRD §3.2: "Returning the indication sends it from `IN_ACTUARIAL_REVIEW`
    back to `DRAFT` and increments `review_round` by one, so the revision loop
    `DRAFT` → `IN_ACTUARIAL_REVIEW` → `DRAFT` may repeat as many times as the
    work requires."

    Design: Difficulty/non_linear_state_machine/indication_review_return_revision_cycle
    """
    product = create_product()
    indication = create_indication(product["id"], product["version"])
    assert indication["review_round"] == 1

    get_success_data(api.submit_indication_review(indication["id"], fx.ACT1))
    returned = validate_success(api.return_indication(indication["id"], fx.ACT2), 200)
    assert returned["status"] == "DRAFT"
    assert returned["review_round"] == 2


def test_revision_cycle_completes_to_locked(api):
    """PRD §3.2: "The preparer submits the draft for actuarial review, moving
    it from `DRAFT` to `IN_ACTUARIAL_REVIEW`. A `ProductActuary` then either
    approves or returns it."
    PRD §3.2: "An approved indication becomes the legal basis for filings only
    when a `ProductActuary` locks it, moving it from `APPROVED` to `LOCKED`."

    Design: Difficulty/non_linear_state_machine/indication_review_return_revision_cycle
    """
    product = create_product()
    indication = create_indication(product["id"], product["version"])

    get_success_data(api.submit_indication_review(indication["id"], fx.ACT1))
    get_success_data(api.return_indication(indication["id"], fx.ACT2))
    get_success_data(api.submit_indication_review(indication["id"], fx.ACT1))
    get_success_data(api.approve_indication(indication["id"], fx.ACT2))
    locked = validate_success(api.lock_indication(indication["id"], fx.ACT2), 200)

    assert locked["status"] == "LOCKED"
    assert locked["review_round"] == 2


def test_lock_supersedes_prior_locked_indication(api):
    """PRD §3.2: "Locking is exclusive within a scope: any other `LOCKED`
    indication for the same product and scope instantly becomes `SUPERSEDED`,
    the indication's terminal state. When the locked indication is countrywide
    (its `scope_state_code` is null), the lock additionally points the
    product's `current_locked_indication_id` at the newly locked indication
    and advances the product's `version` by one."

    Design: Corner/state_machines/indication_lock_supersedes_prior_locked
    """
    product = create_product()
    first = create_indication(product["id"], product["version"])
    fx.walk_indication_to_locked(first["id"])

    product = get_success_data(api.get_product(product["id"], fx.ACT1))
    assert product["current_locked_indication_id"] == first["id"]

    second = create_indication(
        product["id"], product["version"], variant="PAID_PURE"
    )
    get_success_data(api.submit_indication_review(second["id"], fx.ACT1))
    get_success_data(api.approve_indication(second["id"], fx.ACT2))
    locked_second = validate_success(api.lock_indication(second["id"], fx.ACT2), 200)
    assert locked_second["status"] == "LOCKED"

    first_after = get_success_data(api.get_indication(first["id"], fx.ACT1))
    assert first_after["status"] == "SUPERSEDED"

    product_after = get_success_data(api.get_product(product["id"], fx.ACT1))
    assert product_after["current_locked_indication_id"] == second["id"]


def test_self_approval_rejected_by_segregation_of_duties(api):
    """PRD §3.2: "Approval moves the indication to `APPROVED` and records the
    approver's identity as `approved_by_user_id` — but segregation of duties
    is enforced: the approver's `X-User-ID` must differ from
    `prepared_by_user_id`, and a self-approval attempt is rejected with
    `ERR_SOD_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/sod_self_approval_rejected
    """
    product = create_product()
    indication = create_indication(product["id"], product["version"])
    get_success_data(api.submit_indication_review(indication["id"], fx.ACT1))

    # act-1 prepared it; act-1 cannot approve it.
    res = api.approve_indication(indication["id"], fx.ACT1)
    validate_error(res, ApiErrorId.ERR_SOD_VIOLATION)

    approved = validate_success(api.approve_indication(indication["id"], fx.ACT2), 200)
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "act-2"


def test_indication_create_stale_product_version_rejected(api):
    """PRD §2.7: "Creating a rate indication requires `expected_product_version`,
    carrying the version of the parent Product the client last observed. If the
    product's current `version` has advanced since that observation — for
    example because another indication was created against the product or a
    countrywide indication was locked, both of which advance the product's
    book-of-record version — the create is rejected with `ERR_STALE_VERSION`
    (HTTP 412)".

    Design: Corner/cross_cutting_layers/occ_indication_create_stale_then_fresh
    """
    product = create_product()
    stale_version = product["version"]
    first = create_indication(product["id"], stale_version)
    assert first["status"] == "DRAFT"

    # The first create advanced the product's version, so replaying it is stale.
    res = api.create_indication(
        create_indication_payload(
            product["id"],
            stale_version,
            variant="PAID_PURE",
            earned_premium_cents=9_000_000,
            incurred_loss_cents=6_000_000,
            paid_loss_cents=5_500_000,
            exposure_units=400,
            trend_factor=0.03,
            countrywide_change_pct=0.05,
        ),
        fx.ACT1,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    product_after = get_success_data(api.get_product(product["id"], fx.ACT1))
    assert product_after["version"] == stale_version + 1

    # Re-reading the product and sending its fresh version succeeds.
    second = validate_success(
        api.create_indication(
            create_indication_payload(
                product["id"],
                product_after["version"],
                variant="PAID_PURE",
                earned_premium_cents=9_000_000,
                incurred_loss_cents=6_000_000,
                paid_loss_cents=5_500_000,
                exposure_units=400,
                trend_factor=0.03,
                countrywide_change_pct=0.05,
            ),
            fx.ACT1,
        ),
        201,
    )
    assert second["status"] == "DRAFT"
