"""Composite setup builders.

Every test starts against an empty database, so every precondition has to be
built from scratch through the declared endpoints.  ``Builder`` wraps that work:
each method performs the real calls, asserts they succeeded, and hands back the
ids and versions a test needs.  Higher tiers compose lower ones, so a test that
needs a closed failing audit asks for one instead of restating twenty calls.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import validate_success

from . import factories as f
from .api_client import PriceIntegrityApiClient
from .constants import (
    DEFAULT_CLOCK,
    ROLE_CODE_LABEL_ASSOCIATE,
    ROLE_CODE_PRICE_AUDITOR,
    ROLE_CODE_STORE_MANAGER,
)
from .test_users import (
    make_compliance_officer_headers,
    make_customer_service_desk_headers,
    make_label_associate_headers,
    make_price_auditor_headers,
    make_pricing_admin_headers,
    make_store_manager_headers,
)


class Builder:
    """Precondition builder bound to one API client."""

    def __init__(self, api: PriceIntegrityApiClient):
        self.api = api
        self.admin = make_pricing_admin_headers()
        self.officer = make_compliance_officer_headers()
        self.desk = make_customer_service_desk_headers()

    # ------------------------------------------------------------------
    # Identity helpers
    # ------------------------------------------------------------------
    def manager(self, associate_id: str) -> Dict[str, str]:
        return make_store_manager_headers(associate_id)

    def associate_headers(self, associate_id: str) -> Dict[str, str]:
        return make_label_associate_headers(associate_id)

    def auditor(self, associate_id: str) -> Dict[str, str]:
        return make_price_auditor_headers(associate_id)

    # ------------------------------------------------------------------
    # Tier 1: single records
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str = DEFAULT_CLOCK) -> None:
        validate_success(self.api.set_clock(current_utc, self.admin))

    def jurisdiction(self, **rulebook: Any) -> str:
        payload = f.jurisdiction_payload(**rulebook)
        data = validate_success(
            self.api.create_jurisdiction(payload, self.admin), 201
        )
        return data["id"]

    def jurisdiction_record(self, **rulebook: Any) -> Dict[str, Any]:
        payload = f.jurisdiction_payload(**rulebook)
        return validate_success(self.api.create_jurisdiction(payload, self.admin), 201)

    def store(self, jurisdiction_id: str, **kwargs: Any) -> str:
        payload = f.store_payload(jurisdiction_id, **kwargs)
        data = validate_success(self.api.create_store(payload, self.admin), 201)
        return data["id"]

    def aisle(self, store_id: str, **kwargs: Any) -> str:
        payload = f.aisle_payload(**kwargs)
        data = validate_success(self.api.create_aisle(store_id, payload, self.admin), 201)
        return data["id"]

    def associate(self, store_id: str, role_code: str, **kwargs: Any) -> str:
        payload = f.associate_payload(role_code, **kwargs)
        data = validate_success(
            self.api.create_associate(store_id, payload, self.admin), 201
        )
        return data["id"]

    def train(
        self, associate_id: str, module_code: str = "LABEL_101", score_pct: float = 95
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.record_training_completion(
                associate_id, f.training_payload(module_code, score_pct), self.admin
            )
        )

    def certified(
        self,
        store_id: str,
        role_code: str,
        score_pct: float = 95,
        module_code: str = "LABEL_101",
        **kwargs: Any,
    ) -> str:
        """Create an associate and certify them with one passing result."""
        associate_id = self.associate(store_id, role_code, **kwargs)
        self.train(associate_id, module_code, score_pct)
        return associate_id

    def certified_manager(self, store_id: str, score_pct: float = 95, **kwargs: Any) -> str:
        kwargs.setdefault("full_name", "Sam Manager")
        return self.certified(store_id, ROLE_CODE_STORE_MANAGER, score_pct, **kwargs)

    def certified_label_associate(
        self, store_id: str, score_pct: float = 95, **kwargs: Any
    ) -> str:
        kwargs.setdefault("full_name", "Lena Label")
        return self.certified(store_id, ROLE_CODE_LABEL_ASSOCIATE, score_pct, **kwargs)

    def certified_auditor(self, store_id: str, score_pct: float = 95, **kwargs: Any) -> str:
        kwargs.setdefault("full_name", "Pat Auditor")
        return self.certified(
            store_id, ROLE_CODE_PRICE_AUDITOR, score_pct, module_code="AUDIT_101", **kwargs
        )

    def assign_aisle(
        self, aisle_id: str, associate_id: Optional[str], manager_id: str
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.assign_aisle_associate(
                aisle_id, f.assign_associate_payload(associate_id), self.manager(manager_id)
            )
        )

    # ------------------------------------------------------------------
    # Tier 2: a store with its people
    # ------------------------------------------------------------------
    def store_with_staff(
        self,
        jurisdiction_id: str,
        aisle_code: str = "A01",
        category_code: str = "DAIRY",
        assign_label_associate: bool = True,
        store_number: Optional[str] = None,
        employee_prefix: str = "E",
    ) -> Dict[str, Any]:
        """A store, one aisle, and a certified manager / associate / auditor."""
        store_id = self.store(jurisdiction_id, store_number=store_number)
        manager_id = self.certified_manager(
            store_id, employee_number=f"{employee_prefix}-SM1"
        )
        label_id = self.certified_label_associate(
            store_id, employee_number=f"{employee_prefix}-LA1"
        )
        auditor_id = self.certified_auditor(
            store_id, employee_number=f"{employee_prefix}-PA1"
        )
        aisle_id = self.aisle(
            store_id, aisle_code=aisle_code, category_code=category_code
        )
        if assign_label_associate:
            self.assign_aisle(aisle_id, label_id, manager_id)
        return {
            "store_id": store_id,
            "aisle_id": aisle_id,
            "manager_id": manager_id,
            "label_associate_id": label_id,
            "auditor_id": auditor_id,
        }

    # ------------------------------------------------------------------
    # Tier 3: price change files and their lines
    # ------------------------------------------------------------------
    def price_change_file(
        self,
        jurisdiction_id: str,
        scope_store_ids: List[str],
        effective_date: str = "2026-08-03T00:00:00Z",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        payload = f.price_change_file_payload(
            jurisdiction_id, scope_store_ids, effective_date, **kwargs
        )
        return validate_success(
            self.api.create_price_change_file(payload, self.admin), 201
        )

    def add_line(
        self,
        file_id: str,
        item_upc: str,
        new_retail_cents: int,
        old_retail_cents: int,
        net_content_qty: float,
        net_content_uom: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        payload = f.price_change_line_payload(
            item_upc,
            new_retail_cents,
            old_retail_cents,
            net_content_qty,
            net_content_uom,
            **kwargs
        )
        return validate_success(
            self.api.create_price_change_line(file_id, payload, self.admin), 201
        )

    def distribute(self, file_id: str) -> Dict[str, Any]:
        return validate_success(
            self.api.distribute_price_change_file(file_id, self.admin)
        )

    def distributed_file(
        self,
        jurisdiction_id: str,
        scope_store_ids: List[str],
        lines: List[Dict[str, Any]],
        effective_date: str = "2026-08-03T00:00:00Z",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """A file carrying ``lines``, distributed, with its post-hop version."""
        record = self.price_change_file(
            jurisdiction_id, scope_store_ids, effective_date, **kwargs
        )
        line_records = [self.add_line(record["id"], **line) for line in lines]
        distributed = self.distribute(record["id"])
        return {
            "file_id": record["id"],
            "file": distributed,
            "draft_version": record["version"],
            "version": distributed["version"],
            "line_ids": [line["id"] for line in line_records],
            "lines": line_records,
        }

    def file_version(self, file_id: str) -> int:
        data = validate_success(self.api.get_price_change_file(file_id, self.admin))
        return data["version"]

    # ------------------------------------------------------------------
    # Tier 3: label tasks and the print / place / verify chain
    # ------------------------------------------------------------------
    def label_task(
        self,
        file_id: str,
        store_id: str,
        price_change_line_id: str,
        aisle_id: str,
        assigned_associate_id: str,
        scheduled_start_at: str = "2026-08-03T08:00:00Z",
        scheduled_end_at: str = "2026-08-03T10:00:00Z",
        expected_price_change_file_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        version = (
            expected_price_change_file_version
            if expected_price_change_file_version is not None
            else self.file_version(file_id)
        )
        payload = f.label_task_payload(
            store_id,
            price_change_line_id,
            aisle_id,
            assigned_associate_id,
            scheduled_start_at,
            scheduled_end_at,
            version,
        )
        return validate_success(
            self.api.create_label_task(file_id, payload, self.admin), 201
        )

    def print_task(self, task_id: str, actor_headers: Dict[str, str]) -> Dict[str, Any]:
        return validate_success(self.api.print_label_task(task_id, actor_headers))

    def place_task(
        self, task_id: str, observed_shelf_price_cents: int, actor_headers: Dict[str, str]
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.place_label_task(
                task_id, f.place_payload(observed_shelf_price_cents), actor_headers
            )
        )

    def verify_task(
        self,
        task_id: str,
        actor_headers: Dict[str, str],
        outcome: str = "VERIFIED",
        rejection_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.verify_label_task_placement(
                task_id, f.verify_payload(outcome, rejection_reason), actor_headers
            )
        )

    def placed_task(
        self,
        file_id: str,
        store_id: str,
        line_id: str,
        aisle_id: str,
        placer_id: str,
        observed_shelf_price_cents: int,
        placer_headers: Optional[Dict[str, str]] = None,
        **task_kwargs: Any,
    ) -> Dict[str, Any]:
        """A task printed and placed by ``placer_id``."""
        headers = placer_headers or self.associate_headers(placer_id)
        task = self.label_task(
            file_id, store_id, line_id, aisle_id, placer_id, **task_kwargs
        )
        self.print_task(task["id"], headers)
        placed = self.place_task(task["id"], observed_shelf_price_cents, headers)
        return {"task_id": task["id"], "task": placed}

    # ------------------------------------------------------------------
    # Tier 4: scanner audits, evidence and the close verdict
    # ------------------------------------------------------------------
    def scanner_audit(
        self,
        store_id: str,
        aisle_id: str,
        auditor_associate_id: str,
        scan_window_start: str = "2026-08-01T08:00:00Z",
        scan_window_end: str = "2026-08-01T10:00:00Z",
        audit_type: str = "ROUTINE",
        actor_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        payload = f.scanner_audit_payload(
            store_id,
            aisle_id,
            auditor_associate_id,
            scan_window_start,
            scan_window_end,
            audit_type,
        )
        headers = actor_headers or self.auditor(auditor_associate_id)
        return validate_success(self.api.create_scanner_audit(payload, headers), 201)

    def scan_line(
        self,
        audit_id: str,
        item_upc: str,
        shelf_price_cents: int,
        register_price_cents: int,
        actor_headers: Dict[str, str],
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.create_scan_line(
                audit_id,
                f.scan_line_payload(item_upc, shelf_price_cents, register_price_cents),
                actor_headers,
            ),
            201,
        )

    def close_audit(
        self,
        audit_id: str,
        actor_headers: Dict[str, str],
        rate_variant: Optional[str] = None,
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.close_scanner_audit(
                audit_id, actor_headers, f.close_audit_payload(rate_variant)
            )
        )

    def reopen_audit(
        self,
        audit_id: str,
        reason: str = "Register export was incomplete",
        actor_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.reopen_scanner_audit(
                audit_id, f.reopen_audit_payload(reason), actor_headers or self.officer
            )
        )

    def audit_with_scan_lines(
        self,
        store_id: str,
        aisle_id: str,
        auditor_associate_id: str,
        observations: List[Dict[str, Any]],
        audit_type: str = "ROUTINE",
        **audit_kwargs: Any,
    ) -> Dict[str, Any]:
        """An audit in SCANNING carrying every observation in ``observations``."""
        headers = self.auditor(auditor_associate_id)
        audit = self.scanner_audit(
            store_id,
            aisle_id,
            auditor_associate_id,
            audit_type=audit_type,
            actor_headers=headers,
            **audit_kwargs
        )
        line_records = [
            self.scan_line(
                audit["id"],
                obs["item_upc"],
                obs["shelf_price_cents"],
                obs["register_price_cents"],
                headers,
            )
            for obs in observations
        ]
        return {
            "audit_id": audit["id"],
            "audit": audit,
            "scan_line_ids": [line["id"] for line in line_records],
            "scan_lines": line_records,
        }

    def closed_audit(
        self,
        store_id: str,
        aisle_id: str,
        auditor_associate_id: str,
        observations: List[Dict[str, Any]],
        rate_variant: Optional[str] = None,
        audit_type: str = "ROUTINE",
        **audit_kwargs: Any,
    ) -> Dict[str, Any]:
        """An audit closed on ``observations``, with the closed version to pin."""
        built = self.audit_with_scan_lines(
            store_id,
            aisle_id,
            auditor_associate_id,
            observations,
            audit_type=audit_type,
            **audit_kwargs
        )
        closed = self.close_audit(
            built["audit_id"], self.auditor(auditor_associate_id), rate_variant
        )
        built["audit"] = closed
        built["version"] = closed["version"]
        return built

    def audit_version(self, audit_id: str) -> int:
        data = validate_success(self.api.get_scanner_audit(audit_id, self.officer))
        return data["version"]

    # ------------------------------------------------------------------
    # Tier 4: signage
    # ------------------------------------------------------------------
    def promo_signage(
        self,
        store_id: str,
        aisle_id: str,
        disclosure_codes: List[str],
        actor_headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        payload = f.promo_signage_payload(
            store_id, aisle_id, disclosure_codes, **kwargs
        )
        return validate_success(
            self.api.create_promo_signage(payload, actor_headers or self.admin), 201
        )

    def post_signage(
        self,
        signage_id: str,
        actor_headers: Dict[str, str],
        override_acknowledged: Optional[bool] = None,
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.post_promo_signage(
                signage_id, actor_headers, f.post_signage_payload(override_acknowledged)
            )
        )

    def remove_signage(self, signage_id: str, actor_headers: Dict[str, str]) -> Dict[str, Any]:
        return validate_success(self.api.remove_promo_signage(signage_id, actor_headers))

    def sweep(self, store_id: str, actor_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        return validate_success(
            self.api.run_signage_sweep(store_id, actor_headers or self.officer)
        )

    def posted_signage(
        self,
        store_id: str,
        aisle_id: str,
        disclosure_codes: List[str],
        manager_id: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """A sign drafted and posted to the floor."""
        sign = self.promo_signage(store_id, aisle_id, disclosure_codes, **kwargs)
        posted = self.post_signage(sign["id"], self.manager(manager_id))
        return {"signage_id": sign["id"], "signage": posted, "draft": sign}

    # ------------------------------------------------------------------
    # Tier 4: accountability actions
    # ------------------------------------------------------------------
    def issue_action(
        self,
        associate_id: str,
        action_type: str,
        trigger_code: str = "VERIFICATION_REJECTED",
        source_ref: Optional[str] = None,
        actor_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.create_accountability_action(
                associate_id,
                f.accountability_action_payload(action_type, trigger_code, source_ref),
                actor_headers or self.officer,
            ),
            201,
        )

    def void_action(
        self,
        action_id: str,
        void_reason: str = "issued against the wrong associate",
        actor_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.transition_accountability_action(
                action_id,
                f.action_transition_payload("VOIDED", void_reason),
                actor_headers or self.officer,
            )
        )

    # ------------------------------------------------------------------
    # Tier 5: inspections, findings and settlement
    # ------------------------------------------------------------------
    def inspection(
        self, store_id: str, scanner_audit_id: str, **kwargs: Any
    ) -> Dict[str, Any]:
        payload = f.inspection_payload(store_id, scanner_audit_id, **kwargs)
        return validate_success(
            self.api.create_regulatory_inspection(payload, self.officer), 201
        )

    def issue_findings(
        self, inspection_id: str, findings: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.issue_inspection_findings(
                inspection_id, f.issue_findings_payload(findings), self.officer
            )
        )

    def finding_ids(self, inspection_id: str) -> List[str]:
        data = validate_success(
            self.api.list_inspection_findings(inspection_id, self.officer)
        )
        return [record["id"] for record in data]

    def inspection_with_findings(
        self,
        store_id: str,
        scanner_audit_id: str,
        findings: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """An inspection advanced to FINDINGS_ISSUED, with its finding ids."""
        record = self.inspection(store_id, scanner_audit_id, **kwargs)
        issued = self.issue_findings(record["id"], findings)
        return {
            "inspection_id": record["id"],
            "inspection": issued,
            "scheduled_version": record["version"],
            "version": issued["version"],
            "finding_ids": self.finding_ids(record["id"]),
        }

    def transition_finding(
        self,
        finding_id: str,
        target_status: str,
        actor_headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.transition_inspection_finding(
                finding_id,
                f.finding_transition_payload(target_status, **kwargs),
                actor_headers or self.officer,
            )
        )

    def remediate_finding(
        self,
        finding_id: str,
        action_code: str,
        evidence_ref: str,
        manager_id: str,
    ) -> Dict[str, Any]:
        """Plan then complete remediation on one finding."""
        headers = self.manager(manager_id)
        self.transition_finding(
            finding_id,
            "REMEDIATION_PLANNED",
            headers,
            remediation_action_code=action_code,
        )
        return self.transition_finding(
            finding_id, "REMEDIATED", headers, remediation_evidence_ref=evidence_ref
        )

    def submit_response(
        self,
        inspection_id: str,
        remediation_summary: str,
        expected_version: int,
        manager_id: str,
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.submit_inspection_response(
                inspection_id,
                f.inspection_response_payload(remediation_summary, expected_version),
                self.manager(manager_id),
            )
        )

    def adjudicate(
        self, inspection_id: str, decision: str, **kwargs: Any
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.adjudicate_inspection(
                inspection_id, f.adjudicate_payload(decision, **kwargs), self.officer
            )
        )

    def inspection_version(self, inspection_id: str) -> int:
        data = validate_success(
            self.api.get_regulatory_inspection(inspection_id, self.officer)
        )
        return data["version"]

    # ------------------------------------------------------------------
    # Tier 5: refund claims
    # ------------------------------------------------------------------
    def refund_claim(
        self,
        scan_line_id: str,
        customer_ref: str,
        expected_scanner_audit_version: int,
        actor_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.create_refund_claim(
                f.refund_claim_payload(
                    scan_line_id, customer_ref, expected_scanner_audit_version
                ),
                actor_headers or self.desk,
            ),
            201,
        )

    def settle_claim(
        self,
        claim_id: str,
        target_status: str,
        actor_headers: Dict[str, str],
        denial_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.settle_refund_claim(
                claim_id,
                f.settle_claim_payload(target_status, denial_reason),
                actor_headers,
            )
        )

    def approved_claim(
        self,
        scan_line_id: str,
        customer_ref: str,
        audit_version: int,
        manager_id: str,
    ) -> Dict[str, Any]:
        claim = self.refund_claim(scan_line_id, customer_ref, audit_version)
        approved = self.settle_claim(claim["id"], "APPROVED", self.manager(manager_id))
        return {"claim_id": claim["id"], "claim": approved, "filed": claim}

    def paid_claim(
        self,
        scan_line_id: str,
        customer_ref: str,
        audit_version: int,
        manager_id: str,
    ) -> Dict[str, Any]:
        built = self.approved_claim(scan_line_id, customer_ref, audit_version, manager_id)
        paid = self.settle_claim(built["claim_id"], "PAID", self.desk)
        built["claim"] = paid
        return built

    # ------------------------------------------------------------------
    # Tier 5: exception reports
    # ------------------------------------------------------------------
    def exception_report(
        self,
        store_id: str,
        period_start_at: str,
        period_end_at: str,
        actor_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.create_exception_report(
                f.exception_report_payload(store_id, period_start_at, period_end_at),
                actor_headers or self.officer,
            ),
            201,
        )

    def assign_root_cause(
        self,
        report_id: str,
        root_cause_code: str,
        owner_associate_id: str,
        actor_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.assign_exception_report_root_cause(
                report_id,
                f.root_cause_payload(root_cause_code, owner_associate_id),
                actor_headers or self.officer,
            )
        )

    def close_report(
        self,
        report_id: str,
        closure_note: str = "Retraining delivered",
        actor_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return validate_success(
            self.api.close_exception_report(
                report_id, f.close_report_payload(closure_note), actor_headers or self.officer
            )
        )

    # ------------------------------------------------------------------
    # Read-back shortcuts
    # ------------------------------------------------------------------
    def read_store(self, store_id: str) -> Dict[str, Any]:
        return validate_success(self.api.get_store(store_id, self.admin))

    def read_summary(self, store_id: str) -> Dict[str, Any]:
        return validate_success(
            self.api.get_store_compliance_summary(store_id, self.admin)
        )

    def read_aisle(self, aisle_id: str) -> Dict[str, Any]:
        return validate_success(self.api.get_aisle(aisle_id, self.admin))

    def read_associate(self, associate_id: str) -> Dict[str, Any]:
        return validate_success(self.api.get_associate(associate_id, self.admin))

    def read_file(self, file_id: str) -> Dict[str, Any]:
        return validate_success(self.api.get_price_change_file(file_id, self.admin))

    def read_line(self, line_id: str) -> Dict[str, Any]:
        return validate_success(self.api.get_price_change_line(line_id, self.admin))

    def read_task(self, task_id: str) -> Dict[str, Any]:
        return validate_success(self.api.get_label_task(task_id, self.admin))

    def read_audit(self, audit_id: str) -> Dict[str, Any]:
        return validate_success(self.api.get_scanner_audit(audit_id, self.officer))

    def read_scan_line(self, scan_line_id: str) -> Dict[str, Any]:
        return validate_success(self.api.get_scan_line(scan_line_id, self.officer))

    def read_signage(self, signage_id: str) -> Dict[str, Any]:
        return validate_success(self.api.get_promo_signage(signage_id, self.admin))

    def read_inspection(self, inspection_id: str) -> Dict[str, Any]:
        return validate_success(
            self.api.get_regulatory_inspection(inspection_id, self.officer)
        )

    def read_finding(self, finding_id: str) -> Dict[str, Any]:
        return validate_success(self.api.get_inspection_finding(finding_id, self.officer))

    def read_claim(self, claim_id: str) -> Dict[str, Any]:
        return validate_success(self.api.get_refund_claim(claim_id, self.desk))

    def read_report(self, report_id: str) -> Dict[str, Any]:
        return validate_success(self.api.get_exception_report(report_id, self.officer))

    def read_action(self, action_id: str) -> Dict[str, Any]:
        return validate_success(
            self.api.get_accountability_action(action_id, self.officer)
        )

    def read_jurisdiction(self, jurisdiction_id: str) -> Dict[str, Any]:
        return validate_success(self.api.get_jurisdiction(jurisdiction_id, self.admin))

    def amend_jurisdiction(self, jurisdiction_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return validate_success(
            self.api.amend_jurisdiction(jurisdiction_id, payload, self.admin)
        )
