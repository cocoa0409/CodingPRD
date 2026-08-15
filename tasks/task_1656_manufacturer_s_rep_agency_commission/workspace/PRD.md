# Manufacturer's Rep Agency & Commission Splits API — Product Requirements Document

## 1. Introduction

An independent manufacturers' representative firm earns its living between two parties: the factories (its **principals**) whose product lines it carries, and the buyers it steers toward those lines across an assigned geography. Compensation flows entirely through commissions — rates that differ by product family, that improve as the agency climbs quota attainment tiers, and that must be shared when the salesperson who specified a product sits in a different territory than the one who receives the shipment. Returns claw commissions back through chargebacks, principals report monthly statements that rarely match the agency's own ledger to the penny, and recoverable draws must be skimmed out of settlement payouts. And when a principal decides to drop the agency, a notice period and a tail window govern which orders still earn commission.

This document specifies an API that operates that entire cycle for a single rep agency: onboarding principals and their line cards, publishing rate schedules, registering and protecting projects, booking and fulfilling orders with per-line split attribution, processing returns and chargebacks, reconciling principal statements from upload through dispute to settlement, and tracking consigned sample and demo inventory. Every time-dependent behavior — protection windows, renewal windows, termination notices, tail commissions, overdue sample charges, and calendar-year rollover — is driven by an explicit logical clock so that each rule in this document is deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, principles, and boilerplate that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. Four roles exist, spelled exactly: `AgencyAdmin`, `Rep`, `PrincipalOps`, and `Auditor`. A request that is missing either header, that names an unknown role, or whose entity-backed identifier does not resolve to an existing record is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A caller whose role is not in an endpoint's allowed list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Rep`, `X-User-ID` is the `id` of the acting `Rep`; ownership checks on any resource that references a rep — a registration's `rep_id`, a checkout's borrower, a split row on an order — compare that field to `X-User-ID`. When `X-User-Role` is `PrincipalOps`, `X-User-ID` is the `id` of the `Principal` the operator serves; ownership checks on any principal-scoped resource compare the resource's principal reference to `X-User-ID`. When `X-User-Role` is `AgencyAdmin` or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any resource's `id`. An entity-backed caller who touches a resource it does not own is rejected with `ERR_FORBIDDEN_NOT_OWNER` (HTTP 403).

Duties are deliberately segregated between the agency and its principals. A `PrincipalOps` operator uploads commission statements and answers disputes for its own principal, but only an `AgencyAdmin` reconciles, accepts variances, raises disputes, and settles. A `Rep` submits project registrations and borrows demo units; the principal's `PrincipalOps` operator approves or rejects those registrations. `Auditor` is a read-only oversight role with access to every list and detail endpoint and no write capability at all.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned in one page; it defaults to 10, accepts a minimum of 1, and is capped at 100. The `offset` parameter sets how many items to skip before the page begins and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order.

Paginated list responses carry four fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed properties:

- `id` — a server-minted UUID with no type prefix, unique across the installation.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` — an integer that starts at its initial value on creation and increments by one on every mutation, including mutations performed by cascades rather than by direct client action.

The commission ledger is the one exception. A `CommissionEntry` is immutable once posted: it carries only `id` and `created_at`, and both `updated_at` and `version` are absent from it.

### 2.5. The Logical Clock and the Epoch Sweep

All time-dependent behavior in the system reads from a single logical clock, never from wall-clock time. Before the clock has ever been advanced, it reads exactly 2026-08-01T00:00:00Z.

An `AgencyAdmin` may advance the logical clock through an admin-only test-driving capability whose request carries a `to_iso8601` timestamp. The supplied instant must be strictly later than the current reading; an attempt to move the clock to an instant at or before the current reading is rejected with `ERR_CLOCK_REGRESSION` (HTTP 409). Advancing the clock synchronously runs the epoch sweep before the response is returned, and the response reports the resulting `current_utc` together with `swept_counts`, a per-category tally of what the sweep touched. The sweep performs, in one atomic pass:

- principals in `NOTICE_PENDING` whose `termination_effective_at` has been reached transition to `TERMINATED`, with the full termination cascade described in §3.9;
- agreements in `ACTIVE` whose optional `effective_end` has been reached transition to `EXPIRED`;
- registrations in `APPROVED` whose `protection_end` has been reached transition to `EXPIRED`, with the re-attribution cascade described in §3.3;
- return authorizations in `APPROVED` whose receipt window has lapsed without a warehouse receipt transition to `EXPIRED`;
- sample checkouts still `OPEN` past their `due_at` transition to `CHARGED` and post their depreciation charge;
- when the clock crosses into a new calendar year, each principal's `credited_ytd_sales_cents` resets to zero and its `ytd_year` advances to the new year;
- any rep whose `commission_balance_cents` has recovered to zero or better is released from `COMMISSION_HOLD` back to `ACTIVE`.

### 2.6. The Commission Ledger and the Rep Hold Posture

All commission movement is recorded in an append-only ledger of `CommissionEntry` rows; balances are never updated in place. Each entry records the `rep_id` whose balance it moves and the `principal_id` it belongs to. An entry's `order_id` is set whenever the entry traces to an order; it is null for orderless `ADJUSTMENT` entries, for `SAMPLE_CHARGE` entries, and for `DRAW_RECOVERY` entries. An entry's `statement_id` is set only on `STATEMENT_PAYMENT` and `DRAW_RECOVERY` entries and is null otherwise. Where an entry traces to a specific line, `ref_line_id` holds the order line or statement line identifier; it is null when not applicable. A free-form `note` is recorded only on `ADJUSTMENT` entries.

The entry `type` is one of `ACCRUAL`, `CHARGEBACK`, `ADJUSTMENT`, `STATEMENT_PAYMENT`, `DRAW_RECOVERY`, or `SAMPLE_CHARGE`. Signs are fixed: `ACCRUAL` amounts are positive; `CHARGEBACK`, `STATEMENT_PAYMENT`, `DRAW_RECOVERY`, and `SAMPLE_CHARGE` amounts are negative; `ADJUSTMENT` amounts may carry either sign but are never zero — a zero-amount adjustment is rejected with `ERR_INVALID_REQUEST`. A rep's `commission_balance_cents` is the algebraic sum of every ledger entry posted for that rep: accruals and positive adjustments add, chargebacks, payments, charges, recoveries, and negative adjustments subtract.

Each entry also carries a `business_date`, which decides which statement period the entry counts toward: an `ACCRUAL` inherits its order's `invoiced_at`, a `CHARGEBACK` inherits its return authorization's `received_at`, and every other entry type uses the clock time at which the entry was posted.

The ledger drives the rep hold posture. After any entry posts, if a rep's `commission_balance_cents` falls below the hold floor of negative 50,000 cents — five hundred dollars in the red — the rep transitions from `ACTIVE` to `COMMISSION_HOLD`. While on hold, the rep's new project registration submissions, registration resubmissions, and sample checkouts are rejected with `ERR_REP_ON_HOLD`. The hold is released — the rep returns to `ACTIVE` — when the balance recovers to zero or better, re-evaluated after any entry posts and again during each clock sweep. Note the asymmetry: the hold engages below the floor, but it releases only at a non-negative balance.

### 2.7. Monetary Values, Rates, and Precision

All money in the system is integer cents — there are no fractional cents anywhere. All percentage rates are expressed in basis points, where 10,000 basis points equal 100 percent.

Wherever a computed amount must be rounded to whole cents, the method is round half up unless the specific rule states otherwise. Three calculations deliberately round down instead: the quota attainment ratio is floored to a whole basis point, the per-line effective commission rate is floored to a whole basis point before the registration bonus is added, and the draw-recovery skim is floored to whole cents. Split allocation at invoice time uses largest-remainder distribution so that allocated cents always sum exactly to the line's commission.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, because each replaces something the client priced or negotiated against without any state field distinguishing the old from the new.

Creating a rate schedule with `POST /rep-agency/principals/{id}/rate-schedules` requires the request to carry `expected_principal_version`, the caller's last observed `version` of the parent principal. If the principal's current `version` no longer matches — because another schedule was created, a termination notice was issued or rescinded, or any other mutation intervened — the create is rejected with `ERR_STALE_PRINCIPAL_VERSION` (HTTP 412): the supersede the client priced against is no longer current.

Overriding an order's splits with `PUT /rep-agency/orders/{orderId}/splits` requires the request to carry `expected_order_version`, the caller's last observed `version` of the order. If the order's current `version` no longer matches, the override is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412): the split rows the client negotiated against have since been replaced.

No other endpoint accepts a version field; these two are the complete set of OCC-guarded writes.

### 2.9. Validation Pipeline and Error Precedence

When a request could fail several rules at once, the checks execute in a fixed pipeline and the request fails with the first check it violates; later checks are never reached. The pipeline order is:

1. **User context.** `X-User-ID` and `X-User-Role` are present, the role is one of the four declared roles, and an entity-backed identifier resolves to an existing entity — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization.** The caller's role appears in the endpoint's allowed list — otherwise `ERR_FORBIDDEN_FOR_ROLE`.
3. **Existence.** Path identifiers and body reference identifiers (such as `customer_id`, `principal_id`, `sample_unit_id`, or `order_id`) resolve to existing records — otherwise `ERR_NOT_FOUND`.
4. **Ownership.** Entity-backed callers own the target: a rep acts only on its own registrations and checkouts and on orders where it holds a split; a principal operator acts only on resources of the principal whose `id` equals its `X-User-ID` — otherwise `ERR_FORBIDDEN_NOT_OWNER`.
5. **State-machine legality.** The target resource's state permits the requested transition, terminal states are locked, a return authorization is created only against an order in `SHIPPED`, `INVOICED`, or `PAID`, a sample checkout is created only against a unit in `IN_STOCK`, and a split override is attempted only while the order's commission dimension is still `ATTRIBUTED` — otherwise `ERR_INVALID_STATE_TRANSITION` or `ERR_SPLITS_LOCKED`.
6. **Optimistic concurrency.** `expected_principal_version` matches the principal's current `version` on rate-schedule creation, and `expected_order_version` matches the order's current `version` on a split override — otherwise `ERR_STALE_PRINCIPAL_VERSION` or `ERR_STALE_ORDER_VERSION`.
7. **Linked-entity gates.** The referenced principal, agreement, rate schedule, territories, product families, and rep posture permit the operation — otherwise one of `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_TERRITORY_NOT_COVERED`, `ERR_NO_ACTIVE_RATE_SCHEDULE`, `ERR_UNKNOWN_FAMILY_CODE`, `ERR_LINE_TERMINATED`, `ERR_LINE_UNDER_TERMINATION_NOTICE`, or `ERR_REP_ON_HOLD`.
8. **Temporal windows.** Protection overlap, checkout blocking intervals, renewal windows, the tail-invoicing window, back-dating, and clock monotonicity — otherwise one of `ERR_PROTECTION_WINDOW_OVERLAP`, `ERR_CHECKOUT_WINDOW_CONFLICT`, `ERR_RENEWAL_WINDOW_NOT_OPEN`, `ERR_RENEWAL_LIMIT_REACHED`, `ERR_TAIL_PERIOD_EXPIRED`, `ERR_FUTURE_DATED`, or `ERR_CLOCK_REGRESSION`.
9. **Shape, uniqueness, and sums.** Payload shape, duplicate identifiers, uniqueness scopes, and split sums — otherwise one of `ERR_SPLIT_SUM_INVALID`, `ERR_DUPLICATE_EXTERNAL_REF`, `ERR_DUPLICATE_PERIOD_LABEL`, `ERR_DUPLICATE_SERIAL`, `ERR_TERRITORY_COVERAGE_CONFLICT`, `ERR_AGREEMENT_CONFLICT`, or `ERR_INVALID_REQUEST`.
10. **Fiscal quantities and settlement gates.** Returnable quantities and statement settle preconditions — otherwise one of `ERR_RETURN_QTY_EXCEEDS_SHIPPED`, `ERR_UNRESOLVED_DISPUTES`, or `ERR_LINES_NOT_DISPOSITIONED`.

### 2.10. Existence Checks and Nested Resource Resolution

For any endpoint whose path contains more than one identifier, identifiers are validated left to right: the first identifier in the path that does not resolve to an existing resource produces `ERR_NOT_FOUND` (HTTP 404), and no later identifier is examined. A request to an agreement nested under a principal therefore reports the principal's absence before the agreement's, and a request targeting a statement line resolves the statement before the line. Body-supplied references are checked in the same spirit — a payload naming a nonexistent `customer_id`, `principal_id`, `sample_unit_id`, or `order_id` fails with `ERR_NOT_FOUND` before any business rule runs, per the pipeline order in §2.9.

## 3. Business Logic & Workflows

### 3.1. Principals, Line Cards, and Rate Schedules

Everything begins when an `AgencyAdmin` onboards a principal by supplying its `name` and the `annual_quota_cents` the agency is expected to sell on that line over a calendar year, plus an optional `notice_period_days` that defaults to ninety days. A new principal is born `ACTIVE` with `credited_ytd_sales_cents` at zero and `ytd_year` set to the year of the current logical clock. The principal list view may be narrowed with the optional `status` query parameter.

With the principal on file, the agency drafts the line card — a territory agreement. Creation names the `territory_codes` the card covers (for example a list of state codes) and an `effective_start`; the optional `effective_end` stays null for an open-ended arrangement. Three commercial defaults ride on the agreement unless overridden at creation: `exclusive` defaults to true, marking the agency as the sole rep in those territories; `specify_share_bp` defaults to 6,000 basis points, the specifying rep's standard sixty-percent cut when the specifier and the ship-to rep differ; and `registered_protection_share_bp` defaults to 10,000 basis points, the share a protected registered rep keeps on protected lines. The agreement also carries a `tail_period_days`, defaulting to 180 days, which becomes relevant only if the line is later terminated. Every agreement is stamped with the `principal_id` of its owning principal and starts life in `DRAFT`.

Activation — performed by an `AgencyAdmin` — moves an agreement from `DRAFT` to `ACTIVE`, and the same action reactivates a `SUSPENDED` agreement back to `ACTIVE`. Two gates guard activation, in the pipeline order of §2.9: the principal must not be `TERMINATED` (else `ERR_LINE_TERMINATED`), and no other agreement for the same principal may already be `ACTIVE` (else `ERR_AGREEMENT_CONFLICT`). At most one agreement per principal is ever `ACTIVE` at a time. An `AgencyAdmin` may also suspend an `ACTIVE` agreement, moving it to `SUSPENDED`; suspension and activation carry no further side effects.

Commission rates live on rate schedules, one active schedule per principal. Creating a schedule takes `family_rates` — an array pairing each `family_code` with its `base_rate_bp` — and `attainment_tiers`, an array pairing a `min_attainment_bp` threshold with a `multiplier_bp`, sorted ascending. An optional `registration_bonus_bp` defaults to 200 basis points, the flat bonus layered onto the effective rate for registration-protected lines. Creation stamps `effective_from` with the current clock, immediately flips the new schedule to `ACTIVE`, and atomically supersedes the principal's previously `ACTIVE` schedule, which moves to `SUPERSEDED`; at no time does a principal have more than one `ACTIVE` schedule. Because supersession is invisible to any state precondition, creation is OCC-guarded on the principal per §2.8, and it also increments the principal's `version` by one. Rate lookup at invoice time always uses whichever schedule is `ACTIVE` at that moment.

### 3.2. Reps, Customers, and Territory Coverage

An `AgencyAdmin` hires coverage into the system by creating a rep with a `display_name` and the `territory_codes` that rep covers agency-wide. Coverage is exclusive: a new rep's territories must be disjoint from the `territory_codes` of every other `ACTIVE` rep, or creation fails with `ERR_TERRITORY_COVERAGE_CONFLICT`. A rep carrying a recoverable draw starts with that balance in `outstanding_draw_cents`, which defaults to zero; every rep starts `ACTIVE` with a `commission_balance_cents` of zero. The reps list may be filtered by `status`.

Customers anchor the geography that attribution later reads. An `AgencyAdmin` creates a customer with a `name`, a `spec_territory_code` — the territory where the customer's design and engineering organization sits — and a `ship_to_territory_code`, the default delivery territory. The split between specifying and ship-to territory is the raw material for the attribution waterfall described in §3.4.

### 3.3. Project Registrations and Protection Windows

A rep who has designed a product into a customer project registers that project to earn protection. Submission carries the `principal_id` of the line, the `customer_id`, the `family_code` scope of the protection, and a free-form `project_name`; the system records the acting rep as the registration's `rep_id` and stamps `submitted_at` with the clock. A new registration is born `SUBMITTED`. Only referential gates run at submit time: a `TERMINATED` principal rejects the submission with `ERR_LINE_TERMINATED`, a principal in `NOTICE_PENDING` rejects it with `ERR_LINE_UNDER_TERMINATION_NOTICE`, and a rep in `COMMISSION_HOLD` is turned away with `ERR_REP_ON_HOLD`. Window overlap is deliberately not evaluated at submission — it is an approval-time check. Registrations may be browsed and narrowed with the `principal_id`, `customer_id`, `rep_id`, and `status` query parameters.

Approval belongs to the principal side: a `PrincipalOps` operator who owns the registration's principal moves it from `SUBMITTED` to `APPROVED`. Approval enforces three preconditions. The principal's single `ACTIVE` territory agreement must exist, else `ERR_AGREEMENT_NOT_ACTIVE`. And no other `APPROVED` registration for the same combination of `principal_id`, `customer_id`, and `family_code` may have a protection window that overlaps the new one. The new window opens at the current clock and closes 180 days later; windows are half-open — they include their opening instant and exclude their closing instant — so a new window that opens exactly when an existing window closes does not overlap. A colliding approval is rejected with `ERR_PROTECTION_WINDOW_OVERLAP`. On approval, `protection_start` is set to the current clock and `protection_end` to 180 days later. The same principal-side operator may instead reject the registration, moving it from `SUBMITTED` to `REJECTED`.

Rejection is not the end of the road. The owning rep — and only that rep, else `ERR_FORBIDDEN_NOT_OWNER` — may resubmit a `REJECTED` registration, returning it to `SUBMITTED` with `submitted_at` refreshed to the current clock; resubmission is blocked while the rep is in `COMMISSION_HOLD` (`ERR_REP_ON_HOLD`). The same owner may withdraw a registration in either `SUBMITTED` or `APPROVED`, moving it to `WITHDRAWN`.

An approved registration can be extended exactly once. Renewal is allowed only inside the renewal window: the clock must be at least thirty days before `protection_end` and still strictly before `protection_end` itself; an attempt outside that window — too early, or after protection has lapsed — is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN`. A registration that has already consumed its single renewal is rejected with `ERR_RENEWAL_LIMIT_REACHED`, enforced through the `renewals_used` counter that starts at zero. A successful renewal increments `renewals_used` by one and extends `protection_end` by ninety days, leaving the registration in `APPROVED`.

Protection ends in three ways. The clock sweep expires an `APPROVED` registration once the clock reaches `protection_end`, moving it to `EXPIRED`. Withdrawal of an `APPROVED` registration voids protection from that moment. And the termination cascade of §3.9 expires every `APPROVED` registration on the terminated line. In all three cases, uninvoiced orders of that principal — those still in `PLACED` or `SHIPPED` — whose lines referenced the registration are re-attributed: the `REGISTERED` share is dropped, the attribution precedence of §3.4 is re-resolved for those lines, and each affected line's `protected_registration_id` is cleared. Split rows that were set by a manual override are never re-attributed.

A line is considered protected for commission purposes when an `APPROVED` registration exists whose `principal_id`, `customer_id`, and `family_code` all match the order and line, and whose window contains the order's `placed_at` — including the window's opening instant and excluding its closing instant.

### 3.4. Booking Orders and Split Attribution

An `AgencyAdmin` books an order with a payload naming the `customer_id`, the `principal_id`, the principal's own purchase-order reference in `external_order_ref`, the customer PO timestamp `placed_at`, and the `lines` array. Each line carries a client-chosen `line_id` unique within the order, the `family_code`, a `quantity`, and a `unit_price_cents`; a line may also override the geography with its own `spec_territory_code` and `ship_to_territory_code`, which default to the customer's two territory codes when omitted. At creation the system initializes each line's `shipped_qty` and `returned_qty` to zero and its `applied_rate_bp`, `commission_cents`, and `protected_registration_id` to null — the rate and commission stay unknown until invoice. The fulfillment timestamps `shipped_at`, `invoiced_at`, and `paid_at` likewise remain null until the corresponding event occurs. An order evolves along two independent state dimensions on the same row: `fulfillment_status` runs from `PLACED` through `SHIPPED` and `INVOICED` to `PAID` (or to `CANCELLED` from `PLACED`), while `commission_status` runs from `ATTRIBUTED` to `ACCRUED` to `SETTLED` (or to `CLOSED` on cancel). A fresh order is `PLACED` and `ATTRIBUTED`. The orders list can be filtered by `customer_id`, `principal_id`, or `fulfillment_status`.

Booking is gated, in the pipeline order of §2.9. A `TERMINATED` principal accepts no new orders (`ERR_LINE_TERMINATED`) — though a principal merely under a termination notice still does. The principal's single `ACTIVE` agreement must exist (`ERR_AGREEMENT_NOT_ACTIVE`), and every line's specifying and ship-to territories must fall inside that agreement's `territory_codes` (`ERR_TERRITORY_NOT_COVERED`). An `ACTIVE` rate schedule must exist (`ERR_NO_ACTIVE_RATE_SCHEDULE`), and every line's `family_code` must appear in that schedule's `family_rates` (`ERR_UNKNOWN_FAMILY_CODE`). The `placed_at` timestamp may not lie in the future relative to the logical clock (`ERR_FUTURE_DATED`). The `external_order_ref` must be unique among this principal's orders that are not `CANCELLED` (`ERR_DUPLICATE_EXTERNAL_REF`) — a cancelled order frees its reference for reuse. Malformed bodies, a duplicated `line_id` inside one order, and non-positive quantities or prices fail with `ERR_INVALID_REQUEST`.

Booking immediately runs the attribution waterfall, which writes one or more `OrderSplit` rows per line. Each split row records the `order_id`, the `line_id` it covers, the `rep_id` it pays (null exactly when the row is a house row), a `role`, and a `share_bp` in basis points; rows for one line always sum to exactly 10,000 basis points, and every row is born with `is_override` false. Precedence is strict — `REGISTERED` first, then `SPECIFY`, then `SHIP_TO`, then `HOUSE`. When the line matches a protected registration per §3.3, a single `REGISTERED` row grants the registering rep the agreement's `registered_protection_share_bp`, and any residual share falls to a `HOUSE` row; the line's `protected_registration_id` records which registration matched. Without a protection match, the system resolves the spec rep — the unique `ACTIVE` rep whose `territory_codes` contain the line's `spec_territory_code` — and the ship rep, resolved the same way against the line's `ship_to_territory_code`. Four outcomes are possible: if both resolve to the same rep, a single `SPECIFY` row takes the full 10,000 basis points; if they resolve to different reps, a `SPECIFY` row pays the spec rep the agreement's `specify_share_bp` and a `SHIP_TO` row pays the ship rep the remainder; if only one side resolves, that role's row takes the full share; if neither resolves, a `HOUSE` row with a null `rep_id` takes the full share. House shares accrue to the house itself — no ledger entry is ever posted for a null-`rep_id` row. Split rows can be browsed via the split list, narrowed with the `order_id` and `rep_id` query parameters.

Two reps who would rather split a line differently renegotiate through the split override, available to an `AgencyAdmin` or to a `Rep` who currently holds a split row on that order (a rep with no row is rejected with `ERR_FORBIDDEN_NOT_OWNER`). The request carries the replacement `splits` array together with the OCC guard `expected_order_version` per §2.8. The override is permitted only while the order's commission dimension is still `ATTRIBUTED`; once the order has been invoiced the attempt fails with `ERR_SPLITS_LOCKED`. The replacement rows must cover every line of the order, and each line's shares must sum to exactly 10,000 basis points — a shortfall, an overage, or an uncovered line fails with `ERR_SPLIT_SUM_INVALID`. A successful override replaces all prior rows for the order with rows whose `role` is `OVERRIDE` and whose `is_override` is true, and increments the order's `version` by one. Override rows survive everything: the re-attribution cascades of §3.3 and §3.9 never touch them.

An order that never should have been booked can be cancelled by an `AgencyAdmin`, but only from `PLACED`. Cancellation moves `fulfillment_status` to `CANCELLED` and the commission dimension to `CLOSED`, increments the order's `version`, and retains the order's split rows for audit.

### 3.5. Fulfillment, Invoicing, and Commission Accrual

Once the goods leave the principal's dock, the owning `PrincipalOps` operator marks the order shipped: `fulfillment_status` moves from `PLACED` to `SHIPPED`, `shipped_at` takes the current clock, every line's `shipped_qty` is set to its full `quantity`, and the order's `version` increments.

Invoicing is the pivotal commercial event, and it too belongs to the owning `PrincipalOps` operator acting on a `SHIPPED` order. One temporal gate applies up front when the principal has been terminated: the order's `placed_at` must be strictly earlier than the principal's `termination_effective_at`, and the current clock must be no later than `termination_effective_at` plus the agreement's `tail_period_days` — the tail boundary is inclusive. An invoice attempt outside that window fails with `ERR_TAIL_PERIOD_EXPIRED`. An `ACTIVE` rate schedule must exist at invoice time (`ERR_NO_ACTIVE_RATE_SCHEDULE`), because rates come from whichever schedule is active when the invoice runs, not from the one that existed at booking.

Rating follows a pinned evaluation order that removes the circular dependency between an order's commission and the quota pool it feeds. First, the pool is read as the principal's `credited_ytd_sales_cents` before this order joins it. Second, attainment is computed as the pool scaled by 10,000 and divided by the principal's `annual_quota_cents`, rounded down to a whole basis point. Third, the applicable tier is the `attainment_tiers` entry with the largest `min_attainment_bp` that the attainment value reaches — the boundary is inclusive, so attainment exactly equal to a tier's threshold qualifies for that tier. Fourth, that tier's `multiplier_bp` is applied to the order being invoiced. Only after every line's rate is fixed does the pool absorb the order. When several orders invoice on the same day, they are rated in order-`created_at` ascending order — never by identifier.

Each line's commission is then computed. The base rate is the `base_rate_bp` that the active schedule's `family_rates` record for the line's `family_code`. The effective rate is that base scaled by the tier multiplier and divided by 10,000, rounded down to a whole basis point, then increased by the schedule's `registration_bonus_bp` when the line is registration-protected per §3.3. The line's net amount is its `quantity` multiplied by its `unit_price_cents`, and the line's commission is the net amount scaled by the effective rate and divided by 10,000, rounded half up to whole cents. The effective rate and the commission are stored on the line as `applied_rate_bp` and `commission_cents` — the stored rate is what a later return will charge back against.

Allocation then splits each line's commission across its split rows. Each row's raw share is the line's `commission_cents` scaled by the row's `share_bp` and divided by 10,000, rounded down; the leftover cents are dealt one by one to the rows ordered by `share_bp` descending, breaking ties by the rep's `created_at` ascending. The invariant holds exactly: a line's allocated cents sum to its `commission_cents`, and its shares sum to 10,000. For each pairing of rep and order, one `ACCRUAL` ledger entry posts the sum of that rep's per-line shares, with its `business_date` taken from the order's `invoiced_at`.

Invoicing closes with its bookkeeping: `invoiced_at` takes the clock, `fulfillment_status` moves to `INVOICED`, `commission_status` moves from `ATTRIBUTED` to `ACCRUED`, the principal's `credited_ytd_sales_cents` grows by the sum of the order's line amounts — the order joins the year-to-date pool only after its own rate was fixed — and the order's `version` increments. Later, when the customer pays, the owning operator records payment: `fulfillment_status` moves from `INVOICED` to `PAID`, `paid_at` takes the clock, and the version increments again. The payment timestamp matters downstream — it is what the cash-basis statement expectation of §3.7 keys on.

### 3.6. Returns and Chargebacks

When a buyer sends goods back, an `AgencyAdmin` opens a return authorization against an order, supplying the `order_id` and a `lines` array pairing each `line_id` with the `qty` being returned. The order must already be `SHIPPED`, `INVOICED`, or `PAID` — an attempt against an order in any other state fails with `ERR_INVALID_STATE_TRANSITION`. Per line, the requested `qty` may not exceed what was shipped minus what has already been returned minus the quantities already sitting on open (requested or approved) return authorizations for that line; an over-claim fails with `ERR_RETURN_QTY_EXCEEDS_SHIPPED`. A new authorization is born `REQUESTED`, with its `principal_id` denormalized from the order and `requested_at` stamped from the clock. Its `approved_at` and `received_at` remain null until the corresponding decision and warehouse receipt, `provisional_chargeback_cents` stays null until approval, and `final_chargeback_cents` stays null until receipt. The RMA list can be filtered by `order_id`, `principal_id`, or `status`.

Decisions belong to the owning `PrincipalOps` operator. Rejection moves the authorization from `REQUESTED` to `REJECTED` with no further effect. Approval moves it to `APPROVED`, stamps `approved_at`, and computes a `provisional_chargeback_cents` estimate using the current-rate variant of the chargeback calculation: each returned line is priced at the rate its family would earn right now — the currently active schedule's base rate scaled by the current attainment tier multiplier, with no registration bonus — regardless of what rate was actually applied at invoice.

Warehouse receipt is the moment money moves. The owning operator's receipt confirmation moves the authorization from `APPROVED` to `CLOSED`, stamps `received_at`, and computes `final_chargeback_cents` with the original-rate variant: each returned line is priced at the `applied_rate_bp` stored on that line at invoice time. The two variants answer differently whenever schedules or tiers have moved between invoice and receipt — identical goods charge back a different amount. Rounding order is pinned in both variants: each line's amount — its returned quantity multiplied by the line's `unit_price_cents` and scaled by the applicable rate in basis points — is first rounded half up to whole cents, and only then are the per-line amounts summed; the system never sums first and rounds once.

Receipt then cascades. Each line's `returned_qty` grows by the received quantity. One `CHARGEBACK` ledger entry posts per rep per order, dividing the final chargeback across the order's locked split rows exactly as the accrual was allocated; each entry's `business_date` is the receipt time. Every touched rep's `commission_balance_cents` is recomputed as the sum of its entries, and any rep whose balance falls below the negative-50,000-cent floor moves from `ACTIVE` to `COMMISSION_HOLD`. Finally, the principal's `credited_ytd_sales_cents` is reduced by the value of the returned goods — per line, the received quantity multiplied by the line's `unit_price_cents` — and is floored at zero so returns can never drag the year-to-date pool negative.

Approvals do not wait forever. If the clock reaches forty-five days after `approved_at` without a receipt, the sweep moves the authorization from `APPROVED` to `EXPIRED`; the provisional estimate is discarded back to null and no quantities change. Termination is final in both directions: `REJECTED`, `CLOSED`, and `EXPIRED` are all terminal.

### 3.7. Statements, Reconciliation, and Settlement

Each month the principal reports what it believes the agency earned. A `PrincipalOps` operator uploads the statement for its own principal with the `principal_id`, a `period_label` naming the calendar month in year-month form such as 2026-08, and the statement `lines`, each carrying a client-chosen `line_id` unique within the statement, the `external_order_ref` the line pays on, and the `amount_cents` the principal attributes to it. The period label must be unique per principal — a second upload of the same month fails with `ERR_DUPLICATE_PERIOD_LABEL`, and a duplicated `line_id` inside one statement fails with `ERR_INVALID_REQUEST`. At upload every line's `disposition` is set to `PENDING`, the `stated_total_cents` is computed as the sum of the line amounts, and the statement is born `RECEIVED`. The expectation fields and `reconciled_at` remain unset until reconciliation runs, and `settled_at` remains null until settlement. Statements can be browsed and filtered by `principal_id` or `status`.

Reconciliation is the agency's job. An `AgencyAdmin` starting reconciliation moves the statement from `RECEIVED` to `IN_RECONCILIATION` and triggers three computations. The canonical expectation, `expected_total_cents`, is accrual-basis: the sum of every `ACCRUAL` and `CHARGEBACK` entry amount for this principal whose `business_date` falls inside the period month — the period runs from the first instant of the `period_label` month up to, but not including, the first instant of the following month. The informational variant, `expected_cash_basis_cents`, instead counts `ACCRUAL` entries whose order's `paid_at` falls inside the period month, plus `CHARGEBACK` entries by their `business_date`; an identical ledger yields a different cash-basis total whenever payment and invoice straddle the period boundary. The `variance_cents` is then the stated total minus the accrual expectation. `reconciled_at` records when reconciliation last ran.

The same run dispositions every line. A line first looks up the unique non-`CANCELLED` order of this principal whose `external_order_ref` equals the line's; if none exists the line becomes `UNMATCHED_ORDER`. Otherwise the line's expected amount is the sum of all ledger entry amounts traced to that order with a `business_date` on or before the end of the period month. A line whose stated amount differs from that expectation by no more than twenty-five cents becomes `MATCHED` — the boundary is inclusive, so a delta of exactly 25 cents still matches — and anything wider becomes `AMOUNT_VARIANCE`.

From `IN_RECONCILIATION`, the agency works the lines. An `AgencyAdmin` may accept an `AMOUNT_VARIANCE` line as-is, moving its disposition to `VARIANCE_ACCEPTED`, or dispute a line outright — supplying a `reason` — which moves the line to `DISPUTED` and the statement from `IN_RECONCILIATION` to `DISPUTED`. The principal side answers each dispute through its `PrincipalOps` operator, naming the `line_id`, an `action`, and optionally an `adjustment_amount_cents`. An `ACCEPT` response moves the line to `RESOLVED` and queues the adjustment amount, if one was supplied, for settle-time allocation to the matched order's splits; when the response resolves the statement's last disputed line the statement returns from `DISPUTED` to `IN_RECONCILIATION`, and while other lines remain disputed it stays `DISPUTED`. A `REJECT` response leaves the line `DISPUTED` and the statement `DISPUTED`.

Settlement closes the loop, and again it is an `AgencyAdmin` action — the segregation of duties keeps the uploader away from settlement. Settle is gated: any line still `DISPUTED` blocks it with `ERR_UNRESOLVED_DISPUTES`, and any line still `PENDING`, `AMOUNT_VARIANCE`, or `UNMATCHED_ORDER` blocks it with `ERR_LINES_NOT_DISPOSITIONED`. A clean settle then posts the money. Every absorbed delta — a `MATCHED` line whose delta was nonzero, a `VARIANCE_ACCEPTED` line, or a `RESOLVED` line carrying an `adjustment_amount_cents` — produces `ADJUSTMENT` ledger entries, the signed delta allocated across the matched order's split rows pro-rata by `share_bp` using the same largest-remainder distribution as invoice allocation. For each rep with accruals on the orders the statement covers, one `STATEMENT_PAYMENT` entry posts equal to the negative of that rep's accrued share plus that rep's share of the adjustments. Then the draw-recovery waterfall runs over reps with a positive `outstanding_draw_cents`, oldest rep first by `created_at`: a rep's gross is its accrued share on covered orders plus its adjustment share; a gross of zero or less means no payment and no recovery; otherwise the recovery is the smaller of the rep's `outstanding_draw_cents` and one half of the gross rounded down to whole cents, posted as a negative `DRAW_RECOVERY` entry with the rep's `outstanding_draw_cents` reduced by the recovered amount. The recovery rides inside the payout — the payment entry is the negative of the full gross, and the rep's cash payout is what remains after the skim.

Settlement finishes by moving every covered order's `commission_status` to `SETTLED`, stamping `settled_at` with the clock, recomputing each affected rep's balance, and re-evaluating hold engagement and release per §2.6. `SETTLED` is the statement's terminal state.

The agency can also move a rep's ledger directly at any time: an `AgencyAdmin` posts a signed `amount_cents` with a `note` and an optional `principal_id`, creating an `ADJUSTMENT` entry. The amount must be non-zero (`ERR_INVALID_REQUEST`), and the posting recomputes the rep's balance and re-evaluates the hold. All ledger rows — accruals, chargebacks, adjustments, payments, recoveries, and sample charges alike — are visible through the entry list, filterable by `rep_id`, `principal_id`, `order_id`, `statement_id`, or `type`.

### 3.8. Sample and Demo Inventory

Principals consign demo units to the agency. A `PrincipalOps` operator registers a unit with its `principal_id`, a `serial_number` that must be unique per principal (`ERR_DUPLICATE_SERIAL`), the `family_code`, and the list `value_cents` that depreciation later keys on; a `TERMINATED` principal consigns nothing new (`ERR_LINE_TERMINATED`). A unit is born `IN_STOCK`, and the unit list can be filtered by `principal_id` or `status`.

A rep borrows a unit by checking it out, supplying only the `sample_unit_id`; the system records the acting rep as the checkout's `rep_id`. The unit must currently be `IN_STOCK` (else `ERR_INVALID_STATE_TRANSITION`), the borrowing rep must not be in `COMMISSION_HOLD` (else `ERR_REP_ON_HOLD`), and the unit must not be inside a blocked interval: the unit is blocked while any checkout of it is still `OPEN`, and after the most recent checkout it stays blocked until one full day of inspection buffer has passed beyond that checkout's `returned_at` — or beyond its `due_at` if it never came back. A checkout attempted inside a blocked interval fails with `ERR_CHECKOUT_WINDOW_CONFLICT`. A successful checkout is born `OPEN` with `checked_out_at` stamped from the clock and `due_at` set thirty days out, while the unit flips from `IN_STOCK` to `CHECKED_OUT`. While a checkout is open its `charge_cents` stays null unless a charge posts, and its `returned_at` stays null until it comes back. Checkouts can be listed and filtered by `sample_unit_id`, `rep_id`, or `status`.

Return and purchase belong to the borrowing rep alone (`ERR_FORBIDDEN_NOT_OWNER`). On return the rep declares the `condition_on_return`: a `SELLABLE` unit goes back to `IN_STOCK` with a `charge_cents` of zero, while a `DAMAGED` unit is written off — the unit moves to `WRITTEN_OFF` and a charge of one half of its depreciated value, rounded half up to whole cents, posts as a `SAMPLE_CHARGE` entry. Either way `returned_at` takes the clock and the checkout moves from `OPEN` to `RETURNED`. A rep who wants to keep the unit converts the checkout instead: the charge is the full depreciated value at conversion time, posted as a `SAMPLE_CHARGE` entry, the unit moves from `CHECKED_OUT` to `CONVERTED`, the checkout moves from `OPEN` to `CONVERTED`, and the rep's balance recompute re-evaluates the hold posture.

Depreciation is a step function of time held. The charge calculation counts the whole days between the checkout's `checked_out_at` and the event, then counts each started thirty-day month. The unit loses fifteen percent of list per started month, and the remaining factor is never allowed below twenty percent of list. The depreciated value is the unit's `value_cents` scaled by that factor, rounded half up to whole cents. Conversion and the overdue sweep charge the full depreciated value; a damaged return charges half of it; a sellable return charges nothing.

A checkout left open past its `due_at` does not linger: the clock sweep moves it from `OPEN` to `CHARGED`, posts a `SAMPLE_CHARGE` entry for the full depreciated value as of the sweep date, writes the unit off to `WRITTEN_OFF`, and cascades into the rep's balance recompute and hold check.

### 3.9. Line Termination, Tail Commissions, and Year Rollover

Terminating a line starts with the principal side: a `PrincipalOps` operator who owns the principal issues a termination notice, moving the principal from `ACTIVE` to `NOTICE_PENDING`. The notice stamps `termination_notice_issued_at` with the current clock and computes `termination_effective_at` as the notice time plus the principal's `notice_period_days`; until a notice exists, both timestamps are null. The principal's `version` increments by one. While the notice pends, the principal may still take orders — but new project registrations are refused with `ERR_LINE_UNDER_TERMINATION_NOTICE`.

A notice can be walked back. The same owning operator rescinds it, but only while the current clock is still strictly earlier than `termination_effective_at`; once the effective instant has been reached the attempt fails with `ERR_INVALID_STATE_TRANSITION`. A successful rescission returns the principal from `NOTICE_PENDING` to `ACTIVE`, clears both termination timestamps back to null, and increments the principal's `version`.

When the clock reaches `termination_effective_at`, the sweep terminates the line. The principal moves from `NOTICE_PENDING` to its terminal `TERMINATED` state, and the cascade runs in three links. First, every territory agreement of the principal that is `ACTIVE` or `SUSPENDED` moves to `TERMINATED`. Second, each terminated agreement expires every `APPROVED` project registration on that principal, moving it to `EXPIRED`. Third, each expired registration triggers the re-attribution of §3.3 on the principal's uninvoiced orders: non-override split rows on orders still `PLACED` or `SHIPPED` have their `REGISTERED` share dropped, precedence is re-resolved, and the affected lines' `protected_registration_id` is cleared. A `TERMINATED` principal then blocks new orders, new registrations, agreement activations, and new sample units — all with `ERR_LINE_TERMINATED`.

Termination does not erase work already in the pipeline. An order placed strictly before the effective instant may still be invoiced during the tail: the invoice must run no later than `termination_effective_at` plus the agreement's `tail_period_days`, with the tail boundary inclusive, per §3.5. An invoice attempted after the tail closes — or for an order placed after the effective instant — fails with `ERR_TAIL_PERIOD_EXPIRED`.

Agreements also die quietly on their own schedule: when the clock reaches an `ACTIVE` agreement's non-null `effective_end`, the sweep moves the agreement to `EXPIRED`, and every `APPROVED` registration on the principal expires with it, feeding the same re-attribution cascade. Finally, the calendar itself turns over: when a clock advance crosses into a new calendar year, each principal's `credited_ytd_sales_cents` resets to zero and its `ytd_year` advances, so a new selling year starts with a clean quota pool while the prior year's settled history remains in the ledger.

## 4. Endpoint Definitions

All endpoints are mounted under the `/rep-agency` prefix. Operations that create a new, stand-alone resource — a principal, agreement, rate schedule, rep, customer, registration, order, return authorization, statement, sample unit, checkout, or a ledger adjustment — answer `201 Created`. Operations that modify an existing resource in place — state transitions, the split override, and the clock advance — answer `200 OK`. The table below is a summary only; request payloads, response bodies, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/rep-agency/_clock/set_current_utc` | Advance the logical clock and run the epoch sweep | AgencyAdmin |
| POST   | `/rep-agency/principals` | Create a principal | AgencyAdmin |
| GET    | `/rep-agency/principals` | List principals | AgencyAdmin, PrincipalOps, Rep, Auditor |
| GET    | `/rep-agency/principals/{id}` | Get a principal | AgencyAdmin, PrincipalOps, Rep, Auditor |
| POST   | `/rep-agency/principals/{id}/issue_termination_notice` | Issue a line termination notice | PrincipalOps |
| POST   | `/rep-agency/principals/{id}/rescind_termination_notice` | Rescind a pending termination notice | PrincipalOps |
| POST   | `/rep-agency/principals/{id}/agreements` | Create a territory agreement (line card) | AgencyAdmin |
| GET    | `/rep-agency/principals/{id}/agreements` | List a principal's agreements | AgencyAdmin, PrincipalOps, Rep, Auditor |
| GET    | `/rep-agency/agreements/{agreementId}` | Get an agreement | AgencyAdmin, PrincipalOps, Rep, Auditor |
| POST   | `/rep-agency/agreements/{agreementId}/activate` | Activate or reactivate an agreement | AgencyAdmin |
| POST   | `/rep-agency/agreements/{agreementId}/suspend` | Suspend an active agreement | AgencyAdmin |
| POST   | `/rep-agency/principals/{id}/rate-schedules` | Create a rate schedule, superseding the active one | AgencyAdmin |
| GET    | `/rep-agency/principals/{id}/rate-schedules` | List a principal's rate schedules | AgencyAdmin, PrincipalOps, Rep, Auditor |
| GET    | `/rep-agency/rate-schedules/{rateScheduleId}` | Get a rate schedule | AgencyAdmin, PrincipalOps, Rep, Auditor |
| POST   | `/rep-agency/reps` | Create a rep | AgencyAdmin |
| GET    | `/rep-agency/reps` | List reps | AgencyAdmin, PrincipalOps, Rep, Auditor |
| GET    | `/rep-agency/reps/{repId}` | Get a rep | AgencyAdmin, PrincipalOps, Rep, Auditor |
| POST   | `/rep-agency/reps/{repId}/adjustments` | Post a signed adjustment to a rep's ledger | AgencyAdmin |
| POST   | `/rep-agency/customers` | Create a customer | AgencyAdmin |
| GET    | `/rep-agency/customers` | List customers | AgencyAdmin, PrincipalOps, Rep, Auditor |
| GET    | `/rep-agency/customers/{customerId}` | Get a customer | AgencyAdmin, PrincipalOps, Rep, Auditor |
| POST   | `/rep-agency/project-registrations` | Submit a project registration | Rep |
| GET    | `/rep-agency/project-registrations` | List project registrations | AgencyAdmin, PrincipalOps, Rep, Auditor |
| GET    | `/rep-agency/project-registrations/{registrationId}` | Get a project registration | AgencyAdmin, PrincipalOps, Rep, Auditor |
| POST   | `/rep-agency/project-registrations/{registrationId}/approve` | Approve a registration, opening its protection window | PrincipalOps |
| POST   | `/rep-agency/project-registrations/{registrationId}/reject` | Reject a registration | PrincipalOps |
| POST   | `/rep-agency/project-registrations/{registrationId}/resubmit` | Resubmit a rejected registration | Rep |
| POST   | `/rep-agency/project-registrations/{registrationId}/renew` | Renew an approved registration inside its renewal window | Rep |
| POST   | `/rep-agency/project-registrations/{registrationId}/withdraw` | Withdraw a submitted or approved registration | Rep |
| POST   | `/rep-agency/orders` | Book an order and run per-line split attribution | AgencyAdmin |
| GET    | `/rep-agency/orders` | List orders | AgencyAdmin, PrincipalOps, Rep, Auditor |
| GET    | `/rep-agency/orders/{orderId}` | Get an order | AgencyAdmin, PrincipalOps, Rep, Auditor |
| POST   | `/rep-agency/orders/{orderId}/ship` | Mark the full order shipped | PrincipalOps |
| POST   | `/rep-agency/orders/{orderId}/invoice` | Invoice a shipped order, rating and accruing commissions | PrincipalOps |
| POST   | `/rep-agency/orders/{orderId}/mark_paid` | Record customer payment | PrincipalOps |
| POST   | `/rep-agency/orders/{orderId}/cancel` | Cancel a placed order | AgencyAdmin |
| PUT    | `/rep-agency/orders/{orderId}/splits` | Override the order's collaboration splits | AgencyAdmin, Rep |
| GET    | `/rep-agency/order-splits` | List order split rows | AgencyAdmin, PrincipalOps, Rep, Auditor |
| GET    | `/rep-agency/order-splits/{orderSplitId}` | Get an order split row | AgencyAdmin, PrincipalOps, Rep, Auditor |
| POST   | `/rep-agency/rmas` | Open a return authorization against a shipped order | AgencyAdmin |
| GET    | `/rep-agency/rmas` | List return authorizations | AgencyAdmin, PrincipalOps, Rep, Auditor |
| GET    | `/rep-agency/rmas/{rmaId}` | Get a return authorization | AgencyAdmin, PrincipalOps, Rep, Auditor |
| POST   | `/rep-agency/rmas/{rmaId}/approve` | Approve an RMA and compute the provisional chargeback | PrincipalOps |
| POST   | `/rep-agency/rmas/{rmaId}/reject` | Reject an RMA | PrincipalOps |
| POST   | `/rep-agency/rmas/{rmaId}/receive` | Confirm warehouse receipt and post final chargebacks | PrincipalOps |
| GET    | `/rep-agency/commission-entries` | List commission ledger entries | AgencyAdmin, PrincipalOps, Rep, Auditor |
| GET    | `/rep-agency/commission-entries/{entryId}` | Get a ledger entry | AgencyAdmin, PrincipalOps, Rep, Auditor |
| POST   | `/rep-agency/statements` | Upload a principal's commission statement | PrincipalOps |
| GET    | `/rep-agency/statements` | List commission statements | AgencyAdmin, PrincipalOps, Rep, Auditor |
| GET    | `/rep-agency/statements/{statementId}` | Get a commission statement | AgencyAdmin, PrincipalOps, Rep, Auditor |
| POST   | `/rep-agency/statements/{statementId}/start_reconciliation` | Compute expectations and disposition all lines | AgencyAdmin |
| POST   | `/rep-agency/statements/{statementId}/lines/{lineId}/accept_variance` | Accept a variance line as-is | AgencyAdmin |
| POST   | `/rep-agency/statements/{statementId}/lines/{lineId}/dispute` | Dispute a statement line | AgencyAdmin |
| POST   | `/rep-agency/statements/{statementId}/respond_dispute` | Principal responds to a disputed line | PrincipalOps |
| POST   | `/rep-agency/statements/{statementId}/settle` | Settle a fully dispositioned statement | AgencyAdmin |
| POST   | `/rep-agency/sample-units` | Register a consigned sample unit | PrincipalOps |
| GET    | `/rep-agency/sample-units` | List sample units | AgencyAdmin, PrincipalOps, Rep, Auditor |
| GET    | `/rep-agency/sample-units/{sampleUnitId}` | Get a sample unit | AgencyAdmin, PrincipalOps, Rep, Auditor |
| POST   | `/rep-agency/sample-checkouts` | Check out a sample unit | Rep |
| GET    | `/rep-agency/sample-checkouts` | List sample checkouts | AgencyAdmin, PrincipalOps, Rep, Auditor |
| GET    | `/rep-agency/sample-checkouts/{checkoutId}` | Get a sample checkout | AgencyAdmin, PrincipalOps, Rep, Auditor |
| POST   | `/rep-agency/sample-checkouts/{checkoutId}/return` | Return a checked-out unit with a condition declaration | Rep |
| POST   | `/rep-agency/sample-checkouts/{checkoutId}/convert` | Purchase the demo unit at its depreciated value | Rep |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status. The conditions that trigger each error are defined in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_FORBIDDEN_NOT_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_STALE_PRINCIPAL_VERSION` | 412 |
| `ERR_STALE_ORDER_VERSION` | 412 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_AGREEMENT_CONFLICT` | 409 |
| `ERR_TERRITORY_NOT_COVERED` | 409 |
| `ERR_NO_ACTIVE_RATE_SCHEDULE` | 409 |
| `ERR_UNKNOWN_FAMILY_CODE` | 422 |
| `ERR_LINE_TERMINATED` | 409 |
| `ERR_LINE_UNDER_TERMINATION_NOTICE` | 409 |
| `ERR_REP_ON_HOLD` | 409 |
| `ERR_PROTECTION_WINDOW_OVERLAP` | 409 |
| `ERR_CHECKOUT_WINDOW_CONFLICT` | 409 |
| `ERR_RENEWAL_WINDOW_NOT_OPEN` | 409 |
| `ERR_RENEWAL_LIMIT_REACHED` | 409 |
| `ERR_TAIL_PERIOD_EXPIRED` | 409 |
| `ERR_FUTURE_DATED` | 422 |
| `ERR_CLOCK_REGRESSION` | 409 |
| `ERR_SPLIT_SUM_INVALID` | 422 |
| `ERR_SPLITS_LOCKED` | 409 |
| `ERR_DUPLICATE_EXTERNAL_REF` | 409 |
| `ERR_DUPLICATE_PERIOD_LABEL` | 409 |
| `ERR_DUPLICATE_SERIAL` | 409 |
| `ERR_TERRITORY_COVERAGE_CONFLICT` | 409 |
| `ERR_RETURN_QTY_EXCEEDS_SHIPPED` | 409 |
| `ERR_UNRESOLVED_DISPUTES` | 409 |
| `ERR_LINES_NOT_DISPOSITIONED` | 409 |
