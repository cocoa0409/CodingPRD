"""Guideline publication guards and the acknowledgment duty (PRD §2.5, §3.2)."""
from test_helpers import (
    ApiErrorId,
    assert_guideline_acknowledgment,
    assert_guideline_version,
    create_department,
    create_firm,
    create_guideline,
    firm_headers,
    get_matter,
    list_acknowledgments,
    ops_headers,
    publish_guideline,
    publish_guideline_and_get_ack,
    set_clock,
    setup_department_with_firm,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestGuidelineNoticeGap:
    """The notice-gap buffer between consecutive published guideline versions."""

    def test_notice_gap_too_small_rejected(self, api, legal_ops_headers):
        """PRD §3.2: "Publication is the pivotal act, and three guards apply: the `effective_date` must not lie in the past (else `ERR_INVALID_TEMPORAL`); no other published version of the same department may carry an `effective_date` on or after the one being published (else `ERR_GUIDELINE_OVERLAP`); and, when another version is currently published, the gap between the new `effective_date` and the prior version's `effective_date` must be at least `guideline_notice_days` days (else `ERR_NOTICE_GAP_VIOLATION`)."

        Design: Difficulty/resource_temporal_overlap/guideline_notice_gap_buffer_semantics
        """
        set_clock("2026-08-01T00:00:00Z")
        dept, firm = setup_department_with_firm(guideline_notice_days=30)
        gv1 = create_guideline(dept["id"], "OCG-V1", "2026-09-01T00:00:00Z")
        publish_guideline(dept["id"], gv1["id"])
        gv2 = create_guideline(dept["id"], "OCG-V2", "2026-09-15T00:00:00Z")

        resp = api.publish_guideline_version(dept["id"], gv2["id"], legal_ops_headers)
        validate_error(resp, ApiErrorId.ERR_NOTICE_GAP_VIOLATION)
        gv2_after = validate_success(api.get_guideline_version(dept["id"], gv2["id"], legal_ops_headers))
        assert gv2_after["status"] == "DRAFT", (
            f"failed publication must leave the version DRAFT, got {gv2_after['status']}"
        )

    def test_notice_gap_exact_boundary_publishes(self, api, legal_ops_headers):
        """PRD §3.2: "Publication is the pivotal act, and three guards apply: the `effective_date` must not lie in the past (else `ERR_INVALID_TEMPORAL`); no other published version of the same department may carry an `effective_date` on or after the one being published (else `ERR_GUIDELINE_OVERLAP`); and, when another version is currently published, the gap between the new `effective_date` and the prior version's `effective_date` must be at least `guideline_notice_days` days (else `ERR_NOTICE_GAP_VIOLATION`)."
        PRD §3.2: "The previously `PUBLISHED` version of the department, if any, transitions to `SUPERSEDED`."

        Design: Difficulty/resource_temporal_overlap/guideline_notice_gap_buffer_semantics
        """
        set_clock("2026-08-01T00:00:00Z")
        dept, firm = setup_department_with_firm(guideline_notice_days=30)
        gv1 = create_guideline(dept["id"], "OCG-V1", "2026-09-01T00:00:00Z")
        publish_guideline(dept["id"], gv1["id"])
        # Exactly 30 days after 2026-09-01: the gap is "at least" the notice days,
        # so the boundary value is compliant.
        gv3 = create_guideline(dept["id"], "OCG-V3", "2026-10-01T00:00:00Z")

        published = validate_success(api.publish_guideline_version(dept["id"], gv3["id"], legal_ops_headers))
        assert_guideline_version(published)
        assert published["status"] == "PUBLISHED", (
            f"30-day gap meets the 30-day requirement, expected PUBLISHED, got {published['status']}"
        )
        gv1_after = validate_success(api.get_guideline_version(dept["id"], gv1["id"], legal_ops_headers))
        assert gv1_after["status"] == "SUPERSEDED", (
            f"prior PUBLISHED version must be SUPERSEDED, got {gv1_after['status']}"
        )


def test_guideline_overlap_same_effective_date_rejected(api, legal_ops_headers):
    """PRD §3.2: "Publication is the pivotal act, and three guards apply: the `effective_date` must not lie in the past (else `ERR_INVALID_TEMPORAL`); no other published version of the same department may carry an `effective_date` on or after the one being published (else `ERR_GUIDELINE_OVERLAP`); and, when another version is currently published, the gap between the new `effective_date` and the prior version's `effective_date` must be at least `guideline_notice_days` days (else `ERR_NOTICE_GAP_VIOLATION`)."

    Design: Corner/validations/guideline_overlap_same_effective_date_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    dept = create_department()
    gv1 = create_guideline(dept["id"], "V1", "2026-09-01T00:00:00Z")
    publish_guideline(dept["id"], gv1["id"])
    gv2 = create_guideline(dept["id"], "V2", "2026-09-01T00:00:00Z")

    resp = api.publish_guideline_version(dept["id"], gv2["id"], legal_ops_headers)
    validate_error(resp, ApiErrorId.ERR_GUIDELINE_OVERLAP)


def test_acknowledge_already_acknowledged_returns_invalid_state(api):
    """PRD §3.2: "A successful acknowledgment — from either `PENDING` or `OVERDUE` — transitions the record to `ACKNOWLEDGED`, stamps `acknowledged_at` with the logical clock, and increments its `version`; `ACKNOWLEDGED` is terminal."
    PRD §2.9: "4. State legality: the target resource is in a state from which the requested transition is permitted — otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/acknowledge_already_acknowledged_returns_invalid_state
    """
    set_clock("2026-08-01T00:00:00Z")
    dept, firm = setup_department_with_firm()
    gv, ack = publish_guideline_and_get_ack(dept["id"], firm["id"])
    first = validate_success(api.acknowledge_guideline(dept["id"], firm["id"], ack["id"], firm_headers(firm["id"])))
    assert_guideline_acknowledgment(first)
    assert first["status"] == "ACKNOWLEDGED"

    resp = api.acknowledge_guideline(dept["id"], firm["id"], ack["id"], firm_headers(firm["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_acknowledgment_list_filtered_by_status(api, legal_ops_headers):
    """PRD §3.2: "Simultaneously, for every panel firm of the department whose `status` is `ACTIVE`, the server cascade-creates one acknowledgment record in `PENDING` status; each record binds the firm through its `panel_firm_id` and the version through its `guideline_version_id`, and its `acknowledged_at` remains null until the firm acts."
    PRD §3.2: "Acknowledgment listings can be narrowed by `status` or by `guideline_version_id`."

    Design: Corner/endpoints/acknowledgment_list_filtered_by_status
    """
    set_clock("2026-08-01T00:00:00Z")
    dept, firm = setup_department_with_firm()
    gv = create_guideline(dept["id"], "V1", "2026-09-01T00:00:00Z")
    publish_guideline(dept["id"], gv["id"])

    resp = api.list_acknowledgments(dept["id"], firm["id"], legal_ops_headers, params={"status": "PENDING"})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"exactly one PENDING acknowledgment must exist, got {meta['total_count']}"
    assert len(data) == 1 and data[0]["status"] == "PENDING"
    assert data[0]["guideline_version_id"] == gv["id"]
    assert data[0]["acknowledged_at"] is None


def test_error_firm_mismatch_on_acknowledge(api):
    """PRD §3.2: "Acknowledgment is the firm's duty, performed by a `PanelFirmUser`. The acting user's firm must equal the acknowledgment's `panel_firm_id`, or the attempt fails with `ERR_FIRM_MISMATCH`."

    Design: Corner/errors/error_firm_mismatch_on_acknowledge
    """
    set_clock("2026-08-01T00:00:00Z")
    dept = create_department()
    firm1 = create_firm(dept["id"], "F1")
    firm2 = create_firm(dept["id"], "F2")
    gv = create_guideline(dept["id"], "V1", "2026-09-01T00:00:00Z")
    publish_guideline(dept["id"], gv["id"])
    acks_f1 = list_acknowledgments(dept["id"], firm1["id"])
    assert len(acks_f1) == 1

    # Firm 2's user targets firm 1's acknowledgment.
    resp = api.acknowledge_guideline(dept["id"], firm1["id"], acks_f1[0]["id"], firm_headers(firm2["id"]))
    validate_error(resp, ApiErrorId.ERR_FIRM_MISMATCH)


def test_ack_overdue_clock_sweep(api):
    """PRD §3.2: "The overdue transition is system-driven: when the logical clock (§2.5) advances past the parent guideline version's publication timestamp plus the department's `acknowledgment_window_days`, the sweep flips the still-`PENDING` record to `OVERDUE` and increments its `version`. A firm that missed the window can still acknowledge late; the record then shows the `OVERDUE → ACKNOWLEDGED` path it took."

    Design: Corner/cross_cutting_layers/ack_overdue_clock_sweep
    """
    set_clock("2026-08-01T00:00:00Z")
    dept, firm = setup_department_with_firm(acknowledgment_window_days=14)
    gv, ack = publish_guideline_and_get_ack(dept["id"], firm["id"])
    assert ack["status"] == "PENDING"

    # 19 days after publication > 14-day window: the sweep flips the ack OVERDUE.
    set_clock("2026-08-20T00:00:00Z")
    swept = validate_success(api.get_acknowledgment(dept["id"], firm["id"], ack["id"], ops_headers()))
    assert swept["status"] == "OVERDUE", f"ack past its window must be OVERDUE, got {swept['status']}"

    late = validate_success(api.acknowledge_guideline(dept["id"], firm["id"], ack["id"], firm_headers(firm["id"])))
    assert late["status"] == "ACKNOWLEDGED", (
        f"late acknowledgment from OVERDUE must succeed, got {late['status']}"
    )
    assert late["acknowledged_at"] is not None
