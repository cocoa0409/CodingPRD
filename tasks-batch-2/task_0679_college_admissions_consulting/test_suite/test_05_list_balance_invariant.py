"""Difficulty queue: the school-list balance-lock conserved quantity — selecting
then dropping a fourth item returns the SELECTED count and Student.list_locked to
their pre-pair values.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    make_counselor_headers,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f


def _build_locked_list_with_extra_candidate():
    """Onboarded student with 3 SELECTED items (A safety, B target, C reach) so
    list_locked is true, plus a 4th item D also SELECTED. Returns
    (counselor, student, item_d_id) after D has been selected."""
    counselor, student = fx.setup_onboarded_student(
        student_overrides={"gpa": 3.5, "sat_total": 1300}
    )
    ch = make_counselor_headers(counselor["id"])
    version = student["version"]

    def add_and_select(school_name, admit_rate, median_sat, expected_version):
        item = get_success_data(
            api_client.create_school_list_item(
                f.create_school_list_item_payload(student["id"], school_name=school_name,
                                                  admit_rate=admit_rate, median_sat=median_sat,
                                                  round="RD"),
                ch,
            )
        )
        sel = get_success_data(
            api_client.select_school_list_item(
                item["id"], {"expected_student_version": expected_version}, ch
            )
        )
        return item, expected_version + 1

    # A: high admit_rate, low median => SAFETY.
    _a, version = add_and_select("Safety A", 0.70, 1100, version)
    # B: target.
    _b, version = add_and_select("Target B", 0.40, 1300, version)
    # C: reach.
    _c, version = add_and_select("Reach C", 0.10, 1550, version)
    # D: 4th selected.
    item_d, version = add_and_select("Extra D", 0.35, 1320, version)
    return counselor, student, item_d["id"]


def test_select_then_drop_fourth_item_conserves_lock(api):
    """PRD §3.2: "The list is locked — `list_locked` becomes true — exactly when
    there is at least one `SAFETY`, the total selected count is at least 3, and
    the number of `ED` selections is at most 1; otherwise `list_locked` is false."
    PRD §3.2: "Dropping an item likewise recomputes `list_locked`."

    Design: Difficulty/compensating_invariant/select_then_drop_conserves_selected_count_and_lock
    """
    counselor, student, item_d_id = _build_locked_list_with_extra_candidate()
    ch = make_counselor_headers(counselor["id"])
    dropped = validate_success(api.drop_school_list_item(item_d_id, ch))
    assert dropped["status"] == "DROPPED"
    student_after = validate_success(api.get_student(student["id"], ch))
    assert student_after["list_locked"] is True, (
        "after dropping the 4th item, 3 balanced selections remain so list_locked stays true"
    )


def test_dropped_item_leaves_three_selected_locked(api):
    """PRD §3.2: "Considering only the items in `SELECTED` status, the system
    counts how many are classified `SAFETY`, the total number selected, and how
    many carry a `round` of `ED`."
    PRD §3.2: "or a `CANDIDATE` or `SELECTED` item may be dropped, transitioning
    it to `DROPPED`."

    Design: Difficulty/compensating_invariant/select_then_drop_conserves_selected_count_and_lock
    """
    counselor, student, item_d_id = _build_locked_list_with_extra_candidate()
    ch = make_counselor_headers(counselor["id"])
    # Before the drop: 4 selected, list still locked (1 safety, total>=3, 0 ED).
    before = validate_success(api.get_student(student["id"], ch))
    assert before["list_locked"] is True
    get_success_data(api_client.drop_school_list_item(item_d_id, ch))
    # The remaining SELECTED set still satisfies the balance rule (3 items).
    from test_helpers import validate_paginated
    sel_list, _meta = validate_paginated(
        api.list_school_list_items(ch, params={"student_id": student["id"], "status": "SELECTED"})
    )
    assert len(sel_list) == 3
