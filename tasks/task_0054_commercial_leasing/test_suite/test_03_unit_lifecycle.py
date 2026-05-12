"""Unit renovation, split, and merge — the structural-transformation rules.

PRD §3.1.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    assert_unit,
    assert_audit_event,
    create_building,
    create_unit,
    find_audit_events,
    list_audit_events,
    make_child_unit_spec,
    merge_units_payload,
    setup_building_with_unit,
    setup_building_with_two_units,
    split_unit_payload,
    start_renovation,
    start_renovation_payload,
    finish_renovation,
    advance_clock,
    unique_unit_code,
    validate_error,
    validate_success,
    PM,
)


# ===========================================================================
# Renovation interval
# ===========================================================================
class TestRenovationLifecycle:
    """PRD §3.1: 'A vacant unit may be taken offline for renovation.
    A property manager opens a renovation interval by supplying a
    renovation_end_date; the server stamps the unit's
    renovation_start_date and renovation_end_date from the request and
    transitions the unit's status from VACANT to UNDER_RENOVATION.'
    """

    def test_start_renovation_transitions_to_under_renovation(self, api):
        """PRD §3.1: 'transitions the unit's status from VACANT to
        UNDER_RENOVATION.'

        Per PRD §3.1 derivation cascade, the status is UNDER_RENOVATION
        only while the current server date falls inside the closed
        interval [renovation_start_date, renovation_end_date]; we
        advance the logical clock to renovation_start_date so the
        derivation reflects the renovation as active.
        """
        b, u = setup_building_with_unit()
        advance_clock("2026-03-01T00:00:00.000Z")
        res = api.start_renovation(
            b["id"], u["id"],
            start_renovation_payload(
                renovation_start_date="2026-03-01T00:00:00.000Z",
                renovation_end_date="2026-03-15T00:00:00.000Z",
            ),
            PM,
        )
        data = validate_success(res)
        assert data["status"] == "UNDER_RENOVATION"

    def test_start_renovation_on_non_vacant_unit_rejected(self, api):
        """PRD §3.1: 'The request is rejected with ERR_INVALID_STATE if
        the unit is not currently VACANT.'"""
        b, u = setup_building_with_unit()
        # Advance clock so the renovation interval is active (derivation
        # rule requires current server date inside the closed interval).
        advance_clock("2026-03-01T00:00:00.000Z")
        # First start a renovation → UNDER_RENOVATION
        start_renovation(
            b["id"], u["id"],
            "2026-03-01T00:00:00.000Z",
            "2026-03-15T00:00:00.000Z",
        )
        # Try to start another renovation while UNDER_RENOVATION
        res = api.start_renovation(
            b["id"], u["id"],
            start_renovation_payload(
                renovation_start_date="2026-04-01T00:00:00.000Z",
                renovation_end_date="2026-04-15T00:00:00.000Z",
            ),
            PM,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_start_renovation_end_before_start_rejected(self, api):
        """PRD §3.1: 'with ERR_INVALID_DATE_RANGE if renovation_end_date
        is not strictly later than renovation_start_date.'"""
        b, u = setup_building_with_unit()
        res = api.start_renovation(
            b["id"], u["id"],
            start_renovation_payload(
                renovation_start_date="2026-03-15T00:00:00.000Z",
                renovation_end_date="2026-03-01T00:00:00.000Z",
            ),
            PM,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_DATE_RANGE.value)

    def test_finish_renovation_transitions_to_vacant(self, api):
        """PRD §3.1: 'Closing the renovation transitions the unit back
        to VACANT and clears both renovation dates.'"""
        b, u = setup_building_with_unit()
        start_renovation(
            b["id"], u["id"],
            "2026-03-01T00:00:00.000Z",
            "2026-03-15T00:00:00.000Z",
        )
        res = api.finish_renovation(b["id"], u["id"], PM)
        data = validate_success(res)
        assert data["status"] == "VACANT"


# ===========================================================================
# Unit split
# ===========================================================================
class TestUnitSplit:
    """PRD §3.1: 'Splitting a VACANT unit retires it and creates one
    new Unit per child specification. Each child specifies its own
    area_sqm, code, and other unit fields.'
    """

    def test_split_retires_parent_and_creates_children(self, api):
        """PRD §3.1: 'On success, the parent's status becomes RETIRED;
        each child is persisted with status VACANT, with its
        parent_unit_id pointing at the retired parent's id, with its
        building_id inherited from the parent, and with its
        rent_reference_per_sqm inherited from the parent.'"""
        b = create_building()
        parent = create_unit(b["id"], area_sqm=100.0,
                             rent_reference_per_sqm=120.0)
        res = api.split_unit(
            b["id"], parent["id"],
            split_unit_payload(child_units=[
                make_child_unit_spec(
                    area_sqm=40.0, code=unique_unit_code("c1"),
                ),
                make_child_unit_spec(
                    area_sqm=60.0, code=unique_unit_code("c2"),
                ),
            ]),
            PM,
        )
        body = res.json()
        assert res.status_code == 201, (
            f"expected 201, got {res.status_code}: {body}"
        )
        children = body["data"]
        assert isinstance(children, list) and len(children) == 2
        for c in children:
            assert c["status"] == "VACANT"
            assert c["parent_unit_id"] == parent["id"]
            assert c["building_id"] == b["id"]
            # Inherited reference rent (PRD prose)
            assert float(c["rent_reference_per_sqm"]) == 120.0

        # Parent is RETIRED
        parent_after = validate_success(
            api.get_unit(b["id"], parent["id"], PM),
        )
        assert parent_after["status"] == "RETIRED"

    def test_split_area_sum_mismatch_rejected(self, api):
        """PRD §3.1: 'with ERR_AREA_SUM_MISMATCH if the sum of
        child_units[].area_sqm does not equal the parent's area_sqm
        exactly when both are compared to 2 decimal places.'"""
        b = create_building()
        parent = create_unit(b["id"], area_sqm=100.0)
        res = api.split_unit(
            b["id"], parent["id"],
            split_unit_payload(child_units=[
                make_child_unit_spec(area_sqm=40.0,
                                     code=unique_unit_code("c1")),
                make_child_unit_spec(area_sqm=50.0,
                                     code=unique_unit_code("c2")),
            ]),
            PM,
        )
        validate_error(res, ApiErrorId.ERR_AREA_SUM_MISMATCH.value)

    def test_split_child_code_conflict_rejected(self, api):
        """PRD §3.1: 'with ERR_UNIT_CODE_CONFLICT if any child's code
        is already taken inside the same building.'"""
        b = create_building()
        existing = create_unit(b["id"])
        parent = create_unit(b["id"], area_sqm=100.0)
        res = api.split_unit(
            b["id"], parent["id"],
            split_unit_payload(child_units=[
                make_child_unit_spec(area_sqm=50.0,
                                     code=existing["code"]),
                make_child_unit_spec(area_sqm=50.0,
                                     code=unique_unit_code()),
            ]),
            PM,
        )
        validate_error(res, ApiErrorId.ERR_UNIT_CODE_CONFLICT.value)

    def test_split_non_vacant_parent_rejected(self, api):
        """PRD §3.1: 'The operation is rejected with ERR_INVALID_STATE
        unless the parent is VACANT.'"""
        b, u = setup_building_with_unit()
        advance_clock("2026-03-01T00:00:00.000Z")
        start_renovation(
            b["id"], u["id"],
            "2026-03-01T00:00:00.000Z",
            "2026-03-15T00:00:00.000Z",
        )
        res = api.split_unit(
            b["id"], u["id"],
            split_unit_payload(child_units=[
                make_child_unit_spec(area_sqm=50.0),
                make_child_unit_spec(area_sqm=50.0),
            ]),
            PM,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_split_emits_unit_split_audit_event(self, api):
        """PRD §3.1: 'An AuditEvent is recorded with subject_kind UNIT
        and action UNIT_SPLIT.'"""
        b = create_building()
        parent = create_unit(b["id"], area_sqm=100.0)
        api.split_unit(
            b["id"], parent["id"],
            split_unit_payload(child_units=[
                make_child_unit_spec(area_sqm=50.0,
                                     code=unique_unit_code("ca")),
                make_child_unit_spec(area_sqm=50.0,
                                     code=unique_unit_code("cb")),
            ]),
            PM,
        )
        rows = list_audit_events(
            subject_kind="UNIT", subject_id=parent["id"],
            action="UNIT_SPLIT",
        )
        assert len(rows) >= 1, (
            "Expected at least one AuditEvent with action UNIT_SPLIT"
        )
        for r in rows:
            assert_audit_event(r)
            assert r["subject_kind"] == "UNIT"
            assert r["action"] == "UNIT_SPLIT"


# ===========================================================================
# Unit merge
# ===========================================================================
class TestUnitMerge:
    """PRD §3.1: 'Merging two or more vacant units retires them in
    favour of a new unit. ... Each unit referenced by source_unit_ids
    must have status VACANT (otherwise ERR_INVALID_STATE) and all
    sources must share the same building_id and floor (otherwise
    ERR_MERGE_LAYOUT_INVALID).'
    """

    def test_merge_two_vacant_same_floor_units(self, api):
        """PRD §3.1: 'a new Unit is persisted with area_sqm equal to
        the sum of the sources' area_sqm, with code taken from the
        request's merged_code, with parent_unit_id of null, with
        status VACANT, and with rent_reference_per_sqm set to the
        area-weighted average of the sources' reference rents, rounded
        half-up to 2 decimal places.'"""
        b, u_a, u_b = setup_building_with_two_units(
            area_sqm_a=40.0, area_sqm_b=60.0,
        )
        # Make their reference rents differ so the weighting matters:
        # we can't update them via API, but the helper sets both to the
        # default 100.0; we re-create with explicit values.
        b2 = create_building()
        u1 = create_unit(b2["id"], code=unique_unit_code("a"),
                         area_sqm=40.0, floor=1,
                         rent_reference_per_sqm=100.00)
        u2 = create_unit(b2["id"], code=unique_unit_code("b"),
                         area_sqm=60.0, floor=1,
                         rent_reference_per_sqm=200.00)
        merged_code = unique_unit_code("M")
        res = api.merge_units(
            b2["id"],
            merge_units_payload(
                source_unit_ids=[u1["id"], u2["id"]],
                merged_code=merged_code,
            ),
            PM,
        )
        body = res.json()
        assert res.status_code == 201, body
        new_unit = body["data"]
        assert new_unit["status"] == "VACANT"
        assert new_unit["code"] == merged_code
        assert new_unit["parent_unit_id"] is None
        assert float(new_unit["area_sqm"]) == pytest.approx(100.0)
        # Area-weighted average: (40*100 + 60*200) / 100 = 160.00
        assert float(new_unit["rent_reference_per_sqm"]) == pytest.approx(
            160.00, abs=0.01,
        )

        # Sources are RETIRED
        for src in (u1, u2):
            data = validate_success(api.get_unit(b2["id"], src["id"], PM))
            assert data["status"] == "RETIRED"

    def test_merge_different_floors_rejected(self, api):
        """PRD §3.1: 'with ERR_MERGE_LAYOUT_INVALID ... all sources
        must share the same building_id and floor.'"""
        b = create_building(floors_count=5)
        u1 = create_unit(b["id"], floor=1, code=unique_unit_code("a"))
        u2 = create_unit(b["id"], floor=2, code=unique_unit_code("b"))
        res = api.merge_units(
            b["id"],
            merge_units_payload(
                source_unit_ids=[u1["id"], u2["id"]],
                merged_code=unique_unit_code("M"),
            ),
            PM,
        )
        validate_error(res, ApiErrorId.ERR_MERGE_LAYOUT_INVALID.value)

    def test_merge_non_vacant_source_rejected(self, api):
        """PRD §3.1: 'Each unit referenced by source_unit_ids must
        have status VACANT (otherwise ERR_INVALID_STATE).'"""
        b = create_building(floors_count=3)
        u1 = create_unit(b["id"], floor=1, code=unique_unit_code("a"))
        u2 = create_unit(b["id"], floor=1, code=unique_unit_code("b"))
        advance_clock("2026-03-01T00:00:00.000Z")
        # Push u1 into UNDER_RENOVATION
        start_renovation(
            b["id"], u1["id"],
            "2026-03-01T00:00:00.000Z",
            "2026-03-15T00:00:00.000Z",
        )
        res = api.merge_units(
            b["id"],
            merge_units_payload(
                source_unit_ids=[u1["id"], u2["id"]],
                merged_code=unique_unit_code("M"),
            ),
            PM,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_merge_emits_unit_merged_audit_event(self, api):
        """PRD §3.1: 'An AuditEvent with action UNIT_MERGED records the
        operation.'"""
        b, u1, u2 = setup_building_with_two_units()
        api.merge_units(
            b["id"],
            merge_units_payload(
                source_unit_ids=[u1["id"], u2["id"]],
                merged_code=unique_unit_code("M"),
            ),
            PM,
        )
        rows = list_audit_events(action="UNIT_MERGED")
        # Find one whose subject is among the merged sources or the
        # new unit (PRD does not pin which); just confirm at least one
        # UNIT_MERGED row exists since this test created exactly one
        # merge — for cleanliness we narrow to UNIT kind.
        unit_rows = [r for r in rows if r["subject_kind"] == "UNIT"]
        assert len(unit_rows) >= 1
