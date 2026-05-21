# FCRA Background Check API — Product Requirements Document

## 1. Introduction

The Fair Credit Reporting Act, layered with a patchwork of state-level Ban-the-Box and Salary History statutes, governs every consumer background check that a U.S. employer commissions. Recruiters who order checks, vendors who return verification payloads, and adjudicators who decide hiring outcomes all sit on the same compliance surface: a missed cooling-off day, a salary-history field accepted in the wrong state, or an adjudicator who signs off on an order they themselves opened can each turn into a regulator finding or a private lawsuit. The FCRA Background Check API is the system of record that mediates this surface. It captures candidate consent, orchestrates criminal, motor-vehicle, and education verifications, and walks an order through Pre-Adverse and Final Adverse Action with full audit evidence.

This document specifies the API contract that recruiters, candidates, verification vendors, and adjudicators interact with. The service is mounted under `/fcra` and exposes a small number of resources — candidates, consent disclosures, jurisdiction policies, background-check orders, verification items, disputes, and adverse-action flows — together with a tamper-evident audit-event chain. Every endpoint enforces FCRA defaults, layers the appropriate state-specific overrides on top, and refuses to advance an order whose paperwork is not in order. The service is designed to be implementation-language-agnostic; the contract below is the single source of truth.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API MUST include two headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, naming the role the principal is acting as. If either header is missing or empty, the request is rejected with `ERR_AUTH_REQUIRED` (HTTP 401). If the role is not authorised for the endpoint per the matrix described in §4, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system defines five roles, and their exact spellings are: `Recruiter`, `Adjudicator`, `Verifier`, `Candidate`, and `PlatformAdmin`. Their identities resolve as follows.

When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the acting `Candidate`; ownership checks on any resource that references a `Candidate` (consent disclosures, orders, verification items, disputes) compare the resource's foreign-key `candidate_id` to `X-User-ID`. A candidate may only revoke their own consent and may only open a dispute on a verification item that belongs to one of their own orders; the latter is enforced with `ERR_DISPUTE_NOT_OWNED` (HTTP 403).

When `X-User-Role` is `Recruiter`, `Adjudicator`, `Verifier`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `opened_by_role`/`adjudicated_by_user_id` on `BackgroundCheckOrder`, or as `actor_role`/`actor_user_id` on `AuditEvent`) but does not compare it to any entity's `id`. The `Recruiter` initiates candidates and orders. The `Adjudicator` reviews returned verifications, issues Pre-Adverse and Final Adverse Action, requests rework, resumes verification, and resolves disputes; an `Adjudicator` may not adjudicate an order they themselves opened. The `Verifier` is the external verification vendor that returns raw findings on assigned items. The `PlatformAdmin` is reserved for jurisdiction-policy upserts and the test-only clock and sweep endpoints.

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

List endpoints accept two query parameters: `limit` and `offset`. The default `limit` is 10, the minimum is 1, and the maximum is 100; the default `offset` is 0. Results are sorted by `created_at` in ascending order. Each list response carries pagination state in `meta`: the echoed `limit`, the echoed `offset`, the `total_count` of records matching the filter set, and a `has_more` boolean indicating whether further pages remain.

### 2.4. Resource Identity, Timestamps, and Versioning

Most resources — candidates, consent disclosures, background-check orders, verification items, disputes, and adverse-action flows — share a common set of system-managed fields. Each carries an `id`, which is a server-minted UUID with no type prefix. Each carries a `created_at` timestamp in ISO 8601 UTC with three fractional digits, set once when the row is first persisted. Each carries an `updated_at` timestamp in the same format, refreshed on every mutation, and an integer `version` that starts at 1 and increments by 1 on every mutation. Two scaffold-defined entities are deliberately outside this convention. `JurisdictionPolicy` rows carry only an `id` and a `created_at`; they have no `updated_at` and no `version`. `AuditEvent` rows likewise carry only an `id` and a `created_at`; an audit event is an immutable record and never mutates.

### 2.5. Optimistic Concurrency Control

Mutating endpoints that update existing rows accept an optional `version` integer in the request body. When `version` is supplied, the server compares it against the current row version; on mismatch the request is rejected with `ERR_STALE_VERSION` (HTTP 409) and no fields change. When `version` is omitted from the body, the OCC check is skipped and the write proceeds on the latest row. The same `ERR_STALE_VERSION` outcome covers concurrent updates: two simultaneous patches against the same row, each carrying the same starting `version`, serialize to a single winner; the loser receives `ERR_STALE_VERSION`.

### 2.6. Nested Resource Path Validation

Several endpoints address sub-resources through hierarchical paths (`/fcra/candidates/{candidateId}/consent`, `/fcra/candidates/{candidateId}/consent/revoke`, and so on). The path-variable names used across the API are `candidateId` for a candidate's `id`, `orderId` for a background-check order's `id`, `itemId` for a verification item's `id`, `disputeId` for a dispute's `id`, and `code` for a jurisdiction policy's `jurisdiction_code`. Path validation runs left to right. If a referenced `Candidate` does not exist or has a non-null `archived_at`, the response is `ERR_CANDIDATE_NOT_FOUND` (HTTP 404). If a referenced `BackgroundCheckOrder` does not exist, the response is `ERR_ORDER_NOT_FOUND` (HTTP 404). For other resources reached by id — `VerificationItem`, `Dispute`, `ConsentDisclosure`, and `JurisdictionPolicy` — the response is `ERR_RESOURCE_NOT_FOUND` (HTTP 404). Existence checks precede state, business, and concurrency checks.

### 2.7. Validation Ordering and Status Codes

Endpoints evaluate their validation rules in a fixed priority order. Authentication is checked first, then authorisation, then left-to-right existence of every path-addressed resource, then state preconditions, then business-safety rules, then business-referential rules, then business-constraint rules, then temporal rules, then audit-chain integrity for any newly minted audit event, and finally optimistic-concurrency `version` comparison for endpoints that accept a request-body `version`. Within business-safety, the FCRA-mandated checks are evaluated before non-safety business rules: compliance gates that would render the operation illegal (Ban-the-Box, Salary History Ban, consent validity, segregation of duties, cooling-off, open-dispute block) precede referential and constraint rules. Because the safety category fires first, an order opened in a Ban-the-Box-restricted state with an invalid `requested_packages` set surfaces `ERR_BAN_THE_BOX_VIOLATION` rather than `ERR_PACKAGE_SET_INVALID`. Successful creations of a candidate, a consent disclosure, an order, or a dispute return HTTP 201; every other successful operation returns HTTP 200. Malformed JSON, missing required fields, and type mismatches surface as `ERR_VALIDATION_FAILED` (HTTP 400).

### 2.8. Cascading State, Audit, and Version Semantics

When a mutating endpoint succeeds, the server updates the target row's `updated_at` and increments its integer `version` by 1. State transitions that touch more than one entity propagate identically: each affected row independently refreshes `updated_at` and increments `version`. State machines never silently overwrite a value computed by a prior transition — for example, when a `BackgroundCheckOrder` is moved to `TERMINATED_ADVERSE`, the cascade that cancels any sibling orders for the same candidate, the recompute of the candidate's `eligibility_posture`, and the append of the `AuditEvent` row all complete inside the same logical transaction. Every state-changing endpoint also appends one or more `AuditEvent` rows, each carrying a `previous_event_id` that points to the immediately prior `AuditEvent` for the same `subject_id`. The first event for any subject has `previous_event_id` of NULL; every subsequent event must reference the latest prior event for the subject, otherwise the insert is refused with `ERR_AUDIT_CHAIN_BROKEN`.

### 2.9. Compliance Boundaries: Ban-the-Box and Salary History Ban

Two FCRA-adjacent state-law gates run on every order-creation request and on candidate writes. The Ban-the-Box gate compares the order's `stage_at_order` against the candidate's residence jurisdiction's `ban_the_box_stage`. The three stage values, in increasing order of permissiveness for criminal screening, are `POST_OFFER` (criminal screen only after conditional offer), `POST_INTERVIEW` (after the first live interview), and `PRE_OFFER` (no restriction). A jurisdiction whose `ban_the_box_stage` is `POST_OFFER` forbids `PRE_OFFER` and `POST_INTERVIEW` orders; a jurisdiction whose gate is `POST_INTERVIEW` forbids `PRE_OFFER` orders; a jurisdiction whose gate is `PRE_OFFER` permits all three. A violation surfaces as `ERR_BAN_THE_BOX_VIOLATION` (HTTP 422). The Salary History Ban is a flat prohibition: when the candidate's jurisdiction has `salary_history_ban` set to true, no request body — candidate creation, candidate patch, or order creation — may carry a `salary_history` field, and the candidate's `salary_history_disclosed` field must remain false. Once `salary_history_disclosed` becomes true on a candidate (because a value was recorded at any point), every future endpoint that would accept `salary_history` on that candidate rejects the request with `ERR_SALARY_HISTORY_BAN` (HTTP 422), regardless of jurisdiction. The salary-ban check applies on candidate registration, candidate patch, and order creation.

### 2.10. Precision, Rounding, and Business-Day Arithmetic

The system's numeric calculations are integer-resolution. Severity scores are integers in the closed range from 0 through 100, computed left-to-right and capped by taking the smaller of the running total and 100. Aggregate adjudication scores are the integer sum of contributing severity scores. The cooling-off period is computed in business days, where Monday through Friday count and Saturday and Sunday never count; the day the Pre-Adverse notice is sent counts as day 0 and is excluded from the elapsed tally, so the candidate has full business days to dispute. The criminal-record age cutoff is the only floating-point computation in the system: age in years is the elapsed time since the conviction divided by 365.25 days per year, and a conviction whose age is less than or equal to the jurisdiction's `criminal_lookback_years` is reportable while a conviction whose age is greater is not. Whenever a calculated value is exposed through the API as a count of days or business days, it is presented as an integer.

### 2.11. Segregation of Duties and Audit Chain Integrity

The Adjudicator's `X-User-ID` must differ from the `BackgroundCheckOrder.opened_by_user_id` recorded when the order was opened; a violation, whether attempted on issuing Pre-Adverse, on issuing Final Adverse, or on resolving a dispute attached to the order, surfaces as `ERR_SOD_VIOLATION` (HTTP 422). The audit chain backing every order is tamper-evident: each `AuditEvent` records the acting `actor_role`, the acting `actor_user_id`, the subject entity through `subject_entity` and `subject_id`, the `event_type`, the `previous_event_id` linking back to the prior event for that subject, and a `payload_hash` that is a SHA-256 over the concatenation of `subject_id`, `event_type`, `actor_user_id`, `created_at`, and `previous_event_id`. The audit chain is broken — and the insert refused with `ERR_AUDIT_CHAIN_BROKEN` — if the supplied `previous_event_id` is not the most recent event id for the same `subject_id`, or if a non-null `previous_event_id` is supplied for what should be the first event on a subject.

## 3. Business Logic & Workflows

### 3.1. Candidate Registration and the Jurisdiction Lens

A hiring workflow begins when a `Recruiter` registers a new `Candidate`. The request supplies the candidate's `full_name`, the contact `email`, the two-letter `residence_jurisdiction`, and the `date_of_birth` in ISO `YYYY-MM-DD` form. The seven supported `residence_jurisdiction` values are `CA`, `NY`, `IL`, `TX`, `FL`, `MA`, and `WA`, and a `JurisdictionPolicy` row must exist for the supplied code (registered separately by a `PlatformAdmin`). On a successful registration the candidate's initial `eligibility_posture` is `ELIGIBLE`, its computed `salary_history_disclosed` is false, and its `archived_at` is null. The candidate's `email` must be unique across candidates whose `archived_at` is null; two simultaneous registrations of the same email serialize to a single winner and the loser sees `ERR_CANDIDATE_EMAIL_TAKEN` (HTTP 409). A request may optionally include a `salary_history` field, but only if the candidate's `residence_jurisdiction` maps to a `JurisdictionPolicy` whose `salary_history_ban` is false; otherwise the request is rejected with `ERR_SALARY_HISTORY_BAN`.

`Recruiter` updates to an existing candidate are limited to mutable fields. A patch may carry a new `full_name`, a new `email`, or an optional `version` for OCC. A `salary_history` field is never accepted on patch: jurisdictions with `salary_history_ban` reject it with `ERR_SALARY_HISTORY_BAN`, and once `salary_history_disclosed` is true on the candidate the same error fires regardless of jurisdiction. A `Recruiter` or `Adjudicator` may also list candidates with `limit` and `offset` pagination and an optional filter on `eligibility_posture`, or fetch a single candidate by `candidateId`. Candidates themselves may read their own row.

Each `JurisdictionPolicy` row is the configuration spine for the candidate's screening contract. Its `jurisdiction_code` is unique, and its fields drive every state-specific gate: `criminal_lookback_years` caps how old a reportable conviction may be, `salary_history_ban` toggles the salary-history prohibition described above, `ban_the_box_stage` (one of `POST_OFFER`, `POST_INTERVIEW`, or `PRE_OFFER`) gates which hiring stage may carry a criminal order, and `adverse_action_waiting_business_days` (an integer of at least 5) names the minimum business days that must elapse between Pre-Adverse and Final Adverse. The federal floor on that waiting period is 5, and a `PlatformAdmin` may upsert a higher value but never a lower one. Reading the catalogue is shared with `Recruiter` and `Adjudicator`; the upsert is `PlatformAdmin`-only.

### 3.2. Consent: Recording, Superseding, and Revocation

Before any order can be opened, a `ConsentDisclosure` row must exist for the candidate. Either the `Recruiter` (on behalf of the candidate) or the `Candidate` (acting on their own row) may record one. The request body carries the `disclosure_text_hash` (the SHA-256 of the standalone disclosure document that was shown), the free-text `consent_signature`, the `consent_timestamp` recording when the candidate signed, and the `disclosure_presented_at` timestamp recording when the disclosure was shown. The temporal contract is strict: `consent_timestamp` must be less than or equal to the server's current time, and `disclosure_presented_at` must be less than or equal to `consent_timestamp` (the candidate cannot sign before seeing the disclosure, and neither timestamp may sit in the future). A violation of either inequality surfaces as `ERR_CONSENT_TIMESTAMP_INVALID` (HTTP 422). The `consent_signature` must be non-empty; a blank signature, an inconsistent timestamp pair, or any other defect that leaves the consent unusable for the next order surfaces as `ERR_CONSENT_INVALID` (HTTP 422) when the order is later opened.

Recording a new consent for a candidate whose row already has an `ACTIVE` consent supersedes the old one: the prior consent's `status` moves to `SUPERSEDED` and the new row's `status` is `ACTIVE`. A consent's `status` therefore takes one of three values: `ACTIVE` (the live disclosure), `SUPERSEDED` (replaced by a newer recorded consent), or `REVOKED` (the candidate withdrew it). The acting `Candidate` may revoke their `ACTIVE` consent at any time; revocation moves `status` to `REVOKED`, stamps `revoked_at` with the server's current time, and writes an `AuditEvent` of type `CONSENT_REVOKED`. Once revoked, no new `BackgroundCheckOrder` may be created against that consent. A successful consent recording appends an `AuditEvent` of type `CONSENT_RECORDED`.

### 3.3. Opening an Order: Eligibility, Consent Pinning, Ban-the-Box

A `Recruiter` opens a `BackgroundCheckOrder` by supplying a `candidate_id`, a `consent_disclosure_id`, a `stage_at_order`, and a `requested_packages` array. The `stage_at_order` is one of `PRE_OFFER`, `POST_INTERVIEW`, or `POST_OFFER`. The `requested_packages` array is a non-empty list, without duplicates, drawn from `CRIMINAL`, `MVR`, and `EDUCATION`; an empty array, a duplicated entry, or an unknown package code is rejected with `ERR_PACKAGE_SET_INVALID` (HTTP 422). The candidate's current `eligibility_posture` must be `ELIGIBLE` — neither `UNDER_REVIEW`, `ADVERSE`, nor `LOCKED` — and a violation surfaces as `ERR_CANDIDATE_NOT_ELIGIBLE` (HTTP 422).

The supplied `consent_disclosure_id` must reference a `ConsentDisclosure` whose `candidate_id` matches the order's `candidate_id`; a mismatch is `ERR_CONSENT_CANDIDATE_MISMATCH` (HTTP 422). The referenced consent must be `ACTIVE` at the moment of order creation, and the order pins that `consent_disclosure_id` for its lifetime — a newer consent recorded later does not retroactively change which disclosure governs the order. An order creation against a missing, `SUPERSEDED`, or `REVOKED` consent surfaces as `ERR_CONSENT_INVALID`. The Ban-the-Box gate is evaluated against the candidate's jurisdiction's `ban_the_box_stage` per §2.9, and a salary-history field in the order body is forbidden whenever the candidate's jurisdiction has `salary_history_ban` true or the candidate's `salary_history_disclosed` is already true.

A successful order creation spawns one `VerificationItem` per entry of `requested_packages`, each in the `QUEUED` initial state with a `kind` matching the requested package (`CRIMINAL`, `MVR`, or `EDUCATION`) and an empty `raw_finding`. The new order's `status` is `INTAKE`, its `composite_decision` is `PENDING`, its `opened_by_role` is the calling role, and the calling `X-User-ID` is recorded as the order's opener for later segregation-of-duties checks. The candidate's `eligibility_posture` is recomputed to `UNDER_REVIEW`, and an `AuditEvent` of type `ORDER_OPENED` is appended, chained off the consent's most recent event. The order responds with HTTP 201.

### 3.4. Verification: Vendor Returns, Item Lifecycle, and Severity Scoring

Once an order is opened, the `Recruiter` triggers verification by starting verification on the order, which transitions the order from `INTAKE` to `IN_VERIFICATION` and moves every spawned item from `QUEUED` to `IN_PROGRESS`. The trigger is rejected if the order's pinned `ConsentDisclosure` is not `ACTIVE` or the candidate's `eligibility_posture` is `LOCKED`. The `Verifier` then submits the vendor's findings on each item, posting a `raw_finding` payload whose shape depends on `kind`: a `CRIMINAL` finding carries a `conviction_date` and a `severity` of `INFRACTION`, `MISDEMEANOR`, or `FELONY`; an `MVR` finding carries a `violations_3yr` integer and a `license_status`; an `EDUCATION` finding carries an `institution` and a `claim_verified` boolean. A well-formed payload advances the item from `IN_PROGRESS` to `RETURNED`, recomputes `severity_score`, appends an `AuditEvent` of type `ITEM_RETURNED`, and — if every sibling item on the same order has reached one of `RETURNED`, `PASSED`, or `FAILED` — cascades the parent order from `IN_VERIFICATION` to `AWAITING_ADJUDICATION`. Any subsequent edit to `raw_finding` while the item is `RETURNED` re-runs the score.

The severity-score computation is item-kind-specific and produces an integer in the closed range from 0 through 100. For a `CRIMINAL` item, the system first determines whether the conviction is reportable at all: the exact age in years is the elapsed time since `conviction_date` divided by 365.25 days per year, and the conviction is reportable when that age is less than or equal to the jurisdiction's `criminal_lookback_years` (the boundary is inclusive — ties go to reportable). When the conviction is outside the lookback window, the base score is forced to 0 regardless of the recorded `severity`. When the conviction is reportable, the base score is 5 for an `INFRACTION`, 25 for a `MISDEMEANOR`, and 70 for a `FELONY`; the final score is the smaller of that base and 100. For an `MVR` item, the tier breakdown is exact: zero violations in the last three years scores 0, one violation scores 10, two violations score 25, and three or more violations score 50; a `license_status` of `SUSPENDED` adds a 20-point bonus on top of the tier; the final score is the smaller of the tier-plus-bonus and 100. For an `EDUCATION` item, the score is 0 when `claim_verified` is true and 40 when `claim_verified` is false.

A `VerificationItem`'s `status` therefore moves through `QUEUED`, `IN_PROGRESS`, `RETURNED`, and one of the adjudicated terminals `PASSED` or `FAILED`, with `DISPUTED` and `REWORK_REQUIRED` as branchable intermediate states. The item's `rework_count` is initialised to zero and tracks how many times the item has cycled through `REWORK_REQUIRED`; the cap is 2, and an attempt to bump the count beyond 2 forces the parent order to `TERMINATED_ADVERSE` rather than incrementing further. The item's `dispute_id` is null whenever no open dispute references the item and is set to the active dispute's id while a dispute is open.

### 3.5. Adjudication: Composite Decision and the Dual-Variant Score

When every item on an order reaches `RETURNED`, `PASSED`, or `FAILED`, the system recomputes the order's `composite_decision`. The input set is exactly those items whose `status` is `RETURNED`, `PASSED`, or `FAILED`; items still `QUEUED`, `IN_PROGRESS`, or `DISPUTED` are excluded. The total aggregate score is the integer sum of each contributing item's `severity_score`.

The system supports two scoring variants on the same input set, and the canonical variant used by the engine to gate live adjudication is the jurisdictional variant. Under the jurisdictional variant, the aggregate is compared against two thresholds. When the aggregate is at most 30, the `composite_decision` is `CLEAR`. When the aggregate is greater than 30 but strictly less than the jurisdiction's INELIGIBLE cut, the `composite_decision` is `CONSIDER`. When the aggregate is greater than or equal to the jurisdiction's INELIGIBLE cut, the `composite_decision` is `INELIGIBLE`. The state-by-state INELIGIBLE cut is 80 for `CA`, 75 for `NY`, 70 for `IL`, 60 for `TX`, 55 for `FL`, 80 for `MA`, and 70 for `WA`. The federal-strict variant is exposed exclusively for audit reconstruction in `PRE_OFFER` orders and regulator audit contexts: under it, each individual item is marked as a per-item CONSIDER when its `severity_score` is at least 15; the fail count is the number of items so marked; a fail count of 0 yields `CLEAR`, a fail count of 1 yields `CONSIDER`, and a fail count of 2 or more yields `INELIGIBLE`. The two variants can diverge on the same item set — for example, a `CRIMINAL` item scoring 25 plus an `MVR` item scoring 10 sums to an aggregate of 35, which the jurisdictional variant treats as `CONSIDER` (the aggregate exceeds 30) while the federal-strict variant also treats as `CONSIDER` because the criminal item alone clears the per-item threshold of 15.

When the recomputed `composite_decision` is `CLEAR`, the order auto-transitions from `AWAITING_ADJUDICATION` straight to `COMPLETED_CLEAR`. No `AdverseActionFlow` is created, the candidate's `eligibility_posture` is recomputed back to `ELIGIBLE`, and the verification-side audit chain closes out. When the recomputed `composite_decision` is `CONSIDER` or `INELIGIBLE`, the order remains in `AWAITING_ADJUDICATION` and awaits a manual Pre-Adverse decision by an `Adjudicator`.

While items are in `AWAITING_ADJUDICATION`, the system also adjudicates each item to its terminal status: items whose `severity_score` is strictly less than 15 move from `RETURNED` to `PASSED`, and items whose `severity_score` is at least 15 move from `RETURNED` to `FAILED`, appending an `AuditEvent` of type `ITEM_FAILED` on the latter.

### 3.6. Pre-Adverse Action and the Cooling-Off Clock

An `Adjudicator` issues Pre-Adverse Action on an order whose `composite_decision` is `CONSIDER` or `INELIGIBLE`, advancing the order from `AWAITING_ADJUDICATION` to `PRE_ADVERSE_ISSUED`. The Pre-Adverse step is gated by three preconditions: the order's `composite_decision` must be in the set containing `CONSIDER` and `INELIGIBLE`; the acting `X-User-ID` must differ from the order's `opened_by_user_id` (a match surfaces as `ERR_SOD_VIOLATION`); and no `AdverseActionFlow` may already exist on the order — two simultaneous Pre-Adverse calls on the same order serialize on the uniqueness of `order_id` in the adverse-action-flow table, and the loser receives `ERR_ADVERSE_FLOW_ALREADY_EXISTS` (HTTP 409). On success the system creates a new `AdverseActionFlow` for the order with `pre_adverse_notice_sent_at` set to the current server time, `notification_status` moved from its initial `PENDING_DELIVERY` to `PRE_DELIVERED`, and `procedural_status` set to `PRE_AWAITING_DISPUTE_WINDOW`. The flow snapshots the jurisdiction's `adverse_action_waiting_business_days` into its own `waiting_period_business_days` field at the moment of Pre-Adverse send, and the flow is pinned to that number even if the jurisdiction's policy changes later. The order's `adjudicated_by_user_id` is set to the acting `X-User-ID`, and an `AuditEvent` of type `PRE_ADVERSE_SENT` is appended, chained off the most recent `ITEM_FAILED` or `ITEM_RETURNED` event on the order's subject chain.

The `earliest_final_eligible_at` timestamp is computed at the moment of Pre-Adverse send by the cooling-off calculation. The required business days for the cooling-off window is the larger of 5 and the jurisdiction's `adverse_action_waiting_business_days`; the federal-strict variant of the same calculation ignores the jurisdictional override and always uses 5. The elapsed business days is the count of business days between `pre_adverse_notice_sent_at` (exclusive — the send day counts as day 0 and does not contribute to the elapsed tally) and either the moment the flow last entered `DISPUTE_PAUSED` (if it ever paused) or the current server time (if it has not paused). The remaining business days is the required business days minus the elapsed business days. The `earliest_final_eligible_at` is then the result of advancing the current server time forward by that remaining number of business days, where weekend days (Saturday and Sunday) are never counted. For a `CA` candidate, whose `adverse_action_waiting_business_days` is 8, the engine's jurisdictional `earliest_final_eligible_at` lands 3 business days later than the federal-strict variant would on the same send time.

### 3.7. Disputes, Rework, and the Dispute-Paused Clock

While the Pre-Adverse notice is outstanding, the `Candidate` may open a `Dispute` on any of the order's items in `RETURNED`, `FAILED`, or `REWORK_REQUIRED` status. A dispute carries a `verification_item_id` and a `reason_text` between 1 and 1000 characters. On creation, the dispute's `status` is `OPEN`, the parent item's `dispute_id` is set, the item moves into `DISPUTED`, an `AuditEvent` of type `DISPUTE_OPENED` is appended, and any associated `AdverseActionFlow`'s `procedural_status` moves to `DISPUTE_PAUSED`. The candidate may only dispute items belonging to their own orders (`ERR_DISPUTE_NOT_OWNED`).

An `Adjudicator` resolves a dispute by supplying a `status` of either `UPHELD` or `OVERTURNED` together with a `resolution_note`. The resolving `Adjudicator` must not be the order's opener (a violation surfaces as `ERR_SOD_VIOLATION`). When the resolution is `UPHELD`, the dispute's `status` becomes `UPHELD`, the underlying item moves to `FAILED`, and — if an `AdverseActionFlow` exists and no other open dispute remains on the order — the flow's `procedural_status` returns to `PRE_AWAITING_DISPUTE_WINDOW` so the cooling-off clock can be re-evaluated. When the resolution is `OVERTURNED`, the dispute's `status` becomes `OVERTURNED` and the item moves to `REWORK_REQUIRED`, with `rework_count` incremented by 1; if the increment would carry the count past 2, the increment is not applied and the parent order is instead forced to `TERMINATED_ADVERSE` via the rework-cap path, surfacing `ERR_REWORK_CAP_EXCEEDED` (HTTP 422) on a same-call attempt. An `AuditEvent` of type `DISPUTE_RESOLVED` is appended on every resolution.

Independently of a candidate-opened dispute, the `Adjudicator` may request rework directly on an order in `PRE_ADVERSE_ISSUED` when new evidence warrants re-verification. The request carries a `target_item_ids` array selecting which items to rework. At least one targeted item must have a `rework_count` strictly less than 2; otherwise the request is rejected with `ERR_REWORK_CAP_EXCEEDED`. Each eligible targeted item moves to `REWORK_REQUIRED` and its `rework_count` is incremented by 1, the order moves from `PRE_ADVERSE_ISSUED` to `REWORK`, the associated `AdverseActionFlow`'s `procedural_status` moves to `DISPUTE_PAUSED`, and an `AuditEvent` of type `REWORK_REQUESTED` is appended. Resuming verification by the same `Adjudicator` moves the order from `REWORK` back to `IN_VERIFICATION` once every `REWORK_REQUIRED` item has a refreshed `raw_finding`; each such item moves from `REWORK_REQUIRED` back to `IN_PROGRESS`, the item's `dispute_id` is cleared, and the flow remains in `DISPUTE_PAUSED` until the items return.

While the `AdverseActionFlow` is in `DISPUTE_PAUSED`, the cooling-off clock does not advance. When the last open dispute on the order resolves and no `DISPUTED` items remain on the parent order, the flow returns from `DISPUTE_PAUSED` to `PRE_AWAITING_DISPUTE_WINDOW` and the system recomputes `earliest_final_eligible_at` using the elapsed business days captured at the moment of pause.

### 3.8. Final Adverse Action and Cascading Termination

The system advances the order from `PRE_ADVERSE_ISSUED` to `AWAITING_FINAL` only when, after a `PlatformAdmin` advances the test clock and runs the periodic sweep, the current server time is at or after the flow's `earliest_final_eligible_at` and no open dispute remains on any item of the order — at that moment the flow itself transitions from `PRE_AWAITING_DISPUTE_WINDOW` to `READY_FOR_FINAL` and the order from `PRE_ADVERSE_ISSUED` to `AWAITING_FINAL`. The Final Adverse Action endpoint then moves the order from `AWAITING_FINAL` to `TERMINATED_ADVERSE` when issued by an `Adjudicator`. Three preconditions are checked: the current server time must be at or after the flow's `earliest_final_eligible_at` (a violation surfaces as `ERR_COOLING_OFF_NOT_ELAPSED`, HTTP 422); no `Dispute` on any of the order's items may have `status` of `OPEN` (a violation surfaces as `ERR_OPEN_DISPUTE_BLOCKS_FINAL`, HTTP 422); and the acting `X-User-ID` must equal the order's `adjudicated_by_user_id` recorded at Pre-Adverse send — Final Adverse must be issued by the same `Adjudicator` who issued Pre-Adverse, and a mismatch surfaces as `ERR_SOD_VIOLATION`.

On success the flow's `final_adverse_action_at` is set to the current server time, its `notification_status` moves to `FINAL_DELIVERED`, and its `procedural_status` moves to `FINALIZED`. The candidate's `eligibility_posture` is recomputed to `ADVERSE` and then promoted to `LOCKED` if every sibling order of the candidate has reached a terminal state. The cascade also cancels every non-terminal sibling order of the same candidate, moving each from its current non-terminal status to `CANCELLED`. An `AuditEvent` of type `FINAL_ADVERSE_ISSUED` is appended, chained off the prior `PRE_ADVERSE_SENT` event for the same order subject. The two state machines — the order's `status` and the flow's `procedural_status` versus `notification_status` — evolve independently up to this terminal pair, after which both are pinned.

The race between Final Adverse issuance and a late dispute on the same order is decided by which write commits first. If a `Dispute` is created with `status` of `OPEN` before Final Adverse commits, the later Final Adverse call is rejected with `ERR_OPEN_DISPUTE_BLOCKS_FINAL`. If Final Adverse commits first, the later dispute call sees the parent order in a terminal status and is rejected with `ERR_INVALID_STATE` (HTTP 409). A similar race between a `Recruiter` cancellation and the system's auto-transition into `AWAITING_ADJUDICATION` serializes on the order's `status` field — whichever write commits first wins, and the loser receives `ERR_INVALID_STATE`.

### 3.9. Cancellation, Abandonment, and Audit Trail Access

A `Recruiter` may cancel an order while it is in `INTAKE`, `IN_VERIFICATION`, or `PRE_ADVERSE_ISSUED`. From `INTAKE` the cancel is unconditional. From `IN_VERIFICATION` the cancel requires either that the candidate has revoked their `ConsentDisclosure` (status `REVOKED`) or that no items have yet been adjudicated; on cancel, items in `IN_PROGRESS` are marked cancelled, the items' `severity_score` is frozen at its current value, the candidate's `eligibility_posture` is recomputed (returning to `ELIGIBLE` if no other open orders remain), and an `AuditEvent` of type `ORDER_CANCELLED` is appended. From `PRE_ADVERSE_ISSUED` a cancel by the `Recruiter` is permitted when no open dispute remains; the associated `AdverseActionFlow` transitions from `PRE_AWAITING_DISPUTE_WINDOW` to `ABANDONED`, and the parent order moves to `CANCELLED`. The `AdverseActionFlow`'s terminal pair on this branch is `ABANDONED`; the flow's other terminal pair, `FINALIZED`, is reached only through Final Adverse Action.

A candidate's `eligibility_posture` is recomputed whenever one of their orders changes status or the flow's `final_adverse_action_at` is set. The rule is purely aggregate: if any order remains in a non-terminal status — anything other than `COMPLETED_CLEAR`, `TERMINATED_ADVERSE`, or `CANCELLED` — the posture is `UNDER_REVIEW`. Otherwise, if any `TERMINATED_ADVERSE` order exists where the elapsed time since `final_adverse_action_at` is at most 365 days, the posture is `LOCKED`; that lock window expires the day after the 365th day. Otherwise, if any historical `TERMINATED_ADVERSE` order exists at all, the posture is `ADVERSE`. Otherwise, the posture is `ELIGIBLE`.

Every order's audit chain is retrievable as an array of `AuditEvent` rows in chronological order. Each row carries the `event_type` (`CONSENT_RECORDED`, `CONSENT_REVOKED`, `ORDER_OPENED`, `ITEM_RETURNED`, `ITEM_FAILED`, `DISPUTE_OPENED`, `DISPUTE_RESOLVED`, `PRE_ADVERSE_SENT`, `FINAL_ADVERSE_ISSUED`, `ORDER_CANCELLED`, or `REWORK_REQUESTED`), the `subject_entity` (one of `Candidate`, `BackgroundCheckOrder`, `VerificationItem`, `Dispute`, `AdverseActionFlow`, or `ConsentDisclosure`), the `subject_id`, the acting `actor_role` (such as `Recruiter`, `Adjudicator`, `Candidate`, or `system`) and `actor_user_id`, the `previous_event_id` linking back to the prior event for the same subject (null only for the first event on a subject), and the `payload_hash` whose SHA-256 input is the concatenation of `subject_id`, `event_type`, `actor_user_id`, `created_at`, and `previous_event_id`. The trail is readable by both `Recruiter` and `Adjudicator`.

### 3.10. Test-Driving the Logical Clock

For test orchestration of the cooling-off window, a `PlatformAdmin` may advance the server's logical clock and then run the periodic sweep. The clock-advance capability accepts a `seconds` integer and pushes the server's current time forward by that many seconds; no automatic state transitions fire as a result. The sweep capability then promotes every order whose flow has reached the conditions for `READY_FOR_FINAL` (current server time at or after `earliest_final_eligible_at`, no open dispute) from `PRE_ADVERSE_ISSUED` to `AWAITING_FINAL` and the flow from `PRE_AWAITING_DISPUTE_WINDOW` to `READY_FOR_FINAL`. The same sweep recomputes the `eligibility_posture` of any candidate whose 365-day `LOCKED` window has expired, demoting them from `LOCKED` to `ADVERSE`.

## 4. Endpoint Definitions

Endpoints that create a new resource — a candidate, a consent disclosure, an order, or a dispute — return HTTP 201 on success. Every other successful operation, including all GETs and all state-changing actions on existing resources, returns HTTP 200. Error responses follow the codes documented in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/fcra/candidates` | Register a new candidate. | `Recruiter` |
| GET | `/fcra/candidates/{candidateId}` | Read a candidate. | `Recruiter`, `Adjudicator`, `Candidate` |
| PATCH | `/fcra/candidates/{candidateId}` | Update mutable candidate fields. | `Recruiter` |
| GET | `/fcra/candidates` | List candidates with pagination and `eligibility_posture` filter. | `Recruiter`, `Adjudicator` |
| POST | `/fcra/candidates/{candidateId}/consent` | Record a `ConsentDisclosure` (supersedes any prior `ACTIVE` consent). | `Recruiter`, `Candidate` |
| POST | `/fcra/candidates/{candidateId}/consent/revoke` | Candidate revokes their own active consent. | `Candidate` |
| GET | `/fcra/jurisdiction-policies` | List all configured jurisdiction policies. | `Recruiter`, `Adjudicator` |
| PUT | `/fcra/jurisdiction-policies/{code}` | Upsert a jurisdiction policy. | `PlatformAdmin` |
| POST | `/fcra/orders` | Open a new `BackgroundCheckOrder`. | `Recruiter` |
| GET | `/fcra/orders/{orderId}` | Read an order including `composite_decision`. | `Recruiter`, `Adjudicator`, `Candidate` |
| GET | `/fcra/orders` | List orders with pagination and `status`/`candidate_id` filters. | `Recruiter`, `Adjudicator` |
| POST | `/fcra/orders/{orderId}/start-verification` | Move order from `INTAKE` to `IN_VERIFICATION`. | `Recruiter` |
| POST | `/fcra/orders/{orderId}/cancel` | Cancel an order in `INTAKE`, `IN_VERIFICATION`, or `PRE_ADVERSE_ISSUED`. | `Recruiter` |
| POST | `/fcra/orders/{orderId}/pre-adverse` | Issue Pre-Adverse Action. | `Adjudicator` |
| POST | `/fcra/orders/{orderId}/final-adverse` | Issue Final Adverse Action. | `Adjudicator` |
| POST | `/fcra/orders/{orderId}/request-rework` | Send order back for re-verification on `target_item_ids`. | `Adjudicator` |
| POST | `/fcra/orders/{orderId}/resume-verification` | After rework, move items from `REWORK_REQUIRED` back to `IN_PROGRESS`. | `Adjudicator` |
| GET | `/fcra/orders/{orderId}/audit-trail` | Return the `AuditEvent` chain for this order. | `Recruiter`, `Adjudicator` |
| GET | `/fcra/verification-items/{itemId}` | Read a verification item. | `Recruiter`, `Adjudicator`, `Candidate` |
| POST | `/fcra/verification-items/{itemId}/return` | Vendor returns the `raw_finding` payload. | `Verifier` |
| POST | `/fcra/disputes` | Candidate opens a dispute on a verification item. | `Candidate` |
| GET | `/fcra/disputes/{disputeId}` | Read a dispute. | `Candidate`, `Adjudicator` |
| POST | `/fcra/disputes/{disputeId}/resolve` | Resolve dispute as `UPHELD` or `OVERTURNED`. | `Adjudicator` |
| POST | `/fcra/_clock/advance` | Advance the server logical clock by `seconds`. | `PlatformAdmin` |
| POST | `/fcra/_sweep/run` | Run the periodic sweep (cooling-off promotion, lock-window expiry). | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_AUTH_REQUIRED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_CANDIDATE_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_BAN_THE_BOX_VIOLATION` | 422 |
| `ERR_SALARY_HISTORY_BAN` | 422 |
| `ERR_CONSENT_INVALID` | 422 |
| `ERR_CONSENT_TIMESTAMP_INVALID` | 422 |
| `ERR_CONSENT_CANDIDATE_MISMATCH` | 422 |
| `ERR_SOD_VIOLATION` | 422 |
| `ERR_COOLING_OFF_NOT_ELAPSED` | 422 |
| `ERR_OPEN_DISPUTE_BLOCKS_FINAL` | 422 |
| `ERR_PACKAGE_SET_INVALID` | 422 |
| `ERR_CANDIDATE_NOT_ELIGIBLE` | 422 |
| `ERR_DISPUTE_NOT_OWNED` | 403 |
| `ERR_REWORK_CAP_EXCEEDED` | 422 |
| `ERR_AUDIT_CHAIN_BROKEN` | 422 |
| `ERR_CANDIDATE_EMAIL_TAKEN` | 409 |
| `ERR_ADVERSE_FLOW_ALREADY_EXISTS` | 409 |
| `ERR_STALE_VERSION` | 409 |
| `ERR_VALIDATION_FAILED` | 400 |
