# Museum & Zoo Membership & Admission API — Product Requirements Document

## 1. Introduction

This document specifies the Museum & Zoo Membership & Admission API, the system of record behind a cultural institution's membership program and its day-to-day gate operations. The product serves two intertwined needs. On one side it runs a **membership program**: patrons buy annual memberships at one of several tiers, add named household members, accrue guest passes, renew (early, on auto-renew, or after lapsing into a grace window), and optionally fold charitable donations into the transaction. On the other side it runs **timed-entry admission**: patrons book a general-admission window, optionally add a special-exhibit session, assemble a party of member, non-member, guest, and reciprocal-network tickets, and either walk through the gate or have the order checked in by front-desk or gate staff.

The two halves meet at pricing. A member's tier changes what each ticket costs, whether the special-exhibit surcharge is discounted or waived, and which reciprocal partners honor the card. Because the institution sells against fixed-capacity slots and a finite pool of guest passes, the system must hold reservations atomically, recompute capacity on every confirm, cancel, and refund, and conserve guest passes across the membership's whole lifecycle. Pricing is computed twice — provisionally while an order is still a draft, and finally and authoritatively at confirmation — and the two computations deliberately differ. The remainder of this document defines the resources, their state machines, the pricing and fee calculations, the validation order, and the exact API surface that realizes all of the above.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint. Section 3 then narrates the business workflows in which these rules are exercised.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. If `X-User-Role` is missing or is not one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles: `Patron`, `BoxOffice`, `GateScanner`, and `MembershipAdmin`. When a caller presents a valid role but that role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

When `X-User-Role` is `Patron`, `X-User-ID` is the `id` of the acting `Patron`; ownership checks compare a resource's owning patron reference to `X-User-ID`. Concretely, a `Membership` is owned by the patron named in its `primary_patron_id`, and an `AdmissionOrder` is owned by the patron named in its `patron_id`; when a `Patron` attempts to act on a membership or order whose owning patron is not `X-User-ID`, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

The three operational roles are not entity-backed. When `X-User-Role` is `BoxOffice`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the front desk registers patrons, sells and renews memberships, builds and confirms orders on a patron's behalf, checks orders in, and processes refunds, and the server does not compare its `X-User-ID` to any entity's `id`. When `X-User-Role` is `GateScanner`, `X-User-ID` is likewise an opaque device identifier not tied to any persisted entity; a gate scanner only checks confirmed orders in at the entry window. When `X-User-Role` is `MembershipAdmin`, `X-User-ID` is an opaque administrator identifier not tied to any persisted entity; the administrator owns catalog configuration (plans, slots, exhibits and their sessions, reciprocal partners) and runs the logical clock, the payment settlement hook, and the batch jobs. None of the three operational roles is subject to the resource-ownership check.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it must lie between a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip; when omitted it defaults to 0, and it must be at least 0. A request whose `limit` or `offset` falls outside these ranges is rejected with `ERR_VALIDATION_PAGINATION`.

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Mutation Semantics

Almost every resource in the system is a top-level resource that carries four system-managed fields. The `id` is a server-minted UUID with no type prefix, used for identity only. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp, refreshed on every mutation — including mutations applied by a cascade rather than by a direct request on that resource. The `version` field is an integer that starts at 1 and increases by one on every mutation.

These four fields apply to `Patron`, `MembershipPlan`, `Membership`, `HouseholdMember`, `GuestPass`, `TimedEntrySlot`, `SpecialExhibit`, `ExhibitSession`, `AdmissionOrder`, `AdmissionTicket`, and `ReciprocalPartner`. The single exception is `Donation`: a donation is an immutable receipt that carries only `id` and `created_at` — it has neither `updated_at` nor `version`, and once written it is never modified.

A mutation applied indirectly is still a mutation. When a cascade voids a ticket, releases a guest pass, or adjusts a slot's reserved count, the affected resource's `updated_at` is refreshed and its `version` increments exactly as if the change had been requested directly. This is the consistency contract that ties parent and child state together: there is no "silent" write.

### 2.5. Nested Resource Retrieval and Identifier Resolution

The resource topology is flat — resources are top-level collections joined by foreign keys, and URL paths do not nest, with the sole exception of a special exhibit's sessions, which are reachable both as a top-level collection and as the reverse sub-resource of their parent exhibit. Wherever a request carries more than one resource identifier (whether in the path or in the body), the identifiers are validated left to right, and the first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any later identifier is examined. This left-to-right rule governs reads, creates, and transitions alike.

Every write must also be structurally well-formed: required fields present, enum-typed fields holding one of their declared values, and integer fields that the catalog marks as at least 0 actually non-negative. A write that violates body conformance — a missing required field, an unrecognized enum value, or a negative integer where a non-negative one is required — is rejected with `ERR_INVALID_REQUEST`. Where both apply, authentication and role checks precede resource resolution, which precedes body conformance, so a request from an unknown role is rejected before its body or its identifiers are examined.

### 2.6. Monetary Amounts, Percentages, and Rounding

All monetary amounts in the system are integer cents — annual fees, admission prices, surcharges, donation amounts, and every computed total. There are no fractional cents anywhere in a stored or returned amount. Where a calculation multiplies a price by a fractional factor (for example, a member surcharge discount or a reciprocal discount), the result is rounded to the nearest whole cent using the round-half-up convention, and this rounding is applied at each such per-component multiplication, never deferred to the final sum. Per-ticket prices are therefore whole-cent values before they are summed, and the order's admission subtotal is the plain sum of those already-rounded per-ticket prices.

Two fields are fractional discount factors rather than money: `member_surcharge_discount_pct` on a special exhibit and `discount_pct` on a reciprocal partner. Each is a number between 0 and 1 inclusive; a value at the lower bound of 0 means no discount and a value at the upper bound of 1 means the charged component falls to zero.

### 2.7. Optimistic Concurrency Control on Membership Renewal

Renewing a membership is the one operation guarded by optimistic concurrency control. A renewal request must carry `expected_membership_version`, which is the `version` of the target `Membership` as the client last observed it. The server compares `expected_membership_version` against the membership's current `version`; if they do not match, the renewal is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is mutated. The rationale is that a renewal mints a fresh term that supersedes the prior term: if the automatic renewal job, or an earlier manual renewal, has already advanced the membership's `version` since the client read it, the client is holding a stale view, and allowing its renewal to land would discard a term it never saw. No other endpoint accepts or requires a version field; the OCC check exists only on membership renewal.

### 2.8. Capacity, Guest-Pass Conservation, and Cascade Consistency

Two scarce quantities are tracked continuously. The first is per-slot and per-session **capacity**: a `TimedEntrySlot` and an `ExhibitSession` each carry a `capacity_total` and a computed `reserved_count`. The reserved count of a slot is the sum of `party_size` over every order on that slot whose status is `CONFIRMED` or `CHECKED_IN`; the reserved count of a session is the same sum over orders that add that session and are `CONFIRMED` or `CHECKED_IN`. Reserved counts move only through the order lifecycle — they rise when an order confirms and fall when an order cancels or refunds, or when a guest ticket is voided by a membership cascade — and they are floored at zero, never negative.

The second scarce quantity is the **guest-pass pool**. When a membership becomes active for a term, the system mints a fixed number of guest passes (the plan's `guest_passes_granted`); across that term the count of passes in `UNUSED`, `RESERVED`, and `REDEEMED` together always equals the number minted for the term. Passes only leave that conserved set by expiring at term rollover or by a cancellation cascade. Reserving a guest pass and later releasing it must net to zero: a release returns the pass and reverses every downstream effect the reservation caused, so the institution never loses or gains a pass through ordinary order churn. Whenever a guest pass that had been reserved against an order is released, the linked guest ticket is voided and the order's held capacity is given back, so that the pass pool and the slot's reserved count stay mutually consistent.

Every cascade in this system is atomic within the request that triggers it. A confirm, a cancel, a refund, a membership transition, or a batch job either applies all of its side effects and capacity recomputations or none of them; there is no intermediate state visible to another reader.

## 3. Business Logic & Workflows

### 3.1. Patrons, Plans, and the Catalog

A patron account is the anchor of the membership relationship. Registering a patron — a capability the front desk and the catalog administrator both hold — records the patron's unique login `email` and their display `full_name`, and may set `home_partner_id`, the reciprocal partner organization whose membership card this patron carries for reciprocal admission; `home_partner_id` is nullable and defaults to absent. Each patron's `email` must be unique across all patrons; a registration whose `email` already exists is rejected with `ERR_EMAIL_TAKEN`. Patrons may be listed and filtered by `email` or by `home_partner_id`.

The catalog administrator defines the **membership plans** that drive pricing. A plan names its `tier`, which is one of `INDIVIDUAL`, `DUAL`, `HOUSEHOLD`, or `PATRON_CIRCLE`, and its `annual_fee_cents`, the base annual fee, which must be at least 0. A plan sets `household_max`, the maximum number of named household members (excluding the primary patron) a membership on this plan may carry, at least 0; `guest_passes_granted`, the number of guest passes minted each time a membership on the plan becomes active for a term, at least 0; and `member_admission_cents`, the per-person general-admission price charged to member-type tickets on this plan, at least 0. Three plan flags shape benefits: `exhibit_surcharge_waived`, which when true fully waives the special-exhibit surcharge on member tickets (it defaults to false); `reciprocal_eligible`, which when true grants members on the plan reciprocal-network benefits at partner organizations (it defaults to false); and the term length `term_days`, the number of days in one membership term, which defaults to 365 and must be at least 1. Finally, `reinstatement_fee_cents` is the surcharge added when a lapsed membership is reinstated during its grace window; it defaults to 0 and must be at least 0. Plans may be listed and filtered by `tier`.

The administrator also configures the admission catalog. A **timed-entry slot** is a general-admission window defined by `starts_at` (inclusive) and `ends_at` (exclusive, and strictly later than `starts_at`), a `capacity_total` of at least 1, and a `non_member_admission_cents`, the per-person general-admission price for non-members on that slot, at least 0. A new slot opens with `status` of `OPEN` and a `reserved_count` of 0; an administrator may later close a slot, moving its `status` to `CLOSED` so it rejects new bookings, which increments the slot's `version` by one. A **special exhibit** carries a `name`, a per-person `surcharge_cents` of at least 0, a `member_surcharge_discount_pct` between 0 and 1 (default 0) applied to the surcharge for member tickets before any plan-level waiver, and a `buffer_minutes` cleaning buffer of at least 0 (default 0) that must separate two of one patron's bookings on this exhibit's sessions. Under an exhibit the administrator creates **exhibit sessions**, each with `starts_at` (inclusive) and `ends_at` (exclusive, strictly later than `starts_at`) and a `capacity_total` of at least 1; a new session opens with `reserved_count` of 0 and references its parent through `exhibit_id`. Sessions are reachable as the reverse sub-resource of their exhibit. Finally, a **reciprocal partner** carries an `org_name`, a `benefit_type` of either `FREE` or `DISCOUNT`, and a `discount_pct` between 0 and 1 (default 0) that applies to non-member admission for reciprocal tickets when `benefit_type` is `DISCOUNT` and is ignored when `benefit_type` is `FREE`.

### 3.2. Buying a Membership and Bringing It to Life

A membership is created against a plan and a patron and begins life unpaid. Creating a membership records its `plan_id`, its `primary_patron_id` (which, when a patron creates their own membership, must equal `X-User-ID`), an optional `auto_renew` flag (default false), and an optional `donation_cents` add-on. The new membership's `status` is `PENDING_PAYMENT`, its `term_count` begins at 1, and its `grace_until` is null. It carries `started_at` and `expires_at` (the term boundaries, unset until activation), `last_paid_fee_cents` (the fee charged for the most recent activation or renewal), and `version` as its OCC anchor for renewal.

Activation is driven by the payment-settlement hook. When the administrator settles a membership payment with a successful outcome, a membership in `PENDING_PAYMENT` transitions to `ACTIVE`. On that transition the system sets `started_at` to the current clock time and `expires_at` to that instant plus the plan's term length in days; mints the plan's full grant of guest passes as fresh rows in `UNUSED` status under the membership; sets `last_paid_fee_cents` to the activation fee; and fixes `term_count` at 1. The activation fee is the plan's base annual fee — the **initial** fee variant: it equals `annual_fee_cents`, with the term beginning at the activation clock time. If a donation was pending on the membership, the settlement also records it. A membership not in `PENDING_PAYMENT` cannot be activated this way, and an attempt to drive an undefined transition is rejected with `ERR_INVALID_STATE`.

The renewal fee is computed on a different basis from order pricing and comes in three variants keyed to the membership's state at renewal. The base for all three is the plan's `annual_fee_cents`. The **initial** variant, described above, applies at first activation. The **early** variant applies when an `ACTIVE` membership is renewed before it expires, whether by a patron's manual early renewal or by the auto-renew job; the fee is exactly `annual_fee_cents` with no proration, and the new `expires_at` extends from the prior `expires_at` (terms stack) rather than from the current clock. The **lapsed** variant applies when a membership in `GRACE` is reinstated; the fee is `annual_fee_cents` plus the plan's `reinstatement_fee_cents`, and the term restarts from the current clock time rather than stacking. Every renewal writes the resulting amount to `last_paid_fee_cents`.

### 3.3. The Membership Lifecycle: Renewal, Grace, Expiry, and Cancellation

Once active, a membership lives on a cyclic lifecycle. **Early renewal** keeps an `ACTIVE` membership `ACTIVE`: a patron (or the front desk) renews while the clock is still before `expires_at`. Early renewal requires that `expected_membership_version` match the membership's current `version` per Section 2.7; on success it sets the new `expires_at` to the prior `expires_at` plus the plan's term length in days, mints a fresh full grant of guest passes in `UNUSED` status, sets `last_paid_fee_cents` to the early fee, increments `term_count` by one, and increments the membership's `version` by one. An optional `donation_cents` may ride along and is recorded as a donation. The same `ACTIVE → ACTIVE` extension is what the **auto-renew batch job** performs: when run, it renews every `ACTIVE` membership whose `auto_renew` is true and whose `expires_at` is at or before the current clock, applying the early fee variant to each; the job is the version-advancing writer that the OCC rule in Section 2.7 protects against.

When the expiry job runs, an `ACTIVE` membership whose `expires_at` is at or before the current clock and whose `auto_renew` is false moves from `ACTIVE` to `GRACE`. On that transition the system sets `grace_until` to the membership's `expires_at` plus thirty days, and every guest pass of the membership still in `UNUSED` status expires, moving to `EXPIRED`. A membership in `GRACE` can be brought back: **reinstatement renewal** moves it from `GRACE` to `ACTIVE`, and is permitted only while the current clock is at or before `grace_until`. Reinstatement also requires that `expected_membership_version` match the current `version`. On success it sets `started_at` to the current clock time, `expires_at` to the current clock time plus the plan's term length in days, and clears `grace_until` to null; mints a fresh full grant of `UNUSED` guest passes; sets `last_paid_fee_cents` to the lapsed fee (which folds in `reinstatement_fee_cents`); increments `term_count` by one; and increments `version` by one. If the grace window itself elapses — the expiry job finds a `GRACE` membership whose `grace_until` is strictly before the current clock — the membership moves from `GRACE` to `EXPIRED`, and every remaining guest pass in `UNUSED` or `RESERVED` status expires to `EXPIRED`.

Cancellation is available from `PENDING_PAYMENT`, `ACTIVE`, or `GRACE` and is terminal, moving the membership to `CANCELLED`. Cancellation first sets `auto_renew` to false. It then performs the deepest cascade in the system over the membership's guest passes. Each guest pass currently `RESERVED` is released back to `UNUSED` and then immediately expired to `EXPIRED`; releasing it voids the guest ticket linked to that pass and gives back the held capacity, decrementing the reserved count on that order's slot — and on its exhibit session, if the order had one — by the affected party. Separately, each guest pass currently `UNUSED` is expired directly to `EXPIRED`. This release-then-void-then-decrement chain is the three-deep cascade that keeps the guest-pass pool and the slot and session reserved counts consistent when a member walks away mid-reservation. A renewal that targets a membership not in a renewable state, a reinstatement attempted after `grace_until`, or a cancellation of an already-terminal membership are all rejected with `ERR_INVALID_STATE`; a reinstatement past `grace_until` is an undefined transition for that state and is likewise rejected with `ERR_INVALID_STATE`.

The administrator can toggle a membership's `auto_renew` flag directly; toggling it increments the membership's `version` by one. Auto-renew is also a side effect target: cancellation always clears it.

### 3.4. Household Members and the Guest-Pass Pool

A membership may name household members up to the plan's ceiling. Adding a household member records the member's `full_name` and their `relationship` to the primary patron, one of `SPOUSE`, `CHILD`, `PARTNER`, or `OTHER`; the new member references its membership through `membership_id` and is born with `active` true. The household is counted by tallying the household members of the membership whose `active` is true; an add is rejected with `ERR_HOUSEHOLD_FULL` when that active count plus the one being added would exceed the plan's `household_max`. Removing a household member sets its `active` to false rather than deleting it; an inactive member no longer counts against `household_max`, freeing a slot for a future add. Household members can be listed and filtered by `membership_id`.

Guest passes are never created directly; they are minted in batches when a membership activates or renews, as described in the lifecycle above, and they reference their membership through `membership_id`. A guest pass moves through `UNUSED`, `RESERVED`, and `REDEEMED` in the forward direction and ends at `EXPIRED`. A pass carries `reserved_order_id`, the order that currently holds it, which is set while the pass is `RESERVED` or `REDEEMED` and cleared back to null when the pass is released. The pass's `created_at` doubles as the tie-break key when the system must pick which pass to reserve: when an order confirms with guest tickets, the system reserves the oldest `UNUSED` passes first. Guest passes can be read individually, listed and filtered by `membership_id`, by `status`, or by `reserved_order_id`, and a guest pass's linked admission tickets can be listed for that pass.

### 3.5. Building an Admission Order and Its Provisional Quote

An admission order begins as a draft. Creating an order records the buyer's `patron_id` (which, for a patron acting on their own behalf, must equal `X-User-ID`), the `slot_id` naming the general-admission window, an optional `membership_id` (nullable for a walk-up non-member order; when set, member pricing applies to member-type tickets), an optional `exhibit_session_id` (nullable; when set, every ticket on the order carries the special-exhibit surcharge for that session), and an optional `donation_cents` add-on (default 0, at least 0). A new order opens with `status` of `DRAFT`, a `party_size` of 0, and a `quoted_total_cents` equal to its donation amount. The order also carries `final_total_cents`, which stays null until the order confirms. Orders can be read individually and listed and filtered by `patron_id`, `slot_id`, `membership_id`, `exhibit_session_id`, or `status`.

Tickets are added one person at a time while the order is a draft. Each added ticket records its `ticket_type` — one of `MEMBER`, `NON_MEMBER`, `GUEST`, or `RECIPROCAL` — the `person_name` admitted, and, for a reciprocal ticket, the `reciprocal_partner_id` whose benefit applies. A ticket also exposes `order_id` linking it to its order, a system-set `guest_pass_id` populated only for a `GUEST` ticket once a pass is reserved, a computed `price_cents` locked at confirmation, and an admission `state` that begins `ACTIVE` and later becomes `SCANNED` or `VOIDED`. Adding a ticket increments the order's `party_size` by one and recomputes the provisional quote. The order's donation can also be edited on a draft; updating `donation_cents` recomputes the provisional quote and increments the order's `version` by one. Tickets can be read individually and listed and filtered by `order_id`, `guest_pass_id`, or `reciprocal_partner_id`.

The **provisional quote** is written to `quoted_total_cents` while the order is `DRAFT`, and it is recomputed every time a ticket is added or the donation is edited. It is an estimate and is not authoritative. The quote prices each ticket by type and sums the results, then adds the donation. A `MEMBER` ticket is quoted at the plan's `member_admission_cents` even when the linked membership is not yet `ACTIVE` — the quote optimistically assumes the membership will be active by confirmation. A `NON_MEMBER` ticket is quoted at the slot's `non_member_admission_cents`. A `GUEST` ticket is quoted at 0, because its admission is covered by a guest pass. A `RECIPROCAL` ticket is quoted from its partner: when the partner's `benefit_type` is `FREE` the base is 0, and when it is `DISCOUNT` the base is the slot's `non_member_admission_cents` multiplied by one minus the partner's `discount_pct`, rounded half-up to whole cents. To each ticket's base the system adds the special-exhibit surcharge as described in Section 3.6, sums the per-ticket prices after their individual rounding, and adds `donation_cents` to reach the quote.

### 3.6. Confirming an Order: Final Pricing, Capacity, and Reservations

Confirmation turns a draft into a committed booking and is the moment pricing becomes authoritative. A draft order confirms to `CONFIRMED` only after a sequence of checks, and only those checks, all of which fire on the confirm operation. They are evaluated in the following order. First, the membership-and-ownership and existence checks of Section 2 apply as everywhere else. Then come the confirm-specific guards, in priority order: **ticket eligibility** first, then **membership-active**, then the **slot window**, then **slot overlap**, then the **exhibit buffer**, then **guest-pass availability**, and finally **slot and session capacity**.

Ticket eligibility (`ERR_TICKET_ELIGIBILITY`) requires that, if any `MEMBER` ticket is present, the order's `membership_id` is set and the membership's `primary_patron_id` — or one of its active household members — matches; that a `GUEST` ticket appears only on an order whose `membership_id` is set; and that every `RECIPROCAL` ticket carries a `reciprocal_partner_id` that resolves to a partner. Membership-active (`ERR_MEMBERSHIP_NOT_ACTIVE`) requires that, when any `MEMBER` ticket is present, the referenced membership's `status` is `ACTIVE` at confirm time. The slot-window check (`ERR_SLOT_WINDOW`) requires that the slot's `starts_at` is strictly after the current clock — the window must not yet have opened — and additionally requires the slot's `status` to be `OPEN`; a draft on a `CLOSED` slot, or a confirm attempted at or after the window opens, cannot proceed. The slot-overlap check (`ERR_SLOT_OVERLAP`) requires that the patron has no other `CONFIRMED` or `CHECKED_IN` order whose slot window overlaps this slot's window, where windows are treated as half-open intervals from `starts_at` (inclusive) to `ends_at` (exclusive) so that two back-to-back windows touching only at an endpoint are allowed. The exhibit-buffer check (`ERR_EXHIBIT_BUFFER_CONFLICT`) applies only when the order has an `exhibit_session_id`: the patron must have no other booked exhibit session within `buffer_minutes` of this order's session window, where the buffer is a closed interval so that a booking exactly `buffer_minutes` away is disallowed — deliberately distinct interval semantics from the half-open slot-overlap test. Guest-pass availability (`ERR_NO_GUEST_PASS`) requires that the membership hold at least one `UNUSED` guest pass for each `GUEST` ticket on the order; an empty pool rejects. Capacity (`ERR_SLOT_CAPACITY`) requires that the slot's current `reserved_count` plus this order's `party_size` not exceed the slot's `capacity_total`, and, when the order has an exhibit session, that the session's `reserved_count` plus `party_size` not exceed the session's `capacity_total`; reaching the limit exactly is allowed and only exceeding it rejects. Confirming an order that is not in `DRAFT` is rejected with `ERR_INVALID_STATE`. Throughout, at least one ticket must be present — the party size must be one or more — for the order to confirm.

When all checks pass, the order moves to `CONFIRMED` and the **final price** is locked. Final pricing follows the same per-ticket structure as the provisional quote, with two differences. First, `MEMBER` pricing is honored only because the membership-active guard has already guaranteed the membership is `ACTIVE`; a `MEMBER` ticket is priced at the plan's `member_admission_cents`. Second, a `RECIPROCAL` ticket uses the partner's `discount_pct` as it stands at confirm time. As in the quote, a `NON_MEMBER` ticket is priced at the slot's `non_member_admission_cents`, a `GUEST` ticket is priced at 0, and a `RECIPROCAL` ticket is priced at 0 when its partner's `benefit_type` is `FREE` or at the slot's `non_member_admission_cents` times one minus the partner's `discount_pct`, rounded half-up to whole cents, when the partner's `benefit_type` is `DISCOUNT`.

The **special-exhibit surcharge** is then applied per ticket and only when the order carries an `exhibit_session_id`; absent a session the surcharge contributes nothing. For a `GUEST`, `NON_MEMBER`, or `RECIPROCAL` ticket the surcharge is the exhibit's full `surcharge_cents`. For a `MEMBER` ticket the surcharge depends on the plan: if the plan's `exhibit_surcharge_waived` is true the surcharge is 0, and otherwise it is the exhibit's `surcharge_cents` multiplied by one minus the exhibit's `member_surcharge_discount_pct`, rounded half-up to whole cents. Each ticket's `price_cents` is its base plus its surcharge, each component already rounded to whole cents. The order's admission subtotal is the sum of the per-ticket `price_cents` after that per-ticket rounding, and `final_total_cents` is that subtotal plus the order's `donation_cents`.

Confirmation also commits the reservations atomically. The slot's `reserved_count` increases by the order's `party_size` and the slot's `version` increments by one; if the order has a session, the session's `reserved_count` increases by `party_size` as well. Each `GUEST` ticket reserves one guest pass, moving the oldest available pass from `UNUSED` to `RESERVED`, stamping its `reserved_order_id` with the order's id and the ticket's `guest_pass_id` with the pass's id. If the order's `donation_cents` is greater than 0, a donation receipt is created carrying the order's id.

### 3.7. Check-In, Cancellation, and Refund

A confirmed order is admitted through check-in, performed by the front desk or a gate scanner. Check-in moves the order from `CONFIRMED` to `CHECKED_IN` and is permitted only within the entry window — the slot's `starts_at` at or before the current clock and the current clock strictly before the slot's `ends_at`; outside that window the check-in is rejected with `ERR_SLOT_WINDOW`. On check-in every still-`ACTIVE` ticket on the order moves to `SCANNED`, and every guest pass `RESERVED` against the order moves to `REDEEMED`. Checking in an order not in `CONFIRMED` is rejected with `ERR_INVALID_STATE`.

Cancellation branches by the order's state, and the two branches differ in their cascades. Cancelling a `DRAFT` order moves it to `CANCELLED` and voids all of its tickets; because a draft never held capacity, no reserved count changes. Cancelling a `CONFIRMED` order moves it to `CANCELLED` and runs the full release: every still-`ACTIVE` ticket moves to `VOIDED`; voiding the tickets decrements the slot's `reserved_count` by the order's `party_size` and, if the order had a session, the session's `reserved_count` by `party_size`; and every guest pass `RESERVED` against the order returns to `UNUSED` with its `reserved_order_id` cleared to null. A cancel attempted on an order that is neither `DRAFT` nor `CONFIRMED` is rejected with `ERR_INVALID_STATE`.

Refund is the post-visit reversal, available only to the front desk and only on a `CHECKED_IN` order. Refunding moves the order to `REFUNDED`, voids all of its tickets, releases the held capacity by decrementing the slot's `reserved_count` by `party_size` (and the session's `reserved_count` by `party_size` when a session was set), and expires every `REDEEMED` guest pass of the order to `EXPIRED` — a redeemed pass has been consumed and is not returned to the pool. Refunding an order not in `CHECKED_IN` is rejected with `ERR_INVALID_STATE`.

A ticket's own state mirrors these flows. A ticket is `ACTIVE` from creation, becomes `SCANNED` when its order checks in, and becomes `VOIDED` when its order is cancelled or refunded or when a guest ticket's pass is released by a membership cancellation. In that last case — a guest ticket voided because the membership that owns its pass was cancelled while the order remained `CONFIRMED` — the void additionally decrements that order's slot `reserved_count` by one for the single freed seat, which is the third level of the membership-cancellation cascade described in Section 3.3.

### 3.8. Donations and the Operational Clock and Jobs

A donation is an immutable receipt of a captured charitable amount. Donations are never posted on their own; one rides along either on an order or on a membership transaction. When an order whose `donation_cents` is greater than 0 confirms, a donation is written with that `amount_cents` and the order's id in `order_id` (its `membership_id` left null). When a membership activation or renewal carries a donation, a donation is written with the `membership_id` set (its `order_id` left null). A donation row carries only `id`, `created_at`, `order_id`, `membership_id`, and `amount_cents`, and is never modified after it is written. Donations can be read individually and listed and filtered by `order_id` or `membership_id`.

The system runs on a logical clock so that time-dependent behavior is deterministic. An administrator-only capability advances that clock to a supplied instant, given as `to_iso8601`, after which every "current clock" comparison in this document evaluates against the new instant. A second administrator-only capability is the payment-settlement hook, which takes a `target` (the kind of thing being paid for, `MEMBERSHIP` for an activation), a `membership_id`, and an `outcome`; a settlement whose `target` is a membership and whose `outcome` is `SUCCEEDED` drives that membership from `PENDING_PAYMENT` to `ACTIVE` and runs the activation side effects of Section 3.2. The renewal batch job reports a `renewed_count` and the `renewed_membership_ids` it touched; the expiration batch job reports a `graced_count` and an `expired_count`. The renewal job advances every eligible `auto_renew` membership through the early-renewal extension, and the expiration job applies the `ACTIVE → GRACE` and `GRACE → EXPIRED` transitions with their guest-pass cascades, all as detailed in Section 3.3.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`. Operations that modify an existing resource — including state transitions, toggles, household removal, and the administrative clock, payment, and job hooks — return `200 OK`. All reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/patrons` | Create a patron account | BoxOffice, MembershipAdmin |
| GET | `/patrons/{id}` | Read a patron | Patron, BoxOffice, MembershipAdmin |
| GET | `/patrons` | List patrons (filter by email or home_partner_id) | BoxOffice, MembershipAdmin |
| POST | `/membership-plans` | Create a membership plan (tier) | MembershipAdmin |
| GET | `/membership-plans/{id}` | Read a plan | Patron, BoxOffice, MembershipAdmin |
| GET | `/membership-plans` | List plans | Patron, BoxOffice, MembershipAdmin |
| POST | `/memberships` | Create a membership for a patron on a plan | Patron, BoxOffice, MembershipAdmin |
| GET | `/memberships/{id}` | Read a membership | Patron, BoxOffice, MembershipAdmin |
| GET | `/memberships` | List memberships (filter by plan_id, primary_patron_id, status) | BoxOffice, MembershipAdmin |
| POST | `/memberships/{id}/renew` | Renew a membership (early while ACTIVE, or reinstate while GRACE) | Patron, BoxOffice |
| POST | `/memberships/{id}/cancel` | Cancel a membership | Patron, BoxOffice |
| PATCH | `/memberships/{id}/auto-renew` | Toggle the auto-renew flag | Patron, BoxOffice |
| POST | `/memberships/{id}/household-members` | Add a household member | Patron, BoxOffice |
| GET | `/household-members/{id}` | Read a household member | Patron, BoxOffice, MembershipAdmin |
| GET | `/household-members` | List household members (filter by membership_id) | Patron, BoxOffice, MembershipAdmin |
| DELETE | `/household-members/{id}` | Remove a household member | Patron, BoxOffice |
| GET | `/guest-passes/{id}` | Read a guest pass | Patron, BoxOffice, MembershipAdmin |
| GET | `/guest-passes` | List guest passes (filter by membership_id, status, reserved_order_id) | Patron, BoxOffice, MembershipAdmin |
| GET | `/guest-passes/{id}/tickets` | List tickets linked to a guest pass | Patron, BoxOffice, MembershipAdmin |
| POST | `/timed-entry-slots` | Create a timed-entry slot | MembershipAdmin |
| GET | `/timed-entry-slots/{id}` | Read a slot | Patron, BoxOffice, MembershipAdmin |
| GET | `/timed-entry-slots` | List slots | Patron, BoxOffice, MembershipAdmin |
| POST | `/timed-entry-slots/{id}/close` | Close a slot to new bookings | MembershipAdmin |
| POST | `/special-exhibits` | Create a special exhibit | MembershipAdmin |
| GET | `/special-exhibits/{id}` | Read a special exhibit | Patron, BoxOffice, MembershipAdmin |
| GET | `/special-exhibits` | List special exhibits | Patron, BoxOffice, MembershipAdmin |
| POST | `/special-exhibits/{id}/sessions` | Create a session window under an exhibit | MembershipAdmin |
| GET | `/special-exhibits/{id}/sessions` | List sessions of an exhibit | Patron, BoxOffice, MembershipAdmin |
| GET | `/exhibit-sessions/{id}` | Read an exhibit session | Patron, BoxOffice, MembershipAdmin |
| POST | `/reciprocal-partners` | Create a reciprocal-network partner | MembershipAdmin |
| GET | `/reciprocal-partners/{id}` | Read a reciprocal partner | Patron, BoxOffice, MembershipAdmin |
| GET | `/reciprocal-partners` | List reciprocal partners | Patron, BoxOffice, MembershipAdmin |
| POST | `/admission-orders` | Create a DRAFT admission order | Patron, BoxOffice |
| GET | `/admission-orders/{id}` | Read an order | Patron, BoxOffice, MembershipAdmin |
| GET | `/admission-orders` | List orders (filter by patron_id, slot_id, membership_id, exhibit_session_id, status) | BoxOffice, MembershipAdmin |
| POST | `/admission-orders/{id}/tickets` | Add a ticket to a DRAFT order | Patron, BoxOffice |
| PATCH | `/admission-orders/{id}` | Update donation_cents on a DRAFT order | Patron, BoxOffice |
| POST | `/admission-orders/{id}/confirm` | Confirm a DRAFT order | Patron, BoxOffice |
| POST | `/admission-orders/{id}/check-in` | Check in a CONFIRMED order during its window | BoxOffice, GateScanner |
| POST | `/admission-orders/{id}/cancel` | Cancel a DRAFT or CONFIRMED order | Patron, BoxOffice |
| POST | `/admission-orders/{id}/refund` | Refund a CHECKED_IN order | BoxOffice |
| GET | `/admission-tickets/{id}` | Read a ticket | Patron, BoxOffice, MembershipAdmin |
| GET | `/admission-tickets` | List tickets (filter by order_id, guest_pass_id, reciprocal_partner_id) | Patron, BoxOffice, MembershipAdmin |
| GET | `/donations/{id}` | Read a donation | BoxOffice, MembershipAdmin |
| GET | `/donations` | List donations (filter by order_id, membership_id) | BoxOffice, MembershipAdmin |
| POST | `/_clock/set_current_utc` | Set the server's logical UTC clock | MembershipAdmin |
| POST | `/_payments/settle` | Settle a pending membership payment | MembershipAdmin |
| POST | `/_jobs/run_renewals` | Run the auto-renew batch | MembershipAdmin |
| POST | `/_jobs/run_expirations` | Run the expiry batch | MembershipAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_EMAIL_TAKEN` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_TICKET_ELIGIBILITY` | 409 |
| `ERR_MEMBERSHIP_NOT_ACTIVE` | 409 |
| `ERR_SLOT_WINDOW` | 409 |
| `ERR_SLOT_OVERLAP` | 409 |
| `ERR_EXHIBIT_BUFFER_CONFLICT` | 409 |
| `ERR_NO_GUEST_PASS` | 409 |
| `ERR_SLOT_CAPACITY` | 409 |
| `ERR_HOUSEHOLD_FULL` | 409 |
| `ERR_VALIDATION_PAGINATION` | 422 |
</content>
</invoke>
