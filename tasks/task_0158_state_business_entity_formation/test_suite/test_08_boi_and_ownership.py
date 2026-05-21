"""BeneficialOwner / BOIOwnership / BOIReport lifecycle and the
ownership-sum-100% rule, owner-age rule, and STALE transition.

Covers PRD §3.8.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    OWNERSHIP_FULL_BPS,
    TEST_USERS,
    add_boi_ownership,
    add_boi_ownership_payload,
    assert_beneficial_owner,
    assert_boi_ownership,
    assert_boi_report,
    assert_event_types_present,
    assert_status,
    create_and_activate_entity,
    create_beneficial_owner,
    create_beneficial_owner_payload,
    create_boi_report,
    create_boi_report_payload,
    date_only_utc,
    file_boi_report,
    iso_now,
    add_days,
    list_compliance_events,
    make_filer_headers,
    setup_entity_with_stale_boi,
    setup_initial_boi_filed,
    setup_owners_full_100,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# BeneficialOwner — PRD §3.8
# ---------------------------------------------------------------------------
class TestBeneficialOwner:

    def test_create_owner(self, api, filer_headers):
        """PRD §3.8: "supplied by the Filer with full_legal_name,
        date_of_birth, residential_address, identifying_document_type,
        and identifying_document_number."

        Claim: a valid owner returns 201 with the expected fields.
        """
        resp = api.create_beneficial_owner(
            create_beneficial_owner_payload(), filer_headers,
        )
        owner = validate_success(resp, expected_status=201)
        assert_beneficial_owner(owner)

    @pytest.mark.parametrize("bad_doc_type", ["DRIVERS_LICENSE",
                                              "PASSPORT", ""])
    def test_invalid_document_type_rejected(self, api,
                                            filer_headers,
                                            bad_doc_type):
        """PRD §3.8: "The identifying_document_type is exactly one of
        US_PASSPORT, STATE_DRIVERS_LICENSE, STATE_ID, or FOREIGN_PASSPORT."

        Claim: any other value → ERR_INVALID_INPUT.
        """
        payload = create_beneficial_owner_payload(
            identifying_document_type=bad_doc_type,
        )
        resp = api.create_beneficial_owner(payload, filer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)


# ---------------------------------------------------------------------------
# BOIOwnership — PRD §3.8
# ---------------------------------------------------------------------------
class TestBOIOwnership:

    def test_add_ownership_row_returns_append_only_envelope(self, api):
        """PRD §2.4 + §3.8: BOIOwnership rows "are mutated only by
        soft-delete which writes terminated_at" and the row carries only
        id and created_at.

        Claim: the returned row carries id + created_at, NO updated_at
        or version, and the input bps value.
        """
        entity, _ = create_and_activate_entity()
        owner = create_beneficial_owner()
        resp = api.add_boi_ownership(
            entity["id"],
            add_boi_ownership_payload(owner["id"], 5000),
            make_filer_headers(entity["id"]),
        )
        own = validate_success(resp, expected_status=201)
        assert_boi_ownership(own)
        assert own["ownership_percent_basis_points"] == 5000

    def test_delete_ownership_soft_deletes(self, api):
        """PRD §3.8: "removing an ownership row is a soft-delete that
        stamps terminated_at to the current clock instant rather than
        removing the row."
        PRD §4 table: "DELETE on BOIOwnership returns 204 with no body"

        Claim: DELETE returns 204.
        """
        entity, _ = create_and_activate_entity()
        owner = create_beneficial_owner()
        own = add_boi_ownership(entity["id"], owner["id"], 10000)
        resp = api.delete_boi_ownership(
            entity["id"], own["id"], make_filer_headers(entity["id"]),
        )
        assert resp.status_code == 204, (
            f"Expected 204 on DELETE boi-ownership, got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# BOIReport filing — PRD §3.8
# ---------------------------------------------------------------------------
class TestBOIReportFile:

    def test_initial_report_starts_in_draft(self, api):
        """PRD §3.8: "The report starts in DRAFT and may transition
        through FILED → CURRENT → (STALE ↔ CURRENT) → CORRECTED."

        Claim: created BOIReport starts in DRAFT.
        """
        entity, _ = create_and_activate_entity()
        resp = api.create_boi_report(
            create_boi_report_payload(entity["id"], "INITIAL"),
            make_filer_headers(entity["id"]),
        )
        rep = validate_success(resp, expected_status=201)
        assert_boi_report(rep)
        assert_status(rep, "DRAFT")

    def test_file_with_full_ownership_advances_to_current(self, api):
        """PRD §3.8: "On DRAFT → FILED the system records filed_at as
        the current clock instant and immediately auto-advances the row
        to CURRENT in the same logical transaction"

        Claim: filing with sum==10000 bps drives the report to CURRENT
        and emits BOI_FILED.
        """
        entity, _ = create_and_activate_entity()
        _owners, _ = setup_owners_full_100(entity["id"])
        rep = create_boi_report(entity["id"], "INITIAL")
        resp = api.file_boi_report(
            rep["id"], make_filer_headers(entity["id"]),
        )
        filed = validate_success(resp)
        # PRD §3.8 says CURRENT after the auto-advance.
        assert_status(filed, "CURRENT")
        assert filed.get("filed_at") is not None
        events = list_compliance_events(entity["id"])
        assert_event_types_present(events, ["BOI_FILED"])

    def test_file_with_ownership_sum_below_10000_rejected(self, api):
        """PRD §3.8: "the sum of active BOIOwnership.ownership_percent_
        basis_points rows for the entity ... must equal exactly 10,000
        at the moment of filing — a violation yields ERR_OWNERSHIP_NOT_100
        with HTTP 422"

        Claim: sum=9999 → ERR_OWNERSHIP_NOT_100.
        """
        entity, _ = create_and_activate_entity()
        owner = create_beneficial_owner()
        add_boi_ownership(entity["id"], owner["id"], 9999)
        rep = create_boi_report(entity["id"], "INITIAL")
        resp = api.file_boi_report(
            rep["id"], make_filer_headers(entity["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_NOT_100.value)

    def test_file_with_no_ownership_rejected(self, api):
        """PRD §3.8: "the sum of active BOIOwnership ... must equal
        exactly 10,000 at the moment of filing"

        Claim: sum=0 (no rows) → ERR_OWNERSHIP_NOT_100.
        """
        entity, _ = create_and_activate_entity()
        rep = create_boi_report(entity["id"], "INITIAL")
        resp = api.file_boi_report(
            rep["id"], make_filer_headers(entity["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_NOT_100.value)

    def test_file_with_underage_owner_rejected(self, api):
        """PRD §3.8: "The date_of_birth carries date-only semantics and
        must be at least eighteen years before the current clock
        instant — every owner included on a BOI report being filed
        must be at least 18 years old at the filing moment, and a
        younger owner yields ERR_OWNER_UNDERAGE with HTTP 422."

        Claim: an active owner with DOB < 18 years ago at /file →
        ERR_OWNER_UNDERAGE.
        """
        entity, _ = create_and_activate_entity()
        # DOB ~1 year ago.
        youngster = create_beneficial_owner(
            date_of_birth=add_days(iso_now(), -365),
        )
        # Even though sum=10000 makes ownership pass, the under-age
        # owner must trip ERR_OWNER_UNDERAGE.
        add_boi_ownership(entity["id"], youngster["id"], OWNERSHIP_FULL_BPS)
        rep = create_boi_report(entity["id"], "INITIAL")
        resp = api.file_boi_report(
            rep["id"], make_filer_headers(entity["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OWNER_UNDERAGE.value)


# ---------------------------------------------------------------------------
# BOI report STALE transition — PRD §3.8
# ---------------------------------------------------------------------------
class TestBOIStaleTransition:

    def test_entity_compliance_drops_after_boi_goes_stale(self, api):
        """PRD §3.8: "thirty days after the ownership change, if no
        UPDATE or CORRECTION BOIReport has been filed in the interim,
        the system transitions the report CURRENT → STALE, sets
        stale_at to the current clock instant, drives the entity's
        compliance_status from GOOD_STANDING to NOT_IN_GOOD_STANDING"

        Claim: after the 30-day stale-timer trips, the entity's
        compliance_status is NOT_IN_GOOD_STANDING and a BOI_STALE event
        was emitted.
        """
        entity, _, _ = setup_entity_with_stale_boi()
        assert entity["compliance_status"] == "NOT_IN_GOOD_STANDING", (
            f"After BOI goes stale, entity should be "
            f"NOT_IN_GOOD_STANDING, got {entity['compliance_status']}"
        )
        events = list_compliance_events(entity["id"])
        assert_event_types_present(events, ["BOI_STALE"])
