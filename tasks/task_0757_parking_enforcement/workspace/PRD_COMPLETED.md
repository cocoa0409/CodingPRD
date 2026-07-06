# Parking Enforcement API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Municipal Parking-Enforcement & Citation Issuance API, the system of record for a city's on-street enforcement program. The platform coordinates the full arc of enforcement work: patrol officers open shifts on assigned beats and issue citations — whether captured by License Plate Recognition (LPR) or entered on a handheld device — each backed by a required evidence photo. Every citation draws its fine from a configurable violation-code schedule, adjusted for repeat offenses and for the surcharge policy of the beat's patrol zone.

Beyond issuance, the system operates as a compliance and reconciliation ledger. It tracks each vehicle's outstanding liability, escalates persistent non-payers through scofflaw, boot, and tow tiers, and integrates with registration holds so that unresolved debt has real administrative consequences. Motorists interact through self-service online payment and the right to contest, which routes disputed citations into a hearing process adjudicated by dedicated officers. Supervisors retain override authority — voiding erroneous citations, reassessing fines, waiving balances, and refunding payments — while the system continuously recomputes derived balances and enforcement eligibility so that the audit trail and revenue picture remain consistent at every step.

The requirements below define the precise contracts every implementation must honor: the shape of API responses, the roles permitted to act, the exact arithmetic behind every fine and fee, the state machines that govern each resource, and the full catalogue of error conditions.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they are acting. The system recognizes exactly five roles: `Admin`, `EnforcementOfficer`, `Supervisor`, `HearingOfficer`, and `Motorist`. If the `X-User-Role` header is missing or does not name one of these recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the role is recognized but is not permitted to perform the requested operation under the access matrix, the request is rejected with `ERR_UNAUTHORIZED`.

The roles differ in how their `X-User-ID` relates to persisted data:

- When `X-User-Role` is `EnforcementOfficer`, `X-User-ID` is the `id` of the acting `Officer`. Ownership checks compare a resource's officer foreign key to this value: an officer may only open or close a shift whose `officer_id` equals their `X-User-ID`, and may only issue a citation against a shift they own. A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`.
- When `X-User-Role` is `Admin`, `Supervisor`, `HearingOfficer`, or `Motorist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server accepts it for authentication and authorization but does not compare it to any entity's `id`. `Admin` configures the system, `Supervisor` performs enforcement overrides and adjudicated financial actions, `HearingOfficer` runs the hearing calendar, and `Motorist` pays and contests.

Read access (all `GET` endpoints) is available to every one of the five roles.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. A `limit` or `offset` outside these bounds is a field-level validation failure and is rejected with `ERR_VALIDATION`.

Unless stated otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order, with ties in `created_at` broken by creation order (the sequence in which the resources were minted). Each list response carries `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object (`has_more` is true exactly when `offset + limit` is less than `total_count`). List endpoints additionally accept reverse-lookup filters as query parameters — for example a citation listing may be narrowed by `vehicle_id`, `shift_id`, `violation_code_id`, `officer_id`, `beat_id`, or `status`, a shift listing by `officer_id`, `beat_id`, or `status`, a payment or contest listing by `citation_id` and `status`, a hearing listing by `contest_id`, `room_id`, or `status`, a boot/tow listing by `vehicle_id` or `status`, and a registration-hold listing by `vehicle_id`, `boot_tow_order_id`, or `status`.

### 2.4. Common Resource Properties and Immutable Configuration

Most resources carry a standard set of system-managed fields:

- `id` — a unique, server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp (three fractional digits) recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` — an integer that is set to 1 at creation and increments by one on every mutation. It underpins optimistic concurrency control (§2.7).

Two resource types are immutable configuration records and therefore carry only `id` and `created_at` — they have no `updated_at` and no `version`: the `Beat` and the `HearingRoom`. A `Beat` is defined by its `beat_code`, its human-readable `name`, and its `patrol_zone`, which must be one of `DOWNTOWN`, `RESIDENTIAL`, or `SCHOOL`. A `HearingRoom` is defined by its `room_code` and its `name`. All other resources — `Officer`, `ViolationCode`, `Shift`, `Vehicle`, `Citation`, `Payment`, `Contest`, `Hearing`, `BootTowOrder`, and `RegistrationHold` — carry the full `updated_at` and `version` fields.

### 2.5. The Logical Clock

The system runs on a logical clock rather than wall-clock time. At server startup the clock reads `2026-03-01T00:00:00Z`, and it never falls back to real time. An `Admin` may advance or set it by supplying a `to_iso8601` instant to the clock-setting capability, after which "now" is that instant. Server-stamped timestamps read from this clock: a citation's `issued_at` is set to the logical now at issue, and a shift's `closed_at` is set to the logical now at close (and is null while the shift is `OPEN`).

### 2.6. Monetary Values and Precision

All money in the system is expressed as an integer number of cents; there are no fractional-cent values in stored fields or responses. Where a calculation multiplies by a rate or percentage and must return to whole cents, the result is rounded using the round-half-up method (a value exactly halfway between two cents rounds up to the larger cent). Each calculation below states the exact point at which rounding is applied; the order of rounding relative to addition and clamping is significant and must be followed precisely. The one non-monetary computed decimal in the system, a shift's `citations_per_hour`, is likewise rounded half-up, to two decimal places.

### 2.7. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a current view of the target, using a version the client last observed:

- A supervisor fine reassessment must carry `expected_citation_version`. The reassessment does not itself depend on the citation's status, and repeating it from the same observed state would legitimately succeed, so there is no state precondition to protect it. If the citation's `version` has advanced since the client observed it — because an intervening reassessment, waiver, payment settlement, or contest filing bumped it — the supplied `expected_citation_version` no longer matches the citation's current `version`, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- A supervisor balance waiver is applied through the parent `Vehicle` and must carry `expected_vehicle_version`. Multiple waivers are legitimately repeatable and change no gating field, so this too is guarded purely by version. If another writer — a settle, a refund, a void, or a prior waiver — has advanced the vehicle's `version` since it was observed, the supplied `expected_vehicle_version` is stale and the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field; those operations are guarded by their state preconditions instead.

### 2.8. Cascading Consistency and the Vehicle Ledger

The `Vehicle` is the reconciliation hub of the system. Its `outstanding_balance_cents`, `projected_balance_cents`, `unpaid_citation_count`, `scofflaw_status`, and `has_active_registration_hold` are all derived fields — never supplied by a client — and are recomputed immediately whenever anything that could affect them changes: a citation is issued, voided, contested, upheld, or dismissed; a payment is settled or refunded; or a supervisor applies a waiver or reassesses a fine. Each such recomputation that mutates a resource refreshes that resource's `updated_at` and increments its `version`. For the `Vehicle` specifically, a recompute refreshes `updated_at` and bumps `version` only when one of its settled-basis gating fields — `outstanding_balance_cents`, `unpaid_citation_count`, `scofflaw_status`, or `has_active_registration_hold` — actually changes; a recompute that alters only `projected_balance_cents` (as when a new `PENDING` payment is recorded) writes that field without bumping the vehicle's `version` or `updated_at`.

Consistency propagates in cascades. Issuing a citation that pushes a vehicle into a boot- or tow-eligible tier automatically creates an enforcement order and places a registration hold. Conversely, any event that de-escalates a vehicle below the boot threshold cascades the other way, cancelling the still-`ORDERED` enforcement order and clearing the hold it placed. These automatic transitions are performed by the system itself, without a client request against the affected order or hold. The specific arithmetic and thresholds behind each cascade are given in §3.

### 2.9. Resource Existence and Reference Resolution

Every request that names resources — by an identifier in the URL path or by a foreign key in the body — must resolve them before any business rule runs. References are validated left to right: path identifiers first, then body foreign keys in the order they are declared for that operation. The first reference that does not resolve produces the corresponding not-found error, one per entity, all carrying HTTP 404: `ERR_OFFICER_NOT_FOUND`, `ERR_BEAT_NOT_FOUND`, `ERR_VIOLATION_CODE_NOT_FOUND`, `ERR_HEARING_ROOM_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_CITATION_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_CONTEST_NOT_FOUND`, `ERR_HEARING_NOT_FOUND`, `ERR_BOOT_TOW_ORDER_NOT_FOUND`, and `ERR_REGISTRATION_HOLD_NOT_FOUND`.

### 2.10. Order of Validation

When several checks could reject the same request, they are evaluated in a fixed precedence so that the returned error is deterministic. The order is:

1. **Authentication** — the `X-User-Role` header is present and names a recognized role, else `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
2. **Authorization** — the role is permitted the operation, else `ERR_UNAUTHORIZED` (403). Applies to every endpoint.
3. **Existence** — all referenced resources resolve left to right (§2.9), else the entity's not-found error (404). Applies to every endpoint that references a resource id.
4. **Ownership** — for opening a shift, closing a shift, and issuing a citation, the acting `EnforcementOfficer`'s `X-User-ID` matches the relevant `officer_id`, else `ERR_NOT_RESOURCE_OWNER` (403).
5. **Concurrency** — for the reassessment and the waiver operations, the supplied version matches the parent's current `version`, else `ERR_STALE_VERSION` (412).
6. **State** — the target resource is in a state that permits the requested transition, else the applicable conflict error (409), such as `ERR_INVALID_STATE`, `ERR_SHIFT_NOT_OPEN`, `ERR_CITATION_NOT_PAYABLE`, `ERR_CITATION_NOT_CONTESTABLE`, `ERR_PAYMENT_NOT_REFUNDABLE`, `ERR_CONTEST_ALREADY_EXISTS`, or `ERR_BOOT_ALREADY_ACTIVE`. Applies to state-transition endpoints.
7. **Temporal** — for opening a shift, scheduling a hearing, and adjourning a hearing, the interval does not collide (§3), else `ERR_SHIFT_OVERLAP` or `ERR_ROOM_UNAVAILABLE` (409).
8. **Eligibility** — for issuing a citation and for ordering a manual boot/tow, the enforcement preconditions hold, else `ERR_VIOLATION_CODE_RETIRED` or `ERR_VEHICLE_NOT_BOOT_ELIGIBLE` (422).
9. **Fiscal bounds** — for recording a payment, applying a waiver, and reassessing a fine, the monetary amounts are within their permitted ranges, else `ERR_PAYMENT_AMOUNT_MISMATCH`, `ERR_ADJUSTMENT_EXCEEDS_BALANCE`, or `ERR_VALIDATION` (422).
10. **Field-level** — required fields are present, enums are valid, each `scheduled_end` is strictly after its `scheduled_start`, and pagination is in bounds, else `ERR_VALIDATION` (400). Applies to every endpoint.

## 3. Business Logic & Workflows

### 3.1. Configuring the Enforcement System

An `Admin` seeds the reference data on which all enforcement depends. Officers are registered with a `badge_number` and a `full_name`. Patrol beats are created with a `beat_code`, a `name`, and a `patrol_zone` — the zone class that later drives a citation's surcharge. Hearing rooms are created with a `room_code` and a `name`.

The fine schedule lives in violation codes. Each is created with a short `code` (such as an expired-meter code), a human `description`, a `base_fine_cents` amount that must be at least 0 (an integer), and a required `is_booting_eligible` boolean. This flag is recorded on the code but does not gate escalation: the scofflaw arithmetic of §3.4 counts every unpaid citation and sums every unpaid balance regardless of whether its code is booting-eligible, so `is_booting_eligible` has no effect on the unpaid set, the balances, or the boot/tow tier. A newly created violation code begins with `status` of `ACTIVE`. An `Admin` may retire a code, moving its `status` from `ACTIVE` to `RETIRED`; retiring a code that is not `ACTIVE` (i.e. already `RETIRED`) is rejected with `ERR_INVALID_STATE`. Retirement is one-way and terminal. Existing citations already written against a retired code are unaffected, but any attempt to issue a new citation referencing a `RETIRED` code is rejected with `ERR_VIOLATION_CODE_RETIRED`.

### 3.2. Officer Shifts and Productivity

Before an officer can write citations, they open a shift. Opening a shift names the working `officer_id`, the `beat_id` being patrolled, and the shift window as `scheduled_start` and `scheduled_end`, where `scheduled_end` must be strictly later than `scheduled_start`. A shift opens in `status` `OPEN`. Because an `EnforcementOfficer` may only manage their own work, the acting officer's `X-User-ID` must equal the `officer_id` on the shift being opened, or the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

An officer cannot be in two places at once, so a new shift may not overlap another `OPEN` shift of the same officer. Overlap is evaluated on half-open intervals with no buffer: a candidate window collides with an existing `OPEN` shift of that officer when the candidate's start falls before that shift's `scheduled_end` and that shift's `scheduled_start` falls before the candidate's end. Two shifts that merely touch — one ending exactly when the next begins — do not overlap and are permitted. A genuine overlap is rejected with `ERR_SHIFT_OVERLAP`.

Closing a shift is permitted only while it is `OPEN` and only by the officer who owns it (`X-User-ID` equal to `officer_id`, else `ERR_NOT_RESOURCE_OWNER`); a shift that is not `OPEN` yields `ERR_SHIFT_NOT_OPEN`. Closing moves the shift from `OPEN` to `CLOSED`, stamps `closed_at` with the logical clock's current time, and finalizes three productivity figures over the citations whose `shift_id` is this shift. The `gross_citation_count` is the raw count of every citation issued during the shift, including any later voided or dismissed. The `net_citation_count` is the quality-adjusted count: every citation of the shift whose `status` is not `VOID` and not `DISMISSED`. The `citations_per_hour` divides the net count by the shift's scheduled duration in hours — the elapsed time from `scheduled_start` to `scheduled_end`, which validation guarantees is positive — and is rounded half-up to two decimal places; when the net count is zero, `citations_per_hour` is exactly 0.00. The gross and net figures diverge precisely when at least one of the shift's citations was voided or dismissed.

### 3.3. Issuing Citations: Tiers, Zones, and the Fine

An `EnforcementOfficer` issues a citation against an `OPEN` shift they own. The issuing payload identifies the cited `vehicle_id`, the `shift_id` under which it is written, and the `violation_code_id`, and records the issuance channel `issued_via` — either `LPR` or `HANDHELD` — together with the `evidence_photo_url` of the mandatory evidence photo. The shift must be `OPEN` (else `ERR_SHIFT_NOT_OPEN`) and the violation code must be `ACTIVE` (else `ERR_VIOLATION_CODE_RETIRED`). From the shift, the system copies the `officer_id` and the `beat_id` onto the citation; the beat's zone drives the surcharge below. The citation is stamped with `issued_at` from the logical clock and opens in `status` `ISSUED`.

The assessed `fine_amount_cents` is computed at issue in a strictly pinned order. First the system establishes the repeat-offense index by counting the vehicle's prior citations of the *same* `violation_code_id` whose `status` is not `VOID`, considering only citations created strictly before this one (ordered by `created_at` ascending). If there are no such prior citations the tier multiplier is 1.0; with exactly one prior it is 1.5; with two or more priors it is 2.0. The base fine is then multiplied by that tier multiplier and rounded half-up to whole cents — this rounding happens *before* the surcharge is added, not after. Next a flat zone surcharge is added according to the citation's beat zone: 2,000 cents for a `DOWNTOWN` beat, 0 cents for a `RESIDENTIAL` beat, and 5,000 cents for a `SCHOOL` beat. Finally the sum is clamped into the allowed band: it is raised to a floor of 2,500 cents if below it and capped at a ceiling of 25,000 cents if above it. The clamped result is the citation's `fine_amount_cents`.

Each citation also carries the derived money fields `amount_paid_cents` and `amount_due_cents`. The `amount_paid_cents` is the sum of the amounts of this citation's `SETTLED` payments plus any supervisor waivers applied against it. The `amount_due_cents` is 0 when the citation's `status` is `DISMISSED`; otherwise it is the `fine_amount_cents` minus `amount_paid_cents`, floored at 0 so it never goes negative. After issue, the system recomputes the vehicle's ledger and scofflaw tier, which may trigger the escalation cascade of §3.4.

A citation's lifecycle statuses are `ISSUED`, `CONTESTED`, `UPHELD`, `DISMISSED`, `PAID`, and `VOID`; `DISMISSED`, `PAID`, and `VOID` are terminal.

### 3.4. The Vehicle Ledger and Scofflaw Escalation

Every `Vehicle` is registered with a `plate` and a two-letter `state` and starts with a `scofflaw_status` of `NONE` and zero balances. From then on the vehicle's ledger is derived from its citations. The unpaid set is the vehicle's citations whose `status` is either `ISSUED` or `UPHELD`; a citation that is `CONTESTED`, `DISMISSED`, `PAID`, or `VOID` is not in the unpaid set. The `unpaid_citation_count` is the size of that set.

Two balances are maintained over the unpaid set, differing only in which payments they credit. The `outstanding_balance_cents` is the settled-basis balance and is authoritative for enforcement: for each unpaid citation it takes the fine less only that citation's `SETTLED` payments and applied waivers (floored at 0), and sums those across the set — `PENDING` payments do not reduce it. The `projected_balance_cents` is the forward-looking preview: it computes the same per-citation shortfall but additionally credits `PENDING` payments as though they will settle, and therefore diverges from the settled balance exactly whenever a `PENDING` payment exists.

The `scofflaw_status` is derived from the settled balance and the unpaid count, checked in this order and using inclusive thresholds. If `outstanding_balance_cents` is at least 100,000 cents, the vehicle is `TOW_ELIGIBLE`. Otherwise, if it is at least 50,000 cents, the vehicle is `BOOT_ELIGIBLE`. Otherwise, if the `unpaid_citation_count` is at least 3, the vehicle is `SCOFFLAW`. Otherwise it is `NONE`. Whenever a citation issue pushes the vehicle to `BOOT_ELIGIBLE` or `TOW_ELIGIBLE`, the system automatically creates a boot/tow enforcement order (with `origin` of `AUTO`) and that order's creation places a `RegistrationHold`, so the vehicle's `has_active_registration_hold` becomes true. That flag is true precisely while at least one `RegistrationHold` for the vehicle is in `status` `PLACED`.

### 3.5. Online Payment and Settlement

A `Motorist` pays online. Recording a payment names the `citation_id`, an `amount_cents`, and a `method` of either `CARD` or `ECHECK`. The target citation must be payable — that is, in `status` `ISSUED` or `UPHELD` — or the payment is rejected with `ERR_CITATION_NOT_PAYABLE`. The amount must be at least 1 cent and no greater than the citation's current `amount_due_cents` at the moment of creation; an amount outside that range is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`. A newly recorded payment opens in `status` `PENDING`, which reduces the vehicle's `projected_balance_cents` but not its authoritative `outstanding_balance_cents`.

Settling a payment captures it. Settlement is allowed only while the payment is `PENDING` and while the citation is still `ISSUED` or `UPHELD`; the payment-state precondition is checked first, so a payment that is not `PENDING` is rejected with `ERR_INVALID_STATE`, while a `PENDING` payment whose citation is no longer `ISSUED` or `UPHELD` is rejected with `ERR_CITATION_NOT_PAYABLE`. On success it moves the payment from `PENDING` to `SETTLED` and increases the citation's `amount_paid_cents` by the payment's `amount_cents`, after which `amount_due_cents` is recomputed. If that brings the amount due to 0 — that is, once the paid amount reaches or exceeds the fine — the citation transitions to `PAID` (from either `ISSUED` or `UPHELD`), and the vehicle ledger and scofflaw tier are recomputed; this de-escalation may cancel a still-`ORDERED` boot/tow order and clear its hold, as described in §3.8.

A `Supervisor` may refund a settled payment as a compensating action. A refund is permitted only on a payment in `status` `SETTLED`, else `ERR_PAYMENT_NOT_REFUNDABLE`; it moves the payment from `SETTLED` to `REFUNDED` and decreases the citation's `amount_paid_cents` by that payment's `amount_cents`. If the citation had been `PAID` and was made so by the very payment now refunded, it reverts from `PAID` back to `ISSUED`. The vehicle ledger and scofflaw tier are recomputed afterward, which may re-escalate the vehicle.

### 3.6. Contesting Citations and the Hearing Calendar

A `Motorist` may contest a citation. Filing a contest names the `citation_id` and the motorist's stated `grounds`. A contest may be filed only against a citation currently in `status` `ISSUED`; any other status yields `ERR_CITATION_NOT_CONTESTABLE`. Furthermore, no non-terminal contest may already exist for that citation — a second concurrent contest is rejected with `ERR_CONTEST_ALREADY_EXISTS`. Filing creates a `Contest` in `status` `SUBMITTED` and moves the citation from `ISSUED` to `CONTESTED`. While `CONTESTED`, the citation leaves the vehicle's unpaid set, so the vehicle balance and scofflaw tier are recomputed and may de-escalate.

A `HearingOfficer` schedules a hearing for a submitted contest. Scheduling names the `contest_id`, the `room_id`, and the hearing window `scheduled_start` and `scheduled_end` (end strictly after start). The contest must be `SUBMITTED` (a contest in any other status is rejected with `ERR_INVALID_STATE`); scheduling creates a `Hearing` in `status` `SCHEDULED` (with `adjournment_count` starting at 0 and `decision` null) and moves the contest from `SUBMITTED` to `HEARING_SCHEDULED`. Hearing rooms enforce a buffered availability window: a candidate window collides with an existing `SCHEDULED` hearing in the same room when the candidate's start falls before that hearing's `scheduled_end` extended forward by 15 minutes, and that hearing's `scheduled_start` pulled back by 15 minutes falls before the candidate's end. In other words, any gap strictly smaller than 15 minutes of turnaround between two hearings in a room is rejected with `ERR_ROOM_UNAVAILABLE`.

The same `HearingOfficer` may adjourn a hearing to reschedule it. Adjourning supplies a new `scheduled_start` and `scheduled_end` and is allowed only while the hearing is `SCHEDULED` (else `ERR_INVALID_STATE`). The new window is re-checked against the room's buffered availability window using the identical 15-minute turnaround rule, but the hearing being adjourned is excluded from its own collision check; a conflict is again `ERR_ROOM_UNAVAILABLE`. A successful adjournment replaces the hearing's `scheduled_start` and `scheduled_end` with the new values and increases `adjournment_count` by 1, leaving the hearing in `SCHEDULED` — a self-cycle that may repeat.

Deciding a hearing renders judgment. Deciding supplies a `decision`, which must be one of `UPHELD` or `DISMISSED`; any other value is rejected with `ERR_HEARING_DECISION_INVALID`. Deciding is allowed only while the hearing is `SCHEDULED` — this state precondition is checked before the decision value, so a hearing that is not `SCHEDULED` is rejected with `ERR_INVALID_STATE`; it sets the hearing's `decision` and moves it from `SCHEDULED` to `HELD`, then drives the paired contest and citation transitions. On an `UPHELD` decision, the contest moves from `HEARING_SCHEDULED` to `CLOSED_UPHELD` and the citation moves from `CONTESTED` to `UPHELD`, returning it to the vehicle's payable unpaid set — the citation remains owed, so the vehicle balance and scofflaw tier are recomputed and may re-escalate. On a `DISMISSED` decision, the contest moves from `HEARING_SCHEDULED` to `CLOSED_DISMISSED` and the citation moves from `CONTESTED` to `DISMISSED`; a dismissed citation's `amount_due_cents` becomes 0 and it is terminal, so the recomputed balance and scofflaw tier may de-escalate. These two branches are deliberately divergent: `UPHELD` preserves the debt, `DISMISSED` extinguishes it.

### 3.7. Supervisor Overrides: Void, Reassess, and Waivers

A `Supervisor` holds corrective authority over citations and vehicle balances. Voiding a citation is permitted only while it is `ISSUED` (a citation in any other status is rejected with `ERR_INVALID_STATE`); it moves the citation from `ISSUED` to `VOID`, removes it from the vehicle's unpaid set, and recomputes the vehicle balance and scofflaw tier, which may de-escalate the vehicle and thereby cancel a still-`ORDERED` order and clear its hold.

Reassessing a citation overrides its fine. The request supplies a `new_fine_amount_cents` together with `expected_citation_version` for the concurrency guard of §2.7. The proposed fine must fall within the permitted band of 2,500 to 25,000 cents; a value outside `[MIN_FINE_CENTS, MAX_FINE_CENTS]` is rejected with `ERR_VALIDATION`. On success the citation's `fine_amount_cents` is set to the clamped new value, its `amount_due_cents` is recomputed, and the vehicle balance and scofflaw tier are recomputed as well; the citation's `version` increments. Reassessment does not change the citation's status.

Applying a waiver reduces what a specific citation owes. The waiver is applied through the parent vehicle and supplies the target `citation_id`, a `waive_amount_cents`, and `expected_vehicle_version` for the concurrency guard. The waiver amount must not exceed that citation's current `amount_due_cents`; an excessive waiver is rejected with `ERR_ADJUSTMENT_EXCEEDS_BALANCE`. The `waive_amount_cents` must additionally be an integer of at least 1, and the named citation must belong to the vehicle addressed in the path; a violation of either is a field-level `ERR_VALIDATION`. On success the citation's `amount_paid_cents` increases by `waive_amount_cents` (waivers count toward the settled basis), the vehicle balance and scofflaw tier are recomputed, and the vehicle's `version` increments; the operation returns the updated `Vehicle` resource (not the citation).

### 3.8. Boot, Tow, Release, and Registration Holds

Enforcement escalation culminates in a `BootTowOrder`. A `Supervisor` may manually order one against a vehicle by naming the `vehicle_id` and the `order_type`, either `BOOT` or `TOW`. A manual order is permitted only when the vehicle is `BOOT_ELIGIBLE` or `TOW_ELIGIBLE`; against a vehicle whose `scofflaw_status` is `NONE` or `SCOFFLAW` it is rejected with `ERR_VEHICLE_NOT_BOOT_ELIGIBLE`. Only one active order may exist per vehicle: if an order in `status` `ORDERED` or `APPLIED` already exists for it, a new one is rejected with `ERR_BOOT_ALREADY_ACTIVE`. A manual order records `origin` of `MANUAL`; an order created automatically by the escalation cascade of §3.4 records `origin` of `AUTO`. Either way the order opens in `status` `ORDERED`, its `fee_cents` is the flat enforcement fee for its type — 7,500 cents for a `BOOT` and 15,000 cents for a `TOW` — and its creation places a `RegistrationHold` in `status` `PLACED`. That hold references the placing order via `boot_tow_order_id` and carries `reason` `BOOT_TOW_ESCALATION`.

A supervisor may physically apply an ordered boot/tow, moving it from `ORDERED` to `APPLIED` (applying an order that is not `ORDERED` is rejected with `ERR_INVALID_STATE`), and may release an order that is currently `ORDERED` or `APPLIED`, moving it to `RELEASED` (releasing an order that is neither `ORDERED` nor `APPLIED` is rejected with `ERR_INVALID_STATE`). Release computes the `release_total_cents` in a pinned order. First the system sums the `amount_due_cents` of the order's vehicle's citations that are still `ISSUED` or `UPHELD` to form the citations subtotal. It then computes the administrative fee as 8.5 percent of that subtotal — the fraction is applied to the citations subtotal alone, rounded half-up to whole cents, and is *not* charged on the boot or tow fee. The `release_total_cents` is the citations subtotal plus the flat enforcement fee (`fee_cents`) plus that rounded administrative fee. The `release_total_cents` is null until the order reaches `RELEASED`.

De-escalation reverses escalation automatically. When a payment settlement, a refund reversal, a void, or a dismissal recomputes a vehicle down to a `scofflaw_status` of `NONE` or `SCOFFLAW`, the system cancels the vehicle's still-`ORDERED` enforcement order, moving it from `ORDERED` to `CANCELLED`; an order that has already been `APPLIED` is not auto-cancelled. Cancelling an order in turn clears the `PLACED` `RegistrationHold` it placed, moving that hold from `PLACED` to `CLEARED`, and once no `PLACED` hold remains for the vehicle its `has_active_registration_hold` is recomputed to false. Registration holds are read-only to clients — they are placed and cleared only through these cascades.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource, drive a state transition, or read data return `200 OK`. In the Authorized Role(s) column, "All roles" means `Admin`, `EnforcementOfficer`, `Supervisor`, `HearingOfficer`, and `Motorist`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/officers` | Register a patrol officer | Admin |
| GET | `/officers/{id}` | Get an officer | All roles |
| POST | `/beats` | Create a patrol beat/route | Admin |
| GET | `/beats/{id}` | Get a beat | All roles |
| POST | `/violation-codes` | Create a violation code and fine-schedule entry | Admin |
| GET | `/violation-codes/{id}` | Get a violation code | All roles |
| POST | `/violation-codes/{id}/retire` | Retire a violation code | Admin |
| POST | `/hearing-rooms` | Create a hearing room | Admin |
| GET | `/hearing-rooms/{id}` | Get a hearing room | All roles |
| POST | `/shifts` | Open a shift on a beat | EnforcementOfficer |
| GET | `/shifts/{id}` | Get a shift | All roles |
| GET | `/shifts` | List shifts | All roles |
| POST | `/shifts/{id}/close` | Close a shift and finalize productivity | EnforcementOfficer |
| POST | `/vehicles` | Register a vehicle record | Admin, Supervisor, EnforcementOfficer |
| GET | `/vehicles/{id}` | Get a vehicle with computed ledger and scofflaw fields | All roles |
| POST | `/vehicles/{id}/adjustments` | Apply a supervisor waiver to one of the vehicle's citations | Supervisor |
| POST | `/citations` | Issue a citation with evidence photo | EnforcementOfficer |
| GET | `/citations/{id}` | Get a citation | All roles |
| GET | `/citations` | List citations | All roles |
| POST | `/citations/{id}/reassess` | Override a citation's fine amount | Supervisor |
| POST | `/citations/{id}/void` | Void a citation | Supervisor |
| POST | `/payments` | Record an online payment against a citation | Motorist |
| GET | `/payments/{id}` | Get a payment | All roles |
| GET | `/payments` | List payments | All roles |
| POST | `/payments/{id}/settle` | Capture/settle a pending payment | Motorist |
| POST | `/payments/{id}/refund` | Refund a settled payment | Supervisor |
| POST | `/contests` | File a contest against a citation | Motorist |
| GET | `/contests/{id}` | Get a contest | All roles |
| GET | `/contests` | List contests | All roles |
| POST | `/hearings` | Schedule a hearing for a contest in a room | HearingOfficer |
| GET | `/hearings/{id}` | Get a hearing | All roles |
| GET | `/hearings` | List hearings | All roles |
| POST | `/hearings/{id}/adjourn` | Adjourn/reschedule a hearing | HearingOfficer |
| POST | `/hearings/{id}/decide` | Render the hearing decision | HearingOfficer |
| POST | `/boot-tow-orders` | Manually order a boot/tow on an eligible vehicle | Supervisor |
| GET | `/boot-tow-orders/{id}` | Get a boot/tow order | All roles |
| GET | `/boot-tow-orders` | List boot/tow orders | All roles |
| POST | `/boot-tow-orders/{id}/apply` | Apply the boot/tow physically | Supervisor |
| POST | `/boot-tow-orders/{id}/release` | Release the boot/tow and compute the release total | Supervisor |
| GET | `/registration-holds/{id}` | Get a registration hold | All roles |
| GET | `/registration-holds` | List registration holds | All roles |
| POST | `/_clock/set_current_utc` | Set the logical clock | Admin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_OFFICER_NOT_FOUND` | 404 |
| `ERR_BEAT_NOT_FOUND` | 404 |
| `ERR_VIOLATION_CODE_NOT_FOUND` | 404 |
| `ERR_HEARING_ROOM_NOT_FOUND` | 404 |
| `ERR_SHIFT_NOT_FOUND` | 404 |
| `ERR_VEHICLE_NOT_FOUND` | 404 |
| `ERR_CITATION_NOT_FOUND` | 404 |
| `ERR_PAYMENT_NOT_FOUND` | 404 |
| `ERR_CONTEST_NOT_FOUND` | 404 |
| `ERR_HEARING_NOT_FOUND` | 404 |
| `ERR_BOOT_TOW_ORDER_NOT_FOUND` | 404 |
| `ERR_REGISTRATION_HOLD_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SHIFT_NOT_OPEN` | 409 |
| `ERR_SHIFT_OVERLAP` | 409 |
| `ERR_ROOM_UNAVAILABLE` | 409 |
| `ERR_CITATION_NOT_PAYABLE` | 409 |
| `ERR_CITATION_NOT_CONTESTABLE` | 409 |
| `ERR_CONTEST_ALREADY_EXISTS` | 409 |
| `ERR_PAYMENT_NOT_REFUNDABLE` | 409 |
| `ERR_BOOT_ALREADY_ACTIVE` | 409 |
| `ERR_HEARING_DECISION_INVALID` | 422 |
| `ERR_VIOLATION_CODE_RETIRED` | 422 |
| `ERR_VEHICLE_NOT_BOOT_ELIGIBLE` | 422 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 |
| `ERR_ADJUSTMENT_EXCEEDS_BALANCE` | 422 |
