"""Queue B — entities section corner tests."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, is_valid_uuid,
    create_active_program, create_program, create_stakeholder_group,
    create_engagement, create_lesson_entry, create_contract,
    create_change_order,
    create_risk_entry,
    create_baseline_payload,
    pm_headers, owner_headers, ApiErrorId,
)


def test_program_creation_defaults_applied(api):
    """PRD §3.1: "A new program is born in CHARTERING status with an empty
    financial posture: all four pool counters are 0, contingency_posture is
    CRITICAL (a zero-total pool is critical by definition, per §2.7),
    current_budget_cents is null until the first baseline approval lands, and
    approved_charter_id, approved_baseline_id, baseline_version_no, and
    target_finish_date are all null." PRD §2.4: "version (integer): A
    system-managed integer that starts at 1 at creation".

    Design: Corner/entities/program_creation_defaults_applied
    """
    resp = api_client.create_program(
        {"program_name": "P-DEF", "owner_organization": "OwnerOrg"}, pm_headers())
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "CHARTERING"
    assert data["version"] == 1
    assert data["contingency_total_cents"] == 0
    assert data["contingency_available_cents"] == 0
    assert data["contingency_posture"] == "CRITICAL"
    assert data["current_budget_cents"] is None
    assert data["baseline_version_no"] is None


def test_program_list_pagination_envelope(api):
    """PRD §2.3: "Paginated list-based responses include the following fields
    in the meta object of the response envelope: limit, offset, total_count,
    and has_more." And: "If not provided, [limit] defaults to 10, with a
    minimum of 1 and a maximum of 100. The offset parameter specifies the
    number of items to skip and defaults to 0."

    Design: Corner/entities/program_list_pagination_envelope
    """
    for name in ("P1", "P2", "P3"):
        api_client.create_program({"program_name": name, "owner_organization": "O"},
                                   pm_headers())
    r1 = api_client.list_programs(pm_headers(), params={"limit": 2, "offset": 0})
    items1, meta1 = validate_paginated(r1)
    assert len(items1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    r2 = api_client.list_programs(pm_headers(), params={"limit": 2, "offset": 2})
    items2, meta2 = validate_paginated(r2)
    assert len(items2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_program_create_missing_required_field_returns_400(api):
    """PRD §2.5 priority 3: "Required fields must be present, types must
    match, enum values must be valid members, amounts must be positive
    integers where required, and time ranges must have the end strictly after
    the start; failures surface ERR_INVALID_REQUEST (400)." PRD §3.1 requires
    program_name and owner_organization.

    Design: Corner/entities/program_create_missing_required_field_returns_400
    """
    resp = api_client.create_program({"program_name": "P-NOFIELD"}, pm_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_risk_exposure_computed_value(api):
    """PRD §3.4: "its exposure_cents is computed immediately — and recomputed
    on every subsequent assessment — as probability_pct multiplied by
    impact_cents, divided by 100, rounded half-up to whole cents."
    PRD §3.4: "The entry is born IDENTIFIED".

    Design: Corner/entities/risk_exposure_computed_input_ignored
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-CMP",
    )
    pid = prog["id"]
    r = create_risk_entry(pid, probability_pct=50, impact_cents=400_000,
                           title="R", category="COST")
    assert r["exposure_cents"] == 200_000
    assert r["status"] == "IDENTIFIED"


def test_engagement_duration_minutes_computed(api):
    """PRD §3.7: "the system computes duration_minutes as the whole minutes
    between start and end. A new engagement starts PROPOSED". PRD §2.10: "an
    engagement derives its program_id from its stakeholder group".

    Design: Corner/entities/engagement_duration_minutes_computed
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-DUR",
    )
    pid = prog["id"]
    g1 = create_stakeholder_group(pid, group_name="G1", contact_email="g1@x.com")
    e = create_engagement(g1["id"], title="E",
                           scheduled_start="2026-09-02T09:00:00Z",
                           scheduled_end="2026-09-02T10:45:00Z")
    assert e["duration_minutes"] == 105
    assert e["status"] == "PROPOSED"
    assert e["program_id"] == pid


def test_lesson_entry_append_only_immutable(api):
    """PRD §2.4: "One entity stands apart: the LessonEntry is an append-only
    log and carries only id and created_at. It has no updated_at and no
    version, and it supports no update or delete operation."

    Design: Corner/entities/lesson_entry_append_only_immutable
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-LES",
    )
    pid = prog["id"]
    le = create_lesson_entry(pid, category="COST",
                              lesson_text="contingency ran hot",
                              recommendation="raise floors")
    assert is_valid_uuid(le["id"])
    assert "created_at" in le
    assert "updated_at" not in le, "LessonEntry must NOT carry updated_at"
    assert "version" not in le, "LessonEntry must NOT carry version"
    # Read back via list filter
    lst, meta = validate_paginated(
        api_client.list_lesson_entries(pm_headers(), params={"program_id": pid}))
    assert meta["total_count"] == 1
    assert lst[0]["lesson_text"] == "contingency ran hot"


def test_baseline_lines_must_sum_to_total(api):
    """PRD §3.1: "the line amounts must sum exactly to total_budget_cents.
    Malformed payloads in any of these respects fail at pipeline step 3 with
    ERR_INVALID_REQUEST." And: "every cost_code is unique within the
    baseline".

    Design: Corner/entities/baseline_lines_must_sum_to_total
    """
    prog = create_program(name="P-SUM")
    pid = prog["id"]
    # Sum mismatch: 600_000 != 1_000_000
    r1 = api_client.create_baseline(
        create_baseline_payload(pid, total_budget_cents=1_000_000,
                                 contingency_total_cents=100_000,
                                 lines=[{"cost_code": "CC-100", "amount_cents": 600_000}]),
        pm_headers(),
    )
    validate_error(r1, ApiErrorId.ERR_INVALID_REQUEST)
    # Duplicate cost_code
    r2 = api_client.create_baseline(
        create_baseline_payload(pid, total_budget_cents=1_000_000,
                                 contingency_total_cents=100_000,
                                 lines=[
                                     {"cost_code": "CC-100", "amount_cents": 500_000},
                                     {"cost_code": "CC-100", "amount_cents": 500_000},
                                 ]),
        pm_headers(),
    )
    validate_error(r2, ApiErrorId.ERR_INVALID_REQUEST)


def test_change_orders_filtered_list_by_contract(api):
    """PRD §4 endpoint table: "GET /change-orders — List change orders,
    filterable by program_id, contract_id, supersedes_id, superseded_by_id,
    linked_drawdown_id, status".

    Design: Corner/entities/change_orders_filtered_list_by_contract
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-FK",
    )
    pid = prog["id"]
    ct1 = create_contract(pid, solicitation_estimate_cents=100_000,
                           vendor_name="V1", contract_type="CONTRACTOR")
    ct2 = create_contract(pid, solicitation_estimate_cents=100_000,
                           vendor_name="V2", contract_type="CONSULTANT")
    coa = create_change_order(ct1["id"], amount_cents=1_000, title="CO-A", reason="r")
    cob = create_change_order(ct2["id"], amount_cents=2_000, title="CO-B", reason="r")
    items, meta = validate_paginated(
        api_client.list_change_orders(pm_headers(), params={"contract_id": ct1["id"]}))
    assert len(items) == 1
    assert items[0]["id"] == coa["id"]
    assert items[0]["contract_id"] == ct1["id"]
