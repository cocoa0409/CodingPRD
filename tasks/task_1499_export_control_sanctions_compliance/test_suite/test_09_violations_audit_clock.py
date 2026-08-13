"""Violations & VSD workflow, audit record immutability/retention, clock sweeps (PRD §2.4, §2.5, §2.10, §2.11, §3.9)."""
from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    assert_audit_record,
    audit_records_for,
    create_approved_license,
    create_classified_product,
    create_draft_classification,
    create_order,
    create_party,
    create_product,
    create_shipment,
    list_audit_records,
    parse_iso,
    purge_audit_records,
    review_classification,
    set_clock,
    setup_released_not_required_order,
    submit_classification,
    to_iso_z,
    validate_error,
    validate_success,
)


class TestViolationWorkflow:
    def test_violation_vsd_full_path_side_effects(self, api, analyst_headers, manager_headers,
                                                  manager2_headers, director_headers):
        """PRD §3.9: "Only a substantiated violation can be disclosed to the regulator, and only the `ComplianceDirector` may file it. Submission moves `SUBSTANTIATED → DISCLOSED`, assigns a `disclosure_reference` from a system-wide monotone counter formatted as `VSD-` followed by six zero-padded digits beginning at `VSD-000001`, and writes an audit record of type `VSD_SUBMITTED`. Closure is a manager action via the `CLOSE` event from either `DISCLOSED` or `UNFOUNDED`, again segregated from `identified_by_user_id`, and it writes `VIOLATION_CLOSED`. `CLOSED` is terminal."
        PRD §3.9: "From `UNDER_REVIEW`, `SUBSTANTIATE` lands the case at `SUBSTANTIATED` and `DISMISS` lands it at `UNFOUNDED`; both adjudication events require the actor's `X-User-ID` to differ from `identified_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`) and anchor `adjudicated_by_user_id`."

        Design: Corner/state_machines/violation_vsd_full_path_side_effects
        """
        # PRD §2.9 applies the existence discipline to a violation's polymorphic
        # source_id, so the SHIPMENT-typed source must name a real shipment.
        ctx = setup_released_not_required_order(
            party_name="Odense Components APS", party_country="DNK", party_city="Odense",
            destination_country="DNK", quantity=1, unit_value_cents=500,
        )
        shipment = create_shipment(ctx["order"]["id"], quantity=1)
        violation = validate_success(
            api.create_violation(
                {"source_type": "SHIPMENT",
                 "source_id": shipment["id"],
                 "severity": "CRITICAL",
                 "description": "Suspected unlicensed export of controlled encoder"},
                analyst_headers,  # identified_by := analyst-1
            ),
            201,
        )
        v_id = violation["id"]
        assert violation["status"] == "IDENTIFIED"

        under_review = validate_success(
            api.advance_violation(v_id, {"event": "START_REVIEW"}, manager_headers), 200,
        )
        assert under_review["status"] == "UNDER_REVIEW"

        substantiated = validate_success(
            api.advance_violation(v_id, {"event": "SUBSTANTIATE"}, manager2_headers), 200,
        )
        assert substantiated["status"] == "SUBSTANTIATED"
        assert substantiated["adjudicated_by_user_id"] == "manager-2"

        disclosed = validate_success(
            api.submit_violation_disclosure(v_id, director_headers), 200,
        )
        assert disclosed["status"] == "DISCLOSED"
        assert disclosed["disclosure_reference"] == "VSD-000001", (
            f"first disclosure must mint VSD-000001, got {disclosed['disclosure_reference']}"
        )

        closed = validate_success(
            api.advance_violation(v_id, {"event": "CLOSE"}, manager_headers), 200,
        )
        assert closed["status"] == "CLOSED"

        records = audit_records_for("Violation", v_id, headers=director_headers)
        event_types = {r["event_type"] for r in records}
        assert len(records) == 2, f"VSD path writes exactly 2 records, got {len(records)}"
        assert event_types == {"VSD_SUBMITTED", "VIOLATION_CLOSED"}

    def test_sod_violation_self_adjudication_rejected(self, api, manager_headers,
                                                      manager2_headers):
        """PRD §2.10: "a violation's `identified_by_user_id` cannot equal the `X-User-ID` of the user who substantiates, dismisses, or closes it. Any breach is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

        Design: Corner/validations/sod_violation_self_adjudication_rejected
        """
        # PRD §2.9 applies the existence discipline to a violation's polymorphic
        # source_id, so the ORDER-typed source must name a real order.
        product, _ = create_classified_product(sku="P-091", name="Gasket",
                                               controlled_content_pct=0, unit_value_cents=10,
                                               classification_code="EAR99")
        party = create_party(legal_name="Tallinn Freight OU", country_code="EST",
                             city="Tallinn")
        order = create_order(product["id"], party["id"], destination_country="EST",
                             end_use="CIVILIAN", quantity=1)
        violation = validate_success(
            api.create_violation(
                {"source_type": "ORDER",
                 "source_id": order["id"],
                 "severity": "MATERIAL", "description": "Suspected embargo breach"},
                manager_headers,  # identified_by := manager-1
            ),
            201,
        )
        v_id = violation["id"]
        # START_REVIEW carries no segregation check; a different manager runs it.
        validate_success(api.advance_violation(v_id, {"event": "START_REVIEW"},
                                               manager2_headers), 200)

        res = api.advance_violation(v_id, {"event": "SUBSTANTIATE"}, manager_headers)
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        after = validate_success(api.get_violation(v_id, manager_headers), 200)
        assert after["status"] == "UNDER_REVIEW", (
            f"rejected adjudication must leave the case UNDER_REVIEW, got {after['status']}"
        )


class TestAuditRecordShape:
    def test_audit_record_has_no_version_field(self, api, director_headers):
        """PRD §2.4: "The `AuditRecord` resource is the single exception: it carries only `id` and `created_at`. Both `updated_at` and `version` are absent from `AuditRecord`, because audit records are immutable once written and are removed only by the retention purge."
        PRD §2.11: "Every audit record is retained for five years: its `retain_until` timestamp is its own `created_at` plus 1825 days."

        Design: Corner/entities/audit_record_has_no_version_field
        """
        product = create_product(sku="P-003", name="Seal", controlled_content_pct=0,
                                 unit_value_cents=10)
        classification = create_draft_classification(product)
        submit_classification(classification["id"])
        review_classification(classification["id"], "APPROVE")

        rows, meta = list_audit_records(
            headers=director_headers,
            entity_type="Classification", entity_id=classification["id"],
        )
        assert meta["total_count"] == 1
        record = rows[0]
        assert_audit_record(record)  # asserts version/updated_at absence among the shape
        assert record["event_type"] == "CLASSIFICATION_ACTIVATED"
        assert record["entity_type"] == "Classification"
        assert record["entity_id"] == classification["id"]

        delta = parse_iso(record["retain_until"]) - parse_iso(record["created_at"])
        assert delta == timedelta(days=1825), (
            f"retain_until must be created_at + 1825 days, got delta {delta}"
        )


class TestAuditRetentionPurgeBoundary:
    def _setup_single_audit_record(self, director_headers):
        """One CLASSIFICATION_ACTIVATED record created at the default clock."""
        product = create_product(sku="P-930", name="Filter", controlled_content_pct=0,
                                 unit_value_cents=100)
        classification = create_draft_classification(product)
        submit_classification(classification["id"])
        review_classification(classification["id"], "APPROVE")
        rows, meta = list_audit_records(
            headers=director_headers,
            entity_type="Classification", entity_id=classification["id"],
        )
        assert meta["total_count"] == 1
        return classification["id"], rows[0]["retain_until"]

    def test_purge_at_exact_retain_until_retains_record(self, api, director_headers):
        """PRD §2.11: "A director-invoked purge capability deletes exactly the records whose `retain_until` is strictly earlier than the current logical clock and answers with a `purged_count`. A record whose `retain_until` equals the current clock time is **retained** — the comparison is strict."

        Design: Difficulty/boundary_precision_check/audit_purge_retain_until_equality_retained
        """
        c_id, retain_until = self._setup_single_audit_record(director_headers)

        # Clock pinned at exactly the record's retain_until: strict comparison retains it.
        set_clock(retain_until, headers=director_headers)
        result = purge_audit_records(headers=director_headers)
        assert result["purged_count"] == 0, (
            f"retain_until == clock must retain the record, purged {result['purged_count']}"
        )

        _, meta = list_audit_records(headers=director_headers,
                                     entity_type="Classification", entity_id=c_id)
        assert meta["total_count"] == 1

    def test_purge_one_second_past_retain_until_deletes(self, api, director_headers):
        """PRD §2.11: "A director-invoked purge capability deletes exactly the records whose `retain_until` is strictly earlier than the current logical clock and answers with a `purged_count`. A record whose `retain_until` equals the current clock time is **retained** — the comparison is strict."

        Design: Difficulty/boundary_precision_check/audit_purge_retain_until_equality_retained
        """
        c_id, retain_until = self._setup_single_audit_record(director_headers)

        one_second_past = to_iso_z(parse_iso(retain_until) + timedelta(seconds=1))
        set_clock(one_second_past, headers=director_headers)
        result = purge_audit_records(headers=director_headers)
        assert result["purged_count"] == 1, (
            f"one second past retain_until must purge exactly the record, "
            f"purged {result['purged_count']}"
        )

        _, meta = list_audit_records(headers=director_headers,
                                     entity_type="Classification", entity_id=c_id)
        assert meta["total_count"] == 0


class TestClockSweeps:
    def test_license_expiry_sweep_boundary(self, api, director_headers, analyst_headers):
        """PRD §2.5: "Advancing the clock triggers two automatic expiry sweeps. Every `License` in `APPROVED` status whose `valid_until` date falls strictly before the current date transitions to `EXPIRED`."

        Design: Corner/cross_cutting_layers/license_expiry_sweep_boundary
        """
        product, _ = create_classified_product(sku="P-072", name="Tape",
                                               controlled_content_pct=0, unit_value_cents=10,
                                               classification_code="EAR99")
        lic = create_approved_license(product["id"], approved_value_cents=1000,
                                      approved_quantity=10, valid_from="2026-07-01",
                                      valid_until="2026-12-31")

        set_clock("2026-12-31T00:00:00Z", headers=director_headers)
        at_equal = validate_success(api.get_license(lic["id"], analyst_headers), 200)
        assert at_equal["status"] == "APPROVED", (
            f"current date == valid_until is still inside the inclusive window, "
            f"got {at_equal['status']}"
        )

        set_clock("2027-01-01T00:00:00Z", headers=director_headers)
        after = validate_success(api.get_license(lic["id"], analyst_headers), 200)
        assert after["status"] == "EXPIRED", (
            f"current date strictly past valid_until must expire the license, "
            f"got {after['status']}"
        )

    def test_ops_cannot_purge_audit_records_forbidden(self, api, ops_headers):
        """PRD §4: "| POST | `/compliance/audit-records/purge` | Purge audit records whose retention deadline is strictly past | ComplianceDirector |"
        PRD §2.1: "A request whose role is authenticated but not permitted to call the target endpoint per the authorization matrix in §4 is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/ops_cannot_purge_audit_records_forbidden
        """
        res = api.purge_audit_records(ops_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_director_cannot_create_order_forbidden(self, api, director_headers):
        """PRD §4: "| POST | `/compliance/orders` | Create an export order (provisional determination computed) | TradeOpsSpecialist |"
        PRD §2.8: "2. **Authorization** — the role is permitted to call this endpoint (`ERR_FORBIDDEN`, 403). Applies to every endpoint."

        Design: Corner/rbac/director_cannot_create_order_forbidden
        """
        res = api.create_order(
            {"product_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
             "party_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
             "destination_country": "FRA", "end_use": "CIVILIAN", "quantity": 1},
            director_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
