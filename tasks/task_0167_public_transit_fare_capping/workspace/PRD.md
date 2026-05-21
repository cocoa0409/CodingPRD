# Transit Fare Capping API — Product Requirements Document

## 1. Introduction

Modern urban transit agencies promise riders that no matter how often they tap, their wallet will never be charged more than a published daily or weekly ceiling, and that low-income residents, seniors, students, and riders with disabilities all enjoy the discounts to which their certification entitles them. Delivering on that promise is genuinely difficult: fares must be charged at the gate before the agency knows what the rest of the day will look like, transfers within a short window must travel free, employer-sponsored commuter benefit accounts must be drawn first, and the entire ledger must be reconciled in chronological order once each window closes — without ever stranding a rider, double-charging a card, or letting a refund drift cents away from the original debit.

This document specifies the Transit Fare Capping API, the system of record for riders, fare cards, employer-sponsored Transit FSAs, reduced-fare certificates, low-income verifications, mobile wallet tokens, taps, transfers, cap windows, and dispute resolution. The API supports a forward-looking provisional charge at tap-in and a chronological re-settlement after each cap window closes, with compensating refunds and back-charges that route through the original FSA-then-wallet allocation. It is designed so that any honest sequence of taps, contributions, suspensions, approvals, and resolutions converges to the same end-of-window balances regardless of the order in which racing operations arrive.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. Requests missing either header are rejected with `ERR_AUTH_MISSING`. The system recognises exactly four roles — `Rider`, `AgencyOfficer`, `EmployerAdmin`, and `Auditor` — and any other value in `X-User-Role` is rejected with `ERR_AUTH_INVALID_ROLE`. Once the role is recognised, the system checks that the role is permitted for the requested endpoint; a mismatch yields `ERR_FORBIDDEN`.

When `X-User-Role` is `Rider`, `X-User-ID` is the `id` of the acting `Rider`; any ownership check on a card, trip, dispute, or mobile token compares the resource's `rider_id` (directly or via the card's `rider_id`) to `X-User-ID`. When `X-User-Role` is `EmployerAdmin`, `X-User-ID` is the `id` of the acting `Employer`; ownership checks on a `CommuterBenefitAccount` or `FSAContribution` compare the account's `employer_id` to `X-User-ID`. When `X-User-Role` is `AgencyOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`. When `X-User-Role` is `Auditor`, `X-User-ID` is likewise an opaque operator identifier; auditors may read every resource without rider or employer restriction and may not perform any mutation.

A `Rider` may tap in and out on a card whose `rider_id` matches `X-User-ID`, file a dispute on a trip belonging to their own card, close their own card, top up their own card, revoke a mobile token they registered, and read only their own riders, cards, trips, and cap periods. A `Rider` may also issue a card to themselves provided the requested `discount_class` is `STANDARD` or `LOW_INCOME`; only an `AgencyOfficer` may issue a card with `discount_class` `REDUCED_FARE` or issue a card on behalf of another rider. An `AgencyOfficer` creates riders and employers, suspends or reactivates cards and employers, creates, approves, and revokes reduced-fare certificates, approves low-income verifications, claims and resolves disputes, and drives the test-only logical clock and the three system sweeps. An `EmployerAdmin` opens commuter benefit accounts and posts or reverses contributions, all scoped to their own employer. An `Auditor` performs read-only inspection across all resources.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0; it must be zero or greater. A `limit` outside the range or a negative `offset` is rejected with `ERR_INVALID_PAGINATION`.

Unless otherwise specified, all list endpoints return resources sorted by their `created_at` timestamp in ascending order. List responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All primary, top-level resources — including `Rider`, `Employer`, `FareCard`, `ReducedFareCertificate`, `LowIncomeVerification`, `MobilePaymentToken`, `Trip`, `FareCapPeriod`, `CommuterBenefitAccount`, and `DisputeCase` — carry a standard set of system-managed fields:

- `id` (string): a server-minted UUID, without a type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`), recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification to the resource.
- `version` (integer): a system-managed counter that starts at the resource's initial version and increments by one with every modification. This field can be used for optimistic concurrency control.

Two entities are append-only ledger lines and therefore carry only `id` and `created_at`, with neither `updated_at` nor `version`: `TransferLink` (linking the `first_trip_id` and `second_trip_id` of a paired transfer with an immutable `window_minutes`) and `FSAContribution` (which records `account_id`, `amount_cents`, `contribution_month`, and `status`, and which is reversed by appending a new contribution rather than by mutating the original).

### 2.5. Optimistic Concurrency Control

Any endpoint that targets an existing resource and modifies it accepts an optional `version` integer in the request body. When provided, the server compares it against the current `version` of the resource: a mismatch causes the request to be rejected with `ERR_VERSION_CONFLICT`, and if it matches, the mutation proceeds and `version` increments by one. When `version` is omitted, the server performs the mutation without an OCC check. Every mutation refreshes `updated_at` and increments `version` on the directly modified resource as well as on any other resource the operation cascades into per §2.6.

### 2.6. Cascade Consistency and Updated-Timestamps

When a single operation mutates more than one resource, every affected resource has its `updated_at` refreshed and its `version` incremented. Approving a `LowIncomeVerification` to `ACTIVE` writes `Rider.low_income_verified` to true, sets `approved_at` to the server clock, and bumps both the verification and the rider. Revoking a `ReducedFareCertificate` from `ACTIVE` to `REVOKED` scans every `FareCard` owned by that rider whose `discount_class` is `REDUCED_FARE`; for each card with no other `ACTIVE` certificate of any `program_type` covering the current server time, the card's `discount_class` is downgraded to `STANDARD` and its `version` and `updated_at` are bumped, while any in-flight trip already in `TAPPED_IN` state is left undisturbed and only future tap-ins charge at the standard rate. The low-income expiry sweep behaves symmetrically: when a verification crosses from `ACTIVE` to `EXPIRED`, the rider's `low_income_verified` flips back to false if no other `ACTIVE` verification remains, and every `LOW_INCOME` card the rider holds is downgraded to `STANDARD`. Filing or resolving a dispute, debiting an FSA balance during a tap, and reverting `accumulated_cents` on the relevant `FareCapPeriod` records all conform to the same rule: every entity touched by the operation is bumped, in the same transactional unit.

### 2.7. Nested Resource Path Validation

Endpoints that embed an identifier in the URL (e.g., a card, certificate, verification, token, trip, or dispute) validate path identifiers strictly left to right. The first path identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND` before any deeper identifier or any body content is even inspected. Body-level foreign keys — for example a `rider_id`, `card_id`, `account_id`, `employer_id`, or `trip_id` referenced inside a request payload — are checked next, and any that fails to resolve produces `ERR_REFERENCE_NOT_FOUND`. Both are returned with HTTP 404.

### 2.8. Monetary Precision and Cents

All monetary quantities — `wallet_balance_cents`, `balance_cents`, `amount_cents`, `monthly_contribution_cap_cents`, `provisional_fare_cents`, `settled_fare_cents`, `paid_from_fsa_cents`, `accumulated_cents`, `cap_cents`, `refund_amount_cents`, `declared_annual_income_cents`, and `verified_annual_income_cents` — are stored and exchanged as integer cents. The only step in any calculation that introduces fractional cents is the post-discount per-leg base fare in the fare formula and the proportional FSA share in the refund split; in both cases the result is rounded half-up to the nearest whole cent before being used. Running accumulators, cap remainders, and the wallet share of a refund are all integer cents throughout, with the wallet share absorbing any rounding remainder so that the sum of FSA share and wallet share equals the conserved total exactly.

### 2.9. The Fare Cap Principle

The fare cap is the system's defining commitment: a rider tapping repeatedly within a single window pays only up to the configured ceiling, never more. The system tracks two parallel cap windows for each card. A `DAILY` cap window covers one calendar day in UTC, starting inclusively at `window_start` and ending exclusively at `window_end` set to `window_start` plus twenty-four hours. A `WEEKLY` cap window covers one ISO week (Monday-start, UTC), starting inclusively at `window_start` and ending exclusively at `window_end` set to `window_start` plus seven days. At most one cap period of a given `scope` exists for a card on a given window — uniqueness is enforced on the combination of `card_id`, `scope`, and `window_start`. At creation, `cap_cents` is pinned to the configured ceiling for that scope: 600 cents for `DAILY` and 3300 cents for `WEEKLY`. `accumulated_cents` is the running sum of `provisional_fare_cents` for trips whose `tap_in_at` falls in the half-open window `[window_start, window_end)`, and it is mutated as a side effect of every trip creation and every settlement. `cap_reached_at` is null while `accumulated_cents` is below `cap_cents`; the first moment `accumulated_cents` reaches `cap_cents`, that moment is written into `cap_reached_at`.

### 2.10. The FSA-First Allocation Principle

When a rider is enrolled in an employer-sponsored Transit FSA — that is, when their `employer_id` is not null and their `CommuterBenefitAccount` is in `ACTIVE` status — the system always draws from the FSA before the wallet. At every trip charge the FSA share is taken first (up to whichever is smaller, the provisional fare or the account's `balance_cents`), and the remainder is taken from the card's `wallet_balance_cents`. Any subsequent refund mirrors this split in proportion, with the wallet share absorbing rounding drift so that the conserved quantity equals the original debit to the cent. If the rider has no `employer_id`, has no account, or the account's `status` is `FROZEN`, the FSA share is zero and the whole charge falls on `wallet_balance_cents`.

### 2.11. Validation Order

Every request is validated in a fixed priority order so that authentication and authorisation concerns surface before structural ones, structural concerns before state checks, and state checks before business referential, temporal, constraint, and fiscal checks. Concretely the order is: presence of `X-User-ID` and `X-User-Role` (rejection: `ERR_AUTH_MISSING`); recognition of the value in `X-User-Role` as one of `Rider`, `AgencyOfficer`, `EmployerAdmin`, `Auditor` (rejection: `ERR_AUTH_INVALID_ROLE`); per-endpoint role permission (rejection: `ERR_FORBIDDEN`); existence of every URL path identifier, evaluated left to right (rejection: `ERR_NOT_FOUND`); existence of every foreign-key resource named in the request body (rejection: `ERR_REFERENCE_NOT_FOUND`); state-eligibility of the target resource for the requested operation, including transitions, dispute resolutions, and approvals (rejection: `ERR_INVALID_STATE`); on a tap-in specifically, the additional state checks that the card is in `ACTIVE` status (rejection: `ERR_CARD_NOT_ACTIVE`) and that no other trip on the same card is currently in `TAPPED_IN` (rejection: `ERR_TRIP_ALREADY_OPEN`); business referential checks such as certificate windows and required certifications or verifications (rejections: `ERR_CERTIFICATE_WINDOW_OVERLAP`, `ERR_MISSING_REDUCED_FARE_CERTIFICATE`, `ERR_MISSING_LOW_INCOME_VERIFICATION`); business temporal checks such as `tap_in_at` lying within the card's validity window (rejection: `ERR_CARD_OUTSIDE_VALIDITY`) and `tap_out_at` being strictly later than `tap_in_at` (rejection: `ERR_TAP_OUT_NOT_AFTER_TAP_IN`); business constraint checks such as `(rider_id, device_fingerprint)` uniqueness on a mobile token (rejection: `ERR_DEVICE_ALREADY_BOUND`), `(card_id, idempotency_key)` deduplication on a tap-in (rejection: `ERR_DUPLICATE_TAP`), strictly positive contribution amounts (rejection: `ERR_INVALID_AMOUNT`), and pagination bounds (rejection: `ERR_INVALID_PAGINATION`); and finally business fiscal checks — the monthly FSA contribution sum staying at or below the employer's monthly cap (rejection: `ERR_FSA_MONTHLY_CAP_EXCEEDED`) and the combined wallet plus FSA balance covering the provisional fare (rejection: `ERR_INSUFFICIENT_FUNDS`).

## 3. Business Logic & Workflows

### 3.1. Riders, Employers, and the Onboarding Setup

A transit agency operator opens the system by registering riders and employers. Creating a `Rider` requires only the rider's `full_name` and `email`; the email must be unique across all riders, and a duplicate is rejected as a constraint violation. Each rider starts with `low_income_verified` set to false and `employer_id` set to null. Creating an `Employer` requires its `legal_name` and a `monthly_contribution_cap_cents` integer expressing the per-month FSA contribution ceiling per employer in cents, which must be zero or greater. A newly created employer begins in `enrollment_status` `ACTIVE`, the only state in which new FSA contributions are accepted. When an `AgencyOfficer` suspends an employer, every `CommuterBenefitAccount` carrying that `employer_id` transitions from `ACTIVE` to `FROZEN`; this freezes both new contributions and new tap-in disbursements from those accounts while still permitting refunds, and a `TERMINATED` employer blocks everything end to end.

### 3.2. Fare Cards, Discounts, and the Reduced-Fare Card Program

A fare card is issued with a `rider_id`, a `discount_class`, a `valid_from`, and a `valid_until`, where `valid_until` must be strictly greater than `valid_from`. The `discount_class` enumerates three values: `STANDARD`, which carries no discount; `REDUCED_FARE`, which charges 50% of the base fare and is reserved for riders who hold an `ACTIVE` `ReducedFareCertificate` covering the moment of card creation; and `LOW_INCOME`, which charges 60% of the base fare and is reserved for riders whose `low_income_verified` flag is true at card creation. If a card is requested with `discount_class` `REDUCED_FARE` and no `ACTIVE` `ReducedFareCertificate` on the rider covers the present moment between its `valid_from` and `valid_until`, the request is rejected with `ERR_MISSING_REDUCED_FARE_CERTIFICATE`; if a card is requested with `discount_class` `LOW_INCOME` while the rider's `low_income_verified` is still false, the request is rejected with `ERR_MISSING_LOW_INCOME_VERIFICATION`. Newly issued cards start with `status` `ACTIVE` and `wallet_balance_cents` of zero; the `mobile_token_id` is null until a mobile token is bound.

Riders top up the card by adding to `wallet_balance_cents`; the request body carries an `amount_cents` integer. A card may be suspended by an `AgencyOfficer`, transitioning `status` from `ACTIVE` to `SUSPENDED`; suspension blocks new tap-ins (any subsequent tap is rejected with `ERR_CARD_NOT_ACTIVE`), and any in-flight trip already in `TAPPED_IN` on that card will be force-closed by the incomplete-trip sweep on its next run. A suspended card may be reactivated, transitioning `status` from `SUSPENDED` back to `ACTIVE`. Closure is a rider-initiated terminal transition from `ACTIVE` to `CLOSED` and is permitted only when no trip on the card has `travel_status` `TAPPED_IN`; closing the card zeros `wallet_balance_cents` (the residual stored value is refunded to the rider out-of-band), and if the card was bound to a `MobilePaymentToken`, the token's `bound_card_id` is cleared.

A `ReducedFareCertificate` records a `rider_id`, a categorical `program_type` of `SENIOR`, `DISABILITY`, or `STUDENT`, and a validity window with `valid_from` and `valid_until`, where `valid_until` must be strictly greater than `valid_from` and where two certificates of the same `program_type` for the same rider may not have overlapping `[valid_from, valid_until]` windows. A newly created certificate starts in `status` `PENDING`. Approval by an `AgencyOfficer` is permitted only while the certificate is in `PENDING` and only while its `valid_until` lies strictly after the current server time; success transitions it to `ACTIVE`. Revocation by an `AgencyOfficer` is permitted only while the certificate is in `ACTIVE`; success transitions it to terminal `REVOKED` and, for each `FareCard` owned by the rider whose `discount_class` is `REDUCED_FARE` and that has no other `ACTIVE` certificate of any `program_type` covering the current moment, the card's `discount_class` is downgraded to `STANDARD` (in-flight `TAPPED_IN` trips are left in place; only future tap-ins charge at the standard rate). Two simultaneous approvals that would each move a certificate to `ACTIVE` with overlapping `[valid_from, valid_until]` windows on the same `(rider_id, program_type)` resolve first-writer-wins on the `PENDING` → `ACTIVE` transition for that pair, and the loser is rejected with `ERR_CERTIFICATE_WINDOW_OVERLAP`.

### 3.3. Low-Income Verification and Renewal

The low-income discount is gated on a `LowIncomeVerification` record. A rider or an agency officer creates one by submitting a `rider_id` and the rider-declared `declared_annual_income_cents`; the record starts in `status` `PENDING` with `verified_annual_income_cents` null and `approved_at` null. Approval is performed by an `AgencyOfficer` who submits the agency-verified `verified_annual_income_cents` in the request body. The threshold for eligibility is three million cents (that is, thirty thousand US dollars), and the comparison is inclusive: a verified income that is at most three million cents qualifies. If the verified income satisfies the threshold and the verification is still in `PENDING`, the record transitions to `ACTIVE`, `approved_at` is written to the server clock, the rider's `low_income_verified` is set to true, and any `FareCard` for that rider whose `discount_class` is `LOW_INCOME` resumes charging the low-income rate. If the verified income exceeds the threshold and the verification is still in `PENDING`, the record transitions to terminal `REJECTED` and the rider's `low_income_verified` remains false. The two transitions out of `PENDING` are mutually exclusive but receive symmetric treatment: each requires `PENDING` status and writes its destination atomically. Approval performed against any non-`PENDING` certificate or verification is rejected with `ERR_INVALID_STATE`.

A verification's `ACTIVE` status is time-limited. The low-income expiry sweep walks every verification whose `approved_at` plus three hundred sixty-five days is at or before the current server time and transitions each from `ACTIVE` to terminal `EXPIRED`. For every rider whose only `ACTIVE` verification just expired, `low_income_verified` flips back to false; every `FareCard` for that rider whose `discount_class` is `LOW_INCOME` is downgraded to `STANDARD`, so that future tap-ins charge the standard rate while existing `TAPPED_IN` trips are unaffected.

### 3.4. Mobile Wallet Tokens

A `MobilePaymentToken` records the rider's `rider_id`, the `wallet_provider` (`APPLE_PAY`, `GOOGLE_PAY`, or `SAMSUNG_PAY`), the provider-supplied `device_fingerprint`, an optional `bound_card_id` linking the token to a specific `FareCard`, and a `status` that begins as `ACTIVE`. The pair `(rider_id, device_fingerprint)` is unique: an attempt to register a second token on the same device for the same rider is rejected with `ERR_DEVICE_ALREADY_BOUND`. Revocation is a one-way transition from `ACTIVE` to terminal `REVOKED`, performed by the owning rider or by an agency officer; once revoked, the token cannot be used for new tap-ins.

### 3.5. Tap-In, the Provisional Charge, and Transfers

A tap-in is the single most complex operation in the system. The rider submits a payload with `card_id`, `idempotency_key`, `tap_in_at`, and an optional `mobile_token_id`. The `idempotency_key` is a client-supplied string of length between 1 and 64 characters that, together with `card_id`, uniquely identifies the tap; a second tap-in carrying the same pair returns the original `Trip` resource with no new debit, but if a genuinely conflicting payload arrives racing against an in-flight tap, the duplicate is rejected with `ERR_DUPLICATE_TAP` — first-writer-wins on the `(card_id, idempotency_key)` pair. The system then enforces that the card's `status` is `ACTIVE`, that no other trip on this card has `travel_status` `TAPPED_IN` (concurrent attempts serialise first-writer-wins on `Trip.travel_status` equal to `TAPPED_IN`, with the loser receiving `ERR_TRIP_ALREADY_OPEN`), that `tap_in_at` lies within the card's `[valid_from, valid_until]` window (otherwise `ERR_CARD_OUTSIDE_VALIDITY`), and, if a `mobile_token_id` is supplied, that the referenced `MobilePaymentToken` is in `status` `ACTIVE`.

Once the checks pass, the trip is created with `travel_status` `TAPPED_IN` and `fare_status` `PROVISIONAL`. The system then ensures cap-period plumbing exists for this card and this `tap_in_at`: if no `DAILY` `FareCapPeriod` exists for the UTC day containing `tap_in_at`, one is created with `cap_cents` pinned to the configured daily ceiling of 600 cents; if no `WEEKLY` `FareCapPeriod` exists for the ISO week containing `tap_in_at`, one is created with `cap_cents` pinned to the configured weekly ceiling of 3300 cents. The trip's `cap_period_id` is pinned at tap-in to the DAILY period.

The provisional fare is computed in three steps. First, the per-leg base fare after discount is selected: for `STANDARD` cards it is the configured base fare of 275 cents; for `REDUCED_FARE` cards it is the base fare multiplied by 0.50, rounded half-up to the nearest whole cent (so 275 times 0.50 is 137.5, which rounds to 138 cents); for `LOW_INCOME` cards it is the base fare multiplied by 0.60, rounded half-up (so 275 times 0.60 is 165 cents). If a `LOW_INCOME` card is presented while the rider's `low_income_verified` is false, the calculation falls back to the standard 275-cent base. Second, the transfer rule is evaluated: the system searches for a prior trip on the same card whose `travel_status` is `COMPLETED`, whose `tap_in_at` is strictly less than the present `tap_in_at`, whose elapsed minutes since that prior `tap_in_at` are at most one hundred twenty (the boundary at exactly one hundred twenty minutes counts as a transfer), and which is not already the `first_trip_id` of an existing `TransferLink`; among all qualifying priors, the one with the greatest `tap_in_at` is chosen, with the lexicographically greatest `Trip.id` breaking any remaining tie. If such an eligible prior exists, the pre-cap fare for the present trip is zero (the transfer is free) and a `TransferLink` is created, recording the prior trip as `first_trip_id`, the present trip as `second_trip_id`, and the elapsed minutes between their `tap_in_at` values as `window_minutes` (constrained to lie strictly above zero and at most one hundred twenty); the present trip's `transfer_link_id` is set accordingly. Otherwise the pre-cap fare is the post-discount per-leg base fare. Third, the cap allocation is applied: the daily remaining is the maximum of zero and the daily period's `cap_cents` minus its `accumulated_cents`, the weekly remaining is computed identically against the weekly period, and the trip's `provisional_fare_cents` is the minimum of the pre-cap fare, the daily remaining, and the weekly remaining. The first two are integer cents from the start, so the only rounding step in the entire formula is the half-up rounding applied to the post-discount base in step one.

The FSA-first allocation now runs. If the rider's `employer_id` is null, or there is no `CommuterBenefitAccount`, or the account's `status` is not `ACTIVE`, then `paid_from_fsa_cents` is zero. Otherwise `paid_from_fsa_cents` is the minimum of the just-computed `provisional_fare_cents` and the account's current `balance_cents`. The remainder is `provisional_fare_cents` minus `paid_from_fsa_cents`. Before any state is mutated, the system checks that this remainder does not exceed the card's `wallet_balance_cents`; if the wallet plus the FSA share together cannot cover the fare, the tap-in is rejected with `ERR_INSUFFICIENT_FUNDS` and nothing has been written. Otherwise the account's `balance_cents` is decremented by `paid_from_fsa_cents`, the card's `wallet_balance_cents` is decremented by the remainder, and the trip's `paid_from_fsa_cents` is recorded.

Finally the cap-period bookkeeping closes the operation. Both the daily and the weekly `FareCapPeriod` have their `accumulated_cents` incremented by `provisional_fare_cents`, and if `accumulated_cents` reaches the period's `cap_cents` on either dimension, that period's `cap_reached_at` is set to `tap_in_at`. The tap-in returns the freshly created trip; the FSA account, the card, and the affected cap periods each have their `updated_at` refreshed and their `version` incremented (cap periods are mutated on both daily and weekly dimensions whenever a tap arrives within either window).

### 3.6. Tap-Out, the Incomplete-Trip Sweep, and Travel Closure

When the rider taps out, the request body carries a `tap_out_at` timestamp; the operation is permitted only when the trip's `travel_status` is `TAPPED_IN`, when `tap_out_at` is strictly greater than `tap_in_at` (otherwise `ERR_TAP_OUT_NOT_AFTER_TAP_IN`), and when the calling rider owns the card the trip is on. Success writes `tap_out_at`, transitions `travel_status` from `TAPPED_IN` to `COMPLETED`, and refreshes `updated_at`.

When a rider taps in but never taps out, the incomplete-trip sweep closes the trip on the rider's behalf. The sweep walks every trip whose `travel_status` is `TAPPED_IN` and whose `tap_in_at` plus one hundred eighty minutes is at or before the current server clock and force-closes each one: `tap_out_at` is written to `tap_in_at` plus one hundred eighty minutes, and `travel_status` transitions to terminal `INCOMPLETE_FORCED`. If the trip was charged a discounted provisional fare — for instance because the transfer rule placed the pre-cap fare at zero — the sweep additionally charges the difference between the post-discount per-leg base fare and the original `provisional_fare_cents` against the wallet so that the trip's contribution to the cap window equals the full post-discount base. That additional charge cascades through the cap window: the `FareCapPeriod.accumulated_cents` rises by the same amount, and any subsequent trip in the same window whose forward-looking allocation had relied on remaining cap headroom may, at settlement time, flip from "charged" to "capped-free" once chronological re-settlement runs.

### 3.7. Disputes

A rider may file a dispute on any trip whose `fare_status` is `PROVISIONAL` and whose owning card belongs to them. Filing creates a `DisputeCase` with the trip's `trip_id` and the filing rider's `rider_id`, starting in `status` `OPEN`; the trip's `fare_status` transitions from `PROVISIONAL` to `DISPUTED`. An `AgencyOfficer` may claim the dispute, transitioning `status` from `OPEN` to `INVESTIGATING`, only while the dispute is in `OPEN`; an attempt against any other state is rejected with `ERR_INVALID_STATE`. From `INVESTIGATING` the officer has three options: request more evidence, which transitions `status` back to `OPEN` so the case can cycle (rider provides evidence, officer claims again, requests again, and so on); resolve in favour of the rider with a `decision` of REFUND; or resolve against the rider with a `decision` of REJECT. Both terminal resolutions require the dispute to be in `INVESTIGATING`. A REFUND resolution sets `refund_amount_cents` to the trip's `provisional_fare_cents`, transitions the trip's `fare_status` from `DISPUTED` to `SETTLED` with `settled_fare_cents` set to zero, splits the refund proportionally back to the `CommuterBenefitAccount.balance_cents` (in proportion to `paid_from_fsa_cents` over `provisional_fare_cents`) and back to the card's `wallet_balance_cents` (taking the difference), and decrements `accumulated_cents` by `provisional_fare_cents` on both the daily and weekly `FareCapPeriod`. A REJECT resolution simply transitions the trip's `fare_status` from `DISPUTED` to `SETTLED` with `settled_fare_cents` set equal to `provisional_fare_cents` and writes no refund. Two officers attempting to resolve the same dispute simultaneously, or an officer's resolve racing against any other terminal mutation of the dispute, serialise first-writer-wins on the dispute's `status`; the loser observes a `status` other than `INVESTIGATING` and is rejected with `ERR_INVALID_STATE`.

### 3.8. The Settlement Sweep and the Chronological Reconciliation

After a cap window closes, the settle sweep recomputes each trip's true fare in chronological order. The sweep is permitted to settle a trip only when the trip's `travel_status` is in `{COMPLETED, INCOMPLETE_FORCED}` and the current server clock is at or after the `window_end` of the trip's `cap_period_id`; trips currently in `fare_status` `DISPUTED` are excluded from the sweep until their dispute resolves. For each eligible cap period, the sweep gathers all trips on that card whose `tap_in_at` is in the half-open window `[window_start, window_end)`, orders them ascending by `tap_in_at` (with `Trip.id` ascending as the tie-break), and walks the ordered list with a running accumulator initialised at zero. For each trip it recomputes the post-discount per-leg base fare exactly as in step one of the tap-in formula, then recomputes transfer eligibility against the chronological history actually emerging (rather than the live view captured at the original tap-in), then re-applies the cap as the maximum of zero and the minimum of (a) the chronologically recomputed pre-cap fare, (b) the daily period's `cap_cents` minus the running accumulator, and (c) the weekly remaining at this point of the walk. The result is written to the trip's `settled_fare_cents`, the running accumulator is increased by that amount, and the sweep proceeds to the next trip.

After all trips in the window are settled, the sweep applies the delta between each trip's `provisional_fare_cents` and its `settled_fare_cents`. When the settled amount is less than the provisional amount, the difference is refunded back: the FSA share is the difference scaled by `paid_from_fsa_cents` divided by `provisional_fare_cents`, rounded half-up, and credited to the account's `balance_cents`; the wallet share is the rest of the difference and is credited to the card's `wallet_balance_cents`, absorbing any rounding remainder so that the total credited equals the difference exactly. When the settled amount exceeds the provisional amount, the additional charge is debited from the wallet first and the FSA second. Each trip's `fare_status` transitions from `PROVISIONAL` to `SETTLED`. Because the chronological walk treats earlier trips before later ones, and because an `INCOMPLETE_FORCED` force-closure between the two sweeps may retroactively raise an earlier trip's contribution from zero (transfer-discounted) to the full post-discount base, the provisional and settled views can legitimately diverge on the same inputs — provisional is a forward-looking forecast, settled is the chronological ground truth, and the system's compensating refunds and back-charges bridge the two so that wallet plus FSA together exactly equal the original conserved quantity per the rounding-order pinned in §2.8.

### 3.9. Commuter Benefit Accounts and the Monthly Cap

An employer-administered staff member opens a `CommuterBenefitAccount` for a rider by submitting that rider's `rider_id` and their own `employer_id`; the account's `employer_id` must equal the acting employer's `X-User-ID`. The account begins with `balance_cents` of zero and `status` `ACTIVE`, and there may be at most one account per rider. Contributions are posted by submitting the `account_id`, the `amount_cents` (strictly positive — otherwise `ERR_INVALID_AMOUNT`), and the `contribution_month` as a `YYYY-MM` tag identifying the calendar month against which the employer's monthly cap is enforced. Each successful contribution starts in `status` `APPLIED` and increments the account's `balance_cents` by `amount_cents`. The monthly cap is enforced on the sum of all `APPLIED` contributions for the same employer in the same `contribution_month`: a new contribution that would push the running sum past `Employer.monthly_contribution_cap_cents` is rejected with `ERR_FSA_MONTHLY_CAP_EXCEEDED`, and two concurrent contributions racing against the cap serialise first-writer-wins on the one that would breach it. A contribution may be reversed by appending a new `FSAContribution` with the same `account_id`, the same `contribution_month`, and a negated `amount_cents`; the original's `status` becomes `REVERSED`. The account's `balance_cents` is therefore exactly the sum of `amount_cents` across all `APPLIED` contributions (positive original entries plus negative reversal entries) minus all `paid_from_fsa_cents` debits from trips charged from that account plus all FSA-share refunds credited back to the account. When the sponsoring employer is suspended, every `CommuterBenefitAccount` carrying that `employer_id` transitions from `ACTIVE` to `FROZEN`, blocking both new contributions and new tap-in disbursements while still allowing refunds.

### 3.10. The Logical Clock and the System Sweeps

For test-driving the temporal mechanics of the API there is an administrative capability to advance the server's logical clock to a supplied `to` instant, expressed as an ISO 8601 UTC timestamp; it does not by itself mutate any other resource. Three system sweeps then act on the clock: the incomplete-trip sweep closes any tap that has been open at least one hundred eighty minutes (§3.6); the settle sweep reconciles each cap period whose `window_end` is at or before the clock (§3.8); and the low-income-expiry sweep transitions any `LowIncomeVerification` whose `approved_at` plus three hundred sixty-five days has elapsed (§3.3). All four are restricted to agency operators (the clock-advance capability is additionally exposed to `Auditor` for replay scenarios), and each sweep operates idempotently — running it twice against the same logical clock leaves the system in the same state as running it once.

### 3.11. List Endpoint Filters

The trip-list endpoint accepts the following query parameters in addition to `limit` and `offset`: `card_id` and `rider_id` restrict by ownership; `date_from` and `date_to` restrict by `tap_in_at`; `fare_status` and `travel_status` restrict by the respective state dimension. The cap-periods endpoint accepts `card_id`, `scope`, `window_from`, and `window_to`. Riders see only their own resources; agency officers and auditors see all. Pagination bounds are checked just like every other list endpoint, and a `limit` outside `[1, 100]` or a negative `offset` is rejected with `ERR_INVALID_PAGINATION`.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources (such as a `Rider`, a `FareCard`, a `Trip`, a `DisputeCase`, or an `FSAContribution`) return a `201 Created` status code. Operations that modify an existing resource — including approvals, revocations, suspensions, reactivations, top-ups, closures, tap-outs, dispute lifecycle moves, clock advances, and system sweeps — return a `200 OK` status code. List endpoints likewise return `200 OK`.

| Method | Path                                                                | Description                                                                       | Authorized Role(s)               |
| ------ | ------------------------------------------------------------------- | --------------------------------------------------------------------------------- | -------------------------------- |
| POST   | `/transit/riders`                                                   | Create a rider                                                                    | AgencyOfficer                    |
| GET    | `/transit/riders/{rider_id}`                                        | Fetch a rider                                                                     | Rider, AgencyOfficer, Auditor    |
| POST   | `/transit/employers`                                                | Create an employer                                                                | AgencyOfficer                    |
| POST   | `/transit/employers/{employer_id}/suspend`                          | Suspend an employer and freeze its FSA accounts                                   | AgencyOfficer                    |
| POST   | `/transit/cards`                                                    | Issue a fare card to a rider with chosen discount class                           | AgencyOfficer, Rider             |
| GET    | `/transit/cards/{card_id}`                                          | Read a fare card                                                                  | Rider, AgencyOfficer, Auditor    |
| POST   | `/transit/cards/{card_id}/top-up`                                   | Add stored value to a card's wallet                                               | Rider, AgencyOfficer             |
| POST   | `/transit/cards/{card_id}/suspend`                                  | Suspend a card; block new tap-ins                                                 | AgencyOfficer                    |
| POST   | `/transit/cards/{card_id}/reactivate`                               | Reactivate a suspended card                                                       | AgencyOfficer                    |
| POST   | `/transit/cards/{card_id}/close`                                    | Close a card; zero its wallet                                                     | Rider                            |
| POST   | `/transit/reduced-fare-certificates`                                | Create a Reduced Fare Card certificate (PENDING)                                  | AgencyOfficer                    |
| POST   | `/transit/reduced-fare-certificates/{cert_id}/approve`              | Approve a certificate (PENDING to ACTIVE)                                         | AgencyOfficer                    |
| POST   | `/transit/reduced-fare-certificates/{cert_id}/revoke`               | Revoke a certificate (ACTIVE to REVOKED) and cascade discount downgrade           | AgencyOfficer                    |
| POST   | `/transit/low-income-verifications`                                 | Create a low-income verification (PENDING)                                        | Rider, AgencyOfficer             |
| POST   | `/transit/low-income-verifications/{verif_id}/approve`              | Set verified income; resolves to ACTIVE or REJECTED based on the threshold       | AgencyOfficer                    |
| POST   | `/transit/mobile-tokens`                                            | Register a mobile wallet token (Apple, Google, or Samsung Pay)                    | Rider                            |
| POST   | `/transit/mobile-tokens/{token_id}/revoke`                          | Revoke a mobile token                                                             | Rider, AgencyOfficer             |
| POST   | `/transit/trips`                                                    | Tap in; idempotent on (card_id, idempotency_key); debits FSA then wallet          | Rider                            |
| GET    | `/transit/trips/{trip_id}`                                          | Read a trip                                                                       | Rider, AgencyOfficer, Auditor    |
| GET    | `/transit/trips`                                                    | List trips with filters                                                           | Rider, AgencyOfficer, Auditor    |
| POST   | `/transit/trips/{trip_id}/tap-out`                                  | Tap out (TAPPED_IN to COMPLETED)                                                  | Rider                            |
| GET    | `/transit/cap-periods`                                              | List cap periods with filters                                                     | Rider, AgencyOfficer, Auditor    |
| POST   | `/transit/fsa-accounts`                                             | Open a CommuterBenefitAccount sponsored by an employer                            | EmployerAdmin                    |
| POST   | `/transit/fsa-contributions`                                        | Post an FSA contribution to an account; monthly cap enforced                      | EmployerAdmin                    |
| POST   | `/transit/fsa-contributions/{contrib_id}/reverse`                   | Reverse a contribution (creates a negated FSAContribution)                        | EmployerAdmin                    |
| POST   | `/transit/disputes`                                                 | File a dispute on a trip                                                          | Rider                            |
| POST   | `/transit/disputes/{dispute_id}/claim`                              | Claim a dispute (OPEN to INVESTIGATING)                                           | AgencyOfficer                    |
| POST   | `/transit/disputes/{dispute_id}/request-evidence`                   | Cycle a dispute back to OPEN to await more rider evidence                         | AgencyOfficer                    |
| POST   | `/transit/disputes/{dispute_id}/resolve`                            | Resolve a dispute to RESOLVED_REFUNDED or RESOLVED_REJECTED                       | AgencyOfficer                    |
| POST   | `/transit/_clock/advance`                                           | Advance the server's logical clock to a supplied ISO 8601 UTC moment              | AgencyOfficer, Auditor           |
| POST   | `/transit/_sweep/incomplete-trips`                                  | Force-close any TAPPED_IN trip whose tap_in_at + 180 minutes has elapsed          | AgencyOfficer                    |
| POST   | `/transit/_sweep/settle`                                            | Recompute settled fares chronologically and apply refunds or back-charges         | AgencyOfficer                    |
| POST   | `/transit/_sweep/low-income-expiry`                                 | Expire any LowIncomeVerification whose approved_at + 365 days has elapsed         | AgencyOfficer                    |

## 5. Error Code Catalogue

| Error ID                              | HTTP Status Code      |
| ------------------------------------- | --------------------- |
| `ERR_AUTH_MISSING`                    | 401 Unauthorized      |
| `ERR_AUTH_INVALID_ROLE`               | 401 Unauthorized      |
| `ERR_FORBIDDEN`                       | 403 Forbidden         |
| `ERR_NOT_FOUND`                       | 404 Not Found         |
| `ERR_REFERENCE_NOT_FOUND`             | 404 Not Found         |
| `ERR_INVALID_STATE`                   | 409 Conflict          |
| `ERR_CARD_NOT_ACTIVE`                 | 409 Conflict          |
| `ERR_TRIP_ALREADY_OPEN`               | 409 Conflict          |
| `ERR_DUPLICATE_TAP`                   | 409 Conflict          |
| `ERR_CARD_OUTSIDE_VALIDITY`           | 422 Unprocessable     |
| `ERR_TAP_OUT_NOT_AFTER_TAP_IN`        | 422 Unprocessable     |
| `ERR_MISSING_REDUCED_FARE_CERTIFICATE`| 409 Conflict          |
| `ERR_MISSING_LOW_INCOME_VERIFICATION` | 409 Conflict          |
| `ERR_CERTIFICATE_WINDOW_OVERLAP`      | 409 Conflict          |
| `ERR_DEVICE_ALREADY_BOUND`            | 409 Conflict          |
| `ERR_INVALID_AMOUNT`                  | 422 Unprocessable     |
| `ERR_FSA_MONTHLY_CAP_EXCEEDED`        | 409 Conflict          |
| `ERR_INSUFFICIENT_FUNDS`              | 402 Payment Required  |
| `ERR_VERSION_CONFLICT`                | 409 Conflict          |
| `ERR_INVALID_PAGINATION`              | 422 Unprocessable     |
