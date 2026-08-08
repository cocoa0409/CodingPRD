# Furnished Midterm Housing API — Product Requirements Document

## 1. Introduction

Furnished mid-term rentals sit awkwardly between the nightly vacation-rental world and the twelve-month lease. A travelling nurse on a thirteen-week assignment, a family relocating across the country, or a consultant on a temporary posting all need a fully furnished home for somewhere between one and three months — with utilities, cleaning, and a predictable deposit already settled. This API is the platform that connects the hosts who own such units with the tenants who need them, and it governs every financial and compliance obligation that arises along the way: identity verification, certificates of insurance, security deposits, damage adjudication, occupancy-tax treatment for stays that qualify for the mid-term exemption, and the eventual payout to the host.

The system is deliberately opinionated about money and about sequencing. Rent is prorated one way while a booking is still in flight and re-prorated on a strict calendar basis once the stay is over; platform fees follow a tiered schedule that rewards longer stays; deposits are conserved to the cent across held, refunded, and forfeited buckets; and host payouts follow a maker-checker discipline in which the operator who schedules a disbursement can never be the one who releases it. Because bookings, extensions, deposits, and damage claims are all mutated by more than one party, the platform relies on optimistic concurrency guards and on immediate, cascading recomputation so that a host's projected earnings and ledger balance always reflect the true state of the world. This document specifies the complete contract that an implementation must honour.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint. Domain workflows and the rules that live inside them are described in Section 3.

### 2.1. User and Role-Based Access Control

Every request, except the two self-registration endpoints described below, must carry two HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they act. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation — or an ownership-bound role acts on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The platform recognizes five roles: `Anonymous`, `Host`, `Tenant`, `ComplianceReviewer`, and `PlatformAdmin`.

- `Anonymous` is the unauthenticated self-registration surface. Only host registration and tenant registration accept anonymous callers, and those two endpoints require no auth headers at all. `X-User-ID` for an anonymous caller is an opaque value not tied to any persisted entity and is never compared against a resource.
- When `X-User-Role` is `Host`, `X-User-ID` is the `id` of the acting `Host`; ownership checks on any resource that references a host — a unit, a booking on one of that host's units, a damage claim the host filed, a turnover on the host's unit — compare the relevant foreign key back to `X-User-ID`.
- When `X-User-Role` is `Tenant`, `X-User-ID` is the `id` of the acting `Tenant`; ownership checks on any resource that references a tenant — a booking, a verification, an extension on the tenant's booking, or a damage-claim dispute on the tenant's deposit — compare the relevant foreign key back to `X-User-ID`.
- When `X-User-Role` is `ComplianceReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where a transition writes an actor reference, but it is not compared against any entity's `id`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. The server records it as `scheduled_by_user_id` on a `Payout` when that operator schedules a disbursement, but it is otherwise not compared against any entity's `id`.

Each state-changing endpoint that drives a resource through its lifecycle accepts a `to_status` field in its request body naming the target state; the set of transitions each role may request is enumerated in Section 3 and constrained by the state machines described there.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of records returned; it defaults to 10 when omitted, and must fall between a minimum of 1 and a maximum of 100; a supplied `limit` below 1 is clamped up to 1 and one above 100 is clamped down to 100 rather than rejected. The `offset` parameter is the number of records to skip and defaults to 0; a negative `offset` is clamped to 0, and an `offset` at or beyond `total_count` simply yields an empty `data` array. A non-integer `limit` or `offset` is rejected with `ERR_VALIDATION`. Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every entity in this system is a first-class, top-level resource that carries a standard set of server-managed fields:

- `id` — a server-minted UUID with no type prefix. Clients never supply it.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at the moment of creation.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that begins at 1 on creation and increments by one on every mutation. It is the value used for optimistic concurrency control.

All entities described in this document — hosts, tenants, verifications, units, bookings, extensions, deposits, damage claims, COI policies, turnovers, payouts, and tax assessments — carry the full quartet above. Foreign keys between resources are expressed as plain string identifiers (for example a booking references its unit and its tenant), never as embedded objects.

### 2.5. Monetary Values, Terms, and Precision

All monetary amounts are integer counts of cents; there are no fractional cents and no floating-point currency fields. Wherever a rule multiplies a cent amount by a rate or a day fraction, the result is rounded to a whole number of cents using the round-half-up convention (a value whose fractional part is exactly one half rounds away from zero, upward). Every calculation in Section 3 that produces `rent_cents`, `platform_fee_cents`, `occupancy_tax_cents`, or any other derived cent amount applies this same round-half-up-to-whole-cents rule unless the rule explicitly composes several already-rounded parts.

Durations are expressed in whole days. A booking's occupancy window is half-open: it includes the move-in date and excludes the move-out date, so a stay from 2026-06-01 to 2026-07-01 spans exactly 30 days.

### 2.6. Optimistic Concurrency Control

Two creation endpoints in this system act against a parent resource whose version can move underneath the client, and both are guarded by an explicit optimistic-concurrency check that the caller cannot omit.

- Requesting an extension against a booking requires the caller to submit `expected_booking_version`, carrying the `version` of the target `Booking` as the client last observed it. The server compares that value against the booking's current `version`; if a prior write — an earlier extension request, which legitimately supersedes the client's view, or a cascade that advanced the booking — has moved the version forward, the values no longer match and the create is rejected with `ERR_STALE_BOOKING_VERSION` (HTTP 412). When the check passes, the newly created extension itself advances the booking's `version` by one, so a second extension request carrying the same observed version is stale.
- Filing a damage claim against a deposit requires the caller to submit `expected_deposit_version`, carrying the `version` of the target `Deposit` as the client last observed it. The server compares it against the deposit's current `version`; if another claim already filed against the same deposit (which the platform permits to coexist) has advanced the deposit's version, the values differ and the create is rejected with `ERR_STALE_DEPOSIT_VERSION` (HTTP 412). A successful filing advances the deposit's `version` by one.

No other endpoint accepts a version field; endpoints that are not one of these two creations perform no optimistic-concurrency check.

### 2.7. Cascading Consistency and Immediate Recomputation

The platform maintains immediate consistency: whenever an operation changes a value that another resource is derived from, every dependent resource is recomputed within the same request, and each mutated resource has its `updated_at` refreshed and its `version` incremented. Several operations therefore ripple across two or three resources at once. Confirming a booking spawns a deposit, a provisional payout, and a tax assessment and refreshes the host's projected earnings. Completing a booking re-prorates its rent, re-derives the associated payout, and schedules a turnover. Approving an extension rewrites the booking's dates and rent and then re-derives the payout and the tax assessment. Approving a damage claim moves money from the deposit's held bucket to its forfeited bucket, credits that forfeiture onto the payout, and then re-derives the host's projected earnings. Each of these cascades is specified in full in Section 3; the governing principle is that no derived field is ever left stale after the operation that feeds it returns.

### 2.8. Reference Resolution and Existence Ordering

Every request is validated against the existence of the resources it names before any business rule runs. Path identifiers and foreign-key identifiers carried in a request body are resolved left to right, in the order they appear, and the first one that does not correspond to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404). A request that files a claim against a deposit, for example, resolves the deposit before evaluating any concurrency or state rule; a request that books a unit for a tenant resolves the unit and then the tenant before checking availability.

### 2.9. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order, and the error reported is the one belonging to the first failing check. The order is:

1. Authentication — headers present and role recognized, else `ERR_UNAUTHENTICATED`.
2. Authorization and ownership — the role may perform the operation and, for ownership-bound roles, owns the target, else `ERR_UNAUTHORIZED`.
3. Existence — all path and foreign-key identifiers resolve, else `ERR_NOT_FOUND`.
4. Body well-formedness — required fields present, enum values legal, dates parseable, and a booking's `end_date` strictly later than its `start_date`, else `ERR_VALIDATION` (HTTP 422).
5. Optimistic concurrency — `expected_booking_version` or `expected_deposit_version` matches the parent's current `version`, else the corresponding stale-version error (HTTP 412).
6. State legality — the target resource is in a state from which the requested transition is defined, else `ERR_INVALID_STATE` (HTTP 409).
7. Tenant verification — a booking confirmation requires the tenant to be verified, else `ERR_TENANT_NOT_VERIFIED`.
8. Term and listing constraints — unit listing status and term-length bounds, yielding `ERR_UNIT_NOT_LISTED`, `ERR_TERM_TOO_SHORT`, or `ERR_TERM_EXCEEDS_MAX` as applicable.
9. Referential business rules — the certificate-of-insurance requirement and the booking-completion prerequisite for payouts, yielding `ERR_COI_REQUIRED` or `ERR_BOOKING_NOT_COMPLETED`.
10. Temporal availability — unit availability and tenant double-booking, yielding `ERR_UNIT_UNAVAILABLE` or `ERR_TENANT_DOUBLE_BOOKED`.
11. Fiscal constraints — host payout verification, damage-claim amount bounds, and payout segregation of duties, yielding `ERR_HOST_PAYOUT_NOT_VERIFIED`, `ERR_APPROVED_EXCEEDS_CLAIMED`, `ERR_APPROVED_EXCEEDS_HELD`, or `ERR_SEGREGATION_OF_DUTIES`.

### 2.10. The Host Ledger and Financial Conservation

Each host carries two derived money fields that summarize their standing on the platform. `projected_payout_cents` is the sum of `net_cents` across that host's payouts that are in either the `PENDING` or the `SCHEDULED` state — money the host expects but has not yet received. `payout_balance_cents` is the sum of `net_cents` across that host's payouts that are in the `PAID` state, with reversed payouts excluded — money actually disbursed. Both are pure sums over the host's payout rows, recomputed immediately whenever a payout is created, finalized, scheduled, paid, reversed, or voided. The reversal path is a compensating entry: paying a payout adds its net to the balance, and reversing that same payout subtracts the identical net, so the invariant that the balance equals the sum of paid nets is preserved through a pay-then-reverse cycle.

Deposits observe their own conservation invariant. A deposit's `amount_cents` is partitioned at all times into three buckets — `held_cents`, `refunded_cents`, and `forfeited_cents` — whose sum always equals `amount_cents`. Money only ever flows from the held bucket into the forfeited bucket (on an approved damage claim) or into the refunded bucket (at settlement); it is never created or destroyed.

### 2.11. Logical Clock

Time-dependent rules — booking activation, booking completion, pre-move-in cancellation, and certificate expiry — are evaluated against a server-controlled logical clock rather than wall-clock time. On startup the clock reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time; before any caller advances it, that startup value is the current instant. A `PlatformAdmin` may move the clock by supplying a `to_iso8601` instant to the clock-setting capability. All comparisons against a booking's `start_date` or `end_date` and a certificate's `effective_end` read this clock.

## 3. Business Logic & Workflows

### 3.1. Onboarding Hosts and Tenants; Establishing Trust

A host joins the platform through anonymous self-registration, supplying a `display_name` and a contact `email`. The new `Host` begins with `payout_account_status` of `UNVERIFIED` and `status` of `ACTIVE`, with both `projected_payout_cents` and `payout_balance_cents` at zero. A host cannot actually be paid, nor can any of its units accept a confirmed booking, until a `ComplianceReviewer` verifies the host's payout account; that review flips `payout_account_status` to `VERIFIED`. The `status` field has only the single value `ACTIVE` in this version and is set at registration.

A tenant likewise self-registers anonymously with a `full_name`, an `email`, and a `tenant_type` — one of `TRAVEL_NURSE`, `RELOCATION`, or `OTHER`. A new `Tenant` starts with `verification_status` of `UNVERIFIED` and `status` of `ACTIVE`. The `verification_status` is not set directly; it is always derived from the tenant's collection of verification documents, as described next.

A tenant establishes identity by submitting one or more `Verification` documents, each naming the `tenant_id` it belongs to, a `doc_type` of `GOVERNMENT_ID`, `EMPLOYMENT_LETTER`, or `ASSIGNMENT_CONTRACT`, and an opaque `document_ref` pointing at the uploaded file. A submitted verification enters `PENDING`. A `ComplianceReviewer` adjudicates it, moving a `PENDING` verification either to `APPROVED` or to `REJECTED` and optionally attaching a `reviewer_note`. A tenant whose document was rejected may resubmit it, which moves that verification from `REJECTED` back to `PENDING`; this resubmission is only permitted to the tenant who owns the parent `tenant_id`, and it is the one cyclic path in the verification lifecycle. `APPROVED` is the sole terminal state.

Every one of these transitions recomputes the owning tenant's `verification_status` from scratch against a fixed precedence: if at least one of the tenant's verifications is `APPROVED`, the tenant is `VERIFIED`; otherwise, if at least one is `PENDING`, the tenant is `PENDING`; otherwise, if at least one exists and is `REJECTED`, the tenant is `REJECTED`; and if the tenant has no verifications at all, the tenant remains `UNVERIFIED`. A reviewer approving one document therefore lifts the tenant to `VERIFIED` even if other documents are still pending or were rejected.

### 3.2. Listing a Unit

A host describes an available property by creating a `Unit`, which begins in `DRAFT`. Unit creation names the owning `host_id` and carries a `title`, an `address`, and a `monthly_rate_cents` that must be greater than zero. Several optional attributes shape the economics and the rules that later apply: `cleaning_fee_cents` (a one-time charge, defaulting to 0, levied only when cleaning is not bundled), `deposit_cents` (the security deposit, defaulting to 0), the booleans `utilities_included`, `cleaning_included`, and `requires_coi` (each defaulting to false), `min_term_days` (defaulting to 30), `max_term_days` (defaulting to 90), and `turnover_buffer_days` (the cleaning gap appended after each stay, defaulting to 2). When `utilities_included` is true the platform fee carries a surcharge; when `cleaning_included` is true no cleaning charge is ever added to a booking on the unit; and when `requires_coi` is true a valid certificate of insurance is a precondition for confirming and activating bookings on the unit.

A host publishes a unit by transitioning it from `DRAFT` to `LISTED`, which is permitted only when `monthly_rate_cents` is greater than zero and `min_term_days` is no greater than `max_term_days` (otherwise the transition is rejected with `ERR_VALIDATION`); this eligibility is evaluated only on the `DRAFT`-to-`LISTED` transition and is not re-checked when a unit is relisted from `SUSPENDED` to `LISTED`. A listed unit may be taken down temporarily, moving `LISTED` to `SUSPENDED`, and brought back with `SUSPENDED` to `LISTED`; the suspend action is available to the host and may also be exercised by a `PlatformAdmin`. From any of `DRAFT`, `LISTED`, or `SUSPENDED` the host may permanently retire the unit to the terminal `DELISTED` state, but only when the unit carries no booking in `REQUESTED`, `CONFIRMED`, or `ACTIVE`; an attempt to delist a unit that still has live bookings is rejected with `ERR_UNIT_HAS_ACTIVE_BOOKINGS`. Every one of these unit transitions increments the unit's `version` by one.

### 3.3. Requesting a Booking

A tenant requests a stay by creating a `Booking` for a given `unit_id` and `tenant_id`, with a `start_date` (the inclusive move-in date, `YYYY-MM-DD`) and an `end_date` (the exclusive move-out date). The booking opens in `REQUESTED` and immediately reserves the unit's calendar for its window. At creation the platform computes several derived fields. The `term_days` is the whole number of calendar days in the half-open window from `start_date` up to but not including `end_date`. The provisional `rent_cents` is computed on a thirty-day-month convention: the monthly rate multiplied by the term in days and divided by a thirty-day month, rounded half up to whole cents — that is, `monthly_rate_cents` times `term_days` divided by thirty. The `cleaning_charge_cents` is zero when the unit's `cleaning_included` is true and otherwise equals the unit's `cleaning_fee_cents`. The `gross_rent_cents` is the sum of `rent_cents` and `cleaning_charge_cents`. The booking's `rent_basis` is set to `PROVISIONAL` at this stage and remains provisional throughout `REQUESTED`, `CONFIRMED`, and `ACTIVE`.

Two eligibility rules guard creation. The requested `term_days` must fall within the unit's configured bounds: a term shorter than `min_term_days` is rejected with `ERR_TERM_TOO_SHORT`, and a term longer than `max_term_days` is rejected with `ERR_TERM_EXCEEDS_MAX`. The unit's calendar must be free: the requested window, extended by the unit's `turnover_buffer_days` cleaning buffer and evaluated on the half-open convention, must not overlap any existing booking on the same unit that is in `REQUESTED`, `CONFIRMED`, or `ACTIVE`, else the request is rejected with `ERR_UNIT_UNAVAILABLE`. The tenant must also be free: if the requested window, evaluated as a closed interval, intersects another booking of the same tenant that is `CONFIRMED` or `ACTIVE`, the request is rejected with `ERR_TENANT_DOUBLE_BOOKED`. A booking request in `REQUESTED` may be withdrawn by the tenant who owns it, moving `REQUESTED` to the terminal `CANCELLED` and releasing the unit slot; the host who owns the unit may instead reject the request, moving `REQUESTED` to the terminal `DECLINED`, also releasing the slot. Neither declination nor pre-confirmation cancellation carries any financial side effect.

### 3.4. Confirming a Booking

A host accepts a requested booking by transitioning it from `REQUESTED` to `CONFIRMED`. This is the most heavily guarded transition in the system, and its preconditions are evaluated in the order the system evaluates checks generally. The booking must still be `REQUESTED` (otherwise `ERR_INVALID_STATE`). The tenant's `verification_status` must be `VERIFIED` (otherwise `ERR_TENANT_NOT_VERIFIED`). The unit's `status` must be `LISTED` (otherwise `ERR_UNIT_NOT_LISTED`). If the unit's `requires_coi` is true, there must exist a certificate of insurance for this booking that is `ACTIVE`, whose `coverage_cents` is at least the platform's minimum required coverage `COI_MIN_COVERAGE_CENTS`, and whose coverage window from `effective_start` through `effective_end` covers the booking's occupancy window — that is, `effective_start` is on or before the booking's `start_date` and `effective_end` is on or after the booking's last occupied night (the `end_date` minus one day, since occupancy is half-open); failing any of these the confirmation is rejected with `ERR_COI_REQUIRED`. Finally, the host's `payout_account_status` must be `VERIFIED` (otherwise `ERR_HOST_PAYOUT_NOT_VERIFIED`).

Confirmation sets in motion a rich cascade of created resources. A `Deposit` is created for the booking with `amount_cents` snapshotted from the unit's `deposit_cents`, all of it placed in `held_cents`, with `refunded_cents` and `forfeited_cents` at zero and `status` of `HELD`. A `Payout` is created on the `PROVISIONAL` basis in state `PENDING`, its `gross_rent_cents` snapshotted from the booking's gross rent, its `platform_fee_cents` computed by the fee rule below, its `deposit_adjustment_cents` at zero, and its `net_cents` equal to gross rent minus platform fee. The host's `projected_payout_cents` is recomputed to include this new payout's net. A `TaxAssessment` is created recording the booking's `assessed_term_days` and deriving `taxable`, `occupancy_tax_cents`, and `exempt_reason` per the occupancy-tax rule below.

The platform fee is tiered by the length of the stay and by whether utilities are bundled. The base rate is eight percent when `term_days` is 90 or more, ten percent when `term_days` is at least 60 but fewer than 90, and twelve percent for any shorter qualifying term (30 through 59 days). If the unit's `utilities_included` is true, a surcharge of two percentage points is added to the base rate; otherwise no surcharge applies. The effective rate is the base plus any surcharge, and the raw fee is `gross_rent_cents` multiplied by that effective rate, rounded half up to whole cents. The stored `platform_fee_cents` is then clamped to lie between a floor of 5,000 cents ($50.00) and a ceiling of 200,000 cents ($2,000.00): a raw fee below the floor is raised to the floor, and one above the ceiling is lowered to the ceiling.

The occupancy tax reflects the mid-term exemption that motivates this whole platform. If the `assessed_term_days` is 30 or more, the stay qualifies as mid-term: `taxable` is false, `occupancy_tax_cents` is zero, and `exempt_reason` is `MID_TERM_30_DAY`. Otherwise the stay is taxable: `taxable` is true, `occupancy_tax_cents` is `gross_rent_cents` multiplied by the fourteen-percent occupancy-tax rate and rounded half up to whole cents, and `exempt_reason` is `NONE`.

### 3.5. Certificates of Insurance

When a unit requires proof of insurance, a certificate is submitted by either the host or the tenant as a `CoiPolicy` naming the `booking_id` it covers, its `coverage_cents`, and its coverage window `effective_start` through `effective_end` (both inclusive dates). A submitted policy begins in `PENDING`. A `ComplianceReviewer` activates it, moving `PENDING` to `ACTIVE`, but only when its `coverage_cents` is at least the platform's minimum required coverage `COI_MIN_COVERAGE_CENTS`, which is `5000000` cents ($50,000) (otherwise `ERR_COI_INSUFFICIENT_COVERAGE`) and its `effective_start` is on or before its `effective_end` (otherwise `ERR_DATE_RANGE_INVALID`). A reviewer may revoke an active policy, moving `ACTIVE` to the terminal `REVOKED`; if the covered booking is still `CONFIRMED`, the unit requires a certificate, and no other `ACTIVE` policy covers the booking, the booking can no longer be activated. A `PlatformAdmin` may expire an active policy, moving `ACTIVE` to the terminal `EXPIRED`, but only once the logical clock has reached or passed the policy's `effective_end`; an attempt before the clock reaches `effective_end` is rejected with `ERR_INVALID_STATE`.

### 3.6. Activation, Cancellation, and Completion

Once the move-in date arrives, a `PlatformAdmin` activates a confirmed booking, moving `CONFIRMED` to `ACTIVE`. This requires the booking to be `CONFIRMED` and the logical clock to have reached or passed the `start_date` (an activation attempted before `start_date` is rejected with `ERR_INVALID_STATE`); if the unit requires a certificate of insurance, a covering policy must still be `ACTIVE`, else `ERR_COI_REQUIRED`. Before the move-in date, a tenant may still call off a confirmed booking: the tenant who owns it moves `CONFIRMED` to the terminal `CANCELLED`, permitted only while the logical clock is still before `start_date` (a cancellation attempted on or after `start_date` is rejected with `ERR_INVALID_STATE`). That cancellation refunds the deposit in full — its entire `held_cents` moves into `refunded_cents`, `held_cents` becomes zero, and the deposit's `status` becomes `REFUNDED` — voids the associated payout to `VOIDED`, and recomputes the host's `projected_payout_cents` to drop the voided net.

When the stay is over, a `PlatformAdmin` completes an active booking, moving `ACTIVE` to the terminal `COMPLETED`, permitted only once the logical clock has reached or passed the `end_date` (a completion attempted before `end_date` is rejected with `ERR_INVALID_STATE`). Completion is where rent is finalized. The booking's `rent_cents` and `gross_rent_cents` are recomputed on the `FINAL` basis and `rent_basis` becomes `FINAL`. The final rent abandons the thirty-day convention in favour of true calendar proration: for each calendar month that the occupancy window touches, the platform takes the number of days of that month that fall inside the half-open window, divides by the actual number of days in that month (28, 29, 30, or 31), multiplies by `monthly_rate_cents`, and rounds that month's contribution half up to whole cents; the finalized rent is the sum of those per-month rounded contributions. The rounding is pinned to round-each-month-then-sum — the platform never sums the raw monthly amounts and rounds once at the end, because the two approaches can differ by a cent. The recomputed gross then cascades into the payout: the payout's `gross_rent_cents` is reset to the booking's final gross, its `platform_fee_cents` is recomputed against the final gross, its `net_cents` is recomputed, its `payout_basis` becomes `FINAL`, and the host's `projected_payout_cents` is recomputed. Completion also creates a `Turnover` for the unit, recording the triggering `booking_id`, a `scheduled_start` equal to the booking's `end_date`, and a `scheduled_end` equal to that date plus the unit's `turnover_buffer_days`, in state `SCHEDULED`.

A turnover represents the cleaning-and-reset window between tenancies. The host starts it by moving `SCHEDULED` to `IN_PROGRESS`, which is allowed only once the triggering booking is `COMPLETED` (otherwise `ERR_INVALID_STATE`), and finishes it by moving `IN_PROGRESS` to the terminal `COMPLETED`, which frees the unit calendar after the `scheduled_end`. Alternatively the host may skip an unstarted turnover, moving `SCHEDULED` to the terminal `SKIPPED`.

### 3.7. Extending a Stay

A tenant who wishes to stay longer requests an `Extension` against their booking, supplying the `booking_id`, the `expected_booking_version` that guards the request as described in the concurrency section, and a proposed `new_end_date` that must be later than the booking's current `end_date`. At creation the platform validates only that `new_end_date` is a parseable date; the later-than-`end_date` ordering is not enforced at request time (so `added_days` may be recorded as zero or negative) and is instead checked when the host approves, per below. The extension records `added_days`, the whole-day difference between `new_end_date` and the booking's current `end_date`, and opens in `REQUESTED`. Creating the extension advances the parent booking's `version` by one.

The host who owns the unit decides the request. Approving it moves `REQUESTED` to the terminal `APPROVED`, subject to several checks: the extension must be `REQUESTED`; the booking must be in `CONFIRMED` or `ACTIVE` (otherwise `ERR_INVALID_STATE`); the `new_end_date` must be strictly later than the booking's current `end_date` (otherwise `ERR_EXTENSION_NOT_LATER`); the resulting full term from `start_date` to `new_end_date` must not exceed the unit's `max_term_days` (otherwise `ERR_TERM_EXCEEDS_MAX`); and the extended occupancy window, once again widened by the unit's turnover buffer, must not overlap any other booking on the unit in `REQUESTED`, `CONFIRMED`, or `ACTIVE` (otherwise `ERR_UNIT_UNAVAILABLE`). Approval then cascades: the booking's `end_date` is set to `new_end_date`, its `term_days` is recomputed, its `rent_cents` and `gross_rent_cents` are recomputed on the still-`PROVISIONAL` basis, and its `version` increments by one; the related payout's `gross_rent_cents` is reset to the booking's new gross while its `platform_fee_cents` is left unchanged — the platform fee is deliberately not recomputed on extension approval, unlike the booking-completion cascade of §3.6, so the original fee is retained even though the term and gross have changed — its `net_cents` is recomputed (as the retained fee against the new gross plus any deposit adjustment), and the host's `projected_payout_cents` is recomputed; and the booking's tax assessment is reassessed against the new `assessed_term_days`, re-deriving `taxable`, `occupancy_tax_cents`, and `exempt_reason`. The host may instead decline the request, moving `REQUESTED` to the terminal `DECLINED`, and the tenant who owns the parent booking may withdraw their own request, moving `REQUESTED` to the terminal `WITHDRAWN`; neither carries any side effect.

### 3.8. Deposits, Damage Claims, and Settlement

A deposit is never created or mutated directly by a client; it is spawned at booking confirmation and driven only by damage claims and by settlement. A host who observes damage files a `DamageClaim` against the booking's `Deposit`, supplying the `deposit_id`, the `expected_deposit_version` that guards the filing, a `claimed_cents` amount, and a `description`. The claim opens in `FILED`, and the filing advances the deposit's `version` by one. Multiple claims may coexist against one deposit.

A filed claim can be negotiated. The tenant who owns the deposit's booking may dispute it, moving `FILED` to `DISPUTED` and recording their `tenant_response`. The host may answer a dispute by moving `DISPUTED` back to `FILED`, revising `claimed_cents` to a new value supplied in the request; this `FILED`-to-`DISPUTED`-and-back loop is the cyclic negotiation path. A host may also withdraw a still-`FILED` claim, moving it to the terminal `WITHDRAWN`.

A `ComplianceReviewer` adjudicates a claim from either `FILED` or `DISPUTED`. Rejection moves the claim to the terminal `REJECTED` with no financial effect. Approval — supplying the `approved_cents` amount adjudicated payable to the host — moves the claim to the terminal `APPROVED` and is subject to three checks: the deposit must still be `HELD`, else `ERR_CLAIM_WINDOW_CLOSED`; the `approved_cents` must not exceed the claim's `claimed_cents`, else `ERR_APPROVED_EXCEEDS_CLAIMED`; and the `approved_cents` must not exceed the deposit's current `held_cents`, else `ERR_APPROVED_EXCEEDS_HELD`. An approval — whether it originates from `FILED` or from `DISPUTED`, which behave identically — triggers a depth-three cascade. First, the deposit's `forfeited_cents` increases by `approved_cents` and its `held_cents` decreases by the same amount; if the held bucket has been drawn down to zero the deposit's `status` becomes `FORFEITED`, otherwise it remains `HELD`. Second, the related payout's `deposit_adjustment_cents` is set to the deposit's `forfeited_cents` and its `net_cents` is recomputed. Third, the host's `projected_payout_cents` is recomputed from the updated payout net.

Settlement closes out a deposit and returns whatever remains to the tenant. A `ComplianceReviewer` settles a `HELD` deposit — a deposit not currently in `HELD` is rejected with `ERR_INVALID_STATE` — which is permitted only once the booking is `COMPLETED` and no damage claim on the deposit is still open in `FILED` or `DISPUTED`; a premature settlement, or one attempted while an open claim exists, is rejected with `ERR_DEPOSIT_NOT_SETTLEABLE`. The outcome depends on how much was forfeited. If nothing was forfeited (`forfeited_cents` is zero), the entire held amount moves to `refunded_cents`, `held_cents` becomes zero, and the deposit's `status` becomes `REFUNDED`. If a partial amount was forfeited (`forfeited_cents` is greater than zero but less than `amount_cents`), the remaining held amount moves to `refunded_cents`, `held_cents` becomes zero, and the `status` becomes `PARTIALLY_REFUNDED`. If the whole deposit was forfeited (`forfeited_cents` equals `amount_cents`, so the held bucket is already zero), `refunded_cents` stays zero and the `status` becomes `FORFEITED`. In every case the conservation invariant holds: the held, refunded, and forfeited buckets sum to `amount_cents`.

### 3.9. Paying the Host

A payout is created provisionally at booking confirmation and finalized by the booking-completion cascade, so by the time it is disbursed its `gross_rent_cents`, `platform_fee_cents`, `deposit_adjustment_cents`, and `net_cents` already reflect the final booking rent and any forfeiture; the `net_cents` in either basis is always the gross rent minus the platform fee plus the deposit adjustment. Disbursement follows a maker-checker discipline exercised entirely by `PlatformAdmin` operators. First an operator schedules the payout, moving `PENDING` to `SCHEDULED`; this is permitted only when the booking is `COMPLETED` (otherwise `ERR_BOOKING_NOT_COMPLETED`) and the host's `payout_account_status` is `VERIFIED` (otherwise `ERR_HOST_PAYOUT_NOT_VERIFIED`), and it records the scheduling operator's `X-User-ID` into `scheduled_by_user_id`. Then a second operator releases it, moving `SCHEDULED` to `PAID`; the acting `X-User-ID` must differ from the `scheduled_by_user_id` that was recorded at scheduling, else the release is rejected with `ERR_SEGREGATION_OF_DUTIES`. Paying adds the payout's `net_cents` to the host's `payout_balance_cents` and subtracts the same net from `projected_payout_cents`.

Two exit paths remain. A paid payout may be reversed, moving `PAID` to the terminal `REVERSED`, which subtracts its `net_cents` back out of the host's `payout_balance_cents` as a compensating entry. A still-`PENDING` payout may be voided, moving `PENDING` to the terminal `VOIDED`, which recomputes the host's `projected_payout_cents` to remove it. The `payout_basis` field carries `PROVISIONAL` while the payout is pending and `FINAL` after the booking-completion cascade has run.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that read a resource or drive an existing resource through a state transition (including settlement and payout actions) return `200 OK`. Consult the Section 3 narratives for the request payloads, derived fields, and side effects of each operation; the table below lists only the transport contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/hosts` | Register a host | Anonymous |
| GET | `/hosts/{id}` | Get a host | Host, Tenant, ComplianceReviewer, PlatformAdmin |
| POST | `/hosts/{id}/verify-payout` | Mark host payout account verified | ComplianceReviewer |
| POST | `/tenants` | Register a tenant | Anonymous |
| GET | `/tenants/{id}` | Get a tenant | Host, Tenant, ComplianceReviewer, PlatformAdmin |
| POST | `/verifications` | Submit a verification document | Tenant |
| GET | `/verifications/{id}` | Get a verification | Host, Tenant, ComplianceReviewer, PlatformAdmin |
| GET | `/verifications` | List verifications (filter by tenant, status) | Host, Tenant, ComplianceReviewer, PlatformAdmin |
| POST | `/verifications/{id}/transitions` | Approve/reject/resubmit a verification | ComplianceReviewer, Tenant |
| POST | `/units` | Create a unit | Host |
| GET | `/units/{id}` | Get a unit | Host, Tenant, ComplianceReviewer, PlatformAdmin |
| GET | `/units` | List units (filter by host, status) | Host, Tenant, ComplianceReviewer, PlatformAdmin |
| POST | `/units/{id}/transitions` | List/suspend/relist/delist a unit | Host, PlatformAdmin |
| POST | `/bookings` | Request a booking | Tenant |
| GET | `/bookings/{id}` | Get a booking | Host, Tenant, ComplianceReviewer, PlatformAdmin |
| GET | `/bookings` | List bookings (filter by unit, tenant, status) | Host, Tenant, ComplianceReviewer, PlatformAdmin |
| POST | `/bookings/{id}/transitions` | Confirm/decline/cancel/activate/complete a booking | Host, Tenant, PlatformAdmin |
| POST | `/extensions` | Request a booking extension | Tenant |
| GET | `/extensions/{id}` | Get an extension | Host, Tenant, ComplianceReviewer, PlatformAdmin |
| GET | `/extensions` | List extensions (filter by booking, status) | Host, Tenant, ComplianceReviewer, PlatformAdmin |
| POST | `/extensions/{id}/transitions` | Approve/decline/withdraw an extension | Host, Tenant |
| GET | `/deposits/{id}` | Get a deposit | Host, Tenant, ComplianceReviewer, PlatformAdmin |
| GET | `/deposits` | List deposits (filter by booking, status) | Host, Tenant, ComplianceReviewer, PlatformAdmin |
| POST | `/deposits/{id}/settle` | Settle a deposit | ComplianceReviewer |
| POST | `/damage-claims` | File a damage claim against a deposit | Host |
| GET | `/damage-claims/{id}` | Get a damage claim | Host, Tenant, ComplianceReviewer, PlatformAdmin |
| GET | `/damage-claims` | List damage claims (filter by deposit, status) | Host, Tenant, ComplianceReviewer, PlatformAdmin |
| POST | `/damage-claims/{id}/transitions` | Dispute/revise/approve/reject/withdraw a claim | Host, Tenant, ComplianceReviewer |
| POST | `/coi-policies` | Submit a certificate of insurance | Host, Tenant |
| GET | `/coi-policies/{id}` | Get a COI policy | Host, Tenant, ComplianceReviewer, PlatformAdmin |
| GET | `/coi-policies` | List COI policies (filter by booking, status) | Host, Tenant, ComplianceReviewer, PlatformAdmin |
| POST | `/coi-policies/{id}/transitions` | Activate/revoke/expire a COI policy | ComplianceReviewer, PlatformAdmin |
| GET | `/turnovers/{id}` | Get a turnover | Host, Tenant, ComplianceReviewer, PlatformAdmin |
| GET | `/turnovers` | List turnovers (filter by unit, booking, status) | Host, Tenant, ComplianceReviewer, PlatformAdmin |
| POST | `/turnovers/{id}/transitions` | Start/complete/skip a turnover | Host |
| GET | `/payouts/{id}` | Get a payout | Host, Tenant, ComplianceReviewer, PlatformAdmin |
| GET | `/payouts` | List payouts (filter by booking, host, status) | Host, Tenant, ComplianceReviewer, PlatformAdmin |
| POST | `/payouts/{id}/transitions` | Schedule/pay/reverse/void a payout | PlatformAdmin |
| GET | `/tax-assessments/{id}` | Get a tax assessment | Host, Tenant, ComplianceReviewer, PlatformAdmin |
| GET | `/tax-assessments` | List tax assessments (filter by booking) | Host, Tenant, ComplianceReviewer, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_STALE_BOOKING_VERSION` | 412 |
| `ERR_STALE_DEPOSIT_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TENANT_NOT_VERIFIED` | 409 |
| `ERR_UNIT_NOT_LISTED` | 409 |
| `ERR_TERM_TOO_SHORT` | 422 |
| `ERR_TERM_EXCEEDS_MAX` | 422 |
| `ERR_COI_REQUIRED` | 409 |
| `ERR_COI_INSUFFICIENT_COVERAGE` | 409 |
| `ERR_BOOKING_NOT_COMPLETED` | 409 |
| `ERR_UNIT_UNAVAILABLE` | 409 |
| `ERR_TENANT_DOUBLE_BOOKED` | 409 |
| `ERR_HOST_PAYOUT_NOT_VERIFIED` | 409 |
| `ERR_APPROVED_EXCEEDS_CLAIMED` | 422 |
| `ERR_APPROVED_EXCEEDS_HELD` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_DEPOSIT_NOT_SETTLEABLE` | 409 |
| `ERR_CLAIM_WINDOW_CLOSED` | 409 |
| `ERR_EXTENSION_NOT_LATER` | 422 |
| `ERR_DATE_RANGE_INVALID` | 422 |
| `ERR_UNIT_HAS_ACTIVE_BOOKINGS` | 409 |
