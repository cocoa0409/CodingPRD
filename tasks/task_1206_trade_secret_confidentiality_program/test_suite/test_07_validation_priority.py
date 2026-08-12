"""Validation priority ordering: when one request violates several rules the
earliest applicable category wins (PRD §2.12)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_counterparty,
    create_active_nda,
    create_registered_asset,
    create_employee_record,
    create_active_employee,
    create_under_review_disclosure,
    create_grant_payload,
    make_employee_headers,
    make_ip_counsel_headers,
    TEST_USERS,
)

IP = TEST_USERS["ip_counsel_headers"]


def _setup_returned_disclosure_on_deficient_asset(api):
    """REGISTERED asset with NO measures (posture DEFICIENT); ACTIVE NDA;
    disclosure pushed to UNDER_REVIEW then RETURNED."""
    cp = create_counterparty(legal_name="Iota Labs", counterparty_type="PARTNER")
    nda = create_active_nda(
        cp["id"], template_version="t8", governing_law="WA",
        effective_date="2026-01-01T00:00:00Z", expiry_date="2027-01-01T00:00:00Z",
        survival_months=6, classification_ceiling="CROWN_JEWEL",
    )
    asset = create_registered_asset(
        title="Unprotected formula", description="no measures yet",
        classification="CONFIDENTIAL", owner_department="RND",
        exposure_estimate_cents=300000,
    )
    emp = create_employee_record(
        full_name="Nora Rnd", email="nora@x.com", department="RND",
        role_title="Scientist", access_clearance="STANDARD",
        hired_at="2026-05-01T00:00:00Z",
    )
    disc = create_under_review_disclosure(
        emp["id"], asset["id"], nda["id"],
        purpose="Eval", marking_protocol="STAMPED_CONFIDENTIAL",
        planned_disclosure_date="2026-07-01T00:00:00Z",
    )
    validate_success(api.transition_disclosure(disc["id"], {"to_status": "RETURNED"}, IP))
    return asset, nda, emp, disc


class TestApproveReturnedDisclosureStateBeatsPosture:
    def test_state_error_wins_over_posture_error(self, api):
        """PRD §2.12: "When a single request violates several rules, the error
        surfaced is the one from the earliest applicable category below — lower
        numbers win."
        PRD §2.12: "Sixth (6) state-machine preconditions: the transition must
        be defined from the current state and entity-level state gates must
        hold, else `ERR_INVALID_STATE`. Seventh (7) classification, need-to-know,
        and preservation safety gates, else `ERR_NEED_TO_KNOW_VIOLATION`,
        `ERR_CLASSIFICATION_CEILING_EXCEEDED`, `ERR_POSTURE_DEFICIENT`,
        `ERR_PRESERVATION_HOLD_ACTIVE`, `ERR_DISCLOSURE_RISK_TOO_HIGH`, or
        `ERR_ENDORSEMENT_REQUIRED`."

        Design: Difficulty/priority_pair_validation_conflict/approve_returned_disclosure_state_beats_posture
        """
        _asset, _nda, _emp, disc = _setup_returned_disclosure_on_deficient_asset(api)
        resp = api.transition_disclosure(
            disc["id"], {"to_status": "APPROVED"}, make_ip_counsel_headers("counsel_1")
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_failed_approval_leaves_disclosure_returned(self, api):
        """PRD §2.12: "Sixth (6) state-machine preconditions: the transition must
        be defined from the current state and entity-level state gates must
        hold, else `ERR_INVALID_STATE`."
        PRD §3.5: "Returning (`UNDER_REVIEW → RETURNED`) sends the request back
        for revision."

        Design: Difficulty/priority_pair_validation_conflict/approve_returned_disclosure_state_beats_posture
        """
        _asset, _nda, _emp, disc = _setup_returned_disclosure_on_deficient_asset(api)
        api.transition_disclosure(
            disc["id"], {"to_status": "APPROVED"}, make_ip_counsel_headers("counsel_1")
        )
        data = validate_success(api.get_disclosure(disc["id"], IP))
        assert data["status"] == "RETURNED", "no side effects may fire on the rejected approval"


class TestGrantCreateClearanceBeatsExpiry:
    def test_need_to_know_wins_over_expiry(self, api):
        """PRD §2.12: "When a single request violates several rules, the error
        surfaced is the one from the earliest applicable category below — lower
        numbers win."
        PRD §2.12: "Seventh (7) classification, need-to-know, and preservation
        safety gates... Eighth (8) time-window rules, else `ERR_DATE_ORDER`,
        `ERR_EXPIRY_IN_PAST`, `ERR_REVIEW_WINDOW_EXPIRED`,
        `ERR_NDA_WINDOW_OVERLAP`, `ERR_AUDIT_WINDOW_CONFLICT`, or
        `ERR_INTERVIEW_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/grant_create_clearance_beats_expiry
        """
        emp = create_active_employee(
            complete_training=True,
            full_name="Omar Temp", email="omar@x.com", department="OPS",
            role_title="Temp", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        asset = create_registered_asset(
            title="Core optimizer", description="solver internals",
            classification="CROWN_JEWEL", owner_department="AI",
            exposure_estimate_cents=999999,
        )
        resp = api.create_grant(
            create_grant_payload(emp["id"], asset["id"], justification="want access",
                                 expires_at="2026-04-01T00:00:00Z"),
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NEED_TO_KNOW_VIOLATION)

    def test_rejected_create_leaves_no_grant_row(self, api):
        """PRD §3.4: "the employee's `access_clearance` must meet the asset's
        classification requirement — `STANDARD` clearance covers `INTERNAL` and
        `CONFIDENTIAL` assets, `RESTRICTED` assets require `ELEVATED`, and
        `CROWN_JEWEL` assets require `PRIVILEGED` — otherwise
        `ERR_NEED_TO_KNOW_VIOLATION`."

        Design: Difficulty/priority_pair_validation_conflict/grant_create_clearance_beats_expiry
        """
        emp = create_active_employee(
            complete_training=True,
            full_name="Omar Temp", email="omar@x.com", department="OPS",
            role_title="Temp", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        asset = create_registered_asset(
            title="Core optimizer", description="solver internals",
            classification="CROWN_JEWEL", owner_department="AI",
            exposure_estimate_cents=999999,
        )
        api.create_grant(
            create_grant_payload(emp["id"], asset["id"], justification="want access",
                                 expires_at="2026-04-01T00:00:00Z"),
            make_employee_headers(emp["id"]),
        )
        data = validate_success(
            api.list_grants(TEST_USERS["security_officer_headers"],
                            params={"employee_id": emp["id"]})
        )
        assert isinstance(data, list) and len(data) == 0, \
            "the rejected request must create no AccessGrant row"
