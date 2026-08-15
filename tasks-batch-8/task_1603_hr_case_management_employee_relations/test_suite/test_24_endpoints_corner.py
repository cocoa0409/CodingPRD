"""Corner tests — endpoints section (case list filtering, litigation happy path, OCC stale seal)."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    make_legal_counsel_headers,
    setup_intake_channel,
    setup_employee,
    setup_investigator,
    setup_case,
    run_case_to_closed,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
)


class TestCaseListFiltering:
    def test_case_list_filter_by_status_and_severity(self):
        """PRD §4: "GET `/er/cases` | List cases; filter by `status`,
        `category`, `severity`, `assigned_investigator_id`,
        `subject_employee_id`, `reporter_employee_id`, `intake_channel_id`,
        `litigation_hold`."
        PRD §2.3: "The `meta` object of a list response carries four
        pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/case_list_filter_by_status_and_severity
        """
        ch = setup_intake_channel(
            channel_code="ANONYMOUS_LETTER", display_name="Anon F",
            default_category="OTHER", default_severity="LOW",
            sla_business_days=10,
        )
        subject = setup_employee()
        c1 = setup_case(ch["id"], subject["id"], category="OTHER", severity="HIGH")
        c2 = setup_case(ch["id"], subject["id"], category="OTHER", severity="LOW")
        c3 = setup_case(ch["id"], subject["id"], category="OTHER", severity="HIGH")
        resp = api_client.list_cases(
            TEST_USERS["er_manager_headers"],
            params={"status": "TRIAGE", "severity": "HIGH"},
        )
        data, meta = validate_paginated(resp)
        ids = {c["id"] for c in data}
        assert ids == {c1["id"], c3["id"]}, (
            f"Expected exactly c1 and c3 (TRIAGE/HIGH), got ids {ids}"
        )
        assert meta["total_count"] == 2


class TestLitigationPackageLifecycle:
    def test_litigation_package_full_happy_path_seal_release(self):
        """PRD §3.8: "Finalizing moves the package from `ASSEMBLING` to
        `READY`: it requires the parent case still `CLOSED` under litigation
        hold, at least one manifest entry, and it computes the `manifest_hash`.
        Sealing then moves `READY` to `SEALED` ... Sealing recomputes the hash
        and freezes it, stamps `sealed_at` from the logical clock, and —
        because the seal mutates the case's file state — increments the parent
        case's `version`. Finally, a `SEALED` package is moved to `RELEASED`
        only against external authority: the request must present a
        `release_authority_reference` — a court order or subpoena identifier —
        of at least eight characters."

        Design: Corner/endpoints/litigation_package_full_happy_path_seal_release
        """
        channel = setup_intake_channel(
            channel_code="ANONYMOUS_LETTER", display_name="Anon P",
            default_category="HARASSMENT", default_severity="HIGH",
            sla_business_days=20,
        )
        subject = setup_employee(location_code="SF")
        _, inv1 = setup_investigator()
        _, inv2 = setup_investigator()
        _, inv3 = setup_investigator()
        case, _, _, _, _ = run_case_to_closed(
            channel["id"], subject["id"], inv1, inv2, inv3,
            category="HARASSMENT", severity="HIGH",
            action_type="SUSPENSION", severity_points=70,
            substantiation_outcome="SUBSTANTIATED",
            assessment_kwargs={"corroboration_count": 4, "contradiction_count": 0,
                                "account_age_days": 2},
        )
        assert case["status"] == "CLOSED"
        # Set litigation_hold
        api_client.patch_case(case["id"], {"litigation_hold": True}, TEST_USERS["er_manager_headers"])
        # Create package
        pkg = get_success_data(api_client.create_litigation_package(
            case["id"], make_legal_counsel_headers()
        ))
        assert pkg["status"] == "ASSEMBLING"
        # Finalize → READY
        fin = api_client.finalize_package(pkg["id"], make_legal_counsel_headers())
        ready = validate_success(fin, 200)
        assert ready["status"] == "READY"
        assert ready.get("manifest_hash"), "manifest_hash must be computed at READY"
        # Seal — capture case version first
        case_now = get_success_data(api_client.get_case(case["id"], make_legal_counsel_headers()))
        case_version_pre_seal = case_now["version"]
        seal_resp = api_client.seal_package(
            pkg["id"], {"expected_case_version": case_version_pre_seal},
            make_legal_counsel_headers(),
        )
        sealed = validate_success(seal_resp, 200)
        assert sealed["status"] == "SEALED"
        assert sealed.get("sealed_at") is not None
        # Verify case version bumped by 1
        case_after_seal = get_success_data(api_client.get_case(case["id"], make_legal_counsel_headers()))
        assert case_after_seal["version"] == case_version_pre_seal + 1, (
            f"Sealing must increment case version by 1: {case_version_pre_seal} -> "
            f"{case_after_seal['version']}"
        )
        # Release
        rel = api_client.release_package(
            pkg["id"], {"release_authority_reference": "SUBPOENA-2026-0847"},
            make_legal_counsel_headers(),
        )
        released = validate_success(rel, 200)
        assert released["status"] == "RELEASED"


class TestLitigationSealStaleVersion:
    def test_litigation_seal_stale_case_version_rejected(self):
        """PRD §2.9: "Sealing a litigation file package
        (`POST /er/litigation-packages/{id}/seal`) ... When the case's current
        `version` no longer equals the supplied `expected_case_version` —
        because an intervening write of any kind has advanced it — the request
        is rejected with `ERR_STALE_VERSION` (HTTP 412) and no change is
        applied."

        Design: Corner/endpoints/litigation_seal_stale_case_version_rejected
        """
        channel = setup_intake_channel(
            channel_code="ANONYMOUS_LETTER", display_name="Anon SV",
            default_category="HARASSMENT", default_severity="HIGH",
            sla_business_days=20,
        )
        subject = setup_employee(location_code="SF")
        _, inv1 = setup_investigator()
        _, inv2 = setup_investigator()
        _, inv3 = setup_investigator()
        case, _, _, _, _ = run_case_to_closed(
            channel["id"], subject["id"], inv1, inv2, inv3,
            category="HARASSMENT", severity="HIGH",
            action_type="SUSPENSION", severity_points=70,
            substantiation_outcome="SUBSTANTIATED",
            assessment_kwargs={"corroboration_count": 4, "contradiction_count": 0,
                                "account_age_days": 2},
        )
        api_client.patch_case(case["id"], {"litigation_hold": True}, TEST_USERS["er_manager_headers"])
        pkg = get_success_data(api_client.create_litigation_package(
            case["id"], make_legal_counsel_headers()
        ))
        api_client.finalize_package(pkg["id"], make_legal_counsel_headers())
        # Capture version
        case_now = get_success_data(api_client.get_case(case["id"], make_legal_counsel_headers()))
        stale_version = case_now["version"]
        # Intervening real mutation: flip litigation_hold true->false->true (two PRD-acknowledged edits).
        # PRD §2.4: version "increments by one on every mutation". Each PATCH here changes a value.
        api_client.patch_case(case["id"], {"litigation_hold": False}, TEST_USERS["er_manager_headers"])
        api_client.patch_case(case["id"], {"litigation_hold": True}, TEST_USERS["er_manager_headers"])
        # Now attempt seal with the stale version
        resp = api_client.seal_package(
            pkg["id"], {"expected_case_version": stale_version},
            make_legal_counsel_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        # Package remains READY
        pkg_after = get_success_data(api_client.get_litigation_package(
            pkg["id"], make_legal_counsel_headers()
        ))
        assert pkg_after["status"] == "READY"
