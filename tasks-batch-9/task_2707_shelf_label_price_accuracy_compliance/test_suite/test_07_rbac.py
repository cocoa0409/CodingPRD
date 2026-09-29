"""Role behaviour: exclusive operations, the identity header contract and role surfaces."""

from test_helpers import (
    NON_EXISTENT_UUID,
    factories,
    make_entity_backed_headers_without_user_id,
    make_headers,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_ROLE_CODE_MISMATCH,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.constants import (
    ROLE_CODE_LABEL_ASSOCIATE,
    ROLE_CODE_PRICE_AUDITOR,
    ROLE_CODE_STORE_MANAGER,
    ROLE_LABEL_ASSOCIATE,
    ROLE_STORE_MANAGER,
)


class TestExclusiveOperations:
    def test_each_owning_role_succeeds_where_a_differently_privileged_role_is_refused(
        self, api, build, admin_headers, officer_headers
    ):
        """Six exclusive calls, six refusals, and no hierarchical override anywhere.

        PRD 2.9: "**Priority 20 — authorization.** `X-User-Role` is one of the six
        declared roles and is listed among the target endpoint's authorized roles."
        PRD 4: "| POST | `/price-integrity/aisles/{id}/assign-associate` | Set or
        clear the aisle's accountable label associate. | `StoreManager` |"
        PRD 4: "| POST | `/price-integrity/scanner-audits/{id}/scan-lines` | Append
        one immutable scan observation comparing the shelf price to the register
        price. | `PriceAuditor` |"
        PRD 4: "| POST | `/price-integrity/regulatory-inspections` | Log a
        regulatory inspection of a store, referencing the scanner audit that is its
        evidence of record. | `ComplianceOfficer` |"
        PRD 4: "| POST |
        `/price-integrity/regulatory-inspections/{id}/issue-findings` |
        Cascade-create the inspector's findings on a SCHEDULED inspection and
        compute penalty_exposure_cents. | `ComplianceOfficer` |"
        PRD 4: "| POST | `/price-integrity/scanner-audits/{id}/reopen` | Reopen a
        CLOSED audit for additional scanning. | `ComplianceOfficer` |"
        PRD 4: "| POST | `/price-integrity/jurisdictions` | Register a pricing
        jurisdiction with its unit-price display rules, scanner error-rate
        threshold, refund policy, penalty rates and signage disclosur.... |
        `PricingAdmin` |"

        Design: Corner/RBAC/corner_every_exclusive_operation_is_reachable_only_by_its_owning_role
        """
        jurisdiction_id = build.jurisdiction(code="US-CA")
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        manager_id = build.certified(
            store_id,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM1",
            full_name="Sam Manager",
        )
        associate_id = build.certified(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lee Label",
        )
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        manager_headers = build.manager(manager_id)
        associate_headers = build.associate_headers(associate_id)
        auditor_headers = build.auditor(auditor_id)

        second_jurisdiction = validate_success(
            api.create_jurisdiction(
                factories.jurisdiction_payload(code="US-NY", name="New York"),
                admin_headers,
            ),
            201,
        )
        assert second_jurisdiction["id"]
        validate_error(
            api.create_jurisdiction(
                factories.jurisdiction_payload(code="US-NJ", name="New Jersey"),
                officer_headers,
            ),
            ERR_UNAUTHORIZED,
            403,
        )

        assigned = validate_success(
            api.assign_aisle_associate(
                aisle_id,
                factories.assign_associate_payload(associate_id),
                manager_headers,
            )
        )
        assert assigned["assigned_associate_id"] == associate_id
        validate_error(
            api.assign_aisle_associate(
                aisle_id, factories.assign_associate_payload(None), admin_headers
            ),
            ERR_UNAUTHORIZED,
            403,
        )

        audit = build.scanner_audit(
            store_id,
            aisle_id,
            auditor_id,
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T09:00:00Z",
            audit_type="REGULATORY",
            actor_headers=auditor_headers,
        )
        appended = build.scan_line(audit["id"], "00000000019001", 100, 100, auditor_headers)
        assert appended["id"]
        validate_error(
            api.create_scan_line(
                audit["id"],
                factories.scan_line_payload("00000000019002", 100, 100),
                associate_headers,
            ),
            ERR_UNAUTHORIZED,
            403,
        )

        closed = build.close_audit(audit["id"], auditor_headers, "GROSS_MISMATCH")
        assert closed["status"] == "CLOSED"

        inspection_payload = factories.inspection_payload(
            store_id,
            audit["id"],
            inspector_ref="INS-2026-16",
            inspection_date="2026-08-01T10:00:00Z",
        )
        validate_error(
            api.create_regulatory_inspection(inspection_payload, manager_headers),
            ERR_UNAUTHORIZED,
            403,
        )
        inspection = validate_success(
            api.create_regulatory_inspection(inspection_payload, officer_headers), 201
        )

        issued = validate_success(
            api.issue_inspection_findings(
                inspection["id"],
                factories.issue_findings_payload(
                    [factories.finding_input("SHELF_TAG_MISMATCH", "MINOR", 1, "A01")]
                ),
                officer_headers,
            )
        )
        assert issued["status"] == "FINDINGS_ISSUED"
        validate_error(
            api.issue_inspection_findings(
                inspection["id"],
                factories.issue_findings_payload(
                    [factories.finding_input("EXPIRED_SIGNAGE", "MINOR", 1, "A01")]
                ),
                manager_headers,
            ),
            ERR_UNAUTHORIZED,
            403,
        )

        validate_error(
            api.reopen_scanner_audit(
                audit["id"],
                factories.reopen_audit_payload("regulator disputed the sample"),
                auditor_headers,
            ),
            ERR_UNAUTHORIZED,
            403,
        )
        reopened = build.reopen_audit(
            audit["id"], "regulator disputed the sample", officer_headers
        )
        assert reopened["status"] == "REOPENED"


class TestEntityBackedIdentityHeader:
    def test_the_user_id_header_must_be_present_then_resolve_then_match_the_role(
        self, api, build, admin_headers
    ):
        """Presence is a 401 at priority 10; resolution and role agreement are a 403 at priority 22.

        PRD 2.9: "**Priority 10 — authentication.** `X-User-Role` is present and
        non-empty, and `X-User-ID` is present and non-empty whenever the claimed
        role is entity-backed (`StoreManager`, `LabelAssociate`, `PriceAuditor`)."
        PRD 2.9: "For entity-backed roles, `X-User-ID` resolves to an existing
        associate whose `role_code` matches the claimed role."
        PRD 3.4: "**Printing.** A label associate or store manager prints the tag,
        moving the print axis to `PRINTED` from either `NOT_PRINTED` or
        `REPRINT_REQUIRED`."
        PRD 3.4: "On success, `placed_by_associate_id` is stamped from `X-User-ID`
        and `placed_at` from the current instant, the store's label backlog is
        recomputed and then its posture recomputed, and when the underlying line
        sits in `FAILED` it moves `FAILED → LABELED`."

        Design: Corner/RBAC/corner_entity_backed_roles_need_a_resolving_matching_user_id_header
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", grace_period_hours=48)
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        manager_id = build.certified(
            store_id,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM1",
            full_name="Sam Manager",
        )
        associate_id = build.certified(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lee Label",
        )
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        aisle_id = build.aisle(
            store_id,
            aisle_code="A01",
            category_code="DAIRY",
            assigned_associate_id=associate_id,
        )
        built = build.distributed_file(
            jurisdiction_id,
            [store_id],
            [
                {
                    "item_upc": "00000000020001",
                    "new_retail_cents": 449,
                    "old_retail_cents": 499,
                    "net_content_qty": 1,
                    "net_content_uom": "GAL",
                    "item_description": "Milk 1 GAL",
                    "category_code": "DAIRY",
                }
            ],
            file_number="PCF-1",
        )
        task = validate_success(
            api.create_label_task(
                built["file_id"],
                factories.label_task_payload(
                    store_id,
                    built["line_ids"][0],
                    aisle_id,
                    associate_id,
                    "2026-08-02T08:00:00Z",
                    "2026-08-02T10:00:00Z",
                    built["version"],
                ),
                build.manager(manager_id),
            ),
            201,
        )

        validate_error(
            api.print_label_task(
                task["id"],
                make_entity_backed_headers_without_user_id(ROLE_LABEL_ASSOCIATE),
            ),
            ERR_UNAUTHENTICATED,
            401,
        )
        validate_error(
            api.print_label_task(
                task["id"], make_headers(ROLE_LABEL_ASSOCIATE, NON_EXISTENT_UUID)
            ),
            ERR_ROLE_CODE_MISMATCH,
            403,
        )
        validate_error(
            api.print_label_task(
                task["id"], make_headers(ROLE_LABEL_ASSOCIATE, auditor_id)
            ),
            ERR_ROLE_CODE_MISMATCH,
            403,
        )
        validate_error(
            api.assign_aisle_associate(
                aisle_id,
                factories.assign_associate_payload(associate_id),
                make_headers(ROLE_STORE_MANAGER, associate_id),
            ),
            ERR_ROLE_CODE_MISMATCH,
            403,
        )

        untouched = validate_success(api.get_label_task(task["id"], admin_headers))
        assert untouched["print_status"] == "NOT_PRINTED"
        assert untouched["placement_status"] == "UNPLACED"

        printed = build.print_task(task["id"], build.associate_headers(associate_id))
        assert printed["print_status"] == "PRINTED"

        placed = build.place_task(task["id"], 449, build.manager(manager_id))
        assert placed["placement_status"] == "PLACED"
        assert placed["placed_by_associate_id"] == manager_id


class TestSharedSurfaceRoles:
    def test_the_two_roles_without_exclusive_calls_can_do_exactly_their_shared_list(
        self, api, build, desk_headers
    ):
        """The refund desk and the floor associate are bounded by the role table, not by intent.

        PRD 2.9: "**Priority 20 — authorization.** `X-User-Role` is one of the six
        declared roles and is listed among the target endpoint's authorized roles."
        PRD 4: "| POST | `/price-integrity/label-tasks/{id}/print` | Print the shelf
        label. | `LabelAssociate`, `StoreManager` |"
        PRD 4: "| POST | `/price-integrity/label-tasks/{id}/verify-placement` |
        Second-person placement verification. | `PriceAuditor`, `StoreManager` |"
        PRD 4: "| POST | `/price-integrity/scanner-audits` | Schedule a scanner
        accuracy audit on one aisle over a half-open scan window. | `PriceAuditor`,
        `ComplianceOfficer` |"
        PRD 4: "| POST | `/price-integrity/refund-claims/{id}/settle` | Approve, pay
        or deny a refund claim. | `CustomerServiceDesk`, `StoreManager` |"
        PRD 3.8: "Under `REFUND_DIFFERENCE_ONLY` the gross amount is that variance
        alone."
        PRD 3.8: "A store manager approves a `PENDING` claim, moving it `PENDING →
        APPROVED`; the store's outstanding liability is unchanged by approval,
        because `PENDING` and `APPROVED` are both outstanding."
        PRD 3.8: "A customer service desk operator pays an `APPROVED` claim, moving
        it `APPROVED → PAID`, stamping `paid_at` with the current instant, and
        recomputing both the store's `refund_liability_outstanding_cents` — from
        which the amount now leaves — and its `refund_paid_total_cents`, into which
        the amount now enters."

        Design: Corner/RBAC/corner_the_two_roles_without_exclusive_operations_stay_inside_their_surface
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", grace_period_hours=48)
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        manager_id = build.certified(
            store_id,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM1",
            full_name="Sam Manager",
        )
        associate_id = build.certified(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lee Label",
        )
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        aisle_id = build.aisle(
            store_id,
            aisle_code="A01",
            category_code="DAIRY",
            assigned_associate_id=associate_id,
        )
        associate_headers = build.associate_headers(associate_id)
        auditor_headers = build.auditor(auditor_id)
        manager_headers = build.manager(manager_id)

        built = build.distributed_file(
            jurisdiction_id,
            [store_id],
            [
                {
                    "item_upc": "00000000021001",
                    "new_retail_cents": 449,
                    "old_retail_cents": 499,
                    "net_content_qty": 1,
                    "net_content_uom": "GAL",
                    "item_description": "Milk 1 GAL",
                    "category_code": "DAIRY",
                }
            ],
            file_number="PCF-1",
        )
        task = validate_success(
            api.create_label_task(
                built["file_id"],
                factories.label_task_payload(
                    store_id,
                    built["line_ids"][0],
                    aisle_id,
                    associate_id,
                    "2026-08-02T08:00:00Z",
                    "2026-08-02T10:00:00Z",
                    built["version"],
                ),
                manager_headers,
            ),
            201,
        )
        build.print_task(task["id"], associate_headers)
        placed = build.place_task(task["id"], 449, associate_headers)
        assert placed["placed_by_associate_id"] == associate_id

        evidence = build.audit_with_scan_lines(
            store_id,
            aisle_id,
            auditor_id,
            [
                {
                    "item_upc": "00000000021001",
                    "shelf_price_cents": 449,
                    "register_price_cents": 499,
                }
            ],
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T09:00:00Z",
        )
        assert evidence["scan_lines"][0]["classification"] == "OVERCHARGE"
        closed = build.close_audit(evidence["audit_id"], auditor_headers, "GROSS_MISMATCH")
        assert closed["outcome"] == "FAIL"

        claim = validate_success(
            api.create_refund_claim(
                factories.refund_claim_payload(
                    evidence["scan_line_ids"][0], "CUST-1", closed["version"]
                ),
                desk_headers,
            ),
            201,
        )
        assert claim["status"] == "PENDING"
        assert claim["claimed_amount_cents"] == 50

        validate_error(
            api.print_label_task(task["id"], desk_headers),
            ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.settle_refund_claim(
                claim["id"], factories.settle_claim_payload("APPROVED"), auditor_headers
            ),
            ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_scanner_audit(
                factories.scanner_audit_payload(
                    store_id,
                    aisle_id,
                    associate_id,
                    "2026-08-02T08:00:00Z",
                    "2026-08-02T09:00:00Z",
                ),
                associate_headers,
            ),
            ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.verify_label_task_placement(
                task["id"], factories.verify_payload("VERIFIED"), associate_headers
            ),
            ERR_UNAUTHORIZED,
            403,
        )

        approved = validate_success(
            api.settle_refund_claim(
                claim["id"], factories.settle_claim_payload("APPROVED"), manager_headers
            )
        )
        assert approved["status"] == "APPROVED"
        paid = validate_success(
            api.settle_refund_claim(
                claim["id"], factories.settle_claim_payload("PAID"), desk_headers
            )
        )
        assert paid["status"] == "PAID"

        readable = validate_success(api.get_label_task(task["id"], associate_headers))
        assert readable["placement_status"] == "PLACED"
        assert readable["version"] == placed["version"]
