"""Transitive cascades (cert-expiry and equipment-outage), the cross-entity publish
gate, maintenance-window overlap, and apparatus posture.

Queue A: transitive_cascade/cert_expiry_cascades_to_shift_understaffing,
transitive_cascade/equipment_oos_cascades_to_shift_suspend,
cross_entity_state_dependency/publish_requires_apparatus_in_service,
resource_temporal_overlap/apparatus_maintenance_window_overlap.
Queue B: corner_apparatus_posture_reserve_on_noncritical.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    CHIEF,
    create_officer,
    create_member,
    create_eligible_member,
    create_station_with_apparatus,
    create_draft_shift,
    create_published_shift,
    assign_member,
    current_shift_version,
    set_clock,
)
from test_helpers.factories import (
    create_equipment_payload,
    create_maintenance_window_payload,
)


# --------------------------------------- cert expiry cascade to understaffing
def _run_cert_expiry_cascade(api):
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(api, apparatus_type="AMBULANCE", min_crew=1)
    m, cert = create_eligible_member(api, off, role_class="EMT", dues=0)  # EMT_BASIC expires 2027-03-01
    sh = create_published_shift(api, off, station["id"], apparatus["id"], "2027-03-05T06:00:00Z", "2027-03-05T18:00:00Z", max_crew=4, min_crew=1)
    a = assign_member(api, off, sh["id"], m["id"], current_shift_version(api, off, sh["id"]))
    set_clock("2027-03-01T00:00:00Z")
    get_success_data(api.sweep_certifications(off))
    return off, m, cert, a, sh


def test_cert_expiry_flips_member_ineligible(api):
    """PRD §3.2: "**Cascade 1** fires whenever a required certification expires
    through the sweep. Its first hop recomputes the member's response eligibility,
    which flips to false when the expiring certification is required."

    Design: Difficulty/transitive_cascade/cert_expiry_cascades_to_shift_understaffing
    """
    off, m, cert, a, sh = _run_cert_expiry_cascade(api)
    cert_now = validate_success(api.get_certification(cert["id"], off), 200)
    assert cert_now["status"] == "EXPIRED"
    member_now = validate_success(api.get_member(m["id"], off), 200)
    assert member_now["response_eligible"] is False


def test_cert_expiry_cancels_assignment_and_understaffs_shift(api):
    """PRD §3.2: "Its second hop cancels that member's forward duty commitments:
    every duty assignment of that member in `ASSIGNED` or `CHECKED_IN` on a shift
    whose `start_at` is later than the current clock is set to `CANCELLED`. Its
    third hop reconciles each affected shift — the shift's assigned count is
    recomputed and its staffing status is recomputed, dropping to `UNDERSTAFFED`
    when the count falls below the shift's crew floor."

    Design: Difficulty/transitive_cascade/cert_expiry_cascades_to_shift_understaffing
    """
    off, m, cert, a, sh = _run_cert_expiry_cascade(api)
    assignment_now = validate_success(api.get_assignment(a["id"], off), 200)
    assert assignment_now["status"] == "CANCELLED"
    shift_now = validate_success(api.get_duty_shift(sh["id"], off), 200)
    assert shift_now["staffing_status"] == "UNDERSTAFFED"


# --------------------------------------- equipment OOS cascade to shift suspend
def _run_equipment_oos_cascade(api):
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(api, apparatus_type="ENGINE", min_crew=1)
    eq = get_success_data(api.create_equipment(apparatus["id"], create_equipment_payload(name="Pump", is_critical=True), CHIEF))
    sh = create_published_shift(api, off, station["id"], apparatus["id"], "2026-04-01T06:00:00Z", "2026-04-01T18:00:00Z")
    get_success_data(api.equipment_out_of_service(eq["id"], CHIEF))
    return off, apparatus, eq, sh


def test_critical_equipment_down_forces_apparatus_out_of_service(api):
    """PRD §3.3: "if the apparatus has any maintenance window currently
    `IN_PROGRESS`, or any critical equipment (an item whose `is_critical` is true)
    currently `OUT_OF_SERVICE`, the posture is `OUT_OF_SERVICE`; otherwise, if the
    apparatus has any non-critical equipment currently `OUT_OF_SERVICE`, the
    posture is `RESERVE`; otherwise the posture is `IN_SERVICE`."

    Design: Difficulty/transitive_cascade/equipment_oos_cascades_to_shift_suspend
    """
    off, apparatus, eq, sh = _run_equipment_oos_cascade(api)
    eq_now = validate_success(api.get_equipment(eq["id"], off), 200)
    assert eq_now["status"] == "OUT_OF_SERVICE"
    ap_now = validate_success(api.get_apparatus(apparatus["id"], off), 200)
    assert ap_now["posture"] == "OUT_OF_SERVICE"


def test_apparatus_out_of_service_suspends_published_future_shift(api):
    """PRD §3.3: "if it becomes `OUT_OF_SERVICE`, every duty shift on that
    apparatus that is currently `PUBLISHED` with a `start_at` later than the
    current clock is suspended, `PUBLISHED → SUSPENDED`."

    Design: Difficulty/transitive_cascade/equipment_oos_cascades_to_shift_suspend
    """
    off, apparatus, eq, sh = _run_equipment_oos_cascade(api)
    shift_now = validate_success(api.get_duty_shift(sh["id"], off), 200)
    assert shift_now["status"] == "SUSPENDED"


# --------------------------------------- publish gated by apparatus posture
def _draft_shift_on_out_of_service_apparatus(api):
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(api, apparatus_type="ENGINE")
    eq = get_success_data(api.create_equipment(apparatus["id"], create_equipment_payload(name="SCBA", is_critical=True), CHIEF))
    get_success_data(api.equipment_out_of_service(eq["id"], CHIEF))
    sh = create_draft_shift(api, off, station["id"], apparatus["id"], "2026-07-01T06:00:00Z", "2026-07-01T18:00:00Z")
    return off, eq, sh


def test_publish_rejected_when_apparatus_out_of_service(api):
    """PRD §3.4: "An Officer publishes a draft shift, `DRAFT → PUBLISHED`, but only
    when the apparatus's posture is `IN_SERVICE` or `RESERVE`; publishing a shift
    whose apparatus posture is `OUT_OF_SERVICE` is rejected with
    `ERR_APPARATUS_OUT_OF_SERVICE`."

    Design: Difficulty/cross_entity_state_dependency/publish_requires_apparatus_in_service
    """
    off, eq, sh = _draft_shift_on_out_of_service_apparatus(api)
    validate_error(api.publish_duty_shift(sh["id"], off), ApiErrorId.ERR_APPARATUS_OUT_OF_SERVICE.value)


def test_publish_succeeds_after_apparatus_returns_to_service(api):
    """PRD §3.3: "When the equipment returns to service or the maintenance window
    completes, the posture is recomputed, and if it recovers to anything other
    than `OUT_OF_SERVICE`, the shifts that were suspended by the outage are
    restored, `SUSPENDED → PUBLISHED`, and each recomputes its staffing."
    PRD §3.4: "An Officer publishes a draft shift, `DRAFT → PUBLISHED`, but only
    when the apparatus's posture is `IN_SERVICE` or `RESERVE`".

    Design: Difficulty/cross_entity_state_dependency/publish_requires_apparatus_in_service
    """
    off, eq, sh = _draft_shift_on_out_of_service_apparatus(api)
    get_success_data(api.equipment_return_to_service(eq["id"], CHIEF))
    published = validate_success(api.publish_duty_shift(sh["id"], off), 200)
    assert published["status"] == "PUBLISHED"


# --------------------------------------- maintenance window overlap
def _apparatus_with_scheduled_window(api):
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(api, apparatus_type="ENGINE")
    get_success_data(
        api.create_maintenance_window(
            apparatus["id"],
            create_maintenance_window_payload(start_at="2026-04-01T00:00:00Z", end_at="2026-04-05T00:00:00Z"),
            CHIEF,
        )
    )
    return apparatus


def test_overlapping_maintenance_window_rejected(api):
    """PRD §3.3: "A new window is rejected with `ERR_MAINTENANCE_OVERLAP` if any
    other window on the same apparatus in `SCHEDULED` or `IN_PROGRESS` status has a
    half-open interval that overlaps it; back-to-back windows that merely touch
    (one ending exactly when the next begins) are allowed, and there is no
    separation buffer."

    Design: Difficulty/resource_temporal_overlap/apparatus_maintenance_window_overlap
    """
    apparatus = _apparatus_with_scheduled_window(api)
    resp = api.create_maintenance_window(
        apparatus["id"],
        create_maintenance_window_payload(start_at="2026-04-03T00:00:00Z", end_at="2026-04-06T00:00:00Z"),
        CHIEF,
    )
    validate_error(resp, ApiErrorId.ERR_MAINTENANCE_OVERLAP.value)


def test_adjacent_maintenance_window_accepted(api):
    """PRD §3.3: "back-to-back windows that merely touch (one ending exactly when
    the next begins) are allowed, and there is no separation buffer."

    Design: Difficulty/resource_temporal_overlap/apparatus_maintenance_window_overlap
    """
    apparatus = _apparatus_with_scheduled_window(api)
    data = validate_success(
        api.create_maintenance_window(
            apparatus["id"],
            create_maintenance_window_payload(start_at="2026-04-05T00:00:00Z", end_at="2026-04-10T00:00:00Z"),
            CHIEF,
        ),
        201,
    )
    assert data["status"] == "SCHEDULED"


# --------------------------------------- corner: posture RESERVE on non-critical
def test_noncritical_equipment_down_moves_posture_to_reserve(api):
    """PRD §3.3: "otherwise, if the apparatus has any non-critical equipment
    currently `OUT_OF_SERVICE`, the posture is `RESERVE`; otherwise the posture is
    `IN_SERVICE`."

    Design: Corner/calculations/corner_apparatus_posture_reserve_on_noncritical
    """
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(api, apparatus_type="ENGINE")
    eq = get_success_data(api.create_equipment(apparatus["id"], create_equipment_payload(name="Spare Hose", is_critical=False), CHIEF))
    get_success_data(api.equipment_out_of_service(eq["id"], CHIEF))
    ap_now = validate_success(api.get_apparatus(apparatus["id"], off), 200)
    assert ap_now["posture"] == "RESERVE"
