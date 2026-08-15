# GFSI Certification Body API — Product Requirements Document

## 1. Introduction

A certification body operating GFSI-benchmarked schemes — SQF and BRC — carries a regulatory burden that generic workflow software does not absorb. Every certificate it publishes traces back through a chain of scope applications, competency-checked auditor assignments, announced and unannounced audits, graded findings with corrective-action deadlines, and an independent certification decision, and each link in that chain is governed by constants the scheme itself publishes: deadline days per finding grade, pass thresholds, calibration validity, appeal windows, rotation limits, and fee components. This document specifies the API, mounted under `/certification-body`, through which the certification body runs that program end to end — registering schemes and their rule constants, onboarding clients, auditors, and decision makers, reviewing and accepting scope applications, scheduling and conducting audits, managing the nonconformity lifecycle, rendering certification decisions, and issuing, suspending, reinstating, withdrawing, and expiring certificates.

Two commitments shape the design. The first is the integrity of the certification decision: the decision maker must never be the auditor of record, appeals are routed to a decision maker uninvolved in the original outcome, auditors are barred from clients with whom they have declared a conflict of interest, and auditor competency and calibration are re-verified at every assignment. The second is transparency toward the market: every granted certificate is published to a public certification directory, and every suspension, withdrawal, or expiry unlists it again, so the directory always reflects present certification status. Because corrective-action deadlines, certificate validity periods, calibration windows, and appeal windows are all measured against time, the server runs on a controllable logical clock rather than wall-clock time; advancing that clock is what drives the overdue-finding and certificate-expiry sweeps described later in this document.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes five roles, spelled exactly as follows: `SchemeAdmin`, `ClientAdmin`, `Auditor`, `DecisionMaker`, and `Anonymous`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `ClientAdmin`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that traces to a client — an application, an audit beneath it, a nonconformity beneath that, a certificate — compare the resource's client chain against `X-User-ID`. When `X-User-Role` is `Auditor`, `X-User-ID` is the `id` of the acting `Auditor`; ownership checks compare the target audit's `auditor_id` against it. When `X-User-Role` is `DecisionMaker`, `X-User-ID` is the `id` of the acting `DecisionMaker`; the server stamps that id onto the decisions it renders (as `decision_maker_id` on an audit and `decided_by` on a scope change or appeal), and independence checks compare those stamps against it. When `X-User-Role` is `SchemeAdmin` or `Anonymous`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

Missing or unrecognized headers are rejected with `ERR_UNAUTHENTICATED` (HTTP 401) on every endpoint except the public certification directory, which an `Anonymous` caller may query without any authentication headers. A caller whose role is not listed among an endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Where a resource has an owner, an entity-backed caller who does not own the target is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403): for a `ClientAdmin` the resource's client chain must equal `X-User-ID`, and for an `Auditor` the target audit's `auditor_id` must be non-null and equal to `X-User-ID`. A null assignee does not fail the ownership check — that situation is caught later by the unassigned-audit constraint described in §3.5.

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

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Unless a list states its own ordering, all list endpoints return resources sorted by `created_at` in ascending order. Because the logical clock (§2.6) holds its value until explicitly advanced, resources created between two clock advances share the same `created_at`; wherever the system orders resources by `created_at` — whether as a list's primary ordering, as a stated tie-break, or in the sweep candidate processing of §2.6 — such ties are resolved by creation order, so a resource created earlier precedes one created later. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource type in the system — Scheme, Client, Auditor, DecisionMaker, Application, Audit, Nonconformity, Certificate, ScopeChange, Appeal, WitnessAudit, and DirectoryListing — shares a standard set of system-managed fields. The `id` is a server-minted UUID formatted identifier with no type prefix. The `created_at` timestamp records when the resource was created, expressed as ISO 8601 in UTC with three fractional digits. The `updated_at` timestamp follows the same format and is refreshed on every mutation of the resource. The `version` is an integer that starts at its initial value on creation and increments by one on every mutation; it is the linchpin of the optimistic concurrency rule in §2.11.

### 2.5. Request Evaluation Order

When several checks could reject the same request, the server evaluates nine classes of checks in a fixed priority order, and a failure in an earlier class masks every later class. The order is:

1. **Authentication.** `X-User-ID` and `X-User-Role` must be present and the role must be recognized; failures carry `ERR_UNAUTHENTICATED` (401). This class applies to every endpoint except the public certification directory.
2. **Role authorization.** The caller's role must appear among the endpoint's authorized roles; otherwise `ERR_UNAUTHORIZED` (403).
3. **Ownership.** Entity-backed callers must own the target resource as described in §2.1; otherwise `ERR_FORBIDDEN_OWNERSHIP` (403).
4. **Path existence.** Path identifiers are validated left to right; the first identifier that does not correspond to an existing resource produces its specific 404 — `ERR_CLIENT_NOT_FOUND`, `ERR_SCHEME_NOT_FOUND`, `ERR_AUDITOR_NOT_FOUND`, `ERR_DECISION_MAKER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_NC_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_SCOPE_CHANGE_NOT_FOUND`, or `ERR_APPEAL_NOT_FOUND`.
5. **State and version.** The target entity's status must permit the requested transition — `ERR_INVALID_APPLICATION_STATE`, `ERR_INVALID_AUDIT_STATE`, `ERR_INVALID_NC_STATE`, `ERR_INVALID_CERTIFICATE_STATE`, `ERR_INVALID_SCOPE_CHANGE_STATE`, or `ERR_INVALID_APPEAL_STATE`, each carrying 409 — and, for scope-change creation, the requested certificate version must match the current one (`ERR_STALE_CERTIFICATE_VERSION`, 412).
6. **Body references.** Foreign keys carried in the request body must reference existing resources: the `auditor_id` on an assignment and the `certificate_id` on an appeal creation; otherwise `ERR_REFERENCE_NOT_FOUND` (422).
7. **Independence and conflicts.** The regulatory separation rules of §2.7: `ERR_AUDITOR_CONFLICT_OF_INTEREST` (422), `ERR_DECISION_NOT_INDEPENDENT` (403), and `ERR_APPEAL_NOT_INDEPENDENT` (403).
8. **Temporal rules.** The window rules of §2.8 and the appeal-window rule of §3.9: `ERR_OUTSIDE_AUDIT_WINDOW` (422), `ERR_INVALID_AUDIT_WINDOW` (422), `ERR_AUDITOR_WINDOW_OVERLAP` (409), `ERR_AUDIT_WINDOW_TOO_CLOSE` (409), and `ERR_APPEAL_WINDOW_EXPIRED` (422).
9. **Capability and aggregate constraints.** Competency, calibration, rotation, category support, duplicate guards, assignment presence, and the decision gates: `ERR_AUDITOR_COMPETENCY_GAP` (422), `ERR_AUDITOR_NOT_CALIBRATED` (422), `ERR_AUDITOR_ROTATION_LIMIT` (422), `ERR_SCOPE_CATEGORY_UNSUPPORTED` (422), `ERR_DUPLICATE_APPLICATION` (409), `ERR_DUPLICATE_CERTIFICATION_SCOPE` (409), `ERR_DUPLICATE_APPEAL` (409), `ERR_AUDIT_UNASSIGNED` (422), `ERR_OPEN_NCS_REMAIN` (422), and `ERR_SCORE_BELOW_PASS` (422).

### 2.6. The Logical Clock and Scheduled Sweeps

All deadlines, validity periods, windows, and "current time" comparisons in the system read a single server-side logical clock, never the wall clock. At startup the logical clock reads 2026-08-01T00:00:00Z. A `SchemeAdmin` advances it through a clock-setting capability that accepts a `to_iso8601` instant in ISO 8601 UTC and returns the resulting `current_utc`; once set, the clock holds that value and never falls back to wall-clock time. Advancing the clock fires two sweeps: the overdue-nonconformity sweep (§3.7) and the certificate-expiry sweep (§3.8). Both sweeps compare with strict inequality — a finding becomes overdue only when the current logical time is strictly later than its `deadline`, and a certificate expires only when the current logical time is strictly later than its `valid_to`; sitting exactly on the boundary is not overdue and not expired. Each sweep processes its candidates in `created_at` ascending order, and repeated sweeps over unchanged data cause no drift: a certificate that is already `SUSPENDED` is not re-transitioned by the overdue sweep.

### 2.7. Independence, Conflicts, and Segregation of Duties

The certification decision is structurally separated from audit execution. A decision maker rendering the certification decision on an audit must not be the auditor of record: if the acting decision maker's `linked_auditor_id` is non-null and equals the audit's `auditor_id`, the decision is rejected with `ERR_DECISION_NOT_INDEPENDENT` (403). Appeals carry a stricter separation: the acting decision maker must be neither the decision maker who rendered the appealed certificate's issuing audit decision nor a person linked to that audit's auditor — that is, the acting decision maker's own `id` must differ from the issuing audit's `decision_maker_id`, and the acting decision maker's `linked_auditor_id` must differ from that audit's `auditor_id`; a violation is rejected with `ERR_APPEAL_NOT_INDEPENDENT` (403). Conflicts of interest are declared on the auditor record: an auditor whose `conflicted_client_ids` contains the client behind an audit may never be assigned to it, and an attempted assignment is rejected with `ERR_AUDITOR_CONFLICT_OF_INTEREST` (422).

### 2.8. Audit Window Geometry

Every audit is bounded by a `window_start` and a `window_end`, and four geometric rules govern those windows. First, a window must be well-formed: `window_start` must be strictly earlier than `window_end`; an announced audit (type `INITIAL` or `SURVEILLANCE`) may span at most the scheme's `announced_max_window_days`; an `UNANNOUNCED` audit must span at least the scheme's `unannounced_min_window_days`; and a rescheduled window may not end in the past. Each violation is rejected with `ERR_INVALID_AUDIT_WINDOW` (422). Second, an auditor's committed windows must not intersect: two windows intersect whenever the first starts no later than the second ends and, symmetrically, the second starts no later than the first ends — boundaries are inclusive, so windows that merely touch still count as overlapping — and an offending assignment or reschedule is rejected with `ERR_AUDITOR_WINDOW_OVERLAP` (409). Third, sibling audits of the same client and scheme must respect the minimum separation: when one window ends before the other begins, the gap from the earlier window's end to the later window's start must be at least the scheme's `min_audit_gap_days`; a violation is rejected with `ERR_AUDIT_WINDOW_TOO_CLOSE` (409). Fourth, an audit may only be started while the current logical time lies within its window, endpoints inclusive; a start outside the window is rejected with `ERR_OUTSIDE_AUDIT_WINDOW` (422).

### 2.9. Scoring, Fees, and Rounding

Audit scoring is integer arithmetic with grade weights. Every nonconformity deducts from a base of 100 according to its `grade`: a `CRITICAL` finding weighs 25 points, a `MAJOR` finding weighs 10 points, and a `MINOR` finding weighs 3 points. The reported variant, frozen at report submission, deducts the full weight of every finding on the audit regardless of closure status. The resolved variant, computed at the certification decision, deducts the full weight of every finding not yet `CLOSED` but only half weight — rounded down, so `CRITICAL` contributes 12, `MAJOR` contributes 5, and `MINOR` contributes 1 — for each `CLOSED` finding. Both variants are clamped at zero and never go negative. Granting additionally requires the resolved score to be at least the scheme's `pass_score`, with the boundary inclusive: a resolved score exactly equal to `pass_score` passes.

Monetary values are handled at two decimal places with round-half-up rounding, and the certification fee is assembled with a pinned rounding order: each line item is rounded to two decimals first, and the rounded lines are then summed — never summed first and rounded after. The quote variant, stored as `provisional_fee_quote` when an application is accepted, is the scheme's `base_fee` plus the number of scoped product categories multiplied by `per_category_fee`, with that single sum rounded half-up to two decimals; the quote has no risk-tier multiplier, no day-rate component, and no unannounced uplift. The invoice variant, stored as `final_fee` at certificate issuance, is the sum of three individually rounded lines: the `base_fee` rounded half-up to two decimals; one line per scoped category of `per_category_fee` multiplied by the scheme's `high_risk_multiplier` when that category's `risk_tier` is `HIGH` and by 1.0 otherwise, each such line rounded half-up to two decimals; and a day-rate line equal to the issuing audit's `audit_fee` — the audit's declared `actual_days` multiplied by the scheme's `day_rate`, increased by the fractional `unannounced_uplift_pct` when the audit is `UNANNOUNCED`, rounded half-up to two decimals.

### 2.10. Certificate Status Propagation and the Public Directory

A certificate never changes public visibility silently: every transition that takes a certificate out of `ACTIVE` — suspension, withdrawal, or expiry — transitions its DirectoryListing to `UNLISTED` and stamps `unlisted_at` with the current logical time, and every reinstatement — manual or through an overturned appeal — transitions the listing back to `LISTED` and stamps `listed_at`. There is exactly one DirectoryListing per certificate; its `certificate_id` is unique across the listing collection. The listing denormalizes `client_name` and `scheme_code` for public display, and its `scope_summary` is computed as the category codes of the certificate's `product_categories` sorted in ascending order and joined with commas; the summary is regenerated whenever a scope change is approved. The public directory is the single unauthenticated read surface of the system (§3.9).

### 2.11. Optimistic Concurrency Control

Scope-change creation is guarded by optimistic concurrency control on the certificate. A request to `POST /certification-body/certificates/{id}/scope-changes` must carry `expected_certificate_version` as a non-optional input, holding the certificate `version` the client last observed. If another write — an earlier scope-change request, a suspension, a reinstatement, an approved scope change — has advanced the certificate's `version` since then, the client's view of the certificate is stale and the creation is rejected with `ERR_STALE_CERTIFICATE_VERSION` (HTTP 412), preventing a scope request from being written against a scope the client never saw. Endpoints not named here do not take a version field.

## 3. Business Logic & Workflows

### 3.1. Schemes and Their Rule Constants

Everything downstream is parameterized by a **Scheme**, and a `SchemeAdmin` registers one with its full set of rule constants. The scheme carries a `code` of either `SQF` or `BRC`, a human-readable `name`, and a non-empty `supported_category_codes` list naming the product category codes (for example BAKERY, DAIRY, or MEAT) the scheme is allowed to certify; every scope request anywhere in the system is validated against this list. Corrective-action pressure is tuned per finding grade through `critical_nc_days`, `major_nc_days`, and `minor_nc_days`, the calendar days from a finding's creation to its corrective-action deadline. The certification bar is `pass_score`, the minimum resolved audit score required to grant.

Scheduling constants give the scheme its cadence. The `unannounced_every_n` constant forces every nth audit in a client-and-scheme cycle to be unannounced, `unannounced_min_window_days` and `announced_max_window_days` bound audit window lengths per type (§2.8), and `min_audit_gap_days` keeps consecutive audits of the same client and scheme separated. Validity constants cover `cert_validity_days` from issuance to expiry, `witness_validity_days` for how long a passing witness audit keeps an auditor calibrated, and `appeal_window_days` for how long a client may appeal a certificate status change. Two integrity limits complete the picture: `max_cap_rejections`, the corrective-action rejection count at which the suspension cascade fires, and `rotation_limit`, the count of most-recent consecutive audits of one client and scheme that bars an auditor from being assigned again.

Finally, the fee constants: a flat `base_fee`, a `per_category_fee` applied per scoped product category, a `day_rate` for the audit-duration component, an `unannounced_uplift_pct` expressed as a fraction (0.10 means a ten percent uplift on the day-rate component for unannounced audits), and a `high_risk_multiplier` applied to the per-category line of categories whose risk tier is `HIGH`. Schemes may be listed — in `created_at` ascending order — and fetched individually by every authenticated role.

### 3.2. Onboarding Clients, Auditors, and Decision Makers

A `SchemeAdmin` registers each **Client** with its legal `name`, a `contact_email`, and a `country`; the returned client `id` is exactly the value the client's administrators will present as `X-User-ID` with role `ClientAdmin`. Reading a client record is restricted: a `ClientAdmin` may read only its own record, and reading another client's record is an ownership violation rejected with `ERR_FORBIDDEN_OWNERSHIP`.

Auditors are registered with a `name`, the `competency_categories` they are qualified to audit, and an optional `conflicted_client_ids` list that defaults to empty and declares the clients they may never audit. Two read-only indicators are computed on the auditor record. The `active_audit_count` counts the audits assigned to the auditor that are currently in `SCHEDULED` or `IN_PROGRESS` status; it rises by one on assignment and falls by one when an audit is decided or a scheduled assigned audit is cancelled. The `calibration_status` is `CURRENT` or `LAPSED` and starts at `LAPSED`; it is `CURRENT` exactly when a witness audit with `result` `PASS` exists whose `witnessed_on` is no older than the scheme's `witness_validity_days` — the boundary is inclusive, so a witness audit exactly `witness_validity_days` old still counts — and a `FAIL` witness audit never counts toward calibration. The `last_witnessed_on` field holds the most recent passing witness date and is null when the auditor has never passed one. Calibration is evaluated whenever an auditor record is read and again on every assignment attempt. A `SchemeAdmin` records a witness audit for an auditor with its `witnessed_on` date, a `result` of `PASS` or `FAIL`, and optional `notes`; recording one refreshes the auditor's computed `calibration_status` and `last_witnessed_on`, and an auditor's witness history lists newest first by `witnessed_on`, breaking ties by `created_at` ascending.

Decision makers are registered with a `name` and an optional `linked_auditor_id`, which is null by default and is set when the reviewer is also a registered auditor — the link that drives the independence checks of §2.7. Decision makers can be listed in `created_at` ascending order, optionally filtered by `linked_auditor_id`, and the audits each decision maker has decided are listable in `sequence_number` ascending order.

### 3.3. The Application: Drafting, Submission, and Scope Review

A certification engagement begins when a `ClientAdmin` creates an **Application** with the target `scheme_id`, the manufacturing `site_name`, the requested `product_categories` scope, and a free-text `scope_text` such as "production of baked goods"; the server binds the application to the caller by taking `client_id` from `X-User-ID`. Each entry of `product_categories` is an object pairing a `category_code` with a `risk_tier` of `STANDARD` or `HIGH`, the array must be non-empty, and every `category_code` must appear in the scheme's `supported_category_codes` — a request naming an unsupported category is rejected with `ERR_SCOPE_CATEGORY_UNSUPPORTED` (422). Only one open application may exist per client and scheme: if the same client already has an application for the same scheme in `DRAFT` or `SUBMITTED`, creation is rejected with `ERR_DUPLICATE_APPLICATION` (409). A new application starts in `DRAFT`, with `submitted_at` and `reviewed_at` null and `provisional_fee_quote` not yet computed. Malformed payloads — a missing required field, an empty scope array, an enum outside its allowed set — are rejected with `ERR_INVALID_REQUEST` (400).

Submitting moves the application from `DRAFT` to `SUBMITTED`. Ownership is checked first — only the client that owns the application may submit it, otherwise `ERR_FORBIDDEN_OWNERSHIP` — and the application must actually be in `DRAFT`, otherwise `ERR_INVALID_APPLICATION_STATE`. Submission stamps `submitted_at` with the current logical time and increments the application's `version`.

Scope review is performed by a `SchemeAdmin` supplying an `outcome`. Rejection requires the application to be `SUBMITTED` (otherwise `ERR_INVALID_APPLICATION_STATE`) and moves it to the terminal `REJECTED` state, stamping `reviewed_at`, storing the supplied `rejection_reason`, and incrementing `version`. Acceptance applies three checks in addition: the application must be `SUBMITTED`; no other application for the same client and scheme may sit in `DRAFT` or `SUBMITTED` (`ERR_DUPLICATE_APPLICATION`); and no certificate for the same client and scheme may exist in `ACTIVE` or `SUSPENDED` (`ERR_DUPLICATE_CERTIFICATION_SCOPE`, 409). Acceptance stamps `reviewed_at` with the current logical time, computes the `provisional_fee_quote` per the quote variant in §2.9, increments `version`, and brings the first audit into existence: its `sequence_number` is 1, its `audit_type` is `INITIAL`, its status is `SCHEDULED`, its `window_start` is fourteen days after `reviewed_at`, and its `window_end` is the scheme's `announced_max_window_days` days after that start.

Applications are listed in `created_at` ascending order with optional `client_id`, `scheme_id`, and `status` filters; a `ClientAdmin` sees only its own applications in this list. The audits belonging to an application are listed in `sequence_number` ascending order.

### 3.4. Assigning and Scheduling Audits

Assignment is the `SchemeAdmin`'s act of naming the auditor for a `SCHEDULED` audit by supplying an `auditor_id`. A body reference to an auditor that does not exist is rejected with `ERR_REFERENCE_NOT_FOUND` (422). Assignment then enforces the assignment gate in full: the auditor must not have declared a conflict with the client behind the audit (`ERR_AUDITOR_CONFLICT_OF_INTEREST`); the auditor's `competency_categories` must cover every product category in the application's scope, otherwise `ERR_AUDITOR_COMPETENCY_GAP` (422); the auditor's calibration must be `CURRENT` at assignment time, otherwise `ERR_AUDITOR_NOT_CALIBRATED` (422); and rotation is enforced — an auditor who performed the scheme's `rotation_limit` most recent consecutive audits for the same client and scheme may not be assigned again, and the attempt is rejected with `ERR_AUDITOR_ROTATION_LIMIT` (422). The new window must also not intersect the auditor's other `SCHEDULED` or `IN_PROGRESS` audits under the inclusive-overlap rule of §2.8 (`ERR_AUDITOR_WINDOW_OVERLAP`). A successful assignment sets the audit's `auditor_id`, raises the auditor's `active_audit_count` by one, and increments the audit's `version`.

Rescheduling lets a `SchemeAdmin` replace the `window_start` and `window_end` of an audit, and only an audit still in `SCHEDULED` may be rescheduled — any other status is rejected with `ERR_INVALID_AUDIT_STATE`. The replacement window must satisfy the well-formedness rules of §2.8 (`ERR_INVALID_AUDIT_WINDOW`), must respect the `min_audit_gap_days` separation against sibling audits of the same client and scheme (`ERR_AUDIT_WINDOW_TOO_CLOSE`), and must not intersect the assigned auditor's other committed windows (`ERR_AUDITOR_WINDOW_OVERLAP`). A successful reschedule stores the new bounds and increments `version`.

Cancelling is also restricted to `SCHEDULED` audits (`ERR_INVALID_AUDIT_STATE` otherwise) and moves the audit to the terminal `CANCELLED` state; when an auditor was assigned, that auditor's `active_audit_count` falls by one, and the audit's `version` increments. An auditor's own audit workload is listable per auditor in `sequence_number` ascending order, optionally filtered by `status`.

### 3.5. Conducting the Audit and Grading Findings

Starting the audit belongs to the assigned auditor. The ownership check runs first: an audit whose `auditor_id` is non-null and differs from the caller's `X-User-ID` is rejected with `ERR_FORBIDDEN_OWNERSHIP`, while a null `auditor_id` does not fail ownership. The audit must be `SCHEDULED` (`ERR_INVALID_AUDIT_STATE`), its parent application must be `ACCEPTED` (`ERR_INVALID_APPLICATION_STATE`), and the current logical time must lie within the window, endpoints inclusive (`ERR_OUTSIDE_AUDIT_WINDOW`). An audit with no assignee at all cannot start: the request is rejected with `ERR_AUDIT_UNASSIGNED` (422), reachable precisely when there is no assignee to fail the ownership check. A successful start moves `SCHEDULED → IN_PROGRESS`, stamps `started_at` with the current logical time, and increments `version`.

While the audit is `IN_PROGRESS`, the assigned auditor records graded findings. Each **Nonconformity** is created with a `grade` of `CRITICAL`, `MAJOR`, or `MINOR`, a `clause_ref` pointing at the scheme clause (for example "SQF 2.4.3"), and a free-text `description`; recording against an audit that is not `IN_PROGRESS` is rejected with `ERR_INVALID_AUDIT_STATE`, and malformed payloads or out-of-set grades are rejected with `ERR_INVALID_REQUEST`. The new finding is tied to the audit through its `audit_id`, opens in `OPEN` status, and receives a computed `deadline`: the finding's `created_at` plus the scheme's per-grade day constant — `critical_nc_days`, `major_nc_days`, or `minor_nc_days` — applied as exact 24-hour multiples. Its `rejection_count` starts at zero, and `cap_text`, `submitted_at`, and `reviewed_at` start null. The findings of an audit are listed in `created_at` ascending order with an optional `status` filter.

Submitting the report closes the auditor's fieldwork. The caller must be the assigned auditor (`ERR_FORBIDDEN_OWNERSHIP` first), the audit must be `IN_PROGRESS` (`ERR_INVALID_AUDIT_STATE`), and the declared `actual_days` — the actual audit duration in days — must be at least 1 (`ERR_INVALID_REQUEST`). The transition `IN_PROGRESS → REPORT_SUBMITTED` freezes two computed values onto the audit: the `reported_score`, the reported variant of the audit score per §2.9 over all findings of the audit, and the `audit_fee`, the day-rate line of §2.9 including the unannounced uplift when the audit is `UNANNOUNCED`. The submission also stamps `reported_at` and increments `version`.

### 3.6. The Certification Decision and the Continuing Audit Chain

Rendering the certification decision is an independent `DecisionMaker`'s act on a `REPORT_SUBMITTED` audit, supplying an `outcome` of `GRANT` or `DENY`; an audit in any other status is rejected with `ERR_INVALID_AUDIT_STATE`. The segregation-of-duties rule of §2.7 applies — a decision maker whose `linked_auditor_id` matches the audit's `auditor_id` is rejected with `ERR_DECISION_NOT_INDEPENDENT` — and a `GRANT` carries two further gates: every nonconformity raised on the audit must be `CLOSED` (`ERR_OPEN_NCS_REMAIN`, 422), and the resolved score per §2.9 must be at least the scheme's `pass_score`, boundary inclusive (`ERR_SCORE_BELOW_PASS`, 422). A rendered decision moves the audit from `REPORT_SUBMITTED` to `DECIDED`, computes and stores the `resolved_score`, stamps `decision_outcome`, `decision_maker_id`, and `decided_at`, drops the assigned auditor's `active_audit_count` by one, and increments the audit's `version`.

What happens next forks on both the outcome and the audit type. A `GRANT` on an `INITIAL` audit issues the certificate: its `valid_from` is the decision's `decided_at`, its `valid_to` is `cert_validity_days` days later, it starts `ACTIVE` with `status_changed_at` equal to `decided_at`, it receives the next `certificate_number` in the global issuance sequence formatted as CERT-NNNNNN with a zero-padded six-digit number, its `product_categories` and `scope_text` are copied from the application, and it records its lineage through `client_id`, `scheme_id`, `application_id`, and `audit_id`. Issuance also computes the `final_fee` per the invoice variant of §2.9, publishes the DirectoryListing in `LISTED` status with `listed_at` equal to `decided_at`, and schedules the next audit in the chain. A `GRANT` on a `SURVEILLANCE` or `UNANNOUNCED` audit leaves the existing certificate `ACTIVE` and likewise schedules the next audit. A `DENY` on an `INITIAL` audit creates neither certificate nor successor audit. A `DENY` on a `SURVEILLANCE` or `UNANNOUNCED` audit withdraws the existing `ACTIVE` certificate — `ACTIVE → WITHDRAWN` with `status_changed_at` equal to `decided_at` — and unlists its DirectoryListing with `unlisted_at` equal to `decided_at`, scheduling no successor.

The next audit in a chain is projected from the one just decided. Its `sequence_number` is the decided audit's plus one. Its `audit_type` is `UNANNOUNCED` when the new sequence number is an exact multiple of the scheme's `unannounced_every_n`, and `SURVEILLANCE` otherwise. Its `window_start` is the later of two instants: fourteen days after `decided_at`, or the decided audit's `window_end` plus the scheme's `min_audit_gap_days`. Its `window_end` extends `unannounced_min_window_days` beyond the start for an `UNANNOUNCED` audit and `announced_max_window_days` beyond the start otherwise. The certificate an audit issued remains readable through the audit, as an array of zero or one entries.

### 3.7. Corrective Action Plans and the Nonconformity Cycle

A finding's closure path runs between the owning client and the audit's auditor. The owning `ClientAdmin` submits a corrective-action plan by supplying `cap_text`; ownership is verified against the client chain behind the finding first (`ERR_FORBIDDEN_OWNERSHIP`), and the finding must be `OPEN` or `OVERDUE` (`ERR_INVALID_NC_STATE`, 409). Submission moves the finding `OPEN → UNDER_REVIEW` — or, for a late plan, `OVERDUE → UNDER_REVIEW` — stores the `cap_text`, stamps `submitted_at` with the current logical time, and increments `version`. A late submission does not undo anything else: if the certificate was already suspended when the finding went overdue, that suspension is not automatically reverted, and reinstatement remains the separate guarded transition of §3.8.

Reviewing a plan belongs to the auditor of the finding's audit (`ERR_FORBIDDEN_OWNERSHIP` for anyone else) and requires the finding to be `UNDER_REVIEW` (`ERR_INVALID_NC_STATE`). The auditor supplies an `outcome` and may attach optional `review_notes`. An `ACCEPT` outcome moves the finding `UNDER_REVIEW → CLOSED` and stamps `reviewed_at`. A `REJECT` outcome returns the finding `UNDER_REVIEW → OPEN`, increments `rejection_count` by one, and stamps `reviewed_at`; when the `rejection_count` thereby reaches the scheme's `max_cap_rejections`, the rejection-limit cascade fires — a certificate for the same client and scheme in `ACTIVE` status transitions to `SUSPENDED` with `suspension_reason` `CAP_REJECT_LIMIT` and `status_changed_at` set to the current logical time, and per §2.10 its DirectoryListing transitions to `UNLISTED` with `unlisted_at` stamped.

The overdue sweep runs whenever the logical clock advances (§2.6). Each finding still `OPEN` whose `deadline` is strictly earlier than the current logical time — sitting exactly on the deadline is not overdue — transitions `OPEN → OVERDUE`, processed in `created_at` ascending order. For each such finding, if a certificate for the same client and scheme is `ACTIVE`, it transitions to `SUSPENDED` with `suspension_reason` `NC_OVERDUE`, `status_changed_at` set, and `version` incremented, and its DirectoryListing transitions to `UNLISTED`. An already-`SUSPENDED` certificate is not re-transitioned, so repeated sweeps over the same findings cause no drift.

### 3.8. Certificate Suspension, Reinstatement, Withdrawal, and Expiry

A `DecisionMaker` may manually suspend a certificate, supplying a free-text `reason`; the certificate must be `ACTIVE` (`ERR_INVALID_CERTIFICATE_STATE` otherwise), and the transition `ACTIVE → SUSPENDED` records `suspension_reason` `MANUAL`, stamps `status_changed_at` with the current logical time, increments the certificate's `version`, and unlists its DirectoryListing. Suspensions also arrive from the two cascades of §3.7 with `suspension_reason` `NC_OVERDUE` or `CAP_REJECT_LIMIT`; the field is null unless the certificate is `SUSPENDED`.

Reinstatement moves `SUSPENDED → ACTIVE` under a guard that depends on why the certificate was suspended. When `suspension_reason` is `NC_OVERDUE` or `CAP_REJECT_LIMIT`, every nonconformity raised on audits of the same client and scheme must be `CLOSED` before reinstatement is allowed, otherwise the attempt is rejected with `ERR_OPEN_NCS_REMAIN`; a `MANUAL` suspension carries no such guard. Reinstatement clears `suspension_reason` back to null, stamps `status_changed_at`, increments `version`, and transitions the DirectoryListing back to `LISTED` with a fresh `listed_at`.

Withdrawal is terminal: a `DecisionMaker` may withdraw a certificate from `ACTIVE` or `SUSPENDED` (any other status is rejected with `ERR_INVALID_CERTIFICATE_STATE`), stamping `status_changed_at`, incrementing `version`, and unlisting the DirectoryListing. The expiry sweep handles the remaining exit: whenever the logical clock advances, each certificate in `ACTIVE` or `SUSPENDED` whose `valid_to` is strictly earlier than the current logical time transitions to the terminal `EXPIRED` state — processed in `created_at` ascending order — with `status_changed_at` set, `version` incremented, and its DirectoryListing transitioned to `UNLISTED` with `unlisted_at` stamped. Certificates are listed in `created_at` ascending order with optional `client_id`, `scheme_id`, `application_id`, and `status` filters.

### 3.9. Scope Changes, Appeals, and the Public Directory

A certified client evolves its scope through a **ScopeChange**. The owning `ClientAdmin` creates one with the replacement `requested_categories` — the same non-empty array shape as the application's scope, each entry pairing a `category_code` with a `risk_tier`, and every category required to appear in the scheme's `supported_category_codes` (`ERR_SCOPE_CATEGORY_UNSUPPORTED`) — plus a free-text `reason`, and the optimistic-concurrency field `expected_certificate_version` per §2.11. The certificate must be `ACTIVE` (`ERR_INVALID_CERTIFICATE_STATE`). Creation produces a ScopeChange in `PENDING` status and itself touches the certificate record, incrementing the certificate's `version` by one. A certificate's scope-change requests list in `created_at` ascending order with an optional `status` filter.

A `DecisionMaker` then decides the request with an `outcome` of `APPROVED` or `REJECTED`; the request must be `PENDING` (`ERR_INVALID_SCOPE_CHANGE_STATE`). Approval replaces the certificate's `product_categories` with the `requested_categories`, increments the certificate's `version`, regenerates the DirectoryListing's `scope_summary` from the new categories, and stamps `decided_by` and `decided_at` on the request. Rejection stamps `decided_by` and `decided_at` and leaves the certificate untouched. Both outcomes increment the ScopeChange's own `version`.

An **Appeal** is the client's remedy against a lost certification status. The owning `ClientAdmin` files one by naming the `certificate_id` — an unknown certificate reference is rejected with `ERR_REFERENCE_NOT_FOUND` — and stating the `grounds`. The target certificate must be `SUSPENDED` or `WITHDRAWN` (`ERR_INVALID_CERTIFICATE_STATE` otherwise), the filing must land no later than the scheme's `appeal_window_days` days after the certificate's `status_changed_at` — the boundary is inclusive, so filing exactly at the deadline is allowed, while a later filing is rejected with `ERR_APPEAL_WINDOW_EXPIRED` — and a certificate may have at most one appeal in `FILED` status at a time (`ERR_DUPLICATE_APPEAL`, 409). A new appeal starts `FILED` with `decided_by` and `decided_at` null; a certificate's appeals list in `created_at` ascending order.

Deciding an appeal belongs to a `DecisionMaker` who was not involved in the original outcome, per the independence rule of §2.7: the acting decision maker must be neither the issuing audit's `decision_maker_id` nor linked to that audit's auditor (`ERR_APPEAL_NOT_INDEPENDENT`, 403), and the appeal must be `FILED` (`ERR_INVALID_APPEAL_STATE`). An `UPHELD` outcome stamps `decided_by` and `decided_at`, increments the appeal's `version`, and leaves the certificate's status unchanged. An `OVERTURNED` outcome stamps the same fields and reinstates the certificate — `SUSPENDED → ACTIVE` or `WITHDRAWN → ACTIVE` — clearing `suspension_reason`, setting `status_changed_at` to the current logical time, incrementing the certificate's `version` by one, and transitioning the DirectoryListing back to `LISTED` with `listed_at` stamped.

The public certification directory is the market-facing surface: it is queryable without authentication — the only endpoint an `Anonymous` caller may use — and by every other role, in `created_at` ascending order with optional `scheme_code` and `status` filters. Each listing row shows its `certificate_id`, the denormalized `client_name` and `scheme_code`, the computed `scope_summary`, its `status` of `LISTED` or `UNLISTED`, and the `listed_at` / `unlisted_at` stamps. A certificate's own listing is also readable through the certificate itself, as an array of zero or one entries.

## 4. Endpoint Definitions

Operations that create a new resource — registering a scheme, client, auditor, witness audit, or decision maker; filing an application, a nonconformity, a scope change, or an appeal — return `201 Created`. Operations that modify an existing resource or drive a state transition, and all reads, return `200 OK`. Request and response payloads for each endpoint are reconstructed from the narratives in §3; the table below is the routing contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/certification-body/schemes` | Register a certification scheme with its rule constants | SchemeAdmin |
| GET    | `/certification-body/schemes` | List schemes (created_at ASC), paginated | SchemeAdmin, ClientAdmin, Auditor, DecisionMaker |
| GET    | `/certification-body/schemes/{id}` | Get one scheme | SchemeAdmin, ClientAdmin, Auditor, DecisionMaker |
| POST   | `/certification-body/clients` | Register a client organization; the returned id is the ClientAdmin's X-User-ID | SchemeAdmin |
| GET    | `/certification-body/clients/{id}` | Get one client (ClientAdmin may read only its own id) | SchemeAdmin, ClientAdmin |
| POST   | `/certification-body/auditors` | Register an auditor with competency categories and declared client conflicts | SchemeAdmin |
| GET    | `/certification-body/auditors/{id}` | Get one auditor (includes computed calibration_status and active_audit_count) | SchemeAdmin, Auditor, DecisionMaker |
| GET    | `/certification-body/auditors/{id}/audits` | List audits assigned to an auditor (sequence_number ASC) | SchemeAdmin, Auditor, DecisionMaker |
| POST   | `/certification-body/auditors/{id}/witness-audits` | Record a witness (calibration) audit for an auditor | SchemeAdmin |
| GET    | `/certification-body/auditors/{id}/witness-audits` | List an auditor's witness audits (witnessed_on DESC, created_at ASC) | SchemeAdmin, Auditor |
| POST   | `/certification-body/decision-makers` | Register a certification decision maker; linked_auditor_id set when the person is also an auditor | SchemeAdmin |
| GET    | `/certification-body/decision-makers/{id}` | Get one decision maker | SchemeAdmin, DecisionMaker |
| GET    | `/certification-body/decision-makers` | List decision makers, optionally filtered by linked_auditor_id (created_at ASC) | SchemeAdmin, DecisionMaker |
| GET    | `/certification-body/decision-makers/{id}/audits` | List audits whose certification decision this decision maker rendered (sequence_number ASC) | SchemeAdmin, DecisionMaker |
| POST   | `/certification-body/applications` | Client creates a certification application selecting scheme, site, and product-category scope | ClientAdmin |
| GET    | `/certification-body/applications` | List applications with optional filters (created_at ASC), paginated; ClientAdmin sees only its own | SchemeAdmin, ClientAdmin, DecisionMaker |
| GET    | `/certification-body/applications/{id}` | Get one application | SchemeAdmin, ClientAdmin, Auditor, DecisionMaker |
| POST   | `/certification-body/applications/{id}/submit` | Submit a DRAFT application for scope review | ClientAdmin |
| POST   | `/certification-body/applications/{id}/review` | SchemeAdmin accepts (scope valid, no duplicate) or rejects a SUBMITTED application; acceptance computes the fee quote and creates the INITIAL audit | SchemeAdmin |
| GET    | `/certification-body/applications/{id}/audits` | List audits of an application (sequence_number ASC) | SchemeAdmin, ClientAdmin, Auditor, DecisionMaker |
| GET    | `/certification-body/audits/{id}` | Get one audit | SchemeAdmin, ClientAdmin, Auditor, DecisionMaker |
| POST   | `/certification-body/audits/{id}/assign` | Assign an auditor: competency superset, no declared conflict, calibration CURRENT, rotation limit, no window intersection | SchemeAdmin |
| POST   | `/certification-body/audits/{id}/reschedule` | Change the window of a SCHEDULED audit under the window geometry rules | SchemeAdmin |
| POST   | `/certification-body/audits/{id}/cancel` | Cancel a SCHEDULED audit | SchemeAdmin |
| POST   | `/certification-body/audits/{id}/start` | Assigned auditor starts the audit inside its window | Auditor |
| POST   | `/certification-body/audits/{id}/nonconformities` | Assigned auditor records a graded finding while the audit is IN_PROGRESS | Auditor |
| GET    | `/certification-body/audits/{id}/nonconformities` | List findings of an audit (created_at ASC) | SchemeAdmin, ClientAdmin, Auditor, DecisionMaker |
| POST   | `/certification-body/audits/{id}/submit-report` | Assigned auditor submits the audit report with the actual duration; freezes reported_score and audit_fee | Auditor |
| POST   | `/certification-body/audits/{id}/decision` | Independent decision maker renders GRANT/DENY; GRANT on an INITIAL audit issues the certificate, computes the final fee, publishes the directory listing, and schedules the next audit | DecisionMaker |
| GET    | `/certification-body/audits/{id}/certificate` | Get the certificate issued by this audit (array of 0 or 1) | SchemeAdmin, ClientAdmin, Auditor, DecisionMaker |
| GET    | `/certification-body/nonconformities/{id}` | Get one nonconformity | SchemeAdmin, ClientAdmin, Auditor, DecisionMaker |
| POST   | `/certification-body/nonconformities/{id}/submit-cap` | Owning client submits (or re-submits) a corrective-action plan; allowed from OPEN and OVERDUE | ClientAdmin |
| POST   | `/certification-body/nonconformities/{id}/review-cap` | The audit's auditor accepts (CLOSED) or rejects (back to OPEN) the CAP; rejection reaching the scheme limit fires the suspension cascade | Auditor |
| GET    | `/certification-body/certificates` | List certificates with optional filters (created_at ASC), paginated | SchemeAdmin, ClientAdmin, DecisionMaker |
| GET    | `/certification-body/certificates/{id}` | Get one certificate | SchemeAdmin, ClientAdmin, Auditor, DecisionMaker |
| POST   | `/certification-body/certificates/{id}/suspend` | Decision maker manually suspends an ACTIVE certificate | DecisionMaker |
| POST   | `/certification-body/certificates/{id}/reinstate` | Decision maker reinstates a SUSPENDED certificate; NC-triggered suspensions first require every finding of the (client, scheme) CLOSED | DecisionMaker |
| POST   | `/certification-body/certificates/{id}/withdraw` | Decision maker withdraws an ACTIVE or SUSPENDED certificate (terminal) | DecisionMaker |
| POST   | `/certification-body/certificates/{id}/scope-changes` | Owning client requests a scope change against the certificate version it last read (OCC guard); certificate must be ACTIVE | ClientAdmin |
| GET    | `/certification-body/certificates/{id}/scope-changes` | List scope-change requests of a certificate (created_at ASC) | SchemeAdmin, ClientAdmin, DecisionMaker |
| GET    | `/certification-body/certificates/{id}/appeals` | List appeals of a certificate (created_at ASC) | SchemeAdmin, ClientAdmin, DecisionMaker |
| GET    | `/certification-body/certificates/{id}/directory-listing` | Get the public directory listing of a certificate (array of 0 or 1) | SchemeAdmin, ClientAdmin, DecisionMaker |
| POST   | `/certification-body/scope-changes/{id}/decision` | Decision maker approves (replaces certificate scope and refreshes the directory listing) or rejects a PENDING scope change | DecisionMaker |
| POST   | `/certification-body/appeals` | Owning client appeals a SUSPENDED or WITHDRAWN certificate within scheme.appeal_window_days of status_changed_at; only one open appeal per certificate | ClientAdmin |
| POST   | `/certification-body/appeals/{id}/decide` | An independent decision maker upholds or overturns the appealed certificate status; OVERTURNED reinstates the certificate and re-lists the directory entry | DecisionMaker |
| GET    | `/certification-body/directory` | Public certification database; no authentication required; optional filters (created_at ASC), paginated | Anonymous, ClientAdmin, Auditor, DecisionMaker, SchemeAdmin |
| POST   | `/certification-body/_clock/set_current_utc` | Set the server's logical clock (ISO8601 UTC); advancing the clock fires the overdue-NC and certificate-expiry sweeps | SchemeAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this table is the identifier-to-status contract only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CLIENT_NOT_FOUND` | 404 |
| `ERR_SCHEME_NOT_FOUND` | 404 |
| `ERR_AUDITOR_NOT_FOUND` | 404 |
| `ERR_DECISION_MAKER_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_AUDIT_NOT_FOUND` | 404 |
| `ERR_NC_NOT_FOUND` | 404 |
| `ERR_CERTIFICATE_NOT_FOUND` | 404 |
| `ERR_SCOPE_CHANGE_NOT_FOUND` | 404 |
| `ERR_APPEAL_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 422 |
| `ERR_INVALID_APPLICATION_STATE` | 409 |
| `ERR_INVALID_AUDIT_STATE` | 409 |
| `ERR_INVALID_NC_STATE` | 409 |
| `ERR_INVALID_CERTIFICATE_STATE` | 409 |
| `ERR_INVALID_SCOPE_CHANGE_STATE` | 409 |
| `ERR_INVALID_APPEAL_STATE` | 409 |
| `ERR_STALE_CERTIFICATE_VERSION` | 412 |
| `ERR_AUDITOR_COMPETENCY_GAP` | 422 |
| `ERR_AUDITOR_CONFLICT_OF_INTEREST` | 422 |
| `ERR_AUDITOR_NOT_CALIBRATED` | 422 |
| `ERR_AUDITOR_ROTATION_LIMIT` | 422 |
| `ERR_AUDITOR_WINDOW_OVERLAP` | 409 |
| `ERR_AUDIT_WINDOW_TOO_CLOSE` | 409 |
| `ERR_INVALID_AUDIT_WINDOW` | 422 |
| `ERR_OUTSIDE_AUDIT_WINDOW` | 422 |
| `ERR_AUDIT_UNASSIGNED` | 422 |
| `ERR_SCOPE_CATEGORY_UNSUPPORTED` | 422 |
| `ERR_DUPLICATE_APPLICATION` | 409 |
| `ERR_DUPLICATE_CERTIFICATION_SCOPE` | 409 |
| `ERR_DUPLICATE_APPEAL` | 409 |
| `ERR_OPEN_NCS_REMAIN` | 422 |
| `ERR_SCORE_BELOW_PASS` | 422 |
| `ERR_DECISION_NOT_INDEPENDENT` | 403 |
| `ERR_APPEAL_NOT_INDEPENDENT` | 403 |
| `ERR_APPEAL_WINDOW_EXPIRED` | 422 |
