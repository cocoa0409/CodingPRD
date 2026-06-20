# Equestrian Barn API — Product Requirements Document

## 1. Introduction

The Equestrian Barn API is the operational backbone of a full-service boarding stable. It coordinates the people, the horses, and the money that flow through a working barn: owners who entrust their animals to the facility, the horses themselves and the stalls or pastures that house them, the lessons and farrier/vet/dentist visits that fill the daily calendar, the show entries that take horses off-property, the turnout windows that share limited pasture, and the invoices that reconcile all of it at the end of each billing period. Every monetary figure in the system is expressed in integer cents so that totals never drift through floating-point error, and every timestamp is an ISO-8601 UTC value carrying three fractional digits.

A defining characteristic of this domain is that time is a first-class business input. Liability waivers expire on a fixed cadence; lessons may only be cancelled outside a protective cutoff window; service visits and pasture turnouts contend for overlapping windows. To make these temporal rules deterministic and testable, the system never reads the wall clock. Instead it consults a logical clock whose value is whatever was last supplied through the clock-setting capability; before any value is set, the logical clock reads `1970-01-01T00:00:00.000Z`. Owners are the billing aggregate root of the model, and a single misjudged finalization can double-count deposits or line items — so the billing pathway is guarded by optimistic concurrency on the owner record. The remainder of this document specifies the contract precisely (Section 2) and then narrates the business workflows that an implementer must reconstruct end to end (Section 3).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. If either header is missing or malformed, the request is rejected with `ERR_MISSING_USER_CONTEXT`. The system recognizes exactly four roles, spelled precisely as follows: `BarnManager`, `Owner`, `Instructor`, and `ServiceProvider`. When a role is syntactically valid but not permitted to perform the requested operation — including a role that is permitted for some target states of a transition endpoint but not the specific one requested — the request is rejected with `ERR_FORBIDDEN_ROLE`.

The `BarnManager` is the barn's operations and billing authority. When `X-User-Role` is `BarnManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it against any entity's `id`. The same opaque-identity rule applies to the `Instructor` role and the `ServiceProvider` role: in both cases `X-User-ID` is an opaque operator identifier (instructors and service providers are not persisted entities, so an instructor is named on a lesson only through the free-text `instructor_name` field rather than by reference), and the server never compares it to any entity's `id`.

The `Owner` role is different. When `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting `Owner` entity. Ownership checks on any resource that ultimately belongs to an owner compare that owner identity to `X-User-ID`: for a horse this is its `owner_id`; for a waiver or an invoice it is the `owner_id`; for a lesson, service visit, show entry, boarding agreement, or turnout assignment it is the `owner_id` of the horse reached through the resource's `horse_id`. When an `Owner` attempts an owner-scoped write (acting on its own horses, waivers, lessons, service/show/turnout requests, or withdrawals) against a resource that resolves to a different owner, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and accepted values range from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result and defaults to 0. A `limit` outside the range 1–100, a negative `offset`, or a `limit`/`offset` that is not a valid integer is rejected with `ERR_INVALID_REQUEST`.

Unless a specific endpoint states otherwise, list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. Every list response carries the pagination bookkeeping in the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identifiers

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits at the moment of creation. Most resources additionally carry two managed fields: `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 and increments by one with each mutation of the resource. Owners, liability waivers, stalls, horses, boarding agreements, lessons, service visits, show entries, turnout assignments, and invoices all carry the full set of `id`, `created_at`, `updated_at`, and `version`. Recomputing a derived field on a resource — for example refreshing an owner's standing score, a stall's occupied count, or an agreement's charge figures — is itself a mutation that refreshes `updated_at` and increments `version` on the resource that changed.

### 2.5. Nested Resource Retrieval and Reference Resolution

Several paths address resources nested beneath a parent, such as a waiver beneath an owner. The system validates path identifiers strictly left to right and rejects on the first one that does not resolve, returning the not-found error specific to that position. Path identifiers and their dedicated errors are: an owner id (`ERR_OWNER_NOT_FOUND`), a waiver id (`ERR_WAIVER_NOT_FOUND`), an invoice id (`ERR_INVOICE_NOT_FOUND`), a horse id (`ERR_HORSE_NOT_FOUND`), a boarding-agreement id (`ERR_AGREEMENT_NOT_FOUND`), a lesson id (`ERR_LESSON_NOT_FOUND`), a service-visit id (`ERR_VISIT_NOT_FOUND`), a show-entry id (`ERR_ENTRY_NOT_FOUND`), a turnout id (`ERR_TURNOUT_NOT_FOUND`), and a stall id (`ERR_STALL_NOT_FOUND`). A request for a waiver under a non-existent owner therefore fails with `ERR_OWNER_NOT_FOUND` before the waiver is ever consulted.

Foreign keys carried in a request body are resolved separately. On creation endpoints, the body's references — `owner_id`, `horse_id`, `stall_id`, and `pasture_id` — must each resolve to an existing entity before any state-machine or business rule is evaluated; an unresolved body reference fails with the corresponding not-found error (`ERR_OWNER_NOT_FOUND`, `ERR_HORSE_NOT_FOUND`, or `ERR_STALL_NOT_FOUND`, the last covering both `stall_id` and `pasture_id` since a pasture is a kind of stall).

### 2.6. Validation Ordering

When several conditions could each reject a single request, they are evaluated in a fixed priority so that the returned error is deterministic. The order is: first, user context is checked (`ERR_MISSING_USER_CONTEXT`); then role permission for the operation and, on transition endpoints, for the specific requested target status (`ERR_FORBIDDEN_ROLE`); then, for owner-scoped writes, resource ownership (`ERR_NOT_RESOURCE_OWNER`); then existence of every path identifier left to right (the 404 family); then resolution of body foreign-key references (the 404 family); then field-shape constraints on the body (`ERR_INVALID_REQUEST`); then whether the requested `target_status` is one the transition endpoint recognizes and whether the target resource is in a legal state for it (the state-conflict family — `ERR_INVALID_STATE`, `ERR_WAIVER_NOT_SIGNABLE`, `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_INVOICE_NOT_OPEN`, `ERR_INVOICE_NOT_FINALIZED`; a `target_status` that is absent, unknown, or not a transition this endpoint supports is rejected with `ERR_INVALID_STATE`); and finally the domain-specific business rules described throughout Section 3 (waiver-active, boarding-active, cancellation cutoff, visit overlap, pasture capacity, stall capacity, turnout-in-past, owner-standing, invoice-has-payments, no-billable-lines, overpayment, deposit-floor, and stale-version checks). The general rule is: authentication before authorization, authorization before existence, existence before shape, shape before state, and state before deeper business logic.

### 2.7. Field-Shape Constraints

Before any state or business rule runs, the system validates the shape of a creation body and rejects malformed input with `ERR_INVALID_REQUEST`. A lesson's `ends_at` must be strictly after its `starts_at`. A turnout's `window_end` must be strictly after its `window_start`. A service visit's `duration_minutes` must be greater than zero, and any quantity-style amount must be at least 1. A stall's capacity depends on its kind: a stall whose `kind` is `STALL` must have `capacity` equal to 1, while a pasture whose `kind` is `PASTURE` must have `capacity` of at least 1. A `pasture_id` supplied for a turnout must reference a stall whose `kind` is `PASTURE`. Any field declared as an enum must carry one of its defined members. A request that violates any of these shape rules — or that omits a required field or supplies a malformed enum value — is rejected with `ERR_INVALID_REQUEST`.

### 2.8. Monetary Precision and Rounding

All monetary amounts are integer cents; the API neither accepts nor emits fractional cents. Where a calculation multiplies an amount by a percentage and could produce a fraction of a cent — a no-show lesson fee, a multi-horse discount — the result is rounded half up to a whole number of cents. Where a calculation works in whole days, day counts are taken as the floor of the difference. The exact order in which rounding and summation are applied for an invoice is contractually pinned and is specified in Section 3; implementers must follow that order rather than rounding the aggregate.

### 2.9. Derived-Field Reconciliation and Cascades

Many fields in this system are computed projections of other state, and the system keeps them continuously reconciled. A stall's `occupied_count` always equals the number of boarding agreements in `ACTIVE` or `SUSPENDED` status currently assigned to it, and it must never exceed the stall's `capacity`. An owner's `account_balance_cents`, `deposit_held_cents`, `standing_score`, and `provisional_standing_score`, and a boarding agreement's `suspended_days`, `provisional_charge_cents`, and `final_charge_cents`, are all maintained by the system rather than written directly by clients.

Certain transitions ripple across more than one resource. The expiry of a liability waiver suspends an owner's active boarding agreements, and suspending an agreement in turn cancels that horse's future scheduled lessons; re-signing a waiver can reinstate eligible suspended agreements; ending an agreement releases its stall slot and cancels the horse's future turnouts; and finalizing or voiding an invoice moves money on the owner record and flips the invoiced state of swept lines. Each of these cascades is specified in full where the triggering workflow is narrated in Section 3. Whenever a cascade mutates a secondary resource, that resource's own `updated_at` and `version` are refreshed exactly as a direct mutation would refresh them.

### 2.10. Optimistic Concurrency on Owner Billing

Invoice finalization is the one operation in this system protected by optimistic concurrency control, because finalization both consumes an owner's deposit and marks the owner's billable lines as invoiced — a snapshot that another finalization could legitimately supersede. The invoice-finalize request therefore requires a non-optional `expected_owner_version` field (an integer) carrying the client's last observed `version` of the target invoice's owner. Both the presence/integer-shape of this field and its comparison are evaluated at the optimistic-concurrency stage — after the invoice's `OPEN`-state check and the at-least-one-billable-line check have passed — so a finalize against a non-`OPEN` invoice surfaces `ERR_INVOICE_NOT_OPEN`, and a finalize that reaches the concurrency stage with a missing or non-integer `expected_owner_version` is rejected with `ERR_INVALID_REQUEST`. At finalization time the server compares `expected_owner_version` against the owner's current `version`. If another writer has advanced the owner's version since the client last read it — for instance because a prior finalization already consumed deposit and marked lines invoiced — the stale request is rejected with `ERR_STALE_OWNER_VERSION` (HTTP 412), so the same deposit and the same lines cannot be double-counted. Finalization is the only endpoint that accepts a version field; no other endpoint takes one, and supplying one elsewhere has no concurrency effect.

### 2.11. The Logical Clock

All temporal preconditions — waiver expiry and the lesson cancellation cutoff — are evaluated against a logical clock rather than the host's wall clock. The clock-setting capability records a supplied UTC instant as the current logical time. Until it is first set, the clock reads `1970-01-01T00:00:00.000Z`. Setting the clock does not by itself fire any lazy expiry; in particular, a waiver that has reached its expiry instant is only transitioned the next time the owner's waiver list is read. This is described in detail in Section 3.

## 3. Business Logic & Workflows

### 3.1. Owners, Deposits, and the Account Ledger

An owner account is the root of everything billable, created by a `BarnManager` with a `full_name` and an `email` (which must be unique across owners; a creation whose `email` collides with an existing owner is rejected with `ERR_INVALID_REQUEST`). A freshly created owner begins life in `ACTIVE` status with `deposit_held_cents`, `account_balance_cents`, `standing_score`, and `provisional_standing_score` all at zero and `version` at 1.

Two monetary fields track the owner's relationship with the barn. The `deposit_held_cents` field is the refundable security deposit the barn currently holds; it is adjusted through a deposit-adjustment capability that accepts a signed `amount_cents` (a positive value adds to the held deposit, a negative value refunds part of it). The held deposit may never be driven below zero — a refund larger than the deposit on hand is rejected with `ERR_INSUFFICIENT_DEPOSIT` — and a successful adjustment increments the owner's `version`. The `account_balance_cents` field is the running ledger of what the owner owes: it accumulates the amount due of each finalized invoice and is reduced as payments are applied, so a positive balance means the owner owes the barn.

When an owner record is read, the system recomputes and returns the owner's `provisional_standing_score` (the projection described in Section 3.9) without persisting any committed field. The committed `standing_score` and the derived `status` are only ever rewritten by the invoice events of Section 3.8.

### 3.2. Stalls, Pastures, and Occupancy

A `BarnManager` provisions housing by creating a stall, which is described by a unique `label` (a creation whose `label` collides with an existing stall is rejected with `ERR_INVALID_REQUEST`), a `kind` of either `STALL` or `PASTURE`, a `capacity`, and a `daily_rate_cents` charged per horse per occupied day. The capacity rule of Section 2.7 applies: a `STALL` holds exactly one horse, while a `PASTURE` may co-locate several. A new stall starts with `occupied_count` at zero.

The `occupied_count` is reconciled by the boarding lifecycle: it rises by one when an agreement is activated into that stall and falls by one when an agreement ends. Because the count tracks both `ACTIVE` and `SUSPENDED` agreements, a suspended horse continues to hold its slot. The count is reflected directly when a stall is read, and a stall exposes reverse views of the agreements assigned to it and of the turnouts booked on it.

### 3.3. Horses

A horse is registered against an owner — by a `BarnManager` or by the owning `Owner` — with the owner's `owner_id` and the horse's `name`. A horse is the hub through which lessons, service visits, show entries, boarding agreements, and turnout assignments are reached: each of those resources carries the horse's `horse_id`, and ownership and boarding checks throughout the system resolve from the resource through its horse to the owner. Reverse-reachability reads expose, for a given horse, its boarding agreements (reflecting their provisional and final charges), its lessons (reflecting billed fees), its service visits, its show entries, and its turnouts; an owner-scoped read lists all of an owner's horses.

### 3.4. The Liability Waiver Cycle

Boarding and showing both depend on the owner holding a valid liability waiver, and waivers move through a renewal cycle. An owner (or a `BarnManager` acting on their behalf) creates a waiver, which records its `owner_id` and begins in `PENDING` status with `signed_at`, `expires_at`, and `superseded_by_id` all null. Creating a new waiver while the owner already holds a `SIGNED` waiver supersedes the old one: the system points the old waiver's `superseded_by_id` at the new waiver's `id` and moves the old waiver to `SUPERSEDED`, which is terminal. The `superseded_by_id` is a forward lineage pointer discovered through the same owner's waiver list, not a parent reference.

Only the owning `Owner` may sign a waiver, and signing covers two cases. Signing a `PENDING` waiver moves it `PENDING → SIGNED`; re-signing an `EXPIRED` waiver renews the same waiver `EXPIRED → SIGNED`. In both cases the system stamps `signed_at` with the current logical time and recomputes `expires_at` as exactly 365 days after `signed_at` (waivers are valid for one year). A sign attempted on a waiver that is in neither `PENDING` nor `EXPIRED` is rejected with `ERR_WAIVER_NOT_SIGNABLE`.

A waiver expires by the passage of logical time rather than by an explicit call. A `SIGNED` waiver is considered `EXPIRED` once the logical clock reaches or passes its `expires_at` — the boundary is inclusive, so at exactly `expires_at` the waiver is already expired. This transition is realized lazily: when an owner's waiver list is read, each `SIGNED` waiver whose `expires_at` the clock has reached or passed is moved `SIGNED → EXPIRED` before the list is returned (the lazy expiry and its cascade run before any optional `status` filter is applied; the waiver list additionally accepts an optional `status` query parameter that, when supplied, restricts the returned waivers to those whose `status` equals the given value). Expiry carries a cascade: every `ACTIVE` boarding agreement belonging to every horse owned by that owner transitions `ACTIVE → SUSPENDED` (the first hop of the waiver-suspends-boarding chain), which in turn fires the lesson-cancellation cascade described in Section 3.5.

Re-signing an expired waiver carries the inverse cascade. When the owner re-signs and the waiver returns to `SIGNED`, every `SUSPENDED` boarding agreement of that owner's horses that has a recorded suspension (its `suspended_at` is set) is transitioned `SUSPENDED → ACTIVE` — but only for an owner whose committed `standing_score` is below the suspension threshold of 80 points. A delinquent owner's agreements remain suspended even after the waiver is renewed.

### 3.5. The Boarding Agreement Lifecycle

A boarding agreement is the contract that places one horse in one stall, and it is the most intricate state machine in the system. A `BarnManager` drafts an agreement with the horse's `horse_id`, the chosen `stall_id`, and a `start_date` (the first occupied day, inclusive); it is created in `DRAFT` with `end_date`, `suspended_at` null, `suspended_days` at zero, and both `provisional_charge_cents` and `final_charge_cents` at zero. All lifecycle moves run through the agreement's transition capability, driven by a `target_status`.

**Activating from draft.** A `BarnManager` activates a `DRAFT` agreement by requesting target status `ACTIVE`. The agreement must currently be `DRAFT`, or the request fails with `ERR_INVALID_STATE`. Two further preconditions guard activation: the owner must hold a `SIGNED` non-expired liability waiver, failing which the request is rejected with `ERR_WAIVER_NOT_ACTIVE`. This "non-expired" check is evaluated point-in-time against the logical clock rather than against the persisted status, so a waiver in `SIGNED` status whose `expires_at` the clock has already reached or passed (inclusive boundary) does not satisfy the precondition even though its lazy `SIGNED → EXPIRED` flip has not yet been realized; the same point-in-time waiver-active test gates show-entry confirmation and agreement reinstatement. The second precondition is that the chosen stall must have room — its `occupied_count` must be strictly less than its `capacity`, or activation fails with `ERR_STALL_FULL`. On success the agreement becomes `ACTIVE`, the stall's `occupied_count` increases by one, and the agreement's `provisional_charge_cents` is computed by the provisional boarding-charge rule of Section 3.6.

**Suspending.** An `ACTIVE` agreement moves to `SUSPENDED` either when a `BarnManager` requests target status `SUSPENDED` or when the waiver-expiry cascade reaches it. The agreement must be `ACTIVE`, or the request fails with `ERR_AGREEMENT_NOT_ACTIVE`. On suspension the agreement becomes `SUSPENDED` and `suspended_at` is stamped with the current logical time. Suspension carries its own cascade — the second hop of the chain begun by waiver expiry: every `SCHEDULED` lesson of that horse whose `starts_at` is at or after the current logical time is transitioned `SCHEDULED → CANCELLED` with its `billed_fee_cents` set to zero.

**Reinstating.** A `SUSPENDED` agreement returns to `ACTIVE` either when a `BarnManager` requests target status `ACTIVE` or when the waiver re-sign cascade reaches it. The agreement must be `SUSPENDED`, or the request fails with `ERR_INVALID_STATE`. The owner must again hold a `SIGNED` non-expired waiver (`ERR_WAIVER_NOT_ACTIVE` otherwise), and the owner's committed `standing_score` must be strictly less than the suspension threshold of 80 points, or reinstatement is refused with `ERR_OWNER_DELINQUENT`. On success the agreement becomes `ACTIVE` again; the whole number of days between `suspended_at` and the current logical time is added to the agreement's `suspended_days`, and `suspended_at` is cleared to null.

**Ending.** A `BarnManager` ends an agreement that is currently `ACTIVE` or `SUSPENDED` by requesting target status `ENDED`. On ending, the agreement becomes `ENDED` (a terminal state) and its `end_date` is stamped with the current logical time (treated as the exclusive move-out day). If the agreement was `SUSPENDED` at the moment it ended, the whole number of days between `suspended_at` and the current logical time is first added to `suspended_days`. The agreement's `final_charge_cents` is then computed by the final boarding-charge rule of Section 3.6, the stall's `occupied_count` is decreased by one, and a release cascade fires: every `BOOKED` turnout assignment of that horse whose `window_start` is at or after the current logical time is transitioned `BOOKED → CANCELLED`.

### 3.6. Boarding Charges: Provisional and Final

A boarding agreement carries two distinct charge figures computed at two different moments, both denominated in the stall's `daily_rate_cents`. The **provisional** charge is forward-looking and is set when the agreement is activated, before actual occupancy is known: it projects a full standard billing month and equals the daily rate multiplied by 30 days. It deliberately ignores any future suspension and any earlier-than-expected move-out.

The **final** charge is chronological and is computed when the agreement ends. The system first counts the whole occupied days from `start_date` inclusive to `end_date` exclusive — that is, the floor of the day difference between the two dates. It then subtracts the agreement's accumulated `suspended_days`, because suspended days are not charged, yielding the number of charged days. The final charge equals the daily rate multiplied by that charged-day count. The provisional and final charges coincide only in the special case where occupied days happen to equal exactly 30 and no days were spent suspended.

### 3.7. Lessons, Service Visits, Show Entries, and Turnouts

**Lessons.** A lesson is scheduled by a `BarnManager` or an `Owner` with the horse's `horse_id`, an `instructor_name`, a `lesson_fee_cents`, a `starts_at` (inclusive) and an `ends_at` (exclusive, strictly after `starts_at`); it begins `SCHEDULED` with `billed_fee_cents` zero and `invoiced` false. A scheduled lesson resolves into exactly one of three terminal branches, each setting `billed_fee_cents` differently. Marking it `COMPLETED` is performed by an `Instructor`: the lesson must be `SCHEDULED` (else `ERR_INVALID_STATE`) and the horse's boarding agreement must be `ACTIVE` (else `ERR_BOARDING_NOT_ACTIVE`), and on success `billed_fee_cents` is set to the full `lesson_fee_cents`. Marking it `NO_SHOW` is also performed by an `Instructor`: the lesson must be `SCHEDULED` (else `ERR_INVALID_STATE`), and `billed_fee_cents` is set to the full fee multiplied by 50 percent, rounded half up to whole cents. Cancelling it may be performed by a `BarnManager`, the `Owner`, or an `Instructor`: the lesson must be `SCHEDULED` (else `ERR_INVALID_STATE`), and — the protective cutoff — the current logical time must be at or before `starts_at` minus 24 hours; a cancellation requested later than that is rejected with `ERR_CANCEL_TOO_LATE` (the boundary is inclusive, so cancelling at exactly 24 hours before start is allowed). A cancelled lesson has `billed_fee_cents` of zero.

**Service visits.** A farrier, vet, or dentist visit is requested by a `BarnManager` or an `Owner` with the horse's `horse_id`, a `visit_type` of `FARRIER`, `VET`, or `DENTIST`, a `scheduled_at` (the inclusive window start), a `duration_minutes` greater than zero, and a `fee_cents`; it begins `REQUESTED` with `invoiced` false. Its occupied window is the half-open interval from `scheduled_at` up to `scheduled_at` plus `duration_minutes`. A `BarnManager` schedules a requested visit by requesting target status `SCHEDULED`: the visit must be `REQUESTED` (else `ERR_INVALID_STATE`), and scheduling is rejected with `ERR_VISIT_OVERLAP` if any other `SCHEDULED` or `COMPLETED` service visit for the *same horse* has a window that overlaps this one (a pairwise overlap of the two half-open windows). A `ServiceProvider` completes a scheduled visit by requesting target status `COMPLETED` (the visit must be `SCHEDULED`, else `ERR_INVALID_STATE`), at which point its `fee_cents` becomes an invoiceable line. A `BarnManager` or `Owner` may cancel a visit that is `REQUESTED` or `SCHEDULED` by requesting target status `CANCELLED`, which releases the horse's window so a replacement visit may be scheduled.

**Show entries.** A show entry is submitted by a `BarnManager` or an `Owner` with the horse's `horse_id`, an `event_name`, an `event_date`, and an `entry_fee_cents`; it begins `SUBMITTED` with `invoiced` false. A `BarnManager` confirms a submitted entry by requesting target status `CONFIRMED`: the entry must be `SUBMITTED` (else `ERR_INVALID_STATE`) and the owner must hold a `SIGNED` non-expired waiver (else `ERR_WAIVER_NOT_ACTIVE`); on confirmation the `entry_fee_cents` becomes an invoiceable line. The owning `Owner` may withdraw a still-`SUBMITTED` entry by requesting target status `WITHDRAWN` (the entry must be `SUBMITTED`, else `ERR_INVALID_STATE`); a withdrawn entry bills no fee. A `BarnManager` may scratch a `CONFIRMED` entry by requesting target status `SCRATCHED` (the entry must be `CONFIRMED`, else `ERR_INVALID_STATE`); a scratched entry keeps its `entry_fee_cents` as a no-refund billable line. Both `SCRATCHED` and `WITHDRAWN` are terminal.

**Turnouts.** A pasture turnout is booked by a `BarnManager` or an `Owner` with the horse's `horse_id`, a `pasture_id` (which must reference a stall whose `kind` is `PASTURE`), a `window_start` (inclusive) and a `window_end` (exclusive, strictly after `window_start`); it begins `BOOKED`. Three guards apply at booking, beyond the field-shape checks: the `window_start` must not be in the past relative to the current logical clock, or the request is rejected with `ERR_TURNOUT_IN_PAST`; the horse's boarding agreement must be `ACTIVE` (not suspended, ended, or absent), or the request is rejected with `ERR_BOARDING_NOT_ACTIVE`; and the pasture must have concurrent capacity, enforced by the rule of Section 3.10. A `BarnManager` or `Owner` cancels a booked turnout by requesting target status `CANCELLED` (the turnout must be `BOOKED`, else `ERR_INVALID_STATE`), which frees the horse's slot in the pasture's concurrent-capacity count; the agreement-end cascade of Section 3.5 also drives this same `BOOKED → CANCELLED` transition automatically.

### 3.8. Invoicing and Settlement

An invoice gathers an owner's unbilled work for a period and settles it. A `BarnManager` opens an invoice with the owner's `owner_id` and a `period_label` (for example, a month tag); it begins `OPEN` with `gross_amount_cents`, `multi_horse_discount_cents`, `deposit_applied_cents`, `amount_due_cents`, and `paid_amount_cents` all zero. An owner-scoped read lists the owner's invoices and reflects their computed totals; this list additionally accepts an optional `status` query parameter that, when supplied, restricts the returned invoices to those whose `status` equals the given value. The invoice lifecycle is driven by the invoice transition capability and a `target_status`.

**Finalizing.** A `BarnManager` finalizes an `OPEN` invoice by requesting target status `FINALIZED`, supplying `expected_owner_version` (Section 2.10). The invoice must be `OPEN` (else `ERR_INVOICE_NOT_OPEN`); at least one unbilled billable line must exist for the owner (else `ERR_NO_BILLABLE_LINES`); and `expected_owner_version` must equal the owner's current `version` (else `ERR_STALE_OWNER_VERSION`, HTTP 412). On success the system computes the invoice totals by the rule of Section 3.9, then: it reduces the owner's `deposit_held_cents` by the `deposit_applied_cents` it consumed; it increases the owner's `account_balance_cents` by the `amount_due_cents`; it marks every swept line (the qualifying lessons, service visits, show entries, and boarding agreements) `invoiced` true; it increments the owner's `version` by one; and it recomputes the owner's committed `standing_score` by the final standing rule of Section 3.9.

**Paying.** A `BarnManager` records a payment against a `FINALIZED` invoice by requesting target status `PAID` and supplying an `amount_cents`. The invoice must be `FINALIZED` (else `ERR_INVOICE_NOT_FINALIZED`); the `amount_cents` field is read and validated at this stage, after the state check, so a missing or non-integer `amount_cents` is rejected with `ERR_INVALID_REQUEST`. The payment must not overpay: `paid_amount_cents` already recorded plus the new `amount_cents` must not exceed `amount_due_cents`, or the request is rejected with `ERR_OVERPAYMENT`. On success the new `amount_cents` is added to `paid_amount_cents`, the owner's `account_balance_cents` is reduced by the same `amount_cents`, and the owner's committed `standing_score` is recomputed. The invoice moves to `PAID` only once `paid_amount_cents` equals `amount_due_cents` exactly; partial payments leave it `FINALIZED`.

**Voiding.** A `BarnManager` voids an invoice by requesting target status `VOID`, which is legal from either `OPEN` or `FINALIZED`. Voiding an `OPEN` invoice simply moves it to `VOID`; no deposit was applied while open, so `deposit_held_cents` is unchanged. Voiding a `FINALIZED` invoice is permitted only when no payment has been recorded — `paid_amount_cents` must be zero, or the request is rejected with `ERR_INVOICE_HAS_PAYMENTS` — and it fully reverses finalization: the owner's `deposit_held_cents` is increased by the `deposit_applied_cents` that was consumed (restoring the deposit), the owner's `account_balance_cents` is reduced by the `amount_due_cents`, every swept line is reverted to `invoiced` false, the owner's `version` is incremented by one, and the owner's committed `standing_score` is recomputed. Both `PAID` and `VOID` are terminal.

### 3.9. Invoice Totals and Owner Standing

**Invoice totals.** When an invoice is finalized, its totals are computed from the owner's eligible unbilled lines — those whose `invoiced` flag is still false across the owner's horses: the `billed_fee_cents` of each `COMPLETED` or `NO_SHOW` lesson, the `fee_cents` of each `COMPLETED` service visit, the `entry_fee_cents` of each `CONFIRMED` or `SCRATCHED` show entry, and the `final_charge_cents` of each `ENDED` boarding agreement. The computation proceeds in a pinned three-step order. Step one produces `gross_amount_cents`: each individual line value is rounded half up to whole cents first, and only then are the rounded line values summed — the rounding happens per line before summation, never on the aggregate. Step two produces the `multi_horse_discount_cents`: let the discount percentage be 0 percent when the number of distinct horses contributing an `ENDED` boarding-agreement line is at most 1, 5 percent when that distinct count is exactly 2, and 10 percent when it is 3 or more; the discount is `gross_amount_cents` multiplied by that percentage, rounded half up to whole cents once after the summation. Step three is the deposit waterfall: the net is `gross_amount_cents` minus the discount; the `deposit_applied_cents` is the smaller of the owner's `deposit_held_cents` and that net; and the `amount_due_cents` is the net minus the applied deposit, floored at zero so it is never negative.

**Owner standing.** An owner's delinquency risk is scored 0 to 100 and lives in a different domain from boarding cost — it concerns the owner, not any single agreement. The score has two parts. The balance component takes the owner's balance, divides it by the overdue unit of 10,000 cents taking the floor, multiplies by 10 points per unit, and caps the result at 60 points (a negative balance contributes zero, since the balance is first floored at zero before division). The penalty component counts the owner's finalized invoices that are not fully paid (those whose `paid_amount_cents` is less than their `amount_due_cents`), multiplies that count by 20 points per unpaid invoice, and caps the result at 40 points. The total score is the sum of the two components, capped at 100.

The score exists in two variants. The **committed** variant is written to the owner's `standing_score` after every finalize, void, or pay event: it uses the committed `account_balance_cents` as the balance and counts only `FINALIZED` not-fully-paid invoices. On each such recompute the owner's `status` is derived: `DELINQUENT` when `standing_score` is at or above the suspension threshold of 80 points, otherwise `ACTIVE`. The **provisional** variant is a read-only projection written to `provisional_standing_score` on each owner read and never gates anything: it adds to the balance the projected amount due of every `OPEN` invoice, and it also counts those `OPEN` invoices toward the unpaid-invoice penalty. The committed `standing_score` is the figure that gates reinstatement (Section 3.5) and the delinquency status; the provisional figure is purely informational.

### 3.10. Pasture Capacity and the Logical Clock

**Pasture concurrent capacity.** Turnouts on a pasture are capped by concurrent occupancy rather than by any pairwise rule, which makes pasture capacity behave differently from the service-visit overlap check. For a proposed turnout on a pasture over its half-open window, consider every instant within that window: at each instant, count the booked turnouts on that pasture whose own half-open window contains the instant, including the proposed one. The booking is rejected with `ERR_PASTURE_FULL` if, at any instant in the proposed window, that concurrent count would exceed the pasture's `capacity`. Reaching exactly capacity is allowed; only exceeding it is rejected. Because the windows are half-open, two turnouts that merely touch — one ending exactly when the next begins — do not overlap and do not count against each other at that shared instant.

**The clock.** The clock-setting capability is an administrative, test-driving facility restricted to a `BarnManager`: it accepts a `to_iso8601` value and records it as the current logical UTC time. It performs no other work — in particular it does not itself sweep waivers into expiry; that sweep happens lazily when the owner's waiver list is read, as described in Section 3.4.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`. Operations that modify an existing resource — every transition, the deposit adjustment, the waiver signing, and the clock setting — return `200 OK`. All list and single-resource reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/owners` | Create an owner account | BarnManager |
| GET | `/owners/{id}` | Get an owner; recomputes the provisional standing score | BarnManager, Owner |
| POST | `/owners/{id}/deposit` | Adjust the held security deposit | BarnManager |
| POST | `/owners/{id}/waivers` | Create a pending waiver; supersedes any signed waiver | BarnManager, Owner |
| GET | `/owners/{id}/waivers` | List the owner's waivers (lazily fires expiry) | BarnManager, Owner |
| POST | `/owners/{id}/waivers/{id}/sign` | Sign or renew the waiver | Owner |
| POST | `/stalls` | Create a stall or pasture | BarnManager |
| GET | `/stalls/{id}` | Get a stall or pasture | BarnManager, Owner |
| GET | `/stalls/{id}/boarding-agreements` | List agreements assigned to this stall | BarnManager, Owner |
| GET | `/stalls/{id}/turnouts` | List turnouts booked on this pasture | BarnManager, Owner |
| POST | `/horses` | Register a horse for an owner | BarnManager, Owner |
| GET | `/owners/{id}/horses` | List an owner's horses | BarnManager, Owner |
| GET | `/horses/{id}` | Get a horse | BarnManager, Owner |
| GET | `/horses/{id}/boarding-agreements` | List a horse's boarding agreements | BarnManager, Owner |
| GET | `/horses/{id}/lessons` | List a horse's lessons | BarnManager, Owner, Instructor |
| GET | `/horses/{id}/service-visits` | List a horse's service visits | BarnManager, Owner, ServiceProvider |
| GET | `/horses/{id}/show-entries` | List a horse's show entries | BarnManager, Owner |
| GET | `/horses/{id}/turnouts` | List a horse's turnout assignments | BarnManager, Owner |
| POST | `/boarding-agreements` | Create a draft boarding agreement | BarnManager |
| POST | `/boarding-agreements/{id}/transition` | Activate, suspend, reinstate, or end an agreement | BarnManager |
| POST | `/lessons` | Schedule a lesson | BarnManager, Owner |
| POST | `/lessons/{id}/transition` | Resolve a lesson: complete, no-show, or cancel | BarnManager, Owner, Instructor |
| POST | `/service-visits` | Request a farrier/vet/dentist visit | BarnManager, Owner |
| POST | `/service-visits/{id}/transition` | Schedule, complete, or cancel a visit | BarnManager, Owner, ServiceProvider |
| POST | `/show-entries` | Submit a show/event entry | BarnManager, Owner |
| POST | `/show-entries/{id}/transition` | Confirm, withdraw, or scratch an entry | BarnManager, Owner |
| POST | `/turnout-assignments` | Book a pasture turnout window | BarnManager, Owner |
| POST | `/turnout-assignments/{id}/transition` | Cancel a booked turnout | BarnManager, Owner |
| POST | `/invoices` | Open a draft invoice for a billing period | BarnManager |
| GET | `/owners/{id}/invoices` | List the owner's invoices | BarnManager, Owner |
| POST | `/invoices/{id}/transition` | Finalize, void, or pay an invoice | BarnManager |
| POST | `/_clock/set_current_utc` | Set the system clock | BarnManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_OWNER_NOT_FOUND` | 404 |
| `ERR_WAIVER_NOT_FOUND` | 404 |
| `ERR_STALL_NOT_FOUND` | 404 |
| `ERR_HORSE_NOT_FOUND` | 404 |
| `ERR_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_LESSON_NOT_FOUND` | 404 |
| `ERR_VISIT_NOT_FOUND` | 404 |
| `ERR_ENTRY_NOT_FOUND` | 404 |
| `ERR_TURNOUT_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_WAIVER_NOT_SIGNABLE` | 409 |
| `ERR_WAIVER_NOT_ACTIVE` | 409 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_BOARDING_NOT_ACTIVE` | 409 |
| `ERR_INVOICE_NOT_OPEN` | 409 |
| `ERR_INVOICE_NOT_FINALIZED` | 409 |
| `ERR_CANCEL_TOO_LATE` | 409 |
| `ERR_VISIT_OVERLAP` | 409 |
| `ERR_PASTURE_FULL` | 409 |
| `ERR_STALL_FULL` | 409 |
| `ERR_TURNOUT_IN_PAST` | 409 |
| `ERR_OWNER_DELINQUENT` | 409 |
| `ERR_INVOICE_HAS_PAYMENTS` | 409 |
| `ERR_NO_BILLABLE_LINES` | 409 |
| `ERR_OVERPAYMENT` | 422 |
| `ERR_INSUFFICIENT_DEPOSIT` | 422 |
| `ERR_STALE_OWNER_VERSION` | 412 |
