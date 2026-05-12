# Lab Equipment Sharing API — Product Requirements Document

## 1. Introduction

Research institutions accumulate expensive analytical instruments whose duty cycle rarely matches the demand of any single laboratory; a centrifuge or sequencing platform purchased by one lab routinely sits idle while another lab a corridor away postpones experiments for lack of access. The Lab Equipment Sharing API formalises a marketplace for this latent capacity. The platform mediates between equipment-owning laboratories, end users from a variety of institutional affiliations, and the platform operator that runs settlements and event integrations. It owns the entire round-trip lifecycle of every shared session: registering an instrument, qualifying a user against training and sample-type requirements, scheduling a slot against published availability and maintenance plans, executing the session with check-in and check-out logs, computing both a forward-looking estimate and a chronologically derived final bill, and finally accruing owner revenue for periodic settlement.

Because the workflow weaves together temporal windowing (slot grids, peak windows, maintenance windows, lead times), multi-party negotiation (owner approval, platform approval, cascading cancellation), and financial accuracy (basis-point splits, version-pinned billing rules, refund tiers, settlement ledger), the API must behave deterministically under concurrency. The contract below specifies entities, state transitions, validation priorities, cost calculations, and error codes in sufficient detail that two independent implementations produce byte-identical answers to the same request sequence.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and contracts that apply to the entire API surface. The API is mounted under `/equipment` and adjacent top-level paths (`/labs`, `/users`, `/reservations`, `/maintenance-windows`, `/authorizations`, `/audit-events`, and the underscored `_clock` and `_events` test surfaces).

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID` identifies the acting principal, and `X-User-Role` declares the operational capacity in which the request is made. When either header is missing or unparseable the request is rejected with `ERR_MISSING_AUTH` and a `401` status; when both are present but the declared role is not permitted to perform the requested operation under the role matrix below, the request is rejected with `ERR_FORBIDDEN` at `403`.

The system recognises exactly three roles:

- `PlatformAdmin` — the platform operator. `X-User-ID` for this role is an opaque operator identifier that is not tied to any persisted entity in the system; the server may record it (for example, in `AuditEvent.actor_user_id` or `Authorization.platform_decision_user_id` where a transition writes it) but does not compare it to any entity's `id` for ownership.
- `LabOwner` — a laboratory administrator. When `X-User-Role` is `LabOwner`, `X-User-ID` is the `id` of the acting `User`; ownership checks on any `Lab` compare the lab's `contact_user_id` to `X-User-ID`, and ownership checks on any `Equipment`, `BillingRule`, `MaintenanceWindow`, `Authorization`, or `Reservation` resolve to the lab through `Equipment.lab_id` and compare the resulting lab's `contact_user_id` to `X-User-ID`.
- `User` — an end user requesting authorizations and reservations. When `X-User-Role` is `User`, `X-User-ID` is the `id` of the acting `User`; ownership checks on `Authorization` and `Reservation` compare the resource's `user_id` foreign key to `X-User-ID`.

For action endpoints that mutate a `Reservation` (cancel, check-in, check-out), the actor must either be the `User` whose `id` matches `Reservation.user_id`, or a `LabOwner` of the equipment's owning lab — any other caller is rejected with `ERR_FORBIDDEN`. Cross-role identity coincidence (a `LabOwner` who is also the requesting `User` on a reservation) is permitted only when invoked under one of those two roles.

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

List endpoints accept two query parameters. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; values outside that range yield `ERR_BAD_REQUEST`. The `offset` parameter defaults to 0 and has no upper bound beyond available rows. Unless explicitly overridden, list endpoints return resources sorted by `created_at` ascending — ties on `created_at` are broken by `id` ascending so that pagination is deterministic.

Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` envelope. The `has_more` flag is `true` if and only if `offset + limit < total_count`.

### 2.4. Common Resource Properties and Optimistic Concurrency

Every resource carries a server-minted `id` rendered as a UUID with no type prefix. Most entities — `Lab`, `User`, `Equipment`, `MaintenanceWindow`, `Authorization`, and `Reservation` — additionally carry three system-managed fields: `created_at` (ISO 8601 UTC with three fractional digits, set once at insert), `updated_at` (same format, refreshed on every state change or field mutation), and `version` (a monotonic integer, set to 1 at insert and incremented by exactly 1 on every mutation, including system-driven cascades). Two entity types are deliberately leaner: `BillingRule` and `UsageLog` carry only `id` and `created_at` — no `updated_at`, no `version` — because they are append-only artefacts whose evolution is expressed by status transitions on neighbouring rows (`BillingRule.status` flipping `DRAFT` → `PUBLISHED` → `SUPERSEDED`, or `UsageLog` being amended by `check_out_at`). The `AuditEvent` entity is similarly append-only and carries only `id` and `created_at`.

Mutating endpoints accept an optional `version` field in the request body. When supplied, the value must equal the current `version` of the targeted row at the moment of the write; a mismatch yields `ERR_VERSION_CONFLICT` at `409`. When the field is omitted entirely the optimistic check is skipped and the write proceeds against whatever the current row is. Every successful mutation — whether triggered by a client or by a system cascade described later in this document — increments the affected row's `version` by 1 and refreshes its `updated_at` to the server clock at write time.

### 2.5. Nested Resource Retrieval

Several endpoint paths are nested, for example `/equipment/{equipment_id}/billing-rules/{rule_id}/publish` or `/equipment/{equipment_id}/maintenance-windows`. Path segments are resolved strictly left to right: the system first verifies that `equipment_id` resolves to a row of type `Equipment`, then that `rule_id` resolves to a row of type `BillingRule` whose `equipment_id` equals the path's `equipment_id`. The first segment that fails to resolve yields `ERR_NOT_FOUND` (`404`) without further checks. Body-referenced foreign keys — `authorization_id` on a reservation create, `lab_id` on equipment create — are resolved after path resolution; an unknown body foreign key likewise yields `ERR_NOT_FOUND`. State-based rejections (`ERR_INVALID_STATE`, `ERR_EQUIPMENT_UNAVAILABLE`) and business validations only run once existence is established.

### 2.6. Monetary Precision and Rounding

All monetary fields in the system are stored as integer cents — `internal_rate_per_hour_cents`, `external_rate_per_hour_cents`, `inter_school_rate_per_hour_cents`, `internal_rate_per_sample_cents`, `external_rate_per_sample_cents`, `inter_school_rate_per_sample_cents`, `consumables_flat_cents`, `estimated_fee_cents`, `final_fee_cents`, `estimated_owner_share_cents`, `final_owner_share_cents`, `estimated_platform_fee_cents`, `final_platform_fee_cents`, `settlement_balance_cents`, and `lifetime_settled_cents`. Whenever a multi-step calculation yields a rational intermediate, the system rounds the result to a whole number of cents using the "round half up" method (a half-cent always rounds away from zero, toward positive infinity for positive amounts).

Basis points are integers in the inclusive range 0 through 10000, where 10000 represents 100 percent. Multiplying a cents quantity by a basis-points figure divides by 10000 in the rational domain before any rounding occurs; the same rule applies to revenue-share, platform-fee, refund-bps, and peak-multiplier multiplications.

### 2.7. Slot Grid, Lead Time, and Peak Windows

Every reservation must align to the owning equipment's `slot_granularity` grid. When `slot_granularity` is `HOUR`, both `start_at` and `end_at` must fall on the top of a UTC hour. When the value is `HALF_DAY`, both timestamps must fall on either 00:00 or 12:00 UTC of a calendar day. When the value is `DAY`, both timestamps must fall on 00:00 UTC of a calendar day. In addition, `end_at` must be strictly greater than `start_at`, and the duration `end_at` minus `start_at` must be a positive integer multiple of the granularity. Any deviation surfaces as `ERR_SLOT_GRID_VIOLATION` at `422`.

A reservation's `start_at` must lie at least `lead_time_hours` hours in the future relative to the server clock at create time; if the gap is shorter the request is rejected with `ERR_LEAD_TIME_VIOLATED`. The reservation duration, measured in full hours as `end_at` minus `start_at`, must not exceed the equipment's `single_user_duration_limit_hours`; otherwise the request is rejected with `ERR_DURATION_LIMIT_EXCEEDED`.

Each piece of equipment defines a daily peak window via `peak_window_start_hour` (the inclusive opening hour, 0 through 23) and `peak_window_end_hour` (the exclusive closing hour, 1 through 24); the window is interpreted in UTC and is half-open with respect to both ends. A reservation's `priority_tier` is computed at create time and equals `PEAK` when the reservation's half-open interval intersects the equipment's daily peak window for strictly more than zero minutes (summed across every calendar day the reservation spans); otherwise it equals `OFF_PEAK`.

### 2.8. Hierarchical Consistency, Cascades, and Audit

The system maintains strict consistency across parent-child relationships and cascading effects. Whenever a system or user action mutates one row in a way that demands compensating writes elsewhere — for example, an `Equipment` transitioning to `MAINTENANCE` that must cancel overlapping `BOOKED` reservations, or a `BillingRule` publish that must supersede the previous rule and refresh the equipment's `active_billing_rule_id` — every cascaded row likewise has its `updated_at` refreshed and its `version` incremented (where the entity carries those fields). Cascades that affect a `Reservation`'s estimated owner share or a `Lab.settlement_balance_cents` likewise update those rows in the same logical transaction.

Every state-changing operation that touches a `Reservation` or an `Authorization` writes an `AuditEvent` row containing the `subject_type` (`RESERVATION` or `AUTHORIZATION`), the `subject_id`, the `actor_role` and `actor_user_id` derived from the request headers, an `action` verb chosen from `CREATE`, `APPROVE`, `REJECT`, `CANCEL`, `REVOKE`, `CHECK_IN`, `CHECK_OUT`, `EXPIRE`, and `RESCHEDULE`, the `from_state` (null on create), the `to_state`, and a compact `payload_json` describing the mutated fields. Cascaded cancellations write their own audit rows individually, one per affected reservation.

### 2.9. Validation Ordering

When multiple validation rules might apply to the same request, the system evaluates them in a fixed priority sequence so that the returned error is predictable. The order is: header presence, role permission, path-segment existence (left-to-right), body-referenced foreign-key existence, generic state-machine admissibility, the more specific equipment-availability check, cross-entity authorization validity, certificate freshness, qualification gate, sharing-scope compatibility, lead time, slot-grid alignment, duration limit, maintenance-window conflict, reservation overlap, peak-priority direction, actor-identity ownership, and finally the fiscal validations on billing-rule publish and settlement. When two checks could both reject the same request, the earlier one in this list wins and its specific error code is returned. Idempotency conflicts on event ingest are evaluated separately and only after the above ordering has admitted the request.

### 2.10. Concurrency Guarantees

For each contested resource the system maintains a deterministic serialization point so that races have a single winner. Two `User` clients posting reservations on the same equipment with half-open intervals that intersect serialize on the existing-reservations overlap check; the second writer is rejected with `ERR_RESERVATION_OVERLAP` at `409`. A reservation check-in that races against a system-driven `SCHEDULED` → `IN_PROGRESS` transition on an overlapping maintenance window serializes on `Equipment.status`; the loser receives `ERR_EQUIPMENT_UNAVAILABLE` at `409`. A billing-rule publish that races a reservation confirm pinning the prior rule serializes on `Equipment.active_billing_rule_id`; the losing reservation receives `ERR_BILLING_RULE_RACED` at `409`. Two `LabOwner` approvals on the same `PENDING_OWNER` authorization, and the analogous race between a `PlatformAdmin` approve and a `LabOwner` revoke on the same authorization, both serialize on `Authorization.status`; whichever transaction commits second receives `ERR_AUTHORIZATION_ALREADY_DECIDED` at `409`. A user-initiated cancellation that races the system's `NO_SHOW` sweep at `end_at` serializes on `Reservation.status`; the loser receives `ERR_INVALID_STATE` at `409`.

### 2.11. Event Ingest Idempotency

External system bridges — payment confirmation and identity verification — are exposed through underscore-prefixed event endpoints that must be idempotent. A repeated call with the same `external_user_id` for identity verification, or the same `external_payment_id` for a payment confirmation on the same `reservation_id`, must produce a success response equivalent to the original; a repeated call whose payload contradicts the previously recorded outcome is rejected with `ERR_IDEMPOTENCY_CONFLICT` at `409`. Malformed bodies — missing required fields, unparseable timestamps, integers outside the documented ranges — uniformly surface as `ERR_BAD_REQUEST` at `400`.

## 3. Business Logic & Workflows

### 3.1. Onboarding Labs, Users, and Equipment

A platform's first action is to create the labs that will own equipment. A `PlatformAdmin` registers a `Lab` by supplying a display `name`, an `institution` code identifying the parent school or institute, a `department` code (later used by the inter-department cost-transfer ledger), the `contact_user_id` of the `User` who will administer the lab, and a `revenue_share_bps` figure between 0 and 10000 inclusive that represents the owner-lab's share of the equipment-fee subtotal in basis points. At creation the lab's `settlement_balance_cents` and `lifetime_settled_cents` are both initialised to 0.

End users are likewise provisioned by a `PlatformAdmin`. The create payload carries an `external_user_id` (an opaque identifier minted by the upstream identity-verification system, used as the idempotency key on user provisioning), a `full_name`, the user's `department` code, an `affiliation` chosen from `WITHIN_SCHOOL`, `INTER_SCHOOL`, or `EXTERNAL`, and a `training_certificates` array enumerating the certificate codes the user has earned. A freshly provisioned user is unverified — `identity_verified` is `false` until the identity-verification system asynchronously emits a `VERIFIED` event ingested by the platform-admin-only identity-verified event hook. The ingest is idempotent on `external_user_id`: a second `VERIFIED` event for the same user is a no-op success; a contradictory payload yields `ERR_IDEMPOTENCY_CONFLICT`.

A `LabOwner` registers an `Equipment` resource under their owned lab. The payload supplies `lab_id`, the instrument's `model` and free-form `specification`, a `value_tier` (`STANDARD` or `HIGH_VALUE`), a `sharing_scope` (`WITHIN_SCHOOL`, `INTER_SCHOOL`, or `EXTERNAL`), the `slot_granularity` (`HOUR`, `HALF_DAY`, or `DAY`), a `lead_time_hours` integer no less than 0, a `single_user_duration_limit_hours` cap, the peak window bounds `peak_window_start_hour` and `peak_window_end_hour`, the two certificate identifiers and expiry timestamps `calibration_cert_id` with `calibration_expires_at` and `safety_inspection_cert_id` with `safety_inspection_expires_at`, asset pointers `photo_uri` and `operation_manual_uri`, and two qualification descriptors: `required_training_codes` listing every certificate code a user must hold to be authorized, and `allowed_sample_types` enumerating every sample-type code the instrument accepts. Equipment is registered with `status` `AVAILABLE` and `active_billing_rule_id` `null`; the latter is filled in when the first billing rule is published.

The owner can update equipment configuration — `single_user_duration_limit_hours`, `peak_window_start_hour`, `peak_window_end_hour`, or `status` — through a profile-edit operation that accepts a `version` field for optimistic concurrency. Setting `status` to `RETIRED` is a terminal step: the equipment must have no `BOOKED` or `CHECKED_IN` reservations remaining, and any future-dated `MaintenanceWindow` rows still in `SCHEDULED` are cascaded to `REJECTED` because they can no longer be accepted. Certificates are a hard prerequisite for any state that flips equipment back to `AVAILABLE`: if `calibration_expires_at` or `safety_inspection_expires_at` is not strictly greater than the server clock at the moment of the transition, the request is rejected with `ERR_CERTIFICATE_EXPIRED`.

### 3.2. Authorization Approval Workflow

Before a `User` may book any equipment they must obtain an `Authorization` for it. The end user opens the request directly against the target instrument by supplying their own `user_id` (which must equal `X-User-ID`), the `sample_type` they intend to run, and an `urgency` of either `NORMAL` or `URGENT`. The system immediately runs the eligibility gate.

The eligibility gate is a weighted-score function with four binary inputs. The `training_match` input is 1 when every code in the equipment's `required_training_codes` array is present in the user's `training_certificates` array, and 0 otherwise (an empty required set yields 1). The `sample_match` input is 1 when the requested `sample_type` is a member of `allowed_sample_types`, and 0 otherwise. The `affiliation_match` input depends on the equipment's `sharing_scope`: when the scope is `WITHIN_SCHOOL`, the input is 1 only if the user's `affiliation` equals `WITHIN_SCHOOL`; when the scope is `INTER_SCHOOL`, the input is 1 when the user's `affiliation` is either `WITHIN_SCHOOL` or `INTER_SCHOOL`; when the scope is `EXTERNAL`, the input is 1 unconditionally. The `identity_match` input is 1 when `User.identity_verified` is `true`, and 0 otherwise. The total score is the sum of the `training_match` weighted by 30, the `sample_match` weighted by 30, the `affiliation_match` weighted by 20, and the `identity_match` weighted by 20, giving a maximum of 100. The authorization passes the gate only when the total score is at least 100 — meaning every component must be 1; any zero input causes immediate rejection. When the failure is specifically a sharing-scope mismatch (training, sample, and identity all 1 but affiliation 0), the system returns `ERR_SHARING_SCOPE_VIOLATION`; in every other failing combination the system returns `ERR_QUALIFICATION_NOT_MET`. The same eligibility computation is re-run at owner approval and at platform approval to catch any user state that drifted between create and approve.

When the gate passes at create time, the authorization is recorded with status `PENDING_OWNER`. The branching downstream then depends on the equipment's `value_tier` and the request's `urgency`.

For a `STANDARD` instrument, the owner step alone is decisive: the `LabOwner` of `Equipment.lab_id` invokes approval, the system writes `owner_decision_user_id`, sets `approved_at` to the server clock, computes `expires_at` as `approved_at` plus a fixed authorization time-to-live (the `AUTHORIZATION_TTL_DAYS` constant; days are measured as exact 24-hour spans), and transitions the authorization to `APPROVED`. An `APPROVE` audit row is written.

For a `HIGH_VALUE` instrument the workflow forks. When `urgency` is `URGENT` the same single owner approval transitions the authorization directly to `APPROVED` and behaves identically to the `STANDARD` flow — this is the expedited path for time-critical requests. When `urgency` is `NORMAL` the owner approval first transitions the authorization to `PENDING_PLATFORM` with `owner_decision_user_id` recorded; a subsequent platform approval by any `PlatformAdmin` then writes `platform_decision_user_id`, sets `approved_at` and `expires_at`, and transitions to `APPROVED`. Both approvers run the eligibility gate.

A rejection at either pending stage uses the same reject action; the request optionally carries a `rejection_reason` string. The authorization moves to `REJECTED` with the captured `from_state` (`PENDING_OWNER` or `PENDING_PLATFORM`) and a `REJECT` audit row is written. Both a `LabOwner` (for `PENDING_OWNER`) and a `PlatformAdmin` (for `PENDING_PLATFORM`) may invoke reject on their respective stage. An approval attempted on an authorization that has already left its initial pending state — including a second `LabOwner` racing into `PENDING_OWNER`, or a `PlatformAdmin` approve arriving after a `LabOwner` revoke — is rejected with `ERR_AUTHORIZATION_ALREADY_DECIDED`.

Once `APPROVED`, an authorization remains valid until either it is explicitly revoked or its `expires_at` is reached. Revocation may be requested by the equipment's `LabOwner` or by a `PlatformAdmin`; the authorization moves to `REVOKED`, every future-dated `BOOKED` reservation bound to it is cascaded to `CANCELLED` with `cancellation_refund_bps` of 10000 (full refund), the cancelled reservations release their accrued owner share back from `Lab.settlement_balance_cents` by debiting the sum of their `estimated_owner_share_cents` values, refund events are emitted to the payment system for each, and a `REVOKE` audit row is written for the authorization with `CANCEL` rows for each cascaded reservation. Expiry follows the same cascade pattern: when the logical clock advances to or beyond `expires_at`, the authorization automatically moves to `EXPIRED`, every future-dated `BOOKED` reservation is cancelled with full refund, and an `EXPIRE` audit row is written.

### 3.3. Booking, Slots, and Peak Priority

Holding an `APPROVED` authorization, the same `User` may open a reservation on the equipment. The request supplies `user_id` (matching `X-User-ID`), the `authorization_id` of the approved authorization, the window `start_at` and `end_at`, and a `requested_sample_count` that records the user's declared sample volume for billing estimates. The system runs validation in the priority order described in §2.9: it verifies headers and role, resolves the path's `equipment_id`, then resolves the body's `authorization_id`, then walks the business checks.

The cross-entity authorization check enforces that the supplied `authorization_id` resolves to a row whose `status` is `APPROVED`, whose `expires_at` is strictly greater than the server clock, and whose `equipment_id` and `user_id` both match the reservation's context — any deviation yields `ERR_AUTHORIZATION_INVALID`. Equipment must be in `status` `AVAILABLE`; if it is in `MAINTENANCE` or `RETIRED` the system returns `ERR_EQUIPMENT_UNAVAILABLE`. Both certificate expiry timestamps must be strictly in the future, otherwise `ERR_CERTIFICATE_EXPIRED`. The slot must align to the granularity grid per §2.7 (`ERR_SLOT_GRID_VIOLATION`), the lead time must be honoured (`ERR_LEAD_TIME_VIOLATED`), and the duration must not exceed the per-user cap (`ERR_DURATION_LIMIT_EXCEEDED`).

The system then checks the slot against the equipment's existing temporal commitments. The requested half-open interval `[start_at, end_at)` must not intersect any `MaintenanceWindow` whose status is `SCHEDULED` or `IN_PROGRESS` for this equipment; if it does, the request is rejected with `ERR_MAINTENANCE_BLOCK`. It must not overlap any existing `BOOKED` or `CHECKED_IN` reservation on the same equipment — intersection uses half-open semantics, so a new reservation whose `start_at` exactly equals an existing reservation's `end_at` is permitted — and an overlap yields `ERR_RESERVATION_OVERLAP`.

Peak-priority handling is a special form of the overlap check. The system first computes `priority_tier` for the candidate reservation as `PEAK` when its window intersects the equipment's daily peak window for more than zero minutes (per §2.7), and `OFF_PEAK` otherwise. When the candidate is `PEAK` and the only conflicting reservation is an `OFF_PEAK` reservation in `BOOKED` status that overlaps the requested slot, the conflicting reservation is preempted: it is cancelled with `cancellation_refund_bps` of 10000 (full refund) and a `CANCEL` audit row is written for it, and the new `PEAK` reservation is then admitted. When the candidate is `OFF_PEAK` and a `PEAK` reservation overlaps the slot, preemption in this direction is forbidden and the request is rejected with `ERR_PEAK_PRIORITY_VIOLATION`. Preemption never occurs against `CHECKED_IN` reservations regardless of tier — those are protected by ordinary overlap and produce `ERR_RESERVATION_OVERLAP`.

When all checks pass, the reservation is admitted in status `BOOKED`. The system pins `billing_rule_id_pinned` to the equipment's current `active_billing_rule_id` at this moment; this snapshot is immutable for the life of the reservation. It computes `estimated_fee_cents`, `estimated_owner_share_cents`, and `estimated_platform_fee_cents` via the forward-looking calculation described in §3.5, and adds `estimated_owner_share_cents` to the owning lab's `settlement_balance_cents`.

A booked reservation can be cancelled by its owning `User` or by a `LabOwner` of the equipment's lab so long as the server clock is strictly before `start_at`; an attempt after `start_at` is rejected with `ERR_INVALID_STATE`. Cancellation sets `cancelled_at` to the server clock, computes `cancellation_refund_bps` per §3.4, debits the lab's `settlement_balance_cents` by `estimated_owner_share_cents` multiplied by the refund basis points and divided by 10000 (rounded half-up to integer cents), and emits a refund event to the payment system. A `CANCEL` audit row is written.

### 3.4. Cancellation Refund Tiers

The refund attached to a voluntary cancellation depends on how far in advance it is requested. Let the delta in minutes between `start_at` and the server clock at the cancellation moment be the lead amount. When that lead is at least 24 hours (the full-refund minimum), `cancellation_refund_bps` is set to 10000 — a complete refund of the estimated fee. When the lead is less than 24 hours but at least 2 hours (the partial-refund minimum), `cancellation_refund_bps` is set to 5000 — a half refund. When the lead is less than 2 hours, `cancellation_refund_bps` is set to 0 — the reservation still cancels but no refund is owed. The refund amount itself, in cents, is computed as `estimated_fee_cents` multiplied by `cancellation_refund_bps` and divided by 10000, rounded half-up to a whole number of cents. The lab's `settlement_balance_cents` is debited by `estimated_owner_share_cents` multiplied by `cancellation_refund_bps` and divided by 10000, rounded half-up to a whole number of cents.

System-driven cancellations — those triggered by an authorization revoke, an authorization expiry, a maintenance window opening, or a peak preemption — always use full refund (`cancellation_refund_bps` of 10000), independent of how close to `start_at` they occur.

### 3.5. Billing Rules and Fee Calculation

Each `Equipment` may have many `BillingRule` rows but only one in `PUBLISHED` status at any moment. A `LabOwner` drafts a rule by supplying its `mode` (`BY_TIME`, `BY_SAMPLE`, or `HYBRID`), three time-based rates `internal_rate_per_hour_cents`, `external_rate_per_hour_cents`, and `inter_school_rate_per_hour_cents` covering the three affiliation tiers, three sample-based rates `internal_rate_per_sample_cents`, `external_rate_per_sample_cents`, and `inter_school_rate_per_sample_cents`, the `peak_multiplier_bps` applied to the time portion when peak overlap is non-zero (a value of 12500 means 1.25x), a `consumables_flat_cents` per-checkout flat fee that is accounted separately from the equipment fee, and a `platform_fee_bps` representing the platform service fee in basis points charged on the equipment-fee subtotal. The draft is created with `status` `DRAFT` and no assigned `rule_version`.

Publishing transitions the rule to `PUBLISHED` and is restricted to the `LabOwner`. At publish, the system checks that every rate field is present and at least 0, and that the sum of `platform_fee_bps` and the owning lab's `revenue_share_bps` does not exceed 10000 — if it does, the publish is rejected with `ERR_FEE_SPLIT_INVALID`. On successful publish, the previously `PUBLISHED` rule for the same equipment (if any) is moved to `SUPERSEDED`, the new rule's `rule_version` is assigned as one greater than the maximum existing `rule_version` for the equipment (starting at 1 if none exist), the equipment's `active_billing_rule_id` is updated to the new rule's `id`, and `published_at` is set to the server clock. Reservations that have already been confirmed retain their pinned rule_version — only future reservations pin the newly published rule.

The forward-looking estimate is computed at reservation create. The system loads the rule referenced by the equipment's current `active_billing_rule_id` (the same rule that will be pinned on the new reservation). It picks the time and sample rates according to the user's `affiliation`: `WITHIN_SCHOOL` users get `internal_rate_per_hour_cents` and `internal_rate_per_sample_cents`; `INTER_SCHOOL` users get `inter_school_rate_per_hour_cents` and `inter_school_rate_per_sample_cents`; `EXTERNAL` users get `external_rate_per_hour_cents` and `external_rate_per_sample_cents`. The billed hours figure for the estimate is the exact rational duration of the reservation window in hours — `end_at` minus `start_at`, expressed as total minutes divided by 60 without rounding.

The raw time component depends on `mode`. When the mode is `BY_TIME` it equals the billed hours multiplied by the affiliation-tier time rate. When the mode is `BY_SAMPLE` it is 0. When the mode is `HYBRID` it equals the billed hours multiplied by the affiliation-tier time rate (the hybrid mode is additive: it includes the time component and the sample component in full). The raw sample component is 0 when the mode is `BY_TIME`, and equals `requested_sample_count` multiplied by the affiliation-tier sample rate when the mode is `BY_SAMPLE` or `HYBRID`.

When the reservation's window overlaps the equipment's daily peak window for strictly more than zero minutes (calculated per §2.7), the raw time component is multiplied by `peak_multiplier_bps` divided by 10000 — this multiplier is applied to the time portion only, never to the sample portion, and applied to the raw rational value before any rounding. The equipment-fee subtotal in cents is then the sum of the (possibly peak-multiplied) raw time component and the raw sample component, rounded half-up to a whole number of cents. The platform fee is computed by multiplying that equipment-fee subtotal in cents by `platform_fee_bps`, dividing by 10000, and rounding half-up independently. The consumables figure is the rule's `consumables_flat_cents` as-is. The total `estimated_fee_cents` is the sum of the equipment fee, the platform fee, and the consumables fee.

The owner share is derived from the same equipment-fee subtotal by an independent rounding pass: `estimated_owner_share_cents` equals the equipment-fee subtotal multiplied by the lab's `revenue_share_bps`, divided by 10000, rounded half-up to a whole number of cents. The `estimated_platform_fee_cents` equals the rounded platform fee already computed.

The chronologically-derived `final_fee_cents` is computed at checkout from the `UsageLog`, using the rule whose `id` equals `billing_rule_id_pinned` — not the rule currently active on the equipment. The actual elapsed minutes are the ceiling, in minutes, of `check_out_at` minus `check_in_at` (any partial minute is rounded up). The actual billed hours figure is the ceiling, in whole hours, of the actual elapsed minutes divided by 60 (any partial hour rounds up). The same affiliation-tier rate selection applies. The raw time component for the final fee is the actual billed hours multiplied by the time rate when the mode is `BY_TIME` or `HYBRID`, and 0 when the mode is `BY_SAMPLE`. The raw sample component uses `actual_sample_count` from the usage log instead of `requested_sample_count`: it is 0 when the mode is `BY_TIME`, and `actual_sample_count` multiplied by the sample rate when the mode is `BY_SAMPLE` or `HYBRID`. The peak multiplier is applied to the raw time component when the actual session window — `check_in_at` to `check_out_at` — overlaps the equipment's daily peak window for more than zero minutes, using the same interval-merge interpretation per calendar day described in §2.7. The equipment-fee subtotal is then the sum of the (possibly peak-multiplied) raw time component and the raw sample component, rounded half-up to whole cents. The `final_fee_cents` adds the rounded platform fee (equipment-fee subtotal times `platform_fee_bps` divided by 10000, rounded half-up independently) and the rule's `consumables_flat_cents`. The `final_owner_share_cents` is independently derived from the equipment-fee subtotal times `revenue_share_bps` divided by 10000, rounded half-up. The `final_platform_fee_cents` equals the rounded platform fee.

Because the estimated and final calculations use different billed-hours conventions (rational duration versus ceil-to-whole-hour) and different sample counts (`requested_sample_count` versus `actual_sample_count`), the two figures will diverge whenever the actual session overruns or under-runs the booking window, or the user reports a different sample count at checkout. This is intentional — the estimate is a conservative forward-looking accrual that is reconciled against the chronological truth on session close.

### 3.6. Sessions and Usage Logs

A `User` opens a session by checking in on their own reservation no earlier than 15 minutes before `start_at` and strictly before `end_at`. Check-in further requires that the equipment is in `status` `AVAILABLE` at the moment of the call, and that the bound authorization is still `APPROVED` with `expires_at` strictly in the future — failures yield `ERR_INVALID_STATE`, `ERR_EQUIPMENT_UNAVAILABLE`, or `ERR_AUTHORIZATION_INVALID` respectively. A successful check-in transitions the reservation from `BOOKED` to `CHECKED_IN` and creates a `UsageLog` row whose `reservation_id` references the reservation and whose `check_in_at` is set to the server clock. The `actual_duration_minutes` field is initialised to 0; it remains 0 until check-out.

The same `User` ends the session by checking out. The check-out payload supplies `actual_sample_count` (the truth at session close, used in the final-fee calculation per §3.5), `status_handover` of either `NORMAL` or `ABNORMAL`, and an optional `abnormal_event_code` describing the incident; whenever an `abnormal_event_code` is supplied the system requires `status_handover` to be `ABNORMAL` and the two travel together. The system sets `check_out_at` to the server clock, computes `actual_duration_minutes` as the ceiling, in minutes, of `check_out_at` minus `check_in_at`, computes the final fee per §3.5, populates `final_fee_cents`, `final_owner_share_cents`, and `final_platform_fee_cents`, and adjusts the lab's `settlement_balance_cents` by the delta between `final_owner_share_cents` and the previously accrued `estimated_owner_share_cents` (which may be positive or negative). The reservation moves to `COMPLETED`.

When `status_handover` is `ABNORMAL`, the system additionally spawns a new `MaintenanceWindow` of `kind` `AD_HOC` with `start_at` equal to the server clock and `end_at` equal to the clock plus 24 hours, recording the user's incident text in `maintenance_notes` together with the `abnormal_event_code`. The window is created in `status` `IN_PROGRESS` and the equipment is transitioned `AVAILABLE` → `MAINTENANCE`. Because the reservation has already moved through `CHECKED_IN` → `COMPLETED`, the maintenance transition does not retroactively cancel the completed session, but any future `BOOKED` reservations that overlap the new window are cascaded to `CANCELLED` with full refund per §3.4. Audit rows record the `CHECK_OUT` action on the reservation and the maintenance cascade on each affected reservation.

A reservation that is never checked in is swept to `NO_SHOW` when the logical clock advances to or beyond `end_at`. The forfeit is total — `estimated_fee_cents` is treated as fully charged, `cancellation_refund_bps` remains 0, and the lab's `settlement_balance_cents` retains the previously accrued `estimated_owner_share_cents`. No refund event is emitted.

### 3.7. Maintenance Windows

A `LabOwner` schedules maintenance by opening a `MaintenanceWindow` on owned equipment with a `kind` of `PERIODIC` (planned downtime announced in advance) or `AD_HOC` (immediate or imminent intervention). The payload supplies `start_at`, `end_at`, and free-form `maintenance_notes`. When `kind` is `AD_HOC` and the window already encompasses the server clock — that is, `start_at` is less than or equal to the clock and the clock is strictly before `end_at` — the equipment transitions `AVAILABLE` → `MAINTENANCE` immediately, the window is recorded in `status` `IN_PROGRESS`, and every `BOOKED` reservation whose half-open interval intersects the window is cascaded to `CANCELLED` with `cancellation_refund_bps` of 10000 (full refund), each cancellation releasing its accrued `estimated_owner_share_cents` back from `Lab.settlement_balance_cents`, emitting a refund event to the payment system, and writing its own audit row. When `kind` is `PERIODIC` or when an `AD_HOC` window's `start_at` lies strictly in the future, the window is recorded in `status` `SCHEDULED` and no cascade fires yet.

The logical clock drives the lifecycle. When the clock advances to or beyond `start_at` on a `SCHEDULED` window, and the equipment is currently `AVAILABLE`, the window transitions to `IN_PROGRESS`, the equipment transitions `AVAILABLE` → `MAINTENANCE`, and overlapping `BOOKED` reservations are cascaded to `CANCELLED` with full refund. When the clock further advances to or beyond `end_at`, the window transitions to `AWAITING_ACCEPTANCE`; the equipment remains in `MAINTENANCE` until acceptance.

Either the equipment's `LabOwner` or a `PlatformAdmin` may close out the window. Acceptance moves the window to `ACCEPTED`, populates `archived_record_uri` with a pointer to the archived maintenance record, attaches the optional `acceptance_notes` text, and — when no other `IN_PROGRESS` or `AWAITING_ACCEPTANCE` window covers the equipment — transitions the equipment `MAINTENANCE` → `AVAILABLE`. Rejection moves the window to `REJECTED`, records the supplied `acceptance_notes` describing why acceptance was withheld, and spawns a follow-up `AD_HOC` `MaintenanceWindow` with `start_at` equal to the server clock and `end_at` equal to the server clock plus 24 hours; the equipment remains in `MAINTENANCE` because it is now covered by the new window. A `SCHEDULED` window on equipment that is retired is automatically transitioned to `REJECTED` because acceptance is no longer possible. A user-initiated `AD_HOC` window create can only be issued by the `LabOwner` of the equipment's lab; that ownership check is in addition to general role permission.

### 3.8. Settlement, Inter-Department Transfer, and External Events

The owning lab's `settlement_balance_cents` accumulates incrementally over the lifecycle of every reservation. At reservation create the balance is credited by `estimated_owner_share_cents`. At check-out it is adjusted by the signed delta `final_owner_share_cents` minus `estimated_owner_share_cents`. At a voluntary cancellation it is debited by `estimated_owner_share_cents` multiplied by `cancellation_refund_bps` divided by 10000, rounded half-up. At a system-driven cancellation (revoke, expiry, maintenance, peak preemption) the debit uses the full-refund basis points of 10000. A no-show leaves the accrued share intact. A periodic settlement initiated by a `PlatformAdmin` adds the current `settlement_balance_cents` to `lifetime_settled_cents` and zeros the balance — but only when the balance is strictly greater than 0; an attempt to settle a zero or negative balance is rejected with `ERR_NOTHING_TO_SETTLE` at `422`. A `SETTLE` audit-style row is recorded.

Payment confirmations arrive from the payment system through the platform-admin-only payment-confirmed event hook. The ingest is idempotent on the combination of `reservation_id` and `external_payment_id`: a repeated event with the same pair is a no-op; a repeated event with the same `reservation_id` but a contradictory `external_payment_id` (or vice versa) yields `ERR_IDEMPOTENCY_CONFLICT`. A successful ingest records a `PAYMENT_CONFIRMED` audit-style row and appends an inter-department cost-transfer ledger entry that debits the reserving user's `department` and credits the owner lab's `department` by `final_owner_share_cents` if the reservation has reached `COMPLETED`, or by `estimated_owner_share_cents` otherwise.

An IM-delivery acknowledgement may be ingested through the platform-admin-only IM-notified event hook with an `audit_event_id` referencing a previously written audit row and an `im_delivery_id` identifying the downstream delivery; the system updates the audit row's `payload_json` to include the supplied `im_delivery_id`. The hook is idempotent on the (`audit_event_id`, `im_delivery_id`) pair.

The logical clock itself is exposed for tests via a platform-admin-only clock-advance capability that accepts a `target_time` ISO timestamp and runs every due time-gated transition in a deterministic order: `MaintenanceWindow` `SCHEDULED` → `IN_PROGRESS` and `IN_PROGRESS` → `AWAITING_ACCEPTANCE` first, then `Authorization` `APPROVED` → `EXPIRED`, then `Reservation` `BOOKED` → `NO_SHOW`. Each transition fires only if its own preconditions hold at the moment it is evaluated; the cascade chain runs to fixed point so that an authorization expiry that cancels a reservation also writes the reservation's audit row before the clock-advance returns.

## 4. Endpoint Definitions

Endpoints that create a brand-new resource return `201 Created`; every other successful operation — state transitions, status updates, listings, and event ingest — returns `200 OK`. Errors return the HTTP status documented in §5.

| Method | Path                                                                              | Description                                                                                  | Authorized Role(s)         |
| ------ | --------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | -------------------------- |
| POST   | `/_clock/advance`                                                                 | Advance the server's logical clock and run due time-gated transitions                        | PlatformAdmin              |
| POST   | `/_events/payment-confirmed`                                                      | Idempotent payment-confirmed ingest                                                          | PlatformAdmin              |
| POST   | `/_events/identity-verified`                                                      | Idempotent identity-verification ingest                                                      | PlatformAdmin              |
| POST   | `/_events/im-notified`                                                            | IM-system delivery acknowledgement                                                           | PlatformAdmin              |
| POST   | `/labs`                                                                           | Create a Lab                                                                                 | PlatformAdmin              |
| GET    | `/labs/{lab_id}`                                                                  | Get lab details                                                                              | PlatformAdmin, LabOwner    |
| POST   | `/labs/{lab_id}/settle`                                                           | Periodic owner-lab settlement                                                                | PlatformAdmin              |
| POST   | `/equipment`                                                                      | Register equipment                                                                           | LabOwner                   |
| GET    | `/equipment`                                                                      | List equipment (filters: lab_id, status, sharing_scope, value_tier)                          | PlatformAdmin, LabOwner, User |
| GET    | `/equipment/{equipment_id}`                                                       | Get equipment details                                                                        | PlatformAdmin, LabOwner, User |
| PUT    | `/equipment/{equipment_id}`                                                       | Update equipment profile or retire it                                                        | LabOwner                   |
| POST   | `/equipment/{equipment_id}/billing-rules`                                         | Draft a billing rule                                                                         | LabOwner                   |
| GET    | `/equipment/{equipment_id}/billing-rules`                                         | List billing rules for an equipment                                                          | PlatformAdmin, LabOwner    |
| POST   | `/equipment/{equipment_id}/billing-rules/{rule_id}/publish`                       | Publish a draft billing rule                                                                  | LabOwner                   |
| POST   | `/equipment/{equipment_id}/maintenance-windows`                                   | Create a maintenance window                                                                  | LabOwner                   |
| POST   | `/maintenance-windows/{window_id}/accept`                                         | Accept maintenance completion                                                                | LabOwner, PlatformAdmin    |
| POST   | `/maintenance-windows/{window_id}/reject`                                         | Reject maintenance completion (spawns follow-up window)                                      | LabOwner, PlatformAdmin    |
| POST   | `/users`                                                                          | Create user (idempotent on external_user_id)                                                 | PlatformAdmin              |
| GET    | `/users/{user_id}`                                                                | Get user details                                                                             | PlatformAdmin, LabOwner, User |
| POST   | `/equipment/{equipment_id}/authorizations`                                        | Request usage authorization                                                                  | User                       |
| POST   | `/authorizations/{authorization_id}/approve`                                      | Approve an authorization (owner step or platform step)                                       | LabOwner, PlatformAdmin    |
| POST   | `/authorizations/{authorization_id}/reject`                                       | Reject an authorization                                                                      | LabOwner, PlatformAdmin    |
| POST   | `/authorizations/{authorization_id}/revoke`                                       | Revoke an APPROVED authorization                                                             | LabOwner, PlatformAdmin    |
| POST   | `/equipment/{equipment_id}/reservations`                                          | Create a reservation                                                                         | User                       |
| GET    | `/reservations`                                                                   | List reservations (filters: equipment_id, user_id, status, start_at_from, start_at_to)        | PlatformAdmin, LabOwner, User |
| GET    | `/reservations/{reservation_id}`                                                  | Get reservation details                                                                      | PlatformAdmin, LabOwner, User |
| POST   | `/reservations/{reservation_id}/check-in`                                         | User checks in to start the session                                                          | User                       |
| POST   | `/reservations/{reservation_id}/check-out`                                        | User checks out and the system finalises the fee                                             | User                       |
| POST   | `/reservations/{reservation_id}/cancel`                                           | Cancel a BOOKED reservation                                                                  | User, LabOwner             |
| GET    | `/audit-events`                                                                   | List audit events                                                                            | PlatformAdmin, LabOwner    |

## 5. Error Code Catalogue

| Error ID                              | HTTP Status Code |
| ------------------------------------- | ---------------- |
| `ERR_MISSING_AUTH`                    | 401 Unauthorized |
| `ERR_FORBIDDEN`                       | 403 Forbidden    |
| `ERR_NOT_FOUND`                       | 404 Not Found    |
| `ERR_INVALID_STATE`                   | 409 Conflict     |
| `ERR_EQUIPMENT_UNAVAILABLE`           | 409 Conflict     |
| `ERR_AUTHORIZATION_INVALID`           | 422 Unprocessable Entity |
| `ERR_AUTHORIZATION_ALREADY_DECIDED`   | 409 Conflict     |
| `ERR_CERTIFICATE_EXPIRED`             | 422 Unprocessable Entity |
| `ERR_QUALIFICATION_NOT_MET`           | 422 Unprocessable Entity |
| `ERR_SHARING_SCOPE_VIOLATION`         | 422 Unprocessable Entity |
| `ERR_LEAD_TIME_VIOLATED`              | 422 Unprocessable Entity |
| `ERR_SLOT_GRID_VIOLATION`             | 422 Unprocessable Entity |
| `ERR_DURATION_LIMIT_EXCEEDED`         | 422 Unprocessable Entity |
| `ERR_MAINTENANCE_BLOCK`               | 409 Conflict     |
| `ERR_RESERVATION_OVERLAP`             | 409 Conflict     |
| `ERR_PEAK_PRIORITY_VIOLATION`         | 409 Conflict     |
| `ERR_FEE_SPLIT_INVALID`               | 422 Unprocessable Entity |
| `ERR_BILLING_RULE_RACED`              | 409 Conflict     |
| `ERR_NOTHING_TO_SETTLE`               | 422 Unprocessable Entity |
| `ERR_IDEMPOTENCY_CONFLICT`            | 409 Conflict     |
| `ERR_VERSION_CONFLICT`                | 409 Conflict     |
| `ERR_BAD_REQUEST`                     | 400 Bad Request  |
