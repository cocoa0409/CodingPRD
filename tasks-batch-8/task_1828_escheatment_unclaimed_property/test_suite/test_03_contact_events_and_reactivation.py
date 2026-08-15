"""Contact evidence, reactivation evidence gates, and the reactivation
cascade into draft reports (PRD §3.1, §3.3)."""
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
    add_line_item,
    create_dormant_property,
    create_owner,
    create_property,
    create_report,
    create_reportable_property,
    create_rule,
    get_property,
    get_report,
    record_contact,
    run_sweep,
    submit_report,
)

CO_H = TEST_USERS["compliance_officer_headers"]


class TestContactEventDerivation:
    def test_qualifies_and_last_contact_max_accumulator(self, api):
        """PRD §3.1: "From the type, the server derives
        `qualifies_for_reactivation`: it is true for `WITHDRAWAL`, `DEPOSIT`,
        `WRITTEN_CORRESPONDENCE`, and `IN_PERSON`, and always false for
        `LOGIN_VERIFIED` and `PHONE_VERIFIED`, which are considered too weak to
        prove the owner is alive and engaged."
        PRD §3.1: "Every recorded contact also refreshes the property it
        concerns: the `last_contact_date` advances to the later of its current
        value and the event's `contact_date`, and it is this maintained date
        that the dormancy sweep of §3.2 measures against."

        Design: Corner/entities/contact_event_qualifies_and_last_contact_maintenance
        """
        create_rule()
        owner = create_owner()
        prop = create_property(owner["id"], original_value_cents=45000)
        ev1 = record_contact(prop["id"], contact_type="WITHDRAWAL",
                             contact_date="2026-05-05", evidence_ref="wd-1")
        assert ev1["qualifies_for_reactivation"] is True
        assert get_property(prop["id"])["last_contact_date"] == "2026-05-05"
        # Backdated qualifying event: the accumulator must not regress.
        ev2 = record_contact(prop["id"], contact_type="DEPOSIT",
                             contact_date="2024-01-01", evidence_ref="dep-old")
        assert ev2["qualifies_for_reactivation"] is True
        assert get_property(prop["id"])["last_contact_date"] == "2026-05-05"
        # Non-qualifying type still feeds the max-accumulator.
        ev3 = record_contact(prop["id"], contact_type="LOGIN_VERIFIED",
                             contact_date="2026-06-01", evidence_ref="login-1")
        assert ev3["qualifies_for_reactivation"] is False
        assert get_property(prop["id"])["last_contact_date"] == "2026-06-01"


class TestReactivationEvidenceGates:
    def test_foreign_contact_event_rejected(self, api):
        """PRD §3.3: "That event must exist (otherwise
        `ERR_CONTACT_EVENT_NOT_FOUND`), must belong to the same property
        (otherwise `ERR_CONTACT_EVENT_PROPERTY_MISMATCH`), must be one whose
        `qualifies_for_reactivation` is true, and must carry a `contact_date`
        on or after the letter's `sent_date` — a qualifying-type or date
        failure surfaces as `ERR_CONTACT_NOT_QUALIFYING`."

        Design: Corner/errors/reactivate_with_foreign_contact_event_rejected
        """
        create_rule()
        owner = create_owner()
        p1 = create_property(owner["id"], original_value_cents=50000)
        p2 = create_property(owner["id"], original_value_cents=60000)
        run_sweep()  # both DORMANT
        ev2 = record_contact(p2["id"], contact_date="2026-08-01",
                             evidence_ref="wd-p2")
        resp = api.reactivate_property(
            p1["id"], {"evidence_contact_event_id": ev2["id"]}, CO_H
        )
        validate_error(resp, ApiErrorId.ERR_CONTACT_EVENT_PROPERTY_MISMATCH, 422)
        assert get_property(p1["id"])["status"] == "DORMANT"

    def test_non_qualifying_contact_rejected(self, api):
        """PRD §3.3: "the cited event must exist, belong to this property, and
        qualify, under the same three evidence errors as above."

        Design: Corner/errors/reactivate_with_non_qualifying_contact_rejected
        """
        _, _, prop = create_dormant_property(original_value_cents=50000)
        ev = record_contact(prop["id"], contact_type="LOGIN_VERIFIED",
                            contact_date="2026-08-01", evidence_ref="login-ev")
        resp = api.reactivate_property(
            prop["id"], {"evidence_contact_event_id": ev["id"]}, CO_H
        )
        validate_error(resp, ApiErrorId.ERR_CONTACT_NOT_QUALIFYING, 422)
        assert get_property(prop["id"])["status"] == "DORMANT"

    def test_reactivate_blocked_by_submitted_report(self, api):
        """PRD §3.3: "When the property is `REPORTABLE`, one more guard
        applies: no line in `INCLUDED` or `FINAL` status for this property may
        belong to a report that is `SUBMITTED` or `ACCEPTED` — a property
        already bound into a filed report cannot be pulled back, and the
        attempt is refused with `ERR_PROPERTY_IN_SUBMITTED_REPORT`."

        Design: Corner/errors/reactivate_blocked_by_submitted_report
        """
        _, _, prop, _ = create_reportable_property(original_value_cents=50000)
        report = create_report()
        line = add_line_item(report["id"], prop["id"])
        submit_report(report["id"])
        ev = record_contact(prop["id"], contact_type="IN_PERSON",
                            contact_date="2026-09-01", evidence_ref="branch-1")
        resp = api.reactivate_property(
            prop["id"], {"evidence_contact_event_id": ev["id"]}, CO_H
        )
        validate_error(resp, ApiErrorId.ERR_PROPERTY_IN_SUBMITTED_REPORT, 409)
        assert get_property(prop["id"])["status"] == "REPORTABLE"
        lines, _ = validate_paginated(api.list_line_items(report["id"], READER))
        assert len(lines) == 1 and lines[0]["status"] == "FINAL"
        assert get_report(report["id"])["status"] == "SUBMITTED"


class TestReactivationCascade:
    def _reportable_with_draft_line(self):
        rule, owner, prop, letter = create_reportable_property(
            original_value_cents=50000
        )
        report = create_report()
        line = add_line_item(report["id"], prop["id"])
        ev = record_contact(prop["id"], contact_type="IN_PERSON",
                            contact_date="2026-08-20", evidence_ref="branch-77")
        return prop, report, line, ev

    def test_reactivate_removes_draft_line(self, api):
        """PRD §3.3: "Every report line item for this property with status
        `INCLUDED` whose containing report is still `DRAFT` is removed to
        `REMOVED`."

        Design: Difficulty/transitive_cascade/reactivation_cascade_line_removal_totals
        """
        prop, report, line, ev = self._reportable_with_draft_line()
        resp = api.reactivate_property(
            prop["id"], {"evidence_contact_event_id": ev["id"]}, CO_H
        )
        reactivated = validate_success(resp, 200)
        assert reactivated["status"] == "ACTIVE"
        lines, _ = validate_paginated(api.list_line_items(report["id"], READER))
        assert lines[0]["id"] == line["id"]
        assert lines[0]["status"] == "REMOVED"

    def test_reactivate_recomputes_report_totals_and_version(self, api):
        """PRD §3.3: "And each affected draft report recomputes its
        `total_provisional_cents`, `total_final_cents`, and `line_count`, with
        its `version` incrementing — the same eager recomputation §2.8
        prescribes"

        Design: Difficulty/transitive_cascade/reactivation_cascade_line_removal_totals
        """
        prop, report, line, ev = self._reportable_with_draft_line()
        before = get_report(report["id"])
        assert before["total_provisional_cents"] == 50000
        get_success_data(
            api.reactivate_property(
                prop["id"], {"evidence_contact_event_id": ev["id"]}, CO_H
            ),
            200,
        )
        after = get_report(report["id"])
        assert after["total_provisional_cents"] == 0
        assert after["total_final_cents"] == 0
        assert after["line_count"] == 0
        assert_version_incremented(after["version"], before["version"])

    def test_immediate_visibility_of_reactivation_cascade(self, api):
        """PRD §2.8: "when an operation's effects cross entity boundaries, the
        server applies every hop of the cascade itself, without requiring
        separate client calls on the affected resources. A property's
        reactivation removes its lines from draft reports"

        Design: Corner/consistency_model/immediate_visibility_after_mutation
        """
        _, _, prop, _ = create_reportable_property(original_value_cents=50000)
        report = create_report()
        line = add_line_item(report["id"], prop["id"])
        ev = record_contact(prop["id"], contact_type="DEPOSIT",
                            contact_date="2026-08-25", evidence_ref="dep-1")
        resp = api.reactivate_property(
            prop["id"], {"evidence_contact_event_id": ev["id"]}, CO_H
        )
        body = validate_success(resp, 200)
        assert body["status"] == "ACTIVE", (
            "mutation is visible in its own response"
        )
        lines, _ = validate_paginated(api.list_line_items(report["id"], READER))
        assert lines[0]["status"] == "REMOVED"
        report_after = get_report(report["id"])
        assert report_after["total_provisional_cents"] == 0
        assert report_after["line_count"] == 0
