# Software License Audit Defense API — Product Requirements Document

## 1. Introduction

Enterprise software vendors increasingly exercise their contractual right to audit customers, and the financial exposure of a poorly defended audit routinely reaches seven figures once back-support penalties are layered on top of list-price true-ups. Defense teams face a recurring set of pain points: entitlement records scattered across procurement history, deployment counts trapped in discovery tooling, no shared picture of the gap before the vendor's own numbers arrive, and uncontrolled evidence handover that can waive privilege or concede scope by accident.

This document specifies a Software Asset Management API that supports the full audit-defense lifecycle as one coherent system of record. It covers entitlement consolidation and purchase history, deployment discovery and measurement per vendor metric, self-audit gap analysis ahead of vendor engagement, audit notice response and scope negotiation, controlled data submission with privilege review, settlement and true-up negotiation with future-licensing terms, remediation of over-deployment, and continuous license position monitoring afterward. Six segregated roles — customer-side asset management, IT, legal, and procurement, plus the platform administrator and the external vendor auditor — share one consistent, versioned view of every figure the negotiation depends on.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID` identifying the acting operator and `X-User-Role` naming their capacity. The system recognizes six roles: `SAMPlatformAdmin` (platform administrator; owns the vendor and product catalog and the logical clock), `SAMManager` (software asset manager; consolidates entitlements, confirms deployments, runs gap analysis, prepares evidence submissions, executes remediation, and suppresses alerts), `ITAnalyst` (IT operations analyst feeding deployment discovery measurements), `LegalCounsel` (legal counsel; owns the audit notice response, scope decisions, privilege review and release, and acceptance of vendor offers), `ProcurementLead` (procurement lead; tenders and withdraws customer-side settlement offers and records purchases), and `VendorAuditor` (the external auditor acting for the vendor; proposes scope, records findings, tenders and withdraws vendor offers, accepts customer offers, requests supplemental evidence, and withdraws audits). A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is not permitted for the endpoint it targets is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

For every one of these six roles — `SAMPlatformAdmin`, `SAMManager`, `ITAnalyst`, `LegalCounsel`, `ProcurementLead`, and `VendorAuditor` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `prepared_by_user_id` on a DataSubmission or as `tendered_by_user_id` on a SettlementOffer, where segregation-of-duties rules later compare it), but it never compares the value to any entity's `id`.

Read access is role-scoped. The five internal roles may read the internal resources: the product catalog, entitlement and deployment histories, license positions, remediation actions, and monitoring alerts, in addition to audit cases, scope items, offers, and submissions. The `VendorAuditor` is an external party with a narrower window: it may read audit cases, scope items, and settlement offers, and it sees only `RELEASED` rows when listing a case's data submissions through a server-side filter; every other read attempted by the auditor is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

---

### 2.3. Pagination

List endpoints paginate through two query parameters. `limit` caps the number of items returned: when not provided it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. `offset` skips a number of items from the beginning of the result set and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

List responses include the following pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The system never consults wall-clock time. A logical clock governs every temporal rule — entitlement activation and expiry, audit response deadlines, measurement recency, and alert evaluation — and its value at server startup is exactly 2026-08-01T00:00:00Z; it never falls back to the host's wall clock. A `SAMPlatformAdmin`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Setting the clock triggers the entitlement status sweep (every `SCHEDULED` record whose `effective_from` has been reached becomes `ACTIVE`, and every `ACTIVE` record whose `effective_to` has been reached or passed becomes `EXPIRED`), the `ENTITLEMENT_EXPIRING` alert sweep, position recomputation for affected products, and recomputation of the audit case rollups that depend on them.

### 2.5. Common Resource Properties

Every resource in the system — vendors, products, entitlement records, deployment records, license positions, audit cases, audit scope items, data submissions, settlement offers, remediation actions, and monitoring alerts — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed counter that increments with every modification of the resource, including server-initiated recomputation of derived fields; it underpins the optimistic concurrency rule of §2.9.

Request payloads that carry unknown fields — including client-supplied `id`, `version`, or `created_at` — are not rejected on that account; the unknown fields are simply ignored.

### 2.6. License Metrics, Environments, and Coverage Classes

Three license metrics exist — `PER_INSTALL`, `PER_USER`, and `PER_CORE` — and each is interpreted per product: a vendor declares a `default_license_metric` for its catalog, while each product's own `license_metric` governs how its measured quantities are read (installations, named users, or processor cores). Deployment measurements are tagged with an `environment` of `PRODUCTION` or `NON_PRODUCTION`, and whether non-production usage consumes entitlement is a per-product decision carried by the product's `counts_non_production` flag. Entitlements are granted for a `coverage_class` of `PRODUCTION`, `NON_PRODUCTION`, or `DISASTER_RECOVERY`, and every measurement arrives with a `measurement_method` of `SCAN` (automated discovery) or `MANUAL_DECLARATION` (hand-reported).

### 2.7. Monetary Precision and Rounding Discipline

All monetary amounts in the system — list prices, exposure figures, vendor findings, settlement offers, and settled amounts — are integer cents, and every derived cent value is rounded half up. Two rounding disciplines are load-bearing. First, when a per-unit vendor-list factor is derived from `unit_list_price_cents` and `support_rate_pct`, the factor itself is rounded half up to whole cents before it is multiplied by any quantity. Second, vendor findings are priced per line: each line's cent amount is rounded half up and stored, and case-level totals sum the stored per-line values exactly without re-rounding at the total. Summing unrounded lines and rounding once at the end is a different, rejected algorithm that yields different totals whenever per-line fractions accumulate below half a cent. Ratio comparisons in the severity ladder of §3.4 use exact decimal arithmetic rather than binary floating point, so boundary values compare exactly: a ratio of exactly 1.05 does not exceed the 1.05 grace boundary, while a ratio of exactly 1.25 does meet the 1.25 critical boundary.

### 2.8. Derived Positions and Cascading Recomputation

A product's license position is a fully derived projection: every quantity, gap, severity, and exposure field on it is recomputed from source records whenever entitlements, deployments, product pricing, or remediations change, and it can additionally be refreshed on demand by a `SAMManager`. Recomputation cascades outward. Whenever a product's position is recomputed, the system also recomputes the rollups of every audit case that is not `CLOSED_SETTLED`, `CLOSED_NO_ACTION`, or `WITHDRAWN` and that holds a `CONFIRMED` scope item for that product, and it upserts the product's monitoring alerts per §3.9. Certain cascades additionally advance the parent case itself: confirming a scope item, excluding a confirmed scope item, releasing a data submission, recording a vendor finding, tendering an offer, accepting an offer, reopening evidence, withdrawing a case, and completing a remediation each increment the affected AuditCase `version` by exactly one and refresh its `updated_at`. The workflows of §3 state these per-operation effects explicitly; §2.5's general rule — every mutation bumps `version` and `updated_at` on the mutated resource — applies throughout.

### 2.9. Optimistic Concurrency Control on Settlement Offers

Tendering a settlement offer is the system's single write operation guarded by optimistic concurrency control. The request must carry `expected_audit_case_version`, a non-optional field holding the AuditCase `version` the client last observed. If the supplied value does not equal the case's current `version` — because, for example, another offer has been tendered since the client last read the case (an event that legitimately supersedes the previously pending offer and advances the case version), or a scope item was confirmed, or evidence was released — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a negotiator from pricing an offer against a worst-case cap or pending-offer state it has not observed. Endpoints not named here do not accept a version field and perform no such check.

### 2.10. Validation Order and Nested Resource Retrieval

Every request is validated against a fixed, prioritized chain; the first failing check produces the error response and later checks are not evaluated. The order is:

1. Authentication context — the `X-User-ID` and `X-User-Role` headers are present and the role is recognized (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Authorization — the role is permitted for the endpoint, including the offered-by/role party match on settlement offers and the VendorAuditor read restrictions (`ERR_INSUFFICIENT_PERMISSIONS`).
3. Request shape — required fields are present, types match, enum values are valid, `quantity` and `amount_cents` are positive, `effective_from` is earlier than `effective_to` when both are present, required arrays such as `covered_scope_item_ids` and `target_deployment_ids` are non-empty where required, an entitlement `source` on manual creation is limited to `MANUAL_IMPORT` or `CONTRACT_EXTRACT`, and `future_license_discount_pct` lies within its allowed range; violations yield `ERR_INVALID_REQUEST`.
4. Existence — path identifiers are validated left to right, then body-referenced identifiers such as `vendor_id`, `product_id`, `audit_case_id`, `covered_scope_item_ids`, and `target_deployment_ids`, each yielding the resource-specific not-found error from §5.
5. Optimistic concurrency — on the one endpoint that takes a version field, a stale `expected_audit_case_version` yields `ERR_STALE_VERSION`.
6. State legality — first the target resource's own status is checked against the requested transition (`ERR_ENTITLEMENT_INVALID_STATE`, `ERR_DEPLOYMENT_INVALID_STATE`, `ERR_SCOPE_ITEM_INVALID_STATE`, `ERR_SUBMISSION_INVALID_STATE`, `ERR_OFFER_INVALID_STATE`, `ERR_REMEDIATION_INVALID_STATE`, or `ERR_ALERT_INVALID_STATE`), then the cross-entity state gates in a pinned order: the parent audit case's status for scope-item, submission, and offer operations (`ERR_AUDIT_CASE_INVALID_STATE`), followed by the advance-specific gates `ERR_SCOPE_ITEMS_PENDING`, `ERR_EMPTY_AUDIT_SCOPE`, `ERR_NO_RELEASED_SUBMISSION`, `ERR_FINDINGS_INCOMPLETE`, and `ERR_EXPOSURE_NOT_ZERO`.
7. Business-temporal rules — the response deadline on advancing to scope negotiation and on scope confirmation (`ERR_RESPONSE_DEADLINE_PASSED`), and the measurement-date rule on deployment confirmation (`ERR_MEASUREMENT_DATE_IN_FUTURE`).
8. Business constraints — vendor code uniqueness (`ERR_DUPLICATE_VENDOR_CODE`), duplicate scope items (`ERR_DUPLICATE_SCOPE_ITEM`), concurrent audit occupation (`ERR_PRODUCT_UNDER_CONCURRENT_AUDIT`), and entitlement window overlap (`ERR_ENTITLEMENT_WINDOW_OVERLAP`).
9. Safety and privilege — segregation of duties (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`) and the privileged-content waiver (`ERR_PRIVILEGED_CONTENT_REQUIRES_WAIVER`).
10. Referential integrity of package and remediation contents — `ERR_SUBMISSION_SCOPE_MISMATCH`, `ERR_REMEDIATION_TARGET_INVALID`, and `ERR_EMPTY_SUBMISSION_PACKAGE`.
11. Fiscal caps — the customer offer cap (`ERR_OFFER_EXCEEDS_WORST_CASE_CAP`) and the remediation gap cap (`ERR_REMEDIATION_EXCEEDS_GAP`).

For endpoints whose paths nest one resource beneath another, identifiers are resolved strictly left to right: the parent is located before any child identifier is considered, and the request is rejected with the 404 error corresponding to the first identifier that does not exist — `ERR_VENDOR_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_ENTITLEMENT_NOT_FOUND`, `ERR_DEPLOYMENT_NOT_FOUND`, `ERR_LICENSE_POSITION_NOT_FOUND`, `ERR_AUDIT_CASE_NOT_FOUND`, `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_SUBMISSION_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_REMEDIATION_NOT_FOUND`, or `ERR_ALERT_NOT_FOUND` as applicable.

## 3. Business Logic & Workflows

### 3.1. Onboarding the Vendor and Product Catalog

Before any gap analysis can begin, a `SAMPlatformAdmin` registers each software licensor as a Vendor with its legal `name`, a short `vendor_code`, and a `default_license_metric` of `PER_INSTALL`, `PER_USER`, or `PER_CORE`. Vendor codes are unique across the entire catalog: registering a vendor whose `vendor_code` is already taken is rejected with `ERR_DUPLICATE_VENDOR_CODE`. Each vendor also carries `notice_response_deadline_days`, the number of days the customer has to respond to an audit notice; it defaults to 30 when omitted and must be a positive integer. This value later drives the response deadline of every audit case opened against the vendor (§3.5).

Products are registered under their owning vendor by passing the vendor's `vendor_id` together with the product `name`, its `license_metric` (again one of `PER_INSTALL`, `PER_USER`, or `PER_CORE`), the `unit_list_price_cents` list price per licensed unit as a positive integer number of cents, and `support_rate_pct`, the annual support and maintenance rate expressed as a decimal fraction of list price between 0 and 1 inclusive (for example, 0.22). Two flags tune downstream behavior: `mission_critical` (defaulting to false) shortens the severity escalation ladder described in §3.4, and `counts_non_production` (defaulting to false) decides whether non-production deployments consume entitlement. Registering a product automatically creates its LicensePosition with all quantities zero, `gap_severity` of `COMPLIANT`, and `position_basis` of `SELF_AUDIT`; exactly one position exists per product for the product's entire lifetime.

Catalog maintenance continues after onboarding. A `SAMPlatformAdmin` may update a product's `name`, `unit_list_price_cents`, `support_rate_pct`, `mission_critical`, or `counts_non_production`; because exposures are priced from these fields, such an update recomputes the product's position, the rollups of every audit case scoping the product, and the product's monitoring alerts, following the cascade rules of §2.8. The catalog can be browsed as a list (optionally filtered by `vendor_id`) or fetched individually; unknown vendor or product identifiers surface as `ERR_VENDOR_NOT_FOUND` or `ERR_PRODUCT_NOT_FOUND`.

### 3.2. Consolidating Entitlements and Purchase History

The entitlement ledger is built record by record. A `SAMManager` or `ProcurementLead` consolidates each purchase by providing the `product_id` the purchase entitles, the procurement `purchase_order_number` as contract reference, the licensed `quantity` as a positive integer, the `coverage_class` the purchase covers (`PRODUCTION`, `NON_PRODUCTION`, or `DISASTER_RECOVERY`), the coverage window `effective_from` and optionally `effective_to`, and the record's `source` — `MANUAL_IMPORT` or `CONTRACT_EXTRACT`. The third source value, `AUTO_TRUE_UP`, is reserved for system-created remediation records (§3.8) and is rejected on manual creation with `ERR_INVALID_REQUEST`. When `effective_to` is present it must be later than `effective_from`; when absent, the record is perpetual.

Coverage windows are closed intervals that include both their boundary dates, so two records for the same product and `coverage_class` whose windows merely touch at a boundary date are already considered overlapping. Creation is rejected with `ERR_ENTITLEMENT_WINDOW_OVERLAP` when the new window overlaps an existing `SCHEDULED` or `ACTIVE` record of the same product and coverage class; `AUTO_TRUE_UP` records are exempt from this check, and records already `EXPIRED` or `VOID` no longer participate in it.

A record's initial `status` is decided against the logical clock at creation: when `effective_from` lies in the future the record begins `SCHEDULED`, and otherwise it begins `ACTIVE` and immediately contributes to the product's entitled quantity. Creating an `ACTIVE` record recomputes the owning product's position, the rollups of every non-terminal audit case with a `CONFIRMED` scope item on that product, and the product's monitoring alerts; creating a `SCHEDULED` record triggers none of these effects. The clock sweep later moves `SCHEDULED` records to `ACTIVE` once `effective_from` is reached, and moves `ACTIVE` records to `EXPIRED` once the clock reaches or passes `effective_to`; expiry is monotonic and never reverts. Both sweep transitions recompute the position, the case rollups, and the alerts — expiry drops the record's quantity from the entitled total, which may open an `OVER_DEPLOYMENT` alert, and it resolves any `ENTITLEMENT_EXPIRING` alert that was tracking the record.

Erroneous or duplicate records are corrected by voiding, a `SAMManager`-only action. Only `ACTIVE` or `SCHEDULED` records can be voided; attempting to void a record in any other state is rejected with `ERR_ENTITLEMENT_INVALID_STATE`. Voiding an `ACTIVE` record drops its quantity from the position and triggers the same recompute cascade across position, case rollups, and alerts; voiding a `SCHEDULED` record has no downstream effects. `EXPIRED` and `VOID` are the terminal states of an entitlement. A product's purchase history can be listed with an optional `status` filter, and unknown entitlement identifiers surface as `ERR_ENTITLEMENT_NOT_FOUND`.

### 3.3. Deployment Discovery and Measurement

Discovery data flows in from IT operations. An `ITAnalyst` records each measurement against a `product_id` with the `measured_quantity` observed under the product's license metric — installations, named users, or cores, always a positive integer — the `environment` observed (`PRODUCTION` or `NON_PRODUCTION`), the `measurement_method` (`SCAN` or `MANUAL_DECLARATION`), and the `measured_on` timestamp of the observation. New records begin in `REPORTED` status and do not yet influence any license position.

A `SAMManager` reviews each reported measurement and either confirms or rejects it. Confirmation is allowed only from `REPORTED` — a record in any other state fails with `ERR_DEPLOYMENT_INVALID_STATE` — and only when `measured_on` is not later than the current logical clock, otherwise the request is rejected with `ERR_MEASUREMENT_DATE_IN_FUTURE`. Confirming moves the record to `CONFIRMED` and recomputes the product's deployed quantity, gap, severity, and exposures, together with the rollups of every non-terminal audit case scoping the product and the product's monitoring alerts. Rejection moves the record to `REJECTED`, a terminal state with no position effects; an optional `rejection_reason` may be supplied.

Two further transitions are driven by remediation rather than by direct operator action. Completion of an `UNINSTALL` remediation moves each targeted `CONFIRMED` record to `EXCLUDED` and stamps its `excluded_by_remediation_id` with the completing action's identifier; a subsequent failed verification of that same action moves every such record back from `EXCLUDED` to `CONFIRMED` and clears `excluded_by_remediation_id` to null (§3.8). A product's measurements can be listed with an optional `status` filter, and unknown deployment identifiers surface as `ERR_DEPLOYMENT_NOT_FOUND`.

### 3.4. The License Position: Gap Analysis and Exposure Pricing

Every product's LicensePosition is the self-audit worksheet on which the entire defense rests. Its `entitled_quantity` is the sum of `quantity` over the product's entitlement records currently in `ACTIVE` status; records in `SCHEDULED`, `EXPIRED`, or `VOID` never contribute. Its `deployed_quantity` is the sum of `measured_quantity` over the product's deployment records in `CONFIRMED` status whose `environment` is `PRODUCTION`, plus the `CONFIRMED` records whose `environment` is `NON_PRODUCTION` only when the product's `counts_non_production` flag is true; `REPORTED`, `REJECTED`, and `EXCLUDED` records never contribute. Both aggregates are exact integer unit counts.

The gap itself is `gap_quantity`, the deployed quantity minus the entitled quantity; a positive value means over-deployment. Severity is assigned by evaluating the following ladder in order and stopping at the first matching rung: if the gap is zero or negative, `gap_severity` is `COMPLIANT`; otherwise, if the entitled quantity is zero, `CRITICAL`; otherwise, if the product is `mission_critical` and the gap is at least 25 units, `CRITICAL`; otherwise, if the ratio of deployed to entitled is at least 1.25 or the gap is at least 100 units, `CRITICAL`; otherwise, if the ratio of deployed to entitled is strictly greater than 1.05 or the gap is at least 10 units, `MATERIAL`; otherwise `MINOR`. Ratio comparisons use exact decimal arithmetic with no floating-point drift, so a ratio of exactly 1.05 is not material — the comparison there is strictly greater — while a ratio of exactly 1.25 is critical.

Two exposure figures are priced from the gap. `self_audit_exposure_cents` is the provisional, customer-side basis used before and during vendor engagement: the positive part of the gap (zero when the gap is not positive) multiplied by `unit_list_price_cents`, with no maintenance uplift. `vendor_list_exposure_cents` is the pessimistic basis used for worst-case planning while no vendor finding is recorded: the per-unit factor is first computed as `unit_list_price_cents` increased by the `support_rate_pct` fraction of itself — one year of back-support per missing unit — rounded half up to whole cents, and that rounded factor is then multiplied by the positive part of the gap. Both exposures are exact integer cent amounts.

The position also tracks `position_basis`, recording which measurement basis currently governs the product. It begins at `SELF_AUDIT`, moves to `VENDOR_MEASURED` when the first vendor finding is recorded on a `CONFIRMED` scope item for the product, and moves to `AGREED` when a settlement offer is accepted on an audit case holding a `CONFIRMED` scope item for the product — directly from `SELF_AUDIT` when acceptance happens before any finding is recorded, and from `VENDOR_MEASURED` otherwise.

Positions refresh automatically as entitlements, deployments, pricing, and remediations change, and a `SAMManager` can additionally force an explicit recalculation of a position, which recomputes every computed field from source records, refreshes the case rollups, and upserts monitoring alerts. Reading a product's position returns an array of length zero or one, since exactly one position exists per product; unknown position identifiers surface as `ERR_LICENSE_POSITION_NOT_FOUND`.

### 3.5. Audit Intake, the Response Deadline, and Scope Negotiation

When a vendor's audit notice arrives, `LegalCounsel` opens an AuditCase by recording the auditing `vendor_id`, the `audit_firm_name` conducting the audit on the vendor's behalf, and the `notice_received_on` date. The case's `response_deadline_on` is computed once at creation as `notice_received_on` plus the vendor's `notice_response_deadline_days` days. The case begins in `NOTICE_RECEIVED` and follows the lifecycle `NOTICE_RECEIVED` → `SCOPE_NEGOTIATION` → `EVIDENCE_COLLECTION` → `FINDINGS_REVIEW` → `SETTLEMENT_NEGOTIATION`, terminating in `CLOSED_SETTLED`, `CLOSED_NO_ACTION`, or `WITHDRAWN`. Case listings support optional `vendor_id` and `status` filters, and unknown case identifiers surface as `ERR_AUDIT_CASE_NOT_FOUND`.

`LegalCounsel` advances the case along this lifecycle by naming the desired `to_state`. Advancing from `NOTICE_RECEIVED` to `SCOPE_NEGOTIATION` constitutes the formal response to the notice and must happen no later than the case's `response_deadline_on`: responding at a clock time strictly later than the deadline is rejected with `ERR_RESPONSE_DEADLINE_PASSED`, while acting exactly at the deadline instant is allowed. Advancing from `SCOPE_NEGOTIATION` to `EVIDENCE_COLLECTION` requires that no scope item of the case remains in `PROPOSED` or `DISPUTED` status — otherwise the advance fails with `ERR_SCOPE_ITEMS_PENDING` — and that at least one scope item is `CONFIRMED`, otherwise `ERR_EMPTY_AUDIT_SCOPE`. Advancing from `EVIDENCE_COLLECTION` to `FINDINGS_REVIEW` requires that the case has at least one data submission in `RELEASED` status, otherwise `ERR_NO_RELEASED_SUBMISSION`. Any advance that does not match the case's current status is rejected with `ERR_AUDIT_CASE_INVALID_STATE`.

Scope itself is negotiated item by item. Either party proposes a product into scope — a proposal created by a `VendorAuditor` is stamped `proposed_by` `VENDOR`, and one created by a `SAMManager` is stamped `CUSTOMER` — by supplying the `audit_case_id`, the `product_id`, and an `inclusion_rationale` explaining why the product is believed to be in scope. Proposals are accepted only while the parent case is `NOTICE_RECEIVED` or `SCOPE_NEGOTIATION`, and a second item for the same case and product in `PROPOSED`, `CONFIRMED`, or `DISPUTED` status is rejected with `ERR_DUPLICATE_SCOPE_ITEM`; an `EXCLUDED` item does not block a fresh proposal.

`LegalCounsel` then disposes of each proposal. Confirming a `PROPOSED` item moves it to `CONFIRMED` and is permitted only while the parent case is in `SCOPE_NEGOTIATION` and no later than the case's response deadline — confirming past `response_deadline_on` fails with `ERR_RESPONSE_DEADLINE_PASSED`, with exactly-at-the-deadline still allowed. Confirmation also enforces exclusive audit occupation: when any other audit case whose status is not `CLOSED_SETTLED`, `CLOSED_NO_ACTION`, or `WITHDRAWN` already holds a `CONFIRMED` scope item for the same product, confirmation is rejected with `ERR_PRODUCT_UNDER_CONCURRENT_AUDIT`. Occupation is measured as the half-open interval from the occupying case's `notice_received_on` up to but not including its closure, so a case that closed before the current case's notice was received does not block. A confirmed item immediately feeds the case rollups, the rollups are recomputed, and the parent case's `version` increments by one. Disputing a `PROPOSED` item records the supplied `dispute_rationale` on it and moves it to `DISPUTED`; either negotiating party may later re-propose a disputed item, which replaces its `inclusion_rationale` with the newly supplied value and returns it to `PROPOSED`. Excluding an item — allowed from `PROPOSED`, `DISPUTED`, or `CONFIRMED` while the case remains in `SCOPE_NEGOTIATION` — moves it to the terminal `EXCLUDED` status; excluding an item that was `CONFIRMED` recomputes the case rollups and increments the case `version`, while excluding a `PROPOSED` or `DISPUTED` item has no rollup effect. Every one of these scope operations requires the item to be in the expected prior `scope_status`, failing with `ERR_SCOPE_ITEM_INVALID_STATE` otherwise, and requires the parent case state described above, failing with `ERR_AUDIT_CASE_INVALID_STATE` otherwise.

The case carries two rolling exposure totals over its `CONFIRMED` scope items only — items in `PROPOSED`, `DISPUTED`, or `EXCLUDED` never contribute. `provisional_case_exposure_cents` sums the `self_audit_exposure_cents` of each confirmed product's position and represents the pure self-audit basis before any vendor finding is recorded. `worst_case_exposure_cents` sums, per confirmed item, the recorded `vendor_finding_amount_cents` where one exists and the product's `vendor_list_exposure_cents` otherwise, mixing recorded findings with vendor-list estimates as the negotiation floor and cap. Both totals add stored integer cents exactly, with no re-rounding at the total. Scope items can be listed per case with an optional `scope_status` filter, or per product across all cases; unknown item identifiers surface as `ERR_SCOPE_ITEM_NOT_FOUND`.

### 3.6. Evidence Packages: Privilege Review and Controlled Release

Evidence flows to the auditor only through curated packages. A `SAMManager` prepares a DataSubmission for a case that is not yet `CLOSED_SETTLED`, `CLOSED_NO_ACTION`, or `WITHDRAWN` by supplying the `audit_case_id`, a human-readable `submission_label`, and a non-empty `covered_scope_item_ids` array naming the scope items whose position data the package covers; every named item must exist (`ERR_SCOPE_ITEM_NOT_FOUND`) and must belong to the same audit case as the package (`ERR_SUBMISSION_SCOPE_MISMATCH`). The preparer's identity is stamped from `X-User-ID` into `prepared_by_user_id` at creation, and the package begins in `DRAFT`. A package flagged `contains_privileged` (defaulting to false) carries attorney-client privileged material and faces an additional release gate.

The review loop is counsel-driven. Sending a `DRAFT` package to privilege review moves it to `PRIVILEGE_REVIEW`. `LegalCounsel` then approves it — moving it to `APPROVED` — or returns it to `DRAFT` with a recorded `return_reason` so the preparer can redact and resubmit through the same loop. Each of these transitions requires the package to be in the expected prior status, failing with `ERR_SUBMISSION_INVALID_STATE` otherwise, and approval enforces segregation of duties: the approver's `X-User-ID` must differ from `prepared_by_user_id`, otherwise the request is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`.

Release is the point of no return. `LegalCounsel` may release an `APPROVED` package only while the parent case is in `EVIDENCE_COLLECTION` or `FINDINGS_REVIEW`, failing with `ERR_AUDIT_CASE_INVALID_STATE` otherwise, and the releaser's `X-User-ID` must again differ from `prepared_by_user_id` (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`). Two content gates then apply. A package whose `contains_privileged` is true may be released only when the request explicitly carries `privilege_waiver_confirmed` set to true, otherwise the release is rejected with `ERR_PRIVILEGED_CONTENT_REQUIRES_WAIVER`. And at least one covered scope item must be `CONFIRMED` at the moment of release, otherwise the release fails with `ERR_EMPTY_SUBMISSION_PACKAGE`. A successful release stamps `released_on` with the current logical clock and freezes `released_exposure_cents` as the sum of the `self_audit_exposure_cents` over the covered items that are `CONFIRMED` at that instant — a snapshot that never changes thereafter — and increments the parent case's `version` by one. `RELEASED` is the package's terminal state, and both `released_on` and `released_exposure_cents` remain null until it is reached. When a case's submissions are listed, a `VendorAuditor` sees only `RELEASED` rows through a server-side filter, while internal roles see all states and may apply a `status` filter; unknown submission identifiers surface as `ERR_SUBMISSION_NOT_FOUND`.

### 3.7. Findings, Settlement Negotiation, and Case Closure

Once a case reaches `FINDINGS_REVIEW`, the `VendorAuditor` records its assessed true-up on each confirmed item. Recording a vendor finding requires the item to be `CONFIRMED` (`ERR_SCOPE_ITEM_INVALID_STATE` otherwise) and the parent case to be in `FINDINGS_REVIEW` (`ERR_AUDIT_CASE_INVALID_STATE` otherwise). The assessed amount is priced from the product's license position at the moment of the finding: the current `gap_quantity` multiplied by `unit_list_price_cents`, multiplied by one plus twice the `support_rate_pct` — that is, two years of back-support per missing unit — with the result rounded half up to whole cents. The rounded per-line value is stored on the item as `vendor_finding_amount_cents` and is never recomputed retroactively; the case's `worst_case_exposure_cents` sums the stored per-line values exactly. The rounding order is pinned: each line is rounded to cents first and the lines are then summed; summing first and rounding the total once is a different, rejected algorithm that yields different totals whenever per-line fractions accumulate below half a cent. The first finding recorded on any confirmed item of a product flips that product's `position_basis` from `SELF_AUDIT` to `VENDOR_MEASURED`; the case rollups recompute and the case `version` increments by one. Until a finding is recorded, `vendor_finding_amount_cents` is null.

Two exits exist from findings review. Advancing to `SETTLEMENT_NEGOTIATION` requires every `CONFIRMED` scope item of the case to carry a recorded `vendor_finding_amount_cents`, failing with `ERR_FINDINGS_INCOMPLETE` otherwise. Advancing directly to `CLOSED_NO_ACTION` is permitted only when the case's `worst_case_exposure_cents` is exactly zero, failing with `ERR_EXPOSURE_NOT_ZERO` otherwise. The vendor may also push the case back for more data: a `VendorAuditor` request for supplemental evidence reopens the case from `FINDINGS_REVIEW` to `EVIDENCE_COLLECTION`, incrementing the case `version` by one.

In `SETTLEMENT_NEGOTIATION`, offers alternate between the parties. A `ProcurementLead` tenders customer offers (`offered_by` `CUSTOMER`) and a `VendorAuditor` tenders vendor offers (`offered_by` `VENDOR`), each naming the `audit_case_id`, a positive `amount_cents`, and an optional `future_license_discount_pct` between 0 and 0.5 inclusive that defaults to 0 when omitted. Offers can be tendered only while the parent case is in `SETTLEMENT_NEGOTIATION`, failing with `ERR_AUDIT_CASE_INVALID_STATE` otherwise. A customer offer is capped at the case's current `worst_case_exposure_cents`: an amount above the cap is rejected with `ERR_OFFER_EXCEEDS_WORST_CASE_CAP`, while an amount exactly equal to the cap is allowed. Vendor offers carry no such cap. Every offer is created directly in `TENDERED` status, its `tendered_by_user_id` stamped from `X-User-ID`, and tendering supersedes whatever offer was previously pending for the case: the prior `TENDERED` offer moves to `SUPERSEDED`, the new offer's `supersedes_offer_id` points at that prior offer (null when none existed), and the case's `last_tendered_offer_id` is updated to the new offer while the case `version` increments by one. Because each tender advances the case version, at most one `TENDERED` offer exists per case at any time, so the supersession selector is deterministic. Tendering is also the system's single optimistic-concurrency-guarded write: the request must carry `expected_audit_case_version` per §2.9, and a stale value is rejected with `ERR_STALE_VERSION`. Offers may be browsed as a list filtered by `audit_case_id`, `supersedes_offer_id`, or `status`, or fetched individually, with unknown identifiers surfacing as `ERR_OFFER_NOT_FOUND`.

Acceptance belongs to the counterparty: a `VENDOR` offer is accepted by `LegalCounsel`, and a `CUSTOMER` offer is accepted by the `VendorAuditor` — a role that does not match the offer's party is rejected with `ERR_INSUFFICIENT_PERMISSIONS` — and only a `TENDERED` offer can be accepted (`ERR_OFFER_INVALID_STATE` otherwise). The acceptor's `X-User-ID` must differ from the `tendered_by_user_id` stamped at tender time, otherwise acceptance fails with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`. Acceptance closes the case as `CLOSED_SETTLED`, copying the accepted offer's `amount_cents` into the case's `settled_amount_cents` and its `future_license_discount_pct` into `accepted_future_discount_pct`; every product with a `CONFIRMED` scope item in the case has its `position_basis` advanced to `AGREED`; and the case `version` increments by one. The tendering party may instead withdraw its own pending offer — `ProcurementLead` for `CUSTOMER` offers, `VendorAuditor` for `VENDOR` offers, again under the party-match rule — moving it from `TENDERED` to `WITHDRAWN` and clearing the case's `last_tendered_offer_id` when it referenced that offer. `ACCEPTED`, `WITHDRAWN`, and `SUPERSEDED` are terminal for an offer, and `settled_amount_cents`, `accepted_future_discount_pct`, and `last_tendered_offer_id` remain null until the events that populate them.

The vendor may abandon the audit entirely: a `VendorAuditor` withdrawal moves the case from any non-terminal state to `WITHDRAWN` — attempting it on a closed or already withdrawn case fails with `ERR_AUDIT_CASE_INVALID_STATE` — and cascades through the case's open work: any currently `TENDERED` offer moves to `WITHDRAWN` with `last_tendered_offer_id` cleared, every `PROPOSED` or `DISPUTED` scope item moves to `EXCLUDED`, and the case `version` increments by one.

### 3.8. Remediation of Over-Deployment

Curing an over-deployed product is planned as a RemediationAction by a `SAMManager`, naming the `product_id` and an `action_type` of `UNINSTALL` or `PURCHASE_TRUE_UP`. The two types take different inputs. An `UNINSTALL` requires a non-empty `target_deployment_ids` array naming the deployments to exclude — each target must exist (`ERR_DEPLOYMENT_NOT_FOUND`), must belong to the action's product, and must be `CONFIRMED`, otherwise creation is rejected with `ERR_REMEDIATION_TARGET_INVALID` — and any `quantity` input on an `UNINSTALL` is ignored: the server computes the action's `quantity` as the sum of the targeted deployments' `measured_quantity`. A `PURCHASE_TRUE_UP` forbids `target_deployment_ids` and instead takes a positive `quantity`. In both cases the action's quantity may not exceed the product's current `gap_quantity`; equality is allowed, and an excess is rejected with `ERR_REMEDIATION_EXCEEDS_GAP`. New actions begin in `PLANNED` status.

Execution proceeds stepwise. Starting moves a `PLANNED` action to `IN_PROGRESS`. Completing an `IN_PROGRESS` action applies the cure. For `UNINSTALL`, completion moves every targeted deployment from `CONFIRMED` to `EXCLUDED`, stamping each record's `excluded_by_remediation_id` with the completing action's identifier. For `PURCHASE_TRUE_UP`, completion creates a new entitlement record with `source` `AUTO_TRUE_UP`, `quantity` equal to the action's `quantity`, `coverage_class` `PRODUCTION`, `effective_from` set to the current logical clock, `effective_to` null (perpetual), and a `purchase_order_number` formed as 'TRUEUP-' followed by the action's identifier; the action's `generated_entitlement_id` points at the new record and remains null for `UNINSTALL` actions. Either way, the position is then recomputed — the new entitlement's activation lifts `entitled_quantity`, or the exclusions lower `deployed_quantity` — the rollups of every non-terminal audit case scoping the product are recomputed with each such case's `version` incremented by one, and the product's monitoring alerts are upserted, resolving the `OVER_DEPLOYMENT` alert when the gap returns to zero. Attempting to start, complete, cancel, or fail-verify an action whose status does not permit that transition is rejected with `ERR_REMEDIATION_INVALID_STATE`.

Verification can fail after completion, which moves the action from `COMPLETED` back to `PLANNED` as a compensating transaction that reverses every completion effect. For `UNINSTALL`, every deployment whose `excluded_by_remediation_id` names this action returns from `EXCLUDED` to `CONFIRMED` with the reference cleared to null. For `PURCHASE_TRUE_UP`, the generated entitlement is voided from `ACTIVE` or `SCHEDULED` to `VOID`, with `generated_entitlement_id` retained on the action for audit. Position, case rollups, and alerts are then recomputed under a conservation rule: deployed and entitled quantities return exactly to their pre-completion values. An optional `verification_notes` may be supplied with the failure report. A `PLANNED` or `IN_PROGRESS` action may instead be cancelled outright, ending in the terminal `CANCELLED` state. Actions can be fetched individually (`ERR_REMEDIATION_NOT_FOUND`), listed per product with an optional `status` filter, and the deployments excluded by an action can be listed from the action itself.

### 3.9. Monitoring Alerts and Ongoing Surveillance

Positions are watched continuously so that a renewed gap or an expiring entitlement never goes unnoticed. Two alert conditions exist, identified by `alert_type`. `OVER_DEPLOYMENT` fires whenever a position recompute finds `gap_quantity` strictly greater than zero — a gap of exactly zero does not trigger it — and its `severity` mirrors the position's `gap_severity`: `MINOR` maps to `INFO`, `MATERIAL` to `WARNING`, and `CRITICAL` to `CRITICAL`. Its `triggered_value` carries the observed `gap_quantity`, and its `threshold_value` is 0. `ENTITLEMENT_EXPIRING` fires when some `ACTIVE` entitlement of the product will reach its `effective_to` within the next 30 days, measured in whole days as the floor of the difference between `effective_to` and the current clock: a record with exactly 30 days remaining does trigger the alert, 31 days does not, and the day of expiry itself still counts. Its `triggered_value` carries the smallest days-to-expiry among the matching records, its `threshold_value` is 30, and its `severity` is always `WARNING`.

Alert creation is an upsert: at most one alert per product and `alert_type` exists in `OPEN` or `SUPPRESSED` status at any time, stamped with its `severity`, `triggered_value`, and `threshold_value` when the triggering recompute or clock sweep creates it. When the underlying condition later evaluates false, any `OPEN` or `SUPPRESSED` alert resolves automatically to the terminal `RESOLVED` status — an expiring-entitlement alert therefore resolves once the entitlement expires, and an over-deployment alert resolves when the gap closes.

A `SAMManager` may suppress an `OPEN` alert by recording a mandatory `suppression_reason`; suppression captures the current `triggered_value` into `suppressed_value`, which remains null unless the alert is `SUPPRESSED`. Suppression is not silence forever: each later re-evaluation compares the fresh `triggered_value` against `suppressed_value`, and when the value has worsened strictly beyond it — a larger gap for `OVER_DEPLOYMENT`, or fewer days to expiry for `ENTITLEMENT_EXPIRING` — the same alert row re-opens to `OPEN` with its `id` unchanged and `suppressed_value` cleared. Suppressing an alert that is not `OPEN` is rejected with `ERR_ALERT_INVALID_STATE`. Alerts are listed per product with optional `status` and `alert_type` filters, and unknown alert identifiers surface as `ERR_ALERT_NOT_FOUND`.

## 4. Endpoint Definitions

Operations that create a new resource — vendors, products, entitlements, deployments, audit cases, scope items, data submissions, settlement offers, and remediation actions — return a `201 Created` status code. Operations that modify an existing resource or drive a state transition, as well as all reads, return a `200 OK` status code. The table below is a summary only; the complete request and response shape of each operation is defined by the workflows of §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/sam/vendors` | Register a software vendor (licensor) | SAMPlatformAdmin |
| POST | `/sam/products` | Register a licensed product; auto-creates its LicensePosition | SAMPlatformAdmin |
| GET | `/sam/products` | List products; optional vendor filter | SAMPlatformAdmin, SAMManager, ITAnalyst, LegalCounsel, ProcurementLead |
| GET | `/sam/products/{productId}` | Get a product | SAMPlatformAdmin, SAMManager, ITAnalyst, LegalCounsel, ProcurementLead |
| PATCH | `/sam/products/{productId}` | Update pricing/flags; recomputes the product's position exposures and case rollups | SAMPlatformAdmin |
| POST | `/sam/entitlements` | Consolidate a purchase/entitlement record; window-overlap and initial status per clock | SAMManager, ProcurementLead |
| GET | `/sam/products/{id}/entitlements` | List entitlement records of a product (purchase history) | SAMPlatformAdmin, SAMManager, ITAnalyst, LegalCounsel, ProcurementLead |
| POST | `/sam/entitlements/{entitlementId}/void` | Void an erroneous/duplicate entitlement record | SAMManager |
| POST | `/sam/deployments` | Record a deployment measurement per the product's vendor metric | ITAnalyst |
| GET | `/sam/products/{id}/deployments` | List deployment records of a product | SAMPlatformAdmin, SAMManager, ITAnalyst, LegalCounsel, ProcurementLead |
| POST | `/sam/deployments/{deploymentId}/confirm` | Confirm a reported measurement into the license position | SAMManager |
| POST | `/sam/deployments/{deploymentId}/reject` | Reject an erroneous measurement (terminal) | SAMManager |
| GET | `/sam/products/{id}/license-positions` | Get the product's license position (array of length 0-1) | SAMPlatformAdmin, SAMManager, ITAnalyst, LegalCounsel, ProcurementLead |
| POST | `/sam/license-positions/{positionId}/recalculate` | Explicitly recompute entitled/deployed/gap/severity/exposures from source records | SAMManager |
| POST | `/sam/audit-cases` | Open an audit case from a vendor audit notice; `response_deadline_on` computed | LegalCounsel |
| GET | `/sam/audit-cases` | List audit cases; optional vendor/status filters | SAMPlatformAdmin, SAMManager, ITAnalyst, LegalCounsel, ProcurementLead, VendorAuditor |
| GET | `/sam/audit-cases/{auditCaseId}` | Get an audit case including rollup exposures | SAMPlatformAdmin, SAMManager, ITAnalyst, LegalCounsel, ProcurementLead, VendorAuditor |
| POST | `/sam/audit-cases/{auditCaseId}/advance` | Advance the case lifecycle; `to_state` selects the target per the state machine | LegalCounsel |
| POST | `/sam/audit-cases/{auditCaseId}/reopen-evidence` | Vendor requests supplemental evidence: `FINDINGS_REVIEW` → `EVIDENCE_COLLECTION` | VendorAuditor |
| POST | `/sam/audit-cases/{auditCaseId}/withdraw` | Vendor withdraws the audit from any non-terminal state | VendorAuditor |
| POST | `/sam/audit-scope-items` | Propose a product into audit scope; `proposed_by` derived from actor role | SAMManager, VendorAuditor |
| GET | `/sam/audit-cases/{id}/scope-items` | List scope items of a case | SAMPlatformAdmin, SAMManager, ITAnalyst, LegalCounsel, ProcurementLead, VendorAuditor |
| GET | `/sam/products/{id}/audit-scope-items` | List scope items referencing a product (across cases) | SAMPlatformAdmin, SAMManager, ITAnalyst, LegalCounsel, ProcurementLead, VendorAuditor |
| POST | `/sam/audit-scope-items/{scopeItemId}/confirm` | Customer accepts a proposed item into confirmed scope | LegalCounsel |
| POST | `/sam/audit-scope-items/{scopeItemId}/dispute` | Customer disputes a proposed item | LegalCounsel |
| POST | `/sam/audit-scope-items/{scopeItemId}/repropose` | Re-propose a disputed item with a revised rationale (negotiation loop) | SAMManager, VendorAuditor |
| POST | `/sam/audit-scope-items/{scopeItemId}/exclude` | Exclude an item from scope while the case is in `SCOPE_NEGOTIATION` | LegalCounsel |
| POST | `/sam/audit-scope-items/{scopeItemId}/vendor-finding` | Vendor records its assessed true-up finding for an item (per-line rounded pricing, snapshotted) | VendorAuditor |
| POST | `/sam/data-submissions` | Prepare an evidence package covering scope items of a case | SAMManager |
| GET | `/sam/audit-cases/{id}/data-submissions` | List submissions of a case; VendorAuditor sees only `RELEASED` rows (server-side filter) | SAMPlatformAdmin, SAMManager, ITAnalyst, LegalCounsel, ProcurementLead, VendorAuditor |
| POST | `/sam/data-submissions/{submissionId}/submit-for-review` | Send a draft package to privilege review | SAMManager |
| POST | `/sam/data-submissions/{submissionId}/approve` | Counsel approves a package (cannot be the preparer) | LegalCounsel |
| POST | `/sam/data-submissions/{submissionId}/return` | Counsel returns a package to `DRAFT` for redaction (revision loop) | LegalCounsel |
| POST | `/sam/data-submissions/{submissionId}/release` | Release an approved package to the auditor; snapshots covered self-audit exposure; privileged content needs waiver | LegalCounsel |
| POST | `/sam/settlement-offers` | Tender a settlement offer (created directly `TENDERED`); supersedes the case's pending offer; OCC-guarded on the case version | ProcurementLead, VendorAuditor |
| GET | `/sam/settlement-offers` | List offers; filter by case, supersession chain, or status | SAMPlatformAdmin, SAMManager, ITAnalyst, LegalCounsel, ProcurementLead, VendorAuditor |
| GET | `/sam/settlement-offers/{offerId}` | Get a settlement offer | SAMPlatformAdmin, SAMManager, ITAnalyst, LegalCounsel, ProcurementLead, VendorAuditor |
| POST | `/sam/settlement-offers/{offerId}/accept` | Counterparty accepts a tendered offer; closes the case as `CLOSED_SETTLED` | LegalCounsel, VendorAuditor |
| POST | `/sam/settlement-offers/{offerId}/withdraw` | Tendering party withdraws its pending offer | ProcurementLead, VendorAuditor |
| POST | `/sam/remediation-actions` | Plan a remediation (`UNINSTALL` with target deployments, or `PURCHASE_TRUE_UP` with quantity) | SAMManager |
| GET | `/sam/remediation-actions/{actionId}` | Get a remediation action | SAMPlatformAdmin, SAMManager, ITAnalyst, LegalCounsel, ProcurementLead |
| GET | `/sam/products/{id}/remediation-actions` | List remediation actions of a product | SAMPlatformAdmin, SAMManager, ITAnalyst, LegalCounsel, ProcurementLead |
| GET | `/sam/remediation-actions/{id}/deployments` | List deployment records excluded by this remediation | SAMPlatformAdmin, SAMManager, ITAnalyst, LegalCounsel, ProcurementLead |
| POST | `/sam/remediation-actions/{actionId}/start` | Begin executing a planned remediation | SAMManager |
| POST | `/sam/remediation-actions/{actionId}/complete` | Complete a remediation; applies entitlement/deployment effects and recomputes positions, rollups, alerts | SAMManager |
| POST | `/sam/remediation-actions/{actionId}/cancel` | Cancel a planned or in-progress remediation | SAMManager |
| POST | `/sam/remediation-actions/{actionId}/fail-verification` | Mark a completed remediation as failed verification; reverses all completion effects | SAMManager |
| GET | `/sam/products/{id}/monitoring-alerts` | List monitoring alerts of a product | SAMPlatformAdmin, SAMManager, ITAnalyst, LegalCounsel, ProcurementLead |
| POST | `/sam/monitoring-alerts/{alertId}/suppress` | Suppress an `OPEN` alert with a reason; re-opens automatically if the condition worsens | SAMManager |
| POST | `/_clock/set_current_utc` | Set the server's logical clock; triggers entitlement sweep, expiry alert sweep, position recomputes, and case rollups | SAMPlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue lists only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_VENDOR_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_ENTITLEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_DEPLOYMENT_NOT_FOUND` | 404 Not Found |
| `ERR_LICENSE_POSITION_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_SCOPE_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_SUBMISSION_NOT_FOUND` | 404 Not Found |
| `ERR_OFFER_NOT_FOUND` | 404 Not Found |
| `ERR_REMEDIATION_NOT_FOUND` | 404 Not Found |
| `ERR_ALERT_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_AUDIT_CASE_INVALID_STATE` | 409 Conflict |
| `ERR_SCOPE_ITEM_INVALID_STATE` | 409 Conflict |
| `ERR_SUBMISSION_INVALID_STATE` | 409 Conflict |
| `ERR_OFFER_INVALID_STATE` | 409 Conflict |
| `ERR_DEPLOYMENT_INVALID_STATE` | 409 Conflict |
| `ERR_REMEDIATION_INVALID_STATE` | 409 Conflict |
| `ERR_ALERT_INVALID_STATE` | 409 Conflict |
| `ERR_ENTITLEMENT_INVALID_STATE` | 409 Conflict |
| `ERR_SCOPE_ITEMS_PENDING` | 409 Conflict |
| `ERR_EMPTY_AUDIT_SCOPE` | 409 Conflict |
| `ERR_NO_RELEASED_SUBMISSION` | 409 Conflict |
| `ERR_FINDINGS_INCOMPLETE` | 409 Conflict |
| `ERR_EXPOSURE_NOT_ZERO` | 409 Conflict |
| `ERR_RESPONSE_DEADLINE_PASSED` | 409 Conflict |
| `ERR_MEASUREMENT_DATE_IN_FUTURE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_VENDOR_CODE` | 409 Conflict |
| `ERR_DUPLICATE_SCOPE_ITEM` | 409 Conflict |
| `ERR_PRODUCT_UNDER_CONCURRENT_AUDIT` | 409 Conflict |
| `ERR_ENTITLEMENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_PRIVILEGED_CONTENT_REQUIRES_WAIVER` | 422 Unprocessable Entity |
| `ERR_SUBMISSION_SCOPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_REMEDIATION_TARGET_INVALID` | 422 Unprocessable Entity |
| `ERR_EMPTY_SUBMISSION_PACKAGE` | 422 Unprocessable Entity |
| `ERR_OFFER_EXCEEDS_WORST_CASE_CAP` | 422 Unprocessable Entity |
| `ERR_REMEDIATION_EXCEEDS_GAP` | 422 Unprocessable Entity |
