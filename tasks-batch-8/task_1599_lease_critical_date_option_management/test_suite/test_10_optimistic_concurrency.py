"""Optimistic concurrency control: stale-version rejection on notice create
and on assessment submit."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_comparable_assessment_payload,
    create_notice_payload,
    get_success_data,
    reject_notice_payload,
    set_clock,
    setup_notice_sent,
    setup_option_on_active_lease,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestStaleVersionOnNoticeCreate:
    def test_occ_stale_version_on_notice_create(self, api):
        """PRD §2.7: "Delivering an exercise notice — first delivery or
        re-delivery — requires `expected_lease_version` equal to the lease's
        current `version`; a mismatch is rejected with `ERR_STALE_VERSION`
        (HTTP 412)"

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_notice_create
        """
        ws = setup_option_on_active_lease(
            name="CC1", region="WEST", with_bk=True,
            option_overrides={
                "option_type": "RENEWAL",
                "notice_window_open_date": "2026-08-01T00:00:00Z",
                "notice_window_close_date": "2026-12-31T00:00:00Z",
                "target_commencement_date": "2028-01-01T00:00:00Z",
                "extension_years": 5,
                "rate_determination": "FIXED",
                "fixed_rent_cents_per_rsf_year": 4200,
            })
        set_clock("2026-09-01T00:00:00Z")
        # Capture the lease version observed at activation.
        lease_at_activate = get_success_data(api.get_lease(
            ws["pid"], ws["lid"], ws["am_headers"]))
        stale_version = lease_at_activate["version"]
        # First notice create succeeds with that version (and bumps Lease.version).
        first = validate_success(api.create_notice(
            ws["pid"], ws["lid"], ws["oid"],
            create_notice_payload(stale_version, delivery_method="COURIER"),
            ws["am_headers"]), 201)  # PRD §4: creating an exercise notice answers 201
        # Reject the first notice so the re-delivery path is open.
        get_success_data(api.reject_notice(
            ws["pid"], ws["lid"], ws["oid"], first["id"],
            reject_notice_payload("refused at door"), ws["bk_headers"]))
        # Re-deliver replaying the original (now stale) version.
        resp = api.create_notice(
            ws["pid"], ws["lid"], ws["oid"],
            create_notice_payload(stale_version, delivery_method="PERSONAL_DELIVERY"),
            ws["am_headers"])
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_fresh_version_after_notice_create_succeeds(self, api):
        """PRD §2.7: "Delivering an exercise notice — first delivery or
        re-delivery — requires `expected_lease_version` equal to the lease's
        current `version`"

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_notice_create
        """
        ws = setup_option_on_active_lease(
            name="CC1b", region="WEST", with_bk=True,
            option_overrides={
                "option_type": "RENEWAL",
                "notice_window_open_date": "2026-08-01T00:00:00Z",
                "notice_window_close_date": "2026-12-31T00:00:00Z",
                "target_commencement_date": "2028-01-01T00:00:00Z",
                "extension_years": 5,
                "rate_determination": "FIXED",
                "fixed_rent_cents_per_rsf_year": 4200,
            })
        set_clock("2026-09-01T00:00:00Z")
        lease = get_success_data(api.get_lease(ws["pid"], ws["lid"], ws["am_headers"]))
        first = validate_success(api.create_notice(
            ws["pid"], ws["lid"], ws["oid"],
            create_notice_payload(lease["version"], delivery_method="COURIER"),
            ws["am_headers"]), 201)  # PRD §4: creating an exercise notice answers 201
        get_success_data(api.reject_notice(
            ws["pid"], ws["lid"], ws["oid"], first["id"],
            reject_notice_payload("refused"), ws["bk_headers"]))
        # Read the post-bump version and re-deliver with it.
        lease_now = get_success_data(api.get_lease(
            ws["pid"], ws["lid"], ws["am_headers"]))
        assert lease_now["version"] == lease["version"] + 1, (
            "Notice create increments the lease's version by exactly one"
        )
        second = validate_success(api.create_notice(
            ws["pid"], ws["lid"], ws["oid"],
            create_notice_payload(lease_now["version"],
                                  delivery_method="PERSONAL_DELIVERY"),
            ws["am_headers"]), 201)  # PRD §4: creating an exercise notice answers 201
        assert second["status"] == "SENT"
        assert second["id"] != first["id"]
