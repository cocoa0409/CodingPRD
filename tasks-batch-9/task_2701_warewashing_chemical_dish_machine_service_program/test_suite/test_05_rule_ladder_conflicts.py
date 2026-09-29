"""
Rungs of the ladder proved by simultaneous violations plus a control.

Each pair stages two rules that both genuinely fail, asserts the higher rung is
what the caller sees, then removes only the winning cause and shows the very
same request now reports the loser.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_CUSTOMER_CREDIT_HOLD,
    ERR_INSUFFICIENT_TELEMETRY,
    ERR_SITE_POSTURE_CRITICAL,
)
from test_helpers.assertions import assert_equipment_ledger
from test_helpers.test_users import (
    ACCOUNT_MANAGER_HEADERS,
    AUDITOR_1_HEADERS,
    AUDITOR_2_HEADERS,
)
from test_helpers.types import (
    AGREEMENT_DRAFT,
    BILLING_CREDIT_HOLD,
    CLASS_INSUFFICIENT_DATA,
    POSTURE_CRITICAL,
    POSTURE_NORMAL,
    REVIEW_DRAFT,
)

PLACEMENT_ASSET_TAG = "AT-701"


def _credit_hold_account_with_draft_agreement(api):
    """
    A CREDIT_HOLD customer whose agreement was never activated, so a placement
    create violates both the state rule and the fiscal rule at once.
    """
    base = X.program_base(
        api,
        customer_overrides={"billing_status": BILLING_CREDIT_HOLD},
        activate=False,
    )
    assert base["customer"]["billing_status"] == BILLING_CREDIT_HOLD
    assert base["agreement"]["status"] == AGREEMENT_DRAFT
    return base


def _place_machine(api, base, version):
    return api.create_machine_placement(
        F.machine_placement_payload(
            base["site_id"],
            base["agreement_id"],
            base["model_id"],
            version,
            asset_tag=PLACEMENT_ASSET_TAG,
        ),
        ACCOUNT_MANAGER_HEADERS,
    )


def test_draft_agreement_outranks_the_customer_credit_hold(api):
    """
    A DRAFT agreement and a CREDIT_HOLD account both block the same placement,
    and the caller sees the rung-9 state error rather than the rung-15 fiscal one.
    The version token is the agreement's true current version, so the rung-8
    stale-parent rule cannot mask the pair.

    PRD §2.8: "15. **Fiscal standing** — `ERR_CUSTOMER_CREDIT_HOLD` (402). This
    is the lowest rung in the whole ladder: a credit hold is reported only when
    the request is otherwise entirely valid."

    Design: Difficulty/priority_pair_validation_conflict/placement_agreement_state_error_outranks_credit_hold
    """
    base = _credit_hold_account_with_draft_agreement(api)

    validate_error(
        _place_machine(api, base, base["agreement"]["version"]),
        ERR_AGREEMENT_NOT_ACTIVE,
        409,
    )

    rows, _meta = validate_paginated(
        api.list_machine_placements(
            ACCOUNT_MANAGER_HEADERS, {"site_id": base["site_id"], "limit": 100}
        )
    )
    assert rows == []

    customer = get_success_data(
        api.get_customer(base["customer_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_equipment_ledger(customer, 0)
    agreement = get_success_data(
        api.get_service_agreement(base["agreement_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert agreement["placement_count"] == 0


def test_credit_hold_surfaces_once_the_agreement_is_active(api):
    """
    Activating the agreement is the only change, and the byte-identical placement
    request then reports the 402 credit hold — proof the fiscal rule was violated
    all along and was merely outranked.

    PRD §3.3: "and finally the customer's `billing_status` must be `CURRENT`,
    with a `CREDIT_HOLD` account refused with `ERR_CUSTOMER_CREDIT_HOLD` only
    once everything else about the request has passed."

    Design: Difficulty/priority_pair_validation_conflict/placement_agreement_state_error_outranks_credit_hold
    """
    base = _credit_hold_account_with_draft_agreement(api)

    validate_error(
        _place_machine(api, base, base["agreement"]["version"]),
        ERR_AGREEMENT_NOT_ACTIVE,
        409,
    )

    activated = X.activate_agreement(api, base["agreement_id"])
    validate_error(
        _place_machine(api, base, activated["version"]),
        ERR_CUSTOMER_CREDIT_HOLD,
        402,
    )

    rows, _meta = validate_paginated(
        api.list_machine_placements(
            ACCOUNT_MANAGER_HEADERS, {"site_id": base["site_id"], "limit": 100}
        )
    )
    assert rows == []
    customer = get_success_data(
        api.get_customer(base["customer_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_equipment_ledger(customer, 0)


def _critical_posture_with_empty_window(api):
    """
    A kitchen whose posture is CRITICAL from a 700-point auto-ticket, plus a
    DRAFT review over [2026-08-01, 2026-08-04) which sits strictly before the
    only reading, so its classification is INSUFFICIENT_DATA.
    """
    base = X.program_base(api)
    placement = X.installed_placement(api, base, asset_tag="AT-801")
    X.fit_dispenser(api, base, placement["id"], dose=8.00)

    X.set_clock(api, "2026-08-05T14:00:00Z")
    X.ingest_reading(
        api, placement["id"], "2026-08-05T14:00:00Z", 600, rinse_pressure_psi=11
    )

    site = get_success_data(api.get_site(base["site_id"], AUDITOR_1_HEADERS))
    assert site["service_posture"] == POSTURE_CRITICAL

    review = X.draft_review(
        api,
        base,
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-04T00:00:00Z",
        opening_inventory_ml=0,
        ending_inventory_ml=0,
    )
    assert review["rack_count_in_period"] == 0
    assert review["expected_consumption_ml"] == 0
    assert review["classification"] == CLASS_INSUFFICIENT_DATA

    base.update({"placement_id": placement["id"], "review_id": review["id"]})
    return base


def test_critical_posture_outranks_insufficient_telemetry_on_publish(api):
    """
    The publish request violates both the safety rule and the telemetry
    constraint, and the caller sees the rung-11 posture error rather than the
    rung-13 telemetry one.

    PRD §2.8: "Publishing a variance review checks, in this order: that the
    review is still `DRAFT` (`ERR_REVIEW_NOT_DRAFT`), then that the publishing
    auditor is not the drafting auditor (`ERR_SEGREGATION_OF_DUTIES`), then that
    the site's posture is not `CRITICAL` (`ERR_SITE_POSTURE_CRITICAL`), then that
    the window carried usable telemetry (`ERR_INSUFFICIENT_TELEMETRY`), and only
    then that the window does not collide with another live review of the same
    kitchen and product (`ERR_REVIEW_PERIOD_OVERLAP`)."

    Design: Difficulty/priority_pair_validation_conflict/publish_safety_posture_error_outranks_insufficient_telemetry
    """
    base = _critical_posture_with_empty_window(api)

    validate_error(
        api.publish_usage_variance_review(base["review_id"], AUDITOR_2_HEADERS),
        ERR_SITE_POSTURE_CRITICAL,
        409,
    )

    review = get_success_data(
        api.get_usage_variance_review(base["review_id"], AUDITOR_1_HEADERS)
    )
    assert review["status"] == REVIEW_DRAFT
    assert review["published_by_user_id"] is None


def test_telemetry_constraint_surfaces_once_the_backlog_is_cleared(api):
    """
    Raising a retrieval order cancels the QUEUED auto-ticket and drops the
    posture back to NORMAL without touching the review; the identical publish
    then reports the 422 telemetry constraint.

    PRD §3.7: "And the window must carry usable telemetry: a review whose
    `classification` came out `INSUFFICIENT_DATA`, equivalently one whose
    `rack_count_in_period` or `expected_consumption_ml` is 0, is refused with
    `ERR_INSUFFICIENT_TELEMETRY`."

    Design: Difficulty/priority_pair_validation_conflict/publish_safety_posture_error_outranks_insufficient_telemetry
    """
    base = _critical_posture_with_empty_window(api)

    validate_error(
        api.publish_usage_variance_review(base["review_id"], AUDITOR_2_HEADERS),
        ERR_SITE_POSTURE_CRITICAL,
        409,
    )

    validate_success(
        api.create_retrieval_order(
            base["placement_id"],
            ACCOUNT_MANAGER_HEADERS,
            F.retrieval_order_payload("2026-09-15"),
        )
    )
    site = get_success_data(api.get_site(base["site_id"], AUDITOR_1_HEADERS))
    assert site["service_posture"] == POSTURE_NORMAL

    validate_error(
        api.publish_usage_variance_review(base["review_id"], AUDITOR_2_HEADERS),
        ERR_INSUFFICIENT_TELEMETRY,
        422,
    )

    review = get_success_data(
        api.get_usage_variance_review(base["review_id"], AUDITOR_1_HEADERS)
    )
    assert review["status"] == REVIEW_DRAFT
    assert review["published_by_user_id"] is None
