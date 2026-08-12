"""Validation priority on submit and optimistic concurrency on the two OCC-guarded
writes (PRD §2.6, §2.7, §3.3)."""
import pytest

from test_helpers import (
    api_client,
    create_application_record,
    get_application_record,
    make_organizer_headers,
    patch_application_record,
    setup_draft_application,
    submit_application_record,
    validate_error,
    validate_success,
)


class TestStateBeatsTemporalOnSubmit:
    def _deficient_petition_with_short_lead_app(self, api):
        ctx = setup_draft_application(
            clock="2026-06-01T12:00:00Z",
            outcome="deficient",
            application_overrides={
                "event_start_at": "2026-06-04T14:00:00Z",  # only 3 days of CITY lead
                "event_end_at": "2026-06-04T18:00:00Z",
            },
        )
        return ctx

    def test_petition_state_error_wins_over_lead_time(self, api):
        """PRD §2.6: "the platform evaluates validation classes in a fixed priority order,
        and the earliest failing class determines the error returned."
        PRD §2.6: "**State gates** — the target resource is in a state that permits the
        transition, including cross-entity state gates such as a petition being `VERIFIED`".
        PRD §2.6: "**Temporal rules** — event window shape, jurisdiction lead time, the
        day-of-week sound cutoff, the dispatch window, the report window, and insurance
        expiry".
        PRD §3.3: "First, the backing petition must be `VERIFIED` (else
        `ERR_PETITION_NOT_VERIFIED`)."

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_temporal_on_submit
        """
        ctx = self._deficient_petition_with_short_lead_app(api)
        application, organizer = ctx["application"], ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])
        res = api.submit_permit_application(application["id"], headers)
        validate_error(res, "ERR_PETITION_NOT_VERIFIED")
        current = validate_success(api.get_permit_application(application["id"], headers), 200)
        assert current["status"] == "DRAFT"

    def test_temporal_error_fires_once_state_passes(self, api):
        """PRD §2.6: "the platform evaluates validation classes in a fixed priority order,
        and the earliest failing class determines the error returned."
        PRD §3.3: "the event must start no sooner than the required notice period measured
        from the logical clock — 14 days for a `CITY` segment, 28 days for `COUNTY`, and 45
        days for `STATE_ROUTE` — with an event starting exactly at the deadline passing, and
        anything earlier rejected as `ERR_LEAD_TIME_INSUFFICIENT`."

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_temporal_on_submit
        """
        # Same short lead but the petition is VERIFIED: the temporal class now reports.
        ctx = setup_draft_application(
            clock="2026-06-01T12:00:00Z",
            outcome="verified",
            application_overrides={
                "event_start_at": "2026-06-04T14:00:00Z",
                "event_end_at": "2026-06-04T18:00:00Z",
            },
        )
        application, organizer = ctx["application"], ctx["organizer"]
        res = api.submit_permit_application(application["id"], make_organizer_headers(organizer["id"]))
        validate_error(res, "ERR_LEAD_TIME_INSUFFICIENT")


class TestOptimisticConcurrency:
    def test_stale_patch_rejected_412(self, api):
        """PRD §2.7: "**Updating a DRAFT application.** The request must carry
        `expected_application_version` equal to the application's current `version`. If
        another writer has advanced the application's version since the caller last read it,
        the update is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412), since any
        intervening mutation — including an insurance-certificate creation, which also bumps
        the application's version — invalidates the caller's view."

        Design: Corner/validations/occ_stale_patch_returns_412
        """
        ctx = setup_draft_application(outcome="collecting", signatures=[])
        application, organizer = ctx["application"], ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])
        observed_version = application["version"]

        patched = patch_application_record(
            application["id"], organizer,
            {"expected_application_version": observed_version, "expected_attendance": 60},
        )
        assert patched["version"] == observed_version + 1
        assert patched["expected_attendance"] == 60

        # Replaying the pre-PATCH version is stale now.
        res = api.patch_permit_application(
            application["id"],
            {"expected_application_version": observed_version, "expected_attendance": 70},
            headers,
        )
        validate_error(res, "ERR_STALE_APPLICATION_VERSION")
        current = validate_success(api.get_permit_application(application["id"], headers), 200)
        assert current["expected_attendance"] == 60

    def test_stale_insurance_create_rejected_412(self, api):
        """PRD §2.7: "**Creating an insurance record.** The request must likewise carry
        `expected_application_version` matching the application's current `version`. Because
        creating a record supersedes the application's prior unresolved insurance record, a
        stale value is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412): another
        writer has mutated the application, possibly superseding the very insurance record
        the caller saw, since the caller last observed it."

        Design: Corner/validations/occ_stale_insurance_create_returns_412
        """
        ctx = setup_draft_application()
        application, organizer = ctx["application"], ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])
        version_at_create = application["version"]
        # Submitting the application is an intervening mutation that bumps the version.
        submitted = submit_application_record(application, organizer)
        assert submitted["version"] == version_at_create + 1

        res = api.create_insurance_certificate(
            application["id"],
            {
                "kind": "CERTIFICATE",
                "expected_application_version": version_at_create,
                "insurer_name": "Acme Mutual",
                "policy_number": "P-130",
                "coverage_amount_cents": 100000000,
                "expires_on": "2026-12-31",
            },
            headers,
        )
        validate_error(res, "ERR_STALE_APPLICATION_VERSION")
