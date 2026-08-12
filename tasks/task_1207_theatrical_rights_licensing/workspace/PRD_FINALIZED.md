# Theatrical Rights Licensing API — Product Requirements Document

## 1. Introduction

Amateur and stock theatrical licensing is a paperwork-heavy business. A community theatre in Ohio wants to mount *Our Town*; a school in Birmingham wants a perusal copy of a new musical; a semi-professional company in Sydney wants to add a streaming-video grant to a license it has already signed. Behind each request sits a catalogue of titles, a map of territory restrictions, a classification decision that separates amateur from professional productions, a royalty computation sensitive to house size and box-office gross, a deposit-and-late-fee lifecycle for rented scripts and scores, and a small but consequential compliance surface — alteration requests, recording grants, breach declarations, and fines.

This document specifies an API that manages that entire pipeline end to end. The system tracks a catalogue of dramatic and musical works, evaluates each incoming application against title availability and territory restriction rules, distinguishes amateur from professional productions via a deterministic classification rule, issues license agreements with a royalty quote computed at issuance, and then follows those agreements through performance reporting, royalty settlement, material rental logistics, alteration requests, recording grants, amendment, cancellation, and breach. Fines are assessed for overdue material, unauthorized alterations, unauthorized recordings, and lost stock, and an organization's standing is suspended when it carries unresolved breach fines.

The API is mounted under `/licensing`. It is consumed by licensor staff in three operational roles, by applicant organizations interacting with their own licenses, and by finance staff reconciling payments and fines. A logical clock, settable by administrative clients, drives every temporal rule — overdue sweeps, write-off aging, and window-based availability — so behavior is deterministic regardless of wall-clock time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. Both are required on every endpoint; a request missing either header, or presenting a role string the server does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Five roles exist, spelled exactly as follows: `RightsAdmin`, `LicensingOfficer`, `Applicant`, `MaterialsClerk`, `FinanceOfficer`.

The `Applicant` role is entity-backed by `Organization`: when `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Organization`, and any ownership check on a resource that references an `Organization` compares the resource's foreign-key field to `X-User-ID`. When an entity-backed caller attempts to act on a resource owned by a different organization — for example, an `Applicant` submitting a `LicenseApplication` whose `organization_id` does not match the `X-User-ID` header — the request is rejected with `ERR_FORBIDDEN_OWNER_MISMATCH` (HTTP 403).

The four remaining roles are opaque operator identifiers not tied to any persisted entity. When `X-User-Role` is `RightsAdmin`, `LicensingOfficer`, `MaterialsClerk`, or `FinanceOfficer`, `X-User-ID` is an opaque staff identifier; the server may record it (for example, as `decided_by_user_id` on an `AlterationRequest` when a `RightsAdmin` decides the request) but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters, `limit` and `offset`. The default `limit` is 10; the minimum accepted value is 1 and the maximum is 100. The default `offset` is 0. List results are always sorted by `created_at` ascending. The `meta` block of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`; `total_count` reflects the total number of matching records after filters are applied, and `has_more` is true whenever `offset + limit < total_count`.

### 2.4. Common Resource Properties, Money, and Temporal Conventions

Every resource carries an `id` that is a server-minted UUID with no type prefix. Most resources also carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version` field that is an integer starting at 1 and incremented on every mutation. Two entities deviate from this pattern. `RoyaltyPayment` carries `id` and `created_at` only — it has neither `updated_at` nor `version`, because payments are append-only and are never edited in place. `AvailabilitySnapshot` likewise carries only `id` and `created_at` — snapshots are point-in-time computations and are never edited, so `updated_at` and `version` are absent.

All monetary amounts are stored as integer cents. Where a calculation produces a fractional cent, the result is rounded half-up to the nearest cent at the specific step the calculation rule identifies; the step at which rounding occurs is part of the rule's definition and is not deferred to a final aggregation.

Datetimes are ISO 8601 UTC. Temporal comparisons across the system operate at seconds granularity; the server renders every datetime it emits — resource fields and envelope timestamps alike — as an ISO 8601 UTC timestamp with three fractional digits (for example, `2026-06-05T00:00:00.000Z`). A datetime range is expressed as a `window_start` and `window_end`; on `TerritoryRestriction` both endpoints are inclusive (closed interval), whereas on an exclusive-run `LicenseAgreement` availability test the window is treated as half-open at the end. A range whose `window_start` is not strictly before its `window_end` is malformed and is rejected with `ERR_INVALID_TEMPORAL` (HTTP 400); the same code covers malformed datetime strings and a rental `due_date` that is not in the future. This strict-inequality rule applies to fields named `window_start` and `window_end` — a `TerritoryRestriction` creation window and an amendment's `new_window_end` relative to the agreement's existing `window_start`. A `LicenseApplication`'s requested run is expressed as `first_performance_date` and `last_performance_date`, not `window_start`/`window_end`; those two fields are validated only as well-formed ISO 8601 UTC datetimes, and no ordering constraint is imposed between them — a single-performance run whose `first_performance_date` equals its `last_performance_date` is well-formed, and the agreement that approval creates from such an application carries that coincident instant as both its `window_start` and its `window_end`.

### 2.5. The Logical Clock

The server maintains a logical clock distinct from wall-clock time. At server startup, before any administrative client has called the clock-advance capability, the logical clock reads exactly `2026-05-01T00:00:00Z` and must not fall back to wall-clock time. A `RightsAdmin` may advance the logical clock by supplying a `to_iso8601` ISO 8601 UTC timestamp to an admin-only test-driving capability. Advancing the clock is the trigger that fires the system's scheduled sweeps: any non-terminal `MaterialRental` whose `due_date` has passed transitions to `OVERDUE`, and any `LicenseAgreement` whose contracted window has fully elapsed transitions to `COMPLETED`. Every deadline, expiry, and window rule in the system reads this logical clock, never wall-clock time, so behavior is fully deterministic under test.

### 2.6. Hierarchical Path Validation and Optimistic Concurrency

Nested endpoints validate their path parameters left-to-right: when a URL contains more than one path variable, the server resolves each path segment in order from the leftmost resource outward, and the first segment that fails to resolve yields `ERR_NOT_FOUND` (HTTP 404). A request that references a foreign key in its body — `title_id`, `organization_id`, or `agreement_id` — has that reference resolved after path validation; an unresolvable body foreign key yields `ERR_REFERENCED_NOT_FOUND` (HTTP 422).

Two write endpoints are guarded by optimistic concurrency control. Applying an amendment to a `LicenseAgreement` requires the caller to supply `expected_agreement_version` carrying the agreement's `version` as last observed by the caller; a mismatch against the current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), capturing the case where another writer has already advanced the agreement's amendment chain. Approving a `LicenseApplication` requires the caller to supply `expected_application_version` carrying the application's `version` as last observed; a mismatch against the current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), capturing the case where a return-for-info or resubmission has legitimately superseded the reviewing officer's snapshot. Endpoints not named here do not accept a version field.

### 2.7. Validation Ordering

When multiple validation rules could fire on the same request, they are evaluated in the following priority order. Authentication comes first (missing or undeclared headers, `ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then entity-ownership for entity-backed callers (`ERR_FORBIDDEN_OWNER_MISMATCH`). Path-parameter existence follows (`ERR_NOT_FOUND`), then body foreign-key existence (`ERR_REFERENCED_NOT_FOUND`), then payload shape and typing (`ERR_INVALID_REQUEST`), then temporal well-formedness (`ERR_INVALID_TEMPORAL`), then state-machine from-state checks (`ERR_INVALID_STATE`). Only after all of those pass do domain business rules fire — organization standing (`ERR_ORG_SUSPENDED`), title status (`ERR_TITLE_WITHDRAWN`), availability and territory conflicts (`ERR_TITLE_UNAVAILABLE`, `ERR_TERRITORY_RESTRICTED`, `ERR_EXCLUSIVE_RUN_CONFLICT`), alteration restrictions (`ERR_ALTERATION_PROHIBITED`), recording-grant restrictions (`ERR_RECORDING_PROHIBITED`, `ERR_STREAMING_CLASSIFICATION_BLOCK`), rental-kind shape (`ERR_RENTAL_KIND_MISMATCH`), performance-window fit (`ERR_PERFORMANCE_OUTSIDE_WINDOW`), payment-amount sanity (`ERR_PAYMENT_AMOUNT_INVALID`), fine waivability (`ERR_FINE_NOT_WAIVABLE`), cancellation eligibility (`ERR_PERFORMANCE_ALREADY_HELD`), write-off aging (`ERR_WRITE_OFF_TOO_EARLY`), report timing (`ERR_REPORT_TOO_EARLY`), and finally OCC staleness (`ERR_STALE_VERSION`). The ordering matters most when several rules could fire — for example, a request to approve an application whose `version` has moved and whose title is also restricted surfaces `ERR_TITLE_UNAVAILABLE`, not `ERR_STALE_VERSION`, because the availability check outranks the OCC check.

### 2.8. Tiered Royalty Pricing and Constants

The royalty engine prices a performance by combining a house-size multiplier and a classification multiplier against the title's configured flat fee and gross-percentage basis points. The house-size ladder has four tiers: at most 199 seats yields a multiplier of 1.00, between 200 and 399 seats yields 1.25, between 400 and 799 seats yields 1.60, and 800 seats or more yields 2.00. The classification ladder has two rungs: an `AMATEUR` production multiplies by 1.00, a `PROFESSIONAL` production by 1.50. The flat component and the percentage component are each rounded half-up to integer cents at the step where they are computed; the total royalty for an engagement is the per-performance royalty multiplied by the relevant performance count.

## 3. Business Logic & Workflows

### 3.1. Building the Title Catalogue

A `RightsAdmin` populates the catalogue by creating `Title` records. A title has a `name` and an `author`, and is classified by `title_kind` as one of `PLAY`, `MUSICAL`, or `MUSICAL_WITH_SCORE`. The royalty basis is fixed at catalogue-entry time via `royalty_basis`, which is one of `PER_PERFORMANCE`, `GROSS_PERCENT`, or `HYBRID`. The flat fee `base_flat_fee_cents` applies under `PER_PERFORMANCE` and `HYBRID`; the percentage `gross_percent_bp` — basis points of gross, where one basis point is one hundredth of a percent — applies under `GROSS_PERCENT` and `HYBRID`. A title whose script or score is restricted is flagged via `restricted_material`; on such titles alterations are prohibited by default and the higher daily overdue fee applies. The remaining catalogue fields are the `perusal_fee_cents` charged for a perusal copy, the refundable `rental_deposit_cents` held per `MaterialRental`, the standard `late_fee_per_day_cents`, the elevated `restricted_late_fee_per_day_cents` that supersedes the standard rate on restricted titles, and the `recording_royalty_flat_cents` base royalty for cast-recording grants. A new title starts in `status` `ACTIVE` and at `version` 1.

When a title is retired from the catalogue, a `RightsAdmin` withdraws it; the title's `status` becomes `WITHDRAWN`. Any attempt to file a new application against a `WITHDRAWN` title, or to create a new rental against one, is rejected with `ERR_TITLE_WITHDRAWN`.

Territory restrictions hang off a title. A `RightsAdmin` creates a `TerritoryRestriction` against a title by supplying the `territory_code` (an ISO-style code such as `US-CA` or `GB-LON`), the `restriction_kind` (one of `BLACKOUT`, `EXCLUSIVE_RUN`, `PRO_TOUR_OVERLAP`), the restriction window `window_start` and `window_end` — both inclusive — and the `blocks_classification` value, one of `AMATEUR`, `PROFESSIONAL`, or `BOTH`. A new restriction is `active` true. Lifting a restriction is a separate administrative action that flips `active` to false; a lifted restriction no longer blocks applications. The catalogue supports listing titles with optional filters on `status`, `title_kind`, and `restricted_material`, and listing restrictions with optional filters on `territory_code` and `active`, plus a reverse-lookup list by `title_id`.

### 3.2. Registering Applicant Organizations

A `RightsAdmin` registers each producing organization. An `Organization` carries a `legal_name`, an `org_kind` drawn from `SCHOOL`, `COMMUNITY`, `SEMI_PRO`, and `PROFESSIONAL_COMPANY`, and a `home_territory_code`. Newly registered organizations start with `standing` `GOOD`. Standing is the lever that connects compliance to downstream behavior: while an organization is `SUSPENDED`, it cannot file new applications, report performance grosses, or have new rentals shipped to it — each of those attempts is rejected with `ERR_ORG_SUSPENDED`. Standing is restored only when the organization's last `ASSESSED` fine is resolved (see §3.8).

### 3.3. From Application Draft to Approval

An `Applicant` begins the licensing conversation by drafting a `LicenseApplication`. The draft names the desired `title_id` and asserts the applicant's own `organization_id`, declares the `requested_territory_code`, and self-declares a `requested_classification` of `AMATEUR` or `PROFESSIONAL`. The draft also carries the production facts that drive classification and pricing: `venue_seating_capacity` (at least one seat), `ticket_top_price_cents` (the highest advertised single-ticket price), `performers_compensated` (true when any cast member is paid), `admission_charged` (true when any ticket is sold), `projected_gross_cents` (the applicant's projected total box-office gross across all performances), `performance_count`, and the requested window `first_performance_date` through `last_performance_date`. A draft starts in `status` `DRAFT` with `review_round` 0. An applicant may edit a draft — touching any of `requested_territory_code`, `requested_classification`, `venue_seating_capacity`, `ticket_top_price_cents`, `performers_compensated`, `admission_charged`, `projected_gross_cents`, `performance_count`, `first_performance_date`, or `last_performance_date` — and each edit bumps the application's `version`.

Submitting the draft transitions the application from `DRAFT` to `SUBMITTED`. The server records `submitted_at` as the current clock and computes an `AvailabilitySnapshot` for the combination of title, requested territory, requested classification, and requested window. The snapshot's verdict is captured in `available` and the snapshot records the blocking identifiers in `blocking_restriction_ids` and `blocking_agreement_ids` so a reviewer can see exactly which restrictions or exclusive runs are in the way; `computed_at` records when the verdict was reached. Snapshots are persisted and re-readable later through the snapshot-reading capability.

A `LicensingOfficer` picks up a `SUBMITTED` application by moving it to `UNDER_REVIEW`. That action increments `review_round` by one and recomputes the `determined_classification` from the classification rule. The classification rule is deterministic. If the organization's `org_kind` is `PROFESSIONAL_COMPANY`, the determination is `PROFESSIONAL`. If `performers_compensated` is true, the determination is `PROFESSIONAL`. If `admission_charged` is false and the `org_kind` is `SCHOOL`, the determination is `AMATEUR`. If `ticket_top_price_cents` is at least 4000 cents (a $40 top ticket), the determination is `PROFESSIONAL`. If `venue_seating_capacity` is at least 500 seats, the determination is `PROFESSIONAL`. Otherwise the determination is `AMATEUR`. This determined value, not the applicant's self-declaration, drives royalty pricing and territory-restriction matching.

Review does not always proceed straight to a decision. When the officer needs more information, they return the application for information, optionally attaching `notes`; the application moves from `UNDER_REVIEW` to `RETURNED_FOR_INFO`. The applicant may edit a returned application — the same set of fields as in draft — and resubmit it; resubmission moves the application back to `SUBMITTED`, refreshes `submitted_at`, and recomputes the `AvailabilitySnapshot`.

Approval is the high-stakes transition. An approval request carries `expected_application_version` matching the application's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) so a reviewing officer cannot approve a snapshot of the application that has since been edited. Approval then evaluates three availability preconditions, in this order. First, the latest `AvailabilitySnapshot` for the application must have `available` true, otherwise the approval is rejected with `ERR_TITLE_UNAVAILABLE`. Second, no active `TerritoryRestriction` may cover the requested territory and requested window with a `blocks_classification` matching either the application's `determined_classification` or `BOTH`, otherwise the approval is rejected with `ERR_TERRITORY_RESTRICTED`. Third, no other `LicenseAgreement` may be `ACTIVE` on the same `title_id` with an overlapping window in the same territory where that agreement holds exclusive-run rights, otherwise the approval is rejected with `ERR_EXCLUSIVE_RUN_CONFLICT`. When all three pass, the application's `status` becomes `APPROVED`, `determined_classification` is persisted, the application's `version` is incremented by one, and a `LicenseAgreement` is created.

Rejection is the simpler sibling: from `UNDER_REVIEW`, an officer rejects the application, optionally supplying a `reason`; the application's `status` becomes `REJECTED` and no agreement is created.

### 3.4. The License Agreement at Issuance

A `LicenseAgreement` is the contract issued on approval. It copies `application_id`, `title_id`, `organization_id`, and `territory_code` from the application, fixes `classification` from the application's `determined_classification`, sets `house_seating_capacity` from the application's venue size, fixes `contracted_performance_count` from the application's performance count, and copies `window_start` and `window_end` from the requested performance dates. The new agreement starts with `license_status` `PENDING_PAYMENT`, `payment_status` `UNPAID`, `royalty_mode` `QUOTED`, and `version` 1. The quoted royalty `quoted_royalty_total_cents` is computed by the performance-royalty rule in its `QUOTED` variant over the application's projected figures, and the opening `royalty_balance_cents` is that quoted total. The `settled_royalty_total_cents` field is null until completion. The `amendment_seq` counter starts at 0, and `supersedes_agreement_id` is null unless the agreement later supersedes a prior one through an amendment-with-reissue.

An agreement's lifecycle has two parallel state dimensions. The `license_status` dimension runs `PENDING_PAYMENT` → `ACTIVE` → one of `COMPLETED`, `CANCELLED`, or `BREACHED`. The `payment_status` dimension runs `UNPAID` → `PARTIALLY_PAID` → `PAID_IN_FULL` and may be set to `REFUNDED` from `UNPAID`, `PARTIALLY_PAID`, or `PAID_IN_FULL`. The two evolve independently except where a transition below pins them together.

Activation is the first gate. A `RightsAdmin` activates a `PENDING_PAYMENT` agreement when the applicant has funded the royalty. Full funding is the normal path — `payment_status` has reached `PAID_IN_FULL`. A partial-payment activation rule permits activation when cumulative payments cover at least half of the quoted royalty: the `royalty_balance_cents` is at most the ceiling of `quoted_royalty_total_cents` divided by two. Either precondition flips `license_status` to `ACTIVE`.

A `FinanceOfficer` records money against the agreement by creating a `RoyaltyPayment` carrying `amount_cents`. The payment's `paid_at` is set to the current clock. The amount must be at least 1 cent and at most the current `royalty_balance_cents`; a payment violating either bound is rejected with `ERR_PAYMENT_AMOUNT_INVALID`. Payments against an agreement in `license_status` `CANCELLED` or `BREACHED` are not accepted. Each payment appends a `RoyaltyPayment` row and decrements `royalty_balance_cents` by `amount_cents`. When the cumulative paid amount after a payment is still strictly less than the balance before the payment, `payment_status` moves to (or stays in) `PARTIALLY_PAID`. When the cumulative paid amount reaches the balance before the payment, `royalty_balance_cents` is set to 0 and `payment_status` becomes `PAID_IN_FULL`. Payments are listed per agreement and via a reverse-lookup list filterable by `agreement_id`.

Amendments are how contracted terms evolve after issuance. A `RightsAdmin` applies an amendment, supplying `expected_agreement_version` for OCC, an optional `new_window_end`, an optional `additional_performances` count, and an `amendment_note`. A mismatch between `expected_agreement_version` and the agreement's current `version` is rejected with `ERR_STALE_VERSION`. Applying the amendment increments `amendment_seq` by one and increments the agreement's `version` by one. When `additional_performances` is greater than zero, `contracted_performance_count` is incremented by that amount, `quoted_royalty_total_cents` is recomputed via the performance-royalty rule in its `QUOTED` variant, and `royalty_balance_cents` is adjusted by the delta between the new and old quoted totals. Amendments are rejected with `ERR_AMENDMENT_ON_TERMINAL` when the target agreement is in `COMPLETED`, `CANCELLED`, or `BREACHED`.

### 3.5. Performances and Settlement

Once an agreement is `ACTIVE`, the applicant declares performances. A performance-declaration request names the agreement and supplies a `performance_at` datetime. The datetime must fall within the agreement's `[window_start, window_end]` window, and no two performances for the same agreement may share a `performance_at`; either violation is rejected with `ERR_PERFORMANCE_OUTSIDE_WINDOW`. A new `Performance` starts in `status` `SCHEDULED` with `gross_reported` false and `reported_attendance` and `reported_gross_cents` at zero.

After the performance has occurred, the applicant files a gross report supplying `reported_attendance` and `reported_gross_cents`. The report is rejected with `ERR_REPORT_TOO_EARLY` if the current clock has not yet reached `performance_at`. The report is rejected with `ERR_ORG_SUSPENDED` if the organization is not in `GOOD` standing. The report requires the agreement to be `ACTIVE`. When it lands, the performance's `status` moves from `SCHEDULED` to `HELD`, `gross_reported` flips to true, the reported figures are persisted, and `royalty_cents` is computed for that single performance via the performance-royalty rule in its `SETTLED` variant — using this performance's `reported_gross_cents`, the agreement's `house_seating_capacity`, and a divisor of 1 for the per-performance computation. As a cascade side effect, the parent agreement's `version` is incremented; this is the signal a holding client uses to detect that reporting activity has moved the agreement under them.

An applicant can also cancel a scheduled performance; the performance must currently be `SCHEDULED` and the agreement must be `ACTIVE`. Cancellation moves the performance to `CANCELLED` and recomputes its `royalty_cents` via the performance-royalty rule with the performance excluded from the contracted count — but only when the agreement is still in `royalty_mode` `QUOTED`; no refund of already-quoted royalty occurs until completion or cancellation.

Completion is system-driven. When every `Performance` for the agreement is in a terminal state (`HELD` or `CANCELLED`), every `HELD` performance has `gross_reported` true, and the current clock has passed `window_end`, the agreement transitions from `ACTIVE` to `COMPLETED`. The transition flips `royalty_mode` to `SETTLED`, computes `settled_royalty_total_cents` via the performance-royalty rule in its `SETTLED` variant aggregated over all `HELD` performances (cancelled performances excluded), and recomputes `royalty_balance_cents` as the settled total minus the sum of all `RoyaltyPayment` amounts. If the recomputed balance is negative — meaning the applicant has overpaid relative to actual grosses — the overage is refunded and `payment_status` is set to `REFUNDED`.

Cancellation and breach are the two failure exits from `ACTIVE`. Cancellation, initiated by a `RightsAdmin` with a `reason`, is refused with `ERR_PERFORMANCE_ALREADY_HELD` when any `Performance` for the agreement is already `HELD`. When it lands, every `Performance` row moves to `CANCELLED`. Every `MaterialRental` in `RESERVED`, `SHIPPED`, `RECEIVED`, or `RETURN_IN_TRANSIT` has its overdue handling skipped, and its `deposit_status` moves to `RETURNED` if no late fee has accrued, otherwise it remains `HELD` pending fine settlement; rentals already in `OVERDUE` stay `OVERDUE`. Every `RecordingGrant` in `REQUESTED` or `APPROVED` moves to `REVOKED`. Every `AlterationRequest` in `SUBMITTED` moves to `DENIED`. The cancellation-refund rule is applied across the agreement's payments: the rule measures `days_until_window_start` as the whole days between the current clock and `window_start`, applies a refund fraction of 1.00 when at least 30 days remain, 0.50 when at least 7 days remain, and 0.00 otherwise; the refundable pool is the sum of payments multiplied by the fraction, rounded half-up once; and the pool is then allocated back to payments oldest-first, each payment's refunded portion capped by its own amount. When the full royalty was returned, `payment_status` moves to `REFUNDED`.

Breach is the punitive exit. A `RightsAdmin` declares a breach by supplying a `breach_reason` — one of unauthorized alteration observed, unauthorized recording distributed, or performance outside the licensed window. The agreement moves from `ACTIVE` to `BREACHED`. A `Fine` is created with `fine_kind` mapped from the breach reason to `UNAUTHORIZED_ALTERATION` or `UNAUTHORIZED_RECORDING` and `status` `ASSESSED`; the fine amount comes from the breach-fine rule, which sets `amount_cents` to the larger of a 500,000-cent floor and twice the `quoted_royalty_total_cents` for `UNAUTHORIZED_ALTERATION`, or three times the `quoted_royalty_total_cents` for `UNAUTHORIZED_RECORDING`. The organization's `standing` flips to `SUSPENDED` until the fine is resolved. Every `RecordingGrant` on the agreement moves to `REVOKED`. Every `Performance` still `SCHEDULED` moves to `CANCELLED`.

### 3.6. Material Rentals and the Deposit Lifecycle

A `MaterialsClerk` creates a `MaterialRental` against an `ACTIVE` agreement. The creation payload names the `agreement_id` and supplies `scripts_qty`, `scores_qty`, and the return-by `due_date`. The `due_date` must be in the future, otherwise the request is rejected with `ERR_INVALID_TEMPORAL`. A title whose `title_kind` is `PLAY` carries no score, so `scores_qty` must be zero; and the combined quantity `scripts_qty + scores_qty` must be at least one. Either violation is rejected with `ERR_RENTAL_KIND_MISMATCH`. The new rental starts in `status` `RESERVED`, with `deposit_cents` set equal to the title's `rental_deposit_cents` (the deposit is flat per rental, not per copy), `deposit_status` `HELD`, and `accrued_late_fee_cents` 0.

Shipping is a clerk action that requires the rental to be `RESERVED`, the agreement `ACTIVE`, the organization in `GOOD` standing, and the deposit to be held — `deposit_status` `HELD`. Shipping when the deposit is not held is rejected with `ERR_DEPOSIT_NOT_HELD`. When it lands, the rental moves from `RESERVED` to `SHIPPED`. The applicant confirms receipt, moving the rental from `SHIPPED` to `RECEIVED`. When the run ends, the applicant ships the materials back, moving the rental from `RECEIVED` to `RETURN_IN_TRANSIT`.

The overdue sweep is system-driven. When the logical clock advances past a non-terminal rental's `due_date`, the rental transitions from `SHIPPED`, `RECEIVED`, or `RETURN_IN_TRANSIT` into `OVERDUE`. The sweep recomputes `accrued_late_fee_cents` via the overdue-fine rule in its `PROJECTED` variant, projecting through the current clock; no `Fine` row is created at sweep time.

Return receipt is the settlement point. A clerk receiving returned materials (on time or late) supplies an optional `damage_lines` payload — each line carrying an `amount_cents` and a `damage_fraction` — and the rental moves from `RETURN_IN_TRANSIT` (or, for a late return, from `OVERDUE`) to `RETURNED`. The server sets `returned_at`, finalizes `accrued_late_fee_cents` via the overdue-fine rule in its `ACTUAL` variant (using `returned_at` as the evaluation clock), and applies the deposit-settlement rule. If the finalized late fee is greater than zero, a `Fine` of kind `OVERDUE_MATERIAL` is created in `status` `ASSESSED`.

The overdue-fine rule has a deliberately pinned evaluation order. The number of overdue days is the floor of the difference between the evaluation clock and `due_date` in whole days, clamped below at zero. The daily rate is the title's `restricted_late_fee_per_day_cents` when `restricted_material` is true, otherwise the title's `late_fee_per_day_cents`. The raw fee is the product of days and daily rate. Only then is the raw fee capped — at twice the rental's `deposit_cents`. The capped value becomes `accrued_late_fee_cents`. The order matters because the deposit-forfeiture branch in the next step depends on the capped fee, not the raw one.

The deposit-settlement rule then walks deductions. Each damage line contributes a deduction equal to `amount_cents` multiplied by `damage_fraction`, rounded half-up per line; the per-line rounded values are then summed to a `total_damage_cents`. The total deduction is the sum of `total_damage_cents` and `accrued_late_fee_cents`. When the total deduction is zero, `deposit_status` becomes `RETURNED` and the full `deposit_cents` is refunded. When the total deduction is strictly less than `deposit_cents`, `deposit_status` becomes `PARTIALLY_FORFEITED` and the refund is the deposit minus the deduction. Otherwise `deposit_status` becomes `FORFEITED` and nothing is refunded. The per-line rounding happens before summation — summing first and then rounding would give different cents.

A rental that never comes back is declared lost by a `MaterialsClerk`. The transition is from `OVERDUE` to `LOST` and is permitted only once the current clock has reached `due_date` plus 30 days; attempting it earlier is rejected with `ERR_RENTAL_NOT_DUE_LOST`. Declaring a rental lost sets `deposit_status` to `FORFEITED` and creates a `Fine` of kind `LOSS` whose amount comes from the replacement-cost rule.

### 3.7. Alteration Requests and Recording Grants

Two kinds of add-on ride on an `ACTIVE` agreement: alterations and recordings.

An `Applicant` submits an `AlterationRequest` naming the `agreement_id`, choosing an `alteration_kind` from `CUT`, `GENDER_SWAP`, `TEXT_CHANGE`, `STAGING_CHANGE`, and `TRANSLATION`, and providing a free-text `description`. The new request starts in `status` `SUBMITTED`. Approval and denial are `RightsAdmin` actions. Approval requires the agreement to be `ACTIVE` and enforces the restricted-material rule: when the agreement's title has `restricted_material` true, only `CUT` and `STAGING_CHANGE` may be approved; an attempt to approve `TEXT_CHANGE`, `GENDER_SWAP`, or `TRANSLATION` on a restricted-material title is rejected with `ERR_ALTERATION_PROHIBITED`. Either decision records `decided_by_user_id` from the acting admin's `X-User-ID`.

An `Applicant` requests a `RecordingGrant` by naming the `agreement_id`, selecting a `grant_kind` from `CAST_RECORDING_AUDIO`, `STREAMING_VIDEO`, and `ARCHIVAL_VIDEO`, and selecting a `distribution_scope` from `CAST_CREW_ONLY`, `PAYWALL`, and `PUBLIC_FREE`. The grant starts in `status` `REQUESTED`. Approval is a `RightsAdmin` action and carries two preconditions. First, a `STREAMING_VIDEO` grant requires the agreement's `classification` to be `AMATEUR` — professional streaming requires a separate contract, and the approval is rejected with `ERR_STREAMING_CLASSIFICATION_BLOCK` when the classification is `PROFESSIONAL`. Second, a `PUBLIC_FREE` distribution scope combined with a `STREAMING_VIDEO` grant on a title whose `restricted_material` is true is rejected with `ERR_RECORDING_PROHIBITED`. When approval lands, the grant's `recording_royalty_cents` is computed by the recording-royalty rule and the agreement's `royalty_balance_cents` is incremented by that amount.

The recording-royalty rule starts from the title's `recording_royalty_flat_cents` as a base. The multiplier depends on `grant_kind`: 1.00 for `CAST_RECORDING_AUDIO`, 0.50 for `ARCHIVAL_VIDEO`, and 2.00 for `STREAMING_VIDEO`. The multiplier is then adjusted by `distribution_scope`: a `PUBLIC_FREE` scope multiplies by 1.50 and a `PAYWALL` scope multiplies by 1.25; `CAST_CREW_ONLY` leaves the multiplier unchanged. The final `recording_royalty_cents` is the base times the final multiplier, rounded half-up to integer cents.

A grant that has been approved can be exercised by the applicant. The grant must be `APPROVED`, the agreement must be `ACTIVE`, and the current clock must fall within the agreement's `[window_start, window_end]` window; then the grant moves to `EXERCISED`. Denial moves a `REQUESTED` grant to `DENIED`. Revocation is system-driven: when the parent agreement transitions to `CANCELLED` or `BREACHED`, every `APPROVED` grant moves to `REVOKED` and the agreement's `royalty_balance_cents` is decremented by the grant's `recording_royalty_cents` to reverse the earlier debit.

### 3.8. Fines, Standing, and Resolution

A `Fine` is the system's monetary penalty record. A fine names the `organization_id` being fined, optionally references a `rental_id` (null on breach fines) and an `agreement_id` (null when the fine is purely rental-related), carries a `fine_kind` from `OVERDUE_MATERIAL`, `UNAUTHORIZED_ALTERATION`, `UNAUTHORIZED_RECORDING`, and `LOSS`, an `amount_cents` computed by the rule that produced the fine, and a `status` that starts at `ASSESSED`.

Three exits resolve a fine. A `FinanceOfficer` can mark a fine paid, moving it from `ASSESSED` to `PAID`. A `FinanceOfficer` can waive a fine, but only when `fine_kind` is `OVERDUE_MATERIAL` or `LOSS` — breach fines of kind `UNAUTHORIZED_ALTERATION` and `UNAUTHORIZED_RECORDING` are never waivable, and the waiver is rejected with `ERR_FINE_NOT_WAIVABLE`. Finally, a `FinanceOfficer` can write off a fine, but only once the fine's age is at least 180 days — attempting to write off a younger fine is rejected with `ERR_WRITE_OFF_TOO_EARLY`. Write-off does not restore standing.

Standing restoration is tied to the last `ASSESSED` fine. When a fine is paid or waived, if that fine was the last `ASSESSED` fine for its organization, the organization's `standing` returns to `GOOD`. A write-off does not trigger this restoration; the organization stays `SUSPENDED` until a payment or waiver clears the assessment backlog.

## 4. Endpoint Definitions

All endpoints live under the `/licensing` mount. Successful resource-creation requests return HTTP 201; successful modifications and reads return HTTP 200. Error responses use the error envelope from §2.2 with the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /licensing/titles | Create a Title catalog entry | RightsAdmin |
| GET | /licensing/titles/{title_id} | Read a Title | RightsAdmin, LicensingOfficer, Applicant, MaterialsClerk, FinanceOfficer |
| GET | /licensing/titles | List titles (filterable) | RightsAdmin, LicensingOfficer, Applicant, MaterialsClerk, FinanceOfficer |
| POST | /licensing/titles/{title_id}/withdraw | Withdraw a title from the catalog | RightsAdmin |
| POST | /licensing/titles/{title_id}/restrictions | Create a TerritoryRestriction on a title | RightsAdmin |
| GET | /licensing/titles/{title_id}/restrictions | List restrictions for a title | RightsAdmin, LicensingOfficer, Applicant, MaterialsClerk, FinanceOfficer |
| GET | /licensing/restrictions/{restriction_id} | Read a TerritoryRestriction | RightsAdmin, LicensingOfficer |
| GET | /licensing/restrictions | List TerritoryRestrictions (filtered list form) | RightsAdmin, LicensingOfficer, Applicant |
| POST | /licensing/restrictions/{restriction_id}/lift | Lift (deactivate) a TerritoryRestriction | RightsAdmin |
| POST | /licensing/organizations | Register an Organization | RightsAdmin |
| GET | /licensing/organizations/{organization_id} | Read an Organization | RightsAdmin, LicensingOfficer, Applicant, FinanceOfficer |
| GET | /licensing/organizations | List organizations | RightsAdmin, LicensingOfficer, FinanceOfficer |
| POST | /licensing/applications | Create a LicenseApplication (DRAFT) | Applicant |
| GET | /licensing/applications/{application_id} | Read a LicenseApplication | RightsAdmin, LicensingOfficer, Applicant |
| GET | /licensing/applications | List applications (filterable) | RightsAdmin, LicensingOfficer, Applicant |
| PATCH | /licensing/applications/{application_id} | Edit a DRAFT or RETURNED_FOR_INFO application | Applicant |
| POST | /licensing/applications/{application_id}/submit | Submit (or resubmit from RETURNED_FOR_INFO) | Applicant |
| POST | /licensing/applications/{application_id}/begin_review | Move application to UNDER_REVIEW | LicensingOfficer |
| POST | /licensing/applications/{application_id}/return_for_info | Return application to applicant for more info | LicensingOfficer |
| POST | /licensing/applications/{application_id}/approve | Approve application; creates LicenseAgreement (OCC-guarded) | LicensingOfficer |
| POST | /licensing/applications/{application_id}/reject | Reject an application | LicensingOfficer |
| GET | /licensing/agreements/{agreement_id} | Read a LicenseAgreement | RightsAdmin, LicensingOfficer, Applicant, FinanceOfficer, MaterialsClerk |
| GET | /licensing/agreements | List agreements | RightsAdmin, LicensingOfficer, Applicant, FinanceOfficer |
| POST | /licensing/agreements/{agreement_id}/activate | Activate agreement (PENDING_PAYMENT → ACTIVE) | RightsAdmin |
| POST | /licensing/agreements/{agreement_id}/payments | Record a RoyaltyPayment against the agreement | FinanceOfficer |
| GET | /licensing/agreements/{agreement_id}/payments | List payments for an agreement | RightsAdmin, FinanceOfficer, Applicant |
| GET | /licensing/payments | List royalty payments (filtered list form) | RightsAdmin, FinanceOfficer |
| GET | /licensing/payments/{payment_id} | Read a RoyaltyPayment | RightsAdmin, FinanceOfficer, Applicant |
| POST | /licensing/agreements/{agreement_id}/performances | Declare a Performance under an ACTIVE agreement | Applicant |
| GET | /licensing/agreements/{agreement_id}/performances | List performances for an agreement | RightsAdmin, LicensingOfficer, Applicant, FinanceOfficer |
| POST | /licensing/agreements/{agreement_id}/amendments | Apply an amendment; OCC-guarded | RightsAdmin |
| POST | /licensing/agreements/{agreement_id}/cancel | Cancel an ACTIVE agreement; cascades | RightsAdmin |
| POST | /licensing/agreements/{agreement_id}/declare_breach | Declare a breach | RightsAdmin |
| GET | /licensing/performances/{performance_id} | Read a Performance | RightsAdmin, LicensingOfficer, Applicant, FinanceOfficer |
| GET | /licensing/performances | List performances (filtered list form) | RightsAdmin, LicensingOfficer, Applicant, FinanceOfficer |
| POST | /licensing/performances/{performance_id}/report | File a post-performance gross report | Applicant |
| POST | /licensing/performances/{performance_id}/cancel | Cancel a SCHEDULED performance | Applicant |
| POST | /licensing/rentals | Create a MaterialRental under an ACTIVE agreement | MaterialsClerk |
| GET | /licensing/rentals/{rental_id} | Read a MaterialRental | RightsAdmin, MaterialsClerk, Applicant, FinanceOfficer |
| GET | /licensing/rentals | List rentals | RightsAdmin, MaterialsClerk, FinanceOfficer |
| POST | /licensing/rentals/{rental_id}/ship | Ship rental to applicant | MaterialsClerk |
| POST | /licensing/rentals/{rental_id}/mark_received | Applicant confirms receipt of materials | Applicant |
| POST | /licensing/rentals/{rental_id}/ship_return | Applicant ships materials back | Applicant |
| POST | /licensing/rentals/{rental_id}/receive_return | Clerk receives returned materials; settles deposit and late fee | MaterialsClerk |
| POST | /licensing/rentals/{rental_id}/declare_lost | Declare rental materials lost | MaterialsClerk |
| POST | /licensing/alteration-requests | Submit an AlterationRequest | Applicant |
| GET | /licensing/alteration-requests/{request_id} | Read an AlterationRequest | RightsAdmin, LicensingOfficer, Applicant |
| GET | /licensing/alteration-requests | List alteration requests | RightsAdmin, LicensingOfficer, Applicant |
| POST | /licensing/alteration-requests/{request_id}/approve | Approve an AlterationRequest | RightsAdmin |
| POST | /licensing/alteration-requests/{request_id}/deny | Deny an AlterationRequest | RightsAdmin |
| POST | /licensing/recording-grants | Request a RecordingGrant add-on | Applicant |
| GET | /licensing/recording-grants/{grant_id} | Read a RecordingGrant | RightsAdmin, LicensingOfficer, Applicant, FinanceOfficer |
| GET | /licensing/recording-grants | List recording grants | RightsAdmin, LicensingOfficer, Applicant, FinanceOfficer |
| POST | /licensing/recording-grants/{grant_id}/approve | Approve a RecordingGrant | RightsAdmin |
| POST | /licensing/recording-grants/{grant_id}/deny | Deny a RecordingGrant | RightsAdmin |
| POST | /licensing/recording-grants/{grant_id}/mark_exercised | Mark a RecordingGrant as exercised | Applicant |
| GET | /licensing/fines/{fine_id} | Read a Fine | RightsAdmin, FinanceOfficer, Applicant |
| GET | /licensing/fines | List fines | RightsAdmin, FinanceOfficer, Applicant |
| POST | /licensing/fines/{fine_id}/pay | Pay a fine | FinanceOfficer |
| POST | /licensing/fines/{fine_id}/waive | Waive an OVERDUE_MATERIAL or LOSS fine | FinanceOfficer |
| POST | /licensing/fines/{fine_id}/write_off | Write off a fine aged ≥180 days | FinanceOfficer |
| GET | /licensing/applications/{application_id}/availability | Read latest AvailabilitySnapshot for an application | RightsAdmin, LicensingOfficer, Applicant |
| GET | /licensing/availability-snapshots | List AvailabilitySnapshots (filtered list form) | RightsAdmin, LicensingOfficer |
| GET | /licensing/availability-snapshots/{snapshot_id} | Read a single AvailabilitySnapshot | RightsAdmin, LicensingOfficer, Applicant |
| POST | /licensing/_clock/set_current_utc | Advance the server's logical clock | RightsAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_FORBIDDEN_OWNER_MISMATCH | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCED_NOT_FOUND | 422 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_TEMPORAL | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_ORG_SUSPENDED | 409 |
| ERR_TITLE_WITHDRAWN | 409 |
| ERR_TITLE_UNAVAILABLE | 409 |
| ERR_TERRITORY_RESTRICTED | 409 |
| ERR_EXCLUSIVE_RUN_CONFLICT | 409 |
| ERR_ALTERATION_PROHIBITED | 409 |
| ERR_RECORDING_PROHIBITED | 409 |
| ERR_STREAMING_CLASSIFICATION_BLOCK | 409 |
| ERR_RENTAL_KIND_MISMATCH | 422 |
| ERR_PERFORMANCE_OUTSIDE_WINDOW | 409 |
| ERR_PERFORMANCE_ALREADY_HELD | 409 |
| ERR_REPORT_TOO_EARLY | 409 |
| ERR_PAYMENT_AMOUNT_INVALID | 422 |
| ERR_FINE_NOT_WAIVABLE | 409 |
| ERR_WRITE_OFF_TOO_EARLY | 409 |
| ERR_RENTAL_NOT_DUE_LOST | 409 |
| ERR_DEPOSIT_NOT_HELD | 409 |
| ERR_AMENDMENT_ON_TERMINAL | 409 |
