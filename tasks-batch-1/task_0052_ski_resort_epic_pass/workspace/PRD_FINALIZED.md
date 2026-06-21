# Ski Resort Epic Pass API — Product Requirements Document

## 1. Introduction

The Ski Resort Epic Pass API powers a multi-resort season-pass network in which a single piece of pass media carries a skier across many mountains for an entire season. The business problem it solves is the coordination of three traditionally siloed concerns into one access-control fabric: deciding in real time whether a pass may open a lift gate, tracking the finite perks (buddy tickets) that a pass grants, and reconciling the money owed back to a holder who leaves the season early. Gates operate in a "scan-and-go" fashion, so every access decision must be computed deterministically from the pass, the product it was sold under, the resort it is presented at, and the recent scanning history — there is no human in the loop at the turnstile.

Several cross-cutting realities shape the design. Each pass carries a server-minted magnetic anti-counterfeit token that must be re-presented at every scan, defeating cloned media. Tiered products gate access by date through blackout calendars, while a premium tier overrides those calendars entirely. An anti-passback cooldown stops a single pass from being passed back over a fence to a second skier within a few minutes. Cross-network interoperability lets eligible products scan at partner IKON-home resorts up to a contractually capped number of distinct days. Finally, the network must honor end-of-season refunds whose payout depends on how lightly the pass was used and why the holder is leaving. Because the same pass can be scanned, suspended, refunded, and auto-expired by the seasonal clock, the system treats consistency between a pass and its dependent buddy tickets as a first-class invariant.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting operator, and `X-User-Role`, which declares the capacity in which they are acting. If either header is absent, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_AUTH_MISSING`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly three peer roles, spelled `NetworkAdmin`, `ResortOps`, and `RefundAdmin`. A `NetworkAdmin` administers the network itself: resorts, pass products, interchange agreements, and the system clock. A `ResortOps` operator works the mountain — issuing and activating passes, running lift scans, and managing buddy tickets. A `RefundAdmin` is the back-office processor who opens, approves, and rejects refund requests. The opening of a refund request is shared: a `ResortOps` or a `RefundAdmin` may both create one. All three roles may perform any read (`GET`) operation.

For all three roles, `X-User-ID` is an opaque operator identifier and is not tied to any persisted entity. When `X-User-Role` is `NetworkAdmin`, `ResortOps`, or `RefundAdmin`, the server treats `X-User-ID` purely as the caller's identity for authentication; it does not compare that value to any entity's `id`, and there is no resource-ownership check that maps a resource's foreign key back to `X-User-ID`. Authorization is therefore governed entirely by role, not by identity.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a single response returns; when omitted it defaults to 10, and a supplied value must be at least 1 and at most 100. The `offset` parameter is the number of leading items to skip; when omitted it defaults to 0.

Unless an endpoint states otherwise, every list is sorted by the resource's creation timestamp in ascending order. List responses surface their pagination state inside the `meta` object using exactly these fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in the network — resorts, pass products, passes, buddy tickets, refund requests, and interchange agreements — carry a common set of system-managed fields. Each receives an `id` formatted as a UUID with no type prefix, a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits, an `updated_at` timestamp in the same format that is refreshed on every mutation, and an integer `version` that begins at its initial value and increments by one each time the resource is mutated.

The lift-scan record is the one exception. A `LiftScan` is an immutable audit row: once written it is never modified. It therefore carries only an `id` (UUID) and a `created_at` timestamp; it has neither an `updated_at` field nor a `version` field. Every other resource type carries the full common set described above.

### 2.5. Nested Resource Retrieval and Reference Validation

Many read endpoints address a resource through a parent in the path — for example, listing the scans for a particular pass, or the buddy tickets valid at a particular resort. For any request whose path or body names other resources, the server validates those references left-to-right and rejects the first one that does not resolve with `ERR_NOT_FOUND`. The reference order across the domain is Pass, Resort, PassProduct, BuddyTicket, RefundRequest, then InterchangeAgreement. A request naming a pass that does not exist therefore fails before any nested or body-referenced resort, product, or ticket is even examined.

Every creating or transitioning request is also subject to a body-validity check: all required body fields must be present and well-typed — for instance the `tier` and `price_cents` of a product, the `pass_product_id` and `holder_name` of a pass, the `presented_token` and `resort_id` of a scan, the `reason` of a refund request, the `valid_date` of a buddy ticket, and the `max_interchange_days` of an interchange agreement. A request with a missing or wrongly typed required field is rejected with `ERR_VALIDATION`. This validation is evaluated across all checks in a fixed priority order: header authentication comes first (`ERR_AUTH_MISSING`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of referenced resources (`ERR_NOT_FOUND`), then body-field validity (`ERR_VALIDATION`), and only then the per-operation business and state rules described in §3.

### 2.6. Mutation Cascades and Version Semantics

Whenever an operation changes a resource, that resource's `updated_at` is refreshed and its `version` is incremented by one. Several operations on a pass cascade into its dependent buddy tickets, and each such cascade is itself a mutation: when a pass is suspended, refunded, or auto-expired, every buddy ticket of that pass that is still in `RESERVED` is moved to `CANCELLED`, the pass's `buddy_tickets_remaining` figure is recomputed, and the pass's `version` advances by one. A granted scan likewise mutates the pass — its `scan_count` advances and its `version` increments. These propagations are immediate and consistent: a read of the pass after any such event reflects the new counts and the new version with no deferral.

### 2.7. Monetary Precision and the Refund Rounding Rule

All money in the system is expressed in whole integer cents — sticker prices, per-buddy-ticket charges, the refund basis, and computed refund payouts are all integers. Refund payouts are the only computed monetary figure, and their rounding order is pinned: the proration fraction and the processing-fee factor are multiplied against the basis as exact rational arithmetic, and the round-half-up rounding to a whole number of cents is applied exactly once, to the final cents value. Rounding the proration and the fee in separate steps is explicitly disallowed, because the two orderings can diverge by a cent.

### 2.8. Anti-Counterfeit Tokens and the Scan Decision Pipeline

The defining safety control of the network is the magnetic anti-counterfeit token. When a pass is issued, the server mints a unique `magnetic_token` and prints it on the media; at every gate the scanned `presented_token` must equal that stored token. The token check is the highest-priority rule in the scan decision and is evaluated ahead of pass state, resort state, anti-passback, interchange, and blackout. A separate temporal safeguard, the anti-passback window, prevents the same pass from being reused at the same resort in quick succession. The interchange controls govern whether a pass may scan at a partner network's home resort at all. The precise ordering and arithmetic of all of these checks is specified in §3.3, but their priority relationship is fixed and is summarized again there.

### 2.9. Optimistic Concurrency on Refund Approval

Exactly one write in the system carries an optimistic-concurrency guard: the approval of a refund request. An approval request must carry `expected_pass_version`, a non-optional field holding the `version` of the target pass that the approver last observed. The server compares it against the referenced pass's current `version`; if they do not match — for instance because a granted scan advanced the pass's `scan_count` and bumped its `version` after the approver loaded it — the approval is rejected with `ERR_STALE_VERSION` and HTTP status 412, because the approver's view of the pass, and therefore of its refund eligibility, is stale. No other endpoint accepts or requires a version field, and no other endpoint performs this check.

## 3. Business Logic & Workflows

### 3.1. Configuring the Network: Resorts, Products, and Interchange Agreements

A `NetworkAdmin` lays down the network's static configuration before any pass is sold. Creating a resort requires a `name` and optionally accepts `home_network` and `gate_count`. The `home_network` declares which pass network owns the resort outright and is one of `EPIC` or `IKON`, defaulting to `EPIC` when omitted. The `gate_count` is the number of physical lift gates that can scan passes there; it must be at least 1 and defaults to 1 when omitted. A freshly created resort begins in `status` `OPEN`. A resort may later be suspended, transitioning its `status` from `OPEN` to `SUSPENDED`, after which its gates stop granting scans; the suspend capability is reserved to the `NetworkAdmin`.

Pass products define the marketable tiers. Creating one requires a `tier` and a `price_cents`, and optionally accepts `blackout_dates`, `buddy_ticket_allotment`, `buddy_ticket_price_cents`, and `ikon_interchange_enabled`. The `tier` is one of `LOCAL`, `EPIC_DAY`, or `FULL_EPIC`, and it must be unique across all pass products — an attempt to create a second product with a tier that already exists is rejected with `ERR_DUPLICATE_TIER`. The `price_cents` is the sticker price in cents and must be at least 0. The `blackout_dates` field is a list of ISO calendar dates in `YYYY-MM-DD` form on which holders of non-`FULL_EPIC` products may not scan; it defaults to an empty list and is ignored entirely for `FULL_EPIC` products. The `buddy_ticket_allotment` is how many buddy tickets each pass of the product grants for the season (at least 0, default 0), `buddy_ticket_price_cents` is the per-buddy-ticket charge (at least 0, default 0), and `ikon_interchange_enabled` is a boolean — default `false` — controlling whether the product's passes may scan at IKON-home resorts via interchange.

Interchange agreements bind the network to honor cross-network scans at a specific partner resort. A `NetworkAdmin` creates one by supplying the `resort_id` of the IKON-home resort that will honor interchange scans and a `max_interchange_days`, the cap (at least 1) on the number of distinct granted interchange scan-days a single pass may use at that resort across the season. A new agreement begins in `status` `ACTIVE` and may later be terminated, moving its `status` from `ACTIVE` to `TERMINATED`; termination is a `NetworkAdmin` capability.

### 3.2. Issuing and Activating a Pass

A `ResortOps` operator issues a pass against a product by submitting the `pass_product_id` of the product and the `holder_name` of the person it is for. On issuance the server mints a unique `magnetic_token` and the pass is created in `status` `ISSUED`. At this point its computed fields sit at their initial values: `scan_count` is 0, `buddy_tickets_remaining` is 0, `refund_basis_cents` is 0, and `activated_on` is unset.

A pass cannot be scanned, nor can it grant any buddy ticket benefits, until it is activated. Activation is a `ResortOps` action that serves double duty. Moving a pass from `ISSUED` to `ACTIVE` is first activation: it is permitted only when the pass is currently `ISSUED`, and on success it sets `activated_on` to the current clock instant in UTC, copies the referenced product's `price_cents` into the pass's `refund_basis_cents`, and sets `buddy_tickets_remaining` to the product's `buddy_ticket_allotment`. The same action also reinstates a suspended pass: moving a pass from `SUSPENDED` back to `ACTIVE` is permitted only when the pass is currently `SUSPENDED`, and on reinstatement `activated_on` and `refund_basis_cents` are left exactly as they were at first activation — they are not recomputed — and buddy tickets that were previously cancelled are not restored. Either form of activation increments the pass's `version` by one. Attempting to activate a pass that is in neither `ISSUED` nor `SUSPENDED` is rejected as an invalid state transition with `ERR_INVALID_STATE`.

Suspension is the mirror action and is also reserved to `ResortOps`. Moving a pass from `ACTIVE` to `SUSPENDED` is permitted only when the pass is currently `ACTIVE`. Suspension cascades: every buddy ticket of the pass that is still `RESERVED` is moved to `CANCELLED`, the pass's `buddy_tickets_remaining` is recomputed accordingly, and the pass's `version` increments by one. A suspend attempt on a pass that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`. The terminal states of a pass are `REFUNDED` and `EXPIRED`, reached respectively by refund approval (§3.5) and by the seasonal clock (§3.6).

### 3.3. Scan-and-Go Lift Access

Presenting a pass at a gate is a `ResortOps` operation that creates a `LiftScan` and always records an outcome — it never silently succeeds or fails. The request supplies the `resort_id` of the scanning resort and the `presented_token` read off the media; the pass itself is identified by the path. The server stamps the scan with `scan_at`, the UTC instant copied from the system clock, and derives `scan_date`, the `YYYY-MM-DD` calendar date used for blackout checks, from that instant. It then computes a `result` of either `GRANTED` or `DENIED`. When the result is `DENIED`, the record also carries a `denial_reason`, one of `TOKEN_MISMATCH`, `NOT_ACTIVE`, `RESORT_SUSPENDED`, `ANTI_PASSBACK`, `NO_INTERCHANGE`, or `BLACKOUT`; when the result is `GRANTED`, `denial_reason` is null. The fields stored on each scan are the presenting `pass_id`, the `resort_id`, the `presented_token`, the `scan_at` instant, the `scan_date`, the `result`, and the `denial_reason`.

The access decision evaluates a fixed sequence of rules; the first rule that fails sets the `denial_reason` and short-circuits, so later rules are not consulted. **First**, the anti-counterfeit check: if the `presented_token` is not equal to the pass's `magnetic_token`, the scan is denied with reason `TOKEN_MISMATCH`. This is the highest-priority rule and is also surfaced to the caller as `ERR_TOKEN_MISMATCH`. **Second**, the pass must be `ACTIVE`; if it is in any other state the scan is denied with reason `NOT_ACTIVE`. **Third**, the resort must be `OPEN`; if it is `SUSPENDED` the scan is denied with reason `RESORT_SUSPENDED`. **Fourth**, the anti-passback window: if there exists a prior `GRANTED` scan for this same pass at this same resort whose `scan_at` falls within the cooldown ending strictly before the current `scan_at`, the scan is denied with reason `ANTI_PASSBACK`. The cooldown is five minutes, evaluated in whole minutes as a half-open window — that is, a prior grant is blocking when the elapsed time from it to the current scan is zero or more minutes and strictly fewer than five minutes; a prior grant exactly five minutes earlier no longer blocks. Anti-passback denial is surfaced as `ERR_ANTI_PASSBACK`.

The remaining two rules depend on the resort's network. **Fifth**, interchange: when the scanning resort's `home_network` is `IKON`, the scan is treated as a cross-network interchange and three conditions must all hold — the product's `ikon_interchange_enabled` must be true, an `ACTIVE` interchange agreement must exist for that resort, and the number of distinct prior interchange scan-days this pass has already used at this resort must be strictly fewer than that agreement's `max_interchange_days`. If any of the three fails, the scan is denied with reason `NO_INTERCHANGE` and surfaced as `ERR_INTERCHANGE_DENIED`; if all three hold the scan is granted. The count of distinct interchange days is the number of distinct `scan_date` values among the `GRANTED` scans already recorded for this pass at this resort, not counting the current scan. **Sixth**, blackout: this rule applies only when the resort's `home_network` is `EPIC`, after anti-passback has passed. `FULL_EPIC` products ignore blackout dates entirely and are always granted at this stage; for any other tier, if the scan's `scan_date` is one of the product's `blackout_dates` the scan is denied with reason `BLACKOUT`. A scan that survives all applicable rules is granted.

When a scan is granted, the pass is mutated: its `scan_count` increases by one (the live count of granted scans for that pass) and its `version` increments by one. A denied scan still produces a persisted `LiftScan` row recording the denial, but it does not advance `scan_count` or the pass's `version`. The denial-bearing rules — token, anti-passback, and interchange — each both write the `DENIED` record and return their corresponding error code, so a caller learns the specific reason a gate refused entry.

### 3.4. Buddy Tickets: Allotment, Redemption, and Conflicts

Buddy tickets let a pass holder bring guests, drawing against the finite allotment their product granted. A `ResortOps` operator reserves one by submitting the host `pass_id`, the `resort_id` the ticket is valid at, the `guest_name` of the guest who will use it, and the `valid_date` (a `YYYY-MM-DD` calendar date) it is good for. On reservation the ticket is created in `status` `RESERVED`, its `price_charged_cents` is copied from the host product's `buddy_ticket_price_cents`, and the host pass's `buddy_tickets_remaining` is recomputed downward to reflect the newly consumed slot.

Two guardrails protect reservation. A pass may not over-issue: reserving a ticket requires the host pass to have at least one buddy slot left, meaning its `buddy_tickets_remaining` must be 1 or greater; a reservation against an exhausted allotment is rejected with `ERR_BUDDY_ALLOTMENT_EXHAUSTED`. Separately, the same guest may not be double-booked: a `guest_name` may not hold two non-`CANCELLED` buddy tickets for the same `valid_date` at the same `resort_id`. A reservation that would collide with an existing `RESERVED` or `REDEEMED` ticket for that same guest, date, and resort is rejected with `ERR_BUDDY_DATE_CONFLICT`; this is a same-calendar-day collision and is unrelated to the minute-based anti-passback window.

The remaining-allotment figure is defined precisely: it is the product's `buddy_ticket_allotment` minus the count of this pass's buddy tickets whose `status` is `RESERVED` or `REDEEMED`. Tickets in `CANCELLED` are excluded from that count and therefore do not consume allotment; the count is order-independent and has no time window. This same definition is what is recomputed on reservation, on cancellation, on redemption-adjacent activity, and by the pass cascades.

A reserved ticket can move in two directions, both `ResortOps` actions. Redeeming it transitions it from `RESERVED` to `REDEEMED`; redemption is permitted only when the ticket is currently `RESERVED` and additionally requires the host pass to be `ACTIVE` at that moment — a cross-entity guard. A redeemed ticket keeps its allotment slot consumed. Cancelling a ticket transitions it from `RESERVED` to `CANCELLED`; cancellation is permitted only when the ticket is currently `RESERVED`, frees the consumed slot by recomputing the host pass's `buddy_tickets_remaining` upward, and increments the ticket's `version` by one. Redemption likewise increments the ticket's `version` by one. Attempting either transition on a ticket that is not `RESERVED` is rejected with `ERR_INVALID_STATE`. Beyond the explicit cancel action, a ticket also reaches `CANCELLED` indirectly whenever its host pass is suspended, refunded, or auto-expired — those pass-level events cancel all of the pass's still-`RESERVED` tickets as described in §3.2, §3.5, and §3.6. The terminal states of a buddy ticket are `REDEEMED` and `CANCELLED`.

### 3.5. End-of-Season Refunds

A refund request is opened against a pass by either a `ResortOps` or a `RefundAdmin` operator, who supplies the host `pass_id` and a `reason` — one of `INJURY`, `RELOCATION`, or `DISSATISFIED`. On creation the request enters `status` `PENDING`, and the system snapshots the pass's current `scan_count` into the request's `scan_count_at_request`. This snapshot, captured at request time, is what the payout calculation later consumes — never the live `scan_count`, which may drift if the pass keeps scanning while the request sits pending. A new request's `refund_amount_cents` is 0 until it is decided.

Only a `RefundAdmin` may decide a pending request. Approval is the system's deepest cascade and is gated by four checks. The generic state check requires the request to be `PENDING`; a non-pending request is rejected with `ERR_INVALID_STATE`. The eligibility check requires the referenced pass to be `ACTIVE` and its current `scan_count` to be at most ten; if the pass is not `ACTIVE`, or if it has been scanned more than ten times, approval is rejected with `ERR_REFUND_INELIGIBLE` — this is treated as a referential/usage failure distinct from the plain state check, because an `ACTIVE` but heavily used pass is ineligible for a reason other than its state. The optimistic-concurrency check requires the submitted `expected_pass_version` to equal the pass's current `version`, failing with `ERR_STALE_VERSION` (HTTP 412) otherwise. These checks are evaluated in priority order: header authentication first, then role authorization, then existence of the referenced resources, then the body-validity check, then the request's `PENDING` state, then refund eligibility, and finally the stale-version comparison. Placing eligibility ahead of the version check ensures an ineligible refund surfaces as `ERR_REFUND_INELIGIBLE` on its own terms.

On a successful approval the request's `refund_amount_cents` is set by the payout calculation, the request moves from `PENDING` to `APPROVED`, and the referenced pass cascades from `ACTIVE` to `REFUNDED`. That pass transition itself cancels every still-`RESERVED` buddy ticket of the pass and recomputes the pass's `buddy_tickets_remaining`, and the pass's `version` increments by one. Rejection is the simpler outcome: a `RefundAdmin` rejecting a `PENDING` request moves it from `PENDING` to `REJECTED`, sets its `refund_amount_cents` to 0, leaves the pass entirely untouched, and increments the request's `version` by one. The terminal states of a refund request are `APPROVED` and `REJECTED`.

The payout itself is computed from two inputs: the basis, which is the pass's `refund_basis_cents`, and the used count, which is the request's `scan_count_at_request` snapshot. The shape of the calculation depends on the `reason`. For an `INJURY` refund, usage is not penalized at all: the payout is ninety percent of the basis, rounded half up to whole cents. For a `RELOCATION` or `DISSATISFIED` refund, the payout prorates by the unused share of a ten-scan budget and then deducts a ten-percent processing fee, with both factors applied before a single rounding step. Concretely, if the snapshot used count is ten or more, the payout is 0; otherwise the unused fraction is the quantity ten minus the used count, divided by ten, and the payout is the basis multiplied by that unused fraction and then multiplied by nine-tenths (that is, one minus the ten-percent processing-fee rate), with the round-half-up rounding applied exactly once to the resulting cents value. The ten-scan figure is the same maximum-scans threshold that gates refund eligibility, so a pass scanned more than ten times is already ineligible before this branch is reached, while a pass at exactly ten scans is eligible but, under the proration branch, yields a payout of 0.

### 3.6. The Seasonal Clock and Auto-Expiry

A `NetworkAdmin` holds an administrative test-driving capability that sets the system clock to a supplied instant. The submitted instant, `to_iso8601`, becomes the clock that subsequent scans copy into `scan_at` and from which `scan_date` is derived, so advancing the clock is how a test or an operator moves the network through the season.

Advancing the clock has a deferred consequence at season's end. When the clock is set to a date later than the configured season-end date, every pass that is currently `ACTIVE` auto-transitions from `ACTIVE` to `EXPIRED`. Each such auto-expiry is a system-actor transition that cascades exactly like a suspension or refund: every still-`RESERVED` buddy ticket of the expiring pass moves to `CANCELLED`, the pass's `buddy_tickets_remaining` is recomputed, and the pass's `version` increments by one. `EXPIRED` is a terminal state for the pass. Because expiry is keyed strictly to the clock crossing the season-end boundary, no pass expires while the clock remains on or before that boundary date.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`; this covers creating resorts, pass products, passes, buddy tickets, refund requests, and interchange agreements, as well as recording a lift scan (each scan creates a new `LiftScan` row even when its result is a denial). Operations that modify or transition an existing resource — activating, suspending, redeeming, cancelling, approving, rejecting, terminating, suspending a resort — return `200 OK`, as do all reads and the clock-setting capability. Request bodies, response bodies, and side effects are intentionally omitted from the table below; reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/resorts` | Create a resort | NetworkAdmin |
| GET | `/resorts` | List resorts (optional `home_network` filter) | NetworkAdmin, ResortOps, RefundAdmin |
| GET | `/resorts/{id}` | Read a resort | NetworkAdmin, ResortOps, RefundAdmin |
| POST | `/resorts/{id}/suspend` | Suspend a resort | NetworkAdmin |
| POST | `/pass-products` | Create a pass product / tier configuration | NetworkAdmin |
| GET | `/pass-products` | List pass products (optional `tier` filter) | NetworkAdmin, ResortOps, RefundAdmin |
| GET | `/pass-products/{id}` | Read a pass product | NetworkAdmin, ResortOps, RefundAdmin |
| POST | `/passes` | Issue a pass under a product | ResortOps |
| GET | `/passes` | List passes (optional `pass_product_id` filter) | NetworkAdmin, ResortOps, RefundAdmin |
| GET | `/passes/{id}` | Read a pass | NetworkAdmin, ResortOps, RefundAdmin |
| POST | `/passes/{id}/activate` | Activate an ISSUED pass or reinstate a SUSPENDED pass | ResortOps |
| POST | `/passes/{id}/suspend` | Suspend an ACTIVE pass | ResortOps |
| POST | `/passes/{id}/scan` | Present a pass at a resort gate; records a LiftScan | ResortOps |
| POST | `/buddy-tickets` | Reserve a buddy ticket against a host pass's allotment | ResortOps |
| GET | `/buddy-tickets` | List buddy tickets (optional `pass_id` filter) | NetworkAdmin, ResortOps, RefundAdmin |
| GET | `/buddy-tickets/{id}` | Read a buddy ticket | NetworkAdmin, ResortOps, RefundAdmin |
| POST | `/buddy-tickets/{id}/redeem` | Redeem a reserved buddy ticket | ResortOps |
| POST | `/buddy-tickets/{id}/cancel` | Cancel a reserved buddy ticket | ResortOps |
| POST | `/refund-requests` | Open a refund request against a pass | ResortOps, RefundAdmin |
| GET | `/refund-requests` | List refund requests (optional `pass_id` filter) | NetworkAdmin, ResortOps, RefundAdmin |
| GET | `/refund-requests/{id}` | Read a refund request | NetworkAdmin, ResortOps, RefundAdmin |
| POST | `/refund-requests/{id}/approve` | Approve a pending refund; computes payout and refunds the pass | RefundAdmin |
| POST | `/refund-requests/{id}/reject` | Reject a pending refund | RefundAdmin |
| POST | `/interchange-agreements` | Create an IKON interchange agreement | NetworkAdmin |
| GET | `/interchange-agreements` | List interchange agreements (optional `resort_id` filter) | NetworkAdmin, ResortOps, RefundAdmin |
| GET | `/interchange-agreements/{id}` | Read an interchange agreement | NetworkAdmin, ResortOps, RefundAdmin |
| POST | `/interchange-agreements/{id}/terminate` | Terminate an interchange agreement | NetworkAdmin |
| GET | `/passes/{id}/lift-scans` | List lift scans for a pass (optional `resort_id` filter) | NetworkAdmin, ResortOps, RefundAdmin |
| GET | `/resorts/{id}/lift-scans` | List lift scans performed at a resort | NetworkAdmin, ResortOps, RefundAdmin |
| GET | `/passes/{id}/buddy-tickets` | List buddy tickets for a host pass | NetworkAdmin, ResortOps, RefundAdmin |
| GET | `/resorts/{id}/buddy-tickets` | List buddy tickets valid at a resort (optional `valid_date` filter) | NetworkAdmin, ResortOps, RefundAdmin |
| GET | `/passes/{id}/refund-requests` | List refund requests for a pass | NetworkAdmin, ResortOps, RefundAdmin |
| GET | `/resorts/{id}/interchange-agreements` | List interchange agreements for a resort | NetworkAdmin, ResortOps, RefundAdmin |
| POST | `/_clock/set_current_utc` | Set the system clock (drives scan timing and season-end auto-expiry) | NetworkAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_AUTH_MISSING` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_TIER` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_TOKEN_MISMATCH` | 409 Conflict |
| `ERR_ANTI_PASSBACK` | 409 Conflict |
| `ERR_INTERCHANGE_DENIED` | 409 Conflict |
| `ERR_REFUND_INELIGIBLE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_BUDDY_ALLOTMENT_EXHAUSTED` | 409 Conflict |
| `ERR_BUDDY_DATE_CONFLICT` | 409 Conflict |
