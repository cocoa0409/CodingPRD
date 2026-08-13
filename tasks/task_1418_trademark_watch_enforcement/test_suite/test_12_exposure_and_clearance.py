"""Portfolio exposure index input-set filtering and threshold, and clearance
searches: computed fields, hit disposition bounds, and finalize outcomes."""
import pytest

from test_helpers import (
    ApiErrorId,
    assess_alert,
    create_alert,
    create_clearance_search,
    create_client,
    create_record,
    escalate_alert,
    get_client,
    get_record,
    make_associate_headers,
    make_client_contact_headers,
    make_partner_headers,
    publish_record,
    register_record,
    setup_registered_record,
    triage_alert,
    validate_error,
    validate_success,
)


class TestExposureIndex:
    def test_exposure_index_recompute_on_resolve(self, api, paralegal_headers,
                                                 partner_headers):
        """PRD §2.7: "Each client carries a computed `exposure_index`: the sum, over
        all of the client's enforcement matters currently in `ACTIVE` status, of a
        per-matter weight — 10 for `OPPOSITION`, 15 for `CANCELLATION`, 20 for
        `INFRINGEMENT`, and 25 for `COUNTERFEIT`"
        PRD §2.7: "Resolved matters contribute nothing."

        Design: Corner/calculations/exposure_index_recompute_on_resolve
        """
        client = create_client()
        record_a = create_record(client["id"], mark_text="ALPHA", classes=(9,),
                                 app_no="US-A1")
        publish_record(record_a["id"], "2026-08-03T00:00:00Z")
        record_b = create_record(client["id"], mark_text="BETA", classes=(9,),
                                 app_no="US-B1")
        publish_record(record_b["id"], "2026-08-03T00:00:00Z")
        register_record(record_b["id"], "2026-08-10T00:00:00Z")

        alert_a = create_alert(record_a["id"], 80, 70, 60,
                               conflicting_mark_text="ALFA")
        alert_a = triage_alert(alert_a["id"])
        alert_a = assess_alert(alert_a["id"], alert_a["version"])
        matter_a = escalate_alert(alert_a["id"], "OPPOSITION")

        alert_b = create_alert(record_b["id"], 80, 70, 60,
                               conflicting_mark_text="BETA2")
        alert_b = triage_alert(alert_b["id"])
        alert_b = assess_alert(alert_b["id"], alert_b["version"])
        matter_b = escalate_alert(alert_b["id"], "CANCELLATION")

        before = get_client(client["id"])
        assert before["exposure_index"] == 25
        assert before["watch_posture"] == "STANDARD"

        validate_success(
            api.resolve_matter(matter_b["id"], {"outcome": "FAVORABLE"},
                               partner_headers), 200)
        after = get_client(client["id"])
        assert after["exposure_index"] == 10
        assert after["watch_posture"] == "STANDARD"
        # Favorable cancellation resolve restores the record to REGISTERED.
        assert get_record(record_b["id"])["status"] == "REGISTERED"
        assert get_record(record_a["id"])["status"] == "UNDER_CHALLENGE"

    def test_exposure_threshold_elevated_at_exactly_100(self, api,
                                                        paralegal_headers):
        """PRD §2.7: "The client's `watch_posture` is `ELEVATED` whenever the index
        is at least 100 and `STANDARD` otherwise."

        Design: Corner/calculations/exposure_threshold_elevated_at_exactly_100
        """
        client, record = setup_registered_record(classes=(25,))

        for i in range(3):
            alert = create_alert(record["id"], 80, 70, 60,
                                 conflicting_mark_text=f"FAKE{i + 1}",
                                 conflicting_classes=(25,))
            alert = triage_alert(alert["id"])
            alert = assess_alert(alert["id"], alert["version"])
            escalate_alert(alert["id"], "COUNTERFEIT")

        before = get_client(client["id"])
        assert before["exposure_index"] == 75
        assert before["watch_posture"] == "STANDARD"

        alert4 = create_alert(record["id"], 80, 70, 60,
                              conflicting_mark_text="FAKE4",
                              conflicting_classes=(25,))
        alert4 = triage_alert(alert4["id"])
        alert4 = assess_alert(alert4["id"], alert4["version"])
        escalate_alert(alert4["id"], "COUNTERFEIT")

        after = get_client(client["id"])
        assert after["exposure_index"] == 100
        assert after["watch_posture"] == "ELEVATED"


class TestClearanceSearches:
    def test_clearance_search_computed_fields_on_create(self, api):
        """PRD §3.9: "A `ClientContact` (for their own `client_id`) or a `Paralegal`
        opens a search with the `proposed_mark` and `proposed_classes`, optionally
        seeding `conflict_hits`; the search starts `OPEN` with
        `unresolved_hit_count` and `risk_rating` computed. Each hit records a
        `conflicting_mark`, a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `IDENTICAL`,
        and a `disposition` that begins `OPEN`"

        Design: Corner/entities/clearance_search_computed_fields_on_create
        """
        client = create_client()
        search = create_clearance_search(
            client["id"], proposed_mark="ACMEPRO", proposed_classes=[9],
            conflict_hits=[{"conflicting_mark": "ACME", "severity": "HIGH"}])
        assert search["status"] == "OPEN"
        assert search["unresolved_hit_count"] == 1
        assert search["risk_rating"] == "HIGH"
        assert search["conflict_hits"][0]["disposition"] == "OPEN"

    def test_dispose_hit_index_out_of_range_rejected(self, api, associate_headers):
        """PRD §3.9: "An `AssociateAttorney` appends a hit to an `OPEN` search by
        `conflicting_mark` and `severity`, and disposes a hit by its 0-based
        `hit_index` — an out-of-range index is `ERR_VALIDATION` — setting
        `disposition` to `WAIVED` or `BLOCKING`."

        Design: Corner/endpoints/dispose_hit_index_out_of_range_rejected
        """
        client = create_client()
        search = create_clearance_search(
            client["id"], proposed_mark="ACMEPRO", proposed_classes=[9],
            conflict_hits=[{"conflicting_mark": "ACME", "severity": "HIGH"}])

        res = api.dispose_hit(search["id"], {"hit_index": 5, "disposition": "WAIVED"},
                              associate_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)
        refreshed = validate_success(
            api.get_clearance_search(search["id"], associate_headers), 200)
        assert refreshed["unresolved_hit_count"] == 1

    def test_clearance_finalize_blocked_until_hits_resolved(
        self, api, associate_headers, partner_headers
    ):
        """PRD §3.9: "A `PartnerAttorney` finalizes the search: any hit still `OPEN`
        is rejected with `ERR_UNRESOLVED_HITS`; with none unresolved, the presence of
        at least one `BLOCKING` hit lands the search in `BLOCKED`, otherwise in
        `CLEARED`. Both are terminal."
        PRD §3.9: "Either mutation recomputes `unresolved_hit_count` (the number of
        hits still `OPEN`) and `risk_rating`, which is the maximum severity among
        non-waived hits with `IDENTICAL` mapped to `HIGH`, or `LOW` when nothing
        non-waived remains."

        Design: Corner/validations/clearance_finalize_blocked_until_hits_resolved
        """
        client = create_client()
        search_a = create_clearance_search(
            client["id"], proposed_mark="ACMEPRO", proposed_classes=[9],
            conflict_hits=[{"conflicting_mark": "ACME", "severity": "HIGH"}])
        search_b = create_clearance_search(
            client["id"], proposed_mark="ACMEZO", proposed_classes=[9],
            conflict_hits=[{"conflicting_mark": "ACME", "severity": "MEDIUM"}])
        disposed_b = validate_success(
            api.dispose_hit(search_b["id"], {"hit_index": 0,
                                             "disposition": "BLOCKING"},
                            associate_headers), 200)
        assert disposed_b["unresolved_hit_count"] == 0

        res = api.finalize_clearance_search(search_a["id"], partner_headers)
        validate_error(res, ApiErrorId.ERR_UNRESOLVED_HITS, expected_status=422)

        waived = validate_success(
            api.dispose_hit(search_a["id"], {"hit_index": 0, "disposition": "WAIVED"},
                            associate_headers), 200)
        assert waived["unresolved_hit_count"] == 0
        assert waived["risk_rating"] == "LOW"

        cleared = validate_success(
            api.finalize_clearance_search(search_a["id"], partner_headers), 200)
        assert cleared["status"] == "CLEARED"

        blocked = validate_success(
            api.finalize_clearance_search(search_b["id"], partner_headers), 200)
        assert blocked["status"] == "BLOCKED"
