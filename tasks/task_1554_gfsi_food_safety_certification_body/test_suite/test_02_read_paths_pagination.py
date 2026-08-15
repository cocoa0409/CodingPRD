"""Path-existence 404s (PRD §2.5 class 4) and list pagination/filtering."""
from test_helpers import (
    ApiErrorId,
    make_client,
    make_decision_maker,
    make_decision_maker_headers,
    make_scheme,
    make_application,
    submit_application,
    validate_error,
    validate_paginated,
)

MISSING = "11111111-2222-4333-8444-555555555555"


class TestNotFound:
    """PRD §2.5: "Path identifiers are validated left to right; the first
    identifier that does not correspond to an existing resource produces its
    specific 404 — `ERR_CLIENT_NOT_FOUND`, `ERR_SCHEME_NOT_FOUND`,
    `ERR_AUDITOR_NOT_FOUND`, `ERR_DECISION_MAKER_NOT_FOUND",
    `ERR_APPLICATION_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_NC_NOT_FOUND`,
    `ERR_CERTIFICATE_NOT_FOUND`, `ERR_SCOPE_CHANGE_NOT_FOUND`, or
    `ERR_APPEAL_NOT_FOUND`." """

    def test_get_nonexistent_client_returns_404(self, api,
                                                scheme_admin_headers):
        """PRD §2.5 (class 4, path existence): an unknown client path id
        produces `ERR_CLIENT_NOT_FOUND`.

        Design: Corner/entities/get_nonexistent_client_returns_404
        """
        resp = api.get_client(MISSING, scheme_admin_headers)
        validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_FOUND, 404)

    def test_get_nonexistent_scheme_returns_404(self, api,
                                                scheme_admin_headers):
        """PRD §2.5 (class 4, path existence): an unknown scheme path id
        produces `ERR_SCHEME_NOT_FOUND`.

        Design: Corner/entities/get_nonexistent_scheme_returns_404
        """
        resp = api.get_scheme(MISSING, scheme_admin_headers)
        validate_error(resp, ApiErrorId.ERR_SCHEME_NOT_FOUND, 404)

    def test_get_nonexistent_auditor_returns_404(self, api,
                                                 scheme_admin_headers):
        """PRD §2.5 (class 4, path existence): an unknown auditor path id
        produces `ERR_AUDITOR_NOT_FOUND`.

        Design: Corner/entities/get_nonexistent_auditor_returns_404
        """
        resp = api.get_auditor(MISSING, scheme_admin_headers)
        validate_error(resp, ApiErrorId.ERR_AUDITOR_NOT_FOUND, 404)

    def test_get_nonexistent_decision_maker_returns_404(self, api,
                                                        scheme_admin_headers):
        """PRD §2.5 (class 4, path existence): an unknown decision-maker path
        id produces `ERR_DECISION_MAKER_NOT_FOUND`.

        Design: Corner/entities/get_nonexistent_decision_maker_returns_404
        """
        resp = api.get_decision_maker(MISSING, scheme_admin_headers)
        validate_error(resp, ApiErrorId.ERR_DECISION_MAKER_NOT_FOUND, 404)

    def test_get_nonexistent_application_returns_404(self, api,
                                                     scheme_admin_headers):
        """PRD §2.5 (class 4, path existence): an unknown application path id
        produces `ERR_APPLICATION_NOT_FOUND`.

        Design: Corner/entities/get_nonexistent_application_returns_404
        """
        resp = api.get_application(MISSING, scheme_admin_headers)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND, 404)

    def test_get_nonexistent_audit_returns_404(self, api, scheme_admin_headers):
        """PRD §2.5 (class 4, path existence): an unknown audit path id
        produces `ERR_AUDIT_NOT_FOUND`.

        Design: Corner/entities/get_nonexistent_audit_returns_404
        """
        resp = api.get_audit(MISSING, scheme_admin_headers)
        validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_FOUND, 404)

    def test_get_nonexistent_nonconformity_returns_404(self, api,
                                                       scheme_admin_headers):
        """PRD §2.5 (class 4, path existence): an unknown nonconformity path
        id produces `ERR_NC_NOT_FOUND`.

        Design: Corner/entities/get_nonexistent_nonconformity_returns_404
        """
        resp = api.get_nonconformity(MISSING, scheme_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NC_NOT_FOUND, 404)

    def test_get_nonexistent_certificate_returns_404(self, api,
                                                     scheme_admin_headers):
        """PRD §2.5 (class 4, path existence): an unknown certificate path id
        produces `ERR_CERTIFICATE_NOT_FOUND`.

        Design: Corner/entities/get_nonexistent_certificate_returns_404
        """
        resp = api.get_certificate(MISSING, scheme_admin_headers)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_NOT_FOUND, 404)

    def test_decide_nonexistent_scope_change_returns_404(self, api):
        """PRD §2.5 (class 4, path existence): an unknown scope-change path id
        produces `ERR_SCOPE_CHANGE_NOT_FOUND`.

        Design: Corner/entities/decide_nonexistent_scope_change_returns_404
        """
        dm = make_decision_maker()
        resp = api.decide_scope_change(MISSING, {"outcome": "APPROVED"},
                                       make_decision_maker_headers(dm["id"]))
        validate_error(resp, ApiErrorId.ERR_SCOPE_CHANGE_NOT_FOUND, 404)

    def test_decide_nonexistent_appeal_returns_404(self, api):
        """PRD §2.5 (class 4, path existence): an unknown appeal path id
        produces `ERR_APPEAL_NOT_FOUND`.

        Design: Corner/entities/decide_nonexistent_appeal_returns_404
        """
        dm = make_decision_maker()
        resp = api.decide_appeal(MISSING, {"outcome": "UPHELD"},
                                 make_decision_maker_headers(dm["id"]))
        validate_error(resp, ApiErrorId.ERR_APPEAL_NOT_FOUND, 404)


class TestPaginationAndFilters:
    def test_list_applications_pagination_limit_offset(self, api,
                                                       scheme_admin_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return; it defaults to 10, with a minimum of 1 and a maximum
        of 100. The `offset` parameter specifies the number of items to skip
        and defaults to 0."
        PRD §3.3: "Applications are listed in `created_at` ascending order with
        optional `client_id`, `scheme_id`, and `status` filters"

        Design: Corner/entities/list_applications_pagination_limit_offset
        """
        sqf = make_scheme()
        brc = make_scheme(code="BRC", name="BRCGS Food Safety")
        client = make_client()
        app1 = make_application(client, sqf, scope_text="baked goods")
        app2 = make_application(client, brc, scope_text="baked goods (BRC)")

        data1, meta1 = validate_paginated(
            api.list_applications(scheme_admin_headers,
                                  params={"limit": 1, "offset": 0}))
        assert len(data1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert data1[0]["id"] == app1["id"]

        data2, meta2 = validate_paginated(
            api.list_applications(scheme_admin_headers,
                                  params={"limit": 1, "offset": 1}))
        assert len(data2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert data2[0]["id"] == app2["id"]

    def test_filter_applications_by_status(self, api, scheme_admin_headers):
        """PRD §3.3: "Applications are listed in `created_at` ascending order
        with optional `client_id`, `scheme_id`, and `status` filters; a
        `ClientAdmin` sees only its own applications in this list."

        Design: Corner/cross_cutting_layers/filter_applications_by_status
        """
        sqf = make_scheme()
        brc = make_scheme(code="BRC", name="BRCGS Food Safety")
        client = make_client()
        app1 = submit_application(
            make_application(client, sqf, scope_text="baked goods"), client)
        app2 = make_application(client, brc, scope_text="baked goods (BRC)")

        data, meta = validate_paginated(
            api.list_applications(scheme_admin_headers,
                                  params={"status": "SUBMITTED"}))
        assert meta["total_count"] == 1
        assert [a["id"] for a in data] == [app1["id"]]

        data, meta = validate_paginated(
            api.list_applications(scheme_admin_headers,
                                  params={"status": "DRAFT"}))
        assert meta["total_count"] == 1
        assert [a["id"] for a in data] == [app2["id"]]
