"""Waste profile segregation of duties and the depth-3 suspend cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_facility_and_approved_profile,
    create_issued_manifest,
    create_job_in_progress,
    create_manifest,
    create_disposal_facility_payload,
    create_site_payload,
    create_waste_profile_payload,
    get_success_data,
    make_environmental_approver_headers,
    validate_error,
)

AM = TEST_USERS["account_manager_headers"]
PA = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["project_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
EA = TEST_USERS["environmental_approver_headers"]


class TestProfileSegregationOfDuties:
    def test_approve_by_submitter_rejected(self, api):
        """PRD §3.6: "an approver whose `X-User-ID` equals `submitted_by` is
        rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/sod_profile_approve_by_submitter_rejected
        """
        site = get_success_data(api.create_site(create_site_payload(), AM))
        facility = get_success_data(
            api.create_disposal_facility(create_disposal_facility_payload(), PA)
        )
        profile = get_success_data(
            api.create_waste_profile(
                create_waste_profile_payload(site["id"], facility["id"]), CO
            )
        )
        get_success_data(api.submit_waste_profile(profile["id"], CO))
        # Approver carries the same X-User-ID ("co_1") as the submitter.
        resp = api.approve_waste_profile(
            profile["id"], make_environmental_approver_headers("co_1")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
        assert resp.status_code == 422
        after = get_success_data(api.get_waste_profile(profile["id"], PM))
        assert after["status"] == "SUBMITTED"


class TestProfileSuspendCascade:
    def _setup_full_facility(self, api):
        """Job IN_PROGRESS; profile APPROVED (density 8.0, WEIGHT); facility cap
        10.0t with one ISSUED manifest of 2500 gal -> reserved 10.0, FULL."""
        ctx = create_job_in_progress()
        facility, profile = create_facility_and_approved_profile(
            ctx["site"]["id"],
            profile_overrides={"density_lbs_per_gal": 8.0, "variance_basis": "WEIGHT"},
            facility_overrides={"total_capacity_tons": 10.0},
        )
        manifest = create_issued_manifest(ctx["job"]["id"], profile["id"], 2500)
        pre = get_success_data(api.get_disposal_facility(facility["id"], PM))
        assert pre["reserved_tons"] == pytest.approx(10.0)
        assert pre["posture"] == "FULL"
        ctx.update({"facility": facility, "profile": profile, "manifest": manifest})
        return ctx

    def test_suspend_voids_manifest_and_releases_reservation(self, api):
        """PRD §3.6: "suspension cascades in three linked steps: every manifest
        referencing the profile in `DRAFT` or `ISSUED` is voided; each `ISSUED`
        manifest so voided releases its facility reservation, subtracting its
        `estimated_tons` from the facility's `reserved_tons`; and each release
        recomputes the facility's `posture`."

        Design: Difficulty/transitive_cascade/profile_suspend_cascade_voids_manifests_releases_reservation
        """
        ctx = self._setup_full_facility(api)
        get_success_data(api.suspend_waste_profile(ctx["profile"]["id"], EA))
        manifest = get_success_data(api.get_manifest(ctx["manifest"]["id"], PM))
        assert manifest["status"] == "VOIDED"
        facility = get_success_data(api.get_disposal_facility(ctx["facility"]["id"], PM))
        assert facility["reserved_tons"] == pytest.approx(0.0)
        assert facility["posture"] == "AVAILABLE"

    def test_suspend_marks_profile_suspended_and_cascade_is_immediate(self, api):
        """PRD §3.6: "An `APPROVED` profile can be suspended by an
        `EnvironmentalApprover`, and suspension cascades in three linked steps".
        PRD §2.4: "Consistency is immediate rather than eventual: derived values
        such as a job's accrued standby total or a facility's reserved tonnage
        are recomputed inside the triggering write, never deferred to a later
        pass."

        Design: Difficulty/transitive_cascade/profile_suspend_cascade_voids_manifests_releases_reservation
        """
        ctx = self._setup_full_facility(api)
        suspended = get_success_data(api.suspend_waste_profile(ctx["profile"]["id"], EA))
        assert suspended["status"] == "SUSPENDED"
        facility = get_success_data(api.get_disposal_facility(ctx["facility"]["id"], PM))
        assert facility["reserved_tons"] == pytest.approx(0.0)
        assert facility["posture"] == "AVAILABLE"


class TestManifestListFilter:
    def test_manifests_filtered_by_waste_profile(self, api):
        """PRD §3.6: "Manifests list by `job_id`, `waste_profile_id` and
        `status`."

        Design: Corner/endpoints/manifests_filtered_list_reverse_reaches_profile
        """
        ctx = create_job_in_progress()
        facility, profile1 = create_facility_and_approved_profile(ctx["site"]["id"])
        profile2 = get_success_data(
            api.create_waste_profile(
                create_waste_profile_payload(
                    ctx["site"]["id"], facility["id"], waste_code="NONHAZ-WW",
                    hazard_class="NON_HAZ", density_lbs_per_gal=8.345,
                    disposal_rate_per_ton_cents=12000, variance_basis="VOLUME",
                ),
                CO,
            )
        )
        get_success_data(api.submit_waste_profile(profile2["id"], CO))
        get_success_data(api.approve_waste_profile(profile2["id"], EA))

        man1 = create_manifest(ctx["job"]["id"], profile1["id"], 500)
        man2 = create_manifest(ctx["job"]["id"], profile2["id"], 700)

        from test_helpers import validate_paginated
        data, meta = validate_paginated(
            api.list_manifests(PM, params={"waste_profile_id": profile2["id"]})
        )
        assert len(data) == 1
        assert data[0]["id"] == man2["id"]
        assert meta["total_count"] == 1
