# Flexible-Rent Splitting API — Product Requirements Document

## 1. Introduction

Renters increasingly need to spread a single month's rent across several smaller payments, or to push part of it a few weeks down the calendar, without the landlord ever waiting on the money. This platform sits between the two parties: it advances the full monthly rent to the landlord on schedule, then collects the renter's own financed share back in installments, charging a transparent flex fee for the service. The product therefore has to reconcile two ledgers at once — what the platform has paid out to a property owner, and what a renter still owes the platform — while keeping both perfectly balanced at every step.

The system spans the entire lifecycle of a financed rent obligation: onboarding a landlord property and its renters, underwriting each renter to an approved financing limit, building a per-month pay schedule (either a multi-way **split** or a single **deferral**), remitting full rent to the landlord, collecting repayments with ret/retry-capped charge attempts and optional autopay, and — when a renter falls behind — running a structured delinquency-recovery workflow that can end in either reinstatement, a negotiated settlement, or a charged-off write-down. Because money moves in both directions, several operations mutate more than one record at once, and the specification is explicit about every cascade so that no derived figure is ever left stale.

Segregation of duties is a first-class concern. The operator who runs day-to-day money movement is deliberately separated from the underwriter who issues credit decisions, and the collections manager who signs off a write-off must not be the same person who last worked the case. Time itself is modeled explicitly through a server-controlled logical clock, so that overdue math, promise windows, and recovery periods are deterministic and testable rather than tied to wall-clock time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID`, an opaque identifier for the acting principal, and `X-User-Role`, naming one of the six recognized roles. When either header is missing or blank, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. When the headers are present but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The six roles are `PlatformAdmin`, `Underwriter`, `CollectionsAgent`, `CollectionsManager`, `Renter`, and `PropertyManager`.

- A `PlatformAdmin` runs operations: registering properties, adjusting their integration state, creating renters and billing cycles, remitting and settling, cancelling, running delinquency assessment, reversing remittances, and driving the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- An `Underwriter` reviews applications and issues approve or decline decisions, and is walled off from money movement. When `X-User-Role` is `Underwriter`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- A `CollectionsAgent` works recovery: outreach, promises, retries, assessment, and resolution. When `X-User-Role` is `CollectionsAgent`, `X-User-ID` is an opaque operator identifier; the server records it on a case as `last_recovery_agent_id` (and on each recovery action as `agent_id`) where a transition writes it, but does not compare it to any entity's `id`.
- A `CollectionsManager` approves charge-offs. When `X-User-Role` is `CollectionsManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it is compared only against a case's `last_recovery_agent_id` for the segregation-of-duties check, never against any entity's `id`.
- A `Renter` is an enrolled resident who applies for financing, manages autopay, charges and defers the installments of their own cycles, and may withdraw their own application. When `X-User-Role` is `Renter`, `X-User-ID` is the `id` of the acting `Renter`; ownership checks on any resource that references a renter compare the resource's renter foreign key (a renter's own `id`, a cycle's `renter_id`, or the `renter_id` of the cycle a target installment belongs to) to `X-User-ID`.
- A `PropertyManager` is the landlord-side viewer of a property's remittances and cycles. When `X-User-Role` is `PropertyManager`, `X-User-ID` is the `id` of the acting `Property`; ownership checks on any resource that references a property compare the resource's property foreign key to `X-User-ID`.

When an entity-backed `Renter` or `PropertyManager` acts on a resource they do not own, the request is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403).

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100. A supplied `limit` below 1 or above 100 is clamped into the [1, 100] range rather than rejected, a negative `offset` is treated as 0, and a `limit`/`offset` that is not an integer is rejected with `ERR_VALIDATION`. The `offset` defaults to 0 and represents the number of leading records to skip. Every list is returned sorted by `created_at` in ascending order, so that the oldest record appears first and pagination is stable across pages.

For list responses, the `meta` block additionally carries `limit` and `offset` (the values in effect for the response), `total_count` (the total number of records matching the query before pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is minted with a server-generated `id` — a UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC form with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format), refreshed on every mutation, and an integer `version` that starts at 1 on creation and increments by one on each mutation that changes the resource.

Three resource types are append-only records of something that happened and therefore carry only `id` and `created_at` — they have neither an `updated_at` nor a `version` field: the recovery-action record (with `case_id`, `action_type`, `agent_id`, `promise_date`, and `note`), the reminder record (with `renter_id`, `cycle_id`, `kind`, `channel`, and `sent_at`), and the ledger entry (with `cycle_id`, `entry_type`, `amount_cents`, and `memo`). All other resources — properties, renters, applications, billing cycles, installments, remittances, and autopay mandates, delinquency cases — carry the full `id`/`created_at`/`updated_at`/`version` set.

When an operation mutates several resources at once, each mutated resource independently refreshes its own `updated_at` and increments its own `version`. A cascade that flips a child's state is a mutation of that child and bumps the child's `version`, just as the triggering write bumps the parent's.

### 2.5. The Logical Clock and Deterministic Time

All deadline, overdue, and elapsed-time math is evaluated against a server-controlled **logical clock**, never against wall-clock time. On startup the clock reads exactly `2026-07-01T00:00:00Z`, and before any clock-setting call it holds that default rather than drifting to real time. A `PlatformAdmin` may advance the clock to a supplied instant, expressed as an ISO 8601 value in the `to_iso8601` field; every subsequent deadline comparison, due-date check, promise-window check, and recovery-period check reads the clock at that value. Timestamps stamped by the system onto resources — an installment's `paid_at`, a remittance's `sent_at`, a reminder's `sent_at`, and a case's `opened_at` — are all taken from the logical clock at the moment of the triggering operation.

### 2.6. Monetary Precision and the Cents Convention

Every monetary amount in the system is an integer number of cents; there are no fractional cents anywhere in stored state or in responses. Where a calculation produces a non-integer intermediate — an income-percentage limit, a defer-carry fee — the result is rounded half up to the nearest whole cent (a value exactly halfway between two cents rounds to the larger cent). Where a calculation divides a principal into installment shares, the division is done as integer floor division and the leftover cents are distributed deterministically rather than rounded per share (see §3.4). Aggregations that sum already-integer cents — a cycle's repaid amount, its net remitted total — are exact and involve no rounding.

### 2.7. The Ledger, the Money-Movement Sign Convention, and the Remittance Invariant

Every movement of money against a cycle is recorded as an immutable ledger entry carrying the cycle's `cycle_id`, an `entry_type`, a signed `amount_cents`, and a human-readable `memo`. The seven entry types are `REMITTANCE_ADVANCE`, `REPAYMENT`, `FEE`, `FEE_REFUND`, `LATE_FEE`, `WRITE_OFF`, and `REVERSAL`. By the platform's receivable sign convention, entries that increase what is owed to the platform are positive — `REMITTANCE_ADVANCE`, `FEE`, and `LATE_FEE` — while entries that reduce the receivable are negative — `REPAYMENT`, `FEE_REFUND`, `WRITE_OFF`, and `REVERSAL`.

A cycle's `net_remitted_cents` is a conserved quantity defined as the sum of its `REMITTANCE_ADVANCE` entry amounts minus the sum of its `REVERSAL` entry amounts. This is the remittance invariant: once full rent is advanced, `net_remitted_cents` equals the advanced full rent; once a remittance is reversed, the compensating reversal restores `net_remitted_cents` to 0. No operation is permitted to leave this figure inconsistent with the ledger.

### 2.8. Optimistic Concurrency on Cycle Rescheduling

Rescheduling a billing cycle rebuilds its installment layout — cancelling the prior scheduled installments and minting a fresh set that supersedes them — so it must act on the layout currently in effect. A reschedule request must therefore carry `expected_cycle_version`, the `version` of the target billing cycle the client last observed. If that value does not match the cycle's current `version` — because another writer has advanced the cycle since the client read it — the request is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412), preventing the client from superseding a layout it has not seen. The version comparison is evaluated only after body well-formedness and the domain-range checks (split-count bounds, custom-offset gap, and defer window) have already passed, so a request that is simultaneously stale and domain-invalid reports the domain error rather than `ERR_STALE_CYCLE_VERSION`. On a successful reschedule the cycle's `version` increments by one. No other endpoint takes a version field; rescheduling is the only optimistically-concurrent operation.

### 2.9. Path Resolution and Validation Ordering

Endpoints whose URLs reference resources by id validate those references left to right along the path. A missing resource yields a not-found error naming that resource — `ERR_PROPERTY_NOT_FOUND`, `ERR_RENTER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_BILLING_CYCLE_NOT_FOUND`, `ERR_INSTALLMENT_NOT_FOUND`, `ERR_REMITTANCE_NOT_FOUND`, `ERR_MANDATE_NOT_FOUND`, or `ERR_DELINQUENCY_CASE_NOT_FOUND` — each HTTP 404.

When multiple checks could fail on one request, they are evaluated in a fixed priority order so that the reported error is deterministic. Authentication (presence of both headers, else `ERR_UNAUTHENTICATED`) comes first; then role authorization (`ERR_UNAUTHORIZED`); then body well-formedness for write endpoints — required fields present, enums valid, integers of the correct type and within their declared syntactic range such as `rent_due_day` between 1 and 28, else `ERR_VALIDATION` (HTTP 400); then existence of path-referenced resources (the not-found errors above); then ownership for entity-backed callers (`ERR_OWNERSHIP_VIOLATION`); then the target's state permitting the transition (`ERR_INVALID_STATE`, HTTP 409); then the attempt-count guard on charge and retry (`ERR_MAX_ATTEMPTS_EXCEEDED`, HTTP 409); then the charge-off segregation-of-duties guard (`ERR_SOD_VIOLATION`, HTTP 403); then the remaining cross-entity, temporal, domain-range, and fiscal checks described in §3. Domain-range checks such as split-count bounds and the defer window are business constraints evaluated in this later band, not part of the initial body-syntax check.

## 3. Business Logic & Workflows

### 3.1. Property Onboarding and Landlord Integration

A `PlatformAdmin` registers a landlord property, supplying the owner's `landlord_name`, a human-readable `unit_label` such as "Maple Court #4B", the `full_rent_cents` the platform will remit each month (which must be greater than zero), the `rent_due_day` on which rent falls due (a day-of-month from 1 through 28), and an opaque `remittance_account_ref` naming the payout account. The registration may also set `integration_status`; when omitted it defaults to `PENDING`. The integration status is one of `PENDING`, `ACTIVE`, or `SUSPENDED`, and the property's `status` field is a computed mirror of it — whenever the integration status is set, the listing-facing `status` is updated to the same value.

Integration status matters because it gates money movement to the landlord. A `PlatformAdmin` may later move a property between `PENDING`, `ACTIVE`, and `SUSPENDED` through a dedicated integration update, which sets `integration_status` to the supplied value and re-mirrors `status`. A property must be `ACTIVE` before any of its cycles can be remitted (see §3.5). A `PlatformAdmin` can fetch or list properties — listing accepts an optional `status` filter — and a `PropertyManager` may read only the property they own, along with the remittances sent for it.

### 3.2. Renter Enrollment and Underwriting

A `PlatformAdmin` creates a renter as a `PROSPECT` attached to a property, supplying the `property_id`, the renter's `email` (unique within the property — a duplicate email under the same property is rejected with `ERR_VALIDATION`, HTTP 400), their `full_name`, and the `portion_rent_cents` — the renter's own share of monthly rent that will be financed and split, which must be greater than zero. A newly created renter's enrollment `status` is `PROSPECT`; its lifecycle values are `PROSPECT`, `UNDERWRITING`, `ENROLLED`, and `SUSPENDED`. On creation the renter's `risk_band` is null, its `approved_limit_cents` is 0, and its `autopay_enabled` flag is false. The `risk_band` mirrors the underwriting band once a decision lands, and `autopay_enabled` mirrors whether the renter's autopay mandate is active.

Underwriting begins when an application is submitted against a renter — either by the `Renter` themselves for their own record, or by a `PlatformAdmin` on their behalf. The submission carries the applicant's `reported_monthly_income_cents` (greater than zero), the `requested_split_count` of how many installments they wish to split into (from 2 through 4), and optionally a self-declared `prior_delinquency_count` of past rent delinquencies (a non-negative integer defaulting to 0). Submitting an application moves the renter's `status` to `UNDERWRITING`, and the application itself begins in `SUBMITTED` (its lifecycle values are `SUBMITTED`, `APPROVED`, `DECLINED`, and `WITHDRAWN`). The application carries the underwriting foreign key `renter_id`.

At submission time the system immediately computes the application's `risk_score`, `risk_band`, and `approved_limit_cents`. The score is a weighted blend of three sub-scores, each derived from one input. The **income-to-rent ratio** is the applicant's reported monthly income divided by the renter's own financed portion (`portion_rent_cents`); its sub-score is 100 when the ratio is at least 3.0, otherwise 70 when it is at least 2.0, otherwise 40 when it is at least 1.5, otherwise 10. The **split** sub-score is 100 when the requested split count is 2 or fewer, 70 when it is exactly 3, and 40 otherwise. The **delinquency** sub-score is 100 when the prior delinquency count is 0, 60 when it is exactly 1, and 20 otherwise. The overall `risk_score` is the ratio sub-score weighted at one-half, plus the split sub-score weighted at one-fifth, plus the delinquency sub-score weighted at three-tenths, with the weighted total rounded half up to a whole integer on a 0-to-100 scale where higher is safer.

The `risk_band` follows directly from the score: `LOW` when the score is at least 75, `MEDIUM` when it is at least 50 (but below 75), and `HIGH` otherwise. The `approved_limit_cents` is the smaller of two ceilings: the renter's financed portion multiplied by a band factor — 3 for a `LOW` band, 2 for a `MEDIUM` band, and 1 for a `HIGH` band — and one-half of the reported monthly income rounded half up to whole cents. The lower of those two figures is the approved limit.

An `Underwriter` then issues a decision on a `SUBMITTED` application, supplying a `decision` of either APPROVE or DECLINE; alternatively the owning `Renter` may supply a decision of WITHDRAW on their own application. A decision on an application that is not `SUBMITTED` is rejected with `ERR_INVALID_STATE`. Approval requires both that the application's `risk_score` is at least 50 and that the income-to-rent ratio is at least 1.5; when either condition fails the application cannot be approved and is instead declined. On the `SUBMITTED → APPROVED` transition the system fixes the application's `approved_limit_cents`, `risk_band`, and a human-readable `decision_reason`, then cascades: the renter's `status` becomes `ENROLLED` (from `PROSPECT` or `UNDERWRITING`), the renter's `approved_limit_cents` and `risk_band` are copied from the application, and — if the renter has no mandate yet — an autopay mandate is created for them in `PAUSED`. This is a two-step cascade from application to renter to a new mandate.

On the `SUBMITTED → DECLINED` transition the system sets the application's `decision_reason` and cascades the renter's `status` to `SUSPENDED`, which blocks that renter from having cycles created. On the `SUBMITTED → WITHDRAWN` transition, available only to the owning renter, the application's `decision_reason` is set to indicate withdrawal by the renter. While an application remains `SUBMITTED`, its `decision_reason` is null. A `Renter`, `Underwriter`, or `PlatformAdmin` may read a single application or list a renter's applications.

### 3.3. Autopay Mandates

Each renter has at most one autopay mandate, created automatically in `PAUSED` at the moment their application is approved. A mandate carries the owner's `renter_id`, an opaque `method_ref` payment-method handle (null until the renter supplies one), and a `status` that is one of `PAUSED`, `ACTIVE`, or `REVOKED`. Only the owning `Renter` may change their mandate, supplying the new `status` and, when activating, a `method_ref`.

Activating a mandate — the `PAUSED → ACTIVE` transition — requires that a non-null `method_ref` be present, either supplied in the activating request or already stored on the mandate; an activation with no `method_ref` available is rejected with `ERR_VALIDATION` (HTTP 400). On activation the renter's `autopay_enabled` flag then becomes true. Pausing an active mandate — `ACTIVE → PAUSED` — sets `autopay_enabled` back to false, and the mandate can be re-activated later, so `PAUSED` and `ACTIVE` form a cycle. A mandate may be revoked from either `ACTIVE` or `PAUSED` into the terminal `REVOKED` state; revoking from `ACTIVE` sets `autopay_enabled` to false, and once `REVOKED` a mandate cannot transition again. A transition attempted from a state that does not permit it is rejected with `ERR_INVALID_STATE`. The owning renter (or a `PlatformAdmin`) may read a mandate directly, or fetch the renter's mandate through the renter, which returns an array of zero or one mandate.

### 3.4. Billing Cycle Creation and the Installment Layout

A `PlatformAdmin` opens a monthly pay-schedule cycle for an enrolled renter. Cycle creation requires that the renter's `status` be `ENROLLED`; otherwise the request is rejected with `ERR_RENTER_NOT_ENROLLED` (HTTP 409). The request supplies the `renter_id`, the `cycle_month` in `YYYY-MM` form (unique per renter among non-cancelled cycles), the `cycle_start_date` ISO datetime that anchors installment due-dates as day zero, and the `mode`, which is either `SPLIT` or `DEFER`. At most one non-`CANCELLED` cycle may exist for a given renter and `cycle_month`; a second is rejected with `ERR_DUPLICATE_CYCLE` (HTTP 409).

At creation the cycle snapshots two amounts that never move afterward: `full_rent_cents` is copied from the property (the amount the platform will remit to the landlord) and `portion_cents` is copied from the renter's `portion_rent_cents` (the total the renter repays across installments). The cycle also copies the renter's `property_id`. The financed portion may not exceed the renter's approved ceiling: if `portion_cents` is greater than the renter's `approved_limit_cents`, creation is rejected with `ERR_LIMIT_EXCEEDED` (HTTP 402). Once the renter is resolved, these creation checks run in a fixed order: renter-enrollment (`ERR_RENTER_NOT_ENROLLED`) first, then the mode's domain-range guard (`ERR_DEFER_WINDOW_EXCEEDED` in `DEFER` mode or `ERR_INVALID_SPLIT_COUNT` in `SPLIT` mode), then the duplicate-cycle guard (`ERR_DUPLICATE_CYCLE`), and finally the approved-limit guard (`ERR_LIMIT_EXCEEDED`). A cycle begins in `SCHEDULED`; its lifecycle values are `SCHEDULED`, `REMITTED`, `SETTLED`, `DELINQUENT`, `WRITTEN_OFF`, and `CANCELLED`. Its computed `repaid_amount_cents` starts at 0, `net_remitted_cents` at 0, `fee_final_cents` null until settled, and `outstanding_cents` equal to `portion_cents` less the repaid amount.

**Split mode.** When the `mode` is `SPLIT`, the request also supplies a `split_count` of how many installments to divide the portion into. The split count must lie between 2 and 4 inclusive; a value outside that band is rejected with `ERR_INVALID_SPLIT_COUNT` (HTTP 422). The portion is divided by taking the integer floor of `portion_cents` divided by the split count as the base share, then computing the leftover as `portion_cents` minus that base multiplied by the count — a remainder of zero up to one less than the count. The installments are numbered by `sequence_no` starting at 1, and each of the earliest sequence numbers up to and including the remainder receives one extra cent on top of the base share; the later sequences receive exactly the base. Shares are never rounded individually, so the sum of installment `amount_cents` exactly equals `portion_cents`. Each installment's `due_date` is the cycle start date plus a fixed spacing multiplied by its zero-based position: the spacing is 14 days when the split count is 2, 10 days when it is 3, and 7 days when it is 4. The first installment's `kind` is `IMMEDIATE` (due at day zero) and every later one is `SPLIT`.

**Defer mode.** When the `mode` is `DEFER`, the cycle always has exactly two installments and the split count is fixed at 2. The request supplies `deferred_amount_cents` — the portion pushed to the later installment — and `planned_defer_days`, the number of days after the cycle start on which that deferred installment falls due. The planned defer days must lie between 1 and 25 inclusive; a value of zero or beyond 25 is rejected with `ERR_DEFER_WINDOW_EXCEEDED` (HTTP 422). The first installment's `amount_cents` is `portion_cents` minus the deferred amount, its `kind` is `IMMEDIATE`, and it is due at day zero; the second installment's `amount_cents` is the deferred amount, its `kind` is `DEFERRED`, and it is due at the cycle start plus the planned defer days. Here too the two shares sum exactly to `portion_cents`.

Every installment carries its parent `cycle_id`, its `sequence_no`, `due_date`, `amount_cents`, and `kind`, an `attempt_count` starting at 0, a `paid_at` that is null until paid, and a `status` beginning at `SCHEDULED` (its lifecycle values are `SCHEDULED`, `PAID`, `FAILED`, `WAIVED`, and `CANCELLED`). The provisional flex fee is computed and stored at creation as described in §3.7. A `PlatformAdmin` may read or list cycles (the list accepts optional `renter_id`, `property_id`, and `status` filters), and a `PlatformAdmin`, owning `Renter`, or the cycle's `PropertyManager` may read a single cycle, its installments, and its computed summary.

**Rescheduling.** A `PlatformAdmin` may rebuild a cycle's installment layout, superseding the prior plan. A reschedule carries `expected_cycle_version` for the optimistic-concurrency guard of §2.8 and may supply a revised `mode`, `split_count`, `deferred_amount_cents`, `planned_defer_days`, or an explicit list of `due_offsets_days` for custom installment spacing. Rescheduling cancels the prior `SCHEDULED` installments and mints a fresh set by the same allocation rules, keeping the sum of non-`CANCELLED` installment amounts equal to `portion_cents`, and increments the cycle's `version` by one. A reschedule in `SPLIT` mode is subject to the same 2-through-4 split-count bound (`ERR_INVALID_SPLIT_COUNT`). When custom offsets are given, consecutive installment due dates must be at least 5 days apart; offsets closer than that are rejected with `ERR_INSTALLMENT_GAP_TOO_SHORT` (HTTP 422). Supplied `due_offsets_days` take precedence over `mode` and `split_count`: the offsets are sorted ascending, the cycle's `split_count` is set to the number of offsets, the portion is allocated across them by the same floor-plus-remainder rule (extra cents to the earliest sequences), the installment at the earliest offset takes `kind` `IMMEDIATE` and every later one `SPLIT`, and the minimum-gap check is applied to the sorted offsets.

### 3.5. Remitting Full Rent to the Landlord, and Reversal

Once a cycle is `SCHEDULED`, a `PlatformAdmin` advances the landlord's full rent, moving the cycle `SCHEDULED → REMITTED`. Remittance requires that the cycle's property be integrated: the property's `integration_status` must be `ACTIVE`, otherwise the request is rejected with `ERR_PROPERTY_NOT_ACTIVE` (HTTP 409). A cycle may not be remitted twice — if a non-`REVERSED` remittance already exists for it, the transition is refused as an invalid state. Remitting creates a remittance record in `SENT` carrying the cycle's `cycle_id`, the `property_id` copied from the cycle as the payout target, an `amount_cents` equal to the cycle's `full_rent_cents`, and a `sent_at` stamped from the logical clock (its lifecycle values are `SENT` and `REVERSED`). It appends a `REMITTANCE_ADVANCE` ledger entry of the full rent amount and a `FEE` ledger entry of the provisional flex fee, and recomputes `net_remitted_cents` to equal the full rent. The remittance operation returns the created remittance.

Remittance can be undone as a compensating operation while no repayment has yet landed. A `PlatformAdmin` reverses a `SENT` remittance — moving it `SENT → REVERSED` and the cycle `REMITTED → SCHEDULED` — but only when the cycle is still `REMITTED` and its `repaid_amount_cents` is exactly 0. Reversal appends a `REVERSAL` ledger entry of the negative full rent and a `FEE_REFUND` ledger entry of the negative provisional fee, and recomputes `net_remitted_cents` back to 0, restoring the remittance invariant. A `PlatformAdmin` or `PropertyManager` may read a remittance or list the remittances of a property or of a cycle.

### 3.6. Installment Repayment, Retries, and Deferral

With a cycle remitted, the renter begins repaying it installment by installment. A charge attempt against an installment may be initiated by the owning `Renter` or by a `PlatformAdmin`, and carries a `method` (the pay method, either manual or autopay) and an optional `outcome` that deterministically simulates whether the attempt succeeds or fails. When `outcome` is omitted the attempt succeeds; a value of `FAIL`, `FAILURE`, `FAILED`, `DECLINE`, or `DECLINED` (case-insensitive) makes it fail, and any other supplied value is treated as a success. A charge is only permitted while the parent cycle is `REMITTED` or `DELINQUENT`; otherwise it is an invalid state. When the `method` is autopay, the renter's autopay mandate must be `ACTIVE`, or the charge is rejected with `ERR_AUTOPAY_NOT_ACTIVE` (HTTP 409).

A successful charge moves the installment `SCHEDULED → PAID`: it increments `attempt_count` by one, sets `paid_at` from the logical clock, appends a `REPAYMENT` ledger entry of the negative installment amount, and recomputes the cycle's `repaid_amount_cents` and `outstanding_cents`. A failed charge moves the installment `SCHEDULED → FAILED` and increments `attempt_count` by one. Both a charge and a retry are guarded by an attempt ceiling of three: an installment whose `attempt_count` has reached three may not be charged or retried again, and such an attempt is rejected with `ERR_MAX_ATTEMPTS_EXCEEDED` (HTTP 409). A `FAILED` installment can be re-armed for another attempt by the owning `Renter` or a `PlatformAdmin`, moving it `FAILED → SCHEDULED`, provided the attempt count is still below three; this `SCHEDULED`/`FAILED` retry loop is the repayment machine's only cycle. Even when a repayment fully clears the outstanding balance of a `DELINQUENT` cycle, the cycle does not auto-settle — an explicit resolve or settle is still required (see §3.8 and §3.7).

Once an installment has exhausted its attempts, collections may waive it. A `FAILED` installment moves to the terminal `WAIVED` state only while a delinquency case exists for its cycle and that case is in `IN_OUTREACH`, `PROMISE_TO_PAY`, or `BROKEN_PROMISE`; on waiver, the cycle's `repaid_amount_cents` is recomputed treating the waived principal as satisfied.

A renter (or `PlatformAdmin`) may also defer a single `SCHEDULED` installment to a later due date, supplying a `new_due_offset_days` measured from the cycle start. The new offset must fall within the 1-to-25-day defer window, or the request is rejected with `ERR_DEFER_WINDOW_EXCEEDED`. Deferral cancels the source installment and mints a replacement of `kind` `DEFERRED` with the same `amount_cents` and a `sequence_no` one greater than the highest existing installment sequence number on the cycle, due at the cycle start plus the new offset; the sum of non-`CANCELLED` installment amounts is unchanged and still equals `portion_cents`.

The cycle's `repaid_amount_cents` is always the exact sum of the `amount_cents` of that cycle's installments whose `status` is either `PAID` or `WAIVED`; cancelled, scheduled, and failed installments contribute nothing. The cycle's `outstanding_cents` is `portion_cents` minus that repaid amount — the principal the renter still owes. These figures are recomputed on every payment, waiver, reschedule, and cancellation.

### 3.7. The Flex Fee and Settlement

The platform's charge for the service is the **flex fee**, computed once provisionally at cycle creation (stored as `fee_provisional_cents`) and once finally at settlement (stored as `fee_final_cents`, null until then). The fee has three components. The **membership component** is fixed by the renter's `risk_band`: 1500 cents for a `LOW` band, 2500 cents for `MEDIUM`, and 4000 cents for `HIGH`. The **split component** is 500 cents for each installment beyond the first — that is, the split count reduced by one (but never below zero) multiplied by 500. The **defer carry component** applies only in `DEFER` mode and is otherwise zero; in defer mode it is the deferred amount multiplied by a daily rate of 30 basis points and by the number of defer days, divided by 10,000, with the result rounded half up to whole cents. Critically, the carry is charged on the raw deferred principal (`deferred_amount_cents`) alone, never on any figure that already includes the fee. The flex fee is the sum of the three components.

The provisional and final computations differ only in which defer-day count they use. The **provisional** fee, computed at creation and charged as the `FEE` ledger entry on remittance, uses the scheduled `planned_defer_days`. The **final** fee, computed at settlement, uses the actual number of days the deferred installment was outstanding — the whole-day floor of the elapsed time from the cycle start date to the deferred installment's `paid_at`. When the renter pays the deferred installment early, the actual days are fewer than planned, the final fee is smaller than the provisional fee, and the difference is refunded.

A `PlatformAdmin` settles a fully-repaid cycle, moving it `REMITTED → SETTLED`. Settlement requires that the cycle's `repaid_amount_cents` be at least its `portion_cents` — equivalently that `outstanding_cents` be zero or below, with the boundary case of exactly zero permitted; a settle attempted while any principal remains is rejected with `ERR_INSUFFICIENT_REPAYMENT` (HTTP 422). Settlement computes `fee_final_cents` by the final variant above, and when the final fee is less than the provisional fee it appends a `FEE_REFUND` ledger entry for the negative of that shortfall (the provisional fee minus the final fee), then sets the cycle to `SETTLED`.

A `PlatformAdmin` may cancel a cycle that has never been remitted, moving it `SCHEDULED → CANCELLED`; cancellation is refused (as an invalid state) once a `SENT` remittance exists. Cancelling cascades every `SCHEDULED` or `FAILED` installment of the cycle to `CANCELLED`.

### 3.8. Delinquency Assessment and the Recovery Workflow

A `PlatformAdmin` runs a time-driven delinquency assessment against a cycle. When at least one of the cycle's installments is past its `due_date` (the logical clock has advanced beyond it) and is not `PAID`, `WAIVED`, or `CANCELLED`, and the cycle's `outstanding_cents` is still greater than zero, the cycle moves `REMITTED → DELINQUENT`. The assessment runs only on a `REMITTED` cycle; when the cycle is in any other state, or no installment is both overdue (its `due_date` strictly before the logical clock) and unpaid, or `outstanding_cents` is not greater than zero, the request is rejected with `ERR_INVALID_STATE` (HTTP 409). Otherwise it opens a delinquency case in `OPEN`, carrying the cycle's `cycle_id`, the `renter_id` copied from the cycle, a `principal_outstanding_cents` snapshot equal to the cycle's current outstanding (though on every subsequent read of the case this field — like the two payoff figures below — is re-derived live from the cycle's `portion_cents` minus its `repaid_amount_cents`, not returned as the frozen opening value), an `opened_at` stamped from the logical clock, a `recovery_round` starting at 0, an `accrued_late_fee_cents` starting at 0, and a `last_recovery_agent_id` that is null until an agent works the case. A `CHARGE_OFF_NOTICE` is not sent here; instead an `OVERDUE` reminder is emitted (see below).

Opening a case may also accrue the flat late fee. The number of days overdue is the whole-day floor of the elapsed time from the earliest unpaid installment's `due_date` to the logical clock. When that count reaches at least 5 days — the grace period — the flat late fee of 2500 cents is applied: a `LATE_FEE` ledger entry of 2500 is appended and the case's `accrued_late_fee_cents` is set to 2500. On the fourth overdue day no flat fee applies; on the fifth it does. The assessment also emits an `OVERDUE` reminder for the renter. Every reminder record carries the recipient's `renter_id`, the concerning `cycle_id`, a `kind` (one of `OVERDUE`, `PROMISE_CONFIRMATION`, or `CHARGE_OFF_NOTICE`), a delivery `channel` fixed to `EMAIL`, and a `sent_at` from the logical clock.

A `CollectionsAgent` drives the recovery workflow by recording recovery actions against a case, each supplying an `action_type` of `OUTREACH`, `PROMISE_SET`, `RETRY_CHARGE`, or `NOTE`, an optional `promise_date`, and an optional free-text `note`. Recording an action creates a recovery-action record carrying the `case_id`, the `action_type`, the acting agent's `agent_id` (the `X-User-ID`), and any `promise_date` and `note`; every action also stamps that same `X-User-ID` onto the case as `last_recovery_agent_id`. An `OUTREACH` action opens outreach, moving a case `OPEN → IN_OUTREACH`, or re-opens it `BROKEN_PROMISE → IN_OUTREACH` — the latter increments the case's `recovery_round` by one, closing the recovery cycle. A `PROMISE_SET` action moves a case `IN_OUTREACH → PROMISE_TO_PAY`, recording the supplied `promise_date` on the case and emitting a `PROMISE_CONFIRMATION` reminder; the promised date must fall within 14 days of the logical clock, or the action is rejected with `ERR_PROMISE_WINDOW_EXCEEDED` (HTTP 422).

A promise that comes due unpaid is caught by a time-driven case assessment, which a `CollectionsAgent` or `PlatformAdmin` may run. The case must be in `PROMISE_TO_PAY`; when it is not, or the logical clock has not yet passed the recorded `promise_date`, or the cycle's `outstanding_cents` is no longer greater than zero, the request is rejected with `ERR_INVALID_STATE` (HTTP 409). When the logical clock has passed the case's `promise_date` and the cycle's `outstanding_cents` remains greater than zero, the case moves `PROMISE_TO_PAY → BROKEN_PROMISE`: the per-round late fee of 1000 cents is applied, adding 1000 to the case's `accrued_late_fee_cents` and appending a `LATE_FEE` ledger entry of 1000. The case's `accrued_late_fee_cents` is therefore the flat opening fee (2500 when the grace period was met, else 0) plus 1000 for each broken-promise transition recorded so far. From `BROKEN_PROMISE` a fresh `OUTREACH` re-enters `IN_OUTREACH`, and the outreach → promise → broken-promise loop may repeat, each lap advancing `recovery_round`. A `CollectionsAgent` or `CollectionsManager` may read a single case, list cases (filtered by optional `cycle_id`, `renter_id`, and `status`), and list a case's recovery actions.

### 3.9. Reinstatement, Settlement Payoffs, Resolution, and Charge-Off

A delinquency case exposes two payoff figures so the parties can choose how to cure it. Both start from the unpaid principal — the cycle's `portion_cents` minus its `repaid_amount_cents`. The `reinstatement_amount_cents` is that principal plus the full `accrued_late_fee_cents`: the complete arrears including every late fee, paid to reactivate the schedule. The `settlement_amount_cents` is that same principal plus a flat settlement administration fee of 1500 cents, with the accrued late fees waived: the discounted lump-sum figure collections may negotiate. The two figures diverge whenever the accrued late fees are not exactly 1500 cents. Both figures are exposed when reading a case directly and on the cycle summary; the summary reports them for every cycle regardless of delinquency, using an accrued-late-fee of 0 (so `reinstatement_amount_cents` equals the bare principal) when no delinquency case exists.

A case is resolved once the renter has actually cured the principal. A `CollectionsAgent` resolves a case from `OPEN`, `IN_OUTREACH`, `PROMISE_TO_PAY`, or `BROKEN_PROMISE` into the terminal `RESOLVED` state, which requires the cycle's `outstanding_cents` to be zero or below (a resolve attempted while principal still remains is rejected with `ERR_NO_OUTSTANDING_BALANCE`, HTTP 422); resolution cascades the cycle to `SETTLED`. (Correspondingly, a `DELINQUENT` cycle reaches `SETTLED` through this resolution, not through the ordinary settle path.)

When recovery fails, a `CollectionsManager` charges the case off, moving it from `BROKEN_PROMISE` or `IN_OUTREACH` into the terminal `CHARGED_OFF` state. Three conditions gate the write-off, and each has its own rejection; they are evaluated in the §2.9 priority order, so the segregation-of-duties guard is checked first, then the recovery-period check, then the balance check. First, the recovery period must have elapsed: the logical clock must be at least 30 days past the case's `opened_at`, or the request is rejected with `ERR_RECOVERY_PERIOD_NOT_ELAPSED` (HTTP 422). Second, segregation of duties applies — the acting manager's `X-User-ID` must differ from the case's `last_recovery_agent_id` (the agent who last worked it); when they are equal the request is rejected with `ERR_SOD_VIOLATION` (HTTP 403). Third, there must actually be a balance to write off: the cycle's `outstanding_cents` must be greater than zero, or the request is rejected with `ERR_NO_OUTSTANDING_BALANCE` (HTTP 422). A charge-off cascades the cycle to `WRITTEN_OFF`, appends a `WRITE_OFF` ledger entry for the negative of the outstanding balance, and emits a `CHARGE_OFF_NOTICE` reminder to the renter.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201; endpoints that modify or transition an existing resource, and all reads, return HTTP 200. Request and response bodies are governed by the narratives in §3; the table below lists only the routing contract.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/api/properties` | Register a landlord property | PlatformAdmin |
| GET | `/api/properties/{id}` | Fetch a property | PlatformAdmin, PropertyManager |
| GET | `/api/properties` | List properties | PlatformAdmin |
| PATCH | `/api/properties/{id}/integration` | Set property integration status | PlatformAdmin |
| GET | `/api/properties/{id}/remittances` | List a property's remittances | PlatformAdmin, PropertyManager |
| POST | `/api/renters` | Create a renter attached to a property | PlatformAdmin |
| GET | `/api/renters/{id}` | Fetch a renter | PlatformAdmin, Renter |
| GET | `/api/renters` | List renters, optionally by property | PlatformAdmin |
| POST | `/api/renters/{id}/applications` | Submit an underwriting application | Renter, PlatformAdmin |
| GET | `/api/applications/{id}` | Fetch an application | Underwriter, PlatformAdmin, Renter |
| GET | `/api/renters/{id}/applications` | List a renter's applications | Underwriter, PlatformAdmin, Renter |
| POST | `/api/applications/{id}/decision` | Approve, decline, or withdraw an application | Underwriter, Renter |
| GET | `/api/renters/{id}/autopay-mandate` | Fetch the renter's autopay mandate | Renter, PlatformAdmin |
| GET | `/api/autopay-mandates/{id}` | Fetch an autopay mandate | Renter, PlatformAdmin |
| PATCH | `/api/autopay-mandates/{id}` | Set mandate status and method | Renter |
| POST | `/api/billing-cycles` | Create a monthly pay-schedule cycle | PlatformAdmin |
| GET | `/api/billing-cycles/{id}` | Fetch a billing cycle | PlatformAdmin, Renter, PropertyManager |
| GET | `/api/billing-cycles` | List billing cycles | PlatformAdmin |
| POST | `/api/billing-cycles/{id}/reschedule` | Rebuild the installment layout (OCC-guarded) | PlatformAdmin |
| POST | `/api/billing-cycles/{id}/remit` | Advance full rent to the landlord | PlatformAdmin |
| POST | `/api/billing-cycles/{id}/settle` | Settle a fully-repaid cycle | PlatformAdmin |
| POST | `/api/billing-cycles/{id}/cancel` | Cancel a never-remitted cycle | PlatformAdmin |
| POST | `/api/billing-cycles/{id}/assess-delinquency` | Time-driven delinquency check | PlatformAdmin |
| GET | `/api/billing-cycles/{id}/installments` | List a cycle's installments | PlatformAdmin, Renter |
| GET | `/api/billing-cycles/{id}/remittances` | List a cycle's remittances | PlatformAdmin, PropertyManager |
| GET | `/api/billing-cycles/{id}/ledger` | List a cycle's ledger entries | PlatformAdmin, PropertyManager |
| GET | `/api/billing-cycles/{id}/reminders` | List reminders for a cycle | PlatformAdmin, Renter |
| GET | `/api/billing-cycles/{id}/summary` | Computed reporting read for a cycle | PlatformAdmin, Renter, PropertyManager |
| GET | `/api/installments/{id}` | Fetch an installment | PlatformAdmin, Renter |
| POST | `/api/installments/{id}/charge` | Attempt a repayment charge | Renter, PlatformAdmin |
| POST | `/api/installments/{id}/retry` | Re-arm a failed installment | Renter, PlatformAdmin |
| POST | `/api/installments/{id}/defer` | Defer a scheduled installment | Renter, PlatformAdmin |
| GET | `/api/remittances/{id}` | Fetch a remittance | PlatformAdmin, PropertyManager |
| POST | `/api/remittances/{id}/reverse` | Reverse a sent remittance | PlatformAdmin |
| GET | `/api/delinquency-cases/{id}` | Fetch a delinquency case | PlatformAdmin, CollectionsAgent, CollectionsManager |
| GET | `/api/delinquency-cases` | List delinquency cases | PlatformAdmin, CollectionsAgent, CollectionsManager |
| POST | `/api/delinquency-cases/{id}/recovery-actions` | Record a recovery step | CollectionsAgent |
| GET | `/api/delinquency-cases/{id}/recovery-actions` | List a case's recovery actions | CollectionsAgent, CollectionsManager, PlatformAdmin |
| POST | `/api/delinquency-cases/{id}/assess` | Time-driven promise check | CollectionsAgent, PlatformAdmin |
| POST | `/api/delinquency-cases/{id}/charge-off` | Write off a case after the recovery period | CollectionsManager |
| POST | `/api/delinquency-cases/{id}/resolve` | Resolve a cured case | CollectionsAgent |
| GET | `/api/renters/{id}/reminders` | List a renter's reminders | PlatformAdmin, Renter |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_PROPERTY_NOT_FOUND` | 404 |
| `ERR_RENTER_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_BILLING_CYCLE_NOT_FOUND` | 404 |
| `ERR_INSTALLMENT_NOT_FOUND` | 404 |
| `ERR_REMITTANCE_NOT_FOUND` | 404 |
| `ERR_MANDATE_NOT_FOUND` | 404 |
| `ERR_DELINQUENCY_CASE_NOT_FOUND` | 404 |
| `ERR_OWNERSHIP_VIOLATION` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MAX_ATTEMPTS_EXCEEDED` | 409 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_RENTER_NOT_ENROLLED` | 409 |
| `ERR_PROPERTY_NOT_ACTIVE` | 409 |
| `ERR_AUTOPAY_NOT_ACTIVE` | 409 |
| `ERR_DEFER_WINDOW_EXCEEDED` | 422 |
| `ERR_PROMISE_WINDOW_EXCEEDED` | 422 |
| `ERR_RECOVERY_PERIOD_NOT_ELAPSED` | 422 |
| `ERR_INVALID_SPLIT_COUNT` | 422 |
| `ERR_INSTALLMENT_GAP_TOO_SHORT` | 422 |
| `ERR_DUPLICATE_CYCLE` | 409 |
| `ERR_LIMIT_EXCEEDED` | 402 |
| `ERR_INSUFFICIENT_REPAYMENT` | 422 |
| `ERR_NO_OUTSTANDING_BALANCE` | 422 |
| `ERR_STALE_CYCLE_VERSION` | 412 |







