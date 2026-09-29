"""Endpoint surfaces of the program API.

This file exercises the observable shape of six endpoint families: the control
implementation create/read/list/update cycle, the body-free test-slot cancel
action with its own preconditions, the all-or-nothing write of the assessment
report's findings array, the reuse grant that links an authorization to an
agency, the computed monitoring-period read that derives its coverage from its
submissions, and the remediation endpoint whose two roles are split by the
requested action.
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ACTION_ROLE_MISMATCH,
    ERR_AGENCY_NOT_FOUND,
    ERR_ALREADY_TERMINAL,
    ERR_AUTHORIZATION_NOT_FOUND,
    ERR_DETECTION_DATE_IN_FUTURE,
    ERR_DUPLICATE_REUSE_GRANT,
    ERR_FORBIDDEN_ROLE,
    ERR_INCOMPLETE_SCAN_SET,
    ERR_INVALID_STATE,
    ERR_TEST_SLOT_NOT_FOUND,
)
from test_helpers.test_users import (
    ASSESSOR_HEADERS,
    BOARD_HEADERS,
    CSP_LEAD_HEADERS,
    make_agency_official_headers,
)

#: Two well-formed identifiers that name no row in the database.
UNKNOWN_AUTHORIZATION_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_AGENCY_ID = "22222222-2222-4222-8222-222222222222"

#: The instant the assessment report is delivered at in this file.
REPORT_CLOCK = fx.AUTHORIZATION_CLOCK

#: Three findings whose last element is dated after ``REPORT_CLOCK``.
MIXED_FINDINGS = [
    f.build_finding("AC-2", "HIGH", "2026-03-15T00:00:00Z"),
    f.build_finding("AC-3", "MODERATE", "2026-03-15T00:00:00Z"),
    f.build_finding("SC-7", "LOW", "2026-03-31T00:00:00Z"),
]

#: The same three findings with every detection instant inside the clock.
CLEAN_FINDINGS = [
    f.build_finding("AC-2", "HIGH", "2026-03-15T00:00:00Z"),
    f.build_finding("AC-3", "MODERATE", "2026-03-15T00:00:00Z"),
    f.build_finding("SC-7", "LOW", "2026-03-15T00:00:00Z"),
]

FINDING_ANCHOR = "2026-03-15T00:00:00Z"


# ---------------------------------------------------------------------------
# Shared state builders
# ---------------------------------------------------------------------------


def _categorized_offering(client):
    """A ``CATEGORIZED`` offering on a MODERATE baseline, with its agency."""
    return fx.seed_categorized_offering(client, fx.seed_reference_data(client))


def _three_implementations(client):
    """The categorized offering plus AC-2, AC-3 and SC-7 implementations.

    AC-2 and SC-7 are documented and ``IMPLEMENTED``; AC-3 is ``PLANNED`` with
    no matrix entry, so it counts toward neither coverage nor the documented
    filter.
    """
    env = _categorized_offering(client)
    rows = {}
    for control_id, family_code, status, documented in (
        ("AC-2", "AC", "IMPLEMENTED", True),
        ("AC-3", "AC", "PLANNED", False),
        ("SC-7", "SC", "IMPLEMENTED", True),
    ):
        rows[control_id] = get_success_data(
            client.create_control_implementation(
                f.build_control_implementation_payload(
                    env["offering_id"],
                    control_id=control_id,
                    family_code=family_code,
                    implementation_status=status,
                    crm_documented=documented,
                ),
                env["lead_headers"],
            ),
            201,
        )
    env["implementations"] = rows
    return env


def _engagement_with_one_scheduled_slot(client):
    """An engagement in ``TESTING`` holding one 8.00-hour ``SCHEDULED`` slot."""
    env = fx.seed_reference_data(client)
    env = fx.seed_path_selected_offering(client, env)
    env = fx.seed_control_implementations(client, env)
    env = fx.seed_engagement(client, env)
    return fx.seed_test_slot(client, env)


def _engagement_ready_to_report(client):
    """The same engagement with the clock moved to the report instant."""
    env = _engagement_with_one_scheduled_slot(client)
    fx.set_clock(client, REPORT_CLOCK)
    env["clock_set_to"] = REPORT_CLOCK
    return env


def _slot_row(client, env, slot_id):
    """One slot of the engagement, read back through the schedule listing."""
    rows = fx.list_test_slots(client, env["engagement_id"])
    matches = [row for row in rows if row["id"] == slot_id]
    assert matches, f"slot {slot_id} is absent from the engagement schedule"
    return matches[0]


def _authorization_with_second_agency(client):
    """A live authorization plus an EPA agency holding no grant yet."""
    env = fx.seed_authorized_offering(client)
    return fx.add_agency(
        client,
        env,
        name="Environmental Protection Agency",
        agency_code="EPA",
        key="epa",
    )


def _open_finding(client):
    """A categorized offering carrying one ``OPEN`` MODERATE finding."""
    env = _categorized_offering(client)
    return fx.seed_poam_item(
        client, env, severity="MODERATE", detected_at=fx.SETUP_CLOCK
    )


# ---------------------------------------------------------------------------
# Control implementations: create, read, list, update
# ---------------------------------------------------------------------------


def test_recording_a_control_implementation_returns_the_row_at_version_one(client):
    """Creating a control implementation returns the stored row at version 1.

    PRD: "`version` (integer): starts at 1 and increments by one on every mutation of the row."

    Design: Corner/endpoints/control_implementations_support_the_full_create_read_list_update_cycle
    """
    env = _categorized_offering(client)

    row = validate_success(
        client.create_control_implementation(
            f.build_control_implementation_payload(
                env["offering_id"],
                control_id="AC-2",
                family_code="AC",
                implementation_status="IMPLEMENTED",
                crm_documented=True,
            ),
            env["lead_headers"],
        ),
        201,
    )

    assert row["offering_id"] == env["offering_id"]
    assert row["control_id"] == "AC-2"
    assert row["family_code"] == "AC"
    assert row["implementation_status"] == "IMPLEMENTED"
    assert row["crm_documented"] is True
    A.assert_audit_triplet(row, "control implementation")
    A.assert_integer(row["version"], 1, "version")


def test_a_control_implementation_read_is_open_to_the_sponsoring_agency_official(client):
    """The sponsor's authorizing official may read an implementation it cannot write.

    PRD: "All read endpoints in §4 are open to all four roles, with the single exception described at the end of this subsection."

    Design: Corner/endpoints/control_implementations_support_the_full_create_read_list_update_cycle
    """
    env = _three_implementations(client)
    ac2 = env["implementations"]["AC-2"]

    row = validate_success(
        client.get_control_implementation(ac2["id"], env["agency_headers"]), 200
    )

    assert row["id"] == ac2["id"]
    assert row["control_id"] == "AC-2"


def test_the_implementation_list_narrows_by_family_code_and_documented_matrix(client):
    """Filtering on family_code and crm_documented returns only the documented AC row.

    PRD: "Implementations are listed with filters on `offering_id`, `inherited_from_offering_id`, `family_code`, `implementation_status` and `crm_documented`."

    Design: Corner/endpoints/control_implementations_support_the_full_create_read_list_update_cycle
    """
    env = _three_implementations(client)
    rows = env["implementations"]

    data, meta = validate_paginated(
        client.list_control_implementations(
            ASSESSOR_HEADERS,
            {
                "offering_id": env["offering_id"],
                "family_code": "AC",
                "crm_documented": "true",
            },
        )
    )

    assert meta["total_count"] == 1
    assert A.ids_of(data) == [rows["AC-2"]["id"]]
    assert rows["AC-3"]["id"] not in A.ids_of(data)
    assert rows["SC-7"]["id"] not in A.ids_of(data)


def test_all_three_implementations_remain_listed_for_the_offering(client):
    """The offering's implementation listing reports all three rows in creation order.

    PRD: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filters before the page window is applied."

    Design: Corner/endpoints/control_implementations_support_the_full_create_read_list_update_cycle
    """
    env = _three_implementations(client)
    rows = env["implementations"]

    data, meta = validate_paginated(
        client.list_control_implementations(
            CSP_LEAD_HEADERS, {"offering_id": env["offering_id"]}
        )
    )

    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    A.assert_created_at_ascending(data)
    assert A.ids_of(data) == [
        rows["AC-2"]["id"],
        rows["AC-3"]["id"],
        rows["SC-7"]["id"],
    ]


def test_updating_an_implementation_bumps_its_version_and_keeps_created_at(client):
    """A revision writes the named fields, moves version 1 to 2 and leaves created_at alone.

    PRD: "Updating an implementation may revise `implementation_status`, `crm_documented`, `customer_responsibility_text` or `inherited_from_offering_id`, and increments the row's own `version` by one."

    Design: Corner/endpoints/control_implementations_support_the_full_create_read_list_update_cycle
    """
    env = _three_implementations(client)
    ac3 = env["implementations"]["AC-3"]
    A.assert_integer(ac3["version"], 1, "version before the update")

    row = validate_success(
        client.update_control_implementation(
            ac3["id"],
            {
                "implementation_status": "PARTIALLY_IMPLEMENTED",
                "crm_documented": True,
                "customer_responsibility_text": f.DEFAULT_CRM_TEXT,
            },
            env["lead_headers"],
        ),
        200,
    )

    assert row["id"] == ac3["id"]
    assert row["control_id"] == "AC-3"
    assert row["implementation_status"] == "PARTIALLY_IMPLEMENTED"
    assert row["crm_documented"] is True
    A.assert_integer(row["version"], 2, "version after the update")
    A.assert_instant(row["created_at"], ac3["created_at"], "created_at")


def test_documenting_the_planned_control_lifts_coverage_to_full(client):
    """Coverage counts only documented IMPLEMENTED or PARTIALLY_IMPLEMENTED rows.

    PRD: "For each remaining family, count the offering's control implementations whose `family_code` matches that family, whose `implementation_status` is either `IMPLEMENTED` or `PARTIALLY_IMPLEMENTED`, and whose `crm_documented` is true — implementations that are `PLANNED`, `ALTERNATIVE_IMPLEMENTATION` or `NOT_APPLICABLE` never count, and neither does an implementation whose matrix entry is undocumented."

    Design: Corner/endpoints/control_implementations_support_the_full_create_read_list_update_cycle
    """
    env = _three_implementations(client)
    ac3 = env["implementations"]["AC-3"]

    before = get_success_data(
        client.get_crm_coverage(env["offering_id"], env["lead_headers"]), 200
    )
    A.assert_money(
        before["overall_coverage_pct"],
        A.expected_overall_coverage([(1, 2), (1, 1)]),
        "overall_coverage_pct with AC-3 undocumented",
    )

    get_success_data(
        client.update_control_implementation(
            ac3["id"],
            {
                "implementation_status": "PARTIALLY_IMPLEMENTED",
                "crm_documented": True,
                "customer_responsibility_text": f.DEFAULT_CRM_TEXT,
            },
            env["lead_headers"],
        ),
        200,
    )

    after = get_success_data(
        client.get_crm_coverage(env["offering_id"], env["lead_headers"]), 200
    )
    A.assert_money(
        after["overall_coverage_pct"],
        A.expected_overall_coverage([(2, 2), (1, 1)]),
        "overall_coverage_pct after the update",
    )
    A.assert_money(after["overall_coverage_pct"], 100.00, "overall_coverage_pct")
    assert after["overall_coverage_pct"] != before["overall_coverage_pct"]


# ---------------------------------------------------------------------------
# Cancelling a test slot
# ---------------------------------------------------------------------------


def test_the_compliance_lead_may_not_cancel_a_test_slot(client):
    """Slot cancellation belongs to the assessor, so the provider's lead is refused.

    PRD: "When the acting role is not listed as authorized for the endpoint being called (see §4), the request is rejected with `ERR_FORBIDDEN_ROLE` (403)."

    Design: Corner/endpoints/cancelling_a_test_slot_is_an_action_endpoint_with_its_own_preconditions
    """
    env = _engagement_with_one_scheduled_slot(client)

    validate_error(
        client.cancel_test_slot(env["slot_id"], env["lead_headers"]),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    assert _slot_row(client, env, env["slot_id"])["status"] == "SCHEDULED"
    engagement = fx.read_engagement(client, env["engagement_id"])
    A.assert_money(engagement["allocated_hours"], 8.00, "allocated_hours")


def test_cancelling_an_unknown_test_slot_reports_the_test_slot_code(client):
    """An unresolvable slot id in the path is reported as a test-slot 404.

    PRD: "Every identifier in the request path exists, resolved left to right — the corresponding 404."

    Design: Corner/endpoints/cancelling_a_test_slot_is_an_action_endpoint_with_its_own_preconditions
    """
    env = _engagement_with_one_scheduled_slot(client)

    validate_error(
        client.cancel_test_slot(NON_EXISTENT_UUID, env["assessor_headers"]),
        ERR_TEST_SLOT_NOT_FOUND,
        404,
    )

    assert _slot_row(client, env, env["slot_id"])["status"] == "SCHEDULED"


def test_cancelling_a_slot_returns_its_hours_to_the_unallocated_pool(client):
    """The cancel action moves the slot to CANCELLED and compensates the hour ledger.

    PRD: "Cancelling a slot moves it `SCHEDULED → CANCELLED`, which is terminal — a slot that is not `SCHEDULED` is refused with `ERR_ALREADY_TERMINAL` — requires the acting `X-User-ID` to equal the engagement's `assessor_user_id`, returns the slot's `hours` to `unallocated_hours` while removing them from `allocated_hours`, and increments the engagement's `version` by one."

    Design: Corner/endpoints/cancelling_a_test_slot_is_an_action_endpoint_with_its_own_preconditions
    """
    env = _engagement_with_one_scheduled_slot(client)

    slot = validate_success(
        client.cancel_test_slot(env["slot_id"], env["assessor_headers"]), 200
    )
    assert slot["status"] == "CANCELLED"

    engagement = fx.read_engagement(client, env["engagement_id"])
    A.assert_money(engagement["allocated_hours"], 0.00, "allocated_hours")
    A.assert_money(engagement["unallocated_hours"], 200.00, "unallocated_hours")
    A.assert_hour_conservation(engagement)
    assert engagement["status"] == "TESTING"


def test_a_second_cancel_of_the_same_slot_is_refused_as_terminal(client):
    """CANCELLED is terminal, so the side effect runs exactly once.

    PRD: "Cancelling a slot moves it `SCHEDULED → CANCELLED`, which is terminal — a slot that is not `SCHEDULED` is refused with `ERR_ALREADY_TERMINAL` — requires the acting `X-User-ID` to equal the engagement's `assessor_user_id`, returns the slot's `hours` to `unallocated_hours` while removing them from `allocated_hours`, and increments the engagement's `version` by one."

    Design: Corner/endpoints/cancelling_a_test_slot_is_an_action_endpoint_with_its_own_preconditions
    """
    env = _engagement_with_one_scheduled_slot(client)
    get_success_data(
        client.cancel_test_slot(env["slot_id"], env["assessor_headers"]), 200
    )

    validate_error(
        client.cancel_test_slot(env["slot_id"], env["assessor_headers"]),
        ERR_ALREADY_TERMINAL,
        409,
    )

    assert _slot_row(client, env, env["slot_id"])["status"] == "CANCELLED"
    engagement = fx.read_engagement(client, env["engagement_id"])
    A.assert_money(engagement["allocated_hours"], 0.00, "allocated_hours")
    A.assert_money(engagement["unallocated_hours"], 200.00, "unallocated_hours")


def test_a_cancelled_slot_is_retained_in_the_engagement_schedule(client):
    """The cancelled row stays in the schedule rather than disappearing from it.

    PRD: "A slot's `status` is one of `SCHEDULED`, `COMPLETED` or `CANCELLED`, and slots are listed per engagement with a `status` filter."

    Design: Corner/endpoints/cancelling_a_test_slot_is_an_action_endpoint_with_its_own_preconditions
    """
    env = _engagement_with_one_scheduled_slot(client)
    get_success_data(
        client.cancel_test_slot(env["slot_id"], env["assessor_headers"]), 200
    )

    data, meta = validate_paginated(
        client.list_test_slots(env["engagement_id"], BOARD_HEADERS)
    )

    assert meta["total_count"] == 1
    assert A.ids_of(data) == [env["slot_id"]]
    assert data[0]["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# The assessment report writes all of its findings or none of them
# ---------------------------------------------------------------------------


def test_a_future_detection_instant_rejects_the_whole_report(client):
    """One findings element dated past the clock refuses the entire delivery.

    PRD: "Report delivery requires the engagement to be in `TESTING`, requires the acting `X-User-ID` to equal the engagement's `assessor_user_id`, and requires every element's `detected_at` to be no later than the logical clock — a future detection instant is refused with `ERR_DETECTION_DATE_IN_FUTURE`."

    Design: Corner/endpoints/the_assessment_report_writes_all_of_its_findings_or_none_of_them
    """
    env = _engagement_ready_to_report(client)

    validate_error(
        client.deliver_report(
            env["engagement_id"],
            f.build_report_payload(MIXED_FINDINGS),
            env["assessor_headers"],
        ),
        ERR_DETECTION_DATE_IN_FUTURE,
        422,
    )


def test_a_refused_report_writes_no_findings_at_all(client):
    """The refused bulk write leaves zero findings and the engagement still testing.

    PRD: "On success the engagement moves `TESTING → REPORT_DELIVERED`; one plan-of-action item is opened per findings element with `source` `ASSESSMENT`, its `anchor_at` set to its `detected_at` and its deadline computed as described in §3.6; `findings_reported_count` is set to the number of items created; and every slot of the engagement still in `SCHEDULED` moves `SCHEDULED → COMPLETED`."

    Design: Corner/endpoints/the_assessment_report_writes_all_of_its_findings_or_none_of_them
    """
    env = _engagement_ready_to_report(client)
    validate_error(
        client.deliver_report(
            env["engagement_id"],
            f.build_report_payload(MIXED_FINDINGS),
            env["assessor_headers"],
        ),
        ERR_DETECTION_DATE_IN_FUTURE,
        422,
    )

    data, meta = validate_paginated(
        client.list_poam_items(CSP_LEAD_HEADERS, {"offering_id": env["offering_id"]})
    )
    assert meta["total_count"] == 0
    assert data == []

    engagement = fx.read_engagement(client, env["engagement_id"])
    A.assert_integer(engagement["findings_reported_count"], 0, "findings_reported_count")
    assert engagement["status"] == "TESTING"
    assert _slot_row(client, env, env["slot_id"])["status"] == "SCHEDULED"


def test_the_clean_report_opens_one_assessment_finding_per_element(client):
    """A legal batch writes one ASSESSMENT-sourced item per element, anchored on detection.

    PRD: "On success the engagement moves `TESTING → REPORT_DELIVERED`; one plan-of-action item is opened per findings element with `source` `ASSESSMENT`, its `anchor_at` set to its `detected_at` and its deadline computed as described in §3.6; `findings_reported_count` is set to the number of items created; and every slot of the engagement still in `SCHEDULED` moves `SCHEDULED → COMPLETED`."

    Design: Corner/endpoints/the_assessment_report_writes_all_of_its_findings_or_none_of_them
    """
    env = _engagement_ready_to_report(client)

    validate_success(
        client.deliver_report(
            env["engagement_id"],
            f.build_report_payload(CLEAN_FINDINGS),
            env["assessor_headers"],
        ),
        200,
    )

    data, meta = validate_paginated(
        client.list_poam_items(CSP_LEAD_HEADERS, {"offering_id": env["offering_id"]})
    )
    assert meta["total_count"] == 3
    for row in data:
        assert row["source"] == "ASSESSMENT"
        A.assert_instant(row["anchor_at"], FINDING_ANCHOR, "anchor_at")
        A.assert_instant(row["detected_at"], FINDING_ANCHOR, "detected_at")
    assert sorted(row["control_id"] for row in data) == ["AC-2", "AC-3", "SC-7"]


def test_the_reported_findings_carry_severity_specific_deadlines(client):
    """Each opened item's deadline is its anchor advanced by its severity allowance.

    PRD: "At creation an item's `anchor_at` equals its `detected_at`, and its `deadline_at` is `anchor_at` advanced by the severity base allowance and then by `granted_extension_days` further days."

    Design: Corner/endpoints/the_assessment_report_writes_all_of_its_findings_or_none_of_them
    """
    env = _engagement_ready_to_report(client)
    get_success_data(
        client.deliver_report(
            env["engagement_id"],
            f.build_report_payload(CLEAN_FINDINGS),
            env["assessor_headers"],
        ),
        200,
    )

    items = {
        row["control_id"]: row
        for row in fx.list_poam_items(client, offering_id=env["offering_id"])
    }

    A.assert_instant(
        items["AC-2"]["deadline_at"],
        A.expected_deadline(FINDING_ANCHOR, "HIGH"),
        "HIGH deadline_at",
    )
    A.assert_instant(items["AC-2"]["deadline_at"], "2026-04-14T00:00:00Z", "HIGH deadline_at")
    A.assert_instant(
        items["AC-3"]["deadline_at"],
        A.expected_deadline(FINDING_ANCHOR, "MODERATE"),
        "MODERATE deadline_at",
    )
    A.assert_instant(
        items["AC-3"]["deadline_at"], "2026-06-13T00:00:00Z", "MODERATE deadline_at"
    )
    A.assert_instant(
        items["SC-7"]["deadline_at"],
        A.expected_deadline(FINDING_ANCHOR, "LOW"),
        "LOW deadline_at",
    )
    A.assert_instant(
        items["SC-7"]["deadline_at"], "2026-09-11T00:00:00Z", "LOW deadline_at"
    )


def test_the_delivered_report_counts_its_findings_and_completes_the_slot(client):
    """Delivery sets the finding count, moves the engagement on and completes the slot.

    PRD: "On success the engagement moves `TESTING → REPORT_DELIVERED`; one plan-of-action item is opened per findings element with `source` `ASSESSMENT`, its `anchor_at` set to its `detected_at` and its deadline computed as described in §3.6; `findings_reported_count` is set to the number of items created; and every slot of the engagement still in `SCHEDULED` moves `SCHEDULED → COMPLETED`."

    Design: Corner/endpoints/the_assessment_report_writes_all_of_its_findings_or_none_of_them
    """
    env = _engagement_ready_to_report(client)

    engagement = validate_success(
        client.deliver_report(
            env["engagement_id"],
            f.build_report_payload(CLEAN_FINDINGS),
            env["assessor_headers"],
        ),
        200,
    )

    A.assert_integer(engagement["findings_reported_count"], 3, "findings_reported_count")
    assert engagement["status"] == "REPORT_DELIVERED"
    assert _slot_row(client, env, env["slot_id"])["status"] == "COMPLETED"
    assert fx.read_offering(client, env["offering_id"])["status"] == "IN_ASSESSMENT"


def test_the_reported_findings_open_undisposed_and_unremediated(client):
    """Every item the report opens starts OPEN with no risk disposition.

    PRD: "Every new item opens with `remediation_status` `OPEN`, `risk_disposition` `NONE`, `closure_reason` null, `granted_extension_days` 0 and `reopen_count` 0."

    Design: Corner/endpoints/the_assessment_report_writes_all_of_its_findings_or_none_of_them
    """
    env = _engagement_ready_to_report(client)
    get_success_data(
        client.deliver_report(
            env["engagement_id"],
            f.build_report_payload(CLEAN_FINDINGS),
            env["assessor_headers"],
        ),
        200,
    )

    data, meta = validate_paginated(
        client.list_poam_items(
            ASSESSOR_HEADERS,
            {"offering_id": env["offering_id"], "source": "ASSESSMENT"},
        )
    )

    assert meta["total_count"] == 3
    for row in data:
        assert row["remediation_status"] == "OPEN"
        assert row["risk_disposition"] == "NONE"
        assert row["closure_reason"] is None
        A.assert_integer(row["granted_extension_days"], 0, "granted_extension_days")
        A.assert_integer(row["reopen_count"], 0, "reopen_count")


def test_replaying_the_report_after_delivery_is_refused_as_an_invalid_state(client):
    """REPORT_DELIVERED is not a from-state of the report action.

    PRD: "Report delivery requires the engagement to be in `TESTING`, requires the acting `X-User-ID` to equal the engagement's `assessor_user_id`, and requires every element's `detected_at` to be no later than the logical clock — a future detection instant is refused with `ERR_DETECTION_DATE_IN_FUTURE`."

    Design: Corner/endpoints/the_assessment_report_writes_all_of_its_findings_or_none_of_them
    """
    env = _engagement_ready_to_report(client)
    get_success_data(
        client.deliver_report(
            env["engagement_id"],
            f.build_report_payload(CLEAN_FINDINGS),
            env["assessor_headers"],
        ),
        200,
    )

    validate_error(
        client.deliver_report(
            env["engagement_id"], f.build_report_payload([]), env["assessor_headers"]
        ),
        ERR_INVALID_STATE,
        409,
    )

    engagement = fx.read_engagement(client, env["engagement_id"])
    A.assert_integer(engagement["findings_reported_count"], 3, "findings_reported_count")


# ---------------------------------------------------------------------------
# A reuse grant links an authorization to an agency
# ---------------------------------------------------------------------------


def test_an_unknown_authorization_is_reported_before_an_unknown_agency(client):
    """The grant resolves authorization_id before agency_id, as declared.

    PRD: "Foreign keys carried in a request body are resolved after path identifiers, in the order in which the endpoint declares its input fields."

    Design: Corner/endpoints/a_reuse_grant_links_an_authorization_to_an_agency_and_both_ends_must_exist
    """
    env = _authorization_with_second_agency(client)
    version = fx.authorization_version(client, env["authorization_id"])

    validate_error(
        client.create_reuse_grant(
            f.build_reuse_grant_payload(
                UNKNOWN_AUTHORIZATION_ID, UNKNOWN_AGENCY_ID, version
            ),
            make_agency_official_headers(UNKNOWN_AGENCY_ID),
        ),
        ERR_AUTHORIZATION_NOT_FOUND,
        404,
    )


def test_a_reuse_request_naming_an_unknown_agency_reports_the_agency_code(client):
    """With the authorization resolved, an unknown agency_id raises the agency 404.

    PRD: "Each unresolvable reference raises the 404 error belonging to the referenced type: `ERR_OFFERING_NOT_FOUND`, `ERR_DATA_CATEGORY_NOT_FOUND`, `ERR_BASELINE_NOT_FOUND`, `ERR_CONTROL_IMPLEMENTATION_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_TEST_SLOT_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_POAM_ITEM_NOT_FOUND`, `ERR_DEVIATION_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_MONITORING_PERIOD_NOT_FOUND`, `ERR_CHANGE_REQUEST_NOT_FOUND`, `ERR_REUSE_GRANT_NOT_FOUND` or `ERR_AGENCY_NOT_FOUND`."

    Design: Corner/endpoints/a_reuse_grant_links_an_authorization_to_an_agency_and_both_ends_must_exist
    """
    env = _authorization_with_second_agency(client)
    version = fx.authorization_version(client, env["authorization_id"])

    validate_error(
        client.create_reuse_grant(
            f.build_reuse_grant_payload(
                env["authorization_id"], UNKNOWN_AGENCY_ID, version
            ),
            make_agency_official_headers(UNKNOWN_AGENCY_ID),
        ),
        ERR_AGENCY_NOT_FOUND,
        404,
    )


def test_a_new_reuse_grant_opens_in_the_requested_state(client):
    """The link is written between both named ends with the documented opening values.

    PRD: "On success the grant opens with `access_state` `REQUESTED`, `incremental_review_findings_count` 0, `notice_count` 0, `reuse_accepted_at` null and `revoked_reason` null; the granting agency's `reuse_grant_count` increments by one and the authorization's `version` increments by one."

    Design: Corner/endpoints/a_reuse_grant_links_an_authorization_to_an_agency_and_both_ends_must_exist
    """
    env = _authorization_with_second_agency(client)
    version = fx.authorization_version(client, env["authorization_id"])

    grant = validate_success(
        client.create_reuse_grant(
            f.build_reuse_grant_payload(
                env["authorization_id"], env["epa_id"], version
            ),
            env["epa_headers"],
        ),
        201,
    )

    assert grant["authorization_id"] == env["authorization_id"]
    assert grant["agency_id"] == env["epa_id"]
    assert grant["access_state"] == "REQUESTED"
    A.assert_integer(
        grant["incremental_review_findings_count"],
        0,
        "incremental_review_findings_count",
    )
    A.assert_integer(grant["notice_count"], 0, "notice_count")
    assert grant["reuse_accepted_at"] is None
    assert grant["revoked_reason"] is None

    stored = fx.read_reuse_grant(client, grant["id"])
    assert stored["id"] == grant["id"]
    assert stored["access_state"] == "REQUESTED"


def test_the_new_grant_consumes_one_reuse_seat(client):
    """The seat ledger on the authorization records the link from its own side.

    PRD: "Seats are finite — `reuse_seats_granted` counts the authorization's grants not in `REVOKED` and `reuse_seats_available` is `reuse_seats_total` less that count — and a request arriving when no seat is available is refused with `ERR_REUSE_SEATS_EXHAUSTED`."

    Design: Corner/endpoints/a_reuse_grant_links_an_authorization_to_an_agency_and_both_ends_must_exist
    """
    env = _authorization_with_second_agency(client)
    fx.seed_reuse_grant(client, env, agency_id=env["epa_id"])

    authorization = fx.read_authorization(client, env["authorization_id"])

    A.assert_integer(authorization["reuse_seats_total"], 5, "reuse_seats_total")
    A.assert_integer(authorization["reuse_seats_granted"], 1, "reuse_seats_granted")
    A.assert_integer(authorization["reuse_seats_available"], 4, "reuse_seats_available")
    A.assert_seat_conservation(authorization)


def test_the_new_grant_is_visible_from_the_grantee_agency(client):
    """The grantee agency's counter and the authorization's version both move by one.

    PRD: "On success the grant opens with `access_state` `REQUESTED`, `incremental_review_findings_count` 0, `notice_count` 0, `reuse_accepted_at` null and `revoked_reason` null; the granting agency's `reuse_grant_count` increments by one and the authorization's `version` increments by one."

    Design: Corner/endpoints/a_reuse_grant_links_an_authorization_to_an_agency_and_both_ends_must_exist
    """
    env = _authorization_with_second_agency(client)
    before = fx.authorization_version(client, env["authorization_id"])
    A.assert_integer(
        fx.read_agency(client, env["epa_id"])["reuse_grant_count"],
        0,
        "reuse_grant_count before the grant",
    )

    fx.seed_reuse_grant(client, env, agency_id=env["epa_id"])

    A.assert_integer(
        fx.read_agency(client, env["epa_id"])["reuse_grant_count"],
        1,
        "reuse_grant_count",
    )
    A.assert_integer(
        fx.authorization_version(client, env["authorization_id"]),
        before + 1,
        "authorization version",
    )


def test_a_second_grant_for_the_same_pair_is_refused_as_duplicate(client):
    """One authorization and one agency may hold only one live grant.

    PRD: "The same pair of authorization and agency may not hold two live grants: an existing grant for that pair in any state other than `REVOKED` causes `ERR_DUPLICATE_REUSE_GRANT`."

    Design: Corner/endpoints/a_reuse_grant_links_an_authorization_to_an_agency_and_both_ends_must_exist
    """
    env = _authorization_with_second_agency(client)
    fx.seed_reuse_grant(client, env, agency_id=env["epa_id"])
    refreshed = fx.authorization_version(client, env["authorization_id"])

    validate_error(
        client.create_reuse_grant(
            f.build_reuse_grant_payload(
                env["authorization_id"], env["epa_id"], refreshed
            ),
            env["epa_headers"],
        ),
        ERR_DUPLICATE_REUSE_GRANT,
        409,
    )

    authorization = fx.read_authorization(client, env["authorization_id"])
    A.assert_integer(authorization["reuse_seats_granted"], 1, "reuse_seats_granted")
    A.assert_integer(authorization["reuse_seats_available"], 4, "reuse_seats_available")


def test_grants_are_listed_by_authorization_and_access_state(client):
    """The grant listing narrows on its authorization and its access state.

    PRD: "Grants are listed with filters on `authorization_id`, `agency_id` and `access_state`."

    Design: Corner/endpoints/a_reuse_grant_links_an_authorization_to_an_agency_and_both_ends_must_exist
    """
    env = _authorization_with_second_agency(client)
    fx.seed_reuse_grant(client, env, agency_id=env["epa_id"])

    data, meta = validate_paginated(
        client.list_reuse_grants(
            CSP_LEAD_HEADERS,
            {"authorization_id": env["authorization_id"], "access_state": "REQUESTED"},
        )
    )

    assert meta["total_count"] == 1
    assert A.ids_of(data) == [env["grant_id"]]
    assert data[0]["agency_id"] == env["epa_id"]


# ---------------------------------------------------------------------------
# The monitoring period read derives its coverage from the submissions
# ---------------------------------------------------------------------------


def test_a_submission_missing_a_mandatory_scan_type_is_refused(client):
    """A scan set without DATABASE is an incomplete set.

    PRD: "Three of those four are mandatory in every submission: a `scan_types` array that omits `INFRASTRUCTURE`, `WEB_APP` or `DATABASE` is refused with `ERR_INCOMPLETE_SCAN_SET`, while `CONTAINER` is optional."

    Design: Corner/endpoints/the_monitoring_period_read_derives_its_coverage_from_the_submissions
    """
    env = fx.seed_authorized_offering(client)

    validate_error(
        client.create_scan_submission(
            env["period_id"],
            f.build_scan_submission_payload(["INFRASTRUCTURE", "WEB_APP"]),
            env["lead_headers"],
        ),
        ERR_INCOMPLETE_SCAN_SET,
        422,
    )


def test_a_refused_submission_leaves_the_period_counters_empty(client):
    """The refused set writes nothing: coverage empty and all three counters 0.

    PRD: "The period opens in status `OPEN` with `accepted_submission_count`, `late_submission_count` and `rejected_submission_count` at 0, `covered_scan_types` an empty array, and `closed_at` null."

    Design: Corner/endpoints/the_monitoring_period_read_derives_its_coverage_from_the_submissions
    """
    env = fx.seed_authorized_offering(client)
    validate_error(
        client.create_scan_submission(
            env["period_id"],
            f.build_scan_submission_payload(["INFRASTRUCTURE", "WEB_APP"]),
            env["lead_headers"],
        ),
        ERR_INCOMPLETE_SCAN_SET,
        422,
    )

    period = validate_success(
        client.get_monitoring_period(env["period_id"], env["agency_headers"]), 200
    )

    assert period["covered_scan_types"] == []
    A.assert_integer(
        period["accepted_submission_count"], 0, "accepted_submission_count"
    )
    A.assert_integer(period["late_submission_count"], 0, "late_submission_count")
    A.assert_integer(period["rejected_submission_count"], 0, "rejected_submission_count")
    assert period["status"] == "OPEN"
    assert period["closed_at"] is None


def test_a_complete_scan_set_delivered_before_the_due_instant_is_accepted(client):
    """A submission at or before scan_due_at is on time and therefore ACCEPTED.

    PRD: "The submission's `status` follows directly from that figure — `ACCEPTED` when `days_late` is 0, `LATE_ACCEPTED` when `days_late` is 1, 2 or 3, and `REJECTED` when `days_late` is 4 or more."

    Design: Corner/endpoints/the_monitoring_period_read_derives_its_coverage_from_the_submissions
    """
    env = fx.seed_authorized_offering(client)

    submission = validate_success(
        client.create_scan_submission(
            env["period_id"],
            f.build_scan_submission_payload(
                ["INFRASTRUCTURE", "WEB_APP", "DATABASE"]
            ),
            env["lead_headers"],
        ),
        201,
    )

    A.assert_integer(submission["days_late"], 0, "days_late")
    assert submission["status"] == "ACCEPTED"


def test_a_partial_follow_up_submission_cannot_widen_the_union(client):
    """Every submission must carry all three mandatory types, even a follow-up one.

    PRD: "Three of those four are mandatory in every submission: a `scan_types` array that omits `INFRASTRUCTURE`, `WEB_APP` or `DATABASE` is refused with `ERR_INCOMPLETE_SCAN_SET`, while `CONTAINER` is optional."

    Design: Corner/endpoints/the_monitoring_period_read_derives_its_coverage_from_the_submissions
    """
    env = fx.seed_authorized_offering(client)
    fx.submit_scans(
        client,
        env,
        env["period_id"],
        scan_types=["INFRASTRUCTURE", "WEB_APP", "DATABASE"],
    )

    validate_error(
        client.create_scan_submission(
            env["period_id"],
            f.build_scan_submission_payload(["DATABASE"]),
            env["lead_headers"],
        ),
        ERR_INCOMPLETE_SCAN_SET,
        422,
    )


def test_the_period_read_reports_the_sorted_union_of_accepted_scan_types(client):
    """covered_scan_types is derived from the accepted submissions, sorted.

    PRD: "The period's `covered_scan_types` is then the sorted union of the `scan_types` of all its submissions whose `status` is `ACCEPTED` or `LATE_ACCEPTED`, so a rejected submission contributes no coverage at all."

    Design: Corner/endpoints/the_monitoring_period_read_derives_its_coverage_from_the_submissions
    """
    env = fx.seed_authorized_offering(client)
    fx.submit_scans(
        client,
        env,
        env["period_id"],
        scan_types=["INFRASTRUCTURE", "WEB_APP", "DATABASE"],
    )
    validate_error(
        client.create_scan_submission(
            env["period_id"],
            f.build_scan_submission_payload(["DATABASE"]),
            env["lead_headers"],
        ),
        ERR_INCOMPLETE_SCAN_SET,
        422,
    )

    period = validate_success(
        client.get_monitoring_period(env["period_id"], BOARD_HEADERS), 200
    )

    assert period["covered_scan_types"] == ["DATABASE", "INFRASTRUCTURE", "WEB_APP"]


def test_the_period_counters_follow_the_graded_submissions(client):
    """Only the accepted submission moves a counter, and only its own counter.

    PRD: "The matching period counter increments by one: `accepted_submission_count` for `ACCEPTED`, `late_submission_count` for `LATE_ACCEPTED`, `rejected_submission_count` for `REJECTED`."

    Design: Corner/endpoints/the_monitoring_period_read_derives_its_coverage_from_the_submissions
    """
    env = fx.seed_authorized_offering(client)
    fx.submit_scans(
        client,
        env,
        env["period_id"],
        scan_types=["INFRASTRUCTURE", "WEB_APP", "DATABASE"],
    )

    period = fx.read_monitoring_period(client, env["period_id"])

    A.assert_integer(
        period["accepted_submission_count"], 1, "accepted_submission_count"
    )
    A.assert_integer(period["late_submission_count"], 0, "late_submission_count")
    A.assert_integer(period["rejected_submission_count"], 0, "rejected_submission_count")


def test_the_period_read_reports_the_window_derived_from_its_month(client):
    """The three period instants stay derived from period_month across submissions.

    PRD: "The server derives three instants from the month: `window_start` is the first instant of that month inclusive, `window_end` is the first instant of the following month exclusive, and `scan_due_at` is five days after `window_end`."

    Design: Corner/endpoints/the_monitoring_period_read_derives_its_coverage_from_the_submissions
    """
    env = fx.seed_authorized_offering(client)
    fx.submit_scans(
        client,
        env,
        env["period_id"],
        scan_types=["INFRASTRUCTURE", "WEB_APP", "DATABASE"],
    )

    period = fx.read_monitoring_period(client, env["period_id"])

    A.assert_monitoring_window(period, "2026-03")
    A.assert_instant(period["window_end"], "2026-04-01T00:00:00Z", "window_end")
    A.assert_instant(period["scan_due_at"], "2026-04-06T00:00:00Z", "scan_due_at")


def test_only_the_accepted_submission_appears_in_the_submissions_listing(client):
    """The append-only listing holds exactly the one submission that was written.

    PRD: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filters before the page window is applied."

    Design: Corner/endpoints/the_monitoring_period_read_derives_its_coverage_from_the_submissions
    """
    env = fx.seed_authorized_offering(client)
    accepted = fx.submit_scans(
        client,
        env,
        env["period_id"],
        scan_types=["INFRASTRUCTURE", "WEB_APP", "DATABASE"],
    )
    validate_error(
        client.create_scan_submission(
            env["period_id"],
            f.build_scan_submission_payload(["DATABASE"]),
            env["lead_headers"],
        ),
        ERR_INCOMPLETE_SCAN_SET,
        422,
    )

    data, meta = validate_paginated(
        client.list_scan_submissions(env["period_id"], ASSESSOR_HEADERS)
    )

    assert meta["total_count"] == 1
    assert A.ids_of(data) == [accepted["id"]]


# ---------------------------------------------------------------------------
# Each remediation action belongs to the role that owns it
# ---------------------------------------------------------------------------


def test_starting_remediation_is_refused_to_the_assessor(client):
    """START belongs to the provider, so the assessor is refused on the action.

    PRD: "`START` and `SUBMIT_EVIDENCE` require a `CspComplianceLead` and `VERIFY_CLOSE` and `REOPEN` require a `ThirdPartyAssessor`; the wrong role for the requested action is refused with `ERR_ACTION_ROLE_MISMATCH`."

    Design: Corner/endpoints/each_remediation_action_is_allowed_only_for_the_role_that_owns_it
    """
    env = _open_finding(client)

    validate_error(
        client.advance_remediation(
            env["poam_id"], f.build_remediation_payload("START"), ASSESSOR_HEADERS
        ),
        ERR_ACTION_ROLE_MISMATCH,
        403,
    )

    item = fx.read_poam_item(client, env["poam_id"])
    assert item["remediation_status"] == "OPEN"
    assert item["risk_disposition"] == "NONE"


def test_starting_remediation_from_the_compliance_lead_moves_the_finding(client):
    """START from the owning lead advances only the remediation dimension.

    PRD: "`START` moves `remediation_status` `OPEN → IN_REMEDIATION` and recomputes the authorization's `residual_risk_score` when the offering has an authorization, leaving `risk_disposition` untouched."

    Design: Corner/endpoints/each_remediation_action_is_allowed_only_for_the_role_that_owns_it
    """
    env = _open_finding(client)

    item = validate_success(
        client.advance_remediation(
            env["poam_id"], f.build_remediation_payload("START"), env["lead_headers"]
        ),
        200,
    )

    assert item["remediation_status"] == "IN_REMEDIATION"
    assert item["risk_disposition"] == "NONE"


def test_submitting_evidence_is_refused_to_the_assessor(client):
    """SUBMIT_EVIDENCE is the provider's action too, so the assessor is refused.

    PRD: "`START` and `SUBMIT_EVIDENCE` require a `CspComplianceLead` and `VERIFY_CLOSE` and `REOPEN` require a `ThirdPartyAssessor`; the wrong role for the requested action is refused with `ERR_ACTION_ROLE_MISMATCH`."

    Design: Corner/endpoints/each_remediation_action_is_allowed_only_for_the_role_that_owns_it
    """
    env = _open_finding(client)
    fx.drive_remediation(client, env, env["poam_id"], ["START"])

    validate_error(
        client.advance_remediation(
            env["poam_id"],
            f.build_remediation_payload("SUBMIT_EVIDENCE"),
            ASSESSOR_HEADERS,
        ),
        ERR_ACTION_ROLE_MISMATCH,
        403,
    )

    assert (
        fx.read_poam_item(client, env["poam_id"])["remediation_status"]
        == "IN_REMEDIATION"
    )


def test_submitting_evidence_from_the_lead_awaits_verification(client):
    """SUBMIT_EVIDENCE from the lead hands the finding to the assessor.

    PRD: "`SUBMIT_EVIDENCE` moves `IN_REMEDIATION → AWAITING_VERIFICATION` and has no further effect."

    Design: Corner/endpoints/each_remediation_action_is_allowed_only_for_the_role_that_owns_it
    """
    env = _open_finding(client)
    fx.drive_remediation(client, env, env["poam_id"], ["START"])

    item = validate_success(
        client.advance_remediation(
            env["poam_id"],
            f.build_remediation_payload("SUBMIT_EVIDENCE"),
            env["lead_headers"],
        ),
        200,
    )

    assert item["remediation_status"] == "AWAITING_VERIFICATION"
    assert item["risk_disposition"] == "NONE"


@pytest.mark.parametrize("action", ["VERIFY_CLOSE", "REOPEN"])
def test_the_verification_actions_are_refused_to_the_compliance_lead(client, action):
    """VERIFY_CLOSE and REOPEN belong to the assessor, not to the provider.

    PRD: "`START` and `SUBMIT_EVIDENCE` require a `CspComplianceLead` and `VERIFY_CLOSE` and `REOPEN` require a `ThirdPartyAssessor`; the wrong role for the requested action is refused with `ERR_ACTION_ROLE_MISMATCH`."

    Design: Corner/endpoints/each_remediation_action_is_allowed_only_for_the_role_that_owns_it
    """
    env = _open_finding(client)
    fx.drive_remediation(client, env, env["poam_id"], ["START", "SUBMIT_EVIDENCE"])

    validate_error(
        client.advance_remediation(
            env["poam_id"], f.build_remediation_payload(action), env["lead_headers"]
        ),
        ERR_ACTION_ROLE_MISMATCH,
        403,
    )

    item = fx.read_poam_item(client, env["poam_id"])
    assert item["remediation_status"] == "AWAITING_VERIFICATION"
    A.assert_integer(item["reopen_count"], 0, "reopen_count")


def test_verified_closure_from_the_assessor_closes_the_finding_as_remediated(client):
    """VERIFY_CLOSE from the assessor closes the finding with the remediated reason.

    PRD: "`VERIFY_CLOSE` moves `AWAITING_VERIFICATION → CLOSED`, sets `closure_reason` to `REMEDIATED`, and recomputes the authorization's `open_findings_count`, `closed_findings_count` and `residual_risk_score`; it is refused with `ERR_DEVIATION_PENDING_ON_ITEM` while any deviation on the item is still in `SUBMITTED`, `BOARD_REVIEW` or `AGENCY_REVIEW`."

    Design: Corner/endpoints/each_remediation_action_is_allowed_only_for_the_role_that_owns_it
    """
    env = _open_finding(client)
    fx.drive_remediation(client, env, env["poam_id"], ["START", "SUBMIT_EVIDENCE"])

    item = validate_success(
        client.advance_remediation(
            env["poam_id"],
            f.build_remediation_payload("VERIFY_CLOSE"),
            ASSESSOR_HEADERS,
        ),
        200,
    )

    assert item["remediation_status"] == "CLOSED"
    assert item["closure_reason"] == "REMEDIATED"
    assert item["risk_disposition"] == "NONE"
