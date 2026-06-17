"""Draws: the waterfall cap, draw sequencing, segregation of duties, OCC, and
total_drawn reconciliation. Covers §3.11, §2.7, validation priorities 13/14/15.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_approved_project,
    submit_review_approve_change_order,
    request_draw, release_draw, request_and_release_draw, project_version,
    create_draw_payload, release_draw_payload,
    make_finance_officer_headers,
    TEST_USERS, COMBO_840_SEGMENTS,
)

PM = TEST_USERS["project_manager_headers"]


class TestDrawCapBoundary:
    """Non-final cap = round(committed * 0.90, 2). Boundary X-0.01 / X."""

    def test_draw_at_cap_releases(self, api):
        """PRD §3.11: "The release is allowed only when the project's
        total_drawn_amount plus this draw's amount is at most the applicable cap;
        if it would exceed the cap, the release is refused with
        ERR_DRAW_EXCEEDS_CONTRACT (HTTP 409)."
        PRD §3.11: "When all guards pass, the draw moves to RELEASED, its
        released_by_user_id is set to the acting officer's X-User-ID, the
        project's total_drawn_amount is recomputed as the sum of amount over all
        RELEASED draws, and both the draw's and the project's version increment."

        Design: Corner/validations/draw_at_cap_boundary_releases
        """
        proj, est = create_approved_project(segments=COMBO_840_SEGMENTS, site_name="CapOk")
        # committed 12452.50; non-final cap round(12452.50*0.90,2) == 11207.25.
        draw = request_draw(proj["id"], "PROGRESS", 11207.25, "fin_5")
        released = release_draw(proj["id"], draw["id"], "fin_5")
        assert released["status"] == "RELEASED"
        project = get_success_data(api.get_project(proj["id"], PM))
        assert project["total_drawn_amount"] == 11207.25

    def test_draw_one_cent_over_cap_rejected(self, api):
        """PRD §3.11: "For a DEPOSIT or PROGRESS draw the cap is the
        committed_contract_value multiplied by 0.90 - that is, committed value
        less a ten-percent retainage - rounded to two decimal places."
        PRD §3.11: "The release is allowed only when the project's
        total_drawn_amount plus this draw's amount is at most the applicable cap;
        if it would exceed the cap, the release is refused with
        ERR_DRAW_EXCEEDS_CONTRACT (HTTP 409)."

        Design: Corner/validations/draw_exceeds_contract_at_cap_boundary
        """
        proj, est = create_approved_project(segments=COMBO_840_SEGMENTS, site_name="Cap")
        # cap == 11207.25; 11207.26 (cap + 0.01) must be refused.
        draw = request_draw(proj["id"], "PROGRESS", 11207.26, "fin_4")
        pv = project_version(proj["id"])
        res = api.release_draw(draw["id"], release_draw_payload(pv),
                               make_finance_officer_headers("fin_4"))
        validate_error(res, "ERR_DRAW_EXCEEDS_CONTRACT")


class TestDrawSequence:
    def test_second_deposit_release_rejected(self, api):
        """PRD §3.11: "At most one DEPOSIT draw may ever be released on a project,
        so a second DEPOSIT release is refused."
        PRD §3.11: "A violation of either sequencing rule yields
        ERR_DRAW_SEQUENCE_INVALID (HTTP 409)."

        Design: Corner/validations/draw_sequence_second_deposit_invalid
        """
        proj, est = create_approved_project(segments=COMBO_840_SEGMENTS, site_name="Dep2")
        request_and_release_draw(proj["id"], "DEPOSIT", 2000.00, "fin_3")
        d2 = request_draw(proj["id"], "DEPOSIT", 1000.00, "fin_3")
        pv = project_version(proj["id"])
        res = api.release_draw(d2["id"], release_draw_payload(pv),
                               make_finance_officer_headers("fin_3"))
        validate_error(res, "ERR_DRAW_SEQUENCE_INVALID")


class TestSegregationOfDuties:
    def test_segregation_beats_fiscal_cap(self, api):
        """PRD §2.6: "Checks specific to a single workflow - the weather gate, the
        cure-window timer, crew and equipment double-booking, segregation of
        duties, the draw waterfall cap, and the draw sequence rule - are evaluated
        after these foundational checks, as described in the workflows that own
        them; their relative ordering is detailed where each rule is introduced."
        PRD §3.11: "Segregation of duties applies in the mirror direction of
        change-order approval: the releasing FinanceOfficer's X-User-ID must not
        equal the submitted_by_user_id of any APPROVED change order on the
        project, and a breach yields ERR_SEGREGATION_VIOLATION (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/draw_release_segregation_beats_fiscal_cap
        """
        proj, est = create_approved_project(segments=COMBO_840_SEGMENTS, site_name="Seg A")
        # fin_1 approves a change order; fin_1 then also attempts to release a draw
        # whose 99999.00 amount is above any cap. Segregation (403) must win over cap (409).
        submit_review_approve_change_order(proj["id"], "add curb", 1000.00, "fin_1")
        draw = request_draw(proj["id"], "PROGRESS", 99999.00, "fin_1")
        pv = project_version(proj["id"])
        res = api.release_draw(draw["id"], release_draw_payload(pv),
                               make_finance_officer_headers("fin_1"))
        validate_error(res, "ERR_SEGREGATION_VIOLATION")

    def test_release_by_change_order_approver_violates_segregation(self, api):
        """PRD §3.11: "Segregation of duties applies in the mirror direction of
        change-order approval: the releasing FinanceOfficer's X-User-ID must not
        equal the submitted_by_user_id of any APPROVED change order on the project,
        and a breach yields ERR_SEGREGATION_VIOLATION (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/draw_release_segregation_beats_fiscal_cap
        """
        proj, est = create_approved_project(segments=COMBO_840_SEGMENTS, site_name="Seg B")
        # The same fin_1 submitted (and approved) the change order; a within-cap draw
        # of 100.00 by fin_1 is still refused purely on segregation grounds.
        submit_review_approve_change_order(proj["id"], "add curb", 1000.00, "fin_1")
        draw = request_draw(proj["id"], "PROGRESS", 100.00, "fin_1")
        pv = project_version(proj["id"])
        res = api.release_draw(draw["id"], release_draw_payload(pv),
                               make_finance_officer_headers("fin_1"))
        validate_error(res, "ERR_SEGREGATION_VIOLATION")


class TestDrawReleaseOcc:
    def test_release_with_stale_project_version_rejected(self, api):
        """PRD §2.7: "When a FinanceOfficer releases a draw, the request must
        likewise carry expected_project_version matching the project's current
        version."
        PRD §2.7: "a stale view would let the waterfall cap be evaluated against an
        outdated draw total, so the release is refused with
        ERR_STALE_PROJECT_VERSION (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_draw_release_stale
        """
        proj, est = create_approved_project(segments=COMBO_840_SEGMENTS, site_name="Occ2")
        d1 = request_draw(proj["id"], "DEPOSIT", 2000.00, "fin_7")
        stale_version = project_version(proj["id"])
        request_draw(proj["id"], "PROGRESS", 3000.00, "fin_7")  # bumps version
        res = api.release_draw(d1["id"], release_draw_payload(stale_version),
                               make_finance_officer_headers("fin_7"))
        validate_error(res, "ERR_STALE_PROJECT_VERSION")


def test_total_drawn_reconciles_over_two_releases(api):
    """PRD §3.11: "When all guards pass, the draw moves to RELEASED, its
    released_by_user_id is set to the acting officer's X-User-ID, the project's
    total_drawn_amount is recomputed as the sum of amount over all RELEASED draws,
    and both the draw's and the project's version increment."

    Design: Corner/cross_cutting_complexity_layers/derived_total_drawn_reconciliation
    """
    proj, est = create_approved_project(segments=COMBO_840_SEGMENTS, site_name="Recon")
    request_and_release_draw(proj["id"], "DEPOSIT", 2000.00, "fin_8")
    request_and_release_draw(proj["id"], "PROGRESS", 3000.00, "fin_8")
    project = get_success_data(api.get_project(proj["id"], PM))
    assert project["total_drawn_amount"] == 5000.00
