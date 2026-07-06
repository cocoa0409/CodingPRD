# Web Accessibility ADA API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Web-Accessibility & ADA Compliance Service, a backend platform that takes a customer's web properties from an initial automated scan all the way through formal conformance certification. Modeled on the workflow of accessibility-audit vendors, the service orchestrates the full compliance lifecycle: scanning a site against the Web Content Accessibility Guidelines (WCAG), cataloguing the resulting issues by severity, assigning and re-testing remediation work, issuing a Voluntary Product Accessibility Template (VPAT) conformance report, granting a public certification badge, and responding to legal demand letters and lawsuits.

The platform serves five distinct professional audiences working in concert. Audit engineers run scans and emit findings; remediation vendors fix what those scans uncover; compliance managers own the legal, certification, and conformance-reporting surface; organization administrators manage their own subscription, sites, and staff training; and platform operators administer the system end to end. Because a single customer site can simultaneously be mid-remediation, named in an active lawsuit, and pending re-certification, the service places heavy emphasis on **derived state** — a site's audit posture and risk exposure are never set by hand but recomputed from the live population of findings and legal demands that surround it. The requirements below describe these derivations, the state machines that drive them, the financial calculations that price subscriptions and grant remediation credits, and the concurrency guards that keep certification honest.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint of the API. All resource paths described in this document are mounted under the `/compliance` prefix.

### 2.1. User and Role-Based Access Control

Every request to the API (with the sole exception of the logical-clock read described later) must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares their operational capacity. If either header is missing, or if `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly five roles, spelled precisely as follows: `PlatformAdmin`, `OrgAdmin`, `AuditEngineer`, `RemediationVendor`, and `ComplianceManager`.

- `PlatformAdmin` is the operational superuser: it creates organizations, drives the operator side of the subscription lifecycle (mark-past-due, suspend), runs monitoring sweeps and expiry transitions, and controls the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.
- `OrgAdmin` is the customer-side administrator who manages the organization's subscription activation and cancellation, registers sites, and runs staff training. When `X-User-Role` is `OrgAdmin`, `X-User-ID` is the `id` of the acting `Organization`; ownership checks on any resource that references an `Organization` compare the resource's organization foreign-key field to `X-User-ID`.
- `AuditEngineer` owns scans, the emission of findings at scan completion, and re-tests. When `X-User-Role` is `AuditEngineer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.
- `RemediationVendor` owns remediation tasks and their lifecycle. When `X-User-Role` is `RemediationVendor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.
- `ComplianceManager` owns VPAT reports, the legal-demand response workflow, accept-risk decisions, and certifications/badges. When `X-User-Role` is `ComplianceManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

The per-operation authorization grants are enumerated in the endpoint table of §4.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the inclusive range of 1 through 100, or an `offset` below 0, is rejected with `ERR_INVALID_PAGINATION` (HTTP 422).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every primary resource carries a server-minted `id` formatted as a UUID, with no type prefix. Most resources also carry three further system-managed fields: a `created_at` ISO 8601 UTC timestamp with three fractional digits recorded at creation, an `updated_at` ISO 8601 UTC timestamp refreshed on every mutation, and an integer `version` that begins at 1 and increments by exactly one on every mutation that changes the resource. The `version` field underpins the optimistic-concurrency guards described in §2.7. Every entity that participates in a lifecycle exposes its current lifecycle state in a field named `status`, whose permitted values are the per-entity state enumerations described throughout §3.

Two entities are deliberately leaner. A `RetestRun` and a `MonitoringCheck` are immutable event records: each carries only an `id` and a `created_at`. Neither has an `updated_at` field and neither has a `version` field. Implementations must not emit those two fields on retest runs or monitoring checks.

### 2.5. Derived State and Cascading Reconciliation

A central design principle of this platform is that several fields are **derived** — never written directly by a client, but recomputed by the server whenever the facts underneath them change. When a single operation changes a derived field's inputs, the server recomputes that field as part of the same operation, and any downstream field that depends on it is recomputed in turn, in a fixed order. Each such recomputation is a mutation of the affected resource: it refreshes that resource's `updated_at` and increments its `version`.

Three cascade chains recur throughout the workflows in §3. First, completing a scan emits findings, then recomputes the parent site's `audit_posture` from those findings, then recomputes the parent site's `risk_exposure_score` from those same findings. Second, issuing a VPAT report freezes its certified score, derives its conformance level, and then recomputes the owning organization's account credit keyed on that newly derived level. Third, every legal-demand transition recomputes the organization's open-demand count, then recomputes the affected site's `audit_posture`, then recomputes that site's `risk_exposure_score`. These chains are described in business terms in §3; the recurring rule is simply that derived fields are always reconciled immediately and the version of every touched resource advances.

### 2.6. Conformance Scoring, Risk, and Rounding Precision

The platform computes two families of scores, both on a 0 to 100 scale and both rounded to exactly two decimal places using the round-half-up method.

Conformance scoring is a severity-weighted measure of how much of a scan's accessibility debt has been remediated. Each finding carries a weight by severity: a `CRITICAL` finding weighs 10, a `SERIOUS` finding weighs 5, a `MODERATE` finding weighs 2, and a `MINOR` finding weighs 1. The total weight is the sum of these weights across every finding emitted by the scan, counting all severities and all statuses. The passed weight is the sum of the same weights, but only over those findings whose status falls in the remediated set for the variant being computed. When the total weight is zero, the score is exactly 100.00; otherwise the score is 100 multiplied by the passed weight, divided by the total weight, rounded half-up to two decimal places. The two variants differ only in which statuses count as remediated: the **provisional** variant (frozen at scan completion onto the scan's `provisional_conformance_score`) treats only `RESOLVED` findings as passed and does not count `WONT_FIX_ACCEPTED`, whereas the **certified** variant (frozen at VPAT issuance onto the report's `certified_conformance_score`) treats both `RESOLVED` and `WONT_FIX_ACCEPTED` findings as passed, so an accepted-risk finding counts as conformant for certification but not for the provisional snapshot.

Risk exposure is a separate 0-to-100 measure stored on a site, recomputed on every finding transition and every legal-demand transition. It is detailed as a workflow concern in §3.7; the relevant precision rule here is that the final value is rounded half-up to two decimal places and capped at 100, and that the overdue-days component is taken as whole days using a floor.

Monetary amounts — subscription invoices and remediation credits — are held in whole cents as integers. The subscription-invoice computation rounds each site's fee to whole cents using round-half-up **before** summing the sites together; that is, rounding is applied per line and then the rounded lines are summed.

### 2.7. Optimistic Concurrency on Certification and Activation

Two write operations are guarded by optimistic concurrency control to prevent a client from acting on a stale view of a moving target. In each case the request must carry an explicit version field naming the version the client last observed; if that value does not match the live version of the target resource, the request is rejected before any state change.

Issuing a VPAT report must carry `expected_scan_version` matching the current `version` of the report's pinned source scan. A VPAT report is pinned at creation to a specific completed scan, and its certified score is frozen against that scan's findings; if another writer has advanced the source scan's `version` since the client last read it (for example by re-completing the scan or otherwise mutating it), the client's view is stale and the issue is rejected with `ERR_STALE_SCAN_VERSION` (HTTP 412).

Activating a subscription must carry `expected_subscription_version` matching the current `version` of the target subscription. The monthly invoice is computed against the organization's site roster at the moment of activation; if the subscription's `version` has advanced since the client last read it — for instance because a past-due-then-reactivate cycle bumped it — the client's view is stale and the activation is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412).

No other endpoint takes a version field; these two operations are the only ones that participate in optimistic concurrency control.

### 2.8. Referenced-Resource Existence and Foreign-Key Consistency

Every resource referenced by a request — whether named in the URL path or carried in the request body — must exist. Path and body references are validated left to right, and the first reference that does not resolve causes the request to be rejected with `ERR_RESOURCE_NOT_FOUND` (HTTP 404) before any later reference is examined.

Beyond mere existence, certain create operations require their foreign keys to be mutually consistent. On the create paths for remediation tasks, retest runs, VPAT reports, and certifications, the body's foreign keys must point at resources that agree with one another; the canonical example is a retest run, whose referenced remediation task must belong to the same finding named in the body — that is, the task's `finding_id` must equal the retest's `finding_id`. An inconsistent set of foreign keys is rejected with `ERR_FK_MISMATCH` (HTTP 409).

### 2.9. The Logical Clock

All time-dependent behavior in this system — SLA deadlines, overdue determination, certification expiry, and event timestamps — is driven by a server-held **logical clock** rather than wall-clock time. On server startup the logical clock reads exactly `2026-03-01T00:00:00Z`, and it continues to read exactly that value until it is explicitly set; it never falls back to wall-clock time. A `PlatformAdmin` may advance or reset the clock by supplying a `to_iso8601` instant, and any role may read the current clock value, which is returned as `current_utc`. If `to_iso8601`, or any other datetime body field such as a legal demand's `response_due_at`, is not a valid ISO 8601 UTC instant, the request is rejected with `ERR_INVALID_DATETIME` (HTTP 422).

### 2.10. Field Validation and Request Well-Formedness

After authentication, authorization, existence, and any applicable foreign-key and state checks, the system validates the shape of the request body. Required body fields that are absent are rejected with `ERR_MISSING_REQUIRED_FIELD` (HTTP 422). Body fields that are present but carry an unrecognized enum value, an out-of-range number, or an otherwise malformed value are rejected with `ERR_INVALID_FIELD_VALUE` (HTTP 422); this covers a bad enum on any enumerated field, an `audited_page_count` below 1, an `estimated_effort_hours` that is not strictly greater than 0, a `score_pct` outside the inclusive 0-to-100 range, and a `regressions_found` below 0.

### 2.11. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of every referenced resource (`ERR_RESOURCE_NOT_FOUND`), then foreign-key consistency on the create paths that require it (`ERR_FK_MISMATCH`). Next comes the state check that the target is in a state valid for the requested transition (`ERR_INVALID_STATE`), followed by the two optimistic-concurrency guards (`ERR_STALE_SCAN_VERSION`, then `ERR_STALE_SUBSCRIPTION_VERSION`). After those come the business guards in their own order: the legal-block guard (`ERR_SITE_BLOCKED_BY_LEGAL`), the scan-completed requirement for VPAT creation (`ERR_SCAN_NOT_COMPLETED`), the issued-VPAT requirement for certification (`ERR_VPAT_NOT_ISSUED`), the active-subscription requirement for scan start (`ERR_SUBSCRIPTION_NOT_ACTIVE`), the non-empty-findings requirement for scan completion (`ERR_EMPTY_FINDINGS`), the training pass threshold (`ERR_SCORE_BELOW_PASS`), the unique-site-URL constraint (`ERR_DUPLICATE_SITE_URL`), the one-subscription-per-organization constraint (`ERR_SUBSCRIPTION_EXISTS`), and the not-yet-expired guard for certification expiry (`ERR_NOT_YET_EXPIRED`). Finally, body well-formedness is checked: field value validity (`ERR_INVALID_FIELD_VALUE`), then required-field presence (`ERR_MISSING_REQUIRED_FIELD`), and for list endpoints the pagination-bounds check (`ERR_INVALID_PAGINATION`). The practical consequence is that a higher-priority failure masks a lower-priority one — for example, a forbidden role surfaces as `ERR_FORBIDDEN_ROLE` even if the body is also malformed.

## 3. Business Logic & Workflows

### 3.1. Organizations, Subscriptions, and Sites

The customer hierarchy begins with an **Organization**, created by a `PlatformAdmin` who supplies the `legal_name` and the primary compliance `contact_email`. An organization additionally exposes two computed bookkeeping fields that are never set directly. Its `account_credit_cents` is a running credit balance in cents that starts at 0 and is increased only as a side effect of VPAT issuance (see §3.5); nothing in this system debits it. Its `open_legal_demand_count` starts at 0 and reflects the number of legal demands linked to any of the organization's sites whose status is `RECEIVED`, `RESPONDING`, or `ESCALATED`; it is recomputed on every legal-demand transition.

Each organization may hold **at most one Subscription**. An `OrgAdmin` or `PlatformAdmin` creates a subscription by naming the `organization_id` and choosing a `tier` of `SCAN`, `MONITOR`, or `MANAGED`. A new subscription enters the `TRIAL` status. An attempt to create a second subscription for an organization that already has one is rejected with `ERR_SUBSCRIPTION_EXISTS`. A subscription also carries a computed `monthly_invoice_cents`, which holds the most recently computed monthly invoice total and reads 0 until it is first computed at activation.

The subscription lifecycle moves through `TRIAL`, `ACTIVE`, `PAST_DUE`, `SUSPENDED`, and `CANCELLED`. An `OrgAdmin` activates a subscription, taking it from `TRIAL` to `ACTIVE` or, after a lapse, from `PAST_DUE` back to `ACTIVE`; this is the cyclic path that lets a recovered account resume. Activation is guarded by optimistic concurrency as described in §2.7 and, on success, computes and stores `monthly_invoice_cents` over the organization's current site roster and advances the subscription's version. A `PlatformAdmin` may move an `ACTIVE` subscription to `PAST_DUE`, and may move a `PAST_DUE` subscription to `SUSPENDED`. An `OrgAdmin` may cancel a subscription that is in `TRIAL` or `SUSPENDED`, moving it to the terminal `CANCELLED` status. Each of these transitions advances the subscription's version, and only the transition out of the documented `from` status is legal — any other starting status yields `ERR_INVALID_STATE`.

The monthly invoice is a **tiered, per-site** computation. The base tier fee in cents is 9,900 for `SCAN`, 24,900 for `MONITOR`, and 49,900 for `MANAGED`. On top of the tier fee, each audited page adds a per-page charge in cents of 0 for `SCAN`, 5 for `MONITOR`, and 12 for `MANAGED`, multiplied by that site's `audited_page_count`. A volume discount then applies based on how many sites the organization owns: the discount is 15 percent when the organization has at least 10 sites, 10 percent when it has at least 5 sites (but fewer than 10), and 0 otherwise. The evaluation order is pinned and matters for rounding: for each site, the system takes the tier fee plus the per-page charge times that site's page count, multiplies by one minus the applicable discount, and rounds that single site's fee half-up to whole cents; only after every site's fee has been individually rounded are the rounded fees summed to produce `monthly_invoice_cents`.

A **Site** is registered under an organization by an `OrgAdmin` or `PlatformAdmin`, who supplies the `organization_id`, the root `url`, and the `audited_page_count`, which must be an integer of at least 1. A site's `url` must be unique within its `organization_id`; a duplicate is rejected with `ERR_DUPLICATE_SITE_URL`. Each site exposes two derived fields, `audit_posture` and `risk_exposure_score`, both described in §3.7, that begin at `UNSCANNED` and 0.0 respectively and evolve as scans complete, findings move, and legal demands come and go.

### 3.2. Scanning a Site and Emitting Findings

An **AuditEngineer** drives the scan workflow. A scan is queued by naming its `site_id` and a `wcag_target_level` of `A`, `AA`, or `AAA`; it begins in the `QUEUED` status. Starting a scan advances it from `QUEUED` to `RUNNING`, but only if the parent site's subscription is in `TRIAL` or `ACTIVE` status; a subscription in any other status blocks the start with `ERR_SUBSCRIPTION_NOT_ACTIVE`. Starting also stamps `started_at` with the current logical-clock instant and advances the scan's version. From `QUEUED`, a scan may instead be cancelled, moving it to the terminal `CANCELLED` status. From `RUNNING`, a scan may be failed, moving it to the terminal `FAILED` status.

Completing a scan is the workflow's pivotal event and advances the scan from `RUNNING` to the terminal `COMPLETED` status. The request must carry a `findings` payload, and that payload must contain at least one entry; an empty `findings` payload is rejected with `ERR_EMPTY_FINDINGS`. On completion, the system stamps `completed_at` with the current logical-clock instant and emits one **AuditFinding** per entry in the `findings` payload. Each emitted finding starts `OPEN`, copies the scan's `site_id` into its own `site_id`, and records the entry's `wcag_criterion` (a success-criterion reference such as `1.4.3`) and its `severity`, which must be one of `CRITICAL`, `SERIOUS`, `MODERATE`, or `MINOR`. Each finding also records the `scan_id` of the scan that emitted it. The scan's `finding_count` is set to the number of findings emitted, and its `provisional_conformance_score` is computed by the provisional variant over those findings and frozen onto the scan; the score is null until the scan is completed.

Each emitted finding's deadline, `sla_due_at`, is frozen at emission as the scan's `completed_at` plus a severity-specific number of hours: 72 hours for `CRITICAL`, 168 hours for `SERIOUS`, 720 hours for `MODERATE`, and 2,160 hours for `MINOR`. A finding also exposes a derived `is_overdue` flag, which is true when the logical clock now is strictly past `sla_due_at` and the finding's status is neither `RESOLVED` nor `WONT_FIX_ACCEPTED`; at the exact instant the clock equals `sla_due_at` the finding is not yet overdue, because the comparison is strict. The `is_overdue` flag is re-evaluated on read and on every transition.

Completing a scan also triggers the first cascade chain of §2.5: the parent site's `audit_posture` is recomputed from the freshly emitted findings (a previously `UNSCANNED` site moves to `AT_RISK` if open findings exist, or to `CLEAN` if none do), and then the site's `risk_exposure_score` is recomputed by the current variant. The scan's own version is advanced.

### 3.3. The Remediation Loop

Findings travel a cyclic remediation lifecycle owned jointly by remediation vendors and audit engineers: `OPEN`, `IN_REMEDIATION`, `RETEST_PENDING`, and then either `RESOLVED` (terminal) or `REOPENED`, from which the loop repeats. A finding may also be retired directly from `OPEN` to the terminal `WONT_FIX_ACCEPTED` status. The two terminal states are `RESOLVED` and `WONT_FIX_ACCEPTED`.

A **RemediationVendor** opens remediation on a finding by creating a **RemediationTask**, supplying the `finding_id`, the `assigned_vendor_id` (an opaque vendor operator identifier), and an `estimated_effort_hours` estimate that must be a number strictly greater than 0. Creating the first task on a finding moves that finding from `OPEN` to `IN_REMEDIATION` and creates the task in the `ASSIGNED` status. A task may only be opened when the parent site is not `BLOCKED` by an active legal demand; an attempt against a blocked site is rejected with `ERR_SITE_BLOCKED_BY_LEGAL` (this same guard governs accept-risk and VPAT issuance, as noted in §3.7). Each remediation-task creation advances the parent finding's version.

The task itself moves through `ASSIGNED`, `IN_PROGRESS`, `SUBMITTED`, and then a terminal outcome of `ACCEPTED`, `REJECTED`, or `SUPERSEDED`. The vendor begins work, moving the task from `ASSIGNED` to `IN_PROGRESS` and advancing the task's version. The vendor then submits the task, which is permitted only when the task is `IN_PROGRESS` and its linked finding is `IN_REMEDIATION`; submission moves the task from `IN_PROGRESS` to `SUBMITTED`, cascades the linked finding from `IN_REMEDIATION` to `RETEST_PENDING`, and advances both the task's and the finding's versions.

An **AuditEngineer** then records a **RetestRun**, naming the `finding_id`, the `remediation_task_id` whose submission triggered the re-test, and an `outcome` of either `PASS` or `FAIL`. A retest may only be recorded when the finding is `RETEST_PENDING` and the referenced task is `SUBMITTED`. On a `PASS`, the finding moves from `RETEST_PENDING` to the terminal `RESOLVED` status and, as a system-driven transition, the task moves from `SUBMITTED` to `ACCEPTED`; this passing path triggers the cascade that recomputes the site's `audit_posture` (and, if this was the last open finding and no active legal demand remains, drives the posture to `CLEAN`) and then recomputes the site's `risk_exposure_score`, advancing the finding's version. On a `FAIL`, the finding moves from `RETEST_PENDING` to `REOPENED` and, as a system-driven transition, the task moves from `SUBMITTED` to `REJECTED`, advancing the finding's version. A `RetestRun` records the logical-clock instant it was recorded in its `tested_at` field.

A `REOPENED` finding re-enters remediation through a superseding task. The vendor creates a new remediation task that names the prior rejected task in its `supersedes_task_id`; this is permitted only when the finding is `REOPENED` and the task named by `supersedes_task_id` is in `REJECTED` status — a supersede target in any other status is rejected with `ERR_SUPERSEDE_TARGET_NOT_REJECTED`. The new task is created in `ASSIGNED` with its `supersedes_task_id` set, the superseded task moves as a system-driven transition from `REJECTED` to the terminal `SUPERSEDED` status, the finding moves from `REOPENED` back to `IN_REMEDIATION`, and the finding's version advances. The `supersedes_task_id` is null for the first task on any finding and is set only for these superseding tasks. As with the first task, a superseding task may only be created when the parent site is not `BLOCKED`. Any of these transitions attempted against a finding or task that is not in the required starting state is rejected with `ERR_INVALID_STATE`.

### 3.4. Conformance Reporting via VPAT

A **ComplianceManager** produces formal conformance documentation through a **VpatReport**. The report is created by naming the `site_id` it covers and the `source_scan_id` whose findings it will certify; the source scan must be `COMPLETED`, and a scan in any other status causes the create to be rejected with `ERR_SCAN_NOT_COMPLETED`. At creation the report enters the `DRAFT` status and snapshots the source scan's current version into `pinned_scan_version`, which later guards against stale references. Until issuance, the report's `certified_conformance_score` and its `conformance_level` are both null.

Issuing a report advances it from `DRAFT` to the `ISSUED` status and is permitted only when the report is `DRAFT`, its source scan is `COMPLETED`, its source site is not `BLOCKED` by an active legal demand (otherwise `ERR_SITE_BLOCKED_BY_LEGAL`), and the optimistic-concurrency guard of §2.7 holds: the supplied `expected_scan_version` must equal the source scan's live version, and `pinned_scan_version` must still match that live version, or the issue is rejected with `ERR_STALE_SCAN_VERSION`. On issuance the system computes and freezes the `certified_conformance_score` by the certified variant of the conformance calculation and then derives the `conformance_level` from that score's tier. The level is `WCAG_AA_FULL` when the certified score is at least 95, `WCAG_AA_PARTIAL` when it is at least 80 (but below 95), `WCAG_A` when it is at least 50 (but below 80), and `NON_CONFORMANT` otherwise; the tier boundaries 95, 80, and 50 are inclusive lower bounds.

Issuance also performs the second cascade chain of §2.5, in a pinned order: first the certified score is computed, then the conformance level is derived from it, and then a remediation credit keyed on that level is added to the owning organization's `account_credit_cents`. The credit, in cents, is 0 for `WCAG_AA_FULL`, 2,500 for `WCAG_AA_PARTIAL`, 5,000 for `WCAG_A`, and 10,000 for `NON_CONFORMANT`. The credit is added to the organization's existing balance and the organization's credit is recomputed; the credit never feeds back into the score, so the order is strictly score, then level, then credit. The report's version advances on issuance.

A `ComplianceManager` may revoke an `ISSUED` report, moving it to the terminal `REVOKED` status. Revocation cascades into certifications: any `Certification` whose `vpat_report_id` names this report and whose status is `GRANTED` is moved from `GRANTED` to `REVOKED`. The report's version advances.

### 3.5. Certifications and Badges

A **Certification** is the public-facing badge that a `ComplianceManager` grants to a site, backed by an issued conformance report. The grant names the `site_id` and the `vpat_report_id`, and the referenced report must be in `ISSUED` status; a report that is not issued causes the grant to be rejected with `ERR_VPAT_NOT_ISSUED`. On a successful grant the certification enters the `GRANTED` status, the server mints an opaque `badge_token` to embed on the certified site, and it sets `expires_at` to the logical-clock granting instant plus 365 days, after which the certification lapses.

A certification may leave `GRANTED` along two paths. A `ComplianceManager` may revoke it directly, moving it to the terminal `REVOKED` status — and, as described in §3.4, the same `GRANTED`-to-`REVOKED` move happens automatically when the backing report is revoked. Alternatively, a `PlatformAdmin` may expire a certification, moving it from `GRANTED` to the terminal `EXPIRED` status, but only once the logical clock now is strictly past the certification's `expires_at`; an attempt to expire before that instant is rejected with `ERR_NOT_YET_EXPIRED`. Each of these transitions advances the certification's version.

### 3.6. Legal Demands and the Block-and-Unblock Cycle

When a customer site is named in a demand letter or lawsuit, a `ComplianceManager` records a **LegalDemand** against it, supplying the `site_id`, the `claimant_name`, and the statutory `response_due_at` deadline. On creation the demand enters the `RECEIVED` status and immediately triggers the third cascade chain of §2.5: the owning organization's `open_legal_demand_count` is recomputed, the named site's `audit_posture` is driven to `BLOCKED`, and the site's `risk_exposure_score` is recomputed with the legal bump (described in §3.7) added.

The demand then proceeds through `RECEIVED`, `RESPONDING`, `ESCALATED`, and the terminal statuses `RESOLVED` and `DISMISSED`. A `ComplianceManager` moves a `RECEIVED` demand to `RESPONDING`, and a `RESPONDING` demand to `ESCALATED`; each of these advances the demand's version without touching the site, because the site stays blocked while any of `RECEIVED`, `RESPONDING`, or `ESCALATED` remain active. The demand is resolved by a `ComplianceManager` from either `RESPONDING` or `ESCALATED`, moving it to the terminal `RESOLVED` status. A `RECEIVED` demand may instead be dismissed, moving it to the terminal `DISMISSED` status.

Both resolution and dismissal close the block-and-unblock cycle by recomputing, in order, the organization's `open_legal_demand_count`, then the affected site's `audit_posture` (which leaves `BLOCKED` for `AT_RISK` or `CLEAN` once no active demand remains on the site), then the site's `risk_exposure_score` (whose legal bump drops to 0 once no active demand remains). The demand's version advances on every transition. As with all transitions, a demand that is not in the documented `from` status for the requested move is rejected with `ERR_INVALID_STATE`.

### 3.7. Audit Posture and Risk Exposure

A site's **audit_posture** is a derived, compound status — `UNSCANNED`, `CLEAN`, `AT_RISK`, or `BLOCKED` — that gates remediation operations and is recomputed on every finding transition and every legal-demand transition. A site is `UNSCANNED` until a scan first completes. Once an active legal demand (one whose status is `RECEIVED`, `RESPONDING`, or `ESCALATED`) is linked to the site, the posture is `BLOCKED`, regardless of its findings. Absent any active legal demand, the posture is `AT_RISK` when the site has any finding in `OPEN`, `IN_REMEDIATION`, or `RETEST_PENDING` status, and `CLEAN` when no such finding remains. A `BLOCKED` posture is what stands behind `ERR_SITE_BLOCKED_BY_LEGAL`: opening or continuing remediation on a finding (creating a remediation task), accepting risk on a finding, and issuing a VPAT report are all refused while the relevant site is `BLOCKED`.

A site's **risk_exposure_score** is a 0-to-100 derived measure, also recomputed on every finding transition and every legal-demand transition, and stored in the current variant on the site. The computation counts, over the site's findings in the open set (for the current variant, the open set is every non-terminal finding — those in `OPEN`, `IN_REMEDIATION`, `RETEST_PENDING`, or `REOPENED`), how many are `CRITICAL` and how many are `SERIOUS`. A base figure is the smaller of 100 and the quantity 8 times the critical count plus 3 times the serious count. An overdue factor is then applied: among the open-set findings that are overdue, the system takes the largest whole number of days a finding is past its `sla_due_at` — that is, the floor of the clock-now-minus-`sla_due_at` difference expressed in whole days (86,400 seconds each) — using 0 if no open-set finding is overdue; the overdue factor is 1 plus the smaller of 1.0 and 0.02 times that day count. A legal bump of 25 is added when the site has any active legal demand (status `RECEIVED`, `RESPONDING`, or `ESCALATED`) and 0 otherwise. The raw score is the base multiplied by the overdue factor, plus the legal bump; the stored `risk_exposure_score` is the smaller of 100.0 and that raw value, rounded half-up to two decimal places.

A **projected** what-if variant of the same measure is available as a computed read and is never persisted. The projection assumes that any finding currently backed by a remediation task in `IN_PROGRESS` or `SUBMITTED` status will close: such findings are excluded from the open set, so the critical and serious counts drop accordingly and the overdue-days figure is taken only over the remaining open-set findings. The read returns both the projected value as `projected_risk_exposure_score` and the live stored value as `current_risk_exposure_score`. Because of the exclusion, the projected figure can diverge from the current figure for the very same site data.

The accept-risk decision sits at the intersection of this section and §3.3. A `ComplianceManager` accepts the risk on a finding that is `OPEN`, moving it directly to the terminal `WONT_FIX_ACCEPTED` status; this is permitted only when the parent site is not `BLOCKED` (otherwise `ERR_SITE_BLOCKED_BY_LEGAL`). Accepting risk cascades a recomputation of the site's `audit_posture` and then its `risk_exposure_score`, and advances the finding's version. As noted in §2.6, an accepted-risk finding counts as conformant for certified scoring but not for the provisional snapshot.

### 3.8. Monitoring and Training

Beyond the core audit-and-remediate loop, the platform tracks two ongoing customer-facing activities.

A `PlatformAdmin` or `AuditEngineer` records a **MonitoringCheck** for a site by naming the `site_id` and the number of new accessibility `regressions_found` during that sweep, which must be an integer of at least 0. The server stamps the check's `checked_at` with the logical-clock instant of the sweep. A monitoring check is an immutable event record, carrying only `id` and `created_at` as system fields.

An `OrgAdmin` enrolls staff in accessibility training by creating a **TrainingEnrollment** under the organization, supplying the `organization_id` and the `learner_email`; the enrollment begins in `ENROLLED`. The `OrgAdmin` starts the training, moving it from `ENROLLED` to `IN_PROGRESS`, and later completes it, moving it from `IN_PROGRESS` to the terminal `COMPLETED` status. Completion requires a `score_pct` (a number in the inclusive 0-to-100 range, required only at completion) of at least 80; a completion submitted with a score below 80 is rejected with `ERR_SCORE_BELOW_PASS`, and the passing score is stored onto the enrollment. A `PlatformAdmin` may instead expire an enrollment that is still `ENROLLED`, moving it to the terminal `EXPIRED` status. Every training transition advances the enrollment's version, and an enrollment not in the documented `from` status is rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including every state transition and every list or fetch read — return a `200 OK` status code. All paths below are mounted under the `/compliance` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/compliance/organizations` | Create an organization | PlatformAdmin |
| GET | `/compliance/organizations/{id}` | Fetch an organization | PlatformAdmin, OrgAdmin, ComplianceManager |
| GET | `/compliance/organizations` | List organizations | PlatformAdmin |
| POST | `/compliance/subscriptions` | Create a TRIAL subscription for an organization | OrgAdmin, PlatformAdmin |
| GET | `/compliance/subscriptions/{id}` | Fetch a subscription | OrgAdmin, PlatformAdmin, ComplianceManager |
| GET | `/compliance/subscriptions` | List subscriptions, filterable by organization | OrgAdmin, PlatformAdmin |
| POST | `/compliance/subscriptions/{id}/activate` | Activate a subscription (OCC-guarded; computes the invoice) | OrgAdmin |
| POST | `/compliance/subscriptions/{id}/mark-past-due` | Move an active subscription to past-due | PlatformAdmin |
| POST | `/compliance/subscriptions/{id}/suspend` | Suspend a past-due subscription | PlatformAdmin |
| POST | `/compliance/subscriptions/{id}/cancel` | Cancel a trial or suspended subscription | OrgAdmin |
| POST | `/compliance/sites` | Register a site under an organization | OrgAdmin, PlatformAdmin |
| GET | `/compliance/sites/{id}` | Fetch a site | OrgAdmin, PlatformAdmin, ComplianceManager, AuditEngineer |
| GET | `/compliance/sites` | List sites, filterable by organization | OrgAdmin, PlatformAdmin, ComplianceManager, AuditEngineer |
| GET | `/compliance/sites/{id}/risk-projection` | Computed read of the projected and current risk exposure | ComplianceManager, AuditEngineer, OrgAdmin |
| POST | `/compliance/scans` | Queue a scan for a site | AuditEngineer |
| GET | `/compliance/scans/{id}` | Fetch a scan | AuditEngineer, ComplianceManager, OrgAdmin, PlatformAdmin |
| GET | `/compliance/scans` | List scans, filterable by site | AuditEngineer, ComplianceManager, OrgAdmin, PlatformAdmin |
| POST | `/compliance/scans/{id}/start` | Start a queued scan | AuditEngineer |
| POST | `/compliance/scans/{id}/complete` | Complete a running scan and emit findings | AuditEngineer |
| POST | `/compliance/scans/{id}/fail` | Fail a running scan | AuditEngineer |
| POST | `/compliance/scans/{id}/cancel` | Cancel a queued scan | AuditEngineer |
| GET | `/compliance/findings/{id}` | Fetch a finding | AuditEngineer, RemediationVendor, ComplianceManager, OrgAdmin, PlatformAdmin |
| GET | `/compliance/findings` | List findings, filterable by scan and/or site | AuditEngineer, RemediationVendor, ComplianceManager, OrgAdmin, PlatformAdmin |
| POST | `/compliance/findings/{id}/accept-risk` | Accept the risk on an open finding | ComplianceManager |
| POST | `/compliance/remediation-tasks` | Create a remediation task on a finding | RemediationVendor |
| GET | `/compliance/remediation-tasks/{id}` | Fetch a remediation task | RemediationVendor, AuditEngineer, ComplianceManager, PlatformAdmin |
| GET | `/compliance/remediation-tasks` | List remediation tasks, filterable by finding and/or superseded task | RemediationVendor, AuditEngineer, ComplianceManager, PlatformAdmin |
| POST | `/compliance/remediation-tasks/{id}/begin` | Begin a remediation task | RemediationVendor |
| POST | `/compliance/remediation-tasks/{id}/submit` | Submit a remediation task for re-test | RemediationVendor |
| POST | `/compliance/retest-runs` | Record a re-test outcome | AuditEngineer |
| GET | `/compliance/retest-runs` | List re-test runs, filterable by finding and/or task | AuditEngineer, ComplianceManager, RemediationVendor, PlatformAdmin |
| POST | `/compliance/vpat-reports` | Create a draft VPAT report pinned to a completed scan | ComplianceManager |
| GET | `/compliance/vpat-reports/{id}` | Fetch a VPAT report | ComplianceManager, OrgAdmin, PlatformAdmin, AuditEngineer |
| GET | `/compliance/vpat-reports` | List VPAT reports, filterable by site and/or source scan | ComplianceManager, OrgAdmin, PlatformAdmin, AuditEngineer |
| POST | `/compliance/vpat-reports/{id}/issue` | Issue a VPAT report (OCC-guarded; grants org credit) | ComplianceManager |
| POST | `/compliance/vpat-reports/{id}/revoke` | Revoke an issued VPAT report | ComplianceManager |
| POST | `/compliance/legal-demands` | Record a legal demand against a site | ComplianceManager |
| GET | `/compliance/legal-demands/{id}` | Fetch a legal demand | ComplianceManager, OrgAdmin, PlatformAdmin |
| GET | `/compliance/legal-demands` | List legal demands, filterable by site | ComplianceManager, OrgAdmin, PlatformAdmin |
| POST | `/compliance/legal-demands/{id}/respond` | Move a received demand to responding | ComplianceManager |
| POST | `/compliance/legal-demands/{id}/escalate` | Escalate a responding demand | ComplianceManager |
| POST | `/compliance/legal-demands/{id}/resolve` | Resolve a responding or escalated demand | ComplianceManager |
| POST | `/compliance/legal-demands/{id}/dismiss` | Dismiss a received demand | ComplianceManager |
| POST | `/compliance/monitoring-checks` | Record a monitoring sweep result | PlatformAdmin, AuditEngineer |
| GET | `/compliance/monitoring-checks` | List monitoring checks, filterable by site | PlatformAdmin, AuditEngineer, ComplianceManager, OrgAdmin |
| POST | `/compliance/training-enrollments` | Enroll a learner | OrgAdmin |
| GET | `/compliance/training-enrollments/{id}` | Fetch a training enrollment | OrgAdmin, PlatformAdmin |
| GET | `/compliance/training-enrollments` | List training enrollments, filterable by organization | OrgAdmin, PlatformAdmin |
| POST | `/compliance/training-enrollments/{id}/start` | Start a training enrollment | OrgAdmin |
| POST | `/compliance/training-enrollments/{id}/complete` | Complete a training enrollment | OrgAdmin |
| POST | `/compliance/training-enrollments/{id}/expire` | Expire an enrolled training record | PlatformAdmin |
| POST | `/compliance/certifications` | Grant a certification badge backed by an issued VPAT | ComplianceManager |
| GET | `/compliance/certifications/{id}` | Fetch a certification | ComplianceManager, OrgAdmin, PlatformAdmin, AuditEngineer |
| GET | `/compliance/certifications` | List certifications, filterable by site and/or VPAT report | ComplianceManager, OrgAdmin, PlatformAdmin, AuditEngineer |
| POST | `/compliance/certifications/{id}/revoke` | Revoke a granted certification | ComplianceManager |
| POST | `/compliance/certifications/{id}/expire` | Expire a granted certification past its expiry | PlatformAdmin |
| POST | `/compliance/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| GET | `/compliance/_clock/now` | Read the logical clock | PlatformAdmin, OrgAdmin, ComplianceManager, AuditEngineer, RemediationVendor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_FK_MISMATCH` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_SCAN_VERSION` | 412 |
| `ERR_STALE_SUBSCRIPTION_VERSION` | 412 |
| `ERR_SITE_BLOCKED_BY_LEGAL` | 409 |
| `ERR_SCAN_NOT_COMPLETED` | 409 |
| `ERR_VPAT_NOT_ISSUED` | 409 |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 |
| `ERR_EMPTY_FINDINGS` | 422 |
| `ERR_SCORE_BELOW_PASS` | 422 |
| `ERR_DUPLICATE_SITE_URL` | 409 |
| `ERR_SUBSCRIPTION_EXISTS` | 409 |
| `ERR_NOT_YET_EXPIRED` | 409 |
| `ERR_INVALID_FIELD_VALUE` | 422 |
| `ERR_MISSING_REQUIRED_FIELD` | 422 |
| `ERR_INVALID_PAGINATION` | 422 |
| `ERR_INVALID_DATETIME` | 422 |
| `ERR_SUPERSEDE_TARGET_NOT_REJECTED` | 409 |
