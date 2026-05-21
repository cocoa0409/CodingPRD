"""Form 3922: immutability + retrieval.

References PRD §2.8.
"""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    assert_form_3922,
    make_participant_headers,
    parse_iso,
    setup_purchase_after_run,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestForm3922Immutability:
    """PRD §2.8 immutability rule."""

    def test_patch_on_form_3922_rejected(self, api):
        """PRD §2.8: "Any subsequent attempt to alter or delete the
        record — via `PATCH`, `PUT`, or `DELETE` against the Form 3922
        endpoint — is rejected with `ERR_FORM_3922_IMMUTABLE`."

        Claim: PATCH /form-3922/{id} -> ERR_FORM_3922_IMMUTABLE.
        """
        plan, _op, pid, purchase = setup_purchase_after_run(
            grant_date_fmv_cents=1000,
            purchase_date_fmv_cents=2000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
        )
        # Locate the form via the per-participant list.
        year = parse_iso(purchase["purchase_date"]).year
        resp = api.list_form_3922(
            pid, make_participant_headers(pid),
            params={"calendar_year": year, "limit": 100, "offset": 0},
        )
        forms = resp.json()["data"]
        assert forms, "Setup failed: no Form3922 issued"
        form = forms[0]
        # Attempt PATCH.
        bad = api.patch_form_3922(
            form["id"],
            {"fmv_grant_date_cents": 999_999},
            TEST_USERS["plan_admin_headers"],
        )
        validate_error(bad, ApiErrorId.ERR_FORM_3922_IMMUTABLE.value)

    def test_delete_on_form_3922_rejected(self, api):
        """PRD §2.8: "Any subsequent attempt to alter or delete the
        record — via `PATCH`, `PUT`, or `DELETE` against the Form 3922
        endpoint — is rejected with `ERR_FORM_3922_IMMUTABLE`."

        Claim: DELETE /form-3922/{id} -> ERR_FORM_3922_IMMUTABLE.
        """
        plan, _op, pid, purchase = setup_purchase_after_run(
            grant_date_fmv_cents=1000,
            purchase_date_fmv_cents=2000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
        )
        year = parse_iso(purchase["purchase_date"]).year
        resp = api.list_form_3922(
            pid, make_participant_headers(pid),
            params={"calendar_year": year, "limit": 100, "offset": 0},
        )
        forms = resp.json()["data"]
        assert forms, "Setup failed: no Form3922 issued"
        form = forms[0]
        bad = api.delete_form_3922(
            form["id"], TEST_USERS["plan_admin_headers"],
        )
        validate_error(bad, ApiErrorId.ERR_FORM_3922_IMMUTABLE.value)

    def test_get_form_3922_returns_append_only_envelope(self, api):
        """PRD §2.6: "A `Form3922` likewise carries only `id` and
        `created_at` — `updated_at` and `version` are absent because
        Form 3922 is immutable by design."

        Claim: GET /form-3922/{id} returns id + created_at but neither
        updated_at nor version.
        """
        plan, _op, pid, purchase = setup_purchase_after_run(
            grant_date_fmv_cents=1000,
            purchase_date_fmv_cents=2000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
        )
        year = parse_iso(purchase["purchase_date"]).year
        resp = api.list_form_3922(
            pid, make_participant_headers(pid),
            params={"calendar_year": year, "limit": 100, "offset": 0},
        )
        forms = resp.json()["data"]
        assert forms, "Setup failed: no Form3922 issued"
        form_id = forms[0]["id"]
        single = api.get_form_3922(
            form_id, TEST_USERS["plan_admin_headers"],
        )
        data = validate_success(single)
        assert_form_3922(data)
