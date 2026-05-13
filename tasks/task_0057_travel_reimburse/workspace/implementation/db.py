"""In-memory data store keyed by entity id."""

from __future__ import annotations


class DB:
    def __init__(self):
        self.employees: dict[str, dict] = {}
        self.expense_standards: dict[str, dict] = {}
        self.travel_applications: dict[str, dict] = {}
        self.itinerary_segments: dict[str, dict] = {}
        self.invoices: dict[str, dict] = {}
        self.reimbursement_forms: dict[str, dict] = {}
        self.reimbursement_items: dict[str, dict] = {}
        self.approval_records: dict[str, dict] = {}
        self.payments: dict[str, dict] = {}
        self.audit_logs: dict[str, dict] = {}

        # Test-harness state
        # eligible booking options keyed by (segment_type, employee_level) -> set[option_code]
        self.eligible_options: dict[tuple[str, str], set[str]] = {}
        # pinned tax verify outcomes: invoice_id -> verdict (VALID/INVALID)
        self.pinned_tax_verdict: dict[str, str] = {}
        # idempotency cache: invoice_id -> {key: (status_code, response_json)}
        self.idempotency_cache: dict[str, dict] = {}

    def reset(self):
        self.__init__()


# Single global store
STORE = DB()
