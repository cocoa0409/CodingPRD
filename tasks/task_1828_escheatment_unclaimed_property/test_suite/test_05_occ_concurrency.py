"""Optimistic concurrency control on reports and version progression
(PRD §2.4, §2.7)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_version_incremented,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
)
from test_helpers.fixtures import (
    CO,
    READER,
    SA,
    accept_report,
    add_line_item,
    create_report,
    create_reportable_properties,
    create_reportable_property,
    get_report,
    setup_accepted_single_line_report,
    submit_report,
)

CO_H = TEST_USERS["compliance_officer_headers"]


class TestLineAddOcc:
    def test_stale_expected_version_rejected(self, api):
        """PRD §2.7: "Two write operations — adding a line item to a holder
        report, and creating an amendment that supersedes an accepted report —
        require the request body to carry `expected_report_version`, holding
        the `version` of the report as the client last observed it. If the
        report's current `version` has advanced beyond that observed value,
        the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_line_add_stale_version_rejected
        """
        _, _, props, _ = create_reportable_properties([60000, 60000])
        report = create_report()
        observed = report["version"]
        first = api.add_line_item(
            report["id"],
            {"property_id": props[0]["id"], "expected_report_version": observed},
            CO_H,
        )
        validate_success(first, 201)
        # The first add advanced the report version; replaying the observed
        # version must now fail even though the payload is otherwise valid.
        second = api.add_line_item(
            report["id"],
            {"property_id": props[1]["id"], "expected_report_version": observed},
            CO_H,
        )
        validate_error(second, ApiErrorId.ERR_STALE_VERSION, 412)
        lines, meta = validate_paginated(api.list_line_items(report["id"], READER))
        assert meta["total_count"] == 1, "the rejected add left no residue"

    def test_fresh_version_after_reread_succeeds(self, api):
        """PRD §2.7: "A mismatch forces a re-read before the write can
        proceed."

        Design: Corner/cross_cutting_complexity_layers/occ_line_add_stale_version_rejected
        """
        _, _, props, _ = create_reportable_properties([60000, 60000])
        report = create_report()
        observed = report["version"]
        validate_success(
            api.add_line_item(
                report["id"],
                {"property_id": props[0]["id"], "expected_report_version": observed},
                CO_H,
            ),
            201,
        )
        validate_error(
            api.add_line_item(
                report["id"],
                {"property_id": props[1]["id"], "expected_report_version": observed},
                CO_H,
            ),
            ApiErrorId.ERR_STALE_VERSION,
            412,
        )
        # Re-read and retry with the current version.
        fresh = get_report(report["id"])["version"]
        retry = api.add_line_item(
            report["id"],
            {"property_id": props[1]["id"], "expected_report_version": fresh},
            CO_H,
        )
        validate_success(retry, 201)


class TestAmendmentOcc:
    def test_stale_amendment_version_rejected(self, api):
        """PRD §2.7: "for amendment creation, it ensures the client's view of
        the amendment chain head is current, since an amendment legitimately
        supersedes the prior head."
        PRD §3.4: "the superseded report's `version` increments at amendment
        creation, though it remains `ACCEPTED` until the amendment itself is
        accepted."

        Design: Corner/cross_cutting_complexity_layers/occ_amendment_stale_version_rejected
        """
        chain = setup_accepted_single_line_report(value=80000)
        r1 = chain["report"]
        observed = chain["accepted_version"]
        first = api.create_amendment(
            r1["id"], {"expected_report_version": observed}, CO_H
        )
        validate_success(first, 201)  # bumps the superseded report's version
        # The same observed version is now stale; the OCC layer (seventh in
        # §2.10) fires before the pending-amendment uniqueness rule (ninth).
        second = api.create_amendment(
            r1["id"], {"expected_report_version": observed}, CO_H
        )
        validate_error(second, ApiErrorId.ERR_STALE_VERSION, 412)


class TestVersionProgression:
    def test_version_increments_on_each_mutation(self, api):
        """PRD §2.4: "`version` (integer): a system-managed integer that
        increments with every modification to the resource, including
        modifications driven by cascades and recomputations rather than by a
        direct client write."
        PRD §3.4: "Each recomputation refreshes the report's `updated_at` and
        increments its `version`."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_mutation
        """
        _, _, prop, _ = create_reportable_property(original_value_cents=80000)
        report = create_report()
        v_create = report["version"]
        assert isinstance(v_create, int) and v_create >= 1
        add_line_item(report["id"], prop["id"])
        v_add = get_report(report["id"])["version"]
        assert_version_incremented(v_add, v_create)
        submitted = submit_report(report["id"])
        assert_version_incremented(submitted["version"], v_add)
        accepted = accept_report(report["id"])
        assert_version_incremented(accepted["version"], submitted["version"])
