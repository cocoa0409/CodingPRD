"""Project creation, validation, and updates.

PRD §3.2 (Project Creation, Drafting, and the Quotation Round).
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)
from test_helpers import (
    ApiErrorId,
    PM,
    api_client,
    assert_project,
    create_client,
    create_project,
    create_project_payload,
    create_project_template_payload,
    future_iso,
    future_iso_hours,
    iso_z,
    setup_client_and_project_in_draft,
    update_project_payload,
)


# ===========================================================================
# Project creation core
# ===========================================================================
class TestProjectCreation:

    def test_create_project_returns_state_draft(self):
        """PRD §3.2: "On creation the project's state is DRAFT, the
        project's word_count is 0."

        Claim: POST /projects -> state == "DRAFT" and word_count == 0.
        """
        client = create_client()
        project = create_project(client["id"])
        assert project["state"] == "DRAFT"
        assert project["word_count"] == 0
        assert_project(project)

    def test_create_project_returns_default_package_size_50(self):
        """PRD §3.2: "an optional package size (package_size_segments,
        defaulting to 50, in the range 1 to 500)."

        Claim: project created without package_size_segments -> default 50.
        """
        client = create_client()
        payload = create_project_payload(client["id"])
        payload.pop("package_size_segments", None)
        resp = api_client.create_project(payload, PM)
        data = validate_success(resp, 201)
        assert data["package_size_segments"] == 50


# ===========================================================================
# Validation gates
# ===========================================================================
class TestProjectValidation:

    def test_deadline_not_in_future_rejected(self):
        """PRD §3.2: "The platform refuses the creation with
        ERR_DEADLINE_NOT_IN_FUTURE when deadline_at is not strictly later
        than the current server time at creation."

        Claim: deadline in the past -> ERR_DEADLINE_NOT_IN_FUTURE.
        """
        client = create_client()
        past = iso_z(datetime.now(timezone.utc) - timedelta(days=1))
        resp = api_client.create_project(
            create_project_payload(client["id"], deadline_at=past), PM,
        )
        validate_error(resp, ApiErrorId.ERR_DEADLINE_NOT_IN_FUTURE)

    def test_same_source_target_rejected(self):
        """PRD §3.2: "with ERR_SAME_SOURCE_TARGET when source_lang and
        target_lang are equal."

        Claim: source_lang == target_lang -> ERR_SAME_SOURCE_TARGET.
        """
        client = create_client()
        resp = api_client.create_project(
            create_project_payload(client["id"],
                                   source_lang="en", target_lang="en"),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_SAME_SOURCE_TARGET)

    def test_zero_base_unit_price_cents_rejected_invalid_price(self):
        """PRD §3.2: "with ERR_INVALID_PRICE when base_unit_price_cents
        is less than 1."

        Claim: base_unit_price_cents == 0 -> ERR_INVALID_PRICE.
        """
        client = create_client()
        resp = api_client.create_project(
            create_project_payload(client["id"], base_unit_price_cents=0),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PRICE)


# ===========================================================================
# Project update
# ===========================================================================
class TestProjectUpdate:

    def test_update_draft_project_name_succeeds(self):
        """PRD §3.2: "Updates to a project in DRAFT are confined to name,
        deadline_at, base_unit_price_cents, and package_size_segments."

        Claim: PUT /projects/{id} on a DRAFT project may change name.
        """
        _, project = setup_client_and_project_in_draft()
        resp = api_client.update_project(
            project["id"], update_project_payload(name="Renamed"), PM,
        )
        data = validate_success(resp)
        assert data["name"] == "Renamed"
        assert data["version"] == project["version"] + 1

    def test_update_with_correct_version_succeeds(self):
        """PRD §2.5: "When the field is supplied, the server checks that
        its value equals the current version of the targeted entity before
        applying the mutation."

        Claim: PUT with matching version proceeds.
        """
        _, project = setup_client_and_project_in_draft()
        resp = api_client.update_project(
            project["id"],
            update_project_payload(name="X", version=project["version"]),
            PM,
        )
        validate_success(resp)

    def test_update_with_stale_version_returns_version_conflict(self):
        """PRD §2.5: "a mismatch fails the request with ERR_VERSION_CONFLICT
        (HTTP 409) and no change is persisted."

        Claim: PUT with stale version -> ERR_VERSION_CONFLICT.
        """
        _, project = setup_client_and_project_in_draft()
        # First update bumps version
        api_client.update_project(
            project["id"],
            update_project_payload(name="First"), PM,
        )
        # Second with the old version is stale
        resp = api_client.update_project(
            project["id"],
            update_project_payload(name="Second", version=project["version"]),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT)

    def test_update_omitting_version_skips_occ_check(self):
        """PRD §2.5: "When the field is omitted from the body, the version
        check is skipped and the mutation proceeds against whatever the
        current row holds."

        Claim: PUT without version succeeds regardless of stale info.
        """
        _, project = setup_client_and_project_in_draft()
        # First update bumps version
        api_client.update_project(project["id"],
                                  update_project_payload(name="First"), PM)
        # Second omits version
        resp = api_client.update_project(
            project["id"], update_project_payload(name="Second"), PM,
        )
        validate_success(resp)


# ===========================================================================
# Project template seeding (PRD §3.2)
# ===========================================================================
class TestProjectTemplate:

    def test_template_seeds_defaults_into_project(self):
        """PRD §3.2: "Where a template is supplied, the platform seeds
        domain, unit_pricing_mode, base_unit_price_cents, and
        package_size_segments from the template's matching defaults."

        Claim: project created with template_id picks up template defaults
        when those fields are omitted from the request body.
        """
        client = create_client()
        tmpl_resp = api_client.create_project_template(
            create_project_template_payload(
                default_domain="MEDICAL",
                default_unit_pricing_mode="PER_SEGMENT",
                default_base_unit_price_cents=250,
                default_package_size_segments=80,
            ),
            PM,
        )
        tmpl = validate_success(tmpl_resp, 201)
        payload = create_project_payload(client["id"])
        # Remove the fields the template should seed
        for f in ("domain", "unit_pricing_mode",
                  "base_unit_price_cents", "package_size_segments"):
            payload.pop(f, None)
        payload["template_id"] = tmpl["id"]
        resp = api_client.create_project(payload, PM)
        proj = validate_success(resp, 201)
        assert proj["domain"] == "MEDICAL"
        assert proj["unit_pricing_mode"] == "PER_SEGMENT"
        assert proj["base_unit_price_cents"] == 250
        assert proj["package_size_segments"] == 80

    def test_explicit_field_overrides_template_default(self):
        """PRD §3.2: "but any explicit field on the request body overrides
        the template default."

        Claim: explicit base_unit_price_cents in body wins over template.
        """
        client = create_client()
        tmpl_resp = api_client.create_project_template(
            create_project_template_payload(
                default_domain="MEDICAL",
                default_unit_pricing_mode="PER_SEGMENT",
                default_base_unit_price_cents=250,
                default_package_size_segments=80,
            ),
            PM,
        )
        tmpl = validate_success(tmpl_resp, 201)
        payload = create_project_payload(
            client["id"], base_unit_price_cents=999,
        )
        payload["template_id"] = tmpl["id"]
        resp = api_client.create_project(payload, PM)
        proj = validate_success(resp, 201)
        assert proj["base_unit_price_cents"] == 999
