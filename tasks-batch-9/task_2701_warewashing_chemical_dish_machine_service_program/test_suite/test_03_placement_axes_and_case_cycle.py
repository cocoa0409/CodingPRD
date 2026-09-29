"""
Non-linear lifecycles: the placement's two parallel axes and the investigation
case's cycle back into evidence gathering.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import ERR_INVALID_STATE_TRANSITION
from test_helpers.assertions import (
    assert_axes,
    assert_cents,
    assert_instant_equals,
    assert_lockout,
)
from test_helpers.test_users import (
    ACCOUNT_MANAGER_HEADERS,
    AUDITOR_1_HEADERS,
    AUDITOR_3_HEADERS,
)
from test_helpers.types import (
    ALERT_LOW_RINSE_PRESSURE,
    ALERT_SUPPRESSED,
    CASE_EVIDENCE_GATHERING,
    CASE_PENDING_REVIEW,
    CASE_SUBSTANTIATED,
    CLASS_THEFT_SUSPECT,
    DECISION_RETURN,
    DECISION_SUBSTANTIATE,
    DISPENSER_ACTIVE,
    DISPENSER_LOCKED_OUT,
    DISPENSER_REMOVED,
    EVIDENCE_DELIVERY_LOG,
    EVIDENCE_INVENTORY_COUNT,
    EVIDENCE_TELEMETRY_EXPORT,
    LOCKOUT_AGREEMENT_ENDED,
    OP_DEGRADED,
    OP_OFFLINE,
    OP_UP,
    PLACEMENT_INSTALLED,
    PLACEMENT_PENDING_INSTALL,
    PLACEMENT_RETRIEVAL_SCHEDULED,
    PLACEMENT_RETRIEVED,
    REMEDIATION_CHARGEBACK,
    REVIEW_CLOSED,
    REVIEW_ESCALATED,
    SEVERITY_WARNING,
)


def _degraded_but_installed(api):
    """
    One placement carrying a DET-100 dispenser, driven to DEGRADED by a single
    WARNING rinse-pressure breach at 14 psi against a 15 psi minimum. No ticket
    is ever filed, so retrieval completion is never blocked.
    """
    base = X.program_base(api)
    created = X.create_placement(api, base, asset_tag="AT-301")
    assert_axes(
        created,
        placement_status=PLACEMENT_PENDING_INSTALL,
        operational_status=OP_UP,
    )

    installed = X.install_placement(api, base, created["id"])
    dispenser = X.fit_dispenser(api, base, created["id"], dose=8.00)

    X.ingest_reading_at_clock(
        api,
        created["id"],
        "2026-08-03T12:00:00Z",
        500,
        rinse_pressure_psi=14,
    )

    base.update(
        {
            "placement_id": created["id"],
            "created": created,
            "installed": installed,
            "dispenser_id": dispenser["id"],
        }
    )
    return base


def test_install_and_a_warning_alert_move_one_axis_each(api):
    """
    Installing moves the lifecycle axis to INSTALLED while health stays UP; the
    14 psi WARNING breach then moves health to DEGRADED while the lifecycle axis
    stays INSTALLED. Neither pair is reachable if the two axes are collapsed.

    PRD §3.3: "Neither axis constrains the other's value except where this
    document says so explicitly. Installing a machine does not touch its health
    axis; a machine going down does not change its placement status; both
    `RETRIEVED` and `CANCELLED` are terminal on the lifecycle axis and `OFFLINE`
    is terminal on the health axis."

    Design: Difficulty/non_linear_state_machine/placement_lifecycle_and_health_axes_advance_independently
    """
    base = _degraded_but_installed(api)

    assert_axes(
        base["installed"],
        placement_status=PLACEMENT_INSTALLED,
        operational_status=OP_UP,
    )

    after_reading = get_success_data(
        api.get_machine_placement(base["placement_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_axes(
        after_reading,
        placement_status=PLACEMENT_INSTALLED,
        operational_status=OP_DEGRADED,
    )

    alerts = X.list_alerts_for_placement(api, base["placement_id"])
    assert len(alerts) == 1
    assert alerts[0]["alert_type"] == ALERT_LOW_RINSE_PRESSURE
    assert alerts[0]["severity"] == SEVERITY_WARNING
    assert alerts[0]["measured_value"] == 14


def test_only_retrieval_completion_joins_both_axes(api):
    """
    A retrieval order moves the lifecycle axis to RETRIEVAL_SCHEDULED and locks
    the dispenser out as AGREEMENT_ENDED, yet deliberately leaves health at
    DEGRADED; retrieval completion is the single event that drives both axes,
    landing on (RETRIEVED, OFFLINE).

    PRD §3.3: "On success the placement moves `RETRIEVAL_SCHEDULED →
    RETRIEVED`, `retrieved_at` is stamped from the clock, `operational_status`
    is driven to `OFFLINE` from whichever of `UP`, `DEGRADED` or `DOWN` it held,
    every dispenser of the placement — whether it stood `ACTIVE` or
    `LOCKED_OUT` — becomes `REMOVED` with its `lockout_reason` cleared to null,
    the model's `equipment_value_cents` is subtracted from the customer's
    `equipment_on_placement_value_cents` restoring that ledger exactly to its
    pre-placement value, the agreement's `placement_count` falls by one with a
    `version` increment, and the site's `service_posture` is re-derived."

    Design: Difficulty/non_linear_state_machine/placement_lifecycle_and_health_axes_advance_independently
    """
    base = _degraded_but_installed(api)

    scheduled = validate_success(
        api.create_retrieval_order(
            base["placement_id"],
            ACCOUNT_MANAGER_HEADERS,
            F.retrieval_order_payload("2026-09-15"),
        )
    )
    assert_axes(
        scheduled,
        placement_status=PLACEMENT_RETRIEVAL_SCHEDULED,
        operational_status=OP_DEGRADED,
    )
    assert scheduled["retrieval_due_date"] == "2026-09-15"

    dispenser = get_success_data(
        api.get_dispenser(base["dispenser_id"], base["technician_headers"])
    )
    assert_lockout(dispenser, DISPENSER_LOCKED_OUT, LOCKOUT_AGREEMENT_ENDED)

    alerts = X.list_alerts_for_placement(api, base["placement_id"])
    assert len(alerts) == 1
    assert alerts[0]["status"] == ALERT_SUPPRESSED

    retrieved = validate_success(
        api.complete_retrieval(base["placement_id"], base["technician_headers"])
    )
    assert_axes(
        retrieved,
        placement_status=PLACEMENT_RETRIEVED,
        operational_status=OP_OFFLINE,
    )
    assert_instant_equals(retrieved["retrieved_at"], "2026-08-03T12:00:00Z", "retrieved_at")

    dispenser = get_success_data(
        api.get_dispenser(base["dispenser_id"], base["technician_headers"])
    )
    assert_lockout(dispenser, DISPENSER_REMOVED, None)


def _escalated_case(api):
    """
    A THEFT_SUSPECT review over August — 3000 racks expecting 24000 ml against
    30100 ml actually drawn — published by a second auditor and escalated into
    an open investigation case by the first.
    """
    base = X.program_base(api)
    placement = X.installed_placement(api, base, asset_tag="AT-401")
    dispenser = X.fit_dispenser(api, base, placement["id"], dose=8.00)

    X.set_clock(api, "2026-08-02T08:00:00Z")
    X.record_delivery(api, base, unit_count=2, delivered_at="2026-08-02T08:00:00Z")

    X.ingest_reading_at_clock(api, placement["id"], "2026-08-05T12:00:00Z", 1000)
    X.ingest_reading_at_clock(api, placement["id"], "2026-08-20T12:00:00Z", 3000)
    X.set_clock(api, "2026-09-01T00:00:00Z")

    review = X.draft_review(
        api, base, opening_inventory_ml=5000, ending_inventory_ml=14900
    )
    assert review["expected_consumption_ml"] == 24000
    assert review["actual_consumption_ml"] == 30100
    assert review["variance_pct"] == 25.42
    assert review["classification"] == CLASS_THEFT_SUSPECT

    X.publish_review(api, review["id"])
    case = X.open_case(api, review["id"])
    assert case["case_status"] == CASE_EVIDENCE_GATHERING

    escalated = get_success_data(
        api.get_usage_variance_review(review["id"], AUDITOR_1_HEADERS)
    )
    assert escalated["status"] == REVIEW_ESCALATED

    base.update(
        {
            "placement_id": placement["id"],
            "dispenser_id": dispenser["id"],
            "review_id": review["id"],
            "case_id": case["id"],
        }
    )
    return base


def test_return_decision_recycles_the_case_and_accumulates_evidence(api):
    """
    One INVENTORY_COUNT item, a RETURN, then two more items: the case leaves and
    re-enters EVIDENCE_GATHERING, return_count reaches 1, and evidence_item_count
    reaches 3 rather than being replaced by the second submission's 2.

    PRD §3.8: "`RETURN` is the non-terminal decision: it sends the case back
    `PENDING_REVIEW → EVIDENCE_GATHERING` and increments `return_count` by one,
    while the linked review stays `ESCALATED`."

    Design: Difficulty/non_linear_state_machine/investigation_case_returns_to_evidence_gathering_twice
    """
    base = _escalated_case(api)

    first = X.submit_case(api, base["case_id"], [EVIDENCE_INVENTORY_COUNT])
    assert first["case_status"] == CASE_PENDING_REVIEW
    assert first["evidence_item_count"] == 1

    returned = X.review_case(
        api,
        base["case_id"],
        DECISION_RETURN,
        finding_note="single inventory count is not enough",
    )
    assert returned["case_status"] == CASE_EVIDENCE_GATHERING
    assert returned["return_count"] == 1

    review = get_success_data(
        api.get_usage_variance_review(base["review_id"], AUDITOR_1_HEADERS)
    )
    assert review["status"] == REVIEW_ESCALATED

    second = X.submit_case(
        api, base["case_id"], [EVIDENCE_TELEMETRY_EXPORT, EVIDENCE_DELIVERY_LOG]
    )
    assert second["case_status"] == CASE_PENDING_REVIEW
    assert second["evidence_item_count"] == 3


def test_substantiation_is_refused_until_the_cycle_has_run(api):
    """
    With a single evidence item the same SUBSTANTIATE request is refused as an
    undeclared transition and the case stays PENDING_REVIEW; only after the
    RETURN loop has added two more items does it succeed.

    PRD §3.8: "`SUBSTANTIATE` moves the case `PENDING_REVIEW → SUBSTANTIATED`
    and additionally requires `evidence_item_count` to be at least 2 — a single
    evidence item cannot substantiate a finding, and the attempt is refused as
    an undeclared transition with `ERR_INVALID_STATE_TRANSITION`."

    Design: Difficulty/non_linear_state_machine/investigation_case_returns_to_evidence_gathering_twice
    """
    base = _escalated_case(api)

    X.submit_case(api, base["case_id"], [EVIDENCE_INVENTORY_COUNT])

    validate_error(
        api.review_investigation_case(
            base["case_id"],
            F.case_review_payload(DECISION_SUBSTANTIATE, REMEDIATION_CHARGEBACK),
            AUDITOR_3_HEADERS,
        ),
        ERR_INVALID_STATE_TRANSITION,
    )
    blocked = get_success_data(
        api.get_investigation_case(base["case_id"], AUDITOR_1_HEADERS)
    )
    assert blocked["case_status"] == CASE_PENDING_REVIEW
    assert blocked["evidence_item_count"] == 1

    X.review_case(api, base["case_id"], DECISION_RETURN)
    X.submit_case(
        api, base["case_id"], [EVIDENCE_TELEMETRY_EXPORT, EVIDENCE_DELIVERY_LOG]
    )

    substantiated = X.review_case(
        api,
        base["case_id"],
        DECISION_SUBSTANTIATE,
        remediation=REMEDIATION_CHARGEBACK,
        finding_note="6100 ml unaccounted",
    )
    assert substantiated["case_status"] == CASE_SUBSTANTIATED
    assert substantiated["evidence_item_count"] == 3
    assert substantiated["return_count"] == 1


def test_chargeback_uses_the_frozen_excess_at_list_price(api):
    """
    The 6100 ml unaccounted for rounds up to one 20000 ml container, charged at
    the undiscounted 9600-cent list price. Cascade gamma then closes the review
    and, because the remediation is CHARGEBACK rather than DISPENSER_REPLACEMENT,
    leaves the dispenser ACTIVE and the health axis alone.

    PRD §3.8: "When and only when the ordered remediation is `CHARGEBACK`,
    `chargeback_cents` is computed from the review's **frozen** figures and never
    recomputed from live telemetry: take `actual_consumption_ml` minus
    `expected_consumption_ml`, keep it only if positive and otherwise treat the
    excess as zero, divide that excess by the product's `unit_size_ml` and round
    **up** to the next whole container, and multiply the resulting container
    count by the product's `unit_price_cents` — the list price, with no volume
    discount, because excess consumption is not a purchase."

    Design: Difficulty/non_linear_state_machine/investigation_case_returns_to_evidence_gathering_twice
    """
    base = _escalated_case(api)

    X.submit_case(api, base["case_id"], [EVIDENCE_INVENTORY_COUNT])
    X.review_case(api, base["case_id"], DECISION_RETURN)
    X.submit_case(
        api, base["case_id"], [EVIDENCE_TELEMETRY_EXPORT, EVIDENCE_DELIVERY_LOG]
    )

    substantiated = X.review_case(
        api,
        base["case_id"],
        DECISION_SUBSTANTIATE,
        remediation=REMEDIATION_CHARGEBACK,
        finding_note="6100 ml unaccounted",
    )
    assert substantiated["case_status"] == CASE_SUBSTANTIATED
    assert substantiated["remediation"] == REMEDIATION_CHARGEBACK
    assert_cents(substantiated["chargeback_cents"], 9600)
    assert substantiated["reviewed_by_user_id"] == AUDITOR_3_HEADERS["X-User-ID"]

    review = get_success_data(
        api.get_usage_variance_review(base["review_id"], AUDITOR_1_HEADERS)
    )
    assert review["status"] == REVIEW_CLOSED

    dispenser = get_success_data(
        api.get_dispenser(base["dispenser_id"], base["technician_headers"])
    )
    assert_lockout(dispenser, DISPENSER_ACTIVE, None)
    placement = get_success_data(
        api.get_machine_placement(base["placement_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_axes(placement, operational_status=OP_UP)
