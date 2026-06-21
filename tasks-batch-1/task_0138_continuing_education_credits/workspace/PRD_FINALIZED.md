# Continuing Education Credits API — Product Requirements Document

## 1. Introduction

Licensed professionals — attorneys, physicians, nurses, accountants — must earn and document a fixed number of continuing-education credit hours within each board-defined renewal cycle before their license can be renewed. The bookkeeping behind that simple-sounding obligation is anything but simple: credits are awarded only by accredited providers, must fall inside both the licensee's renewal window and the provider's accreditation window, are categorized (ethics, substance-abuse, general) with per-category minimums, may be partially carried forward to the next cycle, may be supplemented by credits earned in another jurisdiction under reciprocity, and are periodically subject to audit under strict segregation-of-duties controls.

This API is the system of record for that entire lifecycle. It tracks license boards and the requirements they impose, the providers they accredit and the courses those providers offer, the licensees who complete courses, the renewal cycles those completions count toward, the audits that verify compliance, and the certificates issued when a cycle is successfully renewed. The core challenge the system solves is keeping every derived figure — a cycle's earned hours, its carryover surplus, a licensee's audit-risk score, the live deadline-reminder state — continuously reconciled against a web of state transitions and cascading side effects, so that a single provider revocation or a single reciprocity reversal ripples correctly through every affected cycle without leaving a stale or contradictory number behind.

This document specifies the complete contract: the global conventions every endpoint obeys, the business rules and workflows that govern each entity, the endpoint catalogue, and the error vocabulary.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All collections are mounted at the top level of the URL space; there is no shared API prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying a malformed one, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This requirement is universal — even the test-driving clock endpoint requires valid headers. When the headers are present and well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as follows: `BoardAdmin`, `Provider`, `Licensee`, and `Auditor`.

A `BoardAdmin` is a board operator. When `X-User-Role` is `BoardAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as the `initiated_by_user_id` on an `Audit` that this operator initiates, or as the `decided_by_user_id` on an audit decided by an operator acting as an `Auditor`) but does not compare it to any entity's `id`.

A `Provider` is an accredited continuing-education provider that owns and manages its courses. When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting `Provider`; ownership checks on any resource that references a `Provider` compare the resource's foreign-key field to `X-User-ID`. Concretely, a provider may create a `Course` only under a `provider_id` equal to its own `X-User-ID`; a violation is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

A `Licensee` is a licensed professional who logs completions, resubmits rejected ones, requests reciprocity, attests during audits, and renews cycles. When `X-User-Role` is `Licensee`, `X-User-ID` is the `id` of the acting `Licensee`; ownership checks on any resource that references a `Licensee` compare the resource's foreign-key field to `X-User-ID`. A licensee may act only on its own completions, renewal cycles, and reciprocity grants; otherwise the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

An `Auditor` is an independent reviewer who decides audits. When `X-User-Role` is `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as the `decided_by_user_id` of any audit the auditor decides but does not compare it to any entity's `id`. The auditor identity is nonetheless load-bearing: an auditor's `X-User-ID` must differ from the `initiated_by_user_id` recorded on the audit (see §2.7).

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10, with a minimum of 1 and a maximum of 100; a request for more than 100 items is served 100. The `offset` defaults to 0 and is the zero-based index of the first item returned. Every list response includes `limit`, `offset`, `total_count` (the total number of matching items irrespective of the page window), and `has_more` (true when more items exist beyond the current page) inside `meta`. Unless an endpoint's narrative states otherwise, list results are sorted by `created_at` in ascending order.

### 2.4. Common Resource Properties, Identifiers, and Timestamps

Every resource is assigned a server-minted `id` that is a UUID with no type prefix. Two timestamp fields, `created_at` and `updated_at`, are ISO 8601 UTC values with three fractional digits; `created_at` records first persistence and `updated_at` advances on every mutation. Most entities also carry an integer `version` that starts at its initial value and increments by one on each mutation that changes the resource.

Two entities are deliberately lightweight and carry **only** `id` and `created_at` — they have neither `updated_at` nor `version`, because they are immutable once written: the `Certificate` and the `Attestation`. For every other entity (`LicenseBoard`, `CreditRequirement`, `Provider`, `Course`, `Licensee`, `RenewalCycle`, `Completion`, `Audit`, `ReciprocityGrant`), the full set of common properties — `id`, `created_at`, `updated_at`, and `version` — is present.

### 2.5. Precision and Rounding

All credit-hour quantities are carried to one decimal place using round-half-up. Where a calculation sums several contributions, the underlying sum is computed exactly and rounded once at the end, except where a calculation explicitly pins a different order (the carryover computation rounds per category *before* summing — see §3.6). Audit-risk scores are integer-valued and clamped to the closed range from 0 to 100. Serial sequences and counts are integers.

### 2.6. Optimistic Concurrency Control on Renewal

Renewing a renewal cycle is guarded by optimistic concurrency control. The renew request must carry `expected_renewal_cycle_version`, a non-optional field whose value is the `version` of the target `RenewalCycle` that the client last observed. The server compares it against the cycle's current `version`. If a verify cascade, a reciprocity approval, or any other writer has advanced the cycle's `version` since the client last read it — which may have recomputed its earned hours and possibly flipped it into `REQUIREMENTS_MET` — the renew is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from renewing against a cycle state it has not seen. No other endpoint accepts or requires a version field.

### 2.7. Segregation of Duties on Audit Decisions

The board operator who initiates an audit and the auditor who decides it must be different people. When an audit is initiated, the initiating `BoardAdmin`'s `X-User-ID` is stored on the audit as `initiated_by_user_id`. When the audit is later decided, the deciding auditor's `X-User-ID` must differ from that stored `initiated_by_user_id`; if they are equal, the decision is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). On a successful decision the deciding identity is recorded as `decided_by_user_id`.

### 2.8. Hierarchical Consistency and Cascading Recomputation

Because earned-hour figures are derived from many contributing rows, every change to a contributing row triggers an immediate recomputation of the affected renewal cycle, and any state change implied by the new numbers is applied in the same operation. Mutations advance `updated_at` and increment `version` on the changed resource. The most consequential cascade is provider revocation, which propagates four hops deep: deactivating the provider's courses, invalidating verified completions on those courses, recomputing each touched cycle's earned hours, and reverting cycles that no longer satisfy their requirement. The cascade is detailed in §3.2. The system's consistency model is immediate: all derived fields and dependent states reflect the new reality before the triggering request returns.

### 2.9. Nested Resource Retrieval and Left-to-Right Validation

Several read endpoints are addressed through a parent path segment (for example, a board's requirements, a provider's courses, a licensee's renewal cycles, a cycle's completions, audits, reciprocity grants, or certificate). When a request names resources positionally, the system validates them left to right: the parent named earlier in the path is checked for existence before the child. Any referenced resource — whether named in the path or in the request body — that does not exist yields `ERR_NOT_FOUND` (HTTP 404). Body-referenced foreign keys are likewise validated for existence.

### 2.10. Validation Ordering

When several checks could fire on one request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication is checked first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN`), then existence of every referenced resource (`ERR_NOT_FOUND`), then resource ownership for entity-backed actors (`ERR_NOT_RESOURCE_OWNER`), then whether the target is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). Endpoint-specific business checks — the cross-entity accreditation gate, segregation of duties, temporal window checks, overlap, cooldown, single-open-audit, jurisdiction, requirements-met, carryover-cap, and the renewal version check — are evaluated after those foundational checks, in the order their workflows describe in §3. Malformed bodies (a missing required field, a bad enum value, or a non-positive credit-hour value) are rejected with `ERR_INVALID_REQUEST` (HTTP 400); a numeric field that is syntactically fine but out of its allowed range (negative hours, or a board's non-general category minimums summing past the board total) is rejected with `ERR_VALIDATION_RANGE` (HTTP 422).

### 2.11. The Logical Clock

Time-dependent logic — deadline reminders, audit cooldowns, and the temporal window checks — reads a single server-side current-UTC clock rather than wall-clock time. An administrative test-driving capability advances that logical clock to a supplied instant; the value to set is provided as `to_iso8601`. All freshness comparisons in this specification are made against that clock.

## 3. Business Logic & Workflows

This section specifies the behaviour of each workflow. Field names introduced here are the JSON keys the API reads and writes; relationships between entities are expressed through the actions that link them rather than through schema declarations.

### 3.1. Boards, Requirements, Providers, and Courses: the Accreditation Spine

A `BoardAdmin` establishes a **license board** by supplying its `name`, a two-letter uppercase `jurisdiction_code` (for example, "CA"), and the `credit_unit` it accredits — one of `CEU`, `CME`, or `CLE`. The pair of `jurisdiction_code` and `credit_unit` must be unique across boards. The admin also fixes the renewal mechanics: `cycle_length_months`, an integer of at least 1 (commonly 24 or 36) that defines how long a renewal window runs; `total_required_hours`, the total credit hours required per cycle, a value of at least 0 carried to one decimal place; and three policy knobs that govern downstream behaviour. The `carryover_cap_hours` caps how much verified surplus may roll into the next cycle and defaults to 10.0 when omitted; the `audit_cooldown_days` sets the minimum number of days that must elapse between the close of one audit and the start of the next on the same licensee, defaulting to 365; and the `reminder_lead_days` sets how many days before a deadline the reminder begins, defaulting to 60. All three are at least 0; the two hour-valued fields are carried to one decimal place.

Each board may declare per-category **credit requirements**. A `BoardAdmin` adds a requirement by naming its `category` — one of `ETHICS`, `SUBSTANCE`, or `GENERAL` — and a `min_hours` value (at least 0, one decimal place) that the licensee must earn in that category each cycle. The requirement is tied to its board through the board it is created under, recorded as `board_id`; the pair of `board_id` and `category` is unique, so a board cannot declare two requirements for the same category. There is an aggregate ceiling: the sum of `min_hours` across all of a board's non-`GENERAL` requirements must not exceed that board's `total_required_hours`. A request that would breach this ceiling is rejected with `ERR_VALIDATION_RANGE`.

A **provider** is registered by a `BoardAdmin` with a `name` and the `board_id` of the accrediting board. A newly registered provider begins in `APPLIED`. Accreditation is a deliberate act: accrediting an `APPLIED` provider requires the request to supply an `accredited_until` instant that is strictly later than the current clock, and on success the system sets the provider's `accredited_from` to the current clock, stores the supplied `accredited_until`, advances the provider to `ACCREDITED`, and increments the provider's `version`. A completion is verifiable only if it was completed within the half-open accreditation window that runs from `accredited_from` inclusive up to `accredited_until` exclusive.

An accredited provider may be **suspended** (moving from `ACCREDITED` to `SUSPENDED`); suspension freezes new verifications but does not deactivate courses and is reversible. A suspended provider may be **reinstated** back to `ACCREDITED`. Each of suspend and reinstate increments the provider's `version`. A provider may be **revoked** from either `ACCREDITED` or `SUSPENDED`, advancing it to the terminal `REVOKED` state. Revocation triggers the system's deepest cascade, described next.

A **course** is created under a provider — by that `Provider` acting on its own `provider_id`, or by a `BoardAdmin` — with a `title`, a `category` (`ETHICS`, `SUBSTANCE`, or `GENERAL`), and `credit_hours` awarded on verified completion (strictly greater than 0, one decimal place). A course begins `ACTIVE` and becomes `DEACTIVATED` only as a consequence of its provider being revoked.

### 3.2. Provider Revocation: the Four-Hop Cascade

Revoking a provider is the most far-reaching operation in the system, and its side effects must all land atomically. The transition itself moves the provider to `REVOKED` and increments its `version`. Then, in order:

First, every `ACTIVE` course belonging to the revoked provider is set to `DEACTIVATED`. Second, for each course thus deactivated, every `VERIFIED` completion recorded against that course is set to the terminal `INVALIDATED` state. Third, each completion invalidation recomputes the earned-hour figures (`final_earned_hours` and `provisional_earned_hours`) of the renewal cycle that completion belonged to, applying the credit-tally rule of §3.5. Fourth, for any cycle that was in `REQUIREMENTS_MET` and whose `final_earned_hours` now falls below what the requirement demands, the cycle reverts from `REQUIREMENTS_MET` back to `OPEN`, and its carryover surplus `carryover_out_hours` is reset to 0. A cycle that still satisfies its requirement after the recomputation stays `REQUIREMENTS_MET`. Each affected cycle's `updated_at` and `version` advance with the recomputation.

### 3.3. The Renewal Cycle: Window, Carryover, and Live Reminders

A **renewal cycle** is the central accounting unit. A `BoardAdmin` or the owning `Licensee` opens a cycle by supplying the `licensee_id`, the `board_id`, and an inclusive UTC `cycle_start`. The system computes the exclusive `cycle_end` by adding the board's `cycle_length_months` to the start; the renewal deadline is exactly `cycle_end`. The cycle begins `OPEN`.

Cycles for the same licensee on the same board must not overlap in time, under closed-open semantics: the occupied interval of an existing cycle runs from its `cycle_start` inclusive to its `cycle_end` exclusive. A new cycle whose `cycle_start` exactly equals a prior cycle's `cycle_end` is permitted (the windows are adjacent, not overlapping); any new start that lands strictly inside a prior cycle's interval is rejected with `ERR_CYCLE_OVERLAP`.

A cycle may carry surplus forward from the licensee's immediately preceding cycle on the same board. The amount carried in is supplied as `carryover_in_hours` (defaulting to 0, at least 0, one decimal place) and is conserved: it must equal the prior cycle's `carryover_out_hours`. A supplied `carryover_in_hours` that exceeds either the prior cycle's `carryover_out_hours` or the board's `carryover_cap_hours` is rejected with `ERR_CARRYOVER_EXCEEDS_CAP`.

Each cycle continuously exposes several computed figures: `provisional_earned_hours` and `final_earned_hours` (the two credit tallies of §3.5), `reciprocity_hours` (the sum of approved reciprocal credit, §3.7), `carryover_out_hours` (the surplus eligible to roll forward, §3.6), and `reminder_status`. The `reminder_status` is never persisted stale — it is re-derived on every read of a cycle or its reminder sub-resource against the current clock. Define the reminder instant as the cycle's `cycle_end` minus the board's `reminder_lead_days`. When the current clock is before that reminder instant, `reminder_status` is `NOT_DUE`. When the current clock is at or after the reminder instant but before `cycle_end`, it is `DUE`. When the current clock is at or after `cycle_end`, it is `OVERDUE`. The boundaries are inclusive on the later side: exactly at the reminder instant the status is `DUE`, and exactly at `cycle_end` it is `OVERDUE`. Comparisons are day-granular.

Renewal is the licensee's culminating act and is described in §3.8.

### 3.4. Licensees, Logging Completions, and the Verification Loop

A **licensee** is registered by a `BoardAdmin` with a `full_name`, the `home_board_id` of the board under which the professional primarily renews, and a `license_number` that identifies the license. The `license_number` must be unique together with `home_board_id`, so the same number may recur under different home boards but not twice under the same one. Each licensee also carries a computed `audit_risk_score` (§3.9) that defaults to 0 at registration. Like most resources, a licensee exposes lifecycle and bookkeeping fields through its `status`-style state where applicable; the licensee itself has no workflow state, but the entities it owns — completions, cycles, audits, and reciprocity grants — each track their own `status` enumeration as described throughout this section.

A `Licensee` (acting on its own `licensee_id`) or a `BoardAdmin` logs a **completion** by supplying the `licensee_id`, the `course_id` of the completed course, the `cycle_id` the credit applies to, and the `completed_at` instant the course was finished. At submission the system snapshots the course's award onto the completion: `awarded_hours` is copied from the course's `credit_hours` and `category` is copied from the course's `category`, and these snapshots are immune to any later edits to the course. The completion also records `is_late`, a flag set true when `completed_at` falls within `reminder_lead_days` of the cycle's `cycle_end` — that is, when it lands in the reminder/overdue window — and false otherwise. A new completion starts in `PENDING_VERIFICATION`, and logging it immediately recomputes the cycle's provisional tally.

The `completed_at` instant must fall inside the renewal window, meaning at or after `cycle_start` and strictly before `cycle_end`; a completion logged outside that window is rejected with `ERR_COMPLETION_OUT_OF_WINDOW`. The same error guards verification, where the window check is additionally applied against the provider's accreditation window.

A `BoardAdmin` **verifies** a pending completion. Verification is permitted only when the completion is `PENDING_VERIFICATION`, when the cycle is `OPEN` or `REQUIREMENTS_MET`, and when the cross-entity accreditation gate is satisfied: the provider behind the completed course must currently be `ACCREDITED` (not `SUSPENDED`, not `REVOKED`). A verify attempted while that provider is not accredited is rejected with `ERR_PROVIDER_NOT_ACCREDITED`. The system also re-checks that `completed_at` lies within the half-open provider accreditation window from `accredited_from` inclusive to `accredited_until` exclusive; a verify outside that window is rejected with `ERR_COMPLETION_OUT_OF_WINDOW`. On success the completion moves to `VERIFIED`, the cycle's `final_earned_hours` and `provisional_earned_hours` are recomputed, and if the cycle's requirement is now satisfied on verified hours the cycle bubbles up from `OPEN` to `REQUIREMENTS_MET` and its `carryover_out_hours` is computed.

A `BoardAdmin` may instead **reject** a pending completion. Rejection moves it from `PENDING_VERIFICATION` to `REJECTED`, optionally recording a `reason`, recomputes the cycle's provisional tally to drop this completion's hours, and recomputes the owning licensee's `audit_risk_score` under the intake variant (§3.9). A rejected completion is not terminal: the owning `Licensee` may **resubmit** it, moving it from `REJECTED` back to `PENDING_VERIFICATION` (permitted only while the cycle is `OPEN` or `REQUIREMENTS_MET`) and recomputing the cycle's provisional tally to re-add this completion's hours. The loop `REJECTED → PENDING_VERIFICATION → VERIFIED` is therefore a revision cycle. A completion also reaches the terminal `INVALIDATED` state, but only as a system consequence of its parent course being deactivated through provider revocation (§3.2); invalidation recomputes the cycle's `final_earned_hours` and `provisional_earned_hours`.

### 3.5. Credit Tally: Provisional and Final Variants

Whenever a cycle's contributing rows change — a completion is verified, rejected, resubmitted, or invalidated, or a reciprocity grant is approved or revoked — the system recomputes two earned-hour figures for that cycle. Both share a base equal to the cycle's `carryover_in_hours` plus its `reciprocity_hours`.

The **provisional** figure, `provisional_earned_hours`, is that base plus the sum of `awarded_hours` over every completion on the cycle whose status is `PENDING_VERIFICATION` or `VERIFIED`. The **final** figure, `final_earned_hours`, is that same base plus the sum of `awarded_hours` over only the completions whose status is `VERIFIED`. Completions in `REJECTED` or `INVALIDATED` contribute to neither. Because the provisional set is a superset of the final set, `provisional_earned_hours` is always at least `final_earned_hours`. Each sum is accumulated exactly and the result rounded half-up to one decimal place. The provisional figure is what the licensee sees mid-cycle and what feeds the deadline-reminder projection; the final figure is the authoritative compliance number used for requirement satisfaction, certificate issuance, and attestation matching.

### 3.6. Requirement Satisfaction and Carryover Surplus

Whether a cycle has **met its requirement** is decided after every credit-tally recompute and at certificate issuance, and it is always computed on `VERIFIED` hours only — never on provisional hours, so a cycle never reaches `REQUIREMENTS_MET` on the strength of pending completions. The computation decomposes the cycle's verified hours by category, where each category's hours equal that category's verified-completion hours plus any carryover and approved-reciprocity hours tagged to that category.

The board's general requirement is derived rather than declared: it equals the board's `total_required_hours` minus the sum of `min_hours` across every non-`GENERAL` credit requirement of that board. For each non-`GENERAL` category that has a requirement with minimum *m*, the system allocates against that minimum the lesser of the category's hours and *m*; any hours beyond *m* are that category's overflow and spill into a shared general pool, while a shortfall below *m* is that category's deficit. The general pool is the cycle's general-category hours plus the total overflow spilled from all non-`GENERAL` categories. The general deficit is the general requirement minus the general pool, floored at 0. The requirement is met exactly when every non-`GENERAL` category's deficit is 0 and the general deficit is also 0. A category holding precisely its minimum is satisfied — comparisons are inclusive, treating exactly-the-minimum as met.

When (and only when) the requirement is met, the system computes the surplus eligible to roll forward, `carryover_out_hours`, by a **per-category-then-sum-then-cap** rule whose order is pinned. For each of `ETHICS`, `SUBSTANCE`, and `GENERAL`, take that category's own hours (its verified, carryover-in, and approved-reciprocity hours of that category) and subtract that category's own requirement — the category minimum for `ETHICS` and `SUBSTANCE`, and the derived general requirement for `GENERAL` — flooring the result at 0 to get that category's surplus. Crucially, carryover does **not** pool the ethics or substance overflow into general the way the requirement test does; each category keeps only its own excess over its own requirement. Round each of the three category surpluses half-up to one decimal place *first*, then sum the three rounded surpluses to get the raw carryover, then cap that raw carryover at the board's `carryover_cap_hours`. The pinned order matters at fractional boundaries — three surpluses of 1.04, 5.04, and 0.04 round per category to 1.0, 5.0, and 0.0 for a total of 6.0, which is not the same as rounding their 6.12 sum to 6.1. When the raw carryover exceeds the board cap, `carryover_out_hours` saturates at `carryover_cap_hours` and the surplus above the cap is forfeited.

The `carryover_out_hours` is 0 until the cycle first reaches `REQUIREMENTS_MET` or `RENEWED`. It is recomputed when a cycle (re-)enters `REQUIREMENTS_MET` — including when an audit passes and the cycle returns to `REQUIREMENTS_MET` — and finalized on renew. It is reset to 0 whenever the cycle reverts to `OPEN` (because a recompute dropped final hours below the requirement) or lapses.

### 3.7. Reciprocity: Cross-Jurisdiction Credit and Compensating Reversal

A licensee who earned credit in another jurisdiction may seek to apply it under reciprocity. A `Licensee` (on its own `licensee_id`) or a `BoardAdmin` requests a **reciprocity grant** by supplying the `licensee_id`, the `target_cycle_id` the credit should apply to, the `source_jurisdiction_code` the credit originates from, the `category` it should count toward (`ETHICS`, `SUBSTANCE`, or `GENERAL`), and the `credit_hours` requested (strictly greater than 0, one decimal place). The `source_jurisdiction_code` must differ from the `jurisdiction_code` of the target cycle's board; a same-jurisdiction request is rejected with `ERR_SAME_JURISDICTION`, and this same-jurisdiction check is enforced both at request time and again at approval time. A new grant starts in `REQUESTED`.

A `BoardAdmin` **approves** a requested grant only when the target cycle is `OPEN` or `REQUIREMENTS_MET` and the jurisdictions still differ. Approval adds the grant's `credit_hours` to the target cycle's `reciprocity_hours`, recomputes that cycle's `final_earned_hours` and `provisional_earned_hours`, and — if the requirement is now met — bubbles the cycle from `OPEN` to `REQUIREMENTS_MET` and computes its `carryover_out_hours`. A `BoardAdmin` may instead **deny** a requested grant, moving it to the terminal `DENIED` state with no effect on any cycle.

An approved grant may be **revoked** as a compensating action, but only while the target cycle is `OPEN` or `REQUIREMENTS_MET`. Revocation moves the grant from `APPROVED` to `DENIED` and is the exact inverse of approval: it subtracts the grant's `credit_hours` from the target cycle's `reciprocity_hours`, recomputes the cycle's earned hours, and — if the requirement is no longer met — reverts the cycle from `REQUIREMENTS_MET` to `OPEN` and resets `carryover_out_hours` to 0. An approve followed by a revoke leaves the cycle's `reciprocity_hours` and `final_earned_hours` exactly as they were before the approval.

### 3.8. Renewing a Cycle and Issuing a Certificate

When a cycle is in `REQUIREMENTS_MET`, the owning `Licensee` may **renew** it. Renewal is permitted only when the cycle is in `REQUIREMENTS_MET`, when no audit for the cycle is in a non-terminal state, when the cycle currently satisfies its requirement on `VERIFIED` hours, and when the optimistic-concurrency check passes. The request supplies `expected_renewal_cycle_version`; if it does not equal the cycle's current `version`, the renewal is rejected with `ERR_STALE_VERSION` (§2.6). If the verified hours do not satisfy the requirement — an empty or insufficient verified set — the renewal is rejected with `ERR_REQUIREMENTS_NOT_MET`.

On a successful renewal the cycle advances from `REQUIREMENTS_MET` to the terminal `RENEWED` state, its `carryover_out_hours` is finalized by the carryover computation, its `version` increments, and a **certificate** is issued for the cycle. The certificate references the cycle through its `cycle_id`, carries a `serial_number` assigned at issuance, snapshots the cycle's `final_earned_hours` at issuance into `total_hours_certified`, and records its `issued_at` timestamp (equal to the certificate's `created_at`). The `serial_number` is a per-board monotonic serial formatted as the board's `jurisdiction_code`, a hyphen, and a zero-padded six-digit sequence number.

### 3.9. Audits, Attestation, and the Audit-Risk Score

A `BoardAdmin` **initiates an audit** against a cycle by supplying the `cycle_id`. The audit may be initiated only when the cycle is `OPEN` or `REQUIREMENTS_MET` and when no other audit for that cycle is currently in a non-terminal state; the single-open business check that guards a second concurrent audit names `ERR_AUDIT_ALREADY_OPEN`. Because initiating the first audit moves its cycle into `AUDIT_HOLD` (leaving it neither `OPEN` nor `REQUIREMENTS_MET`), a real second-initiation attempt fails the foundational state precondition — which §2.10 orders before the single-open business check — and is therefore rejected with `ERR_INVALID_STATE`. Initiation is further gated by a cooldown: a new audit on a licensee is allowed only if the current clock is at or after the most recently closed audit's `closed_at` plus the board's `audit_cooldown_days` — the full buffer must have elapsed — otherwise the request is rejected with `ERR_AUDIT_COOLDOWN_ACTIVE`. On initiation the system records the initiating operator's identity as `initiated_by_user_id`, denormalizes the cycle's `licensee_id` onto the audit for filtered lookup, sets `initiated_at` (equal to `created_at`), starts the audit in `INITIATED`, and moves the cycle into `AUDIT_HOLD` (from either `OPEN` or `REQUIREMENTS_MET`).

The audit then proceeds through an attestation handshake. A `BoardAdmin` (or, on a later revision pass, an `Auditor`) **requests attestation**, moving the audit to `ATTESTATION_PENDING` from either `INITIATED` or `UNDER_REVIEW`. The owning `Licensee` then **submits an attestation** against the `audit_id`, supplying a signed `statement` affirming the records are accurate and the `attested_hours` total claimed. Submission moves the audit from `ATTESTATION_PENDING` to `UNDER_REVIEW` and recomputes the licensee's `audit_risk_score` under the review-final variant. The `attested_hours` must equal the cycle's `final_earned_hours` at attestation time, or the audit will fail on review.

An `Auditor` **decides** the audit by supplying a `decision`. The decider's `X-User-ID` must differ from the recorded `initiated_by_user_id`, or the decision is rejected with `ERR_SEGREGATION_OF_DUTIES` (§2.7). A decision is allowed only when the audit is `UNDER_REVIEW`. The audit passes — moving to the terminal `PASSED` — when the `decision` is to pass and the latest attestation's `attested_hours` equals the cycle's `final_earned_hours`. The audit fails — moving to the terminal `FAILED` — when the `decision` is to fail, or when the latest attestation's `attested_hours` does not equal the cycle's `final_earned_hours` even on a pass decision. Either outcome records `decided_by_user_id` and sets `closed_at` to the current clock. The decision then bubbles up to the held cycle: on a pass, if the cycle still satisfies its requirement it returns from `AUDIT_HOLD` to `REQUIREMENTS_MET` and its `carryover_out_hours` is recomputed, but if it no longer satisfies the requirement it returns to `OPEN` with `carryover_out_hours` reset to 0; on a fail, the cycle moves from `AUDIT_HOLD` to the terminal `LAPSED` and its `carryover_out_hours` is reset to 0.

The licensee's `audit_risk_score` is a weighted, integer-valued figure clamped to the range 0 through 100, stored on the licensee. It weights three counts: each late completion contributes 3 points, each rejected completion contributes 5 points, and each approved reciprocity grant contributes 2 points; the weighted sum is then capped at 100. The two recompute moments use different inclusion sets and therefore typically yield different scores for the same licensee. The **intake variant**, recomputed when a completion is rejected, is an early pessimistic estimate: it counts late completions whose status is `PENDING_VERIFICATION`, `VERIFIED`, or `REJECTED`, and counts all `REJECTED` completions. The **review-final variant**, recomputed when an attestation is submitted, is the settled figure: it counts late completions only among `VERIFIED` completions and excludes rejections that were later resubmitted and verified. Both variants count the licensee's `APPROVED` reciprocity grants identically.

## 4. Endpoint Definitions

The following table summarizes every endpoint. Successful creation of a new resource returns HTTP 201; successful reads and state-changing actions on existing resources return HTTP 200. Request bodies, response payloads, and side effects are intentionally not repeated here — reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/license-boards` | Create a license board | `BoardAdmin` |
| GET | `/license-boards/{id}` | Fetch a license board | `BoardAdmin`, `Provider`, `Licensee`, `Auditor` |
| POST | `/license-boards/{id}/requirements` | Add a credit requirement to a board | `BoardAdmin` |
| GET | `/license-boards/{id}/requirements` | List a board's credit requirements | `BoardAdmin`, `Provider`, `Licensee`, `Auditor` |
| GET | `/credit-requirements/{id}` | Fetch a single credit requirement | `BoardAdmin`, `Provider`, `Licensee`, `Auditor` |
| POST | `/providers` | Register a provider (starts `APPLIED`) | `BoardAdmin` |
| GET | `/providers/{id}` | Fetch a provider | `BoardAdmin`, `Provider`, `Licensee`, `Auditor` |
| GET | `/providers` | List providers, filterable by `board_id` | `BoardAdmin`, `Provider`, `Licensee`, `Auditor` |
| POST | `/providers/{id}/accredit` | Accredit an `APPLIED` provider | `BoardAdmin` |
| POST | `/providers/{id}/suspend` | Suspend an `ACCREDITED` provider | `BoardAdmin` |
| POST | `/providers/{id}/reinstate` | Reinstate a `SUSPENDED` provider | `BoardAdmin` |
| POST | `/providers/{id}/revoke` | Revoke a provider; runs the four-hop cascade | `BoardAdmin` |
| POST | `/courses` | Create a course under a provider | `Provider`, `BoardAdmin` |
| GET | `/courses/{id}` | Fetch a course | `BoardAdmin`, `Provider`, `Licensee`, `Auditor` |
| GET | `/providers/{id}/courses` | List a provider's courses | `BoardAdmin`, `Provider`, `Licensee`, `Auditor` |
| POST | `/licensees` | Register a licensee | `BoardAdmin` |
| GET | `/licensees/{id}` | Fetch a licensee (includes computed `audit_risk_score`) | `BoardAdmin`, `Licensee`, `Auditor` |
| GET | `/licensees` | List licensees, filterable by `home_board_id` | `BoardAdmin`, `Auditor` |
| POST | `/renewal-cycles` | Open a renewal cycle for a licensee on a board | `BoardAdmin`, `Licensee` |
| GET | `/renewal-cycles/{id}` | Fetch a renewal cycle (computed hours and reminder) | `BoardAdmin`, `Licensee`, `Auditor` |
| GET | `/renewal-cycles` | List renewal cycles, filterable by `board_id` / `licensee_id` | `BoardAdmin`, `Auditor` |
| GET | `/licensees/{id}/renewal-cycles` | List a licensee's renewal cycles | `BoardAdmin`, `Licensee`, `Auditor` |
| GET | `/renewal-cycles/{id}/reminder` | Computed read of a cycle's deadline reminder state | `BoardAdmin`, `Licensee`, `Auditor` |
| POST | `/renewal-cycles/{id}/renew` | Renew a qualifying cycle; issues a certificate (OCC-guarded) | `Licensee` |
| POST | `/completions` | Log a course completion against a cycle | `Licensee`, `BoardAdmin` |
| GET | `/completions/{id}` | Fetch a completion | `BoardAdmin`, `Licensee`, `Auditor` |
| GET | `/completions` | List completions, filterable by `licensee_id` / `course_id` / `cycle_id` | `BoardAdmin`, `Licensee`, `Auditor` |
| GET | `/renewal-cycles/{id}/completions` | List a cycle's completions | `BoardAdmin`, `Licensee`, `Auditor` |
| POST | `/completions/{id}/verify` | Verify a pending completion | `BoardAdmin` |
| POST | `/completions/{id}/reject` | Reject a pending completion | `BoardAdmin` |
| POST | `/completions/{id}/resubmit` | Resubmit a rejected completion | `Licensee` |
| GET | `/certificates/{id}` | Fetch a certificate | `BoardAdmin`, `Licensee`, `Auditor` |
| GET | `/renewal-cycles/{id}/certificate` | List the certificate(s) issued for a cycle | `BoardAdmin`, `Licensee`, `Auditor` |
| POST | `/audits` | Initiate an audit against a cycle | `BoardAdmin` |
| GET | `/audits/{id}` | Fetch an audit | `BoardAdmin`, `Licensee`, `Auditor` |
| GET | `/audits` | List audits, filterable by `licensee_id` / `cycle_id` | `BoardAdmin`, `Auditor` |
| GET | `/renewal-cycles/{id}/audits` | List a cycle's audits | `BoardAdmin`, `Licensee`, `Auditor` |
| POST | `/audits/{id}/request-attestation` | Move an audit to `ATTESTATION_PENDING` | `BoardAdmin`, `Auditor` |
| POST | `/audits/{id}/attestations` | Licensee submits an attestation | `Licensee` |
| GET | `/audits/{id}/attestations` | List an audit's attestations | `BoardAdmin`, `Licensee`, `Auditor` |
| POST | `/audits/{id}/decide` | Auditor decides PASS/FAIL; bubbles to the cycle | `Auditor` |
| POST | `/reciprocity-grants` | Request a reciprocity grant against a target cycle | `Licensee`, `BoardAdmin` |
| GET | `/reciprocity-grants/{id}` | Fetch a reciprocity grant | `BoardAdmin`, `Licensee`, `Auditor` |
| GET | `/reciprocity-grants` | List reciprocity grants, filterable by `licensee_id` | `BoardAdmin`, `Licensee`, `Auditor` |
| GET | `/renewal-cycles/{id}/reciprocity-grants` | List a cycle's reciprocity grants | `BoardAdmin`, `Licensee`, `Auditor` |
| POST | `/reciprocity-grants/{id}/approve` | Approve a reciprocity grant | `BoardAdmin` |
| POST | `/reciprocity-grants/{id}/deny` | Deny a requested reciprocity grant | `BoardAdmin` |
| POST | `/reciprocity-grants/{id}/revoke` | Revoke an approved reciprocity grant (compensating) | `BoardAdmin` |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC clock | `BoardAdmin` |

## 5. Error Code Catalogue

The trigger conditions for each error are described in the relevant §2 and §3 narratives; this catalogue lists only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PROVIDER_NOT_ACCREDITED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_COMPLETION_OUT_OF_WINDOW` | 422 |
| `ERR_CYCLE_OVERLAP` | 409 |
| `ERR_AUDIT_COOLDOWN_ACTIVE` | 409 |
| `ERR_AUDIT_ALREADY_OPEN` | 409 |
| `ERR_SAME_JURISDICTION` | 422 |
| `ERR_REQUIREMENTS_NOT_MET` | 409 |
| `ERR_CARRYOVER_EXCEEDS_CAP` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_VALIDATION_RANGE` | 422 |
