# Makerspace Fablab API — Product Requirements Document

## 1. Introduction

This document specifies the Makerspace & Fab-Lab Membership platform, a back-office system that governs how a community workshop sells access to its members and bills them for the equipment time, materials, and storage they consume. The space runs a fleet of high-value, potentially dangerous machines — laser cutters, CNC routers, and 3D printers — and the platform's central job is to let the right member, with the right training, reserve the right machine for the right window, while keeping a precise prepaid wallet ledger behind every charge and refund.

The product reconciles several tensions that a hand-run front desk cannot. Membership comes in both pay-as-you-go day-pass form and recurring monthly subscriptions, each with its own pricing, machine-time discount, prepaid-minute allowance, and locker quota. Safety obligations — a signed waiver, a current certification on the relevant machine class, and a demonstrated readiness before anyone runs a machine unsupervised — must be enforced before, not after, a session begins. Money must be exact: a session is quoted forward when it is confirmed, then reconciled against real occupancy at check-out, and every cent moves through an append-only wallet ledger. Because two staff actions or a member top-up can race against a member's own booking, the platform uses optimistic concurrency control on the writes most exposed to a stale balance.

To make time-dependent behavior deterministic and testable, the platform runs on a **logical clock** rather than wall-clock time. All expiry, window, cycle, and rolling-threshold computations read this clock, which a facility operator advances explicitly.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contract, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an `X-User-Role` that is not one of the three recognized roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The two exceptions that do not require authentication are self-service member registration and setting the logical clock, which are reachable without these headers being validated against an existing identity.

The system recognizes exactly three roles, spelled precisely as `Member`, `StaffInstructor`, and `FacilityAdmin`. When an authenticated caller invokes an operation their role is not permitted to perform — or an ownership-bound role acts on a resource it does not own — the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

A **`Member`** is an entity-backed role: when `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`, and ownership checks on any resource that references a member compare that resource's member foreign key (for example, a reservation's `member_id`, a locker's `member_id`, a purchase's `member_id`, or an enrollment's `member_id`) to `X-User-ID`. A member may act only on their own subscription, reservations, lockers, purchases, and enrollments.

A **`StaffInstructor`** is likewise an entity-backed role: when `X-User-Role` is `StaffInstructor`, `X-User-ID` is the `id` of the acting `Member` record that represents that staff person (the same `id` that appears as a workshop's `instructor_id`). Staff run certifications and workshops, supervise sessions, suspend members, and resolve no-shows, and they have read access across resources.

A **`FacilityAdmin`** is an opaque operator role: when `X-User-Role` is `FacilityAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but does not compare it to any entity's `id`. A `FacilityAdmin` configures membership tiers, machines, and the material catalog, advances the logical clock, rolls billing cycles, and may also register members and assign lockers on a member's behalf.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may be no less than 1, and may be no greater than 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the inclusive range of 1 through 100, or an `offset` below 0, is rejected with `ERR_VALIDATION_LIMIT` (HTTP 400).

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Every primary resource is addressed by an `id` that is a server-minted UUID with no type prefix; clients never supply it. Each such resource also carries a `created_at` timestamp, formatted as an ISO 8601 UTC instant with three fractional digits, recording when it was first created. Most resources additionally carry an `updated_at` timestamp, refreshed on every mutation, and an integer `version` that begins at 1 when the resource is created and increases by exactly 1 on each subsequent mutation.

The one exception is the wallet ledger entry. A `WalletEntry` is an append-only audit record: it carries only an `id` and a `created_at`, and it has neither an `updated_at` nor a `version`, because it is never modified after it is written. Its `created_at` doubles as the append-only ordering key for reconstructing a member's balance history.

Time-dependent rules — certification expiry, reservation windows, billing cycles, and the rolling day-pass window — are all evaluated against a **logical clock**, never against wall-clock time. On startup the clock reads exactly `2026-04-01T00:00:00Z`, and until an operator sets it, every read returns that default rather than falling back to the real time of day. An operator advances the clock by supplying a target instant in the `to_iso8601` field, and the returned `now_utc` reflects the new clock; all later deadline, expiry, and window comparisons use it.

### 2.5. Optimistic Concurrency Control

Two specific writes are exposed to a stale view of a member and therefore require an optimistic-concurrency token. In each case the request body must include `expected_member_version`, carrying the `version` of the target `Member` that the client last observed. The server compares it to that member's current `version`; if they differ, the write is rejected with `ERR_STALE_VERSION` (HTTP 412), and no state changes.

The first guarded write is **assigning a new locker**. A locker's overage quota is keyed to the member's current `locker_free_liters` allowance on their tier; if the member was re-tiered (any mutation that advances `Member.version`) after the client read the member, the client's view of the free-liter quota is stale, and the assignment must be re-derived against the member's current tier rather than the observed one. A mismatch between `expected_member_version` and the member's present `version` yields `ERR_STALE_VERSION` (HTTP 412).

The second guarded write is **confirming a reservation**. Confirmation debits the member's wallet and prepaid minutes, so it depends on the member's balance being exactly what the client believed. Any other wallet-affecting action — a top-up, another confirm, a refund — advances `Member.version`; if `expected_member_version` no longer matches the member's current `version`, the client computed affordability against an outdated balance, and the confirm is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints other than these two take no version field and perform no such check.

### 2.6. Validation Ordering and the Error Precedence Chain

When several checks could fail on a single request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication comes first: a missing or unrecognized header is `ERR_UNAUTHENTICATED` (HTTP 401). Authorization comes next: a role not permitted for the operation, or an entity-backed role reaching another member's resource, is `ERR_FORBIDDEN` (HTTP 403). Existence comes third: every path identifier and every foreign key in the body must resolve to an existing resource, checked left to right, with the first unresolved reference returning `ERR_NOT_FOUND` (HTTP 404). Request well-formedness comes fourth: required fields present, enum values in range, `end_at` strictly after `start_at`, line quantities at least 1, and a non-empty line array — any violation is `ERR_INVALID_REQUEST` (HTTP 422). Optimistic concurrency comes fifth: on the two guarded writes, a stale `expected_member_version` is `ERR_STALE_VERSION` (HTTP 412). Only after these five gates do the state-machine and business rules of §3 apply: an illegal transition for the resource's current state is `ERR_INVALID_STATE` (HTTP 409), and the domain-specific safety, temporal, and fiscal checks described throughout §3 follow in the order their own narratives lay out. This ordering means, for example, that an unauthenticated request to a non-existent reservation is reported as an authentication failure, not a not-found.

### 2.7. Nested Lookup and Foreign-Key Resolution

Although every collection sits at the root of the URL space, many resources reference others by foreign key — a reservation names a `member_id`, a `machine_id`, and (when required) a `certification_id`; a purchase names a `member_id` and a `material_item_id` per line; an enrollment names a `workshop_id` and a `member_id`. Whenever a request carries such references, each is resolved before the operation's business logic runs, and an unresolved reference yields `ERR_NOT_FOUND` (HTTP 404). List endpoints expose these same foreign keys as optional filter parameters so a caller can reverse-reach a parent's children — for instance, filtering reservations by `member_id`, `machine_id`, or `certification_id`; certifications by `member_id` or `machine_class`; wallet entries by `member_id` or `reservation_id`; and so on.

### 2.8. Money, Rounding, and the Wallet Ledger

All money in the system is expressed in integer cents. Every member carries a prepaid `wallet_credit_cents` balance that can never go negative; it is credited by top-ups and refunds and debited by confirmed sessions, subscriptions, day-passes, material purchases, and locker overage. Whenever a charge cannot be covered by the balance — at activation, at reservation confirm, or at material billing — the operation is refused with `ERR_INSUFFICIENT_FUNDS` (HTTP 409).

Wherever a computation produces a fractional cent, the result is rounded to a whole number of cents using the round-half-up convention, and each calculation's narrative in §3 pins exactly where that single rounding step falls. Discounts and basis-point surcharges are expressed in basis points, where 10000 basis points equals the full amount and 1000 basis points equals ten percent.

Every movement of wallet money is mirrored by exactly one append-only `WalletEntry`. Each entry records the owning `member_id`, a `kind` drawn from `TOPUP`, `DEBIT`, `REFUND`, `DAYPASS`, `SUBSCRIPTION`, `MATERIAL`, and `OVERAGE`, a signed `amount_cents` (positive credits the wallet, negative debits it), and a `balance_after_cents` snapshot of `wallet_credit_cents` taken immediately after the entry is applied. When the entry arises from a reservation — that is, when `kind` is `DEBIT` or `REFUND` — it also records the originating `reservation_id`; for all other kinds that field is null.

### 2.9. Hierarchical Consistency and Cascades

Several operations mutate more than one resource. Whenever a write changes a resource, that resource's `updated_at` is refreshed and its `version` is incremented; this is true of the directly targeted resource and of every other resource the operation touches as a side effect. The major cascades — a suspension or cancellation that unwinds a member's open reservations, a certification lapse or revocation that cancels affected future bookings, a workshop completion that resolves stragglers, and a material billing that debits catalog stock — are described in full within the relevant workflow narratives of §3. In every cascade, each affected resource is mutated independently, with its own `updated_at` refresh and `version` bump, and any wallet movement the cascade triggers writes its own `WalletEntry`.

### 2.10. Machine Classes, Enumerations, and Configuration Values

The fleet is partitioned into three machine classes — `LASER`, `CNC`, and `PRINTER_3D` — and certifications, workshops, and reservations are all keyed to one of these classes. Membership tiers declare a `billing_mode` of either `DAYPASS` or `MONTHLY`, and reservations declare a `supervision_mode` of either `SUPERVISED` or `UNSUPERVISED`. Machines declare an `operational_status` of `AVAILABLE` or `OUT_OF_SERVICE`. These exact strings are the only accepted values for their fields, and an out-of-range enum on any create or update is an `ERR_INVALID_REQUEST` (HTTP 422). Uniqueness is enforced on three configuration keys: a duplicate tier `code` is rejected with `ERR_DUPLICATE_TIER_CODE` (HTTP 409), a duplicate material `sku` with `ERR_DUPLICATE_SKU` (HTTP 409), and a member who already holds a non-terminal enrollment in a given workshop cannot enroll twice, which is `ERR_DUPLICATE_ENROLLMENT` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Configuring the Space: Tiers, Machines, and the Material Catalog

Before members can transact, a `FacilityAdmin` lays down the configuration. A **membership tier** is created with a unique `code`, a display `name`, and a `billing_mode`. A tier's commercial parameters are all optional and default to neutral values: `monthly_fee_cents` is the recurring fee for `MONTHLY` tiers (0 for day-pass tiers) and defaults to 0; `daypass_fee_cents` is the per-day-pass price for `DAYPASS` tiers (0 for monthly tiers) and defaults to 0; `discount_bps` is the member's machine-time discount in basis points and defaults to 0, constrained to the inclusive range 0 through 10000; `prepaid_machine_minutes` is the free machine-minute grant refreshed each cycle and defaults to 0; `locker_free_liters` is the free project-storage volume before overage and defaults to 0; and `unsupervised_allowed` declares whether the tier may ever book unsupervised sessions and defaults to false. All of `monthly_fee_cents`, `daypass_fee_cents`, `prepaid_machine_minutes`, and `locker_free_liters` must be non-negative.

A **machine** is created with a `name`, a `machine_class`, and an hourly `hourly_rate_cents`. Optional configuration includes a flat per-session `setup_fee_cents` (default 0), a `min_billing_minutes` floor that guarantees a minimum billable session length regardless of shorter use (default 0), a `cooldown_minutes` buffer used in overlap geometry (default 0), and `requires_certification`, which declares whether a class certification is mandatory to reserve and defaults to true. All four numeric fields must be non-negative. A new machine begins with `operational_status` of `AVAILABLE`; an operator may later flip a machine to `OUT_OF_SERVICE` and back by supplying a new `operational_status`.

A **material catalog item** is created with a unique `sku`, a `name`, a `unit_price_cents` price per unit, and an optional opening `stock_qty` (default 0); both numeric fields must be non-negative.

### 3.2. Joining: Registration, Waiver, Wallet, and Activation

A new **member** is registered — either self-service or by an operator — with an `email`, a `full_name`, and a `tier_id` naming the chosen tier. Registration starts the member in `PENDING_WAIVER` subscription status with `wallet_credit_cents` and `prepaid_minutes_remaining` both 0. The member's `subscription_status` walks the values `PENDING_WAIVER`, `ACTIVE`, `SUSPENDED`, and `CANCELLED`, where `CANCELLED` is terminal.

No one may run a machine until the safety obligation is met. Signing the waiver stamps `waiver_signed_at` with the current logical-clock instant; until then it is null. A member tops up prepaid credit by supplying an `amount_cents`, which increments `wallet_credit_cents` and appends a `WalletEntry` of kind `TOPUP`.

Activation moves the member from `PENDING_WAIVER` to `ACTIVE`. It is permitted only when `waiver_signed_at` is not null — otherwise the request is refused with `ERR_WAIVER_REQUIRED` (HTTP 409) — and when the member's `tier_id` resolves to a real tier. For a `MONTHLY` tier, activation also requires that `wallet_credit_cents` cover the **forward** prorated fee described in §3.9; if it does not, the activation is `ERR_INSUFFICIENT_FUNDS` (HTTP 409). On success, activation sets `cycle_start_at` to the logical-clock now, resets `prepaid_minutes_remaining` to the tier's `prepaid_machine_minutes`, and — for a `MONTHLY` tier only — debits `wallet_credit_cents` by the forward prorated fee and appends a `WalletEntry` of kind `SUBSCRIPTION` whose `balance_after_cents` reflects the new balance.

A member who reaches `ACTIVE` and is later suspended can be reactivated. The `SUSPENDED → ACTIVE` path is permitted only when the member is currently `SUSPENDED` and `waiver_signed_at` is not null; reactivation performs no re-proration and leaves `cycle_start_at` unchanged.

A `FacilityAdmin` may advance a member's billing cycle out of band: rolling the cycle sets `cycle_start_at` to the logical-clock now, resets `prepaid_minutes_remaining` to the tier's `prepaid_machine_minutes`, and resets `daypass_count_window` to 0.

### 3.3. Day-Passes and the Rolling-Window Threshold

A member on a day-pass footing buys access one day at a time. Each purchase increments `daypass_count_window`, debits `wallet_credit_cents` by the tier's `daypass_fee_cents`, and appends a `WalletEntry` of kind `DAYPASS`. The count is governed as a **rolling 30-day window** anchored at the logical clock: `daypass_count_window` reflects the number of day-passes bought in the trailing 30 days. The space caps casual use at three day-passes within that window; a purchase that would be the fourth is blocked with `ERR_CONVERT_TO_MONTHLY` (HTTP 409), nudging the member toward a monthly subscription. The boundary is inclusive of the three already used: the first, second, and third are allowed; the fourth within the window is refused.

### 3.4. Earning Access: Certifications and Readiness

Operating a machine that requires certification demands a current **certification** on that machine's class. Staff may grant one directly by naming the `member_id` and the `machine_class`, optionally supplying `orientation_complete` (default false), `supervised_minutes` already logged (default 0), and `required_supervised_minutes` needed for full readiness (default 0). A new certification starts `ACTIVE`, with `granted_at` set to the logical-clock now and `expires_at` set to exactly 365 days after `granted_at`; the `status` ranges over `ACTIVE`, `EXPIRED`, and `REVOKED`, with `REVOKED` terminal. The same certification is also minted automatically when a member is marked attended at a certifying workshop, as described in §3.8.

Each certification carries a computed `readiness_score` in the closed interval from 0 to 1 that gates unsupervised access. The score is the sum of three weighted components. The first contributes 0.5 when the certification's `status` is `ACTIVE` and 0 otherwise. The second contributes 0.2 when `orientation_complete` is true and 0 otherwise. The third is 0.3 multiplied by the supervised ratio, where the supervised ratio is `supervised_minutes` divided by `required_supervised_minutes`, capped at 1; when `required_supervised_minutes` is 0 the supervised ratio is taken to be 0, contributing nothing. The three components are added and the total is rounded to four decimal places. The score is recomputed whenever the certification is created, renewed, or re-evaluated for expiry, and it is read at reservation confirm time to enforce the unsupervised readiness gate. A certification is ready for unsupervised work when its `readiness_score` is at least 0.8.

Certifications expire on a cycle. Re-evaluating a certification against the logical clock moves it from `ACTIVE` to `EXPIRED` only when it is currently `ACTIVE` and the clock now is at or past its `expires_at`; an attempt to expire a certification whose deadline has not arrived, or that is not `ACTIVE`, is an invalid transition (`ERR_INVALID_STATE`, HTTP 409). When a certification lapses to `EXPIRED`, a cascade fires: every future reservation on the same member and `machine_class` — that is, every reservation whose `start_at` is after the clock now — that is still `HELD` or `CONFIRMED` and was booked `UNSUPERVISED` is cancelled (with the refund treatment of §3.6). Renewing an expired certification moves it from `EXPIRED` back to `ACTIVE`, sets a fresh `granted_at` to the clock now and `expires_at` to 365 days later, and recomputes `readiness_score`. Revoking a certification — permitted from either `ACTIVE` or `EXPIRED` — moves it to `REVOKED` and cancels every `HELD` or `CONFIRMED` reservation on that member and `machine_class`, refunding each hold.

### 3.5. Booking a Machine: Holds, Overlap, and the Reservation Window

A member books a machine by creating a **reservation** that names the `member_id`, the `machine_id`, an optional `certification_id`, a `start_at` and `end_at` window, and a `supervision_mode`. The `certification_id` is the certification relied upon for access; it may be omitted only when the chosen machine's `requires_certification` is false. A new reservation begins `HELD` on its occupancy dimension and `UNBILLED` on its billing dimension, and the server computes `reserved_minutes` as the whole number of minutes from `start_at` (inclusive) to `end_at` (exclusive). The body is rejected with `ERR_INVALID_REQUEST` (HTTP 422) unless `end_at` is strictly after `start_at`.

Reservations track two parallel dimensions that advance independently. The **occupancy_status** runs over `HELD`, `CONFIRMED`, `CHECKED_IN`, `COMPLETED`, `CANCELLED`, and `NO_SHOW`, with `COMPLETED`, `CANCELLED`, and `NO_SHOW` terminal. The **billing_status** runs over `UNBILLED`, `HOLD_PLACED`, `SETTLED`, and `REFUNDED`.

A machine can never be double-booked. At both reservation creation and reservation confirm, the requested window is tested against every other non-terminal reservation on the same machine, and a collision is rejected with `ERR_RESERVATION_OVERLAP` (HTTP 409). The interval geometry depends on the machine's `cooldown_minutes`: when `cooldown_minutes` is 0, the windows are compared as bare half-open intervals (so a reservation ending exactly when another begins does not collide), and when `cooldown_minutes` is positive, each existing window is dilated by that many minutes of mandatory post-session cooldown before the comparison, so a new booking must leave at least that buffer after any neighbor.

### 3.6. Confirming, Releasing, Checking In, and Settling

**Confirming** a reservation is the gate where money and safety meet, and it is the most heavily guarded transition in the system. It moves the reservation from `HELD` to `CONFIRMED` and requires an `expected_member_version` in the body, per the optimistic-concurrency rule of §2.5; a stale value is `ERR_STALE_VERSION` (HTTP 412). The confirm proceeds only when all of the following hold, each with its own rejection: the member's `subscription_status` is `ACTIVE`; the member has signed the waiver, or else `ERR_WAIVER_REQUIRED` (HTTP 409); the machine's `operational_status` is `AVAILABLE`, or else `ERR_MACHINE_OUT_OF_SERVICE` (HTTP 409); if the machine's `requires_certification` is true, a certification on the member and the machine's `machine_class` with `status` of `ACTIVE` exists and is the one named by `certification_id`, or else `ERR_CERTIFICATION_REQUIRED` (HTTP 409); if the `supervision_mode` is `UNSUPERVISED`, the member's tier has `unsupervised_allowed` true and that certification's `readiness_score` is at least 0.8, or else `ERR_READINESS_NOT_MET` (HTTP 409); the window still does not overlap another non-terminal reservation on the machine, or else `ERR_RESERVATION_OVERLAP` (HTTP 409); and finally `wallet_credit_cents` covers the forward estimate computed in this transition, or else `ERR_INSUFFICIENT_FUNDS` (HTTP 409).

On a successful confirm the server computes `estimate_charge_cents` via the **forward** variant of the session-charge calculation in §3.10 on the reserved-window basis, records the `free_minutes_applied` it consumed, debits `wallet_credit_cents` by `estimate_charge_cents`, moves `billing_status` to `HOLD_PLACED`, decrements `prepaid_minutes_remaining` by `free_minutes_applied`, advances `Member.version` by 1, and appends a `WalletEntry` of kind `DEBIT` with a negative `amount_cents` equal to the estimate and the reservation's id in `reservation_id`.

Before the window opens, a member may **release the hold**, moving the reservation from `CONFIRMED` back to `HELD`. This is permitted only while the reservation is `CONFIRMED` and the logical clock now is strictly before `start_at`; releasing after the window has opened is refused as an invalid transition. Releasing refunds `wallet_credit_cents` by `estimate_charge_cents`, sets `billing_status` back to `UNBILLED`, restores `prepaid_minutes_remaining` by `free_minutes_applied`, resets `free_minutes_applied` to 0, and appends a `WalletEntry` of kind `REFUND` with a positive `amount_cents` equal to the estimate and the reservation's `reservation_id`.

**Checking in** moves the reservation from `CONFIRMED` to `CHECKED_IN`. It is permitted only while the reservation is `CONFIRMED` and the logical clock now is at or after `start_at` and strictly before `end_at`; a check-in attempted before the window opens or after it closes is refused with `ERR_WINDOW_NOT_OPEN` (HTTP 409). Check-in stamps `check_in_at` with the clock now.

**Checking out** moves the reservation from `CHECKED_IN` to `COMPLETED`. It stamps `check_out_at` with the clock now, computes `actual_minutes` as the whole minutes from `check_in_at` to `check_out_at`, and computes `final_charge_cents` via the **final** variant of the session-charge calculation on the actual-minutes basis. The wallet is then reconciled by the delta between final and estimate: when `final_charge_cents` exceeds `estimate_charge_cents` the difference is debited, when it is less the difference is refunded, and `billing_status` moves to `SETTLED`. A reconciling `WalletEntry` of kind `DEBIT` or `REFUND` is appended for the delta, and is omitted entirely when the delta is zero.

A member may **cancel** a reservation that is `HELD` or `CONFIRMED`. Cancellation moves `occupancy_status` to `CANCELLED`; if a hold was in place — that is, if `billing_status` is `HOLD_PLACED` — the cancellation refunds `wallet_credit_cents` by `estimate_charge_cents`, restores `prepaid_minutes_remaining` by `free_minutes_applied`, moves `billing_status` to `REFUNDED`, and appends a `WalletEntry` of kind `REFUND` carrying the estimate and the `reservation_id`. When no hold existed, no wallet movement and no ledger entry occur. This same hold-aware refund is the cascade treatment applied whenever a reservation is auto-cancelled by suspension, cancellation of membership, certification lapse, or revocation.

Staff resolve abandoned bookings. **Marking a no-show** moves a reservation from `CONFIRMED` to `NO_SHOW` and is permitted only when the reservation is `CONFIRMED` and the logical clock now is at or after `end_at`. A no-show forfeits the hold: `billing_status` moves to `SETTLED` with no refund, and `final_charge_cents` is set equal to `estimate_charge_cents` so the estimate stands as the final charge.

### 3.7. Lockers and Storage Overage

A member may be assigned a **project locker** by naming the `member_id`, a `label`, a `capacity_liters`, and an optional opening `used_liters` (default 0). Because the locker's overage is keyed to the member's current tier quota, this write is optimistic-concurrency-guarded and must carry `expected_member_version`, per §2.5; a stale value is `ERR_STALE_VERSION` (HTTP 412). A new locker starts `ASSIGNED`, the only non-terminal value of its `status`, which otherwise reaches the terminal `RELEASED`. Both `capacity_liters` and `used_liters` must be non-negative.

The locker's `overage_fee_cents` reflects the storage volume currently stored above the member's free quota. The free volume is the member's tier `locker_free_liters`. The overage liters are the greater of 0 and `used_liters` minus the free volume, and the `overage_fee_cents` is the overage liters multiplied by a flat storage rate of 30 cents per liter. The boundary is exact: when `used_liters` equals the free quota the overage is 0, and when `used_liters` is one liter above the free quota exactly one liter is charged. A member may update a locker's `used_liters`, which recomputes `overage_fee_cents`.

Releasing a locker moves it from `ASSIGNED` to `RELEASED`. If `overage_fee_cents` is greater than 0 at release, the member's `wallet_credit_cents` is debited by `overage_fee_cents` and a `WalletEntry` of kind `OVERAGE` with a negative `amount_cents` is appended; release then sets `used_liters` to 0.

### 3.8. Materials: Drafting, Billing, and Stock

A member assembles a **material purchase** by submitting a `member_id` and a non-empty `lines` array, where each line names a `material_item_id` and a `quantity` of at least 1; an optional order-level `waste_surcharge_bps` (default 0, constrained to 0 through 10000) adds a waste surcharge over the discounted subtotal. An empty `lines` array or a line quantity below 1 is `ERR_INVALID_REQUEST` (HTTP 422). A new purchase starts in `DRAFT`; its `status` ranges over `DRAFT`, `BILLED`, and `VOIDED`, both of the latter terminal. On creation the server computes the purchase's `subtotal_cents`, `surcharge_cents`, and `total_cents` per §3.10.

Billing a draft purchase moves it from `DRAFT` to `BILLED`. It is permitted only when the purchase is `DRAFT`, when every line's `MaterialItem` has a `stock_qty` at least as large as that line's `quantity` — otherwise `ERR_INSUFFICIENT_STOCK` (HTTP 409) — and when the member's `wallet_credit_cents` covers the `total_cents` computed in this transition, otherwise `ERR_INSUFFICIENT_FUNDS` (HTTP 409). On success, billing recomputes `subtotal_cents`, `surcharge_cents`, and `total_cents`, decrements each line's `MaterialItem` `stock_qty` by that line's `quantity`, debits `wallet_credit_cents` by `total_cents`, and appends a `WalletEntry` of kind `MATERIAL` with a negative `amount_cents`. Voiding a draft purchase simply moves it from `DRAFT` to `VOIDED` with no wallet or stock effect.

### 3.9. Workshops and Enrollment

A `StaffInstructor` (or `FacilityAdmin`) creates a **workshop** with a `title`, an optional `machine_class` (set when completing the workshop should certify the attendee, null for non-certifying classes), an `instructor_id` naming the staff member who leads it, a `starts_at` instant, and a `capacity` of at least 1. A workshop starts `OPEN`; its `status` ranges over `OPEN`, `FULL`, `RUNNING`, `COMPLETED`, and `CANCELLED`, with `COMPLETED` and `CANCELLED` terminal. Its computed `enrolled_count` counts enrollments that are `ENROLLED` or `ATTENDED`.

A member enrolls by naming the `workshop_id` and the `member_id`. Enrollment is allowed only while a seat is open — that is, while `enrolled_count` is below `capacity` — otherwise it is refused with `ERR_WORKSHOP_FULL` (HTTP 409); a member already holding a non-terminal enrollment in the same workshop is refused with `ERR_DUPLICATE_ENROLLMENT` (HTTP 409). A new enrollment starts `ENROLLED`; its `status` ranges over `ENROLLED`, `ATTENDED`, `NO_SHOW`, and `WITHDRAWN`, the last three terminal. Creating an enrollment increments the workshop's `enrolled_count`, and when that count reaches `capacity` the workshop auto-transitions from `OPEN` to `FULL`, after which further enrollment attempts are refused as full.

The workshop walks its lifecycle under staff control. Starting a workshop moves it from `OPEN` or `FULL` to `RUNNING`, permitted only when the logical clock now is at or after `starts_at` and the workshop is currently `OPEN` or `FULL`. Completing a workshop moves it from `RUNNING` to `COMPLETED` and, as a cascade, resolves every enrollment still in `ENROLLED` to `NO_SHOW`. Cancelling a workshop moves it from `OPEN` or `FULL` to `CANCELLED` and, as a cascade, moves every `ENROLLED` enrollment to `WITHDRAWN`.

Enrollments resolve through their own transitions, each permitted only from `ENROLLED`. Marking an enrollment attended requires that its parent workshop be `RUNNING` and moves the enrollment to `ATTENDED`; if the workshop's `machine_class` is not null, attendance mints a fresh `Certification` for that member and `machine_class` — `status` `ACTIVE`, `granted_at` set to the clock now, `expires_at` 365 days later, `orientation_complete` set to true — and writes that certification's id into the enrollment's `certification_id`. Marking an enrollment no-show moves it to `NO_SHOW`; this is the same resolution the workshop-completion cascade applies. Withdrawing — a member action — is permitted only while the parent workshop is `OPEN` or `FULL`, moves the enrollment to `WITHDRAWN`, decrements the workshop's `enrolled_count`, and, when the workshop was `FULL` and the count now falls below `capacity`, bubbles the workshop back from `FULL` to `OPEN` so the freed seat becomes bookable again.

### 3.10. Member Lifecycle Endgame: Suspension and Cancellation

A `StaffInstructor` (or `FacilityAdmin`) may **suspend** an `ACTIVE` member, moving them to `SUSPENDED`. Suspension triggers cascade A: every reservation belonging to that member whose `occupancy_status` is `HELD` or `CONFIRMED` is cancelled, and each such cancellation refunds its wallet hold exactly as a direct cancellation would. A suspension attempted on a member who is not `ACTIVE` is an invalid transition (`ERR_INVALID_STATE`, HTTP 409).

A member may **cancel** their membership from `PENDING_WAIVER`, `ACTIVE`, or `SUSPENDED`; `CANCELLED` is terminal. Cancellation cancels every reservation of that member whose `occupancy_status` is `HELD`, `CONFIRMED`, or `CHECKED_IN`, refunding each wallet hold; releases every locker of that member whose `status` is `ASSIGNED`, moving each to `RELEASED`; and, when the subscription was `ACTIVE` or `SUSPENDED` on a `MONTHLY` tier, performs the **chronological** proration accounting of the membership calculation below, crediting `wallet_credit_cents` by the resulting refund and appending a `WalletEntry` of kind `SUBSCRIPTION` with the positive refund amount — omitted entirely when that refund works out to 0.

### 3.11. The Calculations in Detail

**Session charge (forward estimate and final actual).** A session's charge is computed in a fixed order, and the single rounding step falls in exactly one place. The basis is the reserved-window length, `reserved_minutes`, in the forward estimate variant used at confirm, and the real occupancy length, `actual_minutes`, in the final variant used at check-out. The billable minutes are the greater of the basis minutes and the machine's `min_billing_minutes`. The free minutes are the lesser of the billable minutes and the member's `prepaid_minutes_remaining`, and the charged minutes are the billable minutes less the free minutes. The raw time charge is the charged minutes multiplied by the machine's `hourly_rate_cents` and divided by 60 minutes per hour, kept as an exact rational. The tier discount applies to the time charge only: the discounted time charge is the raw time charge multiplied by the quantity (10000 minus the tier's `discount_bps`) and divided by 10000. This discounted time charge is then rounded half-up to whole cents exactly once. Finally the machine's `setup_fee_cents` — which is never discounted — is added after rounding to yield the session charge. In the forward variant this charge is written to `estimate_charge_cents` and held against the wallet; in the final variant it is written to `final_charge_cents`, and the wallet is reconciled by the difference between the final charge and the prior estimate.

**Material billing.** A purchase's total is computed by rounding per line first, then summing, then surcharging, then rounding the surcharge once. For each line, the raw line amount is the line `quantity` multiplied by its `MaterialItem` `unit_price_cents`; the discounted line is that raw amount multiplied by (10000 minus the buyer's tier `discount_bps`) and divided by 10000; and the line's cents are that discounted amount rounded half-up to whole cents. The `subtotal_cents` is the sum of those per-line rounded amounts — the system rounds per line and does not defer rounding to the sum. The `surcharge_cents` is the `subtotal_cents` multiplied by the order's `waste_surcharge_bps`, divided by 10000, and rounded half-up to whole cents. The `total_cents` is the `subtotal_cents` plus the `surcharge_cents`.

**Membership proration (forward and chronological).** The billing cycle is anchored to the member and spans 30 days from `cycle_start_at`. The forward variant, charged once at activation, projects the entire upcoming cycle: the forward amount is the tier's `monthly_fee_cents` for the full month, rounded half-up to whole cents (and because the full cycle is projected, it equals `monthly_fee_cents`). The chronological variant, computed at cancellation, charges only the days actually elapsed. The elapsed days are the whole days from `cycle_start_at` to the logical clock now — the floor of the difference measured in days, never below 0. The used days are the lesser of those elapsed days and 30. The accrued amount is the tier's `monthly_fee_cents` multiplied by the used days, divided by 30, and rounded half-up to whole cents. The refund credited back to the wallet at cancellation is the forward amount minus the accrued amount.

**Certification readiness** is computed exactly as described in §3.4: 0.5 for an `ACTIVE` status, plus 0.2 for completed orientation, plus 0.3 times the capped supervised ratio, summed and rounded to four decimal places, and compared against the gate of 0.8 (at least 0.8 passes).

**Locker overage** is computed exactly as described in §3.7: the overage liters are the greater of 0 and `used_liters` minus the tier's `locker_free_liters`, and the fee is those liters times 30 cents per liter, in whole cents with no rounding required.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including every state-transition and lifecycle action, and the logical-clock and cycle-roll utilities — return `200 OK`. The request body, response body, and side effects of each operation are described in §3; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | FacilityAdmin |
| POST | `/membership-tiers` | Create a membership tier | FacilityAdmin |
| GET | `/membership-tiers/{id}` | Get a membership tier | Member, StaffInstructor, FacilityAdmin |
| GET | `/membership-tiers` | List membership tiers | Member, StaffInstructor, FacilityAdmin |
| POST | `/members` | Register a member (self-service) | Member, FacilityAdmin |
| GET | `/members/{id}` | Get a member | Member, StaffInstructor, FacilityAdmin |
| GET | `/members` | List members | StaffInstructor, FacilityAdmin |
| POST | `/members/{id}/sign-waiver` | Sign the safety waiver | Member |
| POST | `/members/{id}/topup` | Top up wallet credit | Member, FacilityAdmin |
| POST | `/members/{id}/activate` | Activate subscription | Member |
| POST | `/members/{id}/suspend` | Suspend a member | StaffInstructor, FacilityAdmin |
| POST | `/members/{id}/cancel` | Cancel membership | Member |
| POST | `/members/{id}/buy-daypass` | Buy a day-pass | Member |
| POST | `/members/{id}/roll-cycle` | Advance the member's billing cycle | FacilityAdmin |
| GET | `/wallet-entries/{id}` | Get a wallet ledger entry | Member, StaffInstructor, FacilityAdmin |
| GET | `/wallet-entries` | List wallet ledger entries | Member, StaffInstructor, FacilityAdmin |
| POST | `/machines` | Create a machine | FacilityAdmin |
| GET | `/machines/{id}` | Get a machine | Member, StaffInstructor, FacilityAdmin |
| GET | `/machines` | List machines | Member, StaffInstructor, FacilityAdmin |
| POST | `/machines/{id}/set-status` | Set machine operational status | FacilityAdmin |
| POST | `/certifications` | Grant a certification | StaffInstructor, FacilityAdmin |
| GET | `/certifications/{id}` | Get a certification | Member, StaffInstructor, FacilityAdmin |
| GET | `/certifications` | List certifications | Member, StaffInstructor, FacilityAdmin |
| POST | `/certifications/{id}/refresh-expiry` | Re-evaluate expiry against the clock | StaffInstructor, FacilityAdmin |
| POST | `/certifications/{id}/renew` | Renew an expired certification | StaffInstructor, FacilityAdmin |
| POST | `/certifications/{id}/revoke` | Revoke a certification | StaffInstructor, FacilityAdmin |
| POST | `/reservations` | Create a reservation | Member |
| GET | `/reservations/{id}` | Get a reservation | Member, StaffInstructor, FacilityAdmin |
| GET | `/reservations` | List reservations | Member, StaffInstructor, FacilityAdmin |
| POST | `/reservations/{id}/confirm` | Confirm a held reservation | Member |
| POST | `/reservations/{id}/release-hold` | Release a hold before the window opens | Member |
| POST | `/reservations/{id}/check-in` | Check in within the window | Member |
| POST | `/reservations/{id}/check-out` | Check out and settle | Member |
| POST | `/reservations/{id}/cancel` | Cancel a held or confirmed reservation | Member |
| POST | `/reservations/{id}/mark-no-show` | Mark a confirmed reservation no-show | StaffInstructor, FacilityAdmin |
| POST | `/lockers` | Assign a project locker (OCC-guarded) | Member, FacilityAdmin |
| GET | `/lockers/{id}` | Get a locker | Member, StaffInstructor, FacilityAdmin |
| GET | `/lockers` | List lockers | Member, StaffInstructor, FacilityAdmin |
| PATCH | `/lockers/{id}` | Update locker stored volume | Member |
| POST | `/lockers/{id}/release` | Release a locker and bill overage | Member |
| POST | `/material-items` | Create a material catalog item | FacilityAdmin |
| GET | `/material-items/{id}` | Get a material item | Member, StaffInstructor, FacilityAdmin |
| GET | `/material-items` | List material items | Member, StaffInstructor, FacilityAdmin |
| POST | `/material-purchases` | Create a draft material purchase | Member |
| GET | `/material-purchases/{id}` | Get a material purchase | Member, StaffInstructor, FacilityAdmin |
| GET | `/material-purchases` | List material purchases | Member, StaffInstructor, FacilityAdmin |
| POST | `/material-purchases/{id}/bill` | Bill a draft purchase | Member |
| POST | `/material-purchases/{id}/void` | Void a draft purchase | Member |
| POST | `/workshops` | Create a workshop | StaffInstructor, FacilityAdmin |
| GET | `/workshops/{id}` | Get a workshop | Member, StaffInstructor, FacilityAdmin |
| GET | `/workshops` | List workshops | Member, StaffInstructor, FacilityAdmin |
| POST | `/workshops/{id}/start` | Start a workshop | StaffInstructor |
| POST | `/workshops/{id}/complete` | Complete a workshop | StaffInstructor |
| POST | `/workshops/{id}/cancel` | Cancel a workshop | StaffInstructor, FacilityAdmin |
| POST | `/workshop-enrollments` | Enroll a member in a workshop | Member |
| GET | `/workshop-enrollments/{id}` | Get an enrollment | Member, StaffInstructor, FacilityAdmin |
| GET | `/workshop-enrollments` | List enrollments | Member, StaffInstructor, FacilityAdmin |
| POST | `/workshop-enrollments/{id}/mark-attended` | Mark an enrollment attended | StaffInstructor |
| POST | `/workshop-enrollments/{id}/mark-no-show` | Mark an enrollment no-show | StaffInstructor |
| POST | `/workshop-enrollments/{id}/withdraw` | Withdraw from a workshop | Member |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_WAIVER_REQUIRED` | 409 |
| `ERR_CERTIFICATION_REQUIRED` | 409 |
| `ERR_READINESS_NOT_MET` | 409 |
| `ERR_RESERVATION_OVERLAP` | 409 |
| `ERR_CONVERT_TO_MONTHLY` | 409 |
| `ERR_WORKSHOP_FULL` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_INSUFFICIENT_FUNDS` | 409 |
| `ERR_MACHINE_OUT_OF_SERVICE` | 409 |
| `ERR_DUPLICATE_ENROLLMENT` | 409 |
| `ERR_DUPLICATE_TIER_CODE` | 409 |
| `ERR_DUPLICATE_SKU` | 409 |
| `ERR_WINDOW_NOT_OPEN` | 409 |
| `ERR_VALIDATION_LIMIT` | 400 |
