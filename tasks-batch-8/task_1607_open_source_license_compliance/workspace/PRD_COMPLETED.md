# Open Source License Compliance API — Product Requirements Document

## 1. Introduction

Modern software is assembled, not written from scratch: a single SaaS offering can pull in hundreds of open-source packages, each carrying its own license, its own obligations, and its own steady drip of newly disclosed vulnerabilities. For the open-source program office, the hard questions are never hypothetical. Which components ship inside the product a customer downloads? Which licenses force source disclosure when the same library is embedded in a hardware image rather than served over the network? Which restricted packages have legal sign-off, and which of those approvals lapse next month? And when an acquirer's diligence team asks for a complete accounting, can the company produce it in days rather than quarters?

This document specifies the Open Source License Compliance API, the system of record that answers those questions continuously instead of retroactively. The API manages the full compliance lifecycle: registering products and a canonical component catalogue, running dependency scans that resolve manifests into finalized bills of materials, classifying every discovered license against corporate policy, deriving per-component obligations from the product's distribution model, adjudicating restricted-license usage through a two-stage legal and engineering review, generating NOTICE files, and gating releases on the result. On top of that lifecycle it layers continuous monitoring — vulnerability intake with severity-based remediation SLAs, remediation planning and verification, and formal audit engagements for M&A, IPO readiness, customer due diligence, and regulatory inquiry — so that a product's compliance posture is always a computed fact, never a stale report.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts that hold uniformly across the API. Product-scoped resources are mounted under the `/oss-products` prefix; the global component and vulnerability catalogues live at `/oss-components` and `/oss-vulnerabilities`; and a small set of administrative, test-driving capabilities are mounted at `/_clock`, `/_vulnerability-feed`, and `/_scan-worker`.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an unrecognized role, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes seven roles: `ComplianceAnalyst`, `LegalCounsel`, `EngineeringManager`, `SecurityAnalyst`, `ReleaseManager`, `CISO`, and `PlatformAdmin`. Write operations are restricted to specific roles as described throughout §3 and summarized in §4; an authenticated user attempting an operation outside their role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). All read operations — every list and detail retrieval — are available to any authenticated role, denoted `Any` in the authorization column of §4.

Identity is uniform across roles. When `X-User-Role` is `ComplianceAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as the originating requester of a license approval request, which the withdrawal workflow later compares against) but does not compare it to any entity's `id`. The same rule holds individually for the remaining roles. For `LegalCounsel`, the identifier is recorded where a transition writes it, such as `legal_reviewer_id` on an approval request or `waived_by` on an obligation ticket. For `EngineeringManager`, it is recorded as `engineering_reviewer_id`. For `CISO`, it is recorded as `bypass_approved_by` on a bypassed release gate. For `SecurityAnalyst`, `ReleaseManager`, and `PlatformAdmin`, the identifier is not attached to any entity. No role's `X-User-ID` is ever compared to an entity's `id` for ownership.

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

List endpoints paginate via two query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Out-of-range values are clamped rather than rejected — a `limit` below 1 becomes 1 and above 100 becomes 100, a negative `offset` becomes 0 — and a non-integer value falls back to its default.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by `id` ascending.

List responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity and Common Properties

Every resource in the system — products, components, scans, bills of materials, BOM entries, approval requests, obligation tickets, vulnerabilities, findings, release gates, remediation plans, and audit engagements — carries a standard set of system-managed properties:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits recording the last modification; any change to the resource refreshes it.
- `version` — a system-managed integer that increments with every modification and underpins the optimistic concurrency rules of §2.8.

Recomputation of a derived field — a product's aggregate counts, a BOM's posture, a finding's deadline — is a modification like any other: it refreshes `updated_at` and increments `version` on the mutated resource. One naming note: on a Component, the client-supplied `version` denotes the upstream package version string (for example, the 4.17.21 inside a package URL), a different notion from the system-managed revision counter described above.

### 2.5. Request Evaluation Order

Incoming requests are validated against an ordered pipeline; a failure at any layer short-circuits all later layers, so the error a client receives always reflects the earliest failing check. The layers, evaluated in order, are:

1. **Authentication context** — the headers of §2.1 must be present and valid, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Malformed request payloads more generally are rejected with `ERR_INVALID_REQUEST` (HTTP 400).
2. **Authorization** — the acting role must be permitted the operation, else `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).
3. **Path existence** — every identifier in the URL is resolved left to right, else a 404 from the catalogue in §2.6.
4. **Product posture** — operations that require a non-blocked product (creating dependency scans, creating release gates, approving remediation plans) fail with `ERR_PRODUCT_BLOCKED` (HTTP 409) while the product's posture is `BLOCKED`.
5. **Target resource state** — state-transition operations verify the target sits in the required state, else a transition-specific 409 such as `ERR_SCAN_NOT_CANCELLABLE`, `ERR_GATE_NOT_EVALUABLE`, or `ERR_REQUEST_NOT_PENDING`.
6. **Prohibited-content safety** — a scan submission whose manifest contains prohibited components is refused with `ERR_PROHIBITED_COMPONENT` (HTTP 403).
7. **Notice-file presence** — release-gate evaluation requires the BOM's NOTICE file to exist, else `ERR_NOTICE_FILE_MISSING` (HTTP 409).
8. **Referential license compatibility** — a remediation plan's target component must exist, else `ERR_COMPONENT_NOT_FOUND` (HTTP 404); an existing target with an incompatible license is refused with `ERR_INCOMPATIBLE_LICENSE` (HTTP 400).
9. **Approval temporal validity** — an approval request relied upon past its `expiry_at` is no defense. At release-gate evaluation, any approval request covering the component of a `RESTRICTED` entry in the BOM under evaluation whose `expiry_at` lies in the past fails the evaluation with `ERR_APPROVAL_EXPIRED` (HTTP 409); the check compares `expiry_at` against the current logical time directly, so it fires for a granted-then-lapsed approval whether or not a clock sweep has already moved that request to `EXPIRED`. At BOM finalization a lapsed approval raises no error but counts as no approval at all, so the restricted entry is treated as lacking one.
10. **Engineering capacity** — a remediation plan whose `migration_effort_days` exceeds available engineering capacity is refused with `ERR_CAPACITY_EXCEEDED` (HTTP 402).

### 2.6. Hierarchical Resolution and Cross-Reference Retrieval

Endpoints that address nested resources validate path identifiers strictly left to right: the request is rejected with a 404 for the first path segment that does not resolve to an existing resource, before any later segment is examined. Each entity type carries its own not-found identifier — `ERR_PRODUCT_NOT_FOUND`, `ERR_COMPONENT_NOT_FOUND`, `ERR_SCAN_NOT_FOUND`, `ERR_BOM_NOT_FOUND`, `ERR_BOM_ENTRY_NOT_FOUND`, `ERR_APPROVAL_REQUEST_NOT_FOUND`, `ERR_OBLIGATION_TICKET_NOT_FOUND`, `ERR_VULNERABILITY_NOT_FOUND`, `ERR_VULNERABILITY_FINDING_NOT_FOUND`, `ERR_RELEASE_GATE_NOT_FOUND`, `ERR_REMEDIATION_PLAN_NOT_FOUND`, and `ERR_AUDIT_ENGAGEMENT_NOT_FOUND` — while `ERR_RESOURCE_NOT_FOUND` (HTTP 404) covers nested-path resolution failures generically.

Alongside the nested paths, the API exposes flat, cross-product retrieval for audit and reporting work. Filtered collection listings accept foreign-key and state filters as query parameters: dependency scans filter by `product_id` and `status`; bills of materials by `product_id`, `scan_id`, and `status`; BOM entries by `bom_id`, `component_id`, `parent_entry_id`, and `effective_classification`; license approval requests by `product_id`, `component_id`, `bom_entry_id`, and `status`; obligation tickets by `product_id`, `bom_entry_id`, `status`, and `obligation_type`; vulnerability findings by `product_id`, `bom_entry_id`, `vulnerability_id`, `status`, `severity`, and `remediation_component_id`; release gates by `product_id`, `bom_id`, and `gate_status`; remediation plans by `product_id`, `finding_id`, `target_component_id`, `verification_scan_id`, and `status`; and audit engagements by `product_id` and `status`; the vulnerability catalogue filters by `severity`. Standalone detail endpoints retrieve any single resource directly by its identifier — a product by `productId`, a component by `componentId`, a scan by `scanId`, a BOM by `bomId`, an entry by `entryId`, an approval request by `requestId`, a ticket by `ticketId`, a vulnerability by `vulnerabilityId`, a finding by `findingId`, a gate by `gateId`, a plan by `planId`, or an engagement by `engagementId` — without walking the product hierarchy.

### 2.7. License Classifications and the Compliance Posture Model

Every component's policy standing is expressed as one of five exact classification strings — `PERMISSIVE`, `WEAK_COPYLEFT`, `STRONG_COPYLEFT`, `RESTRICTED`, or `PROHIBITED` — and every product's health as one of three posture strings: `COMPLIANT`, `AT_RISK`, or `BLOCKED`. These vocabularies are closed: enum-valued fields always carry exactly one of their documented values.

Posture is a derived, hierarchical fact. A product's `compliance_posture` is computed from what its active bill of materials contains — open findings, pending approvals, unresolved violations — and its aggregate counts (`total_dependency_count`, `copyleft_dependency_count`, `restricted_dependency_count`, and `high_severity_vulnerability_count`) are recomputed whenever the underlying scans, entries, or findings change. Changes propagate upward without requiring a client request on the parent: a component reclassification recomputes every BOM entry that references it, then every affected BOM's posture, then every affected product's counts and posture. Each automatic posture change increments the product's `posture_version` and refreshes its `updated_at`, so observers holding a previously read version can detect that the ground has shifted beneath them.

### 2.8. Optimistic Concurrency Control

Two write operations participate in optimistic concurrency control, and each names its own expected-version field.

Creating a dependency scan accepts `expected_product_version`, the client's last-observed `posture_version` of the target product; the field is optional — when omitted, no version check is performed — and a non-integer value is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Scan creation itself advances the product's `posture_version`, so a second writer working from a stale read would otherwise silently interleave its work with state it never saw. If a supplied `expected_product_version` does not match the product's current `posture_version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), and no scan is created.

Evaluating a release gate accepts `expected_bom_version`, the client's last-observed `version` of the bill of materials being evaluated, under the same optional-and-validated rule: omitted skips the check, and a non-integer draws `ERR_INVALID_REQUEST` (HTTP 400). If a newer scan has superseded the BOM, or any other mutation has advanced its version since the client read it, the evaluation is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than producing a verdict against stale data.

Endpoints not named in this section do not accept a version field.

### 2.9. Logical Time and Scheduled Re-evaluation

All timestamps are ISO 8601 UTC, and all deadline arithmetic is performed in UTC. The server maintains a logical clock whose default value, before any adjustment, is 2026-08-01T00:00:00Z. A `PlatformAdmin` may move the logical clock by supplying a `to_iso8601` instant through the clock-setting capability; the response reports the now-current logical time in `current_utc`. Advancing the clock re-evaluates every time-dependent rule in the system as a single sweep: obligation tickets still `OPEN` or `IN_PROGRESS` whose `due_at` has passed move to `OVERDUE`, license approval requests past their expiry move to `EXPIRED`, a release gate still in `EVALUATING` completes to `FAILED` or `PASSED` per the `evaluation_result` recorded at evaluation, release gates past their `evaluation_expires_at` move to `EXPIRED` — including a gate that completes to `PASSED` in this sweep whose expiry has already passed — and vulnerability findings past their `remediation_deadline` are flagged (their `deadline_exceeded` marker is set true). Product postures are re-evaluated as part of the same sweep.

### 2.10. Numeric Precision, Hashes, and Evidence References

Percentages — `license_scan_coverage_pct` on a scan and `obligations_fulfilled_pct` on a release gate — are rounded to exactly two decimal places using round-half-up. All counts, including `blocking_findings_count`, `warning_findings_count`, `critical_findings_count`, and the product's aggregate dependency and vulnerability counts, are exact integers. Classification, obligation, and posture determinations are exact enum matches with no tolerance or approximation. Content-integrity fields — a scan's `raw_manifest_hash`, a BOM's `notice_file_hash`, and an audit's `report_hash` — are SHA-256 digests of the underlying artifact. Evidence of human work, such as obligation fulfillment or remediation verification, is captured as URI references supplied by the operator.

## 3. Business Logic & Workflows

### 3.1. Registering Products and Reading Their Posture

A `ComplianceAnalyst` onboards a product by supplying its `product_code` — a short unique code such as CRM-SUITE — a human-readable `product_name`, and the `distribution_model` that will shape every downstream obligation: one of `SaaS`, `ON_PREMISE`, `EMBEDDED`, or `MOBILE_APP`. Any other distribution value is rejected with `ERR_INVALID_DISTRIBUTION_MODEL` (HTTP 400). A new product starts with `compliance_posture` set to `COMPLIANT`, `posture_version` at 1, and all four aggregate counts at zero.

Thereafter the posture moves on its own, computed against the product's active bill of materials — its most recently created `FINALIZED` BOM, or its newest `DRAFT` while none has finalized. When an open `HIGH` or `CRITICAL` vulnerability is detected, or that active BOM contains a `RESTRICTED` entry lacking a non-expired approval, the product slides from `COMPLIANT` to `AT_RISK`; in the same sweep, every open release gate on the product has its `warning_findings_count` incremented. Escalation to `BLOCKED` happens when a `PROHIBITED` component lands in the active BOM — and that escalation is destructive: every open release gate on the product is moved to `FAILED` with `evaluation_result` of `FAIL`, every `PENDING` approval request moves to `EXPIRED`, and every `OPEN` or `IN_PROGRESS` obligation ticket whose `due_at` has already passed flips to `OVERDUE`. Recovery from `AT_RISK` to `COMPLIANT` is equally automatic once the active BOM holds no `PROHIBITED` entry, no `RESTRICTED` entry lacking a non-expired approval, and no entry whose findings still `OPEN`, `CONFIRMED`, or `MITIGATED` peak at `HIGH` or `CRITICAL` — and, for an `EMBEDDED` product, no `WEAK_COPYLEFT` entry either. Each of these moves increments the product's `posture_version`.

A `BLOCKED` product refuses new dependency scans, new release gates, and remediation-plan approvals with `ERR_PRODUCT_BLOCKED` (HTTP 409). The only way out is an explicit unblock by the `CISO`, submitted with a `justification` that is accepted without validation; unblocking a product that is not `BLOCKED` is likewise refused with `ERR_PRODUCT_BLOCKED` (HTTP 409). The unblock succeeds only while the product is `BLOCKED` and every `PROHIBITED` entry in the active BOM is covered by a remediation plan in `IN_PROGRESS` or `COMPLETED` that names the entry's component as its target or is attached to a finding on that entry; it lands the product back at `AT_RISK` — never directly at `COMPLIANT` — and increments `posture_version`.

### 3.2. Curating the Component Catalogue

The component catalogue is the global inventory every product draws from. A `ComplianceAnalyst` registers a component with its `package_url` in package-URL form (for example, pkg:npm/lodash@4.17.21), its `component_name`, the package `version`, and the `declared_license_spdx` taken from the package's own metadata; `source_download_url` and `copyright_notice` are optional at registration but become essential when copyleft obligations come due. A freshly registered component has `discovered_license_spdx` unset — it stays null until a scan completes — and no policy classification computed yet: registration never classifies the declared license, so `license_policy_classification` stays null until a scan completes and `effective_classification` likewise reports null for a component no scan has classified. The catalogue listing supports `package_url` and `effective_classification` filters for lookup work.

Classification is policy, not guesswork. When a scan completes, each component's `license_policy_classification` is computed from its `discovered_license_spdx` against a closed catalogue of eighteen recognized identifiers: MIT, BSD-2-Clause, BSD-3-Clause, ISC, Apache-2.0, Zlib, and Unlicense classify as `PERMISSIVE`; LGPL-2.1, LGPL-3.0, MPL-2.0, EPL-2.0, and CDDL-1.0 classify as `WEAK_COPYLEFT`; GPL-2.0, GPL-3.0, AGPL-3.0, and SSPL-1.0 classify as `STRONG_COPYLEFT`; CC-BY-NC-4.0, CC-BY-SA-4.0, and proprietary licenses that merely make source available classify as `RESTRICTED`; and WTFPL, unlicensed code, proprietary licenses without any grant, and SSPL-1.0 in a SaaS context classify as `PROHIBITED`. Context can tighten the verdict beyond the table: an AGPL-3.0 component inside a product whose `distribution_model` is `SaaS` is upgraded to `PROHIBITED`. A component whose discovered license is null or unrecognized does not fail open — the classifier falls back to `RESTRICTED` and lets the approval workflow decide.

`LegalCounsel` may override any classification by recording a `policy_override_classification` together with a `rationale` — stored as `override_rationale` — and a value outside the five classifications of §2.7 is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The `effective_classification` reported everywhere downstream is the override when one is set and the computed `license_policy_classification` otherwise. An override is a cross-aggregate event: every BOM entry referencing the component has its `obligation_determination` recomputed, every bill of materials containing the component has its `bom_posture` recomputed, and every product shipping the component has its counts updated and its posture re-evaluated.

### 3.3. Scanning Dependencies and Assembling the Bill of Materials

Scanning begins when a `ComplianceAnalyst` submits a dependency scan for a product, naming the `scan_tool` — one of `SYFT`, `ORT`, `SCANCODE`, `FOSSOLOGY`, or `COMMERCIAL_VENDOR_X`, with any other value rejected as `ERR_INVALID_SCAN_TOOL` (HTTP 400) — and the `scan_scope`: `FULL`, `INCREMENTAL`, `TRANSITIVE`, or `DIRECT_ONLY` (the scope may be omitted; any other value is rejected with `ERR_INVALID_REQUEST`, HTTP 400). The manifest itself is supplied as `manifest_components`, an array of package specs each carrying `package_url`, `component_name`, `version`, and `declared_license_spdx`, with `discovered_license_spdx`, `dependency_scope`, `is_direct`, `dependency_depth`, `source_download_url`, and `copyright_notice` optional per line. The request may carry `expected_product_version` under the optimistic-concurrency rule of §2.8, and it is refused outright with `ERR_PRODUCT_BLOCKED` when the product is `BLOCKED`. A submission whose manifest contains prohibited components — each line's declared license classified per §3.2 in the product's distribution context — is refused with `ERR_PROHIBITED_COMPONENT` (HTTP 403). The new scan lands in `QUEUED` with its `raw_manifest_hash` — the SHA-256 of the submitted manifest — recorded on the scan (every submission creates a new scan), and the product's `posture_version` is incremented at creation.

From there the pipeline drives itself. A worker pickup moves the scan from `QUEUED` to `PARSING`; a successfully parsed manifest moves it to `RESOLVING` with `components_discovered` set from the parsed contents. Resolution matches every package to a catalogue component by exact `package_url`, registering a new catalogue component for each unrecognized package, and moves the scan to `SCANNING_LICENSES`: `components_resolved` is set, a bill of materials is created in `DRAFT` status linked back to the scan through its `scan_id`, and one BOM entry is created per resolved component. License scanning then moves the scan to `SCORING`, populating each component's `discovered_license_spdx`, computing each component's `license_policy_classification` per §3.2, deriving every entry's `obligation_determination` from the product's `distribution_model` and the component's `effective_classification` per §3.4, and computing `license_scan_coverage_pct` — the number of resolved components whose `discovered_license_spdx` is populated, divided by `components_resolved`, multiplied by one hundred, rounded half-up to two decimal places, and recorded as 0.00 when nothing resolved at all. Coverage never blocks finalization in this revision: a scan completes and finalizes its bill of materials at any coverage percentage, and `ERR_LICENSE_SCAN_INCOMPLETE` is not raised.

Scoring completion moves the scan from `SCORING` to `COMPLETED` and detonates the cascade. The bill of materials transitions from `DRAFT` to `FINALIZED` with its `bom_posture` computed and `notice_file_generated` reset to false; the product's `total_dependency_count`, `copyleft_dependency_count`, and `restricted_dependency_count` are updated; any entry classified `PROHIBITED` drives the product's `compliance_posture` to `BLOCKED`; any `RESTRICTED` entry lacking an approval spawns a license approval request in `PENDING`; and an obligation ticket is created for every entry whose obligation determination is anything other than `NONE`. A parse, resolution, or license-scan error instead fails the scan — moving it from `PARSING`, `RESOLVING`, or `SCANNING_LICENSES` to `FAILED` — with worker failures reported as `ERR_SCAN_WORKER_ERROR` (HTTP 500). A `ComplianceAnalyst` may cancel a scan while it is still `QUEUED` or `PARSING`, moving it to `CANCELLED`; cancelling a scan that has progressed further is rejected with `ERR_SCAN_NOT_CANCELLABLE` (HTTP 409). For deterministic testing, a `PlatformAdmin` can process the next queued scan synchronously by naming its `scan_id`, driving it through every stage with all cascaded side effects applied; naming a scan that is not `QUEUED` is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and an unknown `scan_id` with `ERR_SCAN_NOT_FOUND` (HTTP 404).

Each bill of materials carries a `version_label` identifying the release it covers (for example, 2.4.0-rc1; taken from the scan request's `version_label`, defaulting to `scan-` plus the first eight characters of the scan id) alongside its derived tallies: `total_components`, `copyleft_components` counting the `WEAK_COPYLEFT` plus `STRONG_COPYLEFT` entries, `restricted_components` counting every `RESTRICTED` entry regardless of approval, and `prohibited_components` — whereas the product's `restricted_dependency_count` counts only `RESTRICTED` entries lacking a non-expired approval. Its `bom_posture` is a three-color summary: `RED` as soon as any entry is `PROHIBITED`; otherwise `YELLOW` when any entry is `RESTRICTED` without an approved license request or any entry's `vulnerability_severity_max` is `HIGH` or `CRITICAL` — a single such entry is enough to tip the color — and `GREEN` only when neither condition holds. Embedded products are held to a stricter line: for a product whose `distribution_model` is `EMBEDDED`, any `WEAK_COPYLEFT` entry also forces `YELLOW`. Posture escalates upward to the product: a `RED` BOM leaves its product `BLOCKED`, and a `YELLOW` BOM leaves it `AT_RISK`. When a newer BOM for the same product reaches `FINALIZED`, the older `FINALIZED` BOM becomes `SUPERSEDED`; every open release gate referencing it moves to `EXPIRED`, and every obligation ticket tied to its entries that is still `OPEN` or `IN_PROGRESS` flips to `OVERDUE`.

Inside a BOM, each entry records how its component participates: the `dependency_scope` (`RUNTIME`, `BUILD_TIME`, `TEST`, `OPTIONAL`, or `DEV`), whether it `is_direct` (true for a direct dependency, false for a transitive one), its `dependency_depth` in the dependency tree with zero marking direct dependencies, and — for transitive entries — the `parent_entry_id` chaining it to the entry that pulled it in, which is null for direct dependencies. The entry listing supports `effective_classification` and `obligation_determination` filters. Once obligations are in hand, a `ComplianceAnalyst` generates the BOM's NOTICE file: generation requires the BOM to be `FINALIZED` (otherwise `ERR_BOM_NOT_FINALIZED`, HTTP 409), sets `notice_file_generated` to true, computes the `notice_file_hash`, and fulfills every `NOTICE_FILE` obligation ticket on the BOM still `OPEN`, `IN_PROGRESS`, or `OVERDUE` in one stroke. Archiving moves a `FINALIZED` BOM to `ARCHIVED` and is permitted only when no open release gate references it and a newer `FINALIZED` BOM exists for the product; a BOM that is not `FINALIZED`, or one failing either condition, is rejected with `ERR_BOM_NOT_ARCHIVABLE` (HTTP 409).

### 3.4. License Obligations and the Restricted-Use Approval Workflow

Obligation determination is where classification meets distribution. Each BOM entry's `obligation_determination` is derived from the component's `effective_classification`, the product's `distribution_model`, and the entry's `dependency_scope`, evaluated in a fixed order. A `PROHIBITED` classification always yields `PROHIBITED_USE`. Entries in `TEST` or `DEV` scope carry no obligation at all — `NONE` — regardless of license. A `PERMISSIVE` component owes `ATTRIBUTION_ONLY`. A `WEAK_COPYLEFT` component owes `ATTRIBUTION_ONLY` inside a `SaaS` product and a source offer everywhere else — the product must stand ready to provide the library's corresponding source, tracked through a ticket of type `SOURCE_OFFER`. A `STRONG_COPYLEFT` component owes `FULL_SOURCE_DISCLOSURE` when it is AGPL-3.0 inside a `SaaS` product or whenever the product is a `MOBILE_APP`, and `SOURCE_DISCLOSURE` under `ON_PREMISE` or `EMBEDDED` distribution — the same AGPL-3.0 library that demands full source disclosure in a hosted service demands only source disclosure in an on-premise install — and a `STRONG_COPYLEFT` component that is not AGPL-3.0 inside a `SaaS` product owes `SOURCE_DISCLOSURE` as well. A `RESTRICTED` component requires approval before use and carries `SOURCE_DISCLOSURE` regardless of approval state.

Every entry whose determination is not `NONE` spawns exactly one obligation ticket at scan completion, created only when the entry has none yet. A ticket's `obligation_type` is one of `ATTRIBUTION`, `SOURCE_OFFER`, `SOURCE_DELIVERY`, `LICENSE_TEXT`, `NOTICE_FILE`, or `COPYLEFT_COMPLIANCE`, mapped from the entry's determination — `ATTRIBUTION_ONLY` spawns `ATTRIBUTION`, `SOURCE_OFFER` spawns `SOURCE_OFFER`, `SOURCE_DISCLOSURE` spawns `SOURCE_DELIVERY`, `FULL_SOURCE_DISCLOSURE` spawns `COPYLEFT_COMPLIANCE`, and `PROHIBITED_USE` spawns `LICENSE_TEXT` — and its `due_at` is set thirty days after its creation. Tickets begin `OPEN`; a `ComplianceAnalyst` starts work, moving a ticket from `OPEN` to `IN_PROGRESS` — starting one that is not `OPEN` is rejected with `ERR_TICKET_NOT_OPEN` (HTTP 409). Fulfillment requires a `fulfillment_evidence_uri` (omitting it draws `ERR_INVALID_REQUEST`, HTTP 400) and moves the ticket from `IN_PROGRESS` to `FULFILLED`, with a ticket in any other state refused as `ERR_TICKET_NOT_IN_PROGRESS` (HTTP 409). `LegalCounsel` alone may waive a ticket, supplying a `waiver_reason` (omitting it draws `ERR_INVALID_REQUEST`); waiving is allowed from `OPEN` or `IN_PROGRESS`, records the acting counsel in `waived_by`, and any other state is rejected with `ERR_TICKET_NOT_WAIVABLE` (HTTP 409). Both fulfillment and waiver re-evaluate the entry: an entry's `obligation_fulfilled` flag begins false and becomes true when every ticket linked to the entry is `FULFILLED` or `WAIVED`, and once every ticket on a BOM is resolved the BOM becomes eligible for notice-file generation. A ticket whose `due_at` passes while it is still `OPEN` or `IN_PROGRESS` moves to `OVERDUE` automatically, and the product's `compliance_posture` is re-evaluated in response.

Restricted components travel through a two-stage approval. The approval request — created in `PENDING` when a completing scan surfaces a restricted entry without approval, at most one live request per entry (a new one is spawned only when none for that entry is `PENDING`, in `LEGAL_REVIEW` or `ENGINEERING_REVIEW`, or `APPROVED`) — links the product, the component, and the triggering BOM entry, and records the requester's business case in `request_reason` together with a `risk_acknowledgment` flag confirming the requester accepts the legal exposure; a scan-spawned request carries `request_reason` null, `risk_acknowledgment` false, and no recorded requester. `LegalCounsel` takes the request from `PENDING` to `LEGAL_REVIEW`, recording themselves as `legal_reviewer_id`; assigning legal review on a request that is not `PENDING` fails with `ERR_REQUEST_NOT_PENDING` (HTTP 409). The legal decision accepts a `legal_decision` of `APPROVE`, `REJECT`, or `CONDITIONAL` — anything else is `ERR_INVALID_LICENSE_DECISION` (HTTP 400) — and a request not in `LEGAL_REVIEW` is refused with `ERR_REQUEST_NOT_IN_LEGAL_REVIEW` (HTTP 409). A legal `REJECT` ends the matter immediately: the request becomes `REJECTED` with `final_decision` set to `REJECTED`. A legal `APPROVE` or `CONDITIONAL` — the latter recording its `legal_conditions` — advances the request to `ENGINEERING_REVIEW`.

Engineering then decides with an `engineering_decision` of `APPROVE` or `REJECT`; any other value draws `ERR_INVALID_ENGINEERING_DECISION` (HTTP 400), and a request not in `ENGINEERING_REVIEW` draws `ERR_REQUEST_NOT_IN_ENGINEERING_REVIEW` (HTTP 409). The deciding manager is recorded as `engineering_reviewer_id`. Engineering approval is only valid atop a legal `APPROVE` or `CONDITIONAL`; on approval the request becomes `APPROVED` with `final_decision` set to `APPROVED`, `decision_effective_at` stamped at the decision moment, `expiry_at` set ninety days after approval, and the linked BOM entry's `obligation_fulfilled` marked true; if the product was `BLOCKED` on account of this request, its posture is re-evaluated at that point. An engineering `REJECT` lands the request at `REJECTED` with `final_decision` set to `REJECTED`. The originating analyst may withdraw a request while it is `PENDING` or in `LEGAL_REVIEW`, moving it to `WITHDRAWN`; withdrawal is restricted to the original requester when one is recorded — scan-spawned requests record none, so any analyst may withdraw them — and an attempt from any other state is rejected with `ERR_REQUEST_NOT_WITHDRAWABLE` (HTTP 409). Requests do not live forever: a `PENDING` request expires automatically — its `final_decision` becoming `EXPIRED` — when the product becomes `BLOCKED` or when the request has been open for more than thirty days, and an approval invoked past its `expiry_at` is no defense: at gate evaluation it surfaces `ERR_APPROVAL_EXPIRED` (HTTP 409) per §2.5, while at BOM finalization it simply does not count as an approval.

### 3.5. Vulnerability Intake, Triage, and Posture Escalation

A `SecurityAnalyst` registers vulnerabilities as the CVE feed delivers them, supplying the `cve_id` (for example, CVE-2024-12345), a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`, the `cvss_score` — a CVSS v3.1 base score between 0.0 and 10.0 — the `published_at` timestamp, and the `affected_package_url` pattern; a missing field, an unrecognized severity, or a score outside that range is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Where a fix exists, `fixed_in_version` names the first safe version and stays null while the vulnerability is unfixed; where the fixed version changes the license, `license_change_flag` is set and `new_license_spdx` names the incoming license. Registration propagates immediately: whenever the pattern equals a catalogued component's `package_url` exactly, a vulnerability finding is created for every BOM entry that ships the component — in a BOM of any status, at most one finding per vulnerability and entry — and each affected product's `high_severity_vulnerability_count` is updated (counting findings still `OPEN`, `CONFIRMED`, or `MITIGATED` whose vulnerability is `HIGH` or `CRITICAL`) with its posture re-evaluated. For deterministic testing, a `PlatformAdmin` can inject the very same payload through the feed-simulation capability, which bypasses feed authentication.

Each finding is born `OPEN` and stamped with `detected_at`. Its remediation SLA attaches at confirmation: the `remediation_deadline` is then computed as `detected_at` plus seven days for `CRITICAL`, thirty days for `HIGH`, ninety days for `MEDIUM`, and one hundred eighty days for `LOW`. Two accelerators each compress the deadline to whichever instant comes first. When the vulnerability's `license_change_flag` is set, the deadline is capped at `detected_at` plus fourteen days regardless of severity. And while the product sits `BLOCKED`, the deadline is capped at three days from the present moment.

Confirmation is the analyst's first act: an `OPEN` finding becomes `CONFIRMED`, with a finding in any other state rejected as `ERR_FINDING_NOT_OPEN` (HTTP 409). Confirming a `CRITICAL` finding pushes a `COMPLIANT` product's posture to `AT_RISK`. From `CONFIRMED`, the analyst may record mitigation — moving the finding to `MITIGATED`, with a finding not in `CONFIRMED` refused as `ERR_FINDING_NOT_CONFIRMED` (HTTP 409). Once remediation lands, the analyst verifies it by supplying a `verification_evidence_uri` (omitting it draws `ERR_INVALID_REQUEST`, HTTP 400). Verification requires the finding to be `CONFIRMED` or `MITIGATED` and requires the finding's `remediation_status` to be `VERIFIED` by the remediation workflow of §3.6 — failing either condition is `ERR_FINDING_NOT_REMEDIABLE` (HTTP 409). A successful verification moves the finding to `REMEDIATED`, recomputes the entry's `vulnerability_severity_max` (the worst severity among the entry's findings still `OPEN`, `CONFIRMED`, or `MITIGATED`, else `NONE`), decrements the product's `high_severity_vulnerability_count`, and — when no `CRITICAL` or `HIGH` findings remain — returns the product's posture to `COMPLIANT`. Two terminal off-ramps exist: an analyst may mark an `OPEN` finding `FALSE_POSITIVE`, and the `CISO` may accept the risk on an `OPEN` or `CONFIRMED` finding by supplying a `risk_acceptance_rationale` (omitting it draws `ERR_INVALID_REQUEST`), moving it to `WONT_FIX`; from any other state both attempts are rejected with `ERR_FINDING_NOT_OPEN` (HTTP 409), and both transitions recompute the product's counts. Throughout, the finding's representation embeds the parent vulnerability's `severity` and `cve_id`; its `remediation_component_id` stays null — the replacement component selected for remediation is recorded on the remediation plan's `target_component_id` — and its `remediation_status` tracks that work across `NOT_STARTED`, `IN_PROGRESS`, `VERIFIED`, and `FAILED`.

### 3.6. Planning and Verifying Remediation

Remediation is planned work, not a vibe. An `EngineeringManager` opens a remediation plan against a finding by naming the `finding_id`, a `plan_type` of `UPGRADE`, `REPLACE`, `PATCH`, `MITIGATE_CONFIG`, or `ACCEPT_RISK` — anything else is rejected with `ERR_INVALID_PLAN_TYPE` (HTTP 400) — and an estimate in `migration_effort_days` person-days; for `UPGRADE` and `REPLACE` work the plan also names the `target_component_id` to migrate toward and the `target_version` to reach. Two business guards fire at creation: a named target component must exist — an unknown one is refused with `ERR_COMPONENT_NOT_FOUND` (HTTP 404) — and, for `UPGRADE` or `REPLACE` plans, must carry a compatible license, with a `PROHIBITED` or otherwise incompatible target refused as `ERR_INCOMPATIBLE_LICENSE` (HTTP 400); and the estimated effort must fit within available engineering capacity — 365 person-days — else `ERR_CAPACITY_EXCEEDED` (HTTP 402). A new plan starts `PROPOSED`, with `license_compatibility_verified` computed whenever a target component is named.

Approval is where the license guard bites again: approving a plan requires it to be `PROPOSED` — anything else draws `ERR_PLAN_NOT_PROPOSED` (HTTP 409) — it is refused outright while the product is `BLOCKED` per the posture layer of §2.5, and for `UPGRADE` or `REPLACE` plans it requires the target component's license to be `PERMISSIVE` or `WEAK_COPYLEFT`. Approval moves the plan to `APPROVED`, computes `license_compatibility_verified`, and flips the linked finding's `remediation_status` to `IN_PROGRESS`. Starting work moves an `APPROVED` plan to `IN_PROGRESS`; a plan in any other state draws `ERR_PLAN_NOT_APPROVED` (HTTP 409). Completion demands evidence: the manager supplies a `verification_scan_id` (omitting it draws `ERR_INVALID_REQUEST`, HTTP 400; an unknown scan draws `ERR_SCAN_NOT_FOUND`, HTTP 404) referencing a `COMPLETED` scan that shows the vulnerability absent (a scan not `COMPLETED` draws `ERR_INVALID_REQUEST`), moving an `IN_PROGRESS` plan to `COMPLETED` — any other state is `ERR_PLAN_NOT_IN_PROGRESS` (HTTP 409) — stamping `actual_completion_at` at that moment and advancing the finding's `remediation_status` to `VERIFIED`, which is exactly what §3.5's remediation verification waits upon. A `PROPOSED` plan may instead be rejected outright, becoming `REJECTED`. A plan that has been approved or started may be abandoned, becoming `ABANDONED` with the finding's `remediation_status` dropped back to `NOT_STARTED`; abandoning from any other state is rejected with `ERR_PLAN_NOT_ABANDONABLE` (HTTP 409).

### 3.7. Gating a Release

Release decisions are made against a finalized bill of materials, never against a feeling. A `ReleaseManager` opens a release gate by naming the `bom_id` to evaluate and the `release_version` intended to ship (both required, else `ERR_INVALID_REQUEST`, HTTP 400). Creation is refused unless the referenced BOM is `FINALIZED` — surfacing `ERR_BOM_NOT_FINALIZED` (HTTP 409) — and refused with `ERR_PRODUCT_BLOCKED` (HTTP 409) while the product is `BLOCKED`. The gate is born `OPEN`, and its `notice_file_attached` flag tracks whether the BOM's NOTICE file has been generated and attached.

Evaluation is the gate's reason to exist. The manager triggers it carrying `expected_bom_version` under the optimistic-concurrency rule of §2.8; a BOM whose version has advanced since the client last read it fails the request with `ERR_STALE_VERSION` (HTTP 412). Evaluation requires the gate to be `OPEN` and the BOM to be `FINALIZED` — otherwise `ERR_GATE_NOT_EVALUABLE` (HTTP 409) — and requires the NOTICE file to be attached — satisfied by the BOM's `notice_file_generated` or the gate's own `notice_file_attached` — otherwise `ERR_NOTICE_FILE_MISSING` (HTTP 409). The evaluation itself computes three numbers. The `blocking_findings_count` tallies entries whose `effective_classification` is `PROHIBITED` plus `CRITICAL` findings on the BOM's own entries still `OPEN` or `CONFIRMED`. The `warning_findings_count` tallies `RESTRICTED` entries lacking an approved license request plus `HIGH` findings on the BOM's own entries still `OPEN` or `CONFIRMED`. The `obligations_fulfilled_pct` is the share of the BOM's obligation tickets in `FULFILLED` or `WAIVED` status — fulfilled plus waived, divided by the total ticket count, multiplied by one hundred, rounded half-up to two decimal places (a BOM with no tickets scores 100.00). The verdict ladder is strict and ordered: any blocking finding fails the gate; obligations below one hundred percent fail it; more than three warnings fail it; between one and three warnings inclusive yield a `CONDITIONAL_PASS`; and a completely clean board yields a `PASS`. Evaluation records the verdict on the gate and moves it from `OPEN` to `EVALUATING` with `notice_file_attached` set true: a failing verdict records `evaluation_result` of `FAIL`, while a passing verdict records `PASS` or `CONDITIONAL_PASS` as the ladder dictates and sets `evaluation_expires_at` thirty days out. The gate remains `EVALUATING` — counts and verdict visible, and bypassable by the CISO as described below — until the system completes the move from `EVALUATING` to `FAILED` or `PASSED` per the recorded verdict, which it does as part of the clock sweep of §2.9; a gate that completes to `PASSED` in a sweep whose current time is already past `evaluation_expires_at` expires in that same sweep. A gate in `OPEN` or `EVALUATING` counts as an open gate for the posture cascades of §3.1, the supersede expiry and archive guard of §3.3; the fourteen-day expiry below applies to `OPEN` gates only. Two contexts forbid conditional passes entirely: for an `EMBEDDED` product, or while an audit engagement is active on the product (in `INITIATED`, `SCOPING`, `DATA_COLLECTION`, `ANALYSIS`, or `REPORT_DRAFT`), the conditional ceiling drops to zero and any warning at all fails the gate.

When the business cannot wait, the `CISO` may bypass a gate that is `EVALUATING`, supplying a `bypass_reason` (required, else `ERR_INVALID_REQUEST`, HTTP 400); bypass is refused — with `ERR_GATE_NOT_BYPASSABLE` (HTTP 409) — when the gate is in any other state or the product is `BLOCKED`. A bypassed gate records `evaluation_result` of `CONDITIONAL_PASS`, stamps `bypass_approved_by` with the acting CISO, and lives on a shorter leash: `evaluation_expires_at` is set only seven days out rather than thirty. Gates expire on their own. An `OPEN` gate moves to `EXPIRED` when its BOM is superseded or when it has sat open for more than fourteen days, and an `EVALUATING` gate whose BOM is superseded expires alongside it. A `PASSED` or `BYPASSED` gate moves to `EXPIRED` the moment its `evaluation_expires_at` passes. Product posture changes wash through the gates as §3.1 describes: a slide to `AT_RISK` increments every open gate's `warning_findings_count`, while a slide to `BLOCKED` fails every open gate outright.

### 3.8. Audit Engagements and the Passage of Time

When a third party comes asking, the open-source office responds through a formal engagement. A `ComplianceAnalyst` opens one by naming the `audit_type` — `M_AND_A`, `IPO_READINESS`, `CUSTOMER_DUE_DILIGENCE`, or `REGULATORY_INQUIRY` (any other value draws `ERR_INVALID_REQUEST`, HTTP 400) — the `requesting_party`, a `scope_description` covering the full product or specific versions, and a `target_completion_at` date (a missing field draws `ERR_INVALID_REQUEST`). The engagement is born `INITIATED` and walks a strict corridor: scoping moves it from `INITIATED` to `SCOPING` (any other start state is `ERR_ENGAGEMENT_NOT_INITIATED`, HTTP 409); data collection moves it from `SCOPING` to `DATA_COLLECTION` (else `ERR_ENGAGEMENT_NOT_SCOPING`, HTTP 409) and takes a snapshot of every `FINALIZED` BOM for the product together with a snapshot of every vulnerability finding still `OPEN`, `CONFIRMED`, or `MITIGATED`; analysis moves it from `DATA_COLLECTION` to `ANALYSIS` (else `ERR_ENGAGEMENT_NOT_DATA_COLLECTION`, HTTP 409); drafting the report moves it from `ANALYSIS` to `REPORT_DRAFT` (else `ERR_ENGAGEMENT_NOT_ANALYSIS`, HTTP 409), populating `findings_summary` and computing `critical_findings_count`; and finalization is `LegalCounsel`'s signature, moving the engagement from `REPORT_DRAFT` to `REPORT_FINAL` (else `ERR_ENGAGEMENT_NOT_REPORT_DRAFT`, HTTP 409), stamping `actual_completion_at` and computing the `report_hash` of the final report. An engagement may be cancelled while it is `INITIATED`, `SCOPING`, or `DATA_COLLECTION`, moving it to `CANCELLED`; cancelling one that has progressed into analysis or beyond is rejected with `ERR_ENGAGEMENT_NOT_CANCELLABLE` (HTTP 409). While an engagement is active on a product, release-gate evaluation tightens as §3.7 describes: no conditional pass is available.

The critical-findings count on a drafted report aggregates four streams: every `PROHIBITED` entry in any `FINALIZED` BOM for the product, every `CRITICAL` vulnerability finding still `OPEN` or `CONFIRMED`, every `RESTRICTED` entry whose approval is expired or missing, and every obligation ticket that is `OVERDUE` with its `due_at` more than thirty days in the past.

Time itself is an actor in this system, and it is steered deliberately. The logical clock starts at 2026-08-01T00:00:00Z and advances only when a `PlatformAdmin` sets it to a supplied `to_iso8601` instant, with the response confirming the new `current_utc`. Advancing the clock is a system-wide sweep: obligation tickets still `OPEN` or `IN_PROGRESS` past `due_at` move to `OVERDUE`, approval requests past expiry move to `EXPIRED`, a gate still in `EVALUATING` completes to `FAILED` or `PASSED` per its recorded verdict, gates past `evaluation_expires_at` move to `EXPIRED` — including one that completes to `PASSED` in this sweep whose expiry has already passed — findings past `remediation_deadline` are flagged, and product postures are re-evaluated accordingly. A second administrative capability processes the next queued dependency scan synchronously when handed its `scan_id`, and a third simulates CVE feed ingestion with the full registration payload of §3.5 while bypassing feed authentication.

## 4. Endpoint Definitions

Operations that create new resources — a product, a component, a dependency scan, a vulnerability, a release gate, a remediation plan, or an audit engagement — return a `201 Created` status code. Operations that modify an existing resource, including every state transition, return a `200 OK` status code, as do the administrative capabilities under `/_clock`, `/_vulnerability-feed`, and `/_scan-worker`. The table below is a summary only; request bodies, response payloads, preconditions, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/oss-products` | Create a new Product | ComplianceAnalyst |
| GET | `/oss-products` | List all Products | Any |
| GET | `/oss-products/{productId}` | Get a specific Product | Any |
| POST | `/oss-products/{productId}/unblock` | Request unblock of a BLOCKED product | CISO |
| POST | `/oss-components` | Create a new Component | ComplianceAnalyst |
| GET | `/oss-components` | List all Components | Any |
| GET | `/oss-components/{componentId}` | Get a specific Component | Any |
| POST | `/oss-components/{componentId}/override-classification` | Override license policy classification | LegalCounsel |
| POST | `/oss-products/{productId}/dependency-scans` | Create a new DependencyScan | ComplianceAnalyst |
| GET | `/oss-products/{productId}/dependency-scans` | List DependencyScans for a Product | Any |
| GET | `/oss-products/{productId}/dependency-scans/{scanId}` | Get a specific DependencyScan | Any |
| POST | `/oss-products/{productId}/dependency-scans/{scanId}/cancel` | Cancel a QUEUED or PARSING scan | ComplianceAnalyst |
| GET | `/oss-products/{productId}/boms` | List BillOfMaterials for a Product | Any |
| GET | `/oss-products/{productId}/boms/{bomId}` | Get a specific BillOfMaterials | Any |
| GET | `/oss-products/{productId}/boms/{bomId}/entries` | List BomEntries for a BOM | Any |
| GET | `/oss-products/{productId}/boms/{bomId}/entries/{entryId}` | Get a specific BomEntry | Any |
| POST | `/oss-products/{productId}/boms/{bomId}/generate-notice` | Generate NOTICE file for BOM | ComplianceAnalyst |
| POST | `/oss-products/{productId}/boms/{bomId}/archive` | Archive a FINALIZED BOM | ComplianceAnalyst |
| GET | `/oss-products/{productId}/license-approvals` | List LicenseApprovalRequests for a Product | Any |
| GET | `/oss-products/{productId}/license-approvals/{requestId}` | Get a specific LicenseApprovalRequest | Any |
| POST | `/oss-products/{productId}/license-approvals/{requestId}/assign-legal` | Assign legal reviewer | LegalCounsel |
| POST | `/oss-products/{productId}/license-approvals/{requestId}/legal-decision` | Record legal decision | LegalCounsel |
| POST | `/oss-products/{productId}/license-approvals/{requestId}/engineering-decision` | Record engineering decision | EngineeringManager |
| POST | `/oss-products/{productId}/license-approvals/{requestId}/withdraw` | Withdraw approval request | ComplianceAnalyst |
| GET | `/oss-products/{productId}/obligation-tickets` | List ObligationTickets for a Product | Any |
| GET | `/oss-products/{productId}/obligation-tickets/{ticketId}` | Get a specific ObligationTicket | Any |
| POST | `/oss-products/{productId}/obligation-tickets/{ticketId}/start` | Start work on ticket | ComplianceAnalyst |
| POST | `/oss-products/{productId}/obligation-tickets/{ticketId}/fulfill` | Mark ticket fulfilled | ComplianceAnalyst |
| POST | `/oss-products/{productId}/obligation-tickets/{ticketId}/waive` | Waive obligation | LegalCounsel |
| POST | `/oss-vulnerabilities` | Register a new Vulnerability (CVE feed ingestion) | SecurityAnalyst |
| GET | `/oss-vulnerabilities` | List all Vulnerabilities | Any |
| GET | `/oss-vulnerabilities/{vulnerabilityId}` | Get a specific Vulnerability | Any |
| GET | `/oss-products/{productId}/vulnerability-findings` | List VulnerabilityFindings for a Product | Any |
| GET | `/oss-products/{productId}/vulnerability-findings/{findingId}` | Get a specific VulnerabilityFinding | Any |
| POST | `/oss-products/{productId}/vulnerability-findings/{findingId}/confirm` | Confirm a vulnerability finding | SecurityAnalyst |
| POST | `/oss-products/{productId}/vulnerability-findings/{findingId}/mitigate` | Mark finding as mitigated | SecurityAnalyst |
| POST | `/oss-products/{productId}/vulnerability-findings/{findingId}/verify-remediation` | Verify remediation complete | SecurityAnalyst |
| POST | `/oss-products/{productId}/vulnerability-findings/{findingId}/mark-false-positive` | Mark finding as false positive | SecurityAnalyst |
| POST | `/oss-products/{productId}/vulnerability-findings/{findingId}/wont-fix` | Accept risk and mark wont-fix | CISO |
| POST | `/oss-products/{productId}/release-gates` | Create a ReleaseGate | ReleaseManager |
| GET | `/oss-products/{productId}/release-gates` | List ReleaseGates for a Product | Any |
| GET | `/oss-products/{productId}/release-gates/{gateId}` | Get a specific ReleaseGate | Any |
| POST | `/oss-products/{productId}/release-gates/{gateId}/evaluate` | Evaluate release gate | ReleaseManager |
| POST | `/oss-products/{productId}/release-gates/{gateId}/bypass` | Emergency bypass of failed gate | CISO |
| POST | `/oss-products/{productId}/remediation-plans` | Create a RemediationPlan | EngineeringManager |
| GET | `/oss-products/{productId}/remediation-plans` | List RemediationPlans for a Product | Any |
| GET | `/oss-products/{productId}/remediation-plans/{planId}` | Get a specific RemediationPlan | Any |
| POST | `/oss-products/{productId}/remediation-plans/{planId}/approve` | Approve remediation plan | EngineeringManager |
| POST | `/oss-products/{productId}/remediation-plans/{planId}/start` | Start remediation work | EngineeringManager |
| POST | `/oss-products/{productId}/remediation-plans/{planId}/complete` | Mark remediation complete | EngineeringManager |
| POST | `/oss-products/{productId}/remediation-plans/{planId}/reject` | Reject remediation plan | EngineeringManager |
| POST | `/oss-products/{productId}/remediation-plans/{planId}/abandon` | Abandon remediation plan | EngineeringManager |
| POST | `/oss-products/{productId}/audit-engagements` | Create an AuditEngagement | ComplianceAnalyst |
| GET | `/oss-products/{productId}/audit-engagements` | List AuditEngagements for a Product | Any |
| GET | `/oss-products/{productId}/audit-engagements/{engagementId}` | Get a specific AuditEngagement | Any |
| POST | `/oss-products/{productId}/audit-engagements/{engagementId}/start-scoping` | Start scoping phase | ComplianceAnalyst |
| POST | `/oss-products/{productId}/audit-engagements/{engagementId}/start-data-collection` | Start data collection phase | ComplianceAnalyst |
| POST | `/oss-products/{productId}/audit-engagements/{engagementId}/start-analysis` | Start analysis phase | ComplianceAnalyst |
| POST | `/oss-products/{productId}/audit-engagements/{engagementId}/draft-report` | Draft audit report | ComplianceAnalyst |
| POST | `/oss-products/{productId}/audit-engagements/{engagementId}/finalize-report` | Finalize audit report | LegalCounsel |
| POST | `/oss-products/{productId}/audit-engagements/{engagementId}/cancel` | Cancel audit engagement | ComplianceAnalyst |
| POST | `/_clock/set_current_utc` | Set logical clock for time-based testing | PlatformAdmin |
| POST | `/_vulnerability-feed/simulate` | Simulate CVE feed ingestion | PlatformAdmin |
| POST | `/_scan-worker/process-next` | Process next queued DependencyScan synchronously | PlatformAdmin |
| GET | `/oss-products/products/{productId}` | Get a specific Product by ID | Any |
| GET | `/oss-products/components/{componentId}` | Get a specific Component by ID | Any |
| GET | `/oss-products/dependency-scans/{scanId}` | Get a specific DependencyScan by ID | Any |
| GET | `/oss-products/boms/{bomId}` | Get a specific BillOfMaterials by ID | Any |
| GET | `/oss-products/bom-entries/{entryId}` | Get a specific BomEntry by ID | Any |
| GET | `/oss-products/license-approvals/{requestId}` | Get a specific LicenseApprovalRequest by ID | Any |
| GET | `/oss-products/obligation-tickets/{ticketId}` | Get a specific ObligationTicket by ID | Any |
| GET | `/oss-products/vulnerability-findings/{findingId}` | Get a specific VulnerabilityFinding by ID | Any |
| GET | `/oss-products/release-gates/{gateId}` | Get a specific ReleaseGate by ID | Any |
| GET | `/oss-products/remediation-plans/{planId}` | Get a specific RemediationPlan by ID | Any |
| GET | `/oss-products/audit-engagements/{engagementId}` | Get a specific AuditEngagement by ID | Any |
| GET | `/oss-products/dependency-scans` | List DependencyScans with product filter | Any |
| GET | `/oss-products/boms` | List BillOfMaterials with product or scan filter | Any |
| GET | `/oss-products/bom-entries` | List BomEntries with bom, component, or parent-entry filter | Any |
| GET | `/oss-products/license-approvals` | List LicenseApprovalRequests with product, component, or entry filter | Any |
| GET | `/oss-products/obligation-tickets` | List ObligationTickets with product or entry filter | Any |
| GET | `/oss-products/vulnerability-findings` | List VulnerabilityFindings with product, entry, or vulnerability filter | Any |
| GET | `/oss-products/release-gates` | List ReleaseGates with product or BOM filter | Any |
| GET | `/oss-products/remediation-plans` | List RemediationPlans with product, finding, target, or scan filter | Any |
| GET | `/oss-products/audit-engagements` | List AuditEngagements with product filter | Any |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status. Trigger conditions are defined by the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_DISTRIBUTION_MODEL` | 400 Bad Request |
| `ERR_INVALID_SCAN_TOOL` | 400 Bad Request |
| `ERR_INVALID_LICENSE_DECISION` | 400 Bad Request |
| `ERR_INVALID_ENGINEERING_DECISION` | 400 Bad Request |
| `ERR_INVALID_PLAN_TYPE` | 400 Bad Request |
| `ERR_INCOMPATIBLE_LICENSE` | 400 Bad Request |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_COMPONENT_NOT_FOUND` | 404 Not Found |
| `ERR_SCAN_NOT_FOUND` | 404 Not Found |
| `ERR_BOM_NOT_FOUND` | 404 Not Found |
| `ERR_BOM_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_APPROVAL_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_OBLIGATION_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_VULNERABILITY_NOT_FOUND` | 404 Not Found |
| `ERR_VULNERABILITY_FINDING_NOT_FOUND` | 404 Not Found |
| `ERR_RELEASE_GATE_NOT_FOUND` | 404 Not Found |
| `ERR_REMEDIATION_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_ENGAGEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_BLOCKED` | 409 Conflict |
| `ERR_SCAN_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_BOM_NOT_FINALIZED` | 409 Conflict |
| `ERR_BOM_NOT_ARCHIVABLE` | 409 Conflict |
| `ERR_REQUEST_NOT_PENDING` | 409 Conflict |
| `ERR_REQUEST_NOT_IN_LEGAL_REVIEW` | 409 Conflict |
| `ERR_REQUEST_NOT_IN_ENGINEERING_REVIEW` | 409 Conflict |
| `ERR_REQUEST_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_TICKET_NOT_OPEN` | 409 Conflict |
| `ERR_TICKET_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_TICKET_NOT_WAIVABLE` | 409 Conflict |
| `ERR_FINDING_NOT_OPEN` | 409 Conflict |
| `ERR_FINDING_NOT_CONFIRMED` | 409 Conflict |
| `ERR_FINDING_NOT_REMEDIABLE` | 409 Conflict |
| `ERR_GATE_NOT_EVALUABLE` | 409 Conflict |
| `ERR_GATE_NOT_BYPASSABLE` | 409 Conflict |
| `ERR_PLAN_NOT_PROPOSED` | 409 Conflict |
| `ERR_PLAN_NOT_APPROVED` | 409 Conflict |
| `ERR_PLAN_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_PLAN_NOT_ABANDONABLE` | 409 Conflict |
| `ERR_ENGAGEMENT_NOT_INITIATED` | 409 Conflict |
| `ERR_ENGAGEMENT_NOT_SCOPING` | 409 Conflict |
| `ERR_ENGAGEMENT_NOT_DATA_COLLECTION` | 409 Conflict |
| `ERR_ENGAGEMENT_NOT_ANALYSIS` | 409 Conflict |
| `ERR_ENGAGEMENT_NOT_REPORT_DRAFT` | 409 Conflict |
| `ERR_ENGAGEMENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_PROHIBITED_COMPONENT` | 403 Forbidden |
| `ERR_NOTICE_FILE_MISSING` | 409 Conflict |
| `ERR_APPROVAL_EXPIRED` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SCAN_WORKER_ERROR` | 500 Internal Server Error |
| `ERR_LICENSE_SCAN_INCOMPLETE` | 422 Unprocessable Entity |
