"""Construction windows: half-open permit overlap, closed blackouts, contractor OCC."""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, ApiErrorId,
    create_blackout_payload, create_contractor_change_payload,
    create_association, register_owner, register_property, register_committee,
    create_under_review_application, decide, read_application, read_property,
    get_single_permit, set_logical_clock, setup_approved_with_permit,
)

MANAGER = TEST_USERS["manager_headers"]
EPOCH = "2026-05-01T09:00:00Z"


def _overlap_scenario(api):
    """Permit1 ACTIVE [2026-06-01, 2026-07-01); app2 and app3 UNDER_REVIEW with ballots."""
    assoc = create_association(name="Overlap HOA")
    owner = register_owner(assoc["id"], full_name="Ann A", email="ann.a@x.com")
    committee = register_committee(assoc["id"], count=3)
    prop = register_property(assoc["id"], owner["id"], lot_number="O-1",
                             address="1 Overlap Ave")
    set_logical_clock(EPOCH)
    app1 = create_under_review_application(
        prop["id"], owner, committee, project_type="ROOF",
        guideline_section="SEC-7.1", description="roof",
        requested_window_start="2026-06-01", requested_window_end="2026-07-01")
    decide(app1["id"], conditions=[])
    app2 = create_under_review_application(
        prop["id"], owner, committee, project_type="PAINT",
        guideline_section="SEC-3.1", description="repaint",
        requested_window_start="2026-06-15", requested_window_end="2026-07-15")
    app3 = create_under_review_application(
        prop["id"], owner, committee, project_type="OTHER",
        guideline_section="SEC-5.0", description="xeriscape",
        requested_window_start="2026-07-01", requested_window_end="2026-08-01")
    return {"association": assoc, "applicant": owner, "committee": committee,
            "property": prop, "app1": app1, "app2": app2, "app3": app3}


class TestPermitWindowHalfOpenSemantics:
    """Permit windows are half-open [start, end): interior overlap conflicts, adjacency not."""

    def test_interior_overlap_rejected(self, api):
        """A window starting inside another ACTIVE permit's window is rejected.

        PRD §2.8: "Two windows on the same property conflict when each window starts
        before the other ends — that is, the first window's start is earlier than
        the second window's end and the second window's start is earlier than the
        first window's end."
        PRD §3.4: "An approving decision must also clear the requested window against
        the construction calendar before it lands: first overlap against the other
        `ACTIVE` permits of the same property, half-open semantics, surfacing as
        `ERR_WINDOW_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/permit_window_half_open_overlap_and_adjacency
        """
        sc = _overlap_scenario(api)
        res = api.decide_application(sc["app2"]["id"], {"conditions": []}, MANAGER)
        validate_error(res, ApiErrorId.ERR_WINDOW_OVERLAP)
        assert read_application(sc["app2"]["id"])["status"] == "UNDER_REVIEW"

    def test_adjacent_window_allowed(self, api):
        """start == the existing window's end does not conflict under half-open semantics.

        PRD §2.8: "Adjacency is allowed: when one window's end equals the other's
        start, the two windows do not conflict."
        PRD §2.5: "`open_permit_count` is the number of construction permits in
        `ACTIVE` status linked, through applications, to the property."

        Design: Difficulty/resource_temporal_overlap/permit_window_half_open_overlap_and_adjacency
        """
        sc = _overlap_scenario(api)
        decided = decide(sc["app3"]["id"], conditions=[])
        assert decided["status"] == "APPROVED_WITH_CONDITIONS"
        prop = read_property(sc["property"]["id"])
        assert prop["open_permit_count"] == 2


def _blackout_scenario(api):
    """Blackout [2026-06-20, 2026-06-27]; app1 starts 06-27, app2 starts 06-28."""
    assoc = create_association(name="Blackout HOA")
    owner = register_owner(assoc["id"], full_name="Ann A", email="ann.a@x.com")
    committee = register_committee(assoc["id"], count=3)
    prop1 = register_property(assoc["id"], owner["id"], lot_number="BL-1",
                              address="1 Blackout Blvd")
    prop2 = register_property(assoc["id"], owner["id"], lot_number="BL-2",
                              address="2 Blackout Blvd")
    validate_success(api.create_blackout(assoc["id"], create_blackout_payload(
        "2026-06-20", "2026-06-27", reason="street repaving moratorium"),
        MANAGER), 201)
    set_logical_clock(EPOCH)
    app1 = create_under_review_application(
        prop1["id"], owner, committee, project_type="FENCE",
        guideline_section="SEC-4.2", description="fence",
        requested_window_start="2026-06-27", requested_window_end="2026-07-27")
    app2 = create_under_review_application(
        prop2["id"], owner, committee, project_type="FENCE",
        guideline_section="SEC-4.2", description="fence",
        requested_window_start="2026-06-28", requested_window_end="2026-07-28")
    return {"association": assoc, "applicant": owner, "committee": committee,
            "prop1": prop1, "prop2": prop2, "app1": app1, "app2": app2}


class TestBlackoutClosedIntervalSemantics:
    """Blackouts are closed intervals: the final day is inside the blackout."""

    def test_window_starting_on_blackout_end_conflicts(self, api):
        """A window whose start equals the blackout's end_date still conflicts.

        PRD §2.8: "Because the blackout's final day is inside the blackout, a window
        whose start equals that final day conflicts with the blackout — a deliberate
        asymmetry with permit-permit adjacency, where touching endpoints never
        conflict."
        PRD §2.9: "then (8b) blackout conflict against the association's blackout
        calendar, closed-interval semantics, yielding `ERR_BLACKOUT_CONFLICT` (422)"

        Design: Difficulty/resource_temporal_overlap/blackout_closed_interval_boundary_conflict
        """
        sc = _blackout_scenario(api)
        res = api.decide_application(sc["app1"]["id"], {"conditions": []}, MANAGER)
        validate_error(res, ApiErrorId.ERR_BLACKOUT_CONFLICT)
        assert read_application(sc["app1"]["id"])["status"] == "UNDER_REVIEW"

    def test_window_starting_day_after_blackout_allowed(self, api):
        """A window starting the day after the closed blackout's end clears the check.

        PRD §2.8: "A permit window conflicts with a blackout when the window's start
        is on or before the blackout's end date and the window's end is after the
        blackout's start date."

        Design: Difficulty/resource_temporal_overlap/blackout_closed_interval_boundary_conflict
        """
        sc = _blackout_scenario(api)
        decided = decide(sc["app2"]["id"], conditions=[])
        assert decided["status"] == "APPROVED_WITH_CONDITIONS"


class TestContractorChange:
    """Contractor change on an ACTIVE permit carries expected_permit_version (OCC)."""

    def test_contractor_change_success_bumps_version(self, api):
        """With the current version supplied, the change stores the contractor fields.

        PRD §3.7: "A `Manager` sets or replaces the contractor details by supplying
        `contractor_name` and `contractor_license`; the request must carry
        `expected_permit_version` under §2.10, with a mismatch rejected as
        `ERR_STALE_VERSION`, and a successful change increments the permit's
        `version` by one."

        Design: Corner/endpoints/contractor_change_success_bumps_version
        """
        bundle = setup_approved_with_permit()
        permit = bundle["permit"]
        res = api.change_contractor(permit["id"], create_contractor_change_payload(
            "Ace Roofing", "LIC-99887", permit["version"]), MANAGER)
        updated = validate_success(res, 200)
        assert updated["contractor_name"] == "Ace Roofing"
        assert updated["contractor_license"] == "LIC-99887"
        assert updated["version"] == permit["version"] + 1

    def test_contractor_change_stale_version_rejected(self, api):
        """A replayed stale expected_permit_version is rejected and the first write stands.

        PRD §2.10: "Changing the contractor on a construction permit likewise
        requires `expected_permit_version`, holding the permit `version` the client
        last observed. A mismatch with the permit's current `version` — for example
        because another writer changed the contractor or extended the window in the
        meantime — is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_contractor_change_stale_version_rejected
        """
        bundle = setup_approved_with_permit()
        permit = bundle["permit"]
        first = validate_success(api.change_contractor(
            permit["id"], create_contractor_change_payload(
                "Ace Roofing", "LIC-1", permit["version"]), MANAGER), 200)
        assert first["version"] == permit["version"] + 1

        replay = api.change_contractor(permit["id"], create_contractor_change_payload(
            "Beta Builders", "LIC-2", permit["version"]), MANAGER)
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)

        final = validate_success(api.get_permit(permit["id"], MANAGER), 200)
        assert final["contractor_name"] == "Ace Roofing"
        assert final["version"] == permit["version"] + 1
