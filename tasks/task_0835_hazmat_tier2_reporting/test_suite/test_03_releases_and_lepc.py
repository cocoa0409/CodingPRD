"""Chemical release notifications, parallel status dimensions, and LEPC notices."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_release_notification_payload,
    make_facility_operator_headers,
    make_lepc_coordinator_headers,
    register_facility,
    create_chemical,
    report_release,
    setup_release_with_lepc_notice,
)


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / release_parallel_reporting_remediation
# ---------------------------------------------------------------------------
def test_remediation_advances_to_contained(api):
    """PRD §3.5: "A `to` of `CONTAINED` moves `remediation_status` from `ONGOING`
    to `CONTAINED` (valid only from `ONGOING`, else `ERR_RELEASE_INVALID_STAGE`)."

    Design: Difficulty/non_linear_state_machine/release_parallel_reporting_remediation
    """
    facility = register_facility()
    fac_id = facility["id"]
    chemical = create_chemical(is_ehs=False, rq_lbs=1000, hazard_weight=0.1)
    release = report_release(
        fac_id, chemical["id"], release_datetime="2026-02-01T00:00:00Z",
        quantity_released_lbs=100, medium="SOIL",
    )
    resp = api.remediate_release_notification(
        release["id"], {"to": "CONTAINED"}, make_facility_operator_headers(fac_id)
    )
    data = validate_success(resp, expected_status=200)
    assert data["remediation_status"] == "CONTAINED"


def test_remediation_advance_leaves_reporting_dimension_untouched(api):
    """PRD §3.5: "Because the two dimensions are independent, remediation can
    progress while reporting is still pending, and vice versa."

    Design: Difficulty/non_linear_state_machine/release_parallel_reporting_remediation
    """
    facility = register_facility()
    fac_id = facility["id"]
    chemical = create_chemical(is_ehs=False, rq_lbs=1000, hazard_weight=0.1)
    release = report_release(
        fac_id, chemical["id"], release_datetime="2026-02-01T00:00:00Z",
        quantity_released_lbs=100, medium="SOIL",
    )
    resp = api.remediate_release_notification(
        release["id"], {"to": "CONTAINED"}, make_facility_operator_headers(fac_id)
    )
    data = validate_success(resp, expected_status=200)
    # Advancing remediation must NOT advance the reporting dimension.
    assert data["reporting_status"] == "PENDING_VERBAL"


# ---------------------------------------------------------------------------
# Corner: calculations / release_rq_inclusive_boundary
# ---------------------------------------------------------------------------
def test_release_at_exactly_rq_exceeds_and_requires_lepc(api):
    """PRD §3.5: "`exceeds_rq` is set to `true` exactly when
    `quantity_released_lbs` reaches or exceeds the chemical's `rq_lbs` (an inclusive
    comparison — an amount exactly equal to the reportable quantity qualifies), and
    `requires_lepc` is set equal to `exceeds_rq`, since an RQ-exceeding release is
    precisely the kind that must be reported to the LEPC and SERC."

    Design: Corner/calculations/release_rq_inclusive_boundary
    """
    facility = register_facility()
    fac_id = facility["id"]
    chemical = create_chemical(is_ehs=False, rq_lbs=500, hazard_weight=0.2, physical_state="SOLID")
    release = report_release(
        fac_id, chemical["id"], release_datetime="2026-02-12T00:00:00Z",
        quantity_released_lbs=500, medium="WATER",
    )
    assert release["exceeds_rq"] is True
    assert release["requires_lepc"] is True


# ---------------------------------------------------------------------------
# Corner: state_machines / release_report_written_before_verbal_invalid_stage
# ---------------------------------------------------------------------------
def test_report_written_before_verbal_rejected(api):
    """PRD §3.5: "A `stage` of `WRITTEN` moves `reporting_status` from
    `VERBAL_GIVEN` to `WRITTEN_FILED`; it requires `reporting_status` to be
    `VERBAL_GIVEN` (else `ERR_RELEASE_INVALID_STAGE`) and additionally requires the
    facility to have an emergency-response plan on file — its `erp_status` must be
    `ACTIVE`, and a written follow-up attempted while `erp_status` is `NONE` is
    rejected with `ERR_NO_ERP_LINKAGE`."

    Design: Corner/state_machines/release_report_written_before_verbal_invalid_stage
    """
    facility = register_facility()
    fac_id = facility["id"]
    chemical = create_chemical(is_ehs=False, rq_lbs=5000, hazard_weight=0.1)
    release = report_release(
        fac_id, chemical["id"], release_datetime="2026-02-10T00:00:00Z",
        quantity_released_lbs=10, medium="SOIL",
    )
    # reporting_status is still PENDING_VERBAL -> WRITTEN is an invalid stage jump.
    resp = api.report_release_notification(
        release["id"], {"stage": "WRITTEN"}, make_facility_operator_headers(fac_id)
    )
    validate_error(resp, ApiErrorId.ERR_RELEASE_INVALID_STAGE.value)


# ---------------------------------------------------------------------------
# Corner: state_machines / release_written_without_erp_returns_no_erp_linkage
# ---------------------------------------------------------------------------
def test_report_written_without_erp_linkage_rejected(api):
    """PRD §3.5: "it requires `reporting_status` to be `VERBAL_GIVEN` (else
    `ERR_RELEASE_INVALID_STAGE`) and additionally requires the facility to have an
    emergency-response plan on file — its `erp_status` must be `ACTIVE`, and a
    written follow-up attempted while `erp_status` is `NONE` is rejected with
    `ERR_NO_ERP_LINKAGE`."

    Design: Corner/state_machines/release_written_without_erp_returns_no_erp_linkage
    """
    facility = register_facility()
    fac_id = facility["id"]
    chemical = create_chemical(is_ehs=False, rq_lbs=5000, hazard_weight=0.1)
    release = report_release(
        fac_id, chemical["id"], release_datetime="2026-02-11T00:00:00Z",
        quantity_released_lbs=10, medium="AIR",
    )
    # Advance reporting to VERBAL_GIVEN so only the ERP guard can fire.
    validate_success(api.report_release_notification(
        release["id"], {"stage": "VERBAL"}, make_facility_operator_headers(fac_id)
    ))
    resp = api.report_release_notification(
        release["id"], {"stage": "WRITTEN"}, make_facility_operator_headers(fac_id)
    )
    validate_error(resp, ApiErrorId.ERR_NO_ERP_LINKAGE.value)


# ---------------------------------------------------------------------------
# Corner: validations / release_future_datetime_returns_422
# ---------------------------------------------------------------------------
def test_future_release_datetime_rejected(api):
    """PRD §3.5: "A release may not be reported in the future: the
    `release_datetime` must be at or before the current logical clock, and a
    `release_datetime` after the clock is rejected with `ERR_FUTURE_RELEASE`
    (HTTP 422)."

    Design: Corner/validations/release_future_datetime_returns_422
    """
    facility = register_facility()
    fac_id = facility["id"]
    chemical = create_chemical(is_ehs=False, rq_lbs=1000, hazard_weight=0.1)
    payload = create_release_notification_payload(
        fac_id, chemical["id"], release_datetime="2027-01-01T00:00:00Z",
        quantity_released_lbs=10, medium="AIR",
    )
    resp = api.create_release_notification(payload, make_facility_operator_headers(fac_id))
    validate_error(resp, ApiErrorId.ERR_FUTURE_RELEASE.value)


# ---------------------------------------------------------------------------
# Corner: endpoints / lepc_notice_create_and_acknowledge
# ---------------------------------------------------------------------------
def test_lepc_coordinator_acknowledges_notice(api):
    """PRD §3.5: "Each recorded notice is stamped with a `sent_at` taken from the
    logical clock and starts with `acknowledged` set to `false`. A
    `LEPCCoordinator` — and only a `LEPCCoordinator` — acknowledges a notice, which
    sets its `acknowledged` flag to `true`."

    Design: Corner/endpoints/lepc_notice_create_and_acknowledge
    """
    ctx = setup_release_with_lepc_notice(recipient="LEPC", notice_type="VERBAL")
    assert ctx["notice"]["acknowledged"] is False
    resp = api.acknowledge_lepc_notice(ctx["notice"]["id"], make_lepc_coordinator_headers())
    data = validate_success(resp, expected_status=200)
    assert data["acknowledged"] is True
