# Public Broadcasting Membership & Pledge API — Product Requirements Document

## 1. Introduction

A public broadcasting member station lives and dies by two intersecting calendars: the on-air pledge drive calendar and the fiscal-year compliance calendar. During a drive, phone volunteers take pledge calls, donors pick thank-you gifts (premiums) from a finite inventory, and challenge sponsors watch a progress bar hoping their match will unlock. After the drive ends, the membership team follows up on unfulfilled pledges, ships premiums, writes off bad debt, and then must produce a CSG/CPB Non-Federal Financial Support (NFFS) report that accurately separates membership revenue from underwriting and recognizes matching gifts at the right moment.

This document specifies the REST API backing those operations. It covers membership level and premium configuration, pledge drive scheduling with on-air break programming, pledge capture across phone and web channels, premium reservation and fulfillment, payment posting with a multi-level cascade into membership renewal and donor statistics, lapsed-member win-back, matching challenge progression, underwriting credit attribution, and the NFFS reporting workflow with its segregation-of-duties finalize step.

Two design commitments shape the entire specification. First, **auditability over convenience**: every derived number (drive totals, donor lifetime giving, challenge progress, NFFS revenue) is a deterministic roll-up of source records, and every compensating reversal (decline, write-off, premium waiver) is spelled out. Second, **segregation of duties**: volunteers capture pledges and post payments, coordinators manage donors/inventory/write-offs/NFFS drafts, and only station administrators finalize NFFS reports and control the drive schedule. The logical clock is explicit so that membership expiry, grace windows, and lapse transitions can be driven deterministically by tests.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a role the server does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A recognized role attempting an operation outside its grant is rejected with `ERR_UNAUTHORIZED` (HTTP 403). The full role-to-endpoint grant appears in §4.

Three roles exist, spelled exactly:

- `StationAdmin` — the station general manager / development director. Owns membership level and premium configuration, the pledge drive lifecycle (create/schedule/unschedule/go-live/close), on-air break scheduling, matching challenge and underwriting credit creation, NFFS report finalization and amendment, and the logical clock.
- `MembershipCoordinator` — the membership manager. Owns donor CRM, premium inventory lot receipt, premium reservation/shipment/waiver/release, pledge write-off, lapsed-member reinstatement, drive reconciliation, and NFFS report drafting.
- `PhoneVolunteer` — a phone-bank volunteer. Captures pledges (PHONE channel) and posts payments against them, and may decline pledges. Also shares donor registration and membership opening with the coordinator.

All three roles have `identity: opaque`: `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it (for example, as `drafted_by_user_id` and `finalized_by_user_id` on an `NFFSReport`) but does not compare it to any entity's `id` for ownership purposes.

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

Requests to an unknown path, and requests using an unsupported method on a defined path, are rejected in this same envelope with `ERR_NOT_FOUND` (HTTP 404); any other unhandled server fault surfaces as `ERR_INVALID_REQUEST` (HTTP 400).

### 2.3. Pagination

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, has a minimum of 1 and a maximum of 100. `offset` defaults to 0. A non-integer `limit` or `offset`, a `limit` outside [1, 100], or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (400). The response `meta` block carries `limit`, `offset`, `total_count`, and `has_more` for every list response, where `has_more` is true exactly when `offset` plus the number of items in the returned page is less than `total_count`. Default sort order across all list endpoints is `created_at` ascending, breaking ties by `id` ascending; no list endpoint in this API takes a custom sort parameter.

### 2.4. Common Resource Properties and Identifier Conventions

Every entity in this API carries the four common fields unless explicitly noted otherwise:

- `id` — a server-minted UUID. The UUID has no type prefix (no `donor_`, `pledge_`, etc.).
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set at creation and never mutated.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the entity, including mutations that arrive via cross-entity cascades.
- `version` — an integer starting at 1 on creation and incremented by exactly 1 on every mutation of the entity, again including cascade-driven mutations. OCC (§2.7) is implemented against this field.

### 2.5. Hierarchical Consistency and Cascading Side Effects

Several aggregates maintain derived totals that are cascaded from child-row mutations. When any cascade writes to an entity, that entity's `version` increments and its `updated_at` refreshes — even when the primary operation was against a different aggregate. The specific cascade rules appear in §3, but the invariant is stated here: any field documented as `computed` in the entity model is server-maintained, and every server maintenance event is a mutation for the purposes of `version` and `updated_at`.

Nested path parameters are validated left-to-right. For example, scheduling a break under `/station/pledge-drives/{drive_id}/breaks` first checks that `drive_id` resolves to an existing drive (else `ERR_NOT_FOUND`), then proceeds to the operation. Releasing a reservation under `/station/premium-reservations/{id}/release` resolves the reservation before evaluating its state.

### 2.6. Money, Precision, and Rounding

All monetary values are integer cents. The fields `amount_cents`, `net_collected_cents`, `collected_cents`, `goal_cents`, `match_cents`, `progress_cents`, `pledged_cents`, `unit_cost_cents`, `total_qty`, `min_annual_cents`, `min_monthly_sustainer_cents`, `fair_market_value_cents`, `lifetime_given_cents`, `membership_revenue_cents`, `underwriting_excluded_cents`, and `matching_revenue_cents` are integer cents throughout the API.

When a calculation cannot avoid a fractional intermediate (specifically, the weighted-average variant of premium inventory valuation), the final value is rounded half-up to whole integer cents. Aggregate roll-ups (drive totals, NFFS revenue, challenge progress) are per-pledge integers first, then summed — never averaged-then-rounded. There are no decimal-place outputs anywhere in the API.

### 2.7. Optimistic Concurrency Control

Two write endpoints enforce optimistic concurrency. Both require a non-optional expected-version field in the request body; if the supplied value does not equal the parent entity's current `version`, the request is rejected with the rule's declared error and HTTP status.

- **Break scheduling against a drive** requires `expected_drive_version` carrying the client's last observed `version` of the target `PledgeDrive`. A mismatch is rejected with `ERR_STALE_DRIVE_VERSION` (HTTP 412). This guards against the case where another scheduler has just modified the drive (added breaks, rescheduled) and the current writer's overlap-check baseline is stale.
- **Payment posting against a pledge** requires `expected_pledge_version` carrying the client's last observed `version` of the target `Pledge`. A mismatch is rejected with `ERR_STALE_PLEDGE_VERSION` (HTTP 412). This guards against the case where a prior payment posting or a cascade from a premium reservation has already advanced the pledge's version, leaving the stale writer's over-payment check computed against the wrong baseline.

Endpoints not listed above do not take a version field. Reads always return the current `version`, and the value the client supplies on a subsequent write must be the value it last read. In the validation order of §2.9, the version check is evaluated after path-resource existence and target-state validation and before the remaining business-rule checks (for example, before the break-overlap check on break scheduling and before the payment-amount bounds check on payment posting).

### 2.8. The Logical Clock

The server maintains a logical UTC clock used for every time-dependent rule: drive window checks, break scheduling, membership period transitions, the 30-day grace window, and the 60-day write-off window. At startup the clock reads exactly `2026-08-01T00:00:00Z`; before any set call it never falls back to wall-clock time. Every timestamp the server emits — entity `created_at`/`updated_at` and the response-meta `api_request_timestamp` — is stamped from this logical clock. A station admin can advance the clock via a test-driving capability that takes a `to_iso8601` timestamp; the setter accepts any timestamp (the server does not enforce forward-only movement), and crossing a membership boundary triggers the membership status transitions described in §3.4, which never revert.

### 2.9. Validation Ordering

When multiple validations could fire on the same request, they are evaluated in a strict priority order so that the surfaced error is deterministic. The order, from first-evaluated to last-evaluated, is:

1. Request body well-formedness → `ERR_INVALID_REQUEST` (400). A body that is not a parseable JSON object is rejected before any other check, including authentication. Field-level validation (missing fields, wrong types, malformed enums, `ends_at` not strictly after `starts_at`) is evaluated after steps 2–3, and its relative order against the existence checks of step 4 is endpoint-specific; one endpoint-specific exception is the break-creation `pitch_level_code` existence check (§3.3), which is evaluated after the drive-state check of step 5.
2. Authentication headers present and role recognized → `ERR_UNAUTHENTICATED` (401).
3. Role authorized for the endpoint per §4 → `ERR_UNAUTHORIZED` (403).
4. Path-referenced resources exist, validated left-to-right → `ERR_NOT_FOUND` (404). For pledge capture, the body-referenced resources are existence-checked in the order: donor, membership, drive, on-air break, matching challenge, premium.
5. Target resource state permits the operation (generic) → `ERR_INVALID_STATE` (409). Pledge capture against a drive not `ON_AIR` is the one exception and yields the more specific `ERR_DRIVE_NOT_OPEN` (409).
6. Segregation of duties on NFFS finalize → `ERR_SEGREGATION_OF_DUTIES` (422).
7. On-air break fits within the drive window and respects the 5-minute buffer → `ERR_BREAK_OVERLAP` (422).
8. Write-off follow-up window (60 days) has elapsed → `ERR_WRITEOFF_WINDOW` (422).
9. Pledge cross-reference belonging checks (membership belongs to donor, break belongs to drive, challenge belongs to drive) → `ERR_CROSS_REFERENCE` (422).
10. Referenced matching challenge is `OPEN` → `ERR_CHALLENGE_NOT_OPEN` (409).
11. Pledge amount qualifies for level, premium tier eligible, premium active → `ERR_LEVEL_OR_PREMIUM_INELIGIBLE` (422).
12. Payment amount within bounds → `ERR_PAYMENT_AMOUNT` (422).
13. Drive scheduling overlap with another `SCHEDULED` or `ON_AIR` drive → `ERR_DRIVE_OVERLAP` (422).
14. Drive reconcile requires all pledges resolved → `ERR_UNRESOLVED_PLEDGES` (422).

The ordering matters most when a pledge capture could fail several checks at once: a request missing its auth header must surface `ERR_UNAUTHENTICATED`, never `ERR_DRIVE_NOT_OPEN`, even if the drive is also closed; and a pledge capture against a closed drive with a challenge that is `MET` surfaces `ERR_DRIVE_NOT_OPEN`, not `ERR_CHALLENGE_NOT_OPEN`.

## 3. Business Logic & Workflows

### 3.1. Configuring Levels and Premiums

Before any drive can run, a `StationAdmin` configures the membership catalogue. A `MembershipLevel` is created with a unique `code` (immutable after creation), a `min_annual_cents` threshold for one-time pledges, a `min_monthly_sustainer_cents` threshold for sustainer pledges — both thresholds are required non-negative integers (0 is allowed) — an optional `premium_eligible` flag defaulting to true, and an optional `active` flag defaulting to true. Levels can be listed with an optional `active` filter, which takes the query value `true` or `false` (case-insensitive); any other value is rejected with `ERR_INVALID_REQUEST` (400). An attempt to create a level whose `code` is already in use is rejected with `ERR_DUPLICATE_CODE` (409).

Premiums are the thank-you gifts donors select at capture. A `Premium` is created with a unique immutable `sku`, a `title`, a `fair_market_value_cents` (the per-unit value that will be deducted from the pledge for IRS quid-pro-quo purposes; a required non-negative integer), the `membership_level_code` of the lowest level at which the premium may be offered, and an optional `active` flag defaulting to true. A duplicate `sku` is rejected with `ERR_DUPLICATE_CODE`. A `membership_level_code` that does not resolve to an existing level is rejected with `ERR_NOT_FOUND` (404). The level-rank comparison used for premium eligibility ranks levels by `min_annual_cents`, breaking ties by `code` ascending.

Inventory arrives in lots. A `MembershipCoordinator` receives a `PremiumInventoryLot` for a premium, supplying `received_at`, `unit_cost_cents` (a non-negative integer), and `total_qty` (at least 1). The lot is initialized with `available_qty` equal to `total_qty`, and `reserved_qty`, `committed_qty`, and `written_off_qty` all at 0. The `available_qty` is server-maintained thereafter as `total_qty` minus `reserved_qty` minus `committed_qty` minus `written_off_qty` and never goes negative.

### 3.2. Donor Registration and Membership Lifecycle

Donors are the people on the other end of the phone. A donor is registered with `email` (unique, case-insensitive), `full_name`, and `postal_code`. A duplicate email, compared case-insensitively, is rejected with `ERR_DUPLICATE_CODE` (409). The server maintains `lifetime_given_cents` (sum of `net_collected_cents` over the donor's pledges whose `payment_status` is `PAID` or `PARTIAL`) and `lapse_count` (the number of times any of the donor's memberships has entered `LAPSED`).

A membership is opened for a donor at a level, optionally flagged `sustainer` (default false). The opening request supplies `donor_id` and `level_code`, with `level_code` referencing the `code` of an existing membership level. A `donor_id` or `level_code` that does not resolve is rejected with `ERR_NOT_FOUND` (404). New memberships are initialized with `status` set to `ACTIVE`, `current_period_start` set to the current logical time, and `current_period_end` also set to the current logical time — a zero-length paid-through window that the first payment will extend. The membership's `status` field is one of `ACTIVE`, `GRACE`, `LAPSED`, or `REINSTATED_PENDING`, and it cycles: `ACTIVE` → `GRACE` → `LAPSED` → `REINSTATED_PENDING` → `ACTIVE`.

### 3.3. Drive Scheduling and On-Air Programming

A `StationAdmin` builds a drive by first creating a `PledgeDrive` in `DRAFT` status, supplying `name`, `starts_at` (inclusive), `ends_at` (exclusive, strictly after `starts_at`), and `goal_cents` (a required non-negative integer). The drive's `pledged_cents` and `collected_cents` start at 0 and are server-maintained.

Breaks are scheduled against a drive that is in `DRAFT` or `SCHEDULED` status; once the drive is `ON_AIR`, `CLOSED`, or `RECONCILED` the break lineup is frozen and break creation is rejected with `ERR_INVALID_STATE`. Each break specifies `starts_at`, `ends_at`, `program_title`, and `pitch_level_code`, and must fall within the drive window — its `starts_at` at or after the drive's `starts_at` and its `ends_at` at or before the drive's `ends_at`; an out-of-window break is rejected with `ERR_BREAK_OVERLAP` (422). A `pitch_level_code` that does not resolve to an existing membership level is rejected with `ERR_INVALID_REQUEST` (400), and this check is evaluated after the drive-state check. The breaks of a single drive are half-open intervals `[starts_at, ends_at)` with a mandatory 5-minute buffer to any other break in the same drive: a break A starting at exactly break B's `ends_at` plus 5 minutes is allowed, but anything closer is rejected with `ERR_BREAK_OVERLAP` (422). Break creation also requires `expected_drive_version` matching the drive's current `version`, per §2.7; on success the drive's `version` increments.

When at least one break exists in `SCHEDULED` status, the drive can be moved `DRAFT` → `SCHEDULED`. At schedule time the server checks that no other drive in `SCHEDULED` or `ON_AIR` status overlaps the half-open `[starts_at, ends_at)` window; a drive ending exactly when another starts is allowed, but any real overlap is rejected with `ERR_DRIVE_OVERLAP` (422). Unscheduling returns the drive from `SCHEDULED` to `DRAFT`; the breaks stay in place and remain editable.

When the logical clock reaches the drive's `starts_at`, the drive can go live: `SCHEDULED` → `ON_AIR`. From this point pledge capture endpoints accept pledges for the drive. Closing the drive moves it `ON_AIR` → `CLOSED`, at which point three cascades fire: further pledge capture is rejected with `ERR_DRIVE_NOT_OPEN`; every `OnAirBreak` still in `SCHEDULED` transitions to `AIRED`; and every `MatchingChallenge` still in `OPEN` transitions to `EXPIRED` (status latched; its `progress_cents` may still be decremented by later compensating reversals per §3.9). Finally, once every pledge of the drive has reached a terminal payment state (`PAID`, `DECLINED`, or `WRITTEN_OFF` — no `PLEDGED` or `PARTIAL` remaining), a `MembershipCoordinator` reconciles the drive: `CLOSED` → `RECONCILED`, freezing totals for NFFS reporting. A reconcile attempt while any pledge is unresolved is rejected with `ERR_UNRESOLVED_PLEDGES` (422).

### 3.4. Membership Period Transitions and the Lapsed-Member Cycle

Membership period transitions are driven by the logical clock, not by wall-clock time. When the clock reaches or passes a membership's `current_period_end`, the membership moves `ACTIVE` → `GRACE`, opening a 30-day grace window. When the clock reaches or passes `current_period_end` plus 30 days, the membership moves `GRACE` → `LAPSED` and the donor's `lapse_count` increments by 1. A single clock advance that crosses both boundaries moves the membership directly from `ACTIVE` to `LAPSED` and increments `lapse_count` once. Clock advances do not affect `REINSTATED_PENDING` memberships, and clock-driven transitions never revert.

The lapsed-member campaign workflow starts from a `LAPSED` membership. A `MembershipCoordinator` moves it `LAPSED` → `REINSTATED_PENDING`, which is the win-back pending state awaiting a payment. When any payment is then posted against a pledge linked to the membership, the membership moves `REINSTATED_PENDING` → `ACTIVE`, `current_period_start` is set to the current logical time, `current_period_end` is set to 12 months after that, and the donor's `lapse_count` resets to 0.

Payments against an already-`ACTIVE` membership extend it without changing status: a `ONE_TIME` payment extends `current_period_end` by exactly 12 months from the later of the existing `current_period_end` and the payment time; a `SUSTAINER` installment extends it by exactly 1 month from the same baseline. Month arithmetic is calendar-based, clamping the day-of-month to the target month's length when necessary. This "max of current period end and now" rule prevents a late payment from losing paid-through time. A payment posted while the membership is in `GRACE` moves it back to `ACTIVE`, sets `current_period_start` to the payment time, and applies the same extension rule to `current_period_end`.

### 3.5. Pledge Capture Across Channels

Pledges are captured by a `PhoneVolunteer` (or, for `WEB` channel, by the same role acting on behalf of the web flow). Capture takes `donor_id`, `membership_id`, `drive_id`, optional `on_air_break_id`, optional `matching_challenge_id`, `channel` (exactly `PHONE` or `WEB`), `kind` (exactly `ONE_TIME` or `SUSTAINER`), `amount_cents` (at least 1), optional `premium_id`, and optional `premium_waived` (default false).

Several cross-reference checks fire at capture, in the priority order of §2.9: the `membership_id` must belong to the `donor_id`; the `on_air_break_id`, when present, must belong to the `drive_id`; the `matching_challenge_id`, when present, must belong to the `drive_id`. Any mismatch is `ERR_CROSS_REFERENCE` (422). The break reference is validated for existence and drive membership only — the break's own status and airtime window are not consulted — and the membership's status is not checked at capture. A challenge reference also requires the challenge to be in `OPEN` status; a challenge that is `MET` or `EXPIRED` rejects with `ERR_CHALLENGE_NOT_OPEN` (409).

The amount must qualify for the pledge's level and premium tier per the `membership_level_for_amount` rule. For a `ONE_TIME` pledge, the annualized amount is simply the `amount_cents`; for a `SUSTAINER` pledge, the annualized amount is `amount_cents` multiplied by 12. The level check passes when a `SUSTAINER` pledge's `amount_cents` is at least the level's `min_monthly_sustainer_cents`, or a `ONE_TIME` pledge's annualized amount is at least the level's `min_annual_cents`. The premium check passes when no premium was selected, or when the level is `premium_eligible` and the level's rank is at least the rank of the premium's `membership_level_code` (rank by `min_annual_cents`, tie-break by `code` ascending). The premium must also be `active`. A failure here is `ERR_LEVEL_OR_PREMIUM_INELIGIBLE` (422).

Inventory availability is deliberately **not** checked at capture. A capture that selects a premium with no stock simply lands in `fulfillment_status` `AWAITING_RESERVATION`; availability is enforced only on the explicit reservation endpoint (§3.6). Capture-time fulfillment status is set as follows: when `premium_waived` is true, `fulfillment_status` becomes `WAIVED`, whether or not a premium was selected; when no premium was selected and `premium_waived` is false, it becomes `NO_PREMIUM`; when a premium was selected, not waived, and stock is available (some lot of the premium has `available_qty` at least 1), an automatic `PremiumReservation` for quantity 1 is created in `HELD` status against the FIFO-first eligible lot (`received_at` ascending, tie-break `created_at` ascending), that lot's `reserved_qty` increments by 1 and `available_qty` decrements by 1, and the pledge's `fulfillment_status` becomes `RESERVED`; otherwise it becomes `AWAITING_RESERVATION`. The pledge's `payment_status` starts at `PLEDGED`, and its `collected_cents` and `net_collected_cents` start at 0. A `SUSTAINER` pledge also flips the linked membership's `sustainer` flag to true.

Every capture increments the drive's `pledged_cents` by the pledge's `amount_cents`. When a `matching_challenge_id` is present, the challenge's `progress_cents` increments by the same `amount_cents`, and the threshold rule runs (§3.7).

### 3.6. Premium Reservation, Shipping, and Waiver

When a pledge's `fulfillment_status` is `AWAITING_RESERVATION`, a `MembershipCoordinator` can explicitly reserve inventory. The reservation record carries `pledge_id` (the pledge it fulfills), `premium_id` (which must equal the pledge's `premium_id`), `lot_id`, and `quantity`. The create request supplies `quantity` (at least 1) and optionally `lot_id`. When `lot_id` is omitted the server selects the lot deterministically: eligible lots are those of the pledge's `premium_id` with `available_qty` at least `quantity`; ranking is by `received_at` ascending, tie-break by `created_at` ascending; an empty candidate set is rejected with `ERR_INSUFFICIENT_INVENTORY` (422). An exact-zero `available_qty` rejects. An explicit `lot_id` that does not resolve to an existing lot is rejected with `ERR_NOT_FOUND` (404); an explicit lot that stocks a different premium than the pledge's, or whose `available_qty` is below `quantity`, is rejected with `ERR_INSUFFICIENT_INVENTORY` (422). Reservation also requires the pledge's premium to still be `active`; an inactive premium is rejected with `ERR_LEVEL_OR_PREMIUM_INELIGIBLE` (422). The reservation is created in `HELD` status, the lot's `reserved_qty` increments by `quantity`, `available_qty` decrements by `quantity`, the pledge's `fulfillment_status` moves to `RESERVED`, and the pledge's `net_collected_cents` is recomputed (premium FMV is now deductible). The drive's `collected_cents` and the donor's `lifetime_given_cents` are resynced by the net delta.

Once a pledge is fully paid (`payment_status` is `PAID`), the premium ships. Shipping moves the pledge's `fulfillment_status` `RESERVED` → `SHIPPED` and the reservation `HELD` → `COMMITTED`, transferring the quantity from the lot's `reserved_qty` to its `committed_qty` (the lot's `available_qty` is unchanged). Shipping before full payment is rejected with `ERR_INVALID_STATE` (409).

A donor who calls back to decline the gift triggers a waiver: `AWAITING_RESERVATION` or `RESERVED` → `WAIVED`. The pledge's `premium_waived` flag is set to true. If the pledge was in `RESERVED`, the reservation transitions to `RELEASED`, the lot's `reserved_qty` decrements, and `available_qty` increments by the same amount. The pledge's `net_collected_cents` is recomputed with the premium FMV no longer deducted, and the drive and donor totals resync by the net delta. A `MembershipCoordinator` can also release a `HELD` reservation directly — for example when the donor changed their mind before shipment — which moves the reservation `HELD` → `RELEASED`, compensates the lot counters, and drops the parent pledge's `fulfillment_status` back to `AWAITING_RESERVATION`.

Reservation, ship, and waive operations on a pledge with no premium selected — one whose `fulfillment_status` is `NO_PREMIUM` or already `WAIVED` — are rejected with `ERR_PREMIUM_NOT_SELECTED` (422).

### 3.7. Matching Challenge Progress and Latching

A `StationAdmin` creates a `MatchingChallenge` against a drive, supplying `sponsor_name`, `goal_cents`, and `match_cents` (both at least 1). Challenge creation is not restricted by the drive's status. The challenge starts `OPEN` with `progress_cents` at 0.

Progress is a derived sum over the challenge's non-terminal pledges: the sum of `amount_cents` over pledges whose `matching_challenge_id` is this challenge and whose `payment_status` is neither `DECLINED` nor `WRITTEN_OFF`. The threshold rule fires when an `OPEN` challenge's `progress_cents` reaches or exceeds the `goal_cents` — a pledge landing exactly on the goal flips the challenge. At that point the challenge transitions to `MET` and stays there: the status is latched and never reverts, even if a subsequent decline or write-off pulls the progress back below the goal. Challenge `MET` is the moment the sponsor's `match_cents` becomes recognizable as NFFS matching revenue at the next report compute.

### 3.8. Payment Posting and the Three-Deep Cascade

A `PhoneVolunteer` posts a payment against a pledge, supplying `amount_cents` (at least 1) and `expected_pledge_version` per §2.7. For a `ONE_TIME` pledge the payment must not exceed the remaining balance; an over-payment is rejected with `ERR_PAYMENT_AMOUNT` (422). For a `SUSTAINER` pledge the payment must not exceed the pledge's `amount_cents` (the per-installment amount); an over-installment payment is likewise rejected with `ERR_PAYMENT_AMOUNT` (422). A payment against a pledge in a terminal payment state (`DECLINED` or `WRITTEN_OFF`) is rejected with `ERR_INVALID_STATE` (409). A `SUSTAINER` pledge additionally requires its linked membership to be in `ACTIVE` or `GRACE` status.

The pledge's `payment_status` moves from `PLEDGED` toward `PAID` or `PARTIAL`: for a `ONE_TIME` pledge it becomes `PAID` once `collected_cents` reaches the pledge's `amount_cents` and `PARTIAL` otherwise; for a `SUSTAINER` pledge any successful payment sets it to `PAID`, and subsequent installments keep it `PAID`. The pledge's `collected_cents` increments by the payment amount, `net_collected_cents` is recomputed per the rule below, and the drive's `collected_cents` increments by the resulting net delta.

The cascade then runs three levels deep. The linked membership's `current_period_end` extends by 12 months (for a `ONE_TIME` payment) or 1 month (for a `SUSTAINER` installment), measured from the later of the existing `current_period_end` and the payment time. If the membership was `LAPSED`, it moves through `REINSTATED_PENDING` to `ACTIVE`, and the donor's `lapse_count` resets to 0. The donor's `lifetime_given_cents` resyncs by the net delta. A successful payment also increments the pledge's `version` by 1.

The `net_collected_cents` rule runs on every payment posting, premium reservation, premium waiver, decline, or write-off affecting a pledge. The FMV deduction is 0 unless three things are all true: the pledge has a `premium_id`, the pledge's `fulfillment_status` is `RESERVED` or `SHIPPED`, and `premium_waived` is false. When all three hold, the deduction is the premium's `fair_market_value_cents` multiplied by the reserved quantity (the quantity on the active reservation, whether `HELD` or `COMMITTED`). The result is the pledge's `collected_cents` minus the deduction, floored at 0. Two variants matter for downstream reporting: when the premium is selected, not waived, and fulfillment is `RESERVED` or `SHIPPED`, the donor-facing tax receipt shows the reduced deductible amount; otherwise net equals gross collected.

### 3.9. Decline and Write-Off: Compensating Reversals

A pledge that fails to collect goes through one of two terminal transitions. **Decline** is the immediate path: a `PhoneVolunteer` moves a pledge from `PLEDGED` or `PARTIAL` to `DECLINED`, supplying a `reason` which is recorded as `decline_reason`. **Write-off** is the follow-up path: after the 60-day unfulfilled-pledge follow-up window has elapsed (the current logical time is at least the pledge's `created_at` plus 60 days), a `MembershipCoordinator` moves the pledge to `WRITTEN_OFF`, again supplying a `reason`, likewise recorded as `decline_reason`. A write-off attempted before the window elapses is rejected with `ERR_WRITEOFF_WINDOW` (422).

Both transitions fire the same compensating-reversal cascade. The drive's `pledged_cents` decrements by the pledge's `amount_cents`. The drive's `collected_cents` decrements by the pledge's `net_collected_cents`. When a `matching_challenge_id` is present, the challenge's `progress_cents` decrements by the pledge's `amount_cents` — but the challenge status is latched, so a `MET` or `EXPIRED` challenge does not revert. When the pledge's `fulfillment_status` was `RESERVED`, the reservation transitions to `RELEASED` and the lot's counters compensate (the `reserved_qty` decrements and `available_qty` increments by the reservation quantity). The donor's `lifetime_given_cents` decrements by the pledge's `net_collected_cents`. Each entity touched by the cascade increments its own `version` and refreshes `updated_at`.

### 3.10. Underwriting Credits

Underwriting revenue is contract revenue, not membership revenue, and is therefore excluded from NFFS membership totals. A `StationAdmin` records an `UnderwritingCredit` against a drive, supplying `underwriter_name`, `amount_cents` (at least 1), and an optional `aired` flag defaulting to false. Credits may be recorded against a drive in any status. Only credits with `aired` true count toward drive revenue reporting; the NFFS report (§3.11) reads them through the `underwriting_excluded_cents` line.

### 3.11. NFFS Reporting and Segregation of Duties

A `MembershipCoordinator` drafts an NFFS report for a fiscal year by supplying `fiscal_year`. The draft is created in `DRAFT` status with `variant` `PROVISIONAL`, the `drafted_by_user_id` set to the requesting `X-User-ID`, and the `membership_revenue_cents`, `underwriting_excluded_cents`, and `matching_revenue_cents` computed under the provisional variant.

The fiscal year window is pinned as the half-open calendar interval from January 1 of the named fiscal year at 00:00:00 UTC through January 1 of the following year at 00:00:00 UTC — a pledge counts toward FY 2026 when its drive's `starts_at` falls within that window.

The membership revenue line has two variants that share the same per-pledge-then-sum rounding order. Under the **PROVISIONAL** variant (the variant on `DRAFT` and `AMENDED` reports), the total is the sum over all pledges in the fiscal year of: the pledge's `amount_cents` minus its FMV deduction when `payment_status` is `PLEDGED`; the pledge's `net_collected_cents` when `payment_status` is `PAID` or `PARTIAL`; and zero when `payment_status` is `DECLINED` or `WRITTEN_OFF`. Under the **FINAL** variant (the variant on `FINALIZED` reports), only actually-collected revenue counts: the sum includes a pledge's `net_collected_cents` only when `payment_status` is `PAID` or `PARTIAL`, and `PLEDGED` pledges contribute zero. The same drive totals therefore yield a strictly smaller-or-equal number under FINAL than under PROVISIONAL.

The matching revenue line sums `match_cents` over all matching challenges in `MET` status whose drive's `starts_at` falls within the fiscal year window. The underwriting line sums `amount_cents` over all underwriting credits with `aired` true whose drive's `starts_at` falls within the window, and is reported separately — never added into membership revenue.

Finalization moves the report `DRAFT` → `FINALIZED`, flips the variant to `FINAL`, recomputes all three revenue lines from current records (membership revenue under the FINAL variant; the underwriting and matching lines are variant-independent), and stamps `finalized_by_user_id` from the requesting `X-User-ID`. The finalizer must differ from the drafter: if the same `X-User-ID` attempts to finalize a report it drafted, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (422). This is the audit control that prevents one person from both preparing and attesting the same NFFS report. Reads return the stored lines; totals are recomputed only at draft, finalize, and amend time, so a report does not reflect pledges, credits, or challenges recorded after its last compute.

Amendment re-opens a `FINALIZED` report to `AMENDED` status, returning the variant to `PROVISIONAL`, recomputing the three revenue lines under that variant, and retaining the prior `finalized_by_user_id`. Re-finalizing from `AMENDED` is allowed and follows the same rule: the variant flips back to `FINAL`, totals are recomputed, and the segregation-of-duties check still applies against the original `drafted_by_user_id`.

### 3.12. Premium Inventory Valuation

At fiscal-year close (and whenever a lot is written off) the station must value its premium inventory for CSG asset reporting. Two variants exist. Both are offline reporting calculations: this API exposes no valuation endpoint and no lot write-off operation, so a lot's `written_off_qty` remains 0 throughout.

The **FIFO** variant is the default for CSG reporting: lots are consumed in chronological order, sorted by `received_at` ascending with tie-break by `created_at` ascending. To value a quantity of units, the algorithm walks the lots in that order, taking from each lot the lesser of the remaining quantity to value and that lot's `available_qty` plus `reserved_qty`, accumulating the taken quantity times the lot's `unit_cost_cents`, until the full quantity is priced.

The **weighted-average** variant is the alternative management view: the total remaining value across all lots of the premium (each lot contributing its `available_qty` plus `reserved_qty`, multiplied by its `unit_cost_cents`) divided by the total remaining quantity, then multiplied by the quantity being valued, with the final result rounded half-up to whole cents. The same write-off quantity yields a different cent value under the two variants whenever lots have different unit costs.

## 4. Endpoint Definitions

All endpoints are mounted under `/station`. A `POST` that creates a new resource returns HTTP 201 with the created resource in `data`. A `POST` that transitions or modifies an existing resource returns HTTP 200 with the updated resource in `data`, with one exception: posting a payment (`POST /station/pledges/{id}/payments`) returns HTTP 201 with the updated pledge even though it creates no new resource. All `GET` requests return HTTP 200. Error responses use the envelope in §2.2 with the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/station/membership-levels` | Create a membership level | StationAdmin |
| GET | `/station/membership-levels` | List membership levels | StationAdmin, MembershipCoordinator, PhoneVolunteer |
| POST | `/station/premiums` | Create a premium (thank-you gift) definition | StationAdmin |
| GET | `/station/premiums/{id}` | Get a premium | StationAdmin, MembershipCoordinator, PhoneVolunteer |
| POST | `/station/premiums/{id}/lots` | Receive an inventory lot for a premium | MembershipCoordinator |
| GET | `/station/premiums/{id}/lots` | List lots of a premium | StationAdmin, MembershipCoordinator |
| POST | `/station/donors` | Register a donor | MembershipCoordinator, PhoneVolunteer |
| GET | `/station/donors/{id}` | Get a donor | StationAdmin, MembershipCoordinator, PhoneVolunteer |
| GET | `/station/donors/{id}/memberships` | List memberships of a donor | StationAdmin, MembershipCoordinator, PhoneVolunteer |
| POST | `/station/memberships` | Open a membership for a donor at a level | MembershipCoordinator, PhoneVolunteer |
| GET | `/station/memberships/{id}` | Get a membership | StationAdmin, MembershipCoordinator, PhoneVolunteer |
| POST | `/station/memberships/{id}/reinstate` | Move a LAPSED membership to REINSTATED_PENDING | MembershipCoordinator |
| GET | `/station/memberships` | List memberships with filters (`status`, `donor_id`, `sustainer`) | StationAdmin, MembershipCoordinator |
| POST | `/station/pledge-drives` | Create a pledge drive (DRAFT) | StationAdmin |
| GET | `/station/pledge-drives/{id}` | Get a pledge drive with computed totals | StationAdmin, MembershipCoordinator, PhoneVolunteer |
| POST | `/station/pledge-drives/{id}/breaks` | Schedule an on-air break inside a drive (OCC on drive version) | StationAdmin |
| GET | `/station/pledge-drives/{id}/breaks` | List breaks of a drive | StationAdmin, MembershipCoordinator, PhoneVolunteer |
| POST | `/station/pledge-drives/{id}/schedule` | Move drive DRAFT → SCHEDULED | StationAdmin |
| POST | `/station/pledge-drives/{id}/unschedule` | Move drive SCHEDULED → DRAFT | StationAdmin |
| POST | `/station/pledge-drives/{id}/go-live` | Move drive SCHEDULED → ON_AIR | StationAdmin |
| POST | `/station/pledge-drives/{id}/close` | Move drive ON_AIR → CLOSED; cascades breaks to AIRED and challenges to EXPIRED | StationAdmin |
| POST | `/station/pledge-drives/{id}/reconcile` | Move drive CLOSED → RECONCILED once all pledges resolved | MembershipCoordinator |
| POST | `/station/pledges` | Capture a pledge (phone or web) | PhoneVolunteer |
| GET | `/station/pledges/{id}` | Get a pledge | StationAdmin, MembershipCoordinator, PhoneVolunteer |
| GET | `/station/pledges` | List pledges with filters (`donor_id`, `drive_id`, `membership_id`, `matching_challenge_id`, `on_air_break_id`, `premium_id`, `payment_status`, `fulfillment_status`) | StationAdmin, MembershipCoordinator, PhoneVolunteer |
| POST | `/station/pledges/{id}/payments` | Post a payment against a pledge (OCC on pledge version) | PhoneVolunteer |
| POST | `/station/pledges/{id}/decline` | Decline a pledge | PhoneVolunteer |
| POST | `/station/pledges/{id}/write-off` | Write off an unfulfilled pledge after the 60-day follow-up window | MembershipCoordinator |
| POST | `/station/pledges/{id}/premium-reservations` | Reserve premium inventory for a pledge in AWAITING_RESERVATION | MembershipCoordinator |
| GET | `/station/pledges/{id}/premium-reservations` | List reservations of a pledge | StationAdmin, MembershipCoordinator |
| GET | `/station/premium-reservations/{id}` | Get a premium reservation | StationAdmin, MembershipCoordinator |
| GET | `/station/premium-reservations` | List premium reservations with filters (`pledge_id`, `premium_id`, `lot_id`, `status`) | StationAdmin, MembershipCoordinator |
| POST | `/station/pledges/{id}/ship-premium` | Mark premium shipped; requires pledge PAID | MembershipCoordinator |
| POST | `/station/pledges/{id}/waive-premium` | Waive premium after capture | MembershipCoordinator |
| POST | `/station/premium-reservations/{id}/release` | Manually release a HELD reservation | MembershipCoordinator |
| POST | `/station/pledge-drives/{id}/matching-challenges` | Create a matching challenge within a drive | StationAdmin |
| GET | `/station/pledge-drives/{id}/matching-challenges` | List challenges of a drive | StationAdmin, MembershipCoordinator, PhoneVolunteer |
| GET | `/station/matching-challenges/{id}` | Get a matching challenge with progress | StationAdmin, MembershipCoordinator, PhoneVolunteer |
| POST | `/station/pledge-drives/{id}/underwriting-credits` | Record an underwriting credit for a drive | StationAdmin |
| GET | `/station/pledge-drives/{id}/underwriting-credits` | List underwriting credits of a drive | StationAdmin, MembershipCoordinator |
| POST | `/station/nffs-reports` | Draft an NFFS report for a fiscal year | MembershipCoordinator |
| GET | `/station/nffs-reports/{id}` | Get an NFFS report | StationAdmin, MembershipCoordinator |
| POST | `/station/nffs-reports/{id}/finalize` | Finalize an NFFS report (segregation of duties enforced) | StationAdmin |
| POST | `/station/nffs-reports/{id}/amend` | Re-open a FINALIZED report for amendment | StationAdmin |
| POST | `/station/_clock/set_current_utc` | Advance the logical clock | StationAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DRIVE_NOT_OPEN` | 409 |
| `ERR_STALE_DRIVE_VERSION` | 412 |
| `ERR_STALE_PLEDGE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_BREAK_OVERLAP` | 422 |
| `ERR_DRIVE_OVERLAP` | 422 |
| `ERR_WRITEOFF_WINDOW` | 422 |
| `ERR_CROSS_REFERENCE` | 422 |
| `ERR_LEVEL_OR_PREMIUM_INELIGIBLE` | 422 |
| `ERR_PAYMENT_AMOUNT` | 422 |
| `ERR_INSUFFICIENT_INVENTORY` | 422 |
| `ERR_PREMIUM_NOT_SELECTED` | 422 |
| `ERR_UNRESOLVED_PLEDGES` | 422 |
| `ERR_DUPLICATE_CODE` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CHALLENGE_NOT_OPEN` | 409 |
