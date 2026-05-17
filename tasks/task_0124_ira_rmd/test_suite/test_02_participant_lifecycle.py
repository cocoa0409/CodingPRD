"""Participant CRUD, decease, and optimistic concurrency.

Coverage targets (PRD §3.1, §2.5):
- POST /participants validation: full_name length, date_of_birth past
  + age >= 18, tax_status enum.
- PATCH /participants accepts full_name and tax_status only; OCC via
  version.
- POST /participants/{id}/decease flips is_deceased and records
  date_of_death.
- Subsequent non-RMD/non-DEATH ops on deceased participant ->
  ERR_PARTICIPANT_DECEASED.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_days,
    assert_participant,
    create_participant,
    create_participant_born,
    create_participant_payload,
    date_n_years_ago,
    decease_participant,
    decease_participant_payload,
    get_clock_state,
    iso_date_str,
    open_account,
    post_contribution,
    update_participant_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Create — PRD §3.1
# ===========================================================================
class TestCreateParticipant:

    def test_create_participant_success(self, api, custodian_headers):
        """PRD §3.1: "Registration captures the participant's legal
        full_name (a non-empty string of 1 to 120 characters after
        trimming whitespace), their date_of_birth as an ISO 8601
        calendar date in YYYY-MM-DD form ... and their IRS filing
        tax_status."

        Claim: valid POST /participants returns 201 with the
        Participant shape.
        """
        payload = create_participant_payload(
            full_name="Alice Smith",
            date_of_birth="1980-05-15",
            tax_status="SINGLE",
        )
        resp = api.create_participant(payload, custodian_headers)
        data = validate_success(resp, expected_status=201)
        assert_participant(data)
        assert data["full_name"] == "Alice Smith"
        assert data["date_of_birth"] == "1980-05-15"
        assert data["tax_status"] == "SINGLE"
        assert data["is_deceased"] is False
        assert data.get("date_of_death") is None
        assert data["version"] == 1

    @pytest.mark.parametrize(
        "bad_status",
        ["single", "MARRIED", "FOO", "married_joint"],
    )
    def test_invalid_tax_status_rejected(
        self, api, custodian_headers, bad_status,
    ):
        """PRD §3.1: "The four permissible values for tax_status are
        SINGLE, MARRIED_JOINT, MARRIED_SEPARATE, and HEAD_OF_HOUSEHOLD;
        any other value is rejected as a schema violation with
        ERR_VALIDATION."

        Claim: out-of-enum tax_status -> ERR_VALIDATION.
        """
        payload = create_participant_payload(tax_status=bad_status)
        resp = api.create_participant(payload, custodian_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_under_age_18_rejected(self, api, custodian_headers):
        """PRD §3.1: "which must place the participant at age 18 or
        older on the day of creation".

        Claim: date_of_birth less than 18 years ago -> ERR_VALIDATION.
        """
        too_young = iso_date_str(date_n_years_ago(17))
        payload = create_participant_payload(date_of_birth=too_young)
        resp = api.create_participant(payload, custodian_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_empty_full_name_rejected(self, api, custodian_headers):
        """PRD §3.1: "a non-empty string of 1 to 120 characters after
        trimming whitespace".

        Claim: empty full_name -> ERR_VALIDATION.
        """
        payload = create_participant_payload(full_name="   ")
        resp = api.create_participant(payload, custodian_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# Read — PRD §4
# ===========================================================================
class TestReadParticipant:

    def test_get_participant_returns_shape(self, api, custodian_headers):
        """PRD §4: "GET /participants/{participant_id} — Read a
        participant".

        Claim: GET returns the same Participant just created.
        """
        created = create_participant()
        resp = api.get_participant(created["id"], custodian_headers)
        data = validate_success(resp, expected_status=200)
        assert_participant(data)
        assert data["id"] == created["id"]


# ===========================================================================
# PATCH + OCC — PRD §3.1, §2.5
# ===========================================================================
class TestUpdateParticipant:

    def test_patch_updates_full_name(self, api, custodian_headers):
        """PRD §3.1: "A custodian may later amend a participant's
        full_name and tax_status; these are the only two fields the
        update operation accepts."

        Claim: PATCH full_name updates the field and increments version
        by exactly 1.
        """
        p = create_participant(full_name="Original Name")
        payload = update_participant_payload(
            full_name="New Name", version=p["version"],
        )
        resp = api.update_participant(p["id"], payload, custodian_headers)
        data = validate_success(resp, expected_status=200)
        assert data["full_name"] == "New Name"
        # PRD §2.4: version increments by exactly 1.
        assert data["version"] == p["version"] + 1

    def test_patch_stale_version_rejected(self, api, custodian_headers):
        """PRD §2.5: "If version is supplied but does not match the
        current value (because another writer has advanced it), the
        request is rejected with ERR_VERSION_CONFLICT."

        Claim: PATCH with stale version -> ERR_VERSION_CONFLICT.
        """
        p = create_participant()
        # First update advances version.
        api.update_participant(
            p["id"], update_participant_payload(
                full_name="V2", version=p["version"],
            ), custodian_headers,
        )
        # Second update reuses old version.
        resp = api.update_participant(
            p["id"], update_participant_payload(
                full_name="V3 stale", version=p["version"],
            ), custodian_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_patch_without_version_proceeds_unconditionally(
        self, api, custodian_headers,
    ):
        """PRD §2.5: "If version is omitted from the request body, the
        server skips the concurrency check and processes the mutation
        unconditionally."

        Claim: PATCH without version succeeds even after another writer
        advanced version.
        """
        p = create_participant()
        api.update_participant(
            p["id"], update_participant_payload(
                full_name="V2", version=p["version"],
            ), custodian_headers,
        )
        # Now omit version.
        resp = api.update_participant(
            p["id"],
            update_participant_payload(full_name="V3 forced"),
            custodian_headers,
        )
        data = validate_success(resp, expected_status=200)
        assert data["full_name"] == "V3 forced"


# ===========================================================================
# Decease — PRD §3.1, §2.11
# ===========================================================================
class TestDecease:

    def test_decease_flips_is_deceased(self, api, custodian_headers):
        """PRD §3.1: "When a participant passes away, a custodian
        records the death by submitting a date_of_death (ISO 8601
        date). This single action triggers the decease cascade
        described in §2.11: is_deceased flips to true, date_of_death
        is recorded".

        Claim: POST /decease sets is_deceased=true and stores
        date_of_death.
        """
        p = create_participant()
        clock = get_clock_state()
        dod = clock.get("current_date") or iso_date_str(
            date_n_years_ago(0),
        )
        resp = api.decease_participant(
            p["id"], decease_participant_payload(date_of_death=dod),
            custodian_headers,
        )
        data = validate_success(resp, expected_status=200)
        assert_participant(data)
        assert data["is_deceased"] is True
        assert data["date_of_death"] == dod

    def test_contribution_after_decease_rejected(
        self, api, custodian_headers,
    ):
        """PRD §3.1: "After this point any attempt to perform a non-RMD,
        non-DEATH operation that requires a live participant — posting
        a new contribution, opening a new conversion request, or
        approving a pending conversion — is rejected with
        ERR_PARTICIPANT_DECEASED."

        Claim: POST contribution after decease is blocked. The decease
        cascade also freezes the account (PRD §2.11), which would
        independently produce ERR_ACCOUNT_FROZEN; the test accepts
        either since PRD prose names both rules without strictly
        ordering them at this granularity.
        """
        from test_helpers import validate_error_is_one_of

        p = create_participant()
        a = open_account(p["id"], account_type="TRADITIONAL")
        clock = get_clock_state()
        dod = clock.get("current_date") or iso_date_str(
            date_n_years_ago(0),
        )
        decease_participant(p["id"], date_of_death=dod)

        resp = api.create_contribution(
            a["id"],
            {"amount_cents": 100_000, "contribution_type": "REGULAR"},
            custodian_headers,
        )
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_PARTICIPANT_DECEASED.value,
            ApiErrorId.ERR_ACCOUNT_FROZEN.value,
        ])
